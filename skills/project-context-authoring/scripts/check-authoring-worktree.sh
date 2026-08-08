#!/usr/bin/env bash
# Return non-zero when a repository has changes outside authoring-owned files.
set -Eeuo pipefail

PROJECT="${1:?Usage: $0 /path/to/one-project}"
GIT_ROOT="$(git -C "$PROJECT" rev-parse --show-toplevel 2>/dev/null || true)"
if [ -z "$GIT_ROOT" ]; then
  echo "Not inside a Git repository: $PROJECT" >&2
  exit 2
fi

unsafe=0
while IFS= read -r changed; do
  [ -n "$changed" ] || continue
  path="${changed:3}"
  path="${path##* -> }"
  # Nested Gradle/Maven/npm builds can leave untracked generated state even in
  # otherwise clean repositories. It is neither authoring input nor a user
  # source change, so do not make developers delete it to run the skill.
  case "/$path/" in
    */.gradle/*|*/build/*|*/target/*|*/node_modules/*)
      continue
      ;;
  esac
  case "$path" in
    project-context.yaml|*/project-context.yaml|docs/usage/*.md|*/docs/usage/*.md)
      ;;
    *)
      echo "$changed"
      unsafe=1
      ;;
  esac
done < <(git -C "$GIT_ROOT" -c core.quotepath=false status --porcelain --untracked-files=all)

exit "$unsafe"
