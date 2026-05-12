"""Tests for ai_resource_eval.fetcher.github — GitHubFetcher URL parsing."""

from __future__ import annotations

import pytest

from ai_resource_eval.fetcher.github import GitHubFetcher


# ---------------------------------------------------------------------------
# _extract_owner_repo
# ---------------------------------------------------------------------------


class TestExtractOwnerRepo:
    """Verify URL parsing extracts owner, repo, ref, and subpath correctly."""

    def test_plain_repo_url(self) -> None:
        result = GitHubFetcher._extract_owner_repo(
            "https://github.com/owner/repo"
        )
        assert result == ("owner", "repo", "HEAD", "")

    def test_repo_with_trailing_slash(self) -> None:
        result = GitHubFetcher._extract_owner_repo(
            "https://github.com/owner/repo/"
        )
        # Regex anchors at the repo segment; trailing slash is ignored.
        assert result is not None
        owner, repo, ref, subpath = result
        assert owner == "owner"
        assert repo == "repo"

    def test_tree_url_with_ref_and_subpath(self) -> None:
        result = GitHubFetcher._extract_owner_repo(
            "https://github.com/modelcontextprotocol/servers/tree/main/src/filesystem"
        )
        assert result == ("modelcontextprotocol", "servers", "main", "src/filesystem")

    def test_tree_url_with_deep_subpath(self) -> None:
        result = GitHubFetcher._extract_owner_repo(
            "https://github.com/owner/repo/tree/develop/packages/core/src"
        )
        assert result == ("owner", "repo", "develop", "packages/core/src")

    def test_blob_url(self) -> None:
        result = GitHubFetcher._extract_owner_repo(
            "https://github.com/owner/repo/blob/main/README.md"
        )
        assert result == ("owner", "repo", "main", "README.md")

    def test_tree_url_ref_only_no_subpath(self) -> None:
        result = GitHubFetcher._extract_owner_repo(
            "https://github.com/owner/repo/tree/v2.0"
        )
        assert result == ("owner", "repo", "v2.0", "")

    def test_dot_git_suffix_stripped(self) -> None:
        result = GitHubFetcher._extract_owner_repo(
            "https://github.com/owner/repo.git"
        )
        assert result is not None
        assert result[1] == "repo"

    def test_non_github_url_returns_none(self) -> None:
        result = GitHubFetcher._extract_owner_repo(
            "https://gitlab.com/owner/repo"
        )
        assert result is None

    def test_trailing_slash_on_subpath_stripped(self) -> None:
        result = GitHubFetcher._extract_owner_repo(
            "https://github.com/owner/repo/tree/main/src/filesystem/"
        )
        assert result is not None
        assert result[3] == "src/filesystem"


# ---------------------------------------------------------------------------
# fetch — URL construction (mocked HTTP)
# ---------------------------------------------------------------------------


class TestFetchURLConstruction:
    """Verify that fetch() builds the correct raw.githubusercontent.com URLs."""

    def test_plain_repo_url_uses_head(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A bare repo URL should request HEAD/<content_path>."""
        requested_urls: list[str] = []

        class FakeResponse:
            status_code = 200
            text = "# Hello"

        class FakeClient:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

            def get(self, url):
                requested_urls.append(url)
                return FakeResponse()

        import ai_resource_eval.fetcher.github as mod

        monkeypatch.setattr(mod.httpx, "Client", lambda **kw: FakeClient())

        fetcher = GitHubFetcher()
        fetcher.fetch("https://github.com/owner/repo")

        assert requested_urls == [
            "https://raw.githubusercontent.com/owner/repo/HEAD/README.md"
        ]

    def test_tree_url_includes_ref_and_subpath(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A tree URL with ref/subpath should embed them in the raw URL."""
        requested_urls: list[str] = []

        class FakeResponse:
            status_code = 200
            text = "# Filesystem MCP"

        class FakeClient:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

            def get(self, url):
                requested_urls.append(url)
                return FakeResponse()

        import ai_resource_eval.fetcher.github as mod

        monkeypatch.setattr(mod.httpx, "Client", lambda **kw: FakeClient())

        fetcher = GitHubFetcher()
        fetcher.fetch(
            "https://github.com/modelcontextprotocol/servers/tree/main/src/filesystem"
        )

        assert requested_urls == [
            "https://raw.githubusercontent.com/modelcontextprotocol/servers/main/src/filesystem/README.md"
        ]

    def test_custom_content_paths_with_subpath(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Multiple content_paths should each be appended after the subpath prefix."""
        requested_urls: list[str] = []

        class FakeResponse:
            status_code = 404
            text = ""

        class FakeClient:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

            def get(self, url):
                requested_urls.append(url)
                return FakeResponse()

        import ai_resource_eval.fetcher.github as mod

        monkeypatch.setattr(mod.httpx, "Client", lambda **kw: FakeClient())

        fetcher = GitHubFetcher(content_paths=["README.md", "SKILL.md"])
        result = fetcher.fetch(
            "https://github.com/owner/repo/tree/develop/packages/core"
        )

        assert result is None
        assert requested_urls == [
            "https://raw.githubusercontent.com/owner/repo/develop/packages/core/README.md",
            "https://raw.githubusercontent.com/owner/repo/develop/packages/core/SKILL.md",
        ]


# ---------------------------------------------------------------------------
# _slugify_heading + _extract_section
# ---------------------------------------------------------------------------


class TestSlugifyHeading:
    """GitHub anchor algorithm: per-space → dash, no dash collapse.

    Regression guard for f/prompts.chat headings whose URL fragments contain
    consecutive dashes derived from ``Foo - Bar`` (literal space-dash-space)
    or ``Foo & Bar`` (& stripped, surrounding spaces preserved).
    """

    def test_plain_heading(self) -> None:
        assert GitHubFetcher._slugify_heading("## Ethereum Developer") == "ethereum-developer"

    def test_heading_with_literal_dash_preserves_triple(self) -> None:
        # " - " has space-dash-space → "---" per GitHub
        result = GitHubFetcher._slugify_heading(
            "## Academic Paper Figure Generator - Nano Banana Pro"
        )
        assert result == "academic-paper-figure-generator---nano-banana-pro"

    def test_heading_with_ampersand_preserves_double(self) -> None:
        # " & " → ampersand stripped, surrounding spaces remain → "--"
        result = GitHubFetcher._slugify_heading(
            "## AI Performance & Deep Testing Engineer"
        )
        assert result == "ai-performance--deep-testing-engineer"

    def test_heading_with_colon_strips_punct(self) -> None:
        # ":" stripped, surrounding space → "--"
        result = GitHubFetcher._slugify_heading("## AI2SQL: SQL Model & Query Generator")
        assert result == "ai2sql-sql-model--query-generator"

    def test_heading_with_parens(self) -> None:
        # "(" ")" stripped, surrounding spaces preserved
        result = GitHubFetcher._slugify_heading("## Foo (Bar)")
        # " (" → space + stripped paren = 1 space; ")" trailing stripped.
        # Result: "foo-bar"
        assert result == "foo-bar"

    def test_existing_dash_in_word_not_doubled(self) -> None:
        # "AI-Powered" has a single dash inside word — should stay single
        result = GitHubFetcher._slugify_heading("## AI-Powered Tools")
        assert result == "ai-powered-tools"


class TestExtractSection:
    """End-to-end: given full PROMPTS.md-style content + a real GitHub anchor
    slug (with consecutive dashes), extract the matching section."""

    def test_extracts_section_with_triple_dash_anchor(self) -> None:
        text = (
            "# Awesome ChatGPT Prompts\n\n"
            "## Ethereum Developer\n\n"
            "First section content.\n\n"
            "## Academic Paper Figure Generator - Nano Banana Pro\n\n"
            "Target section content here.\n\n"
            "## Linux Terminal\n\n"
            "Third section.\n"
        )
        result = GitHubFetcher._extract_section(
            text, "academic-paper-figure-generator---nano-banana-pro"
        )
        assert result is not None
        assert "Academic Paper Figure Generator - Nano Banana Pro" in result
        assert "Target section content here." in result
        # Should not bleed into next section
        assert "Linux Terminal" not in result

    def test_extracts_section_with_double_dash_anchor(self) -> None:
        text = (
            "## AI Performance & Deep Testing Engineer\n\n"
            "Body text.\n\n"
            "## Next Section\n"
        )
        result = GitHubFetcher._extract_section(
            text, "ai-performance--deep-testing-engineer"
        )
        assert result is not None
        assert "Body text." in result

    def test_missing_anchor_returns_none(self) -> None:
        text = "## Ethereum Developer\n\nContent.\n"
        assert (
            GitHubFetcher._extract_section(text, "nonexistent-slug")
            is None
        )
