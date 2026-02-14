# Google Workspace MCP (Home Assistant Add-on)

Home Assistant add-on that runs [`workspace-mcp`](https://github.com/taylorwilsdon/google_workspace_mcp) as a local service.

## What this add-on provides

- Google Workspace MCP endpoint on port `8000`
- Persistent credentials storage in `/data/credentials`
- Configurable OAuth and runtime modes from Home Assistant add-on options

## Notes

- Recommended transport for modern MCP clients: `streamable-http`
- OAuth 2.1 (`enable_oauth21=true`) **cannot** be combined with `single_user_mode=true`
- Use your own Google OAuth app credentials only
- This add-on is designed to run fully inside HAOS without a separate MCP host
- OAuth scope-plane interop is enabled: client scopes like `mcp:tools` are accepted locally, while Google receives only Google/OIDC scopes

## Upstream project

- https://github.com/taylorwilsdon/google_workspace_mcp
