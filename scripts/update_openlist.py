"""Synchronize stable releases with the HA package; never execute upstream code."""
import json
import os
from pathlib import Path
import re
import subprocess


def version(value):
    if not re.fullmatch(r"v?\d+\.\d+\.\d+", value):
        raise ValueError(f"Not a stable semantic version: {value!r}")
    return tuple(map(int, value.lstrip("v").split(".")))


def plan(root, tag, digest):
    version(tag)
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", digest):
        raise ValueError("Invalid image digest")
    docker = (root / "openlist/Dockerfile").read_text()
    old_tag = re.search(r"^FROM docker.io/openlistteam/openlist:(v[\d.]+)@sha256:[a-f0-9]{64}$", docker, re.M)[1]
    if version(tag) <= version(old_tag):
        return {}
    config = (root / "openlist/config.yaml").read_text()
    old_package = re.search(r'^version: "([\d.]+)"$', config, re.M)[1]
    major, minor, patch = version(old_package)
    package = f"{major}.{minor}.{patch + 1}"
    if f'ARG BUILD_VERSION="{old_package}"' not in docker:
        raise ValueError("Dockerfile and config.yaml versions differ")
    changes = {
        "openlist/Dockerfile": re.sub(r"^FROM .*", f"FROM docker.io/openlistteam/openlist:{tag}@{digest}", docker, count=1).replace(f'ARG BUILD_VERSION="{old_package}"', f'ARG BUILD_VERSION="{package}"'),
        "openlist/config.yaml": config.replace(f'version: "{old_package}"', f'version: "{package}"', 1),
    }
    for name in ("README.md", "openlist/README.md", "openlist/DOCS.md"):
        content = (root / name).read_text()
        if old_tag not in content:
            raise ValueError(f"Upstream version missing from {name}")
        changes[name] = content.replace(old_tag, tag)
    changelog = (root / "openlist/CHANGELOG.md").read_text()
    changes["openlist/CHANGELOG.md"] = changelog.replace(
        "# Changelog\n", f"# Changelog\n\n## {package}\n\n- Update OpenList from `{old_tag}` to `{tag}` with a pinned image digest.\n", 1)
    return changes


def main():
    root = Path(__file__).resolve().parents[1]
    release = json.loads(subprocess.check_output([
        "gh", "api", "repos/OpenListTeam/OpenList/releases/latest"], text=True))
    if release["draft"] or release["prerelease"]:
        raise ValueError("Refusing a draft/prerelease")
    tag = release["tag_name"]
    version(tag)
    inspection = subprocess.check_output([
        "docker", "buildx", "imagetools", "inspect", f"docker.io/openlistteam/openlist:{tag}"], text=True)
    digest = re.search(r"^Digest:\s+(sha256:[a-f0-9]{64})$", inspection, re.M)[1]
    manifest = json.loads(subprocess.check_output([
        "docker", "buildx", "imagetools", "inspect", "--raw",
        f"docker.io/openlistteam/openlist@{digest}"], text=True))
    if not any(m.get("platform", {}).get("architecture") == "amd64" and m["platform"].get("os") == "linux" for m in manifest.get("manifests", [])):
        raise ValueError("Image has no linux/amd64 manifest")
    changes = plan(root, tag, digest)
    for name, content in changes.items():
        (root / name).write_text(content)
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as output:
            output.write(f"changed={'true' if changes else 'false'}\ntag={tag}\n")
    print(f"{tag}: {'updated ' + str(len(changes)) + ' files' if changes else 'already current'}")


if __name__ == "__main__":
    main()
