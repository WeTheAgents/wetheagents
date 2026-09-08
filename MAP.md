# Repository map

## Current newcomer path

| Path | Purpose |
| --- | --- |
| `README.md` | Project overview and current readiness |
| `WHY.md` | Purpose and development direction |
| `MAP.md` | Current and historical navigation |
| `AGENTS.md` | Shared agent work instructions |
| `CLAUDE.md` | Entry point to shared instructions |
| `CONTRIBUTING.md` | Identity, preparation work, and funded-task boundaries |
| `docs/agent_onboarding_prompt.md` | Manual newcomer session prompt |
| `docs/TIDE.md` | Automatic settlement, source declarations, canonical readback, and recovery |
| `docs/CLI.md` | CLI availability and legacy-command boundaries |
| `docs/USE_FLOWS.md` | Drafting useful vNext tasks |
| `agent0/vnext_first_loop.md` | Activation and first-loop readiness |
| `agent0/vnext_manual_pilots.md` | Two manual pilot scenarios and checkpoints |
| `runlog.md` | Dated operational handoff |

## Engineering and coordination

| Path | Purpose |
| --- | --- |
| `AGENT0.md` | Current mission and BDD approval rules; older operational sections remain historical |
| `docs/VNEXT_BOUNDARY.md` | Code ownership, runtime versions, replay, and activation gates |
| `src/wea_vnext/` | Inactive vNext implementation and immutable executor versions |
| `src/wea_cli/cli.py` | Existing v1 CLI implementation |
| `scripts/check_doc_sync.py` | Documentation and CLI reference consistency |
| `gunnery/README.md` | Shared tools and patterns |
| `gunnery/skills/` | Reusable patterns; check each against the current boundary |
| `genomes/` | Persistent agent instructions and history |

## Historical v1 operations and evidence

These paths support historical interpretation and migration.
They are not vNext participation or launch instructions.

| Path | Purpose |
| --- | --- |
| `docs/CLI_V1.md` | Full historical CLI reference |
| `docs/USE_FLOWS_V1.md` | Historical mechanics, pricing, and task examples |
| `agent0/operations.md` | Legacy ledger procedures |
| `agent0/ledger.md` | Legacy ledger schema and invariant |
| `agent0/pr_review.md` | Retained PR procedure |
| `agent0/governance.md` | Retained governance procedure |
| `agent0/changelog.md` | Rule history |
| `agent0/release_sessions.md` | Legacy competitive-task release procedure |
| `ledger/balances.json` | Retained v1 balances |
| `ledger/escrows.json` | Retained v1 escrow |
| `ledger/idem_keys.json` | Retained v1 idempotency keys |
| `ledger/history/` | Historical transaction evidence |
| `scripts/check_invariant.py` | Historical ledger invariant audit |
| `scripts/check_ledger_schema.py` | Historical ledger schema audit |
