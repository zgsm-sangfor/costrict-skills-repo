# Coding Hub 项目整体改进策略

> 基于项目现状的全面分析，覆盖数据质量、工程基础、用户体验、架构演进四个维度。

---

## 一、数据质量

当前 3037 条资源，数据质量参差不齐。

### 1.1 category=other 不在 schema 枚举中

**现状**：143 条资源的 category 是 `other`，但 schema.json 的枚举值里没有 `other`，validate_curated.py 也不认这个值。这些条目是从上游同步时兜底产生的。

**方案**：
- `categorize()` 兜底值从 `"tooling"` 改为根据 description/tags 做二次分类
- 对现有 143 条 `other` 做一次批量修正（可以跑一次脚本重新分类）
- 或者在 schema 里正式承认 `other`，validate 也加上

### 1.2 install.method=manual 占比 33%

**现状**：1024 条资源的安装方式是 `manual`（无法自动安装），用户体验差。主要来自 mcp.so 同步的条目。

**方案**：
- 对 `manual` 条目批量探测：有 npm 包 → `mcp_config`，有 Dockerfile → docker 方式，有 pyproject.toml → uvx/pipx
- 新同步时在 `sync_mcp.py` 里增加安装方式推断逻辑
- 短期：至少给 manual 条目加 `install.repo` 字段，用户可以手动 clone

### 1.3 83% 条目被标记为 abandoned

**现状**：freshness 分布 — active: 269, stale: 228, abandoned: 2540。大量 abandoned 条目拉低整体质量感知。

**方案**：
- 分析 abandoned 原因：是真的不维护了，还是 `pushed_at` 数据缺失导致误判？
- health_scorer 的 freshness 阈值是否合理？如果一个工具 1 年没更新但功能完备（如 prettier-config），不应该标 abandoned
- 考虑对 abandoned 条目降权（搜索排序靠后）但不删除
- 或者给用户展示时加标签提示

### 1.4 tags 和 tech_stack 严重缺失

**现状**：
- 1328/3037 (43%) 无 tags
- 2908/3037 (95%) 无 tech_stack

这直接影响搜索命中率和 `/recommend` 的匹配精度。

**方案**：
- `extract_tags()` 增强：不只看 name/description，也解析 GitHub topics（现在只在 curated 流程用了 topics，sync 脚本没用）
- tech_stack：从 GitHub languages API 补充（sync_mcp.py 已有 API 调用基础，但没写入 tech_stack）
- 做一次全量 backfill：遍历所有 stars>0 的条目，调 GitHub API 补充 topics + languages
- 注意 rate limit：3037 条全量补需要 3000+ API 调用，有 token 的情况下约 30 分钟

### 1.5 prompt 类型只有 2 条

**现状**：mcp=1628, skill=1225, rule=182, prompt=2。prompt 几乎是空的。

**方案**：
- 扩展上游源：awesome-chatgpt-prompts（67k stars）只同步了 2 条，应该是过滤太激进
- `sync_prompts.py` 的 `is_coding_related()` 过滤把大量 prompt 排除了（因为很多 prompt 不带 coding 关键词但实际有用）
- 放宽过滤条件，或者对 prompt 类型做专门的 relevance 判定
- 中期考虑增加更多 prompt 上游源

---

## 二、工程基础

### 2.1 测试覆盖率极低

**现状**：15 个 Python 脚本只有 5 个有测试。核心同步脚本（sync_mcp/rules/skills/prompts）、merge_index、generate_featured、crawl_mcp_so 全部没有测试。

```
❌ crawl_mcp_so      ❌ generate_featured    ❌ llm_evaluator
❌ merge_index        ❌ skill_registry       ❌ supplement_tags
❌ sync_mcp           ❌ sync_prompts         ❌ sync_rules
❌ sync_skills        ❌ update_readme
```

**方案**：
- 优先补 merge_index.py 测试（合并逻辑是数据管道的核心节点，出错影响全量数据）
- 补 health_scorer.py 的边界 case（当前只有 5 个测试）
- sync 脚本因为依赖外部 API 较难测试，但可以测 parsing 逻辑（mock HTTP 响应，验证解析结果）
- CI 加 `pytest` 步骤，PR 合并前必须通过

### 2.2 CI 没有跑测试

**现状**：`sync.yml` 只跑同步脚本，不跑测试。`validate-pr.yml` 只校验 curated.json。没有任何 CI 步骤会执行 `pytest`。

**方案**：
- 新增 `test.yml`：在 push 和 PR 时触发，跑 `pytest tests/`
- 或者在 `validate-pr.yml` 里加一步跑全量测试
- 同步 CI 失败时完全静默（`continue-on-error: true`），应该至少发个通知

### 2.3 sync CI 全部 continue-on-error

**现状**：每个同步步骤都是 `continue-on-error: true`，任何一步失败都会静默跳过。如果 sync_mcp 崩了，merge_index 会用旧数据合并，最后 auto-commit 推一个不完整的结果上去。

**方案**：
- 区分"可接受的失败"（rate limit、网络超时）和"不可接受的失败"（脚本 bug、数据格式变更）
- 在 merge 步骤前检查各 sync 步骤的 exit code，如果全部失败则不合并不提交
- 同步完成后加数据完整性检查：条目数不能比上次减少超过 10%（防止上游源意外变更导致大量丢失）

### 2.4 sync_rules.py 错误处理最弱

**现状**：只有 2 处 try/except，而 sync_mcp 有 53 处。如果上游 README 格式变了，sync_rules 很可能直接崩溃。

**方案**：
- 补充 parsing 异常处理
- 加入对上游格式变更的检测（比如预期的 markdown 表格结构不存在时，输出明确错误而非崩溃）

---

## 三、用户体验

### 3.1 四套平台文件维护负担重

**现状**：costrict、opencode、vscode-costrict、claude-code 四个平台各有一套 SKILL.md + 6 个 command 文件，内容高度相似但行数不同（SKILL.md 从 117 到 274 行），差异散落在命名规则、路径、少量措辞上。

**问题**：每次改功能逻辑需要改 4 遍。已经出现过平台间内容不一致的情况（opencode 比 costrict 多了示例表格，vscode-costrict 多了路径处理规则段落）。

**方案**：
- 模板化：维护一份 master 模板（Jinja2 或简单的变量替换），CI/脚本自动生成四套文件
- 变量包括：平台名、配置目录、命令分隔符、MCP 配置路径、安装目标路径
- 新增一个 `scripts/generate_platform_files.py`，从模板 + 平台配置生成最终文件
- 这样改逻辑只需改一处模板

### 3.2 搜索/推荐依赖 tags，但 43% 条目无 tags

**现状**：`/coding-hub:recommend` 通过匹配项目 tech stack 和条目 tags 来推荐。但 1328 条资源没有 tags，这些资源永远不会被推荐到。

**方案**：见 1.4 的 tags backfill。这是用户体验的核心瓶颈之一。

### 3.3 install 命令对非 Claude Code 平台的适配

**现状**：条目的 `install.config` 通常是 Claude Desktop 格式（`claude_desktop_config.json`），但 vscode-costrict 用的是 `.roo/mcp.json`，opencode 用的是 `.opencode/mcp.json`。虽然 SKILL.md 里写了"忽略 install 字段中的路径信息"，但这完全依赖 LLM 理解并遵守这条指令。

**方案**：
- 给条目增加多平台 install 配置（或者在 SKILL.md 的 install 命令里做运行时转换）
- 更可靠的方案：install 命令的 Python 预处理脚本根据当前平台自动改写路径

---

## 四、架构演进

### 4.1 索引存储全是 JSON 文件

**现状**：`catalog/index.json` 3037 条资源，约 2MB。每次搜索/浏览都要下载整个文件解析。随着资源增长，这个文件会越来越大。

**短期方案**：
- 搜索命令已经用 Python 做预过滤（只传相关条目给 LLM），暂时够用
- 可以做分片：按 type 分成 4 个文件，搜索时只下载相关类型

**中期方案**：
- 如果资源量到 10000+，考虑换 SQLite 或 API 服务
- 或者用 GitHub Pages 托管一个静态 API（按 category/type 分目录的 JSON 文件）

### 4.2 上游源脆弱性

**现状**：9 个上游源，3 个贡献了 90% 的数据：mcp.so (1057)、antigravity-skills (1197)、awesome-mcp-zh (369)。如果任一源挂了或格式变了，影响面很大。

**方案**：
- 每次同步记录每个源的条目数，与上次对比，变化超过 20% 发告警
- 增加 fallback：同步失败时保留上一次的数据，不清空
- 扩展上游源：减少对单一源的依赖
- 考虑对重要源做本地快照（定期备份到 repo 或 artifact）

### 4.3 health_scorer 没有时效性

**现状**：health score 只在 `merge_index.py` 跑时计算。如果一个项目半年前 active，现在已经废弃了，下次同步前它的 health score 不会变。

**方案**：
- 在每周同步时重新计算所有条目的 health score（现在已经在做，但要确认 `pushed_at` 是否每次都从 API 更新）
- 对 curated 条目也做定期 health 刷新（现在 curated 条目的 stars/pushed_at 是提交时的快照，之后不会更新）

### 4.4 LLM 评估的成本和稳定性

**现状**：Tier 2 skills 要走 `llm_evaluator.py` 做质量评估，依赖外部 LLM API（`LLM_BASE_URL`/`LLM_API_KEY`/`LLM_MODEL`）。如果 API 不可用，Tier 2 skills 整层缺失。

**方案**：
- 加 LLM 评估缓存：已评估过且 repo 没有重大变更的条目，直接复用上次评估结果
- 加 fallback 策略：LLM 不可用时，用 heuristic 评估（stars + freshness + has_readme 加权）替代
- 或者把评估结果持久化到 `.llm_cache.json`，不依赖每次都调 LLM

---

## 五、社区与增长

### 5.1 README 缺少贡献指引

**现状**：README 没有 CONTRIBUTING.md 或贡献说明。外部贡献者不知道可以通过 Issue 推荐资源。

**方案**：
- 在 README 加"如何贡献"章节，指向 Issue Template
- 新增 CONTRIBUTING.md 说明贡献流程

### 5.2 没有变更日志

**现状**：用户无法知道"上周新增了哪些资源"。每周同步是静默的。

**方案**：
- 同步 CI 完成后自动生成 CHANGELOG 或 release notes
- 或者用 GitHub Releases：每次同步后创建一个 release，附带 diff 统计（新增 N 条、更新 M 条、删除 K 条）
- 可以配合 RSS feed 让用户订阅

### 5.3 Featured 精选的更新机制

**现状**：`catalog/featured.md` 由 `generate_featured.py` 生成，但触发条件不清楚（不在 sync.yml 里）。

**方案**：
- 把 `generate_featured.py` 加入 sync CI 流程
- 或者在 curated PR 合并后触发重新生成（新增精选资源应该更新精选列表）

---

## 优先级建议

| 优先级 | 改进项 | 影响面 | 工作量 | 状态 |
|--------|--------|--------|--------|------|
| **P0** | CI 加测试步骤 | 工程质量底线 | 小 | ✅ 已完成 — `.github/workflows/test.yml` |
| **P0** | tags/tech_stack 全量 backfill | 搜索和推荐的核心依赖 | 中 | 待实施 |
| **P0** | category=other 修正 | 数据一致性 | 小 | ✅ 已完成 — `sync_skills.py` 映射修正 + `merge_index.py` 兜底修复 |
| **P1** | 补 merge_index 等核心脚本测试 | 防止合并逻辑出 bug | 中 | ✅ 已完成 — `tests/test_merge_index.py` (6 cases) |
| **P1** | 四平台文件模板化 | 维护效率 | 中 | 待实施 |
| **P1** | install.method=manual 批量优化 | 用户可安装率从 67% 提升 | 中 | 待实施 |
| **P1** | 同步 CI 完整性检查 | 防数据丢失 | 小 | ✅ 已完成 — `sync.yml` merge 前校验各源数据 |
| **P2** | abandoned 条目处理策略 | 质量感知 | 小 | 待实施 |
| **P2** | prompt 类型扩源 | 数据覆盖面 | 中 | 待实施 |
| **P2** | 贡献指引 + 变更日志 | 社区增长 | 小 | 待实施 |
| **P3** | 索引分片/API 化 | 性能（当前不紧急） | 大 | 待实施 |
| **P3** | LLM 评估 fallback | 稳定性 | 中 | 待实施 |
