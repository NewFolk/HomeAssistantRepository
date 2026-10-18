#!/usr/bin/env python3
"""Decode the Supervisor-persisted string without changing options.json."""

import argparse
import json
from pathlib import Path
import re
import sys

import yaml


class UniqueKeyLoader(yaml.SafeLoader):
    """Reject duplicate explicit keys instead of silently losing an override."""


def unique_mapping(loader, node, deep=False):
    seen = set()
    for key_node, _ in node.value:
        if key_node.tag == "tag:yaml.org,2002:merge":
            continue
        key = loader.construct_object(key_node, deep=deep)
        if key in seen:
            raise yaml.constructor.ConstructorError(
                None, None, "duplicate mapping key", key_node.start_mark
            )
        seen.add(key)
    return yaml.SafeLoader.construct_mapping(loader, node, deep=deep)


UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping
)


def parse_options(path):
    text = Path(path).read_text()
    options = json.loads(text) if text.strip() else {}
    if not isinstance(options, dict):
        raise ValueError("HA options must be an object")
    value = options.get("openlist", {})
    if isinstance(value, str):
        value = yaml.load(value, Loader=UniqueKeyLoader) if value.strip() else {}
    # Accept legacy objects only for existing on-disk fixtures/manual migrations.
    # HA's supported schema requires a string; arbitrary dictionaries are stripped.
    if not isinstance(value, dict):
        raise ValueError("openlist must contain a YAML/JSON object")
    options["openlist"] = value
    return json.dumps(options, allow_nan=False)


def compare_overrides(wanted, actual, path="openlist"):
    """Walk only user-supplied paths; upstream may add default object members."""
    verified, errors = [], []
    if type(wanted) is not type(actual):
        return [], [(path, "value/type differs")]
    if isinstance(wanted, dict):
        for key, value in wanted.items():
            # Field names are useful diagnostics, but arbitrary keys can contain
            # pasted secrets or control characters. Never print those verbatim.
            label = key if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", key) else "<invalid-key>"
            child = f"{path}.{label}"
            if key not in actual:
                errors.append((child, "unknown or discarded field"))
            else:
                accepted, rejected = compare_overrides(value, actual[key], child)
                verified.extend(accepted)
                errors.extend(rejected)
        if not wanted:
            verified.append(path)
    elif isinstance(wanted, list):
        if len(wanted) != len(actual):
            errors.append((path, "array length differs"))
        else:
            for index, value in enumerate(wanted):
                accepted, rejected = compare_overrides(value, actual[index], f"{path}[{index}]")
                verified.extend(accepted)
                errors.extend(rejected)
            if not wanted:
                verified.append(path)
    elif wanted != actual:
        errors.append((path, "value/type differs"))
    else:
        verified.append(path)
    return verified, errors


def verify_options(options, runtime):
    """Verify against the working config AFTER OpenList has decoded/rebuilt it."""
    wanted = options["openlist"]
    verified, errors = compare_overrides(wanted, runtime)
    if errors:
        for path, reason in errors:
            print(f"[ERROR] HA override not accepted by OpenList: {path} ({reason}); check spelling, nesting and type", file=sys.stderr)
        return 1
    if not wanted:
        print("[INFO] No HA OpenList overrides configured")
    else:
        for path in verified:
            print(f"[INFO] Verified HA override after OpenList load: {path}")
        print(f"[INFO] All {len(verified)} HA OpenList override paths verified; values omitted")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("options", type=Path)
    parser.add_argument("--verify", type=Path, metavar="RUNTIME_CONFIG")
    args = parser.parse_args()
    try:
        result = parse_options(args.options)
        if args.verify:
            return verify_options(json.loads(result), json.loads(args.verify.read_text()))
    except yaml.YAMLError as error:
        mark = getattr(error, "problem_mark", None)
        location = f" (line {mark.line + 1}, column {mark.column + 1})" if mark else ""
        print(f"[ERROR] Invalid YAML in openlist{location}; configuration values omitted", file=sys.stderr)
        return 1
    except (OSError, ValueError, TypeError, RecursionError):
        print("[ERROR] Cannot parse HA options: openlist must be a YAML/JSON object with JSON-compatible values; configuration values omitted", file=sys.stderr)
        return 1
    print(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
