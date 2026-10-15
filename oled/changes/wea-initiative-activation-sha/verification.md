# Verification

Decision: Not ready for protected merge, installation, or live activation.
Implementation and local checks are complete. Final review/publication checks remain pending at this checkpoint.
Accepted contract: Outcome 1, Spec 1, Design 1.
Original defect reproduced independently with identical 161-file manifests and incompatible SHA predicates.
Evidence, 2026-10-15:

- `python -B -m pytest -q -p no:cacheprovider tests/vnext/test_initiative_activation_replay.py tests/vnext/test_initiatives.py`: 76 passed.
- The retained nine-file Access/Domain/activation/scenario regression invocation: 230 passed, exit 0. These groups overlap.
- Scoped Ruff lint/format, documentation sync and diff whitespace checks: pass.
- Offline replay of real journal `8f13cb9ca499685267841ce1011a237039db7ade`: 11 records, four grants, identical baseline/candidate state hash.
- State SHA-256: `c8a39546a567a69881ee1f09a2b7529b5747e9e2a79e57f4b7719db91521efb2`.

| Contract | Actual proving surface |
| --- | --- |
| AS-01 | `test_new_main_activation_and_exact_retry`, `test_trusted_run_retains_both_shas_and_exact_checked_manifest` |
| AS-02 | 23 pure independent mutations, trusted-boundary and failed-read parameter cases, nonoperator and edited-source tests |
| AS-03 | `test_historical_prefix_survives_versioned_package`, canonical retry test, existing protocol-transition and initiative prefix/race tests |

An independent review found no actionable code/contract defects at this checkpoint.
Its broad run hit a Windows temporary-directory ACL error before one test executed.
That exact metadata/prefix case passed independently with a writable temporary directory.
Final fresh-context and required post-publication native reviews remain pending.

Scope: three production files, existing activation negative-test repair, two new test files and contract/installation records.
No runtime dependency, financial ruleset, workflow permission, journal record or released executor changed.
Protected cut pass: existing source/dispatch/journal paths are reused. No safe cut removes further code without weakening history or evidence checks.
The capability marker preserves old rejected records and stays part of the complete package identity.

Known separate limitation: existing receipt formatting can duplicate a text comment on retry.
Canonical journal objects and state remain unchanged. This patch does not change receipt formatting.

Local detailed receipts remain in the task evidence directory under `activation-repair-*` and `retained-access-replay-*`.
The public PR retains exact-head review/CI disposition before any future operator installation decision.
Simple English self-check: normative text uses explicit conditions, MUST outcomes, short active sentences and consistent identifiers.
Historical scenario registry remains accepted-future. No live BDD transition is claimed.
