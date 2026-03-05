from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.meaning_compression import validate as validate_cli
from scripts.meaning_compression.schema import build_submission_schema
from scripts.meaning_compression.validator import (
    DEFAULT_SCHEMA_PATH,
    count_words,
    load_atom_index,
    validate_pair,
)

SAMPLES_DIR = ROOT / "scripts" / "meaning_compression" / "samples"


def _load_sample(name: str) -> dict:
    return json.loads((SAMPLES_DIR / name).read_text(encoding="utf-8"))


def _sync_metrics(payload: dict) -> dict:
    payload["metrics"]["word_count"] = count_words(payload["text_en"])
    payload["metrics"]["atoms_count"] = len(payload["atoms_claimed"])
    return payload


def test_schema_file_matches_builder() -> None:
    on_disk = json.loads(DEFAULT_SCHEMA_PATH.read_text(encoding="utf-8"))
    assert on_disk == build_submission_schema()


def test_cli_happy_path_passes(capsys) -> None:
    rc = validate_cli.main(
        [
            "--baseline",
            str(SAMPLES_DIR / "baseline.json"),
            "--submission",
            str(SAMPLES_DIR / "challenger.json"),
        ]
    )

    out = capsys.readouterr().out
    assert rc == 0
    assert "PASS" in out
    assert "baseline: words=43 atoms=8" in out
    assert "submission: words=32 atoms=12" in out


def test_metric_mismatch_fails() -> None:
    atoms = load_atom_index()
    baseline = _load_sample("baseline.json")
    challenger = _load_sample("challenger.json")
    challenger["metrics"]["word_count"] = challenger["metrics"]["word_count"] + 1

    report = validate_pair(baseline, challenger, atom_index=atoms)

    assert not report.ok
    assert any("submission.metrics.word_count" in error for error in report.errors)


def test_agent_field_is_metadata_only() -> None:
    atoms = load_atom_index()
    baseline = _load_sample("baseline.json")
    challenger = _load_sample("challenger.json")
    challenger["agent"] = "future/agent-format:v2"

    report = validate_pair(baseline, challenger, atom_index=atoms)

    assert report.ok


def test_unknown_atom_id_fails() -> None:
    atoms = load_atom_index()
    baseline = _load_sample("baseline.json")
    challenger = _load_sample("challenger.json")
    challenger["atoms_claimed"].append("WTA-999")
    _sync_metrics(challenger)

    report = validate_pair(baseline, challenger, atom_index=atoms)

    assert not report.ok
    assert any("unknown atom IDs: WTA-999" in error for error in report.errors)


def test_escalation_failure_fails() -> None:
    atoms = load_atom_index()
    baseline = _load_sample("baseline.json")
    challenger = copy.deepcopy(baseline)
    challenger["agent"] = "not-dense-enough"
    _sync_metrics(challenger)

    report = validate_pair(baseline, challenger, atom_index=atoms)

    assert not report.ok
    assert any(error.startswith("escalation: submission word_count") for error in report.errors)
    assert any(error.startswith("escalation: submission atoms_count") for error in report.errors)
