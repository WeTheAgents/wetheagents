"""Atomic IO + backup + sidecar helpers for the 2026 data pipeline.

Every parquet write goes through these helpers so a crashed process or a
buggy merge can never silently destroy state. They:

1. Write to a `.tmp` file then atomic-rename — never leave a half-written
   parquet/text file at the destination path.
2. Optionally back up the existing file to `data/backups/YYYY-MM-DD/` before
   overwrite. Backups older than `BACKUP_RETENTION_DAYS` are pruned.
3. Optionally write a `<file>.meta.json` sidecar with row count, date range,
   generator name, and timestamp. The daily health check compares actual
   parquet contents against the sidecar to catch silent regressions.
4. Append a one-line entry to `data/fetch_2026/audit_log.jsonl` describing
   the action. The audit log is append-only and never rotated — it's the
   forensic trail for "where did my data go?" investigations.
"""

from __future__ import annotations

import json
import logging
import shutil
from collections.abc import Iterable, Mapping
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

# data/fetch_2026/io_safety.py → data/
BASE_DIR = Path(__file__).resolve().parent.parent
BACKUPS_DIR = BASE_DIR / "backups"
AUDIT_LOG = Path(__file__).parent / "audit_log.jsonl"
BACKUP_RETENTION_DAYS = 14


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _today_str() -> str:
    return date.today().strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Atomic writes
# ---------------------------------------------------------------------------


def atomic_write_parquet(df: pd.DataFrame, path: Path) -> None:
    """Write a parquet via tmp file + rename. Never leaves a partial file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    df.to_parquet(tmp, index=False)
    tmp.replace(path)


def atomic_write_text(text: str, path: Path, *, encoding: str = "utf-8") -> None:
    """Write text via tmp file + rename. Use for state.json, sidecars, caches."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding=encoding)
    tmp.replace(path)


def atomic_write_xlsx(df: pd.DataFrame, path: Path, **to_excel_kwargs) -> None:
    """Write an xlsx via tmp file + rename."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    df.to_excel(tmp, **to_excel_kwargs)
    tmp.replace(path)


# ---------------------------------------------------------------------------
# Backups
# ---------------------------------------------------------------------------


def backup_existing(path: Path) -> Path | None:
    """Copy the existing file (if any) to data/backups/YYYY-MM-DD/<name>.

    Returns the backup path, or None if the source did not exist.
    Idempotent within a day: re-running overwrites the same day's backup.
    """
    path = Path(path)
    if not path.exists():
        return None
    day_dir = BACKUPS_DIR / _today_str()
    day_dir.mkdir(parents=True, exist_ok=True)
    dest = day_dir / path.name
    shutil.copy2(path, dest)
    # Also back up sidecar if present.
    sidecar = path.with_suffix(path.suffix + ".meta.json")
    if sidecar.exists():
        shutil.copy2(sidecar, day_dir / sidecar.name)
    return dest


def prune_old_backups(retention_days: int = BACKUP_RETENTION_DAYS) -> int:
    """Drop backup directories older than retention_days. Returns count removed."""
    if not BACKUPS_DIR.exists():
        return 0
    today = date.today()
    removed = 0
    for d in sorted(BACKUPS_DIR.iterdir()):
        if not d.is_dir():
            continue
        try:
            day = date.fromisoformat(d.name)
        except ValueError:
            continue
        if (today - day).days > retention_days:
            shutil.rmtree(d)
            removed += 1
    return removed


# ---------------------------------------------------------------------------
# Sidecar metadata
# ---------------------------------------------------------------------------


def write_sidecar(
    path: Path,
    df: pd.DataFrame,
    *,
    generator: str,
    date_col: str | None = "date",
    schema_version: int = 1,
    extra: Mapping[str, object] | None = None,
) -> Path:
    """Write a `<file>.meta.json` sidecar with row count, date range, provenance."""
    path = Path(path)
    meta: dict[str, object] = {
        "rows": int(len(df)),
        "schema_version": schema_version,
        "generator": generator,
        "written_at": _now_iso(),
    }
    if date_col and date_col in df.columns and len(df):
        try:
            dates = pd.to_datetime(df[date_col], errors="coerce").dropna()
            if len(dates):
                meta["date_min"] = dates.min().strftime("%Y-%m-%d")
                meta["date_max"] = dates.max().strftime("%Y-%m-%d")
        except (TypeError, ValueError) as e:
            logger.debug("sidecar date range skipped for %s: %s", path.name, e)
    if extra:
        meta.update(dict(extra))
    sidecar = path.with_suffix(path.suffix + ".meta.json")
    atomic_write_text(json.dumps(meta, indent=2), sidecar)
    return sidecar


def read_sidecar(path: Path) -> dict | None:
    """Load the sidecar for a parquet file, or None if missing/invalid."""
    sidecar = Path(path).with_suffix(Path(path).suffix + ".meta.json")
    if not sidecar.exists():
        return None
    try:
        return json.loads(sidecar.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------


def append_audit(
    action: str,
    *,
    target_date: str | date | None = None,
    rows_added: int | None = None,
    rows_total: int | None = None,
    files_written: Iterable[str] | None = None,
    extra: Mapping[str, object] | None = None,
) -> None:
    """Append a structured one-line entry to audit_log.jsonl. Never overwrites."""
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    entry: dict[str, object] = {
        "ts": _now_iso(),
        "action": action,
    }
    if target_date is not None:
        entry["date"] = str(target_date)
    if rows_added is not None:
        entry["rows_added"] = int(rows_added)
    if rows_total is not None:
        entry["rows_total"] = int(rows_total)
    if files_written:
        entry["files_written"] = list(files_written)
    if extra:
        entry.update(dict(extra))
    with AUDIT_LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")


# ---------------------------------------------------------------------------
# High-level entry point: every parquet write site should call this.
# ---------------------------------------------------------------------------


def safe_write_parquet(
    df: pd.DataFrame,
    path: Path,
    *,
    generator: str,
    date_col: str | None = "date",
    backup: bool = True,
    audit_action: str | None = None,
    audit_extra: Mapping[str, object] | None = None,
) -> None:
    """Backup → atomic write → sidecar → audit log. Single safe-write entry point.

    Use `backup=False` only for files that are derived/recomputed every run
    and where losing the previous version is not a problem.
    """
    path = Path(path)
    if backup:
        backup_existing(path)
    atomic_write_parquet(df, path)
    write_sidecar(path, df, generator=generator, date_col=date_col)
    if audit_action:
        append_audit(
            audit_action,
            rows_total=len(df),
            files_written=[path.name],
            extra=audit_extra,
        )
