#!/usr/bin/env python3
"""Verify and install a portable knowledge-pack archive into this project."""

import argparse
import hashlib
import json
import zipfile
from pathlib import Path


FILES = {
    "knowledge.db": "knowledge.db",
    "generated-catalog.md": "skill/generated-catalog.md",
    "evaluation-summary.json": "audit-summary.json",
}


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    parser.add_argument("--destination", type=Path, default=Path("."))
    options = parser.parse_args()
    with zipfile.ZipFile(options.archive) as pack:
        manifest = json.loads(pack.read("manifest.json"))
        for archive_name, target_name in FILES.items():
            payload = pack.read(archive_name)
            expected = manifest["files"][archive_name]["sha256"]
            if sha256(payload) != expected:
                raise SystemExit("Checksum mismatch: %s" % archive_name)
            target = options.destination / target_name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
    print("Installed knowledge pack %s" % manifest["version"])


if __name__ == "__main__":
    main()
