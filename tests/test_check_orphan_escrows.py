import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from check_orphan_escrows import run_check


def make_escrows(active: dict) -> dict:
    return {"version": 1, "active": active}


def escrow_entry(amount=25, author="agent0@system"):
    return {"amount": amount, "author": author, "type": "standard", "created_at": "2026-01-01T00:00:00Z"}


class TestRunCheck(unittest.TestCase):
    def test_all_open_escrows_pass(self):
        escrows = make_escrows({"100": escrow_entry(), "101": escrow_entry()})
        result = run_check(escrows, "token", fetch_fn=lambda _: "open")
        self.assertTrue(result["passed"])
        self.assertEqual(result["orphans"], [])
        self.assertEqual(result["total_checked"], 2)

    def test_closed_issue_is_orphan(self):
        escrows = make_escrows({"200": escrow_entry(amount=38)})
        states = {"200": "closed"}
        result = run_check(escrows, "token", fetch_fn=lambda n: states[str(n)])
        self.assertFalse(result["passed"])
        self.assertEqual(len(result["orphans"]), 1)
        self.assertEqual(result["orphans"][0]["issue"], 200)
        self.assertEqual(result["orphans"][0]["state"], "closed")
        self.assertEqual(result["orphans"][0]["amount"], 38)

    def test_empty_escrows_pass(self):
        result = run_check(make_escrows({}), "token", fetch_fn=lambda _: "open")
        self.assertTrue(result["passed"])
        self.assertEqual(result["total_checked"], 0)

    def test_multiple_orphans_all_reported(self):
        escrows = make_escrows({
            "300": escrow_entry(25),
            "301": escrow_entry(38),
            "302": escrow_entry(41),
        })
        result = run_check(escrows, "token", fetch_fn=lambda _: "closed")
        self.assertFalse(result["passed"])
        self.assertEqual(len(result["orphans"]), 3)

    def test_not_found_issue_is_orphan(self):
        escrows = make_escrows({"999": escrow_entry()})
        result = run_check(escrows, "token", fetch_fn=lambda _: "not_found")
        self.assertFalse(result["passed"])
        self.assertEqual(result["orphans"][0]["state"], "not_found")

    def test_api_error_reported_in_errors(self):
        def raise_error(n):
            raise ConnectionError("API timeout")
        escrows = make_escrows({"400": escrow_entry()})
        result = run_check(escrows, "token", fetch_fn=raise_error)
        self.assertFalse(result["passed"])
        self.assertEqual(len(result["errors"]), 1)
        self.assertIn("API timeout", result["errors"][0]["error"])

    def test_mixed_open_and_closed(self):
        escrows = make_escrows({
            "500": escrow_entry(25),
            "501": escrow_entry(38),
            "502": escrow_entry(10),
        })
        states = {"500": "open", "501": "closed", "502": "open"}
        result = run_check(escrows, "token", fetch_fn=lambda n: states[str(n)])
        self.assertFalse(result["passed"])
        self.assertEqual(len(result["orphans"]), 1)
        self.assertEqual(result["orphans"][0]["issue"], 501)

    def test_orphan_includes_author(self):
        escrows = make_escrows({"600": escrow_entry(author="agent0@system")})
        result = run_check(escrows, "token", fetch_fn=lambda _: "closed")
        self.assertEqual(result["orphans"][0]["author"], "agent0@system")

    def test_result_has_required_keys(self):
        result = run_check(make_escrows({}), "token", fetch_fn=lambda _: "open")
        self.assertIn("passed", result)
        self.assertIn("orphans", result)
        self.assertIn("errors", result)
        self.assertIn("total_checked", result)

    def test_partial_api_error_marks_failed(self):
        def fetch_fn(n):
            if n == 700:
                raise RuntimeError("network error")
            return "open"
        escrows = make_escrows({"700": escrow_entry(), "701": escrow_entry()})
        result = run_check(escrows, "token", fetch_fn=fetch_fn)
        self.assertFalse(result["passed"])
        self.assertEqual(len(result["errors"]), 1)
        self.assertEqual(result["errors"][0]["issue"], 700)

    def test_large_amount_orphan_reported_correctly(self):
        escrows = make_escrows({"800": escrow_entry(amount=1000)})
        result = run_check(escrows, "token", fetch_fn=lambda _: "closed")
        self.assertEqual(result["orphans"][0]["amount"], 1000)


if __name__ == "__main__":
    unittest.main()
