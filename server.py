"""Dependency-free local stdio MCP server over the generated SQLite FTS5 pack."""

import json
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

from knowledge_schema import KnowledgeSchemaError, validate_schema
from retrieval_evaluator import (
    KIND_PRIORITY_EXPRESSION,
    RANK_EXPRESSION,
    fts_query,
    matching_dependency_aliases,
)


BASE = Path(__file__).parent
DB_PATH = BASE / "knowledge.db"
CATALOG_PATH = BASE / "skills" / "library-knowledge-workflow" / "generated-catalog.md"
AUDIT_PATH = BASE / "audit-summary.json"
CAMPAIGN_TOOL = BASE / "skills" / "project-context-authoring" / "scripts" / "project-context-campaign-state.py"
PROJECT_CONTEXT_VALIDATOR = BASE / "validate_project_contexts.py"


def db():
    if not DB_PATH.exists():
        return None
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        validate_schema(con)
    except Exception:
        con.close()
        raise
    return con


def query(value):
    return fts_query(value)


def text(value):
    return [{"type": "text", "text": value}]


def search(arguments):
    con = db()
    if not con:
        return "Knowledge pack is not installed. Run the index build or install a published pack."
    fts = query(arguments.get("query", ""))
    if not fts:
        return "Query is empty."
    limit = min(max(int(arguments.get("limit", 5)), 1), 10)
    filters, params = [], [fts]
    for field in ("pack_id", "repository", "module", "kind", "language", "configuration_set"):
        if arguments.get(field):
            filters.append(field + " = ?")
            params.append(arguments[field])
    params.append(limit * 20)
    sql = "SELECT source_id, repository, path, kind, language, configuration_set, commit_sha, line_start, line_end, title, content_hash, snippet(chunks, 12, '**', '**', '…', 28) AS snippet, " + KIND_PRIORITY_EXPRESSION + " AS kind_priority, " + RANK_EXPRESSION + " AS rank FROM chunks WHERE chunks MATCH ?"
    if filters:
        sql += " AND " + " AND ".join(filters)
    sql += " ORDER BY kind_priority, rank LIMIT ?"
    rows = con.execute(sql, params).fetchall()
    con.close()
    if not rows:
        return "Nothing found. Try simpler keywords or use list_libraries."
    result = []
    seen_hashes = set()
    seen_sources = set()
    for row in rows:
        source_key = (row["repository"], row["path"])
        if row["content_hash"] in seen_hashes or source_key in seen_sources:
            continue
        seen_hashes.add(row["content_hash"])
        seen_sources.add(source_key)
        index = len(result) + 1
        config = " · configuration set: %s" % row["configuration_set"] if row["configuration_set"] else ""
        result.append("### [%d] %s\nsource: `%s`\npath: `%s:%s-%s`\nkind: %s · language: %s%s · commit: %s\n\n%s" % (index, row["title"], row["source_id"], row["path"], row["line_start"], row["line_end"], row["kind"], row["language"], config, row["commit_sha"][:12], row["snippet"]))
        if len(result) == limit:
            break
    return "\n\n---\n\n".join(result)


def source(arguments):
    con = db()
    if not con:
        return "Knowledge pack is not installed."
    source_id = arguments.get("source_id", "")
    if "#" in source_id:
        rows = con.execute("SELECT source_id, path, language, commit_sha, line_start, line_end, title, content FROM chunks WHERE source_id = ?", (source_id,)).fetchall()
    else:
        rows = con.execute("SELECT source_id, path, language, commit_sha, line_start, line_end, title, content FROM chunks WHERE source_id GLOB ? ORDER BY source_id", (source_id + "#*",)).fetchall()
    con.close()
    if not rows:
        return "Source not found: %s" % source_id
    return "\n\n---\n\n".join("### %s\nsource: `%s`\npath: `%s:%s-%s` · %s · %s\n\n%s" % (row["title"], row["source_id"], row["path"], row["line_start"], row["line_end"], row["language"], row["commit_sha"][:12], row["content"]) for row in rows)


def repositories():
    con = db()
    if not con:
        return "Knowledge pack is not installed."
    rows = con.execute(
        "SELECT repository, count(*) AS chunks, "
        "sum(kind = 'source') AS source_chunks, sum(kind = 'example') AS example_chunks, "
        "sum(kind = 'docs') AS docs_chunks, sum(kind = 'configuration') AS config_chunks, "
        "sum(kind = 'context') AS context_chunks, sum(kind = 'usage') AS usage_chunks, "
        "count(DISTINCT module) AS modules, max(commit_sha) AS commit_sha "
        "FROM chunks GROUP BY repository ORDER BY repository"
    ).fetchall()
    con.close()
    if not rows:
        return "No repositories are indexed."
    lines = ["# Indexed repositories", "", "Use `search_knowledge` with `repository` and optional `module` to search one application.", ""]
    for row in rows:
        lines.append("- `%s`: %d chunks (%d context, %d usage, %d source, %d examples, %d docs, %d config), %d modules, commit %s" % (
            row["repository"], row["chunks"], row["context_chunks"], row["usage_chunks"], row["source_chunks"], row["example_chunks"], row["docs_chunks"], row["config_chunks"], row["modules"], row["commit_sha"][:12]
        ))
    return "\n".join(lines)


def alias_usage_rows(con, alias_row, repository="", limit=10):
    filters = ["catalog_repository = ?", "catalog_path = ?", "alias = ?"]
    parameters = [
        alias_row["catalog_repository"], alias_row["catalog_path"], alias_row["alias"]
    ]
    if repository:
        filters.append("consumer_repository = ?")
        parameters.append(repository)
    parameters.append(limit)
    return con.execute(
        "SELECT consumer_repository, consumer_module, path, configuration, "
        "commit_sha, line FROM dependency_usages WHERE "
        + " AND ".join(filters)
        + " ORDER BY consumer_repository, consumer_module, path, line LIMIT ?",
        parameters,
    ).fetchall()


def dependency_suggestion(arguments):
    """Resolve a structured Gradle alias and show verified consumers."""
    con = db()
    if not con:
        return "Knowledge pack is not installed."
    requested = arguments.get("query", "")
    scope = arguments.get("scope", "implementation")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", scope):
        con.close()
        return "Invalid Gradle scope."
    matches = matching_dependency_aliases(con, requested)
    if not matches:
        con.close()
        return "No matching alias was found in uvz-platform. Do not add a direct version; use search_knowledge to inspect the library and ask the platform owner to add or confirm an alias."
    output = ["# Dependency suggestion", ""]
    for row in matches[:10]:
        version = ""
        if row["version_ref"]:
            version = " · version ref: `%s`" % row["version_ref"]
        elif row["version_value"]:
            version = " · catalog version: `%s`" % row["version_value"]
        owner = "`%s%s`" % (row["owner_repository"], row["owner_module"]) if row["owner_repository"] else "not resolved"
        output.extend([
            "## libs.%s" % row["accessor"],
            "- declaration: `%s(libs.%s)`" % (scope, row["accessor"]),
            "- coordinates: `%s:%s`%s" % (row["group_id"], row["artifact_id"], version),
            "- owner: %s" % owner,
            "- catalog: `%s:%s` · commit `%s`" % (
                row["catalog_repository"], row["catalog_path"], row["catalog_commit_sha"][:12]
            ),
        ])
        examples = alias_usage_rows(con, row, limit=3)
        if examples:
            output.append("- verified consumers: " + ", ".join(
                "`%s%s:%s:%d` (%s, commit %s)" % (
                    example["consumer_repository"], example["consumer_module"],
                    example["path"], example["line"], example["configuration"],
                    example["commit_sha"][:12],
                )
                for example in examples
            ))
        output.extend([
            "- prerequisite: the consumer project must import the `uvz-platform` version catalog as `libs`.",
            "",
        ])
    con.close()
    return "\n".join(output).rstrip()


def library_usages(arguments):
    con = db()
    if not con:
        return "Knowledge pack is not installed."
    requested = arguments.get("query", "")
    repository = arguments.get("repository", "")
    limit = min(max(int(arguments.get("limit", 20)), 1), 50)
    matches = matching_dependency_aliases(con, requested)
    if not matches:
        con.close()
        return "No matching uvz-platform alias was found. Try an artifact id, repository, or libs alias."
    output = ["# Verified library usages", ""]
    remaining = limit
    for row in matches:
        usages = alias_usage_rows(con, row, repository=repository, limit=remaining)
        output.extend([
            "## libs.%s" % row["accessor"],
            "coordinates: `%s:%s`" % (row["group_id"], row["artifact_id"]),
            "owner: `%s%s`" % (row["owner_repository"], row["owner_module"])
            if row["owner_repository"] else "owner: not resolved",
            "catalog: `%s:%s` · commit `%s`" % (
                row["catalog_repository"], row["catalog_path"], row["catalog_commit_sha"][:12]
            ),
            "",
        ])
        if not usages:
            output.extend(["No verified consumer build usage found.", ""])
            continue
        for usage in usages:
            output.append("- `%s%s` — `%s:%d` · %s · commit `%s`" % (
                usage["consumer_repository"], usage["consumer_module"],
                usage["path"], usage["line"], usage["configuration"],
                usage["commit_sha"][:12],
            ))
        output.append("")
        remaining -= len(usages)
        if remaining <= 0:
            break
    con.close()
    return "\n".join(output).rstrip()


def resolve_config(arguments):
    con = db()
    if not con:
        return "Knowledge pack is not installed."
    application = arguments.get("application", "")
    config_set = arguments.get("configuration_set", "")
    profile = arguments.get("profile", "")
    module = arguments.get("module", "")
    if not application or not config_set:
        con.close()
        return "Specify both application (repository name) and configuration_set. Use search_config first if you do not know the set name."
    try:
        con.execute("SELECT 1 FROM configuration_values LIMIT 1").fetchone()
    except sqlite3.OperationalError:
        con.close()
        return "This knowledge pack predates effective configuration support. Rebuild it with the current indexer."
    # A conservative, explicit default. A project can override the resulting values after
    # inspecting their Spring config-import order; every answer carries provenance.
    precedence = [("central", ""), ("module", ""), ("central", profile), ("module", profile)]
    selected = {}
    origins = {}
    for layer, value_profile in precedence:
        filters = ["repository = ?", "layer = ?", "profile = ?"]
        params = [application, layer, value_profile]
        if layer == "central":
            filters[0] = "configuration_set = ?"
            params[0] = config_set
        else:
            filters.append("configuration_set = ''")
            if module:
                filters.append("module = ?")
                params.append(module)
        rows = con.execute("SELECT source_id, path, key_path, value_json FROM configuration_values WHERE " + " AND ".join(filters) + " ORDER BY path, source_id", params).fetchall()
        for row in rows:
            selected[row["key_path"]] = json.loads(row["value_json"])
            origins[row["key_path"]] = {"layer": layer, "profile": value_profile or "base", "source": row["source_id"], "path": row["path"]}
    con.close()
    if not selected:
        return "No effective values found. Check application, configuration_set, module, and profile; then use search_config for raw files."
    payload = {"application": application, "module": module or "all modules", "configuration_set": config_set, "profile": profile or "base", "precedence": ["central:base", "module:base", "central:profile", "module:profile"], "values": selected, "provenance": origins}
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


def campaign_state(arguments, action):
    """Run one constrained authoring campaign state transition."""
    if not CAMPAIGN_TOOL.is_file():
        return "Project-context campaign controller is not installed."
    state_file = arguments.get("state_file", "")
    if not state_file:
        return "state_file is required."
    command = [sys.executable, str(CAMPAIGN_TOOL), action, "--state", state_file]
    if action in {"start", "finish"}:
        repository = arguments.get("repository", "")
        if not repository:
            return "repository is required."
        command.extend(["--repository", repository])
    if action == "finish":
        status = arguments.get("status", "")
        if status not in {"successful", "failed"}:
            return "status must be successful or failed."
        command.extend(["--status", status, "--message", arguments.get("message", "")])
    process = subprocess.run(command, capture_output=True, text=True)
    output = process.stdout.strip() or process.stderr.strip()
    if process.returncode == 10 and action == "next":
        return "NO_ELIGIBLE_REPOSITORIES"
    if process.returncode:
        return "Campaign state transition refused (exit %d): %s" % (process.returncode, output)
    return output


def validate_project_context(arguments):
    """Run the deterministic project-context validator without modifying files."""
    repository = arguments.get("repository", "")
    if not repository:
        return "VALIDATION_FAILED\nrepository is required."
    root = Path(repository).expanduser().resolve()
    if not root.is_dir():
        return "VALIDATION_FAILED\nRepository does not exist: %s" % root
    process = subprocess.run(
        [sys.executable, str(PROJECT_CONTEXT_VALIDATOR), str(root)],
        capture_output=True,
        text=True,
    )
    output = "\n".join(
        value.strip() for value in (process.stdout, process.stderr) if value.strip()
    )
    prefix = "VALIDATION_OK" if process.returncode == 0 else "VALIDATION_FAILED"
    return prefix + ("\n" + output if output else "")


TOOLS = [
    {"name": "search_knowledge", "description": "Search local indexed project context, verified usage, libraries, applications, documentation, examples, source code and configuration. Curated context and usage rank first.", "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}, "pack_id": {"type": "string"}, "repository": {"type": "string", "description": "Optional Git repository name; use list_repositories first"}, "module": {"type": "string", "description": "Optional Gradle module, for example :api"}, "kind": {"type": "string", "enum": ["context", "usage", "docs", "example", "source", "configuration"]}, "language": {"type": "string"}, "configuration_set": {"type": "string"}, "limit": {"type": "integer", "default": 5}}, "required": ["query"]}},
    {"name": "search_config", "description": "Search raw local configuration values. Specify configuration_set when central configuration has multiple variants.", "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}, "configuration_set": {"type": "string"}, "limit": {"type": "integer", "default": 5}}, "required": ["query"]}},
    {"name": "suggest_dependency", "description": "ALWAYS call before adding an internal Gradle dependency. Resolves a uvz-platform version-catalog alias and returns the correct libs alias declaration without a direct version.", "inputSchema": {"type": "object", "properties": {"query": {"type": "string", "description": "Library name, artifact, or alias fragment, for example sbertone adapter"}, "scope": {"type": "string", "default": "implementation", "description": "Gradle configuration, for example implementation, api, testImplementation"}}, "required": ["query"]}},
    {"name": "find_library_usages", "description": "Find verified Gradle consumers of an internal library through structured uvz-platform aliases. Returns repository, module, build path, line, configuration and commit.", "inputSchema": {"type": "object", "properties": {"query": {"type": "string", "description": "Library name, artifact id, repository, or libs alias"}, "repository": {"type": "string", "description": "Optional consumer repository filter"}, "limit": {"type": "integer", "default": 20}}, "required": ["query"]}},
    {"name": "resolve_config", "description": "Resolve YAML leaf values for one application and central configuration set. Result includes exact source provenance. Default order is central base → module base → central profile → module profile; verify it against the application's Spring config-import order.", "inputSchema": {"type": "object", "properties": {"application": {"type": "string", "description": "Application repository name"}, "module": {"type": "string", "description": "Optional Gradle module, for example :api"}, "configuration_set": {"type": "string", "description": "Central configuration variant folder"}, "profile": {"type": "string", "description": "Optional Spring profile"}}, "required": ["application", "configuration_set"]}},
    {"name": "get_source", "description": "Read the complete indexed chunk(s) after search_knowledge returned a source id.", "inputSchema": {"type": "object", "properties": {"source_id": {"type": "string"}}, "required": ["source_id"]}},
    {"name": "list_libraries", "description": "List local generated catalog entries and their capabilities.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "list_repositories", "description": "List all indexed Git repositories, including applications, with chunk counts and discovered Gradle modules.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "index_status", "description": "Show the last local ingestion audit summary.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "project_context_campaign_next", "description": "Return the next eligible repository in the active project-context campaign. A repository is never returned after success or after two attempts.", "inputSchema": {"type": "object", "properties": {"state_file": {"type": "string", "description": "Absolute campaign state path supplied by the runner"}}, "required": ["state_file"]}},
    {"name": "project_context_campaign_start", "description": "Atomically start one repository attempt, increment its attempt counter and capture a safety baseline. Refuses a third attempt.", "inputSchema": {"type": "object", "properties": {"state_file": {"type": "string"}, "repository": {"type": "string"}}, "required": ["state_file", "repository"]}},
    {"name": "project_context_campaign_finish", "description": "Immediately record one repository result. Forces terminal failure if files outside project-context.yaml or docs/usage changed since start.", "inputSchema": {"type": "object", "properties": {"state_file": {"type": "string"}, "repository": {"type": "string"}, "status": {"type": "string", "enum": ["successful", "failed"]}, "message": {"type": "string"}}, "required": ["state_file", "repository", "status"]}},
    {"name": "project_context_campaign_report", "description": "Return current project-context campaign totals.", "inputSchema": {"type": "object", "properties": {"state_file": {"type": "string"}}, "required": ["state_file"]}},
    {"name": "validate_project_context", "description": "Run the deterministic schema and path validator for all project-context.yaml files in one Git repository. Read-only. Fix every reported error and call again before marking a campaign attempt successful.", "inputSchema": {"type": "object", "properties": {"repository": {"type": "string", "description": "Absolute Git repository path from the campaign queue"}}, "required": ["repository"]}},
]


def dispatch_tool(name, arguments):
    if name == "search_knowledge":
        return text(search(arguments))
    if name == "search_config":
        return text(search({**arguments, "kind": "configuration"}))
    if name == "suggest_dependency":
        return text(dependency_suggestion(arguments))
    if name == "find_library_usages":
        return text(library_usages(arguments))
    if name == "resolve_config":
        return text(resolve_config(arguments))
    if name == "get_source":
        return text(source(arguments))
    if name == "list_libraries":
        return text(CATALOG_PATH.read_text(encoding="utf-8") if CATALOG_PATH.exists() else "Catalog has not been generated yet.")
    if name == "list_repositories":
        return text(repositories())
    if name == "index_status":
        return text(AUDIT_PATH.read_text(encoding="utf-8") if AUDIT_PATH.exists() else "No local index run found.")
    if name == "project_context_campaign_next":
        return text(campaign_state(arguments, "next"))
    if name == "project_context_campaign_start":
        return text(campaign_state(arguments, "start"))
    if name == "project_context_campaign_finish":
        return text(campaign_state(arguments, "finish"))
    if name == "project_context_campaign_report":
        return text(campaign_state(arguments, "report"))
    if name == "validate_project_context":
        return text(validate_project_context(arguments))
    return text("Unknown tool: %s" % name)


def call_tool(name, arguments):
    try:
        return dispatch_tool(name, arguments)
    except KnowledgeSchemaError as exception:
        return text(str(exception))
    except sqlite3.DatabaseError as exception:
        return text("Knowledge pack database is unreadable: %s. Install a current pack." % exception)


MISSING = object()


def result(request_id, value):
    return {"jsonrpc": "2.0", "id": request_id, "result": value}


def error(request_id, code, message):
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def handle(message):
    request_id = message.get("id", MISSING)
    method = message.get("method")
    params = message.get("params") or {}
    if method == "initialize":
        if request_id is MISSING:
            return None
        return result(request_id, {
            "protocolVersion": params.get("protocolVersion", "2024-11-05"),
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "local-library-mcp", "version": "1.4.0"},
        })
    if method == "ping":
        return None if request_id is MISSING else result(request_id, {})
    if method == "tools/list":
        return None if request_id is MISSING else result(request_id, {"tools": TOOLS})
    if method == "tools/call":
        if request_id is MISSING:
            return None
        name = params.get("name", "")
        arguments = params.get("arguments") or {}
        return result(request_id, {"content": call_tool(name, arguments)})
    if request_id is MISSING:
        return None
    return error(request_id, -32601, "Method not found: %s" % method)


def read_message():
    first = sys.stdin.buffer.readline()
    if not first:
        return None
    if first.lstrip().startswith(b"{"):
        return json.loads(first)
    headers = {}
    line = first
    while line not in (b"\n", b"\r\n", b""):
        key, _, value = line.decode("ascii").partition(":")
        headers[key.lower()] = value.strip()
        line = sys.stdin.buffer.readline()
    length = int(headers["content-length"])
    return json.loads(sys.stdin.buffer.read(length))


def write_message(payload):
    # GigaCode's stdio transport uses one JSON-RPC message per line, not the
    # HTTP-style Content-Length framing used by some other MCP clients.
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def main():
    while True:
        try:
            message = read_message()
            if message is None:
                return
            response = handle(message)
            if response is not None:
                write_message(response)
        except Exception as exception:  # Never send tracebacks to the MCP protocol stream.
            request_id = message.get("id") if "message" in locals() and isinstance(message, dict) else None
            write_message(error(request_id, -32603, "Internal error: %s" % exception))


if __name__ == "__main__":
    main()
