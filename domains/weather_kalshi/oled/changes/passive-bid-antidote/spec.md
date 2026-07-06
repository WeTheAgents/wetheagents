# Spec — Passive-Bid Adverse Selection: Diagnosis + Intraday-Slope Antidote

## Outcome summary

Passive 3-tier bid execution (codex passive-bids worktree) avoids slippage but is
adversely selected. Operator's goal: not a verdict but an **antidote** using intraday
weather, replacing the previous-day-based decision. Research only; no runner change here
(recommendations feed a later runner update).

## Question

Can an intraday weather signal re-select passive fills away from losers?

## Inputs (all local, no API)

- Passive ledger: `D:/GitHub/wetheagents-codex-paper-passive-bids/.../data/paper/paper_trades.jsonl`
  (27 settled), `paper_order_snapshots.jsonl`.
- Weather/market history (main domain): `data/processed/metar_day_table.parquet`
  (running max by local hour rm10..rm21, rise15, settle_hour),
  `data/raw/polymarket/all_cities_price_history.parquet` (10-min candle path),
  `data/processed/dayof_study_checkpoints.parquet`, `data/raw/snapshots/*` (NBM/ens forecasts).

## Requirements

- **R1 Diagnosis.** From the live ledger: 2×2 win×fill, P(fill|outcome), total P&L.
- **R2 Signal.** Establish that the intraday 2h running-max slope separates rise-days at
  scale, and that the morning forecast does not (document the contrast).
- **R3 Gate.** Define `locked` = (2h pre-entry slope ≤ 0) AND (entry hour ≥ city climatological
  peak hour). Live-decidable from hourly METAR.
- **R4 Gated-passive sim.** On the historical candle path, place a passive bid at
  entry_price − 1¢; it fills if a later candle ≤ bid; outcome from resolution. Compare
  ungated / gated / excluded on: P(fill|loss), P(win|fill), P&L. Test window > 2026-06-15.
- **R5 Niche + decomposition.** Gate × entry-price band (locate the profitable cell).
  Decompose filled losses into rise-losses (rise15=1, weather-gateable) vs basis-losses
  (rise15=0, WU≠METAR). Report the basis ceiling (gated P&L with basis-losses removed).
- **R6 Deliverable.** `reports/passive_antidote_report.html` (Russian, Plotly inline) with
  explicit verdict + prioritized data levers (resolution-station audit, 5-min ASOS, hourly HRRR).

## Acceptance criteria

- [ ] R1 reproduces P(fill|loss)=100%, P(fill|win)=27%, −$373 from the live ledger.
- [ ] R4 gated cell shows reduced P(fill|loss) and raised P(win|fill) vs ungated.
- [ ] R5 identifies at least one positive-P&L cell (or states none exists) and quantifies
      the rise/basis split.
- [ ] Report built; every headline number produced by the script; no external deps.
- [ ] Thin-n cells (< ~30) flagged; live n=27 treated as directional only.
