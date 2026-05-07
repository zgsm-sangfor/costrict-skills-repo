# Changelog

All notable changes to `ai-resource-eval` are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

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
