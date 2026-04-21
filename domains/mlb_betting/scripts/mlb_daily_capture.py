"""Strict canonical daily runner for MLB live data capture."""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parent
for _path in (SCRIPT_DIR, BASE_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from check_2026_pipeline import append_alert, run_checks
from data.fetch_2026.io_safety import atomic_write_text
from data.fetch_2026.mlb_boxscore import run_boxscore_fetch
from data.fetch_2026.mlb_lineups import run_lineup_fetch
from data.fetch_2026.orchestrator import RAW_2026_DIR, run_pitchers, run_postgame, run_pregame
from data.fetch_2026.savant_live import refresh_live_savant
from src.live_runtime_contracts import evaluate_live_runtime_contract, live_dataset_contracts, scoreboard_day_summary

logger = logging.getLogger(__name__)

ALERTS_PATH = RAW_2026_DIR / "pitcher_alerts.jsonl"
STATUS_PATH = BASE_DIR / "data" / "fetch_2026" / "capture_status_latest.json"


def _emit_toast(title: str, body: str) -> None:
    ps = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        f"[System.Windows.Forms.MessageBox]::Show('{body}', '{title}', "
        "'OK', 'Information') | Out-Null"
    )
    try:
        subprocess.run(
            ["powershell", "-WindowStyle", "Hidden", "-Command", ps],
            timeout=5,
            check=False,
        )
    except Exception:
        pass


def _now_iso() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_status(payload: dict[str, Any]) -> None:
    atomic_write_text(json.dumps(payload, indent=2, default=str), STATUS_PATH)


def _load_pitcher_snapshot(dt: date) -> dict[tuple[str, str], str]:
    path = RAW_2026_DIR / f"pitchers_{dt.strftime('%Y%m%d')}.json"
    if not path.exists():
        return {}
    rows = json.loads(path.read_text(encoding="utf-8"))
    return {(r["event_id"], r["team"]): (r.get("pitcher_name") or "") for r in rows}


def _diff_pitchers(
    before: dict[tuple[str, str], str],
    after: dict[tuple[str, str], str],
    dt: date,
) -> list[dict[str, Any]]:
    path = RAW_2026_DIR / f"pitchers_{dt.strftime('%Y%m%d')}.json"
    vh_map: dict[tuple[str, str], str] = {}
    if path.exists():
        rows = json.loads(path.read_text(encoding="utf-8"))
        for row in rows:
            vh = "H" if row.get("home_away") == "home" else "V"
            vh_map[(row["event_id"], row["team"])] = vh

    alerts = []
    for key in sorted(set(before) | set(after)):
        prev = before.get(key, "")
        curr = after.get(key, "")
        if prev == curr:
            continue
        if not prev and curr:
            kind = "named"
        elif prev and not curr:
            kind = "scratch"
        else:
            kind = "swap"
        alerts.append(
            {
                "captured_at": _now_iso(),
                "game_date": str(dt),
                "event_id": key[0],
                "team": key[1],
                "vh": vh_map.get(key, "?"),
                "prev_pitcher": prev,
                "new_pitcher": curr,
                "kind": kind,
            }
        )
    return alerts


def _log_alerts(alerts: list[dict[str, Any]]) -> None:
    if not alerts:
        return
    ALERTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with ALERTS_PATH.open("a", encoding="utf-8") as handle:
        for alert in alerts:
            handle.write(json.dumps(alert) + "\n")


def _phase_result(
    *,
    name: str,
    status: str,
    detail: str,
    critical: bool,
    rows: dict[str, int] | None = None,
    expected: dict[str, int] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "name": name,
        "status": status,
        "detail": detail,
        "critical": critical,
    }
    if rows:
        payload["rows"] = rows
    if expected:
        payload["expected"] = expected
    if extra:
        payload.update(extra)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Strict MLB daily capture")
    parser.add_argument("--date", default=None, help="Override 'today' (YYYY-MM-DD)")
    parser.add_argument("--skip-postgame", action="store_true")
    parser.add_argument("--skip-pregame", action="store_true")
    parser.add_argument("--skip-savant", action="store_true")
    parser.add_argument(
        "--allow-degraded-system",
        action="store_true",
        help="Continue despite contract failures for manual recovery only.",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    today = date.fromisoformat(args.date) if args.date else date.today()
    yesterday = today - timedelta(days=1)
    today_summary = scoreboard_day_summary(today)
    yesterday_summary = scoreboard_day_summary(yesterday)

    phase_results: dict[str, dict[str, Any]] = {}
    critical_failures: list[str] = []
    all_alerts: list[dict[str, Any]] = []

    if args.skip_postgame:
        phase_results["postgame"] = _phase_result(
            name="postgame",
            status="skipped",
            detail="skipped via --skip-postgame",
            critical=False,
        )
    else:
        expected_rows = int(yesterday_summary["final_games"]) * 2
        try:
            game_rows = run_postgame(yesterday)
            pitcher_rows = run_boxscore_fetch(yesterday)
            batter_rows = run_lineup_fetch(yesterday)
            ok = True
            detail = (
                f"game_rows={game_rows}, pitcher_rows={pitcher_rows}, batter_rows={batter_rows}"
            )
            if expected_rows > 0 and game_rows != expected_rows:
                ok = False
                detail += f" (expected game_rows={expected_rows})"
            if yesterday_summary["final_games"] > 0 and pitcher_rows == 0:
                ok = False
                detail += " (expected pitcher rows > 0)"
            if yesterday_summary["final_games"] > 0 and batter_rows == 0:
                ok = False
                detail += " (expected batter rows > 0)"
            phase_results["postgame"] = _phase_result(
                name="postgame",
                status="ok" if ok else "failed",
                detail=detail,
                critical=yesterday_summary["final_games"] > 0,
                rows={
                    "game_rows": int(game_rows),
                    "pitcher_rows": int(pitcher_rows),
                    "batter_rows": int(batter_rows),
                },
                expected={"final_games": int(yesterday_summary["final_games"]), "team_rows": expected_rows},
            )
            if not ok and yesterday_summary["final_games"] > 0:
                critical_failures.append("postgame")
        except Exception as exc:  # noqa: BLE001
            phase_results["postgame"] = _phase_result(
                name="postgame",
                status="failed",
                detail=str(exc),
                critical=yesterday_summary["final_games"] > 0,
                expected={"final_games": int(yesterday_summary["final_games"]), "team_rows": expected_rows},
            )
            if yesterday_summary["final_games"] > 0:
                critical_failures.append("postgame")

    if args.skip_pregame:
        phase_results["pregame"] = _phase_result(
            name="pregame",
            status="skipped",
            detail="skipped via --skip-pregame",
            critical=False,
        )
        phase_results["pitchers"] = _phase_result(
            name="pitchers",
            status="skipped",
            detail="skipped via --skip-pregame",
            critical=False,
        )
    else:
        expected_rows = int(today_summary["scheduled_games"]) * 2
        try:
            odds_rows = run_pregame(today)
            ok = not (today_summary["scheduled_games"] > 0 and odds_rows != expected_rows)
            detail = f"odds_rows={odds_rows}"
            if not ok:
                detail += f" (expected={expected_rows})"
            phase_results["pregame"] = _phase_result(
                name="pregame",
                status="ok" if ok else "failed",
                detail=detail,
                critical=today_summary["scheduled_games"] > 0,
                rows={"odds_rows": int(odds_rows)},
                expected={"scheduled_games": int(today_summary["scheduled_games"]), "team_rows": expected_rows},
            )
            if not ok and today_summary["scheduled_games"] > 0:
                critical_failures.append("pregame")
        except Exception as exc:  # noqa: BLE001
            phase_results["pregame"] = _phase_result(
                name="pregame",
                status="failed",
                detail=str(exc),
                critical=today_summary["scheduled_games"] > 0,
                expected={"scheduled_games": int(today_summary["scheduled_games"]), "team_rows": expected_rows},
            )
            if today_summary["scheduled_games"] > 0:
                critical_failures.append("pregame")

        try:
            before = _load_pitcher_snapshot(today)
            pitcher_rows = run_pitchers(today)
            after = _load_pitcher_snapshot(today)
            alerts = _diff_pitchers(before, after, today)
            _log_alerts(alerts)
            all_alerts.extend(alerts)
            ok = not (today_summary["scheduled_games"] > 0 and pitcher_rows != expected_rows)
            detail = f"pitcher_rows={pitcher_rows}, changes={len(alerts)}"
            if not ok:
                detail += f" (expected={expected_rows})"
            phase_results["pitchers"] = _phase_result(
                name="pitchers",
                status="ok" if ok else "failed",
                detail=detail,
                critical=today_summary["scheduled_games"] > 0,
                rows={"pitcher_rows": int(pitcher_rows), "changes": int(len(alerts))},
                expected={"scheduled_games": int(today_summary["scheduled_games"]), "team_rows": expected_rows},
            )
            if not ok and today_summary["scheduled_games"] > 0:
                critical_failures.append("pitchers")
        except Exception as exc:  # noqa: BLE001
            phase_results["pitchers"] = _phase_result(
                name="pitchers",
                status="failed",
                detail=str(exc),
                critical=today_summary["scheduled_games"] > 0,
                expected={"scheduled_games": int(today_summary["scheduled_games"]), "team_rows": expected_rows},
            )
            if today_summary["scheduled_games"] > 0:
                critical_failures.append("pitchers")

    if args.skip_savant:
        phase_results["savant"] = _phase_result(
            name="savant",
            status="skipped",
            detail="skipped via --skip-savant",
            critical=False,
        )
    elif yesterday_summary["final_games"] == 0:
        phase_results["savant"] = _phase_result(
            name="savant",
            status="skipped",
            detail="no completed games yesterday",
            critical=False,
        )
    else:
        try:
            info = refresh_live_savant(yesterday)
            phase_results["savant"] = _phase_result(
                name="savant",
                status="ok",
                detail=(
                    f"pitcher_max={info['pitcher_max_date']}, "
                    f"bullpen_max={info['bullpen_max_date']}"
                ),
                critical=True,
                rows={
                    "pitcher_rows": int(info["pitcher_rows"]),
                    "bullpen_rows": int(info["bullpen_rows"]),
                },
                expected={"expected_date": yesterday.isoformat()},
            )
        except Exception as exc:  # noqa: BLE001
            phase_results["savant"] = _phase_result(
                name="savant",
                status="failed",
                detail=str(exc),
                critical=True,
                expected={"expected_date": yesterday.isoformat()},
            )
            critical_failures.append("savant")

    health_checks = run_checks(today, strict_freshness=True)
    health_failures = [check for check in health_checks if not check.ok]
    phase_results["pipeline_health"] = _phase_result(
        name="pipeline_health",
        status="ok" if not health_failures else "failed",
        detail="; ".join(check.detail for check in health_failures) if health_failures else "all checks passed",
        critical=True,
        extra={"failures": [{"name": check.name, "detail": check.detail} for check in health_failures]},
    )
    if health_failures:
        critical_failures.append("pipeline_health")
        append_alert(health_failures)

    runtime_contract = evaluate_live_runtime_contract(today)
    blocked_tiers = {
        tier: info
        for tier, info in runtime_contract["tier_results"].items()
        if info["status"] not in {"ready", "strict_but_empty"}
    }
    phase_results["runtime_contract"] = _phase_result(
        name="runtime_contract",
        status="ok" if not blocked_tiers else "failed",
        detail="all tiers ready" if not blocked_tiers else "; ".join(
            f"{tier}:{info['status']}" for tier, info in blocked_tiers.items()
        ),
        critical=True,
        extra={"tier_results": runtime_contract["tier_results"], "completeness": runtime_contract["completeness"]},
    )
    if blocked_tiers:
        critical_failures.append("runtime_contract")

    dataset_contracts = live_dataset_contracts(today)
    status_payload = {
        "ts": _now_iso(),
        "run_date": today.isoformat(),
        "target_postgame_date": yesterday.isoformat(),
        "strict_mode": not args.allow_degraded_system,
        "scoreboard": {"today": today_summary, "yesterday": yesterday_summary},
        "phases": phase_results,
        "file_contracts": dataset_contracts,
        "pitcher_alert_count": len(all_alerts),
        "verdict": "ok" if not critical_failures else "failed",
        "critical_failures": critical_failures,
    }
    _write_status(status_payload)

    if all_alerts:
        kinds = ", ".join(
            f"{kind}:{sum(1 for alert in all_alerts if alert['kind'] == kind)}"
            for kind in ("scratch", "named", "swap")
            if any(alert["kind"] == kind for alert in all_alerts)
        )
        _emit_toast("MLB Pitcher Alert", f"{len(all_alerts)} pitcher alert(s): {kinds}")

    for name, info in phase_results.items():
        print(f"{name}: {info['status']} — {info['detail']}")

    if critical_failures and not args.allow_degraded_system:
        print(f"FAILED: {critical_failures}")
        return 1

    if critical_failures:
        print(f"DEGRADED OVERRIDE: {critical_failures}")
    else:
        print("ALL OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
