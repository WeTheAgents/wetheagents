# Verification: WEA vNext Block 9 BDD

## Artifact Versions

- Outcome version: 1.0.
- Spec version: 1.0.
- Parent migration and decision delta overlays: 1.2.
- Design version: 1.0, accepted on 2026-08-18 and pinned externally.
- Tasks revision: 2.0, accepted on 2026-08-22 and pinned externally.
- Implementation status: dormant code Groups 1, 3, 4, and 5 authorized; no
  code completion is claimed yet.

## Contract and Authority

- Accepted-future behavior: S-71 through S-79 in `spec.md`.
- Accepted owner decisions: gauntlet mint retirement, achievement-history-only,
  separate ikigai work, and permission to prepare the Block 9 Design lane.
- Exact Outcome/BDD acceptance: accepted without changes by the WEA operator
  on 2026-08-17 in the current Codex task.
- Protected boundaries: no live write, no gauntlet mint, achievement history
  has no replay effect, one writer, exact reconciliation, and no automatic v1
  fallback.
- Exact Design acceptance: accepted by the WEA operator on 2026-08-18.
- Exact Tasks acceptance: accepted by the WEA operator on 2026-08-22. It
  authorizes only code work in Groups 1, 3, 4, and 5.
- Required next authority outside code: a separate operator approval before
  Group 2 environment mutation or Groups 6 and 7.
- Required activation authority: a later exact operator and Agent0 approval.

## Scenario Coverage

| Scenario scope | Evidence | Result |
| --- | --- | --- |
| S-71 through S-79 are accepted-future only | `tests/vnext/scenarios.py`, registry test, and exact BDD headings | PASS. Proposed-future remains empty. |
| R-B9-01 through R-B9-09 each map to one scenario | `spec.md` scenario evidence map | PASS. |
| All 70 implemented scenarios stay current | Complete vNext suite and registry test | PASS. |
| No Block 9 runtime behavior is claimed | No Block 9 production module or behavior test exists | PASS. Design remains next. |
| No live or ledger boundary changes | Status and protected-path inspection | PASS. |

## Task Completion

| Required task | Evidence or blocker | Result |
| --- | --- | --- |
| Record all six operator decisions | Parent decision registry, locked HTML, and hash-bound deterministic text record | PASS. The sixth decision separately records exact BDD acceptance. |
| Prepare and accept complete Block 9 BDD | R-B9-01 through R-B9-09 and S-71 through S-79 | PASS. Accepted without changes on 2026-08-17. |
| Bind the exact accepted bytes without rewriting them | `WEA_vNext_BLOCK9_ACCEPTANCE.txt`; builder hash guard | PASS. The frozen Outcome/Spec retain their preparation-time labels; the external manifest pins and supersedes status. |
| Track accepted-future scope without changing current scope | Scenario registry is 70 current / 9 accepted-future / 0 proposed-future | PASS. |
| Reconcile parent current meaning | Outcome, migration/delta overlays, boundary, handoffs, and generators | PASS. |
| Implement dormant Block 9 code Groups 1, 3, 4, and 5 | Exact Tasks 2.0 acceptance manifest | Authorized and in progress; no completion claimed yet. |
| Activate vNext | Exact later operator and Agent0 approval is absent | Forbidden. |

## Fresh Commands

| Command or check | Exit / result | Material evidence |
| --- | --- | --- |
| Focused S13C, registry, and runtime gate | 0 | `53 passed`. |
| `python -m pytest tests/vnext -q` | 0 | `499 passed, 18 skipped`. |
| Ruff on changed Python surfaces | 0 | All checks passed after the final review fixes. |
| Pyright on changed Python surfaces | 0 | `0 errors, 0 warnings`; only existing configuration/version notices remain. |
| Doc sync, invariant, ledger schema, task-index schema | 0 | All pass. Economy remains `19025 = 10000 + 9025`. |
| Current SDD HTML build and `--check` | 0 | Deterministic artifact, local links, locked decisions, sources, and exact accepted Outcome/Spec hashes validate. |
| Parent HTML build and `--check` | 0 | Accepted-BDD/current-status overlay is reproducible. |
| Playwright desktop/mobile inspection | 0 | Six locked accepted choices, nine accepted BDD cards, 70/9/0, Design-only gate, no console errors, and no page overflow at 1280 px or 390 px. |
| Protected-path and whitespace inspection | 0 | No production, writer, credential, workflow, or ledger change; whitespace is clean. |

Pytest reports the existing asyncio fixture-scope warning. It is unrelated to
this documentation delivery.

## Scope and Dirty State

| Entry | Classification | Action |
| --- | --- | --- |
| Block 9 Outcome/Spec/Tasks/Verification/Handoff | intended | Retain. |
| Parent SDD overlays and engineering boundary | intended | Retain current decision meaning and historical provenance. |
| Scenario registry and its contract test | intended | Retain 70 current, nine accepted-future, and zero proposed-future IDs. |
| S13C reconciliation, tests, and current HTML | intended earlier work in this branch | Retain and verify. |
| Parent HTML builder and generated review | intended compatibility fix | Retain so the historical/current review remains reproducible. |
| Production modules, ledger, credentials, workflows | protected | No changes. |

Unrelated user work was preserved: yes. All work is in the dedicated branch
and worktree.

## Independent Review

Trigger: money, authority, identity, migration, recovery, and external state
make the Serious Change Gate applicable.

First fresh-context review: `/root/block9_bdd_neutral_review` on 2026-08-16.

| Severity | Finding | Resolution |
| --- | --- | --- |
| HIGH | Atomic bootstrap conflicted with fallible projections, and S-79 required convergence before retry. | Fixed. R-B9-05 limits atomicity to authoritative epoch/ledger effects. S-79 now exposes `projection_degraded` before retry and requires convergence after idempotent retry. |
| HIGH | S-71 could not detect an omitted or late-added writer. | Fixed. The inventory binds to an independently derived frozen writer universe and rejects omissions, additions, bypasses, and delayed writers. |
| HIGH | `convert-with-fresh-approval` had no single money sequence. | Fixed. v1 escrow closes first, genesis stores only a conversion intent, and one post-cutover idempotent activation creates the debit, program escrow, Plan, Task, and first child Contract atomically. Dual escrow and direct-Contract activation are forbidden. |
| HIGH | S-78 relied on inactive S13C and absent durable recovery mechanisms. | Fixed. Durable authenticated correction and durable `replay_repair`, with crash/restart evidence, are explicit cutover prerequisites. |
| MEDIUM | Parent SDD reconciliation broke its retained HTML generator. | Fixed. The builder understands the current overlay, renders 70 current / 0 accepted-future / 9 proposed-future status, and implements a real deterministic `--check`. |
| MEDIUM | S13C tasks and verification still claimed interactive persistence after the HTML became a locked record. | Fixed. The records now describe locked rendering, copy, and download only. |
| MEDIUM | The displayed fingerprint omitted primary boundary and registry sources. | Fixed. The selected-source fingerprint now includes the parent decision records, migration/schema/delta, boundary document, production correction module, scenario registry, and runtime tests. The footer labels its scope. |
| MEDIUM | Parent migration/delta were both changed and described as stale. | Fixed. Decision overlays are version 1.1 and current for OD-28/OD-29. Only technical Design/schema mechanics remain pending. |

Second fresh-context review: `/root/block9_bdd_second_neutral_review` on
2026-08-16.

| Severity | Finding | Resolution |
| --- | --- | --- |
| HIGH | The approval bundle did not bind the exact transition or sole writer. | Fixed. R-B9-05 now binds the canonical bootstrap bytes/hash, epoch, predecessor, resulting state, exact `agent0@system` writer and credential binding, and recovery implementation versions. Substitution and drift reject before any effect. |
| HIGH | The conversion intent did not define what exact and fresh approval meant. | Fixed. R-B9-02 now fixes the complete source, payer, target, bank/runtime, authority, time, and idempotency payload; it defines a terminal one-shot state machine and rejection after expiry, rotation, mutation, reuse, or insufficient funds. |
| HIGH | Copy/download omitted exact candidate and decision identities and left no durable review record. | Fixed without overstating authority. The generated deterministic record contains the full selected-source fingerprint, prepared-candidate hash, decision payload hash, local base, scope, and exact choices. HTML copy/download exports those exact bytes and says the record is not standalone proof of an operator act. |
| HIGH | The parent Outcome version could be read as still current at 1.0. | Fixed. Parent Outcome now declares composite Outcome 1.1 and treats Domain/Access 1.0 as its preserved baseline. Parent Spec declares the exact current composite contract. |
| MEDIUM | The current HTML artifact had not been regenerated after source changes. | Fixed. Both builders now regenerate deterministically and have real stale-output checks. |
| MEDIUM | Durable recovery did not explicitly retain the accepted S13C 1.1 contract. | Fixed. R-B9-08 requires the durable path to implement or strictly extend S13C 1.1, lists its financial and tamper guarantees, and binds its implementation and crash evidence into the cutover bundle. |

Third fresh-context review: `/root/block9_bdd_final_neutral_review` on
2026-08-16.

| Severity | Finding | Resolution |
| --- | --- | --- |
| HIGH | The exact Block 9 Outcome/BDD was labeled operator-accepted although it was drafted after the operator requested it. | Fixed. The five business decisions remain accepted, while Outcome/Spec 1.0 and S-71 through S-79 are proposed for exact operator review. The registry is 70 current / 0 accepted-future / 9 proposed-future. Design waits for BDD acceptance. |
| HIGH | Conversion activation silently reopened a direct-Contract money path and bypassed the accepted Plan authority model. | Fixed. R-B9-02 binds the exact complete author-funded Plan and atomically creates debit, program escrow, Plan, Task, and first child Contract. Direct-Contract conversion rejects. |
| HIGH | A substituted non-Agent0 identity could become the sole writer. | Fixed. R-B9-05 requires exactly `agent0@system` and its approved active authenticated credential binding; any other Agent ID rejects. |
| HIGH | The derived text file was presented as immutable standalone authority evidence. | Fixed. It is now labeled a deterministic source-bound record, names the unavailable authenticated repository source limitation, and does not claim to prove the operator act or accept the later BDD. |
| MEDIUM | S13C and parent resume pointers still named version 1.2 or Design as immediately next. | Fixed. Exact pointers name Tasks/Verification 1.3, BDD review is next, and actual Design waits for acceptance. |
| MEDIUM | Parent migration and the permanent boundary contained weaker procedural approvals and ambiguous direct-Contract mechanics. | Fixed. The migration analysis is explicitly proposed, preserves complete Plan activation, and defers to the exact separate authenticated bundle with `agent0@system`. |
| MEDIUM | Both generated HTML artifacts were stale during the review. | Fixed by final regeneration and deterministic `--check` after the status corrections. |
| MEDIUM | Playwright left an untracked accessibility snapshot inside the worktree. | Fixed. The generated browser residue was removed and is not part of the delivery. |

Post-fix narrow recheck: no remaining actionable finding. The reviewer
confirmed the exact proposed-status surfaces, deterministic checks, Plan
conversion, `agent0@system` writer rule, and absence of Playwright residue.

Acceptance-promotion fresh-context review:
`/root/block9_acceptance_fresh_review` on 2026-08-18.

| Severity | Finding | Resolution |
| --- | --- | --- |
| HIGH | A first hash manifest incorrectly attributed post-acceptance metadata bytes to the operator's earlier acceptance. | Fixed. Outcome/Spec 1.0 were restored to their exact preparation-time bytes. `WEA_vNext_BLOCK9_ACCEPTANCE.txt` pins those unchanged hashes and records the later acceptance externally, so the files are not rewritten after acceptance. A negative temp-byte probe is rejected. |
| MEDIUM | Parent overlay and S13C verification pointers still named 1.1/1.3 after promotion. | Fixed. Mutable current records consistently name composite Outcome and decision overlays 1.2 plus S13C Tasks/Verification 1.4. The frozen accepted snapshot intentionally retains its preparation-time 1.1 references. |
| MEDIUM | Completion evidence still described five decisions or marked the final browser/build checks pending. | Fixed. Final evidence records six locked decisions, 70/9/0, exact acceptance wording, deterministic builders, and zero desktop/mobile overflow or console errors. |
| MEDIUM | Current reader entrypoints linked only to the frozen Spec and did not explain its internal proposed/pending labels. | Fixed. `docs/VNEXT_BOUNDARY.md`, `operator-review.md`, the handoff, and HTML pair the frozen snapshot with the exact acceptance manifest and explain current overlay 1.2. |

Final narrow recheck: no actionable finding. The reviewer confirmed the frozen
snapshot, acceptance binding, current overlay pointers, deterministic builds,
and clean diff are mutually consistent.

## Protected Lean Cut

- Calibration: retain the operator decisions, nine observable future
  scenarios, exact current/future separation, no-live boundary, and evidence
  needed to review them.
- `delete`: no separate Block 9 application or production stub was added.
- `reuse`: the existing scenario registry, parent SDD package, and HTML builders
  remain the proving surfaces.
- `stdlib` and `native`: the new current artifact builder uses the Python
  standard library and native browser APIs.
- `yagni`: implementation mechanics stay out until Design. Planned tests are
  locators, not false evidence.
- Rejected cut: removing negative writer, conversion-money, durable recovery,
  or projection-degradation cases would reopen review findings.
- Irreducible complexity: nine scenarios are required because writer
  completeness, money reconciliation, genesis, shadow, cutover, retirement,
  recovery, and projections have different failure boundaries.

## Evidence Gaps and Non-blocking Limitations

- Blocking evidence gap for preserving this accepted BDD: none.
- Approval gap for the authorized dormant code scope: none. Group 2,
  Groups 6 and 7, and Group 8 retain their separate authority gates.
- Non-blocking limitation: behavior tests for S-71 through S-79 do not exist.
  This is expected before Design and implementation.
- Non-blocking environment limitation: the remote origin was not refreshed in
  this worktree. Evidence is pinned to local `origin/main` at `0ea6513`.

## Completion Decision

`Authorized for dormant code Groups 1, 3, 4, and 5; not implemented or cutover-ready`.
The operator accepted exact Tasks 2.0 and its lean cut on 2026-08-22. Host and
GitHub setup, real v1 mutation, rehearsal, and activation remain unauthorized.
