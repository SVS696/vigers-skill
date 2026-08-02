# Вигерс

Переносимый мультиагентный workflow для подготовки и независимого ревью
постановок, требований, Acceptance Criteria и Definition of Done.

Общий пакет содержит четыре независимые роли:

- системный аналитик;
- архитектор решения в раздельных режимах `design` и `conformance`;
- редактор постановки;
- независимый reviewer.

Роли получают явный case package и не наследуют рассуждения друг друга.
Архитектор включается по гейту, а business-context остаётся условной линзой
системного аналитика, не отдельным владельцем бизнес-решений.

## Публичное и проектное

Репозиторий намеренно не содержит профили конкретных проектов. Здесь лежат
только общий метод, контракты ролей, generic fallback и шаблон overlay-профиля.

Проектная конфигурация хранится рядом с проектом:

```text
<project-root>/.vigers/profile.md
```

Ближайший профиль вверх по дереву имеет приоритет. Если его нет, используется
`profiles/generic.md`. Такой контракт не раскрывает в публичном репозитории
названия проектов, внутренние источники, архитектуру и правила публикации.

## Установка

Клонируйте пакет в пользовательский каталог скиллов Codex:

```bash
git clone https://github.com/SVS696/vigers-skill.git ~/.codex/skills/vigers
python3 ~/.codex/skills/vigers/scripts/install.py --dry-run
python3 ~/.codex/skills/vigers/scripts/install.py
python3 ~/.codex/skills/vigers/scripts/install.py --check
```

Installer подключает сам скилл и четыре именованных агента:

- `~/.agents/skills/vigers` и `~/.claude/skills/vigers`;
- Codex-адаптеры в `~/.codex/agents/`;
- Claude-адаптеры в `~/.claude/agents/`.

Перед изменением файлов выполняется полный preflight. При конфликте installer
останавливается до первой записи и не перетирает существующие файлы или ссылки.
Повторный запуск идемпотентен.

Для обновления существующего git-clone:

```bash
git -C ~/.codex/skills/vigers pull --ff-only
python3 ~/.codex/skills/vigers/scripts/install.py
```

## Проектный профиль

Скопируйте безопасный шаблон в корень приватного проекта:

```bash
mkdir -p .vigers
cp ~/.codex/skills/vigers/profiles/project-profile-template.md .vigers/profile.md
```

Заполните `profile_id` и шесть секций:

1. область;
2. канонические источники;
3. системный анализ;
4. архитектурный гейт;
5. артефакт и author gates;
6. жизненный цикл и публикация.

Проверка профиля:

```bash
python3 ~/.codex/skills/vigers/scripts/spec_pipeline.py detect --cwd "$PWD"
python3 ~/.codex/skills/vigers/scripts/spec_pipeline.py show-profile auto --cwd "$PWD"
python3 ~/.codex/skills/vigers/scripts/spec_pipeline.py validate --project-root "$PWD"
```

## Использование

- Codex: `$vigers` или автоматическое подключение по описанию задачи.
- Claude Code: `/vigers` или автоматическое подключение по описанию задачи.

Пример:

```text
Используй Вигерса и преврати этот черновик в проверяемую постановку.
Отдельно покажи допущения, архитектурный гейт и блокирующие вопросы.
```

## Детерминированная маршрутизация

Обычная постановка использует маршрут `core`. Для специальной области можно
выбрать один ограниченный маршрут:

```bash
python3 scripts/vigers_context.py list
python3 scripts/vigers_context.py match "краткое описание области"
python3 scripts/vigers_context.py show traceability
```

Текстовая выжимка источника подключается только явным bounded fallback:

```bash
python3 scripts/vigers_context.py show traceability --fallback
```

## Проверка пакета

```bash
python3 scripts/vigers_context.py validate
python3 scripts/spec_pipeline.py validate
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s scripts -p 'test_*.py'
```

Валидатор проверяет маршруты метода, профильный контракт, роли обоих рантаймов,
workflow, отсутствие жёстких домашних путей и маркеров приватных проектов.

## Состав

```text
.
├── SKILL.md
├── agents
│   ├── claude
│   ├── codex
│   ├── contracts
│   └── openai.yaml
├── profiles
│   ├── generic.md
│   └── project-profile-template.md
├── references
├── scripts
│   ├── install.py
│   ├── spec_pipeline.py
│   └── test_*.py
└── workflows
    └── specification-pipeline.md
```

Исходные PDF, FB2 и растровые изображения в комплект не входят. Текстовые
технические карты и reference-файлы, необходимые для детерминированной
маршрутизации, сохраняются.
