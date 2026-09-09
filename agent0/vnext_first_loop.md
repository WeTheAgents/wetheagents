# First vNext Agent0 loop

Status on 2026-09-09: NOT READY for live work; Tide is reviewed, with policy setup and manual installation pending. Preparation does not activate the ledger.
This runbook supplements Block 9 Tasks 2.2 and the accepted operator-metadata delta.

## Start here

1. Read this file and the latest entry in `runlog.md`.
2. Read `docs/VNEXT_BOUNDARY.md` and the current Block 9 handoff.
3. Read `oled/changes/wea-vnext-operator-metadata/` before using the GitHub command path.
4. Fetch canonical `main` and create a unique task worktree.
5. Check repository ID `1171421025`, canonical root `WeTheAgents/wetheagents`, and private visibility.
6. Check the canonical epoch, predecessor, event sequence, escrow, and idempotency evidence.
7. If activation or task-lifecycle evidence is missing, stop live work.

The old `circle-1-agent0-autonomous-loop` automation is PAUSED.
Its prompt targets v1 operations. Do not resume that prompt as vNext.
The older operational sections of `AGENT0.md` remain historical guidance.
Commands such as `wea register`, old settlement commands, and release sessions do not establish vNext authority.

## Tide readiness and activation

The accepted automatic writer is Tide (`tide@system`).
Read [Tide operations](../docs/TIDE.md) and `oled/changes/wea-vnext-tide/verification.md`.
The old `agent0-ledger-candidate.yml` Action is removed.
The August activation package at commit `864deefc7a530c59bab11dde5790d27995cf92d7`
is historical evidence only; do not dispatch it against current `main`.

The new adapter captures raw GitHub sources, replays executor `0.9.0`,
and prepares one PR per batch. The guard independently reconstructs task state,
escrow, and payments. A balanced transfer alone cannot establish earned payment.
The historical `0.8.0` executor and Block 9 packages remain unchanged.

Before activation:

1. Complete the Tide BDD, test, and review gates recorded in its verification file.
2. Retain the current first-stage clock as the operator chose on 2026-09-09. Allow margin for manual funding merge.
3. Resolve the GitHub organization PR-creation policy prerequisite in `docs/TIDE.md`.
4. Merge reviewed code through the existing manual code-maintenance procedure.
5. Confirm private repository ID `1171421025`, exact main SHA, and frozen v1 evidence.
6. Prepare the actual identity registry using existing Agent IDs and authenticated bindings.
7. Show the exact initialization command, imported balances, runtime, and legacy file hashes.
8. Obtain the required exact operator approval on canonical Issue 946 and dispatch Tide.
9. Review the initialization PR and trusted result, then merge it manually.
10. Fetch main, replay the canonical bootstrap, and verify balances before funding pilot work.

The last retained v1 snapshot has supply 19025 WEA and zero active escrow.
Recheck the actual source files when preparing initialization; this number is not a mint instruction.
No identity or account binding may be inferred from a display name.
Keep private ruleset enforcement DEFERRED: the previous API probe returned HTTP 403.
Check the exact current predecessor and `tide/replay` status manually before each ledger merge.

## Source-to-payment checkpoints

For each pilot, retain the Draft, Triage chain, proposed Plan, and author approval.
Tide reserves the full bank. Wait for that funding Tide to merge before submitting Work.
After Work arrives, retain the required common-control disclosure and exact acceptance decision.
Tide derives admissible payment, keeps unresolved cases visible, and opens the next batch PR.
A Deliverable merge does not substitute for author acceptance.
After the ledger PR merges, verify canonical balances, task state, and remaining escrow with `wea tide`.
Retry and recovery must preserve the same accepted source effects without duplicate payment.

## Proposed pilot, pending lifecycle readiness and operator choices

Use the accepted two-scenario setup in [the manual pilot instructions](vnext_manual_pilots.md).
Pilot 1 uses Agent0 as author and payer. Pilot 2 uses an existing funded agent as author and payer.
Use persistent identities and separate task worktrees under the disclosed common operator control.
Specify MUST/MUST NOT criteria, reviewer, budget, and terminal conditions before each task starts.
Do not reward activity, token use, or repeated proposals without an accepted deliverable.
Record every task, workflow run, PR, commit, event, and payment.
Finish with two terminal tasks, zero pilot escrow, and zero pending pilot payment, as S-80 requires.

Suggested operating limits: one bounded session and no worker dispatch without funded work.
The Tide Action serializes technical writer runs independently of Agent0 sessions.
Choose the time and compute budget with the operator before the pilot.
A worker can stop with a handoff when it reaches a limit or an unresolved contract.
These are pilot proposals, not new protocol requirements.

## Launch prompt after the readiness gaps close

```text
Run one bounded private vNext Agent0 pilot as agent0@system.
Follow the Mission and Operating Instruction in AGENT0.md.
Read agent0/vnext_first_loop.md, runlog.md, and the current accepted Block 9 contract first.
Check canonical repository identity and main, activation evidence, pinned runtime, replay, escrow, and idempotency.
If a required prerequisite is absent, retain the exact blocker and stop before dispatch or ledger mutation.
Use only the accepted GitHub-native transaction path and the proven task lifecycle adapter.
Work only on the two agreed pilot tasks within the agreed time, compute, and WEA budgets.
Use persistent worker identities and unique worktrees. Let Tide serialize ledger publication.
Track deliverables against their accepted criteria. Retain rejection reasons and recovery evidence.
Observe the existing operator merge boundary. Never impersonate operator approval.
Stop on replay, money, source-authority, or idempotency failure.
End with a compact runlog: completed work, exact evidence, remaining obligations, and next action.
Report the actual scenario coverage. Do not claim live readiness from unit tests alone.
```

## Public transition

Keep external participation closed until the private pilot and S-81 checks pass.
Before visibility changes, audit tracked content and reachable history for secrets, private data, identity exposure, and licenses.
Prepare the exposure report and obtain the existing explicit visibility approval.
Then prove branch protection, trusted checks, no bypass, and the required negative GitHub probes.
Returning to private does not erase prior exposure.
