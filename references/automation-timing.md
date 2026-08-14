# Таймер и проектная калибровка

Время в Vigers существует только для человека. Оно не является входом модели,
deadline, timebox, бюджетом токенов, критерием остановки или основанием менять
scope, assurance, порядок ролей и полноту проверок. Ролевой context исключает
`automation_plan`, прогноз, runtime ledger и историю калибратора.

## Когда появляется прогноз

Прогноз строится только после предварительного анализа:

1. planner завершил research coverage;
2. материализованы `mode-decision.json` и `plan.json` с этапами/checklists;
3. отдельный детерминированный `timing_model.py` извлёк структурные признаки;
4. он выбрал ближайшие завершённые кейсы только того же project root/profile;
5. project adapter записал человекочитаемый диапазон в task manager и сделал
   read-back, если это включено настройками.

До готового анализа сравнивать задачу с историей запрещено: недостаточно фактов
о поверхностях, компонентах, владельцах, рисках и форме плана. При material
replanning прогноз пересчитывается по новой feature fingerprint.

Прогноз хранится отдельно от постановки и содержит:

- диапазон чистой работы без пауз;
- при project calendar — диапазон `business_elapsed` в рабочих окнах и calendar
  ETA первой передачи;
- raw `calendar_elapsed` как фактический срок с ночами, выходными, обычными
  паузами и deferred-интервалами;
- likely-ориентир для доступных диапазонов;
- число похожих кейсов, confidence и IDs использованных наблюдений;
- `purpose: human_information_only`.

Это прогноз **оставшегося первичного цикла постановки**: preliminary analysis
уже выполнен и в ETA не входит; дальше учитываются полный системный анализ,
применимые design/review gates, исправления, повторные публикации и иные
доработки до первой фактической `development_handoff`. Исторические samples
включают реально случившиеся до handoff итерации, поэтому диапазон со временем
учится на обычной для проекта частоте доработок, хотя конкретную будущую правку
заранее не выдумывает.

Если данных проекта нет, результат — `insufficient_data`, без подмешивания
другого проекта и без выдуманного heuristic.

## Самообучающийся модуль

`scripts/timing_model.py` — эмпирический калибратор, а не LLM-роль. Он получает
только структурные признаки готового предварительного анализа и завершённые
числовые замеры. Текст требований, evidence и прогноз не передаются моделям.

По умолчанию модель проекта живёт в:

```text
<project-root>/.vigers/telemetry/timing-model.json
```

Файл привязан одновременно к `profile_id` и fingerprint канонического project
root. Попытка открыть его из другого проекта отклоняется, даже если profile ID
совпадает. Обновление по тому же case/fingerprint идемпотентно; изменившийся
sample требует явного `--replace`.

Feature schema 2 различает не только количество, но и тип работы:

- точный `change_scope`, включая `semantic-local|semantic-crosscutting`;
- multi-hot сигнатуру semantic surfaces (`data`, `states`, `scenarios`,
  `permissions` и другие канонические типы);
- project-local сигнатуру компонентов с меньшим весом, чтобы не переобучаться
  на имя одного подсервиса;
- сигнатуру типов риска, а не только их число.

Для наборов используется Jaccard distance. Surface types имеют больший вес,
component names — вспомогательный. Старые schema-1 samples сохраняются и
участвуют в подборе, но получают penalty за неизвестные categorical признаки;
старые forecast fingerprints по-прежнему разрешаются при завершении уже начатых
кейсов.

После preliminary analysis:

```text
python3 {baseDir}/scripts/timing_model.py predict \
  --profile-id "<profile-id>" --project-root "<project-root>" \
  --mode-decision "<case-root>/mode-decision.json" \
  --plan "<planning-root>/plan.json" \
  --business-calendar "<project-root>/.vigers/timing-calendar.json" \
  --write "<case-root>/timing-forecast.json"
```

После финального завершённого dual-timer case:

```text
python3 {baseDir}/scripts/timing_model.py update \
  --profile-id "<profile-id>" --project-root "<project-root>" \
  --mode-decision "<case-root>/mode-decision.json" \
  --plan "<planning-root>/plan.json" \
  --ledger "<case-root>/automation-timing.json" \
  --forecast "<case-root>/timing-forecast.json"
```

Если установлен независимый companion `work-metrics` и coordinator может
доказать полноту журналов всех относящихся к кейсу сессий/харнесов, сначала
сформируй post-facto reconciliation:

```text
python3 <work-metrics>/scripts/vigers_adapter.py reconcile \
  --case-root "<case-root>" \
  --forecast "<case-root>/timing-forecast.json" \
  --harness-log "<session-1.jsonl>" \
  --harness-log "<session-2.jsonl>" \
  --business-calendar "<project-root>/.vigers/timing-calendar.json" \
  --logs-complete \
  --write "<case-root>/activity-reconciliation.json"

python3 {baseDir}/scripts/timing_model.py update \
  --profile-id "<profile-id>" --project-root "<project-root>" \
  --mode-decision "<case-root>/mode-decision.json" \
  --plan "<planning-root>/plan.json" \
  --ledger "<case-root>/automation-timing.json" \
  --forecast "<case-root>/timing-forecast.json" \
  --activity-reconciliation "<case-root>/activity-reconciliation.json"
```

Повторяй `--harness-log` для разных сессий и разных харнесов. Адаптер объединяет
пересечения без двойного счёта, склеивает короткие межсобытийные разрывы,
считает длинные разрывы inferred idle и принимает `limit_exhausted` как паузу
до явного `resume` либо следующего наблюдаемого действия. Явные pause intervals
из runtime ledger сильнее вычисленного состояния.

`--logs-complete` — утверждение о coverage, а не режим оптимизма. Его можно
передавать только после перечисления всех известных журналов этого work item.
Partial reconciliation сохраняй для ретроспективы, но не передавай в `update`:
Vigers отклонит неполный, чужой, нетерминальный или повреждённый результат.
При отсутствии companion или доказанной полноты обычный dual-timer ledger
остаётся каноническим fallback и обучение не ломается.

Update создаёт case-local `timing-calibration.json`: фактические active,
business/calendar elapsed, отдельное ожидание ready → handoff, дельту и ratio к
likely, попадание в исходный диапазон, число публикаций и development handoff
timestamp. Этот же record добавляется sample в project model и, при включённом
passport history, в историю паспорта.

При принятом reconciliation calibration записывает его fingerprint и источник
измерения. Счётчики `work-metrics` (tokens, retries, findings и будущие providers)
остаются отдельными наблюдениями: Vigers сейчас читает только `activity-time` и
не превращает прочие метрики во входы ролевых моделей.

Prediction использует не больше двенадцати ближайших наблюдений и сообщает
реальный sample size. `high` confidence требует не меньше восьми близких samples;
при меньшей истории модуль не изображает высокую точность.

## Три временные оси

Новый policy `measured` ведёт:

- `active_seconds` — чистую работу; пользовательская пауза, исчерпание лимита,
  внешнее ожидание и interruption сюда не входят;
- `business_elapsed_seconds` — время в рабочих окнах проекта; явный `deferred`
  исключается, а наблюдаемая off-schedule работа сохраняется;
- `calendar_elapsed_seconds` / legacy `elapsed_seconds` — полную стену до
  terminal/handoff, включая ночи, выходные и все паузы.

`actual_seconds` в measured ledger остаётся совместимым alias чистого времени.
Summary отдельно показывает active critical path, raw calendar span и stage sum.
Business elapsed восстанавливает `work-metrics` по project calendar. Калибратор
не подменяет отсутствующий business sample сырым elapsed: пока таких замеров нет,
человек видит active-прогноз и честное отсутствие calendar ETA.

Project-owned `.vigers/timing-calendar.json` имеет schema 1:

```json
{
  "schema": 1,
  "calendar_id": "project-calendar",
  "timezone": "Europe/Moscow",
  "working_windows": [
    {"weekdays": [1, 2, 3, 4, 5], "start": "09:00", "end": "18:00"}
  ],
  "handoff_windows": [
    {"weekdays": [1, 2, 3, 4, 5], "start": "09:00", "end": "18:00"}
  ],
  "holidays": []
}
```

`working_windows` задают business clock, `handoff_windows` — допустимые моменты
передачи. Фактические логи имеют приоритет над расписанием: реально сделанная
вечером или в выходной работа остаётся active и business fact. Holidays —
project-owned dated input; при их изменении обновляй calendar явно.

## Публикация, передача и межсессионная история

Публикация постановки и передача в разработку — разные точки. После первой или
повторной публикации запиши milestone, но не закрывай последний этап: поставь его
на `external_wait`, а при правках возобнови. Тогда новые active intervals
доплюсуются, а elapsed включает межсессионный разрыв и человеческие действия до
явной передачи.

```text
python3 {baseDir}/scripts/automation_timing.py milestone \
  --case-root "<case-root>" --kind publication \
  --evidence "<redmine-read-back-ref>"

python3 {baseDir}/scripts/automation_timing.py milestone \
  --case-root "<case-root>" --kind ready_for_handoff \
  --evidence "<analysis-ready-ref>"

python3 {baseDir}/scripts/automation_timing.py milestone \
  --case-root "<case-root>" --kind development_handoff \
  --evidence "<explicit-handoff-ref>"
```

`ready_for_handoff` фиксирует момент, когда постановка действительно готова к
передаче. `development_handoff` допустим только после него, создаётся ровно один
раз и закрывает primary sample. Разрыв между точками измеряется отдельно: вечер,
выходные или ожидание человеческого действия не маскируются под анализ.
Если после публикации пришли правки, возобнови последний completed stage без
переписывания прежнего факта:

```text
python3 {baseDir}/scripts/automation_timing.py reopen \
  --case-root "<case-root>" --stage P07 \
  --evidence "<change-request-ref>"
```

После правок снова выполни `stop`, зафиксируй следующую publication revision,
новую ready revision и только затем development handoff. Active накапливает
новые интервалы, raw calendar elapsed считается от первого старта до handoff.

Первый handoff — жёсткая правая граница основного sample. Ожидание, пока
разработчик начнёт работу или вернётся с вопросами, после этой точки не входит
ни в active, ни в elapsed постановки. Если после handoff появились новые данные
и нужен доанализ, создай новый follow-up case в момент фактического возобновления
работы. `work-metrics` помечает его `post-handoff-followup` и связывает через
`parent_id`; основной `timing_model.py` такой sample не принимает. Это оставляет
follow-up доступным для отдельной будущей аналитики, не превращая полгода
ожидания разработки в полгода анализа.

Для переноса между сессиями/харнесами сформируй last-known checkpoint:

```text
python3 {baseDir}/scripts/automation_timing.py checkpoint \
  --case-root "<case-root>" --write "<checkpoint.json>"
```

При включённом task-note adapter заменяет в Singularity один timing-блок и
читает его обратно после `start|pause|resume|stop|milestone`. Checkpoint содержит
revision, ledger hash, active, elapsed и state. Новый координатор сравнивает его
с локальным ledger:

```text
python3 {baseDir}/scripts/automation_timing.py reconcile \
  --case-root "<case-root>" --external-checkpoint "<read-back.json>"
```

`local_ahead|local_clock_advanced` разрешают обновить внешний снимок.
`external_ahead` означает лишь partial recovery, а одинаковая revision с разным
ledger hash — конфликт без молчаливой перезаписи.

При `timing_history=passport` forecast, публикации, development handoff и итоговая
calibration append-only записываются также в историю паспорта:

- local ledger — полный машинный event log;
- паспорт — долговечная история смысловых точек;
- Singularity — быстро доступный последний снимок.

Старт этапа:

```text
python3 {baseDir}/scripts/automation_timing.py start \
  --case-root "<case-root>" --stage P03
```

Пауза одного этапа или всех активных этапов:

```text
python3 {baseDir}/scripts/automation_timing.py pause \
  --case-root "<case-root>" --reason user_pause

python3 {baseDir}/scripts/automation_timing.py pause \
  --case-root "<case-root>" --reason limit_exhausted
```

Допустимые причины: `user_pause`, `limit_exhausted`, `external_wait`,
`interrupted`. Active timer останавливается, raw calendar elapsed продолжает идти.

### Явное отложенное состояние

Если пользователь явно не планирует продолжать work item, не оставляй его
обычной паузой. При `deferred_state=enabled` сначала выполни project projections
и read-back, затем запиши:

```text
python3 {baseDir}/scripts/automation_timing.py defer \
  --case-root "<case-root>" \
  --reason "<why work is intentionally out of WIP>" \
  --evidence "<user-or-tracker-ref>" \
  --projection-readbacks "<readbacks.json>"
```

Команда останавливает active stages и исключает интервал из обучаемого business
elapsed, но raw calendar elapsed сохраняет полный исторический срок. Внешний
project adapter может перевести tracker в deferred status, добавить личный
task-manager tag и вернуть задачу в backlog. Core хранит только provider-neutral
read-backs. Каждый defer read-back может содержать `previous_state` — JSON-снимок
канонического статуса, tags и binding до изменения. Он остаётся в append-only
`case_deferred` event и служит основанием для точного восстановления, а не для
безусловного перевода в заранее выбранный статус.

Возобновление:

```text
python3 {baseDir}/scripts/automation_timing.py resume \
  --case-root "<case-root>"
```

Для обычной stage pause `--evidence` не нужен. Для deferred case передай
`--evidence "<resume-ref>"` и при внешних проекциях
`--projection-readbacks "<restored-readbacks.json>"`. Resume возвращает
состояние до откладывания; project adapter восстанавливает сохранённые внешние
status/kanban/tag facts и читает их обратно.

Завершение:

```text
python3 {baseDir}/scripts/automation_timing.py stop \
  --case-root "<case-root>" --stage P03 --status completed
```

Остановка этапа во время паузы разрешена: незакрытый pause interval попадает
только в elapsed.

## Progress не зависит от таймера

Checklists сохраняют stable `Pxx-Cxx` и completion barriers при включённом или
выключенном времени. Policy `disabled` не записывает длительности, но позволяет
`start/begin/check/stop` менять progress state. Policy `fine` остаётся portable
default; `milestones|off` применяются только по явной user/project настройке.

Перед содержательной работой:

```text
python3 {baseDir}/scripts/automation_timing.py begin \
  --case-root "<case-root>" --stage P03 --item P03-C02
```

Сразу после выполнения `done_when`:

```text
python3 {baseDir}/scripts/automation_timing.py check \
  --case-root "<case-root>" --stage P03 --item P03-C02 \
  --evidence "<artifact-or-check-ref>"
```

Для внешней галки добавь system/item/read-back. Для user-owned пункта требуется
`--user-confirmed`. Не откладывай синхронизацию до конца этапа: галки нужны и
человеку для видимого прогресса, и машине как completion barriers.

## Post-facto recovery

Старые `agent-ledger.json` позволяют восстановить только нижнюю границу:

```text
python3 {baseDir}/scripts/timing_model.py recover \
  --agent-ledger "<case-root>/agent-ledger.json" \
  --write "<case-root>/timing-recovery.json"
```

Такой результат имеет `coverage: partial`, `quality: recovered_lower_bound` и
`training_eligible: false`: логи вызовов не доказывают границы всей работы,
паузы пользователя и ожидание лимитов. Он годится для ручной ретроспективы, но
не загрязняет модель проекта.

Для полного post-facto восстановления по нескольким журналам используй
`work-metrics`, описанный выше. Legacy `recover` намеренно остаётся узким
fallback одного `agent-ledger.json` и не изображает знание о межсессионных
паузах.

## Совместимость

- legacy `required|optional` plan сохраняет старые трёхточечные estimates и
  одноконтурный wall-clock;
- новый `measured` plan не содержит оценок модели и включает dual timer;
- новый `disabled` plan ведёт только progress;
- отсутствие нового execution-preferences snapshot означает legacy semantics.

Проверка:

```text
python3 {baseDir}/scripts/automation_timing.py validate \
  --case-root "<case-root>" --final
python3 {baseDir}/scripts/automation_timing.py summary \
  --case-root "<case-root>" --json
```
