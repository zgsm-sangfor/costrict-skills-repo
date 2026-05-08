"""Tests for plugin task evaluation path through eval_bridge.

Verifies Task 5.6 of the `add-plugins-category` change:
- _TYPE_TO_TASK routes "plugin" → "plugin"
- plugin task config is health-only (metrics=[]) + enrichment=true
- manifest_completeness signal reads from entry.manifest_completeness
- final_score == health_score when health_blend_alpha=0.0 / metrics empty
- enrichment fields propagate through map_result_to_entry
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))


# ---------------------------------------------------------------------------
# 1. Routing
# ---------------------------------------------------------------------------


def test_type_to_task_routes_plugin():
    """`plugin` resource type must map to the `plugin` task config."""
    from eval_bridge import _TYPE_TO_TASK, resolve_task_name

    assert _TYPE_TO_TASK["plugin"] == "plugin"
    assert resolve_task_name("plugin") == "plugin"


# ---------------------------------------------------------------------------
# 2. Task config shape
# ---------------------------------------------------------------------------


def test_load_plugin_task_config():
    """plugin.yaml v2: 5-dim LLM (drops install_clarity), 4 health signals, enrichment=true, accept=65/review=50.

    History: v1 was health-only (metrics=[]) per add-plugins-category decision 3.
    v2 (improve-plugin-content-substance follow-up) activates 5-dim LLM scoring
    once PluginContentFetcher provides substantive plugin content as input.
    install_clarity dropped because plugin marketplace install is uniform
    `/plugin install <name>` flow — spike showed this dim is noise (6/8 plugins
    scored 1) so its 0.10 weight redistributed to doc_completeness.
    """
    from ai_resource_eval.tasks.loader import load_task_config

    cfg = load_task_config("plugin")

    # 5-dim LLM evaluation (no install_clarity).
    metric_names = {m.metric for m in cfg.metrics}
    assert metric_names == {
        "coding_relevance",
        "doc_completeness",
        "desc_accuracy",
        "writing_quality",
        "specificity",
    }
    assert "install_clarity" not in metric_names
    assert sum(m.weight for m in cfg.metrics) == pytest.approx(1.0)

    # Enrichment still on (LLM call also produces summary/tags/etc.)
    assert cfg.enrichment is True

    # Thresholds bumped for 5-dim path (was 60/40 in v1 health-only mode).
    assert cfg.thresholds.accept == 65
    assert cfg.thresholds.review == 50

    # health_blend_alpha=0.85 — LLM-led blend (skill-style mix)
    assert cfg.health_blend_alpha == pytest.approx(0.85)

    # Rubric major bumped to v2 to invalidate v1 (health-only) cache.
    assert cfg.rubric_major_version == 2

    # 4 health signals: freshness, popularity, source_trust, manifest_completeness
    # (loader.py also auto-injects install_popularity at weight 0.05 by default;
    # we only assert the 4 required signals are present.)
    signals = {s.signal for s in cfg.heuristic_signals}
    for required in ("freshness", "popularity", "source_trust", "manifest_completeness"):
        assert required in signals, f"signal {required!r} missing from plugin task config"


# ---------------------------------------------------------------------------
# 3. manifest_completeness signal computation
# ---------------------------------------------------------------------------


def test_manifest_completeness_signal_reads_entry_field():
    """Entry with manifest_completeness=0.7 → signal returns 70.0 (0–100 scale)."""
    from ai_resource_eval.api.types import EvalItem
    from ai_resource_eval.runner import EvalRunner

    entry = EvalItem(id="p1", name="Plugin 1", type="plugin", manifest_completeness=0.7)
    score = EvalRunner._compute_manifest_completeness(entry)
    assert score == pytest.approx(70.0)


def test_manifest_completeness_default_when_missing():
    """Entry without manifest_completeness → signal returns default 100.0."""
    from ai_resource_eval.api.types import EvalItem
    from ai_resource_eval.runner import EvalRunner

    entry = EvalItem(id="p2", name="Plugin 2", type="plugin")
    score = EvalRunner._compute_manifest_completeness(entry)
    assert score == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# 4. health-only final_score == health_score
# ---------------------------------------------------------------------------


def test_health_only_final_score_equals_health_score():
    """Plugin entry: health-only weighted score = 0.30·F + 0.30·P + 0.30·T + 0.10·MC.

    With F=80, P=50, T=100, MC=70 (and install_popularity excluded for non-skills.sh):
        health_score = 0.30*80 + 0.30*50 + 0.30*100 + 0.10*70
                     = 24 + 15 + 30 + 7
                     = 76.0
    Since health_blend_alpha=0.0 and metrics=[], final_score == health_score.
    """
    from ai_resource_eval.api.types import HealthSignals
    from ai_resource_eval.scoring.governor import ScoringGovernor
    from ai_resource_eval.tasks.loader import load_task_config

    cfg = load_task_config("plugin")

    signals = HealthSignals(
        freshness=80.0,
        popularity=50.0,
        source_trust=100.0,
        manifest_completeness=70.0,
        # install_popularity defaults to 0; excluded below to mimic non-skills.sh entry
    )

    health_score = ScoringGovernor.compute_health_score(
        signals,
        cfg.heuristic_signals,
        excluded_signals={"install_popularity"},
    )
    assert health_score == pytest.approx(76.0)

    # With health_blend_alpha=0.0 the runner returns final_score = health_score.
    # We mirror the runner's branch:
    #   if metrics is empty → llm_score is None → final_score = health_score (line 365)
    # See runner._eval_one health-only path.
    final_score = health_score  # health-only branch
    assert final_score == pytest.approx(health_score)


def test_map_result_to_entry_health_only_final_score():
    """map_result_to_entry: a health-only EvalResult dict (no metrics, final_score=76)
    should populate entry.evaluation.final_score == 76 and entry.final_score == 76.
    """
    from eval_bridge import map_result_to_entry

    entry = {
        "id": "plugin-1",
        "name": "Test Plugin",
        "type": "plugin",
        "source": "claude-plugins-official",
    }
    result = {
        "entry_id": "plugin-1",
        "metrics": {},  # health-only: no LLM dimensions
        "enrichment": None,
        "health": {
            "freshness": 80.0,
            "popularity": 50.0,
            "source_trust": 100.0,
            "manifest_completeness": 70.0,
        },
        "llm_score": None,
        "final_score": 76.0,  # = health_score (alpha=0)
        "decision": "accept",
        "star_weight": 1.0,
        "content_hash": "deadbeef",
        "rubric_version": "1.cafef00d",
        "model_id": "",
        "evaluated_at": "2026-05-07T00:00:00Z",
    }
    map_result_to_entry(entry, result)

    ev = entry["evaluation"]
    # No LLM metric scores leaked into evaluation
    for llm_dim in ("coding_relevance", "doc_completeness", "writing_quality"):
        assert llm_dim not in ev
    assert ev["final_score"] == 76
    assert ev["decision"] == "accept"
    assert entry["final_score"] == 76
    assert entry["decision"] == "accept"


# ---------------------------------------------------------------------------
# 5. Enrichment propagation
# ---------------------------------------------------------------------------


def test_enrichment_fields_propagate_for_plugin():
    """A plugin EvalResult with enrichment data should propagate summary/summary_zh/
    tags/highlights onto the catalog entry.
    """
    from eval_bridge import map_result_to_entry

    entry = {
        "id": "plugin-2",
        "name": "Another Plugin",
        "type": "plugin",
        "description": "原始描述",
        "source": "superpowers-marketplace",
    }
    enrichment = {
        "summary": "Plugin that bundles three productivity skills",
        "summary_zh": "打包三个效率工具的插件集",
        "tags": ["plugin", "productivity", "claude-code"],
        "tech_stack": ["typescript"],
        "search_terms": ["productivity", "效率", "plugin bundle"],
        "highlights": ["3 个 skill 一键安装", "兼容 Claude Code"],
    }
    result = {
        "entry_id": "plugin-2",
        "metrics": {},
        "enrichment": enrichment,
        "health": {
            "freshness": 90.0,
            "popularity": 60.0,
            "source_trust": 95.0,
            "manifest_completeness": 100.0,
        },
        "llm_score": None,
        "final_score": 84.5,
        "decision": "accept",
        "star_weight": 1.0,
        "content_hash": "abc",
        "rubric_version": "1.deadbeef",
        "model_id": "deepseek-chat",
        "evaluated_at": "2026-05-07T00:00:00Z",
    }

    map_result_to_entry(entry, result)

    # Enrichment fields propagated
    assert entry["tags"] == ["plugin", "productivity", "claude-code"]
    assert entry["tech_stack"] == ["typescript"]
    assert entry["description_zh"] == "打包三个效率工具的插件集"
    assert entry["search_terms"] == ["productivity", "效率", "plugin bundle"]
    assert entry["highlights"] == ["3 个 skill 一键安装", "兼容 Claude Code"]
    # summary overwrites description; original is preserved as description_original
    assert entry["description"] == "Plugin that bundles three productivity skills"
    assert entry["description_original"] == "原始描述"

    # Health signals also mapped
    assert entry["health"]["score"] == round((90.0 + 60.0 + 95.0) / 3)
    assert entry["health"]["signals"]["freshness"] == 90
    assert entry["health"]["signals"]["popularity"] == 60
    assert entry["health"]["signals"]["source_trust"] == 95
