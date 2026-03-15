"""PATH shim generation for wea spawn — milestone event interception.

Each shimmed binary (git, gh, wea) is written as a Python script so it runs
cross-platform.  On Windows a .cmd wrapper is also written so the OS can find
and execute the shim without requiring a shebang interpreter.

Shim lifecycle per invocation:
  1. If WEA_RUN_DIR is not set → exec real binary and exit (fail-open).
  2. Find the real binary by walking PATH, skipping the shim directory.
  3. Run the real command with all original args, capture exit code.
  4. If exit code == 0 AND args match the intercept table → emit milestone.
  5. Exit with the real command's exit code.

Milestone is emitted AFTER success; failures produce no milestone.
"""

from __future__ import annotations

import os
import sys
import textwrap
from pathlib import Path

# ---------------------------------------------------------------------------
# Intercept table
# ---------------------------------------------------------------------------
# Each entry: (command_name, match_fn_source, milestone_name)
# match_fn_source is Python source for a one-liner predicate over `args`
# (a list of strings, the argv passed to the shim *after* argv[0]).
#
# The shim script embeds this directly so there is no import dependency.

# Milestone payloads keyed by milestone name
_MILESTONE_MAP: dict[str, str] = {
    "task_claimed":   '{"milestone": "task_claimed"}',
    "branch_created": '{"milestone": "branch_created"}',
    "commit_created": '{"milestone": "commit_created"}',
    "push_completed": '{"milestone": "push_completed"}',
    "pr_opened":      '{"milestone": "pr_opened"}',
    "pr_merged":      '{"milestone": "pr_merged"}',
}

# Per-binary intercept rules: list of (predicate_expr, milestone_key)
# predicate_expr is a Python expression that evaluates to True/False given
# the variable `args` (list[str] of all args after the binary name).
_INTERCEPT_RULES: dict[str, list[tuple[str, str]]] = {
    "git": [
        # git commit  (any flags, no subcommand restriction beyond first token)
        ("len(args) >= 1 and args[0] == 'commit'", "commit_created"),
        # git push  (any flags)
        ("len(args) >= 1 and args[0] == 'push'", "push_completed"),
        # git checkout -b  (must have -b flag)
        (
            "len(args) >= 2 and args[0] == 'checkout' and '-b' in args[1:]",
            "branch_created",
        ),
        # git switch -c
        (
            "len(args) >= 2 and args[0] == 'switch' and '-c' in args[1:]",
            "branch_created",
        ),
    ],
    "gh": [
        # gh pr create
        (
            "len(args) >= 2 and args[0] == 'pr' and args[1] == 'create'",
            "pr_opened",
        ),
        # gh pr merge
        (
            "len(args) >= 2 and args[0] == 'pr' and args[1] == 'merge'",
            "pr_merged",
        ),
    ],
    "wea": [
        # wea claim  (any flags/args after "claim")
        ("len(args) >= 1 and args[0] == 'claim'", "task_claimed"),
    ],
}

# ---------------------------------------------------------------------------
# Shim script template
# ---------------------------------------------------------------------------

_SHIM_TEMPLATE = textwrap.dedent(
    """\
    #!/usr/bin/env python3
    # wea-shim: auto-generated — do not edit
    import os
    import subprocess
    import sys

    SHIM_DIR = os.path.normcase(os.path.abspath(os.path.dirname(__file__)))
    BINARY = {binary!r}
    RULES = {rules!r}
    MILESTONES = {milestones!r}

    # Extension search order when looking for real binaries.
    # .exe/.cmd/.bat come first (native Windows executables).
    # "" = bare name (works on POSIX; on Windows catches unusual cases).
    # .py = Python scripts that we'll run via sys.executable.
    _PATHEXT_ORDER = [".exe", ".cmd", ".bat", ".com", "", ".py"]

    def _build_cmd(path):
        \"\"\"Return a (cmd_list, use_shell) pair for running `path`.

        On Windows:
          - .exe        → run directly, no shell
          - .cmd / .bat → must use shell=True (cmd.exe dispatch)
          - .py         → invoke via sys.executable, no shell
        On POSIX:
          - anything    → run directly, no shell
        \"\"\"
        low = path.lower()
        if low.endswith(".py"):
            return [sys.executable, path], False
        if sys.platform == "win32" and (low.endswith(".cmd") or low.endswith(".bat")):
            return [path], True
        return [path], False

    def _find_real(name):
        \"\"\"Find real binary in PATH, skipping SHIM_DIR.

        Returns a (cmd_list, use_shell) pair so callers can pass it
        directly to subprocess.run / subprocess.Popen.
        \"\"\"
        path_env = os.environ.get("PATH", "")
        sep = os.pathsep
        for directory in path_env.split(sep):
            if not directory:
                continue
            norm = os.path.normcase(os.path.abspath(directory))
            if norm == SHIM_DIR:
                continue
            # Try extensions in priority order
            for ext in _PATHEXT_ORDER:
                candidate = os.path.join(directory, name + ext)
                if os.path.isfile(candidate):
                    return _build_cmd(candidate)
        return None

    def _milestone_for(args):
        \"\"\"Return milestone payload JSON string or None.\"\"\"
        local_ns = {{"args": args, "len": len}}
        for predicate, key in RULES:
            try:
                if eval(predicate, {{"__builtins__": {{}}}}, local_ns):
                    return MILESTONES.get(key)
            except Exception:
                pass
        return None

    def main():
        args = sys.argv[1:]
        run_dir = os.environ.get("WEA_RUN_DIR", "")

        found = _find_real(BINARY)
        if found is None:
            # Fallback: let the OS produce a FileNotFoundError naturally
            real_cmd, use_shell = [BINARY], False
        else:
            real_cmd, use_shell = found

        result = subprocess.run(real_cmd + args, shell=use_shell)
        rc = result.returncode

        if rc == 0 and run_dir:
            payload = _milestone_for(args)
            if payload is not None:
                # Emit via CLI: wea trace emit <run_dir> milestone wea-shim <payload>
                wea_found = _find_real("wea")
                if wea_found is None:
                    wea_cmd2, wea_shell = ["wea"], sys.platform == "win32"
                else:
                    wea_cmd2, wea_shell = wea_found
                try:
                    subprocess.run(
                        wea_cmd2 + ["trace", "emit", run_dir, "milestone", "wea-shim", payload],
                        shell=wea_shell,
                        check=False,
                    )
                except Exception:
                    pass  # fail-open: never break the real command's exit

        sys.exit(rc)

    if __name__ == "__main__":
        main()
    """
)

_CMD_WRAPPER_TEMPLATE = textwrap.dedent(
    """\
    @echo off
    "{python}" "%~dpn0.py" %*
    exit /b %ERRORLEVEL%
    """
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def create_shim_dir(run_dir: Path) -> Path:
    """Create .shims/ directory inside run_dir with shim scripts for git, gh, wea.

    Returns the shim directory path (to prepend to PATH).
    On Windows, both a .py and a .cmd file are written per binary.
    On POSIX, only a .py file is written (executable bit set).
    """
    shim_dir = run_dir / ".shims"
    shim_dir.mkdir(parents=True, exist_ok=True)

    for binary, rules in _INTERCEPT_RULES.items():
        _write_shim(shim_dir, binary, rules)

    return shim_dir


def _write_shim(
    shim_dir: Path,
    binary: str,
    rules: list[tuple[str, str]],
) -> None:
    """Write the Python shim (and .cmd wrapper on Windows) for one binary."""
    py_path = shim_dir / f"{binary}.py"
    script = _SHIM_TEMPLATE.format(
        binary=binary,
        rules=rules,
        milestones=_MILESTONE_MAP,
    )
    py_path.write_text(script, encoding="utf-8")

    if sys.platform == "win32":
        # .cmd wrapper so Windows finds the shim without a file extension hunt
        cmd_path = shim_dir / f"{binary}.cmd"
        cmd_path.write_text(
            _CMD_WRAPPER_TEMPLATE.format(python=sys.executable),
            encoding="utf-8",
        )
    else:
        # Set executable bit on POSIX
        py_path.chmod(py_path.stat().st_mode | 0o111)
        # Also write an extension-less wrapper script for POSIX
        wrapper_path = shim_dir / binary
        wrapper_script = f"#!/usr/bin/env python3\nimport runpy, sys; sys.argv[0]={str(py_path)!r}; runpy.run_path({str(py_path)!r}, run_name='__main__')\n"
        wrapper_path.write_text(wrapper_script, encoding="utf-8")
        wrapper_path.chmod(wrapper_path.stat().st_mode | 0o111)
