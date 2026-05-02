## ADDED Requirements

### Requirement: Skill entry SHALL support optional skills.sh provenance fields

Skill 类型的 catalog entry SHALL 支持三个可选字段：`install_count`（int，来自 skills.sh 的真实安装量）、`skills_sh_url`（str，skills.sh 上对应 skill 页 URL）、`skills_sh_scraped_at`（ISO 8601，skills.sh 数据快照时间）。

#### Scenario: skill entry 来自 skills.sh 源
- **WHEN** 一个 skill entry 由 sync_skills_sh.py 生成或被该流程合并 enrich
- **THEN** entry SHALL 包含 `install_count`、`skills_sh_url`、`skills_sh_scraped_at` 三个字段，值分别取自上游 mastra/skills.sh 数据

#### Scenario: skill entry 来自非 skills.sh 源
- **WHEN** 一个 skill entry 由其他源（anthropics/skills、antigravity 镜像、curated.json 等）生成且未与 skills.sh 数据匹配
- **THEN** entry MAY 不含上述三个字段，schema 校验 SHALL 不视其为错误

#### Scenario: skill entry 在多源合并后获得 skills.sh 字段
- **WHEN** 一个原本仅来自 anthropics/skills 的 skill entry 在 merge_index 阶段与 skills.sh 数据匹配（同 source_url）
- **THEN** 系统 SHALL 把 skills.sh 提供的三个字段追加到该 entry，不替换其他字段

### Requirement: Schema validation SHALL accept new optional fields

Catalog schema 校验 SHALL 不因 `install_count`、`skills_sh_url`、`skills_sh_scraped_at` 字段缺失而失败，但若存在则字段类型 SHALL 与定义一致。

#### Scenario: 字段类型正确
- **WHEN** 一条 entry 包含 `install_count: 1234`、`skills_sh_url: "https://skills.sh/..."`、`skills_sh_scraped_at: "2026-01-30T04:51:07Z"`
- **THEN** schema 校验 SHALL 通过

#### Scenario: 字段类型错误
- **WHEN** 一条 entry 的 `install_count` 是字符串、或 `skills_sh_scraped_at` 不是 ISO 8601 格式
- **THEN** schema 校验 SHALL 失败并指出具体字段

#### Scenario: 字段全部缺失
- **WHEN** 一条 entry 完全不含上述三个字段
- **THEN** schema 校验 SHALL 通过（向后兼容）
