"""Genome evolution engine — retrospective learning from betting outcomes.

Weekly: analyze high-confidence losses → generate anti-patterns.
Monthly: crossbreed lessons between experts.
Half-season: promote strong anti-patterns to principles.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from src.llm_expert import Genome, Verdict

logger = logging.getLogger(__name__)


@dataclass
class ResolvedPick:
    """A pick with its outcome."""

    game_id: str
    date: str
    zone: str
    expert_name: str
    verdict: Verdict
    outcome: str  # "WIN" | "LOSS" | "PUSH"
    dog_won: bool  # dog won outright
    dog_covered_rl: bool  # dog covered +1.5
    home_margin: int  # home_final - away_final
    card_summary: str  # first 5 lines of feature card for reference


# ── Retrospective prompt ─────────────────────────────────────────────────

_RETRO_SYSTEM = """\
You are an MLB betting analyst reviewing your past picks. Your job is to
identify what you MISSED in losing bets and extract a concise, reusable
lesson that will prevent similar mistakes.

Rules:
- Focus on what the FEATURES showed that you overlooked or misweighed
- Be specific: "pitcher RA momentum was +0.6 (worsening)" not "pitcher was bad"
- Phrase the lesson as a rule: "When X and Y, do Z" or "Never bet when X"
- Keep lessons to 1-2 sentences maximum
- Only generate a lesson if there's a genuine pattern; say "NO_LESSON" if
  the loss was just variance (close game, no clear miss)

Respond with ONLY a JSON object:
{
  "lesson": "the lesson text" or "NO_LESSON",
  "pattern": "what you missed in the features",
  "severity": "high" | "medium" | "low"
}
"""

_RETRO_USER = """\
You picked {action} with confidence {confidence:.2f} on this game:

{card_summary}

Result: {outcome}. Home margin: {margin:+d} (negative = dog won).

Your reasoning at the time: {reasoning}

Key factors you cited: {factors}

What did you miss? What pattern should you watch for next time?
"""


class EvolutionEngine:
    """Evolves expert genomes through retrospective analysis."""

    def __init__(
        self,
        *,
        provider: str = "openai",
        model: str = "gpt-4o-mini",
    ):
        self.provider = provider
        self.model = model
        self._client = None

    def weekly_retrospective(
        self,
        picks: list[ResolvedPick],
        genome: Genome,
        *,
        max_lessons: int = 3,
    ) -> Genome:
        """Analyze recent picks and evolve the genome.

        Focuses on HIGH-CONFIDENCE LOSSES — these have the biggest
        learning signal. Also promotes high-confidence wins to examples.

        Args:
            picks: Resolved picks from this expert
            genome: Current genome to mutate
            max_lessons: Maximum new anti-patterns per retrospective

        Returns:
            Mutated genome (new version)
        """
        losses = [
            p for p in picks
            if p.outcome == "LOSS" and p.verdict.confidence >= 0.6
        ]
        wins = [
            p for p in picks
            if p.outcome == "WIN" and p.verdict.confidence >= 0.7
        ]

        # Sort by confidence descending — analyze highest-confidence losses first
        losses.sort(key=lambda p: p.verdict.confidence, reverse=True)

        new_anti_patterns = []
        for pick in losses[:max_lessons]:
            lesson = self._generate_lesson(pick)
            if lesson and lesson != "NO_LESSON":
                # Avoid duplicate lessons
                if not any(lesson.lower() in ap.lower() or ap.lower() in lesson.lower()
                           for ap in genome.anti_patterns):
                    new_anti_patterns.append(lesson)
                    logger.info(f"New anti-pattern for {genome.name}: {lesson[:80]}...")

        # Promote high-confidence wins to examples
        new_examples = []
        for pick in wins[:2]:  # Max 2 new examples per cycle
            new_examples.append({
                "summary": pick.card_summary[:200],
                "verdict": pick.verdict.action,
                "outcome": pick.outcome,
                "lesson": f"Correct call at {pick.verdict.confidence:.0%} confidence",
            })

        # Prune: keep max 15 anti-patterns (remove oldest if over)
        all_anti = genome.anti_patterns + new_anti_patterns
        if len(all_anti) > 15:
            all_anti = all_anti[-15:]

        # Keep max 10 examples
        all_examples = genome.examples + new_examples
        if len(all_examples) > 10:
            all_examples = all_examples[-10:]

        genome.anti_patterns = all_anti
        genome.examples = all_examples
        genome.version += 1

        logger.info(
            f"Evolution complete: {genome.name} v{genome.version} "
            f"(+{len(new_anti_patterns)} anti-patterns, +{len(new_examples)} examples)"
        )
        return genome

    def monthly_crossbreed(
        self,
        genome_a: Genome,
        genome_b: Genome,
        fitness_a: float,
        fitness_b: float,
    ) -> None:
        """Share best lessons between two experts.

        The better-performing expert's newest anti-pattern gets copied
        to the weaker expert (if not duplicate). Prevents blind spots
        from genome divergence.

        Args:
            fitness_a: ROI or win rate of expert A this month
            fitness_b: ROI or win rate of expert B this month
        """
        if fitness_a >= fitness_b:
            winner, loser = genome_a, genome_b
        else:
            winner, loser = genome_b, genome_a

        # Transfer newest anti-pattern from winner to loser
        if winner.anti_patterns:
            candidate = winner.anti_patterns[-1]
            if not any(candidate.lower() in ap.lower() or ap.lower() in candidate.lower()
                       for ap in loser.anti_patterns):
                loser.anti_patterns.append(candidate)
                loser.version += 1
                logger.info(
                    f"Crossbreed: {winner.name} → {loser.name}: {candidate[:60]}..."
                )
            else:
                logger.info("Crossbreed: no new lessons to transfer (duplicate)")

    def _generate_lesson(self, pick: ResolvedPick) -> str | None:
        """Ask LLM to analyze a losing pick and extract a lesson."""
        user_prompt = _RETRO_USER.format(
            action=pick.verdict.action,
            confidence=pick.verdict.confidence,
            card_summary=pick.card_summary,
            outcome=pick.outcome,
            margin=pick.home_margin,
            reasoning=pick.verdict.reasoning,
            factors=", ".join(pick.verdict.key_factors),
        )

        try:
            raw = self._call_llm(_RETRO_SYSTEM, user_prompt)
            return self._parse_lesson(raw)
        except Exception as e:
            logger.warning(f"Lesson generation failed: {e}")
            return None

    def _parse_lesson(self, raw: str) -> str | None:
        """Parse lesson from LLM response."""
        text = raw.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)

        try:
            data = json.loads(text)
            lesson = data.get("lesson", "NO_LESSON")
            if lesson == "NO_LESSON":
                return None
            return lesson
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse lesson response: {text[:100]}")
            return None

    def _call_llm(self, system_prompt: str, user_prompt: str) -> str:
        """Call LLM API for retrospective analysis."""
        if self.provider == "openai":
            if self._client is None:
                from openai import OpenAI
                self._client = OpenAI()
            response = self._client.chat.completions.create(
                model=self.model,
                temperature=0.4,
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
                max_tokens=256,
                temperature=0.4,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            return response.content[0].text
        else:
            raise ValueError(f"Unknown provider: {self.provider}")


# ── Picks I/O ─────────────────────────────────────────────────────────────


def save_picks(picks: list[dict], date: str, picks_dir: Path) -> Path:
    """Save daily picks to JSON file."""
    picks_dir.mkdir(parents=True, exist_ok=True)
    path = picks_dir / f"{date}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(picks, f, indent=2, ensure_ascii=False)
    logger.info(f"Picks saved: {path}")
    return path


def load_picks(date: str, picks_dir: Path) -> list[dict]:
    """Load daily picks from JSON file."""
    path = picks_dir / f"{date}.json"
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)
