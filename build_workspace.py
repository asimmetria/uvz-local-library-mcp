#!/usr/bin/env python3
"""Discover Git roots below a workspace and build one local knowledge pack."""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


SKIP = {".git", ".gradle", ".idea", "build", "node_modules", "target"}


def excluded_names(path):
    if path is None:
        return set()
    return {
        line.split("#", 1)[0].strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.split("#", 1)[0].strip()
    }


def invalid_git_revisions(roots):
    invalid = []
    for root in sorted(roots):
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--verify", "HEAD"],
            text=True,
            capture_output=True,
        )
        revision = result.stdout.strip()
        if result.returncode or not re.fullmatch(r"[0-9a-f]{40,64}", revision):
            reason = result.stderr.strip().splitlines()
            invalid.append((root, reason[-1] if reason else "no commit at HEAD"))
    return invalid


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("workspace", type=Path)
    parser.add_argument("--sync", action="store_true")
    parser.add_argument("--configuration-root", action="append", type=Path, default=[])
    parser.add_argument("--exclude-file", type=Path, help="One exact Git root directory name per line")
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).parent)
    parser.add_argument("--evaluation-cases", type=Path, default=Path(__file__).with_name("evaluation-cases.json"))
    options = parser.parse_args()
    workspace = options.workspace.resolve()
    if not options.evaluation_cases.is_file():
        raise SystemExit("Retrieval evaluation cases do not exist: %s" % options.evaluation_cases)
    roots = []
    for git_dir in workspace.rglob(".git"):
        if not git_dir.is_dir() or any(part in SKIP - {".git"} for part in git_dir.parts):
            continue
        root = git_dir.parent
        if not any(parent in roots for parent in root.parents):
            roots.append(root)
    excluded = excluded_names(options.exclude_file)
    skipped = sorted(root.name for root in roots if root.name in excluded)
    roots = [root for root in roots if root.name not in excluded]
    if not roots:
        raise SystemExit("No Git repositories found under %s" % workspace)
    if skipped:
        print("Excluded from indexing: " + ", ".join(skipped), flush=True)
    invalid = invalid_git_revisions(roots)
    if invalid:
        details = "\n".join(
            "- %s (%s): %s" % (root.name, root, reason)
            for root, reason in invalid
        )
        raise SystemExit(
            "Cannot build the index because these repositories have no valid Git HEAD:\n"
            + details
            + "\nFix the repository or add its directory name to the index exclude file."
        )
    output_dir = options.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    final = {
        "database": output_dir / "knowledge.db",
        "catalog": output_dir / "skills/library-knowledge-workflow/generated-catalog.md",
        "audit": output_dir / "audit-summary.json",
        "evaluation": output_dir / "evaluation-summary.json",
        "cases": output_dir / "evaluation-cases.built.json",
    }
    with tempfile.TemporaryDirectory(prefix="knowledge-build-", dir=str(output_dir)) as directory:
        staging = Path(directory)
        candidate = {
            "database": staging / "knowledge.db",
            "catalog": staging / "generated-catalog.md",
            "audit": staging / "audit-summary.json",
            "evaluation": staging / "evaluation-summary.json",
            "cases": staging / "evaluation-cases.json",
        }
        command = [sys.executable, str(Path(__file__).with_name("knowledge_indexer.py")), "--pack", "workspace", "--db", str(candidate["database"]), "--catalog", str(candidate["catalog"]), "--audit", str(candidate["audit"])]
        for root in sorted(roots):
            command += ["--source", str(root)]
        if options.sync:
            command.append("--sync")
        for root in options.configuration_root:
            command += ["--configuration-root", str(root.resolve())]
        for name in skipped:
            command += ["--excluded-source", name]
        code = subprocess.call(command)
        if code:
            raise SystemExit(code)
        audit = json.loads(candidate["audit"].read_text(encoding="utf-8"))
        audit["database"] = "knowledge.db"
        audit["catalog"] = "skills/library-knowledge-workflow/generated-catalog.md"
        candidate["audit"].write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
        code = subprocess.call([
            sys.executable,
            str(Path(__file__).with_name("verify_index.py")),
            "--db", str(candidate["database"]),
            "--audit", str(candidate["audit"]),
            "--cases", str(options.evaluation_cases.resolve()),
            "--output", str(candidate["evaluation"]),
        ])
        if code:
            raise SystemExit(code)
        shutil.copyfile(str(options.evaluation_cases.resolve()), str(candidate["cases"]))
        evaluation = json.loads(candidate["evaluation"].read_text(encoding="utf-8"))
        evaluation["database"] = "knowledge.db"
        evaluation["audit"] = "audit-summary.json"
        evaluation["retrieval_cases"] = "evaluation-cases.built.json"
        candidate["evaluation"].write_text(
            json.dumps(evaluation, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        for name in ("catalog", "audit", "evaluation", "cases", "database"):
            final[name].parent.mkdir(parents=True, exist_ok=True)
            os.replace(str(candidate[name]), str(final[name]))
    print("Published verified knowledge index: %s" % final["database"])


if __name__ == "__main__":
    main()
