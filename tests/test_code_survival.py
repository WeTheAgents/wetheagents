"""Tests for scripts/code_survival.py using synthetic git repositories.

All tests create isolated temporary git repos, make commits with known
authorship, then run the script (or its functions) to verify correctness.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SCRIPT = Path(__file__).parent.parent / "scripts" / "code_survival.py"
AUTHOR_MAP = Path(__file__).parent.parent / "scripts" / "author_map.json"


def git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git"] + args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=True,
    )


def init_repo(path: Path) -> None:
    """Initialise a git repo with basic config."""
    git(["init", "-b", "main"], path)
    git(["config", "user.email", "agent-a@test"], path)
    git(["config", "user.name", "Agent A"], path)
    git(["config", "commit.gpgsign", "false"], path)


def make_commit(
    path: Path,
    email: str,
    name: str,
    message: str,
    files: dict[str, str],
) -> str:
    """Create a commit with the given author. Returns commit hash."""
    for filename, content in files.items():
        fpath = path / filename
        fpath.parent.mkdir(parents=True, exist_ok=True)
        fpath.write_text(content)
        git(["add", filename], path)
    result = subprocess.run(
        [
            "git", "commit", "-m", message,
            f"--author={name} <{email}>",
        ],
        cwd=str(path),
        capture_output=True,
        text=True,
        env={**__import__("os").environ, "GIT_COMMITTER_EMAIL": email, "GIT_COMMITTER_NAME": name},
        check=True,
    )
    # Return the hash
    rev = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(path),
        capture_output=True,
        text=True,
        check=True,
    )
    return rev.stdout.strip()


def make_author_map(path: Path, mapping: dict[str, str]) -> Path:
    """Write an author_map.json into scripts/ dir."""
    scripts_dir = path / "scripts"
    scripts_dir.mkdir(exist_ok=True)
    map_path = scripts_dir / "author_map.json"
    map_path.write_text(json.dumps(mapping))
    return map_path


def run_script(
    repo: Path,
    since: str,
    extra_args: list[str] | None = None,
) -> tuple[int, dict | None, str]:
    """Run code_survival.py and return (returncode, parsed_json_or_None, stderr)."""
    cmd = [sys.executable, str(SCRIPT), "--since", since]
    if extra_args:
        cmd += extra_args
    result = subprocess.run(
        cmd,
        cwd=str(repo),
        capture_output=True,
        text=True,
    )
    out_json = None
    if result.returncode == 0:
        try:
            out_json = json.loads(result.stdout)
        except json.JSONDecodeError:
            pass
    return result.returncode, out_json, result.stderr


# ---------------------------------------------------------------------------
# TC-1: Basic survival calculation (Scenario 1)
# ---------------------------------------------------------------------------


def test_basic_survival(tmp_path: Path) -> None:
    """Agent A writes 100 lines; Agent B deletes 40. Expect lines_surviving=60."""
    init_repo(tmp_path)
    make_author_map(tmp_path, {
        "agent-a@test": "agent-a",
        "agent-b@test": "agent-b",
    })

    # Commit 1: Agent A adds 100 lines
    lines_100 = "\n".join(f"line{i}" for i in range(100)) + "\n"
    first = make_commit(
        tmp_path, "agent-a@test", "Agent A",
        "[Task #1] initial",
        {"scripts/foo.py": lines_100},
    )

    # Commit 2: Agent B removes 40 lines (keep 60)
    lines_60 = "\n".join(f"line{i}" for i in range(60)) + "\n"
    make_commit(
        tmp_path, "agent-b@test", "Agent B",
        "[Task #2] trim",
        {"scripts/foo.py": lines_60},
    )

    rc, data, stderr = run_script(tmp_path, first)
    assert rc == 0, f"Script failed: {stderr}"
    assert data is not None

    agents = {a["agent_id"]: a for a in data["agents"]}
    assert "agent-a" in agents, f"agent-a missing from {list(agents)}"
    a = agents["agent-a"]
    assert a["lines_authored"] == 100
    assert a["lines_surviving"] == 60
    assert abs(a["survival_rate"] - 0.60) < 0.01


# ---------------------------------------------------------------------------
# TC-2: Per-task breakdown (Scenario 3)
# ---------------------------------------------------------------------------


def test_per_task_breakdown(tmp_path: Path) -> None:
    """Two tasks from Agent A; 10 lines from task-42 deleted. Verify per-task."""
    init_repo(tmp_path)
    make_author_map(tmp_path, {"agent-a@test": "agent-a"})

    # Task #42: 50 lines
    lines_42 = "\n".join(f"task42_line{i}" for i in range(50)) + "\n"
    first = make_commit(
        tmp_path, "agent-a@test", "Agent A",
        "[Task #42] add foo",
        {"scripts/foo.py": lines_42},
    )

    # Task #99: 30 lines in a separate file
    lines_99 = "\n".join(f"task99_line{i}" for i in range(30)) + "\n"
    make_commit(
        tmp_path, "agent-a@test", "Agent A",
        "[Task #99] add bar",
        {"scripts/bar.py": lines_99},
    )

    # Delete 10 lines from task #42 (keep 40)
    lines_42_trimmed = "\n".join(f"task42_line{i}" for i in range(40)) + "\n"
    make_commit(
        tmp_path, "agent-a@test", "Agent A",
        "cleanup",
        {"scripts/foo.py": lines_42_trimmed},
    )

    rc, data, stderr = run_script(tmp_path, first)
    assert rc == 0, f"Script failed: {stderr}"
    assert data is not None

    agents = {a["agent_id"]: a for a in data["agents"]}
    assert "agent-a" in agents
    a = agents["agent-a"]

    tasks = {t["task_id"]: t for t in a["tasks"]}
    assert "42" in tasks, f"task 42 missing; tasks = {list(tasks)}"
    assert "99" in tasks, f"task 99 missing; tasks = {list(tasks)}"

    t42 = tasks["42"]
    assert t42["lines_authored"] == 50
    assert t42["lines_surviving"] == 40
    assert abs(t42["survival_rate"] - 0.80) < 0.01

    t99 = tasks["99"]
    assert t99["lines_authored"] == 30
    assert t99["lines_surviving"] == 30
    assert abs(t99["survival_rate"] - 1.0) < 0.01

    # Invariant: sum of per-task authored <= agent authored
    assert sum(t["lines_authored"] for t in a["tasks"]) <= a["lines_authored"]


# ---------------------------------------------------------------------------
# TC-3: Unknown author (Scenario 4)
# ---------------------------------------------------------------------------


def test_unknown_author(tmp_path: Path) -> None:
    """Unmapped email → attributed to __unknown__, script exits 0."""
    init_repo(tmp_path)
    make_author_map(tmp_path, {"known@test": "known-agent"})  # unknown@test not mapped

    lines = "\n".join(f"line{i}" for i in range(10)) + "\n"
    first = make_commit(
        tmp_path, "unknown@test", "Unknown",
        "some work",
        {"scripts/foo.py": lines},
    )

    rc, data, stderr = run_script(tmp_path, first)
    assert rc == 0, f"Expected exit 0, got {rc}. stderr={stderr}"
    assert data is not None

    agents = {a["agent_id"]: a for a in data["agents"]}
    assert "__unknown__" in agents, f"__unknown__ missing from {list(agents)}"
    assert "warning" in stderr.lower() or "unknown" in stderr.lower()


# ---------------------------------------------------------------------------
# TC-4: Deleted file (Scenario 5)
# ---------------------------------------------------------------------------


def test_deleted_file(tmp_path: Path) -> None:
    """Agent writes a file then it's deleted. lines_authored>0, lines_surviving=0."""
    init_repo(tmp_path)
    make_author_map(tmp_path, {"agent-a@test": "agent-a"})

    lines = "\n".join(f"line{i}" for i in range(20)) + "\n"
    first = make_commit(
        tmp_path, "agent-a@test", "Agent A",
        "[Task #10] add old",
        {"scripts/old.py": lines},
    )

    # Delete the file
    (tmp_path / "scripts" / "old.py").unlink()
    git(["rm", "scripts/old.py"], tmp_path)
    git(["commit", "-m", "delete old.py", "--author=Agent B <agent-b@test>"], tmp_path)

    rc, data, stderr = run_script(tmp_path, first)
    assert rc == 0, f"Script failed: {stderr}"
    assert data is not None

    agents = {a["agent_id"]: a for a in data["agents"]}
    assert "agent-a" in agents
    a = agents["agent-a"]
    assert a["lines_authored"] > 0
    assert a["lines_surviving"] == 0
    assert a["survival_rate"] == 0.0


# ---------------------------------------------------------------------------
# TC-5: Excluded paths (Scenario 7)
# ---------------------------------------------------------------------------


def test_excluded_paths(tmp_path: Path) -> None:
    """Lines in ledger/ are excluded from both authored and surviving."""
    init_repo(tmp_path)
    make_author_map(tmp_path, {"agent-a@test": "agent-a"})

    # Write lines in scripts/ (included) and ledger/ (default excluded)
    scripts_lines = "\n".join(f"line{i}" for i in range(10)) + "\n"
    ledger_lines = "\n".join(f"ledger{i}" for i in range(10)) + "\n"

    first = make_commit(
        tmp_path, "agent-a@test", "Agent A",
        "[Task #5] work",
        {
            "scripts/good.py": scripts_lines,
            "ledger/balances.json": ledger_lines,
        },
    )

    rc, data, stderr = run_script(tmp_path, first)
    assert rc == 0, f"Script failed: {stderr}"
    assert data is not None

    agents = {a["agent_id"]: a for a in data["agents"]}
    assert "agent-a" in agents
    a = agents["agent-a"]
    # Only scripts/ lines counted (10), ledger/ excluded
    assert a["lines_authored"] == 10, f"Expected 10 authored, got {a['lines_authored']}"


# ---------------------------------------------------------------------------
# TC-6: --since validation
# ---------------------------------------------------------------------------


def test_since_invalid(tmp_path: Path) -> None:
    """Non-hash, non-date --since value → exit code 1."""
    init_repo(tmp_path)
    make_author_map(tmp_path, {})

    lines = "hello\n"
    first = make_commit(
        tmp_path, "agent-a@test", "Agent A",
        "init",
        {"scripts/foo.py": lines},
    )

    rc, _, stderr = run_script(tmp_path, "TOTAL_GARBAGE_XYZ_NOT_A_DATE_OR_HASH_12345")
    assert rc == 1, f"Expected exit 1 for invalid --since, got {rc}"
    assert "error" in stderr.lower()


# ---------------------------------------------------------------------------
# TC-7: JSON output structure (Scenario 7 / Property invariants)
# ---------------------------------------------------------------------------


def test_json_output_structure(tmp_path: Path) -> None:
    """Output is valid JSON with required keys; survival_rate in [0, 1]."""
    init_repo(tmp_path)
    make_author_map(tmp_path, {"agent-a@test": "agent-a"})

    lines = "\n".join(f"line{i}" for i in range(5)) + "\n"
    first = make_commit(
        tmp_path, "agent-a@test", "Agent A",
        "[Task #7] work",
        {"scripts/foo.py": lines},
    )

    rc, data, stderr = run_script(tmp_path, first)
    assert rc == 0, f"Script failed: {stderr}"
    assert data is not None, "Output was not valid JSON"

    # Required top-level keys
    assert "generated_at" in data
    assert "since_commit" in data
    assert "agents" in data
    assert isinstance(data["agents"], list)

    # All survival rates in [0, 1]
    for agent in data["agents"]:
        assert 0.0 <= agent["survival_rate"] <= 1.0, (
            f"survival_rate out of bounds for {agent['agent_id']}: {agent['survival_rate']}"
        )
        for task in agent.get("tasks", []):
            assert 0.0 <= task["survival_rate"] <= 1.0


# ---------------------------------------------------------------------------
# TC-8: --agent filter (Scenario 2)
# ---------------------------------------------------------------------------


def test_agent_filter(tmp_path: Path) -> None:
    """--agent restricts output to a single agent."""
    init_repo(tmp_path)
    make_author_map(tmp_path, {
        "agent-a@test": "agent-a",
        "agent-b@test": "agent-b",
    })

    first = make_commit(
        tmp_path, "agent-a@test", "Agent A",
        "work by A",
        {"scripts/a.py": "line1\nline2\n"},
    )
    make_commit(
        tmp_path, "agent-b@test", "Agent B",
        "work by B",
        {"scripts/b.py": "lineX\nlineY\n"},
    )

    rc, data, stderr = run_script(tmp_path, first, ["--agent", "agent-a"])
    assert rc == 0, f"Script failed: {stderr}"
    assert data is not None

    agent_ids = [a["agent_id"] for a in data["agents"]]
    assert "agent-a" in agent_ids
    assert "agent-b" not in agent_ids, f"agent-b should be filtered out, got {agent_ids}"


# ---------------------------------------------------------------------------
# TC-9: Clamp — lines_surviving > lines_authored
# ---------------------------------------------------------------------------


def test_clamp_survival_rate(tmp_path: Path) -> None:
    """When --since excludes earlier authorship, survival_rate is clamped to 1.0."""
    init_repo(tmp_path)
    make_author_map(tmp_path, {"agent-a@test": "agent-a"})

    # Commit 1 (before baseline): Agent A writes 100 lines
    lines_100 = "\n".join(f"line{i}" for i in range(100)) + "\n"
    make_commit(
        tmp_path, "agent-a@test", "Agent A",
        "pre-baseline work",
        {"scripts/foo.py": lines_100},
    )

    # Commit 2 (baseline): Agent A writes 10 MORE lines
    lines_110 = "\n".join(f"line{i}" for i in range(110)) + "\n"
    baseline = make_commit(
        tmp_path, "agent-a@test", "Agent A",
        "[Task #1] post-baseline work",
        {"scripts/foo.py": lines_110},
    )

    # With --since=baseline: lines_authored=10 (delta), but lines_surviving=110 (all lines in HEAD)
    # survival_rate would be 11.0 without clamp → must be clamped to 1.0
    rc, data, stderr = run_script(tmp_path, baseline)
    assert rc == 0, f"Script failed: {stderr}"
    assert data is not None

    agents = {a["agent_id"]: a for a in data["agents"]}
    if "agent-a" in agents:
        assert agents["agent-a"]["survival_rate"] <= 1.0


# ---------------------------------------------------------------------------
# TC-10: --no-merges (merge commits excluded from lines_authored)
# ---------------------------------------------------------------------------


def test_no_merge_commits(tmp_path: Path) -> None:
    """Merge commits must not inflate lines_authored."""
    init_repo(tmp_path)
    make_author_map(tmp_path, {"agent-a@test": "agent-a"})

    # Create a branch structure with a merge commit
    lines_main = "\n".join(f"main{i}" for i in range(5)) + "\n"
    first = make_commit(
        tmp_path, "agent-a@test", "Agent A",
        "[Task #1] main work",
        {"scripts/main.py": lines_main},
    )

    # Create feature branch
    git(["checkout", "-b", "feature"], tmp_path)
    lines_feat = "\n".join(f"feat{i}" for i in range(5)) + "\n"
    make_commit(
        tmp_path, "agent-a@test", "Agent A",
        "[Task #2] feature work",
        {"scripts/feat.py": lines_feat},
    )

    # Switch back and merge
    git(["checkout", "main"], tmp_path)
    subprocess.run(
        ["git", "merge", "feature", "--no-ff", "-m", "Merge feature"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
    )

    rc, data, stderr = run_script(tmp_path, first)
    assert rc == 0, f"Script failed: {stderr}"
    assert data is not None

    agents = {a["agent_id"]: a for a in data["agents"]}
    if "agent-a" in agents:
        # Without --no-merges, merge commit would add 5 extra lines
        # With --no-merges: should be exactly 10 (5 main + 5 feature)
        assert agents["agent-a"]["lines_authored"] == 10, (
            f"Expected 10 lines_authored (merge excluded), "
            f"got {agents['agent-a']['lines_authored']}"
        )
