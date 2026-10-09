# Verification

Windows verification, 2026-10-09: 18 coordinator tests and one PowerShell5/native
fake-executable integration and package-boundary test pass (20 total); Ruff and diff whitespace check
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

The published first commit `f17e23b1cb0febce10a4c43c23160d9b88822bc5` received
a clean native review in session `01a121df-275f-7652-be46-ec94cf02592e`.
Subsequent integration inspection moved the unchanged coordinator into `scripts`
to preserve the installed Hello World fingerprint. All 190 protected package
files match origin/main; both package hashes are
`7d5dadbc3caa1c894b074e5678d9f57042dfbfdfd1ae433fc4ecf72eec779ec5`.
This preserves current package identity; it does not repair the pre-existing
Hello World installation mismatch. Separate PR #1061 remains necessary.
Absolute script invocation and an older-checkout package-shadow regression pass.
The new published head requires a final native review.

Existing coordination snapshot:
`D:/GitHub/wea-hypothesis-lab-coordination-20261009/coordination-before/sha256.json`.
No old task worktree, branch, PR, registry or ledger was changed during preparation.
