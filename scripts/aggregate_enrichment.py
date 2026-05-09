"""Aggregate per-type partial enrichment artifacts back into the main catalog.

This script is the **publish-time** counterpart to ``run_enrichment.py``. It is
invoked once after every per-type enrichment cell has finished (or failed) in
the ``sync`` / ``sync-test`` workflows. Its job is to take the data-layer
catalog produced by ``merge_index.py --skip-enrichment`` and stitch the
``evaluation`` field back onto every entry, with a graceful fallback chain so
that a single cell failure never blocks the full publish.

Fallback priority (per entry):

1. **New evaluation** from ``tests/_enrich_output/<type>.json`` (current run).
2. **Old evaluation** from the previous ``catalog/index.json`` at git HEAD.
3. **Health-only synthesis** — when neither of the above is available, fabricate
   a minimal evaluation dict from ``entry["health"]`` so the row remains
   publishable. ``decision`` defaults to ``"review"``.

The aggregate step is intentionally tolerant: missing partial files, missing
git history, an empty old catalog — none of these abort publish. Each
condition is recorded in the per-type markdown summary written to
``$GITHUB_STEP_SUMMARY``.

See ``openspec/changes/harden-merge-pipeline/specs/merge-pipeline-resilience/
spec.md`` for the full requirement.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Sibling-import pattern: works when invoked as ``python scripts/aggregate_enrichment.py``
# from the repo root (puts ``scripts/`` on sys.path).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils import load_index, save_index  # noqa: E402

# eval_bridge owns the schema-shaping logic that turns a raw run_eval result
# into the flattened catalog evaluation (plus enrichment / mcp_installability /
# health side-effects). Aggregating the artifact MUST go through this helper —
# the partial artifact stores the raw EvalResult dump, not the flat schema.
try:
    from eval_bridge import map_result_to_entry  # noqa: E402
except ImportError:  # pragma: no cover - aggregate is rarely used without eval_bridge
    map_result_to_entry = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

DEFAULT_TYPES = ("mcp", "skill", "rule", "prompt", "plugin")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utcnow_iso() -> str:
    """Return current UTC time as an ISO 8601 string (Z suffix normalized)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


_SEARCH_INDEX_FIELDS = (
    "id", "name", "type", "category", "tags", "tech_stack",
    "stars", "description", "description_zh", "source_url",
    "final_score", "decision", "freshness_label",
)


def _regenerate_search_index(entries: list[dict[str, Any]], catalog_path: Path) -> None:
    """Write the lightweight search-index.json next to the catalog.

    Mirrors the emission in ``merge_index.py`` so the published search index
    reflects the post-aggregate catalog (with restored final_score / decision)
    instead of the data-only placeholder produced by ``--skip-enrichment``.
    """
    search_entries: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        se: dict[str, Any] = {k: entry.get(k) for k in _SEARCH_INDEX_FIELDS}
        install_obj = entry.get("install")
        se["install_method"] = (
            install_obj.get("method") if isinstance(install_obj, dict) else None
        )
        parts = [
            entry.get("name", ""),
            entry.get("description", ""),
            entry.get("description_zh", ""),
            " ".join(entry.get("tags") or []),
            " ".join(entry.get("tech_stack") or []),
            " ".join(entry.get("search_terms") or []),
        ]
        se["search_text"] = " ".join(p for p in parts if p)
        search_entries.append(se)

    search_path = catalog_path.parent / "search-index.json"
    with open(search_path, "w", encoding="utf-8") as fh:
        json.dump(search_entries, fh, ensure_ascii=False, separators=(",", ":"))


def _load_old_catalog_from_git(catalog_path: str) -> list[dict[str, Any]]:
    """Read previous ``catalog/index.json`` content from ``git show HEAD:<path>``.

    Returns a list of entries, or empty list when:
    - git is unavailable
    - the file did not exist at HEAD
    - the JSON failed to parse
    - the working dir is not a git repo

    The function never raises — every failure is logged and treated as
    "no historical data available", which forces the health-only path.
    """
    try:
        result = subprocess.run(
            ["git", "show", f"HEAD:{catalog_path}"],
            capture_output=True,
            text=True,
            check=False,
        )
    except (FileNotFoundError, OSError) as exc:
        logger.warning("git show HEAD:%s failed: %s", catalog_path, exc)
        return []

    if result.returncode != 0:
        logger.info(
            "git show HEAD:%s returned %d (no history?); falling back to empty old catalog",
            catalog_path,
            result.returncode,
        )
        return []

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        logger.warning("Failed to parse old catalog from git HEAD: %s", exc)
        return []

    if not isinstance(data, list):
        logger.warning("Old catalog from git HEAD has unexpected shape; ignoring")
        return []
    return data


def _build_old_eval_lookup(old_entries: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Build ``{entry_id: evaluation_dict}`` from previous catalog entries."""
    lookup: dict[str, dict[str, Any]] = {}
    for entry in old_entries:
        if not isinstance(entry, dict):
            continue
        eid = entry.get("id")
        if not eid:
            continue
        ev = entry.get("evaluation")
        if isinstance(ev, dict) and ev:
            lookup[str(eid)] = ev
    return lookup


def _load_partial_artifact(path: Path) -> dict[str, Any] | None:
    """Load a single ``<type>.json`` artifact written by ``run_enrichment.py``.

    Returns the parsed dict, or ``None`` if the file is missing/unparseable
    (caller treats both as "cell failed").
    """
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to load partial artifact %s: %s", path, exc)
        return None
    if not isinstance(data, dict):
        logger.warning("Partial artifact %s has unexpected shape; ignoring", path)
        return None
    return data


def _build_new_eval_lookup(artifact: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Extract ``{entry_id: evaluation}`` from a partial artifact's ``succeeded`` list."""
    if not artifact:
        return {}
    succeeded = artifact.get("succeeded") or []
    if not isinstance(succeeded, list):
        return {}
    lookup: dict[str, dict[str, Any]] = {}
    for item in succeeded:
        if not isinstance(item, dict):
            continue
        eid = item.get("entry_id")
        ev = item.get("evaluation")
        if eid and isinstance(ev, dict):
            lookup[str(eid)] = ev
    return lookup


def _synthesize_health_only(entry: dict[str, Any]) -> dict[str, Any]:
    """Fabricate a minimal evaluation dict from ``entry["health"]``.

    Used as last-resort fallback when an entry is brand-new (no old eval) and
    the current run's cell failed (no new eval). The synthesized record is
    flagged with ``evaluation_mode = "health_only_synthesized"`` so downstream
    readers can distinguish it from a real LLM-derived eval.
    """
    health = entry.get("health") or {}
    health_score = 0
    if isinstance(health, dict):
        raw = health.get("score", 0)
        try:
            health_score = float(raw) if raw is not None else 0
        except (TypeError, ValueError):
            health_score = 0
    return {
        "final_score": health_score,
        "decision": "review",
        "evaluation_mode": "health_only_synthesized",
        "evaluated_at": _utcnow_iso(),
    }


# ---------------------------------------------------------------------------
# Step summary
# ---------------------------------------------------------------------------


def _format_step_summary(per_type_stats: dict[str, dict[str, Any]], types: list[str]) -> str:
    """Render the markdown table for ``$GITHUB_STEP_SUMMARY``."""
    lines = [
        "## Aggregate enrichment summary",
        "",
        "| type | succeeded | failed | quarantined | fallback (old + synth) | cell status |",
        "|------|-----------|--------|-------------|------------------------|-------------|",
    ]
    for t in types:
        s = per_type_stats.get(t, {})
        succeeded = s.get("succeeded", 0)
        failed = s.get("failed", 0)
        quarantined = s.get("quarantined", 0)
        old = s.get("fallback_old", 0)
        synth = s.get("fallback_synth", 0)
        fallback_total = old + synth
        status = s.get("cell_status", "failed")
        fallback_cell = f"{fallback_total} ({old} + {synth})"
        lines.append(
            f"| {t} | {succeeded} | {failed} | {quarantined} | {fallback_cell} | {status} |"
        )
    lines.append("")
    return "\n".join(lines)


def _emit_step_summary(text: str, step_summary_path: str | None) -> None:
    """Append ``text`` to ``$GITHUB_STEP_SUMMARY`` (or print to stdout)."""
    target = step_summary_path or os.environ.get("GITHUB_STEP_SUMMARY")
    if not target:
        print(text)
        return
    try:
        target_path = Path(target)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with target_path.open("a", encoding="utf-8") as f:
            f.write(text)
            if not text.endswith("\n"):
                f.write("\n")
    except OSError as exc:
        logger.warning("Failed to write step summary to %s: %s", target, exc)
        print(text)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scripts.aggregate_enrichment",
        description=(
            "Stitch per-type partial enrichment artifacts back onto the main "
            "catalog. Falls back to old evaluation (git HEAD) or health-only "
            "synthesis when a cell did not produce results."
        ),
    )
    parser.add_argument(
        "--catalog",
        type=Path,
        default=Path("catalog/index.json"),
        help="Catalog index path (input). Default: catalog/index.json.",
    )
    parser.add_argument(
        "--partial-dir",
        type=Path,
        default=Path("tests/_enrich_output"),
        help="Directory containing per-type partial artifacts named <type>.json. "
        "Default: tests/_enrich_output.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output catalog path. Default: same as --catalog (in-place overwrite).",
    )
    parser.add_argument(
        "--types",
        type=str,
        default=",".join(DEFAULT_TYPES),
        help="Comma-separated resource types to aggregate. "
        f"Default: {','.join(DEFAULT_TYPES)}.",
    )
    parser.add_argument(
        "--step-summary",
        type=str,
        default=None,
        help="Path for markdown step summary. Default: $GITHUB_STEP_SUMMARY env, "
        "else stdout.",
    )
    return parser


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    types = [t.strip() for t in args.types.split(",") if t.strip()]
    catalog_path = str(args.catalog)
    output_path = str(args.output) if args.output is not None else catalog_path
    partial_dir = Path(args.partial_dir)

    # ---- Load current (data-layer) catalog ------------------------------------
    entries = load_index(catalog_path)
    if not isinstance(entries, list):
        logger.warning("Catalog %s is not a list; aborting aggregate", catalog_path)
        return 0

    # ---- Build old evaluation lookup from git HEAD ----------------------------
    old_entries = _load_old_catalog_from_git(catalog_path)
    old_eval_by_id = _build_old_eval_lookup(old_entries)
    logger.info(
        "Loaded %d old evaluations from git HEAD:%s", len(old_eval_by_id), catalog_path
    )

    # ---- Load each type's partial artifact ------------------------------------
    new_eval_by_type: dict[str, dict[str, dict[str, Any]]] = {}
    artifact_present_by_type: dict[str, bool] = {}
    quarantined_by_type: dict[str, int] = {}
    failed_by_type: dict[str, int] = {}

    for t in types:
        artifact_path = partial_dir / f"{t}.json"
        artifact = _load_partial_artifact(artifact_path)
        artifact_present_by_type[t] = artifact is not None
        new_eval_by_type[t] = _build_new_eval_lookup(artifact)
        if artifact:
            sq = artifact.get("skipped_quarantined") or []
            fl = artifact.get("failed") or []
            quarantined_by_type[t] = len(sq) if isinstance(sq, list) else 0
            failed_by_type[t] = len(fl) if isinstance(fl, list) else 0
        else:
            quarantined_by_type[t] = 0
            failed_by_type[t] = 0

    # ---- Apply fallback chain to every entry ----------------------------------
    per_type_stats: dict[str, dict[str, Any]] = {
        t: {
            "succeeded": 0,
            "failed": failed_by_type.get(t, 0),
            "quarantined": quarantined_by_type.get(t, 0),
            "fallback_old": 0,
            "fallback_synth": 0,
            "cell_status": "failed" if not artifact_present_by_type.get(t) else "ok",
        }
        for t in types
    }

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        eid = entry.get("id")
        t = entry.get("type")
        if not eid or not t:
            continue
        eid_str = str(eid)

        # Ensure stat bucket exists (entries with unexpected types still get a row).
        if t not in per_type_stats:
            per_type_stats[t] = {
                "succeeded": 0,
                "failed": 0,
                "quarantined": 0,
                "fallback_old": 0,
                "fallback_synth": 0,
                "cell_status": "failed",
            }

        new_lookup = new_eval_by_type.get(t, {})
        if eid_str in new_lookup:
            # The partial artifact stores the raw EvalResult dict; route it
            # through map_result_to_entry so the catalog gets the flattened
            # evaluation + enrichment / mcp_installability / health side-effects
            # that frontend and downstream consumers expect.
            if map_result_to_entry is not None:
                map_result_to_entry(entry, new_lookup[eid_str])
            else:
                entry["evaluation"] = new_lookup[eid_str]
            per_type_stats[t]["succeeded"] += 1
        elif eid_str in old_eval_by_id and old_eval_by_id[eid_str]:
            # Old catalog evaluation is already in flattened form (last run's
            # aggregate output), so assign directly.
            entry["evaluation"] = old_eval_by_id[eid_str]
            per_type_stats[t]["fallback_old"] += 1
        else:
            entry["evaluation"] = _synthesize_health_only(entry)
            per_type_stats[t]["fallback_synth"] += 1

        # Promote scoring fields to top level for search/browse/recommend
        # readers — mirror what merge_index does in the non-skip path.
        ev = entry.get("evaluation") or {}
        entry["final_score"] = ev.get("final_score", 0)
        entry["decision"] = ev.get("decision", "review")

    # ---- Decide cell_status per type based on observed counts -----------------
    for t in types:
        s = per_type_stats[t]
        if not artifact_present_by_type.get(t):
            s["cell_status"] = "failed"
        elif s["fallback_old"] > 0 or s["fallback_synth"] > 0:
            s["cell_status"] = "partial"
        else:
            s["cell_status"] = "ok"

    # ---- Persist final catalog -------------------------------------------------
    save_index(entries, output_path)

    # ---- Regenerate search-index.json so consumers see restored scores ---------
    # merge_index.py --skip-enrichment wrote search-index.json with
    # final_score=0 / decision=review (placeholders). Mirror its post-merge
    # search-index emission here so the published search index matches the
    # final catalog rather than the data-only intermediate.
    _regenerate_search_index(entries, Path(output_path))

    # ---- Emit markdown step summary -------------------------------------------
    summary_text = _format_step_summary(per_type_stats, types)
    _emit_step_summary(summary_text, args.step_summary)

    # Aggregate is publish-time and must never fail the workflow.
    return 0


if __name__ == "__main__":
    sys.exit(main())
