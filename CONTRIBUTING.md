# Contributing

Create changes on a feature branch and submit a pull request to `main`. Do not merge while required CI checks are failing.

For every add-on change:

1. Pin upstream container images and application dependencies to a released version. Prefer an immutable digest in addition to a readable version tag.
2. Keep `config.yaml`, `Dockerfile`, documentation, and the changelog consistent.
3. Increment the add-on version whenever a published container or Home Assistant metadata changes.
4. Advertise only architectures that CI builds and tests.
5. Keep a new add-on `experimental` until installation, startup, Ingress, mounts, backup, restore, and upgrade have been verified on Home Assistant.
6. Never commit credentials or generated application data.

Before opening a pull request, run the same checks used by CI when the required tools are available:

```bash
git diff --check
python3 -m pip install -r openlist/tests/requirements.txt
sh -n openlist/run.sh openlist/prepare-config.sh google_workspace_mcp/run.sh
shellcheck openlist/run.sh openlist/prepare-config.sh google_workspace_mcp/run.sh openlist/tests/smoke.sh
python3 -m unittest discover -s scripts -p 'test_*.py'
docker build --platform linux/amd64 -t local/openlist-addon:test ./openlist
upstream_version="$(sed -nE 's|^FROM .*openlist:(v[^@]+)@sha256:.*$|\1|p' openlist/Dockerfile)"
./openlist/tests/smoke.sh local/openlist-addon:test "${upstream_version}"
python3 openlist/tests/ingress-auth-smoke.py local/openlist-addon:test
docker build -t local/google-workspace-mcp:test ./google_workspace_mcp
python3 google_workspace_mcp/tests/smoke.py local/google-workspace-mcp:test
```

The smoke test builds confidence that the container starts, becomes healthy, serves its direct UI, rewrites the simulated Home Assistant Ingress path for frontend assets and API calls, reports the expected upstream version, and reuses its persistent data. It does not replace testing inside Home Assistant.

Google Workspace MCP is built and smoke-tested on native amd64 and aarch64 runners.
Its separate test uses synthetic OAuth credentials to check the installed Python,
package dependencies, actual scope-filtering hooks, discovery, client registration,
rejection of unsupported scopes and unauthenticated MCP requests, real token
rotation/retry/expiry behavior with only the Google transport mocked, and client
persistence across container recreation. PRs and the Google updater also build
the exact published baseline and verify its registered client survives upgrading
on the same data volume. It does not sign in to Google or call a Google tool;
those still need an authenticated integration check when changing OAuth behavior.

## Supervisor option persistence contract

Use real supported schemas: `ingress_auto_login: bool` and `openlist: str`, with matching defaults. Advanced settings are stored as a YAML/JSON string (`openlist: |`), decoded by `parse-options.py` with PyYAML's safe loader into a private temporary JSON document, then merged by the existing jq filter. Never rewrite Supervisor's `/data/options.json`, dump its values on parse failure, or replace the persistent OpenList source with overrides.

After upstream becomes ready, `parse-options.py --verify` walks the user-supplied paths and compares them with the working config rewritten by OpenList's typed decoder. Only then does Ingress start. This must not be reduced to comparing our own merge output: that would falsely accept unknown keys. The actual-image smoke test deliberately supplies a misspelled field to guard this upstream rewrite contract on upgrades. Object defaults may be added, including inside arrays; user-provided values/types must match. Log field paths, not values. This is not a guarantee of every setting's runtime semantics.

`schema: false` is **not** an arbitrary-dictionary escape hatch. In Supervisor 2026.10.2, `AppModel.options_schema()` turns boolean schemas into `{}` and `AppOptions` drops every unrecognized key during both saving and writing options. Empty nested schemas similarly discard unknown nested keys. A container test that writes options.json directly misses this boundary.

CI checks out Supervisor commit `c9e000812b7131fa1f1b72b483555083929d7f83` (2026.10.2) and runs `openlist/tests/supervisor-options.py` with Python 3.14 and its pinned PyYAML/voluptuous versions. The test executes the actual upstream option validator and schema factory, stubbing only unrelated hardware/CoreSys imports. It reproduces the false-schema data loss, checks typed-schema JSON save/reload including the auto-login switch, then feeds validated settings into the built image and recreates it after saves made while running and stopped. Verify options are unchanged, settings apply/remove and the persistent source checksum remains unchanged. This contract test is not a running Supervisor REST server or frontend test; real HA Save/reload still needs user confirmation.

To run it locally with a checkout of the pinned Supervisor revision and the built image:

```bash
python3.14 -m pip install -r openlist/tests/requirements.txt
python3.14 openlist/tests/supervisor-options.py /path/to/supervisor local/openlist-addon:test
```

## Ingress authentication trust boundary

`ingress_auto_login` defaults to false. When enabled, Supervisor's `panel_admin: true` default is a security boundary, not just a sidebar preference. Keep that property omitted (the linter rejects redundant defaults); never set it to false. Supervisor 2026.10.2 is the first supported version: [upstream enforcement change](https://github.com/home-assistant/supervisor/pull/7308). The add-on checks the stable Supervisor version through the already permitted `/info` endpoint before starting auto-login; do not remove this check or substitute trust in a client-provided role/name header. No `hassio_api`, `homeassistant_api`, `auth_api`, host networking or privileged role is needed.

Follow [HA's Ingress guide](https://contributors.home-assistant.io/apps/guides/ingress/) and its Supervisor-only access model (also used by [Node-RED](https://github.com/hassio-addons/app-node-red/blob/main/node-red/rootfs/etc/nginx/templates/ingress.gtpl)). HA/Supervisor owns browser-session authentication and admin-panel authorization. The [HA frontend](https://github.com/home-assistant/frontend/blob/dev/src/data/hassio/ingress.ts) creates the Ingress cookie with `SameSite=Strict` and `Secure` on HTTPS; [Supervisor](https://github.com/home-assistant/supervisor/blob/c9e000812b7131fa1f1b72b483555083929d7f83/supervisor/api/ingress.py) validates the session and enforces `panel_admin` before proxying. Do not treat a browser header, external hostname or Ingress path alone as authentication.

nginx's internal auth subrequest forwards only its actual peer IP and Supervisor's HA user ID to a loopback-only Python helper, with original request headers disabled. The helper reads the existing admin token from SQLite in read-only mode, requires an active OpenList administrator, and returns that token only to the internal nginx subrequest. This is an OpenList credential adapter, not a second HA session system. nginx replaces the client's Authorization header on the upstream request; it does not issue a browser session. Do not expose port 8098, turn the internal auth location into a public endpoint, log the returned token or replace the native frontend's `/api/me` request with a browser-token injection.

Do not add an independent Origin/Fetch Metadata allowlist on top of authenticated Ingress. The 1.4.2 policy failed behind proxies stripping Origin and was removed in 1.4.3 at the user's request to use the standard Ingress boundary. This is delegation to HA's session/security implementation, not a claim that requests from arbitrary peers or unsigned client headers are safe. Do not request broad Core API permission to discover an external URL. Never log request/header values or put actual Ingress URLs in source, fixtures or reports.

Helper tests cover version rejection, opt-in configuration, read-only access, rotation and identity/peer checks. The separate auth smoke uses a mock `/info` server at Supervisor's real IP on an isolated Docker network, exercises actual OpenList admin writes and filesystem access without browser-origin headers, rejects a second untrusted container even with forged identity/peer/browser headers, tests old-Supervisor failure and restores password mode on the same data directory. The mock does **not** implement HA sessions or prove HA's admin/non-admin authorization or cookie behavior. Before marking the feature stable, test real HA with admin/non-admin accounts, password mode, logout, token rotation, WebSockets, uploads and external HTTPS access.

## Automated OpenList releases

CI builds the add-on linter from pinned upstream commit `b9cfd1bc62ba60d2c4fc96317b5f7ada5923f4a7` without modifying its schema or disabling checks. Update this pinned checkout manually when adopting a new linter release.

The `Update OpenList` workflow checks the latest stable upstream release daily at 07:23 UTC and can also be run manually in Actions. Stable patch, minor and major releases are eligible. It pins the image digest, checks for a linux/amd64 image, increments the HA package patch version, and updates documentation and changelog together.

Prereleases and downgrades are excluded. Every eligible release must pass the complete runtime CI; there is no manual major/minor approval gate. Python runtime upgrades must pass Google Workspace MCP's own build and upgrade tests; OpenList checks alone do not validate that runtime.

The workflow opens a PR, calls the complete CI workflow on its exact commit with read-only permissions, then merges only if validation succeeds and main has not changed. Failed runs leave the PR open. The explicit reusable CI call is the validation gate and runs automatically without PR workflow approval. GitHub can also create a separate approval-required `pull_request` CI run for PRs opened with GITHUB_TOKEN; that duplicate run does not need manual approval for the updater to validate and merge its tested commit. See [GITHUB_TOKEN workflow triggers](https://docs.github.com/en/actions/concepts/security/github_token). No personal access token is needed. Repository Actions settings must allow GitHub Actions to create pull requests.

Merging publishes an add-on update to the repository. Installation on a Home Assistant instance is controlled separately by that instance's update settings.

## Automated Google Workspace MCP releases

`Update Google Workspace MCP` runs daily at 08:17 UTC and supports manual dispatch.
The metadata-only prepare job selects the highest stable three-part versions of
workspace-mcp, FastMCP and MCP with non-yanked wheels on PyPI. It also refreshes the
latest stable Python major/minor slim tag from Docker's official image manifest,
pins its immutable digest, and verifies linux/amd64 and linux/arm64 manifests. It never installs or executes
the candidate packages with write permissions. Dockerfile pins, add-on version,
README release/runtime lines and changelog are updated as one release.

The updater follows the same PR/exact-commit/read-only-CI/unchanged-main merge gate
as OpenList. Its reusable CI additionally receives the exact published base SHA
for both native Google upgrade tests. Only a successful full validation can reach
the merge job; failure leaves a reviewable PR and the published release unchanged.
Package and Python branch major/minor releases are eligible because the user
authorized broad automated upgrades. Compatibility-code adaptations remain
maintainer changes with their own validation. The updater never edits tests or
runtime hooks to make an incompatible candidate pass. Docker Dependabot for this
add-on is replaced by this coordinated updater; GitHub Actions Dependabot remains.

## Automatic Dependabot merging

Dependabot checks all configured GitHub Actions daily at 06:29 UTC, including
weekends, with no cooldown or major/minor/patch restrictions. `Merge Dependabot
updates` reacts to completed CI and scans every 15 minutes. All same-repository,
non-draft Dependabot PRs targeting the default branch are eligible; neither a
dependency allowlist nor SHA-only references are required. Major releases and
tag-based updates use the same full-CI gate.

The controller is downloaded only from the trusted default branch and never
executes PR code with its write token. It refreshes a stale Dependabot branch,
then reuses complete successful CI for the exact head or dispatches CI on a
temporary reference to that head. Explicit dispatch avoids approval-required
duplicate bot PR runs and includes published-baseline upgrade checks. All jobs
must succeed; failed jobs get one automatic retry. The head and default branch
are checked again before a SHA-guarded merge, followed by published-main CI.
Conflicts or persistently failing tests remain visible without publishing them.

All three publishers share a merge concurrency group. If main advances while an
add-on update is being validated, its workflow automatically queues a fresh run
and closes only the unchanged superseded attempt. No user approval, personal token,
or running Codex session is needed for these GitHub workflows. HA installation
and unrelated human/fork PRs retain their own controls.
