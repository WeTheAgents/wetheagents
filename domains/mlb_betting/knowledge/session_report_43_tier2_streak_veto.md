# Session 43 -- Tier2 RL Streak Veto

**Date**: 2026-04-18
**Scope**: `tier2_fatigue_gap`, `standard` RL regime only, real recorded away `+1.5` odds only.
**Headline verdict**: **do_not_promote**.

## TL;DR

- Baseline `2015-2025`: N=1318, cover= **63.7%**, ROI= **+5.0%**.
- Recent `2022-2025`: N=373, cover= **61.1%**, ROI= **+1.5%**.
- Single-side streak vetoes were small and unstable. The best historical lifts were generally under one percentage point of ROI delta.
- Best discovery combo veto was `dog W3+` with `fav L2+`/`L3+`, but both holdouts flipped the wrong way: the removed rows were profitable in `2024` and `2025`.

## Threshold Read

- `favorite W2+`: N=374, cover= 62.0%, ROI +3.2%.
- `favorite L3+`: N=154, cover= 61.7%, ROI -0.2%.
- `dog W3+`: N=178, cover= 62.4%, ROI +1.3%.
- `dog L2+`: N=377, cover= 62.3%, ROI +4.1%.

## Top Discovery Vetoes

- `veto_dog_hot_3plus__fav_cold_2plus` -> removed N=88, removed ROI -10.4%, kept ROI +6.0%, loss_filter_edge +2.61pp.
- `veto_dog_hot_3plus__fav_cold_3plus` -> removed N=45, removed ROI -22.1%, kept ROI +5.9%, loss_filter_edge +2.50pp.
- `veto_dog_hot_3plus` -> removed N=155, removed ROI -1.2%, kept ROI +5.7%, loss_filter_edge +1.68pp.
- `veto_fav_hot_2plus` -> removed N=310, removed ROI +2.8%, kept ROI +5.5%, loss_filter_edge +2.22pp.
- `veto_dog_cold_2plus` -> removed N=313, removed ROI +2.9%, kept ROI +5.5%, loss_filter_edge +2.56pp.

## Validation

- `veto_dog_hot_3plus__fav_cold_2plus`: `2024` removed N=7, removed ROI +33.6%; `2025` removed N=5, removed ROI +30.4%.
- `veto_dog_hot_3plus__fav_cold_3plus`: `2024` removed N=5, removed ROI +27.0%; `2025` removed N=4, removed ROI +20.5%.
- `veto_dog_hot_3plus`: `2024` removed N=14, removed ROI +35.8%; `2025` removed N=9, removed ROI -10.1%.
- `veto_fav_hot_2plus`: `2024` removed N=34, removed ROI -8.4%; `2025` removed N=30, removed ROI +20.0%.
- `veto_dog_cold_2plus`: `2024` removed N=35, removed ROI +7.9%; `2025` removed N=29, removed ROI +12.2%.

## Recommendation

- Leave `tier2_fatigue_gap` unchanged in production.
- Use streak only as descriptive context for chat/writeups, not as an automatic runline veto.
- If we revisit this lane, streak should be tested only as a secondary interaction with a fresher structural variable, not as a standalone basket trim.
