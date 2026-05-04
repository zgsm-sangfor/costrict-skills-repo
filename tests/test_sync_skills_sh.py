"""scripts/sync_skills_sh.py 单元测试。

覆盖：
- 正常拉取 mastra 快照（200 OK）
- ETag 命中走本地缓存（304 Not Modified）
- scrapedAt 陈旧 → should_use_fallback=True
- scrapedAt 新鲜 → should_use_fallback=False
- 阈值过滤（默认 1000 / 环境变量覆盖）
- normalize_entry 生成的 id 唯一性（同 owner 不同 repo 同 skillId）
- normalize_entry 生成的 source_url 含 #skill= anchor
- 双路径都失败 → 退出码 2
- compute_diff 生成 added/changed/removed/stable 类目
"""

import io
import json
import os
import sys
import tempfile
import unittest
import unittest.mock as mock
import urllib.error
from datetime import datetime, timedelta, timezone

SCRIPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts"))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import sync_skills_sh as sss  # noqa: E402


def _make_response(body: bytes, etag: str = ""):
    """构造一个伪 urlopen 响应对象，模拟 read() / headers.get()。"""
    class _Resp:
        def __init__(self, body, etag):
            self._body = body
            self.headers = {"ETag": etag} if etag else {}

        def read(self):
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    # headers 需要 get(name, default) 接口
    class _Headers(dict):
        def get(self, name, default=""):
            return super().get(name, default)

    r = _Resp(body, etag)
    h = _Headers()
    if etag:
        h["ETag"] = etag
    r.headers = h
    return r


class _CacheDirSandbox:
    """临时切换 sync_skills_sh 模块的缓存路径常量到一个临时目录。"""

    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._patches = []

    def __enter__(self):
        cache_dir = os.path.join(self.tmp.name, ".skills_sh_cache")
        os.makedirs(cache_dir, exist_ok=True)
        catalog_dir = os.path.join(self.tmp.name, "catalog", "skills")
        os.makedirs(catalog_dir, exist_ok=True)
        self._patches = [
            mock.patch.object(sss, "CACHE_DIR", cache_dir),
            mock.patch.object(sss, "MASTRA_CACHE_PATH", os.path.join(cache_dir, "mastra.json")),
            mock.patch.object(sss, "ETAG_PATH", os.path.join(cache_dir, "etag.txt")),
            mock.patch.object(sss, "DIFF_PATH", os.path.join(cache_dir, "diff.json")),
            mock.patch.object(
                sss,
                "OUTPUT_PATH",
                os.path.join(catalog_dir, "skills_sh_index.json"),
            ),
        ]
        for p in self._patches:
            p.start()
        self.cache_dir = cache_dir
        self.catalog_dir = catalog_dir
        return self

    def __exit__(self, *exc):
        for p in self._patches:
            p.stop()
        self.tmp.cleanup()
        return False


# ---------------------------------------------------------------------------
# fetch_mastra_snapshot
# ---------------------------------------------------------------------------

class TestFetchMastraSnapshot(unittest.TestCase):
    def test_fetch_success_200(self):
        """200 OK 时返回解析后的 dict 并落盘缓存 + ETag。"""
        with _CacheDirSandbox() as box:
            payload = {
                "scrapedAt": "2026-05-01T00:00:00.000Z",
                "totalSkills": 1,
                "skills": [{"skillId": "foo", "owner": "bar", "installs": 2000}],
            }
            body = json.dumps(payload).encode("utf-8")
            with mock.patch.object(
                sss.urllib.request, "urlopen",
                return_value=_make_response(body, etag="abc123"),
            ):
                result = sss.fetch_mastra_snapshot()
            self.assertEqual(result["totalSkills"], 1)
            # 缓存 / ETag 已落盘
            self.assertTrue(os.path.exists(sss.MASTRA_CACHE_PATH))
            self.assertTrue(os.path.exists(sss.ETAG_PATH))
            with open(sss.ETAG_PATH, "r", encoding="utf-8") as f:
                self.assertEqual(f.read().strip(), "abc123")

    def test_fetch_etag_304_uses_local_cache(self):
        """304 Not Modified 时复用本地 mastra.json。"""
        with _CacheDirSandbox() as box:
            cached = {"scrapedAt": "2026-04-30T00:00:00.000Z", "totalSkills": 0, "skills": []}
            with open(sss.MASTRA_CACHE_PATH, "w", encoding="utf-8") as f:
                json.dump(cached, f)
            with open(sss.ETAG_PATH, "w", encoding="utf-8") as f:
                f.write("oldetag")

            err = urllib.error.HTTPError(
                url=sss.MASTRA_URL, code=304, msg="Not Modified", hdrs=None, fp=None
            )
            with mock.patch.object(sss.urllib.request, "urlopen", side_effect=err):
                result = sss.fetch_mastra_snapshot()
            self.assertEqual(result["scrapedAt"], "2026-04-30T00:00:00.000Z")

    def test_fetch_dual_path_failure_exits_2(self):
        """网络失败 + 本地无缓存 → sys.exit(2)。"""
        with _CacheDirSandbox() as box:
            # 不预置 cache
            err = urllib.error.URLError(reason="connection refused")
            with mock.patch.object(sss.urllib.request, "urlopen", side_effect=err):
                with self.assertRaises(SystemExit) as ctx:
                    sss.fetch_mastra_snapshot()
            self.assertEqual(ctx.exception.code, 2)


# ---------------------------------------------------------------------------
# should_use_fallback
# ---------------------------------------------------------------------------

class TestShouldUseFallback(unittest.TestCase):
    def test_stale_8_days_old(self):
        """8 天前的 scrapedAt 应该触发 fallback（默认阈值 7 天）。"""
        ts = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat().replace("+00:00", "Z")
        self.assertTrue(sss.should_use_fallback({"scrapedAt": ts}, max_days=7))

    def test_fresh_1_day_old(self):
        """1 天前不触发。"""
        ts = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat().replace("+00:00", "Z")
        self.assertFalse(sss.should_use_fallback({"scrapedAt": ts}, max_days=7))

    def test_missing_scraped_at_treated_as_stale(self):
        """无 scrapedAt 字段视为陈旧（保守降级）。"""
        self.assertTrue(sss.should_use_fallback({}, max_days=7))

    def test_invalid_scraped_at_treated_as_stale(self):
        self.assertTrue(sss.should_use_fallback({"scrapedAt": "not-a-date"}, max_days=7))

    def test_paginated_endpoint_returns_empty_on_404(self):
        """skills.sh 分页端点 404 → 返回空列表（不抛错）。"""
        err = urllib.error.HTTPError(
            url="x", code=404, msg="Not Found", hdrs=None, fp=None
        )
        with mock.patch.object(sss.urllib.request, "urlopen", side_effect=err):
            out = sss.fetch_skills_sh_paginated()
        self.assertEqual(out, [])


# ---------------------------------------------------------------------------
# Threshold filter (in main flow)
# ---------------------------------------------------------------------------

class TestThresholdFilter(unittest.TestCase):
    def _run_main_with(self, raw_skills, env=None):
        """跑 main()，注入指定 raw skills 与可选环境变量，返回输出 entries。"""
        snapshot = {
            "scrapedAt": (
                datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            ),
            "totalSkills": len(raw_skills),
            "skills": raw_skills,
        }
        with _CacheDirSandbox() as box, \
             mock.patch.object(sss, "fetch_mastra_snapshot", return_value=snapshot):
            # 重新读取阈值（环境变量在模块加载时就 freeze 了）。
            with mock.patch.object(
                sss,
                "DEFAULT_MIN_INSTALLS",
                int((env or {}).get("SKILLS_SH_MIN_INSTALLS", "1000")),
            ):
                rc = sss.main()
            self.assertEqual(rc, 0)
            with open(sss.OUTPUT_PATH, "r", encoding="utf-8") as f:
                return json.load(f)

    def test_default_threshold_1000(self):
        """install_count < 1000 的条目被过滤。"""
        raw = [
            {"skillId": "a", "owner": "x", "repo": "r1", "installs": 5000,
             "githubUrl": "https://github.com/x/r1"},
            {"skillId": "b", "owner": "y", "repo": "r2", "installs": 500,
             "githubUrl": "https://github.com/y/r2"},
            {"skillId": "c", "owner": "z", "repo": "r3", "installs": 1200,
             "githubUrl": "https://github.com/z/r3"},
        ]
        entries = self._run_main_with(raw)
        ids = [e["name"] for e in entries]
        self.assertIn("a", ids)
        self.assertIn("c", ids)
        self.assertNotIn("b", ids)

    def test_env_override_threshold(self):
        """SKILLS_SH_MIN_INSTALLS=2000 → 1500 被过滤。"""
        raw = [
            {"skillId": "a", "owner": "x", "repo": "r1", "installs": 1500,
             "githubUrl": "https://github.com/x/r1"},
            {"skillId": "b", "owner": "y", "repo": "r2", "installs": 3000,
             "githubUrl": "https://github.com/y/r2"},
        ]
        entries = self._run_main_with(raw, env={"SKILLS_SH_MIN_INSTALLS": "2000"})
        names = [e["name"] for e in entries]
        self.assertNotIn("a", names)
        self.assertIn("b", names)


# ---------------------------------------------------------------------------
# normalize_entry: id uniqueness + source_url anchor
# ---------------------------------------------------------------------------

class TestNormalizeEntry(unittest.TestCase):
    def test_id_uniqueness_same_owner_diff_repo_same_skillid(self):
        """同 owner、不同 repo、同 skillId → id 应不同（包含 repo 段）。"""
        e1 = sss.normalize_entry({
            "skillId": "frontend-design",
            "owner": "anthropics",
            "repo": "skills",
            "githubUrl": "https://github.com/anthropics/skills",
            "installs": 65000,
        })
        e2 = sss.normalize_entry({
            "skillId": "frontend-design",
            "owner": "anthropics",
            "repo": "claude-code",
            "githubUrl": "https://github.com/anthropics/claude-code",
            "installs": 50000,
        })
        self.assertNotEqual(e1["id"], e2["id"])
        # 两个 id 都以 frontend-design 开头
        self.assertTrue(e1["id"].startswith("frontend-design-"))
        self.assertTrue(e2["id"].startswith("frontend-design-"))

    def test_source_url_contains_skill_anchor(self):
        """source_url 应附带 #skill={skillId} 让同 repo 多 skill 区分。"""
        e = sss.normalize_entry({
            "skillId": "react-best-practices",
            "owner": "vercel-labs",
            "repo": "agent-skills",
            "githubUrl": "https://github.com/vercel-labs/agent-skills",
            "installs": 8000,
        })
        self.assertIn("#skill=react-best-practices", e["source_url"])

    def test_skills_sh_url_format(self):
        """skills_sh_url 格式正确（owner/repo/skillId）。"""
        e = sss.normalize_entry({
            "skillId": "foo",
            "owner": "bar",
            "repo": "baz",
            "githubUrl": "https://github.com/bar/baz",
            "installs": 1500,
        })
        self.assertEqual(e["skills_sh_url"], "https://skills.sh/bar/baz/foo")
        self.assertEqual(e["install_count"], 1500)
        self.assertEqual(e["source"], "skills-sh")
        self.assertEqual(e["type"], "skill")

    def test_id_avoids_repo_redundancy_when_repo_eq_skillid(self):
        """repo 与 skillId 重复时不重复加 repo 段（避免 frontend-foo-foo-foo）。"""
        e = sss.normalize_entry({
            "skillId": "skills",
            "owner": "anthropics",
            "repo": "skills",
            "githubUrl": "https://github.com/anthropics/skills",
            "installs": 1000,
        })
        # id 应该是 skills-anthropics 而不是 skills-anthropics-skills
        self.assertEqual(e["id"], "skills-anthropics")


# ---------------------------------------------------------------------------
# compute_diff
# ---------------------------------------------------------------------------

class TestComputeDiff(unittest.TestCase):
    def test_diff_added_changed_removed_stable(self):
        """覆盖四种类目：added / changed / removed / stable。"""
        prev = [
            {"id": "stable-1", "install_count": 5000},
            {"id": "stable-2", "install_count": 1200},
            {"id": "changed-1", "install_count": 1000},  # +50%
            {"id": "removed-1", "install_count": 3000},
        ]
        new = [
            {"id": "stable-1", "install_count": 5100},  # +2%, stable
            {"id": "stable-2", "install_count": 1200},
            {"id": "changed-1", "install_count": 1500},  # +50%
            {"id": "added-1", "install_count": 8000},
        ]
        diff = sss.compute_diff(prev, new)
        self.assertEqual(diff["added"], ["added-1"])
        self.assertEqual(diff["removed"], ["removed-1"])
        # stable 计数应为 2（stable-1 与 stable-2）
        self.assertEqual(diff["stable"], 2)
        # changed 列表至少含 changed-1，比例 +50%
        ids = [c["id"] for c in diff["changed_install_count"]]
        self.assertIn("changed-1", ids)
        c1 = next(c for c in diff["changed_install_count"] if c["id"] == "changed-1")
        self.assertAlmostEqual(c1["pct"], 0.5, places=4)

    def test_diff_zero_to_significant_recorded(self):
        """旧值为 0 / 新值 ≥ 1000 → 记录为变化。"""
        prev = [{"id": "x", "install_count": 0}]
        new = [{"id": "x", "install_count": 5000}]
        diff = sss.compute_diff(prev, new)
        self.assertEqual(len(diff["changed_install_count"]), 1)
        self.assertIsNone(diff["changed_install_count"][0]["pct"])

    def test_diff_zero_to_small_stable(self):
        """旧值为 0 / 新值 < 1000 → 视为 stable。"""
        prev = [{"id": "x", "install_count": 0}]
        new = [{"id": "x", "install_count": 100}]
        diff = sss.compute_diff(prev, new)
        self.assertEqual(diff["stable"], 1)
        self.assertEqual(diff["changed_install_count"], [])


if __name__ == "__main__":
    unittest.main()
