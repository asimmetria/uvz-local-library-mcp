#!/usr/bin/env python3
"""Verify and install a portable knowledge-pack archive into this project."""

import argparse
import hashlib
import json
import os
import tempfile
import zipfile
from pathlib import Path

from knowledge_schema import SCHEMA_VERSION, validate_database


FILES = {
    "generated-catalog.md": "skills/library-knowledge-workflow/generated-catalog.md",
    "audit-summary.json": "audit-summary.json",
    "evaluation-summary.json": "evaluation-summary.json",
    "knowledge.db": "knowledge.db",
}


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    parser.add_argument("--destination", type=Path, default=Path("."))
    options = parser.parse_args()
    options.destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(options.archive) as pack:
        manifest = json.loads(pack.read("manifest.json"))
        if manifest.get("schema_version") != SCHEMA_VERSION:
            raise SystemExit(
                "Knowledge pack schema %s is incompatible with installer schema %s"
                % (manifest.get("schema_version", "missing"), SCHEMA_VERSION)
            )
        with tempfile.TemporaryDirectory(prefix="knowledge-pack-install-", dir=str(options.destination)) as directory:
            staging = Path(directory)
            staged_files = {}
            for archive_name, target_name in FILES.items():
                file_manifest = manifest.get("files", {}).get(archive_name)
                if not file_manifest:
                    raise SystemExit("Knowledge pack manifest is missing: %s" % archive_name)
                payload = pack.read(archive_name)
                if len(payload) != file_manifest.get("size"):
                    raise SystemExit("Size mismatch: %s" % archive_name)
                if sha256(payload) != file_manifest.get("sha256"):
                    raise SystemExit("Checksum mismatch: %s" % archive_name)
                staged = staging / archive_name
                staged.write_bytes(payload)
                staged_files[target_name] = staged
            validate_database(staged_files["knowledge.db"])
            # Publish metadata first and the validated database last. A running
            # MCP therefore never observes a partially written SQLite file.
            for target_name, staged in staged_files.items():
                target = options.destination / target_name
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(str(staged), str(target))
    print("Installed knowledge pack %s" % manifest["version"])


if __name__ == "__main__":
    main()
