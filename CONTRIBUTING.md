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
sh -n openlist/run.sh google_workspace_mcp/run.sh
shellcheck openlist/run.sh google_workspace_mcp/run.sh openlist/tests/smoke.sh
docker build --platform linux/amd64 -t local/openlist-addon:test ./openlist
upstream_version="$(sed -nE 's|^FROM .*openlist:(v[^@]+)@sha256:.*$|\1|p' openlist/Dockerfile)"
./openlist/tests/smoke.sh local/openlist-addon:test "${upstream_version}"
```

The smoke test builds confidence that the container starts, becomes healthy, serves HTTP, reports the expected upstream version, and reuses its persistent data. It does not replace testing inside Home Assistant.
