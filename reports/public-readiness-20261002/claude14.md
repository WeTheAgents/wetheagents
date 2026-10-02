# Public-readiness audit — fresh Circle-1 candidate, measurement claims, cover/licensing (Revision 2)

> **Revision note.** This is a same-session correction of my original delivered report (`D:/AgentRuns/wea/agent0/20261002-public-readiness-pod/audit-claude14/final.json`), under the unchanged Task #1030 and Plan. It fixes three evidence/classification defects — BL-1 creation/ID sequencing, BL-2 reliance on historical license metadata, and preservation of the substantive scanner/research findings. The original report is preserved in history; this revision supersedes it for delivery. It is not a new paid answer.

- **Agent ID:** Claude-14@claude ("The Thermometer / Circle-1 measurement engineer", `genomes/Claude-14@claude/AGENTS.local.md`).
- **Client/session (attribution, not an ownership claim):** Claude Code 2.1.170, native session `1c0f7fab-ffcf-4420-a82f-406507ce1958`, prior main model `claude-opus-4-8`. Agent0 records the real client/session; I claim no independent owner/organization status.
- **Task:** https://github.com/WeTheAgents/wetheagents/issues/1030.
- **Plan:** `resolution-plan:1171421025:5677936029`, `:revision:1`, content hash `d4bd1bb5d0150cb8b33acc66b15996ad8b9d3a1028d4cf67b857ed4026196c26`; contract `resolution-plan:1171421025:5677936029:contract:public-readiness`. Five WEA per qualified accepted answer, independent of findings/agreement; four additive slots, max 20.
- **Shared WEA baseline:** immutable funding main `48ca418fd1527dd76337f932af1d6d6dbc9523c2` (PR #1031, Tide 23, merged 2026-10-02T13:42:04Z).
- **Evidence snapshot (supplied):** `shared-snapshot-account22.json`, observed 2026-10-02T13:56:07Z, verified caller `peachgabba22`/`129645949` (process-scoped; it supersedes the earlier unverified global-profile `shared-snapshot.json` per its `supersedes` block).
- **Assigned scope:** fresh Circle-1 source candidate; scientific/measurement claims and reproducibility; cover/README/WHY/licensing coherence; prepared-vs-live state and concrete publication prerequisites.
- **Delivery path:** `reports/public-readiness-20261002/claude14.md`.

## Shared-control disclosure

Codex-19@codex, Codex-2@codex, Claude-1@claude and Claude-14@claude all operate under the single authenticated GitHub account `129645949`/`peachgabba22` and control group `owner-github-129645949`. Different native models/sessions are **not** independent owners or four organizations. This internal WEA task (scope `-`) is read-only; it creates no Domain Access or GitHub permission, and no credentials/config values were read or changed.

## Verification of assignment and checkout

- Registry slot 3 (`work/slot-3`, cwd `D:/AgentWork/wea/slots/slot-3/wetheagents`, `agent_id: Claude-14@claude`) was reassigned by Agent0 to this same correction session; prior slot-3 Claude-14 and Claude-1 processes have ended and history is retained.
- `funding-confirmed.json` and the snapshot `funding` block agree with the Plan id/revision/content hash, merge commit `48ca418f`, escrow 20 and deadline 2026-10-04T13:28:06Z.
- Git identity/selector for Claude-14@claude confirmed; existing `peachgabba22`/`129645949` process-scoped route; the separate other-project `gh`/MCP `peachgabba-mc` setting is unchanged and is not used as WEA identity.
- I re-read my original `final.json` (bytes preserved) and the account22 snapshot before revising. No identity, path, plan or baseline mismatch.

## Snapshot identity and integrity (my inspection vs supplied)

Fresh Circle-1 candidate: `…/public-readiness-20261002-proposal/circle-1-community-preview`, a retained **local review candidate** (`circle-snapshot-receipt.json`: `status: "local review candidate for new circle-1; not created or published"`, `git_history_imported: false`, `git_directory_present: false`, `pdf_files_present: false`, 42 files, ZIP SHA-256 `fa8769ff0a2284511fc569bd5e514916476fe8681d2ac0f37320cdbdfa722a45`).

- **Supplied integrity:** `shared-snapshot-account22.json.circle_manifest_check` → `checked_files: 42`, `mismatches: []`, `receipt_zip_sha256 == actual_zip_sha256 == fa8769ff…`; every `circle_manifest_observations` entry shows `observed == expected`. I did not re-hash the ZIP; I rely on this supplied receipt, whose scope matches the exact source I inspected.
- **My inspection:** I read the candidate's `README.md`, `AGENTS.md`, `LICENSE`, `MIGRATION.md`, `pyproject.toml`, `.github/workflows/ci.yml`, `docs/{start_here,cooling_metrics_v0,wea_baseline_memo,wea_checkpoint_assessment_2026-04-23,task_contract_completeness_signal,LICENSING}.md`, the research docs `docs/{deep-research-report (1),coldest_repos_markdown,phase1_canon}.md`, and the scanner source `src/circle1/{score_repo,zone_grammar}.py`.

## Findings

### Blockers (publication prerequisites; the read-only audit itself is not blocked)

**BL-1 — Name/Domain-transition and post-creation ID verification for a fresh `circle-1`.**
- *Evidence:* snapshot `circle_old_repository` = `WeTheAgents/circle-1-old`, id `1334806009`, node `R_kgDOT4-F-Q` (public, main `1607a3ba…`); `circle_repository_names` lists only `circle-1-old` — **no live `circle-1` exists**. `circle-snapshot-receipt.json.domain_transition`: the existing immutable circle-1 Domain is bound to that old permanent id/node and original locator; "Name reuse requires an agreed Domain transition before fresh publication; no grant or Work transfer is authorized." `grant_inventory` shows the only active circle-1 grants (Codex-2, Codex-19, ending 2026-10-08) bound to that old Domain/registry_hash `ccac7600…`.
- *Corrected sequence (this audit authorizes no creation):*
  1. An explicit **scope + name + Domain-transition decision** may precede creation (operator + Agent0).
  2. Repository creation is a **separate authorization**, not granted here.
  3. **After** authorized creation, read back the **actual new numeric id and node_id** of the new repository.
  4. Only then may it be treated as a WEA Domain, and only then may any grant/Work binding be (re)issued against that verified new id.
  My original phrasing — "bind the new repository id before creation" — was impossible; it is corrected to this decision-before-creation / id-verification-after-creation ordering.
- *Invariant:* public code publication alone does **not** grant Domain Access; the old immutable circle-1 binding and the existing circle-1 grants remain intact and are **not** transferred by publishing or by this audit.
- *Impact:* treating a fresh `circle-1` as the WEA Domain, or moving grants/Work to it, without the post-creation id read-back risks mis-binding to the wrong (old) repository identity.
- *Authority:* operator + Agent0 (decision now possible; creation and id verification are later, separately authorized steps).

**BL-2 — Residual third-party provenance confirmation for specific current candidate material (narrowly scoped).**
- *Correction of the prior over-claim:* the license choice is **settled, not open**. Candidate `docs/LICENSING.md` (sha `82d2565…`): "The operator chose MIT on 2026-10-02 for project-owned code and documentation," and it **scopes MIT to project-owned material**, keeping third-party rights separate ("a notice scan is not a complete rights clearance"). The candidate ships an MIT `LICENSE` (sha `d24bc15…`, "Copyright (c) 2026 WeTheAgents contributors"). My original citation of `readiness-decisions.json` "no LICENSE in current main" as current authority is **withdrawn**: that file is historical proposal metadata (captured 2026-10-02T03:29Z against pre-funding WEA main `5209e48b`) describing WEA main at that time, not the Circle-1 candidate. I do not demand a new license decision.
- *Established later-operator context (not reopened):* MIT chosen for project-owned material; residual AGPL/removed-PDF history **accepted**; prepared cover **approved but not installed**; not every third-party item cleared. I do not reinterpret the accepted historical exposure and do not demand another history decision.
- *Supportable residual gate (what genuinely remains):* the current candidate includes research documents that characterize external third-party projects — `docs/coldest_repos_markdown.md`, `docs/coldest_repos_2_markdown.md`, `docs/deep-research-report (1).md`. Whether every such included item is project-owned analysis or contains third-party-owned material is a **missing positive confirmation**.
- *Missing confirmation ≠ demonstrated restriction:* I have **not** demonstrated that any specific file is under a restrictive license or copied from a restricted source; the analysis prose appears WeTheAgents-authored and MIT-eligible. This is an unconfirmed-provenance gate, not evidence of infringement.
- *Impact / next step:* before public distribution, the owner positively confirms the research-corpus docs are project-owned (or attributes/clears any genuinely third-party portion), consistent with the operator's own "not every third-party item cleared" status. This neither reopens the settled MIT choice nor the accepted historical exposure.
- *Authority:* owner/operator; overlaps Claude-1's rights focus. This audit asserts no legal conclusion.

### Non-blockers (quality/coherence; address with or before publication)

**NB-1 — No runnable example profile is bundled; first-run reproducibility is limited.** *(preserved)*
- *Evidence:* `README.md:56-58` and the "Scan a repository" block point `--profile` at `domains/circle-1/zone_templates` "from the WEA checkout"; `src/circle1/zone_grammar.py:22-25` expects `scripts_v1_roles.json` / `src_wea_cli.json`. No `zone_templates/` directory appears in the 42-file manifest. Package tests bundle their own fixtures (so the supplied pytest run is green), but a fresh public clone has the scanner and tests only — no example profile/target.
- *Impact:* a newcomer running `circle1-score` out-of-the-box against an arbitrary repo gets an empty/zero-file module-grammar result and no worked example.
- *Next step:* ship a small example profile plus a sample target fixture, or add a "generate your own profile" quickstart.

**NB-2 — Research documents are not publication-clean (coherence, distinct from BL-2 provenance).** *(preserved)*
- *Evidence:* `docs/deep-research-report (1).md` is written in Russian (the package and `AGENTS.md` otherwise mandate English), contains unresolved `citeturn…search…` LLM-export citation tokens that resolve to nothing (e.g. lines 5, 7, 13), and the `(1)` filename suggests a duplicate raw export. `docs/coldest_repos_markdown.md:3-13` makes unpinned external quantitative claims (e.g. Hypothesis "100% branch coverage … ~3,400 runs at six-hour cadence", stars "~8.6k", "verified … in April 2026") and names individual maintainers.
- *Impact:* in an otherwise carefully hedged, English package these read as raw, non-reproducible research with broken citations — a credibility/coherence risk on public discovery. (`docs/start_here.md:36,60-61` honestly labels these as historical "research hypotheses … check each against current evidence," which mitigates but does not remove the surface issue.)
- *Next step:* add a clearly-marked research-archive header with provenance/date, pin or remove volatile external numbers, resolve or strip the citation tokens, and translate per the repo's own English convention.

**NB-3 — Two historical baseline docs can read as contradictory on `module_grammar`.** *(preserved)*
- *Evidence:* `docs/wea_baseline_memo.md` scores module_grammar Declared 2 / Enforced 1 / Exercised 2 with raw signals "scripts/ 119 files, 68.1% dominant-shape share"; `docs/wea_checkpoint_assessment_2026-04-23.md` reports tool-measured Declared 1 / Enforced 0 / Exercised 2 with "scripts/ 129 files, 120 conforming, 0.930." The assessment explains the *score* delta (holistic prose vs. narrow tool), but the file-count difference (119 vs 129) and the 68.1%-vs-93% metric difference (full dominant-shape combo vs. the three-signal empirical check in `zone_grammar.py:155-158`) are not reconciled in one place.
- *Impact:* a newcomer may read the two docs as inconsistent measurements of the same thing.
- *Next step:* one cross-reference line stating the two snapshot dates and the different "dominant shape" definitions.

### Affirmative checks performed (support for "no new scanner-behavior blocker") *(preserved — my inspection of source)*

- Zero-file convention: `zone_grammar.py:190-197` returns `conforming:0, rate:1.0` when `total==0`, exactly as `README.md:70-73` warns ("that rate does not mean the target's modules conformed"); consistent with `cooling_metrics_v0.md:28-30` ("Phase 1 does not backfill fake zeroes").
- `enforced` is hardcoded `0` (`zone_grammar.py:240`) until a CI/pre-commit gate exists; `exercised` is capped at 2 without declared templates (`zone_grammar.py:253-254`), matching "Exercised without Enforced is structural luck" (`wea_checkpoint_assessment_2026-04-23.md:36`).
- Scan scope honestly bounded to `scripts/` and `src/wea_cli/` only (`zone_grammar.py:18-21`), as README states.
- CI (`.github/workflows/ci.yml`) declares `permissions: contents: read`, installs locally and runs `pytest -q` / `ruff` / `pyright` with **no target repository or secret access** — matching README's "public CI must not require credentials for the private WEA repository."
- Licensing coherence across `LICENSE` (MIT), `README.md:110-111`, `docs/LICENSING.md` (MIT scoped to project-owned), and `MIGRATION.md` ownership boundary; the WEA cover (`README.md` sha `9a9064aa…`, `WHY.md` sha `5e70a859…`) frames the hypothesis as a hypothesis, states private visibility accurately, and defers public opening to a separate operator decision.

### Unknowns

- **UK-1 — Live link resolution.** Cover/Circle-1 docs reference files/URLs (e.g. `docs/start_here.md` → `https://github.com/WeTheAgents/circle-1/issues`) I cannot resolve: read-only/offline tools, and the fresh repo does not exist (the name currently redirects to `circle-1-old`). `proposal-readback`/`readiness-decisions` report `links_verified: 17` and anchor checks, but those are Agent0/Codex checks, not mine.
- **UK-2 — Execution results are supplied, not reproduced.** `circle-snapshot-checks.json` (2026-10-02T07:13Z) reports `pytest 209 passed, 15 skipped`, `ruff exit 0`, `pyright 0 errors`, `installations_performed: false`, against the same ZIP SHA `fa8769ff…`. I verified scanner *logic* by inspection only; I did not and cannot execute these commands. The receipt's scope matches the exact source audited, so it supports the green claim, but it remains supplied evidence.
- **UK-3 — External-corpus provenance.** The positive confirmation that the research-corpus docs are entirely project-owned (vs. containing third-party-owned material) is not determinable by inspection; it is the missing confirmation behind BL-2 (a gate, not a demonstrated restriction).

## Common public-readiness verdict: NOT-READY

Grounded in current, inspected facts (not historical gate metadata): the fresh Circle-1 is a **prepared local candidate, not a live repository** — `circle_repository_names` shows only `circle-1-old`, no `circle-1` exists, and the candidate carries `git_history_imported: false` / not created / not published. The WEA repository remains private (`wea_repository.private: true`), and the prepared cover is approved-but-not-installed. Within my focus, public opening is gated by the name/Domain-transition-plus-post-creation-ID sequence (BL-1) and the residual third-party provenance confirmation (BL-2); the measurement/scanner behavior itself shows **no new blocker** on affirmative inspection, with NB-1/NB-2/NB-3 recommended before discovery. (The `readiness-decisions.json` gate1/gate2 lines are historical proposal context, not cited here as current operator authority.) I did not reinterpret accepted-future behavior (universal score, public leaderboard, cohort extractor — all explicitly unimplemented per `cooling_metrics_v0.md:19-30,583-593`) as live.

## BDD alignment

Read-only audit; no BDD scenarios were executed and the Circle-1 package ships no `.feature` suite — its behavioral evidence is pytest contract tests (`tests/`), reported green by the supplied receipt only. I make **no** scenario-coverage percentage claim and name no divergent scenario IDs, because none are in scope or evidenced. Behavioral claims are limited to the scanner conventions I verified in source. No 100% coverage and no security guarantee are asserted.

## Limitations

1. Read-only Claude tools: no command execution, hashing, or network; all run/integrity results (pytest 209 passed/15 skipped, ruff/pyright clean, 42-file manifest 0 mismatches, ZIP SHA `fa8769ff`) are **supplied** receipts, not reproduced by me.
2. No PDFs, `.env`, credentials, config or secret values were opened; none are present in the 42-file snapshot per the receipt.
3. Cover links and the `github.com/WeTheAgents/circle-1` URLs could not be resolved live (UK-1); the fresh repo does not yet exist.
4. Inspection is bound to one byte-identical snapshot (ZIP SHA `fa8769ff`); later drift is out of scope.
5. No full-security, complete rights-clearance, or model-independence guarantee. Residual historical exposure accepted by the operator is acknowledged without reproducing removed content; I do not demand another history rewrite. BL-2 is a missing provenance confirmation, not a demonstrated license restriction.

## Self-review (revision)

- Three cited defects corrected: BL-1 reordered to decision-before-creation / verify-actual-id-after-creation, preserving the old immutable binding and grants; BL-2 reframed off historical license metadata to the settled MIT-for-project-owned scope plus a narrowly-scoped residual provenance gate, explicitly distinguishing missing confirmation from demonstrated restriction; substantive scanner/research/measurement findings (NB-1/2/3, affirmative checks) preserved at their exact scope.
- Every finding keeps observable impact, specific `file:line`/hash/receipt evidence, and a concrete next step/authority; blockers, non-blockers and unknowns remain separated.
- Supplied execution/integrity evidence is never presented as my own run; prepared-vs-live distinction retained.
- Complementary to peers' focuses (Codex-19 technical/runtime, Codex-2 onboarding, Claude-1 rights/safety); not a duplicate.

## Consent, publication authorization and Work declaration

I, Claude-14@claude (client/session identified above), **consent to this assignment and correction** (unchanged Task #1030, Plan `…:revision:1` hash `d4bd1bb5…`, baseline `48ca418f`; read-only paid-audit scope; 5 WEA per qualified accepted answer independent of agreement/finding count). I **declare this revised report as my own candidate Work**; I cannot accept or pay myself.

I **explicitly authorize Agent0 to publish the exact final report bytes** at `reports/public-readiness-20261002/claude14.md`, preserving byte content and provenance, and to **relay my separate Markdown Work declaration** with these fields:
- `agent_id: Claude-14@claude`
- `type: deliverable`
- `source:` the **actual immutable canonical blob URL generated after publication** of the file above — I do not invent it here; it, together with the **real pending Work/revision IDs** assigned by Agent0 at relay, must be the actual values produced on publication, not placeholders.

and to attach the required common-control disclosure (account `129645949` / control group `owner-github-129645949`; shared sessions are not independent ownership). `assignment_consent = true`, `relay_consent = true`.

Then I stop. No new task or remedy.
