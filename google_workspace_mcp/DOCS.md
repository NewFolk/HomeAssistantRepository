## Google Workspace MCP add-on

This add-on runs Google Workspace MCP inside Home Assistant.

### 1) Prepare Google OAuth credentials

Create OAuth 2.0 credentials in your own Google Cloud project and copy:

- `oauth_client_id`
- `oauth_client_secret`

Use only your own OAuth client. Do not use third-party/shared OAuth apps.

### 2) Configure add-on options

Required:

- `oauth_client_id`
- `oauth_client_secret`

Recommended defaults:

- `transport: streamable-http`
- `tool_tier: core`
- `tools: "gmail calendar drive docs sheets"`
- `enable_oauth21: true`

Optional:

- `oauth_redirect_uri`: force a specific callback URL
- `external_url`: public/LAN URL used in server metadata
- `user_google_email`: default email for single-user auth
- `client_compat_scopes`: client-facing MCP scopes accepted locally (default: `mcp:tools`)
- `allow_insecure_transport: true`: dev only for non-HTTPS redirect testing

### 3) Start the add-on

After saving options, start/restart the add-on.

The server exposes:

- Health endpoint: `http://<ha-host>:8000/health`

### 4) Connect clients

Use your MCP client to connect to the running endpoint on your HA host.

- LAN/direct: `http://<ha-host>:8000/mcp`
- Reverse proxy (HTTPS): `https://<your-domain>/mcp`

> If OAuth callback URLs fail, set `oauth_redirect_uri` explicitly to the exact callback URL expected by your Google OAuth app.

### 5) Reverse proxy quick checks

If you use `external_url` with HTTPS domain, make sure the proxy forwards these paths to backend `http://<ha-host>:8000`:

- `/mcp`
- `/.well-known/*`
- `/authorize`
- `/token`
- `/register`
- `/oauth2callback`

A quick check:

- `https://<your-domain>/health` must return `200`
- `https://<your-domain>/.well-known/oauth-authorization-server` must return JSON (not 502)

### 6) OAuth troubleshooting

If your MCP client fails auth with:

- `Requested scopes are not valid: mcp:tools`

use add-on version `0.2.1+`.
This release introduces scope-plane separation:

- client-plane accepts MCP scopes such as `mcp:tools`
- upstream Google authorize request receives only Google/OIDC scopes

So `mcp:tools` is no longer forwarded to Google.

### 7) Security baseline

- Never store or commit OAuth secrets in Git.
- Start with minimum tools/APIs only (for example: `gmail calendar drive`).
- Keep `read_only_mode: true` for initial smoke testing if you want read-only access first.
- Keep `allow_insecure_transport: false` in production.

### 8) Updates and rollback

- For each release: increase `version` in `config.yaml` and add an entry to `CHANGELOG.md`.
- To rollback, checkout the previous git tag/commit and reinstall or rebuild the add-on from that revision.

### 9) E2E verification checklist

- Run `mcporter auth <your-server-url>` and complete browser consent.
- Confirm there is no 401 auth loop on `/mcp`.
- Run `mcporter list --schema` and verify tools are listed.
- Execute read-only smoke tests for Gmail, Calendar, Drive.
- Restart add-on and repeat `mcporter list --schema` to verify stable session behavior.
