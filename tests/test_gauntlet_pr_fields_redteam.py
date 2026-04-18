import pytest
from scripts.check_gauntlet_pr_fields import evaluate_pr_body

def test_bypass_empty_strings():
    """Attack vector: All 5 fields present but all values are empty strings."""
    body = """
frontier_closed:
artifact:
evidence:
made_redundant:
redundancy_proof:
"""
    res = evaluate_pr_body(body)
    assert res["status"] == "FAIL"
    assert len(res["empty"]) == 5

def test_bypass_whitespace_only():
    """Attack vector: All 5 fields present but values are whitespace-only."""
    body = """
frontier_closed:   
artifact: \t
evidence: \n
made_redundant:  
redundancy_proof: \t
"""
    res = evaluate_pr_body(body)
    assert res["status"] == "FAIL"
    assert len(res["empty"]) == 5

def test_bypass_headers_no_value():
    """Attack vector: Fields present in PR body as headers but with no value after colon."""
    body = """
frontier_closed: 
artifact: 
evidence: 
made_redundant: 
redundancy_proof: 
"""
    res = evaluate_pr_body(body)
    assert res["status"] == "FAIL"
    assert len(res["empty"]) == 5

def test_bypass_na_placeholder():
    """Attack vector: frontier_closed contains only the literal string 'N/A'."""
    body = """
frontier_closed: N/A
artifact: https://example.com/artifact
evidence: https://example.com/evidence
made_redundant: https://example.com/made_redundant
redundancy_proof: https://example.com/redundancy_proof
"""
    res = evaluate_pr_body(body)
    assert res["status"] == "FAIL"
    assert "frontier_closed" in res["empty"]

def test_bypass_short_value():
    """Attack vector: Field values below minimum length threshold (e.g. 1-character values)."""
    body = """
frontier_closed: a
artifact: b
evidence: c
made_redundant: d
redundancy_proof: e
"""
    res = evaluate_pr_body(body)
    assert res["status"] == "FAIL"
    assert len(res["empty"]) == 5

def test_bypass_unrelated_text():
    """Attack vector: PR body contains the field names as part of unrelated text not as structured fields."""
    body = """
    This PR is very important. The frontier_closed is important.
    The artifact is located here.
    I have evidence to support this.
    It made_redundant the other system.
    This is my redundancy_proof.
    """
    res = evaluate_pr_body(body)
    assert res["status"] == "FAIL"
    assert len(res["missing"]) == 5
