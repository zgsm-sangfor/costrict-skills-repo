#!/usr/bin/env python3
"""Deep reviewer - fetch actual content for 'review' entries and reclassify via LLM."""

import os
import re
import json
import hashlib
import logging
import time
from datetime import datetime, timedelta
from typing import Any, Optional
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError

try:
    from .scoring_governor import judge_decision, compute_final_score
except ImportError:
    from scoring_governor import judge_decision, compute_final_score

try:
    from .utils import GITHUB_TOKEN
except ImportError:
    from utils import GITHUB_TOKEN

logger = logging.getLogger(__name__)

CATALOG_DIR = os.path.join(os.path.dirname(__file__), "..", "catalog")
CACHE_PATH = os.path.join(CATALOG_DIR, ".deep_review_cache.json")
CACHE_EXPIRY_DAYS = 30
CONTENT_TRUNCATE = 2000

LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "claude-haiku-4-5-20251001")

# Category → coding_relevance mapping
CATEGORY_RELEVANCE = {
    "core": 5,
    "related": 3,
    "unrelated": 1,
}

_SYSTEM_PROMPT = """You are re-evaluating a software development resource.
The initial screening could not determine its relevance because
the metadata was insufficient. You now have the ACTUAL CONTENT.

Based on the ACTUAL CONTENT (not just the short description),
classify this resource:

  core — The tool directly operates on code, code execution, or code infrastructure.
         Ask: does a developer USE this tool while writing, testing, debugging, or deploying code?
         Examples: database client, testing framework, CI/CD tool, K8s orchestration,
                   code linter, Git tool, compiler, debugger, IDE plugin.

  related — Developers encounter this in their workflow, but it is not about code itself.
            Ask: would a non-developer also find this tool useful?
            Examples: project management, documentation, design tools, API clients
                      for non-dev services, data visualization.

  unrelated — Not related to software development.
              Examples: cooking, travel, sports, marketing, SEO, sales CRM,
                        social media, content writing, persona simulation,
                        voice/audio generation, image generation, entertainment.

CRITICAL RULES:
- Having install instructions (npm, pip, brew) does NOT make something a dev tool.
  Judge by WHAT THE TOOL DOES, not how it is installed.
- "MCP server for X" — classify based on X, not on being an MCP server.
- Voice/TTS/audio platforms → unrelated, even if they have an API.
- Marketing/psychology/persuasion frameworks → unrelated.
- Kubernetes/Docker/CI tools → core (infrastructure IS code management).

You MUST choose one. Do not say "unknown" — you have the full content now.
The initial description may have been misleading. Judge by what you see above.

Respond with JSON only: {"id": "...", "category": "core|related|unrelated", "reason": "..."}"""


# ---------------------------------------------------------------------------
# 3.1  URL construction
# ---------------------------------------------------------------------------

def _parse_github_url(source_url: str) -> Optional[tuple[str, str]]:
    """Extract (owner/repo, path_within_repo) from a GitHub URL.

    Returns (repo_slug, subpath) where subpath may be empty for root-level repos.
    Examples:
        https://github.com/owner/repo           -> ("owner/repo", "")
        https://github.com/owner/repo/tree/main/sub/dir -> ("owner/repo", "sub/dir")
    """
    m = re.match(
        r"https?://github\.com/([^/]+/[^/]+?)(?:\.git)?(?:/tree/[^/]+/(.+?))?/?$",
        source_url,
    )
    if not m:
        return None
    repo_slug = m.group(1)
    subpath = m.group(2) or ""
    return repo_slug, subpath


def build_content_url(entry: dict[str, Any]) -> Optional[tuple[str, str, str]]:
    """Return (repo_slug, file_path, fallback_path|None) for fetching content.

    Returns None if the entry type is unsupported or URL is unparseable.
    The caller should try file_path first, then fallback_path if provided.
    """
    entry_type = entry.get("type", "")
    source_url = entry.get("source_url", "")

    if entry_type == "prompt":
        return None  # Skip deep review for prompts

    if entry_type == "rule":
        # Rules: use install.files[0] which is already a raw URL
        install = entry.get("install", {})
        files = install.get("files", [])
        if files and isinstance(files[0], str):
            return "__raw_url__", files[0], None
        return None

    if not source_url:
        return None

    parsed = _parse_github_url(source_url)
    if not parsed:
        return None

    repo_slug, subpath = parsed

    if entry_type == "mcp":
        # MCP: independent repo → README.md at root
        return repo_slug, "README.md", None

    if entry_type == "skill":
        if subpath:
            # Subdirectory skill → SKILL.md, fallback README.md
            return repo_slug, f"{subpath}/SKILL.md", f"{subpath}/README.md"
        else:
            # Root-level skill repo
            return repo_slug, "SKILL.md", "README.md"

    return None


# ---------------------------------------------------------------------------
# 3.2  Content fetch
# ---------------------------------------------------------------------------

def fetch_content(entry: dict[str, Any]) -> Optional[str]:
    """Fetch actual content for an entry. Returns truncated text or None on error.

    Return values:
        str  — content fetched (may be empty string for empty files)
        None — network error or timeout (keep review for retry)

    Raises nothing; all errors are caught and logged.
    """
    url_info = build_content_url(entry)
    if url_info is None:
        return None

    repo_slug, primary_path, fallback_path = url_info

    if repo_slug == "__raw_url__":
        # Rule: primary_path is the full raw URL
        return _fetch_url(primary_path)

    # Try primary path via raw URL (so we can distinguish 404 vs network error)
    primary_url = f"https://raw.githubusercontent.com/{repo_slug}/main/{primary_path}"
    content = _fetch_url(primary_url)
    if content is not None and content != "":
        return content
    if content is None:
        # Network error on primary → don't reject, signal retry
        return None

    # Primary was 404/empty, try fallback if available
    if fallback_path:
        fallback_url = f"https://raw.githubusercontent.com/{repo_slug}/main/{fallback_path}"
        content = _fetch_url(fallback_url)
        if content is not None and content != "":
            return content
        if content is None:
            # Network error on fallback → signal retry
            return None

    # Both paths 404 → treat as reject-worthy (return empty)
    return ""


def _fetch_url(url: str) -> Optional[str]:
    """Fetch a raw URL directly. Returns truncated content, empty string on 404, None on error."""
    headers = {"User-Agent": "everything-ai-coding-deep-review"}
    if GITHUB_TOKEN and "githubusercontent.com" in url:
        headers["Authorization"] = f"token {GITHUB_TOKEN}"
    req = Request(url, headers=headers)
    try:
        with urlopen(req, timeout=30) as resp:
            content = resp.read().decode("utf-8", errors="replace")
            return content[:CONTENT_TRUNCATE]
    except HTTPError as e:
        if e.code == 404:
            return ""  # 404 → empty content → reject
        logger.warning(f"Deep review fetch error {e.code}: {url}")
        return None
    except (URLError, TimeoutError) as e:
        logger.warning(f"Deep review network error: {e}")
        return None


# ---------------------------------------------------------------------------
# 3.3  LLM reclassification
# ---------------------------------------------------------------------------

def _call_llm_reclassify(entry: dict[str, Any], content: str) -> Optional[dict[str, str]]:
    """Call LLM to reclassify an entry based on actual content.

    Returns {"id": ..., "category": "core"|"related"|"unrelated", "reason": ...}
    or None on failure.
    """
    if not LLM_BASE_URL or not LLM_API_KEY:
        return None

    user_prompt = f"""METADATA:
  id: {entry.get('id', '')}
  name: {entry.get('name', '')}
  type: {entry.get('type', '')}
  description: {entry.get('description', '')}

ACTUAL CONTENT (first {CONTENT_TRUNCATE} chars):
---
{content}
---"""

    url = f"{LLM_BASE_URL.rstrip('/')}/chat/completions"
    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.1,
        "max_tokens": 512,
    }

    data = json.dumps(payload).encode()
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LLM_API_KEY}",
    }
    req = Request(url, data=data, headers=headers, method="POST")

    for attempt in range(3):
        try:
            with urlopen(req, timeout=120) as resp:
                result = json.loads(resp.read().decode())
                raw = result["choices"][0]["message"]["content"].strip()
                # Strip markdown code fences if present
                if raw.startswith("```"):
                    raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
                parsed = json.loads(raw)
                cat = parsed.get("category", "")
                if cat not in ("core", "related", "unrelated"):
                    logger.warning(f"LLM returned invalid category '{cat}' for {entry.get('id')}")
                    return None
                return {
                    "id": parsed.get("id", entry.get("id", "")),
                    "category": cat,
                    "reason": parsed.get("reason", ""),
                }
        except (HTTPError, URLError, TimeoutError) as e:
            logger.warning(f"Deep review LLM error (attempt {attempt + 1}): {e}")
            if attempt < 2:
                time.sleep(2 ** attempt)
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            logger.warning(f"Deep review LLM parse error: {e}")
            return None
    return None


# ---------------------------------------------------------------------------
# 3.4  Cache read/write
# ---------------------------------------------------------------------------

def _load_cache() -> dict[str, Any]:
    """Load deep review cache from disk."""
    if not os.path.exists(CACHE_PATH):
        return {}
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def _save_cache(cache: dict[str, Any]) -> None:
    """Save deep review cache to disk."""
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)


def _content_hash(content: str) -> str:
    """Compute SHA-256 hash of content for cache invalidation."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _is_cache_hit(cache_entry: dict[str, Any], content: str) -> bool:
    """Check if cache entry is still valid (not expired, content unchanged)."""
    reviewed_at = cache_entry.get("reviewed_at", "")
    if not reviewed_at:
        return False
    try:
        review_date = datetime.fromisoformat(reviewed_at)
        if datetime.now() - review_date >= timedelta(days=CACHE_EXPIRY_DAYS):
            return False
    except ValueError:
        return False

    # Content changed → re-evaluate even if not expired
    cached_hash = cache_entry.get("content_hash", "")
    if cached_hash and cached_hash != _content_hash(content):
        return False

    return True


# ---------------------------------------------------------------------------
# 3.5  Main function
# ---------------------------------------------------------------------------

def deep_review_entries(entries: list[dict[str, Any]]) -> None:
    """Process entries with decision=='review': fetch content, reclassify via LLM, update in-place.

    Filters to entries where evaluation.decision == 'review' and type != 'prompt'.
    Updates each entry's evaluation.coding_relevance and re-runs judge_decision.
    """
    # Filter to review candidates
    candidates = [
        e for e in entries
        if e.get("evaluation", {}).get("decision") == "review"
        and e.get("type") != "prompt"
    ]

    if not candidates:
        logger.info("Deep review: no entries to review")
        return

    logger.info(f"Deep review: {len(candidates)} candidates")

    cache = _load_cache()
    reviewed = 0
    cached_hits = 0
    fetch_errors = 0

    for entry in candidates:
        entry_id = entry.get("id", "")
        entry_type = entry.get("type", "")
        cache_key = f"{entry_type}:{entry_id}"

        # Fetch content first (needed for cache hash comparison)
        content = fetch_content(entry)

        if content is None:
            # Network error / timeout → keep as review, retry next run
            fetch_errors += 1
            logger.debug(f"Deep review: fetch failed for {entry_id}, keeping review")
            continue

        if content == "":
            # Empty content or 404 → reject
            logger.debug(f"Deep review: empty/404 content for {entry_id}, rejecting")
            _apply_classification(entry, "unrelated", "No content found (404 or empty)")
            reviewed += 1
            continue

        # Check cache
        if cache_key in cache and _is_cache_hit(cache[cache_key], content):
            cached = cache[cache_key]
            _apply_classification(entry, cached["category"], cached.get("reason", "cached"))
            cached_hits += 1
            reviewed += 1
            continue

        # Call LLM
        result = _call_llm_reclassify(entry, content)
        if result is None:
            # LLM unavailable → keep as review
            logger.debug(f"Deep review: LLM failed for {entry_id}, keeping review")
            continue

        # Update cache
        cache[cache_key] = {
            "category": result["category"],
            "reason": result["reason"],
            "content_hash": _content_hash(content),
            "reviewed_at": datetime.now().isoformat(),
        }
        _save_cache(cache)

        # Apply classification
        _apply_classification(entry, result["category"], result["reason"])
        reviewed += 1
        logger.debug(f"Deep review: {entry_id} → {result['category']} ({result['reason']})")

    logger.info(
        f"Deep review complete: {reviewed} reviewed ({cached_hits} from cache), "
        f"{fetch_errors} fetch errors"
    )


def _apply_classification(entry: dict[str, Any], category: str, reason: str) -> None:
    """Update entry evaluation based on LLM reclassification and re-run decision."""
    evaluation = entry.get("evaluation") or {}
    entry["evaluation"] = evaluation

    new_cr = CATEGORY_RELEVANCE.get(category, 3)
    evaluation["coding_relevance"] = new_cr
    evaluation["deep_review_category"] = category
    evaluation["deep_review_reason"] = reason

    # Recompute final_score
    evaluation["final_score"] = compute_final_score(entry)

    # Deep review has the final word: unrelated → reject directly,
    # bypassing the cr≤1 hard rule which would loop back to "review".
    if category == "unrelated":
        evaluation["decision"] = "reject"
    else:
        evaluation["decision"] = judge_decision(entry)
