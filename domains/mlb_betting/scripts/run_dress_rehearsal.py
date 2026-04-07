"""Dress rehearsal: day-by-day portfolio simulation across all strategies.

Runs 7 strategies simultaneously on a target month, tracking P&L day by day.
Designed for final validation before the 2026 season.

Strategies:
  1. S3 Series Dogon (ML favorite, martingale)
  2. RL-1H (Away +1.5, 1st half, edge>0.10)
  3. RL-2H (Away +1.5, 2nd half, edge>0.05)
  4. UNDER O/U (P(under) pre-filter + LLM duel)
  5. OVER O/U (P(over) pre-filter + LLM duel)
  6. LLM Multi-zone (CF/S3/RL zone auto-assign + LLM duel)
  7. YRFI (top3_babip_inn1 + fip filter)

Usage:
    python scripts/run_dress_rehearsal.py --month 2024-06 --dry-run
    python scripts/run_dress_rehearsal.py --all-months --dry-run
    python scripts/run_dress_rehearsal.py --month 2023-09 --strategies rl2h,yrfi
"""

import hashlib
import json
import sys
import warnings
import logging
import argparse
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Load .env for OPENAI_API_KEY
_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    from dotenv import load_dotenv
    load_dotenv(_env_path)

warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                    datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

import numpy as np
import pandas as pd

from src.data_loader import (
    add_derived_odds,
    american_to_decimal,
    apply_data_filters,
    enrich_innings_from_retrosheet,
    load_all_seasons,
)
from src.feature_card import AnalystCard, FeatureCard, OUAnalystCard, OUFeatureCard
from src.features import (
    OU_FEATURES,
    SPEC_FEATURES,
    build_all_features,
    build_ou_features,
    build_spec_features,
    build_yrfi_features,
)
from src.llm_duel import DuelEngine
from src.llm_expert import Genome, LLMAnalyst, LLMExpert
from src.model import compute_divergence, run_walk_forward, run_walk_forward_under
from src.series import identify_series, select_series_favorite

BASE_DIR = Path(__file__).resolve().parent.parent
GENOMES_DIR = BASE_DIR / "genomes"
ASG_MONTH = 7
ASG_DAY = 15
RL_FALLBACK_ODDS = 1.87
OU_DECIMAL_ODDS = 1.909  # -110 standard

# YRFI odds calibration table (from run_yrfi_research.py)
_CALIB_OU = np.array([6.5, 7.25, 7.75, 8.25, 8.75, 9.50, 10.25, 11.0])
_CALIB_ODDS = np.array([2.32, 2.02, 1.94, 1.89, 1.84, 1.80, 1.71, 1.59])

TARGET_MONTHS = ["2019-09", "2024-06", "2025-04"]


# ── Data Structures ─────────────────────────────────────────────────────


@dataclass
class Bet:
    date: str
    strategy: str
    market: str
    game: str  # "AWAY@HOME"
    side: str  # team being backed
    odds: float
    stake: float
    won: bool | None = None
    pnl: float = 0.0
    meta: dict = field(default_factory=dict)


@dataclass
class DailyResult:
    date: str
    n_games: int
    bets: list[Bet]
    day_pnl: float = 0.0
    day_stake: float = 0.0


# ── Helpers ──────────────────────────────────────────────────────────────


def is_first_half(date_str: str) -> bool:
    dt = pd.Timestamp(date_str)
    return dt.month < ASG_MONTH or (dt.month == ASG_MONTH and dt.day <= ASG_DAY)


def estimate_yrfi_odds(close_ou: float) -> float:
    return float(np.interp(close_ou, _CALIB_OU, _CALIB_ODDS))


def max_loss_streak(outcomes: list[bool]) -> int:
    m = c = 0
    for o in outcomes:
        if not o:
            c += 1
            m = max(m, c)
        else:
            c = 0
    return m


def max_win_streak(outcomes: list[bool]) -> int:
    m = c = 0
    for o in outcomes:
        if o:
            c += 1
            m = max(m, c)
        else:
            c = 0
    return m


# ── LLM Cache ────────────────────────────────────────────────────────────

CACHE_DIR = BASE_DIR / ".llm_cache"


class LLMCache:
    """Disk-backed cache for LLM duel results.

    Key: (strategy_game_id, genome_versions). Prevents re-running
    API calls on restart.
    """

    def __init__(self, cache_dir: Path = CACHE_DIR):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._memory: dict[str, dict] = {}
        self.hits = 0
        self.misses = 0

    def _key(self, game_id: str) -> str:
        return hashlib.md5(game_id.encode()).hexdigest()

    def get(self, game_id: str) -> dict | None:
        k = self._key(game_id)
        if k in self._memory:
            self.hits += 1
            return self._memory[k]
        path = self.cache_dir / f"{k}.json"
        if path.exists():
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            self._memory[k] = data
            self.hits += 1
            return data
        self.misses += 1
        return None

    def put(self, game_id: str, result: dict) -> None:
        k = self._key(game_id)
        self._memory[k] = result
        path = self.cache_dir / f"{k}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False)


# ── Duel Context ──────────────────────────────────────────────────────────


@dataclass
class DuelContext:
    """Shared LLM infrastructure for strategies requiring duel calls."""
    ml_engine: DuelEngine       # Momentum + Value (for LLM-MULTI)
    under_engine: DuelEngine    # PitchingFirst + RunEnvironment
    over_engine: DuelEngine     # OffenseFirst + FatigueExploit
    cache: LLMCache


# ── Data Pipeline ────────────────────────────────────────────────────────


def build_master_data():
    """Load all data, build features, run ML models. Returns (master_df, series_list)."""
    logger.info("Loading all seasons...")
    games = load_all_seasons()
    games = enrich_innings_from_retrosheet(games)
    games = apply_data_filters(games)
    games = add_derived_odds(games)

    logger.info("Building all features (~3 min)...")
    enriched = build_all_features(games)

    # ML walk-forward: regime-split regression → edge_consensus
    logger.info("Running ML walk-forward (regime split)...")
    spec = build_spec_features(enriched=enriched)
    fold_results = run_walk_forward(spec, SPEC_FEATURES, "closing_decimal_odds_favorite")

    # Collect predictions and compute edge_consensus
    div_df = compute_divergence(fold_results)
    pred_cols = [c for c in div_df.columns if c.startswith("pred_")]
    if pred_cols:
        div_df["pred_consensus"] = div_df[pred_cols].mean(axis=1)
        target_col = "closing_decimal_odds_favorite"
        if target_col in div_df.columns:
            div_df["edge_consensus"] = div_df[target_col] - div_df["pred_consensus"]

    # Under classifier walk-forward → p_under
    logger.info("Running Under classifier walk-forward...")
    ou = build_ou_features(enriched=enriched)
    under_results = run_walk_forward_under(ou, OU_FEATURES)

    # Collect under predictions
    under_preds = pd.concat(
        [r.test_predictions for r in under_results if r.test_predictions is not None],
        ignore_index=True,
    )
    # Use the last fold's threshold as default
    p_under_threshold = under_results[-1].p_under_threshold if under_results else 0.55

    # YRFI features
    logger.info("Building YRFI features...")
    yrfi_df = build_yrfi_features(enriched=enriched)

    # Series identification
    logger.info("Identifying series...")
    series_list = identify_series(enriched)

    # ── Merge everything onto enriched ───────────────────────────────
    master = enriched.copy()
    master["date"] = pd.to_datetime(master["date"]).dt.normalize()

    # Merge edge_consensus from divergence
    if "edge_consensus" in div_df.columns:
        merge_cols = ["season", "date", "home_team", "away_team"]
        avail = [c for c in merge_cols if c in div_df.columns]
        if avail:
            div_df["date"] = pd.to_datetime(div_df["date"]).dt.normalize()
            master = master.merge(
                div_df[avail + ["edge_consensus", "pred_consensus"]].drop_duplicates(subset=avail),
                on=avail,
                how="left",
                suffixes=("", "_div"),
            )

    # Merge p_under
    if not under_preds.empty:
        under_preds["date"] = pd.to_datetime(under_preds["date"]).dt.normalize()
        master = master.merge(
            under_preds[["date", "home_team", "away_team", "p_under"]].drop_duplicates(
                subset=["date", "home_team", "away_team"]
            ),
            on=["date", "home_team", "away_team"],
            how="left",
        )
    if "p_under" not in master.columns:
        master["p_under"] = np.nan
    master["p_over"] = 1 - master["p_under"]

    # Merge late-game quality features for triple-stake gate (session 25)
    gate_cols = [c for c in ["hold_rate_combined", "close_game_wp_combined"]
                 if c in ou.columns and c not in master.columns]
    if gate_cols:
        ou_gate = ou[["season", "date", "home_team", "away_team"] + gate_cols].copy()
        ou_gate["date"] = pd.to_datetime(ou_gate["date"]).dt.normalize()
        master = master.merge(
            ou_gate.drop_duplicates(subset=["date", "home_team", "away_team"]),
            on=["date", "home_team", "away_team"],
            how="left",
            suffixes=("", "_ou"),
        )

    # Merge YRFI composites
    yrfi_cols_new = [c for c in yrfi_df.columns if c not in master.columns]
    if yrfi_cols_new:
        yrfi_df["date"] = pd.to_datetime(yrfi_df["date"]).dt.normalize()
        master = master.merge(
            yrfi_df[["date", "home_team", "away_team"] + yrfi_cols_new].drop_duplicates(
                subset=["date", "home_team", "away_team"]
            ),
            on=["date", "home_team", "away_team"],
            how="left",
        )

    # Derived flags
    master["fav_is_home"] = master.get("home_implied_prob", 0.5) > master.get("away_implied_prob", 0.5)
    if "total_runs" not in master.columns:
        master["total_runs"] = master["home_final"] + master["away_final"]

    logger.info(f"Master data: {len(master)} games, edge_consensus coverage: "
                f"{master['edge_consensus'].notna().sum()}, p_under coverage: "
                f"{master['p_under'].notna().sum()}")

    return master, series_list, p_under_threshold


# ── Strategy Classes ─────────────────────────────────────────────────────


class S3Strategy:
    """Series Dogon: bet favorite (home or away) ML in game 1, double-up game 2."""

    name = "S3"
    requires_llm = False

    def __init__(self, series_list, enriched, base_stake=100.0):
        self.base_stake = base_stake
        # Index series by game dates for quick lookup
        self.date_to_series = {}  # date_str -> [(series, game_idx)]
        for s in series_list:
            for i, g in enumerate(s.games):
                d = pd.Timestamp(g.date).normalize().strftime("%Y-%m-%d")
                self.date_to_series.setdefault(d, []).append((s, i))
        # Build feature index: (home_team, away_team, date) -> row
        self.feat_index = {}
        for _, row in enriched.iterrows():
            d = pd.Timestamp(row["date"]).normalize().strftime("%Y-%m-%d")
            key = (row["home_team"], row["away_team"], d)
            self.feat_index[key] = row
        self.open_series = {}  # series_key -> {g1_lost, g1_stake, g1_odds, favorite}

    def is_active(self, month, first_half):
        return True  # Active all months (September no longer excluded)

    def reset(self):
        self.open_series = {}

    def _check_filters(self, series, favorite):
        g1 = series.games[0]
        fav_is_home = (favorite == g1.home_team)
        key = (g1.home_team, g1.away_team,
               pd.Timestamp(g1.date).normalize().strftime("%Y-%m-%d"))
        feats = self.feat_index.get(key)
        if feats is None:
            return False
        rpi_diff = feats.get("rpi_diff", 0)
        wp_diff = feats.get("wp_diff", 0)
        sp_wr = feats.get("sp_wr_long_diff", 0)
        sp_ra = feats.get("sp_ra_long_diff", 0)
        # Flip if favorite is away
        if not fav_is_home:
            rpi_diff = -rpi_diff
            wp_diff = -wp_diff
            sp_wr = -sp_wr
            sp_ra = -sp_ra
        return rpi_diff >= 0.03 and wp_diff >= 0.05 and sp_ra <= 0 and sp_wr >= 0.10

    def generate_bets(self, day_games, date_str):
        bets = []
        entries = self.date_to_series.get(date_str, [])
        for series, game_idx in entries:
            g = series.games[game_idx]
            sk = series.series_key

            if game_idx == 0:
                # Game 1: check filters, potentially enter
                fav = select_series_favorite(series, method="game1_odds")
                if fav is None:
                    continue
                favorite, underdog = fav
                if not self._check_filters(series, favorite):
                    continue
                # Determine odds
                if favorite == g.home_team:
                    odds = g.home_decimal_odds
                    won = g.home_win
                else:
                    odds = g.away_decimal_odds
                    won = not g.home_win
                if odds < 1.66:
                    continue  # Skip heavy favorites: stake too large vs $100 profit
                stake = self.base_stake / (odds - 1)
                pnl = stake * (odds - 1) if won else -stake
                bets.append(Bet(
                    date=date_str, strategy="S3", market=f"ML {'home' if favorite == g.home_team else 'away'}",
                    game=f"{g.away_team}@{g.home_team}", side=favorite,
                    odds=round(odds, 3), stake=round(stake, 2), won=won, pnl=round(pnl, 2),
                    meta={"series_key": sk, "game": 1},
                ))
                if not won:
                    self.open_series[sk] = {
                        "g1_loss": stake, "favorite": favorite,
                    }
                else:
                    self.open_series.pop(sk, None)

            elif game_idx == 1 and sk in self.open_series:
                # Game 2: dogon (recovery bet)
                info = self.open_series.pop(sk)
                favorite = info["favorite"]
                needed = info["g1_loss"] + self.base_stake
                if favorite == g.home_team:
                    odds = g.home_decimal_odds
                    won = g.home_win
                else:
                    odds = g.away_decimal_odds
                    won = not g.home_win
                if odds <= 1.0:
                    continue
                stake = needed / (odds - 1)
                pnl = stake * (odds - 1) if won else -stake
                bets.append(Bet(
                    date=date_str, strategy="S3", market=f"ML {'home' if favorite == g.home_team else 'away'}",
                    game=f"{g.away_team}@{g.home_team} (G2!)", side=favorite,
                    odds=round(odds, 3), stake=round(stake, 2), won=won, pnl=round(pnl, 2),
                    meta={"series_key": sk, "game": 2, "dogon": True},
                ))
        return bets


class RL1HStrategy:
    """Run Line Away +1.5, first half only, edge > 0.10."""

    name = "RL-1H"
    requires_llm = False

    def __init__(self, base_stake=100.0):
        self.base_stake = base_stake

    def is_active(self, month, first_half):
        return first_half

    def reset(self):
        pass

    def generate_bets(self, day_games, date_str):
        bets = []
        for _, row in day_games.iterrows():
            edge = row.get("edge_consensus", np.nan)
            if pd.isna(edge) or edge <= 0.10:
                continue
            if not row.get("fav_is_home", True):
                continue  # only bet when home is favorite (away is underdog)
            if row.get("involves_col", False) or row.get("is_extreme_line", False):
                continue
            # Away +1.5
            rl_raw = row.get("away_run_line_odds", np.nan)
            odds = american_to_decimal(float(rl_raw)) if pd.notna(rl_raw) else RL_FALLBACK_ODDS
            margin = int(row.get("home_final", 0)) - int(row.get("away_final", 0))
            won = margin <= 1
            pnl = self.base_stake * (odds - 1) if won else -self.base_stake
            bets.append(Bet(
                date=date_str, strategy="RL-1H", market="RL+1.5 away",
                game=f"{row['away_team']}@{row['home_team']}", side=row["away_team"],
                odds=round(odds, 3), stake=self.base_stake, won=won, pnl=round(pnl, 2),
                meta={"edge": round(edge, 4)},
            ))
        return bets


class RL2HStrategy:
    """Run Line Away +1.5, second half only (incl September), edge > 0.05."""

    name = "RL-2H"
    requires_llm = False

    def __init__(self, base_stake=100.0):
        self.base_stake = base_stake

    def is_active(self, month, first_half):
        return not first_half

    def reset(self):
        pass

    def generate_bets(self, day_games, date_str):
        bets = []
        for _, row in day_games.iterrows():
            edge = row.get("edge_consensus", np.nan)
            if pd.isna(edge) or edge <= 0.05:
                continue
            if not row.get("fav_is_home", True):
                continue
            if row.get("involves_col", False) or row.get("is_extreme_line", False):
                continue
            rl_raw = row.get("away_run_line_odds", np.nan)
            odds = american_to_decimal(float(rl_raw)) if pd.notna(rl_raw) else RL_FALLBACK_ODDS
            margin = int(row.get("home_final", 0)) - int(row.get("away_final", 0))
            won = margin <= 1
            pnl = self.base_stake * (odds - 1) if won else -self.base_stake
            bets.append(Bet(
                date=date_str, strategy="RL-2H", market="RL+1.5 away",
                game=f"{row['away_team']}@{row['home_team']}", side=row["away_team"],
                odds=round(odds, 3), stake=self.base_stake, won=won, pnl=round(pnl, 2),
                meta={"edge": round(edge, 4)},
            ))
        return bets


class UnderStrategy:
    """Under O/U: P(under) pre-filter + LLM duel (PitchingFirst + RunEnvironment)."""

    name = "UNDER"
    requires_llm = True

    # Triple-stake gate: P(under)>=0.60 + late-game quality confirmation.
    # Session 25 A/B: H1 +11.5pp, C1 +13.5pp ROI at P>=0.60.
    HIGH_CONF_THRESHOLD = 0.60
    HOLD_RATE_GATE = 1.667       # p50 of hold_rate_combined
    CLOSE_GAME_WP_GATE = 1.000   # p50 of close_game_wp_combined
    HIGH_CONF_MULTIPLIER = 3.0

    def __init__(self, threshold=0.55, base_stake=100.0, duel_ctx: DuelContext | None = None):
        self.threshold = threshold
        self.base_stake = base_stake
        self.duel_ctx = duel_ctx

    def is_active(self, month, first_half):
        return True

    def reset(self):
        pass

    def count_candidates(self, day_games, date_str):
        return int((day_games.get("p_under", pd.Series(dtype=float)) >= self.threshold).sum())

    def generate_bets(self, day_games, date_str):
        bets = []
        for _, row in day_games.iterrows():
            p_u = row.get("p_under", np.nan)
            if pd.isna(p_u) or p_u < self.threshold:
                continue
            if row.get("involves_col", False) or row.get("is_extreme_line", False):
                continue
            close_ou = row.get("close_ou", np.nan)
            if pd.isna(close_ou):
                continue
            total = row.get("total_runs", np.nan)
            if pd.isna(total):
                continue

            game_label = f"{row['away_team']}@{row['home_team']}"
            meta: dict = {"p_under": round(p_u, 3)}

            # ── LLM duel gate ──
            if self.duel_ctx:
                cache_key = f"under_{date_str}_{row['away_team']}_{row['home_team']}"
                cached = self.duel_ctx.cache.get(cache_key)
                if cached:
                    duel_action = cached["final_action"]
                    meta["duel"] = cached
                else:
                    try:
                        analyst_card = OUAnalystCard.from_row(row)
                        betting_card = OUFeatureCard.from_row(row, p_under=p_u)
                        result = self.duel_ctx.under_engine.run_ou(
                            betting_card, analyst_card=analyst_card, close_ou=float(close_ou),
                        )
                        duel_dict = result.to_dict()
                        self.duel_ctx.cache.put(cache_key, duel_dict)
                        duel_action = result.final_action
                        meta["duel"] = duel_dict
                    except Exception as e:
                        logger.warning(f"  UNDER duel error {game_label}: {e}")
                        continue
                if duel_action == "PASS":
                    continue  # LLM rejected

            # ── Stake sizing: triple on high-conf + late-game quality gate ──
            stake = self.base_stake
            if p_u >= self.HIGH_CONF_THRESHOLD:
                hr = row.get("hold_rate_combined", np.nan)
                cg = row.get("close_game_wp_combined", np.nan)
                hr_ok = not pd.isna(hr) and hr > self.HOLD_RATE_GATE
                cg_ok = not pd.isna(cg) and cg > self.CLOSE_GAME_WP_GATE
                if hr_ok or cg_ok:
                    stake = self.base_stake * self.HIGH_CONF_MULTIPLIER
                    meta["triple_gate"] = "hold_rate" if hr_ok else "close_game_wp"

            # ── Score ──
            if total == close_ou:
                meta["push"] = True
                bets.append(Bet(
                    date=date_str, strategy="UNDER", market=f"UNDER {close_ou}",
                    game=game_label, side="under",
                    odds=OU_DECIMAL_ODDS, stake=stake, won=None, pnl=0.0,
                    meta=meta,
                ))
                continue
            won = total < close_ou
            meta["total"] = int(total)
            pnl = stake * (OU_DECIMAL_ODDS - 1) if won else -stake
            bets.append(Bet(
                date=date_str, strategy="UNDER", market=f"UNDER {close_ou}",
                game=game_label, side="under",
                odds=OU_DECIMAL_ODDS, stake=stake, won=won, pnl=round(pnl, 2),
                meta=meta,
            ))
        return bets


class ExpansionUnderStrategy:
    """Expansion zone UNDER: p_under in [0.51, main_threshold), Jun-Aug only.

    Bets only when the LLM duel returns LEAN_UNDER (one expert leans under).
    Full UNDER consensus in this zone is noise (session 25 backtest: +6.2% ROI
    on LEAN_UNDER vs -4.5% on UNDER across 2267 games 2023-2025).
    Stake: 0.5x base (half-stake, matching the LEAN_UNDER signal strength).
    """

    name = "UNDER-EXP"
    requires_llm = True

    EXPANSION_MIN = 0.51
    ACTIVE_MONTHS = {6, 7, 8}  # Jun-Aug: +13.3% ROI vs +6.2% all months
    STAKE_MULT = 0.5

    def __init__(self, main_threshold=0.55, base_stake=100.0, duel_ctx: DuelContext | None = None):
        self.main_threshold = main_threshold
        self.base_stake = base_stake
        self.duel_ctx = duel_ctx

    def is_active(self, month, first_half):
        return month in self.ACTIVE_MONTHS

    def reset(self):
        pass

    def count_candidates(self, day_games, date_str):
        return int((
            (day_games.get("p_under", pd.Series(dtype=float)) >= self.EXPANSION_MIN)
            & (day_games.get("p_under", pd.Series(dtype=float)) < self.main_threshold)
        ).sum())

    def generate_bets(self, day_games, date_str):
        bets = []
        for _, row in day_games.iterrows():
            p_u = row.get("p_under", np.nan)
            if pd.isna(p_u) or p_u < self.EXPANSION_MIN or p_u >= self.main_threshold:
                continue
            if row.get("involves_col", False) or row.get("is_extreme_line", False):
                continue
            close_ou = row.get("close_ou", np.nan)
            total = row.get("total_runs", np.nan)
            if pd.isna(close_ou) or pd.isna(total):
                continue

            game_label = f"{row['away_team']}@{row['home_team']}"
            meta: dict = {"p_under": round(p_u, 3), "expansion": True}

            # ── LLM duel gate — only LEAN_UNDER passes ──
            if not self.duel_ctx:
                continue  # expansion zone requires LLM confirmation
            cache_key = f"under_{date_str}_{row['away_team']}_{row['home_team']}"
            cached = self.duel_ctx.cache.get(cache_key)
            if cached:
                duel_action = cached["final_action"]
                meta["duel"] = cached
            else:
                try:
                    analyst_card = OUAnalystCard.from_row(row)
                    betting_card = OUFeatureCard.from_row(row, p_under=p_u)
                    result = self.duel_ctx.under_engine.run_ou(
                        betting_card, analyst_card=analyst_card, close_ou=float(close_ou),
                    )
                    duel_dict = result.to_dict()
                    self.duel_ctx.cache.put(cache_key, duel_dict)
                    duel_action = result.final_action
                    meta["duel"] = duel_dict
                except Exception as e:
                    logger.warning(f"  UNDER-EXP duel error {game_label}: {e}")
                    continue

            if duel_action != "LEAN_UNDER":
                continue  # only LEAN_UNDER; UNDER and PASS are both rejected

            stake = self.base_stake * self.STAKE_MULT

            # ── Score ──
            if total == close_ou:
                meta["push"] = True
                bets.append(Bet(
                    date=date_str, strategy="UNDER-EXP", market=f"UNDER {close_ou}",
                    game=game_label, side="under",
                    odds=OU_DECIMAL_ODDS, stake=stake, won=None, pnl=0.0,
                    meta=meta,
                ))
                continue
            won = total < close_ou
            meta["total"] = int(total)
            pnl = stake * (OU_DECIMAL_ODDS - 1) if won else -stake
            bets.append(Bet(
                date=date_str, strategy="UNDER-EXP", market=f"UNDER {close_ou}",
                game=game_label, side="under",
                odds=OU_DECIMAL_ODDS, stake=stake, won=won, pnl=round(pnl, 2),
                meta=meta,
            ))
        return bets


class OverStrategy:
    """Over O/U: P(over) pre-filter + LLM duel (OffenseFirst + FatigueExploit)."""

    name = "OVER"
    requires_llm = True

    def __init__(self, threshold=0.52, base_stake=100.0, duel_ctx: DuelContext | None = None):
        self.threshold = threshold
        self.base_stake = base_stake
        self.duel_ctx = duel_ctx

    def is_active(self, month, first_half):
        return True

    def reset(self):
        pass

    def count_candidates(self, day_games, date_str):
        return int((day_games.get("p_over", pd.Series(dtype=float)) >= self.threshold).sum())

    def generate_bets(self, day_games, date_str):
        bets = []
        for _, row in day_games.iterrows():
            p_o = row.get("p_over", np.nan)
            if pd.isna(p_o) or p_o < self.threshold:
                continue
            if row.get("involves_col", False) or row.get("is_extreme_line", False):
                continue
            close_ou = row.get("close_ou", np.nan)
            total = row.get("total_runs", np.nan)
            if pd.isna(close_ou) or pd.isna(total):
                continue

            game_label = f"{row['away_team']}@{row['home_team']}"
            meta: dict = {"p_over": round(p_o, 3)}

            # ── LLM duel gate ──
            if self.duel_ctx:
                cache_key = f"over_{date_str}_{row['away_team']}_{row['home_team']}"
                cached = self.duel_ctx.cache.get(cache_key)
                if cached:
                    duel_action = cached["final_action"]
                    meta["duel"] = cached
                else:
                    try:
                        analyst_card = OUAnalystCard.from_row_over(row)
                        betting_card = OUFeatureCard.from_row_over(row, p_over=p_o)
                        result = self.duel_ctx.over_engine.run_over(
                            betting_card, analyst_card=analyst_card, close_ou=float(close_ou),
                        )
                        duel_dict = result.to_dict()
                        self.duel_ctx.cache.put(cache_key, duel_dict)
                        duel_action = result.final_action
                        meta["duel"] = duel_dict
                    except Exception as e:
                        logger.warning(f"  OVER duel error {game_label}: {e}")
                        continue
                if duel_action == "PASS":
                    continue  # LLM rejected

            # ── Score ──
            if total == close_ou:
                meta["push"] = True
                bets.append(Bet(
                    date=date_str, strategy="OVER", market=f"OVER {close_ou}",
                    game=game_label, side="over",
                    odds=OU_DECIMAL_ODDS, stake=self.base_stake, won=None, pnl=0.0,
                    meta=meta,
                ))
                continue
            won = total > close_ou
            meta["total"] = int(total)
            pnl = self.base_stake * (OU_DECIMAL_ODDS - 1) if won else -self.base_stake
            bets.append(Bet(
                date=date_str, strategy="OVER", market=f"OVER {close_ou}",
                game=game_label, side="over",
                odds=OU_DECIMAL_ODDS, stake=self.base_stake, won=won, pnl=round(pnl, 2),
                meta=meta,
            ))
        return bets


class LLMMultiStrategy:
    """LLM Multi-zone: zone auto-assign + LLM duel (Momentum + Value)."""

    name = "LLM-MULTI"
    requires_llm = True

    # Zone name mapping for DuelEngine
    _ZONE_MAP = {"CF": "CF_pickem", "S3": "S3_expansion", "RL": "RL_expansion"}

    def __init__(self, base_stake=100.0, duel_ctx: DuelContext | None = None):
        self.base_stake = base_stake
        self.duel_ctx = duel_ctx

    def is_active(self, month, first_half):
        return True

    def reset(self):
        pass

    def count_candidates(self, day_games, date_str):
        n = 0
        for _, row in day_games.iterrows():
            if row.get("involves_col", False) or row.get("is_extreme_line", False):
                continue
            if pd.isna(row.get("home_close_ml")) or pd.isna(row.get("away_close_ml")):
                continue
            fav_home = row.get("fav_is_home", True)
            is_cf = row.get("is_coinflip", False)
            if is_cf or fav_home:
                n += 1
        return n

    def generate_bets(self, day_games, date_str):
        bets = []
        for _, row in day_games.iterrows():
            if row.get("involves_col", False) or row.get("is_extreme_line", False):
                continue
            if pd.isna(row.get("home_close_ml")) or pd.isna(row.get("away_close_ml")):
                continue
            is_cf = row.get("is_coinflip", False)
            fav_home = row.get("fav_is_home", True)
            if is_cf:
                zone = "CF"
            elif fav_home:
                edge = row.get("edge_consensus", np.nan)
                zone = "S3" if (pd.notna(edge) and edge < 0) else "RL"
            else:
                continue  # home underdog -> skip

            game_label = f"{row['away_team']}@{row['home_team']}"
            home_win = bool(row.get("home_win", 0))
            margin = int(row.get("home_final", 0)) - int(row.get("away_final", 0))
            meta: dict = {"zone": zone}

            # ── LLM duel gate ──
            if self.duel_ctx:
                cache_key = f"multi_{zone}_{date_str}_{row['away_team']}_{row['home_team']}"
                cached = self.duel_ctx.cache.get(cache_key)
                if cached:
                    duel_action = cached["final_action"]
                    target_side = cached.get("target_side", "away")
                    bet_type = cached.get("final_bet_type", "ML")
                    meta["duel"] = cached
                else:
                    try:
                        duel_zone = self._ZONE_MAP.get(zone, zone)
                        card = FeatureCard.from_row(row, zone=duel_zone)
                        analyst_card = AnalystCard.from_row(row)
                        result = self.duel_ctx.ml_engine.run(card, analyst_card=analyst_card)
                        duel_dict = result.to_dict()
                        self.duel_ctx.cache.put(cache_key, duel_dict)
                        duel_action = result.final_action
                        target_side = result.target_side
                        bet_type = result.final_bet_type
                        meta["duel"] = duel_dict
                    except Exception as e:
                        logger.warning(f"  MULTI duel error {game_label}: {e}")
                        continue
                if duel_action == "PASS":
                    continue  # LLM rejected

            # ── Determine bet side and odds ──
            if self.duel_ctx:
                # Use duel result to determine side
                if zone == "CF":
                    if target_side == "home":
                        won = home_win
                        odds = float(row.get("home_decimal_odds", 2.0))
                        side = row["home_team"]
                        market = "ML CF home"
                    else:
                        won = not home_win
                        odds = float(row.get("away_decimal_odds", 2.0))
                        side = row["away_team"]
                        market = "ML CF away"
                elif zone == "S3":
                    won = not home_win
                    odds = float(row.get("away_decimal_odds", 2.0))
                    side = row["away_team"]
                    market = "ML away"
                else:  # RL
                    won = margin <= 1
                    rl_raw = row.get("away_run_line_odds", np.nan)
                    odds = american_to_decimal(float(rl_raw)) if pd.notna(rl_raw) else RL_FALLBACK_ODDS
                    side = row["away_team"]
                    market = "RL+1.5"
            else:
                # Dry-run fallback: always away
                if zone == "CF":
                    won = not home_win
                    odds = float(row.get("away_decimal_odds", 2.0))
                    market = "ML CF"
                    side = row["away_team"]
                elif zone == "S3":
                    won = not home_win
                    odds = float(row.get("away_decimal_odds", 2.0))
                    market = "ML away"
                    side = row["away_team"]
                else:  # RL
                    won = margin <= 1
                    rl_raw = row.get("away_run_line_odds", np.nan)
                    odds = american_to_decimal(float(rl_raw)) if pd.notna(rl_raw) else RL_FALLBACK_ODDS
                    market = "RL+1.5"
                    side = row["away_team"]

            pnl = self.base_stake * (odds - 1) if won else -self.base_stake
            bets.append(Bet(
                date=date_str, strategy="LLM-MULTI", market=f"{market} ({zone})",
                game=game_label, side=side,
                odds=round(odds, 3), stake=self.base_stake, won=won, pnl=round(pnl, 2),
                meta=meta,
            ))
        return bets


class YRFIStrategy:
    """YRFI: top3_babip_inn1 + starter_fip filter."""

    name = "YRFI"
    requires_llm = False

    def __init__(self, base_stake=100.0):
        self.base_stake = base_stake

    def is_active(self, month, first_half):
        return True  # Active whenever inning data exists

    def reset(self):
        pass

    def generate_bets(self, day_games, date_str):
        bets = []
        for _, row in day_games.iterrows():
            # Check inning data exists
            if pd.isna(row.get("away_inn_1")) or pd.isna(row.get("home_inn_1")):
                continue
            if row.get("away_inn_1", 0) == 0 and row.get("home_inn_1", 0) == 0:
                # Could be real NRFI or fake zero data — check total
                total_inns = sum(
                    row.get(f"away_inn_{i}", 0) + row.get(f"home_inn_{i}", 0)
                    for i in range(1, 10)
                )
                if total_inns == 0:
                    continue  # Fake data
            if row.get("involves_col", False):
                continue
            # YRFI filters: top3_babip_inn1_combined > 0.7 AND starter_fip_combined > 8.4
            babip = row.get("top3_babip_inn1_combined", np.nan)
            fip = row.get("starter_fip_combined", np.nan)
            if pd.isna(babip) or pd.isna(fip):
                continue
            if babip <= 0.7 or fip <= 8.4:
                continue
            # Odds from calibration table
            close_ou = row.get("close_ou", 8.5)
            odds = estimate_yrfi_odds(close_ou) if pd.notna(close_ou) else 1.85
            # Outcome
            inn1_runs = row.get("away_inn_1", 0) + row.get("home_inn_1", 0)
            won = inn1_runs > 0
            pnl = self.base_stake * (odds - 1) if won else -self.base_stake
            bets.append(Bet(
                date=date_str, strategy="YRFI", market="YRFI",
                game=f"{row['away_team']}@{row['home_team']}", side="yrfi",
                odds=round(odds, 3), stake=self.base_stake, won=won, pnl=round(pnl, 2),
                meta={"babip": round(babip, 3), "fip": round(fip, 2), "inn1_runs": int(inn1_runs)},
            ))
        return bets


# ── Output ───────────────────────────────────────────────────────────────


def _duel_summary(meta: dict) -> str:
    """One-line duel verdict summary for display."""
    duel = meta.get("duel")
    if not duel:
        return ""
    action = duel.get("final_action", "?")
    conf = duel.get("combined_confidence", 0)
    parts = [f"{action} conf={conf:.2f}"]
    # Expert verdicts
    for key in ("verdict_a", "verdict_b"):
        v = duel.get(key)
        if v:
            name = v.get("expert_name", key[-1].upper())
            parts.append(f"{name}:{v.get('action', '?')}")
    # Analyst scenario
    sc = duel.get("scenario")
    if sc:
        pt = sc.get("predicted_total")
        sp = sc.get("scoring_pattern", "")
        pw = sc.get("predicted_winner", "")
        tight = sc.get("tightness", "")
        if pt:
            parts.append(f"Analyst:{pt:.1f} {sp}")
        elif pw:
            parts.append(f"Analyst:{pw} {tight}")
    return " | ".join(parts)


def print_daily_card(daily: DailyResult, bankroll: float, peak: float,
                     running_mws: int = 0, running_mls: int = 0):
    dt = pd.Timestamp(daily.date)
    day_name = dt.strftime("%a")
    print(f"\n{'='*78}")
    print(f"  {daily.date} ({day_name}) | {daily.n_games} games on slate")
    print(f"{'='*78}")

    if not daily.bets:
        print("  No bets today.")
        return

    print(f"  {'#':<3} {'Strat':<10} {'Market':<18} {'Game':<22} {'Odds':>5} "
          f"{'Stake':>7} {'Result':>6} {'P&L':>8}")
    print(f"  {'-'*76}")

    for i, b in enumerate(daily.bets, 1):
        result = "PUSH" if b.won is None else ("WON" if b.won else "LOST")
        print(f"  {i:<3} {b.strategy:<10} {b.market:<18} {b.game:<22} "
              f"{b.odds:5.2f} ${b.stake:6.0f} {result:>6} {b.pnl:+8.0f}")
        # Duel verdict for LLM strategies
        duel_line = _duel_summary(b.meta)
        if duel_line:
            print(f"      -> {duel_line}")

    print(f"  {'-'*76}")
    dd = (peak - bankroll) / peak * 100 if peak > 0 else 0
    print(f"  Day P&L: {daily.day_pnl:+.0f} | Bankroll: ${bankroll:,.0f} "
          f"| Peak: ${peak:,.0f} | DD: {dd:.1f}%"
          f" | MaxWS: {running_mws} | MaxLS: {running_mls}")


def print_monthly_summary(month: str, daily_results: list[DailyResult],
                          strategies_used: list[str]):
    all_bets = [b for d in daily_results for b in d.bets]
    if not all_bets:
        print(f"\n  {month}: No bets placed.")
        return

    print(f"\n{'='*80}")
    print(f"  DRESS REHEARSAL SUMMARY: {month}")
    print(f"{'='*80}")

    # Per-strategy stats
    print(f"\n  {'Strategy':<12} {'Bets':>5} {'Win%':>6} {'P&L':>8} {'ROI':>7} "
          f"{'Sharpe':>7} {'MaxDD':>6} {'MLS':>4} {'MWS':>4}")
    print(f"  {'-'*66}")

    strat_names = sorted(set(b.strategy for b in all_bets))
    for sname in strat_names:
        sb = [b for b in all_bets if b.strategy == sname]
        scored = [b for b in sb if b.won is not None]
        if not scored:
            print(f"  {sname:<12} {len(sb):5d}   {'--':>4}   {'--':>6}   {'--':>5}   {'--':>5}   {'--':>4}   {'--':>2}   {'--':>2}")
            continue
        wins = sum(1 for b in scored if b.won)
        total_pnl = sum(b.pnl for b in scored)
        total_stake = sum(b.stake for b in scored)
        wr = wins / len(scored) * 100
        roi = total_pnl / total_stake * 100 if total_stake > 0 else 0
        pnl_arr = np.array([b.pnl for b in scored])
        ev = pnl_arr.mean()
        std = pnl_arr.std(ddof=1) if len(pnl_arr) > 1 else 1
        sharpe = ev / std * np.sqrt(len(pnl_arr)) if std > 0 else 0
        # Max drawdown
        cum = np.cumsum(pnl_arr)
        peak_cum = np.maximum.accumulate(cum)
        dd_arr = peak_cum - cum
        max_dd = dd_arr.max() / (10000 + peak_cum.max()) * 100 if peak_cum.max() > 0 else 0
        outcomes = [b.won for b in scored]
        mls = max_loss_streak(outcomes)
        mws = max_win_streak(outcomes)
        print(f"  {sname:<12} {len(scored):5d} {wr:5.1f}% {total_pnl:+8.0f} "
              f"{roi:+6.1f}% {sharpe:7.3f} {max_dd:5.1f}% {mls:4d} {mws:4d}")

    # Portfolio combined
    scored_all = [b for b in all_bets if b.won is not None]
    if scored_all:
        wins = sum(1 for b in scored_all if b.won)
        total_pnl = sum(b.pnl for b in scored_all)
        total_stake = sum(b.stake for b in scored_all)
        wr = wins / len(scored_all) * 100
        roi = total_pnl / total_stake * 100 if total_stake > 0 else 0
        pnl_arr = np.array([b.pnl for b in scored_all])
        ev = pnl_arr.mean()
        std = pnl_arr.std(ddof=1) if len(pnl_arr) > 1 else 1
        sharpe = ev / std * np.sqrt(len(pnl_arr)) if std > 0 else 0
        cum = np.cumsum(pnl_arr)
        peak_cum = np.maximum.accumulate(cum)
        dd_arr = peak_cum - cum
        max_dd = dd_arr.max() / (10000 + peak_cum.max()) * 100 if peak_cum.max() > 0 else 0
        all_outcomes = [b.won for b in scored_all]
        mls = max_loss_streak(all_outcomes)
        mws = max_win_streak(all_outcomes)
        print(f"  {'-'*66}")
        print(f"  {'PORTFOLIO':<12} {len(scored_all):5d} {wr:5.1f}% {total_pnl:+8.0f} "
              f"{roi:+6.1f}% {sharpe:7.3f} {max_dd:5.1f}% {mls:4d} {mws:4d}")

    # Inactive strategies
    inactive = [s for s in strategies_used if s not in strat_names]
    if inactive:
        print(f"\n  INACTIVE: {', '.join(inactive)}")

    # Overlap
    game_strats = {}
    for b in all_bets:
        game_strats.setdefault(b.game.replace(" (G2!)", ""), set()).add(b.strategy)
    overlaps = {g: s for g, s in game_strats.items() if len(s) > 1}
    if overlaps:
        print(f"\n  CROSS-STRATEGY OVERLAP: {len(overlaps)} games with 2+ strategies")

    # Danger zones (3+ consecutive losing days)
    daily_pnls = [(d.date, d.day_pnl) for d in daily_results if d.bets]
    if daily_pnls:
        streaks = []
        current = []
        for date, pnl in daily_pnls:
            if pnl < 0:
                current.append((date, pnl))
            else:
                if len(current) >= 3:
                    streaks.append(current[:])
                current = []
        if len(current) >= 3:
            streaks.append(current)
        if streaks:
            print(f"\n  DANGER ZONES (3+ consecutive losing days):")
            for streak in streaks:
                total = sum(p for _, p in streak)
                print(f"    {streak[0][0]} to {streak[-1][0]}: {len(streak)} days, {total:+.0f}")


def print_cross_month_comparison(month_results: dict):
    print(f"\n{'='*80}")
    print("  CROSS-MONTH COMPARISON")
    print(f"{'='*80}")
    print(f"\n  {'Month':<12} {'Bets':>5} {'Win%':>6} {'P&L':>8} {'ROI':>7} "
          f"{'Sharpe':>7} {'MaxDD':>6}")
    print(f"  {'-'*56}")

    for month in TARGET_MONTHS:
        if month not in month_results:
            continue
        bets = month_results[month]
        scored = [b for b in bets if b.won is not None]
        if not scored:
            print(f"  {month:<12}     0   --       --      --      --      --")
            continue
        wins = sum(1 for b in scored if b.won)
        total_pnl = sum(b.pnl for b in scored)
        total_stake = sum(b.stake for b in scored)
        wr = wins / len(scored) * 100
        roi = total_pnl / total_stake * 100 if total_stake > 0 else 0
        pnl_arr = np.array([b.pnl for b in scored])
        ev = pnl_arr.mean()
        std = pnl_arr.std(ddof=1) if len(pnl_arr) > 1 else 1
        sharpe = ev / std * np.sqrt(len(pnl_arr)) if std > 0 else 0
        cum = np.cumsum(pnl_arr)
        peak_cum = np.maximum.accumulate(cum)
        dd_arr = peak_cum - cum
        max_dd = dd_arr.max() / (10000 + peak_cum.max()) * 100 if peak_cum.max() > 0 else 0
        print(f"  {month:<12} {len(scored):5d} {wr:5.1f}% {total_pnl:+8.0f} "
              f"{roi:+6.1f}% {sharpe:7.3f} {max_dd:5.1f}%")


# ── Runner ───────────────────────────────────────────────────────────────


def _build_duel_context(model: str = "gpt-4o-mini") -> DuelContext:
    """Load v1 genomes and build all three duel engines."""
    logger.info("Loading expert genomes (v1, frozen)...")
    g = {
        "momentum": Genome.load(GENOMES_DIR / "momentum_v1.yaml"),
        "value": Genome.load(GENOMES_DIR / "value_v1.yaml"),
        "analyst": Genome.load(GENOMES_DIR / "analyst_v1.yaml"),
        "ou_pitching": Genome.load(GENOMES_DIR / "ou_pitching_v1.yaml"),
        "ou_scoring": Genome.load(GENOMES_DIR / "ou_scoring_v1.yaml"),
        "ou_analyst": Genome.load(GENOMES_DIR / "ou_analyst_v1.yaml"),
        "ou_over_offense": Genome.load(GENOMES_DIR / "ou_over_offense_v1.yaml"),
        "ou_over_fatigue": Genome.load(GENOMES_DIR / "ou_over_fatigue_v1.yaml"),
    }

    ml_engine = DuelEngine(
        LLMExpert(g["momentum"], model=model),
        LLMExpert(g["value"], model=model),
        analyst=LLMAnalyst(g["analyst"], model=model),
    )
    under_engine = DuelEngine(
        LLMExpert(g["ou_pitching"], model=model),
        LLMExpert(g["ou_scoring"], model=model),
        analyst=LLMAnalyst(g["ou_analyst"], model=model),
    )
    over_engine = DuelEngine(
        LLMExpert(g["ou_over_offense"], model=model),
        LLMExpert(g["ou_over_fatigue"], model=model),
        analyst=LLMAnalyst(g["ou_analyst"], model=model),
    )

    cache = LLMCache()
    logger.info(f"Duel engines ready (model={model}, 8 genomes, cache={cache.cache_dir})")
    return DuelContext(ml_engine, under_engine, over_engine, cache)


def run_month(master, series_list, p_under_threshold, month: str,
              strategy_filter: list[str] | None, dry_run: bool, base_stake: float,
              duel_ctx: DuelContext | None = None):
    """Run all strategies for a single month."""
    year, mon = int(month.split("-")[0]), int(month.split("-")[1])
    month_mask = (
        (pd.to_datetime(master["date"]).dt.year == year)
        & (pd.to_datetime(master["date"]).dt.month == mon)
    )
    month_data = master[month_mask].copy()
    if month_data.empty:
        print(f"\n  No data for {month}")
        return []

    dates = sorted(month_data["date"].unique())
    print(f"\n{'#'*80}")
    print(f"  DRESS REHEARSAL: {month} ({len(dates)} game days, {len(month_data)} games)")
    print(f"{'#'*80}")

    # Initialize strategies
    all_strategies = [
        S3Strategy(series_list, master, base_stake),
        RL1HStrategy(base_stake),
        RL2HStrategy(base_stake),
        UnderStrategy(p_under_threshold, base_stake, duel_ctx=duel_ctx),
        ExpansionUnderStrategy(p_under_threshold, base_stake, duel_ctx=duel_ctx),
        OverStrategy(0.52, base_stake, duel_ctx=duel_ctx),
        LLMMultiStrategy(base_stake, duel_ctx=duel_ctx),
        YRFIStrategy(base_stake),
    ]

    name_map = {
        "s3": "S3", "rl1h": "RL-1H", "rl2h": "RL-2H",
        "under": "UNDER", "under-exp": "UNDER-EXP", "over": "OVER",
        "llm": "LLM-MULTI", "yrfi": "YRFI",
    }

    if strategy_filter:
        active_names = {name_map.get(s.lower(), s.upper()) for s in strategy_filter}
        strategies = [s for s in all_strategies if s.name in active_names]
    else:
        strategies = all_strategies

    for s in strategies:
        s.reset()

    bankroll = 10000.0
    peak = bankroll
    daily_results = []
    all_strat_names = [s.name for s in strategies]
    all_outcomes: list[bool] = []  # running outcomes for streak tracking

    for date in dates:
        date_ts = pd.Timestamp(date)
        date_str = date_ts.strftime("%Y-%m-%d")
        fh = is_first_half(date_str)
        day_games = month_data[month_data["date"] == date]

        day_bets = []
        for strategy in strategies:
            if not strategy.is_active(mon, fh):
                continue
            if strategy.requires_llm and dry_run:
                n = strategy.count_candidates(day_games, date_str)
                if n > 0:
                    day_bets.append(Bet(
                        date=date_str, strategy=strategy.name,
                        market=f"[{n} candidates, LLM skipped]",
                        game="--", side="--", odds=0, stake=0,
                        won=None, pnl=0, meta={"dry_run": True},
                    ))
                continue
            bets = strategy.generate_bets(day_games, date_str)
            day_bets.extend(bets)

        day_pnl = sum(b.pnl for b in day_bets)
        day_stake = sum(b.stake for b in day_bets if not b.meta.get("dry_run"))
        bankroll += day_pnl
        peak = max(peak, bankroll)

        # Track outcomes for running streaks
        for b in day_bets:
            if b.won is not None:
                all_outcomes.append(b.won)

        daily = DailyResult(
            date=date_str, n_games=len(day_games),
            bets=day_bets, day_pnl=day_pnl, day_stake=day_stake,
        )
        daily_results.append(daily)
        mws = max_win_streak(all_outcomes)
        mls_run = max_loss_streak(all_outcomes)
        print_daily_card(daily, bankroll, peak, mws, mls_run)

    # Monthly summary
    print_monthly_summary(month, daily_results, all_strat_names)

    # Cache stats
    if duel_ctx:
        c = duel_ctx.cache
        print(f"\n  LLM Cache: {c.hits} hits, {c.misses} misses "
              f"({c.hits / max(c.hits + c.misses, 1) * 100:.0f}% hit rate)")

    return [b for d in daily_results for b in d.bets if not b.meta.get("dry_run")]


# ── CLI ──────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="MLB Dress Rehearsal: day-by-day portfolio simulation")
    parser.add_argument("--month", type=str, help="Target month YYYY-MM (e.g. 2024-06)")
    parser.add_argument("--all-months", action="store_true",
                        help="Run all 3 target months: Sep 2023, Jun 2024, Apr 2025")
    parser.add_argument("--dry-run", action="store_true",
                        help="ML-only strategies run fully; LLM strategies log candidate counts")
    parser.add_argument("--strategies", type=str, default=None,
                        help="Comma-separated: s3,rl1h,rl2h,under,over,llm,yrfi")
    parser.add_argument("--stake", type=float, default=100.0,
                        help="Base stake per bet in dollars (default: 100)")
    parser.add_argument("--model", type=str, default="gpt-4o-mini",
                        help="LLM model for duel strategies (default: gpt-4o-mini)")
    args = parser.parse_args()

    if not args.month and not args.all_months:
        parser.error("Specify --month YYYY-MM or --all-months")

    months = TARGET_MONTHS if args.all_months else [args.month]
    strat_filter = args.strategies.split(",") if args.strategies else None

    # Build data once
    master, series_list, p_under_threshold = build_master_data()

    # Build duel context (once for all months, genomes frozen at v1)
    duel_ctx = None
    if not args.dry_run:
        duel_ctx = _build_duel_context(model=args.model)

    # Run each month
    month_results = {}
    for month in months:
        bets = run_month(master, series_list, p_under_threshold, month,
                         strat_filter, args.dry_run, args.stake, duel_ctx)
        month_results[month] = bets

    # Cross-month comparison
    if len(months) > 1:
        print_cross_month_comparison(month_results)


if __name__ == "__main__":
    main()
