# build_catalog_bundle.py

把 `catalog/index.json` + `catalog-download/` 打成一个自洽的、下游可直接消费的 tarball。

设计目标：让下游（`costrict-web` 的 `CatalogIngestService` 等）一次 HTTPS GET 就能拿到完整数据，**不再依赖 git clone**。

## 使用

```bash
# 默认输出到 dist/catalog-bundle.tar.gz
python3 scripts/build_catalog_bundle.py

# 自定义输出路径
python3 scripts/build_catalog_bundle.py --output /tmp/foo.tar.gz

# 跳过 gzip 压缩（debug 用，体积大一倍但解压快）
python3 scripts/build_catalog_bundle.py --no-compress
```

## 产物布局

```
catalog-bundle.tar.gz
├── manifest.json
├── index.json                   ← 过滤后的 entries 数组
└── catalog-download/
    ├── mcp/<id>/.mcp.json
    ├── skills/<id>/SKILL.md     (+ references/, scripts/ 等附件)
    ├── plugins/<id>/.plugin.json
    ├── prompts/<id>/PROMPT.md
    └── rules/<id>/RULE.md
```

### manifest.json schema

| 字段 | 类型 | 说明 |
|---|---|---|
| `schema_version` | int | 当前 `1`。下游 `costrict-web` 拒绝执行未知版本，升级时需要下游同步更新 `SupportedBundleSchemaVersion` |
| `generated_at` | str | ISO-8601 UTC 时间戳，bundle 构造时刻 |
| `entry_count` | int | 过滤后 `index.json` 中 entries 数（也是 bundle 实际可用 entry 数） |
| `index_sha256` | str | 过滤后 `index.json` 内容的 sha256，下游可用来做 If-None-Match 短路 |
| `type_counts` | dict | `{type: count}` 各 item type 数量 |
| `filtered_from` | int | 原始 `catalog/index.json` 的 entry 数（过滤前） |
| `orphan_dropped` | int | 被 orphan filter 丢掉的数量（index 列了但 catalog-download/ 没文件） |
| `unknown_type_dropped` | int | 被 unknown type filter 丢掉的数量 |

## 过滤规则

bundle 不照搬 `catalog/index.json` 原始内容，而是跑三道过滤保证内外一致：

### 1. orphan_no_file

`merge_index.py` 写 index.json 时是从各 source 的 listing 拉的，可能列出 `download_catalog.py` 没成功抓到文件的 entry。bundle 用磁盘真实文件作为 ground truth，剔除孤儿。

> 注：`download_catalog.py` 末尾的 `_filter_top_index_to_downloaded` 已经做过同样的事，所以正常流水线跑完这道 filter 应当 drop=0。这里保留作为安全网，防止有人手动改 `catalog/index.json` 但忘了同步 download。

### 2. unknown_type

`type` 不在 `{mcp, skill, plugin, prompt, rule}` 范围内的 entry 丢掉。新加类型时要同步 `_PRIMARY_FILE_BY_TYPE`（download_catalog.py）和 `TYPE_DIR_AND_FILE`（本脚本）。

### 3. unusable_*（per-type 可用性检查）

| 子类型 | 检测 | 为什么丢 |
|---|---|---|
| `mcp_empty_stub` | `.mcp.json` 里所有 `mcpServers.<name>` 都缺 `command` 且缺 `url` | 下游 `NormalizeMCPMetadata` 严格要求至少一个传输方式，硬上 ingest 会失败。`registry.modelcontextprotocol.io` 上常见这种只有 listing 没有 install 的 stub |
| `md_yaml_broken` | `PROMPT.md` / `SKILL.md` / `RULE.md` 的 frontmatter 跑不通 `yaml.safe_load` | 下游 `ParseSKILLMD` 会失败。常见原因：description 字段里有未引号化的 `:` |

> bundle 默认用 PyYAML 真跑一次解析，没装 PyYAML 时回退到启发式（只能抓 description 里有 `: ` 的 case）。

## 与 download_catalog 的关系

```
download_catalog.py           build_catalog_bundle.py
─────────────────────         ────────────────────────
1. 各 source 抓文件           1. 读 catalog/index.json (download 阶段已 reconciliation)
2. 缺 install 信息直接拒写    2. 三道 filter (orphan / mcp_empty_stub / md_yaml_broken)
3. _filter_top_index_to_      3. 写 manifest.json + 过滤后 index.json
   downloaded 末尾回填 index      + catalog-download/ 整树
```

**职责分离**：
- `download_catalog` 负责"按 listing 抓文件 + 同步 index"，保证 `index.json` 永远不超出磁盘
- `build_catalog_bundle` 负责"打包 + 二次校验"，是给下游的最终产物

## 体积参考

基于 2026-05-21 数据：

| 阶段 | entries | 磁盘体积 |
|---|---|---|
| 原始 `catalog/index.json` | 9381 | 9 MB (JSON) |
| `download_catalog.py` 后 | 3576 | 100 MB (catalog-download/) |
| `build_catalog_bundle.py` 后 | 3325 | **33 MB tarball** |

下游一次拉就行，**比 git clone 170 MB 整历史快 5x 以上**。

## 故障

| 现象 | 原因 | 修法 |
|---|---|---|
| `missing catalog/index.json` | 没跑 `merge_index.py` | 先跑完整 sync 流水线 |
| `missing catalog-download/` | 没跑 `download_catalog.py` | 先跑下载 |
| `orphan_dropped` 数字很大 | `download_catalog.py` 的 reconciliation 没跑 / 失败 | 检查 download 输出末尾是否有 `Reconciled catalog/index.json` 日志 |
| 下游 ingest `incomplete > 0` | 有新的"上游数据 quality 问题"没被 filter 抓到 | 查 `INGEST_ERROR_LOG` 看 signature，加到本脚本的对应 filter |

## 相关代码

- `_entry_file` — type → 路径映射，与 `download_catalog.py::_PRIMARY_FILE_BY_TYPE` 严格一致
- `_mcp_is_empty_stub` — mcp 空 stub 检测
- `_has_broken_md_frontmatter` — md frontmatter YAML 校验
- 下游对应 service：`costrict-web/server/internal/services/catalog_ingest_service.go`
- 下游链路总览：`costrict-web/docs/CATALOG_INGEST.md`
