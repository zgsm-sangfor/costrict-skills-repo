"""install_popularity 信号测试

覆盖：
1. 公式正确性（log10 标度）
2. HealthSignals 模型字段
3. loader 注入信号 + env var 权重覆盖
4. 默认权重 0 → final_score 不变（核心 invariant）
"""

from __future__ import annotations

import math
import os
from unittest.mock import patch

import pytest

from ai_resource_eval.api.types import (
    EvalItem,
    HealthSignals,
    HeuristicSignalWeight,
)
from ai_resource_eval.runner import EvalRunner
from ai_resource_eval.scoring.governor import ScoringGovernor
from ai_resource_eval.tasks.loader import (
    _resolve_install_popularity_weight,
    load_task_config,
)


# ===================================================================
# 公式：min(100, log10(max(install_count, 1)) / log10(100000) * 100)
# ===================================================================


class TestComputeInstallPopularityFormula:
    """compute_install_popularity 公式核心边界与典型值"""

    @pytest.mark.parametrize(
        "install_count, expected",
        [
            (0, 0.0),  # 缺失/零 → 0
            (None, 0.0),
            (1, 0.0),  # log10(1) = 0
            (10, 20.0),  # log10(10)/log10(100000) * 100 = 1/5 * 100
            (100, 40.0),  # log10(100)/log10(100000) * 100 = 2/5 * 100
            (1000, 60.0),  # 3/5 * 100
            (10000, 80.0),  # 4/5 * 100
            (100000, 100.0),  # 5/5 * 100
            (1000000, 100.0),  # 上界 clamp 到 100
        ],
    )
    def test_formula_values(self, install_count, expected):
        entry = EvalItem(
            id="t1",
            name="t",
            install_count=install_count,
        )
        score = EvalRunner._compute_install_popularity(entry)
        assert score == pytest.approx(expected, abs=0.01)

    def test_no_install_count_attribute(self):
        """EvalItem 完全不指定 install_count → 默认 None → 0 分"""
        entry = EvalItem(id="t1", name="t")
        assert EvalRunner._compute_install_popularity(entry) == 0.0


# ===================================================================
# HealthSignals 模型字段
# ===================================================================


class TestHealthSignalsField:
    """install_popularity 字段在 HealthSignals 上正确设置"""

    def test_default_zero(self):
        h = HealthSignals()
        assert h.install_popularity == 0.0

    def test_explicit_value(self):
        h = HealthSignals(install_popularity=80.0)
        assert h.install_popularity == 80.0

    def test_clamp_range(self):
        with pytest.raises(ValueError):
            HealthSignals(install_popularity=-1)
        with pytest.raises(ValueError):
            HealthSignals(install_popularity=101)


# ===================================================================
# loader 注入：默认权重 0、env var 覆盖、信号自动注入
# ===================================================================


class TestLoaderInjection:
    """env var HEALTH_W_INSTALL_POPULARITY 控制信号权重注入"""

    def test_default_weight_is_005(self):
        """默认权重从 0 改为 0.05：让 install_count 高的 skills.sh entry 救场。"""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("HEALTH_W_INSTALL_POPULARITY", None)
            assert _resolve_install_popularity_weight() == 0.05

    def test_env_override_valid(self):
        with patch.dict(os.environ, {"HEALTH_W_INSTALL_POPULARITY": "0.25"}):
            assert _resolve_install_popularity_weight() == 0.25

    def test_env_override_invalid_falls_back(self):
        with patch.dict(os.environ, {"HEALTH_W_INSTALL_POPULARITY": "garbage"}):
            assert _resolve_install_popularity_weight() == 0.05

    def test_env_override_out_of_range_falls_back(self):
        with patch.dict(os.environ, {"HEALTH_W_INSTALL_POPULARITY": "1.5"}):
            assert _resolve_install_popularity_weight() == 0.05

    def test_skill_task_has_install_popularity_signal(self):
        """skill task 加载后应包含 install_popularity 信号（权重默认 0.05）"""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("HEALTH_W_INSTALL_POPULARITY", None)
            cfg = load_task_config("skill")
        sig_names = [s.signal for s in cfg.heuristic_signals]
        assert "install_popularity" in sig_names
        ip = next(s for s in cfg.heuristic_signals if s.signal == "install_popularity")
        assert ip.weight == pytest.approx(0.05, abs=0.001)
        # 其它信号按比例缩减，使「非零信号权重和」仍为 1.0
        non_zero_sum = sum(s.weight for s in cfg.heuristic_signals if s.weight > 0)
        assert non_zero_sum == pytest.approx(1.0, abs=0.001)

    def test_env_override_rescales_other_signals(self):
        """非零权重时其它信号按比例缩减，保持非零信号和 = 1.0"""
        with patch.dict(os.environ, {"HEALTH_W_INSTALL_POPULARITY": "0.20"}):
            cfg = load_task_config("skill")
        non_zero_sum = sum(s.weight for s in cfg.heuristic_signals if s.weight > 0)
        assert non_zero_sum == pytest.approx(1.0, abs=0.001)
        ip = next(s for s in cfg.heuristic_signals if s.signal == "install_popularity")
        assert ip.weight == pytest.approx(0.20, abs=0.001)


# ===================================================================
# 核心 invariant：默认权重 0.05 时仅 skills.sh entry 受影响
# (excluded path：无 install_count 的 entry 自动剔除该信号 → 结果不变)
# ===================================================================


class TestFinalScoreInvariantUnderDefault:
    """默认权重 0.05：non-skills.sh entry 走 excluded path → 结果与权重 0 时等价。
    skills.sh entry（install_count > 0）→ install_popularity 参与 health_score。
    """

    def test_health_score_unchanged_for_non_skills_sh_entry(self):
        """non-skills.sh entry（无 install_count）→ excluded → 等价于不含此信号。

        即便默认权重升到 0.05，excluded_signals 机制保证原 freshness/popularity/
        source_trust 按比例分回原权重，最终 health_score 不变。
        """
        signals = HealthSignals(
            freshness=80.0,
            popularity=60.0,
            source_trust=90.0,
            install_popularity=0.0,  # 无 install_count → 信号本身就为 0
        )

        # 旧版配置（不含 install_popularity）
        weights_old = [
            HeuristicSignalWeight(signal="freshness", weight=0.30),
            HeuristicSignalWeight(signal="popularity", weight=0.30),
            HeuristicSignalWeight(signal="source_trust", weight=0.40),
        ]
        score_old = ScoringGovernor.compute_health_score(signals, weights_old)

        # 新版配置（默认权重 0.05，原信号按比例缩减到 0.95 总和）
        weights_new = [
            HeuristicSignalWeight(signal="freshness", weight=0.30 * 0.95),
            HeuristicSignalWeight(signal="popularity", weight=0.30 * 0.95),
            HeuristicSignalWeight(signal="source_trust", weight=0.40 * 0.95),
            HeuristicSignalWeight(signal="install_popularity", weight=0.05),
        ]
        # 模拟 runner 的 excluded 路径：non-skills.sh entry 自动 exclude
        score_new = ScoringGovernor.compute_health_score(
            signals, weights_new, excluded_signals={"install_popularity"}
        )

        # 核心 invariant：excluded 后结果与旧版完全相等
        assert score_new == pytest.approx(score_old, abs=0.01)
        assert score_new == pytest.approx(78.0, abs=0.01)

    def test_health_score_boosted_for_skills_sh_entry(self):
        """skills.sh entry（高 install_count）→ install_popularity 参与加权 → 救场。"""
        # 模拟 install_count = 50000 的 skills.sh entry：log10(50000)/log10(100000)*100 ≈ 93.95
        signals = HealthSignals(
            freshness=50.0,
            popularity=40.0,
            source_trust=60.0,
            install_popularity=93.95,
        )
        weights = [
            HeuristicSignalWeight(signal="freshness", weight=0.30 * 0.95),
            HeuristicSignalWeight(signal="popularity", weight=0.30 * 0.95),
            HeuristicSignalWeight(signal="source_trust", weight=0.40 * 0.95),
            HeuristicSignalWeight(signal="install_popularity", weight=0.05),
        ]
        score = ScoringGovernor.compute_health_score(signals, weights)
        # 等价：(50*0.285 + 40*0.285 + 60*0.38 + 93.95*0.05) = 14.25 + 11.4 + 22.8 + 4.6975 ≈ 53.15
        # 旧权重 0 下：50*0.30 + 40*0.30 + 60*0.40 = 51.0
        # 加分 ≈ 2.15 分（相对救场效果显现）
        assert score > 51.0
        assert score == pytest.approx(53.15, abs=0.05)

    def test_install_popularity_changes_score_when_weight_nonzero(self):
        """权重非零时确实参与加权（提供 baseline 用于未来调权）"""
        signals = HealthSignals(
            freshness=0.0,
            popularity=0.0,
            source_trust=0.0,
            install_popularity=100.0,
        )
        weights = [
            HeuristicSignalWeight(signal="freshness", weight=0.20),
            HeuristicSignalWeight(signal="popularity", weight=0.20),
            HeuristicSignalWeight(signal="source_trust", weight=0.40),
            HeuristicSignalWeight(signal="install_popularity", weight=0.20),
        ]
        score = ScoringGovernor.compute_health_score(signals, weights)
        # 仅 install_popularity 有值，它的贡献 = 100 * 0.20 = 20
        assert score == pytest.approx(20.0, abs=0.01)


class TestInstallPopularityExcludedWhenMissing:
    """P2 修复：entry 无 install_count 时，install_popularity 应被剔除并重分配权重，
    避免拉低混合分。"""

    def test_excluded_when_install_count_none(self):
        """entry.install_count = None → install_popularity 进入 excluded 集合"""
        entry = EvalItem(
            id="x",
            name="x",
            type="skill",
            install_count=None,
        )
        excluded = EvalRunner._get_excluded_signals(entry, star_weight=1.0)
        assert "install_popularity" in excluded

    def test_excluded_when_install_count_zero(self):
        entry = EvalItem(id="x", name="x", type="skill", install_count=0)
        excluded = EvalRunner._get_excluded_signals(entry, star_weight=1.0)
        assert "install_popularity" in excluded

    def test_not_excluded_when_install_count_positive(self):
        entry = EvalItem(id="x", name="x", type="skill", install_count=5000)
        excluded = EvalRunner._get_excluded_signals(entry, star_weight=1.0)
        assert "install_popularity" not in excluded

    def test_excluded_weight_redistributed_to_others(self):
        """缺失 install_count 时，原权重按比例分回 freshness / popularity / source_trust。"""
        signals = HealthSignals(
            freshness=80.0,
            popularity=60.0,
            source_trust=90.0,
            install_popularity=0.0,  # 实际不会用到
        )
        # 模拟非零 install_popularity 权重的配置
        weights = [
            HeuristicSignalWeight(signal="freshness", weight=0.30),
            HeuristicSignalWeight(signal="popularity", weight=0.30),
            HeuristicSignalWeight(signal="source_trust", weight=0.30),
            HeuristicSignalWeight(signal="install_popularity", weight=0.10),
        ]
        score_excluded = ScoringGovernor.compute_health_score(
            signals, weights, excluded_signals={"install_popularity"}
        )
        # 等价于：把 0.10 按比例分给前三者（各 +0.10 * 1/3 ≈ 0.0333）
        # 总分 ≈ 80*0.3333 + 60*0.3333 + 90*0.3333 = 76.67
        expected = (80 + 60 + 90) / 3
        assert score_excluded == pytest.approx(expected, abs=0.01)
