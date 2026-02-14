# Google Workspace MCP (Home Assistant Add-on)

Home Assistant add-on that runs [`workspace-mcp`](https://github.com/taylorwilsdon/google_workspace_mcp) as a local service.

## What this add-on provides

- Google Workspace MCP endpoint on port `8000`
- Persistent credentials storage in `/data/credentials`
- OAuth 2.1 compatible HTTP endpoint for MCP clients (`/mcp`)
- Scope-plane interop for MCP clients that request `mcp:tools`

## Notes

- Recommended transport: `streamable-http`
- `enable_oauth21=true` **cannot** be combined with `single_user_mode=true`
- Use your own Google OAuth app credentials only
- This add-on is designed to run fully inside HAOS

---

## End-to-end setup (recommended)

### 1) Create OAuth client in Google Cloud

Create OAuth 2.0 credentials in your own project.

Use **Web application** client type.

Add this exact Authorized redirect URI:

```text
https://<your-mcp-domain>/oauth2callback
```

Example:

```text
https://mcp.example.com/oauth2callback
```

> Exact match is required (scheme, host, path).

### 2) Configure OAuth consent screen

If app is in **Testing** mode:
- add your Google account to **Test users**

If test-user restrictions block access:
- switch to **In production** for private/self use (you may still see unverified-app warning for sensitive scopes)

### 3) Configure Home Assistant add-on options

Minimum required:

- `oauth_client_id`
- `oauth_client_secret`
- `external_url` = `https://<your-mcp-domain>`

Recommended:

- `transport: streamable-http`
- `enable_oauth21: true`
- `client_compat_scopes: "mcp:tools"`
- `tool_tier: core` (or as needed)
- `tools: "gmail calendar drive docs sheets"`

Optional:

- `oauth_redirect_uri` (leave empty unless you need to force override)

After saving options: **restart add-on**.

### 4) Reverse proxy routing

Forward these paths to backend `http://<ha-host>:8000`:

- `/mcp`
- `/.well-known/*`
- `/authorize`
- `/token`
- `/register`
- `/oauth2callback`
- `/consent`

### 5) Validate endpoints

```bash
curl -fsS https://<your-mcp-domain>/health
curl -fsS https://<your-mcp-domain>/.well-known/oauth-authorization-server
```

Expected:
- `/health` returns JSON with `"status":"healthy"`
- OAuth metadata endpoint returns JSON (not 502)

### 6) Validate Dynamic Client Registration (scope interop)

```bash
curl -fsS -X POST https://<your-mcp-domain>/register \
  -H 'content-type: application/json' \
  --data '{
    "client_name":"probe",
    "redirect_uris":["http://127.0.0.1/callback"],
    "grant_types":["authorization_code","refresh_token"],
    "response_types":["code"],
    "token_endpoint_auth_method":"none",
    "scope":"mcp:tools"
  }'
```

Expected: HTTP `201` with `client_id`.

---

## mcporter/OpenClaw authentication runbook

### 1) Configure MCP target

```bash
npx -y mcporter config add google-workspace \
  https://<your-mcp-domain>/mcp \
  --scope home --auth oauth
```

### 2) (Optional but recommended) Set fixed LAN callback

If you complete consent from another device in the same LAN, set a callback URL reachable from that device:

```bash
npx -y mcporter config add google-workspace \
  https://<your-mcp-domain>/mcp \
  --scope home --auth oauth \
  --oauth-redirect-url http://<ha-lan-ip>:41293/callback
```

### 3) Start auth with longer timeout

```bash
MCPORTER_OAUTH_TIMEOUT_MS=600000 npx -y mcporter auth google-workspace --reset
```

Open the URL printed by `mcporter`, complete Google consent, wait for callback.

> The callback listener exists only while `mcporter auth` is running.

### 4) Verify tools are available

```bash
npx -y mcporter list google-workspace --schema --json
```

---

## Known errors and fixes

### `Requested scopes are not valid: mcp:tools`

- Use add-on version `0.2.2+`
- Ensure `client_compat_scopes` includes `mcp:tools`

### `redirect_uri_mismatch`

- Add exact URI in Google OAuth client:
  `https://<your-mcp-domain>/oauth2callback`

### `access_denied` / app not verified / tester restrictions

- Add current account to OAuth **Test users**, or
- Switch app audience status to **In production** for private/self use

### `invalid_client: Unauthorized` (token exchange)

- Usually wrong `oauth_client_secret` or mismatched client pair
- Re-copy exact `client_id` and `client_secret` from the same OAuth client

### `OAuth authorization ... timed out`

- Increase timeout:
  `MCPORTER_OAUTH_TIMEOUT_MS=600000`

### `mcporter auth` ends with SSE 400 after tokens were saved

If logs show:
- authorization code received
- tokens saved

...this can be a post-auth transport artifact. Confirm by running:

```bash
npx -y mcporter call google-workspace.list_calendars --output json
```

If tool call succeeds, OAuth is complete.

---

## Minimal smoke tests

```bash
npx -y mcporter call google-workspace.list_calendars --output json
npx -y mcporter call google-workspace.search_gmail_messages query="in:inbox" page_size=1 --output json
npx -y mcporter call google-workspace.search_drive_files query="trashed=false" page_size=1 --output json
```

---

## Upstream project

- https://github.com/taylorwilsdon/google_workspace_mcp
