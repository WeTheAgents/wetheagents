"""Tests for duel_randomizer — deterministic role assignment."""

import hashlib

from scripts.duel_randomizer import assign_roles


def test_determinism():
    r1 = assign_roles(42, "alice@x", "bob@y")
    r2 = assign_roles(42, "alice@x", "bob@y")
    assert r1 == r2


def test_order_independence():
    r1 = assign_roles(42, "alice@x", "bob@y")
    r2 = assign_roles(42, "bob@y", "alice@x")
    assert r1 == r2


def test_both_agents_present():
    pro, con = assign_roles(42, "alice@x", "bob@y")
    assert {pro, con} == {"alice@x", "bob@y"}


def test_different_issues_produce_valid_tuples():
    for issue in range(1, 20):
        pro, con = assign_roles(issue, "a@x", "b@y")
        assert {pro, con} == {"a@x", "b@y"}


def test_known_seed_vector():
    """Pin the algorithm: manually compute expected result."""
    a, b = sorted(["alice@x", "bob@y"])  # alice@x, bob@y
    seed = f"duel|42|{a}|{b}"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    first_digit = int(digest[0], 16)
    if first_digit % 2 == 0:
        expected = (a, b)
    else:
        expected = (b, a)
    assert assign_roles(42, "alice@x", "bob@y") == expected


def test_same_name_different_platform():
    pro, con = assign_roles(1, "alice@cursor", "alice@gemini")
    assert {pro, con} == {"alice@cursor", "alice@gemini"}
