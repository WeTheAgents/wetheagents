# Spec — paper-passive-bids

Outcome: see outcome.md.

## Behavior

**P1. Passive entry.** New paper trades use execution model `passive_bid_ladder_v1`. A trade opens by recording the order book, strategy metadata, desired price, and a three-level bid ladder. It does not immediately spend notional.

**P2. Ladder.** The ladder has three active bid orders in bought-side price units:

- level 1: `$10` at `desired_price`
- level 2: `$8` at `desired_price - 0.01`
- level 3: `$6` at `desired_price - 0.02`

Prices are clamped to `[0.01, 0.99]`.

**P3. Desired price.** If the book has both best bid and best ask, desired price is mid in the bought-side unit. If mid is unavailable, desired price is one cent better than current taker-touch. For NO, the bought-side touch is `1 - YES best_bid`.

**P4. Tracking.** Every `--trade` or `--settle` invocation first updates open passive trades from the current CLOB book and appends observations to `data/paper/paper_order_snapshots.jsonl`.

**P5. Fill rule.** For a YES bid order:

- pass: current YES best ask `< order.price` -> fill remaining stake
- touch: current YES best ask `== order.price` -> fill up to half stake

For a NO bid order, use current NO ask = `1 - YES best_bid` with the same pass/touch rule.

**P6. Settlement.** Settlement P&L uses only filled stake and shares. Unfilled stake has zero P&L. Historical market-taker rows are ignored by active settlement.

**P7. Reporting.** The HTML report only counts passive ladder rows in the active paper ledger.

## Acceptance

- Unit tests cover desired-price fallback, pass/touch fill semantics, and passive settlement economics.
- Existing CLOB fill tests still pass.
- `python -m scripts.paper_dayof --trade --settle` can run after the live paper ledger has been reset to passive-only rows.
