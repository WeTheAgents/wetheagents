from __future__ import annotations

import io
import json
import shutil
import sys
import uuid
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import check_genome_snapshot_freshness as checker  # noqa: E402


FIXED_NOW = "2026-04-15T12:00:00Z"


@pytest.fixture
def repo_tmp_path() -> Path:
    base_root = Path(r"C:\Users\peach\AppData\Local\Temp\genome-snapshot-freshness")
    base_root.mkdir(parents=True, exist_ok=True)
    base = base_root / f"case-{uuid.uuid4().hex}"
    try:
        yield base
    finally:
        shutil.rmtree(base, ignore_errors=True)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _setup_repo(
    root: Path,
    *,
    registered_agents: list[str],
    meta_by_agent: dict[str, object] | None = None,
) -> Path:
    meta_by_agent = meta_by_agent or {}
    agents_payload = {
        "agent0@system": {"balance": 0},
    }
    agents_payload.update({agent_id: {"balance": 0} for agent_id in registered_agents})
    _write_json(root / "ledger" / "balances.json", {"agents": agents_payload})
    (root / "genomes" / "base").mkdir(parents=True, exist_ok=True)

    for agent_id, payload in meta_by_agent.items():
        agent_dir = root / "genomes" / agent_id
        agent_dir.mkdir(parents=True, exist_ok=True)
        meta_path = agent_dir / "genome_meta.json"
        if isinstance(payload, str):
            meta_path.write_text(payload, encoding="utf-8")
        elif payload is None:
            continue
        else:
            _write_json(meta_path, payload)

    return root


def test_collect_report_marks_recent_snapshot_fresh(repo_tmp_path: Path) -> None:
    root = _setup_repo(
        repo_tmp_path,
        registered_agents=["Codex-2@codex"],
        meta_by_agent={
            "Codex-2@codex": {"last_snapshot": "2026-04-15T00:30:00Z"},
        },
    )

    report = checker.collect_report(root, now=FIXED_NOW)

    assert report["counts"] == {"FRESH": 1, "AGING": 0, "STALE": 0, "MISSING": 0}
    assert report["agents"][0]["status"] == "FRESH"


def test_collect_report_includes_vnext_only_agent(repo_tmp_path: Path) -> None:
    root = _setup_repo(
        repo_tmp_path,
        registered_agents=[],
        meta_by_agent={
            "New@agent": {"last_snapshot": "2026-04-15T00:30:00Z"},
        },
    )
    _write_json(
        root / "ledger" / "vnext" / "tide-state.json",
        {"schema": "wea-tide-state-2", "balances": {"New@agent": 0}},
    )

    report = checker.collect_report(root, now=FIXED_NOW)

    assert [entry["agent_id"] for entry in report["agents"]] == ["New@agent"]
    assert report["agents"][0]["status"] == "FRESH"


def test_collect_report_marks_exactly_one_day_as_aging(repo_tmp_path: Path) -> None:
    root = _setup_repo(
        repo_tmp_path,
        registered_agents=["Codex-2@codex"],
        meta_by_agent={
            "Codex-2@codex": {"last_snapshot": "2026-04-14T12:00:00Z"},
        },
    )

    report = checker.collect_report(root, now=FIXED_NOW)

    assert report["agents"][0]["status"] == "AGING"
    assert report["counts"]["AGING"] == 1


def test_collect_report_keeps_exact_threshold_in_aging(repo_tmp_path: Path) -> None:
    root = _setup_repo(
        repo_tmp_path,
        registered_agents=["Codex-2@codex"],
        meta_by_agent={
            "Codex-2@codex": {"last_snapshot": "2026-04-12T12:00:00Z"},
        },
    )

    report = checker.collect_report(root, now=FIXED_NOW, threshold_days=3)

    assert report["agents"][0]["status"] == "AGING"


def test_collect_report_marks_older_than_threshold_stale(repo_tmp_path: Path) -> None:
    root = _setup_repo(
        repo_tmp_path,
        registered_agents=["Codex-2@codex"],
        meta_by_agent={
            "Codex-2@codex": {"last_snapshot": "2026-04-12T11:59:59Z"},
        },
    )

    report = checker.collect_report(root, now=FIXED_NOW)

    assert report["agents"][0]["status"] == "STALE"
    assert report["counts"]["STALE"] == 1


def test_collect_report_respects_custom_threshold_days(repo_tmp_path: Path) -> None:
    root = _setup_repo(
        repo_tmp_path,
        registered_agents=["Codex-2@codex"],
        meta_by_agent={
            "Codex-2@codex": {"last_snapshot": "2026-04-11T12:00:00Z"},
        },
    )

    report = checker.collect_report(root, now=FIXED_NOW, threshold_days=5)

    assert report["agents"][0]["status"] == "AGING"


def test_collect_report_marks_missing_genome_dir_as_missing(repo_tmp_path: Path) -> None:
    root = _setup_repo(repo_tmp_path, registered_agents=["Codex-2@codex"])

    report = checker.collect_report(root, now=FIXED_NOW)

    assert report["agents"][0]["status"] == "MISSING"
    assert "missing genomes/Codex-2@codex/genome_meta.json" in report["agents"][0]["detail"]


def test_collect_report_marks_missing_last_snapshot_as_missing(repo_tmp_path: Path) -> None:
    root = _setup_repo(
        repo_tmp_path,
        registered_agents=["Codex-2@codex"],
        meta_by_agent={"Codex-2@codex": {"agent_id": "Codex-2@codex"}},
    )

    report = checker.collect_report(root, now=FIXED_NOW)

    assert report["agents"][0]["status"] == "MISSING"
    assert report["agents"][0]["detail"] == "last_snapshot missing"


def test_collect_report_marks_invalid_last_snapshot_as_missing(repo_tmp_path: Path) -> None:
    root = _setup_repo(
        repo_tmp_path,
        registered_agents=["Codex-2@codex"],
        meta_by_agent={"Codex-2@codex": {"last_snapshot": "not-a-timestamp"}},
    )

    report = checker.collect_report(root, now=FIXED_NOW)

    assert report["agents"][0]["status"] == "MISSING"
    assert "not valid ISO-8601" in report["agents"][0]["detail"]


def test_collect_report_marks_invalid_json_as_missing(repo_tmp_path: Path) -> None:
    root = _setup_repo(
        repo_tmp_path,
        registered_agents=["Codex-2@codex"],
        meta_by_agent={"Codex-2@codex": "{invalid json"},
    )

    report = checker.collect_report(root, now=FIXED_NOW)

    assert report["agents"][0]["status"] == "MISSING"
    assert "cannot load genomes/Codex-2@codex/genome_meta.json" in report["agents"][0]["detail"]


def test_collect_report_marks_non_object_metadata_as_missing(repo_tmp_path: Path) -> None:
    root = _setup_repo(
        repo_tmp_path,
        registered_agents=["Codex-2@codex"],
        meta_by_agent={"Codex-2@codex": ["not", "an", "object"]},
    )

    report = checker.collect_report(root, now=FIXED_NOW)

    assert report["agents"][0]["status"] == "MISSING"
    assert "is not a JSON object" in report["agents"][0]["detail"]


def test_default_exit_code_ignores_aging_but_strict_fails(repo_tmp_path: Path) -> None:
    root = _setup_repo(
        repo_tmp_path,
        registered_agents=["Codex-2@codex"],
        meta_by_agent={
            "Codex-2@codex": {"last_snapshot": "2026-04-14T12:00:00Z"},
        },
    )

    report = checker.collect_report(root, now=FIXED_NOW)

    assert checker.exit_code_for_report(report, strict=False) == 0
    assert checker.exit_code_for_report(report, strict=True) == 1


def test_collect_report_skips_agent0_system(repo_tmp_path: Path) -> None:
    root = _setup_repo(
        repo_tmp_path,
        registered_agents=["Codex-2@codex"],
        meta_by_agent={
            "Codex-2@codex": {"last_snapshot": "2026-04-15T08:00:00Z"},
        },
    )

    report = checker.collect_report(root, now=FIXED_NOW)

    assert [entry["agent_id"] for entry in report["agents"]] == ["Codex-2@codex"]


def test_future_snapshot_is_treated_as_fresh(repo_tmp_path: Path) -> None:
    root = _setup_repo(
        repo_tmp_path,
        registered_agents=["Codex-2@codex"],
        meta_by_agent={
            "Codex-2@codex": {"last_snapshot": "2026-04-16T12:00:00Z"},
        },
    )

    report = checker.collect_report(root, now=FIXED_NOW)

    assert report["agents"][0]["status"] == "FRESH"
    assert report["agents"][0]["age_days"] == 0


def test_main_returns_zero_and_prints_summary_for_all_fresh(
    repo_tmp_path: Path,
    monkeypatch,
) -> None:
    root = _setup_repo(
        repo_tmp_path,
        registered_agents=["Claude-1@claude", "Codex-2@codex"],
        meta_by_agent={
            "Claude-1@claude": {"last_snapshot": "2026-04-15T10:00:00Z"},
            "Codex-2@codex": {"last_snapshot": "2026-04-15T09:59:59Z"},
        },
    )

    monkeypatch.setattr(
        sys,
        "argv",
        ["check_genome_snapshot_freshness.py", "--root", str(root)],
    )
    monkeypatch.setattr(checker, "_resolve_now", lambda now=None: checker._parse_utc_timestamp(FIXED_NOW))
    stdout = io.StringIO()
    monkeypatch.setattr(sys, "stdout", stdout)

    exit_code = checker.main()

    assert exit_code == 0
    output = stdout.getvalue()
    assert "[FRESH] Claude-1@claude" in output
    assert "Summary: 2 agent(s), 2 fresh, 0 aging, 0 stale, 0 missing" in output


def test_main_returns_one_for_invalid_threshold(repo_tmp_path: Path, monkeypatch) -> None:
    root = _setup_repo(repo_tmp_path, registered_agents=["Codex-2@codex"])

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "check_genome_snapshot_freshness.py",
            "--root",
            str(root),
            "--threshold-days",
            "0.5",
        ],
    )
    stderr = io.StringIO()
    monkeypatch.setattr(sys, "stderr", stderr)

    exit_code = checker.main()

    assert exit_code == 1
    assert "--threshold-days must be >= 1" in stderr.getvalue()


def test_collect_report_skips_deprecated_agents_by_default(
    repo_tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        checker,
        "DEPRECATED_AGENTS",
        {"gemini-4@google": ("2026-04-23", "test rationale")},
    )
    root = _setup_repo(
        repo_tmp_path,
        registered_agents=["Codex-2@codex", "gemini-4@google"],
        meta_by_agent={
            "Codex-2@codex": {"last_snapshot": "2026-04-15T00:30:00Z"},
            "gemini-4@google": {"last_snapshot": "2026-01-01T00:00:00Z"},
        },
    )

    report, exit_code = checker.run(root, now=FIXED_NOW)

    assert exit_code == 0
    agent_ids = [entry["agent_id"] for entry in report["agents"]]
    assert "gemini-4@google" not in agent_ids
    assert report["skipped_deprecated"] == [
        {
            "agent_id": "gemini-4@google",
            "deprecated_at": "2026-04-23",
            "rationale": "test rationale",
        }
    ]


def test_collect_report_include_deprecated_overrides_skip(
    repo_tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        checker,
        "DEPRECATED_AGENTS",
        {"gemini-4@google": ("2026-04-23", "test rationale")},
    )
    root = _setup_repo(
        repo_tmp_path,
        registered_agents=["gemini-4@google"],
        meta_by_agent={
            "gemini-4@google": {"last_snapshot": "2026-01-01T00:00:00Z"},
        },
    )

    report, exit_code = checker.run(root, now=FIXED_NOW, include_deprecated=True)

    assert exit_code == 1
    assert report["agents"][0]["agent_id"] == "gemini-4@google"
    assert report["agents"][0]["status"] == "STALE"
    assert report["skipped_deprecated"] == []


def test_main_returns_one_for_nan_threshold(repo_tmp_path: Path, monkeypatch) -> None:
    root = _setup_repo(repo_tmp_path, registered_agents=["Codex-2@codex"])

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "check_genome_snapshot_freshness.py",
            "--root",
            str(root),
            "--threshold-days",
            "nan",
        ],
    )
    stderr = io.StringIO()
    monkeypatch.setattr(sys, "stderr", stderr)

    exit_code = checker.main()

    assert exit_code == 1
    assert "--threshold-days must be >= 1" in stderr.getvalue()
