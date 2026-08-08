#!/usr/bin/env bash
# Run one primary GigaCode agent across all non-excluded repositories.
set -Eeuo pipefail

WORKSPACE="${1:?Usage: $0 /path/to/projects [--restart] [--reset-validation-failures] [--reset-interrupted-failures]}"
shift
RESTART=0
RESET_VALIDATION_FAILURES=0
RESET_INTERRUPTED_FAILURES=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --restart) RESTART=1 ;;
    --reset-validation-failures) RESET_VALIDATION_FAILURES=1 ;;
    --reset-interrupted-failures) RESET_INTERRUPTED_FAILURES=1 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done

WORKSPACE="$(cd "$WORKSPACE" && pwd)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
MCP_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd -P)"
PROMPT_FILE="$SCRIPT_DIR/../references/workspace-campaign-prompt.md"
STATE_TOOL="$SCRIPT_DIR/project-context-campaign-state.py"
VALIDATE_TOOL="$SCRIPT_DIR/validate-project-context.sh"
EXCLUDE_FILE="${INDEX_EXCLUDE_FILE:-$MCP_ROOT/index-exclude.txt}"
STATE_FILE="${PROJECT_CONTEXT_STATE_FILE:-$MCP_ROOT/.project-context-authoring-campaign.json}"

if ! command -v gigacode >/dev/null 2>&1; then
  echo "gigacode was not found in PATH" >&2
  exit 1
fi
for required in "$PROMPT_FILE" "$STATE_TOOL" "$VALIDATE_TOOL"; do
  if [ ! -f "$required" ]; then
    echo "Required campaign file is missing: $required" >&2
    exit 1
  fi
done

PYTHON="${PYTHON_BIN:-}"
if [ -z "$PYTHON" ] && [ -n "${GIGACODE_HOME:-}" ] && [ -x "$GIGACODE_HOME/.venv/bin/python" ]; then
  PYTHON="$GIGACODE_HOME/.venv/bin/python"
fi
PYTHON="${PYTHON:-python3}"
"$PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' || {
  echo "Project-context campaign requires Python 3.10 or newer" >&2
  exit 1
}

INIT_ARGS=(init --workspace "$WORKSPACE" --state "$STATE_FILE" --exclude-file "$EXCLUDE_FILE")
if [ "$RESTART" = "1" ]; then
  INIT_ARGS+=(--restart)
fi
"$PYTHON" "$STATE_TOOL" "${INIT_ARGS[@]}"
if [ "$RESET_VALIDATION_FAILURES" = "1" ]; then
  "$PYTHON" "$STATE_TOOL" reset-validation-failures --state "$STATE_FILE"
fi
if [ "$RESET_INTERRUPTED_FAILURES" = "1" ]; then
  "$PYTHON" "$STATE_TOOL" reset-interrupted-failures --state "$STATE_FILE"
fi

PROMPT="$(<"$PROMPT_FILE")"
PROMPT+=$'\n\n## Параметры текущей кампании\n\n'
PROMPT+="- Workspace: $WORKSPACE"$'\n'
PROMPT+="- State file: $STATE_FILE"$'\n'
PROMPT+="- Excludes: $EXCLUDE_FILE"$'\n'
PROMPT+="- Максимум попыток на repository: 2"$'\n'

OUTPUT_FORMAT="${PROJECT_CONTEXT_OUTPUT_FORMAT:-stream-json}"
MAX_TURNS="${PROJECT_CONTEXT_MAX_TURNS:-1000}"
case "$MAX_TURNS" in
  ''|*[!0-9]*) echo "PROJECT_CONTEXT_MAX_TURNS must be a positive integer" >&2; exit 2 ;;
esac
if [ "$MAX_TURNS" -lt 1 ]; then
  echo "PROJECT_CONTEXT_MAX_TURNS must be a positive integer" >&2
  exit 2
fi

GIGACODE_ARGS=(
  --approval-mode=auto-edit
  --include-directories "$WORKSPACE"
  --exclude-tools agent
  --exclude-tools run_shell_command
  --allowed-mcp-server-names local-library-mcp
  --allowed-tools mcp__local-library-mcp__suggest_dependency
  --allowed-tools mcp__local-library-mcp__find_library_usages
  --allowed-tools mcp__local-library-mcp__project_context_campaign_next
  --allowed-tools mcp__local-library-mcp__project_context_campaign_start
  --allowed-tools mcp__local-library-mcp__project_context_campaign_finish
  --allowed-tools mcp__local-library-mcp__project_context_campaign_report
  --allowed-tools mcp__local-library-mcp__validate_project_context
  --max-session-turns "$MAX_TURNS"
)
if [ "$OUTPUT_FORMAT" = "stream-json" ]; then
  GIGACODE_ARGS+=(--output-format stream-json --include-partial-messages)
elif [ "$OUTPUT_FORMAT" != "text" ]; then
  echo "PROJECT_CONTEXT_OUTPUT_FORMAT must be text or stream-json" >&2
  exit 2
fi

echo "Starting one primary GigaCode agent for workspace: $WORKSPACE" >&2
echo "Campaign state: $STATE_FILE" >&2
echo "Dirty repositories are included; only exact names from $EXCLUDE_FILE are excluded." >&2
set +e
(
  cd "$WORKSPACE"
  gigacode "${GIGACODE_ARGS[@]}" "$PROMPT"
)
GIGACODE_CODE=$?
set -e

# Trust the agent only for authoring edits. Validate every reported success
# again outside the agent and return invalid repositories to the retry queue.
while IFS= read -r repository; do
  [ -n "$repository" ] || continue
  set +e
  VALIDATION_OUTPUT="$("$VALIDATE_TOOL" "$repository" 2>&1)"
  VALIDATION_CODE=$?
  set -e
  printf '%s\n' "$VALIDATION_OUTPUT"
  if [ "$VALIDATION_CODE" -ne 0 ]; then
    "$PYTHON" "$STATE_TOOL" invalidate \
      --state "$STATE_FILE" \
      --repository "$repository" \
      --message "Deterministic validation failed after the agent session. $VALIDATION_OUTPUT"
  fi
done < <("$PYTHON" "$STATE_TOOL" list --state "$STATE_FILE" --status successful)

echo "Campaign report:"
"$PYTHON" "$STATE_TOOL" report --state "$STATE_FILE"
if [ "$GIGACODE_CODE" -ne 0 ]; then
  echo "GigaCode campaign session failed with exit code $GIGACODE_CODE" >&2
  exit "$GIGACODE_CODE"
fi
set +e
"$PYTHON" "$STATE_TOOL" check --state "$STATE_FILE"
CHECK_CODE=$?
set -e
if [ "$CHECK_CODE" -ne 0 ]; then
  echo "Campaign is incomplete or has terminal failures; rerun the same command to resume." >&2
  exit "$CHECK_CODE"
fi

echo "Project-context campaign completed successfully."
