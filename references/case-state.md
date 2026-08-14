# Case-state Vigers

`case_pipeline.py` — детерминированный оркестратор. Он не анализирует
требования и не пишет постановку: хранит состояние, проверяет зависимости,
свежесть kernel, semantic IDs и гейты.

Для нового non-review case обязательны approved `planning-handoff.json/md`,
экспортированные `planning_case.py`. `--allow-unplanned` существует только для
миграции старого runtime state. Planning package и specification package имеют
разные state machines и не объединяются в один manifest.

## Состав case package

```text
<case-root>/
├── mode-decision.json         # факты, правила, выбранный режим, fingerprint
├── method-context.json        # маршрут, состав выжимки, hashes, fingerprint
├── method-context.md          # ограниченный методический контекст ролей
├── planning-handoff.json      # approved planning revision и fingerprints
├── planning-handoff.md        # полный approved basis для оркестратора
├── planning-role-context.json # planning basis без ETA/runtime для ролей
├── manifest.json              # режим, kernel revision, gates, event log
├── role-manifest.json         # bounded manifest ролей без timing-derived полей
├── ledger.json                # блоки, DAG, состояния, пути артефактов
├── automation-timing.json     # прогноз и wall-clock факт approved этапов
├── agent-ledger.json          # стоимость и повторы модельных проходов
├── working-projection.json    # видимые draft targets и read-back updates
├── status.md                  # генерируемый человекочитаемый DoD
├── kernel.md                  # общие цель, scope, словарь и инварианты
├── evidence.md                # источники, факты, gaps и актуальность
├── decisions.md               # принятые решения и основания
├── blocks/
│   ├── B01.md                 # смысловая модель блока
│   └── B01.index.json         # определения и трассировка
├── reviews/
│   ├── B01.md                 # локальное независимое ревью
│   ├── integration.md
│   ├── global.md
│   ├── project.md
│   └── architecture.md
└── draft.md                   # интегрированный документ
```

Machine truth — связка `planning-handoff.json/md`, `mode-decision.json`,
`method-context.json/md`, `manifest.json`, `ledger.json` и
`automation-timing.json`. Не редактируй их вручную. `status.md` можно в любой
момент пересобрать командой `status`.

`working-projection.json` не хранит текст постановки. Он доказывает, куда и
когда проецировался растущий человекочитаемый draft. При policy `required`
target уже создан или связан до полного анализа. При
`projection_sync=per-block` после каждого reviewed блока координатор обновляет
targets и записывает read-back с `source=Bxx`; следующий semantic pass ждёт
проекции. При `milestones` Bxx-барьера нет: обязательны полный draft,
integration и принятые смысловые изменения. В compact-mode первый update обязателен до
`author_passes`, а его `source_sha256` должен совпадать с текущим `draft.md`.
В block-mode перед `author_passes` так же проверяется текущий `integration`
update. Последующие существенные исправления также читаются обратно.
Канал выбирается из project profile: локальный документ остаётся обычным
проектным файлом, а tracker/wiki проекция записывается непосредственно в
объявленный внешний target. Универсальный параллельный файл core не создаёт.

Для `local_file` evidence команда сама читает bound project file и сверяет его
SHA-256. Путь обязан точно совпадать с `object_id` target и находиться за
пределами скрытого runtime case. Для `external_readback` project adapter
сохраняет в case отдельный JSON receipt по `references/handoff-contract.md`;
одного URL недостаточно. Runtime update принимает только `evidence_kind`,
зафиксированный target в approved handoff.

## Решение о режиме

`spec_pipeline.py suggest-mode` принимает извлечённые оркестратором факты, а не
пытается угадать структуру задачи по сырому тексту. Результат содержит:

- задачу и разрешённый профиль;
- нормализованные facts;
- сработавшие rules;
- `recommended_mode`, `selected_mode` и `selection_source`;
- независимо выбранные `selected_assurance`, `selected_tracking` и
  `selected_projection_sync`;
- warnings для явного override;
- fingerprint всего решения.

Обычный новый case начинается с записи решения по стандартному имени:

```text
python3 {baseDir}/scripts/spec_pipeline.py suggest-mode --cwd "<cwd>" \
  --task "<область>" --blocks 3 --surface scenarios --surface interfaces \
  --change-scope semantic-local \
  --write "<case-root>/mode-decision.json"
```

До `init` case-root содержит exported planning handoff, decision и пару
`method-context.json/md`, созданную `vigers_context.py materialize`. `init`
проверяет planning approval, связь с `--mode`, `--profile-id` и `--route-id`,
пересобирает методическую выжимку по текущим источникам и сохраняет fingerprints
в manifest. Последующие проверки case
валидируют уже закреплённый snapshot и обнаруживают ручное изменение. Старые
cases без decision или method context читаются как `legacy-unrecorded`. Для их
миграции есть явные `--allow-unrecorded-mode` и
`--allow-unrecorded-method` и `--allow-unplanned`; новый workflow эти escape
hatches не использует.

## Состояния блока

```text
planned → ready → in_progress → analyzed → reviewed → integrated
              ↘ blocked → ready
kernel edit: in_progress|analyzed|reviewed|integrated → stale → ready
```

- `ready` разрешён только после `reviewed|integrated` всех зависимостей.
- `analyzed` требует заполненные `.md` и `.index.json`.
- `reviewed` требует review artifact и свежий kernel snapshot.
- `integrated` требует заполненный `draft.md`.
- `blocked` всегда содержит причину.

## Сходимость review gates

Review report — evidence гейта, а не повод автоматически запустить ещё один
полный круг. Перед `set-gate --status pass` координатор проверяет:

- все findings имеют disposition `accepted|rejected|user-decision`;
- `open_blocker=0` и `open_major=0` после disposition;
- неисправленные `minor` записаны как `residual` с основанием;
- `research_reopen=targeted` указан только для принятого `blocker|major` с
  `research_question`, `missing_evidence`, `target_sources` и `stop_condition`;
- для minor-only уже использован не более чем один polish-pass текущего гейта.

Повторяй только затронутый review gate и детерминированные проверки. `pass` не
переоткрывается из-за residual minor. Если тот же `blocker/major` остаётся после
двух точечных циклов, состояние становится `user-decision`; третий автоматический
цикл запрещён. Полные правила заданы в
`{baseDir}/references/convergence-contract.md`.

## Базовые команды

```text
python3 {baseDir}/scripts/case_pipeline.py init \
  --case-root "<path>" --case-id "<id>" --mode block --intent create \
  --cwd "<cwd>" --profile-id "<profile>" --route-id core

python3 {baseDir}/scripts/case_pipeline.py add-block \
  --case-root "<path>" --id B01 --kind scenarios --title "Основной поток"

python3 {baseDir}/scripts/case_pipeline.py add-block \
  --case-root "<path>" --id B02 --kind interfaces --title "Публичный контракт" \
  --depends-on B01

python3 {baseDir}/scripts/case_pipeline.py transition \
  --case-root "<path>" --id B01 --status ready

python3 {baseDir}/scripts/case_pipeline.py context \
  --case-root "<path>" --block B01 --role system-analyst \
  --role-mode block --contract-surface diagram

python3 {baseDir}/scripts/case_pipeline.py refresh-kernel \
  --case-root "<path>" --change-scope semantic-local --affects B01 \
  --reason "<what changed>"

python3 {baseDir}/scripts/case_pipeline.py begin-remediation \
  --case-root "<path>" --id B01 \
  --finding "REV-014=major" --semantic-id "REQ-B01-003" \
  --evidence "reviews/history/global_review-r001.md" \
  --reason "<accepted finding and bounded correction>"

python3 {baseDir}/scripts/case_pipeline.py record-remediation \
  --case-root "<path>" --id B01 --remediation-id R001 \
  --reason "<fresh checks and read-back confirmed the bounded delta>"

python3 {baseDir}/scripts/case_pipeline.py record-change \
  --case-root "<path>" --change-scope editorial --reason "<what changed>"

python3 {baseDir}/scripts/case_pipeline.py projection-update \
  --case-root "<path>" --target-id EXT-001 --source B01 \
  --source-sha256 "<sha256-source-artifact>" \
  --content-sha256 "<sha256-read-back-content>" \
  --evidence-kind "<local_file|external_readback>" \
  --evidence-ref "<file-or-receipt-path>" --read-back-at "<iso-8601>"

python3 {baseDir}/scripts/case_pipeline.py check \
  --case-root "<path>" --final-trace

python3 {baseDir}/scripts/automation_timing.py start \
  --case-root "<path>" --stage P01

python3 {baseDir}/scripts/automation_timing.py begin \
  --case-root "<path>" --stage P01 --item P01-C01

python3 {baseDir}/scripts/automation_timing.py check \
  --case-root "<path>" --stage P01 --item P01-C01 \
  --evidence "<evidence-ref>"

# Только после того, как пользователь сам поставил ручную галку:
python3 {baseDir}/scripts/automation_timing.py check \
  --case-root "<path>" --stage P05 --item P05-C01 \
  --user-confirmed --evidence "<user-confirmation-ref>" \
  --external-system "<system>" --external-item-id "<item-id>" \
  --read-back-at "<timestamp>"

python3 {baseDir}/scripts/automation_timing.py stop \
  --case-root "<path>" --stage P01 --status completed

python3 {baseDir}/scripts/case_pipeline.py record-agent-run \
  --case-root "<path>" --role spec-reviewer --role-mode final \
  --model "<model>" --subject-sha256 "<sha256>" --input-bytes 12345 \
  --duration-seconds 42 --retries 0 --reported-blocker 0 \
  --reported-major 0 --reported-minor 1

python3 {baseDir}/scripts/case_pipeline.py validate \
  --case-root "<path>" --final
```

Если новый runtime ужесточил planning/timing-контракт уже после старта case,
сначала открой и локально утверди новую planning revision, затем экспортируй её
в отдельный каталог и выполни штатную миграцию:

```text
python3 {baseDir}/scripts/case_pipeline.py migrate-planning \
  --case-root "<path>" --handoff-root "<exported-handoff-directory>" \
  --reason "<why the previous runtime contract is superseded>"
```

Команда не переносит галки по догадке: она архивирует прежние handoff, timing,
manifest и semantic ledger, сохраняет текущие блоки, связывает новую revision и
создаёт свежий runtime checklist. Уже выполненные пункты после этого повторно
подтверждаются обычными `automation_timing.py check` с evidence и внешним
read-back; для `completion_owner: user` нужен новый пользовательский confirm и
`--user-confirmed`. Миграция запрещена, пока semantic block находится в
`in_progress`.
Старый case без `working-projection.json` мигрирует с policy `optional`. Updates
сохраняются только для target, чья identity
`target_id+system+object_id+url+evidence_kind` не изменилась; при перенаправлении target
прошлые read-back updates остаются в архиве, но не переносятся в новую revision.
Старый `planning-role-context.json` без ключа `working_projection` принимается
только вместе со старым handoff и при точном совпадении сохранённого fingerprint;
остальные расхождения по-прежнему считаются tampering.

Для review готового артефакта используй `--intent review`. Это единственный
новый case, которому разрешено не иметь `planning-handoff.json/md`.

`context --role system-analyst|spec-reviewer` всегда включает закреплённые
`method-context.json/md`. Редактору и архитектору эти файлы не выдаются: они
работают с уже полученной моделью требований и своими контрактами.
Архитектор получает отдельный `--role solution-architect --role-mode
design|conformance` и только объявленные contract surfaces.
В compact-mode вызывай `context` без `--block`; в block-mode `--block Bxx`
обязателен.

Role context содержит точные `contract_inputs`, `role-manifest.json` и
`planning-role-context.json`, но не coordinator manifest, raw planning JSON,
forecast, project timing model или runtime ledger. Время остаётся
человекочитаемой информацией и не становится скрытым бюджетом роли; role
projections инвариантны к значениям forecast.

`refresh-kernel` различает `editorial|projection-only|semantic-local|
semantic-crosscutting|architecture`. Локальное смысловое изменение переводит в
`stale` только выбранные блоки и downstream, остальные переносит на новый
kernel hash. Широкая инвалидация требует `--invalidate-all`; отсутствие
аргумента не означает «протухло всё». Старые cases без execution policy
сохраняют прежнюю семантику `high + fine + per-block`.
`record-change` сравнивает текущий consistency snapshot со snapshot каждого
переносимого review gate. Editorial допускает только изменения регистра и
пробелов; операторы, checkbox state и Markdown-структура сохраняются.
Projection-only не допускает изменений semantic artifacts вообще. Одной
декларации scope недостаточно для переноса review evidence.

Новый блок с `remediation_contract: targeted-v1` нельзя вернуть из
`reviewed|integrated` в работу обычным `transition`. `begin-remediation`
сохраняет immutable copies предыдущего блока, index и finding evidence, а также
ограничивает targeted delta перечисленными semantic IDs. Повторный block report
обязан вернуть `review_scope: targeted-remediation`, точный список
`verified_findings` и путь `coverage_reused`. При `--full-block` прошлое
покрытие не переносится. После свежих `semantic_integration`, `author_passes`,
consistency, document checks и projection read-back `record-remediation`
создаёт audit receipts и переносит только действительно существовавшие passed
whole-case review gates. Изменение любого постороннего semantic artifact
блокирует перенос.

Planning stages `Pxx` и semantic blocks `Bxx` — разные DAG. Первый измеряет
исполнение approved плана, второй управляет смысловой сборкой постановки. Не
создавай отдельный timing stage для каждого блока, если planning plan этого не
объявляет. Полный контракт — `{baseDir}/references/automation-timing.md`.

## Правила хранения

- Case package не содержит секреты, cookies, приватные ключи и необработанные
  чувствительные дампы.
- Профиль выбирает рабочий каталог. Без профильного правила используй
  отдельную локальную область координатора.
- Если case лежит в проектном `.vigers/cases/`, каталог `cases/` должен быть
  локально проигнорирован git.
- Канонический документ и runtime state — разные артефакты с разным жизненным
  циклом.
