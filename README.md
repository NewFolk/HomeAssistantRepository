# Home Assistant Add-ons by NewFolk

This repository contains custom Home Assistant add-ons.

## Available add-ons

- **OpenList** (`openlist`)
  - A file-listing and sharing platform for many storage providers.
  - Includes Home Assistant Ingress, persistent configuration, and access to `/share` and `/media`.
  - Optional administrator auto-login through Ingress (Supervisor 2026.10.2+); direct port stays disabled by default.
  - Current experimental release: OpenList `v4.2.9` on `amd64`.
  - Based on: `OpenListTeam/OpenList`.

- **Google Workspace MCP** (`google_workspace_mcp`)
  - Google Workspace MCP server for Home Assistant OS.
  - Based on: `taylorwilsdon/google_workspace_mcp`
  - Runtime package: `workspace-mcp` (inside add-on container)
  - Automatic tested runtime releases for `amd64` and `aarch64`, including upgrade checks.
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
