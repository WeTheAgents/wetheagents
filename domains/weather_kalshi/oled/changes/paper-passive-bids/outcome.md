# Outcome — paper-passive-bids

## Goal

Make day-of paper trading measure passive execution instead of immediate market/taker fills.

The operator needs to know whether the strategy can be profitable when buying only at acceptable prices. Full $25 taker fills are no longer the target; partial fills are acceptable if the market reaches or passes the desired bid price.

## Decisions

- New headline paper stake is `$24`, split into three bid ladder orders: `$10`, `$8`, `$6`.
- The runner records a desired buy price in the bought-side unit:
  - YES trades: YES price.
  - NO trades: NO price, derived from the YES book.
- Default desired price is the decision-time mid when both sides exist.
- If mid is unavailable but the required taker side exists, use one cent better than taker-touch as a fallback desired price.
- A ladder order is considered fully filled when the observed market passes its bid price.
- A ladder order is considered half filled when the observed market only touches its bid price.
- Post-signal observations must continue on every scheduled runner cycle until the trade settles.

## Non-goals

- No real orders, wallet use, or private API keys.
- No queue-position modeling beyond the explicit half-fill-on-touch rule.
- No deletion or rewriting of historical paper rows except normal settlement/status updates.
