"""Pydantic models for ai-resource-eval evaluation pipeline."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class Decision(str, Enum):
    """Evaluation decision outcome."""

    accept = "accept"
    review = "review"
    reject = "reject"


class McpInstallState(str, Enum):
    """Normalized MCP installability state."""

    ready = "ready"
    needs_config = "needs_config"
    manual = "manual"
    invalid = "invalid"
    unknown = "unknown"


class McpValidationTag(str, Enum):
    """Fixed MCP validation tag vocabulary."""

    readme_config_found = "readme_config_found"
    catalog_config_shape_valid = "catalog_config_shape_valid"
    catalog_config_ready = "catalog_config_ready"
    catalog_config_template = "catalog_config_template"
    catalog_config_missing = "catalog_config_missing"
    catalog_config_wrong = "catalog_config_wrong"
    wrong_config = "wrong_config"
    remote_url = "remote_url"
    local_command = "local_command"
    self_installing_command = "self_installing_command"
    placeholder_env = "placeholder_env"
    placeholder_path = "placeholder_path"
    placeholder_url = "placeholder_url"
    placeholder_variable = "placeholder_variable"
    requires_auth = "requires_auth"
    requires_local_build = "requires_local_build"
    requires_local_clone = "requires_local_clone"
    requires_global_install = "requires_global_install"
    requires_project_context = "requires_project_context"
    requires_local_app = "requires_local_app"
    requires_local_server = "requires_local_server"
    requires_extension = "requires_extension"
    requires_daemon = "requires_daemon"
    missing_config = "missing_config"
    command_invalid = "command_invalid"
    args_invalid = "args_invalid"
    env_invalid = "env_invalid"
    no_mcp_config_found = "no_mcp_config_found"
    insufficient_evidence = "insufficient_evidence"
    sdk_not_server = "sdk_not_server"
    not_mcp_server = "not_mcp_server"


class ContentSource(str, Enum):
    """Primary content source strategy."""

    readme = "readme"
    description = "description"
    # plugin_bundle: 由 PluginContentFetcher 提供，将 .claude-plugin/plugin.json
    # + skills/<n>/SKILL.md + agents/*.md + commands/*.md 拼接成单个 LLM 评估串。
    # 仅 plugin task config 使用；非 plugin entry 命中此 content_source 时 runner
    # 会自动降级到 GitHubFetcher (README) 路径。
    plugin_bundle = "plugin_bundle"


# ---------------------------------------------------------------------------
# EvalItem — catalog entry input
# ---------------------------------------------------------------------------


class EvalItem(BaseModel):
    """A single catalog entry to be evaluated.

    Flexible schema: only ``id`` and ``name`` are required.  All other fields
    are optional so the model can ingest catalog entries that may have varying
    shapes.
    """

    id: str
    name: str
    type: str | None = None
    description: str | None = None
    source_url: str | None = None
    stars: int | None = None
    pushed_at: datetime | str | None = None
    category: str | None = None
    tags: list[str] = Field(default_factory=list)
    tech_stack: list[str] = Field(default_factory=list)
    install: dict[str, Any] | None = None
    source: str | None = None
    last_synced: str | None = None
    added_at: str | None = None
    description_zh: str | None = None
    search_terms: list[str] = Field(default_factory=list)

    # skills.sh Tier 1 源新增字段：install_count 用于派生 install_popularity 信号
    install_count: int | None = None

    # plugin 类型专属：sync_plugins_official.py 计算的 plugin.json manifest 完整度
    # （0.0–1.0），仅对 type == "plugin" 的 entry 有意义；其他类型缺失 / None
    # 表示「不参与该信号」，runner 会从权重表剔除。
    manifest_completeness: float | None = None

    # Existing evaluation / health data (from upstream catalog) — ignored by
    # this harness but accepted so we can round-trip catalog JSON.
    evaluation: dict[str, Any] | None = None
    health: dict[str, Any] | None = None
    final_score: float | None = None
    decision: str | None = None

    model_config = {"extra": "allow"}


# ---------------------------------------------------------------------------
# MetricResult — single dimension output
# ---------------------------------------------------------------------------


class MetricResult(BaseModel):
    """Self-explaining result for a single evaluation dimension.

    ``score`` is clamped to the [1, 5] range.
    """

    score: int = Field(..., description="Integer score 1-5")
    evidence: list[str] = Field(
        default_factory=list,
        description="Evidence strings found in the README supporting the score",
    )
    missing: list[str] = Field(
        default_factory=list,
        description="Content absent from the README that would improve the score",
    )
    suggestion: str = Field(
        default="",
        description="Actionable suggestion for how to score higher",
    )

    @field_validator("score")
    @classmethod
    def clamp_score(cls, v: int) -> int:
        """Clamp score to [1, 5] range."""
        if v < 1:
            return 1
        if v > 5:
            return 5
        return v


# ---------------------------------------------------------------------------
# EvalResult — complete evaluation output
# ---------------------------------------------------------------------------


class HealthSignals(BaseModel):
    """Heuristic health signals (computed locally, not by LLM)."""

    freshness: float = Field(0.0, ge=0, le=100)
    popularity: float = Field(0.0, ge=0, le=100)
    source_trust: float = Field(0.0, ge=0, le=100)
    # 由 skills.sh 提供的 install_count 派生而来，仅做信号采集；默认权重 0 不参与 final_score
    install_popularity: float = Field(0.0, ge=0, le=100)
    # plugin 类型专属：plugin.json manifest 完整度（0-100，由 sync_plugins_official.py
    # 写入 entry.manifest_completeness，0.0-1.0 区间映射到 0-100）。非 plugin 类型
    # 默认 100（完整），由 runner._get_excluded_signals 自动从权重表剔除以保持
    # 与原 3 信号 health_score 等价。
    manifest_completeness: float = Field(100.0, ge=0, le=100)


class EnrichmentData(BaseModel):
    """Enrichment fields produced alongside evaluation metrics in a single LLM call."""

    summary: str = Field("", description="Concise English summary (≤150 chars)")
    summary_zh: str = Field("", description="Concise Chinese summary (≤100 chars)")
    tags: list[str] = Field(default_factory=list, description="3-5 lowercase kebab-case tags")
    tech_stack: list[str] = Field(default_factory=list, description="Languages/frameworks/tools")
    search_terms: list[str] = Field(default_factory=list, description="3-5 bilingual search terms")
    highlights: list[str] = Field(default_factory=list, description="2-3 Chinese feature highlights (≤60 chars each)")

    @field_validator("summary")
    @classmethod
    def truncate_summary(cls, v: str) -> str:
        return v[:150] if len(v) > 150 else v

    @field_validator("summary_zh")
    @classmethod
    def truncate_summary_zh(cls, v: str) -> str:
        return v[:100] if len(v) > 100 else v

    @field_validator("highlights")
    @classmethod
    def truncate_highlights(cls, v: list[str]) -> list[str]:
        return [h[:60] for h in v[:3]]

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, v: list[str]) -> list[str]:
        return [t.lower().strip() for t in v[:5]]


class RiskLevel(str, Enum):
    """Security risk level (aligned with costrict-web SecurityScan)."""

    clean = "clean"
    low = "low"
    medium = "medium"
    high = "high"
    extreme = "extreme"


class SecurityVerdict(str, Enum):
    """Security verdict (aligned with costrict-web SecurityScan)."""

    safe = "safe"
    caution = "caution"
    reject = "reject"


class SecurityPermissions(BaseModel):
    """Permissions block (aligned with costrict-web SecurityScan.permissions)."""

    files: list[str] = Field(default_factory=list)
    network: list[str] = Field(default_factory=list)
    commands: list[str] = Field(default_factory=list)


# verdict 必须满足的 risk_level 映射（spec security-risk-eval 强约束）。
# 把映射表放在模型外便于复用（runner 解析失败检测与文档可读）。
_VERDICT_FOR_RISK: dict[RiskLevel, SecurityVerdict] = {
    RiskLevel.clean: SecurityVerdict.safe,
    RiskLevel.low: SecurityVerdict.safe,
    RiskLevel.medium: SecurityVerdict.caution,
    RiskLevel.high: SecurityVerdict.reject,
    RiskLevel.extreme: SecurityVerdict.reject,
}


class SecurityScanResult(BaseModel):
    """Security scan output (语义与 costrict-web SecurityScan 模型对齐，仅 6 字段)。

    强约束：``verdict`` MUST 满足 risk_level 映射：
        clean / low → safe
        medium → caution
        high / extreme → reject
    """

    risk_level: RiskLevel
    verdict: SecurityVerdict
    red_flags: list[str] = Field(default_factory=list)
    permissions: SecurityPermissions = Field(default_factory=SecurityPermissions)
    summary: str = Field("", description="Concise Chinese summary of the security assessment")
    recommendations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _verdict_matches_risk_level(self) -> SecurityScanResult:
        expected = _VERDICT_FOR_RISK[self.risk_level]
        if self.verdict is not expected:
            raise ValueError(
                f"verdict={self.verdict.value} does not match risk_level="
                f"{self.risk_level.value} (expected {expected.value})"
            )
        return self


class McpInstallabilityData(BaseModel):
    """MCP installability fields produced alongside evaluation metrics."""

    mcp_schema_valid: bool = Field(
        ...,
        description="Whether a Claude-style MCP config can be derived from catalog install metadata or README evidence",
    )
    mcp_install_state: McpInstallState = Field(
        ...,
        description="Normalized install state: ready, needs_config, manual, invalid, or unknown",
    )
    mcp_validation_tags: list[McpValidationTag] = Field(
        default_factory=list,
        description="Fixed validation tags explaining source and blocking reasons",
    )
    mcp_installability_reason: str = Field(
        "",
        description="Short Chinese reason explaining the installability classification",
    )

    @field_validator("mcp_validation_tags")
    @classmethod
    def dedupe_tags(cls, v: list[McpValidationTag]) -> list[McpValidationTag]:
        seen: set[McpValidationTag] = set()
        result: list[McpValidationTag] = []
        for tag in v:
            if tag not in seen:
                seen.add(tag)
                result.append(tag)
        return result

    @field_validator("mcp_installability_reason")
    @classmethod
    def truncate_reason(cls, v: str) -> str:
        return v[:240] if len(v) > 240 else v


class EvalResult(BaseModel):
    """Complete evaluation result for one catalog entry."""

    entry_id: str
    metrics: dict[str, MetricResult] = Field(
        default_factory=dict,
        description="Keyed by dimension name (e.g. 'coding_relevance')",
    )
    enrichment: EnrichmentData | None = Field(
        None,
        description="Enrichment fields from single LLM call (optional)",
    )
    mcp_installability: McpInstallabilityData | None = Field(
        None,
        description="MCP installability fields from single LLM call (optional)",
    )
    security: SecurityScanResult | None = Field(
        None,
        description="Security scan result from independent LLM call (optional)",
    )
    health: HealthSignals = Field(default_factory=HealthSignals)
    llm_score: float | None = Field(
        None,
        ge=0,
        le=100,
        description="LLM-only weighted score before health blending (0-100)",
    )
    final_score: float = Field(
        ...,
        ge=0,
        le=100,
        description="Blended score (LLM × α + health × (1-α)), 0-100",
    )
    decision: Decision
    star_weight: float = Field(
        1.0,
        description="0.0 if star noise detected, else 1.0",
    )
    content_hash: str | None = Field(
        None,
        description="SHA-256 of the content used for evaluation",
    )
    rubric_version: str | None = Field(
        None,
        description='Format: "{major}.{sha8}"',
    )
    model_id: str | None = None
    evaluated_at: datetime | None = None

    @field_validator("star_weight")
    @classmethod
    def validate_star_weight(cls, v: float) -> float:
        """star_weight must be 0.0 or 1.0."""
        if v not in (0.0, 1.0):
            raise ValueError("star_weight must be 0.0 or 1.0")
        return v


# ---------------------------------------------------------------------------
# TaskConfig — YAML task configuration
# ---------------------------------------------------------------------------


class MetricWeight(BaseModel):
    """A single metric with its weight in the task configuration."""

    metric: str
    weight: float = Field(..., gt=0, le=1)


class HeuristicSignalWeight(BaseModel):
    """A single heuristic signal with its weight."""

    signal: str
    # 允许 weight=0 表示「采集但不计入 final_score」（如 install_popularity 默认）
    weight: float = Field(..., ge=0, le=1)


class StarRoutingConfig(BaseModel):
    """Star noise routing configuration."""

    zero_weight_sources: list[str] = Field(default_factory=list)
    monorepo_threshold: int = Field(5, ge=1)


class ThresholdsConfig(BaseModel):
    """Decision thresholds for accept/review/reject."""

    accept: float = Field(65, ge=0, le=100)
    review: float = Field(40, ge=0, le=100)

    @model_validator(mode="after")
    def accept_above_review(self) -> ThresholdsConfig:
        if self.accept <= self.review:
            raise ValueError(
                f"accept threshold ({self.accept}) must be greater than "
                f"review threshold ({self.review})"
            )
        return self


class TaskConfig(BaseModel):
    """Parsed YAML task configuration.

    Validates that metric weights and heuristic signal weights each sum to 1.0
    (tolerance ±0.001).
    """

    task: str
    content_source: ContentSource = ContentSource.readme
    content_paths: list[str] = Field(default_factory=lambda: ["README.md"])
    content_fallback: str = "description"

    # 允许 metrics 为空：health-only 评估（如 plugin task）不依赖 LLM 维度，
    # 仅靠 heuristic_signals 计算 final_score。详见 plugin.yaml。
    metrics: list[MetricWeight] = Field(default_factory=list)
    heuristic_signals: list[HeuristicSignalWeight] = Field(default_factory=list)

    star_routing: StarRoutingConfig = Field(default_factory=StarRoutingConfig)
    thresholds: ThresholdsConfig = Field(default_factory=ThresholdsConfig)
    rubric_major_version: int = Field(1, ge=1)
    health_blend_alpha: float = Field(
        0.85,
        ge=0,
        le=1,
        description="Blend ratio: final = α × llm_score + (1-α) × health_score",
    )
    enrichment: bool = Field(
        True,
        description="When true, LLM prompt includes enrichment section for tags/summary/etc.",
    )
    mcp_installability: bool = Field(
        False,
        description="When true, LLM prompt includes MCP installability fields.",
    )
    security_scan: bool = Field(
        False,
        description=(
            "When true, the runner makes an independent security-scan LLM call "
            "and attaches a SecurityScanResult to EvalResult.security. metrics "
            "and heuristic_signals are expected to be empty in this mode."
        ),
    )

    @model_validator(mode="after")
    def validate_weights(self) -> TaskConfig:
        """Ensure metric weights and heuristic signal weights each sum to 1.0.

        当 ``metrics`` 为空（health-only 任务，如 plugin）时跳过 metric 权重校验；
        runner 会在 metrics 为空时直接走 ``final_score = health_score`` 路径。
        """
        if self.metrics:
            metric_sum = sum(m.weight for m in self.metrics)
            if abs(metric_sum - 1.0) > 0.001:
                raise ValueError(
                    f"Metric weights must sum to 1.0 (±0.001), got {metric_sum:.4f}"
                )

        if self.heuristic_signals:
            # 跳过 weight=0 的信号（如 install_popularity 默认）：仅采集不计入综合分
            non_zero = [s for s in self.heuristic_signals if s.weight > 0]
            if non_zero:
                signal_sum = sum(s.weight for s in non_zero)
                if abs(signal_sum - 1.0) > 0.001:
                    raise ValueError(
                        f"Heuristic signal weights must sum to 1.0 (±0.001), got {signal_sum:.4f}"
                    )

        return self
