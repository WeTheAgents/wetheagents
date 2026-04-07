"""Duel engine: Analyst → two betting experts → consensus.

Flow:
1. Analyst sees neutral stats, writes a game scenario
2. Both betting experts see their full card + the analyst's scenario
3. Consensus logic determines final action and stake multiplier

Consensus:
- Both BET same type → STRONG_BET (x1.5)
- Both BET different type → BET with zone-appropriate type (x1.0)
- One BET + one PASS → LEAN (x0.5)
- Both PASS → PASS

Analyst scenario can modify confidence:
- Analyst says blowout for fav + experts say BET → downgrade
- Analyst says tight/coinflip + experts say BET_RL → upgrade
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from src.feature_card import AnalystCard, FeatureCard, OUAnalystCard, OUFeatureCard
from src.llm_expert import (
    GameScenario,
    LLMAnalyst,
    LLMExpert,
    OUGameScenario,
    OUVerdict,
    Verdict,
)

logger = logging.getLogger(__name__)


@dataclass
class DuelResult:
    """Combined result from analyst + two experts analyzing the same game."""

    game_id: str
    zone: str  # "S3_expansion" | "RL_expansion" | "CF_pickem"
    scenario: GameScenario | None  # analyst's prediction
    verdict_a: Verdict
    verdict_b: Verdict
    final_action: str  # "STRONG_BET" | "BET" | "LEAN" | "PASS"
    final_bet_type: str  # "ML" | "RL" | ""
    target_side: str  # "home" | "away" | "" (for CF zone)
    combined_confidence: float
    stake_multiplier: float  # 1.5 / 1.0 / 0.5 / 0.0

    def to_dict(self) -> dict:
        return {
            "game_id": self.game_id,
            "zone": self.zone,
            "scenario": self.scenario.to_dict() if self.scenario else None,
            "verdict_a": self.verdict_a.to_dict(),
            "verdict_b": self.verdict_b.to_dict(),
            "final_action": self.final_action,
            "final_bet_type": self.final_bet_type,
            "target_side": self.target_side,
            "combined_confidence": self.combined_confidence,
            "stake_multiplier": self.stake_multiplier,
        }


@dataclass
class OUDuelResult:
    """Combined result from analyst + two experts on O/U."""

    game_id: str
    scenario: OUGameScenario | None
    verdict_a: OUVerdict
    verdict_b: OUVerdict
    final_action: str  # "STRONG_UNDER" | "UNDER" | "LEAN_UNDER" | "PASS"
    combined_confidence: float
    predicted_total_avg: float
    stake_multiplier: float  # 1.0 / 0.5 / 0.0

    def to_dict(self) -> dict:
        return {
            "game_id": self.game_id,
            "scenario": self.scenario.to_dict() if self.scenario else None,
            "verdict_a": self.verdict_a.to_dict(),
            "verdict_b": self.verdict_b.to_dict(),
            "final_action": self.final_action,
            "combined_confidence": self.combined_confidence,
            "predicted_total_avg": self.predicted_total_avg,
            "stake_multiplier": self.stake_multiplier,
        }


class DuelEngine:
    """Orchestrates Analyst → Experts → Consensus flow."""

    def __init__(
        self,
        expert_a: LLMExpert,
        expert_b: LLMExpert,
        analyst: LLMAnalyst | None = None,
    ):
        self.expert_a = expert_a
        self.expert_b = expert_b
        self.analyst = analyst

    def run(
        self,
        card: FeatureCard,
        analyst_card: AnalystCard | None = None,
    ) -> DuelResult:
        """Full duel: analyst first, then both experts, then arbitrate.

        Args:
            card: Full betting card (with odds, edge, zone) for experts.
            analyst_card: Neutral card for analyst. If None and analyst is
                configured, will be skipped (experts see card without scenario).
        """
        logger.info(f"Duel: {card.game_id} ({card.strategy_zone})")

        # Step 1: Analyst produces scenario (if available)
        scenario = None
        expert_card = card

        if self.analyst and analyst_card:
            logger.info(f"  Analyst ({self.analyst.genome.name}) predicting...")
            scenario = self.analyst.predict(analyst_card)
            logger.info(
                f"  Analyst: {scenario.predicted_winner} wins "
                f"{scenario.predicted_score} ({scenario.tightness}, "
                f"conf={scenario.winner_confidence:.0%})"
            )
            # Inject scenario into the card that experts see
            expert_card = card.with_scenario(scenario.to_text())

        # Step 2: Both betting experts analyze (seeing the scenario)
        verdict_a = self.expert_a.analyze(expert_card)
        verdict_b = self.expert_b.analyze(expert_card)

        logger.info(
            f"  {self.expert_a.genome.name}: {verdict_a.action} "
            f"(conf={verdict_a.confidence:.2f})"
        )
        logger.info(
            f"  {self.expert_b.genome.name}: {verdict_b.action} "
            f"(conf={verdict_b.confidence:.2f})"
        )

        # Step 3: Arbitrate with scenario as tiebreaker/modifier
        result = self._arbitrate(verdict_a, verdict_b, card, scenario)

        logger.info(
            f"  -> {result.final_action} {result.final_bet_type} "
            f"(conf={result.combined_confidence:.2f}, "
            f"stake={result.stake_multiplier}x)"
        )
        return result

    def run_ou(
        self,
        card: OUFeatureCard,
        analyst_card: OUAnalystCard | None = None,
        close_ou: float = 0.0,
    ) -> OUDuelResult:
        """Full O/U duel: analyst → two experts → arbitrate.

        Args:
            card: O/U betting card (with P(under), line) for experts.
            analyst_card: Neutral O/U card for analyst.
            close_ou: Closing O/U line for analyst adjustment.
        """
        logger.info(f"O/U Duel: {card.game_id}")

        # Step 1: Analyst produces scoring scenario
        scenario = None
        expert_card = card

        if self.analyst and analyst_card:
            logger.info(f"  OU Analyst ({self.analyst.genome.name}) predicting...")
            scenario = self.analyst.predict_ou(analyst_card)
            logger.info(
                f"  OU Analyst: total={scenario.predicted_total:.1f} "
                f"({scenario.scoring_pattern})"
            )
            # Build expert card with scenario injected
            expert_card = OUFeatureCard(
                game_id=card.game_id,
                prompt_text=(
                    card.prompt_text
                    + "\n\n── Analyst Scoring Scenario ──\n"
                    + scenario.to_text()
                ),
            )

        # Step 2: Both experts analyze
        verdict_a = self.expert_a.analyze_ou(expert_card)
        verdict_b = self.expert_b.analyze_ou(expert_card)

        logger.info(
            f"  {self.expert_a.genome.name}: {verdict_a.action} "
            f"(conf={verdict_a.confidence:.2f}, total={verdict_a.predicted_total:.1f})"
        )
        logger.info(
            f"  {self.expert_b.genome.name}: {verdict_b.action} "
            f"(conf={verdict_b.confidence:.2f}, total={verdict_b.predicted_total:.1f})"
        )

        # Step 3: Arbitrate
        result = self._arbitrate_ou(verdict_a, verdict_b, card.game_id, scenario, close_ou)

        logger.info(
            f"  -> {result.final_action} "
            f"(conf={result.combined_confidence:.2f}, "
            f"avg_total={result.predicted_total_avg:.1f}, "
            f"stake={result.stake_multiplier}x)"
        )
        return result

    def run_over(
        self,
        card: OUFeatureCard,
        analyst_card: OUAnalystCard | None = None,
        close_ou: float = 0.0,
    ) -> OUDuelResult:
        """Full OVER duel: analyst → two experts → arbitrate.

        Args:
            card: O/U betting card (with P(over), line) for experts.
            analyst_card: Neutral O/U card for analyst.
            close_ou: Closing O/U line for analyst adjustment.
        """
        logger.info(f"OVER Duel: {card.game_id}")

        # Step 1: Analyst produces scoring scenario (neutral)
        scenario = None
        expert_card = card

        if self.analyst and analyst_card:
            logger.info(f"  OU Analyst ({self.analyst.genome.name}) predicting...")
            scenario = self.analyst.predict_ou(analyst_card)
            logger.info(
                f"  OU Analyst: total={scenario.predicted_total:.1f} "
                f"({scenario.scoring_pattern})"
            )
            # Build expert card with scenario injected
            expert_card = OUFeatureCard(
                game_id=card.game_id,
                prompt_text=(
                    card.prompt_text
                    + "\n\n── Analyst Scoring Scenario ──\n"
                    + scenario.to_text()
                ),
            )

        # Step 2: Both experts analyze with OVER system prompt
        verdict_a = self.expert_a.analyze_over(expert_card)
        verdict_b = self.expert_b.analyze_over(expert_card)

        logger.info(
            f"  {self.expert_a.genome.name}: {verdict_a.action} "
            f"(conf={verdict_a.confidence:.2f}, total={verdict_a.predicted_total:.1f})"
        )
        logger.info(
            f"  {self.expert_b.genome.name}: {verdict_b.action} "
            f"(conf={verdict_b.confidence:.2f}, total={verdict_b.predicted_total:.1f})"
        )

        # Step 3: Arbitrate with OVER logic
        result = self._arbitrate_over(verdict_a, verdict_b, card.game_id, scenario, close_ou)

        logger.info(
            f"  -> {result.final_action} "
            f"(conf={result.combined_confidence:.2f}, "
            f"avg_total={result.predicted_total_avg:.1f}, "
            f"stake={result.stake_multiplier}x)"
        )
        return result

    def run_rl_away_v2(
        self,
        card: FeatureCard,
        analyst_card: AnalystCard | None = None,
    ) -> DuelResult:
        """Away +1.5 RL v2: analyst predict_simple -> solo expert -> margin gate.

        Mirrors run_rl_fav() architecture but with inverted margin gate:
        - Margin <= 1: tight game -> BET (covers +1.5)
        - Margin == 2: expert decides
        - Margin >= 3: blowout -> PASS (doesn't cover +1.5)
        """
        logger.info(f"RL Away v2: {card.game_id}")

        # Step 1: Analyst produces simplified scenario (score + narrative)
        scenario = None
        expert_card = card

        if self.analyst and analyst_card:
            logger.info(f"  Analyst ({self.analyst.genome.name}) predicting...")
            scenario = self.analyst.predict_simple(analyst_card)
            logger.info(
                f"  Analyst: {scenario.predicted_winner} wins "
                f"{scenario.predicted_score}"
            )
            expert_card = card.with_scenario(scenario.to_text())

        # Step 2: Solo expert (expert_a only)
        verdict = self.expert_a.analyze_rl_away_v2(expert_card)

        logger.info(
            f"  {self.expert_a.genome.name}: {verdict.action} "
            f"(conf={verdict.confidence:.2f})"
        )

        # Step 3: Analyst margin gate (signed: negative = dog wins)
        analyst_margin = _extract_signed_margin(scenario)
        if verdict.action == "BET_RL":
            if analyst_margin < 0:
                # Analyst predicts dog wins → guaranteed cover
                action, stake = "BET", 1.0
                confidence = verdict.confidence
                logger.info(
                    f"  RL Away v2: analyst predicts dog wins (margin={analyst_margin}) "
                    "-> BET confirmed"
                )
            elif analyst_margin <= 1:
                # Fav wins by 1 → covers +1.5
                action, stake = "BET", 1.0
                confidence = verdict.confidence
                logger.info(
                    f"  RL Away v2: analyst margin={analyst_margin} (tight) "
                    "-> BET confirmed"
                )
            elif analyst_margin >= 3:
                # Fav blowout → override to PASS
                action, stake = "PASS", 0.0
                confidence = 0.0
                logger.info(
                    f"  RL Away v2: analyst margin={analyst_margin} (fav blowout) "
                    "-> override to PASS"
                )
            else:
                # margin == 2: expert decides
                action, stake = "BET", 1.0
                confidence = verdict.confidence
        else:
            action, stake = "PASS", 0.0
            confidence = 0.0

        pass_verdict = Verdict(
            action="PASS", confidence=0.0,
            key_factors=[], risk_flags=[], reasoning="(not used)",
        )

        result = DuelResult(
            game_id=card.game_id,
            zone="RL_away_v2",
            scenario=scenario,
            verdict_a=verdict,
            verdict_b=pass_verdict,
            final_action=action,
            final_bet_type="RL" if action == "BET" else "",
            target_side="away",
            combined_confidence=confidence,
            stake_multiplier=stake,
        )

        logger.info(
            f"  -> {result.final_action} "
            f"(conf={result.combined_confidence:.2f})"
        )
        return result

    def run_rl_fav(
        self,
        card: FeatureCard,
        analyst_card: AnalystCard | None = None,
    ) -> DuelResult:
        """Full fav -1.5 RL duel: analyst -> two experts -> arbitrate.

        Args:
            card: RL fav betting card (zone="RL_fav") for experts.
            analyst_card: Neutral card for analyst scenario prediction.
        """
        logger.info(f"RL Fav: {card.game_id}")

        # Step 1: Analyst produces simplified scenario (score + narrative)
        scenario = None
        expert_card = card

        if self.analyst and analyst_card:
            logger.info(f"  Analyst ({self.analyst.genome.name}) predicting...")
            scenario = self.analyst.predict_simple(analyst_card)
            logger.info(
                f"  Analyst: {scenario.predicted_winner} wins "
                f"{scenario.predicted_score}"
            )
            expert_card = card.with_scenario(scenario.to_text())

        # Step 2: Solo Momentum expert
        verdict = self.expert_a.analyze_rl_fav(expert_card)

        logger.info(
            f"  {self.expert_a.genome.name}: {verdict.action} "
            f"(conf={verdict.confidence:.2f})"
        )

        # Step 3: Direct mapping — no arbitration
        if verdict.action == "BET_RL":
            action, stake = "BET", 1.0
        else:
            action, stake = "PASS", 0.0

        pass_verdict = Verdict(
            action="PASS", confidence=0.0,
            key_factors=[], risk_flags=[], reasoning="(not used)",
        )

        result = DuelResult(
            game_id=card.game_id,
            zone="RL_fav",
            scenario=scenario,
            verdict_a=verdict,
            verdict_b=pass_verdict,
            final_action=action,
            final_bet_type="RL" if action == "BET" else "",
            target_side="fav",
            combined_confidence=verdict.confidence,
            stake_multiplier=stake,
        )

        logger.info(
            f"  -> {result.final_action} "
            f"(conf={result.combined_confidence:.2f})"
        )
        return result

    def run_rl(
        self,
        card: FeatureCard,
        analyst_card: AnalystCard | None = None,
    ) -> DuelResult:
        """Full Away +1.5 RL duel: analyst → two experts → arbitrate.

        Experts use RL-specific system prompt focused on tight-game analysis
        (NOT outright winner prediction).

        Args:
            card: RL expansion betting card (zone="RL_expansion") for experts.
            analyst_card: Neutral card for analyst scenario prediction.
        """
        logger.info(f"RL Away Duel: {card.game_id}")

        # Step 1: Analyst produces scenario
        scenario = None
        expert_card = card

        if self.analyst and analyst_card:
            logger.info(f"  Analyst ({self.analyst.genome.name}) predicting...")
            scenario = self.analyst.predict(analyst_card)
            logger.info(
                f"  Analyst: {scenario.predicted_winner} wins "
                f"{scenario.predicted_score} ({scenario.tightness}, "
                f"conf={scenario.winner_confidence:.0%})"
            )
            expert_card = card.with_scenario(scenario.to_text())

        # Step 2: Both experts analyze with Away +1.5 RL system prompt
        verdict_a = self.expert_a.analyze_rl(expert_card)
        verdict_b = self.expert_b.analyze_rl(expert_card)

        logger.info(
            f"  {self.expert_a.genome.name}: {verdict_a.action} "
            f"(conf={verdict_a.confidence:.2f})"
        )
        logger.info(
            f"  {self.expert_b.genome.name}: {verdict_b.action} "
            f"(conf={verdict_b.confidence:.2f})"
        )

        # Step 3: Arbitrate
        result = self._arbitrate_rl(verdict_a, verdict_b, card, scenario)

        logger.info(
            f"  -> {result.final_action} "
            f"(conf={result.combined_confidence:.2f}, "
            f"stake={result.stake_multiplier}x)"
        )
        return result

    def _arbitrate_rl(
        self,
        a: Verdict,
        b: Verdict,
        card: FeatureCard,
        scenario: GameScenario | None,
    ) -> DuelResult:
        """Away +1.5 RL consensus logic.

        Both BET_RL              → STRONG_BET (1.5x): both see a tight game
        BET_RL + BET_ML          → BET (1.0x): ML win also covers RL
        BET_RL + PASS            → LEAN (0.5x): one signal
        BET_ML + PASS            → LEAN (0.5x): conservative cover lean
        Both PASS / Both BET_ML  → PASS: no RL signal (both BET_ML = S3 zone)
        """
        a_rl = a.action == "BET_RL"
        b_rl = b.action == "BET_RL"
        a_ml = a.action == "BET_ML"
        b_ml = b.action == "BET_ML"

        if a_rl and b_rl:
            action, stake = "STRONG_BET", 1.5
            confidence = (a.confidence + b.confidence) / 2 * 1.1
        elif (a_rl and b_ml) or (a_ml and b_rl):
            # One says RL, other says ML — both outcomes cover +1.5
            action, stake = "BET", 1.0
            confidence = (a.confidence + b.confidence) / 2
        elif a_rl or b_rl:
            # One BET_RL + PASS → LEAN
            bettor = a if a_rl else b
            action, stake = "LEAN", 0.5
            confidence = bettor.confidence * 0.8
        elif (a_ml and not b_ml) or (b_ml and not a_ml):
            # One BET_ML + PASS → conservative RL lean (dog might win = covers)
            bettor = a if a_ml else b
            action, stake = "LEAN", 0.5
            confidence = bettor.confidence * 0.7
        else:
            # Both PASS OR both BET_ML (both see outright upset = S3 signal, not RL)
            action, stake = "PASS", 0.0
            confidence = 0.0

        # Analyst scenario adjustments
        if scenario and action != "PASS":
            if scenario.tightness in ("tight", "coinflip"):
                # Tight game = high +1.5 cover probability
                confidence *= 1.15
                confidence = min(confidence, 1.0)
                logger.info(
                    f"  RL Away: analyst says {scenario.tightness} → conf +15%"
                )
            elif (
                scenario.tightness == "blowout"
                and scenario.predicted_winner == "home"
            ):
                # Fav dominates → away +1.5 very unlikely to cover
                confidence *= 0.70
                if action in ("LEAN", "BET"):
                    action = "PASS"
                    stake = 0.0
                    confidence = 0.0
                    logger.info(
                        "  RL Away: analyst says fav blowout → downgrade to PASS"
                    )
            elif scenario.predicted_winner == "away":
                # Dog wins outright — strong RL cover signal
                confidence *= 1.10
                confidence = min(confidence, 1.0)
                logger.info("  RL Away: analyst says dog wins → conf +10%")

        confidence = min(confidence, 1.0)

        return DuelResult(
            game_id=card.game_id,
            zone=card.strategy_zone,
            scenario=scenario,
            verdict_a=a,
            verdict_b=b,
            final_action=action,
            final_bet_type="RL" if action != "PASS" else "",
            target_side="away",
            combined_confidence=confidence,
            stake_multiplier=stake,
        )

    def _arbitrate_ou(
        self,
        a: OUVerdict,
        b: OUVerdict,
        game_id: str,
        scenario: OUGameScenario | None,
        close_ou: float,
    ) -> OUDuelResult:
        """O/U consensus logic. We only bet UNDER."""
        a_under = a.action == "UNDER"
        b_under = b.action == "UNDER"
        a_over = a.action == "OVER"
        b_over = b.action == "OVER"

        # Average predicted totals from experts
        totals = [v.predicted_total for v in [a, b] if v.predicted_total > 0]
        avg_total = sum(totals) / len(totals) if totals else 0.0

        if a_under and b_under:
            # Both UNDER → cap to UNDER (1.0x) for v1, no STRONG_UNDER yet
            final_action = "UNDER"
            confidence = (a.confidence + b.confidence) / 2
            stake = 1.0
        elif (a_under and b.action == "PASS") or (b_under and a.action == "PASS"):
            # One UNDER + one PASS → LEAN_UNDER
            bettor = a if a_under else b
            final_action = "LEAN_UNDER"
            confidence = bettor.confidence * 0.6
            stake = 0.5
        elif a_over and b_over:
            # Both OVER → PASS (we only bet UNDER)
            final_action = "PASS"
            confidence = 0.0
            stake = 0.0
        elif (a_under and b_over) or (a_over and b_under):
            # Conflict → PASS
            final_action = "PASS"
            confidence = 0.0
            stake = 0.0
            logger.info("  O/U: experts conflict (UNDER vs OVER) → PASS")
        else:
            # Both PASS
            final_action = "PASS"
            confidence = 0.0
            stake = 0.0

        # Analyst adjustment
        if scenario and final_action != "PASS" and close_ou > 0:
            if scenario.predicted_total < close_ou:
                # Analyst confirms UNDER direction
                confidence *= 1.10
                confidence = min(confidence, 0.95)
            elif scenario.predicted_total > close_ou + 1.0:
                # Analyst predicts significantly OVER → downgrade
                confidence *= 0.75
                if final_action == "LEAN_UNDER":
                    final_action = "PASS"
                    stake = 0.0
                    logger.info("  O/U: Analyst says OVER by 1+ → LEAN_UNDER → PASS")

        return OUDuelResult(
            game_id=game_id,
            scenario=scenario,
            verdict_a=a,
            verdict_b=b,
            final_action=final_action,
            combined_confidence=confidence,
            predicted_total_avg=avg_total,
            stake_multiplier=stake,
        )

    def _arbitrate_over(
        self,
        a: OUVerdict,
        b: OUVerdict,
        game_id: str,
        scenario: OUGameScenario | None,
        close_ou: float,
    ) -> OUDuelResult:
        """OVER consensus logic. Symmetric to _arbitrate_ou with direction flipped."""
        a_over = a.action == "OVER"
        b_over = b.action == "OVER"
        a_under = a.action == "UNDER"
        b_under = b.action == "UNDER"

        # Average predicted totals from experts
        totals = [v.predicted_total for v in [a, b] if v.predicted_total > 0]
        avg_total = sum(totals) / len(totals) if totals else 0.0

        if a_over and b_over:
            # Both OVER → OVER (1.0x)
            final_action = "OVER"
            confidence = (a.confidence + b.confidence) / 2
            stake = 1.0
        elif (a_over and b.action == "PASS") or (b_over and a.action == "PASS"):
            # One OVER + one PASS → LEAN_OVER
            bettor = a if a_over else b
            final_action = "LEAN_OVER"
            confidence = bettor.confidence * 0.6
            stake = 0.5
        elif a_under and b_under:
            # Both UNDER → PASS (we only bet OVER here)
            final_action = "PASS"
            confidence = 0.0
            stake = 0.0
        elif (a_over and b_under) or (a_under and b_over):
            # Conflict → PASS
            final_action = "PASS"
            confidence = 0.0
            stake = 0.0
            logger.info("  OVER: experts conflict (OVER vs UNDER) → PASS")
        else:
            # Both PASS
            final_action = "PASS"
            confidence = 0.0
            stake = 0.0

        # Analyst adjustment (inverted from UNDER)
        if scenario and final_action != "PASS" and close_ou > 0:
            if scenario.predicted_total > close_ou:
                # Analyst confirms OVER direction
                confidence *= 1.10
                confidence = min(confidence, 0.95)
            elif scenario.predicted_total < close_ou - 1.0:
                # Analyst predicts significantly UNDER → downgrade
                confidence *= 0.75
                if final_action == "LEAN_OVER":
                    final_action = "PASS"
                    stake = 0.0
                    logger.info("  OVER: Analyst says UNDER by 1+ → LEAN_OVER → PASS")

        return OUDuelResult(
            game_id=game_id,
            scenario=scenario,
            verdict_a=a,
            verdict_b=b,
            final_action=final_action,
            combined_confidence=confidence,
            predicted_total_avg=avg_total,
            stake_multiplier=stake,
        )

    def _arbitrate(
        self,
        a: Verdict,
        b: Verdict,
        card: FeatureCard,
        scenario: GameScenario | None,
    ) -> DuelResult:
        """Apply consensus logic, then adjust with analyst scenario."""
        # Route coinflip zone to its own logic
        if card.strategy_zone.startswith("CF"):
            return self._arbitrate_cf(a, b, card, scenario)

        a_bets = a.action.startswith("BET")
        b_bets = b.action.startswith("BET")

        if a_bets and b_bets:
            a_type = _bet_type(a.action)
            b_type = _bet_type(b.action)

            if a_type == b_type:
                final_action = "STRONG_BET"
                final_type = a_type
                confidence = (a.confidence + b.confidence) / 2
                stake = 1.5
            else:
                final_action = "BET"
                final_type = _zone_default_type(card.strategy_zone)
                confidence = (a.confidence + b.confidence) / 2 * 0.8
                stake = 1.0

        elif a_bets or b_bets:
            bettor = a if a_bets else b
            final_action = "LEAN"
            final_type = _bet_type(bettor.action)
            confidence = bettor.confidence * 0.6
            stake = 0.5

        else:
            final_action = "PASS"
            final_type = ""
            confidence = 0.0
            stake = 0.0

        # ── Expansion-zone cap: never STRONG_BET in expansion ────────
        if "expansion" in card.strategy_zone and final_action == "STRONG_BET":
            final_action = "BET"
            stake = 1.0
            logger.info("  Expansion-zone cap: STRONG_BET → BET (1.0x)")

        # ── Analyst scenario adjustments ──────────────────────────────
        if scenario and final_action != "PASS":
            confidence, stake, final_action = _apply_scenario_adjustment(
                scenario, final_action, final_type, confidence, stake
            )

        return DuelResult(
            game_id=card.game_id,
            zone=card.strategy_zone,
            scenario=scenario,
            verdict_a=a,
            verdict_b=b,
            final_action=final_action,
            final_bet_type=final_type,
            target_side="",
            combined_confidence=confidence,
            stake_multiplier=stake,
        )

    def _arbitrate_cf(
        self,
        a: Verdict,
        b: Verdict,
        card: FeatureCard,
        scenario: GameScenario | None,
    ) -> DuelResult:
        """Coinflip zone arbitration — experts pick sides, not dog/fav."""
        a_side = _cf_side(a.action)
        b_side = _cf_side(b.action)
        a_bets = a_side is not None
        b_bets = b_side is not None

        if a_bets and b_bets:
            if a_side == b_side:
                # Both pick same side → BET (never STRONG_BET for CF)
                final_action = "BET"
                target_side = a_side
                confidence = (a.confidence + b.confidence) / 2
                stake = 1.0
            else:
                # Opposite sides → cancel out → PASS
                final_action = "PASS"
                target_side = ""
                confidence = 0.0
                stake = 0.0
                logger.info("  CF: experts disagree on side → PASS")
        elif a_bets or b_bets:
            # CF: no consensus = no bet. LEAN too risky on coinflips.
            final_action = "PASS"
            target_side = ""
            confidence = 0.0
            stake = 0.0
            logger.info("  CF: only one expert bets → PASS (no LEAN in pick'em)")
        else:
            final_action = "PASS"
            target_side = ""
            confidence = 0.0
            stake = 0.0

        # Analyst scenario adjustment for CF
        if scenario and final_action != "PASS" and target_side:
            analyst_side = (
                "home" if scenario.predicted_winner == "home" else "away"
            )
            if analyst_side == target_side:
                confidence *= 1.10
                confidence = min(confidence, 0.95)
            else:
                confidence *= 0.85

        return DuelResult(
            game_id=card.game_id,
            zone=card.strategy_zone,
            scenario=scenario,
            verdict_a=a,
            verdict_b=b,
            final_action=final_action,
            final_bet_type="ML",
            target_side=target_side,
            combined_confidence=confidence,
            stake_multiplier=stake,
        )


def _cf_side(action: str) -> str | None:
    """Extract side from CF verdict action. Returns None for PASS."""
    if action == "BET_HOME":
        return "home"
    elif action == "BET_AWAY":
        return "away"
    return None


def _apply_scenario_adjustment(
    scenario: GameScenario,
    action: str,
    bet_type: str,
    confidence: float,
    stake: float,
) -> tuple[float, float, str]:
    """Adjust confidence/stake based on analyst scenario.

    The analyst is a calibration anchor — not a veto. Adjustments are
    moderate, not binary.
    """
    # Analyst says home wins (= fav wins, dog loses)
    analyst_says_fav = scenario.predicted_winner == "home"

    if analyst_says_fav and scenario.tightness == "blowout":
        # Analyst predicts blowout for favorite — bad for ANY dog bet
        # Downgrade: STRONG_BET→BET, BET→LEAN, LEAN→PASS
        confidence *= 0.6
        if action == "STRONG_BET":
            action = "BET"
            stake = 1.0
        elif action == "BET":
            action = "LEAN"
            stake = 0.5
        elif action == "LEAN":
            action = "PASS"
            stake = 0.0

    elif analyst_says_fav and scenario.tightness == "comfortable":
        # Comfortable fav win — ML risky, but RL might still cover
        if bet_type == "ML":
            confidence *= 0.75
            if action == "STRONG_BET":
                action = "BET"
                stake = 1.0
        # RL gets a smaller penalty — "comfortable" 2-3 run win still
        # means the dog could lose by 1 on a different day
        elif bet_type == "RL":
            confidence *= 0.85

    elif not analyst_says_fav:
        # Analyst predicts AWAY wins (= dog wins) — confirms dog edge
        if scenario.tightness == "blowout":
            # Analyst predicts dog blowout — strong confirmation
            confidence *= 1.20
            confidence = min(confidence, 0.95)
            if action == "LEAN":
                action = "BET"
                stake = 1.0
        elif scenario.tightness in ("comfortable", "tight"):
            # Analyst leans dog — moderate confirmation
            confidence *= 1.10
            confidence = min(confidence, 0.95)

    elif scenario.tightness in ("tight", "coinflip"):
        # Analyst says fav wins but barely — good for RL bets
        if bet_type == "RL":
            confidence *= 1.15
            confidence = min(confidence, 0.95)
        # Tight fav win is neutral for ML (could go either way)

    return confidence, stake, action


def _bet_type(action: str) -> str:
    """Extract bet type from action string."""
    if "ML" in action:
        return "ML"
    elif "RL" in action:
        return "RL"
    return "ML"


def _zone_default_type(zone: str) -> str:
    """Default bet type for a given expansion zone."""
    if "S3" in zone:
        return "ML"
    else:
        return "RL"


def _extract_margin(scenario) -> int:
    """Extract predicted run margin from analyst scenario.

    Parses "5-3" -> 2, "4-3" -> 1, "7-2" -> 5.
    Returns 2 (neutral) if parsing fails or scenario is None.
    """
    if scenario is None:
        return 2
    try:
        score = scenario.predicted_score.replace("-", " ").split()
        return abs(int(score[0]) - int(score[1]))
    except (ValueError, IndexError, AttributeError):
        return 2


def _extract_signed_margin(scenario) -> int:
    """Extract signed margin: positive = home (fav) wins, negative = away (dog) wins.

    Used by RL Away v3 to distinguish dog wins from fav blowouts.
    Score format is always "winner_runs-loser_runs" (winner first).
    Returns +2 (neutral) if parsing fails or scenario is None.
    """
    if scenario is None:
        return 2
    try:
        score = scenario.predicted_score.replace("-", " ").split()
        margin = abs(int(score[0]) - int(score[1]))
        if scenario.predicted_winner == "away":
            return -margin  # dog wins → negative
        return margin  # home wins → positive
    except (ValueError, IndexError, AttributeError):
        return 2
