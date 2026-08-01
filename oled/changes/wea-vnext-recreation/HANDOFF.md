# Agent0 handoff: Spec 0.9 review pending

The inactive WEA vNext reference runtime now implements Outcome/Spec `0.9`. Design/schema `1.0`, delta/migration `0.9`, tasks `1.2`, ruleset/interface `0.8`, executor `v0_8_0`, the exact BDD registry, and contract tests are reconciled. `BDD alignment: 100%`. WEA vNext remains `Not live`.

Status: `Implementation verified — independent PR review pending`.

## Repository boundary

- Worktree: `D:\GitHub\wetheagents-codex-wea-vnext-resolution-plan-block4-2026-07-30`.
- Branch: `codex/wea-vnext-resolution-plan-block4-2026-07-30`.
- Current base: `252c6ca` (`origin/main` after three unrelated BTC snapshot commits). The feature commit is rebased on this base.
- Ruleset `0.8` SHA-256: `e6b0c46795c443865acf8279bc4669c0511f7e92a77e95693e3adfc591cea0c1`.
- Executor `v0_8_0` manifest SHA-256: `5d3aca055c7290c39eae0ddc7b18e5dae1fa5ac81afbf438350ade5a66f69b56`.
- Ruleset `0.7` and executor `v0_7_0` retain the historical Resolution Plan intake and activation behavior. Older `0.6.x` executors retain their versioned replay behavior.

## Delivered behavior

- Triage proposes a complete Resolution Plan and budget split. The author approves, requests revision, or declines. Exact schedules and the full bank are part of approval.
- Each Plan stage chooses a depth (`Explore`, `Spec`, or `Implement`) and a mode (`Ranked`, `Flat PoD`, `Frontier`, or `Duel`) allowed by the exact matrix.
- Ranked, Flat PoD, Frontier, and Duel implement exact finite admission, deadlines, settlement, refund, underfill, pause, and replay rules.
- One accepted immutable revision feeds the next child Contract. Ambiguity pauses progression. A suffix replan cannot change the completed or active prefix.
- Body-integrity pause, Agent0 risk pause, frozen assigned-role terms, treasury role escrow, role generations, replacement races, and ordered stop behavior are explicit.
- Implement participation is open to every eligible Agent. A selected Spec author has no implicit exclusive right or duty.
- Non-Triage Release derives from completed pinned outcomes. Triage Release requires successful completion of the whole Plan. A downstream blocker records negative Triage feedback and suppresses Release.
- `next_action` is a pure projection. It reports the exact current actor, action, and effective boundary without writes.
- Get 10 Issue #10 is preserved as prior art. All six accepted expressions are classified; no new epoch, funding, Issue mutation, or ledger write occurred.

## Exact BDD contract

- Current scenarios: `70`.
- Compatible by reference: `44`.
- Changed or added in Spec `0.9`: `26`.
- Current, accepted-future, and historical scopes are separate. Only current IDs count as implementation evidence.
- `AGENT0.md` requires a BDD impact report for behavior changes and forbids completion claims when the BDD contract and runtime differ.

## Fresh evidence

- `tests/vnext`: `375 passed`, `18 skipped`.
- Full repository: `4660 passed`, `18 skipped`, `11 xfailed`.
- Ruff: clean. Targeted Pyright: `0 errors, 0 warnings`. Compileall: clean.
- Ledger invariant: PASS, `19025 = 10000 + 9025`. Ledger schema, task-index schema, and doc sync: PASS.
- Rules and manifest use exact canonical bytes. `git diff --check`: clean.
- Draft PR: `#941`. Review pass 1 closed two P1 timing defects. Pass 2 closed four P1 authority/progression defects. Pass 3 is pending.

## Hard stop boundary

This delivery does not add or change a live Tide or CLI writer, `ledger/vnext/`, GitHub Issue state, WEA funding, migration records, bootstrap, Domain/Access behavior, or cutover. OD-11, OD-14, OD-28, and OD-29 remain deferred. OD-28 and OD-29 block only the future live migration/bootstrap phase.

## Next action

Create the dedicated PR, run `codex exec review`, fix all actionable findings, repeat until clean, then regenerate this handoff, `verification.md`, and `WEA_vNext_REVIEW.html` from the final commit.
