#!/usr/bin/env python3
"""
Diary censorship tool.

Transforms raw diary entries (agent0_diary_raw/) into public censored versions
(agent0_diary/) by replacing sensitive internal vocabulary with variable-length
redaction blocks.

The redacted length varies ±1–2 characters from the original word length,
so pattern analysis cannot reliably recover the source term.

Usage:
    # Censor a single file:
    python scripts/censor_diary.py agent0_diary_raw/2026-03-09.md

    # Censor all raw diaries into agent0_diary/:
    python scripts/censor_diary.py --all

    # Dry run (print to stdout, don't write):
    python scripts/censor_diary.py agent0_diary_raw/2026-03-09.md --dry-run

    # Check if a file has any sensitive terms:
    python scripts/censor_diary.py --check agent0_diary/2026-03-09.md
"""

import argparse
import hashlib
import re
import sys
from pathlib import Path

BLOCK = "\u2588"  # █

RAW_DIR = Path("agent0_diary_raw")
PUBLIC_DIR = Path("agent0_diary")

# ---------------------------------------------------------------------------
# Sensitive term list — exact patterns to redact (word-boundary matched)
# ---------------------------------------------------------------------------

# Each entry: (pattern_str, case_sensitive)
# Ordered longest-first to avoid partial matches being shadowed.
_TERMS: list[tuple[str, bool]] = [
    # Filenames — literal, case-sensitive
    (r"AGENTS\.local(?:\.md)?", True),
    (r"genome_snapshot", False),
    (r"genome_meta", False),
    (r"genome_log", False),
    # Biology vocabulary — word-boundary, case-insensitive
    (r"\bgenomics?\b", False),
    (r"\bgenomic\b", False),
    (r"\bgenome[s]?\b", False),
    (r"\bgenotyp(?:e|es|ic)\b", False),
    (r"\bphenotyp(?:e|es|ic)\b", False),
    (r"\bchromosome[s]?\b", False),
    (r"\bhereditar[yi]\b", False),
    (r"\bheredity\b", False),
    (r"\bgenetic[s]?\b", False),
    (r"\bgenes?\b", False),          # gene, genes — not generate, general
    (r"\bmutati(?:on|ons|ng|ed|e)s?\b", False),
    (r"\bmutate[ds]?\b", False),
    (r"\b[Dd][Nn][Aa]\b", True),
]

# Compile all patterns into a single alternation for efficiency.
_MASTER_RE = re.compile(
    "|".join(f"(?:{pat})" for pat, cs in _TERMS),
    re.IGNORECASE,
)


def _redact_length(original: str, seed: str) -> int:
    """
    Return a redacted block length that is original length +0, +1, or +2.
    Never shorter than the original — avoids suspiciously short masks on
    short words like "gene" (4 chars).
    Uses a deterministic seed so the same word in the same file always gets
    the same mask length (stable diffs), but varies across files.
    """
    h = int(hashlib.sha256(seed.encode()).hexdigest(), 16)
    delta = h % 3  # 0, +1, +2
    return len(original) + delta


def censor_text(text: str, source_hint: str = "") -> tuple[str, list[str]]:
    """
    Replace all sensitive terms with variable-length block masks.

    Returns (censored_text, list_of_found_terms).
    """
    found: list[str] = []
    offset = 0
    result = []

    for m in _MASTER_RE.finditer(text):
        result.append(text[offset : m.start()])
        term = m.group(0)
        found.append(term)
        seed = f"{source_hint}:{m.start()}:{term.lower()}"
        length = _redact_length(term, seed)
        result.append(BLOCK * length)
        offset = m.end()

    result.append(text[offset:])
    return "".join(result), found


def censor_file(src: Path, dst: Path, dry_run: bool = False) -> list[str]:
    """Censor src and write to dst. Returns list of redacted terms."""
    raw = src.read_text(encoding="utf-8")
    censored, found = censor_text(raw, source_hint=src.name)

    if dry_run:
        print(censored)
    else:
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(censored, encoding="utf-8")

    return found


def check_file(path: Path) -> list[tuple[int, str]]:
    """Return (line_no, matched_term) pairs for any sensitive terms found."""
    hits: list[tuple[int, str]] = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        for m in _MASTER_RE.finditer(line):
            hits.append((i, m.group(0)))
    return hits


def _resolve_dst(src: Path) -> Path:
    """Map raw path → public path."""
    if src.is_relative_to(RAW_DIR):
        return PUBLIC_DIR / src.relative_to(RAW_DIR)
    # If called on an arbitrary path, put output next to source with _censored suffix
    return src.with_stem(src.stem + "_censored")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("files", nargs="*", type=Path, help="Raw diary file(s) to censor")
    parser.add_argument("--all", action="store_true", help="Censor all files in agent0_diary_raw/")
    parser.add_argument("--dry-run", action="store_true", help="Print censored output to stdout, do not write")
    parser.add_argument("--check", action="store_true", help="Check files for sensitive terms (exit 1 if found)")
    args = parser.parse_args()

    if args.check:
        # Check mode: scan public dir for leaked terms
        targets = args.files if args.files else sorted(PUBLIC_DIR.glob("*.md"))
        any_hit = False
        for path in targets:
            hits = check_file(path)
            for lineno, term in hits:
                print(f"{path}:{lineno}: found sensitive term \"{term}\"")
                any_hit = True
        if any_hit:
            print("\nFAIL — sensitive vocabulary detected in public diary.")
            return 1
        print("OK — no sensitive vocabulary found.")
        return 0

    if args.all:
        sources = sorted(RAW_DIR.glob("*.md"))
    else:
        sources = args.files

    if not sources:
        parser.print_help()
        return 1

    total_found: list[str] = []
    for src in sources:
        dst = _resolve_dst(src)
        found = censor_file(src, dst, dry_run=args.dry_run)
        if found:
            label = "(dry-run) " if args.dry_run else ""
            print(f"{label}{src} → {dst}: redacted {len(found)} term(s): {', '.join(set(found))}")
        else:
            print(f"{src} → {dst}: clean (no sensitive terms)")
        total_found.extend(found)

    if total_found:
        print(f"\nTotal: {len(total_found)} redaction(s) across {len(sources)} file(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
