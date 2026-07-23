#!/usr/bin/env python3
"""Create a versioned portable knowledge-pack archive from local build output."""

import argparse
import hashlib
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=Path("knowledge.db"))
    parser.add_argument("--catalog", type=Path, default=Path("skills/library-knowledge-workflow/generated-catalog.md"))
    parser.add_argument("--audit", type=Path, default=Path("audit-summary.json"))
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", type=Path, default=Path("dist"))
    options = parser.parse_args()
    required = (options.db, options.catalog, options.audit)
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise SystemExit("Cannot package missing files: " + ", ".join(missing))
    archive_files = {
        "knowledge.db": options.db,
        "generated-catalog.md": options.catalog,
        "evaluation-summary.json": options.audit,
    }
    manifest = {
        "version": options.version,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "files": {name: {"sha256": digest(path), "size": path.stat().st_size} for name, path in archive_files.items()},
    }
    options.output.mkdir(parents=True, exist_ok=True)
    archive = options.output / ("knowledge-pack-" + options.version + ".zip")
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as out:
        for name, path in archive_files.items():
            out.write(path, name)
        out.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    print(archive)


if __name__ == "__main__":
    main()
