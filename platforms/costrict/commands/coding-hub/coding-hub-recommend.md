---
description: '基于当前项目技术栈推荐 coding 资源。用法: /coding-hub-recommend'
---

# Coding Hub - Recommend

## 数据源

索引 URL: `https://raw.githubusercontent.com/zgsm-sangfor/costrict-skills-repo/main/catalog/index.json`

用 Bash 执行: `curl -s <URL>` 获取 JSON。

## 执行流程

1. 分析当前项目技术栈：
   - 读取 `package.json` → 提取 dependencies 中的框架名 (react, next, vue, express, etc.)
   - 读取 `requirements.txt` / `pyproject.toml` → 提取 Python 包名
   - 读取 `go.mod` → 提取 Go module
   - 读取 `Cargo.toml` → 提取 Rust crate
   - 读取 `Gemfile` → 提取 Ruby gem
   - 检查文件后缀: `.tsx`→react, `.vue`→vue, `.py`→python, `.go`→go, `.rs`→rust, `.swift`→swift, `.kt`→kotlin
   - 检查配置文件: `Dockerfile`→docker, `.github/workflows/`→ci-cd, `tsconfig.json`→typescript

2. 将识别到的技术栈与索引中每条的 `tags` 和 `tech_stack` 做交集匹配
3. 按匹配标签数 + stars 排序，展示 Top 10
4. 展示格式：

```
## 项目推荐

检测到技术栈: Python, FastAPI, Docker, PostgreSQL

| # | 名称 | 类型 | 匹配标签 | Stars | 描述 |
|---|------|------|----------|-------|------|
| 1 | xxx  | MCP  | python, fastapi | 1234 | xxx |
```

5. 提示: "输入 `/coding-hub-install <名称>` 安装"
