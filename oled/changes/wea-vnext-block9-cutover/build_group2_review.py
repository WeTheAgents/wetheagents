"""Build the simple Russian Block 9 private-pilot review artifact."""

# ruff: noqa: E501, RUF001

from __future__ import annotations

import argparse
import hashlib
import html
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
INSPECTION = HERE / "GROUP2_INSPECTION.json"
SPEC = HERE / "spec-1.1.md"
DESIGN = HERE / "design-1.3.md"
TASKS = HERE / "tasks-2.2.md"
DECISION = HERE / "WEA_vNext_BLOCK9_PRIVATE_CANONICAL_PILOT_DECISION.txt"
DESIGN_1_2 = HERE / "design-1.2.md"
DESIGN_1_2_ACCEPTANCE = HERE / "WEA_vNext_BLOCK9_DESIGN_1_2_ACCEPTANCE.txt"
OUTPUT = HERE / "WEA_vNext_BLOCK9_GROUP2_REVIEW.html"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def _available(node: object, default: object = "недоступно") -> object:
    if isinstance(node, dict) and node.get("available") is True:
        return node.get("value", default)
    return default


def _build() -> bytes:
    inspection = json.loads(INSPECTION.read_bytes())
    if inspection.get("environment_mutated") is not False:
        raise ValueError("inspection must be read-only")
    if inspection.get("credential_value_recorded") is not False:
        raise ValueError("inspection must not contain credential values")
    if inspection.get("canonical_repository") != "WeTheAgents/wetheagents":
        raise ValueError("inspection targets the wrong canonical repository")

    decision_text = DECISION.read_text(encoding="utf-8")
    for required in (
        "real canonical ledger",
        "GitHub Actions is the default",
        "separate Tasks 2.2 hash gate",
    ):
        if required not in decision_text:
            raise ValueError(f"decision record misses {required!r}")

    spec_text = SPEC.read_text(encoding="utf-8")
    design_text = DESIGN.read_text(encoding="utf-8")
    tasks_text = TASKS.read_text(encoding="utf-8")
    if "Spec version: `1.1`" not in spec_text:
        raise ValueError("Spec 1.1 is not current")
    if "Current design revision: `1.3`" not in design_text:
        raise ValueError("Design 1.3 is not current")
    if "needs no separate hash" not in tasks_text:
        raise ValueError("Tasks 2.2 still contains an approval gate")

    design_1_2_hash = _sha(DESIGN_1_2)
    if design_1_2_hash not in DESIGN_1_2_ACCEPTANCE.read_text(encoding="utf-8"):
        raise ValueError("historical Design 1.2 acceptance is not bound")

    github = inspection.get("github", {})
    repo = _available(github.get("repository"), {})
    ref = _available(github.get("canonical_ref"), {})
    rulesets = github.get("rulesets", {})
    repo_id = repo.get("id", "?") if isinstance(repo, dict) else "?"
    private = repo.get("private", "?") if isinstance(repo, dict) else "?"
    head = ref.get("sha", "?") if isinstance(ref, dict) else "?"
    ruleset_http = rulesets.get("http_status", "?") if isinstance(rulesets, dict) else "?"

    spec_hash = _sha(SPEC)
    design_hash = _sha(DESIGN)
    tasks_hash = _sha(TASKS)
    decision_hash = _sha(DECISION)
    inspection_hash = _sha(INSPECTION)

    document = f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="icon" href="data:,">
<title>Block 9 — настоящий private pilot</title>
<style>
:root{{--bg:#f4f3ee;--card:#fff;--ink:#20231f;--muted:#62675f;--line:#d7d6ce;--ok:#246b45;--warn:#945800;--stop:#a12d2d;--blue:#315d88}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:17px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}}
main{{max-width:1000px;margin:auto;padding:38px 20px 80px}}h1{{font-size:clamp(34px,5vw,54px);line-height:1.05;margin:.2em 0}}h2{{margin:2em 0 .6em;font-size:28px}}h3{{margin:1.4em 0 .35em}}p{{max-width:78ch}}.lead{{font-size:21px;color:var(--muted)}}
.card,.status{{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:20px 23px;margin:18px 0}}.status{{border-left:7px solid var(--ok)}}.warnbox{{border-left:7px solid var(--warn)}}.stopbox{{border-left:7px solid var(--stop)}}
.flow{{display:grid;grid-template-columns:repeat(6,minmax(120px,1fr));gap:8px;align-items:stretch;margin:20px 0}}.node{{background:#fff;border:1px solid var(--line);border-radius:12px;padding:13px;text-align:center}}.arrow{{display:none}}
.tag{{display:inline-block;padding:3px 10px;border-radius:99px;background:#e6efe9;color:var(--ok);font-size:14px;font-weight:700}}code{{overflow-wrap:anywhere}}table{{border-collapse:collapse;width:100%;background:var(--card)}}th,td{{border:1px solid var(--line);padding:12px;text-align:left;vertical-align:top}}th{{background:#ecebe5}}ul,ol{{padding-left:1.3em}}li{{margin:.4em 0}}.hash{{font:13px/1.45 ui-monospace,SFMono-Regular,Consolas,monospace;word-break:break-all;color:var(--muted)}}.ok{{color:var(--ok)}}.warn{{color:var(--warn)}}.stop{{color:var(--stop)}}a{{color:#285f92}}@media(max-width:800px){{.flow{{grid-template-columns:1fr 1fr}}table{{font-size:14px}}}}
</style>
</head>
<body><main>
<span class="tag">реализация проверена локально</span>
<h1>Block 9: настоящий ledger сначала работает private</h1>
<p class="lead">Мы запускаем vNext на каноническом ledger. Затем локальные агенты выполняют несколько реальных задач. После успешного E2E root станет public.</p>

<section class="status">
<h2 style="margin-top:0">Главное упрощение</h2>
<p><strong>GitHub Actions выполняет работу. GitHub pull request показывает каждый кандидат. Оператор вручную подтверждает merge.</strong></p>
<p>Этот путь уже реализован и проверен локально. Он ещё не включён на canonical <code>main</code>.</p>
<p>Локальный App, локальный lock и локальный epoch guard удалены из доверенной границы.</p>
<p>Отдельного hash-gate для Tasks 2.2 нет.</p>
</section>

<h2>Как проходит одна операция ledger</h2>
<div class="flow" aria-label="Путь ledger операции">
<div class="node"><strong>1</strong><br>Issue или comment</div>
<div class="node"><strong>2</strong><br>Ручной старт Agent0 Action</div>
<div class="node"><strong>3</strong><br>Actions строит candidate</div>
<div class="node"><strong>4</strong><br>Actions делает проверки</div>
<div class="node"><strong>5</strong><br>Оператор открывает и merge PR</div>
<div class="node"><strong>6</strong><br><code>main</code> становится ledger truth</div>
</div>
<p>Локальный агент не пишет ledger. Незамердженная ветка тоже не пишет ledger. Истиной остаётся только GitHub <code>main</code>.</p>

<h2>Почему сейчас без custom GitHub App</h2>
<table>
<tr><th>Вопрос</th><th>Только GitHub Actions</th><th>Custom GitHub App</th></tr>
<tr><td>Где работает код</td><td>На GitHub-hosted runner.</td><td>На нашем сервере или внутри Actions.</td></tr>
<tr><td>Ключи</td><td>GitHub выдаёт временный <code>GITHUB_TOKEN</code>.</td><td>Нужен private key и App installation.</td></tr>
<tr><td>Прозрачность</td><td>Run, PR, checks и commit видны в GitHub.</td><td>Видны действия App. Внешний runtime надо объяснять отдельно.</td></tr>
<tr><td>Работа между репозиториями</td><td>По умолчанию нет. На pilot можно переносить команду вручную.</td><td>App может читать Domain и писать в root.</td></tr>
<tr><td>Полная автоматизация</td><td>Нужны ручной старт, создание PR и merge.</td><td>Можно автоматизировать dispatch и merge.</td></tr>
<tr><td>Выбор сейчас</td><td><strong class="ok">Да. Этого достаточно.</strong></td><td><strong>Нет. Добавим только после фактической необходимости.</strong></td></tr>
</table>
<p>GitHub рекомендует встроенный token, если его прав достаточно. App нужен для других репозиториев или дополнительных прав: <a href="https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/making-authenticated-api-requests-with-a-github-app-in-a-github-actions-workflow">официальная документация</a>.</p>

<h2>Что мы убираем</h2>
<section class="card"><ul>
<li>Локальный ledger App и его ключ на ноутбуке.</li>
<li>Локальный общий lock между worktree.</li>
<li>Локальный epoch guard как источник права на запись.</li>
<li>Специальные Windows accounts и ACL для writer.</li>
<li>Два разных ruleset и App-only bypass.</li>
<li>Disposable public repository для репетиции App.</li>
<li>Отдельное согласование текста Tasks 2.2.</li>
</ul></section>

<h2>Что мы не упрощаем</h2>
<section class="card"><ul>
<li>Escrow-first и отсутствие двойной оплаты.</li>
<li>Idempotency key для каждой операции.</li>
<li>Exact replay и проверку supply.</li>
<li>Append-only recovery после активации.</li>
<li>Запрет запуска кода из чужого pull request.</li>
<li>Полную GitHub-историю задач, проверок, платежей и коммитов.</li>
</ul></section>

<h2>Честное ограничение private pilot</h2>
<section class="card warnbox">
<p>Root остаётся private на GitHub Free. Поэтому GitHub ruleset пока нельзя доказать.</p>
<p>Этот результат называется <code>DEFERRED</code>. Он не называется <code>PASS</code>.</p>
<p>Риск приемлем только потому, что все участники и все действия контролирует оператор.</p>
</section>

<h2>Blocking findings и их решение</h2>
<table>
<tr><th>Finding</th><th>Простое объяснение</th><th>Решение</th><th>Что блокирует</th></tr>
<tr><td>Design 1.2 оставлял vNext выключенным</td><td>Это противоречило настоящему private E2E.</td><td>Spec 1.1 и Design 1.3 заменили это правило.</td><td class="ok">Решено</td></tr>
<tr><td>Локальные guards стали лишними</td><td>Они создавали второй скрытый слой управления.</td><td>Trusted GitHub workflow заменил local authority hooks.</td><td class="ok">Решено в коде</td></tr>
<tr><td>Старые workflows имели write token</td><td>Они создавали второй путь записи.</td><td>Три writer workflow удалены. BTC workflow стал ручным и read-only.</td><td class="ok">Решено в коде</td></tr>
<tr><td>Старый ledger guard запрещал любой ledger PR</td><td>Новый путь должен принимать только точный Agent0 candidate.</td><td>Data-only guard проверяет точную команду, package, replay, money и supply.</td><td class="ok">Решено в коде</td></tr>
<tr><td>GitHub Issue #1 остаётся open</td><td>Это единственный открытый task в GitHub и task index.</td><td>Activation package даст ему явный <code>historical-close</code>. Ledger при этом не меняется до согласования.</td><td>Exact package</td></tr>
<tr><td>Private ruleset недоступен</td><td>GitHub Free не защищает private root этим механизмом.</td><td>Показать <code>DEFERRED</code>. До public допускать только контролируемых агентов.</td><td>Только внешних участников</td></tr>
<tr><td>Exposure audit не готов</td><td>До public надо проверить всю доступную Git-историю.</td><td>Проверить secrets, private data, licenses и identity data после E2E.</td><td>Только public transition</td></tr>
</table>

<h2>Пять шагов до проверки SDD</h2>
<ol>
<li>Согласовать Spec 1.1, Design 1.3, runbook и HTML.</li>
<li>Создать GitHub Actions writer и trusted PR guard.</li>
<li>Убрать local authority и отключить старые writers.</li>
<li>Провести no-write rehearsal и один exact activation merge.</li>
<li>Выполнить минимум две реальные E2E-задачи.</li>
</ol>
<p>После шага 5 мы проверим все текущие SDD/OLED rules. Лишний механизм или gate будет удалён до public transition.</p>

<h2>Какие согласования ещё нужны</h2>
<table>
<tr><th>Момент</th><th>Почему нужен stop</th><th>Что увидит оператор</th></tr>
<tr><td>Первый activation merge</td><td>Это первая реальная запись в canonical vNext ledger.</td><td>Точный predecessor, genesis, sequence zero, state hash и результаты проверок.</td></tr>
<tr><td>Переход в public</td><td>Уже раскрытую историю нельзя сделать снова секретной.</td><td>Exposure audit, текущий ref, ruleset payload и negative checks.</td></tr>
</table>
<p><strong>Других обязательных approval gates сейчас нет.</strong></p>

<h2>Нужна ли помощь сейчас</h2>
<section class="card"><p><strong>Нет.</strong> Сначала надо закончить code review и посадить code-only реализацию в <code>main</code>.</p>
<p>После этого я соберу exact package. Тогда понадобится ваше согласование точных ledger bytes.</p></section>

<h2>Текущий read-only snapshot</h2>
<table>
<tr><th>Поле</th><th>Значение</th></tr>
<tr><td>Canonical repository</td><td><code>WeTheAgents/wetheagents</code></td></tr>
<tr><td>Repository ID</td><td><code>{_esc(repo_id)}</code></td></tr>
<tr><td>Private</td><td><code>{_esc(private)}</code></td></tr>
<tr><td>Snapshot <code>main</code></td><td><code>{_esc(head)}</code></td></tr>
<tr><td>Ruleset API snapshot</td><td><code>HTTP {_esc(ruleset_http)}</code></td></tr>
</table>
<p class="hash">Это snapshot из read-only inspection. Перед mutation мы прочитаем GitHub state снова.</p>

<h2>Документы и hashes для аудита</h2>
<p><a href="spec-1.1.md">Spec 1.1</a></p><div class="hash">SHA-256: {spec_hash}</div>
<p><a href="design-1.3.md">Design 1.3</a></p><div class="hash">SHA-256: {design_hash}</div>
<p><a href="tasks-2.2.md">Active Tasks 2.2 runbook</a></p><div class="hash">SHA-256: {tasks_hash}</div>
<p><a href="WEA_vNext_BLOCK9_PRIVATE_CANONICAL_PILOT_DECISION.txt">Owner decision record</a></p><div class="hash">SHA-256: {decision_hash}</div>
<p><a href="design-1.2.md">Historical accepted Design 1.2</a></p><div class="hash">SHA-256: {design_1_2_hash}</div>
<p><a href="GROUP2_INSPECTION.json">Read-only inspection</a></p><div class="hash">SHA-256: {inspection_hash}</div>

<section class="card stopbox"><h2 style="margin-top:0">Сейчас ledger и GitHub settings не изменены</h2>
<p>Actions и guard готовы локально. Этот HTML не является activation package.</p>
<p>Exact package можно связать только с commit, который окажется на canonical <code>main</code> после code review.</p></section>
</main></body></html>"""
    return document.encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered = _build()
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_bytes() != rendered:
            print("stale Group 2 review artifact")
            return 1
        print("Group 2 review artifact is current")
        return 0
    OUTPUT.write_bytes(rendered)
    print(OUTPUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
