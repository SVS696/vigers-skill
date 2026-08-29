#!/usr/bin/env python3
"""Project-local, shadow-only policy learning for Vigers orchestration."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import case_pipeline
from mode_decision import ModeDecisionError, validate_mode_decision


MODEL_SCHEMA_VERSION = 2
FEATURE_SCHEMA_VERSION = 1
FEEDBACK_SCHEMA_VERSION = 1
SHADOW_SCHEMA_VERSION = 1
DEFAULT_RELATIVE_PATH = Path(".vigers/telemetry/policy-model.json")
MIN_SHADOW_COHORT = 3
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SAMPLE_ORIGINS = {"historical-biased", "prospective-clean", "frozen-replay"}
TRAINING_ORIGINS = {"prospective-clean", "frozen-replay"}
PROCESS_AUDIT_DEEP_SIGNALS = {
    "manual_stop",
    "guard_stop",
    "excessive_reviews",
    "remediation_limit",
    "human_rework",
    "quality_regression",
    "scope_drift",
}
PROCESS_AUDIT_OUTCOMES = {
    "completed",
    "blocked",
    "user_stopped",
    "guard_stopped",
    "cancelled",
    "external_failure",
}
PROCESS_AUDIT_SIGNALS = PROCESS_AUDIT_DEEP_SIGNALS | {
    "limit_exhausted",
    "external_error",
}
PROCESS_AUDIT_CLASSIFICATIONS = {
    "KEEP",
    "EXECUTION_DEFECT",
    "PROCESS_DEFECT",
    "EXTERNAL_FAILURE",
    "EVIDENCE_GAP",
    "MANUAL_STOP_VALIDATED",
    "MANUAL_STOP_UNCONFIRMED",
}
PROCESS_AUDIT_SEVERITIES = {"none", "minor", "major", "blocker"}
PROCESS_AUDIT_MANUAL_ASSESSMENTS = {"not_applicable", "validated", "unconfirmed"}
PROCESS_AUDIT_ACTIONS = {
    "no_change",
    "repair_result",
    "propose_policy_change",
    "investigate",
}
PROCESS_AUDIT_CLASSIFICATION_ACTIONS = {
    "KEEP": {"no_change"},
    "EXECUTION_DEFECT": {"repair_result", "investigate", "no_change"},
    "PROCESS_DEFECT": {"propose_policy_change", "investigate"},
    "EXTERNAL_FAILURE": {"no_change", "investigate"},
    "EVIDENCE_GAP": {"investigate"},
    "MANUAL_STOP_VALIDATED": {
        "propose_policy_change",
        "repair_result",
        "investigate",
    },
    "MANUAL_STOP_UNCONFIRMED": {"no_change", "investigate"},
}
PROCESS_AUDIT_PATTERN_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,127}$")
RISK_FIELDS = (
    "public_contract",
    "data_migration",
    "security_or_permissions",
    "cross_service",
    "irreversible",
    "compliance",
)


class PolicyLearningError(RuntimeError):
    """Invalid policy history, feedback, case observation, or shadow query."""


def now_utc() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def canonical_fingerprint(
    payload: Any,
    *,
    ignored: set[str] | None = None,
) -> str:
    ignored_fields = {"fingerprint"} | (ignored or set())
    material = (
        {key: value for key, value in payload.items() if key not in ignored_fields}
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
        raise PolicyLearningError(f"Cannot read JSON {path}: {exc}") from exc


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def bind_evidence_file(path: Path) -> dict[str, str]:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise PolicyLearningError(f"policy feedback evidence file is missing: {resolved}")
    return {"ref": str(resolved), "sha256": sha256_file(resolved)}


def canonical_project_root(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PolicyLearningError("project_root is required for project-local policy history")
    return str(Path(value).expanduser().resolve())


def project_key(profile_id: str, project_root: str) -> str:
    if not isinstance(profile_id, str) or not profile_id.strip():
        raise PolicyLearningError("profile_id is required")
    return canonical_fingerprint(
        {
            "profile_id": profile_id.strip(),
            "project_root": canonical_project_root(project_root),
        }
    )


def default_model_path(project_root: str) -> Path:
    return Path(canonical_project_root(project_root)) / DEFAULT_RELATIVE_PATH


def empty_model(profile_id: str, project_root: str) -> dict[str, Any]:
    return {
        "schema": MODEL_SCHEMA_VERSION,
        "feature_schema": FEATURE_SCHEMA_VERSION,
        "profile_id": profile_id,
        "project_key": project_key(profile_id, project_root),
        "sample_count": 0,
        "samples": [],
        "updated_at": now_utc(),
    }


def non_negative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def validate_feedback(payload: Any, *, case_id: str | None = None) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, dict) or payload.get("schema") != FEEDBACK_SCHEMA_VERSION:
        return ["policy feedback has unsupported schema"]
    if not isinstance(payload.get("case_id"), str) or not payload["case_id"].strip():
        errors.append("policy feedback requires case_id")
    elif case_id is not None and payload["case_id"] != case_id:
        errors.append("policy feedback belongs to another case")
    if payload.get("coverage") not in {"complete", "partial"}:
        errors.append("policy feedback coverage must be complete or partial")
    if not isinstance(payload.get("window_closed"), bool):
        errors.append("policy feedback window_closed must be boolean")
    observed = payload.get("observed")
    if not isinstance(observed, dict):
        errors.append("policy feedback observed must be an object")
    else:
        for field in ("human_rework_count", "developer_clarification_count"):
            if not non_negative_int(observed.get(field)):
                errors.append(f"policy feedback {field} must be non-negative")
        defects = observed.get("specification_defects")
        if not isinstance(defects, dict):
            errors.append("policy feedback specification_defects must be an object")
        else:
            for severity in ("blocker", "major", "minor"):
                if not non_negative_int(defects.get(severity)):
                    errors.append(
                        f"policy feedback specification_defects.{severity} must be non-negative"
                    )
    evidence_refs = payload.get("evidence_refs")
    if not isinstance(evidence_refs, list):
        errors.append("policy feedback evidence_refs must be an array")
    else:
        seen_refs: set[str] = set()
        for index, binding in enumerate(evidence_refs, start=1):
            label = f"policy feedback evidence_refs[{index}]"
            if not isinstance(binding, dict):
                errors.append(f"{label} must be an object")
                continue
            reference = binding.get("ref")
            if not isinstance(reference, str) or not reference.strip():
                errors.append(f"{label}.ref must be a non-empty string")
            elif reference in seen_refs:
                errors.append("policy feedback evidence_refs must be unique")
            else:
                seen_refs.add(reference)
            if not isinstance(binding.get("sha256"), str) or not SHA256_RE.fullmatch(
                binding["sha256"]
            ):
                errors.append(f"{label}.sha256 is invalid")
    if (
        payload.get("coverage") == "complete"
        and payload.get("window_closed") is True
        and not evidence_refs
    ):
        errors.append("complete closed policy feedback requires evidence_refs")
    stored = payload.get("fingerprint")
    if not isinstance(stored, str) or stored != canonical_fingerprint(
        payload,
        ignored={"recorded_at"},
    ):
        errors.append("policy feedback fingerprint mismatch")
    return errors


def feedback_evidence_errors(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for binding in payload.get("evidence_refs", []):
        if not isinstance(binding, dict):
            continue
        reference = binding.get("ref")
        expected = binding.get("sha256")
        if not isinstance(reference, str) or not isinstance(expected, str):
            continue
        path = Path(reference).expanduser().resolve()
        if not path.is_file():
            errors.append(f"policy feedback evidence is missing: {reference}")
        elif sha256_file(path) != expected:
            errors.append(f"policy feedback evidence changed after binding: {reference}")
    return errors


def build_feedback(
    *,
    case_id: str,
    coverage: str,
    window_closed: bool,
    human_rework_count: int,
    developer_clarification_count: int,
    blocker_defects: int,
    major_defects: int,
    minor_defects: int,
    evidence_refs: list[dict[str, str]],
) -> dict[str, Any]:
    payload = {
        "schema": FEEDBACK_SCHEMA_VERSION,
        "case_id": case_id.strip(),
        "coverage": coverage,
        "window_closed": window_closed,
        "observed": {
            "human_rework_count": human_rework_count,
            "developer_clarification_count": developer_clarification_count,
            "specification_defects": {
                "blocker": blocker_defects,
                "major": major_defects,
                "minor": minor_defects,
            },
        },
        "evidence_refs": sorted(evidence_refs, key=lambda item: item.get("ref", "")),
        "recorded_at": now_utc(),
    }
    payload["fingerprint"] = canonical_fingerprint(
        payload,
        ignored={"recorded_at"},
    )
    errors = validate_feedback(payload)
    if errors:
        raise PolicyLearningError("Invalid policy feedback: " + "; ".join(errors))
    return payload


def feedback_summary(payload: dict[str, Any] | None) -> dict[str, Any]:
    if payload is None:
        return {
            "available": False,
            "promotion_evidence_eligible": False,
            "coverage": "missing",
        }
    observed = payload["observed"]
    defects = observed["specification_defects"]
    return {
        "available": True,
        "promotion_evidence_eligible": (
            payload["coverage"] == "complete" and payload["window_closed"] is True
        ),
        "coverage": payload["coverage"],
        "window_closed": payload["window_closed"],
        "human_rework_count": observed["human_rework_count"],
        "developer_clarification_count": observed["developer_clarification_count"],
        "specification_defects": defects,
        "evidence_refs": payload["evidence_refs"],
        "feedback_fingerprint": payload["fingerprint"],
    }


def process_audit_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def process_audit_root_key(project_root: str) -> str:
    root = canonical_project_root(project_root)
    return hashlib.sha256(root.encode("utf-8")).hexdigest()


def process_audit_required_depth(outcome: Any, signals: list[str]) -> str:
    if outcome in {"user_stopped", "guard_stopped"} or (
        PROCESS_AUDIT_DEEP_SIGNALS.intersection(signals)
    ):
        return "deep"
    return "routine"


def validate_process_audit_pair(
    episode: Any,
    verdict: Any,
    *,
    verify_evidence: bool = True,
) -> list[str]:
    errors: list[str] = []
    if not isinstance(episode, dict):
        return ["process audit episode must be an object"]
    if episode.get("schema") != 1:
        errors.append("process audit episode has unsupported schema")
    episode_required = {
        "episode_id",
        "work_item_id",
        "parent_episode_id",
        "project_root",
        "project_key",
        "workflow",
        "outcome",
        "origin",
        "author_run_id",
        "skill_chain",
        "evidence_refs",
        "signals",
        "required_depth",
        "window",
        "manual_stop",
        "recorded_at",
        "fingerprint",
    }
    for field in sorted(episode_required - set(episode)):
        errors.append(f"process audit episode missing required field: {field}")
    for field in (
        "episode_id",
        "work_item_id",
        "project_root",
        "workflow",
        "author_run_id",
    ):
        if not isinstance(episode.get(field), str) or not episode[field].strip():
            errors.append(f"process audit episode {field} must be non-empty")
    audit_root = episode.get("project_root")
    if isinstance(audit_root, str) and audit_root.strip():
        canonical_root = canonical_project_root(audit_root)
        if audit_root != canonical_root:
            errors.append("process audit project_root must be canonical")
        if episode.get("project_key") != process_audit_root_key(canonical_root):
            errors.append("process audit project_key does not match project_root")
    if episode.get("origin") not in SAMPLE_ORIGINS:
        errors.append("process audit origin is invalid")
    outcome = episode.get("outcome")
    if outcome not in PROCESS_AUDIT_OUTCOMES:
        errors.append("process audit outcome is invalid")
    parent = episode.get("parent_episode_id")
    if parent is not None and (not isinstance(parent, str) or not parent.strip()):
        errors.append("process audit parent_episode_id must be null or non-empty")
    skills = episode.get("skill_chain")
    if not isinstance(skills, list) or not skills:
        errors.append("process audit skill_chain must be non-empty")
    else:
        names: set[str] = set()
        for item in skills:
            if not isinstance(item, dict):
                errors.append("process audit skill_chain entries must be objects")
                continue
            name, version = item.get("name"), item.get("version")
            if not isinstance(name, str) or not name.strip():
                errors.append("process audit skill name must be non-empty")
            elif name in names:
                errors.append(f"process audit duplicate skill name: {name}")
            else:
                names.add(name)
            if not isinstance(version, str) or not version.strip():
                errors.append("process audit skill version must be non-empty")
    evidence_refs = episode.get("evidence_refs")
    evidence_hashes: set[str] = set()
    evidence_by_ref: dict[str, str] = {}
    if not isinstance(evidence_refs, list) or not evidence_refs:
        errors.append("process audit episode requires evidence_refs")
    else:
        seen_refs: set[str] = set()
        for binding in evidence_refs:
            if not isinstance(binding, dict):
                errors.append("process audit evidence binding must be an object")
                continue
            reference, expected = binding.get("ref"), binding.get("sha256")
            if not isinstance(reference, str) or not reference:
                errors.append("process audit evidence ref must be non-empty")
                continue
            if reference in seen_refs:
                errors.append(f"process audit duplicate evidence ref: {reference}")
            seen_refs.add(reference)
            if not isinstance(expected, str) or not SHA256_RE.fullmatch(expected):
                errors.append(f"process audit evidence sha256 is invalid: {reference}")
                continue
            evidence_hashes.add(expected)
            evidence_by_ref[reference] = expected
            if verify_evidence:
                evidence_file = Path(reference).expanduser().resolve()
                if not evidence_file.is_file():
                    errors.append(f"process audit evidence is missing: {reference}")
                elif sha256_file(evidence_file) != expected:
                    errors.append(
                        f"process audit evidence changed after binding: {reference}"
                    )
    signals = episode.get("signals")
    if not isinstance(signals, list) or any(
        signal not in PROCESS_AUDIT_SIGNALS for signal in signals
    ):
        errors.append("process audit signals are invalid")
        signals = []
    elif signals != sorted(set(signals)):
        errors.append("process audit signals must be unique and sorted")
    actual_depth = episode.get("required_depth")
    if actual_depth not in {"routine", "deep"}:
        errors.append("process audit required_depth is invalid")
    elif process_audit_required_depth(outcome, signals) == "deep" and actual_depth != "deep":
        errors.append("process audit required_depth is weaker than outcome/signals")
    window = episode.get("window")
    if not isinstance(window, dict):
        errors.append("process audit window must be an object")
    else:
        started_raw, ended_raw = window.get("started_at"), window.get("ended_at")
        started = process_audit_iso(started_raw) if started_raw is not None else None
        ended = process_audit_iso(ended_raw) if ended_raw is not None else None
        if started_raw is not None and started is None:
            errors.append("process audit started_at must be timezone-aware ISO-8601")
        if ended_raw is not None and ended is None:
            errors.append("process audit ended_at must be timezone-aware ISO-8601")
        if started is not None and ended is not None and ended < started:
            errors.append("process audit ended_at precedes started_at")
    manual_stop = episode.get("manual_stop")
    if outcome == "user_stopped":
        if not isinstance(manual_stop, dict):
            errors.append("process audit user_stopped requires manual_stop")
        else:
            if manual_stop.get("authority") != "user":
                errors.append("process audit manual_stop authority must be user")
            if manual_stop.get("resume_authority") != "user_only":
                errors.append("process audit manual_stop resume_authority must be user_only")
            if process_audit_iso(manual_stop.get("at")) is None:
                errors.append("process audit manual_stop.at must be timezone-aware ISO-8601")
            if manual_stop.get("reason_status") not in {"provided", "unknown"}:
                errors.append("process audit manual_stop reason_status is invalid")
    elif manual_stop is not None:
        errors.append("process audit manual_stop is allowed only for user_stopped")
    review_scope = episode.get("review_scope")
    selected_fingerprints: list[str] = []
    if review_scope is not None:
        if not isinstance(review_scope, dict):
            errors.append("process audit review_scope must be an object")
            review_scope = {}
        if review_scope.get("mode") != "targeted_remediation":
            errors.append("process audit review_scope mode is invalid")
        if review_scope.get("new_findings_policy") != "backlog_only":
            errors.append("process audit targeted remediation must be backlog_only")
        if review_scope.get("max_rechecks") != 1:
            errors.append("process audit targeted remediation max_rechecks must be one")
        if review_scope.get("automatic_followup") is not False:
            errors.append("process audit targeted remediation cannot auto-follow-up")
        if outcome != "completed" or signals != [] or actual_depth != "routine":
            errors.append("process audit targeted remediation boundary is invalid")
        selected = review_scope.get("selected_findings")
        if not isinstance(selected, list) or not selected:
            errors.append("process audit targeted remediation requires selected findings")
            selected = []
        indices: list[int] = []
        for item in selected:
            if not isinstance(item, dict):
                errors.append("process audit selected finding must be an object")
                continue
            index = item.get("index")
            selected_fingerprint = item.get("fingerprint")
            if not isinstance(index, int) or isinstance(index, bool) or index < 1:
                errors.append("process audit selected finding index is invalid")
            else:
                indices.append(index)
            if (
                not isinstance(selected_fingerprint, str)
                or not SHA256_RE.fullmatch(selected_fingerprint)
            ):
                errors.append("process audit selected finding fingerprint is invalid")
            else:
                selected_fingerprints.append(selected_fingerprint)
        if indices != sorted(set(indices)) or len(selected_fingerprints) != len(
            set(selected_fingerprints)
        ):
            errors.append("process audit selected findings must be sorted and unique")
        source_paths: dict[str, Path] = {}
        for kind in ("episode", "verdict"):
            reference = review_scope.get(f"source_{kind}_ref")
            expected = review_scope.get(f"source_{kind}_sha256")
            if not isinstance(reference, str) or not isinstance(expected, str):
                errors.append(f"process audit source {kind} binding is invalid")
                continue
            resolved = Path(reference).expanduser().resolve()
            if reference != str(resolved) or evidence_by_ref.get(reference) != expected:
                errors.append(f"process audit source {kind} is not evidence-bound")
                continue
            source_paths[kind] = resolved
        if verify_evidence and set(source_paths) == {"episode", "verdict"}:
            source_episode = read_json(source_paths["episode"])
            source_verdict = read_json(source_paths["verdict"])
            if isinstance(source_episode, dict) and source_episode.get("review_scope") is not None:
                errors.append("process audit targeted remediation cannot chain")
            else:
                errors.extend(
                    f"process audit source pair: {error}"
                    for error in validate_process_audit_pair(
                        source_episode, source_verdict, verify_evidence=False
                    )
                )
                if isinstance(source_episode, dict) and isinstance(source_verdict, dict):
                    if episode.get("parent_episode_id") != source_episode.get("episode_id"):
                        errors.append("process audit targeted parent is invalid")
                    for field in ("work_item_id", "project_root", "project_key", "workflow"):
                        if episode.get(field) != source_episode.get(field):
                            errors.append(f"process audit targeted {field} does not match source")
                    if review_scope.get("source_episode_id") != source_episode.get(
                        "episode_id"
                    ) or review_scope.get("source_verdict_fingerprint") != source_verdict.get(
                        "fingerprint"
                    ):
                        errors.append("process audit targeted source identity is invalid")
                    source_findings = source_verdict.get("findings")
                    if isinstance(source_findings, list):
                        for item in selected:
                            if not isinstance(item, dict) or not isinstance(
                                item.get("index"), int
                            ):
                                continue
                            index = item["index"]
                            if index < 1 or index > len(source_findings):
                                errors.append("process audit selected finding is outside source")
                                continue
                            source_finding = source_findings[index - 1]
                            if not isinstance(source_finding, dict) or item.get(
                                "fingerprint"
                            ) != canonical_fingerprint(source_finding):
                                errors.append("process audit selected finding binding is stale")
    episode_recorded = process_audit_iso(episode.get("recorded_at"))
    if episode_recorded is None:
        errors.append("process audit episode recorded_at must be timezone-aware ISO-8601")
    episode_fingerprint = episode.get("fingerprint")
    if not isinstance(episode_fingerprint, str) or not SHA256_RE.fullmatch(
        episode_fingerprint
    ) or episode_fingerprint != canonical_fingerprint(episode):
        errors.append("process audit episode fingerprint is invalid")

    if not isinstance(verdict, dict):
        return errors + ["process audit verdict must be an object"]
    if verdict.get("schema") != 2:
        errors.append("process audit verdict has unsupported schema")
    verdict_required = {
        "episode_id",
        "episode_fingerprint",
        "evaluator",
        "classification",
        "severity",
        "summary",
        "process_pattern_id",
        "findings",
        "actions",
        "manual_stop_assessment",
        "no_auto_resume",
        "auto_apply",
        "recorded_at",
        "fingerprint",
    }
    for field in sorted(verdict_required - set(verdict)):
        errors.append(f"process audit verdict missing required field: {field}")
    if verdict.get("episode_id") != episode.get("episode_id"):
        errors.append("process audit verdict episode_id mismatch")
    if verdict.get("episode_fingerprint") != episode_fingerprint:
        errors.append("process audit verdict binding is stale")
    evaluator = verdict.get("evaluator")
    if not isinstance(evaluator, dict):
        errors.append("process audit evaluator must be an object")
    else:
        run_id = evaluator.get("run_id")
        if not isinstance(run_id, str) or not run_id.strip():
            errors.append("process audit evaluator.run_id must be non-empty")
        elif run_id == episode.get("author_run_id"):
            errors.append("process audit evaluator matches the author")
        if not isinstance(evaluator.get("model"), str) or not evaluator["model"].strip():
            errors.append("process audit evaluator.model must be non-empty")
        if evaluator.get("independent") is not True:
            errors.append("process audit verdict is not independent")
        if evaluator.get("context_policy") != "evidence-only":
            errors.append("process audit verdict did not use evidence-only context")
        if evaluator.get("review_depth") != actual_depth:
            errors.append("process audit review_depth does not match episode")
    classification = verdict.get("classification")
    if classification not in PROCESS_AUDIT_CLASSIFICATIONS:
        errors.append("process audit classification is invalid")
    if outcome == "user_stopped" and classification not in {
        "MANUAL_STOP_VALIDATED",
        "MANUAL_STOP_UNCONFIRMED",
    }:
        errors.append("process audit user_stopped requires manual classification")
    elif classification == "KEEP" and outcome != "completed":
        errors.append("process audit KEEP requires completed outcome")
    severity = verdict.get("severity")
    if severity not in PROCESS_AUDIT_SEVERITIES:
        errors.append("process audit severity is invalid")
    if not isinstance(verdict.get("summary"), str) or not verdict["summary"].strip():
        errors.append("process audit summary must be non-empty")
    pattern = verdict.get("process_pattern_id")
    if pattern is not None and (
        not isinstance(pattern, str) or not PROCESS_AUDIT_PATTERN_RE.fullmatch(pattern)
    ):
        errors.append("process audit process_pattern_id is invalid")
    if classification == "PROCESS_DEFECT" and pattern is None:
        errors.append("process audit PROCESS_DEFECT requires process_pattern_id")
    protected_none = {
        "KEEP",
        "EXTERNAL_FAILURE",
        "EVIDENCE_GAP",
        "MANUAL_STOP_UNCONFIRMED",
    }
    if classification in protected_none and severity == "blocker":
        errors.append(f"process audit {classification} cannot claim blocker")
    if classification == "KEEP" and severity != "none":
        errors.append("process audit KEEP requires severity none")
    findings = verdict.get("findings")
    if not isinstance(findings, list):
        errors.append("process audit findings must be a list")
        findings = []
    for finding in findings:
        if not isinstance(finding, dict):
            errors.append("process audit finding must be an object")
            continue
        if not isinstance(finding.get("description"), str) or not finding[
            "description"
        ].strip():
            errors.append("process audit finding description must be non-empty")
        target = finding.get("target_skill")
        if target is not None and (not isinstance(target, str) or not target.strip()):
            errors.append("process audit finding target_skill must be null or non-empty")
        hashes = finding.get("evidence_sha256")
        if not isinstance(hashes, list) or not hashes:
            errors.append("process audit finding must cite evidence_sha256")
        elif any(value not in evidence_hashes for value in hashes):
            errors.append("process audit finding cites evidence outside episode")
        if classification == "PROCESS_DEFECT" and not target:
            errors.append("process audit PROCESS_DEFECT findings require target_skill")
    if classification in {"PROCESS_DEFECT", "MANUAL_STOP_VALIDATED"} and not findings:
        errors.append(f"process audit {classification} requires a finding")
    actions = verdict.get("actions")
    if not isinstance(actions, list) or not actions:
        errors.append("process audit actions must be a non-empty list")
        actions = []
    allowed_actions = PROCESS_AUDIT_CLASSIFICATION_ACTIONS.get(
        str(classification), set()
    )
    for action in actions:
        if not isinstance(action, dict):
            errors.append("process audit action must be an object")
            continue
        kind = action.get("kind")
        if kind not in PROCESS_AUDIT_ACTIONS or kind not in allowed_actions:
            errors.append(f"process audit action {kind!r} is invalid for classification")
        if not isinstance(action.get("description"), str) or not action[
            "description"
        ].strip():
            errors.append("process audit action description must be non-empty")
        target = action.get("target_skill")
        if kind == "propose_policy_change" and (
            not isinstance(target, str) or not target.strip()
        ):
            errors.append("process audit propose_policy_change requires target_skill")
    if (
        classification == "MANUAL_STOP_VALIDATED"
        and any(
            isinstance(action, dict)
            and action.get("kind") == "propose_policy_change"
            for action in actions
        )
        and pattern is None
    ):
        errors.append(
            "process audit policy-changing MANUAL_STOP_VALIDATED requires "
            "process_pattern_id"
        )
    manual_assessment = verdict.get("manual_stop_assessment")
    if manual_assessment not in PROCESS_AUDIT_MANUAL_ASSESSMENTS:
        errors.append("process audit manual_stop_assessment is invalid")
    if outcome == "user_stopped":
        expected = {
            "MANUAL_STOP_VALIDATED": "validated",
            "MANUAL_STOP_UNCONFIRMED": "unconfirmed",
        }.get(str(classification))
        if manual_assessment not in {"validated", "unconfirmed"}:
            errors.append("process audit user_stopped requires manual assessment")
        elif expected is not None and manual_assessment != expected:
            errors.append("process audit manual classification/assessment mismatch")
    elif manual_assessment != "not_applicable":
        errors.append("process audit manual_stop_assessment must be not_applicable")
    if classification in {
        "MANUAL_STOP_VALIDATED",
        "MANUAL_STOP_UNCONFIRMED",
    } and outcome != "user_stopped":
        errors.append("process audit manual classification requires user_stopped")
    if verdict.get("no_auto_resume") is not True or verdict.get("auto_apply") is not False:
        errors.append("process audit safety boundary is invalid")
    if review_scope is not None:
        if findings != [] or pattern is not None:
            errors.append("process audit targeted verdict cannot expand findings or pattern")
        if verdict.get("scope_expansion") is not False or verdict.get(
            "automatic_followup"
        ) is not False:
            errors.append("process audit targeted verdict safety flags are invalid")
        results = verdict.get("remediation_results")
        actual_fingerprints: list[str] = []
        statuses: list[str] = []
        if not isinstance(results, list) or not results:
            errors.append("process audit targeted verdict requires remediation_results")
            results = []
        source_hashes = {
            review_scope.get("source_episode_sha256"),
            review_scope.get("source_verdict_sha256"),
        }
        for result in results:
            if not isinstance(result, dict):
                errors.append("process audit remediation result must be an object")
                continue
            finding_id = result.get("finding_fingerprint")
            if isinstance(finding_id, str):
                actual_fingerprints.append(finding_id)
            status = result.get("status")
            if status in {"closed", "open", "unverified"}:
                statuses.append(status)
            else:
                errors.append("process audit remediation result status is invalid")
            if not isinstance(result.get("summary"), str) or not result["summary"].strip():
                errors.append("process audit remediation result summary is empty")
            hashes = result.get("evidence_sha256")
            if not isinstance(hashes, list) or not hashes:
                errors.append("process audit remediation result requires evidence")
            elif any(value not in evidence_hashes for value in hashes):
                errors.append("process audit remediation result cites outside evidence")
            elif not any(value not in source_hashes for value in hashes):
                errors.append("process audit remediation result lacks current evidence")
        if actual_fingerprints != selected_fingerprints:
            errors.append("process audit remediation results do not match selected findings")
        if statuses and all(status == "closed" for status in statuses):
            if classification != "KEEP" or severity != "none":
                errors.append("process audit closed remediation requires KEEP none")
        elif "open" in statuses:
            if classification != "EXECUTION_DEFECT" or severity == "none":
                errors.append("process audit open remediation requires execution defect")
        elif statuses and classification != "EVIDENCE_GAP":
            errors.append("process audit unverified remediation requires evidence gap")
    elif "remediation_results" in verdict:
        errors.append("process audit remediation_results require targeted review_scope")
    verdict_recorded = process_audit_iso(verdict.get("recorded_at"))
    if verdict_recorded is None:
        errors.append("process audit verdict recorded_at must be timezone-aware ISO-8601")
    elif episode_recorded is not None and verdict_recorded < episode_recorded:
        errors.append("process audit verdict recorded_at precedes episode")
    verdict_fingerprint = verdict.get("fingerprint")
    if not isinstance(verdict_fingerprint, str) or not SHA256_RE.fullmatch(
        verdict_fingerprint
    ) or verdict_fingerprint != canonical_fingerprint(verdict):
        errors.append("process audit verdict fingerprint is invalid")
    return errors


def process_audit_summary(
    *,
    case_id: str,
    project_root: str,
    origin: str,
    episode_path: Path | None,
    verdict_path: Path | None,
) -> dict[str, Any]:
    if episode_path is None and verdict_path is None:
        return {
            "available": False,
            "independent": False,
            "classification": "missing",
            "promotion_evidence_eligible": False,
            "evidence_refs": [],
        }
    if episode_path is None or verdict_path is None:
        raise PolicyLearningError("process audit requires both episode and verdict")
    resolved_episode = episode_path.expanduser().resolve()
    resolved_verdict = verdict_path.expanduser().resolve()
    episode = read_json(resolved_episode)
    verdict = read_json(resolved_verdict)
    validation_errors = validate_process_audit_pair(
        episode,
        verdict,
        verify_evidence=True,
    )
    if validation_errors:
        raise PolicyLearningError("invalid process audit: " + "; ".join(validation_errors))
    assert isinstance(episode, dict)
    assert isinstance(verdict, dict)
    if episode.get("work_item_id") != case_id:
        raise PolicyLearningError("process audit belongs to another case")
    if episode.get("origin") != origin:
        raise PolicyLearningError("process audit origin does not match policy sample origin")
    audit_root = episode.get("project_root")
    if canonical_project_root(audit_root) != canonical_project_root(project_root):
        raise PolicyLearningError("process audit belongs to another project root")
    skills = episode.get("skill_chain")
    if not any(
        isinstance(item, dict) and item.get("name") == "vigers" for item in skills
    ):
        raise PolicyLearningError("process audit does not cover vigers")
    classification = verdict.get("classification")
    outcome = episode.get("outcome")
    return {
        "available": True,
        "independent": True,
        "classification": classification,
        "promotion_evidence_eligible": (
            classification == "KEEP"
            and outcome == "completed"
            and origin in TRAINING_ORIGINS
            and episode.get("review_scope") is None
        ),
        "outcome": outcome,
        "episode_id": episode.get("episode_id"),
        "evidence_refs": [
            bind_evidence_file(resolved_episode),
            bind_evidence_file(resolved_verdict),
        ],
    }


def block_bucket(value: int) -> str:
    if value <= 1:
        return "1"
    if value <= 3:
        return "2-3"
    if value <= 8:
        return "4-8"
    return "9+"


def build_features(
    decision: dict[str, Any],
    *,
    route_id: str,
    intent: str,
    effective_assurance: str | None = None,
) -> dict[str, Any]:
    try:
        validate_mode_decision(decision)
    except ModeDecisionError as exc:
        raise PolicyLearningError(f"Invalid mode decision: {exc}") from exc
    if "risk_facts" not in decision or "selected_assurance" not in decision:
        raise PolicyLearningError(
            "policy learning requires a current mode decision with assurance features"
        )
    facts = decision["facts"]
    risks = decision["risk_facts"]
    active_risks = sorted(field for field in RISK_FIELDS if risks[field])
    features = {
        "schema": FEATURE_SCHEMA_VERSION,
        "mode": decision["selected_mode"],
        "assurance": effective_assurance or decision["selected_assurance"],
        "change_scope": risks["change_scope"],
        "surface_signature": sorted(facts["surfaces"]),
        "risk_signature": active_risks,
        "block_bucket": block_bucket(facts["estimated_blocks"]),
        "route_id": route_id,
        "intent": intent,
    }
    features["cohort_fingerprint"] = canonical_fingerprint(features)
    return features


def run_bundle(run: dict[str, Any]) -> dict[str, Any]:
    findings = run["findings"]
    reported_total = sum(findings[severity] for severity in ("blocker", "major", "minor"))
    verification = run.get("verification")
    dispositions = (
        verification.get("dispositions") if isinstance(verification, dict) else None
    )
    lenses = sorted(run.get("lenses", []))
    identity = {
        "role": run["role"],
        "role_mode": run["role_mode"],
        "lenses": lenses,
    }
    return {
        **identity,
        "bundle_fingerprint": canonical_fingerprint(identity),
        "model": run["model"],
        "duration_seconds": run["duration_seconds"],
        "input_tokens": run.get("input_tokens"),
        "output_tokens": run.get("output_tokens"),
        "reported": dict(findings),
        "reported_total": reported_total,
        "verification_complete": reported_total == 0 or isinstance(dispositions, dict),
        "dispositions": dict(dispositions) if isinstance(dispositions, dict) else None,
        "status": run.get("status", "completed"),
    }


def sum_optional_int(runs: list[dict[str, Any]], field: str) -> int | None:
    values = [run.get(field) for run in runs]
    if any(value is None for value in values):
        return None
    return sum(int(value) for value in values)


def remediation_counts(ledger: dict[str, Any]) -> dict[str, int]:
    counts = {"targeted": 0, "full-block": 0}
    for block in ledger.get("blocks", []):
        if not isinstance(block, dict):
            continue
        for remediation in block.get("remediations", []):
            if isinstance(remediation, dict) and remediation.get("scope") in counts:
                counts[str(remediation["scope"])] += 1
    return counts


def build_episode(
    case_root: Path,
    *,
    profile_id: str,
    project_root: str,
    origin: str,
    feedback_path: Path | None = None,
    process_episode_path: Path | None = None,
    process_verdict_path: Path | None = None,
) -> dict[str, Any]:
    if origin not in SAMPLE_ORIGINS:
        raise PolicyLearningError(f"unsupported policy sample origin: {origin}")
    try:
        root, manifest, ledger = case_pipeline.load_case(case_root)
    except case_pipeline.CaseError as exc:
        raise PolicyLearningError(str(exc)) from exc
    expected_project_root = canonical_project_root(project_root)
    manifest_project_root = manifest.get("project_root")
    if not isinstance(manifest_project_root, str) or (
        canonical_project_root(manifest_project_root) != expected_project_root
    ):
        raise PolicyLearningError("case belongs to another project root")
    if manifest.get("profile_id") != profile_id:
        raise PolicyLearningError("case belongs to another profile")
    final_errors = case_pipeline.validate_case(root, manifest, ledger, final=True)
    if final_errors:
        preview = "; ".join(final_errors[:5])
        suffix = "" if len(final_errors) <= 5 else f"; and {len(final_errors) - 5} more"
        raise PolicyLearningError(f"case is not final-green: {preview}{suffix}")

    decision_binding = manifest.get("mode_decision")
    if not isinstance(decision_binding, dict) or decision_binding.get("path") != "mode-decision.json":
        raise PolicyLearningError("case has no current mode decision binding")
    decision = read_json(root / "mode-decision.json")
    try:
        validate_mode_decision(
            decision,
            expected_mode=str(manifest.get("mode")),
            expected_profile_id=profile_id,
        )
    except ModeDecisionError as exc:
        raise PolicyLearningError(f"Invalid case mode decision: {exc}") from exc
    if decision_binding.get("fingerprint") != decision.get("fingerprint"):
        raise PolicyLearningError("case mode decision binding is stale")
    decision_project_root = decision.get("profile", {}).get("project_root")
    if not isinstance(decision_project_root, str) or (
        canonical_project_root(decision_project_root) != expected_project_root
    ):
        raise PolicyLearningError("case mode decision belongs to another project root")

    agent_relative = manifest.get("artifacts", {}).get("agent_ledger")
    if not isinstance(agent_relative, str):
        raise PolicyLearningError("case has no agent ledger")
    agent_payload = read_json(root / agent_relative)
    agent_errors = case_pipeline.validate_agent_ledger(
        agent_payload,
        case_id=str(manifest.get("case_id")),
    )
    if agent_errors:
        raise PolicyLearningError("invalid agent ledger: " + "; ".join(agent_errors))
    runs = [run for run in agent_payload["runs"] if isinstance(run, dict)]
    bundles = [run_bundle(run) for run in runs]
    verification_complete = all(bundle["verification_complete"] for bundle in bundles)
    terminal_clean = all(bundle["status"] == "completed" for bundle in bundles)

    feedback: dict[str, Any] | None = None
    if feedback_path is not None:
        loaded_feedback = read_json(feedback_path.expanduser().resolve())
        feedback_errors = validate_feedback(
            loaded_feedback,
            case_id=str(manifest.get("case_id")),
        )
        if feedback_errors:
            raise PolicyLearningError("Invalid policy feedback: " + "; ".join(feedback_errors))
        evidence_errors = feedback_evidence_errors(loaded_feedback)
        if evidence_errors:
            raise PolicyLearningError("Invalid policy feedback: " + "; ".join(evidence_errors))
        feedback = loaded_feedback

    process_audit = process_audit_summary(
        case_id=str(manifest.get("case_id")),
        project_root=expected_project_root,
        origin=origin,
        episode_path=process_episode_path,
        verdict_path=process_verdict_path,
    )
    if origin in TRAINING_ORIGINS and not process_audit["available"]:
        raise PolicyLearningError(
            "prospective-clean and frozen-replay samples require an independent process audit"
        )

    features = build_features(
        decision,
        route_id=str(manifest.get("route_id")),
        intent=str(manifest.get("intent")),
        effective_assurance=str(manifest.get("assurance_level")),
    )
    reported = {
        severity: sum(bundle["reported"][severity] for bundle in bundles)
        for severity in ("blocker", "major", "minor")
    }
    dispositions = {name: 0 for name in ("accepted", "rejected", "duplicate", "verified")}
    for bundle in bundles:
        if isinstance(bundle["dispositions"], dict):
            for name in dispositions:
                dispositions[name] += bundle["dispositions"][name]
    episode = {
        "case_id": manifest["case_id"],
        "origin": origin,
        "case_subject_fingerprint": canonical_fingerprint(
            {
                "mode_decision": decision["fingerprint"],
                "kernel": manifest.get("kernel", {}).get("sha256"),
                "gates": manifest.get("gates"),
                "agent_ledger": canonical_fingerprint(agent_payload),
            }
        ),
        "features": features,
        "strategy": {
            "review_strategy": case_pipeline.REVIEW_STRATEGIES[
                str(manifest.get("assurance_level"))
            ],
            "run_bundles": bundles,
            "remediations": remediation_counts(ledger),
        },
        "efficiency": {
            "agent_run_count": len(runs),
            "review_run_count": sum(run["role"] == "spec-reviewer" for run in runs),
            "duration_seconds": round(sum(float(run["duration_seconds"]) for run in runs), 6),
            "retries": sum(int(run["retries"]) for run in runs),
            "input_tokens": sum_optional_int(runs, "input_tokens"),
            "output_tokens": sum_optional_int(runs, "output_tokens"),
            "tool_calls": sum_optional_int(runs, "tool_calls"),
            "poll_calls": sum_optional_int(runs, "poll_calls"),
        },
        "quality": {
            "final_validation": "pass",
            "terminal_runs_clean": terminal_clean,
            "verification_complete": verification_complete,
            "reported_findings": reported,
            "dispositions": dispositions,
            "external_feedback": feedback_summary(feedback),
            "process_audit": process_audit,
        },
        "training_eligible": (
            origin in TRAINING_ORIGINS
            and terminal_clean
            and verification_complete
            and process_audit["promotion_evidence_eligible"]
        ),
        "promotion_evidence_eligible": (
            feedback_summary(feedback)["promotion_evidence_eligible"]
            and process_audit["promotion_evidence_eligible"]
            and origin in TRAINING_ORIGINS
            and terminal_clean
            and verification_complete
        ),
        "recorded_at": now_utc(),
    }
    episode["fingerprint"] = canonical_fingerprint(
        episode,
        ignored={"recorded_at"},
    )
    return episode


def validate_model(payload: Any, *, profile_id: str, project_root: str) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, dict) or payload.get("schema") != MODEL_SCHEMA_VERSION:
        return ["policy model has unsupported schema"]
    if payload.get("feature_schema") != FEATURE_SCHEMA_VERSION:
        errors.append("policy model has unsupported feature schema")
    if payload.get("profile_id") != profile_id:
        errors.append("policy model belongs to another profile")
    if payload.get("project_key") != project_key(profile_id, project_root):
        errors.append("policy model belongs to another project root")
    samples = payload.get("samples")
    if not isinstance(samples, list):
        return errors + ["policy model samples must be an array"]
    if payload.get("sample_count") != len(samples):
        errors.append("policy model sample count is invalid")
    seen: set[str] = set()
    for index, sample in enumerate(samples, start=1):
        label = f"policy sample {index}"
        if not isinstance(sample, dict):
            errors.append(f"{label} must be an object")
            continue
        case_id = sample.get("case_id")
        if not isinstance(case_id, str) or not case_id.strip() or case_id in seen:
            errors.append(f"{label} has invalid or duplicate case_id")
        else:
            seen.add(case_id)
        features = sample.get("features")
        if not isinstance(features, dict) or features.get("schema") != FEATURE_SCHEMA_VERSION:
            errors.append(f"{label} has invalid features")
        elif features.get("cohort_fingerprint") != canonical_fingerprint(
            features,
            ignored={"cohort_fingerprint"},
        ):
            errors.append(f"{label} has invalid cohort fingerprint")
        for field in ("training_eligible", "promotion_evidence_eligible"):
            if not isinstance(sample.get(field), bool):
                errors.append(f"{label} {field} must be boolean")
        if sample.get("origin") not in SAMPLE_ORIGINS:
            errors.append(f"{label} has invalid origin")
        if sample.get("origin") == "historical-biased" and sample.get(
            "training_eligible"
        ):
            errors.append(f"{label} historical-biased sample cannot train policy")
        if sample.get("promotion_evidence_eligible") and not sample.get(
            "training_eligible"
        ):
            errors.append(f"{label} promotion evidence requires training eligibility")
        strategy = sample.get("strategy")
        bundles = strategy.get("run_bundles") if isinstance(strategy, dict) else None
        if not isinstance(bundles, list):
            errors.append(f"{label} strategy.run_bundles must be an array")
        else:
            for bundle_index, bundle in enumerate(bundles, start=1):
                bundle_label = f"{label} bundle {bundle_index}"
                if not isinstance(bundle, dict):
                    errors.append(f"{bundle_label} must be an object")
                    continue
                identity = {
                    "role": bundle.get("role"),
                    "role_mode": bundle.get("role_mode"),
                    "lenses": bundle.get("lenses"),
                }
                if any(
                    not isinstance(identity[field], expected)
                    for field, expected in (
                        ("role", str),
                        ("role_mode", str),
                        ("lenses", list),
                    )
                ) or bundle.get("bundle_fingerprint") != canonical_fingerprint(identity):
                    errors.append(f"{bundle_label} identity is invalid")
                if not isinstance(bundle.get("verification_complete"), bool):
                    errors.append(f"{bundle_label} verification_complete must be boolean")
                if not non_negative_int(bundle.get("reported_total")):
                    errors.append(f"{bundle_label} reported_total must be non-negative")
                duration = bundle.get("duration_seconds")
                if (
                    not isinstance(duration, (int, float))
                    or isinstance(duration, bool)
                    or duration < 0
                ):
                    errors.append(f"{bundle_label} duration_seconds is invalid")
        efficiency = sample.get("efficiency")
        if not isinstance(efficiency, dict):
            errors.append(f"{label} efficiency must be an object")
        else:
            for field in ("agent_run_count", "review_run_count", "retries"):
                if not non_negative_int(efficiency.get(field)):
                    errors.append(f"{label} efficiency.{field} must be non-negative")
            duration = efficiency.get("duration_seconds")
            if (
                not isinstance(duration, (int, float))
                or isinstance(duration, bool)
                or duration < 0
            ):
                errors.append(f"{label} efficiency.duration_seconds is invalid")
        quality = sample.get("quality")
        if not isinstance(quality, dict) or quality.get("final_validation") != "pass":
            errors.append(f"{label} requires final validation pass")
        elif not isinstance(quality.get("external_feedback"), dict):
            errors.append(f"{label} external feedback summary is invalid")
        elif not isinstance(quality.get("process_audit"), dict):
            errors.append(f"{label} process audit summary is invalid")
        elif sample.get("training_eligible") != bool(
            sample.get("origin") in TRAINING_ORIGINS
            and quality["process_audit"].get("promotion_evidence_eligible")
            and quality.get("terminal_runs_clean")
            and quality.get("verification_complete")
        ):
            errors.append(f"{label} training eligibility is inconsistent")
        elif sample.get("promotion_evidence_eligible") != bool(
            quality["external_feedback"].get("promotion_evidence_eligible")
            and quality["process_audit"].get("promotion_evidence_eligible")
            and sample.get("training_eligible")
        ):
            errors.append(f"{label} promotion evidence eligibility is inconsistent")
        if sample.get("fingerprint") != canonical_fingerprint(
            sample,
            ignored={"recorded_at"},
        ):
            errors.append(f"{label} fingerprint mismatch")
    return errors


def load_model(path: Path, *, profile_id: str, project_root: str) -> dict[str, Any]:
    if not path.exists():
        return empty_model(profile_id, project_root)
    payload = read_json(path)
    errors = validate_model(payload, profile_id=profile_id, project_root=project_root)
    if errors:
        raise PolicyLearningError("Invalid policy model: " + "; ".join(errors))
    return payload


def update_model(
    model: dict[str, Any],
    episode: dict[str, Any],
    *,
    replace: bool = False,
) -> bool:
    matches = [
        index
        for index, sample in enumerate(model["samples"])
        if sample.get("case_id") == episode["case_id"]
    ]
    if not matches:
        model["samples"].append(episode)
        changed = True
    else:
        index = matches[0]
        if model["samples"][index].get("fingerprint") == episode["fingerprint"]:
            return False
        if not replace:
            raise PolicyLearningError(
                "policy sample changed; pass --replace after verifying the new evidence"
            )
        model["samples"][index] = episode
        changed = True
    model["samples"].sort(key=lambda sample: sample["case_id"])
    model["sample_count"] = len(model["samples"])
    model["updated_at"] = now_utc()
    return changed


def median(values: list[float | int]) -> float | None:
    return round(float(statistics.median(values)), 6) if values else None


def clean_external_feedback(sample: dict[str, Any]) -> bool:
    quality = sample["quality"]
    feedback = quality["external_feedback"]
    if not sample.get("promotion_evidence_eligible"):
        return False
    if feedback_evidence_errors({"evidence_refs": feedback.get("evidence_refs", [])}):
        return False
    process_audit = quality.get("process_audit", {})
    if (
        process_audit.get("classification") != "KEEP"
        or process_audit.get("outcome") != "completed"
        or feedback_evidence_errors(
            {"evidence_refs": process_audit.get("evidence_refs", [])}
        )
    ):
        return False
    defects = feedback["specification_defects"]
    return (
        feedback["human_rework_count"] == 0
        and feedback["developer_clarification_count"] == 0
        and defects["blocker"] == 0
        and defects["major"] == 0
    )


def build_shadow_candidate(
    model: dict[str, Any],
    decision: dict[str, Any],
    *,
    route_id: str,
    intent: str,
) -> dict[str, Any]:
    query_profile = decision.get("profile")
    if not isinstance(query_profile, dict) or query_profile.get("id") != model.get(
        "profile_id"
    ):
        raise PolicyLearningError("mode decision belongs to another policy profile")
    query_project_root = query_profile.get("project_root")
    if not isinstance(query_project_root, str) or project_key(
        str(query_profile["id"]),
        query_project_root,
    ) != model.get("project_key"):
        raise PolicyLearningError("mode decision belongs to another policy project root")
    features = build_features(decision, route_id=route_id, intent=intent)
    cohort = [
        sample
        for sample in model["samples"]
        if sample.get("training_eligible")
        and sample.get("features", {}).get("cohort_fingerprint")
        == features["cohort_fingerprint"]
    ]
    quality_cohort = [sample for sample in cohort if sample.get("promotion_evidence_eligible")]
    blockers: list[str] = []
    candidates: list[dict[str, Any]] = []
    if features["assurance"] == "high":
        status = "protected_baseline"
        blockers.append("high assurance is excluded from automatic policy experiments")
    elif len(cohort) < MIN_SHADOW_COHORT:
        status = "insufficient_data"
        blockers.append(
            f"exact cohort has {len(cohort)} eligible samples; {MIN_SHADOW_COHORT} required"
        )
    elif len(quality_cohort) != len(cohort):
        status = "feedback_incomplete"
        blockers.append("every eligible cohort sample needs complete closed external feedback")
    elif not all(clean_external_feedback(sample) for sample in quality_cohort):
        status = "quality_floor_not_met"
        blockers.append("external feedback contains rework, clarification, blocker, or major defects")
    else:
        protected_review_modes = {"final", "block"}
        review_bundles: dict[str, list[dict[str, Any]]] = {}
        for sample in cohort:
            for bundle in sample["strategy"]["run_bundles"]:
                if bundle["role"] != "spec-reviewer":
                    continue
                if bundle["role_mode"] in protected_review_modes:
                    continue
                review_bundles.setdefault(bundle["bundle_fingerprint"], []).append(bundle)
        for bundle_fingerprint, bundles in sorted(review_bundles.items()):
            if len(bundles) != len(cohort):
                continue
            if not all(bundle["verification_complete"] for bundle in bundles):
                continue
            reported = sum(bundle["reported_total"] for bundle in bundles)
            accepted = sum(
                (bundle["dispositions"] or {}).get("accepted", 0) for bundle in bundles
            )
            if reported != 0 and accepted != 0:
                continue
            identity = {
                "role": bundles[0]["role"],
                "role_mode": bundles[0]["role_mode"],
                "lenses": bundles[0]["lenses"],
            }
            candidates.append(
                {
                    "id": f"PLC-{len(candidates) + 1:03d}",
                    "kind": "extra-review-bundle-ablation-replay",
                    "target": identity,
                    "evidence": {
                        "case_ids": sorted(sample["case_id"] for sample in cohort),
                        "run_count": len(bundles),
                        "reported_findings": reported,
                        "accepted_findings": accepted,
                        "median_duration_seconds": median(
                            [bundle["duration_seconds"] for bundle in bundles]
                        ),
                        "bundle_fingerprint": bundle_fingerprint,
                    },
                    "next_step": "replay against frozen cases with unchanged quality gates",
                    "promotion_allowed": False,
                }
            )
        status = "shadow_candidates" if candidates else "baseline_retained"
        if not candidates:
            blockers.append("no consistently low-yield review bundle was observed")

    result = {
        "schema": SHADOW_SCHEMA_VERSION,
        "purpose": "human_review_only",
        "status": status,
        "query": features,
        "baseline": {
            "mode": features["mode"],
            "assurance": features["assurance"],
            "review_strategy": case_pipeline.REVIEW_STRATEGIES[features["assurance"]],
            "protected_review_modes": ["block", "final"],
        },
        "cohort": {
            "minimum_samples": MIN_SHADOW_COHORT,
            "eligible_sample_count": len(cohort),
            "external_quality_sample_count": len(quality_cohort),
            "case_ids": sorted(sample["case_id"] for sample in cohort),
            "median_agent_duration_seconds": median(
                [sample["efficiency"]["duration_seconds"] for sample in cohort]
            ),
            "median_agent_run_count": median(
                [sample["efficiency"]["agent_run_count"] for sample in cohort]
            ),
        },
        "quality_floor": {
            "met": status in {"shadow_candidates", "baseline_retained"},
            "requirements": [
                "same project and exact cohort",
                "final validation",
                "complete finding disposition",
                "closed external feedback",
                "no observed human rework, developer clarification, blocker, or major defect",
            ],
        },
        "enforcement": {
            "auto_apply": False,
            "assurance_change": False,
            "gate_removal": False,
            "role_context_input": False,
            "requires_frozen_replay": True,
            "requires_human_promotion": True,
            "rollback_required": True,
        },
        "candidates": candidates,
        "blockers": blockers,
        "generated_at": now_utc(),
    }
    result["fingerprint"] = canonical_fingerprint(
        result,
        ignored={"generated_at"},
    )
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    feedback_parser = subparsers.add_parser(
        "feedback",
        help="Build one evidence-bound post-handoff feedback record",
    )
    feedback_parser.add_argument("--case-id", required=True)
    feedback_parser.add_argument("--coverage", choices=("complete", "partial"), required=True)
    feedback_parser.add_argument("--window-closed", action="store_true")
    feedback_parser.add_argument("--human-rework", type=int, required=True)
    feedback_parser.add_argument("--developer-clarifications", type=int, required=True)
    feedback_parser.add_argument("--blocker-defects", type=int, required=True)
    feedback_parser.add_argument("--major-defects", type=int, required=True)
    feedback_parser.add_argument("--minor-defects", type=int, required=True)
    feedback_parser.add_argument("--evidence-file", action="append", default=[])
    feedback_parser.add_argument("--write", required=True)

    update_parser = subparsers.add_parser(
        "update",
        help="Add one final-green case observation to project-local policy history",
    )
    update_parser.add_argument("--case-root", required=True)
    update_parser.add_argument("--profile-id", required=True)
    update_parser.add_argument("--project-root", required=True)
    update_parser.add_argument("--origin", choices=sorted(SAMPLE_ORIGINS), required=True)
    update_parser.add_argument("--feedback")
    update_parser.add_argument("--process-episode")
    update_parser.add_argument("--process-verdict")
    update_parser.add_argument("--model")
    update_parser.add_argument("--replace", action="store_true")

    suggest_parser = subparsers.add_parser(
        "suggest",
        help="Create a shadow-only candidate report for one mode decision",
    )
    suggest_parser.add_argument("--profile-id", required=True)
    suggest_parser.add_argument("--project-root", required=True)
    suggest_parser.add_argument("--mode-decision", required=True)
    suggest_parser.add_argument("--route-id", required=True)
    suggest_parser.add_argument("--intent", required=True)
    suggest_parser.add_argument("--model")
    suggest_parser.add_argument("--write", required=True)

    validate_parser = subparsers.add_parser("validate", help="Validate one policy model")
    validate_parser.add_argument("--profile-id", required=True)
    validate_parser.add_argument("--project-root", required=True)
    validate_parser.add_argument("--model")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "feedback":
            payload = build_feedback(
                case_id=args.case_id,
                coverage=args.coverage,
                window_closed=args.window_closed,
                human_rework_count=args.human_rework,
                developer_clarification_count=args.developer_clarifications,
                blocker_defects=args.blocker_defects,
                major_defects=args.major_defects,
                minor_defects=args.minor_defects,
                evidence_refs=[bind_evidence_file(Path(value)) for value in args.evidence_file],
            )
            target = Path(args.write).expanduser().resolve()
            atomic_json(target, payload)
            print(json.dumps(payload, ensure_ascii=False, indent=2))
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
        if args.command == "update":
            episode = build_episode(
                Path(args.case_root),
                profile_id=args.profile_id,
                project_root=args.project_root,
                origin=args.origin,
                feedback_path=Path(args.feedback) if args.feedback else None,
                process_episode_path=(
                    Path(args.process_episode) if args.process_episode else None
                ),
                process_verdict_path=(
                    Path(args.process_verdict) if args.process_verdict else None
                ),
            )
            changed = update_model(model, episode, replace=args.replace)
            if changed:
                atomic_json(model_path, model)
            print(
                json.dumps(
                    {
                        "changed": changed,
                        "model": str(model_path),
                        "sample_count": model["sample_count"],
                        "case_id": episode["case_id"],
                        "training_eligible": episode["training_eligible"],
                        "promotion_evidence_eligible": episode[
                            "promotion_evidence_eligible"
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        if args.command == "suggest":
            decision = read_json(Path(args.mode_decision).expanduser().resolve())
            result = build_shadow_candidate(
                model,
                decision,
                route_id=args.route_id,
                intent=args.intent,
            )
            target = Path(args.write).expanduser().resolve()
            atomic_json(target, result)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        errors = validate_model(
            model,
            profile_id=args.profile_id,
            project_root=args.project_root,
        )
        if errors:
            raise PolicyLearningError("Invalid policy model: " + "; ".join(errors))
        print(f"PASS policy-model samples={model['sample_count']}")
        return 0
    except PolicyLearningError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
