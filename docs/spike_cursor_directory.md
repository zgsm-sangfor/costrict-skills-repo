# Spike: cursor.directory 程序化访问路径调研

报告时间：2026-05-04 15:18 UTC

> 本报告由 `scripts/spike_cursor_directory.py` 真实探测生成。所有 HTTP 状态码、响应大小、
> __NEXT_DATA__ 字段、pontusab/directories 文件计数均来自实测，**未硬编码**。

## 1. 候选路径探测

| URL | HTTP | 内容类型 | 大小 (bytes) | 耗时 (ms) | 错误 | 可用性 |
|-----|------|----------|--------------|-----------|------|--------|
| https://cursor.directory/api/rules | 404 | application/json | 0 | 946 | HTTPError 404 Not Found | ❌ |
| https://cursor.directory/api/v1/rules | 404 | text/html | 0 | 1416 | HTTPError 404 Not Found | ❌ |
| https://cursor.directory/api/list | 404 | application/json | 0 | 973 | HTTPError 404 Not Found | ❌ |
| https://cursor.directory/api/categories | 404 | application/json | 0 | 611 | HTTPError 404 Not Found | ❌ |
| https://cursor.directory/api/mcp | 404 | application/json | 0 | 1602 | HTTPError 404 Not Found | ❌ |
| https://cursor.directory/api/search | 404 | application/json | 0 | 804 | HTTPError 404 Not Found | ❌ |
| https://cursor.directory/sitemap.xml | 200 | application/xml | 479790 | 4399 | — | ✅ |
| https://cursor.directory/sitemap_index.xml | 404 | text/html | 0 | 1251 | HTTPError 404 Not Found | ❌ |
| https://cursor.directory/robots.txt | 404 | text/html | 0 | 573 | HTTPError 404 Not Found | ❌ |
| https://cursor.directory/ | 200 | text/html | 1339098 | 34651 | — | ✅ |
| https://cursor.directory/rules | — | — | 0 | 66952 | TimeoutError: The read operation timed out | ❌ |
| https://cursor.directory/mcp | — | — | 0 | 116122 | TimeoutError: The read operation timed out | ❌ |

## 2. __NEXT_DATA__ / RSC payload / sitemap 提取

> 未能从任何 HTML 页面提取 `__NEXT_DATA__`。这通常意味着站点是 **Next.js App Router** 而不是 Pages Router
> （App Router 改用 RSC 流式 payload，参见 2.0）。

### 2.0 Next.js App Router RSC payload 检测

> cursor.directory 使用 Next.js App Router（`self.__next_f.push(...)` 流式 RSC payload，
> **没有 Pages Router 风格的 `__NEXT_DATA__`**）。RSC payload 是带前缀 + escape 的私有格式，
> 解析需要 react-server-dom 一致的反序列化器，通用 JSON 提取不可行。

| 来源 URL | self.__next_f | push 数 | 近似 payload 大小 |
|----------|---------------|---------|-------------------|
| `https://cursor.directory/` | ✅ | 19 | 1228327 |

### 2.1 sitemap.xml URL 分布

- 总 URL 数：**2717**

| 顶层路径 | URL 数 |
|----------|--------|
| `/plugins` | 2615 |
| `/companies` | 100 |
| `/(root)` | 1 |
| `/learn` | 1 |

样本 URL：
- https://cursor.directory
- https://cursor.directory/plugins
- https://cursor.directory/learn
- https://cursor.directory/plugins/haiku-mcp-server
- https://cursor.directory/plugins/archcore
- https://cursor.directory/plugins/tap
- https://cursor.directory/plugins/excel-webview2-mcp
- https://cursor.directory/plugins/java-performance-mcp

### 2.2 单个 `/plugins/<slug>` 页面抽样

- URL: `https://cursor.directory/plugins/haiku-mcp-server`
- HTTP: `200`
- 大小: 34604 bytes
- `<title>`: haiku-mcp-server | Cursor Directory | Cursor Directory
- `<meta description>`: haiku-mcp-server plugin for Cursor
- RSC payload: push 数 8, 近似大小 16803 bytes

**结论**：每个 plugin 页面的元数据（title / description）可通过 `<title>` + `<meta>` 标签直接提取，
不依赖 RSC 反序列化。完整的 plugin 字段（作者、tags、content）需进一步解析 RSC 流或转向 Supabase 反向工程。

## 3. pontusab/directories 数据规模复核

- repo: `pontusab/directories`
- default_branch: `main`
- 总 blob 数（仓库全量）: **243**
- tree truncated: `False`
- src/data/ 下文件总数: **3**

### src/data/ 子目录分布

| 子目录 | 文件数 |
|--------|--------|
| `rules` | 3 |

### src/data/ 文件扩展名分布

| 扩展名 | 文件数 |
|--------|--------|
| `.ts` | 3 |

### 样本文件（最多 12 条）

- `src/data/rules/cairo.ts`
- `src/data/rules/fsharp.ts`
- `src/data/rules/symfony.ts`

### 仓库根目录 top-level 分布

| 顶层目录 | 文件数 |
|----------|--------|
| `apps` | 222 |
| `packages` | 10 |
| `(root)` | 7 |
| `src` | 3 |
| `.vscode` | 1 |

## 4. 第三方 wrapper 搜索

> GitHub 全文搜索匹配很噪（带 hyphen 的 token 会拆开），表中 `相关` 列标识 repo 名或描述
> 是否真的提到 `cursor` / `cursor.directory` / `cursor-directory`。

### 查询：`cursor-directory in:name`
- 总匹配数（GitHub 报告）: 10

| repo | stars | pushed_at | description | 相关 |
|------|-------|-----------|-------------|------|
| [escwxyz/cursor-directory](https://github.com/escwxyz/cursor-directory) | 10 | 2025-01-25T07:07:47Z | Raycast extension for cusor.directory | ✅ |
| [drumnation/cursor-directory-structure-ts](https://github.com/drumnation/cursor-directory-structure-ts) | 3 | 2025-12-19T02:25:32Z | A TypeScript tool for monitoring and analyzing project directory structures, with a focus on Cursor IDE integration | ✅ |
| [ericzakariasson/cursor-directory-cli](https://github.com/ericzakariasson/cursor-directory-cli) | 1 | 2025-03-15T16:58:57Z |  | ✅ |
| [juansebsol/cursor-directory-plugin](https://github.com/juansebsol/cursor-directory-plugin) | 1 | 2025-07-01T04:53:01Z | A minimal prompt picker built for Cursor and VSCode. | ✅ |
| [mohammadjaf013/cursor.directory](https://github.com/mohammadjaf013/cursor.directory) | 0 | 2025-08-04T09:14:12Z |  | ✅ |

### 查询：`cursor.directory in:name`
- 总匹配数（GitHub 报告）: 10
- 命中 top-N: （无）

### 查询：`"cursor.directory" scraper in:readme`
- 总匹配数（GitHub 报告）: 17

| repo | stars | pushed_at | description | 相关 |
|------|-------|-----------|-------------|------|
| [nemanjam/bookmarks](https://github.com/nemanjam/bookmarks) | 27 | 2026-05-03T19:11:00Z | Links to useful coding resources. | — |
| [zengzzzzz/golang-trending-archive](https://github.com/zengzzzzz/golang-trending-archive) | 22 | 2026-05-04T01:31:41Z | track golang trending in github | — |
| [giordanorogers/cursor_rules_scraper](https://github.com/giordanorogers/cursor_rules_scraper) | 8 | 2024-12-05T15:43:46Z |  | ✅ |
| [YamilAyma/enlaces-para-desarrolladores](https://github.com/YamilAyma/enlaces-para-desarrolladores) | 4 | 2026-05-03T00:53:33Z | 🚀⭐ Mi lista con enlaces a herramientas, boletines, blogs y entre otros recursos para desarrolladores (Se actualiza a men | — |
| [ly7erg1c/instant_data_scraper_firefox](https://github.com/ly7erg1c/instant_data_scraper_firefox) | 3 | 2025-06-17T08:08:57Z |  | — |

### 查询：`"cursor.directory" api wrapper in:readme`
- 总匹配数（GitHub 报告）: 78

| repo | stars | pushed_at | description | 相关 |
|------|-------|-----------|-------------|------|
| [PatrickJS/awesome-angular](https://github.com/PatrickJS/awesome-angular) | 10013 | 2026-05-03T22:45:59Z | :page_facing_up: A curated list of awesome Angular resources | — |
| [marekbrze/categorized-raycast-extensions](https://github.com/marekbrze/categorized-raycast-extensions) | 599 | 2024-09-27T16:58:01Z | Easily find Raycast Extensions!🚀 | — |
| [Dicklesworthstone/ultimate_bug_scanner](https://github.com/Dicklesworthstone/ultimate_bug_scanner) | 227 | 2026-05-04T05:00:28Z | Static analysis tool that catches 1000+ bug patterns across all popular programming languages, with auto-wiring into AI  | — |
| [xpaysh/awesome-x402](https://github.com/xpaysh/awesome-x402) | 197 | 2026-04-22T04:52:36Z | 🚀 Curated list of x402 resources: HTTP 402 Payment Required protocol for blockchain payments, crypto micropayments, AI a | — |
| [xyzthiago/claude-flows](https://github.com/xyzthiago/claude-flows) | 103 | 2026-02-20T11:12:39Z | 🌊 The leading agent orchestration platform for Claude. Deploy intelligent multi-agent swarms, coordinate autonomous work | — |

> **相关命中合计**：6 个（按 `cursor` / `cursor.directory` 词命中过滤）。

## 5. 可行性评估与推荐

以下结论基于**本次实测**结果。如果运行环境受限（rate-limit / 网络隔离），
结论应以"覆盖最多信号"的方式给出，并在"障碍"小节标注限制。

### 5.1 信号汇总

- `/api/*` 200 命中：**0** 条
- sitemap.xml 命中：✅（2717 个 URL）
- __NEXT_DATA__（Pages Router）提取：❌（cursor.directory 是 App Router）
- RSC payload（App Router）检测：✅
- `_next/data/<buildId>/...` 端点 200 + JSON：❌
- 单个 `/plugins/<slug>` 页面抽样可读出 title/meta：✅
- pontusab/directories src/data 文件数 ≥ 50：❌ (3 个，仅 3 条种子文件，**与 baseline 假设一致**)
- 第三方 cursor.directory 相关 repo（stars 排序，至多 8）：**6** 个

### 5.2 结论

- **推荐路径**：sitemap.xml 提供 **2717** 个 URL（其中 `/plugins/*` 2615 条），单个 plugin 页面可读出 `<title>` + `<meta description>`。完整字段（标签 / 作者 / content）需解析 RSC payload 或反向 Supabase 接口。
- **接入难度**：中
- **推荐下一步**：记 follow-up change `spike-cursor-directory-extended`：评估(a) sitemap + per-plugin 页面 meta 解析（覆盖 title/description，足够 search index）；(b) RSC payload 反序列化的可行性 / 维护成本；(c) 反向 Supabase 公开接口的合规性。**主 change 不在本轮接入，避免阻塞**。

### 5.3 障碍 / 限制

- 部分 URL（2/12）连通失败 — 可能瞬时网络抖动，可重试。

---

_脚本：`scripts/spike_cursor_directory.py` — 仅 Python 标准库，read-only，可重复运行。_
