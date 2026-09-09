# Verification

Outcome/Spec/Design 1.0. Draft candidate; full vNext suite and post-PR review pending.

## Evidence

- GitHub readback: all eight retired workflows are disabled_manually; Tide and trusted ledger guard remain active. No retired jobs were running, queued, or waiting. Snapshot: D:/tmp/wea-ci-retirement-live-20260909.json.
- YAML parsing and filter inspection passed. Only ledger/vnext/** and evidence/vnext/** are excluded; any other changed path retains the PR trigger.
- Tide writer and trusted guard workflow bytes match origin/main exactly. No ledger or runtime code changed.
- python -m pytest tests/vnext/test_runtime_boundary.py -q: 11 passed after the review correction.
- python -m ruff check tests/vnext/test_runtime_boundary.py: passed.
- python scripts/check_doc_sync.py: passed.
- python scripts/check_invariant.py --root .: passed; 19025 WEA, zero escrow, Tide sequence 0.
- git diff --check: passed.

## Independent review

The neutral reviewer found that the new paths-ignore strings triggered the entrypoint scanner. Fixed by excluding only the exact approved filter line in three workflows. The remainder of every workflow, including executable references, stays checked. Boundary suite then passed.

## Scope and lean cut

15 product files: eight deleted workflows, three scoped CI workflows, two relevant docs, one existing test, and the handoff. No new runtime dependency or scheduled job. Historical scripts remain local audit tools. No changes to private synchronization or publication policy.

Self-review: resolves the operator's cost request immediately through reversible GitHub disablement, and records retirement in git. No financial BDD changes, code bypass, or unrelated files. Manual merge remains required. BDD alignment: 100% for the affected CI-only scope.
