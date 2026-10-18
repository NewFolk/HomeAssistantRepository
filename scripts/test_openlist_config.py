import json
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        directory = Path(self.tmp.name)
        self.base = directory / "config.json"
        self.options = directory / "options.json"
        self.runtime = directory / "runtime.json"
        self.original = {
            "jwt_secret": "keep-this-secret",
            "tasks": {"copy": {"workers": 5, "task_persistant": False}},
            "cors": {"allow_origins": ["original"]},
        }
        self.base.write_text(json.dumps(self.original))

    def prepare(self, options):
        self.options.write_text(json.dumps(options))
        return subprocess.run([
            "sh", str(ROOT / "openlist/prepare-config.sh"), str(self.base),
            str(self.options), str(self.runtime), str(ROOT / "openlist/config-overrides.jq"),
            str(ROOT / "openlist/parse-options.py"),
        ], capture_output=True, text=True)

    def test_deep_merge_types_arrays_and_removal(self):
        result = self.prepare({"openlist": {
            "tasks": {"copy": {"task_persistant": True}},
            "cors": {"allow_origins": ["replacement"]},
            "future_field": {"number": 12, "list": [1, False, "value"]},
        }})
        self.assertEqual(result.returncode, 0, result.stderr)
        effective = json.loads(self.runtime.read_text())
        self.assertEqual(effective["tasks"]["copy"], {"workers": 5, "task_persistant": True})
        self.assertEqual(effective["cors"]["allow_origins"], ["replacement"])
        self.assertEqual(effective["future_field"]["number"], 12)
        self.assertEqual(effective["jwt_secret"], self.original["jwt_secret"])
        self.assertEqual(json.loads(self.base.read_text()), self.original)
        self.assertNotIn(self.original["jwt_secret"], result.stdout + result.stderr)
        self.assertEqual(self.prepare({"openlist": {}}).returncode, 0)
        restored = json.loads(self.runtime.read_text())
        self.assertFalse(restored["tasks"]["copy"]["task_persistant"])
        self.assertEqual(restored["cors"]["allow_origins"], ["original"])
        self.assertNotIn("future_field", restored)
        self.assertEqual(self.runtime.stat().st_mode & 0o777, 0o600)

    def test_keep_upstream_migration_marker_without_old_overrides(self):
        self.runtime.write_text(json.dumps({"last_launched_version": "v4.2.7", "token_expires_in": 168}))
        result = self.prepare({"openlist": {}})
        self.assertEqual(result.returncode, 0, result.stderr)
        runtime = json.loads(self.runtime.read_text())
        self.assertEqual(runtime["last_launched_version"], "v4.2.7")
        self.assertNotIn("token_expires_in", runtime)

    def test_rebuild_partial_runtime_file(self):
        self.runtime.write_text('{"truncated":')
        result = self.prepare({"openlist": {"token_expires_in": 72}})
        self.assertEqual(result.returncode, 0, result.stderr)
        effective = json.loads(self.runtime.read_text())
        self.assertEqual(effective["jwt_secret"], self.original["jwt_secret"])
        self.assertEqual(effective["token_expires_in"], 72)

    def test_reject_protected_fields_and_bad_structure(self):
        self.assertEqual(self.prepare({}).returncode, 0)
        previous = self.runtime.read_bytes()
        for options in (
            {"openlist": {"site_url": "/other"}},
            {"openlist": {"database": {"db_file": "/tmp/empty.db"}}},
            {"openlist": {"scheme": {"http_port": 1234}}},
            {"openlist": {"force": False}},
            {"openlist": {"scheme": None}},
            {"openlist": "secret-value"}, {"openlist": []},
            {"openlist": None}, {"typo": {}}, [], None,
            {"ingress_auto_login": "true"}, {"ingress_auto_login": None},
        ):
            with self.subTest(options=options):
                result = self.prepare(options)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("[ERROR]", result.stderr)
                self.assertEqual(self.runtime.read_bytes(), previous)
                self.assertEqual(json.loads(self.base.read_text()), self.original)

    def test_wrapper_option_is_not_merged_into_openlist(self):
        result = self.prepare({"ingress_auto_login": True, "openlist": {"token_expires_in": 72}})
        self.assertEqual(result.returncode, 0, result.stderr)
        runtime = json.loads(self.runtime.read_text())
        self.assertEqual(runtime["token_expires_in"], 72)
        self.assertNotIn("ingress_auto_login", runtime)

    def test_malformed_json_and_empty_base(self):
        self.options.write_text('{"openlist":')
        command = ["sh", str(ROOT / "openlist/prepare-config.sh"), str(self.base),
                   str(self.options), str(self.runtime), str(ROOT / "openlist/config-overrides.jq"),
                   str(ROOT / "openlist/parse-options.py")]
        self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)
        self.assertFalse(self.runtime.exists())
        self.options.write_text("{}")
        self.base.write_text("")
        self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)
        self.assertFalse(self.runtime.exists())

    def test_yaml_block_types_restart_and_source_preservation(self):
        options = {"ingress_auto_login": False, "openlist": """tasks:
  copy:
    task_persistant: true
token_expires_in: 168
cors:
  allow_origins: [replacement]
"""}
        for _ in range(2):
            result = self.prepare(options)
            self.assertEqual(result.returncode, 0, result.stderr)
            runtime = json.loads(self.runtime.read_text())
            self.assertIs(runtime["tasks"]["copy"]["task_persistant"], True)
            self.assertEqual(runtime["tasks"]["copy"]["workers"], 5)
            self.assertEqual(runtime["token_expires_in"], 168)
            self.assertEqual(runtime["cors"]["allow_origins"], ["replacement"])
            self.assertEqual(json.loads(self.options.read_text()), options)
            self.assertEqual(json.loads(self.base.read_text()), self.original)
        self.assertEqual(self.prepare({"openlist": "{}"}).returncode, 0)
        self.assertFalse(json.loads(self.runtime.read_text())["tasks"]["copy"]["task_persistant"])

    def test_json_string_and_blank_string(self):
        result = self.prepare({"openlist": '{"token_expires_in":72}'})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(self.runtime.read_text())["token_expires_in"], 72)
        self.assertEqual(self.prepare({"openlist": ""}).returncode, 0)

    def test_bad_yaml_does_not_leak_values_or_replace_runtime(self):
        self.assertEqual(self.prepare({"openlist": "{}"}).returncode, 0)
        previous = self.runtime.read_bytes()
        for value in ("secret-value: [", "- secret-value", "secret-value", "null",
                      "secret-value: !!python/object:os.system {}", "secret-value: .nan",
                      "secret-value: 2026-10-18"):
            with self.subTest(value=value):
                result = self.prepare({"openlist": value})
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("[ERROR]", result.stderr)
                self.assertNotIn("secret-value", result.stderr + result.stdout)
                self.assertEqual(self.runtime.read_bytes(), previous)


if __name__ == "__main__":
    unittest.main()
