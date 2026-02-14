"""Runtime patch for MCP/Google OAuth scope interop.

Why this exists:
- Some MCP clients request client-facing scopes like `mcp:tools` during DCR/auth.
- FastMCP OAuth proxy + MCP registration handler can validate client scopes
  against Google required scopes, causing false rejections before Google auth.

This patch enforces scope-plane separation:
1) Client-facing MCP scope plane:
   - local registration validation accepts configured compat scopes.
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


def _merge_compat_scopes(existing: Iterable[str] | None) -> list[str]:
    merged = set(existing or [])
    merged.update(CLIENT_COMPAT_SCOPES)
    return sorted(merged)


def _patch_fastmcp_oauth_proxy() -> bool:
    """Patch FastMCP OAuthProxy internals.

    Targets:
    - OAuthProxy.__init__ : expands valid_scopes with client compat scopes
    - OAuthProxy._build_upstream_authorize_url : strips non-Google scopes upstream
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

    original_init = proxy_cls.__init__
    original_build = proxy_cls._build_upstream_authorize_url

    def patched_init(self, *args, **kwargs):
        required_scopes = kwargs.get("required_scopes")
        valid_scopes = kwargs.get("valid_scopes")

        # If valid_scopes is omitted, FastMCP would use required_scopes only.
        # We explicitly merge compat scopes into local client validation set.
        base = valid_scopes if valid_scopes is not None else (required_scopes or [])
        kwargs["valid_scopes"] = _merge_compat_scopes(base)

        return original_init(self, *args, **kwargs)

    def patched_build_upstream_authorize_url(self, txn_id, transaction):
        tx = dict(transaction or {})
        scopes = tx.get("scopes") or []

        if scopes:
            google_scopes = _filter_google_scopes(scopes)
            if google_scopes:
                tx["scopes"] = google_scopes
            else:
                # If transaction has only compat scopes, drop them for upstream.
                tx["scopes"] = [s for s in scopes if s not in CLIENT_COMPAT_SCOPES]

        return original_build(self, txn_id, tx)

    proxy_cls.__init__ = patched_init
    proxy_cls._build_upstream_authorize_url = patched_build_upstream_authorize_url
    proxy_cls._MCP_SCOPE_PLANE_PATCHED = True
    print(
        "[INFO] Applied MCP scope-plane patch: OAuthProxy.__init__ + _build_upstream_authorize_url",
        file=sys.stderr,
    )
    return True


def _patch_mcp_register_handler() -> bool:
    """Patch MCP registration handler as safety net.

    Target:
    - mcp.server.auth.handlers.register.RegistrationHandler.handle

    Ensures compat scopes are included in options.valid_scopes at request time.
    """
    try:
        module = importlib.import_module("mcp.server.auth.handlers.register")
    except Exception:
        return False

    handler_cls = getattr(module, "RegistrationHandler", None)
    if handler_cls is None:
        return False

    if getattr(handler_cls, "_MCP_SCOPE_PLANE_PATCHED", False):
        return True

    original_handle = handler_cls.handle

    async def patched_handle(self, request):
        try:
            if getattr(self, "options", None) is not None:
                current_valid = getattr(self.options, "valid_scopes", None)
                if current_valid is not None:
                    self.options.valid_scopes = _merge_compat_scopes(current_valid)
        except Exception:
            # Never break request path due to patch-side issues
            pass
        return await original_handle(self, request)

    handler_cls.handle = patched_handle
    handler_cls._MCP_SCOPE_PLANE_PATCHED = True
    print("[INFO] Applied MCP scope-plane patch: RegistrationHandler.handle", file=sys.stderr)
    return True


def _patch_fastmcp_inmemory_store() -> bool:
    """Optional compatibility patch for FastMCP in-memory store validation.

    This is not the primary failing path in current stack, but kept as defense-in-depth.
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

        self.clients[client_info.client_id] = client_info

    store_cls.register_client = patched_register_client
    store_cls._MCP_SCOPE_PLANE_PATCHED = True
    print("[INFO] Applied MCP scope-plane patch: InMemoryClientStore.register_client", file=sys.stderr)
    return True


def _apply() -> None:
    patched_any = False
    patched_any = _patch_fastmcp_oauth_proxy() or patched_any
    patched_any = _patch_mcp_register_handler() or patched_any
    patched_any = _patch_fastmcp_inmemory_store() or patched_any

    if not patched_any:
        print("[WARN] MCP scope-plane patch not applied: target symbols not found", file=sys.stderr)


_apply()
