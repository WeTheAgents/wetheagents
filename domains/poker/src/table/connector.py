"""PokerNow table connector: Selenium-based automation for pokernow.club."""

from __future__ import annotations

import logging
import random
import re
import time
from collections.abc import Callable

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

# Card normalization maps — single source of truth for DOM → internal format
_RANK_MAP = {
    "A": "A", "K": "K", "Q": "Q", "J": "J",
    "10": "T", "T": "T",
    "9": "9", "8": "8", "7": "7", "6": "6",
    "5": "5", "4": "4", "3": "3", "2": "2",
}
_SUIT_MAP = {"s": "s", "h": "h", "d": "d", "c": "c"}

# Unicode suit symbols (used in game log parsing)
_SUIT_UNICODE = {"♠": "s", "♥": "h", "♦": "d", "♣": "c"}

# Compiled regex patterns for game log parsing
_FLOP_RE = re.compile(r'[Ff]lop:\s*\[(.+?)\]')
_TURN_RE = re.compile(r'[Tt]urn:\s*(.+?)\s*\[(.+?)\]')
_RIVER_RE = re.compile(r'[Rr]iver:\s*(.+?)\s*\[(.+?)\]')
_NEW_HAND_RE = re.compile(r'starting hand')

# CSS selectors for PokerNow DOM elements
# Source: Jackaljkdan/pokernow-bot (verified working)
SELECTORS = {
    # Game state
    "pot": ".table-pot-size .main-value .chips-value",
    "pot_addon": ".table-pot-size .add-on .chips-value",
    "community_cards": ".table-cards .card",
    "my_cards": ".you-player .card",
    "my_stack": ".table-player.you-player .table-player-stack .chips-value",
    "my_name": ".you-player .table-player-name",
    "dealer_chip": ".dealer-chip-holder",

    # Players
    "players": ".table-player",
    "player_name": ".table-player-name",
    "player_stack": ".table-player-stack .chips-value",
    "player_bet": ".table-player-bet-value .chips-value",
    "player_cards": ".card",

    # Action buttons
    "fold_btn": "button.fold",
    "check_btn": "button.check",
    "call_btn": "button.call",
    "raise_btn": "button.raise",
    "all_in_btn": "button.all-in",
    "bet_input": ".raise-controller-form input[type='number'], .raise-controller-form input",
    "raise_confirm": ".raise-controller-form input[type='submit']",
    "action_buttons": ".action-buttons",
    "action_signal": ".action-signal",

    # Game info
    "blind_level": ".blind-value .chips-value",
    "game_log": ".game-log-container .log-message",
    "hand_rank": ".player-hand-message",
}


class PokerNowConnector:
    """Connects to a PokerNow game table and provides read/write access."""

    def __init__(
        self,
        profile_dir: str | None = None,
        headless: bool = False,
        humanize: bool = True,
        bot_name: str = "WEA-Bot",
        buy_in: int = 1000,
    ):
        self.driver: webdriver.Chrome | None = None
        self.profile_dir = profile_dir
        self.headless = headless
        self.humanize = humanize
        self.bot_name = bot_name
        self.buy_in = buy_in
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

        # Accept TOS / dismiss any startup overlays
        time.sleep(2)
        self._dismiss_overlays()

        # Auto-join: sit at the table if not already seated
        self._auto_join()

        # Dismiss any post-join overlays
        time.sleep(1)
        self._dismiss_overlays()

    def _auto_join(self) -> None:
        """Automatically sit at the table if not already seated."""
        # Check if we're already seated (have .you-player element)
        try:
            self.driver.find_element(By.CSS_SELECTOR, ".you-player")
            logger.info("Already seated at the table")
            return
        except NoSuchElementException:
            pass

        # Find a SIT button and click it
        try:
            sit_buttons = self.driver.find_elements(
                By.CSS_SELECTOR, ".table-player-seat button"
            )
            if not sit_buttons:
                # Alternative selector
                sit_buttons = self.driver.find_elements(
                    By.XPATH, "//button[contains(text(), 'Sit')]"
                )
            if not sit_buttons:
                logger.warning("No SIT buttons found — manual join required")
                return

            sit_buttons[0].click()
            time.sleep(1)

            # Fill in name
            try:
                name_input = self.driver.find_element(
                    By.CSS_SELECTOR, "input[type='text']"
                )
                name_input.clear()
                name_input.send_keys(self.bot_name)
            except NoSuchElementException:
                logger.warning("Could not find name input")
                return

            # Fill in buy-in chips amount
            try:
                chip_inputs = self.driver.find_elements(
                    By.CSS_SELECTOR, "input[type='number'], input[type='text'][name*='chip'], input[type='text'][name*='stack']"
                )
                # Find the chips input — it's likely the second input field (after name)
                all_inputs = self.driver.find_elements(By.CSS_SELECTOR, "input")
                for inp in all_inputs:
                    inp_type = inp.get_attribute("type") or "text"
                    inp_val = inp.get_attribute("value") or ""
                    # Look for a numeric/amount field that isn't the name field
                    if inp_type == "number" or (inp_type == "text" and inp_val.isdigit()):
                        inp.clear()
                        inp.send_keys(str(self.buy_in))
                        logger.debug(f"Filled buy-in: {self.buy_in}")
                        break
                    elif inp_type == "text" and inp.get_attribute("placeholder") and any(
                        w in (inp.get_attribute("placeholder") or "").lower()
                        for w in ["chip", "stack", "amount", "buy"]
                    ):
                        inp.clear()
                        inp.send_keys(str(self.buy_in))
                        logger.debug(f"Filled buy-in via placeholder: {self.buy_in}")
                        break
            except Exception as e:
                logger.debug(f"Could not fill buy-in (may use default): {e}")

            # Click "Request the Seat" / confirm button
            try:
                confirm = self.driver.find_element(
                    By.CSS_SELECTOR, ".join-button, .request-seat-button"
                )
                confirm.click()
            except NoSuchElementException:
                # Try by text content
                buttons = self.driver.find_elements(By.CSS_SELECTOR, "button")
                for btn in buttons:
                    if "request" in btn.text.lower() or "join" in btn.text.lower():
                        btn.click()
                        break

            logger.info(f"Joined table as '{self.bot_name}'")
            time.sleep(3)  # Wait for seat confirmation

        except Exception as e:
            logger.warning(f"Auto-join failed: {e}. Manual join required.")

    def disconnect(self) -> None:
        """Close the browser."""
        if self.driver:
            self.driver.quit()
            self.driver = None

    def is_my_turn(self) -> bool:
        """Check if it's our turn to act.

        Uses a single JS call for speed — avoids 4×3s Selenium implicit waits.
        """
        try:
            result = self.driver.execute_script("""
                var ab = document.querySelector('.action-buttons');
                if (!ab) return false;
                var btns = ab.querySelectorAll('.fold, .check, .call, .raise');
                for (var i = 0; i < btns.length; i++) {
                    var b = btns[i];
                    if (b.offsetParent !== null && !b.disabled) return true;
                }
                return false;
            """)
            return bool(result)
        except (NoSuchElementException, StaleElementReferenceException, TimeoutException):
            return False
        except Exception as e:
            logger.warning(f"is_my_turn() unexpected error: {e}")
            raise

    def read_state(self) -> GameState | None:
        """Read the complete game state from the DOM.

        Returns None if we can't determine the state.
        """
        try:
            state = self._parse_game_state()
            if state is None:
                self._debug_dump_cards()
            return state
        except Exception as e:
            logger.error(f"Error reading game state: {e}")
            self._debug_dump_cards()
            return None

    def _debug_dump_cards(self) -> None:
        """Dump card DOM to log for debugging."""
        try:
            html = self.driver.execute_script("""
                var result = '';
                // Check .you-player
                var you = document.querySelector('.you-player');
                if (!you) {
                    result += 'NO .you-player found\\n';
                } else {
                    result += '.you-player class: ' + you.className + '\\n';
                    var cards = you.querySelectorAll('.card');
                    if (!cards.length) {
                        result += 'NO .card in .you-player\\n';
                        // Dump you-player innerHTML snippet
                        result += 'you-player HTML: ' + you.innerHTML.substring(0, 400) + '\\n';
                    } else {
                        cards.forEach(function(c, i) {
                            result += 'Card[' + i + ']: class=' + c.className + ' | html=' + c.outerHTML.substring(0, 300) + '\\n';
                        });
                    }
                }
                // Also dump action-buttons
                var ab = document.querySelector('.action-buttons');
                if (ab) result += 'action-buttons HTML: ' + ab.innerHTML.substring(0, 500) + '\\n';
                return result;
            """)
            logger.debug(f"DOM dump:\\n{html}")
        except Exception as e:
            logger.debug(f"Debug dump failed: {e}")

    def _dismiss_overlays(self) -> None:
        """Dismiss any blocking overlays (TOS agreement, alerts, announcements).

        Uses a single JS call to avoid Selenium implicit-wait delays.
        """
        try:
            clicked = self.driver.execute_script("""
                var selectors = [
                    '.tos-agreement button',
                    '.tos-agreement .button-1',
                    '.alert-1-container button',
                    '.alert-1-container .button-1',
                    '.modal button.close',
                    '.modal .button-1'
                ];
                var clicked = [];
                selectors.forEach(function(sel) {
                    document.querySelectorAll(sel).forEach(function(btn) {
                        if (btn.offsetParent !== null) {
                            btn.click();
                            clicked.push(sel);
                        }
                    });
                });
                return clicked;
            """)
            if clicked:
                logger.info(f"Dismissed overlays: {clicked}")
                time.sleep(0.5)
        except (NoSuchElementException, StaleElementReferenceException):
            pass  # No overlays to dismiss — expected
        except Exception as e:
            logger.warning(f"Overlay dismissal failed: {e}")

    def execute_action(self, action: Action) -> bool:
        """Execute a poker action using keyboard shortcuts.

        PokerNow keyboard shortcuts: R=Raise, K=Check, F=Fold, C=Call
        This avoids overlay/stale-element issues with button clicking.

        Returns True if action was executed successfully.
        """
        # Dismiss any overlays that might block keyboard input
        self._dismiss_overlays()

        if self.humanize:
            self._human_delay(action)

        try:
            if action.type == ActionType.FOLD:
                return self._send_key("f")

            elif action.type == ActionType.CHECK:
                return self._send_key("k")

            elif action.type == ActionType.CALL:
                # Try keyboard shortcut first (C), fall back to button click
                return self._send_key("c") or self._click_button(SELECTORS["call_btn"])

            elif action.type == ActionType.RAISE:
                return self._do_raise_keyboard(action.amount or 0)

            elif action.type == ActionType.ALL_IN:
                # All-in = raise to max: press R, clear input, enter big number, confirm
                return self._do_raise_keyboard(action.amount or 999999)

            return False

        except Exception as e:
            logger.error(f"Error executing action {action}: {e}")
            # Emergency fold via keyboard
            try:
                self._send_key("f")
            except Exception as fold_err:
                logger.error(f"Emergency fold also failed: {fold_err}")
            return False

    def _send_key(self, key: str) -> bool:
        """Send a keyboard shortcut via ActionChains (targets focused element)."""
        from selenium.webdriver.common.action_chains import ActionChains
        try:
            ActionChains(self.driver).send_keys(key).perform()
            logger.info(f"Sent key '{key}'")
            return True
        except Exception as e:
            logger.warning(f"Key send failed for '{key}': {e}")
            return False

    def _do_raise_keyboard(self, amount: float) -> bool:
        """Raise using keyboard shortcuts only: R <digits> Enter.

        PokerNow accepts keyboard-only raise: press R to activate raise mode,
        type the amount as digits, then press Enter to confirm.
        Uses ActionChains so keys go to the focused element (raise input after R).
        """
        from selenium.webdriver.common.action_chains import ActionChains
        from selenium.webdriver.common.keys import Keys
        try:
            amount_str = str(int(amount))

            # Single ActionChains sequence: R -> pause -> select-all -> digits -> pause -> Enter
            actions = ActionChains(self.driver)
            actions.send_keys("r")
            actions.pause(0.3)
            # Clear pre-filled min raise amount before typing
            actions.key_down(Keys.CONTROL).send_keys("a").key_up(Keys.CONTROL)
            actions.send_keys(amount_str)
            actions.pause(0.2)
            actions.send_keys(Keys.RETURN)
            actions.perform()

            logger.info(f"Raise to {amount_str} executed (R {amount_str} Enter)")
            time.sleep(0.5)  # wait for PokerNow to process
            return True

        except Exception as e:
            logger.error(f"Raise via keyboard failed: {e}")
            return False

    def _parse_game_state(self) -> GameState | None:
        """Parse the full game state from DOM elements."""
        state = GameState(hole_cards=[])

        # My cards — parse via JS to avoid StaleElementReferenceException
        try:
            cards_data = self.driver.execute_script("""
                var you = document.querySelector('.you-player');
                if (!you) return null;
                var cards = you.querySelectorAll('.card');
                if (cards.length < 2) return null;
                var result = [];
                cards.forEach(function(c) {
                    var v = c.querySelector('.value');
                    var s = c.querySelector('.suit:not(.sub-suit)') ||
                            c.querySelector('.suit');
                    if (v && s) result.push([v.textContent.trim(), s.textContent.trim()]);
                });
                return result.length >= 2 ? result : null;
            """)
            if not cards_data:
                return None
            for value, suit in cards_data:
                rank = _RANK_MAP.get(value.upper(), value)
                suit_char = _SUIT_MAP.get(suit[0].lower(), "") if suit else ""
                if rank and suit_char:
                    state.hole_cards.append(f"{rank}{suit_char}")
        except Exception as e:
            logger.error(f"Card parse error: {e}")
            return None

        if len(state.hole_cards) < 2:
            return None

        # Blinds first — needed for community card retry condition
        try:
            blind_els = self.driver.find_elements(By.CSS_SELECTOR, SELECTORS["blind_level"])
            if len(blind_els) >= 2:
                state.big_blind = self._parse_chips(blind_els[1].text)
            elif len(blind_els) == 1:
                blind_text = blind_els[0].text
                parts = blind_text.replace(",", "").split("/")
                if len(parts) >= 2:
                    state.big_blind = float(parts[1].strip())
                else:
                    state.big_blind = self._parse_chips(blind_text)
        except (NoSuchElementException, ValueError):
            state.big_blind = 20  # fallback
        if state.big_blind <= 0:
            logger.warning(f"big_blind parsed as {state.big_blind}, using fallback 20")
            state.big_blind = 20

        # Pot — before community cards so retry condition works
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
            logger.warning("Could not find stack element")
        if state.my_stack <= 0:
            logger.warning(f"Stack={state.my_stack}, cannot make decisions")
            return None

        # Community cards — single JS call (fast and reliable)
        state.community_cards = self._parse_community_cards_js()

        # Retry if pot suggests postflop but no cards found (animation delay)
        if not state.community_cards and state.pot > state.big_blind * 2:
            time.sleep(0.5)
            state.community_cards = self._parse_community_cards_js()

        if state.community_cards:
            logger.info(f"Board: {' '.join(state.community_cards)}")

        # Street
        num_community = len(state.community_cards)
        if num_community == 0:
            state.street = Street.PREFLOP
        elif num_community == 3:
            state.street = Street.FLOP
        elif num_community == 4:
            state.street = Street.TURN
        elif num_community >= 5:
            state.street = Street.RIVER
        else:
            logger.warning(f"Unexpected community card count: {num_community}")
            return None  # partial board — animation in progress

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
        except (NoSuchElementException, StaleElementReferenceException) as e:
            logger.warning(f"Player enumeration failed: {e}")
        if state.num_players == 0:
            logger.warning("No players detected — state unreliable")
            return None

        # To call amount (from call button text)
        try:
            call_btn = self.driver.find_element(By.CSS_SELECTOR, SELECTORS["call_btn"])
            if call_btn.is_displayed():
                call_text = call_btn.text  # e.g. "Call 100"
                parts = call_text.split()
                if len(parts) >= 2:
                    state.to_call = self._parse_chips(parts[-1])
        except (NoSuchElementException, ValueError) as e:
            if isinstance(e, ValueError):
                logger.warning(f"Failed to parse to_call amount: {e}")

        # Min/max raise (from raise input if visible)
        try:
            raise_btn = self.driver.find_element(By.CSS_SELECTOR, SELECTORS["raise_btn"])
            if raise_btn.is_displayed():
                bet_input = self.driver.find_element(By.CSS_SELECTOR, SELECTORS["bet_input"])
                state.min_raise = float(bet_input.get_attribute("min") or 0)
                state.max_raise = float(bet_input.get_attribute("max") or state.my_stack)
        except (NoSuchElementException, ValueError) as e:
            if isinstance(e, ValueError):
                logger.warning(f"Failed to parse raise bounds: {e}")

        state.my_position = self._detect_position(state)

        return state

    def _detect_position(self, state: GameState) -> Position | None:
        """Detect our position using a single JS call.

        Reads seat numbers from DOM classes (table-player-N), finds dealer seat,
        and computes relative position.  Falls back to bet-amount heuristic.
        """
        try:
            result = self.driver.execute_script("""
                var you = document.querySelector('.you-player');
                if (!you) return {error: 'no you-player'};

                // Our seat index from class like 'table-player-3'
                var ourSeat = -1;
                you.classList.forEach(function(c) {
                    var m = c.match(/^table-player-(\\d+)$/);
                    if (m) ourSeat = parseInt(m[1]);
                });

                // Dealer detection: find which player is closest to .dealer-button-ctn
                // (chip is absolutely positioned, not necessarily inside player div)
                var dealerSeat = -1;
                var dealerBtn = document.querySelector('.dealer-button-ctn');
                if (dealerBtn) {
                    // Try walking up DOM first (sometimes it IS inside player)
                    var el = dealerBtn.parentElement;
                    while (el && el !== document.body) {
                        el.classList.forEach(function(c) {
                            var m = c.match(/^table-player-(\\d+)$/);
                            if (m) dealerSeat = parseInt(m[1]);
                        });
                        if (dealerSeat >= 0) break;
                        el = el.parentElement;
                    }
                    // Fallback: nearest player by center-point distance
                    if (dealerSeat < 0) {
                        var dr = dealerBtn.getBoundingClientRect();
                        var dc = {x: (dr.left+dr.right)/2, y: (dr.top+dr.bottom)/2};
                        var minDist = Infinity;
                        document.querySelectorAll('.table-player').forEach(function(p) {
                            if (p.classList.contains('table-player-seat')) return;
                            var pr = p.getBoundingClientRect();
                            var pc = {x:(pr.left+pr.right)/2, y:(pr.top+pr.bottom)/2};
                            var d = Math.sqrt(Math.pow(dc.x-pc.x,2)+Math.pow(dc.y-pc.y,2));
                            if (d < minDist) {
                                minDist = d;
                                p.classList.forEach(function(c) {
                                    var m = c.match(/^table-player-(\\d+)$/);
                                    if (m) dealerSeat = parseInt(m[1]);
                                });
                            }
                        });
                    }
                }

                // Our preflop bet amount
                var myBet = 0;
                var betEl = you.querySelector('.table-player-bet-value .chips-value');
                if (betEl) myBet = parseFloat(betEl.textContent.replace(/[^0-9.]/g,'')) || 0;

                // Count seated (non-empty) players
                var seated = 0;
                document.querySelectorAll('.table-player').forEach(function(p) {
                    if (!p.classList.contains('table-player-seat')) seated++;
                });

                return {ourSeat: ourSeat, dealerSeat: dealerSeat,
                        myBet: myBet, numSeated: seated};
            """)

            if not result or "error" in result:
                return Position.MP

            our_seat = result.get("ourSeat", -1)
            dealer_seat = result.get("dealerSeat", -1)
            my_bet = result.get("myBet", 0)
            num_players = state.num_players or result.get("numSeated", 4)

            def _return(pos: Position, dist: int = -1) -> Position:
                state.position_dist = dist
                return pos

            # Bet-amount heuristic for BB/SB (most reliable)
            if state.is_preflop and state.big_blind > 0:
                if abs(my_bet - state.big_blind) < 1.0:
                    return _return(Position.BB, 2)
                if abs(my_bet - state.big_blind / 2) < 1.0:
                    return _return(Position.SB, 1)

            # Seat-based position if we found both seats
            if our_seat >= 0 and dealer_seat >= 0:
                dist = (our_seat - dealer_seat) % num_players
                if dist == 0:
                    return _return(Position.SB if num_players == 2 else Position.BTN, 0)
                pos = get_position(our_seat, dealer_seat, num_players)
                # Short-handed: UTG/MP is effectively CO
                if num_players <= 5 and pos in (Position.UTG, Position.MP):
                    return _return(Position.CO, dist)
                return _return(pos, dist)

            # Short-handed fallback: use CO (not MP)
            if num_players <= 5:
                return _return(Position.CO)
            return _return(Position.MP)
        except Exception as e:
            logger.warning(f"Position detection failed, defaulting to MP: {e}")
            return Position.MP

    def _parse_community_cards_js(self) -> list[str]:
        """Parse community cards from .table-cards via JS."""
        try:
            comm_data = self.driver.execute_script("""
                var cards = document.querySelectorAll('.table-cards .card');
                var result = [];
                cards.forEach(function(c) {
                    var v = c.querySelector('.value');
                    var s = c.querySelector('.suit:not(.sub-suit)') ||
                            c.querySelector('.suit');
                    if (v && s) {
                        result.push([v.textContent.trim(), s.textContent.trim()]);
                    }
                });
                return result;
            """)
            if not comm_data:
                return []
            cards = []
            for value, suit in comm_data:
                rank = _RANK_MAP.get(value.upper(), value.upper())
                suit_char = _SUIT_MAP.get(suit[0].lower(), "") if suit else ""
                if rank and suit_char:
                    cards.append(f"{rank}{suit_char}")
            return cards
        except Exception as e:
            logger.debug(f"Community card JS error: {e}")
            return []

    def _parse_community_from_log(self) -> list[str]:
        """Parse community cards from PokerNow game log.

        Scans recent log entries for lines like:
          Flop:  [5♠, 8♠, 9♣]
          Turn: 5♠, 8♠, 9♣ [4♥]
          River: 5♠, 8♠, 9♣, 4♥ [J♣]
          -- starting hand #N ... --  (resets community)

        Returns list of card strings like ['5s', '8s', '9c'].
        """
        def _parse_card_str(raw: str) -> str | None:
            """Convert '5♠' or 'J♣' to '5s' or 'Jc'."""
            raw = raw.strip()
            if len(raw) < 2:
                return None
            suit_char = raw[-1]
            suit = _SUIT_UNICODE.get(suit_char)
            if not suit:
                return None
            rank_raw = raw[:-1]
            rank = _RANK_MAP.get(rank_raw.upper())
            if not rank:
                return None
            return f"{rank}{suit}"

        try:
            log_texts = self.driver.execute_script("""
                var msgs = document.querySelectorAll('.game-log-container .log-message');
                var result = [];
                // Read up to 30 most recent entries (newest first in DOM)
                var limit = Math.min(msgs.length, 30);
                for (var i = 0; i < limit; i++) {
                    result.push(msgs[i].textContent.trim());
                }
                return result;
            """)
        except Exception as e:
            logger.debug(f"Failed to read game log: {e}")
            return []

        if not log_texts:
            logger.info("BOARD_DEBUG: no log entries found")
            return []

        # Log first few entries for debugging
        logger.info(f"BOARD_DEBUG: {len(log_texts)} log entries, first 3: {log_texts[:3]}")

        # Walk from newest to oldest, find the latest street line
        for text in log_texts:
            # If we hit a new hand marker before any street, it's preflop
            if _NEW_HAND_RE.search(text):
                return []

            m = _RIVER_RE.search(text)
            if m:
                # All 5 cards: group1 = first 4, group2 = river card
                all_raw = m.group(1) + ", " + m.group(2)
                cards = [_parse_card_str(c) for c in all_raw.split(",")]
                cards = [c for c in cards if c]
                if len(cards) == 5:
                    return cards
                continue

            m = _TURN_RE.search(text)
            if m:
                all_raw = m.group(1) + ", " + m.group(2)
                cards = [_parse_card_str(c) for c in all_raw.split(",")]
                cards = [c for c in cards if c]
                if len(cards) == 4:
                    return cards
                continue

            m = _FLOP_RE.search(text)
            if m:
                cards = [_parse_card_str(c) for c in m.group(1).split(",")]
                cards = [c for c in cards if c]
                if len(cards) == 3:
                    return cards
                continue

        return []

    def _parse_card_element(self, el) -> str | None:
        """Parse a card from DOM element with child spans.

        PokerNow DOM: <div class="card">
            <span class="value">7</span>
            <span class="suit">s</span>
        </div>
        Returns e.g. "7s", "Ah", "Td".
        """
        try:
            value = el.find_element(By.CSS_SELECTOR, ".value").text.strip()
            suit = el.find_element(By.CSS_SELECTOR, ".suit").text.strip()
        except NoSuchElementException:
            return None

        # Normalize: PokerNow uses "10" for ten, we use "T"
        rank = _RANK_MAP.get(value.upper(), value)
        suit_char = _SUIT_MAP.get(suit[0].lower(), "") if suit else ""

        if rank and suit_char:
            return f"{rank}{suit_char}"
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
        """Set raise amount and click raise button.

        PokerNow 2-step raise: click RAISE to open bet panel,
        then set amount via input/slider, then confirm.
        """
        try:
            # Step 1: Click raise to open bet panel
            self._click_button(SELECTORS["raise_btn"])
            time.sleep(0.5)

            # Step 2: Find bet input and set amount
            try:
                bet_input = self.driver.find_element(
                    By.CSS_SELECTOR, SELECTORS["bet_input"]
                )
                bet_input.clear()
                bet_input.send_keys(str(int(amount)))
                time.sleep(0.3)
            except NoSuchElementException:
                logger.debug("No bet input found — using default amount")

            # Step 3: Confirm raise (submit button in raise form)
            confirmed = self._click_button(SELECTORS["raise_confirm"])
            if not confirmed:
                # Fallback: click raise button again
                confirmed = self._click_button(SELECTORS["raise_btn"])
            return confirmed
        except (NoSuchElementException, TimeoutException):
            return False

    def _human_delay(self, action: Action) -> None:
        """Add human-like delay before acting.

        When humanize=False, uses minimal delay (just enough for DOM updates).
        """
        if not self.humanize:
            time.sleep(0.3)
            return

        if action.type == ActionType.FOLD:
            delay = random.uniform(1.0, 3.0)
        elif action.type == ActionType.CHECK:
            delay = random.uniform(1.0, 2.5)
        elif action.type == ActionType.CALL:
            delay = random.uniform(2.0, 5.0)
        elif action.type in (ActionType.RAISE, ActionType.ALL_IN):
            delay = random.uniform(3.0, 7.0)
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
    hand_recorder: HandRecorder | None = None,
) -> None:
    """Main bot loop: poll for turn, get action, execute.

    Between turns, observes the game log to feed opponent statistics.

    Args:
        connector: Connected PokerNow table
        get_action: Strategy function (state -> action)
        poll_interval: How often to check if it's our turn (seconds)
        hand_recorder: Optional HandRecorder for tracking opponent stats
    """
    logger.info("Bot loop started. Waiting for hands...")
    last_log_count = 0
    consecutive_errors = 0

    while True:
        try:
            # Observe game log between turns (even when not our turn)
            if hand_recorder is not None:
                last_log_count = _observe_game_log(
                    connector, hand_recorder, last_log_count,
                )

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
            consecutive_errors = 0  # reset on successful cycle

        except KeyboardInterrupt:
            logger.info("Bot stopped by user (Ctrl+C)")
            if hand_recorder is not None:
                hand_recorder.flush()
            break
        except Exception as e:
            consecutive_errors += 1
            logger.error(f"Unexpected error in bot loop ({consecutive_errors}/5): {e}")
            # Try to fold as emergency action
            try:
                connector.execute_action(Action(ActionType.FOLD))
            except Exception as fold_err:
                logger.error(f"Emergency fold also failed: {fold_err}")
            if consecutive_errors >= 5:
                logger.critical("5 consecutive errors — aborting bot loop")
                break
            time.sleep(2)


def _observe_game_log(
    connector: PokerNowConnector,
    hand_recorder: HandRecorder,
    last_log_count: int,
) -> int:
    """Read new game log entries and feed them to the HandRecorder.

    Returns updated log count for next call.
    """
    from src.tracker.stats import parse_log_entry

    try:
        log_elements = connector.driver.find_elements(
            By.CSS_SELECTOR, SELECTORS["game_log"],
        )
    except (NoSuchElementException, StaleElementReferenceException):
        return last_log_count
    except Exception as e:
        logger.warning(f"Game log observation failed: {e}")
        return last_log_count

    current_count = len(log_elements)
    if current_count <= last_log_count:
        return last_log_count

    # Process only new entries (game log appends at the top in PokerNow,
    # so new entries are at lower indices; we read from oldest-new to newest)
    new_entries = log_elements[:current_count - last_log_count]
    # Reverse so we process oldest first (DOM order is newest-first)
    for el in reversed(new_entries):
        try:
            text = el.text.strip()
            if text:
                event = parse_log_entry(text)
                hand_recorder.process_event(event)
        except StaleElementReferenceException:
            continue
        except Exception as e:
            logger.debug(f"Error parsing log entry: {e}")
            continue

    return current_count
