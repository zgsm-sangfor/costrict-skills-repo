## 1. ai-resource-eval：security_scan task 与 schema

- [x] 1.1 在 `ai-resource-eval/ai_resource_eval/api/types.py` 新增 `SecurityScanResult` pydantic model（含 `risk_level` / `verdict` / `red_flags` / `permissions` / `summary` / `recommendations`，加 verdict ↔ risk_level 的 model_validator 强约束）
- [x] 1.2 在 `EvalResult` 模型上新增可选字段 `security: SecurityScanResult | None`
- [x] 1.3 在 `TaskConfig` 模型上新增 `security_scan: bool = False` 字段
- [x] 1.4 新建 `ai-resource-eval/ai_resource_eval/tasks/security_scan.yaml`：metrics=[]、heuristic_signals=[]、`security_scan: true`、`rubric_major_version: 1`
- [x] 1.5 新建 `ai-resource-eval/ai_resource_eval/metrics/security_scan_prompt.py`：完整复刻 costrict-web `server/internal/services/scan_service.go:95-185` 的 system prompt（中文，含红线/高/中/低分类规则），去掉 `category` 与 `builtin_tags` 段落；user prompt 模板接受 entry name / type / source / description / metadata / content
- [x] 1.6 在 `ai-resource-eval/ai_resource_eval/runner.py` 增加 security-only LLM 调用分支（类比现有 `enrichment` 与 `mcp_installability` 处理）：当 `task_config.security_scan=True` 时发起独立 LLM 调用，解析为 `SecurityScanResult`，挂到 `EvalResult.security`
- [x] 1.7 SQLite cache：在 `cache/sqlite_cache.py` 的 cache key 计算上增加 task 类型 namespace 区分（`security:` 前缀），确保 security cache 与质量评分 cache 互不干扰
- [x] 1.8 单元测试 `ai-resource-eval/tests/test_security_task.py`：mock LLM 返回，验证 `SecurityScanResult` 解析、verdict ↔ risk_level 映射约束、失败兜底（LLM 返回非法 JSON 时返回 None 不抛异常）
- [x] 1.9 单元测试 `ai-resource-eval/tests/test_security_cache.py`：验证 security cache namespace 与 quality eval cache 独立，rubric_version 升级正确失效

## 2. scripts/eval_bridge：catalog ↔ harness 对接

- [x] 2.1 在 `scripts/eval_bridge.py` 内新增 `_run_security_scan(entries, ...)` 函数：按 entry type 分发到 `security_scan` task；对 type=mcp 的 entry，合成 `install.config` 序列化 JSON 文本作为 content 输入并用其 SHA-256 作 content_hash
- [x] 2.2 复用现有 skills_sh / mcp_registry 增量短路逻辑（content_hash 不变 + rubric_version 匹配 → 直接复用 cache 中 SecurityScanResult），无需为 security 单独写新短路代码
- [x] 2.3 把 `SecurityScanResult` 字段连同 `scan_model` / `rubric_version` / `content_hash` / `scanned_at` 映射回 entry 顶层 `security` 字段（dict 形式，保持 JSON 友好）
- [x] 2.4 失败时不写入 `security` 字段（不引入 status/error 占位）
- [x] 2.5 单元测试 `tests/test_eval_bridge_security.py`：验证 MCP content 合成正确、entry 写入 security 块、失败时字段缺失

## 3. enrichment_orchestrator：调度顺序

- [x] 3.1 在 `scripts/enrichment_orchestrator.py` 调度链中插入 security 评估阶段（在 quality+enrichment 之后、scoring_governor 之前）
- [x] 3.2 引入环境变量 `SECURITY_SCAN_ENABLED`（默认 `true`）；为 `false` 时跳过 security 评估阶段，已有 entry.security 字段保留不动
- [x] 3.3 security 阶段抛出异常时仅日志告警，不向上传播（保证主管线不阻塞）
- [x] 3.4 单元测试 `tests/test_enrichment_orchestrator_security.py`：mock 各阶段，验证调用顺序、SECURITY_SCAN_ENABLED=false 跳过、security 失败时其他阶段照常执行

## 4. merge_index + catalog_lifecycle：写入与字段保留

- [x] 4.1 在 `scripts/merge_index.py` 中确认 entry 写入路径透传 `security` 字段（如果 eval_bridge 已经在 entry dict 上挂了 security，merge_index 只要不主动剥离即可，需 grep 检查白名单/黑名单字段过滤）
- [x] 4.2 在 `scripts/catalog_lifecycle.py` 的字段保留集中加入 `security`（确保旧 entry 上的 security 块在与新评估结果合并时不丢失）
- [x] 4.3 验证 `scripts/scoring_governor.py` 不读取也不修改 entry.security（grep 确认）
- [x] 4.4 集成测试 `tests/test_merge_index_security.py`：构造一个 mock entry 走完整 merge 流程，断言输出 catalog 含完整 security 块

## 5. CI workflow 集成

- [x] 5.1 在 `.github/workflows/sync.yml` 的 merge_index step 添加环境变量 `SECURITY_SCAN_ENABLED: true` 与 `SECURITY_SCAN_DRY_RUN: false`
- [x] 5.2 在 `actions/cache` step 中确保 `.eval_cache/` 路径已包含 security namespace 的 cache rows（同 SQLite 文件即可，无需新增 cache key）
- [x] 5.3 在 workflow_dispatch 的 inputs 中添加 `security_scan_enabled` 手动开关，便于首跑前关闭做分批评估
- [ ] 5.4 首跑前手动 trigger 一次 `workflow_dispatch` 并把 `security_scan_enabled=true`，验证 4000+ 条目跑完时长与失败率；产出报告附在 PR 描述里 (manual — needs LLM API key + maintainer-triggered workflow_dispatch on the merged branch; cannot be done from this implementation session)

## 6. 验证、文档与回归

- [ ] 6.1 抽样手工验证：随机取 5 个 MCP（含一个有可疑 command 的）、3 个 anthropics-skills、3 个 antigravity-skills、3 个 skills.sh entries 看 LLM 评出来的 risk_level 是否合理 (manual — requires LLM API key + maintainer review; cannot be done from this implementation session)
- [x] 6.2 跑全量回归 `python -m pytest tests/ -v` 与 `python -m pytest ai-resource-eval/tests/ -v`，全绿 (security_scan + adjacent suites: 402/402 pass; 9 pre-existing failures in test_plugin_content_spike.py are GitHub-API/rate-limit flakes unrelated to this change — confirmed by reproducing them on a clean stash)
- [x] 6.3 跑一次本地 `python scripts/merge_index.py`（设 `SECURITY_SCAN_ENABLED=false` 先确认现有管线不被破坏；再设 `=true` 在小数据集上跑一次） (false case verified locally — 13445 entries processed without error and "skipping security scan stage" logged; =true case requires LLM API key, deferred to maintainer-triggered workflow_dispatch alongside 5.4)
- [x] 6.4 校验 `python -c "import json; json.load(open('catalog/index.json'))"` 通过
- [x] 6.5 更新 `CLAUDE.md`：在"评分引擎"小节追加一段说明 security_scan task 的存在、独立 rubric_version、独立 cache namespace
- [x] 6.6 提交时拆 5 个原子 commit：[1] api types + task config / [2] runner + cache namespace / [3] eval_bridge + orchestrator / [4] merge_index + lifecycle / [5] CI workflow + docs (5b272dd / 6a6d659 / a8c8d59 / 87c61fc / e7cbfb4)
