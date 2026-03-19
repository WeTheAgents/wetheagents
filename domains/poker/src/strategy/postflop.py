"""Postflop strategy: Monte Carlo equity + pot odds + implied odds."""

from __future__ import annotations

import logging
import random

from treys import Card, Deck, Evaluator

from src.strategy.blockers import blocker_adjustment
from src.strategy.board import board_wetness, range_advantage
from src.table.state import Action, ActionType, GameState, Position, Street

logger = logging.getLogger(__name__)

_evaluator = Evaluator()


def calculate_equity(
    hole_cards: list[str],
    community_cards: list[str],
    num_opponents: int = 1,
    iterations: int = 1000,
) -> float:
    """Monte Carlo equity estimation.

    Deals random opponent hands and remaining board cards,
    evaluates all hands, returns win probability [0.0, 1.0].
    """
    # Convert to treys format
    my_hand = [Card.new(c) for c in hole_cards]
    board = [Card.new(c) for c in community_cards]

    dead_cards = set(my_hand + board)
    remaining_board = 5 - len(board)

    wins = 0
    ties = 0

    for _ in range(iterations):
        # Build a deck without known cards
        deck = Deck()
        deck.cards = [c for c in deck.cards if c not in dead_cards]
        random.shuffle(deck.cards)

        # Deal remaining community cards
        sim_board = board.copy()
        idx = 0
        for _ in range(remaining_board):
            sim_board.append(deck.cards[idx])
            idx += 1

        # Deal opponent hands
        my_rank = _evaluator.evaluate(my_hand, sim_board)
        best_opp_rank = 7463  # worst possible

        for _ in range(num_opponents):
            opp_hand = [deck.cards[idx], deck.cards[idx + 1]]
            idx += 2
            opp_rank = _evaluator.evaluate(opp_hand, sim_board)
            best_opp_rank = min(best_opp_rank, opp_rank)

        # Lower rank = better hand in treys
        if my_rank < best_opp_rank:
            wins += 1
        elif my_rank == best_opp_rank:
            ties += 1

    return (wins + ties * 0.5) / iterations


def get_hand_strength_class(equity: float) -> str:
    """Classify hand strength for logging."""
    if equity >= 0.80:
        return "monster"
    elif equity >= 0.65:
        return "strong"
    elif equity >= 0.50:
        return "decent"
    elif equity >= 0.35:
        return "marginal"
    else:
        return "weak"




# board_wetness is now in src.strategy.board (imported above)


def stack_leverage(spr: float) -> float:
    """Stack leverage multiplier for fold equity.

    When we have a deep stack and raise, the opponent faces not just
    this bet but the THREAT of future bets up to all-in. A raise on
    the flop with SPR=10 effectively says "I'm prepared to put in
    10x the pot". This scares opponents with medium-strength hands.

    Returns a multiplier (1.0 = no leverage, up to 1.20).
    """
    if spr > 8:
        return 1.20  # deep: massive leverage, opponent fears stacking
    elif spr > 5:
        return 1.12
    elif spr > 3:
        return 1.06
    else:
        return 1.0  # short: no leverage, stacks too shallow


def is_wawb(equity: float, wetness: float, players_in_hand: int) -> bool:
    """Detect Way Ahead / Way Behind situations.

    WA/WB = we have a medium-strength hand on a dry board where:
    - We're either way ahead (villain has air) or way behind (villain has us crushed)
    - Betting accomplishes nothing: worse hands fold, better hands call
    - Correct play: pot control (check) and let villain bluff

    Conditions:
    - Medium equity (0.45-0.62): not strong enough to value-bet heavy,
      not weak enough to fold. Hands with 63%+ equity (TPTK, overpairs)
      should value-bet, not pot-control.
    - Dry board (wetness < 0.30): few draws means the situation won't
      change much on later streets
    - Heads-up: multiway pots have too many ranges to WA/WB
    """
    return (
        0.45 <= equity <= 0.62
        and wetness < 0.30
        and players_in_hand <= 2
    )


def implied_pot_odds(state: GameState) -> float:
    """Calculate pot odds adjusted for implied odds.

    Implied odds account for money we can win on future streets if we hit
    our draw. Deeper stacks (higher SPR) and more streets remaining = better
    implied odds.

    Example: flush draw on flop, pot=100, to_call=50, stack=2000.
    - Direct pot odds: 50/150 = 33%
    - Implied with SPR>5: 50/(150*2.5) = 13%
    - Flush draw ~35% equity -> easy call with implied odds.
    """
    if state.to_call <= 0:
        return 0.0

    direct = state.pot_odds

    if state.street == Street.RIVER:
        return direct

    spr = state.spr

    if state.street == Street.FLOP:
        if spr > 5:
            multiplier = 2.5
        elif spr > 2:
            multiplier = 1.8
        else:
            multiplier = 1.2
    elif state.street == Street.TURN:
        if spr > 3:
            multiplier = 1.8
        elif spr > 1.5:
            multiplier = 1.4
        else:
            multiplier = 1.1
    else:
        multiplier = 1.0

    effective_pot = (state.pot + state.to_call) * multiplier
    implied = state.to_call / effective_pot

    logger.debug(
        f"  implied odds: direct={direct:.2f} -> implied={implied:.2f} "
        f"(SPR={spr:.1f}, mult={multiplier:.1f})"
    )
    return implied

def semi_bluff_ev(
    state: GameState,
    equity: float,
    raise_size: float,
) -> float:
    """Calculate EV of a semi-bluff raise using fold equity.

    EV(raise) = P(fold_eff) * current_pot
              + (1 - P(fold_eff)) * [equity * new_pot - raise_cost]

    Fold probability is adjusted by:
    - Board texture: dry boards = villain folds more (fewer draws to call with)
    - Stack leverage: deep stacks = villain folds more (fears future bets)

    Returns EV in chips. Positive = profitable raise.
    """
    base_fold = state.villain_fold_pct

    # Board texture adjustment: dry boards amplify fold equity,
    # wet boards reduce it (opponent has draws to call with)
    wetness = board_wetness(state.community_cards)
    texture_adj = 0.10 * (0.5 - wetness)  # dry=+0.05, wet=-0.05

    # Stack leverage: deep stacks threaten future bets
    leverage = stack_leverage(state.spr)

    # Blocker effect: holding cards that block villain's strong hands
    blocker_adj = blocker_adjustment(state.hole_cards, state.community_cards)

    # Effective fold probability (clamped to 0.05-0.90)
    fold_pct = max(0.05, min(0.90, base_fold * leverage + texture_adj + blocker_adj))

    pot = state.pot + state.to_call  # pot including villain's bet

    # When villain folds: we win the current pot
    ev_fold = fold_pct * pot

    # When villain calls: we play for bigger pot with our equity.
    # We invest raise_size chips; win new_pot with probability equity.
    # Net EV when called = equity * new_pot - raise_size
    villain_call = raise_size  # simplified: villain calls our raise
    new_pot = pot + raise_size + villain_call
    ev_call = (1 - fold_pct) * (equity * new_pot - raise_size)

    total_ev = ev_fold + ev_call

    logger.debug(
        f"  semi-bluff EV: base_fold={base_fold:.2f} eff_fold={fold_pct:.2f} "
        f"wetness={wetness:.2f} leverage={leverage:.2f} raise={raise_size:.0f} "
        f"ev_fold={ev_fold:.1f} ev_call={ev_call:.1f} total={total_ev:.1f}"
    )
    return total_ev


def call_ev(state: GameState, equity: float) -> float:
    """Calculate EV of calling.

    EV(call) = equity * (pot + to_call) - (1-equity) * to_call
    """
    if state.to_call <= 0:
        return equity * state.pot  # checking is free
    return equity * (state.pot + state.to_call) - (1 - equity) * state.to_call


def get_postflop_action(state: GameState) -> Action:
    """Make a postflop decision based on equity vs pot odds.

    Strategy:
    - equity >> pot_odds -> raise (value bet)
    - equity > pot_odds -> call
    - equity < pot_odds -> fold (or check if free)
    - Adjustments by street (tighter on river)
    """
    opponents = max(1, state.players_in_hand - 1)
    equity = calculate_equity(
        state.hole_cards,
        state.community_cards,
        num_opponents=opponents,
        iterations=800,
    )

    pot_odds = state.pot_odds
    impl_odds = implied_pot_odds(state)
    strength = get_hand_strength_class(equity)
    wetness = board_wetness(state.community_cards)

    logger.info(
        f"POSTFLOP [{state.street.value}]: equity={equity:.2f} "
        f"pot_odds={pot_odds:.2f} implied={impl_odds:.2f} "
        f"strength={strength} wetness={wetness:.2f} "
        f"pot={state.pot:.0f} to_call={state.to_call:.0f} "
        f"SPR={state.spr:.1f} {'IP' if state.in_position else 'OOP'} "
        f"v_fold={state.villain_fold_pct:.2f} v_AF={state.villain_aggression:.1f}"
    )

    # Free check available
    if state.to_call <= 0:
        return _decide_check_or_bet(state, equity, opponents)

    # Facing a bet -- use implied odds for call/fold threshold
    return _decide_call_raise_fold(state, equity, pot_odds, opponents, impl_odds)


def _decide_check_or_bet(state: GameState, equity: float, opponents: int) -> Action:
    """Decide whether to check or bet when action is free.

    Includes WA/WB logic: on dry boards with medium hands, check behind
    for pot control instead of betting into a polarized range.
    """
    from src.strategy.sizing import get_bet_size

    wetness = board_wetness(state.community_cards)

    # Monster hand (>=0.80) -> always bet for value, even on dry boards
    if equity >= 0.80:
        bet = get_bet_size(state, equity, is_value=True)
        if bet > 0:
            logger.info(f"  -> VALUE BET {bet:.0f} (monster equity {equity:.2f})")
            return Action(ActionType.RAISE, bet)

    # Probe bet: villain checked back on flop, showing weakness. Bet wider on turn.
    if state.villain_checked_back_flop and state.street == Street.TURN and equity >= 0.30:
        bet = get_bet_size(state, equity, is_cbet=True)
        if bet > 0:
            logger.info(
                f"  -> PROBE BET {bet:.0f} (villain checked back flop, equity {equity:.2f})"
            )
            return Action(ActionType.RAISE, bet)

    # Donk-bet: BB with range advantage leads out instead of checking to aggressor
    if (state.street == Street.FLOP
            and state.my_position == Position.BB
            and not state.in_position):
        ra = range_advantage(state.community_cards, Position.BB, False)
        if ra > 0.20 and equity >= 0.50:
            bet = get_bet_size(state, equity, is_cbet=True)
            if bet > 0:
                logger.info(
                    f"  -> DONK BET {bet:.0f} (BB range advantage {ra:.2f}, equity {equity:.2f})"
                )
                return Action(ActionType.RAISE, bet)

    # WA/WB: medium-to-strong hand on dry board — pot control
    # "Betting accomplishes nothing: worse folds, better calls"
    # This MUST come before regular value bet: on dry boards, even 65%
    # equity shouldn't bet (second pair, small overpair territory).
    if is_wawb(equity, wetness, state.players_in_hand):
        if state.in_position:
            # In position: check behind, control pot, let villain bluff later
            logger.info(
                f"  -> CHECK (WA/WB: equity {equity:.2f}, dry board "
                f"wetness={wetness:.2f}, pot control IP)"
            )
            return Action(ActionType.CHECK)
        else:
            # Out of position: check to induce bluffs from aggressive villains
            if state.villain_aggression > 1.5:
                logger.info(
                    f"  -> CHECK (WA/WB: equity {equity:.2f}, OOP vs aggro "
                    f"AF={state.villain_aggression:.1f}, induce bluff)"
                )
                return Action(ActionType.CHECK)
            else:
                # Vs passive villain: thin value bet (they won't bet for us)
                bet = get_bet_size(state, equity, is_cbet=True)
                if bet > 0:
                    logger.info(
                        f"  -> THIN VALUE {bet:.0f} (WA/WB OOP vs passive "
                        f"AF={state.villain_aggression:.1f}, they won't bluff)"
                    )
                    return Action(ActionType.RAISE, bet)

    # Strong hand on non-dry board -> bet for value + protection
    if equity >= 0.65:
        bet = get_bet_size(state, equity, is_value=True)
        if bet > 0:
            logger.info(f"  -> VALUE BET {bet:.0f} (equity {equity:.2f} wet={wetness:.2f})")
            return Action(ActionType.RAISE, bet)

    # Medium hand on flop -> continuation bet (range-advantage-aware)
    if state.street == Street.FLOP:
        ra = range_advantage(state.community_cards, state.my_position, state.in_position)
        cbet_threshold = 0.45 - ra * 0.10  # lower threshold when we have range advantage
        if equity >= cbet_threshold:
            bet = get_bet_size(state, equity, is_cbet=True)
            if bet > 0:
                logger.info(
                    f"  -> C-BET {bet:.0f} (equity {equity:.2f} "
                    f"wetness={wetness:.2f} range_adv={ra:.2f})"
                )
                return Action(ActionType.RAISE, bet)

    # Semi-bluff with draws (equity 0.25-0.50 on flop/turn)
    # Use fold equity EV instead of random coin flip
    if 0.25 <= equity < 0.50 and state.street in (Street.FLOP, Street.TURN):
        bet = get_bet_size(state, equity, is_bluff=True)
        if bet > 0:
            raise_ev = semi_bluff_ev(state, equity, bet)
            check_ev = call_ev(state, equity)  # EV of checking (to_call=0)
            if raise_ev > check_ev:
                logger.info(
                    f"  -> SEMI-BLUFF {bet:.0f} (equity {equity:.2f} "
                    f"raise_EV={raise_ev:.1f} > check_EV={check_ev:.1f} "
                    f"fold_pct={state.villain_fold_pct:.2f})"
                )
                return Action(ActionType.RAISE, bet)

    logger.info(f"  -> CHECK (equity {equity:.2f})")
    return Action(ActionType.CHECK)


def _should_check_raise(state: GameState, equity: float, wetness: float) -> bool:
    """Decide if we should check-raise (after checking this street).

    Check-raise is an OOP play: we check, villain bets, we raise.
    Two branches:
    - Value CR: strong hands that benefit from building pot OOP
    - Bluff CR: draws with fold equity on wet boards
    """
    if state.in_position:
        return False  # check-raise is an OOP play
    if not state.checked_this_street:
        return False  # only when we already checked
    if state.players_in_hand > 3:
        return False  # too many players, check-raise less effective

    # Value check-raise: strong hands OOP (sets, two pair+)
    if equity >= 0.75:
        return random.random() < 0.70  # 70% of the time

    # Bluff check-raise: draws on wet boards with fold equity
    if 0.35 <= equity <= 0.50 and state.street == Street.FLOP:
        if wetness > 0.30 and state.villain_fold_pct > 0.40:
            return random.random() < 0.25  # 25% of the time

    return False


def _strong_hand_raise_frequency(state: GameState, equity: float, wetness: float) -> float:
    """Dynamic raise frequency for strong (0.60-0.75) hands facing a bet.

    Replaces the fixed 35% raise rate. Varies by:
    - Board texture: wet -> raise more (protect equity)
    - Villain type: passive -> raise more (value), aggressive -> call more (trap)
    - SPR: low -> raise more (approaching commitment)
    - Street: river -> slightly less (villain's range defined)
    """
    base = 0.35

    # Wet board: raise more often (deny draws)
    if wetness > 0.40:
        base += 0.15
    elif wetness > 0.25:
        base += 0.08

    # Passive villain: raise more (they call too much = value)
    if state.villain_aggression < 1.0:
        base += 0.10
    # Aggressive villain: call more (let them bluff into us)
    elif state.villain_aggression > 2.5:
        base -= 0.10

    # Low SPR: raise more (commit)
    if state.spr < 4:
        base += 0.10

    # River: slightly less (ranges defined)
    if state.street == Street.RIVER:
        base -= 0.10

    return max(0.15, min(0.65, base))


def _decide_call_raise_fold(
    state: GameState,
    equity: float,
    pot_odds: float,
    opponents: int,
    impl_odds: float = 0.0,
) -> Action:
    """Decide call/raise/fold. Uses implied odds for call/fold threshold."""
    from src.strategy.sizing import get_bet_size

    # Street-dependent tightness (need stronger hand on later streets)
    tightness = {
        Street.FLOP: 0.0,
        Street.TURN: 0.03,
        Street.RIVER: 0.06,
    }
    threshold_adjustment = tightness.get(state.street, 0.0)
    call_threshold = impl_odds + threshold_adjustment

    # Check if we're committed (SPR < 2)
    committed = state.spr < 2
    wetness = board_wetness(state.community_cards)

    # Check-raise: if we checked this street and villain bet, raise with strong hands OOP
    if _should_check_raise(state, equity, wetness):
        raise_amount = get_bet_size(state, equity, is_value=(equity >= 0.75))
        cr_type = "value" if equity >= 0.75 else "bluff"
        logger.info(
            f"  -> CHECK-RAISE ({cr_type}) {raise_amount:.0f} "
            f"(equity {equity:.2f} wetness={wetness:.2f})"
        )
        return Action(ActionType.RAISE, raise_amount)

    # Monster -> raise
    if equity >= 0.75:
        if committed:
            logger.info(f"  -> ALL-IN (monster, committed)")
            return Action(ActionType.ALL_IN, state.my_stack)
        raise_amount = get_bet_size(state, equity, is_value=True)
        logger.info(f"  -> RAISE {raise_amount:.0f} (monster equity {equity:.2f})")
        return Action(ActionType.RAISE, raise_amount)

    # WA/WB facing a bet: medium hand on dry board.
    # MUST check before "strong" branch: on dry boards, even 60-70% equity
    # should not raise — villain's bet is either a bluff or they crush us.
    # Vs aggressive villain: call (they bluff a lot, we catch them)
    # Vs passive villain: lean fold (they only bet with goods)
    if is_wawb(equity, wetness, state.players_in_hand):
        if state.villain_aggression > 2.0:
            # Aggressive villain fires a lot — they're often bluffing.
            # Call down and let them hang themselves. But not on river
            # with huge bets (even maniacs have it sometimes).
            if state.street == Street.RIVER and state.to_call > state.pot * 0.75:
                logger.info(
                    f"  -> FOLD (WA/WB river, overbet from aggro "
                    f"AF={state.villain_aggression:.1f} — even maniacs have it)"
                )
                return Action(ActionType.FOLD)
            logger.info(
                f"  -> CALL (WA/WB vs aggro AF={state.villain_aggression:.1f}, "
                f"equity {equity:.2f}, catching bluffs)"
            )
            return Action(ActionType.CALL)
        elif state.villain_aggression < 1.0:
            # Passive villain — when they bet, they HAVE it.
            # Not all can fire three barrels without a hand.
            logger.info(
                f"  -> FOLD (WA/WB vs passive AF={state.villain_aggression:.1f}, "
                f"equity {equity:.2f}, they have it when they bet)"
            )
            return Action(ActionType.FOLD)
        # Average aggression: standard call/fold by pot odds below

    # Strong hand on non-dry board -> raise sometimes, call otherwise
    if equity >= 0.60:
        if random.random() < _strong_hand_raise_frequency(state, equity, wetness):
            raise_amount = get_bet_size(state, equity, is_value=True)
            logger.info(f"  -> RAISE {raise_amount:.0f} (strong equity {equity:.2f})")
            return Action(ActionType.RAISE, raise_amount)
        logger.info(f"  -> CALL (strong equity {equity:.2f})")
        return Action(ActionType.CALL)

    # Semi-bluff raise with draws: raise is better than call when fold equity
    # makes it +EV. This is the "raise on a bet with a draw" play.
    # Only on flop/turn (river has no outs to improve), need decent equity.
    if (
        0.25 <= equity < 0.55
        and state.street in (Street.FLOP, Street.TURN)
        and state.spr > 2  # need stack behind for the raise to be credible
    ):
        raise_size = get_bet_size(state, equity, is_bluff=True)
        if raise_size > 0:
            raise_ev = semi_bluff_ev(state, equity, raise_size)
            flat_ev = call_ev(state, equity)
            if raise_ev > flat_ev and raise_ev > 0:
                logger.info(
                    f"  -> SEMI-BLUFF RAISE {raise_size:.0f} (equity {equity:.2f} "
                    f"raise_EV={raise_ev:.1f} > call_EV={flat_ev:.1f} "
                    f"fold_pct={state.villain_fold_pct:.2f})"
                )
                return Action(ActionType.RAISE, raise_size)

    # Equity beats implied odds threshold -> call
    if equity > call_threshold:
        # But avoid calling large bets with marginal hands on river
        if state.street == Street.RIVER and equity < 0.45 and state.to_call > state.pot * 0.5:
            logger.info(f"  -> FOLD (marginal on river, large bet)")
            return Action(ActionType.FOLD)
        logger.info(f"  -> CALL (equity {equity:.2f} > implied threshold {call_threshold:.2f})")
        return Action(ActionType.CALL)

    # Below implied threshold — but semi-bluff raise might still be +EV
    # (fold equity alone can make it profitable even with weak equity)
    if (
        equity >= 0.20
        and state.street in (Street.FLOP, Street.TURN)
        and state.villain_fold_pct >= 0.50  # only vs players who fold a lot
        and state.spr > 3
    ):
        raise_size = get_bet_size(state, equity, is_bluff=True)
        if raise_size > 0:
            raise_ev = semi_bluff_ev(state, equity, raise_size)
            if raise_ev > 0:
                logger.info(
                    f"  -> BLUFF RAISE {raise_size:.0f} (equity {equity:.2f} "
                    f"raise_EV={raise_ev:.1f} fold_pct={state.villain_fold_pct:.2f} "
                    f"below call threshold but +EV raise)"
                )
                return Action(ActionType.RAISE, raise_size)

    # Equity below threshold -> fold
    logger.info(
        f"  -> FOLD (equity {equity:.2f} < implied threshold {call_threshold:.2f})"
    )
    return Action(ActionType.FOLD)
