#!/usr/bin/env python3
"""Record and aggregate automated Vigers wall-clock execution time."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import statistics
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
FILENAME = "automation-timing.json"
POLICIES = {"optional", "required", "measured", "disabled"}
METRIC = "wall_clock"
UNIT = "seconds"
EXECUTION_USE = "human_information_only"
ESTIMATE_BASES = {"historical", "analogous", "heuristic"}
CONFIDENCE_LEVELS = {"low", "medium", "high"}
TERMINAL_STATUSES = {"completed", "failed", "blocked", "cancelled"}
STAGE_STATUSES = {"pending", "running", *TERMINAL_STATUSES}
CHECKLIST_STATUSES = {"pending", "in_progress", "completed"}
PAUSE_REASONS = {
    "user_pause",
    "limit_exhausted",
    "external_wait",
    "interrupted",
    "deferred",
}
USER_PAUSE_REASONS = PAUSE_REASONS - {"deferred"}
CASE_STATES = {"active", "deferred", "ready_for_handoff", "handed_off"}


class AutomationTimingError(RuntimeError):
    """Invalid automation timing plan, ledger, or transition."""


def now_utc() -> str:
    """Return a compact UTC timestamp with second precision."""
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def canonical_fingerprint(payload: dict[str, Any]) -> str:
    """Hash a JSON object without its own fingerprint field."""
    material = {key: value for key, value in payload.items() if key != "fingerprint"}
    encoded = json.dumps(
        material,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def atomic_json(path: Path, payload: Any) -> None:
    """Write JSON through a sibling temporary file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def parse_timestamp(value: Any, *, field: str) -> datetime:
    """Parse one timezone-aware ISO timestamp and normalize it to UTC."""
    if not isinstance(value, str) or not value.strip():
        raise AutomationTimingError(f"{field} must be a non-empty ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise AutomationTimingError(f"{field} is not a valid ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise AutomationTimingError(f"{field} must include timezone offset")
    return parsed.astimezone(UTC).replace(microsecond=0)


def normalized_timestamp(value: str | None) -> str:
    """Normalize an optional user timestamp, otherwise use current UTC."""
    if value is None:
        return now_utc()
    return parse_timestamp(value, field="timestamp").isoformat()


def validate_projection_readbacks(payload: Any, *, prefix: str) -> list[str]:
    """Validate provider-neutral state projection evidence."""
    errors: list[str] = []
    if not isinstance(payload, list):
        return [f"{prefix} projection_readbacks must be an array"]
    systems: set[str] = set()
    for index, item in enumerate(payload, start=1):
        label = f"{prefix} projection_readbacks[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{label} must be an object")
            continue
        for field in ("system", "item_id", "state", "read_back_at"):
            if not isinstance(item.get(field), str) or not item[field].strip():
                errors.append(f"{label} missing {field}")
        previous_state = item.get("previous_state")
        if previous_state is not None and not isinstance(previous_state, dict):
            errors.append(f"{label} previous_state must be an object or null")
        system = item.get("system")
        if isinstance(system, str):
            if system in systems:
                errors.append(f"{prefix} has duplicate read-back system {system}")
            systems.add(system)
        try:
            parse_timestamp(item.get("read_back_at"), field=f"{label}.read_back_at")
        except AutomationTimingError as exc:
            errors.append(str(exc))
    return errors


def current_case_state(ledger: dict[str, Any]) -> str:
    """Return explicit lifecycle state or derive the compatible legacy state."""
    state = ledger.get("case_state")
    if isinstance(state, dict) and state.get("status") in CASE_STATES:
        return str(state["status"])
    if any(
        item.get("kind") == "development_handoff"
        for item in ledger.get("milestones", [])
        if isinstance(item, dict)
    ):
        return "handed_off"
    return "active"


def require_active_case(ledger: dict[str, Any], *, action: str) -> None:
    state = current_case_state(ledger)
    if state != "active":
        raise AutomationTimingError(f"Cannot {action} while case state is {state}")


def validate_estimate(payload: Any, *, prefix: str) -> list[str]:
    """Validate one three-point stage estimate."""
    errors: list[str] = []
    if not isinstance(payload, dict):
        return [f"{prefix} automation_estimate must be an object"]

    values: list[int] = []
    for field in ("optimistic_seconds", "likely_seconds", "pessimistic_seconds"):
        value = payload.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            errors.append(f"{prefix} automation_estimate {field} must be a positive integer")
        else:
            values.append(value)
    if len(values) == 3 and not values[0] <= values[1] <= values[2]:
        errors.append(
            f"{prefix} automation_estimate must satisfy optimistic <= likely <= pessimistic"
        )

    if payload.get("basis") not in ESTIMATE_BASES:
        errors.append(
            f"{prefix} automation_estimate basis must be one of {sorted(ESTIMATE_BASES)}"
        )
    if payload.get("confidence") not in CONFIDENCE_LEVELS:
        errors.append(
            f"{prefix} automation_estimate confidence must be one of "
            f"{sorted(CONFIDENCE_LEVELS)}"
        )
    sample_size = payload.get("sample_size")
    if not isinstance(sample_size, int) or isinstance(sample_size, bool) or sample_size < 0:
        errors.append(f"{prefix} automation_estimate sample_size must be a non-negative integer")
    return errors


def validate_plan_estimation(plan_payload: Any) -> list[str]:
    """Validate the automation estimation fields of a planning plan."""
    errors: list[str] = []
    if not isinstance(plan_payload, dict):
        return ["plan.json must be an object"]
    policy = plan_payload.get("automation_estimation")
    if not isinstance(policy, dict):
        return ["plan.json automation_estimation must be an object"]
    selected_policy = policy.get("policy")
    if selected_policy not in {"required", "measured", "disabled"}:
        errors.append(
            "plan.json automation_estimation policy must be required, measured, or disabled"
        )
    if policy.get("metric") != METRIC:
        errors.append(f"plan.json automation_estimation metric must be {METRIC}")
    if policy.get("unit") != UNIT:
        errors.append(f"plan.json automation_estimation unit must be {UNIT}")
    if policy.get("execution_use") != EXECUTION_USE:
        errors.append(
            "plan.json automation_estimation execution_use must be "
            f"{EXECUTION_USE}"
        )

    stages = plan_payload.get("stages")
    if not isinstance(stages, list) or not stages:
        return errors
    if selected_policy == "required":
        for stage in stages:
            stage_id = stage.get("id", "<unknown>") if isinstance(stage, dict) else "<unknown>"
            estimate = stage.get("automation_estimate") if isinstance(stage, dict) else None
            errors.extend(validate_estimate(estimate, prefix=str(stage_id)))
    else:
        for stage in stages:
            if isinstance(stage, dict) and stage.get("automation_estimate") is not None:
                errors.append(
                    f"{stage.get('id', '<unknown>')}: {selected_policy} timing must not ask "
                    "the planning model for an estimate"
                )
    return errors


def build_automation_plan(plan_payload: dict[str, Any]) -> dict[str, Any]:
    """Create the immutable automation plan carried by planning handoff."""
    errors = validate_plan_estimation(plan_payload)
    if errors:
        raise AutomationTimingError("; ".join(errors))
    policy = plan_payload["automation_estimation"]
    stages = [
        {
            "id": stage["id"],
            "title": stage["title"],
            "depends_on": list(stage.get("depends_on", [])),
            "estimate": (
                dict(stage["automation_estimate"])
                if policy["policy"] == "required"
                else None
            ),
            "external_target_id": stage.get("external_target_id"),
            "checklist": [
                {
                    "id": item["id"],
                    "text": item["text"],
                    "required": item.get("required", True),
                    "done_when": item.get("done_when"),
                    "completion_owner": item.get("completion_owner", "agent"),
                }
                for item in stage.get("checklist", [])
            ],
        }
        for stage in plan_payload["stages"]
    ]
    result: dict[str, Any] = {
        "policy": policy["policy"],
        "metric": policy["metric"],
        "unit": policy["unit"],
        "execution_use": policy["execution_use"],
        "stages": stages,
    }
    if isinstance(plan_payload.get("progress_target_id"), str) and plan_payload[
        "progress_target_id"
    ].strip():
        result["progress_target_id"] = plan_payload["progress_target_id"].strip()
    result["fingerprint"] = canonical_fingerprint(result)
    return result


def validate_automation_plan(payload: Any) -> list[str]:
    """Validate an immutable handoff automation plan."""
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["automation plan must be an object"]
    if payload.get("policy") not in POLICIES:
        errors.append(f"automation plan policy must be one of {sorted(POLICIES)}")
    if payload.get("metric") != METRIC:
        errors.append(f"automation plan metric must be {METRIC}")
    if payload.get("unit") != UNIT:
        errors.append(f"automation plan unit must be {UNIT}")
    if payload.get("execution_use") != EXECUTION_USE:
        errors.append(f"automation plan execution_use must be {EXECUTION_USE}")
    progress_target_id = payload.get("progress_target_id")
    if progress_target_id is not None and (
        not isinstance(progress_target_id, str) or not progress_target_id.strip()
    ):
        errors.append("automation plan progress_target_id must be non-empty text or null")
    stages = payload.get("stages")
    if not isinstance(stages, list):
        errors.append("automation plan stages must be an array")
        return errors

    ids: set[str] = set()
    checklist_ids: set[str] = set()
    dependencies: dict[str, list[str]] = {}
    for stage in stages:
        if not isinstance(stage, dict):
            errors.append("automation plan stage must be an object")
            continue
        stage_id = stage.get("id")
        if not isinstance(stage_id, str) or not stage_id.strip():
            errors.append("automation plan stage requires id")
            continue
        if stage_id in ids:
            errors.append(f"automation plan duplicate stage id: {stage_id}")
        ids.add(stage_id)
        if not isinstance(stage.get("title"), str) or not stage["title"].strip():
            errors.append(f"{stage_id}: automation plan title is required")
        depends_on = stage.get("depends_on")
        if not isinstance(depends_on, list) or not all(
            isinstance(item, str) and item.strip() for item in depends_on
        ):
            errors.append(f"{stage_id}: automation plan depends_on must be string array")
            dependencies[stage_id] = []
        else:
            dependencies[stage_id] = list(depends_on)
        if payload.get("policy") in {"required", "optional"}:
            errors.extend(validate_estimate(stage.get("estimate"), prefix=stage_id))
        elif stage.get("estimate") is not None:
            errors.append(f"{stage_id}: measured/disabled plan estimate must be null")
        external_target_id = stage.get("external_target_id")
        if external_target_id is not None and (
            not isinstance(external_target_id, str) or not external_target_id.strip()
        ):
            errors.append(f"{stage_id}: external_target_id must be non-empty text or null")
        checklist = stage.get("checklist")
        if not isinstance(checklist, list) or not checklist:
            errors.append(f"{stage_id}: automation plan checklist must be non-empty")
            continue
        for item in checklist:
            if not isinstance(item, dict):
                errors.append(f"{stage_id}: automation plan checklist items must be objects")
                continue
            item_id = item.get("id")
            if not isinstance(item_id, str) or not item_id.strip():
                errors.append(f"{stage_id}: automation plan checklist item requires id")
            elif item_id in checklist_ids:
                errors.append(f"automation plan duplicate checklist id: {item_id}")
            else:
                checklist_ids.add(item_id)
            if not isinstance(item.get("text"), str) or not item["text"].strip():
                errors.append(f"{item_id}: automation plan checklist text is required")
            if not isinstance(item.get("required"), bool):
                errors.append(f"{item_id}: automation plan checklist required must be boolean")
            done_when = item.get("done_when")
            if done_when is not None and (
                not isinstance(done_when, str) or not done_when.strip()
            ):
                errors.append(f"{item_id}: automation plan checklist done_when is invalid")
            if item.get("completion_owner", "agent") not in {"agent", "user"}:
                errors.append(
                    f"{item_id}: automation plan completion_owner must be agent or user"
                )

    for stage_id, items in dependencies.items():
        for dependency in items:
            if dependency not in ids:
                errors.append(f"{stage_id}: unknown automation dependency {dependency}")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(stage_id: str) -> None:
        if stage_id in visiting:
            raise AutomationTimingError(f"automation plan dependency cycle at {stage_id}")
        if stage_id in visited:
            return
        visiting.add(stage_id)
        for dependency in dependencies.get(stage_id, []):
            if dependency in dependencies:
                visit(dependency)
        visiting.remove(stage_id)
        visited.add(stage_id)

    try:
        for stage_id in dependencies:
            visit(stage_id)
    except AutomationTimingError as exc:
        errors.append(str(exc))

    fingerprint = payload.get("fingerprint")
    if not isinstance(fingerprint, str) or fingerprint != canonical_fingerprint(payload):
        errors.append("automation plan fingerprint mismatch")
    return errors


def initialize_ledger(
    *,
    case_id: str,
    automation_plan: dict[str, Any] | None,
    planning_case_id: str | None,
    planning_revision: int | None,
    passport: dict[str, Any] | None,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Create a timing ledger from an approved planning handoff."""
    timestamp = normalized_timestamp(created_at)
    if automation_plan is None:
        automation_plan = {
            "policy": "optional",
            "metric": METRIC,
            "unit": UNIT,
            "execution_use": EXECUTION_USE,
            "stages": [],
        }
        automation_plan["fingerprint"] = canonical_fingerprint(automation_plan)
    errors = validate_automation_plan(automation_plan)
    if errors:
        raise AutomationTimingError("; ".join(errors))

    dual_timer = automation_plan["policy"] == "measured"
    timing_disabled = automation_plan["policy"] == "disabled"
    ledger = {
        "schema": SCHEMA_VERSION,
        "case_id": case_id,
        "policy": automation_plan["policy"],
        "metric": automation_plan["metric"],
        "unit": automation_plan["unit"],
        "execution_use": automation_plan["execution_use"],
        "planning": (
            {
                "case_id": planning_case_id,
                "revision": planning_revision,
                "automation_plan_fingerprint": automation_plan["fingerprint"],
            }
            if planning_case_id is not None
            else None
        ),
        "passport": passport,
        "plan_fingerprint": automation_plan["fingerprint"],
        **(
            {
                "progress_target_id": automation_plan["progress_target_id"],
                "progress_projection": {
                    "source": "plan",
                    "progress_target_id": automation_plan["progress_target_id"],
                    "system": None,
                    "target_id": None,
                    "bindings": [],
                    "bound_at": None,
                    "migration_evidence": None,
                },
            }
            if isinstance(automation_plan.get("progress_target_id"), str)
            and automation_plan["progress_target_id"].strip()
            else {}
        ),
        "created_at": timestamp,
        "updated_at": timestamp,
        "case_state": {
            "status": "active",
            "changed_at": timestamp,
            "reason": None,
            "evidence_ref": None,
            "resume_status": None,
            "projection_readbacks": [],
        },
        "stages": [
            {
                "id": stage["id"],
                "title": stage["title"],
                "depends_on": list(stage["depends_on"]),
                "estimate": (
                    dict(stage["estimate"])
                    if isinstance(stage.get("estimate"), dict)
                    else None
                ),
                "external_target_id": stage.get("external_target_id"),
                "checklist": [
                    {
                        "id": item["id"],
                        "text": item["text"],
                        "required": item["required"],
                        "done_when": item.get("done_when"),
                        "completion_owner": item.get("completion_owner", "agent"),
                        "completion_owner_declared": "completion_owner" in item,
                        "status": "pending",
                        "started_at": None,
                        "parallel_reason": None,
                        "completed_at": None,
                        "evidence_refs": [],
                        "external_read_back": None,
                        "completion_confirmation": None,
                    }
                    for item in stage["checklist"]
                ],
                "status": "pending",
                "started_at": None,
                "finished_at": None,
                "actual_seconds": None,
                "terminal_reason": None,
                **(
                    {
                        "active_started_at": None,
                        "active_seconds": 0,
                        "elapsed_seconds": None,
                        "pause_started_at": None,
                        "pause_reason": None,
                        "pauses": [],
                    }
                    if dual_timer
                    else {}
                ),
            }
            for stage in automation_plan["stages"]
        ],
        "events": [],
        **(
            {"timer_model": "dual", "milestones": []}
            if dual_timer
            else ({"timer_model": "disabled"} if timing_disabled else {})
        ),
    }
    return ledger


def ledger_automation_plan(ledger: dict[str, Any]) -> dict[str, Any]:
    """Extract immutable plan fields from a mutable timing ledger."""
    result: dict[str, Any] = {
        "policy": ledger.get("policy"),
        "metric": ledger.get("metric"),
        "unit": ledger.get("unit"),
        "execution_use": ledger.get("execution_use"),
        "stages": [
            {
                "id": stage.get("id"),
                "title": stage.get("title"),
                "depends_on": stage.get("depends_on"),
                "estimate": stage.get("estimate"),
                "external_target_id": stage.get("external_target_id"),
                "checklist": [
                    {
                        "id": item.get("id"),
                        "text": item.get("text"),
                        "required": item.get("required"),
                        "done_when": item.get("done_when"),
                        **(
                            {
                                "completion_owner": item.get(
                                    "completion_owner", "agent"
                                )
                            }
                            if item.get("completion_owner_declared") is True
                            else {}
                        ),
                    }
                    for item in stage.get("checklist", [])
                    if isinstance(item, dict)
                ],
            }
            for stage in ledger.get("stages", [])
            if isinstance(stage, dict)
        ],
    }
    progress_projection = ledger.get("progress_projection")
    if (
        isinstance(ledger.get("progress_target_id"), str)
        and not (
            isinstance(progress_projection, dict)
            and progress_projection.get("source") == "migration"
        )
    ):
        result["progress_target_id"] = ledger["progress_target_id"]
    result["fingerprint"] = canonical_fingerprint(result)
    return result


def runtime_checklist_index(ledger: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return every runtime checklist item keyed by its stable local id."""
    result: dict[str, dict[str, Any]] = {}
    for stage in ledger.get("stages", []):
        if not isinstance(stage, dict):
            continue
        for item in stage.get("checklist", []):
            if isinstance(item, dict) and isinstance(item.get("id"), str):
                result[item["id"]] = item
    return result


def normalized_progress_receipt(
    payload: Any,
    *,
    require_readbacks: bool,
) -> dict[str, Any]:
    """Validate and normalize one provider-neutral checklist projection receipt."""
    if not isinstance(payload, dict) or payload.get("schema") != 1:
        raise AutomationTimingError("Progress receipt must be a schema-1 object")
    result: dict[str, Any] = {"schema": 1}
    for field in ("progress_target_id", "system", "target_id"):
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            raise AutomationTimingError(f"Progress receipt requires {field}")
        result[field] = value.strip()

    bindings = payload.get("bindings")
    if not isinstance(bindings, list) or not bindings:
        raise AutomationTimingError("Progress receipt bindings must be a non-empty array")
    normalized_bindings: list[dict[str, Any]] = []
    local_ids: set[str] = set()
    external_ids: set[str] = set()
    for index, binding in enumerate(bindings, start=1):
        if not isinstance(binding, dict):
            raise AutomationTimingError(f"Progress binding {index} must be an object")
        local_item_id = binding.get("local_item_id")
        external_item_id = binding.get("external_item_id")
        title = binding.get("title")
        if not isinstance(local_item_id, str) or not local_item_id.strip():
            raise AutomationTimingError(f"Progress binding {index} requires local_item_id")
        if not isinstance(external_item_id, str) or not external_item_id.strip():
            raise AutomationTimingError(f"Progress binding {index} requires external_item_id")
        if not isinstance(title, str) or not title.strip():
            raise AutomationTimingError(f"Progress binding {index} requires title")
        local_item_id = local_item_id.strip()
        external_item_id = external_item_id.strip()
        title = title.strip()
        if not title.startswith(local_item_id):
            raise AutomationTimingError(
                f"Progress binding {local_item_id} title must start with its stable id"
            )
        if local_item_id in local_ids:
            raise AutomationTimingError(f"Duplicate progress binding for {local_item_id}")
        if external_item_id in external_ids:
            raise AutomationTimingError(
                f"Duplicate external checklist binding {external_item_id}"
            )
        local_ids.add(local_item_id)
        external_ids.add(external_item_id)
        normalized_bindings.append(
            {
                "local_item_id": local_item_id,
                "external_item_id": external_item_id,
                "title": title,
            }
        )
    result["bindings"] = sorted(
        normalized_bindings,
        key=lambda item: item["local_item_id"],
    )

    readbacks = payload.get("readbacks", [])
    if not isinstance(readbacks, list):
        raise AutomationTimingError("Progress receipt readbacks must be an array")
    if require_readbacks and not readbacks:
        raise AutomationTimingError("Progress reconciliation requires readbacks")
    normalized_readbacks: list[dict[str, Any]] = []
    readback_ids: set[str] = set()
    for index, readback in enumerate(readbacks, start=1):
        if not isinstance(readback, dict):
            raise AutomationTimingError(f"Progress read-back {index} must be an object")
        local_item_id = readback.get("local_item_id")
        external_item_id = readback.get("external_item_id")
        title = readback.get("title")
        checked = readback.get("checked")
        if not isinstance(local_item_id, str) or not local_item_id.strip():
            raise AutomationTimingError(f"Progress read-back {index} requires local_item_id")
        if not isinstance(external_item_id, str) or not external_item_id.strip():
            raise AutomationTimingError(f"Progress read-back {index} requires external_item_id")
        if not isinstance(title, str) or not title.strip():
            raise AutomationTimingError(f"Progress read-back {index} requires title")
        if not isinstance(checked, bool):
            raise AutomationTimingError(f"Progress read-back {index} checked must be boolean")
        local_item_id = local_item_id.strip()
        external_item_id = external_item_id.strip()
        title = title.strip()
        if local_item_id in readback_ids:
            raise AutomationTimingError(f"Duplicate progress read-back for {local_item_id}")
        if not title.startswith(local_item_id):
            raise AutomationTimingError(
                f"Progress read-back {local_item_id} title must start with its stable id"
            )
        readback_ids.add(local_item_id)
        normalized_readbacks.append(
            {
                "local_item_id": local_item_id,
                "external_item_id": external_item_id,
                "title": title,
                "checked": checked,
                "read_back_at": parse_timestamp(
                    readback.get("read_back_at"),
                    field=f"progress read-back {local_item_id}.read_back_at",
                ).isoformat(),
            }
        )
    if require_readbacks and readback_ids != local_ids:
        missing = sorted(local_ids - readback_ids)
        extra = sorted(readback_ids - local_ids)
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if extra:
            details.append("unknown " + ", ".join(extra))
        raise AutomationTimingError(
            "Progress reconciliation must read back every binding: " + "; ".join(details)
        )
    result["readbacks"] = sorted(
        normalized_readbacks,
        key=lambda item: item["local_item_id"],
    )
    return result


def validate_progress_projection(payload: dict[str, Any]) -> list[str]:
    """Validate the bound checklist target, stable item bindings, and read-backs."""
    errors: list[str] = []
    progress_target_id = payload.get("progress_target_id")
    projection = payload.get("progress_projection")
    if progress_target_id is None and projection is None:
        return errors
    if not isinstance(progress_target_id, str) or not progress_target_id.strip():
        errors.append("progress_target_id must be non-empty text")
        return errors
    if not isinstance(projection, dict):
        errors.append("progress_projection contract is required")
        return errors
    if projection.get("source") not in {"plan", "migration"}:
        errors.append("progress_projection source must be plan or migration")
    if projection.get("progress_target_id") != progress_target_id:
        errors.append("progress_projection target differs from progress_target_id")

    checklist = runtime_checklist_index(payload)
    bindings = projection.get("bindings")
    if not isinstance(bindings, list):
        errors.append("progress_projection bindings must be an array")
        bindings = []
    unbound = (
        projection.get("system") is None
        and projection.get("target_id") is None
        and projection.get("bound_at") is None
        and not bindings
    )
    if unbound:
        if any(item.get("status") == "completed" for item in checklist.values()):
            errors.append("completed checklist items require a bound progress projection")
        return errors
    for field in ("system", "target_id"):
        if not isinstance(projection.get(field), str) or not projection[field].strip():
            errors.append(f"progress_projection requires {field}")
    try:
        parse_timestamp(projection.get("bound_at"), field="progress_projection.bound_at")
    except AutomationTimingError as exc:
        errors.append(str(exc))
    migration_evidence = projection.get("migration_evidence")
    if projection.get("source") == "migration":
        if not isinstance(migration_evidence, str) or not migration_evidence.strip():
            errors.append("migrated progress_projection requires migration_evidence")
    elif migration_evidence is not None:
        errors.append("plan-bound progress_projection cannot have migration_evidence")

    binding_by_local: dict[str, dict[str, Any]] = {}
    external_ids: set[str] = set()
    for binding in bindings:
        if not isinstance(binding, dict):
            errors.append("progress_projection bindings must be objects")
            continue
        local_item_id = binding.get("local_item_id")
        external_item_id = binding.get("external_item_id")
        title = binding.get("title")
        if not isinstance(local_item_id, str) or local_item_id not in checklist:
            errors.append(f"progress_projection has unknown local item {local_item_id!r}")
            continue
        if local_item_id in binding_by_local:
            errors.append(f"progress_projection duplicates binding {local_item_id}")
        binding_by_local[local_item_id] = binding
        if not isinstance(external_item_id, str) or not external_item_id.strip():
            errors.append(f"{local_item_id}: progress binding requires external_item_id")
        elif external_item_id in external_ids:
            errors.append(f"progress_projection duplicates external item {external_item_id}")
        else:
            external_ids.add(external_item_id)
        if not isinstance(title, str) or not title.strip() or not title.startswith(local_item_id):
            errors.append(f"{local_item_id}: progress binding title must start with stable id")
        last_read_back = binding.get("last_read_back")
        if last_read_back is not None:
            if not isinstance(last_read_back, dict):
                errors.append(f"{local_item_id}: last_read_back must be an object or null")
            else:
                try:
                    parse_timestamp(
                        last_read_back.get("read_back_at"),
                        field=f"{local_item_id}.last_read_back.read_back_at",
                    )
                except AutomationTimingError as exc:
                    errors.append(str(exc))
                if last_read_back.get("item_id") != external_item_id:
                    errors.append(f"{local_item_id}: last read-back item mismatch")
                if not isinstance(last_read_back.get("checked"), bool):
                    errors.append(f"{local_item_id}: last read-back checked must be boolean")
    missing_bindings = sorted(set(checklist) - set(binding_by_local))
    if missing_bindings:
        errors.append("progress_projection misses bindings: " + ", ".join(missing_bindings))

    for local_item_id, item in checklist.items():
        if item.get("status") != "completed":
            continue
        binding = binding_by_local.get(local_item_id)
        read_back = item.get("external_read_back")
        if not isinstance(binding, dict):
            continue
        if not isinstance(read_back, dict):
            errors.append(f"{local_item_id}: completed projected item requires read-back")
            continue
        expected = {
            "progress_target_id": progress_target_id,
            "system": projection.get("system"),
            "target_id": projection.get("target_id"),
            "item_id": binding.get("external_item_id"),
        }
        for field, expected_value in expected.items():
            if read_back.get(field) != expected_value:
                errors.append(f"{local_item_id}: external read-back {field} mismatch")
        if read_back.get("checked") is not True:
            errors.append(f"{local_item_id}: external read-back must confirm checked=true")
        title = read_back.get("title")
        if not isinstance(title, str) or not title.startswith(local_item_id):
            errors.append(f"{local_item_id}: external read-back title mismatch")
        try:
            parse_timestamp(
                read_back.get("read_back_at"),
                field=f"{local_item_id}.external_read_back.read_back_at",
            )
        except AutomationTimingError as exc:
            errors.append(str(exc))
    return errors


def validate_ledger(
    payload: Any,
    *,
    final: bool = False,
    expected_case_id: str | None = None,
    expected_plan: dict[str, Any] | None = None,
    expected_planning_case_id: str | None = None,
    expected_planning_revision: int | None = None,
) -> list[str]:
    """Validate timing structure, transitions, linkage, and optional final state."""
    errors: list[str] = []
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA_VERSION:
        return ["automation-timing.json unsupported schema"]
    errors.extend(validate_progress_projection(payload))
    timer_model = payload.get("timer_model", "legacy")
    if timer_model not in {"legacy", "dual", "disabled"}:
        errors.append("automation timing timer_model is invalid")
    expected_timer_model = {
        "measured": "dual",
        "disabled": "disabled",
    }.get(payload.get("policy"), "legacy")
    if timer_model != expected_timer_model:
        errors.append("automation timing timer_model does not match policy")
    if not isinstance(payload.get("case_id"), str) or not payload["case_id"].strip():
        errors.append("automation timing case_id is required")
    elif expected_case_id is not None and payload["case_id"] != expected_case_id:
        errors.append("automation timing case_id mismatch")

    extracted_plan = ledger_automation_plan(payload)
    errors.extend(validate_automation_plan(extracted_plan))
    if payload.get("plan_fingerprint") != extracted_plan["fingerprint"]:
        errors.append("automation timing plan fingerprint mismatch")
    if expected_plan is not None:
        expected_errors = validate_automation_plan(expected_plan)
        if expected_errors:
            errors.extend(f"expected {item}" for item in expected_errors)
        elif extracted_plan["fingerprint"] != expected_plan["fingerprint"]:
            errors.append("automation timing plan differs from planning handoff")

    planning = payload.get("planning")
    if expected_planning_case_id is not None:
        if not isinstance(planning, dict):
            errors.append("automation timing planning linkage is required")
        else:
            if planning.get("case_id") != expected_planning_case_id:
                errors.append("automation timing planning case mismatch")
            if planning.get("revision") != expected_planning_revision:
                errors.append("automation timing planning revision mismatch")
            if planning.get("automation_plan_fingerprint") != payload.get("plan_fingerprint"):
                errors.append("automation timing planning fingerprint mismatch")

    try:
        parse_timestamp(payload.get("created_at"), field="created_at")
        parse_timestamp(payload.get("updated_at"), field="updated_at")
    except AutomationTimingError as exc:
        errors.append(str(exc))

    case_state = payload.get("case_state")
    if case_state is not None:
        if not isinstance(case_state, dict):
            errors.append("automation timing case_state must be an object")
        else:
            status = case_state.get("status")
            if status not in CASE_STATES:
                errors.append("automation timing case_state status is invalid")
            try:
                parse_timestamp(case_state.get("changed_at"), field="case_state.changed_at")
            except AutomationTimingError as exc:
                errors.append(str(exc))
            reason = case_state.get("reason")
            evidence_ref = case_state.get("evidence_ref")
            resume_status = case_state.get("resume_status")
            if status == "deferred":
                if not isinstance(reason, str) or not reason.strip():
                    errors.append("deferred case_state requires reason")
                if not isinstance(evidence_ref, str) or not evidence_ref.strip():
                    errors.append("deferred case_state requires evidence_ref")
                if resume_status not in {"active", "ready_for_handoff"}:
                    errors.append(
                        "deferred case_state resume_status must be active or ready_for_handoff"
                    )
            elif reason is not None and (
                not isinstance(reason, str) or not reason.strip()
            ):
                errors.append("case_state reason must be non-empty text or null")
            if status != "deferred" and resume_status is not None:
                errors.append("non-deferred case_state cannot have resume_status")
            if evidence_ref is not None and (
                not isinstance(evidence_ref, str) or not evidence_ref.strip()
            ):
                errors.append("case_state evidence_ref must be non-empty text or null")
            errors.extend(
                validate_projection_readbacks(
                    case_state.get("projection_readbacks", []), prefix="case_state"
                )
            )

    milestones = payload.get("milestones", [])
    if timer_model == "dual":
        if not isinstance(milestones, list):
            errors.append("dual timer milestones must be an array")
            milestones = []
        publication_revisions: list[int] = []
        ready_revisions: list[int] = []
        handoff_count = 0
        previous_at: datetime | None = None
        for index, milestone in enumerate(milestones, start=1):
            label = f"milestone {index}"
            if not isinstance(milestone, dict):
                errors.append(f"{label} must be an object")
                continue
            kind = milestone.get("kind")
            if kind not in {"publication", "ready_for_handoff", "development_handoff"}:
                errors.append(f"{label} has invalid kind")
            try:
                milestone_at = parse_timestamp(milestone.get("at"), field=f"{label}.at")
                if previous_at is not None and milestone_at < previous_at:
                    errors.append("milestones must be append-only chronological")
                previous_at = milestone_at
            except AutomationTimingError as exc:
                errors.append(str(exc))
            if not isinstance(milestone.get("evidence_ref"), str) or not milestone[
                "evidence_ref"
            ].strip():
                errors.append(f"{label} requires evidence_ref")
            if kind == "publication":
                revision = milestone.get("publication_revision")
                if not isinstance(revision, int) or isinstance(revision, bool) or revision <= 0:
                    errors.append(f"{label} has invalid publication_revision")
                else:
                    publication_revisions.append(revision)
                if milestone.get("ready_revision") is not None:
                    errors.append(f"{label} publication cannot have ready_revision")
            elif kind == "ready_for_handoff":
                revision = milestone.get("ready_revision")
                if not isinstance(revision, int) or isinstance(revision, bool) or revision <= 0:
                    errors.append(f"{label} has invalid ready_revision")
                else:
                    ready_revisions.append(revision)
                if milestone.get("publication_revision") is not None:
                    errors.append(f"{label} ready milestone cannot have publication_revision")
            elif kind == "development_handoff":
                handoff_count += 1
                if milestone.get("publication_revision") is not None:
                    errors.append(f"{label} handoff cannot have publication_revision")
                if milestone.get("ready_revision") is not None:
                    errors.append(f"{label} handoff cannot have ready_revision")
            read_back = milestone.get("external_read_back")
            if read_back is not None:
                if not isinstance(read_back, dict):
                    errors.append(f"{label} external_read_back must be an object or null")
                else:
                    for field in ("system", "item_id", "read_back_at"):
                        if not isinstance(read_back.get(field), str) or not read_back[field].strip():
                            errors.append(f"{label} external_read_back missing {field}")
                    try:
                        parse_timestamp(
                            read_back.get("read_back_at"),
                            field=f"{label}.external_read_back.read_back_at",
                        )
                    except AutomationTimingError as exc:
                        errors.append(str(exc))
        if publication_revisions != list(range(1, len(publication_revisions) + 1)):
            errors.append("publication milestones must use contiguous revisions from 1")
        if ready_revisions != list(range(1, len(ready_revisions) + 1)):
            errors.append("ready milestones must use contiguous revisions from 1")
        if handoff_count > 1:
            errors.append("dual timer may have only one development_handoff")
        if case_state is not None:
            handoff_milestones = [
                item for item in milestones if item.get("kind") == "development_handoff"
            ]
            ready_milestones = [
                item for item in milestones if item.get("kind") == "ready_for_handoff"
            ]
            status = case_state.get("status") if isinstance(case_state, dict) else None
            if handoff_milestones and not ready_milestones:
                errors.append("development_handoff requires ready_for_handoff")
            if status == "handed_off" and len(handoff_milestones) != 1:
                errors.append("handed_off case_state requires one development_handoff")
            if status == "ready_for_handoff" and (
                not ready_milestones or handoff_milestones
            ):
                errors.append(
                    "ready_for_handoff case_state requires ready milestone without handoff"
                )
            if status in {"active", "deferred"} and handoff_milestones:
                errors.append(f"{status} case_state cannot have development_handoff")
    elif milestones:
        errors.append("legacy/disabled timer cannot have measured milestones")

    stages = payload.get("stages")
    if not isinstance(stages, list):
        errors.append("automation timing stages must be an array")
        return errors
    by_id = {
        stage.get("id"): stage
        for stage in stages
        if isinstance(stage, dict) and isinstance(stage.get("id"), str)
    }
    for stage in stages:
        if not isinstance(stage, dict):
            continue
        stage_id = stage.get("id", "<unknown>")
        status = stage.get("status")
        if status not in STAGE_STATUSES:
            errors.append(f"{stage_id}: invalid automation timing status {status!r}")
            continue
        started_at = stage.get("started_at")
        finished_at = stage.get("finished_at")
        actual_seconds = stage.get("actual_seconds")
        terminal_reason = stage.get("terminal_reason")
        checklist = stage.get("checklist")
        if not isinstance(checklist, list) or not checklist:
            errors.append(f"{stage_id}: runtime checklist must be non-empty")
            checklist = []
        for item in checklist:
            if not isinstance(item, dict):
                errors.append(f"{stage_id}: runtime checklist items must be objects")
                continue
            item_id = item.get("id", "<unknown>")
            item_status = item.get("status")
            completion_owner = item.get("completion_owner", "agent")
            if completion_owner not in {"agent", "user"}:
                errors.append(f"{item_id}: invalid completion_owner {completion_owner!r}")
            if item_status not in CHECKLIST_STATUSES:
                errors.append(f"{item_id}: invalid checklist status {item_status!r}")
                continue
            item_started_at = item.get("started_at")
            parallel_reason = item.get("parallel_reason")
            completed_at = item.get("completed_at")
            evidence_refs = item.get("evidence_refs")
            external_read_back = item.get("external_read_back")
            completion_confirmation = item.get("completion_confirmation")
            if not isinstance(evidence_refs, list) or any(
                not isinstance(ref, str) or not ref.strip() for ref in evidence_refs
            ):
                errors.append(f"{item_id}: evidence_refs must be a string array")
                evidence_refs = []
            if item_status == "pending":
                if (
                    item_started_at is not None
                    or parallel_reason is not None
                    or completed_at is not None
                    or evidence_refs
                    or external_read_back is not None
                    or completion_confirmation is not None
                ):
                    errors.append(f"{item_id}: pending checklist item cannot have runtime facts")
            elif item_status == "in_progress":
                try:
                    parse_timestamp(item_started_at, field=f"{item_id}.started_at")
                except AutomationTimingError as exc:
                    errors.append(str(exc))
                if parallel_reason is not None and (
                    not isinstance(parallel_reason, str) or not parallel_reason.strip()
                ):
                    errors.append(f"{item_id}: parallel_reason must be non-empty text or null")
                if (
                    completed_at is not None
                    or evidence_refs
                    or external_read_back is not None
                    or completion_confirmation is not None
                ):
                    errors.append(
                        f"{item_id}: in-progress checklist item cannot have completion facts"
                    )
            else:
                if item_started_at is not None:
                    try:
                        parse_timestamp(item_started_at, field=f"{item_id}.started_at")
                    except AutomationTimingError as exc:
                        errors.append(str(exc))
                if parallel_reason is not None and (
                    not isinstance(parallel_reason, str) or not parallel_reason.strip()
                ):
                    errors.append(f"{item_id}: parallel_reason must be non-empty text or null")
                try:
                    parse_timestamp(completed_at, field=f"{item_id}.completed_at")
                except AutomationTimingError as exc:
                    errors.append(str(exc))
                if not evidence_refs and external_read_back is None:
                    errors.append(f"{item_id}: completed checklist item requires evidence")
                if completion_owner == "user" and completion_confirmation != "user":
                    errors.append(
                        f"{item_id}: user-owned checklist item requires user confirmation"
                    )
                if completion_owner == "agent" and completion_confirmation not in {
                    None,
                    "agent",
                }:
                    errors.append(f"{item_id}: agent-owned checklist has invalid confirmation")
                target_id = stage.get("external_target_id")
                if payload.get("progress_target_id") is None and target_id is not None:
                    if not isinstance(external_read_back, dict):
                        errors.append(f"{item_id}: external checklist requires read-back evidence")
                    else:
                        if external_read_back.get("target_id") != target_id:
                            errors.append(f"{item_id}: external read-back target mismatch")
                        if external_read_back.get("checked") is not True:
                            errors.append(f"{item_id}: external read-back must confirm checked=true")
                        for field in ("system", "item_id", "read_back_at"):
                            if not isinstance(external_read_back.get(field), str) or not external_read_back[field].strip():
                                errors.append(f"{item_id}: external read-back missing {field}")
                        try:
                            parse_timestamp(
                                external_read_back.get("read_back_at"),
                                field=f"{item_id}.external_read_back.read_back_at",
                            )
                        except AutomationTimingError as exc:
                            errors.append(str(exc))

        if timer_model == "disabled":
            if any(value is not None for value in (started_at, finished_at, actual_seconds)):
                errors.append(f"{stage_id}: disabled timer cannot have timing facts")
        elif timer_model == "dual":
            active_started_at = stage.get("active_started_at")
            active_seconds = stage.get("active_seconds")
            elapsed_seconds = stage.get("elapsed_seconds")
            pause_started_at = stage.get("pause_started_at")
            pause_reason = stage.get("pause_reason")
            pauses = stage.get("pauses")
            if not isinstance(active_seconds, int) or isinstance(active_seconds, bool) or active_seconds < 0:
                errors.append(f"{stage_id}: active_seconds must be a non-negative integer")
            if not isinstance(pauses, list):
                errors.append(f"{stage_id}: pauses must be an array")
                pauses = []
            for index, pause in enumerate(pauses, start=1):
                if not isinstance(pause, dict):
                    errors.append(f"{stage_id}: pause {index} must be an object")
                    continue
                if pause.get("reason") not in PAUSE_REASONS:
                    errors.append(f"{stage_id}: pause {index} has invalid reason")
                try:
                    pause_start = parse_timestamp(
                        pause.get("started_at"), field=f"{stage_id}.pauses[{index}].started_at"
                    )
                    pause_finish = parse_timestamp(
                        pause.get("finished_at"), field=f"{stage_id}.pauses[{index}].finished_at"
                    )
                    pause_seconds = int((pause_finish - pause_start).total_seconds())
                    if pause_seconds < 0 or pause.get("seconds") != pause_seconds:
                        errors.append(f"{stage_id}: pause {index} duration mismatch")
                except AutomationTimingError as exc:
                    errors.append(str(exc))
            if status == "pending":
                if any(
                    value is not None
                    for value in (
                        started_at,
                        finished_at,
                        actual_seconds,
                        active_started_at,
                        elapsed_seconds,
                        pause_started_at,
                        pause_reason,
                    )
                ) or active_seconds != 0 or pauses:
                    errors.append(f"{stage_id}: pending dual timer has runtime facts")
            elif status == "running":
                if started_at is None or finished_at is not None or actual_seconds is not None or elapsed_seconds is not None:
                    errors.append(f"{stage_id}: running dual timer has invalid terminal facts")
                try:
                    parse_timestamp(started_at, field=f"{stage_id}.started_at")
                except AutomationTimingError as exc:
                    errors.append(str(exc))
                active = active_started_at is not None
                paused = pause_started_at is not None
                if active == paused:
                    errors.append(f"{stage_id}: running dual timer must be active or paused")
                if active:
                    try:
                        parse_timestamp(active_started_at, field=f"{stage_id}.active_started_at")
                    except AutomationTimingError as exc:
                        errors.append(str(exc))
                    if pause_reason is not None:
                        errors.append(f"{stage_id}: active timer cannot have pause_reason")
                if paused:
                    try:
                        parse_timestamp(pause_started_at, field=f"{stage_id}.pause_started_at")
                    except AutomationTimingError as exc:
                        errors.append(str(exc))
                    if pause_reason not in PAUSE_REASONS:
                        errors.append(f"{stage_id}: paused timer requires a valid reason")
            else:
                if (
                    started_at is None
                    or finished_at is None
                    or active_started_at is not None
                    or pause_started_at is not None
                    or pause_reason is not None
                ):
                    errors.append(f"{stage_id}: terminal dual timer has invalid state")
                else:
                    try:
                        started = parse_timestamp(started_at, field=f"{stage_id}.started_at")
                        finished = parse_timestamp(finished_at, field=f"{stage_id}.finished_at")
                        expected_elapsed = int((finished - started).total_seconds())
                        if expected_elapsed < 0 or elapsed_seconds != expected_elapsed:
                            errors.append(f"{stage_id}: elapsed_seconds does not match timestamps")
                        if actual_seconds != active_seconds:
                            errors.append(f"{stage_id}: actual_seconds must equal active_seconds")
                    except AutomationTimingError as exc:
                        errors.append(str(exc))
        elif status == "pending":
            if any(value is not None for value in (started_at, finished_at, actual_seconds)):
                errors.append(f"{stage_id}: pending stage cannot have timing facts")
        elif status == "running":
            if started_at is None or finished_at is not None or actual_seconds is not None:
                errors.append(f"{stage_id}: running stage requires only started_at")
            else:
                try:
                    parse_timestamp(started_at, field=f"{stage_id}.started_at")
                except AutomationTimingError as exc:
                    errors.append(str(exc))
        else:
            if started_at is None or finished_at is None:
                errors.append(f"{stage_id}: terminal stage requires start and finish timestamps")
            else:
                try:
                    started = parse_timestamp(started_at, field=f"{stage_id}.started_at")
                    finished = parse_timestamp(finished_at, field=f"{stage_id}.finished_at")
                    expected_seconds = int((finished - started).total_seconds())
                    if expected_seconds < 0:
                        errors.append(f"{stage_id}: finished_at precedes started_at")
                    if actual_seconds != expected_seconds:
                        errors.append(f"{stage_id}: actual_seconds does not match timestamps")
                except AutomationTimingError as exc:
                    errors.append(str(exc))
            if status != "completed" and (
                not isinstance(terminal_reason, str) or not terminal_reason.strip()
            ):
                errors.append(f"{stage_id}: {status} stage requires terminal_reason")
            if status == "completed":
                incomplete_items = [
                    str(item.get("id"))
                    for item in checklist
                    if isinstance(item, dict)
                    and (
                        (
                            item.get("required") is True
                            and item.get("status") != "completed"
                        )
                        or item.get("status") == "in_progress"
                    )
                ]
                if incomplete_items:
                    errors.append(
                        f"{stage_id}: completed stage has unfinished checklist items: "
                        + ", ".join(incomplete_items)
                    )

        if status in {"running", *TERMINAL_STATUSES}:
            for dependency in stage.get("depends_on", []):
                dependency_stage = by_id.get(dependency)
                if dependency_stage is not None and dependency_stage.get("status") != "completed":
                    errors.append(
                        f"{stage_id}: dependency {dependency} was not completed before execution"
                    )

    if final and payload.get("policy") in {"required", "measured"}:
        unfinished = [
            str(stage.get("id"))
            for stage in stages
            if isinstance(stage, dict) and stage.get("status") not in TERMINAL_STATUSES
        ]
        if unfinished:
            errors.append(f"automation timing has unfinished stages: {', '.join(unfinished)}")
    return errors


def load_ledger(case_root: Path) -> tuple[Path, dict[str, Any]]:
    """Load a ledger from a case root or direct JSON path."""
    candidate = case_root.expanduser().resolve()
    path = candidate if candidate.is_file() else candidate / FILENAME
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AutomationTimingError(f"Cannot read {path}: {exc}") from exc
    return path, payload


def save_ledger(path: Path, ledger: dict[str, Any]) -> None:
    """Persist one validated mutable ledger."""
    ledger["updated_at"] = now_utc()
    errors = validate_ledger(ledger)
    if errors:
        raise AutomationTimingError("; ".join(errors))
    atomic_json(path, ledger)


def find_stage(ledger: dict[str, Any], stage_id: str) -> dict[str, Any]:
    """Resolve one stage by stable id."""
    for stage in ledger.get("stages", []):
        if isinstance(stage, dict) and stage.get("id") == stage_id:
            return stage
    raise AutomationTimingError(f"Unknown automation stage: {stage_id}")


def find_checklist_item(stage: dict[str, Any], item_id: str) -> dict[str, Any]:
    """Resolve one checklist item inside a planned stage."""
    for item in stage.get("checklist", []):
        if isinstance(item, dict) and item.get("id") == item_id:
            return item
    raise AutomationTimingError(f"Unknown checklist item {item_id} in {stage.get('id')}")


def progress_binding(
    ledger: dict[str, Any],
    item_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Resolve a stable external checklist binding for one local item."""
    projection = ledger.get("progress_projection")
    if not isinstance(projection, dict):
        raise AutomationTimingError("Checklist progress projection is not bound")
    for binding in projection.get("bindings", []):
        if isinstance(binding, dict) and binding.get("local_item_id") == item_id:
            return projection, binding
    raise AutomationTimingError(f"Checklist item {item_id} has no stable progress binding")


def bind_progress_projection(
    ledger: dict[str, Any],
    receipt: Any,
    *,
    source: str = "plan",
    migration_evidence: str | None = None,
    allow_completed: bool = False,
    at: str | None = None,
) -> bool:
    """Bind every stable local checklist id to exactly one external item."""
    require_active_case(ledger, action="bind checklist progress")
    errors = validate_ledger(ledger)
    if errors:
        raise AutomationTimingError("; ".join(errors))
    if source not in {"plan", "migration"}:
        raise AutomationTimingError("Progress binding source must be plan or migration")
    if source == "migration" and (
        not isinstance(migration_evidence, str) or not migration_evidence.strip()
    ):
        raise AutomationTimingError("Progress migration requires evidence")
    normalized = normalized_progress_receipt(receipt, require_readbacks=False)
    checklist = runtime_checklist_index(ledger)
    binding_ids = {item["local_item_id"] for item in normalized["bindings"]}
    if binding_ids != set(checklist):
        missing = sorted(set(checklist) - binding_ids)
        extra = sorted(binding_ids - set(checklist))
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if extra:
            details.append("unknown " + ", ".join(extra))
        raise AutomationTimingError(
            "Progress bindings must cover every checklist item: " + "; ".join(details)
        )
    completed = sorted(
        item_id
        for item_id, item in checklist.items()
        if item.get("status") == "completed"
    )
    if completed and not allow_completed:
        raise AutomationTimingError(
            "Completed checklist items require migrate-progress: " + ", ".join(completed)
        )
    existing_target = ledger.get("progress_target_id")
    if source == "plan" and existing_target is None:
        raise AutomationTimingError(
            "Progress target is absent from the planning contract; use migrate-progress"
        )
    if existing_target is not None and existing_target != normalized["progress_target_id"]:
        raise AutomationTimingError("Progress target differs from the immutable plan binding")

    existing = ledger.get("progress_projection")
    desired_bindings = [
        {**binding, "last_read_back": None}
        for binding in normalized["bindings"]
    ]
    if isinstance(existing, dict) and existing.get("bindings"):
        current_signature = {
            "progress_target_id": existing.get("progress_target_id"),
            "system": existing.get("system"),
            "target_id": existing.get("target_id"),
            "bindings": [
                {
                    "local_item_id": item.get("local_item_id"),
                    "external_item_id": item.get("external_item_id"),
                    "title": item.get("title"),
                }
                for item in existing.get("bindings", [])
                if isinstance(item, dict)
            ],
        }
        desired_signature = {
            "progress_target_id": normalized["progress_target_id"],
            "system": normalized["system"],
            "target_id": normalized["target_id"],
            "bindings": normalized["bindings"],
        }
        if current_signature == desired_signature:
            return False
        raise AutomationTimingError(
            "Progress projection is already bound differently; use a new planning revision"
        )

    timestamp = normalized_timestamp(at)
    ledger["progress_target_id"] = normalized["progress_target_id"]
    ledger["progress_projection"] = {
        "source": source,
        "progress_target_id": normalized["progress_target_id"],
        "system": normalized["system"],
        "target_id": normalized["target_id"],
        "bindings": desired_bindings,
        "bound_at": timestamp,
        "migration_evidence": (
            migration_evidence.strip() if source == "migration" else None
        ),
    }
    ledger["events"].append(
        {
            "at": timestamp,
            "kind": (
                "progress_projection_migrated"
                if source == "migration"
                else "progress_projection_bound"
            ),
            "progress_target_id": normalized["progress_target_id"],
            "system": normalized["system"],
            "target_id": normalized["target_id"],
            "binding_count": len(desired_bindings),
            "migration_evidence": (
                migration_evidence.strip() if source == "migration" else None
            ),
        }
    )
    return True


def reconcile_progress_projection(
    ledger: dict[str, Any],
    receipt: Any,
    *,
    at: str | None = None,
    skip_initial_validation: bool = False,
) -> bool:
    """Apply a complete external checklist read-back without changing local status."""
    require_active_case(ledger, action="reconcile checklist progress")
    if not skip_initial_validation:
        errors = validate_ledger(ledger)
        if errors:
            raise AutomationTimingError("; ".join(errors))
    normalized = normalized_progress_receipt(receipt, require_readbacks=True)
    projection = ledger.get("progress_projection")
    if not isinstance(projection, dict) or not projection.get("bindings"):
        raise AutomationTimingError("Bind checklist progress before reconciliation")
    for field in ("progress_target_id", "system", "target_id"):
        actual = (
            ledger.get("progress_target_id")
            if field == "progress_target_id"
            else projection.get(field)
        )
        if normalized[field] != actual:
            raise AutomationTimingError(f"Progress reconciliation {field} mismatch")
    binding_by_local = {
        item["local_item_id"]: item
        for item in projection["bindings"]
        if isinstance(item, dict) and isinstance(item.get("local_item_id"), str)
    }
    receipt_bindings = {
        item["local_item_id"]: item for item in normalized["bindings"]
    }
    for local_item_id, binding in binding_by_local.items():
        supplied = receipt_bindings.get(local_item_id)
        if supplied is None or any(
            supplied.get(field) != binding.get(field)
            for field in ("external_item_id", "title")
        ):
            raise AutomationTimingError(
                f"Progress reconciliation binding mismatch for {local_item_id}"
            )
    checklist = runtime_checklist_index(ledger)
    readbacks = {item["local_item_id"]: item for item in normalized["readbacks"]}
    updates: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []
    for local_item_id, binding in binding_by_local.items():
        item = checklist[local_item_id]
        readback = readbacks[local_item_id]
        if readback["external_item_id"] != binding["external_item_id"]:
            raise AutomationTimingError(
                f"Progress read-back item mismatch for {local_item_id}"
            )
        if item.get("status") == "completed" and readback["checked"] is not True:
            raise AutomationTimingError(
                f"Completed checklist item {local_item_id} requires checked=true"
            )
        if item.get("status") != "completed" and readback["checked"] is not False:
            raise AutomationTimingError(
                f"External checklist is ahead of local state for {local_item_id}"
            )
        external_read_back = {
            "progress_target_id": ledger["progress_target_id"],
            "system": projection["system"],
            "target_id": projection["target_id"],
            "item_id": binding["external_item_id"],
            "title": readback["title"],
            "checked": readback["checked"],
            "read_back_at": readback["read_back_at"],
        }
        existing = item.get("external_read_back")
        if item.get("status") == "completed" and existing is not None:
            immutable_fields = (
                "progress_target_id",
                "system",
                "target_id",
                "item_id",
                "title",
                "checked",
            )
            if any(
                existing.get(field) != external_read_back.get(field)
                for field in immutable_fields
            ):
                raise AutomationTimingError(
                    f"Completed checklist item {local_item_id} has different read-back evidence"
                )
        previous_read_back = binding.get("last_read_back")
        if isinstance(previous_read_back, dict) and (
            parse_timestamp(
                external_read_back["read_back_at"],
                field=f"{local_item_id}.read_back_at",
            )
            < parse_timestamp(
                previous_read_back.get("read_back_at"),
                field=f"{local_item_id}.last_read_back.read_back_at",
            )
        ):
            raise AutomationTimingError(
                f"Progress read-back for {local_item_id} is older than stored evidence"
            )
        updates.append((item, binding, external_read_back))

    changed = False
    for item, binding, external_read_back in updates:
        if binding.get("last_read_back") != external_read_back:
            binding["last_read_back"] = external_read_back
            changed = True
        if item.get("status") == "completed" and item.get("external_read_back") is None:
            item["external_read_back"] = external_read_back
            changed = True
    if changed:
        timestamp = normalized_timestamp(at)
        ledger["events"].append(
            {
                "at": timestamp,
                "kind": "progress_projection_reconciled",
                "progress_target_id": ledger["progress_target_id"],
                "system": projection["system"],
                "target_id": projection["target_id"],
                "read_back_count": len(updates),
            }
        )
    return changed


def migrate_progress_projection(
    ledger: dict[str, Any],
    receipt: Any,
    *,
    evidence_ref: str,
    at: str | None = None,
) -> bool:
    """Atomically bind and reconcile a legacy ledger with completed local items."""
    errors = validate_ledger(ledger)
    if errors:
        raise AutomationTimingError("; ".join(errors))
    working = copy.deepcopy(ledger)
    bound = bind_progress_projection(
        working,
        receipt,
        source="migration",
        migration_evidence=evidence_ref,
        allow_completed=True,
        at=at,
    )
    reconciled = reconcile_progress_projection(
        working,
        receipt,
        at=at,
        skip_initial_validation=True,
    )
    errors = validate_ledger(working)
    if errors:
        raise AutomationTimingError("; ".join(errors))
    if not bound and not reconciled:
        return False
    ledger.clear()
    ledger.update(working)
    return True


def begin_checklist_item(
    ledger: dict[str, Any],
    stage_id: str,
    item_id: str,
    *,
    parallel_reason: str | None = None,
    at: str | None = None,
) -> bool:
    """Claim any pending item before work, with explicit concurrent-work evidence."""
    require_active_case(ledger, action="begin checklist work")
    errors = validate_ledger(ledger)
    if errors:
        raise AutomationTimingError("; ".join(errors))
    stage = find_stage(ledger, stage_id)
    if stage["status"] != "running":
        raise AutomationTimingError(
            f"Stage {stage_id} is {stage['status']}, checklist work requires running"
        )
    item = find_checklist_item(stage, item_id)
    if item.get("completion_owner", "agent") == "user":
        raise AutomationTimingError(
            f"Checklist item {item_id} is user-owned; wait for explicit user confirmation"
        )
    if item["status"] == "completed":
        raise AutomationTimingError(f"Checklist item {item_id} is already completed")
    if item["status"] == "in_progress":
        return False

    active = [
        str(candidate.get("id"))
        for candidate in stage.get("checklist", [])
        if isinstance(candidate, dict) and candidate.get("status") == "in_progress"
    ]
    if parallel_reason is not None and (
        not isinstance(parallel_reason, str) or not parallel_reason.strip()
    ):
        raise AutomationTimingError("parallel_reason must be non-empty text or null")
    normalized_parallel_reason = parallel_reason.strip() if parallel_reason else None
    if active and normalized_parallel_reason is None:
        raise AutomationTimingError(
            f"Stage {stage_id} already has in-progress checklist items: {', '.join(active)}; "
            "complete their synchronization or provide --parallel-reason for genuinely "
            "concurrent independent work"
        )
    if not active and normalized_parallel_reason is not None:
        raise AutomationTimingError(
            "parallel_reason requires another checklist item already in progress"
        )

    timestamp = normalized_timestamp(at)
    item.update(
        status="in_progress",
        started_at=timestamp,
        parallel_reason=normalized_parallel_reason,
    )
    ledger["events"].append(
        {
            "at": timestamp,
            "kind": "checklist_started",
            "stage_id": stage_id,
            "item_id": item_id,
            "parallel_reason": normalized_parallel_reason,
        }
    )
    return True


def complete_checklist_item(
    ledger: dict[str, Any],
    stage_id: str,
    item_id: str,
    *,
    evidence_refs: list[str],
    external_system: str | None = None,
    external_item_id: str | None = None,
    external_title: str | None = None,
    read_back_at: str | None = None,
    user_confirmed: bool = False,
    at: str | None = None,
) -> bool:
    """Mark one finished item immediately after evidence and external read-back."""
    require_active_case(ledger, action="complete checklist work")
    errors = validate_ledger(ledger)
    if errors:
        raise AutomationTimingError("; ".join(errors))
    stage = find_stage(ledger, stage_id)
    if stage["status"] != "running":
        raise AutomationTimingError(
            f"Stage {stage_id} is {stage['status']}, checklist updates require running"
        )
    item = find_checklist_item(stage, item_id)
    completion_owner = item.get("completion_owner", "agent")
    if completion_owner == "user" and not user_confirmed:
        raise AutomationTimingError(
            f"Checklist item {item_id} is user-owned; --user-confirmed is required"
        )
    if completion_owner == "agent" and user_confirmed:
        raise AutomationTimingError(
            f"Checklist item {item_id} is agent-owned; user confirmation is not applicable"
        )
    normalized_evidence = list(dict.fromkeys(ref.strip() for ref in evidence_refs if ref.strip()))
    progress_projection: dict[str, Any] | None = None
    progress_item_binding: dict[str, Any] | None = None
    if ledger.get("progress_target_id") is not None:
        progress_projection, progress_item_binding = progress_binding(ledger, item_id)
        external_values = (
            external_system,
            external_item_id,
            external_title,
            read_back_at,
        )
        if not all(isinstance(value, str) and value.strip() for value in external_values):
            raise AutomationTimingError(
                "Projected checklist read-back requires system, item id, title, and timestamp"
            )
        if external_system.strip() != progress_projection.get("system"):
            raise AutomationTimingError(f"Checklist item {item_id} external system mismatch")
        if external_item_id.strip() != progress_item_binding.get("external_item_id"):
            raise AutomationTimingError(f"Checklist item {item_id} external item mismatch")
        if not external_title.strip().startswith(item_id):
            raise AutomationTimingError(
                f"Checklist item {item_id} external title must start with its stable id"
            )
        external_read_back = {
            "progress_target_id": ledger["progress_target_id"],
            "target_id": progress_projection["target_id"],
            "system": external_system.strip(),
            "item_id": external_item_id.strip(),
            "title": external_title.strip(),
            "checked": True,
            "read_back_at": parse_timestamp(
                read_back_at,
                field=f"{item_id}.external_read_back.read_back_at",
            ).isoformat(),
        }
    else:
        external_values = (external_system, external_item_id, read_back_at)
        if any(value is not None for value in external_values) and not all(
            isinstance(value, str) and value.strip() for value in external_values
        ):
            raise AutomationTimingError(
                "External checklist read-back requires system, item id, and timestamp together"
            )
        target_id = stage.get("external_target_id")
        if target_id is not None and not all(
            isinstance(value, str) and value.strip() for value in external_values
        ):
            raise AutomationTimingError(
                f"Checklist item {item_id} is projected to {target_id}; read-back is required"
            )
        external_read_back = (
            {
                "target_id": target_id,
                "system": external_system.strip(),
                "item_id": external_item_id.strip(),
                "checked": True,
                "read_back_at": parse_timestamp(
                    read_back_at,
                    field=f"{item_id}.external_read_back.read_back_at",
                ).isoformat(),
            }
            if external_system is not None
            else None
        )
    if not normalized_evidence and external_read_back is None:
        raise AutomationTimingError(f"Checklist item {item_id} requires completion evidence")
    timestamp = (
        item["completed_at"]
        if item["status"] == "completed"
        else normalized_timestamp(at)
    )
    if item["status"] == "pending" and completion_owner == "user":
        item.update(status="in_progress", started_at=timestamp, parallel_reason=None)
        ledger["events"].append(
            {
                "at": timestamp,
                "kind": "checklist_started",
                "stage_id": stage_id,
                "item_id": item_id,
                "parallel_reason": None,
                "source": "user_confirmation",
            }
        )
    desired = {
        "completed_at": timestamp,
        "evidence_refs": normalized_evidence,
        "external_read_back": external_read_back,
        "completion_confirmation": "user" if completion_owner == "user" else None,
    }
    if item["status"] == "completed":
        current = {key: item.get(key) for key in desired}
        if current == desired:
            return False
        raise AutomationTimingError(
            f"Checklist item {item_id} is already completed with different evidence"
        )
    if item["status"] != "in_progress":
        raise AutomationTimingError(
            f"Checklist item {item_id} is {item['status']}; begin it before work and "
            "synchronize it immediately after done_when is satisfied"
        )
    item.update(status="completed", **desired)
    if progress_item_binding is not None:
        progress_item_binding["last_read_back"] = external_read_back
    ledger["events"].append(
        {
            "at": timestamp,
            "kind": "checklist_completed",
            "stage_id": stage_id,
            "item_id": item_id,
            "evidence_refs": normalized_evidence,
            "external_read_back": external_read_back,
        }
    )
    return True


def normalized_projection_readbacks(payload: Any) -> list[dict[str, Any]]:
    errors = validate_projection_readbacks(payload, prefix="state transition")
    if errors:
        raise AutomationTimingError("; ".join(errors))
    result: list[dict[str, Any]] = []
    for item in payload:
        normalized: dict[str, Any] = {
            "system": item["system"].strip(),
            "item_id": item["item_id"].strip(),
            "state": item["state"].strip(),
            "read_back_at": parse_timestamp(
                item["read_back_at"], field="projection_readback.read_back_at"
            ).isoformat(),
        }
        if isinstance(item.get("previous_state"), dict):
            normalized["previous_state"] = item["previous_state"]
        result.append(normalized)
    return result


def defer_case(
    ledger: dict[str, Any],
    *,
    reason: str,
    evidence_ref: str,
    projection_readbacks: Any | None = None,
    at: str | None = None,
) -> None:
    """Suspend case WIP without teaching the model that backlog time is work."""
    state = current_case_state(ledger)
    if state == "deferred":
        raise AutomationTimingError("Timing case is already deferred")
    if state == "handed_off":
        raise AutomationTimingError("Handed-off timing case cannot be deferred")
    if not isinstance(reason, str) or not reason.strip():
        raise AutomationTimingError("Deferral requires a reason")
    if not isinstance(evidence_ref, str) or not evidence_ref.strip():
        raise AutomationTimingError("Deferral requires evidence_ref")
    timestamp = normalized_timestamp(at)
    if ledger.get("timer_model") == "dual":
        for stage in ledger.get("stages", []):
            if (
                isinstance(stage, dict)
                and stage.get("status") == "running"
                and stage.get("active_started_at") is not None
            ):
                pause_stage(ledger, stage["id"], reason="deferred", at=timestamp)
    readbacks = normalized_projection_readbacks(projection_readbacks or [])
    ledger["case_state"] = {
        "status": "deferred",
        "changed_at": timestamp,
        "reason": reason.strip(),
        "evidence_ref": evidence_ref.strip(),
        "resume_status": state,
        "projection_readbacks": readbacks,
    }
    ledger["events"].append(
        {
            "at": timestamp,
            "kind": "case_deferred",
            "reason": reason.strip(),
            "evidence_ref": evidence_ref.strip(),
            "resume_status": state,
            "projection_readbacks": readbacks,
        }
    )


def resume_case(
    ledger: dict[str, Any],
    *,
    evidence_ref: str,
    projection_readbacks: Any | None = None,
    at: str | None = None,
) -> list[str]:
    """Resume a deferred case and any stage paused specifically by deferral."""
    state = ledger.get("case_state")
    if not isinstance(state, dict) or state.get("status") != "deferred":
        raise AutomationTimingError("Timing case is not deferred")
    if not isinstance(evidence_ref, str) or not evidence_ref.strip():
        raise AutomationTimingError("Resuming a deferred case requires evidence_ref")
    timestamp = normalized_timestamp(at)
    resumed_stages: list[str] = []
    if ledger.get("timer_model") == "dual":
        for stage in ledger.get("stages", []):
            if (
                isinstance(stage, dict)
                and stage.get("status") == "running"
                and stage.get("pause_started_at") is not None
                and stage.get("pause_reason") == "deferred"
            ):
                resume_stage(ledger, stage["id"], at=timestamp)
                resumed_stages.append(stage["id"])
    readbacks = normalized_projection_readbacks(projection_readbacks or [])
    resumed_status = state.get("resume_status", "active")
    ledger["case_state"] = {
        "status": resumed_status,
        "changed_at": timestamp,
        "reason": None,
        "evidence_ref": evidence_ref.strip(),
        "resume_status": None,
        "projection_readbacks": readbacks,
    }
    ledger["events"].append(
        {
            "at": timestamp,
            "kind": "case_resumed",
            "status": resumed_status,
            "evidence_ref": evidence_ref.strip(),
            "projection_readbacks": readbacks,
        }
    )
    return resumed_stages


def start_stage(ledger: dict[str, Any], stage_id: str, *, at: str | None = None) -> None:
    """Start a pending stage after all dependencies completed."""
    require_active_case(ledger, action="start a stage")
    errors = validate_ledger(ledger)
    if errors:
        raise AutomationTimingError("; ".join(errors))
    stage = find_stage(ledger, stage_id)
    if stage["status"] != "pending":
        raise AutomationTimingError(f"Stage {stage_id} is {stage['status']}, expected pending")
    by_id = {item["id"]: item for item in ledger["stages"]}
    incomplete = [
        dependency
        for dependency in stage["depends_on"]
        if by_id[dependency]["status"] != "completed"
    ]
    if incomplete:
        raise AutomationTimingError(
            f"Stage {stage_id} has incomplete dependencies: {', '.join(incomplete)}"
        )
    timestamp = normalized_timestamp(at)
    stage["status"] = "running"
    if ledger.get("timer_model") != "disabled":
        stage["started_at"] = timestamp
    if ledger.get("timer_model") == "dual":
        stage["active_started_at"] = timestamp
    ledger["events"].append({"at": timestamp, "kind": "stage_started", "stage_id": stage_id})


def pause_stage(
    ledger: dict[str, Any],
    stage_id: str,
    *,
    reason: str,
    at: str | None = None,
) -> None:
    """Pause active work while leaving calendar elapsed time running."""
    if ledger.get("timer_model") != "dual":
        raise AutomationTimingError("Pause/resume requires a measured dual timer")
    if reason not in PAUSE_REASONS:
        raise AutomationTimingError(f"Invalid pause reason: {reason}")
    stage = find_stage(ledger, stage_id)
    if stage["status"] != "running" or stage.get("active_started_at") is None:
        raise AutomationTimingError(f"Stage {stage_id} is not actively running")
    timestamp = normalized_timestamp(at)
    active_started = parse_timestamp(
        stage["active_started_at"], field=f"{stage_id}.active_started_at"
    )
    paused = parse_timestamp(timestamp, field=f"{stage_id}.pause_started_at")
    segment = int((paused - active_started).total_seconds())
    if segment < 0:
        raise AutomationTimingError(f"Stage {stage_id} pause precedes active start")
    stage["active_seconds"] += segment
    stage["active_started_at"] = None
    stage["pause_started_at"] = paused.isoformat()
    stage["pause_reason"] = reason
    ledger["events"].append(
        {
            "at": paused.isoformat(),
            "kind": "stage_paused",
            "stage_id": stage_id,
            "reason": reason,
            "active_seconds": stage["active_seconds"],
        }
    )


def resume_stage(ledger: dict[str, Any], stage_id: str, *, at: str | None = None) -> None:
    """Resume a paused dual timer."""
    if ledger.get("timer_model") != "dual":
        raise AutomationTimingError("Pause/resume requires a measured dual timer")
    stage = find_stage(ledger, stage_id)
    if stage["status"] != "running" or stage.get("pause_started_at") is None:
        raise AutomationTimingError(f"Stage {stage_id} is not paused")
    timestamp = normalized_timestamp(at)
    pause_started = parse_timestamp(
        stage["pause_started_at"], field=f"{stage_id}.pause_started_at"
    )
    resumed = parse_timestamp(timestamp, field=f"{stage_id}.active_started_at")
    seconds = int((resumed - pause_started).total_seconds())
    if seconds < 0:
        raise AutomationTimingError(f"Stage {stage_id} resume precedes pause")
    stage["pauses"].append(
        {
            "started_at": pause_started.isoformat(),
            "finished_at": resumed.isoformat(),
            "seconds": seconds,
            "reason": stage["pause_reason"],
        }
    )
    stage["pause_started_at"] = None
    stage["pause_reason"] = None
    stage["active_started_at"] = resumed.isoformat()
    ledger["events"].append(
        {"at": resumed.isoformat(), "kind": "stage_resumed", "stage_id": stage_id}
    )


def reopen_stage(
    ledger: dict[str, Any],
    stage_id: str,
    *,
    evidence_ref: str,
    at: str | None = None,
) -> None:
    """Reopen a completed stage for edits after a recorded publication."""
    state = current_case_state(ledger)
    if state in {"deferred", "handed_off"}:
        raise AutomationTimingError(f"Cannot reopen a stage while case state is {state}")
    if ledger.get("timer_model") != "dual":
        raise AutomationTimingError("Post-publication reopen requires a dual timer")
    if not isinstance(evidence_ref, str) or not evidence_ref.strip():
        raise AutomationTimingError("Post-publication reopen requires evidence_ref")
    if any(
        item.get("kind") == "development_handoff"
        for item in ledger.get("milestones", [])
    ):
        raise AutomationTimingError("Handed-off timing case cannot be reopened")
    stage = find_stage(ledger, stage_id)
    if stage.get("status") != "completed":
        raise AutomationTimingError(f"Stage {stage_id} must be completed before reopen")
    finished = parse_timestamp(stage.get("finished_at"), field=f"{stage_id}.finished_at")
    publications = [
        item
        for item in ledger.get("milestones", [])
        if item.get("kind") == "publication"
    ]
    if not publications or parse_timestamp(
        publications[-1].get("at"), field="publication.at"
    ) < finished:
        raise AutomationTimingError("Post-publication reopen requires a later publication milestone")
    reopened = parse_timestamp(normalized_timestamp(at), field=f"{stage_id}.active_started_at")
    if reopened < finished:
        raise AutomationTimingError(f"Stage {stage_id} reopen precedes previous completion")
    stage["status"] = "running"
    stage["active_started_at"] = reopened.isoformat()
    stage["finished_at"] = None
    stage["elapsed_seconds"] = None
    stage["actual_seconds"] = None
    stage["terminal_reason"] = None
    ledger["events"].append(
        {
            "at": reopened.isoformat(),
            "kind": "stage_reopened_after_publication",
            "stage_id": stage_id,
            "evidence_ref": evidence_ref.strip(),
            "publication_revision": publications[-1]["publication_revision"],
        }
    )
    if state == "ready_for_handoff":
        ledger["case_state"] = {
            "status": "active",
            "changed_at": reopened.isoformat(),
            "reason": "post-ready correction",
            "evidence_ref": evidence_ref.strip(),
            "resume_status": None,
            "projection_readbacks": [],
        }
        ledger["events"].append(
            {
                "at": reopened.isoformat(),
                "kind": "ready_for_handoff_withdrawn",
                "evidence_ref": evidence_ref.strip(),
            }
        )


def stop_stage(
    ledger: dict[str, Any],
    stage_id: str,
    *,
    status: str,
    reason: str | None,
    at: str | None = None,
) -> None:
    """Finish a running stage with one terminal status."""
    require_active_case(ledger, action="stop a stage")
    if status not in TERMINAL_STATUSES:
        raise AutomationTimingError(f"Invalid terminal status: {status}")
    stage = find_stage(ledger, stage_id)
    if stage["status"] != "running":
        raise AutomationTimingError(f"Stage {stage_id} is {stage['status']}, expected running")
    if status != "completed" and (reason is None or not reason.strip()):
        raise AutomationTimingError(f"Stage {stage_id} status {status} requires reason")
    if status == "completed":
        incomplete = [
            item["id"]
            for item in stage.get("checklist", [])
            if (
                item.get("required") is True and item.get("status") != "completed"
            )
            or item.get("status") == "in_progress"
        ]
        if incomplete:
            raise AutomationTimingError(
                f"Stage {stage_id} has unfinished checklist items: {', '.join(incomplete)}"
            )
    timestamp = normalized_timestamp(at)
    timer_model = ledger.get("timer_model", "legacy")
    actual_seconds: int | None = None
    finished: datetime | None = None
    if timer_model != "disabled":
        started = parse_timestamp(stage["started_at"], field=f"{stage_id}.started_at")
        finished = parse_timestamp(timestamp, field=f"{stage_id}.finished_at")
        elapsed_seconds = int((finished - started).total_seconds())
        if elapsed_seconds < 0:
            raise AutomationTimingError(f"Stage {stage_id} finish precedes start")
        if timer_model == "dual":
            if stage.get("active_started_at") is not None:
                active_started = parse_timestamp(
                    stage["active_started_at"], field=f"{stage_id}.active_started_at"
                )
                segment = int((finished - active_started).total_seconds())
                if segment < 0:
                    raise AutomationTimingError(f"Stage {stage_id} finish precedes active start")
                stage["active_seconds"] += segment
            else:
                pause_started = parse_timestamp(
                    stage["pause_started_at"], field=f"{stage_id}.pause_started_at"
                )
                pause_seconds = int((finished - pause_started).total_seconds())
                if pause_seconds < 0:
                    raise AutomationTimingError(f"Stage {stage_id} finish precedes pause")
                stage["pauses"].append(
                    {
                        "started_at": pause_started.isoformat(),
                        "finished_at": finished.isoformat(),
                        "seconds": pause_seconds,
                        "reason": stage["pause_reason"],
                    }
                )
            stage["active_started_at"] = None
            stage["pause_started_at"] = None
            stage["pause_reason"] = None
            stage["elapsed_seconds"] = elapsed_seconds
            actual_seconds = stage["active_seconds"]
        else:
            actual_seconds = elapsed_seconds
    stage["status"] = status
    stage["finished_at"] = finished.isoformat() if finished is not None else None
    stage["actual_seconds"] = actual_seconds
    stage["terminal_reason"] = reason.strip() if reason else None
    ledger["events"].append(
        {
            "at": finished.isoformat() if finished is not None else timestamp,
            "kind": "stage_stopped",
            "stage_id": stage_id,
            "status": status,
            "actual_seconds": actual_seconds,
            "reason": stage["terminal_reason"],
        }
    )


def record_milestone(
    ledger: dict[str, Any],
    *,
    kind: str,
    evidence_ref: str,
    external_system: str | None = None,
    external_item_id: str | None = None,
    read_back_at: str | None = None,
    at: str | None = None,
) -> dict[str, Any]:
    """Record publication, readiness, and the explicit development handoff."""
    if ledger.get("timer_model") != "dual":
        raise AutomationTimingError("Measured milestones require a dual timer")
    if kind not in {"publication", "ready_for_handoff", "development_handoff"}:
        raise AutomationTimingError(f"Invalid timing milestone: {kind}")
    if not isinstance(evidence_ref, str) or not evidence_ref.strip():
        raise AutomationTimingError("Timing milestone requires evidence_ref")
    milestones = ledger.setdefault("milestones", [])
    if any(item.get("kind") == "development_handoff" for item in milestones):
        raise AutomationTimingError("Timing case is already handed to development")
    state = current_case_state(ledger)
    previous_case_state = ledger.get("case_state")
    lifecycle_enabled = isinstance(previous_case_state, dict) or kind == "ready_for_handoff"
    if state == "deferred":
        raise AutomationTimingError("Deferred timing case must be resumed before a milestone")
    if kind in {"publication", "ready_for_handoff"} and state != "active":
        raise AutomationTimingError(f"Cannot record {kind} while case state is {state}")
    if (
        kind == "development_handoff"
        and lifecycle_enabled
        and state != "ready_for_handoff"
    ):
        raise AutomationTimingError(
            "Development handoff requires explicit ready_for_handoff state"
        )
    if any(stage.get("status") != "completed" for stage in ledger.get("stages", [])):
        raise AutomationTimingError(
            "Timing milestone requires every planned stage to be completed"
        )
    external_values = (external_system, external_item_id, read_back_at)
    if any(value is not None for value in external_values) and not all(
        isinstance(value, str) and value.strip() for value in external_values
    ):
        raise AutomationTimingError(
            "Milestone external read-back requires system, item id, and timestamp together"
        )
    timestamp = normalized_timestamp(at)
    milestone_at = parse_timestamp(timestamp, field="milestone.at")
    stage_starts = [
        parse_timestamp(stage["started_at"], field=f"{stage['id']}.started_at")
        for stage in ledger.get("stages", [])
        if stage.get("started_at") is not None
    ]
    if not stage_starts or milestone_at < min(stage_starts):
        raise AutomationTimingError("Timing milestone requires started case work")
    if kind in {"ready_for_handoff", "development_handoff"}:
        stage_finishes = [
            parse_timestamp(stage["finished_at"], field=f"{stage['id']}.finished_at")
            for stage in ledger.get("stages", [])
            if stage.get("finished_at") is not None
        ]
        if stage_finishes and milestone_at < max(stage_finishes):
            raise AutomationTimingError(f"{kind} precedes stage completion")
        publications = [
            parse_timestamp(item["at"], field="publication.at")
            for item in milestones
            if item.get("kind") == "publication"
        ]
        if not publications or (stage_finishes and max(publications) < max(stage_finishes)):
            raise AutomationTimingError(
                f"{kind} requires a publication after final edits"
            )
        if publications and milestone_at < max(publications):
            raise AutomationTimingError(f"{kind} precedes the latest publication")
        if kind == "development_handoff" and lifecycle_enabled:
            ready = [
                parse_timestamp(item["at"], field="ready_for_handoff.at")
                for item in milestones
                if item.get("kind") == "ready_for_handoff"
            ]
            if not ready or milestone_at < max(ready):
                raise AutomationTimingError(
                    "Development handoff requires a preceding ready_for_handoff milestone"
                )
    external_read_back = (
        {
            "system": external_system.strip(),
            "item_id": external_item_id.strip(),
            "read_back_at": parse_timestamp(
                read_back_at, field="milestone.external_read_back.read_back_at"
            ).isoformat(),
        }
        if external_system is not None
        else None
    )
    milestone: dict[str, Any] = {
        "kind": kind,
        "at": timestamp,
        "evidence_ref": evidence_ref.strip(),
        "external_read_back": external_read_back,
        "publication_revision": (
            1 + sum(item.get("kind") == "publication" for item in milestones)
            if kind == "publication"
            else None
        ),
        "ready_revision": (
            1 + sum(item.get("kind") == "ready_for_handoff" for item in milestones)
            if kind == "ready_for_handoff"
            else None
        ),
    }
    milestones.append(milestone)
    ledger["events"].append(
        {
            "at": timestamp,
            "kind": f"timing_{kind}",
            "publication_revision": milestone["publication_revision"],
            "ready_revision": milestone["ready_revision"],
            "evidence_ref": milestone["evidence_ref"],
        }
    )
    if kind in {"ready_for_handoff", "development_handoff"} and lifecycle_enabled:
        ledger["case_state"] = {
            "status": (
                "ready_for_handoff"
                if kind == "ready_for_handoff"
                else "handed_off"
            ),
            "changed_at": timestamp,
            "reason": None,
            "evidence_ref": evidence_ref.strip(),
            "resume_status": None,
            "projection_readbacks": [],
        }
    errors = validate_ledger(ledger)
    if errors:
        milestones.pop()
        ledger["events"].pop()
        if kind in {"ready_for_handoff", "development_handoff"} and lifecycle_enabled:
            if isinstance(previous_case_state, dict):
                ledger["case_state"] = previous_case_state
            else:
                ledger.pop("case_state", None)
        raise AutomationTimingError("; ".join(errors))
    return milestone


def live_active_seconds(stage: dict[str, Any], at: datetime) -> int:
    value = int(stage.get("active_seconds", 0))
    active_started_at = stage.get("active_started_at")
    if active_started_at is not None:
        started = parse_timestamp(active_started_at, field=f"{stage.get('id')}.active_started_at")
        segment = int((at - started).total_seconds())
        if segment < 0:
            raise AutomationTimingError("Checkpoint precedes an active timer")
        value += segment
    return value


def live_critical_path_seconds(stages: list[dict[str, Any]], at: datetime) -> int:
    by_id = {stage["id"]: stage for stage in stages}
    totals: dict[str, int] = {}

    def total(stage_id: str) -> int:
        if stage_id in totals:
            return totals[stage_id]
        stage = by_id[stage_id]
        dependency_total = max((total(item) for item in stage["depends_on"]), default=0)
        totals[stage_id] = dependency_total + live_active_seconds(stage, at)
        return totals[stage_id]

    return max((total(stage_id) for stage_id in by_id), default=0)


def build_checkpoint(ledger: dict[str, Any], *, at: str | None = None) -> dict[str, Any]:
    """Build a deterministic last-known snapshot suitable for external mirroring."""
    errors = validate_ledger(ledger)
    if errors:
        raise AutomationTimingError("; ".join(errors))
    if ledger.get("timer_model") != "dual":
        raise AutomationTimingError("Timing checkpoints require a dual timer")
    timestamp = parse_timestamp(normalized_timestamp(at), field="checkpoint.at")
    stages = ledger["stages"]
    starts = [
        parse_timestamp(stage["started_at"], field=f"{stage['id']}.started_at")
        for stage in stages
        if stage.get("started_at") is not None
    ]
    handoff = next(
        (
            item
            for item in ledger.get("milestones", [])
            if item.get("kind") == "development_handoff"
        ),
        None,
    )
    elapsed_end = (
        parse_timestamp(handoff["at"], field="development_handoff.at")
        if handoff is not None
        else timestamp
    )
    elapsed = int((elapsed_end - min(starts)).total_seconds()) if starts else 0
    if elapsed < 0:
        raise AutomationTimingError("Checkpoint precedes case start")
    explicit_state = current_case_state(ledger)
    if explicit_state in {"deferred", "ready_for_handoff", "handed_off"}:
        state = explicit_state
    elif handoff is not None:
        state = "handed_off"
    elif any(stage.get("active_started_at") is not None for stage in stages):
        state = "active"
    elif any(stage.get("pause_started_at") is not None for stage in stages):
        state = "paused"
    elif all(stage.get("status") in TERMINAL_STATUSES for stage in stages):
        state = "awaiting_handoff"
    else:
        state = "pending"
    checkpoint: dict[str, Any] = {
        "schema": SCHEMA_VERSION,
        "purpose": "human_information_only",
        "case_id": ledger["case_id"],
        "plan_fingerprint": ledger["plan_fingerprint"],
        "checkpoint_revision": len(ledger.get("events", [])),
        "ledger_fingerprint": canonical_fingerprint(ledger),
        "state": state,
        "generated_at": timestamp.isoformat(),
        "active_critical_path_seconds": live_critical_path_seconds(stages, timestamp),
        "active_stage_sum_seconds": sum(live_active_seconds(stage, timestamp) for stage in stages),
        "elapsed_seconds": elapsed,
        "publication_count": sum(
            item.get("kind") == "publication" for item in ledger.get("milestones", [])
        ),
        "ready_for_handoff_at": next(
            (
                item.get("at")
                for item in reversed(ledger.get("milestones", []))
                if item.get("kind") == "ready_for_handoff"
            ),
            None,
        ),
        "development_handoff_at": handoff.get("at") if handoff is not None else None,
    }
    checkpoint["fingerprint"] = canonical_fingerprint(checkpoint)
    return checkpoint


def reconcile_checkpoint(
    ledger: dict[str, Any], external: Any, *, at: str | None = None
) -> dict[str, Any]:
    """Compare local canonical history with one external last-known snapshot."""
    if not isinstance(external, dict) or external.get("fingerprint") != canonical_fingerprint(
        external
    ):
        raise AutomationTimingError("External timing checkpoint fingerprint mismatch")
    local = build_checkpoint(ledger, at=at)
    if external.get("case_id") != local["case_id"] or external.get(
        "plan_fingerprint"
    ) != local["plan_fingerprint"]:
        raise AutomationTimingError("External timing checkpoint belongs to another case")
    local_revision = local["checkpoint_revision"]
    external_revision = external.get("checkpoint_revision")
    if not isinstance(external_revision, int):
        raise AutomationTimingError("External timing checkpoint revision is invalid")
    if external_revision < local_revision:
        status = "local_ahead"
    elif external_revision > local_revision:
        status = "external_ahead_partial_recovery_required"
    elif external.get("ledger_fingerprint") == local["ledger_fingerprint"]:
        live_fields = (
            "state",
            "active_critical_path_seconds",
            "active_stage_sum_seconds",
            "elapsed_seconds",
            "publication_count",
            "ready_for_handoff_at",
            "development_handoff_at",
        )
        status = (
            "in_sync"
            if all(external.get(field) == local.get(field) for field in live_fields)
            else "local_clock_advanced"
        )
    else:
        status = "conflict_same_revision"
    return {
        "status": status,
        "local": local,
        "external": external,
        "safe_to_overwrite_external": status in {
            "local_ahead",
            "local_clock_advanced",
        },
        "training_eligible": status in {
            "in_sync",
            "local_ahead",
            "local_clock_advanced",
        },
    }


def critical_path_seconds(stages: list[dict[str, Any]], value_key: str) -> int:
    """Return dependency-aware critical-path duration for one estimate field."""
    by_id = {stage["id"]: stage for stage in stages}
    totals: dict[str, int] = {}

    def total(stage_id: str) -> int:
        if stage_id in totals:
            return totals[stage_id]
        stage = by_id[stage_id]
        duration = int(stage["estimate"][value_key])
        dependency_total = max((total(item) for item in stage["depends_on"]), default=0)
        totals[stage_id] = dependency_total + duration
        return totals[stage_id]

    return max((total(stage_id) for stage_id in by_id), default=0)


def runtime_critical_path_seconds(stages: list[dict[str, Any]]) -> int | None:
    """Return active critical-path fact once every stage is terminal."""
    if not stages or any(
        stage.get("status") not in TERMINAL_STATUSES
        or not isinstance(stage.get("actual_seconds"), int)
        for stage in stages
    ):
        return None
    by_id = {stage["id"]: stage for stage in stages}
    totals: dict[str, int] = {}

    def total(stage_id: str) -> int:
        if stage_id in totals:
            return totals[stage_id]
        stage = by_id[stage_id]
        dependency_total = max((total(item) for item in stage["depends_on"]), default=0)
        totals[stage_id] = dependency_total + int(stage["actual_seconds"])
        return totals[stage_id]

    return max((total(stage_id) for stage_id in by_id), default=0)


def summarize(ledger: dict[str, Any]) -> dict[str, Any]:
    """Build a stable machine-readable forecast and actual summary."""
    errors = validate_ledger(ledger)
    if errors:
        raise AutomationTimingError("; ".join(errors))
    stages = ledger["stages"]
    has_manual_estimates = bool(stages) and all(
        isinstance(stage.get("estimate"), dict) for stage in stages
    )
    if has_manual_estimates:
        forecast = {
            key.replace("_seconds", "_critical_path_seconds"): critical_path_seconds(stages, key)
            for key in ("optimistic_seconds", "likely_seconds", "pessimistic_seconds")
        }
        forecast["likely_stage_sum_seconds"] = sum(
            stage["estimate"]["likely_seconds"] for stage in stages
        )
    else:
        forecast = {
            "optimistic_critical_path_seconds": None,
            "likely_critical_path_seconds": None,
            "pessimistic_critical_path_seconds": None,
            "likely_stage_sum_seconds": None,
        }

    terminal = [stage for stage in stages if stage["status"] in TERMINAL_STATUSES]
    completed = [stage for stage in stages if stage["status"] == "completed"]
    timed_terminal = [
        stage
        for stage in terminal
        if stage.get("started_at") is not None and stage.get("finished_at") is not None
    ]
    starts = [
        parse_timestamp(stage["started_at"], field=f"{stage['id']}.started_at")
        for stage in timed_terminal
    ]
    finishes = [
        parse_timestamp(stage["finished_at"], field=f"{stage['id']}.finished_at")
        for stage in timed_terminal
    ]
    handoff = next(
        (
            item
            for item in ledger.get("milestones", [])
            if isinstance(item, dict) and item.get("kind") == "development_handoff"
        ),
        None,
    )
    elapsed_finish = (
        parse_timestamp(handoff["at"], field="development_handoff.at")
        if handoff is not None
        else (max(finishes) if finishes else None)
    )
    actual_elapsed = (
        int((elapsed_finish - min(starts)).total_seconds())
        if starts and elapsed_finish is not None
        else None
    )
    likely = forecast["likely_critical_path_seconds"]
    estimate_ratio = (
        round(actual_elapsed / likely, 4)
        if actual_elapsed is not None
        and isinstance(likely, int)
        and likely > 0
        and len(terminal) == len(stages)
        else None
    )
    counts = {status: 0 for status in sorted(STAGE_STATUSES)}
    for stage in stages:
        counts[stage["status"]] += 1
    checklist = [item for stage in stages for item in stage.get("checklist", [])]
    return {
        "case_id": ledger["case_id"],
        "planning": ledger.get("planning"),
        "passport": ledger.get("passport"),
        "policy": ledger["policy"],
        "metric": ledger["metric"],
        "unit": ledger["unit"],
        "execution_use": ledger["execution_use"],
        "forecast": forecast,
        "actual": {
            "elapsed_seconds": actual_elapsed,
            "active_critical_path_seconds": runtime_critical_path_seconds(stages),
            "stage_sum_seconds": sum(
                stage["actual_seconds"]
                for stage in terminal
                if isinstance(stage.get("actual_seconds"), int)
            ),
            "completed_stage_sum_seconds": sum(
                stage["actual_seconds"]
                for stage in completed
                if isinstance(stage.get("actual_seconds"), int)
            ),
            "likely_estimate_ratio": estimate_ratio,
        },
        "timer_model": ledger.get("timer_model", "legacy"),
        "case_state": current_case_state(ledger),
        "milestones": ledger.get("milestones", []),
        "status_counts": counts,
        "terminal_stage_count": len(terminal),
        "stage_count": len(stages),
        "checklist_item_count": len(checklist),
        "completed_checklist_item_count": sum(
            1 for item in checklist if item.get("status") == "completed"
        ),
        "in_progress_checklist_item_count": sum(
            1 for item in checklist if item.get("status") == "in_progress"
        ),
        "complete": len(terminal) == len(stages),
    }


def render_summary(summary: dict[str, Any]) -> str:
    """Render a compact Markdown summary."""
    forecast = summary["forecast"]
    actual = summary["actual"]
    lines = [
        f"# Automation timing: {summary['case_id']}",
        "",
        f"- metric: `{summary['metric']}`",
        f"- policy: `{summary['policy']}`",
        f"- execution use: `{summary['execution_use']}`",
        "- forecast critical path: "
        f"{forecast['optimistic_critical_path_seconds']} / "
        f"{forecast['likely_critical_path_seconds']} / "
        f"{forecast['pessimistic_critical_path_seconds']} seconds",
        f"- actual elapsed: `{actual['elapsed_seconds']}` seconds",
        f"- actual active critical path: `{actual['active_critical_path_seconds']}` seconds",
        f"- stages terminal: `{summary['terminal_stage_count']}/{summary['stage_count']}`",
        "- checklist completed: "
        f"`{summary['completed_checklist_item_count']}/{summary['checklist_item_count']}`",
        f"- checklist in progress: `{summary['in_progress_checklist_item_count']}`",
        f"- likely estimate ratio: `{actual['likely_estimate_ratio']}`",
    ]
    return "\n".join(lines) + "\n"


def discover_ledgers(roots: list[Path]) -> list[Path]:
    """Find unique ledger files under explicit roots."""
    found: set[Path] = set()
    for root in roots:
        candidate = root.expanduser().resolve()
        if candidate.is_file():
            if candidate.name == FILENAME:
                found.add(candidate)
            continue
        direct = candidate / FILENAME
        if direct.is_file():
            found.add(direct)
            continue
        if candidate.is_dir():
            found.update(path.resolve() for path in candidate.rglob(FILENAME))
    return sorted(found)


def aggregate(roots: list[Path]) -> dict[str, Any]:
    """Aggregate completed and partial ledgers without inventing a forecast model."""
    cases: list[dict[str, Any]] = []
    stage_actuals: dict[str, list[int]] = {}
    ratios: list[float] = []
    for path in discover_ledgers(roots):
        _, ledger = load_ledger(path)
        summary = summarize(ledger)
        summary["path"] = str(path)
        cases.append(summary)
        ratio = summary["actual"]["likely_estimate_ratio"]
        if isinstance(ratio, (int, float)):
            ratios.append(float(ratio))
        for stage in ledger["stages"]:
            if stage["status"] == "completed" and isinstance(
                stage.get("actual_seconds"), int
            ):
                stage_actuals.setdefault(stage["title"], []).append(stage["actual_seconds"])

    by_stage = {
        title: {
            "sample_size": len(values),
            "median_actual_seconds": int(statistics.median(values)),
            "mean_actual_seconds": round(statistics.fmean(values), 2),
        }
        for title, values in sorted(stage_actuals.items())
    }
    return {
        "schema": SCHEMA_VERSION,
        "case_count": len(cases),
        "complete_case_count": sum(1 for item in cases if item["complete"]),
        "median_likely_estimate_ratio": round(statistics.median(ratios), 4) if ratios else None,
        "cases": cases,
        "by_stage_title": by_stage,
    }


def build_parser() -> argparse.ArgumentParser:
    """Build command-line interface."""
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    start_parser = subparsers.add_parser("start", help="Start one planned stage")
    start_parser.add_argument("--case-root", required=True)
    start_parser.add_argument("--stage", required=True)
    start_parser.add_argument("--at")

    pause_parser = subparsers.add_parser(
        "pause",
        help="Pause one stage or every active stage; elapsed time keeps running",
    )
    pause_parser.add_argument("--case-root", required=True)
    pause_parser.add_argument("--stage")
    pause_parser.add_argument("--reason", choices=sorted(USER_PAUSE_REASONS), required=True)
    pause_parser.add_argument("--at")

    defer_parser = subparsers.add_parser(
        "defer",
        help="Suspend case WIP; active and business clocks stop learning backlog time",
    )
    defer_parser.add_argument("--case-root", required=True)
    defer_parser.add_argument("--reason", required=True)
    defer_parser.add_argument("--evidence", required=True)
    defer_parser.add_argument("--projection-readbacks")
    defer_parser.add_argument("--at")

    resume_parser = subparsers.add_parser(
        "resume",
        help="Resume one stage or every paused stage",
    )
    resume_parser.add_argument("--case-root", required=True)
    resume_parser.add_argument("--stage")
    resume_parser.add_argument("--evidence")
    resume_parser.add_argument("--projection-readbacks")
    resume_parser.add_argument("--at")

    reopen_parser = subparsers.add_parser(
        "reopen", help="Reopen a completed stage for post-publication edits"
    )
    reopen_parser.add_argument("--case-root", required=True)
    reopen_parser.add_argument("--stage", required=True)
    reopen_parser.add_argument("--evidence", required=True)
    reopen_parser.add_argument("--at")

    milestone_parser = subparsers.add_parser(
        "milestone", help="Record publication, readiness, or explicit development handoff"
    )
    milestone_parser.add_argument("--case-root", required=True)
    milestone_parser.add_argument(
        "--kind",
        choices=("publication", "ready_for_handoff", "development_handoff"),
        required=True,
    )
    milestone_parser.add_argument("--evidence", required=True)
    milestone_parser.add_argument("--external-system")
    milestone_parser.add_argument("--external-item-id")
    milestone_parser.add_argument("--read-back-at")
    milestone_parser.add_argument("--at")

    checkpoint_parser = subparsers.add_parser(
        "checkpoint", help="Build a last-known snapshot for an external mirror"
    )
    checkpoint_parser.add_argument("--case-root", required=True)
    checkpoint_parser.add_argument("--write")
    checkpoint_parser.add_argument("--at")

    reconcile_parser = subparsers.add_parser(
        "reconcile", help="Compare local history with an external checkpoint read-back"
    )
    reconcile_parser.add_argument("--case-root", required=True)
    reconcile_parser.add_argument("--external-checkpoint", required=True)
    reconcile_parser.add_argument("--at")

    bind_progress_parser = subparsers.add_parser(
        "bind-progress",
        help="Bind stable Pxx-Cxx ids to one external checklist target",
    )
    bind_progress_parser.add_argument("--case-root", required=True)
    bind_progress_parser.add_argument("--receipt", required=True)
    bind_progress_parser.add_argument("--at")

    migrate_progress_parser = subparsers.add_parser(
        "migrate-progress",
        help="Atomically bind and reconcile a legacy completed checklist",
    )
    migrate_progress_parser.add_argument("--case-root", required=True)
    migrate_progress_parser.add_argument("--receipt", required=True)
    migrate_progress_parser.add_argument("--evidence", required=True)
    migrate_progress_parser.add_argument("--at")

    reconcile_progress_parser = subparsers.add_parser(
        "reconcile-progress",
        help="Read back every bound external checklist item and detect drift",
    )
    reconcile_progress_parser.add_argument("--case-root", required=True)
    reconcile_progress_parser.add_argument("--receipt", required=True)
    reconcile_progress_parser.add_argument("--at")

    begin_parser = subparsers.add_parser(
        "begin",
        help="Claim any checklist item before starting its work",
    )
    begin_parser.add_argument("--case-root", required=True)
    begin_parser.add_argument("--stage", required=True)
    begin_parser.add_argument("--item", required=True)
    begin_parser.add_argument(
        "--parallel-reason",
        help="Why another item may remain in progress concurrently",
    )
    begin_parser.add_argument("--at")

    stop_parser = subparsers.add_parser("stop", help="Stop one running stage")
    stop_parser.add_argument("--case-root", required=True)
    stop_parser.add_argument("--stage", required=True)
    stop_parser.add_argument("--status", choices=sorted(TERMINAL_STATUSES), required=True)
    stop_parser.add_argument("--reason")
    stop_parser.add_argument("--at")

    check_parser = subparsers.add_parser(
        "check",
        help="Mark one completed checklist item after evidence/read-back",
    )
    check_parser.add_argument("--case-root", required=True)
    check_parser.add_argument("--stage", required=True)
    check_parser.add_argument("--item", required=True)
    check_parser.add_argument("--evidence", action="append", default=[])
    check_parser.add_argument("--external-system")
    check_parser.add_argument("--external-item-id")
    check_parser.add_argument("--external-title")
    check_parser.add_argument("--read-back-at")
    check_parser.add_argument(
        "--user-confirmed",
        action="store_true",
        help="Record an explicit user-owned checklist confirmation after external read-back",
    )
    check_parser.add_argument("--at")

    validate_parser = subparsers.add_parser("validate", help="Validate timing ledger")
    validate_parser.add_argument("--case-root", required=True)
    validate_parser.add_argument("--final", action="store_true")

    summary_parser = subparsers.add_parser("summary", help="Summarize one timing ledger")
    summary_parser.add_argument("--case-root", required=True)
    summary_parser.add_argument("--json", action="store_true")

    aggregate_parser = subparsers.add_parser("aggregate", help="Aggregate ledger history")
    aggregate_parser.add_argument("--root", action="append", required=True)
    return parser


def main() -> int:
    """Run CLI."""
    args = build_parser().parse_args()
    try:
        if args.command in {
            "start",
            "pause",
            "defer",
            "resume",
            "reopen",
            "milestone",
            "checkpoint",
            "reconcile",
            "bind-progress",
            "migrate-progress",
            "reconcile-progress",
            "begin",
            "check",
            "stop",
            "validate",
            "summary",
        }:
            path, ledger = load_ledger(Path(args.case_root))
        if args.command == "start":
            start_stage(ledger, args.stage, at=args.at)
            save_ledger(path, ledger)
            print(f"PASS stage={args.stage} status=running")
            return 0
        if args.command == "pause":
            stage_ids = (
                [args.stage]
                if args.stage
                else [
                    stage["id"]
                    for stage in ledger["stages"]
                    if stage.get("status") == "running"
                    and stage.get("active_started_at") is not None
                ]
            )
            if not stage_ids:
                raise AutomationTimingError("No active stages to pause")
            for stage_id in stage_ids:
                pause_stage(ledger, stage_id, reason=args.reason, at=args.at)
            save_ledger(path, ledger)
            print(f"PASS paused={','.join(stage_ids)} reason={args.reason}")
            return 0
        if args.command == "defer":
            projection_readbacks = (
                json.loads(Path(args.projection_readbacks).read_text(encoding="utf-8"))
                if args.projection_readbacks
                else []
            )
            defer_case(
                ledger,
                reason=args.reason,
                evidence_ref=args.evidence,
                projection_readbacks=projection_readbacks,
                at=args.at,
            )
            save_ledger(path, ledger)
            print("PASS case_state=deferred")
            return 0
        if args.command == "resume":
            if current_case_state(ledger) == "deferred":
                projection_readbacks = (
                    json.loads(Path(args.projection_readbacks).read_text(encoding="utf-8"))
                    if args.projection_readbacks
                    else []
                )
                resumed = resume_case(
                    ledger,
                    evidence_ref=args.evidence,
                    projection_readbacks=projection_readbacks,
                    at=args.at,
                )
                save_ledger(path, ledger)
                print(
                    f"PASS case_state={current_case_state(ledger)} "
                    f"resumed={','.join(resumed)}"
                )
                return 0
            stage_ids = (
                [args.stage]
                if args.stage
                else [
                    stage["id"]
                    for stage in ledger["stages"]
                    if stage.get("status") == "running"
                    and stage.get("pause_started_at") is not None
                ]
            )
            if not stage_ids:
                raise AutomationTimingError("No paused stages to resume")
            for stage_id in stage_ids:
                resume_stage(ledger, stage_id, at=args.at)
            save_ledger(path, ledger)
            print(f"PASS resumed={','.join(stage_ids)}")
            return 0
        if args.command == "reopen":
            reopen_stage(
                ledger,
                args.stage,
                evidence_ref=args.evidence,
                at=args.at,
            )
            save_ledger(path, ledger)
            print(f"PASS reopened={args.stage}")
            return 0
        if args.command == "milestone":
            milestone = record_milestone(
                ledger,
                kind=args.kind,
                evidence_ref=args.evidence,
                external_system=args.external_system,
                external_item_id=args.external_item_id,
                read_back_at=args.read_back_at,
                at=args.at,
            )
            save_ledger(path, ledger)
            checkpoint = build_checkpoint(ledger, at=args.at)
            print(
                f"PASS milestone={args.kind} "
                f"publication_revision={milestone.get('publication_revision')} "
                f"checkpoint_revision={checkpoint['checkpoint_revision']}"
            )
            return 0
        if args.command == "checkpoint":
            result = build_checkpoint(ledger, at=args.at)
            if args.write:
                atomic_json(Path(args.write), result)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command == "reconcile":
            external = json.loads(Path(args.external_checkpoint).read_text(encoding="utf-8"))
            result = reconcile_checkpoint(ledger, external, at=args.at)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command in {"bind-progress", "migrate-progress", "reconcile-progress"}:
            receipt = json.loads(Path(args.receipt).read_text(encoding="utf-8"))
            if args.command == "bind-progress":
                changed = bind_progress_projection(ledger, receipt, at=args.at)
            elif args.command == "migrate-progress":
                changed = migrate_progress_projection(
                    ledger,
                    receipt,
                    evidence_ref=args.evidence,
                    at=args.at,
                )
            else:
                changed = reconcile_progress_projection(ledger, receipt, at=args.at)
            if changed:
                save_ledger(path, ledger)
            print(
                f"PASS command={args.command} changed={str(changed).lower()} "
                f"progress_target_id={ledger.get('progress_target_id')}"
            )
            return 0
        if args.command == "begin":
            changed = begin_checklist_item(
                ledger,
                args.stage,
                args.item,
                parallel_reason=args.parallel_reason,
                at=args.at,
            )
            if changed:
                save_ledger(path, ledger)
            item = find_checklist_item(find_stage(ledger, args.stage), args.item)
            print(
                f"PASS stage={args.stage} item={args.item} status=in_progress "
                f"text={json.dumps(item['text'], ensure_ascii=False)} "
                f"done_when={json.dumps(item.get('done_when'), ensure_ascii=False)}"
            )
            return 0
        if args.command == "check":
            changed = complete_checklist_item(
                ledger,
                args.stage,
                args.item,
                evidence_refs=args.evidence,
                external_system=args.external_system,
                external_item_id=args.external_item_id,
                external_title=args.external_title,
                read_back_at=args.read_back_at,
                user_confirmed=args.user_confirmed,
                at=args.at,
            )
            if changed:
                save_ledger(path, ledger)
            print(f"PASS stage={args.stage} item={args.item} status=completed")
            return 0
        if args.command == "stop":
            stop_stage(
                ledger,
                args.stage,
                status=args.status,
                reason=args.reason,
                at=args.at,
            )
            save_ledger(path, ledger)
            print(
                f"PASS stage={args.stage} status={args.status} "
                f"actual_seconds={find_stage(ledger, args.stage)['actual_seconds']}"
            )
            return 0
        if args.command == "validate":
            errors = validate_ledger(ledger, final=args.final)
            if errors:
                raise AutomationTimingError("\n".join(f"- {item}" for item in errors))
            print(f"PASS case={ledger['case_id']} final={str(args.final).lower()}")
            return 0
        if args.command == "summary":
            result = summarize(ledger)
            print(
                json.dumps(result, ensure_ascii=False, indent=2)
                if args.json
                else render_summary(result),
                end="" if args.json else "",
            )
            if args.json:
                print()
            return 0
        if args.command == "aggregate":
            result = aggregate([Path(value) for value in args.root])
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        raise AssertionError(args.command)
    except (AutomationTimingError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
