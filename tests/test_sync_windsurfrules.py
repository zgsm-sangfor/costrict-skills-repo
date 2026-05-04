"""scripts/sync_windsurfrules.py 单元测试。

覆盖：
- 标准 windsurfrules/ 下 README.md → 普通 entry
- global_rules/ 下 global_rules.md → tags 含 "windsurf-global"，category="global"（两仓都测）
- frontmatter 容错（无 / 损坏 / 多种字段格式）
- 跨仓库 id 唯一性（同 slug，repo_slug 后缀不同）
- 仓库 404 → 跳过该仓
- 两仓全失败 → exit 1
"""

import os
import sys
import tempfile
import unittest
import unittest.mock as mock

SCRIPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts"))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import sync_windsurfrules as sw  # noqa: E402


def _make_tree(paths: list[str]) -> dict:
    return {
        "tree": [
            {"path": p, "type": "blob"} for p in paths
        ] + [{"path": "rules", "type": "tree"}]
    }


def _repo_info(branch: str = "main", stars: int = 70,
               pushed_at: str = "2026-04-30T00:00:00Z") -> dict:
    return {
        "default_branch": branch,
        "stargazers_count": stars,
        "pushed_at": pushed_at,
    }


class TestParseFrontmatter(unittest.TestCase):
    def test_no_frontmatter(self):
        fm, body = sw.parse_frontmatter("just body content here")
        self.assertEqual(fm, {})
        self.assertEqual(body, "just body content here")

    def test_basic_frontmatter(self):
        text = "---\nname: My Rule\ndescription: Awesome\n---\nbody line"
        fm, body = sw.parse_frontmatter(text)
        self.assertEqual(fm["name"], "My Rule")
        self.assertEqual(fm["description"], "Awesome")
        self.assertEqual(body.strip(), "body line")

    def test_quoted_values(self):
        text = '---\nname: "Quoted Name"\ndescription: \'singles\'\n---\nx'
        fm, _ = sw.parse_frontmatter(text)
        self.assertEqual(fm["name"], "Quoted Name")
        self.assertEqual(fm["description"], "singles")

    def test_tags_list_inline(self):
        text = "---\ntags: [react, frontend, typescript]\n---\nbody"
        fm, _ = sw.parse_frontmatter(text)
        self.assertEqual(fm["tags"], ["react", "frontend", "typescript"])

    def test_tags_csv(self):
        text = "---\ntags: react, frontend\n---\nbody"
        fm, _ = sw.parse_frontmatter(text)
        self.assertEqual(fm["tags"], ["react", "frontend"])

    def test_corrupted_frontmatter_no_closing(self):
        # 缺闭合 ---，应当被视作整体无 frontmatter
        text = "---\nname: Foo\nno closing fence\nstill body"
        fm, body = sw.parse_frontmatter(text)
        self.assertEqual(fm, {})
        self.assertEqual(body, text)

    def test_empty_input(self):
        fm, body = sw.parse_frontmatter("")
        self.assertEqual(fm, {})
        self.assertEqual(body, "")


class TestBuildEntry(unittest.TestCase):
    def test_standard_rule(self):
        path = "rules/windsurfrules/react-windsurfrules-prompt-file/README.md"
        content = "# React Rules\n\nA collection of React Windsurf rules.\n"
        entry = sw._build_entry(
            "SchneiderSam/awesome-windsurfrules", "schneidersam", "main",
            path, content,
        )
        self.assertIsNotNone(entry)
        self.assertEqual(
            entry["id"], "react-windsurfrules-prompt-file-schneidersam"
        )
        self.assertEqual(entry["type"], "rule")
        self.assertEqual(entry["source"], sw.SOURCE_NAME)
        self.assertNotIn("windsurf-global", entry["tags"])
        self.assertIn("windsurf", entry["tags"])
        self.assertIn(
            "https://github.com/SchneiderSam/awesome-windsurfrules/blob/main/" + path,
            entry["source_url"],
        )
        self.assertEqual(entry["install"]["method"], "download_file")
        self.assertTrue(
            entry["install"]["files"][0].startswith("https://raw.githubusercontent.com/")
        )

    def test_global_rule_schneidersam(self):
        path = "rules/global_rules/commit-message-short/global_rules.md"
        content = "Some content describing global commit rules."
        entry = sw._build_entry(
            "SchneiderSam/awesome-windsurfrules", "schneidersam", "main",
            path, content,
        )
        self.assertEqual(entry["category"], "tooling")
        self.assertIn("windsurf-global", entry["tags"])
        self.assertEqual(entry["id"], "commit-message-short-schneidersam")

    def test_global_rule_balqaasem(self):
        path = "rules/global_rules/commit-message-short/global_rules.md"
        content = "Mirror copy of the same global rule."
        entry = sw._build_entry(
            "balqaasem/awesome-windsurfrules", "balqaasem", "main",
            path, content,
        )
        self.assertEqual(entry["category"], "tooling")
        self.assertIn("windsurf-global", entry["tags"])
        self.assertEqual(entry["id"], "commit-message-short-balqaasem")

    def test_id_unique_across_repos(self):
        path = "rules/windsurfrules/react-rule/README.md"
        a = sw._build_entry(
            "SchneiderSam/awesome-windsurfrules", "schneidersam", "main", path, "x",
        )
        b = sw._build_entry(
            "balqaasem/awesome-windsurfrules", "balqaasem", "main", path, "x",
        )
        self.assertNotEqual(a["id"], b["id"])
        self.assertTrue(a["id"].endswith("-schneidersam"))
        self.assertTrue(b["id"].endswith("-balqaasem"))

    def test_frontmatter_description_used(self):
        path = "rules/windsurfrules/foo/README.md"
        content = (
            "---\nname: Foo Rule\ndescription: From frontmatter\n"
            "tags: [react, ts]\n---\nbody first line\n"
        )
        entry = sw._build_entry(
            "SchneiderSam/awesome-windsurfrules", "schneidersam", "main",
            path, content,
        )
        self.assertEqual(entry["description"], "From frontmatter")
        self.assertIn("react", entry["tags"])
        self.assertIn("ts", entry["tags"])

    def test_frontmatter_corrupt_falls_back_to_body(self):
        path = "rules/windsurfrules/foo/README.md"
        content = "---\nname: Broken\nNO CLOSING\nstill text"
        entry = sw._build_entry(
            "SchneiderSam/awesome-windsurfrules", "schneidersam", "main",
            path, content,
        )
        # 损坏 frontmatter → 走 body 第一段
        self.assertTrue(entry["description"])
        self.assertNotEqual(entry["description"], "")

    def test_no_content_uses_placeholder(self):
        path = "rules/windsurfrules/empty/README.md"
        entry = sw._build_entry(
            "SchneiderSam/awesome-windsurfrules", "schneidersam", "main",
            path, "",
        )
        self.assertIn("Windsurf rules for empty", entry["description"])


class TestParseRepo(unittest.TestCase):
    def test_skip_when_repo_404(self):
        with mock.patch.object(sw, "github_api", return_value=None) as gh:
            entries = sw.parse_repo("ghost/repo", "ghost")
        self.assertEqual(entries, [])
        gh.assert_called()

    def test_skip_when_no_md_files(self):
        def fake_api(path):
            if path.startswith("repos/SchneiderSam/awesome-windsurfrules/git/trees/"):
                return {"tree": [{"path": "README.md", "type": "blob"}]}
            return _repo_info()

        with mock.patch.object(sw, "github_api", side_effect=fake_api):
            entries = sw.parse_repo(
                "SchneiderSam/awesome-windsurfrules", "schneidersam"
            )
        self.assertEqual(entries, [])

    def test_full_parse_with_mixed_paths(self):
        paths = [
            "rules/windsurfrules/react-rule/README.md",
            "rules/global_rules/commit-message-short/global_rules.md",
            "rules/windsurfrules/python/README.md",
            "rules/README.md",  # 顶层 README 也可作为 fallback md
            "docs/README.md",   # 不在 rules/ 下，应被忽略
        ]

        def fake_api(path):
            if "/git/trees/" in path:
                return _make_tree(paths)
            return _repo_info(branch="main")

        def fake_fetch(repo, path, branch="main", quiet_404=False):
            if path.endswith("global_rules.md"):
                return "global content"
            if path.endswith("README.md"):
                return f"# {path}\n\nDescription line."
            return None

        with mock.patch.object(sw, "github_api", side_effect=fake_api), \
             mock.patch.object(sw, "fetch_raw_content", side_effect=fake_fetch):
            entries = sw.parse_repo(
                "SchneiderSam/awesome-windsurfrules", "schneidersam"
            )

        ids = sorted(e["id"] for e in entries)
        self.assertIn("commit-message-short-schneidersam", ids)
        self.assertIn("react-rule-schneidersam", ids)
        self.assertIn("python-schneidersam", ids)
        # docs/ 下不会被收
        self.assertFalse(any("docs" in i for i in ids))

        # global_rule 标记正确
        gentry = next(e for e in entries if e["id"].startswith("commit-message-short"))
        self.assertEqual(gentry["category"], "tooling")
        self.assertIn("windsurf-global", gentry["tags"])

        # 普通 rule 不带 windsurf-global tag
        rentry = next(e for e in entries if e["id"] == "react-rule-schneidersam")
        self.assertNotIn("windsurf-global", rentry["tags"])

        # pushed_at / stars 透传
        self.assertTrue(all(e["pushed_at"] == "2026-04-30T00:00:00Z" for e in entries))
        self.assertTrue(all(e["stars"] == 70 for e in entries))

    def test_skip_individual_fetch_failure(self):
        paths = [
            "rules/windsurfrules/a/README.md",
            "rules/windsurfrules/b/README.md",
        ]

        def fake_api(path):
            if "/git/trees/" in path:
                return _make_tree(paths)
            return _repo_info()

        def fake_fetch(repo, path, branch="main", quiet_404=False):
            if "/a/" in path:
                return None  # 单文件 404，不退出
            return "# B\nDescription."

        with mock.patch.object(sw, "github_api", side_effect=fake_api), \
             mock.patch.object(sw, "fetch_raw_content", side_effect=fake_fetch):
            entries = sw.parse_repo(
                "SchneiderSam/awesome-windsurfrules", "schneidersam"
            )
        ids = [e["id"] for e in entries]
        self.assertEqual(ids, ["b-schneidersam"])


class TestSyncMain(unittest.TestCase):
    def test_cross_repo_id_distinct(self):
        # 同一 slug 在两个仓库出现 → id 不同，皆入索引
        paths = ["rules/windsurfrules/react-rule/README.md"]

        def fake_api(path):
            if "/git/trees/" in path:
                return _make_tree(paths)
            return _repo_info()

        def fake_fetch(repo, path, branch="main", quiet_404=False):
            return "# React\nA shared rule."

        with tempfile.TemporaryDirectory() as tmp:
            output = os.path.join(tmp, "windsurfrules_index.json")
            with mock.patch.object(sw, "OUTPUT_PATH", output), \
                 mock.patch.object(sw, "github_api", side_effect=fake_api), \
                 mock.patch.object(sw, "fetch_raw_content", side_effect=fake_fetch):
                rc = sw.sync()

            self.assertEqual(rc, 0)
            import json
            with open(output, "r", encoding="utf-8") as f:
                data = json.load(f)
            ids = sorted(e["id"] for e in data)
            self.assertEqual(
                ids,
                ["react-rule-balqaasem", "react-rule-schneidersam"],
            )

    def test_all_repos_fail_returns_1(self):
        with mock.patch.object(sw, "github_api", return_value=None), \
             mock.patch.object(sw, "fetch_raw_content", return_value=None):
            rc = sw.sync()
        self.assertEqual(rc, 1)

    def test_partial_repo_failure_still_succeeds(self):
        paths = ["rules/windsurfrules/foo/README.md"]

        def fake_api(path):
            # 第一个仓库 OK，第二个仓库 404
            if "balqaasem" in path:
                return None
            if "/git/trees/" in path:
                return _make_tree(paths)
            return _repo_info()

        def fake_fetch(repo, path, branch="main", quiet_404=False):
            if "balqaasem" in repo:
                return None
            return "# Foo\nDesc."

        with tempfile.TemporaryDirectory() as tmp:
            output = os.path.join(tmp, "windsurfrules_index.json")
            with mock.patch.object(sw, "OUTPUT_PATH", output), \
                 mock.patch.object(sw, "github_api", side_effect=fake_api), \
                 mock.patch.object(sw, "fetch_raw_content", side_effect=fake_fetch):
                rc = sw.sync()
            self.assertEqual(rc, 0)
            import json
            with open(output, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual([e["id"] for e in data], ["foo-schneidersam"])


if __name__ == "__main__":
    unittest.main()
