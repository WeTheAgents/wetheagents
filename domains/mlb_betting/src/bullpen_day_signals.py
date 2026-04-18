"""Research and scanner utilities for early bullpen-day signals."""

from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from data.fetch_2026.espn_api import fetch_scoreboard, parse_probable_pitchers
from data.fetch_2026.io_safety import append_audit, atomic_write_text, safe_write_parquet
from src.fangraphs_probables import normalize_pitcher_name

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / "data" / "raw" / "bullpen_signal"
RAW_ESPN_DIR = RAW_DIR / "espn"
PROCESSED_DIR = BASE_DIR / "data" / "processed" / "bullpen_signal"
STARTER_PRIORS_PATH = BASE_DIR / "data" / "reference" / "season_2026_starter_priors.csv"

ESPN_SNAPSHOT_PATH = PROCESSED_DIR / "espn_probable_snapshots.parquet"
ROLE_SNAPSHOT_PATH = PROCESSED_DIR / "pitcher_role_rows.parquet"
LIVE_SCANNER_PATH = PROCESSED_DIR / "live_bullpen_signal_scanner.parquet"
HISTORICAL_ROWS_PATH = PROCESSED_DIR / "espn_historical_signal_rows.parquet"
HISTORICAL_REPORT_PATH = PROCESSED_DIR / "espn_historical_signal_report.md"

PREGAME_DIR = BASE_DIR / "data" / "raw" / "odds_2026"
GAME_BRIDGE_PATH = BASE_DIR / "data" / "processed" / "pitchers_2026" / "game_id_bridge.parquet"
PITCHER_GAME_LOGS_PATH = BASE_DIR / "data" / "processed" / "pitchers_2026" / "pitcher_game_logs.parquet"
STARTER_GAME_LOGS_PATH = BASE_DIR / "data" / "processed" / "pitchers_2026" / "starter_game_logs.parquet"

ESPN_SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard"

ROLE_BUCKET_STARTER = "starter_like"
ROLE_BUCKET_RELIEVER = "reliever_like"
ROLE_BUCKET_UNKNOWN = "unknown"
ROLE_BUCKET_BLANK = "blank"

ROLE_SOURCE_STARTER_PRIOR = "starter_prior"
ROLE_SOURCE_METRIC_STARTER = "metric_starter"
ROLE_SOURCE_METRIC_RELIEVER = "metric_reliever"
ROLE_SOURCE_DEFAULT_NON_STARTER = "default_non_starter"

SIGNAL_LIKELY = "likely_bullpen_day"
SIGNAL_SUSPICIOUS = "suspicious_non_starter"
SIGNAL_NONE = "no_flag"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _as_utc(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=UTC)
    return ts.astimezone(UTC)


def _source_url_for_date(target_date: date) -> str:
    return f"{ESPN_SCOREBOARD_URL}?dates={target_date.strftime('%Y%m%d')}"


def _normalize_probable_name(value: str | None) -> tuple[str, str, bool]:
    raw = (value or "").strip()
    is_blank = raw == "" or raw.upper() == "TBD"
    return raw, normalize_pitcher_name(raw), is_blank


def _coerce_text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value)


def _persist_snapshot_rows(
    rows: pd.DataFrame,
    *,
    path: Path,
    generator: str,
    dedup_keys: list[str],
) -> Path | None:
    if rows.empty:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = pd.read_parquet(path) if path.exists() else pd.DataFrame()
    combined = pd.concat([existing, rows], ignore_index=True, sort=False)
    combined = combined.drop_duplicates(subset=dedup_keys, keep="last")
    safe_write_parquet(
        combined,
        path,
        generator=generator,
        date_col="target_date",
        backup=False,
        audit_action=f"save_{path.stem}",
    )
    return path


def load_season_starter_priors(
    *,
    starter_priors_path: Path = STARTER_PRIORS_PATH,
) -> pd.DataFrame:
    """Load curated 2026 starter priors keyed by (team, pitcher_name_norm)."""
    if not starter_priors_path.exists():
        return pd.DataFrame(
            columns=["team", "pitcher_name", "pitcher_name_norm", "source_tag", "note"]
        )

    priors = pd.read_csv(starter_priors_path).copy()
    if priors.empty:
        return priors

    priors["team"] = priors["team"].astype(str).str.strip().str.upper()
    priors["pitcher_name"] = priors["pitcher_name"].astype(str).str.strip()
    priors["pitcher_name_norm"] = priors["pitcher_name"].map(normalize_pitcher_name)
    priors["source_tag"] = priors.get("source_tag", "").fillna("").astype(str)
    priors["note"] = priors.get("note", "").fillna("").astype(str)
    priors = priors.loc[
        priors["team"].ne("") & priors["pitcher_name_norm"].ne(""),
        ["team", "pitcher_name", "pitcher_name_norm", "source_tag", "note"],
    ].drop_duplicates(subset=["team", "pitcher_name_norm"], keep="last")
    return priors.reset_index(drop=True)


def parse_espn_pregame_snapshot_text(
    text: str,
    *,
    captured_at: datetime,
    snapshot_id: str,
    source_url: str,
) -> pd.DataFrame:
    """Parse an ESPN pregame snapshot JSON blob into normalized rows."""
    captured_at = _as_utc(captured_at)
    raw_rows = json.loads(text)
    rows: list[dict[str, object]] = []
    target_date = _infer_target_date_from_snapshot(snapshot_id, raw_rows, captured_at)

    for row in raw_rows:
        probable_raw, probable_norm, is_blank = _normalize_probable_name(
            row.get("pitcher") or row.get("pitcher_name")
        )
        rows.append(
            {
                "captured_at_utc": captured_at,
                "target_date": pd.Timestamp(target_date),
                "event_id": str(row.get("event_id", "")),
                "team": str(row.get("team", "")),
                "home_away": str(row.get("home_away", "")),
                "source": "espn",
                "probable_name_raw": probable_raw,
                "probable_name_norm": probable_norm,
                "is_blank": is_blank,
                "source_url": source_url,
                "snapshot_id": snapshot_id,
            }
        )
    return pd.DataFrame(rows)


def _infer_target_date_from_snapshot(
    snapshot_id: str,
    raw_rows: list[dict],
    captured_at: datetime,
) -> date:
    """Infer the target date for a snapshot.

    Existing raw ESPN snapshots do not store an explicit target date, so we
    derive it from the filename when possible and fall back to the file mtime.
    """
    for token in snapshot_id.split("_"):
        if len(token) == 8 and token.isdigit():
            try:
                return datetime.strptime(token, "%Y%m%d").date()
            except ValueError:
                continue

    if raw_rows:
        # Current raw snapshot schemas are one-date only.
        return captured_at.date()
    return captured_at.date()


def fetch_and_save_espn_probables_snapshot(target_date: date) -> pd.DataFrame:
    """Fetch today's probable pitchers from ESPN and persist raw + parsed rows."""
    captured_at = _utc_now()
    scoreboard = fetch_scoreboard(target_date)
    parsed = parse_probable_pitchers(scoreboard, override_date=target_date)

    RAW_ESPN_DIR.mkdir(parents=True, exist_ok=True)
    stamp = captured_at.strftime("%Y%m%dT%H%M%SZ")
    snapshot_path = RAW_ESPN_DIR / f"espn_probables_{target_date.strftime('%Y%m%d')}_{stamp}.json"
    payload = [
        {
            "event_id": row.event_id,
            "team": row.team_abbr,
            "home_away": row.home_away,
            "pitcher_name": row.pitcher_name,
        }
        for row in parsed
    ]
    atomic_write_text(json.dumps(payload, indent=2, ensure_ascii=False), snapshot_path)
    append_audit(
        "espn_probables_capture",
        target_date=target_date,
        rows_total=len(payload),
        files_written=[snapshot_path.name],
    )

    rows = []
    for row in parsed:
        probable_raw, probable_norm, is_blank = _normalize_probable_name(row.pitcher_name)
        rows.append(
            {
                "captured_at_utc": captured_at,
                "target_date": pd.Timestamp(target_date),
                "event_id": row.event_id,
                "team": row.team_abbr,
                "home_away": row.home_away,
                "source": "espn",
                "probable_name_raw": probable_raw,
                "probable_name_norm": probable_norm,
                "is_blank": is_blank,
                "source_url": _source_url_for_date(target_date),
                "snapshot_id": snapshot_path.stem,
            }
        )

    df = pd.DataFrame(rows)
    _persist_snapshot_rows(
        df,
        path=ESPN_SNAPSHOT_PATH,
        generator="bullpen_day_signals.fetch_and_save_espn_probables_snapshot",
        dedup_keys=["snapshot_id", "event_id", "team", "source"],
    )
    return df


def load_historical_espn_probables_from_pregame_dir(
    *,
    pregame_dir: Path = PREGAME_DIR,
) -> pd.DataFrame:
    """Load all 2026 ESPN pregame snapshots from the existing odds capture dir."""
    frames: list[pd.DataFrame] = []
    for path in sorted(pregame_dir.glob("pregame_*.json")):
        captured_at = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("Failed to read ESPN pregame snapshot %s: %s", path.name, exc)
            continue
        frames.append(
            parse_espn_pregame_snapshot_text(
                text,
                captured_at=captured_at,
                snapshot_id=path.stem,
                source_url=_source_url_for_date(_infer_target_date_from_snapshot(path.stem, [], captured_at)),
            )
        )

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True, sort=False)


def select_latest_snapshot_rows(
    rows: pd.DataFrame,
    *,
    date_min: date | None = None,
    date_max: date | None = None,
    source: str | None = None,
) -> pd.DataFrame:
    """Pick the latest row per source/team/date/event within an optional window."""
    if rows.empty:
        return rows.copy()

    df = rows.copy()
    df["target_date"] = pd.to_datetime(df["target_date"])
    if source is not None:
        df = df[df["source"] == source].copy()
    if date_min is not None:
        df = df[df["target_date"].dt.date >= date_min].copy()
    if date_max is not None:
        df = df[df["target_date"].dt.date <= date_max].copy()
    if df.empty:
        return df

    group_cols = ["source", "target_date", "team"]
    if "event_id" in df.columns:
        group_cols.append("event_id")
    df = df.sort_values(["captured_at_utc", "snapshot_id"])
    return df.groupby(group_cols, as_index=False, sort=False).tail(1).reset_index(drop=True)


def classify_pitcher_role_bucket(
    *,
    starts_prior: float,
    recent_starts_30d: float,
    recent_relief_apps_14d: float,
    recent_relief_share_30d: float,
    ip_per_start_short: float,
) -> str:
    """Bucket a pitcher into starter-like / reliever-like / unknown."""
    starts_prior = float(starts_prior) if pd.notna(starts_prior) else np.nan
    recent_starts_30d = float(recent_starts_30d) if pd.notna(recent_starts_30d) else np.nan
    recent_relief_apps_14d = (
        float(recent_relief_apps_14d) if pd.notna(recent_relief_apps_14d) else np.nan
    )
    recent_relief_share_30d = (
        float(recent_relief_share_30d) if pd.notna(recent_relief_share_30d) else np.nan
    )
    ip_per_start_short = float(ip_per_start_short) if pd.notna(ip_per_start_short) else np.nan

    if (
        pd.notna(starts_prior)
        and starts_prior >= 5
        and pd.notna(recent_starts_30d)
        and recent_starts_30d >= 2
        and pd.notna(ip_per_start_short)
        and ip_per_start_short >= 4.0
    ):
        return ROLE_BUCKET_STARTER

    if (
        pd.notna(recent_starts_30d)
        and recent_starts_30d >= 2
        and pd.notna(ip_per_start_short)
        and ip_per_start_short >= 4.5
        and (
            pd.isna(recent_relief_share_30d)
            or recent_relief_share_30d <= 0.25
        )
    ):
        return ROLE_BUCKET_STARTER

    if (
        pd.notna(starts_prior)
        and starts_prior <= 1
        and (
            (pd.notna(recent_relief_apps_14d) and recent_relief_apps_14d >= 3)
            or (pd.notna(recent_relief_share_30d) and recent_relief_share_30d >= 0.6)
        )
    ):
        return ROLE_BUCKET_RELIEVER

    return ROLE_BUCKET_UNKNOWN


def _build_pitcher_reference(
    pitcher_game_logs: pd.DataFrame,
    starter_game_logs: pd.DataFrame,
) -> pd.DataFrame:
    frames = []
    for frame in (pitcher_game_logs, starter_game_logs):
        subset = frame[["pitcher_id", "pitcher_name", "date"]].copy()
        subset["pitcher_name_norm"] = subset["pitcher_name"].map(normalize_pitcher_name)
        frames.append(subset)
    merged = pd.concat(frames, ignore_index=True).dropna(subset=["pitcher_name_norm"])
    merged["date"] = pd.to_datetime(merged["date"])

    by_id = (
        merged.groupby(["pitcher_name_norm", "pitcher_id", "pitcher_name"], dropna=False)
        .agg(last_seen=("date", "max"), appearances=("date", "size"))
        .reset_index()
    )
    by_id = by_id.sort_values(
        ["pitcher_name_norm", "appearances", "last_seen", "pitcher_id"],
        ascending=[True, False, False, True],
    )
    best = by_id.groupby("pitcher_name_norm", as_index=False, sort=False).head(1).copy()
    counts = by_id.groupby("pitcher_name_norm")["pitcher_id"].nunique().rename("n_pitcher_ids")
    best = best.merge(counts, on="pitcher_name_norm", how="left")
    best["name_ambiguous"] = best["n_pitcher_ids"].fillna(0).astype(int) > 1
    return best[
        ["pitcher_name_norm", "pitcher_id", "pitcher_name", "name_ambiguous"]
    ].reset_index(drop=True)


def build_pitcher_role_rows(
    probables: pd.DataFrame,
    *,
    pitcher_game_logs_path: Path = PITCHER_GAME_LOGS_PATH,
    starter_game_logs_path: Path = STARTER_GAME_LOGS_PATH,
    starter_priors_path: Path = STARTER_PRIORS_PATH,
    persist: bool = True,
) -> pd.DataFrame:
    """Build role rows for unique (target_date, team, pitcher_name_norm) pairs."""
    if probables.empty:
        return pd.DataFrame()

    if not pitcher_game_logs_path.exists() or not starter_game_logs_path.exists():
        raise FileNotFoundError("Pitcher logs required for role classification are missing")

    pitcher_games = pd.read_parquet(pitcher_game_logs_path)
    starter_games = pd.read_parquet(starter_game_logs_path)
    pitcher_games["date"] = pd.to_datetime(pitcher_games["date"])
    starter_games["date"] = pd.to_datetime(starter_games["date"])
    starter_games["ip"] = starter_games["p_ipouts"].astype(float) / 3.0

    reference = _build_pitcher_reference(pitcher_games, starter_games)
    ref_lookup = reference.set_index("pitcher_name_norm").to_dict(orient="index")
    priors = load_season_starter_priors(starter_priors_path=starter_priors_path)
    prior_lookup = (
        priors.set_index(["team", "pitcher_name_norm"]).to_dict(orient="index")
        if not priors.empty
        else {}
    )

    source_probables = probables.copy()
    if "team" not in source_probables.columns:
        source_probables["team"] = ""

    unique_probables = (
        source_probables.loc[~source_probables["probable_name_norm"].fillna("").eq("")]
        [["target_date", "team", "probable_name_norm"]]
        .drop_duplicates()
        .copy()
    )
    unique_probables["target_date"] = pd.to_datetime(unique_probables["target_date"])
    unique_probables["team"] = unique_probables["team"].fillna("").astype(str).str.upper()

    rows: list[dict[str, object]] = []
    for _, probable in unique_probables.iterrows():
        target_ts = probable["target_date"]
        target_day = target_ts.date()
        team = probable["team"]
        name_norm = probable["probable_name_norm"]
        ref = ref_lookup.get(name_norm)
        prior = prior_lookup.get((team, name_norm))

        pitcher_id = ref["pitcher_id"] if ref else None
        display_name = ref["pitcher_name"] if ref else ""
        if not display_name and prior:
            display_name = prior["pitcher_name"]
        name_ambiguous = bool(ref["name_ambiguous"]) if ref else False

        starts_prior = np.nan
        recent_starts_30d = np.nan
        recent_relief_apps_14d = np.nan
        recent_relief_share_30d = np.nan
        ip_per_start_short = np.nan
        days_since_last_start = np.nan
        days_since_last_appearance = np.nan

        if pitcher_id is not None:
            starts = starter_games[
                (starter_games["pitcher_id"] == pitcher_id) & (starter_games["date"] < target_ts)
            ].sort_values("date")
            apps = pitcher_games[
                (pitcher_games["pitcher_id"] == pitcher_id) & (pitcher_games["date"] < target_ts)
            ].sort_values("date")

            starts_prior = float(len(starts))
            recent_starts = starts[starts["date"] >= (target_ts - pd.Timedelta(days=30))]
            recent_starts_30d = float(len(recent_starts))

            relief_14d = apps[
                (apps["p_seq"] > 1) & (apps["date"] >= (target_ts - pd.Timedelta(days=14)))
            ]
            recent_relief_apps_14d = float(len(relief_14d))

            recent_apps_30d = apps[apps["date"] >= (target_ts - pd.Timedelta(days=30))]
            relief_30d = recent_apps_30d[recent_apps_30d["p_seq"] > 1]
            if len(recent_apps_30d):
                recent_relief_share_30d = float(len(relief_30d) / len(recent_apps_30d))

            last_five_starts = starts.tail(5)
            if len(last_five_starts):
                ip_per_start_short = float(last_five_starts["ip"].mean())
                days_since_last_start = float((target_day - last_five_starts.iloc[-1]["date"].date()).days)

            if len(apps):
                days_since_last_appearance = float((target_day - apps.iloc[-1]["date"].date()).days)

        metric_role_bucket = classify_pitcher_role_bucket(
            starts_prior=starts_prior,
            recent_starts_30d=recent_starts_30d,
            recent_relief_apps_14d=recent_relief_apps_14d,
            recent_relief_share_30d=recent_relief_share_30d,
            ip_per_start_short=ip_per_start_short,
        )
        if prior is not None:
            role_bucket = ROLE_BUCKET_STARTER
            role_source = ROLE_SOURCE_STARTER_PRIOR
        elif metric_role_bucket == ROLE_BUCKET_STARTER:
            role_bucket = ROLE_BUCKET_STARTER
            role_source = ROLE_SOURCE_METRIC_STARTER
        elif metric_role_bucket == ROLE_BUCKET_RELIEVER:
            role_bucket = ROLE_BUCKET_RELIEVER
            role_source = ROLE_SOURCE_METRIC_RELIEVER
        else:
            role_bucket = ROLE_BUCKET_RELIEVER
            role_source = ROLE_SOURCE_DEFAULT_NON_STARTER

        rows.append(
            {
                "target_date": target_ts,
                "team": team,
                "pitcher_name_norm": name_norm,
                "pitcher_id": pitcher_id,
                "pitcher_name": display_name,
                "starts_prior": starts_prior,
                "recent_starts_30d": recent_starts_30d,
                "recent_relief_apps_14d": recent_relief_apps_14d,
                "recent_relief_share_30d": recent_relief_share_30d,
                "ip_per_start_short": ip_per_start_short,
                "days_since_last_start": days_since_last_start,
                "days_since_last_appearance": days_since_last_appearance,
                "role_bucket": role_bucket,
                "role_source": role_source,
                "starter_prior_source_tag": prior["source_tag"] if prior is not None else "",
                "name_ambiguous": name_ambiguous,
            }
        )

    out = pd.DataFrame(rows)
    if persist and not out.empty:
        _persist_snapshot_rows(
            out,
            path=ROLE_SNAPSHOT_PATH,
            generator="bullpen_day_signals.build_pitcher_role_rows",
            dedup_keys=["target_date", "team", "pitcher_name_norm"],
        )
    return out


def determine_source_state(
    *,
    fg_name_norm: str,
    espn_name_norm: str,
    fg_available: bool,
    espn_available: bool,
) -> str:
    fg_named = bool(fg_name_norm)
    espn_named = bool(espn_name_norm)
    if fg_available and not espn_available:
        return "fg_only_named" if fg_named else "fg_only_blank"
    if espn_available and not fg_available:
        return "espn_only_named" if espn_named else "espn_only_blank"
    if not fg_available and not espn_available:
        return "no_source"
    if fg_named and espn_named:
        return "both_named_same" if fg_name_norm == espn_name_norm else "both_named_different"
    if fg_named:
        return "fg_named_espn_blank"
    if espn_named:
        return "fg_blank_espn_named"
    return "both_blank"


def classify_signal_tier(
    *,
    source_state: str,
    fg_role_bucket: str,
    espn_role_bucket: str,
    fg_role_source: str,
    espn_role_source: str,
    fg_available: bool,
    espn_available: bool,
) -> tuple[str, str]:
    """Return (signal_tier, reason_codes_json)."""
    reasons = {source_state}

    if fg_role_bucket and fg_role_bucket != ROLE_BUCKET_BLANK:
        reasons.add(f"fg_{fg_role_bucket}")
    if espn_role_bucket and espn_role_bucket != ROLE_BUCKET_BLANK:
        reasons.add(f"espn_{espn_role_bucket}")
    if fg_role_source:
        reasons.add(f"fg_src_{fg_role_source}")
    if espn_role_source:
        reasons.add(f"espn_src_{espn_role_source}")
    if not fg_available:
        reasons.add("fg_unavailable")
    if not espn_available:
        reasons.add("espn_unavailable")

    any_reliever = (
        fg_role_bucket == ROLE_BUCKET_RELIEVER or espn_role_bucket == ROLE_BUCKET_RELIEVER
    )
    any_starter = fg_role_bucket == ROLE_BUCKET_STARTER or espn_role_bucket == ROLE_BUCKET_STARTER
    strong_reliever = (
        (fg_role_bucket == ROLE_BUCKET_RELIEVER and fg_role_source == ROLE_SOURCE_METRIC_RELIEVER)
        or (
            espn_role_bucket == ROLE_BUCKET_RELIEVER
            and espn_role_source == ROLE_SOURCE_METRIC_RELIEVER
        )
    )
    default_non_starter = (
        (fg_role_bucket == ROLE_BUCKET_RELIEVER and fg_role_source == ROLE_SOURCE_DEFAULT_NON_STARTER)
        or (
            espn_role_bucket == ROLE_BUCKET_RELIEVER
            and espn_role_source == ROLE_SOURCE_DEFAULT_NON_STARTER
        )
    )

    if any_reliever and not any_starter and strong_reliever:
        reasons.add("hard_reliever_signal")
        return SIGNAL_LIKELY, json.dumps(sorted(reasons))

    if source_state in ("both_named_same", "espn_only_named", "fg_only_named") and any_starter:
        return SIGNAL_NONE, json.dumps(sorted(reasons))

    suspicious = (
        source_state
        in (
            "both_named_different",
            "fg_named_espn_blank",
            "fg_blank_espn_named",
            "both_blank",
            "espn_only_blank",
            "fg_only_blank",
            "no_source",
        )
        or (fg_available and fg_role_bucket in (ROLE_BUCKET_UNKNOWN, ROLE_BUCKET_BLANK))
        or (espn_available and espn_role_bucket in (ROLE_BUCKET_UNKNOWN, ROLE_BUCKET_BLANK))
        or default_non_starter
        or strong_reliever
    )
    if suspicious:
        reasons.add("manual_review")
        return SIGNAL_SUSPICIOUS, json.dumps(sorted(reasons))

    return SIGNAL_NONE, json.dumps(sorted(reasons))


def load_game_label_frame(*, game_bridge_path: Path = GAME_BRIDGE_PATH) -> pd.DataFrame:
    """Load strict bullpen-day labels keyed by (date, home_team, away_team)."""
    if not game_bridge_path.exists():
        return pd.DataFrame()

    bridge = pd.read_parquet(game_bridge_path).copy()
    bridge["target_date"] = pd.to_datetime(bridge["date"])
    key_cols = ["target_date", "home_team", "away_team"]

    dup = bridge.duplicated(subset=key_cols, keep=False)
    if dup.any():
        amb = bridge.loc[dup, key_cols].drop_duplicates().copy()
        amb["home_strict_label"] = pd.NA
        amb["away_strict_label"] = pd.NA
        amb["label_ambiguous"] = True
        uniq = bridge.loc[~dup, key_cols + [
            "home_is_bullpen_no_starter",
            "away_is_bullpen_no_starter",
        ]].copy()
        uniq = uniq.rename(
            columns={
                "home_is_bullpen_no_starter": "home_strict_label",
                "away_is_bullpen_no_starter": "away_strict_label",
            }
        )
        uniq["label_ambiguous"] = False
        out = pd.concat([uniq, amb], ignore_index=True, sort=False)
    else:
        out = bridge[key_cols + ["home_is_bullpen_no_starter", "away_is_bullpen_no_starter"]].copy()
        out = out.rename(
            columns={
                "home_is_bullpen_no_starter": "home_strict_label",
                "away_is_bullpen_no_starter": "away_strict_label",
            }
        )
        out["label_ambiguous"] = False

    return out.drop_duplicates(subset=key_cols, keep="last").reset_index(drop=True)


def build_live_scanner_rows(
    espn_latest: pd.DataFrame,
    *,
    fangraphs_latest: pd.DataFrame | None = None,
    role_rows: pd.DataFrame | None = None,
    label_frame: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build side-level scanner rows for the latest today/tomorrow window."""
    if espn_latest.empty:
        return pd.DataFrame()

    fangraphs_latest = fangraphs_latest if fangraphs_latest is not None else pd.DataFrame()
    role_rows = role_rows if role_rows is not None else pd.DataFrame()
    label_frame = label_frame if label_frame is not None else pd.DataFrame()
    fangraphs_available = not fangraphs_latest.empty

    espn = espn_latest.copy()
    espn["target_date"] = pd.to_datetime(espn["target_date"])

    home = espn[espn["home_away"] == "home"].copy()
    away = espn[espn["home_away"] == "away"].copy()
    home = home.rename(
        columns={
            "team": "home_team",
            "probable_name_raw": "home_espn_name",
            "probable_name_norm": "home_espn_norm",
            "is_blank": "home_espn_blank",
        }
    )
    away = away.rename(
        columns={
            "team": "away_team",
            "probable_name_raw": "away_espn_name",
            "probable_name_norm": "away_espn_norm",
            "is_blank": "away_espn_blank",
        }
    )
    games = home[
        [
            "event_id",
            "target_date",
            "home_team",
            "home_espn_name",
            "home_espn_norm",
            "home_espn_blank",
        ]
    ].merge(
        away[
            [
                "event_id",
                "target_date",
                "away_team",
                "away_espn_name",
                "away_espn_norm",
                "away_espn_blank",
            ]
        ],
        on=["event_id", "target_date"],
        how="inner",
    )

    if not fangraphs_latest.empty:
        fg = fangraphs_latest.copy()
        fg["target_date"] = pd.to_datetime(fg["target_date"])
        fg_home = fg.rename(
            columns={
                "team": "home_team",
                "probable_name_raw": "home_fg_name",
                "probable_name_norm": "home_fg_norm",
                "is_blank": "home_fg_blank",
            }
        )
        fg_away = fg.rename(
            columns={
                "team": "away_team",
                "probable_name_raw": "away_fg_name",
                "probable_name_norm": "away_fg_norm",
                "is_blank": "away_fg_blank",
            }
        )
        games = games.merge(
            fg_home[["target_date", "home_team", "home_fg_name", "home_fg_norm", "home_fg_blank"]],
            on=["target_date", "home_team"],
            how="left",
        ).merge(
            fg_away[["target_date", "away_team", "away_fg_name", "away_fg_norm", "away_fg_blank"]],
            on=["target_date", "away_team"],
            how="left",
        )
    else:
        for col in [
            "home_fg_name",
            "home_fg_norm",
            "home_fg_blank",
            "away_fg_name",
            "away_fg_norm",
            "away_fg_blank",
        ]:
            games[col] = np.nan

    if not label_frame.empty:
        lf = label_frame.copy()
        lf["target_date"] = pd.to_datetime(lf["target_date"])
        games = games.merge(lf, on=["target_date", "home_team", "away_team"], how="left")
    else:
        games["home_strict_label"] = pd.NA
        games["away_strict_label"] = pd.NA
        games["label_ambiguous"] = False

    role_lookup = {}
    role_lookup_by_name = {}
    if not role_rows.empty:
        rr = role_rows.copy()
        rr["target_date"] = pd.to_datetime(rr["target_date"])
        if "team" in rr.columns:
            role_lookup = rr.set_index(["target_date", "team", "pitcher_name_norm"]).to_dict(
                orient="index"
            )
        role_lookup_by_name = rr.set_index(["target_date", "pitcher_name_norm"]).to_dict(orient="index")

    side_rows: list[dict[str, object]] = []
    for _, game in games.iterrows():
        for side in ("home", "away"):
            opp = "away" if side == "home" else "home"
            team = game[f"{side}_team"]
            opponent = game[f"{opp}_team"]
            espn_name = _coerce_text(game.get(f"{side}_espn_name"))
            espn_norm = _coerce_text(game.get(f"{side}_espn_norm"))
            fg_name = _coerce_text(game.get(f"{side}_fg_name"))
            fg_norm = _coerce_text(game.get(f"{side}_fg_norm"))

            espn_role = ROLE_BUCKET_BLANK if not espn_norm else ROLE_BUCKET_UNKNOWN
            fg_role = ROLE_BUCKET_BLANK if not fg_norm else ROLE_BUCKET_UNKNOWN
            espn_role_source = ""
            fg_role_source = ""

            if espn_norm:
                role_info = role_lookup.get((game["target_date"], team, espn_norm)) or role_lookup_by_name.get(
                    (game["target_date"], espn_norm)
                )
                if role_info is not None:
                    espn_role = role_info["role_bucket"]
                    espn_role_source = role_info.get("role_source", "")
            if fg_norm:
                role_info = role_lookup.get((game["target_date"], team, fg_norm)) or role_lookup_by_name.get(
                    (game["target_date"], fg_norm)
                )
                if role_info is not None:
                    fg_role = role_info["role_bucket"]
                    fg_role_source = role_info.get("role_source", "")

            source_state = determine_source_state(
                fg_name_norm=fg_norm,
                espn_name_norm=espn_norm,
                fg_available=fangraphs_available,
                espn_available=True,
            )
            signal_tier, reason_codes = classify_signal_tier(
                source_state=source_state,
                fg_role_bucket=fg_role,
                espn_role_bucket=espn_role,
                fg_role_source=fg_role_source,
                espn_role_source=espn_role_source,
                fg_available=fangraphs_available,
                espn_available=True,
            )

            side_rows.append(
                {
                    "target_date": game["target_date"],
                    "event_id": game["event_id"],
                    "bullpen_team": team,
                    "opponent_team": opponent,
                    "side_to_bet": opp,
                    "source_state": source_state,
                    "fg_name": fg_name,
                    "espn_name": espn_name,
                    "fg_role_bucket": fg_role,
                    "espn_role_bucket": espn_role,
                    "fg_role_source": fg_role_source,
                    "espn_role_source": espn_role_source,
                    "signal_tier": signal_tier,
                    "reason_codes": reason_codes,
                    "strict_label_if_known": game.get(f"{side}_strict_label"),
                }
            )

    return pd.DataFrame(side_rows)


def build_research_summaries(scanner_rows: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (by_signal_tier, by_source_state) summary frames."""
    if scanner_rows.empty:
        return pd.DataFrame(), pd.DataFrame()

    df = scanner_rows.copy()
    labeled = df[df["strict_label_if_known"].notna()].copy()
    if labeled.empty:
        return pd.DataFrame(), pd.DataFrame()

    labeled["strict_label_if_known"] = pd.Series(
        labeled["strict_label_if_known"],
        dtype="boolean",
    ).astype(int)
    total_positive = int(labeled["strict_label_if_known"].sum())

    def _summarize(group_col: str) -> pd.DataFrame:
        summary = (
            labeled.groupby(group_col, dropna=False)["strict_label_if_known"]
            .agg(n_rows="size", positives="sum")
            .reset_index()
        )
        summary["hit_rate"] = np.where(
            summary["n_rows"] > 0,
            summary["positives"] / summary["n_rows"],
            np.nan,
        )
        summary["recall_share"] = np.where(
            total_positive > 0,
            summary["positives"] / total_positive,
            np.nan,
        )
        return summary.sort_values("n_rows", ascending=False).reset_index(drop=True)

    return _summarize("signal_tier"), _summarize("source_state")


def render_research_report(
    scanner_rows: pd.DataFrame,
    *,
    title: str = "ESPN Historical Bullpen-Day Signal Report",
) -> str:
    """Render a compact Markdown report from labeled scanner rows."""
    by_signal, by_state = build_research_summaries(scanner_rows)
    labeled = scanner_rows[scanner_rows["strict_label_if_known"].notna()].copy()
    positives = (
        int(pd.Series(labeled["strict_label_if_known"], dtype="boolean").astype(int).sum())
        if not labeled.empty
        else 0
    )

    parts = [
        f"# {title}",
        "",
        f"- labeled_rows: {len(labeled)}",
        f"- strict_bullpen_day_positives: {positives}",
        "",
        "## By Signal Tier",
        "",
        "```text",
        by_signal.to_string(index=False) if not by_signal.empty else "No labeled rows.",
        "```",
        "",
        "## By Source State",
        "",
        "```text",
        by_state.to_string(index=False) if not by_state.empty else "No labeled rows.",
        "```",
    ]
    return "\n".join(parts)


def persist_scanner_and_report(
    live_scanner: pd.DataFrame,
    historical_scanner: pd.DataFrame,
) -> dict[str, Path | None]:
    """Persist scanner parquet and historical report artifacts."""
    out: dict[str, Path | None] = {"live_scanner": None, "historical_rows": None, "historical_report": None}

    if not live_scanner.empty:
        LIVE_SCANNER_PATH.parent.mkdir(parents=True, exist_ok=True)
        safe_write_parquet(
            live_scanner,
            LIVE_SCANNER_PATH,
            generator="bullpen_day_signals.persist_scanner_and_report",
            date_col="target_date",
            backup=False,
            audit_action="save_live_bullpen_signal_scanner",
        )
        out["live_scanner"] = LIVE_SCANNER_PATH

    if not historical_scanner.empty:
        safe_write_parquet(
            historical_scanner,
            HISTORICAL_ROWS_PATH,
            generator="bullpen_day_signals.persist_scanner_and_report",
            date_col="target_date",
            backup=False,
            audit_action="save_espn_historical_signal_rows",
        )
        out["historical_rows"] = HISTORICAL_ROWS_PATH

        report = render_research_report(historical_scanner)
        atomic_write_text(report, HISTORICAL_REPORT_PATH)
        append_audit(
            "save_espn_historical_signal_report",
            rows_total=len(historical_scanner),
            files_written=[HISTORICAL_REPORT_PATH.name],
        )
        out["historical_report"] = HISTORICAL_REPORT_PATH

    return out
