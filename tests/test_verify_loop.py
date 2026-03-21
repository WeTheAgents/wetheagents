"""Tests for the iterative refinement loop — task #199."""

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


# Load pipeline_support first (pipeline_parser depends on it)
_pipeline_support = _load_local("wea_cli.pipeline_support", SRC / "wea_cli" / "pipeline_support.py")
# Ensure sub-package is importable under the package namespace too
if "wea_cli" not in sys.modules:
    import types
    _wea_cli_pkg = types.ModuleType("wea_cli")
    _wea_cli_pkg.__path__ = [str(SRC / "wea_cli")]  # type: ignore[assignment]
    sys.modules["wea_cli"] = _wea_cli_pkg
sys.modules["wea_cli"].pipeline_support = _pipeline_support  # type: ignore[assignment]

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# Add scripts dir for pipeline_parser
_SCRIPTS = ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from pipeline_parser import EvaluationResult, aggregate_results  # noqa: E402

from wea_cli.pipeline_support import derive_status  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_schema(name: str) -> dict:
    return json.loads((ROOT / "pipeline" / "verify" / name).read_text(encoding="utf-8"))


def _eval_schema() -> dict:
    return _load_schema("evaluation.schema.json")


def _rr_schema() -> dict:
    return _load_schema("refinement_request.schema.json")


def _rubrics_all_one() -> dict:
    keys = [
        "gaming", "spec_conformance", "scope_violation", "fragility",
        "test_coverage", "dead_code", "error_handling", "documentation",
        "performance_risk", "naming_clarity",
    ]
    return {k: {"score": 1.0, "note": "ok"} for k in keys}


def _valid_eval(verdict: str = "APPROVED", iteration: int | None = None) -> dict:
    payload: dict = {
        "station": "verify",
        "agent_id": "TestAgent@test",
        "verdict": verdict,
        "summary": "looks good",
        "overall_score": 1.0,
        "blocking_comments": [],
        "rubrics": _rubrics_all_one(),
    }
    if iteration is not None:
        payload["iteration"] = iteration
    return payload


def _make_eval_result(verdict: str, iteration: int | None = None) -> EvaluationResult:
    payload = _valid_eval(verdict=verdict, iteration=iteration)
    return EvaluationResult(
        station="verify",
        agent_id="TestAgent@test",
        verdict=verdict,
        format="json",
        payload=payload,
        raw_comment="",
    )


# ---------------------------------------------------------------------------
# TC-1: evaluation with iteration=2 validates — no ValidationError
# ---------------------------------------------------------------------------

def test_tc1_eval_iteration_valid():
    validate(instance=_valid_eval("APPROVED", iteration=2), schema=_eval_schema())


# ---------------------------------------------------------------------------
# TC-2: evaluation with iteration=0 — ValidationError (minimum: 1)
# ---------------------------------------------------------------------------

def test_tc2_eval_iteration_zero_rejected():
    with pytest.raises(ValidationError):
        validate(instance=_valid_eval("APPROVED", iteration=0), schema=_eval_schema())


# ---------------------------------------------------------------------------
# TC-3: evaluation without iteration key — no ValidationError (optional field)
# ---------------------------------------------------------------------------

def test_tc3_eval_no_iteration_valid():
    validate(instance=_valid_eval("APPROVED"), schema=_eval_schema())


# ---------------------------------------------------------------------------
# TC-4: valid refinement_request — no ValidationError
# ---------------------------------------------------------------------------

def test_tc4_valid_refinement_request():
    payload = {
        "station": "verify",
        "type": "refinement_request",
        "issue_number": 199,
        "iteration": 1,
        "blocking_comments": ["Fix X"],
        "reviewer_agent_id": "Claude-8@claude",
    }
    validate(instance=payload, schema=_rr_schema())


# ---------------------------------------------------------------------------
# TC-5: refinement_request with blocking_comments=[] — ValidationError (minItems: 1)
# ---------------------------------------------------------------------------

def test_tc5_rr_empty_blocking_comments():
    payload = {
        "station": "verify",
        "type": "refinement_request",
        "issue_number": 199,
        "iteration": 1,
        "blocking_comments": [],
        "reviewer_agent_id": "Claude-8@claude",
    }
    with pytest.raises(ValidationError):
        validate(instance=payload, schema=_rr_schema())


# ---------------------------------------------------------------------------
# TC-6: refinement_request missing blocking_comments — ValidationError
# ---------------------------------------------------------------------------

def test_tc6_rr_missing_blocking_comments():
    payload = {
        "station": "verify",
        "type": "refinement_request",
        "issue_number": 199,
        "iteration": 1,
        "reviewer_agent_id": "Claude-8@claude",
    }
    with pytest.raises(ValidationError):
        validate(instance=payload, schema=_rr_schema())


# ---------------------------------------------------------------------------
# TC-7: aggregate_results — latest iteration wins
#   iter=1 CR, iter=2 APPR, iter=2 APPR → APPROVED, iteration=2
# ---------------------------------------------------------------------------

def test_tc7_aggregation_latest_iteration_wins():
    evals = [
        _make_eval_result("CHANGES_REQUESTED", iteration=1),
        _make_eval_result("APPROVED", iteration=2),
        _make_eval_result("APPROVED", iteration=2),
    ]
    result = aggregate_results("verify", evals)
    assert result.verdict == "APPROVED"
    assert result.iteration == 2


# ---------------------------------------------------------------------------
# TC-8: aggregate_results — ESCALATE at max iterations
#   iter=3 CR (low score), iter=3 CR (low score) → ESCALATE when verify_max_iterations=3
# ---------------------------------------------------------------------------

def _make_low_eval_result(iteration: int) -> EvaluationResult:
    """Make an eval result with rubric scores=0.0 to force CHANGES_REQUESTED by score."""
    low_rubrics = {k: {"score": 0.0, "note": "bad"} for k in _rubrics_all_one()}
    payload = _valid_eval("CHANGES_REQUESTED", iteration=iteration)
    payload["rubrics"] = low_rubrics
    payload["overall_score"] = 0.0
    return EvaluationResult(
        station="verify", agent_id="T@t", verdict="CHANGES_REQUESTED",
        format="json", payload=payload, raw_comment="",
    )


def test_tc8_aggregation_escalate():
    evals = [
        _make_low_eval_result(iteration=3),
        _make_low_eval_result(iteration=3),
    ]
    result = aggregate_results("verify", evals, config={"verify_max_iterations": 3})
    assert result.verdict == "ESCALATE"
    assert result.iteration == 3


# ---------------------------------------------------------------------------
# TC-9: aggregate_results — CHANGES_REQUESTED below threshold
#   iter=2 CR, iter=2 CR with max=3 → CHANGES_REQUESTED
# ---------------------------------------------------------------------------

def test_tc9_aggregation_changes_requested_below_threshold():
    evals = [
        _make_eval_result("CHANGES_REQUESTED", iteration=2),
        _make_eval_result("CHANGES_REQUESTED", iteration=2),
    ]
    result = aggregate_results("verify", evals, config={"verify_max_iterations": 3})
    # Score-based: rubrics all 1.0 so avg=1.0 → APPROVED regardless of verdict field
    # Need low rubric scores to force CHANGES_REQUESTED
    low_rubrics = {k: {"score": 0.0, "note": "bad"} for k in _rubrics_all_one()}
    low_evals = []
    for _ in range(2):
        payload = _valid_eval("CHANGES_REQUESTED", iteration=2)
        payload["rubrics"] = low_rubrics
        payload["overall_score"] = 0.0
        low_evals.append(EvaluationResult(
            station="verify", agent_id="T@t", verdict="CHANGES_REQUESTED",
            format="json", payload=payload, raw_comment="",
        ))
    result = aggregate_results("verify", low_evals, config={"verify_max_iterations": 3})
    assert result.verdict == "CHANGES_REQUESTED"
    assert result.iteration == 2


# ---------------------------------------------------------------------------
# TC-10: backward compat — no iteration field defaults to 1
# ---------------------------------------------------------------------------

def test_tc10_backward_compat_no_iteration():
    evals = [
        _make_eval_result("APPROVED", iteration=None),
        _make_eval_result("APPROVED", iteration=None),
    ]
    result = aggregate_results("verify", evals)
    assert result.verdict == "APPROVED"
    assert result.iteration == 1


# ---------------------------------------------------------------------------
# TC-11: mixed latest group — score >= 0.85 → APPROVED even at max_iter
#   iter=3 APPR (score=0.90), iter=3 CR (score=0.90, high rubrics) → APPROVED
#   Score-based logic overrides the CHANGES_REQUESTED verdict field.
# ---------------------------------------------------------------------------

def test_tc11_mixed_latest_approved_wins():
    # Both evals have high scores (0.90); one has CHANGES_REQUESTED verdict.
    # avg = (0.90 + 0.90) / 2 = 0.90 >= 0.85 → APPROVED by score, not ESCALATE.
    high_rubrics = {k: {"score": 0.9, "note": "good"} for k in _rubrics_all_one()}
    approved_payload = _valid_eval("APPROVED", iteration=3)
    approved_payload["rubrics"] = high_rubrics
    approved_payload["overall_score"] = 0.9

    cr_payload = _valid_eval("CHANGES_REQUESTED", iteration=3)
    cr_payload["rubrics"] = high_rubrics
    cr_payload["overall_score"] = 0.9

    evals = [
        EvaluationResult(station="verify", agent_id="A@a", verdict="APPROVED",
                         format="json", payload=approved_payload, raw_comment=""),
        EvaluationResult(station="verify", agent_id="B@b", verdict="CHANGES_REQUESTED",
                         format="json", payload=cr_payload, raw_comment=""),
    ]
    result = aggregate_results("verify", evals, config={"verify_max_iterations": 3})
    assert result.verdict == "APPROVED"
    assert result.iteration == 3


# ---------------------------------------------------------------------------
# TC-12: derive_status — awaiting_review (pure function, no network)
# ---------------------------------------------------------------------------

def test_tc12_derive_status_awaiting_review():
    evals = [{"iteration": 1, "verdict": "CHANGES_REQUESTED", "station": "verify"}]
    status = derive_status(evals, [], verify_max_iterations=3)
    assert status == "awaiting_review"


# ---------------------------------------------------------------------------
# TC-13: derive_status — awaiting_fix when refinement_request posted
# ---------------------------------------------------------------------------

def test_tc13_derive_status_awaiting_fix():
    evals = [{"iteration": 1, "verdict": "CHANGES_REQUESTED", "station": "verify"}]
    rrs = [{"iteration": 1, "type": "refinement_request", "station": "verify"}]
    status = derive_status(evals, rrs, verify_max_iterations=3)
    assert status == "awaiting_fix"


# ---------------------------------------------------------------------------
# TC-14: derive_status — mixed group at max_iter, avg >= 0.85 → APPROVED
#   iter=3 CR (score=0.90) + iter=3 APPR (score=0.90) → APPROVED by score
#   Score-based logic agrees with aggregate_results on mixed-verdict groups.
# ---------------------------------------------------------------------------

def test_tc14_derive_status_mixed_not_all_approved():
    evals = [
        {"iteration": 3, "verdict": "CHANGES_REQUESTED", "station": "verify",
         "overall_score": 0.9},
        {"iteration": 3, "verdict": "APPROVED", "station": "verify",
         "overall_score": 0.9},
    ]
    # avg = (0.90 + 0.90) / 2 = 0.90 >= 0.85 → APPROVED (not ESCALATE)
    status = derive_status(evals, [], verify_max_iterations=3)
    assert status == "APPROVED"


# ---------------------------------------------------------------------------
# TC-15: derive_status — no evaluations → awaiting_review
# ---------------------------------------------------------------------------

def test_tc15_derive_status_no_evals():
    status = derive_status([], [], verify_max_iterations=3)
    assert status == "awaiting_review"


# ---------------------------------------------------------------------------
# TC-16: derive_status — all APPROVED at max_iter → APPROVED (not ESCALATE)
# ---------------------------------------------------------------------------

def test_tc16_derive_status_approved_at_max():
    evals = [
        {"iteration": 3, "verdict": "APPROVED", "station": "verify"},
        {"iteration": 3, "verdict": "APPROVED", "station": "verify"},
    ]
    status = derive_status(evals, [], verify_max_iterations=3)
    assert status == "APPROVED"
