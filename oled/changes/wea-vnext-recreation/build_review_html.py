# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "beautifulsoup4==4.14.3",
#   "markdown-it-py==3.0.0",
# ]
# ///

# The builder embeds Russian prose plus self-contained HTML, CSS, and JavaScript.
# ruff: noqa: E501, RUF001

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from bs4 import BeautifulSoup
from bs4.element import NavigableString
from markdown_it import MarkdownIt

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "WEA_vNext_REVIEW.html"
BASE_SHA = "882a063"
PACKAGE_REVISION = "1.2"
DOMAIN_ACCESS_SPEC_REVISION = "1.0"
DESIGN_REVISION = "1.1"
MIGRATION_REVISION = "1.2"
DELTA_REVISION = "1.2"
TASKS_REVISION = "1.3"


@dataclass(frozen=True)
class Document:
    slug: str
    filename: str
    nav_title: str | None
    eyebrow: str


DOCUMENTS = (
    Document("handoff", "HANDOFF.md", "Следующая сессия", "Требует внимания"),
    Document(
        "domain-access-decision",
        "domain-access-proposal.md",
        "Решение Domain/Access",
        "Принятое решение",
    ),
    Document("tasks", "tasks.md", "План реализации", "Следующие задачи"),
    Document("design", "design.md", "Как это устроить", "Техническое решение"),
    Document("outcome", "outcome.md", "Что строим", "Коротко"),
    Document("spec", "spec.md", "Утверждённое поведение", "Сценарии"),
    Document(
        "bdd-contract-rewrite",
        "bdd-contract-rewrite.md",
        "Решения BDD",
        "Журнал принятых различий",
    ),
    Document("schema", "schema.md", "Записи и инварианты", "Техническое приложение"),
    Document("migration", "migration.md", "Миграция", "Техническое приложение"),
    Document("delta", "delta.md", "Что меняется", "Техническое приложение"),
    Document("decisions", "open-decisions.md", None, "Отложенные вопросы"),
    Document("evidence", "evidence.md", "Источники", "Аудит происхождения"),
    Document("verification", "verification.md", "Проверка", "Техническое приложение"),
)

SUPPORTING_SOURCES = (ROOT / "sources" / "WEA_RESTART_HANDOFF_2026-07-14.md",)
SOURCE_SNAPSHOT_SHA256 = (
    "4ECEC24E8CAE4F915825E1536A346E4C6462FAC94A79EE5659C7D96B75322F14"
)
SOURCE_ORIGINAL_SHA256 = (
    "6D39F389D763D09BE0D7BAFAF0E9A7B92C26270FE3A50A580BD755171A930416"
)

MARKDOWN = (
    MarkdownIt("commonmark", {"html": False, "linkify": False, "typographer": False})
    .enable("table")
    .enable("strikethrough")
)

SOURCE_TAGS = {
    "CHAT": ("Предметно обсуждено и одобрено в этом чате", "chat"),
    "DOC": ("Следует из существующей документации", "doc"),
    "CODE@c703f5e": ("Следует из кода на c703f5e", "code"),
    "CHECK": ("Подтверждено свежей командой или проверкой", "check"),
    "REVIEW": ("Вывод независимого рецензента этого пакета", "review"),
    "DERIVED": ("Техническое следствие одобренных правил", "derived"),
}
SOURCE_EVIDENCE_ANCHORS = {
    "CHAT": "evidence-chat",
    "DOC": "evidence-doc",
    "CODE@c703f5e": "evidence-code-c703f5e",
    "CHECK": "evidence-check",
    "REVIEW": "evidence-review",
    "DERIVED": "evidence-derived",
}
SOURCE_TAG_PATTERN = re.compile(r"\[(CHAT|DOC|CODE@c703f5e|CHECK|REVIEW|DERIVED)\]")
OD_PATTERN = re.compile(r"\bOD-(\d{2})\b")
CURRENT_DECISION_IDS = set(
    re.findall(
        r"^\|\s*(OD-\d{2})\s*\|",
        (ROOT / "open-decisions.md").read_text(encoding="utf-8"),
        re.MULTILINE,
    )
)

VERSION_MARKERS = {
    "HANDOFF.md": (
        r"Status: `([^`]+)`",
        "Block 9 Spec 1.1 and Design 1.3 select a real canonical private pilot;\n"
        "active Tasks 2.2 has no hash gate; GitHub-native writer implementation is next",
    ),
    "open-decisions.md": (r"Статус кандидата `([^`]+)`", PACKAGE_REVISION),
    "outcome.md": (r"\| (1\.2) \| 2026-08-17", PACKAGE_REVISION),
    "spec.md": (
        r"# WEA vNext: поведение кандидата ([0-9.]+)",
        DOMAIN_ACCESS_SPEC_REVISION,
    ),
    "design.md": (r"Статус: `design ([^`]+)`", DESIGN_REVISION),
    "tasks.md": (r"`tasks ([^`]+)`", TASKS_REVISION),
    "schema.md": (r"Статус: `schema ([^`]+)`", DESIGN_REVISION),
    "migration.md": (
        r"Статус: `migration decision overlay ([^`]+)`",
        MIGRATION_REVISION,
    ),
    "delta.md": (r"Статус: `decision delta ([^`]+)`", DELTA_REVISION),
    "verification.md": (
        r"# WEA vNext: Domain/Access verification ([0-9.]+)",
        DOMAIN_ACCESS_SPEC_REVISION,
    ),
}


def current_decision(verification: str) -> str:
    match = re.search(r"^Decision: `([^`]+)`\.$", verification, re.MULTILINE)
    return match.group(1) if match else ""


def validate_package_contract() -> None:
    errors: list[str] = []
    texts: dict[str, str] = {}
    for filename, (pattern, expected) in VERSION_MARKERS.items():
        text = (ROOT / filename).read_text(encoding="utf-8")
        texts[filename] = text
        match = re.search(pattern, text)
        if not match:
            errors.append(f"{filename}: version marker is missing")
        elif match.group(1) != expected:
            errors.append(f"{filename}: version {match.group(1)!r} != {expected!r}")

    verification = texts.get("verification.md", "")
    decisions = texts.get("open-decisions.md", "")
    tasks = texts.get("tasks.md", "")
    handoff = texts.get("HANDOFF.md", "")
    evidence = (ROOT / "evidence.md").read_text(encoding="utf-8")
    decision = current_decision(verification)
    current_block9_overlay = (
        "Block 9 Spec 1.1 and Design 1.3 select a real canonical private pilot"
        in handoff
    )
    spec_implementation_review_pending = (
        decision
        == "Domain/Access implementation verified — independent PR review pending"
    )
    spec_implementation_review_clean = (
        decision == "Domain/Access implementation verified — independent PR review clean"
    )
    spec_reconciliation_complete = decision == "Ready after Spec 0.9 reconciliation"
    spec_reconciliation_pending = (
        decision == "Not ready — Spec 0.9 reconciliation pending"
    )
    bdd_rewrite_pending = decision == "Not ready — BDD rewrite pending"
    block_four_complete = decision == "Ready after Block 4"
    block_four_implemented = (
        current_block9_overlay
        or spec_implementation_review_pending
        or spec_implementation_review_clean
        or spec_reconciliation_complete
        or spec_reconciliation_pending
        or bdd_rewrite_pending
        or block_four_complete
    )
    block_three_complete = block_four_implemented or "Ready for Block 4" in verification
    block_two_complete = block_three_complete or "Ready for Block 3" in verification
    block_one_complete = block_two_complete or "Ready for Block 2" in verification
    if current_block9_overlay:
        if "Not live" not in verification:
            errors.append("verification.md: live-runtime boundary is missing")
        if (
            "registry is 70 current / 9 accepted-future / 0 proposed-future"
            not in tasks
        ):
            errors.append("tasks.md: current Block 9 scenario overlay is missing")
        if "OD-28 и OD-29 закрыты" not in decisions:
            errors.append("open-decisions.md: accepted Block 9 decisions are missing")
        if "BDD alignment: 100%" not in verification:
            errors.append("verification.md: retained BDD alignment is missing")
    elif spec_implementation_review_pending:
        if "Not live" not in verification:
            errors.append("verification.md: live-runtime boundary is missing")
        if "tasks 1.3`: **implemented / independent review pending**" not in tasks:
            errors.append("tasks.md: Domain/Access completion marker is missing")
        if "Domain/Access review pending" not in handoff:
            errors.append("HANDOFF.md: Domain/Access review status is missing")
        if "BDD alignment: 100%" not in verification:
            errors.append("verification.md: exact BDD alignment is missing")
    elif spec_implementation_review_clean:
        if "Not live" not in verification:
            errors.append("verification.md: live-runtime boundary is missing")
        if "tasks 1.3`: **implemented / review clean**" not in tasks:
            errors.append("tasks.md: Domain/Access completion marker is missing")
        if "Domain/Access review-clean" not in handoff:
            errors.append("HANDOFF.md: Domain/Access review status is missing")
        if "BDD alignment: 100%" not in verification:
            errors.append("verification.md: exact BDD alignment is missing")
    elif spec_reconciliation_complete:
        if "Not live" not in verification:
            errors.append("verification.md: live-runtime boundary is missing")
        if "Spec 0.9 reference runtime implemented and verified" not in tasks:
            errors.append("tasks.md: Spec 0.9 completion marker is missing")
        if "Ready after Spec 0.9 reconciliation" not in handoff:
            errors.append("HANDOFF.md: Spec 0.9 handoff status is missing")
        if "BDD alignment: 100%" not in verification:
            errors.append("verification.md: exact BDD alignment is missing")
    elif spec_reconciliation_pending:
        if "Not live" not in verification:
            errors.append("verification.md: live-runtime boundary is missing")
        if "stale после Spec 0.9" not in tasks:
            errors.append("tasks.md: Spec 0.9 stale marker is missing")
        if "Spec 0.9 reconciliation pending" not in handoff:
            errors.append("HANDOFF.md: Spec 0.9 reconciliation status is missing")
        if "stale design/tasks/runtime/tests" not in decisions:
            errors.append("open-decisions.md: reconciliation blocker is missing")
    elif bdd_rewrite_pending:
        if "Not live" not in verification:
            errors.append("verification.md: live-runtime boundary is missing")
        if "блоки 1–4 реализованы и проверены" not in tasks:
            errors.append("tasks.md: Block 4 completion marker is missing")
        if "BDD rewrite pending after Block 4" not in handoff:
            errors.append("HANDOFF.md: BDD rewrite handoff status is missing")
        if "BDD rewrite теперь блокирует" not in decisions:
            errors.append("open-decisions.md: BDD blocker status is missing")
    elif block_four_complete:
        if "Not live" not in verification:
            errors.append("verification.md: live-runtime boundary is missing")
        if "блоки 1–4 реализованы и проверены" not in tasks:
            errors.append("tasks.md: Block 4 completion marker is missing")
        if "Ready after Block 4" not in handoff:
            errors.append("HANDOFF.md: post-Block-4 handoff status is missing")
    elif block_three_complete:
        if "Not live" not in verification:
            errors.append("verification.md: live-runtime boundary is missing")
        if "блоки 1–3 реализованы и проверены" not in tasks:
            errors.append("tasks.md: Block 3 completion marker is missing")
        if "Ready for Block 4" not in handoff:
            errors.append("HANDOFF.md: Block 4 handoff status is missing")
    elif block_two_complete:
        if "Not live" not in verification:
            errors.append("verification.md: live-runtime boundary is missing")
        if "блоки 1–2 реализованы и проверены" not in tasks:
            errors.append("tasks.md: Block 2 completion marker is missing")
        if "Ready for Block 3" not in handoff:
            errors.append("HANDOFF.md: Block 3 handoff status is missing")
    elif block_one_complete:
        if "Not live" not in verification:
            errors.append("verification.md: live-runtime boundary is missing")
    else:
        if "Ready for implementation" not in verification:
            errors.append("verification.md: implementation-readiness marker is missing")
        if "Not implemented" not in verification:
            errors.append("verification.md: runtime status marker is missing")
    if "Статус свежих команд: `Complete`" not in verification:
        errors.append("verification.md: fresh-command evidence is incomplete")
    if current_block9_overlay:
        if "Статус независимой проверки: `CLEAN`" not in verification:
            errors.append("verification.md: retained clean review status is missing")
    elif spec_implementation_review_pending:
        if "Статус независимой проверки: `Pending`" not in verification:
            errors.append("verification.md: pending review status is missing")
    elif spec_implementation_review_clean:
        if "Статус независимой проверки: `CLEAN`" not in verification:
            errors.append("verification.md: clean review status is missing")
    elif spec_reconciliation_pending:
        if "Статус независимой проверки Spec 0.9:" not in verification:
            errors.append("verification.md: Spec 0.9 review status is missing")
    else:
        expected_review = "`CLEAN`" if block_one_complete else "`Complete`"
        if f"Статус независимой проверки: {expected_review}" not in verification:
            errors.append("verification.md: independent review is incomplete")
    if re.search(r"записываются после|выполняется после сборки", verification):
        errors.append("verification.md: contains a future evidence placeholder")
    if (
        not current_block9_overlay
        and not bdd_rewrite_pending
        and "блокирующих решений нет" not in decisions
    ):
        errors.append(
            "open-decisions.md: blocking-decision status disagrees with readiness"
        )
    if not block_two_complete and block_one_complete:
        if "блок 1 `tasks 1.0` реализован" not in tasks:
            errors.append("tasks.md: Block 1 completion marker is missing")
        if "Ready for Block 2" not in handoff:
            errors.append("HANDOFF.md: Block 2 handoff status is missing")
    elif not block_two_complete:
        if "готов к реализации" not in tasks:
            errors.append("tasks.md: implementation boundary disagrees with readiness")
        if "Ready for implementation" not in handoff:
            errors.append("HANDOFF.md: next-session status is missing")
    for marker in (
        "## CHAT",
        "## DOC",
        "## CODE@c703f5e",
        "## CHECK",
        "## REVIEW",
        "## DERIVED",
        SOURCE_ORIGINAL_SHA256,
    ):
        if marker not in evidence:
            errors.append(f"evidence.md: missing {marker}")
    for decision_id in ("OD-24", "OD-25", "OD-26", "OD-27"):
        if decision_id not in evidence:
            errors.append(f"evidence.md: missing approved resolution {decision_id}")
    snapshot_hash = (
        hashlib.sha256(SUPPORTING_SOURCES[0].read_bytes()).hexdigest().upper()
    )
    if snapshot_hash != SOURCE_SNAPSHOT_SHA256:
        errors.append(
            "source handoff snapshot hash differs: "
            + snapshot_hash
            + " != "
            + SOURCE_SNAPSHOT_SHA256
        )

    if errors:
        raise ValueError("Package contract failed:\n- " + "\n- ".join(errors))


def source_manifest() -> tuple[str, list[tuple[str, str]]]:
    digest = hashlib.sha256()
    rows: list[tuple[str, str]] = []
    source_files = [ROOT / document.filename for document in DOCUMENTS]
    source_files.extend(SUPPORTING_SOURCES)
    source_files.append(Path(__file__).resolve())
    for path in source_files:
        filename = (
            path.relative_to(ROOT).as_posix()
            if path.is_relative_to(ROOT)
            else path.name
        )
        payload = path.read_bytes()
        file_hash = hashlib.sha256(payload).hexdigest()
        rows.append((filename, file_hash))
        digest.update(filename.encode("utf-8"))
        digest.update(b"\0")
        digest.update(payload)
        digest.update(b"\0")
    return digest.hexdigest(), rows


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).lower()
    normalized = re.sub(r"[^\w]+", "-", normalized, flags=re.UNICODE).strip("-")
    return normalized or "section"


def inner_html(node) -> str:
    return "".join(str(child) for child in node.contents)


def decorate_source_tags(soup: BeautifulSoup) -> None:
    for code in list(soup.find_all("code")):
        text = code.get_text(strip=True)
        matches = list(SOURCE_TAG_PATTERN.finditer(text))
        if not matches:
            continue
        remainder = SOURCE_TAG_PATTERN.sub("", text)
        if remainder:
            continue
        wrapper = soup.new_tag("span")
        wrapper["class"] = "source-tags"
        wrapper["aria-label"] = "Источники"
        for match in matches:
            key = match.group(1)
            label, css_class = SOURCE_TAGS[key]
            badge = soup.new_tag("a", href="#" + SOURCE_EVIDENCE_ANCHORS[key])
            badge["class"] = "source-tag source-" + css_class
            badge["title"] = label
            badge.string = "[" + key + "]"
            wrapper.append(badge)
        code.replace_with(wrapper)


def autolink_decisions(soup: BeautifulSoup) -> None:
    ignored = {
        "a",
        "code",
        "pre",
        "textarea",
        "button",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
    }
    for text_node in list(soup.find_all(string=OD_PATTERN)):
        if not isinstance(text_node, NavigableString):
            continue
        if text_node.parent and text_node.parent.name in ignored:
            continue
        text = str(text_node)
        cursor = 0
        replacements = []
        for match in OD_PATTERN.finditer(text):
            if match.group(0) not in CURRENT_DECISION_IDS:
                continue
            if match.start() > cursor:
                replacements.append(NavigableString(text[cursor : match.start()]))
            link = soup.new_tag("a", href="#decision-od-" + match.group(1))
            link["class"] = "xref"
            link.string = match.group(0)
            replacements.append(link)
            cursor = match.end()
        if cursor == 0:
            continue
        if cursor < len(text):
            replacements.append(NavigableString(text[cursor:]))
        text_node.replace_with(*replacements)


def render_markdown(path: Path) -> BeautifulSoup:
    rendered = MARKDOWN.render(path.read_text(encoding="utf-8"))
    soup = BeautifulSoup(rendered, "html.parser")
    decorate_source_tags(soup)
    autolink_decisions(soup)
    return soup


def assign_heading_ids(
    soup: BeautifulSoup, document_slug: str
) -> list[dict[str, str | int]]:
    entries: list[dict[str, str | int]] = []
    used: set[str] = set()
    counters: dict[str, int] = {}
    for heading in soup.find_all(re.compile(r"^h[1-6]$")):
        level = int(heading.name[1])
        title = heading.get_text(" ", strip=True)
        protocol_ref = re.match(r"^((?:R|S)-\d{2}[A-Z]?)\b", title, flags=re.IGNORECASE)
        base = protocol_ref.group(1).lower() if protocol_ref else slugify(title)
        candidate = document_slug + "-" + base
        counters[candidate] = counters.get(candidate, 0) + 1
        if candidate in used:
            candidate = candidate + "-" + str(counters[candidate])
        used.add(candidate)
        heading["id"] = candidate
        entries.append({"level": level, "title": title, "id": candidate})
    return entries


def render_document(document: Document) -> tuple[str, list[dict[str, str | int]], str]:
    soup = render_markdown(ROOT / document.filename)
    headings = assign_heading_ids(soup, document.slug)
    source_h1 = soup.find("h1")
    title = (
        source_h1.get_text(" ", strip=True)
        if source_h1
        else (document.nav_title or document.filename)
    )
    if source_h1:
        source_h1.extract()
        headings = [entry for entry in headings if entry["level"] != 1]

    for heading in soup.find_all(re.compile(r"^h[2-6]$")):
        level = min(6, int(heading.name[1]) + 1)
        heading.name = "h" + str(level)

    for table in list(soup.find_all("table")):
        wrapper = soup.new_tag("div")
        wrapper["class"] = "table-wrap"
        table.wrap(wrapper)

    section = f"""
    <section class="document-section" id="doc-{document.slug}" data-source="{html.escape(document.filename)}">
      <header class="document-header">
        <p class="eyebrow">{html.escape(document.eyebrow)}</p>
        <h2>{html.escape(title)}</h2>
        <p class="source-file">Исходный Markdown-файл: <code>{html.escape(document.filename)}</code></p>
      </header>
      <div class="markdown-body">{inner_html(soup)}</div>
    </section>
    """
    return section, headings, title


def extract_decisions() -> tuple[str, list[dict[str, str]], str, dict[str, int]]:
    soup = render_markdown(ROOT / "open-decisions.md")
    title_node = soup.find("h1")
    if title_node is None:
        raise RuntimeError("open-decisions.md has no h1 title")
    title = title_node.get_text(" ", strip=True)
    status_node = title_node.find_next_sibling("p")
    if status_node is None:
        raise RuntimeError("open-decisions.md has no status paragraph")
    status_html = inner_html(status_node)
    decisions: list[dict[str, str]] = []
    group_counts = {"core": 0, "late": 0}

    for group_heading in soup.find_all("h2"):
        group = group_heading.get_text(" ", strip=True)
        normalized_group = group.casefold()
        if (
            "решения оператора" in normalized_group
            or "решение оператора" in normalized_group
            or "будущая продуктовая работа" in normalized_group
        ):
            continue
        if (
            "до реализации" in normalized_group
            or "требует внимания" in normalized_group
        ):
            group_key = "core"
        elif "позже" in normalized_group or "отлож" in normalized_group:
            group_key = "late"
        else:
            raise RuntimeError("Unknown decision group: " + group)
        table = group_heading.find_next_sibling("table")
        if table is None:
            raise RuntimeError("No decision table after " + group)
        for row in table.select("tbody tr"):
            cells = row.find_all("td", recursive=False)
            if len(cells) != 4:
                raise RuntimeError(
                    "Decision table row must have four cells: "
                    + row.get_text(" ", strip=True)
                )
            decision_id = cells[0].get_text(" ", strip=True)
            if not re.fullmatch(r"OD-\d{2}", decision_id):
                raise RuntimeError("Invalid decision id: " + decision_id)
            decisions.append(
                {
                    "id": decision_id,
                    "number": decision_id[-2:],
                    "group": group,
                    "group_key": group_key,
                    "question": inner_html(cells[1]),
                    "question_text": cells[1].get_text(" ", strip=True),
                    "recommendation": inner_html(cells[2]),
                    "recommendation_text": cells[2].get_text(" ", strip=True),
                    "basis": inner_html(cells[3]),
                    "basis_text": cells[3].get_text(" ", strip=True),
                }
            )
            group_counts[group_key] += 1

    paragraphs = soup.find_all("p")
    tail_html = inner_html(paragraphs[-1]) if paragraphs[-1] is not status_node else ""
    return title, decisions, status_html + "\n" + tail_html, group_counts


def decision_card(decision: dict[str, str]) -> str:
    search_text = " ".join(
        (
            decision["id"],
            decision["question_text"],
            decision["recommendation_text"],
            decision["basis_text"],
        )
    )
    initial_status = "defer" if decision["group_key"] == "late" else "pending"
    fingerprint = hashlib.sha256(
        (decision["group_key"] + "\0" + search_text).encode("utf-8")
    ).hexdigest()[:16]
    recommendation_label = (
        "Когда вернуться" if decision["group_key"] == "late" else "Рекомендация"
    )
    basis_label = "Источник" if decision["group_key"] == "late" else "Основание"
    return f"""
    <article class="decision-card" id="decision-od-{decision["number"]}"
      data-decision-id="{decision["id"]}" data-group="{decision["group_key"]}"
      data-decision-fingerprint="{fingerprint}"
      data-title="{html.escape(decision["question_text"], quote=True)}"
      data-search="{html.escape(search_text.lower(), quote=True)}"
      data-decision-status="{initial_status}" tabindex="-1">
      <header class="decision-card-header">
        <span class="decision-id">{decision["id"]}</span>
        <span class="decision-group">{html.escape(decision["group"])}</span>
        <h4>{decision["question"]}</h4>
      </header>
      <div class="decision-copy">
        <div class="decision-recommendation">
          <p class="field-label">{recommendation_label}</p>
          <div class="copy-source">{decision["recommendation"]}</div>
        </div>
        <div class="decision-basis">
          <p class="field-label">{basis_label}</p>
          <div class="copy-source">{decision["basis"]}</div>
        </div>
      </div>
      <div class="decision-review">
        <div class="decision-actions" role="group" aria-label="Решение по {decision["id"]}">
          <button type="button" data-set-status="accept" aria-pressed="false">Принять</button>
          <button type="button" data-set-status="change" aria-pressed="false">Изменить</button>
          <button type="button" data-set-status="defer" aria-pressed="false">Отложить</button>
        </div>
        <details class="decision-note">
          <summary>Комментарий оператора</summary>
          <label class="sr-only" for="note-{decision["number"]}">Комментарий к {decision["id"]}</label>
          <textarea id="note-{decision["number"]}" rows="3"
            placeholder="Что изменить, уточнить или проверить…"></textarea>
        </details>
        <p class="decision-print-state">Статус: {"отложено" if initial_status == "defer" else "не решено"}</p>
      </div>
    </article>
    """


def russian_plural(count: int, one: str, few: str, many: str) -> str:
    if count % 10 == 1 and count % 100 != 11:
        return one
    if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        return few
    return many


def render_decision_section() -> tuple[
    str, list[dict[str, str | int]], str, dict[str, int]
]:
    title, decisions, status_and_tail, group_counts = extract_decisions()
    status_html, tail_html = status_and_tail.split("\n", 1)
    groups: list[tuple[str, str, list[dict[str, str]]]] = []
    for group_key in ("core", "late"):
        members = [item for item in decisions if item["group_key"] == group_key]
        if not members:
            continue
        groups.append((group_key, members[0]["group"], members))

    cards = []
    for group_key, group_title, members in groups:
        cards.append(
            f'<section class="decision-group-section" id="decisions-{group_key}">'
            f"<h3>{html.escape(group_title)}</h3>"
            f'<p class="group-count">{len(members)} '
            f"{russian_plural(len(members), 'решение', 'решения', 'решений')}</p>"
            + "".join(decision_card(item) for item in members)
            + "</section>"
        )

    section_soup = BeautifulSoup("".join(cards), "html.parser")
    decorate_source_tags(section_soup)
    autolink_decisions(section_soup)

    core_filter = (
        '<button type="button" data-filter="core" aria-pressed="false">До реализации</button>'
        if group_counts["core"]
        else ""
    )
    next_button = (
        '<button type="button" class="button-secondary" id="next-unresolved">'
        "Следующее нерешённое</button>"
        if group_counts["core"]
        else ""
    )
    section_class = "document-section decisions-section"
    if not group_counts["core"]:
        section_class += " decisions-readonly"
    section = f"""
    <section class="{section_class}" id="doc-decisions" data-source="open-decisions.md">
      <header class="document-header">
        <p class="eyebrow">{group_counts["core"]} блокирующих · {group_counts["late"]} отложено</p>
        <h2>{html.escape(title)}</h2>
        <p class="source-file">Исходный Markdown-файл: <code>open-decisions.md</code></p>
        <p class="source-status">{status_html}</p>
      </header>
      <div class="decision-toolbar" aria-label="Инструменты проверки решений">
        <div class="decision-progress-copy">
          <strong><span id="decision-done-count">0</span> / {group_counts["core"]}</strong>
          <span>блокирующих решений разобрано</span>
        </div>
        <div class="decision-progress" aria-hidden="true"><span id="decision-progress-bar"></span></div>
        <div class="decision-filters" role="group" aria-label="Фильтр решений">
          <button type="button" data-filter="all" aria-pressed="true">Все</button>
          <button type="button" data-filter="pending" aria-pressed="false">Не решено</button>
          {core_filter}
          <button type="button" data-filter="late" aria-pressed="false">Позже</button>
        </div>
        <label class="decision-search">
          <span class="sr-only">Поиск по решениям</span>
          <input id="decision-search" type="search" placeholder="Найти решение…" autocomplete="off">
        </label>
        <div class="decision-toolbar-actions">
          {next_button}
          <button type="button" class="button-primary" id="export-review">Скачать решения</button>
          <button type="button" class="button-secondary" id="copy-review">Копировать</button>
          <button type="button" class="button-quiet" id="reset-review">Сбросить</button>
        </div>
      </div>
      <div class="decision-groups">{inner_html(section_soup)}</div>
      <p class="operator-rule">{tail_html}</p>
    </section>
    """
    headings: list[dict[str, str | int]] = [
        {"level": 2, "title": group_title, "id": "decisions-" + group_key}
        for group_key, group_title, _ in groups
    ]
    return section, headings, title, group_counts


def nav_document(
    document: Document, title: str, headings: list[dict[str, str | int]]
) -> str:
    items = []
    for heading in headings:
        if int(heading["level"]) > 3:
            continue
        css_class = "nav-level-" + str(heading["level"])
        items.append(
            f'<li class="{css_class}"><a href="#{heading["id"]}" '
            f'data-nav-text="{html.escape(str(heading["title"]).lower(), quote=True)}">'
            f"{html.escape(str(heading['title']))}</a></li>"
        )
    details_open = " open" if document.slug in {"handoff", "decisions"} else ""
    nav_title = document.nav_title or title
    nested = '<ul class="nav-subsections">' + "".join(items) + "</ul>" if items else ""
    return f"""
    <details class="nav-document" data-nav-document="{document.slug}"{details_open}>
      <summary>
        <a href="#doc-{document.slug}">{html.escape(nav_title)}</a>
        <span>{html.escape(document.filename)}</span>
      </summary>
      {nested}
    </details>
    """


def build(*, check: bool = False) -> None:
    validate_package_contract()
    verification_text = (ROOT / "verification.md").read_text(encoding="utf-8")
    handoff_text = (ROOT / "HANDOFF.md").read_text(encoding="utf-8")
    decision = current_decision(verification_text)
    current_block9_overlay = (
        "Block 9 Spec 1.1 and Design 1.3 select a real canonical private pilot"
        in handoff_text
    )
    spec_implementation_review_pending = (
        decision
        == "Domain/Access implementation verified — independent PR review pending"
    )
    spec_implementation_review_clean = (
        decision == "Domain/Access implementation verified — independent PR review clean"
    )
    spec_reconciliation_complete = decision == "Ready after Spec 0.9 reconciliation"
    spec_reconciliation_pending = (
        decision == "Not ready — Spec 0.9 reconciliation pending"
    )
    bdd_rewrite_pending = decision == "Not ready — BDD rewrite pending"
    block_four_complete = decision == "Ready after Block 4"
    block_four_implemented = (
        current_block9_overlay
        or spec_implementation_review_pending
        or spec_implementation_review_clean
        or spec_reconciliation_complete
        or spec_reconciliation_pending
        or bdd_rewrite_pending
        or block_four_complete
    )
    block_three_complete = (
        block_four_implemented or "Ready for Block 4" in verification_text
    )
    block_two_complete = (
        block_three_complete or "Ready for Block 3" in verification_text
    )
    block_one_complete = block_two_complete or "Ready for Block 2" in verification_text
    source_digest, manifest_rows = source_manifest()
    attention_sections: list[str] = []
    sections: list[str] = []
    nav_sections: list[str] = []
    decision_counts = {"core": 0, "late": 0}

    for document in DOCUMENTS:
        if document.slug == "decisions":
            section, headings, title, decision_counts = render_decision_section()
            sections.append(section)
        elif document.slug == "handoff":
            section, headings, title = render_document(document)
            attention_sections.append(section)
        else:
            section, headings, title = render_document(document)
            sections.append(section)
        nav_sections.append(nav_document(document, title, headings))

    decision_count = sum(decision_counts.values())
    if current_block9_overlay:
        decision_guide = (
            "Шесть решений оператора приняты. Точный Block 9 Outcome/BDD 1.0 "
            "принят без изменений. Design разрешён как следующий gate; "
            "implementation, live-активация и ledger writes запрещены."
        )
    elif spec_implementation_review_pending:
        decision_guide = (
            "Domain/Access решения приняты и локально доказаны. "
            "Остаётся независимая проверка опубликованного WEA PR."
        )
    elif spec_implementation_review_clean:
        decision_guide = (
            "Domain/Access решения приняты и независимо проверены. "
            "S-13C и live-активация остаются отдельными будущими изменениями."
        )
    elif spec_reconciliation_complete:
        decision_guide = (
            "Все решения текущего reference runtime приняты и доказаны. "
            "Отложенные вопросы относятся только к будущей live-активации."
        )
    elif spec_reconciliation_pending:
        decision_guide = (
            "Все BDD-решения приняты. Журнал различий сохранён для traceability. "
            "Следующий шаг — design reconciliation, затем новый tasks contract."
        )
    elif bdd_rewrite_pending:
        decision_guide = (
            "Текущий blocker находится в таблице BDD: принимайте или изменяйте "
            "сценарии построчно; отложенные OD показаны только для контекста."
        )
    elif decision_counts["core"]:
        decision_guide = (
            "Кнопки решений сохраняют выбор только в хранилище этого браузера. "
            "Для обсуждения скачайте или скопируйте решения в формате Markdown."
        )
    else:
        decision_guide = (
            "Отложенные вопросы показаны только для контекста; сейчас решения по ним не нужны. "
            "План и handoff готовы для следующего ограниченного блока."
        )

    if current_block9_overlay:
        hero_kicker = "Block 9 Spec 1.1 · GitHub-native implementation next"
        hero_lead = (
            "Spec 1.1 и Design 1.3 выбирают настоящий canonical private pilot. "
            "GitHub Actions и pull requests заменяют local Apps, locks и epoch "
            "guards как authority. vNext остаётся выключенным до точного "
            "activation merge."
        )
        package_status = "Spec 1.1 current · Actions next · Not live"
        primary_href = "#doc-handoff"
        primary_label = "Открыть текущий handoff"
        core_status_label = "Блокеров для Design"
        core_status_count = "0"
    elif spec_implementation_review_pending:
        hero_kicker = "Spec 1.0 · Domain/Access verified"
        hero_lead = (
            "69 текущих BDD-сценариев включают 67 неизменных runtime-сценариев "
            "и два Domain/Access control-plane сценария. S-13C остаётся "
            "accepted-future. Пакет ожидает независимую проверку WEA PR; "
            "live Tide, ledger, bootstrap и GitHub permission writers не подключены."
        )
        package_status = "Spec 1.0 verified · PR review pending · Not live"
        primary_href = "#doc-handoff"
        primary_label = "Открыть review handoff"
        core_status_label = "Расхождений BDD"
        core_status_count = "0"
    elif spec_implementation_review_clean:
        hero_kicker = "Spec 1.0 · independent review clean"
        hero_lead = (
            "69 текущих BDD-сценариев включают 67 неизменных runtime-сценариев "
            "и два Domain/Access control-plane сценария. S-13C остаётся "
            "accepted-future. Независимый review не нашёл actionable defects. "
            "Live-системы не подключены."
        )
        package_status = "Spec 1.0 verified · PR review clean · Not live"
        primary_href = "#doc-handoff"
        primary_label = "Открыть review-clean handoff"
        core_status_label = "Расхождений BDD"
        core_status_count = "0"
    elif spec_reconciliation_complete:
        hero_kicker = "Spec 0.9 · reference runtime verified"
        hero_lead = (
            "Все 67 текущих BDD-сценариев согласованы с ruleset 0.8 и "
            "manifest-pinned executor 0.8.0. Три future-сценария non-effective. "
            "Live Tide, ledger, migration, "
            "bootstrap и GitHub writers не подключены."
        )
        package_status = "Spec 0.9 verified · Not live"
        primary_href = "#doc-handoff"
        primary_label = "Открыть verified handoff"
        core_status_label = "Расхождений BDD"
        core_status_count = "0"
    elif spec_reconciliation_pending:
        hero_kicker = "Spec 0.9 принят · reconciliation pending"
        hero_lead = (
            "Оператор принял 24 переписанных и два новых BDD-сценария. "
            "Design, tasks, ruleset 0.7, runtime и tests ещё описывают Spec 0.8. "
            "Пакет остаётся Not ready до отдельного согласования и реализации."
        )
        package_status = "Not ready · Spec 0.9 reconciliation pending"
        primary_href = "#doc-spec"
        primary_label = "Открыть Spec 0.9"
        core_status_label = "Открытых BDD-решений"
        core_status_count = "0"
    elif bdd_rewrite_pending:
        hero_kicker = "BDD-контракт · построчная проверка"
        hero_lead = (
            "Block 4 code slice проверен, но новая матрица изменила смысл 24 старых "
            "сценариев и требует двух новых. До вашего построчного решения пакет "
            "не считается согласованным и дальнейшая реализация остановлена."
        )
        package_status = "Not ready · BDD rewrite pending"
        primary_href = "#doc-bdd-contract-rewrite"
        primary_label = "Открыть таблицу BDD"
        core_status_label = "BDD-строк к решению"
        core_status_count = "26"
    elif decision_counts["core"]:
        hero_kicker = "Кандидат · построчная проверка"
        hero_lead = (
            "Короткий пакет утверждённых правил, оставшихся вопросов и технических "
            "предложений. Он предназначен для полной вычитки и пока не разрешает планирование."
        )
        package_status = "Ожидает полной вычитки"
        primary_href = "#doc-decisions"
        primary_label = "Решить открытые вопросы"
        core_status_label = "Блокирующих решений"
        core_status_count = str(decision_counts["core"])
    elif block_four_complete:
        hero_kicker = "Кандидат · блоки 1–4 проверены"
        hero_lead = (
            "Author-approved Resolution Plan и атомарная активация первого child "
            "Contract реализованы в отдельной immutable closure 0.7. Live Tide, "
            "ledger и GitHub не подключены; следующие execution slices ещё не начаты."
        )
        package_status = "Block 4 закрыт; vNext не подключена"
        primary_href = "#doc-handoff"
        primary_label = "Открыть post-Block-4 handoff"
        core_status_label = "Блокирующих решений"
        core_status_count = str(decision_counts["core"])
    elif block_three_complete:
        hero_kicker = "Кандидат · блоки 1–3 проверены"
        hero_lead = (
            "Draft, Triage и атомарный ordinary Contract реализованы в неактивной "
            "immutable closure. Live Tide, ledger и GitHub не подключены; handoff "
            "ограничен первым полным direct-pr path."
        )
        package_status = "Блок 3 закрыт; vNext не подключена"
        primary_href = "#doc-handoff"
        primary_label = "Открыть handoff блока 4"
        core_status_label = "Блокирующих решений"
        core_status_count = str(decision_counts["core"])
    elif block_two_complete:
        hero_kicker = "Кандидат · блоки 1–2 проверены"
        hero_lead = (
            "Исторический Hello World закрыт операторским verdict и проверяемым "
            "read-only evidence. Live Tide, ledger и GitHub не подключены; handoff "
            "ограничен Draft, Triage и обычным Contract."
        )
        package_status = "Блок 2 закрыт; vNext не подключена"
        primary_href = "#doc-handoff"
        primary_label = "Открыть handoff блока 3"
        core_status_label = "Блокирующих решений"
        core_status_count = str(decision_counts["core"])
    elif block_one_complete:
        hero_kicker = "Кандидат · блок 1 проверен"
        hero_lead = (
            "Внутреннее протокольное ядро реализовано и прошло независимую проверку. "
            "Live Tide, ledger и GitHub не подключены; handoff ограничен Identity и Hello World."
        )
        package_status = "Блок 1 готов; vNext не подключена"
        primary_href = "#doc-handoff"
        primary_label = "Открыть handoff блока 2"
        core_status_label = "Блокирующих решений"
        core_status_count = str(decision_counts["core"])
    else:
        hero_kicker = "Кандидат · план реализации"
        hero_lead = (
            "Оператор одобрил поведение и разрешил начать внутреннее ядро vNext. "
            "План и handoff готовы; рабочий код, ledger и GitHub пока не менялись."
        )
        package_status = "План готов; код не начат"
        primary_href = "#doc-handoff"
        primary_label = "Открыть handoff"
        core_status_label = "Блокирующих решений"
        core_status_count = str(decision_counts["core"])

    manifest_html = "".join(
        "<tr><td><code>"
        + html.escape(filename)
        + "</code></td><td><code>"
        + file_hash
        + "</code></td></tr>"
        for filename, file_hash in manifest_rows
    )

    legend_html = "".join(
        '<li><a href="#'
        + SOURCE_EVIDENCE_ANCHORS[key]
        + '" class="source-tag source-'
        + css_class
        + '">['
        + html.escape(key)
        + "]</a><span>"
        + html.escape(label)
        + "</span></li>"
        for key, (label, css_class) in SOURCE_TAGS.items()
    )

    template = r"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light">
  <meta name="description" content="WEA vNext — единый документ для операторской проверки">
  <link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='14' fill='%231d211f'/%3E%3Cpath d='M13 18h9l5 26 5-18h8l5 18 5-26h9L50 48H40l-4-14-4 14H22z' fill='white'/%3E%3C/svg%3E">
  <title>WEA vNext · операторская проверка</title>
  <style>
    :root {
      --paper: #f5f3ee;
      --surface: #fffefa;
      --surface-2: #eeece5;
      --ink: #1d211f;
      --muted: #676d68;
      --line: #d9d6cd;
      --line-strong: #b9b7ae;
      --accent: #b34f2a;
      --accent-soft: #f4e2d9;
      --green: #28745b;
      --green-soft: #dfeee8;
      --amber: #8c651f;
      --amber-soft: #f3ead5;
      --blue: #2c5f91;
      --blue-soft: #e2ebf5;
      --violet: #66528a;
      --violet-soft: #ebe6f2;
      --shadow: 0 1px 2px rgba(24, 30, 27, 0.06), 0 10px 30px rgba(24, 30, 27, 0.04);
      --ease-out: cubic-bezier(0.23, 1, 0.32, 1);
      --sans: Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      --mono: "SFMono-Regular", Consolas, "Liberation Mono", monospace;
    }

    * { box-sizing: border-box; }
    html { scroll-padding-top: 18px; }
    body {
      margin: 0;
      color: var(--ink);
      background: var(--paper);
      font-family: var(--sans);
      font-size: 16px;
      line-height: 1.62;
      text-rendering: optimizeLegibility;
    }
    a { color: var(--blue); text-underline-offset: 0.18em; }
    button, input, textarea { font: inherit; }
    button { color: inherit; }
    .sr-only {
      position: absolute;
      width: 1px;
      height: 1px;
      padding: 0;
      margin: -1px;
      overflow: hidden;
      clip: rect(0, 0, 0, 0);
      white-space: nowrap;
      border: 0;
    }
    .reading-progress {
      position: fixed;
      z-index: 50;
      inset: 0 0 auto;
      height: 3px;
      background: transparent;
    }
    .reading-progress span {
      display: block;
      width: 0;
      height: 100%;
      background: var(--accent);
    }
    .layout {
      display: grid;
      grid-template-columns: 300px minmax(0, 1fr);
      min-height: 100vh;
    }
    .sidebar {
      position: sticky;
      top: 0;
      height: 100vh;
      overflow: auto;
      padding: 28px 22px 36px;
      border-right: 1px solid var(--line);
      background: rgba(245, 243, 238, 0.96);
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 11px;
      margin-bottom: 24px;
      color: var(--ink);
      text-decoration: none;
    }
    .brand-mark {
      display: grid;
      place-items: center;
      width: 34px;
      height: 34px;
      border-radius: 9px;
      color: #fff;
      background: var(--ink);
      font-weight: 750;
      letter-spacing: -0.05em;
    }
    .brand-copy { display: grid; line-height: 1.2; }
    .brand-copy strong { font-size: 14px; }
    .brand-copy span { color: var(--muted); font-size: 12px; }
    .nav-search {
      width: 100%;
      min-height: 39px;
      margin-bottom: 8px;
      padding: 8px 11px;
      border: 1px solid var(--line);
      border-radius: 9px;
      color: var(--ink);
      background: var(--surface);
      outline: none;
    }
    .nav-search:focus { border-color: var(--ink); box-shadow: 0 0 0 3px rgba(29, 33, 31, 0.08); }
    .search-hint {
      margin: 0 0 18px;
      color: var(--muted);
      font-size: 11px;
    }
    .primary-nav > a {
      display: flex;
      align-items: center;
      justify-content: space-between;
      min-height: 38px;
      padding: 7px 9px;
      border-radius: 8px;
      color: var(--ink);
      font-size: 13px;
      font-weight: 650;
      text-decoration: none;
    }
    .primary-nav > a span {
      color: var(--muted);
      font-size: 11px;
      font-weight: 500;
    }
    .primary-nav > a:hover,
    .primary-nav > a.active { background: var(--surface-2); }
    .nav-document {
      margin: 3px 0;
      border-radius: 9px;
    }
    .nav-document[open] { background: rgba(255, 254, 250, 0.62); }
    .nav-document summary {
      position: relative;
      min-height: 42px;
      padding: 7px 26px 7px 9px;
      cursor: pointer;
      list-style: none;
    }
    .nav-document summary::-webkit-details-marker { display: none; }
    .nav-document summary::after {
      position: absolute;
      top: 14px;
      right: 10px;
      content: "›";
      color: var(--muted);
      transform: rotate(0);
      transition: transform 160ms var(--ease-out);
    }
    .nav-document[open] summary::after { transform: rotate(90deg); }
    .nav-document summary a {
      display: block;
      color: var(--ink);
      font-size: 13px;
      font-weight: 650;
      line-height: 1.3;
      text-decoration: none;
    }
    .nav-document summary span {
      display: block;
      margin-top: 2px;
      color: var(--muted);
      font-family: var(--mono);
      font-size: 10px;
    }
    .nav-subsections {
      margin: 0;
      padding: 1px 10px 10px 20px;
      list-style: none;
    }
    .nav-subsections li { margin: 2px 0; }
    .nav-subsections a {
      display: block;
      padding: 4px 7px;
      border-left: 1px solid var(--line);
      color: var(--muted);
      font-size: 11px;
      line-height: 1.35;
      text-decoration: none;
    }
    .nav-subsections a:hover,
    .nav-subsections a.active {
      border-left-color: var(--accent);
      color: var(--ink);
    }
    .nav-level-3 a { padding-left: 13px; }
    .nav-empty { display: none; }

    main {
      width: min(100%, 1080px);
      min-width: 0;
      margin: 0 auto;
      padding: 72px 64px 120px;
    }
    .hero {
      padding: 34px 0 72px;
      border-bottom: 1px solid var(--line-strong);
    }
    .hero-kicker, .eyebrow {
      margin: 0 0 9px;
      color: var(--accent);
      font-size: 12px;
      font-weight: 750;
      letter-spacing: 0.09em;
      text-transform: uppercase;
    }
    .hero h1 {
      max-width: 820px;
      margin: 0;
      font-size: clamp(40px, 6vw, 72px);
      line-height: 0.98;
      letter-spacing: -0.055em;
    }
    .hero-lead {
      max-width: 760px;
      margin: 25px 0 0;
      color: #444a46;
      font-size: 20px;
      line-height: 1.55;
    }
    .hero-status {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin: 28px 0 0;
    }
    .status-pill {
      display: inline-flex;
      align-items: center;
      min-height: 31px;
      padding: 5px 10px;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: var(--surface);
      color: var(--muted);
      font-size: 12px;
      font-weight: 650;
    }
    .status-pill.alert { border-color: #e0b69f; color: #8e3e20; background: var(--accent-soft); }
    .hero-actions {
      display: flex;
      flex-wrap: wrap;
      gap: 9px;
      margin-top: 24px;
    }
    .hero-actions a {
      display: inline-flex;
      align-items: center;
      min-height: 41px;
      padding: 8px 14px;
      border-radius: 9px;
      font-size: 13px;
      font-weight: 700;
      text-decoration: none;
      transition: transform 140ms var(--ease-out);
    }
    .hero-actions a:active { transform: scale(0.97); }
    .hero-actions .primary { color: #fff; background: var(--ink); }
    .hero-actions .secondary { border: 1px solid var(--line); color: var(--ink); background: var(--surface); }

    .reading-guide {
      display: grid;
      grid-template-columns: 1.15fr 1fr;
      gap: 32px;
      padding: 52px 0 56px;
      border-bottom: 1px solid var(--line);
    }
    .reading-guide h2 { margin: 0 0 14px; font-size: 25px; letter-spacing: -0.025em; }
    .reading-guide p { margin: 0 0 12px; color: var(--muted); }
    .legend {
      margin: 0;
      padding: 0;
      list-style: none;
    }
    .legend li {
      display: grid;
      grid-template-columns: minmax(104px, auto) 1fr;
      align-items: center;
      gap: 9px;
      margin: 7px 0;
      color: var(--muted);
      font-size: 12px;
    }
    .source-tag {
      display: inline-flex;
      align-items: center;
      width: max-content;
      min-height: 22px;
      padding: 2px 6px;
      border: 1px solid transparent;
      border-radius: 5px;
      font-family: var(--mono);
      font-size: 10px;
      font-weight: 700;
      line-height: 1;
      white-space: nowrap;
      text-decoration: none;
    }
    .source-tags {
      display: inline-flex;
      flex-wrap: wrap;
      gap: 4px;
      vertical-align: 0.06em;
    }
    .source-chat { color: #8f3c20; background: var(--accent-soft); border-color: #e1b49f; }
    .source-doc { color: var(--blue); background: var(--blue-soft); border-color: #bfd0e2; }
    .source-code { color: var(--violet); background: var(--violet-soft); border-color: #cdc1dd; }
    .source-check { color: var(--green); background: var(--green-soft); border-color: #b7d5c9; }
    .source-review { color: #315c63; background: #e8f2f3; border-color: #bdd2d5; }
    .source-derived { color: var(--amber); background: var(--amber-soft); border-color: #decda7; }

    .document-section {
      padding: 74px 0 34px;
      border-bottom: 1px solid var(--line-strong);
    }
    .document-header { margin-bottom: 38px; }
    .document-header h2 {
      max-width: 800px;
      margin: 0;
      font-size: clamp(34px, 4vw, 48px);
      line-height: 1.06;
      letter-spacing: -0.045em;
    }
    .source-file {
      margin: 13px 0 0;
      color: var(--muted);
      font-size: 12px;
    }
    .source-status {
      max-width: 760px;
      margin: 16px 0 0;
      color: var(--muted);
    }
    .markdown-body {
      max-width: 850px;
      min-width: 0;
      font-size: 16px;
      line-height: 1.68;
      overflow-wrap: anywhere;
    }
    #doc-bdd-contract-rewrite .markdown-body { max-width: none; }
    #doc-bdd-contract-rewrite table {
      table-layout: fixed;
      font-size: 12px;
    }
    #doc-bdd-contract-rewrite th:first-child,
    #doc-bdd-contract-rewrite td:first-child {
      width: 7%;
      white-space: nowrap;
      overflow-wrap: normal;
    }
    #doc-bdd-contract-rewrite th:nth-child(2),
    #doc-bdd-contract-rewrite td:nth-child(2) { width: 14%; }
    #doc-bdd-contract-rewrite th:nth-child(3),
    #doc-bdd-contract-rewrite td:nth-child(3) { width: 21%; }
    #doc-bdd-contract-rewrite th:nth-child(4),
    #doc-bdd-contract-rewrite td:nth-child(4) { width: 25%; }
    #doc-bdd-contract-rewrite th:nth-child(5),
    #doc-bdd-contract-rewrite td:nth-child(5) { width: 33%; }
    .markdown-body > p,
    .markdown-body > ul,
    .markdown-body > ol,
    .markdown-body > pre,
    .markdown-body > blockquote { max-width: 760px; }
    .markdown-body h3,
    .markdown-body h4,
    .markdown-body h5,
    .markdown-body h6 { scroll-margin-top: 16px; }
    .markdown-body h3 {
      margin: 58px 0 18px;
      font-size: 27px;
      line-height: 1.15;
      letter-spacing: -0.03em;
    }
    .markdown-body h4 {
      margin: 42px 0 14px;
      font-size: 21px;
      line-height: 1.2;
      letter-spacing: -0.02em;
    }
    .markdown-body h5 {
      margin: 31px 0 11px;
      font-size: 16px;
    }
    .markdown-body h6 {
      margin: 25px 0 9px;
      font-size: 14px;
    }
    .markdown-body p { margin: 0 0 16px; }
    .markdown-body ul, .markdown-body ol { margin: 0 0 20px; padding-left: 25px; }
    .markdown-body li { margin: 6px 0; padding-left: 3px; }
    .markdown-body blockquote {
      margin: 24px 0;
      padding: 14px 18px;
      border-left: 3px solid var(--accent);
      background: var(--accent-soft);
    }
    code {
      padding: 0.12em 0.34em;
      border-radius: 4px;
      background: var(--surface-2);
      font-family: var(--mono);
      font-size: 0.86em;
      overflow-wrap: anywhere;
    }
    pre {
      overflow: auto;
      padding: 17px 18px;
      border: 1px solid var(--line);
      border-radius: 10px;
      background: #292e2b;
      color: #f2f2ee;
      line-height: 1.55;
    }
    pre code { padding: 0; background: transparent; color: inherit; }
    .table-wrap { overflow-x: auto; margin: 22px 0 30px; }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
      line-height: 1.48;
    }
    th, td {
      padding: 10px 11px;
      border: 1px solid var(--line);
      vertical-align: top;
      text-align: left;
    }
    th {
      background: var(--surface-2);
      font-size: 11px;
      letter-spacing: 0.025em;
      text-transform: uppercase;
    }
    tr:nth-child(even) td { background: rgba(255, 254, 250, 0.48); }
    .xref {
      padding: 0 2px;
      border-radius: 3px;
      color: var(--blue);
      background: var(--blue-soft);
      font-family: var(--mono);
      font-size: 0.9em;
      font-weight: 700;
      text-decoration: none;
    }

    .decision-toolbar {
      position: sticky;
      z-index: 15;
      top: 13px;
      display: grid;
      grid-template-columns: auto minmax(110px, 1fr);
      gap: 10px 16px;
      margin: 0 0 36px;
      padding: 13px;
      border: 1px solid rgba(185, 183, 174, 0.8);
      border-radius: 12px;
      background: rgba(255, 254, 250, 0.94);
      box-shadow: var(--shadow);
      backdrop-filter: blur(12px);
    }
    .decision-progress-copy {
      display: flex;
      align-items: baseline;
      gap: 6px;
      font-size: 12px;
    }
    .decision-progress-copy strong { font-size: 15px; }
    .decision-progress {
      align-self: center;
      height: 5px;
      overflow: hidden;
      border-radius: 999px;
      background: var(--surface-2);
    }
    .decision-progress span {
      display: block;
      width: 0;
      height: 100%;
      border-radius: inherit;
      background: var(--green);
      transition: width 180ms var(--ease-out);
    }
    .decision-filters,
    .decision-toolbar-actions {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }
    .decision-filters button,
    .decision-toolbar button,
    .decision-actions button {
      min-height: 32px;
      padding: 5px 9px;
      border: 1px solid var(--line);
      border-radius: 7px;
      background: var(--surface);
      font-size: 11px;
      font-weight: 650;
      cursor: pointer;
      transition: transform 140ms var(--ease-out), border-color 140ms ease, background-color 140ms ease;
    }
    .decision-toolbar button:active,
    .decision-actions button:active { transform: scale(0.97); }
    .decision-filters button[aria-pressed="true"] { border-color: var(--ink); color: #fff; background: var(--ink); }
    .decision-search input {
      width: 100%;
      min-height: 34px;
      padding: 6px 9px;
      border: 1px solid var(--line);
      border-radius: 7px;
      background: var(--surface);
      font-size: 12px;
      outline: none;
    }
    .decision-search input:focus { border-color: var(--ink); box-shadow: 0 0 0 3px rgba(29, 33, 31, 0.08); }
    .decision-toolbar-actions { grid-column: 1 / -1; }
    .decision-toolbar .button-primary { border-color: var(--ink); color: #fff; background: var(--ink); }
    .decision-toolbar .button-quiet { margin-left: auto; border-color: transparent; color: var(--muted); background: transparent; }
    .decision-group-section { margin-top: 52px; }
    .decision-group-section > h3 {
      display: inline;
      margin: 0;
      font-size: 25px;
      letter-spacing: -0.03em;
    }
    .group-count {
      display: inline;
      margin-left: 8px;
      color: var(--muted);
      font-size: 12px;
    }
    .decision-card {
      margin: 18px 0;
      overflow: hidden;
      border: 1px solid var(--line);
      border-radius: 13px;
      background: var(--surface);
      box-shadow: 0 1px 0 rgba(24, 30, 27, 0.03);
      outline: none;
    }
    .decision-card:focus { box-shadow: 0 0 0 3px rgba(44, 95, 145, 0.15); }
    .decision-card[hidden] { display: none; }
    .decision-card-header {
      display: grid;
      grid-template-columns: auto 1fr;
      gap: 4px 10px;
      padding: 16px 18px 14px;
      border-bottom: 1px solid var(--line);
      background: #fbfaf6;
    }
    .decision-id {
      color: var(--accent);
      font-family: var(--mono);
      font-size: 12px;
      font-weight: 800;
    }
    .decision-group {
      justify-self: end;
      color: var(--muted);
      font-size: 10px;
    }
    .decision-card h4 {
      grid-column: 1 / -1;
      margin: 2px 0 0;
      font-size: 20px;
      line-height: 1.2;
      letter-spacing: -0.02em;
    }
    .decision-copy {
      display: grid;
      grid-template-columns: minmax(0, 1.8fr) minmax(190px, 1fr);
      gap: 0;
    }
    .decision-recommendation,
    .decision-basis { padding: 17px 18px; }
    .decision-basis {
      border-left: 1px solid var(--line);
      color: var(--muted);
      background: rgba(238, 236, 229, 0.38);
    }
    .field-label {
      margin: 0 0 7px;
      color: var(--muted);
      font-size: 10px;
      font-weight: 750;
      letter-spacing: 0.07em;
      text-transform: uppercase;
    }
    .copy-source { font-size: 14px; line-height: 1.58; }
    .copy-source p { margin: 0; }
    .decision-review {
      padding: 13px 18px 15px;
      border-top: 1px solid var(--line);
    }
    .decisions-readonly .decision-toolbar,
    .decisions-readonly .decision-actions,
    .decisions-readonly .decision-note { display: none; }
    .decision-card[data-group="late"] .decision-review { display: none; }
    .decision-actions { display: flex; flex-wrap: wrap; gap: 7px; }
    .decision-actions button[aria-pressed="true"][data-set-status="accept"] {
      border-color: #98c8b6;
      color: #175b45;
      background: var(--green-soft);
    }
    .decision-actions button[aria-pressed="true"][data-set-status="change"] {
      border-color: #e1b49f;
      color: #8f3c20;
      background: var(--accent-soft);
    }
    .decision-actions button[aria-pressed="true"][data-set-status="defer"] {
      border-color: #d7c18f;
      color: #715015;
      background: var(--amber-soft);
    }
    .decision-note { margin-top: 10px; }
    .decision-note summary {
      width: max-content;
      color: var(--muted);
      font-size: 11px;
      cursor: pointer;
    }
    .decision-note textarea {
      width: 100%;
      margin-top: 8px;
      padding: 9px 10px;
      resize: vertical;
      border: 1px solid var(--line);
      border-radius: 8px;
      color: var(--ink);
      background: #fff;
      font-size: 13px;
      line-height: 1.5;
      outline: none;
    }
    .decision-note textarea:focus { border-color: var(--ink); box-shadow: 0 0 0 3px rgba(29, 33, 31, 0.08); }
    .decision-print-state {
      margin: 9px 0 0;
      color: var(--muted);
      font-size: 11px;
    }
    .operator-rule {
      margin: 38px 0 0;
      padding: 15px 17px;
      border: 1px solid #e0b69f;
      border-radius: 10px;
      color: #76361f;
      background: var(--accent-soft);
      font-weight: 650;
    }
    .manifest {
      margin-top: 72px;
      padding-top: 28px;
      color: var(--muted);
      font-size: 12px;
    }
    .manifest details { margin-top: 12px; }
    .manifest summary { cursor: pointer; }
    .manifest table { margin-top: 12px; font-size: 10px; }
    .manifest td:last-child code { word-break: break-all; }

    @media (hover: hover) and (pointer: fine) {
      .hero-actions a:hover,
      .decision-toolbar button:hover,
      .decision-actions button:hover { border-color: var(--line-strong); }
    }
    @media (max-width: 980px) {
      html { scroll-padding-top: 0; }
      .layout { display: block; }
      .sidebar {
        position: relative;
        width: 100%;
        height: auto;
        max-height: 52vh;
        border-right: 0;
        border-bottom: 1px solid var(--line);
      }
      main { padding: 46px 24px 90px; }
      .reading-guide { grid-template-columns: 1fr; }
      .decision-toolbar { position: relative; top: auto; }
    }
    @media (max-width: 680px) {
      main { padding-inline: 17px; }
      .hero { padding-top: 20px; }
      .hero h1 { font-size: 42px; }
      .hero-lead { font-size: 17px; }
      .decision-copy { grid-template-columns: 1fr; }
      .decision-basis { border-top: 1px solid var(--line); border-left: 0; }
      .decision-toolbar { grid-template-columns: 1fr; }
      .decision-toolbar-actions, .decision-progress { grid-column: 1; }
      .decision-toolbar .button-quiet { margin-left: 0; }
      .document-section { padding-top: 58px; }
      .document-header h2 { font-size: 35px; }
    }
    @media (prefers-reduced-motion: reduce) {
      .nav-document summary::after,
      .hero-actions a,
      .decision-toolbar button,
      .decision-actions button,
      .decision-progress span { transition-duration: 0ms; }
    }
    @media print {
      :root { --paper: #fff; --surface: #fff; --surface-2: #f3f3f3; }
      body { font-size: 10pt; }
      .reading-progress, .sidebar, .hero-actions, .decision-toolbar,
      .decision-actions, .decision-note summary { display: none !important; }
      .layout { display: block; }
      main { width: 100%; padding: 0; }
      .hero { padding-top: 0; }
      .hero h1 { font-size: 34pt; }
      .document-section { break-before: page; padding-top: 0; }
      .decision-card { break-inside: avoid; box-shadow: none; }
      .decision-note[open] textarea { border: 0; padding: 0; resize: none; }
      .decision-print-state { color: #000; font-weight: 700; }
      a { color: inherit; text-decoration: none; }
    }
  </style>
</head>
<body>
  <div class="reading-progress" aria-hidden="true"><span id="reading-progress-bar"></span></div>
  <div class="layout">
    <aside class="sidebar">
      <a class="brand" href="#top">
        <span class="brand-mark">W</span>
        <span class="brand-copy"><strong>WEA vNext</strong><span>операторская проверка</span></span>
      </a>
      <label class="sr-only" for="nav-search">Поиск по навигации</label>
      <input class="nav-search" id="nav-search" type="search" placeholder="Раздел или требование…" autocomplete="off">
      <p class="search-hint">Поиск здесь фильтрует оглавление. Ctrl+F — весь текст.</p>
      <nav class="primary-nav" aria-label="Оглавление">
        <a href="#top">Начало <span>кандидат __REVISION__</span></a>
        <a href="#reading-guide">Как читать <span>источники</span></a>
        __NAV__
      </nav>
    </aside>

    <main id="top">
      <header class="hero">
        <p class="hero-kicker">__HERO_KICKER__</p>
        <h1>WEA vNext</h1>
        <p class="hero-lead">__HERO_LEAD__</p>
        <div class="hero-status" aria-label="Статус пакета">
          <span class="status-pill">__PACKAGE_STATUS__</span>
          <span class="status-pill">__CORE_STATUS_LABEL__: __CORE_DECISION_COUNT__</span>
          <span class="status-pill">Отложено: __LATE_DECISION_COUNT__</span>
          <span class="status-pill">Кандидат __REVISION__</span>
        </div>
        <div class="hero-actions">
          <a class="primary" href="__PRIMARY_HREF__">__PRIMARY_LABEL__</a>
          <a class="secondary" href="#doc-outcome">Читать основу системы</a>
        </div>
      </header>

      __ATTENTION__

      <section class="reading-guide" id="reading-guide">
        <div>
          <p class="eyebrow">Порядок чтения</p>
          <h2>Сначала статус, затем основной пакет</h2>
          <p>
            Рекомендуемый маршрут: handoff → план реализации → техническое устройство →
            утверждённое поведение по необходимости → приложения.
          </p>
          <p>__DECISION_GUIDE__</p>
        </div>
        <div>
          <p class="eyebrow">Легенда источников</p>
          <ul class="legend">__LEGEND__</ul>
        </div>
      </section>

      __SECTIONS__

      <footer class="manifest">
        <strong>Состав исходных файлов</strong>
        <p>
          SHA-256 набора: <code>__DIGEST__</code>. HTML автономен; внешние шрифты,
          скрипты и сетевые запросы не используются.
        </p>
        <details>
          <summary>Хеши Markdown и сборщика</summary>
          <div class="table-wrap">
            <table><thead><tr><th>Файл</th><th>SHA-256</th></tr></thead><tbody>__MANIFEST__</tbody></table>
          </div>
        </details>
      </footer>
    </main>
  </div>

  <script>
    (function () {
      "use strict";

      var STORAGE_KEY = "wea-vnext-review-__REVISION__";
      var STATUS_LABELS = {
        pending: "не решено",
        accept: "принять рекомендацию",
        change: "изменить рекомендацию",
        defer: "отложить"
      };
      var cards = Array.prototype.slice.call(document.querySelectorAll(".decision-card"));
      var activeFilter = "all";
      var reviewState = {};

      function safeLoad() {
        try {
          reviewState = JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}");
        } catch (error) {
          reviewState = {};
        }
      }

      function safeSave() {
        try {
          localStorage.setItem(STORAGE_KEY, JSON.stringify(reviewState));
        } catch (error) {
          return;
        }
      }

      function stateFor(card) {
        var id = card.getAttribute("data-decision-id");
        var fingerprint = card.getAttribute("data-decision-fingerprint");
        var defaultStatus = card.getAttribute("data-group") === "late" ? "defer" : "pending";
        var saved = reviewState[id];
        if (saved && saved.fingerprint === fingerprint) { return saved; }
        return {
          status: defaultStatus,
          note: saved && saved.note ? saved.note : "",
          fingerprint: fingerprint
        };
      }

      function applyCardState(card) {
        var state = stateFor(card);
        var status = state.status || "pending";
        card.setAttribute("data-decision-status", status);
        Array.prototype.forEach.call(card.querySelectorAll("[data-set-status]"), function (button) {
          button.setAttribute("aria-pressed", String(button.getAttribute("data-set-status") === status));
        });
        var note = card.querySelector("textarea");
        if (note && note.value !== (state.note || "")) {
          note.value = state.note || "";
        }
        var printState = card.querySelector(".decision-print-state");
        var noteText = state.note ? " · Комментарий: " + state.note : "";
        printState.textContent = "Статус: " + STATUS_LABELS[status] + noteText;
      }

      function updateDecisionProgress() {
        var actionableCards = cards.filter(function (card) {
          return card.getAttribute("data-group") === "core";
        });
        var done = actionableCards.filter(function (card) {
          return stateFor(card).status !== "pending";
        }).length;
        document.getElementById("decision-done-count").textContent = String(done);
        document.getElementById("decision-progress-bar").style.width =
          String((actionableCards.length ? done / actionableCards.length : 0) * 100) + "%";
      }

      function applyDecisionFilter() {
        var query = document.getElementById("decision-search").value.trim().toLowerCase();
        cards.forEach(function (card) {
          var status = stateFor(card).status || "pending";
          var group = card.getAttribute("data-group");
          var filterMatch =
            activeFilter === "all" ||
            (activeFilter === "pending" && status === "pending") ||
            activeFilter === group;
          var searchMatch =
            !query || (card.getAttribute("data-search") || "").indexOf(query) !== -1;
          card.hidden = !(filterMatch && searchMatch);
        });
        Array.prototype.forEach.call(document.querySelectorAll(".decision-group-section"), function (group) {
          group.hidden = !group.querySelector(".decision-card:not([hidden])");
        });
      }

      function setDecisionStatus(card, status) {
        var id = card.getAttribute("data-decision-id");
        var previous = stateFor(card);
        reviewState[id] = {
          status: status,
          note: previous.note || "",
          fingerprint: card.getAttribute("data-decision-fingerprint")
        };
        safeSave();
        applyCardState(card);
        updateDecisionProgress();
        applyDecisionFilter();
        if (status === "change") {
          var details = card.querySelector(".decision-note");
          details.open = true;
          card.querySelector("textarea").focus();
        }
      }

      function exportMarkdown() {
        var lines = [
          "# WEA vNext — решения оператора",
          "",
          "- Версия кандидата: __REVISION__",
          "- Основа: __BASE_SHA__",
          "- Хеш исходных файлов: __DIGEST__",
          ""
        ];
        cards
          .filter(function (card) {
            return card.getAttribute("data-group") === "core";
          })
          .forEach(function (card) {
          var id = card.getAttribute("data-decision-id");
          var state = stateFor(card);
          lines.push("## " + id + " — " + card.getAttribute("data-title"));
          lines.push("");
          lines.push("**Решение:** " + STATUS_LABELS[state.status || "pending"]);
          if (state.note) {
            lines.push("");
            lines.push("**Комментарий:** " + state.note.trim());
          }
          lines.push("");
          var sourceLabel = card.getAttribute("data-group") === "late" ?
            "**Когда вернуться:** " : "**Исходная рекомендация:** ";
          lines.push(sourceLabel +
            card.querySelector(".decision-recommendation .copy-source").innerText.trim());
          lines.push("");
          });
        return lines.join("\n");
      }

      function downloadReview() {
        var blob = new Blob([exportMarkdown()], { type: "text/markdown;charset=utf-8" });
        var url = URL.createObjectURL(blob);
        var link = document.createElement("a");
        link.href = url;
        link.download = "wea-vnext-operator-review.md";
        document.body.appendChild(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(url);
      }

      function copyReview(button) {
        var text = exportMarkdown();
        function showDone() {
          var prior = button.textContent;
          button.textContent = "Скопировано";
          window.setTimeout(function () { button.textContent = prior; }, 1400);
        }
        if (navigator.clipboard && window.isSecureContext) {
          navigator.clipboard.writeText(text).then(showDone);
          return;
        }
        var field = document.createElement("textarea");
        field.value = text;
        field.style.position = "fixed";
        field.style.opacity = "0";
        document.body.appendChild(field);
        field.select();
        document.execCommand("copy");
        field.remove();
        showDone();
      }

      safeLoad();
      cards.forEach(function (card) {
        applyCardState(card);
        Array.prototype.forEach.call(card.querySelectorAll("[data-set-status]"), function (button) {
          button.addEventListener("click", function () {
            setDecisionStatus(card, button.getAttribute("data-set-status"));
          });
        });
        card.querySelector("textarea").addEventListener("input", function (event) {
          var id = card.getAttribute("data-decision-id");
          var previous = stateFor(card);
          reviewState[id] = {
            status: previous.status || "pending",
            note: event.target.value,
            fingerprint: card.getAttribute("data-decision-fingerprint")
          };
          safeSave();
          applyCardState(card);
        });
      });
      updateDecisionProgress();

      Array.prototype.forEach.call(document.querySelectorAll("[data-filter]"), function (button) {
        button.addEventListener("click", function () {
          activeFilter = button.getAttribute("data-filter");
          Array.prototype.forEach.call(document.querySelectorAll("[data-filter]"), function (item) {
            item.setAttribute("aria-pressed", String(item === button));
          });
          applyDecisionFilter();
        });
      });
      document.getElementById("decision-search").addEventListener("input", applyDecisionFilter);
      document.getElementById("export-review").addEventListener("click", downloadReview);
      document.getElementById("copy-review").addEventListener("click", function (event) {
        copyReview(event.currentTarget);
      });
      document.getElementById("reset-review").addEventListener("click", function () {
        if (!window.confirm("Сбросить все локальные решения и комментарии?")) {
          return;
        }
        reviewState = {};
        safeSave();
        cards.forEach(applyCardState);
        updateDecisionProgress();
        applyDecisionFilter();
      });
      var nextUnresolved = document.getElementById("next-unresolved");
      if (nextUnresolved) { nextUnresolved.addEventListener("click", function () {
        var target = cards.find(function (card) {
          return stateFor(card).status === "pending" && !card.hidden;
        });
        if (!target) {
          activeFilter = "pending";
          document.querySelector("[data-filter='pending']").click();
          target = cards.find(function (card) { return stateFor(card).status === "pending"; });
        }
        if (target) {
          target.scrollIntoView({ block: "start" });
          target.focus({ preventScroll: true });
        }
      }); }

      var navSearch = document.getElementById("nav-search");
      navSearch.addEventListener("input", function () {
        var query = navSearch.value.trim().toLowerCase();
        Array.prototype.forEach.call(document.querySelectorAll(".nav-document"), function (details) {
          var summaryText = details.querySelector("summary").innerText.toLowerCase();
          var links = Array.prototype.slice.call(details.querySelectorAll(".nav-subsections a"));
          var matchingLinks = 0;
          links.forEach(function (link) {
            var match = !query || (link.getAttribute("data-nav-text") || "").indexOf(query) !== -1;
            link.parentElement.classList.toggle("nav-empty", !match);
            if (match) { matchingLinks += 1; }
          });
          var documentMatch = !query || summaryText.indexOf(query) !== -1 || matchingLinks > 0;
          details.classList.toggle("nav-empty", !documentMatch);
          if (query && documentMatch) { details.open = true; }
        });
      });

      var progressBar = document.getElementById("reading-progress-bar");
      function updateReadingProgress() {
        var maxScroll = document.documentElement.scrollHeight - window.innerHeight;
        var ratio = maxScroll > 0 ? window.scrollY / maxScroll : 0;
        progressBar.style.width = String(Math.max(0, Math.min(1, ratio)) * 100) + "%";
      }
      window.addEventListener("scroll", updateReadingProgress, { passive: true });
      updateReadingProgress();

      var navLinks = Array.prototype.slice.call(document.querySelectorAll(".primary-nav a[href^='#']"));
      var observed = Array.prototype.slice.call(document.querySelectorAll("main section[id], main h3[id], main h4[id]"));
      if ("IntersectionObserver" in window) {
        var observer = new IntersectionObserver(function (entries) {
          var visible = entries
            .filter(function (entry) { return entry.isIntersecting; })
            .sort(function (a, b) { return a.boundingClientRect.top - b.boundingClientRect.top; });
          if (!visible.length) { return; }
          var id = visible[0].target.id;
          navLinks.forEach(function (link) {
            link.classList.toggle("active", link.getAttribute("href") === "#" + id);
          });
        }, { rootMargin: "-8% 0px -82% 0px", threshold: 0 });
        observed.forEach(function (node) { observer.observe(node); });
      }

      Array.prototype.forEach.call(document.querySelectorAll(".markdown-body table, .manifest table"), function (table) {
        if (table.parentElement.classList.contains("table-wrap")) { return; }
        var wrapper = document.createElement("div");
        wrapper.className = "table-wrap";
        table.parentNode.insertBefore(wrapper, table);
        wrapper.appendChild(table);
      });
    }());
  </script>
</body>
</html>
"""

    output = (
        template.replace("__REVISION__", PACKAGE_REVISION)
        .replace("__BASE_SHA__", BASE_SHA)
        .replace("__DIGEST_SHORT__", source_digest[:12])
        .replace("__DIGEST__", source_digest)
        .replace("__HERO_KICKER__", hero_kicker)
        .replace("__HERO_LEAD__", hero_lead)
        .replace("__PACKAGE_STATUS__", package_status)
        .replace("__CORE_STATUS_LABEL__", core_status_label)
        .replace("__PRIMARY_HREF__", primary_href)
        .replace("__PRIMARY_LABEL__", primary_label)
        .replace("__CORE_DECISION_COUNT__", core_status_count)
        .replace("__LATE_DECISION_COUNT__", str(decision_counts["late"]))
        .replace("__DECISION_GUIDE__", decision_guide)
        .replace("__NAV__", "".join(nav_sections))
        .replace("__LEGEND__", legend_html)
        .replace("__ATTENTION__", "".join(attention_sections))
        .replace("__SECTIONS__", "".join(sections))
        .replace("__MANIFEST__", manifest_html)
    )
    output = "\n".join(line.rstrip() for line in output.splitlines()) + "\n"
    if check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != output:
            raise ValueError(f"Generated artifact is stale: {OUTPUT}")
    else:
        OUTPUT.write_text(output, encoding="utf-8", newline="\n")
    print(
        json.dumps(
            {
                "output": str(OUTPUT),
                "documents": len(DOCUMENTS),
                "decisions": decision_count,
                "core_decisions": decision_counts["core"],
                "late_decisions": decision_counts["late"],
                "source_digest": source_digest,
                "bytes": len(output.encode("utf-8")),
                "check": check,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    build(check=parser.parse_args().check)
