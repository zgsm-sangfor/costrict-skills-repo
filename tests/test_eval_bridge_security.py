"""Tests for the security_scan stage in scripts/eval_bridge.py."""

from __future__ import annotations

import json
import os
import sys
from typing import Any
from unittest.mock import patch

import pytest

SCRIPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts"))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import eval_bridge  # noqa: E402


# ---------------------------------------------------------------------------
# MCP synthetic content + EvalItem construction
# ---------------------------------------------------------------------------


class TestMcpSyntheticContent:
    def test_synth_returns_serialized_install_config(self):
        from ai_resource_eval.metrics.security_scan_prompt import (
            build_security_synth_content_for_mcp,
        )

        install = {
            "method": "mcp_config_template",
            "config": {
                "command": "uvx",
                "args": ["some-mcp-server"],
                "env": {"API_KEY": "${API_KEY}"},
            },
        }
        synth = build_security_synth_content_for_mcp(install)
        parsed = json.loads(synth)
        assert parsed["config"]["command"] == "uvx"
        assert parsed["method"] == "mcp_config_template"

    def test_synth_handles_missing_install(self):
        from ai_resource_eval.metrics.security_scan_prompt import (
            build_security_synth_content_for_mcp,
        )

        assert build_security_synth_content_for_mcp(None) == "(no install metadata)"
        assert build_security_synth_content_for_mcp({}) == "(no install metadata)"

    def test_mcp_eval_item_drops_source_url(self):
        from ai_resource_eval.api.types import EvalItem

        entry = {
            "id": "mcp-1",
            "name": "test-mcp",
            "type": "mcp",
            "source_url": "https://github.com/owner/repo",
            "description": "Original description",
            "install": {
                "method": "stdio",
                "config": {"command": "python", "args": ["./srv.py"]},
            },
        }
        item = eval_bridge._build_mcp_security_eval_item(entry, EvalItem)
        assert item is not None
        # source_url is cleared so the runner uses description fallback.
        assert item.source_url is None
        # description was replaced with the serialized install.config
        assert "stdio" in (item.description or "")
        assert "python" in (item.description or "")
        # install field is preserved so the user prompt can still surface it
        assert item.install is not None
        assert item.install["method"] == "stdio"


# ---------------------------------------------------------------------------
# Mapping security result → entry.security
# ---------------------------------------------------------------------------


def _valid_security_result() -> dict[str, Any]:
    return {
        "entry_id": "skill-1",
        "metrics": {},
        "security": {
            "risk_level": "low",
            "verdict": "safe",
            "red_flags": [],
            "permissions": {"files": [], "network": [], "commands": []},
            "summary": "无外部 IO",
            "recommendations": [],
        },
        "final_score": 0,
        "decision": "review",
        "content_hash": "deadbeef" * 8,
        "rubric_version": "1.abcd1234",
        "model_id": "fake-judge",
        "evaluated_at": "2026-05-18T00:00:00+00:00",
    }


class TestMapSecurityToEntry:
    def test_full_security_block_written(self):
        entry = {"id": "skill-1", "name": "test", "type": "skill"}
        eval_bridge._map_security_to_entry(entry, _valid_security_result())
        sec = entry["security"]
        assert sec["risk_level"] == "low"
        assert sec["verdict"] == "safe"
        assert sec["permissions"] == {"files": [], "network": [], "commands": []}
        assert sec["red_flags"] == []
        assert sec["summary"] == "无外部 IO"
        assert sec["recommendations"] == []
        # audit fields
        assert sec["scan_model"] == "fake-judge"
        assert sec["rubric_version"] == "1.abcd1234"
        assert sec["content_hash"] == "deadbeef" * 8
        assert sec["scanned_at"] == "2026-05-18T00:00:00+00:00"

    def test_no_result_means_no_security_field(self):
        entry = {"id": "skill-1", "name": "test", "type": "skill"}
        eval_bridge._map_security_to_entry(entry, None)
        assert "security" not in entry

    def test_result_without_security_key_skips(self):
        entry = {"id": "skill-1", "name": "test", "type": "skill"}
        result = _valid_security_result()
        result.pop("security")
        eval_bridge._map_security_to_entry(entry, result)
        assert "security" not in entry

    def test_missing_evaluated_at_uses_now(self):
        entry = {"id": "skill-1", "name": "test", "type": "skill"}
        result = _valid_security_result()
        result.pop("evaluated_at")
        eval_bridge._map_security_to_entry(entry, result)
        # Just verify the field exists and is a non-empty string.
        assert isinstance(entry["security"]["scanned_at"], str)
        assert entry["security"]["scanned_at"]


# ---------------------------------------------------------------------------
# security_scan_and_map: full failure isolation
# ---------------------------------------------------------------------------


class TestSecurityScanAndMap:
    def test_no_judge_means_no_writes(self, tmp_path):
        """When no LLM key is configured (judge=None) the stage is a no-op."""
        entries = [{"id": "skill-1", "name": "test", "type": "skill"}]
        with patch.object(eval_bridge, "_build_judge", return_value=None):
            eval_bridge.security_scan_and_map(
                entries, cache_dir=str(tmp_path / ".eval_cache")
            )
        assert "security" not in entries[0]

    def test_runner_exception_does_not_propagate(self, tmp_path):
        entries = [{"id": "skill-1", "name": "test", "type": "skill"}]

        def boom(*a, **kw):
            raise RuntimeError("runner blew up")

        with patch.object(eval_bridge, "_run_security_scan", side_effect=boom):
            # Must not raise
            eval_bridge.security_scan_and_map(
                entries, cache_dir=str(tmp_path / ".eval_cache")
            )
        assert "security" not in entries[0]

    def test_successful_result_writes_entry_security(self, tmp_path):
        entries = [{"id": "skill-1", "name": "test", "type": "skill"}]
        fake_results = {"skill-1": _valid_security_result()}
        with patch.object(eval_bridge, "_run_security_scan", return_value=fake_results):
            eval_bridge.security_scan_and_map(
                entries, cache_dir=str(tmp_path / ".eval_cache")
            )
        assert entries[0]["security"]["risk_level"] == "low"
        assert entries[0]["security"]["verdict"] == "safe"

    def test_missing_result_means_no_field(self, tmp_path):
        entries = [
            {"id": "skill-1", "name": "test1", "type": "skill"},
            {"id": "skill-2", "name": "test2", "type": "skill"},
        ]
        # Only skill-1 has a result; skill-2 should be left without security
        fake_results = {"skill-1": _valid_security_result()}
        with patch.object(eval_bridge, "_run_security_scan", return_value=fake_results):
            eval_bridge.security_scan_and_map(
                entries, cache_dir=str(tmp_path / ".eval_cache")
            )
        assert "security" in entries[0]
        assert "security" not in entries[1]
