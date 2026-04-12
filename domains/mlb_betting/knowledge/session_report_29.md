# Session 29: Production Picks Generator + Data Pipeline Insurance

**Date**: 2026-04-12
**Objective**: Go-live readiness for 2026 MLB betting. Full audit, bug fixes, pick generation.
**Result**: POSITIVE -- 4 bugs fixed, picks generator shipped, 34 unit tests, pipeline healthy.

---

## What We Built

### 1. Data Pipeline Insurance (`data/fetch_2026/io_safety.py`)

Every parquet/state write now goes through a single safe-write entry point:
- **Atomic writes** (tmp + rename -- never half-written files)
- **Timestamped backups** (data/backups/YYYY-MM-DD/, 14-day retention)
- **Sidecar JSONs** (row count, date range, generator name, timestamp per parquet)
- **Append-only audit log** (data/fetch_2026/audit_log.jsonl -- forensic trail)

Wired into: mlb_boxscore.py, orchestrator.py, mlb_api.py, bullpen_features.py, retrosheet_pitchers.py.

### 2. Daily Health Check (`scripts/check_2026_pipeline.py`)

5 hard assertions, runs after the 11:00 results capture:
1. state.json freshness (postgame + boxscore dates within 2 days)
2. games_2026.parquet integrity (no duplicate event_ids, V/H pairing)
3. pitcher_game_logs row count never shrinks (sidecar comparison)
4. Bullpen dual-version (BOTH historical retrosheet/ AND live pitchers_2026/ must exist)
5. audit_log.jsonl has recent entries

Failures append to picks/ALERTS.md for the operator's morning routine.

### 3. Bug Fixes

| Bug | Impact | Fix |
|-----|--------|-----|
| **A: bullpen_features.parquet overwrite** | Historical 2014-2025 wiped on every backfill | Architectural: 2026 writes ONLY to pitchers_2026/; historical paths owned by Retrosheet builders; src/data_loader.py combines both via load_combined_* helpers |
| **B: pitcher_game_logs data loss** | Mar 26-Apr 5 lost (535 rows instead of ~1800) | Backfilled via --backfill-boxscore; insurance prevents recurrence |
| **C: results-capture state drift** | state.json stuck at Apr 3 despite daily runs | Root cause: non-atomic writes; fixed by atomic_write_text for state.json |
| **E: doubleheader collapse (latent)** | Future DH would silently drop one game | _dedup_games uses (event_id, team, vh); 6 regression tests in test_orchestrator_dedup.py |

### 4. Picks Generator (`scripts/generate_picks_2026.py`)

The core deliverable -- wires the full pipeline into a daily-use CLI:

```
load_all_seasons -> apply_data_filters -> add_derived_odds
  -> build_all_features -> add_derived_for_strategies
  -> Tier 1/2/3 + Fav-RL filters -> dedup -> Polymarket prices -> Kelly sizing
  -> picks/picks_YYYY-MM-DD.json + picks/pick_log.jsonl
```

**Four strategies** in `src/strategies/`:
- **tier1_bullpen_day** -- Sess 26 (ML_dog + RL +1.5, p=0.742/0.837)
- **tier2_fatigue_gap** -- Sess 26 (RL +1.5, p=0.722)
- **tier3_pitcher_advantage** -- Sess 27, short-window swap per Decision SS9.1 (RL +1.5, p=0.790)
- **fav_rl** -- Sess 25 (RL -1.5, p=0.498)

YRFI deferred (no saved CatBoost model on disk).

### 5. Target Pricing (L1 Sweet-Spot System)

Each pick now includes:
- `target_min_decimal`: breakeven odds (edge=0, DON'T bet below this)
- `target_sweet_decimal`: wait-for price (where edge = --target-edge, default 20%)
- `kelly_at_sweet`: Kelly fraction if filled at the sweet price

Operator output:
```
TIER                   AWAY @ HOME MKT      SIDE       P    REF  POLY  EDGE  STAKE   MIN SWEET K@SW
tier1_bullpen_day       COL @ TOR  ML_dog   away   0.705   3.34    -   +41%  14.5%  1.42  1.98  40%
tier1_bullpen_day       COL @ TOR  RL_+1.5  away   0.795   2.09    -   +32%  15.2%  1.26  1.68  49%
```

MIN/SWEET columns tell the operator: "you can bet now at ref odds, or WAIT for the sweet price for +20% edge and dramatically higher Kelly."

---

## Validation on 2026 Data

### Pipeline end-to-end
```
HISTORICAL bullpen           71,880 rows  (2010-2025)
LIVE 2026 bullpen               416 rows  (Mar 26 - Apr 11)
HISTORICAL starter logs      75,950 rows  (37,975 games)
LIVE 2026 pitcher logs        1,818 rows  (209 games)
games_2026.parquet              414 rows  (207 games)
check_2026_pipeline.py       ALL OK
```

### Strategy fire rates (17 days, Mar 26 - Apr 11)
```
Tier 1 bullpen day:  1 unique game  (2 picks: ML + RL)  -> ~19/season
Tier 3 pitcher adv:  2 unique games (2 picks)            -> ~19/season
Fav -1.5 RL:         2 unique games (2 picks)            -> ~19/season
Tier 2 fatigue gap:  0 picks (expected -- ramp-up period)
```

### Retroactive results (if picks were live)

| Date | Pick | Tier | Result | Odds | PnL |
|------|------|------|--------|------|-----|
| Mar 30 | COL @ TOR ML_dog | T1 | ? (to verify) | 3.34 | ? |
| Mar 30 | COL @ TOR RL +1.5 | T1 | ? (to verify) | 2.09 | ? |
| Apr 1 | OAK @ ATL RL -1.5 | Fav-RL | ? | ? | ? |
| Apr 3 | CIN @ TEX RL -1.5 | Fav-RL | ? | ? | ? |
| Apr 6 | DET @ MIN RL +1.5 | T3 | **LOST** (3-7, margin -4) | 1.48 | -5.85% |
| Apr 11 | MIN @ TOR RL +1.5 | T3 | **WON** (7-4, margin +3) | 2.64 | +24.5% |

Apr 6 DET@MIN and Apr 11 MIN@TOR are confirmed. Others need manual lookup. MIN@TOR Apr 11 was a textbook Tier 3: Lauer (7.82 ERA) exits early, tired TOR bullpen can't hold, 3-run HR in the 3rd is the exact explosive-inning pattern Sess 27 identified.

### fav_is_home filter discovery

During development, discovered that 3 of 4 early-season Tier 1 bullpen-day games had already moved so the road team became the favorite (market priced the bullpen-day announcement). The `fav_is_home == True` filter from Sess 26 correctly excludes these -- but one of them (MIL @ BOS Apr 6) would have won both picks (+24.64% bankroll). This is a single observation, not actionable -- but worth tracking as "line-flipped bullpen day" shadow picks in Session D.

---

## Key Architecture Decisions

1. **build_all_features, NOT build_spec_features** for live picks. build_spec_features drops all April games (historical backtest convention). The picks generator must call build_all_features on unfiltered data.

2. **Dual-path layout** (architectural Bug A fix). 2026 fetcher writes exclusively to `data/processed/pitchers_2026/`. Historical Retrosheet scripts write to `data/processed/pitchers/` and `data/processed/retrosheet/`. `src/data_loader.load_combined_*` reads both and concats. Neither writer can clobber the other.

3. **add_derived_for_strategies** computes fav-oriented diffs (fav_implied, fav_is_home, fav_starter_fip_diff, etc.) that build_spec_features normally adds but build_all_features doesn't. This bridges the gap without touching the core features.py.

4. **Historical p shrinkage** (plans/SS11.1 #14): Kelly uses `0.95 * historical_cover_rate` as the true probability. Bakes in a 5% margin of safety so we don't over-bet a sample-mean estimate.

---

## Files Created/Modified

| File | Action | Purpose |
|------|--------|---------|
| `data/fetch_2026/io_safety.py` | CREATE | Atomic writes, backups, sidecars, audit log |
| `scripts/check_2026_pipeline.py` | CREATE | Daily health check (5 assertions) |
| `scripts/generate_picks_2026.py` | CREATE | Daily picks generator (Tier 1/2/3 + Fav-RL + target pricing) |
| `src/strategies/__init__.py` | CREATE | Strategy package entrypoint |
| `src/strategies/base.py` | CREATE | Pick dataclass, add_derived_for_strategies, feature_snapshot |
| `src/strategies/tier1_bullpen_day.py` | CREATE | Bullpen-day dog filter (Sess 26) |
| `src/strategies/tier2_fatigue_gap.py` | CREATE | Bullpen workload gap filter (Sess 26) |
| `src/strategies/tier3_pitcher_advantage.py` | CREATE | Pitcher advantage filter (Sess 27, short-window) |
| `src/strategies/fav_rl.py` | CREATE | Fav -1.5 RL filter (Sess 25) |
| `tests/test_orchestrator_dedup.py` | CREATE | 6 DH dedup regression tests |
| `tests/test_strategies.py` | CREATE | 28 strategy filter + Pick + derived column tests |
| `data/fetch_2026/mlb_boxscore.py` | MODIFY | Bug A fix + insurance wiring |
| `data/fetch_2026/orchestrator.py` | MODIFY | Bug E fix + insurance wiring |
| `data/fetch_2026/mlb_api.py` | MODIFY | Atomic pitcher cache writes |
| `src/data_loader.py` | MODIFY | Combined loaders + helper params |
| `src/features.py` | MODIFY | Read combined paths |
| `src/bullpen_features.py` | MODIFY | Safe historical builder writes |
| `src/retrosheet_pitchers.py` | MODIFY | Safe historical builder writes |
| `scripts/fetch_daily_2026.py` | MODIFY | Unicode fix |
| `.gitignore` | MODIFY | data/backups/ |
| `knowledge/session_report_29.md` | CREATE | This report |

---

## Next Steps

### Session D: Polymarket Order-Book Monitor (L2)

Operator observation: Polymarket shows regular odds spikes, especially on early lines and post-lineup-announcement volatility windows. The target pricing system (L1) tells the operator WHAT price to wait for, but can't alert them WHEN it arrives. L2 fills this gap:

- `scripts/monitor_polymarket_picks.py` -- reads picks_YYYY-MM-DD.json, polls order book every 5-15 min
- Alerts in picks/ALERTS.md when `best_ask >= target_sweet_decimal`
- Scheduled task from 12:00 Kyiv to first pitch (~02:00 Kyiv next day)
- Read-only, no order placement
- ~150 LOC, separate PR
- Key volatility windows: 2-3h pre-first-pitch (lineup cards), 30min pre-game (sharp money), evening market open (low liquidity overshoots)

### Session E: Shadow Pick Tracking

Track "line-flipped" Tier 1 games (bullpen day confirmed but market moved so home is no longer favorite). These were validated in the original universe but dropped by the `fav_is_home` filter. Apr 6 MIL@BOS showed a 2W/0L shadow result. Track outcomes through 2026 to decide if the filter should be relaxed.

### Session F: Auto-Placed Limit Orders (L3)

Only after 4-6 weeks of manual L2 with >70% fill rate at target prices. Requires:
- MATIC wallet + private key management
- Polymarket CLOB API integration for resting limit orders
- Separate risk controls (max stake per game, daily loss limit)
- Full operator sign-off before enabling

**Not recommended until calibration on real market data is established.**

### Weekly Sunday Reviews

Starting Apr 13 (first Sunday after go-live), weekly entry in this report (or a new session_report_30.md):
- Live ROI vs backtest expectation per tier
- Fill rate at target prices
- Feature coverage ramp (pitcher FIP, power_rate window fill)
- Alert counts from check_2026_pipeline.py

---

## Key Lessons

1. **Atomic writes are non-negotiable for any pipeline that runs on a schedule.** A single half-written state.json or parquet can cascade into days of stale data without anyone noticing. The insurance layer cost ~250 LOC and prevents an entire class of bugs.

2. **build_spec_features vs build_all_features is a real production trap.** Spec drops April -- fine for backtesting 2014-2025 where April has low signal, catastrophic for 2026 live picks where April is the ONLY data.

3. **fav_is_home filter is load-bearing.** Without it, picks volume nearly doubles but many are in a zone the backtest never validated (road-favorite bullpen days). Maintaining Sess 26 universe parity is the conservative-correct choice; shadow tracking will decide if relaxation is warranted.

4. **Target pricing is free alpha.** Computing the sweet-spot odds (20% edge target) costs zero additional API calls and immediately changes the operator's decision from "bet now at 1.48" to "wait for 1.82 if you can." The math is trivial but the behavioral impact is large.

5. **Polymarket order-book monitoring is the highest-leverage next step.** The picks generator identifies WHAT to bet; target pricing identifies WHEN (at what price). The only missing piece is WHO watches the order book -- currently it's the operator refreshing a tab. A 5-minute cron reading order books and alerting on target hits would capture volatility windows during Kyiv sleep hours (02:00-05:00, prime MLB game time).
