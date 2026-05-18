"""Tests for the plugin-level blacklist helpers in ``utils``.

The two plugin sync scripts (``sync_plugins_official``, ``sync_plugins_dev``)
both funnel their per-plugin skip decision through
``utils.is_plugin_blacklisted()``, which reads the optional ``plugins`` array
loaded by ``utils.load_plugin_blacklist()`` from
``scripts/plugin_sources.json``. Testing the shared helper directly therefore
exercises the same code path each script relies on.

Coverage:
- Exact ``(source, plugin_name)`` match → True.
- Case-insensitive normalization → ``Superpowers-Marketplace::Superpowers``
  matches a blacklist entry stored as ``superpowers-marketplace::superpowers``.
- Source matches but ``plugin_name`` does not → False (no spurious hits).
- Legacy ``plugin_sources.json`` files missing the ``plugins`` field load as
  an empty list and the helper returns False (sync output unchanged).
- Empty / ``None`` blacklist inputs are tolerated.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from utils import (  # noqa: E402
    is_plugin_blacklisted,
    load_plugin_blacklist,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def blacklist() -> list[dict]:
    """Canonical blacklist matching the initial production entries."""
    return [
        {"source": "superpowers-marketplace", "plugin_name": "superpowers"},
        {"source": "superpowers-marketplace", "plugin_name": "superpowers-dev"},
    ]


# ---------------------------------------------------------------------------
# is_plugin_blacklisted — behavioural tests (Scenarios i–iv from spec)
# ---------------------------------------------------------------------------


def test_exact_match_hits(blacklist):
    """Scenario (i): exact tuple match returns True."""
    assert is_plugin_blacklisted(
        "superpowers-marketplace", "superpowers", blacklist
    ) is True
    assert is_plugin_blacklisted(
        "superpowers-marketplace", "superpowers-dev", blacklist
    ) is True


def test_case_insensitive_match(blacklist):
    """Scenario (ii): mixed-case inputs still hit the lowercased blacklist."""
    assert is_plugin_blacklisted(
        "Superpowers-Marketplace", "Superpowers", blacklist
    ) is True
    assert is_plugin_blacklisted(
        "SUPERPOWERS-MARKETPLACE", "SUPERPOWERS-DEV", blacklist
    ) is True
    # Also test the inverse: lowercase input, mixed-case blacklist entry.
    bl = [{"source": "Superpowers-Marketplace", "plugin_name": "Superpowers"}]
    assert is_plugin_blacklisted(
        "superpowers-marketplace", "superpowers", bl
    ) is True


def test_source_matches_but_plugin_name_does_not(blacklist):
    """Scenario (iii): same source, different plugin name → not blacklisted.

    This protects ``superpowers-chrome`` (and any other future superpowers-*
    plugins) from being collateral-damaged by the consolidation entries.
    """
    assert is_plugin_blacklisted(
        "superpowers-marketplace", "superpowers-chrome", blacklist
    ) is False
    assert is_plugin_blacklisted(
        "superpowers-marketplace", "totally-unrelated-plugin", blacklist
    ) is False


def test_different_source_not_affected(blacklist):
    """Different source (e.g. anthropic-curated) must not match obra entries."""
    assert is_plugin_blacklisted(
        "claude-plugins-official", "superpowers", blacklist
    ) is False
    assert is_plugin_blacklisted(
        "claude-plugins-dev", "superpowers", blacklist
    ) is False


def test_empty_and_none_blacklist_tolerated():
    """Empty list / ``None`` short-circuit to False."""
    assert is_plugin_blacklisted("anything", "anything", []) is False
    assert is_plugin_blacklisted("anything", "anything", None) is False


def test_malformed_blacklist_entries_ignored(blacklist):
    """Non-dict / missing-field entries don't crash the helper."""
    polluted = list(blacklist) + [
        "not-a-dict",
        None,
        {"source": "only-source"},
        {"plugin_name": "only-name"},
        {"source": 123, "plugin_name": "x"},
        {"source": "x", "plugin_name": None},
    ]
    assert is_plugin_blacklisted(
        "superpowers-marketplace", "superpowers", polluted
    ) is True
    assert is_plugin_blacklisted(
        "only-source", "anything", polluted
    ) is False


def test_blank_inputs_return_false(blacklist):
    assert is_plugin_blacklisted("", "superpowers", blacklist) is False
    assert is_plugin_blacklisted("superpowers-marketplace", "", blacklist) is False
    assert is_plugin_blacklisted("   ", "   ", blacklist) is False


# ---------------------------------------------------------------------------
# load_plugin_blacklist — file-loading tests (Scenario iv covered here)
# ---------------------------------------------------------------------------


def test_legacy_file_without_plugins_field_loads_empty(tmp_path):
    """Scenario (iv): legacy ``plugin_sources.json`` (only ``repos`` array) is
    not an error — loader returns ``[]`` and behavior degrades to repo-only
    skip logic (handled by the existing ``is_plugin_source()`` path).
    """
    legacy = tmp_path / "plugin_sources.json"
    legacy.write_text(
        json.dumps({"repos": ["https://github.com/obra/superpowers"]}),
        encoding="utf-8",
    )
    assert load_plugin_blacklist(_path_override=str(legacy)) == []


def test_missing_file_returns_empty(tmp_path):
    missing = tmp_path / "does-not-exist.json"
    assert load_plugin_blacklist(_path_override=str(missing)) == []


def test_malformed_json_returns_empty(tmp_path):
    bad = tmp_path / "plugin_sources.json"
    bad.write_text("{not valid json", encoding="utf-8")
    assert load_plugin_blacklist(_path_override=str(bad)) == []


def test_full_file_with_plugins_array_loads(tmp_path):
    """Happy path: file with both ``repos`` and ``plugins`` loads the plugin
    list verbatim, dropping malformed entries silently."""
    full = tmp_path / "plugin_sources.json"
    full.write_text(
        json.dumps(
            {
                "repos": ["https://github.com/obra/superpowers"],
                "plugins": [
                    {
                        "source": "superpowers-marketplace",
                        "plugin_name": "superpowers",
                    },
                    {
                        "source": "superpowers-marketplace",
                        "plugin_name": "superpowers-dev",
                    },
                    # Malformed — should be dropped.
                    {"source": "missing-plugin-name"},
                    "not a dict",
                ],
            }
        ),
        encoding="utf-8",
    )
    out = load_plugin_blacklist(_path_override=str(full))
    assert len(out) == 2
    names = {(e["source"], e["plugin_name"]) for e in out}
    assert names == {
        ("superpowers-marketplace", "superpowers"),
        ("superpowers-marketplace", "superpowers-dev"),
    }


def test_production_file_contains_initial_entries():
    """The production ``scripts/plugin_sources.json`` must contain the two
    consolidation entries this change is responsible for."""
    repo_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..")
    )
    prod_path = os.path.join(repo_root, "scripts", "plugin_sources.json")
    if not os.path.exists(prod_path):
        pytest.skip("production plugin_sources.json not present")
    entries = load_plugin_blacklist(_path_override=prod_path)
    pairs = {(e["source"].lower(), e["plugin_name"].lower()) for e in entries}
    assert ("superpowers-marketplace", "superpowers") in pairs
    assert ("superpowers-marketplace", "superpowers-dev") in pairs


# ---------------------------------------------------------------------------
# Integration: helper + loader end-to-end with a temp file (Scenario iv proof)
# ---------------------------------------------------------------------------


def test_end_to_end_legacy_file_does_not_filter_anything(tmp_path):
    """When a project still ships the pre-change ``plugin_sources.json``
    (no ``plugins`` field), nothing should be filtered — proving backwards
    compatibility for the sync scripts that always call
    ``is_plugin_blacklisted(..., load_plugin_blacklist())``.
    """
    legacy = tmp_path / "plugin_sources.json"
    legacy.write_text(
        json.dumps({"repos": ["https://github.com/obra/superpowers"]}),
        encoding="utf-8",
    )
    bl = load_plugin_blacklist(_path_override=str(legacy))
    # No plugin should ever be filtered with a legacy file.
    assert is_plugin_blacklisted(
        "superpowers-marketplace", "superpowers", bl
    ) is False
    assert is_plugin_blacklisted(
        "claude-plugins-dev", "anything", bl
    ) is False
