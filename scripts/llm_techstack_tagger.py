#!/usr/bin/env python3
"""LLM batch tech_stack tagger for catalog entries.

Sends entries to an LLM in batches, returns tech_stack labels from a controlled vocabulary.
Reuses LLM_BASE_URL / LLM_API_KEY / LLM_MODEL environment variables.
Cache stored at catalog/.llm_techstack_cache.json (separate from other LLM caches).
"""

import os
import json
import hashlib
import time
import logging
from datetime import datetime
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError

logger = logging.getLogger(__name__)

CATALOG_DIR = os.path.join(os.path.dirname(__file__), "..", "catalog")
CACHE_PATH = os.path.join(CATALOG_DIR, ".llm_techstack_cache.json")
BATCH_SIZE = 40

TECH_STACK_VOCAB = [
    # Frontend
    "react", "vue", "angular", "svelte", "nextjs", "nuxt", "tailwind",
    # Backend frameworks
    "nodejs", "express", "fastapi", "django", "flask", "spring", "rails",
    # Languages
    "typescript", "python", "go", "rust", "java", "ruby", "php", "swift", "kotlin", "c-sharp",
    # Database
    "postgres", "mysql", "sqlite", "redis", "mongodb", "supabase", "prisma", "drizzle",
    # DevOps/Infra
    "docker", "kubernetes", "terraform", "github-actions", "aws", "gcp", "azure",
    # AI/ML
    "langchain", "openai", "anthropic", "huggingface", "pytorch", "tensorflow",
    # Mobile
    "react-native", "flutter", "expo",
    # Other
    "graphql", "grpc", "elasticsearch", "kafka",
]

_VOCAB_SET = set(TECH_STACK_VOCAB)


def _load_cache() -> dict:
    if not os.path.exists(CACHE_PATH):
        return {}
    try:
        with open(CACHE_PATH, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def _save_cache(cache: dict):
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    with open(CACHE_PATH, "w") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)


def _content_hash(entry: dict) -> str:
    raw = (entry.get("name", "") + "|" + entry.get("description", "")).encode()
    return hashlib.md5(raw).hexdigest()[:12]


def _is_cache_hit(cached: dict, entry: dict) -> bool:
    """Content unchanged → hit. Legacy entries without hash → also hit."""
    stored = cached.get("content_hash", "")
    if not stored:
        return True
    return stored == _content_hash(entry)


def _build_prompt(entries: list[dict]) -> str:
    """Build the LLM prompt for tech_stack tagging."""
    items = []
    for e in entries:
        name = e.get("name", "")[:100]
        desc = e.get("description", "")[:300]
        url = e.get("source_url", "")[:200]
        tags = ", ".join((e.get("tags") or [])[:15])
        items.append(f"- id: {e['id']}\n  name: {name}\n  description: {desc}\n  url: {url}\n  tags: {tags}")

    vocab_str = ", ".join(TECH_STACK_VOCAB)

    return f"""For each entry below, select 1-5 relevant tech_stack labels.

CONTROLLED VOCABULARY (you MUST only pick from this list):
{vocab_str}

RULES:
- Output ONLY labels from the vocabulary above — no exceptions
- Select 1-5 labels per entry; skip entry if none apply
- Do NOT invent labels or use variations (use "react" not "React.js" or "ReactJS")

ENTRIES:
{chr(10).join(items)}

Respond ONLY with a JSON array.
Example: [{{"id": "entry-id", "tech_stack": ["python", "fastapi"]}}]"""


def _call_llm_batch(entries: list[dict]) -> dict[str, list[str]]:
    """Call LLM API with a batch. Returns {{id: [tech_stack]}} or {{}}."""
    base_url = os.environ.get("LLM_BASE_URL", "")
    api_key = os.environ.get("LLM_API_KEY", "")
    model = os.environ.get("LLM_MODEL", "deepseek-chat")

    if not base_url or not api_key:
        return {}

    prompt = _build_prompt(entries)
    url = f"{base_url.rstrip('/')}/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a tech stack tagger. Respond only with valid JSON."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
        "max_tokens": 8192,
    }

    data = json.dumps(payload).encode()
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    req = Request(url, data=data, headers=headers, method="POST")

    for attempt in range(3):
        try:
            with urlopen(req, timeout=300) as resp:
                result = json.loads(resp.read().decode())
                content = result["choices"][0]["message"]["content"].strip()
                if content.startswith("```"):
                    content = content.split("\n", 1)[1].rsplit("```", 1)[0]
                parsed = json.loads(content)
                # Convert array format to {id: tech_stack} dict
                if isinstance(parsed, list):
                    return {item["id"]: item["tech_stack"] for item in parsed if "id" in item and "tech_stack" in item}
                return parsed
        except (HTTPError, URLError, TimeoutError) as e:
            logger.warning(f"LLM techstack tagger API error (attempt {attempt+1}): {e}")
            if attempt < 2:
                time.sleep(2 ** attempt)
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            logger.warning(f"LLM techstack tagger response parse error: {e}")
            return {}

    return {}


def _postprocess_labels(labels: list) -> list[str]:
    """Lowercase, filter to vocab, dedup while preserving order."""
    seen = set()
    result = []
    for label in labels:
        if not isinstance(label, str):
            continue
        label = label.lower().strip()
        if label and label in _VOCAB_SET and label not in seen:
            seen.add(label)
            result.append(label)
    return result


def tag_techstack(entries: list[dict]) -> dict[str, list[str]]:
    """Tag entries with tech_stack labels using LLM.

    Args:
        entries: List of index entries.

    Returns:
        Dict mapping entry id to list of tech_stack labels (from TECH_STACK_VOCAB, deduped).
    """
    base_url = os.environ.get("LLM_BASE_URL", "")
    api_key = os.environ.get("LLM_API_KEY", "")
    if not base_url or not api_key:
        logger.info("LLM credentials not set, skipping tech_stack enrichment")
        return {}

    if not entries:
        return {}

    # Check cache
    cache = _load_cache()
    result = {}
    uncached = []

    for e in entries:
        eid = e["id"]
        if eid in cache and _is_cache_hit(cache[eid], e):
            result[eid] = cache[eid]["tech_stack"]
        else:
            uncached.append(e)

    if not uncached:
        return result

    # Batch LLM calls
    batches = [uncached[i:i+BATCH_SIZE] for i in range(0, len(uncached), BATCH_SIZE)]
    now_iso = datetime.now().isoformat()

    for batch in batches:
        raw = _call_llm_batch(batch)
        for e in batch:
            eid = e["id"]
            if eid in raw and isinstance(raw[eid], list):
                labels = _postprocess_labels(raw[eid])
                result[eid] = labels
                cache[eid] = {"tech_stack": labels, "content_hash": _content_hash(e), "cached_at": now_iso}

        _save_cache(cache)

    logger.info(f"LLM techstack tagger: {len(batches)} API calls, {len(result)} entries tagged")
    return result
