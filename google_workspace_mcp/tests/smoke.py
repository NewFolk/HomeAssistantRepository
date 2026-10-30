"""Exercise the built runtime with synthetic credentials, never a Google account."""

import http.client
import json
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.parse import urlencode, urlparse
import uuid


def docker(*args, **kwargs):
    return subprocess.run(
        ["docker", *args], check=True, text=True, capture_output=True, **kwargs
    ).stdout.strip()


def request(port, path, data=None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        headers = {"Content-Type": "application/json"} if data is not None else {}
        connection.request(
            "POST" if data is not None else "GET", path,
            json.dumps(data) if data is not None else None, headers,
        )
        response = connection.getresponse()
        return response.status, {key.lower(): value for key, value in response.getheaders()}, response.read()
    finally:
        connection.close()


def main(image):
    root = Path(__file__).resolve().parents[1]
    dockerfile = (root / "Dockerfile").read_text()
    python_version = re.search(r"^FROM python:([\d.]+)-", dockerfile)[1]
    package_version = re.search(r"workspace-mcp==([\d.]+)", dockerfile)[1]
    name = "workspace-mcp-smoke-" + uuid.uuid4().hex[:12]
    volume = name + "-data"
    options = {
        "oauth_client_id": "test-client.apps.googleusercontent.com",
        "oauth_client_secret": "test-client-secret",
        "external_url": "http://127.0.0.1:8000",
        "tool_tier": "core",
        "tools": "gmail calendar drive docs sheets",
        "client_compat_scopes": "mcp:tools",
        "enable_oauth21": True,
        "stateless_mode": False,
        "single_user_mode": False,
        "read_only_mode": True,
        "allow_insecure_transport": True,
        "transport": "streamable-http",
    }
    docker("volume", "create", volume)
    try:
        docker(
            "run", "--rm", "--interactive", "--volume", f"{volume}:/data", "--entrypoint", "python",
            image, "-c",
            "import pathlib,sys; pathlib.Path('/data/options.json').write_text(sys.stdin.read())",
            input=json.dumps(options),
        )
        docker("run", "--rm", "--entrypoint", "python", image, "-m", "pip", "check")
        hooks = r'''
import sys
from urllib.parse import parse_qs, urlparse
from fastmcp.server.auth.oauth_proxy import OAuthProxy
from fastmcp.server.auth.providers.google import GoogleProvider
from mcp.server.auth.handlers.register import RegistrationHandler
assert sys.version.startswith(sys.argv[1] + ".")
assert OAuthProxy._MCP_SCOPE_PLANE_PATCHED
assert RegistrationHandler._MCP_SCOPE_PLANE_PATCHED
assert OAuthProxy.exchange_refresh_token.__name__ == "patched_exchange_refresh_token"
provider = GoogleProvider(client_id="test-client", client_secret="test-secret",
                          base_url="http://127.0.0.1:8000", required_scopes=["openid"])
scopes = ["mcp:tools", "openid", "https://www.googleapis.com/auth/drive.readonly"]
url = provider._build_upstream_authorize_url("test-state", {"scopes": scopes})
assert set(parse_qs(urlparse(url).query)["scope"][0].split()) == set(scopes[1:])
assert set(provider._prepare_scopes_for_upstream_refresh(scopes)) == set(scopes[1:])
'''
        docker("run", "--rm", "--entrypoint", "python", image, "-c", hooks, python_version)
        client = None
        for iteration in range(2):
            docker(
                "run", "--detach", "--name", name, "--publish", "127.0.0.1::8000",
                "--volume", f"{volume}:/data", image,
            )
            port = int(docker("port", name, "8000/tcp").rsplit(":", 1)[1])
            deadline = time.monotonic() + 90
            while True:
                try:
                    status, _, body = request(port, "/health")
                    if status == 200:
                        health = json.loads(body)
                        assert health["status"] == "healthy"
                        assert health["version"] == package_version
                        break
                except (OSError, http.client.HTTPException):
                    pass
                if time.monotonic() > deadline:
                    raise AssertionError("Container did not become healthy")
                if docker("inspect", "--format", "{{.State.Running}}", name) != "true":
                    raise AssertionError("Container exited before health check")
                time.sleep(1)

            status, _, body = request(port, "/.well-known/oauth-authorization-server")
            assert status == 200
            discovery = json.loads(body)
            assert "mcp:tools" in discovery["scopes_supported"]
            assert "refresh_token" in discovery["grant_types_supported"]
            assert request(port, "/mcp", {})[0] == 401
            if iteration == 0:
                registration = {
                    "client_name": "CI scope check",
                    "redirect_uris": ["http://127.0.0.1:34567/callback"],
                    "grant_types": ["authorization_code", "refresh_token"],
                    "response_types": ["code"],
                    "token_endpoint_auth_method": "none",
                    "scope": "mcp:tools",
                }
                status, _, body = request(port, "/register", registration)
                assert status == 201, f"Registration returned HTTP {status}"
                client = json.loads(body)
                assert client["scope"] == "mcp:tools"
                registration["scope"] = "unsupported-ci-scope"
                assert request(port, "/register", registration)[0] == 400

            query = urlencode({
                "client_id": client["client_id"],
                "redirect_uri": "http://127.0.0.1:34567/callback",
                "response_type": "code", "scope": "mcp:tools", "state": "ci-state",
                "code_challenge": "A" * 43, "code_challenge_method": "S256",
            })
            status, headers, _ = request(port, "/authorize?" + query)
            assert status == 302, f"Known-client authorization returned HTTP {status}"
            assert urlparse(headers["location"]).path == "/consent"
            persisted = json.loads(docker(
                "exec", name, "python", "-c",
                "from pathlib import Path; print(Path('/data/options.json').read_text())",
            ))
            assert persisted == options
            docker("rm", "--force", name)
        print("PASS: runtime, OAuth scope hooks, registration, access boundary, and persisted client")
    finally:
        subprocess.run(["docker", "rm", "--force", name], capture_output=True, check=False)
        docker("volume", "rm", volume)


if __name__ == "__main__":
    main(sys.argv[1])
