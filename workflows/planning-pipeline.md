# Planning pipeline до Vigers

Используй task-driven workflow для новой, изменяемой, декомпозируемой или
архитектурно прорабатываемой задачи. Ревью готового артефакта может начинаться без
planning-case, если scope ревью уже явно задан.

## Фаза 1. Intake и passport

**Вход:** известна исходная просьба и выбран один project profile.

1. Создай planning-case:

```text
python3 {baseDir}/scripts/planning_case.py init \
  --case-root "<planning-root>" --case-id "<stable-id>" \
  --cwd "<cwd>" --profile-id auto \
  --passport-id "<existing-or-temporary-id>" --passport-path "<local-path>"
```

Команда сама читает `planning_anchors` ближайшего profile, сохраняет обязательные
системы в manifest и создаёт по одному `before_research` target. Не объявляй
проектные anchors вручную в общем workflow.

2. Запиши в `intake.md` цель, исходный запрос, предполагаемый scope, известные
   полномочия и initial gaps без улучшения смысла.
3. Если passport отсутствует, создай один по profile с временным ID и
   `provenance_status: partial`. Не создавай второй passport после появления
   tracker ID.
4. Для каждого `before_research` target сначала выполни точный поиск существующей
   единицы результата по profile, затем создай или свяжи пустой учётный anchor.
   Если объект уже существует, передай `bind --action link`, сохрани тот же
   object ID и не создавай дубль. Не добавляй описание,
   план, assignee, priority, commitment date и не меняй workflow status.
   Прочитай объект обратно и запиши binding командой `planning_case.py bind`.
5. Переведи case в `researching`. Команда не пропустит обязательный anchor без
   подтверждённого read-back.

**Выход:** один planning-case и один passport связаны. Внешние системы не
изменены, кроме profile-required пустых учётных anchors и явно разрешённого
создания самого passport.

## Фаза 2. Research design

**Вход:** state `researching`, заполнен intake.

1. Передай `vigers-planner` режим `research-design` и bounded context из:

```text
python3 {baseDir}/scripts/planning_case.py context --case-root "<planning-root>"
```

2. По profile построй search matrix: системы, запросы, authority, freshness и
   достаточность. Включи трекер, wiki, репозиторий, проектные заметки и
   переписку только когда они применимы к задаче.
3. Выполни read-only поиск через project adapters. Фиксируй и найденные, и
   отрицательные/недоступные результаты.
4. Для большого корпуса сгруппируй независимые источники по системе или
   смысловой поверхности. Каждый cluster обрабатывай свежим planner context.

**Выход:** собраны source documents со стабильными `SRC-NNN`; внешних записей нет.

## Фаза 3. Research synthesis и coverage gate

**Вход:** завершены запланированные поиски или зафиксирована недоступность.

1. Передай planner режим `research-synthesis` отдельно от research-design.
2. Заполни `source-map.json` и `research.md`: факты, конфликты, gaps,
   planning implications и `sufficient|partial|blocked`.
3. При `blocked` переведи case в `blocked`, покажи пользователю точную причину и
   не планируй внешние задачи.
4. При `partial` продолжай только если влияние gaps явно ограничено и не мешает
   безопасной декомпозиции.
5. Если источники уточнили уровень существующей единицы результата, до выхода из
   `researching` скорректируй тот же early binding через `bind --action link
   --replace` и новый read-back; не создавай второй anchor.
6. После `sufficient` или допустимого `partial` закрой coverage gate. Не создавай
   новый общий search cluster в последующих фазах. Переоткрыть research можно
   только по принятому `blocker|major` с `remediation: targeted-research` и
   полями из `{baseDir}/references/convergence-contract.md`.
7. Переведи case в `researched`.

**Выход:** coverage gate доказуемо пройден либо case остановлен.

## Фаза 4. Зависимый план и проект внешних записей

**Вход:** state `researched`.

1. Передай planner режим `plan` в новом контексте.
2. Построй `plan.json` schema 3 как DAG этапов с outcome, `depends_on`, exit
   criteria, source refs и checklist. Для каждого этапа добавь трёхточечный
   `automation_estimate` по `{baseDir}/references/automation-timing.md`. Общий
   автоматизированный срок считай по critical path, а не суммой параллельных
   этапов. Обязательно задай `execution_use: human_information_only`: цифры
   показываются человеку, не входят в ролевой context и не управляют темпом,
   порядком, scope, остановкой, покрытием или проверками модели. Не копируй
   структуру будущей постановки
   механически.
3. Выяви предварительные `PUS-*` и `PDOD-*` по research basis. Добавь их в
   `preliminary_requirements` со статусом `preliminary`, source refs, confidence
   и обязательным `validation_gate: full_analysis`. Не считай planning approval
   утверждением US/DoD: полный анализ может подтвердить, изменить, разделить,
   отклонить или дополнить их.
4. Сформируй `plan.md`, `artifact-plan.json` и `handoff.md`. Если profile
   объявляет `working_projection: required`, добавь один или несколько
   согласованных targets с `working_projection: true`,
   `publish_gate: after_approval` и обязательным read-back. Канал выбирает
   профиль: обычный проектный файл, tracker, wiki либо их допустимая комбинация.
   Для каждого target сразу зафиксируй
   `evidence_kind: local_file|external_readback`.
5. Сохрани уже связанные `before_research` targets; не создавай их повторно.
6. Для checklist примени правила `{baseDir}/references/planning-contract.md`:
   содержательный title, optional details/done_when в task note,
   `completion_owner: user` для ручных гейтов и subtask только при
   самостоятельном результате/dependency/owner.
7. Проверь ясность формулировок, затем выполни `simplicity-spec` → `humanizer`
   без пользовательского voice profile. Не вызывай отдельного агента для
   каждого пункта; обрабатывай checklist целиком. Подробный пункт допустим, если
   сокращение теряет условие или критерий готовности.
8. Переведи case в `artifacts_planned`.

**Выход:** план минимален, зависим, основан на источниках и готов к проектной
публикации.

## Фаза 5. Draft external artifacts

**Вход:** state `artifacts_planned`, artifact-plan указывает разрешённые actions.

1. Обрабатывай только targets с `publish_gate: before_review`; ранние anchors уже
   связаны, `after_approval` ожидает решения пользователя, `none` означает
   отсутствие записи.
2. Через project adapter создай/обнови draft-артефакты личного task manager,
   tracker или wiki в порядке зависимостей.
3. Не меняй workflow status, assignee, priority, обещанный срок или production
   state, если это отдельно не разрешено profile и пользователем.
4. Прочитай каждый объект обратно и запиши binding:

```text
python3 {baseDir}/scripts/planning_case.py bind \
  --case-root "<planning-root>" --target-id EXT-001 \
  --system "<system>" --object-id "<id>" --url "<url>" \
  --read-back-at "<timestamp>" [--action "create|update|link"] [--replace]
```

5. Переведи case в `published_for_review`; команда создаст immutable snapshot.

**Выход:** пользователь видит план и реальные draft objects; IDs/read-back
зафиксированы.

## Фаза 6. User review и revision loop

**Вход:** state `published_for_review`.

1. Покажи plan.md, source coverage/gaps, passport и ссылки на external bindings.
2. Не переходи дальше без явного комментария или approval пользователя.
3. Запиши verdict:

```text
python3 {baseDir}/scripts/planning_case.py review \
  --case-root "<planning-root>" --verdict "changes_requested|approved" \
  --actor "<actor>" --note "<verbatim decision>"
```

4. Для `changes_requested` переведи case в `researching`: новая revision обязана
   проверить, нужен ли research delta. После уже закрытого coverage новый поиск
   ограничен конкретным изменением пользователя, новым evidence или принятым
   `blocker|major`; поиск «для уверенности» запрещён. Старый snapshot не изменяй.
5. Повтори фазы 2–6 до approval. Не ограничивай число содержательных ревизий, но
   после трёх повторов одной и той же блокировки назови impasse и запроси решение.

**Выход:** одна точная revision approved либо case ожидает исправлений.

## Фаза 7. Handoff и запуск Vigers

**Вход:** state `approved`.

1. Обработай targets с `publish_gate: after_approval` через project adapter.
   Их action и назначение уже входят в approved snapshot и не меняются. Прочитай
   объекты обратно и запиши bindings командой из фазы 5.
   Working projection создай до экспорта handoff: даже начальная рамка должна
   быть видимой человеку, отличать проверенные сведения от provisional и явно
   говорить, что это не финальная публикация.
2. Экспортируй bounded snapshot в ещё не инициализированный Vigers case-root:

```text
python3 {baseDir}/scripts/planning_case.py export \
  --case-root "<planning-root>" --write "<vigers-case-root>"
```

3. Материализуй `mode-decision.json` и `method-context.json/md` в тот же root.
4. Запусти `case_pipeline.py init` с точными `--intent`, `--cwd`, profile и
   `--route-id "<route_id>"`, без `--allow-unplanned`. Он проверит planning
   approval, project root и fingerprints, затем создаст связанный
   `automation-timing.json`.
5. Продолжи compact/block workflow. Planning basis входит в bounded role context
   через `planning-role-context.json` без ETA; raw automation plan остаётся
   только у оркестратора и не заменяет requirement analysis.

**Выход:** planning-case имеет state `handed_to_vigers`; полноценный Vigers case
создан только из approved snapshot.

Обычные пункты approved plan выполняй без повторного согласования каждого
`Pxx-Cxx`. Немедленная отметка completion, evidence и внешний read-back — это
фиксация факта исполнения, а не новый approval gate.

## Фаза 8. Replanning во время полного анализа

**Вход:** системный аналитик остановил текущий проход и вернул доказанный
`status: replan` с `planning_delta`.

1. Реагируй сразу: не дожидайся окончания полного анализа, не сохраняй его
   частичный результат как модель требований и не продолжай заведомо неверный
   DAG.
2. Закрой active runtime stage как `blocked` с причиной `replanning required`.
3. Открой новую revision:

```text
python3 {baseDir}/scripts/planning_case.py replan \
  --case-root "<planning-root>" --impact "local|material" \
  --reason "<why plan must change>" --evidence-ref "<analysis-ref>"
```

4. Выполни только необходимый research/plan delta. Research delta допустим лишь
   по существенной evidence-дыре с `research_question`, `missing_evidence`,
   `target_sources` и `stop_condition`; иначе скорректируй только план. Старые
   snapshots, approval, handoff и runtime ledger не удаляй.
5. Синхронизируй изменённый внешний checklist. Уже выполненные неизменившиеся
   пункты сохраняют stable ID и галку; удалённые/заменённые явно пометь в delta.
   Каждую запись прочитай обратно.
6. Для `local` delta проверь, что не изменились цель, scope,
   требования/приёмка, внешний контракт, архитектура, риск, обязательства,
   владелец решения и полномочия. После публикации revision зафиксируй её без
   отдельного user review:

```text
python3 {baseDir}/scripts/planning_case.py approve-local-replan \
  --case-root "<planning-root>" \
  --note "<why this delta is non-critical>"
```

7. Для `material` delta снова покажи revision пользователю и получи явный
   approval. Если классификация сомнительна, считай delta material.
8. Экспортируй новый handoff в новый Vigers case-root. Переноси completion только
   после повторной проверки evidence и внешнего checked state.
9. Возобнови прерванный полный анализ в свежем контексте на новой revision; не
   продолжай прежний частичный role output.

**Выход:** анализ возобновлён по новой принятой revision без потери истории и
выполненного прогресса; user review выполнен только для критичной delta.

## Фаза 9. Проверка

**Вход:** Vigers case и все bindings созданы.

1. Выполни:

```text
python3 {baseDir}/scripts/planning_case.py validate --case-root "<planning-root>" --final
python3 {baseDir}/scripts/case_pipeline.py validate --case-root "<vigers-case-root>"
python3 {baseDir}/scripts/automation_timing.py validate --case-root "<vigers-case-root>"
```

2. Проверь, что passport один, external IDs прочитаны обратно, profile совпадает,
   source refs разрешаются, approval относится к экспортированному revision, а
   timing ledger содержит тот же plan fingerprint и passport linkage.

**Выход:** planning и Vigers packages согласованы и возобновляемы.
