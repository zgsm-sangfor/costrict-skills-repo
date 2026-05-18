#!/usr/bin/env python3
"""Merge all type-specific indexes and curated files into catalog/index.json."""

import argparse
import json
import os
import sys
from typing import Any
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
try:
    from .utils import (
        load_index,
        save_index,
        deduplicate,
        categorize,
        extract_tags,
        normalize_source_url,
        get_repo_meta,
        logger,
    )
    from .enrichment_orchestrator import enrich_entries
    from .scoring_governor import apply_governance
    from .catalog_lifecycle import (
        overlay_added_at,
        build_incremental_recrawl_candidates,
        backfill_missing_added_at,
        overlay_preserved_fields,
    )
except ImportError:
    from utils import (
        load_index,
        save_index,
        deduplicate,
        categorize,
        extract_tags,
        normalize_source_url,
        get_repo_meta,
        logger,
    )
    from enrichment_orchestrator import enrich_entries
    from scoring_governor import apply_governance
    from catalog_lifecycle import (
        overlay_added_at,
        build_incremental_recrawl_candidates,
        backfill_missing_added_at,
        overlay_preserved_fields,
    )

CATALOG_DIR = os.path.join(os.path.dirname(__file__), "..", "catalog")
# Resource-type sub-directories under catalog/. Entry-level `type` values are
# singular (mcp / skill / rule / prompt / plugin); these directory names are
# plural to match the on-disk layout (catalog/<dir>/index.json + curated.json).
TYPES = ["mcp", "skills", "rules", "prompts", "plugins"]
TODAY = date.today().isoformat()


def _apply_bundled_in_annotations(entries: list[dict], log=logger) -> list[dict]:
    """Soft-annotate skill entries that are bundled by a plugin entry, and
    write the reverse mapping (``bundle.bundled_skill_ids``) on plugin entries.

    For each entry whose ``type == "plugin"``, scan ``bundle.skills_namespaces``
    (a list of ``"<plugin-name>:<skill-name>"`` strings, per the plugin manifest
    contract). For every namespace string, locate a matching skill entry and
    set ``bundled_in: <plugin-id>`` on it.

    Match resolution (first hit wins, in this order):
      1. Skill ``namespace`` field equals the namespace string verbatim
         (e.g. ``superpowers:brainstorming``). This is the canonical match.
      2. Skill ``id`` equals the namespace string verbatim.
      3. Slugified fallback: skill ``id`` equals ``<plugin-name>-<skill-name>``
         derived by replacing ``:`` with ``-`` (handles the common case where
         skills are stored as ``superpowers-brainstorming``).

    In the same pass, populate ``plugin["bundle"]["bundled_skill_ids"]`` — a
    list **position-aligned** with ``bundle.skills_namespaces``: element[i] is
    the matched skill's catalog ``id``, or ``None`` if no skill matched (orphan).
    Plugins whose ``skills_namespaces`` is missing or empty do NOT get the
    field written (it stays absent rather than being set to ``[]``).

    Mutates ``entries`` in place and also returns it. Logs a single summary
    line per spec plugin-bundle-dedup §"Dedup correctness logging" and a
    WARNING per orphan namespace.
    """
    plugin_entries = [e for e in entries if (e.get("type") or "") == "plugin"]
    skill_entries = [e for e in entries if (e.get("type") or "") == "skill"]

    skills_by_namespace: dict[str, dict] = {}
    skills_by_id: dict[str, dict] = {}
    # Index skills by the trailing path segment of their source_url so we can
    # match plugin namespaces like "superpowers:brainstorming" against catalog
    # skills mirrored under different repos (e.g. sickn33/...) whose
    # source_url ends in /skills/brainstorming. Many skills share names — so
    # we keep a list and pick the first hit per (plugin_repo, skill_name) pair
    # below to avoid arbitrary cross-plugin attribution.
    skills_by_source_skill_name: dict[str, list[dict]] = {}
    for s in skill_entries:
        ns = s.get("namespace")
        if isinstance(ns, str) and ns:
            skills_by_namespace.setdefault(ns, s)
        sid = s.get("id")
        if isinstance(sid, str) and sid:
            skills_by_id.setdefault(sid, s)
        url = s.get("source_url")
        if isinstance(url, str) and "/skills/" in url:
            # Trailing component after /skills/ — strip /SKILL.md or trailing /
            tail = url.rstrip("/").rsplit("/skills/", 1)[-1].split("/")[0]
            if tail and tail != "skills":
                skills_by_source_skill_name.setdefault(tail, []).append(s)

    def _plugin_source_repo(plugin: dict) -> str:
        url = plugin.get("source_url") or ""
        if "github.com" not in url:
            return ""
        path = url.replace("https://github.com/", "").replace("http://github.com/", "")
        # Remove trailing /tree/<ref>/... and .git suffix
        path = path.split("/tree/")[0].split("/blob/")[0]
        if path.endswith(".git"):
            path = path[:-4]
        parts = path.split("/")
        return "/".join(parts[:2]) if len(parts) >= 2 else ""

    annotated = 0
    orphan_count = 0
    for plugin in plugin_entries:
        plugin_id = plugin.get("id") or ""
        bundle = plugin.get("bundle") or {}
        namespaces = bundle.get("skills_namespaces")
        if not namespaces:
            log.debug(
                "post-merge: plugin %s has no skills_namespaces; skipping",
                plugin_id or "<unknown>",
            )
            continue
        if not isinstance(namespaces, list):
            log.debug(
                "post-merge: plugin %s skills_namespaces is not a list (%s); skipping",
                plugin_id or "<unknown>",
                type(namespaces).__name__,
            )
            continue
        plugin_repo = _plugin_source_repo(plugin)
        # Position-aligned reverse mapping: one element per namespace entry
        # (None for orphans). Written back to plugin["bundle"]["bundled_skill_ids"]
        # after the namespace loop completes.
        bundled_skill_ids: list = []
        for ns in namespaces:
            if not isinstance(ns, str) or not ns:
                # Non-string / empty namespace entries can't be matched; keep
                # alignment with the input list by recording None.
                bundled_skill_ids.append(None)
                continue
            target = skills_by_namespace.get(ns) or skills_by_id.get(ns)
            if target is None and ":" in ns:
                slug_id = ns.replace(":", "-")
                target = skills_by_id.get(slug_id)
            if target is None and ":" in ns:
                # Source-url-path fallback: look for any catalog skill whose
                # source_url ends in /skills/<skill-name>. Prefer one whose
                # source_url contains the plugin's GitHub repo path
                # (highest-confidence: same-repo mirror); if no same-repo
                # match exists, fall back to any catalog skill with that
                # trailing skill-name segment.
                _, skill_name = ns.split(":", 1)
                candidates = skills_by_source_skill_name.get(skill_name) or []
                if candidates:
                    same_repo = [
                        c for c in candidates
                        if plugin_repo and plugin_repo in (c.get("source_url") or "")
                    ]
                    target = same_repo[0] if same_repo else candidates[0]
            if target is None:
                orphan_count += 1
                bundled_skill_ids.append(None)
                log.warning(
                    "post-merge: plugin %s declares orphan namespace %r "
                    "(no matching skill in catalog)",
                    plugin_id or "<unknown>",
                    ns,
                )
                continue
            target_id = target.get("id") or None
            bundled_skill_ids.append(target_id)
            if plugin_id:
                target["bundled_in"] = plugin_id
                annotated += 1
        # Write reverse mapping back onto the plugin entry. We only reach this
        # point when ``namespaces`` was a non-empty list (the earlier guards
        # ``continue`` for empty/missing/non-list cases), so per-spec we are
        # safe to set the field unconditionally here.
        plugin.setdefault("bundle", {})["bundled_skill_ids"] = bundled_skill_ids

    log.info(
        "post-merge: scanned %d plugins, annotated %d skills with bundled_in, "
        "found %d orphan namespaces",
        len(plugin_entries),
        annotated,
        orphan_count,
    )
    return entries


def overlay_curated_fields(entries: list) -> list:
    """Merge supplementary fields from curated.json files into deduped entries.

    For each entry in the deduped list, if a matching curated entry exists
    (matched by id, with fallback to normalized source_url):
      - tech_stack: union of curated + existing (curated values first, deduplicated)
      - tags: append curated tags (deduplicated)
      - Non-supplementary fields (name, description, stars, source_url, install,
        evaluation) are NOT overwritten.

    Curated entries with no match are appended as new entries.

    This function is idempotent: calling it multiple times produces the same result.
    """
    # Build lookup maps over the deduped entries
    id_to_entry: dict[str, Any] = {}
    url_to_entry: dict[str, Any] = {}
    for entry in entries:
        eid = entry.get("id", "")
        if eid:
            id_to_entry[eid] = entry
        surl = entry.get("source_url", "")
        if surl:
            url_to_entry[normalize_source_url(surl)] = entry

    appended: list = []

    for resource_type in TYPES:
        curated_path = os.path.join(CATALOG_DIR, resource_type, "curated.json")
        curated_entries = load_index(curated_path)
        for curated in curated_entries:
            cid = curated.get("id", "")
            curl = curated.get("source_url", "")
            norm_curl = normalize_source_url(curl) if curl else ""

            # Find match: id first, then normalized source_url
            target = None
            if cid and cid in id_to_entry:
                target = id_to_entry[cid]
            elif norm_curl and norm_curl in url_to_entry:
                target = url_to_entry[norm_curl]

            if target is None:
                # No match — append as new entry, track to prevent
                # duplicates from subsequent curated entries in the loop
                appended.append(curated)
                if cid:
                    id_to_entry[cid] = curated
                if norm_curl:
                    url_to_entry[norm_curl] = curated
                continue

            # Merge tech_stack: curated first, then existing, deduplicated
            curated_ts = curated.get("tech_stack") or []
            existing_ts = target.get("tech_stack") or []
            merged_ts_seen: set = set()
            merged_ts: list = []
            for item in curated_ts + existing_ts:
                if item not in merged_ts_seen:
                    merged_ts_seen.add(item)
                    merged_ts.append(item)
            target["tech_stack"] = merged_ts

            # Merge tags: append curated tags (deduplicated)
            curated_tags = curated.get("tags") or []
            existing_tags = target.get("tags") or []
            existing_tags_set = set(existing_tags)
            for tag in curated_tags:
                if tag not in existing_tags_set:
                    existing_tags.append(tag)
                    existing_tags_set.add(tag)
            target["tags"] = existing_tags

    return entries + appended


def _load_queue_state(queue_state_path: str) -> dict[str, Any]:
    try:
        with open(queue_state_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, IOError):
        return {}


def merge(skip_enrichment: bool = False):
    """Merge all source indexes into catalog/index.json.

    Args:
        skip_enrichment: When True, skip the LLM enrichment + evaluation step
            (``enrich_entries``) and produce a "data-only" catalog where every
            entry has ``evaluation == {}`` (empty dict, not missing key) so
            downstream aggregate jobs can distinguish a deferred-evaluation
            placeholder from a missing field. Governance still runs in
            health-only mode (no LLM-derived final_score), assigning safe
            defaults (final_score=0, decision="review").
    """
    all_entries = []

    for resource_type in TYPES:
        type_dir = os.path.join(CATALOG_DIR, resource_type)

        # Load auto-synced index (includes Tier 1 + Tier 2 for skills)
        index_path = os.path.join(type_dir, "index.json")
        entries = load_index(index_path)
        logger.info(f"Loaded {len(entries)} entries from {resource_type}/index.json")
        all_entries.extend(entries)

        # Load skills.sh sub-index (Tier 1 sibling source for skills only).
        # Skill identity-aware dedup in utils.deduplicate() collapses these
        # against the main index by source_priority, merging install_count /
        # skills_sh_url / skills_sh_scraped_at onto the winning entry.
        if resource_type == "skills":
            skills_sh_path = os.path.join(type_dir, "skills_sh_index.json")
            skills_sh_entries = load_index(skills_sh_path)
            if skills_sh_entries:
                logger.info(
                    f"Loaded {len(skills_sh_entries)} entries from "
                    f"{resource_type}/skills_sh_index.json"
                )
                all_entries.extend(skills_sh_entries)

        # Load mcp_registry sub-index (Tier 1 sibling source for mcp only).
        # mcp identity-aware dedup in utils.deduplicate() collapses registry
        # entries against GitHub URL sources by mcp_identity_key, merging
        # mcp_registry_status / mcp_registry_published_at / mcp_remotes onto
        # the winning entry. Sidecar absence is tolerated (logged at INFO).
        if resource_type == "mcp":
            mcp_registry_path = os.path.join(type_dir, "mcp_registry_index.json")
            if os.path.exists(mcp_registry_path):
                registry_entries = load_index(mcp_registry_path)
                if registry_entries:
                    logger.info(
                        f"Loaded {len(registry_entries)} entries from "
                        f"{resource_type}/mcp_registry_index.json"
                    )
                    all_entries.extend(registry_entries)
            else:
                logger.info(
                    f"No {resource_type}/mcp_registry_index.json sidecar; "
                    "skipping registry source"
                )

        # Load awesome-windsurfrules sub-index (Tier 1 sibling source for rules
        # only). Currently no rule_identity_key — entries are deduped by id /
        # source_url in Pass 2. Sidecar absence is tolerated.
        if resource_type == "rules":
            windsurfrules_path = os.path.join(type_dir, "windsurfrules_index.json")
            if os.path.exists(windsurfrules_path):
                wr_entries = load_index(windsurfrules_path)
                if wr_entries:
                    logger.info(
                        f"Loaded {len(wr_entries)} entries from "
                        f"{resource_type}/windsurfrules_index.json"
                    )
                    all_entries.extend(wr_entries)
            else:
                logger.info(
                    f"No {resource_type}/windsurfrules_index.json sidecar; "
                    "skipping windsurfrules source"
                )

        # Load curated entries (Tier 3 — lowest priority in dedup)
        curated_path = os.path.join(type_dir, "curated.json")
        curated = load_index(curated_path)
        if curated:
            logger.info(
                f"Loaded {len(curated)} entries from {resource_type}/curated.json"
            )
            all_entries.extend(curated)

    # Deduplicate by source_url + id (earlier entries take priority: Tier 1 > Tier 2 > Tier 3)
    pre_dedup_counts = {}
    for entry in all_entries:
        t = entry.get("type", "unknown")
        pre_dedup_counts[t] = pre_dedup_counts.get(t, 0) + 1

    deduped = deduplicate(all_entries)

    post_dedup_counts = {}
    for entry in deduped:
        t = entry.get("type", "unknown")
        post_dedup_counts[t] = post_dedup_counts.get(t, 0) + 1
    for t, pre in pre_dedup_counts.items():
        post = post_dedup_counts.get(t, 0)
        drop_pct = (1 - post / pre) * 100 if pre > 0 else 0
        if drop_pct > 50:
            logger.warning(
                f"Dedup integrity: type={t} dropped {drop_pct:.0f}% ({pre} → {post})"
            )
        else:
            logger.info(f"Dedup stats: type={t} {pre} → {post} (-{drop_pct:.0f}%)")

    # Overlay supplementary fields (tech_stack, tags) from curated.json files
    deduped = overlay_curated_fields(deduped)

    # Fix invalid categories
    VALID_CATEGORIES = {
        "frontend",
        "backend",
        "fullstack",
        "mobile",
        "devops",
        "database",
        "testing",
        "security",
        "ai-ml",
        "tooling",
        "documentation",
    }
    fixed_cats = 0
    for entry in deduped:
        if entry.get("category") not in VALID_CATEGORIES:
            tags = entry.get("tags") or []
            entry["category"] = categorize(
                entry.get("name", ""), entry.get("description", ""), tags
            )
            fixed_cats += 1
    if fixed_cats:
        logger.info(f"Fixed {fixed_cats} entries with invalid category")

    # --- Overlay prior evaluation from existing output ---
    # Per-type source indexes don't carry evaluation data. Store the full
    # prior evaluation under _prior_evaluation so populate_signals() can
    # use it as a fallback when cache/LLM are unavailable, preventing
    # unchanged entries from losing their scores. Only overlay timestamps
    # into evaluation{} to avoid blocking enrich_quality() re-evaluation.
    existing_output = load_index(os.path.join(CATALOG_DIR, "index.json"))
    _TIMESTAMP_KEYS = ("evaluated_at", "model_id")
    _SCORE_KEYS = ("coding_relevance", "doc_completeness", "specificity")
    existing_eval_map = {}
    for entry in existing_output:
        eid = entry.get("id")
        ev = entry.get("evaluation")
        if eid and ev and (ev.get("evaluated_at") or any(ev.get(k) for k in _SCORE_KEYS)):
            existing_eval_map[eid] = ev
    for entry in deduped:
        eid = entry.get("id")
        if eid and eid in existing_eval_map and not entry.get("evaluation"):
            prior_ev = existing_eval_map[eid]
            entry["_prior_evaluation"] = dict(prior_ev)
            entry["evaluation"] = {k: prior_ev[k] for k in _TIMESTAMP_KEYS if k in prior_ev}

    # --- Preserve security block across rebuilds ---
    # Spec security-risk-eval "catalog_lifecycle 保留 security 字段": old entries'
    # `security` blocks SHALL survive rebuilds where the security stage is
    # skipped (SECURITY_SCAN_ENABLED=false) or fails for that entry. Overlay
    # happens BEFORE enrichment so a fresh security_scan result naturally wins
    # (it writes into entry["security"] later).
    overlay_preserved_fields(deduped, existing_output)

    # --- Backfill pushed_at: overlay from prior output, API only for new entries ---
    existing_pushed_at = {}
    for entry in existing_output:
        eid = entry.get("id")
        pa = entry.get("pushed_at")
        if eid and pa:
            existing_pushed_at[eid] = pa
    overlayed = 0
    for entry in deduped:
        if not entry.get("pushed_at"):
            pa = existing_pushed_at.get(entry.get("id"))
            if pa:
                entry["pushed_at"] = pa
                overlayed += 1

    # mcp_registry 派生条目复用 mcp_registry_published_at 作为 pushed_at，
    # 避免对 6000+ registry 条目逐个打 GitHub API（首次接入时 6h CI 超时根因）。
    # registry publishedAt 是 registry 端打包时间，对 freshness 信号是合理近似。
    registry_overlayed = 0
    for entry in deduped:
        if not entry.get("pushed_at"):
            rpa = entry.get("mcp_registry_published_at")
            if rpa:
                entry["pushed_at"] = rpa
                registry_overlayed += 1
    if registry_overlayed:
        logger.info(
            f"Overlayed pushed_at for {registry_overlayed} entries "
            f"from mcp_registry_published_at"
        )

    still_missing = [e for e in deduped if not e.get("pushed_at") and e.get("source_url", "").startswith("https://github.com/")]
    if still_missing:
        logger.info(f"Backfilling pushed_at for {len(still_missing)} new entries via GitHub API (overlayed {overlayed} from prior output)")
        filled = 0
        for entry in still_missing:
            meta = get_repo_meta(entry["source_url"])
            if meta and meta.get("pushed_at"):
                entry["pushed_at"] = meta["pushed_at"]
                filled += 1
        logger.info(f"Backfilled pushed_at for {filled}/{len(still_missing)} entries")
    elif overlayed:
        logger.info(f"Overlayed pushed_at for {overlayed} entries from prior output, 0 new API calls")

    # --- Post-merge soft annotation: bundled_in on skills bundled by plugins ---
    # Runs AFTER deduplicate()/overlay_curated_fields() and BEFORE enrichment so
    # downstream stages (governance / lifecycle / featured / readme) can read the
    # bundled_in field. Per spec plugin-bundle-dedup §"Post-merge bundled_in
    # soft annotation" (`openspec/changes/add-plugins-category`).
    _apply_bundled_in_annotations(deduped)

    # --- Layer 2: Enrichment (tags, translation, LLM evaluation, signals) ---
    if skip_enrichment:
        logger.info(
            "--skip-enrichment: skipping LLM evaluation; "
            "entries will have evaluation={}"
        )
        # Reset evaluation to an empty dict on every entry so downstream
        # aggregate jobs can distinguish "data layer wrote skip-enrichment
        # placeholder" from "missing key entirely". Drop _prior_evaluation
        # too — that overlay is only meaningful when enrichment runs.
        for entry in deduped:
            entry["evaluation"] = {}
            entry.pop("_prior_evaluation", None)
    else:
        enrich_entries(deduped)
        logger.info(f"Enrichment complete for {len(deduped)} entries")

    # --- Layer 3: Scoring & Governance (final_score, decision, health, reject filter) ---
    # Only pass health_only when set, so legacy mocks of apply_governance that
    # accept a single positional arg continue to work.
    if skip_enrichment:
        deduped = apply_governance(deduped, health_only=True)
    else:
        deduped = apply_governance(deduped)
    logger.info(f"Governance complete: {len(deduped)} entries after filtering")

    # Promote scoring fields to top level for easy consumption by search/browse/recommend.
    # In skip_enrichment mode, evaluation stays empty ({}) so final_score=0,
    # decision="review" — aggregate_enrichment will fill these in later.
    for entry in deduped:
        ev = entry.get("evaluation") or {}
        if skip_enrichment:
            entry["evaluation"] = {}
            entry["final_score"] = 0
            entry["decision"] = "review"
        else:
            entry["final_score"] = ev.get("final_score", 0)
            entry["decision"] = ev.get("decision", "review")

    # --- Lifecycle ---
    existing_output = backfill_missing_added_at(existing_output, today=TODAY)
    prior_entries = deduped + existing_output
    deduped = overlay_added_at(deduped, prior_entries, today=TODAY)

    maintenance_dir = os.path.join(CATALOG_DIR, "maintenance")
    queue_path = os.path.join(maintenance_dir, "incremental_recrawl_candidates.json")
    queue_state_path = os.path.join(maintenance_dir, "incremental_recrawl_state.json")
    queue_state = _load_queue_state(queue_state_path)
    candidates, queue_state = build_incremental_recrawl_candidates(
        deduped,
        queue_state,
        now=datetime.combine(
            date.fromisoformat(TODAY), datetime.min.time(), tzinfo=timezone.utc
        ),
        threshold_days=365,
        cooldown_days=30,
        max_candidates=500,
    )
    save_index(candidates, queue_path)
    os.makedirs(os.path.dirname(queue_state_path), exist_ok=True)
    with open(queue_state_path, "w", encoding="utf-8") as f:
        json.dump(queue_state, f, indent=2, ensure_ascii=False)

    # Sort by final_score descending, then health.score, then stars (nulls last)
    deduped.sort(
        key=lambda x: (
            x.get("final_score", 0),
            x.get("health", {}).get("score", 0),
            x.get("stars") if x.get("stars") is not None else -1,
        ),
        reverse=True,
    )

    output_path = os.path.join(CATALOG_DIR, "index.json")
    save_index(deduped, output_path)

    # Generate lightweight search index (subset of fields for search/browse/recommend)
    SEARCH_INDEX_FIELDS = (
        "id", "name", "type", "category", "tags", "tech_stack",
        "stars", "description", "description_zh", "source_url",
        "final_score", "decision", "freshness_label", "bundled_in",
    )
    search_entries = []
    for entry in deduped:
        se = {k: entry.get(k) for k in SEARCH_INDEX_FIELDS}
        install_obj = entry.get("install")
        se["install_method"] = install_obj.get("method") if isinstance(install_obj, dict) else None
        # Build search_text: merged field for semantic keyword matching
        parts = [
            entry.get("name", ""),
            entry.get("description", ""),
            entry.get("description_zh", ""),
            " ".join(entry.get("tags") or []),
            " ".join(entry.get("tech_stack") or []),
            " ".join(entry.get("search_terms") or []),
        ]
        se["search_text"] = " ".join(p for p in parts if p)
        search_entries.append(se)

    search_index_path = os.path.join(CATALOG_DIR, "search-index.json")
    with open(search_index_path, "w", encoding="utf-8") as f:
        json.dump(search_entries, f, ensure_ascii=False, separators=(",", ":"))

    full_size = os.path.getsize(output_path)
    search_size = os.path.getsize(search_index_path)
    ratio = search_size / full_size * 100 if full_size else 0
    logger.info(
        f"Search index: {len(search_entries)} entries, "
        f"{search_size / 1024:.0f} KB ({ratio:.1f}% of full index)"
    )

    # Print summary by type and category
    by_type = {}
    by_category = {}
    for entry in deduped:
        t = entry.get("type", "unknown")
        c = entry.get("category", "unknown")
        by_type[t] = by_type.get(t, 0) + 1
        by_category[c] = by_category.get(c, 0) + 1

    logger.info(f"\nTotal: {len(deduped)} entries")
    logger.info(f"By type: {by_type}")
    logger.info(f"By category: {by_category}")


def main(argv: list[str] | None = None) -> None:
    """CLI entry point. Parses argv and dispatches to merge()."""
    parser = argparse.ArgumentParser(
        description=(
            "Merge type-specific indexes and curated files into "
            "catalog/index.json."
        )
    )
    parser.add_argument(
        "--skip-enrichment",
        action="store_true",
        default=False,
        help=(
            "Skip the LLM enrichment + evaluation step. Produces a "
            "'data-only' catalog where every entry has evaluation={} "
            "so a downstream aggregate job can fill it in."
        ),
    )
    args = parser.parse_args(argv)
    merge(skip_enrichment=args.skip_enrichment)


if __name__ == "__main__":
    main()
