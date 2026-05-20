"""Security scan prompt builder for the security_scan task.

复刻自 costrict-web ``server/internal/services/scan_service.go`` 中的安全审查
prompt（中文，含红线/高/中/低风险分类规则），但仅输出 6 个字段（去掉 category
与 builtin_tags 段落），并显式声明 verdict ↔ risk_level 的映射约束。

非 MCP 类型的 entry 复用 fetcher 拉到的 README/SKILL.md；type=mcp 的 entry
由 eval_bridge 把序列化后的 install.config 注入到 description 字段中喂给 LLM。
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from pydantic import BaseModel

from ai_resource_eval.api.types import SecurityScanResult

if TYPE_CHECKING:  # pragma: no cover
    from ai_resource_eval.api.types import EvalItem


# ---------------------------------------------------------------------------
# LLM response model
# ---------------------------------------------------------------------------


class LLMSecurityResponse(BaseModel):
    """Top-level JSON the LLM is asked to return for security_scan task.

    Mirrors :class:`SecurityScanResult` 一对一；包成顶层 model 便于 runner
    的 ``pydantic_model=`` 校验 hook 复用现有 retry/解析路径。
    """

    risk_level: str
    verdict: str
    red_flags: list[str] = []
    permissions: dict = {}
    summary: str = ""
    recommendations: list[str] = []


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------


SECURITY_SCAN_SYSTEM_PROMPT = """\
你是一位经验丰富的 AI 编程资源安全审查员。你的任务是对一段「能力项」（可能是
Claude Code Skill、MCP server 的安装配置、Cursor/Windsurf rule、prompt 或 plugin
包）进行安全风险评估，并输出严格的结构化 JSON。

## 输出字段（严格 6 个，不要新增字段）

返回一个顶层 JSON 对象，包含且仅包含以下键：

- `risk_level`: 风险等级，枚举之一 `clean` | `low` | `medium` | `high` | `extreme`
- `verdict`: 处置结论，枚举之一 `safe` | `caution` | `reject`
- `red_flags`: list[str]，命中的具体风险点（中文短句，每条 ≤ 60 字），无则空数组
- `permissions`: object，请求的权限范围，三个固定子键：
  - `files`: list[str]，会读/写的文件或路径模式
  - `network`: list[str]，访问的域名 / endpoint / 协议
  - `commands`: list[str]，要执行的外部命令 / 可执行文件
  无对应内容时各子键为空数组，但 `permissions` 对象本身必须出现
- `summary`: str，中文一句话总结评估结论与主要依据（≤ 120 字）
- `recommendations`: list[str]，给用户的处置建议（中文短句，每条 ≤ 80 字）；
  当 risk_level=clean 时通常为空数组

## verdict 必须与 risk_level 匹配

这是强约束，违反会导致整次评估被丢弃：

- `clean` / `low` → `safe`
- `medium` → `caution`
- `high` / `extreme` → `reject`

## 风险分级规则

### extreme（红线，verdict=reject）
凡有以下任一表现，直接判定为 extreme：

- 主动窃取凭据、token、ssh key、env 中的 secret、~/.aws、~/.kube、~/.config
- 上传用户文件 / 命令输出 / 剪贴板 / 浏览器历史到任意远端
- 反向 shell、远程代码执行 endpoint、安装/启动后门或守护进程
- 删除 / 加密 / 篡改用户本地文件且无明确用户意图（例如 `rm -rf`、改写 .git）
- 在用户机器上挖矿 / 隐蔽 RPC

### high（verdict=reject）
- 执行高权限命令但未在文档中明确告知（sudo / 修改系统配置 / 修改 /etc）
- 把用户数据（含 prompt 内容、对话记录）传到非用户授权的第三方
- 安装额外组件、远程下载脚本后直接 eval/exec
- 默认开启遥测且无关闭开关

### medium（verdict=caution）
- 调用外部 API 但用途合理且文档清晰，需用户提供 API Key 才能用
- 读取本机源代码 / 项目文件用于其本职功能（如 code review skill）
- 在用户机器上写入文件但限定在工作目录内
- 执行 shell 命令但命令固定且文档显式列出

### low（verdict=safe）
- 仅本地纯计算 / 字符串处理 / 文档展示
- 只读用户已显式打开的文件
- 调用单一公共 API 且不传送敏感信息

### clean（verdict=safe）
- 纯文本指令 / prompt 模版 / rule，不触发任何代码执行或外部 IO

## 评估输入约定

- 你会拿到 entry 的元信息（name / type / source / description）和一段「内容」。
  「内容」可能是 SKILL.md / README.md / plugin manifest / 或对 MCP 而言的
  install.config 序列化 JSON 文本。
- 对 MCP entry：重点看 command / args / env / url 中是否有可疑 endpoint、
  危险命令或 placeholder（含 placeholder 不等于风险，但 command 引用本地任意路径
  且无说明属于 medium）。
- 对 skill / rule / prompt：重点看是否指示 LLM 执行远端命令、写文件、传输数据。
- 对 plugin：重点看 plugin.json 的 commands / agents 列表与捆绑的 SKILL.md 内容。

## 严格输出要求

- 只输出一个顶层 JSON 对象，**不要**附加解释文字 / Markdown / 代码块围栏
- 字段必须严格按照本文档约定，**不要**增加 category、builtin_tags 或任何额外键
- 中文字段用中文短句
- `verdict` **必须**严格按 risk_level 推导（`clean`/`low`→`safe`、`medium`→`caution`、
  `high`/`extreme`→`reject`），不允许出现 `medium`+`safe` 这种自相矛盾的组合
- 当 entry 内容明显不足以评估时（如 install.config 仅含 `method`、description 只有 1-2 句话），
  默认给 `risk_level=clean` + `verdict=safe` + 空 `red_flags`，并在 summary 说明"内容不足以评估"。
  **不要**为了"保守"硬推到 medium——保守的代价是把无害条目错标为黄牌，污染前端展示
- 只有在内容中能看到具体可执行命令 / 远端 endpoint / 敏感权限请求时，才往 medium 及以上走
- 不要返回错误、不要拒绝、不要要求更多信息
"""


# ---------------------------------------------------------------------------
# Schema builder
# ---------------------------------------------------------------------------


def build_security_output_schema() -> dict:
    """Return a JSON schema describing the top-level security_scan output.

    Schema 字段与 :class:`SecurityScanResult` 一一对应。runner 把它作为
    structured output schema 传给 judge，解析后用 SecurityScanResult.model_validate
    做强校验（含 verdict ↔ risk_level 约束）。
    """
    return {
        "type": "object",
        "required": [
            "risk_level",
            "verdict",
            "red_flags",
            "permissions",
            "summary",
            "recommendations",
        ],
        "properties": {
            "risk_level": {
                "type": "string",
                "enum": ["clean", "low", "medium", "high", "extreme"],
            },
            "verdict": {
                "type": "string",
                "enum": ["safe", "caution", "reject"],
            },
            "red_flags": {
                "type": "array",
                "items": {"type": "string"},
            },
            "permissions": {
                "type": "object",
                "required": ["files", "network", "commands"],
                "properties": {
                    "files": {"type": "array", "items": {"type": "string"}},
                    "network": {"type": "array", "items": {"type": "string"}},
                    "commands": {"type": "array", "items": {"type": "string"}},
                },
                "additionalProperties": False,
            },
            "summary": {"type": "string"},
            "recommendations": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "additionalProperties": False,
    }


# ---------------------------------------------------------------------------
# User prompt builder
# ---------------------------------------------------------------------------


# content 长度上限：超过该字符数会被截断。prompts.chat 等仓库把上百条 prompt
# 塞进一个 5MB+ 的 PROMPTS.md，fetcher 拉到全文后会超出 DeepSeek 等模型的
# 1M token 上下文。截断阈值定保守一点（~50KB ≈ 15k token），给 metadata 头
# 与 system prompt 留余量；description 已经在 metadata 头出现，截断后 LLM
# 仍能基于 description + name + source_url 给出评估。
_MAX_SECURITY_CONTENT_CHARS = 50_000


def build_security_user_prompt(entry: "EvalItem", content: str) -> str:
    """Build the security_scan user prompt with entry metadata + content.

    与质量评分共用相似的结构（metadata 头 + 分隔 + 内容），但措辞侧重 "请审查
    该 entry 的安全风险"。
    """
    parts: list[str] = [f"# 待审查能力项: {entry.name}\n"]

    if entry.type:
        parts.append(f"Type: {entry.type}\n")
    if entry.description:
        parts.append(f"Description: {entry.description}\n")
    if entry.source_url:
        parts.append(f"Source: {entry.source_url}\n")
    if entry.tags:
        parts.append(f"Tags: {', '.join(entry.tags)}\n")

    # MCP install.config 元数据：当 entry 是 MCP 且 eval_bridge 已经把 install.config
    # 合成内容写进 content 时，install 字段也保留——此处再单独列出便于 LLM 聚焦。
    if entry.install and isinstance(entry.install, dict):
        config_block = json.dumps(entry.install, ensure_ascii=False, indent=2, sort_keys=True)
        parts.append("\n## install metadata\n\n```json\n")
        parts.append(config_block)
        parts.append("\n```\n")

    parts.append("\n---\n\n")
    parts.append("## 评估内容\n\n")
    if content and len(content) > _MAX_SECURITY_CONTENT_CHARS:
        truncated = content[:_MAX_SECURITY_CONTENT_CHARS]
        parts.append(truncated)
        parts.append(
            f"\n\n[...内容截断：原文 {len(content)} 字符，仅保留前 "
            f"{_MAX_SECURITY_CONTENT_CHARS} 字符。请基于 description 与已提供片段评估，"
            f"截断常见原因：多条目共享 README/大型 prompt 集合，单条 entry 的相关内容已被 "
            f"description 概括。]"
        )
    else:
        parts.append(content or "(no content provided)")

    return "".join(parts)


def build_security_synth_content_for_mcp(install: dict | None) -> str:
    """构造 MCP entry 的合成评估内容（序列化 install.config 为可读 JSON）。

    返回值同时承担两个用途：
    1. 作为 user prompt 中 ``## 评估内容`` 块的文本
    2. 其 SHA-256 作为 entry.security.content_hash（保证 install 配置变化触发重评）

    install 为空或非 dict 时返回字符串 ``"(no install metadata)"``，让 LLM 知道
    确实没东西可看（不构造假数据，避免误评）。
    """
    if not install or not isinstance(install, dict):
        return "(no install metadata)"

    relevant_keys = ("method", "config", "placeholder_hints", "remotes")
    distilled = {k: install[k] for k in relevant_keys if k in install}
    if not distilled:
        distilled = install
    return json.dumps(distilled, ensure_ascii=False, indent=2, sort_keys=True)


__all__ = [
    "LLMSecurityResponse",
    "SECURITY_SCAN_SYSTEM_PROMPT",
    "build_security_output_schema",
    "build_security_user_prompt",
    "build_security_synth_content_for_mcp",
]
