import json
import pytest
from pathlib import Path
from scripts.check_genome_completeness import run

def create_env(tmp_path: Path, balances_data: dict, genomes_data: dict) -> Path:
    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir(parents=True, exist_ok=True)
    if balances_data is not None:
        (ledger_dir / "balances.json").write_text(json.dumps(balances_data))
    
    genomes_dir = tmp_path / "genomes"
    genomes_dir.mkdir(parents=True, exist_ok=True)
    
    for agent_id, data in genomes_data.items():
        if "/" in agent_id or "\\" in agent_id:
            # For path traversal tests
            agent_dir = (genomes_dir / agent_id).resolve()
            agent_dir.parent.mkdir(parents=True, exist_ok=True)
        else:
            agent_dir = genomes_dir / agent_id
            
        if not agent_dir.exists():
            agent_dir.mkdir()
            
        if "meta" in data:
            meta_path = agent_dir / "genome_meta.json"
            if data["meta"] == "__DIR__":
                meta_path.mkdir()
            else:
                meta_path.write_text(
                    data["meta"] if isinstance(data["meta"], str) else json.dumps(data["meta"])
                )
        
        if "md" in data:
            md_path = agent_dir / "AGENTS.local.md"
            if data["md"] == "__DIR__":
                md_path.mkdir()
            else:
                md_path.write_text(data["md"])
                
    return tmp_path

def test_1_wrong_agent_id_in_meta(tmp_path):
    env = create_env(
        tmp_path,
        {"agents": {"Agent-1@test": 0}},
        {"Agent-1@test": {
            "meta": {"agent_id": "Agent-2@test", "fitness": 1, "mutations": []},
            "md": "hello"
        }}
    )
    res, passed = run(env)
    assert not passed
    assert any("does not match" in c["detail"] for c in res["checks"] if c["status"] == "FAIL")

def test_2_agents_local_md_is_directory(tmp_path):
    env = create_env(
        tmp_path,
        {"agents": {"Agent-1@test": 0}},
        {"Agent-1@test": {
            "meta": {"agent_id": "Agent-1@test", "fitness": 1, "mutations": []},
            "md": "__DIR__"
        }}
    )
    res, passed = run(env)
    assert not passed

def test_3_agents_local_md_is_whitespace_only(tmp_path):
    env = create_env(
        tmp_path,
        {"agents": {"Agent-1@test": 0}},
        {"Agent-1@test": {
            "meta": {"agent_id": "Agent-1@test", "fitness": 1, "mutations": []},
            "md": "   \n\t  \n"
        }}
    )
    res, passed = run(env)
    assert not passed

def test_4_meta_required_fields_are_null(tmp_path):
    env = create_env(
        tmp_path,
        {"agents": {"Agent-1@test": 0}},
        {"Agent-1@test": {
            "meta": {"agent_id": None, "fitness": None, "mutations": None},
            "md": "hello"
        }}
    )
    res, passed = run(env)
    assert not passed

def test_5_meta_required_fields_are_empty_strings(tmp_path):
    env = create_env(
        tmp_path,
        {"agents": {"Agent-1@test": 0}},
        {"Agent-1@test": {
            "meta": {"agent_id": "", "fitness": "", "mutations": ""},
            "md": "hello"
        }}
    )
    res, passed = run(env)
    assert not passed

def test_6_meta_is_directory(tmp_path):
    env = create_env(
        tmp_path,
        {"agents": {"Agent-1@test": 0}},
        {"Agent-1@test": {
            "meta": "__DIR__",
            "md": "hello"
        }}
    )
    res, passed = run(env)
    assert not passed
    # Should not raise exception, should cleanly fail

def test_7_path_traversal_in_agent_id(tmp_path):
    env = create_env(
        tmp_path,
        {"agents": {"../Agent-1@test": 0}},
        {"../Agent-1@test": {
            "meta": {"agent_id": "../Agent-1@test", "fitness": 1, "mutations": []},
            "md": "hello"
        }}
    )
    res, passed = run(env)
    assert not passed

def test_8_balances_agents_is_list(tmp_path):
    env = create_env(
        tmp_path,
        {"agents": ["Agent-1@test", "Agent-2@test"]},
        {"Agent-1@test": {
            "meta": {"agent_id": "Agent-1@test", "fitness": 1, "mutations": []},
            "md": "hello"
        }}
    )
    res, passed = run(env)
    # The script should detect invalid structure and fail cleanly
    assert not passed

def test_9_agent_id_is_empty_string(tmp_path):
    env = create_env(
        tmp_path,
        {"agents": {"": 0}},
        {"": {
            "meta": {"agent_id": "", "fitness": 1, "mutations": []},
            "md": "hello"
        }}
    )
    res, passed = run(env)
    assert not passed

def test_10_missing_required_field_entirely(tmp_path):
    env = create_env(
        tmp_path,
        {"agents": {"Agent-1@test": 0}},
        {"Agent-1@test": {
            "meta": {"agent_id": "Agent-1@test", "fitness": 1}, # missing mutations
            "md": "hello"
        }}
    )
    res, passed = run(env)
    assert not passed
