"""DA-01/06/08 visibility delta: public reading grants no protocol authority."""

# Imported fixtures intentionally share test-argument names.
# ruff: noqa: F811

from __future__ import annotations

import argparse
from datetime import timedelta

import pytest

from wea_cli import access as cli
from wea_vnext import access_control as c
from wea_vnext import access_github as g

from .test_access_runtime import (  # noqa: F401
    ACCOUNT,
    AT,
    GitAPI,
    declaration,
    genesis,
    identities,
)


@pytest.mark.parametrize("private", [True, False])
@pytest.mark.parametrize("mutation", ["id", "name", "missing", None, "false", 0, 1])
def test_foreign_or_ambiguous_visibility_cannot_reach_intake(private, mutation):
    api = GitAPI()
    repo = {"id": g.REPOSITORY_ID, "full_name": g.REPOSITORY, "private": private}
    if mutation == "id":
        repo["id"] = 123
    elif mutation == "name":
        repo["full_name"] = "Other/repository"
    elif mutation == "missing":
        repo.pop("private")
    else:
        repo["private"] = mutation

    def get(path):
        assert path == g.API_ROOT, "Invalid metadata must fail before intake"
        return repo

    api.get = get
    with pytest.raises(ValueError, match="canonical repository"):
        g.repository(api, 997)
    assert not api.writes


@pytest.mark.parametrize("private", [True, False])
@pytest.mark.parametrize("unauthorized", [True, False])
def test_visibility_preserves_authority_interval_and_readback(
    genesis, identities, monkeypatch, private, unauthorized
):
    api = GitAPI()
    api.private = private
    g.Journal(api).append(None, "genesis.json", genesis)
    assert g.repository(api, 997)["id"] == 997997
    src = declaration(genesis)
    if unauthorized:
        src["actor_account_id"] = src["original_author_account_id"] = "123"
    result = g.process(api, src, identities, "b" * 40, {}, lambda: AT)
    journal = g.Journal(api)
    journal.read()
    if unauthorized:
        assert result["status"] == "rejected"
        assert not journal.state.grants
    else:
        assert result["status"] == "active"
        grant = journal.state.grants[0]
        assert grant.ends_at - grant.starts_at == timedelta(seconds=604800)
        monkeypatch.setattr(c, "utcnow", lambda: grant.ends_at)
        observed = cli.read(
            api, argparse.Namespace(agent="Codex-2@codex", request_id=None), ACCOUNT
        )
        assert observed["decisions"][0]["status"] == "expired"


@pytest.mark.parametrize("private", [True, False])
@pytest.mark.parametrize("mutation", ["number", "pull_request"])
def test_visibility_does_not_authorize_a_foreign_issue_or_pr(private, mutation):
    api = GitAPI()
    api.private = private
    original_get = api.get

    def get(path):
        item = original_get(path)
        if path.endswith("/issues/997"):
            if mutation == "number":
                item["number"] = 998
            else:
                item["pull_request"] = {}
        return item

    api.get = get
    with pytest.raises(ValueError, match="configured Issue"):
        g.repository(api, 997)
    assert not api.writes
