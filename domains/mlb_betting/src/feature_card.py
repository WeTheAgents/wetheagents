"""Feature card builder for LLM expert analysis.

Converts an enriched DataFrame row into a narrative-format feature card
that LLM experts can reason about. Embeds domain knowledge (thresholds,
labels) so the LLM gets contextualized signals, not raw numbers.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class FeatureCard:
    """Structured game summary for LLM consumption."""

    game_id: str  # "2025-06-14_NYY_BOS"
    strategy_zone: str  # "S3_expansion" | "RL_expansion"
    prompt_text: str  # rendered narrative

    @classmethod
    def from_row(cls, row: pd.Series, zone: str) -> "FeatureCard":
        """Build a feature card from an enriched game row.

        Args:
            row: Single row from enriched DataFrame (build_spec_features output
                 merged with walk-forward divergence).
            zone: "S3_expansion", "RL_expansion", or "CF_pickem"
        """
        date = row.get("date", "unknown")
        away = row.get("away_team", "?")
        home = row.get("home_team", "?")
        game_id = f"{date}_{away}_{home}"

        if zone.startswith("CF"):
            sections = [
                _header_cf(row),
                _odds_section_cf(row),
                _model_signal_cf(row),
                _team_strength_cf(row),
                _neutral_offense_context(row),
                _recent_form(row),
                _starting_pitchers_cf(row),
                _neutral_bullpen_management(row),
                _context(row),
            ]
        else:
            sections = [
                _header(row, zone),
                _odds_section(row),
                _model_signal(row, zone),
                _team_strength(row),
                _offense_context(row),
                _recent_form(row),
                _starting_pitchers(row),
                _bullpen_management(row),
                _context(row),
            ]
        prompt_text = "\n\n".join(s for s in sections if s)

        return cls(game_id=game_id, strategy_zone=zone, prompt_text=prompt_text)

    def with_scenario(self, scenario_text: str) -> "FeatureCard":
        """Return a copy with analyst scenario prepended."""
        new_prompt = (
            self.prompt_text
            + "\n\n── Independent Analyst Scenario ──\n"
            + scenario_text
        )
        return FeatureCard(
            game_id=self.game_id,
            strategy_zone=self.strategy_zone,
            prompt_text=new_prompt,
        )

    def to_prompt(self) -> str:
        return self.prompt_text


@dataclass
class AnalystCard:
    """Clean game summary for the Analyst — no betting context.

    No odds, no edge, no model signals, no "dog"/"fav" language.
    Just teams, stats, pitchers, form. Neutral framing.
    """

    game_id: str
    prompt_text: str

    @classmethod
    def from_row(cls, row: pd.Series) -> "AnalystCard":
        """Build a neutral card from an enriched game row."""
        date = row.get("date", "unknown")
        away = row.get("away_team", "?")
        home = row.get("home_team", "?")
        game_id = f"{date}_{away}_{home}"

        sections = [
            f"GAME: {away} @ {home} -- {date}",
            _neutral_team_strength(row),
            _neutral_offense_context(row),
            _recent_form(row),  # already neutral enough
            _neutral_pitchers(row),
            _neutral_bullpen_management(row),
            _context(row),  # already neutral
        ]
        prompt_text = "\n\n".join(s for s in sections if s)

        return cls(game_id=game_id, prompt_text=prompt_text)

    def to_prompt(self) -> str:
        return self.prompt_text


# ── Section builders ──────────────────────────────────────────────────────


def _header(row: pd.Series, zone: str) -> str:
    date = row.get("date", "?")
    away = row.get("away_team", "?")
    home = row.get("home_team", "?")
    edge = _safe(row, "edge_consensus")
    edge_str = f"edge={edge:+.2f}" if edge is not None else "edge=N/A"
    zone_label = "S3 expansion (Away ML)" if "S3" in zone else "RL expansion (Away +1.5)"
    return f"GAME: {away} @ {home} — {date} | Zone: {zone_label} ({edge_str})"


def _odds_section(row: pd.Series) -> str:
    away = row.get("away_team", "?")
    home = row.get("home_team", "?")
    away_dec = _safe(row, "away_decimal_odds")
    home_dec = _safe(row, "home_decimal_odds")
    away_imp = _safe(row, "away_implied_prob")
    home_imp = _safe(row, "home_implied_prob")

    lines = ["── Odds ──"]
    if away_dec is not None and away_imp is not None:
        away_ml = _decimal_to_american(away_dec)
        lines.append(
            f"DOG: {away} (away) — odds {away_dec:.2f} ({away_ml}), "
            f"implied {away_imp * 100:.1f}%"
        )
    if home_dec is not None and home_imp is not None:
        home_ml = _decimal_to_american(home_dec)
        lines.append(
            f"FAV: {home} (home) — odds {home_dec:.2f} ({home_ml}), "
            f"implied {home_imp * 100:.1f}%"
        )
    return "\n".join(lines)


def _model_signal(row: pd.Series, zone: str) -> str:
    lines = ["── Model Signal ──"]

    edge = _safe(row, "edge_consensus")
    if edge is not None:
        if "S3" in zone:
            note = _label_edge_s3(edge)
        else:
            note = _label_edge_rl(edge)
        lines.append(f"edge_consensus: {edge:+.3f} ({note})")

    # Regime predictions
    preds = []
    for regime in ["M0", "M2", "M3", "M4"]:
        v = _safe(row, f"pred_{regime}")
        if v is not None:
            preds.append(f"{regime}={v:.2f}")
    if preds:
        lines.append(f"regime predictions: {', '.join(preds)}")

    div_std = _safe(row, "div_std")
    if div_std is not None:
        label = "low" if div_std < 0.10 else "moderate" if div_std < 0.25 else "high"
        lines.append(f"divergence (std): {div_std:.3f} ({label} model disagreement)")

    return "\n".join(lines)


def _team_strength(row: pd.Series) -> str:
    away = row.get("away_team", "?")
    home = row.get("home_team", "?")
    lines = ["── Team Strength ──"]

    # RPI
    rpi_h = _safe(row, "rpi_home")
    rpi_a = _safe(row, "rpi_away")
    rpi_diff = _safe(row, "rpi_diff")
    if rpi_h is not None and rpi_a is not None:
        label = _label_rpi_diff(rpi_diff)
        lines.append(f"RPI: {away} {rpi_a:.3f} vs {home} {rpi_h:.3f} → diff {rpi_diff:+.3f} ({label})")

    # Elo
    elo_diff = _safe(row, "elo_diff")
    if elo_diff is not None:
        label = "home strong advantage" if elo_diff > 50 else "slight home edge" if elo_diff > 0 else "dog Elo advantage"
        lines.append(f"Elo diff: {elo_diff:+.0f} ({label})")

    # Pythagorean
    pyth_h = _safe(row, "pyth_wp_home")
    pyth_a = _safe(row, "pyth_wp_away")
    pyth_diff = _safe(row, "pyth_wp_diff")
    if pyth_h is not None and pyth_a is not None:
        label = "dog fundamentally BETTER" if pyth_diff < -0.01 else "even" if abs(pyth_diff) <= 0.01 else "fav fundamentally better"
        lines.append(f"Pythagorean WP: {away} {pyth_a:.3f} vs {home} {pyth_h:.3f} → diff {pyth_diff:+.3f} ({label})")

    # wRC+ (if available)
    wrc_h = _safe(row, "wrc_plus_home")
    wrc_a = _safe(row, "wrc_plus_away")
    if wrc_h is not None and wrc_a is not None:
        diff = wrc_a - wrc_h
        label = "dog bats BETTER" if diff > 3 else "even" if abs(diff) <= 3 else "fav bats better"
        lines.append(f"wRC+: {away} {wrc_a:.0f} vs {home} {wrc_h:.0f} ({label})")

    # OBP
    obp_h = _safe(row, "obp_home")
    obp_a = _safe(row, "obp_away")
    if obp_h is not None and obp_a is not None:
        diff = obp_a - obp_h
        label = "dog higher OBP" if diff > 0.005 else "even" if abs(diff) <= 0.005 else "fav higher OBP"
        lines.append(f"OBP: {away} {obp_a:.3f} vs {home} {obp_h:.3f} ({label})")

    # Runs scoring/allowing
    rpg_h = _safe(row, "rpg_home")
    rpg_a = _safe(row, "rpg_away")
    rapg_h = _safe(row, "rapg_home")
    rapg_a = _safe(row, "rapg_away")
    if rpg_h is not None and rpg_a is not None:
        lines.append(f"Offense RPG: {away} {rpg_a:.2f} vs {home} {rpg_h:.2f}")
    if rapg_h is not None and rapg_a is not None:
        lines.append(f"Defense RAPG: {away} {rapg_a:.2f} vs {home} {rapg_h:.2f} (lower=better)")

    return "\n".join(lines)


def _offense_context(row: pd.Series) -> str:
    away = row.get("away_team", "?")
    home = row.get("home_team", "?")
    lines = ["── Offense & Defense vs League ──"]

    off_h = _safe(row, "offense_vs_league_home")
    off_a = _safe(row, "offense_vs_league_away")
    def_h = _safe(row, "defense_vs_league_home")
    def_a = _safe(row, "defense_vs_league_away")

    if off_h is not None and off_a is not None:
        lines.append(
            f"Offense vs league: {away} {off_a * 100:.0f}% ({_label_offense(off_a)}) "
            f"| {home} {off_h * 100:.0f}% ({_label_offense(off_h)})"
        )
        # Caution flag
        if off_h > 1.10 and off_a > 1.10:
            lines.append("  ⚠ CAUTION: both lineups elite — any pitcher at risk")
    else:
        lines.append("Offense vs league: N/A (early season or missing data)")

    if def_h is not None and def_a is not None:
        lines.append(
            f"Defense vs league: {away} {def_a * 100:.0f}% ({_label_defense(def_a)}) "
            f"| {home} {def_h * 100:.0f}% ({_label_defense(def_h)})"
        )
    else:
        lines.append("Defense vs league: N/A")

    return "\n".join(lines)


def _recent_form(row: pd.Series) -> str:
    away = row.get("away_team", "?")
    home = row.get("home_team", "?")
    lines = ["── Recent Form ──"]

    # Rolling WP
    for window in [3, 6, 10]:
        wp_h = _safe(row, f"wp_last{window}_home")
        wp_a = _safe(row, f"wp_last{window}_away")
        if wp_h is not None and wp_a is not None:
            lines.append(f"WP last {window}: {away} {wp_a:.3f} vs {home} {wp_h:.3f}")

    # Streaks
    str_h = _safe(row, "streak_home")
    str_a = _safe(row, "streak_away")
    if str_h is not None and str_a is not None:
        h_label = f"W{int(str_h)}" if str_h > 0 else f"L{int(abs(str_h))}" if str_h < 0 else "even"
        a_label = f"W{int(str_a)}" if str_a > 0 else f"L{int(abs(str_a))}" if str_a < 0 else "even"
        lines.append(f"Streaks: {away} {a_label} vs {home} {h_label}")

    # Season WP
    wp_h = _safe(row, "wp_home")
    wp_a = _safe(row, "wp_away")
    if wp_h is not None and wp_a is not None:
        lines.append(f"Season WP: {away} {wp_a:.3f} vs {home} {wp_h:.3f}")

    return "\n".join(lines)


def _starting_pitchers(row: pd.Series) -> str:
    away = row.get("away_team", "?")
    home = row.get("home_team", "?")
    lines = ["── Starting Pitchers ──"]

    for side, team, prefix in [
        ("away", away, "away_sp"),
        ("home", home, "home_sp"),
    ]:
        pitcher = row.get(f"{side}_pitcher", "?")
        hand = _pitcher_hand_label(row, prefix)
        starts = _safe(row, f"{prefix}_starts")
        starts_str = f", {int(starts)} starts" if starts is not None else ""
        hand_str = f" {hand}" if hand else ""
        lines.append(f"{team}: {pitcher}{hand_str}{starts_str}")

        lines.extend(_pitcher_skill_lines(row, prefix))

        # First inning RA
        fi_s = _safe(row, f"{prefix}_fi_ra_short")
        if fi_s is not None:
            label = "low" if fi_s < 0.4 else "moderate" if fi_s < 0.8 else "elevated"
            lines.append(f"  1st inn RA: {fi_s:.2f} ({label})")

    # Composite diffs (use pre-computed or derive from raw columns)
    lines.append("")
    fip_diff = _diff_or_compute(row, "starter_fip_diff", "home_sp_fip_short", "away_sp_fip_short")
    if fip_diff is not None:
        label = "dog's pitcher BETTER FIP" if fip_diff > 0.3 else "fav's pitcher better FIP" if fip_diff < -0.3 else "similar FIP"
        lines.append(f"Starter FIP diff: {fip_diff:+.2f} ({label})")

    whip_diff = _diff_or_compute(row, "starter_whip_diff", "home_sp_whip_short", "away_sp_whip_short")
    if whip_diff is not None:
        label = "dog's pitcher tighter" if whip_diff > 0.05 else "fav's pitcher tighter" if whip_diff < -0.05 else "similar"
        lines.append(f"Starter WHIP diff: {whip_diff:+.2f} ({label})")

    kbb_diff = _diff_or_compute(row, "starter_kbb_diff", "home_sp_kbb_short", "away_sp_kbb_short")
    if kbb_diff is not None:
        label = "dog's pitcher BETTER command" if kbb_diff > 0.3 else "fav's pitcher better command" if kbb_diff < -0.3 else "similar"
        lines.append(f"Starter K/BB diff: {kbb_diff:+.2f} ({label})")

    ip_diff = _diff_or_compute(row, "starter_recent_ip_diff", "home_sp_ip_per_start_short", "away_sp_ip_per_start_short")
    if ip_diff is not None:
        label = "dog goes deeper" if ip_diff > 0.3 else "fav goes deeper" if ip_diff < -0.3 else "similar"
        lines.append(f"Starter IP/start diff: {ip_diff:+.1f} ({label})")

    # Matchup vs hand
    vs_hand = _matchup_vs_hand_lines(row)
    if vs_hand:
        lines.append("")
        lines.append("── Matchup vs Hand ──")
        lines.extend(vs_hand)

    return "\n".join(lines)


def _bullpen_management(row: pd.Series) -> str:
    away = row.get("away_team", "?")
    home = row.get("home_team", "?")
    lines = ["── Bullpen & Late Game ──"]

    hold_h = _safe(row, "hold_rate_home")
    hold_a = _safe(row, "hold_rate_away")
    close_h = _safe(row, "close_game_wp_home")
    close_a = _safe(row, "close_game_wp_away")
    recov_h = _safe(row, "deficit_recovery_rate_home")
    recov_a = _safe(row, "deficit_recovery_rate_away")

    if hold_h is not None and hold_a is not None:
        lines.append(
            f"Hold rate (lead after 5): {away} {hold_a * 100:.0f}% ({_label_hold(hold_a)}) "
            f"| {home} {hold_h * 100:.0f}% ({_label_hold(hold_h)})"
        )
    else:
        lines.append("Hold rate: N/A (insufficient data)")

    if close_h is not None and close_a is not None:
        lines.append(
            f"Close-game W% (1-2 run): {away} {close_a * 100:.0f}% ({_label_close_wp(close_a)}) "
            f"| {home} {close_h * 100:.0f}% ({_label_close_wp(close_h)})"
        )
    else:
        lines.append("Close-game W%: N/A")

    if recov_h is not None and recov_a is not None:
        lines.append(
            f"Deficit recovery (trailing after 6): {away} {recov_a * 100:.0f}% ({_label_recovery(recov_a)}) "
            f"| {home} {recov_h * 100:.0f}% ({_label_recovery(recov_h)})"
        )
    else:
        lines.append("Deficit recovery: N/A")

    lines.extend(_bullpen_fatigue_lines(row))

    return "\n".join(lines)


def _context(row: pd.Series) -> str:
    lines = ["── Context ──"]

    month = _safe(row, "month")
    if month is not None:
        month = int(month)
        month_names = {4: "April", 5: "May", 6: "June", 7: "July", 8: "August", 9: "September", 10: "October"}
        month_str = month_names.get(month, f"Month {month}")

        # Half-season
        day = int(_safe(row, "day") or 15)
        if month < 7 or (month == 7 and day <= 15):
            half = "1st half (pre-ASG)"
        else:
            half = "2nd half (post-ASG)"
        lines.append(f"Month: {month_str} | Half: {half}")

    gp_h = _safe(row, "games_played_home")
    gp_a = _safe(row, "games_played_away")
    if gp_h is not None and gp_a is not None:
        min_gp = min(gp_h, gp_a)
        reliability = "adequate" if min_gp >= 30 else "limited (early season)" if min_gp >= 10 else "very early season"
        lines.append(f"Games played: {int(gp_a)}/{int(gp_h)} ({reliability} sample)")

    # O/U line (contextual)
    ou = _safe(row, "close_ou")
    if ou is not None:
        label = "low-scoring environment" if ou < 7.5 else "high-scoring environment" if ou > 9.5 else "normal"
        lines.append(f"O/U line: {ou:.1f} ({label})")

    return "\n".join(lines)


# ── Neutral section builders (for Analyst — no betting context) ───────────


def _neutral_team_strength(row: pd.Series) -> str:
    away = row.get("away_team", "?")
    home = row.get("home_team", "?")
    lines = ["-- Team Strength --"]

    rpi_h = _safe(row, "rpi_home")
    rpi_a = _safe(row, "rpi_away")
    rpi_diff = _safe(row, "rpi_diff")
    if rpi_h is not None and rpi_a is not None:
        stronger = away if rpi_diff < -0.005 else home if rpi_diff > 0.005 else "even"
        lines.append(f"RPI: {away} {rpi_a:.3f} vs {home} {rpi_h:.3f} ({stronger} higher)")

    elo_diff = _safe(row, "elo_diff")
    if elo_diff is not None:
        lines.append(f"Elo diff (home-away incl. home bonus): {elo_diff:+.0f}")

    pyth_h = _safe(row, "pyth_wp_home")
    pyth_a = _safe(row, "pyth_wp_away")
    if pyth_h is not None and pyth_a is not None:
        lines.append(f"Pythagorean WP: {away} {pyth_a:.3f} vs {home} {pyth_h:.3f}")

    wrc_h = _safe(row, "wrc_plus_home")
    wrc_a = _safe(row, "wrc_plus_away")
    if wrc_h is not None and wrc_a is not None:
        lines.append(f"wRC+: {away} {wrc_a:.0f} vs {home} {wrc_h:.0f}")

    rpg_h = _safe(row, "rpg_home")
    rpg_a = _safe(row, "rpg_away")
    rapg_h = _safe(row, "rapg_home")
    rapg_a = _safe(row, "rapg_away")
    if rpg_h is not None and rpg_a is not None:
        lines.append(f"Offense RPG: {away} {rpg_a:.2f} vs {home} {rpg_h:.2f}")
    if rapg_h is not None and rapg_a is not None:
        lines.append(f"Defense RAPG: {away} {rapg_a:.2f} vs {home} {rapg_h:.2f} (lower=better)")

    return "\n".join(lines)


def _neutral_pitchers(row: pd.Series) -> str:
    away = row.get("away_team", "?")
    home = row.get("home_team", "?")
    lines = ["-- Starting Pitchers --"]

    for side, team, prefix in [
        ("away", away, "away_sp"),
        ("home", home, "home_sp"),
    ]:
        pitcher = row.get(f"{side}_pitcher", "?")
        hand = _pitcher_hand_label(row, prefix)
        starts = _safe(row, f"{prefix}_starts")
        starts_str = f", {int(starts)} starts" if starts is not None else ""
        hand_str = f" {hand}" if hand else ""
        lines.append(f"{team}: {pitcher}{hand_str}{starts_str}")

        lines.extend(_pitcher_skill_lines(row, prefix))

        fi_s = _safe(row, f"{prefix}_fi_ra_short")
        if fi_s is not None:
            lines.append(f"  1st inning RA: {fi_s:.2f}")

    # Neutral composite diffs (no dog/fav language)
    fip_diff = _diff_or_compute(row, "starter_fip_diff", "home_sp_fip_short", "away_sp_fip_short")
    if fip_diff is not None:
        better = "home" if fip_diff < -0.1 else "away" if fip_diff > 0.1 else "similar"
        lines.append(f"Starter FIP diff (home-away): {fip_diff:+.2f} (better: {better})")

    whip_diff = _diff_or_compute(row, "starter_whip_diff", "home_sp_whip_short", "away_sp_whip_short")
    if whip_diff is not None:
        better = "home" if whip_diff < -0.03 else "away" if whip_diff > 0.03 else "similar"
        lines.append(f"Starter WHIP diff (home-away): {whip_diff:+.2f} (better: {better})")

    kbb_diff = _diff_or_compute(row, "starter_kbb_diff", "home_sp_kbb_short", "away_sp_kbb_short")
    if kbb_diff is not None:
        better = "home" if kbb_diff < -0.3 else "away" if kbb_diff > 0.3 else "similar"
        lines.append(f"Starter K/BB diff (home-away): {kbb_diff:+.2f} (better: {better})")

    ip_diff = _diff_or_compute(row, "starter_recent_ip_diff", "home_sp_ip_per_start_short", "away_sp_ip_per_start_short")
    if ip_diff is not None:
        better = "home" if ip_diff < -0.3 else "away" if ip_diff > 0.3 else "similar"
        lines.append(f"Starter IP/start diff (home-away): {ip_diff:+.1f} (better: {better})")

    # Matchup vs hand
    vs_hand = _matchup_vs_hand_lines(row)
    if vs_hand:
        lines.append("")
        lines.append("-- Matchup vs Hand --")
        lines.extend(vs_hand)

    return "\n".join(lines)


def _neutral_offense_context(row: pd.Series) -> str:
    away = row.get("away_team", "?")
    home = row.get("home_team", "?")
    lines = ["-- Offense & Defense vs League --"]

    off_h = _safe(row, "offense_vs_league_home")
    off_a = _safe(row, "offense_vs_league_away")
    def_h = _safe(row, "defense_vs_league_home")
    def_a = _safe(row, "defense_vs_league_away")

    if off_h is not None and off_a is not None:
        lines.append(
            f"Offense vs league: {away} {off_a * 100:.0f}% ({_label_offense(off_a)}) "
            f"| {home} {off_h * 100:.0f}% ({_label_offense(off_h)})"
        )
        if off_h > 1.10 and off_a > 1.10:
            lines.append("  Note: both lineups above 110% of league average")
    else:
        lines.append("Offense vs league: N/A")

    if def_h is not None and def_a is not None:
        lines.append(
            f"Defense vs league: {away} {def_a * 100:.0f}% ({_label_defense(def_a)}) "
            f"| {home} {def_h * 100:.0f}% ({_label_defense(def_h)})"
        )
    else:
        lines.append("Defense vs league: N/A")

    # Offensive power: multi-run inning rate
    pw_h = _safe(row, "power_rate_home")
    pw_a = _safe(row, "power_rate_away")
    if pw_h is not None and pw_a is not None:
        lines.append(
            f"Offensive power (multi-run inning %): {away} {pw_a:.0%} ({_label_power_rate(pw_a)}) "
            f"| {home} {pw_h:.0%} ({_label_power_rate(pw_h)})"
        )

    return "\n".join(lines)


def _neutral_bullpen_management(row: pd.Series) -> str:
    away = row.get("away_team", "?")
    home = row.get("home_team", "?")
    lines = ["-- Bullpen & Late Game --"]

    hold_h = _safe(row, "hold_rate_home")
    hold_a = _safe(row, "hold_rate_away")
    close_h = _safe(row, "close_game_wp_home")
    close_a = _safe(row, "close_game_wp_away")
    recov_h = _safe(row, "deficit_recovery_rate_home")
    recov_a = _safe(row, "deficit_recovery_rate_away")

    if hold_h is not None and hold_a is not None:
        lines.append(
            f"Hold rate (lead after 5): {away} {hold_a * 100:.0f}% ({_label_hold(hold_a)}) "
            f"| {home} {hold_h * 100:.0f}% ({_label_hold(hold_h)})"
        )
    else:
        lines.append("Hold rate: N/A")

    if close_h is not None and close_a is not None:
        lines.append(
            f"Close-game W% (1-2 run): {away} {close_a * 100:.0f}% ({_label_close_wp(close_a)}) "
            f"| {home} {close_h * 100:.0f}% ({_label_close_wp(close_h)})"
        )
    else:
        lines.append("Close-game W%: N/A")

    if recov_h is not None and recov_a is not None:
        lines.append(
            f"Deficit recovery (trailing after 6): {away} {recov_a * 100:.0f}% ({_label_recovery(recov_a)}) "
            f"| {home} {recov_h * 100:.0f}% ({_label_recovery(recov_h)})"
        )
    else:
        lines.append("Deficit recovery: N/A")

    lines.extend(_bullpen_fatigue_lines(row))

    return "\n".join(lines)


# ── Helpers ───────────────────────────────────────────────────────────────


def _label_offense(ratio: float) -> str:
    """Label offense ratio vs league average."""
    if ratio > 1.10:
        return "STRONG"
    elif ratio > 1.05:
        return "ABOVE AVG"
    elif ratio >= 0.95:
        return "AVERAGE"
    else:
        return "BELOW AVG"


def _label_defense(ratio: float) -> str:
    """Label defense ratio vs league average (lower = better defense)."""
    if ratio < 0.90:
        return "STRONG"
    elif ratio < 0.95:
        return "ABOVE AVG"
    elif ratio <= 1.05:
        return "AVERAGE"
    else:
        return "BELOW AVG"


def _label_hold(rate: float) -> str:
    """Label hold rate (win% when leading after 6)."""
    if rate > 0.80:
        return "ELITE"
    elif rate > 0.72:
        return "STRONG"
    elif rate >= 0.65:
        return "AVERAGE"
    else:
        return "WEAK"


def _label_close_wp(rate: float) -> str:
    """Label close-game win percentage."""
    if rate > 0.55:
        return "STRONG"
    elif rate >= 0.48:
        return "AVERAGE"
    else:
        return "WEAK"


def _label_recovery(rate: float) -> str:
    """Label deficit recovery rate."""
    if rate > 0.25:
        return "GOOD"
    elif rate >= 0.18:
        return "AVERAGE"
    else:
        return "LOW"


def _safe(row: pd.Series, col: str) -> float | None:
    """Safely extract a numeric value, returning None for missing/NaN."""
    val = row.get(col)
    if val is None:
        return None
    try:
        f = float(val)
        return None if np.isnan(f) else f
    except (ValueError, TypeError):
        return None


def _decimal_to_american(dec: float) -> str:
    """Convert decimal odds to American format string."""
    if dec >= 2.0:
        return f"+{round((dec - 1) * 100)}"
    elif dec > 1.0:
        return f"-{round(100 / (dec - 1))}"
    return "+100"


def _label_edge_s3(edge: float) -> str:
    """Label edge for S3 zone (negative edge = dog underpriced)."""
    if edge <= -0.08:
        return "strong signal: dog significantly underpriced"
    elif edge <= -0.05:
        return "strict-zone signal (would auto-bet)"
    elif edge <= -0.03:
        return "moderate: dog somewhat underpriced"
    else:
        return "weak: borderline signal"


def _label_edge_rl(edge: float) -> str:
    """Label edge for RL zone (positive edge = favorite overpriced → tight game)."""
    if edge >= 0.15:
        return "strong signal: favorite significantly overpriced"
    elif edge >= 0.10:
        return "strict-zone signal (would auto-bet)"
    elif edge >= 0.07:
        return "moderate: favorite somewhat overpriced"
    else:
        return "weak: borderline signal"


def _label_rpi_diff(diff: float | None) -> str:
    """Label RPI differential (home - away; negative = dog stronger)."""
    if diff is None:
        return "N/A"
    if diff <= -0.03:
        return "dog MUCH STRONGER"
    elif diff <= -0.01:
        return "dog stronger"
    elif diff <= 0.01:
        return "even"
    elif diff <= 0.03:
        return "fav stronger"
    else:
        return "fav much stronger"


def _label_fip(fip: float) -> str:
    if fip < 3.20:
        return "elite"
    elif fip < 3.80:
        return "good"
    elif fip < 4.30:
        return "average"
    else:
        return "below-avg"


def _label_kbb(kbb: float) -> str:
    # League avg ~2.67, median ~2.67, p75 ~3.7
    if kbb >= 3.5:
        return "elite command"
    elif kbb >= 3.0:
        return "good"
    elif kbb >= 2.5:
        return "average"
    elif kbb >= 2.0:
        return "below average"
    else:
        return "poor command"


def _label_k9(k9: float) -> str:
    if k9 > 9.5:
        return "elite"
    elif k9 > 7.5:
        return "good"
    elif k9 > 5.5:
        return "average"
    else:
        return "low"


def _label_ip_start(ip: float) -> str:
    if ip > 6.0:
        return "deep"
    elif ip > 5.0:
        return "adequate"
    else:
        return "short outings"


def _label_obp_vs_hand(obp: float) -> str:
    # League avg ~.339, p25 ~.326, p75 ~.352
    if obp >= 0.360:
        return "elite"
    elif obp >= 0.350:
        return "above average"
    elif obp >= 0.330:
        return "average"
    elif obp >= 0.315:
        return "below average"
    else:
        return "poor"


def _label_bp_fip(fip: float) -> str:
    if fip < 3.50:
        return "strong"
    elif fip < 4.00:
        return "average"
    else:
        return "weak"


def _label_bp_workload(ip: float) -> str:
    # League avg ~9.5 IP per team per 3 days
    if ip >= 13.0:
        return "very heavy"
    elif ip >= 11.0:
        return "heavy"
    elif ip >= 8.0:
        return "average"
    elif ip >= 5.0:
        return "light"
    else:
        return "very light"


def _label_hold_rate(hr: float) -> str:
    # League avg ~0.82 (after 5 innings), p25=0.75, p75=0.91
    if hr >= 0.91:
        return "elite"
    elif hr >= 0.83:
        return "above avg"
    elif hr >= 0.75:
        return "average"
    elif hr >= 0.65:
        return "below avg"
    else:
        return "poor"


def _label_power_rate(pr: float) -> str:
    # League avg ~0.465, p25=0.42, p75=0.51
    if pr >= 0.52:
        return "explosive"
    elif pr >= 0.47:
        return "above avg"
    elif pr >= 0.42:
        return "average"
    elif pr >= 0.35:
        return "below avg"
    else:
        return "weak"


def _pitcher_hand_label(row: pd.Series, prefix: str) -> str:
    """Return '(RHP)' or '(LHP)' or '' from pitcher hand column."""
    hand = row.get(f"{prefix}_hand")
    if hand == "R":
        return "(RHP)"
    elif hand == "L":
        return "(LHP)"
    return ""


def _pitcher_skill_lines(row: pd.Series, prefix: str) -> list[str]:
    """Build FIP/K-BB/K9/IP-per-start lines for one pitcher."""
    lines = []
    fip_s = _safe(row, f"{prefix}_fip_short")
    fip_l = _safe(row, f"{prefix}_fip_long")
    if fip_s is not None:
        mom_str = ""
        if fip_l is not None:
            fip_mom = fip_s - fip_l
            label = "IMPROVING" if fip_mom < -0.3 else "DECLINING" if fip_mom > 0.3 else "stable"
            mom_str = f" \u2192 momentum {fip_mom:+.2f} ({label})"
        lines.append(f"  FIP: {fip_s:.2f} ({_label_fip(fip_s)}){mom_str}")

    kbb = _safe(row, f"{prefix}_kbb_short")
    k9 = _safe(row, f"{prefix}_k9_short")
    parts = []
    if kbb is not None:
        parts.append(f"K/BB: {kbb:.1f} ({_label_kbb(kbb)})")
    if k9 is not None:
        parts.append(f"K/9: {k9:.1f} ({_label_k9(k9)})")
    if parts:
        lines.append(f"  {'  '.join(parts)}")

    ip = _safe(row, f"{prefix}_ip_per_start_short")
    if ip is not None:
        lines.append(f"  IP/start: {ip:.1f} ({_label_ip_start(ip)})")

    return lines


def _matchup_vs_hand_lines(row: pd.Series) -> list[str]:
    """Build lineup-vs-pitcher-hand matchup lines."""
    away = row.get("away_team", "?")
    home = row.get("home_team", "?")
    lines = []

    home_hand = row.get("home_sp_hand")
    away_hand = row.get("away_sp_hand")

    # Away lineup vs home pitcher's hand
    if home_hand in ("R", "L"):
        col = f"top3_obp_vs_{'rhp' if home_hand == 'R' else 'lhp'}_away"
        obp = _safe(row, col)
        if obp is not None:
            hand_lbl = "RHP" if home_hand == "R" else "LHP"
            lines.append(
                f"{away} top-3 OBP vs {hand_lbl}: {obp:.3f} ({_label_obp_vs_hand(obp)})"
            )

    # Home lineup vs away pitcher's hand
    if away_hand in ("R", "L"):
        col = f"top3_obp_vs_{'rhp' if away_hand == 'R' else 'lhp'}_home"
        obp = _safe(row, col)
        if obp is not None:
            hand_lbl = "RHP" if away_hand == "R" else "LHP"
            lines.append(
                f"{home} top-3 OBP vs {hand_lbl}: {obp:.3f} ({_label_obp_vs_hand(obp)})"
            )

    return lines


def _diff_or_compute(row: pd.Series, diff_col: str, home_col: str, away_col: str) -> float | None:
    """Get pre-computed diff or compute from raw columns (home - away)."""
    val = _safe(row, diff_col)
    if val is not None:
        return val
    h = _safe(row, home_col)
    a = _safe(row, away_col)
    if h is not None and a is not None:
        return h - a
    return None


def _bullpen_fatigue_lines(row: pd.Series) -> list[str]:
    """Build bullpen FIP + workload fatigue lines."""
    away = row.get("away_team", "?")
    home = row.get("home_team", "?")
    lines = []

    bp_fip_h = _safe(row, "bp_fip_short_home")
    bp_fip_a = _safe(row, "bp_fip_short_away")
    if bp_fip_h is not None and bp_fip_a is not None:
        lines.append(
            f"Bullpen FIP: {away} {bp_fip_a:.2f} ({_label_bp_fip(bp_fip_a)}) "
            f"| {home} {bp_fip_h:.2f} ({_label_bp_fip(bp_fip_h)})"
        )

    bp_ip_h = _safe(row, "bp_ip_3d_home")
    bp_ip_a = _safe(row, "bp_ip_3d_away")
    if bp_ip_h is not None and bp_ip_a is not None:
        lines.append(
            f"BP workload (3d IP): {away} {bp_ip_a:.1f} ({_label_bp_workload(bp_ip_a)}) "
            f"| {home} {bp_ip_h:.1f} ({_label_bp_workload(bp_ip_h)})"
        )

    return lines


# ── Coinflip (CF) zone section builders ──────────────────────────────────


def _header_cf(row: pd.Series) -> str:
    date = row.get("date", "?")
    away = row.get("away_team", "?")
    home = row.get("home_team", "?")
    spread = _safe(row, "odds_spread")
    spread_str = f"spread={spread * 100:.1f}%" if spread is not None else ""
    return f"GAME: {away} @ {home} — {date} | Zone: PICK'EM ({spread_str})"


def _odds_section_cf(row: pd.Series) -> str:
    away = row.get("away_team", "?")
    home = row.get("home_team", "?")
    away_dec = _safe(row, "away_decimal_odds")
    home_dec = _safe(row, "home_decimal_odds")
    away_imp = _safe(row, "away_implied_prob")
    home_imp = _safe(row, "home_implied_prob")

    lines = ["── Odds (near pick'em) ──"]
    if home_dec is not None and home_imp is not None:
        lines.append(
            f"HOME: {home} — odds {home_dec:.2f} ({_decimal_to_american(home_dec)}), "
            f"implied {home_imp * 100:.1f}%"
        )
    if away_dec is not None and away_imp is not None:
        lines.append(
            f"AWAY: {away} — odds {away_dec:.2f} ({_decimal_to_american(away_dec)}), "
            f"implied {away_imp * 100:.1f}%"
        )
    if home_imp is not None and away_imp is not None:
        spread_pct = abs(home_imp - away_imp) * 100
        lines.append(f"Probability gap: {spread_pct:.1f}%")
    return "\n".join(lines)


def _model_signal_cf(row: pd.Series) -> str:
    away = row.get("away_team", "?")
    home = row.get("home_team", "?")
    lines = ["── Model Signal ──"]

    edge = _safe(row, "edge_consensus")
    if edge is not None:
        # Direction only — no strength or numeric edge.
        # Positive edge → model says fav overpriced → lean away
        # Negative → lean home
        lean_team = away if edge > 0 else home
        lines.append(f"model lean: {lean_team}")

    return "\n".join(lines)


def _team_strength_cf(row: pd.Series) -> str:
    """Symmetric team strength — no dog/fav labels."""
    away = row.get("away_team", "?")
    home = row.get("home_team", "?")
    lines = ["── Team Strength ──"]

    rpi_h = _safe(row, "rpi_home")
    rpi_a = _safe(row, "rpi_away")
    if rpi_h is not None and rpi_a is not None:
        stronger = away if rpi_a > rpi_h else home if rpi_h > rpi_a else "even"
        lines.append(f"RPI: {away} {rpi_a:.3f} vs {home} {rpi_h:.3f} ({stronger} higher)")

    elo_diff = _safe(row, "elo_diff")
    if elo_diff is not None:
        lines.append(f"Elo diff (home-away incl. home bonus): {elo_diff:+.0f}")

    pyth_h = _safe(row, "pyth_wp_home")
    pyth_a = _safe(row, "pyth_wp_away")
    if pyth_h is not None and pyth_a is not None:
        lines.append(f"Pythagorean WP: {away} {pyth_a:.3f} vs {home} {pyth_h:.3f}")

    rpg_h = _safe(row, "rpg_home")
    rpg_a = _safe(row, "rpg_away")
    rapg_h = _safe(row, "rapg_home")
    rapg_a = _safe(row, "rapg_away")
    if rpg_h is not None and rpg_a is not None:
        lines.append(f"Offense RPG: {away} {rpg_a:.2f} vs {home} {rpg_h:.2f}")
    if rapg_h is not None and rapg_a is not None:
        lines.append(f"Defense RAPG: {away} {rapg_a:.2f} vs {home} {rapg_h:.2f} (lower=better)")

    return "\n".join(lines)


# ── Over/Under feature cards ──────────────────────────────────────────────


@dataclass
class OUFeatureCard:
    """O/U betting card — totals framing, no dog/fav language."""

    game_id: str
    prompt_text: str

    @classmethod
    def from_row(cls, row: pd.Series, p_under: float, scenario_text: str = "") -> "OUFeatureCard":
        date = row.get("date", "unknown")
        away = row.get("away_team", "?")
        home = row.get("home_team", "?")
        game_id = f"{date}_{away}_{home}"

        ou_line = _safe(row, "close_ou") or 0
        sections = [
            f"GAME: {away} @ {home} — {date} | O/U Line: {ou_line:.1f} | Model P(under): {p_under * 100:.0f}%",
            _ou_scoring_environment(row),
            _ou_starting_pitchers(row),
            _ou_bullpen_state(row),
            _neutral_offense_context(row),
            _ou_recent_trends(row),
            _ou_context(row),
        ]
        if scenario_text:
            sections.append(f"── Analyst Scenario ──\n{scenario_text}")

        prompt_text = "\n\n".join(s for s in sections if s)
        return cls(game_id=game_id, prompt_text=prompt_text)

    @classmethod
    def from_row_over(cls, row: pd.Series, p_over: float, scenario_text: str = "") -> "OUFeatureCard":
        date = row.get("date", "unknown")
        away = row.get("away_team", "?")
        home = row.get("home_team", "?")
        game_id = f"{date}_{away}_{home}"

        ou_line = _safe(row, "close_ou") or 0
        sections = [
            f"GAME: {away} @ {home} — {date} | O/U Line: {ou_line:.1f} | Model P(over): {p_over * 100:.0f}%",
            _ou_scoring_environment(row),
            _ou_starting_pitchers(row),
            _ou_bullpen_state(row),
            _neutral_offense_context(row),
            _ou_recent_trends(row),
            _ou_context(row),
        ]
        if scenario_text:
            sections.append(f"── Analyst Scenario ──\n{scenario_text}")

        prompt_text = "\n\n".join(s for s in sections if s)
        return cls(game_id=game_id, prompt_text=prompt_text)

    def to_prompt(self) -> str:
        return self.prompt_text


@dataclass
class OUAnalystCard:
    """Neutral O/U card for analyst — no P(under), no betting context."""

    game_id: str
    prompt_text: str

    @classmethod
    def from_row(cls, row: pd.Series) -> "OUAnalystCard":
        date = row.get("date", "unknown")
        away = row.get("away_team", "?")
        home = row.get("home_team", "?")
        game_id = f"{date}_{away}_{home}"

        ou_line = _safe(row, "close_ou") or 0
        sections = [
            f"GAME: {away} @ {home} — {date} | O/U Line: {ou_line:.1f}",
            _ou_scoring_environment(row),
            _ou_starting_pitchers(row),
            _ou_bullpen_state(row),
            _neutral_offense_context(row),
            _ou_recent_trends(row),
            _ou_context(row),
        ]
        prompt_text = "\n\n".join(s for s in sections if s)
        return cls(game_id=game_id, prompt_text=prompt_text)

    @classmethod
    def from_row_over(cls, row: pd.Series) -> "OUAnalystCard":
        """Analyst card for OVER pipeline — same neutral data as UNDER.

        All pitching/bullpen/momentum data is embedded in the shared
        section builders. No directional summary or indicator counts.
        """
        # Delegate to from_row — the shared sections now contain all data
        return cls.from_row(row)

    def to_prompt(self) -> str:
        return self.prompt_text


def _label_vs_league_avg(val: float, lg_avg: float) -> str:
    """Label value relative to league average."""
    pct = val / lg_avg if lg_avg else 1.0
    if pct >= 1.15:
        return "well above avg"
    elif pct >= 1.05:
        return "above avg"
    elif pct >= 0.95:
        return "near avg"
    elif pct >= 0.85:
        return "below avg"
    else:
        return "well below avg"


def _ou_scoring_environment(row: pd.Series) -> str:
    away = row.get("away_team", "?")
    home = row.get("home_team", "?")
    lines = ["── Scoring Environment ──"]

    # League average: ~4.42 RPG per team, ~8.85 combined
    LG_RPG = 4.42

    rpg_h = _safe(row, "rpg_home")
    rpg_a = _safe(row, "rpg_away")
    if rpg_h is not None and rpg_a is not None:
        combined = rpg_h + rpg_a
        label = _label_vs_league_avg(combined, LG_RPG * 2)
        lines.append(f"Combined RPG (season): {combined:.2f} ({away} {rpg_a:.2f} + {home} {rpg_h:.2f}) [{label}, lg avg {LG_RPG * 2:.2f}]")

    rpg10_h = _safe(row, "rpg_last10_home")
    rpg10_a = _safe(row, "rpg_last10_away")
    if rpg10_h is not None and rpg10_a is not None:
        combined10 = rpg10_h + rpg10_a
        label = _label_vs_league_avg(combined10, LG_RPG * 2)
        lines.append(f"Combined RPG (last 10): {combined10:.2f} ({away} {rpg10_a:.2f} + {home} {rpg10_h:.2f}) [{label}]")

    # Scoring momentum: recent vs season
    if all(v is not None for v in [rpg_h, rpg_a, rpg10_h, rpg10_a]):
        momentum = (rpg10_h + rpg10_a) - (rpg_h + rpg_a)
        lines.append(f"Scoring momentum (L10 - season): {momentum:+.2f}")

    rapg_h = _safe(row, "rapg_home")
    rapg_a = _safe(row, "rapg_away")
    if rapg_h is not None and rapg_a is not None:
        combined_ra = rapg_h + rapg_a
        label = _label_vs_league_avg(combined_ra, LG_RPG * 2)
        lines.append(f"Combined RAPG: {combined_ra:.2f} ({away} {rapg_a:.2f} + {home} {rapg_h:.2f}) [{label}]")

    ou_line = _safe(row, "close_ou")
    if rpg_h is not None and rpg_a is not None and ou_line is not None:
        rpg_vs = (rpg_h + rpg_a) - ou_line
        lines.append(f"RPG vs O/U line: {rpg_vs:+.2f}")

    if rpg10_h is not None and rpg10_a is not None and ou_line is not None:
        rpg10_vs = (rpg10_h + rpg10_a) - ou_line
        lines.append(f"Recent RPG vs O/U line: {rpg10_vs:+.2f}")

    if rapg_h is not None and rapg_a is not None and ou_line is not None:
        rapg_vs = (rapg_h + rapg_a) - ou_line
        lines.append(f"Combined RAPG vs O/U line: {rapg_vs:+.2f}")

    return "\n".join(lines)


def _ou_starting_pitchers(row: pd.Series) -> str:
    away = row.get("away_team", "?")
    home = row.get("home_team", "?")
    lines = ["── Pitching: Starters ──"]

    for side, team, prefix in [("away", away, "away_sp"), ("home", home, "home_sp")]:
        pitcher = row.get(f"{side}_pitcher", "?")
        hand = _pitcher_hand_label(row, prefix)
        starts = _safe(row, f"{prefix}_starts")
        starts_str = f", {int(starts)} starts" if starts is not None else ""
        hand_str = f" {hand}" if hand else ""
        lines.append(f"{team}: {pitcher}{hand_str}{starts_str}")
        lines.extend(_pitcher_skill_lines(row, prefix))

    # Combined metrics
    fip_h = _safe(row, "home_sp_fip_short")
    fip_a = _safe(row, "away_sp_fip_short")
    if fip_h is not None and fip_a is not None:
        combined_fip = fip_h + fip_a
        label = "both strong" if combined_fip < 7.0 else "both weak" if combined_fip > 9.0 else "mixed"
        lines.append(f"Combined starter FIP: {combined_fip:.2f} ({label})")

    ip_h = _safe(row, "home_sp_ip_per_start_short")
    ip_a = _safe(row, "away_sp_ip_per_start_short")
    if ip_h is not None and ip_a is not None:
        combined_ip = ip_h + ip_a
        label = "deep starters" if combined_ip > 12.0 else "short starters" if combined_ip < 10.0 else "average"
        lines.append(f"Combined IP/start: {combined_ip:.1f} ({label})")

    # Quality floor (worst starter)
    if fip_h is not None and fip_a is not None:
        floor = max(fip_h, fip_a)
        floor_label = _label_fip(floor)
        lines.append(f"Quality floor (worst starter FIP): {floor:.2f} ({floor_label})")

    # Matchup vs hand
    vs_hand = _matchup_vs_hand_lines(row)
    if vs_hand:
        lines.append("")
        lines.append("── Lineup vs Pitcher Hand ──")
        lines.extend(vs_hand)

    return "\n".join(lines)


def _ou_bullpen_state(row: pd.Series) -> str:
    away = row.get("away_team", "?")
    home = row.get("home_team", "?")
    lines = ["── Pitching: Bullpen ──"]
    # League avg BP FIP ~3.84, workload ~9.5 IP/3d, hold rate ~0.86

    # Season FIP (short window)
    bp_fip_h = _safe(row, "bp_fip_short_home")
    bp_fip_a = _safe(row, "bp_fip_short_away")
    if bp_fip_h is not None and bp_fip_a is not None:
        lines.append(
            f"Bullpen FIP (season): {away} {bp_fip_a:.2f} ({_label_bp_fip(bp_fip_a)}) "
            f"| {home} {bp_fip_h:.2f} ({_label_bp_fip(bp_fip_h)})"
        )

    # 7-game FIP
    bp_7g_h = _safe(row, "bp_fip_7g_home")
    bp_7g_a = _safe(row, "bp_fip_7g_away")
    if bp_7g_h is not None and bp_7g_a is not None:
        lines.append(
            f"Bullpen FIP (7-game): {away} {bp_7g_a:.2f} ({_label_bp_fip(bp_7g_a)}) "
            f"| {home} {bp_7g_h:.2f} ({_label_bp_fip(bp_7g_h)})"
        )

    # Per-team oscillator (7g - long)
    # Oscillator = 7g FIP - season FIP. Positive = deteriorating (recent worse than season).
    # Negative = improving (recent better than season). Zero = stable.
    bp_long_h = _safe(row, "bp_fip_long_home")
    bp_long_a = _safe(row, "bp_fip_long_away")
    if bp_7g_h is not None and bp_long_h is not None:
        osc_h = bp_7g_h - bp_long_h
        lines.append(f"  {home} bullpen oscillator: {osc_h:+.2f} (+ = deteriorating, - = improving)")
    if bp_7g_a is not None and bp_long_a is not None:
        osc_a = bp_7g_a - bp_long_a
        lines.append(f"  {away} bullpen oscillator: {osc_a:+.2f} (+ = deteriorating, - = improving)")

    # Combined bullpen momentum
    if all(v is not None for v in [bp_7g_h, bp_7g_a, bp_long_h, bp_long_a]):
        osc_combined = (bp_7g_h - bp_long_h) + (bp_7g_a - bp_long_a)
        lines.append(f"Combined bullpen momentum: {osc_combined:+.2f}")

    # Workload — league avg ~9.5 IP per team per 3 days
    bp_ip_h = _safe(row, "bp_ip_3d_home")
    bp_ip_a = _safe(row, "bp_ip_3d_away")
    if bp_ip_h is not None and bp_ip_a is not None:
        lines.append(
            f"BP workload (3d IP): {away} {bp_ip_a:.1f} ({_label_bp_workload(bp_ip_a)}) "
            f"| {home} {bp_ip_h:.1f} ({_label_bp_workload(bp_ip_h)}) [lg avg ~9.5]"
        )

    # Hold rate (after 5 innings) — league avg ~0.82
    hold_h = _safe(row, "hold_rate_home")
    hold_a = _safe(row, "hold_rate_away")
    if hold_h is not None and hold_a is not None:
        lines.append(
            f"Hold rate: {away} {hold_a:.2f} ({_label_hold_rate(hold_a)}) "
            f"| {home} {hold_h:.2f} ({_label_hold_rate(hold_h)}) [lg avg 0.82]"
        )

    # Fatigue composite (oscillator + workload)
    if all(v is not None for v in [bp_7g_h, bp_7g_a, bp_long_h, bp_long_a, bp_ip_h, bp_ip_a]):
        osc_c = (bp_7g_h - bp_long_h) + (bp_7g_a - bp_long_a)
        wl_c = bp_ip_h + bp_ip_a
        lines.append(f"Fatigue composite: oscillator {osc_c:+.2f}, combined workload {wl_c:.0f} IP [lg avg ~19]")

    return "\n".join(lines)


def _ou_recent_trends(row: pd.Series) -> str:
    lines = ["── Recent Trends ──"]

    fi_h = _safe(row, "fi_score_rate_home")
    fi_a = _safe(row, "fi_score_rate_away")
    if fi_h is not None and fi_a is not None:
        combined = fi_h + fi_a
        label = "low (slow starters)" if combined < 0.45 else "high (fast scoring)" if combined > 0.60 else "average"
        lines.append(f"Combined 1st-inning scoring rate: {combined:.2f} ({label})")

    return "\n".join(lines)


def _ou_context(row: pd.Series) -> str:
    lines = ["── Context ──"]

    month = _safe(row, "month")
    if month is not None:
        month = int(month)
        month_names = {4: "April", 5: "May", 6: "June", 7: "July", 8: "August", 9: "September", 10: "October"}
        month_str = month_names.get(month, f"Month {month}")
        day = int(_safe(row, "day") or 15)
        half = "1st half (pre-ASG)" if month < 7 or (month == 7 and day <= 15) else "2nd half (post-ASG)"
        lines.append(f"Month: {month_str} | Half: {half}")

    gp_h = _safe(row, "games_played_home")
    gp_a = _safe(row, "games_played_away")
    if gp_h is not None and gp_a is not None:
        min_gp = min(gp_h, gp_a)
        reliability = "adequate" if min_gp >= 30 else "limited (early season)" if min_gp >= 10 else "very early season"
        lines.append(f"Games played: {int(gp_a)}/{int(gp_h)} ({reliability} sample)")

    ou = _safe(row, "close_ou")
    if ou is not None:
        label = "low-scoring environment" if ou < 7.5 else "high-scoring environment" if ou > 9.5 else "normal"
        lines.append(f"O/U line: {ou:.1f} ({label})")

    return "\n".join(lines)


# ── OVER-specific section builders ───────────────────────────────────────


def _ou_starting_pitchers_neutral(row: pd.Series) -> str:
    """Starting pitchers for OVER card — neutral title (no 'run suppression')."""
    away = row.get("away_team", "?")
    home = row.get("home_team", "?")
    lines = ["── Starting Pitchers ──"]

    for side, team, prefix in [("away", away, "away_sp"), ("home", home, "home_sp")]:
        pitcher = row.get(f"{side}_pitcher", "?")
        hand = _pitcher_hand_label(row, prefix)
        starts = _safe(row, f"{prefix}_starts")
        starts_str = f", {int(starts)} starts" if starts is not None else ""
        hand_str = f" {hand}" if hand else ""
        lines.append(f"{team}: {pitcher}{hand_str}{starts_str}")
        lines.extend(_pitcher_skill_lines(row, prefix))

    # Combined metrics
    fip_h = _safe(row, "home_sp_fip_short")
    fip_a = _safe(row, "away_sp_fip_short")
    if fip_h is not None and fip_a is not None:
        combined_fip = fip_h + fip_a
        label = "both strong" if combined_fip < 7.0 else "both weak" if combined_fip > 9.0 else "mixed"
        lines.append(f"Combined starter FIP: {combined_fip:.2f} ({label})")

    ip_h = _safe(row, "home_sp_ip_per_start_short")
    ip_a = _safe(row, "away_sp_ip_per_start_short")
    if ip_h is not None and ip_a is not None:
        combined_ip = ip_h + ip_a
        label = "deep starters" if combined_ip > 12.0 else "short starters" if combined_ip < 10.0 else "average"
        lines.append(f"Combined IP/start: {combined_ip:.1f} ({label})")

    # Quality floor (worst starter)
    if fip_h is not None and fip_a is not None:
        floor = max(fip_h, fip_a)
        floor_label = _label_fip(floor)
        lines.append(f"Quality floor (worst starter FIP): {floor:.2f} ({floor_label})")

    # Matchup vs hand
    vs_hand = _matchup_vs_hand_lines(row)
    if vs_hand:
        lines.append("")
        lines.append("── Lineup vs Pitcher Hand ──")
        lines.extend(vs_hand)

    return "\n".join(lines)


def _over_recent_trends(row: pd.Series) -> str:
    """Recent trends for OVER card — scoring acceleration instead of hold rate."""
    lines = ["── Recent Trends ──"]

    fi_h = _safe(row, "fi_score_rate_home")
    fi_a = _safe(row, "fi_score_rate_away")
    if fi_h is not None and fi_a is not None:
        combined = fi_h + fi_a
        label = "low (slow starters)" if combined < 0.45 else "high (fast scoring)" if combined > 0.60 else "average"
        lines.append(f"Combined 1st-inning scoring rate: {combined:.2f} ({label})")

    rpg_h = _safe(row, "rpg_home")
    rpg10_h = _safe(row, "rpg_last10_home")
    rpg_a = _safe(row, "rpg_away")
    rpg10_a = _safe(row, "rpg_last10_away")
    away = row.get("away_team", "?")
    home = row.get("home_team", "?")
    if rpg10_h is not None and rpg_h is not None:
        delta_h = rpg10_h - rpg_h
        label = "surging" if delta_h > 0.5 else "cooling" if delta_h < -0.5 else "stable"
        lines.append(f"{home} scoring trend: {delta_h:+.2f} ({label})")
    if rpg10_a is not None and rpg_a is not None:
        delta_a = rpg10_a - rpg_a
        label = "surging" if delta_a > 0.5 else "cooling" if delta_a < -0.5 else "stable"
        lines.append(f"{away} scoring trend: {delta_a:+.2f} ({label})")

    return "\n".join(lines)


def _over_signal_summary(row: pd.Series) -> str:
    """Aggregated OVER signals from key ML features."""
    lines = ["── OVER Signal Summary ──"]
    indicators_fired = []

    # 1. Combined bp_fip_osc (#1 ML feature, 38% importance)
    bp_7g_h = _safe(row, "bp_fip_7g_home")
    bp_7g_a = _safe(row, "bp_fip_7g_away")
    bp_long_h = _safe(row, "bp_fip_long_home")
    bp_long_a = _safe(row, "bp_fip_long_away")
    if all(v is not None for v in [bp_7g_h, bp_7g_a, bp_long_h, bp_long_a]):
        osc_combined = (bp_7g_h - bp_long_h) + (bp_7g_a - bp_long_a)
        if osc_combined > 0.5:
            label = "BOTH deteriorating — strong OVER signal"
            indicators_fired.append("bullpen fatigue")
        elif osc_combined > 0.0:
            label = "slightly deteriorating"
        elif osc_combined < -0.5:
            label = "BOTH freshening — UNDER signal, caution"
        else:
            label = "stable"
        lines.append(f"Combined bullpen oscillator: {osc_combined:+.2f} ({label})")

    # 2. RPG momentum (last10 vs season)
    rpg_h = _safe(row, "rpg_home")
    rpg_a = _safe(row, "rpg_away")
    rpg10_h = _safe(row, "rpg_last10_home")
    rpg10_a = _safe(row, "rpg_last10_away")
    if all(v is not None for v in [rpg_h, rpg_a, rpg10_h, rpg10_a]):
        momentum = (rpg10_h + rpg10_a) - (rpg_h + rpg_a)
        if momentum > 0.5:
            label = "scoring trending UP"
            indicators_fired.append("scoring momentum")
        elif momentum > 0:
            label = "slightly up"
        elif momentum < -0.5:
            label = "scoring trending DOWN — caution"
        else:
            label = "flat"
        lines.append(f"Scoring momentum (recent-season): {momentum:+.2f} ({label})")

    # 3. RAPG vs line
    rapg_h = _safe(row, "rapg_home")
    rapg_a = _safe(row, "rapg_away")
    ou_line = _safe(row, "close_ou")
    if rapg_h is not None and rapg_a is not None and ou_line is not None:
        rapg_vs = (rapg_h + rapg_a) - ou_line
        if rapg_vs > 0.5:
            label = "both staffs ALLOWING more than line"
            indicators_fired.append("pitching leaking runs")
        elif rapg_vs > 0:
            label = "slightly above line"
        else:
            label = "below line"
        lines.append(f"Combined RAPG vs line: {rapg_vs:+.2f} ({label})")

    # 4. Quality floor (worst starter)
    fip_h = _safe(row, "home_sp_fip_short")
    fip_a = _safe(row, "away_sp_fip_short")
    if fip_h is not None and fip_a is not None:
        worst = max(fip_h, fip_a)
        if worst > 4.5:
            lines.append(f"Worst starter FIP: {worst:.2f} — weak arm, could yield 4-5 runs alone")
            indicators_fired.append("weak quality floor")

    # 5. Fatigue composite (osc + workload)
    bp_ip_h = _safe(row, "bp_ip_3d_home")
    bp_ip_a = _safe(row, "bp_ip_3d_away")
    if all(v is not None for v in [bp_7g_h, bp_7g_a, bp_long_h, bp_long_a, bp_ip_h, bp_ip_a]):
        osc_c = (bp_7g_h - bp_long_h) + (bp_7g_a - bp_long_a)
        wl_c = bp_ip_h + bp_ip_a
        if osc_c > 0.3 and wl_c > 8:
            lines.append(f"Fatigue composite: HIGH RISK (osc {osc_c:+.1f}, workload {wl_c:.0f} IP)")
            if "bullpen fatigue" not in indicators_fired:
                indicators_fired.append("fatigue composite")

    lines.append(f"OVER indicators fired: {len(indicators_fired)}/5 [{', '.join(indicators_fired) or 'none'}]")
    return "\n".join(lines)


# ── Coinflip (CF) zone section builders ──────────────────────────────────


def _starting_pitchers_cf(row: pd.Series) -> str:
    """Starting pitchers section with neutral diff labels."""
    away = row.get("away_team", "?")
    home = row.get("home_team", "?")
    lines = ["── Starting Pitchers ──"]

    for side, team, prefix in [("away", away, "away_sp"), ("home", home, "home_sp")]:
        pitcher = row.get(f"{side}_pitcher", "?")
        hand = _pitcher_hand_label(row, prefix)
        starts = _safe(row, f"{prefix}_starts")
        starts_str = f", {int(starts)} starts" if starts is not None else ""
        hand_str = f" {hand}" if hand else ""
        lines.append(f"{team}: {pitcher}{hand_str}{starts_str}")

        lines.extend(_pitcher_skill_lines(row, prefix))

        fi_s = _safe(row, f"{prefix}_fi_ra_short")
        if fi_s is not None:
            label = "low" if fi_s < 0.4 else "moderate" if fi_s < 0.8 else "elevated"
            lines.append(f"  1st inn RA: {fi_s:.2f} ({label})")

    lines.append("")
    fip_diff = _diff_or_compute(row, "starter_fip_diff", "home_sp_fip_short", "away_sp_fip_short")
    if fip_diff is not None:
        better = "away" if fip_diff > 0.3 else "home" if fip_diff < -0.3 else "similar"
        lines.append(f"Starter FIP diff (home-away): {fip_diff:+.2f} (better: {better})")

    whip_diff = _diff_or_compute(row, "starter_whip_diff", "home_sp_whip_short", "away_sp_whip_short")
    if whip_diff is not None:
        better = "away" if whip_diff > 0.05 else "home" if whip_diff < -0.05 else "similar"
        lines.append(f"Starter WHIP diff (home-away): {whip_diff:+.2f} (better: {better})")

    kbb_diff = _diff_or_compute(row, "starter_kbb_diff", "home_sp_kbb_short", "away_sp_kbb_short")
    if kbb_diff is not None:
        better = "away" if kbb_diff > 0.3 else "home" if kbb_diff < -0.3 else "similar"
        lines.append(f"Starter K/BB diff (home-away): {kbb_diff:+.2f} (better: {better})")

    ip_diff = _diff_or_compute(row, "starter_recent_ip_diff", "home_sp_ip_per_start_short", "away_sp_ip_per_start_short")
    if ip_diff is not None:
        better = "away" if ip_diff > 0.3 else "home" if ip_diff < -0.3 else "similar"
        lines.append(f"Starter IP/start diff (home-away): {ip_diff:+.1f} (better: {better})")

    # Matchup vs hand
    vs_hand = _matchup_vs_hand_lines(row)
    if vs_hand:
        lines.append("")
        lines.append("── Matchup vs Hand ──")
        lines.extend(vs_hand)

    return "\n".join(lines)
