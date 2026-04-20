# Evo Rubric — 客户端质量演化评分标准

本文档是 `/eac:evo` 命令所用评分体系的**规范源**。4 个平台的 evo 命令文件（claude-code / opencode / costrict / vscode-costrict）在此基础上撰写 LLM 评分与改进 prompt。

**rubric 改编自**：[darwin-skill](https://github.com/alchaincyf/darwin-skill)（MIT License © 花叔）——darwin-skill 原 rubric 为 8 维（总分 100），包含"实测表现"动态测试维。本仓库在客户端按需场景下去除了该维，保留结构 + 写作导向的 7 维（适配 skill）与简化 4 维（适配 prompt/rule）。

> 📖 **与 catalog 6 维 rubric 的关系**
>
> catalog 管线（`ai-resource-eval`，服务端、CI）的 6 维 rubric（coding_relevance / doc_completeness / desc_accuracy / writing_quality / specificity / install_clarity）面向"值不值得入库推荐"。evo 的 7 维 / 4 维 rubric 面向"本机装下来之后能否被 Agent 高质量执行"。**两套 rubric 视角不同、各自运行、互不合并**。

---

## Skill 类型 — 7 维 rubric（总分 100）

| # | 维度（英文 key） | 中文 | 权重 | 评估对象 |
|---|----------------|------|------|---------|
| D1 | `frontmatter_description_quality` | Frontmatter 描述质量 | 10 | frontmatter.description 字段 |
| D2 | `workflow_clarity` | 工作流清晰度 | 20 | 正文步骤、阶段、流程 |
| D3 | `instruction_specificity` | 指令具体性 | 20 | 每条指令的可执行性 |
| D4 | `edge_case_coverage` | 边界条件覆盖 | 15 | 异常/错误处理说明 |
| D5 | `checkpoint_design` | 检查点设计 | 10 | 用户确认节点与防失控机制 |
| D6 | `resource_integration` | 资源整合度 | 5 | references/scripts/assets 引用 |
| D7 | `overall_architecture` | 整体架构 | 20 | 层次、冗余、一致性 |

### 每维 1-10 分档描述

打分维度采用 1-10 分整数。每维加权得分 = 原始分 × 权重 / 10。总分 = 所有维度加权得分之和（0-100）。

#### D1 — Frontmatter 描述质量（权重 10）

评估 `description` 字段能否让 Agent 准确判断何时激活此 skill。

| 分值 | 描述 |
|------|------|
| 1-3 | description 缺失、≤20 字、或只是重复 name，Agent 无法据此判断触发时机 |
| 4-5 | 有描述但模糊（"处理文件"、"辅助开发"等），缺少"做什么"或"何时用"其中之一 |
| 6-7 | 包含"做什么"+"何时用"，但缺具体触发词/关键场景，容易误触发或漏触发 |
| 8-10 | 同时覆盖"做什么/何时用/触发词"，≤1024 字符，中英文触发词齐全；Agent 能精确判断 |

**示例**：
- **1 分**：`description: "Python 助手"`
- **5 分**：`description: "处理 Python 测试相关任务"`
- **10 分**：`description: "For pytest-based Python projects: scaffold tests, fix failures, improve coverage. Trigger words: 写测试, pytest, 单元测试, 覆盖率, test coverage, unit test."`

#### D2 — 工作流清晰度（权重 20）

评估正文中的步骤/阶段是否可直接按图索骥执行。

| 分值 | 描述 |
|------|------|
| 1-3 | 无步骤结构，整段叙述，读完不知道第一步做什么 |
| 4-5 | 有步骤但无序号或层次混乱，部分步骤跳跃（如从 1 到 3） |
| 6-7 | 步骤有序号/阶段划分，但部分步骤输入/输出不明 |
| 8-10 | 线性清晰的阶段（Phase / Step）+ 每步明确的输入、动作、输出；新手可无需解读就执行 |

#### D3 — 指令具体性（权重 20）

评估指令是不是"可直接执行"级别。

| 分值 | 描述 |
|------|------|
| 1-3 | 全部是抽象动词（"处理"、"分析"、"优化"），无任何参数/格式/示例 |
| 4-5 | 有部分具体动作但缺参数（"运行测试"但没说哪些文件/哪个框架） |
| 6-7 | 大多数指令具体，少数关键节点仍模糊 |
| 8-10 | 每条关键指令都带具体命令、参数、格式或示例；直接复制执行即可 |

#### D4 — 边界条件覆盖（权重 15）

评估对异常路径、错误、边界情况的说明。

| 分值 | 描述 |
|------|------|
| 1-3 | 完全不提异常，假设"一切理想" |
| 4-5 | 零散提及某一类错误，无系统性处理 |
| 6-7 | 关键步骤有 "如果 X 失败则 Y" 的 fallback，但覆盖不全 |
| 8-10 | 有完整的异常/边界表格（失败场景 × 触发条件 × 处理动作），原则明示（如"先告知用户再处理"） |

#### D5 — 检查点设计（权重 10）

评估是否在关键决策前插入用户确认、防止 Agent 自主失控。

| 分值 | 描述 |
|------|------|
| 1-3 | 无任何用户确认节点，Agent 全程自主跑到底 |
| 4-5 | 有 1 个确认点（通常在最终输出前） |
| 6-7 | 重要决策前都有确认，但确认展示信息不足（"确认？"而非"确认 X，将执行 Y"） |
| 8-10 | 每个破坏性/不可逆动作前都有明确检查点，确认信息含足够上下文（diff/预览/影响面） |

#### D6 — 资源整合度（权重 5）

评估对 references / scripts / assets 等外部资源的引用正确性。

| 分值 | 描述 |
|------|------|
| 1-3 | 引用了不存在的文件，或路径明显错误 |
| 4-5 | 引用存在但描述与实际不符（如指向旧路径） |
| 6-7 | 引用正确，但未说明何时使用该资源 |
| 8-10 | 引用正确 + 使用时机清晰 + 资源作用有说明 |

**注**：本维权重最低（5 分）是因为大部分 skill 不依赖外部资源。

#### D7 — 整体架构（权重 20）

评估层次结构、信息冗余、前后一致性。

| 分值 | 描述 |
|------|------|
| 1-3 | 段落与章节顺序混乱，同样的指令在多处重复且不一致 |
| 4-5 | 结构基本存在但有冗余（同一内容重复 2 次以上） |
| 6-7 | 层次清晰，少量冗余 |
| 8-10 | 章节层次清晰 + 无冗余 + 无内部矛盾 + 顺序符合执行时间轴 |

---

## Prompt / Rule 类型 — 4 维简化 rubric（总分 100）

对 prompt 和 rule 类型资源，去除 frontmatter（多数无）/ 边界条件（通常较薄）/ 检查点（通常不适用）三维，保留核心 4 维并重新归一化权重。

| # | 维度（英文 key） | 中文 | 权重 |
|---|----------------|------|------|
| D2 | `workflow_clarity` | 工作流清晰度 | 31 |
| D3 | `instruction_specificity` | 指令具体性 | 31 |
| D6 | `resource_integration` | 资源整合度 | 8 |
| D7 | `overall_architecture` | 整体架构 | 30 |

**分档描述**：与 skill 同名维度完全一致，只是总权重重新归一到 100。

---

## 静态 lint 规则（LLM 调用前门槛）

evo 在调用 LLM 评分前，先跑静态 lint。lint 失败的资源**不进入 LLM 评分**，直接报告给用户修复。

### Skill 类型

| 规则 | 必填 | 失败判定 |
|------|------|---------|
| 文件以 `---` 开头并有闭合 `---` 形成 frontmatter | 是 | frontmatter 缺失 |
| frontmatter 包含 `name` 字段 | 是 | `name` 缺失 |
| `name` 为合法 slug（`^[a-z0-9][a-z0-9-]*$`） | 是 | `name` 非法 |
| frontmatter 包含 `description` 字段且非空 | 是 | `description` 缺失或空 |
| markdown 所有代码块闭合（```...``` 成对） | 是 | 有未闭合代码块 |
| 无非法控制字符（除常规换行/制表外的 `\x00-\x1f`） | 是 | 含非法字符 |

### Prompt / Rule 类型

| 规则 | 必填 | 失败判定 |
|------|------|---------|
| 文件非空（≥50 字节）| 是 | 文件过小 |
| markdown 所有代码块闭合 | 是 | 有未闭合代码块 |
| 无非法控制字符 | 是 | 含非法字符 |

`.cursorrules` 格式例外：不要求 markdown 规范（视为纯文本），只检查非空和控制字符。

---

## LLM 评分 prompt 模板

以下模板在各平台 evo 命令文件中作为 LLM 调用的 prompt 参考。实际命令文件里要把模板嵌入到 Bash/WebFetch 调用的 prompt 参数中。

### Skill 评分 prompt（中文版）

```
你是 SKILL.md 质量评审员。按以下 7 维 rubric 对给定 SKILL.md 评分（每维 1-10 整数）。

【rubric】
D1 frontmatter_description_quality (权重10): description 能否让 Agent 判断何时激活
D2 workflow_clarity (权重20): 正文步骤/阶段是否可按图索骥
D3 instruction_specificity (权重20): 指令是否"可直接执行"
D4 edge_case_coverage (权重15): 异常/边界说明完整度
D5 checkpoint_design (权重10): 关键决策前有无用户确认
D6 resource_integration (权重5): 外部资源引用正确性
D7 overall_architecture (权重20): 层次/冗余/一致性

【SKILL.md 内容】
<此处插入 SKILL.md 全文>

【输出要求】
严格返回以下 JSON 结构（不要 markdown 代码块包裹，不要额外说明）：
{
  "dimensions": {
    "frontmatter_description_quality": {"score": <1-10>, "weight": 10, "reason": "<≤40 字中文>", "suggestion": "<≤80 字改进建议>"},
    "workflow_clarity": {"score": <1-10>, "weight": 20, "reason": "...", "suggestion": "..."},
    "instruction_specificity": {"score": <1-10>, "weight": 20, "reason": "...", "suggestion": "..."},
    "edge_case_coverage": {"score": <1-10>, "weight": 15, "reason": "...", "suggestion": "..."},
    "checkpoint_design": {"score": <1-10>, "weight": 10, "reason": "...", "suggestion": "..."},
    "resource_integration": {"score": <1-10>, "weight": 5, "reason": "...", "suggestion": "..."},
    "overall_architecture": {"score": <1-10>, "weight": 20, "reason": "...", "suggestion": "..."}
  },
  "total_score": <0-100 加权总分>
}
```

### Prompt/Rule 评分 prompt（中文版）

```
你是 prompt/rule 文档质量评审员。按以下 4 维 rubric 评分（每维 1-10 整数）。

【rubric】
D2 workflow_clarity (权重31): 步骤/阶段清晰度
D3 instruction_specificity (权重31): 指令具体性
D6 resource_integration (权重8): 外部引用正确性
D7 overall_architecture (权重30): 层次/冗余/一致性

【文档内容】
<此处插入文件全文>

【输出要求】
严格返回以下 JSON：
{
  "dimensions": {
    "workflow_clarity": {"score": <1-10>, "weight": 31, "reason": "...", "suggestion": "..."},
    "instruction_specificity": {"score": <1-10>, "weight": 31, "reason": "...", "suggestion": "..."},
    "resource_integration": {"score": <1-10>, "weight": 8, "reason": "...", "suggestion": "..."},
    "overall_architecture": {"score": <1-10>, "weight": 30, "reason": "...", "suggestion": "..."}
  },
  "total_score": <0-100>
}
```

### 英文版 prompt

中文 prompt 对应的英文版本，用于 `lang:en` 模式。键名（`frontmatter_description_quality` 等）保持不变，分档描述、reason、suggestion 改为英文。

---

## LLM 改进 prompt 模板

### 改进 prompt（中文版）

```
你是 SKILL.md（或 prompt/rule 文档）改进者。根据给定的评分结果和目标维度列表，产出改进后的完整文档。

【原文档】
<此处插入原始全文>

【资源类型】
skill | prompt | rule

【目标改进维度】
<用户选择的维度列表，如 ["workflow_clarity", "edge_case_coverage"]>

【当前评分与建议】
<评分 JSON 的 dimensions 字段，仅包含目标维度>

【改进原则】
1. 保留原文档核心功能和用途——只改"怎么写"，不改"做什么"
2. 保留原有结构/层次/章节顺序，不删除无关内容
3. 保留原有语言风格（中文/英文）
4. skill 类型：绝不修改 frontmatter 里 `---` 之间的任何字段
5. 改进后总体积受**动态 size cap** 约束（见下）；超过时必须警告用户并要求显式确认
6. 不引入新依赖（scripts/references/MCP 等）
7. 仅针对目标维度改，不触碰其他维度涉及的段落

【动态 size cap 规则】
- 正常输入（原文 > 30 行且 > 1200 字节）：cap = 1.5×
- 骨架型输入（原文 ≤ 30 行 **或** ≤ 1200 字节）：cap = 3.0×
  理由：catalog 里很多资源是 auto-gen 模板（复读式样板，几乎没实质内容），一旦要写真东西必然显著增量；若照搬 1.5× 会让 evo 在这类最需要改进的场景里反而动不了。
- 若实际改后 ratio > cap：不自动拒绝，而是在 diff 预览里打出 ⚠️ 警告并要求 Y/n/edit；若用户选 Y，history.json 追加 `size_override: {original_bytes, improved_bytes, ratio, reason}` 字段留痕。

【输出要求】
严格返回以下 JSON：
{
  "improved_content": "<改进后的完整文档全文，字符串>",
  "diff_summary": [
    {"section": "<被改动的章节名>", "change": "<改动描述，≤50 字中文>", "targets": ["<对应的维度 key>"]}
  ]
}
```

---

## 改进后落盘与历史记录

### 本机落盘路径

| 平台 | 配置目录 | history.json 路径 |
|------|---------|-------------------|
| claude-code | `~/.claude/` | `~/.claude/.evo/<id>/history.json` |
| opencode | `~/.opencode/` | `~/.opencode/.evo/<id>/history.json` |
| costrict | `~/.costrict/` | `~/.costrict/.evo/<id>/history.json` |
| vscode-costrict | `~/.costrict/` | `~/.costrict/.evo/<id>/history.json`（与 costrict 共用） |

### history.json schema

每次 evo 运行（包括用户选 skip）都追加一条 entry。结构使用**开放字段**——未来新增维度或字段时，老数据仍合法：

```json
{
  "id": "<资源id>",
  "type": "skill | prompt | rule",
  "local_path": "<被 evo 的文件绝对路径>",
  "history": [
    {
      "timestamp": "<ISO8601>",
      "rubric_version": "1.0",
      "content_hash_before": "<sha256 of local file before evo>",
      "content_hash_after": "<sha256 of local file after evo, same as before if skipped>",
      "dimensions": {
        "<dim_name>": {
          "score": <1-10>,
          "weight": <number>,
          "reason": "<string>",
          "suggestion": "<string>"
        }
      },
      "total_score": <0-100>,
      "user_action": "accept | skip | edit",
      "selected_dimensions": ["<dim_name>", ...],
      "size_override": {
        "original_bytes": <int>,
        "improved_bytes": <int>,
        "ratio": <float>,
        "reason": "<string, e.g. 'auto-gen skeleton — 1.5× cap not meaningful'>"
      },
      "diff_summary": [
        {"section": "<string>", "change": "<string>", "targets": ["<dim_name>"]}
      ]
    }
  ]
}
```

**注**：`size_override` 仅在用户 Y 接受了超 cap 的改动时出现；正常在 cap 内的改动不写这个字段。

**兼容性保证**：
- `dimensions` 是 map（`{<name>: {...}}`），不是固定字段 record——后期加"实测表现"维只需加 key
- 每个维度 entry 内部可追加字段（如后期棘轮用的 `baseline_score`、`accepted`），老数据缺字段按 `null` 处理
- `rubric_version` 用于将来 rubric 大改时区分

---

## 致谢

evo rubric 的维度设计灵感来自 [darwin-skill](https://github.com/alchaincyf/darwin-skill)（MIT License © 花叔）。darwin-skill 首次在 skill 优化语境下系统化提出"结构 + 效果"双重评估与棘轮机制。本仓库在客户端按需场景下作了简化适配：去除动态测试维、去除棘轮（MVP 延后）、加入 prompt/rule 4 维变体。感谢原作者的开源贡献。
