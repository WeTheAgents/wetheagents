import json
import os
import shutil
import subprocess
import sys
import uuid
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from check_idem_key_format import is_known, run_check


def make_idem(keys: list[str]) -> dict:
    return {"version": 1, "keys": {k: "2026-01-01T00:00:00Z" for k in keys}}


class TestIsKnown(unittest.TestCase):
    def test_register(self):
        self.assertTrue(is_known("register|Claude-1@claude"))

    def test_trajectory_mint(self):
        self.assertTrue(is_known("trajectory_mint|T3|19"))

    def test_escrow_create_gauntlet(self):
        self.assertTrue(is_known("escrow_create_610_t3_gauntlet"))

    def test_escrow_create_gauntlet_dashed_cycle(self):
        self.assertTrue(is_known("escrow-create-gauntlet-cycle20-741"))

    def test_escrow_create_transitional_dash(self):
        self.assertTrue(is_known("escrow_create-765"))

    def test_escrow_create_pipe_issue(self):
        self.assertTrue(is_known("escrow_create|812"))

    def test_escrow_return_short(self):
        self.assertTrue(is_known("escrow_return|610"))

    def test_escrow_return_with_agent(self):
        self.assertTrue(is_known("escrow_return|107|agent0@system"))

    def test_escrow_return_with_reason(self):
        self.assertTrue(is_known("escrow_return|130|agent0@system|reconcile"))

    def test_claim(self):
        self.assertTrue(is_known("claim|42|Claude-1@claude"))

    def test_accept(self):
        self.assertTrue(is_known("accept|42|Claude-1@claude"))

    def test_accept_with_slot(self):
        self.assertTrue(is_known("accept|5|gemini-4@google|slot1"))

    def test_verify(self):
        self.assertTrue(is_known("verify|42|Claude-1@claude"))

    def test_payment_simple(self):
        self.assertTrue(is_known("payment|42|Claude-1@claude"))

    def test_payment_with_role(self):
        self.assertTrue(is_known("payment|42|Claude-1@claude|winner"))

    def test_payment_with_ranking(self):
        self.assertTrue(is_known("payment|109|Codex-2@codex|ranking|1"))

    def test_reject(self):
        self.assertTrue(is_known("reject|42|Claude-1@claude"))

    def test_settle(self):
        self.assertTrue(is_known("settle|42|Claude-1@claude"))

    def test_cleanup_bare(self):
        self.assertTrue(is_known("cleanup"))

    def test_cleanup_with_suffix(self):
        self.assertTrue(is_known("cleanup|escrow_return|old_cycle"))

    def test_hello_world_bare(self):
        self.assertTrue(is_known("hello_world"))

    def test_hello_world_with_agent(self):
        self.assertTrue(is_known("hello_world|gemini-4@google"))

    def test_join_with_agent(self):
        self.assertTrue(is_known("join|16|cursor-3@cursor"))

    def test_create_task_bare(self):
        self.assertTrue(is_known("create_task"))

    def test_create_task_with_issue(self):
        self.assertTrue(is_known("create_task|209"))

    def test_legacy_escrow_create(self):
        self.assertTrue(is_known("escrow|107|agent0@system"))

    def test_legacy_escrow_create_with_reason(self):
        self.assertTrue(is_known("escrow|70|agent0@system|v2"))

    def test_legacy_heartbeat_escrow_create(self):
        self.assertTrue(is_known("escrow-create-597"))

    def test_legacy_heartbeat_escrow_return(self):
        self.assertTrue(is_known("escrow-return-cycle10-601"))

    def test_legacy_orphan_escrow_return(self):
        self.assertTrue(is_known("escrow_return_486_t3s10_orphan"))

    def test_sha256_hash_key(self):
        self.assertTrue(is_known("30c1b897d9132a8e3cfebc0ae11f6332861a3bce12ba5354420e19aae469ff50"))

    def test_unknown_random_string(self):
        self.assertFalse(is_known("totally_random_key"))

    def test_unknown_bare_escrow_return(self):
        self.assertFalse(is_known("escrow_return"))

    def test_unknown_partial_trajectory_mint(self):
        self.assertFalse(is_known("trajectory_mint|T1"))

    def test_unknown_spaces_in_key(self):
        self.assertFalse(is_known("register| Claude-1@claude"))

    def test_unknown_empty_string(self):
        self.assertFalse(is_known(""))


class TestRunCheck(unittest.TestCase):
    def test_all_valid_passes(self):
        keys = ["register|Claude-1@claude", "trajectory_mint|T1|21", "claim|5|Claude-1@claude"]
        result = run_check(make_idem(keys))
        self.assertTrue(result["passed"])
        self.assertEqual(result["unknown_keys"], [])
        self.assertEqual(result["total_checked"], 3)

    def test_unknown_key_fails(self):
        keys = ["register|Claude-1@claude", "bad_key_format"]
        result = run_check(make_idem(keys))
        self.assertFalse(result["passed"])
        self.assertIn("bad_key_format", result["unknown_keys"])
        self.assertEqual(result["total_checked"], 2)

    def test_empty_idem_keys_passes(self):
        result = run_check({"version": 1, "keys": {}})
        self.assertTrue(result["passed"])
        self.assertEqual(result["total_checked"], 0)

    def test_mixed_valid_invalid_reports_unknown(self):
        keys = ["register|Claude-1@claude", "???invalid???", "trajectory_mint|T2|5", "another::bad"]
        result = run_check(make_idem(keys))
        self.assertFalse(result["passed"])
        self.assertEqual(sorted(result["unknown_keys"]), sorted(["???invalid???", "another::bad"]))
        self.assertEqual(result["total_checked"], 4)

    def test_all_legacy_formats_pass(self):
        keys = [
            "escrow|107|agent0@system",
            "escrow-create-597",
            "escrow-return-cycle10-601",
            "30c1b897d9132a8e3cfebc0ae11f6332861a3bce12ba5354420e19aae469ff50",
        ]
        result = run_check(make_idem(keys))
        self.assertTrue(result["passed"])


class TestCLI(unittest.TestCase):
    def _run_with_ledger(self, keys: list[str]) -> tuple[int, dict]:
        tmp_path = Path.cwd() / ".tmp-tests" / f"idem-format-{uuid.uuid4().hex}"
        try:
            ledger_dir = tmp_path / "ledger"
            ledger_dir.mkdir(parents=True)
            idem = {"version": 1, "keys": {k: "2026-01-01T00:00:00Z" for k in keys}}
            (ledger_dir / "idem_keys.json").write_text(json.dumps(idem))
            script = Path(__file__).parent.parent / "scripts" / "check_idem_key_format.py"
            env = {**os.environ, "PYTHONPATH": str(Path(__file__).parent.parent / "scripts")}
            result = subprocess.run(
                [sys.executable, str(script), "--root", str(tmp_path)],
                capture_output=True, text=True, cwd=tmp_path, env=env
            )
            output = json.loads(result.stdout)
            return result.returncode, output
        finally:
            shutil.rmtree(tmp_path, ignore_errors=True)

    def test_exit_0_on_clean_ledger(self):
        code, _ = self._run_with_ledger(["register|Claude-1@claude", "trajectory_mint|T1|1"])
        self.assertEqual(code, 0)

    def test_exit_1_on_unknown_key(self):
        code, output = self._run_with_ledger(["register|Claude-1@claude", "corrupted:key"])
        self.assertEqual(code, 1)
        self.assertIn("corrupted:key", output["unknown_keys"])

    def test_json_output_structure(self):
        _, output = self._run_with_ledger(["register|Claude-1@claude"])
        self.assertIn("passed", output)
        self.assertIn("unknown_keys", output)
        self.assertIn("total_checked", output)


if __name__ == "__main__":
    unittest.main()
