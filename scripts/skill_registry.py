#!/usr/bin/env python3
"""Skill Registry: discover skills from community repos via skill_repos.json."""

import os
import re
import json
import shutil
import subprocess
import tempfile
from datetime import date
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError

import sys
sys.path.insert(0, os.path.dirname(__file__))
from utils import (
    categorize, extract_tags, to_kebab_case, logger, github_api,
    SPAM_PATTERNS, NON_CODING_CATEGORIES, SKILL_CODING_KEYWORDS,
)

SCRIPTS_DIR = os.path.dirname(__file__)
SKILL_REPOS_URL = "https://raw.githubusercontent.com/Chat2AnyLLM/awesome-repo-configs/main/skill_repos.json"
FALLBACK_PATH = os.path.join(SCRIPTS_DIR, "fallback_skill_repos.json")
BLACKLIST_PATH = os.path.join(SCRIPTS_DIR, "repo_blacklist.json")
AGGREGATOR_THRESHOLD = 1000
CLONE_TIMEOUT = 300  # 5 minutes
TODAY = date.today().isoformat()


def load_blacklist() -> set:
    """Load repo blacklist from repo_blacklist.json."""
    try:
        with open(BLACKLIST_PATH, "r") as f:
            return set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"moltbot/skills"}


def fetch_skill_repos() -> dict:
    """Fetch skill_repos.json from remote, fallback to local cache."""
    try:
        req = Request(SKILL_REPOS_URL, headers={"User-Agent": "coding-hub-sync"})
        with urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
            # Save as fallback on success
            with open(FALLBACK_PATH, "w") as f:
                json.dump(data, f, indent=2)
            logger.info(f"Fetched skill_repos.json: {len(data)} repos")
            return data
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as e:
        logger.warning(f"Failed to fetch skill_repos.json: {e}")

    # Try fallback
    if os.path.exists(FALLBACK_PATH):
        try:
            with open(FALLBACK_PATH, "r") as f:
                data = json.load(f)
            logger.info(f"Using fallback skill_repos.json: {len(data)} repos")
            return data
        except (json.JSONDecodeError, IOError):
            pass

    logger.warning("No skill_repos.json available, skipping Tier 2 sync")
    return {}


def clone_repo(owner: str, name: str, branch: str, tmp_dir: str) -> str | None:
    """Clone a repo with --depth 1 into tmp_dir. Returns clone path or None."""
    clone_path = os.path.join(tmp_dir, f"{owner}_{name}")
    url = f"https://github.com/{owner}/{name}.git"
    try:
        subprocess.run(
            ["git", "clone", "--depth", "1", "--branch", branch, url, clone_path],
            capture_output=True, timeout=CLONE_TIMEOUT,
            check=True,
        )
        return clone_path
    except subprocess.TimeoutExpired:
        logger.warning(f"Clone timeout for {owner}/{name}")
    except subprocess.CalledProcessError as e:
        logger.warning(f"Clone failed for {owner}/{name}: {e.stderr.decode()[:200]}")
    return None


def scan_skill_mds(repo_path: str) -> list[dict]:
    """Recursively scan for SKILL.md files and parse frontmatter."""
    entries = []
    for root, _, files in os.walk(repo_path):
        for fname in files:
            if fname.upper() == "SKILL.MD":
                fpath = os.path.join(root, fname)
                rel_path = os.path.relpath(fpath, repo_path)
                skill_dir = os.path.dirname(rel_path)
                entry = parse_skill_md(fpath, skill_dir)
                if entry:
                    entries.append(entry)
    return entries


def parse_skill_md(filepath: str, skill_dir: str) -> dict | None:
    """Parse a SKILL.md file and extract frontmatter fields."""
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except IOError:
        return None

    name = ""
    description = ""
    category = ""
    tags = []

    # Parse YAML frontmatter
    fm_match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
    if fm_match:
        frontmatter = fm_match.group(1)
        name_m = re.search(r'name:\s*"?([^"\n]+)"?', frontmatter)
        desc_m = re.search(r'description:\s*[>|]?\s*\n?\s*"?([^"\n]+)"?', frontmatter)
        cat_m = re.search(r'category:\s*"?([^"\n]+)"?', frontmatter)
        tags_m = re.search(r'tags:\s*\[([^\]]*)\]', frontmatter)

        if name_m:
            name = name_m.group(1).strip()
        if desc_m:
            description = desc_m.group(1).strip()
        if cat_m:
            category = cat_m.group(1).strip()
        if tags_m:
            tags = [t.strip().strip('"').strip("'") for t in tags_m.group(1).split(",") if t.strip()]

    # Fallback: infer name from directory
    if not name:
        name = os.path.basename(skill_dir) if skill_dir and skill_dir != "." else ""

    # Skip if still no name or no description
    if not name:
        return None
    if not description:
        return None

    return {
        "name": name,
        "description": description,
        "category": category,
        "tags": tags,
        "skill_dir": skill_dir,
    }


def get_repo_stars(owner: str, name: str) -> int:
    """Get star count for a repo via GitHub API."""
    data = github_api(f"repos/{owner}/{name}")
    if data and "stargazers_count" in data:
        return data["stargazers_count"]
    return 0


def hard_filter(candidate: dict, stars: int, tier1_urls: set, tier1_ids: set) -> str | None:
    """Apply Phase 1 hard rules. Returns None if pass, or rejection reason."""
    name = candidate["name"].lower()
    desc = candidate["description"].lower()
    cat = candidate.get("category", "").lower()

    # Rule 1: Star threshold
    if stars <= 50:
        return "stars <= 50"

    # Rule 2: Description quality
    if len(candidate["description"]) <= 20:
        return "description too short"

    # Rule 3: Spam patterns
    text = f"{name} {desc}"
    for pattern in SPAM_PATTERNS:
        if pattern in text:
            return f"spam: {pattern}"

    # Rule 4: Non-coding category
    if cat in NON_CODING_CATEGORIES:
        return f"non-coding category: {cat}"

    # Rule 6: Dedup with Tier 1
    source_url = candidate.get("source_url", "")
    skill_id = candidate.get("id", "")
    if source_url in tier1_urls or skill_id in tier1_ids:
        return "duplicate with Tier 1"

    return None


def has_coding_keyword(candidate: dict) -> bool:
    """Check if candidate matches coding keywords (Rule 5) using word boundaries."""
    text = f"{candidate['name']} {candidate['description']}".lower()
    return any(re.search(r'\b' + re.escape(kw) + r'\b', text) for kw in SKILL_CODING_KEYWORDS)


def discover_skills(tier1_entries: list) -> list[dict]:
    """
    Main entry: discover Tier 2 skills from skill_repos.json.
    Returns list of candidate dicts ready for LLM evaluation.
    Candidates that match coding keywords are marked as keyword_match=True.
    """
    repos_data = fetch_skill_repos()
    if not repos_data:
        return []

    blacklist = load_blacklist()

    # Build Tier 1 dedup sets
    tier1_urls = {e.get("source_url", "") for e in tier1_entries if e.get("source_url")}
    tier1_ids = {e.get("id", "") for e in tier1_entries if e.get("id")}

    candidates = []
    stars_cache = {}  # owner/name -> stars
    tmp_dir = tempfile.mkdtemp(prefix="skill_registry_")

    try:
        for repo_key, repo_info in repos_data.items():
            if not isinstance(repo_info, dict):
                continue
            if not repo_info.get("enabled", False):
                continue

            owner = repo_info.get("owner", "")
            name = repo_info.get("name", "")
            branch = repo_info.get("branch", "main")
            repo_slug = f"{owner}/{name}"

            if repo_slug in blacklist:
                logger.info(f"Skipping blacklisted repo: {repo_slug}")
                continue

            logger.info(f"Processing repo: {repo_slug} (branch: {branch})")

            clone_path = clone_repo(owner, name, branch, tmp_dir)
            if not clone_path:
                continue

            # Scan SKILL.md files
            skill_entries = scan_skill_mds(clone_path)

            # Aggregator detection
            if len(skill_entries) > AGGREGATOR_THRESHOLD:
                logger.warning(
                    f"Repo {repo_slug} has {len(skill_entries)} skills, "
                    f"exceeds threshold {AGGREGATOR_THRESHOLD}, skipped as suspected aggregator"
                )
                continue

            # Get stars (cached per repo)
            if repo_slug not in stars_cache:
                stars_cache[repo_slug] = get_repo_stars(owner, name)
            stars = stars_cache[repo_slug]

            for entry in skill_entries:
                skill_id = f"{to_kebab_case(entry['name'])}-skill"
                source_url = f"https://github.com/{repo_slug}/tree/{branch}/{entry['skill_dir']}"

                candidate = {
                    "id": skill_id,
                    "name": entry["name"],
                    "type": "skill",
                    "description": entry["description"],
                    "source_url": source_url,
                    "stars": stars,
                    "category": categorize(
                        entry["name"], entry["description"],
                        entry["tags"], entry.get("category", "")
                    ),
                    "tags": entry["tags"] if entry["tags"] else extract_tags(entry["name"], entry["description"]),
                    "tech_stack": [],
                    "install": {
                        "method": "git_clone",
                        "repo": f"{owner}/{name}",
                        "branch": branch,
                        "path": entry["skill_dir"],
                    },
                    "source": repo_slug,
                    "last_synced": TODAY,
                }

                # Apply hard filter
                rejection = hard_filter(candidate, stars, tier1_urls, tier1_ids)
                if rejection:
                    continue

                # Mark coding keyword match for LLM fallback
                candidate["_keyword_match"] = has_coding_keyword(candidate)
                candidates.append(candidate)

        logger.info(f"Phase 1 passed: {len(candidates)} candidates from {len(repos_data)} repos")

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return candidates


if __name__ == "__main__":
    # Standalone test
    results = discover_skills([])
    print(f"Discovered {len(results)} candidates")
    for r in results[:5]:
        print(f"  {r['name']} ({r['source']}) stars={r['stars']} kw={r.get('_keyword_match')}")
