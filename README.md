# Вигерс

Переносимый мультиагентный workflow для подготовки, поблочной сборки и
независимого ревью постановок, требований, Acceptance Criteria и Definition of
Done.

Общий пакет содержит четыре независимые роли:

- системный аналитик с условной business-context линзой;
- архитектор решения в раздельных режимах `design` и `conformance`;
- редактор постановки в режимах document/block-render/integrate;
- reviewer в режимах block/integration/global/project-conformance.

Роли обмениваются только case artifacts и не наследуют рассуждения друг друга.
Общий prompt-contract задаёт ограниченный assignment envelope, отделяет
инструкции от source documents и требует явный handoff-формат.

## Compact и block

`compact` обслуживает один связный смысловой контур. `block` делит крупную
постановку на 3–8 семантических contracts с явным DAG, стабильными IDs и
сохраняемым состоянием:

```text
manifest.json + ledger.json + kernel.md
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
`case_pipeline.py init` связывает decision с manifest и отклоняет несовпадение
режима или профиля.

## Публичное и проектное

Репозиторий не содержит профили конкретных проектов. Приватный overlay хранится
рядом с проектом:

```text
<project-root>/.vigers/profile.md
```

Ближайший профиль вверх по дереву имеет приоритет; без него используется
`profiles/generic.md`. Профиль задаёт sources, architecture gate, compact/block
правила, author/project gates и publication lifecycle.

## Установка

```bash
git clone https://github.com/SVS696/vigers-skill.git ~/.codex/skills/vigers
python3 ~/.codex/skills/vigers/scripts/install.py --dry-run
python3 ~/.codex/skills/vigers/scripts/install.py
python3 ~/.codex/skills/vigers/scripts/install.py --check
```

Installer подключает skill и четыре именованных агента к Codex и Claude,
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
python3 scripts/vigers_context.py show traceability
```

Книжный fallback подключается только для точной детали, которой нет в
дистилляте; весь reference corpus не грузится в один контекст.

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
├── scripts/{vigers_context,spec_pipeline,mode_decision,case_pipeline}.py
└── workflows/{specification-pipeline,block-pipeline}.md
```

Исходные PDF/FB2/изображения в комплект не входят. Пакет содержит только
текстовые выжимки и маршруты, необходимые для детерминированной работы.
