"""Fangraphs RosterResource probable-pitcher snapshots.

Best effort:
  * fetch raw HTML from FanGraphs
  * detect Cloudflare / challenge responses
  * parse a probables grid-like HTML table into normalized snapshot rows

The parser is intentionally table-oriented so it can also ingest manually
saved HTML snapshots when direct fetching is blocked.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pandas as pd
from bs4 import BeautifulSoup, Tag

from data.fetch_2026.io_safety import append_audit, atomic_write_text, safe_write_parquet
from data.fetch_2026.team_mapping import normalize_team

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / "data" / "raw" / "bullpen_signal" / "fangraphs"
PROCESSED_PATH = BASE_DIR / "data" / "processed" / "bullpen_signal" / "fangraphs_probable_snapshots.parquet"

FANGRAPHS_URL = "https://www.fangraphs.com/roster-resource/probables-grid"
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

DATE_RE = re.compile(r"(?<!\d)(\d{1,2})/(\d{1,2})(?!\d)")
HAND_SUFFIX_RE = re.compile(r"\s+\(([RLS])\)\s*$", re.IGNORECASE)
WS_RE = re.compile(r"\s+")
CF_MARKERS = (
    "Just a moment...",
    "Enable JavaScript and cookies to continue",
    "challenge-error-text",
    "cf_chl_opt",
)

FULL_NAME_TO_CODE = {
    "arizona diamondbacks": "ARI",
    "atlanta braves": "ATL",
    "baltimore orioles": "BAL",
    "boston red sox": "BOS",
    "chicago cubs": "CHC",
    "chicago white sox": "CHW",
    "cincinnati reds": "CIN",
    "cleveland guardians": "CLE",
    "colorado rockies": "COL",
    "detroit tigers": "DET",
    "houston astros": "HOU",
    "kansas city royals": "KCR",
    "los angeles angels": "LAA",
    "los angeles dodgers": "LAD",
    "miami marlins": "MIA",
    "milwaukee brewers": "MIL",
    "minnesota twins": "MIN",
    "new york mets": "NYM",
    "new york yankees": "NYY",
    "athletics": "OAK",
    "oakland athletics": "OAK",
    "sacramento athletics": "OAK",
    "philadelphia phillies": "PHI",
    "pittsburgh pirates": "PIT",
    "san diego padres": "SDP",
    "san francisco giants": "SFG",
    "seattle mariners": "SEA",
    "st. louis cardinals": "STL",
    "st louis cardinals": "STL",
    "tampa bay rays": "TBR",
    "texas rangers": "TEX",
    "toronto blue jays": "TOR",
    "washington nationals": "WSN",
}


def normalize_pitcher_name(name: str | None) -> str:
    """Normalize a pitcher name for cross-source matching."""
    if not name:
        return ""
    text = WS_RE.sub(" ", str(name).strip())
    text = HAND_SUFFIX_RE.sub("", text)
    text = text.replace(".", "")
    text = "".join(
        ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch)
    )
    text = text.casefold()
    return text


def normalize_team_label(label: str | None) -> str | None:
    """Convert a Fangraphs team label to our canonical code."""
    if not label:
        return None
    text = WS_RE.sub(" ", str(label).strip())
    if not text:
        return None

    upper = text.upper()
    try:
        return normalize_team(upper)
    except KeyError:
        pass

    return FULL_NAME_TO_CODE.get(text.casefold())


def _is_cloudflare_challenge(html: str) -> bool:
    sample = html[:4000]
    return any(marker in sample for marker in CF_MARKERS)


def fetch_fangraphs_html(*, timeout: int = 30) -> str:
    """Fetch the raw Fangraphs probables-grid HTML.

    Raises RuntimeError if FanGraphs returns a Cloudflare challenge page.
    """
    response = httpx.get(
        FANGRAPHS_URL,
        headers=DEFAULT_HEADERS,
        timeout=timeout,
        follow_redirects=True,
    )
    html = response.text
    if response.status_code >= 400 and _is_cloudflare_challenge(html):
        raise RuntimeError("FanGraphs returned a Cloudflare challenge page")
    response.raise_for_status()
    if _is_cloudflare_challenge(html):
        raise RuntimeError("FanGraphs returned a Cloudflare challenge page")
    return html


def save_raw_fangraphs_snapshot(html: str, *, captured_at: datetime) -> Path:
    """Persist the raw HTML snapshot and return its path."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    stamp = captured_at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = RAW_DIR / f"fangraphs_probables_{stamp}.html"
    atomic_write_text(html, path)
    append_audit(
        "fangraphs_probables_capture",
        target_date=captured_at.date(),
        files_written=[path.name],
    )
    return path


def _extract_dates_from_row(row: Tag, *, year: int) -> list[date]:
    out: list[date] = []
    for cell in row.find_all(["th", "td"]):
        text = WS_RE.sub(" ", cell.get_text(" ", strip=True))
        match = DATE_RE.search(text)
        if not match:
            continue
        month, day = (int(match.group(1)), int(match.group(2)))
        out.append(date(year, month, day))
    return out


def _select_grid_table(soup: BeautifulSoup, *, year: int) -> tuple[Tag, list[date]] | None:
    """Return the most likely probables table and its date columns."""
    best: tuple[Tag, list[date]] | None = None
    best_score = -1

    for table in soup.find_all("table"):
        dates: list[date] = []
        for row in table.find_all("tr"):
            row_dates = _extract_dates_from_row(row, year=year)
            if len(row_dates) > len(dates):
                dates = row_dates
        score = len(dates)
        if score > best_score:
            best = (table, dates)
            best_score = score

    if best_score <= 0:
        return None
    return best


def _extract_probable_name(cell: Tag) -> str:
    """Extract a probable pitcher's display name from one grid cell."""
    links = [
        WS_RE.sub(" ", a.get_text(" ", strip=True))
        for a in cell.find_all("a")
        if WS_RE.sub(" ", a.get_text(" ", strip=True))
    ]
    for text in links:
        if " " in text and not DATE_RE.search(text):
            return text

    text = WS_RE.sub(" ", cell.get_text(" ", strip=True))
    if not text or text.upper() == "OFF":
        return ""
    if "TBD" in text.upper():
        return ""

    match = re.search(
        r"([A-Z][A-Za-z'`\.-]+(?: [A-Z][A-Za-z'`\.-]+)+(?: \([RLS]\))?)",
        text,
    )
    if match:
        return match.group(1)

    return ""


def parse_fangraphs_probables_html(
    html: str,
    *,
    captured_at: datetime | None = None,
    source_url: str = FANGRAPHS_URL,
    snapshot_id: str | None = None,
    year: int | None = None,
) -> pd.DataFrame:
    """Parse a Fangraphs probables-grid HTML snapshot into normalized rows."""
    captured_at = captured_at or datetime.now(UTC)
    if captured_at.tzinfo is None:
        captured_at = captured_at.replace(tzinfo=UTC)
    if snapshot_id is None:
        snapshot_id = captured_at.astimezone(UTC).strftime("fangraphs_%Y%m%dT%H%M%SZ")

    soup = BeautifulSoup(html, "html.parser")
    inferred_year = year
    if inferred_year is None:
        title = WS_RE.sub(" ", soup.get_text(" ", strip=True))
        year_match = re.search(r"\b(20\d{2})\b", title)
        inferred_year = int(year_match.group(1)) if year_match else captured_at.year

    table_info = _select_grid_table(soup, year=inferred_year)
    if table_info is None:
        raise ValueError("Could not locate a Fangraphs probables grid table")

    table, header_dates = table_info
    rows: list[dict[str, object]] = []

    body_rows = table.find_all("tr")
    for row in body_rows:
        cells = row.find_all(["th", "td"])
        if len(cells) < 2:
            continue
        team = normalize_team_label(cells[0].get_text(" ", strip=True))
        if not team:
            continue

        for target_date, cell in zip(header_dates, cells[1:], strict=False):
            cell_text = WS_RE.sub(" ", cell.get_text(" ", strip=True))
            if not cell_text or cell_text.upper() == "OFF":
                continue
            probable_raw = _extract_probable_name(cell)
            rows.append(
                {
                    "captured_at_utc": captured_at.astimezone(UTC),
                    "target_date": pd.Timestamp(target_date),
                    "team": team,
                    "source": "fangraphs",
                    "probable_name_raw": probable_raw,
                    "probable_name_norm": normalize_pitcher_name(probable_raw),
                    "is_blank": probable_raw == "",
                    "source_url": source_url,
                    "snapshot_id": snapshot_id,
                }
            )

    return pd.DataFrame(rows)


def persist_fangraphs_rows(rows: pd.DataFrame) -> Path | None:
    """Append parsed Fangraphs snapshot rows to the consolidated parquet."""
    if rows.empty:
        return None

    PROCESSED_PATH.parent.mkdir(parents=True, exist_ok=True)
    existing = pd.read_parquet(PROCESSED_PATH) if PROCESSED_PATH.exists() else pd.DataFrame()
    combined = pd.concat([existing, rows], ignore_index=True, sort=False)
    combined = combined.drop_duplicates(
        subset=["snapshot_id", "target_date", "team", "source"],
        keep="last",
    )
    safe_write_parquet(
        combined,
        PROCESSED_PATH,
        generator="fangraphs_probables.persist_fangraphs_rows",
        date_col="target_date",
        backup=False,
        audit_action="save_fangraphs_probables",
    )
    return PROCESSED_PATH
