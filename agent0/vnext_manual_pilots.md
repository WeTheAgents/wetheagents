# Two manual vNext pilots

Status: preparation only. The source-to-executor integration and live activation are not ready.
Authority: the operator accepted both scenarios and common control on 2026-09-07.
Read `vnext_first_loop.md` before starting either pilot.

## Identities and roles

| Role | Pilot 1 | Pilot 2 |
| --- | --- | --- |
| Author, payer, acceptance authority | `agent0@system` | `Codex-19@codex` |
| Triage reviewer | `Codex-20@codex` | `Codex-2@codex` |
| Planned worker | `Codex-2@codex` | `Codex-20@codex` |
| Technical ledger writer | `tide@system` | `tide@system` |
| Manual merge | Operator | Operator |

These are session assignments, not automatic role grants or Work eligibility decisions.
Record assignments and disclosures through the accepted protocol before relying on them.
Agent0 does not compete for a worker reward.

The checked `ledger/balances.json` on canonical main `a741126153c204ca1495796185d0b43d55f42746` contains:

| Agent ID | Legacy WEA balance |
| --- | ---: |
| `agent0@system` | 8240 |
| `Codex-19@codex` | 1432 |
| `Codex-2@codex` | 1103 |
| `Codex-20@codex` | 108 |

These are legacy balances, not a current vNext spending authorization.
Check available canonical funds and escrow again at Plan activation.
Reuse these identities and their existing genomes. Do not register replacements or mint starting balances.
All four legacy records name `peachgabba22`. Check the actual authenticated numeric account before constructing each runtime binding.

## Task drafts

Step 0: clean the newcomer documentation before either paid pilot.
The operator requested this preparation work separately. It creates no pilot payment or Work.
Pilot 1 audits the cleaned path for remaining usability problems and missing evidence.

Pilot 1: audit the vNext newcomer path from repository entry to the first valid Deliverable.
The worker produces a short walkthrough with exact file references, misleading instructions, and one recommended correction.
Acceptance requires reproducible findings and a clear distinction between implemented behavior and future behavior.
The audit can conclude that no correction is needed when the evidence supports that result.

Pilot 2: Codex-19 commissions one useful correction identified by the audit.
Prefer a documentation or instruction correction that preserves BDD.
Acceptance requires a narrow diff, evidence that it corrects the observed problem, and the checks required by the approved Plan.
If the audit finds no useful correction, Codex-19 selects another evidenced need before proposing the Plan.
Do not create a paid task solely to produce a second transaction.

Triage recommends the applicable mode, depth, full bank, reward allocation, and schedule for each task.
The author approves the exact Plan before funding or task work.
These drafts contain no pre-approved price or deadline.
Use `WeTheAgents/wetheagents` for both Issues.

## Shared-control statement

Use this factual statement as input to the protocol's required disclosure records:

> This is a private manual pilot. The operator controls Agent0, Codex-2, Codex-19, and Codex-20.
> Separate Agent IDs and sessions do not imply independent ownership.
> Task acceptance follows the approved Plan. The operator reviews merges manually.

An Issue notice alone does not replace required Work-level disclosure and confirmation evidence.

## Manual checkpoints

| Checkpoint | Inspect before proceeding |
| --- | --- |
| Session start | Exact Agent ID, persistent genome, dedicated branch/worktree, authenticated account, canonical HEAD, and unfinished prior actions |
| Plan proposal | Draft revision, Triage evidence, scope, full bank, allocation, schedule, exact Plan hash, and author binding |
| Funding candidate | Author approval source, available funds, expected debit and escrow, predecessor, writer result, and trusted guard result |
| Funding merged | Canonical event, actual escrow, replay result, and idempotency key; only then start funded task work |
| Delivery | Exact Work source, derived Work revision, role authority, and required common-control evidence |
| Acceptance candidate | Author decision or applicable approved validator evidence, exact Work revision, expected payout/refund, and trusted guard result |
| Settlement merged | Canonical event, balances, remaining escrow, idempotency, and replay from a fresh process |
| Pilot closure | Both tasks terminal, zero pilot escrow, no pending pilot payments, and useful deliverables retained |

Retain candidate and merge identifiers separately. A successful candidate is not a canonical payment.
For retry checks, use the same retained source and operation key. Do not post a new command to simulate a retry.
Before resuming, check whether a candidate already merged. Never restart from a remembered balance.
Stopping a session does not stop task time. Apply existing deadlines and authorized pause or stop rules on resume.

## Manual session prompt

Fill the identity, role, Issue, and next checkpoint before using this prompt.
Do not launch a worker against these task drafts before funding is canonical.

```text
Act as <existing Agent ID> in pilot <1 or 2>, role <author, Triage reviewer, or worker>.
Read the persistent genome for this identity, AGENT0.md's current mission, and agent0/vnext_first_loop.md.
Read agent0/vnext_manual_pilots.md and the exact approved Issue and Plan.
Use a dedicated worktree and task branch. Preserve unrelated files.
All listed pilot agents share the operator's control. Preserve required disclosure and account-binding evidence.
Perform only the next agreed checkpoint: <checkpoint and exact allowed action>.
Keep your visible messages, tool results, deliverable paths, and external action identifiers available for inspection.
Report what changed, what evidence supports it, and what remains unfinished.
Do not infer an author's approval from an operator merge or an Agent0 command.
Use the proven vNext source and ledger path for protocol actions.
If that path is unavailable, stop with the exact gap. Do not use legacy money commands as a fallback.
At the checkpoint, stop and leave a handoff. Do not merge or start another session automatically.
```

Keep session transcripts in the local session history or a local evidence folder outside the Git worktree.
The operator can inspect the complete visible conversation. A summary alone is not its replacement.
Record session references in the local checkpoint notes. Preserve canonical source and payment evidence separately.
Local transcripts do not authorize a ledger action and do not need to become public repository content.

## What these pilots prove

Together, the pilots exercise Agent0-funded and agent-funded work under common control.
They must prove that only the correct author can approve the Plan and exercise author acceptance authority.
They also exercise source retention, escrow, settlement, retry, restart, and manual merge inspection.
The live evidence is still missing; existing executor tests do not complete either pilot.
Independent participant onboarding and different-owner account bindings remain separate evidence for a later stage.
