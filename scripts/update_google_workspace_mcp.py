"""Plan coordinated Google Workspace MCP releases without executing upstream code."""

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from urllib.request import urlopen


PACKAGES = ("workspace-mcp", "fastmcp", "mcp")
ADDON = "google_workspace_mcp"


def version(value):
    if not re.fullmatch(r"\d+\.\d+\.\d+", value):
        raise ValueError("Expected a stable three-part release version")
    return tuple(map(int, value.split(".")))


def latest_stable(metadata):
    candidates = []
    for release, files in metadata["releases"].items():
        if re.fullmatch(r"\d+\.\d+\.\d+", release) and any(
            not item.get("yanked", False) and item["packagetype"] == "bdist_wheel"
            for item in files
        ):
            candidates.append(release)
    if not candidates:
        raise ValueError("No stable non-yanked wheel release found")
    return max(candidates, key=version)


def read_pins(dockerfile):
    base = re.search(r"^FROM (python:([\d.]+)-slim)@(sha256:[a-f0-9]{64})$", dockerfile, re.M)
    if base is None:
        raise ValueError("Expected a pinned Python slim image")
    pins = {}
    for package in PACKAGES:
        matches = re.findall(r"(?<![\w-])" + re.escape(package) + r"==([\d.]+)(?![\w.])", dockerfile)
        if len(matches) != 1:
            raise ValueError(f"Expected exactly one {package} pin")
        version(matches[0])
        pins[package] = matches[0]
    return base[1], base[2], base[3], pins


def require_platforms(manifest):
    platforms = {
        (item.get("platform", {}).get("os"), item.get("platform", {}).get("architecture"))
        for item in manifest.get("manifests", [])
    }
    if not {("linux", "amd64"), ("linux", "arm64")} <= platforms:
        raise ValueError("Python image must support linux/amd64 and linux/arm64")


def runtime_line(python, pins):
    return (f"Runtime: Python `{python}`, workspace-mcp `{pins['workspace-mcp']}`, "
            f"FastMCP `{pins['fastmcp']}`, MCP `{pins['mcp']}`.")


def plan(root, pins, digest):
    if set(pins) != set(PACKAGES):
        raise ValueError("All runtime package pins are required")
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", digest):
        raise ValueError("Invalid image digest")
    dockerfile = (root / ADDON / "Dockerfile").read_text()
    image, python, old_digest, old_pins = read_pins(dockerfile)
    for name in PACKAGES:
        if version(pins[name]) < version(old_pins[name]):
            raise ValueError("Refusing a package downgrade")
    if pins == old_pins and digest == old_digest:
        return {}
    config = (root / ADDON / "config.yaml").read_text()
    old_package = re.search(r'^version: "([\d.]+)"$', config, re.M)[1]
    major, minor, patch = version(old_package)
    package = f"{major}.{minor}.{patch + 1}"
    updated_docker = dockerfile.replace(f"{image}@{old_digest}", f"{image}@{digest}", 1)
    notes = []
    for name in PACKAGES:
        updated_docker = updated_docker.replace(f"{name}=={old_pins[name]}", f"{name}=={pins[name]}", 1)
        if pins[name] != old_pins[name]:
            notes.append(f"- Update {name} from `{old_pins[name]}` to `{pins[name]}`.")
    if digest != old_digest:
        notes.append(f"- Refresh the pinned Python {python} base image digest.")
    readme = (root / ADDON / "README.md").read_text()
    old_release = f"Current add-on release: `{old_package}`."
    old_runtime = runtime_line(python, old_pins)
    if readme.count(old_release) != 1 or readme.count(old_runtime) != 1:
        raise ValueError("README release/runtime metadata differs from the package pins")
    readme = readme.replace(old_release, f"Current add-on release: `{package}`.", 1)
    readme = readme.replace(old_runtime, runtime_line(python, pins), 1)
    changelog = (root / ADDON / "CHANGELOG.md").read_text()
    if not changelog.startswith("# Changelog\n"):
        raise ValueError("Missing changelog heading")
    entry = "# Changelog\n\n## " + package + "\n\n" + "\n".join(notes) + "\n"
    return {
        f"{ADDON}/Dockerfile": updated_docker,
        f"{ADDON}/config.yaml": config.replace(f'version: "{old_package}"', f'version: "{package}"', 1),
        f"{ADDON}/README.md": readme,
        f"{ADDON}/CHANGELOG.md": changelog.replace("# Changelog\n", entry, 1),
    }


def main():
    root = Path(__file__).resolve().parents[1]
    image, _, _, old_pins = read_pins((root / ADDON / "Dockerfile").read_text())
    pins = {}
    for name in PACKAGES:
        with urlopen(f"https://pypi.org/pypi/{name}/json", timeout=30) as response:
            candidate = latest_stable(json.load(response))
        # A yanked release must never turn a later scheduled run into a downgrade.
        pins[name] = max((old_pins[name], candidate), key=version)
    inspection = subprocess.check_output([
        "docker", "buildx", "imagetools", "inspect", image,
    ], text=True)
    digest = re.search(r"^Digest:\s+(sha256:[a-f0-9]{64})$", inspection, re.M)[1]
    manifest = json.loads(subprocess.check_output([
        "docker", "buildx", "imagetools", "inspect", "--raw", f"{image}@{digest}",
    ], text=True))
    require_platforms(manifest)
    changes = plan(root, pins, digest)
    for name, content in changes.items():
        (root / name).write_text(content)
    fingerprint = hashlib.sha256(json.dumps([pins, digest], sort_keys=True).encode()).hexdigest()[:12]
    target = f"v{pins['workspace-mcp']}-{fingerprint}"
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as output:
            output.write(f"changed={'true' if changes else 'false'}\ntarget={target}\n")
    print(f"{target}: {'updated ' + str(len(changes)) + ' files' if changes else 'already current'}")


if __name__ == "__main__":
    main()
