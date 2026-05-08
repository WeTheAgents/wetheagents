"""Enrich new entries in telegram_queue.jsonl with GitHub repo metadata.

Reads queue, for every `status=="new"` entry:
  - Classifies each URL (github_repo / other)
  - For github_repo: fetches stars, description, primary language, pushed_at, readme_head
  - Rewrites entry with enrichment + `status="enriched"`

Leaves triage decision to Agent0 (heartbeat Phase 3f reads enriched entries
and records outcomes to telegram_decisions.jsonl).

Usage:
  python scripts/telegram_scout.py
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INBOX_DIR = REPO_ROOT / "agent0" / "inbox"
QUEUE_FILE = INBOX_DIR / "telegram_queue.jsonl"

GITHUB_REPO_RE = re.compile(
    r"^https?://github\.com/([^/\s]+)/([^/\s#?]+)(?:[/?#].*)?$",
    re.IGNORECASE,
)


def classify(url: str) -> tuple[str, dict]:
    m = GITHUB_REPO_RE.match(url)
    if m:
        owner, repo = m.group(1), m.group(2).removesuffix(".git")
        return "github_repo", {"owner": owner, "repo": repo}
    return "other", {}


def gh_api(path: str) -> dict | None:
    try:
        out = subprocess.run(
            ["gh", "api", path],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        if out.returncode != 0:
            return {"error": out.stderr.strip()[:200]}
        return json.loads(out.stdout)
    except Exception as e:
        return {"error": str(e)[:200]}


def enrich_github(owner: str, repo: str) -> dict:
    info = gh_api(f"repos/{owner}/{repo}") or {}
    if "error" in info:
        return {"error": info["error"]}
    readme = gh_api(f"repos/{owner}/{repo}/readme") or {}
    readme_head = ""
    if readme and "content" in readme:
        try:
            import base64
            raw = base64.b64decode(readme["content"]).decode("utf-8", errors="replace")
            readme_head = raw[:1200]
        except Exception:
            readme_head = ""
    return {
        "full_name": info.get("full_name"),
        "description": info.get("description"),
        "language": info.get("language"),
        "stars": info.get("stargazers_count"),
        "forks": info.get("forks_count"),
        "pushed_at": info.get("pushed_at"),
        "archived": info.get("archived"),
        "license": (info.get("license") or {}).get("spdx_id"),
        "topics": info.get("topics", []),
        "readme_head": readme_head,
    }


def enrich_entry(entry: dict) -> dict:
    enriched_urls: list[dict] = []
    for url in entry["urls"]:
        kind, ctx = classify(url)
        item: dict = {"url": url, "kind": kind}
        if kind == "github_repo":
            item["meta"] = enrich_github(ctx["owner"], ctx["repo"])
        enriched_urls.append(item)
    entry["urls_enriched"] = enriched_urls
    entry["status"] = "enriched"
    return entry


def main() -> int:
    if not QUEUE_FILE.exists():
        print("telegram_scout: no queue file, nothing to do")
        return 0

    lines = QUEUE_FILE.read_text(encoding="utf-8").splitlines()
    entries = [json.loads(l) for l in lines if l.strip()]
    changed = 0
    for e in entries:
        if e.get("status") == "new":
            enrich_entry(e)
            changed += 1
    if changed:
        with QUEUE_FILE.open("w", encoding="utf-8") as f:
            for e in entries:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
    pending = sum(1 for e in entries if e.get("status") == "enriched")
    print(f"telegram_scout: enriched={changed} pending_triage={pending}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
