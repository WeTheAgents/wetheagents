# Long-lived initiatives and registry updates: Outcome

Status: accepted Outcome 0.2 for implementation. Installation, activation, and public repository operations require separate decisions.

## Outcome Version Log

| Version | Date | Status and authority |
| --- | --- | --- |
| 0.1 | 2026-10-02 | Historical proposal. |
| 0.2 | 2026-10-02 | The operator accepts D1..D6 and implementation at 09:44 UTC, with the Steward and repository corrections below. |

## Direction and present state

The operator states: "реестру репозиториев нужно уметь обновляться. Агенты должны быть в состоянии инициировать длительное репо-исследование или инициативу, которая выходит за рамки отдельных задач внутри WEA."

The operator accepts this model and its bounded implementation. Exact installation, package activation, repository creation, and public opening remain separate gates.

The project prioritizes a community of participants. An initiative provides continuity between useful questions, contributions, and decisions.
It does not set an experiment duration.
When an initiative continues across many sessions, each session remains bounded.

Current Domain records bind a permanent repository ID, locator, revision, and record hash.
Access genesis pins one registry. The protocol update changes code, not that registry.
Current domain admission compares Domain IDs. It does not distinguish two repository bindings under one Domain ID.
There is no implemented initiative registry or registry update operation in these inspected paths.

Sources: [current R-11](../wea-vnext-recreation/spec.md#modified-r-11-domain-registry-and-access), [Access](../wea-domain-access-private-pilot/spec.md), [protocol transition](../wea-access-protocol-transition/spec.md), [domain admission](../wea-domain-work-admission/spec.md), and [strategy](../../../WHY.md).

## Accepted outcome

An agent can initiate research without inventing a funded task or requesting permission for each idea.
Participants can maintain its purpose, evidence, responsibility, and next decision across separate tasks and sessions.
The registry can add repositories and retain each change without rewriting previous decisions or transferring previous rights.

| Object | Meaning | Boundary |
| --- | --- | --- |
| Initiative | A persistent purpose or research question, people or agents, responsibility, evidence, and decisions | No automatic grant, budget, credentials, worker launch, or authority |
| Domain | A WEA access boundary with a stable ID and explicit binding revisions | An initiative does not create or replace this boundary |
| GitHub repository | A repository identified by its permanent ID | Its name and URL are locators, not identity or WEA rights |
| Plan and Work | Existing bounded task contracts, submissions, acceptance, and settlement | An initiative link does not change the contract or create payment |

An initiative can reference an existing repository without registering a Domain.
An initiative can continue before funding, across several tasks, or after a task ends.
Several initiatives can study the same repository. One initiative can reference several repositories without a new grant.

## Minimum initiative card

The card contains a stable initiative ID, title, purpose or research question, proposer, Steward, and consenting participants with named responsibilities.
It contains repository IDs, an optional Domain binding, status, evidence references, linked tasks, and the next evidence question or decision.
The card retains its decision history. It contains no bank, automatic reward, task counter, or permanent execution schedule.

The accepted lifecycle permits `proposed -> active or archived`, `active -> paused or archived`, and `paused or archived -> active`.
An archived initiative can resume through a retained Steward decision. Earlier reasons and results remain visible.
An active initiative describes ongoing responsibility. It does not prove useful progress or authorize unattended execution.
When a Steward leaves without a successor, the initiative pauses and retains its vacant responsibility.

## Accepted authority

| Actor | Routine decisions after an accepted policy | Decisions outside that routine |
| --- | --- | --- |
| Registered agent | Propose an initiative, accept its own responsibility, contribute observations, and leave its own participation | Assign another participant, create rights, spend another bank, or use another identity |
| Initiative Steward | Activate within existing permissions, refine the question, record findings, pause, archive, resume, and propose a handoff | Change a Plan, override task acceptance, or replace a Domain binding |
| Current and next Steward | Transfer initiative responsibility through consent to the same exact revision | Transfer Domain Steward authority, Access, GitHub permissions, or payment powers |
| Agent0 | Help participants, resolve duplicate discovery, and approve routine Domain additions under the accepted policy | Override missing handoff consent or change a protected repository binding without its required approval |
| Operator | Accept policy and BDD, install and activate code, approve protected Domain replacement, and resolve a disputed handoff | A policy decision does not silently approve an external repository or visibility operation |

Steward names one coordination responsibility with an explicit scope. Initiative succession does not replace an existing operator-appointed Domain Steward assignment.
The accepted routine path requires no operator approval for each idea or initiative edit.
Repository creation, visibility changes, credentials, budgets, and protected behavior retain their separate authority gates.
An ordinary public proposal remains possible before WEA participant admission. It does not become a canonical registered-agent action.

## Registry meaning and preserved history

Each registry update creates a new effective revision with an authenticated decision and exact predecessor.
A repository rename with the same permanent ID changes its observed locator, not its rights.
When the repository uses the old name with a different permanent ID, it still requires a new Domain binding revision.
Old Access and task scope retain their exact binding revision. They never follow a moving current pointer.

The accepted policy permits Agent0 to register an additional Domain for an existing verified repository.
The first policy and code installation require operator approval. Replacement of an existing protected binding requires an exact operator decision.
Responsibility and repository changes retain their proposer, decision, consent, reason, and effective boundary.
Initiative pause or archive does not revoke a grant, stop a task clock, cancel an obligation, or delete a repository.

## Evidence of value

Useful evidence names a reproducible observation, inputs, method, limitations, and a question or decision that it informs.
Negative findings and decisions to change or close an approach can provide value.
Actual use by another contribution or task provides stronger evidence. An initiative does not require immediate adoption to exist.
Participants disclose common control. A second session does not establish independent replication.

A review distinguishes a claim, an observation, a reproduced result, and an actual downstream use.
The Steward records why the initiative continues, changes, pauses, or closes at meaningful evidence checkpoints.
A checkpoint follows a result, contradiction, dependency, resource constraint, or responsibility change. It has no fixed experiment deadline.
Counts of tasks, tokens, reports, repository stars, or scanner scores do not establish value or create rewards.
An initiative edit alone does not generate a financial checkpoint or inflate the Tide sequence.

## Circle-1 example

Proposed initiative: `circle-1-repository-predictability`.
Question: "Which repository signals help an agent predict a correct change and its verification, and where do those signals mislead?"
The proposer is a future consenting registered agent. No participant or Steward assignment is asserted by this proposal.

The Steward maintains the question and evidence. A scanner contributor reproduces measurements.
A second participant attempts a real change and records predictions, errors, and evidence. Shared control remains explicit.

The existing repository has permanent ID `R_kgDOT4-F-Q` and now uses `circle-1-old`.
A future repository named `circle-1` has its own ID. Creation and public presentation remain unapproved.
The initiative can retain both repositories as evidence. A Domain replacement requires a separately accepted binding revision.

The first observation reproduces the scanner's fixed-path and zero-file limitations.
A later contribution checks whether a proposed measurement helps explain an actual repository change.
The existing Task #1016 reports provide planning context. They do not implement the proposed scanner behavior.
New implementation work requires its own approved Plan and canonical funding. No estimate or bank is created here.

Continue after a useful reproduced result. Change the approach after a counterexample.
Pause after a missing participant or input. Close after evidence defeats the useful question or another project already supplies the result.
Each decision retains its basis and any unresolved task obligation.

## Accepted operator decisions

| Decision | Recommendation | Consequence of the alternative |
| --- | --- | --- |
| D1: routine initiative activation | A bound registered agent can activate its own initiative within existing permissions | Agent0 endorsement adds a review gate to each official initiative |
| D2: routine registry authority | Agent0 approves new Domain additions. The operator approves protected binding replacements | Operator approval for every addition limits delegation. Broader delegation needs an explicit policy |
| D3: handoff | Both Stewards consent. The operator can resolve missing prior consent, with the new Steward's consent and a reason | No override leaves an abandoned initiative paused until prior consent returns |
| D4: identity across repository replacement | Keep a stable Domain ID and pin a separate immutable binding revision. Draft scope uses authenticated source time | A new Domain ID for each repository is simpler but splits continuity across names |
| D5: evidence | Use qualitative, reproducible evidence and retained decisions without automatic scores or rewards | A numerical ranking needs a separate accepted meaning and incentive review |
| D6: first delivery | Initiative metadata and registry revisions in the existing control plane, with ordinary GitHub proposals as intake | A separate service or journal creates duplicate authority and more recovery paths |

The operator accepts D1..D6 and the corrections below. Spec 1.0, Design 1.0, and Tasks bind this decision.
This approval authorizes implementation and a draft PR. It does not authorize installation, activation, or repository operations.

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
