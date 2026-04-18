# Bullpen Day Chat Watchlist 2026

Operational memory for early-season bullpen-day research.

As of April 18, 2026, we do not have a strict production-grade bullpen-day model. The first pass should therefore be chat-first:

1. ask for a bullpen-day risk check in chat
2. review `today + tomorrow` probables
3. compare named pitchers against the 2026 starter prior list in `data/reference/season_2026_starter_priors.csv`
4. treat non-prior names, reliever-like names, blanks, or source disagreements as manual review candidates

Important:

- a plain `TBD` is not enough by itself
- a named pitcher who is in the season starter priors is not a bullpen-day flag by default
- this document is a watchlist, not a betting rule

## Priority Watchlist

### Red Watch

Teams whose rotation depth looked structurally stressed as of April 18, 2026.

- `TOR`
  - Toronto was described by MLB as a rotation that is "a shell of what it was designed to be"
  - relevant losses/issues: `Trey Yesavage`, `Jose Berrios`, `Shane Bieber`, `Cody Ponce`, plus elbow management around `Max Scherzer`
  - this is the clearest current rotation-shortage team

- `ATL`
  - Atlanta opened the season with three projected rotation members on the IL
  - `Spencer Strider` was only beginning rehab work in April 2026, with other depth also missing
  - not an automatic bullpen-day team, but a real depth-stress team

### Yellow Watch

Teams where the rotation was still viable, but depth already looked thin enough to matter for bullpen-day monitoring.

- `CHC`
  - rotation depth questions intensified after the `Cade Horton` injury in early April 2026

- `MIL`
  - not short on paper, but thin on healthy fallback options
  - `Quinn Priester` was sidelined into May 2026, so the margin for another starter loss was small

- `TBR`
  - more thin than broken
  - early-season reshuffling already forced some flexibility in the rotation mix

## False-Positive Guardrails

These teams should not be treated as shortage teams just because an unfamiliar or secondary starter appears.

- `BAL`
  - `Dean Kremer` should be treated as normal starter depth, not an automatic shortage tell

- `CIN`
  - Cincinnati opened with more starter options than slots
  - not a natural bullpen-day watch team unless new injuries hit

## Chat Workflow

Until a stricter model is promoted, bullpen-day risk should usually be investigated in chat using this order:

1. check whether the team is on the red or yellow watchlist
2. check whether the probable pitcher is inside `season_2026_starter_priors.csv`
3. check whether ESPN and Fangraphs agree on the probable
4. escalate only if at least one of these is true:
   - probable pitcher is not in starter priors
   - probable pitcher looks reliever-like from game logs
   - source is blank or `TBD`
   - ESPN and Fangraphs disagree

## Source Notes

This watchlist was assembled from April 2026 MLB coverage and should be revised if rotation health changes materially.

Primary references:

- [Opening Day lineups, rotations for every 2026 MLB team](https://www.mlb.com/news/projected-lineups-rotations-for-every-2026-mlb-team)
- [Teams that should or should not worry early in 2026](https://www.mlb.com/news/teams-that-should-or-should-not-worry-early-in-2026)
- [MLB teams dealing with key early injuries in 2026](https://www.mlb.com/news/mlb-teams-dealing-with-key-early-injuries-in-2026)
- [Spencer Strider's first rehab appearance, April 11, 2026](https://www.mlb.com/braves/news/spencer-strider-1st-rehab-appearance-2026)
- [Brewers 2026 regular season preview](https://www.mlb.com/news/brewers-2026-regular-season-preview)
