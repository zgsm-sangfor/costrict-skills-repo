## 1. 探针与基线

- [x] 1.1 拉取 registry.modelcontextprotocol.io v0/servers 一次（带 cursor 全量），统计：active+isLatest 条数、与现有 catalog/mcp/index.json 的 source_url 重叠数（registry name 与 wong2 GitHub URL 的对应关系）
- [x] 1.2 拉取 SchneiderSam/awesome-windsurfrules 与 balqaasem/awesome-windsurfrules 仓库的 rules/ 目录，统计文件数 + 与现有 catalog/rules/index.json 重叠（按文件名与 frontmatter title）
- [x] 1.3 输出基线报告 `docs/tier1_rules_mcp_baseline.md`：进库条目数估算、重叠分析、跨平台 fuzzy match 边界案例（如 microsoft/playwright vs microsoft.com/playwright/mcp）

## 2. 核心 sync_mcp_registry.py

- [x] 2.1 新建 `scripts/sync_mcp_registry.py`，仅用 Python 标准库（urllib、json、os、hashlib、datetime）
- [x] 2.2 实现 `fetch_registry(limit=100)` 生成器：分页拉取 v0/servers，处理 cursor 翻页与 ETag 缓存到 `.mcp_registry_cache/registry.json` + `etag.txt`
- [x] 2.3 实现 active+isLatest 过滤：仅保留 `_meta.io.modelcontextprotocol.registry/official.status == "active"` 且 `isLatest == true`
- [x] 2.4 实现 `normalize_entry(raw)`：转换为 catalog mcp schema，含 mcp_registry_status / mcp_registry_published_at / mcp_remotes 三个新字段
- [x] 2.5 source_url 构造：`https://registry.modelcontextprotocol.io/v0/servers/{encoded_name}`（每条 entry 唯一，避免与 wong2 GitHub URL 错误合并）
- [x] 2.6 输出 `catalog/mcp/mcp_registry_index.json`，结构与现有 mcp child index 一致
- [x] 2.7 增量 diff 写入 `.mcp_registry_cache/diff.json`：added / status_changed / version_bumped / removed 四类
- [x] 2.8 单元测试 `tests/test_sync_mcp_registry.py`：覆盖分页 / ETag 304 / active 过滤 / isLatest 过滤 / id 唯一性 / 字段映射

## 3. 核心 sync_windsurfrules.py

- [x] 3.1 新建 `scripts/sync_windsurfrules.py`，参考 sync_skills.py 风格（GitHub API 列目录 + raw fetch 文件）
- [x] 3.2 配置两个仓库：SchneiderSam/awesome-windsurfrules + balqaasem/awesome-windsurfrules
- [x] 3.3 递归遍历 rules/ 子目录，对每个 .md 文件 fetch raw 内容
- [x] 3.4 global_rules 子目录特殊处理（SchneiderSam + balqaasem 两仓库都有，路径形如 `rules/global_rules/<slug>/global_rules.md`）：加 tag `windsurf-global` + category=global
- [x] 3.5 frontmatter 解析（含容错）：提取 name/description/category/tags
- [x] 3.6 id 生成：`<filename_slug>-<repo_slug>` 保证跨仓库唯一
- [x] 3.7 输出 `catalog/rules/windsurfrules_index.json`
- [x] 3.8 单元测试 `tests/test_sync_windsurfrules.py`：覆盖标准 rule / global_rule 标记 / frontmatter 容错 / id 跨仓库唯一性

## 4. merge_index 整合

- [x] 4.1 修改 `scripts/merge_index.py`：mcp 类型分支加载 `catalog/mcp/mcp_registry_index.json`
- [x] 4.2 修改 `scripts/merge_index.py`：rules 类型分支加载 `catalog/rules/windsurfrules_index.json`
- [x] 4.3 在 `scripts/utils.py` 扩展 `source_priority()`：注册 `registry.modelcontextprotocol.io`（900）与 `awesome-windsurfrules`（500）
- [x] 4.4 实现 `mcp_identity_key(entry)`：严格匹配，**不做 owner-only fuzzy match**。规则：`io.github.<owner>/<repo>` → `('github', owner/repo)`（与 GitHub URL 源 dedup）；其他 reverse-DNS（如 `com.microsoft/azure`）→ 独立 `('registry', registry_name)` key（避免错误合并同 owner 不同 product）；GitHub URL → `('github', owner/repo)`。详见 docs/tier1_rules_mcp_baseline.md §5。
- [x] 4.5 单元测试：覆盖 mcp 跨源去重 4 场景（仅 registry / 仅 wong2 / 双源 / fuzzy match）+ rules 跨仓库去重 3 场景

## 5. catalog schema 增量字段

- [x] 5.1 更新 `catalog/schema.json`：mcp entry 增加 mcp_registry_status / mcp_registry_published_at / mcp_remotes 三个 optional 字段
- [x] 5.2 status 字段加 enum 校验：active / inactive / deprecated
- [x] 5.3 mcp_remotes 字段加 sub-schema：array of {type, url}
- [x] 5.4 单元测试扩展：4 种 mcp 字段场景（全有 / 全无 / 部分缺 / 类型错）

## 6. CI workflow 改造

- [ ] 6.1 修改 `.github/workflows/sync.yml`：sync_mcp 之后插入 sync_mcp_registry step
- [ ] 6.2 修改 workflow：sync_rules 之后插入 sync_windsurfrules step
- [ ] 6.3 加 `.mcp_registry_cache/` 与 `.windsurfrules_cache/` 各自独立 weekly cache block（restore-keys 仅本周 stamp 不跨周回退）
- [ ] 6.4 添加错误兜底：两个 sync 任意失败时输出 ERROR 但 continue-on-error=true，不阻断 merge_index
- [ ] 6.5 sync_mcp_registry 与 sync_windsurfrules step 加 `timeout-minutes: 10` 防卡死

## 7. 覆盖率审计扩展

- [ ] 7.1 扩展 `scripts/popular_skills_expected.yaml`：增加 expected_mcp 与 expected_rules 两个分组，含 5-7 条经典 entry（如 `modelcontextprotocol/servers/fetch`、`React Cursor Rules` 等）
- [ ] 7.2 修改 `scripts/audit_popular_coverage.py`：支持 mcp / rules 类型审计（与 skill 类型并列）
- [ ] 7.3 报告输出 `docs/coverage_report.md` 加分组（Skills / MCP / Rules）

## 8. 增量评估保护

- [ ] 8.1 修改 `scripts/eval_bridge.py`：识别 mcp_registry / windsurfrules 派生 entry，复用 skills.sh 同款短路逻辑（diff stable + cache 命中）
- [ ] 8.2 验证 rubric_version 不变：跑现有测试集确认 mcp_server / rule 两个 task config 没改
- [ ] 8.3 单元测试：覆盖 mcp_registry stable 短路 + windsurfrules stable 短路

## 9. spike：cursor.directory

- [ ] 9.1 新建 `scripts/spike_cursor_directory.py`，探测候选路径：cursor.directory/api/* 各路径 / sitemap.xml / _next/data/ / 第三方 wrapper
- [ ] 9.2 复核 GitHub repo `pontusab/directories` 的 src/data 实际数据规模
- [ ] 9.3 输出 `docs/spike_cursor_directory.md` 报告：可行性评估 + 推荐下一步
- [ ] 9.4 spike 结果分支：发现可行路径 → 在本 change 追加接入；不可行 → 记 follow-up change `spike-cursor-directory-extended`

## 10. spike：windsurf.com/editor/directory

- [ ] 10.1 新建 `scripts/spike_windsurf_directory.py`，探测：_next/data 路径 / sitemap.xml / 网页源码中 __NEXT_DATA__ JSON / 第三方 wrapper
- [ ] 10.2 输出 `docs/spike_windsurf_directory.md` 报告
- [ ] 10.3 spike 结果分支：发现可行路径 → 追加接入；不可行 → 推荐"放弃官网，依赖 awesome-windsurfrules"

## 11. 测试覆盖与本地验证

- [ ] 11.1 全量测试 `python -m pytest tests/ ai-resource-eval/tests/ -v`，确保 0 回归
- [ ] 11.2 本地跑 `python scripts/sync_mcp_registry.py`，确认输出 5K-8K 条目
- [ ] 11.3 本地跑 `python scripts/sync_windsurfrules.py`，确认输出 100-300 条目
- [ ] 11.4 本地跑 `python scripts/merge_index.py`，确认去重正确、新字段写入 catalog/index.json
- [ ] 11.5 本地跑 `python scripts/audit_popular_coverage.py`，确认 mcp+rules 期望命中

## 12. 文档与提交

- [ ] 12.1 更新 `CLAUDE.md` "MCP 上游源" 与 "Skills 三层来源" 章节，新增两个源说明
- [ ] 12.2 更新 `CLAUDE.md` "评估引擎" 章节，新增 mcp_registry 字段
- [ ] 12.3 更新 `README.md` / `README.zh-CN.md` Sources 表格
- [ ] 12.4 删除或归档 1.3 的基线报告
- [ ] 12.5 提交 PR：标题 `[feat] 接入 MCP 官方 registry + awesome-windsurfrules（含 cursor/windsurf spike）`

## 13. 上线后观察

- [ ] 13.1 首次 CI 跑通后人工 review docs/coverage_report.md，确认 mcp+rules 期望命中
- [ ] 13.2 监控 mcp_registry API schema 与 status 字段稳定性
- [ ] 13.3 评估 catalog 体积膨胀对前端加载的影响（如必要触发后续优化 follow-up）
