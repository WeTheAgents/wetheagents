"""Synthetic package authority; no test receipt is real operator approval."""

import copy
import hashlib
import json
from types import SimpleNamespace

import pytest

from wea_vnext.tide import __main__ as cli
from wea_vnext.tide import hello_world as hw
from wea_vnext.tide import package_transition as pt
from wea_vnext.tide.ledger import STATE, candidate, load, validate
from wea_vnext.tide.replay import ReplayError, digest

from .test_hello_world_candidate import acceptance, event, native  # noqa: F401
from .test_hello_world_financial import (
    capture,
    financial,  # noqa: F401
    greeting,
    raw,
    transact,
)
from .test_tide_ledger import commit, put


def source_for(engine, base, manifest, revision="github:TEST-package:created"):
    previous = engine.hello_world_package
    auth = {
        "schema": pt.SCHEMA,
        "anchor_sha256": digest(engine.hello_world_anchor),
        "previous_package_sha256": pt.current_hash(engine),
        "package_sha256": digest(manifest),
        "previous_transition_sha256": digest(previous) if previous else None,
        "previous_tide_hash": engine.last_hash,
        "predecessor": base,
        "code_sha": base,
    }
    row = {
        "repository_id": "1171421025",
        "issue_id": "4015417565",
        "issue_number": 1,
        "object_kind": "issue_comment",
        "object_id": "TEST-package",
        "revision_id": revision,
        "revision_status": "confirmed",
        "actor_account_id": "129645949",
        "original_author_account_id": "129645949",
        "edit_history": [],
        "created_at": "2026-10-01T00:00:11+00:00",
        "effective_at": "2026-10-01T00:00:11+00:00",
        "body": pt.MARKER + json.dumps(auth),
    }
    row["content_hash"] = hashlib.sha256(row["body"].encode()).hexdigest()
    return row


@pytest.fixture
def packet():
    old = {
        "wea_vnext/tide/ledger.py": "1" * 64,
        "wea_vnext/executors/v0_11_0/sources.py": "2" * 64,
        "wea_vnext/rulesets/0.11.json": "3" * 64,
    }
    new = {**old, "wea_vnext/repair.py": "4" * 64}
    engine = SimpleNamespace(
        hello_world_anchor={
            "checkpoint": {"installation_sha256": digest(old), "predecessor": "a" * 40}
        },
        hello_world_package=None,
        hello_world={"contract": {"body_hash": hashlib.sha256(b"issue").hexdigest()}},
        last_cutoff="2026-10-01T00:00:10+00:00",
        last_hash="5" * 64,
    )
    row = source_for(engine, "b" * 40, new)
    issue = {
        "object_kind": "issue",
        "object_id": "4015417565",
        "repository_id": "1171421025",
        "revision_status": "confirmed",
        "body": "issue",
        "content_hash": hashlib.sha256(b"issue").hexdigest(),
        "issue_state": "open",
        "revision_id": "TEST-issue",
    }
    batch = {
        "predecessor": "b" * 40,
        "hello_world": engine.hello_world_anchor,
        "collection": {"sources": [issue, row], "cutoff": "2026-10-01T00:00:20+00:00"},
    }
    record = {
        "schema": pt.SCHEMA,
        "source_revision_id": row["revision_id"],
        "previous_code_sha": "a" * 40,
        "previous_manifest": old,
        "manifest": new,
        "authorization": json.loads(row["body"][len(pt.MARKER) :]),
    }
    return engine, batch, record


def test_exact_retained_transition_is_pure(packet, monkeypatch):
    engine, batch, record = packet
    before = copy.deepcopy(vars(engine))
    monkeypatch.setattr(
        pt, "git_manifest", lambda *_: pytest.fail("pure replay read Git")
    )
    monkeypatch.setattr(
        hw, "package_files", lambda: pytest.fail("pure replay read install")
    )
    pt.validate(engine, batch, record)
    assert vars(engine) == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("repository_id", "999"),
        ("issue_id", "999"),
        ("issue_number", True),
        ("object_kind", "issue"),
        ("actor_account_id", "1001"),
        ("original_author_account_id", "1001"),
        ("revision_status", "unresolved"),
        ("edit_history", [{}]),
        ("content_hash", "0" * 64),
        ("created_at", "2026-10-01T00:00:09+00:00"),
        ("effective_at", "2026-10-01T00:00:21+00:00"),
    ],
)
def test_source_authority_negative(packet, field, value):
    engine, batch, record = packet
    batch["collection"]["sources"][-1][field] = value
    with pytest.raises(ReplayError):
        pt.validate(engine, batch, record)


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "duplicate",
        "edited-revision",
        "duplicate-fields",
        "closed-issue",
        "changed-issue",
        "unconfirmed-issue",
        "pre-cutoff",
        "future",
        "extra-field",
    ],
)
def test_source_structure_negative(packet, mutation):
    engine, batch, record = packet
    rows = batch["collection"]["sources"]
    row = rows[-1]
    if mutation == "missing":
        rows.pop()
    elif mutation == "duplicate":
        rows.append(copy.deepcopy(row))
    elif mutation == "edited-revision":
        row["revision_id"] = record["source_revision_id"] = "github:TEST:edited"
    elif mutation == "duplicate-fields":
        row["body"] = pt.MARKER + '{"schema":"one","schema":"two"}'
    elif mutation == "closed-issue":
        rows[0]["issue_state"] = "closed"
    elif mutation == "changed-issue":
        rows[0]["body"] = "changed"
    elif mutation == "unconfirmed-issue":
        rows[0]["revision_status"] = "unresolved"
    elif mutation in {"pre-cutoff", "future"}:
        at = (
            "2026-10-01T00:00:10+00:00"
            if mutation == "pre-cutoff"
            else "2026-10-01T00:00:21+00:00"
        )
        row["created_at"] = row["effective_at"] = at
    else:
        auth = json.loads(row["body"][len(pt.MARKER) :])
        auth["extra"] = True
        row["body"] = pt.MARKER + json.dumps(auth)
    row["content_hash"] = hashlib.sha256(row["body"].encode()).hexdigest()
    with pytest.raises(ReplayError):
        pt.validate(engine, batch, record)


@pytest.mark.parametrize("field", sorted(pt.FIELDS))
def test_exact_authorization_binding(packet, field):
    engine, batch, record = packet
    record["authorization"][field] = "wrong"
    row = batch["collection"]["sources"][-1]
    row["body"] = pt.MARKER + json.dumps(record["authorization"])
    row["content_hash"] = hashlib.sha256(row["body"].encode()).hexdigest()
    with pytest.raises(ReplayError):
        pt.validate(engine, batch, record)


@pytest.mark.parametrize("mutation", ["changed", "added", "deleted", "ruleset"])
def test_native_closure_invariance(packet, mutation):
    engine, batch, record = packet
    paths = record["manifest"]
    if mutation == "changed":
        paths["wea_vnext/executors/v0_11_0/sources.py"] = "9" * 64
    elif mutation == "added":
        paths["wea_vnext/executors/new/source.py"] = "9" * 64
    elif mutation == "deleted":
        paths.pop("wea_vnext/executors/v0_11_0/sources.py")
    else:
        paths["wea_vnext/rulesets/0.11.json"] = "9" * 64
    with pytest.raises(ReplayError, match="native closures"):
        pt.validate(engine, batch, record)


@pytest.mark.parametrize(
    "mutation", ["old-code", "old-hash", "old-manifest", "no-op", "anchor", "inactive"]
)
def test_chain_and_initial_boundary(packet, mutation):
    engine, batch, record = packet
    if mutation == "old-code":
        record["previous_code_sha"] = "c" * 40
    elif mutation == "old-hash":
        record["previous_manifest"]["wea_vnext/tide/ledger.py"] = "8" * 64
    elif mutation == "old-manifest":
        engine.hello_world_package = copy.deepcopy(record)
    elif mutation == "no-op":
        record["manifest"] = copy.deepcopy(record["previous_manifest"])
    elif mutation == "anchor":
        batch["hello_world"] = {}
    else:
        engine.hello_world_anchor = None
    with pytest.raises(ReplayError):
        pt.validate(engine, batch, record)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"activation_comment_id": 1, "hello_world_package_revision": "r"},
        {"activation_sha256": "s", "hello_world_package_revision": "r"},
        {"hello_world_installation_revision": "i", "hello_world_package_revision": "r"},
    ],
)
def test_exclusive_inputs_fail_before_network(tmp_path, kwargs):
    with pytest.raises(ReplayError, match="exclusive"):
        cli.run(tmp_path, None, False, **kwargs)


@pytest.mark.parametrize(
    "mutation", ["none", "old-git", "new-git", "installed", "missing", "added"]
)
def test_live_manifest_boundaries_are_independent(
    packet, monkeypatch, tmp_path, mutation
):
    engine, _, record = packet
    old, new = record["previous_manifest"], record["manifest"]
    expected = copy.deepcopy(new)

    def git_bytes(_root, commit):
        result = copy.deepcopy(old if commit == "a" * 40 else new)
        if (mutation == "old-git" and commit == "a" * 40) or (
            mutation == "new-git" and commit == "b" * 40
        ):
            result["wea_vnext/tide/ledger.py"] = "f" * 64
        return result

    if mutation == "installed":
        expected["wea_vnext/tide/ledger.py"] = "e" * 64
    elif mutation == "missing":
        expected.pop("wea_vnext/repair.py")
    elif mutation == "added":
        expected["wea_cli/extra.py"] = "e" * 64
    monkeypatch.setattr(pt, "git_manifest", git_bytes)
    monkeypatch.setattr(hw, "package_files", lambda: expected)
    if mutation == "none":
        pt.verify_installed(tmp_path, "b" * 40, engine, record)
    else:
        with pytest.raises(ReplayError):
            pt.verify_installed(tmp_path, "b" * 40, engine, record)


@pytest.mark.parametrize("financial", ["package"], indirect=True)
def test_real_git_transition_guard_replay_retry_and_money(financial, monkeypatch):  # noqa: F811
    root, _, n, anchor, sources = financial
    active, before = transact(financial, sources)
    engine, _ = load(root, active)
    assert "hello_world_package" not in before
    original_manifest = pt.git_manifest(root, anchor["checkpoint"]["predecessor"])
    assert digest(original_manifest) == anchor["checkpoint"]["installation_sha256"]
    (root / "src/wea_vnext/operational_test.py").write_bytes(
        b"# synthetic package change\n"
    )
    base = commit(root)
    manifest = pt.git_manifest(root, base)
    monkeypatch.setattr(hw, "package_files", lambda: manifest)
    with pytest.raises(ReplayError, match="installed package differs"):
        candidate(
            root,
            base,
            capture(sources, 20),
            {},
            {},
            access_snapshot=engine.access_snapshot,
        )
    source = source_for(engine, base, manifest)
    # Native fixture's epoch differs from the pure packet's illustrative epoch.
    from datetime import timedelta

    from .test_hello_world_candidate import NOW

    source["created_at"] = source["effective_at"] = (
        NOW + timedelta(seconds=11)
    ).isoformat()
    sources += [source]
    values = candidate(
        root,
        base,
        capture(sources, 20),
        {},
        {"run_id": "1", "run_attempt": "1"},
        access_snapshot=engine.access_snapshot,
        package_revision=source["revision_id"],
    )
    assert values is not None
    after = values[STATE]
    for key in (
        "balances",
        "current_supply",
        "opening_supply",
        "escrow_wea",
        "tasks",
        "hello_world",
        "hello_world_anchor",
    ):
        assert after[key] == before[key]
    assert after["hello_world_package"]["authorization"]["package_sha256"] == digest(
        manifest
    )
    put(root, values)
    head = commit(root)
    assert validate(root, base, head) == after
    # The trusted guard independently compares its recaptured boundary. A claimed
    # confirmed source in the candidate cannot substitute for that fresh boundary.
    from wea_vnext.tide import ledger

    captured = capture(sources, 20)

    class API:
        def get(self, path):
            if path.endswith("git/ref/heads/main"):
                return {"object": {"sha": base}}
            if "/actions/runs/" in path:
                return {
                    "head_sha": base,
                    "path": ".github/workflows/tide.yml",
                    "event": "workflow_dispatch",
                    "head_branch": "main",
                    "run_started_at": NOW.isoformat(),
                    "updated_at": (NOW + timedelta(seconds=30)).isoformat(),
                }
            raise AssertionError(path)

        def graphql(self, *args):
            raise AssertionError("synthetic authenticated collection is injected")

    with monkeypatch.context() as guard:
        guard.setattr(ledger.domain, "capture", lambda *_: engine.access_snapshot)
        # The synthetic initial fixture has no GitHub merge receipts or tasks.
        guard.setattr(ledger, "funding_merges", lambda *_: {})
        guard.setattr(hw, "collect_hello_world_sources", lambda *_, **__: captured)
        guard.setattr(ledger, "retain_artifacts", lambda value, *_: value)
        assert validate(root, base, head, api=API()) == after
        captured = copy.deepcopy(captured)
        captured["sources"][-1]["actor_account_id"] = "1001"
        captured["capture_hash"] = digest(hw.collection.cutoff_evidence(captured))
        with pytest.raises(ReplayError, match="authenticated GitHub reads"):
            validate(root, base, head, api=API())
    reloaded, _ = load(root, head)
    assert reloaded.state() == after
    assert (
        pt.prepare(root, head, reloaded, capture(sources, 30), source["revision_id"])
        is None
    )
    assert (
        candidate(
            root,
            head,
            capture(sources, 30),
            {},
            {},
            access_snapshot=engine.access_snapshot,
            package_revision=source["revision_id"],
        )
        is None
    )
    # An independent exact-byte check rejects code that is absent from Git.
    monkeypatch.setattr(
        hw, "package_files", lambda: {**manifest, "wea_cli/rogue.py": "f" * 64}
    )
    with pytest.raises(ReplayError, match="installed bytes"):
        candidate(
            root,
            head,
            capture(sources, 30),
            {},
            {},
            access_snapshot=engine.access_snapshot,
        )
    monkeypatch.setattr(hw, "package_files", lambda: manifest)
    work = greeting(n, 31)
    sources += [raw(work), raw(acceptance(n, work, 32))]
    paid_values = candidate(
        root, head, capture(sources, 40), {}, {}, access_snapshot=engine.access_snapshot
    )
    assert (
        paid_values[STATE]["balances"]["base@test"]
        == before["balances"]["base@test"] + 42
    )
    assert paid_values[STATE]["hello_world_anchor"] == anchor
    put(root, paid_values)
    paid_head = commit(root)
    paid, _ = load(root, paid_head)
    assert paid.state() == paid_values[STATE]
    assert (
        candidate(
            root,
            paid_head,
            capture(sources, 50),
            {},
            {},
            access_snapshot=engine.access_snapshot,
        )
        is None
    )
    # A second explicitly authorized package extends the exact canonical chain.
    (root / "src/wea_vnext/operational_test.py").write_bytes(
        b"# second synthetic change\n"
    )
    next_base = commit(root)
    second_manifest = pt.git_manifest(root, next_base)
    monkeypatch.setattr(hw, "package_files", lambda: second_manifest)
    source2 = source_for(
        paid, next_base, second_manifest, "github:TEST-package2:created"
    )
    source2["object_id"] = "TEST-package2"
    source2["created_at"] = source2["effective_at"] = (
        NOW + timedelta(seconds=61)
    ).isoformat()
    sources.append(source2)
    second_values = candidate(
        root,
        next_base,
        capture(sources, 70),
        {},
        {},
        access_snapshot=engine.access_snapshot,
        package_revision=source2["revision_id"],
    )
    chain = second_values[STATE]["hello_world_package"]
    assert chain["authorization"]["previous_transition_sha256"] == digest(
        after["hello_world_package"]
    )
    assert chain["previous_manifest"] == manifest
    assert second_values[STATE]["balances"] == paid.state()["balances"]
    put(root, second_values)
    second_head = commit(root)
    assert validate(root, next_base, second_head) == second_values[STATE]
    final, _ = load(root, second_head)
    assert final.state() == second_values[STATE]
    assert (
        pt.prepare(
            root, second_head, final, capture(sources, 80), source2["revision_id"]
        )
        is None
    )
    with pytest.raises(ReplayError):
        pt.prepare(
            root, second_head, final, capture(sources, 80), source["revision_id"]
        )
