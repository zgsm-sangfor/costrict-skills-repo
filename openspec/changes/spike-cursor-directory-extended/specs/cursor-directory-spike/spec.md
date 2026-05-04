## ADDED Requirements

### Requirement: Follow-up SHALL evaluate three candidate ingestion paths

继 `add-tier1-rules-mcp-sources` 主 change 的 spike 报告（`docs/spike_cursor_directory.md`）后，follow-up SHALL 对 (a) sitemap+meta、(b) RSC payload、(c) 反向 Supabase 三条候选路径产出选型决策报告并按结论实施。

#### Scenario: 选型报告产出
- **WHEN** follow-up change 进入 design 阶段
- **THEN** 文档 SHALL 含三条路径的成本 / 收益 / 合规性比较表与最终选择理由

#### Scenario: 选定路径实施
- **WHEN** 选型决策为 (a) 或 (c)
- **THEN** 系统 SHALL 实施 `scripts/sync_cursor_directory.py` 与对应 catalog schema 字段（如 `cursor_directory_url`）

#### Scenario: 选型决策为 (b)
- **WHEN** 选定 RSC payload 反序列化
- **THEN** SHALL 先做 PoC 验证 Next.js 升级稳定性，再决定是否实施
