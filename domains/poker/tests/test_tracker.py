"""Tests for opponent tracker: log parsing, HandRecorder, and stat tracking."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.tracker.stats import (
    HandRecorder,
    LogEvent,
    LogEventType,
    OpponentTracker,
    PlayerStats,
    parse_log_entry,
)


# --- parse_log_entry tests ---


class TestParseLogEntry:
    """Test PokerNow game log line parsing."""

    def test_fold(self):
        event = parse_log_entry('"Alice" folds')
        assert event.type == LogEventType.FOLD
        assert event.player == "Alice"

    def test_check(self):
        event = parse_log_entry("Bob checks")
        assert event.type == LogEventType.CHECK
        assert event.player == "Bob"

    def test_call(self):
        event = parse_log_entry("Alice calls 200")
        assert event.type == LogEventType.CALL
        assert event.player == "Alice"
        assert event.amount == 200.0

    def test_raise_to(self):
        event = parse_log_entry("Bob raises to 500")
        assert event.type == LogEventType.RAISE
        assert event.player == "Bob"
        assert event.amount == 500.0

    def test_bets(self):
        event = parse_log_entry("Charlie bets 300")
        assert event.type == LogEventType.RAISE
        assert event.player == "Charlie"
        assert event.amount == 300.0

    def test_all_in(self):
        event = parse_log_entry("Dave goes all in with 1,500")
        assert event.type == LogEventType.ALL_IN
        assert event.player == "Dave"
        assert event.amount == 1500.0

    def test_all_in_hyphenated(self):
        event = parse_log_entry("Dave all-in 2,000")
        assert event.type == LogEventType.ALL_IN
        assert event.player == "Dave"
        assert event.amount == 2000.0

    def test_shows(self):
        event = parse_log_entry('Alice shows [Ah Kd]')
        assert event.type == LogEventType.SHOW
        assert event.player == "Alice"
        assert event.cards == ["Ah", "Kd"]

    def test_wins(self):
        event = parse_log_entry("Bob wins 1,200")
        assert event.type == LogEventType.WIN
        assert event.player == "Bob"
        assert event.amount == 1200.0

    def test_new_hand(self):
        event = parse_log_entry("Starting Hand #42")
        assert event.type == LogEventType.NEW_HAND

    def test_flop(self):
        event = parse_log_entry("flop: [Ah 7c 2d]")
        assert event.type == LogEventType.FLOP

    def test_turn(self):
        event = parse_log_entry("turn: [Ks]")
        assert event.type == LogEventType.TURN

    def test_river(self):
        event = parse_log_entry("river: [3h]")
        assert event.type == LogEventType.RIVER

    def test_unknown(self):
        event = parse_log_entry("some random text")
        assert event.type == LogEventType.UNKNOWN

    def test_empty(self):
        event = parse_log_entry("")
        assert event.type == LogEventType.UNKNOWN

    def test_pokernow_at_suffix(self):
        """PokerNow uses 'Player @ id' format — strip the suffix."""
        event = parse_log_entry('"Alice @ abc123" folds')
        assert event.type == LogEventType.FOLD
        assert event.player == "Alice"

    def test_call_with_commas(self):
        event = parse_log_entry("Alice calls 1,000")
        assert event.type == LogEventType.CALL
        assert event.amount == 1000.0


# --- HandRecorder tests ---


class TestHandRecorder:
    """Test the HandRecorder state machine."""

    def _make_recorder(self, my_name: str = "Hero"):
        tracker = OpponentTracker()
        recorder = HandRecorder(tracker, my_name=my_name)
        return tracker, recorder

    def test_simple_hand_preflop_fold(self):
        """Track a hand where villain folds preflop."""
        tracker, rec = self._make_recorder()

        rec.process_event(LogEvent(type=LogEventType.NEW_HAND))
        rec.process_event(LogEvent(type=LogEventType.CALL, player="Alice", amount=20))
        rec.process_event(LogEvent(type=LogEventType.FOLD, player="Bob"))
        rec.process_event(LogEvent(type=LogEventType.WIN, player="Alice", amount=50))

        alice = tracker.get_stats("Alice")
        assert alice.hands_seen == 1
        assert alice.vpip_count == 1  # called

        bob = tracker.get_stats("Bob")
        assert bob.hands_seen == 1
        assert bob.vpip_count == 0  # folded

    def test_preflop_raise_tracked(self):
        """PFR is tracked correctly."""
        tracker, rec = self._make_recorder()

        rec.process_event(LogEvent(type=LogEventType.NEW_HAND))
        rec.process_event(LogEvent(type=LogEventType.RAISE, player="Alice", amount=60))
        rec.process_event(LogEvent(type=LogEventType.FOLD, player="Bob"))
        rec.process_event(LogEvent(type=LogEventType.WIN, player="Alice", amount=90))

        alice = tracker.get_stats("Alice")
        assert alice.pfr_count == 1
        assert alice.vpip_count == 1

    def test_postflop_aggression(self):
        """Postflop bets/calls tracked for aggression factor."""
        tracker, rec = self._make_recorder()

        rec.process_event(LogEvent(type=LogEventType.NEW_HAND))
        rec.process_event(LogEvent(type=LogEventType.CALL, player="Alice", amount=20))
        rec.process_event(LogEvent(type=LogEventType.CALL, player="Bob", amount=20))
        rec.process_event(LogEvent(type=LogEventType.FLOP))
        rec.process_event(LogEvent(type=LogEventType.RAISE, player="Alice", amount=40))
        rec.process_event(LogEvent(type=LogEventType.CALL, player="Bob", amount=40))
        rec.process_event(LogEvent(type=LogEventType.WIN, player="Alice", amount=120))

        alice = tracker.get_stats("Alice")
        assert alice.bets_and_raises == 1
        assert alice.calls == 0  # preflop call doesn't count as postflop

        bob = tracker.get_stats("Bob")
        assert bob.bets_and_raises == 0
        assert bob.calls == 1

    def test_cbet_tracking(self):
        """C-bet: preflop raiser bets flop."""
        tracker, rec = self._make_recorder()

        rec.process_event(LogEvent(type=LogEventType.NEW_HAND))
        rec.process_event(LogEvent(type=LogEventType.RAISE, player="Alice", amount=60))
        rec.process_event(LogEvent(type=LogEventType.CALL, player="Bob", amount=60))
        rec.process_event(LogEvent(type=LogEventType.FLOP))
        rec.process_event(LogEvent(type=LogEventType.RAISE, player="Alice", amount=80))
        rec.process_event(LogEvent(type=LogEventType.WIN, player="Alice", amount=200))

        alice = tracker.get_stats("Alice")
        assert alice.cbet_opportunities == 1
        assert alice.cbet_count == 1

    def test_cbet_missed(self):
        """C-bet missed: preflop raiser checks flop."""
        tracker, rec = self._make_recorder()

        rec.process_event(LogEvent(type=LogEventType.NEW_HAND))
        rec.process_event(LogEvent(type=LogEventType.RAISE, player="Alice", amount=60))
        rec.process_event(LogEvent(type=LogEventType.CALL, player="Bob", amount=60))
        rec.process_event(LogEvent(type=LogEventType.FLOP))
        rec.process_event(LogEvent(type=LogEventType.CHECK, player="Alice"))
        rec.process_event(LogEvent(type=LogEventType.RAISE, player="Bob", amount=80))
        rec.process_event(LogEvent(type=LogEventType.WIN, player="Bob", amount=200))

        alice = tracker.get_stats("Alice")
        assert alice.cbet_opportunities == 1
        assert alice.cbet_count == 0

    def test_fold_to_raise_tracked(self):
        """Fold-to-raise: player folds facing a postflop bet."""
        tracker, rec = self._make_recorder()

        rec.process_event(LogEvent(type=LogEventType.NEW_HAND))
        rec.process_event(LogEvent(type=LogEventType.CALL, player="Alice", amount=20))
        rec.process_event(LogEvent(type=LogEventType.CALL, player="Bob", amount=20))
        rec.process_event(LogEvent(type=LogEventType.FLOP))
        rec.process_event(LogEvent(type=LogEventType.RAISE, player="Alice", amount=40))
        rec.process_event(LogEvent(type=LogEventType.FOLD, player="Bob"))
        rec.process_event(LogEvent(type=LogEventType.WIN, player="Alice", amount=80))

        bob = tracker.get_stats("Bob")
        assert bob.fold_to_raise_opportunities == 1
        assert bob.fold_to_raise_count == 1

    def test_hero_actions_ignored(self):
        """Our own actions should not be tracked."""
        tracker, rec = self._make_recorder("Hero")

        rec.process_event(LogEvent(type=LogEventType.NEW_HAND))
        rec.process_event(LogEvent(type=LogEventType.RAISE, player="Hero", amount=60))
        rec.process_event(LogEvent(type=LogEventType.CALL, player="Alice", amount=60))
        rec.process_event(LogEvent(type=LogEventType.WIN, player="Hero", amount=120))

        # Hero should not be tracked
        hero = tracker.get_stats("Hero")
        assert hero.hands_seen == 0

    def test_multiple_hands(self):
        """Multiple hands accumulate stats correctly."""
        tracker, rec = self._make_recorder()

        # Hand 1: Alice folds
        rec.process_event(LogEvent(type=LogEventType.NEW_HAND))
        rec.process_event(LogEvent(type=LogEventType.FOLD, player="Alice"))
        rec.process_event(LogEvent(type=LogEventType.WIN, player="Bob", amount=30))

        # Hand 2: Alice calls
        rec.process_event(LogEvent(type=LogEventType.NEW_HAND))
        rec.process_event(LogEvent(type=LogEventType.CALL, player="Alice", amount=20))
        rec.process_event(LogEvent(type=LogEventType.WIN, player="Alice", amount=40))

        alice = tracker.get_stats("Alice")
        assert alice.hands_seen == 2
        assert alice.vpip_count == 1

    def test_limp_tracking(self):
        """Limp: call preflop without a prior raise."""
        tracker, rec = self._make_recorder()

        rec.process_event(LogEvent(type=LogEventType.NEW_HAND))
        rec.process_event(LogEvent(type=LogEventType.CALL, player="Alice", amount=20))
        rec.process_event(LogEvent(type=LogEventType.RAISE, player="Bob", amount=60))
        rec.process_event(LogEvent(type=LogEventType.WIN, player="Bob", amount=80))

        alice = tracker.get_stats("Alice")
        assert alice.limp_count == 1
        assert alice.limp_opportunities == 1

    def test_flush(self):
        """flush() finalizes in-progress hand."""
        tracker, rec = self._make_recorder()

        rec.process_event(LogEvent(type=LogEventType.NEW_HAND))
        rec.process_event(LogEvent(type=LogEventType.CALL, player="Alice", amount=20))
        # No WIN event — force finalize
        rec.flush()

        alice = tracker.get_stats("Alice")
        assert alice.hands_seen == 1

    def test_street_transitions(self):
        """Street transitions track postflop actions per street."""
        tracker, rec = self._make_recorder()

        rec.process_event(LogEvent(type=LogEventType.NEW_HAND))
        rec.process_event(LogEvent(type=LogEventType.CALL, player="Alice", amount=20))
        rec.process_event(LogEvent(type=LogEventType.CALL, player="Bob", amount=20))
        rec.process_event(LogEvent(type=LogEventType.FLOP))
        rec.process_event(LogEvent(type=LogEventType.CHECK, player="Alice"))
        rec.process_event(LogEvent(type=LogEventType.CHECK, player="Bob"))
        rec.process_event(LogEvent(type=LogEventType.TURN))
        rec.process_event(LogEvent(type=LogEventType.RAISE, player="Alice", amount=60))
        rec.process_event(LogEvent(type=LogEventType.CALL, player="Bob", amount=60))
        rec.process_event(LogEvent(type=LogEventType.WIN, player="Alice", amount=160))

        alice = tracker.get_stats("Alice")
        assert alice.bets_and_raises == 1  # turn bet
        bob = tracker.get_stats("Bob")
        assert bob.calls == 1  # turn call


# --- PlayerStats property tests ---


class TestPlayerStats:
    """Test PlayerStats computed properties."""

    def test_consecutive_folds_afk(self):
        """is_likely_afk after 6+ consecutive folds."""
        tracker = OpponentTracker()
        for _ in range(6):
            tracker.record_hand("Alice", vpip=False, pfr=False)
        assert tracker.get_stats("Alice").is_likely_afk is True

    def test_consecutive_folds_reset_on_vpip(self):
        """Consecutive folds reset when player puts money in."""
        tracker = OpponentTracker()
        for _ in range(5):
            tracker.record_hand("Alice", vpip=False, pfr=False)
        tracker.record_hand("Alice", vpip=True, pfr=False)
        assert tracker.get_stats("Alice").consecutive_folds == 0
        assert tracker.get_stats("Alice").is_likely_afk is False

    def test_max_consecutive_folds(self):
        """max_consecutive_folds tracks longest streak."""
        tracker = OpponentTracker()
        for _ in range(4):
            tracker.record_hand("Alice", vpip=False, pfr=False)
        tracker.record_hand("Alice", vpip=True, pfr=False)
        for _ in range(7):
            tracker.record_hand("Alice", vpip=False, pfr=False)
        assert tracker.get_stats("Alice").max_consecutive_folds == 7

    def test_limp_frequency(self):
        """Limp frequency calculated correctly."""
        tracker = OpponentTracker()
        for _ in range(3):
            tracker.record_limp("Alice", had_opportunity=True, did_limp=True)
        for _ in range(7):
            tracker.record_limp("Alice", had_opportunity=True, did_limp=False)

        alice = tracker.get_stats("Alice")
        assert abs(alice.limp_frequency - 0.30) < 0.01

    def test_limp_frequency_not_enough_data(self):
        """Limp frequency returns 0 without enough data."""
        tracker = OpponentTracker()
        tracker.record_limp("Alice", had_opportunity=True, did_limp=True)
        assert tracker.get_stats("Alice").limp_frequency == 0.0

    def test_player_type_classification(self):
        """Player type classification after enough hands."""
        stats = PlayerStats(name="Test", hands_seen=20, vpip_count=14, pfr_count=10)
        # VPIP=0.70 (loose), PFR/VPIP=0.71 (aggressive) -> LAG
        assert stats.player_type == "LAG"

    def test_player_type_tight_passive(self):
        stats = PlayerStats(name="Test", hands_seen=20, vpip_count=4, pfr_count=1)
        # VPIP=0.20 (tight), PFR/VPIP=0.25 (passive) -> TP
        assert stats.player_type == "TP"

    def test_player_type_unknown_few_hands(self):
        stats = PlayerStats(name="Test", hands_seen=5)
        assert stats.player_type == "unknown"
