import subprocess
import sys
from pathlib import Path

import pytest

GUARD_SCRIPT = Path(__file__).parent.parent / "scripts" / "genome_guard.py"

def setup_fake_root(tmp_path: Path) -> Path:
    """Sets up a minimal valid repository structure."""
    base_dir = tmp_path / "genomes" / "base"
    base_dir.mkdir(parents=True)
    template = base_dir / "AGENTS.local.template.md"
    template.write_text("Constitution Line 1\nConstitution Line 2\n---\nTemplate body\n", encoding="utf-8")
    return tmp_path

def create_agent(tmp_path: Path, name: str, content: str) -> Path:
    agent_dir = tmp_path / "genomes" / name
    agent_dir.mkdir(parents=True, exist_ok=True)
    agent_file = agent_dir / "AGENTS.local.md"
    agent_file.write_text(content, encoding="utf-8")
    return agent_file

def run_guard(*args):
    cmd = [sys.executable, str(GUARD_SCRIPT)] + list(args)
    return subprocess.run(cmd, capture_output=True, text=True)

def test_empty_agent_genome(tmp_path):
    """Attack vector: Empty AGENTS.local.md - does the guard catch it or pass it?"""
    setup_fake_root(tmp_path)
    create_agent(tmp_path, "agent1", "")
    
    result = run_guard("--root", str(tmp_path))
    # Should fail because the constitution part is missing
    assert result.returncode == 1
    assert "AMENDMENT SIGNAL" in result.stdout

def test_whitespace_only_genome(tmp_path):
    """Attack vector: Genome file with only whitespace lines."""
    setup_fake_root(tmp_path)
    create_agent(tmp_path, "agent2", "   \n\n\t\n")
    
    result = run_guard("--root", str(tmp_path))
    assert result.returncode == 1
    assert "AMENDMENT SIGNAL" in result.stdout

def test_exact_line_count_different_content(tmp_path):
    """Attack vector: Genome file exactly at template line count but with different content."""
    setup_fake_root(tmp_path)
    # The template has 4 lines. We make agent file 4 lines with different content.
    create_agent(tmp_path, "agent3", "Malicious Line 1\nMalicious Line 2\n---\nBad body\n")
    
    result = run_guard("--root", str(tmp_path))
    assert result.returncode == 1
    assert "AMENDMENT SIGNAL" in result.stdout

def test_missing_template_file(tmp_path):
    """Attack vector: Missing template file - does the guard crash or silently exit 0?"""
    # Set up root without the base/AGENTS.local.template.md
    base_dir = tmp_path / "genomes" / "base"
    base_dir.mkdir(parents=True)
    create_agent(tmp_path, "agent4", "Constitution Line 1\nConstitution Line 2\n---\nBody\n")
    
    result = run_guard("--root", str(tmp_path))
    # It should fail safely (exit 1)
    assert result.returncode == 1
    assert "Base template not found" in result.stdout

def test_malformed_template_file(tmp_path):
    """Attack vector: Template file itself is malformed (no --- divider)."""
    setup_fake_root(tmp_path)
    # Overwrite template without ---
    template = tmp_path / "genomes" / "base" / "AGENTS.local.template.md"
    template.write_text("Constitution Line 1\nConstitution Line 2\nBody\n", encoding="utf-8")
    
    create_agent(tmp_path, "agent5", "Constitution Line 1\nConstitution Line 2\nDifferent Body\n")
    
    result = run_guard("--root", str(tmp_path))
    # The const_len will be the full length of the template (3 lines).
    # Since agent file's line 3 is different, it should fail.
    assert result.returncode == 1
    assert "AMENDMENT SIGNAL" in result.stdout

def test_very_large_genome(tmp_path):
    """Attack vector: Very large genome file (10x template size)."""
    setup_fake_root(tmp_path)
    # Create valid constitution but over 120 lines total (MAX_LINES=120)
    body = "\n".join([f"line {i}" for i in range(150)])
    content = f"Constitution Line 1\nConstitution Line 2\n---\n{body}"
    create_agent(tmp_path, "agent6", content)
    
    result = run_guard("--root", str(tmp_path))
    assert result.returncode == 1
    assert "has 153 lines (max 120)" in result.stdout

def test_guard_called_with_no_arguments_or_wrong_path(tmp_path):
    """Attack vector: Guard called with no arguments or wrong path - does it exit 1 or 0?"""
    # If called with a path that has no genome files, does it pass?
    # Create a completely empty dir
    empty_root = tmp_path / "empty"
    empty_root.mkdir()
    
    result = run_guard("--root", str(empty_root))
    # It exits 1 because template is not found!
    assert result.returncode == 1
    assert "Base template not found" in result.stdout

def test_genome_meta_json_corruption(tmp_path):
    """Attack vector: genome_meta.json corruption vs AGENTS.local.md corruption."""
    setup_fake_root(tmp_path)
    agent_dir = tmp_path / "genomes" / "agent7"
    agent_dir.mkdir()
    # Create valid AGENTS.local.md
    (agent_dir / "AGENTS.local.md").write_text("Constitution Line 1\nConstitution Line 2\n---\nValid\n", encoding="utf-8")
    
    # Create corrupted genome_meta.json
    (agent_dir / "genome_meta.json").write_text("invalid json {[[}", encoding="utf-8")
    
    result = run_guard("--root", str(tmp_path))
    # The script ignores genome_meta.json completely, so it will EXIT 0.
    # This is a bypass / gap in validation if genome_meta.json is important!
    assert result.returncode == 0
    assert "Status: PASS" in result.stdout

def test_bypass_using_hidden_or_non_standard_path(tmp_path):
    """Attack vector: Bypassing the check by passing a file that doesn't trigger the check."""
    setup_fake_root(tmp_path)
    agent_dir = tmp_path / "genomes" / "agent8"
    agent_dir.mkdir()
    # If the pre-commit hook passes a file that is not ending with AGENTS.local.md exactly,
    # or if we pass a malformed file not matching the glob.
    bad_file = agent_dir / "malformed_AGENTS.local.md"
    bad_file.write_text("Bad constitution", encoding="utf-8")
    
    result = run_guard("--root", str(tmp_path), "--files", str(bad_file))
    # The script ignores this file because it does not end with "AGENTS.local.md" exactly,
    # or if it does, it might be skipped. Let's see: bad_file does end with AGENTS.local.md.
    # wait, f.endswith("AGENTS.local.md") is true for "malformed_AGENTS.local.md".
    # so it WILL be checked, and WILL fail.
    assert result.returncode == 1
    assert "AMENDMENT SIGNAL" in result.stdout

def test_bypass_using_files_argument_empty(tmp_path):
    """Attack vector: Passing files that don't match the suffix results in exit 0."""
    setup_fake_root(tmp_path)
    # If pre-commit passes ONLY a changed python file
    result = run_guard("--root", str(tmp_path), "--files", "some_script.py")
    assert result.returncode == 0
    assert "No agent genome files found." in result.stdout
