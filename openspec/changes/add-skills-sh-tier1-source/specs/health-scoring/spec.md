## ADDED Requirements

### Requirement: Health signals SHALL include install_popularity from skills.sh

Health 评分对象 SHALL 在 `signals` 子对象中支持可选信号 `install_popularity`，由 skills.sh 提供的 `install_count` 派生而来。

#### Scenario: entry 含 install_count
- **WHEN** 一条 skill entry 含 `install_count` 字段
- **THEN** health.signals.install_popularity SHALL 由 `min(100, log10(max(install_count, 1)) / log10(100000) * 100)` 计算得出

#### Scenario: entry 缺 install_count
- **WHEN** 一条 entry 不含 `install_count` 字段或值为 null
- **THEN** health.signals.install_popularity SHALL 为 0 或省略

### Requirement: install_popularity SHALL default to weight 0 in composite score

健康分综合公式 SHALL 默认不把 install_popularity 计入 final_score，权重为 0，仅作为可观测信号采集。

#### Scenario: 默认权重不影响 final_score
- **WHEN** 计算任意 skill entry 的 health.score
- **THEN** install_popularity 信号 SHALL 不参与 final_score 加权（即权重 0）

#### Scenario: install_popularity 出现在 health 输出中
- **WHEN** health scorer 处理含 install_count 的 entry
- **THEN** 输出 health 对象 SHALL 在 signals 子对象中包含 install_popularity 字段以便观测

#### Scenario: 权重通过环境变量调优
- **WHEN** 未来通过环境变量 `HEALTH_W_INSTALL_POPULARITY` 配置非零权重
- **THEN** final_score 公式 SHALL 把该信号按权重纳入计算（本 change 范围内默认值仍为 0）
