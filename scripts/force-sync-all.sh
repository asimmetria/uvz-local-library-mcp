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

  # Remove untracked files first so they cannot block a forced checkout.
  git -C "$repository" clean -fd
  if git -C "$repository" show-ref --verify --quiet "refs/heads/$branch"; then
    # checkout -f discards tracked worktree changes while switching, but does
    # not reset the branch history yet.
    git -C "$repository" checkout -f "$branch"
  else
    git -C "$repository" checkout -f --track -b "$branch" "origin/$branch"
  fi
  git -C "$repository" reset --hard "origin/$branch"
  echo "OK: $branch → $(git -C "$repository" rev-parse --short HEAD)"
done
