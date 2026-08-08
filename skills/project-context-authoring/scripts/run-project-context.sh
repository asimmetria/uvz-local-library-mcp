#!/usr/bin/env bash
# Run one GigaCode authoring session for exactly one repository.
set -Eeuo pipefail

PROJECT="${1:?Usage: $0 /path/to/one-project}"
PROJECT="$(cd "$PROJECT" && pwd)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PROMPT_FILE="$SCRIPT_DIR/../references/repository-prompt.md"
CHECK_WORKTREE="$SCRIPT_DIR/check-authoring-worktree.sh"
GIGACODE_RUNNER="$SCRIPT_DIR/run-gigacode-noninteractive.sh"

if ! command -v gigacode >/dev/null 2>&1; then
  echo "gigacode was not found in PATH" >&2
  exit 1
fi

if [ ! -f "$PROMPT_FILE" ]; then
  echo "Repository prompt is missing: $PROMPT_FILE" >&2
  exit 1
fi

GIT_ROOT="$(git -C "$PROJECT" rev-parse --show-toplevel 2>/dev/null || true)"
if [ -z "$GIT_ROOT" ]; then
  echo "Not inside a Git repository: $PROJECT" >&2
  exit 1
fi
PROJECT="$(cd "$GIT_ROOT" && pwd)"
if ! "$CHECK_WORKTREE" "$PROJECT"; then
  echo "Refusing to start: repository has changes outside project-context.yaml and docs/usage/*.md" >&2
  exit 3
fi
PROMPT="$(<"$PROMPT_FILE")"
OUTPUT_FORMAT="${PROJECT_CONTEXT_OUTPUT_FORMAT:-stream-json}"
GIGACODE_ARGS=(
  --approval-mode=auto-edit
  --allowed-mcp-server-names local-library-mcp
  --allowed-tools mcp__local-library-mcp__suggest_dependency
  --allowed-tools mcp__local-library-mcp__find_library_usages
  --allowed-tools mcp__local-library-mcp__validate_project_context
)
if [ "$OUTPUT_FORMAT" = "stream-json" ]; then
  GIGACODE_ARGS+=(--output-format stream-json --include-partial-messages)
elif [ "$OUTPUT_FORMAT" != "text" ]; then
  echo "PROJECT_CONTEXT_OUTPUT_FORMAT must be text or stream-json" >&2
  exit 2
fi

cd "$PROJECT"
echo "Starting isolated GigaCode session in $PROJECT" >&2
"$GIGACODE_RUNNER" gigacode "${GIGACODE_ARGS[@]}" -p "$PROMPT"
if ! "$CHECK_WORKTREE" "$PROJECT"; then
  echo "FAILED SAFETY CHECK: agent changed files outside the authoring scope; inspect them manually" >&2
  exit 4
fi
"$SCRIPT_DIR/validate-project-context.sh" "$PROJECT"
