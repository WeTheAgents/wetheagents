"""Tests for scripts/circle1/observability_inventory.py.

Coverage targets (one class per channel family + integration):
    TestStdoutHuman       - print, click.echo, sys.stdout.write
    TestStderr            - print(file=sys.stderr), click.echo(err=True)
    TestLogging           - logging module + bound-logger heuristic
    TestFileArtifact      - open() writes, Path.write_text/open, json.dump
    TestLedgerWrite       - literal-path ledger detection + under-report
    TestGithubSideEffect  - `gh` subprocess + api.github.com URLs
    TestSubprocessLaunch  - subprocess.run, os.system, os.popen
    TestNetworkExternal   - requests/httpx/urllib (excluding api.github.com)
    TestAmbiguous         - non-literal mode/command, non-sys file=
    TestParseError        - files that fail to parse are recorded
    TestExclusion         - __init__.py default + --exclude transparency
    TestEnd2End           - CLI invocation, JSON shape, summary counts
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from scripts.circle1.observability_inventory import (
    CHANNEL_TAXONOMY,
    HARNESS_VERSION,
    LIMITATIONS,
    build_inventory,
    main,
    render_markdown_summary,
    scan_file,
    scan_zone,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def write_py(tmp_path: Path):
    def _write(src: str, name: str = "module.py") -> Path:
        p = tmp_path / name
        p.write_text(textwrap.dedent(src), encoding="utf-8")
        return p
    return _write


def _channels(report) -> list[str]:
    return [d.channel for d in report.channels]


def _evidence(report) -> list[tuple[str, str]]:
    return [(d.channel, d.evidence) for d in report.channels]


# ---------------------------------------------------------------------------
# stdout_human
# ---------------------------------------------------------------------------


class TestStdoutHuman:
    def test_print_default(self, write_py, tmp_path):
        p = write_py("print('hello')")
        report = scan_file(p, tmp_path)
        assert "stdout_human" in _channels(report)

    def test_print_explicit_stdout(self, write_py, tmp_path):
        p = write_py(
            """\
            import sys
            print('x', file=sys.stdout)
            """
        )
        report = scan_file(p, tmp_path)
        assert "stdout_human" in _channels(report)

    def test_click_echo(self, write_py, tmp_path):
        p = write_py(
            """\
            import click
            click.echo('hi')
            """
        )
        report = scan_file(p, tmp_path)
        assert "stdout_human" in _channels(report)

    def test_sys_stdout_write(self, write_py, tmp_path):
        p = write_py(
            """\
            import sys
            sys.stdout.write('raw')
            """
        )
        report = scan_file(p, tmp_path)
        assert "stdout_human" in _channels(report)

    def test_aliased_sys_module(self, write_py, tmp_path):
        """`import sys as s` then `s.stdout.write(...)` — alias must
        resolve before classification."""
        p = write_py(
            """\
            import sys as s
            s.stdout.write('raw')
            """
        )
        report = scan_file(p, tmp_path)
        assert "stdout_human" in _channels(report)


# ---------------------------------------------------------------------------
# stderr
# ---------------------------------------------------------------------------


class TestStderr:
    def test_print_to_stderr(self, write_py, tmp_path):
        p = write_py(
            """\
            import sys
            print('boom', file=sys.stderr)
            """
        )
        report = scan_file(p, tmp_path)
        assert "stderr" in _channels(report)
        assert "stdout_human" not in _channels(report)

    def test_sys_stderr_write(self, write_py, tmp_path):
        p = write_py(
            """\
            import sys
            sys.stderr.write('boom')
            """
        )
        report = scan_file(p, tmp_path)
        assert "stderr" in _channels(report)

    def test_click_echo_err_true(self, write_py, tmp_path):
        p = write_py(
            """\
            import click
            click.echo('boom', err=True)
            """
        )
        report = scan_file(p, tmp_path)
        assert "stderr" in _channels(report)
        assert "stdout_human" not in _channels(report)


# ---------------------------------------------------------------------------
# logging
# ---------------------------------------------------------------------------


class TestLogging:
    def test_basic_config(self, write_py, tmp_path):
        p = write_py(
            """\
            import logging
            logging.basicConfig(level=logging.INFO)
            """
        )
        report = scan_file(p, tmp_path)
        assert "logging" in _channels(report)

    def test_module_level_call(self, write_py, tmp_path):
        p = write_py(
            """\
            import logging
            def go():
                logging.info('starting')
            """
        )
        report = scan_file(p, tmp_path)
        assert "logging" in _channels(report)

    def test_aliased_logging_module(self, write_py, tmp_path):
        p = write_py(
            """\
            import logging as L
            def go():
                L.getLogger(__name__)
            """
        )
        report = scan_file(p, tmp_path)
        assert "logging" in _channels(report)

    def test_from_import_get_logger(self, write_py, tmp_path):
        """`from logging import getLogger` followed by a bare `getLogger(...)`
        call must classify as logging via the ImportFrom alias table."""
        p = write_py(
            """\
            from logging import getLogger
            def go():
                getLogger(__name__)
            """
        )
        report = scan_file(p, tmp_path)
        assert "logging" in _channels(report)

    def test_from_import_get_logger_aliased(self, write_py, tmp_path):
        p = write_py(
            """\
            from logging import getLogger as gl
            def go():
                gl(__name__)
            """
        )
        report = scan_file(p, tmp_path)
        assert "logging" in _channels(report)

    def test_bound_logger_tracked_binding(self, write_py, tmp_path):
        """Receiver assigned from logging.getLogger is tracked, regardless
        of name — `audit`, `metrics`, `tracer` are all classified."""
        p = write_py(
            """\
            import logging
            audit = logging.getLogger('audit')
            metrics = logging.getLogger('metrics')
            tracer = logging.getLogger('tracer')
            def go():
                audit.info('a')
                metrics.error('m')
                tracer.debug('t')
            """
        )
        report = scan_file(p, tmp_path)
        chans = _channels(report)
        # 3 getLogger configs + 3 bound calls = 6 logging detections
        assert chans.count("logging") >= 6
        # Evidence makes the binding-tracking path explicit somewhere.
        joined = " | ".join(d.reason for d in report.channels)
        assert "tracked as logging.getLogger" in joined

    def test_bound_logger_from_import_binding(self, write_py, tmp_path):
        """Binding tracker also handles `from logging import getLogger`."""
        p = write_py(
            """\
            from logging import getLogger
            audit = getLogger('audit')
            def go():
                audit.warning('hi')
            """
        )
        report = scan_file(p, tmp_path)
        chans = _channels(report)
        assert chans.count("logging") >= 2  # getLogger + audit.warning

    def test_bound_logger_named_logger_heuristic(self, write_py, tmp_path):
        """`logger.info(...)` without a tracked binding still classifies
        via the narrowed name heuristic (logger / *_logger)."""
        p = write_py(
            """\
            def emit(logger):
                logger.info('hi')
                logger.error('bad')
            """
        )
        report = scan_file(p, tmp_path)
        assert "logging" in _channels(report)

    def test_dialog_not_classified_as_logger(self, write_py, tmp_path):
        """`dialog.error(...)` and `catalog.warning(...)` must NOT fire the
        bound-logger heuristic — name does not end in 'logger' and there is
        no tracked binding. This was the redteam's over-firing complaint."""
        p = write_py(
            """\
            def show(dialog, catalog):
                dialog.error('oh no')
                catalog.warning('missing')
            """
        )
        report = scan_file(p, tmp_path)
        assert "logging" not in _channels(report)

    def test_logger_substring_alone_not_enough(self, write_py, tmp_path):
        """Receiver `mylog` (substring 'log' but no binding) must NOT fire."""
        p = write_py(
            """\
            def emit(mylog):
                mylog.info('hi')
            """
        )
        report = scan_file(p, tmp_path)
        assert "logging" not in _channels(report)


# ---------------------------------------------------------------------------
# file_artifact (and ledger_write)
# ---------------------------------------------------------------------------


class TestFileArtifact:
    def test_open_write_mode(self, write_py, tmp_path):
        p = write_py(
            """\
            with open('out.txt', 'w') as fh:
                fh.write('x')
            """
        )
        report = scan_file(p, tmp_path)
        assert "file_artifact" in _channels(report)

    def test_open_append_mode(self, write_py, tmp_path):
        p = write_py("open('out.txt', 'a').close()")
        report = scan_file(p, tmp_path)
        assert "file_artifact" in _channels(report)

    def test_open_default_mode_not_flagged(self, write_py, tmp_path):
        p = write_py("open('in.txt').read()")
        report = scan_file(p, tmp_path)
        assert "file_artifact" not in _channels(report)

    def test_path_write_text(self, write_py, tmp_path):
        p = write_py(
            """\
            from pathlib import Path
            Path('out.txt').write_text('x')
            """
        )
        report = scan_file(p, tmp_path)
        assert "file_artifact" in _channels(report)

    def test_path_open_write(self, write_py, tmp_path):
        p = write_py(
            """\
            from pathlib import Path
            with Path('out.txt').open('w') as fh:
                fh.write('x')
            """
        )
        report = scan_file(p, tmp_path)
        assert "file_artifact" in _channels(report)

    def test_path_open_read_not_flagged(self, write_py, tmp_path):
        p = write_py(
            """\
            from pathlib import Path
            with Path('in.txt').open(encoding='utf-8') as fh:
                fh.read()
            """
        )
        report = scan_file(p, tmp_path)
        assert "file_artifact" not in _channels(report)

    def test_json_dump(self, write_py, tmp_path):
        p = write_py(
            """\
            import json
            with open('x.json', 'w') as f:
                json.dump({'k': 1}, f)
            """
        )
        report = scan_file(p, tmp_path)
        assert "file_artifact" in _channels(report)


class TestLedgerWrite:
    def test_literal_ledger_path(self, write_py, tmp_path):
        p = write_py(
            """\
            with open('ledger/balances.json', 'w') as f:
                f.write('{}')
            """
        )
        report = scan_file(p, tmp_path)
        chans = _channels(report)
        assert "file_artifact" in chans
        assert "ledger_write" in chans

    def test_nested_ledger_path(self, write_py, tmp_path):
        p = write_py(
            """\
            open('./ledger/history/2026.jsonl', 'a').close()
            """
        )
        report = scan_file(p, tmp_path)
        assert "ledger_write" in _channels(report)

    def test_non_literal_path_under_reports(self, write_py, tmp_path):
        """Documented limitation: variable path is not classified as
        ledger_write. The harness must still flag the artifact write."""
        p = write_py(
            """\
            balances = 'ledger/balances.json'
            with open(balances, 'w') as f:
                f.write('{}')
            """
        )
        report = scan_file(p, tmp_path)
        chans = _channels(report)
        assert "file_artifact" in chans
        assert "ledger_write" not in chans  # documented under-report


# ---------------------------------------------------------------------------
# github_side_effect
# ---------------------------------------------------------------------------


class TestGithubSideEffect:
    def test_subprocess_gh_list_form(self, write_py, tmp_path):
        p = write_py(
            """\
            import subprocess
            subprocess.run(['gh', 'issue', 'list'], check=True)
            """
        )
        report = scan_file(p, tmp_path)
        chans = _channels(report)
        assert "subprocess_launch" in chans
        assert "github_side_effect" in chans

    def test_subprocess_gh_string_form(self, write_py, tmp_path):
        p = write_py(
            """\
            import subprocess
            subprocess.run('gh issue list', shell=True)
            """
        )
        report = scan_file(p, tmp_path)
        assert "github_side_effect" in _channels(report)

    def test_requests_to_api_github_com(self, write_py, tmp_path):
        p = write_py(
            """\
            import requests
            requests.post('https://api.github.com/repos/x/y/issues')
            """
        )
        report = scan_file(p, tmp_path)
        chans = _channels(report)
        assert "github_side_effect" in chans
        assert "network_external" not in chans  # reclassified, not duplicated

    def test_subprocess_non_gh_not_flagged(self, write_py, tmp_path):
        p = write_py(
            """\
            import subprocess
            subprocess.run(['git', 'status'])
            """
        )
        report = scan_file(p, tmp_path)
        chans = _channels(report)
        assert "subprocess_launch" in chans
        assert "github_side_effect" not in chans

    def test_from_import_subprocess_run_gh(self, write_py, tmp_path):
        """`from subprocess import run; run(['gh', ...])` must classify via
        the ImportFrom alias table — both subprocess_launch AND github."""
        p = write_py(
            """\
            from subprocess import run
            run(['gh', 'pr', 'list'])
            """
        )
        report = scan_file(p, tmp_path)
        chans = _channels(report)
        assert "subprocess_launch" in chans
        assert "github_side_effect" in chans

    def test_from_import_subprocess_check_output(self, write_py, tmp_path):
        p = write_py(
            """\
            from subprocess import check_output
            check_output(['gh', 'api', 'user'])
            """
        )
        report = scan_file(p, tmp_path)
        chans = _channels(report)
        assert "subprocess_launch" in chans
        assert "github_side_effect" in chans

    def test_os_popen_gh_string(self, write_py, tmp_path):
        """`os.popen('gh issue list')` must flag both subprocess_launch and
        github_side_effect — first-token check is uniform across os funcs."""
        p = write_py(
            """\
            import os
            os.popen('gh issue list')
            """
        )
        report = scan_file(p, tmp_path)
        chans = _channels(report)
        assert "subprocess_launch" in chans
        assert "github_side_effect" in chans

    def test_os_system_gh_string(self, write_py, tmp_path):
        p = write_py(
            """\
            import os
            os.system('gh pr review --approve')
            """
        )
        report = scan_file(p, tmp_path)
        chans = _channels(report)
        assert "subprocess_launch" in chans
        assert "github_side_effect" in chans


# ---------------------------------------------------------------------------
# subprocess_launch
# ---------------------------------------------------------------------------


class TestSubprocessLaunch:
    def test_subprocess_run(self, write_py, tmp_path):
        p = write_py(
            """\
            import subprocess
            subprocess.run(['ls', '-la'])
            """
        )
        report = scan_file(p, tmp_path)
        assert "subprocess_launch" in _channels(report)

    def test_subprocess_check_output(self, write_py, tmp_path):
        p = write_py(
            """\
            import subprocess
            subprocess.check_output(['git', 'rev-parse', 'HEAD'])
            """
        )
        report = scan_file(p, tmp_path)
        assert "subprocess_launch" in _channels(report)

    def test_os_system(self, write_py, tmp_path):
        p = write_py(
            """\
            import os
            os.system('echo hi')
            """
        )
        report = scan_file(p, tmp_path)
        assert "subprocess_launch" in _channels(report)


# ---------------------------------------------------------------------------
# network_external
# ---------------------------------------------------------------------------


class TestNetworkExternal:
    def test_requests_get(self, write_py, tmp_path):
        p = write_py(
            """\
            import requests
            requests.get('https://example.com/data')
            """
        )
        report = scan_file(p, tmp_path)
        assert "network_external" in _channels(report)

    def test_httpx_post(self, write_py, tmp_path):
        p = write_py(
            """\
            import httpx
            httpx.post('https://example.com/endpoint')
            """
        )
        report = scan_file(p, tmp_path)
        assert "network_external" in _channels(report)


# ---------------------------------------------------------------------------
# ambiguous
# ---------------------------------------------------------------------------


class TestAmbiguous:
    def test_print_with_unknown_file(self, write_py, tmp_path):
        p = write_py(
            """\
            def emit(stream):
                print('x', file=stream)
            """
        )
        report = scan_file(p, tmp_path)
        assert "ambiguous" in _channels(report)
        # And not classified as stdout/stderr
        chans = _channels(report)
        assert "stdout_human" not in chans
        assert "stderr" not in chans

    def test_subprocess_non_literal_command(self, write_py, tmp_path):
        p = write_py(
            """\
            import subprocess
            def run(cmd):
                subprocess.run(cmd)
            """
        )
        report = scan_file(p, tmp_path)
        chans = _channels(report)
        assert "subprocess_launch" in chans
        assert "ambiguous" in chans

    def test_open_non_literal_mode(self, write_py, tmp_path):
        p = write_py(
            """\
            def make(p, m):
                return open(p, m)
            """
        )
        report = scan_file(p, tmp_path)
        assert "ambiguous" in _channels(report)


# ---------------------------------------------------------------------------
# parse error
# ---------------------------------------------------------------------------


class TestParseError:
    def test_syntax_error_recorded(self, write_py, tmp_path):
        p = write_py("def broken(:\n    pass")
        report = scan_file(p, tmp_path)
        assert report.parse_error is not None
        assert "SyntaxError" in report.parse_error
        assert report.channels == []


# ---------------------------------------------------------------------------
# exclusion
# ---------------------------------------------------------------------------


class TestExclusion:
    def test_default_excludes_init_only(self, tmp_path):
        zone = tmp_path / "scripts"
        nested = zone / "sub"
        nested.mkdir(parents=True)
        (zone / "__init__.py").write_text("# excluded\n", encoding="utf-8")
        (nested / "__init__.py").write_text("# excluded too\n", encoding="utf-8")
        (zone / "real.py").write_text("print('a')\n", encoding="utf-8")
        (nested / "deep.py").write_text("print('b')\n", encoding="utf-8")

        reports = scan_zone(tmp_path, zone="scripts")
        paths = sorted(r.path for r in reports)
        # Both __init__ files excluded; both real files retained.
        assert paths == ["scripts/real.py", "scripts/sub/deep.py"]

    def test_explicit_exclude_recorded_in_output(self, tmp_path):
        zone = tmp_path / "scripts"
        zone.mkdir()
        (zone / "__init__.py").write_text("# x\n", encoding="utf-8")
        (zone / "noisy.py").write_text("print('a')\n", encoding="utf-8")
        (zone / "quiet.py").write_text("x = 1\n", encoding="utf-8")

        reports = scan_zone(
            tmp_path, zone="scripts", exclude_patterns=["__init__.py", "noisy.py"]
        )
        paths = sorted(r.path for r in reports)
        assert paths == ["scripts/quiet.py"]

        inv = build_inventory(
            reports,
            scan_date="2026-05-02",
            root_zone="scripts",
            exclude_patterns=["__init__.py", "noisy.py"],
        )
        # Anti-gaming: exclusions are visible in the JSON.
        assert inv["exclude_patterns"] == ["__init__.py", "noisy.py"]


# ---------------------------------------------------------------------------
# end-to-end
# ---------------------------------------------------------------------------


class TestEnd2End:
    def test_inventory_shape_and_counts(self, tmp_path):
        zone = tmp_path / "scripts"
        zone.mkdir()
        (zone / "a.py").write_text("print('a')\n", encoding="utf-8")
        (zone / "b.py").write_text(
            "import subprocess\nsubprocess.run(['gh','issue','list'])\n",
            encoding="utf-8",
        )
        (zone / "c.py").write_text("def broken(:\n    pass", encoding="utf-8")

        reports = scan_zone(tmp_path, zone="scripts")
        inv = build_inventory(
            reports,
            scan_date="2026-05-02",
            root_zone="scripts",
            exclude_patterns=["__init__.py"],
        )

        # Top-level shape
        assert inv["harness_version"] == HARNESS_VERSION
        assert inv["scan_date"] == "2026-05-02"
        assert inv["root_zone"] == "scripts"
        assert inv["channel_taxonomy"] == CHANNEL_TAXONOMY
        assert inv["limitations"] == LIMITATIONS

        # Summary counts
        s = inv["summary"]
        assert s["total_files"] == 3
        assert s["files_unparseable"] == 1
        assert s["files_with_any_channel"] == 2

        # by_channel completeness — every taxonomy channel appears as a key
        # even when its count is zero (stable schema for checkpoint diffs).
        assert set(s["by_channel"]) >= set(CHANNEL_TAXONOMY)

        # Per-file structure
        files_by_path = {f["path"]: f for f in inv["files"]}
        assert files_by_path["scripts/c.py"]["parse_error"] is not None
        assert files_by_path["scripts/c.py"]["channels"] == []

        # Each channel detection has the documented fields.
        for ch in files_by_path["scripts/b.py"]["channels"]:
            assert set(ch) == {"channel", "lineno", "evidence", "reason"}
            assert isinstance(ch["lineno"], int)
            assert ch["lineno"] >= 1

    def test_cli_writes_json_and_markdown(self, tmp_path):
        zone = tmp_path / "scripts"
        zone.mkdir()
        (zone / "a.py").write_text("print('a')\n", encoding="utf-8")

        out_json = tmp_path / "out.json"
        out_md = tmp_path / "out.md"
        rc = main(
            [
                "--root",
                str(tmp_path),
                "--output",
                str(out_json),
                "--markdown",
                str(out_md),
                "--scan-date",
                "2026-05-02",
            ]
        )
        assert rc == 0
        payload = json.loads(out_json.read_text(encoding="utf-8"))
        assert payload["scan_date"] == "2026-05-02"
        assert payload["summary"]["total_files"] == 1
        md = out_md.read_text(encoding="utf-8")
        assert "Observability inventory" in md
        assert "stdout_human" in md

    def test_cli_missing_zone_exits_nonzero(self, tmp_path, capsys):
        """A mistyped --zone must exit nonzero with a stderr message rather
        than silently produce total_files=0 (denominator-hiding violation)."""
        rc = main(
            [
                "--root",
                str(tmp_path),
                "--zone",
                "scrits",  # typo
                "--scan-date",
                "2026-05-02",
            ]
        )
        captured = capsys.readouterr()
        assert rc != 0
        assert "zone directory not found" in captured.err
        # No JSON inventory written to stdout — empty inventory must not be
        # indistinguishable from a successful scan of an empty zone.
        assert captured.out == ""

    def test_cli_root_present_zone_absent_no_silent_zero(self, tmp_path, capsys):
        """Defensive variant: root is a real directory, zone happens to be
        absent. We must NOT print a valid {total_files: 0} JSON document."""
        # tmp_path is a valid directory but contains no `scripts/` subdir.
        rc = main(["--root", str(tmp_path), "--scan-date", "2026-05-02"])
        captured = capsys.readouterr()
        assert rc != 0
        assert captured.out == ""
        assert "zone directory not found" in captured.err

    def test_cli_subprocess_invocation(self, tmp_path):
        """Black-box: invoke the CLI as a child process. Catches any
        regression in argparse, exit code, stdout JSON, or import path
        wiring that direct main() calls would mask."""
        zone = tmp_path / "scripts"
        zone.mkdir()
        (zone / "a.py").write_text("print('a')\n", encoding="utf-8")

        result = subprocess.run(
            [
                sys.executable,
                "scripts/circle1/observability_inventory.py",
                "--root",
                str(tmp_path),
                "--scan-date",
                "2026-05-02",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["root_zone"] == "scripts"
        assert payload["summary"]["total_files"] == 1


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------


class TestMarkdownRender:
    def test_lists_every_channel(self, tmp_path):
        reports = scan_zone(tmp_path / "absent_zone", zone="missing")
        # missing zone -> empty list, but rendering must still work.
        inv = build_inventory(
            reports,
            scan_date="2026-05-02",
            root_zone="missing",
            exclude_patterns=["__init__.py"],
        )
        md = render_markdown_summary(inv)
        for channel in CHANNEL_TAXONOMY:
            assert channel in md
        assert "Known limitations" in md
