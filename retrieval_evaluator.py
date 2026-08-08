#!/usr/bin/env python3
"""Deterministic lexical retrieval evaluation for a SQLite knowledge index."""

import json
import re


RANK_EXPRESSION = "bm25(chunks)"
KIND_PRIORITY_EXPRESSION = (
    "CASE kind WHEN 'context' THEN 0 WHEN 'usage' THEN 1 "
    "WHEN 'docs' THEN 2 WHEN 'example' THEN 3 "
    "WHEN 'source' THEN 4 ELSE 5 END"
)


def fts_query(value):
    terms = re.findall(r"[\w-]+", value, flags=re.UNICODE)
    return " ".join('"%s"' % term.replace('"', '""') for term in terms)


def normalized_dependency_text(value):
    return re.sub(r"[^\w]+", "", value.lower(), flags=re.UNICODE).replace("_", "")


def matching_dependency_aliases(connection, requested):
    """Use the same deterministic alias matching in evaluation and MCP runtime."""
    terms = [
        normalized_dependency_text(term)
        for term in re.findall(r"[\w-]+", requested, flags=re.UNICODE)
        if term.lower() not in {"libs", "library", "dependency"}
    ]
    if not terms:
        return []
    rows = connection.execute(
        "SELECT * FROM dependency_aliases ORDER BY alias, catalog_path"
    ).fetchall()
    return [
        row for row in rows
        if all(term in normalized_dependency_text(" ".join(
            str(row[field]) for field in (
                "alias", "accessor", "group_id", "artifact_id",
                "owner_repository", "owner_module",
            )
        )) for term in terms)
    ]


def dependency_consumers(connection, alias_rows, repository=""):
    consumers = []
    seen = set()
    for alias_row in alias_rows:
        filters = ["catalog_repository = ?", "catalog_path = ?", "alias = ?"]
        parameters = [
            alias_row["catalog_repository"], alias_row["catalog_path"], alias_row["alias"]
        ]
        if repository:
            filters.append("consumer_repository = ?")
            parameters.append(repository)
        rows = connection.execute(
            "SELECT alias, accessor, consumer_repository, consumer_module, path, "
            "configuration, commit_sha, line FROM dependency_usages WHERE "
            + " AND ".join(filters)
            + " ORDER BY consumer_repository, consumer_module, path, line",
            parameters,
        ).fetchall()
        for row in rows:
            value = {
                "alias": row["alias"],
                "accessor": row["accessor"],
                "repository": row["consumer_repository"],
                "module": row["consumer_module"],
                "path": row["path"],
                "configuration": row["configuration"],
                "commit": row["commit_sha"],
                "line": row["line"],
            }
            identity = tuple(value.items())
            if identity not in seen:
                seen.add(identity)
                consumers.append(value)
    return consumers


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
        "SELECT source_id, repository, path, title, content_hash, "
        + KIND_PRIORITY_EXPRESSION + " AS kind_priority, " + RANK_EXPRESSION + " AS rank "
        "FROM chunks WHERE chunks MATCH ?"
    )
    if clauses:
        sql += " AND " + " AND ".join(clauses)
    sql += " ORDER BY kind_priority, rank LIMIT ?"
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


def expected_consumer_matches(expected, actual):
    allowed = {"alias", "accessor", "repository", "module", "path", "configuration", "commit", "line"}
    unknown = set(expected) - allowed
    if unknown:
        raise ValueError("Unknown expected consumer fields: %s" % ", ".join(sorted(unknown)))
    if not expected:
        raise ValueError("Expected dependency consumer cannot be empty")
    return all(actual.get(field) == value for field, value in expected.items())


def evaluate_dependency_graph(connection, definition):
    """Evaluate structured alias and consumer retrieval independently from FTS."""
    cases = definition.get("dependency_cases", [])
    thresholds = definition.get("thresholds", {})
    minimum_cases = max(int(thresholds.get("min_dependency_cases", 0)), 0)
    minimum_pass_rate = float(thresholds.get("min_dependency_pass_rate", 1.0))
    results = []
    identifiers = set()
    passed_cases = 0
    positive_cases = 0
    negative_cases = 0
    for case in cases:
        identifier = case.get("id", "")
        if not identifier or identifier in identifiers:
            raise ValueError("Every dependency case must have a unique non-empty id")
        identifiers.add(identifier)
        query = case.get("query", "")
        if not query:
            raise ValueError("Dependency case %s has an empty query" % identifier)
        alias_rows = matching_dependency_aliases(connection, query)
        aliases = sorted({row["alias"] for row in alias_rows})
        consumers = dependency_consumers(
            connection, alias_rows, repository=case.get("repository", "")
        )
        provenance_valid = all(
            consumer["repository"]
            and consumer["module"]
            and consumer["path"]
            and consumer["configuration"]
            and re.fullmatch(r"[0-9a-f]{40,64}", consumer["commit"])
            and consumer["line"] >= 1
            for consumer in consumers
        )
        expect_no_results = bool(case.get("expect_no_results"))
        expected_aliases = case.get("expected_aliases", [])
        expected_consumers = case.get("expected_consumers", [])
        if expect_no_results:
            negative_cases += 1
            alias_match = consumer_match = None
            passed = not aliases
        else:
            positive_cases += 1
            if not expected_aliases and not expected_consumers:
                raise ValueError(
                    "Positive dependency case %s has no expected_aliases or expected_consumers"
                    % identifier
                )
            alias_match = (
                any(alias in aliases for alias in expected_aliases)
                if expected_aliases else True
            )
            consumer_match = (
                any(
                    expected_consumer_matches(expected, actual)
                    for expected in expected_consumers
                    for actual in consumers
                )
                if expected_consumers else True
            )
            passed = alias_match and consumer_match and provenance_valid
        passed_cases += int(passed)
        results.append({
            "id": identifier,
            "query": query,
            "repository": case.get("repository", ""),
            "expected_aliases": expected_aliases,
            "expected_consumers": expected_consumers,
            "expect_no_results": expect_no_results,
            "retrieved_aliases": aliases,
            "retrieved_consumers": consumers,
            "alias_match": alias_match,
            "consumer_match": consumer_match,
            "provenance_valid": provenance_valid,
            "passed": passed,
        })
    pass_rate = passed_cases / len(cases) if cases else 1.0
    return {
        "definition_version": definition.get("version", 1),
        "cases": len(cases),
        "positive_cases": positive_cases,
        "negative_cases": negative_cases,
        "pass_rate": round(pass_rate, 6),
        "thresholds": {
            "min_dependency_cases": minimum_cases,
            "min_dependency_pass_rate": minimum_pass_rate,
        },
        "passed": positive_cases >= minimum_cases and pass_rate >= minimum_pass_rate,
        "results": results,
    }


def load_definition(path):
    return json.loads(path.read_text(encoding="utf-8"))
