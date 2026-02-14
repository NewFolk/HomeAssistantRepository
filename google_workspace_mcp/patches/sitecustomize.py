"""Runtime patch for MCP/Google OAuth scope interop.

Why this exists:
- Some MCP clients request client-facing scopes like `mcp:tools` during DCR/auth.
- FastMCP's Google OAuth proxy validates client scopes against Google required scopes.
- That can reject valid MCP clients before Google auth even begins.

This patch enforces scope-plane separation:
1) Client-facing MCP scope plane:
   - local client registration validation accepts configured compat scopes.
2) Upstream Google scope plane:
   - only Google/OIDC scopes are forwarded to Google authorize endpoint.
"""

from __future__ import annotations

import importlib
import os
import sys
from typing import Iterable
from urllib.parse import urlparse

OIDC_SCOPES = {"openid", "email", "profile"}


def _read_scope_set(env_name: str, default_value: str) -> set[str]:
    raw = os.getenv(env_name, default_value)
    items = raw.replace(",", " ").split()
    return {item.strip() for item in items if item.strip()}


CLIENT_COMPAT_SCOPES = _read_scope_set("MCP_CLIENT_COMPAT_SCOPES", "mcp:tools")


def _is_google_or_oidc_scope(scope: str) -> bool:
    if scope in OIDC_SCOPES:
        return True
    if not scope.startswith("https://"):
        return False
    parsed = urlparse(scope)
    host = (parsed.hostname or "").lower()
    return host.endswith("googleapis.com") or host.endswith("google.com")


def _filter_google_scopes(scopes: Iterable[str]) -> list[str]:
    return [scope for scope in scopes if _is_google_or_oidc_scope(scope)]


def _patch_fastmcp_inmemory_store() -> bool:
    """Patch FastMCP client registration scope validation.

    Target: fastmcp.server.auth.providers.in_memory.InMemoryClientStore.register_client
    """
    try:
        module = importlib.import_module("fastmcp.server.auth.providers.in_memory")
    except Exception:
        return False

    store_cls = getattr(module, "InMemoryClientStore", None)
    if store_cls is None:
        return False

    if getattr(store_cls, "_MCP_SCOPE_PLANE_PATCHED", False):
        return True

    def patched_register_client(self, client_info):
        # Original logic + compat scopes union
        if (
            getattr(client_info, "scope", None) is not None
            and self.client_registration_options is not None
            and self.client_registration_options.valid_scopes is not None
        ):
            requested_scopes = set(client_info.scope.split())
            valid_scopes = set(self.client_registration_options.valid_scopes)
            valid_scopes.update(CLIENT_COMPAT_SCOPES)
            invalid_scopes = requested_scopes - valid_scopes
            if invalid_scopes:
                raise ValueError(
                    f"Requested scopes are not valid: {', '.join(sorted(invalid_scopes))}"
                )

        if getattr(client_info, "client_id", None) is None:
            raise ValueError("client_id is required for client registration")

        # RFC7591: treat known client_id as re-registration/update for this simple store
        self.clients[client_info.client_id] = client_info

    store_cls.register_client = patched_register_client
    store_cls._MCP_SCOPE_PLANE_PATCHED = True
    print("[INFO] Applied MCP scope-plane patch: InMemoryClientStore.register_client", file=sys.stderr)
    return True


def _patch_fastmcp_oauth_proxy() -> bool:
    """Patch upstream authorize URL construction.

    Target: fastmcp.server.auth.oauth_proxy.OAuthProxy._build_upstream_authorize_url
    Ensures only Google/OIDC scopes are forwarded upstream.
    """
    try:
        module = importlib.import_module("fastmcp.server.auth.oauth_proxy")
    except Exception:
        return False

    proxy_cls = getattr(module, "OAuthProxy", None)
    if proxy_cls is None:
        return False

    if getattr(proxy_cls, "_MCP_SCOPE_PLANE_PATCHED", False):
        return True

    original_build = proxy_cls._build_upstream_authorize_url

    def patched_build_upstream_authorize_url(self, txn_id, transaction):
        tx = dict(transaction or {})
        scopes = tx.get("scopes") or []

        if scopes:
            google_scopes = _filter_google_scopes(scopes)
            if google_scopes:
                tx["scopes"] = google_scopes
            else:
                # If only compat scopes were provided, drop them before upstream.
                tx["scopes"] = [s for s in scopes if s not in CLIENT_COMPAT_SCOPES]

        return original_build(self, txn_id, tx)

    proxy_cls._build_upstream_authorize_url = patched_build_upstream_authorize_url
    proxy_cls._MCP_SCOPE_PLANE_PATCHED = True
    print("[INFO] Applied MCP scope-plane patch: OAuthProxy._build_upstream_authorize_url", file=sys.stderr)
    return True


def _apply() -> None:
    patched_any = False
    patched_any = _patch_fastmcp_inmemory_store() or patched_any
    patched_any = _patch_fastmcp_oauth_proxy() or patched_any

    if not patched_any:
        print("[WARN] MCP scope-plane patch not applied: FastMCP symbols not found", file=sys.stderr)


_apply()
