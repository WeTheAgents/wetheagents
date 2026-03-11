from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

import pytest
from jsonschema import ValidationError

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from scripts.pipeline_parser import aggregate_results, parse_evaluation_comment  # noqa: E402
from wea_cli import cli  # noqa: E402


NEGATIVA_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["station", "agent_id", "verdict", "summary", "checks"],
    "properties": {
        "station": {"const": "negativa"},
        "agent_id": {"type": "string", "minLength": 1},
        "verdict": {"enum": ["PROCEED", "KILL"]},
        "summary": {"type": "string", "minLength": 1},
        "checks": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "not_duplicate",
                "architecture_compatible",
                "positive_roi",
                "no_fragility",
                "gaming_resistant",
                "requires_code",
            ],
            "properties": {
                name: {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["status", "note"],
                    "properties": {
                        "status": {"enum": ["PASS", "FAIL"]},
                        "note": {"type": "string", "minLength": 1},
                    },
                }
                for name in (
                    "not_duplicate",
                    "architecture_compatible",
                    "positive_roi",
                    "no_fragility",
                    "gaming_resistant",
                    "requires_code",
                )
            },
        },
    },
}

SPEC_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["station", "agent_id", "red_team_result", "approval", "notes"],
    "properties": {
        "station": {"const": "spec"},
        "agent_id": {"type": "string", "minLength": 1},
        "red_team_result": {"enum": ["NO_GAMING_FOUND", "GAMING_FOUND"]},
        "approval": {"enum": ["APPROVED", "REJECTED"]},
        "notes": {"type": "string", "minLength": 1},
        "findings": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
        },
    },
}

VERIFY_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["station", "agent_id", "verdict", "summary", "checklist", "blocking_comments"],
    "properties": {
        "station": {"const": "verify"},
        "agent_id": {"type": "string", "minLength": 1},
        "verdict": {"enum": ["APPROVED", "CHANGES_REQUESTED"]},
        "summary": {"type": "string", "minLength": 1},
        "blocking_comments": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
        },
        "checklist": {
            "type": "object",
            "additionalProperties": False,
            "required": ["gaming", "out_of_scope", "fragility", "removable_code"],
            "properties": {
                name: {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["status", "note"],
                    "properties": {
                        "status": {"enum": ["NONE", "FOUND"]},
                        "note": {"type": "string", "minLength": 1},
                    },
                }
                for name in ("gaming", "out_of_scope", "fragility", "removable_code")
            },
        },
    },
}


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _prepare_repo(root: Path) -> None:
    _write_json(root / "pipeline" / "negativa" / "evaluation.schema.json", NEGATIVA_SCHEMA)
    _write_json(root / "pipeline" / "spec" / "evaluation.schema.json", SPEC_SCHEMA)
    _write_json(root / "pipeline" / "verify" / "evaluation.schema.json", VERIFY_SCHEMA)


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
    _write_json(
        root / "pipeline" / "negativa" / "checklist.json",
        {"station": "negativa", "checks": ["not duplicate"]},
    )
    (root / "pipeline" / "negativa" / "WORKFLOW.md").write_text(
        "# Negativa\n\nUse schema.\n",
        encoding="utf-8",
    )


def _valid_negativa_payload() -> dict:
    return {
        "station": "negativa",
        "agent_id": "Codex-2@codex",
        "verdict": "PROCEED",
        "summary": "Looks worth doing.",
        "checks": {
            "not_duplicate": {"status": "PASS", "note": "new work"},
            "architecture_compatible": {"status": "PASS", "note": "fits current CLI"},
            "positive_roi": {"status": "PASS", "note": "worth the effort"},
            "no_fragility": {"status": "PASS", "note": "no new risky deps"},
            "gaming_resistant": {"status": "PASS", "note": "schema is explicit"},
            "requires_code": {"status": "PASS", "note": "cannot be solved by docs only"},
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
    assert result.payload["checks"]["gaming_resistant"]["status"] == "PASS"


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

1. Not duplicate: PASS - new task
2. Architecture compatible: PASS - fits design
3. Positive ROI: PASS - leverage is real
4. No fragility: PASS - no new risk
5. Gaming-resistant: PASS - anti-gaming present
6. Requires code: PASS - docs are not enough

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
