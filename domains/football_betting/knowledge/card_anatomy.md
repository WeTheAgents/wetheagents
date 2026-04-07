# Match Card Anatomy

Example: **Trabzonspor vs Antalyaspor, 2023-02-01** (actual result: 2-0 Home)

## MATCH CARD (neutral, for Analyst)

Analyst sees ONLY this card. No odds, no model, no betting context.

```
MATCH: TS vs ANT -- 2023-02-01, Season progress: 59%
```
- **TS / ANT**: canonical team codes (Trabzonspor / Antalyaspor)
- **Season progress 59%**: normalized matchday (0% = season start, 100% = end). Mid-season = rosters stabilized, form data is reliable.

```
-- Squad Stability --
  TS: SSS 0.73 (cumulative) 0.73 (last 10) -- moderate rotation
  ANT: SSS 0.44 (cumulative) 0.44 (last 10) -- significant rotation
  Stability gap: +0.29 (home - away)
```
- **SSS** (Squad Stability Score): weighted measure of how many regular starters are in today's XI. 1.0 = full-strength, 0.0 = all reserves.
  - **cumulative**: season-to-date, considers all prior matches
  - **last 10**: rolling window, captures recent rotation patterns
- **Qualitative labels**: >0.75 = core intact, 0.60-0.75 = moderate rotation, <0.60 = significant rotation
- **Stability gap**: home SSS minus away SSS. +0.29 = home has much more settled lineup. This is our core signal -- bookmakers underestimate coordination loss from wholesale rotation.

```
-- Form & Momentum --
  TS: 1.75 PPG (season), 1.80 PPG (last 5), streak L1
    Attack: 1.80 GF/game, Defense: 1.40 GA/game (last 5)
  ANT: 1.11 PPG (season), 1.00 PPG (last 5), streak W1
    Attack: 1.40 GF/game, Defense: 1.60 GA/game (last 5)
```
- **PPG (season)**: points per game, season-to-date. Turkish league: 3 for win, 1 for draw, 0 for loss. 1.75 is solid (roughly 5th-6th place pace).
- **PPG (last 5)**: recent form, captures hot/cold streaks.
- **Streak**: W3 = won last 3, L1 = lost last 1, D = draw. Positive momentum vs negative.
- **Attack (GF/game)**: goals scored per game, last 5. Measures offensive potency.
- **Defense (GA/game)**: goals conceded per game, last 5. Lower = better. ANT at 1.60 = leaky defense.

```
-- Congestion --
  TS: 4 days rest, 2 matches in 14 days
  ANT: 4 days rest, 2 matches in 14 days
```
- **Days rest**: days since last match. <=2 = VERY FATIGUED, <=3 = FATIGUED. 4+ = normal.
- **Matches in 14 days**: fixture density. 4+ = heavy congestion, especially combined with short rest.
- Teams with European competition (Champions League, Conference League) have much higher density.

```
-- Context --
  Home: TS (Big-3: No)
  Away: ANT (Big-3: No)
  Season progress: 59%
```
- **Big-3**: Galatasaray (GS), Fenerbahce (FB), Besiktas (BJK). Our model is -18% vs Pinnacle on Big-3 matches (market prices them perfectly). Non-Big-3 matches are where we have edge.

---

## BETTING CARD (full, for Expert)

Expert sees everything the Analyst saw PLUS:

```
-- Market Odds (Pinnacle) --
  Home: 1.64 (impl 59.2%)
  Draw: 4.06 (impl 23.9%)
  Away: 5.76 (impl 16.9%)
  Asian Handicap: Home -0.75 @ 1.93 / Away +0.75 @ 1.97
  Line movement: Home -0.028 (drifted), Draw +0.011 (shortened), Away +0.019 (shortened)
```
- **Odds**: Pinnacle closing (sharpest bookmaker). Decimal format: bet 1 unit, get 1.64 back on home win.
- **impl (implied probability)**: vig-removed fair probability. 1/1.64 = 61.0%, but after removing overround (sum = 103.2%) we get fair 59.2%.
- **Asian Handicap**: line + odds. Home -0.75 means home must win by 1+ to fully win AH (half-win on exactly 1 goal margin with quarter lines).
- **Line movement**: change in implied probability from opening to closing. Negative = odds drifted (less money coming in). Positive = shortened (sharp money backing this outcome).

```
-- Model Predictions --
  Expected goals: Home lam=1.82, Away lam=1.05 (total 2.87)
  Model probabilities: Home 55.4%, Draw 25.0%, Away 19.5%
  Over 2.5: 53.3%
  Home -0.5: 55.4%, Home -1.5: 29.7%
```
- **lam (lambda)**: Poisson expected goals from our CatBoost ensemble (baseline + 4 biased specialists + Ridge meta-learner).
- **Model probabilities**: derived via bivariate Poisson convolution (rho=0.22 for goal correlation). These are the probabilities the expert compares against market.
- **Over 2.5**: probability total goals > 2.5.
- **Home -0.5 / -1.5**: model probability home covers Asian Handicap at those lines.

```
-- Discrepancy (Model - Market) --
  Home: -3.8% (market OVERRATES home)
  Draw: +1.1% (market UNDERRATES draw)
  Away: +2.6% (market UNDERRATES away)
  Largest edge: Home -3.8%
```
- The core signal for the Expert. Shows where our model disagrees with the market.
- Positive = model sees higher probability than market (potential value bet).
- Negative = model sees lower probability (market overrates this outcome).
- In this example: market gives home 59.2% but our model says 55.4% -- no value on home win.

```
-- Regime Flags --
  Squad disruption: YES (SSS diff +0.29)
  Congestion: NO
  Big-3 involved: NO
```
- Binary flags for the regimes where our model has historical edge.
- **Squad disruption** (SSS diff > 0.15): one team significantly rotated.
- **Congestion** (any team <= 3 days rest): fatigue factor.
- **Big-3 involved**: auto-PASS regime for the expert.

```
-- Analyst Scenario --
[Injected from Analyst's GameScenario output]
```
- The Analyst's narrative prediction (winner, score, tightness, key factors).
- Expert uses this as qualitative confirmation/contradiction of the numbers.
