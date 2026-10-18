#!/usr/bin/env python3
"""Decode the Supervisor-persisted string without changing options.json."""

import json
from pathlib import Path
import sys

import yaml


def parse_options(path):
    text = Path(path).read_text()
    options = json.loads(text) if text.strip() else {}
    if not isinstance(options, dict):
        raise ValueError("HA options must be an object")
    value = options.get("openlist", {})
    if isinstance(value, str):
        value = yaml.safe_load(value) if value.strip() else {}
    # Accept legacy objects only for existing on-disk fixtures/manual migrations.
    # HA's supported schema requires a string; arbitrary dictionaries are stripped.
    if not isinstance(value, dict):
        raise ValueError("openlist must contain a YAML/JSON object")
    options["openlist"] = value
    return json.dumps(options, allow_nan=False)


def main():
    try:
        result = parse_options(sys.argv[1])
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
