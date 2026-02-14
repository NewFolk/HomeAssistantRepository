# Changelog

## 0.1.5

- Added compatibility patch for OAuth scope negotiation with clients like `mcporter` that request `mcp:tools`.
- During image build, the installed `workspace-mcp` scope list is patched to include `mcp:tools` in `BASE_SCOPES`.
- Fixes auth failure: `Requested scopes are not valid: mcp:tools`.

## 0.1.4

- Enabled `host_network: true` so the add-on can bind directly on the HAOS host network.
- This is required for common reverse-proxy setups (e.g. Keenetic/Nginx) that upstream to `HA_HOST:8000`.

## 0.1.3

- Fixed Home Assistant Supervisor validation: `watchdog` now uses full URL format `http://[HOST]:[PORT:8000]/health`.
- Resolves add-on hiding caused by invalid `config.yaml` schema value.

## 0.1.2

- Changed add-on visibility defaults: `advanced: false`, `stage: stable`.
- This makes `google_workspace_mcp` visible in Add-on Store without enabling advanced mode.

## 0.1.1

- Fixed boolean option parsing in `run.sh` to reliably pass `true/false` values to runtime env.
- Set add-on `watchdog` to `/health` (HA watchdog path format).
- Expanded operational docs for security baseline, update flow, and rollback.

## 0.1.0

- Initial release
- Home Assistant add-on wrapper for `workspace-mcp`
- Configurable OAuth/runtime options via add-on configuration
- Persistent credential storage in `/data/credentials`
