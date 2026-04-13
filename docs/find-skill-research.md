# Find-Skill Research Notes

> Date: 2026-04-04  
> Scope: current strengths of Everything AI Coding style find-skill, key bottlenecks, external reference systems, and the next expansion wave for MCP / skills / rules / prompts.

## 1. Executive Summary

The current system is already stronger than a naive "search by keyword and sort by stars" finder.

Its real advantage is not raw search, but a governed discovery pipeline:

- lightweight recall via `catalog/search-index.json`
- shortlist verification via per-entry APIs
- source-aware enrichment and scoring
- install-aware result modeling
- project-context recommendation instead of plain text matching only

The main bottleneck is also clear: `find-skill` still retrieves skills through a mostly generic metadata lens. The system already computes better signals than it currently uses in first-pass retrieval.

The next evolution should focus on:

1. better stage-1 skill reranking
2. richer skill-specific lightweight metadata
3. source diversity controls
4. stronger Tier 2 deterministic filtering
5. a benchmark query set before any larger retrieval migration

## 2. Current Internal Strengths

### 2.1 Two-stage retrieval is the right foundation

Current flow:

1. recall from lightweight index
2. shortlist top candidates
3. fetch full entry details
4. apply candidate validation gate before calling something a recommendation

This is implemented across:

- `scripts/merge_index.py`
- `scripts/generate_pages.py`
- `platforms/*/commands/everything-ai-coding/*search*.md`
- `platforms/*/commands/everything-ai-coding/*recommend*.md`

Why this matters:

- keeps recall cheap
- avoids forcing full-index payloads into context
- preserves a precision layer for quality / trust / install checks
- is compatible with richer reranking later

### 2.2 The strongest asset is the catalog pipeline, not the UI prompt layer

The repo already has a real pipeline:

- sync
- deduplicate
- enrich
- score
- govern
- compute health
- generate lightweight search index

Key modules:

- `scripts/sync_skills.py`
- `scripts/skill_registry.py`
- `scripts/unified_enrichment.py`
- `scripts/scoring_governor.py`
- `scripts/health_scorer.py`
- `scripts/merge_index.py`

This makes the system closer to a curated registry than an awesome-list wrapper.

### 2.3 The scoring layer is already richer than the retrieval layer

The catalog already carries strong signals:

- `evaluation.coding_relevance`
- `evaluation.content_quality`
- `evaluation.specificity`
- `evaluation.source_trust`
- `evaluation.confidence`
- `evaluation.final_score`
- `evaluation.decision`
- `health.score`
- `health.freshness_label`
- `install.method`

Practical implication:

The system does **not** need a brand-new scoring concept first. It needs those existing signals to influence candidate generation and reranking earlier.

### 2.4 Recommend already uses project context well

The recommend surface already derives stack signals from:

- `package.json`
- `requirements.txt`
- `pyproject.toml`
- `go.mod`
- `Cargo.toml`
- `Gemfile`
- file suffixes
- `Dockerfile`
- `.github/workflows/`
- `tsconfig.json`

That is already stronger than plain global search, and the command design explicitly avoids over-recommending MCP when a skill / rule / prompt is the more direct fit.

### 2.5 The skill ingestion pipeline is already better than naive SKILL.md crawling

Current skill discovery combines:

- Tier 1 trusted upstreams
- Tier 2 registry-based expansion
- Tier 2 OpenClaw category mining
- Tier 3 curated supplement
- hard filters against spam / non-coding / suspected aggregators
- repo-level incremental caching by `pushed_at`

This is already a meaningful discovery advantage over simple filename search.

## 3. Evidence Snapshot from the Current Catalog

### 3.1 Corpus size

- total entries: `3907`
- MCP: `1629`
- skill: `1518`
- prompt: `524`
- rule: `236`

### 3.2 Skill-source concentration

Current skill corpus is highly concentrated:

- `antigravity-skills`: `1197` (`78.9%`)
- `davila7/claude-code-templates`: `276` (`18.2%`)
- all remaining skill sources combined: `45` (`3.0%`)

This is the clearest structural weakness in the current skill pool.

### 3.3 Skill trust / freshness / install signals

- source trust distribution
  - trust `3`: `1214`
  - trust `2`: `287`
  - trust `5`: `17`
- freshness labels
  - `abandoned`: `1231`
  - `active`: `287`
- install method
  - all `1518` skills currently use `git_clone`

Important implication:

"surface install richness earlier" is not a top skill-specific lever yet, because skill install metadata currently has little discriminative power.

### 3.4 Skill taxonomy and tag shape

Top skill categories:

- tooling: `546`
- ai-ml: `207`
- devops: `190`
- frontend: `125`
- backend: `120`

Average skill tag richness is lower than MCP:

- MCP avg tags: `4.52`
- skill avg tags: `3.44`

Most common skill tags are more domain-oriented than intent-oriented:

- automation
- ai
- python
- go
- agent
- git
- security
- react
- typescript
- llm

Meaning:

The system is stronger at **domain retrieval** than **workflow-intent retrieval**.

## 4. Main Bottlenecks for Find-Skill

### 4.1 Stage-1 ranking is too shallow

Current first-pass matching still depends too much on:

- `name`
- `description`
- `tags`
- `tech_stack`
- match count
- stars

That underuses already-computed signals like:

- `evaluation.final_score`
- `evaluation.decision`
- `health.score`
- `source_trust`
- `freshness_label`

### 4.2 Skills are retrieved through a generic metadata lens

For `find-skill`, the missing pieces are often:

- action verbs
- trigger phrases
- likely outcomes
- invocation context
- workflow type
- prerequisite/tool affinity

This is why the system can still feel like "search with filters" instead of a true skill finder.

### 4.3 Source monoculture creates ranking bias

Even good ranking can be distorted if one source family dominates the pool.

This creates risk of:

- source-family repetition
- template-style near-duplicates
- apparent breadth without real conceptual diversity

### 4.4 Tier 2 deterministic filtering is too simple for long-term quality

Current Tier 2 compression is useful, but too crude as the main gate:

- `log10(stars) * 10`
- `+50 if keyword match`

That is fine for a broad candidate gate, but weak as a quality prior for a serious find-skill system.

## 5. External Systems Worth Learning From

These references consistently outperformed naive keyword-only discovery patterns.

### 5.1 Backstage — best metadata/entity model

Why it matters:

- discoverable items are typed entities, not plain text blobs
- fields like `kind`, `type`, `owner`, `lifecycle`, `namespace`, and relations become searchable facets

Most relevant idea to borrow:

- model skills / prompts / rules / agents as typed entities with explicit lifecycle and ownership metadata

### 5.2 Artifact Hub — best federation + trust + install pattern

Why it matters:

- aggregates multiple ecosystems under one normalized surface
- trust signals are first-class: verified publisher, official status, ownership claim, security report
- discovery is tightly linked to install/use actions

Most relevant ideas to borrow:

- verified / official / ownership signals
- install methods as result-level affordances
- source adapters rather than one-off scrapers

### 5.3 Libraries.io — best scoring + recommendation + adapter pattern

Why it matters:

- SourceRank is an explicit composite quality model, not stars-only ranking
- recommendations use favorites, dependents, platform affinity, and behavior signals
- adding new ecosystems is treated as an adapter problem

Most relevant ideas to borrow:

- composite quality score with positive and negative factors
- co-install / affinity-based recommendations
- normalized source adapters

### 5.4 OpenSearch — best retrieval architecture upgrade path

Why it matters:

- strongest reference for hybrid lexical + semantic retrieval + normalization/reranking

Most relevant idea to borrow:

- do not replace keyword search; combine lexical precision with semantic intent and rerank them together

### 5.5 OpenVSX — best result-shape example for trust + actionability

Why it matters:

- exposes verified, ratings, review counts, downloads, deprecation status, and installability directly in result surfaces

Most relevant idea to borrow:

- discovery results should explain why something is trustworthy and usable without forcing a second lookup for basic confidence signals

### 5.6 Flowise — best example/import-first discovery pattern

Why it matters:

- templates are discoverable via use case, framework, badge, and category
- users can import directly after discovery

Most relevant ideas to borrow:

- example-first discovery
- use-case-driven browsing
- one-click import / install / copy next step

### 5.7 Hugging Face Hub — best curation/collection layer

Why it matters:

- full-text over rich artifacts is combined with collections, trending, and public discoverability signals

Most relevant ideas to borrow:

- curated collections
- rich-card indexing
- a second discovery path beyond literal query search

## 6. Recommended Evolution Path for Find-Skill

### Phase 1 — use current strengths better

This phase should happen before any major retrieval migration.

#### 6.1 Rebuild stage-1 skill reranking

Priority signals to incorporate early:

- title specificity
- trigger/action verbs
- source trust
- evaluation final score
- evaluation decision
- health score
- freshness label
- tag / tech-stack overlap
- source-family diversity penalty

#### 6.2 Extend the lightweight skill representation

Suggested additions for skill-specific search/indexing:

- trigger phrases
- action verbs
- likely outcome
- workflow type
- invocation context
- platform/runtime hints
- prerequisites
- examples available (boolean)

#### 6.3 Add source-family normalization

Suggested controls:

- source-family caps in top results
- near-duplicate collapse
- generic template penalty
- diversity bonus across sources/categories

#### 6.4 Improve Tier 2 deterministic filtering

Move beyond stars + keyword bonus.

Suggested features:

- specificity
- actionability
- tag richness
- description richness
- source quality prior
- freshness
- category diversity bonus
- generic-template penalty

#### 6.5 Build a judged benchmark set

Before making more retrieval changes, build a query set covering:

- broad task intent
- narrow task intent
- stack + task
- skill vs MCP ambiguity
- install-oriented intent
- workflow-oriented intent

### Phase 2 — expand upstreams to reduce structural bias

Only after Phase 1 work is underway should expansion become the next force multiplier.

Primary goal:

- break skill-source monoculture
- improve trust diversity
- improve intent diversity
- add new resource shapes not captured by current lists

### Phase 3 — only then consider hybrid retrieval

If Phase 1 and Phase 2 still plateau, move toward:

- lexical + semantic hybrid retrieval
- weighted normalization/rerank
- query-routing by intent
- collections and curated bundles

## 7. Recommended Next-Wave Upstreams

### 7.1 Direct-ingest priority group

These are the best balance of authority, structure, signal quality, and parser cost.

#### MCP

1. **`modelcontextprotocol/registry`**
   - official structured registry
   - best long-term canonical MCP source

2. **`docker/mcp-registry`**
   - adds deployability, packaging, and trust posture

3. **`sylviangth/awesome-remote-mcp-servers`**
   - unique hosted/remote MCP coverage

#### Skills

4. **`microsoft/skills`**
   - official, structured, multi-platform, coding-relevant

5. **`trailofbits/skills`**
   - strong specialist coverage in security/audit workflows

6. **`mattpocock/skills`**
   - small but high-quality, low-noise curated source

#### Rules

7. **`nedcodes-ok/cursorrules-collection`**
   - modern and structure-friendly rule corpus
   - includes format variants and validation mindset

8. **`lifedever/claude-rules`**
   - clean `base/`, `languages/`, `frameworks/` taxonomy

9. **`continuedev/awesome-rules`**
   - promising because of machine-readable `rules.json`

#### Prompts

10. **`repowise-dev/claude-code-prompts`**
    - deep coding-agent prompt architecture source

11. **`instructa/ai-prompts`**
    - strong structure and `data/index.json`

12. **`pnp/copilot-prompts`**
    - practical enterprise-oriented coding prompt samples

### 7.2 Selective-curation / mining sources

These are important, but should be mined selectively rather than blindly ingested.

- `obra/superpowers`
- `vercel-labs/skills`
- `alirezarezvani/claude-skills`
- `VoltAgent/awesome-agent-skills`
- `ComposioHQ/awesome-claude-skills`
- `awslabs/mcp`
- `agentic-community/mcp-gateway-registry`
- `affaan-m/everything-claude-code`

Why they are not first-wave direct ingests:

- overlap risk is high
- content type is mixed
- curation burden is higher
- raw ingest would likely amplify duplication/noise

### 7.3 Watchlist / caution group

- `thehimel/cursor-rules-and-prompts`
- `ai-driven-dev/rules`
- `dontriskit/awesome-ai-system-prompts`

Reason:

- licensing or policy ambiguity
- mixed content types
- higher risk of ingesting material that needs manual review

## 8. If Only a Few Things Are Done Next

### 8.1 If only five upstreams are added

Add these first:

1. `modelcontextprotocol/registry`
2. `microsoft/skills`
3. `docker/mcp-registry`
4. `nedcodes-ok/cursorrules-collection`
5. `repowise-dev/claude-code-prompts`

### 8.2 If only one product iteration is funded

Do this sequence:

1. rebuild stage-1 skill reranking
2. extend the lightweight skill index with intent-aware fields
3. add source-family diversity controls
4. upgrade Tier 2 deterministic filtering
5. build a judged query benchmark set

## 9. Open Questions for the Next Design Pass

- How should skill intent fields be generated: deterministic extraction first, LLM enrichment second, or both?
- Should source-family diversity be a hard cap or a soft ranking penalty?
- Should collections be generated algorithmically, curated manually, or both?
- When hybrid retrieval is introduced, should it be skill-only first or global across all resource types?
- Which new upstreams should receive the highest `source_trust` priors?

## 10. Suggested Immediate Follow-up Artifacts

This research note is enough to support the next phase. The most useful follow-ups would be:

1. `find-skill v2` field/schema draft
2. rerank formula proposal
3. benchmark query set
4. parser plan for first-wave upstream additions
5. source trust proposal for new upstreams
