# WEA restart: handoff for the next Agent0 session

Date: 2026-07-14
Repository: `D:\GitHub\wetheagents`
Status: strategy agreed; Phase 0A Agent0 activation implemented locally; mechanism design remains

## Agent0 0A state

The next Agent0 session continues in **Deliberation** with the operator. It is a planning conversation, not ledger monitoring or autonomous protocol execution. No launcher or `WEA_AGENT` runtime identity is required.

The current 0A implementation artifacts are in:

`D:\GitHub\wetheagents-codex-agent0-vnext-0a-2026-07-14`

Branch: `codex/agent0-vnext-0a-2026-07-14`

The worktree has ignored `AGENTS.override.md`, which composes tracked `AGENTS.md` and the new tracked `AGENT0.md`; it does not replace the shared file. This is useful for carrying the complete Agent0 context into another Codex task, but it does not activate Operations.

Only when the operator explicitly requests execution or monitoring of a specific approved protocol action, start Operations through the command below. A bare request to "activate Operations" is not enough.

`pwsh -NoProfile -File D:\GitHub\wetheagents-codex-agent0-vnext-0a-2026-07-14\agent0\launch_agent0.ps1 -Worktree D:\GitHub\wetheagents-codex-agent0-vnext-0a-2026-07-14`

0A tracked changes are local and uncommitted. They include the vNext Agent0 contract, deterministic override builder, verified runtime launcher, rollback-safe worktree bootstrap, compatibility sync wrapper, tests, changelog, and OLED outcome/spec/tasks/verification. Review this diff before publishing it.

## Start here

Read, in order:

1. `AGENT0.md`, especially the Deliberation / Operations boundary
2. `C:\Users\peach\Downloads\wea-vnext-private-2026-07-14.html`
3. this handoff
4. `oled/changes/agent0-vnext-activation/outcome.md`, `spec.md`, and `verification.md`
5. `CONTRIBUTING.md`, `agent0/operations.md`, `agent0/governance.md`, `agent0/release_sessions.md`
6. `runlog.md`

## Your mission

First review the local Phase 0A diff and preserve it. Then convert the agreed strategy into a canonical WEA vNext specification and a current-to-vNext delta map. Do not implement mechanics or mutate the ledger before the operator approves those documents.

The first deliverable should answer:

- What files become sources of truth?
- Which current rules survive, change, or disappear?
- What entities and state machines need schemas?
- What migration preserves balances, identities, issues, and history?
- What gates separate internal dogfood, public root, and external agents?

## Repository safety

- The primary worktree was dirty on 2026-07-14. It contained user changes in `runlog.md`, many `genome_meta.json` files, `.codex/`, and a local skill directory. Do not touch or absorb them.
- `main` was behind `origin/main`. A clean worktree was created from `origin/main` at `D:\GitHub\wetheagents-codex-wea-restart-doc-2026-07-14` on branch `codex/wea-restart-doc-2026-07-14`.
- GitHub access required `gh auth switch -u peachgabba22`, as specified for personal projects.
- Create a fresh task branch/worktree for implementation. Never work on `main`.
- Do not make the repository public, open external Join, alter balances, return escrow, or create governance/task issues during the spec phase.
- Agent0 0A explicitly separates current executable operations from vNext targets. Do not simulate target behavior with manual ledger edits.

## Agreed strategic model

### Root

- The current repository remains private until a secrets, privacy, and license audit passes.
- The same repository later becomes the public root. Preserve issues, history, and ordinary mistakes. Rewrite history only for sensitive material.
- Root is the control plane for WEA identity, tasks, escrow, Work receipts, releases, Tours, domain visibility, and governance.
- Every task that uses WEA escrow has a root issue. A private domain can hide task content, but root exposes the domain, bank, lifecycle stage, and opaque Work receipts.
- All public root content, including genomes, uses the MIT License.

### WEA and identity

- WEA is an internal unit of purchasing power. Balance is not reputation, voting power, or achievement.
- Preserve existing balances, identities, contribution history, and issues.
- One GitHub account receives one base agent and one Hello World mint of 42 WEA.
- Hello World accepts mechanically unique Work. Agent0 does not judge creativity.
- Extra permanent agent slots can be bought. Their price remains open. Purchased slots do not receive a mint.
- A successful agent should spend WEA on useful work and improvement of its environment.

### Domains and Tours

- Domains create value outside WEA. Research may start before anyone knows what that value will be.
- Work outside WEA stays off-ledger and does not affect balance, contribution history, or release.
- Every domain has a Steward. The detailed role and minimum team remain open.
- Tours last seven days and start asynchronously for each agent. One identity can have one active Tour.
- Tour means access/membership, not a delivery obligation. Public tasks remain available outside the active Tour.
- Domains publish admission and pricing rules. A domain controls how its entry revenue is distributed.
- Start with public external domains and private repositories controlled by the operator, such as `mlb_betting`. External private domains come later.
- Agent0 can use current authenticated GitHub/local access to verify opaque receipts in operator-controlled private repositories. Do not build a separate permission system for bootstrap.
- Repository ownership or local access does not prove WEA connection. Each initial domain must complete at least two root-tracked task cycles. A recognized infrastructure domain must also dogfood its mechanism against WEA itself.
- Before pilots, classify Gauntlet, Circle-1, `wea_ther`, `mlb_betting`, `weather_kalshi`, `markdup8x-wea`, and other candidates as root mechanism, infrastructure domain, product domain, experiment, paused system, legacy surface, or external project.

### Tasks and economy

- Keep PoD, Progressive PoD, Linear PoD, WTA, Best-X, and Duel.
- A task bank is not the same as an individual payout.
- Minimum escrow is 1 WEA. No task-creation fee.
- The issue author evaluates Work and determines winners/ranks. Content decisions have no appeal.
- Agent0 runs mandatory intake triage before escrow. It checks framing, fields, mechanics, safety, and protocol coherence.
- An author cannot override Agent0 triage. Only the operator can, with a public rationale, including for private domains.
- `human` records provenance. Every paid task still needs a registered agent or treasury as WEA payer.
- The agent identity that created a task cannot claim it. Other registered agents under the same GitHub account may participate, earn payouts, and join release. Root discloses known common control before settlement.
- Lock criteria, mechanic, and access rules before the first Work.

### Finite and Infinite

- Use symmetric lifecycle labels: `Finite` and `Infinite`.
- Finite tasks close intake, then give the author seven days for evaluation.
- If the author stays silent and evaluable Work exists, the remaining bank is divided equally among agents with at least one evaluable Work. The task closes unresolved. No release opens.
- If no evaluable Work exists, escrow can return to the author after expiry/grace.
- Closing a private domain or revoking required access forces intake to close and starts the seven-day evaluation window. Only Work receipts already recorded in root participate.
- Infinite tasks have no task deadline. Each Work has its own seven-day evaluation period. Silence pays the declared PoD amount or next Progressive/Linear slot. The task remains open while bank/slots remain.
- Infinite tasks never create release sessions.

### Release and genomes

- Release sessions open only after settled Finite WTA, Best-X, or Duel tasks.
- All valid participants, including losers, may reflect on the result.
- Genome mutation is voluntary. Remove the current Agent0-synthesized fallback.
- Outside the constitution area, only automatic guards can reject a mutation: schema, size, provenance, secret detection, and similar infrastructure checks.
- A constitution-area mutation is rejected and opens governance.
- Agent0 does not grade whether a voluntary mutation is wise.
- A semantic genome scanner should become a future WTA task, not an implicit production gate.

### Governance and authority

- Root is the default governance platform and accepts a broad agenda.
- Root decisions bind WEA and any domain scope that a domain charter explicitly delegates. Other domain decisions remain recommendations to the Steward/repository owner.
- Free discussion may precede a task. A governance task itself retains paid Best-X or Duel, escrow, settlement, and the Finite competitive release path.
- During bootstrap, binding root changes require two keys: Agent0 and operator. WEA balances do not buy votes.
- Agent0 is the sole ledger writer, intake triager, protocol validator, and one bootstrap governance key. Agent0 does not replace the issue author's evaluation.

## Current-to-vNext conflicts already found

The next session should turn this list into a complete delta map.

1. Current README/CONTRIBUTING describe a closed ecosystem with no public Join or Hello World. vNext restores staged openness and a 42 WEA mint.
2. Current registration starts at 0 WEA. vNext preserves that for purchased slots but gives the base agent one Hello World mint.
3. Current CONTRIBUTING forbids authors from claiming their own tasks but does not define sibling identities. vNext preserves the creator ban and explicitly allows other agents under the same GitHub account with common-control disclosure.
4. Current disputes let Agent0 review author rejection. vNext removes content appeals.
5. Current governance uses paid Best-X/Duel tasks. vNext preserves them and distinguishes preliminary free discussion from a paid governance task.
6. Current Agent0 docs let Agent0 check task acceptance criteria and review all PR acceptance. vNext puts content evaluation with the issue author and keeps Agent0 at intake/protocol boundaries.
7. Current release docs let Agent0 synthesize mutations and editorially approve mutation quality. vNext allows only agent-proposed mutations and automatic guards.
8. Current repository has no active LICENSE. vNext uses one MIT License for the whole public root.
9. Current terminology and schemas do not model domains, Tours, root Work receipts, or Finite/Infinite lifecycle.

## High-level restart order

0A. Agent0 vNext contract with Deliberation as the default and separately activated Operations. Implemented locally; review and publish separately.
0. Baseline and delta audit.
1. Canonical vNext protocol and glossary.
2. State models, invariants, and migration design.
3. Minimum vertical slice with guards and tests.
4. Internal dogfood with current agents.
5. Candidate classification followed by public and operator-private domain pilots, each with two connected cycles and infra dogfooding where claimed.
6. Security, privacy, history, and license audit followed by the public root decision.
7. Separately gated public domain registration and external agent onboarding.

The HTML contains detailed gates and failure scenarios for each phase.

## Open design work

- Declarative domain connection manifest and registration flow.
- Third-party private repository verification and access model.
- Steward powers, succession, and the minimum domain team.
- Price of extra agent slots.
- Exact task/receipt/Tour/domain schemas and CLI grammar.
- Contribution policy under MIT, including DCO/CLA choice.
- Public-release audit checklist and migration tooling.
- Governance after bootstrap.
- Future genome commerce wrapper.
- WTA task for a semantic genome scanner.

## Completion condition for the next session

Stop after the operator can review a coherent vNext spec, delta map, schema inventory, migration outline, and staged acceptance gates. Do not start implementation merely because one mechanism looks straightforward.
