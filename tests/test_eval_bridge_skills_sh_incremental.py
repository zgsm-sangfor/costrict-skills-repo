"""Section 6 增量评估短路：skills.sh 源条目复用 cache 的判定与流程。

测试目标：
- _install_count_drift_within 阈值判定（边界 / 缺失）
- load_skills_sh_diff 解析 diff.json
- _diff_unstable_ids 提取不稳定 id 集合
- _select_short_circuit_entries 在 stable + cache 命中时短路
- run_eval 在全短路场景下不调用 judge / runner（零 LLM 调用）
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))


def _make_skills_sh_entry(eid: str, install_count: int = 5000) -> dict:
    return {
        "id": eid,
        "name": eid,
        "type": "skill",
        "description": "Skill from skills.sh",
        "source_url": f"https://github.com/owner/{eid}#skill={eid}",
        "source": "skills-sh",
        "install_count": install_count,
    }


def _make_diff(added=None, changed=None, removed=None, stable=0) -> dict:
    return {
        "added": list(added or []),
        "changed_install_count": [
            {"id": cid, "old": 1000, "new": 5000, "pct": 4.0} for cid in (changed or [])
        ],
        "removed": list(removed or []),
        "stable": stable,
    }


def _make_cached_result(entry_id: str) -> dict:
    """构造 cache 中存储的 result_json（最小可解析）。"""
    return {
        "entry_id": entry_id,
        "metrics": {},
        "enrichment": None,
        "health": {
            "freshness": 80.0,
            "popularity": 50.0,
            "source_trust": 70.0,
            "install_popularity": 0.0,
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
# 单元测试：阈值与 diff 解析
# ---------------------------------------------------------------------------


class TestInstallCountDrift:
    def test_within_threshold(self):
        from eval_bridge import _install_count_drift_within

        # +20% 边界
        assert _install_count_drift_within(1000, 1200) is True
        assert _install_count_drift_within(1000, 800) is True
        # 同值
        assert _install_count_drift_within(5000, 5000) is True

    def test_outside_threshold(self):
        from eval_bridge import _install_count_drift_within

        assert _install_count_drift_within(1000, 1500) is False  # +50%
        assert _install_count_drift_within(1000, 700) is False  # -30%

    def test_missing_or_zero(self):
        from eval_bridge import _install_count_drift_within

        assert _install_count_drift_within(None, 1000) is False
        assert _install_count_drift_within(1000, None) is False
        assert _install_count_drift_within(0, 1000) is False
        assert _install_count_drift_within(1000, 0) is False

    def test_invalid_types(self):
        from eval_bridge import _install_count_drift_within

        assert _install_count_drift_within("abc", 1000) is False
        assert _install_count_drift_within(1000, "xyz") is False


class TestLoadDiff:
    def test_loads_valid_diff(self, tmp_path):
        from eval_bridge import load_skills_sh_diff

        path = tmp_path / "diff.json"
        diff = _make_diff(added=["a"], changed=["b"], removed=["c"], stable=10)
        path.write_text(json.dumps(diff))

        loaded = load_skills_sh_diff(path)
        assert loaded["added"] == ["a"]
        assert loaded["removed"] == ["c"]

    def test_missing_returns_empty(self, tmp_path):
        from eval_bridge import load_skills_sh_diff

        loaded = load_skills_sh_diff(tmp_path / "nonexistent.json")
        assert loaded == {}

    def test_corrupt_returns_empty(self, tmp_path):
        from eval_bridge import load_skills_sh_diff

        path = tmp_path / "bad.json"
        path.write_text("{not json")

        loaded = load_skills_sh_diff(path)
        assert loaded == {}


class TestUnstableIds:
    def test_collects_added_changed_removed(self):
        from eval_bridge import _diff_unstable_ids

        diff = _make_diff(added=["a", "b"], changed=["c"], removed=["d"])
        ids = _diff_unstable_ids(diff)
        assert ids == {"a", "b", "c", "d"}

    def test_empty_diff(self):
        from eval_bridge import _diff_unstable_ids

        assert _diff_unstable_ids({}) == set()


# ---------------------------------------------------------------------------
# 集成：_select_short_circuit_entries
# ---------------------------------------------------------------------------


class _FakeCache:
    """模拟 EvalCache：内部用 dict 存 entry_id → result。"""

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
        if self._data is None:
            return None
        return self._data


class TestShortCircuitSelection:
    def test_skills_sh_stable_with_cache_hits_short_circuit(self):
        from eval_bridge import _select_short_circuit_entries

        entries = [
            _make_skills_sh_entry("e1"),
            _make_skills_sh_entry("e2"),
        ]
        diff = _make_diff(added=[], changed=[], removed=[], stable=2)
        cache = _FakeCache({"e1": _make_cached_result("e1"), "e2": _make_cached_result("e2")})

        short, remaining = _select_short_circuit_entries(entries, cache, diff)

        assert set(short.keys()) == {"e1", "e2"}
        assert short["e1"]["model_id"] == "__cached__"
        assert remaining == []

    def test_skills_sh_changed_skip_short_circuit(self):
        from eval_bridge import _select_short_circuit_entries

        entries = [
            _make_skills_sh_entry("changed-id"),
            _make_skills_sh_entry("stable-id"),
        ]
        diff = _make_diff(changed=["changed-id"])
        cache = _FakeCache(
            {
                "changed-id": _make_cached_result("changed-id"),
                "stable-id": _make_cached_result("stable-id"),
            }
        )

        short, remaining = _select_short_circuit_entries(entries, cache, diff)

        assert "stable-id" in short
        assert "changed-id" not in short
        assert any(e["id"] == "changed-id" for e in remaining)

    def test_no_cache_entry_skip_short_circuit(self):
        from eval_bridge import _select_short_circuit_entries

        entries = [_make_skills_sh_entry("uncached")]
        diff = _make_diff(stable=1)
        cache = _FakeCache({})  # cache miss

        short, remaining = _select_short_circuit_entries(entries, cache, diff)

        assert short == {}
        assert remaining == entries

    def test_non_skills_sh_entry_not_short_circuited(self):
        from eval_bridge import _select_short_circuit_entries

        non_skills_sh = {
            "id": "anth-1",
            "name": "Other",
            "type": "skill",
            "source": "anthropics-skills",
        }
        diff = _make_diff(stable=1)
        cache = _FakeCache({"anth-1": _make_cached_result("anth-1")})

        short, remaining = _select_short_circuit_entries([non_skills_sh], cache, diff)

        assert short == {}
        assert remaining == [non_skills_sh]

    def test_no_diff_means_full_evaluation(self):
        """diff.json 缺失 / 空 dict（首次 sync）→ 全部走完整评估。"""
        from eval_bridge import _select_short_circuit_entries

        entries = [_make_skills_sh_entry("e1")]
        cache = _FakeCache({"e1": _make_cached_result("e1")})

        short, remaining = _select_short_circuit_entries(entries, cache, {})

        assert short == {}
        assert remaining == entries


# ---------------------------------------------------------------------------
# 端到端：run_eval 在全短路场景下不触发 LLM
# ---------------------------------------------------------------------------


def _current_rubric_version(task_name: str = "skill") -> str:
    """复算 eval_bridge 当前算出的 rubric_version。

    P1 修复后短路必须按 rubric_version 命中 cache；测试 fixture 写入的 row
    需要使用同一版本号才能被复用。"""
    from eval_bridge import _compute_rubric_version_for_task

    return _compute_rubric_version_for_task(task_name)


class TestRunEvalShortCircuit:
    def test_full_short_circuit_skips_judge_init(self, tmp_path, monkeypatch):
        """两次 sync 场景：第二次跑 run_eval 时全部命中 cache，不调用 _build_judge。"""
        import eval_bridge

        # Step 1: 准备真实 SQLite cache，预先写入两条 result（模拟首次评估完成）
        # rubric_version 必须用当前实际版本号，否则 P1 修复后短路按版本过滤会 miss
        rv = _current_rubric_version("skill")
        cache_dir = tmp_path / ".eval_cache"
        cache_dir.mkdir()
        from ai_resource_eval.cache import CacheEntry, EvalCache

        cache = EvalCache(db_path=cache_dir / "eval_cache.db")
        for eid in ("e1", "e2"):
            key = EvalCache.make_key("__full__", f"hash-{eid}", rv)
            cache.put(
                key,
                CacheEntry(
                    cache_key=key,
                    entry_id=eid,
                    content_hash=f"hash-{eid}",
                    rubric_version=rv,
                    result_json=json.dumps(_make_cached_result(eid)),
                    evaluated_at="2026-04-01T00:00:00+00:00",
                    expires_at="2099-01-01T00:00:00+00:00",
                ),
            )
        cache.close()

        # Step 2: 准备 diff.json，标记 e1、e2 为 stable
        diff_path = tmp_path / "diff.json"
        diff_path.write_text(json.dumps(_make_diff(stable=2)))

        # Step 3: 跑 run_eval；计 _build_judge 调用数
        entries = [_make_skills_sh_entry("e1"), _make_skills_sh_entry("e2")]
        build_judge_calls = []
        original = eval_bridge._build_judge

        def _spy():
            build_judge_calls.append(1)
            return original()

        monkeypatch.setattr(eval_bridge, "_build_judge", _spy)

        results = eval_bridge.run_eval(
            entries,
            cache_dir=str(cache_dir),
            incremental=True,
            skills_sh_diff_path=diff_path,
        )

        # 全短路：results 含两条，judge 未被构造
        assert set(results.keys()) == {"e1", "e2"}
        assert build_judge_calls == [], "全短路场景下不应初始化 judge"
        for r in results.values():
            assert r["model_id"] == "__cached__"

    def test_partial_short_circuit_only_unstable_evaluated(self, tmp_path, monkeypatch):
        """部分短路：stable 走 cache、changed 进 runner；runner.run 只看到 1 条。"""
        import eval_bridge

        rv = _current_rubric_version("skill")
        cache_dir = tmp_path / ".eval_cache"
        cache_dir.mkdir()
        from ai_resource_eval.cache import CacheEntry, EvalCache

        cache = EvalCache(db_path=cache_dir / "eval_cache.db")
        for eid in ("stable", "changed"):
            cache.put(
                EvalCache.make_key("__full__", f"hash-{eid}", rv),
                CacheEntry(
                    cache_key=EvalCache.make_key("__full__", f"hash-{eid}", rv),
                    entry_id=eid,
                    content_hash=f"hash-{eid}",
                    rubric_version=rv,
                    result_json=json.dumps(_make_cached_result(eid)),
                    evaluated_at="2026-04-01T00:00:00+00:00",
                    expires_at="2099-01-01T00:00:00+00:00",
                ),
            )
        cache.close()

        diff_path = tmp_path / "diff.json"
        diff_path.write_text(json.dumps(_make_diff(changed=["changed"], stable=1)))

        entries = [_make_skills_sh_entry("stable"), _make_skills_sh_entry("changed")]

        # 模拟无 LLM key 环境：_build_judge 返回 None；runner 不会被调用
        monkeypatch.setattr(eval_bridge, "_build_judge", lambda: None)

        results = eval_bridge.run_eval(
            entries,
            cache_dir=str(cache_dir),
            incremental=True,
            skills_sh_diff_path=diff_path,
        )

        # 短路命中 stable；changed 进入 runner 流程但 judge 缺失被跳过
        assert "stable" in results
        assert results["stable"]["model_id"] == "__cached__"
        assert "changed" not in results


# ---------------------------------------------------------------------------
# P1 修复回归：rubric_version 升级后短路必须不复用旧 row
# ---------------------------------------------------------------------------


class TestRubricVersionInvalidation:
    """P1：rubric v1→v2 升级后，cache 中残留的 v1 row 不应被短路误用。"""

    def test_rubric_mismatch_misses_cache(self, tmp_path, monkeypatch):
        """cache 中只有旧 rubric_version 的 row，新 rubric 下短路应 miss。"""
        import eval_bridge

        cache_dir = tmp_path / ".eval_cache"
        cache_dir.mkdir()
        from ai_resource_eval.cache import CacheEntry, EvalCache

        # 写入「旧 rubric」row（模拟 v1 cache）
        old_rv = "1.deadbeef"
        cache = EvalCache(db_path=cache_dir / "eval_cache.db")
        for eid in ("e1",):
            key = EvalCache.make_key("__full__", f"hash-{eid}", old_rv)
            cache.put(
                key,
                CacheEntry(
                    cache_key=key,
                    entry_id=eid,
                    content_hash=f"hash-{eid}",
                    rubric_version=old_rv,
                    result_json=json.dumps(_make_cached_result(eid)),
                    evaluated_at="2026-04-01T00:00:00+00:00",
                    expires_at="2099-01-01T00:00:00+00:00",
                ),
            )
        cache.close()

        diff_path = tmp_path / "diff.json"
        diff_path.write_text(json.dumps(_make_diff(stable=1)))

        entries = [_make_skills_sh_entry("e1")]
        # 无 LLM key：runner 会被尝试调用（短路 miss）但 judge=None 直接返回空
        monkeypatch.setattr(eval_bridge, "_build_judge", lambda: None)

        results = eval_bridge.run_eval(
            entries,
            cache_dir=str(cache_dir),
            incremental=True,
            skills_sh_diff_path=diff_path,
        )

        # 期望：短路 miss（rubric 不匹配），结果为空 / 没有 e1
        assert "e1" not in results, (
            "rubric_version 升级后，短路必须按版本过滤，不能复用旧 cache row"
        )

    def test_lookup_with_rubric_filters_old_rows(self, tmp_path):
        """直接验证 _lookup_cached_result 按 rubric_version 过滤。"""
        from eval_bridge import _lookup_cached_result
        from ai_resource_eval.cache import CacheEntry, EvalCache

        cache_dir = tmp_path / ".eval_cache"
        cache_dir.mkdir()
        cache = EvalCache(db_path=cache_dir / "eval_cache.db")
        old_rv, new_rv = "1.aaa", "1.bbb"
        # 写入旧版本 row
        key_old = EvalCache.make_key("__full__", "hash-e1", old_rv)
        cache.put(
            key_old,
            CacheEntry(
                cache_key=key_old,
                entry_id="e1",
                content_hash="hash-e1",
                rubric_version=old_rv,
                result_json=json.dumps(_make_cached_result("e1")),
                evaluated_at="2026-04-01T00:00:00+00:00",
                expires_at="2099-01-01T00:00:00+00:00",
            ),
        )

        # 用新版本查询：应 miss
        assert _lookup_cached_result(cache, "e1", rubric_version=new_rv) is None
        # 用旧版本查询：应命中
        result = _lookup_cached_result(cache, "e1", rubric_version=old_rv)
        assert result is not None
        assert result["model_id"] == "__cached__"


# ---------------------------------------------------------------------------
# P2-1 修复回归：merged entry 通过 skills_sh_url 反推 raw id 命中 diff
# ---------------------------------------------------------------------------


class TestMergedEntryShortCircuit:
    """P2-1：merge_index 合并到高优先级 winner 后，winner 的 source/id 已变，
    但 skills_sh_url 仍保留。短路必须用 skills_sh_url 反推 raw id 比对 diff。"""

    def test_skills_sh_raw_id_from_skills_sh_url(self):
        """反推算法与 sync_skills_sh._make_id 同款。"""
        from eval_bridge import _skills_sh_raw_id_from_entry

        entry = {
            "id": "winner-id-from-other-source",
            "source": "anthropics-skills",  # merged 后变了
            "skills_sh_url": "https://skills.sh/anthropics/skills/frontend-design",
        }
        # _make_id("frontend-design", "anthropics", "skills") → "frontend-design-anthropics"
        # （因 repo "skills" 与 sk "frontend-design" 不重复，会附加 repo 段后清洗）
        raw_id = _skills_sh_raw_id_from_entry(entry)
        assert raw_id == "frontend-design-anthropics-skills"

    def test_skills_sh_raw_id_skips_repo_when_equal_to_skill(self):
        """repo 段与 skill 同名时不重复（与 sync_skills_sh 行为一致）。"""
        from eval_bridge import _skills_sh_raw_id_from_entry

        entry = {
            "id": "x",
            "skills_sh_url": "https://skills.sh/foo/skills/skills",
        }
        # sk="skills", ow="foo", rp="skills" → 但 rp == sk 跳过 → "skills-foo"
        assert _skills_sh_raw_id_from_entry(entry) == "skills-foo"

    def test_skills_sh_raw_id_returns_none_for_non_skills_sh(self):
        from eval_bridge import _skills_sh_raw_id_from_entry

        assert _skills_sh_raw_id_from_entry({"id": "x"}) is None
        assert (
            _skills_sh_raw_id_from_entry({"id": "x", "skills_sh_url": ""}) is None
        )
        assert (
            _skills_sh_raw_id_from_entry(
                {"id": "x", "skills_sh_url": "https://github.com/foo/bar"}
            )
            is None
        )

    def test_merged_entry_uses_skills_sh_url_for_diff_lookup(self):
        """merged winner（source 不再是 skills-sh）也能短路：用 skills_sh_url 反推 raw id 比对 diff。"""
        from eval_bridge import _select_short_circuit_entries

        # winner entry：source 已变成 anthropics-skills，但 skills_sh_url 保留
        merged_entry = {
            "id": "frontend-design-from-anth-mirror",  # winner 的 catalog id
            "name": "Frontend Design",
            "type": "skill",
            "source": "anthropics-skills",  # 不再是 skills-sh
            "skills_sh_url": "https://skills.sh/anthropics/skills/frontend-design",
        }
        # diff.json 用 raw skills.sh id（与 _make_id 同款）
        diff = _make_diff(
            added=[],
            changed=["frontend-design-anthropics-skills"],  # raw id 标记为 unstable
            stable=0,
        )
        cache = _FakeCache(
            {merged_entry["id"]: _make_cached_result(merged_entry["id"])}
        )

        short, remaining = _select_short_circuit_entries(
            [merged_entry], cache, diff
        )
        # 因 raw id 在 unstable 集合 → 不短路
        assert short == {}
        assert remaining == [merged_entry]

    def test_merged_stable_entry_short_circuits_via_skills_sh_url(self):
        """raw id 是 stable 时，merged entry 也能短路命中。"""
        from eval_bridge import _select_short_circuit_entries

        merged_entry = {
            "id": "winner-catalog-id",
            "name": "X",
            "type": "skill",
            "source": "anthropics-skills",
            "skills_sh_url": "https://skills.sh/anthropics/skills/frontend-design",
        }
        diff = _make_diff(stable=1)  # 没有 unstable
        cache = _FakeCache(
            {merged_entry["id"]: _make_cached_result(merged_entry["id"])}
        )

        short, remaining = _select_short_circuit_entries(
            [merged_entry], cache, diff
        )
        # rubric_version=None → 走 fallback lookup（按 entry_id 取最新），应命中
        assert "winner-catalog-id" in short
        assert remaining == []


# ---------------------------------------------------------------------------
# P2-2 修复回归：workflow yaml 的 skills.sh cache 隔离（仅周失效）
# ---------------------------------------------------------------------------


class TestWorkflowSkillsShCacheIsolation:
    """P2-2：.skills_sh_cache/ 必须独立 cache block，restore-keys 仅含 weekly stamp 前缀。"""

    def test_workflow_yaml_isolates_skills_sh_cache(self):
        """静态校验 sync.yml：
        1. YAML 合法
        2. 存在独立的 skills-sh-cache restore step
        3. restore-keys 仅以 skills-sh-cache-${stamp}- 开头（不含跨周兜底）
        4. 通用 sync-caches- 不再 restore .skills_sh_cache/
        """
        try:
            import yaml  # PyYAML
        except ImportError:
            pytest.skip("PyYAML 不可用")

        repo_root = Path(__file__).resolve().parent.parent
        yml_path = repo_root / ".github" / "workflows" / "sync.yml"
        with open(yml_path, "r", encoding="utf-8") as f:
            wf = yaml.safe_load(f)

        steps = wf["jobs"]["sync"]["steps"]

        # 找 sync-caches restore step：path 不应再含 .skills_sh_cache/
        sync_restore = next(
            s for s in steps
            if s.get("name") == "Restore sync caches"
        )
        assert ".skills_sh_cache/" not in sync_restore["with"]["path"], (
            "sync-caches block 不应再 restore .skills_sh_cache/"
        )

        # 找 skills-sh restore step：必须存在，restore-keys 仅含 weekly stamp
        skills_sh_restore = next(
            (s for s in steps if s.get("name") == "Restore skills.sh weekly cache"),
            None,
        )
        assert skills_sh_restore is not None, "缺少独立的 skills.sh weekly cache restore step"
        assert ".skills_sh_cache/" in skills_sh_restore["with"]["path"]
        rk = skills_sh_restore["with"]["restore-keys"]
        # restore-keys 是字符串（YAML "|" 块）；用 splitlines 拆
        keys = [line.strip() for line in rk.splitlines() if line.strip()]
        # 每行必须以 skills-sh-cache- 开头，不能出现通用 sync-caches- 兜底
        for k in keys:
            assert k.startswith("skills-sh-cache-${{ steps.week.outputs.stamp }}-"), (
                f"skills.sh restore-keys 必须仅含 weekly stamp 前缀，发现：{k}"
            )
            assert "sync-caches-" not in k

        # save step 同样存在且 path 隔离
        skills_sh_save = next(
            (s for s in steps if s.get("name") == "Save skills.sh weekly cache"),
            None,
        )
        assert skills_sh_save is not None
        assert ".skills_sh_cache/" in skills_sh_save["with"]["path"]
