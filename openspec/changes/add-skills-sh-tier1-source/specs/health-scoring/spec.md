## ADDED Requirements

### Requirement: Health signals SHALL include install_popularity from skills.sh

Health 评分对象 SHALL 在 `signals` 子对象中支持可选信号 `install_popularity`，由 skills.sh 提供的 `install_count` 派生而来。

#### Scenario: entry 含 install_count
- **WHEN** 一条 skill entry 含 `install_count` 字段
- **THEN** health.signals.install_popularity SHALL 由 `min(100, log10(max(install_count, 1)) / log10(100000) * 100)` 计算得出

#### Scenario: entry 缺 install_count
- **WHEN** 一条 entry 不含 `install_count` 字段或值为 null
- **THEN** health.signals.install_popularity SHALL 为 0 或省略

### Requirement: install_popularity SHALL default to weight 0.05 in composite score

健康分综合公式 SHALL 默认按权重 0.05 把 install_popularity 计入 final_score，仅 skills.sh 派生 entry 受影响（含 `install_count > 0`），其他 entry 走 `excluded_signals` 路径自动剔除信号。

#### Scenario: 默认权重 0.05 仅 skills.sh entry 受影响
- **WHEN** 计算 skills.sh 派生 skill entry 的 health.score（含 install_count > 0）
- **THEN** install_popularity 信号 SHALL 按权重 0.05 纳入 final_score 加权
- **AND** 原 freshness/popularity/source_trust 权重按比例缩减到总和 0.95，使非零信号权重和保持 1.0

#### Scenario: 非 skills.sh entry 不受默认权重影响
- **WHEN** 计算非 skills.sh 来源 entry 的 health.score（无 install_count 或为 0）
- **THEN** install_popularity 信号 SHALL 进入 excluded 集合，原权重按比例分回 freshness/popularity/source_trust
- **AND** health_score 数值与权重为 0 时完全等价

#### Scenario: install_popularity 出现在 health 输出中
- **WHEN** health scorer 处理含 install_count 的 entry
- **THEN** 输出 health 对象 SHALL 在 signals 子对象中包含 install_popularity 字段以便观测

#### Scenario: 权重通过环境变量调优
- **WHEN** 通过环境变量 `HEALTH_W_INSTALL_POPULARITY` 配置非零权重
- **THEN** final_score 公式 SHALL 把该信号按权重纳入计算（默认值 0.05；设 0 等价于禁用）
