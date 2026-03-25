"""Match card builders for LLM expert analysis.

Two card types:
  1. MatchCard -- neutral, no betting context (for Analyst)
  2. BettingCard -- adds odds, model predictions, discrepancy, regime flags (for Expert)

Follows the same pattern as MLB domain's feature_card.py.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.features import BIG_3


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _safe(row: pd.Series, col: str, fmt: str = ".2f") -> str | None:
    """Safely format a value from a row, returning None if NaN."""
    val = row.get(col)
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return None
    return f"{val:{fmt}}"


def _safe_float(row: pd.Series, col: str) -> float | None:
    val = row.get(col)
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return None
    return float(val)


def _streak_str(streak: float | None) -> str:
    if streak is None or np.isnan(streak):
        return "N/A"
    s = int(streak)
    if s > 0:
        return f"W{s}"
    elif s < 0:
        return f"L{abs(s)}"
    return "D"


def _fatigue_label(days_rest: float | None, density: float | None) -> str:
    """Label fatigue level based on days rest and match density."""
    parts = []
    if days_rest is not None and not np.isnan(days_rest):
        if days_rest <= 2:
            parts.append("VERY FATIGUED")
        elif days_rest <= 3:
            parts.append("FATIGUED")
    if density is not None and not np.isnan(density):
        if density >= 4:
            parts.append(f"{int(density)} matches in 14d")
    return " -- ".join(parts) if parts else ""


# ---------------------------------------------------------------------------
# MatchCard (neutral -- no odds, no model, no betting context)
# ---------------------------------------------------------------------------

@dataclass
class MatchCard:
    """Neutral match profile for the Analyst. No odds, no model predictions."""

    match_id: str
    prompt_text: str

    @classmethod
    def from_row(cls, row: pd.Series) -> "MatchCard":
        date = row.get("date", "unknown")
        if hasattr(date, "strftime"):
            date = date.strftime("%Y-%m-%d")
        home = row.get("home_team", "?")
        away = row.get("away_team", "?")
        match_id = f"{date}_{home}_{away}"

        sections = [
            _header_neutral(row),
            _squad_stability_section(row),
            _form_section(row),
            _congestion_section(row),
            _context_section(row),
        ]
        prompt_text = "\n\n".join(s for s in sections if s)
        return cls(match_id=match_id, prompt_text=prompt_text)

    def to_prompt(self) -> str:
        return self.prompt_text


# ---------------------------------------------------------------------------
# BettingCard (MatchCard + odds + model + scenario + regime)
# ---------------------------------------------------------------------------

@dataclass
class BettingCard:
    """Full match profile for the Betting Expert. Includes odds, model, scenario."""

    match_id: str
    prompt_text: str

    @classmethod
    def from_row(
        cls,
        row: pd.Series,
        model_probs: dict,
        scenario_text: str = "",
    ) -> "BettingCard":
        date = row.get("date", "unknown")
        if hasattr(date, "strftime"):
            date = date.strftime("%Y-%m-%d")
        home = row.get("home_team", "?")
        away = row.get("away_team", "?")
        match_id = f"{date}_{home}_{away}"

        sections = [
            _header_neutral(row),
            _squad_stability_section(row),
            _form_section(row),
            _congestion_section(row),
            _context_section(row),
            _odds_section(row),
            _model_section(model_probs),
            _discrepancy_section(row, model_probs),
            _regime_section(row),
        ]

        if scenario_text:
            sections.append(f"--Analyst Scenario --\n{scenario_text}")

        prompt_text = "\n\n".join(s for s in sections if s)
        return cls(match_id=match_id, prompt_text=prompt_text)

    def to_prompt(self) -> str:
        return self.prompt_text


# ---------------------------------------------------------------------------
# Section builders -- neutral (shared by both cards)
# ---------------------------------------------------------------------------

def _header_neutral(row: pd.Series) -> str:
    date = row.get("date", "?")
    if hasattr(date, "strftime"):
        date = date.strftime("%Y-%m-%d")
    home = row.get("home_team", "?")
    away = row.get("away_team", "?")
    matchday = _safe(row, "matchday")
    md_str = f", Season progress: {float(matchday):.0%}" if matchday else ""
    return f"MATCH: {home} vs {away} -- {date}{md_str}"


def _squad_stability_section(row: pd.Series) -> str:
    lines = ["--Squad Stability --"]
    home = row.get("home_team", "?")
    away = row.get("away_team", "?")

    for side, team in [("home", home), ("away", away)]:
        sss_cum = _safe(row, f"sss_cum_{side}")
        sss_r10 = _safe(row, f"sss_r10_{side}")
        if sss_cum is None and sss_r10 is None:
            lines.append(f"  {team}: SSS data unavailable")
            continue

        parts = [f"  {team}:"]
        if sss_cum:
            parts.append(f"SSS {sss_cum} (cumulative)")
        if sss_r10:
            parts.append(f"{sss_r10} (last 10)")

        # Qualitative label
        cum_val = _safe_float(row, f"sss_cum_{side}")
        if cum_val is not None:
            if cum_val >= 0.75:
                parts.append("-- core intact")
            elif cum_val >= 0.60:
                parts.append("-- moderate rotation")
            else:
                parts.append("-- significant rotation")

        lines.append(" ".join(parts))

    # Diff
    diff = _safe_float(row, "sss_cum_diff")
    if diff is not None:
        lines.append(f"  Stability gap: {diff:+.2f} (home - away)")

    return "\n".join(lines)


def _form_section(row: pd.Series) -> str:
    lines = ["--Form & Momentum --"]
    home = row.get("home_team", "?")
    away = row.get("away_team", "?")

    for side, team in [("home", home), ("away", away)]:
        ppg_cum = _safe(row, f"ppg_cum_{side}")
        ppg_r5 = _safe(row, f"ppg_r5_{side}")
        streak = _safe_float(row, f"streak_{side}")
        gf = _safe(row, f"gf_pg_r5_{side}")
        ga = _safe(row, f"ga_pg_r5_{side}")

        parts = [f"  {team}:"]
        if ppg_cum:
            parts.append(f"{ppg_cum} PPG (season)")
        if ppg_r5:
            parts.append(f"{ppg_r5} PPG (last 5)")
        if streak is not None:
            parts.append(f"streak {_streak_str(streak)}")
        lines.append(", ".join(parts[1:]).rstrip(","))
        lines[-1] = f"  {team}: " + lines[-1].lstrip()

        if gf or ga:
            atk_def = f"    Attack: {gf or 'N/A'} GF/game, Defense: {ga or 'N/A'} GA/game (last 5)"
            lines.append(atk_def)

    return "\n".join(lines)


def _congestion_section(row: pd.Series) -> str:
    lines = ["--Congestion --"]
    home = row.get("home_team", "?")
    away = row.get("away_team", "?")

    for side, team in [("home", home), ("away", away)]:
        dr = _safe_float(row, f"days_rest_{side}")
        density = _safe_float(row, f"match_density_14d_{side}")

        parts = [f"  {team}:"]
        if dr is not None:
            parts.append(f"{int(dr)} days rest")
        if density is not None:
            parts.append(f"{int(density)} matches in 14 days")

        fatigue = _fatigue_label(dr, density)
        if fatigue:
            parts.append(fatigue)

        lines.append(", ".join(parts[1:]).rstrip(","))
        lines[-1] = f"  {team}: " + lines[-1].lstrip()

    return "\n".join(lines)


def _context_section(row: pd.Series) -> str:
    lines = ["--Context --"]
    home = row.get("home_team", "?")
    away = row.get("away_team", "?")

    home_big3 = home in BIG_3
    away_big3 = away in BIG_3
    lines.append(f"  Home: {home} (Big-3: {'Yes' if home_big3 else 'No'})")
    lines.append(f"  Away: {away} (Big-3: {'Yes' if away_big3 else 'No'})")

    matchday = _safe_float(row, "matchday")
    if matchday is not None:
        lines.append(f"  Season progress: {matchday:.0%}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Section builders -- betting-only (BettingCard)
# ---------------------------------------------------------------------------

def _odds_section(row: pd.Series) -> str:
    lines = ["--Market Odds (Pinnacle) --"]

    for outcome, col, impl_col in [
        ("Home", "home_odds", "home_implied"),
        ("Draw", "draw_odds", "draw_implied"),
        ("Away", "away_odds", "away_implied"),
    ]:
        odds = _safe_float(row, col)
        impl = _safe_float(row, impl_col)
        if odds is not None and impl is not None:
            lines.append(f"  {outcome}: {odds:.2f} (impl {impl:.1%})")

    # Line movement
    lm_parts = []
    for outcome, col in [("Home", "line_move_home"), ("Draw", "line_move_draw"), ("Away", "line_move_away")]:
        lm = _safe_float(row, col)
        if lm is not None:
            direction = "shortened" if lm > 0.005 else ("drifted" if lm < -0.005 else "stable")
            lm_parts.append(f"{outcome} {lm:+.3f} ({direction})")
    if lm_parts:
        lines.append(f"  Line movement: {', '.join(lm_parts)}")

    return "\n".join(lines)


def _model_section(model_probs: dict) -> str:
    lines = ["--Model Predictions --"]

    lh = model_probs.get("expected_home", 0)
    la = model_probs.get("expected_away", 0)
    lines.append(f"  Expected goals: Home lam={lh:.2f}, Away lam={la:.2f} (total {lh + la:.2f})")

    ph = model_probs.get("home_win", 0)
    pd_ = model_probs.get("draw", 0)
    pa = model_probs.get("away_win", 0)
    lines.append(f"  Model probabilities: Home {ph:.1%}, Draw {pd_:.1%}, Away {pa:.1%}")

    o25 = model_probs.get("over_2.5", 0)
    lines.append(f"  Over 2.5: {o25:.1%}")

    return "\n".join(lines)


def _discrepancy_section(row: pd.Series, model_probs: dict) -> str:
    lines = ["--Discrepancy (Model - Market) --"]

    pairs = [
        ("Home", model_probs.get("home_win", 0), _safe_float(row, "home_implied")),
        ("Draw", model_probs.get("draw", 0), _safe_float(row, "draw_implied")),
        ("Away", model_probs.get("away_win", 0), _safe_float(row, "away_implied")),
    ]

    max_edge = 0.0
    max_edge_label = ""
    for label, model_p, market_p in pairs:
        if market_p is not None:
            diff = model_p - market_p
            direction = "OVERRATES" if diff < 0 else "UNDERRATES"
            lines.append(f"  {label}: {diff:+.1%} (market {direction} {label.lower()})")
            if abs(diff) > abs(max_edge):
                max_edge = diff
                max_edge_label = label

    if max_edge_label:
        lines.append(f"  Largest edge: {max_edge_label} {max_edge:+.1%}")

    return "\n".join(lines)


def _regime_section(row: pd.Series) -> str:
    lines = ["--Regime Flags --"]

    sss_diff = _safe_float(row, "sss_cum_diff")
    if sss_diff is not None:
        is_disruption = abs(sss_diff) > 0.15
        lines.append(f"  Squad disruption: {'YES' if is_disruption else 'NO'} (SSS diff {sss_diff:+.2f})")

    dr_home = _safe_float(row, "days_rest_home")
    dr_away = _safe_float(row, "days_rest_away")
    if dr_home is not None or dr_away is not None:
        any_short = (dr_home is not None and dr_home <= 3) or (dr_away is not None and dr_away <= 3)
        lines.append(f"  Congestion: {'YES' if any_short else 'NO'}")

    home_team = row.get("home_team", "")
    away_team = row.get("away_team", "")
    big3 = (home_team in BIG_3) or (away_team in BIG_3)
    lines.append(f"  Big-3 involved: {'YES' if big3 else 'NO'}")

    return "\n".join(lines)
