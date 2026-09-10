"""Retryable GitHub display updates, separate from financial replay."""

from __future__ import annotations

from urllib.parse import quote

from ..task_labels import definition, managed, names, project
from .collection import API_ROOT
from .github import GitHubError


class MainAdvanced(RuntimeError):
    """A label update must wait for the next canonical pass."""


class LabelSync:
    def __init__(self, api):
        self.api = api
        self.catalog = None

    def ensure(self, desired):
        if self.catalog is None:
            self.catalog = set()
            for page in range(1, 101):
                rows = self.api.get(f"{API_ROOT}/labels?per_page=100&page={page}")
                self.catalog.update(item["name"] for item in rows)
                if len(rows) < 100:
                    break
            else:
                raise GitHubError("label inventory exceeded its page bound")
        for name in sorted(desired - self.catalog):
            color, description = definition(name)
            self.api.request(
                "POST",
                f"{API_ROOT}/labels",
                {"name": name, "color": color, "description": description},
            )
            self.catalog.add(name)

    def check_base(self, base):
        if (
            base is not None
            and self.api.get(f"{API_ROOT}/git/ref/heads/main")["object"]["sha"] != base
        ):
            raise MainAdvanced

    def update(self, number, current, desired, *, base=None):
        remove = {name for name in current if managed(name)} - desired
        add = desired - current
        if not remove and not add:
            return False
        self.check_base(base)
        self.ensure(add)
        path = f"{API_ROOT}/issues/{number}/labels"
        for name in sorted(remove):
            self.check_base(base)
            self.api.request("DELETE", path + "/" + quote(name, safe=""))
        if add:
            self.check_base(base)
            self.api.request("POST", path, {"labels": sorted(add)})
        return True


def sync_canonical(api, engine, base, now, report):
    """Run before pending/no-op returns; never receives candidate state."""
    sync = LabelSync(api)
    for issue_id, task in engine.state()["tasks"].items():
        number = next(
            raw["issue_number"]
            for raw in engine.sources.values()
            if raw["issue_id"] == issue_id
        )
        try:
            issue = api.get(f"{API_ROOT}/issues/{number}")
            desired = project(task, now, issue_closed=issue["state"] == "closed")
            if sync.update(number, names(issue), desired, base=base):
                report(f"Task labels synchronized: #{number} at canonical {base}.")
        except MainAdvanced:
            report("Task labels deferred: main advanced; retry at the next Tide.")
            return
        except GitHubError as exc:
            report(
                f"Task labels unresolved for #{number}: {exc}. "
                "Retry at the next Tide; settlement continues."
            )
