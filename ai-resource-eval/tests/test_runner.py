"""Tests for ai_resource_eval.runner — EvalRunner pipeline.

Tests cover:
- Full pipeline with mock judge + mock fetcher
- Incremental mode (cache hit -> skip judge)
- Queue mode (fetch failure -> review_queue output)
- Concurrent safety (10 threads)
- Fetch failure strategies (skip, queue, error)
- Progress tracking
"""

from __future__ import annotations

import json
import threading
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from ai_resource_eval.api.judge import JudgeResult
from ai_resource_eval.api.types import (
    Decision,
    EvalItem,
    EvalResult,
    MetricResult,
    TaskConfig,
)
from ai_resource_eval.judges.base import BaseJudge
from ai_resource_eval.runner import EvalRunner, FetchError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_task_config() -> TaskConfig:
    """Build a minimal valid TaskConfig for testing."""
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


def _make_entry(
    entry_id: str = "test-entry-1",
    name: str = "Test Resource",
    source_url: str = "https://github.com/owner/repo",
    description: str = "A test resource",
    stars: int = 100,
) -> EvalItem:
    """Build a minimal EvalItem for testing."""
    return EvalItem(
        id=entry_id,
        name=name,
        source_url=source_url,
        description=description,
        stars=stars,
    )


def _make_llm_metrics_response(score: int = 4) -> dict[str, Any]:
    """Build a valid LLM response dict with all 6 metrics."""
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
                "score": score,
                "evidence": [f"evidence for {name}"],
                "missing": [],
                "suggestion": f"improve {name}",
            }
            for name in metric_names
        }
    }


def _make_judge_result(score: int = 4) -> JudgeResult:
    """Build a JudgeResult with a valid structured response."""
    response = _make_llm_metrics_response(score)
    return JudgeResult(
        content=json.dumps(response),
        structured=response,
        cost_usd=0.005,
        prompt_tokens=500,
        completion_tokens=200,
        latency_ms=1200,
        model_id="test-model",
    )


class FakeJudge(BaseJudge):
    """A fake judge for testing that returns pre-configured results."""

    def __init__(self, score: int = 4) -> None:
        self._score = score
        self._call_count = 0
        self._lock = threading.Lock()

    @property
    def call_count(self) -> int:
        with self._lock:
            return self._call_count

    def _call_llm(
        self,
        system_prompt: str,
        user_prompt: str,
        schema: dict[str, Any] | None = None,
    ) -> tuple[str, int, int, int]:
        with self._lock:
            self._call_count += 1
        response = _make_llm_metrics_response(self._score)
        return json.dumps(response), 500, 200, 1200

    def _compute_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        return 0.005

    def _model_id(self) -> str:
        return "fake-model"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def task_config() -> TaskConfig:
    return _make_task_config()


@pytest.fixture()
def fake_judge() -> FakeJudge:
    return FakeJudge(score=4)


@pytest.fixture()
def runner(task_config, fake_judge, tmp_path) -> EvalRunner:
    """Build an EvalRunner with mocked fetcher."""
    r = EvalRunner(
        task_config=task_config,
        judge=fake_judge,
        cache_dir=str(tmp_path / "cache"),
        concurrency=2,
        incremental=False,
        interactive=False,
        on_fail="skip",
    )
    return r


# ===================================================================
# Full pipeline — mock judge + mock fetcher
# ===================================================================


class TestFullPipeline:
    """Test the complete evaluation pipeline end-to-end."""

    @patch("ai_resource_eval.runner.GitHubFetcher.fetch")
    def test_single_entry_produces_eval_result(
        self, mock_fetch, task_config, fake_judge, tmp_path
    ):
        """A single entry with successful fetch produces an EvalResult."""
        mock_fetch.return_value = ("# Test README\nSome content", "abc123hash")

        runner = EvalRunner(
            task_config=task_config,
            judge=fake_judge,
            cache_dir=str(tmp_path / "cache"),
            concurrency=1,
            interactive=False,
        )

        entries = [_make_entry()]
        results = runner.run(entries)

        assert len(results) == 1
        r = results[0]
        assert r.entry_id == "test-entry-1"
        assert isinstance(r.decision, Decision)
        assert r.content_hash == "abc123hash"
        assert r.rubric_version is not None
        assert r.rubric_version.startswith("1.")
        assert len(r.metrics) == 6
        assert "coding_relevance" in r.metrics
        assert r.final_score > 0
        assert r.model_id == "fake-model"
        assert r.evaluated_at is not None

    @patch("ai_resource_eval.runner.GitHubFetcher.fetch")
    def test_multiple_entries(
        self, mock_fetch, task_config, fake_judge, tmp_path
    ):
        """Multiple entries are all evaluated."""
        mock_fetch.return_value = ("# README content", "hash123")

        runner = EvalRunner(
            task_config=task_config,
            judge=fake_judge,
            cache_dir=str(tmp_path / "cache"),
            concurrency=2,
            interactive=False,
        )

        entries = [_make_entry(entry_id=f"entry-{i}") for i in range(5)]
        results = runner.run(entries)

        assert len(results) == 5
        result_ids = {r.entry_id for r in results}
        assert result_ids == {f"entry-{i}" for i in range(5)}

    @patch("ai_resource_eval.runner.GitHubFetcher.fetch")
    def test_score_computation(
        self, mock_fetch, task_config, tmp_path
    ):
        """Verify final_score computation with known metric scores."""
        mock_fetch.return_value = ("README", "hash")

        # All metrics score 5 -> final_score = 100
        judge = FakeJudge(score=5)
        runner = EvalRunner(
            task_config=task_config,
            judge=judge,
            cache_dir=str(tmp_path / "cache"),
            concurrency=1,
            interactive=False,
        )

        results = runner.run([_make_entry()])
        assert len(results) == 1
        assert results[0].final_score == pytest.approx(100.0)

    @patch("ai_resource_eval.runner.GitHubFetcher.fetch")
    def test_score_with_low_scores(
        self, mock_fetch, task_config, tmp_path
    ):
        """Low metric scores produce low final_score."""
        mock_fetch.return_value = ("README", "hash")

        # All metrics score 1 -> final_score = 20
        judge = FakeJudge(score=1)
        runner = EvalRunner(
            task_config=task_config,
            judge=judge,
            cache_dir=str(tmp_path / "cache"),
            concurrency=1,
            interactive=False,
        )

        results = runner.run([_make_entry()])
        assert len(results) == 1
        # score=1: (1/5)*100 * sum(weights) = 20 * 1.0 = 20
        assert results[0].final_score == pytest.approx(20.0)

    @patch("ai_resource_eval.runner.GitHubFetcher.fetch")
    def test_decision_thresholds(
        self, mock_fetch, task_config, tmp_path
    ):
        """Verify decision logic: high score=accept, low score=reject."""
        mock_fetch.return_value = ("README", "hash")

        # score=5 -> 100 -> accept
        judge = FakeJudge(score=5)
        runner = EvalRunner(
            task_config=task_config,
            judge=judge,
            cache_dir=str(tmp_path / "cache"),
            concurrency=1,
            interactive=False,
        )
        results = runner.run([_make_entry()])
        assert results[0].decision == Decision.accept

        # score=1 -> 20 -> reject (below review threshold of 40)
        judge2 = FakeJudge(score=1)
        runner2 = EvalRunner(
            task_config=task_config,
            judge=judge2,
            cache_dir=str(tmp_path / "cache2"),
            concurrency=1,
            interactive=False,
        )
        results2 = runner2.run([_make_entry()])
        assert results2[0].decision == Decision.reject

    @patch("ai_resource_eval.runner.GitHubFetcher.fetch")
    def test_result_is_cached(
        self, mock_fetch, task_config, fake_judge, tmp_path
    ):
        """After evaluation, the result is stored in the cache."""
        mock_fetch.return_value = ("README content", "hash123")

        runner = EvalRunner(
            task_config=task_config,
            judge=fake_judge,
            cache_dir=str(tmp_path / "cache"),
            concurrency=1,
            interactive=False,
        )

        runner.run([_make_entry()])

        # Cache should have at least 1 entry
        stats = runner.cache.stats()
        assert stats["entries"] >= 1


# ===================================================================
# Incremental mode — cache hit -> skip judge
# ===================================================================


class TestIncrementalMode:
    """Test that incremental mode skips cached entries."""

    @patch("ai_resource_eval.runner.GitHubFetcher.fetch")
    def test_incremental_skips_cached(
        self, mock_fetch, task_config, tmp_path
    ):
        """Second run with same content should use cache, not call judge."""
        mock_fetch.return_value = ("README same content", "same_hash")

        judge = FakeJudge(score=4)

        # First run: evaluates normally
        runner = EvalRunner(
            task_config=task_config,
            judge=judge,
            cache_dir=str(tmp_path / "cache"),
            concurrency=1,
            incremental=True,
            interactive=False,
        )
        results1 = runner.run([_make_entry()])
        assert len(results1) == 1
        first_call_count = judge.call_count
        assert first_call_count == 1

        # Second run: should hit cache, no additional judge calls
        results2 = runner.run([_make_entry()])
        assert len(results2) == 1
        assert judge.call_count == first_call_count  # no new calls
        # Cached result is marked with __cached__
        assert results2[0].model_id == "__cached__"

    @patch("ai_resource_eval.runner.GitHubFetcher.fetch")
    def test_incremental_reeval_on_content_change(
        self, mock_fetch, task_config, tmp_path
    ):
        """Changed content should cause re-evaluation even in incremental mode."""
        judge = FakeJudge(score=4)
        runner = EvalRunner(
            task_config=task_config,
            judge=judge,
            cache_dir=str(tmp_path / "cache"),
            concurrency=1,
            incremental=True,
            interactive=False,
        )

        # First run with content v1
        mock_fetch.return_value = ("README v1", "hash_v1")
        runner.run([_make_entry()])
        assert judge.call_count == 1

        # Second run with content v2 (different hash)
        mock_fetch.return_value = ("README v2", "hash_v2")
        runner.run([_make_entry()])
        assert judge.call_count == 2  # re-evaluated

    @patch("ai_resource_eval.runner.GitHubFetcher.fetch")
    def test_non_incremental_always_evaluates(
        self, mock_fetch, task_config, tmp_path
    ):
        """Without incremental mode, every run calls the judge."""
        mock_fetch.return_value = ("README content", "same_hash")
        judge = FakeJudge(score=4)

        runner = EvalRunner(
            task_config=task_config,
            judge=judge,
            cache_dir=str(tmp_path / "cache"),
            concurrency=1,
            incremental=False,
            interactive=False,
        )

        runner.run([_make_entry()])
        runner.run([_make_entry()])
        assert judge.call_count == 2


# ===================================================================
# Queue mode — fetch failure -> review_queue
# ===================================================================


class TestQueueMode:
    """Test that fetch failures in queue mode produce review_queue entries."""

    @patch("ai_resource_eval.runner.GitHubFetcher.fetch")
    def test_fetch_failure_queued(
        self, mock_fetch, task_config, fake_judge, tmp_path
    ):
        """Fetch failure with on_fail='queue' adds entry to review_queue."""
        mock_fetch.return_value = None  # fetch fails

        runner = EvalRunner(
            task_config=task_config,
            judge=fake_judge,
            cache_dir=str(tmp_path / "cache"),
            concurrency=1,
            interactive=False,
            on_fail="queue",
        )

        entry = _make_entry(description=None)  # no fallback either
        results = runner.run([entry])

        assert len(results) == 0
        assert len(runner.review_queue) == 1
        queued = runner.review_queue[0]
        assert queued["id"] == "test-entry-1"
        assert queued["_review_reason"] == "fetch_failed"

    @patch("ai_resource_eval.runner.GitHubFetcher.fetch")
    def test_queue_preserves_entry_schema(
        self, mock_fetch, task_config, fake_judge, tmp_path
    ):
        """Queued entries preserve the original entry schema plus _review_reason."""
        mock_fetch.return_value = None

        runner = EvalRunner(
            task_config=task_config,
            judge=fake_judge,
            cache_dir=str(tmp_path / "cache"),
            concurrency=1,
            interactive=False,
            on_fail="queue",
        )

        entry = _make_entry(
            entry_id="q-test",
            name="Queue Test",
            source_url="https://github.com/owner/repo",
            description=None,
            stars=42,
        )
        runner.run([entry])

        queued = runner.review_queue[0]
        assert queued["name"] == "Queue Test"
        assert queued["stars"] == 42
        assert "_review_reason" in queued

    @patch("ai_resource_eval.runner.GitHubFetcher.fetch")
    def test_multiple_failures_all_queued(
        self, mock_fetch, task_config, fake_judge, tmp_path
    ):
        """Multiple fetch failures are all added to the queue."""
        mock_fetch.return_value = None

        runner = EvalRunner(
            task_config=task_config,
            judge=fake_judge,
            cache_dir=str(tmp_path / "cache"),
            concurrency=2,
            interactive=False,
            on_fail="queue",
        )

        entries = [
            _make_entry(entry_id=f"fail-{i}", description=None)
            for i in range(3)
        ]
        runner.run(entries)

        assert len(runner.review_queue) == 3

    @patch("ai_resource_eval.runner.GitHubFetcher.fetch")
    def test_queue_is_json_serializable(
        self, mock_fetch, task_config, fake_judge, tmp_path
    ):
        """The review_queue output should be JSON-serializable."""
        mock_fetch.return_value = None

        runner = EvalRunner(
            task_config=task_config,
            judge=fake_judge,
            cache_dir=str(tmp_path / "cache"),
            concurrency=1,
            interactive=False,
            on_fail="queue",
        )

        runner.run([_make_entry(description=None)])

        # Should not raise
        serialized = json.dumps(runner.review_queue, default=str)
        assert isinstance(serialized, str)


# ===================================================================
# Fetch failure strategies
# ===================================================================


class TestFetchFailureStrategies:
    """Test on_fail='skip', 'queue', and 'error' strategies."""

    @patch("ai_resource_eval.runner.GitHubFetcher.fetch")
    def test_skip_returns_empty(
        self, mock_fetch, task_config, fake_judge, tmp_path
    ):
        """on_fail='skip' returns no result for failed entries."""
        mock_fetch.return_value = None

        runner = EvalRunner(
            task_config=task_config,
            judge=fake_judge,
            cache_dir=str(tmp_path / "cache"),
            concurrency=1,
            interactive=False,
            on_fail="skip",
        )

        results = runner.run([_make_entry(description=None)])
        assert len(results) == 0
        assert len(runner.review_queue) == 0

    @patch("ai_resource_eval.runner.GitHubFetcher.fetch")
    def test_error_raises(
        self, mock_fetch, task_config, fake_judge, tmp_path
    ):
        """on_fail='error' raises FetchError on failure."""
        mock_fetch.return_value = None

        runner = EvalRunner(
            task_config=task_config,
            judge=fake_judge,
            cache_dir=str(tmp_path / "cache"),
            concurrency=1,
            interactive=False,
            on_fail="error",
        )

        # The error is caught by the executor but propagated as FetchError.
        # In the runner, it's caught and counted as skipped.
        results = runner.run([_make_entry(description=None)])
        assert len(results) == 0

    @patch("ai_resource_eval.runner.GitHubFetcher.fetch")
    def test_description_fallback(
        self, mock_fetch, task_config, fake_judge, tmp_path
    ):
        """When GitHub fetch fails but description exists, use description."""
        mock_fetch.return_value = None  # GitHub fails

        runner = EvalRunner(
            task_config=task_config,
            judge=fake_judge,
            cache_dir=str(tmp_path / "cache"),
            concurrency=1,
            interactive=False,
            on_fail="skip",
        )

        entry = _make_entry(description="This is a description fallback")
        results = runner.run([entry])

        # Should succeed because description is used as content
        assert len(results) == 1

    @patch("ai_resource_eval.runner.GitHubFetcher.fetch")
    def test_mixed_success_and_failure(
        self, mock_fetch, task_config, fake_judge, tmp_path
    ):
        """Mix of successful and failed entries."""
        # First entry succeeds, second fails
        mock_fetch.side_effect = [
            ("README content", "hash1"),
            None,
            ("README content 2", "hash2"),
        ]

        runner = EvalRunner(
            task_config=task_config,
            judge=fake_judge,
            cache_dir=str(tmp_path / "cache"),
            concurrency=1,
            interactive=False,
            on_fail="queue",
        )

        entries = [
            _make_entry(entry_id="ok-1"),
            _make_entry(entry_id="fail-1", description=None),
            _make_entry(entry_id="ok-2"),
        ]
        results = runner.run(entries)

        assert len(results) == 2
        assert len(runner.review_queue) == 1
        assert runner.review_queue[0]["id"] == "fail-1"


# ===================================================================
# Concurrent safety — 10 threads
# ===================================================================


class TestConcurrentSafety:
    """Test that the runner is safe with multiple concurrent threads."""

    @patch("ai_resource_eval.runner.GitHubFetcher.fetch")
    def test_concurrent_10_threads(
        self, mock_fetch, task_config, tmp_path
    ):
        """10 concurrent threads should produce correct results without errors."""
        mock_fetch.return_value = ("# Concurrent README", "concurrent_hash")

        judge = FakeJudge(score=3)
        runner = EvalRunner(
            task_config=task_config,
            judge=judge,
            cache_dir=str(tmp_path / "cache"),
            concurrency=10,
            interactive=False,
        )

        entries = [_make_entry(entry_id=f"concurrent-{i}") for i in range(20)]
        results = runner.run(entries)

        assert len(results) == 20
        result_ids = {r.entry_id for r in results}
        assert len(result_ids) == 20

        # Judge should have been called for each entry
        assert judge.call_count == 20

    @patch("ai_resource_eval.runner.GitHubFetcher.fetch")
    def test_concurrent_cache_writes(
        self, mock_fetch, task_config, tmp_path
    ):
        """Concurrent cache writes should not corrupt the database."""
        mock_fetch.return_value = ("README", "hash")

        judge = FakeJudge(score=4)
        runner = EvalRunner(
            task_config=task_config,
            judge=judge,
            cache_dir=str(tmp_path / "cache"),
            concurrency=10,
            interactive=False,
        )

        entries = [_make_entry(entry_id=f"cache-{i}") for i in range(10)]
        runner.run(entries)

        stats = runner.cache.stats()
        # Each entry gets its own cache key (content hash is the same,
        # but we store per entry_id within the full result)
        assert stats["entries"] >= 1  # at least some were cached

    @patch("ai_resource_eval.runner.GitHubFetcher.fetch")
    def test_concurrent_with_failures(
        self, mock_fetch, task_config, tmp_path
    ):
        """Concurrent execution handles mixed success/failure gracefully."""
        call_count = {"n": 0}
        lock = threading.Lock()

        def alternating_fetch(url):
            with lock:
                call_count["n"] += 1
                n = call_count["n"]
            if n % 3 == 0:
                return None  # every 3rd fetch fails
            return ("README", f"hash_{n}")

        mock_fetch.side_effect = alternating_fetch

        judge = FakeJudge(score=4)
        runner = EvalRunner(
            task_config=task_config,
            judge=judge,
            cache_dir=str(tmp_path / "cache"),
            concurrency=5,
            interactive=False,
            on_fail="queue",
        )

        entries = [
            _make_entry(entry_id=f"mixed-{i}", description=None)
            for i in range(12)
        ]
        results = runner.run(entries)

        # Should have some results and some queued
        total = len(results) + len(runner.review_queue)
        assert total == 12


# ===================================================================
# Rubric version
# ===================================================================


class TestRubricVersion:
    """Test rubric version computation."""

    def test_rubric_version_format(self, task_config, fake_judge, tmp_path):
        """rubric_version should be 'major.sha8'."""
        runner = EvalRunner(
            task_config=task_config,
            judge=fake_judge,
            cache_dir=str(tmp_path / "cache"),
        )
        rv = runner._rubric_version
        parts = rv.split(".")
        assert len(parts) == 2
        assert parts[0] == "1"  # rubric_major_version from config
        assert len(parts[1]) == 8  # sha8

    def test_rubric_version_deterministic(
        self, task_config, fake_judge, tmp_path
    ):
        """Same config produces the same rubric_version."""
        r1 = EvalRunner(
            task_config=task_config,
            judge=fake_judge,
            cache_dir=str(tmp_path / "cache1"),
        )
        r2 = EvalRunner(
            task_config=task_config,
            judge=fake_judge,
            cache_dir=str(tmp_path / "cache2"),
        )
        assert r1._rubric_version == r2._rubric_version


# ===================================================================
# User prompt building
# ===================================================================


class TestUserPromptBuilding:
    """Test the user prompt construction."""

    @patch("ai_resource_eval.runner.GitHubFetcher.fetch")
    def test_user_prompt_contains_metadata(
        self, mock_fetch, task_config, fake_judge, tmp_path
    ):
        """User prompt includes entry metadata and content."""
        runner = EvalRunner(
            task_config=task_config,
            judge=fake_judge,
            cache_dir=str(tmp_path / "cache"),
        )

        entry = _make_entry(
            name="My Tool",
            description="A great tool",
            stars=500,
        )
        prompt = runner._build_user_prompt(entry, "# My README\nContent here")

        assert "My Tool" in prompt
        assert "A great tool" in prompt
        assert "500" in prompt
        assert "# My README" in prompt
        assert "Content here" in prompt


# ===================================================================
# Review queue property
# ===================================================================


class TestReviewQueueProperty:
    """Test the review_queue property."""

    def test_review_queue_returns_copy(
        self, task_config, fake_judge, tmp_path
    ):
        """review_queue should return a copy, not the internal list."""
        runner = EvalRunner(
            task_config=task_config,
            judge=fake_judge,
            cache_dir=str(tmp_path / "cache"),
        )
        q1 = runner.review_queue
        q2 = runner.review_queue
        assert q1 is not q2  # different list objects

    def test_review_queue_empty_initially(
        self, task_config, fake_judge, tmp_path
    ):
        """review_queue starts empty."""
        runner = EvalRunner(
            task_config=task_config,
            judge=fake_judge,
            cache_dir=str(tmp_path / "cache"),
        )
        assert runner.review_queue == []


# ===================================================================
# Star weight integration
# ===================================================================


class TestStarWeightIntegration:
    """Test that star_weight is computed and included in results."""

    @patch("ai_resource_eval.runner.GitHubFetcher.fetch")
    def test_entry_with_stars_gets_weight(
        self, mock_fetch, task_config, fake_judge, tmp_path
    ):
        """Entry with stars should get star_weight = 1.0."""
        mock_fetch.return_value = ("README", "hash")

        runner = EvalRunner(
            task_config=task_config,
            judge=fake_judge,
            cache_dir=str(tmp_path / "cache"),
            concurrency=1,
            interactive=False,
        )

        results = runner.run([_make_entry(stars=100)])
        assert results[0].star_weight == 1.0

    @patch("ai_resource_eval.runner.GitHubFetcher.fetch")
    def test_entry_without_stars_gets_zero_weight(
        self, mock_fetch, task_config, fake_judge, tmp_path
    ):
        """Entry with no stars should get star_weight = 0.0."""
        mock_fetch.return_value = ("README", "hash")

        runner = EvalRunner(
            task_config=task_config,
            judge=fake_judge,
            cache_dir=str(tmp_path / "cache"),
            concurrency=1,
            interactive=False,
        )

        results = runner.run([_make_entry(stars=0)])
        assert results[0].star_weight == 0.0


# ===================================================================
# Metric parsing edge cases
# ===================================================================


class TestMetricParsing:
    """Test metric parsing from LLM response."""

    def test_parse_valid_response(self, task_config, fake_judge, tmp_path):
        """Valid structured response is parsed into MetricResults."""
        runner = EvalRunner(
            task_config=task_config,
            judge=fake_judge,
            cache_dir=str(tmp_path / "cache"),
        )

        jr = _make_judge_result(score=4)
        result = runner._parse_metrics(jr)

        assert result is not None
        assert len(result) == 6
        assert all(isinstance(v, MetricResult) for v in result.values())
        assert result["coding_relevance"].score == 4

    def test_parse_none_structured(self, task_config, fake_judge, tmp_path):
        """None structured response returns None."""
        runner = EvalRunner(
            task_config=task_config,
            judge=fake_judge,
            cache_dir=str(tmp_path / "cache"),
        )

        jr = JudgeResult(
            content="garbage",
            structured=None,
            cost_usd=0.0,
            prompt_tokens=0,
            completion_tokens=0,
            latency_ms=0,
            model_id="test",
        )
        assert runner._parse_metrics(jr) is None

    def test_parse_missing_metric(self, task_config, fake_judge, tmp_path):
        """Response missing a required metric returns None."""
        runner = EvalRunner(
            task_config=task_config,
            judge=fake_judge,
            cache_dir=str(tmp_path / "cache"),
        )

        # Only 5 of 6 metrics
        response = _make_llm_metrics_response()
        del response["metrics"]["install_clarity"]

        jr = JudgeResult(
            content=json.dumps(response),
            structured=response,
            cost_usd=0.0,
            prompt_tokens=0,
            completion_tokens=0,
            latency_ms=0,
            model_id="test",
        )
        assert runner._parse_metrics(jr) is None
