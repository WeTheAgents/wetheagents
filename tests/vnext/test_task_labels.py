"""L-01 through L-06: metadata is a recoverable display, never ledger authority."""

from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace

import pytest

from wea_cli import task_labels as cli
from wea_vnext.task_labels import CATALOG, definition, project, summary
from wea_vnext.tide.github import GitHubError
from wea_vnext.tide.labels import LabelSync, sync_canonical

from .test_tide_replay import funded


@pytest.fixture
def canonical_task():
    engine, _, now = funded()
    return engine, engine.state()["tasks"]["issue-42"], now


@pytest.mark.parametrize(
    "mode,config,payment,reward",
    [
        ("flat_pod", {"payout_vector": [10] * 15}, "pod", "10-wea"),
        ("ranked", {"winner_count": 1, "payout_vector": [100]}, "wta", "100-wea"),
        (
            "ranked",
            {"winner_count": 2, "payout_vector": [60, 40]},
            "best-x",
            "variable",
        ),
        ("ranked", {"winner_count": 2, "payout_vector": [50, 50]}, "best-x", "50-wea"),
        (
            "frontier",
            {"incentive": "linear", "payout_vector": [10, 20]},
            "frontier-linear",
            "variable",
        ),
        (
            "frontier",
            {"incentive": "fibonacci", "payout_vector": [10, 10, 20]},
            "frontier-fibonacci",
            "variable",
        ),
        ("duel", {}, "duel", "variable"),
    ],
)
def test_current_stage_mechanics(canonical_task, mode, config, payment, reward):
    _, task, now = canonical_task
    next_stage = deepcopy(task["stages"][0])
    next_stage["stage_index"] = 1
    next_stage["contract"].update(mode=mode, config=config, depth="spec")
    task["stages"].append(next_stage)
    task["current_stage_index"] = 1
    labels = project(task, now)
    assert "pay:" + payment in labels
    assert "reward:" + reward in labels
    assert "depth:spec" in labels
    assert len(labels) == 5


def test_open_deadlines_pauses_and_closed_issue(canonical_task):
    _, task, now = canonical_task
    assert "state:open" in project(task, now)
    assert "state:review" in project(task, now + timedelta(days=2))
    assert "state:review" in project(task, now, issue_closed=True)
    task["pauses"].append({"ended_at": None})
    assert "state:paused" in project(task, now)
    task["pauses"].clear()
    task["stages"][0]["paid_wea"] = 100
    assert "state:review" in project(task, now)


def test_terminal_task_and_role_escrow(canonical_task):
    _, task, now = canonical_task
    task["plan_status"] = "stopped"
    assert "state:settlement" in project(task, now)
    task["escrow"]["refunded_wea"] = 100
    assert "state:done" in project(task, now)
    task["roles"].append({"escrow_available_wea": 5})
    assert "state:settlement" in project(task, now)


class API:
    def __init__(self, labels=(), fail=False, base="main"):
        self.labels = set(labels)
        self.catalog = set(CATALOG)
        self.writes = []
        self.fail = fail
        self.base = base

    def get(self, path):
        if "/git/ref/" in path:
            return {"object": {"sha": self.base}}
        if "/issues/" in path:
            return {"labels": sorted(self.labels), "state": "open"}
        assert "/labels?" in path
        return [{"name": name} for name in self.catalog]

    def request(self, method, path, data=None):
        from urllib.parse import unquote

        if self.fail:
            raise GitHubError("simulated HTTP 403")
        self.writes.append((method, path, data))
        if path.endswith("/labels") and "/issues/" not in path:
            self.catalog.add(data["name"])
        elif method == "DELETE":
            self.labels.remove(unquote(path.rsplit("/", 1)[1]))
        else:
            self.labels.update(data["labels"])


def test_sync_preserves_topics_audience_and_retries_without_ledger_effects(
    canonical_task,
):
    engine, task, now = canonical_task
    before = engine.state()
    api = API(
        {"documentation", "audience:pilot", "pay:wta", "stage:triage", "task-proposal"},
        fail=True,
    )
    reports = []
    sync_canonical(api, engine, "main", now, reports.append)
    assert "unresolved" in reports[0]
    assert engine.state() == before
    api.fail = False
    sync_canonical(api, engine, "main", now, reports.append)
    assert api.labels == project(task, now) | {"documentation", "audience:pilot"}
    assert engine.state() == before
    api.writes.clear()
    sync_canonical(api, engine, "main", now, reports.append)
    assert not api.writes


def test_main_advance_and_proposals_do_not_open_work(canonical_task):
    engine, _, now = canonical_task
    api = API({"state:funding"}, base="new-main")
    reports = []
    sync_canonical(api, engine, "main", now, reports.append)
    assert not api.writes and "main advanced" in reports[0]
    empty = SimpleNamespace(state=lambda: {"tasks": {}})
    sync_canonical(api, empty, "main", now, reports.append)
    assert api.labels == {"state:funding"}


def test_update_recovers_after_partial_removal(canonical_task):
    _, task, now = canonical_task
    api = API({"documentation", "state:funding"})
    sync = LabelSync(api)
    desired = project(task, now)
    sync.ensure(desired)
    api.request("DELETE", "repos/x/issues/42/labels/state%3Afunding")
    sync.update(42, api.labels.copy(), desired)
    assert api.labels == desired | {"documentation"}


@pytest.mark.parametrize("advance_at", ["inventory", "delete"])
def test_main_advance_during_update_stops_further_issue_writes(
    canonical_task, advance_at
):
    engine, _, now = canonical_task

    class RacingAPI(API):
        def get(self, path):
            result = super().get(path)
            if "/labels?" in path and advance_at == "inventory":
                self.base = "new-main"
            return result

        def request(self, method, path, data=None):
            result = super().request(method, path, data)
            if method == "DELETE" and advance_at == "delete":
                self.base = "new-main"
            return result

    api = RacingAPI({"state:funding", "pay:wta"})
    reports = []
    sync_canonical(api, engine, "main", now, reports.append)
    issue_writes = [row for row in api.writes if "/issues/" in row[1]]
    assert len(issue_writes) == (0 if advance_at == "inventory" else 1)
    assert "main advanced" in reports[-1]
    assert "state:open" not in api.labels


def test_summary_does_not_guess_pod_or_hide_conflicts():
    assert "pay:unknown" in summary({"vnext"})
    assert "pay:conflict" in summary({"pay:pod", "pay:wta"})
    assert "pay:unknown" in summary({"pay:typo"})
    assert definition("reward:10-wea")[0] == "0e8a16"


def test_cli_discovers_proposals_without_calling_them_open_work(monkeypatch, capsys):
    def listing(*, repo, label):
        assert label == "vnext"
        return [
            {
                "number": 958,
                "title": "Audit",
                "labels": [
                    "vnext",
                    "pay:pod",
                    "reward:10-wea",
                    "state:proposal",
                    "depth:explore",
                    "audience:pilot",
                    "documentation",
                ],
            }
        ]

    monkeypatch.setattr(cli, "list_open_tasks", listing)
    assert cli.show_tasks(SimpleNamespace(repo="WeTheAgents/wetheagents")) == 0
    text = capsys.readouterr().out
    assert "state:proposal" in text and "reward:10-wea" in text
    assert "not funding or eligibility authority" in text


@pytest.mark.parametrize("pending", [False, True])
def test_existing_tide_syncs_before_pending_and_noop_returns(
    canonical_task, monkeypatch, tmp_path, pending
):
    from wea_vnext.tide import __main__ as tide

    from .test_tide_ledger import workflow_env

    engine, _, _ = canonical_task
    before = engine.state()
    workflow_env(monkeypatch)
    monkeypatch.setattr(tide, "git", lambda *args: "main")
    monkeypatch.setattr(tide, "files", lambda *args: ["bootstrap"])
    monkeypatch.setattr(tide, "load", lambda *args: (engine, []))
    monkeypatch.setattr(tide, "dispatch_guard", lambda *args: None)
    monkeypatch.setattr(tide, "funding_merges", lambda *args: {})
    monkeypatch.setattr(tide, "collect_sources", lambda *args, **kwargs: {})
    monkeypatch.setattr(tide, "retain_artifacts", lambda collection, *args: collection)
    def empty_candidate(*args, access_snapshot, hello_world):
        assert hello_world is None
        return None

    monkeypatch.setattr(tide, "candidate", empty_candidate)

    class WriterAPI(API):
        def get(self, path):
            if "matching-refs" in path:
                return []
            if "/pulls?" in path:
                return (
                    [
                        {
                            "number": 10,
                            "state": "open",
                            "head": {"sha": "candidate"},
                            "html_url": "https://github.com/WeTheAgents/wetheagents/pull/10",
                        }
                    ]
                    if pending
                    else []
                )
            return super().get(path)

        def graphql(self, *args):
            raise AssertionError("source collection is injected")

    api = WriterAPI({"state:funding"})
    tide.run(tmp_path, api, False)
    assert "state:funding" not in api.labels
    assert "pay:pod" in api.labels
    assert engine.state() == before
    assert not list(tmp_path.iterdir())


def test_start_uses_canonical_balance_and_preserves_genome(
    canonical_task, monkeypatch, capsys, tmp_path
):
    from wea_cli import start_snapshot
    from wea_vnext.tide import ledger

    engine, _, _ = canonical_task
    monkeypatch.setattr(ledger, "git", lambda *args: "canonical-sha")
    monkeypatch.setattr(ledger, "load", lambda *args: (engine, []))
    monkeypatch.setattr(
        start_snapshot,
        "_load_genome_identity",
        lambda *args: {
            "role": "Researcher",
            "north_star": "Useful work",
        },
    )
    monkeypatch.setattr(cli, "list_open_tasks", lambda **kwargs: [])
    cli.show_start(
        SimpleNamespace(repo="WeTheAgents/wetheagents"), tmp_path, "agent-author"
    )
    output = capsys.readouterr().out
    assert "Available WEA: 100" in output and "Researcher" in output
    assert "canonical-sha" in output and "Useful work" in output
    assert cli.show_start(SimpleNamespace(), tmp_path, "misspelled-agent") == 1
    assert "Agent not found" in capsys.readouterr().out


def test_remote_task_listing_still_works_without_a_checkout(
    monkeypatch, tmp_path, capsys
):
    from wea_cli import cli as main_cli

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(main_cli, "resolve_agent", lambda *args: None)
    monkeypatch.setattr(main_cli, "list_open_tasks", lambda **kwargs: [])
    assert (
        main_cli.cmd_tasks(SimpleNamespace(repo="WeTheAgents/wetheagents", root=None))
        == 0
    )
    assert "No open task issues found" in capsys.readouterr().out
