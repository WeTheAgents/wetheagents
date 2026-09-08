from __future__ import annotations

import hashlib
import json
import subprocess

import pytest

from wea_vnext.tide import activation
from wea_vnext.tide.collection import API_ROOT
from wea_vnext.tide.ledger import BOOTSTRAP, STATE
from wea_vnext.tide.replay import ReplayError

from .test_tide_ledger import commit, put
from .test_tide_replay import bootstrap


def approval(body):
    return {
        "id": 23,
        "user": {"id": activation.OPERATOR, "login": "peachgabba22"},
        "issue_url": f"https://api.github.com/{API_ROOT}/issues/946",
        "html_url": "https://github.com/WeTheAgents/wetheagents/issues/946#issuecomment-23",
        "created_at": "2026-09-08T12:00:00Z",
        "updated_at": "2026-09-08T12:00:00Z",
        "author_association": "COLLABORATOR",
        "body": body,
    }


class SourceAPI:
    def __init__(self, comment):
        self.comment = comment

    def get(self, path):
        assert path == f"{API_ROOT}/issues/comments/23"
        return self.comment


def retained(comment):
    return activation.fetch_source(
        SourceAPI(comment), 23, hashlib.sha256(comment["body"].encode()).hexdigest()
    )


@pytest.fixture
def legacy_repo(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    initial = bootstrap()
    ids = {
        item["subject_id"]
        for item in initial["identities"]["bindings"]
        if item["actor_kind"] == "agent"
    }
    balances = {agent: initial["balances"].get(agent, 0) for agent in ids}
    balances["treasury"] = 100
    put(
        tmp_path,
        {
            "ledger/balances.json": {
                "agents": {key: {"balance": value} for key, value in balances.items()}
            },
            "ledger/escrows.json": {"active": {}},
            "ledger/idem_keys.json": {},
        },
    )
    base = commit(tmp_path)
    _, hashes = activation.legacy(tmp_path, base)
    command = {
        "schema": "wea-tide-activation-1",
        "predecessor": base,
        "runtime": initial["runtime"],
        "legacy_files": hashes,
        "identities": initial["identities"],
    }
    source = retained(approval(activation.MARKER + json.dumps(command)))
    return tmp_path, base, source, balances


def test_activation_imports_exact_existing_balances_without_minting(legacy_repo):
    root, base, source, balances = legacy_repo
    values = activation.payloads(
        root, base, source, {"run_id": "1", "run_attempt": "1"}
    )
    assert values[BOOTSTRAP]["balances"] == balances
    assert values[STATE]["balances"] == balances
    put(root, values)
    head = commit(root)
    assert activation.validate_activation(root, base, head, None) == values[STATE]


def test_activation_rejects_balanced_reallocation(legacy_repo):
    root, base, source, _ = legacy_repo
    values = activation.payloads(root, base, source, {})
    values[BOOTSTRAP]["balances"]["agent-author"] -= 1
    values[BOOTSTRAP]["balances"]["treasury"] += 1
    put(root, values)
    with pytest.raises(ReplayError, match="differs from retained source"):
        activation.validate_activation(root, base, commit(root), None)


def test_activation_requires_fresh_exact_predecessor(legacy_repo):
    root, _base, source, _ = legacy_repo
    (root / "new.txt").write_text("main advanced")
    with pytest.raises(ReplayError, match="another predecessor"):
        activation.payloads(root, commit(root), source, {})


@pytest.mark.parametrize("change", ["identity", "issue", "edited", "hash"])
def test_activation_source_cannot_be_substituted(change):
    comment = approval("operator command")
    if change == "identity":
        comment["user"]["id"] += 1
    elif change == "issue":
        comment["issue_url"] = comment["issue_url"].replace("946", "947")
    elif change == "edited":
        comment["updated_at"] = "2026-09-08T12:01:00Z"
    with pytest.raises(ReplayError):
        activation.fetch_source(
            SourceAPI(comment),
            23,
            "0" * 64
            if change == "hash"
            else hashlib.sha256(comment["body"].encode()).hexdigest(),
        )
