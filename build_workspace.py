#!/usr/bin/env python3
"""Discover Git roots below a workspace and build one local knowledge pack."""

import argparse
import subprocess
import sys
from pathlib import Path


SKIP = {".git", ".gradle", ".idea", "build", "node_modules", "target"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("workspace", type=Path)
    parser.add_argument("--sync", action="store_true")
    parser.add_argument("--configuration-root", action="append", type=Path, default=[])
    options = parser.parse_args()
    workspace = options.workspace.resolve()
    roots = []
    for git_dir in workspace.rglob(".git"):
        if not git_dir.is_dir() or any(part in SKIP - {".git"} for part in git_dir.parts):
            continue
        root = git_dir.parent
        if not any(parent in roots for parent in root.parents):
            roots.append(root)
    if not roots:
        raise SystemExit("No Git repositories found under %s" % workspace)
    command = [sys.executable, str(Path(__file__).with_name("knowledge_indexer.py")), "--pack", "workspace", "--db", str(Path(__file__).with_name("knowledge.db")), "--catalog", str(Path(__file__).with_name("skill") / "generated-catalog.md"), "--audit", str(Path(__file__).with_name("audit-summary.json"))]
    for root in sorted(roots):
        command += ["--source", str(root)]
    if options.sync:
        command.append("--sync")
    for root in options.configuration_root:
        command += ["--configuration-root", str(root.resolve())]
    raise SystemExit(subprocess.call(command))


if __name__ == "__main__":
    main()
