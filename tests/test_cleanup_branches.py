from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from itertools import combinations
from pathlib import Path

import pytest

from scripts import cleanup_branches as cleanup

PERSISTENT_NAMES = ("work/agent0", "work/slot-1", "work/slot-2", "work/slot-3")
NEAR_MISSES = (
    "work/slot-0",
    "work/slot-4",
    "work/slot-10",
    "work/slot-5/task",
    "work/slot-2-old",
    "work/agent0-old",
    "work/agent1",
    "feature/unrelated",
)
CATEGORY_COMBINATIONS = [
    categories
    for size in range(len(cleanup.CATEGORY_ORDER) + 1)
    for categories in combinations(cleanup.CATEGORY_ORDER, size)
]


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        [
            "git",
            "-c",
            f"core.hooksPath={root / 'no-hooks'}",
            "-c",
            "user.name=Cleanup fixture",
            "-c",
            "user.email=cleanup@example.invalid",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout.strip()


@pytest.fixture
def repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-b", "main")
    monkeypatch.setenv("GIT_AUTHOR_DATE", "2020-01-01T00:00:00+00:00")
    monkeypatch.setenv("GIT_COMMITTER_DATE", "2020-01-01T00:00:00+00:00")
    for message in ("base", "main advances"):
        git(
            root,
            "-c",
            "user.name=Cleanup fixture",
            "-c",
            "user.email=cleanup@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "--allow-empty",
            "-m",
            message,
        )
    for name in (*PERSISTENT_NAMES, *NEAR_MISSES, "agent0/old", "agent/agent0/old"):
        git(root, "branch", name, "main~1")
    # A local-only remote configuration produces real [gone] metadata; no fetch.
    git(root, "config", "remote.fixture.url", str(tmp_path / "absent-remote"))
    git(root, "config", "remote.fixture.fetch", "+refs/heads/*:refs/remotes/fixture/*")
    for name in PERSISTENT_NAMES:
        git(root, "config", f"branch.{name}.remote", "fixture")
        git(root, "config", f"branch.{name}.merge", f"refs/heads/{name}")
    monkeypatch.setattr(
        cleanup,
        "_gh",
        lambda *args, **kwargs: subprocess.CompletedProcess(["gh"], 0, "[]", ""),
    )
    return root


@pytest.mark.parametrize("name", PERSISTENT_NAMES)
@pytest.mark.parametrize("categories", CATEGORY_COMBINATIONS)
def test_exact_name_protection_precedes_all_category_combinations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    categories: tuple[str, ...],
) -> None:
    now = datetime.now(timezone.utc)
    branch = cleanup.BranchInfo(
        name=name,
        sha="a" * 40,
        upstream=None,
        upstream_track="[gone]" if "gone_remote" in categories else None,
        committed_at=now - timedelta(days=60 if "idle_30d" in categories else 1),
        issue=None,
    )
    monkeypatch.setattr(cleanup, "_list_local_branches", lambda root: [branch])
    monkeypatch.setattr(cleanup, "_resolve_main_ref", lambda *args: ("main", "b" * 40))
    monkeypatch.setattr(cleanup, "_worktree_branch_map", lambda root: {})
    monkeypatch.setattr(cleanup, "_load_open_task_statuses", lambda root: {})
    monkeypatch.setattr(cleanup, "_query_open_pull_requests", lambda root: ({}, None))
    monkeypatch.setattr(
        cleanup,
        "_branch_is_merged",
        lambda *args: "merged_into_main" in categories,
    )
    monkeypatch.setattr(
        cleanup,
        "_issue_closed_by_merged_task",
        lambda *args: "closed_task_pr_merged" in categories,
    )
    reports, main_ref, log_path, error = cleanup.build_report(tmp_path)
    row = reports[0]
    assert tuple(row.categories) == categories
    assert row.protections == ["protected:persistent_workplace"]
    assert not row.can_delete
    assert row.is_stale == bool(categories)
    output = cleanup.render_report(
        reports,
        main_ref=main_ref,
        log_path=log_path,
        apply=False,
        pr_query_error=error,
    )
    assert "Deletion candidates: 0" in output
    if categories:
        assert f"- {name} @ aaaaaaa" in output
        assert "protected:persistent_workplace" in output

    def unexpected_git(*args, **kwargs):
        pytest.fail("protected branches must not reach deletion")

    monkeypatch.setattr(cleanup, "_git", unexpected_git)
    assert cleanup.apply_deletions(tmp_path, reports=reports, log_path=log_path) == (
        [],
        [],
    )
    assert not log_path.exists()


def test_real_detached_slots_and_near_misses_keep_classification(repository: Path):
    reports, _, _, error = cleanup.build_report(repository)
    assert error is None
    rows = {row.branch.name: row for row in reports}
    for name in PERSISTENT_NAMES:
        row = rows[name]
        assert row.categories == ["merged_into_main", "gone_remote", "idle_30d"]
        assert row.protections == ["protected:persistent_workplace"]
        assert not row.can_delete
    for name in NEAR_MISSES:
        assert rows[name].categories == ["merged_into_main", "idle_30d"]
        assert rows[name].protections == []
        assert rows[name].can_delete
    assert "protected:main" in rows["main"].protections
    assert any(
        item.startswith("checked_out_in_worktree:") for item in rows["main"].protections
    )
    for name in ("agent0/old", "agent/agent0/old"):
        assert rows[name].protections == ["protected:agent0"]
        assert not rows[name].can_delete


@pytest.mark.parametrize("parent", PERSISTENT_NAMES)
def test_nested_near_miss_is_not_permanently_protected(
    repository: Path,
    parent: str,
) -> None:
    # Git cannot hold a branch and its child simultaneously. Change only fixture refs.
    git(repository, "branch", "-D", parent)
    child = f"{parent}/task"
    git(repository, "branch", child, "main~1")
    reports, _, _, _ = cleanup.build_report(repository)
    row = next(row for row in reports if row.branch.name == child)
    assert row.categories == ["merged_into_main", "idle_30d"]
    assert row.protections == []
    assert row.can_delete


@pytest.mark.parametrize("name", ["work/Agent0", "WORK/slot-1", "work/Slot-2"])
def test_case_variant_near_misses_remain_eligible(
    repository: Path,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
) -> None:
    # Case-folding filesystems cannot store both exact names and these near misses.
    branch = cleanup.BranchInfo(
        name=name,
        sha="a" * 40,
        upstream=None,
        upstream_track=None,
        committed_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
        issue=None,
    )
    monkeypatch.setattr(cleanup, "_list_local_branches", lambda root: [branch])
    monkeypatch.setattr(cleanup, "_branch_is_merged", lambda *args: True)
    reports, _, _, _ = cleanup.build_report(repository)
    assert reports[0].categories == ["merged_into_main", "idle_30d"]
    assert reports[0].protections == []
    assert reports[0].can_delete


def test_default_dry_run_prints_protection_without_ref_or_receipt_changes(
    repository: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    before = git(repository, "show-ref")
    assert cleanup.main(["--root", str(repository)]) == 0
    output = capsys.readouterr().out
    assert "Mode: dry-run" in output
    assert "Open PR guard: verified via gh" in output
    assert "Deletion candidates: 8" in output
    for name in PERSISTENT_NAMES:
        line = next(
            line for line in output.splitlines() if line.startswith(f"- {name} @")
        )
        assert "protected:persistent_workplace" in line
    assert "Deleted branches:" not in output
    assert git(repository, "show-ref") == before
    assert not (repository / cleanup.BRANCH_LOG).exists()


@pytest.mark.parametrize("failure", ["missing", "failed", "invalid_json"])
def test_failed_pr_query_blocks_apply_and_keeps_dry_run_read_only(
    repository: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failure: str,
) -> None:
    def unavailable(*args, **kwargs):
        if failure == "missing":
            raise FileNotFoundError("gh unavailable")
        if failure == "failed":
            raise subprocess.CalledProcessError(1, ["gh"], stderr="query failed")
        return subprocess.CompletedProcess(["gh"], 0, "invalid JSON", "")

    monkeypatch.setattr(cleanup, "_gh", unavailable)
    before = git(repository, "show-ref")
    for flags, expected in (([], 0), (["--apply"], 2)):
        assert cleanup.main(["--root", str(repository), *flags]) == expected
        output = capsys.readouterr().out
        assert "Open PR guard: unavailable" in output
        assert "protected:persistent_workplace" in output
        if flags:
            assert "Apply blocked: open PR verification failed" in output
        assert git(repository, "show-ref") == before
        assert not (repository / cleanup.BRANCH_LOG).exists()


def test_open_pr_and_attached_worktree_guards_remain(
    repository: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cleanup,
        "_gh",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            ["gh"],
            0,
            json.dumps(
                [{"number": 7, "headRefName": "feature/unrelated", "url": "pr/7"}]
            ),
            "",
        ),
    )
    # Native checkout of an unrelated branch in this isolated repository.
    git(repository, "checkout", "work/slot-4")
    reports, _, _, _ = cleanup.build_report(repository)
    rows = {row.branch.name: row for row in reports}
    assert rows["feature/unrelated"].protections == ["open_pr:#7"]
    assert rows["feature/unrelated"].open_pr_url == "pr/7"
    assert rows["work/slot-4"].protections[0].startswith("checked_out_in_worktree:")
    assert not rows["feature/unrelated"].can_delete
    assert not rows["work/slot-4"].can_delete


def test_opt_in_deletes_only_eligible_fixture_refs_after_recovery_receipt(
    repository: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    original_git = cleanup._git
    expected_sha = git(repository, "rev-parse", "main~1")
    observed = []
    log_path = repository / cleanup.BRANCH_LOG

    def check_receipt(args, **kwargs):
        if args[:3] == ["update-ref", "--no-deref", "-d"]:
            assert args[3].startswith("refs/heads/")
            name = args[3][len("refs/heads/") :]
            assert args[4] == expected_sha
            receipt = json.loads(log_path.read_text(encoding="utf-8").splitlines()[-1])
            assert receipt["action"] == "pre_delete"
            assert receipt["branch"] == name
            assert receipt["sha"] == expected_sha
            assert receipt["categories"] == ["merged_into_main", "idle_30d"]
            assert cleanup.parse_iso_utc(receipt["timestamp"])
            assert name in NEAR_MISSES
            assert git(repository, "rev-parse", name) == expected_sha
            observed.append(name)
        return original_git(args, **kwargs)

    monkeypatch.setattr(cleanup, "_git", check_receipt)
    assert cleanup.main(["--root", str(repository), "--apply"]) == 0
    output = capsys.readouterr().out
    assert "Mode: apply" in output
    assert "Deleted branches: 8" in output
    assert set(observed) == set(NEAR_MISSES)
    remaining = set(git(repository, "branch", "--format=%(refname:short)").splitlines())
    assert remaining == {*PERSISTENT_NAMES, "main", "agent0/old", "agent/agent0/old"}
    assert len(log_path.read_text(encoding="utf-8").splitlines()) == 8


def test_receipt_write_failure_prevents_deletion(
    repository: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    reports, _, _, _ = cleanup.build_report(repository)
    before = git(repository, "show-ref")
    blocked_log = repository / "not-a-directory"
    blocked_log.write_text("retain", encoding="utf-8")
    deleted, failed = cleanup.apply_deletions(
        repository, reports=reports, log_path=blocked_log / "log"
    )
    assert deleted == []
    assert len(failed) == len(NEAR_MISSES)
    assert all("deletion refused" in failure for failure in failed)
    assert git(repository, "show-ref") == before
    monkeypatch.setattr(
        cleanup,
        "build_report",
        lambda *args, **kwargs: (reports, "main", blocked_log / "log", None),
    )
    assert cleanup.main(["--root", str(repository), "--apply"]) == 2
    assert "Delete failures:" in capsys.readouterr().out
    assert git(repository, "show-ref") == before


def test_changed_tip_is_not_deleted_after_classification(repository: Path) -> None:
    reports, _, log_path, _ = cleanup.build_report(repository)
    row = next(row for row in reports if row.branch.name == "feature/unrelated")
    git(repository, "branch", "-f", row.branch.name, "main")
    assert git(repository, "rev-parse", row.branch.name) != row.branch.sha
    deleted, failed = cleanup.apply_deletions(
        repository, reports=[row], log_path=log_path
    )
    assert deleted == []
    assert len(failed) == 1
    assert "SHA mismatch" in failed[0]
    assert not log_path.exists()
    remaining = git(repository, "branch", "--format=%(refname:short)").splitlines()
    assert row.branch.name in remaining


def test_failed_deletion_retains_predelete_receipt(
    repository: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    reports, _, log_path, _ = cleanup.build_report(repository)
    row = next(row for row in reports if row.branch.name == "feature/unrelated")
    before = git(repository, "show-ref")
    original_git = cleanup._git

    def fail_update(args, **kwargs):
        if args[0] == "update-ref":
            return subprocess.CompletedProcess(
                ["git"], 1, "", "fixture deletion refused"
            )
        return original_git(args, **kwargs)

    monkeypatch.setattr(cleanup, "_git", fail_update)
    assert cleanup.apply_deletions(repository, reports=[row], log_path=log_path) == (
        [],
        [
            "feature/unrelated: conditional ref deletion failed: "
            "fixture deletion refused"
        ],
    )
    receipt = json.loads(log_path.read_text(encoding="utf-8"))
    assert receipt["branch"] == row.branch.name
    assert receipt["sha"] == row.branch.sha
    assert receipt["action"] == "pre_delete"
    assert git(repository, "show-ref") == before
    monkeypatch.setattr(
        cleanup, "build_report", lambda *args, **kwargs: ([row], "main", log_path, None)
    )
    assert cleanup.main(["--root", str(repository), "--apply"]) == 2
    assert "conditional ref deletion failed" in capsys.readouterr().out
    assert git(repository, "show-ref") == before


def captured_candidate(root: Path) -> tuple[cleanup.BranchReport, Path]:
    reports, _, log_path, error = cleanup.build_report(root)
    assert error is None
    return next(
        row for row in reports if row.branch.name == "feature/unrelated"
    ), log_path


@pytest.mark.parametrize("change", ["moved", "missing"])
def test_stale_tip_cli_refusal_is_exit_2_without_receipt(
    repository: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    change: str,
) -> None:
    row, log_path = captured_candidate(repository)
    ref = f"refs/heads/{row.branch.name}"
    if change == "moved":
        git(repository, "update-ref", ref, git(repository, "rev-parse", "main"))
    else:
        git(repository, "update-ref", "-d", ref, row.branch.sha)
    before = git(repository, "show-ref")
    monkeypatch.setattr(
        cleanup, "build_report", lambda *args, **kwargs: ([row], "main", log_path, None)
    )
    assert cleanup.main(["--root", str(repository), "--apply"]) == 2
    output = capsys.readouterr().out
    assert "Deleted branches: 0" in output
    assert "Delete failures:" in output
    assert ("SHA mismatch" if change == "moved" else "Missing or unreadable") in output
    assert git(repository, "show-ref") == before
    assert not log_path.exists()


@pytest.mark.parametrize("change", ["moved", "missing"])
def test_conditional_delete_refuses_changes_after_early_inspection(
    repository: Path,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    row, log_path = captured_candidate(repository)
    ref = f"refs/heads/{row.branch.name}"
    new_sha = git(repository, "rev-parse", "main")
    original_git = cleanup._git

    def race(args, **kwargs):
        if args[0] == "update-ref":
            assert args == ["update-ref", "--no-deref", "-d", ref, row.branch.sha]
            assert log_path.exists()
            if change == "moved":
                git(repository, "update-ref", ref, new_sha)
            else:
                git(repository, "update-ref", "-d", ref, row.branch.sha)
        return original_git(args, **kwargs)

    monkeypatch.setattr(cleanup, "_git", race)
    deleted, failed = cleanup.apply_deletions(
        repository, reports=[row], log_path=log_path
    )
    assert deleted == []
    assert len(failed) == 1
    assert "conditional ref deletion failed" in failed[0]
    if change == "moved":
        assert git(repository, "rev-parse", "--verify", ref) == new_sha
    else:
        assert ref not in git(repository, "for-each-ref", "--format=%(refname)")
    assert json.loads(log_path.read_text(encoding="utf-8"))["sha"] == row.branch.sha


@pytest.mark.parametrize("moment", ["before_apply", "during_logging"])
def test_newly_attached_worktree_is_retained(
    repository: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    moment: str,
) -> None:
    row, log_path = captured_candidate(repository)
    attached = tmp_path / "attached"

    def attach():
        git(repository, "worktree", "add", str(attached), row.branch.name)

    if moment == "before_apply":
        attach()
    else:
        original_log = cleanup._write_predelete_log

        def attach_after_log(*args):
            original_log(*args)
            attach()

        monkeypatch.setattr(cleanup, "_write_predelete_log", attach_after_log)
    before = git(repository, "show-ref")
    deleted, failed = cleanup.apply_deletions(
        repository, reports=[row], log_path=log_path
    )
    assert deleted == []
    assert "Branch held by worktree" in failed[0]
    assert git(repository, "show-ref") == before
    assert git(attached, "symbolic-ref", "HEAD") == f"refs/heads/{row.branch.name}"
    assert log_path.exists()


@pytest.mark.parametrize("failure", ["query", "empty", "malformed", "operation_state"])
def test_worktree_inspection_failure_refuses_cli_deletion(
    repository: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failure: str,
) -> None:
    row, log_path = captured_candidate(repository)
    before = git(repository, "show-ref")
    original_git = cleanup._git

    def fail_inspection(args, **kwargs):
        if args[:2] == ["worktree", "list"]:
            if failure == "query":
                raise subprocess.CalledProcessError(
                    1, ["git"], stderr="worktree failed"
                )
            if failure == "empty":
                return subprocess.CompletedProcess(["git"], 0, "", "")
            if failure == "malformed":
                return subprocess.CompletedProcess(
                    ["git"], 0, f"worktree {repository}\0\0", ""
                )
        if failure == "operation_state" and args == ["rev-parse", "--absolute-git-dir"]:
            raise OSError("operation state unavailable")
        if args[0] == "update-ref":
            pytest.fail("inspection failure must prevent deletion")
        return original_git(args, **kwargs)

    monkeypatch.setattr(cleanup, "_git", fail_inspection)
    monkeypatch.setattr(
        cleanup, "build_report", lambda *args, **kwargs: ([row], "main", log_path, None)
    )
    assert cleanup.main(["--root", str(repository), "--apply"]) == 2
    assert "deletion refused" in capsys.readouterr().out
    assert git(repository, "show-ref") == before
    assert log_path.exists()


@pytest.mark.parametrize(
    "name", [*PERSISTENT_NAMES, "main", "agent0/old", "agent/agent0/old"]
)
def test_protected_names_are_defended_even_without_classifier_labels(
    repository: Path,
    name: str,
) -> None:
    row, log_path = captured_candidate(repository)
    forged = replace(row, branch=replace(row.branch, name=name), protections=[])
    before = git(repository, "show-ref")
    assert cleanup.apply_deletions(repository, reports=[forged], log_path=log_path) == (
        [],
        [f"{name}: protected branch"],
    )
    assert git(repository, "show-ref") == before
    assert not log_path.exists()


@pytest.mark.parametrize(
    "name",
    [
        "refs/heads/main",
        "refs/tags/tag",
        "refs/remotes/origin/main",
        "../main",
        "bad..name",
        "@{-1}",
        "-unsafe",
        "HEAD",
        "",
        "bad\nname",
    ],
)
def test_invalid_branch_identity_is_refused(
    repository: Path,
    name: str,
) -> None:
    row, log_path = captured_candidate(repository)
    row.branch = replace(row.branch, name=name)
    before = git(repository, "show-ref")
    deleted, failed = cleanup.apply_deletions(
        repository, reports=[row], log_path=log_path
    )
    assert deleted == []
    assert len(failed) == 1
    assert "Invalid local branch" in failed[0]
    assert git(repository, "show-ref") == before
    assert not log_path.exists()


@pytest.mark.parametrize("sha", ["0" * 40, "abc", "x" * 40, "-d", "a" * 40 + "\n"])
def test_invalid_expected_sha_is_refused(repository: Path, sha: str) -> None:
    row, log_path = captured_candidate(repository)
    row.branch = replace(row.branch, sha=sha)
    before = git(repository, "show-ref")
    deleted, failed = cleanup.apply_deletions(
        repository, reports=[row], log_path=log_path
    )
    assert deleted == []
    assert "Expected SHA must be a nonzero full object ID" in failed[0]
    assert git(repository, "show-ref") == before
    assert not log_path.exists()


def test_full_ref_identity_preserves_tags_remotes_and_slot_protection(repository: Path):
    tag_sha = git(repository, "rev-parse", "main")
    for name in (*PERSISTENT_NAMES, "feature/unrelated"):
        git(repository, "update-ref", f"refs/tags/{name}", tag_sha)
    remote = "refs/remotes/fixture/feature/unrelated"
    git(repository, "update-ref", remote, tag_sha)
    row, log_path = captured_candidate(repository)
    assert row.branch.sha != tag_sha
    assert row.categories == ["merged_into_main", "idle_30d"]
    reports, _, _, _ = cleanup.build_report(repository)
    for name in PERSISTENT_NAMES:
        slot = next(item for item in reports if item.branch.name == name)
        assert slot.protections == ["protected:persistent_workplace"]
    assert cleanup.apply_deletions(repository, reports=[row], log_path=log_path) == (
        [row.branch.name],
        [],
    )
    for name in (*PERSISTENT_NAMES, "feature/unrelated"):
        assert git(repository, "rev-parse", f"refs/tags/{name}") == tag_sha
    assert git(repository, "rev-parse", remote) == tag_sha
    assert git(repository, "rev-parse", "refs/heads/main") == tag_sha


@pytest.mark.parametrize(
    "target",
    [
        "refs/heads/main",
        "refs/heads/work/slot-1",
        "refs/tags/target",
        "refs/remotes/fixture/target",
    ],
)
def test_symbolic_local_branch_is_refused_without_touching_target(
    repository: Path,
    target: str,
) -> None:
    row, log_path = captured_candidate(repository)
    if not target.startswith("refs/heads/"):
        git(repository, "update-ref", target, row.branch.sha)
    ref = f"refs/heads/{row.branch.name}"
    git(repository, "symbolic-ref", ref, target)
    before = git(repository, "show-ref")
    deleted, failed = cleanup.apply_deletions(
        repository, reports=[row], log_path=log_path
    )
    assert deleted == []
    assert "Refusing symbolic local branch ref" in failed[0]
    assert git(repository, "symbolic-ref", ref) == target
    assert git(repository, "show-ref") == before
    assert not log_path.exists()


def test_symbolic_swap_before_conditional_delete_cannot_dereference_target(
    repository: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row, log_path = captured_candidate(repository)
    ref = f"refs/heads/{row.branch.name}"
    target = "refs/tags/retained"
    git(repository, "update-ref", target, row.branch.sha)
    original_git = cleanup._git

    def swap(args, **kwargs):
        if args[0] == "update-ref":
            assert args[1] == "--no-deref"
            git(repository, "symbolic-ref", ref, target)
        return original_git(args, **kwargs)

    monkeypatch.setattr(cleanup, "_git", swap)
    cleanup.apply_deletions(repository, reports=[row], log_path=log_path)
    assert git(repository, "rev-parse", target) == row.branch.sha
    assert log_path.exists()


@pytest.mark.parametrize("operation", ["rebase", "rebase-apply", "bisect"])
def test_detached_operation_retains_the_native_held_branch_guard(
    repository: Path,
    operation: str,
) -> None:
    def commit(message: str):
        git(
            repository,
            "-c",
            "user.name=Cleanup fixture",
            "-c",
            "user.email=cleanup@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "--allow-empty",
            "-m",
            message,
        )

    if operation.startswith("rebase"):
        (repository / "conflict.txt").write_text("main\n", encoding="utf-8")
        git(repository, "add", "conflict.txt")
        commit("main change")
        git(repository, "checkout", "feature/unrelated")
        (repository / "conflict.txt").write_text("branch\n", encoding="utf-8")
        git(repository, "add", "conflict.txt")
        commit("branch change")
    else:
        commit("extra bisect point")
    git(repository, "checkout", "main")
    row, log_path = captured_candidate(repository)
    assert row.can_delete
    git(repository, "checkout", "feature/unrelated")
    if operation.startswith("rebase"):
        with pytest.raises(subprocess.CalledProcessError) as error:
            flags = ["--apply"] if operation == "rebase-apply" else []
            git(repository, "rebase", *flags, "main")
        directory = "rebase-apply" if operation == "rebase-apply" else "rebase-merge"
        assert (repository / ".git" / directory / "head-name").is_file(), (
            error.value.stderr
        )
    else:
        git(repository, "bisect", "start", "main", row.branch.sha)
    with pytest.raises(subprocess.CalledProcessError):
        git(repository, "symbolic-ref", "--quiet", "HEAD")
    # Demonstrate the previous native command's refusal on this same fixture.
    with pytest.raises(subprocess.CalledProcessError):
        git(repository, "branch", "-D", row.branch.name)
    before = git(repository, "show-ref")
    deleted, failed = cleanup.apply_deletions(
        repository, reports=[row], log_path=log_path
    )
    assert deleted == []
    assert "Branch held by worktree" in failed[0]
    assert git(repository, "show-ref") == before


def test_full_worktree_branch_name_preserves_unicode_whitespace(
    repository: Path,
    tmp_path: Path,
) -> None:
    name = "feature/unrelated\u00a0"
    git(repository, "branch", name, "main~1")
    reports, _, log_path, _ = cleanup.build_report(repository)
    row = next(row for row in reports if row.branch.name == name)
    git(repository, "worktree", "add", str(tmp_path / "attached"), name)
    deleted, failed = cleanup.apply_deletions(
        repository, reports=[row], log_path=log_path
    )
    assert deleted == []
    assert "Branch held by worktree" in failed[0]
    assert git(repository, "rev-parse", f"refs/heads/{name}") == row.branch.sha


@pytest.mark.parametrize(
    "name,alias",
    [
        ("main", "Main"),
        ("work/agent0", "work/Agent0"),
        ("agent0/old", "Agent0/old"),
        ("agent/agent0/old", "Agent/agent0/old"),
    ],
)
def test_case_alias_cannot_bypass_protected_ref_identity(
    repository: Path,
    name: str,
    alias: str,
) -> None:
    row, log_path = captured_candidate(repository)
    actual = git(repository, "rev-parse", f"refs/heads/{name}")
    row.branch = replace(row.branch, name=alias, sha=actual)
    before = git(repository, "show-ref")
    deleted, failed = cleanup.apply_deletions(
        repository, reports=[row], log_path=log_path
    )
    assert deleted == []
    assert len(failed) == 1
    assert git(repository, "show-ref") == before
    assert not log_path.exists()


@pytest.mark.parametrize("name", ["feature/secondary", "feature/secondary\u2028"])
def test_rebase_update_refs_retains_secondary_branches(
    repository: Path,
    name: str,
) -> None:
    (repository / "conflict.txt").write_text("main\n", encoding="utf-8")
    git(repository, "add", "conflict.txt")
    git(repository, "commit", "-m", "main conflict")
    git(repository, "checkout", "feature/unrelated")
    (repository / "extra.txt").write_text("extra\n", encoding="utf-8")
    git(repository, "add", "extra.txt")
    git(repository, "commit", "-m", "secondary point")
    git(repository, "branch", name)
    (repository / "conflict.txt").write_text("feature\n", encoding="utf-8")
    git(repository, "add", "conflict.txt")
    git(repository, "commit", "-m", "feature conflict")
    git(repository, "checkout", "main")
    reports, _, log_path, error = cleanup.build_report(repository)
    assert error is None
    row = next(row for row in reports if row.branch.name == name)
    assert row.can_delete
    git(repository, "checkout", "feature/unrelated")
    with pytest.raises(subprocess.CalledProcessError):
        git(repository, "rebase", "--update-refs", "main")
    state = repository / ".git/rebase-merge/update-refs"
    assert state.is_file() and f"refs/heads/{name}\n" in state.read_text(
        encoding="utf-8"
    )
    # This secondary branch is not HEAD; native branch -D still refuses it.
    with pytest.raises(subprocess.CalledProcessError):
        git(repository, "branch", "-D", name)
    before = git(repository, "show-ref")
    assert git(repository, "rev-parse", f"refs/heads/{name}") == row.branch.sha
    deleted, failed = cleanup.apply_deletions(
        repository, reports=[row], log_path=log_path
    )
    assert deleted == [] and "Branch held by worktree" in failed[0]
    assert git(repository, "show-ref") == before
    refreshed, _, _, _ = cleanup.build_report(repository)
    held = next(row for row in refreshed if row.branch.name == name)
    assert not held.can_delete


@pytest.mark.parametrize(
    "payload",
    [
        "refs/heads/feature/unrelated\n",
        "refs/heads/feature/unrelated\n" + "0" * 40 + "\n",
        "refs/tags/alias\n" + "0" * 40 + "\n" + "0" * 40 + "\n",
        "refs/heads/bad ref\n" + "0" * 40 + "\n" + "0" * 40 + "\n",
        "refs/heads/feature/unrelated\ninvalid\n" + "0" * 40 + "\n",
        "refs/heads/feature/unrelated\n" + "0" * 40 + "\ninvalid\n",
        "refs/heads/feature/unrelated\n" + "0" * 40 + "\n" + "0" * 64 + "\n",
        "\n",
    ],
)
def test_malformed_update_refs_state_refuses_deletion(
    repository: Path, payload: str
) -> None:
    row, log_path = captured_candidate(repository)
    state = repository / ".git/rebase-merge/update-refs"
    state.parent.mkdir()
    state.write_text(payload, encoding="utf-8")
    before = git(repository, "show-ref")
    deleted, failed = cleanup.apply_deletions(
        repository, reports=[row], log_path=log_path
    )
    assert deleted == [] and "rebase update-refs state" in failed[0]
    assert git(repository, "show-ref") == before


def test_empty_update_refs_state_has_no_secondary_holds(repository: Path) -> None:
    row, log_path = captured_candidate(repository)
    state = repository / ".git/rebase-merge/update-refs"
    state.parent.mkdir()
    state.write_text("", encoding="utf-8")
    assert cleanup.apply_deletions(repository, reports=[row], log_path=log_path) == (
        [row.branch.name],
        [],
    )


@pytest.mark.parametrize(
    "state", ["rebase-merge/head-name", "rebase-apply/head-name", "BISECT_START"]
)
@pytest.mark.parametrize(
    "payload", ["", "refs/heads/bad ref\n", "refs/heads/unfinished/\n"]
)
def test_invalid_held_branch_metadata_refuses_deletion(
    repository: Path,
    state: str,
    payload: str,
) -> None:
    row, log_path = captured_candidate(repository)
    metadata = repository / ".git" / state
    metadata.parent.mkdir(exist_ok=True)
    metadata.write_text(payload, encoding="utf-8")
    before = git(repository, "show-ref")
    deleted, failed = cleanup.apply_deletions(
        repository, reports=[row], log_path=log_path
    )
    assert deleted == [] and "Invalid worktree operation branch" in failed[0]
    assert git(repository, "show-ref") == before


@pytest.mark.parametrize("apply", [False, True])
@pytest.mark.parametrize(
    "state", ["rebase-merge/head-name", "rebase-merge/update-refs", "BISECT_START"]
)
@pytest.mark.parametrize("error_type", [PermissionError, OSError])
def test_initial_operation_metadata_io_failure_returns_cli_refusal(
    repository: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    apply: bool,
    state: str,
    error_type: type[OSError],
) -> None:
    metadata = repository / ".git" / state
    before = git(repository, "show-ref")
    original = Path.read_text

    def unavailable(path, *args, **kwargs):
        if path == metadata:
            raise error_type("operation metadata unreadable")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", unavailable)
    flags = ["--apply"] if apply else []
    assert cleanup.main(["--root", str(repository), *flags]) == 2
    assert "operation metadata unreadable" in capsys.readouterr().err
    assert git(repository, "show-ref") == before
    assert not (repository / cleanup.BRANCH_LOG).exists()
