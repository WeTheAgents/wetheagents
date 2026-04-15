"""LLM Expert engine with evolvable genomes.

Three expert roles:
- LLMAnalyst: pure game analyst, no betting context. Goes first.
- LLMExpert (x2): betting experts with different genomes. See the scenario.

Each expert has a Genome (system prompt ingredients) that evolves over time
through retrospective analysis of betting outcomes.

Provider-agnostic: supports OpenAI (default) and Anthropic backends.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from src.feature_card import FeatureCard, OUFeatureCard

logger = logging.getLogger(__name__)


def _retry_llm_call(fn, *args, max_retries: int = 5, base_delay: float = 2.0, **kwargs) -> str:
    """Retry an LLM API call with exponential backoff on connection errors."""
    for attempt in range(max_retries):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            err_str = str(e).lower()
            is_transient = any(s in err_str for s in [
                "connection", "timeout", "getaddrinfo", "reset by peer",
                "server_error", "rate_limit", "503", "502", "429",
            ])
            if not is_transient or attempt == max_retries - 1:
                raise
            delay = base_delay * (2 ** attempt)
            logger.warning(f"LLM call failed (attempt {attempt+1}/{max_retries}): {e}. "
                           f"Retrying in {delay:.0f}s...")
            time.sleep(delay)


# ── Genome ────────────────────────────────────────────────────────────────


@dataclass
class Genome:
    """Mutable expert identity — evolves through retrospective learning."""

    name: str  # "Momentum" / "Value"
    philosophy: str  # IMMUTABLE core identity
    principles: list[str] = field(default_factory=list)
    anti_patterns: list[str] = field(default_factory=list)
    examples: list[dict] = field(default_factory=list)
    confidence_modifiers: dict[str, float] = field(default_factory=dict)
    version: int = 1

    def save(self, path: Path) -> None:
        """Serialize genome to YAML."""
        data = {
            "name": self.name,
            "version": self.version,
            "philosophy": self.philosophy,
            "principles": self.principles,
            "anti_patterns": self.anti_patterns,
            "examples": self.examples,
            "confidence_modifiers": self.confidence_modifiers,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        logger.info(f"Genome saved: {path} (v{self.version})")

    @classmethod
    def load(cls, path: Path) -> "Genome":
        """Deserialize genome from YAML."""
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        genome = cls(
            name=data["name"],
            philosophy=data["philosophy"],
            principles=data.get("principles", []),
            anti_patterns=data.get("anti_patterns", []),
            examples=data.get("examples", []),
            confidence_modifiers=data.get("confidence_modifiers", {}),
            version=data.get("version", 1),
        )
        logger.info(f"Genome loaded: {path} (v{genome.version}, "
                     f"{len(genome.anti_patterns)} anti-patterns)")
        return genome


# ── Verdict ───────────────────────────────────────────────────────────────


@dataclass
class Verdict:
    """Structured expert verdict on a game."""

    action: str  # "BET_ML" | "BET_RL" | "PASS"
    confidence: float  # 0.0 - 1.0
    key_factors: list[str]  # top 3-5 reasons FOR
    risk_flags: list[str]  # concerns AGAINST
    reasoning: str  # 2-3 sentence rationale

    def to_dict(self) -> dict:
        return {
            "action": self.action,
            "confidence": self.confidence,
            "key_factors": self.key_factors,
            "risk_flags": self.risk_flags,
            "reasoning": self.reasoning,
        }


# ── LLM Expert ────────────────────────────────────────────────────────────

# JSON output schema instruction appended to every expert call
_OUTPUT_SCHEMA = """\
Respond with ONLY a JSON object (no markdown, no explanation outside JSON):
{
  "action": "BET_ML" | "BET_RL" | "PASS",
  "confidence": 0.0 to 1.0,
  "key_factors": ["reason 1", "reason 2", "reason 3"],
  "risk_flags": ["concern 1", "concern 2"],
  "reasoning": "2-3 sentence rationale"
}

Rules:
- BET_ML = bet on underdog moneyline (dog wins outright)
- BET_RL = bet on underdog run line +1.5 (dog loses by ≤1 or wins)
- PASS = not enough edge, skip this game
- confidence: 0.5 = coin flip, 0.7 = decent edge, 0.85+ = strong conviction
- You MUST give a verdict. Do not hedge. Either you see edge or you don't.
"""

_OUTPUT_SCHEMA_CF = """\
Respond with ONLY a JSON object (no markdown, no explanation outside JSON):
{
  "action": "BET" | "PASS",
  "side": "home" | "away",
  "confidence": 0.0 to 1.0,
  "key_factors": ["reason 1", "reason 2", "reason 3"],
  "risk_flags": ["concern 1", "concern 2"],
  "reasoning": "2-3 sentence rationale"
}

Rules:
- BET = one side has genuine edge, bet their moneyline
- PASS = too close to call, no clear edge worth betting
- side: which team you'd back (required even on PASS — state who is stronger)
- confidence: 0.5 = true coin flip, 0.6 = slight lean, 0.7+ = genuine edge
- These are PICK'EM games. Most should be PASS. Only bet when one side has
  clear structural advantages the market hasn't priced in.
"""


_OUTPUT_SCHEMA_OU = """\
Respond with ONLY a JSON object (no markdown, no explanation outside JSON):
{
  "action": "UNDER" | "OVER" | "PASS",
  "confidence": 0.0 to 1.0,
  "predicted_total": 7.5,
  "key_factors": ["reason 1", "reason 2", "reason 3"],
  "risk_flags": ["concern 1", "concern 2"],
  "reasoning": "2-3 sentence rationale"
}

Rules:
- UNDER = total runs will be below the O/U line
- OVER = total runs will be above the O/U line (be honest even though we're looking for UNDER)
- PASS = no clear edge on either side of the total
- predicted_total: your best estimate of total runs (e.g., 7.5)
- confidence: 0.5 = coin flip, 0.7 = decent edge, 0.85+ = strong conviction
- You MUST give a verdict. Do not hedge. Either you see edge or you don't.
"""


_OUTPUT_SCHEMA_OU_OVER = """\
Respond with ONLY a JSON object (no markdown, no explanation outside JSON):
{
  "action": "UNDER" | "OVER" | "PASS",
  "confidence": 0.0 to 1.0,
  "predicted_total": 7.5,
  "key_factors": ["reason 1", "reason 2", "reason 3"],
  "risk_flags": ["concern 1", "concern 2"],
  "reasoning": "2-3 sentence rationale"
}

Rules:
- OVER = total runs will be above the O/U line (be honest even though we're looking for OVER)
- UNDER = total runs will be below the O/U line
- PASS = no clear edge on either side of the total
- predicted_total: your best estimate of total runs (e.g., 7.5)
- confidence: 0.5 = coin flip, 0.7 = decent edge, 0.85+ = strong conviction
- You MUST give a verdict. Do not hedge. Either you see edge or you don't.
"""


_OUTPUT_SCHEMA_OU_SCORER = """\
Respond with ONLY a JSON object (no markdown, no explanation outside JSON):
{
  "predicted_total": 7.5,
  "probable_delta": 2.0,
  "key_factors": ["factor 1", "factor 2", "factor 3"],
  "reasoning": "2-3 sentence rationale explaining your scoring estimate"
}

Rules:
- predicted_total: your best estimate of total runs scored by both teams
- probable_delta: the likely swing in either direction. E.g., predicted_total=7
  with delta=1.5 means you expect 5.5-8.5 runs. Small delta = high conviction,
  large delta = uncertain game
- Build your reasoning FIRST, then derive predicted_total from it
- League averages are provided in the card — use them for calibration
- Focus on scoring volume from BOTH sides, not who wins
"""


_OUTPUT_SCHEMA_RL_FAV = """\
Respond with ONLY a JSON object (no markdown, no explanation outside JSON):
{
  "action": "BET_RL" | "PASS",
  "confidence": 0.0 to 1.0,
  "predicted_margin": "3-1",
  "key_factors": ["reason 1", "reason 2", "reason 3"],
  "risk_flags": ["concern 1", "concern 2"],
  "reasoning": "2-3 sentence rationale"
}

Rules:
- BET_RL = favorite will win by 2+ runs (covers -1.5 run line)
- PASS = favorite may win but not by enough margin, or too much uncertainty
- predicted_margin: your best estimate of the final score (e.g., "5-2", "4-1")
- confidence: 0.5 = coin flip, 0.7 = decent edge, 0.85+ = strong conviction
- Breakeven cover rate is ~42%. The market average is ~43%. Your edge comes
  from identifying COMFORTABLE wins, not just any favorite win.
- You MUST give a verdict. Do not hedge. Either you see a 2+ run margin or you don't.
"""


_OUTPUT_SCHEMA_RL_AWAY_V2 = """\
Respond with ONLY a JSON object (no markdown, no explanation outside JSON):
{
  "action": "BET_RL" | "PASS",
  "confidence": 0.0 to 1.0,
  "key_factors": ["reason 1", "reason 2", "reason 3"],
  "risk_flags": ["concern 1", "concern 2"],
  "reasoning": "2-3 sentence rationale"
}

Rules:
- BET_RL = away underdog covers +1.5 (loses by 1 or wins outright)
- PASS = too much risk of a 2+ run blowout, or not enough signal
- confidence: 0.5 = coin flip, 0.7 = decent edge, 0.85+ = strong conviction
- You MUST give a verdict. Do not hedge. Either you see a tight game or you don't.
"""


@dataclass
class OUVerdict:
    """Structured expert verdict on O/U."""

    action: str  # "UNDER" | "OVER" | "PASS"
    confidence: float
    predicted_total: float
    key_factors: list[str]
    risk_flags: list[str]
    reasoning: str

    def to_dict(self) -> dict:
        return {
            "action": self.action,
            "confidence": self.confidence,
            "predicted_total": self.predicted_total,
            "key_factors": self.key_factors,
            "risk_flags": self.risk_flags,
            "reasoning": self.reasoning,
        }


class LLMExpert:
    """LLM-powered betting expert with genome-driven analysis."""

    def __init__(
        self,
        genome: Genome,
        *,
        provider: str = "openai",
        model: str = "gpt-4o-mini",
        temperature: float = 0.3,
    ):
        self.genome = genome
        self.provider = provider
        self.model = model
        self.temperature = temperature
        self._client = None

    def analyze(self, card: FeatureCard) -> Verdict:
        """Analyze a feature card and produce a structured verdict."""
        is_cf = card.strategy_zone.startswith("CF")
        system_prompt = (
            self._build_system_prompt_cf() if is_cf
            else self._build_system_prompt()
        )
        user_prompt = card.to_prompt()

        for attempt in range(3):
            raw = self._call_llm(system_prompt, user_prompt)
            verdict = (
                self._parse_response_cf(raw) if is_cf
                else self._parse_response(raw)
            )
            if "parse_error" not in verdict.key_factors:
                return verdict
            logger.warning(
                f"Parse retry {attempt + 1}/3 for {self.genome.name}"
            )
        return verdict

    def analyze_ou(self, card: OUFeatureCard, *, zone_context: str | None = None) -> OUVerdict:
        """Analyze an O/U feature card and produce a structured verdict.

        Args:
            card: Feature card with game matchup data.
            zone_context: Optional override for the prompt Context section.
        """
        system_prompt = self._build_system_prompt_ou(zone_context=zone_context)
        user_prompt = card.to_prompt()

        for attempt in range(3):
            raw = self._call_llm(system_prompt, user_prompt)
            verdict = self._parse_response_ou(raw)
            if "parse_error" not in verdict.key_factors:
                return verdict
            logger.warning(
                f"OU parse retry {attempt + 1}/3 for {self.genome.name}"
            )
        return verdict

    def _build_system_prompt(self) -> str:
        """Compose genome into a system prompt."""
        g = self.genome
        parts = [
            f"You are {g.name}, an expert MLB handicapper specializing in underdog betting.",
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

        if g.examples:
            parts.append("\n## Reference Picks (calibrate your confidence)")
            for ex in g.examples[-5:]:  # Keep last 5 to manage prompt size
                parts.append(f"- Game: {ex.get('summary', '?')}")
                parts.append(f"  Verdict: {ex.get('verdict', '?')}")
                parts.append(f"  Outcome: {ex.get('outcome', '?')}")
                if ex.get("lesson"):
                    parts.append(f"  Lesson: {ex['lesson']}")

        if g.confidence_modifiers:
            parts.append("\n## Confidence Adjustments")
            parts.append("Apply these modifiers to your raw confidence:")
            for key, mod in g.confidence_modifiers.items():
                parts.append(f"- {key}: {mod:+.2f}")

        parts.append("\n## Context")
        parts.append(
            "You are analyzing games from the EXPANSION ZONE — these are borderline "
            "games that didn't pass strict mechanical filters but show some promise. "
            "Your job is to find the ones with genuine edge. Most games here should be "
            "PASS — only bet when you see clear confluence of signals. "
            "Remember: a single 3-run homer or defensive collapse can decide any game. "
            "Your edge is over 100+ games, not any single outcome."
        )

        parts.append(f"\n## Output Format\n{_OUTPUT_SCHEMA}")

        return "\n".join(parts)

    def _build_system_prompt_cf(self) -> str:
        """Compose genome into a system prompt for coinflip/pick'em games."""
        g = self.genome
        parts = [
            f"You are {g.name}, an expert MLB handicapper evaluating a PICK'EM game.",
            "",
            "These teams are priced nearly even by the market. Your job is NOT to find "
            "an underdog — it's to determine which side, if either, has a genuine edge "
            "the market is missing.",
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
            for key, mod in g.confidence_modifiers.items():
                parts.append(f"- {key}: {mod:+.2f}")

        parts.append("\n## Context")
        parts.append(
            "This is a PICK'EM game — the market sees these teams as nearly equal. "
            "Home field advantage is minimal in these matchups. Look for asymmetric "
            "information: pitcher mismatches, form divergence, bullpen edges, or "
            "structural quality gaps the market hasn't fully priced. "
            "Most pick'em games should be PASS. Only bet when you see genuine "
            "confluence. Remember: variance is highest in even matchups."
        )

        parts.append(f"\n## Output Format\n{_OUTPUT_SCHEMA_CF}")

        return "\n".join(parts)

    def _build_system_prompt_ou(self, *, zone_context: str | None = None) -> str:
        """Compose genome into a system prompt for O/U totals evaluation.

        Args:
            zone_context: Optional override for the Context section. If provided,
                replaces the default "P(under) >= 60%" framing.
        """
        g = self.genome
        parts = [
            f"You are {g.name}, an expert MLB totals evaluator.",
            "",
            "Your job is to evaluate whether the total runs scored will go OVER or "
            "UNDER the posted O/U line. You are NOT picking a winner — you are "
            "predicting scoring volume.",
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
            for key, mod in g.confidence_modifiers.items():
                parts.append(f"- {key}: {mod:+.2f}")

        parts.append("\n## Context")
        if zone_context:
            parts.append(zone_context)
        else:
            parts.append(
                "These games have been pre-filtered by an ML classifier that gives them "
                "P(under) >= 60%. Your job is to validate or override that signal using "
                "the full statistical context. The ML model is good but not perfect — "
                "look for factors it might miss: bullpen trends, offensive cold/hot streaks, "
                "pitcher matchup dynamics. Be honest: if you see OVER, say OVER. "
                "Standard O/U odds are -110 (52.38% breakeven). "
                "You need to be right more than 52.4% to be profitable."
            )

        parts.append(f"\n## Output Format\n{_OUTPUT_SCHEMA_OU}")

        return "\n".join(parts)

    def _build_system_prompt_over(self) -> str:
        """Compose genome into a system prompt for OVER totals evaluation."""
        g = self.genome
        parts = [
            f"You are {g.name}, an expert MLB totals evaluator.",
            "",
            "Your job is to evaluate whether the total runs scored will go OVER or "
            "UNDER the posted O/U line. You are NOT picking a winner — you are "
            "predicting scoring volume.",
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
            for key, mod in g.confidence_modifiers.items():
                parts.append(f"- {key}: {mod:+.2f}")

        parts.append("\n## Context")
        parts.append(
            "These games have been pre-filtered by an ML classifier that gives them "
            "P(over) >= 55%. Your job is to validate or override that signal using "
            "the full statistical context. The ML model is good but not perfect — "
            "look for factors it might miss: bullpen fatigue trends, offensive "
            "hot streaks, short starters exposing tired bullpens. "
            "Be honest: if you see UNDER, say UNDER. "
            "Standard O/U odds are -110 (52.38% breakeven). "
            "You need to be right more than 52.4% to be profitable."
        )

        parts.append(f"\n## Output Format\n{_OUTPUT_SCHEMA_OU_OVER}")

        return "\n".join(parts)

    def analyze_over(self, card: "OUFeatureCard") -> OUVerdict:
        """Evaluate an O/U game card for OVER direction. Returns OUVerdict."""
        system_prompt = self._build_system_prompt_over()
        user_prompt = card.to_prompt()

        for attempt in range(3):
            raw = self._call_llm(system_prompt, user_prompt)
            verdict = self._parse_response_ou(raw)
            if verdict.action != "PASS" or verdict.confidence > 0:
                return verdict
            logger.warning(f"OVER parse retry {attempt + 1}/3 for {card.game_id}")

        return verdict

    def _build_system_prompt_ou_scorer(self) -> str:
        """Compose genome into a neutral scoring estimator prompt.

        No betting context, no action/confidence — just predicted_total
        and probable_delta (uncertainty range in runs).
        """
        g = self.genome
        parts = [
            f"You are {g.name}, an expert MLB scoring analyst.",
            "",
            "Your job is to estimate the total runs scored in this game. "
            "You are not making a betting recommendation — just predicting "
            "scoring volume as accurately as you can.",
            "",
            "## Your Approach",
            g.philosophy,
        ]

        if g.principles:
            parts.append("\n## Analytical Principles")
            for i, p in enumerate(g.principles, 1):
                parts.append(f"{i}. {p}")

        if g.anti_patterns:
            parts.append("\n## Pitfalls to Avoid")
            for i, ap in enumerate(g.anti_patterns, 1):
                parts.append(f"{i}. {ap}")

        parts.append(f"\n## Output Format\n{_OUTPUT_SCHEMA_OU_SCORER}")

        return "\n".join(parts)

    def analyze_ou_scoring(self, card: "OUFeatureCard") -> dict:
        """Estimate total runs without betting bias. Returns raw dict.

        Output keys: predicted_total (float), probable_delta (float),
        key_factors (list[str]), reasoning (str).
        """
        system_prompt = self._build_system_prompt_ou_scorer()
        user_prompt = card.to_prompt()

        for attempt in range(3):
            raw = self._call_llm(system_prompt, user_prompt)
            result = self._parse_response_ou_scoring(raw)
            if result.get("reasoning") != "parse_error":
                return result
            logger.warning(
                f"Scorer parse retry {attempt + 1}/3 for {card.game_id}"
            )
        return result

    def _parse_response_ou_scoring(self, raw: str) -> dict:
        """Parse scorer JSON response into a plain dict."""
        text = raw.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning(f"Scorer parse error: {text[:200]}")
            return {
                "predicted_total": 8.5,
                "probable_delta": 3.0,
                "key_factors": ["parse_error"],
                "reasoning": "parse_error",
            }

        return {
            "predicted_total": float(data.get("predicted_total", 8.5)),
            "probable_delta": float(data.get("probable_delta", 3.0)),
            "key_factors": data.get("key_factors", []),
            "reasoning": data.get("reasoning", ""),
        }

    def _parse_response_ou(self, raw: str) -> OUVerdict:
        """Parse LLM response for O/U verdict."""
        text = raw.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse OU response as JSON: {text[:200]}")
            return OUVerdict(
                action="PASS",
                confidence=0.0,
                predicted_total=0.0,
                key_factors=["parse_error"],
                risk_flags=["LLM response was not valid JSON"],
                reasoning=f"Parse error. Raw: {text[:100]}",
            )

        action = data.get("action", "PASS").upper()
        if action not in ("UNDER", "OVER", "PASS"):
            action = "PASS"

        confidence = float(data.get("confidence", 0.0))
        confidence = max(0.0, min(1.0, confidence))

        predicted_total = float(data.get("predicted_total", 0.0))

        return OUVerdict(
            action=action,
            confidence=confidence,
            predicted_total=predicted_total,
            key_factors=data.get("key_factors", []),
            risk_flags=data.get("risk_flags", []),
            reasoning=data.get("reasoning", ""),
        )

    def _parse_response_cf(self, raw: str) -> Verdict:
        """Parse LLM response for coinflip zone (includes side field)."""
        text = raw.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse CF response as JSON: {text[:200]}")
            return Verdict(
                action="PASS",
                confidence=0.0,
                key_factors=["parse_error"],
                risk_flags=["LLM response was not valid JSON"],
                reasoning=f"Parse error. Raw: {text[:100]}",
            )

        action = data.get("action", "PASS").upper()
        side = data.get("side", "home").lower()
        if side not in ("home", "away"):
            side = "home"

        if action == "BET":
            action = f"BET_{side.upper()}"
        elif action != "PASS":
            action = "PASS"

        confidence = float(data.get("confidence", 0.0))
        confidence = max(0.0, min(1.0, confidence))

        return Verdict(
            action=action,
            confidence=confidence,
            key_factors=data.get("key_factors", []),
            risk_flags=data.get("risk_flags", []),
            reasoning=data.get("reasoning", ""),
        )

    def analyze_rl(self, card: FeatureCard) -> Verdict:
        """Evaluate an Away +1.5 RL game card. Returns Verdict (BET_RL, BET_ML, or PASS).

        BET_RL = away team covers +1.5 (loses by ≤1 or wins outright)
        BET_ML = dog wins outright (also covers RL)
        PASS   = fav likely wins by 2+, skip
        """
        system_prompt = self._build_system_prompt_rl()
        user_prompt = card.to_prompt()

        for attempt in range(3):
            raw = self._call_llm(system_prompt, user_prompt)
            verdict = self._parse_response(raw)
            if "parse_error" not in verdict.key_factors:
                return verdict
            logger.warning(
                f"RL away parse retry {attempt + 1}/3 for {card.game_id}"
            )

        return verdict

    def _build_system_prompt_rl(self) -> str:
        """Compose genome into a system prompt for Away +1.5 RL analysis."""
        g = self.genome
        parts = [
            f"You are {g.name}, an expert MLB handicapper specializing in "
            "UNDERDOG RUN LINE +1.5 betting.",
            "",
            "You are analyzing whether the AWAY UNDERDOG will COVER +1.5.",
            "The away team covers if they LOSE BY 1 RUN OR LESS, or WIN OUTRIGHT.",
            "This is NOT about picking winners. You are betting AGAINST a dominant win.",
            "A 3-1 loss still COVERS +1.5. A 4-1 loss does NOT.",
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

        if g.examples:
            parts.append("\n## Reference Picks (calibrate your confidence)")
            for ex in g.examples[-5:]:
                parts.append(f"- Game: {ex.get('summary', '?')}")
                parts.append(f"  Verdict: {ex.get('verdict', '?')}")
                parts.append(f"  Outcome: {ex.get('outcome', '?')}")
                if ex.get("lesson"):
                    parts.append(f"  Lesson: {ex['lesson']}")

        if g.confidence_modifiers:
            parts.append("\n## Confidence Adjustments")
            parts.append("Apply these modifiers to your raw confidence:")
            for key, mod in g.confidence_modifiers.items():
                parts.append(f"- {key}: {mod:+.2f}")

        parts.append("\n## Context")
        parts.append(
            "These games passed a coarse pre-filter (edge_consensus > 0.05), meaning "
            "the model sees the home favorite as OVERPRICED. Your job is the SECOND "
            "filter — confirm that matchup specifics support a COMPETITIVE game "
            "(within 1 run). The market embeds the blowout narrative. Your edge is "
            "reading structural reality against that narrative.\n"
            "PASS generously — target 20-30% bet rate. Only BET_RL when 2+ signals "
            "converge to indicate the game will NOT be a 2+ run blowout. "
            "Use BET_ML only if you believe the dog has a genuine shot to win outright."
        )

        parts.append(f"\n## Output Format\n{_OUTPUT_SCHEMA}")

        return "\n".join(parts)

    def analyze_rl_away_v2(self, card: FeatureCard) -> Verdict:
        """Away +1.5 RL v2: solo expert, no edge_consensus, reads analyst score.

        BET_RL = away covers +1.5 (loses by <=1 or wins)
        PASS   = blowout risk too high
        """
        system_prompt = self._build_system_prompt_rl_away_v2()
        user_prompt = card.to_prompt()

        for attempt in range(3):
            raw = self._call_llm(system_prompt, user_prompt)
            verdict = self._parse_response_rl_fav(raw)  # reuse BET_RL/PASS parser
            if "parse_error" not in verdict.key_factors:
                return verdict
            logger.warning(
                f"RL away v2 parse retry {attempt + 1}/3 for {card.game_id}"
            )

        return verdict

    def _build_system_prompt_rl_away_v2(self) -> str:
        """System prompt for Away +1.5 v2/v3 — find strong underdogs."""
        g = self.genome
        parts = [
            f"You are {g.name}, an expert MLB analyst specializing in "
            "identifying UNDERVALUED AWAY UNDERDOGS.",
            "",
            "The away team has +1.5 run line insurance -- they cover if they "
            "LOSE BY 1 OR LESS, or WIN OUTRIGHT. Your primary thesis: can this "
            "underdog COMPETE AND WIN? The +1.5 is the safety net.",
            "",
            "72% of historical +1.5 covers come from the underdog WINNING THE "
            "GAME. Only 28% from losing by exactly 1 run. Find strong dogs.",
            "",
            "## Your Philosophy (core identity -- never deviate)",
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

        if g.examples:
            parts.append("\n## Reference Picks (calibrate your confidence)")
            for ex in g.examples[-5:]:
                parts.append(f"- Game: {ex.get('summary', '?')}")
                parts.append(f"  Verdict: {ex.get('verdict', '?')}")
                parts.append(f"  Outcome: {ex.get('outcome', '?')}")
                if ex.get("lesson"):
                    parts.append(f"  Lesson: {ex['lesson']}")

        if g.confidence_modifiers:
            parts.append("\n## Confidence Adjustments")
            parts.append("Apply these modifiers to your raw confidence:")
            for key, mod in g.confidence_modifiers.items():
                parts.append(f"- {key}: {mod:+.2f}")

        parts.append("\n## Context")
        parts.append(
            "You will see an Independent Analyst Scenario with a predicted final "
            "score. Use it to inform your judgment:\n"
            "- Analyst predicts AWAY wins: strong signal that the underdog is "
            "live to win outright -- lean BET unless fundamentals are terrible.\n"
            "- Analyst predicts HOME wins by 1-2: borderline. Check if the "
            "underdog has structural advantages the analyst may underweight "
            "(road WP, pitcher matchup, momentum).\n"
            "- Analyst predicts HOME wins by 3+: blowout. Lean PASS.\n\n"
            "PASS generously -- target 30-40% bet rate. Only BET_RL when "
            "multiple indicators converge showing the underdog can compete."
        )

        parts.append(f"\n## Output Format\n{_OUTPUT_SCHEMA_RL_AWAY_V2}")

        return "\n".join(parts)

    def analyze_rl_fav(self, card: FeatureCard) -> Verdict:
        """Evaluate a fav -1.5 RL game card. Returns Verdict (BET_RL or PASS)."""
        system_prompt = self._build_system_prompt_rl_fav()
        user_prompt = card.to_prompt()

        for attempt in range(3):
            raw = self._call_llm(system_prompt, user_prompt)
            verdict = self._parse_response_rl_fav(raw)
            if verdict.action != "PASS" or verdict.confidence > 0:
                return verdict
            logger.warning(f"RL fav parse retry {attempt + 1}/3 for {card.game_id}")

        return verdict

    def _build_system_prompt_rl_fav(self) -> str:
        """Compose genome into a system prompt for fav -1.5 RL analysis."""
        g = self.genome
        parts = [
            f"You are {g.name}, an expert MLB handicapper specializing in "
            "FAVORITE RUN LINE -1.5 betting.",
            "",
            "You are analyzing whether the FAVORITE will win by 2+ runs.",
            "This is NOT about whether the favorite wins — it's about the MARGIN.",
            "A 3-2 win is a LOSS on this bet. A 4-2 win is a WIN.",
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

        if g.examples:
            parts.append("\n## Reference Picks (calibrate your confidence)")
            for ex in g.examples[-5:]:
                parts.append(f"- Game: {ex.get('summary', '?')}")
                parts.append(f"  Verdict: {ex.get('verdict', '?')}")
                parts.append(f"  Outcome: {ex.get('outcome', '?')}")
                if ex.get("lesson"):
                    parts.append(f"  Lesson: {ex['lesson']}")

        if g.confidence_modifiers:
            parts.append("\n## Confidence Adjustments")
            parts.append("Apply these modifiers to your raw confidence:")
            for key, mod in g.confidence_modifiers.items():
                parts.append(f"- {key}: {mod:+.2f}")

        parts.append("\n## Context")
        parts.append(
            "These games have already passed a rule-based pre-filter selecting "
            "favorites with structural dominance profiles (low close-game WP + "
            "positive momentum). Your job is the SECOND filter — confirm that the "
            "matchup specifics support a 2+ run margin. Most pre-filtered games "
            "still won't cover. Only bet when you see clear margin-expanding signals. "
            "Remember: even a 60% ML favorite only covers -1.5 about 43% of the time."
        )

        parts.append(f"\n## Output Format\n{_OUTPUT_SCHEMA_RL_FAV}")

        return "\n".join(parts)

    def _parse_response_rl_fav(self, raw: str) -> Verdict:
        """Parse LLM response for RL fav verdict."""
        text = raw.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse RL fav response as JSON: {text[:200]}")
            return Verdict(
                action="PASS",
                confidence=0.0,
                key_factors=["parse_error"],
                risk_flags=["LLM response was not valid JSON"],
                reasoning=f"Parse error. Raw: {text[:100]}",
            )

        action = data.get("action", "PASS").upper()
        if action not in ("BET_RL", "PASS"):
            action = "PASS"

        confidence = float(data.get("confidence", 0.0))
        confidence = max(0.0, min(1.0, confidence))

        return Verdict(
            action=action,
            confidence=confidence,
            key_factors=data.get("key_factors", []),
            risk_flags=data.get("risk_flags", []),
            reasoning=data.get("reasoning", ""),
        )

    def _call_llm(self, system_prompt: str, user_prompt: str) -> str:
        """Call the LLM API with retry on transient errors."""
        if self.provider == "openai":
            return _retry_llm_call(self._call_openai, system_prompt, user_prompt)
        elif self.provider == "anthropic":
            return _retry_llm_call(self._call_anthropic, system_prompt, user_prompt)
        else:
            raise ValueError(f"Unknown provider: {self.provider}")

    def _call_openai(self, system_prompt: str, user_prompt: str) -> str:
        """Call OpenAI API."""
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

    def _call_anthropic(self, system_prompt: str, user_prompt: str) -> str:
        """Call Anthropic API."""
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

    def _parse_response(self, raw: str) -> Verdict:
        """Parse LLM response into a Verdict."""
        # Strip markdown code fences if present
        text = raw.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            # Remove first and last lines (fences)
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse LLM response as JSON: {text[:200]}")
            return Verdict(
                action="PASS",
                confidence=0.0,
                key_factors=["parse_error"],
                risk_flags=["LLM response was not valid JSON"],
                reasoning=f"Parse error. Raw: {text[:100]}",
            )

        action = data.get("action", "PASS").upper()
        if action not in ("BET_ML", "BET_RL", "PASS"):
            action = "PASS"

        confidence = float(data.get("confidence", 0.0))
        confidence = max(0.0, min(1.0, confidence))

        return Verdict(
            action=action,
            confidence=confidence,
            key_factors=data.get("key_factors", []),
            risk_flags=data.get("risk_flags", []),
            reasoning=data.get("reasoning", ""),
        )


# ── Game Scenario (Analyst output) ───────────────────────────────────────


@dataclass
class GameScenario:
    """Pure game prediction from the Analyst — no betting context."""

    predicted_winner: str  # "home" | "away"
    winner_confidence: float  # 0.5 (coinflip) to 0.95 (near certain)
    predicted_score: str  # e.g. "5-3" (winner-loser)
    tightness: str  # "blowout" | "comfortable" | "tight" | "coinflip"
    key_narrative: str  # 2-3 sentence game flow prediction
    decisive_factors: list[str]  # top 3 factors that decide the game

    def to_text(self) -> str:
        """Render as text for injection into betting experts' cards."""
        lines = [
            f"Predicted winner: {self.predicted_winner} "
            f"(confidence: {self.winner_confidence:.0%})",
            f"Predicted score: {self.predicted_score}",
            f"Game type: {self.tightness}",
            f"Narrative: {self.key_narrative}",
            f"Decisive factors: {'; '.join(self.decisive_factors)}",
        ]
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "predicted_winner": self.predicted_winner,
            "winner_confidence": self.winner_confidence,
            "predicted_score": self.predicted_score,
            "tightness": self.tightness,
            "key_narrative": self.key_narrative,
            "decisive_factors": self.decisive_factors,
        }


@dataclass
class OUGameScenario:
    """Analyst prediction for O/U — scoring pattern, not winner."""

    predicted_total: float
    scoring_pattern: str  # "low" | "normal" | "high"
    key_narrative: str
    decisive_factors: list[str]

    def to_text(self) -> str:
        return (
            f"Predicted total: {self.predicted_total:.1f}\n"
            f"Scoring pattern: {self.scoring_pattern}\n"
            f"Narrative: {self.key_narrative}\n"
            f"Decisive factors: {'; '.join(self.decisive_factors)}"
        )

    def to_dict(self) -> dict:
        return {
            "predicted_total": self.predicted_total,
            "scoring_pattern": self.scoring_pattern,
            "key_narrative": self.key_narrative,
            "decisive_factors": self.decisive_factors,
        }


# ── Analyst system prompt ─────────────────────────────────────────────────

_ANALYST_SCHEMA = """\
Respond with ONLY a JSON object (no markdown, no explanation outside JSON):
{
  "predicted_winner": "home" or "away",
  "winner_confidence": 0.50 to 0.95,
  "predicted_score": "5-3",
  "tightness": "blowout" | "comfortable" | "tight" | "coinflip",
  "key_narrative": "2-3 sentences: how does this game play out?",
  "decisive_factors": ["factor 1", "factor 2", "factor 3"]
}

Rules:
- predicted_score: winner's runs first, loser's runs second (e.g. "5-3")
- tightness: "blowout" = 4+ run margin, "comfortable" = 2-3 runs,
  "tight" = 1 run, "coinflip" = genuinely 50/50
- winner_confidence: 0.50 = true coinflip, 0.60 = slight lean,
  0.70 = clear favorite, 0.80+ = strong favorite
- Focus on HOW the game plays out, not just who wins
- Consider: pitching matchup, lineup strength, recent momentum, park/month
- Be honest about uncertainty — most MLB games are closer to 55/45 than 80/20
"""


_ANALYST_SCHEMA_SIMPLE = """\
Respond with ONLY a JSON object (no markdown, no explanation outside JSON):
{
  "predicted_winner": "home" or "away",
  "predicted_score": "5-3",
  "key_narrative": "3-4 sentences: how does this game play out?",
  "decisive_factors": ["factor 1", "factor 2", "factor 3"]
}

Rules:
- predicted_winner: "home" or "away" — who wins this game
- predicted_score: winner's runs first, loser's runs second (e.g. "5-3", "4-1", "7-2")
- key_narrative: describe HOW the game plays out, not just who wins.
  Cover: starting pitching matchup, when runs score, how bullpens perform.
- decisive_factors: 3 most important factors driving this outcome
- Commit to a specific score. Don't hedge. Your best estimate.
- Be calibrated — most MLB games are decided by 1-3 runs, blowouts are rare but real.
"""


_ANALYST_SCHEMA_OU = """\
Respond with ONLY a JSON object (no markdown, no explanation outside JSON):
{
  "predicted_total": 7.5,
  "scoring_pattern": "low" | "normal" | "high",
  "key_narrative": "3-4 sentences describing the probable match scenario: how does this game unfold, how many runs does each team score and WHY (which matchups, bullpen states, and trends drive that outcome). The predicted_total must follow naturally from this scenario.",
  "decisive_factors": ["factor 1", "factor 2", "factor 3"]
}

Rules:
- predicted_total: the expected total runs that follows from your scenario
- scoring_pattern: "low" = under 7 total, "normal" = 7-10, "high" = 10+
- Build a scenario FIRST, then derive the total from it. Do not start with a number.
- Focus on SCORING VOLUME, not who wins. Both teams' contributions matter equally.
- Consider: starter quality and depth, bullpen momentum and workload,
  offensive environments, recent scoring trends
- Be calibrated: MLB averages ~8.5-9.0 total runs per game
"""


class LLMAnalyst:
    """Pure game analyst — predicts game scenarios without betting context.

    Sees clean stats (no odds, no edge, no zone). Produces a GameScenario
    that betting experts use as additional input.
    """

    def __init__(
        self,
        genome: Genome,
        *,
        provider: str = "openai",
        model: str = "gpt-4o-mini",
        temperature: float = 0.4,
    ):
        self.genome = genome
        self.provider = provider
        self.model = model
        self.temperature = temperature
        self._client = None

    def predict(self, card) -> GameScenario:
        """Analyze a neutral card and produce a game scenario.

        Args:
            card: AnalystCard (neutral, no betting context)
        """
        system_prompt = self._build_system_prompt()
        user_prompt = card.to_prompt()

        for attempt in range(3):
            raw = self._call_llm(system_prompt, user_prompt)
            scenario = self._parse_response(raw)
            if scenario.key_narrative != "parse_error":
                return scenario
            logger.warning(
                f"Analyst parse retry {attempt + 1}/3 for {self.genome.name}"
            )
        return scenario

    def predict_simple(self, card) -> GameScenario:
        """Predict game scenario with simplified output — just winner + score.

        No tightness labels, no winner_confidence. Pure sports prediction.
        Returns GameScenario with tightness derived from predicted score margin.
        """
        system_prompt = self._build_system_prompt_simple()
        user_prompt = card.to_prompt()

        for attempt in range(3):
            raw = self._call_llm(system_prompt, user_prompt)
            scenario = self._parse_response_simple(raw)
            if scenario.key_narrative != "parse_error":
                return scenario
            logger.warning(
                f"Analyst simple parse retry {attempt + 1}/3 for {self.genome.name}"
            )
        return scenario

    def _build_system_prompt_simple(self) -> str:
        """System prompt for simplified analyst — pure sports prediction."""
        g = self.genome
        parts = [
            f"You are {g.name}, an expert MLB game analyst.",
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
            "You are a pure game analyst. You have no knowledge of betting lines, "
            "odds, or market prices. Your only job is to predict the most likely "
            "game outcome and final score based on the statistical profiles of both "
            "teams and their starting pitchers. Commit to a specific score — your "
            "best estimate of how this game ends. Be calibrated — most MLB games "
            "are decided by 1-3 runs, and even the best teams lose 40% of their games."
        )

        parts.append(f"\n## Output Format\n{_ANALYST_SCHEMA_SIMPLE}")

        return "\n".join(parts)

    def _parse_response_simple(self, raw: str) -> GameScenario:
        """Parse simplified analyst response into GameScenario."""
        text = raw.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning(f"Analyst simple parse error: {text[:200]}")
            return GameScenario(
                predicted_winner="home",
                winner_confidence=0.0,
                predicted_score="0-0",
                tightness="N/A",
                key_narrative="parse_error",
                decisive_factors=["parse_error"],
            )

        predicted_winner = data.get("predicted_winner", "home").lower()
        if predicted_winner not in ("home", "away"):
            predicted_winner = "home"

        predicted_score = data.get("predicted_score", "4-3")

        # Derive tightness from score margin
        try:
            parts = predicted_score.replace("-", " ").split()
            margin = abs(int(parts[0]) - int(parts[1]))
        except (ValueError, IndexError):
            margin = 1

        if margin >= 4:
            tightness = "blowout"
        elif margin >= 2:
            tightness = "comfortable"
        elif margin == 1:
            tightness = "tight"
        else:
            tightness = "coinflip"

        return GameScenario(
            predicted_winner=predicted_winner,
            winner_confidence=0.0,  # not asked
            predicted_score=predicted_score,
            tightness=tightness,  # derived from score, not LLM
            key_narrative=data.get("key_narrative", ""),
            decisive_factors=data.get("decisive_factors", []),
        )

    def predict_ou(self, card) -> OUGameScenario:
        """Analyze a neutral O/U card and produce a scoring scenario."""
        system_prompt = self._build_system_prompt_ou()
        user_prompt = card.to_prompt()

        for attempt in range(3):
            raw = self._call_llm(system_prompt, user_prompt)
            scenario = self._parse_response_ou(raw)
            if scenario.key_narrative != "parse_error":
                return scenario
            logger.warning(
                f"OU Analyst parse retry {attempt + 1}/3 for {self.genome.name}"
            )
        return scenario

    def _build_system_prompt_ou(self) -> str:
        g = self.genome
        parts = [
            f"You are {g.name}, an expert MLB scoring analyst.",
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
            "You are a pure scoring analyst. You predict total runs scored in a game. "
            "You have no knowledge of betting lines or odds — only the scoring environment, "
            "pitching matchups, and offensive profiles.\n\n"
            "Your task: describe the MOST PROBABLE MATCH SCENARIO based on the statistics. "
            "How does this game unfold? Which pitching matchups limit or allow runs? "
            "How do bullpen states and offensive trends shape the middle and late innings? "
            "Your predicted_total is a CONSEQUENCE of this scenario — the mathematical "
            "expectation that follows from how you expect the game to play out.\n\n"
            "Be calibrated: MLB averages about 8.5-9.0 total runs per game, but the range "
            "is wide (4-15+). Focus on how many runs each side is likely to generate, not who wins."
        )

        parts.append(f"\n## Output Format\n{_ANALYST_SCHEMA_OU}")

        return "\n".join(parts)

    def _parse_response_ou(self, raw: str) -> OUGameScenario:
        text = raw.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning(f"OU Analyst parse error: {text[:200]}")
            return OUGameScenario(
                predicted_total=8.5,
                scoring_pattern="normal",
                key_narrative="parse_error",
                decisive_factors=["parse_error"],
            )

        predicted_total = float(data.get("predicted_total", 8.5))

        scoring_pattern = data.get("scoring_pattern", "normal").lower()
        if scoring_pattern not in ("low", "normal", "high"):
            scoring_pattern = "normal"

        return OUGameScenario(
            predicted_total=predicted_total,
            scoring_pattern=scoring_pattern,
            key_narrative=data.get("key_narrative", ""),
            decisive_factors=data.get("decisive_factors", []),
        )

    def _build_system_prompt(self) -> str:
        g = self.genome
        parts = [
            f"You are {g.name}, an expert MLB game analyst.",
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
            "You are a pure game analyst. You have no knowledge of betting lines, "
            "odds, or market prices. Your only job is to predict the most likely "
            "game outcome based on the statistical profile of both teams and their "
            "starting pitchers. Be calibrated — most MLB games are decided by 1-3 "
            "runs, and even the best teams lose 40% of their games."
        )

        parts.append(f"\n## Output Format\n{_ANALYST_SCHEMA}")

        return "\n".join(parts)

    def _call_llm(self, system_prompt: str, user_prompt: str) -> str:
        """Call the LLM API with retry on transient errors."""
        return _retry_llm_call(self._call_llm_raw, system_prompt, user_prompt)

    def _call_llm_raw(self, system_prompt: str, user_prompt: str) -> str:
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
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning(f"Analyst parse error: {text[:200]}")
            return GameScenario(
                predicted_winner="home",
                winner_confidence=0.55,
                predicted_score="4-3",
                tightness="tight",
                key_narrative=f"Parse error. Raw: {text[:100]}",
                decisive_factors=["parse_error"],
            )

        winner = data.get("predicted_winner", "home").lower()
        if winner not in ("home", "away"):
            winner = "home"

        confidence = float(data.get("winner_confidence", 0.55))
        confidence = max(0.50, min(0.95, confidence))

        tightness = data.get("tightness", "tight").lower()
        if tightness not in ("blowout", "comfortable", "tight", "coinflip"):
            tightness = "tight"

        return GameScenario(
            predicted_winner=winner,
            winner_confidence=confidence,
            predicted_score=data.get("predicted_score", "4-3"),
            tightness=tightness,
            key_narrative=data.get("key_narrative", ""),
            decisive_factors=data.get("decisive_factors", []),
        )
