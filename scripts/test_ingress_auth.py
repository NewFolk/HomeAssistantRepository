import importlib.util
from contextlib import closing
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from http.server import ThreadingHTTPServer


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("ingress_auth", ROOT / "openlist/ingress-auth.py")
AUTH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUTH)


class IngressAuthTests(unittest.TestCase):
    def test_metadata_keeps_admin_only_panel_and_unpublished_native_port(self):
        metadata = (ROOT / "openlist/config.yaml").read_text()
        self.assertNotRegex(metadata, r"(?m)^panel_admin:\s*false\s*$")
        self.assertRegex(metadata, r"(?m)^  5244/tcp: null$")
        self.assertIn("  ingress_auto_login: false", metadata)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.config = self.directory / "runtime.json"
        self.database = self.directory / "data.db"
        self.config.write_text(json.dumps({"database": {"db_file": str(self.database), "table_prefix": "x_"}}))
        self.mutate('CREATE TABLE x_users(role INTEGER, disabled BOOLEAN)')
        self.mutate('INSERT INTO x_users VALUES (2, 0)')
        self.mutate('CREATE TABLE x_setting_items(key TEXT, value TEXT)')
        self.mutate('INSERT INTO x_setting_items VALUES (?, ?)', ("token", "test-secret-not-a-real-token"))

    def mutate(self, sql, parameters=()):
        with closing(sqlite3.connect(self.database)) as db:
            db.execute(sql, parameters)
            db.commit()

    def test_supervisor_version_gate(self):
        for version, allowed in (("2026.10.2", True), ("2026.11.0", True),
                                 ("2026.10.1", False), ("2026.9.9", False),
                                 ("2026.10.2.dev0", False), ("unknown", False), (None, False)):
            with self.subTest(version=version), patch.dict("os.environ", {"SUPERVISOR_TOKEN": "fixture"}):
                response = io.BytesIO(json.dumps({"result": "ok", "data": {"supervisor": version}}).encode())
                with patch.object(AUTH, "urlopen", return_value=response):
                    if allowed:
                        AUTH.check_supervisor()
                    else:
                        with self.assertRaises(ValueError):
                            AUTH.check_supervisor()
        with patch.dict("os.environ", {}, clear=True), self.assertRaises(ValueError):
            AUTH.check_supervisor()

    def test_configure_is_opt_in_and_does_not_write_secrets(self):
        options = self.directory / "options.json"
        output = self.directory / "auth.conf"
        with patch.object(AUTH, "check_supervisor") as check:
            AUTH.configure(options, output)
            check.assert_not_called()
            self.assertNotIn("auth_request", output.read_text())
            options.write_text('{"ingress_auto_login":true}')
            AUTH.configure(options, output)
            check.assert_called_once()
            self.assertIn("auth_request", output.read_text())
            self.assertNotIn("test-secret", output.read_text())
            options.write_text('{"ingress_auto_login":"true"}')
            with self.assertRaises(ValueError):
                AUTH.configure(options, output)

    def test_unavailable_supervisor_never_enables_auth(self):
        options = self.directory / "options.json"
        options.write_text('{"ingress_auto_login":true}')
        output = self.directory / "auth.conf"
        with patch.object(AUTH, "check_supervisor", side_effect=OSError), self.assertRaises(OSError):
            AUTH.configure(options, output)
        self.assertFalse(output.exists())

    def test_read_only_token_lookup_and_rotation(self):
        before = self.database.read_bytes()
        self.assertEqual(AUTH.admin_token(self.config), "test-secret-not-a-real-token")
        self.assertEqual(before, self.database.read_bytes())
        self.mutate('UPDATE x_setting_items SET value = ?', ("rotated-test-token",))
        self.assertEqual(AUTH.admin_token(self.config), "rotated-test-token")

    def test_missing_or_disabled_admin_and_bad_token_fail_closed(self):
        self.mutate('UPDATE x_users SET disabled = 1')
        with self.assertRaises(ValueError):
            AUTH.admin_token(self.config)
        self.mutate('UPDATE x_users SET disabled = 0')
        for token in ("", "unsafe\r\nheader", None):
            self.mutate('UPDATE x_setting_items SET value = ?', (token,))
            with self.assertRaises(ValueError):
                AUTH.admin_token(self.config)

    def test_missing_db_is_not_created(self):
        missing = self.directory / "missing.db"
        self.config.write_text(json.dumps({"database": {"db_file": str(missing)}}))
        with self.assertRaises(sqlite3.Error):
            AUTH.admin_token(self.config)
        self.assertFalse(missing.exists())

    def test_header_boundary_and_no_token_body(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), AUTH.handler(self.config))
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        self.addCleanup(server.server_close)
        self.addCleanup(worker.join)
        self.addCleanup(server.shutdown)
        url = f"http://127.0.0.1:{server.server_port}/authorize"
        for headers in ({}, {"X-Ingress-Peer": "127.0.0.1", "X-Remote-User-Id": "fixture"},
                        {"X-Ingress-Peer": "172.30.32.2"}):
            with self.assertRaises(HTTPError) as result:
                urlopen(Request(url, headers=headers))
            self.assertEqual(result.exception.code, 403)
            result.exception.close()
        headers = {"X-Ingress-Peer": "172.30.32.2", "X-Remote-User-Id": "fixture", "X-Ingress-Method": "GET"}
        with urlopen(Request(url, headers=headers)) as response:
            self.assertEqual(response.status, 204)
            self.assertEqual(response.read(), b"")
            self.assertEqual(response.headers["X-OpenList-Token"], "test-secret-not-a-real-token")
        with urlopen(url.replace("/authorize", "/health")) as response:
            self.assertNotIn("X-OpenList-Token", response.headers)
        headers.update({"X-Ingress-Method": "POST", "X-Ingress-Proto": "https", "X-Ingress-Host": "ha.example"})
        for origin in (None, "https://attacker.example"):
            if origin:
                headers["Origin"] = origin
            with self.assertRaises(HTTPError) as result:
                urlopen(Request(url, headers=headers))
            self.assertEqual(result.exception.code, 403)
            result.exception.close()
        headers["Origin"] = "https://ha.example"
        with urlopen(Request(url, headers=headers)) as response:
            self.assertEqual(response.status, 204)


if __name__ == "__main__":
    unittest.main()
