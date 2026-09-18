# Domain / Access operational proposal

Revision 0.5, accepted 2026-09-18. Bound to accepted Outcome 0.5.
The operator accepted DA-01..08, ST-01, C1-P01 and C1-P02 and authorized implementation.
R-11, S-11A, and S-11B retain their library meaning; this accepted delta supplies the operational path.

## Affected BDD

| Contract | Proposed change |
| --- | --- |
| R-11 / S-11A | Authenticated CLI intake, registered recipient, durable grant, publication without an Access PR |
| R-11 / S-11B | Readback derives expiry at the endpoint; observations retain their actual timestamps |
| Tide T-01 through T-06 | No change to financial collection, replay, batch schema, guard, or merge |
| Participant admission and Work | No change; admission remains canonical before Access and funding remains separate |
| DA-01 through DA-08 | Replace unaccepted 0.1 proposals with the CLI and GitHub journal path below |
| C1-P01 | Retained grant/read/expiry sub-scenario with a named Steward |
| C1-P02 | Two separate trips and the existing funded WTA, result, settlement, and Release path |
| ST-01 | Accepted manual Agent0 appointment; handoff and role boundaries add no new Access issuer type |
| Circle-1 parser snapshot test | Unchanged by the Access mechanism; the funded #997 repair must update the real-file debt expectation while retaining negative synthetic cases |

Acceptance authorizes implementation; passing evidence and live activation are recorded separately.

## DA-01: declaration and authority

- **GIVEN:** A canonical registered recipient and Domain exist.
- **WHEN:** The operator or Agent0 submits `wea access grant`.
- **THEN:** The CLI MUST publish one structured declaration in the configured private WEA Issue.
- **THEN:** The handler MUST verify repository, numeric author, authority role, recipient registration, and registry hash from canonical evidence.
- **THEN:** Authority MUST hold at declaration and acceptance; the record MUST retain both evaluations.
- **GIVEN:** The source has a wrong account, inactive binding, declared subject without the required role, unregistered recipient, or foreign repository.
- **WHEN:** The handler validates it.
- **THEN:** It MUST reject the declaration without a grant and retain a specific reason.
- **THEN:** Account authentication MUST be followed by validation of the declared subject's canonical role binding.
- **THEN:** Evidence MUST identify agent attribution as declared, not proof of the originating local process.
- **REQUIRED EVIDENCE:** Both positive authority branches, every negative branch, and real source readback.

Pilot trust scope: holders of the same operator credentials can select that account's valid Agent0 binding.
This proposal does not isolate their sessions. Tests must not claim to reject such a request as independently proven impersonation.

## DA-02: acceptance, publication, and clock

- **GIVEN:** Authority, Domain, recipient, and global overlap checks pass.
- **WHEN:** The trusted handler accepts against the current journal head.
- **THEN:** It MUST record `starts_at = accepted_at` and `ends_at = starts_at + 604800 seconds`.
- **THEN:** Acceptance time MUST come from the trusted runtime UTC clock, never a caller argument or Issue edit.
- **THEN:** Durable publication MUST establish the grant without a per-Access PR or merge.
- **THEN:** Before publication, the CLI MUST report pending, not active.
- **GIVEN:** Concurrent grants overlap for one agent, including across different domains.
- **WHEN:** They attempt publication against the same predecessor.
- **THEN:** At most one MUST succeed; the other MUST be revalidated against the winner.
- **GIVEN:** A new acceptance occurs at the exact previous endpoint.
- **WHEN:** Overlap is checked.
- **THEN:** The new grant MUST be permitted.
- **REQUIRED EVIDENCE:** Durable acknowledgement, interval, cross-domain race, and endpoint tests.

## DA-03: retry and source retention

- **GIVEN:** One request ID and identical payload recur after an uncertain response.
- **WHEN:** CLI or handler retries.
- **THEN:** Readback MUST resolve that request before another effect is attempted.
- **THEN:** Duplicate source comments MUST map to one decision and at most one grant.
- **GIVEN:** The same key names different input, or the source was edited before capture.
- **WHEN:** The handler validates it.
- **THEN:** It MUST reject the conflict without changing an existing grant.
- **GIVEN:** A source is edited or deleted after capture.
- **WHEN:** The journal is replayed.
- **THEN:** Its retained accepted source and decision MUST remain unchanged.
- **REQUIRED EVIDENCE:** Lost responses, conflicting payloads, pre-capture edits, post-capture edits, and deletion.

## DA-04: GitHub history and recovery

- **GIVEN:** Complete journal decisions, authority snapshots, Domain bytes, and protocol references exist.
- **WHEN:** A fresh process reconstructs Access from GitHub.
- **THEN:** It MUST derive identical grants, rejections, idempotency results, and expiry state.
- **GIVEN:** The journal commit succeeded but an Issue receipt is absent, stale, or edited.
- **WHEN:** The CLI reads that request.
- **THEN:** It MUST report the committed result and distinguish receipt repair from grant creation.
- **GIVEN:** Publication fails, a predecessor changes, or replay detects invalid data.
- **WHEN:** The handler or CLI evaluates the operation.
- **THEN:** It MUST preserve valid history and MUST NOT report a fabricated success.
- **THEN:** Recovery MUST NOT rewrite an accepted interval or financial history.
- **REQUIRED EVIDENCE:** Fresh-process replay, tampering, races, and crashes before/after commit and receipt.

## DA-05: expiry and observation

- **GIVEN:** A grant has a recorded endpoint.
- **WHEN:** Readback evaluates immediately before, exactly at, or after it.
- **THEN:** It MUST report active, expired, and expired respectively.
- **THEN:** Expiry MUST require no write, scheduler, PR, merge, or human action.
- **GIVEN:** The first real observation occurs after the endpoint.
- **WHEN:** Its receipt is recorded.
- **THEN:** It MUST preserve `effective_at = ends_at` and the later actual `observed_at` separately.
- **THEN:** Synthetic-time tests MUST NOT count as a real seven-day trip.
- **REQUIRED EVIDENCE:** Boundary tests and an actual post-boundary readback after time elapses.

## DA-06: CLI readback and transparency

- **GIVEN:** A request is pending, rejected, committed and active, or committed and expired.
- **WHEN:** The user runs `wea access show`.
- **THEN:** It MUST show status, request/grant IDs, Issue link, journal commit, Domain, interval, and evaluation time.
- **THEN:** It MUST distinguish the authenticated declaration, authority evidence, and accepted decision.
- **GIVEN:** Fetch or replay fails.
- **WHEN:** Current state cannot be established.
- **THEN:** The CLI MUST report unavailable, not stale success.
- **THEN:** Historical or synthetic evaluation MUST identify itself.
- **REQUIRED EVIDENCE:** Subprocess cases and two independent real reads of the first grant.

## DA-07: Work, money, and permissions

- **GIVEN:** Access is issued, absent, or expired.
- **WHEN:** Access or independent task processing runs.
- **THEN:** Work, funding, acceptance, settlement, Release, and participant rules MUST remain unchanged.
- **THEN:** The Access handler MUST NOT write the financial ledger or modify GitHub permissions.
- **THEN:** Expiry MUST NOT cancel an existing payment obligation.
- **THEN:** The interface MUST NOT expose early revoke, extension, renewal, or transfer.
- **REQUIRED EVIDENCE:** No task/ledger writes or permission calls; independent Tide maintenance remains unchanged.

## DA-08: implementation and activation

- **GIVEN:** This exact proposal is agreed for implementation.
- **WHEN:** The code candidate is ready.
- **THEN:** It MUST pass review and manual code merge before deployment.
- **GIVEN:** No separate activation decision exists.
- **WHEN:** The installed handler sees Access-like sources.
- **THEN:** It MUST remain disabled and issue no grants.
- **GIVEN:** The operator activates one exact protocol, journal genesis, and intake Issue.
- **WHEN:** Fresh eligible declarations arrive after that boundary.
- **THEN:** They MUST use the new path without per-operation approval PRs.
- **THEN:** Old comments, batches, and executor history MUST NOT acquire retroactive effects.
- **REQUIRED EVIDENCE:** Activation receipt, disabled-path, fresh-source cutoff, and history-isolation tests.

## ST-01: named Steward and independent Access

Appointment evidence: the operator appointed `agent0@system` in this conversation on 2026-09-18; Agent0 accepted.
This resolves the manual pilot responsibility without activating DA-01..08 or claiming a new runtime role mechanism.

- **GIVEN:** The operator selects one registered Steward and records the Domain, remit, appointment evidence, and handoff terms.
- **WHEN:** The Steward acknowledges the assignment in the private pilot record.
- **THEN:** The pilot handoff MUST identify the named Steward and link the pinned Domain context.
- **THEN:** Appointment MUST NOT create Access, Work, payment authority, or GitHub permissions.
- **GIVEN:** A Steward has no separate operator or Agent0 authority.
- **WHEN:** A declaration uses stewardship as its sole basis to grant Access.
- **THEN:** The Access adapter MUST reject it under the existing issuer rules.
- **GIVEN:** A Steward's own Access expires.
- **WHEN:** The right is evaluated at its endpoint.
- **THEN:** Access MUST expire normally; the responsibility assignment MUST NOT silently extend it or change the named Steward.
- **REQUIRED EVIDENCE:** Explicit appointment/acknowledgement, first handoff, and preservation of existing Access authority and interval rules.

## C1-P01: first trip

- **GIVEN:** Codex-19 remains registered, the pilot has a named Steward, and first issuance is authorized after activation.
- **WHEN:** Agent0 grants Access to the pinned `circle-1` Domain through CLI.
- **THEN:** Issue and journal MUST expose the decision, revision, authority, and exact interval.
- **THEN:** Two fresh reads MUST reconstruct the same grant without issuer process memory.
- **THEN:** A real later read MUST show expiry at the original endpoint.
- **THEN:** Handoff MUST identify outstanding elapsed-time observation.
- **THEN:** Stage 1 MUST NOT be reported as useful Work, acceptance, settlement, or Release.
- **REQUIRED EVIDENCE:** Request/receipt URLs, journal commit, readbacks, and real post-boundary observation.

## C1-P02: two trips and one WTA cycle

- **GIVEN:** Two registered workers have distinct active Access grants and the exact #997 Plan has canonical funding.
- **WHEN:** Agent0 starts their separate task sessions.
- **THEN:** Both MUST receive the same task scope, criteria, common-control requirements, and supported Work evidence path.
- **GIVEN:** Both submissions have been checked against the exact Plan.
- **WHEN:** Agent0 selects through the existing Ranked path.
- **THEN:** Only an eligible compliant winner MUST receive the 10 WEA prize through canonical Tide settlement.
- **THEN:** If no result qualifies, existing stop/expiry/refund behavior MUST apply without a fabricated winner.
- **GIVEN:** Settlement is canonical.
- **WHEN:** Agent0 conducts Release.
- **THEN:** Both competitors MUST provide their own actual reflections; any accepted genome change MUST retain that agent's provenance.
- **THEN:** Canonical Release MUST use actual runtime invitations. The unselected worker's operational reflection, Agent0 decision, provenance, and summary MUST NOT be reported as an automatic implement-work invitation. A Triage invitation remains a separate basis.
- **THEN:** The handoff MUST distinguish task closure, Release, and any pending real Access-expiry observation.
- **REQUIRED EVIDENCE:** Two grant receipts, canonical funding, worker sessions, immutable Work, disclosures, comparison, selection, settlement, and both reflection/decision records with their actual runtime or operational basis.

These are pilot composition criteria. Existing task/executor, money, and Release rules do not change.
