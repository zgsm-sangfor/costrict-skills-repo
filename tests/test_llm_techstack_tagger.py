"""Tests for llm_techstack_tagger.py — LLM batch tech_stack tagging."""

import json
import os
import sys
import tempfile
from unittest.mock import patch
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import llm_techstack_tagger


class TestTagTechstack:
    """Test suite for tag_techstack()."""

    def setup_method(self):
        """Create a temp cache file for each test."""
        self.tmpdir = tempfile.mkdtemp()
        self.cache_path = os.path.join(self.tmpdir, ".llm_techstack_cache.json")
        llm_techstack_tagger.CACHE_PATH = self.cache_path

    def _make_entry(self, eid, tech_stack=None, name="Test Tool", desc="A tool"):
        return {
            "id": eid,
            "name": name,
            "description": desc,
            "tech_stack": tech_stack or [],
            "source_url": f"https://github.com/org/{eid}",
        }

    @patch.dict(os.environ, {"LLM_BASE_URL": "http://llm.test/v1", "LLM_API_KEY": "key123"})
    @patch("llm_techstack_tagger._call_llm_batch")
    def test_successful_batch_tagging_returns_vocab_labels(self, mock_llm):
        """WHEN tag_techstack() called with valid entries → returns tech_stack from vocab."""
        entries = [self._make_entry(f"entry-{i}") for i in range(3)]
        mock_llm.return_value = {
            "entry-0": ["python", "fastapi"],
            "entry-1": ["react", "typescript"],
            "entry-2": ["docker", "kubernetes"],
        }
        result = llm_techstack_tagger.tag_techstack(entries)
        assert result["entry-0"] == ["python", "fastapi"]
        assert result["entry-1"] == ["react", "typescript"]
        assert result["entry-2"] == ["docker", "kubernetes"]
        # All labels must be in TECH_STACK_VOCAB
        vocab_set = set(llm_techstack_tagger.TECH_STACK_VOCAB)
        for labels in result.values():
            for label in labels:
                assert label in vocab_set

    @patch.dict(os.environ, {}, clear=True)
    def test_llm_unavailable_returns_empty(self):
        """WHEN LLM_BASE_URL or LLM_API_KEY not set → return {} without crash."""
        os.environ.pop("LLM_BASE_URL", None)
        os.environ.pop("LLM_API_KEY", None)
        entries = [self._make_entry("entry-1")]
        result = llm_techstack_tagger.tag_techstack(entries)
        assert result == {}

    @patch.dict(os.environ, {"LLM_BASE_URL": "http://llm.test/v1", "LLM_API_KEY": "key123"})
    @patch("llm_techstack_tagger._call_llm_batch")
    def test_out_of_vocabulary_labels_filtered(self, mock_llm):
        """WHEN LLM returns label not in TECH_STACK_VOCAB → silently discarded."""
        entries = [self._make_entry("entry-1")]
        mock_llm.return_value = {
            "entry-1": ["python", "react-native", "invalid-framework", "not-in-vocab"],
        }
        result = llm_techstack_tagger.tag_techstack(entries)
        labels = result["entry-1"]
        assert "invalid-framework" not in labels
        assert "not-in-vocab" not in labels
        assert "python" in labels
        assert "react-native" in labels

    @patch.dict(os.environ, {"LLM_BASE_URL": "http://llm.test/v1", "LLM_API_KEY": "key123"})
    @patch("llm_techstack_tagger._call_llm_batch")
    def test_lowercase_normalization(self, mock_llm):
        """WHEN LLM returns mixed-case labels → lowercased before vocab matching."""
        entries = [self._make_entry("entry-1")]
        mock_llm.return_value = {
            "entry-1": ["Python", "REACT", "Docker"],
        }
        result = llm_techstack_tagger.tag_techstack(entries)
        labels = result["entry-1"]
        assert "python" in labels
        assert "react" in labels
        assert "docker" in labels
        # No uppercase should remain
        for label in labels:
            assert label == label.lower()

    @patch.dict(os.environ, {"LLM_BASE_URL": "http://llm.test/v1", "LLM_API_KEY": "key123"})
    @patch("llm_techstack_tagger._call_llm_batch")
    def test_cache_hit_skips_api_call(self, mock_llm):
        """WHEN entry has valid cache entry → use cached result, no LLM call."""
        cache = {
            "entry-cached": {
                "tech_stack": ["python", "django"],
                "cached_at": datetime.now().isoformat(),
            }
        }
        with open(self.cache_path, "w") as f:
            json.dump(cache, f)

        entries = [self._make_entry("entry-cached")]
        result = llm_techstack_tagger.tag_techstack(entries)
        assert result == {"entry-cached": ["python", "django"]}
        mock_llm.assert_not_called()

    @patch.dict(os.environ, {"LLM_BASE_URL": "http://llm.test/v1", "LLM_API_KEY": "key123"})
    @patch("llm_techstack_tagger._call_llm_batch")
    def test_cache_written_after_tagging(self, mock_llm):
        """WHEN new tech_stack results obtained → cache file updated with results and cached_at."""
        entries = [self._make_entry("entry-new")]
        mock_llm.return_value = {"entry-new": ["go", "redis"]}
        llm_techstack_tagger.tag_techstack(entries)

        with open(self.cache_path) as f:
            cache = json.load(f)
        assert "entry-new" in cache
        assert cache["entry-new"]["tech_stack"] == ["go", "redis"]
        assert "cached_at" in cache["entry-new"]

    @patch.dict(os.environ, {"LLM_BASE_URL": "http://llm.test/v1", "LLM_API_KEY": "key123"})
    @patch("llm_techstack_tagger._call_llm_batch")
    def test_expired_cache_triggers_api_call(self, mock_llm):
        """WHEN cache entry is expired → call LLM again."""
        old_time = (datetime.now() - timedelta(days=31)).isoformat()
        cache = {
            "entry-old": {
                "tech_stack": ["python"],
                "cached_at": old_time,
            }
        }
        with open(self.cache_path, "w") as f:
            json.dump(cache, f)

        entries = [self._make_entry("entry-old")]
        mock_llm.return_value = {"entry-old": ["rust", "docker"]}
        result = llm_techstack_tagger.tag_techstack(entries)
        mock_llm.assert_called_once()
        assert result["entry-old"] == ["rust", "docker"]

    @patch.dict(os.environ, {"LLM_BASE_URL": "http://llm.test/v1", "LLM_API_KEY": "key123"})
    @patch("llm_techstack_tagger._call_llm_batch")
    def test_deduplication_of_labels(self, mock_llm):
        """WHEN LLM returns duplicate labels → deduplicated in output."""
        entries = [self._make_entry("entry-1")]
        mock_llm.return_value = {
            "entry-1": ["python", "python", "docker", "docker"],
        }
        result = llm_techstack_tagger.tag_techstack(entries)
        labels = result["entry-1"]
        assert labels.count("python") == 1
        assert labels.count("docker") == 1
