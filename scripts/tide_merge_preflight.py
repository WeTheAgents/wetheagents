"""Read-only exact-candidate preparation for the Tide merge transport.

A successful result is not enduring merge authority.
"""

from pathlib import Path

from wea_vnext.tide.collection import API_ROOT, REPOSITORY
from wea_vnext.tide.ledger import RECEIPTS, git, read, validate
from wea_vnext.tide.replay import ReplayError


def inspect(root: Path, api, number: int, *, base: str, head: str) -> dict:
    """Replay one exact ordinary candidate, then recheck mutable identities.

    Server-side strict required checks are still needed to close the race after
    this function returns. Never consume this result as an enduring approval.
    """
    if type(number) is not int or number <= 1057:
        raise ReplayError("candidate predates the proposed automation rollout")

    def current():
        pr = api.get(f"{API_ROOT}/pulls/{number}")
        if (
            pr["state"] != "open"
            or pr.get("draft") is not False
            or pr.get("merged") is not False
            or pr["base"]["repo"]["full_name"] != REPOSITORY
            or pr["head"]["repo"]["full_name"] != REPOSITORY
            or pr["base"]["ref"] != "main"
            or pr["head"]["ref"] != "tide/pending"
            or pr["base"]["sha"] != base
            or pr["head"]["sha"] != head
        ):
            raise ReplayError("PR is not the exact open canonical Tide candidate")
        if api.get(f"{API_ROOT}/git/ref/heads/main")["object"]["sha"] != base:
            raise ReplayError("canonical main advanced")

    current()
    if git(root, "rev-parse", "HEAD") != base:
        raise ReplayError("preflight must execute from the trusted base checkout")
    # Ordinary validator enforces one parent, three exact paths, provenance,
    # authenticated retained sources and deterministic replay. No activation or
    # code-only fallback and no trust in a caller-provided green status.
    state = validate(root, base, head, api=api)
    receipt = read(root, head, f"{RECEIPTS}{state['sequence']:016d}.json")
    provenance = receipt["provenance"]
    run = api.get(
        f"{API_ROOT}/actions/runs/{int(provenance['run_id'])}"
        f"/attempts/{int(provenance['run_attempt'])}"
    )
    if run.get("status") != "completed" or run.get("conclusion") != "success":
        raise ReplayError("candidate producer has not completed successfully")
    latest = api.get(f"{API_ROOT}/actions/runs/{int(provenance['run_id'])}")
    if (
        latest.get("run_attempt") != int(provenance["run_attempt"])
        or latest.get("status") != "completed"
        or latest.get("conclusion") != "success"
    ):
        raise ReplayError("candidate producer attempt is obsolete or unsuccessful")
    current()
    return {
        "number": number,
        "base": base,
        "head": head,
        "sequence": state["sequence"],
        "mode": "read-only",
    }
