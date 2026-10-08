# Not ready for automatic merge

CURRENT: single authorized retry of the identical ruleset request succeeded.
24719775 was created first; then 13444370 lost only duplicated update restriction
and gained strict tide/replay from GitHub Actions15368. Readback validated full
rules and bypass scope. Installation remains169219742, App5236324. 45 focused
tests and Ruff pass; independent Codex reviewer found no actionable defects.
Draft workflow checks returned installation ID before merge and stays disabled
unless TIDE_MERGE_ENABLED=true. No live merge or payout occurred. Details and
remaining deployment checkpoints are in deployment.md. Older failures below
are historical and do not mean setup is currently blocked.

## Installation verified; ruleset submission blocked

Operator completed installation at 11:32 UTC. Chrome and authenticated read-only
API confirm installation 169219742, App 5236324 (`wea-tide-merger`), organization
WeTheAgents, selected repository wetheagents only, Contents write and Metadata
read. Installation is complete; do not ask for it again.

Submission of `update-ruleset-request.json` was rejected by automatic approval
review: delegated approval was not accepted for this exact persistent main
bypass grant. No ruleset was created, and no alternate route or retry was used.
The prepared payload retains the administrator exception, adds only App 5236324
with pull_request bypass to an update-only main rule, and does not modify the
existing ruleset. Human approval/completion is the next settings checkpoint.

Independent review accepted setup attestation plus visible-policy runtime checks
under existing trusted-admin governance. Code now requires a trusted-main
`.github/tide-merge-policy.json` binding full setup policy, visible digest,
repository, App and installation. Missing runtime bypass metadata is permitted;
returned conflicting metadata refuses. No Administration grant is required.
Attestation cannot be generated until approved rules exist. Hidden bypass-only
admin changes remain a stated trust boundary; disable and re-attest before them.
No enabled workflow, code publication, financial operation or live test occurred.

## Current handoff, 2026-10-08

The operator manually created organization-owned `wea-tide-merger`, App ID
5236324, generated its key and saved `TIDE_MERGER_PRIVATE_KEY` in environment
`tide-merge`. UI inspection confirmed Contents write and mandatory Metadata read
only. Secret metadata was inspected; no key content was read. This supersedes
the earlier App-creation blocker below.

Environment deployment restriction was saved and verified: selected branches,
exact branch pattern `main`, one branch and zero tags. Other environment
protection settings were unchanged.

App installation is not confirmed. Chrome is prepared with Only select
repositories, exactly `WeTheAgents/wetheagents`, and the Install button.
Automatic approval review rejected that submission because it did not accept
delegated authorization as trusted user-authored confirmation for this exact
persistent Contents-write grant. No alternate installation API or retry was
used. The operator must complete this visible step manually.

No ruleset, active workflow, ledger or repository permission was changed.
The workflow template remains disabled outside `.github/workflows`.
Remaining work: verify installation, resolve runtime policy verification without
Administration access (hidden bypass actors must not require a broader token),
review and publish transport, apply the approved narrow ruleset split, then
demonstrate a safe live candidate and negative enforcement. Automation is not
operational yet. Earlier paragraphs below are historical execution evidence.

Latest continuation: 68 tests passed in the combined preflight/transport/ledger/
replay run. Independent review identified missing bypass-authority hashing and
incomplete-response recovery. Added full ruleset snapshot validation (missing
bypass visibility refuses), partial HTTP/JSON response reconciliation and negative
tests. Final focused suite: 40 passed; Ruff passed. No live claims follow from
mocked server enforcement. Minimal-token bypass visibility remains an explicit
design gap documented in design.md; do not request broader permissions silently.

Continuation evidence: preflight + transport focused suite, 36 passed in 0.34s;
Ruff on all four new Python files passed. Disabled template remains outside Actions.
Browser proof: local Chrome reached the prepared App form; user completed sudo.
Two automatic approval-review denials blocked submission. No App/key/settings
were created. This is a security-review handoff, not a GitHub permission error.

Local preparation only, 2026-10-08, branch codex/tide-merge-gate-20261008,
base 62ab2346070a8525211221f9cbd49388fd7612bf. No commits or PR published.

- Ruff check: passed for the two new Python files.
- pytest preflight + existing Tide ledger/replay: 47 passed in 38.71s.
- Independent fresh-context review: no defect in inactive P1-P4; identified
  missing latest producer-attempt check for the proposed live contract.
- Added latest-attempt validation and regression; focused suite: 16 passed.
- Only seven intended new files. Removed task-generated pytest temporary trees.
  Other worktrees, original dirty files, ledger, credentials and GitHub settings
  were not modified. No live merge or workflow dispatch was attempted.

Preflight is deliberately read-only and has no Actions caller. Its tests mock
replay to test orchestration; existing ledger tests separately cover unauthorized
payments, mixed code/ledger files, incorrect provenance and canonical replay.
Neither suite establishes server-side race closure or production merge success.

Remaining blockers: exact security approval, actual dedicated App identity,
protected transport/workflow implementation and review, ruleset application,
fresh safe live candidate and server-side negative evidence. No Ready claim.
Lean cut: reuse existing ordinary validator; no duplicate financial logic.
