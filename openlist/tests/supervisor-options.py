"""Run pinned upstream validation code, then test its output in the real image.

Only hardware/CoreSys imports are stubbed; option/schema validation is unchanged.
This is not a full Supervisor REST API or Home Assistant frontend integration test.
"""

import ast
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest

import voluptuous as vol
import yaml


ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path(sys.argv[1])
IMAGE = sys.argv[2] if len(sys.argv) > 2 else None
METADATA = yaml.safe_load((ROOT / "openlist/config.yaml").read_text())


def load_validator():
    options_path = SOURCE / "supervisor/apps/options.py"
    tree = ast.parse(options_path.read_text())
    # Importing the entire Supervisor requires a privileged HA host. Keep all
    # upstream validator code, constants and stdlib/voluptuous imports intact.
    tree.body = [node for node in tree.body if not (isinstance(node, ast.ImportFrom) and node.level)]
    namespace = {"__name__": "supervisor_options_fixture", "CoreSysAttributes": object}
    exec(compile(tree, str(options_path), "exec"), namespace)
    model_path = SOURCE / "supervisor/apps/model.py"
    model = ast.parse(model_path.read_text())
    model_class = next(node for node in model.body if isinstance(node, ast.ClassDef) and node.name == "AppModel")
    factory = next(node for node in model_class.body if isinstance(node, ast.FunctionDef) and node.name == "options_schema")
    namespace["ATTR_SCHEMA"] = "schema"
    exec(compile(ast.Module(body=[factory], type_ignores=[]), str(model_path), "exec"), namespace)
    return namespace["options_schema"]


OPTIONS_SCHEMA = load_validator()


def validate(options, schema=None):
    model = SimpleNamespace(data={"schema": METADATA["schema"] if schema is None else schema},
                            coresys=None, name="OpenList test", slug="local_openlist")
    return OPTIONS_SCHEMA(model, resolve_secrets=False).validate(deepcopy(options))


def docker(*args, check=True):
    return subprocess.run(["docker", *args], capture_output=True, text=True, check=check).stdout.strip()


class SupervisorOptionsTests(unittest.TestCase):
    def test_reproduce_false_schema_discarding_every_key(self):
        payload = {"ingress_auto_login": True, "openlist": {"token_expires_in": 168}}
        with self.assertLogs("supervisor_options_fixture", level="WARNING"):
            self.assertEqual(validate(payload, schema=False), {})

    def test_save_reload_preserves_switch_and_arbitrary_yaml(self):
        payload = {"ingress_auto_login": True, "openlist": """tasks:
  copy:
    task_persistant: true
token_expires_in: 168
future_setting:
  values: [true, 12, 0.5, example]
"""}
        persisted = json.loads(json.dumps(validate(payload)))
        self.assertEqual(persisted, payload)
        self.assertEqual(validate(persisted), payload)
        self.assertEqual(validate(METADATA["options"]), METADATA["options"])
        with self.assertRaises(vol.Invalid):
            validate({"ingress_auto_login": False, "openlist": {"arbitrary": True}})

    @unittest.skipUnless(IMAGE, "Docker image argument not supplied")
    def test_validated_options_apply_after_running_and_stopped_saves(self):
        name = f"openlist-options-contract-{os.getpid()}"
        with tempfile.TemporaryDirectory() as directory:
            options_path = Path(directory) / "options.json"

            def save(options):
                saved = json.dumps(validate(options))
                options_path.write_text(saved)
                self.assertEqual(json.loads(options_path.read_text()), options)
                return saved

            def start():
                docker("rm", "-f", name, check=False)
                docker("run", "-d", "--name", name, "-e", "INGRESS_ENTRY=/api/hassio_ingress/options-test",
                       "-v", f"{directory}:/data", IMAGE)
                for _ in range(60):
                    state = json.loads(docker("inspect", name))[0]["State"]
                    self.assertTrue(state["Running"], "Container stopped before becoming healthy")
                    if state["Health"]["Status"] == "healthy":
                        return
                    time.sleep(1)
                self.fail("Options-contract container did not become healthy")

            def check_runtime(predicate):
                docker("exec", name, "jq", "-e", predicate, "/data/.openlist-runtime.json")

            try:
                save(METADATA["options"])
                start()
                checksum = docker("exec", name, "sha256sum", "/data/config.json")
                # Save while running, then recreate exactly as HA's restart does.
                saved = save({"ingress_auto_login": False, "openlist": "tasks:\n  copy:\n    task_persistant: true\ntoken_expires_in: 168\n"})
                start()
                check_runtime(".tasks.copy.task_persistant == true and .token_expires_in == 168")
                self.assertEqual(options_path.read_text(), saved)
                self.assertEqual(docker("exec", name, "sha256sum", "/data/config.json"), checksum)
                # Save while stopped: values must remain and reset only by request.
                docker("rm", "-f", name)
                saved = save({"ingress_auto_login": False, "openlist": "{}"})
                start()
                check_runtime(".tasks.copy.task_persistant == false and .token_expires_in == 48")
                self.assertEqual(options_path.read_text(), saved)
                self.assertEqual(docker("exec", name, "sha256sum", "/data/config.json"), checksum)
                self.assertTrue((Path(directory) / "data.db").exists())
            finally:
                docker("rm", "-f", name, check=False)
                docker("run", "--rm", "--entrypoint", "python3", "-v", f"{directory}:/data", IMAGE,
                       "-c", "import pathlib,shutil; [shutil.rmtree(p) if p.is_dir() else p.unlink() for p in pathlib.Path('/data').iterdir()]", check=False)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]], verbosity=2)
