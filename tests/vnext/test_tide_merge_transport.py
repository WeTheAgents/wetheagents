"""Offline REST orchestration proof; no live credentials or ledger effects."""

import hashlib
import http.client
import json
from copy import deepcopy
from pathlib import Path

import pytest

from scripts import tide_merge as transport
from wea_vnext.tide.collection import REPOSITORY
from wea_vnext.tide.github import GitHubError
from wea_vnext.tide.replay import ReplayError, canonical

BASE, HEAD, MERGE = "a" * 40, "b" * 40, "c" * 40


@pytest.fixture
def setup(monkeypatch, tmp_path):
    class Service:
        def __init__(self):
            self.pr = {
                "state": "open",
                "draft": False,
                "merged": False,
                "base": {"repo": {"full_name": REPOSITORY}, "sha": BASE, "ref": "main"},
                "head": {
                    "repo": {"full_name": REPOSITORY},
                    "sha": HEAD,
                    "ref": "tide/pending",
                },
                "merge_commit_sha": MERGE,
            }
            self.main = BASE
            self.rules = [
                {"type": kind}
                for kind in ("update", "pull_request", "non_fast_forward", "deletion")
            ]
            self.rules.append(
                {
                    "type": "required_status_checks",
                    "parameters": {
                        "strict_required_status_checks_policy": True,
                        "required_status_checks": [
                            {"context": "tide/replay", "integration_id": 12}
                        ],
                    },
                }
            )
            for rule in self.rules:
                rule["ruleset_id"] = 1 if rule["type"] == "update" else 2
            self.policies = {}
            for identifier in (1, 2):
                self.policies[identifier] = {
                    "id": identifier,
                    "target": "branch",
                    "source_type": "Repository",
                    "source": REPOSITORY,
                    "enforcement": "active",
                    "conditions": {
                        "ref_name": {"include": ["refs/heads/main"], "exclude": []}
                    },
                    "rules": [
                        {k: v for k, v in rule.items() if k != "ruleset_id"}
                        for rule in self.rules
                        if rule["ruleset_id"] == identifier
                    ],
                    "bypass_actors": [
                        {
                            "actor_type": "Integration",
                            "actor_id": 56,
                            "bypass_mode": "pull_request",
                        }
                    ]
                    if identifier == 1
                    else [],
                }
            self.status = {
                "sha": HEAD,
                "total_count": 1,
                "statuses": [
                    {
                        "id": 567,
                        "context": "tide/replay",
                        "state": "success",
                        "creator": {"id": 34},
                    }
                ],
            }
            self.writes = []
            self.fail = None
            self.lose_response = False
            self.before_write = None
            self.parents = [BASE, HEAD]
            self.tree = "tree"
            self.response_error = None

        def get(self, path):
            if "/pulls/" in path:
                return deepcopy(self.pr)
            if "/rules/branches/" in path:
                return deepcopy(self.rules)
            if "/rulesets/" in path:
                return deepcopy(self.policies[int(path.rsplit("/", 1)[1])])
            if "/status?" in path:
                return deepcopy(self.status)
            if "/statuses?" in path:
                return deepcopy(self.status["statuses"])
            if "/git/ref/" in path:
                return {"object": {"sha": self.main}}
            if "/git/commits/" in path:
                merged = path.endswith(MERGE)
                return {
                    "parents": [
                        {"sha": p} for p in (self.parents if merged else [BASE])
                    ],
                    "tree": {"sha": self.tree if merged else "tree"},
                }
            if "/compare/" in path:
                return {"status": "identical"}
            raise AssertionError(path)

        def request(self, method, path, data):
            self.writes.append((method, path, data))
            if self.before_write:
                self.before_write()
            if self.fail:
                raise GitHubError(self.fail)
            # Simulate server SHA check + strict up-to-date required checks.
            if self.pr["head"]["sha"] != data["sha"] or self.main != BASE:
                raise GitHubError("GitHub rejected concurrent head/base movement")
            self.pr.update(merged=True, state="closed")
            self.main = MERGE
            if self.response_error:
                raise self.response_error
            if self.lose_response:
                raise GitHubError("response lost after server merge")
            return {"merged": True, "sha": MERGE}

    service = Service()
    monkeypatch.setattr(transport, "inspect", lambda *args, **kwargs: None)
    policy_hash = hashlib.sha256(
        canonical(transport.policy_snapshot(service))
    ).hexdigest()
    attestation = {
        "repository": REPOSITORY,
        "app_id": 56,
        "installation_id": 169219742,
        "visible_digest": policy_hash,
        "full_policy": transport.policy_snapshot(service, include_bypass=True),
    }
    service.attestation = attestation

    def run():
        return transport.merge_one(
            tmp_path,
            service,
            service,
            1058,
            base=BASE,
            head=HEAD,
            rollout_floor=1057,
            policy_hash=policy_hash,
            integration_id=12,
            status_actor_id=34,
            merger_app_id=56,
            attestation=attestation,
        )

    return service, run


def test_exact_merge_and_retry_are_one_write(setup):
    service, run = setup
    assert run()["merge"] == MERGE
    assert run()["merge"] == MERGE
    assert len(service.writes) == 1
    assert service.writes[0][2] == {"sha": HEAD, "merge_method": "merge"}


def test_hidden_bypass_authority_uses_operator_attested_visible_digest(setup):
    service, run = setup
    del service.policies[2]["bypass_actors"]
    assert run()["merge"] == MERGE
    with pytest.raises(ReplayError, match="hid ruleset bypass"):
        transport.policy_snapshot(service, include_bypass=True)


def test_lost_response_recovers_without_second_write(setup):
    service, run = setup
    service.lose_response = True
    assert run()["merge"] == MERGE
    assert len(service.writes) == 1


@pytest.mark.parametrize(
    "error", [http.client.IncompleteRead(b""), ValueError("malformed JSON")]
)
def test_incomplete_success_response_is_reconciled(setup, error):
    service, run = setup
    service.response_error = error
    assert run()["merge"] == MERGE
    assert len(service.writes) == 1


def test_setup_attestation_rejects_broad_merger_bypass(setup):
    service, _run = setup
    service.policies[2]["bypass_actors"] = [
        {"actor_type": "Integration", "actor_id": 56, "bypass_mode": "always"}
    ]
    with pytest.raises(ReplayError, match="bypass exceeds"):
        transport.verify_setup_authority(
            transport.policy_snapshot(service, include_bypass=True), 56
        )
    assert not service.writes


def test_returned_bypass_drift_fails_before_write(setup):
    service, run = setup
    service.policies[2]["bypass_actors"] = [
        {"actor_type": "Integration", "actor_id": 56, "bypass_mode": "always"}
    ]
    with pytest.raises(ReplayError, match="bypass authority differs"):
        run()
    assert not service.writes


@pytest.mark.parametrize("field,value", [
    ("repository", "other/repo"), ("app_id", 999), ("installation_id", 999),
    ("visible_digest", "0" * 64),
])
def test_attestation_identity_mismatch_does_not_write(setup, field, value):
    service, run = setup
    service.attestation[field] = value
    with pytest.raises(ReplayError, match="attestation identity"):
        run()
    assert not service.writes


@pytest.mark.parametrize(
    "error", ["HTTP 403", "HTTP 405", "HTTP 409", "HTTP 422", "timeout"]
)
def test_rejection_is_not_retried(setup, error):
    service, run = setup
    service.fail = error
    with pytest.raises(GitHubError, match=error):
        run()
    assert len(service.writes) == 1


@pytest.mark.parametrize("state", ["failure", "pending", "error"])
def test_failed_or_stale_status_does_not_write(setup, state):
    service, run = setup
    service.status["statuses"][0]["state"] = state
    with pytest.raises(ReplayError, match="replay status"):
        run()
    assert not service.writes


def test_forged_status_publisher_does_not_write(setup):
    service, run = setup
    service.status["statuses"][0]["creator"]["id"] = 999
    with pytest.raises(ReplayError, match="replay status"):
        run()
    assert not service.writes


def test_failed_replay_or_foreign_files_does_not_write(setup, monkeypatch):
    service, run = setup

    def reject(*args, **kwargs):
        raise ReplayError(
            "Tide PR must contain exactly its batch, projection, and receipt"
        )

    monkeypatch.setattr(transport, "inspect", reject)
    with pytest.raises(ReplayError, match="exactly"):
        run()
    assert not service.writes


def test_policy_change_does_not_write(setup):
    service, run = setup
    service.rules.pop()
    with pytest.raises(ReplayError, match="policy differs"):
        run()
    assert not service.writes


@pytest.mark.parametrize("side", ["base", "head"])
def test_movement_before_request_does_not_write(setup, side):
    service, run = setup
    service.pr[side]["sha"] = "d" * 40
    with pytest.raises(ReplayError, match="changed"):
        run()
    assert not service.writes


@pytest.mark.parametrize("side", ["base", "head"])
def test_movement_during_request_is_rejected_by_server(setup, side):
    service, run = setup

    def move():
        if side == "base":
            service.main = "d" * 40
        else:
            service.pr["head"]["sha"] = "d" * 40

    service.before_write = move
    with pytest.raises(GitHubError, match="concurrent"):
        run()
    assert len(service.writes) == 1
    assert service.pr["merged"] is False


@pytest.mark.parametrize(
    "field,value", [("parents", ["d" * 40, HEAD]), ("tree", "foreign")]
)
def test_readback_never_accepts_different_merge(setup, field, value):
    service, run = setup
    setattr(service, field, value)
    with pytest.raises(ReplayError, match="parents or tree"):
        run()
    assert len(service.writes) == 1


def test_template_is_disabled_and_outside_workflows():
    root = Path(__file__).resolve().parents[2]
    path = root / "oled/changes/wea-tide-merge-gate/tide-merge.yml.disabled"
    template = path.read_text(encoding="utf-8")
    assert "if: ${{ false }}" in template
    assert "TIDE_MERGE_ENABLED: 'false'" in template
    deployed = (root / ".github/workflows/guard-vnext-ledger.yml").read_text()
    assert not (root / ".github/workflows/tide-merge.yml").exists()
    assert "needs: trusted-ledger-check" in deployed
    assert "needs.trusted-ledger-check.result == 'success'" in deployed
    assert "github.ref == 'refs/heads/main'" in deployed
    assert "VERIFIED_HEAD: ${{ needs.trusted-ledger-check.outputs.head }}" in deployed
    assert "workflow_run:" not in deployed
    assert "vars.TIDE_MERGE_ENABLED == 'true'" in deployed
    assert "environment: tide-merge" in deployed
    assert "persist-credentials: false" in deployed


def test_transport_preserves_canonical_hello_world_package_identity():
    from wea_vnext.tide.hello_world import package_hash

    root = Path(__file__).resolve().parents[2]
    state = json.loads((root / "ledger/vnext/tide-state.json").read_bytes())
    expected = state["hello_world_anchor"]["checkpoint"]["installation_sha256"]
    assert package_hash() == expected
