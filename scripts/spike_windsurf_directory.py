#!/usr/bin/env python3
"""Spike: probe windsurf.com/editor/directory programmatic access paths.

Probes:
  1. windsurf.com/editor/directory candidate paths + /api/* + sitemap + robots
  2. Parse __NEXT_DATA__ (Pages Router) and detect RSC payload (App Router)
  3. Try `_next/data/<buildId>/...` if buildId is found
  4. GitHub search for third-party wrappers (windsurf-directory / windsurf-rules-scraper)

Output: docs/spike_windsurf_directory.md (markdown report).

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
REPORT_PATH = ROOT / "docs" / "spike_windsurf_directory.md"

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
)
# Polite delay between windsurf.com probes to avoid WAF / rate-limit.
PROBE_DELAY_S = float(os.environ.get("SPIKE_PROBE_DELAY", "1.5"))

PROBE_URLS = [
    # Directory landing pages
    "https://windsurf.com/editor/directory",
    "https://windsurf.com/editor/directory/rules",
    "https://windsurf.com/editor/directory/mcp",
    # API-style paths (most likely 404 — we're probing)
    "https://windsurf.com/api/rules",
    "https://windsurf.com/api/mcp",
    "https://windsurf.com/api/directory",
    "https://windsurf.com/api/v1/rules",
    "https://windsurf.com/api/list",
    # Sitemap & robots
    "https://windsurf.com/sitemap.xml",
    "https://windsurf.com/sitemap_index.xml",
    "https://windsurf.com/robots.txt",
    # Homepage as fallback build_id source
    "https://windsurf.com/",
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
    """Detect Next.js App Router RSC streaming payload (`self.__next_f.push(...)`)."""
    pushes = re.findall(r"self\.__next_f\.push\(\[(\d+),\s*(\".*?\")\]\)", html, re.DOTALL)
    has_next_f = "self.__next_f" in html
    total_body = sum(len(p[1]) for p in pushes)
    return {
        "has_self_next_f": has_next_f,
        "push_count": len(pushes),
        "approx_payload_bytes": total_body,
    }


def detect_framework_hints(html: str) -> dict:
    """Best-effort hints about the framework (Next.js / Nuxt / Astro / static)."""
    hints = {
        "next_js": "/_next/" in html or "__NEXT_DATA__" in html or "self.__next_f" in html,
        "nuxt": "__NUXT__" in html or "/_nuxt/" in html,
        "astro": "astro-island" in html or "data-astro" in html,
        "gatsby": "/page-data/" in html or "___gatsby" in html,
        "webflow": "webflow" in html.lower(),
        "wordpress": "/wp-content/" in html or "/wp-json/" in html,
    }
    return hints


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


def search_third_party_wrappers() -> list[dict]:
    """Search GitHub for windsurf-directory wrappers / scrapers."""
    queries = [
        "windsurf-directory in:name",
        "windsurf-rules-scraper in:name",
        "windsurf-rules in:name",
        "windsurf.com in:readme api",
        '"windsurf.com/editor/directory" in:readme',
        "windsurf mcp directory in:name",
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
    """Try `https://windsurf.com/_next/data/<buildId>/<route>.json`."""
    if route in ("", "/"):
        url = f"https://windsurf.com/_next/data/{build_id}/index.json"
    else:
        clean = route.strip("/")
        url = f"https://windsurf.com/_next/data/{build_id}/{clean}.json"
    return _request(url, timeout=timeout)


def render_report(
    *,
    findings: list[dict],
    next_data_summaries: list[dict],
    rsc_summaries: list[dict],
    framework_hints: list[dict],
    next_data_endpoint_attempts: list[dict],
    sitemap_summary: dict,
    directory_sample: dict | None,
    third_party: list[dict],
) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines: list[str] = []
    lines.append("# Spike: windsurf.com/editor/directory 程序化访问路径调研")
    lines.append("")
    lines.append(f"报告时间：{now}")
    lines.append("")
    lines.append("> 本报告由 `scripts/spike_windsurf_directory.py` 真实探测生成。所有 HTTP 状态码、响应大小、")
    lines.append("> __NEXT_DATA__ 字段等均来自实测，**未硬编码**。")
    lines.append("")
    lines.append("> 注：本 spike 与 §3（awesome-windsurfrules）独立。awesome-windsurfrules 已在主 change 内接入，")
    lines.append("> 因此即便 windsurf.com 官网无可行路径，rules 数据已有覆盖。")
    lines.append("")

    # Section 1 — candidate URLs
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

    # Section 2 — __NEXT_DATA__ / RSC / framework hints
    lines.append("## 2. __NEXT_DATA__ / RSC payload / 框架特征提取")
    lines.append("")
    if framework_hints:
        lines.append("### 2.0 框架特征（基于 HTML 关键词）")
        lines.append("")
        lines.append("| 来源 URL | Next.js | Nuxt | Astro | Gatsby | Webflow | WordPress |")
        lines.append("|----------|---------|------|-------|--------|---------|-----------|")
        for h in framework_hints:
            lines.append(
                f"| `{h['source_url']}` | "
                f"{'✅' if h['next_js'] else '—'} | "
                f"{'✅' if h['nuxt'] else '—'} | "
                f"{'✅' if h['astro'] else '—'} | "
                f"{'✅' if h['gatsby'] else '—'} | "
                f"{'✅' if h['webflow'] else '—'} | "
                f"{'✅' if h['wordpress'] else '—'} |"
            )
        lines.append("")

    if not next_data_summaries:
        lines.append("### 2.1 __NEXT_DATA__ 提取")
        lines.append("")
        lines.append("> 未能从任何 HTML 页面提取 `__NEXT_DATA__`。可能原因：(a) 不是 Next.js Pages Router；")
        lines.append("> (b) 是 Next.js App Router（看 RSC 检测）；(c) 完全是其他框架 / 静态站点。")
        lines.append("")
    else:
        for idx, s in enumerate(next_data_summaries, start=1):
            lines.append(f"### 2.1.{idx} `{s['source_url']}` 的 __NEXT_DATA__")
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
        lines.append("### 2.2 Next.js App Router RSC payload 检测")
        lines.append("")
        lines.append("> 若检出 `self.__next_f.push(...)` 流式 payload，说明 windsurf.com 使用 App Router。")
        lines.append("> RSC payload 是带前缀 + escape 的私有格式，解析需要 react-server-dom 一致的反序列化器，")
        lines.append("> 通用 JSON 提取不可行。")
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
        lines.append("### 2.3 sitemap.xml URL 分布")
        lines.append("")
        lines.append(f"- 总 URL 数：**{sitemap_summary['total_urls']}**")
        lines.append("")
        lines.append("| 顶层路径 | URL 数 |")
        lines.append("|----------|--------|")
        for k, v in sitemap_summary["buckets"].items():
            lines.append(f"| `/{k}` | {v} |")
        lines.append("")
        if sitemap_summary.get("directory_urls_count", 0) > 0:
            lines.append(
                f"> sitemap 中包含 `editor/directory/...` 路径 **{sitemap_summary['directory_urls_count']}** 条，"
                f"可作为 slug 列表的来源。"
            )
            lines.append("")
        lines.append("样本 URL：")
        for u in sitemap_summary["sample"]:
            lines.append(f"- {u}")
        lines.append("")

    if directory_sample:
        lines.append("### 2.4 单个 `/editor/directory/...` 页面抽样")
        lines.append("")
        lines.append(f"- URL: `{directory_sample['url']}`")
        lines.append(f"- HTTP: `{directory_sample.get('status')}`")
        lines.append(f"- 大小: {directory_sample.get('size')} bytes")
        if directory_sample.get("title"):
            lines.append(f"- `<title>`: {directory_sample['title']}")
        if directory_sample.get("meta_description"):
            lines.append(f"- `<meta description>`: {directory_sample['meta_description'][:240]}")
        rsc = directory_sample.get("rsc")
        if rsc:
            lines.append(
                f"- RSC payload: push 数 {rsc['push_count']}, "
                f"近似大小 {rsc['approx_payload_bytes']} bytes"
            )
        lines.append("")

    if next_data_endpoint_attempts:
        lines.append("### 2.5 `_next/data/<buildId>/...` 端点尝试")
        lines.append("")
        lines.append("| URL | HTTP | 内容类型 | 大小 | 错误 |")
        lines.append("|-----|------|----------|------|------|")
        for f in next_data_endpoint_attempts:
            status = f["status"] if f["status"] is not None else "—"
            ct = (f["content_type"] or "—").split(";")[0].strip()
            err = (f["error"] or "—")[:60].replace("|", "\\|")
            lines.append(f"| {f['url']} | {status} | {ct} | {f['size']} | {err} |")
        lines.append("")

    # Section 3 — third-party wrappers
    lines.append("## 3. 第三方 wrapper 搜索")
    lines.append("")
    lines.append("> GitHub 全文搜索匹配很噪。`相关` 列标识 repo 名或描述是否真的提到")
    lines.append("> `windsurf` / `windsurf.com` / `windsurf-directory` 且与 IDE 上下文相关（非冲浪运动）。")
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
                # "windsurf" alone is too noisy (surfing). Require IDE-context co-mention.
                ide_ctx_words = (
                    "ide", "editor", "ai", "rules", "mcp", "cascade", "codeium",
                    "directory", "scraper", "wrapper", "api"
                )
                relevant = (
                    "windsurf" in full_lc
                    and any(w in (full_lc + " " + desc_lc) for w in ide_ctx_words)
                )
                if relevant:
                    relevant_total += 1
                rel_mark = "✅" if relevant else "—"
                lines.append(
                    f"| [{it['full_name']}]({it['html_url']}) | {it['stars']} | {it['pushed_at']} | {desc} | {rel_mark} |"
                )
            lines.append("")
        lines.append(f"> **相关命中合计**：{relevant_total} 个（按 IDE 上下文过滤）。")
        lines.append("")

    # Section 4 — feasibility
    lines.append("## 4. 可行性评估")
    lines.append("")
    lines.append("以下结论基于**本次实测**结果。如果运行环境受限（rate-limit / 网络隔离），")
    lines.append('结论应以"覆盖最多信号"的方式给出，并在"障碍"小节标注限制。')
    lines.append("")

    # Auto-derive verdict signals
    # Note: windsurf.com is a SPA — any unmatched route (e.g. /api/mcp, /api/list)
    # returns the SPA shell HTML (~65KB, content_type text/html). To distinguish
    # a *real* JSON API from the catch-all, we require content_type to contain "json".
    api_hits = [
        f for f in findings
        if f["url"].startswith("https://windsurf.com/api/")
        and f["status"] == 200
        and "json" in (f.get("content_type") or "").lower()
    ]
    # Also count which `/api/*` URLs returned the SPA shell (HTML) — useful as a
    # signal that the path is a "soft 404" rather than a real API.
    api_spa_shells = [
        f for f in findings
        if f["url"].startswith("https://windsurf.com/api/")
        and f["status"] == 200
        and "html" in (f.get("content_type") or "").lower()
    ]
    sitemap_hit = next((f for f in findings if "sitemap.xml" in f["url"] and f["status"] == 200), None)
    sitemap_url_count = sitemap_summary.get("total_urls", 0)
    sitemap_directory_count = sitemap_summary.get("directory_urls_count", 0)
    has_next_data = bool(next_data_summaries) and any(s.get("build_id") for s in next_data_summaries)
    has_rsc = bool(rsc_summaries)
    directory_landing_ok = any(
        f["url"].startswith("https://windsurf.com/editor/directory") and f["status"] == 200
        for f in findings
    )
    directory_sample_ok = bool(
        directory_sample
        and directory_sample.get("status") == 200
        and (directory_sample.get("title") or directory_sample.get("meta_description"))
    )
    next_data_endpoint_hit = any(
        f["status"] == 200 and "application/json" in (f.get("content_type") or "")
        for f in next_data_endpoint_attempts
    )
    # Filter third-party — strict: must be a *directory scraper / wrapper*, not
    # an LLM proxy or a personal rules collection. Require windsurf AND one of
    # {directory, scraper, wrapper}; explicitly exclude proxy / account / tool.
    third_party_top: list[dict] = []
    seen_full: set[str] = set()
    DIRECTORY_WRAPPER_WORDS = ("directory", "scraper", "wrapper")
    EXCLUDE_WORDS = ("proxy", "account", "switcher", "tool", "manager", "openai compatible")
    for grp in third_party:
        for it in grp.get("items", []):
            full = (it.get("full_name") or "").lower()
            desc = (it.get("description") or "").lower()
            blob = full + " " + desc
            if full in seen_full:
                continue
            if "windsurf" not in full:
                continue
            if not any(w in blob for w in DIRECTORY_WRAPPER_WORDS):
                continue
            if any(w in blob for w in EXCLUDE_WORDS):
                continue
            seen_full.add(full)
            third_party_top.append(it)
    third_party_top = sorted(third_party_top, key=lambda x: -x.get("stars", 0))[:8]

    lines.append("### 4.1 信号汇总")
    lines.append("")
    lines.append(f"- `/editor/directory*` landing 页 200：{'✅' if directory_landing_ok else '❌'}（注意：SPA shell，无静态数据）")
    lines.append(f"- `/api/*` 真 JSON API 命中（content_type=json）：**{len(api_hits)}** 条")
    lines.append(f"- `/api/*` 返回 SPA shell HTML（catch-all 软 404）：**{len(api_spa_shells)}** 条 — 说明 windsurf.com 没有公开 REST API")
    lines.append(f"- sitemap.xml 命中：{'✅' if sitemap_hit else '❌'}（{sitemap_url_count} 个 URL，其中 directory 路径 {sitemap_directory_count} 条）")
    lines.append(f"- __NEXT_DATA__（Pages Router）提取：{'✅' if has_next_data else '❌'}")
    lines.append(f"- RSC payload（App Router）检测：{'✅' if has_rsc else '❌'}")
    lines.append(f"- `_next/data/<buildId>/...` 端点 200 + JSON：{'✅' if next_data_endpoint_hit else '❌'}")
    lines.append(f"- 单个 `/editor/directory/<slug>` 页面抽样可读出 title/meta：{'✅' if directory_sample_ok else '❌'}")
    lines.append(f"- 第三方 directory/scraper/wrapper 仓库（严格名称过滤）：**{len(third_party_top)}** 个")
    lines.append("")

    # Verdict — priority order: official API > _next/data > sitemap+per-page > third-party > nothing
    if api_hits:
        verdict = "易"
        path_recommend = f"`{api_hits[0]['url']}` 等 API 端点直接返回 JSON，可直接用于 sync 接入"
        next_step = "在本 change 内追加 `scripts/sync_windsurf_directory.py`（草拟字段映射）"
    elif next_data_endpoint_hit:
        verdict = "中"
        path_recommend = "通过 `_next/data/<buildId>/<route>.json` 拉取 SSG 静态数据；buildId 需先抓 HTML 提取"
        next_step = "本 change 内追加 sync 脚本，但需处理 buildId 漂移（每次 deploy 都会变）"
    elif sitemap_hit and directory_sample_ok and sitemap_directory_count >= 50:
        verdict = "中"
        path_recommend = (
            f"sitemap.xml 暴露 **{sitemap_directory_count}** 条 `/editor/directory/...` URL，"
            "单个页面可读出 `<title>` + `<meta description>`。完整字段需解析 RSC payload。"
        )
        next_step = (
            "follow-up change `spike-windsurf-directory-extended` 评估 RSC 反序列化；"
            "本 change 不在本轮接入，避免阻塞主流程（rules 已由 §3 awesome-windsurfrules 覆盖）。"
        )
    elif third_party_top:
        verdict = "中"
        top = third_party_top[0]
        path_recommend = (
            f"借力第三方 wrapper（如 [{top['full_name']}]({top['html_url']}) — {top['stars']}★），"
            f"或仿制其抓取逻辑"
        )
        next_step = "follow-up change 评估 wrapper 维护活跃度后再决定是否接入"
    else:
        verdict = "不可行（当前实测）"
        if sitemap_directory_count > 0:
            sitemap_clause = (
                f"sitemap 仅 {sitemap_directory_count} 条 `editor/directory` 路径（不足以构造批量抓取）"
            )
        else:
            sitemap_clause = "sitemap 无 `editor/directory` 路径"
        path_recommend = (
            f"windsurf.com 官网无可靠程序化路径（无 API、无 __NEXT_DATA__、"
            f"无 _next/data、{sitemap_clause}、无第三方 wrapper）"
        )
        next_step = (
            "**推荐放弃 windsurf.com 官网，仅依赖 awesome-windsurfrules（已通过 §3 接入）**。"
            "MCP 维度由 §1 sync_mcp_registry（mcpservers.org）+ 现有 mcp.so 覆盖。"
            "无需创建 follow-up spike change（awesome-windsurfrules 已经是 rules 维度的有效覆盖）。"
        )

    lines.append("### 4.2 结论")
    lines.append("")
    lines.append(f"- **推荐路径**：{path_recommend}")
    lines.append(f"- **接入难度**：{verdict}")
    lines.append(f"- **推荐下一步**：{next_step}")
    lines.append("")

    # Section 5 — recommended next step (explicit)
    lines.append("## 5. 推荐下一步（明确指令）")
    lines.append("")
    if verdict == "易":
        lines.append("- ✅ **可行 / 易**：在本 change（`add-tier1-rules-mcp-sources`）内追加 sync 脚本。")
        lines.append("- 建议字段映射草稿：`id` ← slug，`name` ← title，`description` ← meta description / RSC `description`，")
        lines.append("  `tags` ← API 提供的 tags，`source_url` ← 完整 URL，`platform` ← `windsurf`。")
        lines.append("- 工作量估算：2-3 小时（与 sync_cursor 同量级）。")
    elif verdict == "中":
        lines.append("- ⚠️ **可行但有成本**：建议放在 follow-up change，**本 change 不阻塞**。")
        lines.append("- 主 change 的 rules 维度已由 §3 awesome-windsurfrules 覆盖，windsurf.com 官网接入是锦上添花。")
    else:
        lines.append("- ❌ **不可行（当前实测）**：**推荐放弃 windsurf.com 官网，依赖 awesome-windsurfrules（已通过 §3 接入）**。")
        lines.append("- 不创建 follow-up spike change（rules 维度已被 §3 awesome-windsurfrules 覆盖，不存在缺口）。")
        lines.append("- MCP 维度由 §1 sync_mcp_registry（mcpservers.org）+ 现有 mcp.so 覆盖。")
        lines.append("- 若将来 windsurf 官方上线 API，再开新 change 重启接入。")
    lines.append("")

    # Section 6 — 障碍
    lines.append("### 6. 障碍 / 限制")
    lines.append("")
    network_blocked = sum(1 for f in findings if f["status"] is None)
    if network_blocked == len(findings):
        lines.append("- ⚠️ **所有 windsurf.com 探针均无法连通**。可能原因：本地网络隔离 / DNS 解析失败 / 防火墙。")
        lines.append("- 建议在 CI 或更宽松环境复跑此脚本，结果以彼时实测为准。")
    elif network_blocked > 0:
        lines.append(f"- 部分 URL（{network_blocked}/{len(findings)}）连通失败 — 可能瞬时网络抖动 / WAF，可重试。")
    if any(grp.get("error") for grp in third_party):
        lines.append("- GitHub 第三方 wrapper 搜索部分失败（rate-limit？设置 `GITHUB_TOKEN` 重试）")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("_脚本：`scripts/spike_windsurf_directory.py` — 仅 Python 标准库，read-only，可重复运行。_")
    return "\n".join(lines) + "\n"


def main() -> int:
    print(f"[spike] windsurf.com/editor/directory probe — {datetime.now(timezone.utc).isoformat()}")

    # 1. Probe URLs (with polite delay to avoid WAF 429)
    findings: list[dict] = []
    for i, url in enumerate(PROBE_URLS):
        if i > 0 and PROBE_DELAY_S > 0:
            time.sleep(PROBE_DELAY_S)
        result = _request(url)
        print(f"  probe {url} → {result['status']} ({result['size']}b, {result.get('elapsed_ms')}ms)")
        findings.append(result)

    # 2. Parse __NEXT_DATA__ + detect RSC payload + framework hints from any HTML 200
    next_data_summaries: list[dict] = []
    rsc_summaries: list[dict] = []
    framework_hints: list[dict] = []
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
        hints = detect_framework_hints(html)
        framework_hints.append({"source_url": f["url"], **hints})

    # 2.x — try _next/data/<buildId>/<route>.json
    next_data_endpoint_attempts: list[dict] = []
    if build_ids:
        for bid in list(build_ids)[:1]:
            for route in ["index", "editor/directory", "editor/directory/rules", "editor/directory/mcp"]:
                if PROBE_DELAY_S > 0:
                    time.sleep(PROBE_DELAY_S)
                attempt = try_next_data_endpoint(bid, route)
                attempt.pop("_body", None)
                next_data_endpoint_attempts.append(attempt)
                print(
                    f"  _next/data {bid}/{route}.json → "
                    f"{attempt['status']} ({attempt['size']}b)"
                )

    # 2.y — sitemap.xml URL extraction + bucket
    sitemap_summary: dict = {"total_urls": 0, "buckets": {}, "sample": [], "directory_urls_count": 0}
    directory_urls: list[str] = []
    for f in findings:
        if "sitemap" in f["url"] and f["url"].endswith(".xml") and f["status"] == 200:
            body = (f.get("_body") or b"").decode("utf-8", errors="replace")
            urls = re.findall(r"<loc>([^<]+)</loc>", body)
            sitemap_summary["total_urls"] = len(urls)
            from collections import Counter
            buckets: Counter = Counter()
            for u in urls:
                path = u.replace("https://windsurf.com", "").strip("/")
                top = path.split("/", 1)[0] if path else "(root)"
                buckets[top] += 1
                if "/editor/directory" in u:
                    directory_urls.append(u)
            sitemap_summary["buckets"] = dict(buckets.most_common(15))
            sitemap_summary["sample"] = urls[:8]
            sitemap_summary["directory_urls_count"] = len(directory_urls)
            break

    # 2.z — sample one /editor/directory/<slug> page if any
    directory_sample: dict | None = None
    sample_candidates: list[str] = []
    # Prefer slug pages from sitemap; fall back to direct landing
    for u in directory_urls:
        # skip the bare landing pages we already probed
        if u.rstrip("/") in (
            "https://windsurf.com/editor/directory",
            "https://windsurf.com/editor/directory/rules",
            "https://windsurf.com/editor/directory/mcp",
        ):
            continue
        sample_candidates.append(u)
        if len(sample_candidates) >= 1:
            break

    if sample_candidates:
        time.sleep(PROBE_DELAY_S)
        sample_url = sample_candidates[0]
        result = _request(sample_url, timeout=30)
        body = result.pop("_body", b"")
        if result["status"] == 200 and body:
            html = body.decode("utf-8", errors="replace")
            rsc = detect_rsc_payload(html)
            title_m = re.search(r"<title[^>]*>([^<]+)</title>", html)
            desc_m = re.search(
                r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']',
                html,
            )
            result["title"] = title_m.group(1).strip() if title_m else None
            result["meta_description"] = desc_m.group(1).strip() if desc_m else None
            result["rsc"] = rsc
        directory_sample = result
        print(
            f"  directory sample {sample_url} → "
            f"{result['status']} ({result['size']}b)"
        )

    # 3. Third-party wrappers
    print("  search github: third-party wrappers...")
    third_party = search_third_party_wrappers()

    # 4. Render report
    findings_for_report = [{k: v for k, v in f.items() if k != "_body"} for f in findings]

    report = render_report(
        findings=findings_for_report,
        next_data_summaries=next_data_summaries,
        rsc_summaries=rsc_summaries,
        framework_hints=framework_hints,
        next_data_endpoint_attempts=next_data_endpoint_attempts,
        sitemap_summary=sitemap_summary,
        directory_sample=directory_sample,
        third_party=third_party,
    )
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(f"[spike] report written: {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
