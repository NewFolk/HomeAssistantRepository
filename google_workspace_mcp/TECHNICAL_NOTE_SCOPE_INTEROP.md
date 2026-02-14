# OAuth2.1 Scope Interop Fix (MCP vs Google)

## Problem

Some MCP clients request `mcp:tools` during OAuth2.1/DCR.
`workspace-mcp` Google OAuth flow expects Google/OIDC scopes only. If `mcp:tools` is treated as a Google scope, auth can fail with:

- `Requested scopes are not valid: mcp:tools`
- authorization loop / `401` on `/mcp`

## Implemented approach: scope-plane separation

We separated scope handling into two planes inside add-on runtime:

1. Client-facing MCP scope plane
- Local validation accepts MCP scopes configured in `MCP_CLIENT_COMPAT_SCOPES`.
- Default value: `mcp:tools`.

2. Upstream Google scope plane
- Before building Google authorize parameters, scopes are filtered.
- Only Google/OIDC scopes are forwarded upstream (`https://*.googleapis.com/*`, `https://*.google.com/*`, `openid`, `email`, `profile`).
- Client-only MCP scopes are removed before redirecting to Google.

Google token verification remains Google-scope based.

## Where this is implemented

- Patch file: `google_workspace_mcp/patches/sitecustomize.py`
- Loaded via `PYTHONPATH=/opt/google_workspace_mcp_patch` in Docker image.
- Applied at interpreter startup to provider module:
  - `google_mcp.auth.provider` (primary)
  - fallback: `auth.provider`

Patched functions:

- `validate_scopes(...)`: accepts configured client compat scopes in addition to required Google scopes.
- `build_google_auth_params(...)`: removes non-Google/non-OIDC scopes before Google authorize URL generation.

## Operational config

- Add-on option: `client_compat_scopes` (default `mcp:tools`)
- Exported env: `MCP_CLIENT_COMPAT_SCOPES`

## Rollback

1. Checkout previous stable revision/tag.
2. Rebuild/reinstall add-on from that revision.
3. Restart add-on.

Immediate rollback target before this fix: version `0.1.5`.
