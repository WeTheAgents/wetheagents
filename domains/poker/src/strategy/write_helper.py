"""Postflop strategy: Monte Carlo equity estimation + pot odds decision engine."""

from __future__ import annotations

import logging
import random

from treys import Card, Deck, Evaluator

from src.table.state import Action, ActionType, GameState, Street

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
    strength = get_hand_strength_class(equity)

    logger.info(
        f"POSTFLOP [{state.street.value}]: equity={equity:.2f} pot_odds={pot_odds:.2f} "
        f"strength={strength} pot={state.pot:.0f} to_call={state.to_call:.0f}"
    )

    # Free check available
    if state.to_call <= 0:
        return _decide_check_or_bet(state, equity, opponents)

    # Facing a bet
    return _decide_call_raise_fold(state, equity, pot_odds, opponents)


def _decide_check_or_bet(state: GameState, equity: float, opponents: int) -> Action:
    """Decide whether to check or bet when action is free."""
    from src.strategy.sizing import get_bet_size

    # Strong hand -> bet for value
    if equity >= 0.65:
        bet = get_bet_size(state, equity, is_value=True)
        if bet > 0:
            logger.info(f"  -> VALUE BET {bet:.0f} (equity {equity:.2f})")
            return Action(ActionType.RAISE, bet)

    # Medium hand on flop -> continuation bet
    if equity >= 0.45 and state.street == Street.FLOP:
        bet = get_bet_size(state, equity, is_cbet=True)
        if bet > 0:
            logger.info(f"  -> C-BET {bet:.0f} (equity {equity:.2f})")
            return Action(ActionType.RAISE, bet)

    # Semi-bluff with draws (equity 0.35-0.50 on flop/turn)
    if 0.35 <= equity < 0.50 and state.street in (Street.FLOP, Street.TURN):
        # Bluff ~40% of the time with draws
        if random.random() < 0.40:
            bet = get_bet_size(state, equity, is_bluff=True)
            if bet > 0:
                logger.info(f"  -> SEMI-BLUFF {bet:.0f} (equity {equity:.2f})")
                return Action(ActionType.RAISE, bet)

    logger.info(f"  -> CHECK (equity {equity:.2f})")
    return Action(ActionType.CHECK)


def _decide_call_raise_fold(
    state: GameState,
    equity: float,
    pot_odds: float,
    opponents: int,
) -> Action:
    """Decide call/raise/fold when facing a bet."""
    from src.strategy.sizing import get_bet_size

    # Street-dependent tightness (need stronger hand on later streets)
    tightness = {
        Street.FLOP: 0.0,
        Street.TURN: 0.03,
        Street.RIVER: 0.06,
    }
    threshold_adjustment = tightness.get(state.street, 0.0)
    adjusted_pot_odds = pot_odds + threshold_adjustment

    # Check if we're committed (SPR < 2)
    committed = state.spr < 2

    # Monster -> raise
    if equity >= 0.75:
        if committed:
            logger.info(f"  -> ALL-IN (monster, committed)")
            return Action(ActionType.ALL_IN, state.my_stack)
        raise_amount = get_bet_size(state, equity, is_value=True)
        logger.info(f"  -> RAISE {raise_amount:.0f} (monster equity {equity:.2f})")
        return Action(ActionType.RAISE, raise_amount)

    # Strong -> raise sometimes, call otherwise
    if equity >= 0.60:
        if random.random() < 0.35:
            raise_amount = get_bet_size(state, equity, is_value=True)
            logger.info(f"  -> RAISE {raise_amount:.0f} (strong equity {equity:.2f})")
            return Action(ActionType.RAISE, raise_amount)
        logger.info(f"  -> CALL (strong equity {equity:.2f})")
        return Action(ActionType.CALL)

    # Equity beats pot odds -> call
    if equity > adjusted_pot_odds:
        # But avoid calling large bets with marginal hands on river
        if state.street == Street.RIVER and equity < 0.45 and state.to_call > state.pot * 0.5:
            logger.info(f"  -> FOLD (marginal on river, large bet)")
            return Action(ActionType.FOLD)
        logger.info(f"  -> CALL (equity {equity:.2f} > adjusted_odds {adjusted_pot_odds:.2f})")
        return Action(ActionType.CALL)

    # Equity below threshold -> fold
    logger.info(
        f"  -> FOLD (equity {equity:.2f} < adjusted_odds {adjusted_pot_odds:.2f})"
    )
    return Action(ActionType.FOLD)
