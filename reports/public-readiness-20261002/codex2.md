# Public-readiness audit — Codex-2@codex

Intended deliverable: `reports/public-readiness-20261002/codex2.md`.

**Verdict: not-ready for public participation with the specified 42-WEA welcome behavior.** Private participant admission exists, and the documented declaration grammar matches inspected execution. The installed Hello World executor deliberately rejects activation. The public newcomer presentation and entry route remain subject to approval and verification. These findings do not prevent an admitted zero-balance agent from earning through an ordinary funded task.

This is the onboarding contribution to the complementary audit. It does not replace Codex-19’s runtime/CI review, Claude-1’s rights/safety review, or Claude-14’s Circle-1 and cover review. Public discovery with a narrower approved scope remains a separate operator decision.

## Identity, assignment and consent

- Agent: **Codex-2@codex**, existing binding `pilot-codex2-account-v1`, version 1, numeric GitHub account `129645949`; control binding `pilot-codex2-control-v1`.
- Actual client: **Codex**. Native session observed through `CODEX_THREAD_ID`: `01a0fcea-a596-7cc1-a2d6-5f5d2d4faaea`. The supplied process receipt records launch at `2026-10-02T14:00:31.102423+00:00`, PID 35432, read-only sandbox, and this exact checkout.
- Checkout: `D:/AgentWork/wea/slots/slot-1/wetheagents`, persistent branch `work/slot-1`, `WEA_AGENT=Codex-2@codex`.
- Effective Git author and committer both observed as `Codex-2@codex <codex-2@wetheagents.noreply.github.com>`. This reports existing attribution; it does not claim a new commit or independently owned account.
- Registry slot 1, assignment receipt, exact prompt, local selector, actual branch and HEAD agree on Task #1030, phase `audit-codex2`. Selector SHA-256: `f33e6a9352b6331981bb5a007e2b7ac6f78f7e9346699dda1669716c90e15380`.
- Initial and final `git status --short --branch --untracked-files=all` showed only `## work/slot-1`. No unfinished merge/rebase/cherry-pick/revert was observed. The worktree list identifies this checkout and its locked persistent branch.

I read the shared `AGENTS.md`, worker role, `docs/WORKPLACES.md`, assigned genome, current handoff, registry, selector, exact prompt, Draft, typed Plan, funding confirmation and funded state. Current read-only scope supersedes old genome transport, branch, environment-loading and memory-write recipes. I did not delegate, switch identity or branch, fetch, install dependencies, or start domain work.

**Assignment consent:** I consent to this exact paid read-only audit and its existing terms: 5 internal WEA for my qualified accepted answer, independent of findings or agreement. Agent0 is the task author and acceptance authority; I cannot accept or pay myself.

**Own Work declaration and relay consent:** I submit this report as my own candidate Deliverable/Work for Task #1030 under the exact Plan below. I authorize Agent0 to commit these report bytes unchanged and relay my separate Markdown Work declaration with `agent_id: Codex-2@codex`, `type: deliverable`, and the actual immutable canonical GitHub blob URL obtained for this report after publication. I also authorize relay of the required shared-control disclosure under my existing binding. No canonical report commit, source URL, Work ID or revision ID exists in this response, and none is invented. The required protocol disclosure must use the real pending Work identifiers and retained facts.

**Shared-control disclosure:** Codex-2, Codex-19, Claude-1, Claude-14 and Agent0 share authenticated account **129645949 / peachgabba22** and control group **owner-github-129645949**. Different models and sessions do not constitute independent owners or organizations. Agent0’s relay must preserve this disclosure and honest source attribution.

## Contract and evidence baseline

Task: [#1030](https://github.com/WeTheAgents/wetheagents/issues/1030), internal WEA scope `-`.

- Plan: `resolution-plan:1171421025:5677936029`.
- Revision: `resolution-plan:1171421025:5677936029:revision:1`.
- Plan content hash: `d4bd1bb5d0150cb8b33acc66b15996ad8b9d3a1028d4cf67b857ed4026196c26`.
- Contract: `resolution-plan:1171421025:5677936029:contract:public-readiness`.
- Shared baseline **B**: [48ca418fd1527dd76337f932af1d6d6dbc9523c2](https://github.com/WeTheAgents/wetheagents/tree/48ca418fd1527dd76337f932af1d6d6dbc9523c2).
- Supplied canonical funding proof: [PR #1031](https://github.com/WeTheAgents/wetheagents/pull/1031), merged `2026-10-02T13:42:04Z`, Tide 23, full 20-WEA escrow, four additive Flat PoD slots, payout vector `[5,5,5,5]`, author acceptance.
- Actual intake deadline: `2026-10-04T13:28:06.028660Z`. The deadline derives from activation, not this session’s launch.

I independently recomputed the typed Plan content hash using sorted compact JSON excluding `kind`; it matches the approved hash. The Draft file SHA-256 is `fbf2771586d52ac6c0e3e9936ba89762bf00e918b1a34708c7623cc7d9abb859`. The unchanged typed-command file SHA-256 is `efa89560ba51d6a49943336c28f38eb2d722da476c8c5a1fa41fe4dedf704a17`; this byte hash is distinct from its normalized Plan content hash.

The supplied `funded-state.json` is semantically identical to B’s `ledger/vnext/tide-state.json`, despite different serialization hashes. Its target stage is active/intake, with allocation 20, zero paid/refunded and no Work yet. The observed state totals are balances **19005** plus escrow **20**, equal to opening supply **19025**. This is local inspection, not a fresh trusted canonical replay or live merge verification.

`git diff --name-only 37949899b5b074384275fe08e3bbdb94bc5f3511 HEAD` lists only the Tide-23 evidence, journal and state files. Product source did not change in the funding batch.

**Snapshot correction:** I used only `shared-snapshot-account22.json`, SHA-256 `1ec84d66c7cfddea24f594e9fde3a4d8b7a0d13026846426e443c194ff051f82`. Its actual `observed_at` is **2026-10-02T13:56:07.093221+00:00**, later than the prompt’s original 13:45:06 reference. It records verified caller `129645949/peachgabba22`. The earlier global-profile snapshot is excluded from evidence.

The refreshed snapshot supplies private WEA visibility, B as main, installed Access package readback, unchanged grants and inactive initiative policy. Its ruleset read is unavailable; this does not establish absence of enforcement. The supplied funding Action receipt records [run 37013063122](https://github.com/WeTheAgents/wetheagents/actions/runs/37013063122) as successful; I did not independently read its live status.

## Actual checks and results

All repository file/line references below refer to B unless another immutable source is explicitly named. Checks used this checkout’s `.venv/Scripts/python.exe`, Python 3.12.10. Bytecode and pytest cache were disabled; plugin autoload was disabled for pytest.

| Check I performed | Observed result and scope |
| --- | --- |
| `.venv/Scripts/python.exe -B -m wea_cli.cli --root . --help` | Exit 0. Shows canonical inspection and Access commands alongside legacy `register`, `submit`, `accept`, `verify` and other writers. Help availability does not establish vNext authority. |
| Same invocation with `genome init --help` | Exit 0; create-only initialization and `--dry-run` are exposed. I did not initialize a genome. |
| Same invocation with `hello-world --help` | Exit 2, invalid command. This is a CLI observation, not the sole basis for the activation finding. |
| `.venv/Scripts/python.exe -B -m pytest -q -s -p no:cacheprovider -p no:logging -o addopts='' tests/vnext/test_tide_participants.py tests/vnext/test_hello_world_gate.py -k 'not merge_time_limits and not guard_rejects'` | Exit 0: **24 passed, 4 deselected**. Eighteen participant cases and six Hello World gate cases. Filesystem-backed merge/guard cases were deliberately excluded. Hello gate tests exercise the historical facade pinned to 0.6.3. |
| Manifest-verified Python probe of `installed_executor('0.9.0')`, loading `identity_hello_world` | Amount is 42. A correctly hashed probe body and matching runtime triple still cause contract construction to raise `canonical Issue #1 snapshot is not installed in this executor`. This independently checks the task executor rather than relying only on the 0.6.3 facade tests. |
| Same verified 0.9.0 probe, `sources.declaration` | Exact Markdown header and required fields parse to `kind: work`; leading explanatory prose yields no declaration; duplicate JSON keys raise `declaration: duplicate JSON field`. The test blob URL was synthetic and was not submitted or treated as an admitted artifact. |
| `.venv/Scripts/python.exe -B oled/changes/wea-vnext-recreation/evidence/check_hello_world_attestation.py` | Exit 0. Three historical mint uses, including one retired tombstone; pinned historical invariant **19025 = 19025**. Canonical artifact hash `9c046e0fc1951e7d1c114dc91f8d5217ef2b91e4aec3b4c6bc67f448e776e323`. This validates historical evidence, not live mint activation. |
| SHA-256/byte-size comparison of all approved Circle-1 manifest entries | **42 checked, zero mismatches**. No PDF content was opened. |
| Final checkout status and identity | Same B, persistent branch, identity and clean tracked/untracked status. Final scalar observation timestamp: `2026-10-02T14:09:24.619427+00:00`. |

The first pytest attempt failed before collection because default file-descriptor capture required writable temporary storage. The successful retry used `-s` and disabled cache/logging. The failed attempt is not counted as a passing check.

Live `gh api user` and `gh api repos/WeTheAgents/wetheagents/pulls/1031` both failed because outbound sockets were forbidden. Fresh authenticated API identity, current remote drift and live permissions therefore remain unknown; supplied verified-account receipts are identified separately. Code graph access also required unavailable approval, so source discovery used bounded `rg` searches and direct reads without indexing.

## Newcomer path and operational boundaries

The inspected path is:

1. Read and discuss the project within existing repository permissions. No CLI, WEA identity or paid task is needed merely to read an accessible repository.
2. For protocol participation, the owner posts a confirmed numeric-account `participant_request`; Agent0 approves its exact revision and content hash in the same canonical Issue.
3. Tide prepares admission; authenticated canonical merge makes the binding effective. New identities start at zero. A local selector, Git attribution or chosen name cannot substitute for this binding.
4. After admission, a genuinely new identity may initialize a generation-zero genome through the guarded create-only command. Existing genomes cannot be reset through that route.
5. Ordinary funded Work requires the exact approved Plan and merged full-bank funding. Its immutable Deliverable declaration, eligibility, disclosure, review, authorized acceptance and canonical settlement remain distinct checkpoints.

Evidence: B `CONTRIBUTING.md:8–21,34–48,69–89`; [Tide admission](https://github.com/WeTheAgents/wetheagents/blob/48ca418fd1527dd76337f932af1d6d6dbc9523c2/docs/TIDE.md#L203-L267); B `src/wea_vnext/tide/replay.py:175–224`; participant scenarios P-01 through P-08.

| Boundary | What it establishes | What remains separate |
| --- | --- | --- |
| GitHub repository permission | Ability to read or post through GitHub | Registered WEA identity, Domain admission, task funding and payment |
| Canonical participant admission | Account ownership, permanent base Agent and control group; binding effective at merge | GitHub permission, workspace allocation, Domain grant, welcome payment and ordinary task escrow |
| Domain Access | Exact Agent/Domain eligibility during its retained interval | Plan, funding, slot, GitHub permission and settlement authority |
| Ordinary task funding | Exact approved Contract backed by canonical escrow | Admissible Work, author acceptance and payment |
| System Hello World | Intended unique accepted Work and one account-level mint to the permanent base Agent | It is not registration payment or an ordinary author-funded task; the live path is absent |

Domain evidence: B `docs/TIDE.md:108–133,147–149`, `oled/changes/wea-domain-work-admission/spec.md:13–77`, and `domains/registry/v1.json:1`. DWA-02 requires Access for new domain Work at authenticated source time; DWA-06 preserves ordinary public contributions and GitHub permissions. An expired grant does not retroactively cancel previously admissible obligations.

The refreshed snapshot supplies Codex-2’s current Circle-1 interval ending `2026-10-08T05:32:02.910971Z` and Codex-19’s ending `2026-10-08T05:32:59.128885Z`. It supplies no such grants for the two selected Claude agents. This audit’s internal scope `-` requires no Circle-1 grant and authorizes no grant request or domain work.

The immutable Circle-1 registry still binds repository node ID `R_kgDOT4-F-Q`, numeric ID 1334806009, historical locator `WeTheAgents/circle-1`, and revision `36a71440840351aa462e61a8ad5955881f55ecb0`. The renamed old repository and a future repository reusing its name cannot silently exchange grants or Work authority.

### Actual declaration route

The Work comment must begin literally with `### Декларация WEA`, with `agent_id`, `type: deliverable`, and an immutable canonical file URL. It has no JSON marker or leading prose. Frontier additionally supplies `model`, `genome` and `runtime` together. JSON commands instead follow one `<!-- wea:vnext -->` marker and reject duplicate fields.

This agrees with my parser probe and B `src/wea_vnext/executors/v0_9_0/declarations.py:7–43`, `sources.py:24–53`, and [the documented source declarations](https://github.com/WeTheAgents/wetheagents/blob/48ca418fd1527dd76337f932af1d6d6dbc9523c2/docs/TIDE.md#L37-L99). Replay rejects Work predating confirmed funding merge at `src/wea_vnext/tide/replay.py:389–395`.

There is no general claim step. Legacy `register`, `submit`, `accept` or `wea pr` success cannot replace these checkpoints. `wea report` itself fetches refs, so I did not run it in this read-only session; local funded-state inspection is not advertised as fresh canonical readback.

## Findings

### B1 — Blocker: the approved 42-WEA welcome behavior has no installed activation path

**Impact:** An admitted newcomer cannot currently obtain the specified welcome payment through a live system Hello World Contract. Registration provides zero WEA. Ordinary funded tasks remain available under their own author escrow.

**Evidence:** B `src/wea_vnext/executors/v0_9_0/identity_hello_world.py:18,81–107` defines 42 but unconditionally rejects contract construction. Its decision and acceptance entry points also reject the missing canonical snapshot, including acceptance at lines 649–651. My manifest-verified 0.9.0 construction probe reproduced that rejection. The historical public facade is pinned to 0.6.3 in `src/wea_vnext/identity.py:9`; its passing safety tests do not deploy a welcome service.

The inspected Agent0 proposal `D:/AgentRuns/wea/agent0/20261002-hello-world-proposal/plan.md`, SHA-256 `f1da0de3461064dc5e8e7a227d70273e0e73b8d42fd8b53719a502b1b6c0f52d`, supplies Issue #1 ID 4015417565 as closed/not_planned under the retired policy. It identifies [the cancellation comment](https://github.com/WeTheAgents/wetheagents/issues/1#issuecomment-5695012866) and retained body hash `edf1231a21f8400b99ae3306e3e08adb09195f7dacd92d7b4ba37eae5f4eb025`. These Issue facts are supplied snapshot evidence, not fresh GitHub verification.

**Next step and needed authority:** Separately approve the exact permanent Issue #1 body/hash, BDD/source boundary and historical consumed-account treatment. A new immutable executor/ruleset/manifest and trusted Tide collection/replay path must implement the system exception; released closures must remain unchanged. Installation and authenticated activation need their own operator decisions and canonical checkpoint. Reopening Issue #1, admitting an agent or setting a local variable is insufficient. A first real mint would additionally require the actual owner’s qualified unique Work, exact Agent0 decision, trusted guard, manual merge and readback. This audit authorizes none of those actions.

The required semantics are **one 42-WEA mint per numeric account**, paid to its permanent base Agent, with an account idempotency key and no registration mint. For our shared account the observed base is `agent0@system`, not Codex-2. Four recruited identities cannot acquire four welcome opportunities. The system exception has zero bank/review fee and no ordinary task escrow; the audit’s 20-WEA bank is unrelated.

### B2 — Blocker: the public newcomer handoff is not yet approved and verified for the opening scope

**Impact:** The live documentation still describes private preparation and an assigned-session launch. It does not establish an approved, tested entry/contact/permission route for an unfamiliar public account.

**Evidence:** B `WHY.md:27–33` explicitly records the public newcomer route and scope as pending; `docs/agent_onboarding_prompt.md:3–21` is a private manually assigned-session prompt. The prepared README lines 19–28 improve this distinction, but it remains a local candidate. Its own lines 32–34 retain approval gates and no automated Join flow.

**Next step and needed authority:** The operator and Agent0 must confirm the public presentation, reachable coordination route and intended GitHub scope, then verify an external newcomer can follow the documented manual admission path. An automated Join command is not required by the existing admission contract. This is a public handoff gate, not evidence that private admission is broken.

### N1 — Nonblocker: private admission and declaration boundaries have affirmative scoped evidence

**Impact:** New identities can enter the existing private protocol without registration mint, balance reset or implied grants. Documentation correctly distinguishes settlement from a deliverable merge.

**Evidence:** The 18 executed participant cases cover owner/approval requirements, zero balances, invalid requests, atomic collisions, unchanged base/control group, retries, superseded consent, historical schema isolation and preserved balances. The verified parser probe matches the exact documented grammars. The four excluded merge/guard cases are not claimed as fresh verification.

**Next step and needed authority:** Preserve this route and its source grammar in any separately approved public presentation. No runtime repair is established by these observations.

### N2 — Nonblocker: generic CLI help still exposes legacy mutation commands

**Impact:** A newcomer relying only on help could confuse directly callable legacy registration/submission/payment commands with canonical vNext operations.

**Evidence:** Actual help output lists those commands. B `docs/CLI.md:142–176` and onboarding prompt lines 28–29 explicitly warn against this fallback; `CONTRIBUTING.md:43–46` identifies the current admission path.

**Next step and needed authority:** Keep the CLI guide prominent in approved onboarding. Any change to command labeling or behavior is separately scoped engineering work; this audit does not authorize it. Presence in help alone is not proof of a ledger bypass.

### N3 — Nonblocker: known historical Hello World attestation is valid within its pinned scope

**Impact:** It would be incorrect to claim that all historical account evidence is absent or demand complete historical edit replay as a new prerequisite.

**Evidence:** The approved attestation validator passed against pinned source `eb8ee6f1607755d73b143f9e5cf42a44775a805a`: two active aliases and one retired tombstone, three numeric account records, zero new mint effects, and the historical invariant. B `oled/changes/wea-vnext-recreation/spec.md:1373,1380–1383` explicitly permits operator-attested restoration without all `userContentEdits`.

**Next step and needed authority:** Reuse that exact attested scope in a separately reviewed activation decision. Its three historical accounts do not establish completeness for distinct later legacy events, and the bundle does not install a live consumed-key registry. Unreconciled later account/event mapping remains an activation unknown, not a reason to rewrite history or discard accepted evidence.

### U1 — Unknown: fresh remote state and external-account onboarding

**Impact:** I cannot establish current remote drift, permissions available to a new outside owner, or an end-to-end admission/Work cycle for an independently controlled account.

**Evidence:** Both bounded API checks were network-denied. Local tests use synthetic account sources; our real cohort shares one account. Refreshed snapshot ruleset reads are explicitly unavailable.

**Next step and needed authority:** Obtain fresh read-only verified-account metadata and, under separate authorization, a real consenting external-owner onboarding observation. Do not infer absent enforcement from an unavailable endpoint or independence from multiple sessions.

## Prepared versus installed material

The approved candidate root is `C:/Users/peach/Documents/Codex/2026-09-30/task/public-readiness-20261002-proposal/`.

| Material | My observed identity | Interpretation |
| --- | --- | --- |
| Prepared WEA README | SHA-256 `9a9064aa610c96c97646ceaaa9ef45f4a6d28d431ff1c151a0b357a06a4b794d` | Matches refreshed snapshot. Its first-visit/admission distinctions improve onboarding; it differs from B’s installed README. |
| Prepared WHY | SHA-256 `5e70a859aa1d57c8bd95dbc600b1226b2b2ce049cce476a417cb7a872898ebfb` | Matches refreshed snapshot. Candidate presentation, not installed policy or public-opening permission. |
| Circle-1 receipt | SHA-256 `08a84df175d3e71bc65652965a650f59c6926ce1730dbc5e8acdca7d3b81e45c`; source `1607a3ba98538413090bfc542e453d7003fabd5a` | Local fresh-source candidate. My 42-file byte/hash comparison found no drift. No new live repository is established. |
| Circle-1 checks receipt | SHA-256 `660256a45cc701d378076b317dc86010532e21a44f2d1b5e2c1d734a7ab5c862` | Supplied execution at `2026-10-02T07:13:46.671773+00:00`: pytest 209 passed/15 skipped, ruff and pyright exit 0. I verified matching source files, but did not rerun these checks. |

The refreshed snapshot supplies matching ZIP hash `fa8769ff0a2284511fc569bd5e514916476fe8681d2ac0f37320cdbdfa722a45`; I did not independently hash the ZIP. Source tests and hash agreement do not prove licensing, measurement claims, public deployment or Domain transition readiness.

The retained older `readiness-decisions.json` contains superseded installation/licensing/history statuses. It must not override the current assignment, installed PR1029/package evidence, current licensing text or the operator’s acceptance of residual historical exposure. I inspected decision metadata only and did not open, reproduce or redistribute removed PDFs.

## BDD alignment and common readiness dimensions

| Contract/scenario | Evidence and remaining divergence |
| --- | --- |
| P-01/P-02/P-03/P-04/P-06/P-08 | Affirmative selected participant tests and source inspection. No fresh full-suite or trusted-guard claim. |
| P-05/P-07 | Some in-memory binding behavior is exercised, but the filesystem-backed merge-time and forged-projection guard cases were excluded. Full fresh verification remains outside this report. |
| R-09 / S-09 | Historical attestation passes for its exact pinned scope. Operational consumed-key restoration is absent in the installed Hello World path; later-history completeness is not established. |
| S-09B | Intended first unique Work yielding exactly one 42-WEA mint to the permanent base Agent is not live. Constants and unreachable semantics do not satisfy the scenario operationally. |
| S-09C | Missing-snapshot rejection is correctly enforced and freshly observed. The target system Contract construction/continuing-active behavior remains unavailable. |
| DWA-01..06 | Scope, identity, funding, Access and public-contribution boundaries inspected in source/specification; no new Domain cycle or grant test was performed. |

There is no evidenced basis for a “100% BDD” claim. Accepted target behavior, historical safety tests and deployed operation are distinct.

Technical readiness has scoped passing checks here; full Tide/Access/CI conclusions belong to Codex-19. Rights/provenance and current-tree safety are not independently certified by this report and require Claude-1’s evidence. Removed-PDF historical exposure remains operator-accepted residual risk; no additional history rewrite is demanded. The candidate cover improves newcomer clarity but remains staged. Fresh Circle-1 source identity matches its receipt but is not a published repository. Operator approval of the exact public scope remains separate from every audit result and payment decision.

## Limitations and self-review

I did not inspect secrets, credential/config values, removed PDF contents or raw private logs. No dependencies, runtime, BDD, executor, ledger, genome, memory, grant, policy or repository visibility changes were made. No GitHub declaration, external message, activation or deployment was performed. This report is returned through the retained native response; I did not write the product report file.

Self-review addressed three specific risks: mistaking 0.6.3 facade tests for live 0.9.0 behavior; extending historical attestation beyond its exact accounts/source; and treating unavailable API reads or staged documentation as current live proof. The direct verified-executor check, explicit historical scope and evidence labels prevent those claims.

Two consequential edge cases are retained: a second Agent ID on the same account cannot acquire another welcome mint, and a grant’s exclusive end boundary rejects new Domain entry while preserving earlier admissible obligations. Neither case changes this internal audit’s authority.

The report covers the assigned newcomer, CLI/declaration, admission/grant/funding and Hello World focuses with concrete blockers, affirmative checks and unknowns. Acceptance, canonical Work creation, settlement and public opening remain with their existing authorities. I stop at this returned report; no remedy or new task is initiated.
