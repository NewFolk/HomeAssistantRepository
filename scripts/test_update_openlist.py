import tempfile
from pathlib import Path
import unittest
from update_openlist import plan, version


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        source = Path(__file__).resolve().parents[1]
        for name in ("openlist/Dockerfile", "openlist/config.yaml", "README.md", "openlist/README.md", "openlist/DOCS.md", "openlist/CHANGELOG.md"):
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text((source / name).read_text().replace("v4.2.7", "v4.2.4"))

    def test_coordinated_bump(self):
        changes = plan(self.root, "v4.2.7", "sha256:" + "a" * 64)
        self.assertEqual(len(changes), 6)
        self.assertIn("v4.2.7@sha256:", changes["openlist/Dockerfile"])
        self.assertNotIn("v4.2.4", changes["README.md"])
        for name, content in changes.items():
            (self.root / name).write_text(content)
        self.assertEqual(plan(self.root, "v4.2.7", "sha256:" + "a" * 64), {})

    def test_reject_minor_major_and_prerelease(self):
        for tag in ("v4.3.0", "v5.0.0", "v4.2.8-beta", "latest"):
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                plan(self.root, tag, "sha256:" + "a" * 64)

    def test_no_downgrade(self):
        self.assertEqual(plan(self.root, "v4.2.3", "sha256:" + "a" * 64), {})

    def test_bad_digest_and_version_drift(self):
        with self.assertRaises(ValueError):
            plan(self.root, "v4.2.7", "latest")
        config = self.root / "openlist/config.yaml"
        config.write_text(config.read_text().replace('version: "', 'version: "99.'))
        with self.assertRaises(ValueError):
            plan(self.root, "v4.2.7", "sha256:" + "a" * 64)


if __name__ == "__main__":
    unittest.main()
