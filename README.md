# Вигерс

Переносимый мультиагентный workflow для исследования источников, согласуемого
планирования, поблочной сборки и независимого ревью постановок, требований,
Acceptance Criteria и Definition of Done.

Общий пакет содержит пять независимых ролей:

- read-only планировщик для research coverage, DAG этапов и external drafts;
- системный аналитик с условной business-context линзой;
- архитектор решения в раздельных режимах `design` и `conformance`;
- редактор постановки в режимах document/block-render/integrate;
- reviewer в режимах block/integration/global/project-conformance.

Роли обмениваются только case artifacts и не наследуют рассуждения друг друга.
Общий prompt-contract задаёт ограниченный assignment envelope, отделяет
инструкции от source documents и требует явный handoff-формат.

## Planning, compact и block

До нового анализа, изменения, декомпозиции или архитектурной проработки Vigers
создаёт planning-case:

```text
intake -> researching -> researched -> artifacts_planned
  -> published_for_review -> approved -> handed_to_vigers
```

Research включает поиск по применимым источникам project profile, фиксацию
отрицательных результатов и gaps. Этапы и внешние checklists строятся только
после coverage gate. Пользователь видит план и созданные draft-артефакты; его
комментарий создаёт новую immutable revision. Полноценный Vigers case принимает
только approved `planning-handoff.json/md`.

План хранит трёхточечную оценку wall-clock времени только для информации
человека. После approval оркестратор ведёт `automation-timing.json`: фиксирует
фактическое время, `evidence` и немедленную отметку каждого `Pxx-Cxx`. Для внешней
галки обязателен read-back с `checked=true`. ETA не попадает в контекст роли и не
управляет её темпом, областью работ или проверками.

Если во время полного анализа обнаружена ошибка в принятом плане, аналитик
сразу возвращает `status: replan`. Некритичную коррекцию принимает координатор;
изменение цели, области работ, требований, приёмки, внешнего контракта, архитектуры,
существенного риска, обязательств или полномочий требует повторного согласования
пользователя.
Неизменившиеся пункты принятого плана поштучно не согласовываются.

Цикл исправлений заканчивается, когда нет открытых принятых `blocker/major`.
`minor` можно исправить одним пакетным проходом или оставить в residual log;
они не запускают новое полное review. После coverage gate новый research разрешён
только для конкретного `blocker|major` с точным вопросом, целевыми источниками
и условием остановки. Это поведение закреплено повторяемым Prompt Cookbook
fixture `evals/prompt-cookbook/convergence-closed-coverage.json`.

`compact` обслуживает один связный смысловой контур. `block` делит крупную
постановку на 3–8 семантических contracts с явным DAG, стабильными IDs и
сохраняемым состоянием:

```text
planning-handoff.json/md + mode-decision.json + method-context.json/md
  -> manifest.json + ledger.json + kernel.md
  -> blocks/Bxx.md + Bxx.index.json
  -> local reviews
  -> integration
  -> global/project/architecture gates
```

Изменение kernel инвалидирует затронутые downstream blocks. Финальный PASS
требует разрешённой трассировки, свежих fingerprints и независимых
integration/global/project-conformance gates.

Режим выбирается детерминированно из явно зафиксированных фактов задачи:

```bash
python3 scripts/spec_pipeline.py suggest-mode --cwd "$PWD" \
  --task "Изменение сценария и публичного интерфейса" --blocks 3 \
  --surface scenarios --surface interfaces \
  --write .vigers/cases/example/mode-decision.json
```

Команда возвращает рекомендацию, сработавшие правила и fingerprint. Явный
`--requested-mode` имеет приоритет, но расхождение остаётся в warnings. Затем
`case_pipeline.py init` связывает planning approval и decision с manifest и
отклоняет несовпадение режима, профиля или fingerprints.

## Публичное и проектное

Репозиторий не содержит профили конкретных проектов. Приватный overlay хранится
рядом с проектом:

```text
<project-root>/.vigers/profile.md
```

Ближайший профиль вверх по дереву имеет приоритет; без него используется
`profiles/generic.md`. Профиль задаёт research sources, planning/external
adapters, architecture gate, compact/block правила, author/project gates и
publication lifecycle.

## Установка

```bash
git clone https://github.com/SVS696/vigers-skill.git ~/.codex/skills/vigers
python3 ~/.codex/skills/vigers/scripts/install.py --dry-run
python3 ~/.codex/skills/vigers/scripts/install.py
python3 ~/.codex/skills/vigers/scripts/install.py --check
```

Installer подключает skill и пять именованных агентов к Codex и Claude,
выполняет preflight и не перетирает существующие targets.

## Проектный профиль

```bash
mkdir -p .vigers
cp ~/.codex/skills/vigers/profiles/project-profile-template.md .vigers/profile.md
python3 ~/.codex/skills/vigers/scripts/spec_pipeline.py validate \
  --project-root "$PWD"
```

Runtime cases рекомендуется хранить в `.vigers/cases/<case-id>/` и исключать из
git, если проект явно не требует иного.

## Использование

```text
Используй Вигерса. Разбей эту многосервисную постановку на смысловые блоки,
сохрани сквозные инварианты и пройди независимые integration, project-style и
architecture checks.
```

## Детерминированная методическая маршрутизация

```bash
python3 scripts/vigers_context.py list
python3 scripts/vigers_context.py match "краткое описание области"
python3 scripts/vigers_context.py materialize traceability \
  --write .vigers/cases/example
```

Команда закрепляет ограниченную книжную выжимку в
`method-context.json/md`. `case_pipeline.py init` связывает её fingerprint с
manifest, а role-context автоматически выдаёт её аналитику и reviewer, но не
редактору. Книжный fallback подключается только через явный `--fallback` для
точной нехватки; весь reference corpus не грузится в один контекст.

## Проверка

```bash
python3 scripts/vigers_context.py validate
python3 scripts/spec_pipeline.py validate
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s scripts -p 'test_*.py'
```

Validator проверяет routes, mode decision, block/case contracts, оба runtime adapters,
workflows, проектные overlays и отсутствие приватных markers/домашних путей.

## Состав

```text
.
├── SKILL.md
├── agents/{contracts,codex,claude}
├── profiles
├── references
├── scripts/{vigers_context,spec_pipeline,mode_decision,planning_case,case_pipeline,automation_timing}.py
└── workflows/{planning-pipeline,specification-pipeline,block-pipeline}.md
```

Исходные PDF/FB2/изображения в комплект не входят. Пакет содержит только
текстовые выжимки и маршруты, необходимые для детерминированной работы.
