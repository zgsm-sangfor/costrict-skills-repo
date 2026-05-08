"""Tests for optional MCP installability fields in catalog/schema.json."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import jsonschema


SCHEMA_PATH = Path(__file__).resolve().parents[1] / "catalog" / "schema.json"


def _schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


def _base_entry(**overrides) -> dict:
    entry = {
        "id": "test-mcp",
        "name": "Test MCP",
        "type": "mcp",
        "description": "Test MCP server",
        "source_url": "https://github.com/example/test-mcp",
        "stars": 10,
        "category": "tooling",
        "tags": ["mcp-server"],
        "tech_stack": ["python"],
        "install": {"method": "manual"},
        "source": "curated",
        "last_synced": "2026-05-08",
        "added_at": "2026-05-08",
    }
    entry.update(overrides)
    return entry


def _validate(entry: dict) -> None:
    jsonschema.Draft7Validator(_schema()).validate([entry])


def test_mcp_installability_all_fields_valid():
    _validate(
        _base_entry(
            mcp_schema_valid=True,
            mcp_install_state="needs_config",
            mcp_validation_tags=["readme_config_found", "placeholder_path"],
            mcp_installability_reason="README 配置包含本地路径占位。",
        )
    )


def test_mcp_installability_fields_optional():
    _validate(_base_entry())


def test_mcp_installability_invalid_state_rejected():
    entry = _base_entry(mcp_install_state="broken")
    validator = jsonschema.Draft7Validator(_schema())
    errors = list(validator.iter_errors([entry]))
    assert errors
    assert any("broken" in str(error.message) for error in errors)


def test_mcp_installability_tags_must_be_array():
    entry = _base_entry(mcp_validation_tags="placeholder_path")
    validator = jsonschema.Draft7Validator(_schema())
    errors = list(validator.iter_errors([entry]))
    assert errors
    assert any("is not of type 'array'" in str(error.message) for error in errors)


def test_mcp_installability_invalid_tag_rejected():
    entry = _base_entry(mcp_validation_tags=["made_up_tag"])
    validator = jsonschema.Draft7Validator(_schema())
    errors = list(validator.iter_errors([entry]))
    assert errors
    assert any("made_up_tag" in str(error.message) for error in errors)


def test_non_mcp_entry_may_omit_mcp_installability_fields():
    entry = copy.deepcopy(_base_entry(type="skill", id="test-skill"))
    _validate(entry)
