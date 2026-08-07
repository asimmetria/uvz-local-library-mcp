#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT="${1:-.}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPOSITORY_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd -P)"
PYTHON="${PYTHON_BIN:-}"
if [ -z "$PYTHON" ] && [ -x "$REPOSITORY_ROOT/.mcp-runtime/.local-library-mcp-venv/bin/python" ]; then
  PYTHON="$REPOSITORY_ROOT/.mcp-runtime/.local-library-mcp-venv/bin/python"
fi
if [ -z "$PYTHON" ] && [ -n "${GIGACODE_HOME:-}" ] && [ -x "$GIGACODE_HOME/.venv/bin/python" ]; then
  PYTHON="$GIGACODE_HOME/.venv/bin/python"
fi
PYTHON="${PYTHON:-python3}"
SITE_PACKAGES="$REPOSITORY_ROOT/.mcp-runtime/.local-library-mcp-site-packages"

if [ -d "$SITE_PACKAGES" ]; then
  PYTHONPATH="$SITE_PACKAGES${PYTHONPATH:+:$PYTHONPATH}" exec "$PYTHON" "$REPOSITORY_ROOT/validate_project_contexts.py" "$PROJECT"
fi
exec "$PYTHON" "$REPOSITORY_ROOT/validate_project_contexts.py" "$PROJECT"
