# ruff: noqa: E501, RUF001
"""Build and validate the self-contained WEA vNext operator review."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

ARTIFACT_VERSION = "2026-08-18.1"
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUTPUT = HERE / "WEA_vNext_SDD_REVIEW.html"
ACCEPTANCE_OUTPUT = HERE / "WEA_vNext_ACCEPTED_DECISIONS.txt"
BLOCK9_ACCEPTANCE_OUTPUT = HERE / "WEA_vNext_BLOCK9_ACCEPTANCE.txt"
BASE_SHA = "0ea6513"
PARENT = ROOT / "oled/changes/wea-vnext-recreation"
BLOCK9 = ROOT / "oled/changes/wea-vnext-block9-cutover"
ACCEPTED_BLOCK9_OUTCOME_SHA256 = (
    "e9cbdcc924c8e01cae3240885e272fc75a7595bae1dcab4ee4034e6d439d1f67"
)
ACCEPTED_BLOCK9_SPEC_SHA256 = (
    "25c65e999bb158d773fa7d46c5e566cd36f5a7eb4b8b8aff272274d8efe59dfa"
)
PRE_ACCEPTANCE_DECISION_PAYLOAD_SHA256 = (
    "100957844bcf3e9a1207ba95c2225acc74d3fb292a2684bd257a7ea7094a1c9e"
)

SOURCE_FILES = (
    HERE / "build_sdd_review.py",
    HERE / "outcome.md",
    HERE / "spec.md",
    HERE / "design.md",
    HERE / "tasks.md",
    HERE / "verification.md",
    HERE / "operator-review.md",
    PARENT / "HANDOFF.md",
    PARENT / "build_review_html.py",
    PARENT / "open-decisions.md",
    PARENT / "outcome.md",
    PARENT / "spec.md",
    PARENT / "design.md",
    PARENT / "tasks.md",
    PARENT / "verification.md",
    PARENT / "migration.md",
    PARENT / "delta.md",
    PARENT / "schema.md",
    BLOCK9 / "outcome.md",
    BLOCK9 / "spec.md",
    BLOCK9 / "verification.md",
    BLOCK9 / "HANDOFF.md",
    ROOT / "docs/VNEXT_BOUNDARY.md",
    ROOT / "src/wea_vnext/financial_correction.py",
    ROOT / "tests/vnext/scenarios.py",
    ROOT / "tests/vnext/test_correction.py",
    ROOT / "tests/vnext/test_scenario_registry.py",
    ROOT / "tests/vnext/test_runtime_boundary.py",
)

DECISIONS = (
    {
        "id": "SDD-01",
        "title": "Принять честное ограничение RED-доказательства",
        "question": "Достаточно ли поздней проверки старого кода и полного текущего набора тестов?",
        "why": (
            "Исходный вывод первого красного запуска не сохранился. Мы не "
            "подменяем его. Старый код проверен отдельно: точный S13C test-модуль "
            "не загружается, потому что production-модуля ещё нет."
        ),
        "recommended": "Принять ограничение",
        "change": "Нужна другая проверка",
        "defer": "Отложить решение",
        "effect": "Закрывает исторический пробел без ложного заявления о пропавшем логе.",
        "note": "",
    },
    {
        "id": "SDD-02",
        "title": "Одобрить документальную сверку",
        "question": "Подтверждаем ли, что обновлённые SDD-записи верно описывают уже принятую систему?",
        "why": (
            "Исправлены устаревшие статусы, добавлена история версий и точная "
            "связь требований с тестами. Производственное поведение не менялось."
        ),
        "recommended": "Одобрить сверку",
        "change": "Нужны изменения",
        "defer": "Отложить решение",
        "effect": "Закрывает документальные блокеры. vNext остаётся выключенным.",
        "note": "",
    },
    {
        "id": "OD-28",
        "title": "Gauntlet mint при первом cutover",
        "question": "Переносить ли старый механизм создания WEA в первый vNext cutover?",
        "why": (
            "Без отдельного контракта перенос создаёт скрытый денежный путь. "
            "Безопаснее сохранить прошлые записи для чтения и не создавать новые."
        ),
        "recommended": "Не переносить",
        "change": "Спроектировать перенос",
        "defer": "Отложить решение",
        "effect": "Первый cutover не получает неописанный источник mint. Позже возможна отдельная поставка.",
        "note": "Вариант А: убрать gauntlet mint из первого cutover.",
    },
    {
        "id": "OD-29",
        "title": "Achievements и transform при первом cutover",
        "question": "Разрешать ли новые award/revoke/transform записи в первом cutover?",
        "why": (
            "Их связь с genome и Release ещё не согласована. Историю можно "
            "сохранить для чтения, не перенося неопределённые write-пути."
        ),
        "recommended": "Только история",
        "change": "Спроектировать перенос",
        "defer": "Отложить решение",
        "effect": "Убирает неопределённые governance-записи из первого переключения.",
        "note": "Вариант А. Будущий механизм важен для ikigai и поиска идентичности, но требует отдельной задачи.",
    },
    {
        "id": "NEXT-01",
        "title": "Разрешить только Block 9 discovery/design",
        "question": "Можно ли начать инвентаризацию writers и проектирование миграции без активации?",
        "why": (
            "Следующий безопасный шаг — выяснить все write-пути, сверить ledger и "
            "спроектировать genesis, shadow replay, транзакции и восстановление."
        ),
        "recommended": "Разрешить design",
        "change": "Изменить границы",
        "defer": "Отложить этап",
        "effect": "Разрешает только новый SDD-пакет. Live-запись, credentials и cutover запрещены.",
        "note": (
            "Приняты остальные рекомендации. Направление Block 9 Design "
            "разрешено в принципе; точный BDD отдельно принят 2026-08-17."
        ),
    },
    {
        "id": "BLOCK9-ACCEPT-01",
        "title": "Принять Block 9 Outcome/Spec 1.0",
        "question": "Принимается ли точный Block 9 Outcome/Spec 1.0 без изменений?",
        "why": (
            "Этот отдельный gate превращает S-71–S-79 из материала для чтения "
            "в обязательный контракт для Design. Он не разрешает реализацию "
            "или включение vNext."
        ),
        "recommended": "Принять без изменений",
        "change": "Нужны изменения",
        "defer": "Отложить решение",
        "effect": "Разрешает Block 9 Design. Реализация и live cutover остаются запрещены.",
        "note": "Принимаю Block 9 Outcome/Spec 1.0 без изменений.",
    },
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def decision_payload() -> str:
    payload = [
        {
            "choice": "recommended",
            "id": item["id"],
            "label": item["recommended"],
            "note": item["note"],
        }
        for item in DECISIONS
    ]
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def decision_payload_hash() -> str:
    return hashlib.sha256(decision_payload().encode("utf-8")).hexdigest()


def candidate_package_identity(fingerprint: str) -> str:
    payload = "\0".join(
        (ARTIFACT_VERSION, BASE_SHA, fingerprint, decision_payload_hash())
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def acceptance_record(fingerprint: str) -> str:
    lines = [
        "WEA vNext — deterministic record of operator decisions",
        f"Artifact version: {ARTIFACT_VERSION}",
        "Authority dates: 2026-08-16 and 2026-08-17",
        (
            "Authority source: operator messages in the current Codex task; "
            "no independently authenticated repository revision is available."
        ),
        f"Local base: {BASE_SHA}",
        f"Selected-source fingerprint SHA-256: {fingerprint}",
        f"Prepared candidate package SHA-256: {candidate_package_identity(fingerprint)}",
        f"Decision payload SHA-256: {decision_payload_hash()}",
        (
            "Evidence meaning: derived self-consistency record; not standalone "
            "proof of an operator act."
        ),
        (
            "Scope: Block 9 Outcome/Spec 1.0 is accepted for Design; "
            "implementation and activation remain unauthorized."
        ),
        "",
    ]
    for item in DECISIONS:
        lines.append(f'{item["id"]}: {item["recommended"]}')
        if item["note"]:
            lines.append(f'Комментарий: {item["note"]}')
        lines.append("")
    return "\n".join(lines)


def block9_acceptance_record() -> str:
    return "\n".join(
        (
            "WEA vNext — exact Block 9 Outcome/Spec acceptance binding",
            "Contract version: 1.0",
            "Authority date: 2026-08-17",
            "Authority wording: Принимаю Block 9 Outcome/Spec 1.0 без изменений.",
            (
                "Authority source: operator message in the current Codex task; "
                "this derived manifest is not standalone identity proof."
            ),
            "Outcome path: oled/changes/wea-vnext-block9-cutover/outcome.md",
            f"Outcome SHA-256: {ACCEPTED_BLOCK9_OUTCOME_SHA256}",
            "Spec path: oled/changes/wea-vnext-block9-cutover/spec.md",
            f"Spec SHA-256: {ACCEPTED_BLOCK9_SPEC_SHA256}",
            (
                "Candidate-preparation decision payload SHA-256: "
                f"{PRE_ACCEPTANCE_DECISION_PAYLOAD_SHA256}"
            ),
            f"Acceptance decision payload SHA-256: {decision_payload_hash()}",
            (
                "Meaning: these exact bytes are accepted for Design only; "
                "implementation and activation remain unauthorized."
            ),
            (
                "Status rule: proposed/pending wording inside the pinned files "
                "is the immutable preparation-time snapshot; this later manifest "
                "records its exact acceptance without rewriting those bytes."
            ),
            (
                "Drift rule: byte changes require a new contract version and "
                "a new exact operator acceptance before the builder can pass."
            ),
            "",
        )
    )


def validate_accepted_block9_contract() -> None:
    actual = {
        "Outcome": _sha256(BLOCK9 / "outcome.md"),
        "Spec": _sha256(BLOCK9 / "spec.md"),
    }
    expected = {
        "Outcome": ACCEPTED_BLOCK9_OUTCOME_SHA256,
        "Spec": ACCEPTED_BLOCK9_SPEC_SHA256,
    }
    mismatches = [
        f"{name} SHA-256 {actual[name]} != accepted {expected[name]}"
        for name in actual
        if actual[name] != expected[name]
    ]
    if mismatches:
        raise SystemExit(
            "Accepted Block 9 contract drifted; version and accept it again:\n- "
            + "\n- ".join(mismatches)
        )


def validate_sources() -> None:
    candidate_hash_token = (
        f"Decision payload SHA-256: `{PRE_ACCEPTANCE_DECISION_PAYLOAD_SHA256}`"
    )
    checks = {
        HERE / "outcome.md": (
            "**Version:** 1.0",
            "Accepted and delivered as an inactive control plane",
            "## Version history",
            "accepted-future Block 9 scenarios",
        ),
        HERE / "spec.md": (
            "**Version:** 1.1",
            "## Version history",
            "**GIVEN:**",
            "**WHEN:**",
            "**THEN:**",
            "**EVIDENCE:**",
            "test_s_13c_1_proposal_hash_binds_the_exact_payload",
        ),
        HERE / "design.md": (
            "**Revision:** 1.1",
            "## Revision history",
            "does not change Design 1.1",
        ),
        HERE / "tasks.md": (
            "**Version:** 1.4",
            "Block 9 BDD accepted",
            "SDD-01",
            "NEXT-01",
        ),
        HERE / "verification.md": (
            "**Version:** 1.4",
            "Block 9 BDD accepted; Design next",
            "ModuleNotFoundError: No module named 'wea_vnext.financial_correction'",
            "0ea6513",
        ),
        PARENT / "HANDOFF.md": (
            "70 current, 9 accepted-future, and zero",
            "proposed-future Block 9 scenarios",
            "Block 9 Outcome/BDD 1.0 accepted",
        ),
        PARENT / "outcome.md": (
            "Текущий составной Outcome: `1.2`",
            "| 1.2 | 2026-08-17 |",
        ),
        PARENT / "open-decisions.md": (
            "Решения оператора 2026-08-16",
            "Решение оператора 2026-08-17",
            "BLOCK9-ACCEPT-01",
            "OD-28",
            "OD-29",
            "NEXT-01",
        ),
        PARENT / "spec.md": (
            "Current overlay — 2026-08-17",
            "70 current / 9 accepted-future / 0 proposed-future",
        ),
        PARENT / "design.md": (
            "Current overlay — 2026-08-17",
            "Block 9 Outcome/Spec 1.0 is accepted",
        ),
        PARENT / "tasks.md": (
            "Current overlay — 2026-08-17",
            "70 current / 9 accepted-future / 0 proposed-future",
        ),
        PARENT / "verification.md": (
            "Historical delivery record — current overlay 2026-08-17",
            "verification.md` version 1.4",
            "70 current / 9 accepted-future / 0 proposed-future",
        ),
        PARENT / "migration.md": (
            "migration decision overlay 1.2",
            "| 1.2 | 2026-08-17 |",
        ),
        PARENT / "delta.md": (
            "decision delta 1.2",
            "| 1.2 | 2026-08-17 |",
        ),
        BLOCK9 / "outcome.md": (
            "Outcome: WEA vNext Block 9 Cutover",
            "pending operator review",
            "WEA vNext Outcome 1.1",
            "migration decision",
            "overlay 1.1",
            "identity discovery",
            candidate_hash_token,
        ),
        BLOCK9 / "spec.md": (
            "Spec version: `1.0`",
            "Status: `proposed for operator review; not implemented; not live`",
            "Decision overlay 1.1",
            "Scenario S-71:",
            "Scenario S-79:",
            candidate_hash_token,
        ),
        ROOT / "tests/vnext/test_scenario_registry.py": (
            "== 70",
            'CORRECTION_SCENARIO_IDS == ("S-13C",)',
            "BLOCK9_SCENARIO_IDS == block9_headings",
        ),
        ROOT / "tests/vnext/scenarios.py": (
            "BLOCK9_SCENARIO_IDS",
            "ACCEPTED_FUTURE_SCENARIO_IDS = BLOCK9_SCENARIO_IDS",
        ),
        ROOT / "docs/VNEXT_BOUNDARY.md": (
            "70 current scenarios, 9 accepted-future Block 9 scenarios",
            "zero proposed-future scenarios",
            "Accepted-future is binding for Design",
        ),
        ROOT / "tests/vnext/test_correction.py": (
            "test_s_13c_1_rejects_incomplete_or_duplicate_proposal_inputs",
            "test_s_13c_1_proposal_hash_binds_the_exact_payload",
            "test_s_13c_3_requires_exact_binding_snapshot_and_one_approval_per_role",
            "test_s_13c_4_rejects_zero_delta_posting",
        ),
    }
    failures: list[str] = []
    for path, tokens in checks.items():
        content = _read(path)
        for token in tokens:
            if token not in content:
                failures.append(f"{path.relative_to(ROOT)}: missing {token!r}")
    if failures:
        raise SystemExit("Source validation failed:\n- " + "\n- ".join(failures))


def source_fingerprint() -> str:
    digest = hashlib.sha256()
    for path in SOURCE_FILES:
        digest.update(path.relative_to(ROOT).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


class _ArtifactParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []
        self.hrefs: list[str] = []
        self.decisions: list[str] = []
        self.accepted_radios: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        values = dict(attrs)
        if values.get("id"):
            self.ids.append(values["id"] or "")
        if values.get("href"):
            self.hrefs.append(values["href"] or "")
        if values.get("data-decision"):
            self.decisions.append(values["data-decision"] or "")
        if (
            tag == "input"
            and values.get("type") == "radio"
            and values.get("value") == "recommended"
            and "checked" in values
            and "disabled" in values
        ):
            self.accepted_radios.append(values.get("name") or "")


def validate_rendered(rendered: str) -> None:
    parser = _ArtifactParser()
    parser.feed(rendered)
    problems: list[str] = []
    duplicates = sorted({value for value in parser.ids if parser.ids.count(value) > 1})
    if duplicates:
        problems.append(f"duplicate HTML IDs: {', '.join(duplicates)}")
    expected_decisions = [item["id"] for item in DECISIONS]
    if parser.decisions != expected_decisions:
        problems.append("decision cards do not match the six accepted decisions")
    if parser.accepted_radios != expected_decisions:
        problems.append("accepted decisions are not checked and locked exactly once")
    known_ids = set(parser.ids)
    for href in parser.hrefs:
        if href.startswith("#"):
            if href[1:] not in known_ids:
                problems.append(f"missing fragment target: {href}")
            continue
        split = urlsplit(href)
        if split.scheme == "data":
            continue
        if split.scheme or split.netloc:
            problems.append(f"external link is not allowed: {href}")
            continue
        target = (OUTPUT.parent / split.path).resolve()
        if not target.is_file():
            problems.append(f"missing local link target: {href}")
    if problems:
        raise SystemExit("Artifact validation failed:\n- " + "\n- ".join(problems))


def decision_cards() -> str:
    cards: list[str] = []
    for index, item in enumerate(DECISIONS, start=1):
        decision_id = item["id"]
        options = (
            ("recommended", item["recommended"], "Рекомендуется"),
            ("change", item["change"], "Нужно пояснение"),
            ("defer", item["defer"], "Оставит блокер"),
        )
        option_html = []
        for value, label, hint in options:
            control_id = f"{decision_id}-{value}"
            selected = value == "recommended"
            checked = " checked" if selected else ""
            option_html.append(
                f'<label class="choice" for="{control_id}">'
                f'<input id="{control_id}" type="radio" '
                f'name="{decision_id}" value="{value}" '
                f'data-label="{html.escape(label)}"{checked} disabled>'
                f'<span><strong>{html.escape(label)}</strong><small>{html.escape(hint)}</small></span>'
                "</label>"
            )
        cards.append(
            f'<article class="decision selected" id="decision-{decision_id}" data-decision="{decision_id}">'
            f'<div class="decision-head"><span class="number">{index}</span><div>'
            f'<p class="eyebrow">{decision_id}</p><h3>{html.escape(item["title"])}</h3></div>'
            '<span class="decision-state" aria-live="polite">Принято</span></div>'
            f'<p class="question">{html.escape(item["question"])}</p>'
            f'<p>{html.escape(item["why"])}</p>'
            f'<div class="effect"><strong>Принятый результат:</strong> {html.escape(item["effect"])}</div>'
            f'<div class="choices" role="radiogroup" aria-label="Решение {decision_id}">{"".join(option_html)}</div>'
            f'<label class="note-label" for="note-{decision_id}">Комментарий оператора</label>'
            f'<textarea id="note-{decision_id}" data-note="{decision_id}" rows="2" '
            f'disabled>{html.escape(item["note"])}</textarea>'
            "</article>"
        )
    return "\n".join(cards)


def build_html() -> str:
    fingerprint = source_fingerprint()
    accepted_record = acceptance_record(fingerprint)
    template = r'''<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light">
<link rel="icon" href="data:,">
<title>WEA vNext — принятые решения и Block 9 BDD</title>
<style>
:root{--ink:#17211d;--muted:#5d6963;--paper:#f5f2ea;--card:#fffdf8;--line:#d8d5ca;--green:#176b4d;--green-soft:#e4f2eb;--amber:#a75d11;--amber-soft:#fff0d8;--red:#a33b35;--navy:#17324d;--shadow:0 18px 50px rgba(23,33,29,.09)}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:linear-gradient(180deg,#e8efe9 0,#f5f2ea 22rem);color:var(--ink);font:16px/1.58 system-ui,-apple-system,"Segoe UI",sans-serif}button,input,textarea{font:inherit}a{color:var(--navy)}code{overflow-wrap:anywhere;word-break:break-all}.wrap{width:min(1120px,calc(100% - 32px));margin:auto}.hero{padding:56px 0 32px}.topline{display:flex;justify-content:space-between;gap:16px;align-items:center;margin-bottom:28px}.brand{font-weight:800;letter-spacing:.02em}.version{color:var(--muted);font-size:.9rem}.hero-grid{display:grid;grid-template-columns:1.4fr .6fr;gap:24px;align-items:stretch}.hero-main,.hero-aside{background:rgba(255,253,248,.92);border:1px solid rgba(255,255,255,.7);border-radius:24px;padding:32px;box-shadow:var(--shadow)}.eyebrow{margin:0 0 6px;color:var(--green);font-size:.78rem;font-weight:800;letter-spacing:.12em;text-transform:uppercase}.hero h1{font-size:clamp(2rem,5vw,4.2rem);line-height:1.02;letter-spacing:-.045em;margin:.15em 0 .35em}.lead{font-size:1.15rem;max-width:68ch}.safe{display:flex;gap:12px;padding:14px 16px;background:var(--green-soft);border-left:4px solid var(--green);border-radius:10px}.safe strong{display:block}.status-list{display:grid;gap:12px;margin-top:20px}.status{border:1px solid var(--line);border-radius:12px;padding:13px}.status b{display:block;font-size:1.3rem}.status small{color:var(--muted)}nav.sticky{position:sticky;top:0;z-index:5;background:rgba(245,242,234,.94);backdrop-filter:blur(12px);border-block:1px solid var(--line)}nav .wrap{display:flex;gap:8px;overflow:auto;padding-block:10px;scrollbar-width:none}nav .wrap::-webkit-scrollbar{display:none}nav a{white-space:nowrap;text-decoration:none;color:var(--ink);padding:8px 12px;border-radius:99px}nav a:hover,nav a:focus{background:#fff}.section{padding:48px 0}.section h2{font-size:clamp(1.65rem,3vw,2.5rem);letter-spacing:-.025em;margin:0 0 12px}.intro{max-width:75ch;color:var(--muted);font-size:1.05rem}.grid-4{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-top:24px}.plain-card,.finding,.step{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:20px}.plain-card h3,.finding h3{margin:0 0 8px}.plain-card p,.finding p{margin:.35em 0}.flow{display:grid;grid-template-columns:repeat(4,1fr);gap:24px;margin-top:26px;counter-reset:flow}.flow .step{position:relative}.flow .step:before{counter-increment:flow;content:counter(flow);display:grid;place-items:center;width:30px;height:30px;border-radius:50%;background:var(--navy);color:white;font-weight:800;margin-bottom:12px}.flow .step:not(:last-child):after{content:"→";position:absolute;right:-19px;top:32px;color:var(--muted);font-weight:800}.findings{display:grid;grid-template-columns:repeat(2,1fr);gap:14px;margin-top:24px}.tag{display:inline-block;border-radius:99px;padding:3px 9px;font-size:.76rem;font-weight:800}.tag.fixed{background:var(--green-soft);color:var(--green)}.tag.pending{background:var(--amber-soft);color:var(--amber)}.decision-shell{display:grid;grid-template-columns:minmax(0,1fr) 280px;gap:22px;align-items:start}.decision-list{display:grid;gap:18px}.decision{background:var(--card);border:1px solid var(--line);border-radius:20px;padding:24px;box-shadow:0 7px 24px rgba(23,33,29,.05)}.decision:has(input:checked){border-color:#8fbda9}.decision-head{display:flex;gap:14px;align-items:flex-start}.decision-head h3{margin:0;font-size:1.28rem}.number{display:grid;place-items:center;flex:0 0 36px;height:36px;border-radius:10px;background:var(--navy);color:#fff;font-weight:800}.decision-state{margin-left:auto;color:var(--amber);font-size:.84rem;font-weight:800}.decision.selected .decision-state{color:var(--green)}.question{font-weight:750}.effect{background:#eef3f6;border-radius:10px;padding:12px 14px;margin:14px 0}.choices{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:16px}.choice{display:flex;gap:9px;align-items:flex-start;border:1px solid var(--line);border-radius:12px;padding:12px;cursor:pointer}.choice:has(input:checked){border-color:var(--green);background:var(--green-soft)}.choice input{margin-top:4px}.choice strong,.choice small{display:block}.choice small{color:var(--muted);font-size:.76rem;margin-top:3px}.note-label{display:block;font-size:.82rem;font-weight:800;margin:16px 0 5px}textarea{width:100%;resize:vertical;border:1px solid var(--line);border-radius:10px;padding:10px;background:white;color:var(--ink)}.review-panel{position:sticky;top:72px;background:var(--navy);color:white;border-radius:20px;padding:22px}.review-panel h3{margin-top:0}.progress-track{height:10px;background:rgba(255,255,255,.18);border-radius:99px;overflow:hidden}.progress-bar{height:100%;width:0;background:#76d4aa;transition:width .2s}.progress-text{margin:8px 0 18px}.actions{display:grid;gap:9px}.btn{border:0;border-radius:10px;padding:11px 14px;font-weight:800;cursor:pointer}.btn.primary{background:#fff;color:var(--navy)}.btn.secondary{background:rgba(255,255,255,.12);color:#fff;border:1px solid rgba(255,255,255,.3)}.btn:focus-visible,.choice:focus-within,a:focus-visible,textarea:focus-visible{outline:3px solid #e9a94b;outline-offset:2px}.panel-note{font-size:.82rem;color:#dce7ee}.after{display:grid;grid-template-columns:1fr 1fr;gap:16px}.do,.dont{border-radius:16px;padding:22px}.do{background:var(--green-soft)}.dont{background:var(--amber-soft)}.do h3,.dont h3{margin-top:0}.source-list{columns:2;column-gap:30px}.source-list li{break-inside:avoid;margin:.5em 0}details{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px;margin:10px 0}summary{cursor:pointer;font-weight:800}footer{border-top:1px solid var(--line);padding:30px 0 60px;color:var(--muted);font-size:.88rem}.toast{position:fixed;right:18px;bottom:18px;background:var(--ink);color:white;border-radius:10px;padding:12px 16px;opacity:0;transform:translateY(10px);pointer-events:none;transition:.2s}.toast.show{opacity:1;transform:none}.print-only{display:none}@media(max-width:850px){.hero-grid,.decision-shell,.after{grid-template-columns:1fr}.grid-4,.flow{grid-template-columns:repeat(2,1fr)}.flow .step:after{display:none}.review-panel{position:static;order:-1}.choices{grid-template-columns:1fr}}@media(max-width:520px){.wrap{width:min(100% - 20px,1120px)}.hero{padding-top:28px}.hero-main,.hero-aside,.decision{padding:19px}.grid-4,.flow,.findings{grid-template-columns:1fr}.topline{align-items:flex-start;flex-direction:column}.source-list{columns:1}}@media print{body{background:white}.sticky,.actions,.toast{display:none!important}.wrap{width:100%}.hero-main,.hero-aside,.decision,.plain-card,.finding,.step{box-shadow:none;break-inside:avoid}.decision-shell{display:block}.review-panel{background:white;color:var(--ink);border:1px solid var(--line);margin-bottom:20px}.print-only{display:block}.section{padding:24px 0}}
</style>
</head>
<body>
<header class="hero"><div class="wrap"><div class="topline"><span class="brand">WeTheAgents / WEA vNext</span><span class="version">Пакет __VERSION__ · fingerprint __FINGERPRINT_SHORT__</span></div><div class="hero-grid"><section class="hero-main"><p class="eyebrow">Принятый контракт для следующего этапа</p><h1>Block 9 BDD принят. Следующий шаг — Design.</h1><p class="lead">S13C готов и слит. Шесть решений оператора записаны в SDD. Точный Block 9 Outcome/Spec 1.0 принят без изменений. vNext всё ещё выключен.</p><div class="safe"><span aria-hidden="true">✓</span><div><strong>Безопасная граница</strong>Сейчас разрешён только Design. Реализация, ledger, credentials и live cutover остаются запрещены до следующих отдельных gates.</div></div></section><aside class="hero-aside" aria-label="Текущий статус"><p class="eyebrow">Текущий статус</p><div class="status-list"><div class="status"><b>v1</b><small>Авторитетен, операционно на паузе</small></div><div class="status"><b>vNext</b><small>Неактивен, live writer отсутствует</small></div><div class="status"><b>70 / 9 / 0</b><small>Текущие / accepted-future / proposed-future</small></div><div class="status"><b>Design</b><small>Следующий разрешённый gate</small></div></div></aside></div></div></header>
<nav class="sticky" aria-label="Разделы"><div class="wrap"><a href="#short">Коротко</a><a href="#terms">Термины</a><a href="#findings">Блокеры</a><a href="#decisions">Решения</a><a href="#block9">Block 9 BDD</a><a href="#after">Следующий шаг</a><a href="#evidence">Источники</a></div></nav>
<div class="section"><div class="wrap"><div class="safe"><span aria-hidden="true">→</span><div><strong>Этот HTML сохраняет BDD-gate от 2026-08-17.</strong>Design 1.0 принят 2026-08-18. Текущий следующий gate — <a href="../wea-vnext-block9-cutover/WEA_vNext_BLOCK9_TASKS_REVIEW.html">review Tasks 2.0 в отдельном простом HTML</a>. Implementation и activation всё ещё не разрешены.</div></div></div></div>
<main>
<section class="section" id="short"><div class="wrap"><p class="eyebrow">Главное за минуту</p><h2>Правила согласованы. Теперь можно проектировать механизм.</h2><p class="intro">Circle-1 опубликован. Domain/Access и S13C работают только как неактивные библиотеки. Block 9 Outcome/Spec 1.0 теперь является принятым контрактом из девяти проверяемых условий. Он разрешает Design, но не реализацию и не включение vNext.</p><div class="flow"><div class="step"><strong>Основа готова</strong><p>Domain/Access и S13C проверены без live-записи.</p></div><div class="step"><strong>Решения приняты</strong><p>Gauntlet mint и активные achievements не входят в первый cutover.</p></div><div class="step"><strong>BDD принят</strong><p>Девять условий S-71–S-79 обязательны для Design.</p></div><div class="step"><strong>Сейчас: Design</strong><p>Технический проект должен объяснить механизм без изменения принятого поведения.</p></div></div></div></section>
<section class="section" id="terms"><div class="wrap"><p class="eyebrow">Без лишнего жаргона</p><h2>Четыре термина, которые нужны дальше</h2><div class="grid-4"><article class="plain-card"><h3>BDD</h3><p>Список наблюдаемых примеров: что дано, что происходит и какой результат обязателен.</p></article><article class="plain-card"><h3>SDD</h3><p>Полный пакет: цель, BDD-поведение, технический Design и Tasks. BDD является частью SDD.</p></article><article class="plain-card"><h3>Genesis</h3><p>Первая каноническая запись vNext. Она должна воспроизводить точное начальное состояние.</p></article><article class="plain-card"><h3>Cutover</h3><p>Будущий момент, когда право записи переходит от v1 к vNext.</p></article></div></div></section>
<section class="section" id="findings"><div class="wrap"><p class="eyebrow">Blocking findings</p><h2>Все прежние блокеры закрыты на уровне решений</h2><p class="intro">Технические исправления S13C уже проверены. Историческое ограничение доказательства принято честно. OD-28 и OD-29 теперь имеют явный результат.</p><div class="findings"><article class="finding"><span class="tag fixed">ПРИНЯТО</span><h3>Исторический RED-лог</h3><p>Исходный вывод не сохранился. Мы используем позднюю проверку старого кода и не заявляем, что потерянный лог существует.</p></article><article class="finding"><span class="tag fixed">ИСПРАВЛЕНО</span><h3>Статусы и версии SDD</h3><p>Родительские документы, сценарный реестр, handoff и HTML показывают одну текущую картину.</p></article><article class="finding"><span class="tag fixed">РЕШЕНО</span><h3>Gauntlet mint</h3><p>Первый cutover не переносит mint. История читается, но не создаёт WEA.</p></article><article class="finding"><span class="tag fixed">РЕШЕНО</span><h3>Achievements</h3><p>История читается без активного эффекта. Будущий ikigai-механизм будет отдельной работой.</p></article></div></div></section>
<section class="section" id="decisions"><div class="wrap"><p class="eyebrow">Зафиксированное согласование</p><h2>Шесть принятых решений</h2><p class="intro">Пять первых карточек фиксируют исходные бизнес-решения. Шестая отдельно фиксирует принятие точного Block 9 Outcome/Spec 1.0. Это производная запись чата, а не самостоятельное доказательство личности оператора. Итог можно скопировать или скачать.</p><div class="decision-shell"><div class="decision-list">__DECISION_CARDS__</div><aside class="review-panel"><h3>Готовность решений</h3><div class="progress-track" aria-hidden="true"><div class="progress-bar" id="progress-bar"></div></div><p class="progress-text" id="progress-text">6 из 6 решений приняты</p><div class="actions"><button class="btn primary" id="copy-decisions" type="button">Копировать итог</button><button class="btn secondary" id="download-decisions" type="button">Скачать .txt</button></div><p class="panel-note">Следующий gate — Block 9 Design. Реализация и live-активация запрещены.</p><p class="print-only" id="print-summary"></p></aside></div></div></section>
<section class="section" id="block9"><div class="wrap"><p class="eyebrow">Принятый BDD для Block 9</p><h2>Девять обязательных условий безопасного перехода</h2><p class="intro">Это принятый контракт для Design, но ещё не код. Design должен сохранить эти наблюдаемые правила и объяснить, как система их обеспечивает.</p><div class="findings"><article class="finding"><h3>S-71 · Ни один writer не пропущен</h3><p>Инвентарь сравнивается с независимо собранным замороженным списком. Пропуск, поздний writer или обход epoch guard блокируют cutover.</p></article><article class="finding"><h3>S-72 · Обязательства и conversion закрыты</h3><p>v1 escrow сначала полностью закрывается. Intent фиксирует точный согласованный Plan и автора-плательщика. После cutover один атомарный переход создаёт debit, program escrow, Plan, Task и первый дочерний Contract. Прямой Contract и двойной escrow запрещены.</p></article><article class="finding"><h3>S-73 · Genesis воспроизводим</h3><p>Одинаковые входы создают одинаковое состояние. Conversion intents сохраняются без активных Plans, Tasks, Contracts и replacement escrow.</p></article><article class="finding"><h3>S-74 · Shadow ничего не пишет</h3><p>Теневой прогон создаёт только повторяемый отчёт и не меняет GitHub или ledger.</p></article><article class="finding"><h3>S-75 · Один авторитетный writer</h3><p>Epoch и ledger bootstrap атомарны. Единственный writer — точно agent0@system через одобренную активную credential binding. Внешние проекции отделены.</p></article><article class="finding"><h3>S-76 · Gauntlet только в истории</h3><p>Старые mint-записи читаются, но не создают WEA в genesis или после него.</p></article><article class="finding"><h3>S-77 · Achievements только в истории</h3><p>Genesis сохраняет отдельно сверенный genome snapshot и не изменяет его replay истории achievements.</p></article><article class="finding"><h3>S-78 · Recovery существует до cutover</h3><p>До переключения нужны durable correction и replay repair с crash/restart доказательствами. Correction сохраняет все финансовые и tamper-гарантии S13C 1.1; текущий inactive S13C этого не даёт.</p></article><article class="finding"><h3>S-79 · Ошибка проекции видна</h3><p>До retry канонический статус показывает degradation, а v1 остаётся закрытым. Idempotent retry сводит все публичные поверхности без повторения денег.</p></article></div></div></section>
<section class="section" id="after"><div class="wrap"><p class="eyebrow">Следующий gate</p><h2>Что разрешено и что запрещено</h2><div class="after"><div class="do"><h3>Разрешено сейчас</h3><ol><li>Подготовить отдельный Block 9 Design.</li><li>Связать каждый механизм с принятыми S-71–S-79.</li><li>Проверить Design на деньги, authority, recovery и single-writer boundary.</li><li>Вернуться за отдельным принятием Design до implementation Tasks.</li></ol></div><div class="dont"><h3>Пока запрещено</h3><ul><li>Менять принятый BDD без новой версии и согласования.</li><li>Включать vNext.</li><li>Менять ledger.</li><li>Запускать writers.</li><li>Создавать genesis или bootstrap.</li><li>Менять credentials или permissions.</li><li>Подключать S13C к live-системе.</li></ul></div></div></div></section>
<section class="section" id="evidence"><div class="wrap"><p class="eyebrow">Проверяемые источники</p><h2>Где находится точный принятый контракт</h2><p class="intro">HTML самодостаточен для чтения. Outcome/Spec сохранены ровно в том виде, в котором были приняты, поэтому внутри них остаются preparation-time метки proposed/pending. Более поздний manifest ниже фиксирует их точные SHA-256 и переводит эти неизменённые bytes в accepted-for-Design.</p><ul class="source-list"><li><a href="WEA_vNext_BLOCK9_ACCEPTANCE.txt">Точная SHA-256 привязка принятого Outcome/Spec 1.0</a></li><li><a href="WEA_vNext_ACCEPTED_DECISIONS.txt">Производная запись решений — не самостоятельное authority proof</a></li><li><a href="../wea-vnext-block9-cutover/outcome.md">Frozen Block 9 Outcome 1.0 snapshot</a></li><li><a href="../wea-vnext-block9-cutover/spec.md">Frozen Block 9 BDD / Spec 1.0 snapshot</a></li><li><a href="../wea-vnext-block9-cutover/tasks.md">Block 9 Tasks</a></li><li><a href="../wea-vnext-block9-cutover/verification.md">Block 9 Verification</a></li><li><a href="operator-review.md">Текстовая версия обзора</a></li><li><a href="verification.md">S13C Verification 1.4</a></li><li><a href="../wea-vnext-recreation/HANDOFF.md">Текущий общий handoff</a></li><li><a href="../wea-vnext-recreation/open-decisions.md">Реестр решений</a></li></ul><details><summary>Почему будущий ikigai-механизм отделён?</summary><p>Он важен для поиска идентичности, но ещё не имеет собственного поведения, полномочий и доказательств. Отдельный Outcome и Spec позволят разработать его осознанно, не пряча в миграции.</p></details><details><summary>Что значит accepted-future?</summary><p>Поведение уже обязательно для Design, но ещё не реализовано и не является текущей возможностью системы.</p></details><details><summary>Что осталось неблокирующим?</summary><p>OD-11 ждёт внутреннего прогона. OD-14 нужен до внешних вкладов. IKIGAI-01 станет отдельной продуктовой задачей.</p></details></div></section>
</main>
<footer><div class="wrap">Пакет __VERSION__. Fingerprint выбранных SDD, production-boundary и verification sources: <code>__FINGERPRINT__</code>. Decision payload: <code>__DECISION_PAYLOAD_HASH__</code>. Prepared candidate package: <code>__CANDIDATE_PACKAGE_ID__</code>. Локальная база: <code>0ea6513</code>.</div></footer><div class="toast" id="toast" role="status" aria-live="polite"></div>
<script>
(()=>{"use strict";const acceptedRecord=__ACCEPTANCE_TEXT_JSON__,toast=document.getElementById("toast");function show(msg){toast.textContent=msg;toast.classList.add("show");setTimeout(()=>toast.classList.remove("show"),1800)}function exportText(){return acceptedRecord}document.getElementById("progress-bar").style.width="100%";document.getElementById("print-summary").textContent=exportText();document.getElementById("copy-decisions").addEventListener("click",async()=>{const text=exportText();try{await navigator.clipboard.writeText(text);show("Итог скопирован")}catch{const area=document.createElement("textarea");area.value=text;document.body.appendChild(area);area.select();document.execCommand("copy");area.remove();show("Итог скопирован")}});document.getElementById("download-decisions").addEventListener("click",()=>{const blob=new Blob([exportText()],{type:"text/plain;charset=utf-8"}),url=URL.createObjectURL(blob),a=document.createElement("a");a.href=url;a.download="WEA_vNext_ACCEPTED_DECISIONS.txt";a.click();URL.revokeObjectURL(url);show("Файл подготовлен")})})();
</script>
</body></html>
'''
    return (
        template.replace("__VERSION__", ARTIFACT_VERSION)
        .replace("__FINGERPRINT_SHORT__", fingerprint[:12])
        .replace("__FINGERPRINT__", fingerprint)
        .replace("__DECISION_PAYLOAD_HASH__", decision_payload_hash())
        .replace("__CANDIDATE_PACKAGE_ID__", candidate_package_identity(fingerprint))
        .replace(
            "__ACCEPTANCE_TEXT_JSON__",
            json.dumps(accepted_record, ensure_ascii=False),
        )
        .replace("__DECISION_CARDS__", decision_cards())
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate sources and fail if the generated artifact is stale",
    )
    args = parser.parse_args()
    validate_accepted_block9_contract()
    validate_sources()
    rendered = build_html()
    accepted_record = acceptance_record(source_fingerprint())
    block9_record = block9_acceptance_record()
    if not args.check:
        ACCEPTANCE_OUTPUT.write_text(accepted_record, encoding="utf-8", newline="\n")
        BLOCK9_ACCEPTANCE_OUTPUT.write_text(
            block9_record,
            encoding="utf-8",
            newline="\n",
        )
    validate_rendered(rendered)
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != rendered:
            raise SystemExit(f"Generated artifact is stale: {OUTPUT}")
        if (
            not ACCEPTANCE_OUTPUT.exists()
            or ACCEPTANCE_OUTPUT.read_text(encoding="utf-8") != accepted_record
        ):
            raise SystemExit(f"Accepted decision record is stale: {ACCEPTANCE_OUTPUT}")
        if (
            not BLOCK9_ACCEPTANCE_OUTPUT.exists()
            or BLOCK9_ACCEPTANCE_OUTPUT.read_text(encoding="utf-8") != block9_record
        ):
            raise SystemExit(
                f"Accepted Block 9 binding is stale: {BLOCK9_ACCEPTANCE_OUTPUT}"
            )
        print(f"OK: {OUTPUT.name} matches sources ({source_fingerprint()[:12]})")
        return 0
    OUTPUT.write_text(rendered, encoding="utf-8", newline="\n")
    print(f"Built {OUTPUT} ({source_fingerprint()[:12]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
