## ADDED Requirements

### Requirement: System SHALL fetch rules from awesome-windsurfrules repos

系统 SHALL 从 SchneiderSam/awesome-windsurfrules 与 balqaasem/awesome-windsurfrules 两个 GitHub 仓库的 `rules/` 子目录拉取所有 markdown rule 文件。

#### Scenario: 拉取标准 rules 目录
- **WHEN** sync_windsurfrules.py 启动
- **THEN** 系统 SHALL 通过 GitHub API 递归列出两个仓库的 `rules/` 子目录所有 .md 文件，逐个 raw fetch 内容

#### Scenario: 仓库不存在或被 archive 时跳过
- **WHEN** 某个仓库返回 404 或 disabled
- **THEN** 系统 SHALL 输出 WARNING 跳过该仓库，继续处理其他源

### Requirement: balqaasem fork SHALL handle global_rules subdirectory specially

系统 SHALL 识别 balqaasem fork 仓库的 `rules/global_rules/` 子目录并标记为 windsurf-global 类别。

#### Scenario: global_rules 路径下文件标记
- **WHEN** 处理 SchneiderSam / balqaasem 仓库中路径形如 `rules/global_rules/<slug>/global_rules.md` 的文件
- **THEN** 转换出的 catalog rule entry SHALL 在 tags 中含 "windsurf-global"，category 为 catalog 合法 enum 内的兜底值（实现选 "tooling"，因 catalog VALID_CATEGORIES 不含 "global"），通过 windsurf-global tag 区分

#### Scenario: 其他路径文件正常处理
- **WHEN** 处理仓库中非 global_rules 子路径的 .md 文件
- **THEN** 系统 SHALL 按现有 sync_rules 风格设置 category（如基于文件名或 frontmatter）

### Requirement: Rule entries SHALL be normalized to catalog rule schema

系统 SHALL 将 markdown rule 文件转换为现有 catalog rule entry schema，与 sync_rules.py 输出格式一致。

#### Scenario: 字段提取
- **WHEN** 处理一个 .md 文件
- **THEN** 转换出的 catalog entry SHALL 含：`id`（基于文件名+repo），`name`（取文件 frontmatter title 或文件名），`description`（取文件首段或 frontmatter description），`source_url`（GitHub blob URL），`source_type=rule`，`category`，`tags`

#### Scenario: 跨仓库 id 唯一
- **WHEN** SchneiderSam 与 balqaasem 仓库下同名 rule 文件
- **THEN** 各自生成的 id SHALL 不同（含 repo slug 后缀，如 `react-rule-schneidersam` vs `react-rule-balqaasem`）

### Requirement: Sync output SHALL be sidecar index for merge_index consumption

系统 SHALL 输出 `catalog/rules/windsurfrules_index.json`，结构与现有 `catalog/skills/skills_sh_index.json` 等 sidecar 一致，由 merge_index.py 统一消费。

#### Scenario: sidecar 文件格式
- **WHEN** sync_windsurfrules.py 完成
- **THEN** 输出 SHALL 是 JSON 数组，每条 entry 符合 catalog rule entry schema

#### Scenario: merge_index 自动读取
- **WHEN** merge_index.py 跑 rules 类型分支
- **THEN** 它 SHALL 加载 windsurfrules_index.json 并加入 entry 池参与去重
