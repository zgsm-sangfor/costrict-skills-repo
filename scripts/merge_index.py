#!/usr/bin/env python3
"""Merge all type-specific indexes and curated files into catalog/index.json."""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from utils import load_index, save_index, deduplicate, logger
from health_scorer import compute_health

CATALOG_DIR = os.path.join(os.path.dirname(__file__), "..", "catalog")
TYPES = ["mcp", "skills", "rules", "prompts"]


def merge():
    all_entries = []

    for resource_type in TYPES:
        type_dir = os.path.join(CATALOG_DIR, resource_type)

        # Load auto-synced index (includes Tier 1 + Tier 2 for skills)
        index_path = os.path.join(type_dir, "index.json")
        entries = load_index(index_path)
        logger.info(f"Loaded {len(entries)} entries from {resource_type}/index.json")
        all_entries.extend(entries)

        # Load curated entries (Tier 3 — lowest priority in dedup)
        curated_path = os.path.join(type_dir, "curated.json")
        curated = load_index(curated_path)
        if curated:
            logger.info(f"Loaded {len(curated)} entries from {resource_type}/curated.json")
            all_entries.extend(curated)

    # Deduplicate by source_url + id (earlier entries take priority: Tier 1 > Tier 2 > Tier 3)
    deduped = deduplicate(all_entries)

    # Compute health scores
    for entry in deduped:
        entry["health"] = compute_health(entry)

    # Sort by health.score descending, ties broken by stars descending (nulls last)
    deduped.sort(
        key=lambda x: (
            x.get("health", {}).get("score", 0),
            x.get("stars") if x.get("stars") is not None else -1,
        ),
        reverse=True,
    )

    output_path = os.path.join(CATALOG_DIR, "index.json")
    save_index(deduped, output_path)

    # Print summary by type and category
    by_type = {}
    by_category = {}
    for entry in deduped:
        t = entry.get("type", "unknown")
        c = entry.get("category", "unknown")
        by_type[t] = by_type.get(t, 0) + 1
        by_category[c] = by_category.get(c, 0) + 1

    logger.info(f"\nTotal: {len(deduped)} entries")
    logger.info(f"By type: {by_type}")
    logger.info(f"By category: {by_category}")


if __name__ == "__main__":
    merge()
