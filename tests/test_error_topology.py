"""Tests for scripts/circle1/error_topology.py and the WeaCliError pilot.

The scanner tests use a synthetic temp tree so that the assertions stay stable
regardless of how the real repo evolves. A small smoke test against the live
repo verifies that the scanner runs end-to-end and that the pilot retrofit is
visible (PushError, GhError, IssueEditError all inherit WeaCliError).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.circle1.error_topology import (  # noqa: E402
    TOOL_VERSION,
    _shared_base_score,
    run_scan,
    scan_file,
    scan_zone,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def _make_tree(root: Path) -> None:
    # src/wea_cli/ — three custom classes sharing a WeaCliError base
    _write(
        root / "src" / "wea_cli" / "errors.py",
        '"""errors module."""\n'
        "from __future__ import annotations\n"
        "class WeaCliError(RuntimeError):\n"
        "    pass\n",
    )
    _write(
        root / "src" / "wea_cli" / "gh.py",
        '"""gh."""\n'
        "from __future__ import annotations\n"
        "from wea_cli.errors import WeaCliError\n"
        "class GhError(WeaCliError):\n"
        "    pass\n"
        "def run():\n"
        "    try:\n"
        "        x = 1\n"
        "    except Exception as exc:\n"
        "        raise GhError('boom') from exc\n",
    )
    _write(
        root / "src" / "wea_cli" / "cli.py",
        '"""cli."""\n'
        "from __future__ import annotations\n"
        "from wea_cli.errors import WeaCliError\n"
        "class PushError(WeaCliError):\n"
        "    pass\n"
        "def cmd_push():\n"
        "    raise PushError('no')\n"
        "def helper():\n"
        "    raise ValueError('bad input')\n"
        "def main():\n"
        "    try:\n"
        "        cmd_push()\n"
        "    except Exception:\n"
        "        pass\n",
    )
    # scripts/ — scattered custom errors with no shared base
    _write(
        root / "scripts" / "alpha.py",
        '"""alpha."""\n'
        "from __future__ import annotations\n"
        "class AlphaError(RuntimeError):\n"
        "    pass\n"
        "def main():\n"
        "    try:\n"
        "        x = 1\n"
        "    except Exception:\n"
        "        raise AlphaError('x')\n"
        'if __name__ == "__main__":\n'
        "    main()\n",
    )
    _write(
        root / "scripts" / "beta.py",
        '"""beta."""\n'
        "from __future__ import annotations\n"
        "class BetaError(RuntimeError):\n"
        "    pass\n"
        "def main():\n"
        "    try:\n"
        "        x = 1\n"
        "    except KeyError:\n"
        "        raise\n"
        "    raise FileNotFoundError('nope')\n"
        'if __name__ == "__main__":\n'
        "    main()\n",
    )
    # tests/ — informational
    _write(
        root / "tests" / "test_x.py",
        '"""tests."""\n'
        "from __future__ import annotations\n"
        "def test_y():\n"
        "    try:\n"
        "        x = 1\n"
        "    except Exception:\n"
        "        pass\n",
    )


# ── Synthetic-tree scanner tests ─────────────────────────────────────────────


def test_scan_picks_up_custom_classes(tmp_path: Path) -> None:
    _make_tree(tmp_path)
    report = run_scan(tmp_path, scan_date="2026-05-05", repo_sha="test")

    src = report["summary"]["zones"]["src_wea_cli"]
    assert src["custom_class_count"] == 3  # WeaCliError, GhError, PushError
    # score 2: WeaCliError used as base by GhError + PushError (>=2 in zone)
    assert src["shared_base_zone_score"] == 2

    scripts = report["summary"]["zones"]["scripts"]
    assert scripts["custom_class_count"] == 2  # AlphaError, BetaError
    assert scripts["shared_base_zone_score"] == 1  # no shared custom base


def test_repo_hint_is_minimum_of_scored_zones(tmp_path: Path) -> None:
    _make_tree(tmp_path)
    report = run_scan(tmp_path, scan_date="2026-05-05")
    # min(src_wea_cli=2, scripts=1) = 1; tests excluded; tests has 0 classes anyway
    assert report["summary"]["repo"]["repo_exception_topology_hint"] == 1


def test_raise_classification(tmp_path: Path) -> None:
    _make_tree(tmp_path)
    report = run_scan(tmp_path, scan_date="2026-05-05")
    src = report["summary"]["zones"]["src_wea_cli"]
    # ValueError raise in helper() — raw built-in
    assert src["raw_builtin_raise_count"] >= 1
    # GhError raised inside `except Exception:` (wrap)
    assert src["wrap_raise_count"] >= 1


def test_catch_classification_swallow_and_broad(tmp_path: Path) -> None:
    _make_tree(tmp_path)
    report = run_scan(tmp_path, scan_date="2026-05-05")
    src = report["summary"]["zones"]["src_wea_cli"]
    # main() in cli.py has `except Exception: pass` — broad + swallow
    assert src["broad_catch_count"] >= 1
    assert src["swallowed_catch_count"] >= 1
    # no bare `except:` in synthetic tree
    assert src["bare_catch_count"] == 0


def test_boundary_function_flagging(tmp_path: Path) -> None:
    _make_tree(tmp_path)
    report = run_scan(tmp_path, scan_date="2026-05-05")
    # cmd_push and helper and main raise from src_wea_cli; cmd_ + main count
    src = report["summary"]["zones"]["src_wea_cli"]
    assert src["boundary_raise_count"] >= 1


def test_findings_sorted_for_stable_diff(tmp_path: Path) -> None:
    _make_tree(tmp_path)
    r1 = run_scan(tmp_path, scan_date="2026-05-05", repo_sha="x")
    r2 = run_scan(tmp_path, scan_date="2026-05-05", repo_sha="x")
    # Two runs over the same tree must produce byte-identical JSON.
    assert json.dumps(r1, indent=2) == json.dumps(r2, indent=2)


def test_parse_errors_recorded(tmp_path: Path) -> None:
    _write(tmp_path / "src" / "wea_cli" / "broken.py", "def oops(:\n    pass\n")
    _write(tmp_path / "src" / "wea_cli" / "ok.py", '"""ok."""\nfrom __future__ import annotations\n')
    report = run_scan(tmp_path, scan_date="2026-05-05")
    assert any("broken.py" in pe["path"] for pe in report["parse_errors"])


def test_excluded_paths_documented(tmp_path: Path) -> None:
    _make_tree(tmp_path)
    report = run_scan(tmp_path, scan_date="2026-05-05")
    assert report["excluded_paths"], "scanner must always declare excluded zones"
    for entry in report["excluded_paths"]:
        assert "path" in entry and "reason" in entry


def test_scanner_does_not_assign_score_above_2(tmp_path: Path) -> None:
    # Even a perfectly hierarchical zone caps mechanical score at 2.
    _write(
        tmp_path / "src" / "wea_cli" / "errors.py",
        "from __future__ import annotations\n"
        "class Base(RuntimeError):\n    pass\n"
        "class A(Base):\n    pass\n"
        "class B(Base):\n    pass\n"
        "class C(B):\n    pass\n",
    )
    report = run_scan(tmp_path, scan_date="2026-05-05")
    assert report["summary"]["zones"]["src_wea_cli"]["shared_base_zone_score"] == 2


def test_external_base_does_not_count_as_zone_shared_base(tmp_path: Path) -> None:
    # If two classes inherit from a name that is NOT defined in the scanned set,
    # we must not credit the zone with score 2.
    _write(
        tmp_path / "src" / "wea_cli" / "a.py",
        "from __future__ import annotations\n"
        "from external_pkg import ExternalError\n"
        "class AlphaError(ExternalError):\n    pass\n",
    )
    _write(
        tmp_path / "src" / "wea_cli" / "b.py",
        "from __future__ import annotations\n"
        "from external_pkg import ExternalError\n"
        "class BetaError(ExternalError):\n    pass\n",
    )
    report = run_scan(tmp_path, scan_date="2026-05-05")
    src = report["summary"]["zones"]["src_wea_cli"]
    # Both classes look like exceptions by name suffix but the base is external.
    assert src["custom_class_count"] == 2
    assert src["shared_base_zone_score"] == 1


def test_zone_filter(tmp_path: Path) -> None:
    _make_tree(tmp_path)
    report = run_scan(tmp_path, scan_date="2026-05-05", selected_zones=["src_wea_cli"])
    assert set(report["summary"]["zones"].keys()) == {"src_wea_cli"}


def test_unknown_zone_in_cli_errors(tmp_path: Path) -> None:
    _make_tree(tmp_path)
    cmd = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "circle1" / "error_topology.py"),
        "--root",
        str(tmp_path),
        "--zones",
        "no_such_zone",
        "--scan-date",
        "2026-05-05",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    assert proc.returncode == 1
    assert "unknown zones" in proc.stderr


def test_tool_version_present(tmp_path: Path) -> None:
    _make_tree(tmp_path)
    report = run_scan(tmp_path, scan_date="2026-05-05")
    assert report["tool_version"] == TOOL_VERSION


def test_shared_base_score_helper() -> None:
    # Empty
    assert _shared_base_score([]) == 0


def test_tuple_with_exception_counts_as_broad(tmp_path: Path) -> None:
    """Codex review (P2): a tuple handler containing Exception or
    BaseException must be classified as broad, not as `narrow_tuple`."""
    _write(
        tmp_path / "src" / "wea_cli" / "x.py",
        '"""x."""\n'
        "from __future__ import annotations\n"
        "def f():\n"
        "    try:\n"
        "        pass\n"
        "    except (Exception, ValueError):\n"
        "        pass\n"
        "    try:\n"
        "        pass\n"
        "    except (BaseException, KeyError):\n"
        "        pass\n"
        "    try:\n"
        "        pass\n"
        "    except (KeyError, ValueError):\n"
        "        pass\n",
    )
    report = run_scan(tmp_path, scan_date="2026-05-05")
    src = report["summary"]["zones"]["src_wea_cli"]
    # Two of three handlers are broad (Exception + BaseException).
    assert src["broad_catch_count"] == 2


def test_unscanned_python_dirs_are_surfaced(tmp_path: Path) -> None:
    """Codex review (P2): a top-level Python dir not in scope and not in
    EXCLUDED_PATHS must show up in `unscanned_python_dirs` so reviewers can
    see drift between checkpoints."""
    _make_tree(tmp_path)
    # An invented top-level Python directory the scanner did not declare.
    _write(tmp_path / "extras" / "thing.py", "x = 1\n")
    report = run_scan(tmp_path, scan_date="2026-05-05")
    found = {entry["path"] for entry in report["unscanned_python_dirs"]}
    assert "extras/" in found


def test_argparse_module_marks_all_raises_as_boundary(tmp_path: Path) -> None:
    """Codex review (P2): a script that constructs ArgumentParser is a CLI
    surface, so raises in its helper functions should be boundary raises,
    not invisible."""
    _write(
        tmp_path / "scripts" / "tool.py",
        "from __future__ import annotations\n"
        "import argparse\n"
        "def parse_iso(value):\n"
        "    raise ValueError(f'bad: {value}')\n"
        "def main():\n"
        "    parser = argparse.ArgumentParser()\n"
        "    parser.parse_args()\n"
        "    parse_iso('x')\n"
        'if __name__ == "__main__":\n'
        "    main()\n",
    )
    report = run_scan(tmp_path, scan_date="2026-05-05")
    scripts = report["summary"]["zones"]["scripts"]
    # Both raises (ValueError in helper, plus none in main) count as boundary
    # because the file constructs ArgumentParser at module scope.
    assert scripts["boundary_raise_count"] >= 1


def test_cross_zone_shared_base_lifts_score(tmp_path: Path) -> None:
    """Codex review (P2): two classes in `scripts/` extending WeaCliError
    defined in `src/wea_cli/errors.py` must lift the scripts zone score
    to 2, because cross-zone inheritance is supposed to count."""
    _write(
        tmp_path / "src" / "wea_cli" / "errors.py",
        "from __future__ import annotations\n"
        "class WeaCliError(RuntimeError):\n"
        "    pass\n",
    )
    _write(
        tmp_path / "scripts" / "alpha.py",
        "from __future__ import annotations\n"
        "from wea_cli.errors import WeaCliError\n"
        "class AlphaError(WeaCliError):\n"
        "    pass\n",
    )
    _write(
        tmp_path / "scripts" / "beta.py",
        "from __future__ import annotations\n"
        "from wea_cli.errors import WeaCliError\n"
        "class BetaError(WeaCliError):\n"
        "    pass\n",
    )
    report = run_scan(tmp_path, scan_date="2026-05-05")
    assert report["summary"]["zones"]["scripts"]["shared_base_zone_score"] == 2


def test_cross_file_transitive_inheritance_chain(tmp_path: Path) -> None:
    """Codex review (P2): a chain Base -> Mid -> Leaf across three files
    must be fully recognized regardless of scan order. The first pre-pass
    iterates to fixpoint precisely for this case."""
    _write(
        tmp_path / "src" / "wea_cli" / "leaf.py",
        "from __future__ import annotations\n"
        "from wea_cli.mid import MidError\n"
        "class LeafError(MidError):\n"
        "    pass\n",
    )
    _write(
        tmp_path / "src" / "wea_cli" / "mid.py",
        "from __future__ import annotations\n"
        "from wea_cli.base import BaseError\n"
        "class MidError(BaseError):\n"
        "    pass\n",
    )
    _write(
        tmp_path / "src" / "wea_cli" / "base.py",
        "from __future__ import annotations\n"
        "class BaseError(RuntimeError):\n"
        "    pass\n",
    )
    report = run_scan(tmp_path, scan_date="2026-05-05")
    src = report["summary"]["zones"]["src_wea_cli"]
    assert src["custom_class_count"] == 3
    # >=2 leaves transitively share BaseError as ancestor -> score 2.
    assert src["shared_base_zone_score"] == 2


def test_multistatement_handler_ending_in_return_is_swallow(tmp_path: Path) -> None:
    """Codex review (P2): a handler that prints/logs/assigns before
    returning must still be classified as swallow."""
    _write(
        tmp_path / "src" / "wea_cli" / "x.py",
        "from __future__ import annotations\n"
        "def f():\n"
        "    try:\n"
        "        pass\n"
        "    except ValueError as exc:\n"
        "        print(f'oops {exc}')\n"
        "        return None\n"
        "def g():\n"
        "    try:\n"
        "        pass\n"
        "    except OSError:\n"
        "        msg = 'failed'\n"
        "        return msg\n",
    )
    report = run_scan(tmp_path, scan_date="2026-05-05")
    assert report["summary"]["zones"]["src_wea_cli"]["swallowed_catch_count"] == 2


def test_handler_with_nested_try_does_not_pollute_outer_disposition(tmp_path: Path) -> None:
    """A `raise` inside a nested except handler must NOT be attributed to
    the outer handler. The outer handler with no own raise + terminal
    return is a swallow."""
    _write(
        tmp_path / "src" / "wea_cli" / "x.py",
        "from __future__ import annotations\n"
        "def f():\n"
        "    try:\n"
        "        pass\n"
        "    except ValueError:\n"
        "        try:\n"
        "            pass\n"
        "        except KeyError:\n"
        "            raise RuntimeError('inner')\n"
        "        return None\n",
    )
    report = run_scan(tmp_path, scan_date="2026-05-05")
    src = report["summary"]["zones"]["src_wea_cli"]
    # Inner handler raises (transform); outer handler is swallow because its
    # only direct flow is `return None` and the inner raise is in a
    # different handler's scope.
    assert src["swallowed_catch_count"] == 1


def test_return_variants_in_handler_are_swallow(tmp_path: Path) -> None:
    """Codex review (P2): bare `return`, `return None`, and `return <value>`
    inside an except body all suppress the caught exception and so all count
    as `swallow`."""
    _write(
        tmp_path / "src" / "wea_cli" / "x.py",
        "from __future__ import annotations\n"
        "def f():\n"
        "    try:\n"
        "        pass\n"
        "    except ValueError:\n"
        "        return None\n"
        "def g():\n"
        "    try:\n"
        "        pass\n"
        "    except ValueError:\n"
        "        return\n"
        "def h():\n"
        "    try:\n"
        "        pass\n"
        "    except OSError:\n"
        "        return False\n",
    )
    report = run_scan(tmp_path, scan_date="2026-05-05")
    src = report["summary"]["zones"]["src_wea_cli"]
    assert src["swallowed_catch_count"] == 3


def test_argparse_import_alone_does_not_mark_module_as_cli(tmp_path: Path) -> None:
    """Just importing argparse for a type hint must not flip a library
    module into 'CLI module'."""
    _write(
        tmp_path / "scripts" / "lib.py",
        "from __future__ import annotations\n"
        "import argparse\n"
        "def helper(ns: argparse.Namespace):\n"
        "    raise ValueError('nope')\n",
    )
    report = run_scan(tmp_path, scan_date="2026-05-05")
    scripts = report["summary"]["zones"]["scripts"]
    # `helper` is not a boundary function name, and the module never
    # constructs ArgumentParser, so the raise is NOT boundary.
    assert scripts["boundary_raise_count"] == 0


def test_known_excluded_dirs_do_not_show_in_unscanned(tmp_path: Path) -> None:
    _make_tree(tmp_path)
    # A directory listed in EXCLUDED_PATHS should NOT also appear as unscanned.
    _write(tmp_path / "domains" / "x.py", "x = 1\n")
    report = run_scan(tmp_path, scan_date="2026-05-05")
    found = {entry["path"] for entry in report["unscanned_python_dirs"]}
    assert "domains/" not in found


# ── Live-repo smoke (sanity, not an assertion on raw numbers) ────────────────


def test_live_repo_smoke_pilot_visible() -> None:
    """The pilot retrofit must be visible: src/wea_cli has a WeaCliError class
    that GhError and IssueEditError inherit from. PushError stays under
    RuntimeError in this PR (named in the pilot doc as a future hardening
    candidate, deferred because cli.py is invoked as a script in some tests
    and that path does not have src/ on sys.path)."""
    report = run_scan(
        REPO_ROOT,
        scan_date="2026-05-05",
        repo_sha="smoke",
        selected_zones=["src_wea_cli"],
    )
    classes = [
        f for f in report["findings"]
        if f["kind"] == "class" and f["zone"] == "src_wea_cli"
    ]
    names = {c["name"] for c in classes}
    assert {"WeaCliError", "GhError", "IssueEditError"} <= names

    by_name = {c["name"]: c for c in classes}
    assert "WeaCliError" in by_name["GhError"]["bases"]
    assert "WeaCliError" in by_name["IssueEditError"]["bases"]

    # >=2 classes share WeaCliError -> zone score 2.
    assert report["summary"]["zones"]["src_wea_cli"]["shared_base_zone_score"] == 2


# ── Pilot behavior preservation ──────────────────────────────────────────────


def test_pilot_preserves_runtime_error_compatibility() -> None:
    """Every retrofitted class still answers True to isinstance(RuntimeError)
    so existing `except RuntimeError` clauses continue to work."""
    sys.path.insert(0, str(REPO_ROOT / "src"))
    from wea_cli.errors import WeaCliError
    from wea_cli.gh import GhError
    from wea_cli.issue_edit import IssueEditError

    for cls in (GhError, IssueEditError):
        assert issubclass(cls, WeaCliError)
        assert issubclass(cls, RuntimeError)
        instance = cls("msg")
        assert isinstance(instance, WeaCliError)
        assert isinstance(instance, RuntimeError)


def test_pilot_pusherror_unchanged() -> None:
    """PushError stays a direct RuntimeError subclass in this PR. It is
    named in the pilot doc as a future hardening candidate."""
    sys.path.insert(0, str(REPO_ROOT / "src"))
    from wea_cli.cli import PushError

    assert issubclass(PushError, RuntimeError)
    err = PushError("msg", status=500)
    assert err.status == 500
    assert str(err) == "msg"
