#!/usr/bin/env python3
"""registry.modelcontextprotocol.io 数据源接入脚本。

用途：
- 主路径：分页拉取 /v0/servers，处理 cursor 翻页与 ETag 缓存
- 过滤：仅保留 _meta.io.modelcontextprotocol.registry/official.status == "active"
  且 isLatest == true 的条目
- 输出：catalog/mcp/mcp_registry_index.json（中间索引），不做与其他源去重
- 增量 diff：与上次输出对比，记录 added / status_changed / version_bumped / removed
  四类，stable 集合不写入文件但日志输出统计数

注意：
- 仅用 Python 标准库
- 错误兜底：网络失败 / 5xx / 缓存损坏 → ERROR 日志 + sys.exit(1)
"""

import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils import is_plugin_source, load_plugin_sources, logger  # noqa: E402

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
CACHE_DIR = os.path.join(REPO_ROOT, ".mcp_registry_cache")
REGISTRY_CACHE_PATH = os.path.join(CACHE_DIR, "registry.json")
ETAG_PATH = os.path.join(CACHE_DIR, "etag.txt")
DIFF_PATH = os.path.join(CACHE_DIR, "diff.json")
# 持久化 diff 视角的基线（所有 isLatest，含非 active）。compute_diff 在下一次运行时
# 以此为 prev，确保非 active 但 isLatest 的条目不会被反复识别为 added。
DIFF_BASELINE_PATH = os.path.join(CACHE_DIR, "diff_baseline.json")
OUTPUT_PATH = os.path.join(REPO_ROOT, "catalog", "mcp", "mcp_registry_index.json")

REGISTRY_BASE = "https://registry.modelcontextprotocol.io/v0/servers"
SOURCE_NAME = "registry.modelcontextprotocol.io"
META_KEY = "io.modelcontextprotocol.registry/official"

DEFAULT_LIMIT = 100
MAX_PAGES = 1000  # 防御性上限

TODAY = date.today().isoformat()


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------

def _log(msg: str) -> None:
    print(f"[sync_mcp_registry] {msg}", file=sys.stderr)


def _ensure_cache_dir() -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)


def _read_etag() -> str:
    if not os.path.exists(ETAG_PATH):
        return ""
    try:
        with open(ETAG_PATH, "r", encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def _write_etag(etag: str) -> None:
    if not etag:
        return
    with open(ETAG_PATH, "w", encoding="utf-8") as f:
        f.write(etag)


def _load_local_registry_cache() -> list:
    """从本地缓存读 servers 列表；不存在或损坏返回空列表。"""
    if not os.path.exists(REGISTRY_CACHE_PATH):
        return []
    try:
        with open(REGISTRY_CACHE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
            return []
    except (json.JSONDecodeError, OSError) as e:
        _log(f"ERROR: local registry cache corrupted: {e}")
        return []


def _save_local_registry_cache(servers: list) -> None:
    _ensure_cache_dir()
    with open(REGISTRY_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(servers, f, ensure_ascii=False)


# ---------------------------------------------------------------------------
# fetch_registry: 分页拉取（generator 风格但内部聚合返回 list）
# ---------------------------------------------------------------------------

def fetch_registry(limit: int = DEFAULT_LIMIT, timeout: int = 30):
    """分页拉取 v0/servers，yield 每条 raw server entry。

    - 首页带 If-None-Match（用上次 ETag）；304 时 yield 本地缓存条目
    - 200 时聚合所有页 + 落盘 + 保存新 ETag
    - 5xx / 网络失败 / 解析失败 → 抛 RuntimeError
    """
    _ensure_cache_dir()
    last_etag = _read_etag()

    cursor = ""
    page_idx = 0
    aggregated: list = []
    new_etag = ""
    used_cache = False

    while True:
        page_idx += 1
        if page_idx > MAX_PAGES:
            _log(f"ERROR: exceeded MAX_PAGES={MAX_PAGES}, abort")
            raise RuntimeError("registry pagination exceeded MAX_PAGES")

        params = {"limit": str(limit)}
        if cursor:
            params["cursor"] = cursor
        url = f"{REGISTRY_BASE}?{urllib.parse.urlencode(params)}"

        req = urllib.request.Request(url, method="GET")
        # 仅首页带 If-None-Match（cursor 翻页是有状态序列，304 仅对全量集合有意义）
        if page_idx == 1 and last_etag:
            req.add_header("If-None-Match", last_etag)
        req.add_header("User-Agent", "everything-ai-coding-mcp-registry-sync")

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                etag = ""
                try:
                    etag = resp.headers.get("ETag", "") or ""
                except AttributeError:
                    etag = ""
                body = resp.read()
                try:
                    data = json.loads(body.decode("utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError) as e:
                    _log(f"ERROR: page={page_idx} JSON parse error: {e}")
                    raise RuntimeError("registry JSON parse error") from e
        except urllib.error.HTTPError as e:
            if e.code == 304 and page_idx == 1:
                _log("INFO: registry 304 Not Modified, using local cache")
                cached = _load_local_registry_cache()
                if not cached:
                    _log("ERROR: 304 received but local cache missing/corrupted")
                    raise RuntimeError("304 with no local cache")
                used_cache = True
                for item in cached:
                    yield item
                return
            if 500 <= e.code < 600:
                _log(f"ERROR: page={page_idx} HTTP 5xx: {e.code} {e.reason}")
                raise RuntimeError(f"registry 5xx {e.code}") from e
            _log(f"ERROR: page={page_idx} HTTP {e.code} {e.reason}")
            raise RuntimeError(f"registry HTTP {e.code}") from e
        except urllib.error.URLError as e:
            _log(f"ERROR: page={page_idx} URL error: {e.reason}")
            raise RuntimeError(f"registry URL error: {e.reason}") from e
        except TimeoutError as e:
            # urllib.request.urlopen(timeout=N) 触发的 socket.timeout 在新 Python 里
            # 是 TimeoutError 的别名，不是 URLError 子类，必须单独捕获否则会逃逸出
            # main()，产生不友好的 traceback 与错误退出码。
            _log(f"ERROR: page={page_idx} timeout after {timeout}s: {e}")
            raise RuntimeError(f"registry timeout after {timeout}s") from e

        if page_idx == 1 and etag:
            new_etag = etag

        if not isinstance(data, dict) or "servers" not in data:
            _log(f"ERROR: page={page_idx} unexpected schema: missing 'servers' key")
            raise RuntimeError("registry response missing 'servers' key")
        servers = data.get("servers") or []
        if not isinstance(servers, list):
            _log(f"ERROR: page={page_idx} 'servers' is not a list")
            raise RuntimeError("registry 'servers' is not a list")
        aggregated.extend(servers)
        for item in servers:
            yield item

        metadata = data.get("metadata") or {}
        next_cursor = metadata.get("nextCursor") or ""
        _log(
            f"INFO: page={page_idx} fetched {len(servers)} entries "
            f"(total={len(aggregated)}, nextCursor={next_cursor[:32] + '...' if next_cursor else 'None'})"
        )
        if not next_cursor:
            break
        cursor = next_cursor

    # 落盘整页缓存 + 新 ETag
    if not used_cache:
        _save_local_registry_cache(aggregated)
        if new_etag:
            _write_etag(new_etag)
        _log(f"INFO: cached {len(aggregated)} entries, etag={new_etag[:16]}...")


# ---------------------------------------------------------------------------
# 过滤
# ---------------------------------------------------------------------------

def _get_official_meta(raw: dict) -> dict:
    meta = (raw or {}).get("_meta") or {}
    return meta.get(META_KEY) or {}


def is_active_and_latest(raw: dict) -> bool:
    """检查 status==active 且 isLatest==true。"""
    official = _get_official_meta(raw)
    if not official:
        return False
    return official.get("status") == "active" and official.get("isLatest") is True


def is_latest(raw: dict) -> bool:
    """检查 isLatest==true（不限制 status）。

    diff 计算需要更广的视角（包含 deprecated 等非 active 但 isLatest 的条目），
    才能正确捕获 active→deprecated 的 status_changed 转移；否则这类 entry 会被
    过滤后误判为 removed。
    """
    official = _get_official_meta(raw)
    if not official:
        return False
    return official.get("isLatest") is True


# ---------------------------------------------------------------------------
# 转换
# ---------------------------------------------------------------------------

_ID_INVALID_RE = re.compile(r"[^a-z0-9-]+")


def _kebab(s: str) -> str:
    s = (s or "").lower().strip()
    s = re.sub(r"[\s_./]+", "-", s)
    s = _ID_INVALID_RE.sub("-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s


def _make_id(server_name: str) -> str:
    """基于 server.name 生成稳定 kebab-case id。

    server.name 形如 io.github.<owner>/<repo> 或 com.example/product。
    同一 name 多次 sync 必须产出同一 id。

    为避免 kebab 化后冲突（例如 io.github.foo/bar-baz 与 io.github.foo-bar/baz
    都会 kebab 成 io-github-foo-bar-baz），始终追加 8 位 SHA-1 短哈希后缀。
    哈希基于原始 server_name，保证：
    - 同一 server_name 永远得到同一 id（稳定）
    - 不同 server_name 即使 kebab 一致也不会碰撞
    """
    sk = _kebab(server_name)
    if not sk:
        sk = "mcp-server"
    h = hashlib.sha1((server_name or "").encode("utf-8")).hexdigest()[:8]
    return f"{sk}-{h}"


def _registry_fallback_url(server_name: str) -> str:
    """无 GitHub repository 时的 fallback：registry URL + URL-encoded name。"""
    encoded = urllib.parse.quote(server_name or "", safe="")
    return f"{REGISTRY_BASE}/{encoded}"


def _build_source_url(server: dict, registry_name: str) -> str:
    """优先使用 server.repository.url（GitHub 真实仓库），fallback 到 registry URL。

    规则（§14 修复 A）：
    - server.repository.source == "github" 且 url 非空 → 用 repo URL
    - 含 subfolder（monorepo）→ 拼接 ``/tree/HEAD/<subfolder>``
    - 否则（SaaS / 商业 server 无 GitHub repo）→ registry URL fallback

    这样去重 / health 信号 / LLM 评估都能拿到真实 GitHub 链接，避免所有 entry
    的 source_url 都落在 registry.modelcontextprotocol.io 上。
    """
    repo = (server or {}).get("repository") or {}
    if isinstance(repo, dict) and (repo.get("source") or "").lower() == "github":
        url = (repo.get("url") or "").rstrip("/")
        if url:
            subfolder = (repo.get("subfolder") or "").strip("/")
            if subfolder:
                return f"{url}/tree/HEAD/{subfolder}"
            return url
    return _registry_fallback_url(registry_name)


def _build_install(server: dict) -> dict:
    """根据 server.packages[] 构建 install 字典；无 packages 时退化为 manual。

    §14 修复 B：把 npm/pypi/cargo/oci 等真实安装信息塞入 install.config，
    供消费者 / LLM 看到具体命令而非空 manual。catalog schema 仍要求
    install.method ∈ {mcp_config|mcp_config_template|manual|git_clone|download_file}，
    所以保持 "manual" 不变；config 是任意 object，安全嵌入扩展字段。
    """
    packages = server.get("packages") or []
    remotes_raw = server.get("remotes") or []

    # mcp_remotes 字段：array of {type, url}
    mcp_remotes: list = []
    for r in remotes_raw:
        if not isinstance(r, dict):
            continue
        rtype = r.get("type") or ""
        rurl = r.get("url") or ""
        if not rtype and not rurl:
            continue
        mcp_remotes.append({"type": rtype, "url": rurl})

    if isinstance(packages, list) and packages:
        pkg = packages[0] if isinstance(packages[0], dict) else {}
        registry_type = (pkg.get("registryType") or "").lower()
        ident = pkg.get("identifier") or ""
        ver = pkg.get("version") or ""

        if registry_type == "npm":
            cmd = f"npx -y {ident}@{ver}" if ver else f"npx -y {ident}"
        elif registry_type == "pypi":
            cmd = f"pipx run {ident}=={ver}" if ver else f"pipx run {ident}"
        elif registry_type == "cargo":
            cmd = f"cargo install {ident}@{ver}" if ver else f"cargo install {ident}"
        elif registry_type == "oci":
            cmd = f"docker run {ident}:{ver}" if ver else f"docker run {ident}"
        elif registry_type and ident:
            cmd = f"{registry_type}: {ident}@{ver}" if ver else f"{registry_type}: {ident}"
        else:
            cmd = ""

        config: dict = {
            "registry_type": registry_type,
            "identifier": ident,
            "version": ver,
        }
        if cmd:
            config["command"] = cmd

        return {
            "method": "manual",
            "config": config,
            "remotes": mcp_remotes,
        }

    return {"method": "manual", "remotes": mcp_remotes}


def normalize_entry(raw: dict) -> dict:
    """将 registry server entry 转换为 catalog mcp schema。"""
    server = (raw or {}).get("server") or {}
    official = _get_official_meta(raw)

    server_name = server.get("name") or ""
    title = server.get("title") or server_name
    description = server.get("description") or ""
    version = server.get("version") or ""
    website_url = server.get("websiteUrl") or ""

    install = _build_install(server)
    mcp_remotes = install.get("remotes") or []

    entry: dict = {
        "id": _make_id(server_name),
        "name": title,
        "type": "mcp",
        "description": description,
        "source_url": _build_source_url(server, server_name),
        "stars": None,
        "category": "tooling",
        "tags": [],
        "tech_stack": [],
        "install": install,
        "source": SOURCE_NAME,
        "last_synced": TODAY,
        # 三个新字段
        "version": version,
        "mcp_registry_status": official.get("status") or "",
        "mcp_registry_published_at": official.get("publishedAt") or "",
        "mcp_remotes": mcp_remotes,
    }
    if website_url:
        entry["website_url"] = website_url
    return entry


# ---------------------------------------------------------------------------
# 增量 diff
# ---------------------------------------------------------------------------

def _diff_signature(entry: dict) -> tuple:
    """diff 比较签名：(version, mcp_registry_status, statusChangedAt 替代用 published_at)。

    R5 要求按 (server.version, _meta.statusChangedAt) 比较。statusChangedAt 不映射到
    catalog entry，因此 diff 直接消费 raw entry 的 _meta；当我们仅有 normalized
    entry 时（如本地上次输出），用 (version, status, published_at) 替代——published_at
    在 status 改变或 version 变更时也会刷新。
    """
    return (
        entry.get("version") or "",
        entry.get("mcp_registry_status") or "",
        entry.get("mcp_registry_published_at") or "",
    )


def compute_diff(prev_entries: list, new_entries: list) -> dict:
    """对比上次与本次输出。

    四类：added / status_changed / version_bumped / removed；stable 仅记数。
    """
    prev_map = {e.get("id"): e for e in prev_entries if e.get("id")}
    new_map = {e.get("id"): e for e in new_entries if e.get("id")}

    added = sorted(set(new_map) - set(prev_map))
    removed = sorted(set(prev_map) - set(new_map))
    common = set(prev_map) & set(new_map)

    status_changed: list = []
    version_bumped: list = []
    stable = 0
    for sid in common:
        old = prev_map[sid]
        new = new_map[sid]
        old_v = old.get("version") or ""
        new_v = new.get("version") or ""
        old_s = old.get("mcp_registry_status") or ""
        new_s = new.get("mcp_registry_status") or ""
        if old_s != new_s:
            status_changed.append({"id": sid, "old": old_s, "new": new_s})
        elif old_v != new_v:
            version_bumped.append({"id": sid, "old": old_v, "new": new_v})
        else:
            # 即使 published_at 变了，只要 version+status 一致仍视作 stable
            stable += 1

    return {
        "added": added,
        "status_changed": sorted(status_changed, key=lambda x: x["id"]),
        "version_bumped": sorted(version_bumped, key=lambda x: x["id"]),
        "removed": removed,
        "stable": stable,
    }


def _load_prev_output() -> list:
    if not os.path.exists(OUTPUT_PATH):
        return []
    try:
        with open(OUTPUT_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
            return []
    except (json.JSONDecodeError, OSError) as e:
        _log(f"WARNING: previous output corrupted: {e}")
        return []


def _load_diff_baseline() -> list:
    """加载上次的 diff 基线（所有 isLatest，含非 active）。

    与 OUTPUT_PATH（仅 active+isLatest）不同：diff 视角的基线在更广的集合上工作，
    保证非 active 但 isLatest 的条目不会在每次 run 都被报告为 added。
    文件不存在时回退到 OUTPUT_PATH（首次升级路径），保留原有行为。
    """
    if not os.path.exists(DIFF_BASELINE_PATH):
        # 首次启用基线：以现有 OUTPUT 作为兼容回退，避免一上来全部条目刷成 added
        return _load_prev_output()
    try:
        with open(DIFF_BASELINE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
            return []
    except (json.JSONDecodeError, OSError) as e:
        _log(f"WARNING: diff baseline corrupted: {e}")
        return []


def _save_diff_baseline(entries: list) -> None:
    _ensure_cache_dir()
    with open(DIFF_BASELINE_PATH, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main() -> int:
    load_plugin_sources()  # warm cache; warns once if missing/unparseable
    _log(f"INFO: fetching {REGISTRY_BASE} (limit={DEFAULT_LIMIT})")

    try:
        raw_iter = fetch_registry(limit=DEFAULT_LIMIT)
        all_raw = list(raw_iter)
    except RuntimeError as e:
        _log(f"ERROR: fetch_registry failed: {e}")
        return 1

    _log(f"INFO: total raw entries fetched: {len(all_raw)}")

    # 第一层：仅按 isLatest 过滤（保留所有 status，含 deprecated/inactive）
    # 这是 diff 的输入集，确保 active→deprecated 这类 status 转移不会被误判为 removed
    latest_raw = [r for r in all_raw if is_latest(r)]
    _log(
        f"INFO: filtered isLatest (any status): {len(latest_raw)} "
        f"(from {len(all_raw)})"
    )

    def _normalize_with_dedup(raw_list: list) -> list:
        out: list = []
        seen: set = set()
        for r in raw_list:
            entry = normalize_entry(r)
            # source_url 现在可能是 GitHub URL（修复 A 后），仅校验非空 + 有 id
            if not entry["id"] or not entry.get("source_url"):
                _log(f"WARNING: skipped invalid entry id={entry.get('id')}")
                continue
            if entry["id"] in seen:
                _log(
                    f"WARNING: duplicate id={entry['id']} (server.name={r.get('server', {}).get('name')}), skipping"
                )
                continue
            # plugin_sources.json skip — match either the (possibly GitHub)
            # source_url or the reverse-DNS server name `io.github.owner/repo`
            # (is_plugin_source rewrites the latter to canonical GitHub form).
            server_name = (r.get("server") or {}).get("name") or ""
            if (
                is_plugin_source(entry.get("source_url", ""))
                or is_plugin_source(server_name)
            ):
                logger.debug(
                    f"skipping {entry.get('id', '<unknown>')}: in plugin_sources.json"
                )
                continue
            seen.add(entry["id"])
            out.append(entry)
        out.sort(key=lambda e: e["id"])
        return out

    # diff 视角：所有 isLatest 条目（含 deprecated 等），用来正确识别 status_changed
    diff_entries = _normalize_with_dedup(latest_raw)

    # 输出视角：仅 active + isLatest（行为不变，写盘集合保持精简）
    active_raw = [r for r in latest_raw if is_active_and_latest(r)]
    entries = _normalize_with_dedup(active_raw)
    _log(
        f"INFO: filtered active+isLatest: {len(entries)} "
        f"(from {len(latest_raw)} isLatest)"
    )

    # diff: 上次「diff 基线」 vs 本次「diff 视角」全集
    # 基线持久化所有 isLatest 条目（含非 active），与 diff_entries 同集合范畴；
    # 否则非 active 条目会在 prev 中缺席、在 diff_entries 中常驻，被反复识别为
    # added。首次运行 baseline 文件不存在时回退到 OUTPUT_PATH 兼容旧仓库状态。
    prev = _load_diff_baseline()
    diff = compute_diff(prev, diff_entries)
    _log(
        f"INFO: diff vs previous: +{len(diff['added'])} added, "
        f"~status={len(diff['status_changed'])}, "
        f"~version={len(diff['version_bumped'])}, "
        f"-{len(diff['removed'])} removed, "
        f"={diff['stable']} stable"
    )

    # 写盘
    _ensure_cache_dir()
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2, ensure_ascii=False)
    _log(f"INFO: wrote {len(entries)} entries to {OUTPUT_PATH}")

    with open(DIFF_PATH, "w", encoding="utf-8") as f:
        json.dump(diff, f, indent=2, ensure_ascii=False)
    _log(f"INFO: wrote diff to {DIFF_PATH}")

    # 持久化本次「diff 视角」全集为下次 run 的基线
    _save_diff_baseline(diff_entries)
    _log(f"INFO: wrote diff baseline ({len(diff_entries)} entries) to {DIFF_BASELINE_PATH}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
