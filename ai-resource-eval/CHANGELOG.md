# Changelog

All notable changes to `ai-resource-eval` are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- `tasks/plugin.yaml` — **plugin task switched from health-only to 5-dim LLM
  scoring** (rubric_major_version 1 → 2). v1's `metrics: []` was based on the
  premise that LLM evaluation of a plugin bundle would be too coarse; that
  premise is invalidated now that `PluginContentFetcher` provides substantive
  content (`plugin.json` + all `SKILL.md` / agents / commands). Spike on 8
  representative plugins (`tools/spike_plugin_six_dim_scoring.py`) showed:
  - score spread widened from 26 → 46 (discrimination ~2× better)
  - mongodb-agent-skills moved 82 → 92 (LLM detected substance health-only
    couldn't see)
  - sickn33-antigravity-bundle (URL-collision water entry) auto-rejected at 46
  - top-cluster `[100/100/97/96]` spread to `[81/85/80/80]` (no more saturation)

  Active dims: `coding_relevance` 0.25 / `doc_completeness` 0.30 /
  `desc_accuracy` 0.15 / `writing_quality` 0.15 / `specificity` 0.15.
  `install_clarity` dropped — plugin marketplace install is a uniform
  `/plugin install <name>` flow, dim was noise (6/8 spike samples scored 1);
  its 0.10 weight redistributed to `doc_completeness` (the highest-discrimination
  dim, mongodb=5 vs sickn33=1). Blend `α = 0.85`, thresholds raised to
  `accept=65 / review=50`.

  Behavior consequences:
  - All 901 plugin entries get a fresh LLM evaluation on the next sync (rubric
    bump invalidates v1 cache).
  - Many anthropic marketplace plugins drop from artificial 100 to 80–90 range.
  - Empty/water plugins (no SKILL.md, manifest only) flow into `reject` bucket.

### Added

- `PluginContentFetcher` (`ai_resource_eval/fetcher/plugin.py`) — plugin-typed
  content fetcher used by `EvalRunner` when `entry.type == "plugin"`. Identifies
  plugin boundary via `.claude-plugin/plugin.json` (uniform across L1 marketplace
  subdir / L2 root plugin / L3 root with many SKILLs / L4 dev monorepo), pulls
  `plugin.json` + all `SKILL.md` + `agents/*.md` + `commands/*.md`, normalizes
  with `## <path>` section headers, applies a 600KB `size_cap` fallback
  (frontmatter + first 800 chars per file beyond the first 5 of each category).
  Exposes `detect_plugin_layout(repo, plugin_root, ref)` for sync-stage callers
  that only need path counts. Two instance caches:
  - `_tree_cache: dict[(repo, ref), tree_json]` — one Tree API call per
    `(repo, ref)` pair, marketplace monorepos with N plugins trigger 1 call total
  - `_raw_cache: dict[url, str|None]` — repeat fetches of the same blob URL
    serve from memory
  - `PluginLayout.fetch_error: str | None` distinguishes "no plugin.json" (legit
    fallback) from "Tree API 4xx/5xx" (transient, callers should not publish
    fallback data)
- `ContentSource.plugin_bundle` enum value (`api/types.py`).
- `tasks/plugin.yaml` — `content_source: plugin_bundle` (was `readme`); when
  the fetcher returns `None`, `EvalRunner._fetch_content` falls back to
  `GitHubFetcher` so behavior matches prior plugin evaluation.
- `tests/test_plugin_content_fetcher.py` — 15 tests covering 5 layouts, shadow
  directory exclusion (`.codex/` `.gemini/` `.github/`), tree truncation
  warning, tree+raw cache reuse, size_cap, fallback-to-None, manifest-name
  derived namespace.
- `tests/test_runner_plugin_routing.py` — 7 tests covering plugin routing +
  fallback to GitHubFetcher + non-plugin entries unchanged.
- `OpenAICompatJudge._capability_cache` — process-level (ClassVar) capability
  cache keyed by `(base_url, model)`, recording whether each endpoint accepts
  the OpenAI 2024-08 `response_format={"type":"json_schema",...}` Structured
  Outputs protocol. Cache miss defaults to `True` (request sent with
  `response_format`); the first HTTP 400 fallback writes `False`, after which
  the same `(base_url, model)` skips `response_format` directly.
- `tests/test_judge.py::TestCapabilityCache` — 8 unit tests covering first-call
  fallback / cache hit / cross-(url,model) isolation / native-200 path /
  schema=None no-op / cross-instance sharing.

### Changed

- `OpenAICompatJudge._call_llm` — now consults `_capability_cache` before
  attaching `response_format` to the payload. Public signature
  `(system_prompt, user_prompt, schema=None) -> tuple[str, int, int, int]`
  is unchanged. The existing 400→retry fallback path is retained as a cold-start
  / cache-miss / agent-proxy safety net.

### Notes for downstream consumers

- **OpenAI / Azure OpenAI** (native Structured Outputs): behavior unchanged —
  cache stays `True`, all calls keep `response_format`.
- **DeepSeek / similar `json_object`-only OpenAI-compatible backends**: per
  endpoint, the first call still observes one 400 round-trip; every subsequent
  call within the same process (across all `OpenAICompatJudge` instances)
  skips the original payload entirely. Empirical CI savings: ~15-25% of eval
  phase wall time, ~99.8% reduction in 400 responses (e.g. ~8621 → ~16 per run).
- **MiMo v2.5-pro and other "accept-but-don't-strictly-enforce-schema"
  endpoints**: cache is never written (no 400 ever observed), behavior is
  identical to prior versions.

No new environment variables, no schema migration, no `.eval_cache` rebuild.

## [0.1.0] - 2026-04-15

Initial release.
