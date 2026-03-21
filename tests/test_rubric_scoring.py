"""Tests for rubric-based scoring — Task #200."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

import sys

sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from pipeline_parser import (
    VERIFY_LEGACY_WEIGHTS,
    VERIFY_WEIGHTS,
    EvaluationResult,
    _parse_verify_legacy,
    aggregate_results,
)

from wea_cli.pipeline_support import compute_overall_score

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _all_rubrics(score: float) -> dict:
    return {k: {"score": score, "note": "test"} for k in VERIFY_WEIGHTS}


# ---------------------------------------------------------------------------
# compute_overall_score — unit tests
# ---------------------------------------------------------------------------

def test_compute_overall_score_all_ones():
    assert compute_overall_score(_all_rubrics(1.0), VERIFY_WEIGHTS) == 1.0


def test_compute_overall_score_all_zeros():
    assert compute_overall_score(_all_rubrics(0.0), VERIFY_WEIGHTS) == 0.0


def test_compute_overall_score_mixed():
    # Assign gaming=0.5, everything else=1.0
    # gaming weight = 0.15, so score = 0.15*0.5 + 0.85*1.0 = 0.075 + 0.85 = 0.925
    rubrics = _all_rubrics(1.0)
    rubrics["gaming"] = {"score": 0.5, "note": "concern"}
    expected = round(0.15 * 0.5 + (1.0 - 0.15) * 1.0, 10)
    assert compute_overall_score(rubrics, VERIFY_WEIGHTS) == pytest.approx(expected, abs=1e-9)


def test_compute_overall_score_rejects_bad_weights_sum():
    bad_weights = dict(VERIFY_WEIGHTS)
    first_key = next(iter(bad_weights))
    bad_weights[first_key] += 0.1  # now sums to 1.1
    with pytest.raises(ValueError, match="sum"):
        compute_overall_score(_all_rubrics(1.0), bad_weights)


def test_compute_overall_score_rejects_missing_rubric():
    rubrics = _all_rubrics(1.0)
    del rubrics["gaming"]
    with pytest.raises(ValueError):
        compute_overall_score(rubrics, VERIFY_WEIGHTS)


def test_compute_overall_score_rejects_extra_rubric():
    rubrics = _all_rubrics(1.0)
    rubrics["fake_rubric"] = {"score": 0.5, "note": "injection"}
    with pytest.raises(ValueError):
        compute_overall_score(rubrics, VERIFY_WEIGHTS)


def test_compute_overall_score_clamps_result():
    # Even with scores > 1.0 that somehow sneak through, result must be clamped to [0,1]
    rubrics = {k: {"score": 1.0, "note": "t"} for k in VERIFY_WEIGHTS}
    result = compute_overall_score(rubrics, VERIFY_WEIGHTS)
    assert 0.0 <= result <= 1.0


def test_verify_weights_sum_to_one():
    assert abs(sum(VERIFY_WEIGHTS.values()) - 1.0) < 1e-9


def test_verify_legacy_weights_sum_to_one():
    assert abs(sum(VERIFY_LEGACY_WEIGHTS.values()) - 1.0) < 1e-9


# ---------------------------------------------------------------------------
# JSON Schema — validation tests
# ---------------------------------------------------------------------------

def _load_schema() -> dict:
    path = ROOT / "pipeline" / "verify" / "evaluation.schema.json"
    with open(path) as f:
        return json.load(f)


def _valid_payload() -> dict:
    return {
        "station": "verify",
        "agent_id": "test-agent@test",
        "verdict": "APPROVED",
        "summary": "all good",
        "overall_score": 0.9,
        "blocking_comments": [],
        "rubrics": {k: {"score": 1.0, "note": "ok"} for k in VERIFY_WEIGHTS},
    }


def test_schema_rejects_out_of_range_score():
    from jsonschema import ValidationError, validate
    schema = _load_schema()
    payload = _valid_payload()
    payload["rubrics"]["gaming"] = {"score": 1.5, "note": "over range"}
    with pytest.raises(ValidationError):
        validate(instance=payload, schema=schema)


def test_schema_rejects_missing_rubric_key():
    from jsonschema import ValidationError, validate
    schema = _load_schema()
    payload = _valid_payload()
    del payload["rubrics"]["gaming"]
    with pytest.raises(ValidationError):
        validate(instance=payload, schema=schema)


def test_schema_rejects_extra_rubric_key():
    from jsonschema import ValidationError, validate
    schema = _load_schema()
    payload = _valid_payload()
    payload["rubrics"]["fake"] = {"score": 0.5, "note": "injection"}
    with pytest.raises(ValidationError):
        validate(instance=payload, schema=schema)


def test_schema_accepts_human_review_verdict():
    from jsonschema import validate
    schema = _load_schema()
    payload = _valid_payload()
    payload["verdict"] = "HUMAN_REVIEW"
    payload["overall_score"] = 0.7
    validate(instance=payload, schema=schema)  # must not raise


def test_schema_accepts_optional_iteration():
    from jsonschema import validate
    schema = _load_schema()
    payload = _valid_payload()
    payload["iteration"] = 2
    validate(instance=payload, schema=schema)  # must not raise


# ---------------------------------------------------------------------------
# Aggregation — threshold tests
# ---------------------------------------------------------------------------

def _make_eval(score: float, format_: str = "json") -> EvaluationResult:
    rubrics = _all_rubrics(score)
    payload = {
        "station": "verify",
        "agent_id": "test-agent@test",
        "verdict": "APPROVED",
        "summary": "test",
        "overall_score": score,
        "blocking_comments": [],
        "rubrics": rubrics,
    }
    return EvaluationResult("verify", "test-agent@test", "APPROVED", format_, payload, "")


def test_aggregate_verify_approved():
    evals = [_make_eval(0.9), _make_eval(0.9)]
    result = aggregate_results("verify", evals)
    assert result.verdict == "APPROVED"


def test_aggregate_verify_approved_boundary():
    # Exactly 0.85 => APPROVED
    evals = [_make_eval(0.85), _make_eval(0.85)]
    result = aggregate_results("verify", evals)
    assert result.verdict == "APPROVED"


def test_aggregate_verify_human_review():
    evals = [_make_eval(0.7), _make_eval(0.7)]
    result = aggregate_results("verify", evals)
    assert result.verdict == "HUMAN_REVIEW"


def test_aggregate_verify_human_review_boundary():
    # Exactly 0.60 => HUMAN_REVIEW
    evals = [_make_eval(0.60), _make_eval(0.60)]
    result = aggregate_results("verify", evals)
    assert result.verdict == "HUMAN_REVIEW"


def test_aggregate_verify_changes_requested():
    evals = [_make_eval(0.3), _make_eval(0.3)]
    result = aggregate_results("verify", evals)
    assert result.verdict == "CHANGES_REQUESTED"


def test_aggregate_verify_multiple_reviewer_averaging():
    # One high, one low — average should determine verdict
    # 0.9 and 0.5 => avg 0.7 => HUMAN_REVIEW
    evals = [_make_eval(0.9), _make_eval(0.5)]
    result = aggregate_results("verify", evals)
    assert result.verdict == "HUMAN_REVIEW"


def test_aggregate_verify_ignores_submitted_overall_score():
    # Submitted overall_score=0.99 but rubric scores compute to ~0.0 => CHANGES_REQUESTED
    rubrics = _all_rubrics(0.0)
    payload = {
        "station": "verify",
        "agent_id": "test-agent@test",
        "verdict": "APPROVED",
        "summary": "gaming attempt",
        "overall_score": 0.99,  # fraudulent
        "blocking_comments": [],
        "rubrics": rubrics,
    }
    eval_ = EvaluationResult("verify", "test-agent@test", "APPROVED", "json", payload, "")
    result = aggregate_results("verify", [eval_, eval_])
    assert result.verdict == "CHANGES_REQUESTED"


# ---------------------------------------------------------------------------
# Legacy binary backward compatibility
# ---------------------------------------------------------------------------

def test_legacy_parser_unchanged():
    body = (
        "### Verification Review by test-agent@test\n\n"
        "- Gaming: NONE - no gaming found\n"
        "- Out-of-scope: NONE - all changes in scope\n"
        "- Fragility: FOUND - brittle regex\n"
        "- Removable code: NONE - clean\n\n"
        "Blocking comments: YES\n"
        "Verdict: CHANGES REQUESTED"
    )
    result = _parse_verify_legacy(body)
    assert result.verdict == "CHANGES_REQUESTED"
    assert result.format == "legacy"
    assert "checklist" in result.payload


def test_aggregate_verify_legacy_binary_backward_compat():
    # Legacy: FOUND->0.0, NONE->1.0 via VERIFY_LEGACY_WEIGHTS
    # gaming=FOUND(0.0,w=0.40), out_of_scope=NONE(1.0,w=0.20),
    # fragility=FOUND(0.0,w=0.25), removable_code=NONE(1.0,w=0.15)
    # score = 0.0*0.40 + 1.0*0.20 + 0.0*0.25 + 1.0*0.15 = 0.35 => CHANGES_REQUESTED
    payload = {
        "station": "verify",
        "agent_id": "test-agent@test",
        "checklist": {
            "gaming":        {"status": "FOUND", "note": "gaming detected"},
            "out_of_scope":  {"status": "NONE",  "note": "in scope"},
            "fragility":     {"status": "FOUND", "note": "brittle"},
            "removable_code": {"status": "NONE", "note": "clean"},
        },
        "blocking_comments": ["legacy blocking"],
        "verdict": "CHANGES_REQUESTED",
        "summary": "legacy review",
    }
    eval_ = EvaluationResult("verify", "test-agent@test", "CHANGES_REQUESTED", "legacy", payload, "")
    result = aggregate_results("verify", [eval_])
    assert result.verdict == "CHANGES_REQUESTED"
