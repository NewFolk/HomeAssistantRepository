"""Exercise the real image's auth proxy using an isolated Supervisor IP fixture."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time


IMAGE = sys.argv[1]
NAME = f"openlist-auth-{os.getpid()}"
NETWORK = NAME + "-net"
SUPERVISOR = NAME + "-supervisor"
TESTS = Path(__file__).resolve().parent


def docker(*args, check=True):
    result = subprocess.run(["docker", *args], check=check, text=True, capture_output=True)
    return (result.stdout + (result.stderr if args[0] == "logs" else "")).strip()


def write_options(data, options):
    docker("run", "--rm", "--entrypoint", "python3", "-v", f"{data}:/data", IMAGE,
           "-c", "import pathlib,sys; pathlib.Path('/data/options.json').write_text(sys.argv[1])", json.dumps(options))


def start(data):
    docker("rm", "-f", NAME, check=False)
    docker("run", "-d", "--name", NAME, "--network", NETWORK, "--ip", "172.30.32.3",
           "--add-host", "supervisor:172.30.32.2", "-e", "SUPERVISOR_TOKEN=ci-fixture",
           "-e", "INGRESS_ENTRY=/api/hassio_ingress/ci-test", "-v", f"{data}:/data", IMAGE)


def healthy():
    for _ in range(60):
        state = json.loads(docker("inspect", NAME))[0]["State"]
        if not state["Running"]:
            raise AssertionError("Auth smoke container stopped unexpectedly")
        if state["Health"]["Status"] == "healthy":
            return
        time.sleep(2)
    print(json.dumps(state.get("Health")), file=sys.stderr)
    # Fixture-only diagnosis: no database rows, options or credentials are printed.
    diagnosis = """import importlib.util,pathlib
s=importlib.util.spec_from_file_location('a','/usr/local/lib/openlist-addon/ingress-auth.py')
a=importlib.util.module_from_spec(s);s.loader.exec_module(a)
try:
    a.admin_token(pathlib.Path('/data/.openlist-runtime.json'));print('Credential lookup: OK')
except Exception as error:
    print('Credential lookup:',type(error).__name__,str(error))
"""
    print(docker("exec", NAME, "python3", "-c", diagnosis, check=False), file=sys.stderr)
    raise AssertionError("Auth smoke container did not become healthy")


def expect_stopped(message):
    for _ in range(30):
        state = json.loads(docker("inspect", NAME))[0]["State"]
        if not state["Running"]:
            break
        time.sleep(1)
    assert not state["Running"] and state["ExitCode"] != 0
    assert message in docker("logs", NAME)


def request(origin, port, path, headers=None, method="GET", body=None):
    host = "172.30.32.3" if origin == SUPERVISOR else "127.0.0.1"
    code = """import json,sys,urllib.request,urllib.error
try:
    body=None if sys.argv[4]=='null' else sys.argv[4].encode()
    response=urllib.request.urlopen(urllib.request.Request(sys.argv[1],headers=json.loads(sys.argv[2]),method=sys.argv[3],data=body),timeout=5)
except urllib.error.HTTPError as error:
    response=error
print(json.dumps({'status':response.code,'headers':dict(response.headers),'body':response.read().decode()}))
"""
    return json.loads(docker("exec", origin, "python3", "-c", code,
                             f"http://{host}:{port}{path}", json.dumps(headers or {}), method, json.dumps(body)))


def main():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        data = root / "data"
        data.mkdir()
        fixtures = root / "fixtures"
        fixtures.mkdir()
        version = fixtures / "version"
        version.write_text("2026.10.2")
        try:
            docker("network", "create", "--subnet", "172.30.32.0/24", NETWORK)
            docker("run", "-d", "--name", SUPERVISOR, "--network", NETWORK, "--ip", "172.30.32.2",
                   "--entrypoint", "python3", "-v", f"{TESTS}:/tests:ro", "-v", f"{fixtures}:/fixtures:ro",
                   IMAGE, "/tests/mock-supervisor.py")
            write_options(data, {"ingress_auto_login": True, "openlist": "{}"})
            start(data)
            expect_stopped("active OpenList administrator")
            write_options(data, {"ingress_auto_login": False, "openlist": "{}"})
            start(data)
            healthy()
            setup = request(SUPERVISOR, 5244, "/openlist/api/public/init/setup",
                            {"Content-Type": "application/json"}, "POST",
                            {"username": "admin", "password": "ci-only-fixture-password"})
            assert json.loads(setup["body"])["code"] == 200
            write_options(data, {"ingress_auto_login": True, "openlist": "{}"})
            start(data)
            healthy()
            trusted = {"X-Remote-User-Id": "ci-ha-admin", "Authorization": "forged-client-token"}
            response = request(SUPERVISOR, 8099, "/openlist/api/me", trusted)
            assert response["status"] == 200
            me = json.loads(response["body"])
            assert me["code"] == 200 and me["data"]["role"] == 2
            assert "X-OpenList-Token" not in response["headers"]
            assert "Set-Cookie" not in response["headers"]
            assert response["headers"]["Cache-Control"] == "no-store"
            # A real admin endpoint must work without an OpenList browser token.
            result = request(SUPERVISOR, 8099, "/openlist/api/admin/storage/list", trusted)
            assert json.loads(result["body"])["code"] == 200
            assert request(SUPERVISOR, 8099, "/openlist/api/admin/storage/create", trusted, "POST")["status"] == 403
            cross_site = {**trusted, "Origin": "https://attacker.example"}
            assert request(SUPERVISOR, 8099, "/openlist/api/admin/storage/create", cross_site, "POST")["status"] == 403
            same_site = {**trusted, "Origin": "http://172.30.32.3:8099"}
            # A real same-origin admin write must work; rotation takes effect immediately.
            same_site["Content-Type"] = "application/json"
            rotated = request(SUPERVISOR, 8099, "/openlist/api/admin/setting/reset_token", same_site, "POST", {})
            assert rotated["status"] == 200 and json.loads(rotated["body"])["code"] == 200
            # Browser sees public HTTPS, while HA/proxy headers describe internal
            # HTTP. Same-origin Fetch Metadata must make a real write work.
            browser = {**trusted, "Origin": "https://ha.example",
                       "X-Forwarded-Host": "homeassistant:8123", "X-Forwarded-Proto": "http",
                       "Content-Type": "application/json"}
            endpoint = "/openlist/api/admin/setting/reset_token"
            assert request(SUPERVISOR, 8099, endpoint, browser, "POST", {})["status"] == 403
            forged = {**browser, "X-Ingress-Fetch-Site": "same-origin"}
            assert request(SUPERVISOR, 8099, endpoint, forged, "POST", {})["status"] == 403
            browser["Sec-Fetch-Site"] = "same-origin"
            result = request(SUPERVISOR, 8099, endpoint, browser, "POST", {})
            assert result["status"] == 200 and json.loads(result["body"])["code"] == 200
            for site in ("cross-site", "same-site", "none", "invalid"):
                rejected = {**browser, "Sec-Fetch-Site": site}
                assert request(SUPERVISOR, 8099, endpoint, rejected, "POST", {})["status"] == 403
            missing_origin = {key: value for key, value in browser.items() if key != "Origin"}
            assert request(SUPERVISOR, 8099, endpoint, missing_origin, "POST", {})["status"] == 403
            assert request(NAME, 8099, endpoint, browser, "POST", {})["status"] == 403
            assert json.loads(request(SUPERVISOR, 8099, "/openlist/api/me", trusted)["body"])["data"]["role"] == 2
            assert request(SUPERVISOR, 8099, "/openlist/api/me")["status"] == 403
            assert request(NAME, 8099, "/openlist/api/me", trusted)["status"] == 403
            assert request(SUPERVISOR, 8099, "/_openlist_ingress_auth", trusted)["status"] == 404
            assert request(SUPERVISOR, 8099, "/_openlist_health", trusted)["status"] == 403
            direct = request(SUPERVISOR, 5244, "/openlist/api/me", trusted)
            assert json.loads(direct["body"])["code"] != 200
            direct = request(SUPERVISOR, 5244, "/openlist/api/me", browser)
            assert json.loads(direct["body"])["code"] != 200
            # The default disabled guest must not become administrator.
            direct = request(SUPERVISOR, 5244, "/openlist/api/me")
            assert json.loads(direct["body"])["code"] == 401
            login = request(SUPERVISOR, 5244, "/openlist/api/auth/login",
                            {"Content-Type": "application/json"}, "POST",
                            {"username": "admin", "password": "ci-only-fixture-password"})
            assert json.loads(login["body"])["code"] == 200
            # Old Supervisor must not activate auto-login, even on an existing DB.
            version.write_text("2026.10.1")
            start(data)
            expect_stopped("Supervisor 2026.10.2+")
            # Roll back the option without losing the initialized DB or admin.
            write_options(data, {"ingress_auto_login": False, "openlist": "{}"})
            start(data)
            healthy()
            regular = request(SUPERVISOR, 8099, "/openlist/api/me", trusted)
            assert json.loads(regular["body"])["code"] != 200
            assert json.loads(request(SUPERVISOR, 8099, "/openlist/api/me")["body"])["code"] == 401
            login = request(SUPERVISOR, 5244, "/openlist/api/auth/login",
                            {"Content-Type": "application/json"}, "POST",
                            {"username": "admin", "password": "ci-only-fixture-password"})
            assert json.loads(login["body"])["code"] == 200
            print("Ingress auth smoke passed: trusted admin proxy, spoof rejection, direct auth, version gate, opt-out.")
        except Exception:
            # Avoid dumping DB/options/auth headers even on failure.
            print("Ingress auth smoke failed; inspecting startup log only.", file=sys.stderr)
            print(docker("logs", NAME, check=False), file=sys.stderr)
            raise
        finally:
            docker("rm", "-f", NAME, SUPERVISOR, check=False)
            docker("network", "rm", NETWORK, check=False)
            docker("run", "--rm", "--entrypoint", "python3", "-v", f"{data}:/data", IMAGE,
                   "-c", "import pathlib,shutil; [shutil.rmtree(p) if p.is_dir() else p.unlink() for p in pathlib.Path('/data').iterdir()]", check=False)


if __name__ == "__main__":
    main()
