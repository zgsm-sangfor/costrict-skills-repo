## 1. Spike 第二轮 — TDD 小样本验证（先做，验证通过再实施生产代码）

- [x] 1.1 扩展 `tools/plugin_content_spike.py`：抓 plugin **install 命令**段落（plugin.json 的 `install` 字段 + README 中带 `## Installation` / `## 安装` / `npm install` / `/plugin install` 等关键字的章节）。归一化时保留 install 段独立 section。
- [x] 1.2 扩展 `tests/test_plugin_content_spike.py` 加 T6 验证：每个 sample 的 normalized content 含 install 命令关键词（`/plugin install` / `npm install` / `marketplace add` 等其中之一），sample 自带的 install 字段（marketplace.json 解析得到）非空。
- [x] 1.3 扩展 fixture：sample.expected_install_keywords，每个 sample 含 1-3 个 install 命令关键词（如 `marketplace add`、`/plugin install <name>`）。
- [x] 1.4 扩展 spike script 输出 catalog-shaped entry（`bundle` + `install` + 完整 enrichment fields），写到 `/tmp/spike_catalog_preview.json`。验证字段完整性、shape 跟现有 catalog/plugins/index.json 一致。
- [x] 1.5 跑 spike 第二轮：`python3 tools/plugin_content_spike.py --output /tmp/spike_v2.json`（用 GITHUB_TOKEN 解 rate limit，全部 20 sample 拿到 tree + 内容 + 真打 MiMo）。
- [x] 1.6 跑 TDD test：`python -m pytest tests/test_plugin_content_spike.py -v`。验证 T1-T6 全过；不过则回 spike script 调整。
- [x] 1.7 抽样 review：从 spike_v2.json 抽 5 个不同 layout 的 catalog-preview entry，人工检查 bundle / install / enrichment 字段质量是否健康。
- [x] 1.8 决策点：spike 结果通过则进入 §2 实施生产代码；不过则记录原因更新 design.md 后再决定。

## 2. 生产代码 — 新增 PluginContentFetcher

- [x] 2.1 在 `ai-resource-eval/ai_resource_eval/fetcher/` 新增 `plugin.py`，实现 `PluginContentFetcher` 类（搬迁 spike 验证过的 layout detector + content normalizer + size_cap fallback）。
- [x] 2.2 实现 `detect_plugin_layout(repo: str, plugin_root: str = "") -> PluginLayout`：返回 plugin file paths（不抓内容），含 plugin_json_path / skill_paths / agent_paths / command_paths / skills_namespaces / is_plugin。
- [x] 2.3 实现 `fetch(source_url: str) -> tuple[content, content_hash] | None`：调 detect_plugin_layout + 拉文件 + 归一化拼接 + size_cap fallback。
- [x] 2.4 实现实例属性 cache：`_tree_cache: dict[(repo, ref), dict]` 和 `_raw_cache: dict[url, str|None]`。GIL 保护并发读写。
- [x] 2.5 实现 fallback：layout detector 返 is_plugin=False 时 `fetch` 返 None，调用方走现行 GitHubFetcher。
- [x] 2.6 在 `ai-resource-eval/ai_resource_eval/fetcher/__init__.py` 暴露 PluginContentFetcher。
- [x] 2.7 编写单测 `ai-resource-eval/tests/test_plugin_content_fetcher.py`：覆盖 layout detection（5 种 layout 各 1 sample）、size_cap fallback、shadow directory 排除、tree cache 跨 plugin 复用、raw cache 命中、fallback to None for non-plugin layout。

## 3. Runner 路由 + plugin task config 切换

- [x] 3.1 修改 `ai-resource-eval/ai_resource_eval/runner.py:_fetch_content`：对 `entry.type == "plugin"` 调 `PluginContentFetcher.fetch`，否则走现行 `GitHubFetcher.fetch`。
- [x] 3.2 PluginContentFetcher 返 None 时（fallback case）回退到 `GitHubFetcher` 拉 README，行为跟现行 plugin 评估等价。
- [x] 3.3 修改 `ai-resource-eval/ai_resource_eval/api/types.py`：`ContentSource` 枚举加 `plugin_bundle`（如必要）。
- [x] 3.4 修改 `ai-resource-eval/ai_resource_eval/tasks/plugin.yaml`：`content_source` 从 `readme` 改为 `plugin_bundle`。
- [x] 3.5 编写 runner 路由测试 `ai-resource-eval/tests/test_runner_plugin_routing.py`：验证 plugin entry → PluginContentFetcher，其他 type → GitHubFetcher。

## 4. Sync 阶段填充 bundle 字段

- [x] 4.1 修改 `scripts/sync_plugins_official.py`：每个 plugin entry 生成时调 `PluginContentFetcher.detect_plugin_layout(repo, plugin_root)`（不抓内容），用结果填 `bundle.skills_count` / `agents_count` / `commands_count` / `skills_namespaces`。
- [x] 4.2 修改 `scripts/sync_plugins_dev.py`：同上策略。dev API 返回的 `skills` 数组保留作 hint，但以 layout detector 为准（layout detector 更准确）。
- [x] 4.3 sync 阶段的 PluginContentFetcher 实例与 evaluation 阶段 isolation：每次 sync 跑独立实例，复用 tree cache 跨 plugin。
- [x] 4.4 layout detector 失败（GitHub Tree API 错 / repo 不存在）时，sync 不阻塞：保持 `bundle = {0,0,0,[]}` 占位写入，next sync 重试。
- [x] 4.5 编写集成测试 `tests/test_sync_plugins_bundle_substance.py`：mock GitHub API 返回 fixture tree，验证 sync 写出的 entry `bundle.skills_count` 不为 0、`skills_namespaces` 含合理 namespace。

## 5. 渐进式发布 — 三 PR 切片

- [x] 5.1 PR 1：核心 fetcher 引入但不激活——单 PR 集成路径替代，本地 LLM 3-sample 验证替代独立 PR 1 验证。
- [x] 5.2 PR 2：激活 PluginContentFetcher——Weekly Sync 25503674781 1h55m 完成，901 plugin 全跑通。
- [x] 5.3 PR 3：sync 阶段填 bundle 字段——CI 跑出 221 plugin 含 bundle，加 source_url 路径回退后 1301 skill 含 bundled_in。

## 6. 文档与归档

- [x] 6.1 在 `ai-resource-eval/CHANGELOG.md` Unreleased 段追加 PluginContentFetcher 说明。
- [x] 6.2 验收：plugin bundle non-zero=221 (target ≥ 200) ✓；bundled_in 非空 skill=1301 (target ≥ 100) ✓。
- [ ] 6.3 通过 `/opsx:archive improve-plugin-content-substance` 归档；将 `specs/plugin-content-fetcher/spec.md` 迁入 `openspec/specs/`、对 `plugins-category` 和 `plugin-bundle-dedup` 应用 MODIFIED delta。
