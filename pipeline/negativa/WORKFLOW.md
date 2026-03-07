# Station: Via Negativa

## Purpose

Null hypothesis gate — "this task should NOT be done until proven otherwise." Eliminates unnecessary work, negative ROI, and fragility before any specification or code is written.

## Input criteria

- Issue has label `stage:negativa`
- Issue has `complexity:complex` (only Complex tasks pass through this station)
- Cynefin and appetite labels already assigned at Triage

## Process

1. **Read** the issue body, shaping comment, and all linked context.
2. **Evaluate independently** against the 6-point kill checklist. Do not read other evaluators' assessments before posting your own.
3. **Post your evaluation** as a structured comment (see output format below).
4. **Wait for fan-in**: pipeline.py collects both evaluations and resolves.

## Gate checklist

- [ ] All 6 kill-checklist points checked and documented
- [ ] Both evaluators posted independent assessments
- [ ] Verdict: both PROCEED to advance (unanimous required)

## 6-point kill checklist

| # | Check | Question |
|---|-------|----------|
| 1 | Not duplicate | Is this already solved or in progress elsewhere? |
| 2 | Architecture compatible | Does this contradict existing architecture or principles? |
| 3 | Positive ROI | Is the expected value greater than the cost? |
| 4 | No fragility | Does this avoid introducing new dependencies, tech debt, or failure points? |
| 5 | Gaming-resistant | Can the spec be satisfied without solving the real problem? |
| 6 | Requires code | Can this be solved with docs, config, or deletion instead? |

## Kill criteria

- Any single kill-checklist item fails: close with `rejected:via-negativa` label
- Both evaluators KILL: reject with combined reasoning
- Evaluators disagree: Agent0 casts tie-breaking vote

## Dual evaluation protocol

**Required: 2 independent evaluators.**

1. pipeline.py assigns 2 agents from the evaluator pool (round-robin, excluding task author)
2. Each evaluator posts assessment independently (no reading the other's first)
3. Fan-in resolution:
   - Both PROCEED: advance to `stage:spec`
   - Both KILL: reject with `rejected:via-negativa`
   - Disagree: Agent0 posts tie-breaking evaluation

## Output artifact

Two evaluation comments on the issue, plus pipeline resolution comment.

## Evaluation comment format

```markdown
<!-- pipeline:evaluation station=negativa agent={your_agent_id} verdict={PROCEED|KILL} -->
### Via Negativa Evaluation

| # | Check | Result | Notes |
|---|-------|--------|-------|
| 1 | Not duplicate | PASS/FAIL | [details] |
| 2 | Architecture compatible | PASS/FAIL | [details] |
| 3 | Positive ROI | PASS/FAIL | [details] |
| 4 | No fragility | PASS/FAIL | [details] |
| 5 | Gaming-resistant | PASS/FAIL | [details] |
| 6 | Requires code | PASS/FAIL | [details] |

**Verdict:** PROCEED / KILL (cite failed item #)
```

**Verdict vocabulary for this station:** `PROCEED` or `KILL`.
