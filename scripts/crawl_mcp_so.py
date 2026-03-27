#!/usr/bin/env python3
"""Crawl mcp.so to build MCP server seed data with real install configs.

Supports resumable crawling — progress is saved after each detail page,
so interrupted crawls can be resumed with the same command.
"""

import argparse
import html
import json
import os
import re
import sys
import time
from datetime import date
from urllib.parse import quote
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError

sys.path.insert(0, os.path.dirname(__file__))
from utils import get_stars, to_kebab_case, categorize, save_index, logger

CATALOG_DIR = os.path.join(os.path.dirname(__file__), "..", "catalog", "mcp")
SEED_PATH = os.path.join(CATALOG_DIR, "mcp_so_seed.json")
STATE_PATH = os.path.join(CATALOG_DIR, "crawl_state.json")
TODAY = date.today().isoformat()

CATEGORY_URL = "https://mcp.so/category/developer-tools"
LATEST_URL = "https://mcp.so/servers?tag=latest"
BASE_URL = "https://mcp.so"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

CONSECUTIVE_KNOWN_STOP = 10
REQUEST_DELAY = 1.0
MAX_CONSECUTIVE_FAILURES = 5


def _id_from_github_url(url: str) -> str:
    """Generate ID from GitHub URL as owner-repo, matching sync_mcp convention."""
    m = re.match(r'https?://github\.com/([^/]+)/([^/]+)', url.rstrip('/'))
    if not m:
        return ""
    owner, repo = m.group(1), m.group(2)
    if owner == "MCP-Mirror" and "_" in repo:
        owner, repo = repo.split("_", 1)
    return to_kebab_case(f"{owner}-{repo}")


def fetch_page(url: str) -> str:
    """Fetch a page with browser User-Agent. Returns HTML string or empty."""
    req = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except (HTTPError, URLError, TimeoutError) as e:
        logger.warning(f"Failed to fetch {url}: {e}")
        return ""


def parse_listing_page(page_html: str) -> list[str]:
    """Extract server detail page URLs from a listing page.
    Returns list of paths like '/server/name/author'."""
    urls = re.findall(r'href="(/server/[^"]+)"', page_html)
    seen = set()
    result = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            result.append(u)
    return result


def parse_detail_page(page_html: str, detail_path: str) -> dict | None:
    """Parse a server detail page and extract structured data.
    Returns entry dict or None if page is broken."""
    if "Project not found" in page_html:
        logger.warning(f"Project not found: {detail_path}")
        return None

    # Server name
    name_match = re.search(r'<h1[^>]*class="[^"]*text-xl[^"]*font-bold[^"]*"[^>]*>([^<]+)</h1>', page_html)
    if not name_match:
        name_match = re.search(r'<h1[^>]*>([^<]+)</h1>', page_html)
    name = html.unescape(name_match.group(1).strip()) if name_match else ""

    # Description from meta tag
    desc_match = re.search(r'<meta\s+name="description"\s+content="([^"]*)"', page_html)
    description = html.unescape(desc_match.group(1).strip()) if desc_match else ""

    # GitHub URL (Visit Server link)
    github_match = re.search(r'href="(https://github\.com/[^"]+)"[^>]*>\s*Visit Server', page_html, re.DOTALL)
    github_url = github_match.group(1).strip() if github_match else ""
    github_url = re.sub(r'[/#?]$', '', github_url)

    if not github_url:
        logger.debug(f"No GitHub URL found for {detail_path}")
        return None

    # Tags
    tags = re.findall(r'href="/tag/([^"]+)"', page_html)
    tags = [re.sub(r'<!--.*?-->', '', t).strip() for t in tags]
    tags = [t for t in tags if t]

    # Category
    cat_match = re.findall(r'href="/category/([^"]+)"', page_html)
    mcp_so_category = cat_match[0] if cat_match else "developer-tools"

    # Server Config (mcpServers JSON)
    install_config = None
    install_method = "manual"
    placeholder_hints = {}

    config_match = re.search(
        r'Server Config</h2>.*?<code[^>]*>(.*?)</code>',
        page_html, re.DOTALL
    )
    if config_match:
        json_text = re.sub(r'<[^>]+>', '', config_match.group(1))
        json_text = html.unescape(json_text).strip()
        try:
            parsed = json.loads(json_text)
            servers = parsed.get("mcpServers", {})
            if servers:
                first_key = next(iter(servers))
                server_config = servers[first_key]
                install_config = {
                    "command": server_config.get("command", ""),
                    "args": server_config.get("args", []),
                }
                if server_config.get("env"):
                    install_config["env"] = server_config["env"]
                install_method, placeholder_hints = detect_placeholders(install_config)
        except (json.JSONDecodeError, StopIteration):
            logger.debug(f"Failed to parse Server Config JSON for {detail_path}")

    entry = {
        "id": _id_from_github_url(github_url),
        "name": name,
        "type": "mcp",
        "description": description,
        "source_url": github_url,
        "stars": 0,
        "category": categorize(name, description, tags, mcp_so_category),
        "tags": tags,
        "tech_stack": [],
        "install": {"method": install_method},
        "source": "mcp.so",
        "last_synced": TODAY,
    }

    if install_config:
        entry["install"]["config"] = install_config
    if placeholder_hints:
        entry["install"]["placeholder_hints"] = placeholder_hints

    return entry


def detect_placeholders(config: dict) -> tuple[str, dict]:
    """Detect placeholder patterns in install config.
    Returns (method, placeholder_hints)."""
    hints = {}
    args = config.get("args", [])
    env = config.get("env", {})

    for arg in args:
        if isinstance(arg, str):
            matches = re.findall(r'<([A-Za-z][A-Za-z0-9_-]+)>', arg)
            for m in matches:
                hints[m] = f"Replace with actual {m.lower().replace('_', ' ').replace('-', ' ')}"

    for key, val in env.items():
        if isinstance(val, str):
            if val == "" or re.match(r'^(YOUR_|your_)', val) or re.match(r'^<.+>$', val):
                hints[key] = f"Set your {key}"

    if hints:
        return "mcp_config_template", hints
    return "mcp_config", {}


# ── State persistence ──────────────────────────────────────────────

def load_state() -> dict:
    """Load crawl state from file."""
    if os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {
        "last_full_crawl": None,
        "last_incremental_crawl": None,
        "known_detail_urls": [],
        "pending_detail_urls": [],
        "processed_detail_urls": [],
        "listing_done": False,
        "listing_page": 0,
    }


def save_state(state: dict):
    """Save crawl state to file."""
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def load_seed() -> list:
    """Load existing seed data."""
    if os.path.exists(SEED_PATH):
        try:
            with open(SEED_PATH, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return []


def save_seed(entries: list):
    """Save seed data."""
    save_index(entries, SEED_PATH)


# ── Resumable full crawl ───────────────────────────────────────────

def crawl_full(max_pages: int = 500):
    """Full crawl with resume support.

    Progress is checkpointed after every listing page and every detail page.
    Re-run the same command to resume from where it stopped.
    Use --force-restart to discard previous progress and start fresh.
    """
    state = load_state()

    # Phase 1: Collect detail URLs from listing pages (resumable)
    if not state.get("listing_done"):
        start_page = state.get("listing_page", 0) + 1
        pending = list(state.get("pending_detail_urls", []))
        pending_set = set(pending)

        if start_page > 1:
            logger.info(f"=== Resuming listing crawl from page {start_page} (already have {len(pending)} URLs) ===")
        else:
            logger.info("=== Full crawl: developer-tools category ===")

        for page_num in range(start_page, max_pages + 1):
            sep = "&" if "?" in CATEGORY_URL else "?"
            url = f"{CATEGORY_URL}{sep}page={page_num}"
            logger.info(f"Fetching listing page {page_num}: {url}")

            page_html = fetch_page(url)
            if not page_html:
                logger.warning(f"Empty response for page {page_num}, stopping listing phase")
                break

            detail_urls = parse_listing_page(page_html)
            if not detail_urls:
                logger.info(f"No more entries on page {page_num}, listing complete")
                break

            new_on_page = 0
            for u in detail_urls:
                if u not in pending_set:
                    pending_set.add(u)
                    pending.append(u)
                    new_on_page += 1
            logger.info(f"  Found {len(detail_urls)} entries, {new_on_page} new (total: {len(pending)})")

            # Checkpoint after each listing page
            state["pending_detail_urls"] = pending
            state["listing_page"] = page_num
            save_state(state)

            time.sleep(REQUEST_DELAY)

        state["listing_done"] = True
        state["pending_detail_urls"] = pending
        save_state(state)
        logger.info(f"Listing phase complete: {len(pending)} detail URLs collected")
    else:
        pending = list(state.get("pending_detail_urls", []))
        logger.info(f"=== Listing already done, {len(pending)} URLs on file ===")

    # Phase 2: Fetch detail pages (resumable)
    processed = set(state.get("processed_detail_urls", []))
    remaining = [p for p in pending if p not in processed]

    if not remaining:
        logger.info("All detail pages already processed")
        _finalize_full_crawl(state, pending)
        return

    logger.info(f"Detail phase: {len(remaining)} remaining ({len(processed)} already done)")

    seed = load_seed()
    seed_urls = {e.get("source_url", "").lower() for e in seed}
    consecutive_failures = 0

    for i, path in enumerate(remaining):
        encoded_path = quote(path, safe='/:@')
        url = f"{BASE_URL}{encoded_path}"
        logger.info(f"[{len(processed)+1}/{len(pending)}] Fetching detail: {path}")

        page_html = fetch_page(url)
        if not page_html:
            consecutive_failures += 1
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                logger.error(
                    f"Hit {MAX_CONSECUTIVE_FAILURES} consecutive failures — "
                    f"possible rate limit. Saving progress and stopping.\n"
                    f"  Processed: {len(processed)}/{len(pending)}\n"
                    f"  Re-run the same command to resume."
                )
                state["processed_detail_urls"] = list(processed)
                save_state(state)
                return
            # Mark as processed (skip) but don't add to seed
            processed.add(path)
            state["processed_detail_urls"] = list(processed)
            save_state(state)
            continue

        consecutive_failures = 0

        entry = parse_detail_page(page_html, path)
        if entry:
            # Fetch GitHub stars
            if entry.get("source_url"):
                stars = get_stars(entry["source_url"])
                entry["stars"] = stars if stars > 0 else -1

            # Deduplicate against existing seed
            if entry.get("source_url", "").lower() not in seed_urls:
                seed.append(entry)
                seed_urls.add(entry["source_url"].lower())

        # Mark processed and checkpoint
        processed.add(path)
        state["processed_detail_urls"] = list(processed)
        save_state(state)

        # Save seed every 50 entries for safety
        if len(processed) % 50 == 0:
            save_seed(seed)
            logger.info(f"  Checkpoint: {len(seed)} entries saved, {len(processed)}/{len(pending)} processed")

        time.sleep(REQUEST_DELAY)

    # Final save
    save_seed(seed)
    _finalize_full_crawl(state, pending)


def _finalize_full_crawl(state: dict, all_detail_paths: list):
    """Clean up state after a full crawl completes."""
    state["last_full_crawl"] = TODAY
    state["known_detail_urls"] = all_detail_paths
    # Clear resume fields
    state.pop("pending_detail_urls", None)
    state.pop("processed_detail_urls", None)
    state.pop("listing_done", None)
    state.pop("listing_page", None)
    save_state(state)

    seed = load_seed()
    logger.info(f"Full crawl complete: {len(seed)} entries in seed")


# ── Incremental crawl ─────────────────────────────────────────────

def crawl_incremental():
    """Incremental crawl via latest page."""
    logger.info("=== Incremental crawl: latest page ===")

    state = load_state()
    known_urls = set(state.get("known_detail_urls", []))
    existing_seed = load_seed()
    existing_source_urls = {e.get("source_url") for e in existing_seed if e.get("source_url")}

    new_detail_paths = []
    consecutive_known = 0

    for page_num in range(1, 500):
        sep = "&" if "?" in LATEST_URL else "?"
        url = f"{LATEST_URL}{sep}page={page_num}"
        logger.info(f"Fetching latest page {page_num}")

        page_html = fetch_page(url)
        if not page_html:
            break

        detail_urls = parse_listing_page(page_html)
        if not detail_urls:
            break

        page_has_new = False
        for detail_path in detail_urls:
            if detail_path in known_urls:
                consecutive_known += 1
                if consecutive_known >= CONSECUTIVE_KNOWN_STOP:
                    logger.info(f"Hit {CONSECUTIVE_KNOWN_STOP} consecutive known entries, stopping")
                    break
            else:
                consecutive_known = 0
                page_has_new = True
                new_detail_paths.append(detail_path)

        if consecutive_known >= CONSECUTIVE_KNOWN_STOP:
            break

        if not page_has_new:
            logger.info(f"No new entries on page {page_num}")

        time.sleep(REQUEST_DELAY)

    if not new_detail_paths:
        logger.info("No new entries found")
        state["last_incremental_crawl"] = TODAY
        save_state(state)
        return

    logger.info(f"Found {len(new_detail_paths)} new entries, fetching details...")

    # Fetch details (with per-entry checkpoint)
    for i, path in enumerate(new_detail_paths):
        encoded_path = quote(path, safe='/:@')
        url = f"{BASE_URL}{encoded_path}"
        logger.info(f"[{i+1}/{len(new_detail_paths)}] Fetching detail: {path}")

        page_html = fetch_page(url)
        if not page_html:
            continue

        entry = parse_detail_page(page_html, path)
        if not entry:
            continue

        if entry.get("source_url"):
            stars = get_stars(entry["source_url"])
            entry["stars"] = stars if stars > 0 else -1

        if entry.get("source_url") not in existing_source_urls:
            existing_seed.append(entry)
            existing_source_urls.add(entry["source_url"])

        known_urls.add(path)
        time.sleep(REQUEST_DELAY)

    # Save
    save_seed(existing_seed)
    state["last_incremental_crawl"] = TODAY
    state["known_detail_urls"] = list(known_urls)
    save_state(state)

    logger.info(f"Incremental crawl complete: {len(existing_seed)} total entries in seed")


# ── CLI ────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Crawl mcp.so for MCP server data")
    parser.add_argument(
        "--mode", choices=["full", "incremental"], default="incremental",
        help="full: crawl developer-tools category entirely; incremental: crawl latest page for new entries"
    )
    parser.add_argument(
        "--max-pages", type=int, default=500,
        help="Max listing pages to crawl (default: 500, useful for testing with small values)"
    )
    parser.add_argument(
        "--force-restart", action="store_true",
        help="Discard previous crawl progress and start fresh"
    )
    args = parser.parse_args()

    if args.force_restart:
        state = load_state()
        for key in ["pending_detail_urls", "processed_detail_urls", "listing_done", "listing_page"]:
            state.pop(key, None)
        save_state(state)
        logger.info("Cleared previous crawl progress")

    if args.mode == "full":
        crawl_full(max_pages=args.max_pages)
    else:
        crawl_incremental()


if __name__ == "__main__":
    main()
