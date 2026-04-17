"""Batter rolling features from Retrosheet batting.csv + allplayers.csv + plays.csv.

Extracts per-batter entering-game rolling stats with vs-hand splits,
designed for NRFI prediction (top-of-order quality vs starter handedness).

Also computes 1st-inning BABIP from plays.csv for batters and pitchers.

Anti-leak: all features computed from data strictly BEFORE the current game.
"""

import logging
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

RETRO_DIR = Path(__file__).resolve().parent.parent / "retrosheets"
SHORT_WINDOW = 50   # PA for short rolling
LONG_WINDOW = 150   # PA for long rolling
MIN_PA = 30          # minimum PA before producing stats


def load_season_batting(year: int) -> pd.DataFrame | None:
    """Load batting.csv from Retrosheet zip for a given year."""
    zf_path = RETRO_DIR / f"{year}csvs.zip"
    if not zf_path.exists():
        logger.warning(f"Zip not found: {zf_path}")
        return None
    with zipfile.ZipFile(zf_path) as zf:
        fname = f"{year}batting.csv"
        if fname not in zf.namelist():
            logger.warning(f"{fname} not in {zf_path}")
            return None
        with zf.open(fname) as f:
            df = pd.read_csv(f)
    df["season"] = year
    return df


def load_season_players(year: int) -> pd.DataFrame | None:
    """Load allplayers.csv to get batter handedness."""
    zf_path = RETRO_DIR / f"{year}csvs.zip"
    if not zf_path.exists():
        return None
    with zipfile.ZipFile(zf_path) as zf:
        fname = f"{year}allplayers.csv"
        if fname not in zf.namelist():
            return None
        with zf.open(fname) as f:
            df = pd.read_csv(f)
    df["season"] = year
    return df


def load_season_pitching(year: int) -> pd.DataFrame | None:
    """Load pitching.csv to identify starters and their handedness."""
    zf_path = RETRO_DIR / f"{year}csvs.zip"
    if not zf_path.exists():
        return None
    with zipfile.ZipFile(zf_path) as zf:
        fname = f"{year}pitching.csv"
        if fname not in zf.namelist():
            return None
        with zf.open(fname) as f:
            df = pd.read_csv(f)
    df["season"] = year
    return df


def load_all_batting(
    years: list[int] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Load batting, players, and pitching for all available years.

    Returns (batting_df, players_df, starters_df).
    """
    if years is None:
        years = list(range(2010, 2020)) + [2021] + list(range(2022, 2026))

    bat_parts, player_parts, starter_parts = [], [], []

    for year in years:
        bat = load_season_batting(year)
        if bat is not None:
            bat_parts.append(bat)

        players = load_season_players(year)
        if players is not None:
            player_parts.append(players)

        pitch = load_season_pitching(year)
        if pitch is not None:
            # Starters: p_seq == 1
            starters = pitch[pitch["p_seq"] == 1][
                ["gid", "id", "team", "vishome", "season"]
            ].copy()
            starters = starters.rename(columns={"id": "starter_id"})
            starter_parts.append(starters)

    batting = pd.concat(bat_parts, ignore_index=True) if bat_parts else pd.DataFrame()
    players = pd.concat(player_parts, ignore_index=True) if player_parts else pd.DataFrame()
    starters = pd.concat(starter_parts, ignore_index=True) if starter_parts else pd.DataFrame()

    logger.info(
        f"Loaded batting: {len(batting)} rows, "
        f"players: {len(players)}, starters: {len(starters)}"
    )
    return batting, players, starters


def build_batter_game_logs(
    batting: pd.DataFrame,
    players: pd.DataFrame,
    starters: pd.DataFrame,
) -> pd.DataFrame:
    """Build per-batter per-game log with opposing starter hand.

    Returns DataFrame with one row per batter-game, including:
    - batter stats (PA, H, K, BB, HR, etc.)
    - batter handedness
    - opposing starter's throwing hand
    - lineup position
    """
    # Filter to actual lineup (b_lp not NaN, b_seq == 1 = starter)
    bat = batting[batting["b_lp"].notna()].copy()
    # Keep only first appearance per lineup spot (b_seq == 1)
    bat = bat[bat["b_seq"] == 1].copy()
    bat["b_lp"] = bat["b_lp"].astype(int)

    # Parse date
    bat["date"] = pd.to_datetime(bat["date"].astype(str), format="%Y%m%d")

    # Batter handedness from allplayers
    # Deduplicate: take first entry per (id, season)
    player_hand = players.drop_duplicates(subset=["id", "season"])[
        ["id", "season", "bat"]
    ].rename(columns={"bat": "bat_hand"})
    bat = bat.merge(player_hand, on=["id", "season"], how="left")

    # Opposing starter's throwing hand
    # For each game, determine who the opposing starter is:
    # - if batter is visitor (vishome='v'), opposing starter is home starter (vishome='h')
    # - and vice versa
    opp_starters = starters.copy()
    # Get pitcher handedness from allplayers
    pitcher_hand = players.drop_duplicates(subset=["id", "season"])[
        ["id", "season", "throw"]
    ].rename(columns={"id": "starter_id", "throw": "opp_starter_hand"})
    opp_starters = opp_starters.merge(pitcher_hand, on=["starter_id", "season"], how="left")

    # Merge: batter gets the starter from the OTHER side
    # visitor batter → home starter
    home_starters = opp_starters[opp_starters["vishome"] == "h"][
        ["gid", "starter_id", "opp_starter_hand"]
    ].rename(columns={"starter_id": "opp_starter_id"})
    away_starters = opp_starters[opp_starters["vishome"] == "v"][
        ["gid", "starter_id", "opp_starter_hand"]
    ].rename(columns={"starter_id": "opp_starter_id"})

    # Deduplicate (doubleheaders can cause dupes)
    home_starters = home_starters.drop_duplicates(subset=["gid"], keep="first")
    away_starters = away_starters.drop_duplicates(subset=["gid"], keep="first")

    # Visitor batters face home starter
    vis_bat = bat[bat["vishome"] == "v"].merge(home_starters, on="gid", how="left")
    # Home batters face away starter
    home_bat = bat[bat["vishome"] == "h"].merge(away_starters, on="gid", how="left")

    log = pd.concat([vis_bat, home_bat], ignore_index=True)
    log = log.sort_values(["id", "season", "date"]).reset_index(drop=True)

    logger.info(f"Batter game log: {len(log)} rows, {log['id'].nunique()} batters")
    return log


def compute_entering_features(log: pd.DataFrame) -> pd.DataFrame:
    """Compute entering-game rolling batter features.

    For each batter-game, computes stats from PRIOR games only (anti-leak).

    Returns DataFrame with rolling features per batter-game.
    """
    results = []

    for batter_id, grp in log.groupby("id"):
        grp = grp.sort_values("date").reset_index(drop=True)
        n = len(grp)
        if n < 2:
            continue

        # Cumulative arrays (for expanding window)
        pa = grp["b_pa"].values.astype(float)
        h = grp["b_h"].values.astype(float)
        k = grp["b_k"].values.astype(float)
        w = grp["b_w"].values.astype(float)
        hbp = grp["b_hbp"].values.astype(float)
        hr = grp["b_hr"].values.astype(float)
        on_base = h + w + hbp

        opp_hand = grp["opp_starter_hand"].values  # 'R', 'L', or NaN

        for i in range(1, n):
            # Entering-game: use games [0..i-1]
            start_short = max(0, i - SHORT_WINDOW)
            start_long = max(0, i - LONG_WINDOW)

            pa_short = pa[start_short:i].sum()
            pa_long = pa[start_long:i].sum()

            if pa_long < MIN_PA:
                continue

            h_short = h[start_short:i].sum()
            h_long = h[start_long:i].sum()
            k_short = k[start_short:i].sum()
            k_long = k[start_long:i].sum()
            ob_short = on_base[start_short:i].sum()
            ob_long = on_base[start_long:i].sum()
            hr_short = hr[start_short:i].sum()

            # vs-hand splits (only games where we know opp starter hand)
            # RHP
            rhp_mask = opp_hand[:i] == "R"
            rhp_pa = pa[:i][rhp_mask].sum()
            rhp_ob = on_base[:i][rhp_mask].sum()
            rhp_k = k[:i][rhp_mask].sum()
            # LHP
            lhp_mask = opp_hand[:i] == "L"
            lhp_pa = pa[:i][lhp_mask].sum()
            lhp_ob = on_base[:i][lhp_mask].sum()
            lhp_k = k[:i][lhp_mask].sum()

            row = {
                "batter_id": batter_id,
                "season": grp.iloc[i]["season"],
                "date": grp.iloc[i]["date"],
                "gid": grp.iloc[i]["gid"],
                "team": grp.iloc[i]["team"],
                "b_lp": grp.iloc[i]["b_lp"],
                "bat_hand": grp.iloc[i]["bat_hand"],
                # Short window
                "b_obp_short": ob_short / pa_short if pa_short >= MIN_PA else np.nan,
                "b_k_rate_short": k_short / pa_short if pa_short >= MIN_PA else np.nan,
                "b_hr_rate_short": hr_short / pa_short if pa_short >= MIN_PA else np.nan,
                # Long window
                "b_obp_long": ob_long / pa_long if pa_long >= MIN_PA else np.nan,
                "b_k_rate_long": k_long / pa_long if pa_long >= MIN_PA else np.nan,
                # vs RHP
                "b_obp_vs_rhp": rhp_ob / rhp_pa if rhp_pa >= MIN_PA else np.nan,
                "b_k_rate_vs_rhp": rhp_k / rhp_pa if rhp_pa >= MIN_PA else np.nan,
                # vs LHP
                "b_obp_vs_lhp": lhp_ob / lhp_pa if lhp_pa >= MIN_PA else np.nan,
                "b_k_rate_vs_lhp": lhp_k / lhp_pa if lhp_pa >= MIN_PA else np.nan,
                # PA counts (for weighting)
                "b_pa_short": pa_short,
                "b_pa_long": pa_long,
            }
            results.append(row)

    df = pd.DataFrame(results)
    logger.info(f"Entering features: {len(df)} batter-game rows")
    return df


def build_game_lineup_features(
    entering: pd.DataFrame,
    starters: pd.DataFrame,
    players: pd.DataFrame,
) -> pd.DataFrame:
    """Aggregate batter features per game for top-of-order (lineup pos 1-3).

    Returns one row per game with team-level batting aggregates.
    """
    # Filter to top-3 lineup positions
    top3 = entering[entering["b_lp"].isin([1, 2, 3])].copy()

    if top3.empty:
        return pd.DataFrame()

    # Get opposing starter hand for the "vs_hand" feature
    # We need to pick the right OBP column based on opposing starter hand
    # This info is already in the batter log, but we need the game-level starter hand
    # For now: use the entering features which already have vs_hand splits

    # For each game+team, get the opposing starter hand
    # (already embedded in the batter log via build_batter_game_logs)
    # We'll compute "effective OBP" = OBP vs the hand that the batter actually faces

    # Group by (gid, team) and aggregate top-3 stats
    agg = top3.groupby(["gid", "team", "season", "date"]).agg(
        top3_obp_short=("b_obp_short", "mean"),
        top3_obp_long=("b_obp_long", "mean"),
        top3_k_rate_short=("b_k_rate_short", "mean"),
        top3_k_rate_long=("b_k_rate_long", "mean"),
        top3_hr_rate_short=("b_hr_rate_short", "mean"),
        top3_obp_vs_rhp=("b_obp_vs_rhp", "mean"),
        top3_k_rate_vs_rhp=("b_k_rate_vs_rhp", "mean"),
        top3_obp_vs_lhp=("b_obp_vs_lhp", "mean"),
        top3_k_rate_vs_lhp=("b_k_rate_vs_lhp", "mean"),
        n_batters=("batter_id", "count"),
    ).reset_index()

    logger.info(f"Game lineup features: {len(agg)} team-game rows")
    return agg


def load_season_plays(year: int) -> pd.DataFrame | None:
    """Load plays.csv (play-by-play) from Retrosheet zip for a given year."""
    zf_path = RETRO_DIR / f"{year}csvs.zip"
    if not zf_path.exists():
        return None
    with zipfile.ZipFile(zf_path) as zf:
        fname = f"{year}plays.csv"
        if fname not in zf.namelist():
            return None
        with zf.open(fname) as f:
            cols = ["gid", "inning", "batter", "pitcher", "batteam",
                    "ab", "single", "double", "triple", "hr", "k", "sf",
                    "bip", "lp", "date"]
            df = pd.read_csv(f, usecols=cols)
    df["season"] = year
    return df


INN1_MIN_PA = 20  # minimum 1st-inning PA before producing BABIP


def build_first_inning_babip(
    years: list[int] | None = None,
) -> pd.DataFrame:
    """Build entering-game 1st-inning BABIP for pitchers and top-3 batters.

    Uses plays.csv (play-by-play) filtered to inning == 1.
    Returns one row per (gid, team) with:
      - sp_babip_inn1: starter pitcher's entering-game 1st-inning BABIP-against
      - top3_babip_inn1: mean 1st-inning BABIP of top-3 lineup batters
    """
    if years is None:
        years = list(range(2010, 2020)) + [2021] + list(range(2022, 2026))

    parts = []
    for year in years:
        plays = load_season_plays(year)
        if plays is not None:
            parts.append(plays)
            logger.info(f"  {year}: {len(plays)} plays loaded")

    if not parts:
        logger.error("No plays data found")
        return pd.DataFrame()

    all_plays = pd.concat(parts, ignore_index=True)
    all_plays["date"] = pd.to_datetime(all_plays["date"].astype(str), format="%Y%m%d")

    # Filter to 1st inning only
    inn1 = all_plays[all_plays["inning"] == 1].copy()
    inn1["hit"] = inn1["single"] + inn1["double"] + inn1["triple"] + inn1["hr"]
    logger.info(f"1st-inning plate appearances: {len(inn1)}")

    # ── Pitcher 1st-inning BABIP (entering-game rolling) ──────────────
    pitcher_babip = _compute_rolling_babip(
        inn1, id_col="pitcher", label="pitcher"
    )

    # ── Batter 1st-inning BABIP (entering-game rolling) ──────────────
    batter_babip = _compute_rolling_babip(
        inn1, id_col="batter", label="batter"
    )

    # ── Aggregate to game-level ──────────────────────────────────────
    # Pitcher: match to starter (first pitcher per team per game)
    # Identify starters: first pitcher each team faces in inning 1
    # Actually simpler: pitcher who pitches in inning 1 IS the starter
    starter_inn1 = inn1.drop_duplicates(subset=["gid", "pitcher"]).copy()
    # Keep the pitcher who faced the first batter for each pitching team
    starter_ids = inn1.sort_values(["gid", "date"]).groupby(
        ["gid"]
    ).agg(
        home_starter=("pitcher", "first"),  # first PA in game is away batting vs home pitcher
    ).reset_index()

    # More precise: group by (gid, batteam) — pitcher field tells us who's pitching to that team
    # Away batters (top of 1st) face the home pitcher; home batters (bottom) face away pitcher
    starters_by_game = inn1.sort_values("date").groupby(["gid", "batteam"]).agg(
        starter_id=("pitcher", "first"),
    ).reset_index()

    # Merge pitcher BABIP to each game-team
    pitcher_babip_game = pitcher_babip.rename(columns={
        "id": "starter_id", "babip_inn1": "sp_babip_inn1",
    })
    game_pitcher = starters_by_game.merge(
        pitcher_babip_game[["starter_id", "gid", "babip_inn1_pa"]].rename(
            columns={"babip_inn1_pa": "_merge_check"}
        ),
        on=["starter_id", "gid"], how="left"
    )
    # Actually we need to match pitcher_babip by (pitcher, gid)
    # pitcher_babip has one row per (pitcher, gid) with entering stats
    game_sp = starters_by_game.merge(
        pitcher_babip[["id", "gid", "babip_inn1"]].rename(
            columns={"id": "starter_id", "babip_inn1": "sp_babip_inn1"}
        ),
        on=["starter_id", "gid"], how="left"
    )

    # Batter: top-3 lineup (lp 1-3) per team per game
    # batter_babip has one row per (batter, gid)
    inn1_with_babip = inn1[["gid", "batter", "batteam", "lp", "date", "season"]].drop_duplicates(
        subset=["gid", "batter"]
    ).merge(
        batter_babip[["id", "gid", "babip_inn1"]].rename(
            columns={"id": "batter", "babip_inn1": "b_babip_inn1"}
        ),
        on=["batter", "gid"], how="left"
    )

    top3 = inn1_with_babip[inn1_with_babip["lp"].isin([1, 2, 3])].copy()
    top3_agg = top3.groupby(["gid", "batteam", "date", "season"]).agg(
        top3_babip_inn1=("b_babip_inn1", "mean"),
    ).reset_index()

    # Merge pitcher + batter into one game-team table
    result = top3_agg.merge(
        game_sp[["gid", "batteam", "sp_babip_inn1"]],
        on=["gid", "batteam"], how="left"
    )

    # batteam is the BATTING team — sp_babip_inn1 is the OPPOSING starter's BABIP
    # top3_babip_inn1 is the batting team's top-3 BABIP
    # Rename batteam → team for consistency
    result = result.rename(columns={"batteam": "team"})

    logger.info(
        f"1st-inning BABIP features: {len(result)} team-game rows, "
        f"sp_babip non-null: {result['sp_babip_inn1'].notna().sum()}, "
        f"top3_babip non-null: {result['top3_babip_inn1'].notna().sum()}"
    )
    return result


def _compute_rolling_babip(
    inn1: pd.DataFrame,
    id_col: str,
    label: str,
) -> pd.DataFrame:
    """Compute entering-game rolling 1st-inning BABIP for each player.

    Returns one row per (player, gid) with the BABIP computed from
    all prior 1st-inning appearances (anti-leak).
    """
    # Aggregate to per-player per-game 1st-inning totals
    game_stats = inn1.groupby([id_col, "gid", "season", "date"]).agg(
        pa=("ab", "sum"),  # using AB as denominator basis
        hits=("hit", "sum"),
        hr=("hr", "sum"),
        k=("k", "sum"),
        sf=("sf", "sum"),
    ).reset_index().sort_values([id_col, "date"])

    results = []
    for pid, grp in game_stats.groupby(id_col):
        grp = grp.sort_values("date").reset_index(drop=True)
        n = len(grp)
        if n < 2:
            continue

        pa_arr = grp["pa"].values.astype(float)
        h_arr = grp["hits"].values.astype(float)
        hr_arr = grp["hr"].values.astype(float)
        k_arr = grp["k"].values.astype(float)
        sf_arr = grp["sf"].values.astype(float)

        for i in range(1, n):
            # Entering-game: all prior 1st-inning appearances
            cum_h = h_arr[:i].sum()
            cum_hr = hr_arr[:i].sum()
            cum_ab = pa_arr[:i].sum()
            cum_k = k_arr[:i].sum()
            cum_sf = sf_arr[:i].sum()
            cum_pa = cum_ab + cum_sf  # total relevant PA

            if cum_pa < INN1_MIN_PA:
                continue

            denom = cum_ab - cum_k - cum_hr + cum_sf
            if denom <= 0:
                continue

            babip = (cum_h - cum_hr) / denom

            results.append({
                "id": pid,
                "gid": grp.iloc[i]["gid"],
                "season": grp.iloc[i]["season"],
                "date": grp.iloc[i]["date"],
                "babip_inn1": babip,
                "babip_inn1_pa": cum_pa,
            })

    df = pd.DataFrame(results)
    if df.empty:
        logger.info(f"{label} 1st-inning BABIP: 0 rows, 0 unique {label}s")
        return pd.DataFrame(
            columns=["id", "gid", "season", "date", "babip_inn1", "babip_inn1_pa"]
        )

    logger.info(f"{label} 1st-inning BABIP: {len(df)} rows, {df['id'].nunique()} unique {label}s")
    return df


def build_and_save(output_dir: Path | None = None) -> pd.DataFrame:
    """Full pipeline: load data, compute features, save parquet.

    Returns the game-level lineup features DataFrame.
    """
    if output_dir is None:
        output_dir = Path(__file__).resolve().parent.parent / "data" / "processed" / "retrosheet"

    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Loading all seasons...")
    batting, players, starters = load_all_batting()

    if batting.empty:
        logger.error("No batting data found")
        return pd.DataFrame()

    logger.info("Building batter game logs...")
    log = build_batter_game_logs(batting, players, starters)

    logger.info("Computing entering-game features...")
    entering = compute_entering_features(log)

    if entering.empty:
        logger.error("No entering features computed")
        return pd.DataFrame()

    # Save batter-level features
    batter_path = output_dir / "batter_entering_features.parquet"
    entering.to_parquet(batter_path, index=False)
    logger.info(f"Saved batter features to {batter_path}")

    logger.info("Building game lineup features...")
    lineup_features = build_game_lineup_features(entering, starters, players)

    # Save game-level lineup features
    lineup_path = output_dir / "game_lineup_features.parquet"
    lineup_features.to_parquet(lineup_path, index=False)
    logger.info(f"Saved lineup features to {lineup_path}")

    # Build 1st-inning BABIP features from plays.csv
    logger.info("Building 1st-inning BABIP features...")
    babip_features = build_first_inning_babip()
    if not babip_features.empty:
        babip_path = output_dir / "first_inning_babip.parquet"
        babip_features.to_parquet(babip_path, index=False)
        logger.info(f"Saved 1st-inning BABIP to {babip_path}")

    return lineup_features
