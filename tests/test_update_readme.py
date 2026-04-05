import json
import tempfile
import unittest
from pathlib import Path
from typing import override

from scripts import update_readme


class UpdateReadmeTests(unittest.TestCase):
    tmpdir: str = ""
    root: Path = Path(".")
    catalog_dir: Path = Path(".")
    index_path: Path = Path(".")
    featured_en: Path = Path(".")
    featured_zh: Path = Path(".")
    readme_en: Path = Path(".")
    readme_zh: Path = Path(".")

    @override
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir)
        self.catalog_dir = self.root / "catalog"
        self.catalog_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.catalog_dir / "index.json"
        self.featured_en = self.catalog_dir / "featured.md"
        self.featured_zh = self.catalog_dir / "featured.zh-CN.md"
        self.readme_en = self.root / "README.md"
        self.readme_zh = self.root / "README.zh-CN.md"

    def _write_json(self, path: Path, data: list[dict[str, str]]) -> None:
        _ = path.write_text(json.dumps(data), encoding="utf-8")

    def test_update_readmes_updates_counts_badge_and_featured_sections(self):
        entries = [
            {"type": "mcp"},
            {"type": "mcp"},
            {"type": "prompt"},
            {"type": "rule"},
            {"type": "skill"},
        ]
        self._write_json(self.index_path, entries)
        _ = self.featured_en.write_text(
            "## ⭐ Featured Picks\n\nEnglish featured block\n", encoding="utf-8"
        )
        _ = self.featured_zh.write_text(
            "## ⭐ 精选推荐\n\n中文精选区块\n", encoding="utf-8"
        )

        readme_template = """# Coding Hub

<p><strong><!-- README_APPROX_COUNT:START -->0000<!-- README_APPROX_COUNT:END -->+ title</strong></p>
<img src=\"https://img.shields.io/badge/resources-0-2ECC71?style=flat-square\" alt=\"Resources\" />

| MCP Server | <!-- README_COUNT_MCP:START -->0<!-- README_COUNT_MCP:END --> |
| Prompt | <!-- README_COUNT_PROMPT:START -->0<!-- README_COUNT_PROMPT:END --> |
| Rule | <!-- README_COUNT_RULE:START -->0<!-- README_COUNT_RULE:END --> |
| Skill | <!-- README_COUNT_SKILL:START -->0<!-- README_COUNT_SKILL:END --> |

<!-- README_FEATURED_SECTION:START -->
old featured content
<!-- README_FEATURED_SECTION:END -->
"""
        _ = self.readme_en.write_text(readme_template, encoding="utf-8")
        _ = self.readme_zh.write_text(readme_template, encoding="utf-8")

        specs = (
            update_readme.ReadmeSpec(
                path=self.readme_en, featured_path=self.featured_en
            ),
            update_readme.ReadmeSpec(
                path=self.readme_zh, featured_path=self.featured_zh
            ),
        )
        _ = update_readme.update_readmes(index_path=self.index_path, readme_specs=specs)

        english = self.readme_en.read_text(encoding="utf-8")
        chinese = self.readme_zh.read_text(encoding="utf-8")

        self.assertIn(
            "<!-- README_APPROX_COUNT:START -->0<!-- README_APPROX_COUNT:END -->+ title",
            english,
        )
        self.assertIn("resources-5-2ECC71", english)
        self.assertIn(
            "<!-- README_COUNT_MCP:START -->2<!-- README_COUNT_MCP:END -->", english
        )
        self.assertIn(
            "<!-- README_COUNT_PROMPT:START -->1<!-- README_COUNT_PROMPT:END -->",
            english,
        )
        self.assertIn("English featured block", english)
        self.assertNotIn("old featured content", english)

        self.assertIn("resources-5-2ECC71", chinese)
        self.assertIn("中文精选区块", chinese)
        self.assertNotIn("old featured content", chinese)


if __name__ == "__main__":
    _ = unittest.main()
