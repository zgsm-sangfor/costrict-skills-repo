"""Merged prompt builder — assembles metric rubrics into a single LLM system prompt."""

from __future__ import annotations

from pydantic import BaseModel, Field

from ai_resource_eval.api.metric import BaseMetric
from ai_resource_eval.api.registry import Registry
from ai_resource_eval.api.types import (
    EnrichmentData,
    McpInstallabilityData,
    MetricResult,
)

from ai_resource_eval.metrics.coding_relevance import CodingRelevance
from ai_resource_eval.metrics.doc_completeness import DocCompleteness
from ai_resource_eval.metrics.desc_accuracy import DescAccuracy
from ai_resource_eval.metrics.writing_quality import WritingQuality
from ai_resource_eval.metrics.specificity import Specificity
from ai_resource_eval.metrics.install_clarity import InstallClarity


# ---------------------------------------------------------------------------
# LLM response model
# ---------------------------------------------------------------------------


class LLMEvalResponse(BaseModel):
    """Expected JSON output from the LLM evaluation call.

    The LLM must return one ``MetricResult`` per dimension, keyed by metric
    name (e.g. ``"coding_relevance"``).  When enrichment is enabled, also
    contains an ``enrichment`` object.
    """

    metrics: dict[str, MetricResult] = Field(
        ...,
        description="Mapping of metric name to its evaluation result",
    )
    enrichment: EnrichmentData | None = Field(
        None,
        description="Enrichment fields (tags, summary, etc.) when enabled",
    )
    mcp_installability: McpInstallabilityData | None = Field(
        None,
        description="MCP installability fields when enabled for MCP tasks",
    )


# ---------------------------------------------------------------------------
# Prompt building functions
# ---------------------------------------------------------------------------


_SYSTEM_PREAMBLE = (
    "You are an expert evaluator of AI coding resources. You will be given a "
    "README (and optionally a catalog description) for a coding resource. "
    "Evaluate it across the following dimensions.\n"
    "\n"
    "For each dimension, return a JSON object with:\n"
    "- score: integer 1-5 (follow the anchors strictly)\n"
    "- evidence: list of strings — quotes or observations from the README\n"
    "- missing: list of strings — what is absent that would improve the score\n"
    "- suggestion: string — one actionable improvement tip\n"
    "\n"
    "Return your evaluation as a JSON object with a top-level key 'metrics' "
    "mapping each dimension name to its result object.\n"
    "\n"
    "---\n\n"
)

_ENRICHMENT_SECTION = (
    "## Enrichment Fields\n\n"
    "In addition to the metrics above, produce an 'enrichment' object at the "
    "same level as 'metrics' in your JSON output. The enrichment object MUST "
    "contain the following fields:\n\n"
    "- **summary**: A concise one-sentence description of the resource's core "
    "functionality. MUST be in English (≤150 characters), regardless of the "
    "README's original language.\n"
    "- **summary_zh**: A concise one-sentence description in Chinese "
    "(≤100 characters), regardless of the README's original language.\n"
    "- **tags**: A list of 3-5 lowercase kebab-case tags derived from the "
    "README content (e.g. ['mcp-server', 'database', 'python']). Tags should "
    "be specific to the resource, not generic.\n"
    "- **tech_stack**: A list of programming languages, frameworks, and tools "
    "mentioned or used in the README (e.g. ['python', 'fastapi', 'docker']).\n"
    "- **search_terms**: A list of 3-5 search-friendly terms/phrases in mixed "
    "languages (English + Chinese) for semantic recall (e.g. "
    "['binary analysis', '二进制分析', 'reverse engineering']).\n"
    "- **highlights**: A list of 2-3 short feature highlights in Chinese "
    "(≤60 characters each), suitable for catalog display "
    "(e.g. ['支持 15+ 数据库类型', 'Docker 一键部署']).\n"
    "\n"
    "---\n\n"
)


_ENRICHMENT_ONLY_PREAMBLE = (
    "You are an expert evaluator of AI coding resources. You will be given a "
    "README (and optionally a catalog description) for a coding resource. "
    "Produce ONLY the enrichment fields described below — no metric scores.\n"
    "\n"
    "Return your output as a JSON object with a top-level key 'enrichment' "
    "(plus an empty 'metrics' object for schema compliance).\n"
    "\n"
    "---\n\n"
)


_MCP_INSTALLABILITY_SECTION = (
    "## MCP Installability Fields\n\n"
    "For MCP server resources, also produce an 'mcp_installability' object at "
    "the same level as 'metrics' and 'enrichment'. Use ONLY the catalog install "
    "metadata and README evidence shown in the user prompt. Do not invent or "
    "infer package names, commands, arguments, or URLs from the resource name, "
    "repository name, or description.\n\n"
    "The mcp_installability object MUST contain:\n\n"
    "- **mcp_schema_valid**: boolean. True means a Claude-style MCP config can "
    "be derived from catalog install metadata or README evidence. Local stdio "
    "configs require command:string plus optional args:string[] and env:"
    "object<string,string>. Remote configs require url:string plus optional "
    "auth/header fields. This field does NOT mean the server is ready to run.\n"
    "- **mcp_install_state**: one of 'ready', 'needs_config', 'manual', "
    "'invalid', 'unknown'.\n"
    "- **mcp_validation_tags**: list of tags from the fixed vocabulary below.\n"
    "- **mcp_installability_reason**: one short Chinese sentence explaining "
    "the classification.\n\n"
    "State rules:\n"
    "- ready: concrete config is available and can reasonably run after being "
    "written to Claude config. Self-installing launchers such as 'npx -y', "
    "'uvx', and 'bunx' may be ready when no other user-specific setup exists.\n"
    "- needs_config: config shape is clear, but the user must provide secrets, "
    "tokens, org IDs, URLs, local paths, variables, project context, local "
    "clone/build, global install, or a local app, extension, server, or daemon.\n"
    "- manual: the resource may be usable, but neither catalog metadata nor "
    "README evidence gives concrete command/args/env or url config. Smithery "
    "or install-helper instructions alone are manual unless the resulting MCP "
    "config is shown.\n"
    "- invalid: evidence shows the entry is not an MCP server, is only an SDK/"
    "framework/library for building MCP servers, catalog config points to the "
    "wrong package and README lacks a corrected concrete config, or the config "
    "field types cannot form a Claude-style MCP config.\n"
    "- unknown: available evidence is genuinely insufficient to decide.\n\n"
    "Placeholder handling: if a Claude-style config contains placeholders such "
    "as '/path/to', 'path/to', 'C:\\\\ABSOLUTE\\\\PATH', '<...>', '{...}', "
    "'[...]', '{{...}}', 'YOUR_*', 'your_*', or '${VAR}', set "
    "mcp_schema_valid=true and mcp_install_state='needs_config'.\n\n"
    "README override rule: README evidence may override a missing or wrong "
    "catalog config only when it explicitly shows the corrected package, "
    "command, args, env, or url. If catalog config is wrong and README does "
    "not show a correction, do not guess a replacement; classify as manual or "
    "invalid according to the evidence.\n\n"
    "Fixed mcp_validation_tags vocabulary: readme_config_found, "
    "catalog_config_shape_valid, catalog_config_ready, catalog_config_template, "
    "catalog_config_missing, catalog_config_wrong, wrong_config, remote_url, "
    "local_command, self_installing_command, placeholder_env, placeholder_path, "
    "placeholder_url, placeholder_variable, requires_auth, requires_local_build, "
    "requires_local_clone, requires_global_install, requires_project_context, "
    "requires_local_app, requires_local_server, requires_extension, "
    "requires_daemon, missing_config, command_invalid, args_invalid, "
    "env_invalid, no_mcp_config_found, insufficient_evidence, sdk_not_server, "
    "not_mcp_server.\n"
    "\n"
    "---\n\n"
)


def build_system_prompt(
    metrics: list[BaseMetric],
    *,
    enrichment: bool = False,
    mcp_installability: bool = False,
) -> str:
    """Concatenate all metric rubrics into one system prompt.

    Parameters
    ----------
    metrics:
        List of metric instances whose rubrics should be included.  When the
        list is empty and ``enrichment`` is True, an enrichment-only preamble
        is used (no metric rubric sections).
    enrichment:
        When True, append the enrichment section to the prompt.
    mcp_installability:
        When True, append the MCP installability section to the prompt.

    Returns
    -------
    str
        A complete system prompt ready to send to the LLM.
    """
    if not metrics:
        # health-only + enrichment（如 plugin task）：跳过 metric 介绍，
        # 直接给 enrichment 指令。无 metrics 又无 enrichment 的退化路径
        # 仍输出 preamble，避免 prompt 为空字符串。
        if enrichment:
            prompt = _ENRICHMENT_ONLY_PREAMBLE + _ENRICHMENT_SECTION
            if mcp_installability:
                prompt += _MCP_INSTALLABILITY_SECTION
            return prompt
        if mcp_installability:
            return _SYSTEM_PREAMBLE + _MCP_INSTALLABILITY_SECTION
        return _SYSTEM_PREAMBLE
    parts = [_SYSTEM_PREAMBLE]
    for metric in metrics:
        parts.append(metric.build_rubric())
        parts.append("\n---\n\n")
    if enrichment:
        parts.append(_ENRICHMENT_SECTION)
    if mcp_installability:
        parts.append(_MCP_INSTALLABILITY_SECTION)
    return "".join(parts)


def build_output_schema(
    metric_names: list[str],
    *,
    enrichment: bool = False,
    mcp_installability: bool = False,
) -> dict:
    """Return the JSON schema for the expected LLM evaluation output.

    The schema describes a top-level ``metrics`` object where each key is a
    metric name and each value conforms to ``MetricResult``.  When
    *enrichment* is True, an ``enrichment`` object is added to the schema.

    Parameters
    ----------
    metric_names:
        List of dimension names that the LLM should produce results for.
    enrichment:
        When True, include the enrichment object in the schema.
    mcp_installability:
        When True, include the MCP installability object in the schema.

    Returns
    -------
    dict
        A JSON-serialisable schema dict.
    """
    metric_result_schema = MetricResult.model_json_schema()

    required = ["metrics"]
    properties: dict = {
        "metrics": {
            "type": "object",
            "required": metric_names,
            "properties": {
                name: {"$ref": "#/$defs/MetricResult"}
                for name in metric_names
            },
            "additionalProperties": False,
        },
    }
    defs: dict = {
        "MetricResult": metric_result_schema,
    }

    if enrichment:
        enrichment_schema = EnrichmentData.model_json_schema()
        properties["enrichment"] = {"$ref": "#/$defs/EnrichmentData"}
        required.append("enrichment")
        defs["EnrichmentData"] = enrichment_schema

    if mcp_installability:
        mcp_installability_schema = McpInstallabilityData.model_json_schema()
        nested_defs = mcp_installability_schema.pop("$defs", {})
        defs.update(nested_defs)
        properties["mcp_installability"] = {
            "$ref": "#/$defs/McpInstallabilityData"
        }
        required.append("mcp_installability")
        defs["McpInstallabilityData"] = mcp_installability_schema

    return {
        "type": "object",
        "required": required,
        "properties": properties,
        "$defs": defs,
    }


# ---------------------------------------------------------------------------
# Default metric registry
# ---------------------------------------------------------------------------

#: Global registry containing the six default evaluation metrics.
metric_registry: Registry[BaseMetric] = Registry()

_DEFAULT_METRICS: list[type[BaseMetric]] = [
    CodingRelevance,
    DocCompleteness,
    DescAccuracy,
    WritingQuality,
    Specificity,
    InstallClarity,
]

for _cls in _DEFAULT_METRICS:
    _instance = _cls()
    metric_registry.register(_instance.name, _instance)
