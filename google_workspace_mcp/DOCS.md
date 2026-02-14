## Google Workspace MCP add-on

This add-on runs Google Workspace MCP inside Home Assistant.

### 1) Prepare Google OAuth credentials

Create OAuth 2.0 credentials in Google Cloud and copy:

- `oauth_client_id`
- `oauth_client_secret`

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
- `allow_insecure_transport: true`: dev only for non-HTTPS redirect testing

### 3) Start the add-on

After saving options, start/restart the add-on.

The server exposes:

- Health endpoint: `http://<ha-host>:8000/health`

### 4) Connect clients

Use your MCP client to connect to the running endpoint on your HA host.

> If OAuth callback URLs fail, set `oauth_redirect_uri` explicitly to the exact callback URL expected by your Google OAuth app.
