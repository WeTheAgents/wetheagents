# Session 9 Handoff — New Hypothesis (post-intraday)

## Where we are

Intraday scalping is dead, and it died the way an efficient market kills things:
- The curmax edge (+65% backtest) was a **midpoint artifact** — not capturable.
- **Marketable** execution dies on slippage (12–19¢ into thin books).
- **Passive** execution dies on adverse selection (P(fill|loss)=100%, P(fill|win)=27%).
- Winner-no-fill analysis proved the market reprices the intraday lock/deceleration
  **faster than our signal is actionable** — the market is efficient at that timescale.

Two execution models, one conclusion: on the fast timescale, **spread ≈ edge**. We were
competing on forecasting skill and speed — exactly where everyone has the same inputs.

## Meta-lesson (the pivot)

Stop competing where the market is efficient (forecasting, intraday speed). Compete where
inefficiency **persists structurally**:
1. **Rules/plumbing edges** — knowing the resolution mechanics better than the crowd.
2. **Behavioral biases** — favorite-longshot, round-number, recency; small per-trade,
   persistent because they need discipline + capital, not skill.
3. **Horizon gaps** — the market may be efficient day-of but thin/mispriced at T-2/T-3.

---

## LEAD HYPOTHESIS — the resolution-basis edge (WU vs METAR)

**Claim.** Polymarket resolves the daily-high markets via **Weather Underground**
(`wunderground.com/history/daily/{STATION}`), but traders forecast using METAR/NWS/model
consensus for that airport. If WU has a **systematic, predictable basis** vs METAR (rounding,
sensor, station identity, or day-boundary), then at a **day-ahead horizon** the market prices
the METAR-anchored forecast while resolution follows WU — a persistent gap that is
**orthogonal to forecasting skill** and therefore not competed away.

**Why this is not another intraday trap.** It is not a speed race. The edge is knowing the
resolution rule better, and it is harvested slowly (enter day-ahead, hold to resolution). Near
resolution the market IS efficient (it sees the realized reading); the edge lives at the
**medium horizon**, before the realized WU number exists, where the market can only price the
forecast.

**Direct evidence we already have:**
- London 2026-06-20: METAR KEGLL max 25.0°C, market **resolved 26°C** (+1°C basis).
- Dallas 2026-06-26: our KDFW max 97°F, market resolved **94–95°F** (likely station mismatch).
- ~20% of the passive study's losses were "basis" losses (max never left our bracket, but WU
  resolved a different bracket). The winning bracket tracked WU, not METAR.
- Session-8 note: resolution reads WU; `icao_map.json` primaries are unaudited vs the WU station.

**First test (crisp, falsifiable):** At a day-ahead snapshot, does the **market's implied
temperature track METAR/forecast or WU?**
1. Scrape WU daily-high history for the ~15–20 resolution stations (this IS the resolution
   source; the crowd's anchor is the forecast).
2. Compute WU−METAR daily-high basis per station/month; test for a **systematic component**
   (mean ≠ 0, low residual variance) vs pure noise.
3. Confirm the market-truth winner (last candle ≥ 0.90) tracks WU better than METAR (strong prior).
4. Build a **WU-adjusted bracket distribution** at day-ahead; compare to market-implied;
   measure edge and executability (spread on the target bracket at that horizon).

**Go / no-go:** edge exists iff (a) WU−METAR has a predictable component ≥ ~half a bracket
(often 1°F), AND (b) the day-ahead market price tracks the forecast (METAR-anchored), not WU.
**Kill it if:** WU−METAR is zero-mean noise, OR the day-ahead market already prices WU.

**Data/tools ready:** `data/raw/metar/*` (hourly, 45 stations), market-truth resolutions
(`assign_positions`, last-candle≥0.9), `data/raw/polymarket/all_cities_price_history.parquet`
(day-ahead prices), `data/static/icao_map.json` (to audit). Need: a WU history scraper.

---

## ALTERNATE 1 — Favorite-longshot / structural mispricing (slow, capital-driven)

Very first analysis this project cycle: buying the favorite at market open gave **+18% ROI**;
cheap wings were overpriced 3–5×. Classic favorite-longshot bias, well-documented and
persistent in retail prediction markets. Edge = systematically fade longshots / back favorites
across many events; slow execution (open→resolution) sidesteps the adverse-selection race.
Research: measure the full favorite-longshot curve across 42 cities on market-truth labels,
calibrate the optimal fade, check it survives the favorite's spread, size it. Risk: small
per-event edge, needs many events + discipline.

## ALTERNATE 2 — Calibrated-tail edge at T-2/T-3 (the original NBM thesis, now testable)

The market is efficient day-of, but at T-2/T-3 participation is thinner and it may misprice
tail uncertainty. We have **NBM QMD pre-calibrated percentiles** (P1–P99) and GEFS ensembles —
exactly a tail product. If the T-2 market prices brackets too confidently (too little tail
mass) or too diffusely, our calibrated empirical CDF vs market gives edge. Slow (T-2 entry,
hold), avoids intraday efficiency. This is the Session-7 thesis that never got a clean test
because data hadn't matured; now we have months of candles + NBM.

---

## Recommendation

Lead with the **resolution-basis edge** — it is the most differentiated (rules-knowledge, not
forecasting), has the strongest direct evidence, and is orthogonal to everything that just
killed us. First concrete step: build the WU history scraper and run the basis test (steps 1–3
above). If WU−METAR has a systematic component and the market anchors to METAR at day-ahead,
that is a real, persistent, non-competed edge. If not, fall back to Alternate 2 (calibrated
tails at T-2), then Alternate 1.

## Do NOT repeat

- No new intraday execution scheme (marketable/passive both dead; market efficient at the lock).
- Don't trust midpoint/candle P&L as tradeable — always model spread + fill.
- Small live-n cells are noise; require historical scale + honest execution modeling.
