"""Integration tests for eval_bridge._run_runner_with_telemetry.

Mocks an EvalRunner so failures, partial results, and exceptions are
exercised against real FailureLog + Checkpoint instances written to tmp_path.
"""
import os
import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import eval_bridge  # noqa: E402
from enrichment_checkpoint import Checkpoint  # noqa: E402
from eval_bridge import _run_runner_with_telemetry  # noqa: E402
from eval_failure_log import FailureLog  # noqa: E402


def _mock_item(eid):
    """Build a mock eval item with a stable .id attribute."""
    item = MagicMock()
    item.id = eid
    return item


def _mock_result(eid):
    """Build a mock EvalResult-like object that pydantic-style dumps."""
    r = MagicMock()
    r.model_dump.return_value = {"entry_id": eid}
    return r


# -----------------------------------------------------------------------
# 1. Per-chunk success path: clears ledger + fills checkpoint
# -----------------------------------------------------------------------


def test_per_chunk_success_records_to_checkpoint_and_clears_ledger(tmp_path):
    fl = FailureLog(tmp_path / "fl.json", rubric_version="1.aaa")
    cp = Checkpoint("mcp", tmp_path / "cp.json", rubric_version="1.aaa")

    ids = ["a", "b", "c"]
    cp.load(ids)
    # Pre-populate the ledger with one stale failure that should be cleared
    # on success.
    fl.record_failure("b", type_="mcp", error_kind="K", error_message="stale")
    assert "b" in fl.failures

    items = [_mock_item(i) for i in ids]
    runner = MagicMock()
    runner.run.return_value = [_mock_result(i) for i in ids]

    results = _run_runner_with_telemetry(
        runner=runner,
        eval_items=items,
        resource_type="mcp",
        failure_log=fl,
        checkpoint=cp,
        chunk_size=50,
    )

    assert len(results) == 3
    # All ids should now be marked completed in the checkpoint.
    assert sorted(cp.completed_entry_ids) == ["a", "b", "c"]
    assert cp.remaining_entry_ids == []
    # The stale failure on 'b' should have been cleared.
    assert "b" not in fl.failures


# -----------------------------------------------------------------------
# 2. Partial results: missing ids logged as EvalRunnerSkip
# -----------------------------------------------------------------------


def test_partial_chunk_skip_records_failure_for_missing_ids(tmp_path):
    fl = FailureLog(tmp_path / "fl.json", rubric_version="1.aaa")
    cp = Checkpoint("mcp", tmp_path / "cp.json", rubric_version="1.aaa")

    ids = ["a", "b", "c"]
    cp.load(ids)

    items = [_mock_item(i) for i in ids]
    # Runner returns only "a" and "c" — "b" is silently skipped.
    runner = MagicMock()
    runner.run.return_value = [_mock_result("a"), _mock_result("c")]

    _run_runner_with_telemetry(
        runner=runner,
        eval_items=items,
        resource_type="mcp",
        failure_log=fl,
        checkpoint=cp,
        chunk_size=50,
    )

    # "b" should be in the ledger as EvalRunnerSkip with attempt_count 1.
    assert "b" in fl.failures
    assert fl.failures["b"].attempt_count == 1
    assert fl.failures["b"].last_error_kind == "EvalRunnerSkip"
    assert fl.failures["b"].type == "mcp"
    # "a" and "c" should be in the checkpoint.
    assert sorted(cp.completed_entry_ids) == ["a", "c"]


# -----------------------------------------------------------------------
# 3. Whole-chunk exception: every id recorded ONCE (not double-counted)
# -----------------------------------------------------------------------


def test_chunk_exception_records_failure_for_all_inputs_only_once(tmp_path):
    fl = FailureLog(tmp_path / "fl.json", rubric_version="1.aaa")
    cp = Checkpoint("mcp", tmp_path / "cp.json", rubric_version="1.aaa")

    ids = ["a", "b", "c"]
    cp.load(ids)

    items = [_mock_item(i) for i in ids]
    runner = MagicMock()
    runner.run.side_effect = RuntimeError("LLM down")

    _run_runner_with_telemetry(
        runner=runner,
        eval_items=items,
        resource_type="mcp",
        failure_log=fl,
        checkpoint=cp,
        chunk_size=50,
    )

    # All three should be in the ledger with attempt_count exactly 1
    # (regression guard for the chunk-1C double-count fix).
    for eid in ids:
        assert eid in fl.failures, f"missing ledger entry for {eid}"
        rec = fl.failures[eid]
        assert rec.attempt_count == 1, (
            f"{eid} attempt_count={rec.attempt_count}, expected 1 "
            "(double-count regression?)"
        )
        assert rec.last_error_kind == "EvalRunnerException"
        assert "RuntimeError" in rec.last_error_message
        assert "LLM down" in rec.last_error_message
    # No checkpoint progress recorded for a fully-failed chunk.
    assert cp.completed_entry_ids == []


# -----------------------------------------------------------------------
# 4. Progress lines printed at chunk boundaries
# -----------------------------------------------------------------------


def test_progress_lines_printed_with_chunk_boundary(tmp_path, capsys):
    fl = FailureLog(tmp_path / "fl.json", rubric_version="1.aaa")
    cp = Checkpoint("mcp", tmp_path / "cp.json", rubric_version="1.aaa")

    ids = [f"id-{i:03d}" for i in range(100)]
    cp.load(ids)

    items = [_mock_item(i) for i in ids]
    runner = MagicMock()
    runner.run.side_effect = lambda batch: [
        _mock_result(getattr(b, "id")) for b in batch
    ]

    _run_runner_with_telemetry(
        runner=runner,
        eval_items=items,
        resource_type="mcp",
        failure_log=fl,
        checkpoint=cp,
        chunk_size=50,
    )

    captured = capsys.readouterr()
    out = captured.out
    assert "[type=mcp] starting:" in out
    assert "progress: 50/100" in out
    assert "progress: 100/100" in out
    assert "[type=mcp] done:" in out


# -----------------------------------------------------------------------
# 5. None failure_log + None checkpoint: still works, returns results
# -----------------------------------------------------------------------


def test_no_failure_log_no_checkpoint_works(tmp_path):
    ids = ["a", "b"]
    items = [_mock_item(i) for i in ids]
    runner = MagicMock()
    runner.run.return_value = [_mock_result(i) for i in ids]

    results = _run_runner_with_telemetry(
        runner=runner,
        eval_items=items,
        resource_type="mcp",
        failure_log=None,
        checkpoint=None,
        chunk_size=50,
    )

    assert len(results) == 2


# -----------------------------------------------------------------------
# 6. Empty input list: no exception, prints starting + done
# -----------------------------------------------------------------------


def test_empty_input_returns_immediately(tmp_path, capsys):
    fl = FailureLog(tmp_path / "fl.json", rubric_version="1.aaa")
    cp = Checkpoint("mcp", tmp_path / "cp.json", rubric_version="1.aaa")
    cp.load([])

    runner = MagicMock()
    results = _run_runner_with_telemetry(
        runner=runner,
        eval_items=[],
        resource_type="mcp",
        failure_log=fl,
        checkpoint=cp,
        chunk_size=50,
    )
    assert results == []
    runner.run.assert_not_called()

    out = capsys.readouterr().out
    assert "starting: 0 to_evaluate" in out
    assert "done:" in out
