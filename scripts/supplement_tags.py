#!/usr/bin/env python3
"""Supplement empty tags for antigravity skills via DeepSeek API.

Usage:
    python scripts/supplement_tags.py [--dry-run]

Reads parse_antigravity_skills() output, finds entries with empty tags,
batches them to DeepSeek for tag extraction, and patches sync_skills.py
to embed a TAG_SUPPLEMENT map so future syncs auto-apply the tags.
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
if not DEEPSEEK_API_KEY:
    print("ERROR: DEEPSEEK_API_KEY environment variable is required", file=sys.stderr)
    sys.exit(1)
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"
MODEL = "deepseek-chat"

# Tags vocabulary — must match extract_tags() in utils.py
VALID_TAGS = [
    "react", "nextjs", "vue", "angular", "svelte",
    "typescript", "javascript", "python", "go", "rust",
    "java", "ruby", "php", "swift", "kotlin", "flutter",
    "docker", "kubernetes", "postgres", "mysql", "mongodb",
    "redis", "graphql", "rest-api", "fastapi", "django",
    "flask", "express", "nodejs", "tailwind", "css",
    "aws", "gcp", "azure", "terraform", "jest", "playwright",
    "cypress", "prisma", "supabase", "openai", "langchain",
    "git", "eslint",
    # Extended tags for better coverage
    "claude", "anthropic", "llm", "ai", "ml",
    "devops", "ci-cd", "github-actions",
    "linux", "macos", "windows",
    "sql", "nosql", "elasticsearch",
    "nginx", "caddy",
    "webpack", "vite", "esbuild",
    "firebase", "vercel", "netlify", "cloudflare",
    "stripe", "twilio", "sendgrid",
    "figma", "storybook",
    "pytest", "vitest", "mocha",
    "grpc", "websocket", "mqtt",
    "solidity", "web3", "ethereum",
    "unity", "godot", "unreal",
    "latex", "markdown",
    "selenium", "puppeteer",
    "rabbitmq", "kafka",
    "s3", "lambda", "ec2",
    "sentry", "datadog", "grafana", "prometheus",
    "oauth", "jwt", "saml",
    "pnpm", "npm", "yarn",
    "deno", "bun",
    "htmx", "alpine-js",
    "shadcn", "radix",
    "trpc", "zod",
    "pandas", "numpy", "scipy",
    "pytorch", "tensorflow", "huggingface",
    "celery", "airflow",
    "helm", "istio", "envoy",
]

BATCH_SIZE = 40  # skills per API call


def call_deepseek(skills_batch: list[dict]) -> dict:
    """Call DeepSeek to extract tags for a batch of skills.

    Returns {skill_id: [tag1, tag2, ...], ...}
    """
    skills_text = "\n".join(
        f"- id: {s['id']} | name: {s['name']} | desc: {s['description'][:150]}"
        for s in skills_batch
    )

    prompt = f"""You are a tech stack tag extractor. For each skill below, output 1-5 relevant tags from this allowed list ONLY:

{', '.join(sorted(set(VALID_TAGS)))}

Rules:
- Output ONLY tags from the allowed list above
- If no tag fits, output empty array []
- Be precise: only tag technologies actually mentioned or strongly implied
- Output valid JSON: {{"skill_id": ["tag1", "tag2"], ...}}

Skills:
{skills_text}

Output JSON only, no explanation:"""

    body = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": 4096,
    }).encode()

    req = urllib.request.Request(
        DEEPSEEK_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
        content = data["choices"][0]["message"]["content"].strip()
        # Strip markdown fences if present
        if content.startswith("```"):
            content = content.split("\n", 1)[1]
            if content.endswith("```"):
                content = content.rsplit("```", 1)[0]
        return json.loads(content)
    except (urllib.error.URLError, json.JSONDecodeError, KeyError) as e:
        print(f"  API error: {e}", file=sys.stderr)
        return {}


def main():
    dry_run = "--dry-run" in sys.argv

    # Get antigravity entries
    sys.path.insert(0, os.path.dirname(__file__))
    from sync_skills import parse_antigravity_skills
    entries = parse_antigravity_skills()

    # Filter to empty-tags entries
    empty = [e for e in entries if not e["tags"]]
    print(f"Total entries: {len(entries)}, empty tags: {len(empty)}")

    if dry_run:
        print(f"[dry-run] Would process {len(empty)} entries in {(len(empty) + BATCH_SIZE - 1) // BATCH_SIZE} batches")
        return

    # Process in batches
    tag_map = {}  # id -> [tags]
    total_batches = (len(empty) + BATCH_SIZE - 1) // BATCH_SIZE

    for i in range(0, len(empty), BATCH_SIZE):
        batch = empty[i:i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1
        print(f"Batch {batch_num}/{total_batches} ({len(batch)} skills)...", end=" ", flush=True)

        result = call_deepseek(batch)

        # Validate and collect
        valid_set = set(VALID_TAGS)
        batch_tagged = 0
        for skill_id, tags in result.items():
            if isinstance(tags, list):
                clean = [t for t in tags if t in valid_set]
                if clean:
                    tag_map[skill_id] = clean
                    batch_tagged += 1

        print(f"tagged {batch_tagged}/{len(batch)}")

        # Rate limit: DeepSeek free tier
        if batch_num < total_batches:
            time.sleep(1)

    # Save result
    output_path = os.path.join(os.path.dirname(__file__), "..", "catalog", "skills", "antigravity_tags.json")
    with open(output_path, "w") as f:
        json.dump(tag_map, f, indent=2, ensure_ascii=False)

    tagged = sum(1 for v in tag_map.values() if v)
    print(f"\nDone! Tagged {tagged}/{len(empty)} previously empty entries")
    print(f"Saved to {output_path}")


if __name__ == "__main__":
    main()
