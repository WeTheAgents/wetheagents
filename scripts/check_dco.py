#!/usr/bin/env python3
"""
DCO (Developer Certificate of Origin) check.

Verifies that every commit in a PR contains a valid Signed-off-by trailer.
Exempts bot commits (GitHub Actions, dependabot, agent0 system operations).

Run in CI with: python scripts/check_dco.py --diff-base <base_sha> --head <pr_head_sha>

Usage:
  python scripts/check_dco.py --diff-base main
  python scripts/check_dco.py --diff-base abc123 --head def456
  python scripts/check_dco.py --commits abc123 def456
"""

import argparse
import re
import subprocess
import sys

BOT_EMAIL_PATTERNS = [
    r".+\[bot\]@users\.noreply\.github\.com$",  # GitHub Apps (verified domain)
    r"^noreply@github\.com$",                   # GitHub merge commits
    r"^agent0@.*",                              # Agent0 system operations
]

SIGNOFF_RE = re.compile(r"^Signed-off-by: .+ <.+>$", re.MULTILINE)


def is_bot_commit(author_email: str) -> bool:
    """Check if the commit author email matches a known bot pattern."""
    for pattern in BOT_EMAIL_PATTERNS:
        if re.match(pattern, author_email, re.IGNORECASE):
            return True
    return False


def check_dco(commits: list[dict]) -> list[dict]:
    """
    Check commits for valid Signed-off-by trailer.

    Args:
        commits: list of {"sha": str, "author_email": str, "message": str}

    Returns:
        list of failing commits (those missing sign-off)
    """
    failures = []
    for commit in commits:
        if is_bot_commit(commit["author_email"]):
            continue
        if not SIGNOFF_RE.search(commit["message"]):
            failures.append(commit)
    return failures


def get_commits(
    diff_base: str | None,
    shas: list[str] | None,
    head: str = "HEAD",
) -> list[dict]:
    """Read commits from git log."""
    if shas:
        raw_shas = shas
    elif diff_base:
        result = subprocess.run(
            ["git", "log", "--format=%H", f"{diff_base}...{head}"],
            capture_output=True, text=True, check=True,
        )
        raw_shas = [s for s in result.stdout.strip().split("\n") if s.strip()]
    else:
        print("Error: provide --diff-base or --commits.")
        sys.exit(2)

    commits = []
    for sha in raw_shas:
        email_result = subprocess.run(
            ["git", "log", "-1", "--format=%ae", sha],
            capture_output=True, text=True, check=True,
        )
        msg_result = subprocess.run(
            ["git", "log", "-1", "--format=%B", sha],
            capture_output=True, text=True, check=True,
        )
        commits.append({
            "sha": sha,
            "author_email": email_result.stdout.strip(),
            "message": msg_result.stdout.strip(),
        })
    return commits


def main() -> None:
    parser = argparse.ArgumentParser(description="DCO check")
    parser.add_argument("--diff-base", help="Git ref to diff against (e.g. origin/main)")
    parser.add_argument("--head", default="HEAD", help="PR head SHA (default: HEAD)")
    parser.add_argument("--commits", nargs="*", help="Explicit commit SHAs to check")
    args = parser.parse_args()

    commits = get_commits(args.diff_base, args.commits, head=args.head)
    if not commits:
        print("No commits to check. PASS")
        sys.exit(0)

    failures = check_dco(commits)

    print("--- DCO Check ---")
    print(f"Commits checked: {len(commits)}")

    if failures:
        print(f"\n{len(failures)} commit(s) missing Signed-off-by:\n")
        for f in failures:
            short_sha = f["sha"][:8]
            first_line = f["message"].split("\n")[0]
            print(f"  FAIL: {short_sha} {first_line}")

        print("\nRemediation:")
        print("  Add a Signed-off-by trailer to each commit:")
        print("    git commit --amend -s          # fix the last commit")
        print("    git rebase --signoff HEAD~N     # fix the last N commits")
        print("")
        print("  The Signed-off-by trailer certifies you have the right to submit")
        print("  this code under the project's license (AGPL-3.0). See CONTRIBUTING.md.")
        print("\nStatus: FAIL")
        sys.exit(1)
    else:
        print("All commits have valid Signed-off-by trailers.")
        print("\nStatus: PASS")
        sys.exit(0)


if __name__ == "__main__":
    main()
