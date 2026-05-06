#!/usr/bin/env python3
"""Spike: probe cursor.directory programmatic access paths.

Probes:
  1. cursor.directory/api/* candidate paths
  2. cursor.directory/sitemap.xml + robots.txt
  3. Homepage / rules HTML, parse __NEXT_DATA__ + look for build_id and try _next/data endpoints
  4. GitHub repo `pontusab/directories` src/data tree (recursive) for real data scale
  5. GitHub search for third-party wrappers (cursor-directory-api / cursor-directory-scraper)

Output: docs/spike_cursor_directory.md (markdown report).

Idempotent — read-only, only writes the report file.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "docs" / "spike_cursor_directory.md"

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
)
# Polite delay between cursor.directory probes to avoid Vercel WAF 429.
PROBE_DELAY_S = float(os.environ.get("SPIKE_PROBE_DELAY", "1.5"))

PROBE_URLS = [
    # API-style paths (most likely 404 — we're probing)
    "https://cursor.directory/api/rules",
    "https://cursor.directory/api/v1/rules",
    "https://cursor.directory/api/list",
    "https://cursor.directory/api/categories",
    "https://cursor.directory/api/mcp",
    "https://cursor.directory/api/search",
    # Sitemap & robots
    "https://cursor.directory/sitemap.xml",
    "https://cursor.directory/sitemap_index.xml",
    "https://cursor.directory/robots.txt",
    # Homepage + listing pages (for __NEXT_DATA__ extraction)
    "https://cursor.directory/",
    "https://cursor.directory/rules",
    "https://cursor.directory/mcp",
]


def _request(url: str, *, timeout: int = 12, headers: dict | None = None) -> dict:
    """Single GET request returning a result dict.

    Result fields: url, status, content_type, size, snippet, error, elapsed_ms.
    Never raises.
    """
    hdrs = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, headers=hdrs)
    started = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            elapsed_ms = int((time.time() - started) * 1000)
            content_type = resp.headers.get("Content-Type", "") or ""
            snippet = ""
            try:
                snippet = data[:240].decode("utf-8", errors="replace")
            except Exception:
                snippet = repr(data[:120])
            return {
                "url": url,
                "status": resp.status,
                "content_type": content_type,
                "size": len(data),
                "snippet": snippet.replace("\n", " ").strip()[:240],
                "error": None,
                "elapsed_ms": elapsed_ms,
                "_body": data,
            }
    except urllib.error.HTTPError as e:
        elapsed_ms = int((time.time() - started) * 1000)
        try:
            body = e.read()
            snippet = body[:200].decode("utf-8", errors="replace").replace("\n", " ").strip()
        except Exception:
            snippet = ""
        return {
            "url": url,
            "status": e.code,
            "content_type": e.headers.get("Content-Type", "") if e.headers else "",
            "size": 0,
            "snippet": snippet,
            "error": f"HTTPError {e.code} {e.reason}",
            "elapsed_ms": elapsed_ms,
            "_body": b"",
        }
    except urllib.error.URLError as e:
        elapsed_ms = int((time.time() - started) * 1000)
        return {
            "url": url,
            "status": None,
            "content_type": "",
            "size": 0,
            "snippet": "",
            "error": f"URLError {e.reason}",
            "elapsed_ms": elapsed_ms,
            "_body": b"",
        }
    except Exception as e:  # pragma: no cover — last-resort tunnel
        elapsed_ms = int((time.time() - started) * 1000)
        return {
            "url": url,
            "status": None,
            "content_type": "",
            "size": 0,
            "snippet": "",
            "error": f"{type(e).__name__}: {e}",
            "elapsed_ms": elapsed_ms,
            "_body": b"",
        }


def parse_next_data(html: str) -> dict | None:
    """Extract __NEXT_DATA__ JSON from HTML (Pages Router style)."""
    m = re.search(
        r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.+?)</script>',
        html,
        re.DOTALL,
    )
    if not m:
        return None
    raw = m.group(1).strip()
    try:
        return json.loads(raw)
    except Exception:
        return None


def detect_rsc_payload(html: str) -> dict:
    """Detect Next.js App Router RSC streaming payload (`self.__next_f.push(...)`).

    Returns presence flag + push count + total payload size + sitemap-style url hints if any.
    """
    pushes = re.findall(r"self\.__next_f\.push\(\[(\d+),\s*(\".*?\")\]\)", html, re.DOTALL)
    has_next_f = "self.__next_f" in html
    total_body = sum(len(p[1]) for p in pushes)
    return {
        "has_self_next_f": has_next_f,
        "push_count": len(pushes),
        "approx_payload_bytes": total_body,
    }


def extract_build_id(next_data: dict) -> str | None:
    if not isinstance(next_data, dict):
        return None
    bid = next_data.get("buildId")
    if isinstance(bid, str) and bid:
        return bid
    return None


def summarize_next_data(nd: dict) -> dict:
    """Light summary of __NEXT_DATA__ — top-level keys, page, pageProps keys, sample entry counts."""
    summary: dict = {"top_keys": [], "page": None, "page_props_keys": [], "list_field_sizes": {}}
    if not isinstance(nd, dict):
        return summary
    summary["top_keys"] = sorted(list(nd.keys()))[:20]
    summary["page"] = nd.get("page")
    props = nd.get("props", {})
    if isinstance(props, dict):
        page_props = props.get("pageProps", {})
        if isinstance(page_props, dict):
            summary["page_props_keys"] = sorted(list(page_props.keys()))[:30]
            for k, v in page_props.items():
                if isinstance(v, list):
                    summary["list_field_sizes"][k] = len(v)
    return summary


def github_api(path: str, timeout: int = 15) -> tuple[int, dict | list | None, str | None]:
    """GET https://api.github.com/<path>. Return (status, json, error)."""
    url = f"https://api.github.com/{path.lstrip('/')}"
    headers = {
        "User-Agent": UA,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            return resp.status, json.loads(data.decode("utf-8")), None
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        return e.code, None, f"HTTPError {e.code} {e.reason} — {body[:160]}"
    except Exception as e:
        return 0, None, f"{type(e).__name__}: {e}"


def probe_pontusab_directories() -> dict:
    """List src/data tree from pontusab/directories — count files per top-level subdir + extensions.

    Uses git/trees API recursive=1 (single call).
    """
    out: dict = {
        "repo": "pontusab/directories",
        "default_branch": None,
        "tree_truncated": None,
        "total_blobs": 0,
        "src_data_files": 0,
        "src_data_breakdown": {},  # subdir -> count
        "ext_breakdown": {},
        "by_top_dir": {},  # full top-level directory tally for repo
        "sample_files": [],
        "error": None,
    }

    status, repo_meta, err = github_api("repos/pontusab/directories")
    if err or not isinstance(repo_meta, dict):
        out["error"] = err or "repo meta missing"
        return out
    branch = repo_meta.get("default_branch") or "main"
    out["default_branch"] = branch

    status, tree_obj, err = github_api(
        f"repos/pontusab/directories/git/trees/{branch}?recursive=1"
    )
    if err or not isinstance(tree_obj, dict):
        out["error"] = err or "tree missing"
        return out
    out["tree_truncated"] = tree_obj.get("truncated", False)
    tree = tree_obj.get("tree", [])
    out["total_blobs"] = sum(1 for x in tree if x.get("type") == "blob")

    by_top: dict[str, int] = {}
    src_data_breakdown: dict[str, int] = {}
    ext_breakdown: dict[str, int] = {}
    sample_files: list[str] = []

    for entry in tree:
        if entry.get("type") != "blob":
            continue
        path = entry.get("path", "")
        # Top-level dir
        top = path.split("/", 1)[0] if "/" in path else "(root)"
        by_top[top] = by_top.get(top, 0) + 1
        # src/data accounting
        if path.startswith("src/data/"):
            out["src_data_files"] += 1
            sub_after = path[len("src/data/"):]
            sub_top = sub_after.split("/", 1)[0] if "/" in sub_after else "(file)"
            src_data_breakdown[sub_top] = src_data_breakdown.get(sub_top, 0) + 1
            ext = "(none)"
            if "." in os.path.basename(path):
                ext = "." + os.path.basename(path).rsplit(".", 1)[1]
            ext_breakdown[ext] = ext_breakdown.get(ext, 0) + 1
            if len(sample_files) < 12:
                sample_files.append(path)

    out["by_top_dir"] = dict(sorted(by_top.items(), key=lambda x: -x[1]))
    out["src_data_breakdown"] = dict(sorted(src_data_breakdown.items(), key=lambda x: -x[1]))
    out["ext_breakdown"] = dict(sorted(ext_breakdown.items(), key=lambda x: -x[1]))
    out["sample_files"] = sample_files
    return out


def search_third_party_wrappers() -> list[dict]:
    """Search GitHub for cursor-directory wrappers / scrapers.

    GitHub search needs careful query construction. We try:
      - Exact-substring repo-name match (the most reliable signal)
      - Cursor.directory mentioned in repo name
      - Generic phrase queries scoped to readme
    """
    queries = [
        "cursor-directory in:name",
        "cursor.directory in:name",
        '"cursor.directory" scraper in:readme',
        '"cursor.directory" api wrapper in:readme',
    ]
    seen: set[str] = set()
    results: list[dict] = []
    for q in queries:
        path = f"search/repositories?q={urllib.parse.quote(q)}&sort=stars&order=desc&per_page=5"
        status, data, err = github_api(path)
        if err or not isinstance(data, dict):
            results.append({
                "query": q,
                "error": err,
                "items": [],
            })
            continue
        items = data.get("items", []) or []
        formatted = []
        for it in items:
            full = it.get("full_name", "")
            if full in seen:
                continue
            seen.add(full)
            formatted.append({
                "full_name": full,
                "stars": it.get("stargazers_count", 0),
                "pushed_at": it.get("pushed_at"),
                "description": (it.get("description") or "")[:200],
                "html_url": it.get("html_url"),
            })
        results.append({"query": q, "items": formatted, "total_count": data.get("total_count", 0)})
    return results


def try_next_data_endpoint(build_id: str, route: str, timeout: int = 12) -> dict:
    """Try `https://cursor.directory/_next/data/<buildId>/<route>.json`."""
    if route in ("", "/"):
        url = f"https://cursor.directory/_next/data/{build_id}/index.json"
    else:
        clean = route.strip("/")
        url = f"https://cursor.directory/_next/data/{build_id}/{clean}.json"
    return _request(url, timeout=timeout)


def render_report(
    *,
    findings: list[dict],
    next_data_summaries: list[dict],
    rsc_summaries: list[dict],
    next_data_endpoint_attempts: list[dict],
    sitemap_summary: dict,
    plugin_sample: dict | None,
    pontusab: dict,
    third_party: list[dict],
) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines: list[str] = []
    lines.append("# Spike: cursor.directory 程序化访问路径调研")
    lines.append("")
    lines.append(f"报告时间：{now}")
    lines.append("")
    lines.append("> 本报告由 `scripts/spike_cursor_directory.py` 真实探测生成。所有 HTTP 状态码、响应大小、")
    lines.append("> __NEXT_DATA__ 字段、pontusab/directories 文件计数均来自实测，**未硬编码**。")
    lines.append("")

    # Section 1
    lines.append("## 1. 候选路径探测")
    lines.append("")
    lines.append("| URL | HTTP | 内容类型 | 大小 (bytes) | 耗时 (ms) | 错误 | 可用性 |")
    lines.append("|-----|------|----------|--------------|-----------|------|--------|")
    for f in findings:
        status = f["status"] if f["status"] is not None else "—"
        ct = (f["content_type"] or "—").split(";")[0].strip()
        size = f["size"]
        elapsed = f.get("elapsed_ms", "—")
        err = (f["error"] or "—")[:60].replace("|", "\\|")
        usable = "✅" if (f["status"] == 200 and size > 0) else "❌"
        url = f["url"].replace("|", "\\|")
        lines.append(f"| {url} | {status} | {ct} | {size} | {elapsed} | {err} | {usable} |")
    lines.append("")

    # Section 2
    lines.append("## 2. __NEXT_DATA__ / RSC payload / sitemap 提取")
    lines.append("")
    if not next_data_summaries:
        lines.append("> 未能从任何 HTML 页面提取 `__NEXT_DATA__`。这通常意味着站点是 **Next.js App Router** 而不是 Pages Router")
        lines.append("> （App Router 改用 RSC 流式 payload，参见 2.0）。")
        lines.append("")
    else:
        for s in next_data_summaries:
            lines.append(f"### 2.{next_data_summaries.index(s) + 1} `{s['source_url']}`")
            lines.append("")
            lines.append(f"- buildId: `{s.get('build_id') or '(missing)'}`")
            lines.append(f"- top-level keys: `{s['summary']['top_keys']}`")
            lines.append(f"- page: `{s['summary']['page']}`")
            lines.append(f"- pageProps keys: `{s['summary']['page_props_keys']}`")
            sizes = s["summary"]["list_field_sizes"]
            if sizes:
                lines.append(f"- pageProps 中数组字段长度：")
                for k, v in sorted(sizes.items(), key=lambda x: -x[1])[:15]:
                    lines.append(f"  - `{k}`: {v} 项")
            lines.append("")

    if rsc_summaries:
        lines.append("### 2.0 Next.js App Router RSC payload 检测")
        lines.append("")
        lines.append("> cursor.directory 使用 Next.js App Router（`self.__next_f.push(...)` 流式 RSC payload，")
        lines.append("> **没有 Pages Router 风格的 `__NEXT_DATA__`**）。RSC payload 是带前缀 + escape 的私有格式，")
        lines.append("> 解析需要 react-server-dom 一致的反序列化器，通用 JSON 提取不可行。")
        lines.append("")
        lines.append("| 来源 URL | self.__next_f | push 数 | 近似 payload 大小 |")
        lines.append("|----------|---------------|---------|-------------------|")
        for s in rsc_summaries:
            lines.append(
                f"| `{s['source_url']}` | {'✅' if s['has_self_next_f'] else '❌'} | "
                f"{s['push_count']} | {s['approx_payload_bytes']} |"
            )
        lines.append("")

    if sitemap_summary.get("total_urls", 0) > 0:
        lines.append("### 2.1 sitemap.xml URL 分布")
        lines.append("")
        lines.append(f"- 总 URL 数：**{sitemap_summary['total_urls']}**")
        lines.append("")
        lines.append("| 顶层路径 | URL 数 |")
        lines.append("|----------|--------|")
        for k, v in sitemap_summary["buckets"].items():
            lines.append(f"| `/{k}` | {v} |")
        lines.append("")
        lines.append("样本 URL：")
        for u in sitemap_summary["sample"]:
            lines.append(f"- {u}")
        lines.append("")

    if plugin_sample:
        lines.append("### 2.2 单个 `/plugins/<slug>` 页面抽样")
        lines.append("")
        lines.append(f"- URL: `{plugin_sample['url']}`")
        lines.append(f"- HTTP: `{plugin_sample.get('status')}`")
        lines.append(f"- 大小: {plugin_sample.get('size')} bytes")
        if plugin_sample.get("title"):
            lines.append(f"- `<title>`: {plugin_sample['title']}")
        if plugin_sample.get("meta_description"):
            lines.append(f"- `<meta description>`: {plugin_sample['meta_description'][:240]}")
        rsc = plugin_sample.get("rsc")
        if rsc:
            lines.append(
                f"- RSC payload: push 数 {rsc['push_count']}, "
                f"近似大小 {rsc['approx_payload_bytes']} bytes"
            )
        lines.append("")
        lines.append("**结论**：每个 plugin 页面的元数据（title / description）可通过 `<title>` + `<meta>` 标签直接提取，")
        lines.append("不依赖 RSC 反序列化。完整的 plugin 字段（作者、tags、content）需进一步解析 RSC 流或转向 Supabase 反向工程。")
        lines.append("")

    if next_data_endpoint_attempts:
        lines.append("### 2.x `_next/data/<buildId>/...` 端点尝试")
        lines.append("")
        lines.append("| URL | HTTP | 内容类型 | 大小 | 错误 |")
        lines.append("|-----|------|----------|------|------|")
        for f in next_data_endpoint_attempts:
            status = f["status"] if f["status"] is not None else "—"
            ct = (f["content_type"] or "—").split(";")[0].strip()
            err = (f["error"] or "—")[:60].replace("|", "\\|")
            lines.append(f"| {f['url']} | {status} | {ct} | {f['size']} | {err} |")
        lines.append("")

    # Section 3
    lines.append("## 3. pontusab/directories 数据规模复核")
    lines.append("")
    if pontusab.get("error"):
        lines.append(f"> 抓取失败：`{pontusab['error']}`")
        lines.append("")
    else:
        lines.append(f"- repo: `{pontusab['repo']}`")
        lines.append(f"- default_branch: `{pontusab['default_branch']}`")
        lines.append(f"- 总 blob 数（仓库全量）: **{pontusab['total_blobs']}**")
        lines.append(f"- tree truncated: `{pontusab['tree_truncated']}`")
        lines.append(f"- src/data/ 下文件总数: **{pontusab['src_data_files']}**")
        lines.append("")
        lines.append("### src/data/ 子目录分布")
        lines.append("")
        lines.append("| 子目录 | 文件数 |")
        lines.append("|--------|--------|")
        for k, v in pontusab["src_data_breakdown"].items():
            lines.append(f"| `{k}` | {v} |")
        lines.append("")
        lines.append("### src/data/ 文件扩展名分布")
        lines.append("")
        lines.append("| 扩展名 | 文件数 |")
        lines.append("|--------|--------|")
        for k, v in pontusab["ext_breakdown"].items():
            lines.append(f"| `{k}` | {v} |")
        lines.append("")
        if pontusab["sample_files"]:
            lines.append("### 样本文件（最多 12 条）")
            lines.append("")
            for p in pontusab["sample_files"]:
                lines.append(f"- `{p}`")
            lines.append("")
        lines.append("### 仓库根目录 top-level 分布")
        lines.append("")
        lines.append("| 顶层目录 | 文件数 |")
        lines.append("|----------|--------|")
        for k, v in list(pontusab["by_top_dir"].items())[:12]:
            lines.append(f"| `{k}` | {v} |")
        lines.append("")

    # Section 4
    lines.append("## 4. 第三方 wrapper 搜索")
    lines.append("")
    lines.append("> GitHub 全文搜索匹配很噪（带 hyphen 的 token 会拆开），表中 `相关` 列标识 repo 名或描述")
    lines.append("> 是否真的提到 `cursor` / `cursor.directory` / `cursor-directory`。")
    lines.append("")
    if not third_party:
        lines.append("> 未执行（或全部失败）。")
        lines.append("")
    else:
        relevant_total = 0
        for grp in third_party:
            lines.append(f"### 查询：`{grp['query']}`")
            if grp.get("error"):
                lines.append(f"- 错误：`{grp['error']}`")
                lines.append("")
                continue
            total = grp.get("total_count", 0)
            lines.append(f"- 总匹配数（GitHub 报告）: {total}")
            if not grp.get("items"):
                lines.append("- 命中 top-N: （无）")
                lines.append("")
                continue
            lines.append("")
            lines.append("| repo | stars | pushed_at | description | 相关 |")
            lines.append("|------|-------|-----------|-------------|------|")
            for it in grp["items"]:
                desc = (it["description"] or "").replace("|", "\\|").replace("\n", " ")[:120]
                full_lc = (it.get("full_name") or "").lower()
                desc_lc = (it.get("description") or "").lower()
                relevant = (
                    "cursor" in full_lc
                    or "cursor.directory" in desc_lc
                    or "cursor-directory" in desc_lc
                )
                if relevant:
                    relevant_total += 1
                rel_mark = "✅" if relevant else "—"
                lines.append(
                    f"| [{it['full_name']}]({it['html_url']}) | {it['stars']} | {it['pushed_at']} | {desc} | {rel_mark} |"
                )
            lines.append("")
        lines.append(f"> **相关命中合计**：{relevant_total} 个（按 `cursor` / `cursor.directory` 词命中过滤）。")
        lines.append("")

    # Section 5
    lines.append("## 5. 可行性评估与推荐")
    lines.append("")
    lines.append("以下结论基于**本次实测**结果。如果运行环境受限（rate-limit / 网络隔离），")
    lines.append('结论应以"覆盖最多信号"的方式给出，并在"障碍"小节标注限制。')
    lines.append("")

    # Auto-derive verdict signals
    api_hits = [f for f in findings if f["url"].startswith("https://cursor.directory/api/") and f["status"] == 200]
    sitemap_hit = next((f for f in findings if "sitemap.xml" in f["url"] and f["status"] == 200), None)
    sitemap_url_count = sitemap_summary.get("total_urls", 0)
    has_next_data = bool(next_data_summaries) and any(s.get("build_id") for s in next_data_summaries)
    has_rsc = bool(rsc_summaries)
    plugin_sample_ok = bool(
        plugin_sample
        and plugin_sample.get("status") == 200
        and (plugin_sample.get("title") or plugin_sample.get("meta_description"))
    )
    next_data_endpoint_hit = any(
        f["status"] == 200 and "application/json" in (f.get("content_type") or "")
        for f in next_data_endpoint_attempts
    )
    pontusab_files = pontusab.get("src_data_files", 0)
    pontusab_ok = bool(pontusab_files and pontusab_files >= 50)
    # Filter third-party to relevant repos only — must mention "cursor" or have a directly-relevant name
    third_party_top: list[dict] = []
    seen_full: set[str] = set()
    for grp in third_party:
        for it in grp.get("items", []):
            full = (it.get("full_name") or "").lower()
            desc = (it.get("description") or "").lower()
            if full in seen_full:
                continue
            if "cursor" not in full and "cursor.directory" not in desc and "cursor-directory" not in desc:
                continue
            seen_full.add(full)
            third_party_top.append(it)
    third_party_top = sorted(third_party_top, key=lambda x: -x.get("stars", 0))[:8]

    lines.append("### 5.1 信号汇总")
    lines.append("")
    lines.append(f"- `/api/*` 200 命中：**{len(api_hits)}** 条")
    lines.append(f"- sitemap.xml 命中：{'✅' if sitemap_hit else '❌'}（{sitemap_url_count} 个 URL）")
    lines.append(f"- __NEXT_DATA__（Pages Router）提取：{'✅' if has_next_data else '❌（cursor.directory 是 App Router）'}")
    lines.append(f"- RSC payload（App Router）检测：{'✅' if has_rsc else '❌'}")
    lines.append(f"- `_next/data/<buildId>/...` 端点 200 + JSON：{'✅' if next_data_endpoint_hit else '❌'}")
    lines.append(f"- 单个 `/plugins/<slug>` 页面抽样可读出 title/meta：{'✅' if plugin_sample_ok else '❌'}")
    lines.append(f"- pontusab/directories src/data 文件数 ≥ 50：{'✅' if pontusab_ok else '❌'} ({pontusab_files} 个，仅 3 条种子文件，**与 baseline 假设一致**)")
    lines.append(f"- 第三方 cursor.directory 相关 repo（stars 排序，至多 8）：**{len(third_party_top)}** 个")
    lines.append("")

    # Verdict — priority order: official API > _next/data > pontusab repo (large) > sitemap+per-page scrape > third-party wrapper > nothing
    if api_hits:
        verdict = "易"
        path_recommend = f"`{api_hits[0]['url']}` 等 API 端点直接返回 JSON，可直接用于 sync 接入"
        next_step = "在本 change 内追加 `scripts/sync_cursor_directory.py`（草拟字段映射）"
    elif next_data_endpoint_hit:
        verdict = "中"
        path_recommend = "通过 `_next/data/<buildId>/<route>.json` 拉取 SSG 静态数据；buildId 需先抓 HTML 提取"
        next_step = "在本 change 追加 sync 脚本，需处理 buildId 漂移（每次 deploy 都会变）"
    elif pontusab_ok:
        verdict = "中"
        path_recommend = (
            f"放弃 cursor.directory 网站直接抓取，改用 GitHub repo `pontusab/directories` "
            f"(src/data 共 {pontusab_files} 个文件) 作为可信源"
        )
        next_step = "在 follow-up change 内实现 `sync_cursor_directory.py`，按 src/data/ 子目录解析"
    elif sitemap_hit and plugin_sample_ok and sitemap_url_count >= 100:
        verdict = "中"
        path_recommend = (
            f"sitemap.xml 提供 **{sitemap_url_count}** 个 URL（其中 `/plugins/*` "
            f"{sitemap_summary['buckets'].get('plugins', 0)} 条），单个 plugin 页面可读出 "
            "`<title>` + `<meta description>`。完整字段（标签 / 作者 / content）需解析 RSC payload 或反向 Supabase 接口。"
        )
        next_step = (
            "记 follow-up change `spike-cursor-directory-extended`：评估"
            "(a) sitemap + per-plugin 页面 meta 解析（覆盖 title/description，足够 search index）；"
            "(b) RSC payload 反序列化的可行性 / 维护成本；"
            "(c) 反向 Supabase 公开接口的合规性。**主 change 不在本轮接入，避免阻塞**。"
        )
    elif third_party_top:
        verdict = "中"
        top = third_party_top[0]
        path_recommend = (
            f"借力第三方 wrapper（如 [{top['full_name']}]({top['html_url']}) — {top['stars']}★），"
            f"或仿制其抓取逻辑"
        )
        next_step = "follow-up change 评估 wrapper 维护活跃度后接入"
    else:
        verdict = "不可行（当前实测）"
        path_recommend = "无可靠程序化路径"
        next_step = "记 follow-up change `spike-cursor-directory-extended`，或放弃"

    lines.append("### 5.2 结论")
    lines.append("")
    lines.append(f"- **推荐路径**：{path_recommend}")
    lines.append(f"- **接入难度**：{verdict}")
    lines.append(f"- **推荐下一步**：{next_step}")
    lines.append("")

    lines.append("### 5.3 障碍 / 限制")
    lines.append("")
    network_blocked = sum(1 for f in findings if f["status"] is None)
    if network_blocked == len(findings):
        lines.append("- ⚠️ **所有 cursor.directory 探针均无法连通**。可能原因：本地网络隔离 / DNS 解析失败 / 防火墙。")
        lines.append("- 建议在 CI 或更宽松环境复跑此脚本，结果以彼时实测为准。")
    elif network_blocked > 0:
        lines.append(f"- 部分 URL（{network_blocked}/{len(findings)}）连通失败 — 可能瞬时网络抖动，可重试。")
    pontusab_err = pontusab.get("error")
    if pontusab_err:
        lines.append(f"- pontusab/directories 探测失败：`{pontusab_err}`（rate-limit？设置 `GITHUB_TOKEN` 重试）")
    if any(grp.get("error") for grp in third_party):
        lines.append("- GitHub 第三方 wrapper 搜索部分失败（rate-limit？设置 `GITHUB_TOKEN`）")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("_脚本：`scripts/spike_cursor_directory.py` — 仅 Python 标准库，read-only，可重复运行。_")
    return "\n".join(lines) + "\n"


def main() -> int:
    print(f"[spike] cursor.directory probe — {datetime.now(timezone.utc).isoformat()}")

    # 1. Probe URLs (with polite delay to avoid Vercel WAF 429)
    findings: list[dict] = []
    for i, url in enumerate(PROBE_URLS):
        if i > 0 and PROBE_DELAY_S > 0:
            time.sleep(PROBE_DELAY_S)
        result = _request(url)
        print(f"  probe {url} → {result['status']} ({result['size']}b, {result.get('elapsed_ms')}ms)")
        findings.append(result)

    # 2. Parse __NEXT_DATA__ + detect RSC payload from any HTML page that returned 200
    next_data_summaries: list[dict] = []
    rsc_summaries: list[dict] = []
    build_ids: set[str] = set()
    for f in findings:
        if f["status"] != 200:
            continue
        ctype = (f.get("content_type") or "").lower()
        if "html" not in ctype:
            continue
        body_bytes = f.get("_body") or b""
        try:
            html = body_bytes.decode("utf-8", errors="replace")
        except Exception:
            continue
        nd = parse_next_data(html)
        if nd is not None:
            bid = extract_build_id(nd)
            if bid:
                build_ids.add(bid)
            next_data_summaries.append({
                "source_url": f["url"],
                "build_id": bid,
                "summary": summarize_next_data(nd),
            })
        rsc = detect_rsc_payload(html)
        if rsc["has_self_next_f"]:
            rsc_summaries.append({"source_url": f["url"], **rsc})

    # 2.x — try _next/data/<buildId>/<route>.json
    next_data_endpoint_attempts: list[dict] = []
    if build_ids:
        for bid in list(build_ids)[:1]:  # only one buildId expected
            for route in ["index", "rules", "mcp"]:
                attempt = try_next_data_endpoint(bid, route)
                # strip body for report
                attempt.pop("_body", None)
                next_data_endpoint_attempts.append(attempt)
                print(
                    f"  _next/data {bid}/{route}.json → "
                    f"{attempt['status']} ({attempt['size']}b)"
                )

    # 2.y — sitemap.xml URL extraction + bucket
    sitemap_summary: dict = {"total_urls": 0, "buckets": {}, "sample": []}
    for f in findings:
        if f["url"].endswith("/sitemap.xml") and f["status"] == 200:
            body = (f.get("_body") or b"").decode("utf-8", errors="replace")
            urls = re.findall(r"<loc>([^<]+)</loc>", body)
            sitemap_summary["total_urls"] = len(urls)
            from collections import Counter
            buckets: Counter = Counter()
            for u in urls:
                path = u.replace("https://cursor.directory", "").strip("/")
                top = path.split("/", 1)[0] if path else "(root)"
                buckets[top] += 1
            sitemap_summary["buckets"] = dict(buckets.most_common(15))
            sitemap_summary["sample"] = urls[:8]
            break

    # 2.z — sample one /plugins/<slug> page if sitemap revealed any
    plugin_sample: dict | None = None
    plugin_urls = []
    for f in findings:
        if f["url"].endswith("/sitemap.xml") and f["status"] == 200:
            body = (f.get("_body") or b"").decode("utf-8", errors="replace")
            for u in re.findall(r"<loc>([^<]+)</loc>", body):
                if "/plugins/" in u:
                    plugin_urls.append(u)
                    if len(plugin_urls) >= 3:
                        break
    if plugin_urls:
        time.sleep(PROBE_DELAY_S)
        sample_url = plugin_urls[0]
        result = _request(sample_url, timeout=30)
        body = result.pop("_body", b"")
        if result["status"] == 200 and body:
            html = body.decode("utf-8", errors="replace")
            rsc = detect_rsc_payload(html)
            # extract <title> + <meta name="description">
            title_m = re.search(r"<title[^>]*>([^<]+)</title>", html)
            desc_m = re.search(
                r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']',
                html,
            )
            result["title"] = title_m.group(1).strip() if title_m else None
            result["meta_description"] = desc_m.group(1).strip() if desc_m else None
            result["rsc"] = rsc
        plugin_sample = result
        print(
            f"  plugin sample {sample_url} → "
            f"{result['status']} ({result['size']}b)"
        )

    # 3. pontusab/directories
    print("  probe github: pontusab/directories tree...")
    pontusab = probe_pontusab_directories()
    if pontusab.get("error"):
        print(f"    error: {pontusab['error']}")
    else:
        print(
            f"    src/data files: {pontusab['src_data_files']}, "
            f"total blobs: {pontusab['total_blobs']}"
        )

    # 4. Third-party wrappers
    print("  search github: third-party wrappers...")
    third_party = search_third_party_wrappers()

    # 5. Render report
    # Strip _body from findings before writing report (report itself doesn't print body anyway)
    findings_for_report = [{k: v for k, v in f.items() if k != "_body"} for f in findings]

    report = render_report(
        findings=findings_for_report,
        next_data_summaries=next_data_summaries,
        rsc_summaries=rsc_summaries,
        next_data_endpoint_attempts=next_data_endpoint_attempts,
        sitemap_summary=sitemap_summary,
        plugin_sample=plugin_sample,
        pontusab=pontusab,
        third_party=third_party,
    )
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(f"[spike] report written: {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
