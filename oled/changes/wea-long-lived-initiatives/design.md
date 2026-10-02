# Long-lived initiatives and registry updates: Design

Status: accepted Design 1.0 for Outcome 0.2 and Spec 1.0. Implementation and a draft PR are authorized.
Installation, activation, repository creation, and public opening remain separate gates.

## Smallest extension

The candidate reuses GitHub sources, canonical identity bindings, the existing Access control plane, native Git transfer, and append-only Git ancestry.
Tide remains the only financial writer. Initiative decisions create no parallel task system, bank, scheduler, or service.
An ordinary GitHub Issue provides proposal discovery and discussion. A confirmed source provides the durable decision.

The existing registry loader proves canonical bytes and record hashes. Access genesis retains those bytes.
`access_control.initial_state` reads that genesis. `decide` checks the genesis registry hash.
`access_protocol` accepts package changes only. It does not change the Domain registry.
`tide.domain.scope` retains a Domain ID. `require` compares that ID with grants and source time.
These surfaces need an accepted extension. An edited JSON file or changed locator does not provide one.

## Objects and projections

| Object | Retained content | Projection or authority |
| --- | --- | --- |
| Initiative | Stable ID, purpose, proposer, Steward, participant consent, responsibilities, status, evidence, task links, decisions | Journal-derived coordination metadata |
| Repository observation | Permanent GitHub ID, observed name and locator, source, observed time | Discovery data. It does not replace an immutable Domain binding |
| Domain binding | Domain ID, permanent repository ID, pinned context revision, record hash | Immutable revision. The registry selects its current effective revision |
| Registry revision | Exact predecessor, accepted source, canonical record set, effective boundary, revision hash | Journal-derived current registry, with all previous revisions retained |
| Access | Existing agent, Domain, interval, authority, idempotency, plus exact binding revision for new grants | No interval or permission change |
| Task scope | Existing task identity and domain scope, plus exact binding revision and optional initiative ID for new Drafts | Tide admission sidecar outside the released task executor |

The initiative starts with one primary repository reference. Supporting repository references need no new orchestration model.
It can exist before a repository exists. An unknown repository remains a proposal, not a verified binding or executable destination.
An initiative ID and Domain ID remain separate. Many initiative references can name one Domain without duplicating its grant rules.

## One control plane

Candidate record kinds cover initiative creation/revision, participant consent, Steward transfer, lifecycle decisions, repository observations, and registry updates.
Each record retains the existing authenticated source envelope, declared subject, source hash, current authority, accepted time, and operation identity.
The exact schema belongs to an accepted implementation plan. This proposal does not register marker strings or released CLI commands.

Routine initiative decisions use the actor's canonical binding and current initiative responsibility.
The trusted writer records metadata decisions after those checks. It does not require an operator decision for each idea under D1.
Agent0 approves additional Domain bindings only under the accepted D2 policy.
An existing Domain repository replacement requires an exact operator source while that protection remains in force.
Steward transfer records both sources. An operator resolution records the exception and new Steward consent.
Steward responsibility uses an explicit initiative or Domain scope. Existing Domain appointments and issuer role bindings remain unchanged.

The first delivery keeps the existing dedicated journal and bounded trusted workflow.
It extends the permitted record set and intake contract after exact acceptance. It does not create another authoritative Git branch.
The intake remains bounded and explicit. A public Issue is discussion evidence until the accepted source checks capture it.
Ordinary public participation and unauthenticated ideas retain their GitHub route without pretending to be canonical registered-agent decisions.

## Repository identity and binding changes

Current locators come from a permanent-ID lookup and an ID check before a publication destination becomes eligible.
A reused locator that resolves to another ID fails without a publication attempt to that repository.
Git configuration, initiative references, and repository names cannot override the binding's permanent ID.
Same-ID renames append observations. Historical record bytes retain their original locator and context revision.

Adding a reference to an initiative does not register a Domain. Registering a Domain does not create the external repository.
A new permanent ID for an existing Domain creates another immutable binding revision.
The current registry projection points to that revision after its authenticated effective boundary.
Every previous revision remains available for historical scope and replay.
Trusted acceptance time sets the boundary. A caller cannot backdate a registry update.

Before a new Draft receives canonical admission, its author names the Domain ID and binding revision in the exact approved body.
The later Plan approval binds both fields through the existing body hash.
The Draft names the binding effective at authenticated source time. Delayed ingestion uses that retained historical boundary.
New grant acceptance uses the then-current binding. A stale request fails without granting Access, except an exact retry of a prior decision.
An initiative link is optional metadata. It grants no funding or acceptance authority.
An initiative pause rejects new initiative assignments and records reasons. It does not reinterpret a valid independently authored task.
When a Steward leaves without a successor, the projection records a vacant responsibility and paused status.
The last Steward and prior decisions remain historical evidence. A later transfer uses consent or the accepted operator resolution path.

## Access and historical task compatibility

New grants retain the exact binding revision from their accepted declaration.
Historical grants resolve their binding through the unchanged registry snapshot that originally accepted them.
That resolution is a replay derivation. It rewrites no historical grant or genesis bytes.
Historical domain tasks resolve their binding from the retained admission snapshot. Their existing stored scope remains unchanged.

New Work and role entry compare the task binding, grant binding, agent identity, and authenticated source time.
An old grant never authorizes a new binding under the same Domain ID.
An old task continues to use its old binding and existing obligations after a registry replacement.
The grant duration, half-open interval, global overlap, endpoint replacement, and no-transfer rules remain unchanged.

An additive Tide schema or equivalent explicit version boundary retains exact new task scopes and mixed registry evidence.
The implementation plan chooses that boundary after Spec acceptance. It cannot silently reinterpret existing schema-3 strings.
Released task and participant closures remain unchanged. The admission adapter owns new scope checks and sidecar data.

## Replay, publication, and recovery

The journal retains registry decisions alongside its unchanged genesis, grant decisions, and package updates.
Replay selects the effective registry from the retained prefix, then applies each source under its retained authority and binding.
Registry and initiative projections contain no financial state. Tide retains the relevant journal prefix as canonical admission evidence.
Initiative-only records do not trigger a Tide batch. Registry, Access, or package changes retain their existing meaningful checkpoint requirement.
The next relevant batch retains the required complete prefix, including intervening metadata records, without losing earlier evidence.
This record classification needs an explicit APT-05/Tide delta. The current snapshot-change rule cannot silently ignore new record types.

Non-forced publication uses the current journal predecessor. A concurrent winner requires fresh replay before another attempt.
An exact operation retry returns the introducing record. A conflicting operation identity does not publish another effect.
Lost acknowledgement triggers readback. A failed required read prevents publication and reports unavailable state.
Recovery appends an authorized forward correction. It never replaces genesis, old sources, or financial rows.
An old writer that lacks the activated record format fails closed. A historical reader remains read-only.

## Circle-1 transition example

The old binding retains Domain ID `circle-1`, repository ID `R_kgDOT4-F-Q`, and context revision `36a71440840351aa462e61a8ad5955881f55ecb0`.
Its repository now uses `circle-1-old`. That rename alone grants nothing and changes no binding identity.
The proposed initiative can reference this old repository as evidence without replacing its Domain binding.

A future repository named `circle-1` receives a different permanent ID. That ID is unknown until separately authorized creation.
Under accepted D4, an exact operator registry decision binds `circle-1` to the new repository through a new revision.
Existing grants and tasks keep the old revision. New trips and Drafts must name the new revision explicitly.
The stable Domain ID preserves continuity. Each immutable record hash identifies one binding revision.
The replacement transfers no Access, Work, participant identity, budget, or credentials.

The two confirmed October trips retain their original October 8 endpoints.
The operational cutover can wait for real expiry readback. Waiting does not replace the required binding and replay checks.
Public opening and cover approval remain separate gates. No future repository or initiative participant is created by this candidate.

## Implementation boundary and evidence

The candidate adds only the records and projections needed for initiative continuity and current repository changes.
It uses the Python standard library and existing GitHub/Git paths. It adds no service, dependency, token, generic event bus, or background loop.
An implementation plan must reconsider the design before changing released closures, financial semantics, external permissions, or a second authoritative journal.
The proposed behavior needs human evidence review. A runtime cannot establish scientific value from record counts.

| Lane or material state | Authority/status | Evidence hook and current result | Gap and next action |
| --- | --- | --- | --- |
| Initiative creation and responsibility | D1/D3 accepted | LRI-01/03 tests pass; exact results in verification.md | Run the bound implementation and tests |
| Evidence and useful decisions | D5 accepted | LRI-02 fixture and retained historical downstream use reviewed in verification.md | Retain qualitative participant review without numerical incentives |
| Routine Domain additions and replacements | D2/D4 accepted | LRI-04/06 and historical registry/source tests pass | Check accepted authorities and exact binding scope |
| Pause, archive, and obligations | Proposed separation | LRI-05 funded Work and acceptance continue after archive | Retain independent lifecycle and payment behavior |
| Replay and race recovery | Forward append candidate | LRI-07 mixed-record, CAS, retry, and failure tests pass | Implement only after exact contract acceptance |
| Read-only and financial boundaries | Current boundaries retained | Runtime closure diff, trusted guard, offline replay, invariant | No new proof is claimed for the candidate |
| Runtime/dependency boundary | Existing Python/Git path candidate | Source inspection. No new runtime or dependency | Reconsider before a second journal, service, or executor change |
| Deployment and public scope | Explicitly not authorized | No activation or opening evidence | Separate exact approval after implementation review |

## Next authorized action

The operator accepts D1..D6 with the corrections below. Tasks bind Outcome 0.2, Spec 1.0, and Design 1.0.
Implementation verification covers each proposed scenario and preserves current closures, genesis, grants, canonical replay, balances, and escrow.
Native review, required CI, manual installation, exact package update, registry transition source, and Tide readback remain distinct gates.
The existing cover and public-repository gates remain pending and independent of this proposal.
The journal inherits WEA repository visibility. Its retained source policy needs that public-scope decision before public opening.
An initiative does not copy private task evidence, local sessions, or credentials into a public repository or card.

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

## Exact implementation boundary

`initiatives.State` retains registry-specific legacy Access states and accepted-time boundaries.
Historical grants retain their original bytes and registry hashes. New grants name the exact Domain record hash.
`wea-initiative-1` decisions use the existing journal, immutable sources, canonical identities, and bounded append/readback path.
The `activate-policy` record requires exact operator source, current installed package, body hash, and explicit workflow dispatch.
Before activation, ordinary initiative sources have no effects. The implementation PR does not activate this record.
Tide schema 4 retains exact binding scopes and optional initiative references. Schema 3 history keeps its original projections.
Source-time binding checks reject locator reuse and prevent old grants from following a new repository ID.
New Draft assignments require an active Steward at source time. Existing task obligations continue after pause or archive.
Metadata-only records do not trigger a Tide batch. The next meaningful batch retains the complete journal prefix.
The implementation uses no new dependency, service, worker, authoritative branch, or financial writer.

Initial size estimate: eight existing product files and one new module, about 1,100 changed product lines.
Tests and OLED records are separate evidence. Reconsider Design after three additional product files or 150 additional product lines.
