"""Code survival tracker — Gene Judge support tool.

Measures per-agent code survival rates by combining:
- git log --no-merges --numstat: lines ever authored (lines_authored)
- git blame --porcelain: lines currently surviving in HEAD (lines_surviving)

survival_rate = clamp(lines_surviving / lines_authored, 0.0, 1.0)

Output: JSON report to stdout or --output. Data collection only — no pipeline gating.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from email.utils import parsedate
from pathlib import Path


# Default excluded path prefixes
DEFAULT_EXCLUDES: list[str] = [
    "ledger/",
    "genomes/",
    ".github/",
    "agent0_diary/",
]

# Task pattern: [Task #N] or bare #N (not adjacent to other word chars)
TASK_PATTERN = re.compile(r"\[Task\s*#(\d+)\]|(?<!\w)#(\d+)(?!\w)")

UNKNOWN_AGENT = "__unknown__"

# Date patterns accepted as valid --since values (heuristic, not exhaustive)
_DATE_FORMATS = [
    "%Y-%m-%d",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%d %H:%M:%S",
    "%d %b %Y",
    "%B %d %Y",
    "%b %d %Y",
]


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------


def _git(args: list[str], cwd: str) -> str:
    """Run a git command, return stdout. Raises CalledProcessError on failure."""
    proc = subprocess.run(
        ["git"] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise subprocess.CalledProcessError(
            proc.returncode, ["git"] + args, proc.stdout, proc.stderr
        )
    return proc.stdout


def find_repo_root(cwd: str) -> str:
    """Return the absolute git repo root. Exits 1 if not in a repo."""
    proc = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        print("error: not inside a git repository", file=sys.stderr)
        sys.exit(1)
    return proc.stdout.strip()


def _is_commit_ref(repo_root: str, since: str) -> bool:
    """Return True if since resolves as a git commit object."""
    proc = subprocess.run(
        ["git", "rev-parse", "--verify", since + "^{commit}"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0


def _looks_like_date(value: str) -> bool:
    """Return True if value looks like a date string (heuristic check)."""
    # Try RFC 2822 / email format
    if parsedate(value) is not None:
        return True
    # Try common ISO-like formats
    for fmt in _DATE_FORMATS:
        try:
            datetime.strptime(value, fmt)
            return True
        except ValueError:
            continue
    # Try unix timestamp (all digits)
    if value.lstrip("-").isdigit():
        return True
    return False


def validate_since(repo_root: str, since: str) -> str:
    """Validate --since as a commit hash or a recognisable date string.

    Returns since unchanged if valid. Exits 1 with a clear message otherwise.
    """
    if _is_commit_ref(repo_root, since):
        return since
    if _looks_like_date(since):
        return since
    print(
        f"error: --since '{since}' is neither a valid commit hash "
        "nor a recognisable date string",
        file=sys.stderr,
    )
    sys.exit(1)


def _commit_timestamp(repo_root: str, commit_hash: str) -> int:
    """Return the Unix timestamp of a commit."""
    out = _git(["show", "-s", "--format=%ct", commit_hash], repo_root)
    return int(out.strip())


def _since_log_args(repo_root: str, since: str) -> list[str]:
    """Build git log range args for the since boundary.

    For commit hashes: use --since=<timestamp-1> so the commit itself is included.
    For date strings: use --since=<date> directly.
    """
    if _is_commit_ref(repo_root, since):
        # Resolve to full hash
        full_hash = _git(["rev-parse", since + "^{commit}"], repo_root).strip()
        ts = _commit_timestamp(repo_root, full_hash)
        # Use timestamp - 1 so --since includes the commit itself
        return [f"--since={ts - 1}"]
    return [f"--since={since}"]


# ---------------------------------------------------------------------------
# Author map
# ---------------------------------------------------------------------------


def load_author_map(map_path: Path) -> dict[str, str]:
    """Load email->agent_id JSON. Exits 1 if missing or invalid."""
    if not map_path.exists():
        print(f"error: author_map.json not found at {map_path}", file=sys.stderr)
        sys.exit(1)
    try:
        with map_path.open() as fh:
            return json.load(fh)
    except json.JSONDecodeError as exc:
        print(f"error: author_map.json is not valid JSON: {exc}", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# File listing & filtering
# ---------------------------------------------------------------------------


def list_tracked_files(repo_root: str) -> list[str]:
    """Return all tracked .py and .json files in HEAD."""
    out = _git(["ls-files", "--", "*.py", "*.json"], repo_root)
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


def apply_filters(
    files: list[str],
    includes: list[str],
    excludes: list[str],
) -> list[str]:
    """Apply include/exclude glob filters. Exclude takes precedence over include."""
    result = []
    for f in files:
        excluded = any(
            fnmatch.fnmatch(f, pat) or f.startswith(pat) for pat in excludes
        )
        if excluded:
            continue
        if includes:
            included = any(fnmatch.fnmatch(f, pat) for pat in includes)
            if not included:
                continue
        result.append(f)
    return result


# ---------------------------------------------------------------------------
# git blame --porcelain parser
# ---------------------------------------------------------------------------


def parse_blame_porcelain(output: str) -> tuple[dict[str, int], dict[str, str]]:
    """Parse git blame --porcelain output.

    Returns:
        hash_to_linecount: {commit_hash: number_of_lines_in_this_file}
        hash_to_email:     {commit_hash: author_email}
    """
    hash_to_linecount: dict[str, int] = defaultdict(int)
    hash_to_email: dict[str, str] = {}

    lines = output.splitlines()
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        parts = line.split()
        # Commit header: 40 hex chars + at least 2 more fields
        if (
            len(parts) >= 3
            and len(parts[0]) == 40
            and all(c in "0123456789abcdefABCDEF" for c in parts[0])
        ):
            commit_hash = parts[0]
            hash_to_linecount[commit_hash] += 1
            i += 1
            # Read header fields until content line (starts with \t)
            while i < n:
                field = lines[i]
                if field.startswith("\t"):
                    i += 1  # consume content line
                    break
                if field.startswith("author-mail ") and commit_hash not in hash_to_email:
                    email = field[len("author-mail "):].strip().strip("<>")
                    hash_to_email[commit_hash] = email
                i += 1
        else:
            i += 1

    return dict(hash_to_linecount), hash_to_email


def blame_file(
    repo_root: str, filepath: str
) -> tuple[dict[str, int], dict[str, str]]:
    """Run git blame --porcelain on filepath. Returns empty dicts on failure."""
    try:
        output = _git(["blame", "--porcelain", filepath], repo_root)
    except subprocess.CalledProcessError:
        return {}, {}
    return parse_blame_porcelain(output)


# ---------------------------------------------------------------------------
# git log helpers
# ---------------------------------------------------------------------------


def parse_task_id(subject: str) -> str | None:
    """Extract first task ID from a commit subject. Returns None if not found."""
    m = TASK_PATTERN.search(subject)
    if m:
        return m.group(1) or m.group(2)
    return None


def collect_commit_task_map(
    repo_root: str, log_args: list[str]
) -> dict[str, str | None]:
    """Return {full_commit_hash: task_id_or_None} for commits in the since window."""
    out = _git(["log", "--no-merges", "--format=%H %s"] + log_args, repo_root)
    result: dict[str, str | None] = {}
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) >= 1 and len(parts[0]) == 40:
            commit_hash = parts[0]
            subject = parts[1] if len(parts) > 1 else ""
            result[commit_hash] = parse_task_id(subject)
    return result


def _file_matches_filter(
    filepath: str,
    includes: list[str],
    excludes: list[str],
) -> bool:
    """Return True if filepath passes the include/exclude filter.

    Also requires the file to end in .py or .json (default type filter).
    excludes takes precedence over includes.
    """
    # Default type filter: only .py and .json
    if not (filepath.endswith(".py") or filepath.endswith(".json")):
        return False
    # Exclude check first
    if any(fnmatch.fnmatch(filepath, pat) or filepath.startswith(pat) for pat in excludes):
        return False
    # Include check
    if includes:
        return any(fnmatch.fnmatch(filepath, pat) for pat in includes)
    return True


def collect_lines_authored(
    repo_root: str,
    log_args: list[str],
    author_map: dict[str, str],
    includes: list[str],
    excludes: list[str],
) -> tuple[dict[str, dict[str | None, int]], set[str]]:
    """Collect lines_authored per (agent_id, task_id) via git log --numstat.

    Uses glob-based file filtering (not the current ls-files set) so that
    deleted files are included in lines_authored.

    Returns:
        authored[agent_id][task_id_or_None] = line_count
        warned_emails: set of emails that triggered unknown-author warnings
    """
    out = _git(
        ["log", "--no-merges", "--numstat", "--format=%H %ae %s"] + log_args,
        repo_root,
    )

    authored: dict[str, dict[str | None, int]] = defaultdict(lambda: defaultdict(int))
    warned_emails: set[str] = set()

    current_email: str | None = None
    current_subject: str | None = None

    for line in out.splitlines():
        if not line.strip():
            continue

        parts = line.split(None, 2)
        # Commit header: 40-hex + email + subject
        if (
            len(parts) >= 2
            and len(parts[0]) == 40
            and all(c in "0123456789abcdefABCDEF" for c in parts[0])
        ):
            current_email = parts[1]
            current_subject = parts[2] if len(parts) > 2 else ""
            continue

        # numstat line: "<added>\t<deleted>\t<filepath>"
        tab = line.split("\t")
        if len(tab) >= 3 and current_email is not None:
            added_str, filepath = tab[0], tab[2]
            if added_str == "-":
                continue  # binary file
            try:
                added = int(added_str)
            except ValueError:
                continue
            if added == 0:
                continue
            # Filter by glob patterns (works for deleted files too)
            if not _file_matches_filter(filepath, includes, excludes):
                continue

            # Resolve agent
            agent_id = author_map.get(current_email)
            if agent_id is None:
                if current_email not in warned_emails:
                    print(
                        f"warning: unknown author '{current_email}' — attributed to {UNKNOWN_AGENT}",
                        file=sys.stderr,
                    )
                    warned_emails.add(current_email)
                agent_id = UNKNOWN_AGENT

            task_id = parse_task_id(current_subject or "")
            authored[agent_id][task_id] += added

    return authored, warned_emails


def collect_lines_surviving(
    repo_root: str,
    filtered_files: list[str],
    author_map: dict[str, str],
    warned_emails: set[str],
    commit_task_map: dict[str, str | None],
) -> tuple[dict[tuple[str, str | None], int], set[str]]:
    """Run git blame --porcelain once per file (eager approach).

    Attributes surviving lines to (agent_id, task_id). task_id is taken from
    commit_task_map; commits outside the since window get task_id=None.

    Returns:
        surviving[(agent_id, task_id)] = line_count
        warned_emails (updated)
    """
    surviving: dict[tuple[str, str | None], int] = defaultdict(int)

    for filepath in filtered_files:
        hash_to_linecount, hash_to_email = blame_file(repo_root, filepath)
        for commit_hash, line_count in hash_to_linecount.items():
            email = hash_to_email.get(commit_hash, "")
            agent_id = author_map.get(email)
            if agent_id is None:
                if email and email not in warned_emails:
                    print(
                        f"warning: unknown author '{email}' (blame) — attributed to {UNKNOWN_AGENT}",
                        file=sys.stderr,
                    )
                    warned_emails.add(email)
                agent_id = UNKNOWN_AGENT

            # task_id only for commits in the since window
            task_id = commit_task_map.get(commit_hash)  # None if outside window
            surviving[(agent_id, task_id)] += line_count

    return surviving, warned_emails


# ---------------------------------------------------------------------------
# Report assembly
# ---------------------------------------------------------------------------


def build_report(
    since: str,
    authored: dict[str, dict[str | None, int]],
    surviving: dict[tuple[str, str | None], int],
    agent_filter: str | None,
) -> dict:
    """Assemble the final JSON-serialisable report."""
    # Pre-aggregate surviving by agent and by (agent, task)
    surviving_by_agent: dict[str, int] = defaultdict(int)
    surviving_by_agent_task: dict[str, dict[str | None, int]] = defaultdict(
        lambda: defaultdict(int)
    )
    for (agent_id, task_id), count in surviving.items():
        surviving_by_agent[agent_id] += count
        surviving_by_agent_task[agent_id][task_id] += count

    agents_out = []
    for agent_id in sorted(authored.keys()):
        if agent_filter and agent_id != agent_filter:
            continue

        task_map = authored[agent_id]
        agent_authored = sum(task_map.values())
        if agent_authored == 0:
            continue  # Scenario 6: omit zero-line agents

        agent_surviving = surviving_by_agent.get(agent_id, 0)
        agent_rate = (
            min(1.0, agent_surviving / agent_authored) if agent_authored > 0 else 0.0
        )

        # Per-task entries (skip None task_id — untagged commits)
        tasks_out = []
        for task_id, t_authored in sorted(
            task_map.items(), key=lambda x: (x[0] is None, x[0] or "")
        ):
            if task_id is None:
                continue
            if t_authored == 0:
                continue
            t_surviving = surviving_by_agent_task.get(agent_id, {}).get(task_id, 0)
            t_rate = min(1.0, t_surviving / t_authored) if t_authored > 0 else 0.0
            tasks_out.append({
                "task_id": task_id,
                "lines_authored": t_authored,
                "lines_surviving": t_surviving,
                "survival_rate": round(t_rate, 4),
            })

        agents_out.append({
            "agent_id": agent_id,
            "lines_authored": agent_authored,
            "lines_surviving": agent_surviving,
            "survival_rate": round(agent_rate, 4),
            "tasks": tasks_out,
        })

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "since_commit": since,
        "agents": agents_out,
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Code survival tracker. Measures per-agent code survival via git blame."
    )
    parser.add_argument(
        "--since",
        required=True,
        help="Git commit hash or date string (baseline for lines_authored).",
    )
    parser.add_argument(
        "--agent",
        default=None,
        help="Restrict output to a single agent ID.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Write JSON to this path instead of stdout.",
    )
    parser.add_argument(
        "--include",
        action="append",
        default=[],
        metavar="GLOB",
        help="Include only files matching this glob (repeatable).",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="GLOB",
        help="Exclude files matching glob (repeatable). Takes precedence over --include.",
    )
    args = parser.parse_args()

    # Validate repo
    repo_root = find_repo_root(".")

    # Validate --since
    since = validate_since(repo_root, args.since)

    # Load author map — look in repo's scripts/ dir first, then next to this script
    map_path = Path(repo_root) / "scripts" / "author_map.json"
    if not map_path.exists():
        map_path = Path(__file__).parent / "author_map.json"
    author_map = load_author_map(map_path)

    # Build effective filter lists
    effective_excludes = DEFAULT_EXCLUDES + args.exclude

    # List and filter current HEAD files (for git blame / lines_surviving)
    all_files = list_tracked_files(repo_root)
    filtered_files = apply_filters(all_files, args.include, effective_excludes)

    # Build git log range args
    log_args = _since_log_args(repo_root, since)

    # Collect lines_authored (uses glob filters, not ls-files set — covers deleted files)
    authored, warned_emails = collect_lines_authored(
        repo_root, log_args, author_map, args.include, effective_excludes
    )

    # Build commit→task map (for per-task surviving attribution)
    commit_task_map = collect_commit_task_map(repo_root, log_args)

    # Collect lines_surviving (eager: once per file)
    surviving, _warned = collect_lines_surviving(
        repo_root, filtered_files, author_map, warned_emails, commit_task_map
    )

    # Build and emit report
    report = build_report(since, authored, surviving, args.agent)
    output_json = json.dumps(report, indent=2)

    if args.output:
        Path(args.output).write_text(output_json)
    else:
        print(output_json)


if __name__ == "__main__":
    main()
