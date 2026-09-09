"""Pure admission decisions over retained GitHub and canonical registry data."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import datetime


def _time(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("participant timestamp needs a timezone")
    return result


def _fields(data, expected):
    if type(data) is not dict or set(data) != set(expected.split()):
        raise ValueError("participant command fields do not match")


def _text(value):
    if type(value) is not str or not value.strip() or value != value.strip():
        raise ValueError("participant identifiers must be nonempty exact strings")
    return value


def _source(raw, repository_id):
    if (
        raw["revision_status"] != "confirmed"
        or raw["object_kind"] != "issue_comment"
        or str(raw["repository_id"]) != str(repository_id)
    ):
        raise ValueError("participant authority requires a confirmed canonical comment")
    if hashlib.sha256(raw["body"].encode("utf-8")).hexdigest() != raw["content_hash"]:
        raise ValueError("participant source hash differs")
    if raw.get("original_author_account_id") != raw["actor_account_id"]:
        raise ValueError("participant consent and approval must be owner-authored")


def _active(binding, at):
    return _time(binding["effective_from"]) <= at and (
        binding["effective_until"] is None or at < _time(binding["effective_until"])
    )


def request(data, raw, repository_id):
    """Validate consent, without reserving an identity or granting authority."""
    _fields(data, "kind owner_account_id base_agent_id control_group_id agents")
    if data["kind"] != "participant_request":
        raise ValueError("participant consent requires a participant_request")
    _source(raw, repository_id)
    owner = _text(data["owner_account_id"])
    if not re.fullmatch(r"[1-9][0-9]*", owner) or owner != raw["actor_account_id"]:
        raise ValueError("participant owner must equal the numeric source author")
    _text(data["base_agent_id"])
    _text(data["control_group_id"])
    agents = data["agents"]
    if type(agents) is not list or not 1 <= len(agents) <= 100:
        raise ValueError("participant request requires one to one hundred agents")
    seen = set()
    for agent in agents:
        _fields(agent, "agent_id preserve_balance")
        name = _text(agent["agent_id"])
        if (
            not re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9_.-]*@[A-Za-z0-9][A-Za-z0-9_.-]*", name
            )
            or name.endswith("@system")
            or name in seen
        ):
            raise ValueError(
                "participant Agent ID is reserved, duplicate, or malformed"
            )
        if type(agent["preserve_balance"]) is not bool:
            raise ValueError("preserve_balance must be boolean")
        seen.add(name)
    return copy.deepcopy(data)


def approve(
    data,
    raw,
    consent,
    consent_data,
    *,
    repository_id,
    registry,
    opening_balances,
    admissions,
    batch_id,
):
    """Atomically validate an exact owner request and Agent0 role approval."""
    _fields(
        data,
        "kind request_revision_id request_content_hash "
        "approver_binding_id approver_binding_version",
    )
    if data["kind"] != "participant_approval":
        raise ValueError("participant approval requires a participant_approval")
    _source(raw, repository_id)
    requested = request(consent_data, consent, repository_id)
    if (
        consent["revision_id"] != data["request_revision_id"]
        or consent["content_hash"] != data["request_content_hash"]
        or consent["issue_id"] != raw["issue_id"]
        or _time(consent["effective_at"]) > _time(raw["effective_at"])
    ):
        raise ValueError(
            "participant approval must pin earlier consent in the same Issue"
        )
    at = _time(raw["effective_at"])
    roles = [
        b
        for b in registry["bindings"]
        if b["actor_kind"] == "agent0"
        and b["subject_id"] == "agent0@system"
        and _active(b, at)
    ]
    if (
        len(roles) != 1
        or roles[0]["github_account_id"] != raw["actor_account_id"]
        or roles[0]["binding_id"] != data["approver_binding_id"]
        or type(data["approver_binding_version"]) is not int
        or roles[0]["version"] != data["approver_binding_version"]
    ):
        raise ValueError("participant approval requires the exact active Agent0 role")
    previous = admissions.get(consent["revision_id"])
    if previous is not None:
        return copy.deepcopy(previous)
    owner = requested["owner_account_id"]
    accounts = {a["github_account_id"]: a for a in registry["accounts"]}
    reserved = {b["subject_id"] for b in registry["bindings"]}
    groups = {
        b["control_group_id"]
        for b in registry["control_group_bindings"]
        if _active(b, at)
        and any(
            a["actor_kind"] == "agent"
            and a["subject_id"] == b["agent_id"]
            and a["github_account_id"] == owner
            and _active(a, at)
            for a in registry["bindings"]
        )
    }
    for admission in admissions.values():
        reserved.update(a["agent_id"] for a in admission["agents"])
        if admission["owner_account_id"] == owner:
            accounts.setdefault(owner, {"base_agent_id": admission["base_agent_id"]})
            groups.add(admission["control_group_id"])
    if owner in accounts:
        if accounts[owner]["base_agent_id"] != requested["base_agent_id"]:
            raise ValueError("participant account base Agent ID is immutable")
        if groups != {requested["control_group_id"]}:
            raise ValueError(
                "participant request must retain the owner's control group"
            )
    elif requested["agents"][0]["agent_id"] != requested["base_agent_id"]:
        raise ValueError("a new account must admit its base Agent ID first")
    for agent in requested["agents"]:
        name = agent["agent_id"]
        if name in reserved:
            raise ValueError("participant Agent ID already bound or reserved")
        if agent["preserve_balance"] != (name in opening_balances):
            raise ValueError("participant preserved/new choice differs from bootstrap")
    return {
        **{k: v for k, v in requested.items() if k != "kind"},
        "request_revision_id": consent["revision_id"],
        "request_content_hash": consent["content_hash"],
        "approval_revision_id": raw["revision_id"],
        "approval_content_hash": raw["content_hash"],
        "batch_id": batch_id,
    }


def registry_at(bootstrap, admissions, merges):
    """Materialize authority only from authenticated canonical admission merges."""
    result = copy.deepcopy(bootstrap)
    for admission in admissions.values():
        merged_at = merges.get(admission["batch_id"])
        if merged_at is None:
            continue
        _time(merged_at)
        owner = admission["owner_account_id"]
        if not any(a["github_account_id"] == owner for a in result["accounts"]):
            result["accounts"].append(
                {
                    "github_account_id": owner,
                    "owner": owner,
                    "base_agent_id": admission["base_agent_id"],
                }
            )
        for agent in admission["agents"]:
            name = agent["agent_id"]
            key = hashlib.sha256(
                json.dumps(
                    [admission["request_revision_id"], name],
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            common = {
                "version": 1,
                "effective_from": merged_at,
                "effective_until": None,
            }
            result["bindings"].append(
                {
                    **common,
                    "binding_id": "participant:" + key,
                    "github_account_id": owner,
                    "actor_kind": "agent",
                    "subject_id": name,
                }
            )
            result["control_group_bindings"].append(
                {
                    **common,
                    "binding_id": "participant-control:" + key,
                    "agent_id": name,
                    "control_group_id": admission["control_group_id"],
                }
            )
    return result
