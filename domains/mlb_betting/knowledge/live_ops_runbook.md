# Live Ops Runbook

This runbook assumes `mlb_betting` is the repo root. It does not depend on a
surrounding monorepo.

Local-only runtime files:

- `.env`
- `data/fetch_2026/state.json`
- `data/fetch_2026/pitcher_cache.json`

If `state.json` or `pitcher_cache.json` are missing, the repo seeds them from
`data/fetch_2026/*.example.json` on first use.

## Canonical Scheduled Command

```bash
python scripts/mlb_daily_capture.py
```

This is the only scheduled entrypoint. It is strict by default and writes:
- `data/fetch_2026/capture_status_latest.json`
- `picks/ALERTS.md`
- `picks/ALERTS.latest.json`

## Manual Recovery

Today's live inputs:

```bash
python scripts/fetch_daily_2026.py --phase pregame --date YYYY-MM-DD
python scripts/fetch_daily_2026.py --phase pitchers --date YYYY-MM-DD
```

Yesterday's completed-game rebuild:

```bash
python scripts/fetch_daily_2026.py --phase postgame-full --date YYYY-MM-DD
python scripts/fetch_daily_2026.py --phase savant --date YYYY-MM-DD
```

Savant stale / missed-date repair:

```bash
python scripts/fetch_daily_2026.py --backfill-savant YYYY-MM-DD YYYY-MM-DD
```

## Verification

Health check:

```bash
python scripts/check_2026_pipeline.py --strict-freshness
```

Runtime contract smoke:

```bash
python scripts/check_live_runtime_contract.py --date YYYY-MM-DD
```

Pick generation:

```bash
python scripts/generate_picks_2026.py --date YYYY-MM-DD --dry-run --no-poly
```

## Failure Modes

### Savant stale

Symptoms:
- `savant_pitcher_games_freshness` or `savant_bullpen_features_freshness` fail
- `last_savant_data_date` lags the expected live date

Recovery:
```bash
python scripts/fetch_daily_2026.py --phase savant --date YYYY-MM-DD
python scripts/check_2026_pipeline.py --strict-freshness
```

### Strategy source / registry drift

Symptoms:
- `strategy_registry_contract` fails
- `generate_picks_2026.py` or `diagnose_2026_coverage.py` fails before evaluation

Recovery:
- Restore the missing source module in `src/strategies/`
- Re-register it in `src/strategies/catalog.py`
- Re-run:

```bash
python scripts/check_2026_pipeline.py --strict-freshness
python scripts/check_live_runtime_contract.py --date YYYY-MM-DD
```

### Live completeness failure

Symptoms:
- games disappear between overlay and enriched frame
- runtime smoke reports `blocked_missing_dependency`

Recovery:
- inspect `check_live_runtime_contract.py` output for the dropped matchup and reason
- re-run missing source capture:

```bash
python scripts/fetch_daily_2026.py --phase pregame --date YYYY-MM-DD
python scripts/fetch_daily_2026.py --phase pitchers --date YYYY-MM-DD
```

- if the game is still missing because of a blank probable pitcher, treat the slate as blocked until the source updates
