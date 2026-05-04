## Why

`add-tier1-rules-mcp-sources` §9 spike 实测确认 cursor.directory 没有公开 JSON API，且 GitHub repo `pontusab/directories` 与 `leerob/directories` 的 `src/data/rules/` 仅含 3 条种子文件（cairo / fsharp / symfony — 与 baseline 假设一致）。真实数据存储在 Supabase，sitemap.xml 暴露了 **2,615 个 `/plugins/<slug>` URL** 但完整字段需解析 Next.js App Router RSC payload 或反向 Supabase 接口，工程量与稳定性风险较高，不适合在主 change 内接入。本 change 用作专门 spike 的扩展位，先不实施，仅占位。

## What Changes

- 评估三条候选接入路径并比较成本 / 收益：
  - **(a) sitemap + per-plugin 页面 meta 解析**：抓 sitemap.xml → 遍历 2,615 个 `/plugins/<slug>` 页面 → 提取 `<title>` + `<meta description>`。**优点**：实测可读、解析简单；**缺点**：每条 entry 一次 HTTP 请求（且 cursor.directory 启用 Vercel WAF，Bot UA 直接 429，需 Browser UA + 限速），完整字段（标签 / 作者 / install 命令 / content 主体）拿不到，只够做 search-index 占位
  - **(b) RSC payload 反序列化**：解析每个页面 HTML 中的 `self.__next_f.push(...)` 流；需要 react-server-dom 兼容的反序列化器或自研。**优点**：拿到完整字段；**缺点**：格式私有 + 每次 Next.js 升级都可能崩
  - **(c) 反向 Supabase 公开接口**：从 chunked JS bundle 中抠出 anon key + URL，直接查 `supabase.from("posts")`。**优点**：拿到完整数据库结构；**缺点**：合规性风险（站点条款）、anon key 随时可能撤
- 输出选型决策报告：从 (a)/(b)/(c) 中选择并说明理由
- 如选 (a)：实施 `scripts/sync_cursor_directory.py`，新增 catalog 字段 `cursor_directory_url`
- 如选 (b)：先做 RSC 反序列化原型 PoC，验证一周内格式稳定性
- 如选 (c)：先与 cursor.directory 维护者（leerob / pontusab）邮件沟通取得授权

## Impact

- Affected specs: `cursor-directory-spike`（本 change 进一步推进，不修改主 change 已归档的 spec）
- Affected code: 新增 `scripts/sync_cursor_directory.py`（如选 (a) 或 (c)）；`scripts/spike_cursor_directory_rsc_poc.py`（如选 (b) 走 PoC 阶段）

## Status

**Pending** — 仅占位，待主 change `add-tier1-rules-mcp-sources` 合入并稳定运行 ≥ 2 周后再启动评估。spike 真实输出见 `docs/spike_cursor_directory.md`。
