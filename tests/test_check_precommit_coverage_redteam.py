"""
Adversarial tests for check_precommit_coverage.py exposing bypass vectors.
"""

from scripts.check_precommit_coverage import parse_invoked_scripts

def test_bypass_string_argument():
    """
    Exploit mechanism: The checker splits by shell tokens but doesn't check if the script
    is the executable or just an argument. Passing the script name inside a string argument
    to python (e.g. python -c "print('scripts/check_invariant.py')") causes the regex to
    match it as invoked, even though it's never executed.
    """
    # BYPASS: Script name hidden inside a string argument for python -c
    hook_text = "python -c \"print('scripts/check_invariant.py')\""
    invoked = parse_invoked_scripts(hook_text)
    assert "check_invariant.py" in invoked


def test_bypass_suffix_extension():
    """
    Exploit mechanism: The regex `\\b` matches the boundary between 'py' and '.' in 'py.bak'.
    Thus, calling a different script like 'scripts/check_invariant.py.bak' will be incorrectly
    parsed as invoking 'check_invariant.py'.
    """
    # BYPASS: Regex boundary \\b allows matching prefixes of longer extensions
    hook_text = "python scripts/check_invariant.py.bak"
    invoked = parse_invoked_scripts(hook_text)
    assert "check_invariant.py" in invoked


def test_bypass_argument_to_other_script():
    """
    Exploit mechanism: The checker looks at all tokens after the 'python' command.
    If 'python' runs a different script, and the mandatory script is passed as a flag or argument,
    the checker counts it as invoked.
    """
    # BYPASS: Mandatory script passed as an argument to another script
    hook_text = "python scripts/other_script.py --target scripts/check_invariant.py"
    invoked = parse_invoked_scripts(hook_text)
    assert "check_invariant.py" in invoked


def test_bypass_redirection_operator():
    """
    Exploit mechanism: shlex.split keeps redirection operators and their targets as regular tokens.
    If the mandatory script is provided as input redirection rather than being executed,
    it is falsely counted as invoked.
    """
    # BYPASS: Mandatory script used as input file via redirection
    hook_text = "python -m json.tool < scripts/check_invariant.py"
    invoked = parse_invoked_scripts(hook_text)
    assert "check_invariant.py" in invoked


def test_bypass_command_chaining():
    """
    Exploit mechanism: shlex.split doesn't understand command separators like ';' or '&&'.
    It treats them as regular tokens. If a line starts with 'python', ANY script mentioned
    later in the line (even in a separate command) is counted as invoked.
    """
    # BYPASS: Script mentioned in a chained command, not executed by python
    hook_text = "python -V ; echo scripts/check_invariant.py"
    invoked = parse_invoked_scripts(hook_text)
    assert "check_invariant.py" in invoked


def test_bypass_quoted_comment():
    """
    Exploit mechanism: shlex.split with comments=True ignores unquoted '#', but keeps quoted ones.
    If a string containing a comment with the script name is passed as an argument,
    it is still parsed and matched by the regex.
    """
    # BYPASS: Script name hidden inside a quoted string that looks like a comment
    hook_text = "python scripts/other.py \"# scripts/check_invariant.py\""
    invoked = parse_invoked_scripts(hook_text)
    assert "check_invariant.py" in invoked
