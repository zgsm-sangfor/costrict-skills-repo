"""Tests for the security_scan task: SecurityScanResult model + runner branch."""

from __future__ import annotations

import json
import threading
from typing import Any

import pytest
from pydantic import ValidationError

from ai_resource_eval.api.judge import JudgeResult
from ai_resource_eval.api.types import (
    EvalItem,
    RiskLevel,
    SecurityPermissions,
    SecurityScanResult,
    SecurityVerdict,
    TaskConfig,
)
from ai_resource_eval.judges.base import BaseJudge
from ai_resource_eval.runner import EvalRunner
from ai_resource_eval.tasks.loader import load_task_config


# ---------------------------------------------------------------------------
# SecurityScanResult model
# ---------------------------------------------------------------------------


class TestSecurityScanResultModel:
    """Pydantic validation for SecurityScanResult (incl. verdict↔risk_level)."""

    def _base_kwargs(self) -> dict[str, Any]:
        return dict(
            risk_level="low",
            verdict="safe",
            red_flags=[],
            permissions={"files": [], "network": [], "commands": []},
            summary="纯本地计算，无外部 IO。",
            recommendations=[],
        )

    def test_minimal_low_safe(self):
        r = SecurityScanResult.model_validate(self._base_kwargs())
        assert r.risk_level == RiskLevel.low
        assert r.verdict == SecurityVerdict.safe
        assert r.permissions.files == []

    def test_clean_safe(self):
        kw = self._base_kwargs()
        kw["risk_level"] = "clean"
        kw["verdict"] = "safe"
        r = SecurityScanResult.model_validate(kw)
        assert r.risk_level == RiskLevel.clean

    def test_medium_caution(self):
        kw = self._base_kwargs()
        kw["risk_level"] = "medium"
        kw["verdict"] = "caution"
        kw["summary"] = "调用 OpenAI API 但需要用户 key"
        r = SecurityScanResult.model_validate(kw)
        assert r.verdict == SecurityVerdict.caution

    def test_high_reject(self):
        kw = self._base_kwargs()
        kw["risk_level"] = "high"
        kw["verdict"] = "reject"
        r = SecurityScanResult.model_validate(kw)
        assert r.verdict == SecurityVerdict.reject

    def test_extreme_reject(self):
        kw = self._base_kwargs()
        kw["risk_level"] = "extreme"
        kw["verdict"] = "reject"
        r = SecurityScanResult.model_validate(kw)
        assert r.risk_level == RiskLevel.extreme

    @pytest.mark.parametrize(
        ("risk", "wrong_verdict", "expected_verdict"),
        [
            ("clean", "caution", "safe"),
            ("clean", "reject", "safe"),
            ("low", "caution", "safe"),
            ("low", "reject", "safe"),
            ("medium", "safe", "caution"),
            ("medium", "reject", "caution"),
            ("high", "safe", "reject"),
            ("high", "caution", "reject"),
            ("extreme", "safe", "reject"),
            ("extreme", "caution", "reject"),
        ],
    )
    def test_verdict_risk_mismatch_coerced(
        self,
        risk: str,
        wrong_verdict: str,
        expected_verdict: str,
        caplog: pytest.LogCaptureFixture,
    ):
        """Mismatched verdict is coerced from risk_level (no raise).

        risk_level 是 5 档细粒度信息，作为权威源；verdict 由 _VERDICT_FOR_RISK
        自动推导，避免 LLM 偶尔输出矛盾组合时整条评估被丢弃。
        """
        kw = dict(
            risk_level=risk,
            verdict=wrong_verdict,
            red_flags=[],
            permissions={"files": [], "network": [], "commands": []},
            summary="x",
            recommendations=[],
        )
        with caplog.at_level("WARNING", logger="ai_resource_eval.api.types"):
            r = SecurityScanResult.model_validate(kw)
        assert r.risk_level.value == risk
        assert r.verdict.value == expected_verdict
        assert any("does not match risk_level" in rec.message for rec in caplog.records)

    def test_invalid_risk_enum_rejected(self):
        kw = self._base_kwargs()
        kw["risk_level"] = "critical"  # not in enum
        with pytest.raises(ValidationError):
            SecurityScanResult.model_validate(kw)

    def test_invalid_verdict_enum_rejected(self):
        kw = self._base_kwargs()
        kw["verdict"] = "blocked"  # not in enum
        with pytest.raises(ValidationError):
            SecurityScanResult.model_validate(kw)

    def test_permissions_block_defaults(self):
        r = SecurityScanResult.model_validate(self._base_kwargs())
        assert isinstance(r.permissions, SecurityPermissions)
        assert r.permissions.files == []
        assert r.permissions.network == []
        assert r.permissions.commands == []

    def test_serialization_roundtrip(self):
        kw = dict(
            risk_level="medium",
            verdict="caution",
            red_flags=["调用未授权远程 endpoint"],
            permissions={
                "files": ["~/.aws"],
                "network": ["api.example.com"],
                "commands": ["curl"],
            },
            summary="存在中等风险",
            recommendations=["建议用户审阅 API 调用"],
        )
        r = SecurityScanResult.model_validate(kw)
        dumped = r.model_dump(mode="json")
        r2 = SecurityScanResult.model_validate(dumped)
        assert r == r2


# ---------------------------------------------------------------------------
# TaskConfig.security_scan flag
# ---------------------------------------------------------------------------


class TestSecurityScanTaskConfig:
    """Tests for the new security_scan TaskConfig field + bundled yaml."""

    def test_security_scan_default_false(self):
        cfg = TaskConfig(task="skill", metrics=[{"metric": "coding_relevance", "weight": 1.0}])
        assert cfg.security_scan is False

    def test_security_scan_explicit_true_with_empty_metrics(self):
        cfg = TaskConfig(task="security_scan", security_scan=True, metrics=[])
        assert cfg.security_scan is True
        assert cfg.metrics == []

    def test_bundled_security_scan_yaml_loads(self):
        cfg = load_task_config("security_scan")
        assert cfg.task == "security_scan"
        assert cfg.security_scan is True
        assert cfg.metrics == []
        assert cfg.heuristic_signals == []
        assert cfg.enrichment is False
        assert cfg.mcp_installability is False
        assert cfg.rubric_major_version == 2


# ---------------------------------------------------------------------------
# Runner branch — _eval_one_security
# ---------------------------------------------------------------------------


_VALID_SECURITY_PAYLOAD = {
    "risk_level": "low",
    "verdict": "safe",
    "red_flags": [],
    "permissions": {"files": [], "network": [], "commands": []},
    "summary": "纯本地计算",
    "recommendations": [],
}

_MISMATCHED_SECURITY_PAYLOAD = {
    "risk_level": "high",
    "verdict": "safe",  # mismatch — high must be reject
    "red_flags": ["fake"],
    "permissions": {"files": [], "network": [], "commands": []},
    "summary": "x",
    "recommendations": [],
}


class _FakeSecurityJudge(BaseJudge):
    """A fake judge that returns a configurable security_scan response."""

    def __init__(self, payload: dict[str, Any] | None) -> None:
        self._payload = payload
        self._lock = threading.Lock()
        self.call_count = 0
        self.last_user_prompt: str = ""

    def _call_llm(
        self,
        system_prompt: str,
        user_prompt: str,
        schema: dict[str, Any] | None = None,
    ) -> tuple[str, int, int, int]:
        with self._lock:
            self.call_count += 1
            self.last_user_prompt = user_prompt
        raw = "" if self._payload is None else json.dumps(self._payload)
        return raw, 300, 100, 800

    def _compute_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        return 0.002

    def _model_id(self) -> str:
        return "fake-security-model"


def _make_runner(tmp_path, judge):
    cfg = load_task_config("security_scan")
    return EvalRunner(
        task_config=cfg,
        judge=judge,
        cache_dir=str(tmp_path / ".eval_cache"),
        concurrency=1,
        incremental=False,
        interactive=False,
        on_fail="skip",
    )


def _make_skill_entry() -> EvalItem:
    return EvalItem(
        id="security-test-skill",
        name="test-skill",
        type="skill",
        description="A test skill for security scan",
        source_url=None,
    )


class TestSecurityRunnerBranch:
    """End-to-end runner tests for security_scan task path."""

    def test_runner_returns_security_for_low_risk(self, tmp_path):
        judge = _FakeSecurityJudge(_VALID_SECURITY_PAYLOAD)
        runner = _make_runner(tmp_path, judge)

        results = runner.run([_make_skill_entry()])
        assert len(results) == 1

        result = results[0]
        assert result.security is not None
        assert result.security.risk_level is RiskLevel.low
        assert result.security.verdict is SecurityVerdict.safe
        assert result.metrics == {}  # security path leaves metrics empty
        assert result.enrichment is None

    def test_runner_coerces_entry_on_verdict_risk_mismatch(self, tmp_path):
        """Runner now writes a result even when LLM gives a mismatched verdict —
        the validator coerces verdict from risk_level so the entry isn't dropped
        and security cache gets a row (avoids repeated retries every CI cycle).
        """
        judge = _FakeSecurityJudge(_MISMATCHED_SECURITY_PAYLOAD)
        runner = _make_runner(tmp_path, judge)

        results = runner.run([_make_skill_entry()])
        assert len(results) == 1
        sec = results[0].security
        assert sec is not None
        assert sec.risk_level.value == "high"
        assert sec.verdict.value == "reject"  # coerced from "safe"

    def test_runner_drops_entry_on_empty_llm_response(self, tmp_path):
        judge = _FakeSecurityJudge(None)
        runner = _make_runner(tmp_path, judge)

        results = runner.run([_make_skill_entry()])
        assert results == []

    def test_runner_uses_security_system_prompt(self, tmp_path):
        from ai_resource_eval.metrics.security_scan_prompt import (
            SECURITY_SCAN_SYSTEM_PROMPT,
        )

        judge = _FakeSecurityJudge(_VALID_SECURITY_PAYLOAD)
        runner = _make_runner(tmp_path, judge)

        # _system_prompt was set in __init__; must be the security prompt
        # not the metric/enrichment one.
        assert runner._system_prompt == SECURITY_SCAN_SYSTEM_PROMPT
        # Run once to bump call_count and verify user_prompt is non-empty.
        runner.run([_make_skill_entry()])
        assert judge.call_count == 1
        assert "待审查能力项" in judge.last_user_prompt

    def test_cache_hit_carries_current_entry_id(self, tmp_path):
        """Cache hit must return cached EvalResult with entry_id of the
        querying entry, not the one that originally produced the cache row.

        Regression: 1000+ MCP entries share install={"method": "manual"} →
        identical synth content → identical content_hash. The first entry
        evaluates and caches; subsequent entries hit cache. Without overriding
        entry_id at lookup, downstream code (eval_bridge) maps results by id
        and orphans every cached entry — the catalog ends up with security on
        the first one but not the 1000+ siblings.
        """
        cfg = load_task_config("security_scan")
        # incremental=True so cache lookup is active
        judge = _FakeSecurityJudge(_VALID_SECURITY_PAYLOAD)
        runner = EvalRunner(
            task_config=cfg,
            judge=judge,
            cache_dir=str(tmp_path / ".eval_cache"),
            concurrency=1,
            incremental=True,
            interactive=False,
            on_fail="skip",
        )

        # Two entries with different ids but identical content (no source_url
        # so fetcher falls back to description → same hash).
        entry_a = EvalItem(
            id="mcp-entry-a",
            name="entry-a",
            type="skill",
            description="same body",
            source_url=None,
        )
        entry_b = EvalItem(
            id="mcp-entry-b",
            name="entry-b",
            type="skill",
            description="same body",
            source_url=None,
        )

        results = runner.run([entry_a, entry_b])
        assert len(results) == 2
        # First result: fresh evaluation
        assert results[0].entry_id == "mcp-entry-a"
        assert results[0].model_id != "__cached__"
        # Second result: cache hit, but entry_id is the QUERYING entry's id
        assert results[1].entry_id == "mcp-entry-b"
        assert results[1].model_id == "__cached__"
        # Only one judge call (second was served from cache)
        assert judge.call_count == 1
