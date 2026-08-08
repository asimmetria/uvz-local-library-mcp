#!/usr/bin/env python3
"""Create a review-required local dependency-case draft from an existing index."""

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from knowledge_schema import validate_database  # noqa: E402


def case_id(alias, position, used):
    base = re.sub(r"[^a-z0-9]+", "-", alias.lower()).strip("-") or "alias"
    candidate = "dependency-%s" % base
    suffix = position
    while candidate in used:
        candidate = "dependency-%s-%d" % (base, suffix)
        suffix += 1
    used.add(candidate)
    return candidate


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as source:
        while True:
            block = source.read(1024 * 1024)
            if not block:
                break
            value.update(block)
    return value.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=ROOT / "knowledge.db")
    parser.add_argument("--base", type=Path, default=ROOT / "evaluation-cases.json")
    parser.add_argument("--output", type=Path, default=ROOT / "evaluation-cases.local.json")
    parser.add_argument("--limit", type=int, default=3, help="Number of distinct positive aliases")
    parser.add_argument(
        "--include-external",
        action="store_true",
        help="Include aliases that cannot be mapped to an indexed workspace library",
    )
    options = parser.parse_args()
    if options.limit < 1:
        raise SystemExit("--limit must be positive")
    if options.output.exists():
        raise SystemExit(
            "Refusing to overwrite %s. Review the existing cases or delete the file explicitly."
            % options.output
        )
    if not options.base.is_file():
        raise SystemExit("Base evaluation definition does not exist: %s" % options.base)
    validate_database(options.db)
    definition = json.loads(options.base.read_text(encoding="utf-8"))
    connection = sqlite3.connect(options.db)
    connection.row_factory = sqlite3.Row
    try:
        query = (
            "SELECT alias.alias, alias.accessor, alias.catalog_repository, alias.catalog_path, "
            "alias.owner_repository, alias.owner_module, "
            "usage.consumer_repository, usage.consumer_module, usage.path, "
            "usage.configuration, usage.line "
            "FROM dependency_aliases AS alias JOIN dependency_usages AS usage ON "
            "usage.catalog_repository = alias.catalog_repository AND "
            "usage.catalog_path = alias.catalog_path AND usage.alias = alias.alias "
            "WHERE usage.configuration != 'unknown' "
        )
        if not options.include_external:
            query += "AND alias.owner_repository != '' "
        query += (
            "ORDER BY alias.alias, usage.consumer_repository, usage.consumer_module, "
            "usage.path, usage.line"
        )
        rows = connection.execute(query).fetchall()
    finally:
        connection.close()
    grouped = {}
    for row in rows:
        identity = (row["catalog_repository"], row["catalog_path"], row["alias"])
        grouped.setdefault(identity, {"alias": row, "consumers": []})["consumers"].append(row)
    candidates = sorted(
        grouped.values(),
        key=lambda item: (-len(item["consumers"]), item["alias"]["alias"], item["alias"]["catalog_path"]),
    )
    if len(candidates) < options.limit:
        scope = "aliases" if options.include_external else "internally owned aliases"
        raise SystemExit(
            "Only %d %s with verified consumers are available; requested %d. "
            "Use --include-external only when external framework dependencies are intentional."
            % (len(candidates), scope, options.limit)
        )
    existing = list(definition.get("dependency_cases", []))
    used_ids = {case.get("id", "") for case in definition.get("cases", []) + existing}
    generated = []
    for position, candidate in enumerate(candidates[:options.limit], 1):
        alias = candidate["alias"]
        consumer = candidate["consumers"][0]
        generated.append({
            "id": case_id(alias["alias"], position, used_ids),
            "query": "libs.%s" % alias["accessor"],
            "expected_aliases": [alias["alias"]],
            "expected_consumers": [{
                "alias": alias["alias"],
                "repository": consumer["consumer_repository"],
                "module": consumer["consumer_module"],
                "path": consumer["path"],
                "configuration": consumer["configuration"],
            }],
        })
    definition["dependency_cases"] = existing + generated
    thresholds = definition.setdefault("thresholds", {})
    positive_count = sum(
        1 for case in definition["dependency_cases"] if not case.get("expect_no_results")
    )
    thresholds["min_dependency_cases"] = max(
        int(thresholds.get("min_dependency_cases", 0)), positive_count
    )
    thresholds["min_dependency_pass_rate"] = 1.0
    definition["dependency_case_draft"] = {
        "review_required": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "database_sha256": digest(options.db),
        "generated_positive_cases": len(generated),
        "selection_scope": (
            "all-aliases" if options.include_external else "internally-owned-aliases"
        ),
        "instruction": (
            "Review every alias and consumer against the source, then set "
            "review_required to false before using this file as a gate."
        ),
    }
    options.output.parent.mkdir(parents=True, exist_ok=True)
    options.output.write_text(
        json.dumps(definition, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print("Created review-required dependency case draft: %s" % options.output)
    for case in generated:
        consumer = case["expected_consumers"][0]
        print(
            "- %s -> %s%s:%s (%s)"
            % (
                case["expected_aliases"][0], consumer["repository"], consumer["module"],
                consumer["path"], consumer["configuration"],
            )
        )


if __name__ == "__main__":
    main()
