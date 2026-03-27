---
description: '浏览 coding 资源分类。用法: /coding-hub-browse [category] [type:mcp|skill|rule|prompt]'
argument-hint: category name
---

# Coding Hub - Browse

$ARGUMENTS

---

## 数据源

索引 URL: `https://raw.githubusercontent.com/zgsm-sangfor/costrict-skills-repo/main/catalog/index.json`

用 Bash 执行: `curl -s <URL>` 获取 JSON。

## 执行流程

0. 从 `$ARGUMENTS` 中提取可选的类型过滤参数
   - 支持 `type:mcp`、`type:skill`、`type:rule`、`type:prompt` 过滤
   - 示例: `/coding-hub-browse type:skill` — 只浏览 Skill 类型
   - 示例: `/coding-hub-browse backend type:mcp` — 只浏览 backend 分类下的 MCP
   - 如果参数中包含 `type:<值>`，提取为过滤条件，剩余部分作为分类参数
   - 如果指定了类型过滤，在执行后续步骤前先按 `type` 字段过滤索引

### 无参数时: 展示分类概览

1. 获取索引，按 `category` 分组计数
2. 展示：

```
## 资源分类

| 分类 | 数量 | 描述 |
|------|------|------|
| frontend | 42 | 前端框架与工具 |
| backend | 38 | 后端框架与语言 |
| fullstack | 5 | 全栈项目模板 |
| mobile | 12 | 移动端开发 |
| devops | 20 | 运维与部署 |
| database | 15 | 数据库工具 |
| testing | 18 | 测试框架与工具 |
| security | 10 | 安全相关 |
| ai-ml | 30 | AI 与机器学习 |
| tooling | 50 | 开发工具链 |
| documentation | 8 | 技术文档 |
```

3. 提示: "输入 `/coding-hub-browse <分类名>` 查看详情"

### 有参数时: 展示该分类下所有条目

1. 从 `$ARGUMENTS` 中提取分类名
2. 过滤 `category == 参数`
3. 按 type 分组展示，每组按 stars 降序
4. 提示: "输入 `/coding-hub-install <名称>` 安装"
