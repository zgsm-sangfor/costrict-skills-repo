"""Tests for deduplicate() — ID dedup, URL dedup, type-aware behavior."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from utils import deduplicate, source_priority, skill_identity_key


def _entry(id, type="mcp", source_url="https://github.com/test/repo", name="Test"):
    return {
        "id": id,
        "name": name,
        "type": type,
        "description": "test",
        "source_url": source_url,
        "stars": 0,
        "category": "tooling",
        "tags": [],
        "tech_stack": [],
        "install": {"method": "manual"},
        "source": "test",
        "last_synced": "2026-03-30",
    }


class TestDeduplicateBasics:
    """Basic dedup: by ID, empty list, entries without ID."""

    def test_dedup_by_id(self):
        entries = [
            {"id": "tool-a", "name": "First"},
            {"id": "tool-a", "name": "Duplicate"},
            {"id": "tool-b", "name": "Other"},
        ]
        result = deduplicate(entries)
        assert len(result) == 2
        assert result[0]["name"] == "First"

    def test_no_duplicates(self):
        entries = [
            {"id": "a", "source_url": "https://github.com/owner/a"},
            {"id": "b", "source_url": "https://github.com/owner/b"},
        ]
        result = deduplicate(entries)
        assert len(result) == 2

    def test_empty_list(self):
        assert deduplicate([]) == []

    def test_entries_without_id(self):
        entries = [{"name": "no-id"}, {"name": "also-no-id"}]
        result = deduplicate(entries)
        assert len(result) == 2

    def test_entries_without_source_url(self):
        entries = [{"id": "a"}, {"id": "b"}]
        result = deduplicate(entries)
        assert len(result) == 2


class TestUrlNormalization:
    """URL normalization: trailing slash, .git suffix, case insensitive."""

    def test_url_trailing_slash(self):
        entries = [
            _entry("a", source_url="https://github.com/owner/repo"),
            _entry("b", source_url="https://github.com/owner/repo/"),
        ]
        result = deduplicate(entries)
        assert len(result) == 1

    def test_url_dot_git_suffix(self):
        entries = [
            _entry("a", source_url="https://github.com/owner/repo"),
            _entry("b", source_url="https://github.com/owner/repo.git"),
        ]
        result = deduplicate(entries)
        assert len(result) == 1

    def test_url_case_insensitive(self):
        entries = [
            _entry("a", source_url="https://github.com/Owner/Repo"),
            _entry("b", source_url="https://github.com/owner/repo"),
        ]
        result = deduplicate(entries)
        assert len(result) == 1

    def test_different_urls_kept(self):
        entries = [
            _entry("a", source_url="https://github.com/owner/repo-a"),
            _entry("b", source_url="https://github.com/owner/repo-b"),
        ]
        result = deduplicate(entries)
        assert len(result) == 2


class TestTypeAwareDedup:
    """Type-aware URL dedup: prompt/rule skip URL dedup, MCP/skill keep it."""

    def test_prompts_sharing_url_all_preserved(self):
        """10 prompts with unique ids but same source_url → all 10 kept."""
        entries = [
            _entry(f"prompt-{i}", type="prompt", source_url="https://github.com/f/prompts.chat")
            for i in range(10)
        ]
        result = deduplicate(entries)
        assert len(result) == 10

    def test_rules_sharing_url_all_preserved(self):
        """5 rules with unique ids but same source_url → all 5 kept."""
        entries = [
            _entry(f"rule-{i}", type="rule", source_url="https://github.com/Mr-chen-05/rules-2.1-optimized")
            for i in range(5)
        ]
        result = deduplicate(entries)
        assert len(result) == 5

    def test_mcp_same_url_deduped(self):
        """2 MCP entries with different ids but same source_url → only first kept."""
        entries = [
            _entry("mcp-a", type="mcp", source_url="https://github.com/owner/server"),
            _entry("mcp-b", type="mcp", source_url="https://github.com/owner/server"),
        ]
        result = deduplicate(entries)
        assert len(result) == 1
        assert result[0]["id"] == "mcp-a"

    def test_skill_same_url_deduped(self):
        """2 skill entries with different ids but same source_url → only first kept."""
        entries = [
            _entry("skill-a", type="skill", source_url="https://github.com/owner/skills"),
            _entry("skill-b", type="skill", source_url="https://github.com/owner/skills"),
        ]
        result = deduplicate(entries)
        assert len(result) == 1
        assert result[0]["id"] == "skill-a"

    def test_prompt_id_dedup_still_works(self):
        """2 prompts with same id → only first kept (id dedup active)."""
        entries = [
            _entry("same-id", type="prompt", source_url="https://github.com/f/prompts.chat", name="First"),
            _entry("same-id", type="prompt", source_url="https://github.com/f/prompts.chat", name="Second"),
        ]
        result = deduplicate(entries)
        assert len(result) == 1
        assert result[0]["name"] == "First"


# ---------------------------------------------------------------------------
# Cross-source skill dedup (skills.sh / antigravity mirror / direct upstream)
# ---------------------------------------------------------------------------


def _skill_entry(
    id,
    skill_name,
    source_url,
    install_count=None,
    skills_sh_url=None,
    skills_sh_scraped_at=None,
    source="test",
):
    """Construct a skill-type entry with optional skills.sh signal fields."""
    e = _entry(id, type="skill", source_url=source_url, name=skill_name)
    e["source"] = source
    if install_count is not None:
        e["install_count"] = install_count
    if skills_sh_url is not None:
        e["skills_sh_url"] = skills_sh_url
    if skills_sh_scraped_at is not None:
        e["skills_sh_scraped_at"] = skills_sh_scraped_at
    return e


class TestSourcePriority:
    """source_priority maps URL → numeric tier (higher = preferred)."""

    def test_anthropics_top_priority(self):
        assert source_priority(
            "https://github.com/anthropics/skills/tree/main/skills/frontend-design"
        ) == 1000

    def test_official_org_high(self):
        assert source_priority("https://github.com/vercel-labs/agent-skills") == 900
        assert source_priority("https://github.com/supermemoryai/supermemory") == 900

    def test_skills_sh_anchor_url(self):
        # An anchor URL on a non-mirror, non-official-org repo → skills.sh tier
        assert source_priority(
            "https://github.com/obra/superpowers#skill=test-driven-development"
        ) == 800

    def test_anthropics_anchor_still_anthropics_priority(self):
        # Even if it carries a skills.sh anchor, anthropics owner wins
        assert source_priority(
            "https://github.com/anthropics/skills#skill=frontend-design"
        ) == 1000

    def test_plain_github_repo(self):
        assert source_priority("https://github.com/random/repo") == 500

    def test_known_mirror_low(self):
        assert source_priority(
            "https://github.com/sickn33/antigravity-awesome-skills/tree/main/skills/frontend-design"
        ) == 200

    def test_non_github(self):
        assert source_priority("https://example.com/whatever") == 100
        assert source_priority("") == 100


class TestSkillIdentityKey:
    """skill_identity_key collapses cross-source entries onto a stable triple."""

    def test_anthropics_direct(self):
        e = _skill_entry(
            "frontend-design-skill",
            "frontend-design",
            "https://github.com/anthropics/skills/tree/main/skills/frontend-design",
        )
        assert skill_identity_key(e) == ("anthropics", "skills", "frontend-design")

    def test_skills_sh_anchor_form(self):
        e = _skill_entry(
            "frontend-design-anthropics-skills",
            "frontend-design",
            "https://github.com/anthropics/skills#skill=frontend-design",
        )
        assert skill_identity_key(e) == ("anthropics", "skills", "frontend-design")

    def test_antigravity_mirror_collapses_to_upstream(self):
        e = _skill_entry(
            "frontend-design-agskill",
            "frontend-design",
            "https://github.com/sickn33/antigravity-awesome-skills/tree/main/skills/frontend-design",
        )
        # Mirror is rewritten to anthropics/skills so all three sources share the key.
        assert skill_identity_key(e) == ("anthropics", "skills", "frontend-design")

    def test_non_skill_returns_none(self):
        e = _entry("a", type="mcp", source_url="https://github.com/foo/bar")
        assert skill_identity_key(e) is None

    def test_non_github_returns_none(self):
        e = _skill_entry("a", "foo", source_url="https://example.com/foo")
        assert skill_identity_key(e) is None

    def test_nested_skill_path_preserved(self):
        """Nested skill paths like ``game-development/2d-games`` must produce
        distinct identity keys from sibling paths under the same parent.

        Regression: before the fix, the regex stopped at the first ``/`` after
        ``/skills/``, collapsing ``game-development/2d-games`` and
        ``game-development/3d-games`` onto the same key ``game-development``.
        """
        a = _skill_entry(
            "2d-games-antigravity",
            "2d-games",
            "https://github.com/sickn33/antigravity-awesome-skills/tree/main/skills/game-development/2d-games",
        )
        b = _skill_entry(
            "3d-games-antigravity",
            "3d-games",
            "https://github.com/sickn33/antigravity-awesome-skills/tree/main/skills/game-development/3d-games",
        )
        ka = skill_identity_key(a)
        kb = skill_identity_key(b)
        # Mirror still rewrites owner/repo to anthropics/skills, but the
        # nested skill name must be preserved end-to-end.
        assert ka == ("anthropics", "skills", "game-development/2d-games")
        assert kb == ("anthropics", "skills", "game-development/3d-games")
        assert ka != kb

    def test_nested_skill_path_dedup(self):
        """Two sibling nested skills must both survive deduplicate()."""
        entries = [
            _skill_entry(
                "2d-games-antigravity",
                "2d-games",
                "https://github.com/sickn33/antigravity-awesome-skills/tree/main/skills/game-development/2d-games",
            ),
            _skill_entry(
                "3d-games-antigravity",
                "3d-games",
                "https://github.com/sickn33/antigravity-awesome-skills/tree/main/skills/game-development/3d-games",
            ),
        ]
        result = deduplicate(entries)
        assert len(result) == 2
        ids = {e["id"] for e in result}
        assert ids == {"2d-games-antigravity", "3d-games-antigravity"}


class TestCrossSourceSkillDedup:
    """End-to-end: 5 dedup scenarios required by Section 3.4."""

    def test_only_skills_sh(self):
        """Scenario 1: a single skills.sh entry passes through untouched."""
        entries = [
            _skill_entry(
                "frontend-design-anthropics-skills",
                "frontend-design",
                "https://github.com/anthropics/skills#skill=frontend-design",
                install_count=12345,
                skills_sh_url="https://skills.sh/anthropics/skills/frontend-design",
                skills_sh_scraped_at="2026-01-30T04:51:07.907Z",
            ),
        ]
        result = deduplicate(entries)
        assert len(result) == 1
        assert result[0]["id"] == "frontend-design-anthropics-skills"
        assert result[0]["install_count"] == 12345

    def test_only_antigravity_mirror(self):
        """Scenario 2: a lone antigravity mirror entry is preserved."""
        entries = [
            _skill_entry(
                "frontend-design-agskill",
                "frontend-design",
                "https://github.com/sickn33/antigravity-awesome-skills/tree/main/skills/frontend-design",
            ),
        ]
        result = deduplicate(entries)
        assert len(result) == 1
        assert result[0]["id"] == "frontend-design-agskill"

    def test_skills_sh_plus_mirror_collapses(self):
        """Scenario 3: skills.sh + antigravity mirror → keep skills.sh (priority 800 > 200)."""
        entries = [
            _skill_entry(
                "frontend-design-agskill",
                "frontend-design",
                "https://github.com/sickn33/antigravity-awesome-skills/tree/main/skills/frontend-design",
                source="antigravity-skills",
            ),
            _skill_entry(
                "frontend-design-anthropics-skills",
                "frontend-design",
                "https://github.com/anthropics/skills#skill=frontend-design",
                install_count=8888,
                skills_sh_url="https://skills.sh/anthropics/skills/frontend-design",
                skills_sh_scraped_at="2026-01-30T04:51:07.907Z",
                source="skills-sh",
            ),
        ]
        result = deduplicate(entries)
        assert len(result) == 1
        # skills.sh anchor URL is on anthropics/* so it actually scores at the
        # anthropics tier (1000), winning over the mirror unconditionally.
        assert result[0]["id"] == "frontend-design-anthropics-skills"
        assert result[0]["install_count"] == 8888

    def test_three_sources_anthropics_wins_with_skills_sh_fields_merged(self):
        """Scenario 4: anthropics direct + skills.sh + mirror → anthropics keeps id, gets skills.sh fields."""
        entries = [
            # anthropics direct (highest priority — 1000)
            _skill_entry(
                "frontend-design-skill",
                "frontend-design",
                "https://github.com/anthropics/skills/tree/main/skills/frontend-design",
                source="anthropics-skills",
            ),
            # skills.sh anchor entry (also anthropics — 1000, but later in input)
            _skill_entry(
                "frontend-design-anthropics-skills",
                "frontend-design",
                "https://github.com/anthropics/skills#skill=frontend-design",
                install_count=54321,
                skills_sh_url="https://skills.sh/anthropics/skills/frontend-design",
                skills_sh_scraped_at="2026-01-30T04:51:07.907Z",
                source="skills-sh",
            ),
            # antigravity mirror (lowest — 200)
            _skill_entry(
                "frontend-design-agskill",
                "frontend-design",
                "https://github.com/sickn33/antigravity-awesome-skills/tree/main/skills/frontend-design",
                source="antigravity-skills",
            ),
        ]
        result = deduplicate(entries)
        assert len(result) == 1
        kept = result[0]
        # Direct anthropics entry wins (tie on priority, but it's first → wins by stable order)
        assert kept["id"] == "frontend-design-skill"
        assert kept["source_url"].endswith("/tree/main/skills/frontend-design")
        # skills.sh signal fields are merged onto the kept entry
        assert kept["install_count"] == 54321
        assert kept["skills_sh_url"] == "https://skills.sh/anthropics/skills/frontend-design"
        assert kept["skills_sh_scraped_at"] == "2026-01-30T04:51:07.907Z"

    def test_completely_different_source_urls_all_preserved(self):
        """Scenario 5: 5 unrelated skills (different repos / names) all kept."""
        entries = [
            _skill_entry(
                "a-skill",
                "alpha",
                "https://github.com/owner1/repo1/tree/main/skills/alpha",
            ),
            _skill_entry(
                "b-skill",
                "beta",
                "https://github.com/owner2/repo2/tree/main/skills/beta",
            ),
            _skill_entry(
                "c-skill",
                "gamma",
                "https://github.com/owner3/repo3#skill=gamma",
                install_count=5000,
            ),
            _skill_entry(
                "d-skill",
                "delta",
                "https://github.com/sickn33/antigravity-awesome-skills/tree/main/skills/delta",
            ),
            _skill_entry(
                "e-skill",
                "epsilon",
                "https://github.com/anthropics/skills/tree/main/skills/epsilon",
            ),
        ]
        result = deduplicate(entries)
        assert len(result) == 5
        assert {r["id"] for r in result} == {
            "a-skill", "b-skill", "c-skill", "d-skill", "e-skill"
        }

    def test_skills_sh_fields_merged_even_when_skills_sh_loses(self):
        """A higher-priority entry without skills.sh fields gains them from a lower-priority entry."""
        entries = [
            _skill_entry(
                "vercel-react-best-practices-skill",
                "vercel-react-best-practices",
                # Plain non-anchor URL → priority 900 (vercel-labs official org)
                "https://github.com/vercel-labs/agent-skills/tree/main/skills/vercel-react-best-practices",
                source="test-tier1",
            ),
            _skill_entry(
                "vercel-react-best-practices-vercel-labs-agent-skills",
                "vercel-react-best-practices",
                # Anchor URL → also vercel-labs → priority 900 (tie); skills.sh fields contributed
                "https://github.com/vercel-labs/agent-skills#skill=vercel-react-best-practices",
                install_count=69954,
                skills_sh_url="https://skills.sh/vercel-labs/agent-skills/vercel-react-best-practices",
                skills_sh_scraped_at="2026-01-30T04:51:07.907Z",
                source="skills-sh",
            ),
        ]
        result = deduplicate(entries)
        assert len(result) == 1
        kept = result[0]
        # First entry wins on tie (stable ordering)
        assert kept["id"] == "vercel-react-best-practices-skill"
        # But it picks up the skills.sh signal fields from the loser
        assert kept["install_count"] == 69954
        assert kept["skills_sh_url"].startswith("https://skills.sh/vercel-labs/")

    def test_id_dedup_still_runs_after_identity_collapse(self):
        """Two skill entries with the same id but no identity key still dedup by id."""
        entries = [
            _skill_entry("dup", "x", source_url="https://example.com/a"),  # no GH URL
            _skill_entry("dup", "x", source_url="https://example.com/b"),
        ]
        result = deduplicate(entries)
        assert len(result) == 1
        assert result[0]["source_url"] == "https://example.com/a"
