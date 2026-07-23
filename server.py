"""Dependency-free local stdio MCP server over the generated SQLite FTS5 pack."""

import json
import re
import sqlite3
import sys
from pathlib import Path


BASE = Path(__file__).parent
DB_PATH = BASE / "knowledge.db"
CATALOG_PATH = BASE / "skills" / "library-knowledge-workflow" / "generated-catalog.md"
AUDIT_PATH = BASE / "audit-summary.json"


def db():
    if not DB_PATH.exists():
        return None
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def query(value):
    return " ".join(re.findall(r"[\w-]+", value, flags=re.UNICODE))


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
    params.append(limit)
    sql = "SELECT source_id, path, kind, language, configuration_set, commit_sha, title, snippet(chunks, 12, '**', '**', '…', 28) AS snippet, bm25(chunks) AS rank FROM chunks WHERE chunks MATCH ?"
    if filters:
        sql += " AND " + " AND ".join(filters)
    sql += " ORDER BY rank LIMIT ?"
    rows = con.execute(sql, params).fetchall()
    con.close()
    if not rows:
        return "Nothing found. Try simpler keywords or use list_libraries."
    result = []
    for index, row in enumerate(rows, 1):
        config = " · configuration set: %s" % row["configuration_set"] if row["configuration_set"] else ""
        result.append("### [%d] %s\nsource: `%s`\nkind: %s · language: %s%s · commit: %s\n\n%s" % (index, row["title"], row["source_id"], row["kind"], row["language"], config, row["commit_sha"][:12], row["snippet"]))
    return "\n\n---\n\n".join(result)


def source(arguments):
    con = db()
    if not con:
        return "Knowledge pack is not installed."
    source_id = arguments.get("source_id", "")
    rows = con.execute("SELECT source_id, path, language, commit_sha, title, content FROM chunks WHERE source_id = ? OR source_id GLOB ? ORDER BY source_id", (source_id, source_id.split("#")[0] + "#*")).fetchall()
    con.close()
    if not rows:
        return "Source not found: %s" % source_id
    return "\n\n---\n\n".join("### %s\nsource: `%s`\npath: `%s` · %s · %s\n\n%s" % (row["title"], row["source_id"], row["path"], row["language"], row["commit_sha"][:12], row["content"]) for row in rows)


def repositories():
    con = db()
    if not con:
        return "Knowledge pack is not installed."
    rows = con.execute(
        "SELECT repository, count(*) AS chunks, "
        "sum(kind = 'source') AS source_chunks, sum(kind = 'example') AS example_chunks, "
        "sum(kind = 'docs') AS docs_chunks, sum(kind = 'configuration') AS config_chunks, "
        "count(DISTINCT module) AS modules, max(commit_sha) AS commit_sha "
        "FROM chunks GROUP BY repository ORDER BY repository"
    ).fetchall()
    con.close()
    if not rows:
        return "No repositories are indexed."
    lines = ["# Indexed repositories", "", "Use `search_knowledge` with `repository` and optional `module` to search one application.", ""]
    for row in rows:
        lines.append("- `%s`: %d chunks (%d source, %d examples, %d docs, %d config), %d modules, commit %s" % (
            row["repository"], row["chunks"], row["source_chunks"], row["example_chunks"], row["docs_chunks"], row["config_chunks"], row["modules"], row["commit_sha"][:12]
        ))
    return "\n".join(lines)


def dependency_suggestion(arguments):
    """Resolve a Gradle version-catalog alias from the indexed uvz-platform."""
    con = db()
    if not con:
        return "Knowledge pack is not installed."
    requested = arguments.get("query", "")
    terms = re.findall(r"[\w-]+", requested.lower(), flags=re.UNICODE)
    if not terms:
        con.close()
        return "Specify a library name, artifact, or catalog alias."
    scope = arguments.get("scope", "implementation")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", scope):
        con.close()
        return "Invalid Gradle scope."
    rows = con.execute(
        "SELECT source_id, path, commit_sha, content FROM chunks "
        "WHERE repository = 'uvz-platform' AND path LIKE '%libs.versions.toml' "
        "ORDER BY source_id"
    ).fetchall()
    matches = []
    for row in rows:
        for line in row["content"].splitlines():
            match = re.match(r"\s*([A-Za-z0-9_.-]+)\s*=\s*\{", line)
            if match and all(term in line.lower() for term in terms):
                matches.append((match.group(1), line.strip(), row))
    if not matches:
        con.close()
        return "No matching alias was found in uvz-platform. Do not add a direct version; use search_knowledge to inspect the library and ask the platform owner to add or confirm an alias."
    output = ["# Dependency suggestion", ""]
    seen = set()
    for alias, line, row in matches:
        if alias in seen:
            continue
        seen.add(alias)
        accessor = re.sub(r"[-_.]+", ".", alias)
        output.extend([
            "- alias: `libs.%s`" % accessor,
            "- declaration: `%s(libs.%s)`" % (scope, accessor),
            "- catalog: `%s` · commit `%s`" % (row["path"], row["commit_sha"][:12]),
            "- catalog entry: `%s`" % line,
        ])
        example_rows = con.execute(
            "SELECT repository, path FROM chunks "
            "WHERE repository != 'uvz-platform' AND path LIKE '%build.gradle.kts' "
            "AND content LIKE ? ORDER BY repository, path LIMIT 3",
            ("%%libs.%s%%" % accessor,),
        ).fetchall()
        if example_rows:
            output.append("- indexed examples: " + ", ".join("`%s:%s`" % (example["repository"], example["path"]) for example in example_rows))
        output.extend([
            "- prerequisite: the consumer project must import the `uvz-platform` version catalog as `libs`.",
            "",
        ])
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


TOOLS = [
    {"name": "search_knowledge", "description": "Search local indexed libraries, applications, documentation, examples, source code and configuration. Use this before answering a library/API question.", "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}, "pack_id": {"type": "string"}, "repository": {"type": "string", "description": "Optional Git repository name; use list_repositories first"}, "module": {"type": "string", "description": "Optional Gradle module, for example :api"}, "kind": {"type": "string", "enum": ["docs", "example", "source", "configuration"]}, "language": {"type": "string"}, "configuration_set": {"type": "string"}, "limit": {"type": "integer", "default": 5}}, "required": ["query"]}},
    {"name": "search_config", "description": "Search raw local configuration values. Specify configuration_set when central configuration has multiple variants.", "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}, "configuration_set": {"type": "string"}, "limit": {"type": "integer", "default": 5}}, "required": ["query"]}},
    {"name": "suggest_dependency", "description": "ALWAYS call before adding an internal Gradle dependency. Resolves a uvz-platform version-catalog alias and returns the correct libs alias declaration without a direct version.", "inputSchema": {"type": "object", "properties": {"query": {"type": "string", "description": "Library name, artifact, or alias fragment, for example sbertone adapter"}, "scope": {"type": "string", "default": "implementation", "description": "Gradle configuration, for example implementation, api, testImplementation"}}, "required": ["query"]}},
    {"name": "resolve_config", "description": "Resolve YAML leaf values for one application and central configuration set. Result includes exact source provenance. Default order is central base → module base → central profile → module profile; verify it against the application's Spring config-import order.", "inputSchema": {"type": "object", "properties": {"application": {"type": "string", "description": "Application repository name"}, "module": {"type": "string", "description": "Optional Gradle module, for example :api"}, "configuration_set": {"type": "string", "description": "Central configuration variant folder"}, "profile": {"type": "string", "description": "Optional Spring profile"}}, "required": ["application", "configuration_set"]}},
    {"name": "get_source", "description": "Read the complete indexed chunk(s) after search_knowledge returned a source id.", "inputSchema": {"type": "object", "properties": {"source_id": {"type": "string"}}, "required": ["source_id"]}},
    {"name": "list_libraries", "description": "List local generated catalog entries and their capabilities.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "list_repositories", "description": "List all indexed Git repositories, including applications, with chunk counts and discovered Gradle modules.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "index_status", "description": "Show the last local ingestion audit summary.", "inputSchema": {"type": "object", "properties": {}}},
]


def call_tool(name, arguments):
    if name == "search_knowledge":
        return text(search(arguments))
    if name == "search_config":
        return text(search({**arguments, "kind": "configuration"}))
    if name == "suggest_dependency":
        return text(dependency_suggestion(arguments))
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
    return text("Unknown tool: %s" % name)


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
            "serverInfo": {"name": "local-library-mcp", "version": "1.0.0"},
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
