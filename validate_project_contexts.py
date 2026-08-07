#!/usr/bin/env python3
"""Validate every project-context.yaml below one Git repository."""

import argparse
import subprocess
from pathlib import Path

from project_context import load_card, validate_card

try:
    import yaml
except ImportError:
    yaml = None


SKIP_DIRS = {".git", ".gradle", ".idea", "build", "dist", "node_modules", "target"}


def git_root(path):
    result = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
        text=True,
        capture_output=True,
    )
    if result.returncode:
        raise ValueError("Not inside a Git repository: %s" % path)
    return Path(result.stdout.strip()).resolve()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repository", type=Path, nargs="?", default=Path.cwd())
    options = parser.parse_args()
    try:
        root = git_root(options.repository.resolve())
    except ValueError as exception:
        raise SystemExit(str(exception))
    cards = sorted(
        path for path in root.rglob("project-context.yaml")
        if not any(part in SKIP_DIRS for part in path.relative_to(root).parts)
    )
    if not cards:
        raise SystemExit("No project-context.yaml files found under %s" % root)
    failures = []
    for path in cards:
        relative = path.relative_to(root).as_posix()
        try:
            card = load_card(path.read_text(encoding="utf-8"), yaml)
            errors = validate_card(card, root)
        except (OSError, ValueError) as exception:
            errors = [str(exception)]
        if errors:
            failures.append((relative, errors))
            print("FAIL: %s" % relative)
            for error in errors:
                print("  - %s" % error)
        else:
            print("OK: %s" % relative)
    if failures:
        raise SystemExit("%d of %d project context cards are invalid" % (len(failures), len(cards)))
    print("Validated %d project context cards" % len(cards))


if __name__ == "__main__":
    main()
