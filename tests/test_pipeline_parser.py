from __future__ import annotations

import argparse
import io
import json
import shutil
import sys
from pathlib import Path

import pytest
from jsonschema import ValidationError

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from scripts.pipeline_parser import (  # noqa: E402
    EvaluationResult,
    aggregate_evaluations,
    aggregate_results,
    parse_evaluation_comment,
    _extract_json_payloads,
    _parse_triage_legacy,
    _parse_impl_legacy,
)
from wea_cli import cli  # noqa: E402
from wea_cli.pipeline_support import normalize_stage, validate_stage_payload  # noqa: E402
def _prepare_repo(root: Path) -> None:
    for stage in ("triage", "negativa", "spec", "impl", "verify"):
        source_dir = ROOT / "pipeline" / stage
        target_dir = root / "pipeline" / stage
        target_dir.mkdir(parents=True, exist_ok=True)
        for name in ("evaluation.schema.json", "checklist.json", "WORKFLOW.md"):
            shutil.copyfile(source_dir / name, target_dir / name)


def _prepare_context_files(root: Path) -> None:
    genome_dir = root / "genomes" / "Codex-2@codex"
    genome_dir.mkdir(parents=True, exist_ok=True)
    (genome_dir / "AGENTS.local.md").write_text(
        "<!-- CONSTITUTION -->\n"
        "Keep it tight.\n\n"
        "## Role\n"
        "Batch executor.\n",
        encoding="utf-8",
    )


def _valid_negativa_payload() -> dict:
    return {
        "station": "negativa",
        "agent_id": "Codex-2@codex",
        "verdict": "PROCEED",
        "summary": "Looks worth doing.",
        "checks": {
            "architecture_compatible": {"status": "PASS", "note": "fits current CLI"},
            "no_fragility": {"status": "PASS", "note": "no new risky deps"},
        },
    }


def test_pipeline_parser_supports_subcommands() -> None:
    parser = cli.build_parser()
    args = parser.parse_args(["pipeline", "submit", "negativa", "--issue", "151", "--dry-run"])

    assert args.command == "pipeline"
    assert args.pipeline_command == "submit"
    assert args.stage == "negativa"
    assert args.issue == 151
    assert args.dry_run is True
    assert args._handler is cli.cmd_pipeline_submit


def test_cmd_pipeline_get_task_renders_issue_and_comments(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    args = argparse.Namespace(issue=151, repo="WeTheAgents/wetheagents")
    monkeypatch.setattr(
        cli,
        "view_issue",
        lambda issue, repo: {"number": issue, "title": "Task title", "body": "Task body"},
    )
    monkeypatch.setattr(
        cli,
        "view_issue_comments",
        lambda issue, repo: {
            "comments": [
                {"body": "First", "createdAt": "2026-03-11T00:00:00Z", "author": {"login": "x"}}
            ]
        },
    )

    rc = cli.cmd_pipeline_get_task(args)

    assert rc == cli.EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["issue"]["number"] == 151
    assert payload["comments"][0]["body"] == "First"


def test_cmd_pipeline_get_context_renders_expected_sections(
    temp_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _prepare_repo(temp_repo)
    _prepare_context_files(temp_repo)
    args = argparse.Namespace(root=str(temp_repo), stage="negativa", agent="Codex-2@codex")

    rc = cli.cmd_pipeline_get_context(args)

    assert rc == cli.EXIT_OK
    out = capsys.readouterr().out
    assert out.index("## Constitution") < out.index("## Genome")
    assert out.index("## Genome") < out.index("## Stage Rules: negativa")
    assert out.index("## Stage Rules: negativa") < out.index("## Stage Checklist: negativa")
    assert out.index("## Stage Checklist: negativa") < out.index("## Stage Schema: negativa")


def test_parse_evaluation_json_valid(temp_repo: Path) -> None:
    _prepare_repo(temp_repo)
    payload = json.dumps(_valid_negativa_payload(), indent=2)
    comment = f"### Negativa Evaluation by Codex-2@codex\n\n```json\n{payload}\n```"

    result = parse_evaluation_comment(comment, station="negativa", root=temp_repo)

    assert result.format == "json"
    assert result.agent_id == "Codex-2@codex"
    assert result.verdict == "PROCEED"
    assert result.payload["checks"]["architecture_compatible"]["status"] == "PASS"
    assert result.checks["architecture_compatible"]["status"] == "PASS"
    assert result.reasoning == "Looks worth doing."


def test_release_stage_removed_from_supported_stage_set() -> None:
    with pytest.raises(ValueError, match="Unknown pipeline stage"):
        normalize_stage("release")


def test_parse_evaluation_json_invalid_missing_verdict(temp_repo: Path) -> None:
    _prepare_repo(temp_repo)
    payload = _valid_negativa_payload()
    del payload["verdict"]
    comment = f"```json\n{json.dumps(payload, indent=2)}\n```"

    with pytest.raises(ValidationError, match="verdict"):
        parse_evaluation_comment(comment, station="negativa", root=temp_repo)


def test_parse_evaluation_json_invalid_extra_check_key(temp_repo: Path) -> None:
    _prepare_repo(temp_repo)
    payload = _valid_negativa_payload()
    payload["checks"]["bonus"] = {"status": "PASS", "note": "should fail"}
    comment = f"```json\n{json.dumps(payload, indent=2)}\n```"

    with pytest.raises(ValidationError, match="bonus"):
        parse_evaluation_comment(comment, station="negativa", root=temp_repo)


def test_parse_evaluation_json_multiple_blocks_rejected(temp_repo: Path) -> None:
    _prepare_repo(temp_repo)
    payload = json.dumps(_valid_negativa_payload(), indent=2)
    comment = (
        f"```json\n{payload}\n```\n\n"
        "text\n\n"
        f"```json\n{payload}\n```"
    )

    with pytest.raises(ValueError, match="Exactly one JSON evaluation block"):
        parse_evaluation_comment(comment, station="negativa", root=temp_repo)


def test_parse_evaluation_legacy_negativa(temp_repo: Path) -> None:
    _prepare_repo(temp_repo)
    comment = """### Via Negativa Evaluation by Codex-2@codex

1. Architecture compatible: PASS - fits design
2. No fragility: PASS - no new risk

Verdict: PROCEED (item #0 - looks good)
"""

    result = parse_evaluation_comment(comment, station="negativa", root=temp_repo)

    assert result.format == "legacy"
    assert result.agent_id == "Codex-2@codex"
    assert result.verdict == "PROCEED"


def test_parse_evaluation_legacy_spec(temp_repo: Path) -> None:
    _prepare_repo(temp_repo)
    comment = """### Spec Review by Codex-2@codex

Red Team result: NO GAMING FOUND
Approval: APPROVED
- none
"""

    result = parse_evaluation_comment(comment, station="spec", root=temp_repo)

    assert result.format == "legacy"
    assert result.agent_id == "Codex-2@codex"
    assert result.verdict == "APPROVED"
    assert result.payload["red_team_result"] == "NO_GAMING_FOUND"


def test_parse_evaluation_legacy_verify(temp_repo: Path) -> None:
    _prepare_repo(temp_repo)
    comment = """### Verification Review by Codex-2@codex

- Gaming: NONE - nothing exploitable
- Out-of-scope: NONE - scope respected
- Fragility: NONE - no brittle changes
- Removable code: NONE - every line is needed

Blocking comments: NO
Verdict: APPROVED
"""

    result = parse_evaluation_comment(comment, station="verify", root=temp_repo)

    assert result.format == "legacy"
    assert result.agent_id == "Codex-2@codex"
    assert result.verdict == "APPROVED"
    assert result.payload["checklist"]["gaming"]["status"] == "NONE"


def test_cmd_pipeline_submit_valid_dry_run(
    temp_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _prepare_repo(temp_repo)
    monkeypatch.delenv("WEA_AGENT", raising=False)
    monkeypatch.setattr(cli, "resolve_agent", lambda explicit=None: None)
    args = argparse.Namespace(
        root=str(temp_repo),
        stage="negativa",
        issue=151,
        agent=None,
        dry_run=True,
        repo="WeTheAgents/wetheagents",
    )
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(_valid_negativa_payload())))

    rc = cli.cmd_pipeline_submit(args)

    assert rc == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "### Negativa Evaluation by Codex-2@codex" in out
    assert "\"verdict\": \"PROCEED\"" in out


def test_cmd_pipeline_submit_invalid_reports_specific_error(
    temp_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _prepare_repo(temp_repo)
    monkeypatch.delenv("WEA_AGENT", raising=False)
    monkeypatch.setattr(cli, "resolve_agent", lambda explicit=None: None)
    payload = _valid_negativa_payload()
    del payload["verdict"]
    args = argparse.Namespace(
        root=str(temp_repo),
        stage="negativa",
        issue=151,
        agent=None,
        dry_run=True,
        repo="WeTheAgents/wetheagents",
    )
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))

    rc = cli.cmd_pipeline_submit(args)

    assert rc == cli.EXIT_DOMAIN_ERROR
    assert "verdict" in capsys.readouterr().out


def test_cmd_pipeline_submit_station_mismatch_rejected(
    temp_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _prepare_repo(temp_repo)
    monkeypatch.delenv("WEA_AGENT", raising=False)
    monkeypatch.setattr(cli, "resolve_agent", lambda explicit=None: None)
    payload = _valid_negativa_payload()
    payload["station"] = "spec"
    args = argparse.Namespace(
        root=str(temp_repo),
        stage="negativa",
        issue=151,
        agent=None,
        dry_run=True,
        repo="WeTheAgents/wetheagents",
    )
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))

    rc = cli.cmd_pipeline_submit(args)

    assert rc == cli.EXIT_DOMAIN_ERROR
    out = capsys.readouterr().out
    assert "station mismatch" in out
    assert "spec" in out
    assert "negativa" in out


def test_cmd_pipeline_submit_explicit_agent_overrides_payload_agent(
    temp_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _prepare_repo(temp_repo)
    payload = _valid_negativa_payload()
    payload["agent_id"] = "stale-agent@old"
    args = argparse.Namespace(
        root=str(temp_repo),
        stage="negativa",
        issue=151,
        agent="Codex-2@codex",
        dry_run=True,
        repo="WeTheAgents/wetheagents",
    )
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))

    rc = cli.cmd_pipeline_submit(args)

    assert rc == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "### Negativa Evaluation by Codex-2@codex" in out
    assert "\"agent_id\": \"Codex-2@codex\"" in out


def test_cmd_pipeline_submit_explicit_agent_fills_blank_payload_agent(
    temp_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _prepare_repo(temp_repo)
    payload = _valid_negativa_payload()
    payload["agent_id"] = "   "
    args = argparse.Namespace(
        root=str(temp_repo),
        stage="negativa",
        issue=151,
        agent="Codex-2@codex",
        dry_run=True,
        repo="WeTheAgents/wetheagents",
    )
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))

    rc = cli.cmd_pipeline_submit(args)

    assert rc == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "### Negativa Evaluation by Codex-2@codex" in out
    assert "\"agent_id\": \"Codex-2@codex\"" in out


def test_validate_triage_no_go_does_not_require_route(temp_repo: Path) -> None:
    _prepare_repo(temp_repo)
    payload = {
        "station": "triage",
        "agent_id": "Codex-2@codex",
        "vote": "NO_GO",
        "summary": "Stop here.",
    }

    assert validate_stage_payload(temp_repo, "triage", payload) == payload


def test_validate_impl_requires_ci(temp_repo: Path) -> None:
    _prepare_repo(temp_repo)
    payload = {
        "station": "impl",
        "agent_id": "Codex-2@codex",
        "verdict": "WIN",
        "summary": "Ship it.",
        "artifacts": {
            "branch": "agent/Codex-2/151-pipeline",
            "pr_url": "https://example.invalid/pr/151",
        },
    }

    with pytest.raises(ValidationError, match="ci"):
        validate_stage_payload(temp_repo, "impl", payload)


def test_aggregate_results_negativa_kill_wins(temp_repo: Path) -> None:
    _prepare_repo(temp_repo)
    proceed = parse_evaluation_comment(
        f"```json\n{json.dumps(_valid_negativa_payload(), indent=2)}\n```",
        station="negativa",
        root=temp_repo,
    )
    kill_payload = _valid_negativa_payload()
    kill_payload["verdict"] = "KILL"
    kill = parse_evaluation_comment(
        f"```json\n{json.dumps(kill_payload, indent=2)}\n```",
        station="negativa",
        root=temp_repo,
    )

    aggregate = aggregate_results("negativa", [proceed, kill])

    assert aggregate.verdict == "KILL"


def test_aggregate_evaluations_backward_compatible_kwargs(temp_repo: Path) -> None:
    _prepare_repo(temp_repo)
    proceed = parse_evaluation_comment(
        f"```json\n{json.dumps(_valid_negativa_payload(), indent=2)}\n```",
        station="negativa",
        root=temp_repo,
    )

    aggregate = aggregate_evaluations(
        "negativa",
        [proceed],
        evaluators_required=1,
        kill_on_any_failure=True,
    )

    assert aggregate.verdict == "PROCEED"


def test_aggregate_results_spec_uses_approval(temp_repo: Path) -> None:
    _prepare_repo(temp_repo)
    approved = parse_evaluation_comment(
        """```json
{
  "station": "spec",
  "agent_id": "Codex-2@codex",
  "red_team_result": "NO_GAMING_FOUND",
  "approval": "APPROVED",
  "notes": "Looks good."
}
```""",
        station="spec",
        root=temp_repo,
    )
    rejected = parse_evaluation_comment(
        """```json
{
  "station": "spec",
  "agent_id": "Cursor-1@cursor",
  "red_team_result": "GAMING_FOUND",
  "approval": "REJECTED",
  "notes": "Blocked."
}
```""",
        station="spec",
        root=temp_repo,
    )

    assert approved.verdict == "APPROVED"
    assert rejected.verdict == "REJECTED"
    assert aggregate_results("spec", [approved, rejected]).verdict == "REJECTED"


def test_aggregate_results_verify_requires_unanimous_approval(temp_repo: Path) -> None:
    _prepare_repo(temp_repo)
    approved = parse_evaluation_comment(
        """```json
{
  "station": "verify",
  "agent_id": "Codex-2@codex",
  "verdict": "APPROVED",
  "summary": "Clean.",
  "blocking_comments": [],
  "checklist": {
    "gaming": {"status": "NONE", "note": "ok"},
    "out_of_scope": {"status": "NONE", "note": "ok"},
    "fragility": {"status": "NONE", "note": "ok"},
    "removable_code": {"status": "NONE", "note": "ok"}
  }
}
```""",
        station="verify",
        root=temp_repo,
    )
    changes = parse_evaluation_comment(
        """```json
{
  "station": "verify",
  "agent_id": "Cursor-1@cursor",
  "verdict": "CHANGES_REQUESTED",
  "summary": "Needs work.",
  "blocking_comments": ["fix parser edge case"],
  "checklist": {
    "gaming": {"status": "FOUND", "note": "ambiguous block handling"},
    "out_of_scope": {"status": "NONE", "note": "ok"},
    "fragility": {"status": "NONE", "note": "ok"},
    "removable_code": {"status": "NONE", "note": "ok"}
  }
}
```""",
        station="verify",
        root=temp_repo,
    )

    assert aggregate_results("verify", [approved, changes]).verdict == "CHANGES_REQUESTED"


# ---------------------------------------------------------------------------
# Bug #171 — aggregate_results triage/impl explicit branches, no else fallback
# ---------------------------------------------------------------------------

class TestAggregateResultsTriage:
    """Tests for the triage branch in aggregate_results (Bug #171)."""

    @staticmethod
    def _make_eval(verdict: str) -> EvaluationResult:
        return EvaluationResult(
            station="triage",
            agent_id="test-agent@test",
            verdict=verdict,
            format="synthetic",
            payload={"summary": f"vote {verdict}"},
            raw_comment="",
        )

    def test_triage_go_with_default_threshold(self) -> None:
        evals = [self._make_eval("GO")] * 3 + [self._make_eval("NO_GO")]
        result = aggregate_results("triage", evals)
        assert result.verdict == "GO"

    def test_triage_no_go_with_default_threshold(self) -> None:
        evals = [self._make_eval("NO_GO")] * 3 + [self._make_eval("GO")]
        result = aggregate_results("triage", evals)
        assert result.verdict == "NO_GO"

    def test_triage_tie_when_below_thresholds(self) -> None:
        evals = [self._make_eval("GO")] * 2 + [self._make_eval("NO_GO")] * 2
        result = aggregate_results("triage", evals)
        assert result.verdict == "TIE"

    def test_triage_custom_go_threshold_via_config(self) -> None:
        evals = [self._make_eval("GO")] * 2
        result = aggregate_results("triage", evals, config={"go_threshold": 2})
        assert result.verdict == "GO"

    def test_triage_custom_no_go_threshold_via_config(self) -> None:
        evals = [self._make_eval("NO_GO")] * 2
        result = aggregate_results("triage", evals, config={"no_go_threshold": 2})
        assert result.verdict == "NO_GO"

    def test_triage_config_none_uses_default_thresholds(self) -> None:
        evals = [self._make_eval("GO")] * 2 + [self._make_eval("NO_GO")]
        result = aggregate_results("triage", evals, config=None)
        assert result.verdict == "TIE"


class TestAggregateResultsImpl:
    """Tests for the impl branch in aggregate_results (Bug #171)."""

    @staticmethod
    def _make_eval(verdict: str) -> EvaluationResult:
        return EvaluationResult(
            station="impl",
            agent_id="test-agent@test",
            verdict=verdict,
            format="synthetic",
            payload={"summary": f"CI {verdict}"},
            raw_comment="",
        )

    def test_impl_uses_last_verdict(self) -> None:
        evals = [self._make_eval("FAIL"), self._make_eval("PASS")]
        result = aggregate_results("impl", evals)
        assert result.verdict == "PASS"

    def test_impl_single_evaluation(self) -> None:
        evals = [self._make_eval("FAIL")]
        result = aggregate_results("impl", evals)
        assert result.verdict == "FAIL"


class TestAggregateResultsUnknownStage:
    """Tests that unknown stages raise ValueError (Bug #171 — no else fallback)."""

    def test_unknown_stage_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Unknown pipeline stage"):
            aggregate_results("nonexistent", [])


class TestAggregateEvaluationsConfig:
    """Tests that aggregate_evaluations passes config through (Bug #171)."""

    @staticmethod
    def _make_eval(verdict: str) -> EvaluationResult:
        return EvaluationResult(
            station="triage",
            agent_id="test-agent@test",
            verdict=verdict,
            format="synthetic",
            payload={"summary": "vote"},
            raw_comment="",
        )

    def test_aggregate_evaluations_passes_config(self) -> None:
        evals = [self._make_eval("GO")] * 2
        result = aggregate_evaluations("triage", evals, config={"go_threshold": 2})
        assert result.verdict == "GO"


# ---------------------------------------------------------------------------
# Bug #169 — jsonschema lazy import
# ---------------------------------------------------------------------------

class TestJsonschemaLazyImport:
    """Tests that jsonschema is imported lazily (Bug #169)."""

    def test_pipeline_parser_no_top_level_jsonschema_import(self) -> None:
        import scripts.pipeline_parser as pp
        source = Path(pp.__file__).read_text(encoding="utf-8")
        lines = source.splitlines()
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith("from __future__"):
                continue
            if "from jsonschema import" in stripped and "def " not in stripped:
                # Check it's not inside a function (indented)
                if not line.startswith(" ") and not line.startswith("\t"):
                    pytest.fail(f"Top-level jsonschema import found: {stripped}")

    def test_pipeline_support_no_top_level_jsonschema_import(self) -> None:
        import wea_cli.pipeline_support as ps
        source = Path(ps.__file__).read_text(encoding="utf-8")
        lines = source.splitlines()
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith("from __future__"):
                continue
            if "from jsonschema import" in stripped and "def " not in stripped:
                if not line.startswith(" ") and not line.startswith("\t"):
                    pytest.fail(f"Top-level jsonschema import found: {stripped}")


# ---------------------------------------------------------------------------
# Bug #170 — stale evaluator_pool
# ---------------------------------------------------------------------------

class TestEvaluatorPool:
    """Tests for updated evaluator_pool in config.json (Bug #170)."""

    def test_evaluator_pool_contains_new_agents(self) -> None:
        config = json.loads((ROOT / "pipeline" / "config.json").read_text(encoding="utf-8"))
        pool = config["evaluator_pool"]
        for agent in ("Claude-8@claude", "Claude-9@claude", "Claude-10@claude", "Claude-11@claude", "Claude-12@claude"):
            assert agent in pool, f"Missing {agent} from evaluator_pool"

    def test_evaluator_pool_does_not_contain_stale_agents(self) -> None:
        config = json.loads((ROOT / "pipeline" / "config.json").read_text(encoding="utf-8"))
        pool = config["evaluator_pool"]
        assert "Claude-1@claude" not in pool
        assert "gemini-4@google" not in pool

    def test_evaluator_pool_retains_active_agents(self) -> None:
        config = json.loads((ROOT / "pipeline" / "config.json").read_text(encoding="utf-8"))
        pool = config["evaluator_pool"]
        assert "cursor-3@cursor" in pool
        assert "Codex-2@codex" in pool


# ---------------------------------------------------------------------------
# Bug #164 — legacy parser for triage and impl
# ---------------------------------------------------------------------------

class TestTriageLegacyParser:
    """Tests for _parse_triage_legacy (Bug #164)."""

    def test_triage_legacy_go_verdict(self) -> None:
        body = "### Triage Record by cursor-3@cursor\n\nVerdict: GO (worth pursuing)\n"
        result = _parse_triage_legacy(body)
        assert result.station == "triage"
        assert result.agent_id == "cursor-3@cursor"
        assert result.verdict == "GO"
        assert result.format == "legacy"
        assert result.payload["summary"] == "worth pursuing"

    def test_triage_legacy_no_go_verdict(self) -> None:
        body = "### Triage Record by Codex-2@codex\n\nVerdict: NO_GO\n"
        result = _parse_triage_legacy(body)
        assert result.verdict == "NO_GO"
        assert result.payload["summary"] == "legacy triage evaluation"

    def test_triage_legacy_unparseable(self) -> None:
        body = "### Triage Record by cursor-3@cursor\n\nNo verdict here.\n"
        result = _parse_triage_legacy(body)
        assert result.verdict == "UNKNOWN"
        assert result.format == "legacy_unparsed"

    def test_triage_legacy_via_parse_evaluation_comment(self, temp_repo: Path) -> None:
        _prepare_repo(temp_repo)
        body = "### Triage Record by cursor-3@cursor\n\nVerdict: GO (good task)\n"
        result = parse_evaluation_comment(body, station="triage", root=temp_repo)
        assert result.station == "triage"
        assert result.verdict == "GO"
        assert result.format == "legacy"


class TestImplLegacyParser:
    """Tests for _parse_impl_legacy (Bug #164)."""

    def test_impl_legacy_pass_verdict(self) -> None:
        body = "### Impl Evaluation by Claude-11@claude\n\nVerdict: PASS (all tests green)\n"
        result = _parse_impl_legacy(body)
        assert result.station == "impl"
        assert result.agent_id == "Claude-11@claude"
        assert result.verdict == "PASS"
        assert result.format == "legacy"
        assert result.payload["summary"] == "all tests green"

    def test_impl_legacy_fail_verdict(self) -> None:
        body = "### Impl Evaluation by Codex-2@codex\n\nVerdict: FAIL\n"
        result = _parse_impl_legacy(body)
        assert result.verdict == "FAIL"
        assert result.payload["summary"] == "legacy impl evaluation"

    def test_impl_legacy_unparseable(self) -> None:
        body = "### Impl Evaluation by Claude-11@claude\n\nNo CI result.\n"
        result = _parse_impl_legacy(body)
        assert result.verdict == "UNKNOWN"
        assert result.format == "legacy_unparsed"

    def test_impl_legacy_via_parse_evaluation_comment(self, temp_repo: Path) -> None:
        _prepare_repo(temp_repo)
        body = "### Impl Evaluation by Codex-2@codex\n\nVerdict: PASS (CI green)\n"
        result = parse_evaluation_comment(body, station="impl", root=temp_repo)
        assert result.station == "impl"
        assert result.verdict == "PASS"
        assert result.format == "legacy"


# ---------------------------------------------------------------------------
# Bug #165 — malformed JSON error message
# ---------------------------------------------------------------------------

class TestMalformedJsonError:
    """Tests for malformed JSON raising ValueError (Bug #165)."""

    def test_malformed_json_raises_value_error(self) -> None:
        body = '```json\n{"key": value_without_quotes}\n```'
        with pytest.raises(ValueError, match="Malformed JSON in evaluation block"):
            _extract_json_payloads(body)

    def test_malformed_json_includes_position_info(self) -> None:
        body = '```json\n{"key": }\n```'
        with pytest.raises(ValueError, match=r"line \d+, col \d+"):
            _extract_json_payloads(body)

    def test_valid_json_still_works(self) -> None:
        body = '```json\n{"station": "triage", "verdict": "GO"}\n```'
        result = _extract_json_payloads(body)
        assert len(result) == 1
        assert result[0]["verdict"] == "GO"
