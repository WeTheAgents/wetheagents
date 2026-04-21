# MLB Betting Moved

`mlb_betting` now lives in its own repository:

- [WeTheAgents/mlb_betting](https://github.com/WeTheAgents/mlb_betting)

Cutover date: `2026-04-21`.

This path is now only a redirect stub inside `wetheagents`.

Active development, live operations, CI, and operator state all moved to the
standalone repository. Use the new repo root for commands such as:

```bash
python scripts/mlb_daily_capture.py
python scripts/check_2026_pipeline.py --strict-freshness
python scripts/generate_picks_2026.py --date YYYY-MM-DD --dry-run --no-poly
```
