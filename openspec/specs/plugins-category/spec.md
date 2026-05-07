# plugins-category Specification

## Purpose
TBD - created by archiving change add-plugins-category. Update Purpose after archive.
## Requirements
### Requirement: Plugin entry schema
The system SHALL recognize `"plugin"` as a valid value for the `type` field in catalog entries. Plugin entries SHALL include the following fields in addition to the standard catalog entry fields (`id`, `name`, `description`, `source_url`, `category`, `tags`, `source`, `last_synced`, `added_at`, `final_score`, `decision`):

- `marketplace_url` (string, optional): URL of the marketplace repository hosting this plugin (e.g. `https://github.com/obra/superpowers-marketplace`)
- `install` (object): SHALL contain `method: "plugin_marketplace"` (or `"npm"` for opencode-targeted plugins), `marketplace` (e.g. `"obra/superpowers-marketplace"`), and `plugin_name` (e.g. `"superpowers"`)
- `platforms` (array of strings): SHALL default to `["claude-code"]`; MAY include `"opencode"` when an npm-form plugin is detected
- `bundle` (object): SHALL contain `skills_count` (integer), `commands_count` (integer), `agents_count` (integer), `mcp_servers_count` (integer), and `skills_namespaces` (array of strings of the form `<plugin-name>:<skill-name>`)
- `manifest_completeness` (number, 0.0–1.0): SHALL reflect the completeness of the upstream `plugin.json` manifest

#### Scenario: Valid plugin entry passes JSON schema validation
- **WHEN** an entry with `type: "plugin"` containing all required fields is loaded from `catalog/plugins/index.json`
- **THEN** `python -c "import json; json.load(open('catalog/plugins/index.json'))"` SHALL succeed and `merge_index.py` SHALL accept the entry without errors

#### Scenario: Plugin entry missing bundle field is rejected
- **WHEN** a plugin entry without the `bundle` object is encountered during merge
- **THEN** `merge_index.py` SHALL log a validation warning and skip the entry from the merged catalog

#### Scenario: Plugin entry default platforms
- **WHEN** a plugin entry is created from `sync_plugins_official.py` without explicit platform information
- **THEN** the entry SHALL contain `platforms: ["claude-code"]`

### Requirement: Plugins index file location
The system SHALL maintain plugin entries in `catalog/plugins/index.json` with the same structural conventions as the existing `catalog/{mcp,skills,rules,prompts}/index.json` files. A `catalog/plugins/curated.json` file SHALL also be supported for hand-curated entries.

#### Scenario: Plugins index file exists after sync
- **WHEN** `sync_plugins_official.py` completes successfully
- **THEN** `catalog/plugins/index.json` SHALL exist as a JSON array of plugin entries

#### Scenario: Curated plugins are merged
- **WHEN** `catalog/plugins/curated.json` contains valid plugin entries and `merge_index.py` runs
- **THEN** curated entries SHALL appear in the final `catalog/index.json` with `source: "curated"` (or the value declared in the curated entry)

### Requirement: Official marketplace sync source
The system SHALL provide a Python script `scripts/sync_plugins_official.py` that fetches `marketplace.json` from `anthropics/claude-plugins-official` and `obra/superpowers-marketplace`, parses each plugin definition, and writes catalog entries to `catalog/plugins/index.json`.

#### Scenario: Successful sync of official marketplace
- **WHEN** `sync_plugins_official.py` runs with a valid `GITHUB_TOKEN`
- **THEN** all plugin entries from `anthropics/claude-plugins-official/.claude-plugin/marketplace.json` and `obra/superpowers-marketplace/.claude-plugin/marketplace.json` SHALL be present in `catalog/plugins/index.json` with `source` set to the originating marketplace identifier and `manifest_completeness` computed from the parsed manifest

#### Scenario: Marketplace JSON parse failure does not crash the script
- **WHEN** one of the upstream marketplace.json files is malformed or unreachable
- **THEN** the script SHALL log an ERROR for that source, continue processing other sources, and exit with a non-zero status only if zero plugins were synced overall

### Requirement: Community registry sync source
The system SHALL provide a Python script `scripts/sync_plugins_dev.py` that calls the `claude-plugins.dev` API (`GET /api/search?limit=200&offset=N`) iteratively and writes filtered plugin entries to `catalog/plugins/index.json`. Entries with `stars < 5` SHALL be excluded.

#### Scenario: Pagination across registry results
- **WHEN** `sync_plugins_dev.py` is executed and the registry returns 850 plugins above the star threshold
- **THEN** the script SHALL paginate through `offset=0,200,400,600,800` and produce 850 entries in `catalog/plugins/index.json` (merged with prior official-marketplace entries via dedup by `source_url`)

#### Scenario: Star threshold filter
- **WHEN** the registry returns a plugin with `stars: 3`
- **THEN** the entry SHALL NOT appear in the produced `catalog/plugins/index.json`

### Requirement: Health-only evaluation for plugins
The system SHALL register a `plugin` task config in the `ai-resource-eval` package with `llm_dimensions: []`, `health_dimensions: ["freshness", "popularity", "source_trust", "manifest_completeness"]`, weights `{freshness: 0.30, popularity: 0.30, source_trust: 0.30, manifest_completeness: 0.10}`, `enrichment: true`, `accept_threshold: 60`, and `review_threshold: 40`.

The plugin task config's `content_source` SHALL be `plugin_bundle` (not `readme`). When a plugin entry passes through the evaluation pipeline, the runner SHALL route it to `PluginContentFetcher` (see capability `plugin-content-fetcher`) instead of the default `GitHubFetcher`. The fetcher returns concatenated content from `.claude-plugin/plugin.json` + all `SKILL.md` + `agents/*.md` + `commands/*.md` files belonging to the plugin, normalized with `## <path>` section headers and a `size_cap` fallback for outliers exceeding 600,000 bytes.

When the plugin's `source_url` resolves to a sub-path that lacks `.claude-plugin/plugin.json` (edge case: marketplace entry referencing a plugin shell with only README), the fetcher SHALL return `is_plugin=False` and the runner SHALL fall back to `GitHubFetcher` retrieving the README. Evaluation continues with whatever content is available.

#### Scenario: Plugin entry receives health-only score
- **WHEN** a plugin entry passes through the evaluation pipeline
- **THEN** the resulting entry SHALL contain `final_score = health_score` (no LLM-dimension contribution), `_prior_evaluation.coding_relevance` SHALL be absent or zero, and `summary` / `summary_zh` / `tags` / `highlights` SHALL be populated from the enrichment LLM call

#### Scenario: Plugin enrichment uses substantive plugin content
- **WHEN** the plugin entry's `source_url` points to a directory containing `.claude-plugin/plugin.json` (any of the L1/L2/L3/L4 layouts)
- **THEN** the LLM enrichment input SHALL include the plugin's `plugin.json`, all `SKILL.md` files under `skills/<name>/`, all `agents/*.md`, and all `commands/*.md` (subject to size_cap)
- **AND THEN** the enrichment output (`description` / `description_zh` / `tags` / `highlights` / `tech_stack`) SHALL reflect the plugin's actual capabilities rather than only its top-level README packaging

#### Scenario: Plugin without `.claude-plugin/plugin.json` falls back to README
- **WHEN** the plugin entry's `source_url` points to a directory that has no `.claude-plugin/plugin.json` (e.g., legacy plugin shell with only LICENSE and README)
- **THEN** the system SHALL fall back to retrieving `README.md` via `GitHubFetcher`
- **AND THEN** evaluation SHALL proceed with whatever content is available, without erroring out

#### Scenario: Manifest completeness signal computation
- **WHEN** a plugin manifest contains `name`, `version`, `description`, and `author` fields
- **THEN** `manifest_completeness` SHALL be 1.0
- **AND WHEN** the manifest is missing one of `version` or `description`
- **THEN** `manifest_completeness` SHALL be 0.7
- **AND WHEN** no manifest is available (marketplace entry references a raw git URL)
- **THEN** `manifest_completeness` SHALL be 0.3

### Requirement: CI integration for plugin sync
The CI workflow `.github/workflows/sync.yml` SHALL execute `sync_plugins_official.py` and `sync_plugins_dev.py` after the existing skill / mcp / rule / prompt sync steps and before `verify_sync` and `merge_index`.

#### Scenario: Weekly CI run includes plugin sync
- **WHEN** the weekly cron triggers the sync workflow
- **THEN** the job log SHALL contain the steps `sync_plugins_official` and `sync_plugins_dev` executed in that order, and `catalog/plugins/index.json` SHALL be updated in the resulting commit

#### Scenario: Plugin sync caches persist weekly
- **WHEN** CI runs the workflow
- **THEN** independent weekly cache blocks `.plugins_official_cache/` and `.plugins_dev_cache/` SHALL be restored using restore-keys anchored only to the current ISO week stamp (no cross-week fallback)

### Requirement: README and frontend reflect plugins category
`update_readme.py` SHALL include a `plugins` count in both `README.md` and `README.zh-CN.md` statistics. `build_frontend_data.py` SHALL include `plugin` in the per-type counts within `stats.json` and produce a `plugins.json` file in the frontend API output directory.

#### Scenario: README statistics include plugins count
- **WHEN** `update_readme.py` runs after `merge_index.py`
- **THEN** both `README.md` and `README.zh-CN.md` SHALL contain a "Plugins" / "插件" badge or stats line whose number matches the count of `type: "plugin"` entries in `catalog/index.json`

#### Scenario: Multi-platform compatibility note
- **WHEN** `update_readme.py` renders the plugins section
- **THEN** the rendered README SHALL contain a sentence noting that plugins primarily target Claude Code, with partial opencode (npm) compatibility, and that cursor / windsurf / costrict platforms have no equivalent mechanism

### Requirement: Evo command excludes plugins
The `/eac:evo` command SHALL reject plugin-type entries with a clear error message directing users to file changes upstream.

#### Scenario: Evo on plugin entry returns error
- **WHEN** a user runs `/eac:evo <id>` where the catalog entry has `type: "plugin"`
- **THEN** the command SHALL exit with a message stating "evo does not support plugin entries; please file changes via the upstream marketplace" and SHALL NOT modify any local files

