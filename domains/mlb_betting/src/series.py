"""Series identification and dogon (martingale) strategy for MLB betting.

MLB teams play in series of 2-4 consecutive games against the same opponent.
Strategy: bet on the favorite to win at least 1 of the first 2 games.
- Game 1: bet to win $TARGET_PROFIT
- Game 2 (if G1 lost): bet to recover G1 loss + win $TARGET_PROFIT
- Game 3+: stop (no further dogon)

Key edge: favorites win ~57% of games. Probability of losing both G1 and G2 ≈ 18%.
With proper selection (RPI, form, etc.), this can be reduced further.
"""

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from src.data_loader import american_to_decimal, american_to_implied_prob

logger = logging.getLogger(__name__)


# ── Data Structures ──────────────────────────────────────────────────────


@dataclass
class SeriesGame:
    """A single game within a series."""

    game_idx: int  # Index in the original DataFrame
    date: str
    game_in_series: int  # 1, 2, 3, or 4
    home_team: str
    away_team: str
    home_win: bool
    home_final: int  # Optional for pre-game matrices; defaulted to 0 if missing
    away_final: int  # Optional for pre-game matrices; defaulted to 0 if missing
    home_close_ml: float
    away_close_ml: float
    home_decimal_odds: float
    away_decimal_odds: float
    home_implied_prob: float
    away_implied_prob: float
    row_id: str | None = None  # Stable join key (Stage1/Stage2). Optional.


@dataclass
class Series:
    """A series of consecutive games between the same two teams."""

    season: int
    home_team: str  # Team that's home for majority of series (or first game)
    away_team: str
    start_date: str
    games: list[SeriesGame] = field(default_factory=list)

    @property
    def length(self) -> int:
        return len(self.games)

    @property
    def series_key(self) -> str:
        return f"{self.season}_{self.start_date}_{self.home_team}_{self.away_team}"


@dataclass
class BetResult:
    """Result of a single bet within a series dogon."""

    series_key: str
    game_in_series: int
    date: str
    bet_on: str  # Team name we're betting on
    bet_side: str  # 'home' or 'away'
    decimal_odds: float
    stake: float
    won: bool
    pnl: float  # Profit/loss for this bet
    is_dogon: bool  # True if this is game 2 (recovery bet)


@dataclass
class SeriesResult:
    """Complete result for a series dogon attempt."""

    series_key: str
    season: int
    start_date: str
    favorite: str  # Team we bet on
    underdog: str
    n_bets: int
    total_stake: float
    total_pnl: float
    won: bool  # Did we end up profitable?
    bets: list[BetResult] = field(default_factory=list)


# ── Series Identification ────────────────────────────────────────────────


def identify_series(games: pd.DataFrame) -> list[Series]:
    """Identify MLB series from game-level DataFrame.

    A series = consecutive games between the same two teams in the same season.
    We group by (season, matchup_key) and split on date gaps > 3 days.
    """
    if "matchup_key" not in games.columns:
        games = games.copy()
        games["matchup_key"] = games.apply(
            lambda r: "_".join(sorted([str(r["away_team"]), str(r["home_team"])])),
            axis=1,
        )

    # Filter out rows with NaN in critical fields before processing
    required_cols = ["home_final", "away_final", "home_close_ml", "away_close_ml", "home_win"]
    existing_required = [c for c in required_cols if c in games.columns]
    games_clean = games.dropna(subset=existing_required).copy()
    if len(games_clean) < len(games):
        n_dropped = len(games) - len(games_clean)
        logger.warning(f"Dropped {n_dropped} rows with NaN in critical fields")

    all_series: list[Series] = []

    for (season, matchup), grp in games_clean.groupby(["season", "matchup_key"]):
        grp = grp.sort_values("date").reset_index()
        dates = pd.to_datetime(grp["date"])
        gaps = dates.diff().dt.days

        # Split into sub-series where gap > 3 days
        current_games: list[SeriesGame] = []
        series_start_row = None

        for i, (_, row) in enumerate(grp.iterrows()):
            # New series if first game or gap > 3 days
            if i == 0 or (gaps.iloc[i] is not None and gaps.iloc[i] > 3):
                # Save previous series if 2+ games
                if len(current_games) >= 2 and series_start_row is not None:
                    s = Series(
                        season=int(season),
                        home_team=series_start_row["home_team"],
                        away_team=series_start_row["away_team"],
                        start_date=str(series_start_row["date"]),
                        games=current_games,
                    )
                    all_series.append(s)
                current_games = []
                series_start_row = row

            # Build SeriesGame
            home_dec = (
                row["home_decimal_odds"]
                if "home_decimal_odds" in row.index and not pd.isna(row.get("home_decimal_odds"))
                else american_to_decimal(row["home_close_ml"])
            )
            away_dec = (
                row["away_decimal_odds"]
                if "away_decimal_odds" in row.index and not pd.isna(row.get("away_decimal_odds"))
                else american_to_decimal(row["away_close_ml"])
            )
            home_imp = (
                row["home_implied_prob"]
                if "home_implied_prob" in row.index and not pd.isna(row.get("home_implied_prob"))
                else american_to_implied_prob(row["home_close_ml"])
            )
            away_imp = (
                row["away_implied_prob"]
                if "away_implied_prob" in row.index and not pd.isna(row.get("away_implied_prob"))
                else american_to_implied_prob(row["away_close_ml"])
            )

            # Stage1 matrix parquet intentionally drops finals/innings for anti-leak,
            # but series identification and dogon only need odds + win outcome.
            home_final = 0
            away_final = 0
            if "home_final" in row.index and not pd.isna(row.get("home_final")):
                home_final = int(row["home_final"])
            if "away_final" in row.index and not pd.isna(row.get("away_final")):
                away_final = int(row["away_final"])

            row_id = None
            if "row_id" in row.index and not pd.isna(row.get("row_id")):
                row_id = str(row["row_id"])

            game = SeriesGame(
                game_idx=row["index"] if "index" in row.index else 0,
                row_id=row_id,
                date=str(row["date"]),
                game_in_series=len(current_games) + 1,
                home_team=row["home_team"],
                away_team=row["away_team"],
                home_win=bool(row["home_win"]),
                home_final=home_final,
                away_final=away_final,
                home_close_ml=float(row["home_close_ml"]),
                away_close_ml=float(row["away_close_ml"]),
                home_decimal_odds=home_dec,
                away_decimal_odds=away_dec,
                home_implied_prob=home_imp,
                away_implied_prob=away_imp,
            )
            current_games.append(game)

        # Don't forget last sub-series in this matchup group
        if len(current_games) >= 2 and series_start_row is not None:
            s = Series(
                season=int(season),
                home_team=series_start_row["home_team"],
                away_team=series_start_row["away_team"],
                start_date=str(series_start_row["date"]),
                games=current_games,
            )
            all_series.append(s)

    # Sort by date for consistent output
    all_series.sort(key=lambda s: (s.season, s.start_date))

    logger.info(
        f"Identified {len(all_series)} series "
        f"(avg {np.mean([s.length for s in all_series]):.1f} games)"
    )
    return all_series


def series_summary(series_list: list[Series]) -> pd.DataFrame:
    """Summary statistics of identified series."""
    data = []
    for s in series_list:
        data.append(
            {
                "season": s.season,
                "start_date": s.start_date,
                "home_team": s.home_team,
                "away_team": s.away_team,
                "length": s.length,
            }
        )
    df = pd.DataFrame(data)
    return df


# ── Favorite Selection ───────────────────────────────────────────────────


def select_series_favorite(
    series: Series,
    method: str = "game1_odds",
) -> tuple[str, str] | None:
    """Determine which team is the favorite for the series.

    Args:
        series: The series to analyze
        method: Selection method:
            - 'game1_odds': Use Game 1 closing odds
            - 'series_avg_odds': Average implied prob across all games
            - 'home_team': Always pick the home team (of game 1)

    Returns:
        (favorite_team, underdog_team) or None if no clear favorite.
    """
    if not series.games:
        return None

    g1 = series.games[0]

    if method == "game1_odds":
        # Favorite = team with higher implied probability in game 1
        if g1.home_implied_prob > g1.away_implied_prob:
            return (g1.home_team, g1.away_team)
        elif g1.away_implied_prob > g1.home_implied_prob:
            return (g1.away_team, g1.home_team)
        return None  # Even odds — skip

    elif method == "series_avg_odds":
        # Average implied probability across all games in series
        home_probs = []
        away_probs = []
        for g in series.games:
            if g.home_team == series.home_team:
                home_probs.append(g.home_implied_prob)
                away_probs.append(g.away_implied_prob)
            else:
                # Teams swapped home/away
                home_probs.append(g.away_implied_prob)
                away_probs.append(g.home_implied_prob)
        avg_home = np.mean(home_probs) if home_probs else 0.5
        avg_away = np.mean(away_probs) if away_probs else 0.5
        if avg_home > avg_away:
            return (series.home_team, series.away_team)
        elif avg_away > avg_home:
            return (series.away_team, series.home_team)
        return None

    elif method == "home_team":
        return (g1.home_team, g1.away_team)

    else:
        raise ValueError(f"Unknown selection method: {method}")


# ── Dogon (Martingale) Engine ────────────────────────────────────────────


def calc_stake_for_profit(target_profit: float, decimal_odds: float) -> float:
    """Calculate stake needed to achieve target profit at given odds.

    stake * (odds - 1) = target_profit
    stake = target_profit / (odds - 1)
    """
    if decimal_odds <= 1.0:
        return 0.0
    return target_profit / (decimal_odds - 1)


def run_series_dogon(
    series: Series,
    favorite: str,
    target_profit: float = 100.0,
    max_games: int = 2,
) -> SeriesResult:
    """Execute dogon strategy on a single series.

    Args:
        series: The series to bet on
        favorite: Team name to bet on
        target_profit: Fixed profit target per series ($100 default)
        max_games: Maximum games to bet on (1=no dogon, 2=one recovery, 3=two)

    Returns:
        SeriesResult with all bet details
    """
    underdog = series.away_team if favorite == series.home_team else series.home_team

    result = SeriesResult(
        series_key=series.series_key,
        season=series.season,
        start_date=series.start_date,
        favorite=favorite,
        underdog=underdog,
        n_bets=0,
        total_stake=0.0,
        total_pnl=0.0,
        won=False,
    )

    cumulative_loss = 0.0

    for i, game in enumerate(series.games):
        if i >= max_games:
            break

        # Determine our odds for this game
        if favorite == game.home_team:
            our_odds = game.home_decimal_odds
            our_win = game.home_win
            bet_side = "home"
        else:
            our_odds = game.away_decimal_odds
            our_win = not game.home_win
            bet_side = "away"

        # Calculate stake
        if i == 0:
            # Game 1: stake to win target_profit
            stake = calc_stake_for_profit(target_profit, our_odds)
        else:
            # Game 2+: stake to recover losses + win target_profit
            needed = cumulative_loss + target_profit
            stake = calc_stake_for_profit(needed, our_odds)

        # Calculate P&L
        if our_win:
            pnl = stake * (our_odds - 1)
        else:
            pnl = -stake

        bet = BetResult(
            series_key=series.series_key,
            game_in_series=i + 1,
            date=game.date,
            bet_on=favorite,
            bet_side=bet_side,
            decimal_odds=our_odds,
            stake=stake,
            won=our_win,
            pnl=pnl,
            is_dogon=i > 0,
        )
        result.bets.append(bet)
        result.n_bets += 1
        result.total_stake += stake
        result.total_pnl += pnl

        if our_win:
            # Won — series dogon complete
            result.won = True
            break
        else:
            # Lost — accumulate loss for dogon calculation
            cumulative_loss += stake

    return result


# ── Backtest Runner ──────────────────────────────────────────────────────


def backtest_series_dogon(
    games: pd.DataFrame,
    target_profit: float = 100.0,
    max_games: int = 2,
    selection_method: str = "game1_odds",
    min_implied_prob: float = 0.0,
    max_implied_prob: float = 1.0,
    exclude_colorado: bool = True,
    exclude_september: bool = True,
    min_games_in_series: int = 2,
) -> tuple[list[SeriesResult], pd.DataFrame]:
    """Run full series dogon backtest.

    Args:
        games: Game-level DataFrame from data_loader
        target_profit: Fixed profit target per series
        max_games: Max games to bet in a series (1-3)
        selection_method: How to pick favorite ('game1_odds', 'series_avg_odds')
        min_implied_prob: Min implied probability for favorite (filter)
        max_implied_prob: Max implied probability (avoid extreme favorites)
        exclude_colorado: Skip series involving Colorado
        exclude_september: Skip September series
        min_games_in_series: Min series length to consider

    Returns:
        (list of SeriesResult, summary DataFrame)
    """
    # Identify all series
    all_series = identify_series(games)
    logger.info(f"Total series: {len(all_series)}")

    results: list[SeriesResult] = []
    skipped = {"colorado": 0, "september": 0, "no_favorite": 0, "prob_filter": 0, "short": 0}

    for series in all_series:
        # Filter: series length
        if series.length < min_games_in_series:
            skipped["short"] += 1
            continue

        # Filter: Colorado
        if exclude_colorado and (
            "COL" in (series.home_team, series.away_team)
        ):
            skipped["colorado"] += 1
            continue

        # Filter: September
        if exclude_september and series.games:
            first_date = pd.Timestamp(series.games[0].date)
            if first_date.month == 9:
                skipped["september"] += 1
                continue

        # Select favorite
        pick = select_series_favorite(series, method=selection_method)
        if pick is None:
            skipped["no_favorite"] += 1
            continue

        favorite, _underdog = pick

        # Filter: implied probability range
        g1 = series.games[0]
        if favorite == g1.home_team:
            fav_prob = g1.home_implied_prob
        else:
            fav_prob = g1.away_implied_prob

        if fav_prob < min_implied_prob or fav_prob > max_implied_prob:
            skipped["prob_filter"] += 1
            continue

        # Run dogon
        result = run_series_dogon(series, favorite, target_profit, max_games)
        results.append(result)

    # Build summary
    logger.info(
        f"Backtest: {len(results)} series bet on, "
        f"skipped: {skipped}"
    )

    summary = build_backtest_summary(results)
    return results, summary


def build_backtest_summary(results: list[SeriesResult]) -> pd.DataFrame:
    """Build summary DataFrame from backtest results."""
    if not results:
        return pd.DataFrame()

    data = []
    for r in results:
        data.append(
            {
                "series_key": r.series_key,
                "season": r.season,
                "start_date": r.start_date,
                "favorite": r.favorite,
                "underdog": r.underdog,
                "n_bets": r.n_bets,
                "total_stake": r.total_stake,
                "total_pnl": r.total_pnl,
                "won": r.won,
                "max_exposure": max(b.stake for b in r.bets) if r.bets else 0,
                "g1_odds": r.bets[0].decimal_odds if r.bets else 0,
                "g1_won": r.bets[0].won if r.bets else False,
                "needed_dogon": r.n_bets > 1,
                "g2_odds": r.bets[1].decimal_odds if len(r.bets) > 1 else None,
                "g2_stake": r.bets[1].stake if len(r.bets) > 1 else None,
            }
        )

    return pd.DataFrame(data)


def print_backtest_report(results: list[SeriesResult], summary: pd.DataFrame) -> None:
    """Print formatted backtest report."""
    if summary.empty:
        print("No results to report.")
        return

    n = len(summary)
    wins = summary["won"].sum()
    losses = n - wins

    total_pnl = summary["total_pnl"].sum()
    total_stake = summary["total_stake"].sum()
    roi = total_pnl / total_stake if total_stake > 0 else 0

    g1_wins = summary["g1_won"].sum()
    needed_dogon = summary["needed_dogon"].sum()
    dogon_won = summary[summary["needed_dogon"]]["won"].sum()
    both_lost = losses  # If series lost, both games were lost

    max_exposure = summary["max_exposure"].max()
    avg_exposure = summary["max_exposure"].mean()

    print("=" * 70)
    print("SERIES DOGON BACKTEST REPORT")
    print("=" * 70)
    print(f"\nSeries bet on: {n}")
    print(f"Won: {wins} ({wins / n:.1%})")
    print(f"Lost: {losses} ({losses / n:.1%})")
    print()
    print(f"Game 1 wins: {g1_wins} ({g1_wins / n:.1%})")
    print(f"Needed dogon (G1 lost): {int(needed_dogon)} ({needed_dogon / n:.1%})")
    if needed_dogon > 0:
        print(
            f"  Dogon recovered (G2 won): {int(dogon_won)} "
            f"({dogon_won / needed_dogon:.1%} of dogons)"
        )
        print(
            f"  Both lost (series lost): {int(needed_dogon - dogon_won)} "
            f"({(needed_dogon - dogon_won) / needed_dogon:.1%} of dogons)"
        )
    print()
    print(f"Total P&L: ${total_pnl:,.0f}")
    print(f"Total staked: ${total_stake:,.0f}")
    print(f"ROI: {roi:.2%}")
    print()
    print(f"Max single bet exposure: ${max_exposure:,.0f}")
    print(f"Avg max exposure per series: ${avg_exposure:,.0f}")

    # By season
    print("\nBy season:")
    by_season = summary.groupby("season").agg(
        series=("won", "count"),
        wins=("won", "sum"),
        pnl=("total_pnl", "sum"),
        staked=("total_stake", "sum"),
    )
    by_season["win_rate"] = by_season["wins"] / by_season["series"]
    by_season["roi"] = by_season["pnl"] / by_season["staked"]

    for season, row in by_season.iterrows():
        print(
            f"  {int(season)}: {int(row['series'])} series, "
            f"{row['win_rate']:.1%} WR, "
            f"P&L ${row['pnl']:+,.0f}, "
            f"ROI {row['roi']:+.1%}"
        )
