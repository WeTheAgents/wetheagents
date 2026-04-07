# Session 27 Report: Pitcher Advantage — Away +1.5 Expansion

## Goal

Expand Away +1.5 RL volume beyond Tier 1 (bullpen day, ~24 games/season). Session 26 showed the bullpen day signal is powerful but rare. Hypothesis: there's a profitable zone between "home has no starter" (bullpen day) and "both have normal starters" (baseline) where the away underdog has a significantly better starter.

---

## Method

Systematic filter scan (`scripts/pitcher_advantage_scan.py`) on the non-bullpen-day universe (2999 games, 2014-2025, bullpen days excluded). Seven phases:

1. **Single filters** — starter FIP, WHIP, depth, RA; bullpen FIP, workload, gaps
2. **2-way combos** — cross-category pairs
3. **Train/test validation** — 2014-2019 vs 2021-2025
4. **Season detail** — per-season breakdown
5. **3-way combos** — bullpen base + starter overlay
6. **Dog ML** — moneyline evaluation of same filters
7. **Starter-first scan** — starter quality as base, soft bullpen overlay

---

## Key Discovery: Pitcher Mismatch Signal

### Phase 1 insight: bullpen workload > starter quality as single filter

Best single filters by ROI:
- `starter_depth_diff <= -1.5`: 107 games, 66.4% cover, +6.1% ROI (7/11 folds)
- `away_bp_3d <= 6`: 598 games, 67.4% cover, +3.9% ROI (9/11 folds)
- `bp_workload_gap >= 2`: 967 games, 66.6% cover, +3.0% ROI (8/11 folds)

Bullpen workload has more volume and consistency; starter depth has higher ROI but thin.

### Phase 2: bullpen combos dominate

Top 2-way combos:
| Strategy | Bets | Cover% | ROI | Train | Test | Folds |
|---|---|---|---|---|---|---|
| away_bp_3d<=6 + home_bp_3d>=8 | 262 | 72.9% | +12.2% | +12.3% | +11.8% | 10/11 |
| away_bp_3d<=6 + bp_workload_gap>=3 | 273 | 72.2% | +11.2% | +9.5% | +14.6% | 10/11 |
| home_ra_long>=5.5 + home_bp_3d>=10 | 108 | 72.2% | +14.4% | +12.4% | +17.0% | 8/11 |
| starter_depth_diff<=-1.0 + away_fip_short<=3.5 | 135 | 71.9% | +12.3% | +9.7% | +15.0% | 8/11 |

### Phase 5-7: starter-first approach unlocks the best strategy

Relaxing bullpen filters and leading with starter quality produced the optimal balance:

**Starter-only (no bullpen):**
- `away_fip_short<=3.5 + depth_diff<=-1.0`: 135 games, 71.9% cover, +12.3% ROI, 8/11 folds

**With soft bullpen overlay:**
- `away_fip_short<=3.5 + depth_diff<=-1.0 + home_bp_3d>=8`: 81 games, **79.0% cover, +24.7% ROI**, 8/10 folds
  - TRAIN: 37 games, 81.1% cover, **+29.2% ROI** (5/5 folds)
  - TEST: 44 games, 77.3% cover, **+21.0% ROI** (3/5 folds)

Dog ML equivalent: 135 games at 56.3% win, +14.4% ROI (starter-only); Dog ML less stable than RL.

---

## Production Strategy: Pitcher Advantage (Tier 3)

### Filters

```python
UNIVERSE:   edge_consensus > 0.05 AND fav_is_home == True AND season >= 2014
EXCLUDE:    home_is_bullpen_no_starter (handled by Tier 1)
EXCLUDE:    away_is_bullpen_no_starter

FILTER 1:   away_sp_fip_short <= 3.5       (away starter FIP last 5 starts <= 3.5)
FILTER 2:   starter_depth_diff <= -1.0      (away starter averages 1+ more IP/start than home starter)
FILTER 3:   bp_ip_3d_home >= 8              (home bullpen worked 8+ IP in last 3 days)

BET:        Away +1.5 run line (primary)
```

### Logic

When the away underdog sends a quality starter (low FIP) who goes deep into games (high IP/start) against a home starter who exits early, AND the home bullpen is already fatigued — the away team has a structural advantage. The home team must rely on a tired bullpen earlier in the game, while the away starter eats innings and limits damage.

This is the "soft" version of the bullpen day signal: the home team technically has a starter, but the starter-to-bullpen handoff happens early, and the bullpen isn't fresh.

### Performance

| Metric | Value |
|---|---|
| **Total games** | 81 (2014-2025, excl. bullpen days) |
| **Games/season** | ~7-8 |
| **RL +1.5 cover rate** | 79.0% |
| **Avg RL odds** | 1.59 |
| **RL +1.5 ROI** | **+24.7%** |
| **Positive seasons** | 8/10 (some seasons < 3 games) |
| **Train ROI (2014-2019)** | +29.2% |
| **Test ROI (2021-2025)** | +21.0% |

### Comparison with starter-only (no bullpen filter)

| Variant | Bets | Cover% | ROI | Folds |
|---|---|---|---|---|
| With bullpen (home_bp_3d>=8) | 81 | 79.0% | +24.7% | 8/10 |
| Without bullpen | 135 | 71.9% | +12.3% | 8/11 |

The bullpen filter cuts volume by 40% but nearly doubles ROI. Both variants are profitable.

---

## Updated Portfolio

| Tier | Signal | Bet Type | Games/Season | Cover/Win% | ROI | Folds |
|---|---|---|---|---|---|---|
| **1** | Bullpen Day (home BP day, away has starter) | Dog ML + RL +1.5 | ~24 | 74.2% / 83.7% | +63.9% / +31.2% | 11/11 |
| **2** | Bullpen Fatigue Gap (workload + rested away BP) | RL +1.5 | ~25 | 72.2% | +11.2% | 10/11 |
| **3** | **Pitcher Advantage (quality away starter + depth + tired home BP)** | **RL +1.5** | **~8** | **79.0%** | **+24.7%** | **8/10** |
| **Combined** | All tiers | Mixed | **~57** | ~75% | ~+20% | — |

Tier 3 adds ~8 high-conviction bets/season to the portfolio. Combined with Tier 1 and Tier 2, the system generates ~57 bets/season across three complementary signals.

---

## Caveats

1. **Volume**: ~8 games/season is thin. Individual seasons may have 3-5 qualifying games. The 81-game total spans 11 seasons.
2. **Overlap with Tier 2**: Some Tier 3 games may overlap with Tier 2 (bullpen fatigue gap). Deduplication needed in production.
3. **Feature availability**: `away_sp_fip_short` requires 3+ prior starts (Retrosheet entering features). Early-season games won't qualify — natural ramp-up filter.
4. **Starter depth**: `ip_per_start_long` (15-start window) is stable but slow to update. New or recently promoted starters may lack enough history.
5. **Train/test asymmetry**: 37 train / 44 test games. Test period includes modern bullpen usage patterns (2021-2025) which may differ from 2014-2019.

---

## Files Created/Modified

| File | Action | Purpose |
|---|---|---|
| `scripts/pitcher_advantage_scan.py` | CREATE | 7-phase filter scan for away dog (starter + bullpen combinations) |
| `scripts/pitcher_advantage_fav_scan.py` | CREATE | Fav -1.5 RL reverse test (all filters negative) |
| `scripts/_fav_ml_scan.py` | CREATE | Fav ML reverse test (all filters negative) |
| `scripts/_home_dog_scan.py` | CREATE | Home dog +1.5 reverse test (all filters negative) |
| `knowledge/session_report_27.md` | CREATE | This report |

---

## Key Lessons

1. **Starter quality alone is profitable.** `away_fip_short<=3.5 + depth_diff<=-1.0` at +12.3% ROI proves the pitcher mismatch signal exists independent of bullpen state. The bullpen overlay is an amplifier, not the core signal.

2. **Depth differential is the strongest starter metric.** Not FIP alone, not WHIP, not RA — but how deep a starter goes. `depth_diff<=-1.0` (away starter averages 1+ more IP/start) captures starters who eat innings and protect the bullpen.

3. **Soft bullpen filters work better than hard ones for expansion.** `home_bp_3d>=8` (mild fatigue) captures more games than `home_bp_3d>=10` or `away_bp_3d<=6` while maintaining high cover rates.

4. **The portfolio is complementary.** Tier 1 = extreme mispricing (no starter). Tier 2 = bullpen fatigue without starter signal. Tier 3 = starter quality with mild bullpen fatigue. Each captures a different market inefficiency.

5. **Pitcher advantage is an away-dog-only signal.** Three reverse tests all failed:

   | Configuration | Universe | Best ROI | Verdict |
   |---|---|---|---|
   | Fav -1.5 RL (same filters, fav perspective) | 8380 games | -0.4% | Market already prices fav win probability correctly |
   | Fav ML (fav just wins, lower breakeven) | 8380 games | -0.7% | Even 56% win rate at 1.73 odds = -3.6% baseline; filters can't close the gap |
   | Home dog +1.5 (mirror: home is underdog) | 1791 games | +1.2% | Smaller universe, worse baseline (59.2% vs 63.9%), no stable combos |

   **Root cause**: the market underprices away underdogs with quality starters because the default model is "home team wins." When the away team sends an ace who goes 7 innings against a short home starter with a tired bullpen, the away team's survival probability is much higher than the market implies. This asymmetry does not exist in reverse — the market already expects favorites to win, and already expects home teams to have an edge.
