"""Shared utilities for sync scripts."""

import os
import re
import json
import time
import logging
import urllib.parse
from typing import Optional
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
_github_api_disabled_until = 0.0

# --- GitHub proxy support ---
GITHUB_PROXY = os.environ.get("GITHUB_PROXY", "").strip()
GITHUB_PROXY_AUTH = os.environ.get("GITHUB_PROXY_AUTH", "").strip()

_PROBE_URL = "https://raw.githubusercontent.com/zgsm-ai/everything-ai-coding/main/catalog/search-index.json"

_use_proxy = False
_proxy_url = ""


def _probe_github_reachable(timeout: int = 3) -> bool:
    """HEAD-style probe to check if GitHub is directly reachable (3s timeout)."""
    try:
        req = Request(_PROBE_URL, method="HEAD")
        if GITHUB_TOKEN:
            req.add_header("Authorization", f"token {GITHUB_TOKEN}")
        urlopen(req, timeout=timeout)
        return True
    except Exception:
        return False


def _init_proxy() -> None:
    """Detect whether to use the GitHub proxy and set global flags."""
    global _use_proxy, _proxy_url

    if not GITHUB_PROXY:
        # No proxy configured → direct access, no probe needed
        return

    # Handle "always:<proxy-url>" shorthand
    if GITHUB_PROXY.startswith("always:"):
        _proxy_url = GITHUB_PROXY[len("always:"):].rstrip("/")
        _use_proxy = True
        logger.info("Using proxy %s (always mode)", _proxy_url)
        return

    proxy_url_candidate = GITHUB_PROXY.rstrip("/")

    # Probe GitHub directly
    if _probe_github_reachable():
        logger.info("GitHub direct access OK")
        return

    # GitHub unreachable — verify proxy is alive before committing
    try:
        proxy_origin = proxy_url_candidate
        if GITHUB_PROXY_AUTH:
            proxy_origin = proxy_origin.replace("://", f"://{GITHUB_PROXY_AUTH}@", 1)
        probe_via_proxy = f"{proxy_origin}/{_PROBE_URL}"
        req = Request(probe_via_proxy, method="HEAD")
        urlopen(req, timeout=3)
    except Exception:
        logger.warning("Proxy %s also unreachable, falling back to direct", proxy_url_candidate)
        return

    _proxy_url = proxy_url_candidate
    _use_proxy = True
    logger.info("Using proxy %s", _proxy_url)


_PROXY_DOMAINS = ("raw.githubusercontent.com", "github.com")


def _proxy_rewrite_url(url: str) -> str:
    """Rewrite a GitHub URL through the proxy if _use_proxy is True.

    Only rewrites URLs targeting GitHub domains (raw.githubusercontent.com,
    github.com, api.github.com). Non-GitHub URLs are returned unchanged.
    Embeds proxy auth credentials in the URL if GITHUB_PROXY_AUTH is set,
    keeping the Authorization header free for GITHUB_TOKEN.
    """
    if not _use_proxy or not _proxy_url:
        return url
    if not any(f"://{domain}/" in url or url.endswith(f"://{domain}") for domain in _PROXY_DOMAINS):
        return url
    if GITHUB_PROXY_AUTH:
        return _proxy_url.replace("://", f"://{GITHUB_PROXY_AUTH}@", 1) + f"/{url}"
    return f"{_proxy_url}/{url}"


def _safe_log_url(url: str) -> str:
    """Strip embedded credentials from URL for safe logging."""
    # Matches https://user:pass@host/... → https://***@host/...
    return re.sub(r"://[^@]+@", "://***@", url)


_init_proxy()

CATEGORY_MAP = {
    # MCP categories (awesome-mcp-servers)
    "browser automation": "testing",
    "cloud platforms": "devops",
    "databases": "database",
    "developer tools": "tooling",
    "file systems": "tooling",
    "os automation": "devops",
    "security": "security",
    "monitoring": "devops",
    "version control": "tooling",
    "code execution": "tooling",
    "coding agents": "tooling",
    "command line": "tooling",
    "data science tools": "ai-ml",
    "data visualization": "frontend",
    "communication": "tooling",
    "research": "documentation",
    "search & data extraction": "tooling",
    "knowledge & memory": "ai-ml",
    # Cursorrules tech stack keywords
    "react": "frontend",
    "nextjs": "frontend",
    "next.js": "frontend",
    "vue": "frontend",
    "angular": "frontend",
    "svelte": "frontend",
    "tailwind": "frontend",
    "css": "frontend",
    "html": "frontend",
    "typescript": "frontend",
    "javascript": "frontend",
    "node": "backend",
    "express": "backend",
    "fastapi": "backend",
    "django": "backend",
    "flask": "backend",
    "python": "backend",
    "go": "backend",
    "golang": "backend",
    "rust": "backend",
    "java": "backend",
    "spring": "backend",
    "ruby": "backend",
    "rails": "backend",
    "elixir": "backend",
    "php": "backend",
    "laravel": "backend",
    "c#": "backend",
    "dotnet": "backend",
    ".net": "backend",
    "flutter": "mobile",
    "react native": "mobile",
    "swift": "mobile",
    "swiftui": "mobile",
    "kotlin": "mobile",
    "android": "mobile",
    "ios": "mobile",
    "docker": "devops",
    "kubernetes": "devops",
    "k8s": "devops",
    "terraform": "devops",
    "aws": "devops",
    "gcp": "devops",
    "azure": "devops",
    "ci/cd": "devops",
    "ci-cd": "devops",
    "sql": "database",
    "postgres": "database",
    "mysql": "database",
    "mongodb": "database",
    "redis": "database",
    "prisma": "database",
    "supabase": "database",
    "drizzle": "database",
    "test": "testing",
    "testing": "testing",
    "jest": "testing",
    "playwright": "testing",
    "cypress": "testing",
    "vitest": "testing",
    "auth": "security",
    "security": "security",
    "crypto": "security",
    "ai": "ai-ml",
    "ml": "ai-ml",
    "llm": "ai-ml",
    "machine learning": "ai-ml",
    "openai": "ai-ml",
    "langchain": "ai-ml",
    "documentation": "documentation",
    "docs": "documentation",
    "markdown": "documentation",
    "api": "backend",
    "graphql": "backend",
    "rest": "backend",
    "fullstack": "fullstack",
    "full-stack": "fullstack",
    "t3": "fullstack",
    "monorepo": "fullstack",
    "turborepo": "fullstack",
    "git": "tooling",
    "eslint": "tooling",
    "prettier": "tooling",
    "linting": "tooling",
    "cli": "tooling",
    "vscode": "tooling",
}

# Spam patterns for skill filtering (case-insensitive)
SPAM_PATTERNS = [
    "viral", "prompt-ready", "copy-paste", "click-bait",
    "get-rich", "make-money",
]

# Non-coding categories to exclude from skill registry
NON_CODING_CATEGORIES = [
    "marketing", "brand", "branding", "raffle", "invoice",
    "resume", "cover-letter", "social-media", "content-writing",
    "seo", "creative", "media", "communication", "writing",
]

# Coding-related keywords for skill registry Phase 1 filtering
SKILL_CODING_KEYWORDS = [
    "code", "develop", "engineer", "debug", "test", "deploy",
    "build", "compile", "lint", "refactor", "api", "database",
    "git", "docker", "ci", "cd", "terminal", "cli", "shell",
    "script", "framework", "library", "sdk", "mcp", "skill", "agent",
]

# Coding-related keywords for prompt filtering
CODING_KEYWORDS = [
    "code", "coding", "developer", "development", "engineer", "engineering",
    "programmer", "programming", "terminal", "frontend", "backend", "devops",
    "debug", "debugging", "software", "api", "database", "algorithm",
    "compiler", "linux", "git", "deploy", "deployment", "architecture",
    "testing", "qa", "fullstack", "full-stack", "web developer",
    "javascript", "python", "typescript", "react", "node", "sql",
    "html", "css", "docker", "kubernetes", "aws", "cloud",
    "machine learning", "data scientist", "data engineer",
    "tech lead", "cto", "sre", "infrastructure",
]


def github_api(path: str) -> Optional[dict]:
    """Make a GitHub API request. Returns parsed JSON or None on error."""
    global _github_api_disabled_until

    if _github_api_disabled_until > time.time():
        return None

    url = f"https://api.github.com/{path.lstrip('/')}"
    url = _proxy_rewrite_url(url)
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "everything-ai-coding-sync",
    }
    if GITHUB_TOKEN:
        headers["Authorization"] = f"token {GITHUB_TOKEN}"
    req = Request(url, headers=headers)
    for attempt in range(3):
        try:
            with urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())
        except HTTPError as e:
            if e.code in (403, 429):  # Rate limit / abuse detection
                wait = _retry_delay_seconds(e.headers, min(2 ** attempt, 60))
                if GITHUB_TOKEN:
                    if attempt < 2:
                        logger.warning(f"GitHub API rate limited, waiting {wait}s...")
                        time.sleep(wait)
                        continue
                else:
                    _github_api_disabled_until = time.time() + wait
                    logger.warning(
                        "GitHub API rate limited without token; "
                        f"skipping repo metadata calls for {wait}s"
                    )
                return None
            elif e.code == 404:
                return None
            elif e.code >= 500 and attempt < 2:
                wait = _retry_delay_seconds(e.headers, min(2 ** attempt, 30))
                logger.warning(f"GitHub API temporary error {e.code}, retrying in {wait}s...")
                time.sleep(wait)
                continue
            logger.error(f"GitHub API error {e.code}: {_safe_log_url(url)}")
            return None
        except (URLError, TimeoutError) as e:
            logger.error(f"Network error (attempt {attempt+1}): {e}")
            if attempt < 2:
                time.sleep(2 ** attempt)
    return None


# Process-level cache for repo metadata (avoids duplicate API calls within a single sync run)
_repo_meta_cache = {}
_repo_readme_cache = {}
_repo_languages_cache = {}


def get_repo_meta(repo_url: str) -> Optional[dict]:
    """Get comprehensive repo metadata from a GitHub URL. Returns None on error.

    Single API call returns: stars, pushed_at, default_branch, topics, license, open_issues, has_readme.
    Uses in-memory cache keyed by normalized owner/repo to avoid duplicate calls.
    """
    # Extract owner/repo from URL
    match = re.search(r"github\.com/([^/]+/[^/]+?)(?:\.git)?(?:/|$|\?|#)", repo_url)
    if not match:
        return None

    repo_slug = match.group(1).lower()  # Normalize to lowercase

    # Check cache
    if repo_slug in _repo_meta_cache:
        return _repo_meta_cache[repo_slug]

    # Fetch from API
    data = github_api(f"repos/{repo_slug}")
    if not data:
        _repo_meta_cache[repo_slug] = None
        return None

    result = {
        "stars": data.get("stargazers_count", 0),
        "pushed_at": data.get("pushed_at"),
        "default_branch": data.get("default_branch", "main"),
        "topics": data.get("topics", []),
        "has_readme": _probe_readme_exists(repo_slug, data.get("default_branch", "main"))
        if GITHUB_TOKEN else False,
        "license": data.get("license", {}).get("spdx_id") if data.get("license") else None,
        "open_issues": data.get("open_issues_count", 0),
    }

    _repo_meta_cache[repo_slug] = result
    return result


def get_repo_languages(repo_url: str) -> list[str]:
    """Get programming languages for a GitHub repo. Returns list of language names.

    Calls GET /repos/{owner}/{repo}/languages. Returns [] for non-GitHub URLs,
    API errors, or repos with no detected languages. Uses in-memory cache.
    """
    match = re.search(r"github\.com/([^/]+/[^/]+?)(?:\.git)?(?:/|$|\?|#)", repo_url)
    if not match:
        return []

    repo_slug = match.group(1).lower()

    if repo_slug in _repo_languages_cache:
        return _repo_languages_cache[repo_slug]

    data = github_api(f"repos/{repo_slug}/languages")
    if not data:
        _repo_languages_cache[repo_slug] = []
        return []

    languages = list(data.keys())
    _repo_languages_cache[repo_slug] = languages
    return languages


def get_repo_info(repo_slug: str) -> Optional[dict]:
    """Get repo metadata (stars, pushed_at, default_branch). Returns None on error.

    DEPRECATED: Use get_repo_meta() instead. Kept for backward compatibility.
    """
    # Convert slug to URL format for get_repo_meta
    meta = get_repo_meta(f"https://github.com/{repo_slug}")
    if not meta:
        return None
    return {
        "stars": meta["stars"],
        "pushed_at": meta["pushed_at"] or "",
        "default_branch": meta["default_branch"],
    }


def list_repo_files(repo_slug: str, branch: str = "main",
                    pattern: str = "") -> list[str]:
    """List files in a repo using Git Tree API (recursive). Optionally filter by pattern.
    Returns list of file paths. Much faster than cloning.
    """
    data = github_api(f"repos/{repo_slug}/git/trees/{branch}?recursive=1")
    if not data or "tree" not in data:
        return []
    paths = [item["path"] for item in data["tree"] if item.get("type") == "blob"]
    if pattern:
        paths = [p for p in paths if pattern.lower() in p.lower()]
    return paths


def get_stars(repo_url: str) -> int:
    """Get star count for a GitHub repo URL. Returns 0 on error.

    DEPRECATED: Use get_repo_meta() instead. Kept for backward compatibility.
    """
    meta = get_repo_meta(repo_url)
    if meta and meta.get("stars") is not None:
        return meta["stars"]
    return 0


def fetch_raw_content(repo: str, path: str, branch: str = "main",
                      quiet_404: bool = False) -> Optional[str]:
    """Fetch raw file content from GitHub.

    Args:
        quiet_404: If True, log 404 at DEBUG level (for expected probes).
                   If False (default), log at WARNING level.
    """
    url = f"https://raw.githubusercontent.com/{repo}/{branch}/{path}"
    url = _proxy_rewrite_url(url)
    headers = {"User-Agent": "everything-ai-coding-sync"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"token {GITHUB_TOKEN}"
    req = Request(url, headers=headers)

    for attempt in range(3):
        try:
            with urlopen(req, timeout=30) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except HTTPError as e:
            if e.code == 404:
                if quiet_404:
                    logger.debug(f"Not found (404): {_safe_log_url(url)}")
                else:
                    logger.warning(f"Not found (404): {_safe_log_url(url)}")
                return None
            if e.code in (429, 500, 502, 503, 504) and attempt < 2:
                wait = _retry_delay_seconds(e.headers, min(2 ** attempt, 30))
                logger.warning(f"Fetch failed {e.code} for {_safe_log_url(url)}, retrying in {wait}s...")
                time.sleep(wait)
                continue
            logger.error(f"Failed to fetch {_safe_log_url(url)}: {e}")
            return None
        except (URLError, TimeoutError) as e:
            logger.error(f"Failed to fetch {_safe_log_url(url)}: {e}")
            if attempt < 2:
                time.sleep(2 ** attempt)
                continue
            return None

    return None


def _retry_delay_seconds(headers, default_wait: int) -> int:
    """Best-effort retry delay from HTTP headers."""
    if headers:
        retry_after = headers.get("Retry-After")
        if retry_after:
            try:
                return max(int(retry_after), 1)
            except (TypeError, ValueError):
                pass

        reset = headers.get("X-RateLimit-Reset")
        if reset:
            try:
                return max(int(reset) - int(time.time()), 1)
            except (TypeError, ValueError):
                pass

    return max(default_wait, 1)


def _probe_readme_exists(repo_slug: str, branch: str) -> bool:
    """Probe common README paths once per repo to avoid misusing unrelated repo flags."""
    cache_key = f"{repo_slug}@{branch}"
    if cache_key in _repo_readme_cache:
        return _repo_readme_cache[cache_key]

    for candidate in ("README.md", "README", "readme.md", "Readme.md"):
        if fetch_raw_content(repo_slug, candidate, branch, quiet_404=True) is not None:
            _repo_readme_cache[cache_key] = True
            return True

    _repo_readme_cache[cache_key] = False
    return False


def categorize(name: str, description: str = "", tags: list = None,
               upstream_category: str = "") -> str:
    """Map a resource to one of the 11 unified categories."""
    tags = tags or []
    search_text = f"{name} {description} {' '.join(tags)} {upstream_category}".lower()

    # Try upstream category first
    if upstream_category:
        cat_lower = upstream_category.lower()
        if cat_lower in CATEGORY_MAP:
            return CATEGORY_MAP[cat_lower]

    # Try matching against all keywords
    for keyword, category in CATEGORY_MAP.items():
        if keyword in search_text:
            return category

    return "tooling"  # default


def extract_tags(name: str, description: str = "") -> list:
    """Extract tech stack tags from name and description."""
    text = f"{name} {description}".lower()
    found = []
    tag_keywords = {
        "react": "react", "next.js": "nextjs", "nextjs": "nextjs",
        "vue": "vue", "angular": "angular", "svelte": "svelte",
        "typescript": "typescript", "javascript": "javascript",
        "python": "python", "go": "go", "rust": "rust",
        "java": "java", "ruby": "ruby", "php": "php",
        "swift": "swift", "kotlin": "kotlin", "flutter": "flutter",
        "docker": "docker", "kubernetes": "kubernetes",
        "postgres": "postgres", "mysql": "mysql", "mongodb": "mongodb",
        "redis": "redis", "graphql": "graphql", "rest": "rest-api",
        "fastapi": "fastapi", "django": "django", "flask": "flask",
        "express": "express", "node": "nodejs",
        "tailwind": "tailwind", "css": "css",
        "aws": "aws", "gcp": "gcp", "azure": "azure",
        "terraform": "terraform",
        "jest": "jest", "playwright": "playwright", "cypress": "cypress",
        "prisma": "prisma", "supabase": "supabase",
        "openai": "openai", "langchain": "langchain",
        "git": "git", "eslint": "eslint",
    }
    for keyword, tag in tag_keywords.items():
        if keyword in text and tag not in found:
            found.append(tag)
    return found


def merge_topics_into_tags(tags: list[str], topics: list[str]) -> list[str]:
    """Merge GitHub repo topics into existing tags, deduplicated and lowercased."""
    seen = set()
    result = []
    for t in tags + [t.lower() for t in topics]:
        t_lower = t.lower().strip()
        if t_lower and t_lower not in seen:
            seen.add(t_lower)
            result.append(t_lower)
    return result


def normalize_source_url(url: str) -> str:
    """Normalize a source URL for dedup comparison."""
    url = url.lower().rstrip("/")
    if url.endswith(".git"):
        url = url[:-4]
    return url


# --- Source priority & cross-source skill dedup ---------------------------

# Whitelist of "official org" hosts on github.com whose direct sources rank
# higher than third-party mirrors. Conservative initial list — extend as needed.
_OFFICIAL_ORG_HOSTS = {
    "anthropics",
    "vercel-labs",
    "supermemoryai",
}

# Known antigravity-style mirror repos (owner/repo lowercased).
_KNOWN_MIRRORS = {
    "sickn33/antigravity-awesome-skills",
}

# Recognized awesome-windsurfrules host repos (owner/repo lowercased).
# Listed for readability; they fall into the default GitHub tier (500),
# matching design.md §4.3.
_WINDSURFRULES_REPOS = {
    "schneidersam/awesome-windsurfrules",
    "balqaasem/awesome-windsurfrules",
}

# registry.modelcontextprotocol.io entry source_url pattern.
_MCP_REGISTRY_URL_RE = re.compile(
    r"^https?://registry\.modelcontextprotocol\.io/v0/servers/(.+?)/?$"
)


def _parse_owner_repo(url: str) -> tuple[str, str] | None:
    """Extract (owner, repo) lowercased from a GitHub URL. Returns None if not GitHub."""
    if not url:
        return None
    m = re.search(r"github\.com/([^/]+)/([^/#?]+)", url)
    if not m:
        return None
    repo = m.group(2)
    if repo.endswith(".git"):
        repo = repo[:-4]
    return (m.group(1).lower(), repo.lower())


def source_priority(source_url: str) -> int:
    """Return numeric priority for a source URL (higher = preferred).

    Tiers (high → low):
      1000 — Anthropic official (github.com/anthropics/*)
      900  — Other official orgs (vercel-labs, supermemoryai, ...) /
             registry.modelcontextprotocol.io entries
      800  — skills.sh sourced direct repos (anchor `#skill=` and not a known mirror)
      500  — Other (non-mirror) GitHub repos (incl. awesome-windsurfrules)
      200  — Known mirrors (sickn33/antigravity-awesome-skills)
      100  — Non-GitHub / unparseable
    """
    # registry.modelcontextprotocol.io entries — official MCP registry tier.
    # Recognized BEFORE _parse_owner_repo so the non-GitHub URL is not
    # demoted to the 100 fallback.
    if source_url and _MCP_REGISTRY_URL_RE.match(source_url):
        return 900

    pr = _parse_owner_repo(source_url)
    if not pr:
        return 100
    owner, repo = pr
    slug = f"{owner}/{repo}"
    if slug in _KNOWN_MIRRORS:
        return 200
    if owner == "anthropics":
        return 1000
    if owner in _OFFICIAL_ORG_HOSTS:
        return 900
    if "#skill=" in (source_url or ""):
        return 800
    # awesome-windsurfrules is a default-tier GitHub repo (kept explicit for
    # readability; behaves identically to other 500-tier repos).
    if slug in _WINDSURFRULES_REPOS:
        return 500
    return 500


def _extract_skill_name(entry: dict) -> str:
    """Best-effort extraction of the skill name from an entry's source_url / name.

    Preserves nested skill paths (e.g. ``game-development/2d-games``) so that
    sibling skills under a shared parent directory don't collide on the same
    identity key.
    """
    url = entry.get("source_url") or ""
    m = re.search(r"#skill=([^&]+)", url)
    if m:
        return m.group(1).lower()
    # Capture everything after `/skills/` up to query/fragment, preserving
    # nested sub-paths. Strip trailing slashes so `.../skills/foo/` and
    # `.../skills/foo` collapse to the same key.
    m = re.search(r"/tree/[^/]+/skills/([^?#]+)", url)
    if m:
        return m.group(1).rstrip("/").lower()
    return (entry.get("name") or "").lower()


def skill_identity_key(entry: dict) -> tuple[str, str, str] | None:
    """Cross-source identity for a skill entry.

    Returns (owner, repo, skill_name) all lowercased — or None if entry is not
    a skill, has no parseable GitHub URL, or no resolvable skill name.

    For mirror repos (e.g. sickn33/antigravity-awesome-skills), the owner/repo
    is rewritten to the upstream "anthropics/skills" so that mirror entries
    collapse with the official entry under the same key.

    TODO(P2 codex review): 当 skills.sh 直接源覆盖了非 anthropics 的真实 owner（如
    obra/superpowers），sickn33 镜像与 skills.sh entry 跨 owner 时不会 collapse，
    会重复入库。需要扩展 _KNOWN_MIRRORS 的 collapse 逻辑：以 skills_sh_index.json
    作为 skill_name → (real_owner, real_repo) lookup table，对镜像 entry 反向
    查表后再 collapse。当前优先完成 Section 6/7 主任务，留 TODO 跟进。
    """
    if (entry.get("type") or "") != "skill":
        return None
    pr = _parse_owner_repo(entry.get("source_url") or "")
    if not pr:
        return None
    owner, repo = pr
    name = _extract_skill_name(entry)
    if not name:
        return None
    if f"{owner}/{repo}" in _KNOWN_MIRRORS:
        # Antigravity mirror is a snapshot of anthropics/skills — collapse to upstream
        owner, repo = "anthropics", "skills"
    return (owner, repo, name)


def mcp_identity_key(entry: dict) -> tuple[str, str, str] | None:
    """Cross-source identity for an MCP server entry.

    Strict matching, no owner-only fuzzy match. Rules (per
    docs/tier1_rules_mcp_baseline.md §5):

    - registry.modelcontextprotocol.io URL whose decoded server name matches
      ``io.github.<owner>/<repo>`` → ``('github', owner/repo, '')`` so it can
      collapse with a wong2 GitHub URL entry pointing at the SAME repo root.
      Registry-supplied "io.github" identity is repo-root scoped — it does not
      collapse with monorepo sub-path entries (those have non-empty sub_path).
    - Other reverse-DNS registry names (e.g. ``com.microsoft/azure``) → an
      independent ``('registry', registry_name, '')`` key. This avoids the
      false positives flagged in baseline §4 (same owner, different product).
    - Plain ``github.com/<owner>/<repo>`` URL → ``('github', owner/repo, '')``.
    - GitHub URL with monorepo sub-path
      (``.../tree/<branch>/src/foo`` or ``.../blob/<branch>/path/to/file``)
      → ``('github', owner/repo, sub_path)`` so sibling sub-paths in a
      monorepo do not collide on the same identity key.

    Returns ``None`` for non-mcp entries or entries whose source_url cannot
    be parsed (excluded from cross-source dedup).
    """
    if (entry.get("type") or "") != "mcp":
        return None
    su = entry.get("source_url") or ""
    if not su:
        return None

    m = _MCP_REGISTRY_URL_RE.match(su)
    if m:
        registry_name = urllib.parse.unquote(m.group(1)).strip().lower()
        if not registry_name:
            return None
        gh_match = re.match(r"^io\.github\.([^/]+)/([^/]+)$", registry_name)
        if gh_match:
            # Registry io.github.<owner>/<repo> identity is repo-root scoped
            # (no sub-path) so it only collapses with the root-level GitHub
            # URL entry for the same repo, never with a monorepo sub-path.
            return ("github", f"{gh_match.group(1)}/{gh_match.group(2)}", "")
        return ("registry", registry_name, "")

    pr = _parse_owner_repo(su)
    if pr:
        owner, repo = pr
        # Extract path after /tree/<branch>/ or /blob/<branch>/ for monorepo
        # distinction. Strip query/fragment and trailing slashes; lowercased
        # so casing differences don't fragment the same logical entry.
        path_match = re.search(r"/(?:tree|blob)/[^/]+/(.+?)(?:[?#]|$)", su)
        sub_path = path_match.group(1).rstrip("/").lower() if path_match else ""
        return ("github", f"{owner}/{repo}", sub_path)
    return None


def rule_identity_key(entry: dict) -> tuple[str, str] | None:
    """Cross-repo identity for an awesome-windsurfrules rule entry.

    The same rule slug appears in BOTH SchneiderSam/awesome-windsurfrules and
    balqaasem/awesome-windsurfrules (the latter is a fork mirror — per baseline
    docs/tier1_rules_mcp_baseline.md §2, 103/108 SchneiderSam slugs overlap
    with balqaasem and balqaasem has 0 unique entries). Their ids differ by a
    repo_slug suffix, so legacy id-based dedup keeps both copies.

    Returns ``('windsurfrules', slug)`` for type="rule" entries whose
    source_url points at one of the two awesome-windsurfrules repos. The
    slug is the directory immediately under ``rules/`` (or under
    ``rules/global_rules/`` / ``rules/windsurfrules/``).

    Returns ``None`` for non-rule entries, rules from other sources
    (awesome-cursorrules, rules-2.1-optimized, ...), or rules whose URL we
    cannot parse a slug from — those flow through unchanged.
    """
    if (entry.get("type") or "") != "rule":
        return None
    su = entry.get("source_url") or ""
    pr = _parse_owner_repo(su)
    if not pr:
        return None
    owner, repo = pr
    slug_full = f"{owner}/{repo}"
    if slug_full not in _WINDSURFRULES_REPOS:
        return None
    # Extract the rule slug from the URL path. Awesome-windsurfrules layout:
    #   .../blob/<branch>/rules/<slug>/.windsurfrules
    #   .../blob/<branch>/rules/global_rules/<slug>/...
    #   .../blob/<branch>/rules/windsurfrules/<slug>/...
    path_match = re.search(
        r"/(?:tree|blob)/[^/]+/rules/(?:global_rules/|windsurfrules/)?([^/?#]+)",
        su,
    )
    if not path_match:
        return None
    slug = path_match.group(1).strip().lower()
    if not slug:
        return None
    return ("windsurfrules", slug)


# Fields contributed by skills.sh that should be carried over to the
# winning entry even when a higher-priority source supplies the base record.
_SKILLS_SH_MERGE_FIELDS = ("install_count", "skills_sh_url", "skills_sh_scraped_at")

# Fields contributed by registry.modelcontextprotocol.io that should be
# carried over to the winning entry when a GitHub URL source wins.
_MCP_REGISTRY_MERGE_FIELDS = (
    "mcp_registry_status",
    "mcp_registry_published_at",
    "mcp_remotes",
)

# ISO 8601 UTC timestamp pattern accepted by skills_sh_scraped_at:
#   2026-01-30T04:51:07Z   或   2026-01-30T04:51:07.907Z
_SKILLS_SH_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")


def validate_skill_optional_fields(entry: dict) -> list[str]:
    """Validate the three optional skills.sh-contributed fields on a skill entry.

    All three fields are optional (向后兼容旧条目)，缺失不会报错。
    若存在则类型必须严格符合 catalog/schema.json：

      - install_count       : int, ≥ 0
      - skills_sh_url       : non-empty str (looks like http(s):// URL)
      - skills_sh_scraped_at: ISO 8601 string e.g. ``2026-01-30T04:51:07Z`` 或 ``.907Z``

    Returns a list of human-readable error messages (empty list = valid).

    Note: This is a lightweight ad-hoc check intended to be cheap enough to call
    inline from sync / merge pipelines. It does NOT attempt full URI parsing.
    """
    errors: list[str] = []
    eid = entry.get("id", "<unknown>")

    if "install_count" in entry:
        v = entry["install_count"]
        # bool is a subclass of int — disallow explicitly (True/False is not a count)
        if isinstance(v, bool) or not isinstance(v, int):
            errors.append(
                f'entry "{eid}" install_count must be int, got {type(v).__name__}'
            )
        elif v < 0:
            errors.append(f'entry "{eid}" install_count must be ≥ 0, got {v}')

    if "skills_sh_url" in entry:
        v = entry["skills_sh_url"]
        if not isinstance(v, str):
            errors.append(
                f'entry "{eid}" skills_sh_url must be str, got {type(v).__name__}'
            )
        elif v and not (v.startswith("http://") or v.startswith("https://")):
            errors.append(
                f'entry "{eid}" skills_sh_url must look like an http(s) URL, got {v!r}'
            )

    if "skills_sh_scraped_at" in entry:
        v = entry["skills_sh_scraped_at"]
        if not isinstance(v, str):
            errors.append(
                f'entry "{eid}" skills_sh_scraped_at must be str, got {type(v).__name__}'
            )
        # Empty string is tolerated as "field present but unset" — sync_skills_sh.py
        # initializes the field to "" before later filling it with the scraped time.
        elif v and not _SKILLS_SH_TS_RE.match(v):
            errors.append(
                f'entry "{eid}" skills_sh_scraped_at not ISO 8601, got {v!r}'
            )

    return errors


def _merge_skills_sh_fields(target: dict, donor: dict) -> None:
    """Copy non-empty skills.sh signal fields from donor onto target (target wins ties)."""
    for k in _SKILLS_SH_MERGE_FIELDS:
        v = donor.get(k)
        if v in (None, "", 0):
            continue
        if not target.get(k):
            target[k] = v


def _merge_mcp_registry_fields(target: dict, donor: dict) -> None:
    """Copy non-empty registry.modelcontextprotocol.io fields from donor onto target.

    Used when a GitHub URL entry wins identity collapse against a registry entry:
    the registry-supplied metadata (status / published_at / remotes) is carried
    onto the winner so consumers don't lose those signals. Existing non-empty
    target values are preserved (target wins ties).
    """
    for k in _MCP_REGISTRY_MERGE_FIELDS:
        v = donor.get(k)
        if v in (None, "", [], {}):
            continue
        if not target.get(k):
            target[k] = v


def _identity_key_for_entry(entry: dict):
    """Route an entry to its identity-collapse key by type.

    Returns the key tuple or ``None`` (entry passes through identity collapse).
    """
    etype = entry.get("type") or ""
    if etype == "skill":
        return skill_identity_key(entry)
    if etype == "mcp":
        return mcp_identity_key(entry)
    if etype == "rule":
        return rule_identity_key(entry)
    return None


def deduplicate(entries: list) -> list:
    """Deduplicate entries.

    Two-pass strategy:

    1. **Cross-source identity collapse** — group entries by an entry-type
       aware identity key (``skill_identity_key`` for skills, ``mcp_identity_key``
       for mcp). Keep the entry with the highest `source_priority`; merge
       sibling-source signal fields (skills.sh fields onto skill winners,
       registry.modelcontextprotocol.io fields onto mcp winners) onto the
       kept entry. Ties broken by input order (earlier wins).

       For mcp entries, **GitHub URL entries are preferred over registry URL
       entries** so that the surviving ``source_url`` stays a useful GitHub
       link (per spec catalog-entry-lifecycle); the registry's status /
       published_at / remotes fields are merged onto the winner.

    2. **Legacy id/source_url dedup** — for everything else (and as a
       safety net), keep the first entry per id and (for non-rule/prompt
       types) per normalized source_url.

    For rule/prompt types, only id-based dedup is applied (these types
    legitimately share a single repo-level source_url across many entries).
    """
    # --- Pass 1: type-aware identity collapse -----------------------------
    # Build groups keyed by per-type identity key. Entries without a key pass through.
    groups: dict[tuple, list[int]] = {}
    for idx, e in enumerate(entries):
        key = _identity_key_for_entry(e)
        if key is not None:
            groups.setdefault(key, []).append(idx)

    # For each group with >1 entry, choose the winner and mark losers.
    losers: set[int] = set()
    for key, idxs in groups.items():
        if len(idxs) <= 1:
            continue
        # Determine entry type by inspecting first entry in group (all entries
        # in a group share the same type by construction).
        group_type = entries[idxs[0]].get("type") or ""

        if group_type == "mcp":
            # spec catalog-entry-lifecycle: GitHub URL entry SHALL be preserved
            # and registry-supplied fields SHALL be merged onto it. So winner
            # selection prefers GitHub URLs first, then source_priority desc,
            # then original order.
            def _mcp_rank(i: int) -> tuple:
                su = entries[i].get("source_url") or ""
                is_registry = bool(_MCP_REGISTRY_URL_RE.match(su))
                return (
                    1 if is_registry else 0,           # GitHub URL first
                    -source_priority(su),              # then highest priority
                    i,                                 # then original order
                )
            ranked = sorted(idxs, key=_mcp_rank)
        elif group_type == "rule":
            # awesome-windsurfrules cross-repo collapse — prefer SchneiderSam
            # (canonical) over balqaasem (fork mirror). Both repos are in the
            # default 500 GitHub tier so source_priority alone can't tiebreak;
            # use an explicit canonical-repo bump.
            def _rule_rank(i: int) -> tuple:
                su = entries[i].get("source_url") or ""
                pr = _parse_owner_repo(su)
                slug = f"{pr[0]}/{pr[1]}" if pr else ""
                # 0 = canonical (SchneiderSam), 1 = mirror (balqaasem), 2 = other
                if slug == "schneidersam/awesome-windsurfrules":
                    canonical_rank = 0
                elif slug == "balqaasem/awesome-windsurfrules":
                    canonical_rank = 1
                else:
                    canonical_rank = 2
                return (
                    canonical_rank,
                    -source_priority(su),
                    i,
                )
            ranked = sorted(idxs, key=_rule_rank)
        else:
            # Skills (and any future identity-keyed type) — pure source_priority.
            ranked = sorted(
                idxs,
                key=lambda i: (
                    -source_priority(entries[i].get("source_url") or ""),
                    i,
                ),
            )

        winner_idx = ranked[0]
        winner = entries[winner_idx]
        for j in ranked[1:]:
            if group_type == "skill":
                _merge_skills_sh_fields(winner, entries[j])
            elif group_type == "mcp":
                _merge_mcp_registry_fields(winner, entries[j])
            losers.add(j)
        if group_type == "skill":
            # Idempotent self-merge so winners that already carry skills.sh
            # fields keep them in canonical form.
            _merge_skills_sh_fields(winner, winner)

    after_identity = [e for i, e in enumerate(entries) if i not in losers]

    # --- Pass 2: legacy id + url dedup (first-wins) -----------------------
    seen_ids: dict[str, dict] = {}
    seen_urls: dict[str, dict] = {}
    result: list = []
    url_dedup_skip_types = {"rule", "prompt"}
    for entry in after_identity:
        eid = entry.get("id", "")
        if eid and eid in seen_ids:
            continue

        source_url = entry.get("source_url", "")
        entry_type = entry.get("type", "")
        if source_url and entry_type not in url_dedup_skip_types:
            norm = normalize_source_url(source_url)
            if norm in seen_urls:
                continue
            seen_urls[norm] = entry

        if eid:
            seen_ids[eid] = entry
        result.append(entry)
    return result


def to_kebab_case(name: str) -> str:
    """Convert a name to kebab-case id."""
    s = re.sub(r"[^\w\s-]", "", name.lower())
    s = re.sub(r"[\s_]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s


def save_index(entries: list, output_path: str):
    """Save entries to a JSON index file."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2, ensure_ascii=False)
    logger.info(f"Saved {len(entries)} entries to {output_path}")


def load_index(path: str) -> list:
    """Load entries from a JSON index file. Returns empty list if not found."""
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.error(f"Failed to load {path}: {e}")
        return []


def is_coding_related(act: str, prompt_text: str) -> bool:
    """Check if a prompt is coding/development related."""
    text = f"{act} {prompt_text}".lower()
    return any(re.search(r'\b' + re.escape(kw) + r'\b', text) for kw in CODING_KEYWORDS)
