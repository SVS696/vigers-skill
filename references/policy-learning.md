# Project-local policy learning

Этот контракт замыкает уже существующую telemetry Vigers в безопасный цикл
улучшения процесса. Он оптимизирует orchestration policy, а не смысл требований,
и не передаёт историю, стоимость или рекомендации исполнительным ролям.

## Граница v1

`scripts/policy_learning.py` работает только в `shadow`-режиме:

- собирает один episode из финально валидного case;
- связывает run-level стоимость, findings, dispositions и remediation shape;
- отдельно принимает evidence-bound feedback после handoff;
- сравнивает только точный project-local cohort;
- предлагает replay-эксперимент, но не меняет profile, prompts, роли или case;
- никогда не снижает assurance, не удаляет gate и не применяет кандидата.

Process verdict создаёт отдельный companion `process-auditor`: Vigers не
оценивает собственный процесс и не подменяет независимый аудит внутренним PASS.

V1 не является online reinforcement learning и не переписывает собственный
контракт. Автоматическая promotion отсутствует намеренно. Следующая версия может
появиться только после доказанного frozen replay и отдельного human decision.

## Источники наблюдения

Один episode читает:

- `mode-decision.json`: mode, assurance, change scope, surfaces и risk facts;
- `manifest.json` и `ledger.json`: route, intent, финальные gates и remediation;
- `agent-ledger.json`: роль, mode, model, duration, tokens, retries, lenses,
  reported findings и их штатную verification;
- опциональный post-handoff feedback: исправления человека, уточнения разработки
  и дефекты постановки, подтверждённые внешними evidence refs.
- обязательную для чистого sample пару `process episode + independent verdict`,
  где оба файла проходят полный публичный контракт Process Auditor
  (`episode schema 1` и `verdict schema 2`), а не только проверку binding и KEEP;
  policy-changing `MANUAL_STOP_VALIDATED` без `process_pattern_id` отклоняется
  так же, как каноническим Process Auditor;
  причём Vigers повторно проверяет минимальную `deep`-глубину для manual/guard
  stop и deep-сигналов, а не доверяет одному совпадению двух полей;
  где verdict связан с case, project root и содержит `classification=KEEP`.

`review_scope.mode=targeted_remediation` повторно проверяется по публичному
контракту: source pair и selected finding fingerprints hash-bound, новый finding
и scope expansion запрещены, второй recheck и automatic follow-up невозможны.
Даже валидный targeted `KEEP` не является promotion evidence и не входит в
training cohort: он подтверждает только закрытие выбранного дефекта.

Перед добавлением episode скрипт запускает текущий `case_pipeline.validate_case`
с `final=True`. Нефинальный, stale или structurally invalid case отклоняется.
`failed|timed_out|degraded` run и finding без disposition сохранять как обучающий
sample нельзя. Неизвестные token/tool counters остаются `null`, а не превращаются
в нули.

История живёт по умолчанию в:

```text
<project-root>/.vigers/telemetry/policy-model.json
```

Модель привязана к `profile_id` и canonical project root. История другого проекта
не подмешивается даже при одинаковом profile ID. Повтор одного case идемпотентен;
изменившийся sample требует явного `--replace` после проверки evidence.

Каждый sample имеет происхождение:

- `historical-biased` — старый кейс, который исправлялся вместе с процессом;
  доступен только для ретроспективы и никогда не обучает policy;
- `prospective-clean` — новый прогон с заранее закреплёнными версиями скиллов;
- `frozen-replay` — повтор старого исходного задания без подсматривания в финал.

Только последние два origin могут иметь `training_eligible=true`, и только после
независимого process verdict `KEEP`. `PROCESS_DEFECT`, `EXECUTION_DEFECT`,
manual stop, внешний сбой и evidence gap остаются в Process Auditor и не
становятся доказательством безопасности ablation.

## Внешний quality feedback

Внутренний `PASS` не доказывает отсутствие систематической слепой зоны. Поэтому
кандидат на ablation/recomposition review появляется только когда каждый sample
точного cohort имеет закрытое полное окно внешнего feedback.

Feedback schema 1 содержит:

```json
{
  "schema": 1,
  "case_id": "case-id",
  "coverage": "complete",
  "window_closed": true,
  "observed": {
    "human_rework_count": 0,
    "developer_clarification_count": 0,
    "specification_defects": {
      "blocker": 0,
      "major": 0,
      "minor": 0
    }
  },
  "evidence_refs": [
    {
      "ref": "<local-project-adapter-receipt.json>",
      "sha256": "<sha256>"
    }
  ],
  "recorded_at": "<timestamp>",
  "fingerprint": "<sha256>"
}
```

`complete + window_closed` без evidence binding отклоняется. Binding указывает
на локальный receipt project adapter и фиксирует его SHA-256; missing или changed
receipt блокирует обучение. Partial feedback разрешён как наблюдение, но не
входит в promotion evidence. Нулевые значения нельзя ставить из отсутствия
данных: unavailable source остаётся `coverage: partial`.

Создание feedback:

```text
python3 {baseDir}/scripts/policy_learning.py feedback \
  --case-id "<case-id>" --coverage complete --window-closed \
  --human-rework 0 --developer-clarifications 0 \
  --blocker-defects 0 --major-defects 0 --minor-defects 0 \
  --evidence-file "<local-project-adapter-receipt.json>" \
  --write "<case-feedback.json>"
```

Команда только материализует локальную запись. Она не читает и не меняет tracker,
delivery system или acceptance state; координатор сначала получает evidence
штатным project adapter и проверяет его полноту.

## Обновление project history

После final validation и, если доступно, закрытого feedback:

```text
python3 {baseDir}/scripts/policy_learning.py update \
  --case-root "<case-root>" \
  --profile-id "<profile-id>" \
  --project-root "<project-root>" \
  --origin prospective-clean \
  --feedback "<case-feedback.json>" \
  --process-episode "<process-episode.json>" \
  --process-verdict "<process-verdict.json>"
```

`historical-biased` разрешён без process verdict только как audit-only
наблюдение. `prospective-clean|frozen-replay` без независимой пары отклоняются.
Без `--feedback` чистый episode может участвовать в cost/yield наблюдении, но не
даёт promotion evidence. Если case был законно пересобран и episode изменился,
прочитай новую evidence обратно и только затем повтори команду с `--replace`.

## Shadow-рекомендация

После materialized `mode-decision.json` нового кейса:

```text
python3 {baseDir}/scripts/policy_learning.py suggest \
  --profile-id "<profile-id>" \
  --project-root "<project-root>" \
  --mode-decision "<case-root>/mode-decision.json" \
  --route-id "<route-id>" --intent "<intent>" \
  --write "<case-root>/policy-shadow.json"
```

Exact cohort фиксирует mode, assurance, change scope, surfaces, risk signature,
block bucket, route и intent. Минимум — три training-eligible samples. Ослаблять
сходство в v1 запрещено: маленькая выборка честно возвращает
`insufficient_data`.

Кандидат `extra-review-bundle-ablation-replay` возможен только для прохода сверх
baseline-required `final|block` и только когда:

- assurance не `high`;
- точный cohort достиг минимальной выборки;
- все findings классифицированы;
- каждый sample имеет полный закрытый внешний feedback;
- каждый sample имеет независимый process verdict `KEEP`;
- process episode имеет тот же origin, что и policy sample; historical audit не
  может заверить prospective-clean sample;
- не наблюдалось human rework, developer clarification, blocker или major
  specification defect;
- один и тот же reviewer bundle стабильно присутствовал и не дал принятого
  finding.

Несколько lenses одного run образуют один bundle: telemetry не присваивает общий
finding отдельной lens по догадке. Baseline `final|block` защищён даже при нулевом
yield. Кандидат означает только «проверить удаление дополнительного bundle на
frozen replay». Он не означает, что проход бесполезен или уже удалён.

## Quality floor и promotion boundary

Каждый `policy-shadow.json` машинно фиксирует:

- `auto_apply: false`;
- `assurance_change: false`;
- `gate_removal: false`;
- `role_context_input: false`;
- обязательные frozen replay, human promotion и rollback.

High assurance всегда возвращает `protected_baseline`. Для lite/standard
кандидат не продвигается по результату текущего кейса: нужен отдельный replay на
замороженных источниках, неизменные safety/acceptance gates, независимый blind
review и подтверждение, что экономия не получена удалением обязательного контроля.

V1 заканчивается на shadow evidence. Любая будущая команда `promote` является
новым контрактом и требует отдельного проектирования, тестов и решения человека.

## Валидация

```text
python3 {baseDir}/scripts/policy_learning.py validate \
  --profile-id "<profile-id>" --project-root "<project-root>"
```

Policy history, feedback и shadow report не входят в prompt/context ролей и не
создают новый model call. Если данных недостаточно или quality floor не пройден,
корректный результат — сохранить baseline и продолжить обычный Vigers workflow.
