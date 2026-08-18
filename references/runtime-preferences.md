# Опциональные runtime-возможности

Core Vigers переносим: task manager, прогноз времени и внешняя проекция не
обязательны. Effective настройки разрешаются один раз при создании planning-case
и закрепляются в manifest/handoff, поэтому изменение общего конфига не меняет
уже начатый case.

## Иерархия

1. package defaults;
2. user common preferences;
3. ближайший project profile.

Package defaults:

```json
{
  "automation_timing": "disabled",
  "timing_model": "disabled",
  "progress_tracking": "fine",
  "task_manager": "none",
  "timing_projection": "none",
  "timing_history": "none",
  "timing_calendar": "disabled",
  "deferred_state": "disabled",
  "state_projection": "none",
  "progress_projection": "none"
}
```

То есть без локальной настройки подробные machine checklists сохраняются, но
время не измеряется и наружу ничего не публикуется.

## User common preferences

Путь по умолчанию: `~/.config/vigers/preferences.json`. Для тестов и изолированного
запуска его можно заменить переменной `VIGERS_PREFERENCES`.

```json
{
  "schema": 1,
  "automation_timing": "enabled",
  "timing_model": "enabled",
  "progress_tracking": "fine",
  "task_manager": "singularity",
  "timing_projection": "task-note",
  "timing_history": "passport",
  "timing_calendar": "enabled",
  "deferred_state": "enabled",
  "state_projection": "project",
  "progress_projection": "checklist"
}
```

Имя provider — slug проектного адаптера, а не API в public core. Core формирует
контракты projection/read-back; авторизацию и вызовы реализует project adapter.

## Project overrides

В frontmatter `<project-root>/.vigers/profile.md` каждое поле принимает
`inherit` или конкретное значение:

```yaml
automation_timing: inherit        # enabled | disabled
timing_model: inherit             # enabled | disabled
progress_tracking: inherit        # fine | milestones | off
task_manager: inherit             # none | provider-slug
timing_projection: inherit        # none | task-note
timing_history: inherit           # none | passport
timing_calendar: inherit          # enabled | disabled
deferred_state: inherit           # enabled | disabled
state_projection: inherit         # none | project
progress_projection: inherit      # none | checklist
```

Project может независимо выключить timing, calendar/deferred-state или task
manager. При
`automation_timing: disabled` timing model, timing projection и passport history
автоматически выключаются; timing calendar также становится `disabled`. Calendar
требует включённый timing model. `state_projection: project` разрешён только при
`deferred_state: enabled`; конкретные Redmine/Singularity/Jira-маппинги остаются
в project profile и adapter. При `task_manager: none` task-note и checklist
projections становятся `none`; passport history от task manager не зависит.
Явная несовместимая комбинация отклоняется, а не молча исправляется.

Опциональный `work-metrics` следует effective timing policy: Vigers вызывает его
адаптер только когда одновременно включены `automation_timing` и `timing_model`.
Отдельного обязательного package dependency нет. Отключённый timing не запускает
сбор журналов от имени Vigers; сам companion можно независимо применять к другим
work item и другим метрикам.

`history_scope` всегда `project-profile` и не настраивается. Модель физически
лежит под project root и дополнительно проверяет его fingerprint; история разных
проектов не смешивается.

## Проекция человеку

После preliminary analysis coordinator вызывает `timing_model.py predict`. При
`timing_calendar=enabled` он передаёт project-owned
`.vigers/timing-calendar.json`; прогноз показывает active, business elapsed и
calendar ETA с учётом рабочих и handoff-окон.
Если `timing_projection=task-note`, project adapter добавляет `human_note` в
описание плана task manager и делает read-back. Если
`progress_projection=checklist`, adapter сопоставляет стабильные `Pxx-Cxx` с
внешними галками и подтверждает каждое изменение read-back.
Plan schema 5 хранит отдельный `progress_target_id`: он указывает на target task
manager и не переиспользует `external_target_id` этапа, предназначенный для
результата этапа. До первого completion вызови `bind-progress` с полной
биекцией `Pxx-Cxx → external_item_id`. Binding неизменяем: другой item требует
новой planning revision, а не молчаливой перепривязки. Completion принимается
только при read-back того же binding с `checked=true`.

Для legacy-case без такого контракта используй только атомарный
`migrate-progress`: команда одновременно фиксирует target/bindings и применяет
полный внешний read-back. Ручная правка `automation-timing.json` запрещена.
Последующие сверки выполняй через `reconcile-progress`; команда требует снимок
всех bindings и отклоняет как локальный completed с `checked=false`, так и
внешний `checked=true` для ещё незавершённого локального пункта.

При `timing_history=passport` project adapter append-only добавляет в паспорт
только смысловые точки: исходный forecast, каждую публикацию, явный development
handoff и финальное расхождение forecast/actual. Singularity хранит заменяемый
last-known checkpoint, паспорт — долговечную историю, локальный ledger — полный
event log.

Ни forecast, ни task-manager timer не попадают в bounded role context. Они не
влияют на модель, требования и финальные review gates.
