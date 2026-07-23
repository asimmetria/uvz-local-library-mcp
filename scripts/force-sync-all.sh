#!/usr/bin/env bash
# Reset every Git repository under a workspace to origin/master, with main fallback.
# WARNING: --apply discards uncommitted tracked/untracked changes and resets the target branch.
set -Eeuo pipefail

WORKSPACE="${1:?Usage: $0 /path/to/projects [--apply]}"
APPLY="${2:-}"

if [[ "$APPLY" != "--apply" ]]; then
  echo "Dry run. Repositories that would be reset under: $WORKSPACE"
  echo "Run again with --apply to discard local tracked and untracked changes."
  find "$WORKSPACE" -type d -name .git -prune -print | sed 's#/.git$##'
  exit 0
fi

find "$WORKSPACE" -type d -name .git -prune -print0 |
while IFS= read -r -d '' git_dir; do
  repository="${git_dir%/.git}"
  name="$(basename "$repository")"

  echo "=== $name ==="
  git -C "$repository" fetch origin --prune

  if git -C "$repository" show-ref --verify --quiet refs/remotes/origin/master; then
    branch="master"
  elif git -C "$repository" show-ref --verify --quiet refs/remotes/origin/main; then
    branch="main"
  else
    echo "SKIP: no origin/master or origin/main"
    continue
  fi

  # Clear the current checkout before switching branches: otherwise Git can
  # refuse checkout when a dirty file would be overwritten by master/main.
  git -C "$repository" reset --hard
  git -C "$repository" clean -fd
  git -C "$repository" checkout -f -B "$branch" "origin/$branch"
  git -C "$repository" reset --hard "origin/$branch"
  echo "OK: $branch → $(git -C "$repository" rev-parse --short HEAD)"
done
