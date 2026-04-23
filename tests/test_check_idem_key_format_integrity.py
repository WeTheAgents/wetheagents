"""Tests for scripts/check_idem_key_format_integrity.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.check_idem_key_format_integrity import (
    build_report,
    classify_key,
    collect_keys,
)


# ---------------------------------------------------------------------------
# classify_key — valid paths (one per category)
# ---------------------------------------------------------------------------

class TestClassifyKeyValid:
    def test_accept_basic(self):
        kind, cat = classify_key("accept|123|Agent-1@claude")
        assert kind == "valid"
        assert cat == "accept"

    def test_accept_with_qualifier(self):
        # Optional trailing slot qualifier must be allowed
        kind, cat = classify_key("accept|5|gemini-4@google|slot1")
        assert kind == "valid"
        assert cat == "accept"

    def test_escrow_create(self):
        kind, cat = classify_key("escrow_create|99")
        assert kind == "valid"
        assert cat == "escrow_create"

    def test_escrow_return(self):
        kind, cat = classify_key("escrow-return-10-597")
        assert kind == "valid"
        assert cat == "escrow_return"

    def test_gauntlet(self):
        kind, cat = classify_key("gauntlet-T1-S10-agent@platform")
        assert kind == "valid"
        assert cat == "gauntlet"

    def test_gauntlet_hyphen_in_agent(self):
        # Agent names like gemini-4@google have hyphens — must still classify correctly
        kind, cat = classify_key("gauntlet-T2-S5-gemini-4@google")
        assert kind == "valid"
        assert cat == "gauntlet"

    def test_register(self):
        kind, cat = classify_key("register|Claude-1@claude")
        assert kind == "valid"
        assert cat == "register"

    def test_escrow_create_large_issue(self):
        kind, cat = classify_key("escrow_create|99999")
        assert kind == "valid"
        assert cat == "escrow_create"

    def test_escrow_return_large_values(self):
        kind, cat = classify_key("escrow-return-20-1000")
        assert kind == "valid"
        assert cat == "escrow_return"


# ---------------------------------------------------------------------------
# classify_key — malformed paths
# ---------------------------------------------------------------------------

class TestClassifyKeyMalformed:
    # accept: non-integer issue
    def test_accept_non_integer_issue(self):
        kind, reason = classify_key("accept|abc|Agent@claude")
        assert kind == "malformed"
        assert "positive integer" in reason

    # accept: empty issue segment
    def test_accept_empty_issue_segment(self):
        kind, reason = classify_key("accept||Agent@claude")
        assert kind == "malformed"
        assert "empty" in reason.lower()

    # accept: agent missing @
    def test_accept_agent_no_at(self):
        kind, reason = classify_key("accept|123|NoAtAgent")
        assert kind == "malformed"
        assert "@" in reason

    # accept: missing agent segment (only 2 pipe-parts)
    def test_accept_missing_agent_segment(self):
        kind, reason = classify_key("accept|123")
        assert kind == "malformed"

    # accept: zero issue is not a positive integer
    def test_accept_zero_issue(self):
        kind, reason = classify_key("accept|0|Agent@claude")
        assert kind == "malformed"
        assert "positive integer" in reason

    # register: agent missing @
    def test_register_agent_no_at(self):
        kind, reason = classify_key("register|NoAtAgent")
        assert kind == "malformed"
        assert "@" in reason

    # register: empty agent
    def test_register_empty_agent(self):
        kind, reason = classify_key("register|")
        assert kind == "malformed"

    # register: extra pipe segment
    def test_register_extra_pipe(self):
        kind, reason = classify_key("register|Agent@claude|extra")
        assert kind == "malformed"
        assert "extra" in reason.lower() or "|" in reason

    # escrow_create: non-integer issue
    def test_escrow_create_non_integer(self):
        kind, reason = classify_key("escrow_create|abc")
        assert kind == "malformed"
        assert "positive integer" in reason

    # escrow_create: zero issue
    def test_escrow_create_zero(self):
        kind, reason = classify_key("escrow_create|0")
        assert kind == "malformed"
        assert "positive integer" in reason

    # escrow_create: missing issue
    def test_escrow_create_empty_issue(self):
        kind, reason = classify_key("escrow_create|")
        assert kind == "malformed"
        assert "missing" in reason.lower()

    # escrow_create: too many pipe segments (>3)
    def test_escrow_create_too_many_pipes(self):
        kind, reason = classify_key("escrow_create|123|slug|toomany")
        assert kind == "malformed"
        assert "too many" in reason.lower()

    # escrow_create: optional slug (|slug) is valid — verify it is NOT malformed
    def test_escrow_create_with_slug_is_valid(self):
        kind, cat = classify_key("escrow_create|753|self-discovery-claude-14")
        assert kind == "valid"
        assert cat == "escrow_create"

    # escrow-return: non-integer issue (triggers because digit follows prefix)
    def test_escrow_return_non_integer_issue(self):
        kind, reason = classify_key("escrow-return-10-abc")
        assert kind == "malformed"
        assert "positive integer" in reason

    # escrow-return: extra segment after cycle-issue
    def test_escrow_return_extra_segment(self):
        kind, reason = classify_key("escrow-return-10-20-30")
        assert kind == "malformed"

    # escrow-return: zero cycle
    def test_escrow_return_zero_cycle(self):
        kind, reason = classify_key("escrow-return-0-597")
        assert kind == "malformed"
        assert "positive integer" in reason

    # gauntlet: agent missing @
    def test_gauntlet_agent_no_at(self):
        kind, reason = classify_key("gauntlet-T1-S10-NoAtAgent")
        assert kind == "malformed"
        assert "@" in reason

    # gauntlet: malformed structure (missing S segment)
    def test_gauntlet_missing_slot(self):
        kind, reason = classify_key("gauntlet-T1-NoSlot-agent@platform")
        assert kind == "malformed"


# ---------------------------------------------------------------------------
# classify_key — unknown paths (no prefix match → not a failure)
# ---------------------------------------------------------------------------

class TestClassifyKeyUnknown:
    def test_unknown_cycle_return(self):
        # "escrow-return-cycle10-597" — non-digit after prefix → UNKNOWN, not malformed
        kind, detail = classify_key("escrow-return-cycle10-597")
        assert kind == "unknown"
        assert detail is None

    def test_unknown_escrow_create_underscore_variant(self):
        # "escrow_create_" uses underscores throughout — not the pipe variant
        kind, _ = classify_key("escrow_create_496_t1s13_gauntlet")
        assert kind == "unknown"

    def test_unknown_sha256_hash(self):
        kind, _ = classify_key("a" * 64)
        assert kind == "unknown"

    def test_unknown_trajectory_mint(self):
        kind, _ = classify_key("trajectory_mint|T1|10")
        assert kind == "unknown"

    def test_unknown_gauntlet_non_digit_after_t(self):
        # "gauntlet-Tabc..." — not digit after T → UNKNOWN
        kind, _ = classify_key("gauntlet-Tabc-S1-agent@x")
        assert kind == "unknown"

    def test_unknown_plain_escrow(self):
        kind, _ = classify_key("escrow|123|agent0@system")
        assert kind == "unknown"

    def test_unknown_claim(self):
        kind, _ = classify_key("claim|109|Claude-1@claude")
        assert kind == "unknown"

    def test_unknown_payment(self):
        kind, _ = classify_key("payment|109|Codex-2@codex|ranking|1")
        assert kind == "unknown"

    def test_unknown_empty_string(self):
        kind, _ = classify_key("")
        assert kind == "unknown"


# ---------------------------------------------------------------------------
# collect_keys — flattening logic
# ---------------------------------------------------------------------------

class TestCollectKeys:
    def test_skips_version_and_keys_metadata(self):
        data = {
            "version": 5,
            "keys": {"nested_key": "v"},
            "real|key": "v",
        }
        result = collect_keys(data)
        assert "version" not in result
        assert "keys" not in result
        assert "real|key" in result
        assert "nested_key" in result

    def test_includes_nested_keys_wrapper(self):
        data = {"keys": {"a|1|x@y": "v", "b|2|z@w": "v"}}
        result = collect_keys(data)
        assert "a|1|x@y" in result
        assert "b|2|z@w" in result

    def test_no_keys_wrapper(self):
        data = {"register|A@b": "v", "version": 1}
        result = collect_keys(data)
        assert result == ["register|A@b"]

    def test_empty_data(self):
        assert collect_keys({}) == []


# ---------------------------------------------------------------------------
# build_report — integration via tmp_path
# ---------------------------------------------------------------------------

class TestBuildReport:
    def _write_idem(self, tmp_path: Path, data: dict) -> None:
        ledger = tmp_path / "ledger"
        ledger.mkdir()
        (ledger / "idem_keys.json").write_text(json.dumps(data))

    def test_pass_on_empty_file(self, tmp_path: Path):
        self._write_idem(tmp_path, {})
        report = build_report(tmp_path)
        assert report["status"] == "pass"
        assert report["totals"]["total"] == 0
        assert report["totals"]["malformed"] == 0

    def test_pass_all_valid_keys(self, tmp_path: Path):
        self._write_idem(tmp_path, {
            "accept|123|Agent@claude": "2026-01-01T00:00:00Z",
            "register|Claude-1@claude": "2026-01-01T00:00:00Z",
        })
        report = build_report(tmp_path)
        assert report["status"] == "pass"
        assert report["totals"]["valid"] == 2
        assert report["totals"]["malformed"] == 0
        assert report["by_category"]["accept"] == 1
        assert report["by_category"]["register"] == 1

    def test_fail_on_malformed_key(self, tmp_path: Path):
        self._write_idem(tmp_path, {
            "accept|notanint|Agent@claude": "2026-01-01T00:00:00Z",
        })
        report = build_report(tmp_path)
        assert report["status"] == "fail"
        assert report["totals"]["malformed"] == 1
        assert report["malformed_keys"][0]["key"] == "accept|notanint|Agent@claude"
        assert "positive integer" in report["malformed_keys"][0]["reason"]

    def test_unknown_keys_do_not_cause_failure(self, tmp_path: Path):
        self._write_idem(tmp_path, {
            "trajectory_mint|T1|10": "2026-01-01T00:00:00Z",
            "some_random_key": "value",
        })
        report = build_report(tmp_path)
        assert report["status"] == "pass"
        assert report["totals"]["unknown"] == 2
        assert report["totals"]["malformed"] == 0

    def test_version_and_keys_metadata_excluded(self, tmp_path: Path):
        self._write_idem(tmp_path, {
            "version": 5,
            "keys": {"accept|10|A@b": "ts"},
            "register|x@y": "ts",
        })
        report = build_report(tmp_path)
        assert report["status"] == "pass"
        # version and "keys" string are skipped; nested accept and register are checked
        assert report["totals"]["valid"] == 2
        assert report["by_category"]["accept"] == 1
        assert report["by_category"]["register"] == 1

    def test_mixed_valid_malformed_unknown(self, tmp_path: Path):
        self._write_idem(tmp_path, {
            "accept|1|A@b": "ts",                   # valid
            "accept|abc|A@b": "ts",                 # malformed
            "trajectory_mint|T1|10": "ts",          # unknown
        })
        report = build_report(tmp_path)
        assert report["status"] == "fail"
        assert report["totals"]["valid"] == 1
        assert report["totals"]["malformed"] == 1
        assert report["totals"]["unknown"] == 1

    def test_file_not_found(self, tmp_path: Path):
        report = build_report(tmp_path)
        assert report["status"] == "fail"
        assert "not found" in report.get("error", "")

    def test_invalid_json(self, tmp_path: Path):
        ledger = tmp_path / "ledger"
        ledger.mkdir()
        (ledger / "idem_keys.json").write_text("{invalid json")
        report = build_report(tmp_path)
        assert report["status"] == "fail"
        assert "parse error" in report.get("error", "").lower()

    def test_unknown_sample_capped_at_limit(self, tmp_path: Path):
        data = {f"unknown_key_{i}": "ts" for i in range(30)}
        self._write_idem(tmp_path, data)
        report = build_report(tmp_path)
        assert report["status"] == "pass"
        assert len(report["unknown_sample"]) == 20
        assert report["totals"]["unknown"] == 30

    def test_escrow_return_digit_variant_is_valid(self, tmp_path: Path):
        self._write_idem(tmp_path, {
            "escrow-return-10-597": "ts",
        })
        report = build_report(tmp_path)
        assert report["status"] == "pass"
        assert report["by_category"]["escrow_return"] == 1

    def test_escrow_return_cycle_variant_is_unknown(self, tmp_path: Path):
        # "escrow-return-cycle10-597" must NOT be classified as malformed — it's UNKNOWN
        self._write_idem(tmp_path, {
            "escrow-return-cycle10-597": "ts",
        })
        report = build_report(tmp_path)
        assert report["status"] == "pass"
        assert report["totals"]["unknown"] == 1
        assert report["totals"]["malformed"] == 0

    def test_gauntlet_key_valid(self, tmp_path: Path):
        self._write_idem(tmp_path, {
            "gauntlet-T1-S10-agent@platform": "ts",
        })
        report = build_report(tmp_path)
        assert report["status"] == "pass"
        assert report["by_category"]["gauntlet"] == 1

    def test_live_repo_exits_pass(self):
        root = Path(__file__).resolve().parent.parent
        report = build_report(root)
        assert report["status"] == "pass", (
            f"Live repo has malformed idem keys: {report['malformed_keys']}"
        )
        assert report["totals"]["malformed"] == 0
