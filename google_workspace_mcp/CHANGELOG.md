# Changelog

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
