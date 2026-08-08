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

## Решение о режиме

`spec_pipeline.py suggest-mode` принимает извлечённые оркестратором факты, а не
пытается угадать структуру задачи по сырому тексту. Результат содержит:

- задачу и разрешённый профиль;
- нормализованные facts;
- сработавшие rules;
- `recommended_mode`, `selected_mode` и `selection_source`;
- warnings для явного override;
- fingerprint всего решения.

Обычный новый case начинается с записи решения по стандартному имени:

```text
python3 {baseDir}/scripts/spec_pipeline.py suggest-mode --cwd "<cwd>" \
  --task "<область>" --blocks 3 --surface scenarios --surface interfaces \
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
  --case-root "<path>" --block B01 --role system-analyst

python3 {baseDir}/scripts/case_pipeline.py refresh-kernel \
  --case-root "<path>" --affects B01

python3 {baseDir}/scripts/case_pipeline.py check \
  --case-root "<path>" --final-trace

python3 {baseDir}/scripts/automation_timing.py start \
  --case-root "<path>" --stage P01

python3 {baseDir}/scripts/automation_timing.py check \
  --case-root "<path>" --stage P01 --item P01-C01 \
  --evidence "<evidence-ref>"

python3 {baseDir}/scripts/automation_timing.py stop \
  --case-root "<path>" --stage P01 --status completed

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
read-back. Миграция запрещена, пока semantic block находится в `in_progress`.

Для review готового артефакта используй `--intent review`. Это единственный
новый case, которому разрешено не иметь `planning-handoff.json/md`.

`context --role system-analyst|spec-reviewer` всегда включает закреплённые
`method-context.json/md`. Редактору и архитектору эти файлы не выдаются: они
работают с уже полученной моделью требований и своими контрактами.
В compact-mode вызывай `context` без `--block`; в block-mode `--block Bxx`
обязателен.

Role context содержит `role-manifest.json` и `planning-role-context.json`, но не
coordinator manifest, raw planning JSON, automation estimates или runtime
ledger. ETA остаётся человекочитаемой информацией для plan review и не
становится скрытым бюджетом роли; role projections инвариантны к самим значениям
оценок.

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
