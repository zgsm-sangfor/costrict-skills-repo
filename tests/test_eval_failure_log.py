"""Tests for scripts.eval_failure_log — backoff, quarantine, atomic write, rubric reset."""
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import eval_failure_log  # noqa: E402
from eval_failure_log import (  # noqa: E402
    FailureLog,
    QUARANTINE_SENTINEL,
    QUARANTINE_THRESHOLD,
    SCHEMA_VERSION,
    _atomic_write_json,
    _parse_iso,
    compute_next_retry,
)


# ---------------------------------------------------------------- backoff


def test_first_failure_records_attempt_count_1_and_immediate_retry(tmp_path):
    log = FailureLog(tmp_path / "f.json", rubric_version="1.aaa")
    log.record_failure("x", type_="mcp", error_kind="K", error_message="msg")
    rec = log.failures["x"]
    assert rec.attempt_count == 1
    assert rec.first_failed_at == rec.last_failed_at
    # next_retry_after equals last_failed_at on attempt 1 (immediate retry).
    assert rec.next_retry_after == rec.last_failed_at


def test_second_failure_advances_to_7d_backoff(tmp_path):
    log = FailureLog(tmp_path / "f.json", rubric_version="1.aaa")
    log.record_failure("x", type_="mcp", error_kind="K", error_message="m")
    log.record_failure("x", type_="mcp", error_kind="K", error_message="m")
    rec = log.failures["x"]
    assert rec.attempt_count == 2
    next_dt = _parse_iso(rec.next_retry_after)
    last_dt = _parse_iso(rec.last_failed_at)
    delta = next_dt - last_dt
    # Allow a tiny tolerance because the two timestamps come from two
    # consecutive _utcnow() calls.
    assert timedelta(days=7) - timedelta(seconds=2) <= delta <= timedelta(days=7) + timedelta(seconds=2)


def test_third_failure_advances_to_28d_backoff(tmp_path):
    log = FailureLog(tmp_path / "f.json", rubric_version="1.aaa")
    for _ in range(3):
        log.record_failure("x", type_="mcp", error_kind="K", error_message="m")
    rec = log.failures["x"]
    assert rec.attempt_count == 3
    next_dt = _parse_iso(rec.next_retry_after)
    last_dt = _parse_iso(rec.last_failed_at)
    delta = next_dt - last_dt
    assert timedelta(days=28) - timedelta(seconds=2) <= delta <= timedelta(days=28) + timedelta(seconds=2)


def test_fourth_failure_quarantines(tmp_path):
    log = FailureLog(tmp_path / "f.json", rubric_version="1.aaa")
    for _ in range(4):
        log.record_failure("x", type_="mcp", error_kind="K", error_message="m")
    rec = log.failures["x"]
    assert rec.attempt_count == 4
    assert rec.next_retry_after == QUARANTINE_SENTINEL
    assert log.is_quarantined("x") is True


# ---------------------------------------------------------------- queries


def test_should_retry_now_false_when_quarantined(tmp_path):
    log = FailureLog(tmp_path / "f.json", rubric_version="1.aaa")
    for _ in range(QUARANTINE_THRESHOLD):
        log.record_failure("x", type_="mcp", error_kind="K", error_message="m")
    assert log.should_retry_now("x") is False


def test_should_retry_now_true_for_unknown_entry(tmp_path):
    log = FailureLog(tmp_path / "f.json", rubric_version="1.aaa")
    assert log.should_retry_now("never_seen") is True


def test_should_retry_now_respects_future_next_retry(tmp_path):
    log = FailureLog(tmp_path / "f.json", rubric_version="1.aaa")
    log.record_failure("x", type_="mcp", error_kind="K", error_message="m")
    log.record_failure("x", type_="mcp", error_kind="K", error_message="m")
    rec = log.failures["x"]
    next_dt = _parse_iso(rec.next_retry_after)

    just_before = next_dt - timedelta(seconds=1)
    just_after = next_dt + timedelta(seconds=1)

    assert log.should_retry_now("x", now=just_before) is False
    assert log.should_retry_now("x", now=just_after) is True


def test_record_success_removes_from_ledger(tmp_path):
    log = FailureLog(tmp_path / "f.json", rubric_version="1.aaa")
    log.record_failure("x", type_="mcp", error_kind="K", error_message="m")
    assert "x" in log.failures
    log.record_success("x")
    assert "x" not in log.failures
    # Idempotent: second call doesn't raise.
    log.record_success("x")
    assert "x" not in log.failures


# ---------------------------------------------------------------- persistence


def test_save_load_roundtrip(tmp_path):
    path = tmp_path / "f.json"
    log = FailureLog(path, rubric_version="1.aaa")
    log.record_failure("a", type_="mcp", error_kind="K", error_message="m")
    log.record_failure("b", type_="skill", error_kind="J", error_message="z")
    log.record_failure("b", type_="skill", error_kind="J", error_message="z")  # 2 attempts
    log.save()

    log2 = FailureLog(path, rubric_version="1.aaa")
    assert set(log2.failures.keys()) == {"a", "b"}
    assert log2.failures["a"].attempt_count == 1
    assert log2.failures["b"].attempt_count == 2
    assert log2.failures["b"].type == "skill"
    assert log2.failures["b"].last_error_kind == "J"


def test_atomic_write_uses_replace(tmp_path):
    path = tmp_path / "f.json"
    log = FailureLog(path, rubric_version="1.aaa")
    log.record_failure("a", type_="mcp", error_kind="K", error_message="m")
    log.save()
    assert path.exists()
    tmp = path.with_suffix(path.suffix + ".tmp")
    assert not tmp.exists(), f"tmp file should be cleaned up by os.replace, found {tmp}"

    # Schema sanity check on the persisted JSON.
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["rubric_version"] == "1.aaa"
    assert "updated_at" in payload
    assert "a" in payload["failures"]


def test_atomic_write_json_helper_direct(tmp_path):
    """Directly hit the atomic write helper to lock its contract."""
    path = tmp_path / "nested" / "out.json"
    _atomic_write_json(path, {"k": 1})
    assert path.exists()
    assert json.loads(path.read_text(encoding="utf-8")) == {"k": 1}
    assert not path.with_suffix(path.suffix + ".tmp").exists()


# ---------------------------------------------------------------- rubric reset


def test_rubric_version_mismatch_resets_failures(tmp_path, caplog):
    path = tmp_path / "f.json"
    log = FailureLog(path, rubric_version="1.aaa")
    log.record_failure("a", type_="mcp", error_kind="K", error_message="m")
    log.save()

    with caplog.at_level(logging.WARNING, logger="eval_failure_log"):
        log2 = FailureLog(path, rubric_version="2.bbb")
    assert log2.failures == {}
    # Look for the WARNING about a rubric mismatch.
    matching = [
        r for r in caplog.records
        if r.levelno == logging.WARNING and "ubric" in r.getMessage()
    ]
    assert matching, f"expected a WARNING about rubric mismatch, got {caplog.records}"


def test_corrupt_file_starts_fresh(tmp_path):
    path = tmp_path / "f.json"
    path.write_text("{not valid json", encoding="utf-8")
    log = FailureLog(path, rubric_version="1.aaa")
    assert log.failures == {}


def test_unexpected_shape_starts_fresh(tmp_path):
    path = tmp_path / "f.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    log = FailureLog(path, rubric_version="1.aaa")
    assert log.failures == {}


# ---------------------------------------------------------------- helper unit


def test_compute_next_retry_helper():
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    assert compute_next_retry(1, now) == now
    assert compute_next_retry(2, now) == now + timedelta(days=7)
    assert compute_next_retry(3, now) == now + timedelta(days=28)
    expected_sentinel = datetime(9999, 12, 31, 0, 0, 0, tzinfo=timezone.utc)
    assert compute_next_retry(4, now) == expected_sentinel
    assert compute_next_retry(99, now) == expected_sentinel
