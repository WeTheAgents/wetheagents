# Verification

Binding: Outcome 1.0, Spec 1.0, Design 1.0.
Decision: Ready. The approved implementation, installation and live checkpoint are verified. Real trip expiry remains a separate future observation.

Account verified as `peachgabba22` / `129645949`; canonical main is `77d2ebec4154b91339aa5bfa4697032220e8318c`. Continue the existing isolated PR #1008 branch. The original checkout remains untouched.

## Implementation evidence

- Protocol-transition/Access/admission/Tide regression: 169 passed, exit 0, 230.31 seconds.
- The first focused run had one fixture error: the second Tide checkpoint reused its cutoff. Corrected the fixture to advance time; production correctly rejected the stale cutoff.
- Ruff and diff checks passed. Economy invariant passed: Tide 16, balances 19025 WEA, escrow 0.
- Fresh independent review found no actionable defects in source authority, mixed replay, preservation, races, retries or checkpoint behavior.
- Native post-PR review and live installation remain pending. No journal, grant, ledger or permission was changed by these checks.
- Scope remains the existing workflow/journal plus one pure format module. No new dependency, executor or financial rule; no safe authority-preserving cut was identified.

- Final focused transition suite: 18 passed, exit 0, 19.30 seconds, including workflow dispatch, idempotent retry, ordinary reconciliation and a subsequent valid seven-day grant.
- A direct writer-boundary probe found the new pure `access_protocol.py` was unprotected. Added it to the existing pinned source set; all six installed-guard regression cases passed (96.17 seconds). The original admission module was already protected by static writer discovery.
- Before installation the live journal still had exactly two decisions at `6ffe0b5dab1d2233bbebff2bacdfb0e874ad7254`. Full immutable readback is retained in `.wea_runs/domain-admission/pre-transition.json`; canonical repository privacy was verified.

- Full native review returned no actionable defects and independently passed 63 transition/admission cases. Runtime-boundary suite: 11 passed, exit 0, 0.60 seconds.
- Final guard-pin review found its synthetic trusted-repository fixture lacked the newly required file. Fixed the fixture; the full native-guard suite passed 44 tests, exit 0, 69.70 seconds. Ruff and diff checks remain clean. Repeat review of the fix precedes installation.

## Live installation and current result

This section supersedes the preparation-time pending statuses above.

- PR #1008 was manually installed at `2026-09-20T08:41:37Z`, commit `4f87629ad6273b3fc1a3e04acd31612a848a134b`, under the explicit operator installation approval.
- Exact update source: https://github.com/WeTheAgents/wetheagents/issues/997#issuecomment-5748736507. Source SHA-256: `82d161ecc52f28659e78161b4506d3403f105a32d639859134c3f07736aa0b5e`.
- Trusted update run: https://github.com/WeTheAgents/wetheagents/actions/runs/35500281448. Accepted at `2026-09-20T08:42:25.187709Z`; journal commit `fd1acf8506bb513525e34d4a220f2de92f8780ea`.
- Latest authorized package hash: `f1b08e4ea8b65039e7b35bc4ddde77e658e08f8f7da72820d7fbbb9cadb25d6a`. The original package and genesis remain unchanged historical evidence.
- Actual read at `2026-09-20T08:43:50.109079+00:00` compared full original records and introducing commits. Both grants are identical and both CLI reads report active.
- Exact update retry run `35500391882` succeeded; the journal contains exactly one update. CLI overlap request `0f6d90c0-e293-41fb-874d-0ceb3ccb029b` was rejected canonically in ordinary run `35500402834`. No third grant exists.
- Schema-3 Tide 17 retains two grants, one update and one rejected request. Candidate `f0f05907e4128672181587801f0acfe1bf381245` passed local replay, native review and authenticated guard run `35500690258`.
- PR #1009 was manually merged at `2026-09-20T08:56:09Z`, canonical commit `cb897b5c34e6b10d38346e2e24c18d6598e6d4de`. Balances remain unchanged and escrow remains zero; no new paid work was launched.
- The code-installation guard rejection remains visible as a one-time authorized maintenance exception. The subsequent data candidate passed the installed guard normally.
- No actionable review finding remains. Receipt paths and original exact expiry endpoints are in the newest runlog entry.

Final ordinary reconciliation run `35500941666` succeeded on canonical Tide-17 main and left the journal head unchanged. The canonical invariant passed at Tide 17: balances 19025 WEA, escrow 0.

APT-01..06 are covered by retained tests and live evidence. September 25 expiry was not observed during this session and is not claimed.
