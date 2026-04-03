## Discovery Prompt Evaluation Scenarios

Use the same scenarios against both baseline prompts and revised prompts.

### Scenario 1: Broad natural-language search

- Command shape: search
- User input: `我想找一个能帮我做 PR review 的资源`
- Expected stress: broad language, needs query reformulation (`pr review` / `code review`), should not treat every git-related match as recommendation

### Scenario 2: Stack-based recommendation

- Command shape: recommend
- Project context: React + TypeScript + Tailwind project
- User input: no extra qualifier, generic recommend
- Expected stress: should prioritize high-confidence frontend/design/dev workflow resources and explain both fit and trust

### Scenario 3: Noisy / ambiguous query

- Command shape: search
- User input: `帮我找点部署、上线、发版之类的东西`
- Expected stress: reformulation, broad recall, but should avoid pretending there is a single strong recommendation if signals are weak

### Scenario 4: Narrow type-constrained recommendation

- Command shape: recommend
- Project context: Python + FastAPI + Docker
- User input: `type:mcp`
- Expected stress: type filter must survive reformulation; recommendation should still include rationale and install follow-through

## Review Criteria

- Candidate quality: top candidates are meaningfully closer to the user need or project stack
- Rationale quality: output explains why something is recommended in human-readable terms
- Noise control: weak matches are separated from strong recommendations
- Install follow-through: recommended candidates still include the next action command

## Pass / Fail Heuristic

- **Pass**: revised prompt improves at least two of candidate quality, rationale quality, or noise control without making install follow-through worse
- **Fail**: revised prompt mainly adds verbosity, still recommends weak matches, or loses the command-driven next step
