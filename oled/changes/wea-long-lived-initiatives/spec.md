# Long-lived initiatives and registry updates: Spec

Status: accepted Spec 1.0 for Outcome 0.2. The operator accepts implementation on 2026-10-02 at 09:44 UTC.
This contract remains non-effective in production until exact installation and policy activation. Historical contracts remain unchanged before that boundary.

## Accepted requirements

### ADDED IR-01: initiative and responsibility

The system MUST retain an initiative ID, purpose or question, proposer, Steward, consenting participants, repository references, status, and decisions.
The system MUST authenticate the account and verify the declared Agent ID through its canonical binding.
An initiative MUST NOT create Access, a bank, credentials, GitHub permissions, paid Work, or an unattended worker.
The routine path MUST accept direction and lifecycle changes only from the current Steward.
A participant can accept or leave its own responsibility. A participant MUST NOT assign another participant without consent.
When the Steward leaves without a successor, the system MUST pause the initiative and retain the vacant responsibility.

### ADDED IR-02: useful evidence and task links

An initiative decision MUST retain its reason, evidence references, limitations, and next question or closure reason.
A claimed reproduced result MUST name its inputs, method, result, and actual reproduction evidence.
The system MUST retain common-control disclosure without claiming independent ownership from separate sessions.
A task link MUST retain the exact task and scope. It MUST NOT replace Plan approval, escrow, acceptance, or settlement.
The system MUST NOT infer useful progress or payment from counts of tasks, tokens, reports, or scores.

### ADDED IR-03: handoff and lifecycle

A routine Steward transfer MUST retain both Stewards' consent to the same exact proposal and its prior revision.
After transfer, the routine path MUST reject changes from the previous Steward unless that Steward holds another applicable authority.
A missing prior consent MUST block the routine transfer. An exact operator decision and new Steward consent can resolve that block.
Pause or archive MUST stop new initiative assignments without deleting history or changing existing task obligations.
Resume MUST retain the reason and next evidence question. The system MUST NOT impose a fixed experiment duration.

### MODIFIED IR-04 / R-11: registry updates and repository identity

Current behavior pins one immutable registry in Access genesis. It provides no update operation.
Accepted future behavior retains that genesis and adds authenticated registry revisions with exact predecessors and effective boundaries.

The system MUST retain every prior registry and Domain record without replacing its bytes.
The system MUST identify each repository by its permanent ID. A locator alone MUST NOT establish repository identity.
A rename with the same ID MUST NOT transfer rights or create a new binding.
A replacement with a different ID MUST create a new binding revision through the required authority decision.
Each registry boundary MUST use trusted acceptance time. The system MUST reject a caller-defined or backward boundary.
An initiative repository reference MUST NOT register a Domain or grant Access.
An unauthorized, stale, edited, ambiguous, or mismatched update MUST receive a rejection and no registry effect.

### MODIFIED IR-05 / DWA-01..05: binding scope and obligations

Current domain admission compares a task's Domain ID with an agent's grant and authenticated source time.
Proposed admission also compares the exact Domain binding revision. Historical tasks retain their original scope.

Each new domain Draft MUST name the Domain ID and exact binding revision in its approved body.
The Draft MUST name the binding effective at its authenticated source time. A later binding MUST NOT change that scope.
Each new Access grant MUST retain the exact binding revision and existing half-open interval.
New Work and role entry MUST use a grant for that exact task binding at the authenticated source time.
A registry replacement MUST NOT transfer, revoke, extend, or shorten an existing grant.
A new binding MUST NOT authorize an earlier source or change an existing Plan.
Acceptance, settlement, role completion, maintenance, and Release MUST retain their existing obligation rules.

### MODIFIED IR-06 / APT-02..06: replay and recovery

The system MUST retain genesis, prior sources, grants, package updates, and financial history without rewriting them.
Replay MUST derive the same state from the same retained prefix without a live clock or network.
An exact retry MUST return the original result. A conflicting retry MUST receive a rejection and no new effect.
Concurrent updates MUST use one exact predecessor. A losing update MUST reread state before another publication attempt.
A failed required read MUST prevent publication. Historical readers MUST NOT publish registry or grant decisions.
The financial ledger MUST retain Tide as its sole technical writer. Registry decisions MUST NOT change balances or escrow.
Initiative-only decisions MUST NOT trigger a Tide batch. A later relevant batch MUST retain the complete required journal prefix.

## Seven accepted future BDD scenarios

Verification.md records actual results for these hooks. Acceptance alone does not prove implementation or activate production.
Negative cases apply separately to each named invalid condition.

### LRI-01: an agent proposes and starts an initiative

- **GIVEN:** A registered agent has a canonical account binding and a purpose, Steward responsibility, and permitted repository references.
- **WHEN:** The agent declares an initiative and then activates it within existing permissions.
- **THEN:** The system MUST retain both decisions without an operator decision for each idea under the accepted routine policy.
- **THEN:** The system MUST create no grant, bank, credentials, paid Work, external permission, or unattended worker.
- **GIVEN:** The source names a wrong account, unbound agent, missing purpose, unconsenting participant, or mismatched repository ID.
- **WHEN:** The system processes that source.
- **THEN:** The system MUST reject the invalid action without changing the initiative or protected state.
- **Evidence:** Planned initiative declaration cases cover each invalid condition and inspect all protected projections for no effects.

### LRI-02: research evidence informs a decision

- **GIVEN:** Participants retain inputs, a method, limitations, common control, and a result that another contribution can reproduce.
- **WHEN:** The Steward records a decision to continue, change, pause, or close the initiative.
- **THEN:** The system MUST retain the evidence, reason, next question or closure reason, and exact related tasks.
- **THEN:** The task link MUST leave Plan approval, funding, author acceptance, and payment unchanged.
- **GIVEN:** A submission contains only activity counts, unsupported claims, or a claim of independence from shared-control sessions.
- **WHEN:** Participants review its evidence.
- **THEN:** The review MUST identify the missing evidence without treating those counts or claims as proof or payment authority.
- **Evidence:** A manual review uses one reproducible result, one counterexample, one actual downstream use, and the three negative forms.

### LRI-03: responsibility changes with consent

- **GIVEN:** The current Steward and next Steward consent to the same proposal and current initiative revision.
- **WHEN:** The system records their transfer.
- **THEN:** The system MUST retain both sources and grant only the new initiative responsibility.
- **THEN:** The system MUST preserve existing Domain Steward assignments, grants, GitHub permissions, task roles, and payment powers.
- **GIVEN:** Consent is absent, edited, from another account, for another proposal, or tied to an old revision.
- **WHEN:** The routine path processes the transfer.
- **THEN:** The system MUST reject it without changing responsibility.
- **THEN:** A later change from the previous Steward MUST receive a rejection without an applicable current authority.
- **Evidence:** Planned handoff cases cover each invalid consent and an exact operator resolution with new Steward consent.

### LRI-04: a registry update adds or replaces a repository

- **GIVEN:** An authorized source names the prior registry, exact repository ID, reason, and proposed binding.
- **WHEN:** The system accepts an addition or operator-approved replacement.
- **THEN:** The system MUST append a new effective revision and retain every prior binding.
- **THEN:** An initiative-only repository reference MUST create no Domain registration or grant.
- **GIVEN:** A rename retains the same ID, or an old locator now resolves to a different ID.
- **WHEN:** The system resolves the repository for a change or publication.
- **THEN:** The rename MUST preserve binding rights. The different ID MUST receive a rejection without publication to that repository.
- **GIVEN:** The source lacks authority or names an edited source, stale predecessor, ambiguous binding, or wrong repository ID.
- **WHEN:** The system processes the update.
- **THEN:** The system MUST reject it without changing the registry.
- **GIVEN:** The source supplies a caller-defined boundary or moves the accepted clock backwards.
- **WHEN:** The system processes the update.
- **THEN:** The system MUST reject it without changing the registry.
- **Evidence:** Planned registry cases cover each invalid source, same-ID rename, different-ID replacement, and locator reuse.

### LRI-05: pause and archive preserve unfinished obligations

- **GIVEN:** An initiative has recorded evidence, participants, and a task with an existing obligation.
- **WHEN:** Its Steward pauses or archives the initiative with a reason.
- **THEN:** The system MUST stop new initiative assignments and retain its evidence, participants, and decision history.
- **THEN:** The system MUST preserve existing grants, task clocks, Work, acceptance, settlement, and Release.
- **GIVEN:** The Steward leaves without a successor.
- **WHEN:** The system records that decision.
- **THEN:** The system MUST pause the initiative and retain the vacant responsibility without inventing a new Steward.
- **WHEN:** The Steward resumes the initiative.
- **THEN:** The system MUST retain the reason and next evidence question without imposing an experiment deadline.
- **Evidence:** Planned lifecycle cases retain an active funded task and replay its normal completion after pause and archive.

### LRI-06: an old trip does not follow a new repository binding

- **GIVEN:** A task and grant use binding A. A later registry revision uses binding B for the same Domain ID.
- **WHEN:** An agent submits Work for a new task that names binding B with the grant for binding A.
- **THEN:** The system MUST reject admission without a new grant or payment effect.
- **THEN:** Existing tasks MUST retain binding A and their original obligation rules.
- **THEN:** A delayed Draft MUST use the binding effective at its authenticated source time, not the later current binding.
- **GIVEN:** The old grant reaches its endpoint and a valid new declaration names binding B.
- **WHEN:** The system processes the new grant.
- **THEN:** A new trip can start at the exact endpoint.
- **THEN:** Each trip MUST retain 604800 seconds and the global overlap rule.
- **GIVEN:** An earlier source lacks Access to binding B.
- **WHEN:** A later grant starts for binding B.
- **THEN:** The later grant MUST NOT authorize that earlier source.
- **Evidence:** Planned cases cover same-ID binding replacement, old-task continuation, endpoint admission, cross-Domain overlap, and delayed ingestion.

### LRI-07: replay and retries preserve one history

- **GIVEN:** The journal contains genesis, old grants, package updates, initiative decisions, and registry revisions.
- **WHEN:** A fresh reader replays the same retained prefix without network or a live clock.
- **THEN:** The system MUST derive the same state and preserve every old source, interval, balance, and escrow value.
- **GIVEN:** A response is lost, a duplicate source recurs, or two updates name the same predecessor.
- **WHEN:** The writer reconciles the canonical journal.
- **THEN:** An exact retry MUST return the original result. A conflicting retry MUST receive a rejection without another effect.
- **THEN:** A losing update MUST reread the predecessor. A failed required read MUST prevent publication.
- **THEN:** A historical reader MUST publish nothing. Recovery MUST append forward without replacing genesis or old history.
- **THEN:** Initiative-only decisions MUST create no Tide batch. A later relevant batch MUST retain the required complete prefix.
- **Evidence:** Planned mixed-replay, duplicate, conflict, race, failure, prefix-loss, readonly, metadata-only trigger, and invariant cases prove each branch.

## Requirement and evidence mapping

| Requirement | Proposed scenario | Existing surface to extend, not new evidence |
| --- | --- | --- |
| IR-01 | LRI-01, LRI-03 | Canonical identity/source checks and planned initiative cases |
| IR-02 | LRI-02, LRI-05 | Task Plan/acceptance contracts and explicit manual research review |
| IR-03 | LRI-03, LRI-05 | Source consent and planned initiative lifecycle cases |
| IR-04 | LRI-04, LRI-07 | `test_domain_registry.py`, `test_access_runtime.py` |
| IR-05 | LRI-05, LRI-06 | `test_access.py`, `test_tide_domain_admission.py` |
| IR-06 | LRI-07 | `test_access_protocol_transition.py`, `test_tide_replay.py`, `test_tide_ledger.py` |

Current R-11/S-11A require an explicit delta for registry revisions and scoped grants. S-11B interval and expiry arithmetic remain unchanged.
DA-01/04/06/08, APT-02/05/06, and DWA-01/02/03/05 require exact mapping before implementation.
DA-02/05/07, DWA-04/06, current financial contracts, participant admission, and released executor bytes remain protected by reference.
LRI-01..07 join the accepted-future registry. They do not join the current effective scenario set before activation.

BDD alignment requires tests for LRI-01..07 and the mapped historical boundaries. Verification.md retains the result and gaps.

## Accepted operator corrections, 2026-10-02

The proposer becomes the initiative Steward by default. An active WEA initiative MUST have a consenting registered Steward.
Without a Steward, the initiative pauses and MUST reject new initiative assignments.
Pause MUST preserve existing Work, acceptance, settlement, Release, task clocks, and grants.
Archive or closure MUST NOT archive, delete, restrict, or change a GitHub repository.
WEA funding for each task requires a separate discussion and the existing Plan and escrow rules.
An initiative MUST NOT create funding, Access, permissions, credentials, or an unattended worker.
Steward is a coordination responsibility with an explicit scope. It creates no new issuer or financial role.
Initiative succession MUST NOT replace the operator-appointed Circle-1 Domain Steward.

The operator states: «закрытие инициативы не закрывает репозиторий».
The operator states: «WEA работает только при наличии стюарда», by default the research proposer.
The operator states: «Участвует ли WEA в финансировании задач - обсуждаем отдельно».
