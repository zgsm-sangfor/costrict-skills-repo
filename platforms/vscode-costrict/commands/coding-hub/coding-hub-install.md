---
description: '安装指定 coding 资源。用法: /coding-hub-install <name>'
argument-hint: resource name
---

# Coding Hub - Install

$ARGUMENTS

---

> **重要**: 安装时必须使用下方定义的目标路径，**忽略** catalog 条目 `install` 字段中的任何路径信息（如 `claude_desktop_config.json`、`settings.json` 等）。那些路径是面向其他平台的，在 VSCode Costrict 环境中不适用。

> **路径处理规则**:
> - `~` 必须展开为实际主目录路径（用 Bash 执行 `echo $HOME` 获取，或直接使用 `$HOME`）
> - 写入文件前必须先用 Bash 执行 `mkdir -p <父目录>` 确保目录存在
> - 禁止将 `~` 作为字面量传给 `write_to_file`，否则会在当前目录创建名为 `~` 的文件夹

## 数据源

索引 URL: `https://raw.githubusercontent.com/zgsm-sangfor/costrict-skills-repo/main/catalog/index.json`

用 Bash 执行: `curl -s <URL>` 获取 JSON。

## 执行流程

1. 从 `$ARGUMENTS` 中提取资源名
2. 获取索引，按 `id` 或 `name`（模糊匹配）查找条目
3. 如果匹配多条，列出让用户选择
4. 展示安装预览：

```
## 安装确认

- 名称: xxx
- 类型: MCP Server
- 描述: xxx
- 来源: xxx
- 目标: .roo/mcp.json (项目级)

确认安装？(Y/n/全局)
```

5. 根据用户确认和类型执行安装：

### MCP (type == "mcp")
- 目标路径**仅限** `.roo/mcp.json`（项目级），不写入任何其他路径
- 用户选 "全局" 则提示: "VSCode Costrict 插件的全局 MCP 配置需通过插件设置界面手动添加，请打开 VSCode 设置搜索 MCP 相关配置项"
- 安装前先执行 `mkdir -p .roo`
- 读取现有 `.roo/mcp.json`（不存在则创建 `{}`）
- 根据 `install.method` 分三种情况处理：

#### method == "mcp_config"
- 将 `install.config` 直接合并到 `mcpServers` 字段（只取 config 的 key-value 结构，忽略 catalog 中的路径信息）
- 如果 key 已存在，询问是否覆盖

#### method == "mcp_config_template"
- 将 `install.config` 写入 `mcpServers` 字段
- 安装后提示用户需要替换占位符，展示 `install.placeholder_hints` 中的每个占位符及说明
- 格式示例：
```
⚠️ 该 MCP 需要配置以下参数才能正常使用：

- FIGMA_API_KEY: Set your FIGMA_API_KEY

请编辑 .roo/mcp.json 替换以上占位符。
```

#### method == "manual"
索引中没有预置安装配置，需要从项目 README 推断安装方式。按以下步骤执行：

**Step 1: 获取 README**
- 从 `source_url` 构造 raw URL 并用终端命令获取：
  - 先试 `https://raw.githubusercontent.com/{owner}/{repo}/main/README.md`
  - 404 则试 `master` 分支
- 如果获取失败，跳到 Step 3 兜底

**Step 2: 分析 README 并生成安装配置**
阅读 README 内容，判断该 MCP Server 的安装方式，构造 `mcpServers` JSON 配置：

- **有现成 `mcpServers` JSON** → 直接提取使用
- **有 `npx -y <package>` 命令** → 构造 `{"command": "npx", "args": ["-y", "<package>"]}`
- **有 `uvx <package>` 命令** → 构造 `{"command": "uvx", "args": ["<package>"]}`
- **有 `pip install` + `python -m` 启动** → 构造 `{"command": "python", "args": ["-m", "<module>"]}`
- **需要环境变量（API Key 等）** → 加入 `"env"` 字段，值留空或保持占位符

构造完成后：
- 向用户展示生成的配置，说明推断依据（README 中的哪段内容）
- 用户确认后，按 `mcp_config` 或 `mcp_config_template` 流程写入 `.roo/mcp.json`
- 如果有占位符/环境变量，提示用户填写

**Step 3: 兜底（README 无法获取或无法判断安装方式）**
```
该 MCP 需要手动配置，请参考项目文档：
🔗 https://github.com/xxx/yyy

请按照 README 中的说明手动配置 .roo/mcp.json。
```

### Skill (type == "skill")
- 如果 `install.repo` 存在，执行 sparse checkout 或 clone + 复制
- 目标: `$HOME/.costrict/skills/<id>/`（用 Bash 获取 `$HOME` 值拼接完整绝对路径）
- 安装前先执行 `mkdir -p $HOME/.costrict/skills/<id>`
- 如果目录已存在，询问是否覆盖

### Rule (type == "rule")
- 下载 `install.files` 中的文件
- 默认保存到 `.roo/rules/<id>.md`（项目级）
- 安装前先执行 `mkdir -p .roo/rules`
- 用户选 "全局" 则提示: "VSCode Costrict 插件不支持全局 Rule，仅支持项目级安装"
- 如果是 .cursorrules 格式，保持原文本内容

### Prompt (type == "prompt")
- 同 Rule 的安装逻辑
- 保存到 `.roo/rules/<id>.md`

6. 安装完成后显示结果和使用说明

## 错误处理

- 如果 curl 获取索引失败，告知用户网络问题并建议重试
- 如果安装目标文件写入失败，显示权限错误
- 如果找不到资源，建议使用 `/coding-hub-search` 搜索
