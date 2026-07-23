#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WORKSPACE_HOME=""
DISCOVERY_DIR="$SCRIPT_DIR"
while [ "$DISCOVERY_DIR" != "/" ]; do
  if [ -d "$DISCOVERY_DIR/.gigacode" ]; then
    WORKSPACE_HOME="$DISCOVERY_DIR"
    break
  fi
  DISCOVERY_DIR="$(dirname "$DISCOVERY_DIR")"
done
if [ -n "${GIGACODE_HOME:-}" ]; then
  GIGACODE_HOME="$GIGACODE_HOME"
elif [ -d "$HOME/.gigacode" ] && [ -w "$HOME/.gigacode" ]; then
  GIGACODE_HOME="$HOME/.gigacode"
elif [ -n "$WORKSPACE_HOME" ]; then
  # Corporate shells can expose a synthetic, non-writable $HOME while the
  # actual GigaCode profile lives beside the developer's workspace.
  GIGACODE_HOME="$WORKSPACE_HOME/.gigacode"
else
  GIGACODE_HOME="$HOME/.gigacode"
fi
# Keep Python packages outside .gigacode: some corporate policies permit its
# settings file but deny importing packages created there.
MCP_RUNTIME_HOME="${MCP_RUNTIME_HOME:-$SCRIPT_DIR/.mcp-runtime}"
PYTHON_BIN="${PYTHON_BIN:-}"
if [ -z "$PYTHON_BIN" ] && [ -x "$GIGACODE_HOME/.venv/bin/python" ]; then
  PYTHON_BIN="$GIGACODE_HOME/.venv/bin/python"
fi
SYS_PYTHON="${PYTHON_BIN:-$(command -v python3 || command -v python)}"
WORKSPACE=""
SYNC=0
CONFIGURATION_ROOTS=()
KNOWLEDGE_PACK=""
EXCLUDE_FILE="${INDEX_EXCLUDE_FILE:-$SCRIPT_DIR/index-exclude.txt}"

"$SYS_PYTHON" -c 'import sys; sys.exit("local-library-mcp requires Python 3.9 or newer; found %s" % sys.version.split()[0]) if sys.version_info < (3, 9) else None'

while [ "$#" -gt 0 ]; do
  case "$1" in
    --workspace) WORKSPACE="$2"; shift 2 ;;
    --sync) SYNC=1; shift ;;
    --configuration-root) CONFIGURATION_ROOTS+=("$2"); shift 2 ;;
    --exclude-file) EXCLUDE_FILE="$2"; shift 2 ;;
    --knowledge-pack) KNOWLEDGE_PACK="$2"; shift 2 ;;
    *) echo "Usage: $0 [--workspace /path/to/projects] [--sync] [--configuration-root /path/to/config] [--exclude-file /path/to/index-exclude.txt] [--knowledge-pack /path/to/pack.zip]"; exit 2 ;;
  esac
done

# The private distribution repository may ship a versioned pack in dist/.
# A normal developer should not need to locate or name it manually. Explicit
# --knowledge-pack always wins; a maintainer --workspace build never consumes a
# possibly stale bundled pack.
if [ -z "$KNOWLEDGE_PACK" ] && [ -z "$WORKSPACE" ]; then
  shopt -s nullglob
  BUNDLED_PACKS=("$SCRIPT_DIR"/dist/knowledge-pack-*.zip)
  shopt -u nullglob
  if [ "${#BUNDLED_PACKS[@]}" -gt 0 ]; then
    KNOWLEDGE_PACK="${BUNDLED_PACKS[${#BUNDLED_PACKS[@]} - 1]}"
    echo "Using bundled knowledge pack: $(basename "$KNOWLEDGE_PACK")"
  fi
fi

mkdir -p "$GIGACODE_HOME" "$GIGACODE_HOME/skills"
mkdir -p "$MCP_RUNTIME_HOME"
VENV="$MCP_RUNTIME_HOME/.local-library-mcp-venv"
if [ ! -x "$VENV/bin/python" ] && "$SYS_PYTHON" -c 'import ensurepip' >/dev/null 2>&1; then
  "$SYS_PYTHON" -m venv "$VENV"
fi
PYTHONPATH_PREFIX=""
if [ -x "$VENV/bin/python" ] && "$VENV/bin/python" -m pip --version >/dev/null 2>&1; then
  PYTHON="$VENV/bin/python"
else
  # Debian corporate images can have Python and pip but omit python3-venv.
  # Install dependencies in a project-local directory instead of requiring apt.
  PYTHON="$SYS_PYTHON"
  PYTHONPATH_PREFIX="$MCP_RUNTIME_HOME/.local-library-mcp-site-packages"
  mkdir -p "$PYTHONPATH_PREFIX"
  echo "Python venv is unavailable; using project-local pip packages"
fi

run_python() {
  if [ -n "$PYTHONPATH_PREFIX" ]; then
    PYTHONPATH="$PYTHONPATH_PREFIX${PYTHONPATH:+:$PYTHONPATH}" "$PYTHON" "$@"
  else
    "$PYTHON" "$@"
  fi
}

install_requirements() {
  if ! grep -q '^[[:space:]]*[^#[:space:]]' "$1"; then
    return
  fi
  if [ -n "$PYTHONPATH_PREFIX" ]; then
    "$PYTHON" -m pip install --quiet --target "$PYTHONPATH_PREFIX" -r "$1"
  else
    "$PYTHON" -m pip install --quiet -r "$1"
  fi
}

install_requirements "$SCRIPT_DIR/requirements.txt"
run_python - "$SCRIPT_DIR/server.py" <<'PY'
import ast, pathlib, sys
ast.parse(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
print("Validated dependency-free MCP runtime")
PY

if [ -n "$WORKSPACE" ]; then
  install_requirements "$SCRIPT_DIR/requirements-indexer.txt"
  run_python -c 'import yaml; print("Validated YAML parser for index build")'
  BUILD_ARGS=("$SCRIPT_DIR/build_workspace.py" "$WORKSPACE")
  [ "$SYNC" = "1" ] && BUILD_ARGS+=(--sync)
  for root in "${CONFIGURATION_ROOTS[@]}"; do BUILD_ARGS+=(--configuration-root "$root"); done
  [ -f "$EXCLUDE_FILE" ] && BUILD_ARGS+=(--exclude-file "$EXCLUDE_FILE")
  run_python "${BUILD_ARGS[@]}"
fi

if [ -n "$KNOWLEDGE_PACK" ]; then
  run_python "$SCRIPT_DIR/install_pack.py" "$KNOWLEDGE_PACK" --destination "$SCRIPT_DIR"
fi

WORKFLOW_SKILL_TARGET="$SCRIPT_DIR/skills/library-knowledge-workflow"
WORKFLOW_SKILL_LINK="$GIGACODE_HOME/skills/library-knowledge-workflow"
if [ -e "$WORKFLOW_SKILL_LINK" ] && [ ! -L "$WORKFLOW_SKILL_LINK" ]; then
  echo "Refusing to replace non-symlink skill path: $WORKFLOW_SKILL_LINK" >&2
  exit 1
fi
if [ -L "$WORKFLOW_SKILL_LINK" ]; then
  rm "$WORKFLOW_SKILL_LINK"
fi
ln -s "$WORKFLOW_SKILL_TARGET" "$WORKFLOW_SKILL_LINK"

SERVER_COMMAND="$PYTHON"
if [ -n "$PYTHONPATH_PREFIX" ]; then
  SERVER_COMMAND="$MCP_RUNTIME_HOME/local-library-mcp-python"
  {
    printf '%s\n' '#!/usr/bin/env bash'
    printf 'export PYTHONPATH=%q${PYTHONPATH:+:$PYTHONPATH}\n' "$PYTHONPATH_PREFIX"
    printf 'exec %q "$@"\n' "$PYTHON"
  } > "$SERVER_COMMAND"
  chmod +x "$SERVER_COMMAND"
fi

run_python - "$GIGACODE_HOME/settings.json" "$SERVER_COMMAND" "$SCRIPT_DIR/server.py" <<'PY'
import json, sys
from pathlib import Path
path, python, server = map(Path, sys.argv[1:])
config = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
config.setdefault("mcpServers", {})["local-library-mcp"] = {
    "command": str(python), "args": [str(server)], "timeout": 120000, "trust": False
}
path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
PY

echo "Installed local-library-mcp runtime into $MCP_RUNTIME_HOME"
echo "Restart GigaCode to load the MCP server and skill."
