"""Generate today's MLB betting picks for the 2026 season.

Implements the audit plan §10 contract. Loads the unfiltered feature
pipeline (build_all_features — NOT build_spec_features which drops
April), runs the four production strategies, deduplicates overlap,
optionally fetches live Polymarket prices, computes Kelly stake
fractions, and writes the picks to disk for manual operator review.

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

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

warnings.filterwarnings("ignore")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
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
# Tier 1's bullpen-day signal is the strongest and wins all conflicts.
TIER_PRIORITY = [
    "tier1_bullpen_day",
    "tier1_bullpen_day_flipped",
    "tier3_pitcher_advantage",
    "tier2_fatigue_gap",
    "fav_rl",
]


# ---------------------------------------------------------------------------
# Pick → JSON serialization
# ---------------------------------------------------------------------------


@dataclass
class EnrichedPick:
    """A Pick after Polymarket lookup, edge calculation, and Kelly sizing.

    This is the JSON shape that lands in picks_YYYY-MM-DD.json. The schema
    is locked at v1 — see audit plan §10.
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
    polymarket_price: float | None
    polymarket_decimal: float | None
    status: str  # "ok" | "poly_unavailable" | "not_on_polymarket" | "no_ref_odds"
    live_edge_pct: float | None
    kelly_fraction: float | None
    stake_fraction: float | None
    # Target pricing — what odds to wait for (L1 sweet-spot targeting).
    # target_min: breakeven odds (edge=0); below this, DON'T bet.
    # target_sweet: odds where edge = --target-edge (default 20%); the wait-for price.
    # kelly_at_sweet: Kelly fraction IF filled at target_sweet odds.
    target_min_decimal: float | None
    target_sweet_decimal: float | None
    kelly_at_sweet: float | None
    reason: str
    feature_snapshot: dict[str, Any]
    generated_at: str
    schema_version: int = 2


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


def _polymarket_price_for(
    poly_data: dict | None,
    market: str,
    side: str,
    away: str,
    home: str,
) -> float | None:
    """Return the Polymarket implied price (0..1) for our pick side, or None.

    market is one of: "ML_dog", "RL_+1.5", "RL_-1.5".
    side is "away" or "home".

    Polymarket lists outcomes as full team names. We match by mapping each
    outcome name back to a 3-letter code. For totals (not used here) the
    outcomes are "Over" / "Under".
    """
    if poly_data is None:
        return None
    markets = poly_data.get("markets", {})

    if market.startswith("ML"):
        ml_list = markets.get("moneyline") or []
        if not ml_list:
            return None
        m = ml_list[0]  # any one moneyline market is fine
        return _outcome_price_for_side(m, side, away, home)

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
                price = _outcome_price_for_side(m, side, away, home)
                if price is not None:
                    return price
        return None

    return None


def _outcome_price_for_side(
    market: dict, side: str, away: str, home: str
) -> float | None:
    """Match a Polymarket outcome to our away/home side and return its price."""
    outcomes = market.get("outcomes", [])
    prices = market.get("outcome_prices", [])
    if len(outcomes) != len(prices):
        return None
    target_code = away if side == "away" else home
    for name, price in zip(outcomes, prices):
        code = _normalize_poly_team(name)
        if code == target_code:
            try:
                return float(price)
            except (TypeError, ValueError):
                return None
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


def enrich_pick(
    pick,
    poly_data: dict | None,
    kelly_fraction_cap: float,
    target_edge: float = 0.20,
) -> EnrichedPick:
    """Add Polymarket price, edge, Kelly stake, and target prices to a raw Pick."""
    poly_price = _polymarket_price_for(
        poly_data, pick.market, pick.side, pick.away, pick.home
    )

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
        stake_fraction = kelly_fraction_cap * kelly_full
    else:
        live_edge_pct = None
        kelly_full = None
        stake_fraction = None

    # Target pricing (L1 sweet-spot targeting).
    target_min, target_sweet = _target_prices(shrunk_p, target_edge)
    kelly_at_sweet = kelly(shrunk_p, target_sweet) if target_sweet else None

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
        polymarket_price=poly_price,
        polymarket_decimal=poly_decimal,
        status=status,
        live_edge_pct=live_edge_pct,
        kelly_fraction=kelly_full,
        stake_fraction=stake_fraction,
        target_min_decimal=target_min,
        target_sweet_decimal=target_sweet,
        kelly_at_sweet=kelly_at_sweet,
        reason=pick.reason,
        feature_snapshot=pick.feature_snapshot,
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
        f"  {'TIER':<22} {'AWAY':>4} @ {'HOME':<4} {'MKT':<8} {'SIDE':<5}"
        f" {'P':>6} {'REF':>6} {'POLY':>6} {'EDGE':>6}"
        f" {'STAKE':>6}  {'MIN':>5} {'SWEET':>5} {'K@SW':>5}  STATUS"
    )
    print("  " + "-" * 115)
    for p in picks:
        ref = f"{p.ref_odds_espn:.2f}" if p.ref_odds_espn else "  -"
        poly = f"{p.polymarket_decimal:.2f}" if p.polymarket_decimal else "  -"
        edge = f"{p.live_edge_pct * 100:+.0f}%" if p.live_edge_pct is not None else "   -"
        stake = f"{p.stake_fraction * 100:.1f}%" if p.stake_fraction is not None else "  -"
        tmin = f"{p.target_min_decimal:.2f}" if p.target_min_decimal else "  -"
        tsweet = f"{p.target_sweet_decimal:.2f}" if p.target_sweet_decimal else "  -"
        ksw = f"{p.kelly_at_sweet * 100:.0f}%" if p.kelly_at_sweet else "  -"
        also = f" (+{','.join(p.also_qualified)})" if p.also_qualified else ""
        print(
            f"  {p.tier + also:<22} {p.away:>4} @ {p.home:<4} {p.market:<8} {p.side:<5}"
            f" {p.shrunk_p:>6.3f} {ref:>6} {poly:>6} {edge:>6}"
            f" {stake:>6}  {tmin:>5} {tsweet:>5} {ksw:>5}  {p.status}"
        )
    print()
    print("  MIN = don't bet below this | SWEET = wait-for price (+20% edge) | K@SW = Kelly at sweet")
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
        default="tier1_bullpen_day,tier2_fatigue_gap,tier3_pitcher_advantage,fav_rl",
        help="Comma-separated tier names (default: all 4)",
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
        "--target-edge",
        type=float,
        default=0.20,
        help="Target edge for sweet-spot pricing (default 0.20 = 20%% edge)",
    )
    args = parser.parse_args()

    target = date.fromisoformat(args.date) if args.date else date.today()
    requested_tiers = [t.strip() for t in args.tiers.split(",") if t.strip()]

    logger.info("=== generate_picks_2026 — %s ===", target)
    logger.info("Tiers: %s", requested_tiers)
    logger.info("Kelly cap: %.2f", args.kelly)

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

    logger.info("Loading + enriching games...")
    games = load_all_seasons()
    games = apply_data_filters(games)
    games = add_derived_odds(games)

    # Restrict to recent seasons for speed (live picks don't need 2004 history).
    games = games[games["season"].isin([2024, 2025, 2026])]

    enriched = build_all_features(games)
    enriched = add_derived_for_strategies(enriched)
    logger.info("Enriched: %d rows, %d cols", len(enriched), len(enriched.columns))

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
            enrich_pick(p, poly_data, args.kelly, target_edge=args.target_edge)
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
