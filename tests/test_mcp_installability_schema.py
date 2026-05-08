"""Tests for optional MCP installability fields in catalog/schema.json."""

from __future__ import annotations

import json
from pathlib import Path


SCHEMA_PATH = Path(__file__).resolve().parents[1] / "catalog" / "schema.json"


def _schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


def _properties() -> dict:
    return _schema()["items"]["properties"]


def test_mcp_installability_fields_optional():
    required = _schema()["items"]["required"]
    assert "mcp_schema_valid" not in required
    assert "mcp_install_state" not in required
    assert "mcp_validation_tags" not in required
    assert "mcp_installability_reason" not in required


def test_mcp_schema_valid_is_boolean():
    prop = _properties()["mcp_schema_valid"]
    assert prop["type"] == "boolean"


def test_mcp_install_state_enum():
    prop = _properties()["mcp_install_state"]
    assert prop["type"] == "string"
    assert prop["enum"] == [
        "ready",
        "needs_config",
        "manual",
        "invalid",
        "unknown",
    ]


def test_mcp_validation_tags_array_and_enum():
    prop = _properties()["mcp_validation_tags"]
    assert prop["type"] == "array"
    assert prop["items"]["type"] == "string"
    enum_values = set(prop["items"]["enum"])
    assert "readme_config_found" in enum_values
    assert "placeholder_path" in enum_values
    assert "insufficient_evidence" in enum_values
    assert "made_up_tag" not in enum_values


def test_mcp_installability_reason_is_string():
    prop = _properties()["mcp_installability_reason"]
    assert prop["type"] == "string"
