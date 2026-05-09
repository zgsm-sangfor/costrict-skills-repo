# enrichment_mock fixtures

本目录是 per-type 评估管线的 **mock 输入** fixtures，专为 sync-test workflow 与
`scripts/run_enrichment.py --mock-mode` 提供轻量、可重现、可脱敏的样本数据。

## 用途

- `run_enrichment.py --mock-mode --type <t>` 读取 `<t>.json` 跑短路 / 真 LLM / 失败台账三条路径
- sync-test workflow（Chunk 3B）在 PR 流程里用这批 fixture 做端到端冒烟，避免拉真实 13k 条目

## 选样标准

每个 type 共 **6 条**：

- **5 条真实条目**：从 `catalog/index.json` 按 `stars desc, id asc` 稳定排序后取头部
  - 必须满足：`type` 匹配、`description` 非空、`source_url` 非空
  - 高 star 条目通常 README 完整，下次评估应短路命中 cache；中等条目走真 LLM
- **1 条合成条目**（`id = "mock-empty-desc-<type>"`）：`description = ""` 强制走失败台账写入路径
  - 用于验证 ledger（eval_failure_log）落盘正确

## 脱敏字段（必须删除）

下列字段属于评估历史 / 评分侧道 / LLM 派生 / 敏感联系方式，sample 脚本一律剔除：

- `evaluation`, `_prior_evaluation`
- `health`, `final_score`, `decision`, `freshness_label`, `weak_dims`
- `description_zh`, `description_original`
- `search_terms`, `highlights`
- `mcp_install_state`, `mcp_validation_tags`, `mcp_schema_valid`, `mcp_installability_reason`

> 注：`manifest_completeness` 看似 LLM 输出，实际由 `sync_plugins_official.py`
> 在数据层算出（plugin 任务配置把它作为 10% 健康信号消费），属于 upstream
> 字段，**保留**。
- `author_email`, `email`, `contact_email`（防御性，即使上游目前无此字段）

## 保留字段（白名单）

只保留 upstream / data-layer 字段，确保 mock 是"输入"而非"期望输出"：

`id`, `name`, `type`, `description`, `source_url`, `stars`, `category`, `tags`,
`tech_stack`, `source`, `source_priority`, `platforms`, `version`,
`marketplace_url`, `skills_sh_url`, `skills_sh_scraped_at`, `install_count`,
`pushed_at`, `added_at`, `last_synced`, `install`, `bundle`, `bundled_in`,
`manifest_completeness`

不在白名单的字段一律丢弃，避免遗漏新增的评估 side-channel。

## 刷新方式

```bash
python3 scripts/_sample_mock_fixtures.py
# 可选参数
python3 scripts/_sample_mock_fixtures.py \
  --catalog catalog/index.json \
  --output-dir tests/fixtures/enrichment_mock \
  --per-type 5
```

由于排序稳定（`stars desc, id asc`），同一份 catalog 跑两次会产出**完全一致**的输出。

### 何时需要刷新

- catalog schema 变化（新增 / 重命名字段，或新增评估侧道字段需要加入脱敏列表）
- 评估管线引入新 type（更新 `TYPES` 常量）
- 头部高 star 条目大规模变动（一般无需主动刷新，fixture 是固化的测试输入）

## 注意事项

- **不要 commit 真实评估输出到这里**：fixtures 是 mock 的「输入」，evaluation/health/decision 等字段须为空，由测试 run 自己产出再校验
- 单文件目标 ≤ 30 KB；plugin 类型因 `bundle` 数组较大可能接近上限，刷新时留意
- `tests/` 目录在仓库 `.gitignore` 内，提交本目录文件需用 `git add -f`
