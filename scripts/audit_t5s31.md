# T5S31 Audit: history timestamp parsing cluster

## Scope
- `scripts/check_claim_before_payment.py`
- `scripts/check_history_chronological_order.py`
- `scripts/check_history_event_completeness.py`

## Decision table

| Script | Finding | Decision | Regression coverage | Notes |
|---|---|---|---|---|
| `check_claim_before_payment.py` | Timestamp lookup did not include `ts` (and was missing `created_at`) | **Fixed**: include `ts` and `created_at` in `_event_timestamp_fields` fallback chain | Added `test_payment_uses_ts_when_timestamp_missing` | Prevents false rejects on `ts`-timestamped payment/claim events |
| `check_history_chronological_order.py` | Timestamp lookup already included required aliases including `ts`; no parser bug identified in scope | **No script change required** for this task | Existing tests already cover `ts` handling (`test_uses_ts_field_when_present`), so no new regression test was added | Behavior remains `ts`, `timestamp`, `created_at`, `started_at`, `event_at`, `at` |
| `check_history_event_completeness.py` | Timestamp aliases omitted `ts`, causing required-field checks to fail on `ts`-only events | **Fixed**: add `ts` to `_TIMESTAMP_ALIASES` | Added `test_ts_alias_passes_for_payment_event` | Aligns with other checks and historical ledger events using `ts` |

## Date
- 2026-04-25
