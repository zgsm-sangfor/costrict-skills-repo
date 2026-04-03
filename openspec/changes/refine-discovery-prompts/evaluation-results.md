## Prompt Evaluation Results

### Evaluation method

- Baseline behavior assessed by Oracle against the original search/recommend prompt style (keyword or tag matching + stars sorting + simple table output, no verification gate)
- Revised behavior assessed twice:
  1. First against the abstract OpenSpec design, which highlighted over-complexity and wording risks
  2. Then against the **actual rewritten prompt wording** after simplification in this branch

### Baseline result

- **Overall: Fail**
- Summary: baseline can retrieve plausible matches, but is weak at rationale quality, noise control, and install-oriented decision support
- Scenario notes:
  - S1 PR review: fail
  - S2 React+TypeScript+Tailwind generic recommend: marginal pass
  - S3 deploy/release/publish broad query: fail
  - S4 Python+FastAPI+Docker with `type:mcp`: fail

### Revised design critique (before simplification)

- Direction judged correct, but prompt was too heavy and too easy for agents to execute sloppily
- Main issues called out:
  - trying to make the prompt act like a policy engine
  - verification gate too underspecified
  - recommendation wording too easy to overclaim

### Simplifications applied after critique

- Reduced the gate to short deterministic rules:
  - search: **1 trust signal + 1 execution signal**
  - recommend: **clear project fit + 1 trust signal + 1 execution signal**
- Softened wording from “推荐 / 高置信推荐” to “优先候选 / 值得先看 / 候选依据” when a strong recommendation claim would overpromise
- Preserved layered output: `优先候选` + `其他匹配结果`

### Actual revised prompt result

- **Overall: Pass**
- Oracle judged the actual tightened prompt wording to be a meaningful improvement over baseline, especially in:
  - noise control
  - avoiding overconfident recommendations
  - preserving install follow-through
- Scenario notes:
  - S1 PR review: pass
  - S2 React+TypeScript+Tailwind generic recommend: pass / medium-strength fit
  - S3 deploy/release/publish broad query: pass, with broad-intent recall as the main remaining weakness
  - S4 Python+FastAPI+Docker with `type:mcp`: pass, strongest scenario

### Final refinement applied after passing evaluation

- Expanded the lightweight synonym pack in search prompts for the two most fragile broad-intent cases:
  - `deploy → deployment / ci-cd / release / publish`
  - `pr review → code review / pull request review / review automation`
- Added an injected-output comparison pass using subagents that simulated baseline vs revised user-facing answers for search and recommend
- Tightened recommend output contracts based on the injected judge result:
  - default `优先候选` list reduced to 2-3 items
  - `其他匹配结果` reduced to 2-4 items
  - raw internal scoring language removed from the main answer contract
  - repeated per-item install commands replaced by a final default install suggestion block

### Tightened recommend rerun

- After the recommend contract was shortened, a fresh injected subagent run produced a noticeably more decisive answer shape:
  - `优先候选` contained 3 items only
  - `其他匹配结果` was reduced to a compact supplement set
  - the final answer ended with a default install combination instead of repeating install commands under every item
- The rerun still showed that candidate selection depends strongly on current catalog coverage, but the **presentation quality** matched the intended “trustworthy discovery assistant” bar much better than the previous long-form recommend output
- This confirms the branch should keep the **shortened recommend contract**, not the earlier verbose variant

### Extra scenario pass after narrow heuristic fixes

After the shortened recommend contract was in place, three more injected scenarios were used to test whether the heuristics had stabilized beyond the original happy path:

1. **Broad deploy / release intent search**
   - Added a wide-intent suppression rule so the first screen prioritizes direct deployment / CI-CD / platform execution results over changelog or release-note adjacent resources
   - Result: first-screen candidate usefulness improved and adjacent-intent noise dropped meaningfully

2. **Sparse `type:mcp` recommendation for Python + FastAPI + Docker**
   - Added a sparse-match rule: prefer `2 strong matches + explicit coverage gap` instead of padding with conditional or weakly relevant items
   - Result: the output became materially more trustworthy because it stopped inventing a fuller list than the catalog could support

3. **Generic frontend recommendation after non-MCP type-bias correction**
   - Added a rule that generic recommend should prefer project-facing skills/rules/prompts unless the user explicitly requests `type:mcp`
   - Result: the prompt stopped over-promoting general-purpose MCPs and returned a much more realistic frontend-oriented shortlist

### Final stability verdict

- Extra-scenario judge verdict: **stable enough to stop prompt iteration**
- Remaining issues were judged to be **ranking/data polish**, not prompt-family instability
- Specific residual notes:
  - broad deploy queries still have some platform-ordering polish to improve
  - sparse MCP recommendations still depend on catalog coverage quality
  - these are not strong enough reasons to keep iterating the prompt family itself

### Keep / drop decision on the five ideas

1. **先头部候选，再通用搜索** → Keep, implemented as shortlist-first plus top-candidate verification rather than a separate leaderboard
2. **禁止搜到即推荐** → Keep, implemented as the compact candidate gate
3. **推荐输出必须带理由** → Keep, implemented via “为什么值得先看 / 候选依据 / 下一步”
4. **把 trust 信号翻译成用户可理解依据** → Keep, but with softened wording to avoid overclaiming
5. **轻量 query reformulation** → Keep, with bounded synonym packs and no impact on install determinism

### Conclusion

This iteration is good enough to keep. The strongest final pattern is:

- search should look like the injected **revised search** output: intent narrowing, direct-vs-adjacent separation, one clear default pick
- recommend should keep the revised shortlist/gate structure, but remain shorter and more decision-oriented than the first long-form draft

The prompt family should now be considered **feature-complete for this change**. Future work, if any, should focus on ranking/data quality rather than further prompt churn.

Further refinement should focus on broad-intent recall and synonym coverage, not on adding more verification complexity.
