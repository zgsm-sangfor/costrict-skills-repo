"""Tests for ``validate_mcp_registry_fields`` — Section 5.4 of
``add-tier1-rules-mcp-sources``.

Covers the 3 optional registry.modelcontextprotocol.io-contributed fields:

    - mcp_registry_status        (str, enum: active / inactive / deprecated)
    - mcp_registry_published_at  (str, ISO 8601 UTC)
    - mcp_remotes                (list[dict], each {type: str, url: str})

All three fields are optional (向后兼容).  If present, type must be strict.

This is the mcp-side sibling of ``test_schema_optional_fields.py``; the
4 scenarios (全有 / 全无 / 部分缺 / 类型错) mirror that file's structure.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from utils import validate_mcp_registry_fields


def _base_entry(**overrides):
    """Minimal mcp entry; ``validate_mcp_registry_fields`` only inspects the
    three optional fields, so other fields are largely irrelevant here."""
    e = {
        "id": "modelcontextprotocol-fetch",
        "name": "fetch",
        "type": "mcp",
        "source_url": (
            "https://registry.modelcontextprotocol.io/v0/servers/"
            "io.github.modelcontextprotocol%2Ffetch"
        ),
    }
    e.update(overrides)
    return e


class TestAllPresent(unittest.TestCase):
    """Scenario 1: all three fields present with correct types."""

    def test_all_present_correct_types(self):
        entry = _base_entry(
            mcp_registry_status="active",
            mcp_registry_published_at="2026-01-30T04:51:07Z",
            mcp_remotes=[
                {"type": "sse", "url": "https://mcp.example.com/sse"},
                {"type": "streamable-http", "url": "https://mcp.example.com/http"},
            ],
        )
        self.assertEqual(validate_mcp_registry_fields(entry), [])

    def test_published_at_with_milliseconds(self):
        # registry dump 中常见 ".907Z" 形式
        entry = _base_entry(
            mcp_registry_status="active",
            mcp_registry_published_at="2026-01-30T04:51:07.907Z",
            mcp_remotes=[{"type": "sse", "url": "https://x/sse"}],
        )
        self.assertEqual(validate_mcp_registry_fields(entry), [])

    def test_status_inactive_ok(self):
        entry = _base_entry(mcp_registry_status="inactive")
        self.assertEqual(validate_mcp_registry_fields(entry), [])

    def test_status_deprecated_ok(self):
        entry = _base_entry(mcp_registry_status="deprecated")
        self.assertEqual(validate_mcp_registry_fields(entry), [])

    def test_mcp_remotes_empty_list_ok(self):
        # 空 list 是合法的：字段存在但暂无 remote 端点
        entry = _base_entry(mcp_remotes=[])
        self.assertEqual(validate_mcp_registry_fields(entry), [])


class TestAllAbsent(unittest.TestCase):
    """Scenario 2: none of the three fields present (legacy / non-registry)."""

    def test_no_optional_fields(self):
        entry = _base_entry()
        self.assertEqual(validate_mcp_registry_fields(entry), [])

    def test_wong2_github_entry_passes(self):
        # wong2/awesome-mcp-servers 来源的 entry 不来自 registry，
        # 三字段全无应该通过
        entry = _base_entry(
            id="wong2-fetch",
            source_url="https://github.com/modelcontextprotocol/servers/tree/main/src/fetch",
        )
        self.assertEqual(validate_mcp_registry_fields(entry), [])


class TestPartialPresent(unittest.TestCase):
    """Scenario 3: only some optional fields present."""

    def test_only_status(self):
        entry = _base_entry(mcp_registry_status="active")
        self.assertEqual(validate_mcp_registry_fields(entry), [])

    def test_only_published_at(self):
        entry = _base_entry(mcp_registry_published_at="2026-01-30T04:51:07Z")
        self.assertEqual(validate_mcp_registry_fields(entry), [])

    def test_only_remotes(self):
        entry = _base_entry(
            mcp_remotes=[{"type": "sse", "url": "https://example.com/sse"}]
        )
        self.assertEqual(validate_mcp_registry_fields(entry), [])

    def test_two_fields_present(self):
        entry = _base_entry(
            mcp_registry_status="active",
            mcp_registry_published_at="2026-01-30T04:51:07Z",
        )
        self.assertEqual(validate_mcp_registry_fields(entry), [])

    def test_empty_string_published_at_tolerated(self):
        # 与 skills_sh_scraped_at 同款容错：空串视为"字段存在但未写入"
        entry = _base_entry(mcp_registry_published_at="")
        self.assertEqual(validate_mcp_registry_fields(entry), [])


class TestTypeErrors(unittest.TestCase):
    """Scenario 4: fields present but wrong type / invalid value / format."""

    # --- mcp_registry_status -------------------------------------------------

    def test_status_invalid_enum_value(self):
        entry = _base_entry(mcp_registry_status="active-test")
        errs = validate_mcp_registry_fields(entry)
        self.assertEqual(len(errs), 1)
        self.assertIn("mcp_registry_status must be one of", errs[0])

    def test_status_uppercase_rejected(self):
        # enum 严格大小写敏感
        entry = _base_entry(mcp_registry_status="ACTIVE")
        errs = validate_mcp_registry_fields(entry)
        self.assertEqual(len(errs), 1)
        self.assertIn("mcp_registry_status must be one of", errs[0])

    def test_status_not_string(self):
        entry = _base_entry(mcp_registry_status=1)
        errs = validate_mcp_registry_fields(entry)
        self.assertEqual(len(errs), 1)
        self.assertIn("mcp_registry_status must be str", errs[0])

    def test_status_none_rejected(self):
        entry = _base_entry(mcp_registry_status=None)
        errs = validate_mcp_registry_fields(entry)
        self.assertEqual(len(errs), 1)
        self.assertIn("mcp_registry_status must be str", errs[0])

    # --- mcp_registry_published_at -------------------------------------------

    def test_published_at_int(self):
        entry = _base_entry(mcp_registry_published_at=1735531867)
        errs = validate_mcp_registry_fields(entry)
        self.assertEqual(len(errs), 1)
        self.assertIn("mcp_registry_published_at must be str", errs[0])

    def test_published_at_bad_format(self):
        # 缺 "T" 分隔符
        entry = _base_entry(mcp_registry_published_at="2026-01-30 04:51:07Z")
        errs = validate_mcp_registry_fields(entry)
        self.assertEqual(len(errs), 1)
        self.assertIn("not ISO 8601", errs[0])

    def test_published_at_no_z_suffix(self):
        # 缺 "Z"（必须是 UTC）
        entry = _base_entry(mcp_registry_published_at="2026-01-30T04:51:07")
        errs = validate_mcp_registry_fields(entry)
        self.assertEqual(len(errs), 1)
        self.assertIn("not ISO 8601", errs[0])

    # --- mcp_remotes ---------------------------------------------------------

    def test_remotes_not_list(self):
        entry = _base_entry(
            mcp_remotes={"type": "sse", "url": "https://example.com/sse"}
        )
        errs = validate_mcp_registry_fields(entry)
        self.assertEqual(len(errs), 1)
        self.assertIn("mcp_remotes must be list", errs[0])

    def test_remotes_string_rejected(self):
        entry = _base_entry(mcp_remotes="https://example.com/sse")
        errs = validate_mcp_registry_fields(entry)
        self.assertEqual(len(errs), 1)
        self.assertIn("mcp_remotes must be list", errs[0])

    def test_remotes_item_missing_type(self):
        entry = _base_entry(mcp_remotes=[{"url": "https://example.com/sse"}])
        errs = validate_mcp_registry_fields(entry)
        self.assertEqual(len(errs), 1)
        self.assertIn('missing required field "type"', errs[0])

    def test_remotes_item_missing_url(self):
        entry = _base_entry(mcp_remotes=[{"type": "sse"}])
        errs = validate_mcp_registry_fields(entry)
        self.assertEqual(len(errs), 1)
        self.assertIn('missing required field "url"', errs[0])

    def test_remotes_item_not_dict(self):
        entry = _base_entry(mcp_remotes=["https://example.com/sse"])
        errs = validate_mcp_registry_fields(entry)
        self.assertEqual(len(errs), 1)
        self.assertIn("mcp_remotes[0] must be dict", errs[0])

    def test_remotes_item_type_not_string(self):
        entry = _base_entry(
            mcp_remotes=[{"type": 1, "url": "https://example.com/sse"}]
        )
        errs = validate_mcp_registry_fields(entry)
        self.assertEqual(len(errs), 1)
        self.assertIn("mcp_remotes[0].type must be str", errs[0])

    def test_remotes_item_url_not_string(self):
        entry = _base_entry(mcp_remotes=[{"type": "sse", "url": 42}])
        errs = validate_mcp_registry_fields(entry)
        self.assertEqual(len(errs), 1)
        self.assertIn("mcp_remotes[0].url must be str", errs[0])

    def test_remotes_multiple_items_aggregate_errors(self):
        # 多条 item 各自错误聚合
        entry = _base_entry(
            mcp_remotes=[
                {"type": "sse", "url": "https://ok.example.com/sse"},  # 合法
                {"url": "https://no-type.example.com/sse"},  # 缺 type
                {"type": "sse"},  # 缺 url
            ]
        )
        errs = validate_mcp_registry_fields(entry)
        self.assertEqual(len(errs), 2)
        self.assertTrue(any("mcp_remotes[1] missing" in e for e in errs))
        self.assertTrue(any("mcp_remotes[2] missing" in e for e in errs))

    # --- aggregate -----------------------------------------------------------

    def test_multiple_errors_aggregated(self):
        entry = _base_entry(
            mcp_registry_status="bogus",
            mcp_registry_published_at="not-a-timestamp",
            mcp_remotes="not-a-list",
        )
        errs = validate_mcp_registry_fields(entry)
        self.assertEqual(len(errs), 3)


if __name__ == "__main__":
    unittest.main()
