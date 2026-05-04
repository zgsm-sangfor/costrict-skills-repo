# Tier 1 Rules + MCP 接入基线报告

> 对应 OpenSpec change：`add-tier1-rules-mcp-sources` 任务 §1
> 探针时间：2026-05-04
> 探针环境：本机直连（无 GITHUB_TOKEN，registry API 公开）

## 摘要

| 指标 | registry.modelcontextprotocol.io | awesome-windsurfrules（双仓库合并） |
|------|----------------------------------|----------------------------------|
| 上游条目总数 | 22,314 | 214（108 + 106） |
| 过滤后入库候选 | **7,496** active+isLatest | **108** 唯一 slug（合并后） |
| 与现有 catalog 重叠 | 76（GitHub ID 严格匹配，1.0%） | 103（与 awesome-cursorrules 同名，95.4%） |
| 净新增（保守估算） | **6,500–7,400** | **5–8** |
| 跨源 fuzzy match 边界 | 29 条 reverse-DNS 命名待 fuzzy 处理 | 几乎无（重叠主要靠 path/slug） |

结论：MCP registry 是巨大补强（catalog 翻 4–5 倍），windsurfrules 增量极有限（5–8 条），但保留接入有价值——它是 Tier 1 Windsurf 生态信号源，少量 `global_rules/` 是 Windsurf 独有特性。

---

## 1. registry.modelcontextprotocol.io 拉取统计

### 拉取过程

- API：`GET https://registry.modelcontextprotocol.io/v0/servers?limit=100&cursor=...`
- 分页：cursor 形如 `<server.name>:<version>`（如 `ai.smithery/kirbah-mcp-youtube:0.2.6`）
- 完整翻页：**224 页**，约 9 分钟，无 rate-limit
- HTTP 200，schema 字段稳定（与 design.md 描述一致）

### 数据分布

| 项 | 数量 |
|----|------|
| 总条目（含历史 version） | 22,314 |
| `_meta.*.status == "active"` | 22,226 |
| `_meta.*.status == "deprecated"` | 88 |
| `isLatest == true` | 7,520 |
| **active + isLatest（入库目标）** | **7,496** |
| 唯一 `server.name`（active+isLatest） | 7,496 |

> design.md 的"5K-8K 估算"上界，实际命中 7,496，建议 tasks §11.2 期望值改为 **7,000–8,000**。

### server.name 命名分布（active+isLatest 7,496 条内）

| pattern | count |
|---------|-------|
| `io.github.<owner>/<repo>` | 5,819（77.6%） |
| 其他 reverse-DNS（`com.x/y` `ai.x/y` `app.x/y` `dev.x/y` 等） | 1,677（22.4%） |

**关键**：77% 的 entry 可直接映射到 GitHub owner/repo（虽然 owner 大小写需要 lower-case），剩余 22% 是商业/SaaS 厂商以自有 domain 注册。

### 字段完整性

抽样 100 条 active+isLatest，所有条目包含：
- `server.name`、`server.title`、`server.description`、`server.version` ✅
- `_meta.io.modelcontextprotocol.registry/official.{status,publishedAt,statusChangedAt,isLatest,updatedAt}` ✅

可选字段：
- `server.remotes[]`（仅 SaaS 类型 entry 有）：约 10–15% 抽样命中
- `server.repository.url`（spec 提到但本次抽样未观察到该字段）

字段映射建议沿用 design.md D2 表格无需调整。

---

## 2. awesome-windsurfrules 仓库统计

### 拉取过程

- API：`GET https://api.github.com/repos/{repo}/git/trees/main?recursive=1`
- 无 token 60 req/h 即可完成（每仓库 1 次 tree call）
- HTTP 200，无截断（`truncated: false`）

### 数据分布

| 仓库 | 默认分支 | stars | fork | tree 总条目 | rules/*.md | rules/global_rules/*.md | rules/windsurfrules/*.md |
|------|---------|-------|------|-------------|------------|------------------------|--------------------------|
| SchneiderSam/awesome-windsurfrules | main | 71 | true | 374 | **108** | 3 | 105 |
| balqaasem/awesome-windsurfrules | main | 47 | true | 368 | **106** | 3 | 103 |

注：两个仓库都是 fork（很可能 fork 自 awesome-cursorrules 或彼此互 fork），因此目录结构高度同质。

### 路径模式

- `rules/global_rules/<slug>/global_rules.md`（3 个，两仓库一致）
- `rules/windsurfrules/<slug>/README.md`（103–105 个）

### 跨仓库 dedup

| 项 | count |
|----|-------|
| 两仓库共有 slug | 106 |
| 仅 SchneiderSam 独有 | **2**（`blueprint-windsurfrules-prompt-file`, `nextjs-vercel-supabase-windsurfrules-prompt-file`） |
| 仅 balqaasem 独有 | 0 |
| 合并后唯一 slug | **108** |

→ balqaasem 仓库不带任何 SchneiderSam 没有的内容；保留 balqaasem 作为镜像主要为冗余。

---

## 3. 与现有 catalog 的重叠分析

### 3.1 MCP（registry vs catalog/mcp/index.json）

**catalog 现状**：1,633 条，来源分布 `mcp.so=1058`、`awesome-mcp-zh=372`、`awesome-mcp-servers=203`。其中 1,598 条带 GitHub URL（可提取 owner/repo）。

**严格匹配（registry 推断的 GitHub ID 与 catalog 已有 GitHub URL 完全相等）**：

- registry 7,496 条 → 76 条命中 catalog（1.0%）
- 主要来自 `io.github.*` 模式

样例（registry_name → catalog github_id）：

```
io.github.GLips/Figma-Context-MCP        ->  glips/figma-context-mcp
io.github.SonarSource/sonarqube-mcp-server -> sonarsource/sonarqube-mcp-server
io.github.microsoft/playwright-mcp       -> microsoft/playwright-mcp
io.github.antvis/mcp-server-chart        -> antvis/mcp-server-chart
io.github.IvanMurzak/Unity-MCP           -> ivanmurzak/unity-mcp
com.gitkraken/gk-cli                     -> gitkraken/gk-cli
com.iunera/druid-mcp-server              -> iunera/druid-mcp-server
com.teamwork/mcp                         -> teamwork/mcp
```

**净新增（registry 独有）**：~7,420 条，约 catalog MCP 总量的 4.5 倍。

### 3.2 Rules（windsurfrules vs catalog/rules/index.json）

**catalog 现状**：237 条，来源 `awesome-cursorrules=183`、`rules-2.1-optimized=54`。

**slug 匹配**（取目录名作为对比键）：

| 仓库 | total .md | 命中 catalog awesome-cursorrules slug | 净新增 |
|------|-----------|----------------------------------|--------|
| SchneiderSam | 108 | 103 | 5 |
| balqaasem | 106 | 103 | 3 |
| **合并去重后** | **108** | **103** | **5** |

5 个 windsurf 独有 slug：
- `blueprint-windsurfrules-prompt-file`
- `commit-message-long-global_rules-prompt-file`（global_rules）
- `commit-message-short-global_rules-prompt-file`（global_rules）
- `global-en-language-global_rules-prompt-file`（global_rules）
- `nextjs-vercel-supabase-windsurfrules-prompt-file`

→ **入库价值**：只有 5 条净新增 + 2 条 SchneiderSam 独有。但 windsurf 系生态信号（windsurfrules-prompt-file 命名 + 3 个 global_rules）在 frontend 标签上有差异化价值，建议保留接入。

---

## 4. 跨源 fuzzy match 边界案例

design.md 提到 `microsoft.com/playwright/mcp` vs `microsoft/playwright-mcp` 风险。实测 7,496 条 active+isLatest 中没出现该 reverse-DNS 路径（实际是 `io.github.microsoft/playwright-mcp`），但出现了 **29 个真实 fuzzy match 候选**——registry 用 `<tld>.<owner>/<product>` 命名，而 catalog 用 `<owner>/<repo>` 命名，二者不能字符串严格相等却指向相似产品/同一组织。

### 真实样例（手动审核）

| # | registry server.name | catalog 已有 entry source_url | 是否同一仓库？ |
|---|---------------------|-------------------------------|--------------|
| 1 | `com.gitkraken/gk-cli` | `https://github.com/gitkraken/gk-cli` | ✅ 同一（io.github.* 严格匹配也命中） |
| 2 | `com.iunera/druid-mcp-server` | `https://github.com/iunera/druid-mcp-server` | ✅ 同一（同上） |
| 3 | `com.apify/apify-mcp-server` | `https://github.com/apify/mcp-server-rag-web-browser` `apify/actors-mcp-server` | ❌ apify 同 owner 但是不同 product（registry 是统一新 server，catalog 是历史 reference servers） |
| 4 | `com.keboola/mcp` | `https://github.com/keboola/keboola-mcp-server` | ⚠️ 极可能同一（产品命名差异：registry 用泛称 "mcp"，github 用 `keboola-mcp-server`） |
| 5 | `app.thoughtspot/mcp-server` | `https://github.com/thoughtspot/mcp-testing-kit` | ❌ 同 owner 不同 product |
| 6 | `com.microsoft/azure` `com.microsoft/microsoft-fabric` `com.microsoft/microsoft-learn-mcp` `com.microsoft/nuget` 等 12 条 | `https://github.com/microsoft/playwright-mcp` 等 5 条 | ❌ 全部同 owner 不同 product；microsoft.* 是 SaaS 注册名，无 GitHub 对应 |
| 7 | `io.github.webdriverio/mcp` | （catalog 无 webdriverio entry） | — 净新增 |

### fuzzy match 风险结论

- **同 owner 不同 product**：12+ 条（以 `com.microsoft/*` 为代表），如果做 owner-only fuzzy match 会**错误合并**。
- **同 owner 同 product 但命名差异**：少量（如 `keboola/mcp` vs `keboola-mcp-server`），手工识别需要"语义同义"判断。
- **结论：不要做 owner-only fuzzy match**。建议 `mcp_identity_key` **只做精确 (registry_name | github_owner_repo) 严格匹配**，把 reverse-DNS 名字与 GitHub URL 的归并交给后续 LLM enrichment（在 enrichment 阶段判断 `summary` 相似度，或者人工 curated 标注）。

---

## 5. 推荐的 `mcp_identity_key` 提取规则

基于上述实测，建议如下实现（design.md D6 的细化版）：

```python
def mcp_identity_key(entry: dict) -> tuple[str, str] | None:
    """
    返回 (kind, key) 二元组，None 表示无法提取（不参与跨源 dedup）。
    严格匹配，不做 fuzzy。
    """
    su = entry.get('source_url', '')

    # 1) registry URL 模式
    m = re.match(
        r'^https?://registry\.modelcontextprotocol\.io/v0/servers/(.+?)/?$',
        su
    )
    if m:
        registry_name = urllib.parse.unquote(m.group(1)).lower()
        # 同时尝试推断 GitHub ID，用于跨源 join
        gh = _registry_name_to_github_id(registry_name)
        if gh:
            return ('github', gh)  # 可与 GitHub URL 源 dedup
        return ('registry', registry_name)  # 商业/SaaS，独立 key

    # 2) GitHub URL 模式
    m = re.match(r'^https?://github\.com/([^/]+)/([^/?#]+)', su)
    if m:
        owner, repo = m.group(1).lower(), m.group(2).lower().replace('.git', '')
        return ('github', f'{owner}/{repo}')

    return None


def _registry_name_to_github_id(name: str) -> str | None:
    """
    仅处理 io.github.<owner>/<repo> 模式（registry 5,819/7,496 = 77.6%）。
    其他 reverse-DNS 模式不推断（避免误合并）。
    """
    m = re.match(r'^io\.github\.([^/]+)/(.+)$', name, re.IGNORECASE)
    if m:
        owner = m.group(1).lower()
        repo = m.group(2).lower()
        return f'{owner}/{repo}'
    return None
```

**测试用例**（写到 §4.5 单测中）：

| input | expected |
|-------|----------|
| `https://github.com/Microsoft/playwright-mcp` | `('github', 'microsoft/playwright-mcp')` |
| `https://registry.modelcontextprotocol.io/v0/servers/io.github.microsoft%2Fplaywright-mcp` | `('github', 'microsoft/playwright-mcp')` ← 与上一行可 join |
| `https://registry.modelcontextprotocol.io/v0/servers/com.microsoft%2Fazure` | `('registry', 'com.microsoft/azure')` ← 不可 join，独立保留 |
| `https://registry.modelcontextprotocol.io/v0/servers/ac.inference.sh%2Fmcp` | `('registry', 'ac.inference.sh/mcp')` ← 商业 SaaS，独立 |
| `https://github.com/iunera/druid-mcp-server` + registry 同名 | dedup 按 source_priority（registry=900 > mcp.so=700 / wong2=600） |

---

## 6. 进库条目数最终估算

### MCP

| 阶段 | 估算 |
|------|------|
| 现有 catalog/mcp | 1,633 |
| registry 新增（严格匹配后净新增） | +7,420 |
| **首次合并后** | **~8,950–9,050** |
| 上限（含部分 fuzzy 冗余） | ~9,100 |

design.md "Goals 5,000-8,000" 实际可能略高（~9K），但因为现有 1,633 中只有 76 与 registry 严格匹配，绝大多数是真实净新增；不是数据噪声。

### Rules

| 阶段 | 估算 |
|------|------|
| 现有 catalog/rules | 237 |
| windsurfrules 新增（合并去重后净新增） | +5 |
| **首次合并后** | **~242** |

design.md "Goals 500-800" **达不到**：windsurfrules 实测仅有 5 个真正独有的 slug。若要达成 500-800，需补 cursor.directory（spike §9）+ windsurf.com/editor/directory（spike §10）。本 change 主要价值是建立接入框架，规模目标须看 spike 结果。

### LLM 评估成本估算

- 新增 ~7,420 MCP entry × DeepSeek v4-flash 单条 ~$0.0008 ≈ **$5.9** 首次评估（design.md "$3-5" 略低估）
- 新增 ~5 windsurfrules entry，可忽略
- 总成本：~$6 首次，后续增量稳定 < $0.5/周（与 design.md D7 吻合）

---

## 7. 探针副产物

本次探针生成的临时文件（已落 `/tmp/`，不入仓）：

```
/tmp/mcp_registry_probe/all_servers.json    # 22,314 条全量
/tmp/mcp_registry_probe/active_latest.json  # 7,496 条过滤后
/tmp/mcp_registry_probe/borderline.json     # 1,670 条 reverse-DNS 边界
/tmp/windsurf_probe/results.json            # 两仓库 tree 数据
```

后续实施 §2/§3 时可参考这些文件做单测 fixture，但**不应**直接提交到仓库（CI 会跑实时 fetch）。

## 8. 影响 tasks.md 的事项

下列 tasks 需根据本基线调整（实施时修改）：

- **§2.7**（增量 diff）：registry 7,496 条 + 5,819 io.github 模式，diff 复用 skills.sh 增量模式无障碍
- **§4.4**（mcp_identity_key fuzzy）：**改方向**——不做 fuzzy，只做 io.github.* 严格映射 + registry SaaS 独立 key（详见本报告 §5）
- **§7.1**（覆盖率审计期望条目）：MCP 部分可加 `microsoft/playwright-mcp`、`anthropic/mcp` 等高识别度条目；rules 期望条目暂时只能从 `awesome-cursorrules` 名单选择（windsurfrules 仅 5 条净新增不足以撑期望集）
- **§11.2** 期望输出条数：写 **7,000–8,000**（实测 7,496）
- **§11.3** 期望输出条数：写 **100–110**（合并后 108）

## 9. 已知障碍 / 后续追踪

1. registry preview 阶段 schema 可能演化：本次未观察到 `server.repository.url` 字段（spec 提到），值得 §2.4 实现时优先用 `server.name` 推断而不依赖 `repository.url`
2. catalog 体积膨胀（1.6K → 9K MCP）会显著增加前端 catalog/index.json 体积。本 change 不处理；记 follow-up
3. balqaasem 仓库相对 SchneiderSam 没有任何独有内容，可考虑只接 SchneiderSam（但保留 balqaasem 作为 fallback 也无妨，成本相同）
