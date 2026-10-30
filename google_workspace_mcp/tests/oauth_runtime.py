"""Check real OAuth rotation/storage code with only the Google transport mocked."""

import asyncio
from contextlib import asynccontextmanager
import hashlib
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastmcp.server.auth.oauth_proxy.models import JTIMapping, RefreshTokenMetadata, UpstreamTokenSet
from fastmcp.server.auth.providers.google import GoogleProvider
from key_value.aio.stores.memory import MemoryStore
from mcp.server.auth.provider import RefreshToken
from mcp.shared.auth import OAuthClientInformationFull

import sitecustomize


async def check_rotation():
    provider = GoogleProvider(
        client_id="test-client", client_secret="test-client-secret",
        base_url="http://127.0.0.1:8000", required_scopes=["openid"],
        client_storage=MemoryStore(),
    )
    provider.get_routes()
    scopes = ["openid", "mcp:tools"]
    client = OAuthClientInformationFull(
        client_id="ci-client", redirect_uris=["http://127.0.0.1:34567/callback"],
        scope=" ".join(scopes), token_endpoint_auth_method="none",
    )
    now = time.time()
    jti = "ci-old-refresh-jti"
    token = provider.jwt_issuer.issue_refresh_token(
        client_id=client.client_id, scopes=scopes, jti=jti, expires_in=3600,
    )
    refresh = RefreshToken(token=token, client_id=client.client_id, scopes=scopes, expires_at=int(now) + 3600)
    await provider._jti_mapping_store.put(
        key=jti, value=JTIMapping(jti=jti, upstream_token_id="ci-upstream", created_at=now), ttl=3600,
    )
    await provider._upstream_token_store.put(
        key="ci-upstream", value=UpstreamTokenSet(
            upstream_token_id="ci-upstream", access_token="test-upstream-access",
            refresh_token="test-upstream-refresh", refresh_token_expires_at=now + 3600,
            expires_at=now + 3600, token_type="Bearer", scope="openid",
            client_id=client.client_id, created_at=now,
        ), ttl=3600,
    )
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    await provider._refresh_token_store.put(
        key=token_hash, value=RefreshTokenMetadata(
            client_id=client.client_id, scopes=scopes, expires_at=int(now) + 3600, created_at=now,
        ), ttl=3600,
    )
    upstream = AsyncMock(return_value={
        "access_token": "test-upstream-access-new", "refresh_token": "test-upstream-refresh-new",
        "expires_in": 3600, "scope": "openid",
    })

    @asynccontextmanager
    async def oauth_client():
        yield SimpleNamespace(refresh_token=upstream)

    provider._upstream_oauth_client = oauth_client
    provider._extract_upstream_claims = AsyncMock(return_value={})
    first = await provider.exchange_refresh_token(client, refresh, scopes)
    repeated = await provider.exchange_refresh_token(client, refresh, scopes)
    assert first.refresh_token != token, "Refresh token did not rotate"
    assert first.access_token == repeated.access_token, "Retry issued a different access token"
    assert first.refresh_token == repeated.refresh_token, "Retry issued a different refresh token"
    assert upstream.await_count == 1, "Retry called the upstream token endpoint again"
    assert upstream.await_args.kwargs["scope"] == "openid", "Client-only scope reached the upstream"
    provider.jwt_issuer.verify_token(first.access_token)
    provider.jwt_issuer.verify_token(first.refresh_token, expected_token_use="refresh")
    previous = await provider._refresh_token_store.get(key=token_hash)
    assert previous is not None, "Previous refresh metadata was removed immediately"
    assert previous.expires_at <= time.time() + sitecustomize.MCP_REFRESH_ROTATION_GRACE_SECONDS
    # Removing the expired grace entry must stop returning the cached rotation.
    # The old mapping is deleted as well to model its matching storage TTL.
    await provider._mcp_refresh_rotation_grace_store.delete(key=jti)
    await provider._jti_mapping_store.delete(key=jti)
    try:
        await provider.exchange_refresh_token(client, refresh, scopes)
    except Exception as error:
        assert getattr(error, "error", None) == "invalid_grant", "Expired refresh failed unexpectedly"
    else:
        raise AssertionError("Expired refresh remained usable after grace storage expired")
    assert upstream.await_count == 1, "Expired refresh called the upstream endpoint"


if __name__ == "__main__":
    try:
        asyncio.run(check_rotation())
    except Exception as error:
        # Never include issued token values or model-validation input in CI output.
        raise RuntimeError(f"OAuth rotation contract failed ({type(error).__name__})") from None
    print("PASS: real token rotation, scope filtering, retry grace, and expiry rejection")
