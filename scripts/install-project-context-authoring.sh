#!/usr/bin/env bash
# Manually install the optional project-context-authoring skill for this user.
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILL_SOURCE="$SCRIPT_DIR/../skills/project-context-authoring"

if [ ! -f "$SKILL_SOURCE/SKILL.md" ]; then
  echo "Skill source is missing: $SKILL_SOURCE" >&2
  exit 1
fi

if [ -n "${GIGACODE_HOME:-}" ]; then
  GIGACODE_HOME="$GIGACODE_HOME"
elif [ -d "$HOME/.gigacode" ] && [ -w "$HOME/.gigacode" ]; then
  GIGACODE_HOME="$HOME/.gigacode"
else
  GIGACODE_HOME=""
  candidate="$SCRIPT_DIR"
  while [ "$candidate" != "/" ]; do
    if [ -d "$candidate/.gigacode" ]; then
      GIGACODE_HOME="$candidate/.gigacode"
      break
    fi
    candidate="$(dirname "$candidate")"
  done
  GIGACODE_HOME="${GIGACODE_HOME:-$HOME/.gigacode}"
fi

mkdir -p "$GIGACODE_HOME/skills"
ln -sfn "$SKILL_SOURCE" "$GIGACODE_HOME/skills/project-context-authoring"

echo "Installed project-context-authoring skill: $GIGACODE_HOME/skills/project-context-authoring"
echo "Restart GigaCode to load the skill."
