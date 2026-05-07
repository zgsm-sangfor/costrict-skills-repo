"""Tests for ai_resource_eval.fetcher.plugin — PluginContentFetcher.

Layouts under test (mocked GitHub Tree API + raw fetches):

* L1: marketplace monorepo with ``plugins/<name>/`` subdir
* L2: single plugin at repo root
* L3: root plugin bundling many SKILL.md files
* L4: dev monorepo with arbitrary subdir naming
* edge: target sub-path without ``plugin.json`` → ``is_plugin=False``

Plus: size_cap fallback, shadow directory exclusion, tree cache reuse, raw
cache reuse, tree truncation warning, manifest-name-based root namespace.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Iterable

import httpx
import pytest

from ai_resource_eval.fetcher.plugin import PluginContentFetcher, PluginLayout


# ---------------------------------------------------------------------------
# Fake httpx.Client
# ---------------------------------------------------------------------------


class _Response:
    def __init__(self, status_code: int, text: str = "", json_payload: Any = None) -> None:
        self.status_code = status_code
        self.text = text
        self._json = json_payload

    def json(self) -> Any:
        if self._json is not None:
            return self._json
        return json.loads(self.text)


class FakeClient:
    """Minimal stand-in for ``httpx.Client``.

    Routes GET requests through a list of ``(predicate, response_factory)``
    handlers and records every URL hit so tests can assert call counts.
    """

    def __init__(self) -> None:
        self.calls: list[str] = []
        self._handlers: list[tuple[Any, Any]] = []

    def add_handler(self, predicate, response_factory) -> None:
        self._handlers.append((predicate, response_factory))

    def get(self, url: str, headers: dict | None = None) -> _Response:
        self.calls.append(url)
        for predicate, factory in self._handlers:
            if predicate(url):
                return factory(url)
        return _Response(404, "")

    def close(self) -> None:
        pass


def _tree_blobs(paths: Iterable[str], truncated: bool = False) -> dict:
    """Synthesize a GitHub Tree API recursive=true response."""
    return {
        "tree": [{"path": p, "type": "blob"} for p in paths],
        "truncated": truncated,
    }


def _tree_url(repo: str, ref: str = "HEAD") -> str:
    return f"https://api.github.com/repos/{repo}/git/trees/{ref}?recursive=1"


def _raw_url(repo: str, ref: str, path: str) -> str:
    return f"https://raw.githubusercontent.com/{repo}/{ref}/{path}"


def _wire(client: FakeClient, repo: str, paths: list[str], **raw_files: str) -> None:
    """Register a tree response for ``repo`` and any keyword raw files."""
    client.add_handler(
        (lambda url, repo=repo: url == _tree_url(repo)),
        lambda url, paths=paths: _Response(200, json_payload=_tree_blobs(paths)),
    )
    for relpath, content in raw_files.items():
        # raw_files is keyed by repo-relative path with "/" replaced by "__"
        path = relpath.replace("__", "/")
        client.add_handler(
            (lambda url, repo=repo, path=path: url == _raw_url(repo, "HEAD", path)),
            lambda url, content=content: _Response(200, content),
        )


# ---------------------------------------------------------------------------
# Layout detection — five layouts
# ---------------------------------------------------------------------------


class TestLayoutDetection:
    """Verify ``detect_plugin_layout`` correctly classifies files for each layout."""

    def test_l1_marketplace_subdir(self) -> None:
        """L1: ``plugins/<name>/`` subdir under a marketplace monorepo."""
        client = FakeClient()
        repo = "anthropics/claude-plugins-official"
        paths = [
            "plugins/frontend-design/.claude-plugin/plugin.json",
            "plugins/frontend-design/skills/aesthetics/SKILL.md",
            "plugins/frontend-design/agents/critic.md",
            "plugins/other/.claude-plugin/plugin.json",
            "plugins/other/skills/x/SKILL.md",
        ]
        _wire(client, repo, paths)
        fetcher = PluginContentFetcher(http_client=client)

        layout = fetcher.detect_plugin_layout(repo, "plugins/frontend-design")

        assert layout.is_plugin is True
        assert layout.plugin_root == "plugins/frontend-design"
        assert layout.plugin_json_path == "plugins/frontend-design/.claude-plugin/plugin.json"
        assert layout.skill_paths == [
            "plugins/frontend-design/skills/aesthetics/SKILL.md",
        ]
        assert layout.agent_paths == ["plugins/frontend-design/agents/critic.md"]
        assert layout.command_paths == []
        assert layout.skills_namespaces == ["frontend-design:aesthetics"]

    def test_l2_root_plugin(self) -> None:
        """L2: ``.claude-plugin/plugin.json`` lives at repo root."""
        client = FakeClient()
        repo = "mongodb/agent-skills"
        paths = [
            ".claude-plugin/plugin.json",
            "skills/atlas/SKILL.md",
            "skills/streams/SKILL.md",
        ]
        manifest = json.dumps({"name": "agent-skills", "version": "1.0.0"})
        _wire(
            client,
            repo,
            paths,
            **{".claude-plugin__plugin.json": manifest},
        )
        fetcher = PluginContentFetcher(http_client=client)

        layout = fetcher.detect_plugin_layout(repo, "")

        assert layout.is_plugin is True
        assert layout.plugin_root == ""
        assert layout.plugin_json_path == ".claude-plugin/plugin.json"
        assert layout.skill_paths == [
            "skills/atlas/SKILL.md",
            "skills/streams/SKILL.md",
        ]
        # Manifest-name-based namespace (NOT literal "plugin").
        assert layout.skills_namespaces == [
            "agent-skills:atlas",
            "agent-skills:streams",
        ]

    def test_l3_root_plugin_with_many_skills(self) -> None:
        """L3: large root plugin with many SKILL.md files (e.g. obra/superpowers)."""
        client = FakeClient()
        repo = "obra/superpowers"
        skill_dirs = [
            "brainstorming",
            "test-driven-development",
            "subagent-driven-development",
            "verification-before-completion",
            "writing-plans",
        ]
        paths = [".claude-plugin/plugin.json"]
        paths.extend(f"skills/{d}/SKILL.md" for d in skill_dirs)
        manifest = json.dumps({"name": "superpowers"})
        _wire(client, repo, paths, **{".claude-plugin__plugin.json": manifest})
        fetcher = PluginContentFetcher(http_client=client)

        layout = fetcher.detect_plugin_layout(repo, "")

        assert layout.is_plugin is True
        assert len(layout.skill_paths) == 5
        assert all(ns.startswith("superpowers:") for ns in layout.skills_namespaces)

    def test_l4_dev_monorepo_arbitrary_naming(self) -> None:
        """L4: dev monorepo with non-`plugins/` subdirectory naming."""
        client = FakeClient()
        repo = "alirezarezvani/claude-skills"
        paths = [
            "business-growth/.claude-plugin/plugin.json",
            "business-growth/skills/funnel/SKILL.md",
            "business-growth/commands/launch.md",
            "other-area/.claude-plugin/plugin.json",
        ]
        _wire(client, repo, paths)
        fetcher = PluginContentFetcher(http_client=client)

        layout = fetcher.detect_plugin_layout(repo, "business-growth")

        assert layout.is_plugin is True
        assert layout.plugin_root == "business-growth"
        assert layout.skill_paths == ["business-growth/skills/funnel/SKILL.md"]
        assert layout.command_paths == ["business-growth/commands/launch.md"]
        assert layout.skills_namespaces == ["business-growth:funnel"]

    def test_edge_no_plugin_json_returns_is_plugin_false(self) -> None:
        """Sub-path without ``.claude-plugin/plugin.json`` → ``is_plugin=False``."""
        client = FakeClient()
        repo = "anthropics/claude-plugins-official"
        paths = [
            "plugins/clangd-lsp/README.md",
            "plugins/other/.claude-plugin/plugin.json",
        ]
        _wire(client, repo, paths)
        fetcher = PluginContentFetcher(http_client=client)

        layout = fetcher.detect_plugin_layout(repo, "plugins/clangd-lsp")

        assert layout.is_plugin is False
        assert layout.plugin_json_path == ""
        assert layout.skill_paths == []


# ---------------------------------------------------------------------------
# Shadow-directory exclusion
# ---------------------------------------------------------------------------


class TestShadowDirectoryExclusion:
    """``.codex/``, ``.gemini/``, ``.github/`` etc. must not appear in plugin content."""

    def test_codex_gemini_github_excluded(self) -> None:
        client = FakeClient()
        repo = "trailofbits/skills"
        paths = [
            "plugins/foo/.claude-plugin/plugin.json",
            "plugins/foo/skills/real/SKILL.md",
            ".codex/skills/gh-cli/SKILL.md",
            ".gemini/skills/leak/SKILL.md",
            ".github/workflows/ci.yml",
            "plugins/foo/.github/CODEOWNERS",
        ]
        _wire(client, repo, paths)
        fetcher = PluginContentFetcher(http_client=client)

        layout = fetcher.detect_plugin_layout(repo, "plugins/foo")

        assert layout.skill_paths == ["plugins/foo/skills/real/SKILL.md"]
        # No ``.codex`` / ``.gemini`` / ``.github`` paths leak into agents or commands.
        for collection in (layout.agent_paths, layout.command_paths):
            assert all(".codex" not in p and ".gemini" not in p and ".github" not in p
                       for p in collection)


# ---------------------------------------------------------------------------
# Tree truncation
# ---------------------------------------------------------------------------


class TestTreeTruncation:
    """When GitHub returns ``truncated=true`` the fetcher logs a WARNING."""

    def test_truncated_logs_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        client = FakeClient()
        repo = "huge/monorepo"
        client.add_handler(
            (lambda url, repo=repo: url == _tree_url(repo)),
            lambda url: _Response(
                200,
                json_payload={
                    "tree": [
                        {"path": ".claude-plugin/plugin.json", "type": "blob"},
                    ],
                    "truncated": True,
                },
            ),
        )
        fetcher = PluginContentFetcher(http_client=client)

        with caplog.at_level(logging.WARNING, logger="ai_resource_eval.fetcher.plugin"):
            fetcher.detect_plugin_layout(repo, "")

        assert any("truncated" in rec.message.lower() for rec in caplog.records)


# ---------------------------------------------------------------------------
# Caches: tree (per repo,ref) and raw (per URL)
# ---------------------------------------------------------------------------


class TestCaches:
    def test_tree_cache_hit_across_plugins(self) -> None:
        """Two plugins in the same repo trigger one Tree API call."""
        client = FakeClient()
        repo = "anthropics/claude-plugins-official"
        paths = [
            "plugins/a/.claude-plugin/plugin.json",
            "plugins/a/skills/x/SKILL.md",
            "plugins/b/.claude-plugin/plugin.json",
            "plugins/b/agents/y.md",
        ]
        _wire(
            client,
            repo,
            paths,
            **{
                "plugins__a__.claude-plugin__plugin.json": "{}",
                "plugins__a__skills__x__SKILL.md": "---\nname: x\n---\n# X",
                "plugins__b__.claude-plugin__plugin.json": "{}",
                "plugins__b__agents__y.md": "agent",
            },
        )
        fetcher = PluginContentFetcher(http_client=client)

        fetcher.fetch(f"https://github.com/{repo}/tree/HEAD/plugins/a")
        fetcher.fetch(f"https://github.com/{repo}/tree/HEAD/plugins/b")

        tree_calls = [u for u in client.calls if u == _tree_url(repo)]
        assert len(tree_calls) == 1

    def test_raw_cache_hit_for_same_url(self) -> None:
        """Calling ``fetch`` twice for the same source_url hits raw cache."""
        client = FakeClient()
        repo = "owner/repo"
        paths = [
            ".claude-plugin/plugin.json",
            "skills/one/SKILL.md",
        ]
        _wire(
            client,
            repo,
            paths,
            **{
                ".claude-plugin__plugin.json": '{"name": "one-plugin"}',
                "skills__one__SKILL.md": "---\nname: one\n---\n# One",
            },
        )
        fetcher = PluginContentFetcher(http_client=client)

        url = f"https://github.com/{repo}"
        first = fetcher.fetch(url)
        second = fetcher.fetch(url)

        assert first is not None and second is not None
        assert first == second

        # The raw plugin.json should have been requested at most twice across
        # the two fetch calls (once for the namespace derivation, once for
        # normalisation — both first call) and zero times during the second.
        plugin_json_url = _raw_url(repo, "HEAD", ".claude-plugin/plugin.json")
        skill_url = _raw_url(repo, "HEAD", "skills/one/SKILL.md")
        # After two fetch calls, each raw URL appears at most once because of
        # the URL cache.
        assert client.calls.count(plugin_json_url) == 1
        assert client.calls.count(skill_url) == 1


# ---------------------------------------------------------------------------
# size_cap fallback
# ---------------------------------------------------------------------------


class TestSizeCapFallback:
    """Large bundles trigger frontmatter+800-char fallback past the first 5 files."""

    def test_size_cap_truncates_files_past_first_five(self) -> None:
        client = FakeClient()
        repo = "huge/plugin"
        # 10 SKILLs each weighing ~150KB → 1.5MB raw, well over the 600KB cap.
        # Cap kicks in after the first ~4 full files; ``or i < 5`` then forces
        # the 5th still-full and abbreviates the rest.
        skill_count = 10
        bulk = "X" * 150_000  # 150KB body per skill
        skill_paths = [f"skills/skill-{i:02d}/SKILL.md" for i in range(skill_count)]
        paths = [".claude-plugin/plugin.json", *skill_paths]

        client.add_handler(
            (lambda url, repo=repo: url == _tree_url(repo)),
            lambda url, paths=paths: _Response(200, json_payload=_tree_blobs(paths)),
        )
        client.add_handler(
            (lambda url, repo=repo: url == _raw_url(repo, "HEAD", ".claude-plugin/plugin.json")),
            lambda url: _Response(200, '{"name": "huge-plugin"}'),
        )
        for path in skill_paths:
            text = f"---\nname: {path}\ndescription: a skill\n---\n\n{bulk}"
            client.add_handler(
                (lambda url, repo=repo, path=path: url == _raw_url(repo, "HEAD", path)),
                lambda url, text=text: _Response(200, text),
            )

        fetcher = PluginContentFetcher(http_client=client)
        result = fetcher.fetch(f"https://github.com/{repo}")
        assert result is not None
        content, _ = result

        # First 5 SKILLs included in full (each with bulk body present).
        for i in range(5):
            marker = f"## skills/skill-{i:02d}/SKILL.md"
            assert marker in content
            section_start = content.index(marker)
            section_end = content.index("\n## ", section_start + 1) if i < skill_count - 1 else len(content)
            section = content[section_start:section_end]
            assert "X" * 1000 in section, f"skill {i} should have bulk body"

        # Files 5..9 must be abbreviated: their section length is much smaller
        # than the full 80KB body.
        for i in range(5, skill_count):
            marker = f"## skills/skill-{i:02d}/SKILL.md"
            assert marker in content
            section_start = content.index(marker)
            section_end = (
                content.index("\n## ", section_start + 1)
                if i < skill_count - 1
                else len(content)
            )
            section = content[section_start:section_end]
            # Frontmatter retained.
            assert "name: skills/skill-" in section
            # Abbreviated body cap is 800 chars; allow generous slack for
            # frontmatter + heading.
            assert len(section) < 3_000, (
                f"skill {i} should be abbreviated, got {len(section)} chars"
            )


# ---------------------------------------------------------------------------
# Fallback path
# ---------------------------------------------------------------------------


class TestFallback:
    def test_fetch_returns_none_when_no_plugin_json(self) -> None:
        client = FakeClient()
        repo = "anthropics/claude-plugins-official"
        paths = [
            "plugins/clangd-lsp/README.md",
            "plugins/other/.claude-plugin/plugin.json",
        ]
        _wire(client, repo, paths)
        fetcher = PluginContentFetcher(http_client=client)

        result = fetcher.fetch(
            f"https://github.com/{repo}/tree/main/plugins/clangd-lsp"
        )

        assert result is None

    def test_fetch_returns_none_for_non_github_url(self) -> None:
        fetcher = PluginContentFetcher(http_client=FakeClient())
        assert fetcher.fetch("https://gitlab.com/foo/bar") is None


# ---------------------------------------------------------------------------
# Manifest-name-based namespace
# ---------------------------------------------------------------------------


class TestRootNamespaceFromManifest:
    def test_root_plugin_uses_manifest_name(self) -> None:
        client = FakeClient()
        repo = "owner/myrepo"
        paths = [
            ".claude-plugin/plugin.json",
            "skills/foo/SKILL.md",
        ]
        manifest = json.dumps({"name": "my-cool-plugin", "version": "0.1"})
        _wire(
            client,
            repo,
            paths,
            **{".claude-plugin__plugin.json": manifest},
        )
        fetcher = PluginContentFetcher(http_client=client)

        layout = fetcher.detect_plugin_layout(repo, "")

        assert layout.skills_namespaces == ["my-cool-plugin:foo"]

    def test_root_plugin_falls_back_to_repo_name(self) -> None:
        """When ``plugin.json`` lacks ``name`` field, namespace uses repo basename."""
        client = FakeClient()
        repo = "owner/awesome-repo"
        paths = [
            ".claude-plugin/plugin.json",
            "skills/foo/SKILL.md",
        ]
        manifest = json.dumps({"version": "0.1"})  # no name
        _wire(
            client,
            repo,
            paths,
            **{".claude-plugin__plugin.json": manifest},
        )
        fetcher = PluginContentFetcher(http_client=client)

        layout = fetcher.detect_plugin_layout(repo, "")

        assert layout.skills_namespaces == ["awesome-repo:foo"]


# ---------------------------------------------------------------------------
# PluginLayout dataclass plumbing (smoke test)
# ---------------------------------------------------------------------------


def test_plugin_layout_default_is_not_plugin() -> None:
    layout = PluginLayout(is_plugin=False)
    assert layout.skill_paths == []
    assert layout.agent_paths == []
    assert layout.command_paths == []
    assert layout.skills_namespaces == []
