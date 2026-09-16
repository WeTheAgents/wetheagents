from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts import post_ecosystem_digest as digest

FIXED_NOW = datetime(2026, 4, 13, 7, 30, tzinfo=timezone.utc)


def sample_report() -> dict:
    return {
        "generated_at": "2026-04-13T07:30:00Z",
        "economy": {
            "active_agents": 5,
            "total_agents": 8,
            "tasks_paid": 12,
            "tasks_open": 3,
            "transactions_today": 7,
        },
        "escrow": {
            "active_escrows": 4,
            "total_locked": 55,
            "expected_total": 10020,
            "actual_total": 10020,
            "invariant_ok": True,
        },
    }


def sample_gauntlet() -> dict[str, int]:
    return {"T1": 3, "T2": 1, "T3": 2, "T4": 4, "T5": 1, "T6": 5}


def test_build_digest_comment_contains_required_sections() -> None:
    body = digest.build_digest_comment(
        sample_report(),
        "AGENT0 REPORT\n5. ESCROW HEALTH\nInvariant: OK",
        sample_gauntlet(),
        now=FIXED_NOW,
    )

    assert "## Daily Ecosystem Digest" in body
    assert "_Generated 2026-04-13 07:30 UTC_" in body
    assert "### WEA Summary" in body
    assert (
        "5 active / 8 registered agents, 12 paid / 3 open tasks, 7 transactions today."
        in body
    )
    assert "### Escrow Count" in body
    assert "4 active escrows holding 55 WEA." in body
    assert "### Gauntlet Next Slots" in body
    assert "T1->3" in body
    assert "### Invariant Status" in body
    assert "OK (expected=10020, actual=10020)" in body
    assert "```text" in body


def test_main_posts_comment_successfully(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    posted: dict[str, object] = {}

    monkeypatch.setattr(
        digest,
        "gather_digest_inputs",
        lambda root: (sample_report(), "REPORT BODY", sample_gauntlet()),
    )

    def _fake_post(issue: int, body: str, *, root: Path) -> None:
        posted["issue"] = issue
        posted["body"] = body
        posted["root"] = root

    monkeypatch.setattr(digest, "post_issue_comment", _fake_post)

    rc = digest.main(["--issue", "471"])

    assert rc == 0
    assert posted["issue"] == 471
    assert "### WEA Summary" in str(posted["body"])
    assert "REPORT BODY" in str(posted["body"])
    assert "Posted ecosystem digest to issue #471." in capsys.readouterr().out


def test_post_issue_comment_uses_gh_command(monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict[str, object] = {}

    def _fake_run(
        command: list[str], *, root: Path, input_text: str | None = None
    ) -> str:
        called["command"] = command
        called["root"] = root
        called["input_text"] = input_text
        return ""

    monkeypatch.setattr(digest, "run_command", _fake_run)

    digest.post_issue_comment(471, "body", root=Path("repo-root"))

    assert called == {
        "command": ["gh", "issue", "comment", "471", "--body-file", "-"],
        "input_text": "body",
        "root": Path("repo-root"),
    }


def test_build_digest_comment_rejects_empty_report_text() -> None:
    with pytest.raises(digest.DigestError, match="empty"):
        digest.build_digest_comment(
            sample_report(), "   ", sample_gauntlet(), now=FIXED_NOW
        )


def test_main_handles_wea_report_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def _raise(root: Path) -> tuple[dict, str, dict[str, int]]:
        raise digest.DigestError("`wea report` failed: boom")

    monkeypatch.setattr(digest, "gather_digest_inputs", _raise)

    rc = digest.main(["--issue", "471"])

    assert rc == 1
    assert "`wea report` failed: boom" in capsys.readouterr().err


def test_dry_run_prints_comment_without_posting(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    called = {"post": False}

    monkeypatch.setattr(
        digest,
        "gather_digest_inputs",
        lambda root: (sample_report(), "REPORT BODY", sample_gauntlet()),
    )

    def _unexpected_post(*args, **kwargs) -> None:
        called["post"] = True

    monkeypatch.setattr(digest, "post_issue_comment", _unexpected_post)

    rc = digest.main(["--issue", "471", "--dry-run"])

    assert rc == 0
    assert called["post"] is False
    out = capsys.readouterr().out
    assert "## Daily Ecosystem Digest" in out
    assert "REPORT BODY" in out


def test_load_gauntlet_next_slots_defaults_when_file_missing() -> None:
    slots = digest.load_gauntlet_next_slots(Path("definitely-missing-digest-root"))

    assert slots == {"T1": 1, "T2": 1, "T3": 1, "T4": 1, "T5": 1, "T6": 1}


@pytest.mark.parametrize("dry_run", [False, True])
def test_versioned_report_is_rejected_before_rendering_or_posting(
    monkeypatch, capsys, dry_run
):
    monkeypatch.setattr(
        digest,
        "run_command",
        lambda *args, **kwargs: json.dumps(
            {"schema": "wea-report-1", "active_escrow_wea": 20}
        ),
    )
    monkeypatch.setattr(
        digest, "post_issue_comment", lambda *args, **kwargs: pytest.fail("published")
    )
    args = ["--issue", "980"]
    if dry_run:
        args.append("--dry-run")
    assert digest.main(args) == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert "does not support versioned report schemas" in output.err
