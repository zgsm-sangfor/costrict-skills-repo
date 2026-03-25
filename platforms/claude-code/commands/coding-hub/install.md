---
description: '安装指定 coding 资源。用法: /coding-hub:install <name>'
---

# Coding Hub - Install

$ARGUMENTS

---

## 数据源

索引 URL: `https://raw.githubusercontent.com/zgsm-sangfor/costrict-skills-repo/main/catalog/index.json`
本地备用: `/Volumes/Work/Projects/costrict-skills-repo/catalog/index.json`

用 Bash 执行: `curl -s <URL>` 获取 JSON，如果失败则用 Read 读取本地备用路径。

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
- 目标: .claude/settings.json (项目级)

确认安装？(Y/n/全局)
```

5. 根据用户确认和类型执行安装：

### MCP (type == "mcp")
- 默认写入 `.claude/settings.json`，用户选 "全局" 则写入 `~/.claude/settings.json`
- 读取现有 settings.json（不存在则创建 `{}`）
- 将 `install.config` 合并到 `mcpServers` 字段
- 如果 key 已存在，询问是否覆盖

### Skill (type == "skill")
- 如果 `install.repo` 存在，执行 sparse checkout 或 clone + 复制
- 目标: `~/.claude/skills/<id>/`
- 如果目录已存在，询问是否覆盖

### Rule (type == "rule")
- 下载 `install.files` 中的文件
- 默认保存到 `.claude/rules/<id>.md`，用户选 "全局" 则保存到 `~/.claude/rules/<id>.md`
- 如果是 .cursorrules 格式，保持原文本内容

### Prompt (type == "prompt")
- 同 Rule 的安装逻辑
- 保存到 `.claude/rules/<id>.md`

6. 安装完成后显示结果和使用说明

## 错误处理

- 如果 curl 获取索引失败，告知用户网络问题并建议重试
- 如果安装目标文件写入失败，显示权限错误
- 如果找不到资源，建议使用 `/coding-hub:search` 搜索
