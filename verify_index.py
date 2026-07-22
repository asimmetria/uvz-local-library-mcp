#!/usr/bin/env python3
"""Run deterministic quality gates against a generated SQLite knowledge index."""

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path


RAW_HTML = re.compile(r"</?(?:article|aside|div|footer|header|main|nav|script|style)\b", re.IGNORECASE)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=Path("knowledge.db"))
    parser.add_argument("--expect", action="append", default=[], help="FTS term expected to find at least one chunk; repeatable")
    parser.add_argument("--output", type=Path, default=Path("evaluation-summary.json"))
    options = parser.parse_args()
    if not options.db.exists():
        raise SystemExit("Database does not exist: %s" % options.db)
    con = sqlite3.connect(options.db)
    chunks = con.execute("SELECT count(*) FROM chunks").fetchone()[0]
    generated = con.execute("SELECT count(*) FROM chunks WHERE path GLOB '*/generated/*' OR path GLOB '*/__generated/*'").fetchone()[0]
    docs = con.execute("SELECT source_id, content FROM chunks WHERE kind = 'docs'").fetchall()
    raw_html = [source_id for source_id, content in docs if RAW_HTML.search(content)]
    expected = {}
    for term in options.expect:
        try:
            expected[term] = con.execute("SELECT count(*) FROM chunks WHERE chunks MATCH ?", (term,)).fetchone()[0]
        except sqlite3.OperationalError:
            expected[term] = 0
    con.close()
    report = {
        "database": str(options.db),
        "chunks": chunks,
        "generated_paths_indexed": generated,
        "raw_html_in_docs": len(raw_html),
        "raw_html_sources": raw_html[:20],
        "expected_queries": expected,
        "passed": bool(chunks) and not generated and not raw_html and all(expected.values()),
    }
    options.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
