import json
import os
import sys
import tempfile
import unittest

SCRIPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts"))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import merge_index  # noqa: E402


def _make_entry(id, name="Test", type="mcp", source_url="https://github.com/test/test",
                category="tooling", stars=10, description="A test entry",
                pushed_at="2026-03-01T00:00:00Z"):
    return {
        "id": id,
        "name": name,
        "type": type,
        "description": description,
        "source_url": source_url,
        "stars": stars,
        "category": category,
        "tags": [],
        "tech_stack": [],
        "install": {"method": "manual"},
        "source": "test",
        "last_synced": "2026-03-30",
        "pushed_at": pushed_at,
    }


class TestMergeIndex(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        # Create type subdirectories
        for t in merge_index.TYPES:
            os.makedirs(os.path.join(self.tmpdir, t), exist_ok=True)
        # Patch CATALOG_DIR
        self._orig_catalog_dir = merge_index.CATALOG_DIR
        merge_index.CATALOG_DIR = self.tmpdir

    def tearDown(self):
        merge_index.CATALOG_DIR = self._orig_catalog_dir

    def _write_index(self, type_name, entries, filename="index.json"):
        path = os.path.join(self.tmpdir, type_name, filename)
        with open(path, "w") as f:
            json.dump(entries, f)

    def _read_output(self):
        path = os.path.join(self.tmpdir, "index.json")
        with open(path) as f:
            return json.load(f)

    def test_basic_merge(self):
        self._write_index("mcp", [_make_entry("a", source_url="https://github.com/t/a")])
        self._write_index("skills", [_make_entry("b", type="skill", source_url="https://github.com/t/b")])

        merge_index.merge()
        result = self._read_output()

        self.assertEqual(len(result), 2)
        ids = {r["id"] for r in result}
        self.assertEqual(ids, {"a", "b"})

    def test_dedup_id_keeps_first(self):
        self._write_index("mcp", [_make_entry("dup", name="First", source_url="https://github.com/t/first")])
        self._write_index("mcp", [_make_entry("dup", name="Second", source_url="https://github.com/t/second")],
                          filename="curated.json")

        merge_index.merge()
        result = self._read_output()

        dup_entries = [r for r in result if r["id"] == "dup"]
        self.assertEqual(len(dup_entries), 1)
        self.assertEqual(dup_entries[0]["name"], "First")

    def test_health_score_present(self):
        self._write_index("mcp", [_make_entry("h1", source_url="https://github.com/t/h1")])

        merge_index.merge()
        result = self._read_output()

        self.assertIn("health", result[0])
        self.assertIn("score", result[0]["health"])
        self.assertIn("signals", result[0]["health"])

    def test_sorted_by_health_desc(self):
        self._write_index("mcp", [
            _make_entry("low", stars=0, pushed_at=None, source_url="https://github.com/t/low"),
            _make_entry("high", stars=5000, pushed_at="2026-03-29T00:00:00Z",
                        source_url="https://github.com/t/high"),
        ])

        merge_index.merge()
        result = self._read_output()

        self.assertEqual(result[0]["id"], "high")
        self.assertEqual(result[1]["id"], "low")

    def test_invalid_category_fixed(self):
        entry = _make_entry("bad-cat", category="other", source_url="https://github.com/t/bad",
                            name="docker-deploy", description="Deploy containers with Docker")
        self._write_index("mcp", [entry])

        merge_index.merge()
        result = self._read_output()

        self.assertNotEqual(result[0]["category"], "other")

    def test_empty_type_dir_no_crash(self):
        # Only mcp has data, others are empty dirs
        self._write_index("mcp", [_make_entry("only", source_url="https://github.com/t/only")])

        merge_index.merge()
        result = self._read_output()

        self.assertEqual(len(result), 1)


if __name__ == "__main__":
    unittest.main()
