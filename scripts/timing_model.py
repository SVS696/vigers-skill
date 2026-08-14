#!/usr/bin/env python3
"""Project-local empirical timing calibration for human planning only."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from automation_timing import AutomationTimingError, load_ledger, summarize
from mode_decision import ModeDecisionError, validate_mode_decision


SCHEMA_VERSION = 1
FEATURE_SCHEMA_VERSION = 2
SUPPORTED_FEATURE_SCHEMA_VERSIONS = {1, FEATURE_SCHEMA_VERSION}
DEFAULT_RELATIVE_PATH = Path(".vigers/telemetry/timing-model.json")
CALIBRATION_FILENAME = "timing-calibration.json"
MAX_NEIGHBORS = 12
BOOLEAN_RISKS = (
    "public_contract",
    "data_migration",
    "security_or_permissions",
    "cross_service",
    "irreversible",
    "compliance",
)
MEASUREMENT_SCOPE = {
    "cycle_kind": "initial-specification",
    "starts_at": "approved_execution_start",
    "ends_at": "first_development_handoff",
    "includes": [
        "full_analysis",
        "reviews",
        "pre_handoff_rework",
        "post_publication_pre_handoff_rework",
    ],
    "excludes": [
        "preliminary_analysis_already_completed",
        "post_handoff_wait",
        "post_handoff_developer_feedback",
    ],
}


class TimingModelError(RuntimeError):
    """Invalid project model, training sample, or prediction request."""


def now_utc() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def canonical_fingerprint(payload: Any) -> str:
    material = (
        {key: value for key, value in payload.items() if key != "fingerprint"}
        if isinstance(payload, dict)
        else payload
    )
    encoded = json.dumps(
        material,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TimingModelError(f"Cannot read JSON {path}: {exc}") from exc


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def canonical_project_root(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TimingModelError("project_root is required for project-local timing history")
    return str(Path(value).expanduser().resolve())


def project_key(profile_id: str, project_root: str) -> str:
    if not isinstance(profile_id, str) or not profile_id.strip():
        raise TimingModelError("profile_id is required")
    material = {
        "profile_id": profile_id.strip(),
        "project_root": canonical_project_root(project_root),
    }
    return canonical_fingerprint(material)


def default_model_path(project_root: str) -> Path:
    return Path(canonical_project_root(project_root)) / DEFAULT_RELATIVE_PATH


def empty_model(profile_id: str, project_root: str) -> dict[str, Any]:
    return {
        "schema": SCHEMA_VERSION,
        "feature_schema": FEATURE_SCHEMA_VERSION,
        "profile_id": profile_id,
        "project_key": project_key(profile_id, project_root),
        "sample_count": 0,
        "samples": [],
        "updated_at": now_utc(),
    }


def validate_model(
    payload: Any,
    *,
    profile_id: str,
    project_root: str,
) -> None:
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA_VERSION:
        raise TimingModelError("timing model has unsupported schema")
    if payload.get("feature_schema") not in SUPPORTED_FEATURE_SCHEMA_VERSIONS:
        raise TimingModelError("timing model has unsupported feature schema")
    if payload.get("profile_id") != profile_id:
        raise TimingModelError("timing model belongs to another profile")
    if payload.get("project_key") != project_key(profile_id, project_root):
        raise TimingModelError("timing model belongs to another project root")
    samples = payload.get("samples")
    if not isinstance(samples, list) or payload.get("sample_count") != len(samples):
        raise TimingModelError("timing model sample count is invalid")
    seen: set[str] = set()
    for sample in samples:
        if not isinstance(sample, dict):
            raise TimingModelError("timing model sample must be an object")
        case_id = sample.get("case_id")
        if not isinstance(case_id, str) or not case_id.strip() or case_id in seen:
            raise TimingModelError("timing model case ids must be non-empty and unique")
        seen.add(case_id)
        if sample.get("quality") != "measured":
            raise TimingModelError("only measured samples may train the timing model")
        if not isinstance(sample.get("features"), dict):
            raise TimingModelError(f"{case_id}: features are missing")
        feature_schema = sample["features"].get("schema")
        if feature_schema not in SUPPORTED_FEATURE_SCHEMA_VERSIONS:
            raise TimingModelError(f"{case_id}: feature schema is unsupported")
        if feature_schema == FEATURE_SCHEMA_VERSION:
            for field in (
                "surface_signature",
                "component_signature",
                "risk_signature",
            ):
                value = sample["features"].get(field)
                if not isinstance(value, list) or any(
                    not isinstance(item, str) or not item.strip() for item in value
                ):
                    raise TimingModelError(f"{case_id}: {field} is invalid")
            if not isinstance(sample["features"].get("change_scope"), str):
                raise TimingModelError(f"{case_id}: change_scope is invalid")
        for field in ("active_seconds", "elapsed_seconds"):
            value = sample.get(field)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise TimingModelError(f"{case_id}: {field} is invalid")
        if sample["elapsed_seconds"] < sample["active_seconds"]:
            raise TimingModelError(f"{case_id}: elapsed time is below active time")
        calibration = sample.get("calibration")
        if not isinstance(calibration, dict) or calibration.get(
            "fingerprint"
        ) != canonical_fingerprint(calibration):
            raise TimingModelError(f"{case_id}: calibration record is invalid")


def load_model(path: Path, *, profile_id: str, project_root: str) -> dict[str, Any]:
    if not path.exists():
        return empty_model(profile_id, project_root)
    payload = read_json(path)
    validate_model(payload, profile_id=profile_id, project_root=project_root)
    # Schema-1 samples remain immutable and usable. The model advertises the
    # newest query schema after loading; mixed history is handled by distance.
    payload["feature_schema"] = FEATURE_SCHEMA_VERSION
    return payload


def build_features(
    mode_payload: Any,
    plan_payload: Any,
    *,
    schema_version: int = FEATURE_SCHEMA_VERSION,
) -> dict[str, Any]:
    """Derive similarity features only after preliminary analysis is materialized."""
    if schema_version not in SUPPORTED_FEATURE_SCHEMA_VERSIONS:
        raise TimingModelError("unsupported requested feature schema")
    try:
        validate_mode_decision(mode_payload)
    except ModeDecisionError as exc:
        raise TimingModelError(f"Invalid mode decision: {exc}") from exc
    if not isinstance(plan_payload, dict):
        raise TimingModelError("planning plan must be an object")
    stages = plan_payload.get("stages")
    if not isinstance(stages, list) or not stages:
        raise TimingModelError(
            "timing prediction requires a materialized preliminary plan with stages"
        )
    checklist_count = 0
    for stage in stages:
        if not isinstance(stage, dict):
            raise TimingModelError("planning stages must be objects")
        checklist = stage.get("checklist", [])
        if not isinstance(checklist, list):
            raise TimingModelError("planning stage checklist must be an array")
        checklist_count += len(checklist)
    facts = mode_payload["facts"]
    risk_facts = mode_payload.get("risk_facts", {})
    features: dict[str, Any] = {
        "schema": schema_version,
        "mode": mode_payload["selected_mode"],
        "assurance": mode_payload.get("selected_assurance", "high"),
        "estimated_blocks": facts["estimated_blocks"],
        "surface_count": len(facts["surfaces"]),
        "component_count": len(facts["components"]),
        "owner_count": len(facts["owners"]),
        "dependent_parts": facts["dependent_parts"],
        "risk_count": sum(risk_facts.get(field) is True for field in BOOLEAN_RISKS),
        "stage_count": len(stages),
        "checklist_count": checklist_count,
    }
    if schema_version == FEATURE_SCHEMA_VERSION:
        features.update(
            change_scope=str(risk_facts.get("change_scope", "unknown")),
            surface_signature=sorted(set(facts["surfaces"])),
            component_signature=sorted(set(facts["components"])),
            risk_signature=sorted(
                field for field in BOOLEAN_RISKS if risk_facts.get(field) is True
            ),
        )
    return features


def set_distance(left: Any, right: Any) -> float:
    """Return Jaccard distance for two categorical signatures."""
    left_set = set(left) if isinstance(left, list) else set()
    right_set = set(right) if isinstance(right, list) else set()
    union = left_set | right_set
    if not union:
        return 0.0
    return 1.0 - len(left_set & right_set) / len(union)


def feature_distance(left: dict[str, Any], right: dict[str, Any]) -> float:
    distance = 0.0
    if left["mode"] != right["mode"]:
        distance += 4.0
    if left["assurance"] != right["assurance"]:
        distance += 3.0
    if left["dependent_parts"] != right["dependent_parts"]:
        distance += 1.5
    weights = {
        "estimated_blocks": 3.0,
        "surface_count": 1.0,
        "component_count": 1.5,
        "owner_count": 1.0,
        "risk_count": 1.0,
        "stage_count": 3.0,
        "checklist_count": 4.0,
    }
    for field, weight in weights.items():
        left_value = int(left[field])
        right_value = int(right[field])
        scale = max(left_value, right_value, 1)
        distance += weight * abs(left_value - right_value) / scale
    if (
        left.get("schema") == FEATURE_SCHEMA_VERSION
        and right.get("schema") == FEATURE_SCHEMA_VERSION
    ):
        if left.get("change_scope") != right.get("change_scope"):
            distance += 3.5
        distance += 5.0 * set_distance(
            left.get("surface_signature"), right.get("surface_signature")
        )
        # Component names are project-local and useful, but deliberately weaker
        # than semantic surface types to avoid overfitting to one subsystem.
        distance += 2.0 * set_distance(
            left.get("component_signature"), right.get("component_signature")
        )
        distance += 3.0 * set_distance(
            left.get("risk_signature"), right.get("risk_signature")
        )
    elif left.get("schema") != right.get("schema"):
        # Old measurements are retained, but cannot masquerade as an exact
        # typed match when their categorical facts were never recorded.
        distance += 3.0
    return round(distance, 6)


def percentile(values: list[int], fraction: float) -> int:
    if not values:
        raise TimingModelError("cannot calculate an empty percentile")
    ordered = sorted(values)
    index = round((len(ordered) - 1) * fraction)
    return ordered[index]


def range_summary(values: list[int]) -> dict[str, int]:
    return {
        "optimistic_seconds": percentile(values, 0.2),
        "likely_seconds": int(statistics.median(values)),
        "pessimistic_seconds": percentile(values, 0.8),
    }


def confidence(sample_size: int, mean_distance: float) -> str:
    if sample_size >= 8 and mean_distance <= 2.5:
        return "high"
    if sample_size >= 3 and mean_distance <= 5.0:
        return "medium"
    return "low"


def format_duration(seconds: int) -> str:
    minutes = max(0, round(seconds / 60))
    hours, remaining = divmod(minutes, 60)
    if hours and remaining:
        return f"{hours} ч {remaining} мин"
    if hours:
        return f"{hours} ч"
    return f"{remaining} мин"


def human_note(prediction: dict[str, Any]) -> str:
    if prediction["status"] == "insufficient_data":
        return (
            "Оценка оставшегося времени Vigers до первой передачи в разработку: "
            "данных этого проекта пока недостаточно; прогноз появится после "
            "завершённых замеров."
        )
    active = prediction["active"]
    elapsed = prediction["elapsed"]
    return (
        "Оценка оставшегося времени Vigers после предварительного анализа "
        "до первой передачи в разработку: "
        f"чистая работа {format_duration(active['optimistic_seconds'])}–"
        f"{format_duration(active['pessimistic_seconds'])} "
        f"(ориентир {format_duration(active['likely_seconds'])}); "
        f"с паузами {format_duration(elapsed['optimistic_seconds'])}–"
        f"{format_duration(elapsed['pessimistic_seconds'])} "
        f"(ориентир {format_duration(elapsed['likely_seconds'])}). "
        f"Выборка: {prediction['sample_size']} похожих кейсов этого проекта, "
        f"уверенность: {prediction['confidence']}."
    )


def predict(model: dict[str, Any], features: dict[str, Any]) -> dict[str, Any]:
    ranked = sorted(
        (
            (feature_distance(features, sample["features"]), sample)
            for sample in model["samples"]
        ),
        key=lambda item: (item[0], item[1]["case_id"]),
    )[:MAX_NEIGHBORS]
    base: dict[str, Any] = {
        "schema": SCHEMA_VERSION,
        "purpose": "human_information_only",
        "measurement_scope": MEASUREMENT_SCOPE,
        "project_key": model["project_key"],
        "profile_id": model["profile_id"],
        "feature_schema": features["schema"],
        "feature_fingerprint": canonical_fingerprint(features),
        "sample_size": len(ranked),
        "matching_case_ids": [sample["case_id"] for _, sample in ranked],
        "matching_neighbors": [
            {
                "case_id": sample["case_id"],
                "distance": distance,
                "feature_schema": sample["features"]["schema"],
            }
            for distance, sample in ranked
        ],
    }
    if not ranked:
        base.update(
            status="insufficient_data",
            confidence="low",
            mean_distance=None,
            active=None,
            elapsed=None,
        )
    else:
        mean_distance = round(statistics.fmean(distance for distance, _ in ranked), 4)
        base.update(
            status="forecast",
            confidence=confidence(len(ranked), mean_distance),
            mean_distance=mean_distance,
            active=range_summary([sample["active_seconds"] for _, sample in ranked]),
            elapsed=range_summary([sample["elapsed_seconds"] for _, sample in ranked]),
        )
    base["human_note"] = human_note(base)
    base["fingerprint"] = canonical_fingerprint(base)
    return base


def resolve_forecast_features(
    mode_payload: Any,
    plan_payload: Any,
    forecast: Any,
) -> dict[str, Any]:
    """Bind new and legacy forecasts to the exact feature representation used."""
    if not isinstance(forecast, dict):
        raise TimingModelError("timing forecast must be an object")
    expected = forecast.get("feature_fingerprint")
    for schema_version in (FEATURE_SCHEMA_VERSION, 1):
        candidate = build_features(
            mode_payload,
            plan_payload,
            schema_version=schema_version,
        )
        if canonical_fingerprint(candidate) == expected:
            return candidate
    raise TimingModelError("timing forecast belongs to another preliminary analysis")


def measured_sample(
    *,
    ledger_path: Path,
    features: dict[str, Any],
    forecast: dict[str, Any],
    activity_reconciliation: Any | None = None,
) -> dict[str, Any]:
    try:
        _, ledger = load_ledger(ledger_path)
        summary = summarize(ledger)
    except AutomationTimingError as exc:
        raise TimingModelError(str(exc)) from exc
    if summary.get("timer_model") != "dual" or not summary.get("complete"):
        raise TimingModelError("training requires a complete measured dual-timer ledger")
    handoff = next(
        (
            item
            for item in summary.get("milestones", [])
            if isinstance(item, dict) and item.get("kind") == "development_handoff"
        ),
        None,
    )
    if handoff is None:
        raise TimingModelError("training requires an explicit development handoff")
    active = summary["actual"].get("active_critical_path_seconds")
    elapsed = summary["actual"].get("elapsed_seconds")
    if not isinstance(active, int) or not isinstance(elapsed, int):
        raise TimingModelError("completed ledger has no active/elapsed timing facts")
    measurement = {
        "source": "automation_timing",
        "activity_reconciliation_fingerprint": None,
        "coverage": "explicit",
        "cycle_kind": "initial-specification",
    }
    if activity_reconciliation is not None:
        reconciled = validate_activity_reconciliation(
            activity_reconciliation,
            case_id=summary["case_id"],
            project_key=forecast.get("project_key"),
            development_handoff_at=handoff["at"],
        )
        active = reconciled["active_seconds"]
        elapsed = reconciled["elapsed_seconds"]
        measurement = {
            "source": "work_metrics_activity_reconciliation",
            "activity_reconciliation_fingerprint": activity_reconciliation["fingerprint"],
            "coverage": activity_reconciliation["coverage"]["status"],
            "cycle_kind": "initial-specification",
        }
    if elapsed < active:
        raise TimingModelError("completed ledger elapsed time is below active time")
    calibration = build_calibration(
        case_id=summary["case_id"],
        forecast=forecast,
        features=features,
        active_seconds=active,
        elapsed_seconds=elapsed,
        milestones=summary.get("milestones", []),
        measurement=measurement,
    )
    material = {
        "case_id": summary["case_id"],
        "features": features,
        "active_seconds": active,
        "elapsed_seconds": elapsed,
        "quality": "measured",
        "cycle_kind": "initial-specification",
        "calibration": calibration,
    }
    return {
        **material,
        "source_fingerprint": canonical_fingerprint(material),
        "recorded_at": now_utc(),
    }


def compare_forecast_axis(axis: Any, actual_seconds: int) -> dict[str, Any]:
    if not isinstance(axis, dict):
        return {
            "status": "no_baseline",
            "actual_seconds": actual_seconds,
            "likely_delta_seconds": None,
            "likely_ratio": None,
            "within_range": None,
        }
    likely = axis.get("likely_seconds")
    optimistic = axis.get("optimistic_seconds")
    pessimistic = axis.get("pessimistic_seconds")
    if not all(isinstance(value, int) for value in (optimistic, likely, pessimistic)):
        raise TimingModelError("forecast range is invalid")
    return {
        "status": "compared",
        "actual_seconds": actual_seconds,
        "forecast_optimistic_seconds": optimistic,
        "forecast_likely_seconds": likely,
        "forecast_pessimistic_seconds": pessimistic,
        "likely_delta_seconds": actual_seconds - likely,
        "likely_ratio": round(actual_seconds / likely, 4) if likely > 0 else None,
        "within_range": optimistic <= actual_seconds <= pessimistic,
    }


def validate_activity_reconciliation(
    payload: Any,
    *,
    case_id: str,
    project_key: Any,
    development_handoff_at: Any,
) -> dict[str, int]:
    """Validate the optional companion contract without importing its package."""
    if not isinstance(payload, dict) or payload.get("schema") != 1:
        raise TimingModelError("activity reconciliation has unsupported schema")
    if payload.get("fingerprint") != canonical_fingerprint(payload):
        raise TimingModelError("activity reconciliation fingerprint mismatch")
    work_item = payload.get("work_item")
    if not isinstance(work_item, dict) or work_item.get("id") != case_id:
        raise TimingModelError("activity reconciliation belongs to another case")
    if not isinstance(project_key, str) or work_item.get("project_key") != project_key:
        raise TimingModelError("activity reconciliation belongs to another project")
    if work_item.get("cycle_kind", "initial-specification") != "initial-specification":
        raise TimingModelError(
            "post-handoff follow-up cannot train the initial specification model"
        )
    coverage = payload.get("coverage")
    if not isinstance(coverage, dict) or coverage.get("status") != "complete":
        raise TimingModelError("activity reconciliation coverage is not complete")
    window = payload.get("window")
    if not isinstance(window, dict) or window.get("terminal") is not True:
        raise TimingModelError("activity reconciliation window is not terminal")
    try:
        reconciled_value = datetime.fromisoformat(
            str(window.get("ended_at", "")).replace("Z", "+00:00")
        )
        handoff_value = datetime.fromisoformat(
            str(development_handoff_at).replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise TimingModelError("activity reconciliation boundary is invalid") from exc
    if reconciled_value.tzinfo is None or handoff_value.tzinfo is None:
        raise TimingModelError("activity reconciliation boundary requires timezone")
    reconciled_end = reconciled_value.astimezone(UTC)
    handoff_end = handoff_value.astimezone(UTC)
    if reconciled_end != handoff_end:
        raise TimingModelError(
            "activity reconciliation must end at the first development handoff"
        )
    if payload.get("training_eligible") is not True:
        raise TimingModelError("activity reconciliation is not training eligible")
    metrics = payload.get("metric_results")
    if not isinstance(metrics, list):
        raise TimingModelError("activity reconciliation has no metric results")
    matching = [
        item
        for item in metrics
        if isinstance(item, dict) and item.get("provider") == "activity-time"
    ]
    if len(matching) != 1 or not isinstance(matching[0].get("values"), dict):
        raise TimingModelError("activity reconciliation requires one activity-time metric")
    values = matching[0]["values"]
    result: dict[str, int] = {}
    for field in ("active_observed_seconds", "active_seconds", "elapsed_seconds"):
        value = values.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise TimingModelError(f"activity reconciliation {field} is invalid")
        result[field] = value
    if result["active_observed_seconds"] > result["active_seconds"]:
        raise TimingModelError("observed activity exceeds reconciled active time")
    if result["active_seconds"] > result["elapsed_seconds"]:
        raise TimingModelError("reconciled active time exceeds elapsed time")
    return result


def build_calibration(
    *,
    case_id: str,
    forecast: Any,
    features: dict[str, Any],
    active_seconds: int,
    elapsed_seconds: int,
    milestones: list[dict[str, Any]],
    measurement: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(forecast, dict) or forecast.get("fingerprint") != canonical_fingerprint(
        forecast
    ):
        raise TimingModelError("timing forecast fingerprint mismatch")
    if forecast.get("purpose") != "human_information_only":
        raise TimingModelError("timing forecast purpose is invalid")
    if forecast.get("feature_fingerprint") != canonical_fingerprint(features):
        raise TimingModelError("timing forecast belongs to another preliminary analysis")
    forecast_scope = forecast.get("measurement_scope", MEASUREMENT_SCOPE)
    if forecast_scope != MEASUREMENT_SCOPE:
        raise TimingModelError("timing forecast measurement scope is invalid")
    handoff = next(item for item in milestones if item.get("kind") == "development_handoff")
    record: dict[str, Any] = {
        "schema": SCHEMA_VERSION,
        "case_id": case_id,
        "forecast_fingerprint": forecast["fingerprint"],
        "forecast_status": forecast.get("status"),
        "feature_fingerprint": forecast["feature_fingerprint"],
        "feature_schema": features["schema"],
        "measurement_scope": forecast_scope,
        "publication_count": sum(item.get("kind") == "publication" for item in milestones),
        "development_handoff_at": handoff["at"],
        "measurement": measurement
        or {
            "source": "automation_timing",
            "activity_reconciliation_fingerprint": None,
            "coverage": "explicit",
            "cycle_kind": "initial-specification",
        },
        "active": compare_forecast_axis(forecast.get("active"), active_seconds),
        "elapsed": compare_forecast_axis(forecast.get("elapsed"), elapsed_seconds),
    }
    record["fingerprint"] = canonical_fingerprint(record)
    return record


def update_model(
    model: dict[str, Any],
    sample: dict[str, Any],
    *,
    replace: bool = False,
) -> bool:
    existing = next(
        (item for item in model["samples"] if item["case_id"] == sample["case_id"]),
        None,
    )
    if existing is not None:
        if existing["source_fingerprint"] == sample["source_fingerprint"]:
            return False
        if not replace:
            raise TimingModelError(
                f"case {sample['case_id']} already exists with different facts; use --replace"
            )
        model["samples"].remove(existing)
    model["samples"].append(sample)
    model["samples"].sort(key=lambda item: item["case_id"])
    model["sample_count"] = len(model["samples"])
    model["feature_schema"] = FEATURE_SCHEMA_VERSION
    model["updated_at"] = now_utc()
    return True


def recover_candidate(agent_ledger_path: Path) -> dict[str, Any]:
    """Recover a lower-bound candidate from run logs without training on it."""
    payload = read_json(agent_ledger_path)
    if not isinstance(payload, dict) or not isinstance(payload.get("runs"), list):
        raise TimingModelError("agent ledger is invalid")
    runs = payload["runs"]
    if not runs:
        raise TimingModelError("agent ledger has no runs")
    active = 0.0
    starts: list[datetime] = []
    finishes: list[datetime] = []
    for run in runs:
        if not isinstance(run, dict) or not isinstance(run.get("duration_seconds"), (int, float)):
            raise TimingModelError("agent ledger run duration is invalid")
        try:
            finished = datetime.fromisoformat(run["at"]).astimezone(UTC)
        except (KeyError, TypeError, ValueError) as exc:
            raise TimingModelError("agent ledger run timestamp is invalid") from exc
        duration = float(run["duration_seconds"])
        active += duration
        finishes.append(finished)
        starts.append(finished - timedelta(seconds=duration))
    return {
        "schema": SCHEMA_VERSION,
        "case_id": payload.get("case_id"),
        "quality": "recovered_lower_bound",
        "active_lower_bound_seconds": round(active),
        "elapsed_lower_bound_seconds": round((max(finishes) - min(starts)).total_seconds()),
        "training_eligible": False,
        "coverage": "partial",
        "reason": "run logs do not prove user pauses, limit waits, or full case boundaries",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("predict", "update"):
        child = subparsers.add_parser(name)
        child.add_argument("--profile-id", required=True)
        child.add_argument("--project-root", required=True)
        child.add_argument("--model")
        child.add_argument("--mode-decision", required=True)
        child.add_argument("--plan", required=True)
        if name == "predict":
            child.add_argument("--write")
        if name == "update":
            child.add_argument("--ledger", required=True)
            child.add_argument("--forecast", required=True)
            child.add_argument("--activity-reconciliation")
            child.add_argument("--calibration-record")
            child.add_argument("--replace", action="store_true")
    recover = subparsers.add_parser("recover", help="Recover non-training lower bounds from logs")
    recover.add_argument("--agent-ledger", required=True)
    recover.add_argument("--write")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "recover":
            result = recover_candidate(Path(args.agent_ledger))
            if args.write:
                atomic_json(Path(args.write), result)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        model_path = (
            Path(args.model).expanduser().resolve()
            if args.model
            else default_model_path(args.project_root)
        )
        model = load_model(
            model_path,
            profile_id=args.profile_id,
            project_root=args.project_root,
        )
        mode_payload = read_json(Path(args.mode_decision))
        profile = mode_payload.get("profile") if isinstance(mode_payload, dict) else None
        if not isinstance(profile, dict) or profile.get("id") != args.profile_id:
            raise TimingModelError("mode decision belongs to another profile")
        if canonical_project_root(profile.get("project_root")) != canonical_project_root(
            args.project_root
        ):
            raise TimingModelError("mode decision belongs to another project root")
        plan_payload = read_json(Path(args.plan))
        if args.command == "predict":
            features = build_features(mode_payload, plan_payload)
            result = predict(model, features)
            if args.write:
                atomic_json(Path(args.write), result)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        forecast = read_json(Path(args.forecast))
        features = resolve_forecast_features(mode_payload, plan_payload, forecast)
        sample = measured_sample(
            ledger_path=Path(args.ledger),
            features=features,
            forecast=forecast,
            activity_reconciliation=(
                read_json(Path(args.activity_reconciliation))
                if args.activity_reconciliation
                else None
            ),
        )
        changed = update_model(model, sample, replace=args.replace)
        calibration_path = (
            Path(args.calibration_record).expanduser().resolve()
            if args.calibration_record
            else Path(args.ledger).expanduser().resolve().parent / CALIBRATION_FILENAME
        )
        if calibration_path.exists():
            existing_calibration = read_json(calibration_path)
            if existing_calibration != sample["calibration"]:
                raise TimingModelError(
                    "calibration record already exists with different facts"
                )
        if changed:
            validate_model(model, profile_id=args.profile_id, project_root=args.project_root)
            atomic_json(model_path, model)
        if not calibration_path.exists():
            atomic_json(calibration_path, sample["calibration"])
        print(f"PASS model={model_path} samples={model['sample_count']} changed={str(changed).lower()}")
        return 0
    except (OSError, TimingModelError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
