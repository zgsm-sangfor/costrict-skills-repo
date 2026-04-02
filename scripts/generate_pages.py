#!/usr/bin/env python3
"""Generate static JSON API files for GitHub Pages deployment.

Reads catalog/index.json and catalog/search-index.json, outputs a file tree:

    docs/api/v1/
    ├── search-index.json
    ├── mcp/
    │   ├── index.json        (lightweight fields for all MCP entries)
    │   └── {id}.json         (full entry data)
    ├── skill/  ...
    ├── rule/   ...
    └── prompt/ ...
"""

import json
import logging
import os
import re
import shutil
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

SCRIPT_DIR = os.path.dirname(__file__)
CATALOG_DIR = os.path.join(SCRIPT_DIR, "..", "catalog")
DEFAULT_OUTPUT_DIR = os.path.join(SCRIPT_DIR, "..", "docs", "api")

SEARCH_INDEX_FIELDS = (
    "id", "name", "type", "category", "tags", "tech_stack",
    "stars", "description", "description_zh", "source_url",
)


def sanitize_id(entry_id: str) -> str:
    """Make an entry ID safe for use as a filename."""
    s = entry_id.replace("@", "").replace("/", "--")
    s = re.sub(r"[^\w\-.]", "-", s)
    return s


def make_lightweight(entry: dict) -> dict:
    """Extract lightweight fields from a full entry."""
    light = {k: entry.get(k) for k in SEARCH_INDEX_FIELDS}
    install_obj = entry.get("install")
    light["install_method"] = (
        install_obj.get("method") if isinstance(install_obj, dict) else None
    )
    return light


def generate(output_dir: str = DEFAULT_OUTPUT_DIR) -> None:
    index_path = os.path.join(CATALOG_DIR, "index.json")
    search_index_path = os.path.join(CATALOG_DIR, "search-index.json")

    if not os.path.exists(index_path):
        logger.error(f"Full index not found: {index_path}")
        sys.exit(1)

    with open(index_path, "r", encoding="utf-8") as f:
        entries = json.load(f)

    # Clean output directory
    v1_dir = os.path.join(output_dir, "v1")
    if os.path.exists(v1_dir):
        shutil.rmtree(v1_dir)
    os.makedirs(v1_dir, exist_ok=True)

    # Copy search index
    if os.path.exists(search_index_path):
        shutil.copy2(search_index_path, os.path.join(v1_dir, "search-index.json"))
    else:
        logger.warning(f"Search index not found: {search_index_path}, skipping copy")

    # Group entries by type
    by_type: dict[str, list[dict]] = {}
    for entry in entries:
        t = entry.get("type", "unknown")
        by_type.setdefault(t, []).append(entry)

    total_files = 0
    total_size = 0

    for entry_type, type_entries in sorted(by_type.items()):
        type_dir = os.path.join(v1_dir, entry_type)
        os.makedirs(type_dir, exist_ok=True)

        # Per-type lightweight index
        light_entries = [make_lightweight(e) for e in type_entries]
        type_index_path = os.path.join(type_dir, "index.json")
        with open(type_index_path, "w", encoding="utf-8") as f:
            json.dump(light_entries, f, ensure_ascii=False, separators=(",", ":"))
        total_files += 1
        total_size += os.path.getsize(type_index_path)

        # Per-entry full JSON
        for entry in type_entries:
            entry_id = entry.get("id", "unknown")
            safe_id = sanitize_id(entry_id)
            entry_path = os.path.join(type_dir, f"{safe_id}.json")
            with open(entry_path, "w", encoding="utf-8") as f:
                json.dump(entry, f, ensure_ascii=False, separators=(",", ":"))
            total_files += 1
            total_size += os.path.getsize(entry_path)

    # Count search index in stats
    si_path = os.path.join(v1_dir, "search-index.json")
    if os.path.exists(si_path):
        total_files += 1
        total_size += os.path.getsize(si_path)

    # Stats
    type_counts = {t: len(es) for t, es in sorted(by_type.items())}
    logger.info(f"Generated {total_files} files, {total_size / 1024:.0f} KB total")
    logger.info(f"By type: {type_counts}")
    logger.info(f"Total entries: {len(entries)}")


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_OUTPUT_DIR
    generate(out)
