import pytest
from pathlib import Path
from scripts.check_script_test_coverage import run

def test_bypass_comment_reference(tmp_path: Path):
    """
    # BYPASS: Exploit mechanism - The regex searches for the script stem anywhere in the test files,
    including inside comments. A test file that only mentions the script in a comment
    will successfully pass the coverage check, even though the script is not actually tested.
    """
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "check_foo.py").write_text("print('foo')")
    
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_unrelated.py").write_text("# We should test check_foo.py eventually")
    
    result, passed = run(tmp_path)
    assert passed is True
    assert result["status"] == "PASS"

def test_bypass_string_literal(tmp_path: Path):
    """
    # BYPASS: Exploit mechanism - The regex matches the script stem inside string literals
    that have unrelated extensions. For example, referencing a YAML file like "check_foo.yaml"
    will count as coverage for the Python script "check_foo.py".
    """
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "check_foo.py").write_text("print('foo')")
    
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_yaml.py").write_text("file = 'check_foo.yaml'")
    
    result, passed = run(tmp_path)
    assert passed is True
    assert result["status"] == "PASS"

def test_bypass_hyphenated_suffix(tmp_path: Path):
    """
    # BYPASS: Exploit mechanism - The regex negative lookahead uses a word boundary that
    allows non-word characters. Thus, referencing an unrelated string like "check_foo-bar"
    will match the stem "check_foo", improperly counting it as covered.
    """
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "check_foo.py").write_text("print('foo')")
    
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    # A test file referencing an unrelated hyphenated name
    (tests_dir / "test_unrelated.py").write_text("var = 'check_foo-bar'")
    
    result, passed = run(tmp_path)
    assert passed is True
    assert result["status"] == "PASS"

def test_bypass_variable_name(tmp_path: Path):
    """
    # BYPASS: Exploit mechanism - The regex matches the script stem when it is used as
    an unrelated local variable name inside a test file.
    """
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "check_foo.py").write_text("print('foo')")
    
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_unrelated.py").write_text("def test_something():\n    check_foo = 1")
    
    result, passed = run(tmp_path)
    assert passed is True
    assert result["status"] == "PASS"

def test_negative_no_bypass_on_word_suffix(tmp_path: Path):
    """
    Exploit mechanism - Testing if "check_foobar" matches "check_foo". 
    This should fail (not bypass) because "b" is a word character, caught by the negative lookahead.
    """
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "check_foo.py").write_text("print('foo')")
    
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_unrelated.py").write_text("var = 'check_foobar'")
    
    result, passed = run(tmp_path)
    assert passed is False
    assert result["status"] == "FAIL"

def test_negative_no_bypass_on_word_prefix(tmp_path: Path):
    """
    Exploit mechanism - Testing if "recheck_foo" matches "check_foo". 
    This should fail (not bypass) because "e" is a word character, caught by the negative lookbehind.
    """
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "check_foo.py").write_text("print('foo')")
    
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_unrelated.py").write_text("var = 'recheck_foo'")
    
    result, passed = run(tmp_path)
    assert passed is False
    assert result["status"] == "FAIL"

def test_bypass_import_unrelated_module(tmp_path: Path):
    """
    # BYPASS: Exploit mechanism - The regex doesn't distinguish between importing the target
    script and an unrelated module with the same stem. Importing `src.check_foo` marks
    `scripts/check_foo.py` as covered.
    """
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "check_foo.py").write_text("print('foo')")
    
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_unrelated.py").write_text("from src import check_foo")
    
    result, passed = run(tmp_path)
    assert passed is True
    assert result["status"] == "PASS"

def test_bypass_dead_test_evasion(tmp_path: Path):
    """
    # BYPASS: Exploit mechanism - A dead test file (tests/test_check_foo.py) that no longer tests 
    its intended script will evade dead test detection if it accidentally mentions another 
    valid check script's name (like check_bar), even in a comment.
    """
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "check_bar.py").write_text("print('bar')")
    
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    # test_check_foo.py is meant for check_foo.py, which doesn't exist.
    # It should be flagged as a dead test file.
    # But because it mentions check_bar in a comment, it evades detection!
    (tests_dir / "test_check_foo.py").write_text("# also related to check_bar")
    
    result, passed = run(tmp_path)
    assert passed is True
    assert result["status"] == "PASS"
    assert len(result["dead_test_files"]) == 0
