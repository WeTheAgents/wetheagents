# Verification: operator metadata correction

Decision: Not ready for live activation.
Bindings: Outcome 1.0, Spec 1.0, Design 1.0 in this directory.

Baseline main: `a741126153c204ca1495796185d0b43d55f42746`.
Baseline vNext suite: 610 passed, 18 skipped, exit 0 on 2026-09-06.
Command: `python -m pytest tests/vnext -q --basetemp D:/tmp/wea-first-loop-pytest-20260906`.
The existing package rehearsal passed in a local clone with synthetic GitHub source evidence.
That result does not prove live Actions authorization.

Changed-code command: `python -m pytest tests/vnext/test_block9_github_native.py -q`.
Result: 39 passed in 59.19 seconds, exit 0. Five association values retain metadata.
Three remote association views pass; wrong author, wrong actor, and source substitution reject.
Ruff command: `python -m ruff check src/wea_vnext/block9/github_native.py tests/vnext/test_block9_github_native.py`.
Result: PASS after wrapping one long test decorator. That final edit changes formatting only.

Independent review: a fresh-context code reviewer inspected the diff, accepted contract, and runbook.
No actionable findings. Its separate focused run also reported 39 passed.
Lean cut: reuse the shared validator; no new runtime dependency, writer, or identity abstraction.
Product scope: two Python files, Agent0 startup link, two runbooks/reports, and runlog.
OLED files retain the accepted delta and supersede the stale cutover handoff status.

Simple English self-check: pragmatic mode; conditions precede instructions; technical identifiers remain literal.
BDD alignment: local S-71/S-75 metadata behavior covered. Their live proof and S-80 live pilot evidence remain absent.
Decision: local correction verified; overall launch Not ready. No ledger mutation or activation approval is implied.

Separate readiness diagnosis: `python scripts/check_idem_key_format_integrity.py --root .` exited 1.
It reports 8 malformed legacy keys and 844 unknown keys out of 928.
All eight use `escrow-return-<issue>-every-good`; the checker expects two numeric segments.
The failure remains open. No historical key was renamed to force a passing result.
