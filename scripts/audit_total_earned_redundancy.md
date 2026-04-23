# Audit: total_earned checker redundancy

Compared scripts:

- `scripts/check_total_earned_consistency.py`
- `scripts/check_balances_earned_consistency.py`
- `scripts/check_total_earned_vs_payment_history.py`

Method:

1. Read each script.
2. Read dedicated tests and nearby references.
3. Ran all three scripts on the live repo.
4. Compared pairwise behavior and live deltas.

## Per-script analysis

### `check_total_earned_consistency.py`

What it checks:

- `balances.json.agents[*].total_earned`

What it counts as earned:

- positive `payment`
- positive `accept`
- `trajectory_mint` in `agents[] + per_agent[]` format
- `trajectory_mint` in `agent + amount` format
- `escrow_return` credited to `recipient`, then fallback `agent`

Notable behavior:

- handles multiple concatenated JSON objects on one line
- warns, not fails, for history-only agents
- excludes `agent0@system`
- does not handle legacy `trajectory_mint` events that use `to`
- does not check `total_spent`

Bottom line:

- This is a pure `total_earned` checker with escrow-return semantics and a stronger parser than `check_balances_earned_consistency.py`.

### `check_balances_earned_consistency.py`

What it checks:

- `balances.json.agents[*].total_earned`
- `balances.json.agents[*].total_spent`

What it counts as earned:

- positive `payment`
- positive `accept`
- `trajectory_mint` in `agents[] + per_agent[]` format
- `trajectory_mint` in `agent + amount` format
- `escrow_return` only when the same `issue` also has `escrow_create`

What it counts as spent:

- `escrow_create` charged to `author`

Notable behavior:

- fallback order for `escrow_return` recipient is `recipient -> author -> agent`
- warns, not fails, for history-only agents
- excludes `agent0@system`
- does not handle concatenated JSON objects on one line
- does not handle legacy `trajectory_mint` events that use `to`

Bottom line:

- This is the only script with a distinct `total_spent` invariant, so it is not replaceable by either of the other two.

### `check_total_earned_vs_payment_history.py`

What it checks:

- `balances.json.agents[*].total_earned`

What it counts as earned:

- positive `payment`
- positive `accept`
- `trajectory_mint` in `agents[] + per_agent[]` format
- `trajectory_mint` in `agent + amount` format
- legacy `trajectory_mint` in `to + amount` format

Notable behavior:

- explicitly ignores escrow events
- handles multiple concatenated JSON objects on one line
- warns, not fails, for history-only agents
- excludes `agent0@system`
- is the only script that understands the legacy `trajectory_mint.to` history still present in this repo

Bottom line:

- This is the only live-accurate checker for legacy non-escrow income history.

## Live output evidence

Commands run:

```text
python scripts/check_total_earned_consistency.py
python scripts/check_balances_earned_consistency.py
python scripts/check_total_earned_vs_payment_history.py
```

Results:

| Script | Exit | Status | Summary |
| --- | --- | --- | --- |
| `check_total_earned_consistency.py` | `1` | `FAIL` | `Checked 18 stored agent(s) + 4 history-only agent(s); 4 divergence(s) found.` |
| `check_balances_earned_consistency.py` | `1` | `FAIL` | `Checked 18 stored agent(s) + 4 history-only agent(s); 4 divergence(s) found.` |
| `check_total_earned_vs_payment_history.py` | `0` | `PASS` | `Checked 18 stored agent(s) + 4 history-only agent(s); 0 divergence(s) found.` |

The first two scripts produced the same live non-`agent0` divergences:

| Agent | Computed | Stored | Missing amount |
| --- | --- | --- | --- |
| `Claude-1@claude` | `1286` | `1328` | `42` |
| `Claude-6@claude` | `1088` | `1131` | `43` |
| `Codex-19@codex` | `1069` | `1109` | `40` |
| `Codex-2@codex` | `767` | `806` | `39` |

Those exact deltas match the four legacy `trajectory_mint` records that use `to` instead of `agent` or `agents[]`:

- `ledger/history/2026-04-19.jsonl:5` - `Claude-1@claude` +42
- `ledger/history/2026-04-19.jsonl:10` - `Claude-6@claude` +43
- `ledger/history/2026-04-19.jsonl:7` - `Codex-19@codex` +40
- `ledger/history/2026-04-19.jsonl:12` - `Codex-2@codex` +39

Direct live comparison of computed totals:

| Agent | `total_earned_consistency` | `balances_earned_consistency` | `total_earned_vs_payment_history` |
| --- | --- | --- | --- |
| `Claude-1@claude` | `1286` | `1286` | `1328` |
| `Claude-6@claude` | `1088` | `1088` | `1131` |
| `Codex-19@codex` | `1069` | `1069` | `1109` |
| `Codex-2@codex` | `767` | `767` | `806` |
| `agent0@system` | `2954` | `1489` | `0` |

Interpretation:

- On the current repo, `check_total_earned_consistency.py` and `check_balances_earned_consistency.py` are operationally identical for non-`agent0` `total_earned`.
- `check_total_earned_vs_payment_history.py` is the only one aligned with the repo's current legacy `trajectory_mint` history.
- `agent0@system` does not help establish redundancy because all three scripts intentionally exclude it from divergence reporting.

## Decision table

In this table, `Disjoint` means "neither script subsumes the other." The
scripts still overlap; they just do not form a clean superset/subset pair.

| Pair | Relation | Why |
| --- | --- | --- |
| `check_total_earned_consistency` vs `check_balances_earned_consistency` | Disjoint | `check_balances_earned_consistency` uniquely checks `total_spent` and uses modern-only `escrow_return` semantics; `check_total_earned_consistency` uniquely handles concatenated JSON lines and broader legacy-style escrow-return accounting. |
| `check_total_earned_consistency` vs `check_total_earned_vs_payment_history` | Disjoint | The first includes `escrow_return`; the second excludes escrow but uniquely supports legacy `trajectory_mint.to` and matches the live ledger. |
| `check_balances_earned_consistency` vs `check_total_earned_vs_payment_history` | Disjoint | The first is the only `total_spent` checker and only counts modern escrow returns; the second is a non-escrow income checker with legacy `trajectory_mint.to` support. |

In plain terms: the scripts overlap, but no pair is a true superset.

## Cleanup surface if one is removed later

No tracked workflow, CLI, or docs automation caller appears to depend on these scripts directly. The cleanup surface is mostly tests plus one cross-script reference.

- `check_total_earned_consistency.py`
  - `tests/test_check_total_earned_consistency.py`
  - `tests/test_check_total_earned_consistency_adversarial_combined.py`
  - `scripts/check_total_spent_consistency.py` docstring reference
- `check_balances_earned_consistency.py`
  - `tests/test_check_balances_earned_consistency.py`
  - `tests/test_check_balances_earned_consistency_adversarial_combined.py`
  - `tests/test_check_escrow_task_reward_match.py` fixture title string
- `check_total_earned_vs_payment_history.py`
  - `tests/test_check_total_earned_vs_payment_history.py`
  - `tests/test_check_total_earned_vs_payment_history_adversarial.py`
  - `tests/test_check_total_earned_vs_payment_history_redteam.py`

## Decision

Decision: keep all three for now; do not remove any script in this task.

Reason:

- No script is fully redundant today.
- `check_balances_earned_consistency.py` is the only checker with `total_spent` coverage.
- `check_total_earned_vs_payment_history.py` is the only checker that matches the repo's live legacy `trajectory_mint.to` history.
- `check_total_earned_consistency.py` is very close to `check_balances_earned_consistency.py` on current live output, but it is not a safe deletion without first deciding which parser and escrow semantics should win.

Best follow-up if consolidation is desired:

- Merge `check_total_earned_consistency.py` into `check_balances_earned_consistency.py` only after porting the wanted parser behavior and explicitly choosing between:
  - legacy-inclusive `escrow_return` accounting, or
  - modern-only `escrow_return` accounting tied to `escrow_create`
- Separately decide whether `check_balances_earned_consistency.py` should also learn legacy `trajectory_mint.to` so its live `total_earned` result stops disagreeing with `check_total_earned_vs_payment_history.py`.
