# Spike: windsurf.com/editor/directory 程序化访问路径调研

报告时间：2026-05-04 15:35 UTC

> 本报告由 `scripts/spike_windsurf_directory.py` 真实探测生成。所有 HTTP 状态码、响应大小、
> __NEXT_DATA__ 字段等均来自实测，**未硬编码**。

> 注：本 spike 与 §3（awesome-windsurfrules）独立。awesome-windsurfrules 已在主 change 内接入，
> 因此即便 windsurf.com 官网无可行路径，rules 数据已有覆盖。

## 1. 候选路径探测

| URL | HTTP | 内容类型 | 大小 (bytes) | 耗时 (ms) | 错误 | 可用性 |
|-----|------|----------|--------------|-----------|------|--------|
| https://windsurf.com/editor/directory | 200 | text/html | 834629 | 9637 | — | ✅ |
| https://windsurf.com/editor/directory/rules | 200 | text/html | 66617 | 7733 | — | ✅ |
| https://windsurf.com/editor/directory/mcp | 200 | text/html | 66607 | 1232 | — | ✅ |
| https://windsurf.com/api/rules | 200 | text/html | 65620 | 5070 | — | ✅ |
| https://windsurf.com/api/mcp | 200 | text/html | 65610 | 9849 | — | ✅ |
| https://windsurf.com/api/directory | 200 | text/html | 65640 | 1558 | — | ✅ |
| https://windsurf.com/api/v1/rules | 200 | text/html | 65639 | 3319 | — | ✅ |
| https://windsurf.com/api/list | 200 | text/html | 65615 | 2399 | — | ✅ |
| https://windsurf.com/sitemap.xml | 200 | application/xml | 25838 | 1108 | — | ✅ |
| https://windsurf.com/sitemap_index.xml | 200 | text/html | 66584 | 2642 | — | ✅ |
| https://windsurf.com/robots.txt | 200 | text/plain | 170 | 599 | — | ✅ |
| https://windsurf.com/ | 200 | text/html | 1741323 | 43891 | — | ✅ |

## 2. __NEXT_DATA__ / RSC payload / 框架特征提取

### 2.0 框架特征（基于 HTML 关键词）

| 来源 URL | Next.js | Nuxt | Astro | Gatsby | Webflow | WordPress |
|----------|---------|------|-------|--------|---------|-----------|
| `https://windsurf.com/editor/directory` | ✅ | — | — | — | — | — |
| `https://windsurf.com/editor/directory/rules` | ✅ | — | — | — | — | — |
| `https://windsurf.com/editor/directory/mcp` | ✅ | — | — | — | — | — |
| `https://windsurf.com/api/rules` | ✅ | — | — | — | — | — |
| `https://windsurf.com/api/mcp` | ✅ | — | — | — | — | — |
| `https://windsurf.com/api/directory` | ✅ | — | — | — | — | — |
| `https://windsurf.com/api/v1/rules` | ✅ | — | — | — | — | — |
| `https://windsurf.com/api/list` | ✅ | — | — | — | — | — |
| `https://windsurf.com/sitemap_index.xml` | ✅ | — | — | — | — | — |
| `https://windsurf.com/` | ✅ | — | — | — | — | — |

### 2.1 __NEXT_DATA__ 提取

> 未能从任何 HTML 页面提取 `__NEXT_DATA__`。可能原因：(a) 不是 Next.js Pages Router；
> (b) 是 Next.js App Router（看 RSC 检测）；(c) 完全是其他框架 / 静态站点。

### 2.2 Next.js App Router RSC payload 检测

> 若检出 `self.__next_f.push(...)` 流式 payload，说明 windsurf.com 使用 App Router。
> RSC payload 是带前缀 + escape 的私有格式，解析需要 react-server-dom 一致的反序列化器，
> 通用 JSON 提取不可行。

| 来源 URL | self.__next_f | push 数 | 近似 payload 大小 |
|----------|---------------|---------|-------------------|
| `https://windsurf.com/editor/directory` | ✅ | 64 | 663413 |
| `https://windsurf.com/editor/directory/rules` | ✅ | 14 | 29675 |
| `https://windsurf.com/editor/directory/mcp` | ✅ | 14 | 29667 |
| `https://windsurf.com/api/rules` | ✅ | 15 | 28845 |
| `https://windsurf.com/api/mcp` | ✅ | 15 | 28837 |
| `https://windsurf.com/api/directory` | ✅ | 15 | 28861 |
| `https://windsurf.com/api/v1/rules` | ✅ | 15 | 28861 |
| `https://windsurf.com/api/list` | ✅ | 15 | 28841 |
| `https://windsurf.com/sitemap_index.xml` | ✅ | 14 | 29647 |
| `https://windsurf.com/` | ✅ | 307 | 484371 |

### 2.3 sitemap.xml URL 分布

- 总 URL 数：**307**

| 顶层路径 | URL 数 |
|----------|--------|
| `/blog` | 172 |
| `/university` | 25 |
| `/enterprise` | 11 |
| `/editor` | 11 |
| `/subscription` | 8 |
| `/account` | 7 |
| `/team` | 6 |
| `/auth` | 5 |
| `/settings` | 4 |
| `/pricing` | 3 |
| `/download` | 3 |
| `/careers` | 2 |
| `/indexing` | 2 |
| `/refer` | 2 |
| `/plugins` | 2 |

> sitemap 中包含 `editor/directory/...` 路径 **1** 条，可作为 slug 列表的来源。

样本 URL：
- https://windsurf.com/codemaps
- https://windsurf.com/students
- https://windsurf.com/conversation-share
- https://windsurf.com/deploy
- https://windsurf.com/notifications
- https://windsurf.com/profile
- https://windsurf.com/settings
- https://windsurf.com/about

## 3. 第三方 wrapper 搜索

> GitHub 全文搜索匹配很噪。`相关` 列标识 repo 名或描述是否真的提到
> `windsurf` / `windsurf.com` / `windsurf-directory` 且与 IDE 上下文相关（非冲浪运动）。

### 查询：`windsurf-directory in:name`
- 总匹配数（GitHub 报告）: 0
- 命中 top-N: （无）

### 查询：`windsurf-rules-scraper in:name`
- 总匹配数（GitHub 报告）: 0
- 命中 top-N: （无）

### 查询：`windsurf-rules in:name`
- 总匹配数（GitHub 报告）: 23

| repo | stars | pushed_at | description | 相关 |
|------|-------|-----------|-------------|------|
| [kinopeee/windsurf-antigravity-rules](https://github.com/kinopeee/windsurf-antigravity-rules) | 365 | 2025-12-01T17:36:27Z |  | ✅ |
| [slime21023/windsurf-rules-toolbox](https://github.com/slime21023/windsurf-rules-toolbox) | 6 | 2025-04-10T09:02:28Z | 簡易的常用windsurf 開發規則集 | ✅ |
| [ArvoreDosSaberes/Windsurf-Rules](https://github.com/ArvoreDosSaberes/Windsurf-Rules) | 2 | 2025-12-12T15:37:55Z | Regras para uso no Windsurf é uma coleção das regras que eu uso no windsurf para projetos as regras podem ser adicionada | ✅ |
| [mikhailOlson/Windsurf-Rules](https://github.com/mikhailOlson/Windsurf-Rules) | 1 | 2025-07-21T20:56:20Z |  | ✅ |
| [Custom-Sync/Roblox-Windsurf-Workspace-Rules](https://github.com/Custom-Sync/Roblox-Windsurf-Workspace-Rules) | 1 | 2025-07-22T06:21:26Z | Contains rules that you can always on to enable the AI Model to stop making common mistakes when vibe coding with Roblox | ✅ |

### 查询：`windsurf.com in:readme api`
- 总匹配数（GitHub 报告）: 151

| repo | stars | pushed_at | description | 相关 |
|------|-------|-----------|-------------|------|
| [dwgx/WindsurfAPI](https://github.com/dwgx/WindsurfAPI) | 1013 | 2026-05-04T03:14:49Z | Windsurf-to-OpenAI compatible API proxy | ✅ |
| [mongodb-js/mongodb-mcp-server](https://github.com/mongodb-js/mongodb-mcp-server) | 1014 | 2026-05-04T15:35:17Z | A Model Context Protocol server to connect to MongoDB databases and MongoDB Atlas Clusters. | — |
| [Ibexoft/awesome-startup-tools-list](https://github.com/Ibexoft/awesome-startup-tools-list) | 991 | 2026-04-07T10:19:10Z | List of all tools (apps, services) that startups should use. | — |
| [crispvibe/Windsurf-Tool](https://github.com/crispvibe/Windsurf-Tool) | 332 | 2026-01-07T14:12:42Z | Windsurf-Tool 一键切号，一键查询积分，一键导入，批量注册，获取绑卡链接，自动绑卡免费使用。 适用于Mac Windows 完全开源 \| 本地运行 \| 无后端服务器 | — |
| [chaogei/windsurf-account-manager-simple](https://github.com/chaogei/windsurf-account-manager-simple) | 307 | 2026-05-04T14:25:47Z |  | — |

### 查询：`"windsurf.com/editor/directory" in:readme`
- 总匹配数（GitHub 报告）: 1

| repo | stars | pushed_at | description | 相关 |
|------|-------|-----------|-------------|------|
| [aknip/Vibe-Coding-Tutorial](https://github.com/aknip/Vibe-Coding-Tutorial) | 0 | 2025-06-22T16:38:05Z |  | — |

### 查询：`windsurf mcp directory in:name`
- 总匹配数（GitHub 报告）: 0
- 命中 top-N: （无）

> **相关命中合计**：6 个（按 IDE 上下文过滤）。

## 4. 可行性评估

以下结论基于**本次实测**结果。如果运行环境受限（rate-limit / 网络隔离），
结论应以"覆盖最多信号"的方式给出，并在"障碍"小节标注限制。

### 4.1 信号汇总

- `/editor/directory*` landing 页 200：✅（注意：SPA shell，无静态数据）
- `/api/*` 真 JSON API 命中（content_type=json）：**0** 条
- `/api/*` 返回 SPA shell HTML（catch-all 软 404）：**5** 条 — 说明 windsurf.com 没有公开 REST API
- sitemap.xml 命中：✅（307 个 URL，其中 directory 路径 1 条）
- __NEXT_DATA__（Pages Router）提取：❌
- RSC payload（App Router）检测：✅
- `_next/data/<buildId>/...` 端点 200 + JSON：❌
- 单个 `/editor/directory/<slug>` 页面抽样可读出 title/meta：❌
- 第三方 windsurf 相关 repo（IDE 上下文，stars 排序，至多 8）：**0** 个

### 4.2 结论

- **推荐路径**：windsurf.com 官网无任何可靠程序化路径（无 API、无 __NEXT_DATA__、无 _next/data、无 sitemap directory 路径、无第三方 wrapper）
- **接入难度**：不可行（当前实测）
- **推荐下一步**：**推荐放弃 windsurf.com 官网，仅依赖 awesome-windsurfrules（已通过 §3 接入）**。MCP 维度由 §1 sync_mcp_registry（mcpservers.org）+ 现有 mcp.so 覆盖。无需创建 follow-up spike change（awesome-windsurfrules 已经是 rules 维度的有效覆盖）。

## 5. 推荐下一步（明确指令）

- ❌ **不可行（当前实测）**：**推荐放弃 windsurf.com 官网，依赖 awesome-windsurfrules（已通过 §3 接入）**。
- 不创建 follow-up spike change（rules 维度已被 §3 awesome-windsurfrules 覆盖，不存在缺口）。
- MCP 维度由 §1 sync_mcp_registry（mcpservers.org）+ 现有 mcp.so 覆盖。
- 若将来 windsurf 官方上线 API，再开新 change 重启接入。

### 6. 障碍 / 限制


---

_脚本：`scripts/spike_windsurf_directory.py` — 仅 Python 标准库，read-only，可重复运行。_
