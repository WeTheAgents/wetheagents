"""Boundary-spec tests for scripts/check_claim_ttl.py.

Covers off-by-one at exact TTL, concurrent claims on the same issue,
verify-before-TTL/accept-after-TTL, zero-balance claimants, re-claim after expiry,
and ghost claims (issue absent from any task index).

## Gaps

GAP-1 (verify-before-TTL): The script has no visibility into verify or accept comments.
If a claim was verified within TTL but acceptance arrives after TTL and the claim entry
remains in the input list, the checker flags it as expired. Callers must remove
verified/accepted claims from the input before running the checker.

GAP-2 (re-claim in JSON mode): In --json-file mode every entry in the array is
evaluated independently, including stale entries for the same issue+agent. A re-claimed
issue whose first (expired) entry was not pruned from the JSON input will trigger a FAIL
even when the re-claim itself is fresh. In idem_keys mode this does not occur because
get_claim_from_idem_keys resolves only the latest-timestamp claim per issue.

GAP-3 (ghost claim): The script does not validate that the referenced issue exists in
any task index. Ghost claims are evaluated purely on claimed_at vs TTL, which can produce
false positives (expired ghost claims flagged as real violations) or false negatives
(fresh ghost claims silently pass without any existence check).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_claim_ttl.py"


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT)] + args,
        capture_output=True,
        text=True,
        check=False,
    )


def _write_claims(path: Path, claims: list[dict]) -> None:
    path.write_text(json.dumps(claims), encoding="utf-8")


# ── 1. Exact TTL Boundary ─────────────────────────────────────────────────────
# Decision table (TTL = 24h):
# | claimed_at           | now                  | age      | expired? |
# |----------------------|----------------------|----------|----------|
# | 2026-03-05T00:00:00Z | 2026-03-06T00:00:00Z | == TTL   | NO  (OK) |
# | 2026-03-05T00:00:00Z | 2026-03-06T00:00:01Z | TTL + 1s | YES(FAIL)|
#
# Checker uses strict less-than: claimed_dt + ttl_delta < now_dt.
# At exactly TTL the inequality is false → claim still valid (off-by-one is safe-side).
# One second past TTL the inequality becomes true → claim expired.


def test_exact_ttl_boundary_at_ttl_is_not_expired(tmp_path: Path) -> None:
    """At now == claimed_at + TTL exactly, the claim is not expired (< not <=)."""
    claims_file = tmp_path / "claims.json"
    _write_claims(claims_file, [
        {"issue": 1, "agent": "alice@test", "claimed_at": "2026-03-05T00:00:00Z"},
    ])
    result = _run([
        "--json-file", str(claims_file),
        "--now", "2026-03-06T00:00:00Z",  # exactly 24h later
        "--ttl-hours", "24",
    ])
    assert result.returncode == 0, f"Expected OK at exact TTL; got:\n{result.stdout}"
    assert "OK" in result.stdout


def test_exact_ttl_boundary_one_second_past_is_expired(tmp_path: Path) -> None:
    """At now == claimed_at + TTL + 1s, the claim is expired."""
    claims_file = tmp_path / "claims.json"
    _write_claims(claims_file, [
        {"issue": 1, "agent": "alice@test", "claimed_at": "2026-03-05T00:00:00Z"},
    ])
    result = _run([
        "--json-file", str(claims_file),
        "--now", "2026-03-06T00:00:01Z",  # 24h + 1 second
        "--ttl-hours", "24",
    ])
    assert result.returncode == 1, f"Expected FAIL one second past TTL; got:\n{result.stdout}"
    assert "FAIL" in result.stdout
    assert "#1" in result.stdout


# ── 2. Concurrent Claims ──────────────────────────────────────────────────────
# Decision table (two agents claim issue 1, TTL = 24h, now = 2026-03-05T12:00:00Z):
# | agent | claimed_at           | age  | expired? | result             |
# |-------|----------------------|------|----------|--------------------|
# | alice | 2026-03-05T02:00:00Z | 10h  | NO       | both pass → exit 0 |
# | bob   | 2026-03-05T02:00:00Z | 10h  | NO       |                    |
#
# | alice | 2026-03-04T00:00:00Z | 36h  | YES      | both fail → exit 1 |
# | bob   | 2026-03-04T01:00:00Z | 35h  | YES      | both reported      |
#
# | alice | 2026-03-04T00:00:00Z | 26h  | YES      | mixed → exit 1     |
# | bob   | 2026-03-05T01:00:00Z | 1h   | NO       | only alice reported|
#
# In --json-file mode the checker processes all entries independently;
# multiple claims for the same issue are each evaluated on their own timestamp.


def test_concurrent_claims_both_within_ttl(tmp_path: Path) -> None:
    """Two agents claim the same task, both within TTL → no expiry, exit 0."""
    claims_file = tmp_path / "claims.json"
    _write_claims(claims_file, [
        {"issue": 1, "agent": "alice@test", "claimed_at": "2026-03-05T02:00:00Z"},
        {"issue": 1, "agent": "bob@test",   "claimed_at": "2026-03-05T02:00:00Z"},
    ])
    result = _run([
        "--json-file", str(claims_file),
        "--now", "2026-03-05T12:00:00Z",  # 10h later — both within 24h TTL
        "--ttl-hours", "24",
    ])
    assert result.returncode == 0, f"Both within TTL; got:\n{result.stdout}"
    assert "OK" in result.stdout


def test_concurrent_claims_both_expired(tmp_path: Path) -> None:
    """Two agents claim the same task, both expired → both reported, exit 1."""
    claims_file = tmp_path / "claims.json"
    _write_claims(claims_file, [
        {"issue": 1, "agent": "alice@test", "claimed_at": "2026-03-04T00:00:00Z"},  # 36h old
        {"issue": 1, "agent": "bob@test",   "claimed_at": "2026-03-04T01:00:00Z"},  # 35h old
    ])
    result = _run([
        "--json-file", str(claims_file),
        "--now", "2026-03-05T12:00:00Z",
        "--ttl-hours", "24",
    ])
    assert result.returncode == 1, f"Both expired; got:\n{result.stdout}"
    assert "FAIL" in result.stdout
    assert "alice@test" in result.stdout
    assert "bob@test" in result.stdout


def test_concurrent_claims_one_expired_one_fresh(tmp_path: Path) -> None:
    """One claim expired, the other fresh → only the expired one is reported."""
    claims_file = tmp_path / "claims.json"
    _write_claims(claims_file, [
        {"issue": 1, "agent": "alice@test", "claimed_at": "2026-03-04T00:00:00Z"},  # 26h old
        {"issue": 1, "agent": "bob@test",   "claimed_at": "2026-03-05T01:00:00Z"},  # 1h old
    ])
    result = _run([
        "--json-file", str(claims_file),
        "--now", "2026-03-05T02:00:00Z",
        "--ttl-hours", "24",
    ])
    assert result.returncode == 1
    assert "alice@test" in result.stdout
    assert "bob@test" not in result.stdout


# ── 3. Verify-Before-TTL, Accept-After-TTL ───────────────────────────────────
# Decision table (TTL = 24h):
# | claimed_at           | verify_at (conceptual) | check_at             | expired? |
# |----------------------|------------------------|----------------------|----------|
# | 2026-03-05T00:00:00Z | T+20h (inside TTL)     | 2026-03-06T01:00:00Z | YES(FAIL)|
#
# GAP-1: The script only reads claimed_at from its input; it has no knowledge of verify
# or accept events. A claim that was verified before TTL is still flagged as expired if
# the claim entry is present at check time and claimed_at + TTL < now.
# Callers must remove verified/accepted claims from the input before running the checker.


def test_verify_before_ttl_accept_after_ttl_claim_still_flagged(tmp_path: Path) -> None:
    """Claim verified within TTL but checked after TTL: flagged as expired.

    GAP-1: script is unaware of verify/accept comments — only claimed_at matters.
    """
    claims_file = tmp_path / "claims.json"
    # claim at T+0h; verify (in real flow) at T+20h; check here at T+25h
    _write_claims(claims_file, [
        {"issue": 42, "agent": "alice@test", "claimed_at": "2026-03-05T00:00:00Z"},
    ])
    result = _run([
        "--json-file", str(claims_file),
        "--now", "2026-03-06T01:00:00Z",  # 25h after claim; verify was at T+20h (inside TTL)
        "--ttl-hours", "24",
    ])
    # Even though verify happened before TTL, the claim is flagged because only
    # claimed_at is examined — caller must pre-filter accepted/verified claims.
    assert result.returncode == 1
    assert "FAIL" in result.stdout
    assert "#42" in result.stdout


def test_claim_accepted_before_ttl_passes_if_removed_from_input(tmp_path: Path) -> None:
    """Caller removes accepted claim before running checker → no entries → exit 0."""
    claims_file = tmp_path / "claims.json"
    # Caller pre-filtered: accepted claim is absent from the input
    _write_claims(claims_file, [])
    result = _run([
        "--json-file", str(claims_file),
        "--now", "2026-03-06T01:00:00Z",
        "--ttl-hours", "24",
    ])
    assert result.returncode == 0
    assert "OK" in result.stdout


# ── 4. Zero-Balance Claimant ──────────────────────────────────────────────────
# Decision table (TTL = 24h, alice.balance = 0 WEA):
# | claimed_at           | now                  | age  | balance | expired? |
# |----------------------|----------------------|------|---------|----------|
# | 2026-03-05T02:00:00Z | 2026-03-05T12:00:00Z | 10h  | 0       | NO  (OK) |
# | 2026-03-04T00:00:00Z | 2026-03-05T10:00:00Z | 34h  | 0       | YES(FAIL)|
#
# The script is balance-agnostic: it processes only (issue, agent, claimed_at).
# TTL behaviour for a zero-balance claimant is identical to a funded agent.


def test_zero_balance_claimant_within_ttl_is_ok(tmp_path: Path) -> None:
    """Zero-balance agent's claim within TTL is not expired — balance is irrelevant."""
    claims_file = tmp_path / "claims.json"
    _write_claims(claims_file, [
        {"issue": 7, "agent": "alice@test", "claimed_at": "2026-03-05T02:00:00Z"},
    ])
    result = _run([
        "--json-file", str(claims_file),
        "--now", "2026-03-05T12:00:00Z",  # 10h later
        "--ttl-hours", "24",
    ])
    assert result.returncode == 0
    assert "OK" in result.stdout


def test_zero_balance_claimant_past_ttl_is_expired(tmp_path: Path) -> None:
    """Zero-balance agent's expired claim is flagged identically to a funded agent."""
    claims_file = tmp_path / "claims.json"
    _write_claims(claims_file, [
        {"issue": 7, "agent": "alice@test", "claimed_at": "2026-03-04T00:00:00Z"},
    ])
    result = _run([
        "--json-file", str(claims_file),
        "--now", "2026-03-05T10:00:00Z",  # 34h later
        "--ttl-hours", "24",
    ])
    assert result.returncode == 1
    assert "alice@test" in result.stdout


# ── 5. Re-Claim After Expiry ──────────────────────────────────────────────────
# Decision table (JSON mode, TTL = 24h, now = 2026-03-07T12:00:00Z):
# | issue | agent | claimed_at           | age  | description          | expired? |
# |-------|-------|----------------------|------|----------------------|----------|
# | 1     | alice | 2026-03-06T06:00:00Z | 30h  | original (stale)     | YES      |
# | 1     | bob   | 2026-03-07T02:00:00Z | 10h  | successor            | NO       |
# | 1     | alice | 2026-03-07T10:00:00Z | 2h   | alice re-claim       | NO       |
# Result: FAIL — stale alice entry still present → exit 1
#
# GAP-2: --json-file mode evaluates all entries independently; stale entries
# are not deduped by issue. Callers must supply only live claims.
# In idem_keys mode, get_claim_from_idem_keys returns the latest-timestamp
# claim per issue, so superseded entries are naturally excluded.


def test_reclaim_after_expiry_stale_entry_causes_fail(tmp_path: Path) -> None:
    """Stale original claim in JSON input causes FAIL even when re-claim is fresh.

    GAP-2: JSON mode does not deduplicate by issue; callers must pre-filter.
    """
    claims_file = tmp_path / "claims.json"
    _write_claims(claims_file, [
        {"issue": 1, "agent": "alice@test", "claimed_at": "2026-03-06T06:00:00Z"},  # 30h old
        {"issue": 1, "agent": "bob@test",   "claimed_at": "2026-03-07T02:00:00Z"},  # 10h old
        {"issue": 1, "agent": "alice@test", "claimed_at": "2026-03-07T10:00:00Z"},  # 2h old (re-claim)
    ])
    result = _run([
        "--json-file", str(claims_file),
        "--now", "2026-03-07T12:00:00Z",
        "--ttl-hours", "24",
    ])
    assert result.returncode == 1, "Stale entry must cause FAIL even when re-claim is fresh"
    assert "alice@test" in result.stdout


def test_reclaim_after_expiry_pre_filtered_input_passes(tmp_path: Path) -> None:
    """Caller removes stale entry before checking: only fresh claims remain → exit 0."""
    claims_file = tmp_path / "claims.json"
    # Stale alice entry pruned by caller; only live claims supplied
    _write_claims(claims_file, [
        {"issue": 1, "agent": "bob@test",   "claimed_at": "2026-03-07T02:00:00Z"},  # 10h old
        {"issue": 1, "agent": "alice@test", "claimed_at": "2026-03-07T10:00:00Z"},  # 2h old
    ])
    result = _run([
        "--json-file", str(claims_file),
        "--now", "2026-03-07T12:00:00Z",
        "--ttl-hours", "24",
    ])
    assert result.returncode == 0, "Pre-filtered fresh entries must all pass"
    assert "OK" in result.stdout


# ── 6. Ghost Claim ────────────────────────────────────────────────────────────
# Decision table (issue 9999 absent from any task index, TTL = 24h):
# | issue | task_index | claimed_at           | now                  | expired? |
# |-------|------------|----------------------|----------------------|----------|
# | 9999  | absent     | 2026-03-05T02:00:00Z | 2026-03-05T12:00:00Z | NO  (OK) |
# | 9999  | absent     | 2026-03-04T00:00:00Z | 2026-03-05T10:00:00Z | YES(FAIL)|
#
# GAP-3: The script does not validate issue existence against any task index.
# Ghost claims are TTL-checked like real claims — no existence guard.
# A fresh ghost claim silently passes; an expired ghost claim is flagged as a real
# violation, making it indistinguishable from a legitimate expired claim.


def test_ghost_claim_within_ttl_passes_silently(tmp_path: Path) -> None:
    """Ghost claim (non-existent issue) within TTL passes — no existence check.

    GAP-3: script is unaware of task index; ghost claims are TTL-checked like real ones.
    """
    claims_file = tmp_path / "claims.json"
    _write_claims(claims_file, [
        {"issue": 9999, "agent": "alice@test", "claimed_at": "2026-03-05T02:00:00Z"},
    ])
    result = _run([
        "--json-file", str(claims_file),
        "--now", "2026-03-05T12:00:00Z",
        "--ttl-hours", "24",
    ])
    assert result.returncode == 0
    assert "OK" in result.stdout


def test_ghost_claim_past_ttl_flagged_indistinguishably(tmp_path: Path) -> None:
    """Ghost claim past TTL is flagged with no indication that the issue is phantom.

    GAP-3: output is identical to a real expired claim; caller cannot distinguish.
    """
    claims_file = tmp_path / "claims.json"
    _write_claims(claims_file, [
        {"issue": 9999, "agent": "bob@test", "claimed_at": "2026-03-04T00:00:00Z"},
    ])
    result = _run([
        "--json-file", str(claims_file),
        "--now", "2026-03-05T10:00:00Z",  # 34h later
        "--ttl-hours", "24",
    ])
    assert result.returncode == 1
    assert "FAIL" in result.stdout
    assert "#9999" in result.stdout
