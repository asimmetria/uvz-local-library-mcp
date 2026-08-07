#!/usr/bin/env python3
"""Create a versioned portable knowledge-pack archive from local build output."""

import argparse
import hashlib
import json
import os
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from knowledge_schema import SCHEMA_VERSION, validate_database


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=Path("knowledge.db"))
    parser.add_argument("--catalog", type=Path, default=Path("skills/library-knowledge-workflow/generated-catalog.md"))
    parser.add_argument("--audit", type=Path, default=Path("audit-summary.json"))
    parser.add_argument("--evaluation", type=Path, default=Path("evaluation-summary.json"))
    parser.add_argument("--cases", type=Path, help="Defaults to the cases path recorded by evaluation")
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", type=Path, default=Path("dist"))
    options = parser.parse_args()
    required = (options.db, options.catalog, options.audit, options.evaluation)
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise SystemExit("Cannot package missing files: " + ", ".join(missing))
    schema_version = validate_database(options.db)
    database_sha256 = digest(options.db)
    audit = json.loads(options.audit.read_text(encoding="utf-8"))
    evaluation = json.loads(options.evaluation.read_text(encoding="utf-8"))
    cases = options.cases
    if cases is None:
        recorded_cases = Path(evaluation.get("retrieval_cases", ""))
        cases = recorded_cases if recorded_cases.is_absolute() else options.evaluation.parent / recorded_cases
    if not cases.is_file():
        raise SystemExit("Cannot package missing retrieval cases: %s" % cases)
    archive_files = {
        "knowledge.db": options.db,
        "generated-catalog.md": options.catalog,
        "audit-summary.json": options.audit,
        "evaluation-summary.json": options.evaluation,
        "evaluation-cases.json": cases,
    }
    if not evaluation.get("passed"):
        raise SystemExit("Cannot package an index that failed evaluation")
    if not evaluation.get("retrieval_evaluation", {}).get("passed"):
        raise SystemExit("Cannot package an index without a successful retrieval evaluation")
    if evaluation.get("retrieval_cases_sha256") != digest(cases):
        raise SystemExit("Retrieval evaluation is stale: its cases checksum does not match")
    if evaluation.get("database_sha256") != database_sha256:
        raise SystemExit("Evaluation is stale: its database checksum does not match knowledge.db")
    if evaluation.get("audit_sha256") != digest(options.audit):
        raise SystemExit("Evaluation is stale: its audit checksum does not match audit-summary.json")
    if evaluation.get("schema_version") != schema_version:
        raise SystemExit("Evaluation schema version does not match knowledge.db")
    if audit.get("database_sha256") != database_sha256:
        raise SystemExit("Audit is stale: its database checksum does not match knowledge.db")
    manifest = {
        "version": options.version,
        "schema_version": SCHEMA_VERSION,
        "pack": audit.get("pack"),
        "index_built_at": audit.get("built_at"),
        "packaged_at": datetime.now(timezone.utc).isoformat(),
        "sources": audit.get("source_revisions", []),
        "files": {name: {"sha256": digest(path), "size": path.stat().st_size} for name, path in archive_files.items()},
    }
    options.output.mkdir(parents=True, exist_ok=True)
    archive = options.output / ("knowledge-pack-" + options.version + ".zip")
    handle = tempfile.NamedTemporaryFile(
        prefix=archive.name + ".", suffix=".tmp", dir=str(options.output), delete=False
    )
    staged_archive = Path(handle.name)
    handle.close()
    try:
        with zipfile.ZipFile(staged_archive, "w", compression=zipfile.ZIP_DEFLATED) as out:
            for name, path in archive_files.items():
                out.write(path, name)
            out.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        os.replace(str(staged_archive), str(archive))
    finally:
        if staged_archive.exists():
            staged_archive.unlink()
    print(archive)


if __name__ == "__main__":
    main()
