---
vigers_profile: 2
profile_id: example
planning_anchors:
working_projection: optional
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
---

# Профиль постановок проекта

Скопируй этот файл в `<project-root>/.vigers/profile.md`, замени `profile_id` на
стабильный публично-безопасный идентификатор и заполни секции ниже. Сам
проектный профиль не входит в общий пакет Vigers.

## Область

Какие постановки и артефакты покрывает профиль.

## Канонические источники

Источники в порядке приоритета и правила проверки изменчивых фактов.

## Планирование и внешние артефакты

Опиши:

- обязательные системы research и search order, включая критерий достаточности,
  freshness, отрицательный результат и недоступное покрытие;
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

Когда использовать `compact` и `block`; рекомендуемые семантические блоки,
зависимости, правила kernel, рабочий `case-root` и маппинг блоков в финальный
проектный шаблон. Runtime `cases/` не должен попадать в общий пакет скилла.

Назови стабильные project-trigger IDs, которые оркестратор передаёт в
`suggest-mode --project-trigger`, и для каждого опиши наблюдаемое условие. Сам
профиль остаётся смысловым источником; общий скрипт не содержит знания проекта.

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
