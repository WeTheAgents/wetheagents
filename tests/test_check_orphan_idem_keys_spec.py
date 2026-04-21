"""Boundary spec tests for scripts/check_orphan_idem_keys.py — Gauntlet T4S27.

Encodes the full behavioural contract for edge/boundary inputs:

  (a) SHA-256 hashing: stored hash resolves to raw history key via digest match
  (b) SHA-256 + alias chain: old-agent history key canonicalised, hashed → matches stored hash
  (c) namespace escrow_create_: identified as history-backed; present in history → not orphan
  (d) namespace escrow-create-: identified as history-backed
  (e) namespace escrow-return-: identified as history-backed; present in history → not orphan
  (f) namespace escrow_return_: identified as history-backed
  (g) non-history namespaces claim| and register|: excluded from check → never orphan
  (h) trajectory_mint alias: agent at index 3 canonicalised via agent_aliases
  (i) empty idem_keys.json {}: 0 recorded, 0 checked → PASS
  (j) missing idem_keys.json: 0 recorded → PASS even with populated history
  (k) malformed JSONL non-dict payload: array/string lines skipped, valid lines kept
  (l) JSONL with blank/whitespace-only lines: skipped without crash
  (m) JSON output schema PASS: all 6 required fields with correct types
  (n) JSON output schema FAIL: all 6 fields present, orphan_keys is sorted list
  (o) exit code contract: subprocess exit 0 on PASS, exit 1 on FAIL
  (p) multiple JSONL history files: all files are processed and merged

Gaps found (documented, not fixed — script unchanged):
  GAP-1: sha256(old_format_key) stored in idem_keys + old_format_key in history will
          produce a false orphan after alias migration, because evidence contains
          sha256(new_format_key), not sha256(old_format_key). The alias normalisation
          happens on the history side before hashing, so stored hashes of pre-migration
          keys become unresolvable.
  GAP-2: canonicalize_idem_key only resolves agent aliases for pipe-delimited formats
          (accept, payment, escrow, escrow_return, trajectory_mint). Keys with
          underscore/hyphen prefixes (escrow_create_, escrow-return-, etc.) are not
          canonicalised — agent aliases embedded in those key strings go unresolved.
  GAP-3: Nested keys dict takes priority over top-level keys with the same name via
          setdefault. A top-level key that duplicates a nested key is silently ignored;
          this precedence is implicit and not documented.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.check_orphan_idem_keys import (
    build_history_key_evidence,
    is_history_backed_idem_key,
    load_history_idem_keys,
    run_check,
    select_history_backed_idem_keys,
)

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_orphan_idem_keys.py"


# ── helpers ───────────────────────────────────────────────────────────────────


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_history(root: Path, filename: str, *events: object) -> None:
    history_dir = root / "ledger" / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for event in events:
        if isinstance(event, str):
            lines.append(event)
        else:
            lines.append(json.dumps(event))
    text = "\n".join(lines)
    if text:
        text += "\n"
    (history_dir / filename).write_text(text, encoding="utf-8")


def _sha256(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


# ── (a) SHA-256 hashing exact algorithm ──────────────────────────────────────


def test_spec_a_stored_hash_resolves_via_sha256_of_raw_history_key(temp_repo: Path) -> None:
    """A SHA-256 hex digest stored in idem_keys matches when history contains the raw key."""
    raw_key = "payment|42|alice@test"
    stored_hash = _sha256(raw_key)

    # Store the hash with payment metadata so it is detected as history-backed.
    _write_json(
        temp_repo / "ledger" / "idem_keys.json",
        {"version": 1, "keys": {stored_hash: {"action": "payment"}}},
    )
    _write_history(temp_repo, "events.jsonl", {"idem_key": raw_key})

    report, exit_code = run_check(temp_repo)

    assert exit_code == 0, f"expected PASS but got orphans: {report['orphan_keys']}"
    assert report["status"] == "PASS"
    assert stored_hash not in report["orphan_keys"]


def test_spec_a_wrong_hash_produces_orphan(temp_repo: Path) -> None:
    """A SHA-256 digest of a *different* key does not match — detected as orphan."""
    raw_key_in_idem = "payment|42|alice@test"
    raw_key_in_history = "payment|99|bob@test"
    stored_hash = _sha256(raw_key_in_idem)

    _write_json(
        temp_repo / "ledger" / "idem_keys.json",
        {"version": 1, "keys": {stored_hash: {"action": "payment"}}},
    )
    _write_history(temp_repo, "events.jsonl", {"idem_key": raw_key_in_history})

    report, exit_code = run_check(temp_repo)

    assert exit_code == 1
    assert stored_hash in report["orphan_keys"]


# ── (b) SHA-256 + alias chain ─────────────────────────────────────────────────


def test_spec_b_hashed_key_resolves_via_alias_canonicalization_then_sha256(
    temp_repo: Path,
) -> None:
    """Stored hash of new-format key resolves when history contains the old-format key.

    Flow: history has old key → alias canonicalises to new key → sha256(new) → matches stored hash.
    """
    old_agent = "Antigravity-1@Google"
    new_agent = "gemini-4@google"
    raw_key_old = f"accept|10|{old_agent}|slot1"
    raw_key_new = f"accept|10|{new_agent}|slot1"
    stored_hash = _sha256(raw_key_new)

    _write_json(
        temp_repo / "ledger" / "idem_keys.json",
        {"version": 1, "keys": {stored_hash: {"action": "accept"}}},
    )
    _write_json(
        temp_repo / "ledger" / "agent_aliases.json",
        {old_agent: new_agent},
    )
    _write_history(temp_repo, "events.jsonl", {"idem_key": raw_key_old})

    report, exit_code = run_check(temp_repo)

    assert exit_code == 0, f"expected PASS, orphans: {report['orphan_keys']}"
    assert report["status"] == "PASS"


# ── (c) namespace: escrow_create_ ────────────────────────────────────────────


def test_spec_c_escrow_create_underscore_prefix_is_history_backed(temp_repo: Path) -> None:
    """Keys with escrow_create_ prefix are treated as history-backed and checked."""
    assert is_history_backed_idem_key("escrow_create_123", True) is True


def test_spec_c_escrow_create_underscore_in_history_is_not_orphan(temp_repo: Path) -> None:
    """escrow_create_ key present in both idem_keys and history → PASS (not orphan)."""
    idem_key = "escrow_create_issue_123_gauntlet"

    _write_json(
        temp_repo / "ledger" / "idem_keys.json",
        {"version": 1, idem_key: True},
    )
    _write_history(temp_repo, "events.jsonl", {"idem_key": idem_key})

    report, exit_code = run_check(temp_repo)

    assert exit_code == 0, f"expected PASS, orphans: {report['orphan_keys']}"
    assert idem_key not in report["orphan_keys"]


# ── (d) namespace: escrow-create- ────────────────────────────────────────────


def test_spec_d_escrow_create_hyphen_prefix_is_history_backed() -> None:
    """Keys with escrow-create- (hyphen) prefix are history-backed."""
    assert is_history_backed_idem_key("escrow-create-456", True) is True


# ── (e) namespace: escrow-return- ────────────────────────────────────────────


def test_spec_e_escrow_return_hyphen_prefix_is_history_backed() -> None:
    """Keys with escrow-return- (hyphen) prefix are history-backed."""
    assert is_history_backed_idem_key("escrow-return-cycle1-789", True) is True


def test_spec_e_escrow_return_hyphen_in_history_is_not_orphan(temp_repo: Path) -> None:
    """escrow-return- key present in history → not an orphan."""
    idem_key = "escrow-return-cycle18-700"

    _write_json(
        temp_repo / "ledger" / "idem_keys.json",
        {"version": 1, idem_key: True},
    )
    _write_history(temp_repo, "events.jsonl", {"idem_key": idem_key})

    report, exit_code = run_check(temp_repo)

    assert exit_code == 0, f"expected PASS, orphans: {report['orphan_keys']}"


# ── (f) namespace: escrow_return_ ────────────────────────────────────────────


def test_spec_f_escrow_return_underscore_prefix_is_history_backed() -> None:
    """Keys with escrow_return_ (trailing underscore, no pipe) prefix are history-backed."""
    assert is_history_backed_idem_key("escrow_return_issue_99", True) is True


# ── (g) non-history namespaces: claim| and register| ─────────────────────────


def test_spec_g_claim_and_register_prefixes_are_not_history_backed() -> None:
    """claim| and register| keys are NOT history-backed — excluded from orphan checks."""
    assert is_history_backed_idem_key("claim|10|alice@test", True) is False
    assert is_history_backed_idem_key("register|alice@test", True) is False


def test_spec_g_claim_and_register_keys_never_appear_in_checked_set() -> None:
    """select_history_backed_idem_keys excludes claim| and register| entries."""
    entries = {
        "claim|10|alice@test": True,
        "register|alice@test": True,
        "claim|99|bob@test": {"action": "claim"},
        "escrow|1": True,
    }
    checked = select_history_backed_idem_keys(entries)
    assert "claim|10|alice@test" not in checked
    assert "register|alice@test" not in checked
    assert "claim|99|bob@test" not in checked
    assert "escrow|1" in checked


def test_spec_g_claim_keys_absent_from_history_still_pass(temp_repo: Path) -> None:
    """claim|/register| keys NOT in history do not cause FAIL (they're not checked)."""
    _write_json(
        temp_repo / "ledger" / "idem_keys.json",
        {"version": 1, "claim|5|alice@test": True, "register|bob@test": True},
    )

    report, exit_code = run_check(temp_repo)

    assert exit_code == 0
    assert report["status"] == "PASS"
    assert report["checked_idem_keys"] == 0


# ── (h) trajectory_mint alias canonicalization ───────────────────────────────


def test_spec_h_trajectory_mint_agent_alias_resolved_at_slot_3(temp_repo: Path) -> None:
    """trajectory_mint|T|S|OldAgent in idem_keys resolved against history entry with new agent name."""
    old_agent = "OldBot@x"
    new_agent = "NewBot@x"
    key_old = f"trajectory_mint|1|2|{old_agent}"
    key_new = f"trajectory_mint|1|2|{new_agent}"

    _write_json(
        temp_repo / "ledger" / "idem_keys.json",
        {"version": 1, key_old: True},
    )
    _write_json(
        temp_repo / "ledger" / "agent_aliases.json",
        {old_agent: new_agent},
    )
    _write_history(temp_repo, "events.jsonl", {"idem_key": key_new})

    report, exit_code = run_check(temp_repo)

    assert exit_code == 0, f"expected PASS, orphans: {report['orphan_keys']}"
    assert key_old not in report["orphan_keys"]


# ── (i) empty idem_keys.json {} ──────────────────────────────────────────────


def test_spec_i_empty_idem_keys_object_passes_with_zero_recorded(temp_repo: Path) -> None:
    """idem_keys.json with just {} records 0 keys and produces PASS."""
    _write_json(temp_repo / "ledger" / "idem_keys.json", {})

    report, exit_code = run_check(temp_repo)

    assert exit_code == 0
    assert report["status"] == "PASS"
    assert report["recorded_idem_keys"] == 0
    assert report["checked_idem_keys"] == 0
    assert report["orphan_keys"] == []


# ── (j) missing idem_keys.json ───────────────────────────────────────────────


def test_spec_j_missing_idem_keys_file_passes_even_with_history(temp_repo: Path) -> None:
    """When idem_keys.json is absent, 0 keys are recorded → PASS regardless of history content."""
    (temp_repo / "ledger" / "idem_keys.json").unlink(missing_ok=True)
    _write_history(temp_repo, "events.jsonl", {"idem_key": "payment|99|alice@test"})

    report, exit_code = run_check(temp_repo)

    assert exit_code == 0
    assert report["recorded_idem_keys"] == 0
    assert report["orphan_keys"] == []


# ── (k) malformed JSONL: non-dict payloads ────────────────────────────────────


def test_spec_k_jsonl_array_lines_skipped_valid_lines_kept(temp_repo: Path) -> None:
    """Non-dict JSONL lines (arrays, raw strings) are skipped; valid dict lines are parsed."""
    (temp_repo / "ledger" / "history").mkdir(parents=True, exist_ok=True)
    history_file = temp_repo / "ledger" / "history" / "events.jsonl"
    history_file.write_text(
        "\n".join([
            json.dumps([1, 2, 3]),                                         # array → skip
            json.dumps({"idem_key": "escrow|10"}),                        # valid
            json.dumps("just a string"),                                   # raw string → skip
            json.dumps({"idem_key": "payment|1|alice@test"}),             # valid
            json.dumps({"no_idem_key": True}),                            # valid dict, no key → skip
        ]) + "\n",
        encoding="utf-8",
    )

    history_keys = load_history_idem_keys(temp_repo / "ledger" / "history")

    assert history_keys == {"escrow|10", "payment|1|alice@test"}


# ── (l) JSONL blank/whitespace-only lines ─────────────────────────────────────


def test_spec_l_blank_and_whitespace_lines_in_jsonl_skipped(temp_repo: Path) -> None:
    """Blank and whitespace-only lines in history JSONL do not cause errors."""
    (temp_repo / "ledger" / "history").mkdir(parents=True, exist_ok=True)
    history_file = temp_repo / "ledger" / "history" / "blank.jsonl"
    history_file.write_text("\n   \n\t\n\n", encoding="utf-8")

    history_keys = load_history_idem_keys(temp_repo / "ledger" / "history")

    assert history_keys == set()


# ── (m) JSON output schema: PASS ─────────────────────────────────────────────


def test_spec_m_json_output_schema_on_pass(temp_repo: Path) -> None:
    """PASS report contains all 6 required fields with correct types."""
    _write_json(temp_repo / "ledger" / "idem_keys.json", {"version": 1})

    report, exit_code = run_check(temp_repo)

    assert exit_code == 0
    required_fields = {
        "status": str,
        "summary": str,
        "recorded_idem_keys": int,
        "checked_idem_keys": int,
        "history_idem_keys": int,
        "orphan_keys": list,
    }
    for field, expected_type in required_fields.items():
        assert field in report, f"missing field: {field}"
        assert isinstance(report[field], expected_type), (
            f"field {field!r}: expected {expected_type.__name__}, got {type(report[field]).__name__}"
        )
    assert report["status"] == "PASS"
    assert report["orphan_keys"] == []


# ── (n) JSON output schema: FAIL ─────────────────────────────────────────────


def test_spec_n_json_output_schema_on_fail_orphan_keys_sorted(temp_repo: Path) -> None:
    """FAIL report contains all 6 required fields; orphan_keys is a sorted list of strings."""
    _write_json(
        temp_repo / "ledger" / "idem_keys.json",
        {
            "version": 1,
            "escrow|30": True,
            "payment|10|alice@test": True,
            "accept|5|bob@test|slot1": True,
        },
    )

    report, exit_code = run_check(temp_repo)

    assert exit_code == 1
    assert report["status"] == "FAIL"

    required_fields = {
        "status": str,
        "summary": str,
        "recorded_idem_keys": int,
        "checked_idem_keys": int,
        "history_idem_keys": int,
        "orphan_keys": list,
    }
    for field, expected_type in required_fields.items():
        assert field in report, f"missing field: {field}"
        assert isinstance(report[field], expected_type)

    orphans = report["orphan_keys"]
    assert all(isinstance(k, str) for k in orphans), "orphan_keys must be strings"
    assert orphans == sorted(orphans), "orphan_keys must be in sorted order"
    assert len(orphans) == 3


# ── (o) exit code contract via subprocess ────────────────────────────────────


def test_spec_o_subprocess_exit_0_on_pass(temp_repo: Path) -> None:
    """Script returns exit code 0 when no orphans exist."""
    _write_json(temp_repo / "ledger" / "idem_keys.json", {"version": 1})

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(temp_repo)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "PASS"


def test_spec_o_subprocess_exit_1_on_fail(temp_repo: Path) -> None:
    """Script returns exit code 1 when orphan keys are detected."""
    _write_json(
        temp_repo / "ledger" / "idem_keys.json",
        {"version": 1, "escrow|99": True},
    )

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(temp_repo)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "FAIL"
    assert "escrow|99" in payload["orphan_keys"]


# ── (p) multiple JSONL history files ─────────────────────────────────────────


def test_spec_p_multiple_history_files_all_loaded(temp_repo: Path) -> None:
    """Keys from multiple JSONL history files are all collected and merged."""
    _write_json(
        temp_repo / "ledger" / "idem_keys.json",
        {
            "version": 1,
            "escrow|1": True,
            "payment|2|alice@test": True,
            "accept|3|bob@test|slot1": True,
        },
    )
    _write_history(temp_repo, "2026-04-20.jsonl", {"idem_key": "escrow|1"})
    _write_history(temp_repo, "2026-04-21.jsonl", {"idem_key": "payment|2|alice@test"})
    _write_history(temp_repo, "2026-04-22.jsonl", {"idem_key": "accept|3|bob@test|slot1"})

    report, exit_code = run_check(temp_repo)

    assert exit_code == 0, f"expected PASS, orphans: {report['orphan_keys']}"
    assert report["history_idem_keys"] == 3
    assert report["orphan_keys"] == []


def test_spec_p_deduplicated_key_across_files_counted_once(temp_repo: Path) -> None:
    """The same idem_key appearing in multiple files is deduplicated in the history set."""
    _write_json(
        temp_repo / "ledger" / "idem_keys.json",
        {"version": 1, "escrow|77": True},
    )
    _write_history(temp_repo, "file_a.jsonl", {"idem_key": "escrow|77"})
    _write_history(temp_repo, "file_b.jsonl", {"idem_key": "escrow|77"})

    report, exit_code = run_check(temp_repo)

    assert exit_code == 0
    assert report["history_idem_keys"] == 1
