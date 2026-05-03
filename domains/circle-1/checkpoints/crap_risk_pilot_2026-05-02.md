# Circle-1 CRAP Risk Pilot

- scan_date: 2026-05-02
- harness_version: v0
- scanned_files: 174
- functions_seen: 1552
- coverage_states: known=0, unknown=1552, not_applicable=0
- risk_bands: critical=183, high=174, medium=497, low=698

## Top Risk Functions

> **WARNING: no coverage artifact was supplied. Coverage is unknown, and blank CRAP cells mean CRAP was not computed; they are not zero or low-risk scores.**

| rank | path | symbol | complexity | coverage | CRAP | side effects | risk |
|---:|---|---|---:|---|---:|---|---|
| 1 | scripts/process_pending.py:110 | process | 75 | unknown |  | file_artifact_write, ledger_or_protocol_write_candidate, stdout_cli_output, unknown_ambiguous_side_effect | critical |
| 2 | src/wea_cli/cli.py:1970 | cmd_rename | 71 | unknown |  | none | critical |
| 3 | scripts/check_task_format.py:193 | validate_detailed | 63 | unknown |  | none | critical |
| 4 | scripts/check_escrow_lifecycle_integrity.py:164 | run_check | 62 | unknown |  | none | critical |
| 5 | scripts/check_history_event_type_schema.py:82 | _check_event | 58 | unknown |  | none | critical |
| 6 | scripts/check_history_escrow_solvency.py:170 | replay | 47 | unknown |  | none | critical |
| 7 | scripts/check_invariant.py:30 | main | 45 | unknown |  | stdout_cli_output | critical |
| 8 | scripts/check_history_balance_flow.py:98 | replay | 46 | unknown |  | none | critical |
| 9 | scripts/tide.py:367 | TideProcessor._task_create | 37 | unknown |  | github_comment_side_effect_candidate | critical |
| 10 | scripts/tide.py:623 | TideProcessor._accept | 34 | unknown |  | github_comment_side_effect_candidate | critical |
| 11 | src/wea_cli/report_snapshot.py:154 | build_inbox | 41 | unknown |  | none | critical |
| 12 | scripts/tide.py:1096 | run | 32 | unknown |  | file_artifact_write, ledger_or_protocol_write_candidate, stderr_output, stdout_cli_output, subprocess_launch, unknown_ambiguous_side_effect | critical |
| 13 | scripts/check_history_cumulative_balance_integrity.py:183 | replay | 39 | unknown |  | none | critical |
| 14 | scripts/check_ledger_schema.py:122 | validate_achievements | 39 | unknown |  | none | critical |
| 15 | scripts/pipeline_parser.py:270 | aggregate_results | 39 | unknown |  | none | critical |

Compact JSON preview: 25 functions in `compact_functions`; 1527 lower-priority functions omitted from that preview. The canonical `functions` array remains complete.

## Tracking

Future sweeps update `tracking_status`, `tracking_notes`, and `evidence_refs` when a watched function later correlates with a review finding, bug fix, redteam note, hardening task, or test addition.
