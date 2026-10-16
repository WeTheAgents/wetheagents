"""Opt-in exact-candidate merge transport with operator-attested policy."""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import re
from pathlib import Path

from scripts.tide_merge_preflight import inspect
from wea_vnext.tide.collection import API_ROOT, REPOSITORY
from wea_vnext.tide.github import GitHub, GitHubError
from wea_vnext.tide.replay import ReplayError, canonical


def policy_snapshot(api, *, include_bypass=False) -> dict:
    rules = api.get(f"{API_ROOT}/rules/branches/main")
    policies = []
    for rule_id in sorted({rule["ruleset_id"] for rule in rules}):
        source = api.get(f"{API_ROOT}/rulesets/{int(rule_id)}")
        if include_bypass and "bypass_actors" not in source:
            raise ReplayError(
                "GitHub hid ruleset bypass actors; policy cannot be verified "
                "with this token; do not widen permissions automatically"
            )
        policies.append(
            {
                key: source[key]
                for key in (
                    "id",
                    "target",
                    "source_type",
                    "source",
                    "enforcement",
                    "conditions",
                    "rules",
                )
            }
        )
        if include_bypass:
            policies[-1]["bypass_actors"] = source["bypass_actors"]
    return {"rules": rules, "rulesets": policies}


def verify_setup_authority(snapshot: dict, merger_app_id: int) -> None:
    """Operator setup check; full snapshot is retained in the reviewed attestation.

    Runtime read-only tokens cannot see bypass lists. Administrators remain
    trusted to preserve this attestation, including between a read and a merge.
    """
    permitted = False
    for source in snapshot["rulesets"]:
        for actor in source["bypass_actors"]:
            if (
                actor["actor_type"] == "Integration"
                and actor["actor_id"] == merger_app_id
            ):
                if (
                    actor["bypass_mode"] != "pull_request"
                    or source["rules"] != [{"type": "update"}]
                    or source["enforcement"] != "active"
                    or source["target"] != "branch"
                    or source["conditions"]
                    != {"ref_name": {"include": ["refs/heads/main"], "exclude": []}}
                ):
                    raise ReplayError("merger App bypass exceeds main PR update-only")
                permitted = True
    if not permitted:
        raise ReplayError("dedicated merger App has no approved update-only bypass")


def policy(api, expected_hash, integration_id, merger_app_id, attestation) -> None:
    """Check visible rules against the operator-attested deployment digest.

    The deployment attestation binds this digest to the full bypass snapshot and
    merger identity. Runtime does not claim to detect hidden bypass-only changes.
    Never request Administration permission to read this diagnostic metadata.
    """
    snapshot = policy_snapshot(api)
    rules = snapshot["rules"]
    if (
        attestation["repository"] != REPOSITORY
        or attestation["app_id"] != merger_app_id
        or attestation["installation_id"] != 169219742
        or attestation["visible_digest"] != expected_hash
    ):
        raise ReplayError("deployment attestation identity mismatch")
    approved = attestation["full_policy"]
    verify_setup_authority(approved, merger_app_id)
    visible = json.loads(json.dumps(approved))
    for source in visible["rulesets"]:
        del source["bypass_actors"]
    if hashlib.sha256(canonical(visible)).hexdigest() != expected_hash:
        raise ReplayError("attestation does not bind visible policy")
    if hashlib.sha256(canonical(snapshot)).hexdigest() != expected_hash:
        raise ReplayError("effective main policy differs from approved snapshot")
    for source in approved["rulesets"]:
        live = api.get(f'{API_ROOT}/rulesets/{source["id"]}')
        if (
            "bypass_actors" in live
            and live["bypass_actors"] != source["bypass_actors"]
        ):
            raise ReplayError("visible bypass authority differs from attestation")
    if not any(
        rule["type"] == "required_status_checks"
        and rule["parameters"]["strict_required_status_checks_policy"] is True
        and {"context": "tide/replay", "integration_id": integration_id}
        in rule["parameters"]["required_status_checks"]
        for rule in rules
    ):
        raise ReplayError("strict app-bound tide/replay is not required")
    if not {"pull_request", "non_fast_forward", "deletion", "update"} <= {
        rule["type"] for rule in rules
    }:
        raise ReplayError("required main protections are missing")


def replay_status(api, head: str, actor_id: int) -> None:
    # Combined endpoint returns the latest status for each context. Do not accept
    # an older green entry from status history or an arbitrary status publisher.
    result = api.get(f"{API_ROOT}/commits/{head}/status?per_page=100")
    if result["sha"] != head or result["total_count"] >= 100:
        raise ReplayError("status inventory is mismatched or incomplete")
    matches = [s for s in result["statuses"] if s["context"] == "tide/replay"]
    # The combined endpoint omits creator. Bind its latest status ID to the
    # authenticated history entry, never accept an older green status.
    history = api.get(f"{API_ROOT}/commits/{head}/statuses?per_page=100")
    authenticated = [
        item for item in history
        if len(matches) == 1 and item["id"] == matches[0]["id"]
    ]
    if (
        len(matches) != 1
        or matches[0]["state"] != "success"
        or len(authenticated) != 1
        or authenticated[0]["creator"]["id"] != actor_id
    ):
        raise ReplayError("latest trusted replay status is not successful")


def readback(api, number: int, base: str, head: str) -> dict | None:
    """Reconcile a prior request using immutable merge parents and tree."""
    pr = api.get(f"{API_ROOT}/pulls/{number}")
    if not pr.get("merged"):
        return None
    if (
        pr["head"]["sha"] != head
        or pr["head"]["repo"]["full_name"] != REPOSITORY
        or pr["base"]["repo"]["full_name"] != REPOSITORY
        or pr["base"]["ref"] != "main"
    ):
        raise ReplayError("merged PR identity differs from requested candidate")
    sha = pr["merge_commit_sha"]
    merge = api.get(f"{API_ROOT}/git/commits/{sha}")
    candidate = api.get(f"{API_ROOT}/git/commits/{head}")
    if (
        [p["sha"] for p in merge["parents"]] != [base, head]
        or [p["sha"] for p in candidate["parents"]] != [base]
        or merge["tree"]["sha"] != candidate["tree"]["sha"]
    ):
        raise ReplayError("merged parents or tree differ; operator inspection required")
    # Encode the fixed compare separator; the shared reader rejects raw dot pairs.
    comparison = api.get(f"{API_ROOT}/compare/{sha}%2E%2E%2Emain")
    if comparison["status"] not in {"identical", "ahead"}:
        raise ReplayError("merge is not in canonical main history")
    return {
        "number": number,
        "base": base,
        "head": head,
        "merge": sha,
        "result": "canonical-merge-observed",
    }


def merge_one(
    root,
    reader,
    writer,
    number,
    *,
    base,
    head,
    rollout_floor,
    policy_hash,
    integration_id,
    status_actor_id,
    merger_app_id,
    attestation,
):
    """Attempt at most one exact-SHA merge; errors never trigger another write.

    Reader is the read-only workflow token. Writer is a short-lived dedicated
    installation token with contents:write only. No approval API is called.
    """
    if (
        type(number) is not int
        or type(rollout_floor) is not int
        or number <= max(1057, rollout_floor)
        or integration_id <= 0
        or status_actor_id <= 0
        or merger_app_id <= 0
        or any(not re.fullmatch(r"[0-9a-f]{40}", sha) for sha in (base, head))
        or not re.fullmatch(r"[0-9a-f]{64}", policy_hash)
    ):
        raise ReplayError("invalid exact candidate or rollout policy configuration")
    previous = readback(reader, number, base, head)
    if previous is not None:
        return previous
    inspect(root, reader, number, base=base, head=head)
    policy(reader, policy_hash, integration_id, merger_app_id, attestation)
    replay_status(reader, head, status_actor_id)
    # Recheck after all other API reads. The remaining base/head race is closed
    # by strict server checks and the REST sha compare, not a local lock.
    pr = reader.get(f"{API_ROOT}/pulls/{number}")
    if (
        pr["state"] != "open"
        or pr.get("draft") is not False
        or pr["head"]["sha"] != head
        or pr["base"]["sha"] != base
        or pr["base"]["ref"] != "main"
        or pr["head"]["ref"] != "tide/pending"
        or reader.get(f"{API_ROOT}/git/ref/heads/main")["object"]["sha"] != base
    ):
        raise ReplayError("candidate changed before merge request")
    try:
        result = writer.request(
            "PUT",
            f"{API_ROOT}/pulls/{number}/merge",
            {"sha": head, "merge_method": "merge"},
        )
    except (GitHubError, http.client.HTTPException, ValueError):
        recovered = readback(reader, number, base, head)
        if recovered is not None:
            return recovered
        raise
    if result.get("merged") is not True:
        raise ReplayError("GitHub did not confirm merge; no automatic write retry")
    observed = readback(reader, number, base, head)
    if observed is None or observed["merge"] != result.get("sha"):
        raise ReplayError("merge readback unconfirmed; inspect before retry")
    return observed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    request = json.loads(args.request.read_text(encoding="utf-8"))
    reader = GitHub(os.environ.get("GITHUB_TOKEN", ""))
    if not args.execute:
        result = inspect(
            Path.cwd(),
            reader,
            request["number"],
            base=request["base"],
            head=request["head"],
        )
    else:
        if os.environ.get("TIDE_MERGE_ENABLED") != "true":
            raise ReplayError("merge transport is disabled")
        result = merge_one(
            Path.cwd(),
            reader,
            GitHub(os.environ.get("TIDE_MERGE_TOKEN", "")),
            request["number"],
            base=request["base"],
            head=request["head"],
            rollout_floor=int(os.environ["TIDE_ROLLOUT_FLOOR"]),
            policy_hash=os.environ["TIDE_POLICY_HASH"],
            integration_id=int(os.environ["TIDE_STATUS_INTEGRATION_ID"]),
            status_actor_id=int(os.environ["TIDE_STATUS_ACTOR_ID"]),
            merger_app_id=int(os.environ["TIDE_MERGER_APP_ID"]),
            attestation=json.loads(
                Path(".github/tide-merge-policy.json").read_text(encoding="utf-8")
            ),
        )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
