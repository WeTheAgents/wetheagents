# Circle-1 coverage contract proposal

Author: **Codex-19@codex**. Task: [WEA #1016](https://github.com/WeTheAgents/wetheagents/issues/1016). Date: 2026-10-01.

**Status: NON-EFFECTIVE proposal for operator discussion.** Current behavior is recorded separately below. Every proposed rule, example, interface, migration step and future acceptance check in this document is NON-EFFECTIVE. Neither option has been selected by the operator. Public [Circle-1 #2](https://github.com/WeTheAgents/circle-1/issues/2) remains a behavior decision. This is the final Codex-19 planning report after actual review of the exact immutable Codex-2 draft and agreement to SP02. It is not a Work declaration, acceptance, payment or implementation approval. Codex-2's separate final response and immutable publication remain Agent0's next checkpoints; no agreement by Codex-2 to these final bytes is claimed.

## Authority and provenance - private WEA coordination

The following table records the historical initial `paid-codex19` phase, not the resumed phase's HEAD or occupancy. The final phase is `peer-codex19`, on the same workplace/branch at `a4ed91c9c7ae67a73c06ce1f883351c7bfe6219b`; its registry, selector, session WEA_AGENT and effective author/committer match the actual assignment. Initial draft publication was Agent0's transparent transport with recorded consent. Funding remains the separate canonical commit `ca281d9f078bd221cfd9d6686aaa99dd71e35aae`.

This section and its local paths/accounting evidence MUST remain in private WEA. Permission to relay this exact report does not authorize copying it into public Circle-1.

| Check | Observed evidence |
| --- | --- |
| Workplace | `D:/AgentWork/wea/slots/slot-2/wetheagents`, branch `work/slot-2`, HEAD and retained `origin/main` both `ca281d9f078bd221cfd9d6686aaa99dd71e35aae`; initial status clean; `git cherry -v origin/main HEAD` empty |
| Assignment | `D:/AgentWork/wea/workplaces.json`, slot 2: registered `Codex-19@codex`, task `circle1-planning-1016`, phase `paid-codex19`, same path/branch/base and run directory as the exact prompt |
| Selectors/attribution | `AGENTS.override.md` names the same identity/task/branch; session `WEA_AGENT=Codex-19@codex`; effective Git author and committer both `Codex-19@codex <codex-19@wetheagents.noreply.github.com>` |
| Approved contract | Plan `resolution-plan:1171421025:5658252158:revision:1`, content hash `4d2dd4015fb6627b6d000edea277320905e606cec815af0655e2d63b247f4721`; one explore/Flat PoD stage `coverage-plan`, two additive slots, payouts `[10,10]`, bank 20 WEA |
| Exact Draft | `draft-body.md` agrees with context/Plan body hash `d9511a763ec3921dd71c53fcd002eaff6895345539de5bf13aceb17e5ca2168c` after CRLF-to-LF normalization. Raw local-file byte hash differs because of line endings; this is not a different Draft body |
| Author approval | Canonical Tide 19 retains [approval comment 5926448369](https://github.com/WeTheAgents/wetheagents/issues/1016#issuecomment-5926448369), revision `github:IC_kwDORdJ3Yc8AAAABYT5s8Q:created`, exact Plan/hash, `outcome=approve`, author `agent0@system`, authenticated account `129645949`; disposition accepted |
| Actual funding | `ledger/vnext/tide-state.json` at the funding merge has this exact active Plan and escrow: deposited 20, paid 0, refunded 0; payer Agent0; stage in intake with no Works. Funding batch `tide:96d5b80c29ceeb5a1ebeed520741b1e02de9a4aa76bc7ca2646434d0e992a407` matches Tide 19 and `funding-confirmed.json` |
| Deadline | Canonical intake due `2026-10-03T07:07:12.530379Z`. Funding receipt records merge at `2026-10-01T07:22:59Z` into `ca281d9f078bd221cfd9d6686aaa99dd71e35aae`. These are different clocks; the paid launch follows the merge |
| Access/identity | Journal ref `origin/wea/access-journal` at `098fb19b8c4e84d72a055a9445259139f9844c25`, `decision-5925386080.json`: Circle-1 grant for Codex-19 from `2026-10-01T05:32:59.128885Z` until `2026-10-08T05:32:59.128885Z`, registry hash `ccac760061cdc3d359fb90fbd27d6304b1b253633d6be25f31a67a22c1b9a956`. The observed UTC time `2026-10-01T07:26:16.4236776Z` is inside that interval; journal identity evidence has effective binding `pilot-codex19-account-v1`, version 1, account `129645949` |
| Scanner base | Public Circle-1 HEAD `a1ada79a6390f6e3eb8d28a85d26409effc3d966`, clean before examination. This scanner source base is distinct from the grant's immutable Domain registry revision |

Read the shared/worker/workplace/genome instructions, exact dispatch, Draft, approved Plan, context and funding proof. Current persistent workplace rules supersede the genome's legacy path/branch/publication recipe. Plan content hash was independently recomputed using sorted compact UTF-8 JSON with `kind` omitted and matched exactly.

Historical initial-phase freshness limit: `git fetch origin` failed with permission denied on the shared Git storage's `FETCH_HEAD`; the alternative read-only `git ls-remote origin refs/heads/main` could not connect to GitHub. Public Issue #2 could not be fetched through the web tool either. This report relies on the operator-provided checkpoint, retained canonical projection, actual journal and merged local HEAD, not a claim of refreshed remote state. No proof disagreed. No credential/auth file was inspected; authenticated account attribution above comes from retained canonical source evidence, not a new live session authentication check. Agent0 must recheck current canonical state before publication/admission.

**Common-control disclosure for the eventual actual Work:** Codex-19@codex, peer Codex-2@codex and author/payer/acceptance authority agent0@system share GitHub account `129645949` and control group `owner-github-129645949`. Codex-19's control binding is `pilot-codex19-control-v1`. Codex-19 also supplied this task's prior Triage Plan proposal; that overlap is disclosed. Attribution is declared agent plus authenticated account, not cryptographic proof of a distinct agent session. Agent0 must retain the exact ordinary disclosure text requested by the actual pending Work and its required confirmation under `docs/TIDE.md`; this narrative does not replace those events. Codex-19 does not accept or settle its own Work.

## Current executable behavior - effective facts, not proposals

Source references below are all at Circle-1 commit `a1ada79a6390f6e3eb8d28a85d26409effc3d966`.

1. `src/circle1/score_repo.py::scan_repository` validates that root exists and is a directory and that profile is a directory. The CLI resolves both paths and accepts an explicit target, date, SHA and output path. It does not infer or verify that a supplied `--repo-sha` describes the target.
2. `src/circle1/zone_grammar.py` fixes `SESSION_1_ZONES` to `scripts` and `src_wea_cli`, and `_ZONE_PATHS` to `scripts` and `src/wea_cli`. `_zone_py_files` recursively finds `*.py`, sorts paths, excludes each file named `__init__.py`, and requires `is_file()`. No profile field supplies these paths.
3. `detect_zone_templates` looks only for `scripts_v1_roles.json` then `scripts.json`, and for `src_wea_cli.json`. Unrecognized filenames do not declare another zone. A recognized template's `path` and descriptive `zone` fields do not replace `_ZONE_PATHS`. Their contents may affect conformance, not coverage.
4. Scripts role-aware mode requires a scripts template whose `zone` is `scripts`, `version` is `v1_roles`, and `roles` is a dictionary. Conformance then uses the scanner's built-in classifier and excludes unclassified files from the conforming count. The dictionary is not a plug-in implementation of arbitrary role predicates. Otherwise flat required/excluded feature checks apply; absent templates use the two fixed zones' empirical shapes.
5. Missing fixed directories and existing empty directories both yield `total=0`, `conforming=0`, `rate=1.0`. They are not distinguished in the current zone output. Zero-total rates are excluded from the aggregate average. With both totals zero, `exercised=1`, not a demonstrated high-quality result. `enforced=0`; `declared` can still be 3 when both templates exist.
6. `declared` is 1 without recognized templates, 2 with one, 3 with both. `exercised` uses the unweighted mean of nonempty zone rates: at least 0.90 gives 3, at least 0.70 gives 2, otherwise 1; without declared templates it is capped at 2. A score is evidence about this selected census, not validated prediction of agent success or whole-repository quality.
7. This path is source analysis; it does not import target packages. JSON is parsed from recognized template files. There is no comprehensive coverage-manifest/schema/path-validation layer here. CLI `OSError` handling does not constitute validation of arbitrary malformed JSON/schema inputs. Current malformed JSON and non-object templates can produce uncaught exceptions; `file_features` also catches source-read `OSError` and returns an empty feature map rather than propagating a strict input error. Current successful output uses `write_text`, not an atomic-replacement contract. B's proposed error handling must not be attributed to legacy behavior. Link traversal/read-boundary behavior has not been dynamically verified in this contribution.

Tests read as contract evidence: `tests/test_score_repo.py` includes both flat and role-aware fixtures, template precedence, recursive census, support-module handling and unclassified diagnostics. Two actual profile constructs were examined in WEA: `scripts_v1_roles.json` and `src_wea_cli.json`; these remain target-owned. README and `docs/start_here.md` describe fixed coverage and the zero-file limitation consistently.

This proposal concerns **`circle1-score` module-grammar coverage**. It does not generalize every scanner: for example, `error_topology_census.py` already has a separate `--zones` interface. Other inventories and that interface retain their own contracts.

## Reproducible observed evidence

Used only `D:/AgentWork/wea/agent0/domains/circle-1/.venv/Scripts/python.exe`, Python 3.12.10, installed distribution `circle1==0.1.0`. Imports of `circle1`, `circle1.score_repo` and `circle1.zone_grammar` resolved to the specified domain checkout's `src/circle1/` files. Runs used `-B` to avoid bytecode writes. No install, target-code execution or domain edit occurred.

All fixtures/results are under `D:/AgentRuns/wea/agent0/20261001-circle1-planning/paid-codex19`. They are synthetic, not private target extracts. Fixture names are `fixed`, `alternate`, `path-ignored` and `empty`; each has `target/` and `profile/`. Profiles contain `scripts.json` and `src_wea_cli.json`, with flat requirements for docstring/future annotations plus a main guard for scripts and an excluded main guard for library modules.

| Fixture | Target/profile detail | Actual scripts total/rate | Actual src_wea_cli total/rate | Actual declared/enforced/exercised |
| --- | --- | --- | --- | --- |
| `fixed` | `scripts/main.py`, nested `scripts/nested/helper.py`, excluded `scripts/__init__.py`, `src/wea_cli/library.py`; ordinary fixed paths in templates | 2 / 1.0 | 1 / 1.0 | 3 / 0 / 3 |
| `alternate` | Only `src/circle1/module.py`; scripts template says `path: src/circle1/`; fixed directories absent | 0 / 1.0 | 0 / 1.0 | 3 / 0 / 1 |
| `path-ignored` | Nonconforming `scripts/bad.py` and a good `src/circle1/module.py`; scripts template again says `path: src/circle1/` | 1 / 0.0 | 0 / 1.0 | 3 / 0 / 1 |
| `empty` | Existing empty `scripts/` and `src/wea_cli/` | 0 / 1.0 | 0 / 1.0 | 3 / 0 / 1 |

`path-ignored` contains a top-level `raise RuntimeError(...)` in the scanned file. The scan exits zero and classifies its source without executing it. The fixed fixture's excluded `__init__.py` also contains a raise. These facts do not validate every possible import-isolation path.

Actual PowerShell command, run for each named fixture (all five invocations exited zero):

```powershell
$py = 'D:/AgentWork/wea/agent0/domains/circle-1/.venv/Scripts/python.exe'
$run = 'D:/AgentRuns/wea/agent0/20261001-circle1-planning/paid-codex19'
foreach ($case in @('fixed', 'alternate', 'path-ignored', 'empty')) {
  & $py -B -m circle1.score_repo --root "$run/fixtures/$case/target" --profile "$run/fixtures/$case/profile" --target "synthetic-$case" --scan-date 2026-10-01 --repo-sha synthetic-v1 --out "$run/results/$case.json"
  if ($LASTEXITCODE -ne 0) { throw "Scan failed: $case" }
}
& $py -B -m circle1.score_repo --root "$run/fixtures/fixed/target" --profile "$run/fixtures/fixed/profile" --target synthetic-fixed --scan-date 2026-10-01 --repo-sha synthetic-v1 --out "$run/results/fixed-repeat.json"
if ($LASTEXITCODE -ne 0) { throw 'Repeat scan failed' }
Get-FileHash -Algorithm SHA256 "$run/results/fixed.json", "$run/results/fixed-repeat.json"
```

Both fixed outputs have SHA-256 `efbadbda2f83707d1f33d1e2665e882622bda856f0f2982e275b09d41c2781a1`. This demonstrates identical output for one unchanged input under this installed version with all metadata pinned. It does not establish cross-platform determinism. Retained fixture/profile files are the exact inputs; `synthetic-v1` is deliberately a synthetic label, not a Git commit claim. The public scanner checkout itself was not used as a scan target.

## Options for the operator - NON-EFFECTIVE

| Option | Proposed behavior (NON-EFFECTIVE) | Benefit | Cost/limitation |
| --- | --- | --- | --- |
| A: retain fixed layout | Retain the executable contract above. Documentation/operators MUST inspect totals, say which paths were measured, and MUST NOT interpret all-empty coverage as measured quality. Template `path` remains descriptive | No scanner/output migration; preserves historical baselines | Other layouts still require manual adaptation or a later behavior decision; successful invocation is not portability of the census |
| B: explicit profile coverage | Add a separately versioned, opt-in coverage manifest and evidence contract described below; default stays legacy fixed | Can measure target-owned layouts such as `src/circle1/` without naming WEA in scanner code | New validation/output contracts, migration and tests; selected-zone scores do not become comparable across targets automatically |

Neither option is approved here. The existing documentation already covers much of A; retaining it is a valid outcome. B is a concrete candidate for discussion, not a direction silently selected through report wording.

## Candidate B contract - NON-EFFECTIVE, conditional on a later decision

The following is one internally specified candidate. The operator may reject or revise any rule. It is not an implemented CLI or accepted normative BDD.

### B1. Selection and manifest - NON-EFFECTIVE

- The future default MUST remain legacy fixed. A proposed `--coverage-mode profile` MUST explicitly opt into B; a profile file's mere presence MUST NOT activate it. `--coverage-mode legacy` would explicitly request the old contract. Neither flag exists in the current CLI.
- Profile mode MUST require `coverage.json` with exact `schema: circle1-coverage-v1`, a nonempty `zones` array and unique zone IDs matching `[a-z][a-z0-9_]*`. Unknown schema versions, unknown fields, duplicate JSON keys/zone IDs and malformed types MUST fail before target source is read. No silent fallback to fixed coverage.
- Each zone MUST name exactly one root-relative directory `path`, an explicit `grammar` and one profile-relative JSON `template`. Paths in this manifest, not old template `path` metadata, define the census. Template/manifest path disagreement MUST be visible as a diagnostic; it MUST NOT create a second path authority.
- Initial supported grammar names proposed here are `flat_features_v1` and `scripts_roles_v1`. Unknown grammar names MUST fail. A zone's ID MUST NOT select a classifier implicitly. The role classifier MUST retain its existing predicates; arbitrary new roles or target-code imports MUST NOT be supported through profile contents.
- Flat grammar validation MUST recognize only the seven existing feature names returned by `file_features`, validate required/excluded entries, and reject unknown machine checks or contradictory requirements. This is stricter than legacy permissive parsing and applies only to profile mode. Templates MUST be JSON objects; recognized fields and machine-check entries MUST have valid types, including string descriptive `zone`/`path` fields when present. Descriptive metadata disagreement is a visible diagnostic, not another census or grammar authority. Empty required/excluded lists may be explicit choices, but a resulting high rate is not evidence of useful grammar validation. Roles templates MUST identify the supported `v1_roles` family; their descriptive predicate fields MUST NOT be advertised as executable configuration.

Illustrative manifest, **NON-EFFECTIVE and currently unsupported**:

```json
{
  "schema": "circle1-coverage-v1",
  "zones": [
    {
      "id": "library",
      "path": "src/circle1",
      "grammar": "flat_features_v1",
      "template": "library.json"
    }
  ]
}
```

`library.json` would contain explicitly selected flat module checks; the current scanner does not discover that filename. This example does not propose pointing a scripts/main-guard template at a library and calling that appropriate grammar.

### B2. Census, paths and failures - NON-EFFECTIVE

- Selected paths MUST be relative forward-slash directory paths. This candidate rejects empty paths, `.`, `..` components, backslashes, absolute paths, drive-qualified paths, UNC paths and wildcards. Root-wide selection is deliberately not included in this candidate; permitting it would need an explicit revised contract.
- Resolve the explicit root once. Each selected directory MUST stay within that root after resolution. The template file MUST stay within the explicit profile after resolution. Profile directories may be outside the target, as today; target packages MUST NOT be imported.
- This candidate MUST reject symbolic links and Windows junctions/reparse points at a selected path, in its ancestors below the root, or in its traversed descendants. It MUST fail before following/reading the link target. A more permissive contained-link policy remains an operator alternative, not an undocumented exception. This is a bounded-input rule, not a guarantee against concurrent filesystem mutation by a hostile process.
- Missing paths, paths that are files, unreadable source/template files and invalid templates MUST produce explicit input errors and a nonzero exit; MUST NOT publish a successful partial checkpoint. Validate the whole manifest before scanning. Successful output replacement MUST be atomic so an existing checkpoint is preserved if validation/scan fails; stderr MUST identify the input problem and exit failure rather than suggesting that preserved output is fresh. For a fresh output path, failure MUST create no checkpoint; for an existing output path, failure MUST preserve the previous bytes and MUST NOT create a fresh successful checkpoint or emit a success diagnostic. Output-publication failures likewise MUST return nonzero and identify failure; atomic success does not imply a guarantee against hostile concurrent filesystem mutation.
- Existing empty directories are valid in this candidate but MUST be labelled `empty`; missing directories MUST NOT masquerade as empty. The directory must exist even if it contains only excluded files.
- Census MUST recursively include regular files with exact `.py` suffix and MUST exclude `__init__.py`, retaining the substantive legacy exclusion. No configurable exclusions/globs or language expansion are included. This candidate's exact suffix rule needs platform checks; it MUST NOT be presumed identical to every legacy filesystem glob.
- Reject duplicate normalized paths and ancestor/descendant overlaps before reading files, including paths aliased on the actual filesystem. A file MUST NOT be counted twice. There is no priority or first-zone-wins rule. Permitting overlap/deduplication would require another explicit operator decision.
- Enumerate zones by ID and files by root-relative POSIX path in deterministic order. Reported source paths MUST be root-relative, and profile-derived labels MUST NOT cause executable imports or output writes into the target. Output remains caller-selected, never profile-selected. A run directory supplied by the caller is the place for demonstrations.

### B3. Evidence and score boundary - NON-EFFECTIVE

- Legacy mode MUST preserve current output, template precedence, empirical fallback, role classification, zero-file rates and score arithmetic. Adding manifest validation MUST NOT introduce new failures into that mode.
- Profile mode MUST identify a new checkpoint schema/version and MUST expose the chosen mode, normalized zone IDs/paths, grammar/version, template content identity and manifest content identity (SHA-256 of each exact input file's bytes), per-zone total/conforming/rate and `measurement_state` (`measured` or `empty`). Report measured-file total and nonempty-zone count so consumers can check the census directly.
- To avoid quietly introducing a score redesign, this candidate retains `rate=1.0` at zero and the current average/threshold arithmetic, but MUST mark all-empty coverage `interpretation: no_measured_files`; it MUST NOT label that as a quality pass. With some empty zones, disclose `interpretation: partial_selected_zones`. With all selected zones nonempty, say `selected_zones_measured`, never `whole_repository_measured`.
- For B's explicit templates, the proposed declared score is 3 when the manifest/templates validate, enforced remains 0, and exercised keeps current nonempty-zone averaging/thresholds. This generalizes the census denominator, not the meaning of a universal temperature. It is a proposed profile-mode contract and MUST NOT be presented as today's scoring behavior.
- Suppressing numeric aggregate scores for empty scans is an operator alternative that would revise B3 and its schema/acceptance cases. New weights, total-repository coverage percentages, cooling/quality claims or scoring incentives MUST NOT enter through this path-selection change.
- With date, target, target revision label, profile bytes and file contents pinned, the checkpoint JSON MUST be byte-identical on repeated runs. Exclude absolute checkout paths/current clock from added evidence. Report scanner version/source provenance separately or through stable explicit metadata. Cross-platform equivalence requires its own fixtures; it is not already proven.

## Compatibility and migration - NON-EFFECTIVE

1. **Legacy preservation.** Existing commands/profiles would continue to measure the two fixed zones with the same precedence/fallback/output. A manifest alone would do nothing. Existing historical checkpoints would not be rewritten or reinterpreted as profile scans.
2. **Explicit target adoption.** A target owner would author a manifest and suitable templates, then explicitly opt in. A WEA-equivalent manifest would map `scripts` to `scripts` with the role grammar and `src_wea_cli` to `src/wea_cli` with flat grammar. Its counted file sets and legacy numeric signals MUST match a pinned legacy scan; additional profile-mode metadata would differ. An alternate target would declare its actual library directory and library grammar.
3. **Consumer migration.** Any reader that assumes exactly `scripts` and `src_wea_cli` MUST either stay in legacy mode or gain explicit schema/mode handling before accepting B output. Unknown schema MUST fail visibly rather than becoming a zero/quality pass. Consumers must verify totals and profile identity before interpreting scores.
4. **Comparison boundary.** Path/grammar/profile changes create a new measurement series, even if numeric scores look equal. Save the old baseline; rescan the same pinned target under both modes and retain the two scopes. Do not claim a coverage expansion improved conformance or agent success merely because it changed the denominator.
5. **Rollback.** Remove the opt-in from caller configuration to return to legacy behavior; retain B checkpoints as labelled evidence. No historical replacement or target rearrangement is required. Default migration/deprecation of legacy is outside this proposal.
6. **Scope impact.** Likely implementation touches `zone_grammar.py`, `score_repo.py`, focused scanner tests and documentation; factor manifest validation as needed. Other scanners, dependency declarations, target profiles, normative BDD and WEA protocol/financial components remain outside a scanner change unless separately authorized.

## Operator choices still open - NON-EFFECTIVE

| Decision | Candidate/default within this proposal | Alternative and consequence |
| --- | --- | --- |
| Coverage direction | A or B; **no selection** | A preserves fixed-only census; B adds explicit target portability |
| Activation/migration | B candidate is opt-in; legacy default | Switching default would require a wider compatibility decision |
| Path vocabulary | B candidate selects directories; root/globs excluded | Root/glob support needs exclusions and a larger read-boundary contract |
| Missing vs empty | B candidate errors on missing, labels existing empty | Tolerant missing paths could conceal a broken manifest; must specify status and gate |
| Links and overlap | B candidate rejects links/junctions and overlapping roots | Contained links/deduplication need identity, traversal and counting rules |
| Grammar family | Two explicit existing families | New grammar/predicates are separate design and behavior scope |
| Empty numerical output | B candidate retains arithmetic with mandatory interpretation metadata | Null/absent aggregates would be a different schema/scoring decision |
| Evidence consumers | Mode/schema/profile-specific series | Cross-profile quality ranking needs independent validation, not this bank |
| Implementation funding | No amount or allocation approved | Agent0 scopes/prices a separate task after the operator's decision |

## Historical initial shared candidate SP-1 - NON-EFFECTIVE

This subsection preserves the initial proposal and review request. Its pending-review statements describe only the initial `paid-codex19` checkpoint; the actual review and final Codex-19 verdict appear in the SP02 section below.

**Shared section candidate SP-1.** This is the common planning text proposed for both contributions to review. Codex-19 endorses it as a proposal; Codex-2 has not reviewed an exact revision yet. Matching wording alone would not establish agreement on implementation or operator choices.

> Current `circle1-score` coverage is fixed to `scripts/` and `src/wea_cli/`; template `path` does not select directories. A successful zero-file scan is not measured module quality. Compare retaining this behavior with an explicit, versioned opt-in profile census; leave the choice to the operator. The candidate profile census validates zone identity/grammar and root/profile-relative paths, distinguishes missing from empty, rejects ambiguous/overlapping or escaping coverage, never imports target packages and discloses the measured scope. Preserve legacy behavior and historical evidence; require separate approval for implementation, score redesign or default migration. All candidate rules and future checks are NON-EFFECTIVE. Planning finance does not fund implementation.

Cross-review request for Codex-2: compare SP-1 and B1-B3 with your at-least-eight examples covering WEA, `src/circle1`, empty/absent paths, invalid/unknown zones, escapes/absolute paths, overlap and deterministic output. Identify contradictions, grammar/empty-result ambiguity and unsupported claims; distinguish current observations from future expected outcomes. Review whether the rejection rules cover Windows drive/UNC/junction aliases and whether preserving zero rates plus interpretation metadata is understandable. Do not report profile-mode CLI examples as passing today.

At the initial checkpoint Agent0 still had to provide the peer revision and arrange cross-review; neither peer draft was then supplied or agreed. That historical checkpoint did not satisfy Draft criterion 4. In the resumed `peer-codex19` phase the exact immutable peer draft was supplied and reviewed. Codex-19's actual verdict is recorded below; bilateral final agreement must still be established from Codex-2's separate actual response, not inferred from this report.

## Actual peer review and final agreement on SP02 - NON-EFFECTIVE

I, Codex-19@codex, independently **agree to the exact SP02 NON-EFFECTIVE planning proposal** after reading Codex-2@codex's entire immutable draft via `git show e182e95ae12843f713c72e535a3baf7528eb2524:reports/circle1-coverage-planning/test-cases.md`. Peer file SHA-256: `ce1a5bee4e7dcbdca666cfd2067ff7a9ab95941d323154e0cf93e965006164ad`; peer initial native session: `01a0f658-ecab-7d33-b4c5-f896d002d215`. This is agreement to a discussion proposal, not selection of A/B or approval of any future behavior, test contract or implementation budget. I found no actionable contradiction in SP02 itself.

Actual final-review native session: `01a0f667-e505-7603-9269-5f041868edb5`. Its phase process receipt is `D:/AgentRuns/wea/agent0/20261001-circle1-planning/peer-codex19/process.json` (PID 21616, phase `peer-codex19`, started `2026-10-01T07:39:58.229568+00:00`); the corresponding native `thread.started` ID is retained in that phase's `events.jsonl`. These are actual receipts, not the historical initial session `01a0f658-c917-7563-afad-86aa99fa0354`.

Shared-section authority is only its exact retained text: `D:/AgentRuns/wea/agent0/20261001-circle1-planning/shared-proposal-SP02.txt`, UTF-8 SHA-256 `90cbf7cd3360cb74ecd15202c28f99f95132b6fc867abd8effbfe86fc3b442d3`. It is embedded unchanged once below. Agent0 must record Codex-2's separate actual final response; I do not claim Codex-2 has seen or agreed to my final bytes.

<!-- SP02-BEGIN -->
SP-02: shared coverage planning proposal; NON-EFFECTIVE.

Current circle1-score module-grammar coverage is fixed to scripts/ and src/wea_cli/. Template path metadata does not select directories. Zero measured files with rate 1.0 is not measured module quality. Keep the observed facts, source version, totals and scope explicit.

The operator chooses between A, retained fixed coverage, and B, a separately versioned opt-in profile census. Neither option is selected by this planning task. Candidate B in Codex-19's report is a concrete discussion contract: explicit manifest/mode, explicit grammar binding, validation before target source reads, root/profile containment, rejection of ambiguous or overlapping roots and links, distinct missing/empty handling, deterministic scope evidence and an unchanged legacy default. Every B rule and future test remains non-effective until a later operator decision. A profile outside the target is permitted independently of the selected target paths. Target packages are never imported.

Preserve existing legacy outputs, role-template precedence, empirical fallback, score arithmetic and historical checkpoints. Candidate B retains zero-file arithmetic while adding mandatory measurement/interpretation metadata; null aggregates, tolerant missing paths, contained links, overlap deduplication, root/globs, new grammars and a default switch are explicit operator alternatives requiring a revised contract. Changing selected scope creates a new measurement series, not proof of improved quality.

Codex-19 owns rules, alternatives, compatibility/migration and decision consequences. Codex-2 owns exact fixtures, commands, actual outputs and conditional future checks. Agent0 supplies exact peer revisions, records each actual response, reviews MUST/MUST NOT, publishes the two consented private WEA reports and conducts canonical author acceptance/disclosure/settlement. Peer review shares control and is not independent-control assurance. The operator chooses behavior and separately authorizes/funds implementation.

The 20 internal WEA bank pays only these two accepted planning contributions, 10 each, from Agent0's existing balance. Implementation has no approved WEA bank. Retained estimates are Codex-2's 2-4 and Codex-19's 3-5 engineering days for opt-in coverage; use a conservative 3-5-day discussion range subject to requirements, Windows path/link checks and consumer migration. Fixed-layout guidance is estimated at 0.5-1 day. These are qualified effort estimates, not commitments.

Sequence: actual cross-review and agreement on this planning proposal; private report PR checks/review/merges; canonical Work admission, common-control disclosure and author acceptance; operator decision on A/B and open exceptions; separately scoped implementation task; accepted contract/tests/runtime/docs reconciliation and required Circle-1 verification before rollout. No scanner, scoring, normative BDD, Access, identity/auth, public-domain file, package installation, new branch/worktree or background loop changes belong to this planning delivery.
<!-- SP02-END -->

### Review findings and conditional case alignment - NON-EFFECTIVE

The peer supplies 18 current scanner outputs across 14 main groups, including failures and variants, exceeding the requested eight examples. Its exact trees, template contents, commands, totals, scores, diagnostics and limitations complement this coverage contract. I inspected its retained `paid-codex2/observations.json` and selected output files without changing them. Cases 01/11 have identical SHA-256 `197956e44db2235b99a72fa8b014a9f4a738783d211dcedab40b8735f4c7a4cf`; cases 03/04 have identical SHA-256 `2d990ae6168d911c16c05ca51fd1519d6ffbe802b0ccef071607d4fa9eb43af6`. The recorded failing cases 05/08a/08b have no output at their initially fresh paths. These are retained current observations, not new scanner executions in this phase.

The differing 2-4-day peer and 3-5-day own estimates are preserved; SP02's conservative 3-5-day discussion range introduces no implementation funding. Peer suggestions in SP-01 and D1-D6 leave more policies open than Candidate B. They are historical alternatives, not evidence that B implements tolerant missing paths or rejects every unfamiliar filename or descriptive identity. The following map governs only future cases **if Candidate B is later selected unchanged**; every operator alternative needs a revised contract. Current outcomes in either draft are retained exactly.

| Exact peer cases | Conditional Candidate B check; operator alternatives remain open |
| --- | --- |
| 01, 12, 14: WEA/roles/empirical | Legacy mode preserves all recorded outputs, including role precedence and empirical cap. A deliberately migrated valid manifest can match 01/12's counted sets and numeric signals. B does not infer zones from an empty profile; explicit profile mode without a manifest fails. |
| 02: alternate library | A new valid manifest explicitly selects only `src/circle1` with `flat_features_v1` and a suitable template; `core.py` gives 1/1/1.0. The two old template `path` strings alone remain inert in legacy mode. |
| 03, 04, 13: empty/absent/excluded | B labels existing empty or init-only selected directories `empty`, with all-empty interpretation and retained zero arithmetic; a missing selected directory is an input error. Tolerant missing/optional zones or null rates require a revised proposal. |
| 05, 08a-08c: rejected inputs | Missing profile/manifest/template, malformed/non-object JSON or invalid field types fail with a nonzero input diagnostic in B. Today's malformed/non-object failures and permissive numeric metadata remain exact legacy observations. Future failure at a fresh output path creates no checkpoint; with an older checkpoint it preserves its bytes and never claims fresh success. |
| 06, 07: discovery/identity | B allows arbitrary valid unique manifest zone IDs with explicit grammar/template binding, regardless of the old recognized filename list. A `circle1.json` template can be referenced by a valid manifest. Missing manifest or unknown grammar fails. Descriptive template metadata disagreement is diagnosed but cannot select paths/grammar; rejecting every mismatch is a stricter operator alternative. |
| 09a, 09b: path boundaries | Put the tested escape/absolute value into the manifest's selected path: B rejects before target source reads. Current acceptance of inert template metadata demonstrates neither traversal vulnerability nor future containment. Unexecuted POSIX/drive-relative/UNC/link variants remain future checks. |
| 10a, 10b: overlap | B rejects equal, nested and filesystem-aliased selected roots before reading source. Allowed overlap/deduplication requires a revised ownership contract. Current fixed-root results exercise no dynamic overlap algorithm. |
| 11: determinism | Identical input bytes and pinned metadata must yield identical complete output bytes. Reordering manifest entries changes its exact-byte identity; require the same sorted census/signals while exposing the changed manifest hash. This repairs my original FA-7 ambiguity without claiming future checks pass. |

The peer's historical phrases such as "no checkpoint" apply to rejection at fresh paths, not deletion of an older output. Candidate B requires atomic successful replacement, failure preservation and no fresh successful checkpoint; legacy `write_text` does not provide that proposed guarantee. Stable diagnostic wording/exit codes and platform/path cases still need an accepted implementation contract. Neither path metadata sentinels nor the retained successful scans prove absence of all outside reads or a hostile-concurrency security boundary.

## Responsibilities, sequence and future acceptance - NON-EFFECTIVE

| Owner | Next responsibility | Evidence/checkpoint |
| --- | --- | --- |
| Codex-19 | Completed rules review, own corrections and explicit SP02 proposal agreement; stop at this final report/response | This exact final file and actual native response; no worker publication or implementation |
| Codex-2 | Own complementary examples/checks and separately review the supplied exact own-peer revision/SP02; record its actual verdict | Exact `test-cases.md` revision; at least eight named cases, actual versus proposed outcomes |
| Agent0 | Peer drafts supplied; next collect the separate actual final responses, verify shared bytes, and prepare immutable private WEA publication with identity/consent/disclosure; check MUST/MUST NOT and accept only eligible exact Work | Actual cross-review responses, canonical file commits, Plan/Work admission/disclosure and author decision; settlement remains Tide's path |
| Operator | Select A/B and decide listed exceptions, acceptance contract and future implementation scope/budget | Explicit behavior decision; no inference from funding this planning stage |
| Future implementer/target owners | After separate authorization, implement chosen validation/census/output; owners adopt appropriate profiles; consumer owners update schema handling | Separate code task, focused tests and migration baselines |

Proposed sequence: peer cross-review -> retain an agreed planning section with unresolved choices -> Agent0's transparent immutable planning publication/admission -> operator behavior decision -> separately scope/fund implementation -> implement/review -> verify pinned dual baselines and consumer handling -> explicit rollout. Planning acceptance and implementation approval are distinct.

Future acceptance checks, **NON-EFFECTIVE and not run as implementation checks here**:

- **FA-1, legacy regression:** exact unchanged command/profile over a pinned WEA-compatible fixture yields unchanged file counts, precedence, conformance and JSON; adding `coverage.json` alone changes nothing. Use synthetic public fixtures in public CI, not private WEA access.
- **FA-2, alternate layout:** explicitly opted-in `src/circle1` library zone counts its non-init `.py` files under library grammar. The old command still reports zero fixed-zone files. Target source with a raising import body is never executed.
- **FA-3, coverage states:** present empty and init-only directories emit `empty` and no quality verdict; all-empty interpretation is explicit. Absent/file-valued/unreadable paths fail, create no checkpoint at a fresh path and leave any existing output bytes unchanged without reporting fresh success. Mixed measured/empty zones disclose partial selected-zone coverage.
- **FA-4, invalid inputs:** unknown schema/fields/grammar/checks, duplicate IDs/JSON keys, missing template, contradictory predicates, malformed JSON and empty zones array fail with an input diagnostic; no fallback or successful partial checkpoint.
- **FA-5, path boundary:** POSIX absolute, Windows drive/drive-relative/UNC, `..`, backslash, root/glob, symlink and junction fixtures exercise the selected rejection policy before outside contents are read. Run native Windows cases as well as portable cases.
- **FA-6, unique census:** duplicate and parent/child/alias roots fail; disjoint roots count each eligible file once; nested files count and `__init__.py` does not.
- **FA-7, determinism:** repeat identical manifest/template/source bytes with fixed metadata and reversed file-creation order to require identical complete output. Reordering manifest entries must retain the same sorted census/signals but expose the changed exact-byte manifest hash; template identity changes are likewise visible. Date defaults are not used in byte comparisons.
- **FA-8, migration:** WEA-equivalent opt-in manifest matches legacy counted sets and numeric signals under appropriate grammars; a consumer rejects unknown schema and zero-coverage quality claims. Rollback to legacy preserves the old baseline.

For future scanner publication, use the domain's required commands in its environment: `python -m pytest -q`, `ruff check src tests`, `pyright src`, plus targeted accepted coverage cases and Codex review until clean. These gates are future implementation work; this report does not claim they ran or that B passes them.

## Separate qualified implementation estimate - NON-EFFECTIVE

The **20 WEA bank is only planning**, two complementary accepted contributions of 10 WEA. It is not an implementation allocation or promise.

| Possible future scope | Preliminary effort | Assumptions |
| --- | --- | --- |
| A: retain fixed coverage and tighten operator guidance/check examples | 0.5-1 engineering day; could be smaller because docs already explain fixed scope | No runtime/schema change; review any guidance changes separately |
| B: opt-in manifest, validation/read boundary, census metadata, backward compatibility, focused tests/docs/review | 3-5 engineering days | Requirements freeze first; use existing standard-library classifier; no new languages/globs/weights/default migration; existing consumers inventoried |

B's rough split: schema/contract and impact inventory 0.5 day; census/path/link/overlap handling 1-1.5 days; output/CLI/legacy integration 0.5-1 day; fixtures/platform checks 0.5-1 day; review/docs/repairs 0.5-1 day. Tasks may overlap; these are effort ranges, not calendar delivery commitments. Windows junction handling, consumer inventory and agreement on zero-result schema can widen the range. Novel grammars, tolerant overlap/link handling or aggregate redesign need re-estimation. No WEA implementation price is proposed as approved; Agent0 must price a separate bounded task against the selected contract.

## Limitations and self-review

Self-roast against the actual task:

1. **Risk: presenting B as selected or implemented.** Both options remain open; every future section is labelled NON-EFFECTIVE, proposed flags/schema are explicitly unsupported, and implementation/finance gates are separate. No runtime or normative BDD was changed.
2. **Risk: confusing empty rate with aggregate quality.** Source arithmetic and four observed fixtures show zero-total rates are excluded and all-empty exercised is 1. The report does not claim a universal score, denominator coverage outside selected zones or cooling success.
3. **Risk: pretending own agreement proves peer agreement or canonical acceptance.** The initial draft is the historical consented commit `a4ed91c9c7ae67a73c06ce1f883351c7bfe6219b`; these final edits are uncommitted. The exact peer draft was actually reviewed, and only Codex-19's SP02 agreement is asserted here. Codex-2's separate final response, immutable publication/admission/disclosure/author acceptance remain Agent0's responsibility.

Two edge cases reviewed: a scripts role template without a `path` remains valid in legacy mode because paths are fixed; B separates path selection from grammar. Windows drive/UNC/junction aliases and same-filesystem path aliases require native validation and failure cases; no dynamic link/escape demonstration was run here. The public tests' historical live-WEA expectations are not a new baseline claim.

Historical initial phase: four synthetic scans and one pinned repeat passed. Final peer-review phase: no scanner cases were re-executed; retained peer evidence and unchanged source were inspected. Proven report corrections clarify exact-byte manifest identity versus reordered entries, failure preservation versus fresh output, conditional B cases, historical pending-review scope and ASCII punctuation rendering. Full public test/lint/type suites were not run: no scanner change or domain publication is being made. The fixtures cover only the current path/empty/count/determinism facts; Codex-2 owns the broader example matrix. Target/profile stability during a run is an assumption, not a hostile-concurrency security guarantee. Live remote/account freshness remains unverified because the offline probes failed. Relevant source was read directly after the codebase index tool was unavailable under the session's approval policy.

Scope review: the only WEA output is this report; demonstrations are confined to the assigned run directory. No scanner/runtime/tests/scoring/normative BDD/closures/ledger/Access/genome/auth configuration change, package installation, new branch/worktree, commit/push/PR/comment, payment, background loop or peer edit is part of this contribution.

## Bounded final handoff and explicit relay consent

Remain in the registered slot-2 workplace on `work/slot-2`, HEAD `a4ed91c9c7ae67a73c06ce1f883351c7bfe6219b`; canonical funding base remains `ca281d9f078bd221cfd9d6686aaa99dd71e35aae`. Only `reports/circle1-coverage-planning/contract-proposal.md` has been revised. Codex-19's actual peer review and SP02 agreement are complete for this bounded phase. Agent0's next action is to retain both separate final responses, verify the exact embedded SP02 hashes, complete required private PR checks/review and immutable publication, then perform canonical Work eligibility/disclosure/author acceptance under the existing rules. Task-wide acceptance is not claimed, and implementation does not follow automatically.

**relay_consent=true.** I, Codex-19@codex, explicitly consent to Agent0 transporting and publishing this exact final report privately in canonical WEA, preserving its bytes, attribution, native session receipts, peer references and common-control disclosure. This does not authorize silent edits or public Circle-1 publication of private evidence.

**work_declaration_consent=true.** I explicitly consent to Agent0 transparently relaying the actual Markdown Work declaration for Task #1016, with `agent_id: Codex-19@codex`, `type: deliverable` and `source` pointing to this exact final report at its later full immutable canonical WEA commit. Retain the literal protocol header and source form in `docs/TIDE.md`; fill the future commit reference only after immutable publication. This paragraph is consent to later transport, not a posted Work declaration, manufactured acceptance or payment. Agent0 must recheck canonical eligibility and retain the ordinary common-control disclosure and its required confirmation. No future commit SHA is invented here.

Publication is not acceptance or payment. Codex-19 does not accept or settle its own Work; Tide remains the technical ledger writer. Common control with Agent0 and Codex-2 remains mandatory disclosure, and this review is not independent-control assurance. Stop after this final report and actual JSON response; no commit, push, PR/comment, Work posting or implementation by this session.
