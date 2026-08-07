#!/usr/bin/env python3
"""Shared SQLite schema contract for indexer, runtime and pack tooling."""

import sqlite3


SCHEMA_VERSION = 1

CHUNK_COLUMNS = (
    "source_id",
    "pack_id",
    "repository",
    "module",
    "path",
    "kind",
    "language",
    "configuration_set",
    "commit_sha",
    "line_start",
    "line_end",
    "title",
    "content",
)

CONFIGURATION_VALUE_COLUMNS = (
    "source_id",
    "pack_id",
    "repository",
    "module",
    "path",
    "configuration_set",
    "profile",
    "layer",
    "key_path",
    "value_json",
)


class KnowledgeSchemaError(RuntimeError):
    """Raised when a knowledge database cannot be used by this runtime."""


def table_columns(connection, table):
    return tuple(row[1] for row in connection.execute("PRAGMA table_info(%s)" % table))


def create_schema(connection):
    connection.execute(
        "CREATE VIRTUAL TABLE chunks USING fts5("
        "source_id UNINDEXED, pack_id UNINDEXED, repository UNINDEXED, "
        "module UNINDEXED, path UNINDEXED, kind UNINDEXED, language UNINDEXED, "
        "configuration_set UNINDEXED, commit_sha UNINDEXED, "
        "line_start UNINDEXED, line_end UNINDEXED, title, content, "
        "tokenize='unicode61')"
    )
    connection.execute(
        "CREATE TABLE configuration_values ("
        "source_id TEXT NOT NULL, pack_id TEXT NOT NULL, repository TEXT NOT NULL, "
        "module TEXT NOT NULL, path TEXT NOT NULL, configuration_set TEXT NOT NULL, "
        "profile TEXT NOT NULL, layer TEXT NOT NULL, key_path TEXT NOT NULL, "
        "value_json TEXT NOT NULL)"
    )
    connection.execute(
        "CREATE INDEX configuration_values_lookup ON configuration_values("
        "repository, module, configuration_set, profile, key_path)"
    )
    connection.execute(
        "CREATE TABLE knowledge_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    connection.execute("PRAGMA user_version = %d" % SCHEMA_VERSION)


def validate_schema(connection):
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    if version != SCHEMA_VERSION:
        raise KnowledgeSchemaError(
            "Knowledge pack schema %s is incompatible with runtime schema %s. "
            "Rebuild the index or install a current knowledge pack."
            % (version, SCHEMA_VERSION)
        )
    chunks = table_columns(connection, "chunks")
    if chunks != CHUNK_COLUMNS:
        raise KnowledgeSchemaError(
            "Knowledge pack has an incompatible chunks table. "
            "Rebuild the index or install a current knowledge pack."
        )
    configuration_values = table_columns(connection, "configuration_values")
    if configuration_values != CONFIGURATION_VALUE_COLUMNS:
        raise KnowledgeSchemaError(
            "Knowledge pack has an incompatible configuration_values table. "
            "Rebuild the index or install a current knowledge pack."
        )
    if table_columns(connection, "knowledge_metadata") != ("key", "value"):
        raise KnowledgeSchemaError(
            "Knowledge pack metadata is missing. Rebuild the index or install a current knowledge pack."
        )
    return version


def validate_database(path):
    connection = sqlite3.connect(str(path))
    try:
        return validate_schema(connection)
    finally:
        connection.close()
