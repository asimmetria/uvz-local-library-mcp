"""Local stdio MCP server over the generated SQLite FTS5 knowledge pack."""

import json
import re
import sqlite3
from pathlib import Path

import mcp.server.stdio
import mcp.types as types
from mcp.server import Server


BASE = Path(__file__).parent
DB_PATH = BASE / "knowledge.db"
CATALOG_PATH = BASE / "skill" / "generated-catalog.md"
AUDIT_PATH = BASE / "audit-summary.json"
app = Server("local-library-mcp")


def db():
    if not DB_PATH.exists():
        return None
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def query(value):
    return " ".join(re.findall(r"[\w-]+", value, flags=re.UNICODE))


def text(value):
    return [types.TextContent(type="text", text=value)]


def search(arguments):
    con = db()
    if not con:
        return "Knowledge pack is not installed. Run the index build or install a published pack."
    fts = query(arguments.get("query", ""))
    if not fts:
        return "Query is empty."
    limit = min(max(int(arguments.get("limit", 5)), 1), 10)
    filters, params = [], [fts]
    for field in ("pack_id", "kind", "language", "configuration_set"):
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


@app.list_tools()
async def list_tools():
    return [
        types.Tool(name="search_knowledge", description="Search local indexed libraries, applications, documentation, examples, source code and configuration. Use this before answering a library/API question.", inputSchema={"type": "object", "properties": {"query": {"type": "string"}, "pack_id": {"type": "string"}, "kind": {"type": "string", "enum": ["docs", "example", "source", "configuration"]}, "language": {"type": "string"}, "configuration_set": {"type": "string"}, "limit": {"type": "integer", "default": 5}}, "required": ["query"]}),
        types.Tool(name="search_config", description="Search raw local configuration values. Specify configuration_set when central configuration has multiple variants.", inputSchema={"type": "object", "properties": {"query": {"type": "string"}, "configuration_set": {"type": "string"}, "limit": {"type": "integer", "default": 5}}, "required": ["query"]}),
        types.Tool(name="resolve_config", description="Resolve YAML leaf values for one application and central configuration set. Result includes exact source provenance. Default order is central base → module base → central profile → module profile; verify it against the application's Spring config-import order.", inputSchema={"type": "object", "properties": {"application": {"type": "string", "description": "Application repository name"}, "module": {"type": "string", "description": "Optional Gradle module, for example :app"}, "configuration_set": {"type": "string", "description": "Central configuration variant folder"}, "profile": {"type": "string", "description": "Optional Spring profile"}}, "required": ["application", "configuration_set"]}),
        types.Tool(name="get_source", description="Read the complete indexed chunk(s) after search_knowledge returned a source id.", inputSchema={"type": "object", "properties": {"source_id": {"type": "string"}}, "required": ["source_id"]}),
        types.Tool(name="list_libraries", description="List local generated catalog entries and their capabilities.", inputSchema={"type": "object", "properties": {}}),
        types.Tool(name="index_status", description="Show the last local ingestion audit summary.", inputSchema={"type": "object", "properties": {}}),
    ]


@app.call_tool()
async def call_tool(name, arguments):
    if name == "search_knowledge":
        return text(search(arguments))
    if name == "search_config":
        return text(search({**arguments, "kind": "configuration"}))
    if name == "resolve_config":
        return text(resolve_config(arguments))
    if name == "get_source":
        return text(source(arguments))
    if name == "list_libraries":
        return text(CATALOG_PATH.read_text(encoding="utf-8") if CATALOG_PATH.exists() else "Catalog has not been generated yet.")
    if name == "index_status":
        return text(AUDIT_PATH.read_text(encoding="utf-8") if AUDIT_PATH.exists() else "No local index run found.")
    return text("Unknown tool: %s" % name)


async def main():
    async with mcp.server.stdio.stdio_server() as streams:
        await app.run(streams[0], streams[1], app.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
