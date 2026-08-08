#!/usr/bin/env bash
# List Git repository roots below a workspace, including non-Gradle projects.
set -Eeuo pipefail

WORKSPACE="${1:?Usage: $0 /path/to/projects}"
WORKSPACE="$(cd "$WORKSPACE" && pwd)"

find "$WORKSPACE" -name .git -prune -print0 |
while IFS= read -r -d '' git_marker; do
  printf '%s\n' "${git_marker%/.git}"
done | sort
