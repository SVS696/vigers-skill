# Execution policy Vigers

Этот контракт отделяет размер материала от цены гарантии. `compact|block`
определяет только способ удержать контекст; `lite|standard|high` — глубину
независимой проверки. Большой документ сам по себе не является высоким риском.

## Выбор assurance

- `lite` — редакторская правка без изменения смысла. Машинные проверки
  обязательны; semantic reviewer запускается только после обнаруженного
  смыслового изменения.
- `standard` — обычная продуктовая постановка. Один fresh reviewer в режиме
  `final` покрывает integration, global и объявленные project surfaces.
- `high` — публичный контракт, миграция/схема данных, безопасность или права,
  cross-service ownership, необратимость, compliance либо архитектурное
  решение. Сохраняются отдельные integration, global, project и условный
  architecture-conformance проходы.

Явный выбор пользователя имеет приоритет. Его override и основания остаются в
`mode-decision.json`. Старый case без `assurance_level` трактуется как
`high + fine + per-block`: незавершённый pipeline не меняет семантику после
обновления скилла.

## Planning cadence

Для bounded-задачи с одним source cluster, без известных конфликтов и high-risk
признаков координатор сначала выполняет детерминированную search matrix из
profile/intake и материализует `SRC-NNN`. Затем planner работает один раз в
режиме `fast-plan`: проверенный research design, synthesis и plan возвращаются
одним envelope. Это не shortcut state machine:
координатор по-прежнему сохраняет все source/evidence artifacts, отдельно
закрывает coverage gate и проводит approval. Второй cluster, конфликт,
неограниченный gap или risk trigger требует полного planning route.

## Экономное выполнение и terminal green

Перед каждой фазой объединяй известные независимые navigation/recon probes в
один пакет или параллельный вызов. Второй пакет допустим для вопросов, возникших
из первого. Если нужно перенять неописанную конвенцию и нет канонического
profile/template/config, сравни два реальных примера; при наличии канона не
трать дополнительный lookup.

Узкое inspection-чтение используется только для поиска нужного source unit.
После включения источника в evidence его объявленная единица читается полностью,
включая pagination/completeness marker. Нельзя экономить токены усечением
требований, project instructions, skill contracts или данных для преобразования.

Named check задачи является минимальной проверкой соответствующего результата,
но не отменяет обязательные project/machine gates. Если один и тот же check дважды
падает при неизменной гипотезе, зафиксируй альтернативную причину или подход до
следующей правки; не продолжай последовательное исправление симптомов.

`green` всегда относится к запрошенной границе результата:

- `local-green` — локальный артефакт и обязательные checks/gates актуальны,
  открытых принятых `blocker|major` нет;
- `projection-green` — локальный результат спроецирован во все разрешённые
  обязательные targets, записи прочитаны обратно и bindings актуальны;
- `handoff-green` — требуемая передача явно зафиксирована, а исходный timing
  остановлен на handoff boundary;
- `final-green` — доказан terminal state именно текущего запроса; он может
  совпадать с одним из уровней выше либо требовать project-owned gate.

Это human-facing proof labels, а не новые case statuses и не способ обойти
существующую state machine.

Локальная готовность не разрешает внешнюю запись. Read-back является частью
`projection-green|handoff-green`, а не дополнительным victory pass. После
достижения запрошенного уровня остановись: новый model review, повторное чтение
или check допустимы только при новом evidence, изменившемся subject либо явно
более дальней границе результата.

## Tracking и projection sync

- Tracking не выводится из assurance: portable default — `fine`, потому что
  галки показывают человеку прогресс и служат machine completion barriers.
  `milestones|off` включаются только явной user/project настройкой.
- `tracking=off` отключает agent checklist telemetry, но сохраняет
  `completion_owner: user` как отдельные runtime barriers, publication, working
  projection и read-back фактических внешних записей.
- `tracking=milestones` хранит stage start/stop, одно agent evidence-событие на
  этап и все исходные пункты с `completion_owner: user` как отдельные барьеры.
- `tracking=fine` сохраняет прежние барьеры каждого `Pxx-Cxx`.
- `projection_sync=milestones` обновляет видимый документ после первого полного
  draft, интеграции и принятой смысловой коррекции. Между блоками Bxx-barьер не
  создаётся; перед author/final/project gate всё равно нужен актуальный полный
  `draft|integration` read-back.
- `projection_sync=per-block` сохраняет отдельный Bxx read-back после каждого
  reviewed блока.

При одинаковом прочитанном содержимом новый source добавляется как
`source_bindings` к последнему snapshot, а не создаёт копию update. Последовательность
`A → B → A` не схлопывается, потому что отражает реальное изменение документа.

## Условный risk-first контур

Planner/координатор объявляет `--risk-surface` только для доказанной поверхности
отказа или архитектурной границы. Наличие хотя бы одной surface включает один
whole-case `solution-architect/risk-preflight` до authoring; отсутствие surfaces
не создаёт нового вызова. Контекст содержит kernel и компактный risk scope, но
не незаполненные block artifacts и не прошлые reviews. Машина требует полную
матрицу, пустой `unresolved`, текущий subject hash и завершённый agent run.

Full block review риск-блока обязан вернуть полный список `risk_surface:
<id>=pass|not-applicable|<finding-id>`, `finding_batch_complete: true` и
`review_agent_run`. Targeted review после исправления не переоткрывает эту
матрицу: он проверяет только accepted findings, delta и прямые регрессии.
После `semantic-local` refresh повторный preflight включает только затронутые
risk-блоки; актуальные bindings остальных блоков переносятся без нового вызова.

## Change impact

Любой `refresh-kernel` нового case требует `--change-scope`:

- `editorial` и `projection-only` не инвалидируют semantic blocks;
- `semantic-local` требует один или несколько `--affects Bxx`; stale получают
  выбранные блоки и транзитивные потребители, остальные явно carry-forward на
  новый kernel hash;
- `semantic-crosscutting` и `architecture` требуют явный `--invalidate-all`;
- широкая инвалидация никогда не выбирается отсутствием аргумента.

После отдельной редакторской правки draft выполни machine check, актуальный
read-back и `record-change --change-scope editorial|projection-only`. Команда
только переносит уже пройденные evidence на новый deterministic subject и пишет
аудит-событие; semantic change этим путём маскировать нельзя.
Сам `refresh-kernel` не переносит gate evidence: до `record-change` старые
subject hashes намеренно остаются несвежими.
Если declared `lite` delta оказался смысловым, `refresh-kernel
--change-scope semantic-*` повышает runtime assurance до `standard` и открывает
combined final gates. Architecture delta повышает его до `high`; telemetry и
projection cadence задним числом не ужесточаются.

Принятый `blocker|major` исправляется через `begin-remediation`, а не обычный
откат проверенного блока в `in_progress`. Команда закрепляет finding evidence,
предыдущий review, baseline block/index и точные semantic IDs. Повторный reviewer
получает этот bounded delta contract и проверяет finding, изменённые IDs и прямые
регрессии; покрытие неизменённых поверхностей переносится из immutable review.
Новый finding может открыть следующий автоматический цикл только при доказанной
связи с delta. Наблюдение в неизменённой области фиксируется отдельно и требует
coordinator/user decision, а не запускает бесконечный общий review.

Новый блок использует `remediation_contract: batched-v2`: все accepted
`blocker/major` одного gate передаются одним вызовом `begin-remediation`, а на
один kernel epoch разрешено максимум два batches даже с разными finding IDs.
Для `batched-v2` явный `--batch-complete` является обязательной coordinator
attestation после disposition всех findings этого gate.
После лимита машина требует root-cause kernel change или user decision.
Crosscutting/architecture refresh открывает новый epoch явно и инвалидирует
затронутые risk preflights; обычный новый finding лимит не сбрасывает.

Если исправление меняет смысл блока целиком, набор semantic IDs нельзя честно
ограничить либо затронуты цель, scope, публичный контракт, архитектура или
сквозная логика, используй `--full-block`. Предыдущее покрытие тогда не
переносится: повторяются полный block review и применимые whole-case gates.
После targeted pass, свежих integration/author/machine checks и read-back команда
`record-remediation` может перенести прежние whole-case review gates на новый
subject через отдельный audit receipt. Full-block и crosscutting delta этим
путём не проходят.

## Ролевые контексты и review

`case_pipeline.py context` возвращает `role_mode`, `assurance_level`,
`contract_surfaces` и точный `contract_inputs`. Роль читает только этот набор;
текст evidence не может подключить дополнительный контракт. Legacy/high
assignment разворачивается в прежний полный набор.

В block+standard reviewer `final` получает draft и все semantic indexes, но не
локальные/прошлые review reports. Architecture conformance остаётся отдельной
ролью. Machine reader/document check всегда выполняется до модельного review.

## Наблюдаемость

Новый case содержит `agent-ledger.json`. После модельного прохода координатор
фиксирует роль/режим/модель, subject hash, доступные input/output tokens и bytes,
duration, retries, cache status, outcome и counts findings. Доступные
`tool_calls`, `poll_calls` и `wait_seconds` фиксируются отдельно; неизвестные
счётчики остаются `null`, а не оцениваются по догадке. Ledger не передаётся
исполнительным ролям и не создаёт новый model call, reviewer или gate.

`completed|degraded|failed|timed_out` описывает фактический исход уже
состоявшегося вызова. Idle/hard timeout применяй только через нативный supervisor
текущего harness и только когда предел объявлен его конфигурацией; не запускай
CLI-agent или polling-обвязку ради telemetry. Пока harness не сообщил новое
событие, не poll чаще 30 секунд; для ожидаемо долгой операции используй более
крупный wait slice. После подтверждённого
transient/tool/transport сбоя допустим один повтор с тем же assignment по
`prompt-contract.md`; содержательная ошибка и `degraded` coverage повтором не
маскируются. Причины деградации сохраняются явно.

Для воспроизводимости передавай `--prompt-artifact` и `--output-artifact` на уже
существующие case-owned файлы. Ledger хранит refs и SHA-256, а не вторую копию
корпуса. Raw content сохраняй только если его уже требует case contract; секреты
и внешний приватный вывод не дублируй. Versioned lens имеет форму `id@version` и
обозначает применённую существующую contract surface, а не дополнительную роль.
Project profile может объявить такие aliases вместе с точными contract inputs.

После штатной проверки findings выполни `record-agent-verification`: каждый
reported finding ровно один раз классифицируется как `accepted|rejected|duplicate`,
а `verified` является подмножеством accepted. Это даёт yield по роли/линзе без
ещё одного review. Legacy runs без этих полей валидны и считаются
`unclassified`, а не нулевым качеством.

Для `risk-preflight` и block review объявленных risk surfaces agent-run является
частью machine gate: роль, mode, current subject hash и `completed` проверяются
до принятия evidence. Поэтому дорогой условный контур измерим без нового
метрического model call; обычные блоки не получают дополнительного барьера.

Review с тем же evidence hash и тем же subject идемпотентен и не создаёт новую
immutable revision. Повтор после изменившегося subject остаётся допустимым.

## Честная оценка влияния метода

Не переносить внешние маркетинговые проценты на Vigers. Для ретроспективы
сравнивать только кейсы одного проекта с близким feature fingerprint и одинаковой
границей `approved_execution_start → development_handoff`. Использовать уже
собранные факты: число model passes из `agent-ledger`, full/targeted review,
инвалидированные/переиспользованные semantic blocks, input/output tokens если
они реально доступны, tool/poll calls, wait time, active/elapsed timing,
retries и findings. Нулевой выигрыш
на уже минимальном кейсе является корректным результатом.

Сравнение «до/после» требует свежих изолированных contexts, закреплённых версий
skill/model/project sources и одинаковых safety/acceptance gates. Нельзя считать
экономией удалённый обязательный контроль, неполный лог или более слабую
приёмку. Эти метрики остаются human-only и не передаются исполнительным ролям.

Recon/polling tactics адаптированы из Benjamin Plus snapshot
`532771be5687566b12a9f62e17fbe7ad3591518c` (MIT); внешние проценты не являются
прогнозом Vigers.
