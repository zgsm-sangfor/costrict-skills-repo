## Context

Catalog 中 Tier 1 已有 4 个上游源（anthropics/skills、Ai-Agent-Skills、antigravity 镜像、vasilyu）。覆盖率审计显示 Top 9 热门 skill 中 6 个未直接收录、2 个仅镜像。skills.sh（Vercel 官方目录，2026-01-20 上线）以 install_count 为度量已积累 34,311 条 skill 数据，是当前事实上的「skill 真实使用量」唯一权威信号源。

但 skills.sh 没有官方公开 API。前期探针确认两条可行接入路径：
1. `mastra-ai/skills-api` 仓库内置 `src/registry/scraped-skills.json`（MIT，34K 条全量，HTTP raw 直拉）
2. skills.sh 的隐藏分页端点 `/api/skills/all-time?page=N`（mastra 项目自身在用，无 SLA 但稳定）

现有 sync 管线为 Python 标准库（urllib + json），CI 通过 `actions/cache` 缓存 `.eval_cache/`、`.llm_cache.json`、`incremental_recrawl_state.json` 等。新增 source 应复用既有缓存与增量评估机制，避免 LLM 评估成本爆炸。

## Goals / Non-Goals

**Goals:**
- 通过单一聚合源一次性补齐 Top 热门 skill 覆盖率（当前已知缺失的 6 个 + 长尾）
- 引入 install_count 作为 catalog 的真实使用量信号，区别于 GitHub stars
- CI 增量更新友好：仅评估新增/变更 + 阈值过线条目，单次 sync 增量评估成本 < $5
- 双路径降级保证数据新鲜度（mastra 停滞时自动回退到 skills.sh 直连）
- 不破坏现有 catalog 条目，所有新字段在旧条目中可缺省

**Non-Goals:**
- 不接入 Claude plugin marketplace 协议（已决定暂缓）
- 不解析 skill 内部跨平台支持声明（platforms_supported 字段留待后续）
- 不修改评分管线现有权重（install_count 默认权重 0，仅做信号采集）
- 不做付费 / 私有 skill 收录（mastra/skills.sh 都仅含公开 GitHub 源）

## Decisions

### D1: 双路径接入（C 方案）vs 单路径

**选择**：mastra JSON 主路径 + skills.sh API 备用路径（C 方案）

**理由**：
- mastra JSON：一次 GET、无分页、MIT、stable URL（`raw.githubusercontent.com/.../scraped-skills.json`），最简单
- 但 mastra 维护者节奏不可控，万一停滞需要兜底
- skills.sh API 是 mastra 自己用的，长期可用性可对赌

**降级触发**：检查 mastra JSON 的 `scrapedAt` 字段，>7 天则启用 skills.sh API 全量重拉。

**替代方案**：
- 仅 mastra：简单但单点；如果 mastra 数据落后 1 个月我们就跟着落后
- 仅 skills.sh API：分页 + 重试逻辑复杂；隐藏端点风险更高
- npm 库 import：跨语言不便，我们 Python 主管线

### D2: install_count 阈值 = 1000

**选择**：仅 install_count ≥ 1000 的 skill 进入 catalog

**理由**：
- 对齐 `vercel-labs/find-skills` 的官方 quality bar
- 34K → 估算 200-400 条进库，单次 LLM 评估增量成本可控
- 阈值过低（如 100）会引入大量低质长尾，污染评分均值
- 阈值过高（如 5000）会漏掉 2-3K stars 段优质新晋 skill

**配置化**：阈值通过环境变量 `SKILLS_SH_MIN_INSTALLS` 暴露，默认 1000，CI 可调。

**替代方案考虑过**：
- (a) 100 — 量太大，CI 评估成本失控
- (b) 5000 — top 50-80 条，过窄，错过新晋
- (c) 动态阈值（如 P75）— 实现复杂，先用静态值打基础

### D3: 数据落点 — 中间索引 vs 直接合并

**选择**：先写到 `catalog/skills/skills_sh_index.json`（中间索引），再由 `merge_index.py` 合并到 `catalog/skills/index.json` 与 `catalog/index.json`

**理由**：
- 与现有 `catalog/skills/{anthropic,ai_agent,antigravity,vasilyu}_index.json` 模式一致
- merge_index.py 已有去重和富化管线，复用最稳
- 隔离性好，调试时可单独跑 sync 不污染最终 catalog

### D4: 去重优先级

**选择**：基于 `source_url`（github URL）的 canonical 优先级

```
优先级（高→低）：
1. 官方直接源（anthropics/skills, vercel-labs/* 等）
2. skills.sh 收录（带 install_count 信号）
3. antigravity 镜像（已在 Tier 1 但是镜像）
4. 其他社区源
```

**实现**：在 `merge_index.py` 去重阶段，同 `source_url` 多源命中时按 `source_priority` 字段排序保留 highest，但**合并所有源的元数据**（如 `install_count` 来自 skills.sh、`stars` 来自 GitHub API）。

**理由**：避免镜像版本覆盖直接源的 source_url；同时不丢失 install_count 信号。

### D5: schema 字段添加策略

**选择**：在 skill entry 上新增 3 字段，向后兼容

```json
{
  "id": "vercel-react-best-practices-vercel-labs",
  "name": "vercel-react-best-practices",
  "source_url": "https://github.com/vercel-labs/agent-skills/tree/main/skills/...",
  "install_count": 69954,                 // NEW
  "skills_sh_url": "https://skills.sh/vercel-labs/agent-skills/vercel-react-best-practices",  // NEW
  "skills_sh_scraped_at": "2026-01-30T04:51:07Z",  // NEW
  ...其他既有字段
}
```

**向后兼容**：旧条目不强制要求这 3 字段，merge_index 不报错。Schema 校验为可选字段。

**理由**：
- 单独字段比嵌套 `skills_sh: {...}` 对象更易在搜索/排序时使用（避免每次访问 `entry.skills_sh?.url`）
- 字段名带 `skills_sh_` 前缀避免命名冲突

### D6: CI 增量更新策略

**关键挑战**：每周 cron 跑全量同步，若每次 LLM 评估 200-400 条新 skill，成本累计。

**选择**：复用现有增量机制 + 新增 mastra snapshot 缓存

```
.github/workflows/sync.yml 流程演进：

  crawl_mcp_so → sync_mcp → sync_rules → sync_skills →
    sync_skills_sh (NEW) → sync_prompts → verify_sync →
    merge_index → update_readme → audit_popular_coverage (NEW) →
    auto commit+push

actions/cache 缓存键扩展：
  ├ 既有：.llm_cache.json, .eval_cache/, incremental_recrawl_state.json
  └ 新增：.skills_sh_cache/  ← 存 mastra JSON 上次拉取的 ETag + scrapedAt
                              用于判断「数据未变更则跳过下游处理」
```

**增量逻辑**：
1. 拉 mastra JSON 时附带 `If-None-Match` header，ETag 命中则直接复用本地副本
2. 解析后与上次 catalog 的 skill set 做 diff（按 `source_url + skillId` 复合 key）
3. 仅对**新增条目**或 `install_count` 变化超过 ±20% 的条目重跑 LLM 评估
4. 已有评估结果通过 `.eval_cache/` 的 SQLite 命中复用

**回退兜底**：mastra JSON `scrapedAt` 距今 >7 天时，CI 输出 WARNING，启用 skills.sh API 全量重拉，跑完后把数据写入本地缓存视作新 snapshot。

### D7: 评分管线接入

**选择**：install_count 作为可选 health 信号，默认权重 0

**理由**：
- 不改现有评分行为（保守，避免一次大幅波动）
- 字段先采集到 health.signals.install_popularity，权重为 0 不影响 final_score
- 留数据 baseline 后续 A/B 调权（例如用 install_count 替代或补充 GitHub stars 的 popularity 信号）

**未来路径**（不在本 change 范围）：
- 调权方案如 `popularity = 0.6 * stars_signal + 0.4 * install_signal`
- 需要先观察 install_count 分布与 stars 的相关性

### D8: 覆盖率审计脚本

**选择**：新增 `scripts/audit_popular_coverage.py`，CI 中跑，输出 markdown 报告到 `docs/coverage_report.md`

**输入**：
- catalog/index.json
- 一份 hard-coded "热门 skill 期望清单"（YAML 文件，初版含 Top 20）
- skills.sh top-N（自动从 install_count 排序）

**输出**：
- `docs/coverage_report.md`（自动 commit）
- 字段：每个期望 skill 的「直接源 / 镜像 / 缺失 / install_count」状态

**作用**：作为 leader 沟通材料、回应「漏收录」质疑的客观数据。

## Risks / Trade-offs

**[mastra-ai/skills-api 项目停止维护]** → 监控 scrapedAt 字段 >7 天报警，自动降级到 skills.sh API 直连

**[skills.sh 改 API 路径]** → mastra 会先踩坑修复，跟随其变更；本地 fallback 路径加 try/except 兜底

**[GitHub raw 拉取 8MB JSON 被限速]** → 必须带 GITHUB_TOKEN（CI 已有）；本地用 ETag 缓存避免重复拉

**[install_count 信号被刷量污染]** → 暂不参与 final_score 权重；评分管线维持现状；如发现刷量再设 ceiling

**[阈值 1000 漏掉新晋优质 skill]** → 阈值参数化（env var），CI 可季度复评；同时保留现有 Tier 1 直接源不取消

**[与 antigravity 镜像大量重叠]** → source_url 去重 + 优先级合并；预期镜像保留率 <30%

**[schema 字段污染旧条目]** → 新字段全部 optional，旧条目缺省 None；merge_index 容错读取

**[CI 评估成本失控]** → 增量评估 + content_hash 缓存 + EVAL_INCREMENTAL=true 硬编码；新源首次接入时人工 dry-run 一次确认成本

## Migration Plan

**首次上线**（不破坏现状）：
1. 部署 sync_skills_sh.py，本地 dry-run 拉数据，人工 review skills_sh_index.json
2. 跑一次 merge_index 在测试分支验证去重正确性
3. 把 LLM_API_KEY 设上后跑一次 EVAL_DRY_RUN=false 评估，确认成本与 reject 比例
4. 合并到 main，CI 接管

**回滚**：
- 出问题时 revert PR 即可，旧 catalog 不依赖新字段
- skills_sh_index.json 单独删除不影响其他源

**长期**：
- 观察 install_count 与 final_score 相关性，决定是否调权
- audit_popular_coverage 报告纳入 weekly review

## Open Questions

1. **mastra JSON 的更新频率**？READMEN 没声明，需观察 1-2 周。如果 <每周更新，C 方案降级触发会频繁；可调降级阈值到 14 天。
2. **是否需要专门的 sync_skills_sh CI artifact**？目前打算共用现有 `.eval_cache/` 缓存，但若数据膨胀可考虑独立 cache key。
3. **skills.sh skill 详情页是否含 platforms_supported 信息**？如果有，未来 platforms_supported 字段可从这里提取，避免另解析 SKILL.md。本 change 范围内不做。
4. **覆盖率审计的「期望清单」从哪里维护**？建议初版 hard-coded YAML，后续可从 skills.sh top-100 动态生成。
