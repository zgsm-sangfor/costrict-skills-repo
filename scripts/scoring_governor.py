#!/usr/bin/env python3
"""Scoring governor - reject filtering and field verification.

All scoring is done by the eval harness (ai-resource-eval). This module
only verifies that entries have the expected fields and filters rejects.
Unevaluated entries get score=0, decision="review" (safe default).
"""

import os
import logging
from typing import Any

logger = logging.getLogger(__name__)

LLM_DIMENSION_ORDER = (
    "coding_relevance",
    "doc_completeness",
    "desc_accuracy",
    "writing_quality",
    "specificity",
    "install_clarity",
)

MCP_REGISTRY_SOURCE = "registry.modelcontextprotocol.io"


def apply_governance(
    entries: list[dict[str, Any]],
    health_only: bool = False,
) -> list[dict[str, Any]]:
    """Verify eval fields, default unevaluated entries, filter rejects.

    Args:
        entries: Catalog entries to govern. Mutated in place.
        health_only: When True, skip LLM-derived final_score promotion and
            weak-dim derivation entirely; assigns safe defaults
            (final_score=0, decision="review") and leaves the
            ``evaluation`` dict empty. Used by ``merge_index --skip-enrichment``
            to produce a data-only catalog where the downstream aggregate
            job fills in evaluation later. No reject filtering occurs in
            health-only mode (all entries pass through).
    """
    dry_run = os.environ.get("EVAL_DRY_RUN", "true").lower() not in ("false", "0", "no")
    # registry.modelcontextprotocol.io 派生 entry 数量爆炸（约 8.4k 条），
    # 大量是测试/占位/单点用途 server，社区 awesome list 类源已自带 curation。
    # 默认要求 registry 派生 entry 拿到 decision=='accept' 才纳入最终 catalog，
    # 把决定权交给已有评估引擎；可通过环境变量关闭以便排查。
    mcp_registry_strict = os.environ.get(
        "MCP_REGISTRY_STRICT_ACCEPT", "true"
    ).lower() not in ("false", "0", "no")

    if health_only:
        # Data-only mode: aggregate job will fill in evaluation later. We do
        # not promote any LLM-derived fields, do not derive weak_dims, and
        # do not run the reject filter. Health/freshness signals (computed
        # earlier in the pipeline) are still surfaced to the top level.
        for entry in entries:
            entry["evaluation"] = {}
            entry["final_score"] = 0
            entry["decision"] = "review"
            entry["weak_dims"] = []
            health = entry.get("health") or {}
            if isinstance(health, dict) and "freshness_label" in health:
                entry["freshness_label"] = health["freshness_label"]
        logger.info(
            "Governance (health-only): %d entries → %d kept (no reject filter)",
            len(entries),
            len(entries),
        )
        return list(entries)

    for entry in entries:
        ev = entry.get("evaluation", {})
        was_evaluated = ev.get("final_score") is not None

        if was_evaluated:
            # Harness evaluated — passthrough
            entry["final_score"] = ev["final_score"]
            entry["decision"] = ev.get("decision", "review")
        else:
            # Not evaluated — safe defaults
            entry["final_score"] = 0
            entry["decision"] = "review"
            ev["final_score"] = 0
            ev["decision"] = "review"
            entry["evaluation"] = ev

        weak_dims: list[str] = []
        if was_evaluated:
            for name in LLM_DIMENSION_ORDER:
                score = ev.get(name)
                if isinstance(score, (int, float)) and score < 3:
                    weak_dims.append(name)
        entry["weak_dims"] = weak_dims

        health = entry.get("health") or {}
        if isinstance(health, dict) and "freshness_label" in health:
            entry["freshness_label"] = health["freshness_label"]

    # Filter rejects
    result = []
    reject_count = 0
    for entry in entries:
        decision = entry.get("decision", "review")
        if decision == "reject" and not dry_run:
            reject_count += 1
            logger.info("REJECT (filtered): %s — score=%s", entry.get("id"), entry.get("final_score"))
        else:
            if decision == "reject":
                logger.info("REJECT (dry-run, kept): %s — score=%s", entry.get("id"), entry.get("final_score"))
            result.append(entry)

    logger.info("Governance: %d entries → %d kept, %d rejected", len(entries), len(result), reject_count)

    # registry.modelcontextprotocol.io strict-accept 二次过滤
    if mcp_registry_strict:
        kept: list[dict[str, Any]] = []
        registry_seen = 0
        registry_dropped = 0
        for entry in result:
            if (entry.get("source") or "") == MCP_REGISTRY_SOURCE:
                registry_seen += 1
                if entry.get("decision") != "accept":
                    registry_dropped += 1
                    continue
            kept.append(entry)
        if registry_seen:
            logger.info(
                "MCP registry strict-accept: %d registry entries seen, "
                "%d dropped (decision != accept), %d kept",
                registry_seen,
                registry_dropped,
                registry_seen - registry_dropped,
            )
        result = kept

    return result
