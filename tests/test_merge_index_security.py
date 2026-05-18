"""Integration tests for the security block lifecycle in merge_index.

Verifies that:
- catalog_lifecycle preserves an existing entry.security block across rebuild
  when the new sync data lacks one (overlay_preserved_fields).
- A fresh security_scan result produced inside enrich_entries() wins over the
  preserved old block.
- scoring_governor does not touch entry.security (passes through unchanged).
"""

from __future__ import annotations

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


def _make_entry(id, type="skill", name="Test", source_url="https://github.com/t/x"):
    return {
        "id": id,
        "name": name,
        "type": type,
        "description": "A test entry",
        "source_url": source_url,
        "stars": 10,
        "category": "tooling",
        "tags": [],
        "tech_stack": [],
        "install": {"method": "manual"},
        "source": "test",
        "last_synced": "2026-05-18",
        "pushed_at": "2026-05-01T00:00:00Z",
    }


def _make_security_block(risk_level="low", verdict="safe", summary="无外部 IO"):
    return {
        "risk_level": risk_level,
        "verdict": verdict,
        "red_flags": [],
        "permissions": {"files": [], "network": [], "commands": []},
        "summary": summary,
        "recommendations": [],
        "scan_model": "test-judge",
        "rubric_version": "1.abcd1234",
        "content_hash": "ch" * 32,
        "scanned_at": "2026-05-01T00:00:00+00:00",
    }


class TestMergeIndexSecurityLifecycle(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        for t in merge_index.TYPES:
            os.makedirs(os.path.join(self.tmpdir, t), exist_ok=True)
        self._orig_catalog_dir = merge_index.CATALOG_DIR
        merge_index.CATALOG_DIR = self.tmpdir

    def tearDown(self):
        merge_index.CATALOG_DIR = self._orig_catalog_dir

    def _write_index(self, type_name, entries, filename="index.json"):
        path = os.path.join(self.tmpdir, type_name, filename)
        with open(path, "w") as f:
            json.dump(entries, f)

    def _write_existing_output(self, entries):
        path = os.path.join(self.tmpdir, "index.json")
        with open(path, "w") as f:
            json.dump(entries, f)

    def _read_output(self):
        path = os.path.join(self.tmpdir, "index.json")
        with open(path) as f:
            return json.load(f)

    def test_existing_security_block_preserved_when_enrichment_skipped(self):
        """Prior security block survives a rebuild where enrich_entries does
        not produce a new security result (overlay_preserved_fields path)."""
        # Sync re-emits the entry without a security block.
        new_entry = _make_entry("entry-1", type="skill")
        self._write_index("skills", [new_entry])

        # Prior catalog had this entry with a security block.
        old_entry = _make_entry("entry-1", type="skill")
        old_entry["security"] = _make_security_block(risk_level="low")
        self._write_existing_output([old_entry])

        # Enrichment is a no-op (does not produce new security); governance
        # passes entries through unchanged.
        with unittest.mock.patch("merge_index.enrich_entries") as mock_enrich, \
             unittest.mock.patch("merge_index.apply_governance") as mock_gov:
            mock_enrich.side_effect = lambda x: x
            mock_gov.side_effect = lambda x, **kw: x
            merge_index.merge()

        out = self._read_output()
        self.assertEqual(len(out), 1)
        sec = out[0].get("security")
        self.assertIsNotNone(sec)
        self.assertEqual(sec["risk_level"], "low")
        self.assertEqual(sec["verdict"], "safe")
        # All audit fields preserved
        self.assertEqual(sec["scan_model"], "test-judge")
        self.assertEqual(sec["content_hash"], "ch" * 32)

    def test_fresh_security_result_overwrites_preserved_block(self):
        """When enrich_entries produces a fresh security block, the new one
        wins (overlay_preserved_fields only fills in missing fields)."""
        new_entry = _make_entry("entry-1", type="skill")
        self._write_index("skills", [new_entry])

        old_entry = _make_entry("entry-1", type="skill")
        old_entry["security"] = _make_security_block(risk_level="low", summary="旧版评估")
        self._write_existing_output([old_entry])

        def fresh_enrich(entries):
            # Simulate security_scan_and_map writing a NEW security block.
            for e in entries:
                e["security"] = _make_security_block(
                    risk_level="medium",
                    verdict="caution",
                    summary="新版评估",
                )

        with unittest.mock.patch("merge_index.enrich_entries", side_effect=fresh_enrich), \
             unittest.mock.patch("merge_index.apply_governance") as mock_gov:
            mock_gov.side_effect = lambda x, **kw: x
            merge_index.merge()

        out = self._read_output()
        sec = out[0]["security"]
        self.assertEqual(sec["risk_level"], "medium")
        self.assertEqual(sec["verdict"], "caution")
        self.assertEqual(sec["summary"], "新版评估")

    def test_governor_does_not_touch_security(self):
        """scoring_governor passes entry.security through unchanged."""
        new_entry = _make_entry("entry-1", type="skill")
        new_entry["security"] = _make_security_block(risk_level="medium", verdict="caution")
        self._write_index("skills", [new_entry])

        # No existing catalog → no overlay; entry already has its security
        # block from the sync step (only realistic in test, but exercises the
        # passthrough behaviour of scoring_governor).
        with unittest.mock.patch("merge_index.enrich_entries") as mock_enrich:
            mock_enrich.side_effect = lambda x: x
            # Use the real apply_governance — it must NOT strip security.
            merge_index.merge()

        out = self._read_output()
        sec = out[0]["security"]
        self.assertEqual(sec["risk_level"], "medium")
        self.assertEqual(sec["verdict"], "caution")

    def test_full_security_block_keys_preserved(self):
        """All 10 keys (6 LLM + 4 audit) survive merge_index roundtrip."""
        new_entry = _make_entry("entry-1", type="skill")
        new_entry["security"] = _make_security_block()
        self._write_index("skills", [new_entry])

        with unittest.mock.patch("merge_index.enrich_entries") as mock_enrich, \
             unittest.mock.patch("merge_index.apply_governance") as mock_gov:
            mock_enrich.side_effect = lambda x: x
            mock_gov.side_effect = lambda x, **kw: x
            merge_index.merge()

        out = self._read_output()
        sec = out[0]["security"]
        for key in (
            "risk_level",
            "verdict",
            "red_flags",
            "permissions",
            "summary",
            "recommendations",
            "scan_model",
            "rubric_version",
            "content_hash",
            "scanned_at",
        ):
            self.assertIn(key, sec, f"missing security key: {key}")


if __name__ == "__main__":
    unittest.main()
