#!/usr/bin/env python3
"""skills.sh / mastra-ai 数据源接入脚本。

用途：
- 主路径：拉取 mastra-ai/skills-api 的 scraped-skills.json 静态快照（零 rate limit、信号纯净）
- 阈值过滤：默认 install_count >= 1000（环境变量 SKILLS_SH_MIN_INSTALLS 可覆盖）
- 输出：catalog/skills/skills_sh_index.json（中间索引），不做与其他源去重
- 增量 diff：与上次输出对比，记录新增 / install_count 显著变化（默认 ±20%）/ 移除条目

注意：
- 本脚本仅做数据抓取与转换，不调用 LLM；评估在后续 merge_index 阶段
- mastra JSON 没有 path 字段，无法精确推断 skill 在 GitHub 上的子路径，
  因此 source_url 退化为 repo 根 URL，由 skills_sh_url 提供权威落点
- design.md 假设的 https://skills.sh/api/skills/all-time?page=N 端点实际不存在（404），
  降级路径仅在本地 mastra 缓存仍可用时打 stale 警告输出旧数据
"""

import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timezone

# 路径常量
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
CACHE_DIR = os.path.join(REPO_ROOT, ".skills_sh_cache")
MASTRA_CACHE_PATH = os.path.join(CACHE_DIR, "mastra.json")
ETAG_PATH = os.path.join(CACHE_DIR, "etag.txt")
DIFF_PATH = os.path.join(CACHE_DIR, "diff.json")
OUTPUT_PATH = os.path.join(REPO_ROOT, "catalog", "skills", "skills_sh_index.json")

# 数据源 URL
MASTRA_URL = (
    "https://raw.githubusercontent.com/mastra-ai/skills-api/main/"
    "src/registry/scraped-skills.json"
)
SKILLS_SH_PAGE_URL = "https://skills.sh/api/skills/all-time?page={page}"

# 配置（可由环境变量覆盖）
DEFAULT_MIN_INSTALLS = int(os.environ.get("SKILLS_SH_MIN_INSTALLS", "1000"))
DEFAULT_FALLBACK_DAYS = int(os.environ.get("SKILLS_SH_FALLBACK_DAYS", "7"))
INSTALL_CHANGE_THRESHOLD = 0.20  # 安装数变化超过 ±20% 视为显著

TODAY = date.today().isoformat()


# ---------------------------------------------------------------------------
# 网络与缓存
# ---------------------------------------------------------------------------

def _ensure_cache_dir() -> None:
    """确保 .skills_sh_cache 目录存在。"""
    os.makedirs(CACHE_DIR, exist_ok=True)


def _read_etag() -> str:
    """读取上次保存的 ETag；不存在返回空串。"""
    if not os.path.exists(ETAG_PATH):
        return ""
    try:
        with open(ETAG_PATH, "r", encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def _write_etag(etag: str) -> None:
    """写入 ETag 到本地缓存。"""
    if not etag:
        return
    with open(ETAG_PATH, "w", encoding="utf-8") as f:
        f.write(etag)


def fetch_mastra_snapshot(timeout: int = 30) -> dict:
    """拉取 mastra scraped-skills.json，支持 ETag 命中复用本地缓存。

    返回结构: {scrapedAt, totalSkills, totalSources, totalOwners, skills: [...]}
    """
    _ensure_cache_dir()
    last_etag = _read_etag()

    req = urllib.request.Request(MASTRA_URL, method="GET")
    if last_etag:
        req.add_header("If-None-Match", last_etag)
    # raw.githubusercontent.com 上传输 token 不影响公共仓
    gh_token = os.environ.get("GITHUB_TOKEN", "").strip()
    if gh_token:
        req.add_header("Authorization", f"token {gh_token}")

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            etag = resp.headers.get("ETag", "")
            body = resp.read()
            data = json.loads(body.decode("utf-8"))
            # 落盘缓存（覆盖式写入）
            with open(MASTRA_CACHE_PATH, "wb") as f:
                f.write(body)
            _write_etag(etag)
            print(
                f"INFO: fetched mastra snapshot 200 OK "
                f"({len(body) / 1024 / 1024:.2f} MB, etag={etag[:16]}...)"
            )
            return data
    except urllib.error.HTTPError as e:
        if e.code == 304:
            # ETag 命中，复用本地缓存
            print("INFO: mastra snapshot 304 Not Modified, using local cache")
            return _load_local_cache_or_die()
        print(f"WARNING: mastra fetch HTTP {e.code} {e.reason}")
    except urllib.error.URLError as e:
        print(f"WARNING: mastra fetch URL error: {e.reason}")
    except (json.JSONDecodeError, OSError) as e:
        print(f"WARNING: mastra fetch parse error: {e}")

    # 网络失败时尝试用本地缓存兜底
    print("INFO: falling back to local mastra cache (if any)")
    return _load_local_cache_or_die()


def _load_local_cache_or_die() -> dict:
    """从本地缓存读 mastra JSON；不存在则报错退出。"""
    if not os.path.exists(MASTRA_CACHE_PATH):
        print("ERROR: no local mastra cache and remote unreachable")
        sys.exit(2)
    try:
        with open(MASTRA_CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"ERROR: local cache corrupted: {e}")
        sys.exit(2)


def fetch_skills_sh_paginated(timeout: int = 30) -> list:
    """降级路径：通过 skills.sh 分页 API 抓取全量数据。

    NOTE: 探针验证 https://skills.sh/api/skills/all-time?page=1 实际返回 404，
    该端点不存在。此函数保留接口签名供未来 skills.sh 真正提供分页 API 时启用，
    当前实现尝试一次后立即报告失败并返回空列表，由调用方决定是否走本地缓存。
    """
    page = 1
    out: list = []
    while True:
        url = SKILLS_SH_PAGE_URL.format(page=page)
        req = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8")
                data = json.loads(body)
        except urllib.error.HTTPError as e:
            print(
                f"WARNING: skills.sh paginated API page={page} returned HTTP {e.code}; "
                f"endpoint not available, abort fallback"
            )
            return out
        except (urllib.error.URLError, json.JSONDecodeError) as e:
            print(f"WARNING: skills.sh paginated API page={page} failed: {e}")
            return out

        skills = data.get("skills") or []
        out.extend(skills)
        if not data.get("hasMore"):
            break
        page += 1
        if page > 1000:  # 防御性上限
            print("WARNING: skills.sh paginated API exceeded 1000 pages, abort")
            break
    return out


def should_use_fallback(snapshot: dict, max_days: int = DEFAULT_FALLBACK_DAYS) -> bool:
    """判断 mastra 快照是否过期（scrapedAt 距今超过 max_days）。"""
    scraped_at = snapshot.get("scrapedAt", "")
    if not scraped_at:
        return True
    try:
        # ISO-8601 with Z
        ts = datetime.fromisoformat(scraped_at.replace("Z", "+00:00"))
    except ValueError:
        return True
    now = datetime.now(timezone.utc)
    delta = now - ts
    return delta.days > max_days


# ---------------------------------------------------------------------------
# 转换
# ---------------------------------------------------------------------------

_ID_INVALID_RE = re.compile(r"[^a-z0-9-]+")


def _sanitize_id_segment(s: str) -> str:
    """将 owner / skillId 等转为 kebab-case 安全片段。"""
    s = (s or "").lower().strip()
    s = re.sub(r"[\s_]+", "-", s)
    s = _ID_INVALID_RE.sub("-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s


def _make_id(skill_id: str, owner: str, repo: str = "") -> str:
    """生成 catalog 内稳定唯一 id：<skillId>-<owner>[-<repo>]。

    同一 owner 可能在多个 repo 下注册同名 skillId（如 anthropics 在 skills /
    claude-code / claude-plugins-official 三个 repo 都有 frontend-design），
    因此 owner 段不够唯一，必须把 repo 段也参与构造。当 repo 与 skillId
    本身重复（如 owner=foo / repo=skills / skillId=skills），保持 owner
    单段以避免 id 冗余。
    """
    sk = _sanitize_id_segment(skill_id)
    ow = _sanitize_id_segment(owner)
    rp = _sanitize_id_segment(repo)
    if not sk:
        sk = "skill"
    if not ow:
        ow = "unknown"
    parts = [sk, ow]
    if rp and rp != sk:
        parts.append(rp)
    return "-".join(parts)


def normalize_entry(raw: dict) -> dict:
    """将 mastra/skills.sh entry 转换为 catalog skill schema。"""
    skill_id = raw.get("skillId") or raw.get("name") or ""
    owner = raw.get("owner") or ""
    repo = raw.get("repo") or ""
    github_url = (raw.get("githubUrl") or "").rstrip("/")
    display_name = raw.get("displayName") or skill_id
    installs = int(raw.get("installs") or 0)

    # source_url 策略：mastra 没有 path 字段，无法精确推断 skill 在 GitHub
    # 上的子路径。直接用 repo 根 URL 会让同一 repo 下的所有 skill 共享同一
    # source_url，被 merge_index 当成重复条目而误合并（同一 repo 通常有几十
    # 个独立 skill）。这里给 repo 根 URL 追加一个 anchor fragment
    # `#skill={skillId}`，让每条 entry 的 source_url 字符串唯一：
    #   - 浏览器忽略 fragment，访问 URL 仍落在 repo 根，不影响人工核查
    #   - URL 字符串去重视为不同 URL，避免 merge_index 误合并
    #   - 不会与其他源（mcp/rules/prompts 等）的 URL 形态冲突
    # mastra JSON 与 skills.sh sitemap 都只暴露 owner/repo/skillId 三段
    # 信息，没法精确推断 GitHub tree 子路径，anchor 是务实选择。
    if github_url and skill_id:
        source_url = f"{github_url}#skill={skill_id}"
    else:
        source_url = github_url or ""

    # skills.sh 详情页（owner/repo/skillId 三段路径在 sitemap 中均有效）
    skills_sh_url = ""
    if owner and repo and skill_id:
        skills_sh_url = f"https://skills.sh/{owner}/{repo}/{skill_id}"

    entry: dict = {
        "id": _make_id(skill_id, owner, repo),
        "name": skill_id,
        "type": "skill",
        "description": display_name,  # mastra 不提供长描述，先用 displayName 占位
        "source_url": source_url,
        "stars": None,
        "pushed_at": None,
        "category": "tooling",  # 占位，merge_index/评估阶段会基于 README 重打 category
        "tags": [],
        "tech_stack": [],
        "install": {
            "method": "git_clone",
            "repo": f"{github_url}.git" if github_url else "",
            "files": [],
        },
        "source": "skills-sh",
        "last_synced": TODAY,
        # skills.sh 专属信号
        "install_count": installs,
        "skills_sh_url": skills_sh_url,
        # 来自 snapshot 顶层 scrapedAt，由调用方注入
        "skills_sh_scraped_at": "",
    }
    return entry


# ---------------------------------------------------------------------------
# 增量 diff
# ---------------------------------------------------------------------------

def compute_diff(prev_entries: list, new_entries: list) -> dict:
    """对比上次与本次 skills_sh_index 输出。

    输出结构：
      {
        "added": [id, ...],
        "changed_install_count": [{id, old, new, pct}, ...],
        "removed": [id, ...],
        "stable": <count>
      }
    """
    prev_map = {e.get("id"): e for e in prev_entries if e.get("id")}
    new_map = {e.get("id"): e for e in new_entries if e.get("id")}

    added = sorted(set(new_map) - set(prev_map))
    removed = sorted(set(prev_map) - set(new_map))
    common = set(prev_map) & set(new_map)

    changed = []
    stable = 0
    for sid in common:
        old_n = int(prev_map[sid].get("install_count") or 0)
        new_n = int(new_map[sid].get("install_count") or 0)
        if old_n <= 0:
            # 历史无 install_count（或为 0）— 仅当新值显著非零时才记一笔
            if new_n >= 1000:
                changed.append({
                    "id": sid, "old": old_n, "new": new_n, "pct": None,
                })
            else:
                stable += 1
            continue
        pct = (new_n - old_n) / old_n
        if abs(pct) >= INSTALL_CHANGE_THRESHOLD:
            changed.append({
                "id": sid,
                "old": old_n,
                "new": new_n,
                "pct": round(pct, 4),
            })
        else:
            stable += 1

    return {
        "added": added,
        "changed_install_count": sorted(
            changed, key=lambda x: abs(x.get("pct") or 0), reverse=True
        ),
        "removed": removed,
        "stable": stable,
    }


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main() -> int:
    min_installs = DEFAULT_MIN_INSTALLS
    print(f"INFO: SKILLS_SH_MIN_INSTALLS={min_installs}")
    print(f"INFO: SKILLS_SH_FALLBACK_DAYS={DEFAULT_FALLBACK_DAYS}")

    # 1. 拉取 mastra 主路径
    snapshot = fetch_mastra_snapshot()
    raw_skills = snapshot.get("skills") or []
    scraped_at = snapshot.get("scrapedAt", "")
    print(
        f"INFO: mastra snapshot scrapedAt={scraped_at}, "
        f"totalSkills={snapshot.get('totalSkills')}, "
        f"loaded={len(raw_skills)}"
    )

    # 2. 过期检测（不阻断流程，仅打 WARNING；当前 skills.sh 分页 API 不存在，无真正降级）
    if should_use_fallback(snapshot, DEFAULT_FALLBACK_DAYS):
        print(
            f"WARNING: mastra snapshot is older than {DEFAULT_FALLBACK_DAYS} days "
            f"(scrapedAt={scraped_at}); skills.sh paginated API endpoint is "
            f"unavailable, continuing with stale snapshot"
        )
        # 探针保留：未来端点可用时启用
        fallback = fetch_skills_sh_paginated()
        if fallback:
            print(f"INFO: fallback fetched {len(fallback)} entries from skills.sh")
            raw_skills = fallback
            # 走 fallback 路径意味着抓取的不是 mastra 旧快照，而是 skills.sh 实时数据；
            # 沿用 mastra scraped_at 会让下游误判为陈旧。改写为当前 UTC 时间戳。
            scraped_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            print(f"INFO: rewrite scraped_at to fallback fetch time: {scraped_at}")

    # 3. 阈值过滤
    filtered = [s for s in raw_skills if int(s.get("installs") or 0) >= min_installs]
    print(
        f"INFO: filtered {len(filtered)} entries with installs>={min_installs} "
        f"(from {len(raw_skills)})"
    )

    # 4. normalize（注入 scrapedAt）
    entries: list = []
    seen_ids: set = set()
    for raw in filtered:
        entry = normalize_entry(raw)
        entry["skills_sh_scraped_at"] = scraped_at
        if entry["id"] in seen_ids:
            # 防御性 id 撞车（理论上 mastra 内 owner+skillId 唯一）
            print(
                f"WARNING: duplicate id={entry['id']} "
                f"(skillId={raw.get('skillId')}, owner={raw.get('owner')}), skipping"
            )
            continue
        seen_ids.add(entry["id"])
        entries.append(entry)

    # 按 install_count 降序固定排序，保证输出 diff 友好
    entries.sort(key=lambda e: (-int(e.get("install_count") or 0), e.get("id", "")))

    # 5. 增量 diff（与上次输出对比，先 diff 再写新）
    prev = _load_prev_output()
    diff = compute_diff(prev, entries)
    print(
        f"INFO: diff vs previous: +{len(diff['added'])} added, "
        f"~{len(diff['changed_install_count'])} changed, "
        f"-{len(diff['removed'])} removed, "
        f"={diff['stable']} stable"
    )

    # 6. 写盘
    _ensure_cache_dir()
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2, ensure_ascii=False)
    print(f"INFO: wrote {len(entries)} entries to {OUTPUT_PATH}")

    with open(DIFF_PATH, "w", encoding="utf-8") as f:
        json.dump(diff, f, indent=2, ensure_ascii=False)
    print(f"INFO: wrote diff to {DIFF_PATH}")

    return 0


def _load_prev_output() -> list:
    """读取上次生成的 skills_sh_index.json，不存在返回空列表。"""
    if not os.path.exists(OUTPUT_PATH):
        return []
    try:
        with open(OUTPUT_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
            return []
    except (json.JSONDecodeError, OSError) as e:
        print(f"WARNING: previous output corrupted: {e}")
        return []


if __name__ == "__main__":
    sys.exit(main())
