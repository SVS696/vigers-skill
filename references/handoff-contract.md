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
    "content_sha256": "...",
    "role_context_path": "planning-role-context.json",
    "role_context_fingerprint": "..."
  },
  "mode_decision": {"path": "mode-decision.json", "fingerprint": "..."},
  "method_context": {
    "metadata_path": "method-context.json",
    "content_path": "method-context.md",
    "fingerprint": "...",
    "content_sha256": "..."
  },
  "project_conformance_contract": {
    "path": "project-conformance-contract.json",
    "sha256": "..."
  },
  "kernel": {"path": "kernel.md", "revision": 1, "sha256": "..."},
  "artifacts": {
    "automation_timing": "automation-timing.json",
    "planning_role_context": "planning-role-context.json",
    "working_projection": "working-projection.json"
  },
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
`automation-timing.json` хранит отдельный runtime ledger approved planning stages
и не передаётся ролям как источник требований.

`project-conformance-contract.json` — immutable snapshot machine-readable
`document_*` правил выбранного profile. Если contract объявлен, перед
`project_conformance: pass` core проверяет выбранные `draft`/`working_projection`,
а subject hash связывает gate с их фактическим содержимым. Старый case без
snapshot не ужесточается задним числом.
После document-contract failure ограниченная правка, projection read-back и
machine recheck предшествуют новому project-conformance review. Evidence report
обязан быть создан после актуального draft/projection update; прежний report
нельзя скопировать в новую revision как будто он проверял исправленный subject.

`working-projection.json` связывает case с видимым человеку растущим черновиком.
Он хранит policy profile, targets из approved artifact plan и append-only
read-back updates. Каждый target содержит неизменяемый
`evidence_kind: local_file|external_readback`. Update использует только semantic source `Bxx`, `draft` или
`integration` и содержит `source_sha256`, `content_sha256`, `evidence_kind`,
`evidence_ref`, `evidence_sha256` и `read_back_at`. Runtime `draft.md` и block artifacts остаются машинными
рабочими материалами и не доказывают, что пользователь видит результат.
Рабочая проекция явно отличена от финальной публикации; непроверенные разделы
не превращаются в утверждённые требования только потому, что записаны наружу.
Перед `author_passes` runtime сверяет хеш текущего `draft.md` с последним
`draft` update в compact-mode или `integration` update в block-mode.

`evidence_kind=local_file` указывает на реально прочитанный файл из bound project
root. Его путь точно совпадает с `object_id` target и не может находиться внутри
скрытого runtime case; текущий SHA-256 обязан совпадать с последним
`content_sha256` target. `evidence_kind=external_readback` указывает на сохранённый
в case JSON receipt проектного адаптера. Receipt содержит `schema=1`,
`kind=external_readback`, adapter, target/system/object identity, `read_back_at`,
`content_sha256` нормализованного прочитанного текста и
`response_fingerprint`. Один URL или заявленный хеш без receipt не являются
read-back evidence.

`planning-role-context.json` — производный bounded input для исполнительных
ролей. Он содержит planning linkage, preliminary requirements, preliminary
`solution_boundary_probe` и контракт working projection, но машинно
исключает `automation_plan`, ETA и runtime facts. Raw `planning-handoff.json`
доступен оркестратору для валидации, но не входит в `case_pipeline.py context`.
Аналогично `role-manifest.json` проецирует только mode/profile/method/kernel,
семантические paths и gates; coordinator `manifest.json`, timing path, event log
и fingerprint raw handoff ролям не передаются.

## Planning handoff

`planning-handoff.json/md` — immutable approved snapshot, а не новый источник
требований. Он содержит цель и scope planning, research basis/gaps, зависимые
этапы, passport/external bindings и открытые риски. `case_pipeline.py init`
проверяет profile, approval revision, fingerprint и content hash. Для plan schema
2+ handoff также содержит immutable `automation_plan`; init создаёт из него ledger
и связывает с теми же planning revision и passport. Schema 3 дополнительно
передаёт `preliminary_requirements` с `PUS-*` и `PDOD-*` как planning-гипотезы.
Schema 4 добавляет `solution_boundary_probe`: предварительный поиск аналогов и
кандидат горизонта. Он требует disposition в полном анализе, но не задаёт scope.

Системный аналитик использует handoff как bounded intake и всё равно строит
модель требований. Для каждого `PUS-*`/`PDOD-*` он фиксирует disposition
`confirmed|changed|split|rejected` и итоговую трассировку; полный анализ может
добавить новые истории и критерии. Редактор не превращает checklist или
planning-гипотезу в требование автоматически. Reviewer проверяет, что итоговая
постановка не потеряла approved scope и явно объясняет обоснованные отклонения.
Как только во время полного анализа требуется изменить сам approved plan,
аналитик останавливает текущий проход и возвращает `status: replan` с
`planning_delta`; координатор сразу открывает новую revision, не переписывая
handoff. Локальная некритичная delta может быть принята координатором, material
delta требует решения пользователя.

## Общий envelope результата роли

Каждая роль возвращает один верхнеуровневый envelope:

```yaml
status: ok | replan | gap | input-error
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

`replan` разрешён только системному аналитику, который во время прохода доказал,
что approved plan больше нельзя безопасно исполнять. Payload содержит только
`planning_delta`, evidence refs, impact `local|material` и границу выполненной
проверки; незавершённая модель требований не принимается как результат.

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
## Разрешение planning-гипотез PUS/PDOD
## Граница решения и горизонт
## Выбор моделей и диаграмм
## Архитектурное влияние
## Предположения
## Открытые вопросы
## Трассировка
```

Business context обязательно разделяет `подтверждено`, `предположение`,
`неизвестно`, `владелец ответа`. Аналитик не утверждает решение за владельца
бизнес-процесса.

Раздел границы следует `references/solution-boundary-contract.md` и содержит
наблюдаемый кейс, корневую способность, инварианты, подтверждённые и
предполагаемые варианты, current scope, seams, deferred, expansion triggers и
disposition planning probe. Координатор принимает финальный machine block в
существующий `decisions.md`; отдельный boundary artifact не создаётся.

Раздел выбора моделей содержит `diagram_gate` из
`references/diagram-contract.md`: для каждой required surface — вопрос,
representation, source IDs, decomposition и placement; для `not-required` —
проверяемую причину. Это часть модели требований, а не отдельный
planning/runtime артефакт.

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
- подтверждённый `solution_horizon`, оценку рисков particular-case и
  speculative-generalization, обязательные seams и evidence выбора.
- уточнения diagram surfaces для границ, взаимодействий и данных, если
  архитектурное решение делает прежний diagram decision неполным. Архитектор не
  рисует финальный документ и не добавляет новый смысл через схему.

В режиме `conformance` архитектор не продолжает собственное прежнее
рассуждение. Он получает чистый набор источников и готовый черновик и возвращает
findings по той же классификации.

## Черновик

Редактор возвращает готовый текст по шаблону профиля и отдельный список:

- использованные входные артефакты;
- неразрешённые placeholder-ы;
- места, где проектный шаблон не применён, и причина;
- подтверждение, что новые требования и решения не добавлялись.
- матрицу `diagram question → source_ids → section/render/source` либо
  `diagram_gate: not-required` из утверждённой модели.

В режиме `block-render` результат ограничен одним block artifact. В режиме
`integrate` редактор возвращает полный draft и матрицу `block_id → место в
документе`; semantic IDs не создаются и не исчезают.

## Review findings

Каждое замечание имеет форму:

```yaml
id: REV-001
severity: blocker | major | minor
category: logic | scope | traceability | testability | diagram | project-rule | architecture | solution-boundary
solution_boundary_smell: particular-case | speculative-generalization | null
location: <section-or-anchor>
finding: <what-is-wrong>
evidence: <source-or-internal-contradiction>
impact: <practical-consequence>
proposed_change: <minimal-correction>
remediation: edit | targeted-research | user-decision
confidence: high | medium | low
```

Вкусовые пожелания без последствия и доказательства не являются finding.
`targeted-research` допустим только для `blocker|major` и дополняется
`research_question`, `missing_evidence`, `target_sources` и `stop_condition` по
`references/convergence-contract.md`. `minor` не переоткрывает research.

Режимы reviewer:

- `block` — локальная логика и полнота одного блока;
- `integration` — конфликты и разрывы между блоками после сборки;
- `global` — итоговая цель, scope, трассировка, тестируемость и проектные правила.
- `project-conformance` — только применимые локальные соглашения и форматы.

## Decision log

Координатор для каждого finding фиксирует `accepted | rejected | user-decision`
и основание. Для accepted finding добавляет resolution `open | corrected |
residual`. `residual` допустим только для `minor` и не блокирует gate. Отклонённое
замечание не записывается в историю изменений постановки, если проектный профиль прямо
не требует обратного.

Каждый review report завершается counts
`reported_blocker/reported_major/reported_minor`, `research_reopen: no|targeted`
и `gate_recommendation: pass|revise|user-decision`. После disposition
координатор отдельно записывает `open_blocker/open_major/open_minor` и
`gate_decision`. `pass` требует нулевые open counts только для принятых
`blocker/major`; residual minor не запускают новый полный цикл.
Evidence integration/global/project/architecture review при каждом `pass`
копируется в новую immutable revision `reviews/history/*-rNNN`; рабочий файл
review можно обновлять, но прежнее доказательство не перезаписывается.

## Handoff во внешнюю поставку

Vigers не реализует и не принимает поставку. Для отдельного delivery-процесса
координатор может сформировать read-only handoff:

- `case_id`, profile и точный kernel revision/hash;
- hash утверждённого draft;
- выбранные `REQ/AC` и их semantic indexes;
- impact map по компонентам без назначения реализации по догадке;
- architecture/project-conformance constraints;
- принятый `solution_horizon`, `current_scope`, `extension_seams`,
  `deferred_variants` и `expansion_triggers` без права delivery-роли расширять
  их самостоятельно;
- матрицу `REQ → AC → required evidence`;
- открытые решения, gaps и остаточный риск.

Этот handoff не разрешает правки кода, тестов, merge, deploy или изменение
внешних статусов. Полномочия задаёт отдельный delivery-skill и проектный профиль.
Завершённый Vigers case подтверждает `specification_ready`, а не
`delivery_complete`; закрытие implementation task или incident требует отдельного
delivery evidence и lifecycle gate проекта.
