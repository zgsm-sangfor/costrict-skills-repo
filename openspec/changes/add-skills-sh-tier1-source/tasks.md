## 1. 探针与基线

- [x] 1.1 本地拉取 mastra JSON 一次（`curl -sLo /tmp/mastra.json`），统计 `install_count ≥ 1000` 条目数与字段分布，校准阈值预期
- [x] 1.2 本地脚本 dump：与现有 catalog 比对，估算与 antigravity 镜像、anthropics/skills 的重叠数量
- [x] 1.3 输出基线报告（写到 `docs/skills_sh_baseline.md`，本任务后续删除或归档），含：进库条目数、与既有源重叠数、Top 10 install_count 列表

## 2. 核心 sync_skills_sh.py

- [x] 2.1 新建 `scripts/sync_skills_sh.py`，仅用 Python 标准库（urllib、json、os、hashlib、datetime）
- [x] 2.2 实现 `fetch_mastra_snapshot()`：GET raw.githubusercontent.com，支持 `If-None-Match` ETag header，缓存到 `.skills_sh_cache/mastra.json` + `.skills_sh_cache/etag.txt`
- [x] 2.3 实现 `fetch_skills_sh_paginated()`：分页调用 `https://skills.sh/api/skills/all-time?page=N` 直到 `hasMore=false`，作为降级路径
- [x] 2.4 实现 `should_use_fallback(snapshot)`：检查 `scrapedAt` 字段距今是否 > 7 天
- [x] 2.5 实现 `normalize_entry(raw)`：将 mastra/skills.sh entry 转换为 catalog skill schema，生成稳定 id（如 `<skillId>-<owner>`）
- [x] 2.6 实现 install_count 阈值过滤，环境变量 `SKILLS_SH_MIN_INSTALLS` 默认 1000
- [x] 2.7 输出 `catalog/skills/skills_sh_index.json`，结构与现有 `{antigravity,vasilyu}_index.json` 一致
- [x] 2.8 增量 diff：与上次输出对比，记录新增 / install_count 显著变化（±20%）/ 移除条目到 `.skills_sh_cache/diff.json`，供 merge_index 决定哪些进 LLM 评估

## 3. merge_index.py 改造

- [x] 3.1 在 `scripts/utils.py` 新增 `source_priority(source_url) -> int` 函数，根据 host 与路径判定优先级（直接源 > skills.sh > antigravity > 其他）
- [x] 3.2 修改 `merge_index.py` 的去重逻辑：同 source_url 多源命中时按优先级保留最高，但合并 `install_count` / `skills_sh_url` / `skills_sh_scraped_at` 字段
- [x] 3.3 处理"镜像 source_url 与官方 source_url 指向同一 skill"的情况：当 skills.sh 提供 githubUrl，antigravity 镜像基于内容 hash 或 skill 名匹配为同一 skill，移除镜像 entry，保留官方
- [x] 3.4 单元测试：构造 5 种去重场景（仅 skills.sh / 仅镜像 / 双源 / 三源 / source_url 完全不同）

## 4. catalog schema 增量字段

- [x] 4.1 更新 catalog skill entry 的 schema 定义文件（若存在 `schemas/skill.json` 或类似），新增三个 optional 字段
- [x] 4.2 修改 `scripts/utils.py` 的 schema 校验逻辑（若有），允许 `install_count`/`skills_sh_url`/`skills_sh_scraped_at` 缺失但若存在则类型严格
- [x] 4.3 单元测试：覆盖字段全有 / 全无 / 部分缺失 / 类型错误 4 种场景

## 5. 评分管线接入

- [x] 5.1 修改 `enrichment_orchestrator.py` 或 `eval_bridge.py`：health.signals 输出新增 `install_popularity` 字段
- [x] 5.2 实现 `compute_install_popularity(install_count) -> 0..100`：使用 `min(100, log10(max(install_count,1)) / log10(100000) * 100)` 公式
- [x] 5.3 在权重表中添加 `install_popularity` 默认权重 0；支持 `HEALTH_W_INSTALL_POPULARITY` 环境变量覆盖
- [x] 5.4 验证 final_score 不变：跑一遍现有测试集，install_popularity 信号不影响默认评分

## 6. 增量评估管线

- [ ] 6.1 在 `eval_bridge.py` 中增量逻辑里加判断：若 entry 来自 skills_sh 且 install_count 变化 ≤ ±20% 且 content_hash 不变，跳过 LLM 评估直接复用 cache
- [ ] 6.2 把 `.skills_sh_cache/diff.json` 作为 `eval_bridge.py` 的可选输入，加速判断
- [ ] 6.3 验证：本地 dry-run 两次 sync，第二次 LLM 调用数应远小于第一次

## 7. CI workflow 改造

- [ ] 7.1 修改 `.github/workflows/sync.yml`：在 `sync_skills` 之后、`merge_index` 之前插入 `sync_skills_sh` 步骤
- [ ] 7.2 把 `.skills_sh_cache/` 加入 `actions/cache` 路径列表
- [ ] 7.3 缓存 key 加入每周时间戳（如 `skills-sh-${{ github.run_id }}-${{ steps.week.outputs.week }}`）以便周期性失效
- [ ] 7.4 添加错误兜底：sync_skills_sh 失败时输出 ERROR 但不阻断后续 step（继续 merge_index）
- [ ] 7.5 在 `update_readme` 之后插入 `audit_popular_coverage` 步骤

## 8. 覆盖率审计脚本

- [ ] 8.1 新建 `scripts/popular_skills_expected.yaml`，初版含 7 条期望（obra/superpowers、vercel-labs/agent-skills、vercel-labs/agent-browser、supermemoryai/supermemory、Leonxlnx/taste、Dammyjay93/interface-design、anthropics/skills）
- [ ] 8.2 新建 `scripts/audit_popular_coverage.py`：加载期望清单，对照 catalog/index.json 检查每条 source_url 的命中状态与来源类型
- [ ] 8.3 输出 markdown 报告到 `docs/coverage_report.md`，含状态表（`✅ 直接源` / `⚠️ 仅镜像` / `❌ 未收录`）、install_count、按状态分组统计
- [ ] 8.4 增量 commit 逻辑：报告内容未变化时跳过 commit，避免空提交
- [ ] 8.5 单元测试：构造 catalog fixture，验证 3 种命中状态判定正确

## 9. 测试覆盖

- [ ] 9.1 新建 `tests/test_sync_skills_sh.py`：覆盖正常拉取 / ETag 命中 / scrapedAt 陈旧降级 / 双路径都失败 / 阈值过滤 / id 唯一性
- [ ] 9.2 新建 `tests/test_popular_coverage_audit.py`：覆盖期望清单 YAML 解析 / 状态判定 / install_count 显示 / 空 commit 跳过
- [ ] 9.3 扩展 `tests/test_merge_index.py`：补充 source_priority 与去重合并的 5 种场景
- [ ] 9.4 扩展 `tests/test_scoring_governor.py`：验证 install_popularity 信号默认权重 0 不影响 final_score
- [ ] 9.5 全部测试通过：`python -m pytest tests/ -v`

## 10. 本地验证与 dry-run

- [ ] 10.1 本地跑 `python scripts/sync_skills_sh.py`，确认输出 `catalog/skills/skills_sh_index.json` 条目数符合预期（200-500 条）
- [ ] 10.2 本地跑 `python scripts/merge_index.py`，确认去重正确、新字段写入 `catalog/index.json`
- [ ] 10.3 本地跑 `python scripts/audit_popular_coverage.py`，确认报告生成且 7 条期望命中
- [ ] 10.4 本地跑 `EVAL_DRY_RUN=true python -m ai_resource_eval ...` 一次完整评估，记录 LLM 调用数与缓存命中率
- [ ] 10.5 第二次跑 sync 验证增量：LLM 调用数应大幅下降（<20% 首次量）

## 11. 文档与提交

- [ ] 11.1 更新 `CLAUDE.md` 中的"Skills 三层来源与去重"章节，新增 skills.sh 作为 Tier 1 源说明
- [ ] 11.2 更新 `CLAUDE.md` 的"评估引擎"章节，新增 `install_popularity` 信号与 `HEALTH_W_INSTALL_POPULARITY` 环境变量
- [ ] 11.3 更新 `README.md` / `README.zh-CN.md` 的 sync 命令说明，加入 `sync_skills_sh.py`
- [ ] 11.4 删除或归档 1.3 的基线报告 `docs/skills_sh_baseline.md`
- [ ] 11.5 提交 PR：标题 `[feat] 接入 skills.sh 作为 Tier 1 上游源（含覆盖率审计）`，描述含 baseline 数据 + 新增字段 + CI 增量策略说明

## 12. 上线后观察

- [ ] 12.1 首次 CI 跑通后人工 review `docs/coverage_report.md`，确认期望清单全部命中
- [ ] 12.2 观察一周内 `.eval_cache/` 命中率，验证增量评估生效
- [ ] 12.3 监控 mastra JSON 的 `scrapedAt` 字段更新频率，决定是否调整 7 天降级阈值
