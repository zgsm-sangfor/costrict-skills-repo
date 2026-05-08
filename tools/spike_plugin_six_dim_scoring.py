#!/usr/bin/env python3
"""Spike: try giving plugin entries the 6-dim LLM scoring path.

Loads ``plugin.yaml`` task config from disk, then constructs a *modified* in-memory
TaskConfig that turns the 6 LLM dimensions back on (skill-style weights + 0.85
LLM/health blend), keeps content_source=plugin_bundle so PluginContentFetcher
fires, and runs EvalRunner on a small representative sample with the real LLM.

Output: side-by-side comparison of current health-only scores vs proposed 6-dim
scores. We're checking whether 6-dim adds discrimination.

Usage:
    GH_TOKEN=$(gh auth token) python3 tools/spike_plugin_six_dim_scoring.py
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "ai-resource-eval"))

env_file = REPO_ROOT / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

logging.basicConfig(level=logging.WARNING)

from ai_resource_eval.api.types import (  # noqa: E402
    EvalItem,
    HeuristicSignalWeight,
    MetricWeight,
    StarRoutingConfig,
    TaskConfig,
    ThresholdsConfig,
)
from ai_resource_eval.judges.openai_compat import OpenAICompatJudge  # noqa: E402
from ai_resource_eval.runner import EvalRunner  # noqa: E402


# 8 representative plugin samples spanning bundle size, source, layout
SAMPLES = [
    # Big bundle, official source, score 100 today
    {"id": "anthropic-superpowers", "name": "superpowers", "type": "plugin",
     "source": "claude-plugins-official", "source_priority": 1000,
     "source_url": "https://github.com/obra/superpowers.git",
     "description": "TDD/debugging/brainstorming skills bundle for Claude Code.",
     "stars": 181632, "category": "engineering", "version": "1.0.0",
     "manifest_completeness": 0.7,
     "_today_score": 97},
    # LSP plugin — ZERO bundle, but currently 100
    {"id": "anthropic-clangd-lsp", "name": "clangd-lsp", "type": "plugin",
     "source": "claude-plugins-official", "source_priority": 1000,
     "source_url": "https://github.com/anthropics/claude-plugins-official/tree/main/plugins/clangd-lsp",
     "description": "C/C++ language server (clangd) for code intelligence.",
     "stars": 18763, "category": "tooling", "version": "1.0.0",
     "manifest_completeness": 1.0,
     "_today_score": 100},
    # MongoDB — root plugin with 7 SKILLs, official-like
    {"id": "anthropic-mongodb", "name": "mongodb", "type": "plugin",
     "source": "claude-plugins-official", "source_priority": 1000,
     "source_url": "https://github.com/mongodb/agent-skills.git",
     "description": "MongoDB Atlas + driver agent skills.",
     "stars": 200, "category": "database", "version": "1.0.0",
     "manifest_completeness": 1.0,
     "_today_score": 82},
    # Single-skill plugin
    {"id": "anthropic-frontend-design", "name": "frontend-design", "type": "plugin",
     "source": "claude-plugins-official", "source_priority": 1000,
     "source_url": "https://github.com/anthropics/claude-plugins-official/tree/main/plugins/frontend-design",
     "description": "Frontend design plugin — production-grade UI aesthetics.",
     "stars": 18763, "category": "frontend", "version": "1.0.0",
     "manifest_completeness": 1.0,
     "_today_score": 96},
    # 1-agent plugin (currently 100, no skills)
    {"id": "anthropic-code-simplifier", "name": "code-simplifier", "type": "plugin",
     "source": "claude-plugins-official", "source_priority": 1000,
     "source_url": "https://github.com/anthropics/claude-plugins-official/tree/main/plugins/code-simplifier",
     "description": "Auto-simplify recently modified code.",
     "stars": 18763, "category": "ai-ml", "version": "1.0.0",
     "manifest_completeness": 1.0,
     "_today_score": 100},
    # Dev source — sickn33 antigravity bundle (URL collision with 36 others)
    {"id": "sickn33-antigravity-awesome-skills-antigravity-bundle-essentials",
     "name": "antigravity-bundle-essentials", "type": "plugin",
     "source": "claude-plugins-dev", "source_priority": 700,
     "source_url": "https://github.com/sickn33/antigravity-awesome-skills",
     "description": "Antigravity essentials bundle.",
     "stars": 50, "category": "ai-ml", "version": "1.0.0",
     "manifest_completeness": 0.7,
     "_today_score": 74},
    # Community marketplace
    {"id": "obra-superpowers-chrome", "name": "superpowers-chrome", "type": "plugin",
     "source": "superpowers-marketplace", "source_priority": 950,
     "source_url": "https://github.com/obra/superpowers-chrome.git",
     "description": "Chrome browser automation skill bundle.",
     "stars": 30, "category": "tooling", "version": "1.0.0",
     "manifest_completeness": 0.7,
     "_today_score": 84},
    # Trail of bits c-review (4 agents)
    {"id": "trailofbits-c-review", "name": "c-review", "type": "plugin",
     "source": "claude-plugins-dev", "source_priority": 700,
     "source_url": "https://github.com/trailofbits/skills/tree/main/plugins/c-review",
     "description": "C code review judges plugin.",
     "stars": 280, "category": "security", "version": "1.0.0",
     "manifest_completeness": 1.0,
     "_today_score": 75},
]


def make_six_dim_plugin_config() -> TaskConfig:
    """In-memory TaskConfig: plugin content + 6-dim metrics + 0.85 LLM blend."""
    return TaskConfig(
        task="plugin_6dim_spike",
        content_source="plugin_bundle",
        content_paths=["README.md", ".claude-plugin/plugin.json"],
        content_fallback="description",
        metrics=[
            MetricWeight(metric="coding_relevance", weight=0.25),
            MetricWeight(metric="doc_completeness", weight=0.20),
            MetricWeight(metric="desc_accuracy", weight=0.15),
            MetricWeight(metric="writing_quality", weight=0.15),
            MetricWeight(metric="specificity", weight=0.15),
            MetricWeight(metric="install_clarity", weight=0.10),
        ],
        heuristic_signals=[
            HeuristicSignalWeight(signal="freshness", weight=0.30),
            HeuristicSignalWeight(signal="popularity", weight=0.30),
            HeuristicSignalWeight(signal="source_trust", weight=0.30),
            HeuristicSignalWeight(signal="manifest_completeness", weight=0.10),
        ],
        star_routing=StarRoutingConfig(zero_weight_sources=[], monorepo_threshold=5),
        thresholds=ThresholdsConfig(accept=65, review=50),
        rubric_major_version=99,  # spike — never collide with prod cache
        enrichment=True,
        health_blend_alpha=0.85,  # 85% LLM, 15% health (skill-style)
    )


def main() -> int:
    api_key = os.environ.get("LLM_API_KEY", "").strip()
    base_url = os.environ.get("LLM_BASE_URL", "").strip()
    model = os.environ.get("LLM_MODEL", "").strip()
    if not (api_key and base_url and model):
        print("Missing LLM_API_KEY / LLM_BASE_URL / LLM_MODEL — abort")
        return 1

    judge = OpenAICompatJudge(base_url=base_url, api_key=api_key, model=model)
    task_config = make_six_dim_plugin_config()
    runner = EvalRunner(
        task_config=task_config,
        judge=judge,
        cache_dir=str(REPO_ROOT / ".eval_cache_plugin_6dim_spike"),
        concurrency=2,
        incremental=False,
        interactive=False,
        on_fail="queue",
    )

    items = [EvalItem(**{k: v for k, v in s.items() if not k.startswith("_")}) for s in SAMPLES]
    print(f"Running 6-dim eval on {len(items)} plugin samples ...")
    print(f"Endpoint: {base_url} model={model}")
    print()

    results = runner.run(items)

    # Build comparison
    rows = []
    for s, r in zip(SAMPLES, results):
        rd = r.model_dump(mode="json")
        # metrics is a dict: {"coding_relevance": {"score": 5, "evidence": [...]}, ...}
        raw_metrics = rd.get("metrics") or {}
        if isinstance(raw_metrics, dict):
            metrics_dict = {k: (v.get("score") if isinstance(v, dict) else v) for k, v in raw_metrics.items()}
            metrics_full = raw_metrics
        else:
            # fallback for list shape
            metrics_dict = {m.get("name", m.get("metric", "?")): m.get("score") for m in raw_metrics}
            metrics_full = {}
        rows.append({
            "id": s["id"],
            "today_score": s["_today_score"],
            "new_final": rd.get("final_score"),
            "new_llm": rd.get("llm_score"),
            "new_health": (rd.get("health") or {}).get("score"),
            "decision": rd.get("decision"),
            "metrics": metrics_dict,
            "metrics_full": metrics_full,
        })

    # Print table
    print()
    print(f"{'ID':55s} {'Today':>6s} {'New':>6s} {'LLM':>6s} {'Health':>7s} {'Decision':>10s} {'Dims (CR/DC/DA/WQ/SP/IC)':>30s}")
    print("─" * 130)
    for row in rows:
        m = row["metrics"]
        dims = "/".join(str(int(m.get(k, 0))) for k in ["coding_relevance", "doc_completeness", "desc_accuracy", "writing_quality", "specificity", "install_clarity"])
        print(f"{row['id']:55s} {row['today_score']:>6} {round(row['new_final'] or 0):>6} {round(row['new_llm'] or 0):>6} {round(row['new_health'] or 0):>7} {row['decision']:>10s} {dims:>30s}")

    print()
    today_scores = [r["today_score"] for r in rows]
    new_scores = [r["new_final"] for r in rows if r["new_final"] is not None]
    print(f"Today score range: {min(today_scores)}..{max(today_scores)} (spread {max(today_scores)-min(today_scores)})")
    print(f"New   score range: {min(new_scores):.0f}..{max(new_scores):.0f} (spread {max(new_scores)-min(new_scores):.0f})")
    print(f"=> Discrimination delta: {(max(new_scores)-min(new_scores)) - (max(today_scores)-min(today_scores)):+.0f}")

    out_path = REPO_ROOT / "tools" / "spike_plugin_six_dim_scoring_output.json"
    out_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2))
    print(f"\nFull output: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
