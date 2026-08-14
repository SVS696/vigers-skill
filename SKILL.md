---
name: vigers
description: "Оркестрирует предварительное исследование источников, согласуемое планирование и независимых агентов для анализа, проектирования, поблочной подготовки, интеграции и ревью постановок, требований, технических заданий, acceptance criteria и Definition of Done. Применяется к запросам «исследуй и спланируй задачу», «напиши постановку», «проверь требования», «проработай решение», «декомпозируй задачу», «сформируй AC/DoD», включая большие документы, которые нужно обрабатывать итерационно без потери контекста. Не применяется для чистого code review, реализации утвержденной задачи и изменения внешнего трекера без явной просьбы."
---

# Вигерс: мультиагентная инженерия постановок

Оркестрируй общий набор изолированных ролей поверх проектного профиля. Не смешивай
анализ, архитектурное решение, редактуру и независимое ревью в одном контексте.

## Основные принципы

1. **Один канон, локальные профили.** Метод и роли общие; конкретный проект
   задаёт источники истины, шаблоны, архитектурные ограничения, контрольные
   проходы и правила публикации в собственном `.vigers/profile.md`. Проектные
   профили не входят в общий распространяемый пакет.
2. **Артефакты вместо пересказа чата.** Роли обмениваются через case package по
   `{baseDir}/references/handoff-contract.md`. `kernel.md` удерживает общие
   инварианты, `method-context.md/json` фиксируют выбранную выжимку метода, а
   `manifest.json` и `ledger.json` — состояние и зависимости.
3. **Свежий ограниченный контекст.** Каждый вызов получает `contract_inputs` и
   нужные артефакты. Не передавай историю автора, нерелевантные блоки и findings.
4. **Архитектор вызывается по влиянию.** Архитектурная роль существует всегда,
   но режимы `design` и `conformance` запускаются только при срабатывании гейта.
5. **Внешние изменения отдельно.** Подготовка текста не разрешает публиковать
   его, менять внешние трекеры, базы знаний или статусы без явной просьбы.
6. **Масштаб не равен риску.** `compact|block` управляет контекстом, а
   `lite|standard|high` — глубиной review. В standard один `final` reviewer
   объединяет integration/global и применимые project surfaces; high сохраняет
   отдельные проходы по `{baseDir}/references/execution-policy.md`.
7. **Планирование начинается с исследования.** Декомпозиция без проверки
   проектных источников создаёт ложную определённость. Planning-case сначала
   фиксирует search coverage, противоречия и gaps, затем строит зависимые этапы,
   внешние draft-артефакты и один user-review gate для первоначального plan
   snapshot. Отдельные пункты принятого плана повторно не согласуются.
8. **Tracking выбирает человек или проект.** Portable default `fine` сохраняет
   видимый прогресс и machine barriers; `off|milestones` требуют явной настройки.
   ETA не передаётся ролям и не влияет на качество или scope.
   Внешняя запись, publication и user-owned handoff всегда требуют read-back.
9. **Качество имеет критерий достаточности.** `blocker` и `major` закрываются
    обязательно через bounded remediation: finding, baseline, semantic IDs и
    прежнее покрытие сохраняются, а re-review проверяет delta, не весь блок заново.
    `minor` не блокируют следующий этап. Новый research после coverage
    gate разрешён только для доказанной существенной evidence-дыры. Minor-only polish
    выполняется не более одного раза на review gate; затем остаток фиксируется и
    pipeline идёт дальше по `{baseDir}/references/convergence-contract.md`.
10. **Скрытый case не заменяет рабочий документ.** Создай объявленную видимую
    проекцию до анализа. В `milestones` обновляй её полным draft на смысловых
    вехах, в `per-block` — после каждого reviewed блока. Это не публикация.
11. **Project-conformance имеет машинный барьер.** Если profile объявляет
    `document_*` contract, core проверяет закреплённый draft и локальную рабочую
    проекцию до `pass`; текстовый verdict ревьюера не перекрывает ошибку
    обязательного раздела, оглавления или якоря. После исправления и нового
    read-back нужен свежий pass только после semantic/project-contract delta.
    Editorial delta закрывается machine check и явным `record-change`.
12. **Готовая постановка не равна готовой поставке.** Закрытие постановочных
    gates означает только готовность specification artifact. Внешние terminal
    statuses, закрытие delivery task или инцидента разрешены только по lifecycle
    policy проекта и подтверждённому delivery evidence; публикация текста сама
    по себе таким evidence не является.
13. **Граница решения защищена с двух сторон.** Частный запрос — наблюдаемый
    экземпляр потребности, а не автоматически весь класс задач. Анализируй
    системно, реализуй подтверждённый scope и сохраняй обоснованный путь
    расширения, но не строй механизм «на будущее» без evidence. Выбирай
    `tactical|bounded-systemic|generalized-capability` строго по
    `{baseDir}/references/solution-boundary-contract.md`; финальное решение живёт
    в существующем `decisions.md`, а не в новом артефакте.
14. **Человекочитаемая User Story не подменяется системной моделью.** Если
    profile объявляет `user_story` contract, каждая история следует одной
    project-owned форме role-goal-value. `RULE/DATA/IF/AC/DOD` остаются
    отдельными трассируемыми слоями; таблицы `ACT` и списки `SCN` не заменяют US.
15. **Трассировка должна навигировать, а не только перечислять ID.** Если
    profile объявляет `traceability` contract, каждый semantic ID в разделе
    трассировки является отдельной внутренней ссылкой на точный существующий
    heading. Сжатые диапазоны и plain-text ID не проходят machine check.
16. **Сложность должна получать подходящее представление.** Для состояний,
    ветвящейся логики, взаимодействий, границ и неочевидных связей данных пройди
    diagram gate по `{baseDir}/references/diagram-contract.md`. Диаграмма
    отвечает на один вопрос, трассируется к semantic IDs и проходит render QA;
    перегруженная схема декомпозируется, а не уменьшается до нечитаемого размера.
    Рабочий source, QA-render и publication artifacts следуют profile lifecycle; файлы будущей публикации не создаются до её явного gate.
17. **Публикуй читательскую проекцию, а не внутреннюю модель.** Служебные ID,
    findings, gates и reasoning остаются в case package. AC описывают
    наблюдаемую приёмку и прямо ведут к сценарию/точке входа проверки, DoD — готовность результата к ней, а developer
    self-check не публикуется без нормативной причины. Semantic references во
    всём документе разрешаются в точные headings; трассировка хранит прямые
    связи. Сначала запускай machine check, затем только необходимые дорогие
    проходы по `{baseDir}/references/reader-projection-contract.md`.
    Общая бизнес-цель остаётся обязательной; объявленный profile публичный
    `GOAL-*` не является служебным ID и сохраняется как вершина трассировки.

## Когда применять

- Из идеи, переписки, тикета или черновика нужна проверяемая постановка.
- Требуется независимо проанализировать, оформить и проверить требования.
- Нужно подготовить решение и сверить его с архитектурой проекта.
- Нужно обновить постановку без потери трассировки и проектных правил.
- Нужны findings ревью, AC, DoD или декомпозиция результата.
- Нужно сначала исследовать трекер, wiki, код и проектные заметки, затем
  согласовать план работ.

## Когда не применять

- Для чистого code review используй процесс ревью кода.
- Для реализации уже утвержденной постановки следуй инструкциям репозитория.
- Для проверки фактической поставки исследуй код, CI и среду напрямую.
- Для локальной редакционной правки без изменения смысла достаточно редактора;
  полный pipeline не нужен.

## Фаза 0. Выбери профиль

**Вход:** известен текущий каталог или корень проекта.

1. Определи профиль детерминированно:

   ```text
   python3 {baseDir}/scripts/spec_pipeline.py detect --cwd "<cwd>"
   ```

2. Загрузи ровно один профиль:

   ```text
   python3 {baseDir}/scripts/spec_pipeline.py show-profile auto --cwd "<cwd>"
   ```

3. Маршрутизатор ищет ближайший `<project-root>/.vigers/profile.md`; если файла
   нет, использует встроенный `generic`. Профиль не заменяет ближайшие
   `AGENTS.md` и `CLAUDE.md`: прочитай их по правилам проекта.

**Выход:** `profile_id`, `project_root` и один загруженный профиль.

## Фаза 1. Исследуй и согласуй planning-case

**Вход:** выбран профиль, задача не сводится к ревью готового артефакта или
мелкой редакционной правке.

1. Полностью прочитай `{baseDir}/workflows/planning-pipeline.md`,
   `{baseDir}/references/planning-contract.md` и
   `{baseDir}/references/solution-boundary-contract.md`. Для опциональных
   checklists, task-manager projection и времени также прочитай
   `{baseDir}/references/runtime-preferences.md` и
   `{baseDir}/references/automation-timing.md`.
2. Создай planning-case и один ранний passport. Команда `init --cwd "<cwd>"`
   автоматически подхватывает `planning_anchors` ближайшего profile. Найди
   существующие единицы результата, создай или свяжи обязательные пустые anchors
   до research и зафиксируй read-back; это не разрешает наполнять задачи планом
   или менять workflow-поля.
3. Пройди `researching → researched`: выполни read-only поиск по применимым
   источникам profile, зафиксируй запросы, freshness, противоречия и coverage.
4. Построй зависимые этапы и checklists, подготовь разрешённые до review external
   artifacts через project adapters и прочитай записи обратно. Модель не
   оценивает время. После materialized preliminary analysis отдельный
   `timing_model.py` выбирает кейсы только этого проекта по change scope, типам
   surfaces/рисков, компонентам и форме плана и прогнозирует human-only остаток
   до первой передачи. Project calendar разделяет active/business/calendar ETA, а `ready_for_handoff` — готовность и ожидание. После handoff `work-metrics` согласует полные
   журналы; Vigers принимает только eligible fingerprinted результат. Доанализ
   после передачи — отдельный follow-up, не обучающий ETA первого цикла.
   Дополнительно выяви preliminary `PUS-*` и `PDOD-*` со
   ссылками на источники; они обязательны для проверки полным анализом, но не
   являются утверждёнными требованиями или финальным DoD.
   Также сохрани preliminary solution-boundary probe: найденные аналоги,
   отрицательный результат, кандидат корневой способности и горизонта. Это не
   финальный scope.
5. Покажи `approval-summary.md`: preliminary `PUS-*`/DoD, coverage/gaps и план;
   пометь истории изменяемыми, а approval — не финальным. До него не запускай case.
6. После approval создай или свяжи объявленные profile post-approval artifacts.
   Для `working_projection: required` хотя бы один target должен иметь
   `working_projection: true`, `publish_gate: after_approval` и read-back.
   Target также фиксирует `evidence_kind: local_file|external_readback`; тип
   evidence нельзя менять при runtime update. Он существует до запуска полного
   анализа, даже если пока содержит только
   рабочую рамку и маркировку непроверенных разделов. Затем экспортируй
   `planning-handoff.json/md` в будущий case-root.

Review готовой постановки может пропустить planning-case, если target и scope
ревью уже однозначны. Для нового анализа, изменения, декомпозиции или
архитектурной проработки shortcut `--allow-unplanned` запрещён.

**Выход:** planning-case в `handed_to_vigers` и проверяемый approved handoff.

## Фаза 2. Выбери методический маршрут

**Вход:** понятна область постановки.

1. Для обычной задачи используй `core`.
2. Если нужна специальная область, выбери ровно один маршрут:

   ```text
   python3 {baseDir}/scripts/vigers_context.py match "<область задачи>"
   python3 {baseDir}/scripts/vigers_context.py materialize <route_id> \
     --write "<case-root>"
   ```

3. Один точный C/D/T-артефакт добавляй через `--id <Cxx|Dxx|Txx>`, только если
   он разрешён маршрутом. Ограниченный книжный fallback добавляй через
   `--fallback`, только если после дистиллята осталась названная нехватка.
4. Не пересказывай результат в prompt вручную. `materialize` создаёт
   `method-context.md` и `method-context.json`; `case_pipeline.py init`
   проверяет их по текущим источникам метода и связывает fingerprint с case.

**Выход:** один `route_id` и неизменяемый ограниченный методический контекст в
case-root.

## Фаза 3. Выбери масштаб и assurance

**Вход:** известны профиль, маршрут и объём смысловых связей.

Сначала оркестратор извлекает только наблюдаемые признаки задачи, затем
детерминированная команда выбирает режим. Не проси команду интерпретировать
сырой текст постановки и не выдумывай признаки ради желаемого результата.

| Режим | Когда | Workflow |
|---|---|---|
| `compact` | Один связный смысловой контур помещается в один независимый проход | `{baseDir}/workflows/specification-pipeline.md` |
| `block` | Несколько сценарных/контрактных контуров, большой корпус источников или риск потери сквозной связности | `{baseDir}/workflows/block-pipeline.md` |

Команда рекомендует `block`, если выполняется хотя бы одно:

- есть три и более независимо проверяемых смысловых блока;
- одновременно меняются несколько из: сценарии, правила, данные, интерфейсы,
  права, состояния, ошибки, качества;
- источники или готовый документ небезопасно передавать одной роли целиком;
- разные части зависят друг от друга и требуют явного порядка;
- обновление затрагивает несколько владельцев данных или компонентов.

Не дели документ механически по заголовкам финального шаблона. Блок —
семантический контракт с собственными входами, результатом и трассировкой.
Обычно достаточно 3–8 блоков; большее число сначала сгруппируй.

Передай только подтверждённые флаги: оценку числа независимых блоков; затронутые
семантические поверхности; компоненты и владельцев; зависимый порядок;
небезопасность одного прохода; сработавшие триггеры из проектного профиля.
Повторяй `--surface`, `--component`, `--owner` и `--project-trigger` по одному
разу на значение. Допустимые surfaces: `scenarios`, `rules`, `data`,
`interfaces`, `permissions`, `states`, `errors`, `qualities`.

```text
python3 {baseDir}/scripts/spec_pipeline.py suggest-mode --cwd "<cwd>" \
  --task "<краткая область>" --blocks <N> \
  --surface scenarios --surface interfaces --component "<component>" \
  --dependent-parts --change-scope semantic-local \
  --project-trigger "<profile-trigger>" \
  --write "<case-root>/mode-decision.json"
```

Добавь проверяемый `--change-scope`. Публичный контракт, migration/schema,
security/permissions, cross-service ownership, необратимость, compliance или
архитектурное решение повышают assurance до `high`. Остальная смысловая работа
по умолчанию `standard`, редактура — `lite`. Явные `--requested-mode` и
`--requested-assurance` имеют приоритет; override сохраняется в `warnings`.

Прочитай `selected_mode` из JSON и инициализируй case тем же значением:

```text
python3 {baseDir}/scripts/case_pipeline.py init --case-root "<case-root>" \
  --case-id "<stable-id>" --mode "<selected_mode>" --intent "<intent>" \
  --cwd "<cwd>" --profile-id "<profile-id>" --route-id "<route_id>"
```

`init` допускает заранее созданные decision и method context, связывает оба
fingerprint с manifest и отклоняет несовпадение режима, профиля, маршрута или
книжной выжимки. Для review готового артефакта передай `--intent review`: только
этот intent может запускаться без planning handoff.

**Выход:** независимо выбраны scale, assurance, tracking и projection sync;
decision и case package согласованы.

## Общие роли

| Роль | Когда | Контракт | Результат |
|---|---|---|---|
| `vigers-planner` | До Vigers case; свежий context на research cluster, plan и revision | `{baseDir}/agents/contracts/planner.md` | Research coverage, DAG плана и проект внешних артефактов |
| `vigers-system-analyst` | Всегда; в block-mode отдельно на каждый блок | `{baseDir}/agents/contracts/system-analyst.md` | Модель требований или блока |
| `vigers-solution-architect` | По архитектурному гейту, отдельно `design` и `conformance` | `{baseDir}/agents/contracts/solution-architect.md` | Решение или архитектурное заключение |
| `vigers-spec-editor` | После модели; режимы `document`, `block-render`, `integrate` | `{baseDir}/agents/contracts/spec-editor.md` | Черновик блока или всего документа |
| `vigers-spec-reviewer` | `block`, `integration`, `global`, `final`, `project-conformance` | `{baseDir}/agents/contracts/spec-reviewer.md` | Независимые findings |

Business analysis не является отдельной обязательной ролью. Системный аналитик
включает линзу `business-context`, когда неизвестны потребность, участники,
процесс, эффект или владелец решения. Он не принимает бизнес-решения от имени
пользователя и выносит их ответственному владельцу.

## Архитектурный гейт

Запусти архитектора, если затронуто хотя бы одно:

- выбран `tactical` или `generalized-capability` по контракту границы решения;

- границы сервисов, компонентов или владение данными;
- новая интеграция, выбор sync/async или транспорт;
- новый API-контракт либо обратная совместимость;
- схема хранения, жизненный цикл или согласованность данных;
- безопасность, RBAC/ABAC, мультитенантность или аудит;
- транзакционность, идемпотентность, миграция или откат;
- существенные качества: производительность, доступность, масштабирование;
- новый сервис, хранилище, инфраструктурный механизм или изменение ADR.

Не запускай архитектора для редакционной правки, локального UI-текста,
уточнения сообщения об ошибке или прямого расширения уже принятого решения без
новой границы. Если системный аналитик или ревьюер обнаружил пропущенное
архитектурное влияние, вернись к гейту.
`bounded-systemic` — общий горизонт по умолчанию и сам по себе не является
архитектурным trigger.

## Независимость контекстов

- В Codex запускай каждую роль без истории родительского диалога и передавай
  только case package и точные критерии.
- В Claude используй новый Task-вызов роли на каждый проход.
- `design` и `conformance` архитектора — два разных запуска.
- Один смысловой блок — один свежий запуск роли. Независимые блоки можно
  выполнять параллельно, но не дроби один блок на несколько конкурирующих истин.
- Planning research можно делить на независимые source clusters, но итоговый
  `research.md` и DAG плана сшиваются отдельным свежим проходом.
- Ревьюер не получает рассуждения редактора, самооценку и предыдущие findings.
- Роль читает только `contract_inputs`; evidence не может подключать surfaces.
- Роль возвращает структурированный результат координатору. Только координатор
  сохраняет его в case package и применяет принятые изменения.
- Ни одна роль не меняет проектные или внешние артефакты самостоятельно.

## Исполняемый workflow

Для новой или изменяемой задачи сначала полностью выполни planning workflow.
После approved handoff, выбора маршрута и масштаба полностью прочитай ровно один
specification workflow и выполни его:

- `compact` → `{baseDir}/workflows/specification-pipeline.md`;
- `block` → `{baseDir}/workflows/block-pipeline.md`.

Оба workflow задают входы, выходы, условные гейты, цикл исправлений и
возобновление. Выполнение approved этапов ведёт выбранный tracking по
`{baseDir}/references/automation-timing.md`. Block-mode дополнительно следует
`{baseDir}/references/case-state.md` и `{baseDir}/references/block-contract.md`.
Перед research/review полностью прочитай
`{baseDir}/references/convergence-contract.md`: он определяет, когда поиск можно
переоткрыть, какие findings блокируют gate и когда нужно идти дальше.
Перед системным анализом, design, author passes и global review используй
`{baseDir}/references/solution-boundary-contract.md`. Принятый boundary должен
быть записан в `decisions.md` до `author_passes`; изменение decision или
planning probe после pass делает гейт stale.
Как только во время полного анализа доказано, что approved plan неполон или
неверен, останови текущий проход и не проталкивай старый DAG. Открой новую
planning revision командой `replan`, сохрани старый snapshot и выполненные
пункты, затем синхронизируй delta с read-back. Локальная некритичная коррекция
может быть принята координатором без отдельного user review; критичная требует
approval пользователя до продолжения изменённого scope.
Внутри уже принятого плана выполняй обычные `Pxx-Cxx` без отдельного
согласования каждого пункта: completion evidence и внешняя галка подтверждают
выполнение, а не запрашивают новое решение пользователя.
Runtime `draft.md`, block artifacts и `working-projection.json` остаются машинным
контуром. Синхронизируй targets по выбранному `projection_sync`; перед
author/final/project gate всегда нужен актуальный полный `draft|integration`
read-back. В `per-block` Bxx update остаётся барьером следующего блока. Локальный
файл подтверждай `--evidence-kind local_file`, внешний tracker/wiki —
сохранённым JSON receipt проектного адаптера и
`--evidence-kind external_readback`.

## Быстрые режимы

| Запрос | Минимальный путь |
|---|---|
| Небольшая новая или изменённая постановка | Planning pipeline → Compact pipeline |
| Большая/многоконтурная постановка | Planning pipeline → Block pipeline |
| Ревью готовой постановки | Профиль → маршрут → mode-decision → `--intent review` → reviewer → architect conformance по гейту |
| Редактура без изменения смысла | Профиль → editor → reviewer только при существенной правке |
| Архитектурная проработка без постановки | Planning pipeline → system analyst → architect design → решение |
| AC/DoD для готовых требований | Planning pipeline → system analyst → editor → reviewer |

## Проверка скилла

После изменения файлов выполни:

```text
python3 {baseDir}/scripts/vigers_context.py validate
python3 {baseDir}/scripts/spec_pipeline.py validate
python3 -m unittest discover -s {baseDir}/scripts -p 'test_*.py'
```

Для конкретного planning-case дополнительно выполни `planning_case.py validate`
с его реальным `--case-root`; эта команда не относится к package-only проверке.

## Критерии успеха

- Выбран ровно один ближайший project overlay либо generic и один маршрут метода.
- Planning research покрывает применимые project sources либо честно фиксирует
  partial/blocked coverage; план, checklists, preliminary US и preliminary DoD
  ссылаются на `SRC-NNN`.
- Перед approval показан immutable `approval-summary.md`: preliminary US имеют role-goal-value и пометку об изменяемости; JSON/checklist не заменяют сводку.
- Planning probe сохранил поиск аналогов и отрицательный результат; полный
  анализ выбрал доказуемый горизонт и разделил current scope, extension seams,
  deferred variants и expansion triggers. Reviewer проверил оба запаха:
  `particular-case` и `speculative-generalization`.
- Полноценный non-review Vigers case связан с approved planning handoff; старые
  revisions, user comments и external read-back bindings не потеряны.
- Runtime ledger связан с точными planning revision и passport; перед финалом
  нет running или pending этапов required/measured plan. При включённом времени
  active исключает pause/limit waits, calendar elapsed включает их, а business
  elapsed вне окон добавляет только наблюдаемую работу, без фонового WIP и `deferred`. Прогноз строится после preliminary analysis по истории текущего проекта и имеет
  `purpose: human_information_only`.
- Ролевой context содержит `planning-role-context.json`, но не automation plan,
  ETA или runtime ledger.
- При `working_projection: required` видимый target создан или связан до полного
  анализа. Cadence соответствует `milestones|per-block`; скрытый case
  не выдаётся за пользовательский черновик, а рабочий draft не называется
  финальной публикацией.
- Tracking соблюдает `off|milestones|fine`; внешняя галка подтверждена read-back.
- Replanning срабатывает немедленно во время полного анализа: текущий проход
  останавливается, новая revision/delta хранит причину и evidence, а старый
  approved snapshot и уже выполненные пункты не исчезают. Отдельный user
  approval требуется только для критичной коррекции.
- Пункты принятого плана не требуют поштучного user approval; новый decision
  gate появляется только при material delta или иной явно критичной развилке.
- Методический маршрут материализован и привязан к case; аналитик и reviewer
  получают его автоматически, а редактор не получает книжный корпус.
- Аналитик отделил факты, решения, предположения и открытые вопросы.
- В block-mode каждый блок свеж относительно kernel; high сохраняет локальное
  ревью каждого блока, standard применяет risk-based review.
- Семантические ID уникальны, ссылки разрешаются, REQ трассируются к AC.
- Review после сборки соответствует assurance: combined final либо separate passes.
- Project-conformance проверил только применимые локальные соглашения.
- Объявленный profile document contract прошёл machine check по закреплённому
  draft и актуальной видимой проекции; review evidence не перезаписало прежнюю
  ревизию.
- Объявленная profile форма User Story едина во всём документе; системные
  semantic IDs сохранены в собственных разделах и связаны трассировкой.
- Объявленная linked traceability содержит только отдельные разрешаемые ссылки;
  plain-text IDs, сокращённые диапазоны и dangling/ambiguous targets отсутствуют.
- Объявленная reader projection не содержит внутренних IDs и process jargon;
  каждое публичное semantic reference во всём теле является точной ссылкой, а
  traceability не хранит транзитивное замыкание.
- AC исполнимы фактическим приёмщиком: UI-критерий ведёт к точному сценарию с экраном/маршрутом либо содержит их сам, а non-UI — к системной точке входа; DoD фиксирует готовность к приёмке, developer self-check исключён без нормативного основания.
- После локальной правки `begin-remediation` сохранил immutable review/baseline;
  проверены finding, объявленные semantic IDs и прямые регрессии. Полный block/
  whole-case review запущен только при смысловой переписи, изменении цели,
  границы, публичного контракта, архитектуры или сквозной логики.
- Diagram gate имеет `required|not-required|blocked`; все required surfaces
  представлены, семантически сверены и просмотрены в фактическом render. Одна
  гигантская нечитаемая схема не считается покрытием нескольких surfaces.
- Diagram delivery contract соблюдён: working source редактируем, QA-render не опубликован, persistent render/source созданы только на publication gate.
- Business-context не присвоил пользователю ответственность бизнес-владельца.
- Архитектор вызван только по гейту; `design` и `conformance` независимы.
- Редактор не добавил новых требований и решений.
- Ревьюер вернул доказуемые findings, а не вкусовые пожелания.
- После review нет открытых принятых `blocker/major`; residual `minor`
  зафиксированы и не переоткрывают gate. Новый research после coverage gate
  ссылается на конкретный `blocker|major`, target sources и stop condition.
- AC трассируются к требованиям, требования — к цели.
- Публикация и изменения внешних систем не выполнены без явной просьбы.
- Specification-ready не выдан за delivery-complete; ручные handoff-пункты
  закрыты только пользователем, а terminal status подтверждён delivery evidence.

## Индекс

| Путь | Назначение |
|---|---|
| `{baseDir}/references/requirements-method.md` | Канонический метод Вигерса |
| `{baseDir}/references/planning-contract.md` | Research, plan DAG, passport, external drafts и approval contract |
| `{baseDir}/references/automation-timing.md` | Прогноз, wall-clock ledger, команды и агрегация истории |
| `{baseDir}/references/execution-policy.md` | Assurance, tracking, projection cadence, change impact и telemetry |
| `{baseDir}/references/convergence-contract.md` | Порог качества, переоткрытие research и остановка minor-only циклов |
| `{baseDir}/references/solution-boundary-contract.md` | Горизонты решения, границы scope и двусторонняя защита от hardcode/overengineering |
| `{baseDir}/references/diagram-contract.md` | Diagram gate, выбор представления, декомпозиция и render QA |
| `{baseDir}/references/reader-projection-contract.md` | Граница внутренней модели и итогового текста, UI-пути, AC/DoD, прямые ссылки и ресурсная дисциплина |
| `{baseDir}/references/handoff-contract.md` | Контракт case package и результатов ролей |
| `{baseDir}/references/prompt-contract.md` | Сборка ограниченного prompt для независимой роли |
| `{baseDir}/evals/prompt-cookbook/convergence-closed-coverage.json` | Регрессия prompt: закрытый coverage не переоткрывается без существенной evidence-дыры |
| `{baseDir}/evals/prompt-cookbook/delivery-completion-handoff-barrier.json` | Регрессия prompt: готовая постановка не закрывает delivery/incident, а ручной handoff остаётся за пользователем |
| `{baseDir}/evals/prompt-cookbook/project-conformance-document-barrier.json` | Регрессия prompt: словесный pass не обходит машинный шаблон документа |
| `{baseDir}/evals/prompt-cookbook/early-working-projection.json` | Регрессия prompt: обязательный рабочий draft появляется и обновляется до финальной интеграции |
| `{baseDir}/evals/prompt-cookbook/live-checklist-completion-barrier.json` | Регрессия prompt: выполненный пункт синхронизируется сразу без навязывания порядка независимым пунктам |
| `{baseDir}/evals/prompt-cookbook/profile-owned-working-projection.json` | Регрессия prompt: форма видимой проекции берётся из project profile без универсального локального дубля |
| `{baseDir}/evals/prompt-cookbook/bounded-systemic-scope.json` | Регрессия prompt: общий класс выявлен без расширения поставки до спекулятивного конструктора |
| `{baseDir}/evals/prompt-cookbook/solution-boundary-smells.json` | Регрессия prompt: reviewer симметрично ловит частный hardcode и преждевременную универсализацию |
| `{baseDir}/evals/prompt-cookbook/user-story-format-barrier.json` | Регрессия prompt: системные IDs не подменяют единую project-owned форму User Story |
| `{baseDir}/evals/prompt-cookbook/traceability-link-barrier.json` | Регрессия prompt: plain-text IDs и диапазоны не обходят linked traceability gate |
| `{baseDir}/evals/prompt-cookbook/diagram-complexity-barrier.json` | Регрессия prompt: полный текст не подменяет required diagrams и visual QA |
| `{baseDir}/evals/prompt-cookbook/diagram-render-lifecycle-barrier.json` | Регрессия prompt: рабочий QA не создаёт PNG/source до publication gate |
| `{baseDir}/evals/prompt-cookbook/reader-projection-barrier.json` | Регрессия prompt: служебная модель, developer checks и транзитивная трассировка не протекают в постановку |
| `{baseDir}/evals/prompt-cookbook/user-journey-screen-context-barrier.json` | Регрессия prompt: UI-сценарий называет экран и видимые поля без повторов и догадок |
| `{baseDir}/evals/prompt-cookbook/acceptance-verification-context-barrier.json` | Регрессия prompt: каждый AC ведёт тестировщика к точному сценарию или точке входа |
| `{baseDir}/evals/prompt-cookbook/human-only-timing-boundary.json` | Регрессия prompt: forecast не попадает в модель и не управляет её работой |
| `{baseDir}/evals/prompt-cookbook/targeted-remediation-preserves-coverage.json` | Регрессия prompt: major проверяется по delta без потери прежнего покрытия |
| `{baseDir}/references/case-state.md` | Машина состояний, команды и возобновление |
| `{baseDir}/references/runtime-preferences.md` | User/project toggles для timing, progress и task-manager projection |
| `{baseDir}/references/automation-timing.md` | Active/business/calendar timing, deferred lifecycle и проектный калибратор |
| `{baseDir}/references/block-contract.md` | Контракт семантического блока и sidecar index |
| `{baseDir}/references/knowledge-map.md` | Детерминированная карта методических маршрутов |
| `{baseDir}/workflows/specification-pipeline.md` | Мультиагентный pipeline |
| `{baseDir}/workflows/block-pipeline.md` | Итерационный pipeline по смысловым блокам |
| `{baseDir}/workflows/planning-pipeline.md` | Research-and-planning preflight |
| `{baseDir}/profiles/generic.md` | Безопасный fallback без проектных сведений |
| `{baseDir}/profiles/project-profile-template.md` | Контракт локального `.vigers/profile.md` |
| `{baseDir}/agents/contracts/` | Канонические контракты общих ролей |
| `{baseDir}/scripts/spec_pipeline.py` | Детектирование и валидация профилей |
| `{baseDir}/scripts/case_pipeline.py` | Детерминированный оркестратор case-state |
| `{baseDir}/scripts/planning_case.py` | Planning state, revisions, external bindings и approved handoff |
| `{baseDir}/scripts/automation_timing.py` | Stage start/stop, validation, summary и aggregation |
| `{baseDir}/scripts/timing_model.py`, `{baseDir}/scripts/timing_calendar.py` | Project-local similarity model и calendar handoff projection |
| `{baseDir}/scripts/vigers_context.py` | Маршрутизация методического контекста |
| `{baseDir}/scripts/install.py` | Безопасное подключение скилла и агентов к рантаймам |
