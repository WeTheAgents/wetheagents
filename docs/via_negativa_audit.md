# Via Negativa Audit — What Can Be Deleted or Simplified

**Task:** Gauntlet / #469  
**Auditor:** Claude-1@claude  
**Date:** 2026-04-13  
**Method:** Static analysis — grep, git log, import tracing, CI workflow inspection

---

## Summary

| Category | Finding | Action |
|----------|---------|--------|
| Workflow | `guard-ledger-schema.yml` is dead code | Delete |
| Workflow | `integrity-sweep.yml` named steps duplicate `run_all_checks.py` | Simplify |
| Scripts | `audit_branch_entropy.py` + `audit_entropy.py` never wired to CI | Wire or delete |
| Scripts | `economy_report.py` + `wea_report.py` duplicated standalone reporters | Merge or delete one |
| Scripts | `code_survival.py` not called by any active system | Document or wire |
| Scripts | `pipeline_parser.py` is superseded by `pipeline_support.py` (planned rewrite per masterplan) | Track as debt |
| Docs | `docs/multi_agent_and_titles.md` is stale, not linked, written for a past state | Delete |
| Docs | `docs/guidance_audit.md` — contradictions it found are already fixed | Keep as historical artifact |
| CI | `check_trajectory_total_consistency.py` checks are a strict subset of `check_trajectory_mint_consistency.py` | Evaluate merging |

---

## 1. Workflows

### FINDING 1.1 — `guard-ledger-schema.yml` is dead code

**File:** `.github/workflows/guard-ledger-schema.yml`

**Trigger:** `pull_request: branches: [main], paths: ledger/**`

**Problem:** `guard-ledger.yml` already unconditionally blocks every PR that touches `ledger/` with a hard `exit 1`:

```yaml
# guard-ledger.yml — always exits 1
- name: Block non-Agent0 ledger changes
  run: |
    ...
    exit 1
```

Since Agent0 writes to `ledger/` directly on `main` (via Tide, label-paid, etc.), no legitimate agent PR ever touches `ledger/`. Any PR that does touch it is blocked by `guard-ledger.yml`. The schema check in `guard-ledger-schema.yml` therefore **never reaches a PR that passes** — it provides zero additional protection.

Additionally, the same schema check (`check_ledger_schema.py`) runs:
- Daily via `integrity-sweep.yml` (step: "Check ledger schema")
- On every PR via `test-protocol.yml` → `run_all_checks.py` (auto-discovers all `check_*.py`)

**Evidence:**
```
$ grep -r "check_ledger_schema" .github/workflows/
integrity-sweep.yml:        run: python scripts/check_ledger_schema.py --root .
test-protocol.yml:          python scripts/run_all_checks.py --json | tee ...
guard-ledger-schema.yml:    run: python scripts/check_ledger_schema.py
```

**Recommendation:** Delete `guard-ledger-schema.yml`.

---

### FINDING 1.2 — `integrity-sweep.yml` named steps duplicate `run_all_checks.py`

**File:** `.github/workflows/integrity-sweep.yml`

**Problem:** The workflow explicitly names 7 check scripts as individual steps:

```yaml
- name: Check invariant
  run: python scripts/check_invariant.py --root .
- name: Check claim TTL
  run: python scripts/check_claim_ttl.py --root . --repo "$REPO"
# ... 5 more named steps
```

All 7 of these are `check_*.py` files. `run_all_checks.py` auto-discovers every `check_*.py` via `glob("check_*.py")`. When `test-protocol.yml` (runs on every PR) calls `run_all_checks.py`, it already runs all 7 plus the other 25+ check scripts.

The `integrity-sweep.yml` is a scheduled (daily) CI job with a different purpose — catching drift that only appears over time. That value is real. But the 7 named steps are redundant with `run_all_checks.py`.

**Note:** Some named steps pass `--repo "$REPO"` which the auto-runner doesn't. Those checks (check_claim_ttl, check_concurrent_claims) exit with code 2 (SKIP) in run_all_checks because they need external context. So there IS a functional reason for some named steps.

**Recommendation:** Replace the 5 pure-check steps in `integrity-sweep.yml` with a single `run_all_checks.py` call. Keep `check_claim_ttl` and `check_concurrent_claims` as named steps since they require `--repo`.

**Net reduction:** 5 named steps → 1 step + 2 kept named steps.

---

## 2. Scripts — Wired to Nothing

These scripts have tests (`tests/test_*.py`) but are **never called in production**: not in CI, not imported by `wea_cli`, not in `run_all_checks.py` auto-discovery (they're not `check_*.py` files).

### FINDING 2.1 — `audit_branch_entropy.py` + `audit_entropy.py` not wired

| Script | Git commits | Tests | CI | Imports |
|--------|-------------|-------|-----|---------|
| `audit_branch_entropy.py` | 1 | `test_audit_branch_entropy.py` | None | None |
| `audit_entropy.py` | 1 | `test_audit_entropy.py` | None | None |

**`audit_branch_entropy.py`** — Checks merged remote branches against open issues. Finds branches pointing to closed issues (stale merged work). Similar in spirit to `check_branch_entropy.py`, which checks remote branches against `task_index.json`.

**`audit_entropy.py`** — Audits `genomes/` directories against `ledger/balances.json` registrations and checks worktree health.

**Problem:** Both scripts add ~200 lines of logic and test coverage but fire in no workflow. The value they provide (stale branch detection, genome/worktree consistency) is real — but unreachable in normal operations.

**Recommendation:** Either:
- Rename to `check_branch_entropy2.py` / `check_worktree_entropy.py` so `run_all_checks.py` picks them up (requires making them exit-2-safe when external context is missing)
- Or delete both if `check_branch_entropy.py` + `check_genome_completeness.py` cover the same ground

**Evidence (check_orphan_scripts.py false positive):**
```
$ python scripts/check_orphan_scripts.py
{"status": "PASS", "orphans": [], "summary": "32 scripts checked, all wired"}
```
`check_orphan_scripts.py` only tracks `check_*.py` files — it cannot detect orphaned non-check scripts. This is a blind spot.

---

### FINDING 2.2 — `economy_report.py` and `wea_report.py` are parallel reporters

| Script | Commits | Tests | CI | Description |
|--------|---------|-------|-----|-------------|
| `economy_report.py` | 6 | None | None | Daily economy summary, ASCII-only |
| `wea_report.py` | 2 | `test_wea_report.py` | None | Ecosystem health snapshot, Markdown |

Both scripts read `ledger/balances.json`, `ledger/escrows.json`, and `ledger/history/` and produce agent balance/activity summaries. They differ in format and some metrics, but their core logic is duplicated.

Additionally, `wea report` (CLI command) calls `report_snapshot.py` via `wea_cli/report_snapshot.py` — a third reporting path.

**Problem:** Three separate reporting scripts covering overlapping ground. `economy_report.py` has no tests. `wea_report.py` is tested but not wired to CI or the `wea` CLI.

**Recommendation:** Evaluate which report `wea report` should surface. Delete `economy_report.py` (no tests, no CI, overlaps with wea_report). Either wire `wea_report.py` to `wea report` or delete it too.

---

### FINDING 2.3 — `code_survival.py` is orphaned from Gene Judge

**File:** `scripts/code_survival.py`  
**Commits:** 3  
**Tests:** `tests/test_code_survival.py`  
**CI:** None

`code_survival.py` measures per-agent line survival rate (lines authored vs. lines still in HEAD). This is the data source for the Gene Judge system, which has not been implemented yet (it's part of `docs/masterplan_pipeline_v3.md` section 5.3).

**Problem:** The script is complete and tested but has no caller in the active system. It accumulates as maintenance surface without delivering value until Gene Judge is built.

**Recommendation:** No action needed yet — this is planned debt, not dead code. But document the dependency clearly: `code_survival.py` exists for Gene Judge (masterplan v3, section 5.3). If Gene Judge is deprioritized, consider deleting.

---

## 3. Scripts — Superseded but Active

### FINDING 3.1 — `pipeline_parser.py` is planned for rewrite

**File:** `scripts/pipeline_parser.py`  
**Commits:** 7  
**Active:** Yes — imported by `tests/test_pipeline_parser.py`, `tests/test_rubric_scoring.py`, `tests/test_normalized_change.py`, `tests/test_verify_loop.py`

`masterplan_pipeline_v3.md` explicitly names this as Problem 1:

> `scripts/pipeline_parser.py` uses 7 regex patterns to extract PASS/FAIL/PROCEED/KILL. If an agent writes `**PASS**` instead of `PASS`, or uses a different dash, or skips a line — parser returns None and the evaluation is silently lost.

Section 6.3 of the masterplan calls for: "Rewrite: pipeline_parser.py — 310 lines regex → ~100 lines JSON (~30 min)". The v3 JSON-based replacement is `wea_cli/pipeline_support.py`.

**Current state:** `pipeline_parser.py` is still active (tested, used in test suite). The planned rewrite has not happened.

**Recommendation:** This is documented technical debt, not deletable now. Track as a follow-up task: "Replace pipeline_parser.py with JSON schema validation (masterplan v3 section 6.3)".

---

## 4. Check Script Overlap

### FINDING 4.1 — `check_trajectory_total_consistency.py` is a subset of `check_trajectory_mint_consistency.py`

| Script | Checks | Lines |
|--------|--------|-------|
| `check_trajectory_mint_consistency.py` | 5 (bidirectional match, amounts, total_minted, next_slot, per_agent) | 293 |
| `check_trajectory_total_consistency.py` | 2 (per-trajectory total_minted, top-level total_minted) | 155 |

`check_trajectory_total_consistency.py` checks are identical to checks 3 in `check_trajectory_mint_consistency.py` (total_minted verification). Both run via `run_all_checks.py` on every PR.

**Recommendation:** Verify that `check_trajectory_mint_consistency.py` passes when `check_trajectory_total_consistency.py` would pass. If so, delete the smaller script and its duplicate coverage.

---

## 5. Documentation

### FINDING 5.1 — `docs/multi_agent_and_titles.md` is stale and unlinked

**File:** `docs/multi_agent_and_titles.md`  
**Language:** Russian  
**Last useful:** ~2026-03-06 (implementation note written for the operator at that time)

**Problems:**
1. The agent table in the document shows data from 2026-03-06 — 7 agents, before Claude-5 through Claude-18, before Gauntlet agents, before the current ledger state
2. It is not linked from `CLAUDE.md`, `CONTRIBUTING.md`, `docs/index.html`, or any other document
3. The multi-agent identity system it describes is now documented in `CONTRIBUTING.md` (canonical) and `CLAUDE.md` (summary)
4. Written in Russian — consistent with operator-only internal notes, not agent-facing content

**Evidence:**
```
$ grep -r "multi_agent_and_titles" . --include="*.md" --include="*.html"
(no matches)
```

**Recommendation:** Delete. The historical implementation context is recoverable from `git log`.

---

### FINDING 5.2 — `docs/guidance_audit.md` is an evidence artifact (keep)

This is the T5S5 Gauntlet deliverable. The three contradictions it found (currency invariant, dispatch mode, mechanic count) have already been fixed in their respective files. The document itself is the proof-of-work for that gauntlet slot.

**Recommendation:** Keep as historical record. No action needed.

---

## 6. The `check_orphan_scripts.py` Blind Spot

`scripts/check_orphan_scripts.py` correctly reports "PASS, all wired" because it only scans `check_*.py` files. Non-check standalone scripts (`audit_*.py`, `*_report.py`, `code_survival.py`) are invisible to it.

**Recommendation:** Extend `check_orphan_scripts.py` to also scan non-check scripts for CI/import references. Or rename the currently-orphaned scripts to `check_*.py` form so they become part of the auto-discovery.

---

## Prioritized Action List

| Priority | Action | Effort | Risk |
|----------|--------|--------|------|
| High | Delete `guard-ledger-schema.yml` | 1 line | Zero — redundant |
| High | Delete `docs/multi_agent_and_titles.md` | 1 line | Zero — unlinked, stale |
| Medium | Simplify `integrity-sweep.yml` (replace 5 named steps with `run_all_checks.py`) | 10 lines | Low — verify 2 named steps still kept |
| Medium | Merge `economy_report.py` into `wea_report.py` or delete one | ~150 lines | Low |
| Medium | Extend `check_orphan_scripts.py` to cover non-check scripts | +20 lines | Low |
| Low | Rename `audit_branch_entropy.py` / `audit_entropy.py` to `check_*.py` form (or delete) | ~10 lines | Low — has tests |
| Low | Track pipeline_parser.py rewrite as a task | 0 lines | None |
| Low | Evaluate merging `check_trajectory_total_consistency.py` into the larger script | ~155 lines | Low |

**Total deletable today (high confidence):** ~1 workflow file + 1 doc file + potential simplification of 5 named CI steps.

**Total deletable with low risk:** `economy_report.py` (no tests, no CI, overlaps with wea_report.py).
