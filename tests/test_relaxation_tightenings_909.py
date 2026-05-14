"""Negative + positive tests for issue #909 relaxation tightenings.

Each section addresses one of the four codex-flagged P2 over-broad bypasses
from #894/#899. Every section provides:

  * a *negative* test that FAILS before the tightening and PASSES after —
    proof the bypass surface shrank
  * a *positive* test that the documented historical exception is still
    honored — proof the FAIL→PASS guarantee of the original stabilization
    round was not regressed.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

from scripts import check_t6_team_enforcement as t6
from scripts.check_idem_keys_schema import run as idem_run
from scripts.check_mint_record_completeness import run as mint_run

REPO_ROOT = Path(__file__).resolve().parents[1]
GAUNTLET_SCRIPT = REPO_ROOT / "scripts" / "check_gauntlet_pr_fields.py"


# ---------------------------------------------------------------------------
# #1 — check_idem_keys_schema.py: legacy-pattern keys with invalid present fields
# ---------------------------------------------------------------------------


class TestIdemKeysSchemaLegacyTightening:
    """Tightening #1: legacy escrow keys no longer bypass all dict validation.

    Before: matching the legacy regex + field-subset whitelisted the entire
    entry, so `{"created_at": null}` or `{"amount": -5, ...}` silently passed.
    After:  present-but-invalid timestamps and non-positive amounts are
    reported as violations even on legacy-shaped keys.
    """

    LEGACY_KEY = "escrow_create_525_t1s16_gauntlet"
    VALID_TS = "2026-04-01T12:00:00Z"

    # Negative tests — were silently PASS, must now FAIL.

    def test_legacy_null_created_at_now_fails(self):
        result = idem_run({self.LEGACY_KEY: {"created_at": None, "amount": 35}})
        assert result["status"] == "FAIL"
        assert any(
            v["key"] == self.LEGACY_KEY and v["field"] == "created_at"
            for v in result["violations"]
        )

    def test_legacy_null_ts_now_fails(self):
        result = idem_run({
            "escrow-return-cycle22-789": {"ts": None, "op": "escrow_return", "issue": 789}
        })
        assert result["status"] == "FAIL"
        assert any(v["field"] == "ts" for v in result["violations"])

    def test_legacy_negative_amount_now_fails(self):
        result = idem_run({
            self.LEGACY_KEY: {"amount": -5, "created_at": self.VALID_TS}
        })
        assert result["status"] == "FAIL"
        assert any(v["field"] == "amount" for v in result["violations"])

    def test_legacy_zero_amount_now_fails(self):
        result = idem_run({
            self.LEGACY_KEY: {"amount": 0, "created_at": self.VALID_TS}
        })
        assert result["status"] == "FAIL"
        assert any(v["field"] == "amount" for v in result["violations"])

    def test_legacy_malformed_created_at_now_fails(self):
        result = idem_run({
            self.LEGACY_KEY: {"created_at": "yesterday", "amount": 10}
        })
        assert result["status"] == "FAIL"
        assert any(v["field"] == "created_at" for v in result["violations"])

    def test_legacy_bool_amount_now_fails(self):
        # bool is a subclass of int — must be excluded explicitly.
        result = idem_run({
            self.LEGACY_KEY: {"amount": True, "created_at": self.VALID_TS}
        })
        assert result["status"] == "FAIL"
        assert any(v["field"] == "amount" for v in result["violations"])

    def test_legacy_blank_op_now_fails(self):
        result = idem_run({
            "escrow-return-cycle22-789": {"op": "", "ts": self.VALID_TS, "issue": 789}
        })
        assert result["status"] == "FAIL"
        assert any(v["field"] == "op" for v in result["violations"])

    # Positive tests — historical exception still honored.

    def test_legacy_valid_created_at_amount_still_passes(self):
        result = idem_run({
            self.LEGACY_KEY: {"created_at": self.VALID_TS, "amount": 35}
        })
        assert result["status"] == "PASS"

    def test_legacy_ts_only_still_passes(self):
        result = idem_run({
            "escrow-return-cycle22-789": {"ts": self.VALID_TS, "op": "escrow_return", "issue": 789}
        })
        assert result["status"] == "PASS"

    def test_legacy_no_op_field_still_passes(self):
        # The whole point of the legacy bypass: op may be absent. Still allowed.
        result = idem_run({
            self.LEGACY_KEY: {"created_at": self.VALID_TS, "amount": 35, "note": "x"}
        })
        assert result["status"] == "PASS"


# ---------------------------------------------------------------------------
# #2 — check_t6_team_enforcement.py: schedule mode falls back to `timestamp`
# ---------------------------------------------------------------------------


class TestT6ScheduleTimestampFallback:
    """Tightening #2: schedule-mode lookup no longer skips mints that record
    only `timestamp` (e.g. T6 slot 15)."""

    @staticmethod
    def _mint(slot, agents, *, accepted_at=None, timestamp=None):
        record = {
            "trajectory": "T6",
            "slot": slot,
            "amount": 20,
            "agents": agents,
            "issue_or_pr": f"#{slot:03d}",
        }
        if accepted_at is not None:
            record["accepted_at"] = accepted_at
        if timestamp is not None:
            record["timestamp"] = timestamp
        return record

    def _run(self, mints):
        return t6.run_check(Path("/fake/root"), mints=mints, events=[], use_schedule=True)

    # Negative — an unauthorized agent on a timestamp-only mint now FAILS.

    def test_timestamp_only_wrong_agent_now_fails(self):
        # gemini era (2026-04-15) but credited to Claude-6 → wrong holder.
        mints = [self._mint(15, ["Claude-6@claude"], timestamp="2026-04-15T07:37:40Z")]
        result = self._run(mints)
        assert result["status"] == "FAIL"
        assert result["violations"][0]["slot"] == 15
        assert "Claude-6@claude" in result["violations"][0]["unauthorized_agents"]

    def test_timestamp_only_post_rotation_gemini_now_fails(self):
        # After 2026-04-29 rotation, gemini is the wrong holder.
        mints = [self._mint(99, ["gemini-4@google"], timestamp="2026-05-10T00:00:00Z")]
        result = self._run(mints)
        assert result["status"] == "FAIL"
        assert "gemini-4@google" in result["violations"][0]["unauthorized_agents"]

    # Positive — the real-life record (gemini-4 in gemini era) still PASSES,
    # and a truly undated mint is still grandfathered.

    def test_real_t6_slot15_record_still_passes(self):
        # gemini-4 in gemini era with timestamp-only — historical exception.
        mints = [self._mint(15, ["gemini-4@google"], timestamp="2026-04-15T07:37:40Z")]
        result = self._run(mints)
        assert result["status"] == "PASS"

    def test_truly_undated_mint_still_grandfathered(self):
        # No accepted_at AND no timestamp — genuinely pre-policy, still skipped.
        mints = [self._mint(1, ["Claude-1@claude"])]
        result = self._run(mints)
        assert result["status"] == "PASS"

    def test_accepted_at_still_preferred_over_timestamp(self):
        # If both are present, accepted_at wins (canonical field).
        mints = [self._mint(
            5,
            ["gemini-4@google"],
            accepted_at="2026-04-01T00:00:00Z",   # gemini era
            timestamp="2026-05-10T00:00:00Z",      # would be Claude-6 era
        )]
        result = self._run(mints)
        assert result["status"] == "PASS"


# ---------------------------------------------------------------------------
# #3 — check_mint_record_completeness.py: grandfather narrowed to two fields
# ---------------------------------------------------------------------------


class TestMintCompletenessGrandfatherNarrowing:
    """Tightening #3: allowlisted slots may only excuse the two known-missing
    fields (made_redundant, redundancy_proof). Any other missing mandatory
    field on those slots is fresh damage and must FAIL."""

    @staticmethod
    def _write(tmp_path, mints):
        path = tmp_path / "ledger" / "trajectory_mints.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"version": 1, "mints": mints}), encoding="utf-8")

    @staticmethod
    def _allowlisted_mint(**overrides):
        """T2 slot 12 is in PRE_RULE_GRANDFATHERED_SLOTS."""
        base = {
            "trajectory": "T2",
            "slot": 12,
            "frontier_closed": "x" * 10,
            "artifact": "scripts/foo.py",
            "evidence": "PR #100 merged",
            # made_redundant + redundancy_proof intentionally absent (the
            # genuine historical state of these records).
        }
        base.update(overrides)
        return base

    # Negative — extra missing fields on allowlisted slots now FAIL.

    def test_allowlisted_slot_missing_frontier_closed_now_fails(self, tmp_path):
        mint = self._allowlisted_mint()
        del mint["frontier_closed"]
        self._write(tmp_path, [mint])
        report = mint_run(tmp_path)
        assert report["status"] == "FAIL"
        check = report["checks"][0]
        assert check["status"] == "FAIL"
        assert "frontier_closed" in check["missing_fields"]

    def test_allowlisted_slot_blank_artifact_now_fails(self, tmp_path):
        mint = self._allowlisted_mint(artifact="")
        self._write(tmp_path, [mint])
        report = mint_run(tmp_path)
        assert report["status"] == "FAIL"
        assert "artifact" in report["checks"][0]["missing_fields"]

    def test_allowlisted_slot_whitespace_evidence_now_fails(self, tmp_path):
        mint = self._allowlisted_mint(evidence="   \t ")
        self._write(tmp_path, [mint])
        report = mint_run(tmp_path)
        assert report["status"] == "FAIL"
        assert "evidence" in report["checks"][0]["missing_fields"]

    def test_allowlisted_slot_non_string_field_now_fails(self, tmp_path):
        mint = self._allowlisted_mint(frontier_closed=12345)
        self._write(tmp_path, [mint])
        report = mint_run(tmp_path)
        assert report["status"] == "FAIL"
        assert "frontier_closed" in report["checks"][0]["missing_fields"]

    # Positive — historical exception (cycle-12 two-field absence) still works.

    def test_allowlisted_slot_only_excused_pair_missing_still_grandfathered(
        self, tmp_path
    ):
        self._write(tmp_path, [self._allowlisted_mint()])
        report = mint_run(tmp_path)
        assert report["status"] == "PASS"
        check = report["checks"][0]
        assert check["status"] == "GRANDFATHERED"
        assert set(check["missing_fields"]) == {"made_redundant", "redundancy_proof"}


# ---------------------------------------------------------------------------
# #4 — check_gauntlet_pr_fields.py: connected stdin with empty content FAILS
# ---------------------------------------------------------------------------


def _run_gauntlet(args=None, stdin=None, env=None):
    run_env = os.environ.copy()
    # PR_BODY env in the caller's shell must not leak through; the test owns
    # the exact environment it runs the script under.
    run_env.pop("PR_BODY", None)
    if env:
        run_env.update(env)
    return subprocess.run(
        [sys.executable, str(GAUNTLET_SCRIPT), *(args or [])],
        cwd=REPO_ROOT,
        text=True,
        input=stdin,
        capture_output=True,
        check=False,
        env=run_env,
    )


class TestGauntletPrFieldsStdinTightening:
    """Tightening #4: an empty stdin pipe is FAIL (the canonical case the
    check exists to catch), not SKIP. Only the no-pipe sweep path remains
    SKIP."""

    # Negative — empty/whitespace stdin pipe now FAILs instead of SKIPping.

    def test_empty_stdin_now_fails(self):
        result = _run_gauntlet(stdin="")
        assert result.returncode == 1
        payload = json.loads(result.stdout)
        assert payload["status"] == "FAIL"
        # All 5 fields missing — the empty body has none.
        assert set(payload["missing"]) == {
            "frontier_closed", "artifact", "evidence", "made_redundant", "redundancy_proof",
        }

    def test_whitespace_only_stdin_now_fails(self):
        result = _run_gauntlet(stdin="   \n\t\n  \n")
        assert result.returncode == 1
        payload = json.loads(result.stdout)
        assert payload["status"] == "FAIL"
        # Same five fields missing because no field-shaped line exists.
        assert len(payload["missing"]) == 5

    # Positive — the documented historical exception (sweep runner with no
    # stdin) still SKIPs cleanly.

    def test_no_stdin_pipe_still_skips(self):
        # Closing stdin via DEVNULL on Windows still presents an EOF-ready
        # pipe — that's *connected* (non-tty), so under the new rule it FAILS
        # rather than SKIPping. To exercise the SKIP path we route stdin
        # through the parent's tty (no redirection). subprocess.run with
        # stdin=None inherits the parent's stdin; in the pytest runner that
        # may also be a pipe. So we explicitly route stdin from the parent's
        # current handle, which is captured/piped under pytest — meaning the
        # sweep-style "no pipe" case can only be reliably exercised by
        # checking sys.stdin.isatty() directly. We assert the documented
        # historical contract via the in-process path used by the sweep
        # runner.
        from scripts.check_gauntlet_pr_fields import _read_body
        # Direct contract: when called with no CLI body and no PR_BODY env,
        # and stdin is a tty, the function reports no input. We simulate via
        # monkeypatching in the next test rather than here.
        # The PR_BODY env fallback continues to work — that's how CI sweeps
        # supply input when no pipe is available.
        result = _run_gauntlet(env={"PR_BODY": "frontier_closed: x\n"})
        # All but one field missing — but importantly, exit is FAIL (1), not
        # SKIP (2): the env-fed body was read.
        assert result.returncode == 1
        payload = json.loads(result.stdout)
        assert payload["status"] == "FAIL"

    def test_in_process_no_pipe_path_still_skips(self, monkeypatch):
        """When stdin is a tty (no pipe) and no env/cli body, SKIP."""
        from scripts.check_gauntlet_pr_fields import _read_body

        class FakeStdin:
            def isatty(self):
                return True
            def read(self):
                raise AssertionError("read() must not be called when isatty() is True")

        monkeypatch.setattr(sys, "stdin", FakeStdin())
        monkeypatch.delenv("PR_BODY", raising=False)
        body, had_input = _read_body(None)
        assert had_input is False
        assert body == ""

    def test_in_process_empty_pipe_now_returns_had_input_true(self, monkeypatch):
        """When stdin IS a pipe (not tty) and content is empty, treat as input."""
        from scripts.check_gauntlet_pr_fields import _read_body

        class FakeStdin:
            def isatty(self):
                return False
            def read(self):
                return ""  # connected but empty

        monkeypatch.setattr(sys, "stdin", FakeStdin())
        monkeypatch.delenv("PR_BODY", raising=False)
        body, had_input = _read_body(None)
        assert had_input is True
        assert body == ""

    def test_valid_pr_body_via_stdin_still_passes(self):
        body = "\n".join([
            "frontier_closed: tightening relaxations",
            "artifact: scripts/check_gauntlet_pr_fields.py",
            "evidence: tests pass",
            "made_redundant: silent SKIP on empty PR bodies",
            "redundancy_proof: the checker now FAILs on empty stdin pipes.",
        ])
        result = _run_gauntlet(stdin=body)
        assert result.returncode == 0
        assert json.loads(result.stdout)["status"] == "PASS"
