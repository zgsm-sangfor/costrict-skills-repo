# Coding Hub

<div align="center">
<img src="assets/title-card.jpg" alt="Coding Hub" />

<p><strong><!-- README_APPROX_COUNT:START -->4000<!-- README_APPROX_COUNT:END -->+ curated developer resources in one index</strong><br/>MCP Servers · Skills · Rules · Prompts</p>

<p>
  <a href="https://github.com/zgsm-sangfor/costrict-coding-hub/stargazers"><img src="https://img.shields.io/github/stars/zgsm-sangfor/costrict-coding-hub?style=flat-square&color=4A90D9" alt="Stars" /></a>
  <a href="https://github.com/zgsm-sangfor/costrict-coding-hub/blob/main/LICENSE"><img src="https://img.shields.io/github/license/zgsm-sangfor/costrict-coding-hub?style=flat-square" alt="License" /></a>
  <a href="https://github.com/zgsm-sangfor/costrict-coding-hub/commits/main"><img src="https://img.shields.io/github/last-commit/zgsm-sangfor/costrict-coding-hub?style=flat-square" alt="Last Commit" /></a>
  <img src="https://img.shields.io/badge/resources-4032-2ECC71?style=flat-square" alt="Resources" />
</p>

<p>
  <a href="./README.md"><strong>English</strong></a> ·
  <a href="./README.zh-CN.md">简体中文</a>
</p>

<p>
  <a href="#quick-start">Quick Start</a> ·
  <a href="https://zgsm-sangfor.github.io/costrict-coding-hub/">Browse Catalog</a> ·
  <a href="#catalog-overview">Catalog Overview</a> ·
  <a href="#platforms">Platforms</a> ·
  <a href="#for-agents">For Agents</a> ·
  <a href="#contributing">Contributing</a>
</p>

</div>

## Why Coding Hub?

AI coding agents are improving fast, but the ecosystem around them is still fragmented. Finding a reliable MCP server, reusable skill, practical rule set, or prompt collection usually means searching across multiple repositories and formats.

Coding Hub turns that scattered discovery process into a single searchable catalog. It continuously syncs from curated upstream sources, deduplicates entries, enriches metadata, scores quality signals, and packages the results so humans and agents can **search and install resources with one command**.

<a id="quick-start"></a>
## Quick Start

Install Coding Hub for your platform with one command:

**macOS / Linux**

```bash
# Costrict CLI (run from your project root)
curl -fsSL https://raw.githubusercontent.com/zgsm-sangfor/costrict-coding-hub/main/install.sh | bash -s -- --platform costrict

# VSCode Costrict extension
curl -fsSL https://raw.githubusercontent.com/zgsm-sangfor/costrict-coding-hub/main/install.sh | bash -s -- --platform vscode-costrict

# Claude Code
curl -fsSL https://raw.githubusercontent.com/zgsm-sangfor/costrict-coding-hub/main/install.sh | bash -s -- --platform claude-code

# Opencode (run from your project root)
curl -fsSL https://raw.githubusercontent.com/zgsm-sangfor/costrict-coding-hub/main/install.sh | bash -s -- --platform opencode
```

**Windows (PowerShell)**

```powershell
# Costrict CLI
irm https://raw.githubusercontent.com/zgsm-sangfor/costrict-coding-hub/main/install.ps1 | iex

# Specify the platform manually if auto-detection fails
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/zgsm-sangfor/costrict-coding-hub/main/install.ps1))) -Platform costrict
```

After installation, try a search command:

```bash
# Claude Code
/coding-hub:search typescript

# Opencode / Costrict CLI / VSCode Costrict (Roo Code)
/coding-hub-search typescript
```

<video src="https://github.com/user-attachments/assets/e58f0b08-73c0-4fba-ac95-138c8087a917" controls width="100%"></video>

You can also hand the installation off to another agent with this prompt:

```text
You are an installation assistant. Open the following URL, read the "For Agents" section,
and follow it exactly to install Coding Hub for the platform you are currently running on.

Do not clone the repository. Only read this raw file:
https://raw.githubusercontent.com/zgsm-sangfor/costrict-coding-hub/main/README.md

After installation, report which platform path was used and whether verification succeeded.
```

<div align="center">
<h3><a href="https://zgsm-sangfor.github.io/costrict-coding-hub/">Browse the full catalog →</a></h3>
<p>Search, filter, and explore all 4000+ resources with the interactive web catalog.</p>
</div>

<a id="catalog-overview"></a>
## Catalog Overview

| Type | Count | Description |
|------|------:|-------------|
| MCP Server | <!-- README_COUNT_MCP:START -->1627<!-- README_COUNT_MCP:END --> | Model Context Protocol servers |
| Prompt | <!-- README_COUNT_PROMPT:START -->531<!-- README_COUNT_PROMPT:END --> | Developer-focused prompts |
| Rule | <!-- README_COUNT_RULE:START -->236<!-- README_COUNT_RULE:END --> | Coding rules and AI workflow conventions |
| Skill | <!-- README_COUNT_SKILL:START -->1638<!-- README_COUNT_SKILL:END --> | Reusable agent skills |

### Data sources

Coding Hub aggregates data from multiple upstream sources, then republishes the cleaned catalog through GitHub Pages and raw GitHub endpoints.

| Type | Sources |
|------|---------|
| MCP | [awesome-mcp-servers](https://github.com/wong2/awesome-mcp-servers) · [Awesome-MCP-ZH](https://github.com/yzfly/Awesome-MCP-ZH) · [mcp.so](https://mcp.so) |
| Skills | Tier 1: [anthropics/skills](https://github.com/anthropics/skills) · [Ai-Agent-Skills](https://github.com/skillcreatorai/Ai-Agent-Skills) · [antigravity-awesome-skills](https://github.com/sickn33/antigravity-awesome-skills) · [ai-agents-public](https://github.com/vasilyu1983/ai-agents-public)<br/>Tier 2: [awesome-repo-configs / skill_repos.json](https://github.com/Chat2AnyLLM/awesome-repo-configs) · [awesome-openclaw-skills](https://github.com/VoltAgent/awesome-openclaw-skills) · [openclaw/skills](https://github.com/openclaw/skills)<br/>Tier 3: `catalog/skills/curated.json` |
| Rules | [awesome-cursorrules](https://github.com/PatrickJS/awesome-cursorrules) · [rules-2.1-optimized](https://github.com/Mr-chen-05/rules-2.1-optimized) |
| Prompts | [prompts.chat](https://github.com/f/prompts.chat) · [wonderful-prompts](https://github.com/langgptai/wonderful-prompts) |

### Pipeline at a glance

1. **Sync** — `scripts/sync_*.py` pull MCPs, skills, rules, and prompts from upstream sources.
2. **Merge** — `scripts/merge_index.py` deduplicates entries, enriches metadata, applies governance, and writes the merged catalog.
3. **Evaluate** — scoring combines source trust, relevance, content quality, freshness, and installability signals.
4. **Publish** — GitHub Actions refresh the catalog weekly, generate lightweight API files, and update both README languages.

<details>
<summary>Repository structure</summary>

```text
costrict-coding-hub/
├── install.sh                    # One-command installer for macOS/Linux
├── install.ps1                   # One-command installer for Windows
├── catalog/                      # Generated catalog data
│   ├── index.json                # Full merged index
│   ├── search-index.json         # Lightweight search index
│   ├── mcp/ skills/ rules/ prompts/
│   └── maintenance/              # Incremental recrawl state
├── docs/api/                     # Generated static API for GitHub Pages
├── platforms/                    # Per-platform skill + command definitions
├── scripts/                      # Sync, merge, scoring, and publishing scripts
├── .github/workflows/            # CI automation
└── openspec/                     # Change-management artifacts
```

</details>

<a id="platforms"></a>
## Platforms

Coding Hub supports four AI coding platforms. The resource catalog is shared, while command names and installation paths vary slightly by platform.

| | Claude Code | Costrict | Opencode | VSCode Costrict (Roo Code) |
|---|---|---|---|---|
| Search | `/coding-hub:search <kw> [type:mcp]` | `/coding-hub-search <kw> [type:mcp]` | `/coding-hub-search <kw> [type:mcp]` | `/coding-hub-search <kw> [type:mcp]` |
| Browse | `/coding-hub:browse [category]` | `/coding-hub-browse [category]` | `/coding-hub-browse [category]` | `/coding-hub-browse [category]` |
| Recommend | `/coding-hub:recommend` | `/coding-hub-recommend` | `/coding-hub-recommend` | `/coding-hub-recommend` |
| Install | `/coding-hub:install <name>` | `/coding-hub-install <name>` | `/coding-hub-install <name>` | `/coding-hub-install <name>` |
| Uninstall | `/coding-hub:uninstall <name>` | `/coding-hub-uninstall <name>` | `/coding-hub-uninstall <name>` | `/coding-hub-uninstall <name>` |
| Update | `/coding-hub:update` | `/coding-hub-update` | `/coding-hub-update` | `/coding-hub-update` |

<details>
<summary>Platform path differences</summary>

| | Claude Code | Costrict | VSCode Costrict | Opencode |
|---|---|---|---|---|
| Global skill path | `~/.claude/skills/coding-hub/` | `~/.costrict/skills/coding-hub/` | `~/.costrict/skills/coding-hub/` | `~/.opencode/skills/coding-hub/` |
| Command path | same global dir | `.costrict/coding-hub/commands/` (project) | `~/.roo/commands/` (global) | `.opencode/command/` (project) |
| Separator | `:` | `-` | `-` | `-` |

- **Costrict CLI** installs command files per project, so run the installer in each repository root.
- **VSCode Costrict / Roo Code** installs command files globally under `~/.roo/commands/`.
- **Claude Code** can load the full skill and subcommands from the global skills directory.
- **Opencode** installs commands per project under `.opencode/command/`.

</details>

<a id="for-agents"></a>
## For Agents

> If you are an AI agent installing Coding Hub automatically, follow this section exactly.

### Step 1: Run the installer

The install scripts auto-detect the host platform when possible.

**macOS / Linux**

```bash
curl -fsSL https://raw.githubusercontent.com/zgsm-sangfor/costrict-coding-hub/main/install.sh | bash
```

**Windows (PowerShell)**

```powershell
irm https://raw.githubusercontent.com/zgsm-sangfor/costrict-coding-hub/main/install.ps1 | iex
```

Auto-detection uses process-level environment variables that each platform injects at startup:

| Environment variable | Platform |
|----------------------|----------|
| `COSTRICT_CALLER=vscode` | VSCode Costrict extension |
| `COSTRICT_RUNNING=1` | Costrict CLI |
| `CLAUDECODE=1` | Claude Code |
| `OPENCODE=1` | Opencode |

If auto-detection fails, specify the platform manually.

**macOS / Linux**

```bash
curl -fsSL https://raw.githubusercontent.com/zgsm-sangfor/costrict-coding-hub/main/install.sh | bash -s -- --platform <platform>
```

**Windows (PowerShell)**

```powershell
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/zgsm-sangfor/costrict-coding-hub/main/install.ps1))) -Platform <platform>
```

Examples:

```bash
# Claude Code (macOS/Linux)
curl -fsSL https://raw.githubusercontent.com/zgsm-sangfor/costrict-coding-hub/main/install.sh | bash -s -- --platform claude-code

# Opencode (run from the project root)
curl -fsSL https://raw.githubusercontent.com/zgsm-sangfor/costrict-coding-hub/main/install.sh | bash -s -- --platform opencode
```

```powershell
# Claude Code (Windows)
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/zgsm-sangfor/costrict-coding-hub/main/install.ps1))) -Platform claude-code
```

<details>
<summary>Fallback: manual installation without <code>curl | bash</code></summary>

Run the platform-specific commands below if you need to download the files directly.

**Costrict CLI** (global skill + project commands)

```bash
mkdir -p ~/.costrict/skills/coding-hub
curl -fsSL "https://raw.githubusercontent.com/zgsm-sangfor/costrict-coding-hub/main/platforms/costrict/skills/coding-hub/SKILL.md" -o ~/.costrict/skills/coding-hub/SKILL.md
mkdir -p .costrict/coding-hub/commands
for cmd in search browse recommend install uninstall update; do
  curl -fsSL "https://raw.githubusercontent.com/zgsm-sangfor/costrict-coding-hub/main/platforms/costrict/commands/coding-hub/coding-hub-${cmd}.md" -o .costrict/coding-hub/commands/coding-hub-${cmd}.md
done
```

**VSCode Costrict extension / Roo Code** (global skill + global commands)

```bash
mkdir -p ~/.costrict/skills/coding-hub
curl -fsSL "https://raw.githubusercontent.com/zgsm-sangfor/costrict-coding-hub/main/platforms/vscode-costrict/skills/coding-hub/SKILL.md" -o ~/.costrict/skills/coding-hub/SKILL.md
mkdir -p ~/.roo/commands
for cmd in search browse recommend install uninstall update; do
  curl -fsSL "https://raw.githubusercontent.com/zgsm-sangfor/costrict-coding-hub/main/platforms/vscode-costrict/commands/coding-hub/coding-hub-${cmd}.md" -o ~/.roo/commands/coding-hub-${cmd}.md
done
```

**Claude Code** (global skill + global commands)

```bash
mkdir -p ~/.claude/skills/coding-hub
curl -fsSL "https://raw.githubusercontent.com/zgsm-sangfor/costrict-coding-hub/main/platforms/claude-code/skills/coding-hub/SKILL.md" -o ~/.claude/skills/coding-hub/SKILL.md
for cmd in search browse recommend install uninstall update; do
  curl -fsSL "https://raw.githubusercontent.com/zgsm-sangfor/costrict-coding-hub/main/platforms/claude-code/commands/coding-hub/${cmd}.md" -o ~/.claude/skills/coding-hub/${cmd}.md
done
```

**Opencode** (global skill + project commands)

```bash
mkdir -p ~/.opencode/skills/coding-hub
curl -fsSL "https://raw.githubusercontent.com/zgsm-sangfor/costrict-coding-hub/main/platforms/opencode/skills/coding-hub/SKILL.md" -o ~/.opencode/skills/coding-hub/SKILL.md
mkdir -p .opencode/command
for cmd in search browse recommend install uninstall update; do
  curl -fsSL "https://raw.githubusercontent.com/zgsm-sangfor/costrict-coding-hub/main/platforms/opencode/command/coding-hub-${cmd}.md" -o .opencode/command/coding-hub-${cmd}.md
done
```

</details>

### Step 2: Verify the installation

Run a search command to confirm that the commands are available:

```text
# Costrict CLI / Opencode
/coding-hub-search typescript

# VSCode Costrict extension
Send this in the chat: "Search typescript with coding-hub"

# Claude Code
/coding-hub:search typescript
```

Expected result: a Markdown table of matching resources. If the command is missing, the installation did not land in the correct platform path.

### Available commands

| Command | Description |
|---------|-------------|
| `search <keyword> [type:mcp\|skill\|rule\|prompt]` | Search resources, optionally filtered by type |
| `browse [category] [type:...]` | Browse by category |
| `recommend [type:...]` | Recommend resources based on the current project stack |
| `install <name>` | Install a resource |
| `uninstall <name>` | Uninstall a resource |
| `update` | Pull the latest Coding Hub files |

### Data endpoints

Search, browse, and recommend operate on a lightweight search index. Installation fetches a per-entry API document.

| Purpose | URL |
|---------|-----|
| Search index | `https://zgsm-sangfor.github.io/costrict-coding-hub/api/v1/search-index.json` |
| Entry API | `https://zgsm-sangfor.github.io/costrict-coding-hub/api/v1/{type}/{id}.json` |
| Type index | `https://zgsm-sangfor.github.io/costrict-coding-hub/api/v1/{type}/index.json` |
| Full index fallback | `https://raw.githubusercontent.com/zgsm-sangfor/costrict-coding-hub/main/catalog/index.json` |

## Why Costrict?

If you like the Coding Hub workflow, try **[Costrict](https://github.com/zgsm-ai/costrict)** — our broader AI coding agent platform built for stronger automation and team workflows.

[Explore Costrict →](https://github.com/zgsm-ai/costrict)

<a id="contributing"></a>
## Contributing

Contributions are welcome. Open a PR against the appropriate directory under `catalog/` and make sure the resource:

- is relevant to coding or AI-assisted development,
- has an accurate `source_url`, `description`, and tags,
- follows `catalog/schema.json`.

## Disclaimer

Coding Hub is an index and installation helper for third-party open-source resources. Every MCP server, skill, rule, and prompt listed in the catalog remains the property of its original author.

This repository does **not** guarantee the safety, availability, accuracy, or compliance of third-party resources. Review source code and licenses before use, and open an issue if you find security or copyright problems.

Coding Hub is released under the [MIT License](LICENSE).
