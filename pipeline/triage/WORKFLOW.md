# Triage Stage

> **Historical Pipeline v3 instructions.** Retained for legacy rendering,
> parsers, schemas and fixtures. For current vNext work, follow
> [CONTRIBUTING](../../CONTRIBUTING.md), [WORKPLACES](../../docs/WORKPLACES.md),
> [Tide](../../docs/TIDE.md) and the exact approved task contract.
> This historical procedure does not assign agents, fund or admit Work, grant
> author approval, accept contributions, settle payment or close current tasks.
> Fixed panels, vote thresholds and "CI is the judge" below describe the old
> pipeline; they are not current vNext authority. Schema validation and CI
> provide evidence, not canonical acceptance or payment.

Purpose: decide whether the task deserves a promise.

Protocol:
- Panel: operator, agent0, cursor, gemini.
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
