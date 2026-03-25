# Session 13 Handoff — LLM Expert Coinflip Zone + Full-Day Calibration

## What Was Done

### Parse Error Fixes (Part 1)
- `max_completion_tokens=512` added to all OpenAI calls (gpt-5.4 uses `max_completion_tokens`, not `max_tokens`)
- Retry logic (3 attempts) in both `LLMExpert.analyze()` and `LLMAnalyst.predict()` on parse errors
- Files: `src/llm_expert.py`

### Coinflip Zone Implementation (Part 2)
Full implementation of CF_pickem zone for games with near-even odds (spread <= 4%):

**`src/feature_card.py`** — symmetric card rendering:
- `_header_cf()`: "Zone: PICK'EM (spread=X%)"
- `_odds_section_cf()`: HOME/AWAY labels (no DOG/FAV)
- `_model_signal_cf()`: direction only — "model lean: HOU" (no strength, no edge value)
- `_team_strength_cf()`: neutral labels ("NYY higher" not "dog stronger")
- `_starting_pitchers_cf()`: neutral diff labels

**`src/llm_expert.py`** — CF-specific expert behavior:
- `_OUTPUT_SCHEMA_CF`: action=BET|PASS + side=home|away
- `_build_system_prompt_cf()`: "pick'em evaluator" framing, not "underdog betting"
- `_parse_response_cf()`: converts BET+side → BET_HOME or BET_AWAY

**`src/llm_duel.py`** — CF arbitration:
- `_arbitrate_cf()`: both agree → BET (1.0x), opposite sides → PASS, **one bet + one pass → PASS** (no LEAN on coinflips)
- `target_side` field on DuelResult
- Analyst scenario adjustment: same side → conf * 1.10, disagree → conf * 0.85

**`src/data_loader.py`** — added `odds_spread` and `is_coinflip` columns in `add_derived_odds()`

### Expansion Zone Fix (from session 12)
- STRONG_BET capped to BET (1.0x) in expansion zones
- Pitcher sample penalty increased: `pitcher_under_5_starts: -0.25` (was -0.15) in value_v1.yaml

## Calibration Results

### Batch 2 (expansion zone, session 12): 5/6 correct, +$160 P&L
Expansion zone fixes validated.

### CF Batch v1 (with model edge, with LEAN): 1/5 correct
- Problem: experts followed model edge blindly. 5/6 picked away because model said "model lean: AWAY (strong, edge=+0.167)"
- 4 LEANs (one BET + one PASS) — 3 of them wrong

### CF Batch v2 (no model edge, no LEAN): 6/6 PASS
- Too conservative. Without model edge, experts lost conviction. One always BETs, other always PASSes.
- No money lost, but no signal either.

### Applied Fixes After CF Calibration
- **Fix A**: No LEAN in CF zone (one bet + one pass → PASS). Consensus required.
- **Fix B (softened)**: Model signal shows direction only — `"model lean: HOU"` — no strength label, no edge value. Direction as a hint, not a crutch.

## Next Session: Full-Day Calibration

### Goal
Pick a real day from 2023-2024 with ~15 games. Apply a very broad initial filter (remove obvious junk — extreme favorites that deserve it, etc.). Should yield 8-10 games that are "formally interesting" across all zones (S3, RL, CF). Run all of them through the expert duel system.

### What This Tests
- Expert selectivity across all zones in a realistic daily volume
- How many games survive expert consensus from a 8-10 game slate
- Whether experts correctly PASS on games that lose and BET on games that win
- Full pipeline behavior: data → card → analyst → experts → arbiter → verdict

### Implementation Steps
1. **Find a good test day**: ~15 games, diverse matchups, at least 2-3 potential CF games, 3-4 expansion zone candidates. Ideally a day where we know the results and have variety (some big upsets, some chalk).
2. **Build broad pre-filter**: not extreme line AND not Colorado AND not September. Maybe also: both pitchers have starts, odds available. This should keep 8-12 of 15 games.
3. **Zone assignment**: for each game, determine zone — CF (spread <= 0.04), S3/RL expansion, or "core" (passes strict mechanical filters). Core games don't go to experts (already handled by rules engine).
4. **Run all games through DuelEngine** with appropriate cards per zone.
5. **Score against actuals** and analyze expert behavior.

### Key Design Questions
- Should we build a new `scripts/run_fullday_calibration.py` or extend the existing batch script?
- How to assign S3 vs RL zone for expansion games that don't pass the strict filter? (Currently manual in batch games)
- Do we want to also test the **analyst independently** — does the analyst predict the winner correctly more than 50% of the time?

## Files Modified This Session

| File | Changes |
|------|---------|
| `src/llm_expert.py` | max_completion_tokens, retry, CF schema/prompt/parser |
| `src/feature_card.py` | CF symmetric card builders, softened model signal |
| `src/llm_duel.py` | CF arbitration (no LEAN), target_side field |
| `src/data_loader.py` | odds_spread, is_coinflip columns |
| `scripts/run_6game_calibration.py` | CF batch, CF-aware report writer |
| `genomes/value_v1.yaml` | pitcher_under_5_starts: -0.25 |
| `knowledge/calibration_6game_report_bcf.md` | CF calibration report |
