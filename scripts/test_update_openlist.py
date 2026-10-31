import tempfile
from pathlib import Path
import re
import unittest
from update_openlist import plan, version


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        source = Path(__file__).resolve().parents[1]
        docker = (source / "openlist/Dockerfile").read_text()
        current_tag = re.search(r"^FROM docker.io/openlistteam/openlist:(v[\d.]+)@", docker, re.M)[1]
        for name in ("openlist/Dockerfile", "openlist/config.yaml", "README.md", "openlist/README.md", "openlist/DOCS.md", "openlist/CHANGELOG.md"):
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text((source / name).read_text().replace(current_tag, "v4.2.4"))

    def test_coordinated_bump(self):
        changes = plan(self.root, "v4.2.7", "sha256:" + "a" * 64)
        self.assertEqual(len(changes), 6)
        self.assertIn("v4.2.7@sha256:" + "a" * 64, changes["openlist/Dockerfile"])
        config = (self.root / "openlist/config.yaml").read_text()
        old_package = re.search(r'^version: "([\d.]+)"$', config, re.M)[1]
        major, minor, patch = version(old_package)
        package = f"{major}.{minor}.{patch + 1}"
        self.assertIn(f'version: "{package}"', changes["openlist/config.yaml"])
        self.assertIn(f'ARG BUILD_VERSION="{package}"', changes["openlist/Dockerfile"])
        self.assertIn(f"## {package}\n", changes["openlist/CHANGELOG.md"])
        for name in ("README.md", "openlist/README.md", "openlist/DOCS.md"):
            self.assertIn("v4.2.7", changes[name])
            self.assertNotIn("v4.2.4", changes[name])
        for name, content in changes.items():
            (self.root / name).write_text(content)
        self.assertEqual(plan(self.root, "v4.2.7", "sha256:" + "a" * 64), {})

    def test_successive_patch_updates(self):
        for patch in range(5, 10):
            tag = f"v4.2.{patch}"
            with self.subTest(tag=tag):
                changes = plan(self.root, tag, "sha256:" + "b" * 64)
                self.assertEqual(len(changes), 6)
                for name, content in changes.items():
                    (self.root / name).write_text(content)
                self.assertEqual(plan(self.root, tag, "sha256:" + "b" * 64), {})

    def test_accept_minor_and_major_after_the_same_release_planning(self):
        for tag in ("v4.3.0", "v5.0.0"):
            with self.subTest(tag=tag):
                changes = plan(self.root, tag, "sha256:" + "a" * 64)
                self.assertEqual(len(changes), 6)
                self.assertIn(f"openlist:{tag}@sha256:", changes["openlist/Dockerfile"])
                self.assertIn(tag, changes["openlist/DOCS.md"])

    def test_reject_prerelease(self):
        for tag in ("v4.2.8-beta", "latest"):
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                plan(self.root, tag, "sha256:" + "a" * 64)

    def test_no_downgrade(self):
        self.assertEqual(plan(self.root, "v4.2.3", "sha256:" + "a" * 64), {})

    def test_bad_digest_and_version_drift(self):
        with self.assertRaisesRegex(ValueError, "Invalid image digest"):
            plan(self.root, "v4.2.7", "latest")
        config = self.root / "openlist/config.yaml"
        config.write_text(re.sub(r'^version: "[\d.]+"$', 'version: "99.0.0"', config.read_text(), flags=re.M))
        with self.assertRaisesRegex(ValueError, "Dockerfile and config.yaml versions differ"):
            plan(self.root, "v4.2.7", "sha256:" + "a" * 64)


if __name__ == "__main__":
    unittest.main()
