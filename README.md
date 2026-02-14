# Home Assistant Add-ons by NewFolk

This repository contains custom Home Assistant add-ons.

## Available add-ons

- **Google Workspace MCP** (`google_workspace_mcp`)
  - Google Workspace MCP server for Home Assistant OS.
  - Based on: `taylorwilsdon/google_workspace_mcp`
  - Runtime package: `workspace-mcp` (inside add-on container)
  - No separate MCP host/VM required on this stage.

## Add this repository to Home Assistant

1. Open **Settings → Add-ons → Add-on Store**
2. Open menu (**⋮**) → **Repositories**
3. Add:

   ```
   https://github.com/NewFolk/HomeAssistantRepository
   ```

4. Refresh the add-on store

## Security note

Do not commit OAuth credentials into this repository. Configure secrets only in Home Assistant add-on options.
