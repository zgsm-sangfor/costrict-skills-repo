## MODIFIED Requirements

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
