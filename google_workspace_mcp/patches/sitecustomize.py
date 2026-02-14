"""Runtime patch for MCP/Google OAuth scope interop.

This patch keeps Google token verification Google-only, while allowing
client-facing MCP scopes (e.g. mcp:tools) during local OAuth validation.
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


def _patch_provider(module_name: str) -> bool:
    try:
        module = importlib.import_module(module_name)
    except Exception:
        return False

    if getattr(module, "_MCP_SCOPE_PLANE_PATCHED", False):
        return True

    required_attrs = ("validate_scopes", "build_google_auth_params")
    if not all(hasattr(module, attr) for attr in required_attrs):
        return False

    original_build_google_auth_params = module.build_google_auth_params

    def patched_validate_scopes(requested_scopes: list[str], required_scopes: list[str]) -> None:
        required_scope_set = set(required_scopes or [])
        invalid = []
        for requested_scope in requested_scopes or []:
            if requested_scope in required_scope_set:
                continue
            if requested_scope in CLIENT_COMPAT_SCOPES:
                continue
            invalid.append(requested_scope)
        if invalid:
            joined = ", ".join(invalid)
            raise ValueError(f"Requested scopes are not valid: {joined}")

    def patched_build_google_auth_params(
        client_id: str, redirect_uri: str, scopes: list[str], state: str
    ) -> dict[str, str]:
        google_scopes = _filter_google_scopes(scopes or [])
        if not google_scopes:
            google_scopes = [scope for scope in (scopes or []) if scope not in CLIENT_COMPAT_SCOPES]
        return original_build_google_auth_params(client_id, redirect_uri, google_scopes, state)

    module.validate_scopes = patched_validate_scopes
    module.build_google_auth_params = patched_build_google_auth_params
    module._MCP_SCOPE_PLANE_PATCHED = True
    print(f"[INFO] Applied MCP scope-plane patch to {module_name}", file=sys.stderr)
    return True


def _apply() -> None:
    candidates = ("google_mcp.auth.provider", "auth.provider")
    for candidate in candidates:
        if _patch_provider(candidate):
            return
    print("[WARN] MCP scope-plane patch not applied: provider module not found", file=sys.stderr)


_apply()
