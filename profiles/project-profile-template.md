---
vigers_profile: 2
profile_id: example
planning_anchors:
working_projection: optional
recommended_document_template: inherit
automation_timing: inherit
timing_model: inherit
progress_tracking: inherit
task_manager: inherit
timing_projection: inherit
timing_history: inherit
timing_calendar: inherit
deferred_state: inherit
state_projection: inherit
progress_projection: inherit
document_checks:
document_required_headings:
document_toc:
document_toc_heading:
document_toc_separators:
document_user_story_policy:
document_user_story_heading:
document_user_story_id_prefix:
document_user_story_title_separator:
document_user_story_role_label:
document_user_story_goal_label:
document_user_story_value_label:
document_traceability_policy:
document_traceability_heading:
document_traceability_link_style:
document_traceability_id_prefixes:
document_reader_projection:
document_public_id_prefixes:
document_internal_id_prefixes:
document_semantic_references:
document_traceability_density:
document_acceptance_focus:
document_dod_focus:
document_developer_checks:
document_prose_language:
document_user_journey_context:
document_ui_field_naming:
document_diagram_working_source:
document_diagram_qa_render:
document_diagram_qa_artifacts:
document_diagram_publication_gate:
document_diagram_publication_render:
document_diagram_publication_source:
---

# Профиль постановок проекта

Скопируй этот файл в `<project-root>/.vigers/profile.md`, замени `profile_id` на
стабильный публично-безопасный идентификатор и заполни секции ниже. Сам
проектный профиль не входит в общий пакет Vigers.

`recommended_document_template` управляет только стартовой рекомендацией и не
делает структуру обязательной:

- `inherit` — использовать переносимый шаблон пакета;
- `none` — не рекомендовать шаблон;
- `project:<relative/path.md>` — использовать проектный файл внутри корня.

Обязательные разделы и machine checks по-прежнему задаются отдельными
`document_*` полями и правилами проекта.

## Область

Какие постановки и артефакты покрывает профиль.

## Канонические источники

Источники в порядке приоритета и правила проверки изменчивых фактов.

## Планирование и внешние артефакты

Опиши:

- обязательные системы research и search order, включая критерий достаточности,
  freshness, отрицательный результат и недоступное покрытие;
- project-specific запреты на `fast-plan` и признаки, требующие нескольких
  source clusters; не делай full planning обязательным только из-за размера;
- поверхности поиска аналогичных кейсов для solution-boundary probe: backlog,
  код, процессы, прежние постановки и roadmap; источник, который проект считает
  достаточным доказательством срочного tactical exception;
- место passport, правило временного ID и обновления binding после появления
  tracker ID без создания второго passport;
- роль каждой системы: личный WIP, канонический tracker, описание/решение,
  локальный архив;
- project adapters: допустимые create/update/link actions, поля draft-объекта,
  authority source, `publish_gate`
  (`before_research|before_review|after_approval|none`) и обязательный read-back;
- политику `working_projection` во frontmatter:
  `required|optional|disabled`; для `required` объяви хотя бы один actionable
  target с `working_projection: true`, `publish_gate: after_approval` и
  обязательным read-back; target сразу фиксирует
  `evidence_kind: local_file|external_readback`;
- нужны ли profile-required пустые учётные anchors при появлении личной работы;
  перечисли системы, trigger, create-or-link правило без дублей, минимальные поля
  и запрети добавлять в anchor описание, статус, assignee, priority и commitment
  date; перечисли обязательные системы в frontmatter `planning_anchors` через
  запятую и отдельно укажи, может ли личный anchor предшествовать tracker/wiki;
- когда external artifact должен существовать до user review, а когда создаётся
  только после approval;
- где живёт ранняя человекочитаемая проекция постановки, когда она впервые
  создаётся, какие события обновляют её и как помечаются непроверенные части;
  отдельно выбери форму результата: project file, tracker description, wiki
  page/delta или согласованное сочетание targets. Не требуй параллельный
  локальный файл, если рабочей проекцией служит внешний target;
- вид read-back evidence: `local_file` только для точного `object_id` файла за
  пределами скрытого case либо `external_readback` с сохраняемым JSON receipt
  project adapter;
- маппинг этапов/checklists в личный task manager: details/done_when в task note,
  допустимая подробность пункта и subtask только для самостоятельного
  outcome/dependency/owner;
- при `timing_calendar: enabled` создай `.vigers/timing-calendar.json` schema 1:
  `calendar_id`, IANA `timezone`, непустые `working_windows`, опциональные
  `handoff_windows`, `holidays`, общий `production_calendar` страны и ручные
  `day_overrides`; materialize production calendar через Work Metrics с
  `isdayoff.ru` и независимой сверкой `xmlcalendar.ru`, персональные отпуска в
  него не включай; фактическая off-schedule активность всё равно
  считается, отсутствие событий вне окон не создаёт business-time и не требует
  ручной паузы, а прогноз перекладывает business duration на будущие окна;
- при `deferred_state: enabled` опиши trigger `defer/resume`. Если включён
  `state_projection: project`, задай для каждого внешнего provider точное
  deferred-состояние, read-back и восстановление предыдущего состояния. Не
  считай тег достаточным, если provider также имеет каноническую backlog/status
  поверхность;
- адаптер progress update: stable `Pxx-Cxx` → внешний item ID, операция установки
  галки, обязательный read-back checked state и правило идемпотентного повтора;
- правила replanning delta: как во время анализа немедленно остановить неверный
  plan, сохранить выполненные галки, явно пометить удалённые/заменённые пункты и
  опубликовать новую revision без потери истории; локальную некритичную delta
  принимает координатор, критичная требует user approval;
- запрещённые обратные ссылки, личные пути и поля, которые нельзя публиковать в
  командные системы;
- действия, запрещённые до approval: workflow status, assignee, priority,
  commitment dates, реализация и delivery mutations.

## Системный анализ

Проектные ограничения системного анализа и границы business-context. Укажи
локальные признаки подтверждённого общего класса, допустимые extension seams и
необратимые решения. Не переопределяй три общих горизонта проекта ради
терминологии проекта. Для общего `diagram_gate` зафиксируй проектные признаки
сложности, допустимые нотации и источники semantic IDs; не вводи правило
«диаграмма по количеству страниц».

## Архитектурный гейт

Дополнительные проектные триггеры и архитектурные источники.

## Режимы и разбиение

Когда использовать `compact` и `block`; локальные high-assurance risk triggers,
допустимая гранулярность tracking/projection sync, рекомендуемые семантические
блоки, зависимости, правила kernel, рабочий `case-root` и маппинг блоков в
финальный проектный шаблон. Runtime `cases/` не должен попадать в общий пакет
скилла.

Назови стабильные project-trigger IDs, которые оркестратор передаёт в
`suggest-mode --project-trigger`, и для каждого опиши наблюдаемое условие. Сам
профиль остаётся смысловым источником; общий скрипт не содержит знания проекта.

Если проекту нужны именованные review lenses, объяви только aliases вида
`stable-id@version → существующие contract inputs/surfaces`. Lens не создаёт
нового reviewer или gate; версия меняется при смысловом изменении набора правил.

## Артефакт и author gates

Шаблон результата и обязательный порядок авторских проверок.

Если формат локального Markdown обязателен, объяви machine contract во
frontmatter: `document_checks: draft, working_projection`, перечень
`document_required_headings`, `document_toc: obsidian-h2-exact`, название
раздела и политику разделителей. Если проект требует единую форму User Story,
добавь policy `numbered-role-goal-value`, H2, ID prefix, разделитель заголовка и
локальные метки role/goal/value. Общий core проверяет объявленную форму, но не
знает язык и терминологию проекта. Не заполняй часть полей: либо объяви контракт
целиком, либо оставь соответствующий набор `document_*` пустым.

Если таблица трассировки должна быть навигационной, добавь policy
`semantic-id-links`, H2 трассировки, style `obsidian-heading-exact` и полный
список допустимых semantic ID prefixes. Тогда каждый ID в разделе обязан быть
отдельной ссылкой на один точный существующий heading. Сокращённые диапазоны и
plain-text IDs machine check отклоняет. Для Obsidian-таблиц project profile
должен отдельно требовать экранированный alias separator `\|`.

Если итоговый документ не должен публиковать служебную модель анализа, объяви
читательскую проекцию полностью:

- `document_reader_projection: required`;
- публичные и внутренние `document_*_id_prefixes` без пересечений;
- `document_semantic_references: exact-heading-links` для ссылок на публичные ID
  во всём документе, а не только в трассировке;
- `document_traceability_density: direct-edges`;
- `document_acceptance_focus: observable-behavior`;
- `document_dod_focus: acceptance-readiness`;
- `document_developer_checks: omit-unless-normative`;
- язык обычной прозы в `document_prose_language`, например `ru`.

Общая бизнес-цель остаётся обязательным содержанием постановки. Если проект
использует semantic IDs и навигационную трассировку, включи `GOAL` в публичные,
а не во внутренние prefixes и свяжи с User Story прямыми ссылками.

Тогда machine check отклоняет внутренние ID, сжатые диапазоны, plain-text и
dangling semantic references во всей читательской проекции. Смысловые правила
AC/DoD, прямой трассировки, языка и ресурсной дисциплины проверяют editor и
reviewer по `references/reader-projection-contract.md`.

Если постановка содержит пользовательские UI-сценарии, объяви оба правила:

- `document_user_journey_context: screen-on-entry-and-evidenced-navigation`;
- `document_ui_field_naming: visible-label-then-technical-id`.

Первое действие на интерфейсе тогда называет текущий экран. Если до него
сценарий описывает навигацию, укажи подтверждённый видимый путь. Каждый переход
на другой экран, вкладку, окно или диалог называет новую поверхность. Пока
сценарий идёт на том же экране, полный путь не повторяется. Значимое поле при первом
упоминании оформляется как видимое пользователю название и технический ID в
скобках. Если source не подтверждает экран, маршрут, подпись или ID, оставь gap,
а не догадку. Не добавляй фиктивный экран в API-, batch- или system-only
сценарий и не смешивай UI-навигацию с URL/API path. Если сценарий начинается с
уже открытого экрана, достаточно назвать его: маршрут задним числом не
реконструируется.

Если рабочая проекция и публикационный target по-разному обрабатывают диаграммы,
объяви полный `document_diagram_*` lifecycle:

- `working_source`: `inline-mermaid|inline-plantuml|external-source`;
- `qa_render`: `target-native|ephemeral-render|target-native-with-ephemeral-fallback`;
- `qa_artifacts`: `none|ephemeral`;
- `publication_gate`: `none|explicit-publication`;
- `publication_render`: `none|target-native|png|svg`;
- `publication_source`: `none|inline|attachment`.

При `explicit-publication` render и source создаются только после достижения
явного publication gate. `ephemeral` разрешает временный QA-render вне
публикуемого/коммитимого результата, но не постоянный файл «на будущее».
Частично заполненный или внутренне противоречивый lifecycle machine check
отклоняет.

Опиши отдельный `project-conformance`: применимые API/HTTP, identifier/casing,
терминологию, frontmatter, шаблоны, ссылки, имена файлов, допустимые форматы
исходников и render диаграмм, целевую ширину, место хранения и
legacy-исключения. Required-диаграмма должна пройти semantic check и визуальный
read-back фактического render; нечитаемую схему требуется декомпозировать, а не
уменьшать до формального наличия.

## Жизненный цикл и публикация

Канонический путь, условия внешних записей и обязательный read-back.
Отдельно зафиксируй границу `specification_ready` / `delivery_complete`,
evidence для terminal status и ручные handoff-пункты с
`completion_owner: user`.
