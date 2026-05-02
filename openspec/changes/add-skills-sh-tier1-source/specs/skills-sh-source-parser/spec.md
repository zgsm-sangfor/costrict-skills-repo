## ADDED Requirements

### Requirement: skills.sh source parser SHALL fetch via dual-path strategy

系统 SHALL 通过两条路径获取 skills.sh 数据：主路径拉取 `mastra-ai/skills-api` 仓库的 `src/registry/scraped-skills.json`；当主路径数据陈旧时降级到 skills.sh 隐藏 API。

#### Scenario: 主路径成功且数据新鲜
- **WHEN** sync_skills_sh.py 启动并成功 GET 到 mastra JSON，且 `scrapedAt` 距今 ≤ 7 天
- **THEN** 系统 SHALL 使用 mastra JSON 作为数据源，不调用 skills.sh API

#### Scenario: 主路径数据陈旧触发降级
- **WHEN** mastra JSON 的 `scrapedAt` 距今 > 7 天
- **THEN** 系统 SHALL 输出 WARNING 日志，并改为分页调用 `https://skills.sh/api/skills/all-time?page=N` 直到 `hasMore=false`，将合并结果作为本次数据源

#### Scenario: 主路径 HTTP 失败
- **WHEN** 拉取 mastra JSON 返回非 200 状态码或网络超时
- **THEN** 系统 SHALL 立即降级到 skills.sh API；若两条路径都失败，sync_skills_sh.py SHALL 退出码非 0 并输出 ERROR

### Requirement: skills.sh entries SHALL be filtered by install threshold

系统 SHALL 仅保留 `install_count ≥ SKILLS_SH_MIN_INSTALLS` 的 skill 条目进入 catalog，阈值默认 1000，可通过环境变量配置。

#### Scenario: 条目满足阈值
- **WHEN** 一条 skill 的 `installs` 字段值 ≥ 1000（或环境变量配置值）
- **THEN** 系统 SHALL 把它转换为 catalog skill entry 并写入 `catalog/skills/skills_sh_index.json`

#### Scenario: 条目低于阈值
- **WHEN** 一条 skill 的 `installs` 字段值 < 1000
- **THEN** 系统 SHALL 跳过该条目，不写入任何索引文件

#### Scenario: 阈值通过环境变量覆盖
- **WHEN** 环境变量 `SKILLS_SH_MIN_INSTALLS` 被设置为非默认值
- **THEN** 系统 SHALL 使用该环境变量的值作为过滤阈值

### Requirement: skills.sh entries SHALL be normalized to catalog skill schema

系统 SHALL 将 skills.sh 数据格式转换为现有 catalog skill entry schema，保留 install_count 等增值信息。

#### Scenario: 条目正常转换
- **WHEN** 系统处理一条 mastra JSON entry `{source, skillId, owner, repo, installs, githubUrl, displayName}`
- **THEN** 转换出的 catalog entry SHALL 包含字段：`id`（基于 source+skillId 生成）、`name`（来自 skillId）、`description`（默认为空字符串，等待后续富化）、`source_url`（取自 githubUrl 加 skill 子路径）、`source_type=skill`、`install_count`、`skills_sh_url`、`skills_sh_scraped_at`

#### Scenario: id 生成保证唯一
- **WHEN** 多条不同 skill 共享同一 `owner/repo` 但不同 `skillId`
- **THEN** 每条转换出的 entry 的 `id` SHALL 各自唯一（如 `vercel-react-best-practices-vercel-labs`）

### Requirement: skills.sh sync SHALL respect existing catalog entries

系统 SHALL 不破坏现有 catalog 中已存在的 entry，重复 source_url 的条目按优先级合并而非覆盖。

#### Scenario: 同一 source_url 已存在于其他 Tier 1 源
- **WHEN** 一条 skills.sh entry 的 `source_url` 已存在于 anthropics/skills 或其他直接源
- **THEN** 系统 SHALL 保留原 entry 的 `id` 与 `source_url`，仅追加 skills.sh 提供的 `install_count` / `skills_sh_url` / `skills_sh_scraped_at` 字段

#### Scenario: 同一 source_url 已存在于 antigravity 镜像
- **WHEN** 一条 skills.sh entry 的 `source_url` 已存在于 antigravity 镜像
- **THEN** 系统 SHALL 让 skills.sh 来源覆盖镜像 entry 的 `source_url`（指向官方），并合并 install_count 字段

### Requirement: skills.sh sync SHALL support incremental processing

系统 SHALL 支持增量同步：仅对新增或 install_count 变化超过阈值的条目重新评估。

#### Scenario: 完全相同的条目跳过 LLM 评估
- **WHEN** 一条 skills.sh entry 在上次 sync 时已存在，且 `install_count` 变化幅度 ≤ ±20%
- **THEN** 系统 SHALL 复用上次的 LLM 评估结果，不再调用 LLM

#### Scenario: install_count 显著变化触发重评估
- **WHEN** 一条 skills.sh entry 的 `install_count` 较上次变化超过 ±20%
- **THEN** 系统 SHALL 标记该条目进入 LLM 重评估候选列表

#### Scenario: 新条目进入评估
- **WHEN** 一条 skills.sh entry 在上次 sync 时不存在
- **THEN** 系统 SHALL 把它加入 LLM 评估候选列表

### Requirement: skills.sh sync SHALL cache snapshots for ETag-based reuse

系统 SHALL 缓存 mastra JSON 的 ETag，并在下次拉取时附带 `If-None-Match` header 复用未变更数据。

#### Scenario: ETag 命中
- **WHEN** mastra JSON 上次拉取时记录的 ETag 仍有效，HTTP 返回 304
- **THEN** 系统 SHALL 使用本地缓存的 JSON 文件，不重新解析

#### Scenario: ETag 失效
- **WHEN** mastra JSON 返回 200 + 新 ETag
- **THEN** 系统 SHALL 更新本地 JSON 缓存与 ETag 记录

#### Scenario: 缓存目录不存在
- **WHEN** 首次运行或缓存目录被清理
- **THEN** 系统 SHALL 创建 `.skills_sh_cache/` 目录并写入首次快照
