"""Shared live runtime contracts for generator, health checks, and daily capture."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from data.fetch_2026.runtime_files import state_path
from src.live_runtime_data import build_live_enriched
from src.strategies.catalog import (
    ACTIVE_STRATEGIES,
    DEFAULT_PRODUCTION_TIERS,
    STRATEGY_CATALOG,
    get_strategy_spec,
    unknown_tiers,
)

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
LINEUP_FEATURES_PATH = DATA_DIR / "processed" / "lineups_2026" / "game_lineup_features.parquet"
SAVANT_PITCHER_GAMES_PATH = DATA_DIR / "processed" / "savant" / "pitcher_games_2026.parquet"
SAVANT_FEATURES_PATH = DATA_DIR / "processed" / "savant" / "savant_bullpen_features.parquet"
STARTER_ENTERING_PATH = DATA_DIR / "processed" / "pitchers_2026" / "starter_entering_features.parquet"
ID_BRIDGE_PATH = DATA_DIR / "processed" / "savant" / "id_bridge.parquet"


def _read_state() -> dict[str, Any]:
    current_state_path = state_path()
    if not current_state_path.exists():
        return {}
    try:
        return json.loads(current_state_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _read_max_date(path: Path, date_col: str) -> date | None:
    if not path.exists():
        return None
    df = pd.read_parquet(path, columns=[date_col])
    if df.empty or date_col not in df.columns:
        return None
    dates = pd.to_datetime(df[date_col], errors="coerce").dropna()
    if dates.empty:
        return None
    return dates.max().date()


def _dataset_contract(
    *,
    name: str,
    path: Path,
    date_col: str,
    expected_date: date,
) -> dict[str, Any]:
    actual_date = _read_max_date(path, date_col)
    return {
        "name": name,
        "path": str(path),
        "expected_date": expected_date.isoformat(),
        "actual_date": actual_date.isoformat() if actual_date else None,
        "ok": actual_date == expected_date,
    }


def scoreboard_day_summary(target: date) -> dict[str, Any]:
    from data.fetch_2026.espn_api import fetch_scoreboard  # noqa: PLC0415

    data = fetch_scoreboard(target)
    summary = {"target_date": target.isoformat(), "scheduled_games": 0, "final_games": 0}
    for event in data.get("events", []):
        competition = event.get("competitions", [{}])[0]
        status_name = competition.get("status", {}).get("type", {}).get("name", "")
        if status_name == "STATUS_SCHEDULED":
            summary["scheduled_games"] += 1
        elif status_name == "STATUS_FINAL":
            summary["final_games"] += 1
    return summary


def live_dataset_contracts(target: date) -> dict[str, dict[str, Any]]:
    expected_live = target - timedelta(days=1)
    return {
        "lineups_2026": _dataset_contract(
            name="lineups_2026",
            path=LINEUP_FEATURES_PATH,
            date_col="date",
            expected_date=expected_live,
        ),
        "starter_entering_2026": _dataset_contract(
            name="starter_entering_2026",
            path=STARTER_ENTERING_PATH,
            date_col="date",
            expected_date=expected_live,
        ),
        "savant_pitcher_games_2026": _dataset_contract(
            name="savant_pitcher_games_2026",
            path=SAVANT_PITCHER_GAMES_PATH,
            date_col="game_date",
            expected_date=expected_live,
        ),
        "savant_bullpen_features": _dataset_contract(
            name="savant_bullpen_features",
            path=SAVANT_FEATURES_PATH,
            date_col="game_date",
            expected_date=expected_live,
        ),
        "starter_id_bridge": {
            "name": "starter_id_bridge",
            "path": str(ID_BRIDGE_PATH),
            "expected_date": None,
            "actual_date": None,
            "ok": _bridge_ok(),
        },
    }


def _bridge_ok() -> bool:
    if not ID_BRIDGE_PATH.exists():
        return False
    bridge = pd.read_parquet(ID_BRIDGE_PATH, columns=["key_retro", "key_mlbam"])
    if bridge.empty:
        return False
    mapped = bridge.dropna(subset=["key_retro", "key_mlbam"])
    return not mapped.empty


def stale_source_labels(target: date) -> tuple[str, ...]:
    contracts = live_dataset_contracts(target)
    mapping = {
        "lineups_2026": "lineups",
        "starter_entering_2026": "starter_entering",
        "starter_id_bridge": "starter_id_bridge",
        "savant_pitcher_games_2026": "savant_pitcher_games",
        "savant_bullpen_features": "savant_features",
    }
    return tuple(mapping[name] for name, info in contracts.items() if not info["ok"])


def registry_contract_report(requested_tiers: list[str] | None = None) -> dict[str, Any]:
    tiers = requested_tiers or list(DEFAULT_PRODUCTION_TIERS)
    unknown = unknown_tiers(tiers)
    source_missing = []
    active_missing = []
    for tier in tiers:
        if tier in unknown:
            continue
        spec = get_strategy_spec(tier)
        if tier not in ACTIVE_STRATEGIES:
            active_missing.append(tier)
        if not spec.source_path.exists():
            source_missing.append(tier)
    return {
        "requested_tiers": tiers,
        "unknown_tiers": unknown,
        "active_missing": active_missing,
        "source_missing": source_missing,
        "ok": not (unknown or active_missing or source_missing),
    }


def _under_bundle_ok() -> bool:
    try:
        from src.under_live import load_under_live_bundle  # noqa: PLC0415

        load_under_live_bundle()
        return True
    except FileNotFoundError:
        return False


def evaluate_live_runtime_contract(
    target: date,
    *,
    requested_tiers: list[str] | None = None,
    frame_bundle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tiers = requested_tiers or list(DEFAULT_PRODUCTION_TIERS)
    registry = registry_contract_report(tiers)
    contracts = live_dataset_contracts(target)
    stale_sources = stale_source_labels(target)
    under_bundle_ok = _under_bundle_ok()
    state = _read_state()

    scoreboard_error = None
    try:
        scoreboard = scoreboard_day_summary(target)
    except Exception as exc:  # noqa: BLE001
        scoreboard = {"target_date": target.isoformat(), "scheduled_games": 0, "final_games": 0}
        scoreboard_error = str(exc)

    bundle = frame_bundle or build_live_enriched(target)
    completeness = bundle["completeness"]
    enriched = bundle["enriched"]
    day = bundle["day"]

    try:
        from src.live_strategy_audit import AUDIT_CONFIGS, evaluate_strategy_day  # noqa: PLC0415

        audit_import_error = None
    except ImportError as exc:
        AUDIT_CONFIGS = {}
        evaluate_strategy_day = None
        audit_import_error = str(exc)

    overlay_count = int(completeness["overlay_games"])
    scheduled_games = int(scoreboard["scheduled_games"])
    overlay_missing = scheduled_games > 0 and overlay_count == 0
    overlay_incomplete = scheduled_games > 0 and overlay_count != scheduled_games

    global_blockers = []
    if scoreboard_error:
        global_blockers.append(f"scoreboard_unavailable: {scoreboard_error}")
    if overlay_missing:
        global_blockers.append("missing_pregame_overlay")
    elif overlay_incomplete:
        global_blockers.append(
            f"incomplete_pregame_overlay: overlay_games={overlay_count}, scheduled_games={scheduled_games}"
        )
    if completeness["blocked"]:
        global_blockers.append("live_completeness_failed")
    non_savant_failures = [
        name
        for name, info in contracts.items()
        if name not in {"savant_pitcher_games_2026", "savant_bullpen_features"} and not info["ok"]
    ]
    if non_savant_failures:
        global_blockers.append(
            "stale_live_dependencies: " + ",".join(sorted(non_savant_failures))
        )

    results: dict[str, dict[str, Any]] = {}
    for tier in tiers:
        if tier in registry["unknown_tiers"] or tier in registry["source_missing"] or tier in registry["active_missing"]:
            results[tier] = {
                "tier": tier,
                "status": "blocked_missing_source",
                "detail": "tier missing from source registry or active strategy map",
                "pick_count": 0,
            }
            continue

        spec = STRATEGY_CATALOG[tier]
        if spec.requires_savant and (
            not contracts["savant_pitcher_games_2026"]["ok"]
            or not contracts["savant_bullpen_features"]["ok"]
        ):
            results[tier] = {
                "tier": tier,
                "status": "blocked_stale_data",
                "detail": "Savant live datasets failed freshness contract",
                "pick_count": 0,
            }
            continue
        if spec.requires_under_bundle and not under_bundle_ok:
            results[tier] = {
                "tier": tier,
                "status": "blocked_missing_dependency",
                "detail": "UNDER live bundle unavailable",
                "pick_count": 0,
            }
            continue
        if global_blockers:
            results[tier] = {
                "tier": tier,
                "status": "blocked_missing_dependency",
                "detail": "; ".join(global_blockers),
                "pick_count": 0,
            }
            continue
        if audit_import_error and tier in {"tier4_ml_depth_load", "tier5_ml_obp_recovery"}:
            results[tier] = {
                "tier": tier,
                "status": "blocked_missing_source",
                "detail": f"live_strategy_audit import failed: {audit_import_error}",
                "pick_count": 0,
            }
            continue

        audit_payload = None
        if tier in AUDIT_CONFIGS and evaluate_strategy_day is not None:
            audit_payload = evaluate_strategy_day(day, tier, stale_sources=stale_sources)
            if audit_payload["verdict"] == "source_blocked":
                results[tier] = {
                    "tier": tier,
                    "status": "blocked_missing_dependency",
                    "detail": audit_payload["verdict_detail"],
                    "pick_count": 0,
                }
                continue
            if audit_payload["verdict"] in {"warmup_sparse", "no_games"}:
                results[tier] = {
                    "tier": tier,
                    "status": "strict_but_empty",
                    "detail": audit_payload["verdict_detail"],
                    "pick_count": 0,
                    "audit": audit_payload,
                }
                continue

        try:
            picks = spec.find_picks(enriched, target)
        except FileNotFoundError as exc:
            results[tier] = {
                "tier": tier,
                "status": "blocked_missing_dependency",
                "detail": str(exc),
                "pick_count": 0,
            }
            continue
        except ImportError as exc:
            results[tier] = {
                "tier": tier,
                "status": "blocked_missing_source",
                "detail": str(exc),
                "pick_count": 0,
            }
            continue
        except Exception as exc:  # noqa: BLE001
            results[tier] = {
                "tier": tier,
                "status": "blocked_missing_dependency",
                "detail": str(exc),
                "pick_count": 0,
            }
            continue

        results[tier] = {
            "tier": tier,
            "status": "ready" if picks else "strict_but_empty",
            "detail": f"picks={len(picks)}",
            "pick_count": len(picks),
        }
        if audit_payload is not None:
            results[tier]["audit"] = audit_payload

    ok = registry["ok"] and all(
        row["status"] in {"ready", "strict_but_empty"}
        for row in results.values()
    )
    return {
        "target_date": target.isoformat(),
        "registry": registry,
        "contracts": contracts,
        "stale_sources": list(stale_sources),
        "scoreboard": scoreboard,
        "scoreboard_error": scoreboard_error,
        "state": {
            "last_pregame_date": state.get("last_pregame_date"),
            "last_pitchers_date": state.get("last_pitchers_date"),
            "last_postgame_date": state.get("last_postgame_date"),
            "last_boxscore_date": state.get("last_boxscore_date"),
            "last_lineup_date": state.get("last_lineup_date"),
            "last_savant_date": state.get("last_savant_date"),
            "last_savant_refresh_date": state.get("last_savant_refresh_date"),
            "last_savant_data_date": state.get("last_savant_data_date"),
        },
        "completeness": completeness,
        "tier_results": results,
        "ok": ok,
    }
