"""Persistent evaluation failure ledger for the merge pipeline.

This module maintains a per-entry evaluation failure ledger
(`catalog/maintenance/eval_failures.json`) that survives across CI runs and
is tracked in git for auditability. The ledger is keyed by `entry_id` for
O(1) lookup and uses an exponential backoff schedule before quarantining a
chronically failing entry.

Backoff schedule:
    attempt_count = 1  -> retry immediately (next_retry_after = now)
    attempt_count = 2  -> retry after 7 days
    attempt_count = 3  -> retry after 28 days
    attempt_count >= 4 -> quarantine (next_retry_after = 9999-12-31)

When the current task's ``rubric_version`` differs from the value recorded
in the ledger, the entire ``failures`` dict is reset on next read, and the
ledger's ``rubric_version`` is bumped to match. This prevents stale failures
from blocking entries after a rubric upgrade.

CLI:
    python -m scripts.eval_failure_log --inspect [--path PATH] [--rubric-version N]

The `--inspect` subcommand renders a markdown table to stdout, suitable for
inclusion in GitHub Actions step summaries.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
QUARANTINE_THRESHOLD = 4
QUARANTINE_SENTINEL = "9999-12-31T00:00:00+00:00"
DEFAULT_LEDGER_PATH = Path("catalog/maintenance/eval_failures.json")


def _utcnow() -> datetime:
    """Return the current time as a timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    """Format a datetime as an ISO 8601 string in UTC."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _parse_iso(value: str) -> datetime:
    """Parse an ISO 8601 string into a timezone-aware UTC datetime."""
    # Tolerate trailing "Z" which fromisoformat handles natively in 3.11+,
    # but normalize defensively for older interpreters too.
    s = value.replace("Z", "+00:00") if value.endswith("Z") else value
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def compute_next_retry(attempt_count: int, now: datetime) -> datetime:
    """Compute next_retry_after based on attempt_count and current time.

    1 -> now (immediate retry)
    2 -> now + 7 days
    3 -> now + 28 days
    >=4 -> 9999-12-31T00:00:00+00:00 (quarantine sentinel)
    """
    if attempt_count <= 1:
        return now
    if attempt_count == 2:
        return now + timedelta(days=7)
    if attempt_count == 3:
        return now + timedelta(days=28)
    return datetime(9999, 12, 31, 0, 0, 0, tzinfo=timezone.utc)


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    """Write JSON to ``path`` atomically via a tmp file + fsync + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    payload = json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True)
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(payload)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


@dataclass
class FailureRecord:
    """In-memory representation of a single failure ledger entry."""

    type: str
    first_failed_at: str
    last_failed_at: str
    attempt_count: int
    last_error_kind: str
    last_error_message: str
    next_retry_after: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "first_failed_at": self.first_failed_at,
            "last_failed_at": self.last_failed_at,
            "attempt_count": self.attempt_count,
            "last_error_kind": self.last_error_kind,
            "last_error_message": self.last_error_message,
            "next_retry_after": self.next_retry_after,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> FailureRecord:
        return cls(
            type=str(raw.get("type", "")),
            first_failed_at=str(raw.get("first_failed_at", "")),
            last_failed_at=str(raw.get("last_failed_at", "")),
            attempt_count=int(raw.get("attempt_count", 0)),
            last_error_kind=str(raw.get("last_error_kind", "")),
            last_error_message=str(raw.get("last_error_message", "")),
            next_retry_after=str(raw.get("next_retry_after", "")),
        )


class FailureLog:
    """Persistent failure ledger keyed by entry_id."""

    def __init__(self, path: Path, rubric_version: str) -> None:
        self.path = Path(path)
        # rubric_version is treated as an opaque string identifier.
        # The runtime value from ai-resource-eval is "<major>.<sha8>" (e.g. "2.85974ec3").
        self.rubric_version = str(rubric_version)
        self.failures: dict[str, FailureRecord] = {}
        self._loaded_rubric_version: str = self.rubric_version
        self._updated_at: str = _iso(_utcnow())
        self.load()

    # ------------------------------------------------------------------ load
    def load(self) -> None:
        """Read the ledger from disk; reset on rubric mismatch or corruption."""
        if not self.path.exists():
            self.failures = {}
            self._loaded_rubric_version = self.rubric_version
            return

        try:
            with open(self.path, encoding="utf-8") as fh:
                raw = json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning(
                "Failure ledger %s is corrupt (%s); starting fresh.",
                self.path,
                exc,
            )
            self.failures = {}
            self._loaded_rubric_version = self.rubric_version
            return

        if not isinstance(raw, dict):
            logger.warning(
                "Failure ledger %s has unexpected shape; starting fresh.",
                self.path,
            )
            self.failures = {}
            self._loaded_rubric_version = self.rubric_version
            return

        recorded_rubric = raw.get("rubric_version")
        recorded_rubric_str = (
            str(recorded_rubric) if recorded_rubric is not None else self.rubric_version
        )

        self._updated_at = str(raw.get("updated_at", _iso(_utcnow())))

        failures_raw = raw.get("failures", {})
        if not isinstance(failures_raw, dict):
            failures_raw = {}

        if recorded_rubric_str != self.rubric_version:
            logger.warning(
                "Rubric version mismatch in %s (ledger=%s, current=%s); "
                "resetting failures.",
                self.path,
                recorded_rubric_str,
                self.rubric_version,
            )
            self.failures = {}
            self._loaded_rubric_version = self.rubric_version
            return

        self.failures = {
            entry_id: FailureRecord.from_dict(rec)
            for entry_id, rec in failures_raw.items()
            if isinstance(rec, dict)
        }
        self._loaded_rubric_version = recorded_rubric_str

    # ------------------------------------------------------------------ save
    def save(self) -> None:
        """Atomically persist the ledger to disk with a fresh updated_at."""
        self._updated_at = _iso(_utcnow())
        data = {
            "schema_version": SCHEMA_VERSION,
            "rubric_version": self.rubric_version,
            "updated_at": self._updated_at,
            "failures": {
                entry_id: rec.to_dict() for entry_id, rec in sorted(self.failures.items())
            },
        }
        _atomic_write_json(self.path, data)

    # ---------------------------------------------------------------- record
    def record_failure(
        self,
        entry_id: str,
        type_: str,
        error_kind: str,
        error_message: str,
    ) -> None:
        """Register a failure for entry_id, advancing attempt_count + backoff."""
        now = _utcnow()
        now_iso = _iso(now)
        existing = self.failures.get(entry_id)
        if existing is None:
            attempt_count = 1
            first_failed_at = now_iso
        else:
            attempt_count = existing.attempt_count + 1
            first_failed_at = existing.first_failed_at or now_iso

        next_retry_dt = compute_next_retry(attempt_count, now)
        next_retry_iso = (
            QUARANTINE_SENTINEL
            if attempt_count >= QUARANTINE_THRESHOLD
            else _iso(next_retry_dt)
        )

        self.failures[entry_id] = FailureRecord(
            type=type_,
            first_failed_at=first_failed_at,
            last_failed_at=now_iso,
            attempt_count=attempt_count,
            last_error_kind=error_kind,
            last_error_message=error_message,
            next_retry_after=next_retry_iso,
        )

    def record_success(self, entry_id: str) -> None:
        """Remove entry_id from the ledger if present."""
        self.failures.pop(entry_id, None)

    # ----------------------------------------------------------------- query
    def is_quarantined(self, entry_id: str) -> bool:
        """Return True if the entry has reached the quarantine threshold."""
        rec = self.failures.get(entry_id)
        if rec is None:
            return False
        return rec.attempt_count >= QUARANTINE_THRESHOLD

    def should_retry_now(
        self, entry_id: str, now: datetime | None = None
    ) -> bool:
        """Return True if the entry is eligible for evaluation right now."""
        rec = self.failures.get(entry_id)
        if rec is None:
            return True
        if rec.attempt_count >= QUARANTINE_THRESHOLD:
            return False
        if not rec.next_retry_after:
            return True
        try:
            next_retry = _parse_iso(rec.next_retry_after)
        except ValueError:
            logger.warning(
                "Invalid next_retry_after for %s: %r; allowing retry.",
                entry_id,
                rec.next_retry_after,
            )
            return True
        current = now if now is not None else _utcnow()
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        return current >= next_retry


# ---------------------------------------------------------------------- CLI


def _render_markdown_table(log: FailureLog) -> str:
    """Render the ledger as a GitHub-flavored markdown table."""
    if not log.failures:
        return "No failures recorded."

    headers = [
        "entry_id",
        "type",
        "attempt_count",
        "first_failed_at",
        "last_failed_at",
        "last_error_kind",
        "next_retry_after",
        "quarantined",
    ]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for entry_id in sorted(log.failures):
        rec = log.failures[entry_id]
        quarantined = "yes" if rec.attempt_count >= QUARANTINE_THRESHOLD else "no"
        row = [
            entry_id,
            rec.type,
            str(rec.attempt_count),
            rec.first_failed_at,
            rec.last_failed_at,
            rec.last_error_kind,
            rec.next_retry_after,
            quarantined,
        ]
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def _peek_rubric_version(path: Path, fallback: str = "") -> str:
    """Read rubric_version from the ledger without triggering a reset."""
    if not path.exists():
        return fallback
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except (json.JSONDecodeError, OSError):
        return fallback
    if not isinstance(raw, dict):
        return fallback
    value = raw.get("rubric_version", fallback)
    return str(value) if value is not None else fallback


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scripts.eval_failure_log",
        description="Inspect / manage the evaluation failure ledger.",
    )
    parser.add_argument(
        "--inspect",
        action="store_true",
        help="Render the ledger as a markdown table to stdout.",
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=DEFAULT_LEDGER_PATH,
        help=f"Path to ledger file (default: {DEFAULT_LEDGER_PATH}).",
    )
    parser.add_argument(
        "--rubric-version",
        type=str,
        default=None,
        help="Current rubric version (opaque string, e.g. '2.85974ec3'). "
        "When inspecting, defaults to the value stored in the ledger (no reset).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    if not args.inspect:
        parser.print_help()
        return 0

    rubric_version = (
        args.rubric_version
        if args.rubric_version is not None
        else _peek_rubric_version(args.path, fallback="")
    )
    log = FailureLog(args.path, rubric_version=rubric_version)
    print(_render_markdown_table(log))
    return 0


if __name__ == "__main__":
    sys.exit(main())
