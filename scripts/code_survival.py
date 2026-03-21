"""Code survival tracker for Gene Judge.

Measures per-agent survival rate: lines authored vs. lines still alive in HEAD.
Uses eager git blame (O(files) blame calls, not O(agents*files)).
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
from pathlib import Path

# Sentinel for unmapped authors
UNKNOWN = "__unknown__"

# Default excluded path prefixes (applied with startswith and fnmatch)
DEFAULT_EXCLUDES = ["ledger/", "genomes/", ".github/", "agent0_diary/"]

# Files to track by extension
TRACKED_EXTENSIONS = {".py", ".json"}

# Regex for task IDs in commit messages
TASK_RE = re.compile(r"\[Task #(\d+)\]|(?<!\w)#(\d+)(?!\w)")

# Patterns git accepts for --since date strings
DATE_RE = re.compile(
    r"^\d{4}[-./]\d{1,2}[-./]\d{1,2}"  # ISO-like: 2020-01-01
    r"|\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}"  # US-like: 01/01/2020
    r"|\d+\s+\w+\s+ago"  # relative: 1 week ago
    r"|yesterday|today|now"  # keywords
    r"|last\s+\w+"  # last week, last month
    r"|\d{4}$"  # just year
    r"|\w+\s+\d{1,2}\s+\d{4}"  # May 1 2020
    r"|\d{4}-\d{2}-\d{2}T\d{2}:\d{2}",  # ISO datetime
    re.IGNORECASE,
)


def _run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)


def resolve_git_root(cwd: Path | None = None) -> Path:
    result = _run(["git", "rev-parse", "--show-toplevel"], cwd=cwd)
    if result.returncode != 0:
        sys.stderr.write("error: not a git repository\n")
        sys.exit(1)
    return Path(result.stdout.strip())


def _is_hash(s: str) -> bool:
    return bool(re.match(r"^[0-9a-f]{4,40}$", s, re.IGNORECASE))


def _hash_has_parent(commit_hash: str, repo: Path) -> bool:
    result = _run(["git", "rev-parse", "--verify", f"{commit_hash}^"], cwd=repo)
    return result.returncode == 0


def validate_and_resolve_since(since: str, repo: Path) -> str:
    """
    Validate --since and return a canonical form:
    - If it resolves as a git commit ref (hash, HEAD~N, etc.): return the 40-char hash.
    - If it matches a date pattern: return the original string.
    - Otherwise: exit 1.
    """
    # Always try git rev-parse first — catches hashes, HEAD~N, branch names, etc.
    result = _run(["git", "rev-parse", "--verify", since], cwd=repo)
    if result.returncode == 0:
        return result.stdout.strip()  # Canonical 40-char hash
    # Try as a date pattern recognizable by git log --since
    if DATE_RE.match(since.strip()):
        return since
    sys.stderr.write(f"error: --since value {since!r} is not a valid commit or date\n")
    sys.exit(1)


def load_author_map(path: Path) -> dict[str, str]:
    if not path.exists():
        sys.stderr.write(f"error: author_map.json not found at {path}\n")
        sys.exit(1)
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    return {k: v for k, v in data.items() if not k.startswith("_")}


def list_tracked_files(repo: Path) -> list[str]:
    result = _run(["git", "ls-files"], cwd=repo)
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line]


def apply_filters(files: list[str], includes: list[str], excludes: list[str]) -> list[str]:
    """Apply include/exclude glob filters. Exclude takes precedence."""
    out = []
    for f in files:
        if Path(f).suffix not in TRACKED_EXTENSIONS:
            continue
        if includes and not any(fnmatch.fnmatch(f, pat) for pat in includes):
            continue
        if any(fnmatch.fnmatch(f, pat) or f.startswith(pat) for pat in excludes):
            continue
        out.append(f)
    return out


def extract_task_id(subject: str) -> str | None:
    """Extract task ID from commit subject. Returns string like '42' or None."""
    m = TASK_RE.search(subject)
    if m:
        return m.group(1) or m.group(2)
    return None


def _build_log_args(since: str, repo: Path) -> list[str]:
    """Build git log command args based on whether since is a hash or date."""
    base = ["git", "log", "--no-merges", "--numstat", "--format=COMMIT %H %ae %s"]
    if _is_hash(since):
        resolved = _run(["git", "rev-parse", "--verify", since], cwd=repo).stdout.strip()
        if _hash_has_parent(resolved, repo):
            base.append(f"{resolved}^..HEAD")
        else:
            # Root commit: include entire history
            base.extend(["--ancestry-path" if False else "--all", "--", ])
            # Simplest correct approach for root: just log all without range
            base = ["git", "log", "--no-merges", "--numstat", "--format=COMMIT %H %ae %s"]
    else:
        base.append(f"--since={since}")
    return base


def _resolve_email(
    email: str,
    author_map: dict[str, str],
    warned: set[str],
) -> str:
    agent_id = author_map.get(email)
    if agent_id is None:
        if email not in warned:
            sys.stderr.write(
                f"warning: unmapped author email {email!r}; "
                f"attributing to {UNKNOWN}\n"
            )
            warned.add(email)
        author_map[email] = UNKNOWN
        return UNKNOWN
    return agent_id


def blame_file_porcelain(
    repo: Path,
    filepath: str,
    commit_tasks: dict[str, str | None],
) -> dict[tuple[str, str | None], int]:
    """
    Run git blame --porcelain and return {(email, task_id): line_count}.
    commit_tasks maps commit hash -> task_id for commits in the analysis window.
    Lines from commits outside the window get task_id=None.
    """
    result = _run(["git", "blame", "--porcelain", "--", filepath], cwd=repo)
    if result.returncode != 0:
        return {}

    commit_emails: dict[str, str] = {}
    current_hash = ""
    counts: dict[tuple[str, str | None], int] = defaultdict(int)

    for line in result.stdout.splitlines():
        if not line:
            continue
        if line[0] == "\t":
            # Content line — count it
            if current_hash:
                email = commit_emails.get(current_hash, "")
                task_id = commit_tasks.get(current_hash)  # None if not in window
                if email:
                    counts[(email, task_id)] += 1
        elif line.startswith("author-mail "):
            email = line[len("author-mail "):].strip().strip("<>")
            commit_emails[current_hash] = email
        elif len(line.split()) >= 3 and len(line.split()[0]) == 40:
            # Hash header line: <40-hex-hash> <orig-line> <final-line> [count]
            tok = line.split()[0]
            if all(c in "0123456789abcdefABCDEF" for c in tok):
                current_hash = tok

    return dict(counts)


def resolve_since_for_output(repo: Path, since: str) -> str:
    """Return a commit hash for the since_commit output field."""
    if _is_hash(since):
        r = _run(["git", "rev-parse", "--verify", since], cwd=repo)
        if r.returncode == 0:
            return r.stdout.strip()
    # Date string: find earliest matching commit
    r = _run(
        ["git", "log", "--since", since, "--format=%H", "--no-merges", "--reverse"],
        cwd=repo,
    )
    if r.returncode == 0 and r.stdout.strip():
        return r.stdout.strip().splitlines()[0]
    return since


def run_analysis(
    repo: Path,
    since: str,
    filtered_files: list[str],
    includes: list[str],
    excludes: list[str],
    author_map: dict[str, str],
    agent_filter: str | None,
) -> dict:
    """Full eager analysis with per-task blame attribution."""
    warned: set[str] = set()
    # filtered_files = files currently in HEAD (for blame)
    # For lines_authored we apply the same filter to numstat paths (including deleted files)

    # --- Step 1: git log --numstat for lines_authored ---
    if _is_hash(since):
        resolved = _run(["git", "rev-parse", "--verify", since], cwd=repo).stdout.strip()
        if _hash_has_parent(resolved, repo):
            log_range = f"{resolved}^..HEAD"
        else:
            log_range = None  # root commit: include all history
    else:
        log_range = None  # use --since flag

    log_cmd = ["git", "log", "--no-merges", "--numstat", "--format=COMMIT %H %ae %s"]
    if log_range is not None:
        log_cmd.append(log_range)
    elif _is_hash(since):
        pass  # no range = all history (root commit case)
    else:
        log_cmd.append(f"--since={since}")

    result = _run(log_cmd, cwd=repo)

    agent_authored: dict[str, int] = defaultdict(int)
    agent_task_authored: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    agent_files: dict[str, set[str]] = defaultdict(set)
    commit_tasks: dict[str, str | None] = {}

    current_hash = ""
    current_email = ""
    current_task: str | None = None

    if result.returncode == 0:
        for line in result.stdout.splitlines():
            if line.startswith("COMMIT "):
                parts = line.split(" ", 3)
                current_hash = parts[1] if len(parts) > 1 else ""
                current_email = parts[2] if len(parts) > 2 else ""
                subject = parts[3] if len(parts) > 3 else ""
                current_task = extract_task_id(subject)
                if current_hash:
                    commit_tasks[current_hash] = current_task
            elif line and "\t" in line:
                cols = line.split("\t", 2)
                if len(cols) == 3:
                    added_str, _del, filepath = cols
                    if added_str == "-":
                        continue  # binary file
                    # Apply filter to each numstat path (handles deleted files too)
                    if not apply_filters([filepath], includes, excludes):
                        continue
                    try:
                        added = int(added_str)
                    except ValueError:
                        continue
                    if added == 0 or not current_email:
                        continue
                    agent_id = _resolve_email(current_email, author_map, warned)
                    agent_authored[agent_id] += added
                    agent_files[agent_id].add(filepath)
                    if current_task is not None:
                        agent_task_authored[agent_id][current_task] += added

    # --- Step 2: Eager blame — once per file ---
    agent_surviving: dict[str, int] = defaultdict(int)
    agent_task_surviving: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for filepath in filtered_files:
        counts = blame_file_porcelain(repo, filepath, commit_tasks)
        for (email, task_id), count in counts.items():
            agent_id = _resolve_email(email, author_map, warned)
            agent_surviving[agent_id] += count
            if task_id is not None:
                agent_task_surviving[agent_id][task_id] += count

    # --- Step 3: Build output ---
    all_agents = set(agent_authored.keys())
    if agent_filter:
        all_agents = {a for a in all_agents if a == agent_filter}

    agents_out = []
    for agent_id in sorted(all_agents):
        la = agent_authored.get(agent_id, 0)
        if la == 0:
            continue  # omit agents with no lines authored (Scenario 6)
        ls = agent_surviving.get(agent_id, 0)
        sr = min(ls / la, 1.0) if la > 0 else 0.0

        tasks_out = []
        for task_id, t_authored in sorted(
            agent_task_authored.get(agent_id, {}).items(),
            key=lambda x: int(x[0]) if x[0].isdigit() else 0,
        ):
            t_surviving = agent_task_surviving.get(agent_id, {}).get(task_id, 0)
            t_sr = min(t_surviving / t_authored, 1.0) if t_authored > 0 else 0.0
            tasks_out.append(
                {
                    "task_id": task_id,
                    "lines_authored": t_authored,
                    "lines_surviving": t_surviving,
                    "survival_rate": round(t_sr, 4),
                }
            )

        agents_out.append(
            {
                "agent_id": agent_id,
                "lines_authored": la,
                "lines_surviving": ls,
                "survival_rate": round(sr, 4),
                "files_touched": sorted(agent_files.get(agent_id, set())),
                "tasks": tasks_out,
            }
        )

    since_commit = resolve_since_for_output(repo, since)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "since_commit": since_commit,
        "agents": agents_out,
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Code survival tracker: measures per-agent line survival rate."
    )
    parser.add_argument(
        "--since",
        required=True,
        help="Start of analysis window: a git commit hash or date string.",
    )
    parser.add_argument(
        "--agent",
        default=None,
        help="Filter output to a single agent ID.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output file path. Defaults to stdout.",
    )
    parser.add_argument(
        "--include",
        action="append",
        default=[],
        metavar="GLOB",
        help="Include files matching this glob (repeatable).",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="GLOB",
        help="Exclude files matching glob (repeatable). Stacks with defaults.",
    )
    args = parser.parse_args(argv)

    repo = resolve_git_root()
    # Resolve --since to canonical form (40-char hash or date string)
    since = validate_and_resolve_since(args.since, repo)

    author_map_path = repo / "scripts" / "author_map.json"
    author_map = load_author_map(author_map_path)

    excludes = DEFAULT_EXCLUDES + args.exclude
    all_files = list_tracked_files(repo)
    filtered = apply_filters(all_files, args.include, excludes)

    output = run_analysis(
        repo=repo,
        since=since,
        filtered_files=filtered,
        includes=args.include,
        excludes=excludes,
        author_map=author_map,
        agent_filter=args.agent,
    )

    json_str = json.dumps(output, indent=2)
    if args.output:
        Path(args.output).write_text(json_str, encoding="utf-8")
    else:
        sys.stdout.write(json_str + "\n")


if __name__ == "__main__":
    main()
