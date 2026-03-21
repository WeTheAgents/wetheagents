"""Tests for the Normalized Change a(c) metric — SWE-CI integration."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from jsonschema import ValidationError, validate

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


# Force-load local modules to avoid editable-install collision with other worktrees.
def _load_local(module_name: str, path: Path):  # type: ignore[return]
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec and spec.loader, f"Cannot load {path}"
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


_pipeline_support = _load_local("wea_cli.pipeline_support", SRC / "wea_cli" / "pipeline_support.py")
if "wea_cli" not in sys.modules:
    import types
    _wea_cli_pkg = types.ModuleType("wea_cli")
    _wea_cli_pkg.__path__ = [str(SRC / "wea_cli")]  # type: ignore[assignment]
    sys.modules["wea_cli"] = _wea_cli_pkg
sys.modules["wea_cli"].pipeline_support = _pipeline_support  # type: ignore[assignment]

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

_SCRIPTS = ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from pipeline_parser import (  # noqa: E402
    VERIFY_WEIGHTS,
    EvaluationResult,
    aggregate_results,
)

from wea_cli.pipeline_support import compute_normalized_change  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_schema() -> dict:
    return json.loads((ROOT / "pipeline" / "verify" / "evaluation.schema.json").read_text(encoding="utf-8"))


def _all_rubrics(score: float) -> dict:
    return {k: {"score": score, "note": "test"} for k in VERIFY_WEIGHTS}


def _make_eval_with_ci_delta(
    score: float, a_c: float,
    passed_before: int = 100, failed_before: int = 5,
    passed_after: int = 105, failed_after: int = 0,
    iteration: int = 1,
) -> EvaluationResult:
    payload = {
        "station": "verify",
        "agent_id": "test-agent@test",
        "verdict": "APPROVED",
        "summary": "test",
        "overall_score": score,
        "blocking_comments": [],
        "rubrics": _all_rubrics(score),
        "iteration": iteration,
        "ci_delta": {
            "passed_before": passed_before,
            "failed_before": failed_before,
            "passed_after": passed_after,
            "failed_after": failed_after,
            "a_c": a_c,
        },
    }
    return EvaluationResult("verify", "test-agent@test", "APPROVED", "json", payload, "")


def _make_eval_no_ci_delta(score: float, iteration: int = 1) -> EvaluationResult:
    payload = {
        "station": "verify",
        "agent_id": "test-agent@test",
        "verdict": "APPROVED",
        "summary": "test",
        "overall_score": score,
        "blocking_comments": [],
        "rubrics": _all_rubrics(score),
        "iteration": iteration,
    }
    return EvaluationResult("verify", "test-agent@test", "APPROVED", "json", payload, "")


# ---------------------------------------------------------------------------
# compute_normalized_change — unit tests
# ---------------------------------------------------------------------------

class TestComputeNormalizedChange:
    def test_all_fixed_no_regressions(self):
        # 3 failing → 0 failing: delta=+3, a(c)= 3/3 = 1.0
        assert compute_normalized_change(100, 3, 103, 0) == 1.0

    def test_partial_fix(self):
        # 10 failing, fixed 5: delta=+5, a(c)= 5/10 = 0.5
        assert compute_normalized_change(90, 10, 95, 5) == 0.5

    def test_no_change(self):
        assert compute_normalized_change(100, 5, 100, 5) == 0.0

    def test_pure_regression(self):
        # 100 passing → 0 passing: delta=-100, a(c)= -100/100 = -1.0
        assert compute_normalized_change(100, 0, 0, 100) == -1.0

    def test_partial_regression(self):
        # 100 passing, 10 broke: delta=-10, a(c)= -10/100 = -0.1
        assert compute_normalized_change(100, 0, 90, 10) == pytest.approx(-0.1)

    def test_zero_failing_before_no_improvement(self):
        # 0 failing before, 0 delta → denominator max(1,0)=1, a(c)=0/1=0.0
        assert compute_normalized_change(100, 0, 100, 0) == 0.0

    def test_zero_passing_before_no_regression(self):
        # 0 passing before, gained 5: delta=+5, a(c)= 5/max(1,10)= 0.5
        assert compute_normalized_change(0, 10, 5, 5) == 0.5

    def test_clamp_positive(self):
        # More tests pass than were failing (new tests added): still capped at 1.0
        assert compute_normalized_change(100, 2, 110, 0) == 1.0

    def test_clamp_negative(self):
        # Edge case: 0 passing before, lost nothing can't go below -1.0
        assert compute_normalized_change(1, 0, 0, 1) == -1.0

    def test_both_zero(self):
        # No tests at all — a(c) = 0.0
        assert compute_normalized_change(0, 0, 0, 0) == 0.0


# ---------------------------------------------------------------------------
# Schema validation — ci_delta field
# ---------------------------------------------------------------------------

class TestSchemaValidation:
    def test_valid_payload_with_ci_delta(self):
        schema = _load_schema()
        payload = {
            "station": "verify",
            "agent_id": "test-agent@test",
            "verdict": "APPROVED",
            "summary": "all good",
            "overall_score": 0.9,
            "blocking_comments": [],
            "rubrics": _all_rubrics(1.0),
            "ci_delta": {
                "passed_before": 142,
                "failed_before": 3,
                "passed_after": 145,
                "failed_after": 0,
                "a_c": 1.0,
            },
        }
        validate(instance=payload, schema=schema)  # must not raise

    def test_valid_payload_without_ci_delta(self):
        """ci_delta is optional — backward compat."""
        schema = _load_schema()
        payload = {
            "station": "verify",
            "agent_id": "test-agent@test",
            "verdict": "APPROVED",
            "summary": "all good",
            "overall_score": 0.9,
            "blocking_comments": [],
            "rubrics": _all_rubrics(1.0),
        }
        validate(instance=payload, schema=schema)  # must not raise

    def test_rejects_a_c_out_of_range_high(self):
        schema = _load_schema()
        payload = {
            "station": "verify",
            "agent_id": "test-agent@test",
            "verdict": "APPROVED",
            "summary": "all good",
            "overall_score": 0.9,
            "blocking_comments": [],
            "rubrics": _all_rubrics(1.0),
            "ci_delta": {
                "passed_before": 100,
                "failed_before": 5,
                "passed_after": 105,
                "failed_after": 0,
                "a_c": 1.5,
            },
        }
        with pytest.raises(ValidationError):
            validate(instance=payload, schema=schema)

    def test_rejects_a_c_out_of_range_low(self):
        schema = _load_schema()
        payload = {
            "station": "verify",
            "agent_id": "test-agent@test",
            "verdict": "APPROVED",
            "summary": "all good",
            "overall_score": 0.9,
            "blocking_comments": [],
            "rubrics": _all_rubrics(1.0),
            "ci_delta": {
                "passed_before": 100,
                "failed_before": 5,
                "passed_after": 50,
                "failed_after": 55,
                "a_c": -1.5,
            },
        }
        with pytest.raises(ValidationError):
            validate(instance=payload, schema=schema)

    def test_rejects_ci_delta_missing_required_field(self):
        schema = _load_schema()
        payload = {
            "station": "verify",
            "agent_id": "test-agent@test",
            "verdict": "APPROVED",
            "summary": "all good",
            "overall_score": 0.9,
            "blocking_comments": [],
            "rubrics": _all_rubrics(1.0),
            "ci_delta": {
                "passed_before": 100,
                "failed_before": 5,
                # missing passed_after, failed_after, a_c
            },
        }
        with pytest.raises(ValidationError):
            validate(instance=payload, schema=schema)

    def test_rejects_negative_test_count(self):
        schema = _load_schema()
        payload = {
            "station": "verify",
            "agent_id": "test-agent@test",
            "verdict": "APPROVED",
            "summary": "all good",
            "overall_score": 0.9,
            "blocking_comments": [],
            "rubrics": _all_rubrics(1.0),
            "ci_delta": {
                "passed_before": -1,
                "failed_before": 5,
                "passed_after": 100,
                "failed_after": 0,
                "a_c": 0.5,
            },
        }
        with pytest.raises(ValidationError):
            validate(instance=payload, schema=schema)


# ---------------------------------------------------------------------------
# Aggregation — a(c) extraction
# ---------------------------------------------------------------------------

class TestAggregationWithAC:
    def test_a_c_averaged_across_reviewers(self):
        evals = [
            _make_eval_with_ci_delta(0.9, a_c=1.0),
            _make_eval_with_ci_delta(0.9, a_c=0.5),
        ]
        result = aggregate_results("verify", evals)
        assert result.verdict == "APPROVED"
        assert result.a_c == pytest.approx(0.75)

    def test_a_c_none_when_no_ci_delta(self):
        evals = [
            _make_eval_no_ci_delta(0.9),
            _make_eval_no_ci_delta(0.9),
        ]
        result = aggregate_results("verify", evals)
        assert result.verdict == "APPROVED"
        assert result.a_c is None

    def test_a_c_from_partial_ci_delta(self):
        """Only one reviewer has ci_delta — still extract it."""
        evals = [
            _make_eval_with_ci_delta(0.9, a_c=0.8),
            _make_eval_no_ci_delta(0.9),
        ]
        result = aggregate_results("verify", evals)
        assert result.a_c == pytest.approx(0.8)

    def test_a_c_uses_latest_iteration_only(self):
        evals = [
            _make_eval_with_ci_delta(0.5, a_c=-0.5, iteration=1),  # old iteration
            _make_eval_with_ci_delta(0.9, a_c=1.0, iteration=2),   # latest
        ]
        result = aggregate_results("verify", evals)
        assert result.a_c == pytest.approx(1.0)
        assert result.iteration == 2

    def test_a_c_none_for_non_verify_stages(self):
        eval_ = EvaluationResult("negativa", "a@a", "PROCEED", "json",
                                 {"station": "negativa", "verdict": "PROCEED", "summary": "ok"}, "")
        result = aggregate_results("negativa", [eval_])
        assert result.a_c is None

    def test_negative_a_c_propagates(self):
        evals = [
            _make_eval_with_ci_delta(0.3, a_c=-0.5),
            _make_eval_with_ci_delta(0.3, a_c=-0.3),
        ]
        result = aggregate_results("verify", evals)
        assert result.a_c == pytest.approx(-0.4)
