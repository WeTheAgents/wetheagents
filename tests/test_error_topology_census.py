"""Tests for scripts/circle1/error_topology_census.py — circle-1 phase 1."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.circle1.error_topology_census import (
    HARNESS_VERSION,
    KIND_NAMES,
    inspect_file,
    main,
    render_markdown,
    scan,
)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_zone(root: Path, zone: str, files: dict[str, str]) -> None:
    zone_dir = root / zone
    zone_dir.mkdir(parents=True, exist_ok=True)
    for relpath, content in files.items():
        target = zone_dir / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


# ── Detection-level tests ────────────────────────────────────────────────────


def test_custom_exception_class_detected(tmp_path):
    _make_zone(
        tmp_path,
        "z",
        {
            "a.py": (
                "class BaseFail(RuntimeError):\n"
                "    '''doc.'''\n"
                "class ChildFail(BaseFail):\n"
                "    pass\n"
            )
        },
    )
    report = scan(tmp_path, zones=["z"])
    classes = [c["name"] for c in report["exception_classes"]]
    assert classes == ["BaseFail", "ChildFail"]
    assert report["inheritance"]["BaseFail"]["subclasses"] == ["ChildFail"]
    assert report["inheritance"]["ChildFail"]["bases"] == ["BaseFail"]


def test_raw_builtin_raise_detected(tmp_path):
    _make_zone(
        tmp_path,
        "z",
        {"a.py": "def f(x):\n    if not x:\n        raise ValueError('bad')\n"},
    )
    report = scan(tmp_path, zones=["z"])
    kinds = [d["kind"] for d in report["files"][0]["detections"]]
    assert "raw_builtin_raise_at_boundary" in kinds


def test_broad_catch_bare_except(tmp_path):
    _make_zone(
        tmp_path,
        "z",
        {
            "a.py": (
                "def f():\n    try:\n        pass\n    except:\n        pass\n"
            )
        },
    )
    report = scan(tmp_path, zones=["z"])
    detections = report["files"][0]["detections"]
    broad = [d for d in detections if d["kind"] == "broad_catch"]
    assert len(broad) == 1
    assert broad[0]["extra"]["sub_reason"] == "bare_except"


def test_broad_catch_exception_and_baseexception(tmp_path):
    _make_zone(
        tmp_path,
        "z",
        {
            "a.py": (
                "def f():\n"
                "    try:\n        pass\n    except Exception:\n        pass\n"
                "    try:\n        pass\n    except BaseException:\n        pass\n"
                "    try:\n        pass\n    except (Exception, KeyError):\n        pass\n"
            )
        },
    )
    report = scan(tmp_path, zones=["z"])
    broad = [
        d for d in report["files"][0]["detections"] if d["kind"] == "broad_catch"
    ]
    assert len(broad) == 3
    symbols = sorted(d["symbol"] for d in broad)
    assert "BaseException" in symbols
    assert symbols.count("Exception") == 2


def test_narrow_except_is_not_broad(tmp_path):
    _make_zone(
        tmp_path,
        "z",
        {
            "a.py": (
                "def f():\n    try:\n        pass\n    except ValueError:\n        pass\n"
            )
        },
    )
    report = scan(tmp_path, zones=["z"])
    detections = report["files"][0]["detections"]
    assert not any(d["kind"] == "broad_catch" for d in detections)


def test_reraise_chain_with_from(tmp_path):
    _make_zone(
        tmp_path,
        "z",
        {
            "a.py": (
                "class GhError(RuntimeError):\n    pass\n\n"
                "def f():\n"
                "    try:\n        x = 1\n"
                "    except ValueError as e:\n"
                "        raise GhError('bad') from e\n"
            )
        },
    )
    report = scan(tmp_path, zones=["z"])
    detections = report["files"][0]["detections"]
    chains = [d for d in detections if d["kind"] == "reraise_chain"]
    assert chains
    assert chains[0]["extra"]["from_clause"] is True
    assert chains[0]["extra"]["inner_types"] == ["ValueError"]
    assert chains[0]["extra"]["outer"] == "GhError"


def test_no_double_count_inside_try_body(tmp_path):
    """Each raise inside a try body or handler must produce exactly one
    `custom_raise` detection, not two from generic-visit recursion."""
    _make_zone(
        tmp_path,
        "z",
        {
            "a.py": (
                "class GhError(RuntimeError):\n    pass\n\n"
                "def f():\n"
                "    try:\n        x = 1\n"
                "    except ValueError as e:\n"
                "        raise GhError('bad') from e\n"
                "    raise GhError('outside-handler')\n"
            )
        },
    )
    report = scan(tmp_path, zones=["z"])
    detections = report["files"][0]["detections"]
    custom = [d for d in detections if d["kind"] == "custom_raise"]
    # exactly two custom_raises: one inside handler (in_handler=True) and one
    # outside (in_handler=False). Three would mean handler is being walked twice.
    assert len(custom) == 2
    in_handler_flags = sorted(d["extra"]["in_handler"] for d in custom)
    assert in_handler_flags == [False, True]


def test_bare_reraise_detected(tmp_path):
    _make_zone(
        tmp_path,
        "z",
        {
            "a.py": (
                "def f():\n"
                "    try:\n        pass\n"
                "    except KeyError:\n        raise\n"
            )
        },
    )
    report = scan(tmp_path, zones=["z"])
    detections = report["files"][0]["detections"]
    bare = [d for d in detections if d["kind"] == "bare_reraise"]
    assert len(bare) == 1


def test_custom_raise_confidence_high_when_local(tmp_path):
    _make_zone(
        tmp_path,
        "z",
        {
            "a.py": (
                "class FooError(RuntimeError):\n    pass\n\n"
                "def f():\n    raise FooError('x')\n"
            )
        },
    )
    report = scan(tmp_path, zones=["z"])
    detections = report["files"][0]["detections"]
    custom = [d for d in detections if d["kind"] == "custom_raise"]
    assert len(custom) == 1
    assert custom[0]["confidence"] == "high"


# ── Score rubric tests (from zero state up) ──────────────────────────────────


def test_score_zero_when_no_custom_classes(tmp_path):
    _make_zone(tmp_path, "z", {"a.py": "x = 1\n"})
    report = scan(tmp_path, zones=["z"])
    assert report["summary"]["by_zone"]["z"]["exception_topology_score"] == 0


def test_score_one_when_classes_have_no_shared_base(tmp_path):
    _make_zone(
        tmp_path,
        "z",
        {
            "a.py": (
                "class AError(RuntimeError):\n    pass\n"
                "class BError(ValueError):\n    pass\n"
                "def f():\n"
                "    raise AError()\n"
                "def g():\n"
                "    raise BError()\n"
            )
        },
    )
    report = scan(tmp_path, zones=["z"])
    assert report["summary"]["by_zone"]["z"]["exception_topology_score"] == 1


def test_score_two_when_zone_has_shared_local_base(tmp_path):
    _make_zone(
        tmp_path,
        "z",
        {
            "a.py": (
                "class WeaCliError(RuntimeError):\n"
                "    '''Base for wea CLI failures.'''\n"
                "class GhError(WeaCliError):\n"
                "    pass\n"
                "class PushError(WeaCliError):\n"
                "    pass\n"
                "def f():\n"
                "    raise GhError('boom')\n"
                "def g():\n"
                "    raise PushError('boom')\n"
            )
        },
    )
    report = scan(tmp_path, zones=["z"])
    score = report["summary"]["by_zone"]["z"]["exception_topology_score"]
    score_inputs = report["summary"]["by_zone"]["z"]["score_inputs"]
    assert score == 2
    assert "WeaCliError" in score_inputs["shared_zone_bases"]


def test_multilevel_hierarchy_with_leaf_raises_scores_two(tmp_path):
    """Codex regression: a base whose only raises happen at leaves of a
    multi-level hierarchy must not be marked as padded. Score should be 2."""
    _make_zone(
        tmp_path,
        "z",
        {
            "a.py": (
                "class BaseError(RuntimeError):\n    pass\n"
                "class MidError(BaseError):\n    pass\n"
                "class LeafA(MidError):\n    pass\n"
                "class LeafB(MidError):\n    pass\n"
                "def f():\n    raise LeafA()\n"
                "def g():\n    raise LeafB()\n"
            )
        },
    )
    report = scan(tmp_path, zones=["z"])
    score_inputs = report["summary"]["by_zone"]["z"]["score_inputs"]
    assert "BaseError" not in score_inputs["padded_hierarchy_bases"]
    assert "MidError" not in score_inputs["padded_hierarchy_bases"]
    assert report["summary"]["by_zone"]["z"]["exception_topology_score"] == 2


def test_padded_hierarchy_does_not_score_two(tmp_path):
    """A shared base whose subclasses are never raised stays at score 1."""
    _make_zone(
        tmp_path,
        "z",
        {
            "a.py": (
                "class Empty(RuntimeError):\n    pass\n"
                "class Sub1(Empty):\n    pass\n"
                "class Sub2(Empty):\n    pass\n"
            )
        },
    )
    report = scan(tmp_path, zones=["z"])
    score_inputs = report["summary"]["by_zone"]["z"]["score_inputs"]
    assert "Empty" in score_inputs["padded_hierarchy_bases"]
    assert report["summary"]["by_zone"]["z"]["exception_topology_score"] == 1


def test_score_never_four_without_enforced_check(tmp_path):
    """Even with documented usage and repo-level shared base, score stays 3 unless
    an enforced_check is supplied."""
    _make_zone(
        tmp_path,
        "z1",
        {
            "a.py": (
                "class WeaCliError(RuntimeError):\n"
                "    '''Documented.'''\n"
                "class A(WeaCliError):\n    pass\n"
                "class B(WeaCliError):\n    pass\n"
                "def f():\n    raise A()\ndef g():\n    raise B()\n"
            )
        },
    )
    _make_zone(
        tmp_path,
        "z2",
        {
            "b.py": (
                "from a import WeaCliError\n"
                "class C(WeaCliError):\n    pass\n"
                "def h():\n    raise C()\n"
            )
        },
    )
    report = scan(tmp_path, zones=["z1", "z2"])
    score_z1 = report["summary"]["by_zone"]["z1"]["exception_topology_score"]
    assert score_z1 == 3

    report_with_check = scan(
        tmp_path, zones=["z1", "z2"], enforced_check="scripts/check_wea_cli_errors.py"
    )
    assert (
        report_with_check["summary"]["by_zone"]["z1"]["exception_topology_score"] == 4
    )


def test_repo_level_base_with_one_subclass_per_zone_scores_three(tmp_path):
    """Codex regression: a documented repo-level common base scores 3 even
    when each zone has only one subclass (no zone-local fan-out)."""
    _make_zone(
        tmp_path,
        "A",
        {
            "a.py": (
                "class BaseError(RuntimeError):\n"
                "    '''Repo-level base.'''\n"
                "class AError(BaseError):\n    pass\n"
                "def f():\n    raise AError()\n"
            )
        },
    )
    _make_zone(
        tmp_path,
        "B",
        {
            "b.py": (
                "from a import BaseError\n"
                "class BError(BaseError):\n    pass\n"
                "def f():\n    raise BError()\n"
            )
        },
    )
    report = scan(tmp_path, zones=["A", "B"])
    a_inputs = report["summary"]["by_zone"]["A"]["score_inputs"]
    b_inputs = report["summary"]["by_zone"]["B"]["score_inputs"]
    assert "BaseError" in a_inputs["repo_documented_bases"]
    assert "BaseError" in b_inputs["repo_documented_bases"]
    assert report["summary"]["by_zone"]["A"]["exception_topology_score"] == 3
    assert report["summary"]["by_zone"]["B"]["exception_topology_score"] == 3


def test_reraise_local_variable_is_not_a_wrap(tmp_path):
    """Codex regression: `raise exc` where `exc` is the bound handler variable
    is direct propagation, not a wrap. It must NOT count as `reraise_chain`."""
    _make_zone(
        tmp_path,
        "z",
        {
            "a.py": (
                "def f():\n"
                "    try:\n        x = 1\n"
                "    except Exception as exc:\n"
                "        raise exc\n"
            )
        },
    )
    report = scan(tmp_path, zones=["z"])
    detections = report["files"][0]["detections"]
    chains = [d for d in detections if d["kind"] == "reraise_chain"]
    assert chains == []


def test_repo_shared_bases_isolated_to_zones_in_hierarchy(tmp_path):
    """Codex regression: a zone whose subclasses do NOT participate in a
    cross-zone hierarchy must not see `repo_shared_bases` populated by an
    unrelated cross-zone hierarchy elsewhere in the scan."""
    # zone A: one local hierarchy with a documented base, no cross-zone reach
    _make_zone(
        tmp_path,
        "A",
        {
            "a.py": (
                "class ABase(RuntimeError):\n    '''A-zone base.'''\n"
                "class A1(ABase):\n    pass\n"
                "class A2(ABase):\n    pass\n"
                "def f():\n    raise A1()\n"
                "def g():\n    raise A2()\n"
            )
        },
    )
    # zones B and C share a separate base. Zone A is unrelated.
    _make_zone(
        tmp_path,
        "B",
        {
            "b.py": (
                "class RBase(RuntimeError):\n    '''shared base.'''\n"
                "class B1(RBase):\n    pass\n"
                "def f():\n    raise B1()\n"
            )
        },
    )
    _make_zone(
        tmp_path,
        "C",
        {
            "c.py": (
                "from b import RBase\n"
                "class C1(RBase):\n    pass\n"
                "def f():\n    raise C1()\n"
            )
        },
    )
    report = scan(tmp_path, zones=["A", "B", "C"])
    a_inputs = report["summary"]["by_zone"]["A"]["score_inputs"]
    # Zone A must NOT have RBase in its repo_shared_bases — RBase is not in
    # zone A's hierarchy.
    assert "RBase" not in a_inputs["repo_shared_bases"]
    # Zone A scores 2 (local shared base, no cross-zone reach), not 3.
    assert report["summary"]["by_zone"]["A"]["exception_topology_score"] == 2


def test_repo_score_is_minimum_over_zones(tmp_path):
    _make_zone(
        tmp_path,
        "warm",
        {"a.py": "def f():\n    raise ValueError('x')\n"},
    )
    _make_zone(
        tmp_path,
        "cold",
        {
            "a.py": (
                "class B(RuntimeError):\n    '''base.'''\n"
                "class C(B):\n    pass\n"
                "class D(B):\n    pass\n"
                "def f():\n    raise C()\n"
                "def g():\n    raise D()\n"
            )
        },
    )
    report = scan(tmp_path, zones=["warm", "cold"])
    per_zone = report["summary"]["exception_topology_score"]["per_zone"]
    assert per_zone["warm"] == 0
    assert per_zone["cold"] == 2
    assert report["summary"]["exception_topology_score"]["repo"] == 0


# ── Stability / determinism ──────────────────────────────────────────────────


def test_output_is_deterministic_across_runs(tmp_path):
    _make_zone(
        tmp_path,
        "z",
        {
            "a.py": (
                "class GhError(RuntimeError):\n    pass\n\n"
                "def f():\n    raise GhError('x')\n"
            ),
            "sub/b.py": "def g():\n    raise ValueError('x')\n",
        },
    )
    r1 = scan(tmp_path, zones=["z"], scan_date="2026-05-05")
    r2 = scan(tmp_path, zones=["z"], scan_date="2026-05-05")
    assert json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True)


def test_files_sorted_by_path(tmp_path):
    _make_zone(
        tmp_path,
        "z",
        {
            "z_last.py": "x = 1\n",
            "a_first.py": "x = 1\n",
            "m_middle.py": "x = 1\n",
        },
    )
    report = scan(tmp_path, zones=["z"])
    paths = [e["path"] for e in report["files"]]
    assert paths == sorted(paths)


# ── Skip / scope handling ────────────────────────────────────────────────────


def test_init_files_skipped_by_default(tmp_path):
    _make_zone(
        tmp_path,
        "z",
        {
            "__init__.py": "",
            "a.py": "x = 1\n",
        },
    )
    report = scan(tmp_path, zones=["z"])
    skipped_paths = [s["path"] for s in report["skipped_files"]]
    assert any(p.endswith("__init__.py") for p in skipped_paths)
    assert not any(e["path"].endswith("__init__.py") for e in report["files"])


def test_include_init_overrides_default(tmp_path):
    _make_zone(tmp_path, "z", {"__init__.py": "x = 1\n"})
    report = scan(tmp_path, zones=["z"], include_init=True)
    paths = [e["path"] for e in report["files"]]
    assert any(p.endswith("__init__.py") for p in paths)


def test_unused_exclude_is_reported(tmp_path):
    _make_zone(tmp_path, "z", {"a.py": "x = 1\n"})
    report = scan(tmp_path, zones=["z"], extra_excludes=["**/never_matches.py"])
    assert "**/never_matches.py" in report["scope"]["unused_extra_excludes"]


def test_used_exclude_reports_skipped_path(tmp_path):
    _make_zone(tmp_path, "z", {"a.py": "x = 1\n", "b.py": "y = 2\n"})
    report = scan(tmp_path, zones=["z"], extra_excludes=["z/b.py"])
    skipped = [s["path"] for s in report["skipped_files"]]
    assert "z/b.py" in skipped
    assert not report["scope"]["unused_extra_excludes"]


def test_alias_with_exception_suffix_resolves_to_canonical(tmp_path):
    """Codex regression: `from pkg import FooError as BarError; raise BarError()`
    must record the canonical symbol `FooError`, not the local alias `BarError`,
    so subclass-usage matching works in score logic."""
    _make_zone(
        tmp_path,
        "z",
        {
            "a.py": (
                "from pkg import FooError as BarError\n"
                "def f():\n    raise BarError()\n"
            )
        },
    )
    report = scan(tmp_path, zones=["z"])
    detections = report["files"][0]["detections"]
    custom = [d for d in detections if d["kind"] == "custom_raise"]
    assert len(custom) == 1
    assert custom[0]["symbol"] == "FooError"
    assert custom[0]["extra"]["alias_local_name"] == "BarError"


def test_handler_bound_variable_raise_is_propagation_not_wrap(tmp_path):
    """Codex regression: `except Exception as TaskError: raise TaskError` is
    direct propagation, not a class wrap. It must not be classified as
    custom_raise or reraise_chain even though `TaskError` ends in `Error`."""
    _make_zone(
        tmp_path,
        "z",
        {
            "a.py": (
                "def f():\n"
                "    try:\n        x = 1\n"
                "    except Exception as TaskError:\n"
                "        raise TaskError\n"
            )
        },
    )
    report = scan(tmp_path, zones=["z"])
    detections = report["files"][0]["detections"]
    custom = [d for d in detections if d["kind"] == "custom_raise"]
    chains = [d for d in detections if d["kind"] == "reraise_chain"]
    bare = [d for d in detections if d["kind"] == "bare_reraise"]
    assert custom == []
    assert chains == []
    assert len(bare) == 1
    assert bare[0]["extra"]["bound_name"] == "TaskError"


def test_alias_introduced_in_try_body_is_resolved(tmp_path):
    """Codex regression: when `from pkg import FooError as E` lives inside a
    try body and the matching except handler raises `E()`, pre-collected
    imports must let the resolver find FooError."""
    _make_zone(
        tmp_path,
        "z",
        {
            "a.py": (
                "def f():\n"
                "    try:\n"
                "        from pkg import FooError as E\n"
                "        x = 1\n"
                "    except Exception:\n"
                "        raise E('boom')\n"
            )
        },
    )
    report = scan(tmp_path, zones=["z"])
    detections = report["files"][0]["detections"]
    custom = [d for d in detections if d["kind"] == "custom_raise"]
    assert len(custom) == 1
    assert custom[0]["symbol"] == "FooError"


def test_zone_label_normalized_in_summary(tmp_path):
    """Codex regression: --zones ./src and --zones src/ must produce the
    same summary keys as --zones src — no duplicate empty zones."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("def f(): pass\n", encoding="utf-8")
    r1 = scan(tmp_path, zones=["src"])
    r2 = scan(tmp_path, zones=["./src"])
    r3 = scan(tmp_path, zones=["src/"])
    keys = lambda r: sorted(r["summary"]["by_zone"].keys())
    assert keys(r1) == keys(r2) == keys(r3) == ["src"]


def test_flow_control_raise_is_detected_at_low_confidence(tmp_path):
    """Codex regression: explicit `raise StopIteration()` / KeyboardInterrupt
    must appear in the detections (low confidence), not be invisible."""
    _make_zone(
        tmp_path,
        "z",
        {
            "a.py": (
                "def f():\n    raise StopIteration()\n"
                "def g():\n    raise KeyboardInterrupt()\n"
            )
        },
    )
    report = scan(tmp_path, zones=["z"])
    detections = report["files"][0]["detections"]
    raised = sorted(d["symbol"] for d in detections if d["kind"] == "raw_builtin_raise_at_boundary")
    assert "StopIteration" in raised
    assert "KeyboardInterrupt" in raised
    flow = [d for d in detections if d.get("extra", {}).get("flow_control")]
    assert len(flow) == 2
    assert all(d["confidence"] == "low" for d in flow)


def test_dot_zone_scans_whole_root(tmp_path):
    """Codex regression: --zones . must scan every Python file under root,
    not produce an empty zone with everything in 'other'."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("def f():\n    pass\n", encoding="utf-8")
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "b.py").write_text("def g():\n    pass\n", encoding="utf-8")
    report = scan(tmp_path, zones=["."])
    paths = sorted(e["path"] for e in report["files"])
    assert paths == ["src/a.py", "tools/b.py"]
    # Both files should land under the requested "." zone, not "other".
    zones_seen = {e["zone"] for e in report["files"]}
    assert zones_seen == {"."}


def test_dot_prefixed_zone_resolves(tmp_path):
    _make_zone(tmp_path, "src", {"a.py": "def f(): pass\n"})
    report = scan(tmp_path, zones=["./src"])
    paths = [e["path"] for e in report["files"]]
    assert paths == ["src/a.py"]
    # zone label should normalize to src
    assert report["files"][0]["zone"] == "src"


def test_missing_zone_directory_appears_in_skipped(tmp_path):
    report = scan(tmp_path, zones=["does_not_exist"])
    assert any(
        "zone directory not found" in s["reason"] for s in report["skipped_files"]
    )


def test_parse_error_recorded(tmp_path):
    _make_zone(tmp_path, "z", {"a.py": "def f(\n  unbalanced\n"})
    report = scan(tmp_path, zones=["z"])
    assert report["summary"]["parse_errors"] == 1
    bad = [e for e in report["files"] if e["status"] == "parse_error"]
    assert bad


# ── File flags ───────────────────────────────────────────────────────────────


def test_cli_failure_surface_flag(tmp_path):
    _make_zone(
        tmp_path,
        "z",
        {
            "tool.py": (
                "import argparse\n"
                "def main():\n"
                "    parser = argparse.ArgumentParser()\n"
                "    raise ValueError('boom')\n"
            )
        },
    )
    report = scan(tmp_path, zones=["z"])
    entry = report["files"][0]
    assert entry["file_flags"]["cli_failure_surface"] is True


def test_github_failure_surface_flag_for_dotted_import(tmp_path):
    """Codex regression: `import wea_cli.gh as gh` must trigger
    github_failure_surface, not just `from wea_cli.gh import ...`."""
    _make_zone(
        tmp_path,
        "z",
        {
            "delegate.py": (
                "import wea_cli.gh as gh\n"
                "def fetch():\n    return gh.run_gh_json(['issue', 'view', '1'])\n"
            )
        },
    )
    report = scan(tmp_path, zones=["z"])
    entry = report["files"][0]
    assert entry["file_flags"]["github_failure_surface"] is True


def test_nested_function_in_except_does_not_inherit_handler(tmp_path):
    """Codex regression: a nested function/closure declared in an except
    handler must not be classified as in-handler when it raises."""
    _make_zone(
        tmp_path,
        "z",
        {
            "a.py": (
                "def outer():\n"
                "    try:\n        x = 1\n"
                "    except ValueError:\n"
                "        def helper():\n"
                "            raise RuntimeError('not part of the wrap')\n"
                "        helper()\n"
            )
        },
    )
    report = scan(tmp_path, zones=["z"])
    detections = report["files"][0]["detections"]
    chains = [d for d in detections if d["kind"] == "reraise_chain"]
    # The raise is inside `helper()` which executes outside the handler stack.
    assert chains == []
    raises = [d for d in detections if d["kind"] == "raw_builtin_raise_at_boundary"]
    assert len(raises) == 1
    assert raises[0]["extra"]["in_handler"] is False


def test_method_in_class_in_except_does_not_inherit_handler(tmp_path):
    _make_zone(
        tmp_path,
        "z",
        {
            "a.py": (
                "def outer():\n"
                "    try:\n        x = 1\n"
                "    except ValueError:\n"
                "        class Helper:\n"
                "            def m(self):\n"
                "                raise RuntimeError('not part of wrap')\n"
            )
        },
    )
    report = scan(tmp_path, zones=["z"])
    detections = report["files"][0]["detections"]
    chains = [d for d in detections if d["kind"] == "reraise_chain"]
    assert chains == []


def test_github_failure_surface_flag_for_delegated_caller(tmp_path):
    """Codex regression: a file that imports wea_cli.gh helpers and lets
    GhError propagate is a github failure surface even without a local raise."""
    _make_zone(
        tmp_path,
        "z",
        {
            "delegate.py": (
                "from wea_cli.gh import run_gh_json\n"
                "def fetch():\n"
                "    return run_gh_json(['issue', 'view', '1'])\n"
            )
        },
    )
    report = scan(tmp_path, zones=["z"])
    entry = report["files"][0]
    assert entry["file_flags"]["github_failure_surface"] is True


def test_imported_alias_raise_is_classified(tmp_path):
    """Codex regression: `from pkg import FooError as E; raise E()` must be
    detected as a custom_raise via the import alias map. The recorded
    `symbol` must be the canonical resolved class name `FooError` so the
    score logic can match it against declared subclasses."""
    _make_zone(
        tmp_path,
        "z",
        {
            "a.py": (
                "from pkg import FooError as E\n"
                "def f():\n    raise E()\n"
            )
        },
    )
    report = scan(tmp_path, zones=["z"])
    detections = report["files"][0]["detections"]
    custom = [d for d in detections if d["kind"] == "custom_raise"]
    assert len(custom) == 1
    assert custom[0]["confidence"] == "medium"
    assert custom[0]["symbol"] == "FooError"
    assert custom[0]["extra"]["alias_local_name"] == "E"


def test_repo_documented_base_requires_zone_local_usage(tmp_path):
    """Codex regression: a documented repo-level base only scores 3 in zones
    that observe an active failure path locally. Zone B that declares an
    unused subclass must NOT score 3 just because zone A raises its sibling."""
    _make_zone(
        tmp_path,
        "A",
        {
            "a.py": (
                "class BaseError(RuntimeError):\n"
                "    '''doc'''\n"
                "class AError(BaseError):\n    pass\n"
                "def f():\n    raise AError()\n"
            )
        },
    )
    _make_zone(
        tmp_path,
        "B",
        {
            "b.py": (
                "from a import BaseError\n"
                "class BError(BaseError):\n    pass\n"
                # NO raise of BError or BaseError in zone B.
            )
        },
    )
    report = scan(tmp_path, zones=["A", "B"])
    a_score = report["summary"]["by_zone"]["A"]["exception_topology_score"]
    b_score = report["summary"]["by_zone"]["B"]["exception_topology_score"]
    assert a_score == 3, f"zone A should score 3 (raises AError); got {a_score}"
    assert b_score < 3, f"zone B has no local usage; got {b_score}"


def test_github_failure_surface_flag(tmp_path):
    _make_zone(
        tmp_path,
        "z",
        {
            "tool.py": (
                "import subprocess\n"
                "def main():\n"
                "    subprocess.run(['gh', 'api', 'x'], check=True)\n"
                "    raise ValueError('boom')\n"
            )
        },
    )
    report = scan(tmp_path, zones=["z"])
    entry = report["files"][0]
    assert entry["file_flags"]["github_failure_surface"] is True


# ── Markdown / kinds catalog ─────────────────────────────────────────────────


def test_markdown_renders_score_and_kinds(tmp_path):
    _make_zone(tmp_path, "z", {"a.py": "def f():\n    raise ValueError()\n"})
    report = scan(tmp_path, zones=["z"], scan_date="2026-05-05")
    md = render_markdown(report, max_hot_files=5)
    assert "Error Topology Census" in md
    assert "Topology Score" in md
    for kind in KIND_NAMES:
        assert kind in md
    # Per-zone score lines look like "- z: <int>" under the topology header.
    assert "- z: " in md


def test_harness_version_present(tmp_path):
    _make_zone(tmp_path, "z", {"a.py": "x = 1\n"})
    report = scan(tmp_path, zones=["z"])
    assert report["harness_version"] == HARNESS_VERSION


# ── CLI black-box tests ──────────────────────────────────────────────────────


def test_main_writes_json_output(tmp_path):
    _make_zone(tmp_path, "z", {"a.py": "x = 1\n"})
    output = tmp_path / "report.json"
    rc = main(
        [
            "--root",
            str(tmp_path),
            "--zones",
            "z",
            "--output",
            str(output),
            "--scan-date",
            "2026-05-05",
        ]
    )
    assert rc == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["scan_date"] == "2026-05-05"
    assert payload["scope"]["zones"] == ["z"]


def test_zone_escaping_root_is_rejected(tmp_path):
    """Codex regression: --zones .. or an absolute path outside the root must
    be rejected. The census is repo-relative; an escaping zone would crash on
    relative_to() and silently scan unintended files."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("def f(): pass\n", encoding="utf-8")
    report = scan(tmp_path, zones=[".."])
    skipped = [s["path"] for s in report["skipped_files"]]
    assert ".." in skipped
    reasons = [s["reason"] for s in report["skipped_files"] if s["path"] == ".."]
    assert any("outside the root" in r for r in reasons)


def test_main_rejects_zone_escaping_root(tmp_path, capsys):
    rc = main(["--root", str(tmp_path), "--zones", ".."])
    assert rc == 1
    err = capsys.readouterr().err
    assert "must be repo-relative" in err


def test_main_fails_when_zone_missing(tmp_path, capsys):
    rc = main(["--root", str(tmp_path), "--zones", "missing_zone"])
    assert rc == 1
    captured = capsys.readouterr()
    assert "zone directories not found" in captured.err


def test_subprocess_invocation_against_real_repo(tmp_path):
    """Runs the harness as a subprocess against this very repository so we cover
    the CLI parsing, exit code, and JSON envelope as a black box."""
    repo_root = Path(__file__).resolve().parent.parent
    output = tmp_path / "report.json"
    proc = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "circle1" / "error_topology_census.py"),
            "--root",
            str(repo_root),
            "--output",
            str(output),
            "--scan-date",
            "2026-05-05",
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["harness_version"] == HARNESS_VERSION
    assert "src/wea_cli" in payload["summary"]["by_zone"]
    assert "scripts" in payload["summary"]["by_zone"]
    assert payload["summary"]["total_files"] > 0
