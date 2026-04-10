#!/usr/bin/env python3

from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path
from typing import TypeAlias

CatalogEntry: TypeAlias = dict[str, object]

ROOT = Path(__file__).resolve().parent.parent
INDEX_PATH = ROOT / "catalog" / "index.json"
RESOURCE_BADGE_PATTERN = re.compile(r"resources-\d+-2ECC71")

COUNT_MARKERS: dict[str, str] = {
    "approx": "README_APPROX_COUNT",
    "mcp": "README_COUNT_MCP",
    "prompt": "README_COUNT_PROMPT",
    "rule": "README_COUNT_RULE",
    "skill": "README_COUNT_SKILL",
}

README_PATHS: tuple[Path, ...] = (
    ROOT / "README.md",
    ROOT / "README.zh-CN.md",
)


def load_entries(index_path: Path = INDEX_PATH) -> list[CatalogEntry]:
    with open(index_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        return []

    entries: list[CatalogEntry] = []
    for raw_entry in data:
        if not isinstance(raw_entry, dict):
            continue
        entry: CatalogEntry = {}
        for key, value in raw_entry.items():
            if isinstance(key, str):
                entry[key] = value
        entries.append(entry)
    return entries


def compute_stats(entries: list[CatalogEntry]) -> dict[str, int]:
    total = len(entries)
    approx = math.floor(total / 100) * 100
    by_type: dict[str, int] = {"mcp": 0, "prompt": 0, "rule": 0, "skill": 0}

    for entry in entries:
        entry_type_value = entry.get("type")
        if isinstance(entry_type_value, str) and entry_type_value in by_type:
            by_type[entry_type_value] += 1

    return {"total": total, "approx": approx, **by_type}


def _replace_between_markers(content: str, marker_name: str, replacement: str) -> str:
    start = f"<!-- {marker_name}:START -->"
    end = f"<!-- {marker_name}:END -->"
    pattern = re.compile(rf"({re.escape(start)})(.*?)({re.escape(end)})", re.DOTALL)

    if not pattern.search(content):
        raise ValueError(f"Marker pair not found: {marker_name}")

    return pattern.sub(
        lambda match: f"{match.group(1)}{replacement}{match.group(3)}", content, count=1
    )


def update_single_readme(readme_path: Path, stats: dict[str, int]) -> bool:
    content = readme_path.read_text(encoding="utf-8")
    original = content

    content = _replace_between_markers(
        content, COUNT_MARKERS["approx"], str(stats["approx"])
    )
    for key in ("mcp", "prompt", "rule", "skill"):
        content = _replace_between_markers(content, COUNT_MARKERS[key], str(stats[key]))

    content = RESOURCE_BADGE_PATTERN.sub(f"resources-{stats['total']}-2ECC71", content)

    if content != original:
        _ = readme_path.write_text(content, encoding="utf-8")
        return True
    return False


def update_readmes(
    index_path: Path = INDEX_PATH, readme_paths: tuple[Path, ...] = README_PATHS
) -> list[Path]:
    stats = compute_stats(load_entries(index_path=index_path))
    updated_paths: list[Path] = []

    for readme_path in readme_paths:
        if update_single_readme(readme_path, stats):
            updated_paths.append(readme_path)

    return updated_paths


def main() -> None:
    updated_paths = update_readmes()

    if updated_paths:
        print("README files updated:")
        for path in updated_paths:
            print(f"- {path.relative_to(ROOT)}")
    else:
        print("README files already up to date")


if __name__ == "__main__":
    main()
