# Verification

Outcome/Spec/Design 1.0. Ready for manual merge. GitHub disablement is already effective; YAML deletion and scoped CI await PR954 merge.

## Evidence

- GitHub readback: all eight retired workflows are disabled_manually; Tide and trusted ledger guard remain active. No retired jobs were running, queued, or waiting. Snapshot: D:/tmp/wea-ci-retirement-live-20260909.json.
- YAML parsing and filter inspection passed. Only ledger/vnext/** and evidence/vnext/** are excluded; any other changed path retains the PR trigger.
- Tide writer and trusted guard workflow bytes match origin/main exactly. No ledger or runtime code changed.
- python -m pytest tests/vnext/test_runtime_boundary.py -q: 11 passed after the review correction.
- python -m ruff check tests/vnext/test_runtime_boundary.py: passed.
- python scripts/check_doc_sync.py: passed.
- python scripts/check_invariant.py --root .: passed; 19025 WEA, zero escrow, Tide sequence 0.
- git diff --check: passed.
- python -m pytest tests/vnext -q: 679 passed, 18 skipped on the corrected candidate (192.01 seconds). The first run collected the pre-fix scanner and failed that one test; the complete rerun passed.
- PR954 head9f592b1181f269eb725a6a67b3ff6939585019d6: all applicable GitHub checks passed, including Ubuntu boundary and trusted Tide replay. No retired job started.
- Post-publication codex exec review: no actionable findings; its independent run also passed 679 tests with 18 skipped. Result: D:/tmp/wea-ci-retirement-codex-review.txt. The reviewer did not verify live settings; the parent verified each disabled workflow through GitHub API readback.

## Independent review

The neutral reviewer found that the new paths-ignore strings triggered the entrypoint scanner. Fixed by excluding only the exact approved filter line in three workflows. The remainder of every workflow, including executable references, stays checked. Boundary suite then passed.

## Scope and lean cut

15 product files: eight deleted workflows, three scoped CI workflows, two relevant docs, one existing test, and the handoff. No new runtime dependency or scheduled job. Historical scripts remain local audit tools. No changes to private synchronization or publication policy.

Self-review: resolves the operator's cost request immediately through reversible GitHub disablement, and records retirement in git. No financial BDD changes, code bypass, or unrelated files. Manual merge remains required. BDD alignment: 100% for the affected CI-only scope.

Final evidence update changes only this record, the checklist, and the handoff. The reviewed implementation is unchanged. No safe additional code cut is needed; no blocking gaps remain. Manual merge belongs to the operator.
