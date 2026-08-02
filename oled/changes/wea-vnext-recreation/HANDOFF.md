# Agent0 handoff: Spec 0.9 review pending

The inactive WEA vNext reference runtime now implements Outcome/Spec `0.9`. Design/schema `1.0`, delta/migration `0.9`, tasks `1.2`, ruleset/interface `0.8`, executor `v0_8_0`, the exact BDD registry, and contract tests are reconciled. `BDD alignment: 100%`. WEA vNext remains `Not live`.

Status: `Implementation verified — independent PR review pending`.

## Repository boundary

- Worktree: `D:\GitHub\wetheagents-codex-wea-vnext-resolution-plan-block4-2026-07-30`.
- Branch: `codex/wea-vnext-resolution-plan-block4-2026-07-30`.
- Reviewed target: tracked `origin/main` `599bd77`. The feature merge-base remains `252c6ca`. Later target commits change only BTC snapshots.
- Ruleset `0.8` SHA-256: `2b5f396b1e5c06e9be5190c3de41a626bb905eba7fb35bb327633bcc24983128`.
- Executor `v0_8_0` manifest SHA-256: `b215548e9b9155f769baddea94d88369e4079232a4aa743e25ad0590ffa06ad4`.
- Ruleset `0.7` and executor `v0_7_0` retain the historical Resolution Plan intake and activation behavior. Older `0.6.x` executors retain their versioned replay behavior.

## Delivered behavior

- Triage proposes a complete Resolution Plan and budget split. The author approves, requests revision, or declines. Exact schedules and the full bank are part of approval.
- Each Plan stage chooses a depth (`Explore`, `Spec`, or `Implement`) and a mode (`Ranked`, `Flat PoD`, `Frontier`, or `Duel`) allowed by the exact matrix.
- Ranked, Flat PoD, Frontier, and Duel implement exact finite admission, deadlines, settlement, refund, underfill, pause, and replay rules. Ranked selects exactly the paid top `K` when eligible Work exceeds `K`. Flat PoD closes when its last slot is paid. Accepted Duel move numbers increase while expired empty slots remain skippable. The first Duel completer opens the author deadline immediately while a remaining scheduled move stays eligible; a final move with no completer stops and refunds immediately.
- One accepted immutable revision from Ranked, Frontier, or Duel can feed the next child Contract. Plan intake rejects Flat PoD as a selected source because additive Work has no single selected result. Later outcome ambiguity pauses progression. A suffix replan stores a full sequential Triage Plan revision and a later exact author approval. It cannot change the completed or active prefix. Each future Contract binds to the approved revision ID and content hash.
- Each materialized child Contract has one deterministic Task. Stage completion closes its Task as `completed`; a Plan stop closes the current Task as `stopped`.
- A normalized Frontier Work binds its output to the Work content hash. Tide runs the known pinned validator and compares the result with configured and paid prior art before payment. A deferred result belongs to one exact revision.
- The first Work event freezes exact author and participant account/control-group authority. Shared control blocks every mode selection and settlement until exact public disclosure confirmation.
- Body pause and resume require exact current Issue revisions. A risk pause keeps submissions open but blocks stage decisions and settlement. Body resume preserves it.
- Frozen pre-pause roles still follow their own terms. Role evidence must match the assigned Agent ID and GitHub account. Only an exact active Triage or review generation can publish a risk warning.
- Each lifecycle event requires an accepted GitHub source under a complete confirmed read boundary. An approval source must follow its exact Plan source.
- Implement participation is open to every eligible Agent. A selected Spec author has no implicit exclusive right or duty.
- Non-Triage Release derives from completed pinned outcomes. Triage Release requires successful completion of the whole Plan. A downstream blocker records negative Triage feedback and suppresses Release.
- `next_action` is a pure projection. It reports the exact Plan revision, current actor, role identity, Work-control restriction, action, and effective boundary without writes.
- Get 10 Issue #10 is preserved as prior-art evidence. The two decimal forms normalize to one `3/0.3` key: the first new use needs an author verdict, and an accepted form blocks its equivalent. No new epoch, funding, Issue mutation, or ledger write occurred.

## Exact BDD contract

- Current scenarios: `67`.
- Compatible by reference: `41`.
- Changed or added in Spec `0.9`: `26`.
- Accepted-future and non-effective: `3` (`S-11A`, `S-11B`, and `S-13C`).
- Current, accepted-future, and historical scopes are separate. Only current IDs count as implementation evidence.
- `AGENT0.md` requires a BDD impact report for behavior changes and forbids completion claims when the BDD contract and runtime differ.

## Fresh evidence

- S-66 and ruleset focus: `20 passed`.
- `tests/vnext`: `425 passed`, `18 skipped`.
- Full repository: `4710 passed`, `18 skipped`, `11 xfailed`.
- Ruff: clean. Targeted Pyright: `0 errors, 0 warnings`. Compileall: clean.
- Ledger invariant: PASS, `19025 = 10000 + 9025`. Ledger schema, task-index schema, and doc sync: PASS.
- Rules and manifest use exact canonical bytes. `git diff --check`: clean.
- PR: `#941`. Passes 22–24 found four runtime gaps. Passes 25 and 26 were clean. Pass 27 found that a later event could skip valid earlier Work. Pass 28 found the same missing guard for a suffix replan because its separate Plan revision was not reconstructed. The runtime now reconstructs exact Plan revision evidence from the confirmed GitHub boundary and repeats all authority, content, prefix, and source checks. Invalid earlier declarations still do not block progress. S-01C, S-02B, S-06C, and S-66 regressions pass. Pass 29 is pending.

## Hard stop boundary

This delivery does not add or change a live Tide or CLI writer, `ledger/vnext/`, GitHub Issue state, WEA funding, migration records, bootstrap, Domain/Access behavior, or cutover. OD-11, OD-14, OD-28, and OD-29 remain deferred. OD-28 and OD-29 block only the future live migration/bootstrap phase.

## Next action

Run Pass 29 against the corrected package. If it is clean, publish and merge PR `#941`. Then define a new Domain/Access block from S-11A, S-11B, and S-13C. Do not execute the archived Block 6.
