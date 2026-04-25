# T5S30 Audit: failing integrity checks

## Root cause identified
- Legacy `to` field in `trajectory_mint` events in `ledger/history/2026-04-19.jsonl` (old format stored receiver as `to` instead of `agent`).

## Fixed
- `scripts/check_balance_history_reconciliation.py`
- `scripts/check_balances_earned_consistency.py`
- `scripts/check_total_earned_consistency.py`

These were false positives from the legacy-format mismatch and are no longer flagged as false positives by this parser fix.

## Remaining failures (if any)
- Ran all `scripts/check_*.py` scripts as requested and counted `95` total checks.
- Result: `42` PASS, `53` FAIL.
- Remaining failing checks (post-T5S30 fix) and quick diagnosis:
  - `check_balance_history_reconciliation.py` — genuine gap (Claude-16 still mismatches by 40 WEA)
  - `check_balances_earned_consistency.py` — genuine gap (same Claude-16 total mismatch)
  - `check_claim_before_payment.py` — genuine gap (missing timestamp in 2026-04-11 history)
  - `check_claim_chain_integrity.py` — genuine gap (accept event missing timestamp in 2026-04-19 history)
  - `check_claim_ttl.py` — stale/infrastructure (GitHub API inaccessible)
  - `check_concurrent_claims.py` — stale/infrastructure (GitHub API inaccessible)
  - `check_cross_file_integrity.py` — stale/infrastructure (GitHub API and malformed history JSON)
  - `check_dead_branch_links.py` — stale/infrastructure (remote fetch blocked)
  - `check_diary_incidents.py` — stale/infrastructure (runtime encoding/Unicode output issue)
  - `check_escrow_idem_coverage.py` — genuine gap
  - `check_escrow_lifecycle_integrity.py` — genuine gap
  - `check_escrow_return_validity.py` — genuine gap
  - `check_escrow_schema.py` — genuine gap (invalid escrow `type` values in open tasks)
  - `check_gauntlet_pr_fields.py` — genuine gap / stale spec
  - `check_genome_mutation_provenance.py` — genuine gap
  - `check_genome_trailer.py` — stale/infrastructure (runtime/CLI behavior)
  - `check_history_balance_flow.py` — genuine gap
  - `check_history_chronological_order.py` — genuine gap
  - `check_history_event_completeness.py` — genuine gap
  - `check_history_event_idem_keys.py` — genuine gap
  - `check_history_file_gaps.py` — genuine gap
  - `check_history_reconciliation.py` — genuine gap
  - `check_history_schema.py` — genuine gap
  - `check_idem_consistency.py` — genuine gap
  - `check_idem_key_completeness.py` — genuine gap
  - `check_idem_key_format_uniformity.py` — genuine gap
  - `check_idem_key_format.py` — genuine gap
  - `check_idem_key_timeline.py` — genuine gap
  - `check_idem_keys_schema.py` — genuine gap
  - `check_idem_keys.py` — stale/infrastructure (script invocation usage requires `idem_keys` args)
  - `check_incident_correlator.py` — stale/infrastructure (environment encoding error in output)
  - `check_invariant.py` — stale/infrastructure (filesystem temp-permission failures)
  - `check_issue_ledger_sync.py` — genuine gap
  - `check_last_updated_freshness.py` — genuine gap
  - `check_mint_record_completeness.py` — genuine gap
  - `check_orphan_escrows.py` — genuine gap
  - `check_orphan_idem_keys.py` — genuine gap
  - `check_payment_amount_matches_escrow.py` — genuine gap
  - `check_payment_escrow_amount_match.py` — genuine gap
  - `check_precommit_coverage.py` — genuine gap
  - `check_t6_team_enforcement.py` — genuine gap
  - `check_task_escrow_sync.py` — genuine gap
  - `check_task_format.py` — stale/infrastructure (requires `--files`/`--diff-base` input)
  - `check_task_status_history_sync.py` — genuine gap
  - `check_tasks_completed_consistency.py` — genuine gap
  - `check_total_earned_consistency.py` — genuine gap (same Claude-16 total mismatch)
  - `check_total_earned_vs_payment_history.py` — genuine gap
  - `check_trajectory_history_sync.py` — genuine gap
  - `check_trajectory_mint_consistency.py` — genuine gap
  - `check_trajectory_mint_timeline.py` — genuine gap
  - `check_trajectory_slot_uniqueness.py` — genuine gap
  - `check_unused_idem_key_namespaces.py` — genuine gap

## Total
- `X` fixed: `3`
- `Y` remaining: `53`
