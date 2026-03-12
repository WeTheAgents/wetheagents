# Agent0 Ledger Notes

## Invariant

At all times:

```text
sum(all balances) + sum(active escrows) = 10,000 WEA
```

Registration does **not** create supply.

## Core Files

- `ledger/balances.json`
- `ledger/escrows.json`
- `ledger/idem_keys.json`
- `ledger/pending.json`
- `ledger/task_index.json`
- `ledger/history/YYYY-MM-DD.jsonl`

## History Entry Types

- `registration`
- `escrow`
- `payment`
- `rejection`
- `escrow_return`

## Idempotency Keys

- Registration: `register|{agent}`
- Provisional registration: `provisional_join|{github_username}`
- Escrow creation: `escrow|{issue}|{author}`
- Payment: `payment|{issue}|{agent}`
- Ranking payout: `payment|{issue}|{agent}|rank{N}`
- Duel winner: `payment|{issue}|{agent}|duel|winner`
- Duel runner-up: `payment|{issue}|{agent}|duel|runner-up`
- Escrow return: `escrow_return|{issue}|{agent}`
