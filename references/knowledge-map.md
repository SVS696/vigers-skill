# Карта знаний скилла «Вигерс»

Это единственный маршрутизатор дополнительных материалов. Основной метод
находится в `SKILL.md` и применяется всегда. Карта нужна только тогда, когда
ядра недостаточно для конкретной предметной области.

Правила маршрутизации:

1. По умолчанию используй маршрут `core` и не загружай справочники.
2. Выбирай один основной тематический маршрут.
3. Сначала загружай только `distilled`.
4. Загружай `fallback` только для точной детали, которой нет в дистилляте.
5. Не открывай `book-extract.md` вручную и не читай его целиком.
6. Если нужны две независимые области, обрабатывай маршруты последовательно,
   не смешивая их источники.

Машиночитаемая часть ниже является канонической. Не дублируй маршруты в других
файлах.

<!-- vigers:routes -->
```json
{
  "version": 1,
  "default_route": "core",
  "routes": [
    {
      "id": "core",
      "when": "Обычная локальная постановка без специальной предметной области",
      "signals": [],
      "core": ["Исполняемая процедура"],
      "distilled": [],
      "fallback": [],
      "result": "Проверяемая постановка по основному playbook без дополнительных материалов"
    },
    {
      "id": "requirement-types",
      "when": "Нужно разделить бизнес-, пользовательские, функциональные, системные требования, интерфейсы и ограничения",
      "signals": ["типы требований", "уровни требований", "бизнес-требование", "функциональное требование", "ограничение"],
      "core": ["Модель требований", "4. Классифицируй найденное"],
      "distilled": [
        {"file": "references/native-diagrams.md", "heading": "D01. Иерархия требований — стр. 7"},
        {"file": "references/native-diagrams.md", "heading": "D06. Типы информации о требованиях — стр. 20"}
      ],
      "fallback": [
        {"file": "references/book-extract.md", "block": "book-requirement-levels"}
      ],
      "result": "Разделенные типы требований с сохраненной связью между уровнями"
    },
    {
      "id": "requirements-process",
      "when": "Нужно организовать процесс выявления, анализа, документирования, утверждения или управления требованиями",
      "signals": ["процесс требований", "разработка требований", "управление требованиями", "итерация требований", "базовая версия"],
      "core": ["Исполняемая процедура"],
      "distilled": [
        {"file": "references/native-diagrams.md", "heading": "D02. Разработка требований и управление ими — стр. 9"},
        {"file": "references/native-diagrams.md", "heading": "D03. Итерационная разработка требований — стр. 10"},
        {"file": "references/native-diagrams.md", "heading": "D04. Разработка требований по итерациям — стр. 14"},
        {"file": "references/native-tables.md", "heading": "T01. Организационные практики — стр. 13"}
      ],
      "fallback": [
        {"file": "references/book-extract.md", "block": "book-process"}
      ],
      "result": "Понятный процесс работы с требованиями и точки контроля"
    },
    {
      "id": "scope-users",
      "when": "Нужно определить бизнес-цель, границы, заинтересованные стороны или классы пользователей",
      "signals": ["бизнес-цель", "границы проекта", "scope", "классы пользователей", "заинтересованные стороны", "сторонник продукта"],
      "core": ["2. Установи основание", "3. Зафиксируй цель и границы"],
      "distilled": [
        {"file": "references/native-tables.md", "heading": "T02. Участие представителей пользователей — стр. 17"},
        {"file": "references/native-tables.md", "heading": "T03. Разрешение конфликтов — стр. 18"}
      ],
      "fallback": [
        {"file": "references/book-extract.md", "block": "book-scope-users"}
      ],
      "result": "Цель, scope, классы пользователей, представители и конфликтующие интересы"
    },
    {
      "id": "elicitation",
      "when": "Нужно выявить требования, подготовить интервью, семинар, наблюдение или найти пропуски",
      "signals": ["выявление требований", "сбор требований", "интервью", "семинар", "наблюдение", "упущенные требования"],
      "core": ["2. Установи основание"],
      "distilled": [
        {"file": "references/native-checklists.md", "heading": "C01. Техники разработки требований — стр. 12"},
        {"file": "references/native-tables.md", "heading": "T04. Выбор техники выявления — стр. 18"},
        {"file": "references/native-diagrams.md", "heading": "D05. Выявление требований — стр. 19"}
      ],
      "fallback": [
        {"file": "references/book-extract.md", "block": "book-elicitation"}
      ],
      "result": "План выявления требований и перечень проверяемых пробелов"
    },
    {
      "id": "scenarios",
      "when": "Нужно описать вариант использования, актора, основной и альтернативные потоки",
      "signals": ["вариант использования", "use case", "актор", "сценарий", "альтернативный поток", "исключение сценария"],
      "core": ["5. Смоделируй поведение"],
      "distilled": [
        {"file": "references/native-checklists.md", "heading": "C02. Поиск вариантов использования — стр. 24"},
        {"file": "references/native-diagrams.md", "heading": "D07. Варианты использования системы учета химикатов — стр. 22"},
        {"file": "references/native-tables.md", "heading": "T05. Пример варианта использования UC-4 — стр. 23"}
      ],
      "fallback": [
        {"file": "references/book-extract.md", "block": "book-use-cases"}
      ],
      "result": "Полный сценарий с актором, триггером, потоками, исключениями и состояниями"
    },
    {
      "id": "business-rules",
      "when": "Нужно выявить или формализовать факты, ограничения, политики, активаторы, выводы и вычисления",
      "signals": ["бизнес-правило", "политика", "активатор операции", "вычисление", "формула", "матрица ролей"],
      "core": ["4. Классифицируй найденное", "5. Смоделируй поведение"],
      "distilled": [
        {"file": "references/native-diagrams.md", "heading": "D06. Типы информации о требованиях — стр. 20"},
        {"file": "references/native-tables.md", "heading": "T26. Таблица решения по заказу — стр. 71"}
      ],
      "fallback": [
        {"file": "references/book-extract.md", "block": "book-business-rules"}
      ],
      "result": "Атомарные бизнес-правила с источником, условиями и наблюдаемыми последствиями"
    },
    {
      "id": "requirements-writing",
      "when": "Нужно написать SRS, атомарные требования или исправить неоднозначный язык",
      "signals": ["srs", "спецификация требований", "атомарное требование", "неоднозначное требование", "идеальное требование", "формулировка требования"],
      "core": ["7. Напиши атомарные требования"],
      "distilled": [
        {"file": "references/native-checklists.md", "heading": "C18. Проверка спецификации требований — стр. 46"},
        {"file": "references/native-tables.md", "heading": "T20. Типы проблем с требованиями — стр. 60"}
      ],
      "fallback": [
        {"file": "references/book-extract.md", "block": "book-documentation-writing"}
      ],
      "result": "Атомарные, однозначные и проверяемые требования"
    },
    {
      "id": "data",
      "when": "Нужно описать сущности, поля, словарь данных, CRUD, целостность или модель данных",
      "signals": ["данные", "сущность", "поле", "словарь данных", "crud", "erd", "целостность данных"],
      "core": ["6. Проверь специальные области"],
      "distilled": [
        {"file": "references/native-tables.md", "heading": "T06. Фрагмент словаря данных — стр. 30"},
        {"file": "references/native-tables.md", "heading": "T07. CRUD-матрица — стр. 31"},
        {"file": "references/native-diagrams.md", "heading": "D14. Модель данных учета химикатов — стр. 68"}
      ],
      "fallback": [
        {"file": "references/book-extract.md", "block": "book-data"}
      ],
      "result": "Модель данных, словарь, CRUD и требования целостности"
    },
    {
      "id": "integration",
      "when": "Нужно описать внешний интерфейс, API, очередь, файл или межсистемный обмен",
      "signals": ["интеграция", "api", "endpoint", "очередь", "topic", "межсистемный обмен", "внешний интерфейс"],
      "core": ["6. Проверь специальные области"],
      "distilled": [
        {"file": "references/task-template.md", "heading": "Интеграционная добавка"},
        {"file": "references/native-tables.md", "heading": "T16. Таблица поведения интерфейса — стр. 53"}
      ],
      "fallback": [
        {"file": "references/book-extract.md", "block": "book-external-interfaces"}
      ],
      "result": "Проверяемый контракт обмена, ошибки, повторы, совместимость и наблюдаемость"
    },
    {
      "id": "reports-dashboards",
      "when": "Нужно поставить отчет, экспорт, выгрузку или информационную панель",
      "signals": ["отчет", "экспорт", "выгрузка", "dashboard", "панель мониторинга", "витрина данных"],
      "core": ["6. Проверь специальные области"],
      "distilled": [
        {"file": "references/task-template.md", "heading": "Добавка для отчетов и экспорта"}
      ],
      "fallback": [
        {"file": "references/book-extract.md", "block": "book-reporting"}
      ],
      "result": "Формат, данные, фильтры, агрегации, пустые результаты, лимиты и сроки"
    },
    {
      "id": "quality",
      "when": "Нужно определить измеримые нефункциональные требования или компромиссы качеств",
      "signals": ["атрибут качества", "нефункциональное требование", "производительность", "надежность", "безопасность", "масштабируемость", "удобство"],
      "core": ["6. Проверь специальные области"],
      "distilled": [
        {"file": "references/native-tables.md", "heading": "T08. Словарь атрибутов качества — стр. 33"},
        {"file": "references/native-tables.md", "heading": "T11. Анализ компромиссов качеств — стр. 41"}
      ],
      "optional_ids": ["C03", "C04", "C05", "C06", "C07", "C08", "C09", "C10", "C11", "C12", "C13", "C14", "C15"],
      "fallback": [
        {"file": "references/book-extract.md", "block": "book-quality"}
      ],
      "result": "Измеримый атрибут качества с нагрузкой, метрикой, границей и методом проверки"
    },
    {
      "id": "prototype-ui",
      "when": "Нужно выбрать тип прототипа, проверить его назначение или вывести интерфейс из сценария",
      "signals": ["прототип", "макет", "wireframe", "интерфейс", "ui", "ux"],
      "core": ["5. Смоделируй поведение"],
      "distilled": [
        {"file": "references/native-checklists.md", "heading": "C16. Оценка прототипа — стр. 43"},
        {"file": "references/native-tables.md", "heading": "T12. Одноразовый и эволюционный прототип — стр. 43"},
        {"file": "references/native-diagrams.md", "heading": "D08. От варианта использования к интерфейсу — стр. 43"}
      ],
      "fallback": [
        {"file": "references/book-extract.md", "block": "book-prototype"}
      ],
      "result": "Прототип с явной целью, сроком жизни и критериями оценки"
    },
    {
      "id": "prioritization",
      "when": "Нужно определить приоритеты, релизный scope или последствия откладывания функции",
      "signals": ["приоритет", "приоритизация", "must", "релизный scope", "отложить функцию", "ценность стоимость риск"],
      "core": ["3. Зафиксируй цель и границы"],
      "distilled": [
        {"file": "references/native-checklists.md", "heading": "C17. Последствия откладывания функции — стр. 45"},
        {"file": "references/native-tables.md", "heading": "T13. Приоритизация по ценности, стоимости и риску — стр. 45"}
      ],
      "fallback": [
        {"file": "references/book-extract.md", "block": "book-prioritization"}
      ],
      "result": "Обоснованный приоритет по ценности, ущербу, стоимости, риску и зависимостям"
    },
    {
      "id": "review-acceptance",
      "when": "Нужно проверить требования, составить acceptance criteria или отделить приемку от DoD",
      "signals": ["ревью требований", "рецензирование требований", "acceptance criteria", "критерии приемки", "dod", "приемочный тест"],
      "core": ["8. Сформируй приемку и DoD", "9. Пройди контрольные ворота"],
      "distilled": [
        {"file": "references/native-checklists.md", "heading": "C18. Проверка спецификации требований — стр. 46"},
        {"file": "references/native-checklists.md", "heading": "C19. Рецензирование требований — стр. 48"},
        {"file": "references/native-checklists.md", "heading": "C20. Концептуальные тесты требования — стр. 49"},
        {"file": "references/task-template.md", "heading": "Acceptance criteria и DoD"}
      ],
      "fallback": [
        {"file": "references/book-extract.md", "block": "book-validation"}
      ],
      "result": "Findings ревью, проверяемые AC и отдельный DoD поставки"
    },
    {
      "id": "reuse",
      "when": "Нужно обобщить требования или подготовить активы для повторного использования",
      "signals": ["повторное использование", "reuse", "библиотека требований", "обобщение требования", "актив требований"],
      "core": ["4. Классифицируй найденное"],
      "distilled": [
        {"file": "references/native-checklists.md", "heading": "C13. Повторное использование — стр. 40"},
        {"file": "references/native-diagrams.md", "heading": "D10. Обобщение требования для повторного использования — стр. 52"},
        {"file": "references/native-tables.md", "heading": "T14. Активы требований для повторного использования — стр. 50"},
        {"file": "references/native-tables.md", "heading": "T15. Типичные возможности повторного использования — стр. 51"}
      ],
      "fallback": [
        {"file": "references/book-extract.md", "block": "book-reuse"}
      ],
      "result": "Обобщенный и управляемый актив требований для повторного применения"
    },
    {
      "id": "delivery-handoff",
      "when": "Нужно связать требования с дизайном, реализацией, тестами и доказательствами поставки",
      "signals": ["передача в разработку", "дизайн по требованиям", "реализация требования", "тестирование требования", "доказательство поставки"],
      "core": ["8. Сформируй приемку и DoD"],
      "distilled": [
        {"file": "references/native-checklists.md", "heading": "C21. Полнота дизайна — стр. 52"},
        {"file": "references/native-tables.md", "heading": "T17. Документы процессов — стр. 54"}
      ],
      "fallback": [
        {"file": "references/book-extract.md", "block": "book-delivery"}
      ],
      "result": "Связь требования с дизайном, кодом, тестом, документом и проверкой поставки"
    },
    {
      "id": "change-management",
      "when": "Нужно описать изменение существующего поведения, оценить влияние, миграцию или откат",
      "signals": ["управление изменениями", "запрос на изменение", "анализ влияния", "миграция", "обратная совместимость", "откат"],
      "core": ["1. Определи режим работы", "6. Проверь специальные области"],
      "distilled": [
        {"file": "references/native-diagrams.md", "heading": "D11. Области управления требованиями — стр. 54"},
        {"file": "references/native-diagrams.md", "heading": "D12. Жизненный цикл запроса на изменение — стр. 56"},
        {"file": "references/native-checklists.md", "heading": "C23. Анализ влияния: требования и бизнес — стр. 58"},
        {"file": "references/native-checklists.md", "heading": "C24. Анализ влияния: артефакты поставки — стр. 58"},
        {"file": "references/native-checklists.md", "heading": "C25. Полная оценка трудозатрат изменения — стр. 59"}
      ],
      "fallback": [
        {"file": "references/book-extract.md", "block": "book-change"}
      ],
      "result": "Полный impact analysis, переход, совместимость, миграция и откат"
    },
    {
      "id": "lifecycle",
      "when": "Нужно определить состояния требования или объекта, переходы и тенденции",
      "signals": ["состояние требования", "статус", "жизненный цикл", "переход состояния", "state machine", "тенденция состояний"],
      "core": ["5. Смоделируй поведение"],
      "distilled": [
        {"file": "references/native-checklists.md", "heading": "C26. Диаграмма тенденций состояний — стр. 60"},
        {"file": "references/native-tables.md", "heading": "T21. Состояния требования — стр. 61"}
      ],
      "optional_ids": ["D15", "T25"],
      "fallback": [
        {"file": "references/book-extract.md", "block": "book-state"}
      ],
      "result": "Состояния, допустимые переходы, события, запреты и метрики движения"
    },
    {
      "id": "traceability",
      "when": "Нужно связать цели, требования, сценарии, реализацию, тесты и владельцев связей",
      "signals": ["трассировка", "traceability", "матрица требований", "связи требований", "связать требования с тестами", "uc fr", "требование тест"],
      "core": ["4. Классифицируй найденное", "9. Пройди контрольные ворота"],
      "distilled": [
        {"file": "references/native-diagrams.md", "heading": "D13. Сеть трассировки требований — стр. 62"},
        {"file": "references/native-tables.md", "heading": "T22. Сквозная трассировка — стр. 63"},
        {"file": "references/native-tables.md", "heading": "T23. Матрица UC ↔ FR — стр. 63"},
        {"file": "references/native-tables.md", "heading": "T24. Владельцы связей трассировки — стр. 63"}
      ],
      "fallback": [
        {"file": "references/book-extract.md", "block": "book-traceability"}
      ],
      "result": "Двусторонняя трассировка с источниками, целями и владельцами связей"
    },
    {
      "id": "risk",
      "when": "Нужно выявить или оценить риски разработки и управления требованиями",
      "signals": ["риск требований", "риски разработки и управления требованиями", "оценка рисков", "риск выявления", "риск анализа", "расползание границ", "нереализованное требование"],
      "core": ["3. Зафиксируй цель и границы", "9. Пройди контрольные ворота"],
      "distilled": [
        {"file": "references/native-checklists.md", "heading": "C17. Последствия откладывания функции — стр. 45"},
        {"file": "references/native-checklists.md", "heading": "C23. Анализ влияния: требования и бизнес — стр. 58"},
        {"file": "references/native-tables.md", "heading": "T13. Приоритизация по ценности, стоимости и риску — стр. 45"}
      ],
      "fallback": [
        {"file": "references/book-extract.md", "block": "book-risk"}
      ],
      "result": "Реестр рисков с причиной, вероятностью, ущербом, мерами и владельцем"
    },
    {
      "id": "modeling",
      "when": "Нужно выбрать или построить модель данных, состояний, решений, событий, контекста или диалогов",
      "signals": ["моделирование требований", "модель данных", "диаграмма", "mermaid", "plantuml", "дерево решений", "контекстная диаграмма", "таблица решений"],
      "core": ["5. Смоделируй поведение"],
      "distilled": [
        {"file": "references/native-diagrams.md", "heading": "D14. Модель данных учета химикатов — стр. 68"},
        {"file": "references/native-diagrams.md", "heading": "D15. Состояния заказа химиката — стр. 69"},
        {"file": "references/native-diagrams.md", "heading": "D17. Дерево решения о заказе — стр. 71"},
        {"file": "references/native-diagrams.md", "heading": "D18. Источники событий системы — стр. 72"}
      ],
      "optional_ids": ["D16", "T25", "T26"],
      "fallback": [
        {"file": "references/book-extract.md", "block": "book-modeling"}
      ],
      "result": "Минимальная модель, которая устраняет конкретную неоднозначность"
    },
    {
      "id": "source-audit",
      "when": "Нужно проверить происхождение нативного D/T/C-артефакта и его соответствие странице выжимки",
      "signals": ["карта изображений", "исходная страница", "происхождение", "происхождение диаграммы", "соответствие конвертации", "d01", "t01", "c01"],
      "core": ["Источники и приоритет"],
      "distilled": [
        {"file": "references/native-image-map.md", "heading": "Карта преобразования иллюстраций"}
      ],
      "fallback": [],
      "result": "Страница и исходное имя для проверки происхождения нативного артефакта"
    }
  ]
}
```
