# Контракт planning-case

Planning-case предшествует Vigers case и отвечает на два вопроса: достаточно ли
исследованы источники и согласован ли исполнимый путь к постановке. Он не содержит
полноценную модель требований и не заменяет будущую постановку.

Границы артефактов:

- planning-case хранит research, зависимый план, review и approval;
- passport хранит происхождение задачи и ссылки на источники;
- личный anchor учитывает один результат и ближайшее действие;
- Vigers case строит модель требований и постановку.

Один факт хранится в каноническом артефакте; остальные ссылаются на него.

## Состояния

```text
intake -> researching -> researched -> artifacts_planned
  -> published_for_review -> approved -> handed_to_vigers
                             |
                             -> changes_requested -> researching

любое рабочее состояние -> blocked -> researching
```

- `researching` начинается только после зафиксированного intake;
- профиль может потребовать минимальные учётные anchors до `researching`; это
  единственное допустимое исключение из read-only research и оно не означает
  согласование плана;
- `researched` требует research report, source map и coverage verdict;
- `artifacts_planned` требует корректный DAG этапов и проект внешних записей;
- `published_for_review` требует созданные и прочитанные обратно draft-артефакты,
  которые profile считает обязательными до review;
- `approved` относится к точному fingerprint revision;
- `handed_to_vigers` означает, что approved snapshot экспортирован в новый
  specification-case;
- `changes_requested` никогда не перетирает прежний snapshot.

## Пакет

```text
<planning-root>/
├── planning-manifest.json   machine state, revision, events, hashes
├── status.md                генерируемый DoD
├── intake.md                исходная цель и полномочия без улучшения смысла
├── research.md              факты, конфликты, gaps и выводы для планирования
├── source-map.json          запросы, найденные/недоступные источники, freshness
├── artifact-plan.json       разрешённые draft-записи во внешние системы
├── plan.json                DAG этапов и checklists
├── plan.md                  человекочитаемый план для review
├── bindings.json            passport и подтверждённые external IDs/read-back
├── handoff.md               bounded approved input для Vigers
├── reviews/revision-NNN.md  комментарий и verdict пользователя
└── revisions/revision-NNN/  immutable snapshot опубликованной revision
```

Machine truth — `planning-manifest.json` и JSON-артефакты. Не редактируй manifest
вручную. Markdown хранит объяснение и доступный пользователю вид тех же решений.

## Исследование источников

Planning начинается с исследования источников. Декомпозиция следует после него.
Profile определяет обязательные системы, их authority и адаптеры. Координатор:

1. строит search matrix по поверхностям задачи;
2. выполняет read-only поиск в трекере, wiki, репозитории, проектных заметках,
   переписке и других применимых источниках;
3. фиксирует выполненные запросы, включая отрицательный результат;
4. присваивает найденному стабильные `SRC-NNN`;
5. указывает system, exact ref, authority, status и `checked_at`;
6. сохраняет противоречия и недоступное покрытие;
7. возвращает `sufficient`, `partial` или `blocked`.

`partial` разрешает продолжение только когда gap не мешает безопасно построить
план, а его влияние и владелец ответа явно зафиксированы. `blocked` останавливает
planning. Отсутствие результата поиска не доказывает отсутствие требования или
решения.

Исходные длинные документы не копируются в case целиком. Роль получает bounded
source documents с ID, origin и датой чтения. Для большого корпуса поиск и
синтез выполняются по независимым source clusters в свежих контекстах.

## План и checklist

`plan.json` содержит этапы `Pxx`. Каждый этап имеет outcome, dependencies, exit
criteria, source refs и checklist `Pxx-Cxx`. Этап создаётся только если у него
есть самостоятельный результат или dependency gate; иначе это checklist item.

Checklist item — исполнимый шаг, а не односложный ярлык и не мини-ТЗ. `text`
может быть полноценным предложением. Если существенное условие не помещается в
одну строку без потери смысла, вынеси его в `details`; не ужимай пункт до
телеграфного обрубка. Допустимы:

- `text` — понятное действие и объект;
- `details` — контекст, входы или ограничения, только когда без них пункт
  двусмыслен; допустим короткий абзац или несколько точных строк;
- `done_when` — короткая проверка результата, когда она не очевидна;
- `links`/`source_refs` — точные ссылки вместо пересказа источника.

Если объявленный profile task manager поддерживает у checklist item только
`title`, `text` превращается в title, а `details` и `done_when` — в раздел заметки
родительской задачи с тем же `Pxx-Cxx`. Конкретное отображение и ограничения
коннектора задаёт profile. Отдельная subtask создаётся только если шаг имеет
собственный outcome, dependency или owner. Не создавай подзадачу ради абзаца.

Пример:

```json
{
  "id": "P02-C03",
  "text": "Сверить контракт загрузки с текущей ручкой и постановкой",
  "details": "Проверить multipart-поля, пустой body и ошибки 4xx; источники по ссылкам.",
  "done_when": "Расхождения перечислены с SRC refs либо подтверждено совпадение."
}
```

Перед публикацией обработай checklist целиком, а не отдельным агентом на каждый
пункт. Примени три лёгких прохода:

1. `copywriting` только как линзу ясности: действие и объект названы прямо,
   расплывчатые глаголы заменены конкретными; маркетинговые приёмы, CTA и
   эмоциональное усиление запрещены.
2. `simplicity-spec` и бритву Оккама: «не множить сущности сверх необходимого».
   Каждая стадия, subtask и уточнение обязаны закрывать текущую цель, dependency
   или проверку; остальное удалить либо отложить.
3. `humanizer`: убрать канцелярит, AI-сигналы и неестественную телеграфность без
   изменения IDs, source refs, условий готовности и смысла. Если доступен
   проектный или пользовательский профиль рабочего стиля, использовать его.

После проходов checklist может остаться подробным. Цель — минимально достаточная
ясность, а не минимальное число слов.

## Внешние артефакты

`artifact-plan.json` задаёт target `EXT-NNN`, system, action, purpose, authority,
`publish_gate` (`before_research|before_review|after_approval|none`) и
`read_back_required`.
Общий core не знает URL, проекты, workflow и поля конкретного tracker — их
задаёт ближайший project profile.

Правила:

- исследование всегда read-only после входа в `researching`;
- `before_research` разрешён только для пустого учётного anchor, который profile
  требует создать или связать при появлении личной содержательной работы. Если
  объект уже существует, target использует action `link` и не создаёт дубль.
  Личный anchor может появиться раньше канонического tracker/wiki-артефакта, если
  profile явно разделяет личный и командный контуры. Anchor содержит минимальное
  название, не получает описание постановки, workflow status, assignee,
  priority или commitment date и обязательно читается обратно;
- после создания anchor research не обновляет его до завершения coverage gate;
- если research уточнил, что единицей результата должен быть другой уже
  существующий объект, координатор до `researched` заменяет только binding через
  `bind --action link --replace` с новым read-back; второй anchor не создаётся;
- passport создаётся максимально рано с временным ID и
  `provenance_status: partial`, если канонического tracker ID ещё нет;
- появление tracker ID обновляет binding того же passport, а не создаёт второй;
- объявленный profile task manager хранит личное обязательство, текущую стадию
  и ближайшее действие;
- трекер, wiki и проектные заметки сохраняют техническую декомпозицию и
  каноническую историю по правилам profile;
- draft creation не означает approval, назначение или начало реализации;
- `after_approval` target заранее входит в опубликованный artifact plan, но
  создаётся или связывается только после approval. До export он получает
  read-back binding; изменение его system, purpose, action или gate требует
  новой revision и повторного review;
- каждая запись проверяется read-back и только затем попадает в `bindings.json`;
- личные ссылки и локальные passport paths не публикуются во внешние командные
  системы, если profile этого не разрешает.

## Review, revision и handoff

Пользователь получает plan.md и ссылки на созданные draft-артефакты. Комментарий
к цели или новый источник создаёт research delta; комментарий к этапам и
checklist — plan delta. Оба варианта начинают новую revision и сохраняют старую.

Approval записывает actor, time, note и subject hash. `planning_case.py export`
создаёт `planning-handoff.json/md`; `case_pipeline.py init` проверяет profile,
fingerprint, content hash и approval revision. Без пары approved handoff files
новый non-review Vigers case не запускается. `--allow-unplanned` существует
только для миграции старых cases и не используется новым workflow.
