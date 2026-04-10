"""Tests for src/wea_cli/knowledge.py — BM25 search, decay, CRUD, CLI commands."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from wea_cli.knowledge import (
    DEFAULT_CAP,
    DEFAULT_HALF_LIFE_DAYS,
    agent_slug,
    bm25_search,
    decay_factor,
    get_knowledge_context,
    load_entries,
    make_entry,
    save_entries,
    trim_entries,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def kb_root(tmp_path: Path) -> Path:
    """Repo root with minimal ledger/ structure for resolve_repo_root."""
    ledger = tmp_path / "ledger"
    ledger.mkdir()
    (ledger / "balances.json").write_text(
        json.dumps({"version": 1, "agents": {}}), encoding="utf-8"
    )
    return tmp_path


AGENT = "Claude-1@claude"
SLUG = "claude-1-claude"

_NOW = datetime(2026, 4, 7, 12, 0, 0, tzinfo=timezone.utc)
_TS = _NOW.strftime("%Y-%m-%dT%H:%M:%SZ")


def _ts(days_ago: float) -> str:
    dt = _NOW - timedelta(days=days_ago)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _entry(text: str, days_ago: float = 0, tags: list[str] | None = None, task_ref: int | None = None) -> dict:
    e = make_entry(text, tags=tags, task_ref=task_ref, now=_NOW - timedelta(days=days_ago))
    return e


# ---------------------------------------------------------------------------
# agent_slug
# ---------------------------------------------------------------------------

def test_agent_slug_replaces_at():
    assert agent_slug("Claude-1@claude") == "claude-1-claude"


def test_agent_slug_replaces_special_chars():
    assert agent_slug("agent0@system") == "agent0-system"


def test_agent_slug_lowercase():
    assert agent_slug("MY-AGENT@PLATFORM") == "my-agent-platform"


# ---------------------------------------------------------------------------
# make_entry
# ---------------------------------------------------------------------------

def test_make_entry_fields():
    e = make_entry("test insight", tags=["ledger", "idempotency"], task_ref=42, now=_NOW)
    assert e["text"] == "test insight"
    assert e["tags"] == ["ledger", "idempotency"]
    assert e["task_ref"] == 42
    assert e["created_at"] == _TS
    assert len(e["id"]) == 36  # UUID4


def test_make_entry_defaults():
    e = make_entry("bare entry")
    assert e["tags"] == []
    assert e["task_ref"] is None


# ---------------------------------------------------------------------------
# load_entries / save_entries
# ---------------------------------------------------------------------------

def test_load_entries_missing_file(kb_root: Path):
    assert load_entries(kb_root, AGENT) == []


def test_save_and_load_roundtrip(kb_root: Path):
    entries = [_entry("insight one"), _entry("insight two")]
    save_entries(kb_root, AGENT, entries)

    path = kb_root / "knowledge" / SLUG / "entries.json"
    assert path.exists()

    loaded = load_entries(kb_root, AGENT)
    assert len(loaded) == 2
    assert loaded[0]["text"] == "insight one"
    assert loaded[1]["text"] == "insight two"


def test_save_entries_creates_parent_dir(kb_root: Path):
    save_entries(kb_root, "new-agent@test", [_entry("x")])
    assert (kb_root / "knowledge" / "new-agent-test" / "entries.json").exists()


def test_save_entries_atomic_write(kb_root: Path):
    """No .tmp files left after save."""
    entries = [_entry("atomic write test")]
    save_entries(kb_root, AGENT, entries)
    parent = kb_root / "knowledge" / SLUG
    tmp_files = list(parent.glob("*.tmp"))
    assert tmp_files == []


# ---------------------------------------------------------------------------
# decay_factor
# ---------------------------------------------------------------------------

def test_decay_factor_fresh_entry():
    """Entry created now should have decay ≈ 1.0."""
    d = decay_factor(_TS, _NOW, DEFAULT_HALF_LIFE_DAYS)
    assert abs(d - 1.0) < 1e-9


def test_decay_factor_half_life():
    """Entry created exactly half_life_days ago should decay to 0.5."""
    ts = _ts(DEFAULT_HALF_LIFE_DAYS)
    d = decay_factor(ts, _NOW, DEFAULT_HALF_LIFE_DAYS)
    assert abs(d - 0.5) < 1e-6


def test_decay_factor_two_half_lives():
    """Two half-lives → decay = 0.25."""
    ts = _ts(DEFAULT_HALF_LIFE_DAYS * 2)
    d = decay_factor(ts, _NOW, DEFAULT_HALF_LIFE_DAYS)
    assert abs(d - 0.25) < 1e-6


def test_decay_factor_old_entry_lower_than_new(  ):
    """60-day-old entry decays more than 1-day-old entry."""
    d_new = decay_factor(_ts(1), _NOW, DEFAULT_HALF_LIFE_DAYS)
    d_old = decay_factor(_ts(60), _NOW, DEFAULT_HALF_LIFE_DAYS)
    assert d_old < d_new


def test_decay_factor_invalid_timestamp():
    """Malformed timestamp defaults to age=0 → decay=1.0."""
    d = decay_factor("not-a-date", _NOW, DEFAULT_HALF_LIFE_DAYS)
    assert abs(d - 1.0) < 1e-9


# ---------------------------------------------------------------------------
# bm25_search
# ---------------------------------------------------------------------------

def test_bm25_search_empty_entries():
    assert bm25_search([], "query", now=_NOW) == []


def test_bm25_search_empty_query():
    entries = [_entry("some insight")]
    assert bm25_search(entries, "", now=_NOW) == []


def test_bm25_search_no_match():
    entries = [_entry("ledger idempotency check")]
    results = bm25_search(entries, "genome evolution", now=_NOW)
    assert results == []


def test_bm25_search_single_match():
    entries = [_entry("ledger idempotency check")]
    results = bm25_search(entries, "ledger", now=_NOW)
    assert len(results) == 1
    assert results[0][0]["text"] == "ledger idempotency check"
    assert results[0][1] > 0.0


def test_bm25_search_ranking_by_relevance():
    """Entry with more query-term overlap ranks higher when ages are equal."""
    entries = [
        _entry("ledger idempotency check fix", days_ago=0),          # 2 terms
        _entry("ledger check", days_ago=0),                           # 1 term
        _entry("unrelated content about genome", days_ago=0),         # 0 terms
    ]
    results = bm25_search(entries, "ledger idempotency", now=_NOW)
    # First result should be the most relevant
    assert results[0][0]["text"] == "ledger idempotency check fix"
    # Unrelated entry should not appear
    texts = [r[0]["text"] for r in results]
    assert "unrelated content about genome" not in texts


def test_bm25_search_temporal_decay_breaks_tie():
    """When text is identical, newer entry scores higher."""
    old_entry = _entry("ledger idempotency", days_ago=60)
    new_entry = _entry("ledger idempotency", days_ago=1)
    entries = [old_entry, new_entry]

    results = bm25_search(entries, "ledger idempotency", now=_NOW)
    assert len(results) == 2
    # newer (days_ago=1) should rank above older (days_ago=60)
    assert results[0][0]["id"] == new_entry["id"]
    assert results[0][1] > results[1][1]


def test_bm25_search_top_n_limits_results():
    entries = [_entry(f"ledger insight {i}") for i in range(20)]
    results = bm25_search(entries, "ledger", now=_NOW, top_n=3)
    assert len(results) <= 3


def test_bm25_search_scores_positive():
    entries = [_entry("ledger idempotency check")]
    results = bm25_search(entries, "ledger", now=_NOW)
    for _, score in results:
        assert score > 0.0


# ---------------------------------------------------------------------------
# trim_entries
# ---------------------------------------------------------------------------

def test_trim_no_op_when_under_cap():
    entries = [_entry(f"e{i}") for i in range(5)]
    result = trim_entries(entries, cap=10)
    assert len(result) == 5


def test_trim_removes_oldest_fifo():
    entries = [_entry(f"entry_{i}") for i in range(10)]
    trimmed = trim_entries(entries, cap=3)
    assert len(trimmed) == 3
    # Last 3 entries kept (newest = appended last)
    assert trimmed[0]["text"] == "entry_7"
    assert trimmed[1]["text"] == "entry_8"
    assert trimmed[2]["text"] == "entry_9"


def test_trim_exact_cap():
    entries = [_entry(f"e{i}") for i in range(5)]
    result = trim_entries(entries, cap=5)
    assert len(result) == 5


def test_trim_empty_list():
    assert trim_entries([], cap=10) == []


def test_trim_cap_zero():
    entries = [_entry("x"), _entry("y")]
    result = trim_entries(entries, cap=0)
    assert result == []


# ---------------------------------------------------------------------------
# get_knowledge_context
# ---------------------------------------------------------------------------

def test_get_knowledge_context_empty_base(kb_root: Path):
    ctx = get_knowledge_context(kb_root, AGENT, "ledger")
    assert ctx == ""


def test_get_knowledge_context_no_match(kb_root: Path):
    entries = [_entry("genome evolution principle")]
    save_entries(kb_root, AGENT, entries)
    ctx = get_knowledge_context(kb_root, AGENT, "ledger idempotency")
    assert ctx == ""


def test_get_knowledge_context_returns_section(kb_root: Path):
    entries = [_entry("ledger idempotency check", task_ref=42)]
    save_entries(kb_root, AGENT, entries)
    ctx = get_knowledge_context(kb_root, AGENT, "ledger idempotency")
    assert "## Relevant Knowledge" in ctx
    assert "ledger idempotency check" in ctx
    assert "task #42" in ctx


def test_get_knowledge_context_top_n(kb_root: Path):
    entries = [_entry(f"ledger insight {i}") for i in range(10)]
    save_entries(kb_root, AGENT, entries)
    ctx = get_knowledge_context(kb_root, AGENT, "ledger", top_n=2)
    # Should mention exactly 2 entries
    assert "(2 entries)" in ctx


# ---------------------------------------------------------------------------
# CLI integration (wea knowledge add / search / list / trim)
# ---------------------------------------------------------------------------

def _run_cli(args_list: list[str], root: Path) -> tuple[int, str]:
    """Run wea CLI and capture stdout."""
    import io
    import sys
    from wea_cli import cli as cli_module

    captured = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = captured
    try:
        # Build argv: wea --root <root> knowledge <subcommand> ...
        sys.argv = ["wea", "--root", str(root)] + args_list
        try:
            code = cli_module.main()
        except SystemExit as e:
            code = int(e.code) if e.code is not None else 0
    finally:
        sys.stdout = old_stdout
    return code, captured.getvalue()


def test_cli_knowledge_add(kb_root: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("WEA_AGENT", AGENT)
    code, out = _run_cli(["knowledge", "add", "test insight about ledger"], kb_root)
    assert code == 0
    assert "Added entry" in out
    entries = load_entries(kb_root, AGENT)
    assert len(entries) == 1
    assert entries[0]["text"] == "test insight about ledger"


def test_cli_knowledge_add_with_tags_and_task(kb_root: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("WEA_AGENT", AGENT)
    code, out = _run_cli(
        ["knowledge", "add", "check escrow author field", "--tags", "ledger,escrow", "--task", "109"],
        kb_root,
    )
    assert code == 0
    entries = load_entries(kb_root, AGENT)
    assert entries[0]["tags"] == ["ledger", "escrow"]
    assert entries[0]["task_ref"] == 109


def test_cli_knowledge_search(kb_root: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("WEA_AGENT", AGENT)
    # Seed entries
    entries = [
        _entry("ledger idempotency key check", days_ago=1),
        _entry("genome evolution principle", days_ago=0),
    ]
    save_entries(kb_root, AGENT, entries)

    code, out = _run_cli(["knowledge", "search", "ledger idempotency"], kb_root)
    assert code == 0
    assert "ledger idempotency key check" in out


def test_cli_knowledge_search_no_match(kb_root: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("WEA_AGENT", AGENT)
    save_entries(kb_root, AGENT, [_entry("genome principle")])
    code, out = _run_cli(["knowledge", "search", "totally unrelated query xyz"], kb_root)
    assert code == 0
    assert "No matching" in out


def test_cli_knowledge_list(kb_root: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("WEA_AGENT", AGENT)
    save_entries(kb_root, AGENT, [_entry("ledger insight"), _entry("genome insight")])
    code, out = _run_cli(["knowledge", "list"], kb_root)
    assert code == 0
    assert "ledger insight" in out
    assert "genome insight" in out
    assert "decay=" in out


def test_cli_knowledge_list_empty(kb_root: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("WEA_AGENT", AGENT)
    code, out = _run_cli(["knowledge", "list"], kb_root)
    assert code == 0
    assert "No knowledge entries" in out


def test_cli_knowledge_trim(kb_root: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("WEA_AGENT", AGENT)
    entries = [_entry(f"entry {i}") for i in range(10)]
    save_entries(kb_root, AGENT, entries)

    code, out = _run_cli(["knowledge", "trim", "--cap", "3"], kb_root)
    assert code == 0
    assert "Trimmed 7" in out
    assert len(load_entries(kb_root, AGENT)) == 3


def test_cli_knowledge_trim_nothing_to_trim(kb_root: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("WEA_AGENT", AGENT)
    save_entries(kb_root, AGENT, [_entry("x"), _entry("y")])
    code, out = _run_cli(["knowledge", "trim", "--cap", "50"], kb_root)
    assert code == 0
    assert "Nothing to trim" in out


def test_cli_knowledge_add_no_agent(kb_root: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("WEA_AGENT", raising=False)
    monkeypatch.setattr("wea_cli.config.get_agent_from_file", lambda path=None: None)
    code, out = _run_cli(["knowledge", "add", "some text"], kb_root)
    assert code != 0
    assert "agent not set" in out


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_add_trims_at_cap(kb_root: Path, monkeypatch: pytest.MonkeyPatch):
    """Adding beyond cap trims automatically."""
    monkeypatch.setenv("WEA_AGENT", AGENT)
    entries = [_entry(f"entry {i}") for i in range(DEFAULT_CAP)]
    save_entries(kb_root, AGENT, entries)

    # Add one more
    _run_cli(["knowledge", "add", "overflow entry", "--cap", str(DEFAULT_CAP)], kb_root)
    loaded = load_entries(kb_root, AGENT)
    assert len(loaded) == DEFAULT_CAP
    assert loaded[-1]["text"] == "overflow entry"


def test_bm25_single_entry_base():
    """BM25 with a single entry doesn't divide by zero."""
    entries = [_entry("ledger check")]
    results = bm25_search(entries, "ledger", now=_NOW)
    assert len(results) == 1
    assert results[0][1] > 0.0
