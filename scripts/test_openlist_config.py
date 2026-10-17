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
        ):
            with self.subTest(options=options):
                result = self.prepare(options)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("[ERROR]", result.stderr)
                self.assertEqual(self.runtime.read_bytes(), previous)
                self.assertEqual(json.loads(self.base.read_text()), self.original)

    def test_malformed_json_and_empty_base(self):
        self.options.write_text('{"openlist":')
        command = ["sh", str(ROOT / "openlist/prepare-config.sh"), str(self.base),
                   str(self.options), str(self.runtime), str(ROOT / "openlist/config-overrides.jq")]
        self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)
        self.assertFalse(self.runtime.exists())
        self.options.write_text("{}")
        self.base.write_text("")
        self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)
        self.assertFalse(self.runtime.exists())


if __name__ == "__main__":
    unittest.main()
