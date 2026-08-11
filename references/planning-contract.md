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

`plan.json` schema 4 содержит этапы `Pxx`. Каждый этап имеет outcome,
dependencies, exit criteria, source refs, checklist `Pxx-Cxx` и трёхточечный
`automation_estimate`. Верхний `automation_estimation` фиксирует обязательные
`wall_clock`, `seconds` и `execution_use: human_information_only`. Это
предварительный baseline для человека и последующей калибровки, а не срок или
runtime-бюджет. Значения не включаются в role-context и не используются моделью
для темпа, порядка, приоритетов, остановки, сокращения scope, покрытия,
детализации или проверок. Общий прогноз вычисляется по critical path DAG; правила и runtime ledger заданы в
`{baseDir}/references/automation-timing.md`. Этап
создаётся только если у него есть самостоятельный результат или dependency gate;
иначе это checklist item.

Schema 4 также требует `preliminary_requirements`. Это planning-гипотезы, а не
утверждённая модель требований:

```json
{
  "status": "preliminary",
  "validation_gate": "full_analysis",
  "change_policy": "confirm_change_split_or_reject",
  "user_stories": [
    {
      "id": "PUS-001",
      "actor": "Пользователь",
      "goal": "понять причину ошибки и доступное действие",
      "benefit": "восстановить работу без лишней эскалации",
      "source_refs": ["SRC-001"],
      "confidence": "medium"
    }
  ],
  "definition_of_done": [
    {
      "id": "PDOD-001",
      "criterion": "Результат проверен по заявленным источникам",
      "evidence": "Сохранена трассировка и evidence проверки",
      "source_refs": ["SRC-001"],
      "confidence": "medium"
    }
  ]
}
```

Planner выявляет минимальный набор предполагаемых пользовательских историй и
критериев готовности по доступному research. Он не придумывает actor, value или
критерий «для полноты»: у каждого элемента есть `SRC-NNN` и честная confidence.
Это результат предварительного анализа; `full_analysis` — следующий gate его
валидации, а не источник этих гипотез.
Approval planning revision согласует направление анализа и план исполнения, но
не превращает `PUS-*`/`PDOD-*` в финальные требования, AC или DoD.

Полный системный анализ обязан рассмотреть каждый стабильный planning ID и
зафиксировать disposition `confirmed|changed|split|rejected` с трассировкой к
итоговым сценариям, требованиям, AC/DoD либо основанием отклонения. Новые US и
DoD, найденные в полном анализе, разрешены. Planning snapshot при этом не
переписывается: изменения живут в модели требований.

Schema 4 дополнительно требует `solution_boundary_probe` по
`{baseDir}/references/solution-boundary-contract.md`. Planner сохраняет
наблюдаемый кейс, кандидат корневой способности, просмотренные поверхности,
подтверждённые и предполагаемые варианты, roadmap/необратимость, источник
срочности и кандидат горизонта. Отсутствие аналогов фиксируется явным
отрицательным результатом. Probe остаётся гипотезой до полного анализа и не
расширяет current scope.

Schema 1 остаётся legacy-планом без telemetry; schema 2 — совместимым планом с
telemetry, но без обязательных planning-гипотез; schema 3 — совместимым планом
с preliminary US/DoD. Все новые revisions используют schema 4.

Checklist item — исполнимый шаг, а не односложный ярлык и не мини-ТЗ. `text`
может быть полноценным предложением. Если существенное условие не помещается в
одну строку без потери смысла, вынеси его в `details`; не ужимай пункт до
телеграфного обрубка. Допустимы:

- `text` — понятное действие и объект;
- `details` — контекст, входы или ограничения, только когда без них пункт
  двусмыслен; допустим короткий абзац или несколько точных строк;
- `done_when` — короткая проверка результата, когда она не очевидна;
- `completion_owner: agent|user` — кто вправе подтвердить выполнение; для
  `user` агент не начинает пункт и не ставит внешнюю галку;
- `links`/`source_refs` — точные ссылки вместо пересказа источника.

Если checklist публикуется наружу, этап содержит `external_target_id` из
`artifact-plan.json`. Во время исполнения stable ID `Pxx-Cxx` используется как
ключ синхронизации с внешней галкой. Порядок элементов checklist не является
неявной dependency: любой независимый пункт можно выбрать первым. Перед
содержательной работой координатор вызывает `automation_timing.py begin` для
выбранного item. Если другой item уже `in_progress`, новая действительно
параллельная работа требует явного `--parallel-reason`.

Сразу после фактического выполнения пункта:

1. проверь `done_when` и собери evidence;
2. отметь соответствующую галку через project adapter;
3. прочитай внешний item обратно и убедись, что он действительно checked;
4. вызови `automation_timing.py check` с evidence и read-back;
5. только затем переходи к следующему пункту.

Для `completion_owner: user` порядок другой: агент подготавливает handoff и
останавливается; пользователь ставит внешнюю галку сам. После явного
подтверждения пользователя и read-back `checked=true` координатор вызывает
`automation_timing.py check --user-confirmed`. Ни готовый handoff, ни обещание,
ни статус соседней задачи не заменяют это подтверждение.

«Следующий» здесь означает следующий обычный последовательный шаг, а не
обязательный порядок списка. Заранее начатая параллельная работа может
продолжаться, но принятие результата каждого item прерывается на его собственную
синхронизацию. Не копи выполненные пункты для пакетного обновления в конце этапа.
Повтор той же операции с тем же evidence идемпотентен. `stop --status completed`
отклоняется, если хотя бы один обязательный checklist item остаётся pending или
`in_progress`. Галку нельзя ставить по прогнозу, обещанию или recap роли без
проверяемого результата.

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
пункт. Сначала проверь ясность: действие и объект названы прямо,
расплывчатые глаголы заменены конкретными, а эмоциональное усиление отсутствует.
Затем выполни два прохода:

1. `simplicity-spec` и бритву Оккама: «не множить сущности сверх необходимого».
   Каждая стадия, subtask и уточнение обязаны закрывать текущую цель, dependency
   или проверку; остальное удалить либо отложить.
2. `humanizer`: убрать канцелярит, AI-сигналы и неестественную телеграфность без
   изменения IDs, source refs, условий готовности и смысла. Для внутреннего
   Vigers checklist и его проекции в личный task manager не применять
   пользовательский профиль внешнего голоса. Такой профиль используется отдельно
   только для текста, который реально публикуется от имени пользователя:
   сообщения, tracker-комментарии, постановки и финальная документация.

После проходов checklist может остаться подробным. Цель — минимально достаточная
ясность, а не минимальное число слов.

## Внешние артефакты

`artifact-plan.json` задаёт target `EXT-NNN`, system, action, purpose, authority,
`publish_gate` (`before_research|before_review|after_approval|none`) и
`read_back_required`. Target, который служит растущей постановкой для человека,
дополнительно получает `working_projection: true` и неизменяемый
`evidence_kind: local_file|external_readback`.
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
- frontmatter profile задаёт `working_projection: required|optional|disabled`.
  При `required` artifact plan содержит хотя бы один actionable target с
  `working_projection: true`, `publish_gate: after_approval` и обязательным
  read-back. Каждый такой target заранее объявляет `evidence_kind`; runtime CLI
  не может подменить внешний read-back локальным файлом. При `disabled` такие
  targets запрещены;
- working projection создаётся или связывается после approval и до полного
  анализа. Это видимый человеку рабочий draft, а не новая машина истины:
  runtime case хранит факты, semantic IDs и состояние; проекция показывает
  растущий результат и статусы проверенности;
- локальный файл считается таким же projection target, как tracker/wiki:
  `system` и `object_id` содержат объявленные profile канал и путь, а read-back
  подтверждает существование и прочитанное содержимое;
- форму projection target выбирает только project profile и исследованная форма
  результата. Core не создаёт параллельный локальный документ, если profile
  объявляет tracker description, wiki page/delta или несколько внешних targets
  рабочей проекцией;
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
После approval обычное выполнение пунктов принятого плана не требует
поштучного согласования: координатор фиксирует completion evidence и read-back.
Новый user decision gate появляется только при `material` delta или иной явно
критичной развилке, не разрешённой approved snapshot.

Как только во время полного системного анализа становится ясно, что approved
DAG, scope, exit criteria либо checklist нужно изменить, аналитик прекращает
текущий проход и возвращает `status: replan`. Координатор создаёт новую revision
командой `planning_case.py replan`. Причина, current-analysis evidence refs и
impact `local|material` сохраняются; прежний snapshot, approval, handoff и runtime
ledger остаются аудируемыми. Изменённый plan снова проходит необходимый research
delta и синхронизацию внешнего checklist с read-back.

`local` — только некритичная коррекция порядка, evidence-step или технической
детализации, не меняющая цель, scope, требования/приёмку, внешний контракт,
архитектуру, риск, обязательства, владельца решения и полномочия. После
публикации новой revision координатор фиксирует её командой
`approve-local-replan`; отдельный user review не нужен. `material` включает
любое изменение перечисленных поверхностей и проходит обычный user approval.
Удалённые или заменённые пункты явно помечаются в delta, а не исчезают; уже
выполненные пункты сохраняют stable ID и evidence, если их смысл и `done_when`
не изменились.

Approval записывает actor, time, note и subject hash. `planning_case.py export`
создаёт `planning-handoff.json/md`; `case_pipeline.py init` проверяет profile,
fingerprint, content hash и approval revision. Handoff переносит immutable
`automation_plan` только для оркестратора, а init создаёт связанный
`automation-timing.json`. Для исполнительных ролей отдельно материализуется
`planning-role-context.json` без ETA и runtime facts. Эти данные не проецируются
в checklist task manager и не считаются временем пользователя.
Handoff также содержит policy и связанные working projection targets с их
read-back bindings. `case_pipeline.py init` переносит их в
`working-projection.json`. После значимого обновления координатор фиксирует
target, semantic source и его hash, hash прочитанного содержимого, evidence ref
и время read-back командой `projection-update`. Для локального файла команда
проверяет файл напрямую; для tracker/wiki принимает только сохранённый adapter
receipt по `references/handoff-contract.md`. Само наличие скрытых block artifacts или
`draft.md` не считается таким обновлением.
Без пары approved handoff files
новый non-review Vigers case не запускается. `--allow-unplanned` существует
только для миграции старых cases и не используется новым workflow.
