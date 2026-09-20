# Verification

Contract: Outcome 1.0, Spec 1.0, Design 1.0.
Decision: Ready. Implementation checks, reviews and the separately approved installation are complete; see the live checkpoint below.
Base: `77d2ebec4154b91339aa5bfa4697032220e8318c`.
Account: `peachgabba22`, numeric ID `129645949`, canonical Agent0 role verified from Tide replay.
WEA remains private. The original checkout's saved changes remain outside this worktree.
There is no `genomes/agent0@system/` directory. The assigned system mission is `AGENT0.md`.

## Behavior evidence

| Scenario | Evidence |
| --- | --- |
| DWA-01 | Invalid/missing/duplicate scope, explicit internal scope and changed Draft body hash tests |
| DWA-02 | Real Tide Work admission, missing grant, exact agent/domain/time, funding/identity independence and later-grant retry tests |
| DWA-03 | Triage admission/completion, exact Draft retry regression, role and Duel subject checks |
| DWA-04 | Half-open endpoints, delayed valid source, real executor acceptance/payment after expiry and existing-operation exclusions |
| DWA-05 | Real journal-object capture, corrupted/unavailable evidence, schema downgrade, retained-prefix checks and independent authenticated guard recapture |
| DWA-06 | Historical task replay, ordinary discussion, unchanged Circle-1 and immutable executor paths |

All new admission scenarios are in `tests/vnext/test_tide_domain_admission.py`.
Time-based tests use synthetic clocks. They are not real seven-day observations.

## Checks

- First Tide/ledger/participant regression: 54 passed, exit 0.
- First focused admission run: 33 passed, exit 0.
- Expanded admission/Access/Tide/collection/activation/runtime-boundary run: 181 passed, exit 0, 211.06 seconds.
- After the Triage review fix, the three direct Triage/retry regressions passed, exit 0.
- Final admission/Tide/ledger/participants/Access/Release/role-deadline regression: 151 passed, exit 0, 212.76 seconds.
- Added Work scope-override regression: 1 passed, exit 0. The admission file then contained 41 cases.
- After all three native-review fixes: the full applicable regression passed 156 tests, exit 0, 195.86 seconds.
- Ruff on all changed Python: passed. `git diff --check`: passed.
- `python scripts/check_invariant.py`: PASS. Tide 16, balances 19025, escrow 0, supply 19025 WEA.
- All 16 canonical Tide batches replayed exactly against `origin/main`. No ledger bytes changed.
- Actual read at `2026-09-20T07:37:59.207764+00:00` reconstructed both existing Access grants from GitHub without writes.
- Codex-2 and Codex-19 remain active with their original September 25 endpoints. Source CLI `access show` reports `observed`, `actual-utc-read`, `active`.
- Actual production-client capture at `2026-09-20T08:08:01.266593+00:00` used exactly one REST request and one native Git transfer. It read both original active grants without writes. Receipt: `.wea_runs/domain-admission/live-native-capture.json`.
- Exact read artifacts remain ignored under `.wea_runs/domain-admission/` in the task worktree.
- Simple English self-check: the three longest normative statements contain 18 words each. Technical identifiers remain unchanged.
- Draft PR: https://github.com/WeTheAgents/wetheagents/pull/1008. Original code head: `c2b59acaffb54dce9323d9fe7b71e480b3af4a01`. Review-fix code head: `3fa22ab7eae58dd350136d4e360c28a30c6fd872`.
- CI on that head: Semgrep, doc-sync, vNext boundary and Workers checks passed. The trusted ledger guard and `tide/replay` failed.
- CI on review-fix head `42bca6726f3775d6a3e227350aa06a074042f54d`: Semgrep, doc-sync, boundary and Workers passed; trusted ledger validation and `tide/replay` failed again (run `35498639357`).
- Exact guard error: `candidate writer universe changed: src/wea_vnext/tide/domain.py`. Run: `35497755355`. No status or guard was bypassed.
- First native review completed with three actionable findings, fixed below. Repeat native review exited 0 with no actionable defects and independently passed all 45 admission tests. Review used the installed npm CLI. The older root bundled CLI first rejected `service_tier=default`, then rejected the configured model as requiring a newer CLI. Shared configuration was not changed.

## Independent review

1. Fresh reviewer found a P1 Triage scope-retry bypass. An assignment processed under an old internal scope could authorize a later domain Plan without grants.
   Fixed: bind Triage sources to the exact admitted Draft and recheck the reviewer at assignment time during completion.
   The original three-batch reproduction now leaves zero escrow and unresolved assignment/completion.
2. A second fresh reviewer examined the complete corrected artifact and reported no actionable findings.
3. Native post-PR review found a P1 unbounded REST journal-read regression, a P2 digit-prefixed Domain ID rejection and a P2 `none` scope collision.
   Fixed: capture uses the existing native Git-object reader, with cleanup on success/failure; scope selection defers Domain authority to the canonical registry; internal scope uses `-`, outside the Domain ID namespace.
   Focused regressions preserve `1-research` and `none` as domains that require Access and forbid per-object REST reads in production capture.
4. Repeat native review of the complete patch against the original base returned no actionable defects (exit 0). It independently passed all 45 admission tests.
   Retained output: `.wea_runs/domain-admission/native-review-repeat.txt` and `.jsonl`.

## Scope and protected cut

The implementation reuses the Access journal and Tide transport, replay, escrow, dispositions and trusted guard.
It adds one small admission module, small integration changes and focused tests. No dependency, alternate writer or general claim operation exists.
Read-only historical journal mode is necessary because historical writer packages differ from current Tide packages. It cannot append decisions.
Live writer checks remain exact. Removing scope binding, source-time checks, prefix preservation or guard recapture would weaken authority.
No safe additional cut was identified. Existing tests retain historical semantics and use explicit internal scope for new candidates.
Public Circle-1 files, GitHub permissions, registries, ledger data and released executor closures remain unchanged.

## Deployment boundary

The live Access genesis pins all vNext files plus its CLI/workflow. This patch changes files in that closure.
The existing Access writer therefore rejects new grants if this candidate is merged without an accepted closure transition.
Read-only inspection and historical replay work. They do not authorize replacing the live writer closure.
The operator subsequently approved that transition. PR #1008 was manually installed and its append-only update succeeded; exact current evidence is in `../wea-access-protocol-transition/verification.md`.
No closure update format, reactivation, replacement genesis or migration is silently introduced here.
BDD alignment: implementation evidence covers DWA-01..06. Live schema-3 checkpoint Tide 17 passed local replay, native review and the trusted guard, then merged through PR #1009. No new paid Work or actual seven-day expiry observation is claimed.

## Live checkpoint

PR #1008 installed at `2026-09-20T08:41:37Z`. The exact operator package update and original grants were verified live. Tide 17 / PR #1009 merged at `2026-09-20T08:56:09Z` with four retained Access records and unchanged balances. The accepted transition contract and detailed receipts are in `../wea-access-protocol-transition/`.
