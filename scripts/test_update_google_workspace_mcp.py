from pathlib import Path
import tempfile
import unittest

from update_google_workspace_mcp import latest_python, latest_stable, plan, read_pins, require_platforms


class GoogleUpdateTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.addon = self.root / "google_workspace_mcp"
        self.addon.mkdir()
        self.pins = {"workspace-mcp": "1.2.3", "fastmcp": "4.0.0", "mcp": "2.0.0"}
        (self.addon / "Dockerfile").write_text(
            "FROM python:3.14-slim@sha256:" + "a" * 64 + "\n"
            "RUN pip install workspace-mcp==1.2.3 fastmcp==4.0.0 mcp==2.0.0\n"
        )
        (self.addon / "config.yaml").write_text('name: Test\nversion: "0.1.2"\n')
        (self.addon / "README.md").write_text(
            "Current add-on release: `0.1.2`.\n"
            "Runtime: Python `3.14`, workspace-mcp `1.2.3`, FastMCP `4.0.0`, MCP `2.0.0`.\n"
        )
        (self.addon / "CHANGELOG.md").write_text("# Changelog\n\n## 0.1.2\n\n- Previous release.\n")

    def test_coordinated_update_and_idempotence(self):
        pins = {"workspace-mcp": "2.2.1", "fastmcp": "4.1.4", "mcp": "2.3.0"}
        digest = "sha256:" + "b" * 64
        changes = plan(self.root, pins, digest)
        self.assertEqual(len(changes), 4)
        self.assertEqual(read_pins(changes["google_workspace_mcp/Dockerfile"])[2:], (digest, pins))
        self.assertIn('version: "0.1.3"', changes["google_workspace_mcp/config.yaml"])
        self.assertIn("Current add-on release: `0.1.3`.", changes["google_workspace_mcp/README.md"])
        self.assertIn("workspace-mcp `2.2.1`", changes["google_workspace_mcp/README.md"])
        self.assertIn("## 0.1.3\n", changes["google_workspace_mcp/CHANGELOG.md"])
        self.assertIn("## 0.1.2\n", changes["google_workspace_mcp/CHANGELOG.md"])
        self.assertEqual(changes, plan(self.root, pins, digest))
        for name, content in changes.items():
            (self.root / name).write_text(content)
        self.assertEqual(plan(self.root, pins, digest), {})

    def test_independent_dependency_and_digest_updates(self):
        for name in (*self.pins, None):
            with self.subTest(component=name):
                pins = dict(self.pins)
                if name:
                    pins[name] = pins[name].rsplit(".", 1)[0] + ".9"
                changes = plan(self.root, pins, "sha256:" + "b" * 64)
                self.assertEqual(len(changes), 4)
                if name:
                    self.assertIn(f"Update {name}", changes["google_workspace_mcp/CHANGELOG.md"])
                else:
                    self.assertNotIn("Update workspace-mcp", changes["google_workspace_mcp/CHANGELOG.md"])
                    self.assertIn("Refresh the pinned Python", changes["google_workspace_mcp/CHANGELOG.md"])

    def test_reject_bad_candidates(self):
        for invalid in ("1.2.2", "2.0.0rc1", "latest", "2.0.0; echo bad"):
            with self.subTest(version=invalid), self.assertRaises(ValueError):
                plan(self.root, {**self.pins, "workspace-mcp": invalid}, "sha256:" + "b" * 64)
        with self.assertRaisesRegex(ValueError, "Invalid image digest"):
            plan(self.root, self.pins, "latest")
        with self.assertRaisesRegex(ValueError, "All runtime package pins"):
            plan(self.root, {"workspace-mcp": "2.0.0"}, "sha256:" + "b" * 64)

    def test_documentation_drift_fails(self):
        readme = self.addon / "README.md"
        readme.write_text(readme.read_text().replace("workspace-mcp `1.2.3`", "workspace-mcp `1.2.0`"))
        with self.assertRaisesRegex(ValueError, "README release/runtime metadata"):
            plan(self.root, self.pins, "sha256:" + "b" * 64)

    def test_stable_release_selection(self):
        def wheel(yanked=False):
            return [{"packagetype": "bdist_wheel", "yanked": yanked}]
        data = {"releases": {
            "1.9.0": wheel(), "1.10.0": wheel(), "2.0.0rc1": wheel(),
            "2.0.0": wheel(True), "3.0.0": [{"packagetype": "sdist", "yanked": False}],
        }}
        self.assertEqual(latest_stable(data), "1.10.0")
        with self.assertRaisesRegex(ValueError, "No stable non-yanked wheel"):
            latest_stable({"releases": {"2.0.0rc1": wheel()}})

    def test_both_architectures_are_required(self):
        manifest = {"manifests": [{"platform": {"os": "linux", "architecture": "amd64"}}]}
        with self.assertRaisesRegex(ValueError, "linux/amd64 and linux/arm64"):
            require_platforms(manifest)
        manifest["manifests"].append({"platform": {"os": "linux", "architecture": "arm64"}})
        require_platforms(manifest)

    def test_python_branch_upgrade_updates_all_release_metadata(self):
        changes = plan(self.root, self.pins, "sha256:" + "b" * 64, "python:3.15-slim")
        self.assertIn("FROM python:3.15-slim@", changes["google_workspace_mcp/Dockerfile"])
        self.assertIn("Runtime: Python `3.15`", changes["google_workspace_mcp/README.md"])
        self.assertIn("Update Python from `3.14` to `3.15`", changes["google_workspace_mcp/CHANGELOG.md"])
        for invalid in ("python:3.13-slim", "python:3.16-rc-slim", "python:latest"):
            with self.subTest(image=invalid), self.assertRaises(ValueError):
                plan(self.root, self.pins, "sha256:" + "b" * 64, invalid)

    def test_official_python_selection_excludes_prerelease_aliases(self):
        source = "Tags: 3.14.1-slim, 3.14-slim\nTags: 3.15-slim, 3-slim, slim\nTags: 3.16-rc-slim\n"
        self.assertEqual(latest_python(source), "python:3.15-slim")
        with self.assertRaises(ValueError):
            latest_python("Tags: 3.16-rc-slim\n")


if __name__ == "__main__":
    unittest.main()
