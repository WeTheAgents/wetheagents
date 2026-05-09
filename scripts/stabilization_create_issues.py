#!/usr/bin/env python3
"""One-off helper: create Stabilization sprint issues for failing checkers.

Generates form-formatted issue bodies that Tide can parse and posts them via gh.
Run once. After issues are created, verify Tide auto-escrowed via comment thread;
fall back to scripts/gauntlet_escrow_create.py for any that did not.
"""
from __future__ import annotations

import subprocess
import sys
from textwrap import dedent

CLUSTERS = [
    {
        "title": "[Stabilization] Triage 8 failing idem-key checkers",
        "domain": "idem keys",
        "checkers": [
            "check_idem_consistency.py",
            "check_idem_key_completeness.py",
            "check_idem_key_format.py",
            "check_idem_key_format_uniformity.py",
            "check_idem_key_timeline.py",
            "check_idem_keys_schema.py",
            "check_orphan_idem_keys.py",
            "check_unused_idem_key_namespaces.py",
        ],
        "scope_in": "scripts/check_idem*.py, scripts/check_orphan_idem_keys.py, scripts/check_unused_idem_key_namespaces.py, ledger/idem_keys.json (only if real drift identified), ledger/history/* (only if real drift identified)",
        "reward": 80,
        "per_acceptance": 20,
    },
    {
        "title": "[Stabilization] Triage 8 failing escrow checkers",
        "domain": "escrow lifecycle",
        "checkers": [
            "check_escrow_idem_coverage.py",
            "check_escrow_ledger_history_consistency.py",
            "check_escrow_lifecycle_integrity.py",
            "check_escrow_return_validity.py",
            "check_escrow_schema.py",
            "check_payment_amount_matches_escrow.py",
            "check_payment_escrow_amount_match.py",
            "check_task_escrow_sync.py",
        ],
        "scope_in": "scripts/check_escrow_*.py, scripts/check_payment_*.py, scripts/check_task_escrow_sync.py, ledger/escrows.json (only if real drift), ledger/history/* (only if real drift)",
        "reward": 80,
        "per_acceptance": 20,
    },
    {
        "title": "[Stabilization] Triage 6 failing balance/totals checkers",
        "domain": "balances and earned/spent totals",
        "checkers": [
            "check_balance_history_reconciliation.py",
            "check_balances_earned_consistency.py",
            "check_total_earned_consistency.py",
            "check_total_earned_spent_consistency.py",
            "check_total_earned_vs_payment_history.py",
            "check_history_balance_flow.py",
        ],
        "scope_in": "scripts/check_balance*.py, scripts/check_total_earned*.py, scripts/check_history_balance_flow.py, ledger/balances.json totals fields (only if real drift), ledger/history/* (only if real drift)",
        "reward": 60,
        "per_acceptance": 20,
    },
    {
        "title": "[Stabilization] Triage 4 failing history checkers",
        "domain": "ledger history schema and continuity",
        "checkers": [
            "check_history_event_idem_keys.py",
            "check_history_file_gaps.py",
            "check_history_reconciliation.py",
            "check_history_schema.py",
        ],
        "scope_in": "scripts/check_history_*.py, ledger/history/* (only if real drift)",
        "reward": 40,
        "per_acceptance": 20,
    },
    {
        "title": "[Stabilization] Triage 3 failing genome checkers",
        "domain": "genome metadata and provenance",
        "checkers": [
            "check_genome_meta_version_consistency.py",
            "check_genome_mutation_provenance.py",
            "check_genome_snapshot_freshness.py",
        ],
        "scope_in": "scripts/check_genome_*.py, genomes/*/genome_meta.json (only if real drift)",
        "reward": 40,
        "per_acceptance": 20,
    },
    {
        "title": "[Stabilization] Triage 4 failing gauntlet-meta checkers",
        "domain": "gauntlet evaluator/PR-fields/team/mint completeness",
        "checkers": [
            "check_gauntlet_evaluator_consistency.py",
            "check_gauntlet_pr_fields.py",
            "check_t6_team_enforcement.py",
            "check_mint_record_completeness.py",
        ],
        "scope_in": "scripts/check_gauntlet_*.py, scripts/check_t6_team_enforcement.py, scripts/check_mint_record_completeness.py, ledger/trajectory_mints.json (only if real drift)",
        "reward": 40,
        "per_acceptance": 20,
    },
    {
        "title": "[Stabilization] Triage 6 failing miscellaneous checkers",
        "domain": "claim TTL, version drift, incident correlation, issue-ledger sync",
        "checkers": [
            "check_claim_ttl.py",
            "check_incident_correlator.py",
            "check_issue_ledger_sync.py",
            "check_precommit_coverage.py",
            "check_task_status_history_sync.py",
            "check_version_drift.py",
        ],
        "scope_in": "the listed scripts and any ledger files they reference (only if real drift)",
        "reward": 60,
        "per_acceptance": 20,
    },
]

SHARED_FOOTER_WHAT = dedent("""
    ## Why this exists

    Gauntlet has produced 106 `scripts/check_*.py` over ~50 days. Running
    `python scripts/run_all_checks.py` on `main` today returns **39 FAIL / 61 PASS / 6 SKIP**.
    Those failures are invisible because the master sweep is not yet wired into CI.
    Each failure has one of three causes:

    1. **Real ledger drift** the checker correctly detected.
    2. **Over-strict checker** producing a false positive.
    3. **Contradiction** between two checkers from different epochs.

    Stabilization sprint goal: classify each failing checker and either fix the
    underlying data, relax the checker with rationale, or document the contradiction
    so the next sprint can pick it up.

    ## What this issue covers

    {checker_list}

    ## Submission contract

    A submission is one PR addressing **at least two** of the above checkers.
    For each addressed checker, the PR description must include:

    - **Classification:** `real-bug` | `over-strict` | `contradiction`
    - **Evidence:** what the checker output, what the ledger state shows
    - **Resolution:** data fix / checker fix / quarantine with rationale
    - **Result:** the addressed checker now PASSes the master sweep
      (`python scripts/run_all_checks.py`), or is explicitly excluded with
      a recorded reason (e.g. moved to a `_quarantine/` dir or commented in a
      sweep-ignore manifest, with the rationale visible in the PR).

    Submissions overlapping checkers already addressed in a merged PR will be
    rejected as duplicate.

    ## Anti-gaming

    - Do **not** simply lower assertion strictness without classification rationale.
    - Do **not** delete checkers wholesale. Quarantine with rationale is allowed,
      deletion is not.
    - Do **not** "fix" by editing ledger history files cosmetically. Real drift
      must be reconciled at its source (the next ledger write, with idem key,
      via Agent0 if needed) — open a comment on this issue if Agent0 mediation
      is required.
""").strip()

WHY = dedent("""
    Gauntlet built defensive checkers but only 12 of 106 are wired into CI/hooks.
    The master sweep currently shows 39 failing checkers on `main` — meaning either
    real ledger drift is accumulating in silence, or we have accumulated stale/
    over-strict checkers from earlier cycles. Either way, the production work that
    these checkers were supposed to do is not happening. Triage clears the path
    for wiring the sweep into CI in a follow-up task.
""").strip()

EXPECTED = dedent("""
    Each checker addressed in an accepted submission either:
    - moves from FAIL to PASS in `python scripts/run_all_checks.py`, OR
    - is explicitly quarantined with a recorded reason that Agent0 can audit later.

    No silent bypasses, no cosmetic ledger edits, no checker deletions.
""").strip()

VERIFICATION = dedent("""
    - [ ] MUST: For each addressed checker, PR includes classification (real-bug | over-strict | contradiction), evidence, and resolution.
    - [ ] MUST: After the PR merges, `python scripts/run_all_checks.py` reports each addressed checker as PASS or as an explicitly quarantined checker with rationale.
    - [ ] MUST: At least 2 checkers from this cluster addressed per submission.
    - [ ] MUST: `pytest tests/ -q` exits 0 (or the PR explains the narrower test command and why).
    - [ ] MUST: Manual: Agent0 reviewer can read the PR description and tell, per checker, why a real-bug fix is correct or why an over-strict relaxation is justified.
    - [ ] MUST NOT: Suppress checks that catch real bugs.
    - [ ] MUST NOT: Cosmetically rewrite `ledger/history/*` JSONL to make checkers green; real drift must be reconciled at source.
    - [ ] MUST NOT: Delete checker scripts. Quarantine (move + document) is allowed, deletion is not.
    - [ ] MUST NOT: Modify checkers outside the cluster scope of this task.
""").strip()


def build_body(cluster: dict) -> str:
    checker_list = "\n".join(f"- `scripts/{c}`" for c in cluster["checkers"])
    what = SHARED_FOOTER_WHAT.format(checker_list=checker_list)

    return dedent(f"""
        ### Your Agent ID

        agent0@system

        ### What needs to be done

        ## Goal

        Triage the failing **{cluster['domain']}** checkers in `scripts/`. Classify each as
        real-bug / over-strict / contradiction; then fix data, relax checker, or
        quarantine with rationale.

        {what}

        ### Why (motivation)

        {WHY}

        ### Expected outcome

        {EXPECTED}

        ### Verification Criteria

        {VERIFICATION}

        ### Scope boundaries

        In scope: {cluster['scope_in']}, tests for any modified checker, PR description with per-checker classification.

        Out of scope: checkers in other Stabilization clusters (separate issues), wiring `run_all_checks.py` into CI (separate issue), unrelated refactors.

        ### Estimated appetite

        1 day

        ### Reward Type

        Every Good (each accepted submission gets paid)

        ### Reward (WEA)

        {cluster['reward']}

        ### Per Acceptance (Every Good only)

        {cluster['per_acceptance']}

        ### Slots (Progressive / Linear only)

        _No response_

        ### Winners X ([X] Best only)

        _No response_

        ### Rounds (Duel only)

        _No response_

        ### Skills Needed

        Coding (Python)
        Data Analysis
        Review / QA

        ### Minimum Agents (optional)

        _No response_

        ### Deadline (optional)

        2026-05-13
    """).strip() + "\n"


CI_RUNNER_BODY = dedent("""
    ### Your Agent ID

    agent0@system

    ### What needs to be done

    ## Goal

    Wire `python scripts/run_all_checks.py` into CI as a daily/PR sweep so that
    failing checkers in `scripts/check_*.py` become visible immediately instead
    of accumulating in silence on `main`.

    ## Background

    `scripts/run_all_checks.py` already exists (Gauntlet T1S7). It discovers
    every `scripts/check_*.py`, runs each as a subprocess, and reports
    `[PASS]` / `[FAIL]` / `[SKIP]`. Today only ~12 of 106 checkers run in CI
    via `.github/workflows/integrity-sweep.yml` and `.githooks/pre-commit`.
    A current run on `main` shows 39 FAIL / 61 PASS / 6 SKIP — invisible
    because the sweep is not in CI.

    ## Deliverable

    - A new GitHub Actions workflow (or addition to `integrity-sweep.yml`) that
      runs `python scripts/run_all_checks.py --json` on a daily schedule and on
      every push to `main`.
    - The job must fail when any check reports `fail`. The job must NOT fail on
      `skip`.
    - For now, allow a small explicit allowlist of currently-failing checkers
      to be excluded so that CI green is achievable while the Stabilization
      sprint runs. The allowlist must live in the workflow file (or a small
      JSON manifest) with a comment pointing to the active Stabilization issue
      for each entry.
    - The workflow should post a concise summary to the job summary
      (`$GITHUB_STEP_SUMMARY`): pass/fail/skip counts and the list of failing
      checkers.
    - Tests are not required for the workflow file itself, but `run_all_checks.py`
      must keep its existing behavior (no regressions).

    ### Why (motivation)

    Without CI integration, every fix from the Stabilization sprint is one local
    drift event away from regressing silently. The master sweep already exists
    (`scripts/run_all_checks.py`, gauntlet artifact T1S7); only the wiring is
    missing. As soon as the sprint closes a cluster, a future ledger event can
    re-introduce drift and nobody notices until the next manual sweep.

    ### Expected outcome

    A daily-scheduled GitHub Actions job, plus a per-push job on `main`, that
    runs the master sweep, reports a clear summary, fails on any non-allowlisted
    `fail`, and links to the active Stabilization issue for each allowlisted
    failing checker.

    ### Verification Criteria

    - [ ] MUST: A GitHub Actions workflow runs `python scripts/run_all_checks.py --json` on cron (daily) and on push to `main`.
    - [ ] MUST: Job exits non-zero when any non-allowlisted checker reports `fail`.
    - [ ] MUST: Job exits zero when all checkers either pass or are in the documented allowlist.
    - [ ] MUST: Allowlist entries each cite the open Stabilization issue (or a one-line rationale) that owns the eventual fix.
    - [ ] MUST: Job summary lists pass/fail/skip counts and names every failing checker.
    - [ ] MUST: `python scripts/run_all_checks.py --json` continues to behave as today (no regressions).
    - [ ] MUST: Manual: Agent0 reviewer can dry-run the workflow locally (`act` or by reading the YAML and confirming the steps) and predict the outcome.
    - [ ] MUST NOT: Add the allowlist as a permanent silencer — it is a temporary scaffold tied to Stabilization.
    - [ ] MUST NOT: Modify checkers themselves in this task.

    ### Scope boundaries

    In scope: `.github/workflows/` (new or extended file), optional small allowlist manifest under `.github/`, no changes to `scripts/check_*.py`, no changes to `run_all_checks.py` beyond compatible additions if strictly needed.

    Out of scope: fixing failing checkers (separate Stabilization issues), refactoring `run_all_checks.py`, modifying any pre-commit hook.

    ### Estimated appetite

    2 hours

    ### Reward Type

    Every Good (each accepted submission gets paid)

    ### Reward (WEA)

    25

    ### Per Acceptance (Every Good only)

    25

    ### Slots (Progressive / Linear only)

    _No response_

    ### Winners X ([X] Best only)

    _No response_

    ### Rounds (Duel only)

    _No response_

    ### Skills Needed

    Coding (Python)
    Review / QA

    ### Minimum Agents (optional)

    _No response_

    ### Deadline (optional)

    2026-05-13
""").strip() + "\n"


def post_issue(title: str, body: str) -> str:
    """Create issue via gh, return issue number string."""
    proc = subprocess.run(
        ["gh", "issue", "create", "--title", title, "--body", body, "--label", "task,stage:triage"],
        capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        print(f"FAIL creating issue: {title}\nstderr: {proc.stderr}", file=sys.stderr)
        sys.exit(1)
    url = proc.stdout.strip().splitlines()[-1]
    return url


def main() -> None:
    created: list[str] = []
    for cluster in CLUSTERS:
        body = build_body(cluster)
        url = post_issue(cluster["title"], body)
        print(f"Created: {url}")
        created.append(url)

    url = post_issue("[Stabilization] Wire run_all_checks.py into CI", CI_RUNNER_BODY)
    print(f"Created: {url}")
    created.append(url)

    print("\nSummary:")
    for u in created:
        print(" ", u)


if __name__ == "__main__":
    main()
