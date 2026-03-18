"""Tests for postflop strategy engine (equity calculator + decisions)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.strategy.postflop import (
    board_wetness,
    calculate_equity,
    call_ev,
    get_postflop_action,
    implied_pot_odds,
    is_wawb,
    semi_bluff_ev,
    stack_leverage,
)
from src.table.state import ActionType, GameState, Street


def _make_postflop_state(
    hole: list[str],
    board: list[str],
    pot: float = 100,
    stack: float = 1000,
    to_call: float = 0,
    bb: float = 20,
    players_in_hand: int = 2,
) -> GameState:
    if len(board) == 3:
        street = Street.FLOP
    elif len(board) == 4:
        street = Street.TURN
    else:
        street = Street.RIVER

    return GameState(
        hole_cards=hole,
        community_cards=board,
        pot=pot,
        my_stack=stack,
        big_blind=bb,
        to_call=to_call,
        street=street,
        num_players=6,
        players_in_hand=players_in_hand,
        min_raise=bb * 2,
        max_raise=stack,
    )


class TestEquityCalculator:
    """Test Monte Carlo equity estimation accuracy."""

    def test_aa_vs_random_preflop(self):
        """AA has ~85% equity vs a random hand."""
        equity = calculate_equity(["Ah", "As"], [], num_opponents=1, iterations=2000)
        assert 0.80 <= equity <= 0.90, f"AA equity should be ~85%, got {equity:.2f}"

    def test_aa_vs_kk_preflop(self):
        """AA vs KK is ~80% (but we don't know opponent's cards, so vs random ~85%)."""
        equity = calculate_equity(["Ah", "As"], [], num_opponents=1, iterations=2000)
        assert equity > 0.75, f"AA should have >75% equity, got {equity:.2f}"

    def test_top_pair_on_flop(self):
        """AK on A-7-2 rainbow should have strong equity vs 1 opponent."""
        equity = calculate_equity(
            ["Ah", "Kd"], ["As", "7c", "2h"],
            num_opponents=1, iterations=2000,
        )
        assert equity > 0.70, f"Top pair top kicker should have >70% equity, got {equity:.2f}"

    def test_flush_draw_with_overcards(self):
        """AKs flush draw + overcards should have ~65-80% equity on flop vs 1 opponent."""
        equity = calculate_equity(
            ["Ah", "Kh"], ["7h", "3h", "2c"],
            num_opponents=1, iterations=2000,
        )
        # AKs here has: nut flush draw (9 outs) + 2 overcards (6 outs) = ~70%+
        assert 0.60 <= equity <= 0.82, f"Nut flush draw + overcards equity: {equity:.2f}"

    def test_more_opponents_lower_equity(self):
        """Equity decreases with more opponents."""
        eq1 = calculate_equity(["Ah", "Kd"], [], num_opponents=1, iterations=2000)
        eq3 = calculate_equity(["Ah", "Kd"], [], num_opponents=3, iterations=2000)
        assert eq1 > eq3, f"AK equity should be lower vs 3 opponents ({eq3:.2f}) than vs 1 ({eq1:.2f})"

    def test_river_with_made_hand(self):
        """Full board, made pair should give clear equity."""
        equity = calculate_equity(
            ["Ah", "Kd"], ["As", "7c", "2h", "9d", "3s"],
            num_opponents=1, iterations=2000,
        )
        assert equity > 0.60, f"Top pair on river should have decent equity: {equity:.2f}"


class TestPostflopDecisions:
    """Test postflop action decisions."""

    def test_strong_hand_bets_when_checked_to(self):
        """Strong hand should bet, not check."""
        state = _make_postflop_state(
            hole=["Ah", "As"],
            board=["Ad", "7c", "2h"],
            pot=100,
            to_call=0,
        )
        action = get_postflop_action(state)
        assert action.type == ActionType.RAISE, \
            f"Set on flop should bet, got {action.type}"

    def test_weak_hand_checks(self):
        """Weak hand with no equity should check when free."""
        state = _make_postflop_state(
            hole=["7h", "2c"],
            board=["As", "Kd", "Qh", "Jc", "Ts"],
            pot=100,
            to_call=0,
        )
        action = get_postflop_action(state)
        assert action.type == ActionType.CHECK, \
            f"No pair no draw should check, got {action.type}"

    def test_calls_with_pot_odds(self):
        """Should call when equity > pot odds."""
        state = _make_postflop_state(
            hole=["Ah", "Kh"],
            board=["7h", "3h", "2c"],  # nut flush draw
            pot=200,
            to_call=50,  # getting 5:1, need ~17% equity (have ~45%)
        )
        action = get_postflop_action(state)
        assert action.type in (ActionType.CALL, ActionType.RAISE), \
            f"Flush draw with good odds should call/raise, got {action.type}"


class TestImpliedOdds:
    """Test implied odds calculation."""

    def test_river_no_implied_odds(self):
        """River has no implied odds — returns direct pot odds."""
        state = _make_postflop_state(
            hole=["Ah", "Kh"],
            board=["7h", "3h", "2c", "9d", "Js"],
            pot=200, to_call=100,
        )
        impl = implied_pot_odds(state)
        direct = state.pot_odds  # 100/300 = 0.333
        assert abs(impl - direct) < 0.001, "River implied == direct pot odds"

    def test_flop_deep_stacks_reduce_threshold(self):
        """Flop with deep stacks should lower the call threshold."""
        state = _make_postflop_state(
            hole=["Ah", "Kh"],
            board=["7h", "3c", "2c"],
            pot=100, to_call=50, stack=2000,  # SPR=20
        )
        impl = implied_pot_odds(state)
        direct = state.pot_odds  # 50/150 = 0.333
        assert impl < direct * 0.6, f"Deep flop implied={impl:.2f} should be much < direct={direct:.2f}"

    def test_short_stack_minimal_implied(self):
        """Short stack = little implied odds benefit."""
        state = _make_postflop_state(
            hole=["Ah", "Kh"],
            board=["7h", "3c", "2c"],
            pot=100, to_call=50, stack=120,  # SPR=1.2
        )
        impl = implied_pot_odds(state)
        direct = state.pot_odds
        # With SPR < 2, multiplier is only 1.2
        assert impl > direct * 0.7, f"Short stack implied={impl:.2f} should be close to direct={direct:.2f}"


class TestFoldEquity:
    """Test fold equity and semi-bluff EV calculations."""

    def test_semi_bluff_ev_positive_vs_nit(self):
        """Semi-bluff raise should be +EV against a nit (fold_pct=0.60)."""
        state = _make_postflop_state(
            hole=["Ah", "Kh"],
            board=["7h", "3h", "2c"],  # flush draw ~35% equity
            pot=100, to_call=50, stack=1000,
        )
        state.villain_fold_pct = 0.60  # nit folds often
        equity = 0.35  # flush draw
        raise_size = 150  # raise to 150

        ev = semi_bluff_ev(state, equity, raise_size)
        assert ev > 0, f"Semi-bluff vs nit should be +EV, got {ev:.1f}"

    def test_semi_bluff_ev_negative_vs_calling_station(self):
        """Semi-bluff raise should be -EV: low equity, big raise, station."""
        state = _make_postflop_state(
            hole=["9h", "8h"],
            board=["Ah", "3c", "2d"],
            pot=100, to_call=50, stack=1000,
        )
        state.villain_fold_pct = 0.15  # extreme calling station
        equity = 0.15  # almost no outs
        raise_size = 200  # big raise into calling station = suicide

        ev = semi_bluff_ev(state, equity, raise_size)
        assert ev < 0, f"Big bluff raise vs station with no equity should be -EV, got {ev:.1f}"

    def test_call_ev_basic(self):
        """Call EV calculation sanity check."""
        state = _make_postflop_state(
            hole=["Ah", "Kh"],
            board=["7h", "3h", "2c"],
            pot=200, to_call=50,
        )
        # EV(call) = equity * (pot + to_call) - (1-equity) * to_call
        # = 0.50 * 250 - 0.50 * 50 = 125 - 25 = 100
        ev = call_ev(state, 0.50)
        assert abs(ev - 100.0) < 0.1, f"Expected call_ev=100, got {ev:.1f}"

    def test_semi_bluff_raise_chosen_vs_nit(self):
        """Engine should semi-bluff raise with a moderate draw vs a nit."""
        # Use bare flush draw without overcards (~35% equity, in draw range)
        state = _make_postflop_state(
            hole=["6h", "5h"],
            board=["Kh", "9h", "2c"],  # flush draw only, ~35% equity
            pot=100, to_call=50, stack=1000,
        )
        state.villain_fold_pct = 0.65  # nit folds often
        action = get_postflop_action(state)
        # With ~35% equity + 65% fold rate, semi-bluff raise is clearly +EV
        assert action.type == ActionType.RAISE, \
            f"Should semi-bluff raise draw vs nit, got {action.type}"

    def test_no_bluff_raise_vs_calling_station(self):
        """Engine should NOT bluff-raise with weak hand vs calling station on turn."""
        # Turn (not flop) so implied odds are weaker, and use truly trash hand
        state = _make_postflop_state(
            hole=["7c", "2d"],
            board=["Ah", "Kd", "Qs", "Jc"],  # turn, complete whiff, ~5% equity
            pot=200, to_call=150, stack=1000,  # big bet to face
        )
        state.villain_fold_pct = 0.15  # extreme calling station
        action = get_postflop_action(state)
        assert action.type == ActionType.FOLD, \
            f"Should fold garbage vs calling station on turn, got {action.type}"

    def test_semi_bluff_check_with_fold_equity(self):
        """When checked to with a draw vs a nit, should bet (not check)."""
        state = _make_postflop_state(
            hole=["Jh", "Th"],
            board=["9h", "3h", "2c"],  # flush draw + open-ender
            pot=100, to_call=0, stack=1000,
        )
        state.villain_fold_pct = 0.60
        action = get_postflop_action(state)
        # With massive draw + fold equity, should bet
        assert action.type == ActionType.RAISE, \
            f"Strong draw with fold equity should bet, got {action.type}"


class TestBoardTexture:
    """Test board wetness analysis."""

    def test_dry_rainbow_board(self):
        """K-7-2 rainbow = very dry."""
        w = board_wetness(["Kh", "7c", "2d"])
        assert w < 0.20, f"K72 rainbow should be dry, got {w:.2f}"

    def test_monotone_board(self):
        """Three of same suit = very wet."""
        w = board_wetness(["Jh", "9h", "4h"])
        assert w >= 0.45, f"Monotone board should be wet, got {w:.2f}"

    def test_connected_two_tone(self):
        """J-T-9 two-tone = soaking wet."""
        w = board_wetness(["Jh", "Th", "9c"])
        assert w > 0.50, f"JT9 two-tone should be very wet, got {w:.2f}"

    def test_paired_dry_board(self):
        """K-K-3 rainbow = dry (paired reduces draws)."""
        w = board_wetness(["Kh", "Kc", "3d"])
        assert w < 0.15, f"KK3 rainbow should be dry, got {w:.2f}"

    def test_turn_adds_draws(self):
        """Adding a card can increase wetness."""
        flop_w = board_wetness(["Kh", "7c", "2d"])
        turn_w = board_wetness(["Kh", "7c", "2d", "8c"])
        # 8c adds a flush draw possibility and 7-8 connects
        assert turn_w > flop_w, "Turn card should increase wetness"

    def test_stack_leverage_deep(self):
        """Deep stacks = high leverage."""
        assert stack_leverage(10.0) > stack_leverage(3.0)
        assert stack_leverage(10.0) == 1.20
        assert stack_leverage(2.0) == 1.0

    def test_stack_leverage_short(self):
        """Short stacks = no leverage."""
        assert stack_leverage(1.5) == 1.0


class TestWAWB:
    """Test Way Ahead / Way Behind logic."""

    def test_wawb_detected_dry_board(self):
        """Medium equity on dry board = WA/WB."""
        assert is_wawb(0.55, 0.10, 2) is True

    def test_wawb_not_on_wet_board(self):
        """Medium equity on wet board = NOT WA/WB (too many draws)."""
        assert is_wawb(0.55, 0.50, 2) is False

    def test_wawb_not_multiway(self):
        """WA/WB doesn't apply multiway."""
        assert is_wawb(0.55, 0.10, 3) is False

    def test_wawb_not_with_strong_hand(self):
        """Strong hand is not WA/WB (should value bet)."""
        assert is_wawb(0.75, 0.10, 2) is False

    def test_wawb_check_behind_ip_dry_board(self):
        """Pocket pair under board on dry board IP: check behind (pot control).

        55 on K-9-3 rainbow: equity ~58% vs random. Classic WA/WB —
        we're ahead of air, behind everything else. Betting folds
        worse and gets called by better.
        """
        state = _make_postflop_state(
            hole=["5c", "5d"],
            board=["Kh", "9c", "3s"],  # bone dry rainbow
            pot=80, to_call=0, stack=1000,
        )
        state.in_position = True
        state.villain_aggression = 2.5  # aggressive villain
        action = get_postflop_action(state)
        assert action.type == ActionType.CHECK, \
            f"WA/WB IP on dry board should check behind, got {action.type}"

    def test_wawb_call_vs_aggro(self):
        """Pocket pair under board facing bet from maniac: call (catching bluffs)."""
        state = _make_postflop_state(
            hole=["5c", "5d"],
            board=["Kh", "9c", "3s"],  # dry board
            pot=100, to_call=60, stack=1000,
        )
        state.villain_aggression = 3.0  # maniac fires with air
        state.villain_fold_pct = 0.30
        action = get_postflop_action(state)
        assert action.type == ActionType.CALL, \
            f"WA/WB vs maniac should call (catching bluffs), got {action.type}"

    def test_wawb_fold_vs_passive(self):
        """Pocket pair under board facing bet from nit: fold (they have it)."""
        state = _make_postflop_state(
            hole=["5c", "5d"],
            board=["Kh", "9c", "3s"],  # dry board
            pot=100, to_call=60, stack=1000,
        )
        state.villain_aggression = 0.7  # passive nit — bets = has it
        state.villain_fold_pct = 0.60
        action = get_postflop_action(state)
        assert action.type == ActionType.FOLD, \
            f"WA/WB vs passive nit should fold (they have it), got {action.type}"

    def test_wawb_thin_value_opp_vs_passive(self):
        """Medium hand OOP on dry board vs passive: bet thin for value.

        Passive villain won't bet for us — we have to extract value ourselves.
        """
        state = _make_postflop_state(
            hole=["5c", "5d"],
            board=["Kh", "9c", "3s"],  # dry board
            pot=80, to_call=0, stack=1000,
        )
        state.in_position = False
        state.villain_aggression = 0.7  # passive — won't bet for us
        action = get_postflop_action(state)
        assert action.type == ActionType.RAISE, \
            f"WA/WB OOP vs passive should thin value bet, got {action.type}"

    def test_bluff_better_on_dry_than_wet(self):
        """Semi-bluff EV should be higher on dry board than wet."""
        dry_state = _make_postflop_state(
            hole=["Ah", "5h"],
            board=["Kd", "7c", "2s"],  # dry rainbow
            pot=100, to_call=50, stack=1000,
        )
        dry_state.villain_fold_pct = 0.50

        wet_state = _make_postflop_state(
            hole=["Ah", "5h"],
            board=["Jh", "Th", "9c"],  # super wet
            pot=100, to_call=50, stack=1000,
        )
        wet_state.villain_fold_pct = 0.50

        dry_ev = semi_bluff_ev(dry_state, 0.30, 100)
        wet_ev = semi_bluff_ev(wet_state, 0.30, 100)
        assert dry_ev > wet_ev, \
            f"Bluff should be better on dry ({dry_ev:.1f}) than wet ({wet_ev:.1f})"
