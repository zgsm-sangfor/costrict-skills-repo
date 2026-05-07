"""Tests for ``merge_index._apply_bundled_in_annotations()``.

The post-merge annotator scans plugin entries' ``bundle.skills_namespaces``
and stamps ``bundled_in: <plugin-id>`` onto matching skill entries. Match
priority (first hit wins):

  1. Skill ``namespace`` exact equals the namespace string.
  2. Skill ``id`` exact equals the namespace string.
  3. Slug fallback: skill ``id`` equals the namespace with ``:`` replaced by ``-``.

Orphan namespaces (no skill matches) emit a WARNING; a single summary INFO
line is always emitted at the end. See spec ``plugin-bundle-dedup``.
"""

import logging
import pathlib
import sys

import pytest

sys.path.insert(
    0,
    str(pathlib.Path(__file__).resolve().parent.parent / "scripts"),
)

from merge_index import _apply_bundled_in_annotations  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures / factories
# ---------------------------------------------------------------------------


def _plugin(id, namespaces=None, *, has_bundle=True):
    """Build a minimal plugin entry. ``namespaces=None`` + has_bundle=False
    yields a plugin with no bundle field at all."""
    entry = {
        "id": id,
        "type": "plugin",
        "name": id,
        "source_url": f"https://github.com/owner/{id}",
    }
    if has_bundle:
        entry["bundle"] = {"skills_namespaces": namespaces or []}
    return entry


def _skill(id, *, namespace=None):
    entry = {
        "id": id,
        "type": "skill",
        "name": id,
        "source_url": f"https://github.com/owner/{id}",
    }
    if namespace is not None:
        entry["namespace"] = namespace
    return entry


def _rule(id):
    return {
        "id": id,
        "type": "rule",
        "name": id,
        "source_url": f"https://github.com/owner/{id}",
    }


def _mcp(id):
    return {
        "id": id,
        "type": "mcp",
        "name": id,
        "source_url": f"https://github.com/owner/{id}",
    }


# Tests use the ``utils`` logger that ``merge_index`` imports as ``logger``.
# pytest's ``caplog`` fixture intercepts ALL loggers by default, but we still
# bump the level so DEBUG records also flow through where asserted.
LOGGER_NAME = "utils"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_annotates_skill_via_namespace_match():
    """Skill with matching ``namespace`` field gets ``bundled_in`` set."""
    skill = _skill("brainstorming", namespace="superpowers:brainstorming")
    plugin = _plugin("superpowers", ["superpowers:brainstorming"])
    entries = [plugin, skill]

    _apply_bundled_in_annotations(entries)

    assert skill.get("bundled_in") == "superpowers"


def test_annotates_skill_via_id_slug_match():
    """Skill ``id == "superpowers-brainstorming"`` is matched via the
    ``:`` → ``-`` slug fallback."""
    skill = _skill("superpowers-brainstorming")  # no explicit namespace
    plugin = _plugin("superpowers", ["superpowers:brainstorming"])
    entries = [plugin, skill]

    _apply_bundled_in_annotations(entries)

    assert skill.get("bundled_in") == "superpowers"


def test_orphan_namespace_logs_warning(caplog):
    """A namespace that matches no skill emits a WARNING naming both
    the plugin id and the orphan namespace."""
    plugin = _plugin("superpowers", ["superpowers:nonexistent"])
    entries = [plugin]  # no skill at all

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        _apply_bundled_in_annotations(entries)

    warnings = [
        r for r in caplog.records
        if r.levelno == logging.WARNING
        and "orphan namespace" in r.getMessage()
    ]
    assert warnings, "expected at least one orphan-namespace WARNING"
    msg = warnings[0].getMessage()
    assert "superpowers" in msg
    assert "superpowers:nonexistent" in msg


def test_empty_skills_namespaces_no_op(caplog):
    """Empty ``skills_namespaces: []`` is a no-op: no skill mutated, no
    WARNING. The function may emit DEBUG (skipping) but never raises."""
    skill = _skill("brainstorming", namespace="superpowers:brainstorming")
    plugin = _plugin("superpowers", [])  # empty list
    entries = [plugin, skill]

    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        _apply_bundled_in_annotations(entries)

    assert "bundled_in" not in skill
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    # No orphan-namespace WARNINGs from this function.
    assert not [w for w in warnings if "orphan namespace" in w.getMessage()]


def test_missing_bundle_field_no_crash(caplog):
    """A plugin with no ``bundle`` field at all is handled gracefully."""
    skill = _skill("brainstorming", namespace="superpowers:brainstorming")
    plugin = _plugin("superpowers", has_bundle=False)
    entries = [plugin, skill]

    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        result = _apply_bundled_in_annotations(entries)

    # No annotation, no exception.
    assert "bundled_in" not in skill
    assert result is entries  # function returns the same list


def test_summary_log_emitted(caplog):
    """The summary INFO line ``post-merge: scanned N plugins, annotated M
    skills with bundled_in, found K orphan namespaces`` is always emitted."""
    skill_ok = _skill("brainstorming", namespace="superpowers:brainstorming")
    plugin = _plugin(
        "superpowers",
        ["superpowers:brainstorming", "superpowers:ghost"],  # 1 hit, 1 orphan
    )
    entries = [plugin, skill_ok]

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        _apply_bundled_in_annotations(entries)

    summaries = [
        r for r in caplog.records
        if r.levelno == logging.INFO
        and "scanned" in r.getMessage()
        and "annotated" in r.getMessage()
        and "orphan namespaces" in r.getMessage()
    ]
    assert summaries, "expected the post-merge summary INFO line"
    msg = summaries[0].getMessage()
    # 1 plugin scanned, 1 skill annotated, 1 orphan namespace.
    assert "1 plugins" in msg
    assert "1 skills" in msg
    assert "1 orphan" in msg


def test_non_plugin_entries_ignored():
    """Mixed catalog with no plugin entries: nothing gets annotated."""
    skill = _skill("brainstorming", namespace="superpowers:brainstorming")
    rule = _rule("some-rule")
    mcp = _mcp("some-mcp")
    entries = [skill, rule, mcp]

    _apply_bundled_in_annotations(entries)

    assert "bundled_in" not in skill
    # Other types are untouched too.
    assert "bundled_in" not in rule
    assert "bundled_in" not in mcp


def test_skill_unmatched_keeps_no_bundled_in():
    """A skill not referenced by any plugin must NOT receive a
    ``bundled_in`` field (absent, not null)."""
    bundled_skill = _skill(
        "brainstorming", namespace="superpowers:brainstorming"
    )
    standalone_skill = _skill("lonely-skill", namespace="other:lonely-skill")
    plugin = _plugin("superpowers", ["superpowers:brainstorming"])
    entries = [plugin, bundled_skill, standalone_skill]

    _apply_bundled_in_annotations(entries)

    assert bundled_skill.get("bundled_in") == "superpowers"
    assert "bundled_in" not in standalone_skill


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
