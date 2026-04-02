"""Tests for scripts/generate_pages.py — static API generation."""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from generate_pages import generate, sanitize_id, make_lightweight


def _make_entry(id_, type_="mcp", stars=100, **kwargs):
    entry = {
        "id": id_,
        "name": kwargs.get("name", id_),
        "type": type_,
        "description": kwargs.get("description", f"Desc for {id_}"),
        "description_zh": kwargs.get("description_zh", ""),
        "source_url": kwargs.get("source_url", f"https://github.com/t/{id_}"),
        "stars": stars,
        "category": kwargs.get("category", "tooling"),
        "tags": kwargs.get("tags", ["test"]),
        "tech_stack": kwargs.get("tech_stack", []),
        "install": kwargs.get("install", {"method": "manual"}),
        "evaluation": {"composite_score": 70, "reason": "x" * 100},
        "health": {"popularity": 60},
    }
    entry.update({k: v for k, v in kwargs.items() if k not in entry})
    return entry


class TestSanitizeId(unittest.TestCase):
    def test_plain_id(self):
        self.assertEqual(sanitize_id("my-server"), "my-server")

    def test_at_symbol_removed(self):
        self.assertEqual(sanitize_id("@scope/name"), "scope--name")

    def test_slash_replaced(self):
        self.assertEqual(sanitize_id("org/repo"), "org--repo")

    def test_special_chars(self):
        result = sanitize_id("a b!c#d")
        self.assertRegex(result, r"^[\w\-\.]+$")


class TestMakeLightweight(unittest.TestCase):
    def test_includes_search_fields(self):
        entry = _make_entry("x")
        light = make_lightweight(entry)
        for field in ("id", "name", "type", "category", "tags", "stars",
                       "description", "source_url", "install_method"):
            self.assertIn(field, light)

    def test_excludes_heavy_fields(self):
        entry = _make_entry("x")
        light = make_lightweight(entry)
        self.assertNotIn("evaluation", light)
        self.assertNotIn("health", light)

    def test_install_method_extracted(self):
        entry = _make_entry("x", install={"method": "mcp_config", "config": {}})
        light = make_lightweight(entry)
        self.assertEqual(light["install_method"], "mcp_config")


class TestGenerate(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.output_dir = os.path.join(self.tmpdir, "api")
        self.catalog_dir = os.path.join(self.tmpdir, "catalog")
        os.makedirs(self.catalog_dir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir)

    def _write_index(self, entries):
        with open(os.path.join(self.catalog_dir, "index.json"), "w") as f:
            json.dump(entries, f)

    def _write_search_index(self, entries):
        with open(os.path.join(self.catalog_dir, "search-index.json"), "w") as f:
            json.dump(entries, f)

    def _run(self, entries):
        self._write_index(entries)
        self._write_search_index([make_lightweight(e) for e in entries])
        import generate_pages
        orig = generate_pages.CATALOG_DIR
        generate_pages.CATALOG_DIR = self.catalog_dir
        try:
            generate(self.output_dir)
        finally:
            generate_pages.CATALOG_DIR = orig

    def test_file_tree_structure(self):
        entries = [_make_entry("a", type_="mcp"), _make_entry("b", type_="skill")]
        self._run(entries)
        v1 = os.path.join(self.output_dir, "v1")
        self.assertTrue(os.path.isfile(os.path.join(v1, "search-index.json")))
        self.assertTrue(os.path.isfile(os.path.join(v1, "mcp", "index.json")))
        self.assertTrue(os.path.isfile(os.path.join(v1, "mcp", "a.json")))
        self.assertTrue(os.path.isfile(os.path.join(v1, "skill", "index.json")))
        self.assertTrue(os.path.isfile(os.path.join(v1, "skill", "b.json")))

    def test_single_entry_has_full_data(self):
        entry = _make_entry("x", install={"method": "mcp_config", "config": {"cmd": "npx"}})
        self._run([entry])
        with open(os.path.join(self.output_dir, "v1", "mcp", "x.json")) as f:
            data = json.load(f)
        self.assertEqual(data["id"], "x")
        self.assertIn("evaluation", data)
        self.assertIn("install", data)
        self.assertEqual(data["install"]["config"]["cmd"], "npx")

    def test_type_index_has_lightweight_fields(self):
        self._run([_make_entry("x")])
        with open(os.path.join(self.output_dir, "v1", "mcp", "index.json")) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        self.assertIn("install_method", data[0])
        self.assertNotIn("evaluation", data[0])
        self.assertNotIn("health", data[0])

    def test_search_index_copied(self):
        self._run([_make_entry("x")])
        src = os.path.join(self.catalog_dir, "search-index.json")
        dst = os.path.join(self.output_dir, "v1", "search-index.json")
        with open(src) as f:
            src_data = f.read()
        with open(dst) as f:
            dst_data = f.read()
        self.assertEqual(src_data, dst_data)

    def test_stale_files_cleaned(self):
        """Old files from previous generation are removed."""
        entries = [_make_entry("a")]
        self._run(entries)
        stale = os.path.join(self.output_dir, "v1", "mcp", "old-entry.json")
        with open(stale, "w") as f:
            f.write("{}")
        self.assertTrue(os.path.exists(stale))
        # Re-run — stale file should be gone
        self._run(entries)
        self.assertFalse(os.path.exists(stale))

    def test_special_id_sanitized(self):
        entry = _make_entry("@scope/my-server")
        self._run([entry])
        path = os.path.join(self.output_dir, "v1", "mcp", "scope--my-server.json")
        self.assertTrue(os.path.isfile(path))


if __name__ == "__main__":
    unittest.main()
