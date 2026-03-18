"""PokerNow table connector: Selenium-based automation for pokernow.club."""

from __future__ import annotations

import logging
import random
import time
from typing import Callable

from selenium import webdriver
from selenium.common.exceptions import (
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
)
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

from src.table.state import (
    Action,
    ActionType,
    GameState,
    PlayerState,
    Position,
    Street,
    get_position,
)

logger = logging.getLogger(__name__)

# CSS selectors for PokerNow DOM elements
# These may need updating if PokerNow changes their frontend
SELECTORS = {
    # Game state
    "pot": ".table-pot-size .main-value",
    "community_cards": ".community-cards .card",
    "my_cards": ".you-player .card",
    "my_stack": ".you-player .player-stack .chips-value",
    "my_name": ".you-player .player-name",
    "dealer_chip": ".dealer-chip-holder",

    # Players
    "players": ".table-player",
    "player_name": ".player-name",
    "player_stack": ".player-stack .chips-value",
    "player_bet": ".player-bet-value .chips-value",
    "player_cards": ".card",

    # Action buttons
    "fold_btn": ".action-buttons .fold-button",
    "check_btn": ".action-buttons .check-button",
    "call_btn": ".action-buttons .call-button",
    "raise_btn": ".action-buttons .raise-button",
    "all_in_btn": ".action-buttons .all-in-button",
    "bet_input": ".action-buttons .raise-input input",
    "action_buttons": ".action-buttons",

    # Game info
    "blind_level": ".table-game-blind-value",
    "game_log": ".game-log-container .log-message",
}


class PokerNowConnector:
    """Connects to a PokerNow game table and provides read/write access."""

    def __init__(
        self,
        profile_dir: str | None = None,
        headless: bool = False,
        humanize: bool = True,
    ):
        self.driver: webdriver.Chrome | None = None
        self.profile_dir = profile_dir
        self.headless = headless
        self.humanize = humanize
        self._my_name: str | None = None

    def connect(self, url: str) -> None:
        """Launch Chrome and navigate to the PokerNow table."""
        options = Options()

        if self.profile_dir:
            options.add_argument(f"--user-data-dir={self.profile_dir}")

        if self.headless:
            options.add_argument("--headless=new")

        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_argument("--no-sandbox")
        options.add_argument("--window-size=1280,900")

        service = Service(ChromeDriverManager().install())
        self.driver = webdriver.Chrome(service=service, options=options)
        self.driver.implicitly_wait(3)

        logger.info(f"Navigating to {url}")
        self.driver.get(url)

        # Wait for table to load
        try:
            WebDriverWait(self.driver, 30).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, SELECTORS["action_buttons"]))
            )
            logger.info("Table loaded successfully")
        except TimeoutException:
            logger.warning("Table load timeout — may need manual join/login")

    def disconnect(self) -> None:
        """Close the browser."""
        if self.driver:
            self.driver.quit()
            self.driver = None

    def is_my_turn(self) -> bool:
        """Check if it's our turn to act."""
        try:
            buttons = self.driver.find_element(By.CSS_SELECTOR, SELECTORS["action_buttons"])
            # Check if any action button is visible and enabled
            for btn_sel in [SELECTORS["fold_btn"], SELECTORS["check_btn"],
                            SELECTORS["call_btn"], SELECTORS["raise_btn"]]:
                try:
                    btn = self.driver.find_element(By.CSS_SELECTOR, btn_sel)
                    if btn.is_displayed():
                        return True
                except NoSuchElementException:
                    continue
            return False
        except (NoSuchElementException, StaleElementReferenceException):
            return False

    def read_state(self) -> GameState | None:
        """Read the complete game state from the DOM.

        Returns None if we can't determine the state.
        """
        try:
            return self._parse_game_state()
        except Exception as e:
            logger.error(f"Error reading game state: {e}")
            return None

    def execute_action(self, action: Action) -> bool:
        """Execute a poker action by clicking DOM buttons.

        Returns True if action was executed successfully.
        """
        if self.humanize:
            self._human_delay(action)

        try:
            if action.type == ActionType.FOLD:
                return self._click_button(SELECTORS["fold_btn"])

            elif action.type == ActionType.CHECK:
                return self._click_button(SELECTORS["check_btn"])

            elif action.type == ActionType.CALL:
                return self._click_button(SELECTORS["call_btn"])

            elif action.type == ActionType.RAISE:
                return self._do_raise(action.amount or 0)

            elif action.type == ActionType.ALL_IN:
                # Try all-in button first, fall back to max raise
                if self._click_button(SELECTORS["all_in_btn"]):
                    return True
                return self._do_raise(action.amount or 999999)

            return False

        except Exception as e:
            logger.error(f"Error executing action {action}: {e}")
            # Emergency fold
            try:
                self._click_button(SELECTORS["fold_btn"])
            except Exception:
                pass
            return False

    def _parse_game_state(self) -> GameState | None:
        """Parse the full game state from DOM elements."""
        state = GameState(hole_cards=[])

        # My cards
        try:
            card_elements = self.driver.find_elements(
                By.CSS_SELECTOR, SELECTORS["my_cards"]
            )
            for el in card_elements:
                card_class = el.get_attribute("class") or ""
                card_str = self._parse_card_class(card_class)
                if card_str:
                    state.hole_cards.append(card_str)
        except NoSuchElementException:
            return None

        if len(state.hole_cards) < 2:
            return None

        # Community cards
        try:
            comm_elements = self.driver.find_elements(
                By.CSS_SELECTOR, SELECTORS["community_cards"]
            )
            for el in comm_elements:
                card_class = el.get_attribute("class") or ""
                card_str = self._parse_card_class(card_class)
                if card_str:
                    state.community_cards.append(card_str)
        except NoSuchElementException:
            pass

        # Street
        num_community = len(state.community_cards)
        if num_community == 0:
            state.street = Street.PREFLOP
        elif num_community == 3:
            state.street = Street.FLOP
        elif num_community == 4:
            state.street = Street.TURN
        else:
            state.street = Street.RIVER

        # Pot
        try:
            pot_el = self.driver.find_element(By.CSS_SELECTOR, SELECTORS["pot"])
            state.pot = self._parse_chips(pot_el.text)
        except NoSuchElementException:
            state.pot = 0

        # My stack
        try:
            stack_el = self.driver.find_element(By.CSS_SELECTOR, SELECTORS["my_stack"])
            state.my_stack = self._parse_chips(stack_el.text)
        except NoSuchElementException:
            pass

        # Blinds
        try:
            blind_el = self.driver.find_element(By.CSS_SELECTOR, SELECTORS["blind_level"])
            blind_text = blind_el.text  # e.g. "10/20"
            parts = blind_text.replace(",", "").split("/")
            if len(parts) >= 2:
                state.big_blind = float(parts[1].strip())
        except (NoSuchElementException, ValueError):
            state.big_blind = 20  # fallback

        # Players
        try:
            player_elements = self.driver.find_elements(By.CSS_SELECTOR, SELECTORS["players"])
            for el in player_elements:
                try:
                    name = el.find_element(By.CSS_SELECTOR, SELECTORS["player_name"]).text
                    stack_text = el.find_element(By.CSS_SELECTOR, SELECTORS["player_stack"]).text
                    stack = self._parse_chips(stack_text)
                    is_active = "folded" not in (el.get_attribute("class") or "")

                    bet = 0.0
                    try:
                        bet_el = el.find_element(By.CSS_SELECTOR, SELECTORS["player_bet"])
                        bet = self._parse_chips(bet_el.text)
                    except NoSuchElementException:
                        pass

                    state.players.append(PlayerState(
                        name=name, stack=stack, bet=bet, is_active=is_active,
                    ))
                except NoSuchElementException:
                    continue

            state.num_players = len(state.players)
            state.players_in_hand = sum(1 for p in state.players if p.is_active)
        except NoSuchElementException:
            pass

        # To call amount (from call button text)
        try:
            call_btn = self.driver.find_element(By.CSS_SELECTOR, SELECTORS["call_btn"])
            if call_btn.is_displayed():
                call_text = call_btn.text  # e.g. "Call 100"
                parts = call_text.split()
                if len(parts) >= 2:
                    state.to_call = self._parse_chips(parts[-1])
        except (NoSuchElementException, ValueError):
            pass

        # Min/max raise (from raise input if visible)
        try:
            raise_btn = self.driver.find_element(By.CSS_SELECTOR, SELECTORS["raise_btn"])
            if raise_btn.is_displayed():
                bet_input = self.driver.find_element(By.CSS_SELECTOR, SELECTORS["bet_input"])
                state.min_raise = float(bet_input.get_attribute("min") or 0)
                state.max_raise = float(bet_input.get_attribute("max") or state.my_stack)
        except (NoSuchElementException, ValueError):
            pass

        # Position (approximate from dealer chip location)
        # This is a simplified version — exact position detection needs
        # mapping player seats to dealer chip
        state.my_position = self._detect_position(state)

        return state

    def _detect_position(self, state: GameState) -> Position | None:
        """Detect our position at the table.

        Approximation: look at the dealer chip and count seats clockwise.
        """
        try:
            # Find which player has the dealer chip
            players = self.driver.find_elements(By.CSS_SELECTOR, SELECTORS["players"])
            dealer_idx = 0
            my_idx = 0

            for i, el in enumerate(players):
                classes = el.get_attribute("class") or ""
                if "dealer" in classes.lower():
                    dealer_idx = i
                if "you-player" in classes.lower() or "is-you" in classes.lower():
                    my_idx = i

            return get_position(my_idx, dealer_idx, state.num_players)
        except Exception:
            return Position.MP  # safe fallback

    def _parse_card_class(self, class_str: str) -> str | None:
        """Parse a card from its CSS class (e.g., 'card rank-a suit-h' -> 'Ah')."""
        rank_map = {
            "rank-a": "A", "rank-k": "K", "rank-q": "Q", "rank-j": "J",
            "rank-t": "T", "rank-10": "T",
            "rank-9": "9", "rank-8": "8", "rank-7": "7", "rank-6": "6",
            "rank-5": "5", "rank-4": "4", "rank-3": "3", "rank-2": "2",
        }
        suit_map = {
            "suit-h": "h", "suit-d": "d", "suit-c": "c", "suit-s": "s",
        }

        rank = None
        suit = None
        for cls in class_str.lower().split():
            if cls in rank_map:
                rank = rank_map[cls]
            if cls in suit_map:
                suit = suit_map[cls]

        if rank and suit:
            return f"{rank}{suit}"
        return None

    def _parse_chips(self, text: str) -> float:
        """Parse a chip amount from text (e.g., '1,234' -> 1234.0)."""
        cleaned = text.replace(",", "").replace("$", "").replace(" ", "").strip()
        try:
            return float(cleaned)
        except ValueError:
            return 0.0

    def _click_button(self, selector: str) -> bool:
        """Click a button by CSS selector."""
        try:
            btn = WebDriverWait(self.driver, 3).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
            )
            btn.click()
            return True
        except (TimeoutException, NoSuchElementException):
            return False

    def _do_raise(self, amount: float) -> bool:
        """Set raise amount and click raise button."""
        try:
            # Clear and set the bet input
            bet_input = self.driver.find_element(By.CSS_SELECTOR, SELECTORS["bet_input"])
            bet_input.clear()
            bet_input.send_keys(str(int(amount)))
            time.sleep(0.3)

            # Click raise/bet button
            return self._click_button(SELECTORS["raise_btn"])
        except (NoSuchElementException, TimeoutException):
            return False

    def _human_delay(self, action: Action) -> None:
        """Add human-like delay before acting."""
        if action.type == ActionType.FOLD:
            delay = random.uniform(1.0, 3.0)
        elif action.type == ActionType.CHECK:
            delay = random.uniform(1.0, 2.5)
        elif action.type == ActionType.CALL:
            delay = random.uniform(2.0, 5.0)
        elif action.type in (ActionType.RAISE, ActionType.ALL_IN):
            delay = random.uniform(3.0, 7.0)
            # Occasional "tank" on big decisions
            if random.random() < 0.15:
                delay = random.uniform(8.0, 14.0)
                logger.info(f"  (tanking for {delay:.0f}s...)")
        else:
            delay = random.uniform(2.0, 4.0)

        time.sleep(delay)


def run_bot_loop(
    connector: PokerNowConnector,
    get_action: Callable[[GameState], Action],
    poll_interval: float = 0.5,
) -> None:
    """Main bot loop: poll for turn, get action, execute.

    Args:
        connector: Connected PokerNow table
        get_action: Strategy function (state -> action)
        poll_interval: How often to check if it's our turn (seconds)
    """
    logger.info("Bot loop started. Waiting for hands...")

    while True:
        try:
            if not connector.is_my_turn():
                time.sleep(poll_interval)
                continue

            state = connector.read_state()
            if state is None:
                logger.warning("Could not read game state, folding")
                connector.execute_action(Action(ActionType.FOLD))
                time.sleep(1)
                continue

            action = get_action(state)
            connector.execute_action(action)

        except KeyboardInterrupt:
            logger.info("Bot stopped by user (Ctrl+C)")
            break
        except Exception as e:
            logger.error(f"Unexpected error in bot loop: {e}")
            # Try to fold as emergency action
            try:
                connector.execute_action(Action(ActionType.FOLD))
            except Exception:
                pass
            time.sleep(2)
