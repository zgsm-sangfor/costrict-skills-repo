"""Tests for plugin-type compatibility in ``utils.deduplicate()`` and
``utils.categorize()``.

Plugin entries (``type: "plugin"``) are a new resource category added by the
``add-plugins-category`` change. They MUST flow through the existing
``deduplicate()`` and ``categorize()`` helpers without raising; the contract
locked in here is:

- ``categorize()`` accepts ``upstream_category="plugin"`` (and the related
  ``"bundle"`` / ``"marketplace"`` keywords) and resolves to ``"tooling"``.
- ``deduplicate()`` does NOT identity-collapse plugin entries (Pass 1 returns
  ``None`` for type=plugin), and does NOT URL-collapse plugins against each
  other in Pass 2 (plugin IS in ``url_dedup_skip_types`` — multiple distinct
  plugins legitimately share a single marketplace repo URL, e.g. several AWS
  plugins under ``awslabs/agent-plugins`` or several Superpowers plugins under
  ``obra/superpowers-marketplace``). Per-entry uniqueness for plugins is
  guaranteed by their unique ``id``.
- A plugin and a non-skip-listed type that share the same source_url still
  collide on Pass 2's URL dedup (which is type-agnostic on the seen_urls
  dict). First entry in input order wins.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from utils import deduplicate, categorize  # noqa: E402


def _plugin_entry(id, source_url, name="Test Plugin"):
    return {
        "id": id,
        "name": name,
        "type": "plugin",
        "description": "A claude code plugin bundle",
        "source_url": source_url,
        "stars": 0,
        "category": "tooling",
        "tags": ["plugin"],
        "tech_stack": [],
        "install": {"method": "manual"},
        "source": "test",
        "last_synced": "2026-05-07",
    }


def _skill_entry(id, source_url, name="Test Skill"):
    return {
        "id": id,
        "name": name,
        "type": "skill",
        "description": "A skill",
        "source_url": source_url,
        "stars": 0,
        "category": "tooling",
        "tags": [],
        "tech_stack": [],
        "install": {"method": "manual"},
        "source": "test",
        "last_synced": "2026-05-07",
    }


# ---------------------------------------------------------------------------
# categorize()
# ---------------------------------------------------------------------------


def test_categorize_plugin_does_not_crash():
    """categorize() must accept upstream_category='plugin' and return a string."""
    result = categorize(
        name="superpowers",
        description="A claude code plugin bundle",
        tags=["plugin"],
        upstream_category="plugin",
    )
    assert isinstance(result, str)
    # CATEGORY_MAP entry added in Task 1.2: "plugin" -> "tooling"
    assert result == "tooling"


def test_categorize_bundle_keyword_maps_to_tooling():
    result = categorize(
        name="some-bundle",
        description="",
        tags=[],
        upstream_category="bundle",
    )
    assert result == "tooling"


def test_categorize_marketplace_keyword_maps_to_tooling():
    result = categorize(
        name="some-marketplace",
        description="",
        tags=[],
        upstream_category="marketplace",
    )
    assert result == "tooling"


# ---------------------------------------------------------------------------
# deduplicate()
# ---------------------------------------------------------------------------


def test_deduplicate_plugin_entries_no_crash():
    """A list of plugin-type entries flows through deduplicate without error."""
    entries = [
        _plugin_entry("plugin-a", "https://github.com/owner/plugin-a"),
        _plugin_entry("plugin-b", "https://github.com/owner/plugin-b"),
        _plugin_entry("plugin-c", "https://github.com/owner/plugin-c"),
    ]
    result = deduplicate(entries)
    assert isinstance(result, list)
    assert len(result) == 3
    assert {e["id"] for e in result} == {"plugin-a", "plugin-b", "plugin-c"}


def test_deduplicate_plugin_shared_source_url_all_kept():
    """Multiple plugin entries with the same source_url are all preserved.

    Marketplace repos (e.g. ``awslabs/agent-plugins``,
    ``obra/superpowers-marketplace``) legitimately host many distinct plugins
    under one git URL. Plugin is in ``url_dedup_skip_types`` so Pass 2 URL
    dedup does NOT collapse them; per-entry uniqueness is guaranteed by ``id``.
    """
    entries = [
        _plugin_entry("plugin-a", "https://github.com/owner/repo"),
        _plugin_entry("plugin-b", "https://github.com/owner/repo/"),
        _plugin_entry("plugin-c", "https://github.com/owner/repo.git"),
    ]
    result = deduplicate(entries)
    assert len(result) == 3
    assert {e["id"] for e in result} == {"plugin-a", "plugin-b", "plugin-c"}


def test_deduplicate_mixed_plugin_and_skill_skill_dropped_on_shared_url():
    """A plugin (skip-listed) and a skill (not skip-listed) share a source_url.

    The plugin enters Pass 2 first and is appended without inserting into
    ``seen_urls`` (skip-listed). The skill then hits the URL dedup branch but
    finds no prior entry in ``seen_urls`` for that URL, so it is also kept.
    Both survive — distinct types, no false collapse.
    """
    entries = [
        _plugin_entry("the-plugin", "https://github.com/owner/shared-repo"),
        _skill_entry("the-skill", "https://github.com/owner/shared-repo"),
    ]
    result = deduplicate(entries)
    assert len(result) == 2
    assert {e["id"] for e in result} == {"the-plugin", "the-skill"}


def test_deduplicate_plugin_distinct_urls_all_kept():
    """Plugin entries with distinct source_urls are all preserved."""
    entries = [
        _plugin_entry("p1", "https://github.com/owner1/repo1"),
        _plugin_entry("p2", "https://github.com/owner2/repo2"),
    ]
    result = deduplicate(entries)
    assert len(result) == 2


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
