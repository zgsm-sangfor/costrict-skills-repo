"""Static-content checks ensuring all 4 platform evo command files reject
type:"plugin" catalog entries, plus the rubric doc documents the exclusion.

This is a regression guard — evo is an LLM-driven command spec, not Python
code, so we can only assert the rejection text is present in the spec.
"""

import pathlib

REPO = pathlib.Path(__file__).resolve().parent.parent

EVO_FILES = [
    REPO / "platforms/claude-code/commands/eac/evo.md",
    REPO / "platforms/opencode/command/eac-evo.md",
    REPO / "platforms/costrict/commands/eac/eac-evo.md",
    REPO / "platforms/vscode-costrict/commands/eac/eac-evo.md",
]

RUBRIC_DOC = REPO / "docs/wiki/evo-rubric.md"


def test_all_four_evo_files_exist():
    for path in EVO_FILES:
        assert path.exists(), f"missing evo command file: {path}"


def test_all_four_evo_files_reject_plugin_type():
    for path in EVO_FILES:
        content = path.read_text(encoding="utf-8")

        # Must list `plugin` in the refused-types section
        assert "plugin" in content.lower(), f"no plugin mention in {path}"

        # Must have an explicit `type is \`plugin\`` branch in Step 2
        assert "type is `plugin`" in content, (
            f"no explicit plugin type-check branch in {path}"
        )

        # Must point users to the upstream marketplace as the alternative
        assert "marketplace" in content.lower(), (
            f"no marketplace alternative mentioned in {path}"
        )

        # Must contain the bilingual error sentinel (English + Chinese)
        assert "evo does not support plugin entries" in content, (
            f"missing English plugin rejection sentence in {path}"
        )
        assert "不支持 plugin" in content, (
            f"missing Chinese plugin rejection sentence in {path}"
        )

        # Must NOT have removed the existing mcp rejection
        assert "type is `mcp`" in content, (
            f"existing mcp rejection branch was lost in {path}"
        )


def test_evo_files_reject_plugin_before_touching_disk():
    """The rejection branch must appear before Step 3 (Locate local copy)
    so plugin entries never trigger any filesystem read/write."""
    for path in EVO_FILES:
        content = path.read_text(encoding="utf-8")
        plugin_idx = content.find("type is `plugin`")
        step3_idx = content.find("### Step 3")
        assert plugin_idx != -1, f"no plugin branch in {path}"
        assert step3_idx != -1, f"no Step 3 heading in {path}"
        assert plugin_idx < step3_idx, (
            f"plugin rejection must come before Step 3 in {path}"
        )


def test_rubric_doc_documents_plugin_exclusion():
    assert RUBRIC_DOC.exists(), f"missing rubric doc: {RUBRIC_DOC}"
    content = RUBRIC_DOC.read_text(encoding="utf-8")

    # Must have a section/header acknowledging plugin is out of scope
    assert "plugin" in content.lower(), "rubric doc never mentions plugin"

    # Must mention the upstream marketplace as the redirection target
    assert (
        "marketplace" in content.lower() or "upstream" in content.lower()
    ), "rubric doc must redirect users to marketplace / upstream"

    # Must explicitly state evo does not support plugins
    lowered = content.lower()
    assert (
        "不支持" in content and "plugin" in lowered
    ) or "does not support" in lowered, (
        "rubric doc must state plugin is unsupported"
    )
