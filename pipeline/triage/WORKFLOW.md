# Station 1: Triage

> **SUMMARY:** Single entry point. Classify by Cynefin (Clear/Complicated/Complex/Chaotic),
> assign appetite (2h/1d/3d/6d), verify completeness, route. Clear→impl, Complicated→spec,
> Complex→negativa (after shaping+decomposition), Chaotic→impl express.
> Kill: 48h no info → ask. 7d no reply → close stale.

---

## Purpose

Classify and route every incoming task. Does NOT judge whether a task *should* be done —
that is Via Negativa's job.

## Input criteria

- Issue has label `task`
- No `stage:*` label yet

## Process

### A — Spam/duplicate filter

Search closed issues and existing code for the same problem.
Check issue is in-scope for W∃A (code, docs, economy, agent tooling).
Out-of-scope or duplicate → close with reason, done.

### B — Cynefin classification

Apply exactly one `complexity:*` label:

- `complexity:clear` — known solution, repro steps present, trivial fix
- `complexity:complicated` — clear goal, expert analysis needed, solution non-obvious
- `complexity:complex` — fuzzy outcome, problem not fully understood, needs shaping
- `complexity:chaotic` — production incident, time-critical, act first

When unsure between two: pick the more conservative (higher complexity) option.

### C — Appetite

Apply exactly one `appetite:*` label:

- `appetite:2h` — ≤2 hours focused work
- `appetite:1d` — full day, one session
- `appetite:3d` — multi-session, 2–5 files
- `appetite:6d` — large, multiple modules

Appetite >6d → mandatory decomposition in Step E.

### D — Completeness check

- Clear: repro steps, expected vs actual, environment
- Complicated: goal, context, success criteria
- Complex: problem statement minimum (will be shaped in Step E)
- Chaotic: anything available; proceed immediately

Incomplete → post clarification request. See Kill criteria.

### E — Shaping + Decomposition (Complex only)

Run inline as comments on the same issue.

**Shaping (A3 format) — post as comment:**

1. Problem — one sentence, no solution assumed
2. Current state — what is happening, with data
3. Root cause — 5 Whys
4. Target state — measurable success criteria
5. Fat-marker sketch — rough solution shape, open questions noted
6. Rabbit holes & no-gos — ≥3 explicit "we will NOT do X" items
7. Pre-mortem — ≥5 failure scenarios with mitigations
8. Appetite confirmation — final after shaping

Kill if root-cause unresolvable in 3 days → label `needs-research`, return to backlog.

**Decomposition (appetite >2h) — post as follow-up comment:**

1. MECE breakdown into sub-tasks
2. Dependency order (no cycles)
3. Each sub-task: INVEST check (Independent, Negotiable, Valuable, Estimable, Small, Testable)
4. Each sub-task: appetite ≤1d, estimated LOC ≤400
5. Create child issues linked to parent with `parent: #N`

Each child issue enters pipeline independently at `stage:negativa`.

### F — Route and post routing comment

```
Triage complete.
Complexity: [label]
Appetite: [label]
Route: [next stage] — [one-line reason]
```

Routing logic:
- `complexity:clear` → `stage:impl`
- `complexity:complicated` → `stage:spec`
- `complexity:complex` → `stage:negativa`
- `complexity:chaotic` → `stage:impl` (note: express mode)

## Gate checklist

- [ ] Exactly one `complexity:*` label applied
- [ ] Exactly one `appetite:*` label applied
- [ ] For complex: shaping comment posted (all 7 A3 sections filled)
- [ ] For complex with appetite >2h: decomposition posted, child issues created
- [ ] Routing comment posted

## Kill criteria

- Spam / out-of-scope → close immediately
- Duplicate → close with link to existing
- Incomplete info, no reply in 48h → post clarification request
- No reply to clarification in 7 days → close with `rejected:stale`
- Complex: root-cause unresolvable in 3 days → `needs-research`, backlog

## Dual evaluation protocol

Not applicable. Single triager (Agent0 or designated).

## Output artifact

Labels `complexity:*` and `appetite:*` applied. Routing comment posted. Issue advanced to next `stage:*`.
