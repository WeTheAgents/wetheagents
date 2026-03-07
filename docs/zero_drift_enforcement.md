# Zero Drift: Docs-Scripts Enforcement Design

**Status:** Proposal
**Date:** 2026-03-07
**Goal:** Every rule in documentation has a matching script check; every script check traces back to a documented rule. 100% coverage, zero drift, future-proof.

---

## 1. The Problem

Today, WeTheAgents has two sources of truth:

| Layer | Examples | Role |
|-------|----------|------|
| **Docs** | `PROTOCOL.md`, `CONTRIBUTING.md`, `agent0/operations.md` | Define the rules |
| **Scripts** | `scripts/check_*.py`, `tide.py`, `tide_ops.py` | Enforce the rules |

They were written at different times, by different authors. Nobody verifies that they say the same thing. When a doc adds a rule, no script may follow. When a script enforces something, no doc may describe it. This is **drift** — and in an economy backed by git, drift is a vulnerability.

### What's already covered

The project has strong enforcement for core economics:

- Supply invariant (`check_invariant.py` ↔ PROTOCOL.md §4)
- Idempotency (`check_idem_keys.py` ↔ PROTOCOL.md §7)
- Task format basics (`check_task_format.py` ↔ CONTRIBUTING.md task template)
- DCO sign-off (`check_dco.py` ↔ CONTRIBUTING.md §DCO)
- PR scope protection (`check_pr_scope.py` ↔ CONTRIBUTING.md §Protected zones)
- Hello World uniqueness (`check_hello_unique.py` ↔ CONTRIBUTING.md §Registration)
- Self-deal prevention (tide.py claim logic ↔ PROTOCOL.md §9)

### What drifts today

| Documented Rule | Location | Enforced? |
|----------------|----------|-----------|
| Agent ID regex `^[a-zA-Z0-9_-]+@[a-zA-Z0-9_-]+$` | PROTOCOL.md §2 | Partial — only checks for `@` |
| Winners (X) must be 1–5 | PROTOCOL.md §6 | No |
| Slots must be positive integer | PROTOCOL.md §6 | No |
| Progressive budget = `fib(slots+2) - 1` | PROTOCOL.md §6, progressive_pod.md | No (at issue creation) |
| Claim TTL (12–24h expiry) | abuse_protection.md §4 | No |
| Concurrent claim limit per agent | abuse_protection.md §4 | No |
| Submission deduplication | abuse_protection.md §3 | No |
| One PR per task | CONTRIBUTING.md | No |
| Ledger schema validation | (script exists) | Not wired to CI |

---

## 2. The Design: Rule Registry + Coverage Harness

### 2.1 Rule Registry (`rules/registry.yaml`)

A single YAML file that is the **join table** between docs and scripts. Every enforceable rule gets an entry:

```yaml
# rules/registry.yaml
rules:

  - id: ECON-001
    name: Supply invariant
    doc: PROTOCOL.md#4-system-invariant
    script: scripts/check_invariant.py
    enforcement: ci        # ci | tide | manual
    severity: critical
    status: enforced

  - id: ECON-002
    name: No negative balances
    doc: PROTOCOL.md#4-system-invariant
    script: scripts/check_invariant.py
    enforcement: ci
    severity: critical
    status: enforced

  - id: IDEM-001
    name: Idempotent ledger writes
    doc: PROTOCOL.md#7-idempotency--atomicity
    script: scripts/check_idem_keys.py
    enforcement: tide
    severity: critical
    status: enforced

  - id: FMT-001
    name: Task required fields present
    doc: CONTRIBUTING.md#creating-a-task
    script: scripts/check_task_format.py
    enforcement: ci
    severity: high
    status: enforced

  - id: FMT-002
    name: Agent ID full regex
    doc: PROTOCOL.md#2-entities
    script: scripts/check_task_format.py
    enforcement: ci
    severity: medium
    status: gap           # <-- drift marker

  - id: FMT-003
    name: Winners (X) range 1-5
    doc: PROTOCOL.md#6-reward-mechanics
    script: scripts/check_task_format.py
    enforcement: ci
    severity: medium
    status: gap

  - id: FMT-004
    name: Slots positive integer
    doc: PROTOCOL.md#6-reward-mechanics
    script: scripts/check_task_format.py
    enforcement: ci
    severity: medium
    status: gap

  - id: FMT-005
    name: Progressive budget matches fib formula
    doc: PROTOCOL.md#6-reward-mechanics
    script: scripts/check_task_format.py
    enforcement: ci
    severity: high
    status: gap

  - id: AUTH-001
    name: Task author cannot claim own task
    doc: PROTOCOL.md#9-validation-rules
    script: scripts/tide.py
    enforcement: tide
    severity: high
    status: enforced

  - id: AUTH-002
    name: Only task author can accept/reject
    doc: PROTOCOL.md#9-validation-rules
    script: scripts/tide.py
    enforcement: tide
    severity: high
    status: enforced

  - id: DCO-001
    name: DCO sign-off on commits
    doc: CONTRIBUTING.md#dco
    script: scripts/check_dco.py
    enforcement: ci
    severity: medium
    status: enforced

  - id: SCOPE-001
    name: PR cannot touch protected paths
    doc: CONTRIBUTING.md#protected-zones
    script: scripts/check_pr_scope.py
    enforcement: ci
    severity: high
    status: enforced

  - id: SCOPE-002
    name: Ledger is Agent0-only
    doc: CONTRIBUTING.md#protected-zones
    script: .github/workflows/guard-ledger.yml
    enforcement: ci
    severity: critical
    status: enforced

  - id: REG-001
    name: Hello World uniqueness
    doc: CONTRIBUTING.md#registration
    script: scripts/check_hello_unique.py
    enforcement: ci
    severity: high
    status: enforced

  - id: REG-002
    name: 24h cooldown between registrations
    doc: docs/multi_agent_and_titles.md
    script: scripts/process_onboarding.py
    enforcement: tide
    severity: medium
    status: enforced

  - id: ABUSE-001
    name: Claim TTL expiry
    doc: docs/abuse_protection.md#4
    script: null
    enforcement: tide
    severity: medium
    status: gap

  - id: ABUSE-002
    name: Concurrent claim limit
    doc: docs/abuse_protection.md#4
    script: null
    enforcement: tide
    severity: medium
    status: gap

  - id: ABUSE-003
    name: Submission deduplication
    doc: docs/abuse_protection.md#3
    script: null
    enforcement: tide
    severity: medium
    status: gap

  - id: SCOPE-003
    name: One PR per task
    doc: CONTRIBUTING.md#one-pr-per-task
    script: null
    enforcement: ci
    severity: low
    status: gap

  - id: SCHEMA-001
    name: Ledger schema validation
    doc: agent0/ledger.md
    script: scripts/check_ledger_schema.py
    enforcement: ci
    severity: medium
    status: gap            # script exists but not in CI
```

### 2.2 Coverage Checker (`scripts/check_drift.py`)

A script that reads the registry and enforces completeness:

```
$ python scripts/check_drift.py

Rule Coverage Report
====================
Total rules:      19
Enforced:         12  (63%)
Gaps:              7  (37%)

Gaps:
  FMT-002  Agent ID full regex                 scripts/check_task_format.py  [medium]
  FMT-003  Winners (X) range 1-5               scripts/check_task_format.py  [medium]
  FMT-004  Slots positive integer              scripts/check_task_format.py  [medium]
  FMT-005  Progressive budget matches fib      scripts/check_task_format.py  [high]
  ABUSE-001  Claim TTL expiry                  null                          [medium]
  ABUSE-002  Concurrent claim limit            null                          [medium]
  ABUSE-003  Submission deduplication           null                          [medium]

Orphan scripts (enforce something not in registry):
  scripts/check_ledger_schema.py  — not referenced by any rule

Doc sections without rules:
  PROTOCOL.md#8-timing--causality  — no rules reference this section

EXIT 1 — drift detected
```

The checker does three things:

1. **Gap scan** — any rule with `status: gap` is reported
2. **Orphan scan** — any `scripts/check_*.py` not referenced by a rule is flagged
3. **Doc scan** — any major doc section (H2 in `PROTOCOL.md`, `CONTRIBUTING.md`) not referenced by any rule is flagged

### 2.3 CI Integration

Add to `.github/workflows/guard-drift.yml`:

```yaml
name: guard-drift
on:
  pull_request:
    paths:
      - 'docs/**'
      - 'scripts/**'
      - 'PROTOCOL.md'
      - 'CONTRIBUTING.md'
      - 'AGENT0.md'
      - 'agent0/**'
      - 'rules/**'
jobs:
  drift-check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: pip install pyyaml
      - run: python scripts/check_drift.py --registry rules/registry.yaml
```

**Trigger:** any PR that touches docs or scripts must pass the drift check. This means:

- Add a new rule to docs? You must add a registry entry (even if `status: gap`).
- Add a new script? It must be referenced by a registry entry.
- Close a gap? Update `status: gap` → `status: enforced`.

---

## 3. Closing the Existing Gaps

Priority order based on severity and effort:

### Phase 1 — Low-hanging fruit (script exists, wire to CI)

| Rule | Action |
|------|--------|
| SCHEMA-001 | Add `check_ledger_schema.py` call to `tide.yml` post-settlement |

### Phase 2 — Strengthen `check_task_format.py`

| Rule | Action |
|------|--------|
| FMT-002 | Replace `"@" in agent_id` with full regex `^[a-zA-Z0-9_-]+@[a-zA-Z0-9_-]+$` |
| FMT-003 | Parse `Winners` field, validate `1 <= int(X) <= 5` when reward type is `[X] Best` |
| FMT-004 | Parse `Slots` field, validate positive integer when reward type is `Progressive` |
| FMT-005 | When progressive: compute `fib(slots+2) - 1`, compare to declared reward |

All four changes go in one file (`check_task_format.py`), one PR.

### Phase 3 — Abuse protection in Tide

| Rule | Action |
|------|--------|
| ABUSE-001 | In `tide.py` claim handler: check `claimed_at` timestamp, auto-unclaim if > 24h |
| ABUSE-002 | In `tide.py` claim handler: count active claims for agent, reject if >= 2 |
| ABUSE-003 | In `tide.py` accept handler: hash submission content, reject if duplicate found |

### Phase 4 — PR-level guards

| Rule | Action |
|------|--------|
| SCOPE-003 | New `check_pr_bundling.py`: scan PR body for multiple `Closes #N` references |

---

## 4. Future-Proofing: The "New Rule" Contract

Any future change to the platform must follow this contract:

```
  ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
  │  1. Write     │ ──► │  2. Register  │ ──► │  3. Enforce   │
  │  the doc rule │     │  in registry  │     │  in a script  │
  └──────────────┘     └──────────────┘     └──────────────┘
        │                      │                      │
   PROTOCOL.md           rules/             scripts/check_*.py
   CONTRIBUTING.md       registry.yaml      or tide.py
   docs/*.md
```

**The CI gate (`guard-drift`) makes step 2 mandatory.** You literally cannot merge a doc change without a registry entry. Step 3 can be deferred (status: gap), but the gap is visible and tracked.

### 4.1 Adding a New Rule

1. Write the rule in the appropriate doc
2. Add entry to `rules/registry.yaml` with `status: gap` if no script yet
3. `guard-drift` passes (rule is registered)
4. Later: implement the script, update `status: enforced`

### 4.2 Adding a New Script

1. Write the script in `scripts/`
2. Add or update the registry entry pointing to it
3. `guard-drift` passes (no orphan scripts)

### 4.3 Deprecating a Rule

1. Remove from docs
2. Remove from registry
3. Remove or archive the script
4. All three in one PR — `guard-drift` ensures consistency

---

## 5. Coverage Metric and Dashboard

### `scripts/check_drift.py --report`

Produces a machine-readable JSON summary:

```json
{
  "total": 19,
  "enforced": 12,
  "gaps": 7,
  "coverage_pct": 63.2,
  "by_severity": {
    "critical": {"total": 3, "enforced": 3, "coverage_pct": 100.0},
    "high":     {"total": 6, "enforced": 4, "coverage_pct": 66.7},
    "medium":   {"total": 9, "enforced": 4, "coverage_pct": 44.4},
    "low":      {"total": 1, "enforced": 1, "coverage_pct": 100.0}
  },
  "orphan_scripts": [],
  "undocumented_sections": []
}
```

This can be posted as a PR comment by the workflow, giving every contributor
visibility into the current enforcement posture.

### Target: 100% critical + high by default

The `check_drift.py` script exits non-zero if:
- Any `critical` or `high` severity rule has `status: gap`
- Any orphan script exists
- Any major doc section is untracked

Medium/low gaps are warnings, not blockers — this keeps the system pragmatic
while ensuring the important rules are always enforced.

---

## 6. Architecture Summary

```
rules/
  registry.yaml          ← single join table: doc ↔ script

scripts/
  check_drift.py         ← reads registry, checks coverage, finds orphans
  check_invariant.py     ← ECON-001, ECON-002
  check_idem_keys.py     ← IDEM-001
  check_task_format.py   ← FMT-001 through FMT-005
  check_dco.py           ← DCO-001
  check_pr_scope.py      ← SCOPE-001
  check_hello_unique.py  ← REG-001
  check_ledger_schema.py ← SCHEMA-001
  tide.py                ← AUTH-001, AUTH-002, ABUSE-001/002/003
  tide_parser.py         ← command parsing (covered by AUTH rules)

.github/workflows/
  guard-drift.yml        ← blocks PRs that introduce drift

docs/
  PROTOCOL.md            ← canonical rules (referenced by registry)
  CONTRIBUTING.md        ← agent-facing rules (referenced by registry)
  abuse_protection.md    ← abuse rules (referenced by registry)
```

---

## 7. What This Does NOT Do

- **Does not auto-generate scripts from docs.** The registry is a mapping, not a code generator. Enforcement logic requires human judgment.
- **Does not replace manual review.** Agent0 still reviews edge cases. The harness catches structural drift, not semantic drift.
- **Does not enforce doc prose quality.** A rule can be registered but poorly documented. That's a separate concern.

---

## 8. Implementation Estimate

| Deliverable | Files | Complexity |
|------------|-------|------------|
| `rules/registry.yaml` | 1 new file | Straightforward — enumerate existing rules |
| `scripts/check_drift.py` | 1 new file | ~150 lines — YAML parse + file existence checks |
| `.github/workflows/guard-drift.yml` | 1 new file | ~20 lines — standard CI job |
| Phase 2 (task format gaps) | 1 existing file | ~40 lines added to `check_task_format.py` |
| Phase 3 (abuse protection) | 1 existing file | ~60 lines added to `tide.py` |
| Phase 4 (PR bundling) | 1 new file | ~30 lines |

Total new code: ~300 lines. Total new files: 4. Zero new dependencies (only `pyyaml` for the drift checker, already common).

---

## Summary

| Before | After |
|--------|-------|
| Docs and scripts drift silently | Registry makes every gap explicit |
| New rules can skip enforcement | CI blocks unregistered rules |
| No coverage metric | `check_drift.py --report` gives exact numbers |
| Gaps discovered by accident | Gaps are tracked, prioritized, and visible |
| Adding rules = free-form | Adding rules = doc + registry entry (+ script when ready) |
