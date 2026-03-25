---
description: '浏览 coding 资源分类。用法: /coding-hub-browse [category]'
argument-hint: category name
---

# Coding Hub - Browse

$ARGUMENTS

---

## 数据源

索引 URL: `https://raw.githubusercontent.com/zgsm-sangfor/costrict-skills-repo/main/catalog/index.json`

用 Bash 执行: `curl -s <URL>` 获取 JSON。

## 执行流程

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
