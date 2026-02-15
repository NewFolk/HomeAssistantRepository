"""Runtime patch for MCP/Google OAuth scope interop.

Why this exists:
- Some MCP clients request client-facing scopes like `mcp:tools` during OAuth2.1/DCR/auth.
- FastMCP OAuth proxy + MCP registration handler can validate client scopes
  against Google required scopes, causing false rejections before Google auth.
- Some stacks leak client-facing MCP scopes into upstream refresh_token calls,
  causing `invalid_scope` on refresh and client-side token invalidation.
- FastMCP rotates refresh tokens (one-time use). Some clients can issue duplicate
  refresh requests (retry/parallelism), which can cause `invalid_grant` on the
  second request and lead clients to wipe cached tokens.

This patch enforces scope-plane separation:
1) Client-facing MCP scope plane:
   - local registration validation accepts configured compat scopes.
2) Upstream Google scope plane:
   - only Google/OIDC scopes are forwarded upstream (authorize + refresh).

And adds refresh-token rotation resilience:
- A short grace window keeps the previous refresh token valid briefly and makes
  refresh idempotent for that window.
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

# Refresh-token rotation grace window (seconds).
#
# FastMCP OAuthProxy rotates refresh tokens and deletes the old one immediately.
# Some clients can issue a second refresh request (retry/parallel) with the old
# refresh token, causing `invalid_grant` and clients like mcporter to delete
# their local `tokens` cache.
MCP_REFRESH_ROTATION_GRACE_SECONDS = int(
    os.getenv("MCP_REFRESH_ROTATION_GRACE_SECONDS", "120").strip() or "120"
)


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
    - OAuthProxy._prepare_scopes_for_upstream_refresh : strips non-Google scopes on refresh
    - OAuthProxy.exchange_refresh_token : add a 120s grace window to make rotation resilient
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
    original_prepare_refresh = getattr(proxy_cls, "_prepare_scopes_for_upstream_refresh", None)
    original_exchange_refresh = getattr(proxy_cls, "exchange_refresh_token", None)

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

    def patched_prepare_scopes_for_upstream_refresh(self, scopes):
        """Prevent MCP-only scopes (e.g. `mcp:tools`) from being sent to Google on refresh.

        Some OAuth providers (Google) reject unknown scopes in refresh_token requests.
        If that happens, MCP SDK treats it as InvalidGrant and invalidates cached tokens
        client-side (mcporter deletes `tokens` from ~/.mcporter/credentials.json).
        """

        upstream_scopes = scopes
        if original_prepare_refresh is not None:
            try:
                upstream_scopes = original_prepare_refresh(self, scopes)
            except Exception:
                upstream_scopes = scopes

        try:
            return _filter_google_scopes(upstream_scopes or [])
        except Exception:
            return upstream_scopes

    async def patched_exchange_refresh_token(self, client, refresh_token, scopes):
        """Make refresh-token rotation resilient to duplicate refresh requests.

        Strategy:
        - Keep old refresh token metadata + JTI mapping alive for a short TTL
          (grace window) instead of deleting immediately.
        - Cache the *new* token response for the old refresh JTI for the same TTL.
        - If the old refresh is used again within the TTL, return the cached
          response (idempotent) instead of issuing another rotation or failing.
        """

        if original_exchange_refresh is None:
            raise RuntimeError("OAuthProxy.exchange_refresh_token symbol not found")

        grace_ttl = int(MCP_REFRESH_ROTATION_GRACE_SECONDS)

        # Derive refresh_jti (used as stable key).
        refresh_jti: str | None = None
        try:
            payload = self.jwt_issuer.verify_token(refresh_token.token)
            refresh_jti = payload.get("jti")
        except Exception:
            refresh_jti = None

        # Lazily create a small grace store in the same encrypted client_storage.
        grace_store = getattr(self, "_mcp_refresh_rotation_grace_store", None)
        GraceModel = getattr(self, "_mcp_refresh_rotation_grace_model", None)
        if grace_store is None:
            try:
                from key_value.aio.adapters.pydantic import PydanticAdapter
                from pydantic import BaseModel

                class _GraceTokenResponse(BaseModel):
                    access_token: str
                    refresh_token: str | None = None
                    expires_in: int | None = None
                    token_type: str | None = None
                    scope: str | None = None

                GraceModel = _GraceTokenResponse
                grace_store = PydanticAdapter(
                    key_value=self._client_storage,
                    pydantic_model=_GraceTokenResponse,
                    default_collection="mcp-refresh-rotation-grace",
                    raise_on_validation_error=True,
                )
                setattr(self, "_mcp_refresh_rotation_grace_store", grace_store)
                setattr(self, "_mcp_refresh_rotation_grace_model", GraceModel)
            except Exception:
                grace_store = None
                GraceModel = None

        # If we already rotated this refresh token very recently, return cached tokens.
        if grace_store is not None and refresh_jti:
            try:
                cached = await grace_store.get(key=refresh_jti)
                if cached is not None:
                    from mcp.shared.auth import OAuthToken

                    return OAuthToken(
                        access_token=cached.access_token,
                        token_type=cached.token_type or "Bearer",
                        expires_in=int(cached.expires_in or 3600),
                        refresh_token=cached.refresh_token,
                        scope=cached.scope or " ".join(scopes or []),
                    )
            except Exception:
                # If grace lookup fails, fall through to normal refresh.
                pass

        # Monkeypatch delete() calls inside the original rotation logic so that
        # old refresh artifacts are not removed immediately; instead, they are
        # shortened to the grace TTL.
        jti_store = getattr(self, "_jti_mapping_store", None)
        refresh_meta_store = getattr(self, "_refresh_token_store", None)

        old_jti_delete = getattr(jti_store, "delete", None) if jti_store else None
        old_refreshmeta_delete = (
            getattr(refresh_meta_store, "delete", None) if refresh_meta_store else None
        )

        async def _grace_jti_delete(*, key):
            if jti_store is None or old_jti_delete is None:
                return
            try:
                current = await jti_store.get(key=key)
                if current is not None:
                    await jti_store.put(key=key, value=current, ttl=grace_ttl)
                    return
            except Exception:
                pass
            await old_jti_delete(key=key)

        async def _grace_refreshmeta_delete(*, key):
            if refresh_meta_store is None or old_refreshmeta_delete is None:
                return
            try:
                current = await refresh_meta_store.get(key=key)
                if current is not None:
                    import time

                    try:
                        data = (
                            current.model_dump()
                            if hasattr(current, "model_dump")
                            else dict(current)
                        )
                        data["expires_at"] = int(time.time()) + int(grace_ttl)
                        refreshed = type(current)(**data)
                    except Exception:
                        refreshed = current

                    await refresh_meta_store.put(key=key, value=refreshed, ttl=grace_ttl)
                    return
            except Exception:
                pass
            await old_refreshmeta_delete(key=key)

        try:
            if jti_store is not None and old_jti_delete is not None:
                jti_store.delete = _grace_jti_delete  # type: ignore[assignment]
            if refresh_meta_store is not None and old_refreshmeta_delete is not None:
                refresh_meta_store.delete = _grace_refreshmeta_delete  # type: ignore[assignment]

            result = await original_exchange_refresh(self, client, refresh_token, scopes)
        finally:
            try:
                if jti_store is not None and old_jti_delete is not None:
                    jti_store.delete = old_jti_delete  # type: ignore[assignment]
                if refresh_meta_store is not None and old_refreshmeta_delete is not None:
                    refresh_meta_store.delete = old_refreshmeta_delete  # type: ignore[assignment]
            except Exception:
                pass

        # Cache the rotated result for a short grace window keyed by old refresh_jti.
        if grace_store is not None and GraceModel is not None and refresh_jti:
            try:
                await grace_store.put(
                    key=refresh_jti,
                    value=GraceModel(
                        access_token=result.access_token,
                        refresh_token=getattr(result, "refresh_token", None),
                        expires_in=getattr(result, "expires_in", None),
                        token_type=getattr(result, "token_type", None),
                        scope=getattr(result, "scope", None),
                    ),
                    ttl=grace_ttl,
                )
            except Exception:
                pass

        return result

    proxy_cls.__init__ = patched_init
    proxy_cls._build_upstream_authorize_url = patched_build_upstream_authorize_url
    if original_prepare_refresh is not None:
        proxy_cls._prepare_scopes_for_upstream_refresh = patched_prepare_scopes_for_upstream_refresh
    if original_exchange_refresh is not None:
        proxy_cls.exchange_refresh_token = patched_exchange_refresh_token

    proxy_cls._MCP_SCOPE_PLANE_PATCHED = True
    print(
        "[INFO] Applied MCP scope-plane patch: OAuthProxy.__init__ + _build_upstream_authorize_url + _prepare_scopes_for_upstream_refresh",
        file=sys.stderr,
    )
    if original_exchange_refresh is not None:
        print(
            f"[INFO] Applied refresh-token rotation grace patch: exchange_refresh_token (ttl={MCP_REFRESH_ROTATION_GRACE_SECONDS}s)",
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
