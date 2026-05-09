"""Tests for scripts.run_enrichment — per-type runner with budget enforcement.

These tests stub out :func:`scripts.eval_bridge.run_eval` and
:func:`scripts.eval_bridge._compute_rubric_version_for_task` so they never hit
the network or require ``ai-resource-eval`` to be importable.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import run_enrichment  # noqa: E402
from eval_failure_log import (  # noqa: E402
    QUARANTINE_SENTINEL,
    FailureLog,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_catalog(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")


def _stub_rubric(monkeypatch, version: str = "1.testaaaa") -> None:
    """Force a deterministic rubric_version regardless of ai-resource-eval."""
    monkeypatch.setattr(
        run_enrichment,
        "_compute_rubric_version_for_task",
        lambda task_name: version,
    )


def _make_run_eval_stub(captured: dict, *, sleep: float = 0.0):
    """Build a fake run_eval that records its inputs and returns canned results.

    Each call appends the list of received entry ids to ``captured["calls"]`` and
    returns a result dict mapping each entry id to a small evaluation dict.
    """
    captured.setdefault("calls", [])

    def _stub(entries, **kwargs):
        captured["calls"].append([str(e["id"]) for e in entries])
        captured.setdefault("kwargs", []).append(kwargs)
        if sleep:
            time.sleep(sleep)
        return {
            str(e["id"]): {
                "entry_id": str(e["id"]),
                "final_score": 80,
                "decision": "accept",
            }
            for e in entries
        }

    return _stub


def _read_artifact(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _base_args(
    *,
    type_: str,
    catalog: Path,
    maintenance_dir: Path,
    output: Path,
    extra: list[str] | None = None,
) -> list[str]:
    args = [
        "--type",
        type_,
        "--catalog",
        str(catalog),
        "--maintenance-dir",
        str(maintenance_dir),
        "--output",
        str(output),
    ]
    if extra:
        args.extend(extra)
    return args


# ---------------------------------------------------------------------------
# 1. type filter
# ---------------------------------------------------------------------------


def test_type_filter_only_evaluates_target_type(tmp_path, monkeypatch):
    catalog = tmp_path / "index.json"
    _write_catalog(
        catalog,
        [
            {"id": "mcp-1", "type": "mcp", "name": "M1"},
            {"id": "mcp-2", "type": "mcp", "name": "M2"},
            {"id": "skill-1", "type": "skill", "name": "S1"},
            {"id": "rule-1", "type": "rule", "name": "R1"},
        ],
    )
    _stub_rubric(monkeypatch)

    captured: dict = {}
    monkeypatch.setattr(run_enrichment, "run_eval", _make_run_eval_stub(captured))

    output = tmp_path / "out.json"
    rc = run_enrichment.main(
        _base_args(
            type_="mcp",
            catalog=catalog,
            maintenance_dir=tmp_path / "maintenance",
            output=output,
        )
    )
    assert rc == 0
    # Only mcp ids ever reached run_eval.
    flat = [eid for batch in captured["calls"] for eid in batch]
    assert sorted(flat) == ["mcp-1", "mcp-2"]

    artifact = _read_artifact(output)
    assert artifact["type"] == "mcp"
    succeeded_ids = sorted(r["entry_id"] for r in artifact["succeeded"])
    assert succeeded_ids == ["mcp-1", "mcp-2"]


# ---------------------------------------------------------------------------
# 2. quarantine skip
# ---------------------------------------------------------------------------


def test_quarantined_entries_excluded_from_run_eval(tmp_path, monkeypatch):
    catalog = tmp_path / "index.json"
    _write_catalog(
        catalog,
        [
            {"id": "mcp-1", "type": "mcp"},
            {"id": "mcp-bad", "type": "mcp"},
            {"id": "mcp-3", "type": "mcp"},
        ],
    )
    _stub_rubric(monkeypatch, "2.fixedver")

    # Pre-populate failure ledger with a quarantined entry.
    maintenance = tmp_path / "maintenance"
    ledger_path = maintenance / "eval_failures.json"
    log = FailureLog(ledger_path, rubric_version="2.fixedver")
    for _ in range(4):
        log.record_failure("mcp-bad", "mcp", "TimeoutError", "boom")
    assert log.is_quarantined("mcp-bad")
    log.save()

    captured: dict = {}
    monkeypatch.setattr(run_enrichment, "run_eval", _make_run_eval_stub(captured))

    output = tmp_path / "out.json"
    rc = run_enrichment.main(
        _base_args(
            type_="mcp",
            catalog=catalog,
            maintenance_dir=maintenance,
            output=output,
        )
    )
    assert rc == 0
    flat = [eid for batch in captured["calls"] for eid in batch]
    assert "mcp-bad" not in flat
    assert sorted(flat) == ["mcp-1", "mcp-3"]

    artifact = _read_artifact(output)
    assert "mcp-bad" in artifact["skipped_quarantined"]
    assert "mcp-bad" not in {r["entry_id"] for r in artifact["succeeded"]}


# ---------------------------------------------------------------------------
# 3. deferred skip (next_retry_after in the future)
# ---------------------------------------------------------------------------


def test_deferred_entries_excluded_from_run_eval(tmp_path, monkeypatch):
    catalog = tmp_path / "index.json"
    _write_catalog(
        catalog,
        [
            {"id": "mcp-1", "type": "mcp"},
            {"id": "mcp-deferred", "type": "mcp"},
        ],
    )
    _stub_rubric(monkeypatch, "2.fixedver")

    maintenance = tmp_path / "maintenance"
    ledger_path = maintenance / "eval_failures.json"
    log = FailureLog(ledger_path, rubric_version="2.fixedver")
    # 1 prior failure -> next_retry_after = now (but we'll override).
    log.record_failure("mcp-deferred", "mcp", "Http5xx", "transient")
    # Push next_retry_after into the future to simulate a 7-day backoff window.
    rec = log.failures["mcp-deferred"]
    rec.attempt_count = 2
    future = datetime.now(timezone.utc) + timedelta(days=7)
    rec.next_retry_after = future.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    log.save()

    captured: dict = {}
    monkeypatch.setattr(run_enrichment, "run_eval", _make_run_eval_stub(captured))

    output = tmp_path / "out.json"
    rc = run_enrichment.main(
        _base_args(
            type_="mcp",
            catalog=catalog,
            maintenance_dir=maintenance,
            output=output,
        )
    )
    assert rc == 0
    flat = [eid for batch in captured["calls"] for eid in batch]
    assert "mcp-deferred" not in flat
    assert flat == ["mcp-1"]

    artifact = _read_artifact(output)
    assert "mcp-deferred" in artifact["skipped_deferred"]
    assert "mcp-deferred" not in artifact["skipped_quarantined"]


# ---------------------------------------------------------------------------
# 4. mock-mode reads from fixture dir
# ---------------------------------------------------------------------------


def test_mock_mode_reads_from_fixture_path(tmp_path, monkeypatch):
    fixture_dir = tmp_path / "fixture"
    fixture_dir.mkdir()
    fixture_entries = [
        {"id": "skill-mock-1", "type": "skill", "name": "Mock"},
        {"id": "skill-mock-2", "type": "skill", "name": "Mock2"},
    ]
    (fixture_dir / "skill.json").write_text(
        json.dumps(fixture_entries), encoding="utf-8"
    )

    # The "real" catalog has different content — we should ignore it in mock mode.
    catalog = tmp_path / "index.json"
    _write_catalog(catalog, [{"id": "skill-real", "type": "skill"}])

    _stub_rubric(monkeypatch)
    captured: dict = {}
    monkeypatch.setattr(run_enrichment, "run_eval", _make_run_eval_stub(captured))

    output = tmp_path / "out.json"
    rc = run_enrichment.main(
        [
            "--type",
            "skill",
            "--mock-mode",
            "--mock-fixture-dir",
            str(fixture_dir),
            "--catalog",
            str(catalog),
            "--maintenance-dir",
            str(tmp_path / "maintenance"),
            "--output",
            str(output),
        ]
    )
    assert rc == 0
    flat = [eid for batch in captured["calls"] for eid in batch]
    assert sorted(flat) == ["skill-mock-1", "skill-mock-2"]
    assert "skill-real" not in flat


# ---------------------------------------------------------------------------
# 5. mock-mode default output path -> tests/_test_output/<type>.json
# ---------------------------------------------------------------------------


def test_mock_mode_default_output_path_under_test_output_dir(tmp_path, monkeypatch):
    fixture_dir = tmp_path / "fixture"
    fixture_dir.mkdir()
    (fixture_dir / "skill.json").write_text(
        json.dumps([{"id": "s1", "type": "skill"}]), encoding="utf-8"
    )
    _stub_rubric(monkeypatch)

    captured: dict = {}
    monkeypatch.setattr(run_enrichment, "run_eval", _make_run_eval_stub(captured))

    # Default-path resolution should still go through _resolve_output_path. We
    # validate the helper directly to avoid writing into the real repo tree.
    args = run_enrichment._build_arg_parser().parse_args(
        [
            "--type",
            "skill",
            "--mock-mode",
            "--mock-fixture-dir",
            str(fixture_dir),
        ]
    )
    resolved = run_enrichment._resolve_output_path(args)
    assert resolved == Path("tests/_test_output/skill.json")

    # And in normal mode the default lands under tests/_enrich_output/.
    args_normal = run_enrichment._build_arg_parser().parse_args(
        ["--type", "mcp"]
    )
    assert run_enrichment._resolve_output_path(args_normal) == Path(
        "tests/_enrich_output/mcp.json"
    )


# ---------------------------------------------------------------------------
# 6. --max-wall-seconds short-circuits before next batch
# ---------------------------------------------------------------------------


def test_max_wall_seconds_short_circuits(tmp_path, monkeypatch, capsys):
    catalog = tmp_path / "index.json"
    # 4 entries with batch-size=2 -> 2 mini-batches. The first batch sleeps
    # past the budget; the second must NOT run.
    _write_catalog(
        catalog,
        [{"id": f"mcp-{i}", "type": "mcp"} for i in range(1, 5)],
    )
    _stub_rubric(monkeypatch)

    captured: dict = {}
    monkeypatch.setattr(
        run_enrichment, "run_eval", _make_run_eval_stub(captured, sleep=1.2)
    )

    output = tmp_path / "out.json"
    rc = run_enrichment.main(
        [
            "--type",
            "mcp",
            "--catalog",
            str(catalog),
            "--maintenance-dir",
            str(tmp_path / "maintenance"),
            "--output",
            str(output),
            "--max-wall-seconds",
            "1",
            "--batch-size",
            "2",
        ]
    )
    assert rc == 0

    # Only the first batch should have been invoked.
    assert len(captured["calls"]) == 1
    assert sorted(captured["calls"][0]) == ["mcp-1", "mcp-2"]

    out = capsys.readouterr().out
    assert "budget reached" in out
    assert "[type=mcp]" in out

    # Artifact present, with the unprocessed ids surfaced as failed.
    artifact = _read_artifact(output)
    succeeded_ids = sorted(r["entry_id"] for r in artifact["succeeded"])
    assert succeeded_ids == ["mcp-1", "mcp-2"]
    assert sorted(artifact["failed"]) == ["mcp-3", "mcp-4"]


# ---------------------------------------------------------------------------
# 7. output artifact schema
# ---------------------------------------------------------------------------


def test_output_artifact_schema(tmp_path, monkeypatch):
    catalog = tmp_path / "index.json"
    _write_catalog(catalog, [{"id": "p1", "type": "plugin"}])
    _stub_rubric(monkeypatch, "9.deadbeef")

    monkeypatch.setattr(
        run_enrichment, "run_eval", _make_run_eval_stub(captured := {})
    )

    output = tmp_path / "plugins.json"
    rc = run_enrichment.main(
        _base_args(
            type_="plugin",
            catalog=catalog,
            maintenance_dir=tmp_path / "maintenance",
            output=output,
        )
    )
    assert rc == 0

    artifact = _read_artifact(output)
    expected_keys = {
        "type",
        "rubric_version",
        "generated_at",
        "succeeded",
        "failed",
        "skipped_quarantined",
        "skipped_deferred",
    }
    assert expected_keys.issubset(artifact.keys())
    assert artifact["type"] == "plugin"
    assert artifact["rubric_version"] == "9.deadbeef"
    assert isinstance(artifact["succeeded"], list)
    assert all(
        isinstance(r, dict) and "entry_id" in r and "evaluation" in r
        for r in artifact["succeeded"]
    )
    assert isinstance(artifact["failed"], list)
    assert isinstance(artifact["skipped_quarantined"], list)
    assert isinstance(artifact["skipped_deferred"], list)


# ---------------------------------------------------------------------------
# 8. no entries for type -> exit 0, no run_eval call
# ---------------------------------------------------------------------------


def test_no_entries_for_type_exits_zero(tmp_path, monkeypatch, capsys):
    catalog = tmp_path / "index.json"
    _write_catalog(catalog, [{"id": "skill-only", "type": "skill"}])
    _stub_rubric(monkeypatch)

    captured: dict = {}
    monkeypatch.setattr(run_enrichment, "run_eval", _make_run_eval_stub(captured))

    output = tmp_path / "out.json"
    rc = run_enrichment.main(
        _base_args(
            type_="mcp",
            catalog=catalog,
            maintenance_dir=tmp_path / "maintenance",
            output=output,
        )
    )
    assert rc == 0
    assert captured.get("calls", []) == []
    out = capsys.readouterr().out
    assert "no entries for this type" in out
    # No artifact should have been written.
    assert not output.exists()


# ---------------------------------------------------------------------------
# 9. --output override path is honored
# ---------------------------------------------------------------------------


def test_output_path_override_used(tmp_path, monkeypatch):
    catalog = tmp_path / "index.json"
    _write_catalog(catalog, [{"id": "r1", "type": "rule"}])
    _stub_rubric(monkeypatch)

    monkeypatch.setattr(
        run_enrichment, "run_eval", _make_run_eval_stub(captured := {})
    )

    custom = tmp_path / "deeply" / "nested" / "out.json"
    rc = run_enrichment.main(
        _base_args(
            type_="rule",
            catalog=catalog,
            maintenance_dir=tmp_path / "maintenance",
            output=custom,
        )
    )
    assert rc == 0
    assert custom.exists()
    artifact = json.loads(custom.read_text(encoding="utf-8"))
    assert artifact["type"] == "rule"
    assert {r["entry_id"] for r in artifact["succeeded"]} == {"r1"}
