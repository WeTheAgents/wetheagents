"""LLM expert layer for football betting — Analyst + Betting Expert.

Architecture (adapted from MLB domain):
  1. Analyst sees neutral MatchCard → produces GameScenario
  2. Betting Expert sees BettingCard (odds + model + scenario) → produces Verdict (BET/PASS)

Both driven by YAML genome files (philosophy, principles, anti-patterns, confidence modifiers).

Usage:
    from src.llm_expert import Genome, LLMAnalyst, LLMBettingExpert

    genome_analyst = Genome.load("genomes/analyst_v1.yaml")
    genome_expert = Genome.load("genomes/edge_hunter_v1.yaml")

    analyst = LLMAnalyst(genome_analyst)
    expert = LLMBettingExpert(genome_expert)

    scenario = analyst.predict(match_card)
    verdict = expert.analyze(betting_card)
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

GENOMES_DIR = Path(__file__).parent.parent / "genomes"


# ---------------------------------------------------------------------------
# Genome
# ---------------------------------------------------------------------------

@dataclass
class Genome:
    """Expert genome — drives LLM behavior via system prompt injection."""

    name: str
    version: int
    philosophy: str
    principles: list[str]
    anti_patterns: list[str] = field(default_factory=list)
    examples: list[dict] = field(default_factory=list)
    confidence_modifiers: dict[str, float] = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path) -> "Genome":
        path = Path(path)
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return cls(
            name=data["name"],
            version=data.get("version", 1),
            philosophy=data["philosophy"],
            principles=data.get("principles", []),
            anti_patterns=data.get("anti_patterns", []),
            examples=data.get("examples", []),
            confidence_modifiers=data.get("confidence_modifiers", {}),
        )

    @classmethod
    def load_latest(cls, name: str) -> "Genome":
        candidates = sorted(GENOMES_DIR.glob(f"{name}_v*.yaml"))
        if not candidates:
            raise FileNotFoundError(f"No genome found for '{name}' in {GENOMES_DIR}")
        return cls.load(candidates[-1])


# ---------------------------------------------------------------------------
# Output dataclasses
# ---------------------------------------------------------------------------

@dataclass
class GameScenario:
    """Analyst output — neutral game prediction."""

    predicted_winner: str      # "home", "away", or "draw"
    predicted_score: str       # e.g. "2-1"
    tightness: str             # "blowout", "comfortable", "tight", "coinflip"
    total_goals: str           # "low" (<2), "normal" (2-3), "high" (>3)
    key_narrative: str         # 2-3 sentence scenario
    decisive_factors: list[str]

    def to_text(self) -> str:
        return (
            f"Prediction: {self.predicted_winner} wins ({self.predicted_score}), "
            f"tightness={self.tightness}, total={self.total_goals}\n"
            f"Narrative: {self.key_narrative}\n"
            f"Factors: {', '.join(self.decisive_factors)}"
        )

    def to_dict(self) -> dict:
        return {
            "predicted_winner": self.predicted_winner,
            "predicted_score": self.predicted_score,
            "tightness": self.tightness,
            "total_goals": self.total_goals,
            "key_narrative": self.key_narrative,
            "decisive_factors": self.decisive_factors,
        }


@dataclass
class Verdict:
    """Betting Expert output — BET or PASS decision."""

    action: str            # "BET" or "PASS"
    market: str            # "1X2_H", "1X2_D", "1X2_A", "O2.5", "U2.5", ""
    confidence: float      # 0.0-1.0
    edge_estimate: float   # model_p - market_p for chosen market
    key_factors: list[str]
    risk_flags: list[str]
    reasoning: str

    def to_dict(self) -> dict:
        return {
            "action": self.action,
            "market": self.market,
            "confidence": self.confidence,
            "edge_estimate": self.edge_estimate,
            "key_factors": self.key_factors,
            "risk_flags": self.risk_flags,
            "reasoning": self.reasoning,
        }


# ---------------------------------------------------------------------------
# JSON schema templates for LLM output
# ---------------------------------------------------------------------------

_ANALYST_SCHEMA = """\
Return a JSON object with exactly these fields:
{
  "predicted_winner": "home" | "away" | "draw",
  "predicted_score": "2-1",
  "tightness": "blowout" | "comfortable" | "tight" | "coinflip",
  "total_goals": "low" | "normal" | "high",
  "key_narrative": "2-3 sentences: how does this game play out?",
  "decisive_factors": ["factor 1", "factor 2", "factor 3"]
}

Rules:
- predicted_winner: who wins or "draw" if evenly matched
- predicted_score: most likely exact score
- tightness: blowout (3+ goal margin), comfortable (2 goals), tight (1 goal), coinflip (could go either way)
- total_goals: low (<2 total), normal (2-3 total), high (>3 total)
- key_narrative: paint the most probable game scenario in 2-3 sentences
- decisive_factors: top 3 statistical factors driving your prediction
"""

_EXPERT_SCHEMA = """\
Return a JSON object with exactly these fields:
{
  "action": "BET" | "PASS",
  "market": "1X2_H" | "1X2_D" | "1X2_A" | "O2.5" | "U2.5" | "",
  "confidence": 0.0 to 1.0,
  "edge_estimate": 0.062,
  "key_factors": ["reason 1", "reason 2", "reason 3"],
  "risk_flags": ["concern 1", "concern 2"],
  "reasoning": "2-3 sentence rationale"
}

Rules:
- BET = genuine edge detected, specific market identified
- PASS = not enough edge, skip this match
- market: which bet to place (empty string on PASS)
  - 1X2_H = home win, 1X2_D = draw, 1X2_A = away win
  - O2.5 = over 2.5 goals, U2.5 = under 2.5 goals
- confidence: 0.5 = marginal, 0.7 = decent edge, 0.85+ = strong conviction
- edge_estimate: your estimated edge in probability points (model P - market P)
- Most matches should be PASS. Only bet when regime + discrepancy + analyst align.
"""


# ---------------------------------------------------------------------------
# LLM Analyst
# ---------------------------------------------------------------------------

class LLMAnalyst:
    """Neutral game analyst — predicts match scenarios without betting context."""

    def __init__(
        self,
        genome: Genome,
        *,
        provider: str = "openai",
        model: str = "gpt-5.4",
        temperature: float = 0.4,
    ):
        self.genome = genome
        self.provider = provider
        self.model = model
        self.temperature = temperature
        self._client = None

    def predict(self, card) -> GameScenario:
        """Analyze a neutral MatchCard and produce a GameScenario."""
        system_prompt = self._build_system_prompt()
        user_prompt = card.to_prompt()

        for attempt in range(3):
            raw = self._call_llm(system_prompt, user_prompt)
            scenario = self._parse_response(raw)
            if scenario.key_narrative != "parse_error":
                return scenario
            logger.warning(f"Analyst parse retry {attempt + 1}/3")
        return scenario

    def _build_system_prompt(self) -> str:
        g = self.genome
        parts = [
            f"You are {g.name}, an expert Turkish Super Lig football analyst.",
            "",
            "## Your Approach",
            g.philosophy,
        ]

        if g.principles:
            parts.append("\n## Analytical Principles")
            for i, p in enumerate(g.principles, 1):
                parts.append(f"{i}. {p}")

        if g.anti_patterns:
            parts.append("\n## Learned Corrections")
            for i, ap in enumerate(g.anti_patterns, 1):
                parts.append(f"{i}. {ap}")

        parts.append("\n## Context")
        parts.append(
            "You are a pure football analyst. You have no knowledge of betting lines, "
            "odds, or market prices. Your only job is to predict the most likely match "
            "outcome based on the statistical profiles of both teams.\n\n"
            "Be calibrated: home advantage in the Turkish Super Lig is ~58%, draws occur "
            "in ~25% of matches, and most games are decided by 1 goal. Even the best teams "
            "lose regularly to organized mid-table sides."
        )

        parts.append(f"\n## Output Format\n{_ANALYST_SCHEMA}")
        return "\n".join(parts)

    def _call_llm(self, system_prompt: str, user_prompt: str) -> str:
        if self.provider == "openai":
            if self._client is None:
                from openai import OpenAI
                self._client = OpenAI()
            response = self._client.chat.completions.create(
                model=self.model,
                temperature=self.temperature,
                max_completion_tokens=512,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            return response.choices[0].message.content
        elif self.provider == "anthropic":
            if self._client is None:
                from anthropic import Anthropic
                self._client = Anthropic()
            response = self._client.messages.create(
                model=self.model,
                max_tokens=512,
                temperature=self.temperature,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            return response.content[0].text
        else:
            raise ValueError(f"Unknown provider: {self.provider}")

    def _parse_response(self, raw: str) -> GameScenario:
        text = raw.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [ln for ln in lines if not ln.strip().startswith("```")]
            text = "\n".join(lines)

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning(f"Analyst parse error: {text[:200]}")
            return GameScenario(
                predicted_winner="home",
                predicted_score="1-1",
                tightness="tight",
                total_goals="normal",
                key_narrative="parse_error",
                decisive_factors=["parse_error"],
            )

        winner = data.get("predicted_winner", "home").lower()
        if winner not in ("home", "away", "draw"):
            winner = "home"

        tightness = data.get("tightness", "tight").lower()
        if tightness not in ("blowout", "comfortable", "tight", "coinflip"):
            tightness = "tight"

        total_goals = data.get("total_goals", "normal").lower()
        if total_goals not in ("low", "normal", "high"):
            total_goals = "normal"

        return GameScenario(
            predicted_winner=winner,
            predicted_score=data.get("predicted_score", "1-1"),
            tightness=tightness,
            total_goals=total_goals,
            key_narrative=data.get("key_narrative", ""),
            decisive_factors=data.get("decisive_factors", []),
        )


# ---------------------------------------------------------------------------
# LLM Betting Expert
# ---------------------------------------------------------------------------

class LLMBettingExpert:
    """Betting expert — decides BET or PASS based on model + market + scenario."""

    def __init__(
        self,
        genome: Genome,
        *,
        provider: str = "openai",
        model: str = "gpt-5.4",
        temperature: float = 0.3,
    ):
        self.genome = genome
        self.provider = provider
        self.model = model
        self.temperature = temperature
        self._client = None

    def analyze(self, card) -> Verdict:
        """Analyze a BettingCard and produce a Verdict."""
        system_prompt = self._build_system_prompt()
        user_prompt = card.to_prompt()

        for attempt in range(3):
            raw = self._call_llm(system_prompt, user_prompt)
            verdict = self._parse_response(raw)
            if verdict.reasoning != "parse_error":
                return verdict
            logger.warning(f"Expert parse retry {attempt + 1}/3")
        return verdict

    def _build_system_prompt(self) -> str:
        g = self.genome
        parts = [
            f"You are {g.name}, an expert Turkish Super Lig betting analyst.",
            "",
            "## Your Philosophy (core identity — never deviate)",
            g.philosophy,
        ]

        if g.principles:
            parts.append("\n## Your Principles")
            for i, p in enumerate(g.principles, 1):
                parts.append(f"{i}. {p}")

        if g.anti_patterns:
            parts.append("\n## Lessons Learned (mistakes to NEVER repeat)")
            for i, ap in enumerate(g.anti_patterns, 1):
                parts.append(f"{i}. {ap}")

        if g.confidence_modifiers:
            parts.append("\n## Confidence Adjustments")
            parts.append("Apply these modifiers to your raw confidence:")
            for key, val in g.confidence_modifiers.items():
                parts.append(f"  - {key}: {val:+.2f}")

        parts.append("\n## Context")
        parts.append(
            "You are analyzing a Turkish Super Lig match. You see the full statistical "
            "profile, market odds, model predictions, and an analyst's scenario.\n\n"
            "Your job: decide BET or PASS. Most matches should be PASS — only bet when "
            "you see genuine edge from regime alignment + model discrepancy + analyst "
            "confirmation. A single goal from a set piece can decide any game. Your edge "
            "is over 100+ bets, not any single match.\n\n"
            "Key regime insight: our model is strongest on congestion + squad disruption "
            "matches involving non-Big-3 teams. Big-3 matches = automatic PASS."
        )

        parts.append(f"\n## Output Format\n{_EXPERT_SCHEMA}")
        return "\n".join(parts)

    def _call_llm(self, system_prompt: str, user_prompt: str) -> str:
        if self.provider == "openai":
            if self._client is None:
                from openai import OpenAI
                self._client = OpenAI()
            response = self._client.chat.completions.create(
                model=self.model,
                temperature=self.temperature,
                max_completion_tokens=512,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            return response.choices[0].message.content
        elif self.provider == "anthropic":
            if self._client is None:
                from anthropic import Anthropic
                self._client = Anthropic()
            response = self._client.messages.create(
                model=self.model,
                max_tokens=512,
                temperature=self.temperature,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            return response.content[0].text
        else:
            raise ValueError(f"Unknown provider: {self.provider}")

    def _parse_response(self, raw: str) -> Verdict:
        text = raw.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [ln for ln in lines if not ln.strip().startswith("```")]
            text = "\n".join(lines)

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning(f"Expert parse error: {text[:200]}")
            return Verdict(
                action="PASS",
                market="",
                confidence=0.0,
                edge_estimate=0.0,
                key_factors=["parse_error"],
                risk_flags=["parse_error"],
                reasoning="parse_error",
            )

        action = data.get("action", "PASS").upper()
        if action not in ("BET", "PASS"):
            action = "PASS"

        market = data.get("market", "")
        valid_markets = {"1X2_H", "1X2_D", "1X2_A", "O2.5", "U2.5", ""}
        if market not in valid_markets:
            market = ""

        confidence = float(data.get("confidence", 0.0))
        confidence = max(0.0, min(1.0, confidence))

        edge = float(data.get("edge_estimate", 0.0))

        return Verdict(
            action=action,
            market=market,
            confidence=confidence,
            edge_estimate=edge,
            key_factors=data.get("key_factors", []),
            risk_flags=data.get("risk_flags", []),
            reasoning=data.get("reasoning", ""),
        )
