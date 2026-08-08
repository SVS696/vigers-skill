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
      "source_refs": ["SRC-12"]
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

## Границы контекста

Роль получает kernel, evidence, карточку целевого блока и только результаты
его зависимостей. Остальные блоки, интегрированный draft, авторские рассуждения
и прошлые findings не входят в локальный контекст без доказанной необходимости.
