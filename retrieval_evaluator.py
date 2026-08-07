#!/usr/bin/env python3
"""Deterministic lexical retrieval evaluation for a SQLite knowledge index."""

import json
import re


def fts_query(value):
    terms = re.findall(r"[\w-]+", value, flags=re.UNICODE)
    return " ".join('"%s"' % term.replace('"', '""') for term in terms)


def source_name(row):
    return "%s:%s" % (row["repository"], row["path"])


def search(connection, query, limit, filters=None):
    expression = fts_query(query)
    if not expression:
        return []
    filters = filters or {}
    clauses = []
    parameters = [expression]
    for field in ("repository", "module", "kind", "language"):
        if filters.get(field):
            clauses.append(field + " = ?")
            parameters.append(filters[field])
    parameters.append(max(limit * 20, limit))
    sql = (
        "SELECT source_id, repository, path, title, content_hash, bm25(chunks) AS rank "
        "FROM chunks WHERE chunks MATCH ?"
    )
    if clauses:
        sql += " AND " + " AND ".join(clauses)
    sql += " ORDER BY rank LIMIT ?"
    rows = connection.execute(sql, parameters).fetchall()
    unique = []
    seen_hashes = set()
    seen_sources = set()
    for row in rows:
        source = source_name(row)
        if row["content_hash"] in seen_hashes or source in seen_sources:
            continue
        seen_hashes.add(row["content_hash"])
        seen_sources.add(source)
        unique.append(row)
        if len(unique) == limit:
            break
    return unique


def evaluate(connection, definition):
    cases = definition.get("cases", [])
    if not cases:
        raise ValueError("Retrieval evaluation contains no cases")
    default_top_k = min(max(int(definition.get("top_k", 5)), 1), 20)
    results = []
    positive_reciprocal_ranks = []
    positive_recalls = []
    negative_results = []
    identifiers = set()
    for case in cases:
        identifier = case.get("id", "")
        if not identifier or identifier in identifiers:
            raise ValueError("Every retrieval case must have a unique non-empty id")
        identifiers.add(identifier)
        query = case.get("query", "")
        if not query:
            raise ValueError("Retrieval case %s has an empty query" % identifier)
        top_k = min(max(int(case.get("top_k", default_top_k)), 1), 20)
        rows = search(connection, query, top_k, case.get("filters"))
        retrieved = [source_name(row) for row in rows]
        expected = case.get("expected_sources", [])
        expect_no_results = bool(case.get("expect_no_results"))
        matching_ranks = []
        if expect_no_results:
            passed = not retrieved
            negative_results.append(1.0 if passed else 0.0)
            reciprocal_rank = None
            recall = None
        else:
            if not expected:
                raise ValueError("Positive retrieval case %s has no expected_sources" % identifier)
            expected_set = set(expected)
            matching_ranks = [index for index, source in enumerate(retrieved, 1) if source in expected_set]
            reciprocal_rank = 1.0 / matching_ranks[0] if matching_ranks else 0.0
            recall = 1.0 if matching_ranks else 0.0
            positive_reciprocal_ranks.append(reciprocal_rank)
            positive_recalls.append(recall)
            passed = bool(matching_ranks)
        results.append({
            "id": identifier,
            "query": query,
            "top_k": top_k,
            "expected_sources": expected,
            "expect_no_results": expect_no_results,
            "retrieved_sources": retrieved,
            "matched_source": retrieved[matching_ranks[0] - 1] if matching_ranks else None,
            "recall": recall,
            "reciprocal_rank": reciprocal_rank,
            "passed": passed,
        })
    recall_at_k = sum(positive_recalls) / len(positive_recalls) if positive_recalls else 1.0
    mrr = sum(positive_reciprocal_ranks) / len(positive_reciprocal_ranks) if positive_reciprocal_ranks else 1.0
    negative_pass_rate = sum(negative_results) / len(negative_results) if negative_results else 1.0
    thresholds = definition.get("thresholds", {})
    minimum_recall = float(thresholds.get("min_recall_at_k", 1.0))
    minimum_mrr = float(thresholds.get("min_mrr", 0.8))
    minimum_negative = float(thresholds.get("min_negative_pass_rate", 1.0))
    return {
        "definition_version": definition.get("version", 1),
        "cases": len(cases),
        "positive_cases": len(positive_recalls),
        "negative_cases": len(negative_results),
        "top_k": default_top_k,
        "recall_at_k": round(recall_at_k, 6),
        "mrr": round(mrr, 6),
        "negative_pass_rate": round(negative_pass_rate, 6),
        "thresholds": {
            "min_recall_at_k": minimum_recall,
            "min_mrr": minimum_mrr,
            "min_negative_pass_rate": minimum_negative,
        },
        "passed": recall_at_k >= minimum_recall and mrr >= minimum_mrr and negative_pass_rate >= minimum_negative,
        "results": results,
    }


def load_definition(path):
    return json.loads(path.read_text(encoding="utf-8"))
