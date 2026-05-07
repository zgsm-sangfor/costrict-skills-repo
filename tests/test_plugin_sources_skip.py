"""Tests for the plugin-source skip helpers in ``utils``.

The 5 sync scripts (``sync_skills``, ``sync_mcp``, ``sync_skills_sh``,
``sync_mcp_registry``, ``sync_windsurfrules``) all funnel their per-entry
skip decision through ``utils.is_plugin_source()`` (which in turn calls
``utils.load_plugin_sources()`` and ``utils._normalize_plugin_url()``).
Testing the shared helper directly therefore exercises the same code path
each script relies on, without requiring HTTP mocking for end-to-end runs.

Coverage:
- URL normalization (fragment, query, ``.git``, trailing slash, ``www.``,
  reverse-DNS).
- ``is_plugin_source()`` matching (exact, sub-path, fragment, unrelated,
  empty inputs).
- ``load_plugin_sources()`` graceful degradation on missing / invalid JSON
  files (WARNING logged + empty set returned). The ``_path_override``
  kwarg added to ``load_plugin_sources()`` for testability lets us point
  the loader at a temp file instead of mutating the real one.
"""

import json
import logging
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import utils  # noqa: E402
from utils import (  # noqa: E402
    _normalize_plugin_url,
    is_plugin_source,
    load_plugin_sources,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_plugin_cache():
    """Clear the module-level cache around each test to keep them isolated."""
    utils._plugin_sources_cache = None
    yield
    utils._plugin_sources_cache = None


@pytest.fixture
def fake_plugin_sources(tmp_path, monkeypatch):
    """Write a controlled plugin_sources.json and force the loader to read it.

    Returns the path so individual tests can re-write it if they need a
    different repo list.
    """
    path = tmp_path / "plugin_sources.json"
    path.write_text(
        json.dumps(
            {
                "repos": [
                    "https://github.com/obra/superpowers",
                    "https://github.com/obra/superpowers-marketplace",
                    "https://github.com/anthropics/claude-plugins-official",
                ]
            }
        ),
        encoding="utf-8",
    )

    # Patch the cache loader to default to our override path so that
    # is_plugin_source() (which calls load_plugin_sources() with no args)
    # picks up the temp file. We do this by replacing load_plugin_sources
    # with a thin wrapper that injects _path_override.
    real_loader = utils.load_plugin_sources

    def _patched_loader(force_reload=False, _path_override=None):
        if _path_override is None:
            _path_override = str(path)
        return real_loader(force_reload=force_reload, _path_override=_path_override)

    monkeypatch.setattr(utils, "load_plugin_sources", _patched_loader)
    return path


# ---------------------------------------------------------------------------
# _normalize_plugin_url()
# ---------------------------------------------------------------------------


def test_normalize_strips_fragment():
    assert (
        _normalize_plugin_url("https://github.com/obra/superpowers#skill=foo")
        == "https://github.com/obra/superpowers"
    )


def test_normalize_strips_query():
    assert (
        _normalize_plugin_url("https://github.com/obra/superpowers?ref=main")
        == "https://github.com/obra/superpowers"
    )


def test_normalize_strips_git_suffix():
    assert (
        _normalize_plugin_url("https://github.com/obra/superpowers.git")
        == "https://github.com/obra/superpowers"
    )


def test_normalize_strips_trailing_slash():
    assert (
        _normalize_plugin_url("https://github.com/obra/superpowers/")
        == "https://github.com/obra/superpowers"
    )


def test_normalize_strips_www():
    assert (
        _normalize_plugin_url("https://www.github.com/obra/superpowers")
        == "https://github.com/obra/superpowers"
    )


def test_normalize_handles_reverse_dns():
    """Reverse-DNS form (used by registry.modelcontextprotocol.io) is rewritten
    to the canonical https://github.com/<owner>/<repo> form before normalizing.
    """
    assert (
        _normalize_plugin_url("io.github.obra/superpowers")
        == "https://github.com/obra/superpowers"
    )


def test_normalize_lowercases():
    assert (
        _normalize_plugin_url("https://GitHub.com/Obra/Superpowers")
        == "https://github.com/obra/superpowers"
    )


def test_normalize_empty_returns_empty():
    assert _normalize_plugin_url("") == ""


# ---------------------------------------------------------------------------
# is_plugin_source()
# ---------------------------------------------------------------------------


def test_is_plugin_source_exact_match(fake_plugin_sources):
    assert is_plugin_source("https://github.com/obra/superpowers") is True


def test_is_plugin_source_subpath(fake_plugin_sources):
    """A URL pointing at a sub-path inside a listed plugin repo matches."""
    assert (
        is_plugin_source(
            "https://github.com/obra/superpowers/tree/main/skills/foo"
        )
        is True
    )


def test_is_plugin_source_fragment_url(fake_plugin_sources):
    """Round-2 regression: skills.sh attaches `#skill=<name>` to the repo URL.
    The normalizer must drop the fragment so the candidate still matches.
    """
    assert (
        is_plugin_source("https://github.com/obra/superpowers#skill=bar")
        is True
    )


def test_is_plugin_source_query_url(fake_plugin_sources):
    assert (
        is_plugin_source("https://github.com/obra/superpowers?ref=main")
        is True
    )


def test_is_plugin_source_git_suffix_url(fake_plugin_sources):
    assert (
        is_plugin_source("https://github.com/obra/superpowers.git") is True
    )


def test_is_plugin_source_reverse_dns(fake_plugin_sources):
    """MCP registry server names (`io.github.<owner>/<repo>`) should match."""
    assert is_plugin_source("io.github.obra/superpowers") is True


def test_is_plugin_source_unrelated_url(fake_plugin_sources):
    assert (
        is_plugin_source("https://github.com/some-other-owner/some-repo")
        is False
    )


def test_is_plugin_source_sibling_repo_not_matched(fake_plugin_sources):
    """A repo that merely shares a prefix (same owner, different repo) must NOT
    match. Without the explicit ``+ "/"`` boundary in the sub-path check this
    would falsely match a hypothetical `superpowers-clone` repo.
    """
    assert (
        is_plugin_source("https://github.com/obra/superpowers-clone")
        is False
    )


def test_is_plugin_source_empty_inputs(fake_plugin_sources):
    assert is_plugin_source("") is False
    assert is_plugin_source(None) is False  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# load_plugin_sources() degradation paths
# ---------------------------------------------------------------------------


def test_load_plugin_sources_missing_file(tmp_path, caplog):
    """Missing file → empty set + WARNING (skip list disabled, no crash)."""
    missing = tmp_path / "missing.json"
    assert not missing.exists()

    with caplog.at_level(logging.WARNING, logger="utils"):
        result = load_plugin_sources(
            force_reload=True, _path_override=str(missing)
        )

    assert result == set()
    assert any(
        "plugin_sources.json not found" in rec.message
        for rec in caplog.records
    ), f"expected 'not found' WARNING, got: {[r.message for r in caplog.records]}"


def test_load_plugin_sources_invalid_json(tmp_path, caplog):
    """Garbage JSON → empty set + WARNING (skip list disabled, no crash)."""
    bad = tmp_path / "broken.json"
    bad.write_text("{not valid json at all", encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="utils"):
        result = load_plugin_sources(
            force_reload=True, _path_override=str(bad)
        )

    assert result == set()
    assert any(
        "Failed to parse plugin_sources.json" in rec.message
        for rec in caplog.records
    ), f"expected 'Failed to parse' WARNING, got: {[r.message for r in caplog.records]}"


def test_load_plugin_sources_missing_repos_array(tmp_path, caplog):
    """JSON without a ``repos`` array → empty set + WARNING."""
    bad = tmp_path / "no_repos.json"
    bad.write_text(json.dumps({"something_else": []}), encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="utils"):
        result = load_plugin_sources(
            force_reload=True, _path_override=str(bad)
        )

    assert result == set()
    assert any(
        "missing 'repos' array" in rec.message for rec in caplog.records
    ), f"expected 'missing repos' WARNING, got: {[r.message for r in caplog.records]}"


def test_load_plugin_sources_normalizes_entries(tmp_path):
    """Entries in the file are normalized at load time (so the lookup set is
    already canonical and ``is_plugin_source`` can do a plain ``in`` check).
    """
    path = tmp_path / "messy.json"
    path.write_text(
        json.dumps(
            {
                "repos": [
                    "https://GitHub.com/Obra/Superpowers/",
                    "https://github.com/obra/superpowers-marketplace.git",
                ]
            }
        ),
        encoding="utf-8",
    )
    result = load_plugin_sources(
        force_reload=True, _path_override=str(path)
    )
    assert result == {
        "https://github.com/obra/superpowers",
        "https://github.com/obra/superpowers-marketplace",
    }


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
