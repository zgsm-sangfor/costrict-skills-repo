# skills.sh / mastra-ai 接入基线探针报告

OpenSpec change: `add-skills-sh-tier1-source` — Section 1（探针与基线）

## 数据快照

| 字段 | 值 |
|------|----|
| 数据源 | `https://raw.githubusercontent.com/mastra-ai/skills-api/main/src/registry/scraped-skills.json` |
| 文件大小 | 10 MB |
| `scrapedAt` | `2026-01-30T04:51:07.907Z` |
| `totalSkills` | 34,311 |
| `totalSources` | 2,843（unique repo） |
| `totalOwners` | 2,451 |

> 注：mastra-ai/skills-api 是 skills.sh 官方维护的爬虫仓库。我们直接拉静态 JSON 主路径稳定、零 rate limit；仓库 cron 每日刷新，目前快照已 ~3 个月，需关注新鲜度。

## 阈值过滤分布

### Skill 级（含同 repo 多 skill）

| 阈值 | skill 数 | 占比 |
|------|---------|------|
| `installs ≥ 100` | 1,105 | 3.22% |
| `installs ≥ 500` | 339 | 0.99% |
| `installs ≥ 1000` | **153** | **0.45%** |
| `installs ≥ 5000` | 17 | 0.05% |
| `installs ≥ 10000` | 7 | 0.02% |

### Repo 级（按 `max(installs)` 聚合）

| 阈值 | repo 数 |
|------|---------|
| `max ≥ 100` | 144 |
| `max ≥ 500` | 55 |
| `max ≥ 1000` | **30** |
| `max ≥ 5000` | 12 |
| `max ≥ 10000` | 5 |

阈值 1000 在 repo 维度命中 30 个 repo，对应 153 个 skill。这与 design.md 对齐 vercel-labs/find-skills 质量基线的预期一致。

## Top 10 by install_count（skill 级）

| # | installs | owner/repo | skillId |
|---|---------:|-----------|---------|
| 1 | 69,954 | vercel-labs/agent-skills | vercel-react-best-practices |
| 2 | 53,076 | vercel-labs/agent-skills | web-design-guidelines |
| 3 | 50,464 | remotion-dev/skills | remotion-best-practices |
| 4 | 49,281 | vercel-labs/skills | find-skills |
| 5 | 25,571 | anthropics/skills | frontend-design |
| 6 | 14,925 | vercel-labs/agent-browser | agent-browser |
| 7 | 12,596 | anthropics/skills | skill-creator |
| 8 | 9,733 | vercel-labs/agent-skills | vercel-composition-patterns |
| 9 | 7,854 | coreyhaines31/marketingskills | seo-audit |
| 10 | 7,783 | squirrelscan/skills | audit-website |

## 与既有 catalog 重叠分析

现有 `catalog/skills/index.json` 共 1,676 条，但只来自 **8 个 upstream repo**：

| catalog 条目数 | upstream repo |
|--------------:|---------------|
| 1,294 | sickn33/antigravity-awesome-skills |
| 272 | davila7/claude-code-templates |
| 62 | vasilyu1983/ai-agents-public |
| 17 | anthropics/skills |
| 17 | skillcreatorai/ai-agent-skills |
| 9 | anthropics/claude-code |
| 3 | kepano/obsidian-skills |
| 2 | nextlevelbuilder/ui-ux-pro-max-skill |

**重叠（mastra `≥1000` 的 30 个 repo vs catalog）**：

| mastra installs | owner/repo | 已在 catalog |
|---------------:|------------|:------------:|
| 25,571 | anthropics/skills | ✅（17 条） |
| 6,900 | nextlevelbuilder/ui-ux-pro-max-skill | ✅（2 条） |
| 1,380 | anthropics/claude-code | ✅（9 条） |

- 重叠 repo 数：**3 / 30**
- 完全新 repo（≥1000 installs）：**27 / 30**
- 与 antigravity 镜像（sickn33/*）重叠：**0**（mastra 几乎不收录镜像 repo，符合预期）

> 关键发现：sickn33 镜像在 catalog 占比极高（77%），但其 1,294 条 skill 在 mastra 中**无 install 信号**——因为 mastra 抓取的是 skills.sh 上 owner 自行注册的源 repo，镜像 repo 本身 install_count 为 0。这意味着 skills.sh 的 install_count 可以作为**指向镜像背后真源**的高质量信号。

## 期望 7 条 skill / repo 命中状况

| 期望 | 在 mastra | max_installs | mastra skill 数 | 在 catalog |
|------|:--------:|------------:|:--------------:|:---------:|
| obra/superpowers | ✅ | 4,736 | 14 | ❌ |
| vercel-labs/agent-skills | ✅ | 69,954 | 6 | ❌ |
| vercel-labs/agent-browser | ✅ | 14,925 | 1 | ❌ |
| supermemoryai/supermemory | ❌ | — | — | ❌ |
| Leonxlnx/taste | ❌ | — | — | ❌ |
| Dammyjay93/interface-design | ⚠️（仅 201） | 201 | 1 | ❌ |
| anthropics/skills | ✅ | 25,571 | 17 | ✅ |

- 7 条期望中 **5 条命中 mastra**（4 条满足 ≥1000 阈值，1 条仅 201 installs 不满足）
- 2 条未命中：`supermemoryai/supermemory`、`Leonxlnx/taste`——可能 owner 未在 skills.sh 注册，或注册时间晚于 2026-01-30 快照
- 唯一与 catalog 重叠的是 anthropics/skills（已通过 anthropics 直接源进来）

## Top 30 新增 repo（≥1000 installs，不在 catalog）

预览阈值 1000 接入后会净增的 repo 列表（按 max_installs 排序）：

| # | max_installs | owner/repo | mastra skill 数 |
|--:|-----------:|------------|--------------:|
| 1 | 69,954 | vercel-labs/agent-skills | 6 |
| 2 | 50,464 | remotion-dev/skills | 4 |
| 3 | 49,281 | vercel-labs/skills | 2 |
| 4 | 14,925 | vercel-labs/agent-browser | 1 |
| 5 | 7,854 | coreyhaines31/marketingskills | 25 |
| 6 | 7,783 | squirrelscan/skills | 1 |
| 7 | 7,260 | supabase/agent-skills | 2 |
| 8 | 6,212 | browser-use/browser-use | 1 |
| 9 | 5,558 | expo/skills | 9 |
| 10 | 5,215 | better-auth/skills | 4 |
| 11 | 4,736 | obra/superpowers | 14 |
| 12 | 3,478 | hyf0/vue-skills | 10 |
| 13 | 3,285 | callstackincubator/agent-skills | 3 |
| 14 | 2,394 | vercel-labs/next-skills | 14 |
| 15 | 2,007 | jimliu/baoyu-skills | 17 |
| 16 | 1,939 | softaworks/agent-toolkit | 42 |
| 17 | 1,856 | vercel/ai | 4 |
| 18 | 1,725 | wshobson/agents | 129 |
| 19 | 1,704 | benjitaylor/agentation | 1 |
| 20 | 1,686 | subsy/ralph-tui | 4 |
| 21 | 1,651 | vercel/turborepo | 1 |
| 22 | 1,634 | atxp-dev/cli | 2 |
| 23 | 1,536 | google-labs-code/stitch-skills | 4 |
| 24 | 1,534 | giuseppe-trisciuoglio/developer-kit | 5 |
| 25 | 1,349 | antfu/skills | 15 |
| 26 | 1,197 | op7418/humanizer-zh | 1 |
| 27 | 1,021 | langgenius/dify | 7 |

（清单 27 条 = 30 个新 repo - 3 个非 ≥1000 的；上方表已扣除重叠的 anthropics/skills、anthropics/claude-code、nextlevelbuilder/ui-ux-pro-max-skill）

## 总结与建议

### 阈值 1000 是否合理

**合理，建议保持**。理由：

1. **数量级可控**：repo 级 30 个、skill 级 153 个——既显著扩充 catalog（净增 ~150 skill ≈ 当前非镜像 catalog 的 39%），又不引入低质长尾噪音
2. **质量信号明确**：1000 installs 在 skills.sh 上属顶部 0.45%，对齐 vercel-labs/find-skills 这个由 Vercel 官方维护的质量榜
3. **与现有源强互补**：30 个 ≥1000 repo 中 27 个是 catalog 完全没有的新 owner / 新组织（vercel-labs、remotion-dev、supabase、expo、better-auth、browser-use、obra、callstack 等），明显改善生态多样性
4. **期望命中率 4/7**：核心期望 skill（obra/superpowers、vercel-labs 全家桶、anthropics/skills）都可达——剩下 2 条期望 mastra 暂未抓到，1 条未达阈值，这些可走 curated 兜底

### 预期入库量级

- **首批入库**：≈ 153 个 skill（30 个 repo），其中 ~8 与既有源重合可去重，**净增 145 skill** 左右
- **若降阈到 500**：repo 级 55 个 → 估算净增 ~270 skill（噪音上升，需更严格的 LLM 评估过滤）
- **若升阈到 5000**：repo 级 12 个 → 净增 ~50 skill（覆盖太窄）

### 后续步骤

1. **Section 2（实现）**：按 design.md D1 写 `sync_skills_sh.py`，主路径 mastra JSON + 备用 skills.sh 隐藏 API
2. **Tier 1 合并策略**：保留 `source_url` 为 mastra 的 `githubUrl`（repo 级），但每 skill 仍以 `skillId` 区分，避免与 anthropics/skills 的 17 条已有条目冲突
3. **install_count 字段保留**：作为新的 popularity 信号，可考虑下沉到 `health.signals`
4. **快照新鲜度**：跟踪 `scrapedAt`，若超过 14 天考虑切到隐藏 API 的实时分页路径补刷

### 阻塞 / 风险

无。mastra JSON 拉取顺利，catalog 结构与预期一致。

> 注意：catalog 现有 `source_url` 是 per-skill 的子路径（如 `.../tree/main/skills/algorithmic-art`），而 mastra 是 repo-level URL（`.../skills`）。后续合并需用 `(owner, repo, skillId)` 三元组做唯一键，不能直接对 URL 做字符串相等。
