## Why

我们的 skill catalog 长期靠 GitHub stars 推断热度，但实际上 vercel-labs/agent-skills、supermemoryai/supermemory、obra/superpowers 这些社区头部 skill 在 catalog 里要么仅有镜像、要么完全缺失，leader 已感知到"我们没收录热门 skill"。skills.sh（Vercel 官方目录，2026-01 上线）提供 install_count 这一更真实的使用量信号，并已通过 mastra-ai/skills-api 项目暴露出 34,311 条 skill 的可程序化访问路径。一次性接入这一聚合源，比逐个加直接源更可持续。

## What Changes

- 新增 Tier 1 上游源 `skills.sh`，通过双路径接入：
  - **主路径**：拉取 `mastra-ai/skills-api` 仓库内置的 `scraped-skills.json`（一次 GET，34K+ 条全量）
  - **备用路径**：当 mastra 数据 scrapedAt 超过 7 天时，降级到 skills.sh 的 `/api/skills/all-time?page=N` 分页 API
- 入库阈值：`install_count ≥ 1000`（对齐 vercel-labs/find-skills 的质量基线）
- catalog skill entry schema 新增字段：
  - `install_count: int` — 来自 skills.sh 的真实安装量
  - `skills_sh_url: str` — skills.sh 上的规范化 URL
  - `skills_sh_scraped_at: ISO8601` — 数据快照时间
- 去重策略：`source_url` 优先级 `直接源 > anthropics/skills > skills.sh > antigravity 镜像`；同一仓库被 skills.sh 和镜像同时收录时保留前者
- CI 集成：`.github/workflows/sync.yml` 流程中在 `sync_skills` 之后插入 `sync_skills_sh`，复用 `actions/cache` 缓存 mastra JSON snapshot 与本地 fallback state；增量原则——仅评估 install_count 阈值过线 + 新增/变更条目
- 评分管线吸收 `install_count` 作为额外 health 信号（非阻塞，不改默认权重，预留后续调优）

## Capabilities

### New Capabilities

- `skills-sh-source-parser`: 从 skills.sh（经 mastra JSON 快照或直连 API）抓取 skill 数据并转换为 catalog entry 的 parser，含双路径降级、增量去重与 CI 缓存契约
- `popular-coverage-audit`: 定期对照外部"热门 skill"清单核对 catalog 覆盖率并输出 markdown 报告，作为防止"漏收录"复发的机制

### Modified Capabilities

- `catalog-entry-lifecycle`: skill entry 增加 `install_count` / `skills_sh_url` / `skills_sh_scraped_at` 三个新字段，原有字段不变
- `data-pipeline`: 在 sync 阶段新增 `sync_skills_sh.py` 步骤，介于 `sync_skills.py` 和 `merge_index.py` 之间；merge 时启用基于 `source_url` 的优先级去重
- `health-scoring`: `install_count` 作为可选 health 信号纳入评分输入（默认权重 0，留待后续 A/B 调权）

## Impact

**新增代码**：
- `scripts/sync_skills_sh.py`（新 parser，~200 行）
- `scripts/audit_popular_coverage.py`（覆盖率核查，~150 行）
- `tests/test_sync_skills_sh.py`、`tests/test_popular_coverage_audit.py`

**修改代码**：
- `scripts/merge_index.py`：去重优先级逻辑接受新字段
- `scripts/utils.py`：可能新增 `source_priority()` 工具函数
- `.github/workflows/sync.yml`：流水线步骤增加 + 缓存 key 扩展
- `catalog/skills/index.json` schema 新增 3 字段（向后兼容，旧条目缺字段不报错）

**外部依赖**：
- 新增依赖 `mastra-ai/skills-api` 仓库的 raw JSON（MIT 许可，第三方维护）
- skills.sh 隐藏 API 作为 fallback（无 SLA 承诺，但 mastra 在生产用）

**CI 资源**：
- 拉取约 8MB JSON（GITHUB_TOKEN 即可避免限流）
- 阈值 1000 后估算新增 200-400 条 skill 进 LLM 评估，单次 sync 约增加 ~$1-3 评估成本（取决于 LLM_MODEL）
- `.eval_cache/` 复用机制确保仅评估增量

**不影响**：
- 现有 sync_mcp/sync_rules/sync_prompts 流程
- 现有 catalog/{type}/curated.json 手工精选
- 评分管线默认行为（install_count 默认权重 0）
