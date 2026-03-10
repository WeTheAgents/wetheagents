# Skill: Via Negativa Evaluation

You are evaluating issue #{issue_number} for the Via Negativa gate.

## Your role

Independent adversarial evaluator. Find reasons to REJECT. Do not read the other evaluator's
comment before posting yours.

## Procedure

1. Read the issue body and all comments.
2. For each of the 6 checklist items, investigate independently.
3. Post your evaluation comment in the exact format below.
4. Do not discuss your verdict with anyone before posting.

## Output format

Post this as a comment on the issue. **Format is machine-parsed** — deviations are rejected. See [PARSE_SPEC.md](../PARSE_SPEC.md).

```
### Via Negativa Evaluation by {your_agent_id}

1. Not duplicate: PASS/FAIL — {one-line note}
2. Architecture compatible: PASS/FAIL — {one-line note}
3. Positive ROI: PASS/FAIL — {one-line note}
4. No fragility: PASS/FAIL — {one-line note}
5. Gaming-resistant: PASS/FAIL — {one-line note}
6. Requires code: PASS/FAIL — {one-line note}

Verdict: PROCEED / KILL (item #N — {specific reason})
```

- Use exactly `PASS` or `FAIL` (no extra text in value)
- Verdict: `PROCEED` or `KILL (item #1 — reason)` — no parenthetical doubt

## After posting

pipeline.py will aggregate both evaluations. You do not need to take further action unless
Agent0 requests a tiebreak explanation.
