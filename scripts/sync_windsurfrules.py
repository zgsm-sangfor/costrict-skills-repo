#!/usr/bin/env python3
"""Sync rules from awesome-windsurfrules (SchneiderSam + balqaasem mirrors)."""

import os
import re
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(__file__))
from utils import (  # noqa: E402
    fetch_raw_content,
    github_api,
    categorize,
    extract_tags,
    to_kebab_case,
    save_index,
    logger,
)

CATALOG_DIR = os.path.join(os.path.dirname(__file__), "..", "catalog", "rules")
OUTPUT_PATH = os.path.join(CATALOG_DIR, "windsurfrules_index.json")
CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", ".windsurfrules_cache")
LAST_SYNC_PATH = os.path.join(CACHE_DIR, "last_sync.txt")
TODAY = date.today().isoformat()

# 两个仓库及其在 id 后缀中使用的 slug
REPOS = [
    ("SchneiderSam/awesome-windsurfrules", "schneidersam"),
    ("balqaasem/awesome-windsurfrules", "balqaasem"),
]

SOURCE_NAME = "awesome-windsurfrules"


def parse_frontmatter(content: str) -> tuple[dict, str]:
    """Parse YAML-style frontmatter without external deps; returns (dict, body)."""
    if not content:
        return {}, content or ""
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", content, re.DOTALL)
    if not m:
        return {}, content
    raw_block = m.group(1)
    body = m.group(2)
    fm: dict = {}
    for line in raw_block.splitlines():
        line = line.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        kv = re.match(r"^\s*([A-Za-z0-9_\-]+)\s*:\s*(.*)$", line)
        if not kv:
            continue
        key = kv.group(1).strip().lower()
        val = kv.group(2).strip()
        # 去掉成对引号
        if (val.startswith('"') and val.endswith('"')) or (
            val.startswith("'") and val.endswith("'")
        ):
            val = val[1:-1]
        # tags 字段允许 [a, b] / a, b / 单值
        if key == "tags":
            stripped = val.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                stripped = stripped[1:-1]
            parts = [p.strip().strip('"').strip("'") for p in stripped.split(",")]
            fm[key] = [p for p in parts if p]
        else:
            fm[key] = val
    return fm, body


def _first_meaningful_line(body: str, limit: int = 200) -> str:
    """Deprecated: 保留以备旧调用点，新代码请用 _extract_description。"""
    for raw in (body or "").splitlines():
        line = raw.strip().strip("#").strip()
        if not line:
            continue
        if line.startswith("!") or line.startswith("["):
            continue
        if line == "---" or line.startswith("---"):
            continue
        return line[:limit]
    return ""


def _extract_description(body: str, limit: int = 300) -> str:
    """Extract description from awesome-list README body.

    §14 修复 C：awesome-windsurfrules 的真实规则内容写在第一段 ``` ``` ```
    code block 内（如 ``` ```js ... ``` ```），上一版 _first_meaningful_line
    会跳过 fence 行而把文件名占位符当成描述（≤50 字符），导致 LLM 误评。

    Strategy:
    1. 第一行的 H1 (``# Title``) 作为前缀
    2. 抓第一个 code block 的内容；只要其中非空就用它（截断到 limit）
    3. 无 code block → 退回到第一段非图片/非链接的纯文本行拼接
    4. 都没有 → 返回 H1 标题 / 空字符串
    """
    if not body:
        return ""
    lines = body.splitlines()
    title = ""
    in_code_block = False
    code_lines: list[str] = []
    paragraph_lines: list[str] = []
    code_block_done = False
    for raw in lines:
        stripped = raw.strip()
        if not title and stripped.startswith("# "):
            title = stripped.lstrip("#").strip()
            continue
        if stripped.startswith("```"):
            if in_code_block:
                # 第一个 code block 结束 → 已收集到内容，停止后续处理
                in_code_block = False
                if code_lines:
                    code_block_done = True
                    break
            else:
                in_code_block = True
            continue
        if in_code_block:
            code_lines.append(raw)
        elif stripped and not stripped.startswith(("!", "[", "---")):
            paragraph_lines.append(stripped)

    body_text = ""
    if code_block_done and code_lines:
        body_text = "\n".join(code_lines).strip()
    elif paragraph_lines:
        body_text = " ".join(paragraph_lines).strip()

    if not body_text:
        return title[:limit]
    if title:
        combined = f"{title}: {body_text}"
        return combined[:limit]
    return body_text[:limit]


def _extract_slug_from_path(path: str) -> str:
    """rules/global_rules/<slug>/global_rules.md → <slug>; fallback 用 basename。"""
    parts = path.split("/")
    if len(parts) >= 3:
        return parts[-2]
    base = parts[-1]
    base = re.sub(r"\.md$", "", base, flags=re.IGNORECASE)
    return base


def _is_global_rule_path(path: str) -> bool:
    return path.lower().startswith("rules/global_rules/")


def _is_supported_md(path: str) -> bool:
    if not path.lower().endswith(".md"):
        return False
    return path.lower().startswith("rules/")


def _list_md_paths(repo: str, branch: str) -> list[str]:
    """通过 git tree API 一次拿全部 .md 文件，返回路径列表。"""
    data = github_api(f"repos/{repo}/git/trees/{branch}?recursive=1")
    if not data or "tree" not in data:
        return []
    paths: list[str] = []
    for item in data["tree"]:
        if item.get("type") != "blob":
            continue
        p = item.get("path") or ""
        if _is_supported_md(p):
            paths.append(p)
    return paths


def _build_entry(repo: str, repo_slug: str, branch: str, path: str,
                 content: str | None) -> dict | None:
    """根据 path + 内容产出一条 entry；content 缺失也允许（仅靠路径生成元数据）。"""
    slug = _extract_slug_from_path(path)
    if not slug:
        return None

    fm, body = parse_frontmatter(content or "")

    # 名称：frontmatter > 路径 slug
    name_raw = fm.get("name") or fm.get("title") or slug
    name = name_raw if isinstance(name_raw, str) else slug
    name_pretty = name.replace("-", " ").replace("_", " ").strip().title()

    # 描述：frontmatter description > body 第一段 > 占位
    description = ""
    desc_fm = fm.get("description")
    if isinstance(desc_fm, str) and desc_fm.strip():
        description = desc_fm.strip()[:300]
    if not description:
        description = _extract_description(body)
    if not description:
        description = f"Windsurf rules for {slug.replace('-', ' ')}"

    is_global = _is_global_rule_path(path)

    # tags：frontmatter tags + 自动 extract + global 标记
    fm_tags = fm.get("tags")
    if isinstance(fm_tags, list):
        explicit_tags = [str(t).strip().lower() for t in fm_tags if str(t).strip()]
    elif isinstance(fm_tags, str) and fm_tags.strip():
        explicit_tags = [t.strip().lower() for t in fm_tags.split(",") if t.strip()]
    else:
        explicit_tags = []

    derived_tags = extract_tags(slug, description)
    tags: list[str] = []
    seen: set[str] = set()
    for t in explicit_tags + derived_tags:
        if t and t not in seen:
            seen.add(t)
            tags.append(t)
    if is_global and "windsurf-global" not in seen:
        tags.append("windsurf-global")
        seen.add("windsurf-global")
    if "windsurf" not in seen:
        tags.append("windsurf")

    # category：global → "tooling"（catalog enum 不含 "global"，以 windsurf-global tag 区分）
    if is_global:
        category = "tooling"
    else:
        cat_fm = fm.get("category")
        if isinstance(cat_fm, str) and cat_fm.strip():
            category = cat_fm.strip().lower()
        else:
            category = categorize(slug, description, tags)

    raw_url = f"https://raw.githubusercontent.com/{repo}/{branch}/{path}"
    blob_url = f"https://github.com/{repo}/blob/{branch}/{path}"

    entry_id = f"{to_kebab_case(slug)}-{repo_slug}"

    return {
        "id": entry_id,
        "name": f"{name_pretty} (Windsurf{' Global' if is_global else ''})",
        "type": "rule",
        "description": description,
        "source_url": blob_url,
        "stars": None,
        "pushed_at": None,
        "category": category,
        "tags": tags,
        "tech_stack": [],
        "install": {
            "method": "download_file",
            "files": [raw_url],
        },
        "source": SOURCE_NAME,
        "last_synced": TODAY,
    }


def parse_repo(repo: str, repo_slug: str) -> list[dict]:
    repo_info = github_api(f"repos/{repo}")
    if not repo_info:
        logger.warning(f"Skip {repo}: repo metadata unavailable (404 or rate limited)")
        return []
    branch = repo_info.get("default_branch") or "main"
    pushed_at = repo_info.get("pushed_at")
    stars = repo_info.get("stargazers_count")

    paths = _list_md_paths(repo, branch)
    if not paths:
        logger.warning(f"Skip {repo}: no .md files under rules/")
        return []

    entries: list[dict] = []
    for p in paths:
        content = fetch_raw_content(repo, p, branch=branch, quiet_404=True)
        if content is None:
            logger.debug(f"Skip {repo}:{p}: fetch failed")
            continue
        entry = _build_entry(repo, repo_slug, branch, p, content)
        if not entry:
            continue
        entry["pushed_at"] = pushed_at
        entry["stars"] = stars
        entries.append(entry)

    logger.info(f"Parsed {len(entries)} entries from {repo}")
    return entries


def sync() -> int:
    os.makedirs(CACHE_DIR, exist_ok=True)
    all_entries: list[dict] = []
    failed_repos = 0
    for repo, repo_slug in REPOS:
        try:
            entries = parse_repo(repo, repo_slug)
        except Exception as e:
            logger.error(f"Unexpected error parsing {repo}: {e}")
            entries = []
        if not entries:
            failed_repos += 1
        all_entries.extend(entries)

    if failed_repos == len(REPOS):
        logger.error("All windsurfrules repos failed; aborting with exit 1")
        return 1

    all_entries.sort(key=lambda e: e.get("id", ""))
    save_index(all_entries, OUTPUT_PATH)
    with open(LAST_SYNC_PATH, "w", encoding="utf-8") as f:
        f.write(TODAY)
    return 0


if __name__ == "__main__":
    sys.exit(sync())
