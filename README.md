# Coding Hub

Coding 开发资源的一站式索引。聚合 1200+ 精选 MCP Servers、Skills、Rules、Prompts，覆盖前后端、DevOps、安全、AI/ML 等 11 个分类。

支持 **Claude Code**、**Opencode**、**Costrict** 三个平台。

## For Humans

### 项目结构

```
costrict-skills-repo/
├── catalog/                  # 资源索引（数据层）
│   ├── index.json            # 合并后的完整索引（1292 条）
│   ├── schema.json           # 条目 schema 定义
│   ├── mcp/                  # MCP Server 源数据
│   ├── skills/               # Skill 源数据
│   ├── rules/                # Rule 源数据
│   └── prompts/              # Prompt 源数据
│
├── platforms/                # 各平台 Skill + 子命令
│   ├── claude-code/          # Claude Code 格式
│   │   ├── skills/coding-hub/SKILL.md
│   │   └── commands/coding-hub/{search,browse,recommend,install}.md
│   ├── opencode/             # Opencode 格式
│   │   ├── skills/coding-hub/SKILL.md
│   │   └── command/coding-hub-{search,browse,recommend,install}.md
│   └── costrict/             # Costrict 格式
│       ├── skills/coding-hub/SKILL.md
│       └── commands/coding-hub/coding-hub-{search,browse,recommend,install}.md
│
├── scripts/                  # 数据同步脚本
│   ├── sync_mcp.py           # 从上游同步 MCP
│   ├── sync_skills.py        # 从上游同步 Skills
│   ├── sync_rules.py         # 从上游同步 Rules
│   ├── sync_prompts.py       # 从上游同步 Prompts
│   ├── merge_index.py        # 合并生成 index.json
│   └── llm_evaluator.py      # LLM 质量评估
│
└── openspec/                 # 变更管理（OpenSpec）
```

### 资源统计

| 类型 | 数量 | 说明 |
|------|------|------|
| MCP Server | 518 | Model Context Protocol 服务器 |
| Prompt | 510 | 开发者专用 Prompt |
| Rule | 236 | 编码规范 / AI 辅助规则 |
| Skill | 28 | Agent Skill 扩展 |

### 上游数据源

- **MCP**: [awesome-mcp-servers](https://github.com/punkpeye/awesome-mcp-servers) + [Awesome-MCP-ZH](https://github.com/yzfly/Awesome-MCP-ZH)
- **Skills**: [anthropics/skills](https://github.com/anthropics/skills) + [Ai-Agent-Skills](https://github.com/skillcreatorai/Ai-Agent-Skills)
- **Rules**: [awesome-cursorrules](https://github.com/PatrickJS/awesome-cursorrules) + [rules-2.1-optimized](https://github.com/Mr-chen-05/rules-2.1-optimized)
- **Prompts**: [prompts.chat](https://github.com/f/prompts.chat) + [wonderful-prompts](https://github.com/langgptai/wonderful-prompts)

### 数据同步

通过 GitHub Actions 每周自动从上游源同步，过滤 star > 10 的 coding 相关资源。

### 平台差异

| | Claude Code | Opencode | Costrict |
|---|---|---|---|
| Skill 路径 | `~/.claude/skills/<name>/` | `~/.opencode/skills/<name>/` | `~/.cospec/skills/<name>/` |
| Command 路径 | `.claude/commands/<ns>/` | `.opencode/command/` | `.cospec/<ns>/commands/` |
| 命令分隔符 | `:` (`/coding-hub:search`) | `-` (`/coding-hub-search`) | `-` (`/coding-hub-search`) |

### 贡献

欢迎通过 PR 向 `catalog/` 下对应类型目录添加精选资源。

---

## For Agents

> 以下内容供 AI Agent 阅读，用于自动安装 coding-hub skill。
> 请根据当前运行平台选择对应的安装方式。

### Claude Code

```bash
# 安装 skill（全局）
cp -r platforms/claude-code/skills/coding-hub/ ~/.claude/skills/coding-hub/

# 安装子命令（项目级）
mkdir -p .claude/commands/coding-hub/
cp platforms/claude-code/commands/coding-hub/*.md .claude/commands/coding-hub/
```

安装后可用命令：
- `/coding-hub:search <关键词>` — 搜索资源
- `/coding-hub:browse [分类]` — 浏览分类
- `/coding-hub:recommend` — 基于当前项目推荐
- `/coding-hub:install <名称>` — 安装资源

### Opencode

```bash
# 安装 skill（全局）
mkdir -p ~/.opencode/skills/coding-hub/
cp platforms/opencode/skills/coding-hub/SKILL.md ~/.opencode/skills/coding-hub/

# 安装子命令（项目级）
mkdir -p .opencode/command/
cp platforms/opencode/command/*.md .opencode/command/
```

安装后可用命令：
- `/coding-hub-search <关键词>` — 搜索资源
- `/coding-hub-browse [分类]` — 浏览分类
- `/coding-hub-recommend` — 基于当前项目推荐
- `/coding-hub-install <名称>` — 安装资源

### Costrict

```bash
# 安装 skill（全局）
mkdir -p ~/.cospec/skills/coding-hub/
cp platforms/costrict/skills/coding-hub/SKILL.md ~/.cospec/skills/coding-hub/

# 安装子命令（项目级）
mkdir -p .cospec/coding-hub/commands/
cp platforms/costrict/commands/coding-hub/*.md .cospec/coding-hub/commands/
```

安装后可用命令：
- `/coding-hub-search <关键词>` — 搜索资源
- `/coding-hub-browse [分类]` — 浏览分类
- `/coding-hub-recommend` — 基于当前项目推荐
- `/coding-hub-install <名称>` — 安装资源

### 验证

安装完成后，运行搜索命令测试：

```
/coding-hub:search typescript    # Claude Code
/coding-hub-search typescript    # Opencode / Costrict
```

返回搜索结果表格即安装成功。

### 数据源

索引 URL: `https://raw.githubusercontent.com/zgsm-sangfor/costrict-skills-repo/main/catalog/index.json`

索引是 JSON 数组，每个条目包含 `id`, `name`, `type`(mcp/skill/rule/prompt), `description`, `source_url`, `stars`, `category`, `tags`, `tech_stack`, `install`。
