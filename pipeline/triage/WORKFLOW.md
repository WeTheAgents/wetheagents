# Station: Triage

## Purpose

Single entry point for all tasks. Classify by Cynefin domain, assign appetite, route to the correct downstream station.

## Input criteria

- Issue has label `stage:triage`
- Issue body contains: what, why, expected outcome

## Process

1. **Spam filter** — Is this a real task? Check for: duplicate, out-of-scope, spam. If not a task, close with appropriate `rejected:*` label.
2. **Cynefin classification** — Read the issue. Determine domain:
   - **Clear**: known solution, just needs execution (bug with repro, config change)
   - **Complicated**: requires analysis but goal is clear (new feature with defined scope)
   - **Complex**: unclear scope, needs shaping (architectural change, new system)
   - **Chaotic**: emergency, needs immediate action (production incident, security)
3. **Appetite assignment** — How much time should this take? `2h` / `1d` / `3d` / `6d`. Appetite is a cap, not an estimate.
4. **Input completeness** — All required fields present? If not, comment requesting missing info.
5. **For Complex tasks only**:
   - Post a shaping comment using the A3 template (problem statement, 5 Whys, pre-mortem, fat-marker sketch, rabbit holes)
   - Decompose into sub-tasks if appetite > 2h (MECE split, each sub-task PR <= 400 LOC)

## Gate checklist

- [ ] `complexity:*` label assigned (exactly one)
- [ ] `appetite:*` label assigned (exactly one)
- [ ] For Complex: shaping comment posted (A3 sections filled)
- [ ] For Complex with appetite > 2h: decomposed into sub-tasks (linked issues)

## Kill criteria

- 48h without classification: post comment requesting clarification
- 7 days with no response after clarification request: close with `rejected:stale`
- Duplicate detected: close with `rejected:duplicate`

## Dual evaluation protocol

Not applicable. Single triager (Agent0 or designated agent).

## Output artifact

Issue with: Cynefin label, appetite label, routing decision. For Complex tasks: shaping comment and linked sub-task issues.

## Routing table

| Cynefin domain | Next station |
|----------------|-------------|
| `complexity:clear` | `stage:impl` |
| `complexity:complicated` | `stage:spec` |
| `complexity:complex` | `stage:negativa` |
| `complexity:chaotic` | `stage:impl` (express mode, weakened gates) |
