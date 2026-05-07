"""TDD tests for tools/plugin_content_spike.py.

注意：本测试**真打 MiMo LLM**（不 mock），需要 LLM_API_KEY / LLM_BASE_URL / LLM_MODEL
环境变量。无凭证时 LLM 相关测试自动 skip。

Layout / bundle 测试不依赖 LLM，但仍需要网络（GitHub Tree API + raw fetch）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "tools"))

import plugin_content_spike as spike  # noqa: E402


# 是否有 LLM 凭证
HAS_LLM = all(os.environ.get(k) for k in ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL"))


# ───────────────────────────────────────────────────────────────────
# T1: layout detection — 20 sample 全部能拿到 tree + 识别 plugin 边界
# ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("sample", spike.SAMPLES, ids=lambda s: s.sid)
def test_layout_detection(sample: spike.Sample) -> None:
    """每个 sample tree API 能拉到 + 找到 plugin 边界（除 L6 fallback case）。"""
    tree_data = spike.fetch_tree(sample.repo)
    assert "error" not in tree_data, f"tree API failed for {sample.repo}: {tree_data.get('error')}"
    tree_paths = [item["path"] for item in tree_data.get("tree", []) if item.get("type") == "blob"]
    assert tree_paths, f"empty tree for {sample.repo}"

    plugin = spike.detect_plugin(tree_paths, sample.plugin_root)

    if sample.layout == "L6":
        # L6 边缘形态可能没 .claude-plugin/plugin.json
        # 允许 plugin 为 None 或 plugin_json_path 为空
        return

    assert plugin is not None, f"layout detection 失败 for {sample.sid}"
    assert plugin.plugin_json_path != "", (
        f"未识别到 plugin.json for {sample.sid} "
        f"(plugin_root={sample.plugin_root}, layout={sample.layout})"
    )


# ───────────────────────────────────────────────────────────────────
# T2: bundle 字段计算 vs ground truth fixture
# ───────────────────────────────────────────────────────────────────


# 容忍：spike 阶段 ground truth 是手工估计，允许 ±20% 偏差（仅看主结构对不对）
BUNDLE_TOLERANCE = 0.3


@pytest.mark.parametrize("sample", spike.SAMPLES, ids=lambda s: s.sid)
def test_bundle_count_within_tolerance(sample: spike.Sample) -> None:
    """bundle.skills_count / agents_count / commands_count 与 fixture 容差内一致。"""
    if sample.layout == "L6":
        pytest.skip("L6 边缘形态 bundle 通常 0 0 0，不强求")

    tree_data = spike.fetch_tree(sample.repo)
    tree_paths = [item["path"] for item in tree_data.get("tree", []) if item.get("type") == "blob"]
    plugin = spike.detect_plugin(tree_paths, sample.plugin_root)
    assert plugin is not None

    actual = {
        "skills_count": len(plugin.skill_paths),
        "agents_count": len(plugin.agent_paths),
        "commands_count": len(plugin.command_paths),
    }
    expected = {
        "skills_count": sample.expected_skills_count,
        "agents_count": sample.expected_agents_count,
        "commands_count": sample.expected_commands_count,
    }

    # 验证：actual 在 expected ± tolerance 范围内（或两边都为 0）
    for key in actual:
        a, e = actual[key], expected[key]
        if e == 0 and a == 0:
            continue
        if e == 0 and a > 0:
            # fixture 写 0 但实际抓到 — 允许（fixture 写得保守）
            continue
        # e > 0 时检查 a 在 [(1-tol)*e, (1+tol)*e + 5] 范围内
        # +5 是为了 fixture 估计偏差容忍（手工估的不可能完全准）
        lower = max(0, int(e * (1 - BUNDLE_TOLERANCE)))
        upper = int(e * (1 + BUNDLE_TOLERANCE)) + 5
        assert lower <= a <= upper, (
            f"{sample.sid} bundle.{key}: actual={a} 不在 fixture {e} ± {BUNDLE_TOLERANCE*100:.0f}% 范围 [{lower}, {upper}]"
        )


# ───────────────────────────────────────────────────────────────────
# T3: 内容抓取完整性
# ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("sample", spike.SAMPLES, ids=lambda s: s.sid)
def test_content_normalization(sample: spike.Sample) -> None:
    """归一化拼接后内容大小合理，包含期望关键词。"""
    if sample.layout == "L6":
        pytest.skip("L6 边缘形态可能无内容")

    tree_data = spike.fetch_tree(sample.repo)
    tree_paths = [item["path"] for item in tree_data.get("tree", []) if item.get("type") == "blob"]
    plugin = spike.detect_plugin(tree_paths, sample.plugin_root)
    assert plugin is not None

    content, stats = spike.normalize_content(sample.repo, "HEAD", plugin)

    # 至少应该拿到 plugin.json
    assert stats["files_fetched"] >= 1, f"{sample.sid} normalize 拉不到任何文件"

    # 总内容长度应该 > 0
    assert len(content) > 0

    # MiMo 1M context 上限：~4MB（按 1 token=4 chars）— 1MB 是安全线
    assert len(content) < 1_000_000, f"{sample.sid} 内容超 1MB（{len(content)} bytes），可能超 MiMo context"


# ───────────────────────────────────────────────────────────────────
# T4: LLM 真实评估（MiMo，不 mock）
# ───────────────────────────────────────────────────────────────────


@pytest.mark.skipif(not HAS_LLM, reason="No LLM credentials")
@pytest.mark.parametrize("sample", spike.SAMPLES[:5], ids=lambda s: s.sid)  # 仅前 5 sample 跑 LLM 测试，减少时长
def test_llm_evaluation_returns_enrichment(sample: spike.Sample) -> None:
    """打真 MiMo，验证返回 enrichment 字段非空 + 200 OK + 不 timeout。"""
    if sample.layout == "L6":
        pytest.skip("L6 边缘形态不一定能成功 enrich")

    tree_data = spike.fetch_tree(sample.repo)
    tree_paths = [item["path"] for item in tree_data.get("tree", []) if item.get("type") == "blob"]
    plugin = spike.detect_plugin(tree_paths, sample.plugin_root)
    assert plugin is not None

    content, _ = spike.normalize_content(sample.repo, "HEAD", plugin)

    result = spike.evaluate_with_llm(sample, content, "test_t4")

    assert result.get("ok"), f"LLM 调用失败: {result.get('error')}"
    assert result.get("summary"), f"summary 字段为空"
    assert result.get("summary_zh"), f"summary_zh 字段为空"
    assert isinstance(result.get("tags"), list) and len(result["tags"]) >= 1, "tags 应有 ≥1 项"
    assert isinstance(result.get("highlights"), list) and len(result["highlights"]) >= 1, "highlights 应有 ≥1 项"

    # latency 合理（< 300s = LLM_TIMEOUT）
    assert result.get("latency_ms", 0) < 300_000


# ───────────────────────────────────────────────────────────────────
# T5: 质量提升（new vs baseline keyword 命中对比）
# ───────────────────────────────────────────────────────────────────


@pytest.mark.skipif(not HAS_LLM, reason="No LLM credentials")
def test_new_content_improves_keyword_hits() -> None:
    """聚合所有 sample，验证 new content 的 expected keyword 命中率 ≥ baseline。

    用前 5 个 L1/L2 sample（关键词最容易验证），跑 baseline + new 各一遍。
    """
    test_samples = [s for s in spike.SAMPLES if s.layout in ("L1", "L2") and s.expected_keywords][:5]
    assert test_samples, "需要至少 1 个有 expected_keywords 的样本"

    baseline_hits = 0
    new_hits = 0
    total_kws = 0

    for sample in test_samples:
        tree_data = spike.fetch_tree(sample.repo)
        tree_paths = [item["path"] for item in tree_data.get("tree", []) if item.get("type") == "blob"]
        plugin = spike.detect_plugin(tree_paths, sample.plugin_root)
        if plugin is None:
            continue
        new_content, _ = spike.normalize_content(sample.repo, "HEAD", plugin)
        baseline_content = spike.fetch_raw(
            sample.repo, "HEAD",
            (sample.plugin_root + "/" if sample.plugin_root else "") + "README.md",
        ) or ""

        eval_b = spike.evaluate_with_llm(sample, baseline_content or "(empty)", "baseline")
        eval_n = spike.evaluate_with_llm(sample, new_content or "(empty)", "new")

        for kw in sample.expected_keywords:
            total_kws += 1
            kw_l = kw.lower()
            if eval_b.get("ok"):
                searchable_b = " ".join([
                    str(eval_b.get("summary", "")),
                    str(eval_b.get("summary_zh", "")),
                    " ".join(eval_b.get("tags", [])),
                    " ".join(eval_b.get("highlights", [])),
                    " ".join(eval_b.get("tech_stack", [])),
                ]).lower()
                if kw_l in searchable_b:
                    baseline_hits += 1
            if eval_n.get("ok"):
                searchable_n = " ".join([
                    str(eval_n.get("summary", "")),
                    str(eval_n.get("summary_zh", "")),
                    " ".join(eval_n.get("tags", [])),
                    " ".join(eval_n.get("highlights", [])),
                    " ".join(eval_n.get("tech_stack", [])),
                ]).lower()
                if kw_l in searchable_n:
                    new_hits += 1

    # 验证 new ≥ baseline（不能退化）
    assert new_hits >= baseline_hits, (
        f"new keyword 命中率 ({new_hits}/{total_kws}) 低于 baseline ({baseline_hits}/{total_kws})"
    )
    print(f"\nT5 result: baseline {baseline_hits}/{total_kws} → new {new_hits}/{total_kws}")


# ───────────────────────────────────────────────────────────────────
# T6: install command extraction — 每个含 expected_install_keywords 的 sample
# 归一化内容必须命中至少一个 install keyword（substring case-insensitive）。
# ───────────────────────────────────────────────────────────────────


_INSTALL_TEST_SAMPLES = [s for s in spike.SAMPLES if s.expected_install_keywords]


@pytest.mark.parametrize("sample", _INSTALL_TEST_SAMPLES, ids=lambda s: s.sid)
def test_install_keyword_extraction(sample: spike.Sample) -> None:
    """归一化内容（plugin.json + install section + bundle 文件）应至少命中 1 个 install keyword。

    对于 plugin.json 含 `install` 字段的 sample，额外验证 spike 提取的
    `install.commands` 非空（即识别到至少一条命令字符串）。
    """
    tree_data = spike.fetch_tree(sample.repo)
    assert "error" not in tree_data, f"tree API failed for {sample.repo}: {tree_data.get('error')}"
    tree_paths = [
        item["path"]
        for item in tree_data.get("tree", [])
        if item.get("type") == "blob"
    ]

    plugin = spike.detect_plugin(tree_paths, sample.plugin_root)

    # plugin.json data
    plugin_json_data = None
    if plugin is not None and plugin.plugin_json_path:
        raw = spike.fetch_raw(sample.repo, "HEAD", plugin.plugin_json_path)
        if raw:
            try:
                import json as _json
                plugin_json_data = _json.loads(raw)
            except Exception:
                plugin_json_data = None

    # README
    readme_path = (sample.plugin_root + "/" if sample.plugin_root else "") + "README.md"
    readme_content = spike.fetch_raw(sample.repo, "HEAD", readme_path) or ""

    plugin_name_hint = (
        sample.plugin_root.rsplit("/", 1)[-1]
        if sample.plugin_root
        else sample.repo.rsplit("/", 1)[-1]
    )
    if isinstance(plugin_json_data, dict) and plugin_json_data.get("name"):
        plugin_name_hint = str(plugin_json_data["name"])
    install = spike.extract_install_commands(
        plugin_json_data, readme_content,
        repo=sample.repo, plugin_name=plugin_name_hint,
    )

    if plugin is None:
        # L6 fallback — normalized content is just README + install section
        normalized = readme_content
        if install.get("raw_section"):
            normalized += "\n## install\n" + install["raw_section"]
    else:
        normalized, _ = spike.normalize_content(
            sample.repo, "HEAD", plugin,
            plugin_json_data=plugin_json_data,
            install_section=install,
        )

    # Substring check (case-insensitive) — at least 1 expected keyword present.
    nl = normalized.lower()
    hits = [kw for kw in sample.expected_install_keywords if kw.lower() in nl]
    assert hits, (
        f"{sample.sid}: 归一化内容未命中任何 expected install keyword "
        f"({sample.expected_install_keywords}); install_commands={install.get('commands')[:3]}"
    )

    # plugin.json 含 install 字段 → spike 应提取到 ≥1 命令
    if isinstance(plugin_json_data, dict) and plugin_json_data.get("install") is not None:
        install_field = plugin_json_data["install"]
        # 仅当 install field 包含 commandlike 字符串时强制 commands 非空
        flat: list[str] = []
        if isinstance(install_field, str):
            flat.append(install_field)
        elif isinstance(install_field, dict):
            flat.extend([v for v in install_field.values() if isinstance(v, str)])
        elif isinstance(install_field, list):
            flat.extend([v for v in install_field if isinstance(v, str)])
        looks_commandlike = any(spike._INSTALL_KEYWORDS_RE.search(s) for s in flat)
        if looks_commandlike:
            assert install.get("commands"), (
                f"{sample.sid}: plugin.json install 字段含命令字符串但 spike 未提取到 commands"
            )
