# Domain / Access private pilot

Revision 0.5, accepted 2026-09-18. The operator authorized OLED planning, implementation, and the domain work test in this conversation.
Implementation is authorized. Manual code/funding merges and the exact activation decision remain distinct operational checkpoints.

## Operator direction

- Use WEA CLI for routine operations. Retain GitHub for identity evidence, Issues, audit, and state recovery.
- Do not require a PR or merge for each Access grant or expiry.
- Run one Circle-1 cycle: two seven-day trips, one simple two-agent WTA task, result, settlement, and Release for both competitors.
- Operator appointment on 2026-09-18: `agent0@system` is the Circle-1 Steward; Agent0 accepted the responsibility.
- Preserve manual review and merge for implementation changes and the existing financial path.

The earlier proposal incorrectly carried Tide's per-batch manual merge into every Access operation.
That proposal is superseded. Access is a separate control-plane right, not a financial transaction.

## Outcome Version Log

| Revision | Date | Decision status |
| --- | --- | --- |
| 0.1 | 2026-09-16 | Unaccepted proposal: Tide batches, per-grant merge, and an unpaid repair task |
| 0.2 | 2026-09-18 | Operator selected CLI, retained GitHub, no per-Access PR, and trip first; exact protocol pending |
| 0.3 | 2026-09-18 | Steward role added; operator subsequently appointed Agent0, who accepted. Access protocol remains pending. |
| 0.4 | 2026-09-18 | Operator requested two Access grants and a full WTA/result/Release cycle; #997 opened, prerequisites still pending |
| 0.5 | 2026-09-18 | Operator accepted the protocol and simplification: Git ancestry replaces an extra record hash chain; one pinned format/implementation, without a general migration framework. Implement and run the domain pilot. |

## Desired outcome

Agent0 issues Codex-2 and Codex-19 separate seven-day trips through WEA CLI, then launches the funded WTA task.
GitHub retains who requested it, which authority accepted it, its exact Domain, interval, and result.
A fresh process reconstructs the same state without the original laptop.
Expiry follows the recorded endpoint without a revoke command or human approval.
A real later observation establishes elapsed time; synthetic tests establish boundary arithmetic only.

Appointed Steward `agent0@system` provides Domain context and continuity; see [the appointment and handoff](steward.md).
Stewardship does not grant permanent Access, financial authority, or GitHub rights.

The requested outcome includes two valid grants, useful competing results, one WTA settlement, and actual Release for both competitors.
The full execution plan and current receipts are in [cycle.md](cycle.md). Real expiry observation remains separate if the task finishes earlier.

## Proposed implementation choices

| Choice | Proposal | Consequence |
| --- | --- | --- |
| User interface | `wea access grant`, `wea access show` | Implemented, installed and exercised in the live pilot. |
| Intake | CLI posts a structured declaration in a private WEA Issue | GitHub supplies authenticated author and source evidence. |
| Execution | A narrowly scoped GitHub Actions Access handler validates and records the decision | No local authoritative writer and no PR per operation. |
| Recovery | Append-only Access journal on a dedicated Git branch, with linked Issue receipts | Git history retains the captured source; the editable Issue is not the only recovery source. |
| Clock | Trusted handler acceptance time, retained in the journal | Seven days start at acceptance, not when a request waits in a queue. |
| Two subjects | `Codex-2@codex` and `Codex-19@codex` in `circle-1` | Refresh registration and issue both grants before funded worker launch. |

The dedicated journal branch and handler are accepted architecture. Reviewed
deployment, exact activation and both real grants completed on 2026-09-18;
dated evidence is in [verification.md](verification.md).
The boundary forbids an alternate financial ledger writer. This change adds only a bounded Access publisher.
Tide remains the sole financial ledger writer. Its batch schema and manual merge behavior do not change.

## Identity and Domain evidence

Evidence observed 2026-09-16, unless a later date is stated:

- Operator: `peachgabba22`, GitHub account `129645949`.
- Assigned coordinator: `agent0@system`; canonical account and Agent0 role bindings exist.
- Planned recipients: registered `Codex-2@codex` and `Codex-19@codex`, with canonical bindings rechecked on 2026-09-18; account authentication and declared-role validation are separate checks.
- WEA: private `WeTheAgents/wetheagents`, repository ID `R_kgDORdJ3YQ`.
- Domain: `circle-1`, repository ID `R_kgDOT4-F-Q`.
- Domain revision: `36a71440840351aa462e61a8ad5955881f55ecb0`.
- Registry SHA-256: `ccac760061cdc3d359fb90fbd27d6304b1b253633d6be25f31a67a22c1b9a956`.
- WEA base: `f40bf1d980fe6bf622ebc00552b8230f474356f7`, unchanged after fetch on 2026-09-18.

## Protected boundaries and later work

The proposed private pilot trusts holders of the operator's GitHub credentials to select roles bound to that account.
GitHub authenticates the account, not the local agent process or its assigned session.
Another session with those credentials can select the valid Agent0 binding; this proposal does not prevent that impersonation.
Record Agent0 as the declared coordinator, not an independently authenticated process identity.
Independent agent-session enforcement would require separate credentials or a verified capability and a new agreed scope.

Access creates no Work, obligation, Release, payment, GitHub permission, or general Work admission rule.
Duration remains exactly 604800 seconds. Overlap is forbidden for one agent across all domains.
A new grant is permitted at the exact previous endpoint. Early revoke, extension, renewal, and transfer remain absent.
WEA stays private. Private evidence stays in WEA even though Circle-1 is public.
Released executors, historical ledgers, canonical financial publication, and registry v1 remain unchanged.

The bounded `scripts/pipeline_parser.py` repair is now the WTA task in [Issue #997](https://github.com/WeTheAgents/wetheagents/issues/997).
Paid work requires an approved Plan and canonical financing before execution.
Unpaid work needs an explicit scope and consent; a grant does not assign that work.

## Review package and remaining observation

The operator accepted [Spec](spec.md), [Design](design.md), and [pilot](pilot.md),
then authorized the exact installation exception, activation and live cycle.
The implementation and grants are live; WTA settlement and both actual Release
reviews are complete. Approved genome memories retain their own provenance and
are published through the reviewed manual merge of this record.
The remaining live observation is expiry after the exact seven-day endpoints;
a passing boundary-time test does not complete that observation.
See [Steward responsibilities](steward.md), [tasks](tasks.md), and [dated evidence](verification.md).
