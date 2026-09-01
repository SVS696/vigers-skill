# Контракт сходимости Vigers

Этот контракт останавливает бесконечное «улучшение ради улучшения». Он действует
для planning research, анализа блоков, author gates, независимых review и
архитектурной проверки. Качество определяется закрытием доказанных рисков, а не
числом итераций или ощущением, что можно поискать ещё.

## Порог качества

Используй общую классификацию findings:

- `blocker` — результат нельзя безопасно передать дальше: нарушена цель,
  отсутствует обязательный контракт или решение, есть критическое противоречие;
- `major` — существенная ошибка в требованиях, приёмке, трассировке, архитектуре
  или проектном правиле, способная привести к неверной реализации или проверке;
- `minor` — локальная ясность, оформление или небольшая неполнота, которая не
  меняет смысл, контракт, архитектуру, проверяемость и решение пользователя.

Если «мелкая» правка способна изменить любую из перечисленных поверхностей,
переклассифицируй её в `major`. Finding без evidence и практического последствия
не входит в цикл исправлений.

Гейт требует `revise` только при открытом принятом `blocker` или `major`.
Оставшиеся `minor` не блокируют переход к следующему пункту approved plan.

## Process YAGNI

Перед добавлением нового шага процесса, артефакта, роли или review gate ответь
по порядку:

1. Какой текущий повторяемый сбой или существенный риск он предотвращает?
2. Может ли тот же риск закрыть deterministic/machine check?
3. Может ли его закрыть текущий semantic owner в существующем проходе?
4. Покрывает ли его уже объявленная review surface?
5. Только если все ответы отрицательны, вводи минимальный новый механизм с exit
   criteria и условием удаления/пересмотра.

Отсутствие blocker/major не является основанием добавить «ещё один контроль для
уверенности». Не создавай отдельный debt/report artifact, если те же данные уже
живут в decision log, manifest, ledger или passport. Process YAGNI не отменяет
обязательный независимый контроль риска; он запрещает дублирующую обвязку.

## Risk-first без постоянного нового гейта

После предварительного анализа пометь только доказанные опасные поверхности
блоков: необратимость, cross-system side effects, partial failure,
retry/recovery, concurrency, cancellation, identity/incarnation,
permissions/security или migration. Если список пуст, дополнительного прохода
нет. Если хотя бы одна поверхность объявлена, один архитектор до authoring
возвращает общую матрицу `block/surface → covered|not-applicable`, конкретные
решения и пустой `unresolved`. `record-risk-preflight` связывает матрицу с
kernel и agent run; high-risk блок нельзя перевести в `in_progress` без неё.

Первый полный reviewer риск-блока закрывает все объявленные surfaces за один
проход и ставит `finding_batch_complete: true`. Это заменяет позднее
последовательное обнаружение связанных edge cases, а не добавляет второй обзор
после уже выполненного полного review.

## Когда разрешено возобновить research

После coverage verdict `sufficient` либо допустимого `partial` не открывай новый
поисковый cluster «на всякий случай». Дополнительный research разрешён только
для принятого `blocker|major` с явным `remediation: targeted-research` и полями:

```yaml
research_question: <какой факт нужен для закрытия finding>
missing_evidence: <чего не хватает в текущем evidence pack>
target_sources: [<конкретные системы или документы>]
stop_condition: <какой результат или отрицательный read-back завершает поиск>
```

`minor` не возобновляет research. Формулировки «копнуть глубже», «проверить ещё
раз» и «поискать альтернативы для уверенности» без указанных полей запрещены.
Targeted research заканчивается по `stop_condition` либо после доказанной
недоступности целевых источников; он не расширяется автоматически на соседние
темы.

## Progressive scope lock

Whole-case review идёт только вперёд по уровням
`block → integration → global → project-conformance → terminal`. Каждый уровень
ищет дефекты только своей новой поверхности:

- block review закрывает локальную семантику одного блока;
- integration review проверяет только швы, зависимости и межблочные инварианты;
- global review проверяет полноту и непротиворечивость постановки целиком;
- project-conformance проверяет только правила и видимую проекцию проекта.

Пройденный уровень становится locked coverage. Более широкий reviewer не
переоткрывает неизменённую локальную поверхность. Если он обнаружил проблему,
координатор фиксирует exact finding IDs, `impact`, affected blocks и semantic
IDs через `record-convergence-review`. Автоматический rewind выбирается по
самой ранней действительно затронутой стадии: `project`, `global` или
`integration`; `block-local` сохраняет текущий whole-case frontier и использует
bounded block remediation. После исправления target → trigger проходят одной
непрерывной цепочкой targeted recheck: конкретный блок, затронутые швы и delta
верхнего уровня. Уже пройденные стадии в этой цепочке не получают новый
`initial/full-stage`, а незатронутые blocks и surfaces вообще не открываются.
Отсутствие impact никогда не означает полный цикл.

Перед повторным reviewer обязателен `complete-convergence-remediation`: команда
связывает evidence исправления и проверяет, что exact subject изменился. Recheck
получает только finding batch, delta и прямые регрессии. Множество открытых
findings должно уменьшаться. Новый finding допустим только с origin
`introduced|exposed-at-changed-boundary` и severity `critical|major`; он
останавливает automatic convergence в `user-decision`. Второй automatic
correction batch на том же уровне запрещён. Обычная targeted remediation не
имеет права выполнять `refresh-kernel` автоматически. Если после открытия
единственного correction batch доказано изменение kernel/scope/архитектуры,
`refresh-kernel` принимает
immutable evidence явного решения пользователя, атомарно завершает targeted
remediation и начинает новый episode. Evidence хранится только в case-local
`decisions/`, `sources/` или `reviews/history/`; mutable kernel/draft/block не
могут подменить пользовательское решение. Атомарный переход из remediation
разрешён только для `semantic-crosscutting|architecture` и требует активной
block-remediation; переход переводит её в `retry_required`, а её budget не
переносится в новый episode. Без такого evidence переход остаётся запрещённым.

## Цикл исправлений

1. Координатор фиксирует disposition каждого finding: `accepted`, `rejected`
   или `user-decision`. Принятый finding получает resolution `open`, затем
   `corrected` либо допустимый для `minor` статус `residual`.
2. Открытые принятые `blocker/major` одного gate сначала объединяются в один
   remediation batch, координатор подтверждает полноту `--batch-complete`, затем
   исправляет его через bounded remediation:
   сохраняются finding evidence, baseline и прежнее покрытие, перечисляются
   точные semantic IDs. Повторный reviewer проверяет finding, delta и прямые
   регрессии, а не начинает аудит неизменённого блока с нуля. Повторяются только
   затронутые deterministic checks и review gate, а не весь завершённый pipeline.
3. Принятые `minor` можно исправить одним общим polish-pass на один review gate,
   если это не меняет смысл. После него выполняется точечная проверка затронутых
   мест; новый полный reviewer ради minor-only улучшений не запускается.
4. Неисправленные `minor` получают resolution `residual` с основанием и
   практическим последствием. Они входят в handoff как остаточные замечания, но
   gate закрывается со статусом `pass`.
5. Новый finding из повторного прохода открывает автоматический rework только
   при явной связи `introduced|exposed-at-changed-boundary` с текущей delta.
   Несвязанное наблюдение в ранее покрытой области не расширяет тот же цикл:
   координатор фиксирует его отдельно и решает приоритет с пользователем.
6. На один блок и kernel epoch разрешён один automatic remediation batch,
   содержащий все принятые findings текущего gate. После его recheck второй
   finding-by-finding цикл запрещён. Если причина архитектурная или
   сквозная, агрегируй её в одно root-cause решение, явно обнови kernel с
   `semantic-crosscutting|architecture` impact и заново пройди полный затронутый
   контракт. Такой root-cause reset автоматически разрешён один раз. Следующий
   reset того же блока требует case-local immutable evidence явного решения
   пользователя через `--user-decision-evidence`; одного coordinator reason
   недостаточно. Иначе верни `user-decision` или bounded targeted research.
7. Новый цикл после `pass` допустим только при новом evidence, изменении
   смыслового артефакта или доказанном новом `blocker/major`. Новые minor-only
   пожелания не переоткрывают гейт.
8. Для whole-case уровней действует максимум один correction batch на каждый
   stage. Это не общий запрет исправлять ошибки разных уровней: integration,
   global и project могут независимо закрыть по одному exact batch. Но recheck
   уровня не начинает новый поиск и не открывает второй batch автоматически.

Targeted remediation автоматически повышается до `full-block-remediation`, если меняется
необъявленный semantic ID либо исправление затрагивает смысл блока целиком.
Изменение цели, scope, публичного контракта, архитектуры или сквозной логики
повышает область ещё дальше до соответствующих whole-case gates. Такое повышение
явное: CLI-флаг остаётся `--full-block`, но reviewer проверяет finding batch,
весь изменённый block delta и прямые регрессии. Отсутствие selector не означает
полный пересмотр или новый поиск дефектов.

## Восстановление уже замороженного case

Если версия постановки уже стабилизирована, а оставшаяся работа вызвана stale
machine state или незакрытыми gates, обычный re-analysis не является допустимым
«ещё одним циклом». После явного решения владельца создай bounded recovery по
`references/bounded-recovery.md`: закрепи kernel/draft/block hashes, точные
review surfaces и конечный набор gates. Recovery не исправляет findings и не
ищет новые требования; он только доказывает frozen subject.

Новый `blocker|major` внутри recovery всегда завершает текущий pass как
`user-decision`. Координатор останавливает recovery, выполняет обычную bounded
remediation после решения и при необходимости начинает новый recovery на новом
subject. Нельзя незаметно превратить recovery во второй remediation batch или
полный review с чистого листа.

## Итог reviewer и решение координатора

Reviewer завершает отчёт полями:

```yaml
reported_blocker: <count>
reported_major: <count>
reported_minor: <count>
research_reopen: no | targeted
gate_recommendation: pass | revise | user-decision
```

Reviewer рекомендует `pass`, когда не нашёл `blocker/major`, и `revise`, когда
нашёл хотя бы один. Рекомендация остаётся независимой: reviewer не знает будущие
решения координатора.

После disposition координатор записывает gate summary:

```yaml
open_blocker: <accepted and unresolved count>
open_major: <accepted and unresolved count>
open_minor: <accepted and unresolved count>
gate_decision: pass | revise | user-decision
```

- `pass` — нет открытых принятых `blocker/major`; residual minor допустимы;
- `revise` — остался хотя бы один открытый принятый `blocker/major`;
- `user-decision` — нужен выбор владельца либо существенный finding остался или
  появился после единственного bounded recheck.

Координатор не закрывает гейт по одной рекомендации: он сверяет reported counts,
dispositions, evidence, open counts и residual log. При `pass` pipeline сразу
переходит к следующему пункту approved plan.

## Пример границы глубины

Если независимое review B02/B03 нашло blocker и несколько major, исправь их
контракты и счётные правила, повтори затронутое review и затем интегрируй блоки.
Не запускай новый археологический поиск, пока конкретный blocker/major не назвал
точную evidence-дыру и `stop_condition`. Когда остались только minor, зафиксируй
их либо выполни один polish-pass и продолжай сборку следующего блока.
