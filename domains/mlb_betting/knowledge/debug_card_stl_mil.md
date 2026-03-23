# STL@MIL 2025-06-14 — Card Debug (actual total=13, OVER)

## Analyst Card (neutral, no betting context)

```
GAME: STL @ MIL — 2025-06-14 00:00:00 | O/U Line: 8.5

── Scoring Environment ──
Combined RPG (season): 8.49 (STL 4.25 + MIL 4.24)
Combined RPG (last 10): 6.60 (STL 3.50 + MIL 3.10)
Scoring momentum (L10 - season): -1.89
Combined RAPG: 8.22 (STL 4.13 + MIL 4.09)
RPG vs O/U line: -0.01
Recent RPG vs O/U line: -1.90
Combined RAPG vs O/U line: -0.28

── Pitching: Starters ──
STL: palla001 (RHP), 11 starts
  FIP: 4.43 (below-avg) → momentum +0.00 (stable)
  K/BB: 2.2 (average)  K/9: 6.0 (average)
  IP/start: 5.7 (adequate)
MIL: quinj001 (LHP), 8 starts
  FIP: 4.96 (below-avg) → momentum +1.41 (DECLINING)
  K/BB: 1.6 (average)  K/9: 7.8 (good)
  IP/start: 5.1 (adequate)
Combined starter FIP: 9.38 (both weak)
Combined IP/start: 10.8 (average)
Quality floor (worst starter FIP): 4.96 (below-avg)

── Lineup vs Pitcher Hand ──
STL top-3 OBP vs LHP: 0.332 (average)
MIL top-3 OBP vs RHP: 0.327 (struggles)

── Pitching: Bullpen ──
Bullpen FIP (season): STL 4.79 | MIL 3.75
Bullpen FIP (7-game): STL 4.78 | MIL 3.49
  MIL bullpen oscillator (7g - season): -0.35
  STL bullpen oscillator (7g - season): +0.63
Combined bullpen momentum: +0.28
BP workload (3d IP): STL 10.3 | MIL 11.0
Fatigue composite: oscillator +0.28, combined workload 21 IP

-- Offense & Defense vs League --
Offense vs league: STL 101% (AVERAGE) | MIL 100% (AVERAGE)
Defense vs league: STL 98% (AVERAGE) | MIL 97% (AVERAGE)

── Recent Trends ──
Combined 1st-inning scoring rate: 0.46 (average)
Combined hold rate: 1.93 (both hold leads)

── Context ──
Month: June | Half: 1st half (pre-ASG)
Games played: 60/68 (adequate sample)
O/U line: 8.5 (normal)
```

## Expert Card (OVER pipeline, with P(over))

```
GAME: STL @ MIL — 2025-06-14 00:00:00 | O/U Line: 8.5 | Model P(over): 54%

── Scoring Environment ──
Combined RPG (season): 8.49 (STL 4.25 + MIL 4.24)
Combined RPG (last 10): 6.60 (STL 3.50 + MIL 3.10)
Scoring momentum (L10 - season): -1.89
Combined RAPG: 8.22 (STL 4.13 + MIL 4.09)
RPG vs O/U line: -0.01
Recent RPG vs O/U line: -1.90
Combined RAPG vs O/U line: -0.28

── Pitching: Starters ──
STL: palla001 (RHP), 11 starts
  FIP: 4.43 (below-avg) → momentum +0.00 (stable)
  K/BB: 2.2 (average)  K/9: 6.0 (average)
  IP/start: 5.7 (adequate)
MIL: quinj001 (LHP), 8 starts
  FIP: 4.96 (below-avg) → momentum +1.41 (DECLINING)
  K/BB: 1.6 (average)  K/9: 7.8 (good)
  IP/start: 5.1 (adequate)
Combined starter FIP: 9.38 (both weak)
Combined IP/start: 10.8 (average)
Quality floor (worst starter FIP): 4.96 (below-avg)

── Lineup vs Pitcher Hand ──
STL top-3 OBP vs LHP: 0.332 (average)
MIL top-3 OBP vs RHP: 0.327 (struggles)

── Pitching: Bullpen ──
Bullpen FIP (season): STL 4.79 | MIL 3.75
Bullpen FIP (7-game): STL 4.78 | MIL 3.49
  MIL bullpen oscillator (7g - season): -0.35
  STL bullpen oscillator (7g - season): +0.63
Combined bullpen momentum: +0.28
BP workload (3d IP): STL 10.3 | MIL 11.0
Fatigue composite: oscillator +0.28, combined workload 21 IP

-- Offense & Defense vs League --
Offense vs league: STL 101% (AVERAGE) | MIL 100% (AVERAGE)
Defense vs league: STL 98% (AVERAGE) | MIL 97% (AVERAGE)

── Recent Trends ──
Combined 1st-inning scoring rate: 0.46 (average)
Combined hold rate: 1.93 (both hold leads)

── Context ──
Month: June | Half: 1st half (pre-ASG)
Games played: 60/68 (adequate sample)
O/U line: 8.5 (normal)
```

## Expert Genomes

### OffenseFirst
```yaml
name: OffenseFirst
version: 1
philosophy: |
  Scoring happens when hot lineups meet mediocre pitching, and markets
  chronically underestimate this. I look for the gap between what the O/U
  line implies and what these offenses actually produce. When combined RPG
  is well above the line AND recent trends confirm the surge, OVER has
  structural value. The market anchors on pitcher names; I anchor on the
  lineups actually stepping into the box today. Cold pitching + hot bats
  is a recipe for runs that the line hasn't caught up to.

principles:
  - >
    Combined RPG vs line is my primary OVER signal. When combined season
    RPG exceeds the O/U line by 0.5+ runs, the market is underpricing
    scoring. A +1.0 gap or more is a strong OVER indicator.
  - >
    Recent RPG (last 10 games) trending UP above season average confirms
    offensive momentum. When both season AND recent RPG agree above the
    line, conviction is highest. If recent is falling while season is high,
    the hot streak may be fading — reduce confidence.
  - >
    Offense vs league average above 105% on BOTH sides creates explosive
    conditions. Two above-average offenses generate more scoring than the
    sum of their parts because both bullpens face sustained pressure.
  - >
    First-inning scoring rate above 0.55 combined means early runs are
    likely. Games that start with 1st-inning scoring rarely finish under
    the total — early runs set a pace the market didn't expect.
  - >
    The quality floor (worst starter FIP) matters most for OVER. When
    the worst starter on the mound has FIP above 4.5, one side alone can
    push 4-5 runs. Combined starter FIP above 9.0 = OVER territory.
  - >
    Combined RAPG (runs allowed) above the line means both pitching
    staffs are leaking runs at a pace that supports OVER regardless of
    today's specific starter. RAPG captures the full staff picture.

anti_patterns:
  - >
    Never bet OVER when combined RPG is 1+ runs BELOW the line AND both
    offenses are below league average. Cold teams don't suddenly explode.
    Low RPG + weak offenses = the scoring just isn't there.
  - >
    One elite starter (FIP < 3.0) suppresses one side completely. Unless
    the OTHER starter is also weak (FIP > 4.5), total runs stay low.
    Don't override elite pitching with environment signals.
  - >
    The OVER Signal Summary shows indicator count. If 0-1 indicators
    fired out of 5, the ML model's signal is likely noise — say PASS.
    I need 2+ independent OVER drivers for conviction.
  - >
    The ML model pre-filtered this game as an OVER candidate, but my job
    is to validate, not rubber-stamp. One favorable signal is noise. Two
    are coincidence. Three are conviction. Default to PASS when unsure.

examples: []

confidence_modifiers:
  rpg_vs_line_above_plus_1: 0.10
  both_offenses_above_110pct: 0.10
  recent_and_season_rpg_agree_over: 0.10
  both_offenses_below_league: -0.15
  rpg_vs_line_below_zero: -0.10
```

### FatigueExploit
```yaml
name: FatigueExploit
version: 1
philosophy: |
  Tired arms give up runs. Markets anchor on season ERA and ignore that
  bullpens deteriorate in 3-5 day fatigue cycles. When bullpen FIP
  oscillators are POSITIVE on both sides — meaning recent performance is
  WORSE than season average — late-inning scoring spikes. Combine that
  with short starters who expose 4+ bullpen innings, and you get a
  structural OVER the market hasn't priced in. I exploit the gap between
  what season stats promise and what fatigued arms actually deliver.

principles:
  - >
    Bullpen FIP oscillator POSITIVE on both sides is the primary fatigue
    signal. 7-game FIP > season FIP means both relief corps are trending
    worse. This is the #1 feature in the ML model (38% importance) and
    it's symmetric: negative = UNDER, positive = OVER.
  - >
    Bullpen workload in last 3 days above 10 combined IP means tired
    arms. High-leverage relievers lose velocity after 3 consecutive days
    of work, and that shows up as elevated WHIP and FIP. Fresh workload
    (<5 IP) is an anti-signal for OVER.
  - >
    Short starters (combined IP/start below 10.0) expose 5+ bullpen
    innings per game. Even a good bullpen breaks when it has to cover
    4+ innings. This is structural OVER exposure the market underweights.
  - >
    Combined starter FIP above 8.5 means baseline pitching is mediocre
    on both sides. Add bullpen fatigue on top and late-inning runs become
    almost certain. When BOTH starters are below-average, the total
    ceiling rises significantly.
  - >
    Low combined K/BB ratio (below 3.5 for starters) means free
    baserunners. Walks lead to damage — runners in scoring position with
    nobody out. When starters can't command pitches, every inning becomes
    a scoring opportunity.
  - >
    The most dangerous OVER setup: one short-outing starter (5 IP or
    fewer average) + that team's bullpen is fatigued + the opposing
    lineup is above league average. This trifecta overwhelms the relief
    corps and pushes runs in innings 6-9.

anti_patterns:
  - >
    Bullpen fatigue alone doesn't cause OVER when one starter is dominant.
    An elite starter (FIP < 3.0, 6+ IP average) absorbs innings, leaving
    only 2-3 bullpen innings — not enough exposure for fatigue to matter.
  - >
    When bullpen oscillator is NEGATIVE (freshening) on both sides, my
    entire thesis is invalid. Fresh bullpens = late-inning runs are
    suppressed regardless of other factors. Don't fight the data.
  - >
    Low combined RPG (below line by 1+ run) means these offenses don't
    score. Fatigue creates opportunities but cold offenses don't capitalize.
    Tired bullpen + cold offense = still UNDER.
  - >
    The ML model pre-filtered this game as an OVER candidate, but my job
    is to validate, not rubber-stamp. I need fatigue signals confirmed by
    at least one other factor (weak starters, hot offenses, high RAPG).
    Fatigue alone with 0-1 OVER indicators fired = PASS.

examples: []

confidence_modifiers:
  both_bullpens_deteriorating_oscillator: 0.10
  high_combined_workload_3d: 0.10
  short_starters_plus_tired_pen: 0.05
  both_bullpens_fresh_oscillator: -0.15
  combined_ip_per_start_above_12: -0.10
```

### OU Analyst
```yaml
name: OU_Analyst
version: 1
philosophy: |
  I predict game scoring totals through pitching matchups and offensive environments.
  I think in innings: how many runs per inning can each side generate against the
  opposing starter, and when does the bullpen take over? I don't care about who wins —
  only about how many total runs will be scored. I know that MLB averages ~8.5-9.0
  total runs per game, but the distribution is wide. I'm calibrated: a 7.0 line and
  a 9.5 line require completely different analytical frames. I resist anchoring to
  the posted O/U line and form my own estimate from the fundamentals.

principles:
  - >
    Starting pitching quality sets the scoring ceiling for the first 5-6 innings.
    Two quality starters (FIP < 3.5) compress the total; one bad starter (FIP > 5.0)
    can blow it open by himself. I always evaluate BOTH starters, not just the
    better one.
  - >
    The "quality floor" — the WORST starter on the mound — matters more for
    totals than the best. A 2.5 FIP ace vs a 5.5 FIP journeyman creates 4-5 runs
    from one side alone. For unders, BOTH pitchers must be competent.
  - >
    Combined RPG (season + last 10) vs the O/U line reveals whether the market
    is pricing above or below what these teams actually produce. When combined
    RPG is 1+ runs below the line, the market is pricing in more scoring than
    reality suggests.
  - >
    Bullpen state determines the 7th-9th inning scoring. Fresh bullpens (low
    recent workload) and strong FIP keep games tight. Fatigued bullpens with
    deteriorating FIP oscillators leak runs late and push totals over.
  - >
    Early-season games (April) have more volatile totals because pitchers aren't
    fully stretched out. Starters exit earlier, exposing more bullpen innings.
    I widen my prediction interval in April.
  - >
    Offense vs league average provides better context than raw RPG. Two teams
    at 90% of league scoring create a suppressed environment regardless of what
    the O/U line says. Two teams at 115%+ create volatility.

anti_patterns: []

examples: []

confidence_modifiers:
  april_uncertainty: -0.10
  both_pitchers_under_5_starts: -0.10
  both_starters_sub_3.5_fip: 0.05
  one_starter_above_5_fip: -0.05
```
