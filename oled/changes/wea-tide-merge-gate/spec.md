# Post-merge readback correction, 2026-10-10

PR1067 already merged through the App. Encode only the fixed compare separator in the transport request. Preserve the shared API path validator, exact merge parents/tree checks, and acceptance of identical/ahead main history only. Raw traversal, foreign repository, fragments, backslashes and newline paths still refuse before HTTP. No repeat merge, dispatch, financial action or permission change is authorized by this repair.

# Preparation contract

Source: delegated user instruction, 2026-10-08. Only local preparation is active.
The proposed automatic-merge behavior is not an effective protocol version.

P1: preflight only reads. Success returns exact PR/base/head/sequence, never
performs a merge or grants lasting authority. Evidence: test_read_only_result.
P2: reject closed, draft, merged, fork, wrong branch, mismatched head/base and
pre-rollout PRs. Evidence: parameterized identity/state and old-candidate tests.
P3: use ordinary authenticated ledger validation, not activation or code-only
guard success. Failed replay propagates. Evidence: test_failed_replay plus the
existing Tide ledger suite; the new tests mock replay only to test orchestration.
P4: recheck head/base after replay; require successful completed producer run.
Evidence: main/head race and producer-failed tests.

Pending live scenarios: ordinary current candidate merges once; failed replay,
foreign PR, obsolete producer run and concurrent main/head movement never merge;
lost merge response is reconciled by immutable PR readback without a second write.
These require server policy plus exact-SHA merge transport and live evidence.

Local continuation authorized before live setup: implement disabled transport and
template. Transport tests cover exact merge, duplicate invocation, lost response,
HTTP/transport refusal without retry, failed/pending/error and forged replay
status, policy drift, head/base movement and wrong merge parents/tree. Existing
ledger tests independently exercise real candidate files and replay rejection.
Mocks of server enforcement establish client behavior only; live scenarios remain
unverified. A later producer attempt makes an earlier attempt obsolete even if
the earlier attempt succeeded (test_old_success_cannot_hide_new_attempt).
