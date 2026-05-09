"""Per-type enrichment checkpoint with 50-entry granularity atomic flush.

This module provides the :class:`Checkpoint` class used by the enrichment
pipeline to record evaluation progress for each resource type. Checkpoint
files live at ``catalog/maintenance/checkpoints/<type>.json`` and are
tracked in git so that a CI run interrupted mid-evaluation can resume from
the last committed boundary on the next invocation.

Design (see ``openspec/changes/harden-merge-pipeline/design.md``):

* Each cell (one resource type) owns a single checkpoint file.
* Writes are atomic (tmp file + ``fsync`` + ``os.replace``) and are
  triggered automatically every ``flush_every`` (default ``50``) successful
  ``mark_completed`` calls.
* Startup logic compares the on-disk ``rubric_version`` against the current
  task's rubric: a mismatch discards the checkpoint and restarts from
  scratch. A match resumes by skipping ``completed_entry_ids``.
* Quarantined entries (those for which :class:`scripts.eval_failure_log.FailureLog`
  reports ``is_quarantined``) are dropped from ``remaining_entry_ids`` at
  load time, so the cell never re-attempts them within the run.

The on-disk schema is::

    {
      "type": "<resource type>",
      "rubric_version": "<major>.<sha8>",
      "started_at": "<ISO 8601 UTC>",
      "last_committed_at": "<ISO 8601 UTC>",
      "completed_count": <int>,
      "completed_entry_ids": ["..."],   // sorted
      "remaining_entry_ids": ["..."]    // sorted
    }
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from scripts.eval_failure_log import _atomic_write_json, _iso, _utcnow

if TYPE_CHECKING:  # pragma: no cover - typing only
    from scripts.eval_failure_log import FailureLog

logger = logging.getLogger(__name__)

DEFAULT_FLUSH_EVERY = 50


class Checkpoint:
    """Per-type evaluation checkpoint with periodic atomic flush.

    Typical usage inside an enrichment cell::

        cp = Checkpoint(type_="mcp", path=path, rubric_version=rv)
        completed, remaining = cp.load(all_entry_ids, failure_log=log)
        for entry_id in cp.pop_remaining():
            evaluate(entry_id)
            cp.mark_completed(entry_id)
        cp.flush()
    """

    def __init__(
        self,
        type_: str,
        path: Path,
        rubric_version: str,
        flush_every: int = DEFAULT_FLUSH_EVERY,
    ) -> None:
        if flush_every <= 0:
            raise ValueError(f"flush_every must be > 0, got {flush_every!r}")
        self.type: str = str(type_)
        self.path: Path = Path(path)
        # rubric_version is an opaque string (e.g. "2.85974ec3"); never coerce to int.
        self.rubric_version: str = str(rubric_version)
        self.flush_every: int = int(flush_every)

        now_iso = _iso(_utcnow())
        self.started_at: str = now_iso
        self.last_committed_at: str = now_iso
        self.completed_entry_ids: list[str] = []
        self.remaining_entry_ids: list[str] = []
        self._since_last_flush: int = 0
        self._loaded: bool = False

    # ------------------------------------------------------------------ load
    def load(
        self,
        all_entry_ids: list[str],
        failure_log: "FailureLog | None" = None,
    ) -> tuple[list[str], list[str]]:
        """Read checkpoint state and reconcile against the current entry set.

        Behavior:
        * If the file is missing, corrupt, or its ``rubric_version`` does not
          match the current task, treat as a fresh run (empty completed,
          remaining = all_entry_ids).
        * If the rubric matches, keep ``completed_entry_ids`` (intersected with
          ``all_entry_ids`` to drop entries no longer in the upstream set) and
          recompute ``remaining_entry_ids = sorted(set(all_entry_ids) - set(completed))``.
        * If ``failure_log`` is provided, drop quarantined entries from
          ``remaining_entry_ids``.

        Returns ``(completed_entry_ids, remaining_entry_ids)`` as sorted lists.
        """
        all_ids = sorted({str(eid) for eid in all_entry_ids})
        all_ids_set = set(all_ids)

        loaded_state = self._read_from_disk()

        if loaded_state is None:
            # Fresh start (no file, corrupt file, or rubric mismatch).
            completed: list[str] = []
            now_iso = _iso(_utcnow())
            self.started_at = now_iso
            self.last_committed_at = now_iso
        else:
            disk_completed = loaded_state.get("completed_entry_ids") or []
            # Drop completed entries that no longer exist in the upstream set.
            completed = sorted(
                {str(eid) for eid in disk_completed if str(eid) in all_ids_set}
            )
            self.started_at = str(
                loaded_state.get("started_at") or _iso(_utcnow())
            )
            self.last_committed_at = str(
                loaded_state.get("last_committed_at") or self.started_at
            )
            logger.info(
                "[type=%s] resuming from checkpoint: completed=%d, remaining=%d",
                self.type,
                len(completed),
                len(all_ids_set - set(completed)),
            )
            # Mirror to stdout per spec (cell startup banner).
            print(
                f"[type={self.type}] resuming from checkpoint: "
                f"completed={len(completed)}, "
                f"remaining={len(all_ids_set - set(completed))}"
            )

        remaining_set = all_ids_set - set(completed)

        if failure_log is not None:
            quarantined = {
                eid for eid in remaining_set if failure_log.is_quarantined(eid)
            }
            if quarantined:
                logger.info(
                    "[type=%s] dropping %d quarantined entries from remaining",
                    self.type,
                    len(quarantined),
                )
                remaining_set -= quarantined

        remaining = sorted(remaining_set)

        self.completed_entry_ids = completed
        self.remaining_entry_ids = remaining
        self._since_last_flush = 0
        self._loaded = True

        return list(self.completed_entry_ids), list(self.remaining_entry_ids)

    # ------------------------------------------------------------------- read
    def _read_from_disk(self) -> dict[str, Any] | None:
        """Return raw checkpoint dict or ``None`` if unusable.

        ``None`` means the caller should treat this as a fresh run. Reasons:
        file missing, JSON corrupt, unexpected shape, or rubric mismatch.
        """
        if not self.path.exists():
            return None

        try:
            with open(self.path, encoding="utf-8") as fh:
                raw = json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning(
                "Checkpoint %s is corrupt (%s); starting fresh.",
                self.path,
                exc,
            )
            return None

        if not isinstance(raw, dict):
            logger.warning(
                "Checkpoint %s has unexpected shape; starting fresh.",
                self.path,
            )
            return None

        recorded_rubric = raw.get("rubric_version")
        recorded_rubric_str = (
            str(recorded_rubric) if recorded_rubric is not None else ""
        )
        if recorded_rubric_str != self.rubric_version:
            logger.warning(
                "[type=%s] checkpoint rubric_version mismatch (%s vs %s), restarting",
                self.type,
                recorded_rubric_str,
                self.rubric_version,
            )
            print(
                f"WARNING: [type={self.type}] checkpoint rubric_version mismatch "
                f"({recorded_rubric_str} vs {self.rubric_version}), restarting"
            )
            return None

        return raw

    # ------------------------------------------------------------------ save
    def save(self) -> None:
        """Atomically persist the checkpoint and refresh ``last_committed_at``."""
        self.last_committed_at = _iso(_utcnow())
        data = {
            "type": self.type,
            "rubric_version": self.rubric_version,
            "started_at": self.started_at,
            "last_committed_at": self.last_committed_at,
            "completed_count": len(self.completed_entry_ids),
            "completed_entry_ids": list(self.completed_entry_ids),
            "remaining_entry_ids": list(self.remaining_entry_ids),
        }
        _atomic_write_json(self.path, data)
        self._since_last_flush = 0

    def flush(self) -> None:
        """Force an unconditional save (used on cell exit / wall-clock budget)."""
        self.save()

    # ------------------------------------------------------------- mutations
    def mark_completed(self, entry_id: str) -> None:
        """Move ``entry_id`` from remaining to completed; flush every N calls.

        Idempotent: if the entry is already completed or was never tracked,
        the call is a no-op (debug-logged).
        """
        eid = str(entry_id)
        if eid in self.completed_entry_ids:
            logger.debug(
                "[type=%s] mark_completed: %s already completed; ignoring.",
                self.type,
                eid,
            )
            return
        if eid not in self.remaining_entry_ids:
            logger.debug(
                "[type=%s] mark_completed: %s not tracked; ignoring.",
                self.type,
                eid,
            )
            return

        self.remaining_entry_ids.remove(eid)
        self.completed_entry_ids.append(eid)
        # Maintain sorted invariant on both lists.
        self.completed_entry_ids.sort()
        # remaining_entry_ids stays sorted because we removed in place.

        self._since_last_flush += 1
        if self._since_last_flush >= self.flush_every:
            self.save()

    def pop_remaining(self) -> list[str]:
        """Return a snapshot copy of the remaining entry ids for iteration."""
        return list(self.remaining_entry_ids)
