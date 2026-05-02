# task_contract_completeness_rate — signal spec

Circle-1 phase 1. Source: `scripts/circle1/task_contract_extractor.py`.

## Definition

```
complete code-change tasks / all code-change tasks in cohort
```

A task is **complete** when it belongs to the code-change cohort AND its body
contains all four structural contract elements.

## Four required elements

| Element | What counts as present |
|---|---|
| `must` | At least one `- [ ] MUST:` checkbox line inside the `### Verification Criteria` section |
| `must_not` | At least one `- [ ] MUST NOT:` checkbox line inside the `### Verification Criteria` section |
| `verification_criteria` | The `### Verification Criteria` section header is present |
| `scope_boundaries` | The `### Scope boundaries` section header is present with at least one non-blank, non-`_No response_` line |

MUST and MUST NOT are checked **only within the Verification Criteria section**,
not in the full body. Checkboxes that appear elsewhere do not count.

## Code-change cohort

A task is included when:
- mechanic is not `"duel"`  AND at least one of:
  - `### Skills Needed` section contains the word "Coding"
  - `### Verification Criteria` text references a code or test artifact
    (`pytest`, `test`, `script`, `.py`, `PR`, `file change`, `commit`)

Non-code-change tasks appear in `findings` with `is_code_change: false` and
are excluded from the rate numerator and denominator.

## Output format

```json
{
  "scan_date": "YYYY-MM-DD",
  "phase": "phase-1",
  "definition": "...",
  "total_inspected": 10,
  "code_change_count": 8,
  "complete_count": 6,
  "incomplete_count": 2,
  "task_contract_completeness_rate": 0.75,
  "findings": [
    {
      "issue": "781",
      "is_code_change": true,
      "complete": true,
      "missing_elements": [],
      "present_elements": ["must", "must_not", "verification_criteria", "scope_boundaries"]
    }
  ]
}
```

`task_contract_completeness_rate` is `null` when `code_change_count` is 0.

## Required context

- Read together with task class and acceptance style; older tasks predate the
  current template and will underperform for historical reasons.
- The signal measures structural form, not semantic quality of the criteria.
- For new Circle-1 work, use
  `domains/circle-1/docs/canonical_issue_format_v1.md` as the manual authoring
  source. It explains how to write semantic `MUST` / `MUST NOT`, scope
  boundaries, anti-gaming, and monitoring language without changing the global
  GitHub issue template.

## Known escapes / gaming

- Adding empty or low-signal MUST / MUST NOT sections just to satisfy the
  checklist inflates the rate without improving contract quality.
- Re-labeling tasks as non-coding to exclude them from the denominator.

## Phase 1 boundary

This extractor classifies task bodies supplied as structured JSON input.
It does not mine full GitHub history. Wire it into broader circle-1
checkpointing by feeding it a batch of issue bodies from the API.
