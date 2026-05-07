## Why

`add-plugins-category` change 把 plugin 作为第 5 类资源接入了 catalog，但 sync 阶段对 plugin 的元数据填充和评估阶段的内容输入都停留在"包装层"：

- **Bundle 字段空**：当前 901 plugin 中只有 48 个（5%）`bundle.skills_count > 0`，853 个全部空数据。`bundle.skills_namespaces` 几乎全为空数组。
- **`bundled_in` 软标注未生效**：1795 个 skill 中 0 个被任何 plugin 标注。catalog 内 plugin 顶层 + 内部 skill 同时收录，重复推荐（实测 anthropic-code-simplifier vs code-simplifier-skill / anthropic-superpowers vs using-superpowers-skill 等多处）。
- **Evaluation 输入不实质**：plugin 评估读 root README.md，那是"包装层"卡片（"What this plugin does + 安装命令"），不是 plugin 内部 skill / agent / command 的实质能力描述。Spike 实测 mongodb-agent-skills 用 README enrichment 命中 1/3 expected keywords，用全 SKILL.md 拼接命中 3/3。

经 spike 验证（`tools/plugin_content_spike.py` 跑 20 个 sample，7 个完整 LLM 对比）：
- 抓 plugin 真实子目录（`.claude-plugin/plugin.json` + `skills/*/SKILL.md` + `agents/*.md` + `commands/*.md`）后，enrichment 的 expected keyword 命中率从 baseline 83% 提升到 100%。
- mongodb 改进最显著：summary 从"Official MongoDB agent skills..."升级到"Comprehensive MongoDB plugin with MCP server and skills for connection, querying, optimization, schema, search, and stream..."。
- MiMo 真打 0 timeout, p95 latency 10.5s，token 7.7x 放大但绝对值仍小（30k vs 4k）。

## What Changes

- **新增 `PluginContentFetcher`**：在 `ai-resource-eval` 增加 plugin 类型专用的内容获取器：
  - 用 GitHub Tree API recursive=true 一次拿仓库全部文件路径（同 marketplace repo 跨多个 plugin 共享一次 tree call）
  - 按统一规则识别 plugin 边界：含 `.claude-plugin/plugin.json` 的目录 = plugin root（覆盖 marketplace subdir / root plugin / nested layout 多种形态）
  - 抓 plugin.json + skills/*/SKILL.md + agents/*.md + commands/*.md，全拼接归一化
  - size_cap 兜底：超 600KB 时除前 5 个文件全文外，其余仅取 frontmatter / 前 800 字符（应对 affaan-m 这种 3.2MB outlier）
  - 缓存：tree by `(repo, ref)`、raw 文件 by URL，进程内 in-memory 避免重复
- **plugin task config 切换 content_source**：从 `readme` 改为新的 `plugin_bundle`，触发 `PluginContentFetcher` 而非现有 `GitHubFetcher`
- **`runner._fetch_content` 路由**：`entry.type == "plugin"` 时调用 `PluginContentFetcher`，其他类型保持现行 `GitHubFetcher`
- **修 sync 阶段填实 bundle 字段**：`sync_plugins_official.py` / `sync_plugins_dev.py` 在 sync 时复用 `PluginContentFetcher.detect_plugin_layout()` 把 `bundle.skills_count` / `agents_count` / `commands_count` / `skills_namespaces` 填实数（不抓内容，只列文件）。这让 `_apply_bundled_in_annotations` 软标注生效。

## Capabilities

### New Capabilities

- `plugin-content-fetcher`: ai-resource-eval 的 plugin 类型内容获取器规范——layout 检测规则（`.claude-plugin/plugin.json` 边界识别）、文件分类（SKILL.md / agents / commands / mcp_servers）、归一化拼接策略（全拼 + size_cap fallback）、缓存约束（tree/raw 进程内共享）、错误兜底（无 plugin.json fallback 到 README only / tree API 失败保持现行 GitHubFetcher）

### Modified Capabilities

- `plugins-category`: plugin 评估输入从 README 切换到实质内容拼接；plugin task config `content_source` 从 `readme` 改为 `plugin_bundle`
- `plugin-bundle-dedup`: bundle 字段填充时机从"sync 阶段写 0 占位、由后续手工填"改为"sync 阶段调用 PluginContentFetcher 填实数"，让 `_apply_bundled_in_annotations` 真正起作用

## Impact

**新增文件**：
- `ai-resource-eval/ai_resource_eval/fetcher/plugin.py`（新 `PluginContentFetcher` 类）
- `ai-resource-eval/tests/test_plugin_content_fetcher.py`（单测）
- `tests/test_sync_plugins_bundle_substance.py`（sync 阶段 bundle 填充集成测试）

**修改文件**：
- `ai-resource-eval/ai_resource_eval/runner.py`：`_fetch_content` 加 `entry.type == "plugin"` 路由
- `ai-resource-eval/ai_resource_eval/tasks/plugin.yaml`：`content_source` 从 `readme` 改为 `plugin_bundle`（如新增枚举）
- `ai-resource-eval/ai_resource_eval/api/types.py`：`ContentSource` 枚举加 `plugin_bundle`（如必要）
- `scripts/sync_plugins_official.py`：sync 时调用 `PluginContentFetcher` 拿 layout，填 `bundle.skills_count` / `skills_namespaces`
- `scripts/sync_plugins_dev.py`：同上（dev 源由 API 提供 `skills` 数组，可保持现行 + 配合 PluginContentFetcher 二次校准）

**配置 / 环境变量**：
- 无新环境变量
- GitHub Tree API 走现有 `GITHUB_TOKEN`，rate limit 按 `~200 unique repo / 5000 hourly` 估算约 4% 限额

**CI 影响**：
- 首次 sync 后 plugin entry 的 `bundle` 字段从全 0 变成实数；`bundled_in` 软标注首次生效，预计 1795 skill 中数百条会获得 `bundled_in` 标注
- README/featured 渲染过滤 `bundled_in` 非空 skill 后，"top 5 skill" 列表会发生变化（plugin 内部 skill 沉到 plugin 区块，留位给独立 skill）
- evaluation token 成本预计 ×7-10（901 plugin × 单次 enrichment 调用），incremental cache 命中后稳态恢复

**不影响**：
- 其他类型（mcp / skill / rule / prompt）的 evaluation 路径完全不变
- evo 命令边界（已拒绝 plugin 类型）
- catalog/index.json 的 schema（plugin 字段早已声明，仅填充策略变化）
