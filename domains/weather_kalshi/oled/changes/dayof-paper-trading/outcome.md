# Outcome: dayof-paper-trading

## Outcome Version Log
| Version | Date | Change | Human Verified |
| --- | --- | --- | --- |
| 0.1 | 2026-07-03 | Initial outcome | pending (operator said "go" on the study's next-steps plan) |
| 0.2 | 2026-07-03 | BR6 stake changed: $100 → dual $10/$25 per trade (executability study: $100 market orders walk 12–19¢ into thin books; touch cost ≈1.5¢) | yes — operator: "давай сделаем $10 и $25. go" |

## Why Now

The day-of nowcast study (oled/changes/dayof-nowcast-edge-study, 2026-07-03) found two
candidate strategies with positive backtest ROI, but both are measured on 10-minute
candles (≈ midpoints), not executable prices. The single biggest unknown standing
between "backtest edge" and "real edge" is executability: spreads, order-book depth,
and whether the assumed 1¢ slippage is realistic. No real money may be risked until
paper trading answers this.

## Business Outcome

A pipeline that, without risking money, produces an evidence trail answering:
1. Can strategy A (buy the bracket containing today's running max at ~15:00 local)
   and strategy B (buy NO on the bracket above the running max after ~16:00 local)
   actually be executed at prices close to backtest assumptions?
2. What is the realized paper P&L of both strategies, day by day, city by city?

After 2–3 weeks of accumulation the operator reads one HTML report and makes a
go / no-go decision on real-money trading.

## Actors / Data Owners

- **Operator** — owns the go/no-go decision; reads the HTML report.
- **Agent0 / weather_kalshi pipeline** — owns collection scripts and paper ledger.
- **Polymarket CLOB** — source of order books (public, unauthenticated reads).
- **Aviation Weather Center** — source of live METAR observations.

## Business Rules

- **BR1. No real orders.** The pipeline only reads market data. It never posts orders,
  never touches wallets or API keys. Paper fills are simulated.
- **BR2. Paper fills must be pessimistic-realistic**: a simulated buy fills by walking
  the actual ask side of the recorded order book for the intended stake; if the book
  cannot fill the stake, the trade is recorded as partially filled or unfillable.
  Both the book-based fill price and the candle midpoint are recorded, so
  "backtest assumption vs reality" is measurable per trade.
- **BR3. Decision inputs must be as-of decision time**: the running max comes from live
  METAR fetched at trade time, market metadata from the most recent daily collection.
  No look-ahead.
- **BR4. Trades settle against market resolution** (the winning bracket), consistent
  with the study's ground-truth convention — not against our own obs pipeline.
- **BR5. Every scheduled run leaves a trace** (timestamp, cities considered, trades
  made or reasons for none) so silent failures are visible in the report.
- **BR6 (v0.2). Two nominal stakes are simulated per trade: $10 and $25** ($25 is
  primary for skip logic and headline P&L). Rationale: the executability study
  showed $100 market orders walk 12–19¢ into thin books while touch-size orders
  pay ~1.5¢ — $10/$25 match realistic book capacity.

## Scenarios

- S1. At 15:00 Tokyo time the runner fetches Tokyo METAR, finds running max 31°C,
  buys paper YES on the "31°C" bracket at the recorded ask; the trade appears in the
  ledger with book snapshot attached; next day it settles as won/lost.
- S2. At 16:30 Hong Kong time the runner buys paper NO on the bracket above the
  running max; ledger records fill from the bid side of YES (NO = 1 − bid walk).
- S3. The book for a target bracket is empty or one-sided → trade logged as
  "unfillable"; this is itself a key executability result.
- S4. CLOB or AWC is unreachable on a run → the run logs the failure and exits
  cleanly; the report shows coverage gaps.
- S5. Operator opens the HTML report at any time: sees executability stats
  (spread/depth vs assumptions), P&L to date per strategy, and run health.

## Non-Goals

- No real-money execution, no order signing, no wallets.
- No new strategy research — parameters (15:00 / 16:00 windows, price bands) come
  from the completed study.
- No backfill of order books for past dates (impossible — books are ephemeral).
- No change to existing daily collection jobs.

## Human Verification Checklist

- [ ] Operator confirms the scheduled job exists and runs every ~15 minutes.
- [ ] After the first day: ledger contains trades (or explicit "no window hit" traces).
- [ ] Report opens locally, shows at least one settled day with P&L.
- [ ] Spot-check one paper trade by hand against Polymarket's UI prices for that time.
