---
description: '搜索 coding 资源（MCP/Skills/Rules/Prompts）。用法: /coding-hub:search <query>'
---

# Coding Hub - Search

$ARGUMENTS

---

## 数据源

索引 URL: `https://raw.githubusercontent.com/zgsm-sangfor/costrict-skills-repo/main/catalog/index.json`
本地备用: `/Volumes/Work/Projects/costrict-skills-repo/catalog/index.json`

用 Bash 执行: `curl -s <URL>` 获取 JSON，如果失败则用 Read 读取本地备用路径。
索引是一个 JSON 数组，每个条目包含: id, name, type, description, source_url, stars, category, tags, tech_stack, install。

## 执行流程

1. 从 `$ARGUMENTS` 中提取搜索关键词
2. 获取索引 JSON
3. 在每条记录的 `name`、`description`、`tags` 中搜索关键词（不区分大小写）
4. 结果按匹配度（匹配字段数量）+ stars 降序排列
5. 展示前 10 条结果，格式：

```
## 搜索结果: "<query>"

| # | 名称 | 类型 | 分类 | Stars | 描述 |
|---|------|------|------|-------|------|
| 1 | xxx  | MCP  | xxx  | 1234  | xxx  |
```

6. 提示用户: "输入 `/coding-hub:install <名称>` 安装，或继续搜索"
