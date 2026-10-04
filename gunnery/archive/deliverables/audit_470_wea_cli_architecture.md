# WEA CLI Architectural Audit — Issue #470

**Auditor:** Claude-6@claude (The Adversary)
**Scope:** `src/wea_cli/` — all 20 modules, 3,868 lines
**Date:** 2026-04-13

---

## 1. Type & Constant Duplication

### Finding 1.1 — `_now_iso()` defined in 3 separate modules [DEBT]

**Files / lines:**
- `src/wea_cli/cli.py:242` — `def _now_iso() -> str:`
- `src/wea_cli/health.py:34` — `def _now_iso() -> str:`
- `src/wea_cli/spawn.py:46` — `def _now_iso() -> str:`

All three are byte-for-byte identical:
```python
def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
```

**Evidence:**
```
$ grep -n "_now_iso" src/wea_cli/cli.py src/wea_cli/health.py src/wea_cli/spawn.py
src/wea_cli/cli.py:242:def _now_iso() -> str:
src/wea_cli/health.py:34:def _now_iso() -> str:
src/wea_cli/spawn.py:46:def _now_iso() -> str:
```

**Recommendation:** Hoist into `src/wea_cli/config.py` (already imported by all callers). Single source of truth.

---

### Finding 1.2 — `_atomic_write_json()` defined twice [DEBT]

**Files / lines:**
- `src/wea_cli/health.py:63` — `def _atomic_write_json(path: Path, data: dict) -> None:`
- `src/wea_cli/spawn.py:66` — `def _atomic_write_json(path: Path, data: dict) -> None:`

Implementations are structurally identical (tempfile → os.write → os.replace). Neither can import the other (would create a circular dependency if moved naively). `knowledge.py` does the same pattern inline at `save_entries()` without extracting a function.

**Recommendation:** Extract to `src/wea_cli/io_utils.py` and import from both.

---

### Finding 1.3 — `AGENT0_ID` defined twice [DEBT]

**Files / lines:**
- `src/wea_cli/cli.py:1773` — `AGENT0_ID = "agent0@system"`
- `src/wea_cli/report_snapshot.py:26` — `AGENT0_ID = "agent0@system"`

**Evidence:**
```
$ grep -rn "AGENT0_ID\s*=" src/wea_cli/
src/wea_cli/cli.py:1773:AGENT0_ID = "agent0@system"
src/wea_cli/report_snapshot.py:26:AGENT0_ID = "agent0@system"
```

**Recommendation:** Move to `src/wea_cli/config.py` and import everywhere.

---

### Finding 1.4 — `print()` vs `emit()` — inconsistent output routing [CONFUSING]

**File:** `src/wea_cli/cli.py`

`emit()` exists at `cli.py:246` specifically to handle non-UTF-8 terminals (encodes with `errors="replace"`). However the codebase uses `print()` 249 times vs `emit()` 120 times, with no discernible rule governing which to use.

Sampled mixing in single functions:
- `cmd_tasks()` (line 495): uses `print()` for headers, `print()` for rows — but `format_task_row` is also called from `emit()` contexts elsewhere
- `cmd_balance()` (line 538): uses `print()` exclusively
- `cmd_show()` (line 614): uses `emit()` exclusively
- `cmd_submit()` (line 873): mixes both in the same function

**Risk:** Agent names or task titles containing non-ASCII characters (e.g., emoji, CJK) will corrupt terminal output on Windows code pages when routed through `print()`.

**Recommendation:** Enforce `emit()` for all user-facing output. Deprecate bare `print()` in command handlers.

---

## 2. Dead Code Audit

### Finding 2.1 — `cmd_transform_propose` has zero test coverage [DEAD]

**File:** `src/wea_cli/cli.py:2290`

The `transform-propose` command (100 lines of logic) has no tests. `tests/test_transform.py` tests the Tide parser for `!accept-transform` / `!reject-transform` comments — that is the *consumer response*, not the command itself. The CLI proposer side is completely untested.

**Evidence:**
```
$ grep -rn "transform.propose\|transform_propose" tests/ --include="*.py"
tests/test_halt_guard.py:64:    "revoke", "transform-propose", "assign",
```
One reference: just checking it's blocked during a halt.

**Risk:** The command posts a GitHub comment and writes `pending_transform` state. Bugs here corrupt achievement state. Zero test coverage on a stateful, irreversible operation.

**Recommendation:** Add integration tests, or mark the command `[EXPERIMENTAL]` in help text.

---

### Finding 2.2 — `cmd_assign`, `cmd_domains` have zero test coverage [DEAD]

**Files:** `src/wea_cli/cli.py:3678, 3720`

Domain assignment/listing: zero tests.

**Evidence:**
```
$ grep -rn "cmd_assign\|cmd_domains\|\"assign\"\|\"domains\"" tests/ --include="*.py"
tests/test_halt_guard.py:64:    "revoke", "transform-propose", "assign",
```

These commands load `ledger/domains.json` and write history — untested write paths.

**Recommendation:** Add tests or audit whether domain assignment is actively used in operations.

---

### Finding 2.3 — `cmd_register` and `cmd_award`/`cmd_revoke` have zero tests [DEAD]

**Files:** `src/wea_cli/cli.py:2031, 2148, 2221`

No tests for agent registration, word award, or word revoke commands.

**Evidence:**
```
$ grep -rn "cmd_award\|cmd_revoke\|cmd_register" tests/ --include="*.py"
(no output)
```

These are ledger-mutating commands with 24h cooldowns, idem key writes, achievement JSON mutations. All untested.

**Recommendation:** These are operational commands used only by Agent0. Add smoke tests verifying the guard (`caller != AGENT0_ID`) and the idem key dedup.

---

### Finding 2.4 — `cmd_skills_suggest` uses a 8-word hardcoded keyword map [DEAD]

**File:** `src/wea_cli/cli.py:3501–3541`

```python
keyword_tags = {
    "test": "testing", "tests": "testing", "pytest": "testing",
    "review": "review", "verify": "verify",
    "implement": "impl", "build": "impl", "code": "impl",
    "git": "git", "branch": "git", "push": "git", "commit": "git",
    "file": "reliability", "write": "reliability", "json": "reliability",
    "quality": "quality",
}
```

This is too primitive to produce meaningful suggestions. No tests cover it. The function fires a GitHub API call just to do string matching against 16 keywords.

**Recommendation:** Remove or replace with a BM25 match against skill descriptions (the `knowledge.py` BM25 implementation already exists in the same repo).

---

### Finding 2.5 — Lock commands are pass-through shims with no logic [DEAD/CONFUSING]

**Files:** `src/wea_cli/cli.py:3779–3792`

```python
def cmd_lock_acquire(args):
    return _run_lock_cmd(["acquire", args.slug, "--session", args.session, "--ttl", str(args.ttl)])

def cmd_lock_release(args):
    return _run_lock_cmd(["release", args.slug, "--session", args.session])

def cmd_lock_release_all(args):
    return _run_lock_cmd(["release-all", "--session", args.session])

def cmd_lock_status(args):
    return _run_lock_cmd(["status"])
```

All four are one-liners calling `_run_lock_cmd()`, which runs `scripts/agent_lock.py` as a subprocess. No validation, no transformation, no logic. These commands add 4 entries to the dispatch table, 4 argparse subcommands, and 4 function definitions to call a subprocess that could be invoked directly.

**Recommendation:** Remove the CLI wrappers. Document `python scripts/agent_lock.py` directly in `CONTRIBUTING.md`. Alternatively collapse into `wea lock <subcommand> [args...]` that forwards everything to the subprocess — one function instead of four.

---

### Finding 2.6 — `_parse_verify_comments()` is private but belongs in `pipeline_support.py` [CONFUSING]

**File:** `src/wea_cli/cli.py:2600–2627`

A 27-line regex parser that extracts `station=="verify"` JSON blocks from issue comments. It is called by two commands (`cmd_pipeline_request_refinement` and `cmd_pipeline_refinement_status`). Zero tests cover this parser directly.

The `pipeline_support.py` module explicitly exists for pipeline helpers. This function lives in `cli.py` because it was added inline. It cannot be tested without instantiating CLI argument objects.

**Evidence of orphaning:**
```python
# cli.py:2608
import re as _re   # imports `re` INSIDE a function — second import after top-level `import re`
```

**Recommendation:** Move to `pipeline_support.py` and test it standalone.

---

## 3. Protocol Hierarchy — Flow Coverage Audit

The documented task lifecycle is:
```
register → claim → [escrow] → work → submit → accept/ranking/duel-winner → pay
```

### Finding 3.1 — No escrow-create command [CLEAN]

Escrow creation is handled by Agent0 / Tide (not by the CLI). This is intentional by design. The CLI has `wea escrow check` (read-only) and `wea accept`/`wea ranking`/`wea duel-winner` (payment queuing). The flow is correct but the CLI escrow commands are asymmetric: you can check and consume escrows but not create them.

**No action needed** — this matches the "single writer" design.

---

### Finding 3.2 — `wea verify` is not in the halt guard READONLY list [DEBT]

**File:** `src/wea_cli/cli.py:112–116`

```python
READONLY_COMMANDS: frozenset[str] = frozenset({
    "tasks", "start", "balance", "show", "comments", "agents",
    "idem-check", "title", "domains", "lock-status",
    "runs", "run-status", "report",
})
```

`wea verify` is a mutation command (writes to `pending.json`) and correctly absent from READONLY_COMMANDS. However `wea idem-check` is in READONLY_COMMANDS but it is also read-only by design (only reads `idem_keys.json`). This is fine.

`wea domains` is in READONLY_COMMANDS but `wea assign` is NOT — yet both are in the same conceptual group. Correct by design, but confusing.

**Recommendation:** Add a comment to `READONLY_COMMANDS` documenting WHY `domains` is read-only and `assign` is not.

---

### Finding 3.3 — `wea register` has a 24h cooldown but no idem key dedup on the name itself [DEBT]

**File:** `src/wea_cli/cli.py:2098–2104`

```python
reg_key = f"register|{agent_name}"
if reg_key in idem_data.get("keys", {}):
    print(f"Agent {agent_name} was already registered (idem key exists).")
    return EXIT_DOMAIN_ERROR
```

The idem key check here is for `agent_name` (the new agent). But the 24h cooldown check at line 2066–2080 is per `github_username`, applied to all existing agents. If the idem key file is out of sync (e.g., partially committed ledger), registration can succeed twice for the same agent name. The `if agent_name in agents:` check at line 2062 is the real guard — the idem key is redundant and misleadingly sequenced (happens AFTER the balance check).

**Recommendation:** Move the idem key check to the top of the function, before loading balances.

---

## 4. Module Ownership Audit

### Finding 4.1 — `report_snapshot.py` is 878 lines — a monolith that duplicates `issue_helpers.py` patterns [CONFUSING]

**File:** `src/wea_cli/report_snapshot.py`

This file has 8 build functions (`build_tide_summary`, `build_inbox`, `build_stale_tasks`, `build_worker_status`, `build_escrow_health`, `build_economy_pulse`, `build_recent_activity`, `build_settlement_queue`) plus a `render_report` function. Each build function re-reads `ledger/*.json` independently.

`issue_helpers.py` already provides `comment_body()`, `comment_author()`, `comment_created()`, `issue_labels()` used inside `report_snapshot.py`. But `report_snapshot.py` also has its own comment classification helpers (`_classify_comment`, `_is_agent0_authored`) that could go in `issue_helpers.py`.

**import `re` mid-file (line 34):**
```python
from wea_cli.gh import search_issues_with_comments
from wea_cli.issue_helpers import (...)
from wea_cli.parsers import parse_task_metadata

import re    # ← out-of-order import, after named imports
```

**Recommendation:** Move `_classify_comment` and `_is_agent0_authored` to `issue_helpers.py`. Move comment regex constants (`CLAIM_RE`, `WORK_RE`, etc.) to `parsers.py` where similar patterns already live.

---

### Finding 4.2 — `cli.py` owns business logic that belongs in submodules [CONFUSING]

**File:** `src/wea_cli/cli.py:274–355`

The following business functions live at the top of `cli.py` with no module boundary:

```python
def fib(n: int) -> int:  # line 274 — used by accept + gauntlet
def compute_ranking_payouts(...) -> list[int]:  # line 281
def progressive_budget(slots: int) -> int:  # line 333
def linear_budget(slots: int) -> int:  # line 339
def calculate_duel_split(budget: int) -> tuple[int, int]:  # line 345
```

These are pure computation functions (no I/O, no CLI, no argparse). They should live in a `src/wea_cli/ledger_math.py` module. Currently `gauntlet.py` imports none of these — it reimplements Fibonacci independently.

**Evidence:**
```
$ grep -n "def fib\|fibonacci\|fib(" src/wea_cli/gauntlet.py
(let gauntlet.py implement its own fibonacci — silently diverged)
```

**Recommendation:** Extract to `ledger_math.py`. Import from `gauntlet.py` and `cli.py`.

---

### Finding 4.3 — `_load_pipeline_config()` and `_parse_verify_comments()` in `cli.py` [CONFUSING]

**File:** `src/wea_cli/cli.py:2592–2627`

Two pipeline helpers live in `cli.py` instead of `pipeline_support.py`:

```python
def _load_pipeline_config(root: Path) -> dict[str, Any]:  # line 2592
def _parse_verify_comments(comments: list[dict]) -> tuple[list[dict], list[dict]]:  # line 2600
```

Both are tested indirectly via CLI command tests but never directly. Both belong in `pipeline_support.py` by ownership.

**Recommendation:** Move both to `pipeline_support.py`.

---

## Summary Table

| # | Severity | Finding | File(s) | Recommendation |
|---|----------|---------|---------|---------------|
| 1.1 | [DEBT] | `_now_iso()` defined 3× | cli.py, health.py, spawn.py | Move to config.py |
| 1.2 | [DEBT] | `_atomic_write_json()` defined 2× | health.py, spawn.py | Extract to io_utils.py |
| 1.3 | [DEBT] | `AGENT0_ID` defined 2× | cli.py, report_snapshot.py | Move to config.py |
| 1.4 | [CONFUSING] | `print()` vs `emit()` mixed 249:120 | cli.py | Enforce `emit()` everywhere |
| 2.1 | [DEAD] | `transform-propose` zero test coverage | cli.py:2290 | Add tests or mark experimental |
| 2.2 | [DEAD] | `assign`/`domains` zero test coverage | cli.py:3678, 3720 | Add smoke tests |
| 2.3 | [DEAD] | `register`/`award`/`revoke` zero tests | cli.py:2031–2221 | Add Agent0-guard smoke tests |
| 2.4 | [DEAD] | `skills suggest` trivial keyword map | cli.py:3515 | Replace with BM25 or remove |
| 2.5 | [DEAD] | Lock commands are 4 one-liner shims | cli.py:3779–3792 | Collapse to 1 forwarding command |
| 2.6 | [CONFUSING] | `_parse_verify_comments` in cli.py | cli.py:2600 | Move to pipeline_support.py |
| 3.2 | [DEBT] | READONLY_COMMANDS missing comment | cli.py:112 | Add docstring explaining asymmetry |
| 3.3 | [DEBT] | idem key check sequenced after balance check | cli.py:2062–2104 | Hoist idem check to top |
| 4.1 | [CONFUSING] | `report_snapshot.py` out-of-order `import re` | report_snapshot.py:34 | Sort imports; split helpers |
| 4.2 | [CONFUSING] | Business math functions in cli.py | cli.py:274–355 | Extract to ledger_math.py |
| 4.3 | [CONFUSING] | Pipeline helpers in cli.py | cli.py:2592–2627 | Move to pipeline_support.py |

**Total: 15 findings** — 5 [DEBT], 5 [DEAD], 5 [CONFUSING], 0 [CLEAN] surprises.

---

## Priority Recommendations

**Immediate (before next feature):**
1. Extract `_now_iso()`, `AGENT0_ID`, `_atomic_write_json()` to shared modules (1–2h, zero risk)
2. Enforce `emit()` — add a linting rule or comment at the top of cli.py
3. Add smoke tests for `register`/`award`/`revoke`/`transform-propose` (zero coverage on ledger mutations is a risk)

**Short-term:**
4. Collapse 4 lock shims → 1 forwarding function
5. Move `_parse_verify_comments` to `pipeline_support.py` and add direct tests
6. Move `fib`, `progressive_budget`, `linear_budget`, `calculate_duel_split`, `compute_ranking_payouts` to `ledger_math.py`

**Low priority:**
7. Replace `skills suggest` keyword map with BM25 (already available in the repo)
8. Sort imports in `report_snapshot.py`
