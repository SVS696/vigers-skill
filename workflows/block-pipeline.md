# Block pipeline постановки

Этот workflow обрабатывает крупную постановку по семантическим контрактам. Его
машинная истина координатора — закреплённый method context, `manifest.json` и
`ledger.json`; роль получает timing-free `role-manifest.json`;
`status.md` только человекочитаемое представление.

## Фаза 1. Инициализация или возобновление

**Вход:** запрос, выбранные `profile_id`, `route_id`, рабочий `case-root`,
`method-context.json/md`, `mode-decision.json` с `selected_mode=block` и
approved planning handoff либо явно выбранный `--intent review`.

1. Если case отсутствует, проверь decision и method context, затем создай его
   командой `case_pipeline.py init` в режиме `block` с точным `--intent` и
   `--cwd`. Несовпадение режима, профиля, маршрута или выжимки — ошибка входа,
   а не повод переписать файлы вручную.
2. Если case существует, выполни `status`, затем `validate` и продолжай с
   первого незавершённого блока или гейта. Прочитай `automation-timing.json`:
   running stage продолжается с исходным `started_at`, terminal stage не
   запускается повторно без новой planning revision.
3. Не перезапускай готовую роль, пока её результат свеж относительно kernel.
4. Не размещай runtime case в каноническом каталоге публикации и не коммить его,
   если профиль прямо не требует обратного.

**Выход:** состояние читается без истории чата; известны следующий шаг и active
automation stage.

Сквозное правило выполнения: planning stages `Pxx` и semantic blocks `Bxx` —
разные DAG. Перед фактическим входом в approved `Pxx` запусти
`automation_timing.py start`; после exit criteria и проверки — `stop --status
completed`. Не создавай отдельный таймер на каждый `Bxx`, если planning stage не
делит их явно. При terminal failure используй `failed|blocked|cancelled` с
причиной. При паузе пользователя, исчерпании лимита, внешнем ожидании или
interruption вызови `pause --reason ...`, затем `resume`; active исключает паузу,
elapsed включает её. При timing disabled команды сохраняют progress без
длительностей. Полный контракт: `{baseDir}/references/automation-timing.md`.

Перед содержательной работой вызови `automation_timing.py begin` для выбранного
`Pxx-Cxx`; порядок списка не является dependency. Если другой item уже
`in_progress`, второй `begin` допустим только с явным `--parallel-reason` для
реально одновременной независимой работы. Как только `done_when` начатого пункта
выполнен, прерви обычный переход: внешнюю галку обнови через project adapter и
прочитай обратно, затем вызови `automation_timing.py check`. До успешного
`check` не объявляй пункт/гейт закрытым и не запускай следующую последовательную
роль. Пакетное проставление галок запрещено; completed stage не может содержать
pending или `in_progress` обязательный пункт.

## Фаза 2. Evidence pack и kernel

**Вход:** профиль и источники задачи.

1. Собери evidence по правилам compact pipeline.
2. Перенеси preliminary `PUS-*`/`PDOD-*` из planning handoff в evidence как
   гипотезы для проверки, а не как факты kernel. Назначь каждому затронутые
   semantic blocks; итоговая интеграция должна дать disposition
   `confirmed|changed|split|rejected`.
3. Запиши в `kernel.md` только общие для всех блоков факты:
   цель, scope, словарь, инварианты, подтверждённые решения, ограничения и
   открытые решения.
4. Не превращай kernel в сокращённую постановку. Детали одного блока остаются
   в его артефакте.
5. После изменения kernel выполни `refresh-kernel` с обязательным
   `--change-scope`. Для `semantic-local` укажи seed через `--affects`; для
   `semantic-crosscutting|architecture` используй явный `--invalidate-all`.
   Пустой selector запрещён; незатронутые блоки carry-forward на новый hash.
6. Зафиксируй гейт `evidence` только после проверки источников.

После закрытия evidence/coverage не запускай новый общий research. Дополнительный
поиск разрешён только по принятому `blocker|major` с `remediation: targeted-research`,
точной evidence-дырой, целевыми источниками и условием
остановки из `{baseDir}/references/convergence-contract.md`.

Если любой аналитический block во время прохода возвращает доказанный
`status: replan` с `planning_delta`, немедленно останови его и не проталкивай как
kernel edit. Останови active `Pxx` как `blocked` с причиной `replanning required`
и выполни replanning workflow. Material delta требует повторного user approval;
local delta проходит coordinator gate. В обоих случаях продолжай в новом
case-root и свежих block contexts.

**Выход:** свежие `evidence.md` и `kernel.md`, revision зарегистрирован.

## Фаза 3. План семантических блоков

**Вход:** kernel, профиль и область результата.

1. Раздели работу по семантическим контрактам, а не заголовкам шаблона.
2. Каждый блок должен иметь один результат, 1–3 смысловых вопроса и обозримые
   зависимости. Обычно используй 3–8 блоков.
3. Добавь блоки командой `add-block` в порядке зависимостей. Для доказанных
   опасных поверхностей передай повторяемый `--risk-surface`; не объявляй risk
   только из-за размера блока или «на всякий случай».
4. Проверь DAG командой `validate`.
5. Если два блока владеют одним фактом, назначь владельца одному, а второму —
   ссылку через semantic ID.

**Выход:** полный DAG в `ledger.json`; каждый блок имеет card, index и review.

### Условный risk-first preflight

Если ни один блок не объявил risk surface, сразу переходи к фазе 4. Иначе до
первого `in_progress` один раз получи whole-case `context --role
solution-architect --role-mode risk-preflight`, запусти архитектора, запиши его
в `agent-ledger` с `subject_sha256` из context и сохрани полную JSON-матрицу.
Выполни `record-risk-preflight --evidence <path>`. Матрица обязана покрывать
каждую пару block/surface текущего `risk_scope`, содержать конкретные decisions
и пустой `unresolved`.
Это ранняя стабилизация связных failure semantics, а не ещё один review обычной
задачи.

Если новую риск-поверхность обнаружили уже в раннем авторинге, выполни
`declare-risk --id Bxx --risk-surface <id> --reason <evidence>`. Машина поставит
блок на паузу и потребует обновлённый preflight перед продолжением. Для уже
проанализированного блока сначала нужен явный semantic/architecture kernel refresh.

## Фаза 4. Поблочный системный анализ

**Вход:** один `ready` блок, kernel, закреплённый method context, evidence и
результаты его зависимостей.

Для каждого доступного блока:

1. Переведи `planned → ready → in_progress`.
2. Получи допустимый набор входов командой `context --role system-analyst
   --contract-surface solution-boundary --contract-surface diagram
   --contract-surface reader-projection`.
3. Запусти новый `vigers-system-analyst` только на этот блок.
4. Сохрани смысловую модель в `blocks/Bxx.md`, а определения и трассировку — в
   `blocks/Bxx.index.json` по block-контракту.
5. Проверь `simplicity_authoring`: спорные сущности, статусы, настройки, поля,
   access dimensions и варианты имеют текущие semantic refs; зафиксированы
   `root_owner`, `chosen_rung`, protected-floor check и применимые пределы;
   необоснованное удалено или отложено без потери доказанной seam.
6. Сохрани локальные решения `diagram_gate` блока: вопрос, представление,
   source IDs и декомпозицию. Не проектируй общую «карту всего документа» из
   одного блока.
7. Оставь блок в `in_progress` до block-render: kernel snapshot фиксируется
   только после последней авторской правки блока.

Независимые блоки можно запускать параллельно ограниченными пакетами. Блоки с
зависимостями ждут состояния `reviewed` или `integrated` предшественников.
Каждый блок может добавить evidence к общей границе решения, но не создаёт свой
конкурирующий горизонт. Координатор сшивает финальный boundary-блок в
`decisions.md` после достаточного полного анализа.

**Выход:** каждый обработанный блок имеет нормализованную модель и semantic index.

## Фаза 5. Локальное решение и block-render

**Вход:** `in_progress` block с моделью/index и сработавший архитектурный гейт.

1. Если блок вводит локальное архитектурное решение, не покрытое risk preflight,
   получи `context --role
   solution-architect --role-mode design --contract-surface solution-boundary
   --contract-surface diagram --contract-surface reader-projection` и запусти
   отдельный architect; внеси принятое ограничение в `decisions.md`. При глобальном инварианте
   обнови kernel и выполни `refresh-kernel`.
   Горизонты `tactical` и `generalized-capability` также требуют этого gate;
   обычный `bounded-systemic` без других triggers — нет.
   До принятия design note проверь его `simplicity_authoring`: у каждого нового
   механизма есть текущий requirement/constraint ref, выбранный уровень
   лестницы, protected-floor check и применимый предел, иначе он удалён/отложен.
2. Получи `context --role spec-editor --role-mode block-render
   --contract-surface diagram --contract-surface reader-projection` и запусти
   editor: он оформляет только данный блок и не собирает финальный документ.
3. Не позволяй редактору создавать определения, которых нет в semantic index.
4. Если у блока есть required-диаграмма, редактор создаёт её как локальную
   derived view, связывает с source IDs и возвращает working source. QA следует
   рабочей стадии profile `diagram_delivery`; publication render и sidecar до
   явного publication gate не создаются. Финальный размер и межблочная
   декомпозиция повторно проверяются после интеграции.
5. Переведи блок в `analyzed`; оркестратор сохранит хэши block/index и kernel
   revision после всех авторских изменений.

**Выход:** блок готов к независимой локальной проверке.

## Фаза 6. Локальное независимое ревью

**Вход:** block artifact, index, kernel, закреплённый method context, evidence и
зависимости.

1. В `high` каждый блок требует fresh reviewer. В `standard` запускай его только
   для публичного контракта, migration/data, permissions/security, architecture,
   cross-service связи или неопределённого владельца. Для прочих блоков сохрани
   machine attestation `review_requirement: not-required`, не изображая PASS.
2. Для review получи `context --role spec-reviewer --role-mode block` с
   применимыми `--contract-surface` и запусти fresh reviewer без истории автора.
3. Для локальной required-диаграммы проверь соответствие semantic index и
   читаемость пробного render; не требуй межблочную обзорную схему раньше
   интеграции.
4. Сохрани findings или явный `PASS` в `reviews/Bxx.md`; отчёт обязан содержать
   reported counts, `research_reopen` и `gate_recommendation`. Disposition и open
   counts координатор фиксирует отдельно. Для risk-блока сначала запиши reviewer
   в `agent-ledger`, затем добавь `review_agent_run`, `review_scope: full-block`,
   `finding_batch_complete: true` и ровно одну строку `risk_surface` для каждой
   объявленной поверхности.
5. Собери все открытые принятые `blocker/major` этого gate в один пакет и вызови
   `begin-remediation --batch-complete` один раз:
   укажи стабильные finding IDs, evidence и точные semantic IDs. Обычный откат
   проверенного блока в `in_progress` запрещён, потому что он теряет прежнее
   покрытие. Исправь bounded delta новым editor, снова переведи блок в
   `analyzed`, затем вызови reviewer с `review_scope: targeted-remediation`.
   Reviewer получает immutable baseline/finding/coverage, проверяет finding и
   прямые регрессии и не открывает неизменённые поверхности заново.
   Если исправление переписывает смысл блока, меняет необъявленные IDs, цель,
   scope, публичный контракт или сквозную логику, перезапусти remediation с
   `--full-block` и выполни полный локальный и применимые whole-case review.
6. При minor-only выполни не более одного пакетного polish-pass для этого review
   gate либо запиши остаток как `residual`; новый полный reviewer не запускай.
7. После двух remediation batches текущего kernel epoch третий автоматический
   цикл запрещён даже для нового finding ID. Агрегируй повторяющийся класс
   проблемы в root-cause kernel change с явным impact либо верни
   `user-decision`. Иначе переведи блок в `reviewed`, когда открытых принятых
   `blocker/major` нет; residual minor переход не блокируют.
   Новый finding открывает следующий цикл только с `delta_relation:
   introduced|exposed-at-changed-boundary`; несвязанное наблюдение сохрани
   отдельно и не превращай в автоматический общий аудит.
8. При `projection_sync=per-block` сразу после `reviewed` проецируй block-render.
   При `milestones` пропусти Bxx-update: следующий read-back — после интеграции.
   В per-block проецируй принятый block-render во все обязательные
   working targets. Сохрани уже показанные разделы, добавь или обнови только
   затронутый смысл, а будущие разделы пометь как непроверенные. Выполни
   read-back и `projection-update --source Bxx`: `local_file` проверяется по
   реально прочитанному project file, `external_readback` — по сохранённому
   receipt проектного адаптера. Пока update не записан, новый semantic block не
   запускай.

**Выход:** каждый смысловой блок проверен независимо и свеж относительно kernel.

## Фаза 7. Семантическая интеграция

**Вход:** все обязательные блоки в `reviewed` и один проектный шаблон.

1. Получи `context --role spec-editor --role-mode integrate --contract-surface
   diagram --contract-surface reader-projection` без `--block` и запусти editor
   в новом контексте.
2. Передай kernel, все block artifacts/indexes, решения и проектный шаблон; не
   передавай историю рассуждений.
3. Собери `draft.md`: один факт в одном месте, ссылки между разделами вместо
   копий, идентификаторы и смысл сохранены. Не возвращай элементы, удалённые или
   отложенные принятыми `simplicity_authoring` решениями блоков/архитектора.
4. Примени `references/reader-projection-contract.md`: не переноси внутренние
   IDs/runtime-артефакты, разверни публичные references в точные локальные
   ссылки, оставь только прямые trace edges и отдели AC/DoD от developer
   self-check. Для UI-сценария сохрани экран входа; путь добавляй, только если
   source описывает навигацию, и не реконструируй его для уже открытого экрана.
   Явно назови новую поверхность при переходе, сопоставь видимые подписи полей
   с technical IDs и не повторяй полный путь, пока экран не меняется. Каждый UI
   AC напрямую ссылается на точный сценарий/ветвь с этим контекстом либо содержит
   подтверждённые экран/точку входа и минимальный маршрут; API-, batch- и
   system-only AC называют сценарий или системную точку входа без фиктивного UI.
5. Проверь, что ни один публичный semantic ID не потерян и не появился без определения.
6. Консолидируй diagram surfaces всех блоков. Удали дубли, но не теряй вопросы;
   добавь обзорную схему только если без неё межблочные связи приходится
   мысленно восстанавливать. Не сшивай локальные схемы в один нечитаемый граф.
7. После фактического включения переводите блоки `reviewed → integrated`.
8. Зафиксируй гейт `semantic_integration` с evidence `draft.md`.
9. Обнови working projection интегрированным draft, сохраняя явную маркировку
   ещё не пройденных global/project/architecture gates. После read-back запиши
   `projection-update --source integration`.

**Выход:** единый draft и явное покрытие всех блоков.

## Фаза 8. Детерминированная consistency-check

**Вход:** integrated blocks и draft.

1. Выполни `case_pipeline.py check --final-trace`.
2. До reviewer pass выполни profile document check читательской проекции.
   Исправь внутренние ID, plain/compressed/dangling references и только затем
   переходи к дорогим независимым проходам.
3. Проверь единый boundary на `particular-case` и
   `speculative-generalization`, затем независимо от profile выполни ровно один
   полный `simplicity-spec` по интегрированному решению. Запиши
   `clean|corrected|decision-required` как evidence существующего
   `author_passes`; не создавай роль или отдельный gate. В статусе/выдаче
   покажи человеку итог одной строкой, а для `corrected` — короткую дельту; в
   постановку служебный отчёт не переноси.
4. Finding по требованиям верни владельцу semantic block, архитектурный —
   архитектору; editor только проецирует принятую bounded дельту. Не открывай
   общий research и не обнуляй локальные reviews. После собственной коррекции
   второй полный simplicity-pass не нужен; позднее проверяй только дельту,
   которая вводит новый элемент решения. Изменение бизнес-смысла, scope,
   публичного контракта или канона требует `decision-required`.
5. Исправь дубликаты ID, неразрешённые ссылки, stale-блоки и разрывы
   `REQ ↔ AC`.
6. Сверь матрицу диаграмм: каждый указанный source ID существует, а каждый
   required-вопрос имеет определённое размещение и render target.
7. После принятой simplicity-дельты и остальных исправлений повторяй только
   deterministic checks до `PASS`; не запускай второй полный control и не
   закрывай гейт вручную.

**Выход:** gate `consistency=pass`, структура и трассировка непротиворечивы.

## Фаза 9. Интеграционное ревью

**Вход:** draft после consistency-check и все block indexes.

1. В `high` запусти reviewer `integration`. В `standard` пометь gate
   `not_required`: межблочная проверка входит в единый `final` pass.
2. Проверь противоречия между блоками, разные значения одного термина,
   переходы состояний, владельцев данных, сквозные ошибки и сохранность scope.
3. Проверь, что diagram surfaces не конфликтуют между блоками и что выбранная
   декомпозиция сохраняет сквозную логику без гигантской схемы.
4. Не повторяй полное локальное ревью каждого блока без доказанного конфликта.
5. Сохрани отчёт в `reviews/integration.md`. Исправь открытые принятые
   `blocker/major`, повтори check и только затронутый review. Minor обработай
   одним polish-pass либо оставь residual.
6. Зафиксируй gate `integration_review`, когда открытых принятых
   `blocker/major` нет; residual minor допустимы.
7. После точечного исправления повторяй только затронутый semantic/project/
   diagram gate. Полный integration/global review нужен лишь при изменении цели,
   границы, публичного контракта или сквозной логики.
8. Если correction осталась targeted, после свежих integration/author/machine
   checks и projection read-back вызови `record-remediation`. Команда создаёт
   audit receipts и переносит прежнее whole-case review coverage на новый
   subject. При full-block/crosscutting delta перенос запрещён и нужен свежий
   полный gate.

**Выход:** документ сшит семантически, а не только редакционно.

## Фаза 10. Author gates и глобальный reviewer

**Вход:** интегрированный draft.

1. Выполни оставшиеся профильные author gates в заданном порядке. Полный
   simplicity-control уже выполнен до integration review; повторно его не
   запускай.
2. Не удаляй доказанную seam как «лишнюю» и не возвращай отложенный обвес.
3. После правок снова выполни consistency-check; если правка вводит новый
   элемент решения, проверь только её simplicity-delta.
4. Отрендери все required-диаграммы способом текущей стадии из profile
   `diagram_delivery` и прочитай фактические изображения на целевой ширине. До
   явного publication gate не создавай persistent publication render/source.
   Исправь обрезку, наложения,
   неразличимые подписи и перегрузку через декомпозицию, а не уменьшение шрифта.
5. Зафиксируй `author_passes` только после machine validation единого
   solution-boundary блока.
6. В `high` запусти reviewer `global`. В `standard` запусти один reviewer
   `final` с `covered_gates: [integration_review, global_review,
   project_conformance]`, integration scope и применимыми project surfaces. Не
   передавай прошлые reports.
7. Сохрани итог в `reviews/global.md`; зафиксируй `global_review` только после
   закрытия открытых принятых `blocker/major`. Minor-only замечания не запускают
   второй полный global review после единственного polish-pass.

**Выход:** глобальная логика, полнота, тестируемость и правила проекта проверены.

## Фаза 11. Project conformance

**Вход:** готовый draft, проектный профиль и только применимые источники
соглашений.

1. В `high` запусти reviewer `project-conformance`. В `standard` используй тот
   же immutable `final` report только при явном `project_conformance` в
   `covered_gates` и полной surface matrix. Machine check обязателен всегда.
2. Проверь API-пути/HTTP, identifiers/casing, темы/сигналы, терминологию,
   frontmatter, шаблон, ссылки, файлы, формат публикации диаграмм и иные правила
   профиля.
3. Не требуй нового стиля от неизменяемого legacy-контракта, если проект велит
   сохранять совместимость.
4. Верни матрицу `surface → source → pass/finding/not-applicable`.
5. После исправлений повтори consistency-check и только затронутые проверки;
   затем зафиксируй gate `project_conformance`. При отсутствии открытых
   `blocker/major` residual minor не переоткрывают conformance.

**Выход:** локальные соглашения проверены независимо от общей логики.

## Фаза 12. Architecture conformance

**Вход:** готовый draft и состояние архитектурного гейта.

1. Если гейт не сработал и reviewer не обнаружил влияние, зафиксируй
   `not_required`.
2. Иначе запусти новый architect в режиме `conformance`; передай канон,
   утверждённые решения и draft, но не design-рассуждения.
3. Классифицируй итог `conform | decision-required | conflict`.
4. При `blocker/major` исправь затронутую область и повтори consistency-check и
   conformance. При minor-only выполни не более одного polish-pass или зафиксируй
   residual; не запускай новый архитектурный круг.

**Выход:** architecture gate закрыт доказуемым результатом.

## Фаза 13. Финальная проверка, выдача и публикация

**Вход:** все гейты закрыты.

1. Проверь нулевые `open_blocker/open_major` во всех review gates и зафиксированный
   residual log. Затем закрой последний active `Pxx`, выполни
   `automation_timing.py validate --final`, затем `case_pipeline.py validate --final`.
   Публикацию зафиксируй отдельным timing milestone. Если после неё пришли
   правки, `reopen` последний completed stage и создай следующую publication
   revision. Project-local model обновляй только после отдельного explicit
   development handoff. При включённом timing и доступном `work-metrics` перед
   update согласуй все объявленные case-related журналы разных сессий/харнесов;
   `--logs-complete` допустим только при доказанной полноте, а partial recovery
   остаётся ретроспективой. Эти данные остаются human-only и не входят в
   постановку или ролевые контексты.
   После первого handoff новые данные разработки веди отдельным follow-up case,
   начатым при фактическом возобновлении анализа: не переоткрывай основной
   sample и не включай межцикловое ожидание в его elapsed.
2. Выдай готовый текст, существенные допущения, решения и остаточный риск.
3. Публикуй или меняй внешние системы только по явной просьбе и правилам
   профиля; после записи выполни read-back.
4. Runtime case оставь для возобновления или архивируй по локальной политике;
   не смешивай его с каноническим документом.

**Выход:** финальная проверка `PASS`; результат не потерял смысл между блоками.
