#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SYS_PYTHON="$(command -v python3 || command -v python)"
GIGACODE_HOME="${GIGACODE_HOME:-$HOME/.gigacode}"
WORKSPACE=""
SYNC=0
CONFIGURATION_ROOTS=()
KNOWLEDGE_PACK=""

"$SYS_PYTHON" -c 'import sys; raise SystemExit("local-library-mcp requires Python 3.10 or newer; found %s" % sys.version.split()[0]) if sys.version_info < (3, 10) else None'

while [ "$#" -gt 0 ]; do
  case "$1" in
    --workspace) WORKSPACE="$2"; shift 2 ;;
    --sync) SYNC=1; shift ;;
    --configuration-root) CONFIGURATION_ROOTS+=("$2"); shift 2 ;;
    --knowledge-pack) KNOWLEDGE_PACK="$2"; shift 2 ;;
    *) echo "Usage: $0 [--workspace /path/to/projects] [--sync] [--configuration-root /path/to/config] [--knowledge-pack /path/to/pack.zip]"; exit 2 ;;
  esac
done

mkdir -p "$GIGACODE_HOME" "$GIGACODE_HOME/skills"
VENV="$GIGACODE_HOME/.local-library-mcp-venv"
if [ ! -x "$VENV/bin/python" ]; then
  "$SYS_PYTHON" -m venv "$VENV"
fi
PYTHON="$VENV/bin/python"
"$PYTHON" -m pip install --quiet -r "$SCRIPT_DIR/requirements.txt"
"$PYTHON" -c 'import mcp; print("Validated MCP runtime")'

if [ -n "$WORKSPACE" ]; then
  "$PYTHON" -m pip install --quiet -r "$SCRIPT_DIR/requirements-indexer.txt"
  "$PYTHON" -c 'import yaml; print("Validated YAML parser for index build")'
  BUILD_ARGS=("$PYTHON" "$SCRIPT_DIR/build_workspace.py" "$WORKSPACE")
  [ "$SYNC" = "1" ] && BUILD_ARGS+=(--sync)
  for root in "${CONFIGURATION_ROOTS[@]}"; do BUILD_ARGS+=(--configuration-root "$root"); done
  "${BUILD_ARGS[@]}"
fi

if [ -n "$KNOWLEDGE_PACK" ]; then
  "$PYTHON" "$SCRIPT_DIR/install_pack.py" "$KNOWLEDGE_PACK" --destination "$SCRIPT_DIR"
fi

ln -sfn "$SCRIPT_DIR" "$GIGACODE_HOME/local-library-mcp"
ln -sfn "$SCRIPT_DIR/skill" "$GIGACODE_HOME/skills/library-knowledge-workflow"

"$PYTHON" - "$GIGACODE_HOME/settings.json" "$PYTHON" "$GIGACODE_HOME/local-library-mcp/server.py" <<'PY'
import json, sys
from pathlib import Path
path, python, server = map(Path, sys.argv[1:])
config = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
config.setdefault("mcpServers", {})["local-library-mcp"] = {
    "command": str(python), "args": [str(server)], "timeout": 120000, "trust": False
}
path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
PY

echo "Installed local-library-mcp into $GIGACODE_HOME"
echo "Restart GigaCode to load the MCP server and skill."
