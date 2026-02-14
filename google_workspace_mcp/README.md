# Google Workspace MCP (Home Assistant Add-on)

Home Assistant add-on that runs [`workspace-mcp`](https://github.com/taylorwilsdon/google_workspace_mcp) as a local service.

## What this add-on provides

- Google Workspace MCP endpoint on port `8000`
- Persistent credentials storage in `/data/credentials`
- Configurable OAuth and runtime modes from Home Assistant add-on options

## Notes

- Recommended transport for modern MCP clients: `streamable-http`
- OAuth 2.1 (`enable_oauth21=true`) **cannot** be combined with `single_user_mode=true`

## Upstream project

- https://github.com/taylorwilsdon/google_workspace_mcp
