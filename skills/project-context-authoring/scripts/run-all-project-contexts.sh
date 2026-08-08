#!/usr/bin/env bash
# Process repositories sequentially in isolated GigaCode workspaces with resume state.
set -Eeuo pipefail

WORKSPACE="${1:?Usage: $0 /path/to/projects [--restart]}"
shift
RESTART=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --restart) RESTART=1 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done

WORKSPACE="$(cd "$WORKSPACE" && pwd)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
MCP_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd -P)"
RUN_ONE="$SCRIPT_DIR/run-project-context.sh"
LIST_PROJECTS="$SCRIPT_DIR/list-projects.sh"
CHECK_WORKTREE="$SCRIPT_DIR/check-authoring-worktree.sh"
EXCLUDE_FILE="${INDEX_EXCLUDE_FILE:-$MCP_ROOT/index-exclude.txt}"
STATE_FILE="${PROJECT_CONTEXT_STATE_FILE:-$MCP_ROOT/.project-context-authoring-state.tsv}"
LOG_DIR="${PROJECT_CONTEXT_LOG_DIR:-$MCP_ROOT/.project-context-authoring-logs}"

mkdir -p "$(dirname "$STATE_FILE")" "$LOG_DIR"
if [ "$RESTART" = "1" ] && [ -f "$STATE_FILE" ]; then
  backup="$STATE_FILE.$(date -u +%Y%m%dT%H%M%SZ).bak"
  mv "$STATE_FILE" "$backup"
  echo "Previous state moved to $backup"
fi
touch "$STATE_FILE"

excluded_by_file() {
  local name="$1"
  [ -f "$EXCLUDE_FILE" ] || return 1
  awk -v expected="$name" '
    {
      sub(/#.*/, "")
      gsub(/^[[:space:]]+|[[:space:]]+$/, "")
      if ($0 == expected) found = 1
    }
    END { exit(found ? 0 : 1) }
  ' "$EXCLUDE_FILE"
}

latest_state() {
  local project="$1"
  awk -F '\t' -v expected="$project" '
    $4 == expected { status = $2; commit = $3 }
    END { if (status != "") print status "\t" commit }
  ' "$STATE_FILE"
}

record_state() {
  local project="$1" commit="$2" status="$3"
  printf '%s\t%s\t%s\t%s\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$status" "$commit" "$project" >> "$STATE_FILE"
}

successful=0
failed=0
skipped=0
resumed=0
index=0

while IFS= read -r project; do
  [ -n "$project" ] || continue
  index=$((index + 1))
  name="$(basename "$project")"
  case "$name" in
    uvz-local-library-mcp|jimmer|jimmer-docs|jimmer-examples)
      echo "=== [$index] Пропущен служебный/public repository: $name ==="
      skipped=$((skipped + 1))
      continue
      ;;
  esac
  if excluded_by_file "$name"; then
    echo "=== [$index] Исключён через index-exclude.txt: $name ==="
    skipped=$((skipped + 1))
    continue
  fi
  commit="$(git -C "$project" rev-parse HEAD 2>/dev/null || printf unknown)"
  previous="$(latest_state "$project")"
  if [ "$previous" = "successful"$'\t'"$commit" ]; then
    if "$SCRIPT_DIR/validate-project-context.sh" "$project" >/dev/null 2>&1; then
      echo "=== [$index] Уже успешно обработан, пропуск: $name ==="
      resumed=$((resumed + 1))
      continue
    fi
  fi
  echo "=== [$index] Проверка: $name ==="
  if ! "$CHECK_WORKTREE" "$project"; then
    echo "SKIPPED_DIRTY: $project"
    record_state "$project" "$commit" "skipped_dirty"
    skipped=$((skipped + 1))
    continue
  fi
  log="$LOG_DIR/$(printf '%04d' "$index")-$name.log"
  echo "=== [$index] Обработка: $project ==="
  echo "Лог: $log"
  set +e
  "$RUN_ONE" "$project" 2>&1 | tee "$log"
  code=${PIPESTATUS[0]}
  set -e
  if [ "$code" -eq 0 ]; then
    record_state "$project" "$commit" "successful"
    successful=$((successful + 1))
    echo "SUCCESSFUL: $project"
  else
    record_state "$project" "$commit" "failed"
    failed=$((failed + 1))
    echo "FAILED ($code): $project" >&2
  fi
done < <("$LIST_PROJECTS" "$WORKSPACE")

echo
echo "Project-context campaign finished"
echo "successful: $successful"
echo "failed: $failed"
echo "skipped: $skipped"
echo "resumed successful: $resumed"
echo "state: $STATE_FILE"
echo "logs: $LOG_DIR"

if [ "$failed" -gt 0 ]; then
  exit 1
fi
