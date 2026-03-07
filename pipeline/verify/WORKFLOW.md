# Station: Verification

## Purpose

Multi-level check that implementation matches spec and doesn't introduce regressions. The final gate before delivery. Eliminates bugs, regressions, and specification gaming.

## Input criteria

- Issue has label `stage:verify`
- PR exists and is linked to the issue
- Implementer posted `!done`

## Process

### Level 1 — Automated (CI)
- All tests pass
- Lint clean (`ruff check`)
- No coverage regression
- Property-based tests from spec (if defined)

### Level 2 — Code Review (agent reviewers)
- Adversarial Red Team mode: actively look for ways the implementation fails
- Review checklist: gaming possible? Out-of-scope changes? Creates fragility? Can remove code without losing functionality?
- Speed limit: <= 400 LOC/hour, <= 60 min review session

### Level 3 — Human gate (Complex tasks only)
- Architectural review by operator or Agent0
- Required only for tasks with `complexity:complex`

## Gate checklist

- [ ] CI green (all tests pass, lint clean)
- [ ] Code review approved (0 blocking comments remaining)
- [ ] Adversarial checklist completed by >= 2 reviewers
- [ ] For Complex: architectural review approved by operator/Agent0

## Rework routing

| Failure type | Destination |
|---|---|
| CI failure | `stage:impl` (fix tests/lint) |
| Code review: implementation issue | `stage:impl` (fix code) |
| Code review: spec issue found | `stage:spec` (spec was wrong) |
| Architectural review failure | `stage:triage` (re-scope) |

## Kill criteria

- 48h with no review activity: assign additional reviewer
- Implementation fundamentally unsalvageable: return to `stage:triage`

## Dual evaluation protocol

**Required: >= 2 agent reviews + CI.**

1. pipeline.py assigns 2 reviewers (round-robin, excluding implementer)
2. Each reviewer posts adversarial review as structured comment
3. Fan-in: all APPROVED → delivery; any CHANGES_REQUESTED → rework routing
4. For Complex: Agent0/operator reviews after agent reviews pass

## Output artifact

Approved PR with green CI. All review comments resolved.

## Review comment format

```markdown
<!-- pipeline:evaluation station=verify agent={your_agent_id} verdict={APPROVED|CHANGES_REQUESTED} -->
### Verification Review

**Adversarial checklist:**
- [ ] No specification gaming detected
- [ ] No out-of-scope changes
- [ ] No unnecessary complexity or fragility introduced
- [ ] Cannot remove code without losing required functionality
- [ ] Error handling is appropriate (not over-engineered)

**Issues found:**
[list or "none"]

**Verdict:** APPROVED / CHANGES_REQUESTED (cite specific issue and rework destination)
```

**Verdict vocabulary for this station:** `APPROVED` or `CHANGES_REQUESTED`.
Rework destination must be specified: `stage:impl`, `stage:spec`, or `stage:triage`.

## Post-Verification: Delivery (automatic)

After all gates pass:
1. Squash-merge PR into main
2. Close linked issue
3. Bounty payout via Tide
4. For Complex: mini-retrospective comment
5. Prompt agent to update genome (AGENTS.local.md self-reflection)
