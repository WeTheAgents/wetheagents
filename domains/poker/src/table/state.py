"""Game state and action data models for poker bot."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Street(Enum):
    PREFLOP = "preflop"
    FLOP = "flop"
    TURN = "turn"
    RIVER = "river"


class ActionType(Enum):
    FOLD = "fold"
    CHECK = "check"
    CALL = "call"
    RAISE = "raise"
    ALL_IN = "all_in"


class Position(Enum):
    """Positions at a poker table (6-max and full ring)."""
    UTG = "UTG"
    UTG1 = "UTG+1"
    UTG2 = "UTG+2"
    MP = "MP"
    HJ = "HJ"
    CO = "CO"
    BTN = "BTN"
    SB = "SB"
    BB = "BB"


# Positional order from earliest to latest
POSITION_ORDER_9MAX = [
    Position.UTG, Position.UTG1, Position.UTG2,
    Position.MP, Position.HJ, Position.CO,
    Position.BTN, Position.SB, Position.BB,
]
POSITION_ORDER_6MAX = [
    Position.UTG, Position.MP, Position.CO,
    Position.BTN, Position.SB, Position.BB,
]


@dataclass
class PlayerState:
    """State of a single player at the table."""
    name: str
    stack: float
    bet: float = 0.0
    is_active: bool = True  # still in the hand
    is_all_in: bool = False
    hole_cards: list[str] | None = None  # visible only at showdown


@dataclass
class Action:
    """A poker action to execute."""
    type: ActionType
    amount: float | None = None  # for RAISE/ALL_IN

    def __repr__(self) -> str:
        if self.amount is not None:
            return f"{self.type.value} {self.amount:.0f}"
        return self.type.value


@dataclass
class GameState:
    """Complete game state snapshot for a single decision point."""
    # Cards
    hole_cards: list[str]  # e.g. ["Ah", "Kd"]
    community_cards: list[str] = field(default_factory=list)  # e.g. ["7c", "3d", "2h"]

    # Money
    pot: float = 0.0
    my_stack: float = 0.0
    big_blind: float = 0.0

    # Position & table
    my_position: Position | None = None
    position_dist: int = -1  # clockwise distance from dealer: 0=BTN,1=SB,2=BB,3=CO...
    num_players: int = 0  # total at table
    players_in_hand: int = 0  # still active this hand
    players: list[PlayerState] = field(default_factory=list)

    # Betting context
    street: Street = Street.PREFLOP
    to_call: float = 0.0  # amount needed to call
    min_raise: float = 0.0  # minimum raise amount
    max_raise: float = 0.0  # max raise (usually all-in)

    # Opponent model (populated by engine from tracker)
    villain_fold_pct: float = 0.45  # how often villain folds to raises (0.0-1.0)
    villain_aggression: float = 1.5  # aggression factor: (bets+raises)/calls
    in_position: bool = True  # are we last to act postflop?

    # Action tracking (populated by connector/engine)
    checked_this_street: bool = False  # did we check earlier this street? (for check-raise)
    villain_checked_back_flop: bool = False  # did villain check back on flop? (for probe bet)

    # Exploit context (populated by engine from tracker)
    bb_is_afk: bool = False  # BB is likely AFK (6+ consecutive folds)
    bb_consecutive_folds: int = 0  # BB's current fold streak
    sb_is_afk: bool = False  # SB is likely AFK
    has_limper: bool = False  # there is a known limping station in the hand
    limper_frequency: float = 0.0  # highest limp freq among active limpers
    bb_is_passive_short: bool = False  # BB is short-stacked (<10BB) and passive (PFR<0.25)
    opener_is_steal: bool = False  # raiser opened from CO/BTN/SB (steal position)
    opener_pfr: float = 0.0  # raiser's PFR stat from tracker

    # Pre-computed helpers
    @property
    def effective_stack_bb(self) -> float:
        """Stack in big blinds."""
        if self.big_blind <= 0:
            return 0.0
        return self.my_stack / self.big_blind

    @property
    def pot_odds(self) -> float:
        """Pot odds as a fraction: to_call / (pot + to_call)."""
        if self.to_call <= 0:
            return 0.0
        return self.to_call / (self.pot + self.to_call)

    @property
    def is_preflop(self) -> bool:
        return self.street == Street.PREFLOP

    @property
    def spr(self) -> float:
        """Stack-to-pot ratio."""
        if self.pot <= 0:
            return float("inf")
        return self.my_stack / self.pot


def get_position(seat_index: int, dealer_index: int, num_players: int) -> Position:
    """Map seat index to positional name given dealer position."""
    if num_players <= 0:
        return Position.BTN

    order = POSITION_ORDER_6MAX if num_players <= 6 else POSITION_ORDER_9MAX
    # Trim to actual player count
    positions = order[-num_players:] if num_players <= len(order) else order

    # Distance from dealer (button), clockwise
    distance = (seat_index - dealer_index) % num_players
    if distance < len(positions):
        return positions[distance]
    return Position.MP  # fallback


def canonicalize_hand(card1: str, card2: str) -> str:
    """Convert two cards to canonical form: 'AKs', 'AKo', 'AA'.

    Cards format: rank + suit, e.g. 'Ah', 'Kd', 'Tc', '9s'.
    """
    rank_order = "AKQJT98765432"
    r1, s1 = card1[0].upper(), card1[1].lower()
    r2, s2 = card2[0].upper(), card2[1].lower()

    # Sort by rank (higher first)
    if rank_order.index(r1) > rank_order.index(r2):
        r1, r2 = r2, r1
        s1, s2 = s2, s1

    if r1 == r2:
        return f"{r1}{r2}"  # pair: "AA", "KK"
    elif s1 == s2:
        return f"{r1}{r2}s"  # suited: "AKs"
    else:
        return f"{r1}{r2}o"  # offsuit: "AKo"
