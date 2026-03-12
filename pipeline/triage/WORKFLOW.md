# Triage Stage

Purpose: decide whether the task deserves a promise.

Protocol:
- Panel: operator, agent0, cursor, antigravity.
- Votes are `GO` or `NO_GO`.
- `3-1` means go.
- `1-3` means no-go.
- `2-2` means duel if there are two clear outcomes, otherwise governance.

Rules:
- Record the main reason, not just the vote.
- Name the next route: `negativa`, `spec`, `impl`, or `governance`.
- Keep triage decisive. Do not implement or spec inside triage.

Output:
- structured vote records,
- final route,
- one short summary in the task issue.
