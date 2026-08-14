# Compact pipeline постановки

Используй этот workflow только для одного связного смыслового контура. Если
задача требует нескольких независимо проверяемых блоков, переключись на
`block-pipeline.md` до начала системного анализа.

## Фаза 1. Инициализация или возобновление

**Вход:** запрос пользователя, выбранные `profile_id`, `route_id`, закреплённые
`method-context.json/md`, `mode-decision.json` с `selected_mode=compact` и
approved planning handoff либо явно выбранный `--intent review`.

1. Найди существующий case package текущего результата.
2. Если его нет, проверь decision через `case_pipeline.py init` в режиме
   `compact` с точным `--intent` и `--cwd` в рабочей области координатора, не в
   каноническом каталоге проекта. Если decision выбирает `block`, перейди в
   block pipeline.
3. Если есть частичный прогон, проверь свежесть источников и продолжай с первой
   незавершённой фазы. Одновременно прочитай `automation-timing.json`: running
   stage продолжается с исходным `started_at`, terminal stage не запускается
   повторно без новой planning revision. Не запускай готовые роли повторно без
   причины.
4. Определи режим: `create`, `update`, `review`, `decompose` или `architecture`.

**Выход:** decision и method context связаны с manifest; `ledger.json`,
`automation-timing.json`, `kernel.md` и следующая фаза определены.

Сквозное правило выполнения: перед входом в каждый approved `Pxx` запусти
`automation_timing.py start`; после его exit criteria и проверки — `stop --status
completed`. При terminal failure закрой этап `failed|blocked|cancelled` с причиной.
При `user_pause|limit_exhausted|external_wait|interrupted` сразу вызови `pause`,
после продолжения — `resume`: active остановится, elapsed продолжит идти. При
timing disabled те же stage-команды ведут progress без длительностей. Не запускай
task-manager timer и не переноси эти данные в checklist: точный контракт задан в
`{baseDir}/references/automation-timing.md`.

Перед содержательной работой вызови `automation_timing.py begin` для выбранного
`Pxx-Cxx`; выбирать пункты разрешено не по порядку списка. Если другой пункт уже
`in_progress`, второй `begin` допустим только с честным `--parallel-reason` для
реально одновременной независимой работы. Как только `done_when` начатого пункта
выполнен, немедленно останови обычный переход: для внешнего checklist поставь
галку через project adapter и выполни read-back, затем вызови
`automation_timing.py check`. До успешного `check` не объявляй пункт или гейт
закрытым и не запускай следующую последовательную роль. `stop --status completed`
не пройдёт при pending или `in_progress` обязательном пункте.
Пункт с `completion_owner: user` не начинай и не отмечай: подготовь handoff,
дождись пользовательской галки, прочитай её обратно и только затем синхронизируй
ledger через `check --user-confirmed`.

## Фаза 2. Сбор evidence pack

**Вход:** coordinator manifest у оркестратора, `role-manifest.json` у роли и
проектный профиль.

1. Прочитай ближайшие проектные инструкции и профиль.
2. Собери только источники, нужные текущей задаче. Объединяй поисковые паттерны;
   не делай N×M обход файлов.
3. Для изменчивых фактов используй актуальный read-back канонического источника.
4. Отдели факты от старых постановок, сообщений, гипотез и примеров.
5. Прочитай preliminary `PUS-*`/`PDOD-*` из planning handoff только как
   гипотезы: они направляют проверку, но не подменяют evidence.
6. Не выполняй внешние записи. Недоступность источника фиксируй как gap.
7. Если planning coverage уже закрыт, не открывай общий research заново.
   Дополнительный поиск допустим только по принятому `blocker|major` с точной
   evidence-дырой и stop condition из
   `{baseDir}/references/convergence-contract.md`.

**Выход:** intake/evidence pack достаточен для анализа либо назван один
блокирующий пробел.

## Фаза 3. Системный анализ

**Вход:** `role-manifest.json`, профиль, закреплённые `method-context.json/md` и evidence
pack.

1. Получи bounded package командой `case_pipeline.py context --role
   system-analyst --contract-surface solution-boundary --contract-surface
   diagram --contract-surface reader-projection` без `--block` и запусти
   `vigers-system-analyst` в свежем контексте.
2. Передай контракт роли, закреплённую методическую выжимку и входные
   артефакты; не заменяй выжимку пересказом маршрута.
3. Включи `business-context`, если неизвестна потребность, участники, процесс,
   эффект или владелец решения.
4. Проверь, что аналитик не выдал предположение за факт и не принял решение за
   бизнес-владельца.
5. Проверь disposition каждого planning `PUS-*`/`PDOD-*`; разрешены
   `confirmed|changed|split|rejected` и новые элементы, найденные полным анализом.
6. Проверь final solution boundary по
   `{baseDir}/references/solution-boundary-contract.md`: disposition planning
   probe, подтверждённый горизонт, current scope, seams, deferred и triggers.
   Сохрани принятый JSON block в существующий `decisions.md`; отдельный артефакт
   не создавай.
7. Проверь `simplicity_authoring`: модель строилась от минимального текущего
   решения после полного понимания потока; зафиксированы `root_owner`,
   `chosen_rung`, protected-floor check и применимые
   `ceiling|revisit_trigger|upgrade_path`. Каждый спорный статус, сущность,
   настройка, dimension доступа или вариант имеет текущую semantic-ссылку, а
   необоснованное удалено/отложено без потери доказанной extension seam.
8. Проверь `diagram_gate` по `{baseDir}/references/diagram-contract.md`: каждая
   сложная поверхность имеет решение `required|not-required|blocked`, вопрос,
   подходящий тип представления, source IDs и решение о декомпозиции. Не
   считай объём текста самостоятельным основанием для диаграммы.
9. Сохрани возвращённую модель требований в case package.

Если аналитик во время прохода вернул доказанный `status: replan` с
`planning_delta`, немедленно останови текущий pipeline и перейди в фазу
replanning из `planning-pipeline.md`. Не сохраняй частичную модель требований и
не исправляй approved plan внутри текущего case. Отдельный user approval нужен
для material delta; local delta проходит coordinator gate по строгим критериям.

**Выход:** требования, AC, DoD, пробелы и архитектурное влияние трассируются к
источникам и цели.

## Фаза 4. Архитектурное решение

**Вход:** модель требований с секцией архитектурного влияния.

1. Применяй архитектурный гейт из `SKILL.md` и профильные триггеры.
2. Горизонты `tactical` и `generalized-capability` всегда включают design gate.
   `bounded-systemic` сам по себе архитектора не требует.
3. Если гейт не сработал, зафиксируй `architecture_gate.required: false`.
4. Если сработал, получи `context --role solution-architect --role-mode design
   --contract-surface solution-boundary --contract-surface diagram
   --contract-surface reader-projection` и запусти `vigers-solution-architect`
   в свежем контексте.
5. Не позволяй архитектору менять бизнес-цель или придумывать требования.
6. Проверь `simplicity_authoring` архитектора: каждый новый компонент,
   хранилище, событие, очередь, конфигуратор или иной механизм имеет текущий
   requirement/constraint ref; указаны `chosen_rung`, protected-floor check и
   предел осознанного упрощения; необоснованное удалено или отложено.
7. `decision-required` вынеси пользователю, только если выбор существенно
   меняет scope, необратимость, стоимость или архитектурный канон.

**Выход:** архитектура не требуется либо существует согласованная
architecture design note с ограничениями для редактора.

## Фаза 5. Редактура постановки

**Вход:** модель требований, architecture design note при наличии, профиль и
проектный шаблон.

1. Получи `context --role spec-editor --role-mode document --contract-surface
   diagram --contract-surface reader-projection` и запусти `vigers-spec-editor`
   в свежем контексте.
2. Не передавай ему сырой диалог, если смысл уже зафиксирован артефактами.
3. Редактор собирает документ, но не закрывает открытые вопросы и не добавляет
   новые требования, поля, числа, технологии или архитектурные решения.
   Он не возвращает элементы, удалённые или отложенные принятым
   `simplicity_authoring`.
4. Редактор реализует принятый `diagram_gate` и возвращает матрицу
   `diagram question → source_ids → section → working source → current stage →
   QA render → publication gate`.
   Перегруженные схемы декомпозируются, а не уменьшаются до нечитаемого вида.
5. Редактор применяет `references/reader-projection-contract.md`: публикует
   только reader-facing смысл, делает все semantic references точными локальными
   ссылками, оставляет прямые trace edges и отделяет живую приёмку от developer
   self-check. UI-сценарий называет экран входа; подтверждённый путь указывается,
   если source описывает навигацию, а для уже открытого экрана не
   реконструируется. Переход на новую поверхность назван, поля сопоставляют
   видимую подпись с technical ID, неизменный путь не повторяется. Каждый UI AC
   содержит прямую ссылку на точный сценарий/ветвь с этим контекстом либо
   собственные подтверждённые экран/точку входа и минимальный маршрут. API-,
   batch- и system-only AC называют сценарий или системную точку входа без
   фиктивного UI. Сырой reasoning corpus и служебные IDs ему не передаются.
6. Координатор сохраняет текст как draft, не публикуя его.
7. Если profile требует working projection, обнови каждый связанный target этим
   draft через project adapter. Явно пометь unresolved и непроверенные разделы,
   выполни read-back и зарегистрируй `projection-update --source draft`. Для
   project file используй `--evidence-kind local_file`; для tracker/wiki сохрани
   JSON receipt проектного адаптера и используй
   `--evidence-kind external_readback`. Это рабочая
   проекция, а не финальная публикация.

**Выход:** полный проектный черновик и список unresolved placeholders.

## Фаза 6. Авторские контрольные проходы

**Вход:** черновик.

1. Сначала выполни machine/document precheck, чтобы не тратить контрольный
   проход на структурно сломанный draft.
2. Проверь границу на оба запаха `particular-case` и
   `speculative-generalization`, затем независимо от profile выполни ровно один
   полный контроль `simplicity-spec` по собранному решению.
3. Контроль проверяет необходимость элементов решения, а не красоту текста, и
   не удаляет доказанную extension seam. Запиши `clean|corrected|decision-required`
   как evidence существующего `author_passes`; новую роль и review gate не
   создавай. В статусе/выдаче покажи человеку этот итог одной строкой, а для
   `corrected` — короткую дельту; не вставляй служебный отчёт в постановку.
4. Findings о сценариях, правилах, данных и состояниях верни аналитику;
   архитектурные — архитектору. Редактор применяет только принятую bounded
   дельту. Не открывай общий research и не проси «пересмотреть всё».
5. После собственной bounded-коррекции не запускай второй полный simplicity
   pass. Поздняя правка получает только delta-check, если вводит новый элемент
   решения; изменение бизнес-смысла, scope, публичного контракта или канона —
   `decision-required`.
6. Выполни остальные обязательные проходы профиля в указанном порядке.
   Логический контроль проверяет связность и трассировку; стилевой не меняет
   факты, идентификаторы и решения.
7. После каждого изменения повторно проверь затронутую трассировку.
8. После существенного author-pass обнови обязательную working projection и
   запиши новый read-back хеш. Косметические изменения можно объединить одним
   update текущего gate.
9. Для каждой required-диаграммы сверь смысл с source IDs, отрендери способом
   текущей рабочей стадии из profile `diagram_delivery` и прочитай фактический
   render на целевой ширине. Не создавай publication render/source до явного
   publication gate. Обрезка,
   наложения, неразличимые подписи, сломанные стрелки либо одна перегруженная
   схема вместо требуемой декомпозиции блокируют author gate.
10. Закрой `author_passes` только после machine validation boundary-блока и
   успешного visual read-back всех required-диаграмм.
11. До независимого глобального review выполни machine check reader projection.
    Не расходуй reviewer pass на draft с внутренними IDs, dangling/plain refs
    или нарушенным project document contract.

**Выход:** черновик прошёл проектные author gates и готов к независимому ревью.

## Фаза 7. Независимое ревью

**Вход:** финальный черновик author-pass, evidence pack, модель требований,
закреплённый method context, профиль и architecture design note.

1. Получи bounded package командой `case_pipeline.py context --role
   spec-reviewer --role-mode global|final --contract-surface solution-boundary
   --contract-surface diagram --contract-surface reader-projection
   --contract-surface project-rules` без `--block`, запусти fresh reviewer и
   передай закреплённые `method-context.json/md`.
2. Не передавай рассуждения редактора, самооценку и предыдущие review findings.
3. Требуй findings по handoff-контракту: место, доказательство, последствие и
   минимальное исправление.
4. Отбрось вкусовщину и недоказанные замечания.
5. Требуй независимую проверку `diagram_gate`: покрытие сложных поверхностей,
   семантическое соответствие source IDs, корректность декомпозиции и evidence
   чтения финального render.
6. В `high` отдельным fresh reviewer `project-conformance` проверь локальные
   соглашения. В `standard` один reviewer `final` покрывает global и применимые
   project surfaces; report объявляет `covered_gates: [integration_review,
   global_review, project_conformance]`. В `lite` semantic
   reviewer запускается только при обнаруженном изменении смысла.
7. Если применимых поверхностей нет, зафиксируй gate `project_conformance` как
   `not_required` с причиной; иначе сохрани evidence и закрой findings.
8. Для каждого отчёта проверь reported counts, `research_reopen` и
   `gate_recommendation`. После disposition координатор считает open counts.
   Координатор записывает `revise` только при открытом принятом `blocker|major`;
   residual minor не переоткрывают гейт.
9. После исправления повторяй только затронутый semantic, project, architecture
   или diagram gate. Полный global pass нужен лишь при изменении цели, границы,
   публичного контракта или сквозной логики.

**Выход:** независимый global review и project-conformance report.

## Фаза 8. Архитектурная проверка

**Вход:** готовый черновик и `architecture_gate.required`.

1. Если гейт не сработал и reviewer не нашёл архитектурного влияния, пропусти.
2. Иначе получи `context --role solution-architect --role-mode conformance
   --contract-surface solution-boundary --contract-surface diagram
   --contract-surface reader-projection` и запусти новый экземпляр
   `vigers-solution-architect`.
3. Не передавай ему design-рассуждения; передай решение как утверждённый
   артефакт, проектный канон, evidence pack и draft.
4. Классифицируй результат:
   - `conform` — соответствует;
   - `decision-required` — осознанно меняет канон, нужен ADR/решение;
   - `conflict` — случайно противоречит канону.

**Выход:** архитектурное заключение либо документированное отсутствие гейта.

## Фаза 9. Разбор замечаний

**Вход:** review report и architecture conformance.

1. Координатор классифицирует каждое замечание: `accepted`, `rejected` или
   `user-decision`. Принятое замечание сначала имеет resolution `open`, после
   обработки — `corrected` либо допустимый для `minor` статус `residual`.
2. Открытые принятые `blocker/major` передай новому запуску редактора вместе с
   точными ограничениями. Не проси «улучшить всё» и не повторяй весь pipeline.
3. Выполни только затронутые deterministic checks, author gates и review gate.
   Новый research разрешён лишь для finding с `remediation: targeted-research`
   и полным набором полей convergence-контракта.
   После принятого существенного исправления синхронизируй working projection и
   только затем продолжай следующий gate.
4. Если остались только `minor`, выполни не более одного пакетного polish-pass
   на текущий review gate либо зафиксируй их как residual. Затем перейди дальше
   без нового полного reviewer.
5. Если тот же `blocker/major` остался после двух точечных циклов, верни
   `user-decision`, а не запускай третий круг.

**Выход:** открытых принятых `blocker/major` нет либо требуется явно
сформулированное решение; residual minor зафиксированы и не блокируют выдачу.

## Фаза 10. Выдача и публикация

**Вход:** проверенный документ.

1. Проверь, что все review gates имеют нулевые `open_blocker/open_major`, а
   residual minor перечислены как остаточный риск. Затем выдай готовый текст,
   существенные допущения, открытые решения и остаточный риск.
2. Сохраняй в канонический путь проекта только если это входит в запрос.
3. Внешние трекеры, базы знаний и статусы изменяй только по явной просьбе и
   через профильный инструмент.
4. После внешней записи выполни read-back. Превью или HTTP 200 не доказывают
   корректную публикацию. При measured timing зафиксируй `milestone
   --kind publication`. Если после него пришли правки, выполни `reopen` последнего
   completed stage, затем снова `stop` и новую publication revision.
5. Явную передачу в разработку не выводи из факта публикации. После отдельного
   подтверждения пользователя запиши `milestone --kind development_handoff`,
   а при включённом timing и доступном `work-metrics` сначала согласуй все
   объявленные case-related журналы разных сессий/харнесов. Передавай
   `--logs-complete` только при доказанной полноте; eligible reconciliation
   добавь в `timing_model.py update`, partial сохрани лишь для ретроспективы.
   Затем сформируй calibration record и обнови project timing model. При включённом
   passport history append-only добавь forecast, публикации, handoff и delta;
   при task-note projection обнови last-known checkpoint Singularity и прочитай
   обе записи обратно.
6. После первого development handoff не переоткрывай основной timing sample.
   Новые факты от разработки оформляй отдельным follow-up case с новым началом
   в момент фактического возобновления анализа и ссылкой на исходный case.
   Ожидание между handoff и follow-up в длительность анализа не включай.

**Выход:** пользователь получил проверенный результат; состояние внешних
систем описано фактически.

Перед выдачей закрой последний active `Pxx`, затем выполни
`automation_timing.py validate --final` и `case_pipeline.py validate --final`.
До development handoff финальная проверка постановки допустима, но sample ещё не
попадает в timing model. Forecast не передавай роли и не добавляй в постановку;
при task-note projection он остаётся только в личном плане.
Гейты, которые обоснованно не применимы, должны иметь состояние `not_required`,
а не `pending`.
