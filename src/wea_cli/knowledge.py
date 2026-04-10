"""Agent knowledge base: BM25 search with temporal decay.

Entries are stored per-agent in knowledge/<slug>/entries.json.
Each entry: {id, text, tags[], task_ref, created_at}.
Search uses BM25+ ranking multiplied by an exponential temporal decay factor.
"""

from __future__ import annotations

import json
import math
import os
import re
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_CAP: int = 50
DEFAULT_HALF_LIFE_DAYS: float = 30.0
DEFAULT_TOP_N: int = 5
# BM25 tuning constants
_K1: float = 1.5
_B: float = 0.75


# ---------------------------------------------------------------------------
# Slug + path helpers
# ---------------------------------------------------------------------------

def agent_slug(agent_id: str) -> str:
    """Convert agent ID to a filesystem-safe lowercase slug.

    Examples:
        "Claude-1@claude"  -> "claude-1-claude"
        "agent0@system"    -> "agent0-system"
    """
    return re.sub(r"[^a-zA-Z0-9_-]", "-", agent_id).lower()


def _entries_path(root: Path, agent_id: str) -> Path:
    return root / "knowledge" / agent_slug(agent_id) / "entries.json"


# ---------------------------------------------------------------------------
# Load / save (atomic writes)
# ---------------------------------------------------------------------------

def load_entries(root: Path, agent_id: str) -> list[dict[str, Any]]:
    """Return entries list; empty list when file does not exist."""
    path = _entries_path(root, agent_id)
    if not path.exists():
        return []
    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw)
    return data if isinstance(data, list) else []


def save_entries(root: Path, agent_id: str, entries: list[dict[str, Any]]) -> None:
    """Atomically write entries to knowledge/<slug>/entries.json."""
    path = _entries_path(root, agent_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(entries, indent=2, ensure_ascii=False).encode("utf-8")
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        os.write(fd, payload)
        os.close(fd)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Entry construction
# ---------------------------------------------------------------------------

def make_entry(
    text: str,
    tags: list[str] | None = None,
    task_ref: int | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Create a new knowledge entry dict."""
    ts = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "id": str(uuid.uuid4()),
        "text": text.strip(),
        "tags": tags or [],
        "task_ref": task_ref,
        "created_at": ts,
    }


# ---------------------------------------------------------------------------
# BM25 + temporal decay
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _age_days(created_at: str, now: datetime) -> float:
    """Return age in fractional days; 0.0 on parse error."""
    try:
        created = datetime.strptime(created_at, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return 0.0
    delta = (now - created).total_seconds()
    return max(0.0, delta) / 86400.0


def decay_factor(created_at: str, now: datetime, half_life_days: float) -> float:
    """Exponential half-life decay: 0.5 ^ (age_days / half_life_days)."""
    age = _age_days(created_at, now)
    return math.pow(0.5, age / half_life_days)


def bm25_search(
    entries: list[dict[str, Any]],
    query: str,
    now: datetime | None = None,
    top_n: int = DEFAULT_TOP_N,
    half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
    k1: float = _K1,
    b: float = _B,
) -> list[tuple[dict[str, Any], float]]:
    """Return top-N (entry, score) pairs ranked by BM25 * temporal decay.

    Score is always > 0 for entries that share at least one query term.
    Returns an empty list when entries or query are empty.
    """
    if not entries or not query.strip():
        return []

    now = now or datetime.now(timezone.utc)
    query_terms = _tokenize(query)
    if not query_terms:
        return []

    tokenized: list[list[str]] = [_tokenize(e.get("text", "")) for e in entries]
    n = len(entries)
    avgdl = sum(len(d) for d in tokenized) / n if n else 1.0

    # Document frequency: how many docs contain each term
    df: dict[str, int] = {}
    for doc in tokenized:
        for term in set(doc):
            df[term] = df.get(term, 0) + 1

    def idf(term: str) -> float:
        n_t = df.get(term, 0)
        # BM25+ IDF formula (avoids negative IDF)
        return math.log((n - n_t + 0.5) / (n_t + 0.5) + 1.0)

    scored: list[tuple[dict[str, Any], float]] = []
    for entry, doc_tokens in zip(entries, tokenized):
        dl = len(doc_tokens)
        tf_map: dict[str, int] = {}
        for t in doc_tokens:
            tf_map[t] = tf_map.get(t, 0) + 1

        raw_score = 0.0
        for term in query_terms:
            tf = tf_map.get(term, 0)
            if tf == 0:
                continue
            numerator = tf * (k1 + 1.0)
            denominator = tf + k1 * (1.0 - b + b * dl / max(avgdl, 1.0))
            raw_score += idf(term) * numerator / denominator

        if raw_score > 0.0:
            d = decay_factor(entry["created_at"], now, half_life_days)
            scored.append((entry, raw_score * d))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_n]


# ---------------------------------------------------------------------------
# Trim
# ---------------------------------------------------------------------------

def trim_entries(entries: list[dict[str, Any]], cap: int = DEFAULT_CAP) -> list[dict[str, Any]]:
    """FIFO trim: drop oldest entries (lowest indices) until len <= cap."""
    if len(entries) <= cap:
        return entries
    return entries[len(entries) - cap :]


# ---------------------------------------------------------------------------
# Pipeline injection helper
# ---------------------------------------------------------------------------

def get_knowledge_context(
    root: Path,
    agent_id: str,
    query: str,
    top_n: int = DEFAULT_TOP_N,
    half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
) -> str:
    """Return a formatted knowledge section for pipeline prompt injection.

    Returns empty string when no relevant entries are found.
    """
    entries = load_entries(root, agent_id)
    if not entries:
        return ""

    results = bm25_search(
        entries, query, top_n=top_n, half_life_days=half_life_days
    )
    if not results:
        return ""

    lines = [f"## Relevant Knowledge ({len(results)} entries)\n"]
    for i, (entry, score) in enumerate(results, 1):
        task_note = f" [task #{entry['task_ref']}]" if entry.get("task_ref") else ""
        tags_note = f" [{', '.join(entry['tags'])}]" if entry.get("tags") else ""
        lines.append(f"{i}. {entry['text']}{task_note}{tags_note}")
        lines.append(f"   score={score:.4f}  created={entry['created_at']}")
    return "\n".join(lines) + "\n"
