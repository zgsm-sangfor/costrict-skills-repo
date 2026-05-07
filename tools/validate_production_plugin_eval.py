#!/usr/bin/env python3
"""End-to-end validation of the production PluginContentFetcher + MiMo eval.

Picks 3 representative plugin entries (L1 marketplace subdir, L2 root plugin,
L3 root plugin with many SKILLs), runs them through the production
``PluginContentFetcher`` + ``EvalRunner`` with the ``plugin`` task config (real
MiMo LLM call), and prints enrichment output for human inspection.

Goal: confirm before pushing CI that
  1. PluginContentFetcher pulls substantive plugin content (not just README)
  2. detect_plugin_layout fills bundle.skills_namespaces correctly
  3. The LLM enrichment summary/tags/highlights reflect actual capabilities

Usage::

    python3 tools/validate_production_plugin_eval.py
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "ai-resource-eval"))

# Load .env
env_file = REPO_ROOT / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

from ai_resource_eval.api.types import EvalItem  # noqa: E402
from ai_resource_eval.fetcher import PluginContentFetcher  # noqa: E402
from ai_resource_eval.judges.openai_compat import OpenAICompatJudge  # noqa: E402
from ai_resource_eval.runner import EvalRunner  # noqa: E402
from ai_resource_eval.tasks.loader import load_task_config  # noqa: E402


SAMPLES = [
    {
        "id": "anthropic-frontend-design",
        "name": "Frontend Design",
        "type": "plugin",
        "source": "claude-plugins-official",
        "source_url": "https://github.com/anthropics/claude-plugins-official/tree/main/plugins/frontend-design",
        "description": "Frontend design plugin — aesthetic & accessible UI.",
        "stars": 1500,
        "category": "frontend",
        "version": "1.0.0",
    },
    {
        "id": "mongodb-agent-skills",
        "name": "MongoDB Agent Skills",
        "type": "plugin",
        "source": "claude-plugins-dev",
        "source_url": "https://github.com/mongodb/agent-skills",
        "description": "MongoDB Atlas + driver skills bundle.",
        "stars": 200,
        "category": "database",
        "version": "1.0.0",
    },
    {
        "id": "obra-superpowers",
        "name": "Superpowers",
        "type": "plugin",
        "source": "claude-plugins-dev",
        "source_url": "https://github.com/obra/superpowers",
        "description": "TDD, debugging, and structured collaboration skills.",
        "stars": 5000,
        "category": "engineering",
        "version": "1.0.0",
    },
]


def section(title: str) -> None:
    print()
    print("=" * 78)
    print(title)
    print("=" * 78)


def main() -> int:
    api_key = os.environ.get("LLM_API_KEY", "").strip()
    base_url = os.environ.get("LLM_BASE_URL", "").strip()
    model = os.environ.get("LLM_MODEL", "").strip()

    if not (api_key and base_url and model):
        print("Missing LLM_API_KEY / LLM_BASE_URL / LLM_MODEL — cannot run end-to-end eval.")
        return 1

    section("Step 1 — PluginContentFetcher: layout + content size per sample")
    fetcher = PluginContentFetcher()
    layouts: dict[str, dict] = {}
    contents: dict[str, str] = {}
    for s in SAMPLES:
        url = s["source_url"]
        # Show layout (no content fetch)
        # Parse URL to (repo, ref, plugin_root) — same logic as production
        parsed = fetcher._parse_source_url(url)
        if parsed is None:
            print(f"[{s['id']}] non-GitHub URL — fetcher will return None")
            continue
        repo, ref, plugin_root = parsed
        layout = fetcher.detect_plugin_layout(repo, plugin_root, ref=ref)
        layouts[s["id"]] = {
            "is_plugin": layout.is_plugin,
            "skills_count": len(layout.skill_paths),
            "agents_count": len(layout.agent_paths),
            "commands_count": len(layout.command_paths),
            "skills_namespaces": layout.skills_namespaces[:5],
            "fetch_error": layout.fetch_error,
        }
        print(f"[{s['id']}] layout: {layouts[s['id']]}")

        # Fetch content
        result = fetcher.fetch(url)
        if result is None:
            print(f"[{s['id']}] fetch returned None")
            contents[s["id"]] = ""
        else:
            content, _ = result
            contents[s["id"]] = content
            print(f"[{s['id']}] content length: {len(content)} bytes")
    fetcher.close()

    section("Step 2 — End-to-end EvalRunner with real MiMo + plugin task config")
    judge = OpenAICompatJudge(base_url=base_url, api_key=api_key, model=model)
    task_config = load_task_config("plugin")
    runner = EvalRunner(
        task_config=task_config,
        judge=judge,
        cache_dir=str(REPO_ROOT / ".eval_cache_validation"),
        concurrency=1,
        incremental=False,
        interactive=False,
        on_fail="queue",
    )

    items = [EvalItem(**s) for s in SAMPLES]
    results = runner.run(items)

    section("Step 3 — Results")
    output = []
    for s, r in zip(SAMPLES, results):
        rd = r.model_dump(mode="json")
        layout = layouts.get(s["id"], {})
        # Enrichment may live nested under various keys depending on harness; flatten
        enrichment = rd.get("enrichment") or {}
        summary = (
            rd.get("description")
            or rd.get("summary")
            or enrichment.get("summary")
            or enrichment.get("description")
            or ""
        )
        summary_zh = (
            rd.get("description_zh")
            or rd.get("summary_zh")
            or enrichment.get("summary_zh")
            or enrichment.get("description_zh")
            or ""
        )
        tags = rd.get("tags") or enrichment.get("tags") or []
        highlights = rd.get("highlights") or enrichment.get("highlights") or []
        tech = rd.get("tech_stack") or enrichment.get("tech_stack") or []
        out_entry = {
            "id": s["id"],
            "layout": layout,
            "content_bytes": len(contents.get(s["id"], "")),
            "final_score": rd.get("final_score"),
            "decision": rd.get("decision"),
            "_all_keys": list(rd.keys()),
            "summary": summary[:300],
            "summary_zh": summary_zh[:200],
            "tags": tags[:8],
            "tech_stack": tech[:6],
            "highlights": highlights[:3],
        }
        output.append(out_entry)
        print()
        print(f"───── {s['id']} ─────")
        for k, v in out_entry.items():
            print(f"  {k}: {v}")

    print()
    print("=" * 78)
    print("Validation summary:")
    healthy = 0
    for o in output:
        is_plugin = o["layout"].get("is_plugin")
        has_summary = bool(o.get("summary"))
        has_tags = len(o.get("tags") or []) >= 2
        decision = o.get("decision")
        ok = is_plugin and has_summary and has_tags and decision in ("accept", "review")
        marker = "✓" if ok else "✗"
        if ok:
            healthy += 1
        print(f"  {marker} {o['id']:30s} is_plugin={is_plugin} score={o['final_score']} decision={decision}")
    print()
    print(f"Healthy: {healthy}/{len(output)}")

    out_path = REPO_ROOT / "tools" / "validate_production_plugin_eval_output.json"
    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2))
    print(f"Output: {out_path}")

    return 0 if healthy == len(output) else 2


if __name__ == "__main__":
    sys.exit(main())
