# Agent0 handoff: Ready for Block 4

Blocks 1–3 завершены. Block 3 добавляет неактивную immutable closure `v0_6_3` для общего Draft validator, Triage/Negativa и атомарной активации ordinary Contract. Старые `v0_6_0…v0_6_2` сохранены byte-for-byte; System Hello World остаётся fail closed. WEA vNext не подключена к GitHub или ledger. `[CHAT][CHECK][REVIEW]`

Статус Block 3: `Ready for Block 4`. Техническая модель: `design 0.8`; schema `0.8`; план `tasks 1.0`. WEA vNext: `Not live`.

## Репозиторий и рабочая граница

- Worktree: `D:\GitHub\wetheagents-codex-wea-vnext-block3-2026-07-28`.
- Branch: `codex/wea-vnext-block3-contract-core-2026-07-28`.
- Base: `6a623cd631793a53430da135196903116866cb95` (`origin/main`, merge Block 2).
- Текущий executor: `v0_6_3`, manifest SHA-256 `b1152140a3d47ab5ff884410438156077d205436cf1b10ad106134e34fdcd0ab`.
- Frozen manifests: `v0_6_0` — `8d2a71e15be535abbbd19eeb4c2b8909f29055f26c87989b26c3826c9f92b6b3`; `v0_6_1` — `dc8298657c13202350d9394e9d198c6a0746dd9bbb230c48a254cad38cd7f2b2`; `v0_6_2` — `975b071d5bb49e14afd71d5b9c07d6113750884c1a9cc9c9b487324b71b100c7`.
- Ledger, GitHub, `scripts/tide_vnext.py`, `ledger/vnext/`, migration/bootstrap и live adapters не изменялись.

## Реализованный контракт Block 3

- Один source-independent validator принимает Draft из Issue Form, CLI или будущего Tide. Валидный Draft остаётся read-only и не создаёт Contract, Task, escrow или debit.
- Все обычные mechanic terms сверяются с versioned rules/money functions: exact mode, slots/winners, payout vector, review fee и разрешённые additional review stages.
- Для Issue существует одна детерминированная Triage role/payment slot. Agent0 assignment и completion имеют versioned authority, exact revision/snapshot/hash/time и idempotency key; reviewer identity также проверяется по GitHub account и binding version.
- Бесплатная Triage не двигает деньги. Treasury Triage списывает только account `treasury`, платит reviewer после отдельного Agent0 completion и никогда не платит второй раз при новой body revision или reassignment.
- Route override требует точную более раннюю operator binding/version; author consent и Agent0 readiness закрепляют exact Issue/body/mechanic/runtime/Triage evidence.
- Ordinary Contract ID детерминирован по immutable Issue ID. Один атомарный переход списывает полный bank только у автора и создаёт Contract, Task, task escrow и debit; ошибка не создаёт ни одного из четырёх объектов.

## Проверка и review

- Focused Block 3: `44 passed`.
- Full vNext: `237 passed`, `18 skipped`.
- Full repository: `4522 passed`, `18 skipped`, `11 xfailed`.
- Packaging/runtime: `10 passed`; WEA invariant `19025 = 19025`; ledger schema, Ruff, Pyright и diff check — PASS.
- Первый независимый review нашёл шесть money/authority gaps; второй — caller-selected treasury source, отсутствующую reviewer authority, неверный порядок assignment/Triage, неидемпотентный старый completion replay и stale boundary docs; третий воспроизвёл caller-selected Triage escrow/account collision. PR review расширил ту же защиту на task escrow и зарегистрированные identity principals без balance row, затем закрыл forged restored Contract terms и completion-before-Triage chronology на уровне `IntakeState`. Все причины исправлены и получили регрессии; финальный повторный review не оставил actionable findings.

## Protected boundary

- Этот код не является live activation и не разрешает записи в GitHub или ledger.
- Future `direct-pr` должен принимать declarations только из accepted `GitHubEvent` revisions внутри confirmed boundary; historical Block 2 attestation не является fallback.
- Block 4 начинается только в новой immutable executor closure: опубликованный `v0_6_3` после merge не редактируется.
- OD-11, OD-14, OD-28 и OD-29 остаются открыты на прежних поздних gate.

## Next action

После merge Block 3 начать Block 4 в свежем worktree/branch от текущего `origin/main`: первый полный `direct-pr` path, точные `UserContentEdit` revisions и confirmed GitHub boundary. Не добавлять live writer, `ledger/vnext/`, migration/bootstrap или переключение v1.

```powershell
$env:PYTHONPATH='src'
python -m pytest tests/vnext/test_intake.py tests/vnext/test_contract_activation.py -q
python -m pytest tests/vnext -q
python -m pytest -q --tb=short
python scripts/check_invariant.py
python scripts/check_ledger_schema.py
python scripts/check_doc_sync.py
ruff check src/wea_vnext tests/vnext
pyright src/wea_vnext
python -m compileall -q src/wea_vnext tests/vnext
git diff --check
```
