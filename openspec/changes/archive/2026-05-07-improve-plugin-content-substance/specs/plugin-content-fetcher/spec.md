## ADDED Requirements

### Requirement: Plugin content fetcher SHALL identify plugin boundary by `.claude-plugin/plugin.json`

The system SHALL provide a `PluginContentFetcher` class that, given a GitHub repo URL and optional sub-path, identifies the plugin boundary by locating the directory containing `.claude-plugin/plugin.json`. This rule SHALL apply uniformly across multiple plugin repository layouts:

- **L1**: marketplace monorepo with `plugins/<name>/` subdirectories (e.g., `anthropics/claude-plugins-official/plugins/frontend-design/`)
- **L2**: single plugin occupying entire repository with root-level `.claude-plugin/plugin.json` (e.g., `mongodb/agent-skills`)
- **L3**: single plugin bundling many internal SKILL.md files (e.g., `obra/superpowers`)
- **L4**: dev marketplace monorepo with arbitrary subdirectory naming (e.g., `trailofbits/skills/plugins/<name>/`, `alirezarezvani/claude-skills/business-growth/`)

#### Scenario: Marketplace subdir layout (L1)

- **WHEN** the fetcher is asked for plugin at `anthropics/claude-plugins-official` with sub-path `plugins/frontend-design`
- **THEN** the fetcher SHALL identify `plugins/frontend-design` as the plugin root
- **AND THEN** files matching `plugins/frontend-design/.claude-plugin/plugin.json`, `plugins/frontend-design/skills/<*>/SKILL.md`, `plugins/frontend-design/agents/*.md`, `plugins/frontend-design/commands/*.md` SHALL be associated with this plugin

#### Scenario: Root-level plugin layout (L2/L3)

- **WHEN** the fetcher is asked for plugin at `mongodb/agent-skills` with empty sub-path
- **THEN** the fetcher SHALL identify the repository root as the plugin root
- **AND THEN** files matching `.claude-plugin/plugin.json`, `skills/<*>/SKILL.md` SHALL be associated with this plugin

#### Scenario: Sub-path without plugin.json triggers fallback

- **WHEN** the fetcher is asked for plugin at a sub-path that has no `.claude-plugin/plugin.json` (e.g., `clangd-lsp` plugin which only has README.md)
- **THEN** the fetcher SHALL return `is_plugin=False` with empty file paths
- **AND THEN** the runner SHALL fall back to the existing `GitHubFetcher` to retrieve the README

### Requirement: Plugin content fetcher SHALL filter platform-specific shadow directories

The fetcher SHALL exclude any file path containing a `.`-prefixed directory segment from the plugin's content set, except `.claude-plugin/plugin.json` itself which is the plugin marker. This excludes `.codex/skills/...` (codex-specific), `.gemini/skills/...` (gemini-specific), `.github/...` (CI configs), and similar non-Claude content.

#### Scenario: Codex shadow directory excluded

- **WHEN** the source tree contains both `plugins/foo/skills/x/SKILL.md` and `.codex/skills/y/SKILL.md`
- **THEN** the fetcher SHALL include only `plugins/foo/skills/x/SKILL.md` in the plugin's skill paths

#### Scenario: Gemini shadow directory excluded

- **WHEN** a repository like `alirezarezvani/claude-skills` contains `.gemini/skills/...` mixed with real plugin content
- **THEN** the fetcher SHALL exclude all `.gemini/skills/...` files from the plugin's content set

### Requirement: Plugin content fetcher SHALL classify files into skill / agent / command buckets

For each file under a plugin root (after shadow-directory filtering), the fetcher SHALL classify by path segments:

- **Skill**: file ending in `SKILL.md` AND has `skills` segment in its relative path
- **Agent**: file ending in `.md` AND has `agents` segment in its relative path
- **Command**: file ending in `.md` AND has `commands` segment in its relative path

#### Scenario: SKILL.md detection in nested skills/ subdirectory

- **WHEN** a file path is `plugins/foo/skills/bar/SKILL.md`
- **THEN** the fetcher SHALL classify it as a skill file
- **AND THEN** the file SHALL appear in `bundle.skills_namespaces` as `foo:bar`

#### Scenario: SKILL.md detection in deep nested subdirectory

- **WHEN** a file path is `skills/writing-skills/anthropic-best-practices.md` (a non-SKILL.md inside skills/)
- **THEN** the fetcher SHALL NOT classify it as a primary skill file (does not end in `SKILL.md`)
- **AND THEN** but it MAY be included in normalized content under the parent skill's section if size_cap allows

### Requirement: Plugin content fetcher SHALL normalize content with size_cap fallback

The fetcher SHALL produce a single concatenated string from `plugin.json`, all `SKILL.md`, `agents/*.md`, and `commands/*.md` files belonging to the plugin, with each file prefixed by `## <path>` markdown heading. Files SHALL be ordered alphabetically by path. When the running concatenation exceeds `size_cap` (default 600,000 bytes ≈ 150k tokens ≈ 15% of MiMo 1M context), the fetcher SHALL include the first 5 files of each category in full, and for remaining files SHALL include only the YAML frontmatter (if present) plus the first 800 characters.

#### Scenario: Small plugin produces full concatenation

- **WHEN** a plugin has total content ≤ 600,000 bytes (e.g., `obra/superpowers` at 248KB)
- **THEN** the fetcher SHALL include every `SKILL.md`, agent, command in full

#### Scenario: Large plugin triggers size_cap fallback

- **WHEN** a plugin has total raw content > 600,000 bytes (e.g., `affaan-m/everything-claude-code` at 3.2MB)
- **THEN** the fetcher SHALL include the first 5 SKILL.md files, first 5 agents, first 5 commands in full
- **AND THEN** remaining files SHALL be represented by their frontmatter description + first 800 characters
- **AND THEN** the final normalized content size SHALL be < 1,000,000 bytes

### Requirement: Plugin content fetcher SHALL cache GitHub Tree API responses by `(repo, ref)`

The fetcher SHALL maintain an in-memory cache mapping `(repo, ref)` → tree JSON, populated on the first GitHub Tree API recursive call for that repo. Subsequent plugin lookups in the same repo within the same process SHALL reuse the cached tree without re-calling the API. This is critical for marketplace monorepos where 50+ plugins share a single repo (e.g., `anthropics/claude-plugins-official`).

#### Scenario: Same marketplace repo with multiple plugins reuses one tree call

- **WHEN** the fetcher is asked for 50 plugins all under `anthropics/claude-plugins-official` in the same process
- **THEN** the GitHub Tree API endpoint `/repos/anthropics/claude-plugins-official/git/trees/HEAD?recursive=1` SHALL be called at most once
- **AND THEN** all 50 plugins SHALL be resolved from the cached tree

### Requirement: Plugin content fetcher SHALL cache raw file content by URL

The fetcher SHALL maintain an in-memory cache mapping each fully-qualified `raw.githubusercontent.com` URL to its content (or `None` for 404). Repeat calls within the same process SHALL serve from cache.

#### Scenario: Repeat fetch of same plugin.json hits cache

- **WHEN** two evaluations within the same process target the same plugin (re-evaluation, retry)
- **THEN** the second call SHALL serve `plugin.json` content from cache without HTTP

### Requirement: Runner SHALL route plugin entries to `PluginContentFetcher`

`EvalRunner._fetch_content` SHALL inspect the entry's `type` field. When `entry.type == "plugin"`, the runner SHALL invoke `PluginContentFetcher.fetch(entry.source_url)`. For all other types, the runner SHALL keep the existing `GitHubFetcher` path unchanged.

#### Scenario: Plugin entry routed to PluginContentFetcher

- **WHEN** the runner processes an entry with `type == "plugin"` and `source_url == "https://github.com/anthropics/claude-plugins-official/tree/main/plugins/frontend-design"`
- **THEN** the runner SHALL call `PluginContentFetcher.fetch(...)` with that URL
- **AND THEN** the runner SHALL NOT call `GitHubFetcher.fetch(...)` for this entry

#### Scenario: Non-plugin entry uses existing GitHubFetcher

- **WHEN** the runner processes an entry with `type == "skill"` (or `mcp`/`rule`/`prompt`)
- **THEN** the runner SHALL call `GitHubFetcher.fetch(...)` as before
- **AND THEN** the routing SHALL NOT introduce any latency on the existing path
