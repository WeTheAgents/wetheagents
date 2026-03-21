"""Tests for scripts/code_survival.py using synthetic git repos."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

# Add scripts/ to path so we can import code_survival directly
SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import code_survival  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def git(args: list[str], cwd: Path, env: dict | None = None) -> subprocess.CompletedProcess:
    base_env = {**os.environ, **(env or {})}
    result = subprocess.run(
        ["git"] + args,
        capture_output=True,
        text=True,
        cwd=cwd,
        env=base_env,
    )
    assert result.returncode == 0, f"git {args} failed:\n{result.stderr}"
    return result


def init_repo(tmp_path: Path, author_email: str = "a@test.com") -> Path:
    """Init a bare git repo with identity configured."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(["init"], cwd=repo)
    git(["config", "user.email", author_email], cwd=repo)
    git(["config", "user.name", "Test User"], cwd=repo)
    return repo


def commit(
    repo: Path,
    message: str,
    files: dict[str, str],
    author_email: str | None = None,
) -> str:
    """Write files and create a commit. Returns commit hash."""
    for filepath, content in files.items():
        dest = repo / filepath
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
        git(["add", filepath], cwd=repo)

    env: dict[str, str] = {}
    if author_email:
        env["GIT_AUTHOR_EMAIL"] = author_email
        env["GIT_AUTHOR_NAME"] = "Test User"
        env["GIT_COMMITTER_EMAIL"] = author_email
        env["GIT_COMMITTER_NAME"] = "Test User"

    git(["commit", "-m", message, "--allow-empty"], cwd=repo, env=env or None)
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True, text=True, cwd=repo,
    )
    return result.stdout.strip()


def make_author_map(tmp_path: Path, mapping: dict[str, str]) -> Path:
    """Write an author_map.json and return its path."""
    p = tmp_path / "author_map.json"
    p.write_text(json.dumps(mapping), encoding="utf-8")
    return p


def run_script(
    repo: Path,
    since: str,
    author_map_path: Path,
    extra_args: list[str] | None = None,
) -> tuple[int, dict | None, str]:
    """Run code_survival.py as a subprocess. Returns (returncode, json_data, stderr)."""
    cmd = [
        sys.executable,
        str(SCRIPTS_DIR / "code_survival.py"),
        "--since", since,
    ]
    if extra_args:
        cmd.extend(extra_args)

    # Patch author_map path: we need to monkey-patch or use a workaround.
    # The script looks for scripts/author_map.json relative to git root.
    # For tests: copy author_map.json into repo/scripts/author_map.json
    scripts_dir = repo / "scripts"
    scripts_dir.mkdir(exist_ok=True)
    (scripts_dir / "author_map.json").write_text(
        author_map_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=repo,
    )
    data = None
    if result.returncode == 0 and result.stdout.strip():
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            pass
    return result.returncode, data, result.stderr


# ---------------------------------------------------------------------------
# TC-1: Basic survival calculation (Scenario 1)
# ---------------------------------------------------------------------------


class TestBasicSurvival:
    def test_lines_authored_and_surviving(self, tmp_path: Path) -> None:
        """Agent A authors 10 lines; Agent B deletes 4 of them."""
        repo = init_repo(tmp_path, author_email="agent-a@test.com")

        # Agent A: write 10 lines
        content_10 = "\n".join(f"line{i} = {i}" for i in range(10)) + "\n"
        first_hash = commit(
            repo, "[Task #1] initial",
            {"scripts/foo.py": content_10},
            author_email="agent-a@test.com",
        )

        # Agent B: delete lines 0-3 (4 lines), keep lines 4-9 (6 lines)
        content_6 = "\n".join(f"line{i} = {i}" for i in range(4, 10)) + "\n"
        commit(
            repo, "[Task #2] trim",
            {"scripts/foo.py": content_6},
            author_email="agent-b@test.com",
        )

        author_map = make_author_map(tmp_path, {
            "agent-a@test.com": "agent-a",
            "agent-b@test.com": "agent-b",
        })

        rc, data, _stderr = run_script(repo, first_hash, author_map)
        assert rc == 0
        assert data is not None

        agents = {a["agent_id"]: a for a in data["agents"]}
        assert "agent-a" in agents
        a = agents["agent-a"]
        assert a["lines_authored"] == 10
        assert a["lines_surviving"] == 6
        assert a["survival_rate"] == pytest.approx(0.6, abs=0.001)

    def test_output_has_required_keys(self, tmp_path: Path) -> None:
        """JSON output must have generated_at, since_commit, agents."""
        repo = init_repo(tmp_path, author_email="agent-a@test.com")
        content = "\n".join(f"x{i} = {i}" for i in range(5)) + "\n"
        first = commit(repo, "init", {"scripts/foo.py": content}, author_email="agent-a@test.com")

        author_map = make_author_map(tmp_path, {"agent-a@test.com": "agent-a"})
        rc, data, _ = run_script(repo, first, author_map)
        assert rc == 0
        assert data is not None
        assert "generated_at" in data
        assert "since_commit" in data
        assert "agents" in data


# ---------------------------------------------------------------------------
# TC-2: Per-task breakdown (Scenario 3)
# ---------------------------------------------------------------------------


class TestPerTaskBreakdown:
    def test_per_task_lines_authored(self, tmp_path: Path) -> None:
        """Two commits from Agent A with distinct task tags; verify per-task breakdown."""
        repo = init_repo(tmp_path, author_email="agent-a@test.com")

        # Task 42: 5 lines
        lines_42 = "\n".join(f"a{i} = {i}" for i in range(5)) + "\n"
        first = commit(
            repo, "[Task #42] add foo",
            {"scripts/foo.py": lines_42},
            author_email="agent-a@test.com",
        )

        # Task 99: 3 lines (separate file to keep things clean)
        lines_99 = "\n".join(f"b{i} = {i}" for i in range(3)) + "\n"
        commit(
            repo, "[Task #99] add bar",
            {"scripts/bar.py": lines_99},
            author_email="agent-a@test.com",
        )

        author_map = make_author_map(tmp_path, {"agent-a@test.com": "agent-a"})
        rc, data, _ = run_script(repo, first, author_map)
        assert rc == 0
        assert data is not None

        agents = {a["agent_id"]: a for a in data["agents"]}
        assert "agent-a" in agents
        a = agents["agent-a"]
        assert a["lines_authored"] == 8  # 5 + 3

        task_map = {t["task_id"]: t for t in a["tasks"]}
        assert "42" in task_map
        assert "99" in task_map
        assert task_map["42"]["lines_authored"] == 5
        assert task_map["99"]["lines_authored"] == 3

    def test_per_task_lines_authored_sum_lte_agent(self, tmp_path: Path) -> None:
        """Sum of per-task lines_authored <= agent-level lines_authored (invariant)."""
        repo = init_repo(tmp_path, author_email="agent-a@test.com")

        # Commit with task tag
        lines = "\n".join(f"x{i} = {i}" for i in range(4)) + "\n"
        first = commit(
            repo, "[Task #10] work",
            {"scripts/work.py": lines},
            author_email="agent-a@test.com",
        )
        # Commit without task tag
        more_lines = "\n".join(f"y{i} = {i}" for i in range(3)) + "\n"
        commit(
            repo, "misc cleanup",
            {"scripts/misc.py": more_lines},
            author_email="agent-a@test.com",
        )

        author_map = make_author_map(tmp_path, {"agent-a@test.com": "agent-a"})
        rc, data, _ = run_script(repo, first, author_map)
        assert rc == 0
        agents = {a["agent_id"]: a for a in data["agents"]}
        a = agents["agent-a"]
        task_sum = sum(t["lines_authored"] for t in a["tasks"])
        assert task_sum <= a["lines_authored"]


# ---------------------------------------------------------------------------
# TC-3: Unknown author (Scenario 4)
# ---------------------------------------------------------------------------


class TestUnknownAuthor:
    def test_unknown_author_attributed_to_sentinel(self, tmp_path: Path) -> None:
        """Commits from unmapped email go to __unknown__, script exits 0."""
        repo = init_repo(tmp_path, author_email="unknown@example.com")

        content = "\n".join(f"z{i} = {i}" for i in range(5)) + "\n"
        first = commit(
            repo, "mystery commit",
            {"scripts/mystery.py": content},
            author_email="unknown@example.com",
        )

        # Empty map — no mapping for unknown@example.com
        author_map = make_author_map(tmp_path, {})
        rc, data, stderr = run_script(repo, first, author_map)
        assert rc == 0
        assert data is not None
        agents = {a["agent_id"]: a for a in data["agents"]}
        assert code_survival.UNKNOWN in agents

    def test_unknown_author_warning_on_stderr(self, tmp_path: Path) -> None:
        """A warning about the unmapped email must appear on stderr."""
        repo = init_repo(tmp_path, author_email="ghost@example.com")

        content = "x = 1\ny = 2\n"
        first = commit(
            repo, "ghost work",
            {"scripts/ghost.py": content},
            author_email="ghost@example.com",
        )

        author_map = make_author_map(tmp_path, {})
        rc, data, stderr = run_script(repo, first, author_map)
        assert rc == 0
        assert "ghost@example.com" in stderr or "unmapped" in stderr.lower()


# ---------------------------------------------------------------------------
# TC-4: Deleted file (Scenario 5)
# ---------------------------------------------------------------------------


class TestDeletedFile:
    def test_deleted_file_lines_surviving_zero(self, tmp_path: Path) -> None:
        """Lines from a file deleted before HEAD have lines_surviving=0."""
        repo = init_repo(tmp_path, author_email="agent-a@test.com")

        content = "\n".join(f"d{i} = {i}" for i in range(6)) + "\n"
        first = commit(
            repo, "[Task #5] add file",
            {"scripts/old.py": content},
            author_email="agent-a@test.com",
        )

        # Delete the file
        (repo / "scripts" / "old.py").unlink()
        git(["rm", "scripts/old.py"], cwd=repo)
        git(["commit", "-m", "delete old.py"], cwd=repo)

        author_map = make_author_map(tmp_path, {"agent-a@test.com": "agent-a"})
        rc, data, _ = run_script(repo, first, author_map)
        assert rc == 0
        agents = {a["agent_id"]: a for a in data["agents"]}
        assert "agent-a" in agents
        a = agents["agent-a"]
        assert a["lines_authored"] > 0
        assert a["lines_surviving"] == 0
        assert a["survival_rate"] == 0.0


# ---------------------------------------------------------------------------
# TC-5: Excluded paths (Scenario 7)
# ---------------------------------------------------------------------------


class TestExcludedPaths:
    def test_ledger_lines_not_counted(self, tmp_path: Path) -> None:
        """Lines in ledger/ are excluded from both authored and surviving counts."""
        repo = init_repo(tmp_path, author_email="agent-a@test.com")

        # Write to scripts/ (included) and ledger/ (excluded by default)
        first = commit(
            repo, "mixed commit",
            {
                "scripts/real.py": "x = 1\ny = 2\nz = 3\n",
                "ledger/balances.json": '{"balance": 100}\n',
            },
            author_email="agent-a@test.com",
        )

        author_map = make_author_map(tmp_path, {"agent-a@test.com": "agent-a"})
        rc, data, _ = run_script(repo, first, author_map)
        assert rc == 0
        agents = {a["agent_id"]: a for a in data["agents"]}
        assert "agent-a" in agents
        # Should only see the 3 lines from scripts/real.py
        a = agents["agent-a"]
        assert a["lines_authored"] == 3

    def test_custom_exclude_flag(self, tmp_path: Path) -> None:
        """--exclude glob should exclude matching files."""
        repo = init_repo(tmp_path, author_email="agent-a@test.com")

        first = commit(
            repo, "work",
            {
                "scripts/keep.py": "a = 1\nb = 2\n",
                "scripts/drop.py": "c = 3\nd = 4\ne = 5\n",
            },
            author_email="agent-a@test.com",
        )

        author_map = make_author_map(tmp_path, {"agent-a@test.com": "agent-a"})
        rc, data, _ = run_script(
            repo, first, author_map,
            extra_args=["--exclude", "scripts/drop.py"],
        )
        assert rc == 0
        agents = {a["agent_id"]: a for a in data["agents"]}
        assert "agent-a" in agents
        a = agents["agent-a"]
        # Only 2 lines from scripts/keep.py
        assert a["lines_authored"] == 2


# ---------------------------------------------------------------------------
# TC-6: --since validation
# ---------------------------------------------------------------------------


class TestSinceValidation:
    def test_invalid_since_exits_1(self, tmp_path: Path) -> None:
        """Invalid --since value should cause exit code 1."""
        repo = init_repo(tmp_path)
        commit(repo, "init", {"scripts/x.py": "x = 1\n"})
        author_map = make_author_map(tmp_path, {})

        rc, _data, stderr = run_script(repo, "not-a-valid-ref-or-date-xyz123", author_map)
        assert rc == 1
        assert "error" in stderr.lower() or stderr  # some error message

    def test_valid_hash_works(self, tmp_path: Path) -> None:
        """Valid commit hash should work."""
        repo = init_repo(tmp_path, author_email="agent-a@test.com")
        content = "x = 1\n"
        first = commit(repo, "init", {"scripts/foo.py": content}, author_email="agent-a@test.com")
        author_map = make_author_map(tmp_path, {"agent-a@test.com": "agent-a"})
        rc, data, _ = run_script(repo, first, author_map)
        assert rc == 0
        assert data is not None

    def test_date_string_works(self, tmp_path: Path) -> None:
        """A date string like '2020-01-01' should work (even if no commits match)."""
        repo = init_repo(tmp_path, author_email="agent-a@test.com")
        commit(repo, "init", {"scripts/foo.py": "x = 1\n"}, author_email="agent-a@test.com")
        author_map = make_author_map(tmp_path, {"agent-a@test.com": "agent-a"})
        rc, data, _ = run_script(repo, "2020-01-01", author_map)
        assert rc == 0
        assert data is not None


# ---------------------------------------------------------------------------
# TC-7: JSON output structure and invariants
# ---------------------------------------------------------------------------


class TestJsonOutput:
    def test_survival_rate_clamped(self, tmp_path: Path) -> None:
        """survival_rate is always in [0.0, 1.0]."""
        repo = init_repo(tmp_path, author_email="agent-a@test.com")

        # Agent A authors lines. Then use a --since AFTER some commits so
        # lines_surviving can exceed lines_authored in the window.
        old_content = "\n".join(f"old{i} = {i}" for i in range(20)) + "\n"
        commit(
            repo, "old commit (before window)",
            {"scripts/foo.py": old_content},
            author_email="agent-a@test.com",
        )

        # Add a tiny new commit — this will be our --since point
        new_content = old_content + "new = 1\n"
        since_hash = commit(
            repo, "[Task #77] tiny addition",
            {"scripts/foo.py": new_content},
            author_email="agent-a@test.com",
        )

        # lines_surviving in HEAD includes the 20 old lines authored before --since
        # lines_authored in the window = 1 new line
        # Without clamping, rate > 1.0
        author_map = make_author_map(tmp_path, {"agent-a@test.com": "agent-a"})
        rc, data, _ = run_script(repo, since_hash, author_map)
        assert rc == 0
        assert data is not None
        for agent in data["agents"]:
            assert 0.0 <= agent["survival_rate"] <= 1.0, (
                f"survival_rate {agent['survival_rate']} out of bounds for {agent['agent_id']}"
            )
            for task in agent["tasks"]:
                assert 0.0 <= task["survival_rate"] <= 1.0

    def test_no_negative_values(self, tmp_path: Path) -> None:
        """lines_authored and lines_surviving are always >= 0."""
        repo = init_repo(tmp_path, author_email="agent-a@test.com")
        content = "\n".join(f"v{i} = {i}" for i in range(5)) + "\n"
        first = commit(repo, "init", {"scripts/v.py": content}, author_email="agent-a@test.com")
        author_map = make_author_map(tmp_path, {"agent-a@test.com": "agent-a"})
        rc, data, _ = run_script(repo, first, author_map)
        assert rc == 0
        for agent in data["agents"]:
            assert agent["lines_authored"] >= 0
            assert agent["lines_surviving"] >= 0

    def test_stdout_only_json(self, tmp_path: Path) -> None:
        """stdout must contain only valid JSON when --output is not set."""
        repo = init_repo(tmp_path, author_email="agent-a@test.com")
        content = "x = 1\n"
        first = commit(repo, "init", {"scripts/x.py": content}, author_email="agent-a@test.com")
        author_map = make_author_map(tmp_path, {"agent-a@test.com": "agent-a"})
        rc, data, _ = run_script(repo, first, author_map)
        assert rc == 0
        assert data is not None  # JSON was valid


# ---------------------------------------------------------------------------
# TC-8: --agent filter (Scenario 2)
# ---------------------------------------------------------------------------


class TestAgentFilter:
    def test_agent_filter_excludes_others(self, tmp_path: Path) -> None:
        """--agent filter: only the specified agent appears in output."""
        repo = init_repo(tmp_path, author_email="agent-a@test.com")

        first = commit(
            repo, "agent-a work",
            {"scripts/a.py": "a = 1\nb = 2\n"},
            author_email="agent-a@test.com",
        )
        commit(
            repo, "agent-b work",
            {"scripts/b.py": "c = 3\nd = 4\n"},
            author_email="agent-b@test.com",
        )

        author_map = make_author_map(tmp_path, {
            "agent-a@test.com": "agent-a",
            "agent-b@test.com": "agent-b",
        })
        rc, data, _ = run_script(repo, first, author_map, extra_args=["--agent", "agent-a"])
        assert rc == 0
        assert data is not None
        agent_ids = [a["agent_id"] for a in data["agents"]]
        assert "agent-a" in agent_ids
        assert "agent-b" not in agent_ids

    def test_agent_filter_no_match_empty_agents(self, tmp_path: Path) -> None:
        """--agent filter with nonexistent agent returns empty agents list."""
        repo = init_repo(tmp_path, author_email="agent-a@test.com")
        first = commit(
            repo, "work",
            {"scripts/a.py": "a = 1\n"},
            author_email="agent-a@test.com",
        )
        author_map = make_author_map(tmp_path, {"agent-a@test.com": "agent-a"})
        rc, data, _ = run_script(
            repo, first, author_map, extra_args=["--agent", "nonexistent-agent"]
        )
        assert rc == 0
        assert data is not None
        assert data["agents"] == []


# ---------------------------------------------------------------------------
# TC-9: No-merges (merge commits excluded from lines_authored)
# ---------------------------------------------------------------------------


class TestNoMerges:
    def test_merge_commits_not_counted(self, tmp_path: Path) -> None:
        """Merge commits must not inflate lines_authored."""
        repo = init_repo(tmp_path, author_email="agent-a@test.com")

        # Main branch commit
        first = commit(
            repo, "[Task #1] main work",
            {"scripts/main.py": "a = 1\nb = 2\nc = 3\n"},
            author_email="agent-a@test.com",
        )

        # Create a feature branch with changes
        git(["checkout", "-b", "feature"], cwd=repo)
        commit(
            repo, "[Task #2] feature work",
            {"scripts/feature.py": "x = 10\ny = 20\n"},
            author_email="agent-a@test.com",
        )

        # Merge back to main
        git(["checkout", "master" if _has_master(repo) else "main"], cwd=repo)
        # Allow non-fast-forward merge
        result = subprocess.run(
            ["git", "merge", "--no-ff", "feature", "-m", "Merge feature"],
            capture_output=True, text=True, cwd=repo,
        )
        # If merge fails (e.g., conflict), skip this test — synthetic repos may differ
        if result.returncode != 0:
            pytest.skip(f"merge failed: {result.stderr}")

        author_map = make_author_map(tmp_path, {"agent-a@test.com": "agent-a"})
        rc, data, _ = run_script(repo, first, author_map)
        assert rc == 0
        agents = {a["agent_id"]: a for a in data["agents"]}
        assert "agent-a" in agents
        a = agents["agent-a"]
        # Should be 3 (main) + 2 (feature) = 5, not inflated by merge
        assert a["lines_authored"] == 5


def _has_master(repo: Path) -> bool:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "master"],
        capture_output=True, text=True, cwd=repo,
    )
    return result.returncode == 0


# ---------------------------------------------------------------------------
# TC-10: Empty result (smoke test)
# ---------------------------------------------------------------------------


class TestEmptyResult:
    def test_empty_window_returns_empty_agents(self, tmp_path: Path) -> None:
        """An analysis window with no matching commits returns empty agents list."""
        repo = init_repo(tmp_path, author_email="agent-a@test.com")
        commit(
            repo, "initial commit",
            {"scripts/x.py": "x = 1\n"},
            author_email="agent-a@test.com",
        )

        # Use HEAD as --since: no commits match (HEAD^..HEAD is empty-ish)
        # Actually, use HEAD itself as since — commit is "at" HEAD so window is empty
        # We use a future date to get empty window
        author_map = make_author_map(tmp_path, {"agent-a@test.com": "agent-a"})
        rc, data, _ = run_script(repo, "2099-01-01", author_map)
        assert rc == 0
        assert data is not None
        assert data["agents"] == []

    def test_output_file_flag(self, tmp_path: Path) -> None:
        """--output writes JSON to the specified file."""
        repo = init_repo(tmp_path, author_email="agent-a@test.com")
        first = commit(
            repo, "init",
            {"scripts/f.py": "f = 1\n"},
            author_email="agent-a@test.com",
        )
        author_map = make_author_map(tmp_path, {"agent-a@test.com": "agent-a"})
        out_file = tmp_path / "out.json"
        rc, _data, _ = run_script(
            repo, first, author_map,
            extra_args=["--output", str(out_file)],
        )
        assert rc == 0
        assert out_file.exists()
        loaded = json.loads(out_file.read_text(encoding="utf-8"))
        assert "agents" in loaded
