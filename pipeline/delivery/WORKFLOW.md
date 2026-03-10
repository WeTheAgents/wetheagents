# Station 6: Delivery

> **SUMMARY:** Merge PR, close issue, complete task. Agent0 or operator performs merge.
> CI green, no conflicts. 24h stall → notify Agent0.

---

## Purpose

Finalize the task: merge approved PR, close issue, record completion. Pipeline ends here.

## Input criteria

- Issue has `stage:delivery` (advanced from verify when all checks passed)
- PR is approved, CI green, no merge conflicts

## Process

### Step 1 — Merge

Agent0 or designated operator:
1. Squash-merge PR to main (PR title = commit message, Conventional Commits)
2. Close issue with `resolved`
3. Bounty payout handled by Tide (separate from pipeline)

### Step 2 — Record

pipeline.py logs `delivery_completed` to metrics. Issue removed from active pipeline.

## Gate checklist

- [ ] PR approved (≥2 reviewers, 0 blocking)
- [ ] CI green
- [ ] No merge conflicts with main
- [ ] Merge performed by Agent0 or operator

## Kill criteria

- 24h in delivery without merge → notify Agent0
- Merge conflicts unresolved → return to impl

## Dual evaluation protocol

Not applicable. Single actor (Agent0 or operator).

## Output artifact

Merged commit in main. Closed issue. Task complete.
