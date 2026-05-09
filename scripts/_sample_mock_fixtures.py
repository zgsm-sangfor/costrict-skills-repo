#!/usr/bin/env python3
"""Sample mock fixtures for the enrichment pipeline tests.

Reads the production catalog (`catalog/index.json`) and extracts a small,
sanitized slice per type into `tests/fixtures/enrichment_mock/<type>.json`
for use by `scripts/run_enrichment.py --mock-mode`.

Sampling per type:
  - top N (default 5) entries by stars desc, ties broken by id (stable).
  - filter: `description` non-empty, `source_url` non-empty, type matches.
  - + 1 synthetic empty-description entry to validate ledger-write path.

Sanitization strips evaluation history / scoring side-channels / LLM-derived
fields; only upstream / data-layer fields are preserved.

Usage:
    python -u scripts/_sample_mock_fixtures.py \
        [--catalog catalog/index.json] \
        [--output-dir tests/fixtures/enrichment_mock] \
        [--per-type 5]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Fields to drop during sanitization (scoring history / LLM-derived / sensitive).
FIELDS_TO_STRIP = {
    "evaluation",
    "_prior_evaluation",
    "health",
    "final_score",
    "decision",
    "freshness_label",
    "weak_dims",
    "description_zh",
    "description_original",
    "search_terms",
    "highlights",
    # NOTE: manifest_completeness is intentionally NOT stripped — it is a
    # data-layer field computed by sync_plugins_official.py during sync, not an
    # LLM evaluation output. The plugin task config consumes it as a 10% health
    # signal, so dropping it would make plugin mock fixtures fail to exercise
    # the same scoring path as production. (codex review chunk 3A)
    # MCP eval outputs
    "mcp_install_state",
    "mcp_validation_tags",
    "mcp_schema_valid",
    "mcp_installability_reason",
    # Author email / sensitive contact (defensive — strip if upstream ever adds these)
    "author_email",
    "email",
    "contact_email",
}

# Fields explicitly kept — anything outside both lists is dropped to be safe.
FIELDS_TO_KEEP = {
    "id",
    "name",
    "type",
    "description",
    "source_url",
    "stars",
    "category",
    "tags",
    "tech_stack",
    "source",
    "pushed_at",
    "added_at",
    "last_synced",
    "install",
    "bundle",
    "bundled_in",
    "marketplace_url",
    "skills_sh_url",
    "skills_sh_scraped_at",
    "install_count",
    "platforms",
    "source_priority",
    "version",
    # Plugin data-layer signal computed by sync_plugins_official.py — kept
    # because the plugin task config consumes it as a 10% health signal.
    "manifest_completeness",
}

TYPES = ("mcp", "skill", "rule", "prompt", "plugin")


def sanitize(entry: dict[str, Any]) -> dict[str, Any]:
    """Return a new dict containing only whitelisted fields, in stable order."""
    out: dict[str, Any] = {}
    # Iterate FIELDS_TO_KEEP in declared order so output is stable across runs.
    for field in [
        "id",
        "name",
        "type",
        "description",
        "source_url",
        "stars",
        "category",
        "tags",
        "tech_stack",
        "source",
        "source_priority",
        "platforms",
        "version",
        "marketplace_url",
        "skills_sh_url",
        "skills_sh_scraped_at",
        "install_count",
        "pushed_at",
        "added_at",
        "last_synced",
        "install",
        "bundle",
        "bundled_in",
        "manifest_completeness",
    ]:
        if field in entry and entry[field] is not None:
            out[field] = entry[field]
    return out


def synthetic_empty_desc(type_name: str) -> dict[str, Any]:
    return {
        "id": f"mock-empty-desc-{type_name}",
        "name": "Empty Desc Test",
        "type": type_name,
        "description": "",
        "source_url": "https://example.com/empty-desc",
        "stars": 0,
        "source": "mock_fixture",
    }


def sample_for_type(
    catalog: list[dict[str, Any]], type_name: str, per_type: int
) -> list[dict[str, Any]]:
    """Pick top-N real entries for this type plus 1 synthetic empty-desc entry."""
    candidates = [
        e
        for e in catalog
        if e.get("type") == type_name
        and isinstance(e.get("description"), str)
        and e["description"].strip()
        and isinstance(e.get("source_url"), str)
        and e["source_url"].strip()
    ]
    # Stable sort: stars desc (None → 0), then id asc.
    candidates.sort(
        key=lambda e: (-(int(e.get("stars") or 0)), str(e.get("id") or ""))
    )
    picked = candidates[:per_type]
    sanitized = [sanitize(e) for e in picked]
    sanitized.append(synthetic_empty_desc(type_name))
    return sanitized


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", default="catalog/index.json")
    parser.add_argument("--output-dir", default="tests/fixtures/enrichment_mock")
    parser.add_argument("--per-type", type=int, default=5)
    args = parser.parse_args(argv)

    catalog_path = Path(args.catalog)
    if not catalog_path.is_file():
        print(f"[mock] error: catalog not found at {catalog_path}", file=sys.stderr)
        return 2

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    with catalog_path.open("r", encoding="utf-8") as fh:
        catalog = json.load(fh)
    if not isinstance(catalog, list):
        print(
            f"[mock] error: catalog at {catalog_path} is not a JSON list",
            file=sys.stderr,
        )
        return 2

    for type_name in TYPES:
        entries = sample_for_type(catalog, type_name, args.per_type)
        out_path = output_dir / f"{type_name}.json"
        with out_path.open("w", encoding="utf-8") as fh:
            json.dump(entries, fh, ensure_ascii=False, indent=2, sort_keys=False)
            fh.write("\n")
        print(f"[mock] {type_name}: wrote {len(entries)} entries to {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
