---
description: 'Recommend coding resources based on current project stack. Usage: /eac-recommend [type:mcp|skill|rule|prompt]'
argument-hint: type filter
---

# Everything AI Coding - Recommend

$ARGUMENTS

---

## Language Detection

Determine the output language using the following priority chain (first match wins):

1. **Explicit parameter**: if `$ARGUMENTS` contains `lang:zh` or `lang:en`, use that (strip it from arguments)
2. **Conversation signal**: if the user's recent messages are clearly in one language, follow that
3. **System locale fallback**: run `echo $LANG` in Bash — if the value starts with `zh` (e.g. `zh_CN.UTF-8`), use Chinese; otherwise use English

Once determined, apply consistently:
- **All output** (section titles, table headers, labels, helper text) MUST be in the detected language.
- For the Description column in tables: use `description_zh` for Chinese, `description` for English.
- For candidate detail text (why-it-fits, basis): generate in the detected language.
- Command references (e.g. `/eac-install <id>`) stay as-is regardless of language.

## Data Sources

**Note**: Apply GitHub Network Detection rules (see SKILL.md) to all GitHub URLs below. If `[network-config]` specifies a proxy, rewrite URLs accordingly.

Search index URL: `https://zgsm-ai.github.io/everything-ai-coding/api/v1/search-index.json`
Fallback URL: `https://raw.githubusercontent.com/zgsm-ai/everything-ai-coding/main/catalog/search-index.json`
Per-entry API: `https://zgsm-ai.github.io/everything-ai-coding/api/v1/{type}/{id}.json`
Full index fallback: `https://raw.githubusercontent.com/zgsm-ai/everything-ai-coding/main/catalog/index.json`

## Execution Flow

1. Extract optional type filter from `$ARGUMENTS`
   - Supports `type:mcp`, `type:skill`, `type:rule`, `type:prompt` filters
   - Example: `/eac-recommend type:mcp` — recommend MCP type only
   - If `type:<value>` is present, extract it as a filter
2. Analyze current project tech stack:
   - Read `package.json` → extract framework names from dependencies (react, next, vue, express, etc.)
   - Read `requirements.txt` / `pyproject.toml` → extract Python packages
   - Read `go.mod` → extract Go modules
   - Read `Cargo.toml` → extract Rust crates
   - Read `Gemfile` → extract Ruby gems
   - Check file extensions: `.tsx`→react, `.vue`→vue, `.py`→python, `.go`→go, `.rs`→rust, `.swift`→swift, `.kt`→kotlin
   - Check config files: `Dockerfile`→docker, `.github/workflows/`→ci-cd, `tsconfig.json`→typescript
3. Generate lightweight recommendation keywords from detected stack:
   - Retain detected tech stack tags
   - Compress "framework + task" into index-friendly short terms, e.g. `react performance`, `fastapi docs`, `docker ci-cd`
   - If user provided extra context (e.g. skill-only or mcp-only), preserve that constraint — do not overwrite with rewrites
   - **Default preference rule**: unless user explicitly specifies `type:mcp`, prioritize `skill`, `rule`, `prompt` that directly serve project implementation/constraints/workflow; only include MCP entries when one is clearly the core workflow tool for the scenario
4. Download index to temp file: `curl -sf --compressed <index URL> -o "$TMPDIR/everything-ai-coding-index.json"`, on failure try Fallback URL, then local fallback
5. Pre-filter with Python (cross-platform: use `$(command -v python3 || command -v python)`):
   - Load JSON file
   - Match detected project tags against each entry's `tags` + `tech_stack`, supplement with lightweight recommendation keyword matching (prefer `search_text` when available)
   - If type filter specified, filter by `type` field first
   - Score each entry by the lexicographic descending key `(matched_tags, freshness_label != "abandoned", final_score, stars)` — `matched_tags` (number of distinct project tags/keywords hit) is the primary relevance signal; within equal relevance, non-abandoned entries outrank abandoned ones (sorting `True > False`); within the same relevance + freshness tier, `final_score` breaks ties ahead of `stars`. Treat missing `freshness_label` as not-abandoned and missing `final_score` as `0`. Do NOT drop abandoned entries here — the gate in step 7 handles them, and they may still surface in "Other Matches".
   - Keep `freshness_label` in the TSV so step 6 can apply the freshness preference and step 8 can render the stale warning: emit `id\ttype\tmatched_tags\tstars\tfinal_score\tdecision\tfreshness_label\tinstall_method\tsource_url\tdescription\tdescription_zh` (output top 15)
6. From shortlist, select top 3-5 candidates and fetch per-entry API for verification:
   - **Freshness preference**: when two candidates are similarly relevant (same `matched_tags` count and comparable project fit), PREFER entries with `freshness_label != "abandoned"`. Abandoned entries can still appear in "Other Matches" but should NOT occupy verification slots unless no active/stale alternative matches the project at all. If the shortlist genuinely has no active/stale matches, it is acceptable to verify abandoned candidates and note the staleness in the output.
   - Prefer `source`, `evaluation`, `health`, `install`, `source_url`, `tags`, `highlights`, `weak_dims`, `freshness_label`
   - Combine with current project stack to judge "does this truly fit the current project" — not just coincidental tag matches
7. **Candidate Verification Gate (mandatory)**
   - NEVER label all matches as "recommendations" based solely on tag overlap or stars
   - A candidate enters the "Top Candidates" section ONLY when ALL of the following hold:
     1. `final_score >= 70`, AND
     2. `freshness_label != "abandoned"`, AND
     3. at least one tag / keyword / `search_text` hit.
   - Entries failing (1) or (2) are routed to "Other Matches" — they MUST NOT appear in "Top Candidates".
   - The numeric floor (≥70) decouples the gate from the rubric's `accept`/`review` symbol; a strong `review` entry can still reach Top Candidates on score alone. Treat missing `final_score` as `0` (i.e. not eligible).
   - If no candidate passes the gate, output "project matches" or "worth checking" — never force the label "recommendation".
   - **Type bias correction**: without `type:mcp` constraint, do not let MCP entries dominate over more project-relevant skill/prompt/rule just because MCP has stronger official/install signals
   - **Sparse hit rule (especially `type:mcp`)**: if the current stack has no obvious specialized candidates, prefer "2 strong matches + explicit thin-coverage note" over padding the list with edge-case entries
8. Format results as "Top Candidates + Other Matches" two-tier output, with these constraints:
   - Top Candidates: default 2-3 items, unless results are very close and hard to distinguish
   - Other Matches: default 2-4 supplementary items, do not expand into a long list
   - NEVER expose raw scoring fields or internal sort fields in the main response — translate into brief user-understandable rationale
   - NEVER repeat install commands under each entry — consolidate install actions into a final "suggested install" section
   - **Rationale**: for each Top Candidate, derive the "why it fits" rationale from `highlights[0:2]` joined with `"; "`. If `highlights` is empty/missing, fall back to `description` (or `description_zh` in Chinese mode).
   - **Weak-dimension warnings**: when a Top Candidate has a non-empty `weak_dims` array, append one `⚠️` line per weak dimension using the active-language label. Bilingual label map:

     ```
     coding_relevance → 编码相关度 / coding relevance
     doc_completeness → 文档完整度 / doc completeness
     desc_accuracy    → 描述准确度 / description accuracy
     writing_quality  → 文档写作质量 / writing quality
     specificity      → 针对性 / specificity
     install_clarity  → 安装步骤清晰度 / install clarity
     ```

     Unknown-dimension fallback: if `weak_dims` contains a name not in the map (e.g. future rubric version), render the raw dimension name as the label — do not error or drop it.
   - **Stale freshness warning**: when a Top Candidate has `freshness_label == "stale"`, append a `⚠️` line — Chinese mode `⚠️ 半年未更新`, English mode `⚠️ half a year without update`. No warning when `freshness_label == "active"`; `"abandoned"` entries are already excluded by the gate.

## Output Structure

Output the following structure in the user's conversation language. The labels below are structural identifiers — translate them naturally.

```
Section: "Project Recommendations"

Line: "Detected stack: {stack list}"
Line: "Recommendation keywords: {keywords}"

Section: "Top Candidates"
  (Only show gate-verified candidates. If none pass: "No high-confidence candidates yet")
  Per item:
    - ID (Type)
    - Why it fits the current project: direct relationship with project stack or default scenario
    - Why worth checking: brief rationale (official source / clear install / best stack fit)

Section: "Other Matches" (table)
  Columns: # | ID | Type | Matched Tags | Stars | Install Method | Description
  (Use description_zh for Chinese users, description for others)
```

9. Footer prompt:
   - If top candidates exist: suggest installing the top one, e.g. "To get started, try `/eac-install <id>`"
   - If no high-confidence candidates: explain that matches were found but none pass the confidence gate, suggest refining type/scenario or browsing candidates
