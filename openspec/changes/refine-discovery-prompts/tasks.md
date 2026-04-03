## 1. Discovery prompt strategy update

- [x] 1.1 Inventory the current search / recommend / browse command prompts across supported platforms and identify the shared sections that control candidate selection, ranking, and output formatting
- [x] 1.2 Define a high-confidence candidate prioritization rule that maps current catalog signals (`curated`, Tier/source trust, score/decision, install completeness) into prompt-friendly selection logic
- [x] 1.3 Define a lightweight query reformulation rule for search / recommend that improves discovery recall without affecting install determinism

## 2. Recommendation verification and explanation

- [x] 2.1 Update search prompt behavior so matching results are not automatically framed as recommendations unless they pass the verification gate
- [x] 2.2 Update recommend prompt behavior to require both project-fit reasoning and trust reasoning before presenting a result as recommended
- [x] 2.3 Revise output contracts for discovery commands so recommended candidates include human-readable rationale plus the next action/install command

## 3. Cross-platform prompt application

- [x] 3.1 Apply the revised discovery and recommendation behavior to opencode command files
- [x] 3.2 Apply the revised discovery and recommendation behavior to costrict and vscode-costrict command/skill files
- [x] 3.3 Apply the revised discovery and recommendation behavior to claude-code equivalents or document why a platform-specific variant is intentionally unchanged

## 4. Prompt evaluation workflow

- [x] 4.1 Create a fixed set of discovery evaluation scenarios covering broad natural-language search, stack-based recommendation, and noisy/ambiguous queries
- [x] 4.2 Run baseline prompts and revised prompts through subagent-assisted evaluation on the same scenarios
- [x] 4.3 Record pass/fail results for candidate quality, rationale quality, noise control, and install follow-through, then summarize which of the five ideas proved worth keeping

## 5. Documentation and readiness

- [x] 5.1 Update README or adjacent docs to reflect the refined recommendation behavior and how users should interpret recommended results
- [x] 5.2 Verify that the change artifacts and evaluation notes are sufficient to begin implementation with `/opsx-apply`
