# Pipeline Comment Parsing Spec

Machine-parseable format for evaluation comments. Comments not matching these patterns are rejected by pipeline.py.

## Via Negativa (stage:negativa)

**Prefix:** `### Via Negativa Evaluation by {agent_id}`

**Lines 1–6:** Each must match:
```
^\d+\. [^:]+: (PASS|FAIL) — .+$
```
- Exactly 6 lines
- Label before colon: alphanumeric + spaces (e.g. "Not duplicate")
- Value: exactly `PASS` or `FAIL`
- Note after em-dash: non-empty

**Verdict:** Must match:
```
^Verdict: (PROCEED|KILL) \(item #\d+ — .+\)$
```

**Rejected:** Extra text, wrong casing, missing lines, parenthetical doubt in verdict.

## Spec Review (stage:spec)

**Prefix:** `### Spec Review by {agent_id}`

**Required lines:**
- `Red Team result: GAMING FOUND` or `Red Team result: NO GAMING FOUND`
- `Approval: APPROVED` or `Approval: REJECTED`

## Verification Review (stage:verify)

**Prefix:** `### Verification Review by {agent_id}`

**Checklist:** Four lines matching:
```
^- (Gaming|Out-of-scope|Fragility|Removable code): (NONE|FOUND) — .+$
```

**Verdict:** `Verdict: APPROVED` or `Verdict: CHANGES REQUESTED`
