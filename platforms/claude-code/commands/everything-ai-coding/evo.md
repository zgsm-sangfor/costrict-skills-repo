---
description: 'Evolve a locally installed skill / prompt / rule. Usage: /everything-ai-coding:evo <id>'
---

# Everything AI Coding - Evo

$ARGUMENTS

---

> 📖 **Rubric attribution** — the 7-dimension skill rubric and 4-dimension prompt/rule rubric used below are adapted from [darwin-skill](https://github.com/alchaincyf/darwin-skill) (MIT License © 花叔). darwin-skill originated the "structure + effectiveness" dual-evaluation idea for SKILL.md files. This command simplifies it for on-demand client-side use: the dynamic "live test" dimension and the ratchet mechanism are deferred. See `docs/wiki/evo-rubric.md` in the main repository for full dimension descriptions.

## Language Detection

Determine the output language using the following priority chain (first match wins):

1. **Explicit parameter**: if `$ARGUMENTS` contains `lang:zh` or `lang:en`, use that (strip it from arguments)
2. **Conversation signal**: if the user's recent messages are clearly in one language, follow that
3. **System locale fallback**: run `echo $LANG` in Bash — if the value starts with `zh` (e.g. `zh_CN.UTF-8`), use Chinese; otherwise use English

Once determined, apply consistently:
- **All output** (status messages, rubric labels, diff summaries, prompts) MUST be in the detected language.
- Command references and file paths stay as-is regardless of language.

## Prompt Rendering Rule

Whenever a prompt asks the user to pick an option with letters, ALWAYS render each option with an explicit label. Use these bilingual templates:

| Pattern | English | Chinese |
|---------|---------|---------|
| `Y/n/edit` (apply/adjust/reject) | `(Y = apply as shown / n = discard, keep original / edit = tell me what to tweak)` | `（Y = 应用改动 / n = 放弃，保留原样 / edit = 告诉我怎么改）` |
| dimension-pick | `(all = improve all weak dimensions / comma-separated dimension numbers / skip = exit without changes)` | `（all = 改进所有弱项 / 逗号分隔维度编号 / skip = 不改，退出）` |

Every bare `(Y/n/edit)` or `(all/numbers/skip)` MUST be expanded at render time.

## Scope and Applicability

This command operates ONLY on resources already installed locally. It does NOT touch the catalog index, does NOT open upstream PRs, and does NOT persist any data outside the user's home configuration directory.

Supported resource types: **skill**, **prompt**, **rule**.
**Refused type**: **mcp** (configuration-only, no textual body to improve).

## Data Sources

**Note**: Apply GitHub Network Detection rules (see SKILL.md) to all GitHub URLs below.

Search index (for id → type resolution): `https://zgsm-ai.github.io/everything-ai-coding/api/v1/search-index.json`
Per-entry API (optional, for displaying catalog `weak_dims` as a starting hint): `https://zgsm-ai.github.io/everything-ai-coding/api/v1/{type}/{id}.json`

## Local Paths

Target files to evolve (search in order; stop at first found):

| Type | Search paths |
|------|--------------|
| skill | `~/.claude/skills/<id>/SKILL.md` |
| rule | `.claude/rules/<id>.md` → `~/.claude/rules/<id>.md` |
| prompt | `.claude/rules/<id>.md` → `~/.claude/rules/<id>.md` (same as rule) |

History cache directory: `~/.claude/.evo/<id>/history.json`

## Execution Flow

### Step 1 — Parse arguments

Extract resource ID from `$ARGUMENTS` (strip `lang:*` parameter if present). If no ID provided, print usage hint and stop.

### Step 2 — Resolve type via search index

1. Fetch search index: `curl -sf --compressed https://zgsm-ai.github.io/everything-ai-coding/api/v1/search-index.json`
2. Exact match on `id` first; else fuzzy match on name/id (Python-side filter)
3. If multiple candidates, list them and let user choose
4. Record the resolved `type`

**If type is `mcp`**, stop immediately with a message:
> Evo does not apply to MCP servers — MCP resources are configuration-only and have no textual body to improve. To reconfigure, edit `.claude/settings.json` or reinstall via `/everything-ai-coding:install <id>`.

### Step 3 — Locate local copy

Check the target paths listed in "Local Paths" above for the resolved type. If no local copy exists:

> This resource is not installed. Run `/everything-ai-coding:install <id>` first, then come back to evo.

Stop without any further action.

### Step 4 — Static lint pre-flight (no LLM call)

Before any LLM invocation, validate the local file's structural integrity.

**Skill lint rules**:
- File starts with `---` and has a matching closing `---` (frontmatter exists)
- Frontmatter contains `name` (non-empty, matches regex `^[a-z0-9][a-z0-9-]*$`)
- Frontmatter contains `description` (non-empty)
- All markdown code fences (```...```) are closed
- No illegal control characters (`\x00-\x1f` except `\n`, `\t`, `\r`)

**Prompt / Rule lint rules**:
- File size ≥ 50 bytes
- All markdown code fences closed
- No illegal control characters

**On lint failure**: list the specific failures, suggest a fix, and stop. Do NOT proceed to LLM scoring — fix the file first.

**`.cursorrules` exception**: for rules whose file extension is `.cursorrules` or whose first line does not start with `#`, only check file size + control characters. Skip markdown fence check.

### Step 5 — Fetch catalog weak_dims hint (optional, for display only)

Try to fetch per-entry API for the resource and extract `evaluation.weak_dims` (from catalog's 6-dim rubric). This is a **courtesy display** — it tells the user which dimensions the catalog already flagged. It is NOT used as input to evo's own scoring.

If per-entry API unavailable or `weak_dims` empty, continue without this hint.

### Step 6 — LLM scoring call

Dispatch an LLM scoring call with the embedded rubric prompt. **The exact rubric text, weights, dimension keys, and 1-10 band descriptions MUST match `docs/wiki/evo-rubric.md` in the main repository** — this is the source of truth.

**Rubric summary (embed in the LLM prompt)**:

For **skill** type (7 dimensions, total 100):

| # | Key | Weight | What it evaluates |
|---|-----|--------|-------------------|
| D1 | `frontmatter_description_quality` | 10 | Can the description field let the Agent decide when to activate this skill? |
| D2 | `workflow_clarity` | 20 | Are the steps/phases in the body executable by following them literally? |
| D3 | `instruction_specificity` | 20 | Is each instruction at "directly runnable" level (has concrete params/format/examples)? |
| D4 | `edge_case_coverage` | 15 | Does it cover failure paths / boundary conditions / error recovery? |
| D5 | `checkpoint_design` | 10 | Are there user confirmations before irreversible actions? |
| D6 | `resource_integration` | 5 | Are references/scripts/assets cited correctly and with clear usage? |
| D7 | `overall_architecture` | 20 | Is the structure layered, non-redundant, internally consistent? |

For **prompt** and **rule** types (4 dimensions, total 100): D2 (31), D3 (31), D6 (8), D7 (30) — same band descriptions as skill, with D1/D4/D5 skipped as they're generally not applicable to plain-text prompts/rules.

**LLM output contract (JSON, strict)**:

```json
{
  "dimensions": {
    "<dim_key>": {
      "score": <1-10 integer>,
      "weight": <number>,
      "reason": "<short sentence>",
      "suggestion": "<concrete improvement hint>"
    }
  },
  "total_score": <0-100 weighted sum>
}
```

Use the project's LLM (same model already used for `/everything-ai-coding:install` customization flow). For claude-code, this is the live Claude conversation; no external API key needed.

### Step 7 — Display scoring results

Render the scoring results in the active language. Order dimensions by `score` ascending (weakest first).

```
Structure:
  Section: "Evo Scoring Result"
  Metadata:
    - Resource: <name> (<type>)
    - Local path: <local_path>
    - Total score: <total_score>/100
    - (optional) Catalog weak_dims: <weak_dims from per-entry API, if any>

  Table (one row per dimension, sorted by score ASC):
    | # | Dimension | Score | Weight | Reason |

  Section: "Dimensions with room to improve"
  List all dimensions where score < 7:
    - [#] <Dimension label>: <suggestion>

  Prompt: "Which dimensions should I improve? (all/numbers/skip)"
```

Dimension labels (bilingual map — use the language per Language Detection):

```
frontmatter_description_quality → Frontmatter 描述质量 / Frontmatter description quality
workflow_clarity                 → 工作流清晰度 / Workflow clarity
instruction_specificity          → 指令具体性 / Instruction specificity
edge_case_coverage               → 边界条件覆盖 / Edge case coverage
checkpoint_design                → 检查点设计 / Checkpoint design
resource_integration             → 资源整合度 / Resource integration
overall_architecture             → 整体架构 / Overall architecture
```

### Step 8 — User dimension selection

Parse user input:
- `all` → select every dimension with score < 7; if every dimension ≥ 7, select the three lowest-scoring ones
- comma-separated numbers (e.g. `2,4`) → the dimensions listed at those row numbers
- `skip` → go to Step 11 (persist history with `user_action: "skip"`, no content changes)
- anything else → re-prompt

### Step 9 — LLM improvement call

Dispatch an LLM improvement call with inputs:
- The full original file content
- Resource type
- List of target dimension keys (from Step 8)
- Scoring `dimensions` subset (only target dimensions' reason + suggestion)

**Improvement prompt constraints** (embed verbatim in the LLM prompt):

1. Preserve the resource's core function and purpose — only change HOW it's written, not WHAT it does
2. Preserve structure, heading hierarchy, and section order; do NOT delete unrelated content
3. Preserve the original language (Chinese or English)
4. For skill type: NEVER modify anything between opening `---` and closing `---` frontmatter delimiters
5. Improved total length is bounded by a **dynamic size cap** (computed at diff-preview time, see Step 10) — not a hard limit on the LLM; the LLM should aim for concise content, and the preview step enforces the policy with user confirmation
6. Do NOT introduce new dependencies (new scripts/references/MCP calls)
7. Only modify sections related to the target dimensions

**LLM output contract (JSON, strict)**:

```json
{
  "improved_content": "<full improved file content as a string>",
  "diff_summary": [
    {"section": "<section name>", "change": "<≤50 chars description>", "targets": ["<dim_key>", ...]}
  ]
}
```

### Step 10 — Diff preview and user confirmation

Render the diff at **section level** (not line-by-line):

```
Structure:
  Section: "Improvement Preview"
  Per diff_summary entry:
    - <Section name> [<target dim labels>]: <change description>
  Size change: <old bytes> → <new bytes> (<ratio>×)

  Dynamic size cap:
    - if original is skeleton-sized (≤ 30 lines OR ≤ 1200 bytes): cap = 3.0×
      (catalog has many auto-gen template skills where 1.5× makes improvement impossible)
    - else: cap = 1.5×
    - if ratio > cap: print ⚠️ warning + reason ("exceeds dynamic cap of <n>×"), still allow Y/n/edit

  Prompt: "Apply changes? (Y/n/edit)"
```

**If user chose Y despite size warning**: record `size_override: {original_bytes, improved_bytes, ratio, reason}` in the history.json entry (see Step 11) so future ratchet/regression tooling can distinguish "organically grew past cap" from "user-approved override".

Handle user response:
- **Y** → write `improved_content` to the local file (overwrite); record `user_action: "accept"`; go to Step 11
- **n** → leave local file unchanged; record `user_action: "skip"`; go to Step 11
- **edit** → ask for additional instructions, loop back to Step 9 with appended instructions; re-present diff

### Step 11 — Persist history

Compute content hashes:
- `content_hash_before`: SHA-256 of the local file content at the moment Step 4 (lint) ran
- `content_hash_after`: SHA-256 of the local file content after Step 10 (same as before if user skipped)

Append an entry to `~/.claude/.evo/<id>/history.json`. If the file does not exist, create it with the envelope structure below. If it exists, append the new entry to the `history` array.

```json
{
  "id": "<id>",
  "type": "skill | prompt | rule",
  "local_path": "<absolute path to the local file>",
  "history": [
    {
      "timestamp": "<ISO8601 UTC>",
      "rubric_version": "1.0",
      "content_hash_before": "<sha256>",
      "content_hash_after": "<sha256>",
      "dimensions": {
        "<dim_key>": {"score": <n>, "weight": <w>, "reason": "<s>", "suggestion": "<s>"}
      },
      "total_score": <n>,
      "user_action": "accept | skip | edit",
      "selected_dimensions": ["<dim_key>", ...],
      "diff_summary": [...]
    }
  ]
}
```

**Schema compatibility**:
- `dimensions` is a map keyed by dimension name — NOT a fixed-field record. Future dimensions (e.g. `live_test_performance`) can be added without breaking older entries.
- `rubric_version` distinguishes future rubric revisions. Current value: `"1.0"`.

### Step 12 — Report result

Print a concise summary in the active language:

```
Structure:
  Section: "Evo complete"
  - Total score before: <n>
  - Selected dimensions: <labels>
  - Changes applied: yes | no (user skipped) | no (lint failed)
  - History appended: ~/.claude/.evo/<id>/history.json
  - Next step: re-run `/everything-ai-coding:evo <id>` later to check remaining weak dimensions
```

## Error Handling

- **Network failure fetching search index**: stop with message "Cannot resolve resource type without network. Retry when connection is available."
- **LLM call fails or returns non-JSON**: print the raw output, suggest retry; do NOT write to the local file
- **Local file write permission denied**: show the permission error and the target path; do NOT append to history (nothing happened)
- **history.json corrupted (invalid JSON)**: back up to `history.json.bak.<timestamp>` and start a fresh history.json with a single entry
- **Schema version mismatch (future history.json has unknown fields)**: accept the file as-is, append the new entry; do NOT delete unknown fields — preserve forward compatibility

## Attribution

Rubric framework adapted from [darwin-skill](https://github.com/alchaincyf/darwin-skill) by 花叔 (MIT License). See `docs/wiki/evo-rubric.md` for full dimension descriptions and the acknowledgment in the project README.
