## Context

`add-plugins-category` change 把 plugin 作为 catalog 第 5 类资源接入：sync 阶段从 marketplace 拉 plugin 元数据，evaluation 阶段走 health-only + enrichment（`plugin.yaml` task config）。但当前实现：
- sync 写入 `bundle.skills_count = 0` 等占位数据，没真正填实
- evaluation 用 `GitHubFetcher` 拉 plugin 子目录的 README，是 plugin 包装层卡片
- `merge_index._apply_bundled_in_annotations` 已就位但因 bundle 空所以 0 标注生效

Spike（`tools/plugin_content_spike.py`，2026-05-07）跑 20 sample 验证：

| 验证项 | 结果 |
|--------|------|
| Layout detection（`.claude-plugin/plugin.json` 边界识别） | 19/20 通过 |
| Bundle 算法 vs ground truth | 12/20 fixture 准确，剩余因手工估错（算法对） |
| 内容归一化（全拼接 + size_cap） | obra/superpowers 6% MiMo context；affaan-m 用 600KB cap 兜住 |
| MiMo 真打 | 7/7 sample, 0 timeout, p95 latency 10.5s |
| Keyword 命中率 | baseline 83% → new 100% |
| token 成本放大 | ~7.7x（绝对值仍小） |

Spike 数据 → spec.md 的 ADDED scenarios 直接引用。

## Goals / Non-Goals

**Goals:**

- 让 plugin evaluation 输入从"包装层 README"升级到"实质内容拼接"（plugin.json + SKILL.md + agents + commands）
- 让 sync 阶段真正填充 `bundle.skills_count` / `agents_count` / `commands_count` / `skills_namespaces`，使 `_apply_bundled_in_annotations` 软标注首次生效
- 用一条统一规则覆盖 5 种 layout（marketplace subdir / root plugin / nested marketplace / dev monorepo / root-level dir）
- 控制成本：单 plugin 内容 < 600KB（spike-validated 安全线），CI tree API ~200 calls 在 5000 hourly 限额内
- 不破坏现有 mcp / skill / rule / prompt 评估路径

**Non-Goals:**

- 不抓 `.codex/` / `.gemini/` 等平台特定影子目录（这些不是 Claude plugin 内容）
- 不修改 plugin task 评分维度（保持 health-only + enrichment 不变）
- 不改 `evo` 命令对 plugin 的拒绝（保持现行）
- 不为 plugin 引入跨进程 / 持久化 cache（in-memory 已足够）
- 不解决"affaan-m 这种巨型 plugin 评分质量"——size_cap 触发后只能基于前 5 个全文文件评估，是已知 trade-off

## Decisions

### Decision 1: layout 识别用统一规则"含 `.claude-plugin/plugin.json` 的目录 = plugin root"

**采用**：扫 tree paths，所有以 `.claude-plugin/plugin.json` 结尾或等于该 path 的位置，其上方目录即为 plugin root。`.claude-plugin/plugin.json` 在 root 表示整个 repo 是 single plugin（L2/L3 形态）；在子目录表示 monorepo 子 plugin（L1/L4 形态）。target_root 由调用方传入（catalog entry 的 `source_url` 解析得到的 subpath，或空字符串）。

**备选 1**：按 source_url 形态分支处理（subdir / root / etc.）
- 拒绝理由：Spike 实测 5 种 layout 都满足同一规则。分支处理增加代码量但收益为 0。

**备选 2**：先 ls /repo/contents 找根级 .claude-plugin/，再递归
- 拒绝理由：每层目录一次 GitHub API call，10x rate limit 消耗。Tree API recursive=true 一次拿全。

### Decision 2: 内容归一化策略：全拼 + size_cap fallback

**采用**：所有 SKILL.md / agents/*.md / commands/*.md 按 `path 字母序` 拼接，每文件加 `## <path>` 章节标题。运行总长超 `size_cap = 600_000 bytes`（约 150k tokens, 15% MiMo 1M context）后，剩余文件仅取 YAML frontmatter + 第一段（最多 800 chars）。

**备选 1**：全文一律截断到 N kb
- 拒绝理由：spike 实测 obra/superpowers（14 SKILL, 248KB）能完整拼且 6% MiMo context；统一截断浪费 MiMo 1M 优势。

**备选 2**：按 stars / install_count 排序优先级
- 拒绝理由：plugin 内 SKILL 没有 per-skill stars 信号；按字母序稳定性最好（不依赖外部排序信号），实测命中率已达 100%。

**备选 3**：每个 SKILL.md 单独一次 LLM 评估，最后聚合
- 拒绝理由：成本 N× 放大，affaan-m 这种 600+ 文件直接爆 token。实证全拼已足够。

### Decision 3: PluginContentFetcher 独立类，不改 GitHubFetcher

**采用**：在 `ai-resource-eval/ai_resource_eval/fetcher/plugin.py` 新增 `PluginContentFetcher`。`runner._fetch_content` 按 `entry.type == "plugin"` 路由：plugin → PluginContentFetcher，其他 → 现行 GitHubFetcher。

**备选 1**：扩展 GitHubFetcher 加 plugin mode
- 拒绝理由：把 plugin-specific tree parsing + 多文件拼接塞进单类违反单一职责；plugin layout 检测 / size_cap / frontmatter 截断都是 plugin 独有。

**备选 2**：在 task config 用 `content_paths: ["**/SKILL.md", ...]` glob
- 拒绝理由：现有 fetcher content_paths 是顺序尝试的字符串列表，不支持 glob；改造成本超过新增类。

### Decision 4: sync 阶段调 layout detector 但不抓内容

**采用**：sync_plugins_official / sync_plugins_dev 在生成每条 plugin entry 时，调 `PluginContentFetcher.detect_plugin_layout(repo, plugin_root)` 拿 plugin 的 file paths（仅 path，不拉内容），填 `bundle.skills_count` / `agents_count` / `commands_count` / `skills_namespaces`。evaluation 阶段才会真正拉文件内容。

**备选 1**：sync 阶段直接拉所有内容存 catalog
- 拒绝理由：catalog/plugins/index.json 体积爆炸（901 plugin × 平均 50KB = ~45MB JSON）；evaluation 阶段才需要内容。

**备选 2**：evaluation 阶段顺便回填 bundle 字段到 entry
- 拒绝理由：违反职责分离（evaluation 不该改 sync 阶段产出）；且当 bundle 字段缺失时，merge_index 的 `_apply_bundled_in_annotations` 在 evaluation 之前就会跑，这时拿不到。

### Decision 5: GitHub Tree API by `(repo, ref)` cache + raw fetch by URL cache

**采用**：`PluginContentFetcher` 实例上挂两个 dict：
- `_tree_cache: dict[tuple[str, str], dict]`（key=`(repo, ref)`，value=tree json）
- `_raw_cache: dict[str, str | None]`（继承自 GitHubFetcher 的模式）

进程内同一 marketplace repo 跨多个 plugin 共享一次 tree call（anthropic 50 plugin → 1 tree call）。

**备选**：fetcher per-plugin 实例
- 拒绝理由：900+ plugin 创 900 个 fetcher 实例无意义；ClassVar 风格不满足 cache key 复杂度（要带 repo, ref）；实例 cache 简单可用。

### Decision 6: 无 plugin.json 的 fallback 行为

**采用**：`detect_plugin_layout(repo, plugin_root)` 在 target_root 没有 `.claude-plugin/plugin.json` 时返回 `is_plugin=False` + 空 file paths，调用方 fallback 到现行 `GitHubFetcher` 拉 README.md。这样 `clangd-lsp` 这种"声明在 marketplace 但实际仅有 README"的边缘形态保持现行评估行为。

**备选**：硬要求 plugin.json 否则评估失败
- 拒绝理由：catalog 已收录这种边缘 plugin，强制要求会让 14 个 entry 直接 reject；保持 fallback 更稳。

### Decision 7: 平台特定影子目录排除规则

**采用**：扫 plugin paths 时排除任何包含 `.` 开头 segment 的路径（除 `.claude-plugin/` 自身，但它在 plugin root 之上不包含 `.` 段）。这剔除 `.codex/skills/...` / `.gemini/skills/...` / `.github/...` 等非 Claude plugin 内容。

**Spike 验证**：trailofbits/skills 含 `.codex/skills/gh-cli/SKILL.md` 不归任何 plugin，alirezarezvani/claude-skills 含 `.gemini/skills/...` 大量 noise，规则正确剔除。

## Risks / Trade-offs

| Risk | Mitigation |
|------|-----------|
| GitHub Tree API rate limit (5000/h authenticated) | ~200 unique repo（901 plugin 共享 marketplace），单次 sync 200 calls ≈ 4% 限额。无 token 时 60/h 不够，但 CI 有 token。 |
| affaan-m 类 outlier（212 skill + 160 agent + 255 commands，3.2MB raw）超 MiMo context | size_cap=600KB（spike 实测覆盖 affaan-m 后总长降到 890KB，仍含前 5 个全文 SKILL）。极端情况 enrichment 质量略降但仍可用。 |
| size_cap 截断对 MiMo evaluation 的语义影响 | spike 7/7 sample 跑通，未观察到 LLM 回答破裂；保留 frontmatter description 让 LLM 知道剩余 SKILL 的存在 |
| sync 阶段每个 plugin 多一次 tree API 调用，sync 时长增加 | 1 次 tree API ≈ 200ms；200 unique repo ≈ 40s 增量。在现有 weekly cron 中可忽略 |
| `_apply_bundled_in_annotations` 首次生效后，README/featured 显示的"top skill"会发生变化（plugin 内部 skill 被过滤） | 这是预期行为（add-plugins-category 设计意图）；首次 PR 中文档说明 |
| skill_namespaces 命名规范变更（plugin name vs plugin path） | 用 `<plugin-name>:<skill-name>` 形态，plugin-name 取 plugin_root 的最后一段（marketplace subdir 形态）或 plugin.json 的 name 字段（root plugin 形态） |
| plugin.json 拉取失败时整个 plugin 退化到 fallback README | 保持现行 GitHubFetcher 路径，不退化为 reject；catalog 收录不变 |

## Migration Plan

1. **PR 1（核心 fetcher）**：新增 `PluginContentFetcher` + 单测，runner 加路由分支。先不改 plugin.yaml，本 PR 仅引入但不激活。验证：现有 plugin 评估走 GitHubFetcher 路径不变，新代码 import 不破坏现有测试。
2. **PR 2（task config 切换）**：plugin.yaml 的 `content_source` 从 `readme` 改为 `plugin_bundle`，激活 PluginContentFetcher。CI 跑一次验证 901 plugin 全跑通、enrichment 质量提升、token cost 控制在预期。
3. **PR 3（sync 填充 bundle）**：sync_plugins_official / sync_plugins_dev 在 sync 时调 layout detector 填 bundle 字段。CI 跑一次后 `_apply_bundled_in_annotations` 首次实数标注，README 渲染发生变化。
4. **回滚**：按 PR 倒序 revert。每 PR 独立可回。`PluginContentFetcher` 不污染 EvalCache（cache key 仍按 content_hash）。

## Open Questions

- 是否需要在 spike 阶段把 affaan-m 这种 outlier plugin 单独评分（每个内部 SKILL 评一次再聚合）？当前判断不做：实质内容前 5 个全文 + 其他 frontmatter 已覆盖 MiMo context 的 ~15%，evaluation 质量可接受。等首次 CI 跑出 affaan-m 的 final_score 实测 < 60 再考虑分桶评估方案。
- `bundle.mcp_servers_count` 怎么填？plugin 内部可能含 `.claude-plugin/` 内的 mcp 配置 JSON（如 `mcp_servers/foo.json`），但 spike 没探测此 layout。**当前默认 0**，遇到含 mcp 的 plugin 时再扩展规则。
- 平台特定影子目录的处理：除 `.codex/` / `.gemini/`，是否还有其他类似目录需要排除？Spike 没发现，留 catch-all 规则（任何 `.` 开头 segment 都排除，除 `.claude-plugin/` 自身）。
