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

### 1.5 rules / prompts 被全局去重误杀

**现状**：
- `catalog/rules/index.json` 有 232 条，`curated` 后原始总量 236 条，但最终总目录里只剩 182 条
- `catalog/prompts/index.json` 有 511 条，`curated` 后原始总量 513 条，但最终总目录里只剩 2 条

这不是采集不到，而是 `merge_index.py` 走全局 `deduplicate()` 时，把 `source_url` 当成了强唯一键。  
而 `rules/prompts` 这两类资源天然经常共用同一个仓库级 `source_url`：
- `prompts.chat` 的大量 prompt 都指向同一个仓库 URL
- `wonderful-prompts` 的编程类 prompt 也共用同一个 README URL
- `rules-2.1-optimized` 同一目录下多个 rule 也会共用目录 URL

结果就是：
- `prompt` 基本退化成“每个源仓库只保留 1 条”，最终只剩 2 条
- `rule` 也被压掉一批，本来 236 条只保留了 182 条

**方案**：
- 调整全局去重策略，不要对 `rule/prompt` 继续使用“仓库级 `source_url` 强唯一”
- 去重主键改成按资源类型区分：
  - `mcp`：优先按标准化 repo URL 去重
  - `skill`：按 `id` + 子路径 / 资源路径去重
  - `rule/prompt`：优先按 `id` 去重，`source_url` 只作为辅助信号，不作为硬去重键
- 对 `rule/prompt` 补一个更细粒度的 `source_path` / `artifact_url` 字段，表示具体文件或具体章节来源
- merge 前后增加类型级数据量校验。如果 `prompt` 从 500+ 被压到个位数，应直接告警或阻断提交

### 1.6 prompt 类型只有 2 条只是表象

**现状**：当前总目录里是 `mcp=1628, skill=1225, rule=182, prompt=2`，看起来像 prompt 源极少。

**本质**：从原始同步结果看，prompt 并不少，真正的问题是 1.5 里的去重策略设计错误，不是上游覆盖面不足。

**方案**：
- 先修 1.5 的全局去重键设计，再重新评估 prompt 覆盖率
- 在去重问题修好前，不要贸然把结论归因到 `sync_prompts.py` 过滤过严
- 去重修复后再判断是否需要扩展 prompt 上游源、放宽 coding relevance 判定

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

### 4.5 统一富化评分层，替代分散的 LLM 调用

**现状**：
- Tier 1 skill 单独做一次中文翻译
- Tier 2 skill 单独做一次 LLM 评估
- merge 阶段再对 tags 不足的条目做一次 LLM 补 tag

这三步都在做“语义理解 + 元数据富化”，但现在分散在不同阶段、不同 prompt、不同缓存中：
- 判断标准不统一
- 不同类型资源治理强度不一致
- 同一个条目可能被多次送进 LLM
- `stars <= 50` 这类 repo 级硬过滤发生得过早，小仓库里的优质 skill 会被一刀砍掉

**问题本质**：
- 当前 Tier 2 是“repo 级硬门槛 + skill 级 LLM 评估”
- 其中 `stars` 是仓库级信号，不是 skill 粒度信号，只适合做弱排序，不适合做一票否决
- 这会导致“高热度 repo 里的普通 skill 容易进入下一轮，小众 repo 里的优质 skill 直接出局”

**方案**：把现有零散的 LLM 逻辑升级为一层统一的 `Unified Enrichment + Scoring Layer`

统一评分层不只输出一个总分，而是输出一组标准化字段：

```
{
  "coding_relevance": 1-5,     # 与开发工作流的直接相关性
  "content_quality": 1-5,      # 描述清晰度、信息密度、是否像真实可用资源
  "specificity": 1-5,          # 内容是否具体，尤其适用于 rule/prompt
  "installability_hint": 1-5,  # 语义上是否可直接使用；真正安装完整度仍由本地规则计算
  "category": "...",           # 统一分类
  "tags": ["..."],             # 规范化 tags
  "description_zh": "...",     # 中文描述
  "reason": "...",             # 一句解释
  "confidence": 1-5            # 模型对自己判断的确信度
}
```

其中仍应保留本地 deterministic 信号，不交给 LLM：
- popularity：stars
- freshness：最近 push 时间
- installability：安装字段是否完整、路径是否明确
- source_trust：官方源 / 成熟社区源 / 未知源
- duplicate_status：是否重复
- has_readme / license / languages 等仓库元信息

最终由系统把“本地规则分”和“LLM 语义分”合成为 `final_score`，并产出决策：

```
decision = accept | review | reject
```

#### 为什么它比“给所有层挂一个 Tier 2”更合理

不是把其他层也照抄 Tier 2，而是把 Tier 2 现有的粗暴门槛拆掉，重构成全类型通用的一层。

好处：
- 小仓库里的优质 skill 不会被 `stars <= 50` 直接打死
- Tier 1 / Tier 2 / MCP / Rule / Prompt 都可以共享同一套语义富化能力
- `category` / `tags` / `description_zh` / `reason` 的生成逻辑统一
- 可以把目前分散的两到三次 LLM 调用收敛成一次 batch enrichment

#### 不同类型共享字段，但权重不同

统一的是评分框架，不是所有类型都用一套同权重公式。

建议：

- `skill`
  - relevance 30
  - quality 25
  - installability 20
  - maintainability 10
  - source_trust 10
  - popularity 5
- `mcp`
  - installability 30
  - relevance 20
  - maintainability 20
  - quality 15
  - source_trust 10
  - popularity 5
- `rule`
  - relevance 30
  - specificity 25
  - direct_usability 20
  - quality 15
  - source_trust 10
- `prompt`
  - relevance 30
  - specificity 30
  - reproducibility 20
  - quality 10
  - source_trust 10

这里 `popularity` 应从“生死线”降级为“弱排序信号”。

#### 能否替代现有两层 LLM

可以，基本可以。

新的统一评分层可以一次返回：
- 语义评分
- `category`
- `tags`
- `description_zh`
- `reason`

这样可以收敛掉当前分散的几类调用：
- Tier 1 description 翻译
- Tier 2 skill 评估
- merge 阶段的 tag 补全

真正应该保留的不是“原有两层 LLM”，而是三段式结构：

```
最小硬过滤 -> 统一富化评分 -> 最终决策
```

其中“最小硬过滤”只保留这些便宜且确定的拦截：
- 解析失败
- 明显重复
- 明显 spam
- 明显非 coding
- description 短到无法判断

除此之外，尽量进入统一评分层，而不是在前面被 repo 级规则提前淘汰。

#### 新流水线草图

```
source adapters
  ↓
normalize
  - 统一 schema
  - 统一 source_url / path
  - 初始 category / tags / install 解析
  ↓
minimal hard filter
  - parse failure
  - duplicate
  - spam
  - obvious non-coding
  - too-short-to-judge
  ↓
deterministic pre-score
  - stars
  - pushed_at
  - license / readme / languages
  - install completeness
  - source trust
  ↓
unified enrichment + scoring
  - coding_relevance
  - content_quality
  - specificity
  - category normalization
  - tags normalization
  - description_zh
  - confidence / reason
  ↓
decision engine
  - accept
  - review
  - reject
  ↓
merge
  - 全局去重
  - 类型级数量校验
  - curated 合并
  ↓
publish
  - catalog/index.json
  - README counts
  - featured / search artifacts
```

#### 分阶段落地建议

**Phase 1**
- 去掉 Tier 2 的 `stars <= 50` 硬门槛，改成 pre-score 信号
- 统一 LLM 输出结构，让 Tier 2 评估同时返回 `tags` / `category` / `description_zh`

**Phase 2**
- 让 Tier 1 也进入同一套 enrichment 流程，但只用于富化和排序，不做强过滤
- merge 阶段移除单独的 tag enrichment 调用

**Phase 3**
- 把 MCP / Rule / Prompt 也接入统一评分层
- 为不同类型配置不同权重和决策阈值
- 把 `accept/review/reject` 引入 CI 完整性校验和精选生成流程

#### Schema 迁移原则：保留旧 catalog，对外兼容演进

统一评分层不应推翻现有 `catalog` 顶层字段。

原因：
- README 当前直接消费 `catalog` 中的多个字段
- 搜索、推荐、平台命令也已经依赖现有 schema
- 如果直接改字段名、改层级、改语义，会造成 README、索引消费方和命令侧同步漂移

因此应该采用“顶层兼容 + 子对象扩展”的方式：

**保留现有顶层发布字段**
- `id`
- `name`
- `type`
- `description`
- `description_zh`
- `source_url`
- `source`
- `category`
- `tags`
- `stars`
- `tech_stack`
- `install`
- `health`
- `last_synced`

这些字段继续作为：
- README 生成输入
- 搜索 / 推荐输入
- 平台命令消费字段

**新增治理层子对象**

建议新增：

```json
"evaluation": {
  "coding_relevance": 5,
  "content_quality": 4,
  "specificity": 4,
  "source_trust": 3,
  "confidence": 4,
  "final_score": 78,
  "decision": "accept",
  "reason": "描述清晰，安装路径明确，和开发流程直接相关"
}
```

推荐放在 `evaluation` 中的字段：
- `coding_relevance`
- `content_quality`
- `specificity`
- `source_trust`
- `confidence`
- `final_score`
- `decision`
- `reason`

这些字段的职责是：
- 解释“系统为什么收录它 / 为什么把它排在前面”
- 为排序、精选、人工 review 提供依据
- 支持后续审计同步策略，而不是直接服务 README 展示

**顶层字段保留，但生产方式可以统一重构**

保留字段不代表保留原有多套生成逻辑。

可以逐步把以下字段改为由统一评分层产出最终结果：
- `category`
- `tags`
- `description_zh`

也就是说：
- 字段名保持不变，保证兼容
- 字段来源切换到统一 enrichment/scoring 层，减少多套逻辑并存

**迁移建议**

Phase 1：
- 先只写入 `evaluation`
- README 和现有命令不读取 `evaluation`

Phase 2：
- 内部排序、精选生成、CI 完整性校验逐步读取 `evaluation`
- 顶层 `category` / `tags` / `description_zh` 仍然保留，但由统一评分层写回

Phase 3：
- README 如有需要，可选择展示 `evaluation.final_score` 或 `evaluation.reason`
- 但 `evaluation` 不应成为 README 正常生成的硬依赖，以避免迁移期耦合过重

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
| **P0** | tags/tech_stack 全量 backfill | 搜索和推荐的核心依赖 | 中 | ✅ 已完成 — `llm_tagger.py` 批量 LLM 补 tag + `merge_index.py` enrichment 层补 tech_stack；sync 阶段保留 topics→tags 零成本富化，languages API 调用下沉到 merge 阶段避免 rate limit |
| **P0** | category=other 修正 | 数据一致性 | 小 | ✅ 已完成 — `sync_skills.py` 映射修正 + `merge_index.py` 兜底修复 |
| **P1** | 补 merge_index 等核心脚本测试 | 防止合并逻辑出 bug | 中 | ✅ 已完成 — `tests/test_merge_index.py` (6 cases) |
| **P1** | 统一富化评分层（替代分散 LLM） | 数据治理一致性、减少误杀 | 中到大 | 待设计 / 待实施 |
| **P1** | 四平台文件模板化 | 维护效率 | 中 | 待实施 |
| **P1** | install.method=manual 批量优化 | 用户可安装率从 67% 提升 | 中 | 待实施 |
| **P1** | 同步 CI 完整性检查 | 防数据丢失 | 小 | ✅ 已完成 — `sync.yml` merge 前校验各源数据 |
| **P2** | abandoned 条目处理策略 | 质量感知 | 小 | 待实施 |
| **P2** | 按类型重构去重主键 | 修复 rules/prompts 被误杀 | 中 | ✅ 已完成 — `deduplicate()` 按 type 分策略：prompt/rule 跳过 URL 去重，prompt 从 2→520，rule 从 182→236 |
| **P2** | prompt 类型扩源 | 数据覆盖面 | 中 | 待实施 |
| **P2** | 贡献指引 + 变更日志 | 社区增长 | 小 | 待实施 |
| **P3** | 索引分片/API 化 | 性能（当前不紧急） | 大 | 待实施 |
| **P3** | LLM 评估 fallback | 稳定性 | 中 | 待实施 |
