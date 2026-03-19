"""Opponent statistics tracker: VPIP, PFR, aggression factor per player."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum

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

    # Exploit-tracking fields
    consecutive_folds: int = 0       # current fold streak
    max_consecutive_folds: int = 0   # longest streak observed
    limp_count: int = 0              # times player open-limped preflop
    limp_opportunities: int = 0      # times player could have open-limped

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

    @property
    def is_likely_afk(self) -> bool:
        """Player is likely AFK if they've folded 6+ hands in a row."""
        return self.consecutive_folds >= 6

    @property
    def limp_frequency(self) -> float:
        """How often this player open-limps preflop."""
        if self.limp_opportunities < 5:
            return 0.0  # not enough data
        return self.limp_count / self.limp_opportunities

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
            stats.consecutive_folds = 0  # reset streak
        else:
            stats.consecutive_folds += 1
            stats.max_consecutive_folds = max(
                stats.max_consecutive_folds, stats.consecutive_folds,
            )
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

    def record_limp(self, name: str, had_opportunity: bool, did_limp: bool) -> None:
        """Record preflop limp stats."""
        stats = self.get_stats(name)
        if had_opportunity:
            stats.limp_opportunities += 1
            if did_limp:
                stats.limp_count += 1

    def print_summary(self) -> None:
        """Log summary of all tracked players."""
        logger.info("=== Opponent Stats ===")
        for stats in sorted(self._players.values(), key=lambda s: s.hands_seen, reverse=True):
            if stats.hands_seen >= 5:
                logger.info(f"  {stats.summary()}")


# --- Game Log Parsing ---

class LogEventType(Enum):
    """Types of events parsed from the game log."""
    FOLD = "fold"
    CHECK = "check"
    CALL = "call"
    RAISE = "raise"
    ALL_IN = "all_in"
    SHOW = "show"
    WIN = "win"
    NEW_HAND = "new_hand"
    FLOP = "flop"
    TURN = "turn"
    RIVER = "river"
    UNKNOWN = "unknown"


@dataclass
class LogEvent:
    """A parsed event from the game log."""
    type: LogEventType
    player: str = ""
    amount: float = 0.0
    cards: list[str] = field(default_factory=list)


# Regex patterns for PokerNow game log lines.
# PokerNow uses "name @ id" format in CSV but may vary in DOM.
# These patterns are flexible: they strip optional " @ <id>" suffixes.
_LOG_PATTERNS: list[tuple[re.Pattern, LogEventType]] = [
    (re.compile(r'^"?(.+?)"?\s+folds', re.IGNORECASE), LogEventType.FOLD),
    (re.compile(r'^"?(.+?)"?\s+checks', re.IGNORECASE), LogEventType.CHECK),
    (re.compile(r'^"?(.+?)"?\s+calls\s+([\d,]+)', re.IGNORECASE), LogEventType.CALL),
    (re.compile(r'^"?(.+?)"?\s+raises\s+to\s+([\d,]+)', re.IGNORECASE), LogEventType.RAISE),
    (re.compile(r'^"?(.+?)"?\s+bets\s+([\d,]+)', re.IGNORECASE), LogEventType.RAISE),
    (re.compile(r'^"?(.+?)"?\s+(?:goes\s+)?all[\s-]?in.*?([\d,]+)', re.IGNORECASE), LogEventType.ALL_IN),
    (re.compile(r'^"?(.+?)"?\s+shows\s+\[(.+?)\]', re.IGNORECASE), LogEventType.SHOW),
    (re.compile(r'^"?(.+?)"?\s+wins\s+([\d,]+)', re.IGNORECASE), LogEventType.WIN),
    (re.compile(r'(?:starting|hand)\s*#?\s*(\d+)', re.IGNORECASE), LogEventType.NEW_HAND),
    (re.compile(r'flop\s*[:\[]', re.IGNORECASE), LogEventType.FLOP),
    (re.compile(r'turn\s*[:\[]', re.IGNORECASE), LogEventType.TURN),
    (re.compile(r'river\s*[:\[]', re.IGNORECASE), LogEventType.RIVER),
]


def parse_log_entry(text: str) -> LogEvent:
    """Parse a game log line into a structured event.

    Handles PokerNow format: "Player @ id" prefix + action text.
    Strips the " @ id" suffix from player names if present.
    """
    text = text.strip()
    if not text:
        return LogEvent(type=LogEventType.UNKNOWN)

    for pattern, event_type in _LOG_PATTERNS:
        match = pattern.search(text)
        if match:
            groups = match.groups()

            if event_type == LogEventType.NEW_HAND:
                return LogEvent(type=event_type)

            if event_type in (LogEventType.FLOP, LogEventType.TURN, LogEventType.RIVER):
                return LogEvent(type=event_type)

            player = _clean_player_name(groups[0]) if groups else ""

            if event_type == LogEventType.SHOW:
                cards = groups[1].split() if len(groups) > 1 else []
                return LogEvent(type=event_type, player=player, cards=cards)

            amount = 0.0
            if len(groups) > 1 and groups[1]:
                amount = float(groups[1].replace(",", ""))

            return LogEvent(type=event_type, player=player, amount=amount)

    return LogEvent(type=LogEventType.UNKNOWN)


def _clean_player_name(name: str) -> str:
    """Strip ' @ id' suffix from PokerNow player names."""
    # "PlayerName @ abc123" -> "PlayerName"
    at_idx = name.rfind(" @ ")
    if at_idx > 0:
        return name[:at_idx].strip()
    return name.strip().strip('"')


class HandRecorder:
    """State machine that tracks a single hand and feeds stats to the tracker.

    Processes game log events in order and calls the appropriate
    OpponentTracker.record_* methods when the hand ends.
    """

    def __init__(self, tracker: OpponentTracker, my_name: str = ""):
        self.tracker = tracker
        self.my_name = my_name
        self._reset()

    def _reset(self) -> None:
        """Reset per-hand state."""
        self._street = "preflop"
        self._players_acted: dict[str, list[LogEventType]] = {}
        self._preflop_raiser: str | None = None
        self._preflop_vpip: set[str] = set()
        self._preflop_pfr: set[str] = set()
        self._preflop_limps: set[str] = set()
        self._has_preflop_raise = False
        self._flop_first_bet_by: str | None = None
        self._hand_active = False

    def process_event(self, event: LogEvent) -> None:
        """Feed a parsed log event into the state machine."""
        if event.type == LogEventType.NEW_HAND:
            if self._hand_active:
                self._finalize_hand()
            self._reset()
            self._hand_active = True
            return

        if event.type == LogEventType.UNKNOWN:
            return

        # Street transitions
        if event.type == LogEventType.FLOP:
            self._street = "flop"
            return
        if event.type == LogEventType.TURN:
            self._street = "turn"
            return
        if event.type == LogEventType.RIVER:
            self._street = "river"
            return

        if not self._hand_active:
            return

        player = event.player
        if not player or player == self.my_name:
            return  # skip our own actions

        # Track actions
        if player not in self._players_acted:
            self._players_acted[player] = []
        self._players_acted[player].append(event.type)

        # Preflop tracking
        if self._street == "preflop":
            if event.type in (LogEventType.CALL, LogEventType.RAISE, LogEventType.ALL_IN):
                self._preflop_vpip.add(player)
            if event.type in (LogEventType.RAISE, LogEventType.ALL_IN):
                self._preflop_pfr.add(player)
                self._has_preflop_raise = True
                self._preflop_raiser = player
            # Detect limps: call without a prior raise
            if event.type == LogEventType.CALL and not self._has_preflop_raise:
                self._preflop_limps.add(player)

        # Postflop tracking
        if self._street in ("flop", "turn", "river"):
            if event.type in (LogEventType.RAISE, LogEventType.ALL_IN):
                self.tracker.record_postflop_action(player, is_bet_or_raise=True)
            elif event.type == LogEventType.CALL:
                self.tracker.record_postflop_action(player, is_bet_or_raise=False)

            # Track c-bet (first bet on flop by preflop raiser)
            if self._street == "flop" and self._flop_first_bet_by is None:
                if event.type in (LogEventType.RAISE, LogEventType.ALL_IN):
                    self._flop_first_bet_by = player

            # Track fold-to-raise
            if event.type == LogEventType.FOLD:
                # If there was a bet/raise before this fold on this street
                self.tracker.record_fold_to_raise(player, faced_raise=True, folded=True)
            elif event.type == LogEventType.CALL:
                self.tracker.record_fold_to_raise(player, faced_raise=True, folded=False)

        # Hand-ending events
        if event.type == LogEventType.WIN:
            self._finalize_hand()
            self._hand_active = False

    def _finalize_hand(self) -> None:
        """End of hand: record all accumulated stats."""
        all_players = set(self._players_acted.keys())

        for player in all_players:
            vpip = player in self._preflop_vpip
            pfr = player in self._preflop_pfr
            self.tracker.record_hand(player, vpip=vpip, pfr=pfr)

            # Limp tracking: player had opportunity to act preflop
            # and either limped or didn't (but had the chance)
            is_limp = player in self._preflop_limps
            self.tracker.record_limp(player, had_opportunity=True, did_limp=is_limp)

        # C-bet tracking
        if self._preflop_raiser and self._preflop_raiser in all_players:
            did_cbet = self._flop_first_bet_by == self._preflop_raiser
            had_opp = self._street != "preflop"  # hand went to flop
            self.tracker.record_cbet(
                self._preflop_raiser, had_opportunity=had_opp, did_cbet=did_cbet,
            )

    def flush(self) -> None:
        """Force finalize current hand (e.g. at session end)."""
        if self._hand_active:
            self._finalize_hand()
            self._hand_active = False
