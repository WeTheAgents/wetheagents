"""Generate today's MLB betting picks for the 2026 season.

Implements the audit plan §10 contract. Loads the unfiltered feature
pipeline (build_all_features — NOT build_spec_features which drops
April), runs the live production strategies, deduplicates overlap,
optionally fetches live Polymarket prices, computes Kelly stake
fractions, applies overlap-aware stake bonuses, and writes the picks
to disk for manual operator review.

Decision matrix from audit plan §9:
  - Tier 3 uses ip_per_start_short (Decision §9.1)
  - Polymarket prices are live where available (Decision §9.2)
  - YRFI is deferred — no saved CatBoost model (Decision §9.3)
  - Pick approval is fully manual — generator does NOT place orders (§9.4)

Usage:
  python scripts/generate_picks_2026.py
  python scripts/generate_picks_2026.py --date 2026-04-12
  python scripts/generate_picks_2026.py --tiers tier1_bullpen_day,tier2_fatigue_gap
  python scripts/generate_picks_2026.py --no-poly        # skip Polymarket fetch
  python scripts/generate_picks_2026.py --dry-run        # no file writes
  python scripts/generate_picks_2026.py --kelly 0.25     # Kelly fraction (default 0.25)

Output:
  picks/picks_YYYY-MM-DD.json   — full pick records for the day
  picks/pick_log.jsonl          — append-only ledger entry per pick
  stdout                        — summary table for the operator
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import warnings
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

# Add script dir + project root to path
SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parent
for _path in (SCRIPT_DIR, BASE_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

warnings.filterwarnings("ignore")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

PICKS_DIR = BASE_DIR / "picks"
PICK_LOG = PICKS_DIR / "pick_log.jsonl"
ALERTS_PATH = PICKS_DIR / "ALERTS.md"

# Confidence shrinkage on the historical p — see plans/§11.1 #14.
# Bakes a 5% margin of safety into Kelly so we don't over-bet a sample mean.
HISTORICAL_P_SHRINK = 0.95

# Drop picks below this stake fraction (Polymarket has minimum bet sizes,
# operator wastes time on tiny bets). See plans/§11.1 #13.
MIN_STAKE_FRACTION = 0.005


# Tier priority for overlap dedup (lower index = higher priority).
TIER_PRIORITY = [
    "tier1_bullpen_day",
    "tier1_bullpen_day_flipped",
    "tier4_ml_depth_load",
    "tier5_ml_obp_recovery",
    "tier3_pitcher_advantage",
    "tier2_fatigue_gap",
    "fav_rl",
    "under_totals_power",
    "under_totals",
    # OVER market is orthogonal to ML/RL (different market key on the same
    # game), so these never collide via dedup; listed last for completeness.
    "over_bullpen_mismatch_power",
    "over_bullpen_mismatch",
]

OVERLAP_STAKE_PAIR = frozenset({"tier4_ml_depth_load", "tier5_ml_obp_recovery"})
OVERLAP_STAKE_MULTIPLIER = 1.5
OVERLAP_STAKE_REASON = "double_confirmed_ml_baskets"

TIER5_FIELDING_OAA_Q10_THRESHOLD = -42.7
TIER5_FIELDING_FLAG_PASS = "tier5_oaa_q10_pass"
TIER5_FIELDING_FLAG_MISS = "tier5_oaa_q10_miss"
TIER5_FIELDING_FLAG_UNKNOWN = "tier5_oaa_q10_unknown"

DEFAULT_TIERS = [
    "tier1_bullpen_day",
    "tier4_ml_depth_load",
    "tier5_ml_obp_recovery",
    "tier3_pitcher_advantage",
    "tier2_fatigue_gap",
    "under_totals",
    "over_bullpen_mismatch",
]
DEFAULT_TIERS_CSV = ",".join(DEFAULT_TIERS)


# ---------------------------------------------------------------------------
# Pick → JSON serialization
# ---------------------------------------------------------------------------


@dataclass
class EnrichedPick:
    """A Pick after Polymarket lookup, edge calculation, and Kelly sizing.

    This is the JSON shape that lands in picks_YYYY-MM-DD.json.
    Schema v3 adds overlap-aware staking fields for the Sess 41 ML baskets.
    """

    pick_id: str
    date: str
    away: str
    home: str
    market: str
    side: str
    tier: str
    also_qualified: list[str]
    historical_p: float
    shrunk_p: float
    ref_odds_espn: float | None
    pick_line: float | None
    polymarket_price: float | None
    polymarket_decimal: float | None
    polymarket_event_id: str | None
    polymarket_market_id: str | None
    polymarket_condition_id: str | None
    polymarket_token_id: str | None
    polymarket_slug: str | None
    polymarket_line: float | None
    polymarket_best_bid: float | None
    polymarket_best_ask: float | None
    polymarket_accepting_orders: bool | None
    status: str  # "ok" | "poly_unavailable" | "not_on_polymarket" | "no_ref_odds"
    live_edge_pct: float | None
    kelly_fraction: float | None
    stake_fraction_base: float | None
    stake_multiplier: float
    stake_multiplier_reason: str | None
    stake_fraction: float | None
    # Target pricing — what odds to wait for (L1 sweet-spot targeting).
    # target_min: breakeven odds (edge=0); below this, DON'T bet.
    # target_sweet: odds where edge = --target-edge (default 20%); the wait-for price.
    # kelly_at_sweet: Kelly fraction IF filled at target_sweet odds.
    target_min_decimal: float | None
    target_sweet_decimal: float | None
    kelly_at_sweet: float | None
    operator_flags: list[str]
    reason: str
    feature_snapshot: dict[str, Any]
    generated_at: str
    schema_version: int = 5


def kelly(p: float, decimal_odds: float) -> float:
    """Standard Kelly fraction. Returns 0 if no positive expectation.

    p          — true win probability
    decimal_odds — payout multiplier (1.91 = bet 1 to win 0.91)
    """
    if decimal_odds <= 1.0 or p <= 0:
        return 0.0
    b = decimal_odds - 1.0
    raw = (p * (b + 1) - 1) / b
    return max(0.0, raw)


# ---------------------------------------------------------------------------
# Polymarket lookup with graceful fallback
# ---------------------------------------------------------------------------


# Polymarket reports full team names ("Boston Red Sox"). We need to map
# them to our 3-letter codes for the join. This table covers all 30 teams.
POLY_NAME_TO_CODE = {
    "arizona diamondbacks": "ARI",
    "atlanta braves": "ATL",
    "baltimore orioles": "BAL",
    "boston red sox": "BOS",
    "chicago cubs": "CHC",
    "chicago white sox": "CHW",
    "cincinnati reds": "CIN",
    "cleveland guardians": "CLE",
    "colorado rockies": "COL",
    "detroit tigers": "DET",
    "houston astros": "HOU",
    "kansas city royals": "KCR",
    "los angeles angels": "LAA",
    "los angeles dodgers": "LAD",
    "miami marlins": "MIA",
    "milwaukee brewers": "MIL",
    "minnesota twins": "MIN",
    "new york mets": "NYM",
    "new york yankees": "NYY",
    "athletics": "OAK",
    "oakland athletics": "OAK",
    "sacramento athletics": "OAK",
    "philadelphia phillies": "PHI",
    "pittsburgh pirates": "PIT",
    "san diego padres": "SDP",
    "san francisco giants": "SFG",
    "seattle mariners": "SEA",
    "st. louis cardinals": "STL",
    "st louis cardinals": "STL",
    "tampa bay rays": "TBR",
    "texas rangers": "TEX",
    "toronto blue jays": "TOR",
    "washington nationals": "WSN",
}


def _normalize_poly_team(name: str) -> str | None:
    """Look up a Polymarket full team name → 3-letter code. None if unknown."""
    return POLY_NAME_TO_CODE.get(name.strip().lower())


def fetch_polymarket_prices(target_date: date) -> dict[tuple[str, str], dict]:
    """Return {(away_code, home_code): {markets: {...}, event_id: ...}}.

    Failures are logged and return an empty dict — picks are still emitted
    with status="poly_unavailable" so the operator can triage.
    """
    try:
        from src.polymarket_client import fetch_todays_games  # noqa: PLC0415

        events = fetch_todays_games()
    except Exception as e:  # noqa: BLE001
        logger.warning("Polymarket fetch failed: %s", e)
        return {}

    out: dict[tuple[str, str], dict] = {}
    for ev in events:
        if ev.event_date != target_date:
            continue
        away = _normalize_poly_team(ev.away_team)
        home = _normalize_poly_team(ev.home_team)
        if not away or not home:
            logger.warning(
                "Polymarket team unmapped: %r vs %r — skipping",
                ev.away_team,
                ev.home_team,
            )
            continue
        markets: dict[str, dict] = {}
        for m in ev.markets:
            markets.setdefault(m.market_type, []).append(
                {
                    "event_id": ev.event_id,
                    "slug": ev.slug,
                    "market_id": m.market_id,
                    "condition_id": m.condition_id,
                    "token_ids": list(m.clob_token_ids),
                    "question": m.question,
                    "outcomes": list(m.outcomes),
                    "outcome_prices": list(m.outcome_prices),
                    "line": m.line,
                    "best_bid": m.best_bid,
                    "best_ask": m.best_ask,
                    "liquidity": m.liquidity,
                    "accepting_orders": m.accepting_orders,
                }
            )
        out[(away, home)] = {"event_id": ev.event_id, "markets": markets}
    return out


def _market_quote_payload(
    market: dict,
    *,
    outcome_index: int,
) -> dict | None:
    outcomes = market.get("outcomes", [])
    prices = market.get("outcome_prices", [])
    token_ids = market.get("token_ids", [])
    if outcome_index < 0 or outcome_index >= len(outcomes) or outcome_index >= len(prices):
        return None
    try:
        price = float(prices[outcome_index])
    except (TypeError, ValueError):
        price = None
    token_id = None
    if outcome_index < len(token_ids):
        token_id = str(token_ids[outcome_index]) or None
    return {
        "price": price,
        "event_id": market.get("event_id"),
        "market_id": market.get("market_id"),
        "condition_id": market.get("condition_id"),
        "token_id": token_id,
        "slug": market.get("slug"),
        "line": market.get("line"),
        "best_bid": market.get("best_bid"),
        "best_ask": market.get("best_ask"),
        "accepting_orders": market.get("accepting_orders"),
        "outcome_name": outcomes[outcome_index],
    }


def _polymarket_quote_for(
    poly_data: dict | None,
    market: str,
    side: str,
    away: str,
    home: str,
    market_line: float | None = None,
) -> dict | None:
    """Return matched Polymarket quote metadata for our pick side, or None.

    market is one of: "ML_dog", "RL_+1.5", "RL_-1.5".
    side is "away" or "home" or totals side "over"/"under".

    Polymarket lists outcomes as full team names. We match by mapping each
    outcome name back to a 3-letter code. For totals, the outcomes are
    "Over" / "Under" (or a text variant containing those labels).
    """
    if poly_data is None:
        return None
    markets = poly_data.get("markets", {})

    if market.startswith("ML"):
        ml_list = markets.get("moneyline") or []
        if not ml_list:
            return None
        m = ml_list[0]  # any one moneyline market is fine
        return _outcome_quote_for_side(m, side, away, home)

    if market.startswith("RL"):
        # Spread markets — pick the one matching the line we want.
        # market = "RL_+1.5" → we want the +1.5 line; side identifies which team.
        sign = -1.5 if "-1.5" in market else 1.5
        sp_list = markets.get("spread") or []
        for m in sp_list:
            line = m.get("line")
            if line is None:
                continue
            # Polymarket may quote the line from either team's perspective.
            # We match by absolute value (1.5) and let the side resolve direction.
            if abs(float(line) - 1.5) < 0.01 or abs(float(line) - (-1.5)) < 0.01:
                quote = _outcome_quote_for_side(m, side, away, home)
                if quote is not None:
                    return quote
        return None

    if market == "O/U":
        totals_list = markets.get("total") or []
        if not totals_list:
            return None
        return _outcome_quote_for_total(totals_list, side, market_line=market_line)

    return None


def _outcome_quote_for_side(
    market: dict, side: str, away: str, home: str
) -> dict | None:
    """Match a Polymarket outcome to our away/home side and return quote metadata."""
    outcomes = market.get("outcomes", [])
    prices = market.get("outcome_prices", [])
    if len(outcomes) != len(prices):
        return None
    target_code = away if side == "away" else home
    for idx, name in enumerate(outcomes):
        code = _normalize_poly_team(name)
        if code == target_code:
            return _market_quote_payload(market, outcome_index=idx)
    return None


def _outcome_quote_for_total(
    markets: list[dict],
    side: str,
    *,
    market_line: float | None,
) -> dict | None:
    """Match a totals market by line and side."""
    normalized_side = side.strip().lower()
    for market in markets:
        line = market.get("line")
        if market_line is not None:
            if line is None:
                continue
            try:
                if abs(float(line) - float(market_line)) > 0.01:
                    continue
            except (TypeError, ValueError):
                continue
        outcomes = market.get("outcomes", [])
        for idx, name in enumerate(outcomes):
            label = str(name).strip().lower()
            if label == normalized_side or label.startswith(normalized_side):
                return _market_quote_payload(market, outcome_index=idx)
    return None


# ---------------------------------------------------------------------------
# Dedup overlap (Tier 1 wins)
# ---------------------------------------------------------------------------


def dedup_overlapping_picks(picks: list) -> list:
    """If multiple tiers fire on the same (away, home, market, side), keep
    the highest-priority tier and record the others in `also_qualified`.

    Picks list is modified in place: kept picks gain `also_qualified` info.
    """
    if not picks:
        return []

    # Group by (away, home, market, side)
    groups: dict[tuple, list] = {}
    for p in picks:
        key = (p.away, p.home, p.market, p.side)
        groups.setdefault(key, []).append(p)

    kept = []
    for _, group in groups.items():
        if len(group) == 1:
            kept.append(group[0])
            continue
        # Sort by tier priority (lower index = higher priority).
        group.sort(
            key=lambda p: TIER_PRIORITY.index(p.tier)
            if p.tier in TIER_PRIORITY
            else len(TIER_PRIORITY)
        )
        winner = group[0]
        winner.also_qualified = [p.tier for p in group[1:]]
        kept.append(winner)
    return kept


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _target_prices(shrunk_p: float, target_edge: float) -> tuple[float | None, float | None]:
    """Compute target decimal odds for breakeven and sweet-spot edge.

    target_min  = 1 / shrunk_p  (edge = 0, DON'T bet below this)
    target_sweet = 1 / (shrunk_p - target_edge)  (where edge = target_edge)

    Returns (None, None) if shrunk_p <= 0 or denominator non-positive.
    """
    if shrunk_p <= 0:
        return None, None
    target_min = 1.0 / shrunk_p
    sweet_denom = shrunk_p - target_edge
    target_sweet = (1.0 / sweet_denom) if sweet_denom > 0.01 else None
    return target_min, target_sweet


def overlap_stake_bonus(pick) -> tuple[float, str | None]:
    """Return stake multiplier for post-dedup overlap-confirmed picks."""
    qualified = {pick.tier, *pick.also_qualified}
    if OVERLAP_STAKE_PAIR.issubset(qualified):
        return OVERLAP_STAKE_MULTIPLIER, OVERLAP_STAKE_REASON
    return 1.0, None


def add_tier5_operator_fielding_signal(enriched: pd.DataFrame) -> pd.DataFrame:
    """Attach prior-season OAA edge support for the tier5 operator flag.

    This is advisory only: it does not change strategy selection or stake.
    It mirrors the research signal that improved tier5 in the prior-season
    scan: away_oaa_edge_prev >= q10 threshold (-42.7).
    """
    from _fielding_scan_common import load_fielding_snapshots  # noqa: PLC0415

    fielding = load_fielding_snapshots()
    home = fielding.rename(
        columns={
            "season_target": "season",
            "team": "home_team",
            "oaa_prev": "home_oaa_prev",
        }
    )[["season", "home_team", "home_oaa_prev"]]
    away = fielding.rename(
        columns={
            "season_target": "season",
            "team": "away_team",
            "oaa_prev": "away_oaa_prev",
        }
    )[["season", "away_team", "away_oaa_prev"]]
    out = enriched.merge(home, on=["season", "home_team"], how="left").merge(
        away,
        on=["season", "away_team"],
        how="left",
    )
    out["tier5_fielding_oaa_edge_prev"] = (
        out["away_oaa_prev"] - out["home_oaa_prev"]
    )
    out["tier5_fielding_oaa_q10_pass"] = pd.Series(
        pd.NA,
        index=out.index,
        dtype="boolean",
    )
    valid = out["tier5_fielding_oaa_edge_prev"].notna()
    out.loc[valid, "tier5_fielding_oaa_q10_pass"] = (
        out.loc[valid, "tier5_fielding_oaa_edge_prev"]
        >= TIER5_FIELDING_OAA_Q10_THRESHOLD
    )
    return out


def build_tier5_operator_lookup(
    enriched: pd.DataFrame,
    target: date,
) -> dict[tuple[str, str], dict[str, Any]]:
    """Return target-day tier5 fielding support keyed by (away, home)."""
    day = enriched[enriched["date"].dt.date == target].copy()
    if day.empty:
        return {}
    cols = [
        "away_team",
        "home_team",
        "tier5_fielding_oaa_edge_prev",
        "tier5_fielding_oaa_q10_pass",
    ]
    rows = day[cols].drop_duplicates(subset=["away_team", "home_team"])
    lookup: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows.itertuples(index=False):
        flag = row.tier5_fielding_oaa_q10_pass
        if pd.isna(flag):
            flag_value = None
        else:
            flag_value = bool(flag)
        lookup[(row.away_team, row.home_team)] = {
            "tier5_fielding_oaa_edge_prev": (
                None
                if pd.isna(row.tier5_fielding_oaa_edge_prev)
                else float(row.tier5_fielding_oaa_edge_prev)
            ),
            "tier5_fielding_oaa_q10_threshold": TIER5_FIELDING_OAA_Q10_THRESHOLD,
            "tier5_fielding_oaa_q10_pass": flag_value,
        }
    return lookup


def pick_has_tier5_context(pick) -> bool:
    qualified = {pick.tier, *pick.also_qualified}
    return "tier5_ml_obp_recovery" in qualified


def tier5_operator_payload(
    pick,
    operator_context: dict[str, Any] | None,
) -> tuple[list[str], dict[str, Any]]:
    if not pick_has_tier5_context(pick):
        return [], {}
    if operator_context is None:
        return (
            [TIER5_FIELDING_FLAG_UNKNOWN],
            {
                "tier5_fielding_oaa_edge_prev": None,
                "tier5_fielding_oaa_q10_threshold": TIER5_FIELDING_OAA_Q10_THRESHOLD,
                "tier5_fielding_oaa_q10_pass": None,
            },
        )

    pass_value = operator_context.get("tier5_fielding_oaa_q10_pass")
    if pass_value is True:
        operator_flag = TIER5_FIELDING_FLAG_PASS
    elif pass_value is False:
        operator_flag = TIER5_FIELDING_FLAG_MISS
    else:
        operator_flag = TIER5_FIELDING_FLAG_UNKNOWN
    payload = {
        "tier5_fielding_oaa_edge_prev": operator_context.get(
            "tier5_fielding_oaa_edge_prev"
        ),
        "tier5_fielding_oaa_q10_threshold": operator_context.get(
            "tier5_fielding_oaa_q10_threshold",
            TIER5_FIELDING_OAA_Q10_THRESHOLD,
        ),
        "tier5_fielding_oaa_q10_pass": pass_value,
    }
    return [operator_flag], payload


def enrich_pick(
    pick,
    poly_data: dict | None,
    kelly_fraction_cap: float,
    target_edge: float = 0.20,
    operator_context: dict[str, Any] | None = None,
) -> EnrichedPick:
    """Add Polymarket price, edge, Kelly stake, and target prices to a raw Pick."""
    poly_quote = _polymarket_quote_for(
        poly_data,
        pick.market,
        pick.side,
        pick.away,
        pick.home,
        market_line=pick.market_line,
    )
    poly_price = poly_quote.get("price") if poly_quote is not None else None

    # Decide which odds source to use for live edge calc.
    if poly_price is not None and poly_price > 0:
        poly_decimal = 1.0 / poly_price
        ref_decimal = poly_decimal
        status = "ok"
    elif pick.ref_odds_espn is not None:
        poly_decimal = None
        ref_decimal = pick.ref_odds_espn
        status = "not_on_polymarket" if poly_data is not None else "poly_unavailable"
    else:
        poly_decimal = None
        ref_decimal = None
        status = "no_ref_odds"

    shrunk_p = pick.historical_p * HISTORICAL_P_SHRINK

    if ref_decimal is not None:
        ref_implied = 1.0 / ref_decimal
        live_edge_pct = shrunk_p - ref_implied
        kelly_full = kelly(shrunk_p, ref_decimal)
        stake_fraction_base = kelly_fraction_cap * kelly_full
    else:
        live_edge_pct = None
        kelly_full = None
        stake_fraction_base = None

    stake_multiplier, stake_multiplier_reason = overlap_stake_bonus(pick)
    if stake_fraction_base is not None:
        stake_fraction = min(stake_fraction_base * stake_multiplier, 1.0)
    else:
        stake_fraction = None

    # Target pricing (L1 sweet-spot targeting).
    target_min, target_sweet = _target_prices(shrunk_p, target_edge)
    kelly_at_sweet = kelly(shrunk_p, target_sweet) if target_sweet else None
    operator_flags, operator_payload = tier5_operator_payload(pick, operator_context)
    feature_snapshot = dict(pick.feature_snapshot)
    feature_snapshot.update(operator_payload)

    return EnrichedPick(
        pick_id=pick.pick_id,
        date=pick.date.isoformat(),
        away=pick.away,
        home=pick.home,
        market=pick.market,
        side=pick.side,
        tier=pick.tier,
        also_qualified=list(pick.also_qualified),
        historical_p=pick.historical_p,
        shrunk_p=shrunk_p,
        ref_odds_espn=pick.ref_odds_espn,
        pick_line=pick.market_line,
        polymarket_price=poly_price,
        polymarket_decimal=poly_decimal,
        polymarket_event_id=poly_quote.get("event_id") if poly_quote else None,
        polymarket_market_id=poly_quote.get("market_id") if poly_quote else None,
        polymarket_condition_id=poly_quote.get("condition_id") if poly_quote else None,
        polymarket_token_id=poly_quote.get("token_id") if poly_quote else None,
        polymarket_slug=poly_quote.get("slug") if poly_quote else None,
        polymarket_line=poly_quote.get("line") if poly_quote else None,
        polymarket_best_bid=poly_quote.get("best_bid") if poly_quote else None,
        polymarket_best_ask=poly_quote.get("best_ask") if poly_quote else None,
        polymarket_accepting_orders=(
            poly_quote.get("accepting_orders") if poly_quote else None
        ),
        status=status,
        live_edge_pct=live_edge_pct,
        kelly_fraction=kelly_full,
        stake_fraction_base=stake_fraction_base,
        stake_multiplier=stake_multiplier,
        stake_multiplier_reason=stake_multiplier_reason,
        stake_fraction=stake_fraction,
        target_min_decimal=target_min,
        target_sweet_decimal=target_sweet,
        kelly_at_sweet=kelly_at_sweet,
        operator_flags=operator_flags,
        reason=pick.reason,
        feature_snapshot=feature_snapshot,
        generated_at=_now_iso(),
    )


def filter_unprofitable(picks: list[EnrichedPick]) -> list[EnrichedPick]:
    """Drop picks that are confirmed unprofitable on Polymarket.

    A pick is dropped only if status="ok" AND live_edge_pct <= 0.
    Picks with poly_unavailable / not_on_polymarket / no_ref_odds are kept
    so the operator can triage them manually.

    Also drops picks below the minimum stake fraction.
    """
    out = []
    for p in picks:
        if p.status == "ok" and (p.live_edge_pct is None or p.live_edge_pct <= 0):
            continue
        if p.stake_fraction is not None and p.stake_fraction < MIN_STAKE_FRACTION:
            continue
        out.append(p)
    return out


def write_picks(
    picks: list[EnrichedPick],
    target_date: date,
    *,
    dry_run: bool,
) -> Path | None:
    """Write picks_YYYY-MM-DD.json + append to pick_log.jsonl."""
    if not picks:
        logger.info("No picks to write.")
        return None
    if dry_run:
        logger.info("DRY RUN: would write %d picks", len(picks))
        return None

    PICKS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = PICKS_DIR / f"picks_{target_date.isoformat()}.json"
    out_path.write_text(
        json.dumps([asdict(p) for p in picks], indent=2, default=str),
        encoding="utf-8",
    )
    # Append to ledger (one line per pick)
    with PICK_LOG.open("a", encoding="utf-8") as fh:
        for p in picks:
            fh.write(json.dumps(asdict(p), default=str) + "\n")
    logger.info("Wrote %d picks -> %s", len(picks), out_path.name)
    return out_path


def print_summary(picks: list[EnrichedPick]) -> None:
    """Print a human-readable table to stdout."""
    if not picks:
        print("\n  (no picks)")
        return
    print()
    print(
        f"  {'TIER':<34} {'AWAY':>4} @ {'HOME':<4} {'MKT':<8} {'SIDE':<5}"
        f" {'P':>6} {'REF':>6} {'POLY':>6} {'EDGE':>6}"
        f" {'STAKE':>6} {'MULT':>5}  {'MIN':>5} {'SWEET':>5} {'K@SW':>5}  {'FLAGS':<24} STATUS"
    )
    print("  " + "-" * 159)
    for p in picks:
        market_label = (
            f"{p.market}@{p.pick_line:g}" if p.pick_line is not None else p.market
        )
        ref = f"{p.ref_odds_espn:.2f}" if p.ref_odds_espn else "  -"
        poly = f"{p.polymarket_decimal:.2f}" if p.polymarket_decimal else "  -"
        edge = f"{p.live_edge_pct * 100:+.0f}%" if p.live_edge_pct is not None else "   -"
        stake = f"{p.stake_fraction * 100:.1f}%" if p.stake_fraction is not None else "  -"
        mult = f"x{p.stake_multiplier:.1f}" if p.stake_multiplier != 1.0 else "  -"
        tmin = f"{p.target_min_decimal:.2f}" if p.target_min_decimal else "  -"
        tsweet = f"{p.target_sweet_decimal:.2f}" if p.target_sweet_decimal else "  -"
        ksw = f"{p.kelly_at_sweet * 100:.0f}%" if p.kelly_at_sweet else "  -"
        flags = ",".join(p.operator_flags) if p.operator_flags else "-"
        also = f" (+{','.join(p.also_qualified)})" if p.also_qualified else ""
        print(
            f"  {p.tier + also:<34} {p.away:>4} @ {p.home:<4} {market_label:<8} {p.side:<5}"
            f" {p.shrunk_p:>6.3f} {ref:>6} {poly:>6} {edge:>6}"
            f" {stake:>6} {mult:>5}  {tmin:>5} {tsweet:>5} {ksw:>5}  {flags:<24} {p.status}"
        )
    print()
    print("  MULT = overlap bonus | MIN = don't bet below this | SWEET = wait-for price (+20% edge) | K@SW = Kelly at sweet")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate 2026 MLB picks (manual review)")
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Target date YYYY-MM-DD (default: today)",
    )
    parser.add_argument(
        "--tiers",
        type=str,
        default=DEFAULT_TIERS_CSV,
        help="Comma-separated tier names (default: live strategy set)",
    )
    parser.add_argument(
        "--no-poly",
        action="store_true",
        help="Skip Polymarket fetch (use ESPN reference odds only)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Don't write picks file or append to ledger",
    )
    parser.add_argument(
        "--kelly",
        type=float,
        default=0.25,
        help="Kelly fraction multiplier (default 0.25 for W2-W3 ramp)",
    )
    parser.add_argument(
        "--kelly-protocol",
        action="store_true",
        help="Auto-select Kelly by season-week (CLAUDE.md ramp): W1=0.0 no bets, "
             "W2/W3=0.25, W4+=0.5. Overrides --kelly.",
    )
    parser.add_argument(
        "--target-edge",
        type=float,
        default=0.20,
        help="Target edge for sweet-spot pricing (default 0.20 = 20%% edge)",
    )
    args = parser.parse_args()

    target = date.fromisoformat(args.date) if args.date else date.today()
    requested_tiers = [t.strip() for t in args.tiers.split(",") if t.strip()]

    # CLAUDE.md season ramp: W1 no bets, W2/W3 ¼ Kelly, W4+ ½ Kelly. Seasons
    # start late March; for simplicity we key off April and compute the
    # week-of-April (1-based).
    kelly_cap = args.kelly
    if args.kelly_protocol:
        april_start = date(target.year, 4, 1)
        if target < april_start:
            week = 0
        else:
            week = ((target - april_start).days // 7) + 1
        if week <= 1:
            kelly_cap = 0.0
            logger.warning(
                "--kelly-protocol: W%d (pre-W2) → Kelly=0.0 (no bets). "
                "Script will still compute signals for monitoring.",
                week,
            )
        elif week <= 3:
            kelly_cap = 0.25
        else:
            kelly_cap = 0.5
        logger.info(
            "--kelly-protocol: week %d of April → Kelly cap = %.2f",
            week,
            kelly_cap,
        )

    logger.info("=== generate_picks_2026 — %s ===", target)
    logger.info("Tiers: %s", requested_tiers)
    logger.info("Kelly cap: %.2f", kelly_cap)

    # 1. Build features.
    from src.data_loader import (  # noqa: PLC0415
        add_derived_odds,
        apply_data_filters,
        load_all_seasons,
    )
    from src.features import build_all_features  # noqa: PLC0415
    from src.strategies import (  # noqa: PLC0415
        ACTIVE_STRATEGIES,
        add_derived_for_strategies,
    )
    try:
        from src.live_strategy_audit import (  # noqa: PLC0415
            AUDIT_CONFIGS,
            evaluate_strategy_day,
            target_day_frame,
        )
    except ImportError as exc:  # noqa: BLE001
        logger.warning("Live strategy audit unavailable: %s", exc)
        AUDIT_CONFIGS = {}

        def target_day_frame(enriched_frame: pd.DataFrame, target_date: date) -> pd.DataFrame:
            if enriched_frame.empty:
                return enriched_frame.copy()
            first = enriched_frame["date"].iloc[0]
            if hasattr(first, "date"):
                return enriched_frame[enriched_frame["date"].dt.date == target_date].copy()
            return enriched_frame[enriched_frame["date"] == target_date].copy()

        def evaluate_strategy_day(day_frame: pd.DataFrame, tier: str) -> dict[str, Any]:
            return {
                "tier": tier,
                "games": int(len(day_frame)),
                "usable_rows": int(len(day_frame)),
                "raw_pass": 0,
                "verdict": "audit_unavailable",
                "verdict_detail": "live_strategy_audit import failed",
            }

    logger.info("Loading + enriching games...")
    games = load_all_seasons()

    # Pregame overlay — for today/future dates, pull the most recent pregame
    # JSON snapshot and concat BEFORE filters so the new rows pass through
    # the same pitcher/odds gates as historical data. The data pipeline never
    # sees these rows (parquet stays canonical = played games).
    if target >= date.today():
        from src.live_pregame import load_pregame_overlay  # noqa: PLC0415
        overlay = load_pregame_overlay(target)
        if not overlay.empty:
            # Guard against dupes if the date was somehow already merged.
            mask_existing = (games["date"].dt.date == target) if len(games) else pd.Series([], dtype=bool)
            if mask_existing.any():
                logger.info(
                    "Overlay: dropping %d pre-existing rows for %s before concat",
                    int(mask_existing.sum()),
                    target,
                )
                games = games.loc[~mask_existing].copy()
            games = pd.concat([games, overlay], ignore_index=True, sort=False)
            logger.info("Pregame overlay: +%d games for %s", len(overlay), target)

    games = apply_data_filters(games)
    games = add_derived_odds(games)

    # Restrict to recent seasons for speed (live picks don't need 2004 history).
    games = games[games["season"].isin([2024, 2025, 2026])]

    enriched = build_all_features(games)

    # If we ran with a pregame overlay, the bullpen & starter-entering parquets
    # only contain dates < target. Forward-project team/pitcher features onto
    # today's rows so strategies have the inputs they need (small bias vs.
    # total absence of signal — see src/live_feature_forward.py).
    if target >= date.today():
        from src.live_feature_forward import forward_project_features  # noqa: PLC0415
        enriched = forward_project_features(enriched, target)

    enriched = add_derived_for_strategies(enriched)
    enriched = add_tier5_operator_fielding_signal(enriched)
    logger.info("Enriched: %d rows, %d cols", len(enriched), len(enriched.columns))
    if target >= date.today() and not enriched.empty:
        day = enriched[enriched["date"].dt.date == target].copy()
        for col in [
            "starter_feature_source_missing",
            "insufficient_starter_history",
            "lineup_feature_source_missing",
            "insufficient_lineup_history",
            "unsupported_live_yrfi_features",
        ]:
            if col in day.columns:
                count = int(day[col].fillna(False).astype(bool).sum())
                if count:
                    logger.warning("Target-date flag %s: %d/%d games", col, count, len(day))
        support_count = int(day["tier5_fielding_oaa_q10_pass"].notna().sum())
        if support_count:
            logger.info(
                "Target-date tier5 fielding support available: %d/%d games",
                support_count,
                len(day),
            )
    else:
        day = target_day_frame(enriched, target)

    tier5_operator_lookup = build_tier5_operator_lookup(enriched, target)

    live_audit_tiers = [tier for tier in requested_tiers if tier in AUDIT_CONFIGS]
    if live_audit_tiers:
        for tier in live_audit_tiers:
            audit = evaluate_strategy_day(day, tier)
            logger.info(
                "%s readiness: games=%d usable=%d raw_pass=%d verdict=%s (%s)",
                tier,
                audit["games"],
                audit["usable_rows"],
                audit["raw_pass"],
                audit["verdict"],
                audit["verdict_detail"],
            )
            if audit["raw_pass"] == 0:
                if audit["verdict"] == "strict_but_ready":
                    logger.info("%s: 0 picks due to strict filters", tier)
                elif audit["verdict"] in {"source_blocked", "warmup_sparse"}:
                    logger.info("%s: 0 picks due to missing/insufficient live data", tier)

    # 2. Run each strategy.
    raw_picks = []
    for tier in requested_tiers:
        if tier not in ACTIVE_STRATEGIES:
            logger.warning("Unknown tier %r — skipping", tier)
            continue
        finder = ACTIVE_STRATEGIES[tier]
        tier_picks = finder(enriched, target)
        logger.info("%s: %d raw picks", tier, len(tier_picks))
        raw_picks.extend(tier_picks)

    # 3. Dedup overlap (Tier 1 wins).
    deduped = dedup_overlapping_picks(raw_picks)
    if len(deduped) != len(raw_picks):
        logger.info(
            "Dedup: %d → %d picks (overlap recorded in also_qualified)",
            len(raw_picks),
            len(deduped),
        )

    # 4. Polymarket prices (graceful fallback on failure).
    poly_lookup: dict[tuple[str, str], dict] = {}
    if not args.no_poly:
        logger.info("Fetching Polymarket prices...")
        poly_lookup = fetch_polymarket_prices(target)
        logger.info("Polymarket events matched: %d", len(poly_lookup))

    # 5. Enrich each pick with poly + edge + Kelly + target prices.
    enriched_picks: list[EnrichedPick] = []
    for p in deduped:
        poly_data = poly_lookup.get((p.away, p.home))
        enriched_picks.append(
            enrich_pick(
                p,
                poly_data,
                kelly_cap,
                target_edge=args.target_edge,
                operator_context=tier5_operator_lookup.get((p.away, p.home)),
            )
        )

    # 6. Filter unprofitable picks.
    final = filter_unprofitable(enriched_picks)
    logger.info(
        "Final: %d picks (dropped %d unprofitable / sub-min)",
        len(final),
        len(enriched_picks) - len(final),
    )

    # 7. Write + summary.
    write_picks(final, target, dry_run=args.dry_run)
    print_summary(final)

    return 0


if __name__ == "__main__":
    sys.exit(main())
