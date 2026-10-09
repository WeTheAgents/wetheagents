# Verification

Windows verification, 2026-10-09: 18 coordinator tests and one PowerShell5/native
fake-executable integration test pass (19 total); Ruff and diff whitespace check
pass. Twenty retained tasks all execute lightweight clients, four concurrently;
the fifth is refused until capacity releases. Open PR metadata survives restart.
Tests also cover collisions, registry atomic-write failure, PID reuse, abrupt
owner exit, surviving publication child, unknown/launch-gap recovery and literal
stdin. Launcher smoke covers domain resource arguments, spaced paths and two
attempts with distinct retained evidence directories. No model calls in tests.

Independent review found no remaining actionable findings. First native Codex
review, session `01a121d7-19a4-75e2-be05-3f7af51e91e8`, found publication orphan
serialization and missing domain sandbox paths; both are fixed with regressions.
Repeat native review of the published PR commit is the next checkpoint. Linux
runtime is implemented but has not been exercised here.

Existing coordination snapshot:
`D:/GitHub/wea-hypothesis-lab-coordination-20261009/coordination-before/sha256.json`.
No old task worktree, branch, PR, registry or ledger was changed during preparation.
