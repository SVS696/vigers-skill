# Вигерс

Скилл для Claude Code и Codex, который превращает идею, переписку или черновик
в проверяемую постановку задачи по принципам инженерии требований Карла
Вигерса.

Основной `SKILL.md` самодостаточен. Он содержит:

- диагностику слабых постановок;
- типы требований и трассировку от цели до приемки;
- десятишаговую процедуру с условными ветками;
- правила для данных, интеграций, отчетов, миграций и атрибутов качества;
- разделение Acceptance Criteria и Definition of Done;
- контрольные ворота и политику уточняющих вопросов.

В `references/` лежат два дополнительных текстовых слоя из переносимого
архива:

- сконвертированная выжимка книги в `book-extract.md` — редкий fallback;
- наш дистиллят метода — таблицы, чек-листы, текстовые диаграммы и расширенный
  шаблон постановки.

`knowledge-map.md` связывает предметную область с точными разделами
дистиллята и размеченным блоком выжимки. `scripts/vigers_context.py` извлекает
только выбранный контекст и не позволяет случайно загрузить оглавление или
весь `book-extract.md`.

Содержимое скилла соответствует переносимому архиву. README, `.gitignore` и
`.github/` — только обвязка GitHub-репозитория. Исходные PDF, FB2 и изображения
в комплект не входят.

## Установка

Каноническую копию удобно хранить в Codex, а Claude Code и общий каталог
агентов подключить символическими ссылками:

```bash
git clone https://github.com/SVS696/vigers-skill.git ~/.codex/skills/vigers
mkdir -p ~/.agents/skills ~/.claude/skills
ln -s ~/.codex/skills/vigers ~/.agents/skills/vigers
ln -s ~/.codex/skills/vigers ~/.claude/skills/vigers
```

Если соответствующая ссылка уже существует, повторно создавать ее не нужно.

## Использование

- Codex: `$vigers` или автоматическое подключение по описанию задачи.
- Claude Code: `/vigers` или автоматическое подключение по описанию задачи.

Пример запроса:

```text
Используй Вигерса и преврати этот черновик в проверяемую постановку.
Отдельно покажи допущения и блокирующие вопросы.
```

## Детерминированная маршрутизация

Обычная постановка использует только `SKILL.md`. Дополнительные материалы
загружаются одним тематическим маршрутом:

```bash
python3 scripts/vigers_context.py list
python3 scripts/vigers_context.py match "краткое описание области"
python3 scripts/vigers_context.py show traceability
```

Текст выжимки подключается только явно:

```bash
python3 scripts/vigers_context.py show traceability --fallback
```

Проверка карты, 21 блока выжимки, 70 нативных D/T/C-артефактов и всех путей:

```bash
python3 scripts/vigers_context.py validate
python3 scripts/test_vigers_context.py
```

## Состав

```text
.
├── SKILL.md
├── README.md
├── agents
│   └── openai.yaml
├── references
│   ├── book-extract.md
│   ├── knowledge-map.md
│   ├── native-checklists.md
│   ├── native-diagrams.md
│   ├── native-image-map.md
│   ├── native-tables.md
│   └── task-template.md
└── scripts
    ├── test_vigers_context.py
    └── vigers_context.py
```

`agents/openai.yaml` добавляет метаданные интерфейса Codex и не мешает Claude
Code.
