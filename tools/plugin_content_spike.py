#!/usr/bin/env python3
"""Plugin content fetch + normalize spike.

跑 20 个真实 plugin sample，验证：
  1. layout detection（统一规则：.claude-plugin/plugin.json 在哪 = plugin root 在哪）
  2. bundle 字段计算（skills_count / agents_count / commands_count / skills_namespaces）
  3. 内容抓取 + 全拼接归一化
  4. baseline (README only) vs new (实质内容) MiMo 评估对比
  5. 整体 token / latency / 稳定性

Spike 脚本，throwaway 性质。验证可行后转 OpenSpec change。

Usage:
    LLM_API_KEY=... LLM_BASE_URL=... LLM_MODEL=... \\
    python3 tools/plugin_content_spike.py [--samples 20] [--no-llm]
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "ai-resource-eval"))

# Load .env if present
env_file = REPO_ROOT / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()
LLM_API_KEY = os.environ.get("LLM_API_KEY", "").strip()
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "").strip()
LLM_MODEL = os.environ.get("LLM_MODEL", "").strip()

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("spike")


# ---------------------------------------------------------------------------
# 20 sample fixtures with hand-curated ground truth
# ---------------------------------------------------------------------------

@dataclass
class Sample:
    sid: str  # sample id (短 slug)
    repo: str  # owner/repo
    plugin_root: str  # plugin 在 repo 内的相对路径，"" = repo root
    layout: str  # L1 / L2 / L3 / L4 / L5 / L6
    expected_skills_count: int
    expected_agents_count: int
    expected_commands_count: int
    expected_keywords: list[str] = field(default_factory=list)  # description 应含的词
    expected_install_keywords: list[str] = field(default_factory=list)  # install 命令片段
    notes: str = ""


SAMPLES: list[Sample] = [
    # ─── L1: marketplace monorepo with plugins/<name>/ ─────────────────────
    Sample(
        sid="anthropic-frontend-design",
        repo="anthropics/claude-plugins-official",
        plugin_root="plugins/frontend-design",
        layout="L1",
        expected_skills_count=1,
        expected_agents_count=0,
        expected_commands_count=0,
        expected_keywords=["frontend", "design", "aesthetic"],
        expected_install_keywords=["plugin marketplace", "plugin install"],
    ),
    Sample(
        sid="anthropic-claude-md-management",
        repo="anthropics/claude-plugins-official",
        plugin_root="plugins/claude-md-management",
        layout="L1",
        expected_skills_count=0,
        expected_agents_count=0,
        expected_commands_count=1,
        expected_keywords=["claude.md", "memory"],
        expected_install_keywords=["plugin install", "marketplace"],
    ),
    Sample(
        sid="anthropic-code-simplifier",
        repo="anthropics/claude-plugins-official",
        plugin_root="plugins/code-simplifier",
        layout="L1",
        expected_skills_count=0,
        expected_agents_count=1,
        expected_commands_count=0,
        expected_keywords=["simplif", "code"],
        expected_install_keywords=["plugin install", "code-simplifier"],
    ),
    Sample(
        sid="anthropic-clangd-lsp",
        repo="anthropics/claude-plugins-official",
        plugin_root="plugins/clangd-lsp",
        layout="L1",
        expected_skills_count=0,
        expected_agents_count=0,
        expected_commands_count=0,  # 仅 plugin.json
        expected_keywords=["clangd", "lsp", "c++"],
        expected_install_keywords=["plugin install", "clangd-lsp"],
    ),
    # ─── L1b: anthropic external_plugins/<name>/ (兄弟形态) ───────────────────
    Sample(
        sid="anthropic-discord",
        repo="anthropics/claude-plugins-official",
        plugin_root="external_plugins/discord",
        layout="L1",
        expected_skills_count=2,
        expected_agents_count=0,
        expected_commands_count=0,
        expected_keywords=["discord", "configure", "access"],
        expected_install_keywords=["plugin install", "discord"],
    ),
    # ─── L2: 单 plugin 整 repo, .claude-plugin/ 在 root ──────────────────────
    Sample(
        sid="mongodb-agent-skills",
        repo="mongodb/agent-skills",
        plugin_root="",
        layout="L2",
        expected_skills_count=8,
        expected_agents_count=0,
        expected_commands_count=0,
        expected_keywords=["mongodb", "atlas", "stream"],
        expected_install_keywords=["mongodb-agent-skills", "marketplace"],
    ),
    Sample(
        sid="supabase-plugin",
        repo="supabase-community/supabase-plugin",
        plugin_root="",
        layout="L2",
        expected_skills_count=2,
        expected_agents_count=0,
        expected_commands_count=0,
        expected_keywords=["supabase", "postgres"],
        expected_install_keywords=["supabase-plugin", "marketplace"],
    ),
    Sample(
        sid="huggingface-skills",
        repo="huggingface/skills",
        plugin_root="",
        layout="L2",
        # huggingface 有嵌套 .claude-plugin (skills/huggingface-trackio/)
        # 我们测最外层那个；嵌套的另算一个 plugin
        expected_skills_count=12,  # 大致 ~14 - nested 1-2
        expected_agents_count=0,
        expected_commands_count=0,
        expected_keywords=["huggingface", "hf"],
        expected_install_keywords=["marketplace add", "huggingface/skills"],
        notes="嵌套 plugin 测试（root + skills/huggingface-trackio/.claude-plugin/）",
    ),
    Sample(
        sid="adobe-aem-65-lts",
        repo="adobe/skills",
        plugin_root="plugins/aem/6.5-lts",
        layout="L2",  # 双层 monorepo
        expected_skills_count=10,  # 实测要 spike 出来
        expected_agents_count=0,
        expected_commands_count=0,
        expected_keywords=["aem", "adobe"],
        expected_install_keywords=["marketplace add", "adobe/skills"],
        notes="双层 monorepo plugins/aem/6.5-lts",
    ),
    # ─── L3: superpowers 形态（单 plugin 但内含大量 SKILL）──────────────────
    Sample(
        sid="obra-superpowers",
        repo="obra/superpowers",
        plugin_root="",
        layout="L3",
        expected_skills_count=14,
        expected_agents_count=0,
        expected_commands_count=0,
        expected_keywords=["brainstorm", "test-driven", "subagent"],
        expected_install_keywords=["superpowers", "marketplace"],
        notes="248KB 总内容，~63k tokens，6% MiMo context",
    ),
    # ─── L4: dev monorepo with plugins/<name>/skills/<sub>/SKILL.md ────────
    Sample(
        sid="trailofbits-agentic-actions-auditor",
        repo="trailofbits/skills",
        plugin_root="plugins/agentic-actions-auditor",
        layout="L4",
        expected_skills_count=1,
        expected_agents_count=0,
        expected_commands_count=0,
        expected_keywords=["github actions", "security", "audit"],
        expected_install_keywords=["marketplace add", "trailofbits/skills"],
    ),
    Sample(
        sid="trailofbits-c-review",
        repo="trailofbits/skills",
        plugin_root="plugins/c-review",
        layout="L4",
        expected_skills_count=0,
        expected_agents_count=4,  # c-review-dedup-judge / fp-judge / 等
        expected_commands_count=0,
        expected_keywords=["review", "judge"],
        expected_install_keywords=["marketplace add", "trailofbits/skills"],
    ),
    Sample(
        sid="awslabs-aws-amplify",
        repo="awslabs/agent-plugins",
        plugin_root="plugins/aws-amplify",
        layout="L4",
        expected_skills_count=1,
        expected_agents_count=0,
        expected_commands_count=0,
        expected_keywords=["amplify", "aws"],
        expected_install_keywords=["marketplace add", "awslabs/agent-plugins"],
    ),
    Sample(
        sid="everyinc-compound-engineering",
        repo="EveryInc/compound-engineering-plugin",
        plugin_root="plugins/compound-engineering",
        layout="L4",
        expected_skills_count=15,
        expected_agents_count=20,  # 实测 47 agents 总数，分到这个 plugin 子集
        expected_commands_count=2,
        expected_keywords=["compound", "engineering", "agent"],
        expected_install_keywords=["marketplace add", "compound-engineering"],
    ),
    Sample(
        sid="everyinc-coding-tutor",
        repo="EveryInc/compound-engineering-plugin",
        plugin_root="plugins/coding-tutor",
        layout="L4",
        expected_skills_count=1,
        expected_agents_count=0,
        expected_commands_count=2,
        expected_keywords=["tutor", "coding", "quiz"],
        expected_install_keywords=["marketplace add", "coding-tutor"],
    ),
    Sample(
        sid="wshobson-accessibility-compliance",
        repo="wshobson/agents",
        plugin_root="plugins/accessibility-compliance",
        layout="L4",
        expected_skills_count=2,
        expected_agents_count=1,
        expected_commands_count=1,
        expected_keywords=["accessibility", "wcag"],
        expected_install_keywords=["marketplace add", "wshobson/agents"],
    ),
    # ─── L4 root-level plugin dirs (alirezarezvani 形态) ──────────────────
    Sample(
        sid="alirezarezvani-business-growth",
        repo="alirezarezvani/claude-skills",
        plugin_root="business-growth",
        layout="L4",
        expected_skills_count=1,  # 实测 spike
        expected_agents_count=0,
        expected_commands_count=0,
        expected_keywords=["business", "growth"],
        expected_install_keywords=["marketplace add", "business-growth"],
        notes="root-level dir 形态",
    ),
    # ─── L5: dev 单 plugin 独立 repo（外部 source URL）─────────────────────
    # claude-plugins-dev 派生很多 entry source_url 是 git+ form
    # 选 starts ranging
    Sample(
        sid="kieranklaassen-compound-engineering",
        repo="kieranklaassen/compound-engineering-plugin",
        plugin_root="",
        layout="L5",
        expected_skills_count=0,  # spike 出来再校准
        expected_agents_count=0,
        expected_commands_count=0,
        expected_keywords=["compound", "engineering"],
        expected_install_keywords=["marketplace add", "kieranklaassen"],
        notes="dev 源 plugin 直接 fork repo（kieranklaassen/...）",
    ),
    # ─── L6: 边缘形态 ───────────────────────────────────────────────────
    Sample(
        sid="affaan-everything-claude-code",
        repo="affaan-m/everything-claude-code",
        plugin_root="",
        layout="L6",
        expected_skills_count=0,  # spike 出来再校准
        expected_agents_count=0,
        expected_commands_count=0,
        expected_keywords=["claude code", "comprehensive"],
        expected_install_keywords=["marketplace add", "everything-claude-code"],
        notes="170k stars 高星 plugin，结构未知",
    ),
    Sample(
        sid="vercel-nextjs",
        repo="vercel/next.js",
        plugin_root="",  # 整 repo 不是 plugin
        layout="L6",
        expected_skills_count=0,
        expected_agents_count=0,
        expected_commands_count=0,
        expected_keywords=["next.js", "react"],
        expected_install_keywords=["npm install", "next"],
        notes="vercel/next.js — 不是 plugin 仓库（dev 注册的 cache-components plugin 引用），fallback 验证",
    ),
]


# ---------------------------------------------------------------------------
# GitHub Tree API + content fetch (with caches)
# ---------------------------------------------------------------------------

_tree_cache: dict[str, dict[str, Any]] = {}
_raw_cache: dict[str, str | None] = {}


def fetch_tree(repo: str, ref: str = "HEAD") -> dict[str, Any]:
    """GitHub Tree API recursive=true，按 (repo, ref) cache。返回 raw json。"""
    key = f"{repo}@{ref}"
    if key in _tree_cache:
        return _tree_cache[key]
    url = f"https://api.github.com/repos/{repo}/git/trees/{ref}?recursive=1"
    headers = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"token {GITHUB_TOKEN}"
    try:
        resp = httpx.get(url, headers=headers, timeout=30.0)
        if resp.status_code != 200:
            log.warning("Tree API %s: HTTP %d %s", repo, resp.status_code, resp.text[:200])
            data = {"tree": [], "truncated": False, "error": resp.status_code}
        else:
            data = resp.json()
    except httpx.HTTPError as e:
        log.warning("Tree API %s exception: %s", repo, e)
        data = {"tree": [], "truncated": False, "error": str(e)}
    _tree_cache[key] = data
    return data


def fetch_raw(repo: str, ref: str, path: str) -> Optional[str]:
    """raw.githubusercontent.com 拉文件，按 URL cache。"""
    url = f"https://raw.githubusercontent.com/{repo}/{ref}/{path}"
    if url in _raw_cache:
        return _raw_cache[url]
    try:
        resp = httpx.get(url, timeout=30.0)
        if resp.status_code == 200:
            _raw_cache[url] = resp.text
            return resp.text
    except httpx.HTTPError:
        pass
    _raw_cache[url] = None
    return None


# ---------------------------------------------------------------------------
# Layout detection + content normalization
# ---------------------------------------------------------------------------

@dataclass
class PluginContent:
    plugin_root: str  # 在 repo 内相对路径，"" = repo root
    plugin_json_path: str
    skill_paths: list[str]
    agent_paths: list[str]
    command_paths: list[str]
    skills_namespaces: list[str]  # ["<plugin-name>:<skill-name>", ...]


def _strip_hidden_prefix(path: str) -> str:
    """剔除 .gemini/ / .codex/ 等"平台特定影子目录"开头的路径，返回原 path 仅当不以此开头。"""
    return path


def detect_plugin(
    tree_paths: list[str],
    target_root: str,
) -> Optional[PluginContent]:
    """从 tree paths 中提取 target_root 下的 plugin 内容。

    target_root="" 表示 repo root；否则是 repo 内的子路径（如 plugins/foo）。

    plugin 边界 = 含 .claude-plugin/plugin.json 的最近祖先目录（统一规则）。
    内部文件归属：path startswith(plugin_root + "/") 且不归属更深 plugin root。
    """
    plugin_json_marker = ".claude-plugin/plugin.json"

    # 找所有 plugin root 候选（同 repo 可能多个）
    all_plugin_roots = set()
    for path in tree_paths:
        if path == plugin_json_marker:
            all_plugin_roots.add("")  # repo root 是个 plugin
        elif path.endswith("/" + plugin_json_marker):
            root = path[: -len("/" + plugin_json_marker)]
            all_plugin_roots.add(root)

    # 排除 hidden 目录开头的 plugin root（.codex / .gemini 等不是真正 plugin）
    all_plugin_roots = {r for r in all_plugin_roots if not any(
        seg.startswith(".") and seg not in ("",) for seg in r.split("/")
    )}

    if target_root not in all_plugin_roots:
        # target_root 没 plugin.json 标识 — fallback：看是否 README only / 边缘形态
        # 仍尝试在 target_root 下找 SKILL.md/agent/command 文件
        return _scan_without_plugin_json(tree_paths, target_root)

    plugin_json_path = (target_root + "/" if target_root else "") + plugin_json_marker

    # 找 target_root 下方"更深的 plugin roots"，用于排除嵌套 plugin 的内容
    deeper_roots = sorted(
        [r for r in all_plugin_roots if r != target_root and r.startswith(target_root + "/" if target_root else "")],
        key=len,
        reverse=False,
    )

    prefix = target_root + "/" if target_root else ""

    skill_paths = []
    agent_paths = []
    command_paths = []

    for path in tree_paths:
        if not path.startswith(prefix):
            continue
        # 剔除归属更深 plugin 的文件
        if any(path.startswith(d + "/") for d in deeper_roots):
            continue

        # 剔除 hidden 目录的文件（.codex/ .gemini/ .github/ 等）
        relative = path[len(prefix):]
        if any(seg.startswith(".") for seg in relative.split("/")[:-1]):
            continue

        # SKILL.md / agents/*.md / commands/*.md 检测
        # 用 path segments 判断（兼容 root plugin "skills/..." 与 nested "<x>/skills/..."）
        rel_segments = relative.split("/")
        if path.endswith("SKILL.md") and "skills" in rel_segments:
            skill_paths.append(path)
        elif path.endswith(".md") and "agents" in rel_segments:
            agent_paths.append(path)
        elif path.endswith(".md") and "commands" in rel_segments:
            command_paths.append(path)

    # de-dup（agents/commands 两条规则都可能命中）
    skill_paths = sorted(set(skill_paths))
    agent_paths = sorted(set(agent_paths))
    command_paths = sorted(set(command_paths))

    # skills_namespaces: <plugin-name>:<skill-name>
    plugin_name = target_root.rsplit("/", 1)[-1] if target_root else _root_plugin_name(plugin_json_path)
    skills_namespaces = [
        f"{plugin_name}:{_extract_skill_name(p, target_root)}"
        for p in skill_paths
    ]

    return PluginContent(
        plugin_root=target_root,
        plugin_json_path=plugin_json_path,
        skill_paths=skill_paths,
        agent_paths=agent_paths,
        command_paths=command_paths,
        skills_namespaces=skills_namespaces,
    )


def _scan_without_plugin_json(tree_paths: list[str], target_root: str) -> Optional[PluginContent]:
    """没有 plugin.json 标识 fallback：仅扫 SKILL.md/agents/commands 文件路径，不算 plugin。"""
    prefix = target_root + "/" if target_root else ""
    has_any = any(path.startswith(prefix) and (path.endswith("SKILL.md") or path.endswith(".md")) for path in tree_paths)
    if not has_any:
        return None
    return PluginContent(
        plugin_root=target_root,
        plugin_json_path="",  # absent
        skill_paths=[],
        agent_paths=[],
        command_paths=[],
        skills_namespaces=[],
    )


def _extract_skill_name(skill_path: str, plugin_root: str) -> str:
    """从 plugins/<plugin>/skills/<skill>/SKILL.md 提取 skill 名。"""
    rel = skill_path[len(plugin_root) + 1:] if plugin_root else skill_path
    # rel 形如 skills/<skill-name>/SKILL.md 或 skills/<skill-name>/<sub>/SKILL.md
    parts = rel.split("/")
    if len(parts) >= 3 and parts[0] == "skills":
        return parts[1]
    return parts[-2] if len(parts) >= 2 else "unknown"


def _root_plugin_name(plugin_json_path: str) -> str:
    """root level plugin.json — 没有 plugin name from path，用 plugin.json 的 name 字段 fallback。"""
    return "plugin"


# ---------------------------------------------------------------------------
# Install command extraction
# ---------------------------------------------------------------------------

# Install-related keywords / regex used to locate install snippets in README.
_INSTALL_KEYWORDS_RE = re.compile(
    r"(npm\s+install|/plugin\s+install|plugin\s+install|marketplace\s+add|"
    r"plugin\s+marketplace\s+add|claude\s+plugin\s+install|"
    r"pnpm\s+add|yarn\s+add|pip\s+install)",
    re.IGNORECASE,
)

# Section headers that signal an install section in README.
_INSTALL_HEADER_RE = re.compile(
    r"^#{1,6}\s+(?:installation|install|安装|setup|getting\s+started|快速开始|usage)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def extract_install_commands(
    plugin_json_data: Optional[dict],
    readme_content: str,
    repo: Optional[str] = None,
    plugin_name: Optional[str] = None,
) -> dict[str, Any]:
    """Extract install commands from plugin.json + README, plus a synthetic
    `marketplace add` fallback derived from repo / plugin_name.

    The synthetic fallback is the canonical install path for plugins
    distributed via marketplace.json (Anthropic / Obra / etc.), where neither
    plugin.json nor README contains the explicit `plugin marketplace add`
    command — it's documented at the marketplace root, not per plugin.

    Returns dict with:
      - commands: list[str]    each commandlike line containing an install keyword
      - raw_section: str       concatenation of plugin.json install field + matched
                                README sections + synthetic fallback (used for
                                downstream LLM context)
      - sources: list[str]     ["plugin.json", "readme:Installation", "synthetic", ...]
    """
    commands: list[str] = []
    raw_parts: list[str] = []
    sources: list[str] = []

    # 1) plugin.json `install` field — keep as JSON-stringified.
    if isinstance(plugin_json_data, dict):
        install_field = plugin_json_data.get("install")
        if install_field is not None:
            try:
                serialized = json.dumps(install_field, ensure_ascii=False, indent=2)
            except (TypeError, ValueError):
                serialized = str(install_field)
            raw_parts.append(f"### plugin.json :: install\n```json\n{serialized}\n```\n")
            sources.append("plugin.json")
            # Pull commandlike strings out of nested install spec when present.
            if isinstance(install_field, str):
                if _INSTALL_KEYWORDS_RE.search(install_field):
                    commands.append(install_field.strip())
            elif isinstance(install_field, dict):
                for v in install_field.values():
                    if isinstance(v, str) and _INSTALL_KEYWORDS_RE.search(v):
                        commands.append(v.strip())
            elif isinstance(install_field, list):
                for v in install_field:
                    if isinstance(v, str) and _INSTALL_KEYWORDS_RE.search(v):
                        commands.append(v.strip())

    # 2) README sections — find headers like ## Installation / ## 安装 / ## Setup
    #    and capture content until the next same-or-higher-level header.
    if readme_content:
        # Build header index (start positions).
        headers: list[tuple[int, int, str]] = []  # (pos, level, title)
        for m in re.finditer(r"^(#{1,6})\s+(.+?)\s*$", readme_content, re.MULTILINE):
            headers.append((m.start(), len(m.group(1)), m.group(2).strip()))

        for idx, (pos, level, title) in enumerate(headers):
            if not _INSTALL_HEADER_RE.match(f"{'#' * level} {title}"):
                continue
            # Section ends at the next header of <= same level, or EOF.
            end = len(readme_content)
            for npos, nlevel, _ in headers[idx + 1:]:
                if nlevel <= level:
                    end = npos
                    break
            section = readme_content[pos:end].strip()
            raw_parts.append(f"### README :: {title}\n{section}\n")
            sources.append(f"readme:{title}")
            # Extract commandlike lines (any line in fences or backtick line that has a keyword).
            for line in section.splitlines():
                stripped = line.strip().lstrip("`$ ").rstrip("`")
                if not stripped:
                    continue
                if _INSTALL_KEYWORDS_RE.search(stripped):
                    if stripped not in commands:
                        commands.append(stripped)

        # 3) Fallback — if no install header but README still mentions install
        #    keywords inside fenced blocks, pull those lines too.
        if not any(s.startswith("readme:") for s in sources):
            for m in re.finditer(r"```[a-zA-Z]*\n(.*?)```", readme_content, re.DOTALL):
                block = m.group(1)
                for line in block.splitlines():
                    stripped = line.strip().lstrip("$ ").strip()
                    if stripped and _INSTALL_KEYWORDS_RE.search(stripped):
                        if stripped not in commands:
                            commands.append(stripped)
                            if "readme:fenced" not in sources:
                                sources.append("readme:fenced")
                                raw_parts.append(
                                    f"### README :: (fenced install snippet)\n```\n{block.strip()}\n```\n"
                                )

    # 4) Synthetic fallback — canonical Claude Code marketplace install path.
    # Always emitted (even when README has install info) so the catalog entry
    # downstream has a deterministic command to display. Mirrors the
    # `install: {method, marketplace, plugin_name}` shape sync_plugins_official
    # writes today.
    if repo or plugin_name:
        marketplace_ref = repo or plugin_name or ""
        plugin_ref = plugin_name or (repo.rsplit("/", 1)[-1] if repo else "")
        synthetic_lines = [
            f"/plugin marketplace add {marketplace_ref}",
        ]
        if plugin_ref:
            synthetic_lines.append(f"/plugin install {plugin_ref}")
        # only append synthetic if not already present
        for sl in synthetic_lines:
            if sl not in commands:
                commands.append(sl)
        raw_parts.append(
            "### synthetic :: marketplace install (Claude Code default)\n"
            "```\n" + "\n".join(synthetic_lines) + "\n```\n"
        )
        sources.append("synthetic")

    return {
        "commands": commands,
        "raw_section": "\n".join(raw_parts),
        "sources": sources,
    }


def normalize_content(
    repo: str,
    ref: str,
    plugin: PluginContent,
    plugin_json_data: Optional[dict] = None,
    size_cap: int = 600_000,  # ~150k tokens (~15% MiMo 1M context)
    install_section: Optional[dict[str, Any]] = None,
) -> tuple[str, dict[str, Any]]:
    """全拼接归一化：plugin.json + 各 SKILL.md + agents + commands。

    超 size_cap 时降级：SKILL.md 按字母序仅前 5 个全文 + 其他仅 frontmatter；
    agents/commands 仅取前 5 个全文。这是为了应对 affaan-m 这种 3MB 超大 plugin。

    返回 (normalized_text, stats)。
    """
    parts = []
    stats = {
        "files_fetched": 0,
        "files_failed": 0,
        "total_bytes": 0,
        "truncated": False,
        "by_type": {"plugin_json": 0, "skill": 0, "agent": 0, "command": 0},
    }

    # plugin.json
    if plugin.plugin_json_path:
        if plugin_json_data is None:
            content = fetch_raw(repo, ref, plugin.plugin_json_path)
        else:
            content = json.dumps(plugin_json_data, indent=2)
        if content:
            parts.append(f"## plugin.json\n```json\n{content}\n```\n")
            stats["files_fetched"] += 1
            stats["total_bytes"] += len(content)
            stats["by_type"]["plugin_json"] += 1
        else:
            stats["files_failed"] += 1

    # Install section (kept as a separate normalized section so LLM sees it
    # alongside skills/agents/commands).
    if install_section and install_section.get("raw_section"):
        section_text = install_section["raw_section"]
        parts.append(f"## install\n{section_text}\n")
        stats["total_bytes"] += len(section_text)
        stats.setdefault("by_type", {}).setdefault("install", 0)
        stats["by_type"]["install"] = stats["by_type"].get("install", 0) + 1

    def _running_total() -> int:
        return sum(len(p) for p in parts)

    def _extract_frontmatter_or_first_lines(content: str, max_chars: int = 800) -> str:
        """提取 yaml frontmatter description + 第一段，或前 max_chars 字符。"""
        # YAML frontmatter
        m = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
        if m:
            front = m.group(1)
            after = content[m.end():]
            first_para = after.split("\n\n")[0] if after else ""
            return f"---\n{front}\n---\n\n{first_para[:max_chars]}"
        return content[:max_chars]

    def _add_file(path: str, kind: str, full: bool) -> None:
        content = fetch_raw(repo, ref, path)
        if content is None:
            stats["files_failed"] += 1
            return
        if not full:
            content = _extract_frontmatter_or_first_lines(content)
            stats["truncated"] = True
        parts.append(f"## {path}\n{content}\n")
        stats["files_fetched"] += 1
        stats["total_bytes"] += len(content)
        stats["by_type"][kind] += 1

    # SKILL.md：按字母序拼接，超 size_cap 后切到 frontmatter 模式
    sorted_skills = sorted(plugin.skill_paths)
    for i, path in enumerate(sorted_skills):
        full = _running_total() < size_cap or i < 5  # 超 cap 后仅前 5 全文
        _add_file(path, "skill", full=full)

    # agents：同样的 size_cap 策略
    sorted_agents = sorted(plugin.agent_paths)
    for i, path in enumerate(sorted_agents):
        full = _running_total() < size_cap or i < 5
        _add_file(path, "agent", full=full)

    # commands：同上
    sorted_commands = sorted(plugin.command_paths)
    for i, path in enumerate(sorted_commands):
        full = _running_total() < size_cap or i < 5
        _add_file(path, "command", full=full)

    return "\n".join(parts), stats


# ---------------------------------------------------------------------------
# LLM evaluation (real MiMo, not mocked)
# ---------------------------------------------------------------------------

def evaluate_with_llm(
    sample: Sample,
    content: str,
    label: str,
) -> dict[str, Any]:
    """调真 MiMo 跑 enrichment prompt。返回 {summary, summary_zh, tags, highlights, latency_ms, ok, error}."""
    system_prompt = """You are an evaluator for AI coding plugins. Output a JSON object with these fields:
- summary (English, 1-2 sentences, ~100 chars)
- summary_zh (中文, 1-2 句, ~50 字)
- tags (array of 5 keywords, lowercase)
- highlights (array of 3 bullets, 中英都可)
- tech_stack (array of relevant tech names, lowercase)

Be substantive. Reflect actual plugin capabilities, not generic install instructions.
Output ONLY the JSON object, no preamble."""

    user_prompt = f"""# Plugin: {sample.sid}

## Source
{sample.repo}/{sample.plugin_root if sample.plugin_root else '(root)'}

## Content
{content[:200000]}
"""

    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.0,
    }

    base = LLM_BASE_URL.rstrip("/")
    if base.endswith("/v1"):
        url = f"{base}/chat/completions"
    else:
        url = f"{base}/v1/chat/completions"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LLM_API_KEY}",
    }

    t0 = time.monotonic()
    try:
        resp = httpx.post(url, json=payload, headers=headers, timeout=300.0)
        latency_ms = int((time.monotonic() - t0) * 1000)
        resp.raise_for_status()
        data = resp.json()
        raw = data["choices"][0]["message"]["content"] or ""
        usage = data.get("usage", {})
        # 解析 JSON
        try:
            # 处理可能的 markdown fence
            cleaned = re.sub(r"^```(?:json)?\s*\n?|\n?```\s*$", "", raw.strip(), flags=re.MULTILINE)
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            # 尝试 freetext extraction
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            parsed = json.loads(m.group(0)) if m else {}

        return {
            "ok": True,
            "label": label,
            "latency_ms": latency_ms,
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "summary": parsed.get("summary", ""),
            "summary_zh": parsed.get("summary_zh", ""),
            "tags": parsed.get("tags", []),
            "highlights": parsed.get("highlights", []),
            "tech_stack": parsed.get("tech_stack", []),
            "raw": raw[:300],
        }
    except httpx.HTTPError as e:
        latency_ms = int((time.monotonic() - t0) * 1000)
        return {
            "ok": False,
            "label": label,
            "latency_ms": latency_ms,
            "error": str(e)[:200],
        }
    except Exception as e:
        return {
            "ok": False,
            "label": label,
            "error": f"{type(e).__name__}: {e}",
        }


# ---------------------------------------------------------------------------
# Catalog-shaped preview entry construction
# ---------------------------------------------------------------------------

_SLUG_RE = re.compile(r"[^a-z0-9-]+")


def _slugify(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[\s_./]+", "-", s)
    s = _SLUG_RE.sub("-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s


def build_catalog_preview_entry(
    sample: Sample,
    plugin: Optional[PluginContent],
    plugin_json_data: Optional[dict],
    bundle: dict[str, Any],
    install: dict[str, Any],
    eval_new: Optional[dict[str, Any]],
) -> dict[str, Any]:
    """Build a catalog-shaped preview entry mirroring catalog/plugins/index.json.

    This is a *preview* — we don't fill every field (e.g. health, freshness),
    just enough to demonstrate the shape is consistent post-PluginContentFetcher.
    """
    plugin_name = sample.sid
    if isinstance(plugin_json_data, dict) and plugin_json_data.get("name"):
        plugin_name = str(plugin_json_data["name"])

    description = ""
    if isinstance(plugin_json_data, dict):
        description = (plugin_json_data.get("description") or "").strip()

    eval_new = eval_new or {}
    summary = eval_new.get("summary", "") or ""
    summary_zh = eval_new.get("summary_zh", "") or ""
    tags = eval_new.get("tags") or []
    tech_stack = eval_new.get("tech_stack") or []
    highlights = eval_new.get("highlights") or []

    # install field — shape must match existing catalog entries
    # (`{method, marketplace, plugin_name}`) plus extra spike-only metadata
    # (`commands`, `sources`, `raw_section`) for review.
    install_entry: dict[str, Any] = {
        "method": "plugin_marketplace",
        "marketplace": sample.repo,
        "plugin_name": plugin_name,
        "commands": install.get("commands", []),
        "sources": install.get("sources", []),
    }

    # Source URL — mirror sync_plugins_official's _resolve_source_url logic by
    # using the GitHub repo URL.
    source_url = f"https://github.com/{sample.repo}"
    if sample.plugin_root:
        source_url += f"/tree/HEAD/{sample.plugin_root}"

    entry = {
        "id": _slugify(f"{sample.repo.replace('/', '-')}-{plugin_name}"),
        "name": plugin_name,
        "type": "plugin",
        "description": description or summary,
        "description_zh": summary_zh,
        "source_url": source_url,
        "category": "tooling",  # spike default — production sets via categorize()
        "tags": [t.lower() for t in tags if isinstance(t, str)],
        "tech_stack": [t.lower() for t in tech_stack if isinstance(t, str)],
        "source": "spike-preview",
        "source_priority": 0,
        "marketplace_url": None,
        "platforms": ["claude-code"],
        "install": install_entry,
        "bundle": bundle,
        "summary": summary,
        "summary_zh": summary_zh,
        "highlights": highlights,
        "manifest_completeness": 1.0 if isinstance(plugin_json_data, dict) else 0.0,
        "last_synced": time.strftime("%Y-%m-%d"),
        "stars": None,
        "pushed_at": None,
        "version": (plugin_json_data or {}).get("version", "") if isinstance(plugin_json_data, dict) else "",
        "_spike_meta": {
            "layout": sample.layout,
            "plugin_root": sample.plugin_root,
            "is_plugin": plugin is not None and bool(plugin.plugin_json_path),
            "skills_namespaces": bundle.get("skills_namespaces", []),
            "eval_new_ok": bool(eval_new.get("ok")),
        },
    }
    return entry


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def run_one_sample(sample: Sample, no_llm: bool = False) -> dict[str, Any]:
    """处理单个 sample，返回包含 layout/bundle/contents/eval 的报告。"""
    log.info("─── [%s] %s/%s ───", sample.sid, sample.repo, sample.plugin_root or "(root)")

    # 1. tree
    tree_data = fetch_tree(sample.repo)
    if "error" in tree_data:
        return {"sample": sample.sid, "fatal": tree_data.get("error")}

    tree_paths = [item["path"] for item in tree_data.get("tree", []) if item.get("type") == "blob"]

    # 2. layout detect
    plugin = detect_plugin(tree_paths, sample.plugin_root)
    plugin_json_data: Optional[dict] = None
    readme_path = (sample.plugin_root + "/" if sample.plugin_root else "") + "README.md"
    readme_content = fetch_raw(sample.repo, "HEAD", readme_path) or ""

    # plugin name hint — used for synthetic install fallback
    plugin_name_hint = (
        sample.plugin_root.rsplit("/", 1)[-1]
        if sample.plugin_root
        else sample.repo.rsplit("/", 1)[-1]
    )

    if plugin is None:
        # README-only / fallback
        bundle = {"skills_count": 0, "agents_count": 0, "commands_count": 0, "skills_namespaces": []}
        install = extract_install_commands(
            None, readme_content,
            repo=sample.repo, plugin_name=plugin_name_hint,
        )
        install_block = ""
        if install.get("raw_section"):
            install_block = f"## install\n{install['raw_section']}\n"
        new_content = (readme_content + ("\n" + install_block if install_block else ""))
        baseline_content = readme_content
        baseline_size = len(baseline_content)
        new_size = len(new_content)
        is_plugin = False
    else:
        is_plugin = bool(plugin.plugin_json_path)
        bundle = {
            "skills_count": len(plugin.skill_paths),
            "agents_count": len(plugin.agent_paths),
            "commands_count": len(plugin.command_paths),
            "skills_namespaces": plugin.skills_namespaces,
        }
        # plugin.json data — pulled once and reused for install extraction + entry build
        if plugin.plugin_json_path:
            raw_json = fetch_raw(sample.repo, "HEAD", plugin.plugin_json_path)
            if raw_json:
                try:
                    plugin_json_data = json.loads(raw_json)
                except json.JSONDecodeError:
                    plugin_json_data = None
        # prefer plugin.json `name` for synthetic fallback when present
        if isinstance(plugin_json_data, dict) and plugin_json_data.get("name"):
            plugin_name_hint = str(plugin_json_data["name"])
        install = extract_install_commands(
            plugin_json_data, readme_content,
            repo=sample.repo, plugin_name=plugin_name_hint,
        )
        new_content, fetch_stats = normalize_content(
            sample.repo, "HEAD", plugin,
            plugin_json_data=plugin_json_data,
            install_section=install,
        )
        new_size = len(new_content)
        # baseline: 仅 plugin_root/README.md
        baseline_content = readme_content
        baseline_size = len(baseline_content)

    log.info(
        "  layout: %s | bundle skills=%d agents=%d commands=%d | content baseline=%dB new=%dB",
        sample.layout, bundle["skills_count"], bundle["agents_count"], bundle["commands_count"],
        baseline_size, new_size,
    )

    # 3. expected vs actual bundle
    bundle_match = (
        bundle["skills_count"] == sample.expected_skills_count
        and bundle["agents_count"] == sample.expected_agents_count
        and bundle["commands_count"] == sample.expected_commands_count
    )

    # install keyword match
    install_kw_hit = any(
        any(kw.lower() in cmd.lower() for cmd in install.get("commands", []))
        or kw.lower() in install.get("raw_section", "").lower()
        or kw.lower() in new_content.lower()
        for kw in (sample.expected_install_keywords or [])
    ) if sample.expected_install_keywords else None

    result: dict[str, Any] = {
        "sample": sample.sid,
        "repo": sample.repo,
        "plugin_root": sample.plugin_root,
        "layout": sample.layout,
        "is_plugin": is_plugin,
        "bundle": bundle,
        "expected_bundle": {
            "skills_count": sample.expected_skills_count,
            "agents_count": sample.expected_agents_count,
            "commands_count": sample.expected_commands_count,
        },
        "bundle_match": bundle_match,
        "baseline_size": baseline_size,
        "new_size": new_size,
        "size_ratio": new_size / max(baseline_size, 1),
        "install": {
            "commands": install.get("commands", []),
            "sources": install.get("sources", []),
            "command_count": len(install.get("commands", [])),
        },
        "install_keyword_hit": install_kw_hit,
    }

    eval_new_for_preview: Optional[dict[str, Any]] = None

    if no_llm or not LLM_API_KEY:
        if not LLM_API_KEY and not no_llm:
            log.warning("无 LLM_API_KEY，跳过 LLM evaluation")
        # Build catalog preview entry with empty enrichment so shape can still be reviewed.
        result["catalog_preview"] = build_catalog_preview_entry(
            sample, plugin, plugin_json_data, bundle, install, eval_new_for_preview
        )
        return result

    eval_baseline = evaluate_with_llm(sample, baseline_content or "(empty README)", "baseline")
    eval_new = evaluate_with_llm(sample, new_content or "(empty content)", "new")

    result["eval_baseline"] = eval_baseline
    result["eval_new"] = eval_new
    eval_new_for_preview = eval_new

    # Build catalog-shaped preview entry
    result["catalog_preview"] = build_catalog_preview_entry(
        sample, plugin, plugin_json_data, bundle, install, eval_new_for_preview
    )

    # 5. expected keyword 匹配率
    def _kw_hit(eval_data: dict, keywords: list[str]) -> dict[str, bool]:
        if not eval_data.get("ok"):
            return {kw: False for kw in keywords}
        searchable = " ".join([
            str(eval_data.get("summary", "")),
            str(eval_data.get("summary_zh", "")),
            " ".join(eval_data.get("tags", [])),
            " ".join(eval_data.get("highlights", [])),
            " ".join(eval_data.get("tech_stack", [])),
        ]).lower()
        return {kw: kw.lower() in searchable for kw in keywords}

    result["keyword_hits_baseline"] = _kw_hit(eval_baseline, sample.expected_keywords)
    result["keyword_hits_new"] = _kw_hit(eval_new, sample.expected_keywords)

    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=20, help="跑前 N 个 sample（默认 20）")
    parser.add_argument("--no-llm", action="store_true", help="跳过 LLM 调用，仅测 layout / bundle")
    parser.add_argument("--concurrency", type=int, default=4, help="LLM 并发（默认 4）")
    parser.add_argument("--output", default="/tmp/plugin_content_spike_report.json")
    parser.add_argument("--catalog-output", default="/tmp/spike_catalog_preview.json",
                        help="catalog-shaped preview entries 输出路径")
    parser.add_argument("--filter", default="", help="只跑 sid 匹配的 sample（substring）")
    args = parser.parse_args(argv)

    samples = SAMPLES[: args.samples]
    if args.filter:
        samples = [s for s in samples if args.filter in s.sid]

    log.info("Spike start: %d samples, concurrency=%d, no_llm=%s", len(samples), args.concurrency, args.no_llm)
    log.info("LLM_BASE_URL=%s LLM_MODEL=%s", LLM_BASE_URL, LLM_MODEL)

    results = []
    if args.no_llm:
        # 顺序跑（layout/bundle 是 GitHub API IO，并发收益小）
        for s in samples:
            results.append(run_one_sample(s, no_llm=True))
    else:
        # LLM 阶段并发
        with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            futures = {pool.submit(run_one_sample, s, False): s for s in samples}
            for fut in as_completed(futures):
                results.append(fut.result())

    # 总结
    log.info("\n" + "=" * 70)
    log.info("总结报告")
    log.info("=" * 70)

    layout_match = sum(1 for r in results if r.get("is_plugin") is not False or r.get("layout", "").startswith("L6"))
    bundle_match = sum(1 for r in results if r.get("bundle_match"))
    log.info("Layout detection (plugin 边界识别): %d/%d", layout_match, len(results))
    log.info("Bundle 字段匹配 ground truth: %d/%d", bundle_match, len(results))

    sizes_baseline = [r.get("baseline_size", 0) for r in results]
    sizes_new = [r.get("new_size", 0) for r in results]
    log.info("Baseline size 范围: %d - %d (avg %d)", min(sizes_baseline) if sizes_baseline else 0, max(sizes_baseline) if sizes_baseline else 0, sum(sizes_baseline) // max(len(sizes_baseline), 1))
    log.info("New      size 范围: %d - %d (avg %d)", min(sizes_new) if sizes_new else 0, max(sizes_new) if sizes_new else 0, sum(sizes_new) // max(len(sizes_new), 1))
    log.info("Size 平均放大倍数: %.1fx", (sum(sizes_new) / max(sum(sizes_baseline), 1)) if sizes_baseline else 0)

    if not args.no_llm:
        ok_baseline = sum(1 for r in results if r.get("eval_baseline", {}).get("ok"))
        ok_new = sum(1 for r in results if r.get("eval_new", {}).get("ok"))
        log.info("LLM eval 成功率: baseline %d/%d, new %d/%d", ok_baseline, len(results), ok_new, len(results))

        # token 消耗
        toks_b = sum(r.get("eval_baseline", {}).get("prompt_tokens", 0) for r in results)
        toks_n = sum(r.get("eval_new", {}).get("prompt_tokens", 0) for r in results)
        log.info("Total prompt tokens: baseline %d, new %d (放大 %.1fx)", toks_b, toks_n, toks_n / max(toks_b, 1))

        # latency
        lats_b = [r.get("eval_baseline", {}).get("latency_ms", 0) for r in results if r.get("eval_baseline", {}).get("ok")]
        lats_n = [r.get("eval_new", {}).get("latency_ms", 0) for r in results if r.get("eval_new", {}).get("ok")]
        if lats_b:
            log.info("Baseline latency p50/p95: %d / %d ms", sorted(lats_b)[len(lats_b)//2], sorted(lats_b)[int(len(lats_b)*0.95)])
        if lats_n:
            log.info("New      latency p50/p95: %d / %d ms", sorted(lats_n)[len(lats_n)//2], sorted(lats_n)[int(len(lats_n)*0.95)])

        # keyword hit rate
        baseline_hits = sum(sum(r.get("keyword_hits_baseline", {}).values()) for r in results)
        new_hits = sum(sum(r.get("keyword_hits_new", {}).values()) for r in results)
        total_kws = sum(len(r.get("keyword_hits_baseline", {})) for r in results)
        log.info("Expected keyword 命中率: baseline %d/%d (%.0f%%), new %d/%d (%.0f%%)",
                 baseline_hits, total_kws, baseline_hits/max(total_kws,1)*100,
                 new_hits, total_kws, new_hits/max(total_kws,1)*100)

    # install command coverage
    install_hit = sum(1 for r in results if r.get("install_keyword_hit") is True)
    install_total = sum(1 for r in results if r.get("install_keyword_hit") is not None)
    if install_total:
        log.info("Install keyword 命中率: %d/%d", install_hit, install_total)
    install_cmd_counts = [r.get("install", {}).get("command_count", 0) for r in results]
    if install_cmd_counts:
        log.info(
            "Install commands: min=%d max=%d avg=%.1f (samples with ≥1 cmd: %d/%d)",
            min(install_cmd_counts), max(install_cmd_counts),
            sum(install_cmd_counts) / max(len(install_cmd_counts), 1),
            sum(1 for c in install_cmd_counts if c > 0), len(install_cmd_counts),
        )

    # 写完整报告
    with open(args.output, "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)
    log.info("\n完整报告写入: %s", args.output)

    # 写 catalog-shaped preview entries（仅含 catalog_preview 字段）
    catalog_entries = [r["catalog_preview"] for r in results if r.get("catalog_preview")]
    with open(args.catalog_output, "w") as f:
        json.dump(catalog_entries, f, ensure_ascii=False, indent=2, default=str)
    log.info("Catalog preview 写入: %s (%d entries)", args.catalog_output, len(catalog_entries))
    return 0


if __name__ == "__main__":
    sys.exit(main())
