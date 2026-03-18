"""Opponent statistics tracker: VPIP, PFR, aggression factor per player."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class PlayerStats:
    """Running statistics for a single opponent."""
    name: str
    hands_seen: int = 0
    vpip_count: int = 0   # voluntarily put money in pot (not forced blind)
    pfr_count: int = 0    # preflop raise
    cbet_opportunities: int = 0
    cbet_count: int = 0
    fold_to_cbet_opportunities: int = 0
    fold_to_cbet_count: int = 0
    bets_and_raises: int = 0
    calls: int = 0
    # Fold-to-aggression: how often they fold when facing a postflop raise
    fold_to_raise_opportunities: int = 0
    fold_to_raise_count: int = 0

    @property
    def vpip(self) -> float:
        """Voluntarily Put money In Pot (%). Key stat."""
        if self.hands_seen < 5:
            return 0.25  # assume average until we have data
        return self.vpip_count / self.hands_seen

    @property
    def pfr(self) -> float:
        """Pre-Flop Raise (%)."""
        if self.hands_seen < 5:
            return 0.15
        return self.pfr_count / self.hands_seen

    @property
    def vpip_pfr_gap(self) -> float:
        """Gap between VPIP and PFR. High gap = calling station."""
        return self.vpip - self.pfr

    @property
    def aggression_factor(self) -> float:
        """(Bets + Raises) / Calls. Higher = more aggressive."""
        if self.calls == 0:
            return 2.0  # default
        return self.bets_and_raises / self.calls

    @property
    def cbet_frequency(self) -> float:
        """How often they continuation bet."""
        if self.cbet_opportunities < 3:
            return 0.65  # assume average
        return self.cbet_count / self.cbet_opportunities

    @property
    def fold_to_raise(self) -> float:
        """How often they fold when facing a postflop raise/bet.

        This is the core stat for fold equity. High fold_to_raise (>0.55)
        means semi-bluff raises are very profitable against this player.
        """
        if self.fold_to_raise_opportunities < 5:
            # Default by player type when not enough data
            return self._default_fold_to_raise()
        return self.fold_to_raise_count / self.fold_to_raise_opportunities

    def _default_fold_to_raise(self) -> float:
        """Estimate fold-to-raise from player type or defaults."""
        if self.hands_seen < 15:
            return 0.45  # conservative default
        ptype = self.player_type
        return {
            "TAG": 0.50,  # competent, folds correctly
            "LAG": 0.35,  # aggressive, doesn't fold easily
            "LP": 0.40,   # calling station, calls too much
            "TP": 0.60,   # nit, folds a LOT — prime target
        }.get(ptype, 0.45)

    @property
    def fold_to_cbet(self) -> float:
        """How often they fold to continuation bets."""
        if self.fold_to_cbet_opportunities < 3:
            return 0.50  # assume average
        return self.fold_to_cbet_count / self.fold_to_cbet_opportunities

    @property
    def player_type(self) -> str:
        """Classify player into archetype after enough hands."""
        if self.hands_seen < 15:
            return "unknown"

        loose = self.vpip > 0.30
        aggressive = self.pfr / self.vpip > 0.50 if self.vpip > 0 else False

        if loose and aggressive:
            return "LAG"  # loose-aggressive (maniac)
        elif loose and not aggressive:
            return "LP"   # loose-passive (calling station)
        elif not loose and aggressive:
            return "TAG"  # tight-aggressive (competent)
        else:
            return "TP"   # tight-passive (nit)

    @property
    def is_reliable(self) -> bool:
        """Do we have enough data for this player?"""
        return self.hands_seen >= 20

    def summary(self) -> str:
        """Human-readable summary."""
        return (
            f"{self.name}: {self.player_type} "
            f"VPIP={self.vpip:.0%} PFR={self.pfr:.0%} "
            f"AF={self.aggression_factor:.1f} "
            f"({self.hands_seen} hands)"
        )


class OpponentTracker:
    """Tracks statistics for all opponents at the table."""

    def __init__(self):
        self._players: dict[str, PlayerStats] = {}

    def get_stats(self, name: str) -> PlayerStats:
        """Get or create stats for a player."""
        if name not in self._players:
            self._players[name] = PlayerStats(name=name)
        return self._players[name]

    def record_hand(self, name: str, vpip: bool, pfr: bool) -> None:
        """Record a player's preflop actions for this hand."""
        stats = self.get_stats(name)
        stats.hands_seen += 1
        if vpip:
            stats.vpip_count += 1
        if pfr:
            stats.pfr_count += 1

    def record_postflop_action(self, name: str, is_bet_or_raise: bool) -> None:
        """Record postflop aggression."""
        stats = self.get_stats(name)
        if is_bet_or_raise:
            stats.bets_and_raises += 1
        else:
            stats.calls += 1

    def record_cbet(self, name: str, had_opportunity: bool, did_cbet: bool) -> None:
        """Record c-bet stats."""
        stats = self.get_stats(name)
        if had_opportunity:
            stats.cbet_opportunities += 1
            if did_cbet:
                stats.cbet_count += 1

    def record_fold_to_raise(self, name: str, faced_raise: bool, folded: bool) -> None:
        """Record fold-to-raise stats (postflop aggression response)."""
        stats = self.get_stats(name)
        if faced_raise:
            stats.fold_to_raise_opportunities += 1
            if folded:
                stats.fold_to_raise_count += 1

    def record_fold_to_cbet(self, name: str, faced_cbet: bool, folded: bool) -> None:
        """Record fold-to-cbet stats."""
        stats = self.get_stats(name)
        if faced_cbet:
            stats.fold_to_cbet_opportunities += 1
            if folded:
                stats.fold_to_cbet_count += 1

    def reset(self) -> None:
        """Reset all stats (e.g., when changing tables in MTT)."""
        self._players.clear()
        logger.info("Opponent stats reset (table change)")

    def print_summary(self) -> None:
        """Log summary of all tracked players."""
        logger.info("=== Opponent Stats ===")
        for stats in sorted(self._players.values(), key=lambda s: s.hands_seen, reverse=True):
            if stats.hands_seen >= 5:
                logger.info(f"  {stats.summary()}")
