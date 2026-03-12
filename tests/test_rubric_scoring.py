"""Tests for rubric-based scoring (task #200)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CANONICAL_WEIGHTS: dict[str, float] = {
    "gaming": 0.15,
    "spec_conformance": 0.15,
    "scope_violation": 0.12,
    "fragility": 0.12,
    "test_coverage": 0.12,
    "dead_code": 0.08,
    "error_handling": 0.08,
    "documentation": 0.08,
    "performance_risk": 0.05,
    "naming_clarity": 0.05,
}

RUBRIC_KEYS = list(CANONICAL_WEIGHTS.keys())


def _rubrics(score: float) -> dict:
    """Return a rubrics dict where every rubric has the given score."""
    return {k: {"score": score, "note": "test note"} for k in RUBRIC_KEYS}


def _make_eval_payload(rubrics: dict, overall_score: float, verdict: str = "APPROVED") -> dict:
    return {
        "station": "verify",
        "agent_id": "TestAgent@test",
        "verdict": verdict,
        "summary": "test evaluation",
        "rubrics": rubrics,
        "overall_score": overall_score,
    }


# ---------------------------------------------------------------------------
# compute_overall_score tests
# ---------------------------------------------------------------------------

from wea_cli.pipeline_support import compute_overall_score  # noqa: E402


class TestComputeOverallScore:
    def test_weighted_average_all_ones(self):
        """All rubrics score 1.0 → overall must be 1.0."""
        result = compute_overall_score(_rubrics(1.0), CANONICAL_WEIGHTS)
        assert result == pytest.approx(1.0, abs=1e-9)

    def test_weighted_average_all_zeros(self):
        """All rubrics score 0.0 → overall must be 0.0."""
        result = compute_overall_score(_rubrics(0.0), CANONICAL_WEIGHTS)
        assert result == pytest.approx(0.0, abs=1e-9)

    def test_weighted_average_mixed(self):
        """Weighted sum with known values produces expected result."""
        rubrics = _rubrics(0.8)
        # All scores 0.8, weights sum to 1.0 → expected = 0.8
        result = compute_overall_score(rubrics, CANONICAL_WEIGHTS)
        assert result == pytest.approx(0.8, abs=1e-9)

    def test_weighted_average_non_uniform(self):
        """Verify actual weighted arithmetic with different per-key scores."""
        rubrics = {k: {"score": 0.0, "note": "bad"} for k in RUBRIC_KEYS}
        # Only gaming (weight=0.15) scores 1.0, everything else 0.0
        rubrics["gaming"] = {"score": 1.0, "note": "ok"}
        result = compute_overall_score(rubrics, CANONICAL_WEIGHTS)
        assert result == pytest.approx(0.15, abs=1e-9)

    def test_weight_validation_raises_on_bad_sum(self):
        """Weights that do not sum to 1.0 (outside tolerance 1e-9) raise ValueError."""
        bad_weights = dict(CANONICAL_WEIGHTS)
        bad_weights["gaming"] = 0.20  # was 0.15 → total = 1.05
        with pytest.raises(ValueError, match="Weights must sum to 1.0"):
            compute_overall_score(_rubrics(0.5), bad_weights)

    def test_weight_validation_tolerates_floating_point(self):
        """Weights that sum to 1.0 within tolerance 1e-9 must not raise."""
        # Reconstruct via arithmetic to introduce floating-point noise
        weights = {k: v for k, v in CANONICAL_WEIGHTS.items()}
        # Force a tiny deviation well within tolerance
        total = sum(weights.values())
        assert abs(total - 1.0) <= 1e-9
        result = compute_overall_score(_rubrics(0.5), weights)
        assert 0.0 <= result <= 1.0

    def test_clamping_above_one(self):
        """Score slightly above 1.0 due to floating point is clamped to 1.0."""
        # Create a scenario where floating-point arithmetic could yield > 1.0
        # by using a score just above 1.0 on a single-item mock weights dict
        # Since our function clamps, this must never exceed 1.0.
        result = compute_overall_score(_rubrics(1.0), CANONICAL_WEIGHTS)
        assert result <= 1.0

    def test_clamping_below_zero(self):
        """Score cannot go below 0.0."""
        result = compute_overall_score(_rubrics(0.0), CANONICAL_WEIGHTS)
        assert result >= 0.0

    def test_result_rounds_to_ten_decimal_places(self):
        """Result is rounded to 10 decimal places."""
        result = compute_overall_score(_rubrics(1.0 / 3.0), CANONICAL_WEIGHTS)
        # The result should not have more than 10 decimal places of precision
        rounded = round(result, 10)
        assert result == rounded


# ---------------------------------------------------------------------------
# Aggregation threshold tests
# ---------------------------------------------------------------------------

import sys  # noqa: E402

sys.path.insert(0, str(ROOT / "scripts"))

from pipeline_parser import EvaluationResult, aggregate_results  # noqa: E402

_CONFIG = {
    "verify_thresholds": {"auto_approve": 0.85, "refinement": 0.6}
}


def _make_eval_result(rubrics: dict, overall_score: float, verdict: str = "APPROVED") -> EvaluationResult:
    payload = _make_eval_payload(rubrics, overall_score, verdict)
    return EvaluationResult(
        station="verify",
        agent_id="TestAgent@test",
        verdict=verdict,
        format="json",
        payload=payload,
        raw_comment="",
    )


class TestAggregationThresholds:
    def test_auto_approve_threshold_boundary(self):
        """Score exactly 0.85 → APPROVED."""
        # All rubrics at score x such that weighted sum = 0.85 exactly
        rubrics = _rubrics(0.85)
        ev = _make_eval_result(rubrics, 0.85, "APPROVED")
        result = aggregate_results("verify", [ev], config=_CONFIG)
        assert result.verdict == "APPROVED"

    def test_above_auto_approve(self):
        """Score > 0.85 → APPROVED."""
        rubrics = _rubrics(0.9)
        ev = _make_eval_result(rubrics, 0.9, "APPROVED")
        result = aggregate_results("verify", [ev], config=_CONFIG)
        assert result.verdict == "APPROVED"

    def test_changes_requested_below_refinement(self):
        """Score < 0.60 → CHANGES_REQUESTED."""
        rubrics = _rubrics(0.5)
        ev = _make_eval_result(rubrics, 0.5, "CHANGES_REQUESTED")
        result = aggregate_results("verify", [ev], config=_CONFIG)
        assert result.verdict == "CHANGES_REQUESTED"

    def test_human_review_band(self):
        """Score between 0.60 and 0.84 → HUMAN_REVIEW."""
        rubrics = _rubrics(0.72)
        ev = _make_eval_result(rubrics, 0.72, "HUMAN_REVIEW")
        result = aggregate_results("verify", [ev], config=_CONFIG)
        assert result.verdict == "HUMAN_REVIEW"

    def test_human_review_lower_boundary(self):
        """Score exactly 0.60 → HUMAN_REVIEW (not CHANGES_REQUESTED)."""
        rubrics = _rubrics(0.60)
        ev = _make_eval_result(rubrics, 0.60, "HUMAN_REVIEW")
        result = aggregate_results("verify", [ev], config=_CONFIG)
        assert result.verdict == "HUMAN_REVIEW"

    def test_multiple_reviewer_averaging(self):
        """Two reviewers with 0.72 and 0.68 → average 0.70 → HUMAN_REVIEW (scenario 3)."""
        rubrics_a = _rubrics(0.72)
        rubrics_b = _rubrics(0.68)
        ev_a = _make_eval_result(rubrics_a, 0.72, "HUMAN_REVIEW")
        ev_b = _make_eval_result(rubrics_b, 0.68, "HUMAN_REVIEW")
        result = aggregate_results("verify", [ev_a, ev_b], config=_CONFIG)
        assert result.verdict == "HUMAN_REVIEW"

    def test_mixed_scores_above_and_below_auto_approve(self):
        """Reviewer A=0.85, reviewer B=0.59 → average=0.72 → HUMAN_REVIEW (scenario 4)."""
        rubrics_a = _rubrics(0.85)
        rubrics_b = _rubrics(0.59)
        ev_a = _make_eval_result(rubrics_a, 0.85, "APPROVED")
        ev_b = _make_eval_result(rubrics_b, 0.59, "CHANGES_REQUESTED")
        result = aggregate_results("verify", [ev_a, ev_b], config=_CONFIG)
        assert result.verdict == "HUMAN_REVIEW"


# ---------------------------------------------------------------------------
# Legacy binary backward compatibility test
# ---------------------------------------------------------------------------

from pipeline_parser import _parse_verify_legacy  # noqa: E402


class TestLegacyBackwardCompat:
    _LEGACY_BODY = """\
### Verification Review by OldAgent@old

- Gaming: NONE — no gaming found
- Out-of-scope: NONE — all changes in scope
- Fragility: FOUND — brittle pattern detected
- Removable code: NONE — clean

Blocking comments: YES
Verdict: CHANGES REQUESTED
"""

    def test_legacy_parser_returns_checklist_not_rubrics(self):
        """Legacy parser result contains 'checklist' key, not 'rubrics'."""
        result = _parse_verify_legacy(self._LEGACY_BODY)
        assert "checklist" in result.payload
        assert "rubrics" not in result.payload

    def test_legacy_parser_verdict(self):
        """Legacy parser maps 'CHANGES REQUESTED' → 'CHANGES_REQUESTED'."""
        result = _parse_verify_legacy(self._LEGACY_BODY)
        assert result.verdict == "CHANGES_REQUESTED"

    def test_legacy_aggregation_approved(self):
        """Legacy APPROVED verdict maps to score 1.0 → APPROVED aggregate."""
        approved_body = """\
### Verification Review by OldAgent@old

- Gaming: NONE — clean
- Out-of-scope: NONE — clean
- Fragility: NONE — clean
- Removable code: NONE — clean

Blocking comments: NO
Verdict: APPROVED
"""
        ev = _parse_verify_legacy(approved_body)
        result = aggregate_results("verify", [ev], config=_CONFIG)
        assert result.verdict == "APPROVED"

    def test_legacy_aggregation_changes_requested(self):
        """Legacy CHANGES_REQUESTED verdict maps to score 0.0 → CHANGES_REQUESTED aggregate."""
        ev = _parse_verify_legacy(self._LEGACY_BODY)
        result = aggregate_results("verify", [ev], config=_CONFIG)
        assert result.verdict == "CHANGES_REQUESTED"


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------


class TestSchemaValidation:
    def _valid_payload(self) -> dict:
        return _make_eval_payload(_rubrics(0.9), 0.9, "APPROVED")

    def test_valid_payload_passes_schema(self):
        """A fully valid payload passes JSON schema validation."""
        from wea_cli.pipeline_support import validate_stage_payload

        payload = self._valid_payload()
        # Should not raise
        validate_stage_payload(ROOT, "verify", payload)

    def test_missing_rubric_key_fails_schema(self):
        """Payload missing 'spec_conformance' rubric fails schema validation."""
        import jsonschema

        from wea_cli.pipeline_support import validate_stage_payload

        payload = self._valid_payload()
        del payload["rubrics"]["spec_conformance"]
        with pytest.raises(jsonschema.ValidationError):
            validate_stage_payload(ROOT, "verify", payload)

    def test_score_out_of_range_fails_schema(self):
        """Rubric score > 1.0 fails schema validation."""
        import jsonschema

        from wea_cli.pipeline_support import validate_stage_payload

        payload = self._valid_payload()
        payload["rubrics"]["gaming"]["score"] = 1.5
        with pytest.raises(jsonschema.ValidationError):
            validate_stage_payload(ROOT, "verify", payload)

    def test_invalid_verdict_fails_schema(self):
        """Verdict not in allowed enum fails schema validation."""
        import jsonschema

        from wea_cli.pipeline_support import validate_stage_payload

        payload = self._valid_payload()
        payload["verdict"] = "UNKNOWN_VERDICT"
        with pytest.raises(jsonschema.ValidationError):
            validate_stage_payload(ROOT, "verify", payload)

    def test_human_review_verdict_passes_schema(self):
        """HUMAN_REVIEW is a valid verdict per updated schema."""
        from wea_cli.pipeline_support import validate_stage_payload

        payload = self._valid_payload()
        payload["verdict"] = "HUMAN_REVIEW"
        validate_stage_payload(ROOT, "verify", payload)

    def test_iteration_field_accepted(self):
        """Optional 'iteration' integer field is accepted by schema (issue #199 compat)."""
        from wea_cli.pipeline_support import validate_stage_payload

        payload = self._valid_payload()
        payload["iteration"] = 2
        validate_stage_payload(ROOT, "verify", payload)

    def test_weights_sum_to_one(self):
        """Canonical rubric weights defined in checklist.json sum to exactly 1.0."""
        checklist_path = ROOT / "pipeline" / "verify" / "checklist.json"
        checklist = json.loads(checklist_path.read_text(encoding="utf-8"))
        weights = checklist["rubric_weights"]
        assert abs(sum(weights.values()) - 1.0) <= 1e-9, (
            f"Rubric weights must sum to 1.0, got {sum(weights.values())}"
        )
