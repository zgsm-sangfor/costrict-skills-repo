"""Tests for scripts.enrichment_checkpoint — load/save, flush granularity, rubric reset."""
import json
import logging
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import enrichment_checkpoint  # noqa: E402
import eval_failure_log  # noqa: E402
from enrichment_checkpoint import Checkpoint  # noqa: E402
from eval_failure_log import FailureLog  # noqa: E402


# ----------------------------------------------------------- load / fresh


def test_initial_load_no_file_returns_all_remaining(tmp_path):
    cp = Checkpoint("mcp", tmp_path / "cp.json", rubric_version="1.aaa")
    completed, remaining = cp.load(["a", "b", "c"])
    assert completed == []
    assert remaining == ["a", "b", "c"]


def test_mark_completed_moves_id(tmp_path):
    cp = Checkpoint("mcp", tmp_path / "cp.json", rubric_version="1.aaa")
    cp.load(["a", "b", "c"])
    cp.mark_completed("a")
    assert cp.completed_entry_ids == ["a"]
    assert cp.remaining_entry_ids == ["b", "c"]


def test_mark_completed_idempotent_for_unknown_id(tmp_path):
    cp = Checkpoint("mcp", tmp_path / "cp.json", rubric_version="1.aaa")
    cp.load(["a", "b", "c"])
    # Not in remaining — no-op, no error.
    cp.mark_completed("z")
    assert cp.completed_entry_ids == []
    assert cp.remaining_entry_ids == ["a", "b", "c"]

    # Already completed — also no-op.
    cp.mark_completed("a")
    cp.mark_completed("a")
    assert cp.completed_entry_ids == ["a"]


# ------------------------------------------------------------ persistence


def test_flush_persists_state_atomically(tmp_path):
    path = tmp_path / "cp.json"
    cp = Checkpoint("mcp", path, rubric_version="1.aaa")
    cp.load(["a", "b", "c"])
    cp.mark_completed("a")
    cp.flush()
    assert path.exists()
    assert not path.with_suffix(path.suffix + ".tmp").exists()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["type"] == "mcp"
    assert payload["rubric_version"] == "1.aaa"
    assert payload["completed_entry_ids"] == ["a"]
    assert payload["completed_count"] == 1
    assert payload["remaining_entry_ids"] == ["b", "c"]


def test_auto_flush_at_50_entries(tmp_path):
    path = tmp_path / "cp.json"
    cp = Checkpoint("mcp", path, rubric_version="1.aaa", flush_every=50)
    ids = [f"id-{i:03d}" for i in range(100)]
    cp.load(ids)

    # Mark 49 — file should NOT yet exist.
    for eid in ids[:49]:
        cp.mark_completed(eid)
    assert not path.exists(), "checkpoint should not auto-flush before threshold"

    # Mark the 50th — auto-flush triggers.
    cp.mark_completed(ids[49])
    assert path.exists(), "checkpoint should auto-flush at flush_every"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["completed_count"] == 50


def test_auto_flush_resets_counter(tmp_path):
    """After auto-flush the counter resets, so the next 49 do not flush again."""
    path = tmp_path / "cp.json"
    cp = Checkpoint("mcp", path, rubric_version="1.aaa", flush_every=50)
    ids = [f"id-{i:03d}" for i in range(100)]
    cp.load(ids)
    for eid in ids[:50]:
        cp.mark_completed(eid)
    assert path.exists()
    # Snapshot mtime + payload at this boundary.
    snapshot = path.read_text(encoding="utf-8")

    # Next 49 should not trigger a write.
    for eid in ids[50:99]:
        cp.mark_completed(eid)
    assert path.read_text(encoding="utf-8") == snapshot

    # The 100th does trigger another flush.
    cp.mark_completed(ids[99])
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["completed_count"] == 100


# ------------------------------------------------------------- resume


def test_resume_skips_completed(tmp_path):
    path = tmp_path / "cp.json"
    cp = Checkpoint("mcp", path, rubric_version="1.aaa")
    cp.load(["a", "b", "c", "d"])
    cp.mark_completed("a")
    cp.mark_completed("b")
    cp.flush()

    cp2 = Checkpoint("mcp", path, rubric_version="1.aaa")
    completed, remaining = cp2.load(["a", "b", "c", "d"])
    assert completed == ["a", "b"]
    assert remaining == ["c", "d"]


def test_remaining_recomputed_when_upstream_set_changes(tmp_path):
    path = tmp_path / "cp.json"
    cp = Checkpoint("mcp", path, rubric_version="1.aaa")
    cp.load(["a", "b"])
    cp.mark_completed("a")
    cp.mark_completed("b")
    cp.flush()

    cp2 = Checkpoint("mcp", path, rubric_version="1.aaa")
    completed, remaining = cp2.load(["a", "b", "c", "d"])
    assert completed == ["a", "b"]
    assert remaining == ["c", "d"]


def test_completed_entries_no_longer_in_input_are_dropped(tmp_path):
    """Drop completed ids that are no longer in the upstream set."""
    path = tmp_path / "cp.json"
    cp = Checkpoint("mcp", path, rubric_version="1.aaa")
    cp.load(["a", "b", "x"])
    cp.mark_completed("a")
    cp.mark_completed("b")
    cp.mark_completed("x")
    cp.flush()

    cp2 = Checkpoint("mcp", path, rubric_version="1.aaa")
    completed, remaining = cp2.load(["a", "b", "c"])
    assert completed == ["a", "b"]
    assert "x" not in completed
    assert remaining == ["c"]


# ------------------------------------------------------- rubric mismatch


def test_rubric_mismatch_discards_checkpoint_with_warning(tmp_path, caplog, capsys):
    path = tmp_path / "cp.json"
    cp = Checkpoint("mcp", path, rubric_version="1.aaa")
    cp.load(["a", "b", "c"])
    cp.mark_completed("a")
    cp.flush()

    cp2 = Checkpoint("mcp", path, rubric_version="2.bbb")
    with caplog.at_level(logging.WARNING, logger="enrichment_checkpoint"):
        completed, remaining = cp2.load(["a", "b", "c"])
    captured = capsys.readouterr()
    assert completed == []
    assert remaining == ["a", "b", "c"]

    # Either the WARNING was logged, or the WARNING line was printed to stdout.
    log_hit = any(
        r.levelno == logging.WARNING and "rubric_version mismatch" in r.getMessage()
        for r in caplog.records
    )
    stdout_hit = "rubric_version mismatch" in captured.out
    assert log_hit or stdout_hit, (
        "expected rubric_version mismatch WARNING in logs or stdout, "
        f"records={caplog.records!r} stdout={captured.out!r}"
    )


def test_corrupt_checkpoint_file_starts_fresh(tmp_path):
    path = tmp_path / "cp.json"
    path.write_text("{not valid", encoding="utf-8")
    cp = Checkpoint("mcp", path, rubric_version="1.aaa")
    completed, remaining = cp.load(["a", "b"])
    assert completed == []
    assert remaining == ["a", "b"]


# ------------------------------------------------------- quarantine filter


def test_quarantine_filter_drops_entries_from_remaining(tmp_path):
    fl = FailureLog(tmp_path / "fl.json", rubric_version="1.aaa")
    for _ in range(4):
        fl.record_failure("b", type_="mcp", error_kind="K", error_message="m")
    assert fl.is_quarantined("b") is True

    cp = Checkpoint("mcp", tmp_path / "cp.json", rubric_version="1.aaa")
    completed, remaining = cp.load(["a", "b", "c"], failure_log=fl)
    assert completed == []
    assert remaining == ["a", "c"]


# -------------------------------------------------------- sorted invariant


def test_sorted_invariant(tmp_path):
    cp = Checkpoint("mcp", tmp_path / "cp.json", rubric_version="1.aaa")
    cp.load(["c", "a", "b"])
    # remaining is sorted on load.
    assert cp.remaining_entry_ids == ["a", "b", "c"]

    cp.mark_completed("c")
    cp.mark_completed("a")
    cp.mark_completed("b")
    assert cp.completed_entry_ids == ["a", "b", "c"]
    assert cp.remaining_entry_ids == []


def test_flush_every_must_be_positive(tmp_path):
    with pytest.raises(ValueError):
        Checkpoint("mcp", tmp_path / "cp.json", rubric_version="1.aaa", flush_every=0)
    with pytest.raises(ValueError):
        Checkpoint("mcp", tmp_path / "cp.json", rubric_version="1.aaa", flush_every=-3)
