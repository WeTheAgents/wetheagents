# Agent0 handoff: Spec 0.9 review pending

The inactive WEA vNext reference runtime now implements Outcome/Spec `0.9`. Design/schema `1.0`, delta/migration `0.9`, tasks `1.2`, ruleset/interface `0.8`, executor `v0_8_0`, the exact BDD registry, and contract tests are reconciled. `BDD alignment: 100%`. WEA vNext remains `Not live`.

Status: `Implementation verified — independent PR review pending`.

## Repository boundary

- Worktree: `D:\GitHub\wetheagents-codex-wea-vnext-resolution-plan-block4-2026-07-30`.
- Branch: `codex/wea-vnext-resolution-plan-block4-2026-07-30`.
- Current base: `252c6ca` (`origin/main` after three unrelated BTC snapshot commits). The feature commit is rebased on this base.
- Ruleset `0.8` SHA-256: `eb5eb18c66bc2a0a4fb53925627e387567b56a303ddc7bae24574fad43b519d7`.
- Executor `v0_8_0` manifest SHA-256: `578ff950e6f08ab6933f427bd87958e263fba2684b11367b3498e36abaafa129`.
- Ruleset `0.7` and executor `v0_7_0` retain the historical Resolution Plan intake and activation behavior. Older `0.6.x` executors retain their versioned replay behavior.

## Delivered behavior

- Triage proposes a complete Resolution Plan and budget split. The author approves, requests revision, or declines. Exact schedules and the full bank are part of approval.
- Each Plan stage chooses a depth (`Explore`, `Spec`, or `Implement`) and a mode (`Ranked`, `Flat PoD`, `Frontier`, or `Duel`) allowed by the exact matrix.
- Ranked, Flat PoD, Frontier, and Duel implement exact finite admission, deadlines, settlement, refund, underfill, pause, and replay rules. Flat PoD closes when its last slot is paid. Accepted Duel move numbers increase while expired empty slots remain skippable.
- One accepted immutable revision feeds the next child Contract. Ambiguity pauses progression. A suffix replan cannot change the completed or active prefix.
- Body pause and resume require exact current Issue revisions. A risk pause keeps submissions open but blocks stage decisions and settlement. Body resume preserves it.
- Frozen pre-pause roles still follow their own terms. Only an exact active Triage or review generation can publish a risk warning.
- Each lifecycle event requires an accepted GitHub source under a complete confirmed read boundary. An approval source must follow its exact Plan source.
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

- `tests/vnext`: `386 passed`, `18 skipped`.
- Full repository: `4671 passed`, `18 skipped`, `11 xfailed`.
- Ruff: clean. Targeted Pyright: `0 errors, 0 warnings`. Compileall: clean.
- Ledger invariant: PASS, `19025 = 10000 + 9025`. Ledger schema, task-index schema, and doc sync: PASS.
- Rules and manifest use exact canonical bytes. `git diff --check`: clean.
- Draft PR: `#941`. Passes 1–5 closed 13 defects. Pass 6 was clean. Pass 7 found one P1 Duel-order defect. Its regression fix is ready for pass 8.

## Hard stop boundary

This delivery does not add or change a live Tide or CLI writer, `ledger/vnext/`, GitHub Issue state, WEA funding, migration records, bootstrap, Domain/Access behavior, or cutover. OD-11, OD-14, OD-28, and OD-29 remain deferred. OD-28 and OD-29 block only the future live migration/bootstrap phase.

## Next action

Push the pass 7 fix. Run `codex exec review` again and fix every actionable finding. Then publish the review-clean handoff and artifact.
