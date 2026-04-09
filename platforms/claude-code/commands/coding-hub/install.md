---
description: 'Install a coding resource. Usage: /coding-hub:install <name>'
---

# Coding Hub - Install

$ARGUMENTS

---

## Language Detection

Determine the output language using the following priority chain (first match wins):

1. **Explicit parameter**: if `$ARGUMENTS` contains `lang:zh` or `lang:en`, use that (strip it from arguments)
2. **Conversation signal**: if the user's recent messages are clearly in one language, follow that
3. **System locale fallback**: run `echo $LANG` in Bash — if the value starts with `zh` (e.g. `zh_CN.UTF-8`), use Chinese; otherwise use English

Once determined, apply consistently:
- **All output** (confirmation dialogs, status messages, error messages) MUST be in the detected language.
- Command references and file paths stay as-is regardless of language.

## Data Sources

Per-entry API: `https://zgsm-sangfor.github.io/costrict-coding-hub/api/v1/{type}/{id}.json`
Full index (fallback): `https://raw.githubusercontent.com/zgsm-sangfor/costrict-coding-hub/main/catalog/index.json`
Local fallback: `/Volumes/Work/Projects/costrict-coding-hub/catalog/index.json`

## Execution Flow

1. Extract resource name from `$ARGUMENTS`
2. Look up entry by ID via per-entry API (requires determining type and id from search index first):
   - Download search index: `curl -sf --compressed https://zgsm-sangfor.github.io/costrict-coding-hub/api/v1/search-index.json`
   - Fuzzy match on name/id with Python to determine the entry's `type` and `id`
   - If exactly one match found, fetch full data: `curl -sf --compressed https://zgsm-sangfor.github.io/costrict-coding-hub/api/v1/{type}/{id}.json`
   - If multiple matches, list them and let the user choose, then fetch the selected one
3. If Pages API unavailable, fall back to full index: `curl -s <full index URL>`, on failure use Read on local fallback path
4. Show install preview (in user's language):

```
Structure:
  Section: "Install Confirmation"
  - Name: xxx
  - Type: MCP Server
  - Description: (use description_zh or description per Language Rule)
  - Source: xxx
  - Target: .claude/settings.json (project-level)

  Prompt: "Confirm install? (Y/n/global)"
```

5. Execute installation based on user confirmation and resource type:

### MCP (type == "mcp")
- Default: write to `.claude/settings.json`; if user chooses "global", write to `~/.claude/settings.json`
- Read existing settings.json (create `{}` if not found)
- Handle by `install.method`:

#### method == "mcp_config"
- Merge `install.config` directly into the `mcpServers` field
- If key already exists, ask whether to overwrite
- If `install.config.env` contains any values → run **Post-Install Configuration Guide** (see below)

#### method == "mcp_config_template"
- Write `install.config` into `mcpServers` field first (so entry exists even if user skips config)
- Then run **Post-Install Configuration Guide** (see below)

#### Post-Install Configuration Guide

When the installed MCP config contains `env` fields (API keys, tokens, connection strings, etc.):

1. **Detect unconfigured env vars** — any env value that is empty, contains `<`, `YOUR_`, or placeholder-like patterns
2. **Fetch the project README for setup guidance**:
   - Use WebFetch on the entry's `source_url` with prompt: "Extract: 1) What API keys or environment variables are needed 2) How to obtain them (signup URL, steps) 3) Example configuration. Be concise, bullet points only."
   - If `source_url` is a GitHub monorepo subpath and fetch fails, try the repo root URL instead
3. **Present actionable guidance** to the user (in detected language):
```
Structure:
  Section: "Configuration Required"
  Per env var:
    - KEY_NAME: [guidance extracted from README — how to obtain, signup URL, etc.]
  Action: "Would you like me to help you fill in these values now?"
```
4. **If user provides values**, update the settings.json entry directly
5. **If README is unavailable**, fall back to showing env var names and `source_url` link

#### method == "manual"
No pre-built install config in the index — infer install method from project README. Steps:

**Step 1: Fetch README**
- Construct raw URL from `source_url`:
  - Try `https://raw.githubusercontent.com/{owner}/{repo}/main/README.md`
  - If 404, try `master` branch
- If fetch fails, go to Step 3 fallback

**Step 2: Analyze README and generate install config**
Read README content, determine the MCP Server's install method, construct `mcpServers` JSON config:

- **Has existing `mcpServers` JSON** → extract and use directly
- **Has `npx -y <package>` command** → construct `{"command": "npx", "args": ["-y", "<package>"]}`
- **Has `uvx <package>` command** → construct `{"command": "uvx", "args": ["<package>"]}`
- **Has `pip install` + `python -m` startup** → construct `{"command": "python", "args": ["-m", "<module>"]}`
- **Requires env vars (API keys etc.)** → add `"env"` field with empty values or placeholders

After construction:
- Show the generated config to user, explain the inference basis (which part of README)
- On user confirmation, write using `mcp_config` or `mcp_config_template` flow
- If placeholders/env vars present, prompt user to fill them

**Step 3: Fallback (README unavailable or cannot determine install method)**
```
Structure:
  Message: "This MCP requires manual configuration. Please refer to the project docs:"
  Link: source_url
  Instruction: "Follow the README instructions to configure mcpServers."
```

### Skill (type == "skill")
- If `install.repo` exists, execute sparse checkout or clone + copy
- Target: `~/.claude/skills/<id>/`
- If directory already exists, ask whether to overwrite

### Rule (type == "rule")
- Download files from `install.files`
- Default: save to `.claude/rules/<id>.md`; if user chooses "global", save to `~/.claude/rules/<id>.md`
- If .cursorrules format, preserve original text content

### Prompt (type == "prompt")
- Same install logic as Rule
- Save to `.claude/rules/<id>.md`

6. After installation, show result and usage instructions (in user's language)

## Error Handling

- If curl fails to fetch index: inform user of network issue and suggest retry
- If writing to target file fails: show permission error
- If resource not found: suggest using `/coding-hub:search` to search
