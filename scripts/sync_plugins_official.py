#!/usr/bin/env python3
"""Official Claude Code plugin marketplace sync.

Fetches `.claude-plugin/marketplace.json` from:
  - anthropics/claude-plugins-official  (source_priority=1000)
  - obra/superpowers-marketplace        (source_priority=950)

Parses each plugin entry, optionally fetches the per-plugin `plugin.json`
manifest to compute `manifest_completeness`, and writes the resulting
catalog entries to `catalog/plugins/index.json`.

Failure isolation (task 2.4):
  - Each marketplace source is wrapped in its own try/except block.
  - A parse / fetch failure for one source logs an ERROR and continues
    to the next source.
  - Non-zero exit status is returned ONLY if zero plugins were synced
    overall across both sources.

Implementation notes:
  - Standard library only (urllib, json) — matches the conventions of
    sync_mcp_registry.py / sync_skills.py.
  - Honors GITHUB_TOKEN for raw.githubusercontent.com requests.
  - source_trust is intentionally NOT written here; it's a derived
    health signal computed by the eval pipeline (task 5.x) based on the
    `source` field.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from typing import Optional

# Allow running both as `python scripts/sync_plugins_official.py` and as a module.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from .utils import categorize, extract_tags, save_index  # type: ignore
except ImportError:  # pragma: no cover - script-style invocation
    from utils import categorize, extract_tags, save_index  # type: ignore


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
OUTPUT_PATH = os.path.join(REPO_ROOT, "catalog", "plugins", "index.json")

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()
USER_AGENT = "everything-ai-coding-plugins-sync"

# Per-source config. `id` is the catalog `source` field value;
# `repo_slug` is the GitHub <owner>/<repo> hosting the marketplace.json;
# `branch` is the branch from which to fetch (defaults to "main").
SOURCES: list[dict] = [
    {
        "id": "claude-plugins-official",
        "repo_slug": "anthropics/claude-plugins-official",
        "branch": "main",
        "source_priority": 1000,
    },
    {
        "id": "superpowers-marketplace",
        "repo_slug": "obra/superpowers-marketplace",
        "branch": "main",
        "source_priority": 950,
    },
]

# manifest_completeness scoring (task 2.2).
MANIFEST_FULL_FIELDS = ("name", "version", "description", "author")
MANIFEST_COMPLETENESS_FULL = 1.0
MANIFEST_COMPLETENESS_PARTIAL = 0.7
MANIFEST_COMPLETENESS_NONE = 0.3


logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("sync_plugins_official")


# ---------------------------------------------------------------------------
# HTTP helpers (stdlib only)
# ---------------------------------------------------------------------------

def _http_get(url: str, timeout: int = 30) -> Optional[bytes]:
    """GET `url` with GITHUB_TOKEN auth (when targeting GitHub) and a UA header.

    Returns the response body bytes, or None on any error / non-2xx status.
    Errors are logged at WARNING level — caller decides if that's fatal.
    """
    headers = {"User-Agent": USER_AGENT}
    is_github = (
        "raw.githubusercontent.com" in url
        or url.startswith("https://api.github.com/")
        or "github.com" in url
    )
    if GITHUB_TOKEN and is_github:
        headers["Authorization"] = f"token {GITHUB_TOKEN}"

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            logger.debug("404 Not Found: %s", url)
        else:
            logger.warning("HTTP %s for %s: %s", e.code, url, e.reason)
        return None
    except (urllib.error.URLError, TimeoutError) as e:
        logger.warning("Network error for %s: %s", url, e)
        return None
    except Exception as e:  # noqa: BLE001 - keep the script robust
        logger.warning("Unexpected error fetching %s: %s", url, e)
        return None


def _http_get_json(url: str, timeout: int = 30) -> Optional[dict | list]:
    body = _http_get(url, timeout=timeout)
    if body is None:
        return None
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        logger.warning("JSON decode error for %s: %s", url, e)
        return None


# ---------------------------------------------------------------------------
# URL builders
# ---------------------------------------------------------------------------

def _marketplace_url(repo_slug: str) -> str:
    """User-facing GitHub URL of the marketplace repo (used for marketplace_url field)."""
    return f"https://github.com/{repo_slug}"


def _marketplace_json_url(repo_slug: str, branch: str) -> str:
    """raw.githubusercontent URL of the marketplace.json file."""
    return (
        f"https://raw.githubusercontent.com/{repo_slug}/{branch}"
        f"/.claude-plugin/marketplace.json"
    )


def _resolve_source_url(plugin_entry: dict, marketplace_repo: str, branch: str) -> str:
    """Determine the canonical `source_url` for a plugin entry.

    Marketplace `source` field can be:
      - "./plugins/foo"          → subfolder of marketplace repo
      - "github:owner/repo"      → external GitHub repo
      - "git+https://..."        → arbitrary git URL
      - "https://github.com/..." → direct GitHub URL
      - missing                  → fall back to marketplace repo URL
    """
    src = plugin_entry.get("source")
    if isinstance(src, dict):
        # Some marketplaces use {source: "github", repo: "owner/repo"} style.
        if src.get("source") == "github" and src.get("repo"):
            return f"https://github.com/{src['repo']}"
        if src.get("url"):
            src = src.get("url")
        else:
            src = ""

    if isinstance(src, str) and src:
        if src.startswith("github:"):
            return f"https://github.com/{src[len('github:'):]}"
        if src.startswith("https://") or src.startswith("http://"):
            return src
        if src.startswith("git+"):
            return src[len("git+"):]
        if src.startswith("./") or src.startswith("/"):
            sub = src.lstrip("./").lstrip("/")
            return f"https://github.com/{marketplace_repo}/tree/{branch}/{sub}"
    # Fallback: the marketplace repo itself.
    return _marketplace_url(marketplace_repo)


def _plugin_manifest_candidate_urls(
    plugin_entry: dict, marketplace_repo: str, branch: str
) -> list[str]:
    """Return raw URLs to try for fetching the plugin's plugin.json.

    Returns an empty list when the source is external (we don't follow
    cross-repo URLs in this task — manifest_completeness falls back to
    whatever the marketplace entry itself supplies).
    """
    src = plugin_entry.get("source")
    if isinstance(src, dict):
        src = src.get("url") or ""
    if not isinstance(src, str):
        return []

    # Only inspect manifest when the plugin lives in the marketplace repo itself.
    if src.startswith("./") or src.startswith("/"):
        sub = src.lstrip("./").lstrip("/").rstrip("/")
        return [
            f"https://raw.githubusercontent.com/{marketplace_repo}/{branch}"
            f"/{sub}/.claude-plugin/plugin.json",
            f"https://raw.githubusercontent.com/{marketplace_repo}/{branch}"
            f"/{sub}/plugin.json",
        ]
    return []


# ---------------------------------------------------------------------------
# manifest_completeness
# ---------------------------------------------------------------------------

def compute_manifest_completeness(manifest: Optional[dict]) -> float:
    """Score manifest completeness per task 2.2.

    - 1.0 if manifest contains all of name / version / description / author
    - 0.7 if the manifest is missing exactly one of `description` or `version`
          (other "partial" shapes also collapse to 0.7 conservatively)
    - 0.3 if no manifest is available at all
    """
    if not manifest or not isinstance(manifest, dict):
        return MANIFEST_COMPLETENESS_NONE

    def _present(key: str) -> bool:
        v = manifest.get(key)
        if v is None:
            return False
        if isinstance(v, str):
            return v.strip() != ""
        if isinstance(v, (list, dict)):
            return len(v) > 0
        return True

    have = {k: _present(k) for k in MANIFEST_FULL_FIELDS}
    if all(have.values()):
        return MANIFEST_COMPLETENESS_FULL

    # If only `description` or `version` (one of them) is missing → 0.7.
    # Anything else (e.g. missing name/author, or missing both desc+version) is
    # also weaker than full but treated as 0.7 per the spec's "missing one"
    # bucket — the rubric only enumerates two strata above the no-manifest
    # floor, so non-trivial partials still belong here.
    return MANIFEST_COMPLETENESS_PARTIAL


# ---------------------------------------------------------------------------
# Bundle counting
# ---------------------------------------------------------------------------

def _build_bundle(manifest: Optional[dict], plugin_name: str) -> dict:
    """Best-effort bundle stats from plugin.json.

    Counts default to 0 when the manifest doesn't expose them; this matches
    the schema (`bundle` always present, integer counts, `skills_namespaces`
    array possibly empty).
    """
    bundle = {
        "skills_count": 0,
        "commands_count": 0,
        "agents_count": 0,
        "mcp_servers_count": 0,
        "skills_namespaces": [],
    }
    if not isinstance(manifest, dict):
        return bundle

    def _count(value) -> int:
        if isinstance(value, list):
            return len(value)
        if isinstance(value, dict):
            return len(value)
        if isinstance(value, int):
            return value
        return 0

    bundle["skills_count"] = _count(manifest.get("skills"))
    bundle["commands_count"] = _count(manifest.get("commands"))
    bundle["agents_count"] = _count(manifest.get("agents"))
    bundle["mcp_servers_count"] = _count(
        manifest.get("mcpServers") or manifest.get("mcp_servers")
    )

    skills = manifest.get("skills")
    namespaces: list[str] = []
    if isinstance(skills, list):
        for s in skills:
            if isinstance(s, str) and s:
                namespaces.append(f"{plugin_name}:{s}")
            elif isinstance(s, dict):
                sn = s.get("name") or s.get("id")
                if sn:
                    namespaces.append(f"{plugin_name}:{sn}")
    elif isinstance(skills, dict):
        for sn in skills.keys():
            if sn:
                namespaces.append(f"{plugin_name}:{sn}")
    bundle["skills_namespaces"] = namespaces
    return bundle


# ---------------------------------------------------------------------------
# Slug / id helpers
# ---------------------------------------------------------------------------

_SLUG_RE = re.compile(r"[^a-z0-9-]+")


def _slugify(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[\s_./]+", "-", s)
    s = _SLUG_RE.sub("-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s


def _build_id(source_id: str, plugin_name: str) -> str:
    # Use a per-source prefix to avoid collisions when two marketplaces ship
    # plugins with the same name. Prefix is intentionally short and stable.
    prefix = {
        "claude-plugins-official": "anthropic",
        "superpowers-marketplace": "obra",
    }.get(source_id, _slugify(source_id))
    return _slugify(f"{prefix}-{plugin_name}")


# ---------------------------------------------------------------------------
# Per-plugin entry construction
# ---------------------------------------------------------------------------

def _author_string(author) -> str:
    if isinstance(author, str):
        return author
    if isinstance(author, dict):
        return author.get("name") or author.get("email") or ""
    return ""


def _entry_from_plugin(
    plugin_entry: dict,
    source_cfg: dict,
    last_synced_iso: str,
) -> Optional[dict]:
    """Convert one marketplace plugin definition into a catalog entry.

    Returns None if the plugin definition is too malformed to produce a
    usable entry (e.g. missing name).
    """
    name = (plugin_entry.get("name") or "").strip()
    if not name:
        logger.warning(
            "Skipping plugin without a name in source=%s: %r",
            source_cfg["id"],
            plugin_entry,
        )
        return None

    repo_slug = source_cfg["repo_slug"]
    branch = source_cfg["branch"]
    description = (plugin_entry.get("description") or "").strip()
    version = (plugin_entry.get("version") or "").strip()
    author_str = _author_string(plugin_entry.get("author"))
    upstream_category = (plugin_entry.get("category") or "").strip()
    upstream_tags = plugin_entry.get("tags")
    if not isinstance(upstream_tags, list):
        upstream_tags = []

    # Try fetching plugin.json for richer manifest data + bundle stats.
    manifest: Optional[dict] = None
    for url in _plugin_manifest_candidate_urls(plugin_entry, repo_slug, branch):
        candidate = _http_get_json(url)
        if isinstance(candidate, dict):
            manifest = candidate
            break

    # If we couldn't fetch a manifest but the marketplace entry itself supplies
    # name+version+description+author, treat the entry as its own manifest for
    # the purposes of completeness scoring (per task spec wording).
    if manifest is None and (description or version or author_str):
        synthetic_manifest = {
            "name": name,
            "version": version,
            "description": description,
            "author": author_str,
        }
        manifest_for_score = synthetic_manifest
    else:
        manifest_for_score = manifest

    completeness = compute_manifest_completeness(manifest_for_score)
    bundle = _build_bundle(manifest, name)

    # Description fallback: marketplace > manifest > "".
    if not description and isinstance(manifest, dict):
        description = (manifest.get("description") or "").strip()

    # Version fallback similarly.
    if not version and isinstance(manifest, dict):
        version = (manifest.get("version") or "").strip()

    source_url = _resolve_source_url(plugin_entry, repo_slug, branch)
    marketplace_url = _marketplace_url(repo_slug)

    # Tags / category — pass marketplace-supplied values through `categorize`
    # / `extract_tags` so plugin entries follow the same enrichment heuristics
    # as the existing types. Upstream tags are preserved verbatim.
    derived_tags = extract_tags(name, description)
    tags: list[str] = []
    seen_tags: set[str] = set()
    for t in list(upstream_tags) + derived_tags:
        if not isinstance(t, str):
            continue

        tl = t.strip().lower()
        if tl and tl not in seen_tags:
            seen_tags.add(tl)
            tags.append(tl)

    category = categorize(
        name=name,
        description=description,
        tags=tags,
        upstream_category=upstream_category,
    )

    entry: dict = {
        "id": _build_id(source_cfg["id"], name),
        "name": name,
        "type": "plugin",
        "description": description,
        "source_url": source_url,
        "category": category,
        "tags": tags,
        "tech_stack": [],
        "source": source_cfg["id"],
        "source_priority": source_cfg["source_priority"],
        "marketplace_url": marketplace_url,
        "platforms": ["claude-code"],
        "install": {
            "method": "plugin_marketplace",
            "marketplace": repo_slug,
            "plugin_name": name,
        },
        "bundle": bundle,
        "manifest_completeness": completeness,
        "last_synced": last_synced_iso,
        # Health pipeline reads these; they're populated later by the
        # enrichment / health stages (kept here as null/defaults for shape).
        "stars": None,
        "version": version,
    }
    return entry


# ---------------------------------------------------------------------------
# Per-source sync (with isolation)
# ---------------------------------------------------------------------------

def sync_one_source(source_cfg: dict, last_synced_iso: str) -> list[dict]:
    """Sync a single marketplace source.

    Returns the list of catalog entries from this source. On any failure
    logs ERROR and returns []; the caller (main) decides whether the
    overall script exits non-zero.
    """
    repo_slug = source_cfg["repo_slug"]
    branch = source_cfg["branch"]
    src_id = source_cfg["id"]
    url = _marketplace_json_url(repo_slug, branch)
    logger.info("Fetching marketplace.json: source=%s url=%s", src_id, url)

    try:
        body = _http_get(url)
        if body is None:
            logger.error(
                "Failed to fetch marketplace.json for source=%s (network/HTTP error)",
                src_id,
            )
            return []
        try:
            data = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            logger.error(
                "Failed to parse marketplace.json for source=%s: %s",
                src_id,
                e,
            )
            return []

        if not isinstance(data, dict):
            logger.error(
                "Unexpected marketplace.json shape for source=%s: top-level is %s",
                src_id,
                type(data).__name__,
            )
            return []

        plugins = data.get("plugins")
        if not isinstance(plugins, list):
            logger.error(
                "marketplace.json for source=%s has no `plugins` array (got %s)",
                src_id,
                type(plugins).__name__,
            )
            return []

        entries: list[dict] = []
        for raw in plugins:
            if not isinstance(raw, dict):
                logger.warning(
                    "Skipping non-dict plugin entry in source=%s: %r",
                    src_id,
                    raw,
                )
                continue
            try:
                entry = _entry_from_plugin(raw, source_cfg, last_synced_iso)
            except Exception as e:  # noqa: BLE001 - never let one entry kill the source
                logger.warning(
                    "Failed to build entry for plugin %r in source=%s: %s",
                    raw.get("name"),
                    src_id,
                    e,
                )
                continue
            if entry is not None:
                entries.append(entry)

        logger.info(
            "Source=%s yielded %d plugin entries (from %d raw)",
            src_id,
            len(entries),
            len(plugins),
        )
        return entries
    except Exception as e:  # noqa: BLE001 - guarantee failure isolation
        logger.error(
            "Unhandled error syncing source=%s: %s",
            src_id,
            e,
        )
        return []


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    """Current UTC timestamp in `YYYY-MM-DDTHH:MM:SSZ` form."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Sync the official Claude Code plugin marketplaces "
            "(anthropics/claude-plugins-official + obra/superpowers-marketplace) "
            "into catalog/plugins/index.json."
        ),
    )
    parser.add_argument(
        "--output",
        default=OUTPUT_PATH,
        help=f"Output index.json path (default: {OUTPUT_PATH})",
    )
    args = parser.parse_args(argv)

    # Catalog schema declares `last_synced` as `format: date` (YYYY-MM-DD),
    # matching sync_mcp_registry.py / sync_skills.py / sync_windsurfrules.py.
    last_synced_iso = date.today().isoformat()
    all_entries: list[dict] = []
    failed_sources: list[str] = []

    for source_cfg in SOURCES:
        entries = sync_one_source(source_cfg, last_synced_iso)
        if not entries:
            failed_sources.append(source_cfg["id"])
        all_entries.extend(entries)

    # Stable ordering: by id, so diffs in git remain readable.
    all_entries.sort(key=lambda e: e.get("id", ""))

    if not all_entries:
        logger.error(
            "Zero plugins synced overall (failed sources: %s); exiting non-zero.",
            ", ".join(failed_sources) or "<none>",
        )
        return 1

    save_index(all_entries, args.output)
    logger.info(
        "Wrote %d plugin entries to %s (failed sources: %s)",
        len(all_entries),
        args.output,
        ", ".join(failed_sources) or "<none>",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
