# ruff: noqa: E501, RUF001
"""Build and validate the plain-language Block 9 Tasks review artifact."""

from __future__ import annotations

import argparse
import hashlib
import html
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

ARTIFACT_VERSION = "2026-08-18.1"
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUTPUT = HERE / "WEA_vNext_BLOCK9_TASKS_REVIEW.html"
DESIGN_ACCEPTANCE = HERE / "WEA_vNext_BLOCK9_DESIGN_ACCEPTANCE.txt"
TASKS = HERE / "tasks.md"
OUTCOME = HERE / "outcome.md"
SPEC = HERE / "spec.md"
DESIGN = HERE / "design.md"
BDD_ACCEPTANCE = (
    HERE.parent
    / "wea-vnext-s13c-financial-correction"
    / "WEA_vNext_BLOCK9_ACCEPTANCE.txt"
)

ACCEPTED_HASHES = {
    OUTCOME: "e9cbdcc924c8e01cae3240885e272fc75a7595bae1dcab4ee4034e6d439d1f67",
    SPEC: "25c65e999bb158d773fa7d46c5e566cd36f5a7eb4b8b8aff272274d8efe59dfa",
    DESIGN: "70026e7551acc7c5f1ae56b1d49962045dec3b70e0647aaf3b5040f36e856283",
}

SOURCE_FILES = (
    TASKS,
    OUTCOME,
    SPEC,
    DESIGN,
    BDD_ACCEPTANCE,
    DESIGN_ACCEPTANCE,
)

GROUP_RU = {
    1: {
        "phase": "Основа",
        "kind": "build",
        "gives": "Один путь записи, один lock, один epoch guard и одна атомарная Git-транзакция.",
        "why": "Иначе старый writer может записать вторую версию истории после cutover.",
        "cut": "Не делить на отдельные approval-этапы. Реализовать и проверить как одну техническую основу.",
    },
    2: {
        "phase": "Среда",
        "kind": "setup",
        "gives": "Отдельные Windows identities, GitHub Apps и rulesets делают границу writer технически исполнимой.",
        "why": "Код не остановит same-account worker или другой credential с правом записи в main.",
        "cut": "Использовать один checkpoint для всей настройки. Не согласовывать каждый account, App или ruleset отдельно.",
    },
    3: {
        "phase": "Данные",
        "kind": "parallel",
        "gives": "Все обязательства v1 получают один исход. Genesis всегда создаёт одинаковое начальное состояние.",
        "why": "Иначе деньги, задачи или identity могут потеряться или попасть в vNext дважды.",
        "cut": "Reconciliation, genesis и retirement используют один snapshot. Их выгодно оставить вместе.",
    },
    4: {
        "phase": "Восстановление",
        "kind": "parallel",
        "gives": "После crash или replay-дефекта система продолжает одну историю и умеет сделать разрешённое исправление.",
        "why": "Без recovery безопасный cutover невозможен. Ошибка может навсегда заблокировать ledger.",
        "cut": "Financial correction и replay repair используют один append kernel. Их proof остаётся раздельным.",
    },
    5: {
        "phase": "Shadow и GitHub",
        "kind": "parallel",
        "gives": "Полный runtime дважды работает без live-эффекта. Comments и labels сходятся без повторной оплаты.",
        "why": "Unit tests не доказывают отсутствие доступа к сети, credentials и live ledger.",
        "cut": "Tracked files входят в activation commit. Projection worker обрабатывает только внешние GitHub-объекты.",
    },
    6: {
        "phase": "Закрытие v1",
        "kind": "operation",
        "gives": "Каждое реальное обязательство v1 получает разрешённый конечный исход до финального snapshot.",
        "why": "Migration code не закрывает реальные Issues, escrow и pending payments сам по себе.",
        "cut": "Одна Delivery 2 acceptance покрывает v1 cleanup и следующий rehearsal. Она не разрешает activation.",
    },
    7: {
        "phase": "Rehearsal",
        "kind": "gate",
        "gives": "Один отчёт показывает, что весь candidate работает на одном точном snapshot.",
        "why": "Раздельные tests не доказывают совместимость всех модулей, ключей, правил и данных.",
        "cut": "Нужен один rehearsal, а не rehearsal для каждой группы. Shadow внутри него запускается дважды.",
    },
    8: {
        "phase": "Activation",
        "kind": "blocked",
        "gives": "Один commit переключает остановленный v1 на vNext.",
        "why": "Это единственный необратимый шаг, который меняет authoritative ledger epoch.",
        "cut": "Оставить один activation gate. Не добавлять rolling migration, dual write или автоматический scheduler.",
    },
}

LEAN_RU = (
    (
        "Параллельная работа",
        "После общей основы группы 3, 4 и 5 идут параллельно.",
        "Без изменения контракта",
        "Рекомендуется",
        "safe",
    ),
    (
        "Одна dormant-поставка",
        "Группы 1–5 входят в один dormant package. Group 2 имеет один environment checkpoint.",
        "Без изменения контракта",
        "Рекомендуется",
        "safe",
    ),
    (
        "Одна acceptance для Groups 6–7",
        "Controlled v1 cleanup и no-write rehearsal образуют одну Delivery 2.",
        "Соответствует Design",
        "Рекомендуется",
        "safe",
    ),
    (
        "Rehearsal вместе с activation",
        "Система потеряет последнюю no-write проверку перед mutation.",
        "Новая версия Design",
        "Не рекомендуется",
        "risk",
    ),
    (
        "Один writer inventory",
        "Пропущенный writer нельзя будет независимо обнаружить.",
        "Нарушает S-71",
        "Нельзя сокращать",
        "risk",
    ),
    (
        "Один Windows account",
        "Worker получит тот же доступ к secrets, что и Agent0.",
        "Новая версия Design",
        "Не рекомендуется",
        "risk",
    ),
    (
        "Один GitHub App",
        "Projection code получит право писать в canonical ref.",
        "Новая версия Design",
        "Не рекомендуется",
        "risk",
    ),
    (
        "Один shadow run",
        "Повторяемость полного runtime останется недоказанной.",
        "Нарушает S-74",
        "Нельзя сокращать",
        "risk",
    ),
    (
        "Recovery после activation",
        "В момент cutover не будет разрешённого repair path.",
        "Нарушает S-78",
        "Нельзя сокращать",
        "risk",
    ),
)


@dataclass(frozen=True)
class TaskGroup:
    number: int
    title: str
    status: str
    depends: str
    scenarios: str
    items: tuple[str, ...]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def design_acceptance_record() -> str:
    return "\n".join(
        (
            "WEA vNext — exact Block 9 Design acceptance binding",
            "Design revision: 1.0",
            "Authority date: 2026-08-18",
            "Authority wording: Принимаю Block 9 Design.",
            (
                "Authority source: operator message in the current Codex task; "
                "this derived manifest is not standalone identity proof."
            ),
            "Design path: oled/changes/wea-vnext-block9-cutover/design.md",
            f"Design SHA-256: {ACCEPTED_HASHES[DESIGN]}",
            f"Governing Outcome SHA-256: {ACCEPTED_HASHES[OUTCOME]}",
            f"Governing Spec SHA-256: {ACCEPTED_HASHES[SPEC]}",
            (
                "Meaning: these exact Design bytes are accepted for Tasks "
                "planning only; implementation and activation remain unauthorized."
            ),
            (
                "Status rule: proposed wording inside the frozen Design is the "
                "preparation-time snapshot; this later manifest records acceptance."
            ),
            (
                "Drift rule: byte changes require a new Design revision and a new "
                "exact operator acceptance."
            ),
            "",
        )
    )


def _inline(value: str) -> str:
    escaped = html.escape(value)
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)


def _field(body: str, label: str) -> str:
    pattern = rf"^- {re.escape(label)}: (.*(?:\n  .+)*)$"
    match = re.search(pattern, body, flags=re.MULTILINE)
    if not match:
        raise ValueError(f"Missing group field: {label}")
    return " ".join(line.strip() for line in match.group(1).splitlines())


def _checklist(body: str) -> tuple[str, ...]:
    items: list[str] = []
    current: list[str] | None = None
    for line in body.splitlines():
        if line.startswith("- [ ] ") or line.startswith("- [x] "):
            if current:
                items.append(" ".join(current))
            current = [line[6:].strip()]
        elif current is not None and line.startswith("  "):
            current.append(line.strip())
        elif current is not None:
            items.append(" ".join(current))
            current = None
    if current:
        items.append(" ".join(current))
    return tuple(items)


def parse_groups(text: str) -> tuple[TaskGroup, ...]:
    matches = list(re.finditer(r"^## ([1-8])\. (.+)$", text, flags=re.MULTILINE))
    groups: list[TaskGroup] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[match.end() : end]
        groups.append(
            TaskGroup(
                number=int(match.group(1)),
                title=match.group(2).strip(),
                status=_field(body, "Status"),
                depends=_field(body, "Depends on"),
                scenarios=_field(body, "Covers accepted scenarios"),
                items=_checklist(body),
            )
        )
    return tuple(groups)


def _scenario_set(value: str) -> set[str]:
    scenarios = set(re.findall(r"S-7[1-9]", value))
    for match in re.finditer(r"S-(7[1-9]) through S-(7[1-9])", value):
        start, end = (int(item) for item in match.groups())
        scenarios.update(f"S-{number}" for number in range(start, end + 1))
    return scenarios


def source_fingerprint() -> str:
    digest = hashlib.sha256()
    for path in SOURCE_FILES:
        relative = path.relative_to(ROOT).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    digest.update(ARTIFACT_VERSION.encode("ascii"))
    return digest.hexdigest()


def validate_sources(groups: tuple[TaskGroup, ...]) -> None:
    for path, expected in ACCEPTED_HASHES.items():
        actual = _sha256(path)
        if actual != expected:
            raise ValueError(
                f"Accepted source drift: {path.name} {actual} != {expected}"
            )

    tasks = _read(TASKS)
    required = (
        "Task revision: `2.0`",
        "Plan status: `planned for operator review; implementation not started; activation blocked`",
        ACCEPTED_HASHES[DESIGN],
        "Groups 3, 4, and 5 can proceed in parallel",
        "Delivery 1 is dormant implementation",
        "Acceptance of Tasks 2.0 authorizes only code work",
        "WEA_vNext_BLOCK9_DESIGN_ACCEPTANCE.txt",
        "Next authorized action: operator review of Tasks 2.0",
    )
    for token in required:
        if token not in tasks:
            raise ValueError(f"Missing Tasks contract token: {token}")

    if tuple(group.number for group in groups) != (1, 2, 3, 4, 5, 6, 7, 8):
        raise ValueError("Tasks must contain the exact eight planned groups")
    if any(not group.items for group in groups):
        raise ValueError("Every task group must contain actionable checklist items")

    scenario_ids = set(re.findall(r"S-7[1-9]", tasks))
    if scenario_ids != {f"S-{number}" for number in range(71, 80)}:
        raise ValueError(f"Scenario trace is incomplete: {sorted(scenario_ids)}")

    expected_group_scenarios = {
        1: {"S-71", "S-75"},
        2: {"S-71", "S-74", "S-75", "S-79"},
        3: {"S-72", "S-73", "S-76", "S-77"},
        4: {"S-78"},
        5: {"S-74", "S-79"},
        6: {"S-72"},
        7: {f"S-{number}" for number in range(71, 80)},
        8: {"S-75", "S-78", "S-79"},
    }
    for group in groups:
        actual = _scenario_set(group.scenarios)
        if actual != expected_group_scenarios[group.number]:
            raise ValueError(
                f"Group {group.number} scenario trace {sorted(actual)} does not "
                f"match {sorted(expected_group_scenarios[group.number])}"
            )

    lean_tokens = (
        "Run Groups 3, 4, and 5 in parallel after Group 1",
        "Deliver Groups 1 through 5 as one dormant implementation package",
        "Use one approval for Groups 6 and 7",
        "Combine rehearsal and activation",
        "Use one writer inventory",
        "Use one Windows account for Agent0 and workers",
        "Use one GitHub App for ledger and projections",
        "Run shadow once",
        "Add recovery after activation",
    )
    for token in lean_tokens:
        if token not in tasks:
            raise ValueError(f"Missing lean-cut source row: {token}")


def render_group(group: TaskGroup) -> str:
    info = GROUP_RU[group.number]
    checklist = "".join(f"<li>{_inline(item)}</li>" for item in group.items)
    badge = {
        "build": "Общая основа",
        "setup": "Нужен environment checkpoint",
        "parallel": "Можно параллельно",
        "operation": "Отдельная Delivery 2 authority",
        "gate": "Отдельный rehearsal",
        "blocked": "Заблокировано",
    }[info["kind"]]
    return f"""
    <article class="task-card" data-kind="{info['kind']}" id="task-{group.number}">
      <div class="task-topline">
        <span class="task-number">{group.number}</span>
        <span class="badge {info['kind']}">{badge}</span>
      </div>
      <p class="eyebrow">{html.escape(info['phase'])}</p>
      <h3>{html.escape(group.title)}</h3>
      <div class="explain-grid">
        <div><h4>Что даёт</h4><p>{html.escape(info['gives'])}</p></div>
        <div><h4>Зачем нужно</h4><p>{html.escape(info['why'])}</p></div>
        <div><h4>Как упростить</h4><p>{html.escape(info['cut'])}</p></div>
      </div>
      <dl class="facts">
        <div><dt>BDD</dt><dd>{_inline(group.scenarios)}</dd></div>
        <div><dt>Статус</dt><dd>{_inline(group.status)}</dd></div>
        <div><dt>Зависимость</dt><dd>{_inline(group.depends)}</dd></div>
        <div><dt>Технических действий</dt><dd>{len(group.items)}</dd></div>
      </dl>
      <details>
        <summary>Показать точный технический checklist</summary>
        <ol class="checklist">{checklist}</ol>
      </details>
    </article>
    """.strip()


def render_lean_rows() -> str:
    rows = []
    for title, result, effect, recommendation, kind in LEAN_RU:
        rows.append(
            f"""
            <tr data-cut="{kind}">
              <th>{html.escape(title)}</th>
              <td>{html.escape(result)}</td>
              <td>{html.escape(effect)}</td>
              <td><span class="decision {kind}">{html.escape(recommendation)}</span></td>
            </tr>
            """.strip()
        )
    return "\n".join(rows)


def build_html(groups: tuple[TaskGroup, ...]) -> str:
    fingerprint = source_fingerprint()
    tasks_hash = _sha256(TASKS)
    group_cards = "\n".join(render_group(group) for group in groups)
    lean_rows = render_lean_rows()
    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="icon" href="data:,">
  <title>WEA vNext — Block 9 Tasks 2.0</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #172033;
      --muted: #647087;
      --paper: #f5f2ea;
      --card: #fffdf8;
      --line: #d9d4c8;
      --blue: #214f8b;
      --blue-soft: #e8f0fb;
      --green: #226a4b;
      --green-soft: #e6f3eb;
      --amber: #8a5a12;
      --amber-soft: #fff0ce;
      --red: #8b2f35;
      --red-soft: #f9e7e7;
      --shadow: 0 18px 50px rgba(35, 44, 64, .09);
    }}
    * {{ box-sizing: border-box; }}
    html {{ scroll-behavior: smooth; }}
    body {{
      margin: 0;
      color: var(--ink);
      background:
        radial-gradient(circle at 85% 5%, rgba(33, 79, 139, .10), transparent 30rem),
        linear-gradient(180deg, #f9f7f1 0, var(--paper) 48rem);
      font: 16px/1.55 Inter, ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
    }}
    a {{ color: var(--blue); }}
    code {{
      padding: .12rem .34rem;
      border-radius: .35rem;
      background: #edf0f4;
      font: .88em/1.4 ui-monospace, SFMono-Regular, Consolas, monospace;
      overflow-wrap: anywhere;
    }}
    .wrap {{ width: min(1180px, calc(100% - 32px)); margin-inline: auto; }}
    .hero {{ padding: 54px 0 28px; }}
    .hero-grid {{ display: grid; grid-template-columns: 1.45fr .75fr; gap: 28px; align-items: end; }}
    .kicker, .eyebrow {{
      margin: 0 0 .4rem;
      color: var(--blue);
      font-size: .76rem;
      font-weight: 800;
      letter-spacing: .12em;
      text-transform: uppercase;
    }}
    h1 {{ max-width: 880px; margin: 0; font-size: clamp(2.2rem, 6vw, 4.8rem); line-height: .98; letter-spacing: -.055em; }}
    .lead {{ max-width: 760px; margin: 1.3rem 0 0; color: #445066; font-size: 1.14rem; }}
    .status-box {{ padding: 22px; border: 1px solid #bfd0e5; border-radius: 18px; background: rgba(255,255,255,.72); box-shadow: var(--shadow); }}
    .status-box strong {{ display: block; font-size: 1.22rem; }}
    .status-box p {{ margin: .45rem 0 0; color: var(--muted); }}
    .metric-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin: 28px 0; }}
    .metric {{ padding: 18px; border: 1px solid var(--line); border-radius: 16px; background: rgba(255,255,255,.66); }}
    .metric b {{ display: block; font-size: 1.7rem; line-height: 1; }}
    .metric span {{ color: var(--muted); font-size: .88rem; }}
    .plain-answer {{ margin: 24px 0 34px; padding: 26px; border-left: 5px solid var(--green); border-radius: 0 18px 18px 0; background: var(--green-soft); }}
    .plain-answer h2 {{ margin-top: 0; }}
    .plain-answer p:last-child {{ margin-bottom: 0; }}
    .flow {{ display: grid; grid-template-columns: 1fr auto 2.4fr auto 1fr auto 1fr; gap: 10px; align-items: center; margin: 22px 0 34px; }}
    .flow-node {{ min-height: 100px; padding: 16px; border: 1px solid var(--line); border-radius: 15px; background: var(--card); }}
    .flow-node.parallel {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; padding: 8px; }}
    .flow-node.parallel span {{ padding: 10px; border-radius: 10px; background: var(--blue-soft); text-align: center; }}
    .arrow {{ color: var(--blue); font-size: 1.5rem; font-weight: 900; }}
    .toolbar {{ display: flex; flex-wrap: wrap; gap: 8px; margin: 18px 0; }}
    button {{ padding: 9px 14px; border: 1px solid #b9c2d0; border-radius: 999px; color: var(--ink); background: white; font: inherit; cursor: pointer; }}
    button[aria-pressed="true"] {{ border-color: var(--blue); color: white; background: var(--blue); }}
    .task-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; }}
    .task-card {{ position: relative; padding: 24px; border: 1px solid var(--line); border-radius: 20px; background: var(--card); box-shadow: 0 8px 26px rgba(35,44,64,.05); }}
    .task-card.is-hidden {{ display: none; }}
    .task-topline {{ display: flex; align-items: center; justify-content: space-between; gap: 12px; }}
    .task-number {{ display: grid; place-items: center; width: 42px; height: 42px; border-radius: 50%; color: white; background: var(--blue); font-weight: 900; }}
    .badge, .decision {{ display: inline-flex; padding: 5px 9px; border-radius: 999px; font-size: .78rem; font-weight: 800; }}
    .badge.build, .badge.parallel {{ color: var(--blue); background: var(--blue-soft); }}
    .badge.setup, .badge.gate {{ color: var(--amber); background: var(--amber-soft); }}
    .badge.operation {{ color: var(--green); background: var(--green-soft); }}
    .badge.blocked {{ color: var(--red); background: var(--red-soft); }}
    .task-card h3 {{ margin: .2rem 0 1rem; font-size: 1.45rem; line-height: 1.15; }}
    .explain-grid {{ display: grid; gap: 8px; }}
    .explain-grid > div {{ padding: 12px 14px; border-radius: 12px; background: #f4f1e9; }}
    .explain-grid h4 {{ margin: 0 0 .2rem; font-size: .84rem; }}
    .explain-grid p {{ margin: 0; color: #4c5668; }}
    .facts {{ margin: 16px 0; }}
    .facts > div {{ display: grid; grid-template-columns: 130px 1fr; gap: 12px; padding: 7px 0; border-bottom: 1px dashed var(--line); }}
    .facts dt {{ color: var(--muted); }}
    .facts dd {{ margin: 0; }}
    details {{ margin-top: 16px; border-top: 1px solid var(--line); padding-top: 14px; }}
    summary {{ color: var(--blue); font-weight: 750; cursor: pointer; }}
    .checklist {{ padding-left: 1.3rem; }}
    .checklist li {{ margin: .55rem 0; }}
    section {{ padding: 32px 0; }}
    section h2 {{ margin: 0 0 .5rem; font-size: clamp(1.8rem, 4vw, 2.8rem); letter-spacing: -.035em; }}
    .section-lead {{ max-width: 780px; margin: 0 0 20px; color: var(--muted); }}
    .table-wrap {{ overflow-x: auto; border: 1px solid var(--line); border-radius: 18px; background: var(--card); }}
    table {{ width: 100%; border-collapse: collapse; min-width: 760px; }}
    th, td {{ padding: 14px 16px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }}
    thead th {{ color: var(--muted); background: #f3f0e8; font-size: .82rem; text-transform: uppercase; letter-spacing: .06em; }}
    tbody th {{ width: 22%; }}
    .decision.safe {{ color: var(--green); background: var(--green-soft); }}
    .decision.risk {{ color: var(--red); background: var(--red-soft); }}
    .decision-box {{ display: grid; grid-template-columns: 1.3fr .7fr; gap: 20px; padding: 26px; border-radius: 20px; color: white; background: #172d4a; }}
    .decision-box h2 {{ color: white; }}
    .decision-box p {{ color: #d9e4f2; }}
    .reply {{ align-self: center; padding: 18px; border: 1px solid #6c87a8; border-radius: 14px; background: #0f223b; }}
    .reply code {{ display: block; color: #fff; background: transparent; white-space: normal; }}
    footer {{ padding: 34px 0 52px; color: var(--muted); font-size: .88rem; }}
    .source-links {{ display: flex; flex-wrap: wrap; gap: 12px; }}
    .hash {{ overflow-wrap: anywhere; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; }}
    @media (max-width: 860px) {{
      .hero-grid, .decision-box {{ grid-template-columns: 1fr; }}
      .metric-grid {{ grid-template-columns: repeat(2, 1fr); }}
      .task-grid {{ grid-template-columns: 1fr; }}
      .flow {{ grid-template-columns: 1fr; }}
      .arrow {{ transform: rotate(90deg); text-align: center; }}
      .flow-node.parallel {{ grid-template-columns: 1fr; }}
    }}
    @media (max-width: 480px) {{
      .wrap {{ width: min(100% - 20px, 1180px); }}
      .hero {{ padding-top: 30px; }}
      .metric-grid {{ grid-template-columns: 1fr 1fr; }}
      .task-card {{ padding: 18px; }}
      .facts > div {{ grid-template-columns: 1fr; gap: 2px; }}
    }}
  </style>
</head>
<body>
  <header class="hero">
    <div class="wrap hero-grid">
      <div>
        <p class="kicker">WEA vNext · Block 9 · Tasks 2.0</p>
        <h1>План реализации без лишних approval-этапов</h1>
        <p class="lead">Этот документ объясняет пользу каждой группы. Он также показывает безопасные сокращения и границы, которые нельзя убрать без изменения принятого Design.</p>
      </div>
      <aside class="status-box">
        <strong>Нужен review Tasks</strong>
        <p>Tasks 2.0 не разрешает менять credentials, Windows accounts, GitHub Apps, rulesets, ledger или main.</p>
      </aside>
    </div>
    <div class="wrap metric-grid" aria-label="Краткие показатели плана">
      <div class="metric"><b>5</b><span>dormant implementation lanes</span></div>
      <div class="metric"><b>2</b><span>группы в rehearsal delivery</span></div>
      <div class="metric"><b>1</b><span>отдельный activation gate</span></div>
      <div class="metric"><b>3</b><span>реальные delivery-этапы</span></div>
    </div>
  </header>

  <main class="wrap">
    <section class="plain-answer" aria-labelledby="short-answer">
      <h2 id="short-answer">Короткий ответ про лишние этапы</h2>
      <p>Восемь групп ниже не означают восемь согласований. Группы 1–5 составляют одну dormant-поставку.</p>
      <p>После общей основы группы 3–5 можно делать параллельно. Группы 6–7 составляют одну отдельно принятую rehearsal delivery.</p>
      <p>Rehearsal остаётся отдельным, потому что activation меняет authoritative ledger epoch. Это единственная необратимая операция.</p>
    </section>

    <div class="flow" aria-label="Поток реализации">
      <div class="flow-node"><strong>1. Safety kernel</strong><br>Общая основа</div>
      <div class="arrow" aria-hidden="true">→</div>
      <div class="flow-node parallel"><span>2. Environment</span><span>3. Migration</span><span>4. Recovery</span><span>5. Shadow</span></div>
      <div class="arrow" aria-hidden="true">→</div>
      <div class="flow-node"><strong>6. v1 cleanup</strong><br><strong>7. Rehearsal</strong></div>
      <div class="arrow" aria-hidden="true">→</div>
      <div class="flow-node"><strong>8. Activation</strong><br>Новые подписи</div>
    </div>

    <section aria-labelledby="groups-title">
      <h2 id="groups-title">Что делает каждая группа</h2>
      <p class="section-lead">Нажмите на технический checklist только при необходимости. Основные причины и результаты указаны простым языком.</p>
      <div class="toolbar" role="group" aria-label="Фильтр групп">
        <button type="button" data-filter="all" aria-pressed="true">Все</button>
        <button type="button" data-filter="build" aria-pressed="false">Общая основа</button>
        <button type="button" data-filter="setup" aria-pressed="false">Environment</button>
        <button type="button" data-filter="parallel" aria-pressed="false">Можно параллельно</button>
        <button type="button" data-filter="operation" aria-pressed="false">Закрытие v1</button>
        <button type="button" data-filter="gate" aria-pressed="false">Rehearsal</button>
        <button type="button" data-filter="blocked" aria-pressed="false">Activation</button>
      </div>
      <div class="task-grid">{group_cards}</div>
    </section>

    <section aria-labelledby="lean-title">
      <h2 id="lean-title">Где план можно сократить</h2>
      <p class="section-lead">Зелёные решения сокращают организационную работу без изменения контракта. Красные решения меняют принятую безопасность или BDD.</p>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Сокращение</th><th>Что произойдёт</th><th>Влияние</th><th>Решение</th></tr></thead>
          <tbody>{lean_rows}</tbody>
        </table>
      </div>
    </section>

    <section class="decision-box" aria-labelledby="decision-title">
      <div>
        <h2 id="decision-title">Что нужно согласовать сейчас</h2>
        <p>Рекомендуемый lean cut сохраняет три delivery-этапа: dormant implementation, no-write rehearsal и отдельно activation.</p>
        <p>Acceptance Tasks разрешит только code work в Groups 1, 3, 4 и 5. Environment setup, v1 cleanup, rehearsal и activation останутся заблокированными.</p>
      </div>
      <div class="reply">
        <strong>Короткий ответ для согласования</strong>
        <code>Принимаю Block 9 Tasks 2.0 и lean cut. Разрешаю только code work Groups 1, 3, 4, 5. Не разрешаю environment mutation, v1 cleanup, rehearsal или activation.</code>
      </div>
    </section>
  </main>

  <footer>
    <div class="wrap">
      <div class="source-links">
        <a href="tasks.md">Tasks 2.0</a>
        <a href="WEA_vNext_BLOCK9_DESIGN_ACCEPTANCE.txt">Design acceptance binding</a>
        <a href="design.md">Accepted Design 1.0</a>
        <a href="spec.md">Accepted Spec 1.0</a>
        <a href="outcome.md">Accepted Outcome 1.0</a>
      </div>
      <p>Artifact version: {ARTIFACT_VERSION}. Tasks SHA-256: <span class="hash">{tasks_hash}</span>.</p>
      <p>Selected-source fingerprint SHA-256: <span class="hash">{fingerprint}</span>.</p>
      <p>Этот HTML является объяснением Tasks. Нормативный checklist находится в <code>tasks.md</code>.</p>
    </div>
  </footer>
  <script>
    const buttons = [...document.querySelectorAll('[data-filter]')];
    const cards = [...document.querySelectorAll('.task-card')];
    for (const button of buttons) {{
      button.addEventListener('click', () => {{
        const filter = button.dataset.filter;
        for (const item of buttons) item.setAttribute('aria-pressed', String(item === button));
        for (const card of cards) card.classList.toggle('is-hidden', filter !== 'all' && card.dataset.kind !== filter);
      }});
    }}
  </script>
</body>
</html>
"""


class ArtifactParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []
        self.links: list[str] = []
        self.lang: str | None = None

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        values = dict(attrs)
        if tag == "html":
            self.lang = values.get("lang")
        if values.get("id"):
            self.ids.append(values["id"] or "")
        if tag == "a" and values.get("href"):
            self.links.append(values["href"] or "")


def validate_html(rendered: str) -> None:
    parser = ArtifactParser()
    parser.feed(rendered)
    if parser.lang != "ru":
        raise ValueError("Artifact language must be Russian")
    if len(parser.ids) != len(set(parser.ids)):
        raise ValueError("Artifact contains duplicate HTML ids")
    if any(link.startswith(("http://", "https://")) for link in parser.links):
        raise ValueError("Artifact must not depend on remote links")
    required = (
        "План реализации без лишних approval-этапов",
        "Короткий ответ про лишние этапы",
        "Что делает каждая группа",
        "Где план можно сократить",
        "Принимаю Block 9 Tasks 2.0",
    )
    for token in required:
        if token not in rendered:
            raise ValueError(f"Artifact is missing required text: {token}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail if the generated artifact is absent or stale.",
    )
    args = parser.parse_args()

    design_record = design_acceptance_record()
    if (
        not DESIGN_ACCEPTANCE.exists()
        or DESIGN_ACCEPTANCE.read_text(encoding="utf-8") != design_record
    ):
        raise SystemExit("Immutable Design acceptance binding is absent or stale")

    groups = parse_groups(_read(TASKS))
    validate_sources(groups)
    rendered = build_html(groups)
    validate_html(rendered)

    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != rendered:
            raise SystemExit("Generated Tasks review artifact is stale")
        print(
            f"OK: {OUTPUT.name} matches sources "
            f"({source_fingerprint()[:12]})"
        )
        return 0

    OUTPUT.write_text(rendered, encoding="utf-8", newline="\n")
    print(
        f"Wrote {OUTPUT} ({len(rendered.encode('utf-8'))} bytes, "
        f"fingerprint {source_fingerprint()[:12]})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
