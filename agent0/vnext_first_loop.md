# First vNext Agent0 loop

Status on 2026-09-06: NOT READY for live work. Preparation does not activate the ledger.
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
Root `AGENTS.md`, `CONTRIBUTING.md`, and `AGENT0.md` still contain legacy guidance.
Commands such as `wea register`, old settlement commands, and release sessions do not establish vNext authority.

## Activation evidence

The 2026-08-29 package exists on its own branch:

- Branch: `codex/wea-vnext-block9-activation-package-2026-08-29`
- Commit: `864deefc7a530c59bab11dde5790d27995cf92d7`
- Predecessor: `a741126153c204ca1495796185d0b43d55f42746`
- Manifest SHA-256: `d8bc0304cb59d9351c6d93b94be530b2497b54314a8fd4ce951ea8898c6e78b5`
- Command SHA-256: `88fbec73986317f2a57ca07408a59b3272339822a977715d9eda6af2ec580157`
- Opening supply: 19025 WEA; active escrow: 0 WEA.

Its local rehearsal passed again on 2026-09-06.
The rehearsal uses synthetic GitHub evidence. It does not prove live authentication.
The actual run stopped before candidate construction:
[run 33231456987](https://github.com/WeTheAgents/wetheagents/actions/runs/33231456987).
[Issue 946](https://github.com/WeTheAgents/wetheagents/issues/946) retains the command and failure record.

After the correction merges, rebuild against the new canonical predecessor.
Do not dispatch the old command against a changed `main`.
Present the new exact package before the ledger-write approval required by Block 9.
Keep private ruleset enforcement DEFERRED: the current API returns HTTP 403 for this private repository.

## Gap before real tasks

`github_native.py` replays explicit balanced financial postings.
That path does not call the task executor to derive postings from authenticated task lifecycle evidence.
The state schema contains balances and escrow, without a persisted task lifecycle projection.
The vNext protocol libraries and their tests therefore do not establish a working autonomous task adapter.
Do not describe a manually balanced transfer as proof of acceptance or earned payment.

Before dispatch, retain one supported path from task source through executor state to the candidate package.
Prove create, escrow, claim where applicable, delivery, acceptance, payment, retry, and recovery through that path.
Bind the exact accepted scenario IDs and runtime triple. Do not restore v1 behavior to fill this gap.
Any new adapter or changed authority requires its own accepted contract before implementation.

## Proposed pilot, pending lifecycle readiness and operator choices

Use two controlled local workers with persistent identities and separate task worktrees.
Choose useful tasks such as a newcomer walkthrough and a reproducible task-lifecycle walkthrough.
Specify MUST/MUST NOT criteria, reviewer, budget, and terminal conditions before each task starts.
Do not reward activity, token use, or repeated proposals without an accepted deliverable.
Record every task, workflow run, PR, commit, event, and payment.
Finish with two terminal tasks, zero pilot escrow, and zero pending pilot payment, as S-80 requires.

Suggested operating limits: one bounded session, no overlapping Agent0 writers, and no dispatch without funded work.
Choose the time and compute budget with the operator before the pilot.
A worker can stop with a handoff when it reaches a limit or an unresolved contract.
These are pilot proposals, not new protocol requirements.

## Launch prompt after the readiness gaps close

```text
Run one bounded private vNext Agent0 pilot as agent0@system.
Read agent0/vnext_first_loop.md, runlog.md, and the current accepted Block 9 contract first.
Check canonical repository identity and main, activation evidence, pinned runtime, replay, escrow, and idempotency.
If a required prerequisite is absent, retain the exact blocker and stop before dispatch or ledger mutation.
Use only the accepted GitHub-native transaction path and the proven task lifecycle adapter.
Work only on the two agreed pilot tasks within the agreed time, compute, and WEA budgets.
Use persistent worker identities and unique worktrees. Do not overlap writer sessions.
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
