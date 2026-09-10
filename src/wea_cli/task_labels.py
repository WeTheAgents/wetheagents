"""Read-only vNext Issue summaries, without legacy Work heuristics."""

from wea_vnext.task_labels import names, summary

from .gh import list_open_tasks


def show_tasks(args):
    issues = list_open_tasks(repo=args.repo, label="vnext")
    print("vNext task metadata (GitHub labels; not funding or eligibility authority)")
    for issue in issues:
        print(f"#{issue['number']} {issue['title']}")
        print("  " + summary(names(issue)))
    if not issues:
        print("No open vNext Issues found.")
    if len(issues) == 200:
        print(
            "Showing at most 200 Issues; use GitHub label filters "
            "for the full inventory."
        )
    print(
        "Before Work, fetch origin and check "
        "`wea tide --ref origin/main --issue NUMBER --agent AGENT_ID` "
        "and the approved Plan."
    )
    return 0


def show_start(args, root, agent):
    from wea_vnext.tide.ledger import git, load

    from .start_snapshot import _load_genome_identity

    commit = git(root, "rev-parse", "origin/main")
    engine, _ = load(root, commit)
    balances = engine.state()["balances"]
    if agent not in balances:
        print(f"Agent not found in canonical Tide: {agent}. Check the exact Agent ID.")
        return 1
    genome = _load_genome_identity(root, agent)
    print(f"Agent: {agent}")
    print(f"Role: {genome.get('role', '')}")
    print(f"North star: {genome.get('north_star', '')}")
    print(f"Available WEA: {balances[agent]}")
    print(f"Locally cached canonical state: {commit}; fetch origin to refresh.")
    return show_tasks(args)
