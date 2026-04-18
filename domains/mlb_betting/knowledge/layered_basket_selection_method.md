# Layered Basket Selection Method

Canonical workflow for promoting MLB betting baskets from research into live production.

This method was finalized during the W3 away-dog ML recheck that produced two promoted live baskets:

- `tier4_ml_depth_load`
- `tier5_ml_obp_recovery`

It exists so future research does not fall back to ad hoc "top ROI row" selection.

## Why This Exists

A raw grid search will always produce attractive high-ROI micro-cells. Most of them are too small, too fragile, or too dependent on one lucky sub-bucket.

The layered basket method answers a stricter question:

1. What is the broad structural basket?
2. Which additional features truly improve that basket?
3. Are they removing bad bets faster than good bets?
4. Is the improvement large enough to justify the lost volume?

## Core Workflow

### 1. Basket-First Search

Start with a broad, interpretable basket in the correct universe.

Example from the W3 away-dog ML cycle:

- `Base A`: `away_sp_fip_short<=5.2`, `bp_ip_3d_home>=4.0`, `effective_obp_away>=0.315`, `bp_sc_xwoba_std_home>=0.28021246065799577`
- `Base B`: `bp_ip_3d_home>=4.0`, `effective_obp_away>=0.315`, `bp_sc_xwoba_std_home>=0.28021246065799577`

Important:

- first isolate lanes that already belong to another strategy
- do not let a stronger lane distort the basket search

In this case `home_bullpen_day=True` was carved out first because that lane already belonged to `tier1_bullpen_day`.

### 2. Layered Refinement

Once the base basket is fixed, test exactly one additional filter at a time.

For every add-on feature, split the base basket into:

- `base_all`: all base-basket games
- `exact-pass`: base basket games where the add-on passes
- `soft-miss`: base basket games where the add-on fails only slightly

This is not just "tighten the threshold and hope". It is a controlled measurement of marginal feature value.

### 3. Near-Miss / Soft-Miss Logic

Soft-miss is sign-aware:

- for `x >= T`: soft-miss is `T - band <= x < T`
- for `x <= T`: soft-miss is `T < x <= T + band`

Band width is not based on the raw threshold. It is:

- `20% * (p90 - p10)` of the feature working range

Why:

- thresholds live on different scales
- this gives a comparable "slightly missed" zone across features

## The Key Diagnostics

### `winner_removed_share`

Share of winning bets removed by the tested add-on.

If the add-on removes too many winners, it may be overfitting or just shrinking volume cosmetically.

### `loser_removed_share`

Share of losing bets removed by the tested add-on.

This is what we want to be high: the filter should preferentially cut bad bets.

### `loss_filter_edge`

Defined as:

- `loser_removed_share - winner_removed_share`

Interpretation:

- positive and meaningful: the add-on removes losers faster than winners
- near zero: probably cosmetic
- negative: dangerous, because the add-on may be throwing away the wrong games

This became the most scalable way to judge whether a feature is truly valuable inside an already-good basket.

## Promotion Rules

An add-on is promotion-worthy when:

- `exact-pass` materially improves ROI over the base basket
- `soft-miss` is clearly worse than `exact-pass`
- `loss_filter_edge` is positive and meaningful
- retained volume is still operationally useful

This is why the method balances:

- `ROI`
- `bets_per_season`
- `exact_retention`
- `winner_removed_share`
- `loser_removed_share`
- `loss_filter_edge`

## Promoted Live Baskets

### `tier4_ml_depth_load`

Promoted from the refined `Base B` lane.

Filters:

- `starter_depth_diff_short <= -0.75`
- `bp_ip_3d_home >= 8.0`
- `effective_obp_away >= 0.315`
- `bp_sc_xwoba_std_home >= 0.28021246065799577`
- `fav_is_home=True`
- `away_is_dog=True`
- `away/home bullpen day=False`

Historical evidence on the Savant window `2015-2025`:

- `55.1` bets/season
- `52.09%` ML win rate
- `+18.13%` ROI overall
- `+29.63%` ROI in `2022-2025`
- `+36.47%` ROI in `2024-2025`

### `tier5_ml_obp_recovery`

Promoted from the refined `Base A` lane after the `effective_obp_away>=0.335` tightening.

Filters:

- `away_sp_fip_short <= 4.8`
- `bp_ip_3d_home >= 4.0`
- `effective_obp_away >= 0.335`
- `bp_sc_xwoba_std_home >= 0.28021246065799577`
- `deficit_recovery_diff <= 0.0`
- `fav_is_home=True`
- `away_is_dog=True`
- `away/home bullpen day=False`

Historical evidence on the Savant window `2015-2025`:

- `89.4` bets/season
- `48.43%` ML win rate
- `+10.91%` ROI overall
- `+11.73%` ROI in `2024-2025`

## Overlap Staking Rule

The two promoted ML baskets are correlated in a useful way.

When the same game qualifies for both:

- keep one final ML pick
- record the second tier in `also_qualified`
- apply `x1.5` to the actionable stake after Kelly sizing

This is not a second bet. It is one bet with stronger confirmation.

Current priority:

- `tier4_ml_depth_load` is primary
- `tier5_ml_obp_recovery` becomes `also_qualified`

## Operational Use

When a future MLB basket looks promising, do not promote it directly from a leaderboard.

Use this workflow:

1. isolate the proper universe
2. define the broad basket
3. run layered exact-pass vs soft-miss refinement
4. inspect `winner_removed_share`, `loser_removed_share`, and `loss_filter_edge`
5. promote only if the add-on improves both quality and decision clarity

That is the canonical path from research basket to live strategy.

## Related Docs

- `bullpen_day_chat_watchlist_2026.md` -- operational watchlist for chat-first bullpen-day rotation checks in the 2026 season
