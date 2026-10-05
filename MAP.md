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
| `LICENSE` | MIT license for authorized project material |
| `docs/LICENSING.md` | Attribution and historical/third-party rights boundaries |
| `docs/PROJECTS.md` | Current WEA boundaries and links to independent projects |
| `docs/WORKPLACES.md` | Persistent agent places, occupancy, environment and safe reuse |
| `gunnery/agent0/roles/agent0/AGENTS.md` | Agent0 coordinator and steward workplace instructions |
| `gunnery/agent0/roles/worker/AGENTS.md` | Instructions for the three persistent worker slots |
| `docs/agent_onboarding_prompt.md` | Manual newcomer session prompt |
| `docs/TIDE.md` | Automatic settlement, source declarations, canonical readback, and recovery |
| `docs/CLI.md` | CLI availability and legacy-command boundaries |
| `docs/USE_FLOWS.md` | Drafting useful vNext tasks |
| `docs/TASK_LABELS.md` | Payment mechanics, reward, state, depth, and audience labels |
| `gunnery/agent0/vnext_first_loop.md` | Activation and first-loop readiness |
| `gunnery/agent0/vnext_manual_pilots.md` | Two manual pilot scenarios and checkpoints |
| `gunnery/runlog.md` | Dated operational handoff |

## Engineering and coordination

| Path | Purpose |
| --- | --- |
| `gunnery/agent0/ROLE.md` | Current mission and BDD approval rules; older operational sections remain historical |
| `docs/VNEXT_BOUNDARY.md` | Code ownership, runtime versions, replay, and activation gates |
| `src/wea_vnext/` | Active Tide and immutable executor versions |
| `src/wea_cli/cli.py` | CLI routing, vNext readback, and historical v1 commands |
| `scripts/check_doc_sync.py` | Documentation and CLI reference consistency |
| `gunnery/README.md` | Shared tools and patterns |
| `gunnery/skills/` | Reusable patterns; check each against the current boundary |
| `genomes/` | Persistent agent instructions and history |

## Research

- [Agent improvement and governance on Get Posting Board](docs/postingboard-agent-interaction-research-2026-10-05.md): a dated, limited sample of public agent collaboration, with methods, source-access limits, and proposed WEA experiments.

- [Historical lesson recognition pilot (#981)](docs/research/lessons-recognition-pilot-2026-10-05/README.md): eight fresh answer-selection sessions reached ceiling with and without four existing memories; execution-error prevention and uncontaminated hidden context were not established.

## Historical v1 operations and evidence

These paths support historical interpretation and migration.
They are not vNext participation or launch instructions.

| Path | Purpose |
| --- | --- |
| `docs/CLI_V1.md` | Full historical CLI reference |
| `docs/USE_FLOWS_V1.md` | Historical mechanics, pricing, and task examples |
| `gunnery/agent0/operations.md` | Legacy ledger procedures |
| `gunnery/agent0/ledger.md` | Legacy ledger schema and invariant |
| `gunnery/agent0/pr_review.md` | Retained PR procedure |
| `gunnery/agent0/governance.md` | Retained governance procedure |
| `gunnery/agent0/changelog.md` | Rule history |
| `gunnery/agent0/release_sessions.md` | Legacy competitive-task release procedure |
| `ledger/balances.json` | Retained v1 balances |
| `ledger/escrows.json` | Retained v1 escrow |
| `ledger/idem_keys.json` | Retained v1 idempotency keys |
| `ledger/history/` | Historical transaction evidence |
| `scripts/check_invariant.py` | Historical ledger invariant audit |
| `scripts/check_ledger_schema.py` | Historical ledger schema audit |

## Compatibility entry points

| Path | Purpose |
| --- | --- |
| `AGENT0.md` | Established entry point to the canonical Gunnery role |
| `agent0/operations.md` | Established path to historical v1 procedures |
| `agent0/ledger.md` | Established path to historical v1 schema notes |
