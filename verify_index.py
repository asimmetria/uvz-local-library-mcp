#!/usr/bin/env python3
"""Run deterministic quality gates against a generated SQLite knowledge index."""

import argparse
import hashlib
import json
import re
import sqlite3
from pathlib import Path

from knowledge_schema import KnowledgeSchemaError, SCHEMA_VERSION, validate_schema
from retrieval_evaluator import evaluate, evaluate_dependency_graph, load_definition


RAW_HTML = re.compile(r"</?(?:article|aside|div|footer|header|main|nav|script|style)\b", re.IGNORECASE)
SECRET_ASSIGNMENT = re.compile(
    r"(?im)^\s*(?:[A-Za-z0-9_.-]+[._-])?"
    r"(?:password|secret|token|private[-_]?key|credential|api[-_]?key)\s*[:=].+$"
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=Path("knowledge.db"))
    parser.add_argument("--audit", type=Path, default=Path("audit-summary.json"))
    parser.add_argument("--cases", type=Path, help="Retrieval evaluation definition")
    parser.add_argument("--expect", action="append", default=[], help="FTS term expected to find at least one chunk; repeatable")
    parser.add_argument("--output", type=Path, default=Path("evaluation-summary.json"))
    options = parser.parse_args()
    if not options.db.exists():
        raise SystemExit("Database does not exist: %s" % options.db)
    report = {
        "database": str(options.db),
        "database_sha256": hashlib.sha256(options.db.read_bytes()).hexdigest(),
        "audit": str(options.audit),
        "expected_schema_version": SCHEMA_VERSION,
        "passed": False,
        "errors": [],
    }
    audit = None
    if not options.audit.exists():
        report["errors"].append("Ingestion audit does not exist: %s" % options.audit)
    else:
        report["audit_sha256"] = hashlib.sha256(options.audit.read_bytes()).hexdigest()
        try:
            audit = json.loads(options.audit.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exception:
            report["errors"].append("Ingestion audit is unreadable: %s" % exception)
    expected = {}
    con = sqlite3.connect(options.db)
    con.row_factory = sqlite3.Row
    try:
        report["schema_version"] = validate_schema(con)
        report["integrity_check"] = con.execute("PRAGMA quick_check").fetchone()[0]
        chunks = con.execute("SELECT count(*) FROM chunks").fetchone()[0]
        generated = con.execute("SELECT count(*) FROM chunks WHERE path GLOB '*/generated/*' OR path GLOB '*/__generated/*'").fetchone()[0]
        generated_dependency_paths = con.execute(
            "SELECT count(*) FROM dependency_usages "
            "WHERE path GLOB '*/generated/*' OR path GLOB '*/__generated/*'"
        ).fetchone()[0]
        orphan_dependency_usages = con.execute(
            "SELECT count(*) FROM dependency_usages AS usage "
            "LEFT JOIN dependency_aliases AS alias ON "
            "alias.catalog_repository = usage.catalog_repository AND "
            "alias.catalog_path = usage.catalog_path AND alias.alias = usage.alias "
            "WHERE alias.alias IS NULL"
        ).fetchone()[0]
        invalid_dependency_provenance = con.execute(
            "SELECT count(*) FROM dependency_usages WHERE "
            "consumer_repository = '' OR consumer_module = '' OR path = '' "
            "OR commit_sha = '' OR line < 1"
        ).fetchone()[0]
        invalid_lines = con.execute("SELECT count(*) FROM chunks WHERE line_start < 1 OR line_end < line_start").fetchone()[0]
        docs = con.execute("SELECT source_id, content FROM chunks WHERE kind IN ('docs', 'usage')").fetchall()
        raw_html = [source_id for source_id, content in docs if RAW_HTML.search(content)]
        configuration = con.execute("SELECT source_id, content FROM chunks WHERE kind = 'configuration'").fetchall()
        possible_secret_leaks = [
            source_id
            for source_id, content in configuration
            if any("<redacted>" not in match.group(0) for match in SECRET_ASSIGNMENT.finditer(content))
        ]
        for term in options.expect:
            try:
                expected[term] = con.execute("SELECT count(*) FROM chunks WHERE chunks MATCH ?", (term,)).fetchone()[0]
            except sqlite3.OperationalError:
                expected[term] = 0
        report.update({
            "chunks": chunks,
            "generated_paths_indexed": generated,
            "generated_dependency_paths": generated_dependency_paths,
            "orphan_dependency_usages": orphan_dependency_usages,
            "invalid_dependency_provenance": invalid_dependency_provenance,
            "invalid_line_ranges": invalid_lines,
            "raw_html_in_docs": len(raw_html),
            "raw_html_sources": raw_html[:20],
            "possible_secret_leaks": len(possible_secret_leaks),
            "possible_secret_sources": possible_secret_leaks[:20],
            "expected_queries": expected,
        })
        audit_failures = []
        if audit is not None:
            if audit.get("schema_version") != SCHEMA_VERSION:
                audit_failures.append("audit schema version does not match runtime")
            if audit.get("database_sha256") != report["database_sha256"]:
                audit_failures.append("audit database checksum does not match knowledge.db")
            if not audit.get("sources"):
                audit_failures.append("audit contains no sources")
            if len(audit.get("source_revisions", [])) != audit.get("sources"):
                audit_failures.append("audit source revision count is incomplete")
            if any(
                not re.fullmatch(r"[0-9a-f]{40,64}", source.get("commit", ""))
                for source in audit.get("source_revisions", [])
            ):
                audit_failures.append("one or more sources have no valid Git commit SHA")
            if audit.get("files_unreadable", 0):
                audit_failures.append("some source files were unreadable")
            if audit.get("chunks_with_raw_html", 0):
                audit_failures.append("indexer reported raw HTML in chunks")
            if audit.get("configuration_values_skipped_no_pyyaml", 0):
                audit_failures.append("configuration values were skipped because PyYAML was unavailable")
            if audit.get("project_contexts_invalid", 0):
                audit_failures.append("one or more project-context.yaml files are invalid")
            if audit.get("dependency_catalogs_seen", 0) and not audit.get("dependency_aliases_indexed", 0):
                audit_failures.append("uvz-platform catalog was found but no dependency aliases were indexed")
        report["audit_failures"] = audit_failures
        retrieval_passed = True
        if options.cases:
            try:
                definition = load_definition(options.cases)
                retrieval = evaluate(con, definition)
                dependency_graph = evaluate_dependency_graph(con, definition)
                report["retrieval_cases"] = str(options.cases)
                report["retrieval_cases_sha256"] = hashlib.sha256(options.cases.read_bytes()).hexdigest()
                report["retrieval_evaluation"] = retrieval
                report["dependency_graph_evaluation"] = dependency_graph
                retrieval_passed = retrieval["passed"] and dependency_graph["passed"]
            except (OSError, ValueError, json.JSONDecodeError, sqlite3.DatabaseError) as exception:
                report["errors"].append("Retrieval evaluation failed: %s" % exception)
                retrieval_passed = False
        report["passed"] = (
            report["integrity_check"] == "ok"
            and bool(chunks)
            and not generated
            and not generated_dependency_paths
            and not orphan_dependency_usages
            and not invalid_dependency_provenance
            and not invalid_lines
            and not raw_html
            and not possible_secret_leaks
            and all(expected.values())
            and audit is not None
            and not audit_failures
            and not report["errors"]
            and retrieval_passed
        )
    except (KnowledgeSchemaError, sqlite3.DatabaseError) as exception:
        report["errors"].append(str(exception))
    finally:
        con.close()
    options.output.parent.mkdir(parents=True, exist_ok=True)
    options.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
