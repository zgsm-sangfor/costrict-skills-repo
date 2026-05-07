"""Tests for ``EvalRunner._fetch_content`` plugin routing.

Spec reference: ``openspec/changes/improve-plugin-content-substance/specs/
plugin-content-fetcher/spec.md`` — sections "Runner SHALL route plugin entries"
and "Non-plugin entry uses existing GitHubFetcher".

Three behaviours covered:

1. Plugin entry with successful PluginContentFetcher → returns plugin content,
   GitHubFetcher.fetch is NOT called.
2. Plugin entry where PluginContentFetcher returns None (no plugin.json at
   target) → falls back to GitHubFetcher.fetch (README mode).
3. Non-plugin entry (skill / mcp / rule / prompt) → bypasses plugin fetcher
   entirely, only GitHubFetcher.fetch is called.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from ai_resource_eval.api.judge import JudgeResult
from ai_resource_eval.api.types import EvalItem, TaskConfig
from ai_resource_eval.judges.base import BaseJudge
from ai_resource_eval.runner import EvalRunner


# ---------------------------------------------------------------------------
# Helpers (copied from test_runner.py to keep this test self-contained)
# ---------------------------------------------------------------------------


def _make_task_config() -> TaskConfig:
    """Minimal TaskConfig — same shape as test_runner.py's helper."""
    return TaskConfig(
        task="test_task",
        content_source="readme",
        content_paths=["README.md"],
        content_fallback="description",
        metrics=[
            {"metric": "coding_relevance", "weight": 0.25},
            {"metric": "doc_completeness", "weight": 0.20},
            {"metric": "desc_accuracy", "weight": 0.15},
            {"metric": "writing_quality", "weight": 0.15},
            {"metric": "specificity", "weight": 0.15},
            {"metric": "install_clarity", "weight": 0.10},
        ],
        thresholds={"accept": 65, "review": 40},
        rubric_major_version=1,
    )


def _make_llm_response() -> dict[str, Any]:
    metric_names = [
        "coding_relevance",
        "doc_completeness",
        "desc_accuracy",
        "writing_quality",
        "specificity",
        "install_clarity",
    ]
    return {
        "metrics": {
            name: {
                "score": 4,
                "evidence": [f"evidence for {name}"],
                "missing": [],
                "suggestion": f"improve {name}",
            }
            for name in metric_names
        }
    }


class FakeJudge(BaseJudge):
    """Stub judge that always returns a valid 4/5 metrics response."""

    def _call_llm(
        self,
        system_prompt: str,
        user_prompt: str,
        schema: dict[str, Any] | None = None,
    ) -> tuple[str, int, int, int]:
        return json.dumps(_make_llm_response()), 100, 50, 100

    def _compute_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        return 0.001

    def _model_id(self) -> str:
        return "fake-model"


def _make_entry(entry_type: str | None, entry_id: str = "e1") -> EvalItem:
    return EvalItem(
        id=entry_id,
        name=f"{entry_type or 'unknown'} entry",
        type=entry_type,
        source_url="https://github.com/owner/repo",
        description="An entry",
        stars=42,
    )


@pytest.fixture()
def runner(tmp_path) -> EvalRunner:
    return EvalRunner(
        task_config=_make_task_config(),
        judge=FakeJudge(),
        cache_dir=str(tmp_path / "cache"),
        concurrency=1,
        incremental=False,
        interactive=False,
        on_fail="skip",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRunnerPluginRouting:
    """Verify _fetch_content branches by entry.type."""

    def test_plugin_entry_uses_plugin_fetcher(self, runner):
        """Plugin entry with successful plugin fetch → PluginContentFetcher.fetch is called and result returned; GitHubFetcher.fetch is NOT called."""
        plugin_mock = MagicMock(return_value=("PLUGIN BUNDLE CONTENT", "phash"))
        github_mock = MagicMock(return_value=("README CONTENT", "rhash"))
        runner._plugin_fetcher.fetch = plugin_mock  # type: ignore[method-assign]
        runner._github_fetcher.fetch = github_mock  # type: ignore[method-assign]

        entry = _make_entry("plugin")
        # Set _all_entries for monorepo detection (matches runner.run() invariant)
        runner._all_entries = [entry]

        result = runner._fetch_content(entry)

        assert result is not None
        content, content_hash = result
        assert "PLUGIN BUNDLE CONTENT" in content
        # Plugin fetcher called exactly once with source_url
        plugin_mock.assert_called_once_with("https://github.com/owner/repo")
        # GitHub fetcher NOT called — plugin path won
        github_mock.assert_not_called()

    def test_plugin_entry_falls_back_to_github_when_layout_missing(self, runner):
        """Plugin entry where PluginContentFetcher returns None (no plugin.json) → GitHubFetcher.fetch is invoked."""
        plugin_mock = MagicMock(return_value=None)
        github_mock = MagicMock(return_value=("README FALLBACK", "rhash"))
        runner._plugin_fetcher.fetch = plugin_mock  # type: ignore[method-assign]
        runner._github_fetcher.fetch = github_mock  # type: ignore[method-assign]

        entry = _make_entry("plugin")
        runner._all_entries = [entry]

        result = runner._fetch_content(entry)

        assert result is not None
        content, _ = result
        assert "README FALLBACK" in content
        # Plugin fetch was tried first…
        plugin_mock.assert_called_once_with("https://github.com/owner/repo")
        # …then GitHub fallback was tried.
        github_mock.assert_called_once_with("https://github.com/owner/repo")

    @pytest.mark.parametrize(
        "entry_type", ["skill", "mcp_server", "rule", "prompt", None]
    )
    def test_non_plugin_entry_skips_plugin_fetcher(self, runner, entry_type):
        """Non-plugin entries → only GitHubFetcher.fetch is called; PluginContentFetcher is skipped."""
        plugin_mock = MagicMock(return_value=("SHOULD NOT BE USED", "x"))
        github_mock = MagicMock(return_value=("README CONTENT", "rhash"))
        runner._plugin_fetcher.fetch = plugin_mock  # type: ignore[method-assign]
        runner._github_fetcher.fetch = github_mock  # type: ignore[method-assign]

        entry = _make_entry(entry_type)
        runner._all_entries = [entry]

        result = runner._fetch_content(entry)

        assert result is not None
        content, _ = result
        assert "README CONTENT" in content
        # Plugin fetcher NEVER called for non-plugin types
        plugin_mock.assert_not_called()
        # GitHub fetcher called exactly once
        github_mock.assert_called_once_with("https://github.com/owner/repo")
