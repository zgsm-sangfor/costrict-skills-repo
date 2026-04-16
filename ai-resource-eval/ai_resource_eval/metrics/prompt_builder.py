"""Merged prompt builder — assembles metric rubrics into a single LLM system prompt."""

from __future__ import annotations

from pydantic import BaseModel, Field

from ai_resource_eval.api.metric import BaseMetric
from ai_resource_eval.api.registry import Registry
from ai_resource_eval.api.types import MetricResult

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
    name (e.g. ``"coding_relevance"``).
    """

    metrics: dict[str, MetricResult] = Field(
        ...,
        description="Mapping of metric name to its evaluation result",
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
    "Return your evaluation as a JSON object with a single key 'metrics' "
    "mapping each dimension name to its result object.\n"
    "\n"
    "---\n\n"
)


def build_system_prompt(metrics: list[BaseMetric]) -> str:
    """Concatenate all metric rubrics into one system prompt.

    Parameters
    ----------
    metrics:
        List of metric instances whose rubrics should be included.

    Returns
    -------
    str
        A complete system prompt ready to send to the LLM.
    """
    parts = [_SYSTEM_PREAMBLE]
    for metric in metrics:
        parts.append(metric.build_rubric())
        parts.append("\n---\n\n")
    return "".join(parts)


def build_output_schema(metric_names: list[str]) -> dict:
    """Return the JSON schema for the expected LLM evaluation output.

    The schema describes a top-level ``metrics`` object where each key is a
    metric name and each value conforms to ``MetricResult``.

    Parameters
    ----------
    metric_names:
        List of dimension names that the LLM should produce results for.

    Returns
    -------
    dict
        A JSON-serialisable schema dict.
    """
    metric_result_schema = MetricResult.model_json_schema()

    return {
        "type": "object",
        "required": ["metrics"],
        "properties": {
            "metrics": {
                "type": "object",
                "required": metric_names,
                "properties": {
                    name: {"$ref": "#/$defs/MetricResult"}
                    for name in metric_names
                },
                "additionalProperties": False,
            },
        },
        "$defs": {
            "MetricResult": metric_result_schema,
        },
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
