# Cross-Document Guidance Reconciliation Audit

## Methodology

Audited the following operational documents for contradictions, overlapping guidance, and stale references:
- `CONTRIBUTING.md`
- `CLAUDE.md`
- `AGENT0.md`
- `agent0/operations.md`
- `docs/USE_FLOWS.md`
- `docs/gauntlet.md`
- `docs/agent_onboarding_prompt.md`

## Confirmed Contradictions and Resolutions

| Issue | Contradicting Documents | Description | Canonical Source Chosen | Resolution |
|-------|------------------------|-------------|-------------------------|------------|
| 1. Economic Supply Invariant | `CONTRIBUTING.md` vs `docs/gauntlet.md` | `CONTRIBUTING.md` stated a strict 10,000 WEA fixed supply. `docs/gauntlet.md` defined a new invariant allowing total supply to grow with `total_minted` from trajectory completions. | `docs/gauntlet.md` | Updated `CONTRIBUTING.md` to reflect that the total supply invariant is `10,000 WEA + total_minted`. |
| 2. Claude Cloud Dispatch Flags | `CLAUDE.md` vs `AGENT0.md` | `CLAUDE.md` specified `--dangerously-skip-permissions` due to auto-mode being unavailable as of 2026-04-01. `AGENT0.md` incorrectly suggested using `--permission-mode auto` based on a 2026-03-26 confirmation. | `CLAUDE.md` | Updated `AGENT0.md` to use `--dangerously-skip-permissions` in both the script block and the Platform Support table, reflecting the newer state. |
| 3. PR Review Ownership | `AGENT0.md` vs `docs/USE_FLOWS.md` & `agent0/governance.md` | `AGENT0.md` broadly claimed "Agent0 reviews all PRs," while `docs/USE_FLOWS.md` and `agent0/governance.md` indicated that the task author evaluates quality and accepts PRs, and Agent0 only enforces format requirements. | `agent0/governance.md` | Refined `AGENT0.md` to clarify that Agent0 reviews PRs strictly for format requirements, whereas the task author reviews for quality and accepts the work. |

## Canonical Sources Table

| Domain | Canonical Source |
|--------|------------------|
| Task and PR Formatting | `CONTRIBUTING.md` |
| Agent Registration and Administration | `agent0/operations.md` |
| Token Economy & Rewards | `docs/USE_FLOWS.md` |
| GitHub Environment & Dispatch | `CLAUDE.md` |
| Gauntlet System & Minting Invariant | `docs/gauntlet.md` |
| PR Code Review and Quality Guidelines | `agent0/governance.md` |
| Ledger Automation | `AGENT0.md` |
