#!/usr/bin/env python3
"""对照期望清单审计 catalog 中热门资源（skill / mcp / rule）的收录状态。

输入：
- scripts/popular_skills_expected.yaml — 期望清单（含 expected_skills /
                                          expected_mcp / expected_rules 三组）
- catalog/index.json                     — 当前 catalog 索引（CI 生成）

输出：
- docs/coverage_report.md — markdown 格式的审计报告（按 type 分组）

状态判定（基于 catalog/index.json 中对应 type 的 entry 的 source_url）：
- "✅ 直接源" — github_repo 在 catalog 中存在且 source_url 直接指向该
                 owner/repo（非 sickn33/antigravity-awesome-skills 等镜像）
- "⚠️ 仅镜像" — github_repo 在 catalog 中**只**以镜像形式存在（仅 skill 类型）
- "❌ 未收录" — github_repo 在 catalog 中完全不存在

类型差异：
- skill：保留镜像（sickn33）判定
- mcp / rule：暂无对应已知镜像，状态二选一（直接源 / 未收录）；
  registry URL 来源的 mcp entry（registry.modelcontextprotocol.io）不参与
  GitHub-based 命中判定（GitHub URL 来源的 entry 即可命中 expected）

增量逻辑：
- 若 docs/coverage_report.md 已存在且与本次生成内容完全一致，跳过写入
  （日志 "No changes"，exit 0），避免空 commit；否则写入并打印 "Updated"。
"""

import json
import os
import re
import sys
from datetime import datetime, timezone

# PyYAML 是项目级依赖（ai-resource-eval 测试用过）。
import yaml

# --- 路径常量 -------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
EXPECTED_PATH = os.path.join(SCRIPT_DIR, "popular_skills_expected.yaml")
CATALOG_PATH = os.path.join(REPO_ROOT, "catalog", "index.json")
REPORT_PATH = os.path.join(REPO_ROOT, "docs", "coverage_report.md")

# 已知镜像源（与 utils._KNOWN_MIRRORS 保持一致）。仅对 skill 类型有效。
KNOWN_MIRRORS = {
    "sickn33/antigravity-awesome-skills",
}

# --- 状态常量 -------------------------------------------------------------
STATUS_DIRECT = "✅ 直接源"
STATUS_MIRROR = "⚠️ 仅镜像"
STATUS_MISSING = "❌ 未收录"

# --- 类型组配置 -----------------------------------------------------------
# (yaml_key, entry_type, display_name, item_label)
TYPE_GROUPS = [
    ("expected_skills", "skill", "Skills", "Skill"),
    ("expected_mcp", "mcp", "MCP", "MCP Server"),
    ("expected_rules", "rule", "Rules", "Rule"),
]


# --- 数据加载 -------------------------------------------------------------

def load_expected(path: str = EXPECTED_PATH) -> dict:
    """加载期望清单 YAML，返回 dict[entry_type, list[item]]。

    键：'skill' / 'mcp' / 'rule'（即使 yaml 中缺失对应组也会有空 list）。
    每条 item 含 name / github_repo / reason。
    """
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    out: dict = {}
    for yaml_key, entry_type, _disp, _label in TYPE_GROUPS:
        items = data.get(yaml_key) or []
        normalized: list = []
        for item in items:
            if not isinstance(item, dict):
                continue
            gh = (item.get("github_repo") or "").strip()
            if not gh:
                continue
            normalized.append({
                "name": item.get("name") or gh.split("/")[-1],
                "github_repo": gh,
                "reason": item.get("reason") or "",
            })
        out[entry_type] = normalized
    return out


def load_catalog(path: str = CATALOG_PATH) -> list:
    """加载 catalog/index.json，返回 entry 列表。

    catalog/index.json 顶层既可能是 list（旧版），也可能是 dict（含 entries 键）。
    两者都兼容。
    """
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("entries", "items", "data"):
            v = data.get(key)
            if isinstance(v, list):
                return v
    return []


# --- 命中判定 -------------------------------------------------------------

_GITHUB_RE = re.compile(r"github\.com/([^/]+)/([^/#?]+)", re.IGNORECASE)


def parse_owner_repo(url: str) -> tuple:
    """从 GitHub URL 提取 (owner, repo)，全部小写。

    返回 (owner, repo) 或 None（非 GitHub URL / 无法解析）。
    registry.modelcontextprotocol.io 等非 github.com URL 返回 None。
    """
    if not url:
        return None
    m = _GITHUB_RE.search(url)
    if not m:
        return None
    repo = m.group(2)
    if repo.endswith(".git"):
        repo = repo[:-4]
    return (m.group(1).lower(), repo.lower())


def classify_entry(entry: dict, target_owner_repo: str, entry_type: str = "skill") -> str:
    """判断 entry 是否命中 target_owner_repo，返回三种 marker：

    - "direct"  — entry 直接落在目标 owner/repo（type 与 entry_type 一致）
    - "mirror"  — entry 落在已知镜像源（仅 entry_type=="skill" 时有效）
    - ""         — 未命中（type 不符 / 非 GitHub URL / repo 不匹配）

    entry_type：要审计的目标 type（skill / mcp / rule），entry 的 type
    必须与之一致才会参与判定。registry URL 等非 github.com URL 自动跳过。
    """
    if (entry.get("type") or "") != entry_type:
        return ""
    pr = parse_owner_repo(entry.get("source_url") or "")
    if not pr:
        # registry URL 或其他非 GitHub URL → 不参与 GitHub-based 命中
        return ""
    owner, repo = pr
    slug = f"{owner}/{repo}"
    if slug == target_owner_repo.lower():
        return "direct"
    # 镜像逻辑仅对 skill 类型有效。mcp / rule 暂无已知镜像。
    if entry_type == "skill" and slug in KNOWN_MIRRORS:
        # sickn33 镜像 = anthropics/skills 的快照（utils.skill_identity_key
        # 的 collapse 逻辑保证）。仅当 expected 是 anthropics/skills 时
        # 才视为镜像命中。
        if target_owner_repo.lower() == "anthropics/skills":
            return "mirror"
    return ""


def determine_status_by_type(target_owner_repo: str, entries: list, entry_type: str) -> tuple:
    """对单个 expected 项遍历 catalog 给出最终状态与代表 entry。

    返回 (status, representative_entry)。representative_entry 用于显示
    install_count（若可得），无则为 None。

    entry_type：要审计的目标 type（skill / mcp / rule）。
    """
    direct_entry = None
    mirror_entry = None
    for entry in entries:
        marker = classify_entry(entry, target_owner_repo, entry_type)
        if marker == "direct":
            # 优先取 install_count 最大的那条作为代表
            if direct_entry is None or (
                int(entry.get("install_count") or 0) > int(direct_entry.get("install_count") or 0)
            ):
                direct_entry = entry
        elif marker == "mirror":
            if mirror_entry is None:
                mirror_entry = entry
    if direct_entry is not None:
        return (STATUS_DIRECT, direct_entry)
    if mirror_entry is not None:
        return (STATUS_MIRROR, mirror_entry)
    return (STATUS_MISSING, None)


def determine_status(target_owner_repo: str, entries: list) -> tuple:
    """向后兼容包装：默认按 skill 类型判定。"""
    return determine_status_by_type(target_owner_repo, entries, "skill")


# --- 报告生成 -------------------------------------------------------------

def _format_install_count(entry) -> str:
    """install_count 显示：数字 / "-"（缺失）。"""
    if entry is None:
        return "-"
    val = entry.get("install_count")
    if val is None or val == "":
        return "-"
    try:
        return f"{int(val):,}"
    except (TypeError, ValueError):
        return str(val)


def _render_section(
    section_title: str,
    item_label: str,
    expected_items: list,
    entries: list,
    entry_type: str,
) -> tuple:
    """渲染单个类型分组（Skills / MCP / Rules）的 markdown 段落。

    返回 (lines, counts)：lines 为 markdown 行 list，counts 为该分组三种状态计数。
    """
    counts = {STATUS_DIRECT: 0, STATUS_MIRROR: 0, STATUS_MISSING: 0}
    rows = []
    for item in expected_items:
        status, rep = determine_status_by_type(item["github_repo"], entries, entry_type)
        counts[status] += 1
        rows.append({
            "name": item["name"],
            "github_repo": item["github_repo"],
            "status": status,
            "install_count": _format_install_count(rep),
            "reason": item["reason"],
        })

    total = len(expected_items)
    lines: list = []
    lines.append(f"## {section_title} 覆盖")
    lines.append("")
    if total == 0:
        lines.append("（暂无期望清单条目）")
        lines.append("")
        return lines, counts

    lines.append("### 状态摘要")
    lines.append("")
    lines.append(f"- {STATUS_DIRECT}：{counts[STATUS_DIRECT]} / {total}")
    if entry_type == "skill":
        lines.append(f"- {STATUS_MIRROR}：{counts[STATUS_MIRROR]} / {total}")
    lines.append(f"- {STATUS_MISSING}：{counts[STATUS_MISSING]} / {total}")
    lines.append("")
    lines.append("### 详细列表")
    lines.append("")
    lines.append(f"| {item_label} | GitHub | 状态 | install_count | 备注 |")
    lines.append("|-------|--------|------|---------------|------|")
    for r in rows:
        lines.append(
            f"| {r['name']} | {r['github_repo']} | {r['status']} | "
            f"{r['install_count']} | {r['reason']} |"
        )
    lines.append("")
    return lines, counts


def render_report(expected, entries: list, generated_at: str = "") -> str:
    """生成 markdown 报告字符串。

    expected 接受两种形式以保持向后兼容：
    - dict[entry_type, list]：新版多类型形式
    - list[item]：旧版仅 skill 形式（自动包装为 {'skill': [...]}）

    generated_at 默认为当前 UTC 时间（YYYY-MM-DD）；测试时可注入固定值。
    """
    if not generated_at:
        generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # 兼容旧形式
    if isinstance(expected, list):
        expected = {"skill": expected, "mcp": [], "rule": []}
    elif isinstance(expected, dict):
        # 确保三个 key 都存在
        expected = {
            "skill": expected.get("skill") or [],
            "mcp": expected.get("mcp") or [],
            "rule": expected.get("rule") or [],
        }
    else:
        expected = {"skill": [], "mcp": [], "rule": []}

    total_all = sum(len(v) for v in expected.values())
    total_counts = {STATUS_DIRECT: 0, STATUS_MIRROR: 0, STATUS_MISSING: 0}

    lines: list = []
    lines.append("# Catalog 热门资源覆盖率审计")
    lines.append("")
    lines.append(f"报告生成时间：{generated_at}")
    lines.append(f"catalog 版本：catalog/index.json 总条目 {len(entries)}")
    lines.append("")

    # 渲染三个分组
    for yaml_key, entry_type, display_name, item_label in TYPE_GROUPS:
        section_lines, section_counts = _render_section(
            display_name, item_label, expected.get(entry_type, []), entries, entry_type
        )
        lines.extend(section_lines)
        for k, v in section_counts.items():
            total_counts[k] += v

    # 总览
    lines.append("## 状态摘要总览")
    lines.append("")
    lines.append(f"- {STATUS_DIRECT}：{total_counts[STATUS_DIRECT]} / {total_all}")
    lines.append(f"- {STATUS_MIRROR}：{total_counts[STATUS_MIRROR]} / {total_all}")
    lines.append(f"- {STATUS_MISSING}：{total_counts[STATUS_MISSING]} / {total_all}")
    lines.append("")
    return "\n".join(lines)


# --- 增量写入 -------------------------------------------------------------

def _strip_volatile(content: str) -> str:
    """剥离 markdown 中"易变"的元数据行（生成时间），用于稳定比较。

    避免每天因为时间戳变化而触发 commit。
    """
    out = []
    for line in content.splitlines():
        if line.startswith("报告生成时间："):
            continue
        out.append(line)
    return "\n".join(out)


def write_report_if_changed(content: str, path: str = REPORT_PATH) -> bool:
    """对比已有报告内容，仅在实质变化时写入。

    返回 True 表示已写入，False 表示无变化跳过。
    比较时剥离生成时间行，避免日期变化导致空 commit。
    """
    new_norm = _strip_volatile(content)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                old_norm = _strip_volatile(f.read())
            if old_norm == new_norm:
                return False
        except OSError:
            pass
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return True


# --- 主流程 ---------------------------------------------------------------

def main() -> int:
    if not os.path.exists(EXPECTED_PATH):
        print(f"ERROR: expected list not found: {EXPECTED_PATH}")
        return 2
    if not os.path.exists(CATALOG_PATH):
        print(f"ERROR: catalog not found: {CATALOG_PATH}")
        return 2

    expected = load_expected(EXPECTED_PATH)
    entries = load_catalog(CATALOG_PATH)
    total_expected = sum(len(v) for v in expected.values())
    print(
        f"INFO: loaded expected skill={len(expected.get('skill', []))}, "
        f"mcp={len(expected.get('mcp', []))}, "
        f"rule={len(expected.get('rule', []))}, "
        f"catalog entries={len(entries)}"
    )

    report = render_report(expected, entries)
    written = write_report_if_changed(report, REPORT_PATH)
    if written:
        print(f"INFO: Updated {REPORT_PATH}")
    else:
        print(f"INFO: No changes, skipped writing {REPORT_PATH}")

    # 简单分组状态摘要再输出一次，便于 CI 日志直接看到结果
    overall = {STATUS_DIRECT: 0, STATUS_MIRROR: 0, STATUS_MISSING: 0}
    for _yaml_key, entry_type, display_name, _label in TYPE_GROUPS:
        items = expected.get(entry_type, [])
        counts = {STATUS_DIRECT: 0, STATUS_MIRROR: 0, STATUS_MISSING: 0}
        for item in items:
            status, _ = determine_status_by_type(item["github_repo"], entries, entry_type)
            counts[status] += 1
            overall[status] += 1
        print(
            f"INFO: [{display_name}] direct={counts[STATUS_DIRECT]}, "
            f"mirror={counts[STATUS_MIRROR]}, "
            f"missing={counts[STATUS_MISSING]}, "
            f"total={len(items)}"
        )
    print(
        f"INFO: [Total] direct={overall[STATUS_DIRECT]}, "
        f"mirror={overall[STATUS_MIRROR]}, "
        f"missing={overall[STATUS_MISSING]}, "
        f"total={total_expected}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
