# Контракт семантического блока

Блок — независимо анализируемая часть смысла, а не обязательный раздел
финального документа. Примеры: сценарный контур, набор бизнес-правил, модель
состояний, публичный контракт, ошибки/восстановление, качества, AC/DoD.

## Карточка блока

Карточка хранится в `ledger.json` и содержит:

- стабильный `id` формата `B01`;
- один `kind` и понятный `title`;
- `depends_on` как DAG;
- состояние и kernel snapshot;
- пути к analysis, semantic index и review.

Хороший блок отвечает на 1–3 связанных вопроса, имеет одного смыслового
владельца и может быть проверен без чтения всего черновика.

## Analysis artifact

`blocks/Bxx.md` содержит:

```markdown
# Bxx — Название

## Block contract
Цель, входит/не входит, входы и ожидаемый результат.

## Analysis
Факты, сценарии, правила, данные, интерфейсы и требования — только применимое.

## Assumptions and open questions
Явные допущения, пробелы и владелец ответа.
```

## Semantic index

`blocks/Bxx.index.json` — нормализованная IR для сквозной проверки:

```json
{
  "schema": 2,
  "block_id": "B01",
  "kernel_revision": 3,
  "definitions": [
    {
      "id": "SCN-B01-001",
      "kind": "scenario",
      "summary": "Пользователь создаёт объект",
      "source_refs": ["SRC-12"]
    },
    {
      "id": "REQ-B01-001",
      "kind": "requirement",
      "summary": "Система сохраняет объект атомарно",
      "source_refs": ["SRC-12"]
    },
    {
      "id": "AC-B01-001",
      "kind": "acceptance",
      "summary": "При успешном запросе объект доступен для чтения",
      "source_refs": ["SRC-12"],
      "verification_context": {
        "kind": "ui-scenario",
        "scenario_refs": ["SCN-B01-001"],
        "surface": "Экран создания объекта"
      }
    }
  ],
  "trace": [
    {"from": "REQ-B01-001", "to": ["SCN-B01-001"]},
    {"from": "AC-B01-001", "to": ["REQ-B01-001"]}
  ]
}
```

Допустимые `kind` и префиксы:

| Kind | Prefix | Kind | Prefix |
|---|---|---|---|
| goal | GOAL | actor | ACT |
| scenario | SCN | rule | RULE |
| data | DATA | state | STATE |
| interface | IF | quality | QUAL |
| requirement | REQ | acceptance | AC |
| dod | DOD | assumption | ASM |
| question | Q | decision | DEC |
| constraint | CON | | |

Каждый ID принадлежит одному блоку: `<PREFIX>-Bxx-<NNN>`. Направление trace:
`from` уточняет, проверяет или выводится из `to`. Поэтому `AC → REQ`, а
`REQ → SCN|RULE|GOAL|...`.

Для новой `acceptance` definition обязателен `verification_context`. Он хранит
`kind: ui-scenario|api|batch|system`, точные `scenario_refs` и подтверждённую
проверяемую поверхность. Для UI это экран/точка входа; видимый маршрут остаётся
в связанном сценарии и не копируется в каждое AC. Если сценария нет, контекст
может хранить минимальный подтверждённый путь. Для API/batch/system указывается
операция, endpoint, событие, job или файл без фиктивного экрана. Поле не заменяет
trace `AC → REQ` и остаётся во внутренней IR; редактор проецирует его ссылкой или
коротким reader-facing контекстом.

Semantic index является внутренней богатой моделью. При `block-render` редактор
проецирует только prefixes, объявленные profile публичными, и только смысл,
который нужен читателю. Integrator не копирует весь `trace` в финальную таблицу:
он оставляет прямые reader-facing edges по
`references/reader-projection-contract.md`. Внутренний ID, отсутствующий в
постановке по profile, не считается потерянным при integration.

## Локальное ревью

`reviews/Bxx.md` содержит findings по handoff-контракту или явный `PASS` с
перечнем проверенных критериев. Отчёт завершает counts
`reported_blocker/reported_major/reported_minor`, `research_reopen` и
`gate_recommendation`. После disposition координатор отдельно фиксирует open
counts и решение гейта. Review не переписывает block artifact и не содержит
скрытых новых требований.

Блок переходит в `reviewed`, когда открытых принятых `blocker/major` нет.
Residual minor допустимы; для minor-only разрешён максимум один пакетный
polish-pass на текущий gate. Повторное review после исправления должно быть
точечным. Новый research открывается только для существенного finding с полями
из `{baseDir}/references/convergence-contract.md`.

Карточка блока может содержать `risk_surfaces`. Тогда до authoring требуется
case-level risk preflight, а initial/full-block review возвращает completed
`review_agent_run`, `finding_batch_complete: true` и ровно одну строку
`risk_surface: <id>=pass|not-applicable|<finding-id>` для каждой поверхности.
Targeted remediation эту матрицу не пересматривает.

Каждый завершённый локальный review сохраняется отдельной immutable revision.
При accepted `blocker|major` координатор открывает `begin-remediation` с finding
ID, evidence и затронутыми semantic IDs. Контекст повторного reviewer включает
baseline block/index, finding evidence и ровно одну закреплённую revision
предыдущего покрытия. Для `targeted-remediation` отчёт возвращает
`review_scope`, точный `verified_findings` и `coverage_reused`; изменение
необъявленного semantic ID блокируется машиной. Для смысловой переписи блока
используется `full-block`, где `coverage_reused: none` и выполняется полный
локальный review. Для `batched-v2` все accepted blocker/major одного gate входят
в один `--batch-complete`; на kernel epoch разрешено максимум два batches. Дальше требуется
root-cause kernel change либо `user-decision`, а не новый finding-by-finding
проход.

## Границы контекста

Роль получает kernel, evidence, карточку целевого блока и только результаты
его зависимостей. Остальные блоки, интегрированный draft, авторские рассуждения
и прошлые findings не входят в локальный контекст без доказанной необходимости.
