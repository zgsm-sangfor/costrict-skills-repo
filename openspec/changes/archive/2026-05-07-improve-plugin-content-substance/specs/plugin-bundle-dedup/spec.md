## ADDED Requirements

### Requirement: Sync scripts SHALL populate plugin `bundle` fields with substantive counts

`scripts/sync_plugins_official.py` and `scripts/sync_plugins_dev.py` SHALL invoke `PluginContentFetcher.detect_plugin_layout(repo, plugin_root)` (or equivalent layout detection) at sync time to compute real values for each plugin entry's `bundle.skills_count`, `bundle.agents_count`, `bundle.commands_count`, and `bundle.skills_namespaces`. The detection SHALL not fetch file contents; only the GitHub Tree API and path classification are required.

When the layout detector returns `is_plugin=False` (no `.claude-plugin/plugin.json` at the target sub-path), sync scripts SHALL write the entry with `bundle = {skills_count: 0, agents_count: 0, commands_count: 0, skills_namespaces: []}` (preserving the existing fallback shape).

#### Scenario: Anthropic marketplace plugin gets real skills_namespaces
- **WHEN** `sync_plugins_official.py` processes a plugin at `anthropics/claude-plugins-official/plugins/frontend-design`
- **THEN** the resulting entry's `bundle.skills_count` SHALL equal the number of `skills/<*>/SKILL.md` files under `plugins/frontend-design/`
- **AND THEN** `bundle.skills_namespaces` SHALL contain entries of the form `frontend-design:<skill-name>`

#### Scenario: Single-plugin repo gets root-level skills counted
- **WHEN** `sync_plugins_dev.py` processes a plugin whose `source_url` points to `obra/superpowers` (a single-plugin repo with `.claude-plugin/plugin.json` at root and 14 SKILL.md files)
- **THEN** the resulting entry's `bundle.skills_count` SHALL equal 14
- **AND THEN** `bundle.skills_namespaces` SHALL contain 14 entries

#### Scenario: Plugin shell without `.claude-plugin/plugin.json` keeps zeros
- **WHEN** a sync script processes a plugin entry whose source path lacks `.claude-plugin/plugin.json` (legacy / README-only shell)
- **THEN** the entry's `bundle.skills_count`, `agents_count`, `commands_count` SHALL be 0
- **AND THEN** `bundle.skills_namespaces` SHALL be `[]`

### Requirement: Layout detection in sync SHALL share the cache with evaluation

When `sync_plugins_official` or `sync_plugins_dev` calls the layout detector for a marketplace monorepo (e.g., `anthropics/claude-plugins-official` containing 50+ plugins), the underlying GitHub Tree API call SHALL be cached so that processing the second through Nth plugin in the same monorepo within the same sync invocation does not re-call the API. The cache MAY be a new dedicated cache or shared with `PluginContentFetcher`'s tree cache — implementation detail.

#### Scenario: Single tree call serves entire marketplace monorepo
- **WHEN** `sync_plugins_official.py` processes 50 plugins all under `anthropics/claude-plugins-official` in one run
- **THEN** the GitHub Tree API endpoint for that repo SHALL be called at most twice (once early to populate cache; one optional refresh path), not 50 times
- **AND THEN** sync time SHALL increase by at most a few seconds for the layout detection step (compared to without `bundle` filling)

## MODIFIED Requirements

### Requirement: Post-merge bundled_in soft annotation
After deduplication and before scoring governance, `scripts/merge_index.py` SHALL execute a post-merge step that scans `catalog/plugins/index.json` and, for each plugin entry, iterates over its `bundle.skills_namespaces`. For any skill entry in the merged catalog whose `id` or `namespace` matches an entry in that list, `merge_index.py` SHALL set `bundled_in: <plugin-id>` on the skill entry.

For this annotation to take effect, plugin entries' `bundle.skills_namespaces` MUST be populated with real namespace strings derived from the plugin's actual `skills/<name>/SKILL.md` paths. The sync layer (see ADDED requirement above) is responsible for populating these. When `bundle.skills_namespaces` is empty (legacy plugin shell or layout detection failure), the annotation step SHALL skip that plugin without error.

#### Scenario: Skill bundled by superpowers gets soft annotation
- **WHEN** `catalog/skills/index.json` contains a skill `brainstorming` whose namespace `superpowers:brainstorming` is listed in the `obra-superpowers` plugin entry's `bundle.skills_namespaces` (which itself is populated at sync time by the layout detector)
- **THEN** the merged `catalog/index.json` SHALL contain that skill entry with `bundled_in: "obra-superpowers"`

#### Scenario: Annotation produces non-zero results when bundle fields are populated
- **WHEN** at least 100 plugin entries have non-empty `bundle.skills_namespaces` after sync
- **THEN** the post-merge step SHALL set `bundled_in` on at least 100 skill entries (assuming each plugin's namespaces match at least one catalog skill)
- **AND THEN** the log line SHALL report a non-zero "annotated <M> skills" count

#### Scenario: Skill not bundled retains no annotation
- **WHEN** a skill entry's namespace is not listed in any plugin's `bundle.skills_namespaces`
- **THEN** the entry SHALL NOT contain a `bundled_in` field (or SHALL contain `bundled_in: null`)

#### Scenario: Plugin without skills_namespaces does not break the step
- **WHEN** a plugin entry is missing `bundle.skills_namespaces` or has an empty array
- **THEN** the post-merge step SHALL skip that plugin without modifying any skill entries and SHALL log a DEBUG line
