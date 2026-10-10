"""Orchestration negatives; existing ledger tests cover full replay semantics."""

from copy import deepcopy

import pytest

from scripts import tide_merge_preflight as gate
from wea_vnext.tide.collection import REPOSITORY
from wea_vnext.tide.replay import ReplayError


@pytest.fixture
def harness(monkeypatch, tmp_path):
    pr = {
        "state": "open",
        "draft": False,
        "merged": False,
        "base": {"repo": {"full_name": REPOSITORY}, "ref": "main", "sha": "a" * 40},
        "head": {
            "repo": {"full_name": REPOSITORY},
            "ref": "tide/pending",
            "sha": "b" * 40,
        },
    }

    class API:
        def __init__(self):
            self.main = "a" * 40
            self.run = {
                "status": "completed",
                "conclusion": "success",
                "run_attempt": 1,
            }
            self.latest = None
            self.reads = 0

        def get(self, path):
            if "/pulls/" in path:
                self.reads += 1
                return deepcopy(pr)
            if "/actions/runs/" in path:
                if "/attempts/" not in path and self.latest is not None:
                    return self.latest
                return self.run
            return {"object": {"sha": self.main}}

    api = API()
    monkeypatch.setattr(gate, "git", lambda *args: "a" * 40)
    monkeypatch.setattr(gate, "validate", lambda *args, **kw: {"sequence": 30})
    monkeypatch.setattr(
        gate, "read", lambda *args: {"provenance": {"run_id": "10", "run_attempt": "1"}}
    )

    def check(number=1058):
        return gate.inspect(tmp_path, api, number, base="a" * 40, head="b" * 40)

    return pr, api, check


def test_read_only_result(harness):
    _, api, check = harness
    assert check()["mode"] == "read-only"
    assert api.reads == 2


@pytest.mark.parametrize(
    "field,value", [("state", "closed"), ("draft", True), ("merged", True)]
)
def test_ineligible_pr(harness, field, value):
    pr, _, check = harness
    pr[field] = value
    with pytest.raises(ReplayError):
        check()


@pytest.mark.parametrize(
    "side,field,value",
    [
        ("head", "ref", "feature"),
        ("base", "ref", "develop"),
        ("head", "sha", "c" * 40),
        ("base", "sha", "c" * 40),
        ("head", "repo", {"full_name": "other/fork"}),
        ("base", "repo", {"full_name": "other/repo"}),
    ],
)
def test_identity_mismatch(harness, side, field, value):
    pr, _, check = harness
    pr[side][field] = value
    with pytest.raises(ReplayError):
        check()


def test_old_candidate(harness):
    with pytest.raises(ReplayError, match="predates"):
        harness[2](1056)


def test_failed_replay(harness, monkeypatch):
    def fail(*args, **kwargs):
        raise ReplayError("replay failed")

    monkeypatch.setattr(gate, "validate", fail)
    with pytest.raises(ReplayError, match="replay failed"):
        harness[2]()


def test_main_race(harness, monkeypatch):
    _, api, check = harness

    def move(*args, **kwargs):
        api.main = "c" * 40
        return {"sequence": 30}

    monkeypatch.setattr(gate, "validate", move)
    with pytest.raises(ReplayError, match="advanced"):
        check()


def test_head_race(harness, monkeypatch):
    pr, _, check = harness

    def move(*args, **kwargs):
        pr["head"]["sha"] = "c" * 40
        return {"sequence": 30}

    monkeypatch.setattr(gate, "validate", move)
    with pytest.raises(ReplayError, match="exact"):
        check()


def test_producer_failed(harness):
    _, api, check = harness
    api.run = {"status": "completed", "conclusion": "failure"}
    with pytest.raises(ReplayError, match="producer"):
        check()


def test_old_success_cannot_hide_new_attempt(harness):
    _, api, check = harness
    api.latest = {"status": "completed", "conclusion": "failure", "run_attempt": 2}
    with pytest.raises(ReplayError, match="obsolete"):
        check()


def test_guarded_request_returns_only_the_guarded_identity(harness):
    _, api, _ = harness
    assert gate.guarded_request(
        api, 1065, base="a" * 40, head="b" * 40, floor=1064
    ) == {
        "number": 1065,
        "base": "a" * 40,
        "head": "b" * 40,
    }


@pytest.mark.parametrize("side", ["base", "head"])
def test_guarded_request_rejects_movement_after_guard(harness, side):
    pr, api, _ = harness
    pr[side]["sha"] = "c" * 40
    with pytest.raises(ReplayError, match="successful guard outputs"):
        gate.guarded_request(api, 1065, base="a" * 40, head="b" * 40, floor=1064)


def test_guarded_request_rejects_main_movement(harness):
    _, api, _ = harness
    api.main = "c" * 40
    with pytest.raises(ReplayError, match="successful guard outputs"):
        gate.guarded_request(api, 1065, base="a" * 40, head="b" * 40, floor=1064)


def test_guarded_request_skips_old_rollout_without_lookup(harness):
    _, api, _ = harness
    assert (
        gate.guarded_request(api, 1064, base="a" * 40, head="b" * 40, floor=1064)
        is None
    )
    assert api.reads == 0


@pytest.mark.parametrize("foreign", [False, True])
def test_non_tide_guard_cannot_select_another_pending_pr(harness, foreign):
    pr, api, _ = harness
    if foreign:
        pr["head"]["repo"]["full_name"] = "other/repository"
    else:
        pr["head"]["ref"] = "feature"
    assert (
        gate.guarded_request(api, 1065, base="a" * 40, head="b" * 40, floor=1064)
        is None
    )
    assert api.reads == 1


@pytest.mark.parametrize("head", ["", "main", "b" * 39, "x" * 40])
def test_invalid_guard_output_cannot_read_or_write(harness, head):
    _, api, _ = harness
    with pytest.raises(ReplayError, match="invalid guard output"):
        gate.guarded_request(api, 1065, base="a" * 40, head=head, floor=1064)
    assert api.reads == 0
