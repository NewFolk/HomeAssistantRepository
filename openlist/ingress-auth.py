#!/usr/bin/env python3
"""Keep Ingress credentials server-side; never mint browser tokens or change users."""

import argparse
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
from urllib.request import Request, urlopen
from urllib.parse import urlsplit


MIN_SUPERVISOR = (2026, 10, 2)
AUTH_CONFIG = """auth_request /_openlist_ingress_auth;
auth_request_set $ingress_admin_token $upstream_http_x_openlist_token;
proxy_set_header Authorization $ingress_admin_token;
proxy_hide_header Cache-Control;
add_header Cache-Control "no-store" always;
"""


def check_supervisor():
    """panel_admin became a server-side access check in Supervisor 2026.10.2."""
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        raise ValueError("Ingress auto-login requires SUPERVISOR_TOKEN")
    request = Request("http://supervisor/info", headers={"Authorization": f"Bearer {token}"})
    with urlopen(request, timeout=10) as response:
        info = json.load(response)
    version = info.get("data", {}).get("supervisor", "")
    if info.get("result") != "ok" or not isinstance(version, str) or not re.fullmatch(r"\d{4}\.\d+\.\d+", version):
        raise ValueError("Cannot verify the Supervisor version for Ingress auto-login")
    if tuple(map(int, version.split("."))) < MIN_SUPERVISOR:
        raise ValueError("Ingress auto-login requires Supervisor 2026.10.2 or newer")


def configure(options_path, output_path, config_path):
    options = json.loads(options_path.read_text()) if options_path.exists() else {}
    enabled = options.get("ingress_auto_login", False)
    if type(enabled) is not bool:
        raise ValueError("ingress_auto_login must be a boolean")
    if enabled:
        check_supervisor()
        admin_token(config_path)
    output_path.write_text(AUTH_CONFIG if enabled else "# Ingress auto-login is disabled.\n")


def admin_token(config_path):
    """Read the existing token and active admin without writing the SQLite DB."""
    config = json.loads(config_path.read_text())
    prefix = config["database"].get("table_prefix", "x_")
    if not isinstance(prefix, str) or not re.fullmatch(r"[A-Za-z0-9_]*", prefix):
        raise ValueError("Unsupported database table prefix for Ingress auto-login")
    database = Path(config["database"]["db_file"]).resolve()
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=2)) as connection:
        active = connection.execute(
            f'SELECT COUNT(*) FROM "{prefix}users" WHERE role = 2 AND disabled = 0'
        ).fetchone()[0]
        row = connection.execute(
            f'SELECT value FROM "{prefix}setting_items" WHERE key = ?', ("token",)
        ).fetchone()
    if active != 1 or row is None or not isinstance(row[0], str) or not row[0]:
        raise ValueError("OpenList has no active administrator or admin API token")
    if not re.fullmatch(r"[\x21-\x7e]+", row[0]):
        raise ValueError("OpenList admin API token is not a valid HTTP header value")
    return row[0]


def origin_tuple(value):
    """Compare browser origins, not raw strings with optional default ports."""
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in ("http", "https") or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or parsed.path or parsed.query or parsed.fragment):
            return None
        port = parsed.port
        if port is None:
            port = 443 if parsed.scheme == "https" else 80
        return parsed.scheme, parsed.hostname, port
    except ValueError:
        return None


def origin_rejection(headers):
    """Browser Fetch Metadata survives TLS termination without a URL allowlist.

    Scripts cannot forge Sec-Fetch-Site. nginx must pass the actual browser
    header, not a client-provided X-Ingress-Fetch-Site. This is CSRF evidence,
    never a replacement for Supervisor peer, identity and panel checks.
    """
    site = headers.get("X-Ingress-Fetch-Site")
    if site in ("cross-site", "same-site"):
        return "cross_origin_fetch"
    origin = headers.get("Origin")
    unsafe = headers.get("X-Ingress-Method") not in ("GET", "HEAD", "OPTIONS")
    if unsafe and not origin:
        return "missing_origin"
    if origin:
        actual = origin_tuple(origin)
        if actual is None:
            return "invalid_origin"
        # The browser evaluates the public target before proxy rewrites; scheme,
        # hostname and port can differ from the internal HTTP transport here.
        if site == "same-origin":
            return None
        expected = origin_tuple(f"{headers.get('X-Ingress-Proto')}://{headers.get('X-Ingress-Host')}")
        if expected is None or actual != expected:
            return "origin_mismatch"
    return None


def handler(config_path):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            # Do not log credentials, trusted user headers or request paths.
            pass

        def do_GET(self):
            if self.path not in ("/authorize", "/health"):
                self.send_error(404)
                return
            if self.path == "/authorize" and (
                self.headers.get("X-Ingress-Peer") != "172.30.32.2"
                or not self.headers.get("X-Remote-User-Id")
            ):
                print("[WARN] Ingress auto-login request rejected: untrusted_peer_or_missing_identity", file=sys.stderr, flush=True)
                self.send_error(403)
                return
            if self.path == "/authorize":
                reason = origin_rejection(self.headers)
                if reason:
                    print(f"[WARN] Ingress auto-login request rejected: {reason}", file=sys.stderr, flush=True)
                    self.send_error(403, "Ingress writes require a same-origin browser request")
                    return
            try:
                token = admin_token(config_path)
            except (OSError, ValueError, KeyError, TypeError, sqlite3.Error):
                self.send_error(503, "OpenList Ingress authentication is unavailable")
                return
            self.send_response(204 if self.path == "/authorize" else 200)
            if self.path == "/authorize":
                self.send_header("X-OpenList-Token", token)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", "0")
            self.end_headers()

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("configure", "serve"))
    args = parser.parse_args()
    if args.mode == "configure":
        try:
            configure(Path("/data/options.json"), Path("/tmp/openlist-ingress-auth.conf"), Path("/data/.openlist-runtime.json"))
        except Exception:
            # Remote exception details may contain a token or response content.
            print("[ERROR] Cannot enable Ingress auto-login. Requires reachable Supervisor 2026.10.2+ and an active OpenList administrator. Set ingress_auto_login: false to complete initial setup or recover.", file=sys.stderr)
            return 1
    else:
        server = ThreadingHTTPServer(("127.0.0.1", 8098), handler(Path("/data/.openlist-runtime.json")))
        server.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
