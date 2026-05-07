"""Tests for ``scripts/build_frontend_data.py`` plugin-related behavior.

Covers:
- ``plugins.json`` is always emitted (even when empty) and only contains
  entries whose ``type == "plugin"``.
- Per-type files are sorted by ``final_score`` descending.
- ``skills.json`` filters out entries whose ``bundled_in`` is non-empty
  (those skills are surfaced via their parent plugin).
- ``search-index.json`` semantics: bundled-in skills retain the
  ``bundled_in`` field so client-side search remains complete (this is
  enforced by ``slim_item`` carrying the field through).
- ``build_stats`` always seeds ``plugin: 0`` so the frontend has stable
  type-count keys before the plugin source has populated the catalog.
"""

import json
import pathlib
import sys

import pytest

sys.path.insert(
    0,
    str(pathlib.Path(__file__).resolve().parent.parent / "scripts"),
)

import build_frontend_data  # noqa: E402
from build_frontend_data import build_stats, build_type_files, slim_item  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures / factories
# ---------------------------------------------------------------------------


def _entry(id, type_, *, final_score=0, bundled_in=None, **extra):
    entry = {
        "id": id,
        "name": id,
        "type": type_,
        "description": f"{id} description",
        "source_url": f"https://github.com/owner/{id}",
        "final_score": final_score,
    }
    if bundled_in is not None:
        entry["bundled_in"] = bundled_in
    entry.update(extra)
    return entry


def _plugin(id, *, final_score=0, **extra):
    return _entry(id, "plugin", final_score=final_score, **extra)


def _skill(id, *, final_score=0, bundled_in=None, **extra):
    return _entry(
        id, "skill", final_score=final_score, bundled_in=bundled_in, **extra
    )


def _mcp(id, *, final_score=0, **extra):
    return _entry(id, "mcp", final_score=final_score, **extra)


def _read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def out_dir(tmp_path, monkeypatch):
    """Redirect ``build_frontend_data.OUT`` to a tmp directory for the test."""
    target = tmp_path / "api"
    target.mkdir()
    monkeypatch.setattr(build_frontend_data, "OUT", str(target))
    return target


# ---------------------------------------------------------------------------
# build_type_files — plugins.json contract
# ---------------------------------------------------------------------------


def test_plugins_json_emitted_with_only_plugin_entries(out_dir):
    """plugins.json is emitted and contains only ``type == "plugin"`` entries.
    Other type files contain only their respective types."""
    items = [
        _plugin("superpowers", final_score=80),
        _skill("some-skill", final_score=60),
        _mcp("some-mcp", final_score=70),
    ]

    build_type_files(items)

    plugins = _read_json(out_dir / "plugins.json")
    assert len(plugins) == 1
    assert plugins[0]["id"] == "superpowers"
    assert plugins[0]["type"] == "plugin"

    skills = _read_json(out_dir / "skills.json")
    assert [s["id"] for s in skills] == ["some-skill"]
    assert all(s["type"] == "skill" for s in skills)

    mcps = _read_json(out_dir / "mcp.json")
    assert [m["id"] for m in mcps] == ["some-mcp"]
    assert all(m["type"] == "mcp" for m in mcps)


def test_plugins_json_sorted_by_final_score_desc(out_dir):
    """plugins.json entries are sorted by ``final_score`` descending."""
    items = [
        _plugin("plugin-mid", final_score=70),
        _plugin("plugin-high", final_score=90),
        _plugin("plugin-low", final_score=50),
    ]

    build_type_files(items)

    plugins = _read_json(out_dir / "plugins.json")
    assert [p["id"] for p in plugins] == [
        "plugin-high",
        "plugin-mid",
        "plugin-low",
    ]
    assert [p["final_score"] for p in plugins] == [90, 70, 50]


def test_plugins_json_empty_when_no_plugins(out_dir):
    """plugins.json is still emitted (as ``[]``) when no plugin entries exist."""
    items = [
        _skill("only-skill", final_score=80),
        _mcp("only-mcp", final_score=70),
    ]

    build_type_files(items)

    plugins_path = out_dir / "plugins.json"
    assert plugins_path.exists(), "plugins.json must be emitted even when empty"
    plugins = _read_json(plugins_path)
    assert plugins == []


# ---------------------------------------------------------------------------
# build_type_files — skills.json filter behavior
# ---------------------------------------------------------------------------


def test_skills_json_excludes_bundled_in_entries(out_dir):
    """Skills with a non-empty ``bundled_in`` are filtered out of skills.json."""
    items = [
        _skill("bundled-a", bundled_in="obra-superpowers"),
        _skill("bundled-b", bundled_in="obra-superpowers"),
        _skill("standalone", bundled_in=None),
    ]

    build_type_files(items)

    skills = _read_json(out_dir / "skills.json")
    assert [s["id"] for s in skills] == ["standalone"]
    # Sanity: the filter relies on ``bundled_in`` truthiness — confirm the
    # remaining entry does not carry that field.
    assert "bundled_in" not in skills[0]


# ---------------------------------------------------------------------------
# slim_item — search-index parity for bundled-in skills
# ---------------------------------------------------------------------------


def test_search_index_preserves_bundled_in_skills():
    """The full search index (built by ``slim_item`` over all entries) keeps
    bundled-in skills, AND those entries retain the ``bundled_in`` field."""
    items = [
        _skill("bundled-a", bundled_in="obra-superpowers"),
        _skill("bundled-b", bundled_in="obra-superpowers"),
        _skill("standalone", bundled_in=None),
    ]

    # Mimic what a search-index build would do: slim every entry without the
    # per-type ``bundled_in`` filter that ``build_type_files`` applies.
    slimmed = [slim_item(i) for i in items]

    assert len(slimmed) == 3
    by_id = {s["id"]: s for s in slimmed}
    assert by_id["bundled-a"]["bundled_in"] == "obra-superpowers"
    assert by_id["bundled-b"]["bundled_in"] == "obra-superpowers"
    # Standalone skill has no bundled_in.
    assert "bundled_in" not in by_id["standalone"]


# ---------------------------------------------------------------------------
# build_stats — plugin count seeded
# ---------------------------------------------------------------------------


def test_stats_includes_plugin_count():
    """``byType`` reflects the actual plugin count when plugins are present."""
    items = (
        [_plugin(f"plug-{i}") for i in range(5)]
        + [_skill(f"skill-{i}") for i in range(10)]
    )

    stats = build_stats(items)

    assert stats["total"] == 15
    assert stats["byType"]["plugin"] == 5
    assert stats["byType"]["skill"] == 10


def test_stats_includes_zero_plugin_when_none():
    """``byType`` always carries a ``plugin`` key, even when no plugin entries
    exist — the frontend relies on stable type-count keys."""
    items = [
        _skill("only-skill"),
        _mcp("only-mcp"),
    ]

    stats = build_stats(items)

    assert "plugin" in stats["byType"], (
        "byType must always include 'plugin' key (default 0)"
    )
    assert stats["byType"]["plugin"] == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
