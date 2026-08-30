# Opt-in backend revmux для независимого review

`revmux` — заменяемый backend существующей роли `vigers-spec-reviewer`, а не
новая роль и не дополнительный gate. Backend по умолчанию остаётся `native`.
Выбор `review_backend: revmux` должен быть явным в assignment или case-local
решении и действует только на названный review gate. Он доступен во всех
существующих reviewer modes: `block`, `integration`, `global`, `final` и
`project-conformance`.

## Opt-in dependency

Native backend не зависит от revmux. Выбранный `review_backend: revmux`
fail-closed требует бинарь `revmux` в `PATH` и caller-интеграцию активного
reviewer runtime из той же совместимой ревизии:

- Codex reviewer загружает установленный skill `revmux` из
  `plugins/codex/skills/revmux`;
- Claude Code reviewer предзагружает skill `revmux:revmux` из включённого
  plugin `revmux@revmux` версии `0.4.3` через agent frontmatter и явно вызывает
  его через `Skill` tool.

Skill-local профили запускают Claude subprocesses, поэтому независимо от caller
им нужен доступный и аутентифицированный `claude` CLI. Текущий compatibility pin:
`33ede7aaf632cebbde08f2dd53ffa06c4722d81b`; ожидаемый `revmux --version`
содержит `33ede7a`. `revmux_review.py prepare` проверяет бинарь и записывает его
resolved path, version и pin в immutable context; reviewer adapter отдельно
проверяет доступность caller skill/plugin. Отсутствующий компонент либо иная
ревизия не вызывает тихий fallback на native: assignment останавливается до
явного исправления dependency или смены backend. Один checkout исходников без
этих подключений не считается установленной зависимостью.

## Контракт reviewer-driver

При `review_backend: revmux` роль reviewer:

1. проверяет доступность `revmux`, фиксирует `revmux --version`, exact subject
   SHA-256, `role_mode`, `covered_gates`, профиль и paths входов;
2. загружает caller skill `revmux` своего runtime и по нему готовит task/round,
   не меняя frozen subject;
3. запускает ровно один профиль `vigers-review` для initial либо ровно один
   `vigers-final` для подтверждения с `--config-dir <vigers-root>/revmux`;
4. читает JSON report и manifest, проверяет полноту sources и отсутствие
   degraded/unverified critical/major;
5. возвращает consolidated findings/evidence существующего review gate.

В Vigers output `critical` детерминированно отображается в существующий
`blocker`, `major` и `minor` сохраняются. Исходный revmux report при этом не
переписывается. Evidence сохраняет точный assignment boundary:

- `block` → `covered_gates: [block_review:Bxx]`, только целевой блок, kernel и
  объявленные dependencies;
- `integration` → `[integration_review]`, только межблочные связи;
- `global` → `[global_review]`, итоговая цель, scope, полнота, проверяемость и
  трассировка;
- `final` → `[integration_review, global_review, project_conformance]`, только
  для combined standard/recovery assignment;
- `project-conformance` → `[project_conformance]`, только объявленные project
  surfaces и их rule sources, без переоткрытия общей семантики.

`review_phase=final` означает подтверждение после correction batch и не меняет
`role_mode`. Для `high` сохраняются отдельные `integration`, `global` и
`project-conformance` assignments; объединять их в role mode `final` нельзя.

Reviewer-driver не выполняет собственный semantic review поверх результата,
не вызывает прежнего reviewer и не запускает следующий round. Revmux не
редактирует постановку. Disposition и один общий correction batch остаются у
координатора и authoring-роли.

Одновременный native model-review и revmux для одного gate запрещены. Исключение
— заранее помеченный `comparison_measurement`, который не создаёт второй gate и
не смешивает findings двух backends в один verdict.

## Материализация контекста round

Revmux не определяет scope сам. После `case_pipeline.py context` сохрани полный
JSON assignment, вызови `revmux new` и передай возвращённые им paths команде:

```text
python3 <vigers-root>/scripts/revmux_review.py prepare \
  --assignment <assignment.json> --case-root <case-root> \
  --profile-source <resolved-vigers-profile.md> \
  --scope-output <revmux-new.scope> --goal-output <revmux-new.goal> \
  --profile-output <revmux-new.profile> --context-dir <revmux-new.context>
```

`prepare` fail-closed проверяет `role_mode`, phase/profile, exact
`covered_gates`, существование каждого `case_input` и `contract_input`, а затем
создаёт:

- `scope.md` — точный target, gate boundary, subject hash и exclusions;
- `goal.md` — вопрос «что относительно чего» и severity bar;
- `context/vigers-assignment.json` — абсолютные paths и SHA-256 всех target,
  case baselines, review contracts и project profile;
- `profile.md` — byte-for-byte frozen resolved `.vigers/profile.md` либо
  встроенный generic profile.

Сравнение задаётся режимом: block artifact/index относительно kernel,
dependencies и decisions; integration — draft относительно всех block indexes;
global — draft относительно frozen goal/requirements/acceptance/traceability;
final — относительно всех перечисленных combined gates; project-conformance —
только относительно project profile и conformance contract. Не включённый в
assignment файл не становится источником review из-за того, что доступен в
worktree. Final round получает новый material fingerprint; прошлые findings в
scope не копируются, потому что revmux инъецирует историю task сам.

Запускай revmux с `--workdir <case-root>` и
`--config-dir <vigers-root>/revmux`, чтобы subprocesses читали именно
материализованный case и skill-local lenses, а не случайный `.revmux/` текущего
репозитория.

## Ограниченный review-цикл

Каждый выбранный revmux review gate содержит:

1. frozen Vigers subject и прошедшие deterministic/document checks;
2. initial `vigers-review` со всеми шестью lenses;
3. disposition findings; только подтверждённые `critical|major` открывают один
   consolidated correction batch, `minor` остаются residual и не запускают
   исправление или review;
4. один `vigers-final` по точному новому subject;
5. terminal `pass`, `failed` либо `user-decision`. Оставшийся/new
   `critical|major` не запускает второй correction round автоматически.

Если assurance требует несколько независимых reviewer gates, сначала собери
их initial findings, примени один общий correction batch к frozen subject и
запусти по одному final confirmation на каждый исходный assignment. Native
reviewer поверх этих же gates не добавляется. Block review остаётся локальным
gate своего Bxx и не ждёт финальной сборки остальных блоков.

Lenses лежат в `revmux/lenses/`: contradictions, scope boundary, acceptance
testability, architecture, traceability и reader projection. Project-specific
правила поступают через frozen `input/profile.md`; generic lens не может
додумать отсутствующее проектное решение. `scope.md` и `goal.md` обязаны назвать
точный `role_mode`; panel применяет линзы только внутри этой границы.
Профили используют независимые Claude subprocesses. Это сохраняет panel
separation и не вызывает Codex CLI рекурсивно из Codex-hosted reviewer.

## Evidence и метрики

Для каждого round сохраняются archive, JSON report, manifest, профиль, subject
hash и evidence, созданное `scripts/revmux_review.py round`. Завершённая пара
initial/final передаётся команде `case`; для block/high case аргументы
`--initial-metrics` и `--final-metrics` повторяются по одному разу на reviewer
gate. Один case receipt суммирует все пары, а 3–5 receipts — команда
`aggregate`.

Обязательные метрики: human active time, revmux elapsed duration, model calls,
tokens, подтверждённые critical/major, correction rounds, новые gating areas в
final и повторившиеся gating areas. `model_calls` включает один свежий
reviewer-driver assignment плюс revmux agent roster, stage prompts и retry
artifacts; неизвестное не подменяется нулём. Tokens
сохраняются раздельно: revmux totals из report и reviewer-driver tokens из
agent ledger; case receipt суммирует их только после обоих completed runs.

Пока backend проходит adoption measurement, решение о permanent enablement
принимает человек только после 3–5 завершённых кейсов. Это свойство журнала
метрик, а не отдельный тип case или review: рабочий assignment, профили и
evidence остаются теми же после смены default. Скрипт отмечает готовность
выборки, но не меняет default.

## Сохранённые границы

Revmux не заменяет planning research, system analysis, solution architecture
design/conformance, authoring/editor, deterministic checks, тесты, live
verification/acceptance, working projection, approval, publication или
development handoff. Отдельный architect остаётся на своих design/conformance
gates; revmux обслуживает только assignments роли `vigers-spec-reviewer`.

Process Auditor не является частью этого backend. Интеграция не включает hooks,
не запускает auditor и не удаляет его skill.
