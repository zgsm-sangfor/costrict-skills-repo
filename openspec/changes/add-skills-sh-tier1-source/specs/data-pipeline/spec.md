## ADDED Requirements

### Requirement: Sync pipeline SHALL include sync_skills_sh.py step

CI 流水线（`.github/workflows/sync.yml`）SHALL 在 `sync_skills` 之后、`merge_index` 之前调用 `python scripts/sync_skills_sh.py`，将 skills.sh 数据写入 `catalog/skills/skills_sh_index.json`。

#### Scenario: 流水线顺序正确
- **WHEN** weekly sync workflow 触发
- **THEN** 步骤顺序 SHALL 为：crawl_mcp_so → sync_mcp → sync_rules → sync_skills → **sync_skills_sh** → sync_prompts → verify_sync → merge_index → update_readme → audit_popular_coverage

#### Scenario: sync_skills_sh 失败不阻断后续
- **WHEN** sync_skills_sh.py 因网络或上游问题失败
- **THEN** workflow SHALL 输出 ERROR 但不阻断 merge_index（merge 时若 skills_sh_index.json 不存在则跳过该源）

### Requirement: CI cache SHALL include skills.sh snapshot directory

`.github/workflows/sync.yml` 的 `actions/cache` 配置 SHALL 把 `.skills_sh_cache/` 加入缓存路径列表，缓存键 SHALL 包含每周时间戳以便周期性失效。

#### Scenario: 缓存命中
- **WHEN** 同一周内重复触发 workflow，且缓存键匹配
- **THEN** `.skills_sh_cache/` SHALL 从缓存恢复，sync_skills_sh.py 通过 ETag 复用上次拉取结果

#### Scenario: 缓存键失效
- **WHEN** 进入新的一周，缓存键变更
- **THEN** `.skills_sh_cache/` SHALL 重新建立，sync_skills_sh.py 实际拉取 mastra JSON

### Requirement: merge_index SHALL deduplicate by source_url with priority order

`scripts/merge_index.py` SHALL 在去重阶段实现基于 `source_url` 的优先级合并，同一 source_url 多源命中时按以下优先级保留：官方直接源 > skills.sh > antigravity 镜像 > 其他社区源。

#### Scenario: 同一 skill 在 anthropics/skills 与 skills.sh 都存在
- **WHEN** 两源均收录同一 source_url
- **THEN** 系统 SHALL 保留 anthropics/skills 的 entry id 与基础字段，但合并 skills.sh 提供的 `install_count`、`skills_sh_url`、`skills_sh_scraped_at`

#### Scenario: 同一 skill 在 antigravity 镜像与 skills.sh 都存在
- **WHEN** antigravity 镜像收录的 source_url（如 `github.com/sickn33/antigravity-awesome-skills/tree/main/skills/X`）与 skills.sh 收录的官方 source_url（如 `github.com/obra/superpowers/tree/main/skills/X`）指向同一 skill 内容
- **THEN** 系统 SHALL 优先保留 skills.sh 提供的官方 source_url，并把 antigravity entry 标记为重复条目移除

#### Scenario: source_url 完全唯一
- **WHEN** 一个 skill 仅在单一源中存在
- **THEN** 系统 SHALL 直接保留该 entry，无优先级判定开销

### Requirement: Sync pipeline SHALL incrementally evaluate only changed entries

LLM 评估管线 SHALL 仅评估新增或 install_count 显著变化（±20%）的 skills.sh entry，复用 `.eval_cache/` SQLite 缓存避免重复评估。

#### Scenario: 完全相同条目复用缓存
- **WHEN** 一条 entry 与上次 sync 时的 content_hash 一致，且 install_count 变化在 ±20% 以内
- **THEN** 系统 SHALL 从 `.eval_cache/` 读取既有评估结果，不调用 LLM

#### Scenario: install_count 大幅波动触发重评估
- **WHEN** 一条 entry 的 install_count 较上次记录变化 > ±20%
- **THEN** 系统 SHALL 标记 cache miss，触发 LLM 重新评估并更新缓存

#### Scenario: 全新 entry 进入评估
- **WHEN** 一条 entry 的 source_url 在 catalog 中首次出现
- **THEN** 系统 SHALL 调用 LLM 评估，评估结果写入 `.eval_cache/`
