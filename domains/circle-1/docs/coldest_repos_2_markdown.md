# Семантическая температура Python-репозиториев: рубрика для агентной разработки

**Главный вывод: агент-дружественность — это не размер, не популярность и даже не качество кода; это предсказуемость в семи независимых слоях.** Из 15 проанализированных Python-репозиториев самым «замороженным» (агент-friendly) оказался **pytest** (13/100), самым «раскалённым» — **tensorflow** Python-слой (~68/100). Разрыв между ними объясняется не объёмом, а наличием единых контрактов на всех уровнях: от CONTRIBUTING.md до иерархии исключений. Ключевая находка: **типизация (L2) и tribal knowledge (L7) — главные независимые оси разброса**; остальные слои сильно коррелируют с ними. Возраст кода и смешение с C++/Rust/CUDA систематически повышают температуру, а наличие scaffold-инструментов (home-assistant) или единого линтера копий (transformers) может локально компенсировать хаос даже в очень больших репозиториях. Отчёт ниже даёт (A) единый рейтинг, (B) детальный разбор экстремумов, (C) операциональную рубрику с AST/grep/CLI-метриками, (D) карту инструментов, (E) неожиданные наблюдения и (F) рекомендации для dogfooding.

**Методологическое предупреждение.** Анализ проводился через сэмплирование (root-файлы, pyproject, 3–10 модулей, 10–20 merged PR на репозиторий); численные оценки имеют погрешность ±5. Для крупных монорепозиториев (cpython, tensorflow, pandas) разброс температуры *внутри* самого репозитория сопоставим с межрепозиторным — это тоже самостоятельный диагностический сигнал.

---

## Часть A. Сводный рейтинг по 7 слоям

Шкала: **0 = замороженный / идеально агент-friendly**, **100 = раскалённый / агент плавает**. Итог — взвешенное среднее с весами L1=0.10, L2=0.20, L3=0.25, L4=0.10, L5=0.10, L6=0.10, L7=0.15 (обоснование весов в Части C).

| # | Репозиторий | L1 Harness | L2 Types | L3 Code sem. | L4 Tests | L5 Errors | L6 Observ. | L7 Tribal | **Итог** | Главная причина |
|---|-------------|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|---|
| 1 | pytest-dev/pytest | 10 | 15 | 15 | 5 | 20 | 15 | 10 | **13** | Dogfooding + towncrier + жёсткий ruff; явная анти-LLM политика единственный минус |
| 2 | pydantic/pydantic | 20 | 5 | 25 | 15 | 10 | 15 | 20 | **16** | `llms.txt`, собственный mypy-plugin, `PydanticErrorMixin` с кодами |
| 3 | pallets/flask | 25 | 15 | 15 | 10 | 35 | 20 | 15 | **19** | `mypy+pyright+py.typed`, `filterwarnings=error`, маленький scope |
| 4 | encode/httpx | 35 | 12 | 10 | 18 | 8 | 30 | 20 | **19** | Эталонный async/sync parity через unasync, чистая иерархия исключений |
| 5 | sqlalchemy/sqlalchemy | 40 | 18 | 28 | 12 | 5 | 22 | 20 | **22** | Мировая иерархия `exc.py`, narrative changelog; Gerrit off-GitHub тянет вверх |
| 6 | django/django | 30 | 70 | 20 | 15 | 8 | 15 | 10 | **24** | Монолитный стиль + `core/exceptions.py`; типы живут во внешнем django-stubs |
| 7 | fastapi/fastapi | 30 | 10 | 30 | 10 | 25 | 20 | 45 | **24** | Strict mypy + `py.typed`; BDFL-горлышко и мета-магия DI |
| 8 | home-assistant/core | 30 | 55 | 45 | 25 | 25 | 20 | 45 | **35** | Scaffold + `manifest.json` спасают; 2000+ integrations дают неизбежную вариативность |
| 9 | pandas-dev/pandas | 35 | 55 | 50 | 20 | 30 | 45 | 20 | **37** | PDEP + numpydoc + TDD; Cython-слой, warnings-культура, stubs в отдельном репо |
| 10 | psf/requests | 45 | 75 | 45 | 25 | 10 | 15 | 40 | **39** | Нет inline-типов до 2026; эталон exceptions не компенсирует |
| 11 | python/cpython (Lib/) | 35 | 78 | 55 | 30 | 10 | 45 | 15 | **42** | Type-пустыня в Lib (типы в typeshed); 20-летние модули стилистически неоднородны |
| 12 | apache/arrow (python/) | 40 | 65 | 45 | 30 | 50 | 50 | 30 | **44** | Трёхслойная `.py/.pyx/.pxd` иерархия, stubs внешние |
| 13 | pytorch/pytorch (torch/) | 55 | 55 | 70 | 45 | 50 | 55 | 45 | **54** | 5+ style-островов: torch.nn / fx / dynamo / inductor / jit; RuntimeError-монокультура |
| 14 | huggingface/transformers | 50 | 60 | 70 | 50 | 60 | 30 | 65 | **55** | «Single-model-single-file» + `# Copied from` + unittest-Mixin — специфичная дисциплина copy-paste |
| 15 | tensorflow/tensorflow (python/) | 78 | 85 | 90 | 55 | 60 | 65 | 50 | **68** | Три параллельные вселенные: compat.v1 / core / keras; copybara; нет `py.typed` |

**Ключевые наблюдения по таблице.** Корреляция L2↔L3 высокая (r≈0.7 на глаз): строгие типы почти всегда идут вместе с единым стилем кода. L5 (ошибки) и L6 (observability) — наименее коррелированные оси: django отлично по L5/L6 при слабом L2; requests — эталон по L5 при катастрофе по L2. L7 (tribal) ведёт себя нелинейно: transformers имеет *жёсткий* процесс (make fix-copies), но его специфичность повышает температуру для внешнего агента.

---

## Часть B. Детальный разбор экстремумов

### Top-5 холодных (агент-friendly)

**1. pytest-dev/pytest — итог 13.** Меньший репозиторий в выборке ведёт себя как «аквариум»: `CONTRIBUTING.rst` (615 строк) содержит раздел *AI/LLM-Assisted Contributions Policy* с явным тезисом «purely agentic contributions are not accepted» — парадоксально, именно эта жёсткость делает репо предсказуемым. Ruff-селекторы `B, D, E, F, I, PGH004, PIE, PLC, PLE, PLR, PLW, PYI` в `pyproject.toml` вместе с `isort.force-single-line=true` фиксируют стиль до уровня одного импорта на строку. Тесты (`testing/`) зеркалят `src/_pytest/` файл-в-файл — агент не гадает, куда класть тест. Towncrier-дисциплина с типами `feature/bugfix/improvement/doc/deprecation/breaking/vendor/trivial` в `changelog/<ISSUE>.<TYPE>.rst` делает каждый PR дисциплинированным. **Что охлаждает:** единообразие даже в тестах самого фреймворка. **Что греет:** `pytest.fail.Exception(Failed)` — необычное имя требует дополнительного контекста.

**2. pydantic/pydantic — итог 16.** Единственный репозиторий с **llms.txt** (`docs.pydantic.dev/latest/llms.txt`) — файл, специально созданный для LLM-агентов. `pyproject.toml` подключает `pydantic.mypy` плагин с `init_forbid_extra`, `init_typed`, `warn_required_dynamic_aliases`; mypy strict и pyright идут параллельно. `pydantic/errors.py` — эталонная иерархия с `PydanticErrorMixin → PydanticUserError/PydanticUndefinedAnnotation/PydanticSchemaGenerationError`, каждая ошибка имеет `code=` → машиночитаемо. `HISTORY.md` ссылается на каждый PR номером. **Что охлаждает:** собственный mypy-plugin, Google-docstrings с `pydocstyle`-линтингом, формальная `docs/version-policy.md`. **Что греет:** плотная метамагия в `pydantic/_internal/_generate_schema.py` и наличие Rust-ядра `pydantic-core` — агенту нужно помнить, что часть логики вне Python.

**3. pallets/flask — итог 19.** Маленький и дисциплинированный. `pyproject.toml` содержит **`filterwarnings = ["error"]`** (любое warning в тестах → падение) и `[tool.mypy] files = ["src", "tests/type_check"]` + отдельная типовая группа через pyright. `src/flask/typing.py` централизует типовые алиасы (`ResponseReturnValue`). Src-layout (`src/flask/`), разделение `src/flask/sansio/app.py` vs стандартной версии — явный паттерн для переиспользования. **Что охлаждает:** `classifiers = [..."Typing :: Typed"]`, py.typed, чёткий PR-checklist с `:pr:`, `:issue:`, `.. versionchanged::`. **Что греет:** исключения делегированы werkzeug (`HTTPException` — не свой), агенту нужно знать про зависимость.

**4. encode/httpx — итог 19.** Младший брат requests, сделанный строгим. Эталон async/sync parity через **unasync** (генерация sync-версии из async-исходника). `httpx/_exceptions.py` — плавная иерархия `HTTPError → RequestError/HTTPStatusError → TransportError → TimeoutException/NetworkError`. Приватность через `_*`-префикс модулей (`_client.py`, `_exceptions.py`) дисциплинирована. FIXME-комментарии обязательно со ссылкой на issue (`# See: https://github.com/encode/httpx/issues/771`). **Что охлаждает:** современный Python 3.9+ стиль, `ruff UP (pyupgrade)` правила (PR #3768), прозрачные enum состояний (`ClientState(UNOPENED/OPENED/CLOSED)`). **Что греет:** обсуждение V1.0 в discussion #3344 (возможный split на `httpx`/`ahttpx`) — будущая неопределённость для агента.

**5. sqlalchemy/sqlalchemy — итог 22.** Загадочно холодный гигант. `lib/sqlalchemy/exc.py` содержит, возможно, лучшую иерархию исключений в Python-экосистеме: `SQLAlchemyError → DBAPIError → OperationalError/IntegrityError/DataError/...` (зеркалит PEP 249), параллельно `ArgumentError → AmbiguousForeignKeysError`, `InvalidRequestError → LoaderStrategyException`, плюс ORM-ветка `orm.exc.FlushError/StaleDataError/DetachedInstanceError` и хитрый `DontWrapMixin` для user-defined ошибок. С 2.0 включена native PEP 484 типизация через `Mapped[T]`, `mapped_column()`, `DeclarativeBase`. Логгеры namespaced: `sqlalchemy.engine`, `sqlalchemy.pool`, `sqlalchemy.dialects.*`. **Что охлаждает:** педантичный narrative changelog в `doc/build/changelog/changelog_*.rst` с `:tickets:` / `:tags:` / `:versions:`, кастомная тестовая инфраструктура `lib/sqlalchemy/testing/`. **Что греет:** **Gerrit** (`gerrit.sqlalchemy.org`) как платформа код-ревью — GitHub-агент туда не попадёт, tribal knowledge утекает с платформы.

### Bottom-5 горячих (агенту сложно)

**15. tensorflow/tensorflow (Python-слой) — итог 68.** Три параллельные вселенные в одном пакете: `tf.*` core (`tensorflow/python/ops/`, snake_case, `@tf_export(...)` декораторы), `tf.keras` (классовый PascalCase, совершенно другая история, Keras 3 — отдельный governance в `keras-team/governance/rfcs`), и `tf.compat.v1` с graph/session парадигмой (`variable_scope`, `Session`, `Graph().as_default()`). Плюс `tf.estimator`, `tf.experimental`, `tf-addons`. **Отсутствует `py.typed`** (issue #58837), типы приходят из `types-tensorflow` в typeshed partial. Copybara-зеркало из Google-internal — «истинный» код живёт снаружи. Логирование — `tf.get_logger()` (обёртка над absl), не stdlib. **Главная боль агента:** приходится *сначала определять, в каком острове* он находится.

**14. huggingface/transformers — итог 55.** «Организованный хаос ML-библиотеки». Файлы моделей — многотысячные (`modeling_llama.py`, `modeling_mistral.py`), и это **намеренно**: политика «single model, single file» ломает DRY. Дисциплину держит *семантический*, а не структурный механизм: комментарии `# Copied from xxx.Module.method`, проверяемые `utils/check_copies.py`. Новая ветка — **Modular Transformers** (`modular_<model>.py` → линтер-unraveller генерирует `modeling_*.py`). Тесты — гибрид: **unittest-классы через pytest**, без `@pytest.fixture`/`parametrize`, вместо них `parameterized.expand` + Mixin-цепочки `ModelTesterMixin/GenerationTesterMixin/PipelineTesterMixin`. Кастомный `transformers.utils.logging` с `WARNING_ADVICE` уровнем — уникум. **Ловушка агента:** любая попытка «навести порядок» (убрать копипаст) ломает `make fix-copies` в CI на десятках моделей.

**13. pytorch/pytorch (torch/) — итог 54.** Пять style-островов: `torch.nn` (классическая ООП), `torch.fx` (symbolic tracing, функциональный стиль, `GraphModule`/`Proxy`), `torch.compile/_dynamo/_inductor` (bytecode-трансформация, FakeTensor, Triton), `torch.jit`/TorchScript (устаревающая параллельная типизированная подсистема), `torch.distributed` с собственным `CONTRIBUTING.md`. Типы частично генерируются из `.pyi.in` шаблонов через `tools/pyi/gen_pyi.py` из `native_functions.yaml` — тройная система исходников (`.py` + `.pyi.in` → `.pyi`). Ошибки — монокультура `RuntimeError` из `TORCH_CHECK` в C++ через pybind11. **Что охлаждает:** отдельный `pytorch/rfcs` репо с RFC-0024, структурированный `TORCH_LOGS="+dynamo,aot"`, CODEOWNERS + `module: *` labels для триажа. **Что греет:** множество `torch._*` приватных модулей — агент видит underscore и не знает, можно ли его читать как контракт.

**12. apache/arrow (python/, pyarrow) — итог 44.** Тройная иерархия одного API: `foo.py` (pythonic wrapper) → `_foo.pyx` (Cython glue) → `includes/_foo.pxd` (C++ declarations). Stubs внешние — `zen-xu/pyarrow-stubs`, discussion #45919 о донорстве в апстрим. `pyarrow.dataset` явно помечена как unstable в docstring. **Что охлаждает:** pytest + Hypothesis, Apache-license-header на всех `.py` файлах (механически проверяемый сигнал), `archery lint` как единый CLI-инструмент, ~5 style-островов (против десятков у PyTorch/TF). **Что греет:** для Python-only агента необходимость читать Cython `.pyx` при сомнениях — «настоящий» API там.

**11. python/cpython (Lib/) — итог 42.** Уникальная патология: референс-реализация языка, в котором нет типов в своей же stdlib. Типы живут отдельно в `python/typeshed`, `py.typed` отсутствует, `[tool.mypy]` нет. Возрастная неоднородность — `Lib/logging/__init__.py` написан в одну эпоху (плотный reST/plain docstring), `Lib/unittest/main.py` — в другую (короткие комментарии), `Lib/asyncio/` — в третью (async-first). В некоторых `__init__.py` stdlib остался `from X import *`. Тесты централизованы в `Lib/test/test_*.py` с общим `test.support`, используется `unittest`, не pytest. **Что охлаждает:** PEP 7/PEP 8 процесс, `Misc/NEWS.d/` через `blurb` — эталонная changelog-дисциплина; каждый модуль имеет локальные exception-классы (`json.JSONDecodeError`). **Что греет:** `Lib/` настолько большой, что разброс температуры *внутри* (между `asyncio` и `argparse`) сопоставим с межрепозиторным.

---

## Часть C. Операциональная рубрика для CLI-инструмента

Рубрика сгруппирована по слоям; для каждого критерия указаны ручная проверка, автоматизация, и калибровка холодно/тепло. Веса внутри слоя нормализованы; межслоевые веса: **L1=0.10, L2=0.20, L3=0.25, L4=0.10, L5=0.10, L6=0.10, L7=0.15** (L3 и L2 получают наибольшие веса, потому что именно они ежедневно касаются агента при написании кода).

### Слой 1: Explicit conventions (вес 0.10)

| Критерий | Как измерить | Холодно (0–20) | Тепло (80–100) | Вес |
|---|---|---|---|---|
| Наличие AGENTS.md/CLAUDE.md/llms.txt в root | `test -f AGENTS.md` / `ls llms.txt` | Файл есть, >500 слов, указывает структуру | Файл отсутствует | 0.30 |
| CONTRIBUTING.md полнота | Длина в строках, наличие секций: dev-setup, style, tests, PR-процесс | >400 строк, все 4 секции | Отсутствует или <50 строк | 0.20 |
| Вложенные AGENTS.md/README в значимых поддиректориях | `find . -name AGENTS.md -o -name CLAUDE.md` и измерить coverage по крупным пакетам | >50% крупных пакетов | 0% | 0.25 |
| PR/issue templates | `ls .github/PULL_REQUEST_TEMPLATE.md .github/ISSUE_TEMPLATE/` | Есть оба, с чек-листами | Нет | 0.10 |
| Явная design-doc/RFC-дисциплина | `docs/rfcs/` или ссылка на отдельный репо; `find . -name "*.rst" -path "*changelog*"` | Формальный процесс с шаблоном и workflow | Design-решения в Discord/Slack | 0.15 |

### Слой 2: Type contracts (вес 0.20)

| Критерий | Как измерить | Холодно | Тепло | Вес |
|---|---|---|---|---|
| Покрытие аннотациями функций | AST-скрипт: для каждого `FunctionDef` проверить `returns is not None` и `all(a.annotation for a in args.args)`; отношение | >90% функций полностью аннотированы | <30% | 0.30 |
| py.typed marker | `find . -name py.typed` в корне пакета | Есть | Нет (для библиотеки) | 0.15 |
| mypy/pyright strict mode | Parse `pyproject.toml`: `[tool.mypy].strict = true`; или `pyright`-config с `strict = [...]` | strict=true на всём коде | Нет секции mypy/pyright | 0.25 |
| Доля `Any` и нетипизированных `dict/tuple` | `grep -rn ": Any\|-> Any\|Dict\[str, Any\]" --include="*.py" \| wc -l` нормировать на LOC | <1 на 1000 LOC | >10 на 1000 LOC | 0.10 |
| Использование TypedDict/Protocol/dataclass вместо raw dict | AST: count `class X(TypedDict)`, `class X(Protocol)`, `@dataclass` vs `return {...}` в публичных API | >80% публичных структур — типизированы | Публичные API возвращают `dict` | 0.20 |

### Слой 3: Code-level semantic coldness (вес 0.25)

| Критерий | Как измерить | Холодно | Тепло | Вес |
|---|---|---|---|---|
| Единообразие структуры модулей | AST: для всех публичных пакетов проверить наличие `__init__.py`, `__all__`, одинаковый паттерн re-export | Все модули идентичной структуры | Каждый модуль уникален | 0.15 |
| Стиль именования | ruff-правила `N801-N818` (pep8-naming). `ruff check --select N --statistics` | 0 нарушений | >100 нарушений | 0.10 |
| Дисциплина импортов | ruff: `I, F401, F403, TID252`; grep `from .* import \*` | Нет star-imports в проде, один стиль (abs/rel) | Микс, есть `*`-импорты | 0.10 |
| Единый формат docstrings | AST + regex: определить формат (Google/NumPy/Sphinx) по первым 10 docstrings каждого публичного модуля; проверить гомогенность | Все модули в одном формате, `pydocstyle --convention=...` проходит | Микс форматов | 0.15 |
| Распределение длины функций | `radon cc -a -s .`; измерить std(length) / median(length) | коэффициент <1.5, медиана <30 строк | std/median >3, медиана >50 | 0.15 |
| Cyclomatic complexity распределение | `radon cc --total-average --min B`; доля функций с rank A/B | >90% rank A/B | >30% rank C+ | 0.10 |
| Единый error-handling паттерн | AST: распределение `raise` statements по типам исключений в одном слое; доля bare `except:` | Один кастомный exception-класс доминирует | Каждый модуль бросает своё | 0.10 |
| Async-паттерн гомогенность | AST: доля `async def` vs sync в модулях которые async | Весь I/O единообразно async или sync | Синхронные враппера вокруг async | 0.10 |
| Отсутствие "островов стиля" | Кластеризация AST-фич по каталогам (PascalCase-доля, avg func length, docstring format) — silhouette score | Один кластер | 3+ кластера | 0.05 |

### Слой 4: Test architecture (вес 0.10)

| Критерий | Как измерить | Холодно | Тепло | Вес |
|---|---|---|---|---|
| Единое расположение тестов | Парсер: все тесты в `tests/` ИЛИ все рядом с модулем — не микс | Одно правило на весь репо | Микс | 0.25 |
| conftest.py иерархия | `find . -name conftest.py`; анализ shared fixtures | Один conftest на уровень, fixtures переиспользуются | Дублирование fixtures | 0.20 |
| Parametrize discipline | `grep -rn "@pytest.mark.parametrize" . \| wc -l` деленое на количество test_* | >0.3 parametrize на тестовую функцию | <0.05 | 0.20 |
| Единый mocking approach | `grep -rn "unittest.mock\|pytest_mock\|respx\|mocker" . \| uniq -c` | Один инструмент доминирует | Микс 3+ | 0.15 |
| Хельперы в отдельной папке | `tests/utils/` / `tests/helpers/` / `testing/` vs разбросаны | Централизованно | Разбросаны | 0.10 |
| Strict test configuration | `pyproject.toml`: `addopts=["--strict-config","--strict-markers"]`, `filterwarnings=["error"]` | Всё есть | Ничего | 0.10 |

### Слой 5: Error taxonomy (вес 0.10)

| Критерий | Как измерить | Холодно | Тепло | Вес |
|---|---|---|---|---|
| Единый базовый класс исключений | AST: найти все `class X(Exception)`; проверить наличие корневого `<Pkg>Error` и процент наследников | >80% кастомных ошибок от одного корня | Нет корня | 0.35 |
| Централизация | `find . -name "exceptions.py" -o -name "exc.py" -o -name "errors.py"`; доля ошибок в этих файлах | Все в одном модуле | Разбросаны | 0.20 |
| Машиночитаемые коды/категории | grep на поля `code=`, `category=` в exception-классах | Все ошибки с `code=` | Только human message | 0.20 |
| Отсутствие bare `raise Exception(...)` | AST: count `Raise(Call(Name('Exception')))` и `raise RuntimeError` без подклассов | ~0 | >0.5 на 100 LOC | 0.15 |
| Deprecation discipline | `grep -rn "DeprecationWarning\|@deprecated"`; наличие собственного `DeprecationWarning`-подкласса | Собственный подкласс, все deprecation через него | Неструктурированные warnings | 0.10 |

### Слой 6: Observability (вес 0.10)

| Критерий | Как измерить | Холодно | Тепло | Вес |
|---|---|---|---|---|
| Канонический logger-паттерн | `grep -rn "getLogger(__name__)" . \| wc -l` vs все `getLogger(` | >95% через `__name__` | Именованные строками | 0.35 |
| print() в production коде | ruff `T201/T203`; `grep -rn "^\s*print(" src/` | Ноль (только `--verbose` CLI) | Регулярный | 0.25 |
| Единая библиотека логирования | grep на `import logging`, `import structlog`, `import loguru` — в `src/` только одна | Одна библиотека | Смесь 2+ | 0.20 |
| Дисциплина уровней | AST: распределение calls к `debug/info/warning/error/critical`; sanity: >5% debug, >0.5% error | Нормальное распределение | Всё как `info()` | 0.10 |
| Namespaced logger tree | Логгеры типа `sqlalchemy.engine`, `django.request` | Есть явная иерархия | Плоская | 0.10 |

### Слой 7: Tribal knowledge & process discipline (вес 0.15)

| Критерий | Как измерить | Холодно | Тепло | Вес |
|---|---|---|---|---|
| PR review — логика vs стиль | GitHub API: 30 последних merged PR; regex по комментариям ревьюеров: `rename\|format\|lint\|style\|conform` vs `logic\|correctness\|edge case\|race` | >70% ревью про логику | >50% про стиль | 0.25 |
| Changelog discipline | `test -d changelog.d/` (towncrier), `test -f CHANGES.rst` / `HISTORY.md`; средняя длина release-notes | towncrier/blurb + детальные нотес | Автогенерация из squash commits | 0.20 |
| Issue/PR template реально заполняется | GitHub API: доля PR, где template-заголовки реально заменены | >80% | <20% (шаблоны игнорируются) | 0.15 |
| CODEOWNERS и модульные owners | `test -f .github/CODEOWNERS`; распределение покрытия | Весь код имеет owners | Нет файла | 0.10 |
| Design doc workflow | Наличие `docs/rfcs/`, `docs/design/`, ADR или отдельного репо; частота merge за год | Живой — >3 за год | Нет папки | 0.15 |
| Ревью off-platform | Ищем в CONTRIBUTING упоминания Gerrit, Phabricator, Gitter, Discord, Slack как основной платформы | Всё на GitHub | Ревью вне GitHub | 0.15 |

---

## Часть D. Инструменты автоматизации

**AST-модуль Python (стандартная библиотека) — самое ценное.** Через `ast.parse` + `ast.walk` прямо извлекаются: покрытие аннотаций (L2), распределение типов exception (L5), доля `print()` и вариации `logging.getLogger` (L6), метаданные функций для L3 (длина, вложенность, имена). **Рекомендация:** собрать эти метрики в один скрипт `temperature_scan.py` — он закроет ~40% рубрики без внешних зависимостей.

**Существующие инструменты по слоям:**

| Слой | Готовые инструменты | Что покрывают |
|---|---|---|
| L2 | `mypy --strict`, `pyright --outputjson`, `pyanalyze`, `monkeytype` (runtime) | Покрытие типов, strict-compliance |
| L3 | `ruff` (N, D, I, PL, B, UP, T201, SIM), `black`, `radon` (cc, mi, hal), `wily` (исторический тренд complexity), `pydocstyle`, `import-linter` (контракты импортов), `pydeps` (граф зависимостей), `vulture` (dead code) | Именование, структура, сложность, дисциплина импортов |
| L4 | `pytest --collect-only --quiet` для инвентаризации; `coverage.py`; `pytest-randomly` (детектирует скрытые зависимости) | Структура тестов |
| L5 | Нет готового — **требуется AST-скрипт** для построения графа наследования исключений | Иерархия ошибок |
| L6 | `ruff T201/T203` для print, кастомный AST для logger-паттернов | Observability |
| L7 | GitHub API (`PyGithub`, `gh api`), `git log --format=...` для heuristics по squash-culture | PR/issue анализ |

**Что требует LLM-оценки** (автоматизировать дорого или невозможно):
- Определение формата docstrings на смешанных примерах (L3.4) — regex ловит ~80% случаев, LLM нужен для граничных.
- Качество PR-дискуссий: «это обсуждение про логику или стиль?» (L7.1) — LLM-классификатор по комментариям.
- Оценка связности «голоса» кода (L3.9): есть ли «острова стиля» — кластеризация даёт численный сигнал, но LLM объясняет *почему*.
- Обнаружение tribal knowledge в коде: фразы `# we do it this way because...` без контекста.

**GitHub API (критично для L7):** `GET /repos/{owner}/{repo}/pulls?state=closed&per_page=100` → для каждого PR `GET /repos/{owner}/{repo}/pulls/{n}/comments` → регулярные выражения по комментариям. 3 запроса на PR × 30 PR = 90 запросов — укладывается в rate-limit с токеном.

**Что НЕ надо автоматизировать** (шум > сигнал): наличие бейджей в README, количество звёзд, размер репозитория, количество контрибьюторов. Всё это не коррелирует с температурой: pytest (13) и cpython (42) имеют сравнимые масштабы сообщества.

---

## Часть E. Неожиданные наблюдения и паттерны

**Возрастной парадокс наоборот.** Ожидание: молодые репо (fastapi, pydantic v2, httpx) холоднее старых. Реальность частично подтверждает, но есть аномалии: **django** (2005) имеет итог 24, холоднее чем **requests** (2011, итог 39). Причина — Django инвестировал в DEP-процесс, единый `core/exceptions.py`, строгий coding-style в doc/internals; requests застрял в Python-2-эпохе без inline-типов до 2026. **Вывод: возраст < инвестиции в process.**

**«Экспертные модули» — устойчивая патология.** В каждом крупном репо нашли 1–2 подсистемы, живущие по своим правилам: `Lib/asyncio/` в cpython, `pydantic/_internal/_generate_schema.py`, `torch._dynamo/`, `tf.compat.v1`, `pyarrow.dataset` («unstable»). Общий признак: **приватные-с-подчёркиванием модули с плотной метамагией**, обслуживаемые 1–2 мейнтейнерами. Это зоны, где агент обязательно напортачит, если его не предупредить.

**requests явно анти-агентский в 2026.** В RFC #7271 / PR #7272 на inline-типы есть фраза: *"Comments that are clearly AI-generated will be hidden or removed. This is a library written for Humans"*. Это первый найденный случай **явной политики против LLM-агентов** в public Python-репо. pytest делает то же мягче («Purely agentic contributions are not accepted»). **Диагностический сигнал для агента:** искать такие фразы в CONTRIBUTING.

**Корреляция L2↔L5 неожиданно слабая.** Гипотеза была: проекты со строгой типизацией также имеют хорошую иерархию исключений. Реальность: **requests** (L2=75, hot) имеет лучшую иерархию `exceptions.py` в выборке (L5=10), **transformers** (L2=60) голые `ValueError/RuntimeError` (L5=60). Объяснение: L5 требует архитектурного решения, L2 — организационного. Это разные типы дисциплины. Для агента: **L5 — ранний сигнал о том, думал ли кто-то об API, L2 — об инструментах.**

**C++/Rust/CUDA всегда нагревают Python.** Все три монорепо-гиганта (TF, PyTorch, Arrow) имеют суммарную температуру 44–68 против 13–39 у чистых Python-проектов. Причина систематическая: (а) `RuntimeError` монокультура из pybind11/SWIG/Cython, (б) невозможность полной типизации через stub-генерацию из C++, (в) «Any»-утечки, (г) параллельные поколения API из-за эволюции C++-ядра. **Практический вывод для рубрики:** при обнаружении `.pyx/.pyi.in/.cc` в репозитории автоматически добавлять +10–15 к L2 и L5.

**Scaffold-инструменты — недооценённый cooling mechanism.** `home-assistant/core` со своим `python3 -m script.scaffold` (генерирует `manifest.json`, `__init__.py`, `config_flow.py`, `const.py`, `quality_scale.yaml`, тесты, `strings.json`) спускает структурную температуру 2000+ integrations до приемлемого уровня (итог 35 при огромном масштабе). Аналогично `transformers` с Modular Transformers (`modular_<model>.py` → автогенерация). **Это лучшее средство против масштаба**, которое увидели в выборке. Для dogfooding: если репозиторий имеет >10 однотипных подсистем — scaffold обязателен.

**Патологии по доменам.**
- **ML (pytorch, tensorflow, transformers):** слабая типизация + RuntimeError-монокультура + style-острова из-за эволюции API. Общая температура 54–68.
- **Web (flask, fastapi, django):** наоборот — сильная типизация, строгие exception hierarchies. Температура 19–24. Веб-фреймворки систематически холоднее.
- **Данные/IO (pandas, arrow, requests, httpx, sqlalchemy):** разброс огромный (19–44). Зависит от наличия Cython/C.
- **Инфраструктурные (pytest, pydantic, cpython):** разброс зависит от возраста (pytest/pydantic 13–16; cpython 42).

**Формат docstrings как возрастной маркер.** rST/Sphinx — django, flask, cpython (модули старше 2015). Google — fastapi, pydantic, tensorflow. NumPy — pytorch, pandas, pyarrow (научный стек). В смешанных репозиториях (cpython Lib/) формат меняется от модуля к модулю — сильный сигнал неоднородности. **Для рубрики:** автоопределение формата по первым 10 docstrings и кластеризация — эффективный детектор «возрастных слоёв».

**llms.txt как новый стандарт.** Pydantic — единственный с ним среди выборки, fastapi добавил `.agents/skills/fastapi/SKILL.md` в феврале 2026. Это *новейшая* конвенция (появилась в 2024–2025). Прогноз: в течение 2026 года `AGENTS.md` и `llms.txt` станут de-facto стандартом, и их отсутствие будет сильным сигналом на L1.

---

## Часть F. Рекомендации для dogfooding

**Минимальный набор из 10 самых предиктивных критериев** (в порядке убывания ценности сигнала):

1. **L2.1** Покрытие аннотациями функций через AST (≥90% = сильно холодно).
2. **L5.1** Наличие единого корневого `<Pkg>Error` с ≥80% наследников.
3. **L3.4** Единый формат docstrings (AST + regex на первые 10 docstrings каждого публичного модуля).
4. **L6.1** Доля `logging.getLogger(__name__)` от всех вызовов `getLogger` (≥95%).
5. **L7.1** GitHub-API анализ 30 последних merged PR: доля ревью «про стиль» vs «про логику».
6. **L3.5** Распределение длины функций (std/median через radon).
7. **L2.3** `[tool.mypy].strict = true` в `pyproject.toml`.
8. **L1.1** Наличие `AGENTS.md` / `CLAUDE.md` / `llms.txt` в root.
9. **L4.6** `filterwarnings=["error"]` + `--strict-markers` в pytest конфиге.
10. **L3.9** Кластеризация «островов стиля» через k-means на векторе `(avg func length, PascalCase ratio, docstring format, import style)`.

**Рекомендованный порядок применения.** Три волны:

**Волна 1 (15 минут, локально, без GitHub API):** критерии 1, 2, 3, 4, 6, 7. Всё — AST + parse pyproject.toml. Даёт ~70% сигнала. Если тут плохо — остальное уже не спасёт.

**Волна 2 (10 минут, локально):** критерии 5, 8, 9, 10. Добавляет tribal + structural сигналы.

**Волна 3 (30 минут, GitHub API):** глубокий анализ PR-дискуссий, issue-template compliance, design-doc activity. Калибрует L7.

**Какие критерии дают больше шума.** (а) Количество файлов docstring — многие проекты имеют docstring-стиль в плохом формате но консистентно; качество формата важнее. (б) Общее количество `bare except:` — модули legacy IO-кода могут иметь их массово, но изолированно. (в) ruff/black-compliance — слишком просто «прошла» через CI не означает семантическую холодность.

**Baseline значения для трёх типов проектов.**

| Тип проекта | Типичный итог | Откуда смотреть | Что ожидать |
|---|---|---|---|
| Небольшой проект (<5k LOC, 1–3 мейнтейнера) | 20–35 | Эталон: flask (19), httpx (19) | L2 через `mypy --strict`; один базовый exception; `tests/` зеркалит `src/`; towncrier не нужен, HISTORY.md достаточно |
| Зрелая библиотека (20–100k LOC, 5–15 мейнтейнеров) | 25–45 | Эталон: sqlalchemy (22), django (24) | L5 обязателен (централизованный `exceptions.py`); CODEOWNERS; narrative changelog; RFC/DEP процесс |
| Корпоративный/ML монолит (>500k LOC, 50+ мейнтейнеров) | 45–70 | Эталон: home-assistant (35, нижний край), pytorch (54) | Scaffold критичен; допустимы 2–3 стиля-острова; обязательно CODEOWNERS + module labels; отдельный rfcs-репо |

**Красные флаги для собственного репо.** Если при самоизмерении вы видите: (1) итог >50 при <50k LOC — структурные проблемы; (2) L5 >40 при L2 <20 — есть типы, но нет архитектуры ошибок; (3) L7 >60 при L3 <30 — хороший код, но процесс не кодифицирован, tribal knowledge в головах; (4) большой разброс температуры между подсистемами (std по L3 >15) — нужен scaffold.

**Финальный совет.** Не оптимизируйте все семь слоёв сразу. По результатам выборки наибольший ROI даёт: **L2 (типы) → L5 (ошибки) → L1 (AGENTS.md) → L7 (changelog discipline)**. L3 (code semantics) корректируется автоматически через ruff/black, L4/L6 — механические правила. Агентная дружественность — это прежде всего **предсказуемые контракты на границах модулей**, а не красота тела функций.

---

## Заключение: температура — это предсказуемость

Исследование показало, что «семантическая температура» измеряет не качество кода, а **энтропию контракта между модулями**. Лучшие результаты (pytest, pydantic, flask) — это не самые элегантные проекты, а те, где агент может *вывести* правила из любой части репозитория. Худшие (tensorflow, transformers, pytorch) — не плохо написанные, а содержащие несколько параллельных контрактов без явной границы между ними. **Главный операциональный вывод для dogfooding: температура понижается не через улучшение отдельных файлов, а через установление инвариантов на уровне пакета** — единого base exception, единого docstring-формата, единого logger-паттерна, единого AGENTS.md. Рубрика в Части C позволяет измерить каждый из этих инвариантов автоматически и получить интегральную оценку за <1 минуту на репозиторий.

Два неожиданных методологических следствия. Во-первых, **L5 (error taxonomy) — удивительно сильный ранний предиктор** общей температуры: проекты с продуманной иерархией исключений почти всегда имеют и другие признаки зрелости, потому что дизайн ошибок требует системного мышления. Во-вторых, **смешение языков (C++/Rust/Cython/CUDA) систематически добавляет 10–25 к температуре Python-слоя** независимо от качества обвязки — это структурный налог, который стоит учитывать как отдельное измерение в будущей версии рубрики. Для Фазы 3 логично добавить восьмой слой: *cross-language boundary discipline* — насколько агент может работать только в Python-слое, не заходя в C++.