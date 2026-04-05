import tempfile
import unittest
from pathlib import Path

from scripts import generate_featured


def _make_entry(
    id_: str,
    *,
    type_: str = "mcp",
    source: str = "curated",
    tags: list[str] | None = None,
    description: str | None = None,
    description_zh: str | None = None,
    category: str = "tooling",
    stars: int | None = 100,
    evaluation: dict[str, str] | None = None,
    source_url: str | None = None,
) -> dict[str, object]:
    entry: dict[str, object] = {
        "id": id_,
        "name": id_,
        "type": type_,
        "description": description or f"English description for {id_}",
        "description_zh": description_zh or f"{id_} 的中文描述",
        "source_url": source_url or f"https://github.com/example/{id_}",
        "stars": stars,
        "category": category,
        "tags": tags or ["mcp"],
        "tech_stack": [],
        "install": {"method": "manual"},
        "source": source,
        "last_synced": "2026-04-04",
    }
    if evaluation is not None:
        entry["evaluation"] = evaluation
    return entry


class GenerateFeaturedTests(unittest.TestCase):
    def test_generate_featured_section_localizes_content(self):
        catalog = [
            _make_entry(
                "playwright-mcp",
                tags=["playwright", "browser"],
                category="automation",
                stars=30100,
                description="Official Playwright MCP for browser automation.",
                description_zh="Playwright 浏览器自动化 MCP。",
            ),
            _make_entry(
                "doc-coauthoring",
                type_="skill",
                source="anthropics-skills",
                stars=None,
                tags=["docs", "documentation"],
                category="documentation",
                description="Co-author technical docs with a structured workflow.",
                description_zh="用结构化流程协作编写技术文档。",
            ),
        ]

        english = generate_featured.generate_featured_section(
            lang="en", catalog=catalog
        )
        chinese = generate_featured.generate_featured_section(
            lang="zh", catalog=catalog
        )

        self.assertIn("## ⭐ Featured Picks", english)
        self.assertIn("### 🌐 Browser & Automation", english)
        self.assertIn("Official Playwright MCP for browser automation.", english)
        self.assertIn("`Anthropic official`", english)

        self.assertIn("## ⭐ 精选推荐", chinese)
        self.assertIn("### 🌐 浏览器与自动化", chinese)
        self.assertIn("Playwright 浏览器自动化 MCP。", chinese)
        self.assertIn("`Anthropic 官方`", chinese)

    def test_generate_featured_section_uses_english_reason_when_description_is_chinese(
        self,
    ):
        catalog = [
            _make_entry(
                "server-filesystem",
                tags=["mcp", "filesystem"],
                description="官方参考实现，提供对本地文件系统的直接访问。",
                description_zh="官方参考实现，提供对本地文件系统的直接访问。",
                evaluation={
                    "reason": "Official filesystem access implementation for local file operations."
                },
            )
        ]

        english = generate_featured.generate_featured_section(
            lang="en", catalog=catalog
        )

        self.assertIn(
            "Official filesystem access implementation for local file operations.",
            english,
        )

    def test_write_featured_sections_writes_both_languages(self):
        catalog = [
            _make_entry(
                "playwright-mcp", tags=["playwright", "browser"], category="automation"
            )
        ]
        tmpdir = tempfile.mkdtemp()
        original_outputs = generate_featured.FEATURED_OUTPUTS
        generate_featured.FEATURED_OUTPUTS = {
            "en": Path(tmpdir) / "featured.md",
            "zh": Path(tmpdir) / "featured.zh-CN.md",
        }

        try:
            written = generate_featured.write_featured_sections(catalog=catalog)
        finally:
            generate_featured.FEATURED_OUTPUTS = original_outputs

        self.assertTrue(written["en"].is_file())
        self.assertTrue(written["zh"].is_file())
        self.assertIn("Featured Picks", written["en"].read_text(encoding="utf-8"))
        self.assertIn("精选推荐", written["zh"].read_text(encoding="utf-8"))


if __name__ == "__main__":
    _ = unittest.main()
