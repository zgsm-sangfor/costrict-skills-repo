## ADDED Requirements

### Requirement: System SHALL generate a popular-skill coverage report

系统 SHALL 提供 `scripts/audit_popular_coverage.py`，对照外部"热门 skill 期望清单"核对 catalog 收录状态，输出 markdown 报告到 `docs/coverage_report.md`。

#### Scenario: 期望清单中 skill 已直接收录
- **WHEN** 期望清单中一条 skill 的 `source_url` 在 catalog 中存在且来自直接源（非镜像）
- **THEN** 报告中该条目状态 SHALL 标记为 `✅ 直接源`

#### Scenario: 期望清单中 skill 仅以镜像形式存在
- **WHEN** 期望清单中一条 skill 的 `source_url` 仅命中 antigravity 镜像源
- **THEN** 报告中该条目状态 SHALL 标记为 `⚠️ 仅镜像`

#### Scenario: 期望清单中 skill 完全缺失
- **WHEN** 期望清单中一条 skill 的 `source_url` 在 catalog 中不存在
- **THEN** 报告中该条目状态 SHALL 标记为 `❌ 未收录`

### Requirement: Coverage audit SHALL include install_count from skills.sh

系统 SHALL 在覆盖率报告中展示每个期望条目的 `install_count`（若 catalog 中有该字段），用于优先级排序。

#### Scenario: catalog entry 含 install_count
- **WHEN** 期望清单条目对应的 catalog entry 含 `install_count` 字段
- **THEN** 报告 SHALL 显示该数值并按降序排列状态行

#### Scenario: catalog entry 无 install_count
- **WHEN** 对应 catalog entry 缺 `install_count` 字段
- **THEN** 报告 SHALL 在该列显示 `-`

### Requirement: Coverage audit SHALL run in CI

CI 流水线 SHALL 在 `merge_index` 与 `update_readme` 之后调用 `audit_popular_coverage.py`，并把生成的 `docs/coverage_report.md` 一并 commit。

#### Scenario: CI 自动运行覆盖率审计
- **WHEN** weekly sync workflow 完成 merge_index 与 update_readme
- **THEN** CI SHALL 执行 `python scripts/audit_popular_coverage.py` 并把结果 commit 到 `docs/coverage_report.md`

#### Scenario: 报告无变化时不产生空 commit
- **WHEN** 生成的报告内容与上次完全一致
- **THEN** CI SHALL 跳过 commit，避免产生空提交

### Requirement: Expected popular-skill list SHALL be maintained as YAML

期望清单 SHALL 保存为 `scripts/popular_skills_expected.yaml`，包含每条 skill 的 `name`、`github_repo`、`reason`（被期望收录的理由）。

#### Scenario: 期望清单结构合法
- **WHEN** YAML 文件被加载
- **THEN** 每条记录 SHALL 至少含 `name` 与 `github_repo` 两个字段，否则脚本 SHALL 退出码非 0

#### Scenario: 期望清单初始内容
- **WHEN** 本 change 首次落地
- **THEN** 期望清单 SHALL 至少包含 obra/superpowers、vercel-labs/agent-skills、vercel-labs/agent-browser、supermemoryai/supermemory、Leonxlnx/taste、Dammyjay93/interface-design、anthropics/skills 这 7 条
