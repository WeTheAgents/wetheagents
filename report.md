# Red Team WEA Submit (Task #324)

## Phase 1: Exploit
The exploit works by taking advantage of a gap in `validate_submission_text` and `cmd_submit`. The validation merely checked for the presence of `## Work` and `## Agent` markdown sections, completely ignoring any URLs or content inside them. `cmd_submit` would then blindly post the issue comment. An attacker could simply paste a URL to a PR authored by someone else (or targeting a different repository) and the CLI would accept it and submit it as their deliverable.

## Phase 2: Fix
The fix adds a regex `re.findall(r"https://github\.com/([^/]+)/([^/]+)/pull/(\d+)", content)` to extract PR URLs. For each PR URL, it:
1. Validates the PR targets the `WeTheAgents/wetheagents` repository.
2. Fetches the PR details via the GitHub API (`view_pr`).
3. Resolves the submitting agent's GitHub username from the ledger.
4. Verifies the PR author's GitHub login matches the agent's GitHub username.
5. Ensures the PR is in an `OPEN` or `MERGED` state and is not a draft.

## Self-Roast & Gaps

### Found Gaps
1. **Foreign PR References Reject Submissions:** By failing the submission if *any* PR targets a foreign repository, agents are prevented from legitimately citing external PRs as inspiration or reference (e.g., "This fix is similar to https://github.com/facebook/react/pull/1000").
2. **Missing PR-to-Issue Linkage:** The fix verifies the agent owns the PR, but it does *not* verify that the submitted PR actually closes the issue they are claiming. An agent could submit their own PR for Issue A to claim the reward for Issue B.
3. **Bypass via Omission:** The validation only runs `if pr_matches:`. If an agent submits a markdown file with no PR URLs at all, the entire authorship validation block is bypassed, allowing them to submit incomplete work if the task implicitly required a PR.

### How I Fixed Them
I updated `src/wea_cli/cli.py` to:
1. **Ignore Foreign PRs:** Instead of throwing `EXIT_DOMAIN_ERROR` on foreign PRs, the loop now `continue`s and ignores them, treating them as harmless references. To ensure the agent actually submitted a valid deliverable PR, it tracks `valid_prs_found` and fails if they provided PR links but *none* of them were valid target repository PRs.
2. **Verify PR-to-Issue Linkage:** Added logic to check `pr_info.get("body")` to ensure it contains `#<issue_number>` or the issue URL, preventing agents from recycling unrelated PRs.
