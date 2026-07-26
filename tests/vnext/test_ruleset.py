from __future__ import annotations

import hashlib
import importlib
import json
import shutil
import sys
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path
from types import ModuleType

import pytest

import wea_vnext
import wea_vnext.declarations as public_declarations
import wea_vnext.engine as engine
import wea_vnext.executors as executor_namespace
import wea_vnext.executors.v0_6_0 as executor_root
import wea_vnext.executors.v0_6_0.rules as executor_rules
import wea_vnext.identity as public_identity
from wea_vnext.engine import (
    ExecutorDescriptor,
    ExecutorRegistry,
    ManifestError,
    RuntimeMismatchError,
    _load_canonical_json,
    installed_executor,
    load_executor,
)
from wea_vnext.executors.v0_6_0.canonical import (
    CanonicalJSONError,
    canonical_dumps,
    canonical_loads,
)
from wea_vnext.executors.v0_6_0.deadlines import duel_windows, materialize_deadline
from wea_vnext.executors.v0_6_0.identity import Binding, IdentityError
from wea_vnext.executors.v0_6_0.money import (
    MoneyRuleError,
    best_x_payout_vector,
    duel_outcome_vectors,
    progressive_payout_vector,
)
from wea_vnext.executors.v0_6_0.projection import ProjectionIntent
from wea_vnext.executors.v0_6_0.rules import load_ruleset, raw_ruleset_bytes


def test_ruleset_is_packaged_and_already_canonical() -> None:
    raw = raw_ruleset_bytes()
    packaged = resources.files("wea_vnext").joinpath("rulesets/0.6.json").read_bytes()
    ruleset = load_ruleset()

    assert packaged == raw
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert not raw.endswith(b"\n")
    assert ruleset.version == "0.6"
    assert ruleset.interface_version == "0.6"
    assert set(ruleset.content["profiles"]) == {
        "direct-pr",
        "duel",
        "full-build",
        "spec-only",
    }
    assert ruleset.content["profiles"]["direct-pr"]["mechanics"] == (
        "best-x",
        "linear",
        "pod",
        "progressive",
        "winner-take-all",
    )
    assert ruleset.content["review_stages"]["implementation-review"]["fee_wea"] == 1
    assert ruleset.content["review_stages"]["spec-redteam"]["fee_wea"] == 1
    assert set(ruleset.content["transitions"]) == {
        "direct-pr",
        "duel",
        "full-build",
        "infinite-work",
        "pre-contract",
        "spec-only",
        "universal",
    }
    transition_events = {
        transition[1]
        for transitions in ruleset.content["transitions"].values()
        for transition in transitions
    }
    assert {
        "assignment-expired",
        "birdie",
        "body-mismatch",
        "body-restored",
        "contract-activated-direct-pr",
        "contract-activated-duel",
        "contract-activated-full-build",
        "contract-activated-spec-only",
        "decision-expired",
        "rework",
        "stop",
    } <= transition_events
    assert [
        row
        for table in ("direct-pr", "full-build", "spec-only")
        for row in ruleset.content["transitions"][table]
        if row[2] in {"pr-intake", "spec-intake"}
    ] == []
    declared_states = {
        stage
        for profile in ruleset.content["profiles"].values()
        for stage in profile["stages"]
    } | set(ruleset.content["task_state"]["transition_states"])
    assert all(
        source in declared_states and target in declared_states
        for table in ruleset.content["transitions"].values()
        for source, _event, target in table
    )
    assert (
        "implementation-review",
        "review-changes",
        "author-decision",
    ) in ruleset.content["transitions"]["direct-pr"]
    assert (
        "spec-redteam",
        "review-changes",
        "author-decision",
    ) in ruleset.content["transitions"]["spec-only"]
    assert (
        "spec-redteam",
        "review-changes",
        "spec-selection",
    ) in ruleset.content["transitions"]["full-build"]
    assert (
        "review",
        "review-changes",
        "author-decision",
    ) in ruleset.content["transitions"]["infinite-work"]


def test_ruleset_economic_content_is_recursively_immutable() -> None:
    ruleset = load_ruleset()
    original_hash = ruleset.content_hash
    original_vector = best_x_payout_vector(100, 2, ruleset)

    with pytest.raises(TypeError):
        ruleset.content["mechanics"]["best-x"]["percentages"]["2"][0] = 60

    assert ruleset.content_hash == original_hash
    assert best_x_payout_vector(100, 2, ruleset) == original_vector == (70, 30)


def test_executor_rejects_ruleset_replacement_after_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    replacement = raw_ruleset_bytes().replace(b'"2":[70,30]', b'"2":[60,40]')
    assert replacement != raw_ruleset_bytes()
    monkeypatch.setattr(executor_rules, "_resource_bytes", lambda: replacement)

    with pytest.raises(executor_rules.RulesetError, match="do not match executor"):
        executor_rules.load_ruleset()


@pytest.mark.parametrize(
    "raw",
    [
        b'\xef\xbb\xbf{"a":1}',
        b'{"a":1,"a":2}',
        b'{"amount":1.5}',
        b'{"amount":NaN}',
        b'{"amount":' + (b"9" * 641) + b"}",
    ],
)
def test_canonical_loader_rejects_ambiguous_or_non_integer_json(raw: bytes) -> None:
    with pytest.raises(CanonicalJSONError):
        canonical_loads(raw)


def test_canonical_integer_limit_applies_to_decode_and_encode() -> None:
    largest = (b"9" * 640)
    assert canonical_loads(b'{"amount":' + largest + b"}")["amount"] > 0

    with pytest.raises(CanonicalJSONError, match="640 decimal digits"):
        canonical_dumps({"amount": 10**640})


@pytest.mark.parametrize(
    "raw",
    [b'{"value":"\\ud800"}', b'{"\\udfff":"value"}'],
)
def test_canonical_json_rejects_lone_unicode_surrogates(raw: bytes) -> None:
    with pytest.raises(CanonicalJSONError, match="lone Unicode surrogate"):
        canonical_loads(raw)

    decoded = json.loads(raw)
    with pytest.raises(CanonicalJSONError, match="lone Unicode surrogate"):
        canonical_dumps(decoded)


def test_money_and_deadline_tables_are_exact_integer_rules() -> None:
    ruleset = load_ruleset()

    assert progressive_payout_vector(5) == (1, 1, 2, 3, 5)
    assert best_x_payout_vector(18, 3, ruleset) == (10, 5, 3)
    assert duel_outcome_vectors(20) == {
        "inconclusive": ((10, 10), 0),
        "no-completers": ((0, 0), 20),
        "single-completer": ((18, 0), 2),
        "winner": ((18, 2), 0),
    }

    start = datetime(2026, 7, 22, 12, tzinfo=timezone.utc)
    assert materialize_deadline(start, 60).isoformat() == "2026-07-22T12:01:00+00:00"
    windows = duel_windows(start, (10, 20, 30, 40, 50, 60))
    assert windows[0].opens_at == start
    assert windows[-1].due_at.isoformat() == "2026-07-22T12:03:30+00:00"


@pytest.mark.parametrize("winners", [2.0, "2", True, None])
def test_best_x_winner_count_requires_an_exact_integer(winners: object) -> None:
    with pytest.raises(MoneyRuleError, match="integer from 2 through 5"):
        best_x_payout_vector(10, winners, load_ruleset())  # type: ignore[arg-type]


def test_full_build_waits_for_every_selected_branch_before_author_decision() -> None:
    ruleset = load_ruleset()
    profile = ruleset.content["profiles"]["full-build"]
    transitions = ruleset.content["transitions"]["full-build"]

    assert "ready-final" in profile["stages"]
    assert (
        "implementation-review",
        "review-approved",
        "ready-final",
    ) in transitions
    assert ("ready-final", "all-branches-ready", "author-decision") in transitions
    assert (
        "implementation-review",
        "review-approved",
        "author-decision",
    ) not in transitions


def test_engine_verifies_the_contract_triple_and_manifest_closure() -> None:
    descriptor = installed_executor()
    handle = load_executor(descriptor.reference)

    assert handle.reference == descriptor.reference
    assert handle.verify().manifest_hash == descriptor.reference.executor_manifest_hash
    raw_manifest = (
        resources.files("wea_vnext")
        .joinpath("executors/v0_6_0/manifest.json")
        .read_bytes()
    )
    assert not raw_manifest.endswith((b"\n", b"\r"))
    assert (
        hashlib.sha256(raw_manifest).hexdigest()
        == descriptor.reference.executor_manifest_hash
    )

    wrong = descriptor.reference._replace(ruleset_hash="0" * 64)
    with pytest.raises(RuntimeMismatchError, match="Contract runtime triple"):
        load_executor(wrong)


@pytest.mark.parametrize("suffix", [b"\n", b"\r\n", b"\n\n"])
def test_manifest_rejects_every_trailing_newline(suffix: bytes) -> None:
    raw = b'{"executor_version":"0.6.0"}'

    with pytest.raises(ManifestError, match="exact canonical"):
        _load_canonical_json(raw + suffix, source="test-manifest")


@pytest.mark.parametrize(
    "raw",
    [
        b'{"invalid-surrogate":"\\ud800"}',
        b'{"oversized-integer":' + (b"9" * 5000) + b"}",
    ],
)
def test_manifest_normalizes_malformed_json_failures(raw: bytes) -> None:
    with pytest.raises(ManifestError):
        _load_canonical_json(raw, source="malformed-manifest")


def test_deeply_nested_future_manifest_does_not_block_current_executor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = installed_executor()
    package = tmp_path / "wea_vnext"
    shutil.copytree(Path("src/wea_vnext"), package)
    future = package / "executors" / "v9_9_9"
    future.mkdir()
    (future / "manifest.json").write_bytes(
        (b"[" * 5000) + b"0" + (b"]" * 5000)
    )
    monkeypatch.setattr(engine, "_resource_root", lambda: package)

    assert load_executor(current.reference).reference == current.reference


def test_deep_future_executor_tree_does_not_block_current_executor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = installed_executor()
    package = tmp_path / "wea_vnext"
    shutil.copytree(Path("src/wea_vnext"), package)
    future = package / "executors" / "v9_9_9"
    future.mkdir()
    nested = future
    for _index in range(66):
        nested /= "nested"
        nested.mkdir()
    manifest = {
        "executor_version": "9.9.9",
        "files": {"untrusted": "0" * 64},
        "module": "wea_vnext.executors.v9_9_9",
        "python_abi": "py3-none-any",
        "ruleset_path": "rulesets/9.9.json",
        "ruleset_sha256": "0" * 64,
        "semantic_dependencies": {},
        "tide_interface_version": "9.9",
    }
    (future / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    monkeypatch.setattr(engine, "_resource_root", lambda: package)

    assert load_executor(current.reference).reference == current.reference


def test_manifest_integer_limit_does_not_depend_on_interpreter_setting() -> None:
    previous_limit = (
        sys.get_int_max_str_digits()
        if hasattr(sys, "get_int_max_str_digits")
        else None
    )
    try:
        if hasattr(sys, "set_int_max_str_digits"):
            sys.set_int_max_str_digits(0)
        with pytest.raises(ManifestError):
            _load_canonical_json(
                b'{"oversized-integer":' + (b"9" * 641) + b"}",
                source="oversized-manifest",
            )
    finally:
        if previous_limit is not None:
            sys.set_int_max_str_digits(previous_limit)


def test_manifest_rejects_unknown_top_level_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = tmp_path / "wea_vnext"
    shutil.copytree(Path("src/wea_vnext"), package)
    manifest_path = package / "executors" / "v0_6_0" / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["unknown"] = "not-versioned"
    manifest_path.write_bytes(
        json.dumps(
            manifest,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    monkeypatch.setattr(engine, "_resource_root", lambda: package)

    with pytest.raises(ManifestError, match="top-level keys"):
        engine._verify_installed_manifest("wea_vnext.executors.v0_6_0")


def test_manifest_interface_must_match_packaged_rules(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = tmp_path / "wea_vnext"
    shutil.copytree(Path("src/wea_vnext"), package)
    manifest_path = package / "executors" / "v0_6_0" / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["tide_interface_version"] = "9.9"
    manifest_path.write_bytes(
        json.dumps(
            manifest,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    monkeypatch.setattr(engine, "_resource_root", lambda: package)

    with pytest.raises(ManifestError, match="interface does not match"):
        engine._verify_installed_manifest("wea_vnext.executors.v0_6_0")


def test_engine_rejects_noncanonical_rules_even_with_matching_file_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = tmp_path / "wea_vnext"
    executor = package / "executors" / "v9_9_9"
    rules_path = package / "rulesets" / "9.9.json"
    executor.mkdir(parents=True)
    rules_path.parent.mkdir()
    init_raw = b"VALUE = 1\n"
    parent_init_raw = b'"""Executor namespace."""\n'
    canonical_rules = b'{"tide_interface_version":"9.9","version":"9.9"}'
    noncanonical_rules = canonical_rules + b"\n"
    (executor.parent / "__init__.py").write_bytes(parent_init_raw)
    (executor / "__init__.py").write_bytes(init_raw)
    rules_path.write_bytes(noncanonical_rules)
    manifest = {
        "executor_version": "9.9.9",
        "files": {
            "executors/__init__.py": hashlib.sha256(parent_init_raw).hexdigest(),
            "executors/v9_9_9/__init__.py": hashlib.sha256(init_raw).hexdigest(),
            "rulesets/9.9.json": hashlib.sha256(noncanonical_rules).hexdigest(),
        },
        "module": "wea_vnext.executors.v9_9_9",
        "python_abi": "py3-none-any",
        "ruleset_path": "rulesets/9.9.json",
        "ruleset_sha256": hashlib.sha256(canonical_rules).hexdigest(),
        "semantic_dependencies": {},
        "tide_interface_version": "9.9",
    }
    (executor / "manifest.json").write_bytes(
        json.dumps(
            manifest,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    monkeypatch.setattr(engine, "_resource_root", lambda: package)

    with pytest.raises(ManifestError, match="exact canonical JSON bytes"):
        engine._verify_installed_manifest("wea_vnext.executors.v9_9_9")


def test_future_executor_rejects_unverified_semantic_dependencies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = tmp_path / "wea_vnext"
    executor = package / "executors" / "v9_9_9"
    rules_path = package / "rulesets" / "9.9.json"
    executor.mkdir(parents=True)
    rules_path.parent.mkdir()
    init_raw = b"VALUE = 1\n"
    parent_init_raw = b'"""Executor namespace."""\n'
    rules_raw = b'{"tide_interface_version":"9.9","version":"9.9"}'
    (executor.parent / "__init__.py").write_bytes(parent_init_raw)
    (executor / "__init__.py").write_bytes(init_raw)
    rules_path.write_bytes(rules_raw)
    manifest = {
        "executor_version": "9.9.9",
        "files": {
            "executors/__init__.py": hashlib.sha256(parent_init_raw).hexdigest(),
            "executors/v9_9_9/__init__.py": hashlib.sha256(init_raw).hexdigest(),
            "rulesets/9.9.json": hashlib.sha256(rules_raw).hexdigest(),
        },
        "module": "wea_vnext.executors.v9_9_9",
        "python_abi": "py3-none-any",
        "ruleset_path": "rulesets/9.9.json",
        "ruleset_sha256": hashlib.sha256(rules_raw).hexdigest(),
        "semantic_dependencies": {"example-runtime": "1.2.3"},
        "tide_interface_version": "9.9",
    }
    (executor / "manifest.json").write_bytes(
        json.dumps(
            manifest,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    monkeypatch.setattr(engine, "_resource_root", lambda: package)

    with pytest.raises(ManifestError, match="semantic dependencies are not supported"):
        engine.installed_executor("9.9.9")


def test_executor_load_rejects_manifest_replacement_after_verification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = tmp_path / "wea_vnext"
    shutil.copytree(Path("src/wea_vnext"), package)
    module_name = "wea_vnext.executors.v0_6_0"
    monkeypatch.setattr(engine, "_resource_root", lambda: package)
    verified = engine._verify_installed_manifest(module_name)

    source_path = package / "executors" / "v0_6_0" / "declarations.py"
    source_path.write_bytes(source_path.read_bytes() + b"# replacement\n")
    manifest_path = package / "executors" / "v0_6_0" / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["files"]["executors/v0_6_0/declarations.py"] = hashlib.sha256(
        source_path.read_bytes()
    ).hexdigest()
    manifest_path.write_bytes(
        json.dumps(
            manifest,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    with pytest.raises(ManifestError, match="changed after executor verification"):
        engine._load_verified_module(module_name, verified)


def test_executor_handle_rejects_replacement_before_module_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = tmp_path / "wea_vnext"
    shutil.copytree(Path("src/wea_vnext"), package)
    monkeypatch.setattr(engine, "_resource_root", lambda: package)
    descriptor = installed_executor()
    handle = load_executor(descriptor.reference)

    source_path = package / "executors" / "v0_6_0" / "__init__.py"
    source_path.write_bytes(source_path.read_bytes() + b"TAMPERED = True\n")
    manifest_path = package / "executors" / "v0_6_0" / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["files"]["executors/v0_6_0/__init__.py"] = hashlib.sha256(
        source_path.read_bytes()
    ).hexdigest()
    manifest_path.write_bytes(
        json.dumps(
            manifest,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )

    with pytest.raises(RuntimeMismatchError, match="changed after"):
        _ = handle.module


def test_executor_handle_returns_only_fresh_verified_submodules(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handle = load_executor(installed_executor().reference)
    verified_module = handle.import_module("declarations")
    fullname = f"{handle.descriptor.module_name}.declarations"
    replacement = ModuleType(fullname)
    replacement.parse_declaration = lambda _raw: "UNVERIFIED"  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, fullname, replacement)

    resolved = handle.import_module("declarations")

    assert resolved is not verified_module
    assert resolved is not replacement
    assert resolved.parse_declaration("anything") != "UNVERIFIED"


def test_executor_handle_does_not_expose_a_mutable_module_namespace() -> None:
    handle = load_executor(installed_executor().reference)
    first = handle.module
    original_replay = first.replay

    with pytest.raises(AttributeError, match="read-only"):
        first.replay = lambda *_args: ("UNVERIFIED",) * 6
    with pytest.raises(AttributeError, match="private"):
        _ = first.__dict__

    second = handle.module

    assert second is not first
    assert second.replay is not original_replay
    assert second.replay((), handle.reference)[5].startswith(b"{")


def test_executor_callable_mutation_cannot_poison_a_later_load() -> None:
    handle = load_executor(installed_executor().reference)
    poisoned = handle.module
    poisoned.serialize_report.__globals__["canonical_dumps"] = (
        lambda _value: b"UNVERIFIED"
    )

    fresh = handle.module

    assert fresh.serialize_report is not poisoned.serialize_report
    assert fresh.replay((), handle.reference)[5] != b"UNVERIFIED"


def test_verified_loader_restores_ordinary_parent_package_bindings() -> None:
    ordinary_rules = executor_rules

    _ = load_executor(installed_executor().reference).module

    assert wea_vnext.executors is executor_namespace
    assert executor_namespace.v0_6_0 is executor_root
    assert executor_root.rules is ordinary_rules
    assert importlib.import_module("wea_vnext.executors") is executor_namespace
    assert importlib.import_module("wea_vnext.executors.v0_6_0") is executor_root
    assert (
        importlib.import_module("wea_vnext.executors.v0_6_0.rules")
        is ordinary_rules
    )


def test_public_facades_keep_class_and_exception_identity() -> None:
    declaration = public_declarations.parse_declaration(
        "### Декларация WEA\n- action: test"
    )

    assert isinstance(declaration, public_declarations.Declaration)
    with pytest.raises(public_declarations.DeclarationError):
        public_declarations.parse_declaration("### Декларация WEA\ninvalid")

    binding = public_identity.Binding(
        "binding-1",
        "agent",
        "U_kgDOAccount",
        "agent-1",
        1,
        datetime(2026, 7, 22, tzinfo=timezone.utc),
    )

    assert (
        public_identity.resolve_binding(
            (binding,),
            github_account_id="U_kgDOAccount",
            subject_id="agent-1",
            effective_at=datetime(2026, 7, 22, tzinfo=timezone.utc),
        )
        is binding
    )
    with pytest.raises(public_identity.IdentityError):
        public_identity.resolve_binding(
            (),
            github_account_id="U_kgDOAccount",
            subject_id="agent-1",
            effective_at=datetime(2026, 7, 22, tzinfo=timezone.utc),
        )


@pytest.mark.parametrize("labels", ["paid", b"paid", ("paid", "")])
def test_projection_labels_require_a_non_string_sequence(
    labels: object,
) -> None:
    with pytest.raises(ValueError, match="sequence of non-empty strings"):
        ProjectionIntent(
            repository="WeTheAgents/wetheagents",
            issue_id="1",
            transaction_id="tx-1",
            labels=labels,  # type: ignore[arg-type]
            issue_state="open",
            confirmation="ok",
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("repository", ""),
        ("issue_id", None),
        ("transaction_id", 123),
        ("confirmation", ""),
    ],
)
def test_projection_identifiers_require_exact_non_empty_strings(
    field: str,
    value: object,
) -> None:
    values = {
        "repository": "WeTheAgents/wetheagents",
        "issue_id": "1",
        "transaction_id": "tx-1",
        "labels": ("paid",),
        "issue_state": "open",
        "confirmation": "ok",
    }
    values[field] = value

    with pytest.raises(ValueError, match=rf"{field}.*non-empty string"):
        ProjectionIntent(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("binding_id", 1),
        ("github_account_id", 123),
        ("subject_id", ["agent"]),
    ],
)
def test_identity_binding_requires_exact_string_ids(field: str, value: object) -> None:
    values = {
        "binding_id": "binding-1",
        "actor_kind": "agent",
        "github_account_id": "U_kgDOAccount",
        "subject_id": "agent-1",
        "version": 1,
        "effective_from": datetime(2026, 7, 22, tzinfo=timezone.utc),
    }
    values[field] = value

    with pytest.raises(IdentityError, match=rf"{field}.*non-empty string"):
        Binding(**values)  # type: ignore[arg-type]


def test_adding_an_executor_does_not_change_resolution_of_existing_contract() -> None:
    current = installed_executor()
    fake_reference = current.reference._replace(
        ruleset_hash="1" * 64,
        executor_manifest_hash="2" * 64,
    )
    registry = ExecutorRegistry(
        (
            current,
            ExecutorDescriptor(reference=fake_reference, module_name="future.executor"),
        )
    )

    assert registry.resolve(current.reference) == current
