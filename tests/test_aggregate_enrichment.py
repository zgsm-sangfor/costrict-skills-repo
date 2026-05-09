"""Tests for scripts.aggregate_enrichment — partial artifact stitcher.

These tests stub the git-show subprocess so no real git history is needed,
and use ``tmp_path`` for catalog / partial / output to keep production
``catalog/`` untouched.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import aggregate_enrichment  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _make_entry(
    eid: str,
    type_: str,
    *,
    health_score: float | None = None,
    evaluation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "id": eid,
        "type": type_,
        "name": eid,
        "evaluation": evaluation if evaluation is not None else {},
    }
    if health_score is not None:
        entry["health"] = {"score": health_score}
    return entry


def _make_partial(
    type_: str,
    succeeded: list[tuple[str, dict[str, Any]]],
    *,
    failed: list[str] | None = None,
    quarantined: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "type": type_,
        "rubric_version": "1.testaaaa",
        "generated_at": "2026-05-09T03:00:00Z",
        "succeeded": [{"entry_id": eid, "evaluation": ev} for eid, ev in succeeded],
        "failed": failed or [],
        "skipped_quarantined": quarantined or [],
        "skipped_deferred": [],
    }


class _FakeCompletedProcess:
    def __init__(self, returncode: int, stdout: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = ""


def _stub_git_show(monkeypatch, payload: list[dict[str, Any]] | None) -> None:
    """Patch subprocess.run inside aggregate_enrichment to return ``payload``.

    ``payload=None`` simulates a git failure (returncode != 0).
    """

    def fake_run(cmd, capture_output=True, text=True, check=False):  # noqa: ARG001
        if payload is None:
            return _FakeCompletedProcess(returncode=128, stdout="")
        return _FakeCompletedProcess(
            returncode=0, stdout=json.dumps(payload, ensure_ascii=False)
        )

    monkeypatch.setattr(aggregate_enrichment.subprocess, "run", fake_run)


def _run_main(
    tmp_path: Path,
    *,
    catalog_entries: list[dict[str, Any]],
    partials: dict[str, dict[str, Any]],
    types: list[str] | None = None,
    output_path: Path | None = None,
    step_summary_path: Path | None = None,
    extra_args: list[str] | None = None,
) -> Path:
    """Wire up tmp paths, write fixtures, invoke main, return the output path."""
    catalog_path = tmp_path / "catalog" / "index.json"
    _write_json(catalog_path, catalog_entries)

    partial_dir = tmp_path / "partial"
    partial_dir.mkdir(parents=True, exist_ok=True)
    for t, p in partials.items():
        _write_json(partial_dir / f"{t}.json", p)

    output = output_path if output_path is not None else catalog_path
    types_arg = ",".join(types) if types else "mcp,skill,rule,prompt,plugin"

    argv = [
        "--catalog",
        str(catalog_path),
        "--partial-dir",
        str(partial_dir),
        "--output",
        str(output),
        "--types",
        types_arg,
    ]
    if step_summary_path is not None:
        argv += ["--step-summary", str(step_summary_path)]
    if extra_args:
        argv += extra_args

    rc = aggregate_enrichment.main(argv)
    assert rc == 0
    return output


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_partial_artifact_succeeds_writes_new_eval(tmp_path, monkeypatch):
    _stub_git_show(monkeypatch, payload=[])

    entries = [
        _make_entry("a", "mcp", health_score=50),
        _make_entry("b", "mcp", health_score=60),
    ]
    partial = _make_partial(
        "mcp",
        [
            ("a", {"final_score": 88, "decision": "accept"}),
            ("b", {"final_score": 72, "decision": "review"}),
        ],
    )
    out = _run_main(
        tmp_path,
        catalog_entries=entries,
        partials={"mcp": partial},
        types=["mcp"],
    )
    result = _read_json(out)
    by_id = {e["id"]: e for e in result}
    assert by_id["a"]["evaluation"]["final_score"] == 88
    assert by_id["a"]["evaluation"]["decision"] == "accept"
    assert by_id["b"]["evaluation"]["final_score"] == 72
    assert by_id["b"]["evaluation"]["decision"] == "review"


def test_missing_partial_artifact_falls_back_to_old_catalog(tmp_path, monkeypatch):
    old_eval_a = {"final_score": 65, "decision": "accept", "evaluation_mode": "llm"}
    old_eval_b = {"final_score": 30, "decision": "reject", "evaluation_mode": "llm"}
    old_payload = [
        _make_entry("a", "mcp", evaluation=old_eval_a),
        _make_entry("b", "mcp", evaluation=old_eval_b),
    ]
    _stub_git_show(monkeypatch, payload=old_payload)

    entries = [
        _make_entry("a", "mcp", health_score=50),
        _make_entry("b", "mcp", health_score=60),
    ]
    # No partial artifact for mcp at all (cell failed).
    out = _run_main(
        tmp_path,
        catalog_entries=entries,
        partials={},
        types=["mcp"],
    )
    result = _read_json(out)
    by_id = {e["id"]: e for e in result}
    assert by_id["a"]["evaluation"] == old_eval_a
    assert by_id["b"]["evaluation"] == old_eval_b
    assert by_id["a"]["final_score"] == 65
    assert by_id["a"]["decision"] == "accept"


def test_new_entry_gets_health_only_synthesis(tmp_path, monkeypatch):
    # Old catalog is empty; partial has no evaluation for `e_new`.
    _stub_git_show(monkeypatch, payload=[])

    entries = [_make_entry("e_new", "mcp", health_score=42)]
    # Partial exists but doesn't include e_new — cell ran but skipped this entry.
    partial = _make_partial("mcp", [])
    out = _run_main(
        tmp_path,
        catalog_entries=entries,
        partials={"mcp": partial},
        types=["mcp"],
    )
    result = _read_json(out)
    ev = result[0]["evaluation"]
    assert ev["final_score"] == 42
    assert ev["decision"] == "review"
    assert ev["evaluation_mode"] == "health_only_synthesized"
    assert "evaluated_at" in ev
    assert result[0]["final_score"] == 42
    assert result[0]["decision"] == "review"


def test_partial_partial_artifact_mixed_fallback(tmp_path, monkeypatch):
    # Old catalog provides eval for a4 and a5 only.
    old_payload = [
        _make_entry("a4", "mcp", evaluation={"final_score": 55, "decision": "review"}),
        _make_entry("a5", "mcp", evaluation={"final_score": 25, "decision": "reject"}),
    ]
    _stub_git_show(monkeypatch, payload=old_payload)

    entries = [
        _make_entry("a1", "mcp", health_score=10),
        _make_entry("a2", "mcp", health_score=20),
        _make_entry("a3", "mcp", health_score=30),
        _make_entry("a4", "mcp", health_score=40),
        _make_entry("a5", "mcp", health_score=50),
    ]
    # Partial covers a1..a3 only.
    partial = _make_partial(
        "mcp",
        [
            ("a1", {"final_score": 91, "decision": "accept"}),
            ("a2", {"final_score": 80, "decision": "accept"}),
            ("a3", {"final_score": 75, "decision": "review"}),
        ],
    )
    out = _run_main(
        tmp_path,
        catalog_entries=entries,
        partials={"mcp": partial},
        types=["mcp"],
    )
    result = _read_json(out)
    by_id = {e["id"]: e for e in result}
    # New eval for a1..a3
    assert by_id["a1"]["evaluation"]["final_score"] == 91
    assert by_id["a2"]["evaluation"]["final_score"] == 80
    assert by_id["a3"]["evaluation"]["final_score"] == 75
    # Old eval for a4, a5
    assert by_id["a4"]["evaluation"]["final_score"] == 55
    assert by_id["a4"]["evaluation"]["decision"] == "review"
    assert by_id["a5"]["evaluation"]["final_score"] == 25
    assert by_id["a5"]["evaluation"]["decision"] == "reject"


def test_top_level_final_score_decision_promoted(tmp_path, monkeypatch):
    """Every entry must have top-level final_score (number) + decision (str)
    matching the inner evaluation values, regardless of source (new/old/synth)."""
    old_payload = [
        _make_entry(
            "old_one", "mcp", evaluation={"final_score": 51, "decision": "review"}
        ),
    ]
    _stub_git_show(monkeypatch, payload=old_payload)

    entries = [
        _make_entry("new_one", "mcp", health_score=10),
        _make_entry("old_one", "mcp", health_score=20),
        _make_entry("synth_one", "mcp", health_score=33),
    ]
    partial = _make_partial(
        "mcp",
        [("new_one", {"final_score": 99, "decision": "accept"})],
    )
    out = _run_main(
        tmp_path,
        catalog_entries=entries,
        partials={"mcp": partial},
        types=["mcp"],
    )
    result = _read_json(out)
    for entry in result:
        ev = entry["evaluation"]
        assert isinstance(entry["final_score"], (int, float))
        assert isinstance(entry["decision"], str)
        assert entry["final_score"] == ev.get("final_score", 0)
        assert entry["decision"] == ev.get("decision", "review")

    by_id = {e["id"]: e for e in result}
    assert by_id["new_one"]["final_score"] == 99
    assert by_id["new_one"]["decision"] == "accept"
    assert by_id["old_one"]["final_score"] == 51
    assert by_id["old_one"]["decision"] == "review"
    assert by_id["synth_one"]["final_score"] == 33
    assert by_id["synth_one"]["decision"] == "review"


def test_step_summary_markdown_format(tmp_path, monkeypatch):
    _stub_git_show(monkeypatch, payload=[])

    entries = [
        _make_entry("m1", "mcp", health_score=10),
        _make_entry("s1", "skill", health_score=15),
    ]
    partials = {
        "mcp": _make_partial("mcp", [("m1", {"final_score": 70, "decision": "accept"})]),
        "skill": _make_partial(
            "skill", [("s1", {"final_score": 60, "decision": "review"})]
        ),
    }
    summary_path = tmp_path / "summary.md"

    # Verify --step-summary CLI arg and env var both work; here use the CLI arg.
    _run_main(
        tmp_path,
        catalog_entries=entries,
        partials=partials,
        types=["mcp", "skill"],
        step_summary_path=summary_path,
    )

    assert summary_path.exists()
    text = summary_path.read_text(encoding="utf-8")
    assert "Aggregate enrichment summary" in text
    # Markdown table header
    assert "| type | succeeded | failed | quarantined | fallback" in text
    # Rows for each type
    assert "| mcp |" in text
    assert "| skill |" in text


def test_step_summary_via_env_var(tmp_path, monkeypatch):
    """When --step-summary is omitted, $GITHUB_STEP_SUMMARY env var is used."""
    _stub_git_show(monkeypatch, payload=[])

    summary_path = tmp_path / "env_summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_path))

    entries = [_make_entry("m1", "mcp", health_score=10)]
    partial = _make_partial(
        "mcp", [("m1", {"final_score": 70, "decision": "accept"})]
    )
    _run_main(
        tmp_path,
        catalog_entries=entries,
        partials={"mcp": partial},
        types=["mcp"],
    )
    assert summary_path.exists()
    assert "| mcp |" in summary_path.read_text(encoding="utf-8")


def test_cell_failed_status_in_summary(tmp_path, monkeypatch):
    _stub_git_show(monkeypatch, payload=[])

    entries = [
        _make_entry("m1", "mcp", health_score=10),
        _make_entry("s1", "skill", health_score=20),
    ]
    # Only skill has an artifact; mcp's cell "failed" (no file).
    partials = {
        "skill": _make_partial(
            "skill", [("s1", {"final_score": 60, "decision": "review"})]
        ),
    }
    summary_path = tmp_path / "summary.md"
    _run_main(
        tmp_path,
        catalog_entries=entries,
        partials=partials,
        types=["mcp", "skill"],
        step_summary_path=summary_path,
    )

    text = summary_path.read_text(encoding="utf-8")
    # Find the mcp row and assert the cell-status column reads "failed".
    mcp_lines = [ln for ln in text.splitlines() if ln.startswith("| mcp ")]
    assert mcp_lines, f"expected an mcp row in:\n{text}"
    assert "failed" in mcp_lines[0]
    skill_lines = [ln for ln in text.splitlines() if ln.startswith("| skill ")]
    assert skill_lines
    # Skill ran cleanly, no fallbacks → status should be "ok"
    assert "ok" in skill_lines[0]


def test_zero_args_works_with_defaults(tmp_path, monkeypatch):
    """Invoking main() with no argv should run against the default paths.

    We chdir into tmp_path and seed catalog/index.json + tests/_enrich_output/<type>.json
    relative to it, so the defaults resolve to safe sandboxed locations.
    """
    _stub_git_show(monkeypatch, payload=[])
    monkeypatch.chdir(tmp_path)

    catalog_path = tmp_path / "catalog" / "index.json"
    _write_json(
        catalog_path,
        [_make_entry("m1", "mcp", health_score=10)],
    )
    partial_path = tmp_path / "tests" / "_enrich_output" / "mcp.json"
    _write_json(
        partial_path,
        _make_partial("mcp", [("m1", {"final_score": 81, "decision": "accept"})]),
    )
    # Other types have no partial artifact; the main loop must tolerate that.
    summary_path = tmp_path / "default_summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_path))

    rc = aggregate_enrichment.main([])
    assert rc == 0

    result = _read_json(catalog_path)
    by_id = {e["id"]: e for e in result}
    assert by_id["m1"]["evaluation"]["final_score"] == 81
    assert by_id["m1"]["final_score"] == 81
    assert summary_path.exists()


def test_git_show_failure_falls_through_to_synthesis(tmp_path, monkeypatch):
    """When git show HEAD:catalog/index.json fails, all unevaluated entries
    must drop to the health-only synthesis path (no crash)."""
    _stub_git_show(monkeypatch, payload=None)  # simulates git failure

    entries = [_make_entry("orphan", "mcp", health_score=22)]
    partial = _make_partial("mcp", [])  # cell ran but evaluated nothing
    out = _run_main(
        tmp_path,
        catalog_entries=entries,
        partials={"mcp": partial},
        types=["mcp"],
    )
    result = _read_json(out)
    ev = result[0]["evaluation"]
    assert ev["evaluation_mode"] == "health_only_synthesized"
    assert ev["final_score"] == 22


def test_git_show_subprocess_unavailable(tmp_path, monkeypatch):
    """If the git binary is missing entirely, aggregate must still publish."""

    def fake_run(cmd, capture_output=True, text=True, check=False):  # noqa: ARG001
        raise FileNotFoundError("git binary missing in test sandbox")

    monkeypatch.setattr(aggregate_enrichment.subprocess, "run", fake_run)

    entries = [_make_entry("m1", "mcp", health_score=15)]
    out = _run_main(
        tmp_path,
        catalog_entries=entries,
        partials={"mcp": _make_partial("mcp", [])},
        types=["mcp"],
    )
    result = _read_json(out)
    assert result[0]["evaluation"]["evaluation_mode"] == "health_only_synthesized"
    assert result[0]["final_score"] == 15


def test_raw_eval_result_is_flattened_via_map_result_to_entry(tmp_path, monkeypatch):
    """A partial artifact carries the raw run_eval result (nested ``metrics``,
    side-channel ``enrichment`` / ``health``). Aggregate must route it through
    eval_bridge.map_result_to_entry so the catalog ends up with the flattened
    schema (``evaluation.coding_relevance`` etc.) and side-effect fields
    populated, not the raw blob."""
    _stub_git_show(monkeypatch, payload=[])

    raw_eval = {
        "entry_id": "x1",
        "final_score": 87,
        "decision": "accept",
        "model_id": "test-model",
        "rubric_version": "9.zzzz0000",
        "evaluated_at": "2026-05-09T04:00:00Z",
        "metrics": {
            "coding_relevance": {"score": 90, "evidence": "noisy", "missing": []},
            "doc_completeness": {"score": 70, "evidence": "noisy", "missing": []},
        },
        "enrichment": {
            "tags": ["alpha", "beta"],
            "summary": "rewritten summary",
            "summary_zh": "重写后的中文摘要",
            "search_terms": ["foo", "bar"],
        },
    }

    entries = [_make_entry("x1", "mcp", health_score=12)]
    entries[0]["description"] = "original desc"
    partial = _make_partial("mcp", [("x1", raw_eval)])
    out = _run_main(
        tmp_path,
        catalog_entries=entries,
        partials={"mcp": partial},
        types=["mcp"],
    )
    result = _read_json(out)
    entry = result[0]
    ev = entry["evaluation"]

    # Flattened metric scores live as top-level integer keys in evaluation.
    assert ev["coding_relevance"] == 90
    assert ev["doc_completeness"] == 70
    # The raw "metrics" dict must NOT survive verbatim.
    assert "metrics" not in ev or isinstance(ev.get("metrics"), int)
    # Governance fields propagate to evaluation + top-level promotions.
    assert ev["final_score"] == 87
    assert ev["decision"] == "accept"
    assert entry["final_score"] == 87
    assert entry["decision"] == "accept"
    # Enrichment side-effects should land on the entry, not on evaluation.
    assert entry["tags"] == ["alpha", "beta"]
    assert entry["description"] == "rewritten summary"
    assert entry["description_zh"] == "重写后的中文摘要"
    assert entry["search_terms"] == ["foo", "bar"]


def test_search_index_regenerated_with_restored_scores(tmp_path, monkeypatch):
    """After aggregate, ``search-index.json`` next to the catalog must reflect
    the restored final_score / decision / description, not the placeholder
    zeros that ``merge_index.py --skip-enrichment`` would have written."""
    _stub_git_show(monkeypatch, payload=[])

    raw_eval = {
        "entry_id": "y1",
        "final_score": 81,
        "decision": "accept",
        "metrics": {"writing_quality": {"score": 80}},
        "enrichment": {"summary": "shiny new summary"},
    }
    entry_y1 = _make_entry("y1", "skill", health_score=44)
    entry_y1["description"] = "boring"
    entries = [
        entry_y1,
        _make_entry("y2", "skill", health_score=33),  # falls back to synth
    ]
    partial = _make_partial("skill", [("y1", raw_eval)])
    out = _run_main(
        tmp_path,
        catalog_entries=entries,
        partials={"skill": partial},
        types=["skill"],
    )
    search_path = Path(out).parent / "search-index.json"
    assert search_path.exists()
    search_data = json.loads(search_path.read_text(encoding="utf-8"))
    by_id = {row["id"]: row for row in search_data}
    assert by_id["y1"]["final_score"] == 81
    assert by_id["y1"]["decision"] == "accept"
    assert by_id["y1"]["description"] == "shiny new summary"
    # Synthesized fallback still gets recorded — score equals health.score.
    assert by_id["y2"]["final_score"] == 33
    assert by_id["y2"]["decision"] == "review"


def test_fallback_overlays_llm_side_effect_fields(tmp_path, monkeypatch):
    """Phase 4 regression guard: when an entry takes the fallback path (cell
    failed / budget cutoff / quarantined), aggregate must overlay LLM-derived
    side-effect fields from old catalog onto the data-layer entry. Without this,
    fallback rows lose health/description_zh/search_terms/etc."""
    old_catalog = [
        {
            "id": "fallback-mcp",
            "type": "mcp",
            "name": "Fallback MCP",
            "description": "rewritten by LLM last week",
            "description_original": "raw upstream description",
            "description_zh": "上周的中文摘要",
            "search_terms": ["foo", "bar"],
            "highlights": ["one", "two"],
            "health": {"score": 75, "freshness_label": "active"},
            "mcp_install_state": "ready",
            "mcp_validation_tags": ["catalog_config_ready"],
            "mcp_schema_valid": True,
            "mcp_installability_reason": "上周判定可直接安装",
            "evaluation": {"final_score": 80, "decision": "accept"},
        },
    ]
    _stub_git_show(monkeypatch, payload=old_catalog)

    # Data-layer entry: fresh from merge_index --skip-enrichment, no LLM fields.
    data_entry = _make_entry("fallback-mcp", "mcp", health_score=10)
    data_entry["description"] = "raw upstream description"

    # Empty partial artifact -> entry must take the old-eval fallback path.
    partial = _make_partial("mcp", [])
    out = _run_main(
        tmp_path,
        catalog_entries=[data_entry],
        partials={"mcp": partial},
        types=["mcp"],
    )
    result = _read_json(out)
    entry = result[0]

    # evaluation came from old catalog
    assert entry["evaluation"]["final_score"] == 80
    assert entry["evaluation"]["decision"] == "accept"

    # LLM-derived side-effects overlaid from old catalog
    assert entry["description_zh"] == "上周的中文摘要"
    assert entry["search_terms"] == ["foo", "bar"]
    assert entry["highlights"] == ["one", "two"]
    assert entry["health"]["score"] == 75
    assert entry["mcp_install_state"] == "ready"
    assert entry["mcp_validation_tags"] == ["catalog_config_ready"]
    assert entry["mcp_schema_valid"] is True
    assert entry["mcp_installability_reason"] == "上周判定可直接安装"

    # Description: old catalog had description_original (signal of LLM rewrite),
    # so old description must override the data-layer one.
    assert entry["description"] == "rewritten by LLM last week"
    assert entry["description_original"] == "raw upstream description"
