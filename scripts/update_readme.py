#!/usr/bin/env python3
"""Update README.md resource counts from catalog/index.json."""

import json
import math
import os
import re

ROOT = os.path.join(os.path.dirname(__file__), "..")
INDEX_PATH = os.path.join(ROOT, "catalog", "index.json")
README_PATH = os.path.join(ROOT, "README.md")


def main():
    with open(INDEX_PATH, "r", encoding="utf-8") as f:
        entries = json.load(f)

    total = len(entries)
    by_type = {}
    for e in entries:
        t = e.get("type", "unknown")
        by_type[t] = by_type.get(t, 0) + 1

    # Round down to nearest 100 for the "N+ 精选" text
    approx = math.floor(total / 100) * 100

    with open(README_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    original = content

    # 1. Update header: "1200+ 精选开发资源一站式索引"
    content = re.sub(
        r"\d+\+\s*精选开发资源一站式索引",
        f"{approx}+ 精选开发资源一站式索引",
        content,
    )

    # 2. Update badge: resources-1292-2ECC71
    content = re.sub(
        r"resources-\d+-2ECC71",
        f"resources-{total}-2ECC71",
        content,
    )

    # 3. Update Features table rows
    type_map = {
        "mcp": "MCP Server",
        "prompt": "Prompt",
        "rule": "Rule",
        "skill": "Skill",
    }
    for key, label in type_map.items():
        count = by_type.get(key, 0)
        content = re.sub(
            rf"\| {re.escape(label)} \| \d+ \|",
            f"| {label} | {count} |",
            content,
        )

    if content != original:
        with open(README_PATH, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"README updated: total={total}, mcp={by_type.get('mcp',0)}, "
              f"prompt={by_type.get('prompt',0)}, rule={by_type.get('rule',0)}, "
              f"skill={by_type.get('skill',0)}")
    else:
        print("README already up to date")


if __name__ == "__main__":
    main()
