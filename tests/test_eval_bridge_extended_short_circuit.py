"""Section 8 增量评估保护：mcp_registry / windsurfrules 短路。

测试目标：
- mcp_registry diff 解析 + 不稳定 id 集合
- mcp_registry 派生判定（registry source / source_url / mcp_registry_status）
- mcp_registry stable + cache 命中 → 短路
- mcp_registry unstable（added / removed / status_changed / version_bumped）→ 不短路
- windsurfrules 派生判定（source / 双仓 source_url）
- windsurfrules cache 命中 → 短路（无 diff 依赖）
- windsurfrules cache miss → 不短路
- rubric_version stable：mcp_server / rule task config 字段存在且非空
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))


# ---------------------------------------------------------------------------
# Fakes (模拟 EvalCache 行为，与 test_eval_bridge_skills_sh_incremental 对齐)
# ---------------------------------------------------------------------------


class _FakeCache:
    def __init__(self, store: dict[str, dict]):
        self._store = store

    def _conn(self):
        return _FakeConn(self._store)


class _FakeConn:
    def __init__(self, store: dict[str, dict]):
        self._store = store

    def execute(self, sql: str, params: tuple):
        eid = params[0]
        if eid in self._store:
            r = self._store[eid]
            return _FakeRow(
                {
                    "result_json": json.dumps(r),
                    "expires_at": "2099-01-01T00:00:00+00:00",
                    "evaluated_at": "2026-04-01T00:00:00+00:00",
                }
            )
        return _FakeRow(None)


class _FakeRow:
    def __init__(self, data: dict | None):
        self._data = data

    def fetchone(self):
        return self._data


def _cached_result(entry_id: str) -> dict:
    return {
        "entry_id": entry_id,
        "metrics": {},
        "enrichment": None,
        "health": {
            "freshness": 80.0,
            "popularity": 50.0,
            "source_trust": 70.0,
        },
        "llm_score": 70.0,
        "final_score": 75.0,
        "decision": "accept",
        "star_weight": 1.0,
        "content_hash": "abc",
        "rubric_version": "1.deadbeef",
        "model_id": "deepseek-chat",
        "evaluated_at": "2026-04-16T00:00:00Z",
    }


# ---------------------------------------------------------------------------
# mcp_registry diff loading
# ---------------------------------------------------------------------------


class TestMcpRegistryDiffLoad:
    def test_loads_valid_diff(self, tmp_path):
        from eval_bridge import load_mcp_registry_diff

        path = tmp_path / "diff.json"
        diff = {
            "added": ["a"],
            "removed": ["b"],
            "status_changed": [{"id": "c", "old": "active", "new": "deprecated"}],
            "version_bumped": [{"id": "d", "old": "1.0", "new": "1.1"}],
            "stable": 5,
        }
        path.write_text(json.dumps(diff))

        loaded = load_mcp_registry_diff(path)
        assert loaded["added"] == ["a"]
        assert loaded["status_changed"][0]["id"] == "c"
        assert loaded["stable"] == 5

    def test_missing_returns_empty(self, tmp_path):
        from eval_bridge import load_mcp_registry_diff

        loaded = load_mcp_registry_diff(tmp_path / "nope.json")
        assert loaded == {}

    def test_corrupt_returns_empty(self, tmp_path):
        from eval_bridge import load_mcp_registry_diff

        path = tmp_path / "bad.json"
        path.write_text("{not json")

        assert load_mcp_registry_diff(path) == {}


class TestMcpRegistryUnstableIds:
    def test_collects_all_four_categories(self):
        from eval_bridge import _mcp_registry_unstable_ids

        diff = {
            "added": ["a", "b"],
            "removed": ["c"],
            "status_changed": [
                {"id": "d", "old": "active", "new": "deprecated"},
                {"id": "e", "old": "active", "new": "inactive"},
            ],
            "version_bumped": [{"id": "f", "old": "1.0", "new": "2.0"}],
            "stable": 3,
        }
        ids = _mcp_registry_unstable_ids(diff)
        assert ids == {"a", "b", "c", "d", "e", "f"}

    def test_empty_diff(self):
        from eval_bridge import _mcp_registry_unstable_ids

        assert _mcp_registry_unstable_ids({}) == set()

    def test_skips_malformed_items(self):
        from eval_bridge import _mcp_registry_unstable_ids

        diff = {
            "added": [],
            "status_changed": [{"old": "x"}, "bad", {"id": "good"}],
            "version_bumped": ["bad-string"],
        }
        # 只收集合法 dict 中的 id
        assert _mcp_registry_unstable_ids(diff) == {"good"}


# ---------------------------------------------------------------------------
# mcp_registry 派生判定
# ---------------------------------------------------------------------------


class TestMcpRegistryDerived:
    def test_source_match(self):
        from eval_bridge import _is_mcp_registry_derived

        assert _is_mcp_registry_derived(
            {"source": "registry.modelcontextprotocol.io"}
        )

    def test_source_url_match(self):
        from eval_bridge import _is_mcp_registry_derived

        assert _is_mcp_registry_derived(
            {
                "source": "awesome-mcp-servers",  # 不同 source
                "source_url": (
                    "https://registry.modelcontextprotocol.io/v0/servers/io.github.foo"
                ),
            }
        )

    def test_merged_winner_with_status_field_not_derived(self):
        """codex review §8 finding #2：merge 后 winner 的 source_url 是 GitHub URL，
        即便 mcp_registry_status 字段保留也不视为 mcp_registry 派生——registry diff
        用 registry id，winner.id 是 GitHub id 二者不对应，短路会误复用旧评分。
        """
        from eval_bridge import _is_mcp_registry_derived

        assert not _is_mcp_registry_derived(
            {
                "source": "awesome-mcp-servers",
                "source_url": "https://github.com/foo/bar",
                "mcp_registry_status": "active",
            }
        )

    def test_non_match(self):
        from eval_bridge import _is_mcp_registry_derived

        assert not _is_mcp_registry_derived(
            {"source": "awesome-mcp-servers", "source_url": "https://github.com/x/y"}
        )


# ---------------------------------------------------------------------------
# mcp_registry 短路集成
# ---------------------------------------------------------------------------


def _make_registry_entry(eid: str, **overrides) -> dict:
    entry = {
        "id": eid,
        "name": eid,
        "type": "mcp",
        "description": "Registry MCP server",
        "source_url": (
            f"https://registry.modelcontextprotocol.io/v0/servers/io.github.{eid}"
        ),
        "source": "registry.modelcontextprotocol.io",
        "mcp_registry_status": "active",
        "mcp_registry_published_at": "2026-04-01T00:00:00Z",
    }
    entry.update(overrides)
    return entry


class TestMcpRegistryShortCircuit:
    def test_stable_with_cache_hits_short_circuit(self):
        from eval_bridge import _select_mcp_registry_short_circuit_entries

        entries = [_make_registry_entry("e1"), _make_registry_entry("e2")]
        diff = {
            "added": [],
            "removed": [],
            "status_changed": [],
            "version_bumped": [],
            "stable": 2,
        }
        cache = _FakeCache({"e1": _cached_result("e1"), "e2": _cached_result("e2")})

        short, remaining = _select_mcp_registry_short_circuit_entries(
            entries, cache, diff
        )

        assert set(short.keys()) == {"e1", "e2"}
        assert short["e1"]["model_id"] == "__cached__"
        assert remaining == []

    def test_added_entry_not_short_circuited(self):
        from eval_bridge import _select_mcp_registry_short_circuit_entries

        entries = [_make_registry_entry("new-id"), _make_registry_entry("stable-id")]
        diff = {
            "added": ["new-id"],
            "removed": [],
            "status_changed": [],
            "version_bumped": [],
        }
        cache = _FakeCache(
            {
                "new-id": _cached_result("new-id"),
                "stable-id": _cached_result("stable-id"),
            }
        )

        short, remaining = _select_mcp_registry_short_circuit_entries(
            entries, cache, diff
        )

        assert "stable-id" in short
        assert "new-id" not in short
        assert any(e["id"] == "new-id" for e in remaining)

    def test_status_changed_entry_not_short_circuited(self):
        from eval_bridge import _select_mcp_registry_short_circuit_entries

        entries = [_make_registry_entry("changed-id"), _make_registry_entry("stable-id")]
        diff = {
            "added": [],
            "removed": [],
            "status_changed": [
                {"id": "changed-id", "old": "active", "new": "deprecated"}
            ],
            "version_bumped": [],
        }
        cache = _FakeCache(
            {
                "changed-id": _cached_result("changed-id"),
                "stable-id": _cached_result("stable-id"),
            }
        )

        short, remaining = _select_mcp_registry_short_circuit_entries(
            entries, cache, diff
        )

        assert "stable-id" in short
        assert "changed-id" not in short

    def test_version_bumped_entry_not_short_circuited(self):
        from eval_bridge import _select_mcp_registry_short_circuit_entries

        entries = [_make_registry_entry("bumped-id"), _make_registry_entry("stable-id")]
        diff = {
            "added": [],
            "removed": [],
            "status_changed": [],
            "version_bumped": [{"id": "bumped-id", "old": "1.0", "new": "2.0"}],
        }
        cache = _FakeCache(
            {
                "bumped-id": _cached_result("bumped-id"),
                "stable-id": _cached_result("stable-id"),
            }
        )

        short, remaining = _select_mcp_registry_short_circuit_entries(
            entries, cache, diff
        )

        assert "stable-id" in short
        assert "bumped-id" not in short

    def test_no_cache_entry_skip_short_circuit(self):
        from eval_bridge import _select_mcp_registry_short_circuit_entries

        entries = [_make_registry_entry("uncached")]
        diff = {"added": [], "removed": [], "status_changed": [], "version_bumped": []}
        cache = _FakeCache({})

        short, remaining = _select_mcp_registry_short_circuit_entries(
            entries, cache, diff
        )

        assert short == {}
        assert remaining == entries

    def test_non_registry_entry_not_short_circuited(self):
        from eval_bridge import _select_mcp_registry_short_circuit_entries

        non_registry = {
            "id": "x1",
            "type": "mcp",
            "source": "awesome-mcp-servers",
            "source_url": "https://github.com/foo/bar",
        }
        diff = {"added": [], "removed": [], "status_changed": [], "version_bumped": []}
        cache = _FakeCache({"x1": _cached_result("x1")})

        short, remaining = _select_mcp_registry_short_circuit_entries(
            [non_registry], cache, diff
        )

        assert short == {}
        assert remaining == [non_registry]

    def test_no_diff_means_full_evaluation(self):
        """diff.json 缺失 / 空 dict（首次 sync）→ 全部走完整评估。"""
        from eval_bridge import _select_mcp_registry_short_circuit_entries

        entries = [_make_registry_entry("e1")]
        cache = _FakeCache({"e1": _cached_result("e1")})

        short, remaining = _select_mcp_registry_short_circuit_entries(entries, cache, {})

        assert short == {}
        assert remaining == entries

    def test_merged_winner_with_status_field_does_not_short_circuit(self):
        """codex review §8 finding #2：merge 后 winner.id (GitHub) 与 registry diff
        中的 registry id 不对应，故这类 entry 不进入 mcp_registry 短路路径，统一
        走完整评估，避免在 status_changed 场景下误复用旧评分。
        """
        from eval_bridge import _select_mcp_registry_short_circuit_entries

        merged = {
            "id": "winner-id",
            "type": "mcp",
            "source": "awesome-mcp-servers",
            "source_url": "https://github.com/foo/bar",
            "mcp_registry_status": "active",
        }
        diff = {"added": [], "removed": [], "status_changed": [], "version_bumped": []}
        cache = _FakeCache({"winner-id": _cached_result("winner-id")})

        short, remaining = _select_mcp_registry_short_circuit_entries(
            [merged], cache, diff
        )

        assert short == {}
        assert remaining == [merged]


# ---------------------------------------------------------------------------
# windsurfrules 派生判定
# ---------------------------------------------------------------------------


class TestWindsurfrulesDerived:
    def test_source_match(self):
        from eval_bridge import _is_windsurfrules_derived

        assert _is_windsurfrules_derived({"source": "awesome-windsurfrules"})

    def test_source_url_schneidersam(self):
        from eval_bridge import _is_windsurfrules_derived

        assert _is_windsurfrules_derived(
            {
                "source": "other",
                "source_url": (
                    "https://github.com/SchneiderSam/awesome-windsurfrules/blob/main/"
                    "rules/global_rules/python/global_rules.md"
                ),
            }
        )

    def test_source_url_balqaasem(self):
        from eval_bridge import _is_windsurfrules_derived

        assert _is_windsurfrules_derived(
            {
                "source": "other",
                "source_url": (
                    "https://github.com/balqaasem/awesome-windsurfrules/blob/main/"
                    "rules/foo/.windsurfrules"
                ),
            }
        )

    def test_non_match(self):
        from eval_bridge import _is_windsurfrules_derived

        assert not _is_windsurfrules_derived(
            {"source": "awesome-cursorrules", "source_url": "https://github.com/x/y"}
        )
        assert not _is_windsurfrules_derived({})


# ---------------------------------------------------------------------------
# windsurfrules 短路集成
# ---------------------------------------------------------------------------


def _make_windsurfrules_entry(eid: str, slug: str = "schneidersam") -> dict:
    repo = {
        "schneidersam": "SchneiderSam/awesome-windsurfrules",
        "balqaasem": "balqaasem/awesome-windsurfrules",
    }[slug]
    return {
        "id": eid,
        "name": eid,
        "type": "rule",
        "description": "Windsurf rules entry",
        "source_url": f"https://github.com/{repo}/blob/main/rules/{eid}/.windsurfrules",
        "source": "awesome-windsurfrules",
    }


class TestWindsurfrulesShortCircuit:
    """codex review §8 finding #1: windsurfrules 短路被保守禁用。

    sync_windsurfrules 没有维护 diff 文件，_lookup_cached_result 会按
    entry_id+rubric_version 命中"任意历史 content_hash"的旧 row，可能在上游
    README 变更时复用 stale eval。规模又小（~108 条），全量重评成本极低。
    """

    def test_cache_hit_does_not_short_circuit(self):
        from eval_bridge import _select_windsurfrules_short_circuit_entries

        entries = [
            _make_windsurfrules_entry("e1", "schneidersam"),
            _make_windsurfrules_entry("e2", "balqaasem"),
        ]
        cache = _FakeCache({"e1": _cached_result("e1"), "e2": _cached_result("e2")})

        short, remaining = _select_windsurfrules_short_circuit_entries(entries, cache)

        assert short == {}
        assert remaining == entries

    def test_cache_miss_skips_short_circuit(self):
        from eval_bridge import _select_windsurfrules_short_circuit_entries

        entries = [_make_windsurfrules_entry("uncached")]
        cache = _FakeCache({})

        short, remaining = _select_windsurfrules_short_circuit_entries(entries, cache)

        assert short == {}
        assert remaining == entries

    def test_non_windsurfrules_entry_pass_through(self):
        from eval_bridge import _select_windsurfrules_short_circuit_entries

        non_ws = {
            "id": "x",
            "type": "rule",
            "source": "awesome-cursorrules",
            "source_url": "https://github.com/PatrickJS/awesome-cursorrules",
        }
        cache = _FakeCache({"x": _cached_result("x")})

        short, remaining = _select_windsurfrules_short_circuit_entries([non_ws], cache)

        assert short == {}
        assert remaining == [non_ws]


# ---------------------------------------------------------------------------
# rubric_version 不变性 — 保证 mcp_server / rule task config 仍可加载且
# 计算出非空 rubric_version（任务 8.2）
# ---------------------------------------------------------------------------


class TestRubricVersionStable:
    @pytest.mark.parametrize("task_name", ["mcp_server", "rule"])
    def test_rubric_version_present_for_task(self, task_name):
        from eval_bridge import _compute_rubric_version_for_task

        rv = _compute_rubric_version_for_task(task_name)
        # 计算成功 → 非空字符串；ai-resource-eval 未安装时返回 None（仍可接受）
        if rv is None:
            pytest.skip("ai-resource-eval not installed; rubric_version unavailable")
        assert isinstance(rv, str) and rv, (
            f"rubric_version for {task_name} must be non-empty str, got {rv!r}"
        )
        # 形态：``<major>.<sha8>``
        assert "." in rv, f"rubric_version expected '<major>.<sha8>', got {rv!r}"

    def test_mcp_and_rule_task_configs_loadable(self):
        try:
            from ai_resource_eval.tasks.loader import load_task_config
        except ImportError:
            pytest.skip("ai-resource-eval not installed")

        for name in ("mcp_server", "rule"):
            cfg = load_task_config(name)
            assert cfg is not None
            # rubric_major_version 必须存在（int）
            assert isinstance(cfg.rubric_major_version, int)
            assert cfg.rubric_major_version >= 1


# ---------------------------------------------------------------------------
# run_eval 端到端：mcp_registry 与 windsurfrules 短路与 skills.sh 不冲突
# ---------------------------------------------------------------------------


class TestRunEvalIntegration:
    def test_mcp_registry_short_circuit_via_run_eval(self, tmp_path, monkeypatch):
        """整条 run_eval 流程：注入 mcp_registry diff + cache，全短路、不构造 judge。"""
        import eval_bridge

        try:
            from ai_resource_eval.cache import CacheEntry, EvalCache
        except ImportError:
            pytest.skip("ai-resource-eval not installed")

        rv = eval_bridge._compute_rubric_version_for_task("mcp_server")
        if rv is None:
            pytest.skip("rubric_version unavailable")

        cache_dir = tmp_path / ".eval_cache"
        cache_dir.mkdir()
        cache = EvalCache(db_path=cache_dir / "eval_cache.db")
        for eid in ("r1", "r2"):
            key = EvalCache.make_key("__full__", f"hash-{eid}", rv)
            cache.put(
                key,
                CacheEntry(
                    cache_key=key,
                    entry_id=eid,
                    content_hash=f"hash-{eid}",
                    rubric_version=rv,
                    result_json=json.dumps(_cached_result(eid)),
                    evaluated_at="2026-04-01T00:00:00+00:00",
                    expires_at="2099-01-01T00:00:00+00:00",
                ),
            )
        cache.close()

        diff_path = tmp_path / "mcp_registry_diff.json"
        diff_path.write_text(
            json.dumps(
                {
                    "added": [],
                    "removed": [],
                    "status_changed": [],
                    "version_bumped": [],
                    "stable": 2,
                }
            )
        )

        entries = [_make_registry_entry("r1"), _make_registry_entry("r2")]

        build_calls = []
        original = eval_bridge._build_judge

        def _spy():
            build_calls.append(1)
            return original()

        monkeypatch.setattr(eval_bridge, "_build_judge", _spy)

        results = eval_bridge.run_eval(
            entries,
            cache_dir=str(cache_dir),
            incremental=True,
            mcp_registry_diff_path=diff_path,
        )

        assert set(results.keys()) == {"r1", "r2"}
        assert build_calls == [], "全短路下不应初始化 judge"
        for r in results.values():
            assert r["model_id"] == "__cached__"

    def test_windsurfrules_does_not_short_circuit_via_run_eval(self, tmp_path, monkeypatch):
        """codex review §8 finding #1：windsurfrules 短路被保守禁用，
        即便 cache 命中也走完整评估（避免 stale content_hash 复用）。"""
        import eval_bridge

        try:
            from ai_resource_eval.cache import CacheEntry, EvalCache
        except ImportError:
            pytest.skip("ai-resource-eval not installed")

        rv = eval_bridge._compute_rubric_version_for_task("rule")
        if rv is None:
            pytest.skip("rubric_version unavailable")

        cache_dir = tmp_path / ".eval_cache"
        cache_dir.mkdir()
        cache = EvalCache(db_path=cache_dir / "eval_cache.db")
        for eid in ("w1",):
            key = EvalCache.make_key("__full__", f"hash-{eid}", rv)
            cache.put(
                key,
                CacheEntry(
                    cache_key=key,
                    entry_id=eid,
                    content_hash=f"hash-{eid}",
                    rubric_version=rv,
                    result_json=json.dumps(_cached_result(eid)),
                    evaluated_at="2026-04-01T00:00:00+00:00",
                    expires_at="2099-01-01T00:00:00+00:00",
                ),
            )
        cache.close()

        entries = [_make_windsurfrules_entry("w1", "schneidersam")]

        results = eval_bridge.run_eval(
            entries,
            cache_dir=str(cache_dir),
            incremental=True,
        )

        # 没有 LLM_API_KEY，run_eval 会跳过评估返回空 dict，但关键是 windsurfrules
        # 不通过短路路径返回 cached 结果。
        assert "w1" not in results, "windsurfrules 不应被短路命中复用旧 eval"
