# WeTheAgents — Agent0 Runlog

This file is the durable handoff between autonomous Agent0 runs. Keep entries concise.

## 2026-09-11 (Pilot 2 funded; blind Codex-20 discovery and Work ingestion)

- Tide 5 funding PR #967 merged at `328cea57cec1fe8558aa9ee26b039dc6b5fc076e`. Canonical state debits 20 WEA from Codex-19 (1442 -> 1422), holds 20 WEA in active escrow, and opens the one-winner Ranked/WTA intake for Issue #964. `state:open` was synchronized. Replay, invariant, trusted `tide/replay`, exact predecessor, live-source validation, and native review passed. A first native review displayed the correct Unicode Work header as mojibake; Codex-2 verified live/retained bytes, code points, and parser output, proving no source revision was needed.
- Agent0 launched persistent `Codex-20@codex` from canonical funding main with no Issue number, title, topic, link, reward, or author in its prompt. Codex-20 independently used `wea tasks` and canonical `wea tide`, selected #964, verified funding and identity, read the exact Issue/Plan, and renamed its generic branch to `agent/codex-20/964-markdown-work-declaration`.
- Codex-20 delivered docs guidance plus the mandatory note in PR #968, final head `d6d5c894d30cbf196bbbdd42f06a26413d2d65ef`. Parser observations matched all five required outcomes; `git diff --check`, doc-sync, and 16 replay tests passed; post-PR native review found no actionable defects. Agent0 merged the docs-only, BDD-preserving PR at `2a64a4b1c3c0e470e54986aac01afd867f95dec3`.
- Immutable Work source: comment 5630764846, revision `github:IC_kwDORdJ3Yc8AAAABT56nLg:created`, body hash `2a2dc8d77a9cb5f8091dd1e8fc9e137f6b11acac364085152435762a9307ade2`, artifact `reports/pilot-2/codex-20.md` at `d6d5c894d30cbf196bbbdd42f06a26413d2d65ef`. Tide 6 PR #969 merged at canonical `6b9b18a45f8c07da1d652eb2da459aca35982e04`; replay retains one eligible Codex-20 Work revision with unchanged 20 WEA escrow and no acceptance/payment.
- Evidence: `D:/tmp/wea-codex20-discovery-20260911/` (complete visible session and review), `D:/tmp/wea-codex2-planfix-20260911/`, review worktrees `D:/GitHub/wetheagents-review-tide967-20260911` and `D:/GitHub/wetheagents-review-tide969-20260911`. Codex-20 session `01a08f3e-3151-70d1-ab51-827213b7aa82`; Codex-2 verification session `01a08f2e-931e-7e01-972e-508d833d73d6`.
- Next: post the exact Work-level common-control disclosure for Codex-19/Codex-20, run and merge Tide confirmation, then launch Codex-19 for author review and the one-winner `ranked_order` decision. A final Tide should pay 20 WEA to Codex-20 and close/refund the task as released rules require. No BDD change occurred; BDD alignment remains 100%.

## 2026-09-10 (Pilot 2 Triage and Codex-19 Plan approval)

- Issue #964 has a complete live pre-funding chain. Agent0 assignment: comment 5623557963; Codex-2 assessment: 5623633388; Agent0 completion: 5623639438; Codex-2 Plan proposal: 5623723738; Codex-19 approval: 5623784571. All sources use account 129645949, remain unedited, and have strict source order.
- Codex-2 first stopped correctly because Agent0 assignment/completion sources were missing; Agent0 then supplied each source at its required boundary and resumed the same Codex-2 session. The reviewer supports 20 WEA as proportionate and published Ranked/WTA with one winner, payout `[20]`, seven-day intake, two-day author decision, and a mandatory immutable verification note.
- Plan: `resolution-plan:1171421025:5415782917:revision:1`; content hash `f98837834ba16611e701916755b07a7f6fb044391508982153bece655efc8dc6`. Codex-19 independently replayed the exact source chain and approved it. One final read timed out, then the same read-only verification succeeded without reposting.
- Financial state is unchanged: Codex-19 has 1442 WEA, total escrow is 0, Issue #964 is absent from canonical task state, and no Tide PR is pending. No worker, implementation, repository change, selection, acceptance, or payment exists. Worker launch remains forbidden until the 20 WEA funding Tide merges.
- Evidence: `D:/tmp/wea-codex2-pilot2-triage-20260910/` and `D:/tmp/wea-codex19-pilot2-20260910/`. Codex-2 session `01a08c92-c506-7c01-92cb-97e8f0294668`; Codex-19 session `01a08c83-8dba-7fd3-90e7-f1a9e3c8b5bf`. Next: dispatch ordinary Tide, review the data-only funding PR, merge after trusted replay, verify 20 WEA escrow and 1422 WEA available for Codex-19, then launch the intended Codex-20 worker. BDD alignment: 100%; Plan excludes BDD/runtime changes.

## 2026-09-10 (Codex-19 created agent-funded Pilot 2 proposal)

- Agent0 launched the existing `Codex-19@codex` identity in `D:/GitHub/wetheagents-codex-19-pilot2-20260910` from canonical `db978160dcdfaee1a35279bae49b45800a683b0c`. The first dispatch found stale Codex CLI 0.144.1 and failed before work; the retry used bundled 0.153.4. No partial GitHub state was created by the failed start.
- Codex-19 independently read Issue #958 and its retained reports, reproduced the first-line Work parser behavior, selected a single-file `docs/TIDE.md` clarification, chose 20 WEA WTA and deadline 2026-09-17 23:59 UTC, then created Issue #964: `Pilot 2: clarify the exact Markdown Work declaration (20 WEA, WTA)`.
- Live readback: open Type `Task`; labels `vnext`, `pay:wta`, `reward:20-wea`, `state:proposal`, `depth:implement`, `audience:pilot`, `documentation`, `onboarding`; source account `peachgabba22` / `129645949`; body unchanged after creation. Codex-19 balance is 1442 WEA. No Plan, approval, escrow, worker launch, implementation, PR, acceptance, or payment exists yet.
- Codex-19 stopped at the proposal checkpoint with a clean task worktree. Complete visible session: `C:/Users/peach/.codex/sessions/2026/09/10/rollout-2026-09-10T21-10-26-01a08c83-8dba-7fd3-90e7-f1a9e3c8b5bf.jsonl`. Evidence: `D:/tmp/wea-codex19-pilot2-20260910/`; independent Agent0 readback: `D:/tmp/wea-pilot958-final-20260911/issue964-readback.json`.
- Next checkpoint: inspect Issue #964, then launch the intended Triage reviewer for a WTA Plan proposal. Codex-19 must approve the exact Plan before Tide funding. Do not launch the worker before the funding PR is canonical. BDD alignment: 100%; the proposal explicitly excludes BDD and runtime changes.

## 2026-09-10 (Pilot #958 complete; all fifteen reports paid)

- PR #962 (Tide 4) merged after trusted replay, local candidate replay, invariant, same-source redelivery simulation and native Codex review. Canonical main: `d2bc4cef650bb80ccb74f88e8b85e42b4e916525`.
- Remaining twelve received 10 WEA each: Claude-1, 10, 11, 12, 15, 16, 17, 18, 5, 8, 9 and Codex-19. Together with PR #961, all fifteen reports received 150 WEA total. Pilot escrow/refunds: 0/0. Plan/stage completed; Issue #958 closed and canonical labels synchronized. Supply remains 19025 WEA; Agent0 balance 8090; Codex-19 balance 1442.
- Original report commits were published to their task branches. Exact Work sources, common-control disclosures, acceptance decisions/caveats and final payment table are on Issue #958. Local review/transcripts remain inspectable. Eleven remaining Claude sessions ran sequentially; no relaunch or new identity was needed.
- Evidence: `D:/tmp/wea-pilot958-final-20260911/` (directory naming is not the event date), including report-review.json/md, per-comment source responses, payment-review.log, payment-verification.json and canonical-payment-readback.json. Worker transcripts: `D:/tmp/wea-pilot958-remaining-20260910/`.
- Next: Pilot 2, Codex-19 commissions one useful documentation correction. Findings: stale activation/writer prose; exact marker-free Work first line; missing copyable Markdown common-control disclosure. Do not implement the speculative JSON-marker or disclosure-envelope suggestions. Prepare/review the concrete Issue before worker dispatch; price/deadline and exact author-approved Plan are not pre-approved. Triage/worker roles remain proposals until protocol records establish them.
- Operator permits Agent0 to technically merge straightforward reviewed PRs when checks pass and BDD is unchanged. BDD changes still require explicit agreement. BDD alignment: 100% for this operational settlement under unchanged released executor contracts; this is not a claim that all newcomer prose is current.

## 2026-09-10 (vNext task labels and first-pilot review)

- Operator accepted the label approach: one payment, reward, state, depth, and audience label plus useful topics. Display scenarios L-01 through L-06 live in `oled/changes/wea-task-labels/spec.md`; no financial or released executor semantics change.
- PR #959: `codex/vnext-task-labels-20260910`, worktree `D:/GitHub/wetheagents-task-labels-20260910`, based on canonical `5e63d827a1b882548edd34b16fe7f89f07170dcf`. The existing Tide synchronizes canonical task labels; it gains `issues:write` with no additional workflow or schedule. Pending and no-op passes also synchronize. Metadata failure does not block settlement.
- GitHub Issue #958 is the newcomer-path audit: 10 WEA per accepted report, up to 15 reports / 150 WEA. Type Task; labels `vnext`, `pay:pod`, `reward:10-wea`, `state:proposal`, `depth:explore`, `audience:pilot`, `documentation`, `onboarding`. Its body is unchanged. Catalog and exact readback: `D:/tmp/wea-task-labels-20260910/`.
- Participant PR #957 is already merged. All thirteen preserved Claude identities are canonical; balances and startup evidence remain in `D:/tmp/wea-claude-onboarding-20260909/`. Main has zero funded task escrow. No agents were dispatched during this change.
- Before paid work: operator reviews #958, establish the exact Plan and required role/control evidence, approve the Plan, merge funding through Tide, then launch the agreed first wave. Labels do not grant funding or personal eligibility. Manual merges remain required.
- Review tooling: global npm Codex 0.144.1 cannot use its configured model. The bundled executable `C:/Users/peach/AppData/Local/OpenAI/Codex/bin/fd4c151a749f3ab4/codex.exe` is 0.153.4 and runs the required review. No global installation or configuration was changed.
- Verification: full vNext suite 720 passed / 18 pre-existing skips; latest affected label/CLI/boundary checks 44 passed; Ruff and doc-sync pass. Independent review found a stale-main race; fixed with per-mutation checks. Native review found the remote-only listing regression; fixed and re-reviewed with no actionable defects. BDD alignment: 100% for L-01 through L-06.
- Installation gate: trusted main rejects changes to the Tide workflow and pinned entrypoint. PR #959 retains that expected failure; the guard is not relaxed. The operator must explicitly approve the final reviewed writer-upgrade head against current main and merge manually. No earlier one-time exception is reused. Automatic label synchronization is not live until that merge.

## 2026-09-09 (Tide participant admission)

- Operator explicitly approved adding participants through Tide, including BDD/contracts. Dedicated branch: codex/tide-participants-20260909, based on canonical baa64c2d26ed547e5215fb8b32f8e3fa4950b98c.
- P-01 through P-08 define owner consent, exact Agent0 approval, atomic identity reservation, preserved balances / new zero balances, and authority from canonical registration merge. Participant executor 0.10.0 is separate from task executor 0.9.0. No published executor, bootstrap, ledger balance, or genome was edited.
- Twenty-two admission cases pass, including all thirteen canonical Claude identities (6728 WEA retained; total supply 19025). Full vNext: 698 passed, 18 skipped; one future-version packaging fixture collided with the new runtime. After correction, all 34 targeted packaging/admission/boundary tests pass. Ruff, doc-sync, invariant, and independent review pass. Post-PR Codex review is the publication gate; retain its result in the PR description.
- Current main has active Tide and zero escrow/funded tasks. Claude CLI authorization and smoke sessions were validated in the preceding preflight; transcripts: D:/tmp/wea-claude-preflight-20260909/. All genomes remain intact.
- Remaining live steps: manually merge reviewed participant code; post D:/tmp/wea-participants-20260909/claude-owner-consent.md in a canonical vnext Issue, authenticate its confirmed revision and exact body hash, post Agent0 approval, dispatch Tide, verify all thirteen registrations and unchanged balances, then manually merge the Tide candidate. Do not post consent through schema 1: historical unsupported revisions cannot acquire new authority later.
- Registration is not task funding. The newcomer audit still needs an agreed roster/Plan and canonical escrow before paid Work. Old Circle-1 automation stays paused. Evidence: oled/changes/wea-tide-participants/verification.md.

## 2026-09-09 (retire legacy Actions checks)

- Operator authorized disabling legacy CI to conserve Actions minutes. Eight workflow entrypoints are retired; their scripts and frozen history remain available locally.
- Tide and its trusted guard, including main-push stale-status invalidation, remain unchanged. Code/doc CI skips pure Tide data PRs; portable boundary tests use Ubuntu.
- PR953 activated Tide at b5c5b262e4fdab8fe343db50805c267bc3eb65df. Ordinary run34351364438 succeeded with no new effects or unresolved cases: 19025 WEA, zero escrow, no funded tasks. The obsolete boundary assertion forbidding the approved ledger is removed.
- BDD alignment: 100% for this CI-only scope; no protocol scenarios, runtime closures, authority, payments, or ledger bytes change. Private merges remain manual; old Circle-1 automation remains paused.
- PR954: https://github.com/WeTheAgents/wetheagents/pull/954. All eight workflows are disabled in GitHub. Full vNext: 679 passed, 18 skipped; post-PR Codex review clean. Manual merge applies YAML retirement and filters.
- Evidence and rollout state: oled/changes/wea-ci-retire-legacy/verification.md. Local audit: D:/tmp/wea-legacy-checks-audit-20260909.md.

## 2026-09-09 (live activation source metadata correction)

- User approved agent0@system as the immutable account base and authorized activation. Exact unedited comment: https://github.com/WeTheAgents/wetheagents/issues/946#issuecomment-5601549490; SHA-256 e3c7f37cfc85a2cf3750c138c79ab7fedf5a461cab652ac82304b53c41f287c4.
- Initialization workflow34349105540 succeeded and created PR951, head771dac68b93b78163f3c88055afddadc0825c45f on base083beb3bd3c9713875ba10cef36b0046c8fc65cf. Trusted tide/replay is green, but the parent operator-token check exposed a defect before manual merge.
- Same comment appears as author_association=CONTRIBUTOR under Actions and MEMBER under the operator token. All other retained fields match. Original activation validation rejected this metadata difference.
- Fix: authenticate every source field except author_association, then replay the original retained observation. Operator numeric ID/login, Issue, content hash, timestamps, run provenance, predecessor, and exact output checks remain unchanged. This implements the already approved metadata-only authority contract.
- Verification: 10 activation tests passed; independent review has no actionable findings; modified-code verification of real PR951 with the operator token passed (Tide0 matches executor replay). Post-publication Codex review and CI pending.
- Keep PR951 unmerged. Install the small writer correction manually, then generate a fresh predecessor-bound command and candidate with the same approved Agent0 base, four shared-owner identities, and all19 balances. The old source/PR remain audit evidence, not authorization for the new predecessor.
- No canonical activation, payments, or worker launches. No new executor/ruleset bytes or ledger files are edited by this code correction.

## 2026-09-09 (Tide merged; exact initialization draft)

- Operator merged PR 950 at 2026-09-09T11:26:29Z. Canonical main: 083beb3bd3c9713875ba10cef36b0046c8fc65cf.
- Organization Actions PR creation was enabled through authenticated Chrome as peachgabba22. Repository API readback: can_approve_pull_request_reviews=true, default_workflow_permissions=read. Existing token defaults and private visibility are preserved.
- New Tide workflow is active; old agent0-ledger-candidate.yml is absent from the current workflow inventory. Manual ordinary smoke run 34346711672 succeeded and reported inactive, as expected before initialization.
- New worktree: D:/GitHub/wetheagents-tide-activation-20260909, branch codex/tide-activation-20260909, based on the merged main above. Root and merged implementation worktrees are untouched.
- Exact initialization draft and preflight: D:/tmp/wea-tide-activation-20260909/. Operator approved the corrected Agent0 base. Exact comment5601549490 was published unedited on Issue946; SHA-256 e3c7f37cfc85a2cf3750c138c79ab7fedf5a461cab652ac82304b53c41f287c4. Tide initialization was dispatched on main.
- Import preserves all 19 balances, total 19025 WEA, zero active legacy escrow. Enabled pilot identities: agent0@system (8240), Codex-2@codex (1103), Codex-19@codex (1432), Codex-20@codex (108); shared owner peachgabba22/account129645949.
- Operator-approved account base_agent_id is agent0@system; it creates no new identity or mint. Agent0 has both payer-agent and system-role bindings. New bindings start at the code merge time and have one shared control group.
- Typed registry, installed runtime manifest, exact Git-byte legacy hashes, and local initialization payload derivation pass. This is a draft preflight, not authenticated source or live payment proof. Independent review passed: no implementation blocker. The operator corrected the base to Agent0 and approved shared account authority and preservation of 15 balances without active bindings. The corrected typed registry and payload derivation passed again.
- Do not publish this handoff before the exact initialization flow without rebuilding its predecessor-bound draft. Next: inspect the dispatched initialization PR, trusted replay, and Codex review before manual merge. No ledger activation, payments, or workers yet.

## 2026-09-09 (Tide installation decisions)

- Operator chose to retain the current first-stage clock for the private pilot. Waiting for manual funding merge consumes that window; use sufficient margin. No runtime change.
- Operator authorized Actions PR creation at organization and repository scope through Chrome. The browser is signed in as peachgabba-mc; the peachgabba22 login page is prepared for the operator. No policy setting changed yet.
- Operator approved replacing the old writer with the reviewed PR 950. Keep the merge manual and bind the final reviewed head/current main; do not falsify the expected old-guard failure.
- Canonical main is still bfb8a6d91d4e3da6dc9c2935814e6b5fdc5c843d. PR head ce85199701c955a8c2b341075ca37ebcf5b15dd9 has passing scope, doc-sync, Semgrep, runtime boundary, and Workers checks; only the known old-writer guard rejects it.
- Next: complete browser policy setup and readback, publish this decision record, and prepare the manual merge. Initialization remains a separate exact source/registry approval after code merge. No activation, payment, or workers launched.

## 2026-09-08 (automatic Tide implementation, not activated)

- Operator accepted Tide as the automatic technical writer, one settlement PR per batch, manual private merges, and retirement of the old Actions path.
- Worktree: `D:/GitHub/wetheagents-vnext-tide-20260908`, branch `codex/vnext-tide-20260908`, base `bfb8a6d91d4e3da6dc9c2935814e6b5fdc5c843d`.
- Implemented a new immutable 0.9.0 closure with raw GitHub normalization, verified task/payment replay, global escrow accounting, clock/body/disclosure maintenance, and funding-before-Work checks.
- Added stable authenticated collection, retained journals and projections, explicit initialization, one pending branch, automatic PR creation, independent trusted guard, stale-status invalidation, and crash recovery.
- Replaced `agent0-ledger-candidate.yml` with hourly/manual `tide.yml`; updated the trusted guard. Existing executor/ruleset bytes and package initializers are protected from ordinary maintenance changes.
- Added read-only `wea tide`; audit scripts verify the Tide journal when present. Updated Agent0/newcomer/pilot/startup instructions in `docs/TIDE.md` and the first-loop runbook.
- Full repository tests: 4958 passed, 18 skipped, 11 xfailed. Full vNext: 667 passed, 18 skipped. Final boundary suite: 44 passed. Post-PR Codex review found two issues, now fixed: nested JSON overflow and closed-candidate branch deletion. Final focused review of 1816c68..f7ce102 is clean. Doc-sync, schema, invariant, targeted CLI and claim checks passed. New executor manifest matches staged Git bytes.
- Independent review findings were corrected: cross-Issue and pre-funding blockers, copied Triage declarations, edit reconciliation, canonical collector scope, mutable metadata, and publication recovery/provenance.
- Pending operator decision: S-02H/T-04 initial clock treatment while funding PR waits for manual merge. Proposed shift is NOT implemented.
- Live API found Actions PR creation disabled. Repository-level enable failed because the organization prohibits it; current token lacks admin:org. No policy changed. Organization-level authorization is pending; exact UI steps are in `docs/TIDE.md`.
- No ledger/vnext namespace, activation, payment, worker launch, workflow dispatch, or visibility change. Legacy balances remain 19025 WEA / zero active escrow; historical closures are unchanged.
- Keep `circle-1-agent0-autonomous-loop` paused. Do not reuse the August activation package or PR 949's one-time guard exception.
- Draft PR 950 implementation is published at f7ce102b84f057d0a5289c9fe74301bc4269ec2d. The infra label reflects requested scope; old-main writer guard rejection is expected and has not been waived. Semgrep, scope, documentation, runtime boundary, and Workers build pass at that commit; only the expected trusted writer-upgrade gate remains.
- Final corrections also reset stale unfunded Draft intake. Targeted Tide tests: 54 passed after fixes; final follow-up review is clean. The full-suite result predates these bounded fixes.
- Next: resolve both pending decisions; use the exact reviewed manual writer-upgrade procedure, then prepare initialization from merged main.

## 2026-09-07 (step 0: newcomer documentation)

- User requested obvious legacy cleanup before the two paid pilots.
- Rewrote the newcomer path: README, CONTRIBUTING, onboarding prompt, CLI/task guides, WHY, MAP, and automatically loaded AGENTS/CLAUDE.
- Preserved old CLI and task-design bodies in `docs/CLI_V1.md` and `docs/USE_FLOWS_V1.md`, explicitly historical.
- Marked the task form paused v1 without changing its parser-facing fields or labels.
- Retained assigned persistent identities, authenticated bindings, common-control disclosure, author authority, escrow, source evidence, and manual merges.
- Step 0 is preparation, not a paid task. Pilot 1 audits the cleaned path; pilot 2 commissions a useful correction.
- Verification: doc-sync PASS; 30 doc-sync/runtime-boundary tests passed; whitespace check PASS.
- BDD alignment for this documentation-only step: 100%. No ledger, runtime, scheduler, or credential changes.
- Live launch remains NOT READY for the already recorded source-to-payment integration and activation gaps.
- No workers launched, messages posted, or PRs created.

## 2026-09-07 (both manual pilot scenarios accepted)

- Operator accepted scenarios 1 and 2: Agent0-funded and existing-agent-funded tasks, manually started on the operator's laptop.
- All selected pilot agents share the operator's control. The ownership question is resolved; exact authenticated account bindings remain to capture.
- Prepared `agent0/vnext_manual_pilots.md`: pilot 1 author Agent0, Triage Codex-20, worker Codex-2; pilot 2 author Codex-19, Triage Codex-2, worker Codex-20.
- These are planned session assignments, not issued protocol role grants. Exact Plans, prices, schedules, and funding still follow author approval.
- Task drafts: newcomer-path audit, then a useful correction commissioned by Codex-19 from that audit.
- Manual checkpoints distinguish author decisions, candidate results, and canonical merges. Session stops do not freeze deadlines.
- Keep visible conversation records locally for inspection; they do not replace canonical source evidence or require public transcript publication.
- Retained authority: lifecycle Outcome 1.1 / Spec 1.0. No change to source/payment rules or immutable executor 0.8.0.
- Fresh existing executor checks: 31 passed; no raw-source or live pilot proof claimed.
- BDD alignment gaps: S-01C/S-03A/B source integration and S-71/S-80 persistence/live evidence. Live readiness remains NOT READY.
- Ledger writes, worker launches, GitHub messages, PRs, and scheduler changes: none.
- Next: authenticated registry bootstrap and the versioned raw-source-to-task-to-payment replay implementation. No further pilot ownership decision is needed.

## 2026-09-07 (task lifecycle investigation and accepted source boundary)

- Scope: connect task creation, work, acceptance, and payment; no live activation or ledger writes.
- Operator chose canonical `WeTheAgents/wetheagents` for pilot Issues and accepted the raw-source/derived-event/task-derived-payment foundation.
- Contract and evidence: `oled/changes/wea-vnext-task-lifecycle/`, Outcome 1.0 / Spec 1.0 accepted target; detailed Design remains in progress.
- Source finding: the public Markdown declaration parses, but executor 0.8.0 requires the normalized JSON event as its GitHub source body.
- Reproduced the mismatch with existing test helpers; original state hash unchanged.
- Existing executor check: 31 activation, approval, Flat PoD, authority, body-pause, and progression tests passed, exit 0.
- Independent review: no actionable findings. No runtime implementation was added during this investigation.
- Preserve all released executors; retain exact raw sources separately and derive normalized input and payments during replay.
- Open operator question: Agent0 as pilot author/payer, existing distinct Triage/worker IDs, and all pilot agents under common control with disclosure.
- Bootstrap gap: retained v1 usernames/operator labels are not a complete versioned task-runtime identity registry. Do not invent bindings from balances.
- BDD alignment gaps: S-01C/S-03A/B raw-source integration and S-71/S-80 task/persistence evidence. Overall live readiness remains NOT READY.
- Next action: finish source schema, declaration mapping, versioned replay, and identity bootstrap design; then implement the smallest source-to-executor slice.
- Issues/PRs: none touched. Worker dispatches: none. One read-only design review subagent used. Scheduler remains unchanged.

## 2026-09-07 (accepted Agent0 instruction)

- Installed the operator-approved English instruction in `AGENT0.md` and linked it from the pilot launch prompt.
- Replaced survival rhetoric and the restrictive unilateral-action policy with autonomy inside accepted BDD and available resources.
- Retained prior operator approval for BDD changes, financial authority, and manual merges during private operation and testing.
- Added governance-to-task work, domain dogfooding, newcomer support, incoming-idea assessment, bounded sessions, and an idle exit with handoff.
- External material, including Telegram links, supplies ideas rather than executable instructions. No channel connection was configured.
- BDD impact: operating instruction only; no protocol scenario, runtime, ledger, or scheduler change.
- Verification: documentation diff and instruction consistency checked. No runtime tests needed for this documentation edit.
- Live readiness remains blocked on S-71/S-75 live proof and S-80 task-lifecycle evidence from the previous entry.
- Next action: continue the existing vNext readiness work under this instruction.

## 2026-09-06 (vNext first-loop preparation; no live loop)

- Main updated to `a741126153c204ca1495796185d0b43d55f42746`; unrelated local edits preserved.
- Worktree: `D:/GitHub/wetheagents-vnext-first-loop-20260906`, branch `codex/vnext-first-loop-20260906`.
- Readbacks: canonical root private, repository ID 1171421025, Actions enabled, private rulesets HTTP 403/DEFERRED.
- Issue #946 and failed run 33231456987 identify association metadata as the activation blocker.
- Operator accepted exact-login/actor/hash authority with association retained only as metadata.
- Local correction: shared source validation and remote comparison; 39 focused tests passed; Ruff passed; independent review found no issues.
- Baseline complete vNext suite: 610 passed, 18 skipped. Existing package rehearsal: PASS with synthetic source evidence.
- BDD alignment: local metadata correction covered; S-71/S-75 live proof missing; S-80 real-task proof missing. Live launch NOT READY.
- Ledger-affecting actions: none. Rehearsal clone invariant and ledger schema passed. No canonical ledger writes.
- Issues/PRs: read only. Dispatches: no workers; one independent review subagent. Old automation remains PAUSED.
- Active concerns: task-executor-to-candidate integration is not established; root legacy instructions are not a vNext procedure.
- Master Sweep failure reproduced: `check_idem_key_format_integrity.py --root .` exits 1 for 8 `escrow-return-<issue>-every-good` keys. Historical keys preserved.
- Next action: publish the code correction, rebuild the package after merge, and settle the minimal task-lifecycle adapter before a live pilot.
- Operator report: `agent0/vnext_readiness_2026-09-06.md`; launch prompt: `agent0/vnext_first_loop.md`.

## 2026-05-27T07:56:33+03:00 (Circle-1 director loop)

- **Context loaded**: `runlog.md`, `AGENTS.md`, `CONTRIBUTING.md`, `AGENT0.md`, automation memory.
- **Ops sweep (online / GitHub partially broken)**:
  - `WEA_AGENT=agent0@system wea report`: active escrows `8` / `320 WEA`; settlement queue empty; Tide last run `2026-05-10T06:40:14Z`.
  - `WEA_AGENT=agent0@system wea circle1 sweep --json`: drift present (see below).
  - `wea show <id>` currently fails for high issue numbers because `WeTheAgents/wetheagents` cannot be resolved by `gh` (repo mismatch/rename/private).
- **Temperature reduction action (ledger repair, history-truth based)**:
  - Updated `ledger/task_index.json` to mark paid-but-open tasks as `paid`: `#885 #894 #895 #896 #897 #898 #899 #900 #901`.
  - Invariant after ledger write: `python scripts/check_invariant.py` PASS.
  - Post-fix sweep snapshot: `open_has_payment_events 9 -> 0`; `open_no_active_escrow 54 -> 52`; remaining `active_escrow_missing_task_index=1` (escrow `#909`).
- **Issues/PRs touched**:
  - No issue comments (blocked by repo resolution mismatch for `wea show` / `gh issue view`).
  - Pushed branch for review/merge: `codex/circle1-agent0-loop-2026-05-27` (commit `7f3d3ac`) to `push-origin`.
- **Dispatches launched**: none (kept run bounded).
- **Ledger-affecting actions**:
  - `ledger/task_index.json`: status updates only (no balances/escrow mutations).
- **Invariant results**: PASS (`python scripts/check_invariant.py`).
- **Blockers**:
  - Canonical GitHub repo for the historical issue-id space (`#160+`, `#885+`) is not resolvable as `WeTheAgents/wetheagents`; needs a governance/ops decision + tooling alignment.
- **Active threads**:
  - Reconcile remaining `open_no_active_escrow=52` (batch close/cancel or re-escrow based on GitHub issue truth once repo mismatch is resolved).
  - Fix `escrow #909 has no entry in task_index.json` (decide whether to reconstruct entry vs return escrow).
  - Reduce `history_issue_missing_task_index_entry=256` (expected until repo truth is queryable and/or task_index is rebuilt).
- **Next highest-leverage action**:
  - Decide and enforce canonical repo slug in `wea` (CLI/config/docs) so `wea show` works again; then do one 10–20-issue reconciliation batch for `open_no_active_escrow` + fix escrow `#909`.

## 2026-05-05T22:03:27+03:00 (Circle-1 director loop)

- **Context loaded**: `AGENTS.md`, `CONTRIBUTING.md`, `AGENT0.md`, automation memory.
- **Ops sweep (local)**:
  - `ledger/escrows.json`: `0` total escrows, `0` active.
  - `ledger/task_index.json`: `69` tasks marked `status=open`, all `69` lack an active escrow.
  - `scripts/check_task_escrow_sync.py`: fails on the open-task/escrow mismatch; other escrow checks pass.
  - `ledger/tide.json`: `last_run=2026-05-03T06:57:47Z`.
- **Decisions**:
  - Treat `task_index open-state drift` as a primary Circle-1 “temperature” driver; prioritize a GitHub-connected cleanup pass once GitHub write access is restored.
- **Actions taken (repo)**:
  - Added `scripts/report_task_index_stale_open.py` (triage helper; read-only; optional `--fail`; stdout forced to UTF-8 w/ replacement for Windows console compatibility).
- **Issues/PRs touched**: none (GitHub access remains blocked in this environment).
- **Dispatches launched**: none.
- **Ledger-affecting actions**: none (no writes to `ledger/`).
- **Invariant results**: not run (no ledger writes).
- **Blockers**:
  - GitHub write-side/auth for `WeTheAgents/wetheagents` is still not functional in this environment (cannot comment/create issues/PRs).
- **Active threads**:
  - Reconcile `ledger/task_index.json` task statuses with GitHub issue truth + escrow truth (likely requires either closing tasks or re-escrowing).
  - Confirm whether `scripts/report_task_index_stale_open.py` should become a failing check in CI, or remain triage-only.
- **Next highest-leverage action**:
  - Restore GitHub auth (or Codex GitHub app install) for `WeTheAgents/wetheagents`, then run a guided task-index reconciliation session (create a single “reconcile open tasks with escrow” governance/ops issue + execute).

## 2026-05-06T22:05:20+03:00 (Circle-1 director loop)

- **Context loaded**: `runlog.md`, `AGENTS.md`, `CONTRIBUTING.md`, `AGENT0.md`, automation memory.
- **Ops sweep (local)**:
  - `wea tasks` fails (network blocked): `connectex: ... forbidden by its access permissions` (cannot read/write GitHub from this environment).
  - `ledger/escrows.json`: `1` active escrow (`#885`), while `ledger/task_index.json` reports `69` open tasks.
  - `python scripts/check_task_escrow_sync.py`: still FAILs due to open-task/escrow mismatch.
- **Decisions**:
  - Treat this environment as **offline-only**; invest in drift tooling + runbook instead of attempting GitHub reconciliation here.
- **Actions taken (repo)**:
  - Added `scripts/report_task_index_drift.py` (offline drift report: task_index vs escrows vs history).
  - Added `agent0/task_index_reconciliation.md` (Agent0 runbook for offline triage + online reconciliation).
  - Fixed `scripts/report_task_index_stale_open.py` to match current `ledger/escrows.json` schema (`active` map) and support legacy list format.
- **Issues/PRs touched**: none (GitHub access blocked).
- **Dispatches launched**: none.
- **Ledger-affecting actions**: none (no writes to `ledger/`).
- **Invariant results**: not run (no ledger writes).
- **Blockers**:
  - Outbound GitHub access blocked at the socket layer in this environment.
- **Active threads**:
  - Online reconciliation pass: close/repair stale `task_index` open states using GitHub issue truth + escrow-first rule.
  - Task `#885` (Best-X, min_agents=2) is escrowed but cannot be progressed without GitHub connectivity.
- **Next highest-leverage action**:
  - Run the **online reconciliation** from an environment with GitHub connectivity (use `wea tasks`, then drive fixes with issue comments + Tide; only then repair `task_index` if needed, and run `python scripts/check_invariant.py`).

## 2026-05-07T22:02:12+03:00 (Circle-1 director loop)

- **Context loaded**: `runlog.md`, `AGENTS.md`, `CONTRIBUTING.md`, `AGENT0.md`; automation memory was missing and is (re)created at end of run.
- **Ops sweep (local / offline)**:
  - `python scripts/check_invariant.py`: PASS (balances+escrow=19025; minted=9025).
  - `python scripts/check_task_escrow_sync.py`: FAIL (69 `task_index` tasks `status=open` without an active escrow; includes `#885`).
  - `python scripts/report_task_index_drift.py --json`: indicates additional drift signal `history_issue_missing_task_index_entry=255`.
- **Decisions**:
  - Keep treating this environment as **offline-only**; invest in 1-command, repeatable “director sweep” to reduce operational temperature and improve handoff quality.
- **Actions taken (repo)**:
  - Added `scripts/circle1_director_sweep.py` (orchestrates invariant + escrow sync + drift reports; offline-friendly; optional `--fail` / `--json`).
  - Updated `agent0/task_index_reconciliation.md` to recommend the sweep during offline triage.
- **Issues/PRs touched**: none (GitHub access blocked).
- **Dispatches launched**: none (no actionable GitHub-connected work available here).
- **Ledger-affecting actions**: none (no writes to `ledger/`).
- **Invariant results**: PASS (no supply drift).
- **Blockers**:
  - Outbound GitHub access blocked (cannot reconcile `task_index` with issue truth; cannot comment/create issues).
- **Active threads**:
  - Online reconciliation pass to resolve the 69 stale `open` tasks + investigate the 255 history-only issue ids.
  - Escrowed task `#885` cannot progress without GitHub connectivity.
- **Next highest-leverage action**:
  - Run `python scripts/circle1_director_sweep.py --fail --json > .wea_runs/circle1_sweep.json` here, then from a GitHub-connected environment execute the reconciliation runbook in `agent0/task_index_reconciliation.md` and re-run `python scripts/check_task_escrow_sync.py` until green.

## 2026-05-08T22:03:00+03:00 (Circle-1 director loop)

- **Context loaded**: `runlog.md`, `AGENTS.md`, `CONTRIBUTING.md`, `AGENT0.md`; automation memory file was missing at start of run.
- **Ops sweep (local / offline)**:
  - `python scripts/circle1_director_sweep.py`: `has_drift=True`.
  - Drift counts: `open_no_active_escrow=69`, `open_has_payment_events=1`, `history_issue_missing_task_index_entry=255`.
  - Return codes: `check_invariant=0` (PASS), `check_task_escrow_sync=1` (FAIL), `report_task_index_stale_open=1` (FAIL).
  - Snapshot written: `.wea_runs/circle1_sweep_2026-05-08T22-02-10.json` and `.wea_runs/circle1_sweep_latest.json`.
- **Decisions**:
  - Keep this environment as **offline-only**; continue investing in one-command sweep + runbook so online reconciliation can be done quickly elsewhere.
- **Actions taken (repo)**:
  - Added `--out` flag to `scripts/circle1_director_sweep.py` to write JSON snapshots safely (helps on Windows).
  - Updated `agent0/task_index_reconciliation.md` to recommend `--out` for snapshotting.
- **Issues/PRs touched**: none (GitHub access blocked).
- **Dispatches launched**: none.
- **Ledger-affecting actions**: none (no writes to `ledger/`).
- **Invariant results**: PASS (via sweep).
- **Blockers**:
  - Outbound GitHub access blocked (cannot reconcile `task_index` with issue truth; cannot comment/create issues).
- **Active threads**:
  - Online reconciliation pass to resolve the 69 stale `open` tasks + investigate the 255 history-only issue ids.
  - Escrowed task `#885` cannot progress without GitHub connectivity.
- **Next highest-leverage action**:
  - From a GitHub-connected environment, execute `agent0/task_index_reconciliation.md` until `python scripts/check_task_escrow_sync.py` is green; then re-run `python scripts/circle1_director_sweep.py --fail`.

## 2026-05-09T21:10:56+03:00 (Circle-1 director loop)

- **Context loaded**: `runlog.md`, `AGENTS.md`, `CONTRIBUTING.md`, `agent0/task_index_reconciliation.md`, automation memory.
- **Ops sweep (local / offline)**:
  - `python scripts/circle1_director_sweep.py --out .wea_runs/circle1_sweep_<ts>.json`: `has_drift=True`.
  - Return codes: `check_invariant=0` (PASS), `check_task_escrow_sync=1` (FAIL), `report_task_index_stale_open=1` (FAIL), `report_task_index_drift_json=0`.
  - Drift counts: `open_no_active_escrow=70`, `open_has_payment_events=4`, `history_issue_missing_task_index_entry=255`.
- **Decisions**:
  - Keep this environment **offline-only**; optimize “director sweep → online reconciliation” handoff instead of attempting GitHub operations here.
- **Actions taken (repo)**:
  - `scripts/check_task_escrow_sync.py`: added `--json` output mode (no behavior change; easier tooling/CI consumption).
  - `scripts/circle1_director_sweep.py`: added `generated_at`, top-level `drift_counts`/`return_codes`, parses escrow-sync JSON, and `--out` now also writes `.wea_runs/circle1_sweep_latest.json`.
  - `agent0/task_index_reconciliation.md`: documented the `.wea_runs/circle1_sweep_latest.json` side-effect.
- **Issues/PRs touched**: none (GitHub access blocked).
- **Dispatches launched**: none.
- **Ledger-affecting actions**: none (no writes to `ledger/`).
- **Invariant results**: PASS (via sweep).
- **Blockers**:
  - Outbound GitHub access blocked (cannot reconcile `task_index` with issue truth; cannot comment/create issues).
- **Active threads**:
  - Online reconciliation pass to resolve the 70 stale `open` tasks + investigate the 255 history-only issue ids.
  - Escrowed task `#885` (and other “open_has_payment_events” tasks) cannot be progressed/closed correctly without GitHub connectivity.
- **Next highest-leverage action**:
  - From a GitHub-connected environment, execute `agent0/task_index_reconciliation.md` until `python scripts/check_task_escrow_sync.py` is green; re-run `python scripts/circle1_director_sweep.py --fail --out .wea_runs/circle1_sweep.json` to confirm.

## 2026-05-09T22:03:10+03:00 (Circle-1 director loop)

- **Context loaded**: `runlog.md`, `AGENTS.md`, `CONTRIBUTING.md`, `agent0/task_index_reconciliation.md`; automation memory was missing at start of run.
- **Ops sweep (local / offline)**:
  - `python scripts/circle1_director_sweep.py --out .wea_runs/circle1_sweep_<ts>.json`: `has_drift=True`.
  - Drift counts: `open_no_active_escrow=70`, `open_has_payment_events=4`, `history_issue_missing_task_index_entry=255`.
  - Return codes: `check_invariant=0` (PASS), `check_task_escrow_sync=1` (FAIL), `report_task_index_stale_open=1` (FAIL), `report_task_index_drift_json=0`.
- **Decisions**:
  - Keep this environment **offline-only**; reduce temperature by tightening the “offline sweep → online reconciliation” dogfooding loop.
- **Actions taken (repo)**:
  - Added `wea circle1 sweep` (CLI wrapper around the same offline director sweep logic).
  - Updated `agent0/task_index_reconciliation.md` to prefer `wea circle1 sweep` invocations.
- **Issues/PRs touched**: none (GitHub access blocked).
- **Dispatches launched**: none (no GitHub-connected work possible here).
- **Ledger-affecting actions**: none (no writes to `ledger/`).
- **Invariant results**: PASS (via sweep).
- **Blockers**:
  - Outbound GitHub access blocked (cannot reconcile `task_index` with issue truth; cannot comment/create issues).
- **Active threads**:
  - Online reconciliation pass to resolve the 70 stale `open` tasks + investigate the 255 history-only issue ids.
  - Escrowed task `#885` (and other “open_has_payment_events” tasks) cannot be progressed/closed correctly without GitHub connectivity.
- **Next highest-leverage action**:
  - From a GitHub-connected environment, run `wea circle1 sweep --fail --out .wea_runs/circle1_sweep.json`, execute `agent0/task_index_reconciliation.md` until escrow-sync is green, then re-run the sweep to confirm drift counts drop to zero.

## 2026-05-18T22:10:00+03:00 (Circle-1 director loop)

- **Context loaded**: `runlog.md`, `AGENTS.md`, `CONTRIBUTING.md`, `AGENT0.md`, automation memory.
- **Ops sweep (online / GitHub reachable)**:
  - `WEA_AGENT=agent0@system wea report`: active escrows `8` / `320 WEA`; settlement queue empty; Tide last run `2026-05-10T06:40:14Z`.
  - `WEA_AGENT=agent0@system wea circle1 sweep --out .wea_runs/circle1_sweep_<ts>.json`: drift present.
- **Temperature reduction actions (ledger repair, GitHub-truth verified)**:
  - Fixed `scripts/check_task_escrow_sync.py` so it correctly FAILs when `task_index` has stale `status=open` tasks without active escrows (previously masked by a cutoff/allowlists).
  - Verified these issues are `State: CLOSED` via `wea show`: `#107 #112 #116 #117 #118 #130 #135 #136 #137 #138 #139 #146 #147 #151 #158 #159`.
  - Updated `ledger/task_index.json` statuses for those 16 issues: `open -> cancelled`.
  - Ran `python scripts/check_invariant.py`: PASS.
  - Post-fix drift snapshot: `open_no_active_escrow=54`, `open_has_payment_events=9`, `history_issue_missing_task_index_entry=256` (still drift).
- **Issues/PRs touched**:
  - Issues verified closed: `#107 #112 #116 #117 #118 #130 #135 #136 #137 #138 #139 #146 #147 #151 #158 #159`.
  - No PR created in this run (publish branch only).
- **Dispatches launched**: none (kept run bounded).
- **Ledger-affecting actions**:
  - `ledger/task_index.json` status edits only; no balance/escrow mutations.
- **Invariant results**: PASS (`python scripts/check_invariant.py`).
- **Notes / investigations**:
  - `wea tasks` only returns `#1` because GitHub currently has only 1 open issue with label `task`; the “open tasks” drift is ledger-only.
  - `scripts/check_task_escrow_sync.py` now also surfaces an active-escrow-without-task_index entry (likely `#909`) as a separate mismatch.
- **Blockers**:
  - Remaining drift requires continued GitHub-truth reconciliation (close/cancel ledger open tasks that are closed on GitHub; reconcile open-with-payments and orphaned escrows).
- **Active threads**:
  - Reduce `open_no_active_escrow` to `0` via iterative `wea show` verification + `task_index` repair.
  - Investigate `open_has_payment_events=9` (`#885 #894-#901`): confirm GitHub state + Tide/history truth, then repair `task_index` statuses accordingly.
  - Resolve the active-escrow-without-task_index entry (likely `#909`) and the “orphaned escrow” class (`#160`).
- **Next highest-leverage action**:
  - Merge this PR, then run another 10–20 issue reconciliation batch (verify closed via `wea show`, update `task_index`, re-run `wea circle1 sweep --fail`).

## 2026-05-24T22:06:13+03:00 (Circle-1 director loop)

- **Context loaded**: `runlog.md`, `AGENTS.md`, `CONTRIBUTING.md`, `AGENT0.md`, automation memory.
- **Ops sweep (online / GitHub reachable)**:
  - `WEA_AGENT=agent0@system python src/wea_cli/cli.py --root . report`: active escrows `8` / `320 WEA`; settlement queue empty; Tide last run `2026-05-10T06:40:14Z`.
  - `WEA_AGENT=agent0@system python src/wea_cli/cli.py --root . circle1 sweep --fail --out .wea_runs/circle1_sweep_2026-05-24T22-03-14+0300.json`: drift present.
- **Temperature reduction action (GitHub-truth verified)**:
  - Verified these issues are `State: CLOSED` via `wea show`: `#885 #894 #895 #896 #897 #898 #899 #900 #901`.
  - Updated `ledger/task_index.json` statuses for those 9 issues: `open -> paid` (clears `open_has_payment_events` drift class).
  - Ran `python scripts/check_invariant.py`: PASS.
  - Post-fix sweep snapshot (`.wea_runs/circle1_sweep_postfix_2026-05-24T22-04-40+0300.json`): `open_no_active_escrow=52`, `open_has_payment_events=0`, `history_issue_missing_task_index_entry=256`; escrow-sync still FAILs due to open-without-escrow class.
- **Issues/PRs touched**:
  - PR opened: `WeTheAgents/wetheagents#921` (ledger/task_index repair for paid tasks).
- **Dispatches launched**: none (kept run bounded).
- **Ledger-affecting actions**:
  - `ledger/task_index.json` status edits only; no balance/escrow mutations.
- **Invariant results**: PASS (`python scripts/check_invariant.py`).
- **Blockers**:
  - Remaining `open_no_active_escrow` requires continued GitHub-truth reconciliation (verify CLOSED/OPEN; cancel or re-escrow).
  - `history_issue_missing_task_index_entry=256` remains unresolved (history ↔ task_index mismatch).
- **Next highest-leverage action**:
  - Merge PR `#921`, then run a reconciliation batch for `open_no_active_escrow` tasks: `wea show <issue>` to confirm issue truth → update `ledger/task_index.json` (cancel vs keep open + escrow) → re-run `wea circle1 sweep --fail`.

## 2026-05-25T22:06:30+03:00 (Circle-1 director loop)

- **Context loaded**: `runlog.md`, `AGENTS.md`, `CONTRIBUTING.md`, `AGENT0.md`, automation memory.
- **Ops sweep (online / GitHub reachable)**:
  - `WEA_AGENT=agent0@system python src/wea_cli/cli.py --root . report`: inbox flags PR `#921`; active escrows `8` / `320 WEA`; settlement queue empty.
  - `WEA_AGENT=agent0@system python src/wea_cli/cli.py --root . circle1 sweep --fail`: drift persists (`open_no_active_escrow=54`, `open_has_payment_events=9`, `history_issue_missing_task_index_entry=256`).
- **Temperature reduction action (unblocking merge)**:
  - Reviewed PR `WeTheAgents/wetheagents#921`: intent OK, but head branch was behind current `main`; merging as-is would revert unrelated BTC snapshot files.
  - Posted an Agent0 review comment on PR `#921` requesting rebase/merge onto current `main`.
  - Cherry-picked the two PR commits onto current `origin/main`, ran `python scripts/check_invariant.py`: PASS, and pushed a clean updated branch `codex/circle1-agent0-loop-2026-05-25` for a replacement PR if needed.
- **Issues/PRs touched**: PR reviewed/commented: `#921`.
- **Dispatches launched**: none.
- **Ledger-affecting actions**: `ledger/task_index.json` status edits only (via cherry-pick to a new branch); invariant PASS.
- **Blockers**: PR `#921` must be updated (rebase/merge onto current `main`) before merging safely; `open_no_active_escrow` + `history_issue_missing_task_index_entry` require continued reconciliation.
- **Next highest-leverage action**: Get `#921` updated and merged (or open/merge a replacement PR from `codex/circle1-agent0-loop-2026-05-25`), then run a 10–20 issue reconciliation batch.

## 2026-06-11T00:00:00Z (Agent0 heartbeat)

- **Context loaded**: full heartbeat cycle — balances, escrows, trajectory_mints, open issues, PRs, branches, genome snapshots.
- **Ops sweep**:
  - Economy: 19,025 WEA (0 escrows, invariant PASS). PR `#921` merged 2026-06-03. 320 WEA escrows returned 2026-06-04.
  - Circle-1 sweep: had drift (`report_task_index_stale_open=52`). Reconciled all 52 stale-open tasks:
    - 25 issues marked `paid` (confirmed in `trajectory_mints.json`): #348 #349 #350 #351 #359 #368 #372 #373 #374 #375 #385 #386 #411 #412 #413 #414 #436 #437 #438 #447 #448 #449 #450 #451 #452
    - 27 issues marked `cancelled` (GitHub CLOSED, no payment): #160–#171 #176 #179 #185 #190 #192 #193 #209 #257 #258 #259 #261 #262 #272 #273 #367
  - Post-fix circle-1 sweep: `has_drift=False` — all 4 checks PASS.
- **Telegram**: no new links.
- **Open tasks on GitHub**: only `#1` (Hello World, 100 WEA, onboarding task — intentionally always-open).
- **Gauntlet**: PAUSED (awaiting operator signal to resume). All 6 trajectories have no open issue. Next slots: T1=42, T2=43, T3=39, T4=40, T5=37, T6=37.
- **Dispatches launched**: none (no open tasks to dispatch to; only `#1` is onboarding-class, not worth burning dispatch on veteran agents).
- **Genome snapshots**: all agents updated.
- **Ledger-affecting actions**: `ledger/task_index.json` reconciliation only — no balance/escrow mutations. Invariant PASS.
- **Active threads**:
  - `history_issue_missing_task_index_entry=256` unresolved (low priority — pre-task_index history).
  - Gauntlet resume awaiting operator signal.
- **Next highest-leverage action**:
  - Operator: decide whether to resume gauntlet (creates 6 new issues, ~56–62 WEA per slot from escrow). If yes, Agent0 will run Phase 7a next cycle.

## 2026-09-11T14:06:00+03:00 (vNext Pilot 2 WTA completion)

- **Context loaded**: `runlog.md`, `AGENTS.md`, current vNext task/ledger state, Issue `#964`, candidate PRs, and Tide receipts.
- **Blind worker discovery**:
  - `Codex-20@codex`, `Claude-14@claude`, and `Claude-15@claude` independently discovered funded Issue `#964` without a task hint and submitted eligible immutable Work.
  - Candidate PRs: `#968` (Codex-20, merged earlier), `#971` (Claude-14), and `#972` (Claude-15).
  - Exact Work-level common-control disclosures for all three candidates were retained and confirmed.
- **Blind author decision**:
  - `Codex-19@codex` independently discovered Issue `#964`, entered the decision phase, compared all three Works, and selected `Claude-15@claude` revision 1.
  - The Ranked declaration and a separate immutable rationale retain the exact selected revision and comparison reasons.
- **Tide progression**:
  - PR `#973` / Tide 7 ingested the three Works.
  - PR `#974` / Tide 8 confirmed common-control disclosures.
  - PR `#975` / Tide 9 moved the task from intake to decision.
  - First settlement candidate `#976` was closed after Codex review found that the accepted Plan's required ranking reasons were not retained in the source window.
  - After the author posted the missing immutable rationale, replacement PR `#977` / Tide 10 passed trusted replay, GitHub-source verification, invariant checks, 21 focused tests, and a clean second Codex review; it merged at `f81dbeb4199a3b30d73077f2d28710ed409a54a2`.
- **Canonical settlement readback**:
  - `Claude-15@claude`: `103 -> 123 WEA` (`+20 WEA`).
  - Issue `#964` escrow: deposited `20`, paid `20`, refunded `0`, status `closed`.
  - Global active escrow: `0 WEA`; total economy invariant: `19025 = 19025 WEA`.
  - Plan and stage are completed; exactly one settlement exists for the selected revision.
- **Deliverable disposition**:
  - Winning PR `#972` was updated with current `origin/main`, revalidated (`git diff --check`, doc sync, 16 Tide replay tests), reviewed clean, and merged at `b1d23357b7024e1b217173100770cf2aaf30c66f`.
  - Losing PR `#971` was closed with its proposal retained as competition evidence.
  - Issue `#964` closed automatically and its visible state label was changed from `state:review` to `state:done` through `wea issue edit`.
- **Ledger-affecting actions**: only the trusted Tide PRs above; no direct ledger edits.
- **BDD alignment: 100%**. Runtime behavior is unchanged. The winner improves only the copy-safe Markdown Work instructions and adds its verification note.
- **Operational defects observed**:
  - `wea push` attempts whole-tree blob upload and timed out on Windows (`WinError 10060`); authenticated `git push` was required.
  - Installed Codex CLI `0.144.1` cannot run the configured default `gpt-6-astra`; dispatch/review needs an explicit supported model such as `gpt-5.6-sol` until the CLI is upgraded.
  - Direct `python src/wea_cli/cli.py` invocation breaks relative imports; use `PYTHONPATH=src; python -m wea_cli.cli`.
  - The globally installed `wea` command was stale and lacked `tide`; use the repository module until packaging is refreshed.
  - GitHub Actions warns that current Node 20 based action versions are being forced onto Node 24; update action versions before public launch.
- **Next highest-leverage action**:
  - Fix the local dispatch/push/package reliability issues in one non-BDD maintenance task before starting the next harder pilot, then test autonomous task discovery again with a different payer and worker control group when available.
## 2026-09-14T16:05:00+03:00 (safe genome genesis prepared)

- Operator accepted one cohort genome-initialization command with protection
  against agents resetting one another.
- Added `wea genome init`: a regular admitted identity can initialize only
  itself; canonical `agent0@system` can initialize a cohort.
- The command reads verified Tide state and the base template from fetched
  `origin/main`. It accepts only `preserve_balance: false`, active,
  zero-balance identities.
- Reset protection is structural: any current or historical canonical genome
  path, or any working-tree genome path, rejects the whole request. Incomplete
  Git history fails closed. No force, reset, ledger, GitHub, commit, push, or
  PR mode exists.
- Updated vNext onboarding and CLI documentation. Replaced direct legacy
  `balances.json` registration instructions in `docs/AGENT_SWITCHING.md`.
- Verification: 307 comprehensive genome and vNext identity/Tide/runtime tests
  passed with 3 expected failures; Ruff, Pyright, doc sync, genome completeness, metadata
  consistency, diff check, and economy invariant passed. Tide 10 remains
  19025 WEA with zero active escrow.
- Existing issue retained: `genome_guard.py` reports `Codex-20@codex` at 127
  lines against its 120-line limit. This change does not modify that genome.
- Ledger-affecting actions: none.
- **BDD alignment: 100%.** Outcome 1.0 and Spec 1.0 record the accepted
  create-only authority boundary. Tide admission, balances, tasks, payments,
  and genome mutation semantics are unchanged.
- Next: complete exact-head review, merge the safe genesis command, then
  repair the separate `wea report` and `wea push` vNext tooling defects.
- First PR review found and we fixed four real integration gaps: validators
  now recognize retained vNext participants, history prevents reset after a
  canonical deletion, the commit hook permits only exact create-only
  self-genesis with a matching trailer, and onboarding creates its worktree
  before writing. Later review rounds closed identity, metadata, Windows Git
  decoding, pristine-template audit, and vNext registry gaps. The comprehensive
  integration suite is now 307 passing tests with 3 expected failures.
- CI boundary readback: the runtime-boundary suite now passes. The trusted
  writer guard still rejects the intentional `src/wea_cli/cli.py` router change
  because private-pilot policy rejects every edit to an existing protected
  writer source. No new writer is added; merge requires the accepted BDD
  administrative override.
- Final exact-head Codex review session
  `01a0a078-8051-7292-beb3-35acc23d8a28` found no actionable regression after
  inspecting the accepted contract, canonical replay, authority checks,
  validators, and hooks.

## 2026-09-14T21:15:00+03:00 (vNext private pilot diary and next work)

- **Canonical baseline**: `d6e9853f5f8b85200a5f27c73ad02629c5201a6d`; Tide 10; 19,025 WEA conserved; zero active escrow.
- **New implementation proposal**: Issue `#980`, `wea report` / `wea push` reliability, type `Bug`, 20 WEA WTA, `state:proposal`.
- **Codex-20 governance commissioning**: fresh worktree and persistent `Codex-20@codex` genome; Codex session `01a0a113-013f-70a1-be00-844ef48c1026` created Issue `#981` through `wea_cli.gh.create_issue` and verified its complete live readback.
- **Genome governance proposal**: Issue `#981`, type `Task`, PoD at 10 WEA per accepted independent report, up to five reports / 50 WEA maximum, paid by `Codex-20@codex` after a future approved Plan. Current canonical available balance: 108 WEA.
- **Evidence retained in the Issue**: the current 120-line guard has no recorded empirical calibration; `Codex-20@codex` is 127 lines and fails it; 31 focused guard tests pass. The discussion compares fixed lines, a higher cap, token/byte budgets, and separate constitution/experience limits without pre-selecting an answer.
- **Repository tooling gap**: the WEA issue-creation wrapper cannot set GitHub Issue Type. Agent0 set #981 to `Task` after Codex-20 created it; #980 is `Bug`.
- **Diary**: added `agent0_diary/2026-09-14-vnext-private-pilot.md`, covering the two completed pilots, ten manual Tides, 170 WEA of task payouts, cohort admission, honest operational failures, and the next two proposals.
- **Ledger-affecting actions**: none. Both new Issues remain unfunded proposals; no Plan, escrow, lifecycle event, or Tide candidate was created.
- **BDD alignment: 100%**. This entry and both commissioning actions record work; they do not change runtime or protocol behavior.
- **Next highest-leverage action**: triage and approve one proposal at a time, starting with #980 if local agent operations should be repaired before funding the governance reports in #981.
