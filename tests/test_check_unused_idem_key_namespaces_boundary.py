"""Boundary-spec tests for scripts/check_unused_idem_key_namespaces.py.

Covers format variants, namespace edge cases, key-count limits, JSON structure
variants, and the output contract (exit codes and JSON shape).

Any test that reveals a behaviour that is not yet explicitly documented in the
script is marked with a GAP comment.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from scripts.check_unused_idem_key_namespaces import (
    SHA256_NAMESPACE,
    build_namespace_report,
    extract_namespace,
    load_recorded_idem_keys,
    main,
    run_check,
)


# ── helpers ───────────────────────────────────────────────────────────────────


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _make_repo(
    root: Path,
    *,
    idem_keys: dict[str, object] | None = None,
    top_level: dict[str, object] | None = None,
) -> Path:
    """Create an idem_keys.json with a nested 'keys' dict and optional top-level entries."""
    payload: dict[str, object] = {"version": 5, "keys": idem_keys or {}}
    if top_level:
        payload.update(top_level)
    _write_json(root / "ledger" / "idem_keys.json", payload)
    return root


def _make_flat_repo(root: Path, payload: dict[str, object]) -> Path:
    """Create an idem_keys.json with NO 'keys' sub-object — flat top-level keys only."""
    _write_json(root / "ledger" / "idem_keys.json", payload)
    return root


# ── Format Variants ───────────────────────────────────────────────────────────


def test_format_variant_sha256_boundary_63_chars() -> None:
    """A 63-char lowercase hex string is one character short of SHA-256 length and is NOT
    classified as a SHA-256 namespace; extract_namespace returns None."""
    assert extract_namespace("a" * 63) is None


def test_format_variant_sha256_boundary_65_chars() -> None:
    """A 65-char lowercase hex string is one character over SHA-256 length and is NOT
    classified as a SHA-256 namespace; extract_namespace returns None."""
    assert extract_namespace("a" * 65) is None


def test_format_variant_pipe_key_trailing_pipe() -> None:
    """A pipe-separated key with an empty suffix ('payment|') still extracts 'payment' as
    its namespace because the split yields a non-empty prefix."""
    assert extract_namespace("payment|") == "payment"


def test_format_variant_dashed_escrow_cancel() -> None:
    """'escrow-cancel-N' matches the dashed-namespace pattern and resolves to the
    recognized namespace 'escrow-cancel'."""
    assert extract_namespace("escrow-cancel-42") == "escrow-cancel"


def test_format_variant_legacy_short_key_bare_namespace() -> None:
    """'join' (4 characters) is in SUPPORTED_BARE_NAMESPACES and is correctly classified
    as its own namespace even though it carries no separator."""
    assert extract_namespace("join") == "join"


def test_format_variant_sha256_uppercase_not_recognized() -> None:
    # GAP-4: The SHA-256 regex (_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")) is
    # lowercase-only. A 64-character uppercase hex string does NOT match and is returned
    # as None (unclassifiable) rather than SHA256_NAMESPACE.
    # Documented gap: whether uppercase SHA-256 hashes are intentionally excluded is not
    # stated in the script; if they can occur in idem_keys.json they will trigger a FAIL.
    assert extract_namespace("A" * 64) is None


# ── Namespace Edge Cases ──────────────────────────────────────────────────────


def test_namespace_edge_empty_prefix_pipe_key() -> None:
    """A pipe key whose first segment is empty ('|rest') yields an empty prefix string
    which the script converts to None → the key is unclassifiable."""
    assert extract_namespace("|rest") is None


def test_namespace_edge_prefix_of_recognized_namespace() -> None:
    # GAP-1: 'pay' is a strict prefix of the recognized namespace 'payment' but is not
    # itself a member of RECOGNIZED_NAMESPACES. The script uses exact-match comparison
    # with no prefix-expansion semantics, so 'pay|1|alice' is UNRECOGNIZED → FAIL.
    # Documented gap: the spec does not state whether prefix-of-recognized should PASS
    # or FAIL; current behaviour is FAIL (strict matching only).
    assert extract_namespace("pay|1|alice") == "pay"
    report = build_namespace_report(["pay|1|alice"])
    assert report["status"] == "FAIL"
    assert report["unrecognized_namespaces"][0]["namespace"] == "pay"


def test_namespace_edge_recognized_namespace_as_bare_key() -> None:
    # GAP-2: 'escrow' is present in RECOGNIZED_NAMESPACES but is absent from
    # SUPPORTED_BARE_NAMESPACES. A bare key 'escrow' (no pipe, no underscore, not a
    # dashed pattern) therefore resolves to namespace None and is silently misclassified
    # as unclassifiable — even though 'escrow' is a known namespace word.
    # Documented gap: RECOGNIZED_NAMESPACES and SUPPORTED_BARE_NAMESPACES are not kept
    # in sync; any namespace that never appears as a bare token is safe, but this
    # divergence should be explicitly noted in the script.
    assert extract_namespace("escrow") is None


def test_namespace_edge_empty_string_key() -> None:
    # GAP-3: An empty string ('') as a key immediately short-circuits in extract_namespace
    # (``if not raw_key: return None``) and is reported as an unclassifiable key.
    # Whether an empty-string key should be rejected at load time is not currently
    # enforced; the script tolerates it and flags it via the None-namespace bucket.
    assert extract_namespace("") is None


# ── Key Count Boundaries ──────────────────────────────────────────────────────


def test_key_count_exactly_one_recognized(temp_repo: Path) -> None:
    """A file with exactly one recognized key must yield exit code 0 and status PASS,
    and the summary must report unique_keys_checked == 1."""
    root = _make_repo(temp_repo, idem_keys={"payment|1|alice@test": "2026-04-22T00:00:00Z"})
    report, exit_code = run_check(root)
    assert exit_code == 0
    assert report["status"] == "PASS"
    assert report["summary"]["unique_keys_checked"] == 1


def test_key_count_exactly_one_unrecognized(temp_repo: Path) -> None:
    """A file with exactly one unrecognized key must yield exit code 1 and status FAIL,
    and the summary must report unique_keys_checked == 1."""
    root = _make_repo(temp_repo, idem_keys={"bogus|1|alice@test": "2026-04-22T00:00:00Z"})
    report, exit_code = run_check(root)
    assert exit_code == 1
    assert report["status"] == "FAIL"
    assert report["summary"]["unique_keys_checked"] == 1


def test_key_count_1000_keys_all_recognized_performance(temp_repo: Path) -> None:
    """1 000 recognized payment keys must all be classified correctly and the entire
    run_check call must complete within the 2-second performance budget."""
    keys = {f"payment|{i}|alice@test": "2026-04-22T00:00:00Z" for i in range(1000)}
    root = _make_repo(temp_repo, idem_keys=keys)

    start = time.perf_counter()
    report, exit_code = run_check(root)
    elapsed = time.perf_counter() - start

    assert exit_code == 0
    assert report["status"] == "PASS"
    assert report["summary"]["unique_keys_checked"] == 1000
    assert elapsed < 2.0, f"run_check took {elapsed:.3f}s — exceeded 2-second budget"


# ── JSON Structure ────────────────────────────────────────────────────────────


def test_json_flat_format_no_keys_field(temp_repo: Path) -> None:
    """A flat JSON object with no 'keys' sub-object is valid; all non-reserved top-level
    keys are loaded as idem keys (the nested path is simply skipped)."""
    _make_flat_repo(
        temp_repo,
        {
            "payment|1|alice@test": "2026-04-22T00:00:00Z",
            "verify|1|alice@test": "2026-04-22T00:00:00Z",
        },
    )
    keys = load_recorded_idem_keys(temp_repo / "ledger" / "idem_keys.json")
    assert sorted(keys) == sorted(["payment|1|alice@test", "verify|1|alice@test"])


def test_json_nested_format_only(temp_repo: Path) -> None:
    """A file that uses only the nested 'keys' dict (no top-level non-reserved keys)
    loads exactly the keys from the nested object and nothing else."""
    root = _make_repo(
        temp_repo,
        idem_keys={"payment|1|alice@test": "2026-04-22T00:00:00Z"},
    )
    keys = load_recorded_idem_keys(root / "ledger" / "idem_keys.json")
    assert keys == ["payment|1|alice@test"]


def test_json_both_nested_and_top_level_counted(temp_repo: Path) -> None:
    """When a file contains both a nested 'keys' dict and top-level non-reserved keys,
    both sources are merged and every key is counted in the report."""
    root = _make_repo(
        temp_repo,
        idem_keys={"payment|1|alice@test": "2026-04-22T00:00:00Z"},
        top_level={"verify|1|alice@test": "2026-04-22T00:00:00Z"},
    )
    report, exit_code = run_check(root)
    assert exit_code == 0
    assert report["status"] == "PASS"
    assert report["summary"]["unique_keys_checked"] == 2


def test_json_duplicate_key_in_nested_and_top_level_counted_twice(temp_repo: Path) -> None:
    # GAP-5: When the same key string appears in BOTH the nested 'keys' dict AND as a
    # top-level non-reserved key, load_recorded_idem_keys appends it twice.
    # As a result, observations_checked == 2 while unique_keys_checked == 1.
    # This double-counting is silent and produces no error; it is likely unintentional
    # and should be documented or guarded against at load time.
    _write_json(
        temp_repo / "ledger" / "idem_keys.json",
        {
            "version": 5,
            "keys": {"payment|1|alice@test": "2026-04-22T00:00:00Z"},
            "payment|1|alice@test": "2026-04-22T00:00:01Z",
        },
    )
    keys = load_recorded_idem_keys(temp_repo / "ledger" / "idem_keys.json")
    assert keys.count("payment|1|alice@test") == 2, (
        "Same key appears in both nested dict and top-level → loaded twice (GAP-5)"
    )


def test_json_version_key_not_treated_as_idem_key(temp_repo: Path) -> None:
    """The top-level 'version' key is in RESERVED_TOP_LEVEL_KEYS and must be silently
    skipped; it must not appear in the list of loaded idem keys."""
    root = _make_repo(
        temp_repo,
        idem_keys={"payment|1|alice@test": "2026-04-22T00:00:00Z"},
    )
    keys = load_recorded_idem_keys(root / "ledger" / "idem_keys.json")
    assert "version" not in keys
    assert keys == ["payment|1|alice@test"]


def test_json_corrupt_keys_field_not_dict(temp_repo: Path) -> None:
    """When the 'keys' field is a JSON array instead of an object, load_recorded_idem_keys
    raises ValueError and main() must return exit code 2."""
    _write_json(
        temp_repo / "ledger" / "idem_keys.json",
        {"version": 5, "keys": ["a", "b"]},
    )
    exit_code = main(["--root", str(temp_repo)])
    assert exit_code == 2


# ── Output Contract ───────────────────────────────────────────────────────────


def test_output_contract_exit_0_is_pass_status(temp_repo: Path) -> None:
    """Exit code 0 and JSON status 'PASS' are emitted together when every observed
    namespace is recognized; the two signals must be consistent."""
    root = _make_repo(temp_repo, idem_keys={"payment|1|alice@test": "2026-04-22T00:00:00Z"})
    report, exit_code = run_check(root)
    assert exit_code == 0
    assert report["status"] == "PASS"


def test_output_contract_exit_1_is_fail_status(temp_repo: Path) -> None:
    """Exit code 1 and JSON status 'FAIL' are emitted together when at least one
    namespace is unrecognized; the two signals must be consistent."""
    root = _make_repo(temp_repo, idem_keys={"bogus|1|alice@test": "2026-04-22T00:00:00Z"})
    report, exit_code = run_check(root)
    assert exit_code == 1
    assert report["status"] == "FAIL"


def test_output_contract_json_shape_invariant(temp_repo: Path) -> None:
    """The JSON report must contain all six required top-level keys and all seven required
    summary sub-keys, regardless of whether the result is PASS or FAIL."""
    root = _make_repo(temp_repo, idem_keys={"payment|1|alice@test": "2026-04-22T00:00:00Z"})
    report, _ = run_check(root)

    required_top = {
        "status",
        "summary",
        "used_namespaces",
        "unused_known_namespaces",
        "namespace_counts",
        "unrecognized_namespaces",
    }
    assert required_top <= report.keys(), f"Missing top-level keys: {required_top - report.keys()}"

    required_summary = {
        "observations_checked",
        "unique_keys_checked",
        "namespace_buckets_seen",
        "recognized_namespaces_seen",
        "unused_known_namespaces_count",
        "keys_with_unrecognized_namespaces",
        "unrecognized_namespace_buckets",
    }
    assert required_summary <= report["summary"].keys(), (
        f"Missing summary keys: {required_summary - report['summary'].keys()}"
    )
