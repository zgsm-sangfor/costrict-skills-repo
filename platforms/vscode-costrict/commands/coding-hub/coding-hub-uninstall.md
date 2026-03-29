---
description: '卸载已安装的 coding 资源。用法: /coding-hub-uninstall <name>'
argument-hint: resource name
---

# Coding Hub - Uninstall

$ARGUMENTS

---

## 数据源

索引 URL: `https://raw.githubusercontent.com/zgsm-sangfor/costrict-coding-hub/main/catalog/index.json`

用 Bash 执行: `curl -s <URL>` 获取 JSON。

## 执行流程

1. 从 `$ARGUMENTS` 中提取资源名
2. 获取索引，按 `id` 或 `name`（模糊匹配）查找条目
3. 如果匹配多条，列出让用户选择要卸载的具体资源
4. 检测安装状态和安装位置：

### MCP (type == "mcp")
- 检查项目级 `.roo/mcp.json` 中的 `mcpServers` 字段
- 查找与该资源 `install.config` key 匹配的条目

### Skill (type == "skill")
- 检查 `$HOME/.costrict/skills/<id>/` 目录是否存在

### Rule (type == "rule") / Prompt (type == "prompt")
- 检查项目级 `.roo/rules/<id>.md`

5. 如果资源未安装（所有位置都不存在），提示 "{name} 未安装" 并终止

6. 展示卸载预览：

```
## 卸载确认

- 名称: xxx
- 类型: MCP Server
- 安装位置: .roo/mcp.json (项目级)

确认卸载？(Y/n)
```

7. 根据用户确认执行卸载，完成后显示结果

## 错误处理

- 如果 curl 获取索引失败，告知用户网络问题并建议重试
- 如果找不到资源，建议使用 `/coding-hub-search` 搜索
