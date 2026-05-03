# Circle-1 CRAP/Observability Risk Report

- scan_date: 2026-05-02
- repo_sha: d372a32
- harness_version: v0
- functions_scanned: 1548
- coverage_unknown: 1548
- coverage_known: 0

## Top Risk Functions

| risk | path | symbol | lines | complexity | coverage | CRAP | channels | tracking |
|---|---|---|---:|---:|---:|---:|---|---|
| critical | scripts/process_pending.py | process | 110-547 | 74 | unknown |  | file_artifact_write, ledger_or_protocol_write_candidate, stdout_cli_output, unknown_ambiguous_side_effect | new |
| critical | scripts/tide.py | TideProcessor._task_create | 367-519 | 37 | unknown |  | github_comment_side_effect_candidate | new |
| critical | scripts/tide.py | TideProcessor._accept | 623-738 | 34 | unknown |  | github_comment_side_effect_candidate | new |
| critical | scripts/tide.py | run | 1096-1255 | 32 | unknown |  | file_artifact_write, ledger_or_protocol_write_candidate, stderr_output, stdout_cli_output, subprocess_launch, unknown_ambiguous_side_effect | new |
| critical | scripts/auto_triage.py | triage | 146-233 | 20 | unknown |  | github_comment_side_effect_candidate, stderr_output, stdout_cli_output | new |
| critical | scripts/tide.py | TideProcessor._ranking | 768-834 | 18 | unknown |  | github_comment_side_effect_candidate | new |
| critical | scripts/genome_snapshot.py | _git_diff_stats | 144-199 | 16 | unknown |  | subprocess_launch | new |
| critical | scripts/claim_fast.py | main | 62-155 | 15 | unknown |  | github_comment_side_effect_candidate, stderr_output, stdout_cli_output | new |
| high | src/wea_cli/cli.py | cmd_rename | 1970-2159 | 71 | unknown |  | - | new |
| high | scripts/check_escrow_lifecycle_integrity.py | run_check | 164-404 | 67 | unknown |  | - | new |
| high | scripts/check_task_format.py | validate_detailed | 193-483 | 63 | unknown |  | - | new |
| high | scripts/check_history_event_type_schema.py | _check_event | 82-204 | 58 | unknown |  | - | new |
| high | scripts/check_history_escrow_solvency.py | replay | 170-333 | 47 | unknown |  | - | new |
| high | scripts/check_history_balance_flow.py | replay | 98-246 | 46 | unknown |  | - | new |
| high | scripts/check_invariant.py | main | 30-321 | 45 | unknown |  | stdout_cli_output | new |
| high | src/wea_cli/report_snapshot.py | build_inbox | 154-276 | 41 | unknown |  | - | new |
| high | scripts/check_history_cumulative_balance_integrity.py | replay | 183-323 | 39 | unknown |  | - | new |
| high | scripts/check_ledger_schema.py | validate_achievements | 122-203 | 39 | unknown |  | - | new |
| high | scripts/pipeline_parser.py | aggregate_results | 270-360 | 39 | unknown |  | - | new |
| high | scripts/check_balance_history_reconciliation.py | compute_balances_from_history | 89-177 | 36 | unknown |  | - | new |

## Review Use

- Prioritize high-complexity functions where coverage is unknown and side-effect channels touch ledger, GitHub, subprocess, network, or file artifacts.
- Treat missing coverage as unknown evidence, not as zero or full coverage.
- Update tracking fields only when later review findings, bugs, redteam notes, test additions, or hardening tasks provide evidence.

## Limitations

- Complexity is AST McCabe-like static complexity, not runtime path proof.
- Coverage is line evidence mapped to function ranges; branch coverage is not inferred.
- Coverage is only known when an explicit JSON/XML artifact is supplied and matches the scanned file.
- Observability annotations for scripts/ are joined by evidence line range and may miss wrapper side effects.
- The harness is a review prioritization aid, not a CI gate or automatic PR verdict.
