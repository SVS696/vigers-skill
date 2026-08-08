#!/usr/bin/env python3
"""Record and aggregate automated Vigers wall-clock execution time."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
FILENAME = "automation-timing.json"
POLICIES = {"optional", "required"}
METRIC = "wall_clock"
UNIT = "seconds"
EXECUTION_USE = "human_information_only"
ESTIMATE_BASES = {"historical", "analogous", "heuristic"}
CONFIDENCE_LEVELS = {"low", "medium", "high"}
TERMINAL_STATUSES = {"completed", "failed", "blocked", "cancelled"}
STAGE_STATUSES = {"pending", "running", *TERMINAL_STATUSES}
CHECKLIST_STATUSES = {"pending", "completed"}


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
    if policy.get("policy") != "required":
        errors.append("plan.json automation_estimation policy must be required")
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
    for stage in stages:
        stage_id = stage.get("id", "<unknown>") if isinstance(stage, dict) else "<unknown>"
        estimate = stage.get("automation_estimate") if isinstance(stage, dict) else None
        errors.extend(validate_estimate(estimate, prefix=str(stage_id)))
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
            "estimate": dict(stage["automation_estimate"]),
            "external_target_id": stage.get("external_target_id"),
            "checklist": [
                {
                    "id": item["id"],
                    "text": item["text"],
                    "required": item.get("required", True),
                    "done_when": item.get("done_when"),
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
        errors.extend(validate_estimate(stage.get("estimate"), prefix=stage_id))
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
        "created_at": timestamp,
        "updated_at": timestamp,
        "stages": [
            {
                "id": stage["id"],
                "title": stage["title"],
                "depends_on": list(stage["depends_on"]),
                "estimate": dict(stage["estimate"]),
                "external_target_id": stage.get("external_target_id"),
                "checklist": [
                    {
                        "id": item["id"],
                        "text": item["text"],
                        "required": item["required"],
                        "done_when": item.get("done_when"),
                        "status": "pending",
                        "completed_at": None,
                        "evidence_refs": [],
                        "external_read_back": None,
                    }
                    for item in stage["checklist"]
                ],
                "status": "pending",
                "started_at": None,
                "finished_at": None,
                "actual_seconds": None,
                "terminal_reason": None,
            }
            for stage in automation_plan["stages"]
        ],
        "events": [],
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
                    }
                    for item in stage.get("checklist", [])
                    if isinstance(item, dict)
                ],
            }
            for stage in ledger.get("stages", [])
            if isinstance(stage, dict)
        ],
    }
    result["fingerprint"] = canonical_fingerprint(result)
    return result


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
            if item_status not in CHECKLIST_STATUSES:
                errors.append(f"{item_id}: invalid checklist status {item_status!r}")
                continue
            completed_at = item.get("completed_at")
            evidence_refs = item.get("evidence_refs")
            external_read_back = item.get("external_read_back")
            if not isinstance(evidence_refs, list) or any(
                not isinstance(ref, str) or not ref.strip() for ref in evidence_refs
            ):
                errors.append(f"{item_id}: evidence_refs must be a string array")
                evidence_refs = []
            if item_status == "pending":
                if completed_at is not None or evidence_refs or external_read_back is not None:
                    errors.append(f"{item_id}: pending checklist item cannot have completion facts")
            else:
                try:
                    parse_timestamp(completed_at, field=f"{item_id}.completed_at")
                except AutomationTimingError as exc:
                    errors.append(str(exc))
                if not evidence_refs and external_read_back is None:
                    errors.append(f"{item_id}: completed checklist item requires evidence")
                target_id = stage.get("external_target_id")
                if target_id is not None:
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

        if status == "pending":
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
                    and item.get("required") is True
                    and item.get("status") != "completed"
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

    if final and payload.get("policy") == "required":
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


def complete_checklist_item(
    ledger: dict[str, Any],
    stage_id: str,
    item_id: str,
    *,
    evidence_refs: list[str],
    external_system: str | None = None,
    external_item_id: str | None = None,
    read_back_at: str | None = None,
    at: str | None = None,
) -> bool:
    """Mark one finished item immediately after evidence and external read-back."""
    errors = validate_ledger(ledger)
    if errors:
        raise AutomationTimingError("; ".join(errors))
    stage = find_stage(ledger, stage_id)
    if stage["status"] != "running":
        raise AutomationTimingError(
            f"Stage {stage_id} is {stage['status']}, checklist updates require running"
        )
    item = find_checklist_item(stage, item_id)
    normalized_evidence = list(dict.fromkeys(ref.strip() for ref in evidence_refs if ref.strip()))
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
    desired = {
        "completed_at": timestamp,
        "evidence_refs": normalized_evidence,
        "external_read_back": external_read_back,
    }
    if item["status"] == "completed":
        current = {key: item.get(key) for key in desired}
        if current == desired:
            return False
        raise AutomationTimingError(
            f"Checklist item {item_id} is already completed with different evidence"
        )
    item.update(status="completed", **desired)
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


def start_stage(ledger: dict[str, Any], stage_id: str, *, at: str | None = None) -> None:
    """Start a pending stage after all dependencies completed."""
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
    stage["started_at"] = timestamp
    ledger["events"].append({"at": timestamp, "kind": "stage_started", "stage_id": stage_id})


def stop_stage(
    ledger: dict[str, Any],
    stage_id: str,
    *,
    status: str,
    reason: str | None,
    at: str | None = None,
) -> None:
    """Finish a running stage with one terminal status."""
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
            if item.get("required") is True and item.get("status") != "completed"
        ]
        if incomplete:
            raise AutomationTimingError(
                f"Stage {stage_id} has unfinished checklist items: {', '.join(incomplete)}"
            )
    timestamp = normalized_timestamp(at)
    started = parse_timestamp(stage["started_at"], field=f"{stage_id}.started_at")
    finished = parse_timestamp(timestamp, field=f"{stage_id}.finished_at")
    actual_seconds = int((finished - started).total_seconds())
    if actual_seconds < 0:
        raise AutomationTimingError(f"Stage {stage_id} finish precedes start")
    stage["status"] = status
    stage["finished_at"] = finished.isoformat()
    stage["actual_seconds"] = actual_seconds
    stage["terminal_reason"] = reason.strip() if reason else None
    ledger["events"].append(
        {
            "at": finished.isoformat(),
            "kind": "stage_stopped",
            "stage_id": stage_id,
            "status": status,
            "actual_seconds": actual_seconds,
            "reason": stage["terminal_reason"],
        }
    )


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


def summarize(ledger: dict[str, Any]) -> dict[str, Any]:
    """Build a stable machine-readable forecast and actual summary."""
    errors = validate_ledger(ledger)
    if errors:
        raise AutomationTimingError("; ".join(errors))
    stages = ledger["stages"]
    forecast = {
        key.replace("_seconds", "_critical_path_seconds"): critical_path_seconds(stages, key)
        for key in ("optimistic_seconds", "likely_seconds", "pessimistic_seconds")
    }
    forecast["likely_stage_sum_seconds"] = sum(
        stage["estimate"]["likely_seconds"] for stage in stages
    )

    terminal = [stage for stage in stages if stage["status"] in TERMINAL_STATUSES]
    completed = [stage for stage in stages if stage["status"] == "completed"]
    starts = [
        parse_timestamp(stage["started_at"], field=f"{stage['id']}.started_at")
        for stage in terminal
    ]
    finishes = [
        parse_timestamp(stage["finished_at"], field=f"{stage['id']}.finished_at")
        for stage in terminal
    ]
    actual_elapsed = int((max(finishes) - min(starts)).total_seconds()) if terminal else None
    likely = forecast["likely_critical_path_seconds"]
    estimate_ratio = (
        round(actual_elapsed / likely, 4)
        if actual_elapsed is not None and likely > 0 and len(terminal) == len(stages)
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
            "stage_sum_seconds": sum(stage["actual_seconds"] for stage in terminal),
            "completed_stage_sum_seconds": sum(stage["actual_seconds"] for stage in completed),
            "likely_estimate_ratio": estimate_ratio,
        },
        "status_counts": counts,
        "terminal_stage_count": len(terminal),
        "stage_count": len(stages),
        "checklist_item_count": len(checklist),
        "completed_checklist_item_count": sum(
            1 for item in checklist if item.get("status") == "completed"
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
        f"- stages terminal: `{summary['terminal_stage_count']}/{summary['stage_count']}`",
        "- checklist completed: "
        f"`{summary['completed_checklist_item_count']}/{summary['checklist_item_count']}`",
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
            if stage["status"] == "completed":
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
    check_parser.add_argument("--read-back-at")
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
        if args.command in {"start", "check", "stop", "validate", "summary"}:
            path, ledger = load_ledger(Path(args.case_root))
        if args.command == "start":
            start_stage(ledger, args.stage, at=args.at)
            save_ledger(path, ledger)
            print(f"PASS stage={args.stage} status=running")
            return 0
        if args.command == "check":
            changed = complete_checklist_item(
                ledger,
                args.stage,
                args.item,
                evidence_refs=args.evidence,
                external_system=args.external_system,
                external_item_id=args.external_item_id,
                read_back_at=args.read_back_at,
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
