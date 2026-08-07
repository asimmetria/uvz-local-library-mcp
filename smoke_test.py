#!/usr/bin/env python3
"""Exercise the real stdio MCP transport against the installed knowledge pack."""

import argparse
import json
import subprocess
import sys
from pathlib import Path


REQUIRED_TOOLS = {
    "search_knowledge",
    "search_config",
    "suggest_dependency",
    "resolve_config",
    "get_source",
    "list_libraries",
    "list_repositories",
    "index_status",
}


def request(identifier, method, params=None):
    payload = {"jsonrpc": "2.0", "id": identifier, "method": method}
    if params is not None:
        payload["params"] = params
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", type=Path, default=Path(__file__).with_name("server.py"))
    parser.add_argument("--python", default=sys.executable)
    options = parser.parse_args()
    messages = [
        request(1, "initialize", {"protocolVersion": "2024-11-05"}),
        request(2, "tools/list"),
        request(3, "tools/call", {"name": "list_repositories", "arguments": {}}),
    ]
    completed = subprocess.run(
        [options.python, str(options.server)],
        input="\n".join(messages) + "\n",
        text=True,
        capture_output=True,
        timeout=30,
    )
    if completed.returncode:
        raise SystemExit("MCP server exited with code %d: %s" % (completed.returncode, completed.stderr.strip()))
    try:
        responses = {item["id"]: item for item in map(json.loads, completed.stdout.splitlines())}
        tools = {tool["name"] for tool in responses[2]["result"]["tools"]}
        repository_text = responses[3]["result"]["content"][0]["text"]
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exception:
        raise SystemExit("Invalid MCP smoke-test response: %s" % exception)
    missing = sorted(REQUIRED_TOOLS - tools)
    if missing:
        raise SystemExit("MCP tool discovery is incomplete: " + ", ".join(missing))
    if "incompatible" in repository_text.lower() or "not installed" in repository_text.lower():
        raise SystemExit("MCP cannot use the installed knowledge pack: " + repository_text)
    if "No repositories are indexed" in repository_text:
        raise SystemExit("MCP knowledge pack contains no indexed repositories")
    print("Validated MCP smoke test: %d tools and an accessible knowledge index" % len(tools))


if __name__ == "__main__":
    main()
