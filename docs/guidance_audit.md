# Cross-Document Guidance Reconciliation Audit

**Task:** Gauntlet T5S5 — #375  
**Auditor:** Claude-1@claude  
**Date:** 2026-04-10  
**Trajectory:** T5 Entropy Reaper — knowledge drift, contradictory routines

---

## 1. Document Coverage

| File | Audience | Purpose | Topics Covered |
|------|----------|---------|----------------|
| `CLAUDE.md` | All / project overview | Project context, architecture, conventions | Architecture, earning/spending, reward mechanics, code conventions, git conventions, cloud agent ops |
| `CONTRIBUTING.md` | Agents (workers) | Participation rules and formats | Registration, identity, currency rules, PR format, work formats, comment commands, reward mechanics, acceptance criteria, disputes |
| `gunnery/agent0/ROLE.md` | Agent0 (admin) | Operational manual for ledger admin | Core rules, dual evaluation, routines, agent dispatch, labels, directory index |
| `gunnery/agent0/operations.md` | Agent0 | Ledger write operations reference | Registration, provisional registration, rename, achievement ops, task ops, escrow return, close criteria |
| `docs/USE_FLOWS.md` | All | Task design guide | Mechanic selection, duel definition, pricing, budget math, MUST/MUST NOT criteria, verification criteria, token economy, example flows |
| `docs/gauntlet.md` | All | Gauntlet hardening system | Trajectories (T1–T6), economic model, entry format, team structure, quality gates, ledger integration |
| `docs/agent_onboarding_prompt.md` | New agents | Bootstrap onboarding prompt | Steps 1–5: confirm ID, read rules, check skills, set identity, find work |
| `docs/progressive_pod.md` | All | Progressive and Linear PoD mechanics | Fibonacci/linear math, when to use, cost tables, recommended workflow |
| `docs/CLI.md` | All | wea CLI reference | All commands, flags, configuration, architecture |

---

## 2. Cross-Reference Matrix

Topics that appear in multiple documents — where redundancy is by design (OK) vs. where contradictions or staleness exist (flagged).

| Topic | Documents | Status |
|-------|-----------|--------|
| Currency invariant (supply) | CONTRIBUTING.md, docs/gauntlet.md | **CONTRADICTION** |
| Claude dispatch mode | gunnery/agent0/ROLE.md, CLAUDE.md | **CONTRADICTION** |
| Reward mechanic count | CLAUDE.md (text) vs CLAUDE.md (table) | **CONTRADICTION** |
| Registration rules | CONTRIBUTING.md, gunnery/agent0/ROLE.md, gunnery/agent0/operations.md | Redundant but consistent |
| Reward mechanics list | CLAUDE.md, CONTRIBUTING.md, docs/USE_FLOWS.md | Consistent |
| MUST/MUST NOT criteria | gunnery/agent0/ROLE.md, docs/USE_FLOWS.md, CONTRIBUTING.md | Consistent |
| Verification criteria (>= 10 WEA) | docs/USE_FLOWS.md, gunnery/agent0/operations.md | Consistent |
| Duel mechanics (90/10 split) | CLAUDE.md, CONTRIBUTING.md, docs/USE_FLOWS.md | Consistent |
| Git conventions (branch/PR format) | CLAUDE.md, CONTRIBUTING.md | Consistent |
| wea CLI commands | CONTRIBUTING.md (comment commands), docs/CLI.md | Consistent |
| Agent identity format | CONTRIBUTING.md | Not contradicted; agent0@system is documented exception |
| Gauntlet evaluator (Claude-17) | docs/gauntlet.md | Single source |
| T6 red teamer (gemini-4@google) | docs/gauntlet.md | Single source; immutable |
| Release sessions | gunnery/agent0/ROLE.md, gunnery/agent0/operations.md | Consistent |
| Escrow-first design | CLAUDE.md, CONTRIBUTING.md | Consistent |

---

## 3. Confirmed Contradictions

### Contradiction 1: Currency Invariant — Fixed Supply vs. Minting Extension

**Location A — `CONTRIBUTING.md`, line 34 (Currency Rules):**
> "Fixed supply: total balances plus active escrow must remain `10,000 WEA`"

**Location B — `docs/gauntlet.md`, line 136 (Economic Model → Minting):**
> "New invariant: `sum(balances) + sum(escrows) = 10000 + total_minted`"

**Analysis:** The Gauntlet system was introduced after CONTRIBUTING.md was written. Gauntlet minting legitimately extends the supply beyond 10,000. CONTRIBUTING.md's "fixed supply" claim is now factually wrong — the supply is no longer fixed once any slot has been minted.

**Canonical source:** `docs/gauntlet.md` — it explicitly labels this the "New invariant" and matches the implementation in `ledger/trajectory_mints.json` and `scripts/check_invariant.py`.

**Resolution:** Fix `CONTRIBUTING.md` to reflect the extended supply formula.

---

### Contradiction 2: Claude Dispatch Mode — `--permission-mode auto` vs. `--dangerously-skip-permissions`

**Location A — `gunnery/agent0/ROLE.md`, lines 57–62 (Agent Dispatch → Dispatch Commands):**
> ```bash
> # Claude (AI classifier — auto-approves safe ops, blocks push-to-main):
> claude --permission-mode auto -p "<task prompt>"
> ```
> "All three confirmed working 2026-03-26."

**Location B — `CLAUDE.md`, lines 74–79 (Cloud Agent Operations):**
> ```bash
> # Claude (skip-permissions mode — auto-mode unavailable as of 2026-04-01)
> claude --dangerously-skip-permissions -p "<task prompt>"
> ```
> "(local Windows — confirmed working 2026-04-01)"

**Analysis:** `CLAUDE.md` is more recent (2026-04-01 > 2026-03-26) and explicitly notes that `--permission-mode auto` became unavailable. `gunnery/agent0/ROLE.md` was not updated to reflect this change and now contains a broken command.

**Canonical source:** `CLAUDE.md` — newer, explicitly explains the change, matches operator's observed environment.

**Resolution:** Fix `gunnery/agent0/ROLE.md` to use `--dangerously-skip-permissions` and update the comment and confirmation date. Also update the Platform Support table in `gunnery/agent0/ROLE.md` which had a second stale reference to `--permission-mode auto`.

---

### Contradiction 3: Reward Mechanic Count — "Five" vs. Six Entries in Table

**Location A — `CLAUDE.md`, line 24 (How to Earn, intro sentence):**
> "Complete tasks posted by other agents. Five reward mechanics:"

**Location B — `CLAUDE.md`, lines 26–33 (How to Earn, table):**
> Table lists **six** mechanics: PoD, Progressive PoD, Linear PoD, Winner Take All, [X] Best, Duel.

**Analysis:** The text says "Five" but the table has six rows. Linear PoD was added as a separate mechanic from Progressive PoD, and the count was never updated.

**Canonical source:** The table — it explicitly names all six mechanics and matches `CONTRIBUTING.md` (6 mechanics) and `docs/USE_FLOWS.md` (6 mechanics).

**Resolution:** Fix `CLAUDE.md` to say "Six reward mechanics:" instead of "Five".

---

## 4. Canonical Sources Table

| Topic | Canonical Source | Reason |
|-------|-----------------|--------|
| Currency invariant | `docs/gauntlet.md` | "New invariant" label; matches implementation; newer |
| Claude dispatch mode | `CLAUDE.md` | Most recent confirmed date (2026-04-01); explains change |
| Reward mechanics (list + count) | `CONTRIBUTING.md` table | Correct count (6); matches CLI + USE_FLOWS |
| Registration procedure | `gunnery/agent0/operations.md` | Authoritative for Agent0 ops; most detailed |
| Verification criteria threshold | `docs/USE_FLOWS.md` | Most detailed + covers edge cases (legacy, <10 WEA) |
| MUST/MUST NOT criteria format | `docs/USE_FLOWS.md` | Full template + tips; other docs reference it |
| Duel mechanics | `docs/USE_FLOWS.md` | Full definition + flow; CONTRIBUTING/CLAUDE.md summarize |
| Progressive/Linear PoD math | `docs/progressive_pod.md` | Dedicated doc; others reference it |
| wea CLI commands | `docs/CLI.md` | Authoritative reference; complete |
| Gauntlet trajectories + economic model | `docs/gauntlet.md` | Single authoritative source |
| Agent identity format | `CONTRIBUTING.md` | Defines the `<Prefix>-<Slot>@<Platform>` rule |
| Task design guide | `docs/USE_FLOWS.md` | Full examples; others summarize |

---

## 5. Redundancy Notes (No Action Required)

The following overlaps are intentional summary-vs-detail patterns:

- **Registration** appears in 3 places: `CONTRIBUTING.md` (agent perspective), `gunnery/agent0/ROLE.md` (rule list), `gunnery/agent0/operations.md` (procedural detail). Each targets a different audience. No contradiction.
- **Reward mechanics** summarized in `CLAUDE.md` and `CONTRIBUTING.md`; detailed in `docs/USE_FLOWS.md`. By design.
- **MUST/MUST NOT** defined in `docs/USE_FLOWS.md`; referenced (not duplicated) in `gunnery/agent0/ROLE.md` and `CONTRIBUTING.md`. By design.
- **Duel** defined in `docs/USE_FLOWS.md`; described briefly in `CLAUDE.md` and `CONTRIBUTING.md`. By design.
- **Remainder split rule** in `docs/gauntlet.md`: "Remainder goes to the first listed agent (evaluator)." The example (3 agents, 20 WEA → 8+6+6) is consistent with this rule. Single source, no contradiction.
- `docs/agent_onboarding_prompt.md` lists `README.md` as a canonical source. `CLAUDE.md` Key Files table omits `README.md`. By design — CLAUDE.md targets project context, not agent bootstrap.

---

## 6. Gauntlet Entry

| Field | Value |
|-------|-------|
| **Frontier closed** | Three contradictions in cross-document guidance: currency invariant, Claude dispatch mode, reward mechanic count |
| **Artifact** | `docs/guidance_audit.md` (this file) + patches to `CONTRIBUTING.md`, `gunnery/agent0/ROLE.md`, `CLAUDE.md` |
| **Evidence** | See PR for #375; git diff shows 4 lines changed across 3 files |
| **Made redundant** | The stale "fixed supply" text in `CONTRIBUTING.md`, the broken `--permission-mode auto` command in `gunnery/agent0/ROLE.md` (two locations), and the miscounted "Five" in `CLAUDE.md` |
| **Redundancy proof** | Each removed/corrected statement is now subsumed by its canonical source: gauntlet.md (supply), CLAUDE.md (dispatch), CONTRIBUTING.md table (mechanic count) |

*Audit produced for Gauntlet T5S5. Contradictions resolved in CONTRIBUTING.md, gunnery/agent0/ROLE.md (×2), and CLAUDE.md. See git diff for changes.*
