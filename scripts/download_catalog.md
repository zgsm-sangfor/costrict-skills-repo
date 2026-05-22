# download_catalog.py

将 `everything-ai-coding` catalog 中的条目下载到本地文件夹，格式参考 `awesome-claude-skills-master`。

## 功能概述

脚本读取 `catalog/` 下的四类索引文件：

| 类型 | 索引文件 | 条目数（参考） | 输出格式 |
|------|----------|---------------|----------|
| skills | `catalog/skills/index.json` | ~1671 | `skills/<name>/SKILL.md` + 递归附件 |
| mcp | `catalog/mcp/index.json` | ~1631 | `mcp/<name>/.mcp.json` |
| rules | `catalog/rules/index.json` | ~232 | `rules/<name>/RULE.md` + `.cursorrules` |
| prompts | `catalog/prompts/index.json` | ~541 | `prompts/<name>/PROMPT.md` |

## 使用方法

```bash
# 下载全部类型到 catalog-download/
python scripts/download_catalog.py

# 只下载 skills 和 mcp
python scripts/download_catalog.py --types skills,mcp

# 指定输出目录
python scripts/download_catalog.py --output ./my-catalog

# 强制覆盖已有文件
python scripts/download_catalog.py --force

# 提高并发数（默认 8，注意 GitHub 速率限制）
python scripts/download_catalog.py --workers 16
```

### CLI 参数

| 参数 | 简写 | 默认值 | 说明 |
|------|------|--------|------|
| `--output` | `-o` | `catalog-download/` | 输出根目录 |
| `--types` | `-t` | `skills,mcp,rules,prompts` | 要下载的类型，逗号分隔 |
| `--force` | `-f` | `false` | 强制覆盖已存在的文件 |
| `--workers` | `-w` | `8` | 并发下载 worker 数 |

## 实现机制

### Skills — 递归下载附件

1. **提取 repo 信息**：从 `install.repo`、`install.branch`、`install.files` / `install.path` 解析 GitHub 仓库地址和 skill 目录路径。
2. **预加载 Tree API**：按 **repo + branch** 分组，每个 repo 只调用一次 `repos/{repo}/git/trees/{branch}?recursive=1`，获取该仓库下所有 blob 文件路径。避免 1671 个 skill 重复请求。
3. **筛选文件**：根据 skill 目录前缀（如 `skills/algorithmic-art/`）从 tree 中筛选出属于该 skill 的所有文件。
4. **递归下载**：逐个下载筛选出的文件，保持相对目录结构保存到本地。
5. **SKILL.md 处理**：若下载的原始 SKILL.md 缺少 YAML frontmatter，自动注入 `name`、`description`、`category`。
6. **回退策略**：当 repo 信息缺失或 Tree API 失败时，用 catalog 元数据生成最小 SKILL.md。

### MCP — 生成配置

直接根据 `install.config` 生成 `.mcp.json`，格式为：

```json
{
  "mcpServers": {
    "MCP 名称": { "command": "...", "args": [...] }
  }
}
```

**install info gating**（自 catalog-bundle 重构起）：`install.config` 既缺 `command` 也缺 `url` 时，**不写文件**直接返回失败（错误信息 `no install info (missing command and url)`）。该 entry 会在末尾 reconciliation pass 中从顶层 `catalog/index.json` 剔除。原因：`registry.modelcontextprotocol.io` 等 source 的 listing 经常只有 server 名字没有 install 命令，硬写成 `mcpServers: {"<name>": {}}` 空 stub 后下游 `costrict-web` 的 `NormalizeMCPMetadata` 会拒收，徒增噪音。

### Rules — 下载原始规则

根据 `install.files` 中的 `.cursorrules` URL 下载原始内容，同时生成 `RULE.md`（包装为带 frontmatter 的 Markdown 代码块，方便阅读）。

### Prompts — 解析共享 CSV

1. **共享源缓存**：`prompts-chat` 源的所有 536 个 prompt 共享同一个 `prompts.csv`。脚本只下载一次该 CSV，解析后缓存到内存。
2. **按名称匹配**：根据 catalog 条目中的 `name` 在 CSV 行中匹配 `act` / `title` 列，提取对应的 `prompt` 文本。
3. **回退策略**：无法从 CSV 匹配时，使用 catalog 中的 `description` 生成最小 PROMPT.md。

## 输出目录结构

```
catalog-download/
├── skills/
│   ├── algorithmic-art-skill/
│   │   ├── SKILL.md
│   │   ├── LICENSE.txt
│   │   └── templates/
│   │       ├── viewer.html
│   │       └── generator_template.js
│   ├── canvas-design-skill/
│   │   ├── SKILL.md
│   │   ├── LICENSE.txt
│   │   └── canvas-fonts/
│   │       ├── ArsenalSC-Regular.ttf
│   │       └── ...
│   └── claude-api-skill/
│       ├── SKILL.md
│       ├── LICENSE.txt
│       ├── python/
│       │   └── claude-api/
│       │       ├── README.md
│       │       └── tool-use.md
│       └── typescript/
│           └── claude-api/
│               └── README.md
├── mcp/
│   ├── blender/
│   │   └── .mcp.json
│   └── github/
│       └── .mcp.json
├── rules/
│   └── angular-typescript-cursorrules/
│       ├── RULE.md
│       └── .cursorrules
└── prompts/
    └── ethereum-developer/
        └── PROMPT.md
```

## 增量更新

默认行为是**增量更新**：

- 若目标文件已存在且大小大于 0，直接跳过。
- 重复执行脚本不会覆盖已有内容，只会补充新增或上次失败的条目。
- 使用 `--force` 可强制重新下载全部内容。

## Reconciliation：保证 index.json 与磁盘一致

`run()` 末尾会跑一次 `_filter_top_index_to_downloaded`，做的事：

1. 读现有 `catalog/index.json`（顶层 9000+ entries，由 `merge_index.py` 写入）
2. 遍历每个 entry，按 `_PRIMARY_FILE_BY_TYPE` 算出预期文件路径
3. 文件实际存在 → 保留 entry；不存在 → 丢掉
4. 用过滤后的列表原子重写 `catalog/index.json`

为什么需要这一步：`merge_index.py` 写 index.json 用的是上游各 source 的 listing 元数据，而 `download_catalog.py` 抓单条文件时可能因为 raw 404 / 仓库已删除 / 速率限制 / 我们的 mcp gating 等原因失败。没有这道对账，**catalog-download/ 永远是 index.json 的真子集**，所有下游消费者都要各自重新发现这套孤儿，徒增重复检查。

输出示例：

```
INFO: Reconciled catalog/index.json: kept 3576 entries with on-disk files, dropped 5805 orphan entries.
```

**这是写回操作**——会修改 git 跟踪的 `catalog/index.json`。CI 流水线后续 `git commit` 会带上这次过滤。下次 sync 时 `merge_index.py` 又会从源 listing 重新发现这些 entry，所以**单次失败不会永久丢信息**。

## 错误处理

- **单条失败不影响整体**：某个 skill / mcp / rule / prompt 下载失败时，记录错误并继续处理其他条目。
- **错误日志**：所有失败记录写入 `catalog-download/download_errors.log`。
- **网络容错**：对 GitHub raw 的请求带 3 次指数退避重试，单个文件失败不会阻断同一 skill 的其他附件下载。
- **速率控制**：每个 worker 在处理条目之间有 `0.15s` 间隔，降低触发 GitHub 速率限制的概率。
