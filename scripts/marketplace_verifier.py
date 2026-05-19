#!/usr/bin/env python3
"""Plugin marketplace manifest verifier.

Shared helper used by ``sync_plugins_dev.py`` and ``sync_plugins_official.py``
to populate the new ``install.marketplace_name`` and
``install.marketplace_verified`` fields on plugin catalog entries.

The verifier resolves a GitHub repo slug (``owner/repo``) to the
``name`` field inside that repo's ``marketplace.json`` (Claude Code's
marketplace manifest), and confirms whether the candidate ``plugin_name``
is actually listed in the manifest's ``plugins[]`` array.

Public API:

  * ``verify_marketplace(repo, plugin_name, cache) -> (marketplace_name, verified)``
  * ``load_cache(path) -> dict``
  * ``save_cache(path, cache) -> None``

Implementation notes:

  * Standard library only (``urllib``, ``json``, ``re``).
  * 5s per-attempt timeout, 3 attempts per URL candidate.
  * Tries ``.claude-plugin/marketplace.json`` then ``marketplace.json`` on
    ``main`` then ``master`` (4 URL candidates total).
  * ``marketplace_name`` must match ``^[A-Za-z0-9._-]+$`` — values
    containing ``@`` / ``/`` / spaces are treated as missing.
  * In-memory ``cache`` is a mutable dict keyed by ``repo``. When a
    ``repo`` key is missing the verifier performs a fresh fetch and
    populates the dict; when present the cached entry is reused.
  * The disk cache is JSON of the same shape. Callers load it at sync
    startup and save it at sync end so future runs can recover from
    upstream outages without losing data.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Optional


logger = logging.getLogger("marketplace_verifier")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")

_BRANCHES = ("main", "master")
_PATHS = (".claude-plugin/marketplace.json", "marketplace.json")

_RAW_URL = "https://raw.githubusercontent.com/{repo}/{branch}/{path}"

_TIMEOUT_SECONDS = 5
_RETRIES_PER_URL = 3
_RETRY_SLEEP_SECONDS = 0.5

USER_AGENT = "everything-ai-coding-marketplace-verifier"


# ---------------------------------------------------------------------------
# Disk cache helpers
# ---------------------------------------------------------------------------

def load_cache(path: str) -> dict:
    """Load a marketplace manifest cache from ``path``.

    Returns an empty dict if the file is missing or unreadable. The cache
    structure is ``{repo: {"marketplace_name": str | None, "plugin_names":
    list[str], "fetched_at": str}}``.
    """
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("Failed to load marketplace cache %s: %s", path, e)
        return {}
    if not isinstance(data, dict):
        logger.warning("Marketplace cache %s has unexpected shape", path)
        return {}
    return data


def save_cache(path: str, cache: dict) -> None:
    """Persist ``cache`` to ``path`` as JSON. Creates the parent directory."""
    if not path:
        return
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2, sort_keys=True)
    except OSError as e:
        logger.warning("Failed to save marketplace cache %s: %s", path, e)


# ---------------------------------------------------------------------------
# HTTP fetch (raw.githubusercontent.com)
# ---------------------------------------------------------------------------

def _fetch_url(url: str) -> Optional[bytes]:
    """GET ``url`` and return raw bytes on success; None on any failure.

    Retries up to ``_RETRIES_PER_URL`` times with a short sleep. 404 is
    returned as None on the first attempt (no point retrying — file
    genuinely missing). Network / 5xx retry.
    """
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    last_err: Optional[Exception] = None
    for attempt in range(_RETRIES_PER_URL):
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT_SECONDS) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            last_err = e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_err = e
        except Exception as e:  # noqa: BLE001 - keep helper resilient
            last_err = e
        if attempt < _RETRIES_PER_URL - 1:
            time.sleep(_RETRY_SLEEP_SECONDS)
    if last_err is not None:
        logger.debug("Fetch failed for %s: %s", url, last_err)
    return None


def _fetch_manifest(repo: str) -> Optional[dict]:
    """Try the 4 candidate marketplace.json locations for ``repo``.

    Returns the parsed JSON dict on first success, or None when all
    candidates fail.
    """
    for branch in _BRANCHES:
        for path in _PATHS:
            url = _RAW_URL.format(repo=repo, branch=branch, path=path)
            body = _fetch_url(url)
            if body is None:
                continue
            try:
                data = json.loads(body.decode("utf-8", errors="replace"))
            except (UnicodeDecodeError, json.JSONDecodeError) as e:
                logger.warning(
                    "Manifest JSON parse failed for %s (%s): %s",
                    repo, url, e,
                )
                continue
            if not isinstance(data, dict):
                logger.warning(
                    "Manifest at %s is not a JSON object", url,
                )
                continue
            return data
    return None


def _extract_manifest_fields(manifest: dict) -> tuple[Optional[str], list]:
    """Pull ``name`` and the set of ``plugin_names`` out of a manifest.

    Returns ``(marketplace_name, plugin_names)``. ``marketplace_name`` may
    be None when the manifest lacks a usable ``name`` field; in that case
    the caller treats the entry as unverified regardless of plugin_names.
    """
    raw_name = manifest.get("name") if isinstance(manifest.get("name"), str) else None
    if raw_name:
        raw_name = raw_name.strip()
    marketplace_name: Optional[str] = raw_name if raw_name and _NAME_RE.match(raw_name) else None

    plugin_names: list = []
    plugins_arr = manifest.get("plugins")
    if isinstance(plugins_arr, list):
        for item in plugins_arr:
            if isinstance(item, dict):
                nm = item.get("name")
                if isinstance(nm, str) and nm.strip():
                    plugin_names.append(nm.strip())
    return marketplace_name, plugin_names


# ---------------------------------------------------------------------------
# Public verifier
# ---------------------------------------------------------------------------

def verify_marketplace(
    repo: str,
    plugin_name: str,
    cache: dict,
) -> tuple[Optional[str], bool]:
    """Resolve and verify a marketplace for a plugin entry.

    Args:
      repo: GitHub repo slug ``owner/repo``. Empty / non-string inputs
            short-circuit to ``(None, False)``.
      plugin_name: The expected plugin name to look for in the manifest's
            ``plugins[]`` array.
      cache: Mutable dict shared across all calls in this sync run. On
            cache miss the verifier performs a fresh fetch and writes the
            result back into the dict.

    Returns:
      ``(marketplace_name, verified)``. ``marketplace_name`` is the value
      from the manifest's ``name`` field (validated against
      ``^[A-Za-z0-9._-]+$``) or None when no valid name was obtained.
      ``verified`` is True iff a valid marketplace_name exists AND
      ``plugin_name`` is in the manifest's plugins[] array.
    """
    if not isinstance(repo, str) or not repo or "/" not in repo:
        return (None, False)
    if not isinstance(plugin_name, str) or not plugin_name:
        return (None, False)

    entry = cache.get(repo)
    if not isinstance(entry, dict):
        manifest = _fetch_manifest(repo)
        if manifest is None:
            return (None, False)
        marketplace_name, plugin_names = _extract_manifest_fields(manifest)
        entry = {
            "marketplace_name": marketplace_name,
            "plugin_names": plugin_names,
            "fetched_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        cache[repo] = entry

    marketplace_name = entry.get("marketplace_name") if isinstance(entry.get("marketplace_name"), str) else None
    plugin_names = entry.get("plugin_names") if isinstance(entry.get("plugin_names"), list) else []

    if not marketplace_name:
        return (None, False)

    verified = plugin_name in plugin_names
    return (marketplace_name, verified)
