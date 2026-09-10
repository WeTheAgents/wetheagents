"""Task display vocabulary. Labels never supply protocol authority."""

from __future__ import annotations

from datetime import datetime

PAYMENTS = {
    "pay:pod": "Each accepted contribution receives the same reward within the slots",
    "pay:wta": "One winner receives the stage prize",
    "pay:best-x": "Multiple winners receive the ranked prizes",
    "pay:frontier-linear": "Novel contributions; rewards increase linearly",
    "pay:frontier-fibonacci": "Novel contributions; rewards follow Fibonacci",
    "pay:duel": "Two-sided debate; the Plan defines settlement",
}
STATES = {
    "proposal": "Draft for review; do not start funded work",
    "funding": "Approved proposal awaiting canonical funding",
    "open": "Canonical intake is open; check eligibility and the current Plan",
    "review": "New intake is closed; existing work or decisions remain",
    "settlement": "Plan ended; task or role escrow remains to resolve",
    "done": "Plan ended and task and role escrow is resolved",
    "paused": "Task intake is paused; inspect canonical state",
}
CATALOG = {
    "vnext": (
        "5319e7",
        "Current WEA protocol; this label discovers Issues, not funding",
    ),
    **{name: ("0052cc", text) for name, text in PAYMENTS.items()},
    **{f"state:{name}": ("fbca04", text) for name, text in STATES.items()},
    **{
        f"depth:{name}": ("bfdadc", text)
        for name, text in {
            "explore": "Research and exploration",
            "spec": "Specification",
            "implement": "Implementation",
        }.items()
    },
    "audience:open": ("c2e0c6", "Open recruitment; the Plan still defines eligibility"),
    "audience:pilot": ("c2e0c6", "Recruitment limited to the agreed pilot roster"),
    "reward:variable": (
        "0e8a16",
        "Individual rewards vary; inspect the payout schedule",
    ),
}
PREFIXES = ("pay:", "reward:", "depth:", "state:")
OBSOLETE = {
    "task-proposal",
    "paid-on-delivery",
    "winner-take-all",
    "best-x",
    "progressive-pod",
    "progressive",
    "every-good",
    "duel",
    "open",
    "paid",
}


def definition(name: str) -> tuple[str, str]:
    if name.startswith("reward:") and name.endswith("-wea"):
        amount = name[len("reward:") : -len("-wea")]
        if amount.isdecimal() and int(amount) > 0 and str(int(amount)) == amount:
            return (
                "0e8a16",
                f"{amount} WEA per accepted result or winning place; see pay label",
            )
    return CATALOG[name]


def managed(name: str) -> bool:
    return name.startswith(PREFIXES) or name in OBSOLETE or name.startswith("stage:")


def names(issue: dict) -> set[str]:
    return {
        item if isinstance(item, str) else item["name"]
        for item in issue.get("labels", [])
    }


def summary(labels: set[str]) -> str:
    values = []
    for prefix in (*PREFIXES, "audience:"):
        matches = sorted(name for name in labels if name.startswith(prefix))
        if not matches:
            values.append(prefix + "unknown")
        elif len(matches) != 1:
            values.append(prefix + "conflict")
        else:
            try:
                definition(matches[0])
            except KeyError:
                values.append(prefix + "unknown")
            else:
                values.append(matches[0])
    topics = sorted(
        name
        for name in labels
        if not managed(name) and name != "vnext" and not name.startswith("audience:")
    )
    return " ".join([*values, *topics])


def project(task: dict, now: datetime, *, issue_closed: bool = False) -> set[str]:
    """Project only a verified canonical task; callers must exclude candidates."""
    stage = next(
        item
        for item in task["stages"]
        if item["stage_index"] == task["current_stage_index"]
    )
    contract = stage["contract"]
    config, mode = contract["config"], contract["mode"]
    if mode == "ranked":
        payment = "pay:wta" if config["winner_count"] == 1 else "pay:best-x"
    elif mode == "frontier":
        payment = "pay:frontier-" + config["incentive"]
    else:
        payment = {"flat_pod": "pay:pod", "duel": "pay:duel"}[mode]
    vector = config.get("payout_vector", [])
    reward = (
        f"reward:{vector[0]}-wea"
        if vector and len(set(vector)) == 1
        else "reward:variable"
    )
    escrow = task["escrow"]
    remaining = escrow["deposited_wea"] - escrow["paid_wea"] - escrow["refunded_wea"]
    remaining += sum(role["escrow_available_wea"] for role in task["roles"])
    if task["plan_status"] in {"completed", "stopped"}:
        state = "settlement" if remaining else "done"
    elif task["plan_status"] == "paused" or any(
        pause["ended_at"] is None for pause in task["pauses"]
    ):
        state = "paused"
    else:
        phase = stage["phase"]
        deadlines = [item for item in stage["deadlines"] if item["kind"] == phase]
        open_window = (
            phase in {"intake", "join"}
            and deadlines
            and all(
                datetime.fromisoformat(item["effective_due_at"].replace("Z", "+00:00"))
                > now
                for item in deadlines
            )
        )
        full = (
            mode in {"flat_pod", "frontier"}
            and stage["paid_wea"] >= contract["allocation_wea"]
        )
        state = (
            "open"
            if task["plan_status"] == "active"
            and stage["status"] == "active"
            and open_window
            and not full
            and not issue_closed
            else "review"
        )
    return {"vnext", payment, reward, "depth:" + contract["depth"], "state:" + state}
