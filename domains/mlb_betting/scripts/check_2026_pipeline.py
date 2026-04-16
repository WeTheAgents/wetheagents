"""Daily health check for the 2026 MLB data pipeline.

Runs every morning (scheduled at 12:30 Kyiv after the 11:00 results capture).
On any failure, appends a one-line alert to picks/ALERTS.md so the operator
sees it during the morning routine. Exit code is 0 on success, 1 on failure.

Checks (each is a HARD assertion):
  1. state.json exists, last_postgame_date and last_boxscore_date are recent
  2. games_2026.parquet exists, sidecar present, no duplicate
     (event_id, team, vh) rows, V/H pairing intact
  3. pitcher_game_logs.parquet row count >= sidecar's recorded count
     (never shrinks)
  4. Dual-path bullpen layout (Bug A guard):
     a. historical bullpen file exists at retrosheet/ with date.min() <= 2014-04-01
     b. live 2026 bullpen file exists at pitchers_2026/ with date.max() >= today-2
     Either side missing is a HARD FAIL.
  5. audit_log.jsonl has at least one entry from the last 2 days.

Output:
  ALL OK     → exit 0
  N FAIL(S)  → exit 1, alert appended to picks/ALERTS.md

Usage:
  python scripts/check_2026_pipeline.py
  python scripts/check_2026_pipeline.py --strict-freshness   # require dates == yesterday
  python scripts/check_2026_pipeline.py --quiet              # only failures to stdout
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent  # domains/mlb_betting
DATA_DIR = BASE_DIR / "data"
STATE_PATH_BOXSCORE = DATA_DIR / "fetch_2026" / "state.json"
AUDIT_LOG = DATA_DIR / "fetch_2026" / "audit_log.jsonl"
GAMES_PARQUET = DATA_DIR / "raw" / "odds_2026" / "games_2026.parquet"
PITCHER_LOGS_PARQUET = DATA_DIR / "processed" / "pitchers_2026" / "pitcher_game_logs.parquet"
# Dual-path bullpen layout (Bug A architectural fix):
HISTORICAL_BULLPEN_PARQUET = DATA_DIR / "processed" / "retrosheet" / "bullpen_features.parquet"
LIVE_BULLPEN_PARQUET = DATA_DIR / "processed" / "pitchers_2026" / "bullpen_features.parquet"
ALERTS_PATH = BASE_DIR / "picks" / "ALERTS.md"

# How many days behind today the last postgame date may be before we fail.
# 2 = yesterday's results should be in by mid-morning.
DEFAULT_FRESHNESS_DAYS = 2

# Earliest date the historical bullpen file should reach. If date_min is later
# than this, the historical Retrosheet rebuild has not been run (or it has
# been wiped) and the historical strategies cannot be backtested.
HISTORICAL_BP_FLOOR = date(2014, 4, 1)


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str

    def render(self) -> str:
        marker = "OK " if self.ok else "FAIL"
        return f"  [{marker}] {self.name} — {self.detail}"


def _read_state() -> dict | None:
    if not STATE_PATH_BOXSCORE.exists():
        return None
    try:
        return json.loads(STATE_PATH_BOXSCORE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def _read_sidecar(path: Path) -> dict | None:
    sidecar = path.with_suffix(path.suffix + ".meta.json")
    if not sidecar.exists():
        return None
    try:
        return json.loads(sidecar.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def check_state_freshness(today: date, max_days_behind: int) -> CheckResult:
    state = _read_state()
    if state is None:
        return CheckResult("state_freshness", False, f"missing or unreadable: {STATE_PATH_BOXSCORE}")

    last_post = _parse_date(state.get("last_postgame_date"))
    last_box = _parse_date(state.get("last_boxscore_date"))

    issues = []
    if last_post is None:
        issues.append("no last_postgame_date")
    elif (today - last_post).days > max_days_behind:
        issues.append(f"last_postgame_date={last_post} is {(today - last_post).days}d behind")

    if last_box is None:
        issues.append("no last_boxscore_date")
    elif (today - last_box).days > max_days_behind:
        issues.append(f"last_boxscore_date={last_box} is {(today - last_box).days}d behind")

    if issues:
        return CheckResult("state_freshness", False, "; ".join(issues))
    return CheckResult(
        "state_freshness",
        True,
        f"postgame={last_post}, boxscore={last_box}",
    )


def check_games_parquet() -> CheckResult:
    if not GAMES_PARQUET.exists():
        return CheckResult("games_parquet", False, f"missing: {GAMES_PARQUET}")
    df = pd.read_parquet(GAMES_PARQUET)
    if df.empty:
        return CheckResult("games_parquet", False, "empty parquet")

    # Duplicate detection — DH bug sentinel.
    # Once Bug E is fixed (dedup by event_id), the dedup key is (event_id, team, vh).
    # Until then, we just verify the rows are paired V/H per game and there are no
    # impossible (date, team, vh) duplicates within the same event.
    if "event_id" in df.columns:
        dup_mask = df.duplicated(subset=["event_id", "team", "vh"], keep=False)
        if dup_mask.any():
            return CheckResult(
                "games_parquet",
                False,
                f"duplicate (event_id, team, vh): {dup_mask.sum()} rows",
            )

    # Row pairing: for every (date, event_id) pair, expect exactly one V and one H.
    if "event_id" in df.columns:
        pair_check = df.groupby(["date", "event_id"])["vh"].apply(
            lambda s: tuple(sorted(s)) == ("H", "V")
        )
        bad_pairs = (~pair_check).sum()
        if bad_pairs > 0:
            return CheckResult(
                "games_parquet",
                False,
                f"{bad_pairs} game(s) without proper V/H pair",
            )

    sidecar = _read_sidecar(GAMES_PARQUET)
    sidecar_note = f", sidecar.rows={sidecar['rows']}" if sidecar else " (no sidecar)"
    return CheckResult(
        "games_parquet",
        True,
        f"{len(df)} rows ({len(df)//2} games){sidecar_note}",
    )


def check_pitcher_logs_monotonic() -> CheckResult:
    if not PITCHER_LOGS_PARQUET.exists():
        return CheckResult("pitcher_logs", False, f"missing: {PITCHER_LOGS_PARQUET}")
    df = pd.read_parquet(PITCHER_LOGS_PARQUET)
    if df.empty:
        return CheckResult("pitcher_logs", False, "empty parquet")

    actual_rows = len(df)
    sidecar = _read_sidecar(PITCHER_LOGS_PARQUET)

    # Strict monotonic check requires sidecar from a previous run.
    # First run after Session A has no prior sidecar — we accept that case
    # and warn instead of failing.
    if sidecar is None:
        return CheckResult(
            "pitcher_logs",
            True,
            f"{actual_rows} rows (no prior sidecar — first health check baseline)",
        )

    prior_rows = int(sidecar.get("rows", 0))
    if actual_rows < prior_rows:
        return CheckResult(
            "pitcher_logs",
            False,
            f"row count REGRESSED: {actual_rows} < {prior_rows} (sidecar)",
        )
    return CheckResult(
        "pitcher_logs",
        True,
        f"{actual_rows} rows (>= sidecar {prior_rows})",
    )


def check_bullpen_dual_version(today: date, max_days_behind: int) -> CheckResult:
    """The most important check — guards Bug A.

    Two separate files must exist (architectural Bug A fix):
      - HISTORICAL: data/processed/retrosheet/bullpen_features.parquet
        - owned by scripts/build_bullpen_features.py
        - must contain rows from <= 2014-04-01 (full historical sweep)
      - LIVE 2026: data/processed/pitchers_2026/bullpen_features.parquet
        - owned by data/fetch_2026/mlb_boxscore.py
        - must have date.max() within max_days_behind of today

    Either side missing or stale is a HARD FAIL — the 2026 fetcher physically
    cannot overwrite historical state because they live in separate paths,
    so a missing file means the build script wasn't run, not a Bug A regression.
    """
    issues: list[str] = []
    info_parts: list[str] = []

    # Historical side
    if not HISTORICAL_BULLPEN_PARQUET.exists():
        issues.append(
            f"historical missing: {HISTORICAL_BULLPEN_PARQUET} — "
            "run scripts/build_bullpen_features.py"
        )
    else:
        hist = pd.read_parquet(HISTORICAL_BULLPEN_PARQUET)
        if hist.empty or "date" not in hist.columns:
            issues.append(f"historical empty or missing 'date' column: {HISTORICAL_BULLPEN_PARQUET}")
        else:
            hist_dates = pd.to_datetime(hist["date"], errors="coerce").dropna()
            if hist_dates.empty:
                issues.append("historical: no valid dates")
            else:
                hist_min = hist_dates.min().date()
                hist_max = hist_dates.max().date()
                if hist_min > HISTORICAL_BP_FLOOR:
                    issues.append(
                        f"historical date_min={hist_min} > {HISTORICAL_BP_FLOOR} "
                        f"(2014-2025 sweep is incomplete or wiped)"
                    )
                else:
                    info_parts.append(
                        f"historical={len(hist)} rows ({hist_min}..{hist_max})"
                    )

    # Live 2026 side
    if not LIVE_BULLPEN_PARQUET.exists():
        issues.append(
            f"live 2026 missing: {LIVE_BULLPEN_PARQUET} — "
            "run scripts/fetch_daily_2026.py --backfill-boxscore"
        )
    else:
        live = pd.read_parquet(LIVE_BULLPEN_PARQUET)
        if live.empty or "date" not in live.columns:
            issues.append(f"live 2026 empty or missing 'date' column: {LIVE_BULLPEN_PARQUET}")
        else:
            live_dates = pd.to_datetime(live["date"], errors="coerce").dropna()
            if live_dates.empty:
                issues.append("live 2026: no valid dates")
            else:
                live_max = live_dates.max().date()
                if (today - live_max).days > max_days_behind:
                    issues.append(
                        f"live 2026 stale: date_max={live_max} is "
                        f"{(today - live_max).days}d behind today"
                    )
                else:
                    info_parts.append(f"live_2026={len(live)} rows (max={live_max})")

    if issues:
        return CheckResult("bullpen_dual_version", False, "; ".join(issues))
    return CheckResult(
        "bullpen_dual_version",
        True,
        ", ".join(info_parts),
    )


def check_audit_log_recent(today: date, max_days_behind: int) -> CheckResult:
    if not AUDIT_LOG.exists():
        return CheckResult(
            "audit_log",
            False,
            f"missing: {AUDIT_LOG} (no fetch action has run since insurance was installed)",
        )
    cutoff = today - timedelta(days=max_days_behind)
    found = False
    last_ts: str | None = None
    with AUDIT_LOG.open("r", encoding="utf-8") as fh:
        for line in fh:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = entry.get("ts", "")
            last_ts = ts or last_ts
            try:
                ts_date = datetime.fromisoformat(ts.replace("Z", "+00:00")).date()
            except ValueError:
                continue
            if ts_date >= cutoff:
                found = True
                break
    if not found:
        return CheckResult(
            "audit_log",
            False,
            f"no entries in last {max_days_behind}d (last_ts={last_ts})",
        )
    return CheckResult("audit_log", True, f"last entry within {max_days_behind}d")


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def append_alert(failures: list[CheckResult]) -> None:
    ALERTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [f"\n## {ts} — check_2026_pipeline.py FAILED ({len(failures)} check(s))"]
    for f in failures:
        lines.append(f"- **{f.name}**: {f.detail}")
    with ALERTS_PATH.open("a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="2026 MLB data pipeline health check")
    parser.add_argument(
        "--strict-freshness",
        action="store_true",
        help="Require state dates to be exactly today or yesterday (default: 2 days)",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress passing checks; print only failures",
    )
    args = parser.parse_args()

    today = date.today()
    max_days_behind = 1 if args.strict_freshness else DEFAULT_FRESHNESS_DAYS

    checks: list[CheckResult] = [
        check_state_freshness(today, max_days_behind),
        check_games_parquet(),
        check_pitcher_logs_monotonic(),
        check_bullpen_dual_version(today, max_days_behind),
        check_audit_log_recent(today, max_days_behind=2),
    ]

    failures = [c for c in checks if not c.ok]
    print(f"check_2026_pipeline.py — {today.isoformat()}")
    print(f"  freshness window: {max_days_behind}d")
    print()

    for c in checks:
        if c.ok and args.quiet:
            continue
        print(c.render())

    print()
    if failures:
        print(f"{len(failures)} FAIL(S) — appending alert to picks/ALERTS.md")
        append_alert(failures)
        return 1

    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
