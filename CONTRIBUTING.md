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
sh -n openlist/run.sh openlist/prepare-config.sh google_workspace_mcp/run.sh
shellcheck openlist/run.sh openlist/prepare-config.sh google_workspace_mcp/run.sh openlist/tests/smoke.sh
python3 -m unittest discover -s scripts -p 'test_*.py'
docker build --platform linux/amd64 -t local/openlist-addon:test ./openlist
upstream_version="$(sed -nE 's|^FROM .*openlist:(v[^@]+)@sha256:.*$|\1|p' openlist/Dockerfile)"
./openlist/tests/smoke.sh local/openlist-addon:test "${upstream_version}"
python3 openlist/tests/ingress-auth-smoke.py local/openlist-addon:test
```

The smoke test builds confidence that the container starts, becomes healthy, serves its direct UI, rewrites the simulated Home Assistant Ingress path for frontend assets and API calls, reports the expected upstream version, and reuses its persistent data. It does not replace testing inside Home Assistant.

## Ingress authentication trust boundary

`ingress_auto_login` defaults to false. When enabled, `panel_admin: true` is a security boundary, not just a sidebar preference. Supervisor 2026.10.2 is the first supported version: [upstream enforcement change](https://github.com/home-assistant/supervisor/pull/7308). The add-on checks the stable Supervisor version through the already permitted `/info` endpoint before starting auto-login; do not remove this check or substitute trust in a client-provided role/name header. No `hassio_api`, `homeassistant_api`, `auth_api`, host networking or privileged role is needed.

nginx's internal auth subrequest forwards its actual peer IP, HA user ID, original method, host/protocol and Origin to a loopback-only Python helper. The helper reads the existing admin token from SQLite in read-only mode, requires an active OpenList administrator, and returns that token only to the internal nginx subrequest. nginx replaces the client's Authorization header on the upstream request; it does not issue a browser session. Do not expose port 8098, turn the internal auth location into a public endpoint, log the returned token or replace the native frontend's `/api/me` request with a browser-token injection.

Helper tests cover version rejection, opt-in configuration, read-only access, rotation, identity/peer checks and Origin checks. The separate auth smoke uses a mock `/info` server at Supervisor's real IP on an isolated Docker network, exercises the actual OpenList admin API without browser credentials, rejects forged/direct/missing-identity requests, tests old-Supervisor failure and restores password mode on the same data directory. The mock does **not** implement HA sessions or prove HA's admin/non-admin authorization. Before marking the feature stable, test real HA with admin/non-admin accounts, password mode, logout, token rotation, WebSockets, uploads and proxy/HTTPS Origins.

## Automated OpenList patch releases

CI builds the add-on linter from pinned upstream commit `b9cfd1bc62ba60d2c4fc96317b5f7ada5923f4a7`. Its JSON schema receives one compatibility fix: accept the official Supervisor `schema: false` mode as well as object schemas. All other upstream lint checks remain enabled. Update this pinned checkout manually when adopting a new linter release, and remove the fix when upstream supports it.

The `Update OpenList` workflow checks the latest stable upstream release daily at 07:23 UTC and can also be run manually in Actions. It pins the image digest, checks for a linux/amd64 image, increments the HA package patch version, and updates documentation and changelog together.

Only newer releases in the same upstream major/minor series are automatic. Prereleases, downgrades, and major/minor upgrades are rejected. Other Dependabot PRs still require review; in particular, the current CI does not build or run Google Workspace MCP, so a green check does not validate a Python runtime upgrade.

The workflow opens a PR, calls the complete CI workflow on its exact commit with read-only permissions, then merges only if validation succeeds and main has not changed. Failed runs leave the PR open. It uses GITHUB_TOKEN; GitHub does not trigger ordinary push/PR workflows for that token, so the explicit reusable CI call is the validation gate. No personal access token is needed. Repository Actions settings must allow GitHub Actions to create pull requests.

Merging publishes an add-on update to the repository. Installation on a Home Assistant instance is controlled separately by that instance's update settings.
