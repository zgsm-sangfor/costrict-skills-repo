## Context

merge_index step 是 weekly sync 的最长链路：load → dedup → bundled_in 标注 → **enrichment（LLM 评估，慢点）** → governance → lifecycle。整个链路单 step 跑，无 timeout，吃满 GitHub-hosted runner 6h 上限即被强制终止。

CI run 25541124221 实测：merge_index step 唯一可见日志在前 4 秒打完（载入 + dedup + 10k+ 行 orphan namespace warning），之后 5h59m56s 完全静默 → 6h cap 触发 kill。日志文件根本没产出，连"卡在哪条 entry"都不可知。

V3 rubric 升级让 cache 大量失效，本次大跑工作量天然超 6h。用户已确认：**数据规模不缩**、**mcp 不分片**、**concurrency 可在测试 CI 适度调高**。

## Goals / Non-Goals

**Goals:**

- 把"6h timeout = 全部丢弃"改成"分 type 跑 + 续跑 = 多周接力可完成"
- 单 cell 中途被 kill 时，已完成的 50 条粒度进度不丢失
- 反复失败的 entry 自动 quarantine，不再周复一周浪费 LLM 调用
- 给 enrichment 管线一条**测试 CI**：用 mock 数据本地验证 + 适度提高并发实验，避免改完直接打主 cron 翻车
- 主 workflow 单 cell 失败时，其他 type 数据照样发布，不再"一卡卡全"

**Non-Goals:**

- **不**重写 ai-resource-eval 包内部（runner / cache / judge），所有改动包在 `scripts/eval_bridge.py` 外层
- **不**分片 mcp（用户判定为过度设计）
- **不**降低数据规模 / 不加 star 阈值过滤
- **不**改 rubric_version（V3 已上线）
- **不**做 self-hosted runner（GitHub-hosted matrix + checkpoint 已能解决）
- **不**做 LLM provider 切换（保持 MiMo，只在测试 CI 实验高并发）

## Decisions

### D1：失败台账 schema 与退避算法

```jsonc
// catalog/maintenance/eval_failures.json
{
  "schema_version": 1,
  "rubric_version": 3,                 // 升 rubric 时清空台账重置计数
  "updated_at": "2026-05-09T03:00:00Z",
  "failures": {
    "<entry_id>": {
      "type": "mcp",
      "first_failed_at": "2026-05-09T03:14:00Z",
      "last_failed_at": "2026-05-23T03:14:00Z",
      "attempt_count": 3,
      "last_error_kind": "ReadTimeout",
      "last_error_message": "httpx.ReadTimeout: …",
      "next_retry_after": "2026-06-06T03:14:00Z"
    }
  }
}
```

退避：
- attempt_count = 1 → 立即下次重试（next_retry_after = now）
- attempt_count = 2 → 1 周后（now + 7d）
- attempt_count = 3 → 4 周后（now + 28d）
- attempt_count >= 4 → quarantine：next_retry_after = `9999-12-31`，evaluation 走 health-only 兜底

`rubric_version` 字段对齐当前 task 的 rubric_version。Rubric 升级后整个台账重置（理由：rubric 不一样了，旧失败原因可能不再成立）。

**为什么 dict 而不是 list**：按 entry_id 索引，O(1) 查询；序列化成 JSON 仍可读且 stable。

### D2：Checkpoint 落盘机制

```jsonc
// catalog/maintenance/checkpoints/<type>.json
{
  "type": "mcp",
  "rubric_version": 3,
  "started_at": "2026-05-09T03:00:00Z",
  "last_committed_at": "2026-05-09T05:30:00Z",
  "completed_count": 6420,
  "completed_entry_ids": [...],   // 已完成 LLM 评估，cache 已写入
  "remaining_entry_ids": [...]    // 启动时填充，每完成 50 条 pop
}
```

写盘原子性：
- 写到 `<type>.json.tmp`
- `os.fsync(fd)` 保证落盘
- `os.replace(tmp, final)` 原子替换

读盘启动逻辑：
- rubric_version 不匹配 → 丢弃 checkpoint，从头跑
- rubric_version 匹配 → 跳过 `completed_entry_ids` 中已确认的，从 `remaining_entry_ids` 续跑
- 已 quarantine 的 entry 直接跳过（在台账里标记）

### D3：Per-type matrix workflow 形状

```yaml
# .github/workflows/sync.yml （Phase 2 后）

jobs:
  sync-data:
    timeout-minutes: 90
    steps:
      - ... (现 22 个 sync step) ...
      - run: python -u scripts/merge_index.py --skip-enrichment
      - uses: actions/upload-artifact@v4
        with:
          name: catalog-data-only
          path: catalog/

  enrich:
    needs: sync-data
    strategy:
      matrix:
        type: [mcp, skill, rule, prompt, plugin]
      fail-fast: false           # 单 type 失败不杀其他
    timeout-minutes: 350         # 5h50m；脚本预算更短，给 artifact upload 留时间
    steps:
      - uses: actions/download-artifact@v4
        with: { name: catalog-data-only }
      - env:
          PYTHONUNBUFFERED: "1"
          EVAL_CONCURRENCY: ${{ vars.EVAL_CONCURRENCY || '6' }}
        timeout-minutes: 335
        run: |
          python -u scripts/run_enrichment.py \
            --type ${{ matrix.type }} \
            --max-wall-seconds 19800
      - uses: actions/upload-artifact@v4
        if: always()              # 即使 run 失败仍上传 partial
        with:
          name: enrichment-${{ matrix.type }}
          path: |
            tests/_enrich_output/${{ matrix.type }}.json
            catalog/maintenance/checkpoints/${{ matrix.type }}.json
            catalog/maintenance/eval_failures.json

  aggregate:
    needs: enrich
    if: always()                  # 即使部分 enrich cell 失败仍跑
    timeout-minutes: 30
    steps:
      - uses: actions/download-artifact@v4
        with: { pattern: "enrichment-*" }
      - run: python -u scripts/aggregate_enrichment.py
      - run: python scripts/update_readme.py
      - run: git commit -am "..." && git push
```

**为什么 matrix.type 而非动态计算**：固定 5 个值，简单稳定，未来加 type 时改 yml 一行即可。dynamic matrix 需要 sync-data 输出 JSON job output，复杂度不值。

### D4：Aggregate 兜底逻辑

```python
# scripts/aggregate_enrichment.py 主流程

# 1. 读 catalog-data-only artifact 的 catalog/index.json（数据层完整、evaluation 空）
# 2. 读各 enrichment-<type> artifact 的结果
# 3. 按 entry_id 把 evaluation 字段写回 catalog/index.json 对应 entry
# 4. 对没有新 evaluation 的 entry（cell 失败 / 超时 / 类型整个 cell 失败）：
#    a. 读旧 catalog/index.json（git HEAD）的对应 entry → 复用旧 evaluation
#    b. 旧值不存在 → evaluation = {"final_score": health_only_score, "decision": "review"}
#    c. 在 step summary 标注"用旧值兜底的 entry 数"
# 5. 写最终 catalog/index.json
# 6. 输出 markdown summary
```

**关键不变量**：aggregate 跑完后 `catalog/index.json` 一定有完整 entry 列表 + 每条都有 evaluation 字段。前端永远不会看到"半成品 catalog"。

### D5：测试 workflow + mock fixture

```yaml
# .github/workflows/sync-test.yml （新建，仅 workflow_dispatch 触发）

on:
  workflow_dispatch:
    inputs:
      eval_concurrency:
        description: '测试并发度 (默认 12，可调到 16-20 实验)'
        default: '12'

jobs:
  test-enrichment:
    timeout-minutes: 30
    strategy:
      matrix:
        type: [mcp, skill, rule, prompt, plugin]
      fail-fast: false
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
      - run: pip install -e ai-resource-eval
      - env:
          PYTHONUNBUFFERED: "1"
          MOCK_FIXTURE_DIR: tests/fixtures/enrichment_mock
          EVAL_CONCURRENCY: ${{ inputs.eval_concurrency }}
          LLM_BASE_URL: ${{ secrets.LLM_BASE_URL }}
          LLM_API_KEY: ${{ secrets.LLM_API_KEY }}
          LLM_MODEL: ${{ secrets.LLM_MODEL }}
        run: |
          python -u scripts/run_enrichment.py \
            --type ${{ matrix.type }} \
            --mock-mode \
            --output tests/_test_output/${{ matrix.type }}.json
      - run: |
          python scripts/eval_failure_log.py --inspect \
            > $GITHUB_STEP_SUMMARY
```

**Mock fixture 选材**：每 type 选 5-10 条
- 必须包含至少 1 个 cache hit（rubric_version=3 已 cached）→ 验证短路
- 必须包含至少 2 条没 cache → 验证真 LLM 调用
- 必须包含至少 1 条故意构造会失败的（如 description=""）→ 验证台账写入
- 不放敏感数据（API key、内部 URL 等）

**为什么 mock 不接 mock LLM**：直接打真 LLM provider，因为我们要验证的是**并发提到 12-20 时是否稳定**——这只能用真 provider 才有意义。

### D6：进度可见性

- 每 cell 启动时 print：`[type=mcp] starting: 9100 total, 6420 already cached, 12 quarantined, 2668 to evaluate`
- 评估循环每 50 条 print + flush：`[type=mcp] progress: 1850/2668 (69%) succeeded=1820 failed=30 elapsed=43min`
- cell 结束时 print：`[type=mcp] done: succeeded=2640 failed=18 quarantined=10 wall_clock=2h11m`
- cell 主动到达时间预算时 print：`[type=mcp] budget reached: checkpoint saved, partial artifact written, remaining=3100`
- aggregate step 输出 GitHub Actions step summary（markdown table），见 D4

### D7：脚本级时间预算

`run_enrichment.py` 必须支持 `--max-wall-seconds`。该预算是脚本自己的软截止时间，必须小于 GitHub Actions step / job timeout，用来避免 runner 被硬杀时 checkpoint 只留在本地临时盘。

运行时每完成一条 entry 后检查剩余预算；当剩余时间不足以安全启动下一条 LLM 评估时，脚本必须：

1. 立即写入当前 checkpoint（不等待 50 条边界）
2. 写入当前 partial artifact
3. 写入 failure ledger
4. 输出 budget reached 日志并以成功状态退出

workflow 必须给 `upload-artifact` 留出时间：`run_enrichment.py` step 的 timeout 小于 enrich job timeout，脚本预算又小于 step timeout。这样即使 MCP 无法在一次 run 内完成，已完成结果也会随 artifact 进入 aggregate，checkpoint / failure ledger 会被下一次 workflow 使用。

### D8：本次大跑的过渡策略

**第一次跑**（V3 失效，工作量超 6h）：
1. sync-data 完成 → 数据层 catalog 落盘
2. 5 个 enrich cell 并行启动；mcp cell 大概率先触发 `--max-wall-seconds` 软截止
3. mcp cell 主动写 checkpoint + partial artifact + failure ledger 后退出（含已完成 ~6000 条）
4. aggregate 跑：mcp 用部分新结果 + 旧值兜底（约 1/3 的 mcp entry 用旧值）
5. publish 写 catalog → 推送

**第二次跑**（一周后）：
- mcp cell 续跑剩余 ~3000 条 → 大概率能在 5h 内跑完
- 其他 type 已 100% cached（除 quarantine） → 几分钟跑完
- aggregate 写最终 catalog

**第三次跑**（增量稳态）：每周新增 / 变更几十条，每 cell 几分钟跑完。

## Risks / Trade-offs

| Risk | Mitigation |
|------|-----------|
| Checkpoint 文件损坏（写盘中断） | tmp + fsync + atomic rename；启动时 schema 校验失败则丢弃从头跑 |
| 失败台账被 git 跟踪后随每周提交膨胀 | 单文件，size_cap：>5MB 时 prune 已 quarantine 超 90 天的条目 |
| Aggregate 用旧 evaluation 兜底导致部分 entry 永远不更新 | 兜底只是过渡；正常情况 cell 跑完会覆盖；连续 4 次 cell 失败的会在台账里 quarantine 显形 |
| Matrix `fail-fast: false` 但某 cell 真 fatal 错误（非超时） | aggregate 用旧值兜底 + step summary 标红；不阻塞其他 type 发布 |
| 测试 CI 用真 LLM 烧 quota | mock fixture 控制在 50 条以内（5 type × 10 条），单次 dispatch < 200 LLM 调用 |
| 提到 concurrency=16 重新触发 429 | 测试 CI 收集到 429/ReadTimeout 比例后再决定主 workflow 是否同步上调；不调成功则保持 6 |
| Aggregate 把空 evaluation 错误覆盖好 evaluation | aggregate 严格规则：partial artifact 中 entry_id 存在但 evaluation 为空 → 视为 cell 失败该条，走兜底而非覆盖 |
| Plugin bundle extraction 改动让 plugin 全量重评（~900 条） | 本 change 后 plugin 走自己的 cell，不阻塞其他 type；1 个 cell 内最多 ~38 min（按 D5 估算） |

## Migration Plan

**Phase 1**（独立 ship，不改 workflow）：
1. 实现失败台账（`scripts/eval_failure_log.py`）+ 单元测试
2. 实现 EvalRunner 包装层 checkpoint 写盘 + 单元测试
3. 改 `eval_bridge.py` 集成台账与 checkpoint
4. 主 workflow 行为不变，但下次单 step 6h 内任何阶段被 kill 都能续跑

**Phase 2**（依赖 Phase 1，跟 Phase 3 一起 ship）：
1. 实现 `--skip-enrichment` flag（merge_index）
2. 新建 `scripts/run_enrichment.py`
3. 新建 `scripts/aggregate_enrichment.py`
4. 单元测试：缺失 type 兜底、partial artifact 合并

**Phase 3**（依赖 Phase 1，跟 Phase 2 一起 ship）：
1. 准备 mock fixture（每 type 5-10 条，从生产 catalog 选样脱敏）
2. 新建 `.github/workflows/sync-test.yml`
3. **手动 dispatch sync-test workflow 验证全链路通过**
4. 收集 sync-test 的 concurrency=12/16/20 实测数据，确定主 workflow concurrency 是否上调
5. **测试通过后再改主 `.github/workflows/sync.yml`**——matrix 拆分

**回滚策略**：
- Phase 1 单独 ship 后回滚成本低（删 maintenance 文件 + revert 一个 commit）
- Phase 2/3 ship 后如果发现 aggregate 兜底逻辑有 bug，可临时把 sync.yml 改回单 step `python merge_index.py`（不带 --skip-enrichment）走老路

## Open Questions

- **OQ1**：rubric_version 升级时台账自动重置——是只重置该 task 涉及的 type，还是整个台账？建议整个台账（简单，一年 1-2 次升级，重置成本低）
- **OQ2**：测试 fixture 是否要包含跨 type 关联（如某 plugin entry bundling 了某 skill）？倾向**不**，每 type 独立 mock 即可；跨 type 行为有专门的 dedup / bundled_in 测试覆盖
- **OQ3**：aggregate 用旧 evaluation 兜底时，`evaluation.evaluated_at` 是否更新？倾向**不**——保留旧时间戳，让 lifecycle 知道这是历史值，未来可基于此识别"长期未刷新"的 entry
- **OQ4**：测试 workflow 跑出更高并发的 ReadTimeout 比例后，主 workflow 何时上调？建议建议门槛"测试 CI 200 条调用 ReadTimeout 比例 < 2%"才上调到 12，否则保持 6

  **结论（2026-05-09 sync-test 实测后）**：保持 `EVAL_CONCURRENCY=6` 默认，**不**上调。

  实测数据（run 25591474158，concurrency=16，345 LLM 调用，5 cell × 80 entries 真实负载）：

  | cell | succeeded | failed | 成功率 | wall_clock |
  |------|-----------|--------|-------|-----------|
  | mcp  | 18 | 63 | **22%** | 78s |
  | rule | 23 | 58 | **28%** | 77s |
  | skill | 47 | 34 | 58% | 128s |
  | prompt | 51 | 30 | 63% | 781s（异常长） |
  | plugin | 19 | 2 | 90% | 56s |

  - 失败模式全部是 `EvalRunnerSkip`（runner 在 `on_fail="skip"` 下吞掉的 fetch / rate-limit / timeout），共 187 条入台账等下周接力。
  - 5 cell × 16 worker = 80 瞬时并发抢 LLM provider 100 RPM 配额 + GitHub raw content fetch，短调用 type（mcp/rule）撞 RPM 最严重。
  - prompt cell wall_clock 781s 远超其他（疑似 httpx 内部 retry 风暴），需要单独深挖才能上调。
  - plugin 反而最稳（90%）：单条 LLM 调用 ~16s，瞬时 RPS 低不抢 RPM。

  **生产规模含义**：mcp 9100 条 / skill 1795 条规模下，concurrency=16 会让单周 22-58% 条目失败入台账接力，多周才能完成。这违背"主 workflow 优先单周完成度 + 6h 配额"的目标。

  门槛重设：未来 LLM provider 流控放宽（≥ 200 RPM）或 prompt 异常 wall_clock 根因解决后再重测。本次主 workflow 切换（Phase 4）保持 `EVAL_CONCURRENCY=6`。
