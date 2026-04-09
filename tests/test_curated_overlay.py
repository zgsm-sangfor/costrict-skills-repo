import json
import os
import sys
import tempfile
import unittest
import unittest.mock

SCRIPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts"))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import merge_index  # noqa: E402


def _make_entry(
    id,
    name="Test",
    type="mcp",
    source_url="https://github.com/test/test",
    category="tooling",
    stars=10,
    description="A test entry",
    tags=None,
    tech_stack=None,
):
    return {
        "id": id,
        "name": name,
        "type": type,
        "description": description,
        "source_url": source_url,
        "stars": stars,
        "category": category,
        "tags": tags if tags is not None else [],
        "tech_stack": tech_stack if tech_stack is not None else [],
        "install": {"method": "manual"},
        "source": "test",
        "last_synced": "2026-03-30",
        "pushed_at": "2026-03-01T00:00:00Z",
    }


class TestCuratedOverlay(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        for t in merge_index.TYPES:
            os.makedirs(os.path.join(self.tmpdir, t), exist_ok=True)
        self._orig_catalog_dir = merge_index.CATALOG_DIR
        merge_index.CATALOG_DIR = self.tmpdir

    def tearDown(self):
        merge_index.CATALOG_DIR = self._orig_catalog_dir

    def _write_curated(self, type_name, entries):
        path = os.path.join(self.tmpdir, type_name, "curated.json")
        with open(path, "w") as f:
            json.dump(entries, f)

    def _call_overlay(self, entries):
        """Call overlay_curated_fields with CATALOG_DIR pointing at tmpdir."""
        return merge_index.overlay_curated_fields(entries)

    # ------------------------------------------------------------------
    # Scenario: tech_stack merged from curated (id match)
    # ------------------------------------------------------------------
    def test_tech_stack_merged_from_curated_id_match(self):
        entry = _make_entry("tool-a", source_url="https://github.com/org/a",
                            tech_stack=["python"])
        curated = _make_entry("tool-a", source_url="https://github.com/org/a",
                              tech_stack=["react", "typescript"])

        self._write_curated("mcp", [curated])
        result = self._call_overlay([entry])

        matched = next(e for e in result if e["id"] == "tool-a")
        # curated values first, then existing, deduplicated
        self.assertEqual(matched["tech_stack"], ["react", "typescript", "python"])

    # ------------------------------------------------------------------
    # Scenario: tags merged from curated (id match)
    # ------------------------------------------------------------------
    def test_tags_merged_from_curated_id_match(self):
        entry = _make_entry("tool-b", source_url="https://github.com/org/b",
                            tags=["existing-tag"])
        curated = _make_entry("tool-b", source_url="https://github.com/org/b",
                              tags=["curated-tag", "existing-tag"])

        self._write_curated("mcp", [curated])
        result = self._call_overlay([entry])

        matched = next(e for e in result if e["id"] == "tool-b")
        # existing-tag already present, curated-tag appended, no duplicates
        self.assertIn("curated-tag", matched["tags"])
        self.assertIn("existing-tag", matched["tags"])
        self.assertEqual(matched["tags"].count("existing-tag"), 1)

    # ------------------------------------------------------------------
    # Scenario: source_url fallback matching
    # ------------------------------------------------------------------
    def test_source_url_fallback_matching(self):
        entry = _make_entry("auto-id", source_url="https://github.com/org/c",
                            tech_stack=[])
        # curated has a different id but same source_url
        curated = _make_entry("curated-id", source_url="https://github.com/org/c",
                              tech_stack=["docker"])

        self._write_curated("mcp", [curated])
        result = self._call_overlay([entry])

        # The original entry (auto-id) should have docker merged in
        matched = next(e for e in result if e["id"] == "auto-id")
        self.assertIn("docker", matched["tech_stack"])
        # curated-id should NOT appear as a new entry (it matched via URL)
        ids = [e["id"] for e in result]
        self.assertNotIn("curated-id", ids)

    # ------------------------------------------------------------------
    # Scenario: Non-supplementary fields NOT overwritten
    # ------------------------------------------------------------------
    def test_non_supplementary_fields_not_overwritten(self):
        entry = _make_entry(
            "tool-d",
            name="Original Name",
            description="Original description",
            stars=999,
            source_url="https://github.com/org/d",
        )
        entry["install"] = {"method": "mcp_config"}
        entry["evaluation"] = {"coding_relevance": 5}

        curated = _make_entry(
            "tool-d",
            name="Curated Name",
            description="Curated description",
            stars=1,
            source_url="https://github.com/org/d",
        )
        curated["install"] = {"method": "manual"}
        curated["evaluation"] = {"coding_relevance": 1}

        self._write_curated("mcp", [curated])
        result = self._call_overlay([entry])

        matched = next(e for e in result if e["id"] == "tool-d")
        self.assertEqual(matched["name"], "Original Name")
        self.assertEqual(matched["description"], "Original description")
        self.assertEqual(matched["stars"], 999)
        self.assertEqual(matched["source_url"], "https://github.com/org/d")
        self.assertEqual(matched["install"]["method"], "mcp_config")
        self.assertEqual(matched["evaluation"]["coding_relevance"], 5)

    # ------------------------------------------------------------------
    # Scenario: New curated entry appended when no match exists
    # ------------------------------------------------------------------
    def test_new_curated_entry_appended_when_no_match(self):
        entry = _make_entry("existing", source_url="https://github.com/org/existing")
        curated_new = _make_entry("brand-new",
                                  source_url="https://github.com/org/brand-new",
                                  tech_stack=["vue"])

        self._write_curated("mcp", [curated_new])
        result = self._call_overlay([entry])

        ids = [e["id"] for e in result]
        self.assertIn("existing", ids)
        self.assertIn("brand-new", ids)
        self.assertEqual(len(result), 2)

        appended = next(e for e in result if e["id"] == "brand-new")
        self.assertEqual(appended["tech_stack"], ["vue"])

    # ------------------------------------------------------------------
    # Scenario: Double overlay produces same output (idempotency)
    # ------------------------------------------------------------------
    def test_double_overlay_is_idempotent(self):
        entry = _make_entry("tool-e", source_url="https://github.com/org/e",
                            tags=["existing"], tech_stack=["python"])
        curated = _make_entry("tool-e", source_url="https://github.com/org/e",
                              tags=["extra-tag"], tech_stack=["react"])

        self._write_curated("mcp", [curated])

        first_pass = self._call_overlay([entry])
        # Deep-copy the first result to avoid mutation issues
        import copy
        first_pass_copy = copy.deepcopy(first_pass)

        second_pass = self._call_overlay(first_pass_copy)

        # Same number of entries
        self.assertEqual(len(first_pass), len(second_pass))

        # Same tech_stack (no duplicates introduced)
        e1 = next(e for e in first_pass if e["id"] == "tool-e")
        e2 = next(e for e in second_pass if e["id"] == "tool-e")
        self.assertEqual(sorted(e1["tech_stack"]), sorted(e2["tech_stack"]))
        self.assertEqual(sorted(e1["tags"]), sorted(e2["tags"]))

    # ------------------------------------------------------------------
    # Integration: overlay runs inside merge() before enrichment
    # ------------------------------------------------------------------
    def test_overlay_runs_in_merge(self):
        """overlay_curated_fields is called during merge, enriching entries."""
        index_entry = _make_entry("merge-test",
                                  source_url="https://github.com/org/merge-test",
                                  tech_stack=[])
        index_path = os.path.join(self.tmpdir, "mcp", "index.json")
        with open(index_path, "w") as f:
            json.dump([index_entry], f)

        curated_entry = _make_entry("merge-test",
                                    source_url="https://github.com/org/merge-test",
                                    tech_stack=["typescript", "nodejs"])
        self._write_curated("mcp", [curated_entry])

        with unittest.mock.patch("merge_index.enrich_entries") as mock_enrich, \
             unittest.mock.patch("merge_index.apply_governance") as mock_gov:
            mock_enrich.side_effect = lambda x: x
            mock_gov.side_effect = lambda x: x
            merge_index.merge()

        output_path = os.path.join(self.tmpdir, "index.json")
        with open(output_path) as f:
            result = json.load(f)

        matched = next(e for e in result if e["id"] == "merge-test")
        self.assertIn("typescript", matched["tech_stack"])
        self.assertIn("nodejs", matched["tech_stack"])


if __name__ == "__main__":
    unittest.main()
