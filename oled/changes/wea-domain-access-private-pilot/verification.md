# Domain / Access readiness evidence

## Current implementation checkpoint — 2026-09-18

**Not ready** for the full live pilot: manual code merge, exact activation,
real grants and canonical #997 funding remain outstanding. Implementation is
authorized by the operator's latest instruction and bound to accepted
Outcome/Spec/Design/Tasks 0.5. The earlier preparation checkpoints below retain
their original dates and are superseded only where explicitly stated here.

### Fresh implementation evidence

- `tests/vnext/test_access_runtime.py`: 41 passed after review fixes. Synthetic
  clocks and GitHub API fixtures; this is not real seven-day travel.
- Combined Access/library/boundary/Tide/CLI/parser compatibility run: 423 passed,
  exit 0, 115.76 seconds. Exact command/output retained locally in
  `.wea_runs/access-implementation/tests.txt`.
- Release lifecycle, Ranked progression/settlement and Triage/Release: 10 passed,
  exit 0; `.wea_runs/access-implementation/release-ranked.txt`.
- Real authenticated source CLI read returned `disabled`, as required without
  genesis. No Access comment, branch, grant or funding was published by that read.
- Current account verified as `peachgabba22`, numeric `129645949`; work remains
  in the dedicated `codex/domain-access-private-pilot-20260916` worktree.

| Accepted scenario | Implemented proving hook | Remaining live proof |
| --- | --- | --- |
| DA-01 | Both issuer branches; account, role, subject, binding version, registration and two-time authority failures; REST/GraphQL capture agreement | Real declaration and authority readback |
| DA-02 | Concurrent append loser revalidates; fixed seven-day interval and exact endpoint; publication-before-success | Real workflow publication permissions and grants |
| DA-03 | Lost commit/comment responses, identical retry, changed payload in fresh CLI process, no double grant | Real retry/readback after activation |
| DA-04 | Retained source replay, tamper rejection, receipt failure/corruption repair, malformed-source isolation and capacity preservation | Independent real clone/process read |
| DA-05 | Before/at endpoint tests, no expiry mutation | Actual post-endpoint observation |
| DA-06 | Pending/rejected/active/expired decisions, edited-source visibility, explicit unavailable on failure | Two fresh real grant reads |
| DA-07 | API write destinations, workflow permissions and unchanged library/executor/Tide tests | Verify live journal and financial state remain separate |
| DA-08 | Disabled state, exact committed-code activation fixture, lost activation response, untrusted ref rejection, old-source cutoff | Manual merge and exact operator activation |
| ST-01 | Prior operator appointment retained; no Steward issuer kind | Publish retained handoff link with pilot |
| C1-P01 / C1-P02 | Existing #997 preparation sources and unchanged Ranked/Release checks | Both live grants, funding, workers, selection, settlement and actual reflections |

### Independent review

Fresh-context reviewer `/root/access_implementation_review` inspected the whole
artifact under OLED Verify. Five findings were confirmed and fixed:

1. Malformed nested JSON and invalid Unicode could poison reconciliation:
   strict input validation now retains rejection; following requests still run.
2. Fresh CLI retries could reuse a UUID with a changed payload: full payload
   comparison now rejects this, including without the local request file.
3. The writer could exceed the reader's capacity: publication now stops before
   overflow and leaves accepted history readable.
4. Edited-source rejections lost their request selector: safe parsed selectors
   now remain visible without treating them as authority or a validated key.
5. Corrupted Bot receipts suppressed repair: exact expected body and workflow
   author are checked, and replacement does not create another grant.

Each finding has a regression in `test_access_runtime.py`. Post-PR
`codex exec review` and remote checks remain required before code-merge readiness.

PR [#999](https://github.com/WeTheAgents/wetheagents/pull/999) was published as
protocol maintenance, not #997 Work. Its first native review found one further
pagination boundary: 20 full comment pages need a 21st completion request.
The handler and CLI now share that bound. The regression proves readback and
receipt repair at exactly 2000 comments. Fresh Access/runtime-boundary checks:
53 passed, exit 0 (42 adapter plus 11 boundary), 17.65 seconds.

CI also found the required Git blob SHA-1 operation. It now carries the same
narrow documented Semgrep exception as Tide's Git object verification; all
source and protocol security hashes remain SHA-256. The scan must rerun.
The trusted ledger guard rejects `candidate writer universe changed:
.github/workflows/access.yml`. This is the established code-installation
checkpoint, described in the accepted Tide Design: old trusted code cannot
approve its own writer-boundary expansion. Preserve the failed status and
obtain a one-time operator decision for this exact PR after review. There is
no waiver of later ledger validation and no change to the guard itself.

Subsequent boundary verification showed that the existing guard discovered the
new workflow but did not automatically pin the Access Python handler. The
candidate now extends the guard's protected file list to the Access workflow,
library, adapter, GitHub handler and CLI. It preserves every existing protected
file and does not modify released executors. This supersedes the preceding
"no change to the guard itself" statement: protection is extended, never weakened.
Five parameterized regressions require rejection of edits to these exact files.
An initial probe incorrectly passed `HEAD` where a full SHA was required;
the corrected probe exposed this real missing protection before activation.

The second native review found that rejected comments could exhaust the
500-decision capacity. The final policy limits actual grants instead: rejected
and duplicate sources remain retained without consuming grant capacity, and
the reader has no artificial decision-count limit. A regression proves that
multiple wrong-account sources do not prevent a later valid grant. No external
grant or financial state changed while resolving these findings.

### Scope, recovery and lean cut

Three new Python modules (about 1,100 production lines), one workflow, one
focused test module, CLI routing, boundary tests and operating documentation.
The estimate remains within Design's 800–1200 line range; there is no new
dependency, task executor change, financial writer or scheduler. The accepted
cut removes a redundant record hash chain and a generic version/migration
engine. Protocol reads use one standard-library Git archive rather than one
process per file. Recovery is append/readback only. Capacity is explicit.

Actual test failures were fixed: pagination query construction; incomplete
synthetic identity/Bot fixtures; a closure hash test ran while files changed
and was rerun against a stable fixture with repository line-ending rules.
The pre-existing pytest-asyncio fixture-scope deprecation warning remains.
No failed check is represented as green. Main-worktree local edits are excluded.

## Earlier preparation verification checkpoint — 2026-09-18

**Not ready** for a live pilot or activation. Preparation checks are complete; missing implementation and live evidence are not waived.
Outcome, Spec, Design, and Tasks remain revision 0.4. This check changes no accepted protocol behavior or published #997 Plan.
The operator requested completion of checks; that instruction did not separately approve implementation or activation.

### Contract and authority

The authorized work is read-only verification and correction of the review package.
Preserve private WEA, manual code/financial merges, immutable executors, source dates, identities, and historical ledger bytes.
The same dedicated branch remains at fetched `origin/main` `f40bf1d980fe6bf622ebc00552b8230f474356f7`.
Numeric account `129645949`, private WEA, exact external repository ID/revision, and all three published Triage/Plan bodies were rechecked at `2026-09-18T16:24:27.224004Z`.
The Draft hash remains unchanged. Agent0, Codex-2 and Codex-19 retain the named version-1 canonical bindings.
No `author_plan_decision` was present in #997. Canonical readback remains Tide 12, Agent0 8070 WEA, with no funded #997 runtime.

### Scenario coverage

| Scenario | Evidence actually available | Result and missing evidence |
| --- | --- | --- |
| R-11 / S-11A / S-11B library | 28 passing registry/Access tests; exact test names below | Library verified; synthetic time, caller-supplied verified authority |
| DA-01 | Library tests exercise operator/Agent0 and invalid authority; canonical source identities checked | Handler account/role/recipient adapter absent; not verified end to end |
| DA-02 | `test_s_11a_authorized_source_grants_exactly_seven_days`, `test_s_11a_one_agent_cannot_hold_overlapping_access_across_domains` | Duration, cross-domain overlap and boundary replacement verified in memory; durable publication and race tests absent |
| DA-03 | `test_s_11a_grant_replay_is_exact_and_conflicting_reuse_is_rejected` | Pure idempotency verified; network retries and source retention absent |
| DA-04 | Registry hash/tampering and state validation tests pass | No Access journal, crash recovery, or independent remote reconstruction yet |
| DA-05 | `test_s_11b_access_expires_only_at_the_exact_boundary_and_replays`, immediate-before/at assertions in S-11A | Boundary arithmetic verified with synthetic `NOW=2026-08-15T12:00:00Z`; no live CLI expiry or actual seven-day observation |
| DA-06 | Source CLI rejects `access` as an unknown command, exit 2, as expected for the current code | Readback command absent; no stale result is reported as live evidence |
| DA-07 | `test_access_has_no_revoke_extend_permission_work_or_money_surface`, 100 existing Tide/Ranked/Release/boundary tests; invariant passes | Existing library/task isolation verified; future handler side effects remain untested |
| DA-08 | Existing runtime-boundary test passes; current boundary calls Access inactive | New disabled handler, activation receipt and fresh-source cutoff tests absent |
| ST-01 | Operator appointment, Agent0 acknowledgement, local handoff, #997/completion attribution | Manual responsibility verified; no automated Steward authority mechanism is claimed |
| C1-P01 | Exact Domain/registration preparation exists | No request, grant, interval, independent grant reads, or real expiry observation |
| C1-P02 | Actual Triage/Plan chain accepted by retained read-only Tide replay; unchanged sources verified again | Funding, active grants, competing Work, selection, payment and both Release records remain pending |

The retained `2026-09-18T14:21:25.982107Z` source replay is not relabeled as a new capture.
Its exact source bodies and unchanged runtime base were checked again; all five preparation sources had accepted dispositions and no money movement.

### Fresh commands and evidence

All commands ran in the dedicated pilot worktree. Source CLI commands used `PYTHONPATH=src`.

| Command or check | Exit / result | Retained evidence |
| --- | --- | --- |
| `git fetch origin` | 0; main/HEAD unchanged | Exact SHA above |
| `python -m pytest tests/vnext/test_domain_registry.py tests/vnext/test_access.py -q` | 0; 28 passed | `domain-access.txt` |
| `python -m pytest tests/vnext/test_tide_replay.py tests/vnext/test_tide_participants.py tests/vnext/test_tide_ledger.py tests/vnext/test_tide_collection.py tests/vnext/test_tide_activation.py tests/vnext/test_runtime_boundary.py tests/vnext/test_release_lifecycle.py tests/vnext/test_current_bdd_triage_release.py tests/vnext/test_current_bdd_ranked_settlement.py tests/vnext/test_current_bdd_ranked_progression.py -q` | 0; 100 passed | `tide-ranked-release.txt` |
| `python -m pytest tests/test_pipeline_parser.py tests/test_normalized_change.py tests/test_rubric_scoring.py tests/test_verify_loop.py tests/test_scripts_role_grammar.py -q` | 0; 206 passed | `parser-consumers.txt` |
| `python scripts/check_invariant.py` | 0; 19025 WEA balances + escrow, zero active escrow | `invariant.txt` |
| `python -m wea_cli.cli tide --ref origin/main --agent agent0@system` | 0; Tide 12, available 8070 | `canonical-tide.json` |
| `python -m wea_cli.cli access --help` | Expected rejection, exit 2; `access` absent | `access-cli-absence.json`; observation assertion exited 0 |
| GitHub identity/repository/commit/Issue readback | 0; all assertions passed | `github-readback.json` |

Files in this table are under ignored `.wea_runs/checks-final-20260918/`; they are inspection receipts, not canonical events.
Fresh total: **334 tests passed**. Existing pytest-asyncio configuration deprecation is a warning; no relevant test failed or was waived.
The source-call search still finds Access operations only inside `src/wea_vnext/domain_access.py`.

After the consistency corrections, `python scripts/check_doc_sync.py` and `git diff --check` passed again.
HTML checks verified all eight embedded source hashes, unique IDs, resolved internal links, and 11 BDD summaries.
Desktop 1440x1080 and mobile 390x844 passed, including all source documents expanded; no page overflow, script errors, or network requests occurred.
The first browser interaction attempt timed out because the test selected a link inside a closed source disclosure. Opening the source disclosure before clicking corrected the test procedure; the complete rerun passed without changing product behavior.
The [verification checkpoint in #997](https://github.com/WeTheAgents/wetheagents/issues/997#issuecomment-5733109755) was published at `2026-09-18T16:38:12Z` and read back exactly. It contains no protocol command marker and grants no authority or funding.

Platform documentation was rechecked: [default-branch Issue-comment workflow behavior](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#issue_comment) and [non-forced Git ref updates](https://docs.github.com/en/rest/git/refs#update-a-reference).
These are platform capabilities, not deployed-handler evidence or proof of branch-scoped credential restrictions.

### Independent review and scope

A fresh-context reviewer, `/root/verify_access_package`, examined the whole proposal against source and retained evidence under the OLED verification review procedure.
Result: **no actionable findings**. Review was read-only, with no competing Work or new paid identity.
Self-review corrected stale one-visitor/first-trip handoff wording and clarified that the parser snapshot changes in funded #997, not in the Access implementation.
These are consistency corrections to the existing scope; reward, Plan hash, grant rules, and BDD behavior did not change.

| Entry | Classification | Action |
| --- | --- | --- |
| `AGENT0.md`, `runlog.md`, `oled/changes/wea-domain-access-private-pilot/` | Intended retained proposal, appointment and handoff | Keep only this task's documentation changes |
| `.wea_runs/` receipts, generator, screenshots and local pinned scanner checkout | Generated local inspection material | Keep ignored; no claim of canonical state |
| Main checkout local changes and other task worktrees | Unrelated | Preserved; no reset, cleanup or publication |
| Production/runtime, workflows, ledger, genomes and scanner/profile files | Protected | No changes |

### Task completion and protected lean cut

Preparation and its applicable checks are complete. The unchecked implementation, activation, funding, Work, settlement, Release and real-expiry tasks remain required and unwaived.
No applied runtime cut is possible: there is no runtime candidate yet. The documentation pass removed stale current-state claims and retained original dated evidence separately.
Removing authority, replay, retry, receipt, or real-time evidence requirements would weaken the requested contract; those proposed checks remain.
Do not run a competing parser repair merely to complete verification before funding.

### Remaining gaps and next step

The next decision is the already-pending separate agreement for the concrete Access mechanism under point 4 of the original request.
After that: implement and review, separately activate the exact code/configuration, grant both Access rights, fund through Tide and manual merge, then execute #997.
After the actual result and settlement, retain both competitors' real Release records on their applicable canonical/operational bases.
Real expiry observation must wait for the actual seven-day endpoints. No synthetic test or repeated preparation check can replace these missing events.

## Historical verification — retained with original dates

The original readiness evidence below was observed on 2026-09-16 UTC.
Proposal revision 0.2 on 2026-09-18 subsequently replaced the operating design; later checkpoints are retained below.
These historical sections do not change the current 0.4 verification status above.

## Reproducible state

- WEA base: `f40bf1d980fe6bf622ebc00552b8230f474356f7`, fetched on 2026-09-16.
- Worktree: `D:/GitHub/wetheagents-domain-access-pilot-20260916`.
- Branch: `codex/domain-access-private-pilot-20260916`.
- Main checkout contains pre-existing genome, slang, runlog, and untracked changes. None was copied, staged, or modified for this task.
- `gh api user`: `peachgabba22`, numeric ID `129645949`, node ID `U_kgDOB7o9fQ`.
- Canonical WEA is private. `gh repo view` returns node ID `R_kgDORdJ3YQ`.
- Canonical bootstrap retains Agent0 account binding `pilot-agent0-account-v1` and role binding `pilot-agent0-role-v1`, both version 1.
- Both bindings start at `2026-09-09T11:26:29Z`, have no end, and bind numeric account `129645949` to `agent0@system`.
- Codex-19 retains `pilot-codex19-account-v1` and the same control group. Its account is not a substitute for a session assignment.
- No Agent0-specific genome exists under `genomes/` in this canonical tree. `AGENT0.md` supplies the assigned coordinator mission; no replacement genome was invented.

## Readiness matrix and source anchors

| Surface | Fact and evidence | Operational gap |
| --- | --- | --- |
| Domain registry | `domains/registry/v1.json`; hashes verified by existing tests | None for this pinned record |
| External repository | GitHub API and cloned `origin/main` both match `36a71440840351aa462e61a8ad5955881f55ecb0`; ID `R_kgDOT4-F-Q` | None for public readable scanner/canon. No GitHub write permission is inferred. |
| Dates | External commit time is `2026-08-15T05:19:27Z`; verification occurred 2026-09-16 | Old commit date is not an Access start |
| Core behavior | `domain_access.py`: `VerifiedAccessAuthority`, `DomainAccessState`, `grant_access`, `expire_access`, `is_access_active` | Caller supplies authority objects; no authenticated loader or recipient registration check. Unique binding IDs require explicit source-witness mapping for repeated use of one role. |
| Declaration intake | `tide/replay.py` handles participant/task commands; source search finds no Domain/Access caller outside the library | No operational Access declaration adapter |
| Persistence | `DomainAccessState` contains immutable Python tuples; canonical Tide state keys contain no Access section | No serialization, durable Access journal/projection, or restart/recovery path |
| CLI | `src/wea_cli/cli.py::cmd_domains/cmd_assign` use `ledger/domains.json` and legacy history | Legacy assignments are not Access. No current canonical Access readback command. |
| Expiry | Existing boundary tests pass | No live evaluation/publication integration or real observation |
| Work | `docs/TIDE.md`, pinned task runtime, `tide/github.py` artifact capture | Access supplies no Work eligibility. External immutable artifacts need a supported adapter. |
| Current boundary | `docs/VNEXT_BOUNDARY.md`; recreation Design D-50/D-51 | Explicitly inactive control plane. A live extension requires agreement. |

Search command: `rg -n 'domain_access|grant_access|expire_access|is_access_active' src scripts .github`.
Matches occur only in `src/wea_vnext/domain_access.py`. Test imports are separate evidence of library use.
No actual Access was issued, persisted, or expired in this session.

## Fresh commands and results

| Command or inspection | Result |
| --- | --- |
| `git fetch origin` | Exit 0; base above |
| `gh api user`, `gh repo view WeTheAgents/wetheagents --json nameWithOwner,isPrivate,id,defaultBranchRef` | Exit 0; identities and privacy above |
| `gh repo view WeTheAgents/circle-1 --json nameWithOwner,id,isPrivate,defaultBranchRef` | Exit 0; public external repo with expected node ID |
| `gh api repos/WeTheAgents/circle-1/commits/36a71440840351aa462e61a8ad5955881f55ecb0` | Exit 0; exact commit and original date |
| `python -m pytest tests/vnext/test_domain_registry.py tests/vnext/test_access.py -q` | Exit 0; **28 passed** |
| `python -m wea_cli.cli tide --ref origin/main --issue 980 --agent agent0@system` with `PYTHONPATH=src` | Exit 0; canonical replay, completed Plan, deposited 20 / paid 20 / refunded 0 / closed escrow |
| Canonical `ledger/vnext/tide-state.json` after replay | Tide 12, cutoff `2026-09-16T04:26:41.507172Z`, escrow 0, supply 19025, Agent0 8070, Codex-19 1422 |
| Pinned external Circle-1 scanner preflight below | Exit 0; scripts 157/158, `src_wea_cli` 24/27 |

Existing tests cover malformed registry bytes/hashes, typed authority, exact intervals, cross-domain overlap, replay conflicts, late expiry, and forbidden side effects.
Their synthetic `NOW` is `2026-08-15T12:00:00Z`. It is test input, not a real session start.
The pytest environment emitted an existing asyncio fixture-scope deprecation warning. No test failed.

## Scanner preflight

The scanner checkout is the exact Domain revision under `.wea_runs/circle1-source`.
It is an ignored, read-only investigation copy, not a dispatched worker worktree.
With `PYTHONPATH=.wea_runs/circle1-source/src`, the retained command is:

```text
python -m circle1.score_repo --root . --profile domains/circle-1/zone_templates --target wea --scan-date 2026-09-16 --repo-sha f40bf1d980fe6bf622ebc00552b8230f474356f7 --out .wea_runs/circle1-preflight-pinned.json
```

This is readiness reconnaissance. It is not a worker deliverable or proof of Access.
The only scripts defect is `scripts/pipeline_parser.py`, with path mutation and import side-effect reasons.
Source lines 12-15 corroborate the path mutation.
`tests/test_scripts_role_grammar.py::test_pipeline_parser_is_unclassified` retains the current debt expectation within its test class.

Profile SHA-256 values:

| File | Hash |
| --- | --- |
| `scripts.json` | `9a970068cbdd2c78add3114316a238db5dcf8b9328479497510ce6654f1233ac` |
| `scripts_v1_roles.json` | `3bd2e1373d677c8b80d8346ae4f4e983480ee6a876bca623c88ac0d4bb754585` |
| `src_wea_cli.json` | `63a42d5906bba79ba600c16eb9c3380860844a2f97a3a16cbef0166f6e721c80` |

The first scanner invocation omitted `--repo-sha`, so its output contained an empty revision.
That incomplete receipt is retained as `.wea_runs/circle1-preflight.json` and is not the pinned baseline.
The command above corrected the invocation without changing scanner code or source dates.
Canonical replay receipt: `.wea_runs/tide980-readback.json`.

## Errors and limits

- Initial inspection of the dirty main checkout encountered inaccessible old pytest temporary directories. The fresh task worktree avoids them.
- The expected Agent0 genome path was absent. Source inventory confirms no such tracked genome; no identity was inferred from a substitute.
- Some PowerShell `rg` probes used nonexistent paths or shell-style globs. Scoped source reads corrected the discovery probes.
- Large early CLI output was not a durable receipt. The successful read-only command was rerun into the retained local JSON file.
- No external write, payment, Issue creation, PR creation, worker launch, or automation change was attempted.

## Historical review of proposal 0.1 (2026-09-16)

BDD alignment: **100% for unchanged live behavior**, scoped to this documentation-only preparation.
S-11A/S-11B retain passing library evidence. Operational coverage for DA-01..DA-08 and C1-P01 is missing and non-effective.
No full-system live-readiness or completed-pilot claim is made.

Simple English self-check: complete in pragmatic mode. Draft normative sentences stay within 25 words and contain no banned modal verbs.
Independent fresh-context proposal review: complete. Two substantive issues were resolved in this proposal:

1. Reused canonical role binding IDs cannot represent multiple declaration revisions in `DomainAccessState`.
   The reviewer reproduced duplicate-binding and missing-binding failures with a read-only probe.
   Design now specifies retained per-source witnesses and separate original role evidence. The reviewer confirmed that this resolves the failure.
2. An Access-containing batch can also cross a task deadline. Requiring unchanged money/task state would suppress legitimate maintenance.
   DA-04 and Design now compare against replay with the same predecessor, cutoff, and non-Access sources.
   Existing maintenance continues. A paired deadline-crossing integration case is required before activation.

Both findings are fixed in draft text. The future integration checks remain unimplemented, not passed.
Documentation checks: `python scripts/check_doc_sync.py`, `git diff --check`, and local Markdown link checks pass.
Scope: six proposal documents plus this session's appended `runlog.md` section. No production code or accepted contract changed.
Ignored local evidence includes the pinned scanner clone, readback JSON, scan receipts, and pytest caches.
The reviewed 0.1 proposal reused Tide and bundled an unpaid task. That operating design was superseded on 2026-09-18.
Its independent review does not establish correctness of revision 0.2.

## Revision 0.2 correction, 2026-09-18

The operator selected WEA CLI, retained GitHub transparency, rejected per-Access PR/merge, and put the trip first.
The original design overextended the financial batch merge requirement to Access; that was an Agent0 proposal error.
The original phrase "no authenticated GitHub source" was ambiguous:
the missing component is an adapter that verifies the author and authority of a grant declaration.
It did not mean that the Domain repository or pinned revision lacked verified GitHub evidence.

Outcome/Spec/Design/pilot/tasks now describe CLI intake, a trusted Access handler, a private Git journal, and Issue receipts.
The journal publisher and acceptance clock are proposed details, not operator-approved infrastructure.
The current proposal removes per-Access merge, Tide schema 3, and useful-code-work requirements from Stage 1.
Manual code review/merge and financial rules remain separate.

A new `git fetch origin` completed with exit 0 on 2026-09-18.
Origin/main remains `f40bf1d980fe6bf622ebc00552b8230f474356f7`.
Identity, external repository, economy, scanner results, and 28 library tests retain their 2026-09-16 evidence date.
No later account, repository, balance, or elapsed-time verification is inferred from the fetch.
The new operational scenarios remain unimplemented and untested.
The earlier role-witness finding still applies; financial maintenance remains outside the proposed Access handler.

One oversized Windows shell command failed before process creation with error 206; it wrote nothing.
Smaller document-only writes succeeded. No runtime source, workflow, accepted boundary, GitHub state, or ledger was changed.

## Documentation and HTML checks, 2026-09-18

- `python scripts/check_doc_sync.py`: exit 0, PASS.
- `git diff --check`: exit 0; only the existing CRLF normalization warning for runlog was printed.
- HTML: 14 internal links resolve; six source documents and nine BDD summaries are embedded; IDs are unique; no remote assets load.
- Headless Chromium: 1440x1080 and 390x844 render without overflow or JavaScript errors; BDD and source-link disclosures work.
- Both viewport screenshots were visually inspected. Images remain in `.wea_runs/html-preview/*-v02.png`.
- The ignored `.wea_runs/render_access_review_v02.py` generates the artifact from current source documents; it is not production code.
- Independent review of revision 0.2 completed with one authority finding, resolved below. The 0.1 review was not reused as a pass.

## Independent review of revision 0.2

Finding P2: numeric account plus a caller-selected Agent0 binding does not authenticate the originating local session.
The bootstrap binds Agent0 and several other agents to account `129645949`; a holder of those credentials can select the valid role.
The current identity implementation resolves account, subject, and time, not an independent session capability.
Verified anchors: `ledger/vnext/tide-bootstrap.json` and `src/wea_vnext/executors/v0_9_0/identity.py`.

Resolution: fixed the claim and made the trust limitation explicit in Outcome, Spec, Design, pilot, and HTML.
The proposed private pilot trusts credential holders to select roles canonically bound to that account.
Receipts separate authenticated account from declared agent attribution. No shared-credential session-isolation claim remains.
Independent session capabilities or credentials are outside this proposed pilot; adding them would require a separately agreed scope.
This documents a proposed trust ceiling for operator review, not a new permission grant or completed authority implementation.

## Steward addition, revision 0.3, 2026-09-18

The operator requested a Steward for Circle-1. No Agent ID or appointment terms were supplied.
The historical source `oled/changes/wea-vnext-recreation/sources/WEA_RESTART_HANDOFF_2026-07-14.md:80` requires a Steward in intent.
That source leaves the detailed role open; line 161 also leaves powers and succession open.
Current R-11/S-11A/S-11B and `domain_access.py` do not implement a Steward appointment or new issuer type.
The pinned external README corroborates scanner/canon ownership and target-profile separation.
These sources do not establish an appointed Circle-1 Steward.

Added `steward.md` and revised Outcome/Spec/Design/pilot/tasks to 0.3.
Proposed remit: Domain direction/state, useful backlog, orientation, technical recommendations, and handoff.
ST-01 states appointment and Access are independent; C1-P01 includes the first Steward handoff.
Manual operator appointment and acknowledgement are proposed; exact Agent ID and terms remain pending.
The role adds no Access authority, permanent right, financial acceptance, payment, GitHub permissions, or new Work admission rule.
The immutable Domain registry is unchanged. The earlier review remains evidence for 0.2, not a completed operational check of stewardship.

A fresh fetch left origin/main at `f40bf1d980fe6bf622ebc00552b8230f474356f7`.
Memory lookup for stewardship returned no relevant entry; no memory-derived role or appointment was used.
No runtime implementation, external comment, Access, appointment, dispatch, or automation was performed.

Revision 0.3 document checks: doc sync and diff whitespace pass. HTML embeds seven current source documents and ten BDD summaries.
All 19 internal links resolve; desktop/mobile layouts and the Steward source disclosure pass without JavaScript errors.
Screenshots were visually inspected and remain ignored under `.wea_runs/html-preview/steward-*-v03.png`.

## Operator appointment of Agent0, 2026-09-18

After the initial Steward proposal, the operator explicitly appointed Agent0 in this conversation. Agent0 accepted the responsibility.
The earlier unassigned status above records the preceding checkpoint and is now superseded.
Checked `AGENT0.md` and current R-11/S-11A/S-11B: no Agent0/Steward incompatibility was found.
Agent0's existing mission already includes Domain coordination, agent orientation, and Circle-1 dogfooding.
The accepted assignment uses the existing `agent0@system` identity; it creates no new agent or runtime role mechanism.

Updated `AGENT0.md`, the proposal documents, and HTML to retain the appointment and initial Domain handoff.
The source is the operator's local session instruction, not a fabricated GitHub comment or authenticated GitHub role event.
No GitHub appointment message was published; later pilot publication can link the retained record without asking for appointment again.
Access implementation/activation approval is still separate. DA-01..08 and the live C1-P01 path remain unimplemented.
ST-01 now has actual manual appointment and acknowledgement evidence, not proof of a new runtime role system.
No Work, payment, permissions, worker loop, or Access was created.

## Two-worker WTA cycle preparation, revision 0.4, 2026-09-18

The operator requested two trips, a simple task for two agents, WTA, result, and Release.
This expands the earlier trip-only checkpoint. The actual cycle plan is retained in `cycle.md`.

Fresh checks:

- `git fetch origin`: exit 0; origin/main still `f40bf1d980fe6bf622ebc00552b8230f474356f7`.
- `gh api user`: account `129645949`, login `peachgabba22`; canonical WEA remains private, node ID `R_kgDORdJ3YQ`.
- Canonical Tide replay: sequence 12, Agent0 available 8070 WEA. Local receipt `.wea_runs/circle1-wta-preflight.json`.
- Exact five task consumer suites: 206 passed, exit 0; existing asyncio fixture deprecation warning only.
- Pinned scanner on clean target f40bf1d, actual scan date 2026-09-18: scripts 157/158, only `scripts/pipeline_parser.py` unclassified; src_wea_cli 24/27.
- Scanner receipt: `.wea_runs/circle1-wta/baseline-20260918.json`. This is preflight, not competing Work.

Actual external preparation:

- Private Type Task [#997](https://github.com/WeTheAgents/wetheagents/issues/997) created at `2026-09-18T14:02:28Z`.
- Draft hash: `c1fdb68204003ab92b3764e137b4e8ef925157ad0a4826e0b0ee7ee7e267a6d6`.
- Agent0 assigned Codex-19 unpaid pre-funding Triage in comment `5731120925`, at `2026-09-18T14:03:38Z`.
- Codex-19 completed Triage in its own worktree/branch and consented to relay of the exact updated assessment and Plan.
- Assessment, completion, and proposed Plan were posted in order as comments `5731343103`, `5731343901`, and `5731344778` at `2026-09-18T14:20:01Z`, `14:20:05Z`, and `14:20:09Z`. Each body and account was checked by exact readback. Draft body/hash remained unchanged.
- Proposed Plan content SHA-256 excluding `kind`: `e84a1fc5f1dec212fe8cb7c9718c50fef1288c215a850e23c1a22e5500fcef61`. This is not author approval or canonical funding.
- Triage clarified fresh-process import proof, both existing import forms, recruitment rather than a runtime whitelist, waiting for both results or withdrawal before early birdie, and the separate operational Release basis for the unselected worker.
- Paid competitor roster: Codex-2 and Codex-19; proposed Ranked payout `[10]`, no extra reward, disclosed shared control.
- Two prepared worker prompts are gated on actual grant and canonical funding receipts; neither paid worker was dispatched.

Existing Tide collection/replay also checked the real published sources in a local read-only preview, cutoff `2026-09-18T14:21:25.982107Z`.
All five #997 sources were accepted: Draft, assignment, assessment, completion, and Plan revision.
Balances and funding batches remained unchanged; #997 has no activated task runtime.
This preview did not publish a Tide, write canonical ledger files, or establish funding.
Receipts: `.wea_runs/circle1-wta/preparation-{collection,preview,preview-summary}.json`.

HTML 0.4 validation: eight current embedded document hashes, 11 BDD summaries, 24 valid internal links, unique IDs.
Headless Chromium at 1440x1080 and 390x844 showed no page overflow, script errors, or network requests; source-link opening and BDD disclosure worked.
`python scripts/check_doc_sync.py` and `git diff --check` passed. Screenshots are retained under `.wea_runs/html-preview/`.

The separate agreement question for Access implementation 0.3 is pending under point 4 of the original task.
No elapsed wait is interpreted as approval. Access implementation, activation, grants, canonical task escrow, Work, selection, settlement, and Release remain uncompleted.
The observed account and baseline dates above do not alter older source timestamps.
A Windows `rg` shell-glob probe returned error 123; the direct Issue-template file read succeeded. No source or runtime was changed by that failed probe.
One local preparation command omitted `PYTHONPATH=src` and failed before writes with `ModuleNotFoundError`; the explicit source invocation then passed.

## Next checkpoint

Actual Triage and proposed Plan publication for #997 are complete; author approval is pending until Access is ready.
Steward selection is complete: `agent0@system`.
Resolve the pending separate agreement on Access implementation; then implement/review and obtain the concrete activation decision.
Only active grants plus canonical task funding permit the paid two-worker launch. Preserve the existing manual merge boundaries.
Continue through actual comparison, settlement, and Release. Leave real expiry observation pending until it occurs.
