# Вигерс

Переносимый мультиагентный workflow для исследования источников, согласуемого
планирования, поблочной сборки и независимого ревью постановок, требований,
Acceptance Criteria и Definition of Done.

Общий пакет содержит пять независимых ролей:

- read-only планировщик для research coverage, DAG этапов и external drafts;
- системный аналитик с условной business-context линзой;
- архитектор решения в раздельных режимах `design` и `conformance`;
- редактор постановки в режимах document/block-render/integrate;
- reviewer в режимах block/integration/global/final/project-conformance.

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
после coverage gate. Перед approval Vigers детерминированно собирает
`approval-summary.md`: предварительные User Story в форме «Как ..., я хочу ...,
чтобы ...», preliminary DoD, укрупнённый план и coverage/gaps. Сводка прямо
говорит, что полный анализ может изменить, разделить, отклонить или дополнить
истории; approval подтверждает направление анализа, а не финальные требования.
Пользователь также видит созданные draft-артефакты; его комментарий создаёт
новую immutable revision. Полноценный Vigers case принимает только approved
`planning-handoff.json/md`.

Для простой однокластерной задачи `fast-plan` объединяет research design,
synthesis и plan в один fresh вызов, не убирая source map, coverage gate,
артефакты, state transitions и пользовательское approval. Конфликт, второй
cluster или high-risk признак возвращает полный planning route.

После предварительного анализа отдельный project-local калибратор выбирает
похожие завершённые кейсы только этого проекта. Без календаря он сохраняет
legacy active/elapsed; с project calendar показывает чистую работу,
business elapsed и calendar ETA первой передачи. Модели время не
получают и не оценивают. После approval оркестратор ведёт
`automation-timing.json`, а подробные `Pxx-Cxx` остаются независимыми progress
barriers. Для внешней галки обязателен read-back с `checked=true`.

Timing, калибратор, task manager и внешние projections опциональны: package
defaults ничего наружу не подключают, user common preferences задают личный
набор, а project profile может переопределить каждую capability. Effective
настройки закрепляются в planning handoff и не меняют уже начатые cases.

Если во время полного анализа обнаружена ошибка в принятом плане, аналитик
сразу возвращает `status: replan`. Некритичную коррекцию принимает координатор;
изменение цели, области работ, требований, приёмки, внешнего контракта, архитектуры,
существенного риска, обязательств или полномочий требует повторного согласования
пользователя.
Неизменившиеся пункты принятого плана поштучно не согласовываются.

Project profile может потребовать раннюю working projection. Тогда после
planning approval и до полного анализа создаётся или связывается обычный файл,
tracker либо wiki draft. В `per-block` он обновляется после каждого reviewed
блока, в `milestones` — на полном draft, integration и принятых смысловых
изменениях; read-back обязателен. `.vigers/cases/` не считается видимым человеку
результатом. Форму target задаёт project profile: core не создаёт параллельный
локальный файл для tracker/wiki проекции. Project file проверяется напрямую,
внешний read-back — по JSON receipt проектного адаптера. Рабочая проекция и
финальная публикация остаются разными состояниями.
Тип evidence закрепляется в approved target: внешний target нельзя закрыть
локальным файлом, а `local_file` должен точно совпадать с объявленным путём вне
скрытого runtime case.

Цикл исправлений заканчивается, когда нет открытых принятых `blocker/major`.
`minor` можно исправить одним пакетным проходом или оставить в residual log;
они не запускают новое полное review. После coverage gate новый research разрешён
только для конкретного `blocker|major` с точным вопросом, целевыми источниками
и условием остановки. Это поведение закреплено повторяемым Prompt Cookbook
fixture `evals/prompt-cookbook/convergence-closed-coverage.json`.
Ранняя видимость отдельно проверяется fixture
`evals/prompt-cookbook/early-working-projection.json`.
Выбор project-owned target вместо универсального локального файла проверяется
fixture `evals/prompt-cookbook/profile-owned-working-projection.json`.

Простота решения применяется двумя слоями. Аналитик и архитектор сразу строят
минимальную модель и обязаны обосновать текущим сценарием, правилом или
ограничением каждый дополнительный статус, сущность, настройку, абстракцию и
инфраструктурный механизм. После сборки всего решения Vigers один раз выполняет
контрольный `simplicity-spec` до независимого смыслового review. Это evidence
существующего author gate, а не новая роль или бесконечный review loop:
требования возвращаются их semantic owner, архитектура — архитектору, а поздние
правки получают только проверку введённой дельты.
Перед выбором нового механизма роли проходят лестницу «не нужно → уже есть в
продукте/процессе → проектная граница → native platform → принятый механизм →
прямое локальное решение → минимальная новая реализация». Простота не может
срезать protected floor: подтверждённый смысл, безопасность, восстановление,
проверяемость, публичный контракт и доказанную extension seam. Для сознательного
компромисса фиксируются потолок, измеримый trigger возврата и upgrade path.
Та же логика действует на сам Vigers: deterministic check, текущая роль и
существующая review surface имеют приоритет над новым артефактом или gate.

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

Изменение kernel инвалидирует затронутые downstream blocks и переносит
незатронутые на новый hash. Финальный PASS требует разрешённой трассировки,
свежих fingerprints и review-покрытия, выбранного по assurance.

Размер контекста (`compact|block`) и цена гарантии (`lite|standard|high`)
выбираются независимо. Обычный `standard` использует один combined final review;
`high` сохраняет отдельные integration/global/project проходы. Legacy cases без
policy продолжают прежний строгий маршрут.

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
├── scripts/{vigers_context,spec_pipeline,mode_decision,planning_case,case_pipeline,automation_timing,timing_model,timing_calendar}.py
└── workflows/{planning-pipeline,specification-pipeline,block-pipeline}.md
```

Исходные PDF/FB2/изображения в комплект не входят. Пакет содержит только
текстовые выжимки и маршруты, необходимые для детерминированной работы.
