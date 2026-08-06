# Контракт передачи между ролями

Роли не обмениваются свободным пересказом диалога. Координатор формирует case
package и передаёт каждой роли только перечисленные входы.

## Case manifest v2

```json
{
  "schema": 2,
  "case_id": "stable-id",
  "mode": "compact | block",
  "intent": "create | update | review | decompose | architecture",
  "profile_id": "generic-or-project-profile-id",
  "project_root": null,
  "route_id": "core",
  "planning_handoff": {
    "metadata_path": "planning-handoff.json",
    "content_path": "planning-handoff.md",
    "planning_case_id": "stable-planning-id",
    "planning_revision": 2,
    "fingerprint": "...",
    "content_sha256": "..."
  },
  "mode_decision": {"path": "mode-decision.json", "fingerprint": "..."},
  "method_context": {
    "metadata_path": "method-context.json",
    "content_path": "method-context.md",
    "fingerprint": "...",
    "content_sha256": "..."
  },
  "kernel": {"path": "kernel.md", "revision": 1, "sha256": "..."},
  "artifacts": {},
  "gates": {},
  "events": []
}
```

`planning_handoff` обязателен для нового non-review case; review готового
артефакта и старый runtime state могут содержать `null`. `mode_decision` и
`method_context` могут быть `null` только у старого case.
Методический context материализуется до `init`, проверяется по канонической
выжимке и затем используется как закреплённый snapshot: изменение любого из
двух файлов ломает валидацию. `manifest.json` не содержит пароли, токены,
cookies, приватные ключи и дампы БД. В block-mode `ledger.json` хранит DAG и
состояния блоков; формат и переходы задаёт `case_pipeline.py`.

## Planning handoff

`planning-handoff.json/md` — immutable approved snapshot, а не новый источник
требований. Он содержит цель и scope planning, research basis/gaps, зависимые
этапы, passport/external bindings и открытые риски. `case_pipeline.py init`
проверяет profile, approval revision, fingerprint и content hash.

Системный аналитик использует handoff как bounded intake и всё равно строит
модель требований. Редактор не превращает checklist в требования автоматически.
Reviewer проверяет, что итоговая постановка не потеряла approved scope и явно
объясняет обоснованные отклонения.

## Общий envelope результата роли

Каждая роль возвращает один верхнеуровневый envelope:

```yaml
status: ok | gap | input-error
mode: <assigned-mode>
target: <assigned-target>
reason: <required-for-gap-or-input-error>
missing_inputs: []
evidence_refs: []
payload: <required-for-ok>
```

`ok` требует полный payload выбранного контракта. `gap` означает, что доступных
источников недостаточно для честного результата. `input-error` означает неверный
mode/target, отсутствующий обязательный файл, stale fingerprint или нарушение
границ assignment. Пустой ответ, refusal и оборванный output не являются `ok`:
координатор классифицирует их как `input-error` либо `gap` и не сохраняет
частичный payload как результат роли.

## Kernel

`kernel.md` — минимальный общий контекст всех ролей:

- цель и границы;
- общий словарь;
- инварианты и глобальные ограничения;
- уже принятые решения;
- решения, которые ещё открыты.

Kernel не содержит подробный анализ каждого блока. Изменение kernel повышает
revision и делает затронутые результаты stale.

## Intake и evidence pack

Координатор фиксирует:

- исходный запрос без смыслового улучшения;
- подтверждённые источники и дату их чтения;
- актуальность и приоритет каждого источника;
- факты отдельно от сообщений, предположений и выводов;
- недоступные источники и пробелы покрытия;
- существующие решения пользователя, которые нельзя переоткрывать молча.

`method-context.md/json` входят в обязательный вход системного аналитика и
логического reviewer. Они не являются evidence задачи и не передаются
редактору как источник нового смысла. Координатор получает точный список файлов
для block-role через `case_pipeline.py context`, а не собирает его по памяти.

## Модель требований

Системный аналитик возвращает:

```markdown
# Модель требований

## Проблема и цель
## Пользователи и заинтересованные стороны
## Подтверждённые факты
## Business context
## Входит / не входит
## Сценарии
## Бизнес-правила
## Данные и состояния
## Интерфейсы и интеграции
## Атрибуты качества и ограничения
## Ошибки и восстановление
## Acceptance criteria
## Definition of Done
## Архитектурное влияние
## Предположения
## Открытые вопросы
## Трассировка
```

Business context обязательно разделяет `подтверждено`, `предположение`,
`неизвестно`, `владелец ответа`. Аналитик не утверждает решение за владельца
бизнес-процесса.

В block-mode аналитик возвращает только модель целевого блока и отдельный
semantic index по `{baseDir}/references/block-contract.md`. Общие факты
предлагаются как изменение kernel, но не меняются ролью самостоятельно.

## Архитектурное решение

Архитектор в режиме `design` возвращает:

- состояние гейта и подтверждённые триггеры;
- до трёх существенно разных вариантов, если выбор ещё открыт;
- рекомендуемое решение и критерии выбора;
- границы компонентов и владение данными;
- контракты, согласованность, качества, миграцию и откат;
- соответствие текущему канону и ссылки на ADR/правила;
- `conform | decision-required | conflict`;
- обязательные ограничения для редактора;
- вопросы, которые меняют решение.

В режиме `conformance` архитектор не продолжает собственное прежнее
рассуждение. Он получает чистый набор источников и готовый черновик и возвращает
findings по той же классификации.

## Черновик

Редактор возвращает готовый текст по шаблону профиля и отдельный список:

- использованные входные артефакты;
- неразрешённые placeholder-ы;
- места, где проектный шаблон не применён, и причина;
- подтверждение, что новые требования и решения не добавлялись.

В режиме `block-render` результат ограничен одним block artifact. В режиме
`integrate` редактор возвращает полный draft и матрицу `block_id → место в
документе`; semantic IDs не создаются и не исчезают.

## Review findings

Каждое замечание имеет форму:

```yaml
id: REV-001
severity: blocker | major | minor
category: logic | scope | traceability | testability | project-rule | architecture
location: <section-or-anchor>
finding: <what-is-wrong>
evidence: <source-or-internal-contradiction>
impact: <practical-consequence>
proposed_change: <minimal-correction>
confidence: high | medium | low
```

Вкусовые пожелания без последствия и доказательства не являются finding.

Режимы reviewer:

- `block` — локальная логика и полнота одного блока;
- `integration` — конфликты и разрывы между блоками после сборки;
- `global` — итоговая цель, scope, трассировка, тестируемость и проектные правила.

## Decision log

Координатор для каждого finding фиксирует `accepted | rejected | user-decision`
и основание. Отклонённое замечание не записывается в историю изменений
постановки, если проектный профиль прямо не требует обратного.

## Handoff во внешнюю поставку

Vigers не реализует и не принимает поставку. Для отдельного delivery-процесса
координатор может сформировать read-only handoff:

- `case_id`, profile и точный kernel revision/hash;
- hash утверждённого draft;
- выбранные `REQ/AC` и их semantic indexes;
- impact map по компонентам без назначения реализации по догадке;
- architecture/project-conformance constraints;
- матрицу `REQ → AC → required evidence`;
- открытые решения, gaps и остаточный риск.

Этот handoff не разрешает правки кода, тестов, merge, deploy или изменение
внешних статусов. Полномочия задаёт отдельный delivery-skill и проектный профиль.
