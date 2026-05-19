# AGENTS.md

Operating guidance for AI coding agents (Claude Code / Codex / Cursor / Opencode / Costrict / etc.) working in this repo.

## Project context

See `CLAUDE.md` for the architectural overview, commit conventions, test commands, and the data pipeline. Read it before making any non-trivial change.

## Do not commit `openspec/`

`openspec/changes/<name>/` is a working directory for proposals, designs, and tasks. It is intentionally ignored (`.gitignore:13 openspec/`) and should not be pushed to `origin/main`.

- When you scaffold a change with `/opsx:propose` or `openspec new change`, keep the resulting files local.
- Do NOT use `git add -f openspec/...` to bypass `.gitignore`.
- If you find tracked files under `openspec/` on `origin/main`, untrack them with `git rm --cached` in a maintenance commit — those are historical leakage from before this rule.
- The final spec ends up in code, tests, and `CLAUDE.md`. The change folder is a scratchpad, not the source of truth.

## Test files

`tests/` is also in `.gitignore` for historical reasons but a large set of files there *are* tracked (legacy state). When adding new tests:

- For pre-existing tracked test files: edit normally, they pick up changes.
- For brand-new test files: don't force-add — submit them as part of the change description / openspec change directory locally, so reviewers see the test coverage logic without polluting the tracked test surface. Production coverage that *must* run in CI should live under `ai-resource-eval/tests/` instead.

## Commit conventions

See `CLAUDE.md` § 提交规范. TL;DR: `[type] 中文描述`, single concern per commit, no `Co-Authored-By` unless explicitly collaborating.
