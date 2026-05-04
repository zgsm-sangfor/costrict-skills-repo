"""scripts/audit_popular_coverage.py 单元测试。

覆盖：
- 期望清单 YAML 解析
- 三种状态判定（直接源 / 仅镜像 / 未收录）
- install_count 显示（数字 / "-" 缺失）
- 报告内容未变化时跳过写入
- 报告内容变化时写入
"""

import json
import os
import sys
import tempfile
import textwrap
import unittest

SCRIPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts"))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import audit_popular_coverage as apc  # noqa: E402


def _skill_entry(source_url: str, install_count=None, name="dummy"):
    """构造一条最小可用的 skill catalog entry。"""
    e = {
        "id": f"id-{name}",
        "name": name,
        "type": "skill",
        "source_url": source_url,
        "description": "test",
    }
    if install_count is not None:
        e["install_count"] = install_count
    return e


class TestLoadExpected(unittest.TestCase):
    def test_load_yaml_basic(self):
        """正常解析 YAML 列表，每条含 name / github_repo / reason。
        load_expected 返回 dict，键为 entry_type。"""
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "exp.yaml")
            with open(p, "w", encoding="utf-8") as f:
                f.write(textwrap.dedent("""\
                    expected_skills:
                      - name: superpowers
                        github_repo: obra/superpowers
                        reason: "94K stars"
                      - name: skills
                        github_repo: anthropics/skills
                        reason: "official"
                """))
            grouped = apc.load_expected(p)
            self.assertIsInstance(grouped, dict)
            # 所有 3 个分组键都应存在
            self.assertIn("skill", grouped)
            self.assertIn("mcp", grouped)
            self.assertIn("rule", grouped)
            items = grouped["skill"]
            self.assertEqual(len(items), 2)
            self.assertEqual(items[0]["github_repo"], "obra/superpowers")
            self.assertEqual(items[0]["reason"], "94K stars")
            self.assertEqual(items[1]["name"], "skills")
            # 未提供的组返回空 list
            self.assertEqual(grouped["mcp"], [])
            self.assertEqual(grouped["rule"], [])

    def test_load_yaml_skips_invalid(self):
        """缺失 github_repo 的条目被跳过，不抛异常。"""
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "exp.yaml")
            with open(p, "w", encoding="utf-8") as f:
                f.write(textwrap.dedent("""\
                    expected_skills:
                      - name: ok
                        github_repo: foo/bar
                      - name: missing-repo
                      - "scalar string entry"
                """))
            items = apc.load_expected(p)["skill"]
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["github_repo"], "foo/bar")

    def test_load_real_yaml_file(self):
        """仓库内置的 popular_skills_expected.yaml 能被正常解析。"""
        grouped = apc.load_expected()
        self.assertIsInstance(grouped, dict)
        skills = grouped["skill"]
        self.assertGreaterEqual(len(skills), 7)
        # 确保几条期望项都在列表里
        slugs = {it["github_repo"].lower() for it in skills}
        self.assertIn("obra/superpowers", slugs)
        self.assertIn("anthropics/skills", slugs)
        # 新增的 mcp / rule 分组也存在
        self.assertGreaterEqual(len(grouped["mcp"]), 5)
        self.assertGreaterEqual(len(grouped["rule"]), 4)
        mcp_slugs = {it["github_repo"].lower() for it in grouped["mcp"]}
        rule_slugs = {it["github_repo"].lower() for it in grouped["rule"]}
        self.assertIn("modelcontextprotocol/servers", mcp_slugs)
        self.assertIn("patrickjs/awesome-cursorrules", rule_slugs)

    def test_load_three_groups(self):
        """同时定义 expected_skills / expected_mcp / expected_rules 时，
        三个分组都被正确解析。"""
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "exp.yaml")
            with open(p, "w", encoding="utf-8") as f:
                f.write(textwrap.dedent("""\
                    expected_skills:
                      - name: s1
                        github_repo: skill/one
                        reason: "s reason"
                    expected_mcp:
                      - name: m1
                        github_repo: mcp/one
                        reason: "m reason"
                      - name: m2
                        github_repo: mcp/two
                        reason: "m2 reason"
                    expected_rules:
                      - name: r1
                        github_repo: rule/one
                        reason: "r reason"
                """))
            grouped = apc.load_expected(p)
            self.assertEqual(len(grouped["skill"]), 1)
            self.assertEqual(len(grouped["mcp"]), 2)
            self.assertEqual(len(grouped["rule"]), 1)
            self.assertEqual(grouped["mcp"][0]["github_repo"], "mcp/one")
            self.assertEqual(grouped["rule"][0]["github_repo"], "rule/one")


class TestStatusDetermination(unittest.TestCase):
    def test_status_direct_hit(self):
        """source_url 直接落在目标 owner/repo → 直接源。"""
        entries = [
            _skill_entry(
                "https://github.com/obra/superpowers/tree/main/skills/foo",
                install_count=12500,
            ),
        ]
        status, rep = apc.determine_status("obra/superpowers", entries)
        self.assertEqual(status, apc.STATUS_DIRECT)
        self.assertIsNotNone(rep)
        self.assertEqual(rep["install_count"], 12500)

    def test_status_direct_with_anchor_form(self):
        """skills.sh 风格 anchor URL（含 #skill=）也算直接源。"""
        entries = [
            _skill_entry(
                "https://github.com/vercel-labs/agent-skills#skill=react-best-practices",
                install_count=8000,
            ),
        ]
        status, rep = apc.determine_status("vercel-labs/agent-skills", entries)
        self.assertEqual(status, apc.STATUS_DIRECT)
        self.assertEqual(rep["install_count"], 8000)

    def test_status_mirror_only_for_anthropics(self):
        """anthropics/skills 仅以 sickn33 镜像存在 → 仅镜像。"""
        entries = [
            _skill_entry(
                "https://github.com/sickn33/antigravity-awesome-skills/tree/main/skills/foo",
            ),
        ]
        status, rep = apc.determine_status("anthropics/skills", entries)
        self.assertEqual(status, apc.STATUS_MIRROR)
        self.assertIsNotNone(rep)

    def test_status_not_found_for_non_anthropics_when_only_mirror(self):
        """vercel-labs/agent-skills 仅有 sickn33 镜像 entry → 未收录
        （因为该镜像不是 vercel-labs 的镜像）。
        """
        entries = [
            _skill_entry(
                "https://github.com/sickn33/antigravity-awesome-skills/tree/main/skills/foo",
            ),
        ]
        status, rep = apc.determine_status("vercel-labs/agent-skills", entries)
        self.assertEqual(status, apc.STATUS_MISSING)
        self.assertIsNone(rep)

    def test_status_direct_takes_priority_over_mirror(self):
        """同时存在直接源和镜像 → 直接源胜出。"""
        entries = [
            _skill_entry(
                "https://github.com/sickn33/antigravity-awesome-skills/tree/main/skills/foo",
            ),
            _skill_entry(
                "https://github.com/anthropics/skills/tree/main/skills/foo",
                install_count=5000,
            ),
        ]
        status, rep = apc.determine_status("anthropics/skills", entries)
        self.assertEqual(status, apc.STATUS_DIRECT)
        self.assertEqual(rep["install_count"], 5000)

    def test_status_missing(self):
        """catalog 完全不含目标 owner/repo → 未收录。"""
        entries = [
            _skill_entry("https://github.com/some/other/tree/main/skills/foo"),
        ]
        status, rep = apc.determine_status("obra/superpowers", entries)
        self.assertEqual(status, apc.STATUS_MISSING)
        self.assertIsNone(rep)

    def test_non_skill_entry_ignored(self):
        """type != skill 的 entry 不参与判定。"""
        entries = [
            {
                "id": "x",
                "type": "mcp",
                "source_url": "https://github.com/obra/superpowers",
            },
        ]
        status, _ = apc.determine_status("obra/superpowers", entries)
        self.assertEqual(status, apc.STATUS_MISSING)

    def test_pick_largest_install_count_as_representative(self):
        """同一 owner/repo 下多条直接源 entry，取 install_count 最大者作为代表。"""
        entries = [
            _skill_entry(
                "https://github.com/obra/superpowers/tree/main/skills/a",
                install_count=1000,
            ),
            _skill_entry(
                "https://github.com/obra/superpowers/tree/main/skills/b",
                install_count=9999,
            ),
            _skill_entry(
                "https://github.com/obra/superpowers/tree/main/skills/c",
                install_count=200,
            ),
        ]
        status, rep = apc.determine_status("obra/superpowers", entries)
        self.assertEqual(status, apc.STATUS_DIRECT)
        self.assertEqual(rep["install_count"], 9999)


class TestInstallCountDisplay(unittest.TestCase):
    def test_format_number_with_thousands_separator(self):
        e = {"install_count": 12500}
        self.assertEqual(apc._format_install_count(e), "12,500")

    def test_format_zero(self):
        e = {"install_count": 0}
        self.assertEqual(apc._format_install_count(e), "0")

    def test_format_none_entry(self):
        self.assertEqual(apc._format_install_count(None), "-")

    def test_format_missing_field(self):
        e = {"install_count": None}
        self.assertEqual(apc._format_install_count(e), "-")

    def test_format_empty_field(self):
        e = {"install_count": ""}
        self.assertEqual(apc._format_install_count(e), "-")

    def test_format_non_int_fallback(self):
        e = {"install_count": "abc"}
        self.assertEqual(apc._format_install_count(e), "abc")


class TestReportRendering(unittest.TestCase):
    def test_render_summary_counts_legacy_list(self):
        """expected 传 list 时按 skill 旧形式处理（向后兼容）。"""
        expected = [
            {"name": "a", "github_repo": "obra/superpowers", "reason": "x"},
            {"name": "b", "github_repo": "vercel-labs/agent-skills", "reason": "y"},
            {"name": "c", "github_repo": "anthropics/skills", "reason": "z"},
        ]
        entries = [
            # direct hit for obra/superpowers
            _skill_entry(
                "https://github.com/obra/superpowers/tree/main/skills/foo",
                install_count=1500,
            ),
            # mirror only for anthropics/skills
            _skill_entry(
                "https://github.com/sickn33/antigravity-awesome-skills/tree/main/skills/foo",
            ),
            # vercel-labs/agent-skills not present
        ]
        report = apc.render_report(expected, entries, generated_at="2026-05-02")
        # Skills 分组各 1 条
        self.assertIn("✅ 直接源：1 / 3", report)
        self.assertIn("⚠️ 仅镜像：1 / 3", report)
        self.assertIn("❌ 未收录：1 / 3", report)
        self.assertIn("| obra/superpowers |", report)
        self.assertIn("1,500", report)
        # 表头存在
        self.assertIn("| Skill | GitHub | 状态 | install_count | 备注 |", report)
        # 生成时间正确注入
        self.assertIn("报告生成时间：2026-05-02", report)
        # 三个分组都有标题
        self.assertIn("## Skills 覆盖", report)
        self.assertIn("## MCP 覆盖", report)
        self.assertIn("## Rules 覆盖", report)
        self.assertIn("## 状态摘要总览", report)


class TestMultiTypeClassify(unittest.TestCase):
    """classify_entry 支持多 type 的关键场景。"""

    def test_mcp_github_url_match(self):
        """type=mcp + GitHub URL 匹配 expected → direct。"""
        e = {
            "id": "x",
            "type": "mcp",
            "source_url": "https://github.com/microsoft/playwright-mcp",
        }
        self.assertEqual(
            apc.classify_entry(e, "microsoft/playwright-mcp", entry_type="mcp"),
            "direct",
        )

    def test_mcp_type_skill_entry_does_not_match(self):
        """同 owner/repo 但 type=skill 时，mcp 审计不命中。"""
        e = {
            "id": "x",
            "type": "skill",
            "source_url": "https://github.com/microsoft/playwright-mcp",
        }
        self.assertEqual(
            apc.classify_entry(e, "microsoft/playwright-mcp", entry_type="mcp"),
            "",
        )

    def test_mcp_registry_url_does_not_match(self):
        """type=mcp 但 source_url 是 registry URL → 不参与 GitHub-based 命中。"""
        e = {
            "id": "x",
            "type": "mcp",
            "source_url": "https://registry.modelcontextprotocol.io/v0/servers/io.github.foo%2Fbar",
        }
        self.assertEqual(
            apc.classify_entry(e, "foo/bar", entry_type="mcp"),
            "",
        )

    def test_rule_direct_hit(self):
        """type=rule + GitHub URL 匹配 expected → direct。"""
        e = {
            "id": "x",
            "type": "rule",
            "source_url": "https://github.com/PatrickJS/awesome-cursorrules/blob/main/rules/react.md",
        }
        self.assertEqual(
            apc.classify_entry(e, "patrickjs/awesome-cursorrules", entry_type="rule"),
            "direct",
        )

    def test_rule_no_mirror_concept(self):
        """rule 类型不复用 sickn33 镜像逻辑（只有 skill 类型才有镜像）。"""
        e = {
            "id": "x",
            "type": "rule",
            "source_url": "https://github.com/sickn33/antigravity-awesome-skills",
        }
        # 即使目标是 anthropics/skills（仅 skill 才会触发 mirror），
        # 对 rule 类型审计来说也不应该返回 mirror
        self.assertEqual(
            apc.classify_entry(e, "anthropics/skills", entry_type="rule"),
            "",
        )

    def test_determine_status_by_type_isolates_types(self):
        """同 owner/repo 下 mcp 与 skill 各 1 条 entry，按 mcp 审计仅 mcp 命中。"""
        entries = [
            {
                "id": "skill-one",
                "type": "skill",
                "source_url": "https://github.com/foo/bar",
            },
            {
                "id": "mcp-one",
                "type": "mcp",
                "source_url": "https://github.com/foo/bar",
                "install_count": 42,
            },
        ]
        # mcp 审计：仅 mcp entry 命中，代表 entry 是 mcp
        status, rep = apc.determine_status_by_type("foo/bar", entries, "mcp")
        self.assertEqual(status, apc.STATUS_DIRECT)
        self.assertEqual(rep["id"], "mcp-one")
        # rule 审计：完全无命中
        status_rule, rep_rule = apc.determine_status_by_type("foo/bar", entries, "rule")
        self.assertEqual(status_rule, apc.STATUS_MISSING)
        self.assertIsNone(rep_rule)


class TestRenderReportThreeSections(unittest.TestCase):
    """render_report 渲染 Skills / MCP / Rules 三个分组。"""

    def test_render_three_sections_with_dict_input(self):
        expected = {
            "skill": [
                {"name": "sp", "github_repo": "obra/superpowers", "reason": "94K"},
            ],
            "mcp": [
                {"name": "playwright", "github_repo": "microsoft/playwright-mcp", "reason": "ms"},
                {"name": "missing-mcp", "github_repo": "nobody/nope", "reason": "n/a"},
            ],
            "rule": [
                {"name": "cr", "github_repo": "PatrickJS/awesome-cursorrules", "reason": "權威"},
            ],
        }
        entries = [
            _skill_entry(
                "https://github.com/obra/superpowers/tree/main/skills/foo",
                install_count=1500,
            ),
            {
                "id": "m1",
                "type": "mcp",
                "source_url": "https://github.com/microsoft/playwright-mcp",
            },
            {
                "id": "r1",
                "type": "rule",
                "source_url": "https://github.com/PatrickJS/awesome-cursorrules/blob/main/x.md",
            },
        ]
        report = apc.render_report(expected, entries, generated_at="2026-05-02")
        # 三个分组标题
        self.assertIn("## Skills 覆盖", report)
        self.assertIn("## MCP 覆盖", report)
        self.assertIn("## Rules 覆盖", report)
        # 总览节
        self.assertIn("## 状态摘要总览", report)
        # 各分组的命中
        self.assertIn("| obra/superpowers |", report)
        self.assertIn("| microsoft/playwright-mcp |", report)
        self.assertIn("| PatrickJS/awesome-cursorrules |", report)
        # 总览：3 条直接源 + 1 条未收录
        self.assertIn("✅ 直接源：3 / 4", report)
        self.assertIn("❌ 未收录：1 / 4", report)
        # 表头按 item_label 渲染
        self.assertIn("| Skill | GitHub |", report)
        self.assertIn("| MCP Server | GitHub |", report)
        self.assertIn("| Rule | GitHub |", report)

    def test_render_with_empty_groups(self):
        """缺失某分组（如未维护 expected_rules）不应崩溃。"""
        expected = {"skill": [], "mcp": [], "rule": []}
        entries = []
        report = apc.render_report(expected, entries, generated_at="2026-05-02")
        self.assertIn("## Skills 覆盖", report)
        self.assertIn("## MCP 覆盖", report)
        self.assertIn("## Rules 覆盖", report)
        # 空清单提示
        self.assertIn("（暂无期望清单条目）", report)


class TestIncrementalWrite(unittest.TestCase):
    def test_unchanged_report_skip_write(self):
        """内容相同时不写文件（即使生成时间字段不同也算未变）。"""
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "report.md")
            content_v1 = (
                "# Catalog 热门 Skill 覆盖率审计\n\n"
                "报告生成时间：2026-05-01\n"
                "catalog 版本：catalog/index.json 总条目 100\n"
                "\n## 状态摘要\n\n- ✅ 直接源：1 / 1\n"
            )
            with open(p, "w", encoding="utf-8") as f:
                f.write(content_v1)
            mtime_before = os.path.getmtime(p)

            # 同样的实质内容，仅日期不同 → 不应触发写入
            content_v2 = content_v1.replace("2026-05-01", "2026-05-02")
            written = apc.write_report_if_changed(content_v2, p)
            self.assertFalse(written)

            # 验证文件没被覆盖（mtime 不变）
            with open(p, "r", encoding="utf-8") as f:
                self.assertEqual(f.read(), content_v1)
            self.assertAlmostEqual(os.path.getmtime(p), mtime_before, places=3)

    def test_changed_report_writes(self):
        """实质内容变化时写入。"""
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "report.md")
            content_v1 = (
                "# Catalog 热门 Skill 覆盖率审计\n\n"
                "报告生成时间：2026-05-01\n"
                "catalog 版本：catalog/index.json 总条目 100\n"
                "\n## 状态摘要\n\n- ✅ 直接源：1 / 7\n"
            )
            with open(p, "w", encoding="utf-8") as f:
                f.write(content_v1)

            content_v2 = content_v1.replace("✅ 直接源：1 / 7", "✅ 直接源：5 / 7")
            written = apc.write_report_if_changed(content_v2, p)
            self.assertTrue(written)
            with open(p, "r", encoding="utf-8") as f:
                self.assertIn("5 / 7", f.read())

    def test_first_run_writes_when_no_prior_report(self):
        """目标文件不存在时直接写入。"""
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "sub", "report.md")
            content = "# title\n报告生成时间：2026-05-02\nbody\n"
            written = apc.write_report_if_changed(content, p)
            self.assertTrue(written)
            self.assertTrue(os.path.exists(p))


class TestCatalogLoading(unittest.TestCase):
    def test_load_list_top_level(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "index.json")
            payload = [{"id": "x", "type": "skill", "source_url": "https://github.com/a/b"}]
            with open(p, "w", encoding="utf-8") as f:
                json.dump(payload, f)
            entries = apc.load_catalog(p)
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["id"], "x")

    def test_load_dict_with_entries_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "index.json")
            payload = {"entries": [{"id": "y", "type": "skill", "source_url": ""}]}
            with open(p, "w", encoding="utf-8") as f:
                json.dump(payload, f)
            entries = apc.load_catalog(p)
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["id"], "y")

    def test_load_missing_returns_empty(self):
        entries = apc.load_catalog("/no/such/path.json")
        self.assertEqual(entries, [])


if __name__ == "__main__":
    unittest.main()
