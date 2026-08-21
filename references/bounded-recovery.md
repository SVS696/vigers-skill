# Bounded recovery Vigers

Этот контур завершает уже стабилизированную постановку, когда обычный case-state
успел разнести старые статусы, но новая смысловая работа не требуется. Он не
заменяет обычный analysis/remediation pipeline и не мигрирует legacy case
автоматически.

## Когда применять

Применяй bounded recovery только после явного решения владельца заморозить
конкретные `kernel.md`, `draft.md` и содержимое выбранных blocks. Типичный случай:
широкая инвалидация сделала ранее проверенные блоки `stale`, поздние замечания уже
классифицированы, а оставшаяся работа — точная переаттестация и закрытие gates.

Не применяй recovery, если требуется новый research, изменение цели/scope,
исправление принятого `blocker|major`, новая архитектура или содержательная
перепись блока. Сначала выполни обычную bounded remediation, получи новую
стабильную версию и только затем создай recovery plan.

## План

Координатор создаёт JSON schema 1 и передаёт его явной командой. Минимальная
форма:

```json
{
  "schema": 1,
  "case_id": "frontend-123",
  "reason": "Finish the frozen revision without reopening analysis",
  "requested_terminal_state": "local-green",
  "kernel_revision": 6,
  "kernel_sha256": "<sha256>",
  "draft_sha256": "<sha256>",
  "block_scopes": {
    "B02": ["SCN-B02-001", "shared-principal"],
    "B03": ["error-boundary"]
  },
  "allowed_gates": [
    "integration_review",
    "global_review",
    "project_conformance"
  ],
  "combine_final_review": true,
  "new_findings_policy": "user-decision",
  "research": "forbidden",
  "content_mutation": "forbidden",
  "kernel_refresh": "forbidden",
  "max_agent_attempts_per_assignment": 2,
  "deferred_findings": []
}
```

`block_scopes` перечисляет не темы для свободного аудита, а точные semantic IDs
или стабильные поверхности, которые ещё надо подтвердить. Известные поздние
findings, не входящие в текущую работу, сохраняются в `deferred_findings`:
`blocker|major` допускают только `user-decision`; `residual` допустим только для
`minor` и требует основания. `allowed_gates` обязан включать каждый gate,
который в момент старта ещё `pending|blocked`, а также формально `pass`, если
его evidence или subject уже устарел. Только актуальные `pass|not_required`
повторять не требуется.

## Команды и переходы

```bash
python3 scripts/case_pipeline.py begin-recovery \
  --case-root <case> --plan <recovery-plan.json>

python3 scripts/case_pipeline.py rebase-recovery-block \
  --case-root <case> --id B03

python3 scripts/case_pipeline.py context \
  --case-root <case> --block B03 --role spec-reviewer --role-mode block

python3 scripts/case_pipeline.py complete-recovery \
  --case-root <case> --note "Frozen revision is locally green"
```

`begin-recovery` копирует и хеширует план, снимает baseline выбранных block
artifacts/indexes и ничего не меняет в их истории. `rebase-recovery-block`
переносит только machine metadata `kernel_revision` у неизменённого `stale`
блока и переводит его в `analyzed`; содержимое artifact и semantic index
проверяется по baseline. После bounded review блок проходит обычные
`analyzed → reviewed → integrated`.

Во время active recovery машина запрещает `refresh-kernel`, planning migration,
новые blocks/risks, authoring, `begin-remediation`, `record-change` и
`record-remediation`. Изменение frozen draft, kernel, block artifact или
semantic meaning index делает validation красной.

Если найден новый существенный дефект, не вписывай его в текущий pass. Выполни:

```bash
python3 scripts/case_pipeline.py stop-recovery \
  --case-root <case> --reason "REV-021 requires a user decision"
```

После решения выполняется обычная targeted/full remediation. Новый recovery
начинается отдельным планом уже на новой замороженной версии; предыдущий план
архивируется.

## Evidence block review

Block reviewer получает только recovery plan, kernel, целевой block/index и его
прямые dependencies. Method context, evidence pack, decisions, прошлые reviews,
другие blocks и внешний research исключены. Его report обязан содержать:

Адаптер роли обязан распознать machine-bound
`review_scope=bounded-recovery|bounded-recovery-final`: отсутствие
`method-context.*` здесь является требуемой изоляцией, а не `input-error`.
Reviewer сверяет recovery plan, exact subject и переданные surfaces/gates.

```yaml
review_scope: bounded-recovery
recovery_plan_sha256: <sha256>
recovery_block: B03
recovery_subject_sha256: <subject from context>
reviewed_surfaces: [error-boundary]
new_findings_policy: user-decision
deferred_findings: []
agent_run_id: AR-0007
decision: pass
```

Machine gate принимает только точное совпадение surface list и completed
`spec-reviewer/block` run текущего subject. Любой новый finding означает, что
`deferred_findings` уже не пуст и pass невозможен: recovery останавливается на
decision boundary.

## Combined final review

`combine_final_review=true` разрешает один свежий `spec-reviewer/final` даже у
legacy/high case, но только для frozen recovery и только для трёх gates:
`integration_review`, `global_review`, `project_conformance`. Это не ослабление
проверки: один assignment получает draft, все semantic indexes и применимые
project contracts, а evidence привязан к одному exact subject.

```yaml
review_scope: bounded-recovery-final
recovery_plan_sha256: <sha256>
recovery_subject_sha256: <subject from context>
covered_gates: [integration_review, global_review, project_conformance]
new_findings_policy: user-decision
deferred_findings: []
agent_run_id: AR-0008
decision: pass
```

Architecture conformance остаётся отдельной ролью, если gate перечислен в
`allowed_gates`. `complete-recovery` требует `integrated` для каждого declared
block, актуальный `pass|not_required` для каждого case gate и зелёную final
validation, включая terminal automation stage и живой read-back обязательных
checklist items. Required gate обычная state machine всё равно не даст отметить
`not_required`. Статус `complete` записывается только после этого preflight;
ошибка оставляет recovery активным.

## Supervisor

Один assignment определяется тройкой `role + role_mode + subject_sha256`.
Допустимы максимум две попытки суммарно: исходная и один retry. Terminal
`completed|degraded` запрещает повтор того же assignment; третий
`failed|timed_out` также отвергается машиной. Новый subject создаёт новый
assignment, но active recovery не позволяет получить его скрытым изменением
контента.
