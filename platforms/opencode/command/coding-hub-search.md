---
description: '搜索 coding 资源（MCP/Skills/Rules/Prompts）。用法: /coding-hub-search <query>'
---

# Coding Hub - Search

$ARGUMENTS

---

## 数据源

索引 URL: `https://raw.githubusercontent.com/zgsm-sangfor/costrict-skills-repo/main/catalog/index.json`

用 Bash 执行: `curl -s <URL>` 获取 JSON。
索引是一个 JSON 数组，每个条目包含: id, name, type, description, source_url, stars, category, tags, tech_stack, install。

## 执行流程

1. 从 `$ARGUMENTS` 中提取搜索关键词和可选的类型过滤参数
   - 支持 `type:mcp`、`type:skill`、`type:rule`、`type:prompt` 过滤
   - 示例: `/coding-hub-search typescript type:mcp` — 只搜索 MCP 类型
   - 如果参数中包含 `type:<值>`，提取为过滤条件，剩余部分作为搜索关键词
2. 获取索引 JSON
3. 如果指定了类型过滤，先按 `type` 字段过滤索引
4. 在每条记录的 `name`、`description`、`tags` 中搜索关键词（不区分大小写）
5. 结果按匹配度（匹配字段数量）+ stars 降序排列
6. 展示前 10 条结果，格式：

```
## 搜索结果: "<query>"

| # | 名称 | 类型 | 分类 | Stars | 描述 |
|---|------|------|------|-------|------|
| 1 | xxx  | MCP  | xxx  | 1234  | xxx  |
```

6. 提示用户: "输入 `/coding-hub-install <名称>` 安装，或继续搜索"
