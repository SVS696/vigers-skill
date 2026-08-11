# Automation timing

Vigers измеряет длительность автоматизированного выполнения отдельно от личного
учёта времени пользователя и календарного обещания результата. Метрика всегда
`wall_clock` в секундах: от фактического входа pipeline в этап до его terminal
status, включая tool waits и технические блокировки внутри этапа.

Не включай в эту метрику:

- часы пользователя, CRM timesheet или task-manager timer;
- ожидание user review до запуска approved pipeline;
- рабочие дни, выходные и календарную доступность пользователя;
- срок, который пользователь обещает внешнему получателю.

## Граница с личным трекером и постановкой

`automation-timing.json` — внутренний runtime ledger Vigers, а не канонический
источник требований. Pipeline не публикует его оценки, фактические замеры и
служебные причины в Redmine, Jira, документ постановки или иной внешний
артефакт без отдельного явного решения пользователя.

Личный task manager, включая Singularity, находится вне этого контракта:
пользователь может хранить там любые оценки, таймеры и черновые заметки. Vigers
не ограничивает их содержание; человекочитаемый план и прогресс pipeline могут
быть спроецированы туда по правилам рабочего процесса. Содержимое личного
трекера не переносится автоматически в Redmine, Jira или итоговую постановку и
не становится требованием только по факту такой записи.

## Прогноз в planning-case

Новый `plan.json` использует schema 4. Верхний уровень объявляет обязательную
метрику:

```json
{
  "schema": 4,
  "revision": 5,
  "automation_estimation": {
    "policy": "required",
    "metric": "wall_clock",
    "unit": "seconds",
    "execution_use": "human_information_only"
  },
  "stages": []
}
```

Каждый этап содержит трёхточечную оценку:

```json
{
  "id": "P03",
  "automation_estimate": {
    "optimistic_seconds": 1800,
    "likely_seconds": 2700,
    "pessimistic_seconds": 3600,
    "basis": "heuristic",
    "confidence": "low",
    "sample_size": 0
  }
}
```

Допустимые basis: `heuristic`, `analogous`, `historical`. Пока исторических
наблюдений нет, используй `heuristic`, `low`, `sample_size: 0`; не изображай
точность. При наличии агрегата укажи реальный basis и число использованных
наблюдений.

Общий срок автоматизации считай по critical path DAG, а не суммой всех этапов:
параллельные этапы не должны искусственно раздувать прогноз. Календарный срок для
пользователя остаётся отдельным решением вне машинного прогноза.

## Оценка существует только для человека

Любая оценка предварительна, включая `historical`: это информация для plan review,
сравнения с фактом и калибровки следующих планов. Поле `execution_use` всегда
равно `human_information_only`. Значения ETA не входят в assignment и bounded
context системного аналитика, архитектора, редактора или reviewer. Для них
`case_pipeline.py context` выдаёт `planning-role-context.json` без
`automation_plan` и без runtime ledger.

После старта этапа агенту запрещено использовать optimistic/likely/pessimistic
как дедлайн, timebox, лимит усилий или сигнал ускориться/остановиться. Оценка не
может влиять на:

- полноту source coverage и число проверяемых сценариев;
- обязательные тесты, render, read-back и независимое review;
- повторы после нестабильного результата;
- качество артефакта, детализацию evidence и решение об эскалации;
- продолжение этапа после превышения pessimistic.
- выбор модели, reasoning effort, token/context budget и порядок независимых
  ролей.

Этап завершается только по exit criteria, явному blocker/terminal failure либо
прямому решению пользователя. Превышение оценки само по себе не blocker и не
terminal reason: pipeline продолжает работу, записывает фактический wall-clock и
сравнивает его с baseline только после terminal status.

Schema 1 читается как legacy plan без telemetry, schema 2 — как совместимый
telemetry-plan без обязательных preliminary US/DoD, schema 3 — как совместимый
план с preliminary US/DoD. Новые revisions используют schema 4 с
solution-boundary probe.

## Handoff и ledger

`planning_case.py export` переносит immutable `automation_plan` в
`planning-handoff.json`. `case_pipeline.py init` проверяет fingerprint и создаёт
`automation-timing.json`, связанный с:

- Vigers `case_id`;
- `planning_case_id` и approved revision;
- fingerprint прогноза;
- passport ID/path;
- этапами, dependencies, прогнозами и runtime status.

Прогноз внутри ledger неизменяем. Runtime меняет только status, timestamps,
`actual_seconds`, checklist progress, terminal reason и append-only events. `case_pipeline.py validate`
сверяет ledger с approved handoff и обнаруживает ручную подмену оценок.
Runtime-переходы не сравнивают elapsed с прогнозом и не содержат автоматического
timeout по optimistic/likely/pessimistic.

## Выполнение

Перед фактическим входом в approved этап:

```text
python3 {baseDir}/scripts/automation_timing.py start \
  --case-root "<vigers-case-root>" --stage P03
```

Перед началом содержательной работы выбери любой независимый пункт и явно
переведи его в `in_progress`; порядок checklist не является dependency:

```text
python3 {baseDir}/scripts/automation_timing.py begin \
  --case-root "<vigers-case-root>" --stage P03 --item P03-C02
```

Исключение — пункт с `completion_owner: user`: агент его не начинает и не
отмечает. Он готовит handoff и ждёт, пока пользователь сам поставит внешнюю
галку. После явного подтверждения и read-back координатор синхронизирует ledger:

```text
python3 {baseDir}/scripts/automation_timing.py check \
  --case-root "<vigers-case-root>" --stage P03 --item P03-C03 \
  --user-confirmed --evidence "<user-confirmation-ref>" \
  --external-system "<system>" --external-item-id "<item-id>" \
  --read-back-at "<timestamp>"
```

Обычно новый item нельзя начать, пока другой item этого этапа остаётся
`in_progress`: это ловит забытый completion barrier. Для реально одновременной
независимой работы разрешён второй `begin --parallel-reason "<reason>"`; не
используй его как обход несинхронизированной галки.

Как только `done_when` начатого пункта выполнен, прерви обычный ход работы и
проверь результат. Если этап связан с
`external_target_id`, сначала отметь внешнюю галку через project adapter и
прочитай её обратно, затем зафиксируй тот же stable item ID:

```text
python3 {baseDir}/scripts/automation_timing.py check \
  --case-root "<vigers-case-root>" --stage P03 --item P03-C02 \
  --evidence "<artifact-or-check-ref>" \
  --external-system "<system>" --external-item-id "<item-id>" \
  --read-back-at "<timestamp>"
```

Для внутреннего агентского пункта достаточно `--evidence`. Обычный `check`
принимает только item в `in_progress`; user-owned item допускает прямой переход
из `pending` только с `--user-confirmed`. Не откладывай агентские галки до конца
этапа, следующей роли или финального ответа и не объявляй пункт/гейт закрытым до
успешного `check`. Повтор с тем же evidence/read-back идемпотентен; другая
попытка переписать уже завершённый item отклоняется.

После выхода и проверки результата:

```text
python3 {baseDir}/scripts/automation_timing.py stop \
  --case-root "<vigers-case-root>" --stage P03 --status completed
```

Для terminal failure используй `failed|blocked|cancelled` и обязательный
`--reason`. Зависимый этап стартует только после `completed` всех dependencies.
Pause/resume в первой версии нет: временные tool waits остаются частью wall-clock.
Не оставляй running stage перед финальной выдачей.

`stop --status completed` разрешён только после completion всех обязательных
`Pxx-Cxx`. Прогноз, сообщение роли или субъективная уверенность не являются
evidence выполнения.

Как только во время полного анализа требуется изменить approved plan, останови
role pass и закрой текущий stage как `blocked` с причиной `replanning required`.
Открой новую planning revision через `planning_case.py replan` и не переписывай
старый ledger. Для local delta достаточно coordinator approval, для material —
user approval; затем создай следующий case. Неизменившиеся выполненные items
сохраняют stable IDs; перед переносом в новый ledger повторно проверь evidence и
внешнюю галку.

Если pipeline завершился аварийно, при возобновлении прочитай ledger. Продолжение
того же этапа сохраняет исходный `started_at`, поэтому итог показывает реальное
время до результата, включая аварию. Если работа по этапу прекращена, закрой его
terminal status с причиной; не переписывай timestamp вручную.

## Проверка и сводка

```text
python3 {baseDir}/scripts/automation_timing.py validate \
  --case-root "<vigers-case-root>" --final
python3 {baseDir}/scripts/automation_timing.py summary \
  --case-root "<vigers-case-root>" --json
```

Summary отдельно показывает:

- optimistic/likely/pessimistic critical path;
- сумму likely по этапам для диагностики параллельности;
- фактический elapsed всей цепочки;
- сумму длительностей этапов;
- число завершённых и остающихся `in_progress` checklist items;
- отношение actual к likely после terminal завершения.

## Агрегация

```text
python3 {baseDir}/scripts/automation_timing.py aggregate \
  --root "<cases-root>"
```

Aggregate сохраняет case, planning и passport linkage, число наблюдений,
фактические длительности и error ratio. Он не выдаёт новый прогноз автоматически:
на первой версии это evidence для следующей оценки, а не самодельная модель с
ложной уверенностью. Следующий planner использует подходящие наблюдения как
`historical|analogous` и явно указывает `sample_size` и confidence.
