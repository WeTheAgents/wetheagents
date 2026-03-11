# Verify Stage

Purpose: prove the implementation is real, not just passing.

Protocol:
- Start with two reviewers.
- Compare unique valid findings.
- The stronger reviewer enters the Circle of Validation.

Each reviewer checks:
- gaming,
- out-of-scope changes,
- fragility,
- removable code.

Rules:
- Verify does not reopen triage by default.
- If the spec itself is broken, route back explicitly and log why.

Output:
- structured reviewer findings,
- verdict: `APPROVED` or `CHANGES_REQUESTED`,
- rework route if needed.
