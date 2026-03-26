#!/usr/bin/env bash
set -euo pipefail

# Coding Hub installer — requires explicit platform selection.
# Usage: curl -fsSL .../install.sh | bash -s -- --platform <platform>
#
# Platforms: claude-code, opencode, costrict, vscode-costrict

BASE_URL="https://raw.githubusercontent.com/zgsm-sangfor/costrict-skills-repo/main"
COMMANDS="search browse recommend install uninstall update"

# --- Parse arguments ---

PLATFORM=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --platform|-p)
      PLATFORM="$2"
      shift 2
      ;;
    claude-code|opencode|costrict|vscode-costrict)
      PLATFORM="$1"
      shift
      ;;
    *)
      echo "Unknown argument: $1" >&2
      echo "" >&2
      echo "Usage: bash install.sh --platform <platform>" >&2
      echo "Platforms: claude-code, opencode, costrict, vscode-costrict" >&2
      exit 1
      ;;
  esac
done

if [ -z "$PLATFORM" ]; then
  echo "ERROR: --platform is required." >&2
  echo "" >&2
  echo "Usage:" >&2
  echo "  curl -fsSL .../install.sh | bash -s -- --platform claude-code" >&2
  echo "  curl -fsSL .../install.sh | bash -s -- --platform opencode" >&2
  echo "  curl -fsSL .../install.sh | bash -s -- --platform costrict" >&2
  echo "  curl -fsSL .../install.sh | bash -s -- --platform vscode-costrict" >&2
  exit 1
fi

# --- Download helper ---

download() {
  local url="$1" dest="$2"
  if ! curl -fsSL "$url" -o "$dest"; then
    echo "ERROR: Failed to download $url" >&2
    exit 1
  fi
}

# --- Install per platform ---
# SKILL.md → global skills dir (always available)
# Commands → project-level dir (CWD) for opencode/costrict (they only load commands from project dir)
# Claude Code is special: it loads sub .md files from skills dir as slash commands, so all-global works.

install_claude_code() {
  local skill_dir="$HOME/.claude/skills/coding-hub"
  mkdir -p "$skill_dir"

  echo "Downloading skill + commands..."
  download "$BASE_URL/platforms/claude-code/skills/coding-hub/SKILL.md" "$skill_dir/SKILL.md"
  for cmd in $COMMANDS; do
    download "$BASE_URL/platforms/claude-code/commands/coding-hub/${cmd}.md" "$skill_dir/${cmd}.md"
  done

  echo ""
  echo "=== Coding Hub installed (Claude Code) ==="
  echo ""
  echo "Skill + commands: $skill_dir/"
  echo ""
  echo "Try:  /coding-hub:search typescript"
}

install_opencode() {
  local skill_dir="$HOME/.opencode/skills/coding-hub"
  local cmd_dir=".opencode/command"
  mkdir -p "$skill_dir" "$cmd_dir"

  echo "Downloading skill..."
  download "$BASE_URL/platforms/opencode/skills/coding-hub/SKILL.md" "$skill_dir/SKILL.md"

  echo "Downloading commands to project dir..."
  for cmd in $COMMANDS; do
    download "$BASE_URL/platforms/opencode/command/coding-hub-${cmd}.md" "$cmd_dir/coding-hub-${cmd}.md"
  done

  echo ""
  echo "=== Coding Hub installed (Opencode) ==="
  echo ""
  echo "Skill (global): $skill_dir/"
  echo "Commands (project): $(pwd)/$cmd_dir/"
  echo ""
  echo "Note: Commands are installed to the current directory."
  echo "      Run this script again in other projects to add commands there too."
  echo ""
  echo "Try:  /coding-hub-search typescript"
}

install_costrict() {
  local skill_dir="$HOME/.costrict/skills/coding-hub"
  local cmd_dir=".costrict/coding-hub/commands"
  mkdir -p "$skill_dir" "$cmd_dir"

  echo "Downloading skill..."
  download "$BASE_URL/platforms/costrict/skills/coding-hub/SKILL.md" "$skill_dir/SKILL.md"

  echo "Downloading commands to project dir..."
  for cmd in $COMMANDS; do
    download "$BASE_URL/platforms/costrict/commands/coding-hub/coding-hub-${cmd}.md" "$cmd_dir/coding-hub-${cmd}.md"
  done

  echo ""
  echo "=== Coding Hub installed (Costrict CLI) ==="
  echo ""
  echo "Skill (global): $skill_dir/"
  echo "Commands (project): $(pwd)/$cmd_dir/"
  echo ""
  echo "Note: Commands are installed to the current directory."
  echo "      Run this script again in other projects to add commands there too."
  echo ""
  echo "Try:  /coding-hub-search typescript"
}

install_vscode_costrict() {
  local skill_dir="$HOME/.costrict/skills/coding-hub"
  mkdir -p "$skill_dir"

  echo "Downloading skill..."
  download "$BASE_URL/platforms/vscode-costrict/skills/coding-hub/SKILL.md" "$skill_dir/SKILL.md"

  echo ""
  echo "=== Coding Hub installed (VSCode Costrict) ==="
  echo ""
  echo "Skill: $skill_dir/"
  echo ""
  echo "Try:  ask your assistant to 'search typescript with coding-hub'"
}

# --- Main ---

echo "Platform: $PLATFORM"
echo ""

case "$PLATFORM" in
  claude-code)       install_claude_code ;;
  opencode)          install_opencode ;;
  costrict)          install_costrict ;;
  vscode-costrict)   install_vscode_costrict ;;
  *)
    echo "ERROR: Unknown platform '$PLATFORM'" >&2
    echo "Valid platforms: claude-code, opencode, costrict, vscode-costrict" >&2
    exit 1
    ;;
esac
