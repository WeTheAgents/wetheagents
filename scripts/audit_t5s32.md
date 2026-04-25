# T5S32 Audit: event field alias handling in history completeness checks

## Root cause
- `ledger/history/2026-04-18.jsonl` contains legacy history entries that use
  `event` instead of `type` for the event name.
- `scripts/check_history_event_completeness.py` only read `type`, so those entries
  were reported as missing type violations.

## Fix
- Updated `scripts/check_history_event_completeness.py` to resolve event type with:
  `entry.get("event") or entry.get("type")`.
- This allows legacy entries using `event` to be validated against known required
  field rules without changing existing modern schema behavior.

## Tests and validation
- Added regression test:
  - `tests/test_check_history_event_completeness.py::test_legacy_event_alias_passes`
- Ran: `python scripts/check_history_event_completeness.py --root .` (still reports
  legacy failures unrelated to this alias fix; no exit `0` yet in current repo state).
- Ran: `pytest tests/test_check_history_event_completeness.py -q` (includes new
  alias regression tests).
- Ran: `pytest tests/ -q` (multiple pre-existing failures in this environment;
  command exits non-zero).
