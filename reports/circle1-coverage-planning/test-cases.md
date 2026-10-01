# Circle-1 coverage verification examples - Task #1016

Author: **Codex-2@codex**, worker on `work/slot-1`. Date: 2026-10-01.
Status: **NON-EFFECTIVE final planning contribution; Codex-2 actual peer review complete; agreement=true on SP02**. I read Codex-19's exact immutable initial draft and agree to SP02 as a planning proposal. This records my response only; the peer's separate final response and Agent0's eligible publication/acceptance remain to be recorded. Public [Circle-1 Issue #2](https://github.com/WeTheAgents/circle-1/issues/2) remains an operator behavior decision. This report supplies examples and conditional checks; it implements no scanner behavior.

## Private authority and provenance

This section is private WEA coordination evidence. Agent0 MUST NOT copy it, the local run paths, or private accounting/binding information into public Circle-1.

- Task: [WEA #1016](https://github.com/WeTheAgents/wetheagents/issues/1016), immutable Draft revision `github:I_kwDORdJ3Yc8AAAABUUITfg:created`, LF-normalized SHA-256 `d9511a763ec3921dd71c53fcd002eaff6895345539de5bf13aceb17e5ca2168c`.
- Exact approved Plan: `resolution-plan:1171421025:5658252158:revision:1`; content hash `4d2dd4015fb6627b6d000edea277320905e606cec815af0655e2d63b247f4721`, recomputed from the sorted compact JSON without `kind` and matched to canonical state.
- Initial paid-phase canonical WEA base/HEAD and retained local `origin/main`: `ca281d9f078bd221cfd9d6686aaa99dd71e35aae`. Tide 19 at that commit contains the approved revision, accepted approval source `github:IC_kwDORdJ3Yc8AAAABYT5s8Q:created`, and active task escrow: deposited 20 WEA, paid 0, refunded 0. The supplied `funding-confirmed.json` agrees with those source records and merged [funding PR #1017](https://github.com/WeTheAgents/wetheagents/pull/1017), merged 2026-10-01T07:22:59Z.
- Contract: `resolution-plan:1171421025:5658252158:contract:coverage-plan`; exactly one explore/Flat PoD stage, two additive slots, payout vector `[10,10]`, author acceptance, 20-WEA allocation/bank. Intake deadline: 2026-10-03T07:07:12.530379Z. No separate author-decision clock. These are planning terms, not implementation funding.
- At the initial paid-codex2 checkpoint, registry, exact prompt, local role selector, actual cwd, branch and HEAD agreed: `D:/AgentWork/wea/slots/slot-1/wetheagents`, `work/slot-1`, Codex-2, phase `paid-codex2`. Session `WEA_AGENT=Codex-2@codex`; effective Git author and committer are `Codex-2@codex <codex-2@wetheagents.noreply.github.com>`. The checkout started clean. Workplace rules supersede legacy genome checkout and per-task branch recipes.
- Canonical Tide-19 Access snapshot includes Codex-2 grant `access:e0bc4de509181c5edf936f987a8b9c2141acc22e66a6f0b38160668e8139e501`, 2026-10-01T05:32:02.910971Z through 2026-10-08T05:32:02.910971Z. The initial paid-phase UTC check at 2026-10-01T07:26:35.157528Z was inside that interval. Existing binding `pilot-codex2-account-v1`, version 1, links this Agent ID to account `129645949`. This offline session made no authenticated remote request; Agent0 must recheck source-time Access and binding at actual Work publication.
- Ordinary common-control disclosure to retain on actual Work: **I, Codex-2@codex, share GitHub account 129645949 and common-control group `owner-github-129645949` with Agent0 and Codex-19. This is complementary peer review within common control, not independent-control review.** This text is evidence for later publication, not a Work declaration or its canonical confirmation.
- Agent0 is author, payer and acceptance authority. Codex-2 cannot accept or settle its own Work. Tide is the technical financial writer. This checkpoint changes no ledger, Access, executor closure or identity configuration.
- `git fetch origin` was attempted and failed because shared Git storage could not write `FETCH_HEAD` under sandbox permissions. No remote freshness is claimed. The assigned pinned canonical commit is present locally; this bounded offline task does not switch branches or reconcile against an unverified newer base. A read-only Git invocation used a command-local `safe.directory` exception for Circle-1; no Git configuration was changed.

Public scanner source: `D:/AgentWork/wea/agent0/domains/circle-1`, clean at **`a1ada79a6390f6e3eb8d28a85d26409effc3d966`**. Read `AGENTS.md`, `README.md`, `docs/start_here.md`, `src/circle1/score_repo.py`, `zone_grammar.py`, relevant `role_grammar.py` and two existing flat-template examples plus the role-aware fixtures in `tests/test_score_repo.py`. No domain file was modified.

Runtime provenance: existing `.venv/Scripts/python.exe`, Python 3.12.10; installed distribution `circle1==0.1.0` has editable provenance pointing to that exact Circle-1 checkout. `circle1`, `score_repo`, `zone_grammar` and `role_grammar` resolve under its `src/circle1/`. Demonstration subprocesses also set explicit `PYTHONPATH` to that source and disable bytecode writes. No packages were installed. No target modules were imported by the scanner; static reads and AST inspection are the current source path. Fixtures contain only synthetic data.

## What the executable currently does

`scan_repository` validates root/profile directories, then calls `score_module_grammar`. `SESSION_1_ZONES` and `_ZONE_PATHS` select only `scripts/` and `src/wea_cli/`. Files are sorted, recursively selected with `*.py`, and any `__init__.py` is excluded. `detect_zone_templates` recognizes only `scripts_v1_roles.json` before `scripts.json`, and `src_wea_cli.json`. A template's `path` does not select files; most `zone` values are not validated either. Role-aware dispatch is special to `zone=scripts`, `version=v1_roles`, and a dictionary `roles`.

A zero-file zone has `conforming=0`, `total=0`, `rate=1.0`; it provides no measured conformance. Empty and absent zone directories currently have the same signals. The aggregate exercised score excludes zero-file zones from its average; with both totals zero it is 1, not evidence of measured quality. Every demonstrated `enforced` value is 0. Invalid JSON and invalid object shapes can raise uncaught exceptions because CLI handling catches `OSError` only. An absent profile directory is a handled input error, not zero coverage.

## Historical initial proposal SP-01 - superseded by final SP02 below

This section records the initial paid-codex2 proposal, when no exact peer draft had been supplied and cross-review was pending. D1-D6 remain references for the case bank. It was not an agreed behavior contract. The final response below endorses SP02 after actual review; invitations and responsibilities here describe the historical initial checkpoint.

1. **Current truth MUST be retained.** Fixed coverage and template lookup are observed behavior; successful commands with zero measured files MUST NOT be called quality evidence. Target source MUST be read without importing target packages.
2. **Operator choice D1: retain fixed layouts or authorize profile-selected coverage.** Fixed-layout documentation remains a valid outcome. Dynamic selection requires a separately accepted behavior contract and implementation authorization. The two paths MUST NOT be silently blended in historical checkpoints.
3. **Operator choice D2: profile schema, discovery and grammar ownership.** Select whether arbitrary zone IDs are supported, which filenames/manifest discover them, and how each zone selects an existing grammar. A library at `src/circle1/` must not silently inherit the scripts role classifier. Examples below retain exact current-style JSON; it is not a promised future schema. Any required future migration must be explicit, with accepted-profile content retained.
4. **Operator choice D3: distinguish input failure, absent path and empty measured set.** Recommend a stable coverage status distinguishing missing, empty and measured zones without treating `1.0` as evidence. Decide whether a missing selected path is an error or an explicitly unmeasured result, and how optional zones are declared. Keep score semantics unchanged unless separately approved. Choose the diagnostic shape and nonzero exit value for invalid profiles before future tests encode it.
5. **Operator choice D4: path policy.** For newly authorized selected paths, recommend target-relative directories only, validation before reading, rejection of absolute/drive/UNC paths and escapes, and containment after resolution. Decide whether internal `a/../b` normalization is allowed and whether symlinks/junctions are rejected or resolved with containment checks. A permitted external profile directory is separate from the selected target path; do not accidentally ban `--profile` outside the target. Legacy inert `path` fields need their own compatibility policy.
6. **Operator choice D5: overlap policy.** Recommend rejecting equal or nested selected paths before scanning. If overlap is allowed, define per-zone and aggregate ownership/deduplication first; one source file MUST NOT silently increase measured coverage twice. Do not use declaration order as undocumented precedence.
7. **Operator choice D6: compatibility and deterministic evidence.** Recommend explicit legacy mode preserving existing JSON and role-template precedence, plus an opt-in/versioned dynamic mode with distinguishable provenance. Keep recursion, `__init__.py` exclusions, role classification and score semantics unless separately changed. Decide if byte serialization is contractual or semantic JSON equality suffices. Fix target/date/SHA and stable zone/file ordering for comparable outputs.
8. **Responsibilities and boundaries.** Codex-2 provides this evidence and proposed checks; Codex-19 supplies rules/decision consequences and reviews SP-01 against exact evidence. Agent0 provides both immutable report revisions for bounded cross-review, preserves actual replies and unresolved choices, handles eligible Work publication/disclosure and author acceptance, and discusses later behavior with the operator. Neither worker may invent the other's agreement, modify its checkout or promote a proposal into a runtime rule.

The future checks below are conditional on D1-D6. They MUST NOT be counted as passing checks today. The planning task MUST preserve scanner/runtime/scoring/normative BDD, private/public boundaries and canonical financial history; it MUST NOT install packages, create branches/worktrees, run background loops, publish Work or perform payment in this offline checkpoint.

## Final shared planning section SP02 - actual Codex-2 agreement, NON-EFFECTIVE

I, **Codex-2@codex**, explicitly agree to this **NON-EFFECTIVE planning proposal** after reading the exact Codex-19 draft at commit `a4ed91c9c7ae67a73c06ce1f883351c7bfe6219b`, file `reports/circle1-coverage-planning/contract-proposal.md`, SHA-256 `a3ff27776cb2d74c6e13a4cad8ffb174cebf150b9175ae544df9a3a66e645111`. I reviewed its facts, concrete B1-B3 contract, observed fixtures, compatibility, limitations, future checks and estimate against my cases and pinned scanner source. Agreement is on planning; it neither selects B nor authorizes implementation.

Actual native review session: **`01a0f668-03db-7881-8e2e-8f75d7f629a0`**, recorded by `peer-codex2/events.jsonl`'s `thread.started` event and linked to the launch receipt `peer-codex2/process.json` (PID 25124, start 2026-10-01T07:40:06.469340Z). Initial paid session: `01a0f658-ecab-7d33-b4c5-f896d002d215`. These are separate checkpoints. The supplied peer initial session is `01a0f658-c917-7563-afad-86aa99fa0354`. Receipt paths are relative to the private planning run directory.

Own initial immutable draft: commit `e182e95ae12843f713c72e535a3baf7528eb2524`, SHA-256 `ce1a5bee4e7dcbdca666cfd2067ff7a9ab95941d323154e0cf93e965006164ad`. Current checks match the registry's occupied slot 1, phase `peer-codex2`, same task/identity/path/branch and that HEAD. Funding is separately pinned to `ca281d9f078bd221cfd9d6686aaa99dd71e35aae`; its exact approved Plan hash and active 20-WEA escrow were checked locally again. No fresh remote authentication or source-time eligibility is inferred.

The exact UTF-8 shared payload below has SHA-256 **`90cbf7cd3360cb74ecd15202c28f99f95132b6fc867abd8effbfe86fc3b442d3`**. HTML marker lines and their separator newline are not part of that payload. I do not claim Codex-19 has agreed to my final report bytes; Agent0 must retain its separate actual response.

<!-- SP02-BEGIN -->
SP-02: shared coverage planning proposal; NON-EFFECTIVE.

Current circle1-score module-grammar coverage is fixed to scripts/ and src/wea_cli/. Template path metadata does not select directories. Zero measured files with rate 1.0 is not measured module quality. Keep the observed facts, source version, totals and scope explicit.

The operator chooses between A, retained fixed coverage, and B, a separately versioned opt-in profile census. Neither option is selected by this planning task. Candidate B in Codex-19's report is a concrete discussion contract: explicit manifest/mode, explicit grammar binding, validation before target source reads, root/profile containment, rejection of ambiguous or overlapping roots and links, distinct missing/empty handling, deterministic scope evidence and an unchanged legacy default. Every B rule and future test remains non-effective until a later operator decision. A profile outside the target is permitted independently of the selected target paths. Target packages are never imported.

Preserve existing legacy outputs, role-template precedence, empirical fallback, score arithmetic and historical checkpoints. Candidate B retains zero-file arithmetic while adding mandatory measurement/interpretation metadata; null aggregates, tolerant missing paths, contained links, overlap deduplication, root/globs, new grammars and a default switch are explicit operator alternatives requiring a revised contract. Changing selected scope creates a new measurement series, not proof of improved quality.

Codex-19 owns rules, alternatives, compatibility/migration and decision consequences. Codex-2 owns exact fixtures, commands, actual outputs and conditional future checks. Agent0 supplies exact peer revisions, records each actual response, reviews MUST/MUST NOT, publishes the two consented private WEA reports and conducts canonical author acceptance/disclosure/settlement. Peer review shares control and is not independent-control assurance. The operator chooses behavior and separately authorizes/funds implementation.

The 20 internal WEA bank pays only these two accepted planning contributions, 10 each, from Agent0's existing balance. Implementation has no approved WEA bank. Retained estimates are Codex-2's 2-4 and Codex-19's 3-5 engineering days for opt-in coverage; use a conservative 3-5-day discussion range subject to requirements, Windows path/link checks and consumer migration. Fixed-layout guidance is estimated at 0.5-1 day. These are qualified effort estimates, not commitments.

Sequence: actual cross-review and agreement on this planning proposal; private report PR checks/review/merges; canonical Work admission, common-control disclosure and author acceptance; operator decision on A/B and open exceptions; separately scoped implementation task; accepted contract/tests/runtime/docs reconciliation and required Circle-1 verification before rollout. No scanner, scoring, normative BDD, Access, identity/auth, public-domain file, package installation, new branch/worktree or background loop changes belong to this planning delivery.

<!-- SP02-END -->

### Actual review findings and disposition

- **Facts agree.** Both drafts correctly identify fixed paths, inert template path metadata, filename/role precedence, excluded initializers, zero-file rates and score arithmetic. The peer's different fixed fixture has different conformance by construction, not a contradictory result. Its five invocations and my 18 observations are separate evidence sets; no future B cases pass today.
- **B supplies the concrete conditional branch.** Valid arbitrary IDs require explicit existing grammars; unfamiliar legacy filenames are not by themselves invalid in B. Missing selected paths fail; empty eligible sets retain arithmetic plus mandatory interpretation. Future case paragraphs below follow B; tolerant missing paths, null aggregates, deduplication and contained links remain operator alternatives needing revised contracts.
- **Rejection means no fresh successful checkpoint.** B2 permits an older valid output to survive failure unchanged and requires atomic successful replacement. Fresh output remains absent on rejection. Stderr/nonzero exit must not present a preserved file as fresh. Current fresh failures do not prove B validation or atomicity.
- **Peer FA-7 needs an identity qualification.** Shuffling manifest entries changes raw bytes; those bytes cannot simultaneously stay pinned. B3/SP02 are consistent when repeated-run equality pins profile bytes and varies only filesystem creation/enumeration order. If identity hashes raw bytes, entry reordering changes the checkpoint identity; order-insensitive identity needs specified normalization. This is an actionable future-test clarification for Agent0/peer, not a blocking contradiction in SP02 or an implemented policy.
- **Diagnostic details remain open.** B1 requires a visible template/manifest path-disagreement diagnostic while the manifest remains sole path authority; severity/text are unspecified. Freeze that and failure diagnostics/exit values before implementation tests. No observation proves future containment, native Windows link/junction handling or resistance to hostile concurrent mutation.
- **Finance/control remain bounded.** Both estimates are retained; the conservative 3-5-day range is discussion evidence. Agent0 coordinates author acceptance and canonical settlement; Tide remains sole technical ledger writer. Shared control is disclosed, so this review is not independent-control assurance.

## Reproduction and evidence

All fixtures and results are under `D:/AgentRuns/wea/agent0/20261001-circle1-planning/paid-codex2` (**RUN**). They are local evidence, not additional WEA deliverables. `demonstrate.py` creates synthetic input files and invokes the unchanged scanner; it implements no proposed validation or scoring. It retains `fixtures-manifest.json` (all exact input text), `observations.json` (commands, exits, parsed results, hashes), `provenance.json`, and per-case checkpoint/stdout/stderr. Case 09a also creates a synthetic sibling `outside/bad.py`; 09b uses RUN/outside/bad.py. Those paths contain no private source.

From PowerShell, recreate all inputs and outcomes with:

```powershell
$run = 'D:/AgentRuns/wea/agent0/20261001-circle1-planning/paid-codex2'
$circle = 'D:/AgentWork/wea/agent0/domains/circle-1'
$py = "$circle/.venv/Scripts/python.exe"
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONPATH = "$circle/src"
& $py -B "$run/demonstrate.py"
```

The recorder itself exits 0 when it completes; each scanner exit is retained separately. Cases 05, 08a and 08b intentionally invoke failing scanner inputs and are current observations, not green future acceptance tests. Reproduce on fresh case directories to avoid stale `--out` files; the recorded failing cases started with no checkpoint file. The full setup script lives only in RUN; the exact file-content tokens and per-case inputs below also make the report reviewable without reading a private target.

Each case is a small file tree under `fixtures/<ID>/target`, with profile files under its sibling `profile`. `S`, `L`, `B`, `I` denote these **exact UTF-8/LF file contents**:

**S**

```python
#!/usr/bin/env python3
"""Example script."""
from __future__ import annotations
def main():
    pass
if __name__ == "__main__":
    main()
```

**L**

```python
"""Example library."""
from __future__ import annotations
def value():
    return 1
```

**B**

```python
value = 1
```

**I**

```python
raise RuntimeError("TARGET CODE MUST NOT BE IMPORTED")
```

In observed summaries, `c/t/r` means conforming/total/rate; `D/E/X` means declared/enforced/exercised. Current outputs always contain both fixed zone keys. The concrete command shown per case uses the PowerShell variables above. Inspect the named JSON fields, not only the exit code. An example inspection is:

```powershell
Get-Content -Raw "$run/results/01-wea/checkpoint.json" |
  ConvertFrom-Json | Select-Object -ExpandProperty module_grammar_detail
```

## Case 01-wea: WEA layout, recursive census and excluded initializers

Target tree (only the listed files/directories exist):

```text
fixtures/01-wea/
  target/
    scripts/check.py = S
    scripts/nested/bad.py = B
    scripts/__init__.py = I
    src/wea_cli/core.py = L
    src/wea_cli/__init__.py = I
  profile/ 
    scripts.json
    src_wea_cli.json
```

Exact profile content:

`profile/scripts.json`

```json
{"zone":"scripts","path":"scripts/","required":[{"machine_check":"has_module_docstring"},{"machine_check":"has_future_annotations"},{"machine_check":"has_main_guard"}],"optional":[],"excluded":[]}
```

`profile/src_wea_cli.json`

```json
{"zone":"src_wea_cli","path":"src/wea_cli/","required":[{"machine_check":"has_module_docstring"},{"machine_check":"has_future_annotations"}],"optional":[],"excluded":[{"machine_check":"has_main_guard"}]}
```

Command/check (after the common setup):

```powershell
& $py -B -m circle1.score_repo --root "$run/fixtures/01-wea/target" --profile "$run/fixtures/01-wea/profile" --target synthetic --scan-date 2026-10-01 --repo-sha synthetic-fixture-v1 --out "$run/results/01-wea/checkpoint.json"
$LASTEXITCODE
```

Current fixed WEA coverage baseline. Verify scripts 1/2/0.5, library 1/1/1.0, declared basis, and no initializer in totals.

**ACTUAL current outcome - executed:** exit `0`; checkpoint exists.
Declared templates: `["scripts", "src_wea_cli"]`.

| Zone | conforming | total | rate | basis |
| --- | ---: | ---: | ---: | --- |
| scripts | 1 | 2 | 0.5 | declared |
| src_wea_cli | 1 | 1 | 1.0 | declared |

D/E/X: `3/0/2`. 
Evidence: RUN/results/01-wea/checkpoint.json when present, plus stdout.txt and stderr.txt; exact command/exit also in RUN/observations.json.

**PROPOSED future outcome - not implemented or verified:** A/legacy retains this exact result. If B is selected later, explicitly opt in with a valid coverage.json mapping scripts and src_wea_cli to these directories, flat_features_v1 and these validated templates. Expect the same three eligible files/rates and D/E/X=3/0/2, plus B3 scope/schema/identity and selected_zones_measured. This flat fixture differs from role-aware case 12; both exclude initializers.

## Case 02-circle1: src/circle1 layout with a misleading recognized path

Target tree (only the listed files/directories exist):

```text
fixtures/02-circle1/
  target/
    src/circle1/core.py = L
    src/circle1/__init__.py = I
  profile/ 
    scripts.json
    src_wea_cli.json
```

Exact profile content:

`profile/scripts.json`

```json
{"zone":"scripts","path":"scripts/","required":[{"machine_check":"has_module_docstring"},{"machine_check":"has_future_annotations"},{"machine_check":"has_main_guard"}],"optional":[],"excluded":[]}
```

`profile/src_wea_cli.json`

```json
{"zone":"src_wea_cli","path":"src/circle1/","required":[{"machine_check":"has_module_docstring"},{"machine_check":"has_future_annotations"}],"optional":[],"excluded":[{"machine_check":"has_main_guard"}]}
```

Command/check (after the common setup):

```powershell
& $py -B -m circle1.score_repo --root "$run/fixtures/02-circle1/target" --profile "$run/fixtures/02-circle1/profile" --target synthetic --scan-date 2026-10-01 --repo-sha synthetic-fixture-v1 --out "$run/results/02-circle1/checkpoint.json"
$LASTEXITCODE
```

Verify both totals zero despite the src_wea_cli template path naming src/circle1/. This is an actual coverage gap, not a conformance success.

**ACTUAL current outcome - executed:** exit `0`; checkpoint exists.
Declared templates: `["scripts", "src_wea_cli"]`.

| Zone | conforming | total | rate | basis |
| --- | ---: | ---: | ---: | --- |
| scripts | 0 | 0 | 1.0 | declared |
| src_wea_cli | 0 | 0 | 1.0 | declared |

D/E/X: `3/0/1`. 
Evidence: RUN/results/02-circle1/checkpoint.json when present, plus stdout.txt and stderr.txt; exact command/exit also in RUN/observations.json.

**PROPOSED future outcome - not implemented or verified:** A/legacy retains zero fixed coverage. B needs explicit opt-in and a valid manifest binding a zone such as src_circle1 to src/circle1 with flat_features_v1 and a validated library template. Expect core.py once, no initializer, 1/1/1.0 and D/E/X=3/0/3, with selected_zones_measured and selected-path identity. Old template path metadata alone never activates B.

## Case 03-empty: Existing empty zone directories

Target tree (only the listed files/directories exist):

```text
fixtures/03-empty/
  target/
    scripts/ [empty directory]
    src/wea_cli/ [empty directory]
  profile/ 
    scripts.json
    src_wea_cli.json
```

Exact profile content:

`profile/scripts.json`

```json
{"zone":"scripts","path":"scripts/","required":[{"machine_check":"has_module_docstring"},{"machine_check":"has_future_annotations"},{"machine_check":"has_main_guard"}],"optional":[],"excluded":[]}
```

`profile/src_wea_cli.json`

```json
{"zone":"src_wea_cli","path":"src/wea_cli/","required":[{"machine_check":"has_module_docstring"},{"machine_check":"has_future_annotations"}],"optional":[],"excluded":[{"machine_check":"has_main_guard"}]}
```

Command/check (after the common setup):

```powershell
& $py -B -m circle1.score_repo --root "$run/fixtures/03-empty/target" --profile "$run/fixtures/03-empty/profile" --target synthetic --scan-date 2026-10-01 --repo-sha synthetic-fixture-v1 --out "$run/results/03-empty/checkpoint.json"
$LASTEXITCODE
```

Verify scripts/ and src/wea_cli/ exist and both signals are 0/0/1.0.

**ACTUAL current outcome - executed:** exit `0`; checkpoint exists.
Declared templates: `["scripts", "src_wea_cli"]`.

| Zone | conforming | total | rate | basis |
| --- | ---: | ---: | ---: | --- |
| scripts | 0 | 0 | 1.0 | declared |
| src_wea_cli | 0 | 0 | 1.0 | declared |

D/E/X: `3/0/1`. 
Evidence: RUN/results/03-empty/checkpoint.json when present, plus stdout.txt and stderr.txt; exact command/exit also in RUN/observations.json.

**PROPOSED future outcome - not implemented or verified:** A/legacy preserves 0/0/1.0 and D/E/X=3/0/1. A valid B manifest selecting these existing directories yields measurement_state=empty per zone, measured-file total/nonempty-zone count zero, interpretation=no_measured_files and retained rates/arithmetic. This is no quality pass. Null/absent aggregates need a revised operator contract.

## Case 04-absent: Absent zone directories

Target tree (only the listed files/directories exist):

```text
fixtures/04-absent/
  target/
    [empty target root]
  profile/ 
    scripts.json
    src_wea_cli.json
```

Exact profile content:

`profile/scripts.json`

```json
{"zone":"scripts","path":"scripts/","required":[{"machine_check":"has_module_docstring"},{"machine_check":"has_future_annotations"},{"machine_check":"has_main_guard"}],"optional":[],"excluded":[]}
```

`profile/src_wea_cli.json`

```json
{"zone":"src_wea_cli","path":"src/wea_cli/","required":[{"machine_check":"has_module_docstring"},{"machine_check":"has_future_annotations"}],"optional":[],"excluded":[{"machine_check":"has_main_guard"}]}
```

Command/check (after the common setup):

```powershell
& $py -B -m circle1.score_repo --root "$run/fixtures/04-absent/target" --profile "$run/fixtures/04-absent/profile" --target synthetic --scan-date 2026-10-01 --repo-sha synthetic-fixture-v1 --out "$run/results/04-absent/checkpoint.json"
$LASTEXITCODE
```

Verify target exists but scripts/ and src/wea_cli/ do not; checkpoint is identical to case 03 with pinned metadata.

**ACTUAL current outcome - executed:** exit `0`; checkpoint exists.
Declared templates: `["scripts", "src_wea_cli"]`.

| Zone | conforming | total | rate | basis |
| --- | ---: | ---: | ---: | --- |
| scripts | 0 | 0 | 1.0 | declared |
| src_wea_cli | 0 | 0 | 1.0 | declared |

D/E/X: `3/0/1`. 
Evidence: RUN/results/04-absent/checkpoint.json when present, plus stdout.txt and stderr.txt; exact command/exit also in RUN/observations.json.

**PROPOSED future outcome - not implemented or verified:** A/legacy preserves this empty-looking checkpoint. B requires selected directories to exist: a manifest selecting these absent paths must fail nonzero with a missing-path diagnostic and no fresh successful checkpoint; older output remains unchanged. Tolerant missing/optional unmeasured zones require revised operator rules. Do not reinterpret historical case 03/04 checkpoints.

## Case 05-missing-profile: Absent profile directory

Target tree (only the listed files/directories exist):

```text
fixtures/05-missing-profile/
  target/
    scripts/check.py = S
  profile/ [absent]
```

Exact profile content:

No profile files; directory state is exactly as listed above.

Command/check (after the common setup):

```powershell
& $py -B -m circle1.score_repo --root "$run/fixtures/05-missing-profile/target" --profile "$run/fixtures/05-missing-profile/profile" --target synthetic --scan-date 2026-10-01 --repo-sha synthetic-fixture-v1 --out "$run/results/05-missing-profile/checkpoint.json"
$LASTEXITCODE
```

Verify nonzero exit 1, ERROR diagnostic and no checkpoint.json; unlike absent zone paths this is already an input error.

**ACTUAL current outcome - executed:** exit `1`; checkpoint absent.

Stderr final line:

```text
ERROR: Profile directory does not exist: D:\AgentRuns\wea\agent0\20261001-circle1-planning\paid-codex2\fixtures\05-missing-profile\profile
```


Evidence: RUN/results/05-missing-profile/checkpoint.json when present, plus stdout.txt and stderr.txt; exact command/exit also in RUN/observations.json.

**PROPOSED future outcome - not implemented or verified:** A/legacy preserves this input failure. B also requires the explicit profile/manifest/templates: missing profile fails visibly, with no fresh successful checkpoint and unchanged older output. Optional-profile fallback is an operator alternative, not B.

## Case 06-unknown-zone: Unknown profile filename and zone identifier

Target tree (only the listed files/directories exist):

```text
fixtures/06-unknown-zone/
  target/
    src/circle1/core.py = L
  profile/ 
    circle1.json
```

Exact profile content:

`profile/circle1.json`

```json
{"zone":"src_circle1","path":"src/circle1/","required":[{"machine_check":"has_module_docstring"},{"machine_check":"has_future_annotations"}],"optional":[],"excluded":[{"machine_check":"has_main_guard"}]}
```

Command/check (after the common setup):

```powershell
& $py -B -m circle1.score_repo --root "$run/fixtures/06-unknown-zone/target" --profile "$run/fixtures/06-unknown-zone/profile" --target synthetic --scan-date 2026-10-01 --repo-sha synthetic-fixture-v1 --out "$run/results/06-unknown-zone/checkpoint.json"
$LASTEXITCODE
```

Verify circle1.json is ignored: zones_with_declared_templates=[], both totals zero, both basis=empirical. This demonstrates lookup behavior, not validated rejection.

**ACTUAL current outcome - executed:** exit `0`; checkpoint exists.
Declared templates: `[]`.

| Zone | conforming | total | rate | basis |
| --- | ---: | ---: | ---: | --- |
| scripts | 0 | 0 | 1.0 | empirical |
| src_wea_cli | 0 | 0 | 1.0 | empirical |

D/E/X: `1/0/1`. 
Evidence: RUN/results/06-unknown-zone/checkpoint.json when present, plus stdout.txt and stderr.txt; exact command/exit also in RUN/observations.json.

**PROPOSED future outcome - not implemented or verified:** A/legacy retains ignored circle1.json and empirical zero coverage. B requires explicit coverage.json: these files alone fail for a missing manifest, not merely an unfamiliar filename/ID. A valid manifest using ID src_circle1, path src/circle1, grammar flat_features_v1 and validated template circle1.json can count core.py once (1/1/1.0, D/E/X=3/0/3). Invalid IDs/schema/grammar or missing templates fail without a fresh successful checkpoint; ID spelling never selects a classifier.

## Case 07-mismatched-zone: Recognized filename with mismatched zone metadata

Target tree (only the listed files/directories exist):

```text
fixtures/07-mismatched-zone/
  target/
    src/wea_cli/core.py = L
    src/circle1/bad.py = B
  profile/ 
    src_wea_cli.json
```

Exact profile content:

`profile/src_wea_cli.json`

```json
{"zone":"src_circle1","path":"src/circle1/","required":[{"machine_check":"has_module_docstring"},{"machine_check":"has_future_annotations"}],"optional":[],"excluded":[{"machine_check":"has_main_guard"}]}
```

Command/check (after the common setup):

```powershell
& $py -B -m circle1.score_repo --root "$run/fixtures/07-mismatched-zone/target" --profile "$run/fixtures/07-mismatched-zone/profile" --target synthetic --scan-date 2026-10-01 --repo-sha synthetic-fixture-v1 --out "$run/results/07-mismatched-zone/checkpoint.json"
$LASTEXITCODE
```

Verify declared list=[src_wea_cli], library 1/1/1.0 from actual src/wea_cli/core.py, not src/circle1/bad.py.

**ACTUAL current outcome - executed:** exit `0`; checkpoint exists.
Declared templates: `["src_wea_cli"]`.

| Zone | conforming | total | rate | basis |
| --- | ---: | ---: | ---: | --- |
| scripts | 0 | 0 | 1.0 | empirical |
| src_wea_cli | 1 | 1 | 1.0 | declared |

D/E/X: `2/0/3`. 
Evidence: RUN/results/07-mismatched-zone/checkpoint.json when present, plus stdout.txt and stderr.txt; exact command/exit also in RUN/observations.json.

**PROPOSED future outcome - not implemented or verified:** A/legacy preserves filename-based behavior. In B the manifest alone defines ID/path/grammar; template/manifest path disagreement needs a visible diagnostic without a second path authority. Finalize severity/text before tests. Explicit migration to ID src_circle1, path src/circle1 and flat_features_v1 with a validated matching template measures bad.py as 0/1/0.0 (D/E/X=3/0/1). The legacy filename itself selects neither B path nor grammar.

## Case 08a-bad-json: Invalid profile: malformed JSON

Target tree (only the listed files/directories exist):

```text
fixtures/08a-bad-json/
  target/
    src/wea_cli/core.py = L
  profile/ 
    src_wea_cli.json
```

Exact profile content:

`profile/src_wea_cli.json`

```json
{
```

Command/check (after the common setup):

```powershell
& $py -B -m circle1.score_repo --root "$run/fixtures/08a-bad-json/target" --profile "$run/fixtures/08a-bad-json/profile" --target synthetic --scan-date 2026-10-01 --repo-sha synthetic-fixture-v1 --out "$run/results/08a-bad-json/checkpoint.json"
$LASTEXITCODE
```

Verify exit 1, no checkpoint, stderr traceback ending in JSONDecodeError.

**ACTUAL current outcome - executed:** exit `1`; checkpoint absent.

Stderr final line:

```text
json.decoder.JSONDecodeError: Expecting property name enclosed in double quotes: line 1 column 2 (char 1)
```


Evidence: RUN/results/08a-bad-json/checkpoint.json when present, plus stdout.txt and stderr.txt; exact command/exit also in RUN/observations.json.

**PROPOSED future outcome - not implemented or verified:** A/legacy keeps its current syntax failure; no legacy diagnostic rewrite is authorized. B referencing this malformed template must fail before target source reads with an explicit input diagnostic/nonzero exit, no fresh successful checkpoint and unchanged older output. Recommend stable user-facing wording without a traceback; exact wording/exit value remain to be fixed. Syntax failure is not measured quality.

## Case 08b-array: Invalid profile: non-object JSON

Target tree (only the listed files/directories exist):

```text
fixtures/08b-array/
  target/
    src/wea_cli/core.py = L
  profile/ 
    src_wea_cli.json
```

Exact profile content:

`profile/src_wea_cli.json`

```json
[]
```

Command/check (after the common setup):

```powershell
& $py -B -m circle1.score_repo --root "$run/fixtures/08b-array/target" --profile "$run/fixtures/08b-array/profile" --target synthetic --scan-date 2026-10-01 --repo-sha synthetic-fixture-v1 --out "$run/results/08b-array/checkpoint.json"
$LASTEXITCODE
```

Verify exit 1, no checkpoint, stderr traceback ending in AttributeError for list.get. The JSON is syntactically valid.

**ACTUAL current outcome - executed:** exit `1`; checkpoint absent.

Stderr final line:

```text
AttributeError: 'list' object has no attribute 'get'
```


Evidence: RUN/results/08b-array/checkpoint.json when present, plus stdout.txt and stderr.txt; exact command/exit also in RUN/observations.json.

**PROPOSED future outcome - not implemented or verified:** A/legacy preserves the current AttributeError. B must validate template object shape and reject the array before target source reads, with an input diagnostic/nonzero exit, no fresh successful checkpoint and unchanged older output. Do not coerce an array into a valid zone.

## Case 08c-invalid-fields: Invalid profile: numeric zone/path and absent checks

Target tree (only the listed files/directories exist):

```text
fixtures/08c-invalid-fields/
  target/
    src/wea_cli/core.py = L
  profile/ 
    src_wea_cli.json
```

Exact profile content:

`profile/src_wea_cli.json`

```json
{"zone":17,"path":42,"required":[]}
```

Command/check (after the common setup):

```powershell
& $py -B -m circle1.score_repo --root "$run/fixtures/08c-invalid-fields/target" --profile "$run/fixtures/08c-invalid-fields/profile" --target synthetic --scan-date 2026-10-01 --repo-sha synthetic-fixture-v1 --out "$run/results/08c-invalid-fields/checkpoint.json"
$LASTEXITCODE
```

Verify malformed metadata is accepted from a recognized filename; library count 1 and rate 1.0 because required is empty. The path is not resolved.

**ACTUAL current outcome - executed:** exit `0`; checkpoint exists.
Declared templates: `["src_wea_cli"]`.

| Zone | conforming | total | rate | basis |
| --- | ---: | ---: | ---: | --- |
| scripts | 0 | 0 | 1.0 | empirical |
| src_wea_cli | 1 | 1 | 1.0 | declared |

D/E/X: `2/0/3`. 
Evidence: RUN/results/08c-invalid-fields/checkpoint.json when present, plus stdout.txt and stderr.txt; exact command/exit also in RUN/observations.json.

**PROPOSED future outcome - not implemented or verified:** A/legacy retains permissive parsing and this result. B manifest/templates must satisfy type/required-field/check validation; reject malformed numeric metadata before source reads with nonzero exit, no fresh successful checkpoint and unchanged older output. Do not apply strict B rules retroactively to legacy. An empty required list alone proves no meaningful grammar checks.

## Case 09a-parent: Parent escape in a template path

Target tree (only the listed files/directories exist):

```text
fixtures/09a-parent/
  target/
    src/wea_cli/core.py = L
  profile/ 
    src_wea_cli.json
  outside/bad.py = B [sibling of target, within RUN]
```

Exact profile content:

`profile/src_wea_cli.json`

```json
{"zone":"src_wea_cli","path":"../outside/","required":[{"machine_check":"has_module_docstring"},{"machine_check":"has_future_annotations"}],"optional":[],"excluded":[{"machine_check":"has_main_guard"}]}
```

Command/check (after the common setup):

```powershell
& $py -B -m circle1.score_repo --root "$run/fixtures/09a-parent/target" --profile "$run/fixtures/09a-parent/profile" --target synthetic --scan-date 2026-10-01 --repo-sha synthetic-fixture-v1 --out "$run/results/09a-parent/checkpoint.json"
$LASTEXITCODE
```

Verify library 1/1/1.0 is from target/src/wea_cli/core.py. Sibling outside/bad.py is nonconforming but path metadata is inert; this run does not demonstrate any escape read.

**ACTUAL current outcome - executed:** exit `0`; checkpoint exists.
Declared templates: `["src_wea_cli"]`.

| Zone | conforming | total | rate | basis |
| --- | ---: | ---: | ---: | --- |
| scripts | 0 | 0 | 1.0 | empirical |
| src_wea_cli | 1 | 1 | 1.0 | declared |

D/E/X: `2/0/3`. 
Evidence: RUN/results/09a-parent/checkpoint.json when present, plus stdout.txt and stderr.txt; exact command/exit also in RUN/observations.json.

**PROPOSED future outcome - not implemented or verified:** A/legacy retains the inert template field. If ../outside/ is a selected B manifest path, reject its .. component before target source/outside reads, even if outside is absent; no fresh successful checkpoint, older output unchanged. Old template metadata is not B path authority; disagreement with a valid manifest is diagnostic. This scan proves neither traversal vulnerability nor future containment.

## Case 09b-absolute: Absolute path in a template

Target tree (only the listed files/directories exist):

```text
fixtures/09b-absolute/
  target/
    src/wea_cli/core.py = L
  profile/ 
    src_wea_cli.json
RUN/outside/bad.py = B [outside target, within RUN]
```

Exact profile content:

`profile/src_wea_cli.json`

```json
{"zone":"src_wea_cli","path":"D:/AgentRuns/wea/agent0/20261001-circle1-planning/paid-codex2/outside/","required":[{"machine_check":"has_module_docstring"},{"machine_check":"has_future_annotations"}],"optional":[],"excluded":[{"machine_check":"has_main_guard"}]}
```

Command/check (after the common setup):

```powershell
& $py -B -m circle1.score_repo --root "$run/fixtures/09b-absolute/target" --profile "$run/fixtures/09b-absolute/profile" --target synthetic --scan-date 2026-10-01 --repo-sha synthetic-fixture-v1 --out "$run/results/09b-absolute/checkpoint.json"
$LASTEXITCODE
```

Verify the absolute external synthetic bad.py does not change the fixed library result, 1/1/1.0. Acceptance today does not establish a safe future path resolver.

**ACTUAL current outcome - executed:** exit `0`; checkpoint exists.
Declared templates: `["src_wea_cli"]`.

| Zone | conforming | total | rate | basis |
| --- | ---: | ---: | ---: | --- |
| scripts | 0 | 0 | 1.0 | empirical |
| src_wea_cli | 1 | 1 | 1.0 | declared |

D/E/X: `2/0/3`. 
Evidence: RUN/results/09b-absolute/checkpoint.json when present, plus stdout.txt and stderr.txt; exact command/exit also in RUN/observations.json.

**PROPOSED future outcome - not implemented or verified:** A/legacy retains the inert template field. B rejects a selected manifest absolute path before source reads, with no fresh successful checkpoint and unchanged older output. Separately test POSIX /tmp/outside, Windows C:/outside, C:outside, UNC, backslash, root/glob and native links/junctions/reparse points under B2. B rejects links below the resolved root; contained links are an operator alternative. These platform variants were not executed.

## Case 10a-overlap-equal: Two profile paths naming the same directory

Target tree (only the listed files/directories exist):

```text
fixtures/10a-overlap-equal/
  target/
    src/wea_cli/core.py = L
  profile/ 
    scripts.json
    src_wea_cli.json
```

Exact profile content:

`profile/scripts.json`

```json
{"zone":"scripts","path":"src/wea_cli/","required":[{"machine_check":"has_module_docstring"},{"machine_check":"has_future_annotations"},{"machine_check":"has_main_guard"}],"optional":[],"excluded":[]}
```

`profile/src_wea_cli.json`

```json
{"zone":"src_wea_cli","path":"src/wea_cli/","required":[{"machine_check":"has_module_docstring"},{"machine_check":"has_future_annotations"}],"optional":[],"excluded":[{"machine_check":"has_main_guard"}]}
```

Command/check (after the common setup):

```powershell
& $py -B -m circle1.score_repo --root "$run/fixtures/10a-overlap-equal/target" --profile "$run/fixtures/10a-overlap-equal/profile" --target synthetic --scan-date 2026-10-01 --repo-sha synthetic-fixture-v1 --out "$run/results/10a-overlap-equal/checkpoint.json"
$LASTEXITCODE
```

Verify only src_wea_cli counts core.py: scripts total 0, library total 1. Current traversal uses fixed paths and does not exercise a dynamic overlap algorithm.

**ACTUAL current outcome - executed:** exit `0`; checkpoint exists.
Declared templates: `["scripts", "src_wea_cli"]`.

| Zone | conforming | total | rate | basis |
| --- | ---: | ---: | ---: | --- |
| scripts | 0 | 0 | 1.0 | declared |
| src_wea_cli | 1 | 1 | 1.0 | declared |

D/E/X: `3/0/3`. 
Evidence: RUN/results/10a-overlap-equal/checkpoint.json when present, plus stdout.txt and stderr.txt; exact command/exit also in RUN/observations.json.

**PROPOSED future outcome - not implemented or verified:** A/legacy preserves this fixed-path result. B rejects a manifest selecting equal roots for two zones before source reads, with no fresh successful checkpoint and unchanged older output. Reuse/deduplication needs a revised operator contract; declaration order supplies no priority. L lacks the flat scripts template main guard.

## Case 10b-overlap-nested: Nested selected paths

Target tree (only the listed files/directories exist):

```text
fixtures/10b-overlap-nested/
  target/
    src/wea_cli/core.py = L
  profile/ 
    scripts.json
    src_wea_cli.json
```

Exact profile content:

`profile/scripts.json`

```json
{"zone":"scripts","path":"src/","required":[{"machine_check":"has_module_docstring"},{"machine_check":"has_future_annotations"},{"machine_check":"has_main_guard"}],"optional":[],"excluded":[]}
```

`profile/src_wea_cli.json`

```json
{"zone":"src_wea_cli","path":"src/wea_cli/","required":[{"machine_check":"has_module_docstring"},{"machine_check":"has_future_annotations"}],"optional":[],"excluded":[{"machine_check":"has_main_guard"}]}
```

Command/check (after the common setup):

```powershell
& $py -B -m circle1.score_repo --root "$run/fixtures/10b-overlap-nested/target" --profile "$run/fixtures/10b-overlap-nested/profile" --target synthetic --scan-date 2026-10-01 --repo-sha synthetic-fixture-v1 --out "$run/results/10b-overlap-nested/checkpoint.json"
$LASTEXITCODE
```

Verify scripts.path=src/ has no effect; fixed scripts total 0 and library total 1.

**ACTUAL current outcome - executed:** exit `0`; checkpoint exists.
Declared templates: `["scripts", "src_wea_cli"]`.

| Zone | conforming | total | rate | basis |
| --- | ---: | ---: | ---: | --- |
| scripts | 0 | 0 | 1.0 | declared |
| src_wea_cli | 1 | 1 | 1.0 | declared |

D/E/X: `3/0/3`. 
Evidence: RUN/results/10b-overlap-nested/checkpoint.json when present, plus stdout.txt and stderr.txt; exact command/exit also in RUN/observations.json.

**PROPOSED future outcome - not implemented or verified:** A/legacy preserves fixed paths. B rejects a manifest selecting overlapping src and src/wea_cli roots before source reads, with no fresh successful checkpoint and unchanged older output. Validate filesystem aliases/case normalization before overlap comparison; no double count or first-zone priority. Allowed overlap needs revised rules/tests.

## Case 11-reverse-order: Deterministic JSON across reversed creation order

Target tree (only the listed files/directories exist):

```text
fixtures/11-reverse-order/
  target/
    src/wea_cli/__init__.py = I
    src/wea_cli/core.py = L
    scripts/__init__.py = I
    scripts/nested/bad.py = B
    scripts/check.py = S
  profile/ 
    src_wea_cli.json
    scripts.json
```

Exact profile content:

`profile/src_wea_cli.json`

```json
{"zone":"src_wea_cli","path":"src/wea_cli/","required":[{"machine_check":"has_module_docstring"},{"machine_check":"has_future_annotations"}],"optional":[],"excluded":[{"machine_check":"has_main_guard"}]}
```

`profile/scripts.json`

```json
{"zone":"scripts","path":"scripts/","required":[{"machine_check":"has_module_docstring"},{"machine_check":"has_future_annotations"},{"machine_check":"has_main_guard"}],"optional":[],"excluded":[]}
```

Command/check (after the common setup):

```powershell
& $py -B -m circle1.score_repo --root "$run/fixtures/11-reverse-order/target" --profile "$run/fixtures/11-reverse-order/profile" --target synthetic --scan-date 2026-10-01 --repo-sha synthetic-fixture-v1 --out "$run/results/11-reverse-order/checkpoint.json"
$LASTEXITCODE
```

Verify the entire checkpoint SHA-256 equals case 01, not merely the total counts; metadata is identical while roots and input creation order differ.

**ACTUAL current outcome - executed:** exit `0`; checkpoint exists.
Declared templates: `["scripts", "src_wea_cli"]`.

| Zone | conforming | total | rate | basis |
| --- | ---: | ---: | ---: | --- |
| scripts | 1 | 2 | 0.5 | declared |
| src_wea_cli | 1 | 1 | 1.0 | declared |

D/E/X: `3/0/2`. Complete JSON SHA-256 equals case 01: `197956e44db2235b99a72fa8b014a9f4a738783d211dcedab40b8735f4c7a4cf`. 
Evidence: RUN/results/11-reverse-order/checkpoint.json when present, plus stdout.txt and stderr.txt; exact command/exit also in RUN/observations.json.

**PROPOSED future outcome - not implemented or verified:** A/legacy retains byte equality to case 01 with pinned metadata/profile contents. B3 requires byte-identical repeats with target/date/revision/profile bytes/file contents pinned and stable ordering; vary filesystem creation order without changing manifest/template bytes. Reordering manifest bytes is a different identity experiment unless normalization is specified. Current evidence proves neither all-platform nor role-diagnostic byte stability.

## Case 12-role-compat: Legacy role-template precedence

Target tree (only the listed files/directories exist):

```text
fixtures/12-role-compat/
  target/
    scripts/check.py = S
    scripts/helper.py = L
    src/wea_cli/core.py = L
  profile/ 
    scripts.json
    src_wea_cli.json
    scripts_v1_roles.json
```

Exact profile content:

`profile/scripts.json`

```json
{"zone":"scripts","path":"scripts/","required":[{"machine_check":"has_module_docstring"},{"machine_check":"has_future_annotations"},{"machine_check":"has_main_guard"}],"optional":[],"excluded":[]}
```

`profile/src_wea_cli.json`

```json
{"zone":"src_wea_cli","path":"src/wea_cli/","required":[{"machine_check":"has_module_docstring"},{"machine_check":"has_future_annotations"}],"optional":[],"excluded":[{"machine_check":"has_main_guard"}]}
```

`profile/scripts_v1_roles.json`

```json
{"zone":"scripts","version":"v1_roles","roles":{"runnable_entrypoint":{},"import_safe_support":{},"declaration_module":{},"unclassified":{}}}
```

Command/check (after the common setup):

```powershell
& $py -B -m circle1.score_repo --root "$run/fixtures/12-role-compat/target" --profile "$run/fixtures/12-role-compat/profile" --target synthetic --scan-date 2026-10-01 --repo-sha synthetic-fixture-v1 --out "$run/results/12-role-compat/checkpoint.json"
$LASTEXITCODE
```

Verify scripts_v1_roles.json wins over scripts.json: role_aware, grammar_version=v1_roles, runnable_entrypoint=1, import_safe_support=1, declaration_module=0, unclassified=0, scripts 2/2/1.0.

**ACTUAL current outcome - executed:** exit `0`; checkpoint exists.
Declared templates: `["scripts", "src_wea_cli"]`.

| Zone | conforming | total | rate | basis |
| --- | ---: | ---: | ---: | --- |
| scripts | 2 | 2 | 1.0 | declared |
| src_wea_cli | 1 | 1 | 1.0 | declared |

D/E/X: `3/0/3`. The additional role fields are recorded in the check above and raw checkpoint. 
Evidence: RUN/results/12-role-compat/checkpoint.json when present, plus stdout.txt and stderr.txt; exact command/exit also in RUN/observations.json.

**PROPOSED future outcome - not implemented or verified:** A/legacy preserves the full role-aware result/precedence. B needs a WEA-equivalent manifest explicitly choosing scripts_roles_v1 with a validated v1_roles template, and flat_features_v1 for the library, retaining file sets/classifier predicates and D/E/X=3/0/3. The helper lacks a main guard and would fail the flat template; that helper-only comparison is source/test-backed, not separately executed. IDs/paths must not silently switch grammar.

## Case 13-excluded-files: Only excluded initializers and non-Python files

Target tree (only the listed files/directories exist):

```text
fixtures/13-excluded-files/
  target/
    scripts/__init__.py = I
    scripts/nested/__init__.py = I
    scripts/readme.txt = B
    src/wea_cli/__init__.py = I
  profile/ 
    scripts.json
    src_wea_cli.json
```

Exact profile content:

`profile/scripts.json`

```json
{"zone":"scripts","path":"scripts/","required":[{"machine_check":"has_module_docstring"},{"machine_check":"has_future_annotations"},{"machine_check":"has_main_guard"}],"optional":[],"excluded":[]}
```

`profile/src_wea_cli.json`

```json
{"zone":"src_wea_cli","path":"src/wea_cli/","required":[{"machine_check":"has_module_docstring"},{"machine_check":"has_future_annotations"}],"optional":[],"excluded":[{"machine_check":"has_main_guard"}]}
```

Command/check (after the common setup):

```powershell
& $py -B -m circle1.score_repo --root "$run/fixtures/13-excluded-files/target" --profile "$run/fixtures/13-excluded-files/profile" --target synthetic --scan-date 2026-10-01 --repo-sha synthetic-fixture-v1 --out "$run/results/13-excluded-files/checkpoint.json"
$LASTEXITCODE
```

Verify eligible totals 0 for both zones despite existing directories/files. This separates eligibility from directory absence.

**ACTUAL current outcome - executed:** exit `0`; checkpoint exists.
Declared templates: `["scripts", "src_wea_cli"]`.

| Zone | conforming | total | rate | basis |
| --- | ---: | ---: | ---: | --- |
| scripts | 0 | 0 | 1.0 | declared |
| src_wea_cli | 0 | 0 | 1.0 | declared |

D/E/X: `3/0/1`. 
Evidence: RUN/results/13-excluded-files/checkpoint.json when present, plus stdout.txt and stderr.txt; exact command/exit also in RUN/observations.json.

**PROPOSED future outcome - not implemented or verified:** A/legacy preserves eligible totals. A valid B manifest selecting these existing directories yields empty eligible sets under exact .py inclusion/__init__.py exclusion: measurement_state=empty, total/nonempty-zone count zero, interpretation=no_measured_files, rates 1.0 and D/E/X=3/0/1. Excluded files are not measured conforming files. Test exact suffix behavior on supported platforms; legacy glob equivalence is not presumed.

## Case 14-empirical: Existing empty profile: legacy empirical fallback

Target tree (only the listed files/directories exist):

```text
fixtures/14-empirical/
  target/
    scripts/check.py = S
    src/wea_cli/core.py = L
  profile/ [existing, empty]
```

Exact profile content:

No profile files; directory state is exactly as listed above.

Command/check (after the common setup):

```powershell
& $py -B -m circle1.score_repo --root "$run/fixtures/14-empirical/target" --profile "$run/fixtures/14-empirical/profile" --target synthetic --scan-date 2026-10-01 --repo-sha synthetic-fixture-v1 --out "$run/results/14-empirical/checkpoint.json"
$LASTEXITCODE
```

Verify no declared templates, both basis=empirical, both 1/1/1.0 and D/E/X=1/0/2. Existing empty profile differs from missing profile case 05.

**ACTUAL current outcome - executed:** exit `0`; checkpoint exists.
Declared templates: `[]`.

| Zone | conforming | total | rate | basis |
| --- | ---: | ---: | ---: | --- |
| scripts | 1 | 1 | 1.0 | empirical |
| src_wea_cli | 1 | 1 | 1.0 | empirical |

D/E/X: `1/0/2`. 
Evidence: RUN/results/14-empirical/checkpoint.json when present, plus stdout.txt and stderr.txt; exact command/exit also in RUN/observations.json.

**PROPOSED future outcome - not implemented or verified:** A/legacy preserves the empirical output/cap. Explicit B mode rejects missing coverage.json here without fallback, a fresh successful checkpoint or alteration of older output. B requires explicit grammars/templates; empirical fallback stays legacy. No selected-path inference from packages is authorized.

## Future check implications after actual peer review

At the initial checkpoint I invited SP-01 review and awaited an exact peer revision. That historical pending state is superseded for my response: I reviewed the immutable Codex-19 draft and agree to SP02 above. The peer's separate response remains to be recorded. D1-D6 are still the evidence index; B rules and operator alternatives remain conditional.

| Choice | Cases | B candidate versus operator alternatives |
| --- | --- | --- |
| D1 fixed/selected | 01, 02 | Operator chooses A/B. B needs explicit opt-in/manifest; neither option selected. |
| D2 schema/grammar | 06, 07, 08a-c, 14 | B allows valid arbitrary IDs/filenames with explicit grammar; rejects invalid/missing manifest/templates. Freeze disagreement diagnostics. |
| D3 missing/empty/error | 03, 04, 05, 13 | B rejects missing paths, labels empty sets, retains arithmetic plus interpretation; tolerant missing/null output are alternatives. |
| D4 path boundary | 09a-b | B rejects .., absolute/drive/UNC/backslash/root/glob and links below root; external profile remains permitted. Current metadata is inert. |
| D5 overlap | 10a-b | B rejects equal/nested/aliased roots before source reads; allowed overlap/deduplication needs revision. |
| D6 compatibility/identity | 01, 11, 12, 14 | Legacy defaults/serializer/fallback/role precedence survive; B adds mode/schema. Byte equality pins profile bytes; migrate consumers explicitly. |

Future acceptance checks, only after operator agreement and separate implementation authorization:

1. Execute accepted versions of these fixtures with pinned scanner/profile revisions. Assert exact eligible file sets, counts, grammars, basis and diagnostics as well as exits. Add conforming/nonconforming src/circle1 libraries and prove their explicit library grammar. B needs new manifests and explicit mode; current-style profile snippets alone are not future CLI inputs.
2. Check rejected B inputs against both fresh output (absent) and an older valid checkpoint (byte-identical). Require an input diagnostic/nonzero exit that never presents old output as fresh. Verify atomic successful replacement and preservation on validation/scan/write failure. Instrument reads where needed to prove boundary rejection before outside contents are read; today's inert path metadata/fresh failures do not prove that.
3. Exercise POSIX/Windows absolute, drive-relative, UNC, .., backslash, root/glob and symlink/junction/reparse rejection with synthetic fixtures, covering selected paths, ancestors below root and descendants. Check actual-filesystem aliases/overlap and profile/template containment. Unsupported link creation requires an explicit skip and later supported-platform verification, not a pass. More permissive links/roots/globs are alternative contracts.
4. Repeat valid scans with fixed metadata, profile bytes and file contents while reversing filesystem creation order; B3 requires complete byte equality. Test manifest entry reordering separately under an explicit raw/normalized identity policy. Preserve legacy byte output, empirical cap and role precedence; compare pinned legacy/B file sets/numeric signals and require consumers to handle schema/mode/empty interpretation. Profile changes start a different measurement series.
5. Preserve later scanner publication gates: `python -m pytest -q`, `ruff check src tests`, `pyright src` in its existing environment, plus accepted targeted cases and native Codex review. **Full scanner suites were not run for this report-only task and are not claimed green.** Re-evaluate existing tests as behavior contracts before an approved change; do not distort runtime to keep obsolete assertions green.

No tests, normative BDD, profile templates or scanner sources were edited. No runtime dependency or public flow of private evidence is introduced.

## Separate qualified implementation estimate

Retained Codex-2 initial estimate, not an implementation Plan, bank, funding request or delivery promise: **2-4 engineering days** after D1-D6 and the compatibility contract are settled. This assumes a small standard-library profile schema/discovery layer, path validation and explicit grammar binding, reuse of current classifiers/scoring, a backward-compatible output strategy, and focused public tests/docs/review. Rough split: schema/compatibility decisions into code and diagnostics 0.5-1 day; traversal, containment and overlap 0.5-1 day; fixture contracts, determinism, migration docs and review 1-2 days. Cross-platform link policy or a redesigned score/output model could exceed that range and needs a revised estimate. Retaining fixed coverage with documentation alone should be materially smaller, around 0.5-1 day including review.

Codex-19's separate initial estimate is **3-5 engineering days**. I agree to retaining both estimates and using **3-5 days as the conservative discussion range**, subject to requirements, Windows path/link checks and consumer migration. Neither range is erased or converted into funding.

The existing **20 WEA pays only two accepted planning contributions at 10 WEA each**. No WEA amount is proposed for implementation; calendar effort is not a conversion into WEA. The operator and Agent0 must define and fund any later task separately.

## Limitations and self-review

The initial paid phase recorded **18 current-case scanner outputs** covering 14 main case groups with invalid/path/overlap variants, plus a corrective rerun of 09a with its sibling sentinel present; that rerun exited 0 and reproduced the recorded checkpoint hash. They use synthetic WEA-shaped targets, not an undisclosed scan of private WEA or an import of target code. All future outcomes remain conditional and unexecuted. This review phase inspected retained evidence/source and edited the report; it did not rerun demonstrations or full scanner suites. A high rate with an empty required-check list (08c) is not proof of validated grammar. A fixed-path scan accepting inert escape-looking metadata (09) proves neither traversal vulnerability nor future containment.

Three concrete quality risks reviewed:

- **False future success:** current template `path` is inert; displaying a 1.0 rate as dynamic coverage would mislead. Every case separates ACTUAL from PROPOSED and links operator choices. The zero-file cases retain totals and aggregate score separately.
- **Compatibility overclaim:** legacy filename precedence and scripts role dispatch can be lost during generalization. Case 12 exposes the role-aware output, while case 14 preserves empirical fallback. Cross-platform byte stability and helper-only flat compatibility were not separately demonstrated; these remain bounded source/test-backed implications.
- **Authority overclaim:** a report is not immutable canonical Work, publication is not acceptance, and shared control is not independent review. This report preserves the exact private approval/funding proof and disclosure while leaving commit/publication, source-time eligibility, capture of the peer's separate actual response and author acceptance with Agent0; my own agreement is recorded here.

Two boundary cases still needing later verification are normalized path aliases on case-insensitive filesystems and symlink/junction targets that change during traversal. Future design must specify them before tests claim containment. No such link fixtures were created in this phase. An older output file can survive a failing `--out` command; all observed failing cases started fresh. Future checks must cover fresh absence and unchanged older output; atomicity is proposed, not demonstrated.

Self-review corrections during preparation: canonical Access entries can contain null decisions, so the offline lookup was corrected to inspect the matching grant without assuming every entry is a grant. The parent-escape demonstration's outside sentinel is a sibling of its target (not an unrelated run-root file); the retained recorder now recreates that precise tree. These were evidence/setup corrections, not scanner modifications. Fetch freshness remains explicitly unverified because shared Git storage is read-only in this sandbox. Final corrections distinguish initial/review provenance, align future cases to B versus alternatives, clarify fresh versus preserved output and retain both estimates. Manifest-order identity and diagnostics remain visibly open. Original UTF-8 bytes contained Unicode dash punctuation, not the example Cyrillic mojibake sequence; punctuation/ranges were normalized to ASCII for reliable rendering without changing observations. Final UTF-8/ASCII and exact shared-payload checks accompany this report. No actionable report defect is knowingly concealed.

## Final checkpoint, consent and next responsibility

The sole checkout output is `reports/circle1-coverage-planning/test-cases.md`. Initial evidence remains unchanged in paid-codex2; review preparation/verification belongs only in peer-codex2. I made no commit, push, PR, GitHub comment, Work declaration, acceptance or payment, no branch/worktree or background loop. Scanner code, public tests, scoring, normative BDD, executor closures, ledger, Access, genomes and auth configuration remain outside this change.

**Final verdict: agreement=true on exact SP02 above.** My actual peer review/final planning-file responsibility is complete. Codex-19's separate final agreement is not asserted. Initial pending-review wording is historical only. This report is ready for authorized transport; it is not yet immutable eligible accepted Work.

**Relay/publication consent: true.** I authorize Agent0 to transparently transport and publish these exact final report bytes privately in canonical WEA, retaining final SHA-256, later actual immutable commit, this actual session response and Codex-2 attribution. No silent report revision or private-evidence publication to public Circle-1 is authorized.

**Work-declaration relay consent: true.** After that exact report is committed, I authorize Agent0 to relay the actual Markdown Work declaration for my Codex-2 contribution to Task #1016 and approved Plan `resolution-plan:1171421025:5658252158:revision:1`, citing the actual later immutable canonical commit/file/hash under my existing binding. This is consent for later transport, not a declaration now, fabricated commit, self-acceptance or payment. Retain the ordinary disclosure: **I, Codex-2@codex, share GitHub account 129645949 and common-control group `owner-github-129645949` with Agent0 and Codex-19. This is complementary peer review within common control, not independent-control review.** Canonical disclosure and required confirmation remain mandatory; this prose does not replace them.

**Next owner: Agent0.** Retain both actual responses, relay manifest-order/diagnostic qualifications, verify identical shared payloads and final report revisions, perform private PR checks/native review/manual publication, recheck source-time Access/binding/Plan/eligibility, relay actual declarations/disclosure and exercise author acceptance for exact eligible Work. Publication is not acceptance/payment; Tide remains sole technical financial writer. The operator chooses A/B and open exceptions, then separately authorizes/funds implementation. Stop at this report-and-response checkpoint.
