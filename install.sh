#!/usr/bin/env bash
set -euo pipefail

# Coding Hub installer — auto-detects platform, installs skill + commands.
# Usage: curl -fsSL https://raw.githubusercontent.com/zgsm-sangfor/costrict-skills-repo/main/install.sh | bash

BASE_URL="https://raw.githubusercontent.com/zgsm-sangfor/costrict-skills-repo/main"
COMMANDS="search browse recommend install uninstall update"

# --- Platform detection ---

detect_platform() {
  if [ -d "$HOME/.costrict" ] && \
     { [ -n "${VSCODE_PID:-}" ] || [ "${TERM_PROGRAM:-}" = "vscode" ]; }; then
    echo "vscode-costrict"
  elif [ -d "$HOME/.costrict" ]; then
    echo "costrict-cli"
  elif [ -d "$HOME/.opencode" ]; then
    echo "opencode"
  else
    echo "claude-code"
  fi
}

PLATFORM=$(detect_platform)

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

install_costrict_cli() {
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

echo "Detected platform: $PLATFORM"
echo ""

case "$PLATFORM" in
  claude-code)       install_claude_code ;;
  opencode)          install_opencode ;;
  costrict-cli)      install_costrict_cli ;;
  vscode-costrict)   install_vscode_costrict ;;
esac
