#!/usr/bin/env bash
# List Git roots that look like Gradle projects. Choose one and pass it to
# run-project-context.sh; this script never starts an agent itself.
set -Eeuo pipefail

WORKSPACE="${1:?Usage: $0 /path/to/projects}"

find "$WORKSPACE" -type d -name .git -prune -print0 |
while IFS= read -r -d '' git_dir; do
  project="${git_dir%/.git}"
  if [[ -f "$project/settings.gradle.kts" || -f "$project/settings.gradle" || -f "$project/build.gradle.kts" || -f "$project/build.gradle" ]]; then
    printf '%s\n' "$project"
  fi
done | sort
