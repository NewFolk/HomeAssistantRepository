# OAuth2.1 Scope Interop Fix (MCP vs Google)

## Problem

Some MCP clients request `mcp:tools` during OAuth2.1/DCR.
`workspace-mcp` Google OAuth flow expects Google/OIDC scopes only. If `mcp:tools` is treated as a Google scope, auth can fail with:

- `Requested scopes are not valid: mcp:tools`
- authorization loop / `401` on `/mcp`

## Implemented approach: scope-plane separation

We separate scope handling into two planes inside add-on runtime:

1. Client-facing MCP scope plane
- Local client registration validation accepts MCP scopes configured in `MCP_CLIENT_COMPAT_SCOPES`.
- Default value: `mcp:tools`.

2. Upstream Google scope plane
- Before building Google authorize URL, scopes are filtered.
- Only Google/OIDC scopes are forwarded upstream (`https://*.googleapis.com/*`, `https://*.google.com/*`, `openid`, `email`, `profile`).
- Client-only MCP scopes are removed before redirecting to Google.

Google token verification remains Google-scope based.

---

## Important post-mortem note (0.2.0 -> 0.2.1)

### What was wrong in 0.2.0

`0.2.0` attempted to patch provider modules:

- `google_mcp.auth.provider` (primary)
- `auth.provider` (fallback)

In `workspace-mcp==1.11.1` these modules are not part of the actual OAuth2.1 validation path used at runtime, so the patch did not affect the failing code path.

### What was changed in 0.2.1

Patch now targets the real FastMCP internals used by this runtime:

- `fastmcp.server.auth.providers.in_memory.InMemoryClientStore.register_client`
  - extends local valid scope set with `MCP_CLIENT_COMPAT_SCOPES` (e.g. `mcp:tools`)
- `fastmcp.server.auth.oauth_proxy.OAuthProxy._build_upstream_authorize_url`
  - filters non-Google scopes before upstream redirect to Google

This is the effective interception point for this version stack.

---

## Where this is implemented

- Patch file: `google_workspace_mcp/patches/sitecustomize.py`
- Loaded via `PYTHONPATH=/opt/google_workspace_mcp_patch` in Docker image.
- Applied at interpreter startup.

## Operational config

- Add-on option: `client_compat_scopes` (default `mcp:tools`)
- Exported env: `MCP_CLIENT_COMPAT_SCOPES`

## Verification checklist

1. `POST /register` with `scope=mcp:tools` no longer returns `invalid_client_metadata`.
2. `mcporter auth <server>` reaches browser consent and completes.
3. `/mcp` no longer stuck in auth loop after successful login.
4. Google authorize request contains only Google/OIDC scopes.

## Rollback

1. Checkout previous stable revision/tag.
2. Rebuild/reinstall add-on from that revision.
3. Restart add-on.

Immediate rollback target before this fix: version `0.2.0` (or `0.1.5` if needed).
