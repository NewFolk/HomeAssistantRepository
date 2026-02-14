# Changelog

## 0.2.4

- Persist OAuth proxy state on disk (`/data/oauth-proxy`) by default so MCP client auth survives add-on restarts/updates.
- Added `FASTMCP_HOME=/data/fastmcp` to keep FastMCP runtime state under HA persistent storage.
- Added add-on store icon/logo.

## 0.2.3

- Security hardening: switched add-on networking from `host_network: true` to `host_network: false`.
- Restores standard Home Assistant port publishing behavior, so host-side port overrides from Add-on UI work reliably again.
- Updated docs/runbook notes for reverse proxy upstream and port override checks.

## 0.2.2

- Added handler-level compatibility patch for OAuth2.1 registration path:
  - `mcp.server.auth.handlers.register.RegistrationHandler.handle`
- Added init-time valid scope merge patch:
  - `fastmcp.server.auth.oauth_proxy.OAuthProxy.__init__`
- Kept upstream scope sanitization in place:
  - `fastmcp.server.auth.oauth_proxy.OAuthProxy._build_upstream_authorize_url`
- Updated technical note with full post-mortem and effective hook points for this stack.

## 0.2.1

- Fixed scope-interop patch target for `workspace-mcp==1.11.1`:
  - patch now hooks FastMCP internals directly:
    - `fastmcp.server.auth.providers.in_memory.InMemoryClientStore.register_client`
    - `fastmcp.server.auth.oauth_proxy.OAuthProxy._build_upstream_authorize_url`
- Keeps `mcp:tools` valid on client registration plane while ensuring only Google/OIDC scopes are sent upstream to Google authorize endpoint.
- Added post-mortem comments to `TECHNICAL_NOTE_SCOPE_INTEROP.md` about why `0.2.0` patch did not activate.

## 0.2.0

- Implemented OAuth2.1 scope-plane separation for MCP/Google interop.
- Added runtime patch (`patches/sitecustomize.py`) to:
  - accept client-side MCP scopes (default: `mcp:tools`) in local scope validation
  - filter non-Google scopes before upstream Google authorize request
- Added add-on option `client_compat_scopes` (default `mcp:tools`).
- Removed previous build-time patch that inserted `mcp:tools` into Google `BASE_SCOPES`.
- Added technical note: `TECHNICAL_NOTE_SCOPE_INTEROP.md`.

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
