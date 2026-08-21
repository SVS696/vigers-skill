#!/usr/bin/env python3
"""Deterministic, resumable case-state orchestration for Vigers."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import shutil
import sys
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from automation_timing import (
    FILENAME as AUTOMATION_TIMING_FILENAME,
    AutomationTimingError,
    initialize_ledger as initialize_automation_timing,
    summarize as summarize_automation_timing,
    validate_ledger as validate_automation_timing,
)
from document_conformance import validate_contract, validate_markdown_file
from mode_decision import (
    ASSURANCE_LEVELS,
    CHANGE_SCOPES,
    MODE_DECISION_FILENAME,
    PROJECTION_SYNC_POLICIES,
    TRACKING_POLICIES,
    ModeDecisionError,
    validate_mode_decision,
)
from planning_case import (
    HANDOFF_JSON as PLANNING_HANDOFF_JSON,
    HANDOFF_MARKDOWN as PLANNING_HANDOFF_MARKDOWN,
    PlanningError,
    TARGET_ID_RE,
    canonical_fingerprint as canonical_planning_fingerprint,
    validate_handoff as validate_planning_handoff,
)
from spec_pipeline import (
    PROJECTION_EVIDENCE_KINDS,
    PipelineError,
    detect_profile,
    select_profile,
)
from vigers_context import (
    METHOD_CONTEXT_JSON,
    METHOD_CONTEXT_MARKDOWN,
    RouterError,
    validate_method_context,
)


SCHEMA_VERSION = 2
TODO_MARKER = "VIGERS_TODO"
PLANNING_ROLE_CONTEXT_JSON = "planning-role-context.json"
PLANNING_ROLE_CONTEXT_SCHEMA = 1
ROLE_MANIFEST_JSON = "role-manifest.json"
ROLE_MANIFEST_SCHEMA = 1
WORKING_PROJECTION_JSON = "working-projection.json"
WORKING_PROJECTION_SCHEMA = 1
AGENT_LEDGER_JSON = "agent-ledger.json"
AGENT_LEDGER_SCHEMA = 1
RECOVERY_PLAN_JSON = "recovery-plan.json"
RECOVERY_PLAN_SCHEMA = 1
RISK_PREFLIGHT_SCHEMA = 1
PROJECT_CONFORMANCE_CONTRACT_JSON = "project-conformance-contract.json"
EXTERNAL_READBACK_RECEIPT_SCHEMA = 1
CASE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
BLOCK_ID_RE = re.compile(r"^B[0-9]{2,3}$")
FINDING_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
AGENT_RUN_ID_RE = re.compile(r"^AR-[0-9]{4,}$")
REVIEW_LENS_RE = re.compile(r"^[a-z][a-z0-9._-]{0,63}@[1-9][0-9]*$")
RISK_SURFACE_RE = re.compile(r"^[a-z][a-z0-9-]{1,63}$")
RECOVERY_SCOPE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
SEMANTIC_ID_RE = re.compile(
    r"^(GOAL|ACT|SCN|RULE|DATA|STATE|IF|QUAL|REQ|AC|DOD|ASM|Q|DEC|CON)-"
    r"(B[0-9]{2,3})-[0-9]{3}$"
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SOLUTION_BOUNDARY_START = "<!-- vigers:solution-boundary:start -->"
SOLUTION_BOUNDARY_END = "<!-- vigers:solution-boundary:end -->"
SOLUTION_HORIZONS = {
    "tactical",
    "bounded-systemic",
    "generalized-capability",
}
SOLUTION_BOUNDARY_SCHEMAS = {1, 2}
IMPLEMENTATION_TRANSITION_MODES = {
    "evolve-in-place",
    "replace-and-remove",
    "staged-migration",
}

BLOCK_KINDS = {
    "context",
    "scenarios",
    "rules",
    "data",
    "interfaces",
    "quality",
    "errors",
    "acceptance",
    "integration",
    "custom",
}
BLOCK_STATUSES = {
    "planned",
    "ready",
    "in_progress",
    "analyzed",
    "reviewed",
    "integrated",
    "blocked",
    "stale",
}
ALLOWED_TRANSITIONS = {
    "planned": {"ready", "blocked"},
    "ready": {"in_progress", "blocked"},
    "in_progress": {"analyzed", "blocked"},
    "analyzed": {"reviewed", "in_progress", "blocked"},
    "reviewed": {"integrated", "in_progress", "blocked"},
    "integrated": {"in_progress", "blocked"},
    "blocked": {"ready"},
    "stale": {"ready"},
}

SEMANTIC_KIND_PREFIX = {
    "goal": "GOAL",
    "actor": "ACT",
    "scenario": "SCN",
    "rule": "RULE",
    "data": "DATA",
    "state": "STATE",
    "interface": "IF",
    "quality": "QUAL",
    "requirement": "REQ",
    "acceptance": "AC",
    "dod": "DOD",
    "assumption": "ASM",
    "question": "Q",
    "decision": "DEC",
    "constraint": "CON",
}

GATE_NAMES = (
    "evidence",
    "architecture_design",
    "author_passes",
    "semantic_integration",
    "consistency",
    "integration_review",
    "global_review",
    "project_conformance",
    "architecture_conformance",
)
GATE_STATUSES = {"pending", "pass", "blocked", "not_required"}
FINAL_GATES = GATE_NAMES
REVISIONED_REVIEW_GATES = {
    "integration_review",
    "global_review",
    "project_conformance",
    "architecture_conformance",
}

REVIEW_STRATEGIES = {
    "lite": "machine-first",
    "standard": "combined-final",
    "high": "layered-independent",
}
CONTRACT_SURFACES = {
    "solution-boundary",
    "diagram",
    "reader-projection",
    "project-rules",
}
REMEDIATION_SCOPES = {"targeted", "full-block"}
REMEDIATION_SEVERITIES = {"blocker", "major"}
REMEDIATION_CONTRACT_V1 = "targeted-v1"
REMEDIATION_CONTRACT_V2 = "batched-v2"
MAX_REMEDIATION_BATCHES = 2
AGENT_RUN_STATUSES = {"completed", "degraded", "failed", "timed_out"}
AGENT_SUPERVISOR_CONTRACT = "one-retry-v1"
RECOVERY_STATUSES = {"active", "complete", "cancelled"}
RECOVERY_COMBINED_GATES = (
    "integration_review",
    "global_review",
    "project_conformance",
)


class CaseError(RuntimeError):
    """Invalid case state or unsafe transition."""


def resolve_init_profile(requested_id: str, cwd: Path):
    """Resolve the nearest profile without allowing an explicit generic bypass."""
    try:
        detected = detect_profile(cwd)
        if requested_id == "generic" and detected.profile_id != "generic":
            raise CaseError(
                "Explicit generic profile cannot override the nearest project profile"
            )
        return detected if requested_id == "auto" else select_profile(requested_id, cwd)
    except PipelineError as exc:
        raise CaseError(str(exc)) from exc


def resolve_init_project_context(
    requested_id: str,
    cwd: Path,
    explicit_project_root: Path | None,
):
    """Detect from cwd and treat an explicit project root only as a cross-check."""
    selection = resolve_init_profile(requested_id, cwd)
    selected_project_root = (
        str(selection.project_root.resolve()) if selection.project_root is not None else None
    )
    expected_project_root = (
        str(explicit_project_root.expanduser().resolve())
        if explicit_project_root is not None
        else None
    )
    if expected_project_root is not None and expected_project_root != selected_project_root:
        raise CaseError("Explicit project root conflicts with detected profile")
    return selection, selected_project_root


def now_utc() -> str:
    """Return a compact UTC timestamp."""
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def sha256(path: Path) -> str:
    """Hash one file."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_json(path: Path, payload: Any) -> None:
    """Write JSON through a sibling temporary file."""
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def atomic_text(path: Path, text: str) -> None:
    """Write text through a sibling temporary file."""
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def read_json(path: Path) -> Any:
    """Read JSON with a useful error."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CaseError(f"Cannot read JSON {path}: {exc}") from exc


def case_file(root: Path, relative: str) -> Path:
    """Resolve a case-owned relative file without allowing root escape."""
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise CaseError(f"Case path escapes root: {relative}") from exc
    return candidate


def write_template(path: Path, text: str) -> None:
    """Create a missing case artifact without overwriting work."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(text, encoding="utf-8")


def artifact_ready(path: Path) -> bool:
    """Return true when an artifact exists and its placeholder is gone."""
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8")
    return bool(text.strip()) and TODO_MARKER not in text


def event(kind: str, **details: Any) -> dict[str, Any]:
    """Build one append-only state event."""
    return {"at": now_utc(), "kind": kind, **details}


def planning_role_context(payload: dict[str, Any]) -> dict[str, Any]:
    """Build the bounded planning input for roles without human ETA fields."""
    result: dict[str, Any] = {
        "schema": PLANNING_ROLE_CONTEXT_SCHEMA,
        "planning_case_id": payload.get("planning_case_id"),
        "planning_revision": payload.get("planning_revision"),
        "profile_id": payload.get("profile_id"),
        "project_root": payload.get("project_root"),
        "passport": payload.get("passport"),
        "required_anchor_systems": payload.get("required_anchor_systems", []),
        "external_bindings": payload.get("external_bindings", []),
        "working_projection": payload.get(
            "working_projection", {"policy": "optional", "targets": []}
        ),
        "preliminary_requirements": payload.get("preliminary_requirements"),
        "approval": payload.get("approval"),
        "timing_visibility": (
            "excluded" if "execution_preferences" in payload else "human_information_only"
        ),
        "excluded_fields": (
            [
                "automation_plan",
                "automation_estimation",
                "estimates",
                "timing_forecast",
                "timing_model",
                "execution_preferences",
                "runtime_ledger",
            ]
            if "execution_preferences" in payload
            else ["automation_plan", "automation_estimation", "estimates"]
        ),
    }
    if payload.get("solution_boundary_probe") is not None:
        result["solution_boundary_probe"] = payload["solution_boundary_probe"]
    if "minimum_solution_boundary_schema" in payload:
        result["minimum_solution_boundary_schema"] = payload[
            "minimum_solution_boundary_schema"
        ]
    result["fingerprint"] = role_context_fingerprint(result)
    return result


def solution_boundary_probe_present(root: Path, manifest: dict[str, Any]) -> bool:
    """Return whether the approved planning context requires a final boundary decision."""
    relative = manifest.get("artifacts", {}).get("planning_role_context")
    if not isinstance(relative, str):
        return False
    payload = read_json(case_file(root, relative))
    return isinstance(payload, dict) and isinstance(
        payload.get("solution_boundary_probe"), dict
    )


def minimum_solution_boundary_schema(root: Path, manifest: dict[str, Any]) -> int:
    """Return the pinned schema floor; absence preserves legacy case behavior."""
    relative = manifest.get("artifacts", {}).get("planning_role_context")
    if not isinstance(relative, str):
        return 1
    payload = read_json(case_file(root, relative))
    value = payload.get("minimum_solution_boundary_schema")
    return value if value in SOLUTION_BOUNDARY_SCHEMAS else 1


def extract_solution_boundary(path: Path) -> dict[str, Any] | None:
    """Extract the single structured boundary block embedded in decisions.md."""
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    starts = text.count(SOLUTION_BOUNDARY_START)
    ends = text.count(SOLUTION_BOUNDARY_END)
    if starts == 0 and ends == 0:
        return None
    if starts != 1 or ends != 1:
        raise CaseError("decisions.md must contain exactly one solution-boundary block")
    body = text.split(SOLUTION_BOUNDARY_START, 1)[1].split(SOLUTION_BOUNDARY_END, 1)[0]
    body = body.strip()
    fence = re.fullmatch(r"```json\s*(.*?)\s*```", body, flags=re.DOTALL)
    if fence is None:
        raise CaseError("solution-boundary block must contain one fenced JSON object")
    try:
        payload = json.loads(fence.group(1))
    except json.JSONDecodeError as exc:
        raise CaseError(f"solution-boundary JSON is invalid: {exc}") from exc
    if not isinstance(payload, dict):
        raise CaseError("solution-boundary payload must be an object")
    return payload


def validate_solution_boundary(
    payload: dict[str, Any],
    *,
    planning_probe_present: bool,
) -> list[str]:
    """Validate the final evidence-bound scope and extensibility decision."""
    errors: list[str] = []
    schema = payload.get("schema")
    if schema not in SOLUTION_BOUNDARY_SCHEMAS:
        errors.append("solution boundary schema must be 1 or 2")
    horizon = payload.get("solution_horizon")
    if horizon not in SOLUTION_HORIZONS:
        errors.append("solution_horizon is invalid")
    for field in ("observed_case", "root_capability"):
        if not isinstance(payload.get(field), str) or not payload[field].strip():
            errors.append(f"solution boundary missing {field}")

    def text_array(field: str, *, required: bool = False) -> list[str]:
        value = payload.get(field)
        if not isinstance(value, list) or any(
            not isinstance(item, str) or not item.strip() for item in value
        ):
            errors.append(f"solution boundary {field} must be an array of text")
            return []
        normalized = [item.strip() for item in value]
        if len(set(normalized)) != len(normalized):
            errors.append(f"solution boundary {field} must be unique")
        if required and not normalized:
            errors.append(f"solution boundary {field} must be non-empty")
        return normalized

    text_array("invariants", required=True)
    text_array("hypothesized_variants")
    text_array("current_scope", required=True)
    seams = text_array("extension_seams")
    text_array("deferred_variants")
    text_array("expansion_triggers", required=True)
    absence = payload.get("extension_seam_absence_reason")
    if seams and absence is not None:
        errors.append("extension_seam_absence_reason must be null when seams exist")
    if not seams and (not isinstance(absence, str) or not absence.strip()):
        errors.append("missing extension seam requires an explicit absence reason")

    confirmed = payload.get("confirmed_variants")
    if not isinstance(confirmed, list) or not confirmed:
        errors.append("confirmed_variants must be non-empty")
        confirmed = []
    for index, variant in enumerate(confirmed, start=1):
        label = f"confirmed_variants[{index}]"
        if not isinstance(variant, dict):
            errors.append(f"{label} must be an object")
            continue
        if not isinstance(variant.get("name"), str) or not variant["name"].strip():
            errors.append(f"{label} missing name")
        refs = variant.get("evidence_refs")
        if not isinstance(refs, list) or not refs or any(
            not isinstance(ref, str) or not ref.strip() for ref in refs
        ):
            errors.append(f"{label} requires evidence_refs")

    evidence = payload.get("horizon_evidence")
    if not isinstance(evidence, dict):
        errors.append("horizon_evidence must be an object")
        evidence = {}
    for field in ("analogy_search_refs", "roadmap_refs", "irreversibility_signals"):
        values = evidence.get(field)
        if not isinstance(values, list) or any(
            not isinstance(item, str) or not item.strip() for item in values
        ):
            errors.append(f"horizon_evidence {field} must be an array of text")

    hotfix = payload.get("hotfix_exception")
    if horizon == "tactical":
        if not isinstance(hotfix, dict):
            errors.append("tactical horizon requires hotfix_exception")
        else:
            for field in ("reason", "reversibility", "return_trigger"):
                if not isinstance(hotfix.get(field), str) or not hotfix[field].strip():
                    errors.append(f"hotfix_exception missing {field}")
            refs = hotfix.get("source_refs")
            if not isinstance(refs, list) or not refs or any(
                not isinstance(ref, str) or not ref.strip() for ref in refs
            ):
                errors.append("hotfix_exception requires source_refs")
    elif hotfix is not None:
        errors.append("hotfix_exception is allowed only for tactical horizon")

    if horizon == "generalized-capability" and not (
        len(confirmed) >= 2
        or evidence.get("roadmap_refs")
        or evidence.get("irreversibility_signals")
    ):
        errors.append(
            "generalized-capability requires confirmed breadth, roadmap, or "
            "irreversibility evidence"
        )
    disposition = payload.get("planning_probe_disposition")
    if not isinstance(disposition, dict) or disposition.get("status") not in {
        "confirmed",
        "changed",
        "rejected",
        "not_available",
    }:
        errors.append("planning_probe_disposition is invalid")
    else:
        if not isinstance(disposition.get("rationale"), str) or not disposition[
            "rationale"
        ].strip():
            errors.append("planning_probe_disposition requires rationale")
        if planning_probe_present and disposition.get("status") == "not_available":
            errors.append("an available planning probe cannot be marked not_available")

    transition = payload.get("implementation_transition")
    if schema == 1:
        if transition is not None:
            errors.append("implementation_transition requires solution boundary schema 2")
        return errors
    if not isinstance(transition, dict):
        errors.append("schema 2 requires implementation_transition")
        return errors

    mode = transition.get("mode")
    if mode not in IMPLEMENTATION_TRANSITION_MODES:
        errors.append("implementation_transition mode is invalid")
    owner = transition.get("authoritative_owner")
    if not isinstance(owner, str) or not owner.strip():
        errors.append("implementation_transition requires authoritative_owner")

    def transition_text_array(field: str) -> list[str]:
        value = transition.get(field)
        if not isinstance(value, list) or any(
            not isinstance(item, str) or not item.strip() for item in value
        ):
            errors.append(f"implementation_transition {field} must be an array of text")
            return []
        normalized = [item.strip() for item in value]
        if len(set(normalized)) != len(normalized):
            errors.append(f"implementation_transition {field} must be unique")
        return normalized

    superseded = transition_text_array("superseded_paths")
    if isinstance(owner, str) and owner.strip() in superseded:
        errors.append("authoritative_owner cannot be a superseded path")

    stages = transition.get("stages")
    if not isinstance(stages, list):
        errors.append("implementation_transition stages must be an array")
        stages = []
    stage_names: list[str] = []
    stage_owners: list[str] = []
    temporary_path_count = 0
    for index, stage in enumerate(stages, start=1):
        label = f"implementation_transition stages[{index}]"
        if not isinstance(stage, dict):
            errors.append(f"{label} must be an object")
            continue
        for field in ("name", "authoritative_owner"):
            if not isinstance(stage.get(field), str) or not stage[field].strip():
                errors.append(f"{label} requires {field}")
        if isinstance(stage.get("name"), str) and stage["name"].strip():
            stage_names.append(stage["name"].strip())
        if (
            isinstance(stage.get("authoritative_owner"), str)
            and stage["authoritative_owner"].strip()
        ):
            stage_owners.append(stage["authoritative_owner"].strip())
        temporary = stage.get("temporary_paths")
        if not isinstance(temporary, list) or any(
            not isinstance(item, str) or not item.strip() for item in temporary
        ):
            errors.append(f"{label} temporary_paths must be an array of text")
        else:
            temporary_path_count += len(temporary)
            if len(set(temporary)) != len(temporary):
                errors.append(f"{label} temporary_paths must be unique")
    if len(set(stage_names)) != len(stage_names):
        errors.append("implementation_transition stage names must be unique")

    coexistence = transition.get("coexistence_reason")
    retirement = transition.get("retirement_trigger")
    rollback = transition.get("rollback_boundary")
    for field, value in (
        ("coexistence_reason", coexistence),
        ("retirement_trigger", retirement),
        ("rollback_boundary", rollback),
    ):
        if value is not None and (not isinstance(value, str) or not value.strip()):
            errors.append(f"implementation_transition {field} must be text or null")

    if mode == "evolve-in-place":
        if superseded or stages or any(
            value is not None for value in (coexistence, retirement, rollback)
        ):
            errors.append("evolve-in-place cannot retain a parallel legacy path")
    elif mode == "replace-and-remove":
        if not superseded:
            errors.append("replace-and-remove requires superseded_paths")
        if stages or coexistence is not None:
            errors.append("replace-and-remove cannot declare staged coexistence")
        if not isinstance(retirement, str) or not retirement.strip():
            errors.append("replace-and-remove requires retirement_trigger")
    elif mode == "staged-migration":
        if not superseded:
            errors.append("staged-migration requires superseded_paths")
        if not isinstance(coexistence, str) or not coexistence.strip():
            errors.append("staged-migration requires coexistence_reason")
        if not stages or temporary_path_count == 0:
            errors.append("staged-migration requires stages with temporary_paths")
        if isinstance(owner, str) and owner.strip() not in stage_owners:
            errors.append("staged-migration stages must reach authoritative_owner")
        if not isinstance(retirement, str) or not retirement.strip():
            errors.append("staged-migration requires retirement_trigger")
        if not isinstance(rollback, str) or not rollback.strip():
            errors.append("staged-migration requires rollback_boundary")
    return errors


def solution_boundary_errors(
    root: Path,
    manifest: dict[str, Any],
    *,
    required: bool,
) -> tuple[dict[str, Any] | None, list[str]]:
    decisions = case_file(root, manifest["artifacts"]["decisions"])
    try:
        payload = extract_solution_boundary(decisions)
    except CaseError as exc:
        return None, [str(exc)]
    if payload is None:
        return None, (["decisions.md has no final solution-boundary block"] if required else [])
    errors = validate_solution_boundary(
        payload,
        planning_probe_present=solution_boundary_probe_present(root, manifest),
    )
    minimum_schema = minimum_solution_boundary_schema(root, manifest)
    if isinstance(payload.get("schema"), int) and payload["schema"] < minimum_schema:
        errors.append(
            f"solution boundary schema {payload['schema']} is below case minimum "
            f"{minimum_schema}"
        )
    return payload, errors


def role_context_fingerprint(payload: dict[str, Any]) -> str:
    """Hash a bounded role context without trusting its stored fingerprint."""
    encoded = json.dumps(
        {key: value for key, value in payload.items() if key != "fingerprint"},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def assurance_level(manifest: dict[str, Any]) -> str:
    """Return explicit assurance or preserve legacy cases as high assurance."""
    value = manifest.get("assurance_level")
    return value if value in ASSURANCE_LEVELS else "high"


def tracking_policy(manifest: dict[str, Any]) -> str:
    """Return explicit tracking or preserve legacy checklist-level tracking."""
    value = manifest.get("tracking")
    return value if value in TRACKING_POLICIES else "fine"


def projection_sync_policy(manifest: dict[str, Any]) -> str:
    """Return explicit projection cadence or preserve legacy per-block barriers."""
    value = manifest.get("projection_sync")
    return value if value in PROJECTION_SYNC_POLICIES else "per-block"


def bounded_recovery_binding(manifest: dict[str, Any]) -> dict[str, Any] | None:
    """Return a structurally plausible recovery binding, if present."""
    value = manifest.get("bounded_recovery")
    return value if isinstance(value, dict) else None


def active_bounded_recovery(manifest: dict[str, Any]) -> dict[str, Any] | None:
    """Return the active recovery binding without treating legacy cases as recovery cases."""
    binding = bounded_recovery_binding(manifest)
    return binding if binding is not None and binding.get("status") == "active" else None


def semantic_index_recovery_sha256(path: Path) -> str:
    """Hash semantic index meaning while excluding the carried-forward kernel revision."""
    payload = read_json(path)
    if not isinstance(payload, dict):
        raise CaseError(f"Semantic index must be an object: {path}")
    semantic_payload = {key: value for key, value in payload.items() if key != "kernel_revision"}
    encoded = json.dumps(
        semantic_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def recovery_plan_errors(
    payload: Any,
    *,
    case_id: str,
    block_ids: set[str],
) -> list[str]:
    """Validate the immutable, user-approved boundary for a frozen recovery run."""
    if not isinstance(payload, dict) or payload.get("schema") != RECOVERY_PLAN_SCHEMA:
        return ["recovery-plan.json has unsupported schema"]
    errors: list[str] = []
    if payload.get("case_id") != case_id:
        errors.append("recovery plan belongs to another case")
    if not isinstance(payload.get("reason"), str) or not payload["reason"].strip():
        errors.append("recovery plan requires a reason")
    if payload.get("requested_terminal_state") != "local-green":
        errors.append("recovery plan terminal state must be local-green")
    revision = payload.get("kernel_revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        errors.append("recovery plan has invalid kernel_revision")
    for field in ("kernel_sha256", "draft_sha256"):
        if not isinstance(payload.get(field), str) or not SHA256_RE.fullmatch(payload[field]):
            errors.append(f"recovery plan has invalid {field}")

    block_scopes = payload.get("block_scopes")
    if not isinstance(block_scopes, dict) or not block_scopes:
        errors.append("recovery plan requires non-empty block_scopes")
    else:
        unknown = sorted(set(block_scopes) - block_ids)
        if unknown:
            errors.append("recovery plan references unknown blocks: " + ", ".join(unknown))
        for block_id, scopes in block_scopes.items():
            if not BLOCK_ID_RE.fullmatch(str(block_id)):
                errors.append(f"recovery plan has invalid block id {block_id!r}")
                continue
            if (
                not isinstance(scopes, list)
                or not scopes
                or any(
                    not isinstance(item, str) or not RECOVERY_SCOPE_RE.fullmatch(item)
                    for item in scopes
                )
                or len(scopes) != len(set(scopes))
            ):
                errors.append(f"recovery plan {block_id} scopes must be unique stable ids")

    allowed_gates = payload.get("allowed_gates")
    if (
        not isinstance(allowed_gates, list)
        or not allowed_gates
        or any(item not in GATE_NAMES for item in allowed_gates)
        or len(allowed_gates) != len(set(allowed_gates))
    ):
        errors.append("recovery plan allowed_gates must be unique known gates")
    combine_final = payload.get("combine_final_review")
    if not isinstance(combine_final, bool):
        errors.append("recovery plan combine_final_review must be boolean")
    elif combine_final and isinstance(allowed_gates, list):
        missing = [gate for gate in RECOVERY_COMBINED_GATES if gate not in allowed_gates]
        if missing:
            errors.append(
                "combined recovery final review requires gates: " + ", ".join(missing)
            )
    if payload.get("new_findings_policy") != "user-decision":
        errors.append("recovery plan new_findings_policy must be user-decision")
    if payload.get("research") != "forbidden":
        errors.append("recovery plan research must be forbidden")
    if payload.get("content_mutation") != "forbidden":
        errors.append("recovery plan content_mutation must be forbidden")
    if payload.get("kernel_refresh") != "forbidden":
        errors.append("recovery plan kernel_refresh must be forbidden")
    if payload.get("max_agent_attempts_per_assignment") != 2:
        errors.append("recovery plan permits exactly two agent attempts per assignment")

    deferred = payload.get("deferred_findings", [])
    if not isinstance(deferred, list):
        errors.append("recovery plan deferred_findings must be an array")
    else:
        seen: set[str] = set()
        for item in deferred:
            if not isinstance(item, dict):
                errors.append("recovery plan deferred findings must be objects")
                continue
            finding_id = item.get("id")
            severity = item.get("severity")
            resolution = item.get("resolution")
            if not isinstance(finding_id, str) or not FINDING_ID_RE.fullmatch(finding_id):
                errors.append(f"recovery plan has invalid deferred finding {finding_id!r}")
                continue
            if finding_id in seen:
                errors.append(f"recovery plan duplicates deferred finding {finding_id}")
            seen.add(finding_id)
            if severity not in {"blocker", "major", "minor"}:
                errors.append(f"recovery plan {finding_id} has invalid severity")
            if resolution not in {"user-decision", "residual"}:
                errors.append(f"recovery plan {finding_id} has invalid resolution")
            if resolution == "residual" and severity != "minor":
                errors.append(f"recovery plan {finding_id} residual is allowed only for minor")
            if not isinstance(item.get("reason"), str) or not item["reason"].strip():
                errors.append(f"recovery plan {finding_id} requires a reason")
    return errors


def load_bounded_recovery(
    root: Path,
    manifest: dict[str, Any],
    ledger: dict[str, Any],
    *,
    require_active: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load and bind one immutable recovery plan."""
    binding = bounded_recovery_binding(manifest)
    if binding is None:
        raise CaseError("Case has no bounded recovery plan")
    if binding.get("status") not in RECOVERY_STATUSES:
        raise CaseError("Bounded recovery status is invalid")
    if require_active and binding.get("status") != "active":
        raise CaseError("Bounded recovery is not active")
    relative = binding.get("path")
    if relative != RECOVERY_PLAN_JSON:
        raise CaseError("Bounded recovery path is invalid")
    path = case_file(root, relative)
    if not path.is_file() or sha256(path) != binding.get("sha256"):
        raise CaseError("Bounded recovery plan is missing or changed")
    plan = read_json(path)
    errors = recovery_plan_errors(
        plan,
        case_id=str(manifest.get("case_id")),
        block_ids=set(blocks_by_id(ledger)),
    )
    if errors:
        raise CaseError("Invalid bounded recovery plan: " + "; ".join(errors))
    open_gates = recovery_required_gates(root, manifest, ledger)
    omitted_gates = [
        gate_name for gate_name in open_gates if gate_name not in plan["allowed_gates"]
    ]
    if omitted_gates:
        raise CaseError(
            "Recovery plan omits gates requiring recovery: "
            + ", ".join(omitted_gates)
        )
    return binding, plan


def recovery_gate_freshness_errors(
    root: Path,
    manifest: dict[str, Any],
    ledger: dict[str, Any],
    gate_name: str,
) -> list[str]:
    """Return status or evidence drift that a recovery plan must explicitly cover."""
    gate = manifest.get("gates", {}).get(gate_name, {})
    status = gate.get("status")
    if status == "not_required":
        return []
    if status != "pass":
        return [f"status is {status or 'missing'}"]
    evidence = gate.get("evidence")
    if not isinstance(evidence, str) or not evidence:
        return ["passed gate has no evidence"]
    path = case_file(root, evidence)
    errors: list[str] = []
    if not artifact_ready(path):
        errors.append("evidence is incomplete")
    elif sha256(path) != gate.get("evidence_sha256"):
        errors.append("evidence changed after pass")
    if gate_subject_hash(root, manifest, ledger, gate_name) != gate.get(
        "subject_sha256"
    ):
        errors.append("subject changed after pass")
    return errors


def recovery_required_gates(
    root: Path,
    manifest: dict[str, Any],
    ledger: dict[str, Any],
) -> list[str]:
    """List non-terminal and stale-pass gates that recovery must declare."""
    return [
        gate_name
        for gate_name in GATE_NAMES
        if recovery_gate_freshness_errors(root, manifest, ledger, gate_name)
    ]


def runtime_automation_plan(
    automation_plan: dict[str, Any] | None,
    policy: str,
) -> dict[str, Any] | None:
    """Project a detailed planning estimate into the selected runtime tracking."""
    if automation_plan is None:
        return None
    if policy == "fine":
        return automation_plan
    projected = {
        key: value
        for key, value in automation_plan.items()
        if key not in {"stages", "fingerprint"}
    }
    projected["stages"] = []
    stages = [stage for stage in automation_plan.get("stages", []) if isinstance(stage, dict)]
    stage_by_id = {
        stage["id"]: stage
        for stage in stages
        if isinstance(stage.get("id"), str)
    }
    user_stage_ids = {
        stage["id"]
        for stage in stages
        if isinstance(stage.get("id"), str)
        and any(
            isinstance(item, dict) and item.get("completion_owner") == "user"
            for item in stage.get("checklist", [])
        )
    }

    def inherited_user_dependencies(stage_id: str) -> list[str]:
        found: set[str] = set()
        pending = list(stage_by_id.get(stage_id, {}).get("depends_on", []))
        while pending:
            dependency = pending.pop()
            if dependency in found:
                continue
            if dependency in user_stage_ids:
                found.add(dependency)
            else:
                pending.extend(stage_by_id.get(dependency, {}).get("depends_on", []))
        return sorted(found)

    for stage in automation_plan.get("stages", []):
        if not isinstance(stage, dict):
            continue
        user_gates = [
            item
            for item in stage.get("checklist", [])
            if isinstance(item, dict) and item.get("completion_owner") == "user"
        ]
        if policy == "off" and not user_gates:
            continue
        checklist = user_gates if policy == "off" else [
            {
                "id": f"{stage['id']}-MILESTONE",
                "text": f"Complete milestone: {stage['title']}",
                "required": True,
                "done_when": "Stage result and evidence are recorded",
                "completion_owner": "agent",
            },
            *user_gates,
        ]
        projected["stages"].append(
            {
                **{key: value for key, value in stage.items() if key != "checklist"},
                **(
                    {"depends_on": inherited_user_dependencies(stage["id"])}
                    if policy == "off"
                    else {}
                ),
                "checklist": checklist,
            }
        )
    from automation_timing import canonical_fingerprint

    projected["fingerprint"] = canonical_fingerprint(projected)
    return projected


def role_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    """Project the coordinator manifest without timing-derived fields."""
    planning = manifest.get("planning_handoff")
    planning_context = None
    if isinstance(planning, dict):
        planning_context = {
            "planning_case_id": planning.get("planning_case_id"),
            "planning_revision": planning.get("planning_revision"),
            "project_root": planning.get("project_root"),
            "role_context_path": planning.get("role_context_path"),
            "role_context_fingerprint": planning.get("role_context_fingerprint"),
        }
    artifacts = manifest.get("artifacts", {})
    allowed_artifacts = (
        "planning_role_context",
        "working_projection",
        "project_conformance_contract",
        "recovery_plan",
        "evidence",
        "decisions",
        "draft",
        "integration_review",
        "global_review",
        "project_conformance",
        "architecture_conformance",
        "consistency_report",
    )
    result: dict[str, Any] = {
        "schema": ROLE_MANIFEST_SCHEMA,
        "case_id": manifest.get("case_id"),
        "mode": manifest.get("mode"),
        "intent": manifest.get("intent"),
        "profile_id": manifest.get("profile_id"),
        "route_id": manifest.get("route_id"),
        "project_root": manifest.get("project_root"),
        "mode_decision": manifest.get("mode_decision"),
        "method_context": manifest.get("method_context"),
        "project_conformance_contract": manifest.get("project_conformance_contract"),
        "planning_context": planning_context,
        "kernel": manifest.get("kernel"),
        "artifacts": {
            key: artifacts.get(key)
            for key in allowed_artifacts
            if artifacts.get(key) is not None
        },
        "gates": manifest.get("gates"),
        "timing_visibility": "excluded",
    }
    if "assurance_level" in manifest:
        result.update(
            assurance_level=assurance_level(manifest),
            review_strategy=REVIEW_STRATEGIES[assurance_level(manifest)],
            tracking=tracking_policy(manifest),
            projection_sync=projection_sync_policy(manifest),
        )
    if isinstance(manifest.get("bounded_recovery"), dict):
        result["bounded_recovery"] = manifest["bounded_recovery"]
    encoded = json.dumps(
        result,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    result["fingerprint"] = hashlib.sha256(encoded).hexdigest()
    return result


def validate_working_projection_state(payload: Any) -> list[str]:
    """Validate the visible working-draft linkage and read-back ledger."""
    errors: list[str] = []
    if not isinstance(payload, dict) or payload.get("schema") != WORKING_PROJECTION_SCHEMA:
        return ["working-projection.json has unsupported schema"]
    policy = payload.get("policy")
    if policy not in {"required", "optional", "disabled"}:
        errors.append("working projection policy is invalid")
    targets = payload.get("targets")
    if not isinstance(targets, list):
        return [*errors, "working projection targets must be an array"]
    target_ids: set[str] = set()
    for target in targets:
        if not isinstance(target, dict):
            errors.append("working projection targets must be objects")
            continue
        target_id = target.get("target_id")
        if not isinstance(target_id, str) or not TARGET_ID_RE.fullmatch(target_id):
            errors.append(f"invalid working projection target id: {target_id!r}")
            continue
        if target_id in target_ids:
            errors.append(f"duplicate working projection target: {target_id}")
        target_ids.add(target_id)
        for field in ("system", "object_id", "read_back_at"):
            if not isinstance(target.get(field), str) or not target[field].strip():
                errors.append(f"{target_id}: missing {field}")
        if target.get("evidence_kind") not in PROJECTION_EVIDENCE_KINDS:
            errors.append(f"{target_id}: invalid evidence_kind")
    if policy == "required" and not target_ids:
        errors.append("required working projection has no targets")
    if policy == "disabled" and target_ids:
        errors.append("disabled working projection has targets")

    updates = payload.get("updates")
    if not isinstance(updates, list):
        return [*errors, "working projection updates must be an array"]
    previous_key_by_target: dict[str, tuple[str, str, str, str]] = {}
    for update in updates:
        if not isinstance(update, dict):
            errors.append("working projection updates must be objects")
            continue
        target_id = update.get("target_id")
        if target_id not in target_ids:
            errors.append(f"working projection update references unknown target {target_id!r}")
        for field in ("source", "read_back_at", "evidence_ref"):
            if not isinstance(update.get(field), str) or not update[field].strip():
                errors.append(f"working projection update {target_id}: missing {field}")
        source = update.get("source")
        if not isinstance(source, str) or not (
            BLOCK_ID_RE.fullmatch(source) or source in {"draft", "integration"}
        ):
            errors.append(f"working projection update {target_id}: invalid source")
        source_hash = update.get("source_sha256")
        if not isinstance(source_hash, str) or not SHA256_RE.fullmatch(source_hash):
            errors.append(f"working projection update {target_id}: invalid source_sha256")
        content_hash = update.get("content_sha256")
        if not isinstance(content_hash, str) or not SHA256_RE.fullmatch(content_hash):
            errors.append(f"working projection update {target_id}: invalid content_sha256")
        evidence_kind = update.get("evidence_kind")
        if evidence_kind not in PROJECTION_EVIDENCE_KINDS:
            errors.append(f"working projection update {target_id}: invalid evidence_kind")
        evidence_hash = update.get("evidence_sha256")
        if not isinstance(evidence_hash, str) or not SHA256_RE.fullmatch(evidence_hash):
            errors.append(f"working projection update {target_id}: invalid evidence_sha256")
        key = (
            str(target_id),
            str(update.get("source")),
            str(source_hash),
            str(content_hash),
        )
        if previous_key_by_target.get(str(target_id)) == key:
            errors.append(f"duplicate working projection update: {target_id}/{update.get('source')}")
        previous_key_by_target[str(target_id)] = key
        bindings = update.get("source_bindings", [])
        if not isinstance(bindings, list):
            errors.append(f"working projection update {target_id}: source_bindings must be an array")
            continue
        seen_bindings: set[tuple[str, str]] = set()
        for binding in bindings:
            if not isinstance(binding, dict):
                errors.append(f"working projection update {target_id}: source binding must be an object")
                continue
            binding_source = binding.get("source")
            binding_hash = binding.get("source_sha256")
            bound_at = binding.get("bound_at")
            if not isinstance(binding_source, str) or not (
                BLOCK_ID_RE.fullmatch(binding_source)
                or binding_source in {"draft", "integration"}
            ):
                errors.append(f"working projection update {target_id}: invalid bound source")
            if not isinstance(binding_hash, str) or not SHA256_RE.fullmatch(binding_hash):
                errors.append(f"working projection update {target_id}: invalid bound source hash")
            if not isinstance(bound_at, str) or not bound_at.strip():
                errors.append(f"working projection update {target_id}: invalid bound_at")
            binding_key = (str(binding_source), str(binding_hash))
            if binding_key in seen_bindings:
                errors.append(f"working projection update {target_id}: duplicate source binding")
            seen_bindings.add(binding_key)
    return errors


def working_projection_targets(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Index projection targets by stable planning target id."""
    return {
        item["target_id"]: item
        for item in payload.get("targets", [])
        if isinstance(item, dict) and isinstance(item.get("target_id"), str)
    }


def projection_local_file(
    root: Path,
    manifest: dict[str, Any],
    target: dict[str, Any],
    evidence_ref: str,
) -> Path:
    """Resolve the exact visible project file declared by the projection target."""
    project_root_raw = manifest.get("project_root")
    project_root = (
        Path(project_root_raw).expanduser().resolve()
        if isinstance(project_root_raw, str) and project_root_raw.strip()
        else None
    )
    object_id = target.get("object_id")
    if not isinstance(object_id, str) or not object_id.strip():
        raise CaseError("Local projection target has no object_id path")
    declared = Path(object_id).expanduser()
    if declared.is_absolute():
        expected = declared.resolve()
    elif project_root is not None:
        expected = (project_root / declared).resolve()
    else:
        raise CaseError(
            "Relative local projection target requires a bound project root"
        )
    raw_evidence = Path(evidence_ref).expanduser()
    if raw_evidence.is_absolute():
        candidate = raw_evidence.resolve()
    elif project_root is not None:
        candidate = (project_root / raw_evidence).resolve()
    else:
        raise CaseError("Relative local projection evidence requires a bound project root")
    if candidate != expected:
        raise CaseError("Local projection evidence does not match target object_id")
    runtime_root = root.resolve()
    if candidate == runtime_root or runtime_root in candidate.parents:
        raise CaseError("Hidden runtime case cannot be a visible local projection")
    if project_root is not None and not (
        candidate == project_root or project_root in candidate.parents
    ):
        raise CaseError("Local projection target escapes the bound project root")
    if not candidate.is_file():
        raise CaseError(f"Local projection read-back file is missing: {evidence_ref}")
    return candidate


def external_readback_receipt(
    root: Path,
    target: dict[str, Any],
    *,
    evidence_ref: str,
    content_sha256: str,
    read_back_at: str,
) -> tuple[Path, dict[str, Any]]:
    """Validate one persisted receipt produced by an external project adapter."""
    receipt_path = case_file(root, evidence_ref)
    receipt = read_json(receipt_path)
    if not isinstance(receipt, dict):
        raise CaseError("External read-back receipt must be a JSON object")
    expected = {
        "schema": EXTERNAL_READBACK_RECEIPT_SCHEMA,
        "kind": "external_readback",
        "target_id": target.get("target_id"),
        "system": target.get("system"),
        "object_id": target.get("object_id"),
        "read_back_at": read_back_at,
        "content_sha256": content_sha256,
    }
    mismatches = [field for field, value in expected.items() if receipt.get(field) != value]
    if mismatches:
        raise CaseError(
            "External read-back receipt does not match the projection update: "
            + ", ".join(mismatches)
        )
    if not isinstance(receipt.get("adapter"), str) or not receipt["adapter"].strip():
        raise CaseError("External read-back receipt must name the project adapter")
    response_fingerprint = receipt.get("response_fingerprint")
    if not isinstance(response_fingerprint, str) or not SHA256_RE.fullmatch(
        response_fingerprint
    ):
        raise CaseError("External read-back receipt has invalid response_fingerprint")
    return receipt_path, receipt


def projection_evidence_sha256(
    root: Path,
    manifest: dict[str, Any],
    target: dict[str, Any],
    *,
    evidence_kind: str,
    evidence_ref: str,
    content_sha256: str,
    read_back_at: str,
) -> str:
    """Verify read-back evidence and return the evidence artifact hash."""
    if target.get("evidence_kind") != evidence_kind:
        raise CaseError(
            "Projection evidence kind does not match the declared target contract"
        )
    if evidence_kind == "local_file":
        evidence_path = projection_local_file(root, manifest, target, evidence_ref)
        evidence_hash = sha256(evidence_path)
        if evidence_hash != content_sha256:
            raise CaseError("Local projection content hash does not match read-back file")
        return evidence_hash
    if evidence_kind == "external_readback":
        evidence_path, _ = external_readback_receipt(
            root,
            target,
            evidence_ref=evidence_ref,
            content_sha256=content_sha256,
            read_back_at=read_back_at,
        )
        return sha256(evidence_path)
    raise CaseError(f"Unknown projection evidence kind: {evidence_kind}")


def projection_evidence_errors(
    root: Path,
    manifest: dict[str, Any],
    payload: dict[str, Any],
) -> list[str]:
    """Detect missing or changed read-back evidence after an update was recorded."""
    errors: list[str] = []
    targets = working_projection_targets(payload)
    updates = payload.get("updates", [])
    latest_local_index: dict[str, int] = {}
    for index, update in enumerate(updates):
        if (
            isinstance(update, dict)
            and update.get("evidence_kind") == "local_file"
            and isinstance(update.get("target_id"), str)
        ):
            latest_local_index[update["target_id"]] = index
    for index, update in enumerate(updates):
        if not isinstance(update, dict):
            continue
        if (
            update.get("evidence_kind") == "local_file"
            and latest_local_index.get(str(update.get("target_id"))) != index
        ):
            continue
        target = targets.get(update.get("target_id"))
        if target is None:
            continue
        try:
            evidence_hash = projection_evidence_sha256(
                root,
                manifest,
                target,
                evidence_kind=str(update.get("evidence_kind")),
                evidence_ref=str(update.get("evidence_ref")),
                content_sha256=str(update.get("content_sha256")),
                read_back_at=str(update.get("read_back_at")),
            )
        except CaseError as exc:
            errors.append(
                f"{update.get('target_id')}/{update.get('source')}: {exc}"
            )
            continue
        if evidence_hash != update.get("evidence_sha256"):
            errors.append(
                f"{update.get('target_id')}/{update.get('source')}: "
                "projection evidence changed after read-back"
            )
    return errors


def projection_update_sources(payload: dict[str, Any], target_id: str) -> dict[str, str]:
    """Return the latest recorded subject hash for each projected source."""
    result: dict[str, str] = {}
    for item in payload.get("updates", []):
        if not isinstance(item, dict) or item.get("target_id") != target_id:
            continue
        if isinstance(item.get("source"), str) and isinstance(item.get("source_sha256"), str):
            result[item["source"]] = item["source_sha256"]
        for binding in item.get("source_bindings", []):
            if (
                isinstance(binding, dict)
                and isinstance(binding.get("source"), str)
                and isinstance(binding.get("source_sha256"), str)
            ):
                result[binding["source"]] = binding["source_sha256"]
    return result


def working_projection_errors(
    root: Path,
    manifest: dict[str, Any],
    ledger: dict[str, Any],
    *,
    require_any_update: bool,
    exclude_sources: set[str] | None = None,
) -> list[str]:
    """Return visibility gaps for required projections and reviewed blocks."""
    relative = manifest.get("artifacts", {}).get("working_projection")
    if not isinstance(relative, str):
        return []
    try:
        payload = read_json(case_file(root, relative))
    except CaseError as exc:
        return [str(exc)]
    errors = validate_working_projection_state(payload)
    if not errors:
        errors.extend(projection_evidence_errors(root, manifest, payload))
    if errors or payload.get("policy") == "disabled" or not payload.get("targets"):
        return errors
    target_ids = [
        item.get("target_id")
        for item in payload.get("targets", [])
        if isinstance(item, dict) and isinstance(item.get("target_id"), str)
    ]
    required_document_source = None
    expected_document_hash = None
    if require_any_update:
        required_document_source = (
            "draft" if manifest.get("mode") == "compact" else "integration"
        )
        draft_relative = manifest.get("artifacts", {}).get("draft")
        if isinstance(draft_relative, str):
            draft_path = case_file(root, draft_relative)
            if artifact_ready(draft_path):
                expected_document_hash = sha256(draft_path)
    for target_id in target_ids:
        sources = projection_update_sources(payload, target_id)
        if require_any_update and not sources:
            errors.append(f"{target_id}: working projection has no read-back update")
        if (
            required_document_source is not None
            and expected_document_hash is not None
            and sources.get(required_document_source) != expected_document_hash
        ):
            errors.append(
                f"{target_id}: working projection has no current "
                f"{required_document_source} read-back"
            )
        if projection_sync_policy(manifest) != "per-block":
            continue
        for block in ledger.get("blocks", []):
            if block.get("status") not in {"reviewed", "integrated"}:
                continue
            block_id = block.get("id")
            if block_id in (exclude_sources or set()):
                continue
            if block_id not in sources:
                errors.append(
                    f"{target_id}: reviewed block {block_id} is absent from working projection"
                )
            elif sources[block_id] != block.get("artifact_sha256"):
                errors.append(
                    f"{target_id}: reviewed block {block_id} has a stale working projection"
                )
    return errors


def load_project_conformance_contract(
    root: Path,
    manifest: dict[str, Any],
) -> tuple[dict[str, Any] | None, list[str]]:
    """Load the immutable project document contract pinned at case init."""
    binding = manifest.get("project_conformance_contract")
    if binding is None:
        return None, []
    if not isinstance(binding, dict):
        return None, ["project conformance contract binding must be an object"]
    relative = binding.get("path")
    if relative != PROJECT_CONFORMANCE_CONTRACT_JSON:
        return None, ["project conformance contract path is invalid"]
    path = case_file(root, relative)
    if not path.is_file():
        return None, ["project conformance contract file is missing"]
    if sha256(path) != binding.get("sha256"):
        return None, ["project conformance contract changed after case init"]
    try:
        payload = read_json(path)
    except CaseError as exc:
        return None, [str(exc)]
    errors = validate_contract(payload)
    if payload.get("profile_id") != manifest.get("profile_id"):
        errors.append("project conformance contract profile_id mismatch")
    return payload, errors


def project_conformance_documents(
    root: Path,
    manifest: dict[str, Any],
    contract: dict[str, Any],
) -> tuple[list[tuple[str, Path]], list[str]]:
    """Resolve the case and visible documents selected by the pinned contract."""
    documents: list[tuple[str, Path]] = []
    errors: list[str] = []
    checks = set(contract.get("checks", []))
    if "draft" in checks:
        draft_relative = manifest.get("artifacts", {}).get("draft")
        if not isinstance(draft_relative, str):
            errors.append("document contract requires draft but manifest has none")
        else:
            documents.append(("draft", case_file(root, draft_relative)))

    if "working_projection" in checks:
        projection_relative = manifest.get("artifacts", {}).get("working_projection")
        if not isinstance(projection_relative, str):
            errors.append("document contract requires working projection but manifest has none")
        else:
            try:
                projection = read_json(case_file(root, projection_relative))
            except CaseError as exc:
                errors.append(str(exc))
                projection = {}
            local_count = 0
            for target in projection.get("targets", []):
                if not isinstance(target, dict) or target.get("evidence_kind") != "local_file":
                    continue
                target_id = str(target.get("target_id", "unknown"))
                object_id = target.get("object_id")
                if not isinstance(object_id, str) or not object_id.strip():
                    errors.append(f"{target_id}: local projection has no object_id")
                    continue
                try:
                    path = projection_local_file(root, manifest, target, object_id)
                except CaseError as exc:
                    errors.append(f"{target_id}: {exc}")
                    continue
                documents.append((f"working_projection:{target_id}", path))
                local_count += 1
            if local_count == 0:
                errors.append(
                    "document contract requires at least one local_file working projection"
                )
    return documents, errors


def project_conformance_errors(
    root: Path,
    manifest: dict[str, Any],
) -> list[str]:
    """Run deterministic profile-owned checks over the declared documents."""
    contract, errors = load_project_conformance_contract(root, manifest)
    if contract is None or errors:
        return errors
    documents, resolution_errors = project_conformance_documents(root, manifest, contract)
    errors.extend(resolution_errors)
    seen: set[Path] = set()
    for label, path in documents:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        errors.extend(validate_markdown_file(path, contract, label=label))
    return errors


def project_conformance_review_freshness_errors(
    root: Path,
    manifest: dict[str, Any],
    evidence_path: Path,
) -> list[str]:
    """Reject a review report older than the subject or its latest read-back."""
    contract, errors = load_project_conformance_contract(root, manifest)
    if contract is None or errors:
        return errors
    documents, resolution_errors = project_conformance_documents(root, manifest, contract)
    errors.extend(resolution_errors)
    watched = [path for _, path in documents]
    # working-projection.json is a runtime ledger. Its mtime can change when a
    # source is bound to an unchanged read-back, so freshness follows the actual
    # draft/visible documents resolved above rather than ledger bookkeeping.
    if errors:
        return errors
    try:
        evidence_mtime = evidence_path.stat().st_mtime_ns
    except OSError as exc:
        return [f"cannot stat project-conformance evidence: {exc}"]
    newest_path: Path | None = None
    newest_mtime = -1
    for path in watched:
        try:
            modified = path.stat().st_mtime_ns
        except OSError as exc:
            errors.append(f"cannot stat project-conformance subject {path}: {exc}")
            continue
        if modified > newest_mtime:
            newest_mtime = modified
            newest_path = path
    if not errors and evidence_mtime < newest_mtime:
        label = newest_path.name if newest_path is not None else "subject"
        errors.append(
            "project-conformance evidence is older than the current document/read-back "
            f"subject ({label}); run a fresh review"
        )
    return errors


def initial_gates(mode: str, assurance: str) -> dict[str, dict[str, Any]]:
    """Create gates from independent scale and assurance decisions."""
    gates = {
        name: {
            "status": "pending",
            "evidence": None,
            "evidence_sha256": None,
            "subject_sha256": None,
            "note": None,
        }
        for name in GATE_NAMES
    }
    if mode == "compact":
        gates["semantic_integration"]["status"] = "not_required"
        gates["integration_review"]["status"] = "not_required"
    elif assurance != "high":
        gates["integration_review"].update(
            status="not_required",
            note="covered by the combined final review",
        )
    if assurance == "lite":
        gates["global_review"].update(
            status="not_required",
            note="machine-first lite assurance; semantic change escalates to standard",
        )
        gates["project_conformance"].update(
            status="not_required",
            note="editorial lite assurance uses deterministic project checks",
        )
    return gates


def required_gates(manifest: dict[str, Any]) -> set[str]:
    """Return gates that policy never permits callers to waive manually."""
    required = {
        name
        for name, gate in initial_gates(
            str(manifest.get("mode")),
            assurance_level(manifest),
        ).items()
        if gate["status"] != "not_required"
        and name not in {"architecture_design", "architecture_conformance"}
    }
    if (
        manifest.get("profile_id") == "generic"
        and manifest.get("project_conformance_contract") is None
    ):
        required.discard("project_conformance")
    return required


def init_case(
    root: Path,
    *,
    case_id: str,
    mode: str,
    intent: str,
    profile_id: str,
    route_id: str,
    project_root: str | None,
    document_contract: dict[str, Any] | None = None,
    assurance: str | None = None,
    tracking: str | None = None,
    projection_sync: str | None = None,
    allow_unrecorded_mode: bool = False,
    allow_unrecorded_method: bool = False,
    allow_unplanned: bool = False,
) -> None:
    """Create a new case package."""
    if not CASE_ID_RE.fullmatch(case_id):
        raise CaseError(f"Invalid case id: {case_id!r}")
    if mode not in {"compact", "block"}:
        raise CaseError(f"Invalid mode: {mode}")
    if document_contract is not None:
        contract_errors = validate_contract(document_contract)
        if contract_errors:
            raise CaseError("Invalid project document contract: " + "; ".join(contract_errors))
        if document_contract.get("profile_id") != profile_id:
            raise CaseError("Project document contract belongs to another profile")

    root = root.expanduser().resolve()
    manifest_path = root / "manifest.json"
    if manifest_path.exists():
        raise CaseError(f"Case already exists: {manifest_path}")
    existing_entries = list(root.iterdir()) if root.exists() else []
    allowed_preinit_entries = {
        MODE_DECISION_FILENAME,
        METHOD_CONTEXT_JSON,
        METHOD_CONTEXT_MARKDOWN,
        PLANNING_HANDOFF_JSON,
        PLANNING_HANDOFF_MARKDOWN,
    }
    unexpected_entries = [
        entry for entry in existing_entries if entry.name not in allowed_preinit_entries
    ]
    if unexpected_entries:
        raise CaseError(f"Refusing to initialize a non-empty directory: {root}")

    decision_binding: dict[str, str] | None = None
    decision_payload: dict[str, Any] | None = None
    decision_path = root / MODE_DECISION_FILENAME
    if decision_path.exists() or decision_path.is_symlink():
        resolved_decision_path = case_file(root, MODE_DECISION_FILENAME)
        if not resolved_decision_path.is_file():
            raise CaseError(f"Mode decision is not a readable file: {decision_path}")
        decision_payload = read_json(resolved_decision_path)
        try:
            validate_mode_decision(
                decision_payload,
                expected_mode=mode,
                expected_profile_id=profile_id,
            )
        except ModeDecisionError as exc:
            raise CaseError(f"Invalid mode decision: {exc}") from exc
        decision_binding = {
            "path": MODE_DECISION_FILENAME,
            "fingerprint": decision_payload["fingerprint"],
        }
    elif not allow_unrecorded_mode:
        raise CaseError(
            f"Missing {MODE_DECISION_FILENAME}; run spec_pipeline.py suggest-mode first"
        )

    if decision_payload is not None and "selected_assurance" in decision_payload:
        decided_assurance = decision_payload["selected_assurance"]
        decided_tracking = decision_payload["selected_tracking"]
        decided_projection_sync = decision_payload["selected_projection_sync"]
    else:
        # Missing fields identify a legacy decision and retain the previous,
        # deliberately expensive semantics.
        decided_assurance = "high"
        decided_tracking = "fine"
        decided_projection_sync = "per-block"
    selected_assurance = assurance or decided_assurance
    selected_tracking = tracking or decided_tracking
    selected_projection_sync = projection_sync or decided_projection_sync
    if selected_assurance not in ASSURANCE_LEVELS:
        raise CaseError(f"Invalid assurance level: {selected_assurance!r}")
    if selected_tracking not in TRACKING_POLICIES:
        raise CaseError(f"Invalid tracking policy: {selected_tracking!r}")
    if selected_projection_sync not in PROJECTION_SYNC_POLICIES:
        raise CaseError(f"Invalid projection sync: {selected_projection_sync!r}")
    if decision_payload is not None and "selected_assurance" in decision_payload:
        mismatches = [
            label
            for label, actual, expected in (
                ("assurance", selected_assurance, decided_assurance),
                ("tracking", selected_tracking, decided_tracking),
                ("projection sync", selected_projection_sync, decided_projection_sync),
            )
            if actual != expected
        ]
        if mismatches:
            raise CaseError(
                "Case runtime overrides conflict with mode decision: " + ", ".join(mismatches)
            )

    method_binding: dict[str, str] | None = None
    method_metadata_path = root / METHOD_CONTEXT_JSON
    method_content_path = root / METHOD_CONTEXT_MARKDOWN
    method_entries_exist = (
        method_metadata_path.exists() or method_metadata_path.is_symlink(),
        method_content_path.exists() or method_content_path.is_symlink(),
    )
    if any(method_entries_exist) and not all(method_entries_exist):
        raise CaseError("Method context requires both Markdown and JSON artifacts")
    if all(method_entries_exist):
        resolved_metadata_path = case_file(root, METHOD_CONTEXT_JSON)
        resolved_content_path = case_file(root, METHOD_CONTEXT_MARKDOWN)
        if not resolved_metadata_path.is_file() or not resolved_content_path.is_file():
            raise CaseError("Method context artifacts must be readable files")
        method_payload = read_json(resolved_metadata_path)
        method_markdown = resolved_content_path.read_text(encoding="utf-8")
        try:
            validate_method_context(
                method_payload,
                method_markdown,
                expected_route_id=route_id,
                verify_sources=True,
            )
        except RouterError as exc:
            raise CaseError(f"Invalid method context: {exc}") from exc
        method_binding = {
            "metadata_path": METHOD_CONTEXT_JSON,
            "content_path": METHOD_CONTEXT_MARKDOWN,
            "fingerprint": method_payload["fingerprint"],
            "content_sha256": method_payload["content_sha256"],
        }
    elif not allow_unrecorded_method:
        raise CaseError(
            f"Missing {METHOD_CONTEXT_JSON} and {METHOD_CONTEXT_MARKDOWN}; "
            "run vigers_context.py materialize first"
        )

    planning_binding: dict[str, str | int] | None = None
    planning_payload: dict[str, Any] | None = None
    planning_metadata_path = root / PLANNING_HANDOFF_JSON
    planning_content_path = root / PLANNING_HANDOFF_MARKDOWN
    planning_entries_exist = (
        planning_metadata_path.exists() or planning_metadata_path.is_symlink(),
        planning_content_path.exists() or planning_content_path.is_symlink(),
    )
    if any(planning_entries_exist) and not all(planning_entries_exist):
        raise CaseError("Planning handoff requires both Markdown and JSON artifacts")
    if all(planning_entries_exist):
        resolved_metadata_path = case_file(root, PLANNING_HANDOFF_JSON)
        resolved_content_path = case_file(root, PLANNING_HANDOFF_MARKDOWN)
        if not resolved_metadata_path.is_file() or not resolved_content_path.is_file():
            raise CaseError("Planning handoff artifacts must be readable files")
        planning_payload = read_json(resolved_metadata_path)
        planning_markdown = resolved_content_path.read_text(encoding="utf-8")
        try:
            validate_planning_handoff(
                planning_payload,
                planning_markdown,
                expected_profile_id=profile_id,
                expected_project_root=project_root,
                enforce_project_root=True,
            )
        except PlanningError as exc:
            raise CaseError(f"Invalid planning handoff: {exc}") from exc
        planning_binding = {
            "metadata_path": PLANNING_HANDOFF_JSON,
            "content_path": PLANNING_HANDOFF_MARKDOWN,
            "planning_case_id": planning_payload["planning_case_id"],
            "planning_revision": planning_payload["planning_revision"],
            "project_root": planning_payload["project_root"],
            "fingerprint": planning_payload["fingerprint"],
            "content_sha256": planning_payload["content_sha256"],
        }
        role_context_payload = planning_role_context(planning_payload)
        atomic_json(root / PLANNING_ROLE_CONTEXT_JSON, role_context_payload)
        planning_binding["role_context_path"] = PLANNING_ROLE_CONTEXT_JSON
        planning_binding["role_context_fingerprint"] = role_context_payload["fingerprint"]
    elif intent != "review" and not allow_unplanned:
        raise CaseError(
            f"Missing {PLANNING_HANDOFF_JSON} and {PLANNING_HANDOFF_MARKDOWN}; "
            "complete and approve planning_case.py before Vigers init"
        )

    working_projection = (
        planning_payload.get("working_projection")
        if isinstance(planning_payload, dict)
        else None
    )
    if not isinstance(working_projection, dict):
        working_projection = {
            "policy": "disabled" if intent == "review" else "optional",
            "targets": [],
        }
    projection_state = {
        "schema": WORKING_PROJECTION_SCHEMA,
        "policy": working_projection.get("policy", "optional"),
        "targets": working_projection.get("targets", []),
        "updates": [],
    }
    projection_errors = validate_working_projection_state(projection_state)
    if projection_errors:
        raise CaseError("Invalid working projection handoff: " + "; ".join(projection_errors))

    (root / "blocks").mkdir(parents=True, exist_ok=True)
    (root / "reviews").mkdir(parents=True, exist_ok=True)
    contract_binding: dict[str, str] | None = None
    if document_contract is not None:
        contract_path = root / PROJECT_CONFORMANCE_CONTRACT_JSON
        atomic_json(contract_path, document_contract)
        contract_binding = {
            "path": PROJECT_CONFORMANCE_CONTRACT_JSON,
            "sha256": sha256(contract_path),
        }
    write_template(
        root / "kernel.md",
        "# Kernel\n\n"
        "## Goal\n\nVIGERS_TODO\n\n"
        "## Scope\n\nVIGERS_TODO\n\n"
        "## Shared vocabulary and invariants\n\nVIGERS_TODO\n\n"
        "## Confirmed decisions\n\nVIGERS_TODO\n\n"
        "## Global constraints\n\nVIGERS_TODO\n\n"
        "## Open decisions\n\nVIGERS_TODO\n",
    )
    write_template(root / "evidence.md", "# Evidence pack\n\nVIGERS_TODO\n")
    write_template(root / "decisions.md", "# Decision log\n\nVIGERS_TODO\n")
    write_template(root / "draft.md", "# Integrated draft\n\nVIGERS_TODO\n")
    write_template(root / "reviews" / "integration.md", "# Integration review\n\nVIGERS_TODO\n")
    write_template(root / "reviews" / "global.md", "# Global review\n\nVIGERS_TODO\n")
    write_template(
        root / "reviews" / "project.md",
        "# Project conformance\n\nVIGERS_TODO\n",
    )
    write_template(
        root / "reviews" / "architecture.md",
        "# Architecture conformance\n\nVIGERS_TODO\n",
    )
    atomic_json(root / WORKING_PROJECTION_JSON, projection_state)

    manifest = {
        "schema": SCHEMA_VERSION,
        "case_id": case_id,
        "mode": mode,
        "assurance_level": selected_assurance,
        "tracking": selected_tracking,
        "projection_sync": selected_projection_sync,
        "intent": intent,
        "profile_id": profile_id,
        "route_id": route_id,
        "project_root": project_root,
        "mode_decision": decision_binding,
        "method_context": method_binding,
        "project_conformance_contract": contract_binding,
        "planning_handoff": planning_binding,
        **(
            {"execution_preferences": dict(planning_payload["execution_preferences"])}
            if isinstance((planning_payload or {}).get("execution_preferences"), dict)
            else {}
        ),
        "created_at": now_utc(),
        "updated_at": now_utc(),
        "kernel": {
            "path": "kernel.md",
            "revision": 1,
            "sha256": sha256(root / "kernel.md"),
        },
        "artifacts": {
            "automation_timing": AUTOMATION_TIMING_FILENAME,
            "agent_ledger": AGENT_LEDGER_JSON,
            "role_manifest": ROLE_MANIFEST_JSON,
            "planning_role_context": (
                PLANNING_ROLE_CONTEXT_JSON if planning_binding is not None else None
            ),
            "working_projection": WORKING_PROJECTION_JSON,
            "project_conformance_contract": (
                PROJECT_CONFORMANCE_CONTRACT_JSON if contract_binding is not None else None
            ),
            "evidence": "evidence.md",
            "decisions": "decisions.md",
            "draft": "draft.md",
            "integration_review": "reviews/integration.md",
            "global_review": "reviews/global.md",
            "project_conformance": "reviews/project.md",
            "architecture_conformance": "reviews/architecture.md",
            "consistency_report": "consistency.json",
        },
        "gates": initial_gates(mode, selected_assurance),
        "gate_history": {},
        "events": [
            event(
                "case_initialized",
                mode=mode,
                intent=intent,
                mode_decision=(
                    decision_binding["fingerprint"] if decision_binding is not None else None
                ),
                method_context=(
                    method_binding["fingerprint"] if method_binding is not None else None
                ),
                planning_handoff=(
                    planning_binding["fingerprint"] if planning_binding is not None else None
                ),
            )
        ],
    }
    ledger = {"schema": SCHEMA_VERSION, "blocks": []}
    automation_ledger = initialize_automation_timing(
        case_id=case_id,
        automation_plan=runtime_automation_plan(
            (planning_payload or {}).get("automation_plan"),
            selected_tracking,
        ),
        planning_case_id=(planning_payload or {}).get("planning_case_id"),
        planning_revision=(planning_payload or {}).get("planning_revision"),
        passport=(planning_payload or {}).get("passport"),
    )
    atomic_json(manifest_path, manifest)
    atomic_json(root / ROLE_MANIFEST_JSON, role_manifest(manifest))
    atomic_json(root / "ledger.json", ledger)
    atomic_json(root / AUTOMATION_TIMING_FILENAME, automation_ledger)
    atomic_json(
        root / AGENT_LEDGER_JSON,
        {"schema": AGENT_LEDGER_SCHEMA, "case_id": case_id, "runs": []},
    )
    render_status(root, manifest, ledger)


def load_case(root: Path) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    """Load and minimally validate a case package."""
    root = root.expanduser().resolve()
    manifest = read_json(root / "manifest.json")
    ledger = read_json(root / "ledger.json")
    if manifest.get("schema") != SCHEMA_VERSION or ledger.get("schema") != SCHEMA_VERSION:
        raise CaseError(f"Unsupported case schema in {root}")
    if not isinstance(ledger.get("blocks"), list):
        raise CaseError("ledger.json: blocks must be an array")
    return root, manifest, ledger


def begin_bounded_recovery(
    root: Path,
    manifest: dict[str, Any],
    ledger: dict[str, Any],
    *,
    plan_path: Path,
) -> dict[str, Any]:
    """Bind an explicit frozen-version recovery plan without migrating case history."""
    previous = bounded_recovery_binding(manifest)
    if previous is not None and previous.get("status") == "active":
        raise CaseError("Bounded recovery is already active")
    ensure_kernel_synced(root, manifest)
    draft_path = case_file(root, manifest["artifacts"]["draft"])
    if not artifact_ready(draft_path):
        raise CaseError("Bounded recovery requires a complete frozen draft")
    source = plan_path.expanduser().resolve()
    plan = read_json(source)
    blocks = blocks_by_id(ledger)
    errors = recovery_plan_errors(
        plan,
        case_id=str(manifest.get("case_id")),
        block_ids=set(blocks),
    )
    if errors:
        raise CaseError("Invalid bounded recovery plan: " + "; ".join(errors))
    if plan["kernel_revision"] != manifest["kernel"]["revision"]:
        raise CaseError("Recovery plan kernel revision is stale")
    if plan["kernel_sha256"] != manifest["kernel"]["sha256"]:
        raise CaseError("Recovery plan kernel hash is stale")
    if plan["draft_sha256"] != sha256(draft_path):
        raise CaseError("Recovery plan draft hash is stale")
    omitted_gates = [
        gate_name
        for gate_name in recovery_required_gates(root, manifest, ledger)
        if gate_name not in plan["allowed_gates"]
    ]
    if omitted_gates:
        raise CaseError(
            "Recovery plan omits gates requiring recovery: "
            + ", ".join(omitted_gates)
        )

    baselines: dict[str, dict[str, Any]] = {}
    for block_id in plan["block_scopes"]:
        block = blocks[block_id]
        if block.get("status") not in {"analyzed", "reviewed", "integrated", "stale"}:
            raise CaseError(
                f"{block_id}: recovery requires analyzed, reviewed, integrated, or stale status"
            )
        if active_block_remediation(block) is not None:
            raise CaseError(f"{block_id}: finish or stop active remediation before recovery")
        artifact = case_file(root, block["artifact"])
        index = case_file(root, block["semantic_index"])
        if not artifact_ready(artifact) or not index.is_file():
            raise CaseError(f"{block_id}: recovery requires complete block artifacts")
        baselines[block_id] = {
            "status": block.get("status"),
            "artifact_sha256": sha256(artifact),
            "semantic_index_sha256": semantic_index_recovery_sha256(index),
        }

    if previous is not None:
        history = manifest.setdefault("bounded_recovery_history", [])
        revision = len(history) + 1
        archive_relative = f"recovery/history/recovery-plan-r{revision:03d}.json"
        archive = case_file(root, archive_relative)
        archive.parent.mkdir(parents=True, exist_ok=True)
        old_plan = case_file(root, str(previous.get("path", "")))
        if old_plan.is_file():
            immutable_copy(old_plan, archive)
        archived = dict(previous)
        archived["path"] = archive_relative
        archived["sha256"] = sha256(archive)
        history.append(archived)

    canonical_path = case_file(root, RECOVERY_PLAN_JSON)
    atomic_json(canonical_path, plan)
    binding = {
        "schema": RECOVERY_PLAN_SCHEMA,
        "status": "active",
        "path": RECOVERY_PLAN_JSON,
        "sha256": sha256(canonical_path),
        "started_at": now_utc(),
        "completed_at": None,
        "note": None,
        "kernel_revision": plan["kernel_revision"],
        "kernel_sha256": plan["kernel_sha256"],
        "draft_sha256": plan["draft_sha256"],
        "block_scopes": plan["block_scopes"],
        "allowed_gates": plan["allowed_gates"],
        "combine_final_review": plan["combine_final_review"],
        "new_findings_policy": plan["new_findings_policy"],
        "block_baselines": baselines,
    }
    manifest["bounded_recovery"] = binding
    manifest.setdefault("artifacts", {})["recovery_plan"] = RECOVERY_PLAN_JSON
    manifest["events"].append(
        event(
            "bounded_recovery_started",
            plan_sha256=binding["sha256"],
            blocks=sorted(plan["block_scopes"]),
            allowed_gates=plan["allowed_gates"],
        )
    )
    save_case(root, manifest, ledger)
    return binding


def bounded_recovery_errors(
    root: Path,
    manifest: dict[str, Any],
    ledger: dict[str, Any],
    *,
    final: bool,
) -> list[str]:
    """Detect plan drift and semantic mutation during a bounded recovery."""
    if manifest.get("bounded_recovery") is None:
        return []
    try:
        binding, plan = load_bounded_recovery(root, manifest, ledger)
    except CaseError as exc:
        return [str(exc)]
    errors: list[str] = []
    for field in (
        "block_scopes",
        "allowed_gates",
        "combine_final_review",
        "new_findings_policy",
    ):
        if binding.get(field) != plan.get(field):
            errors.append(f"bounded recovery binding differs from plan: {field}")
    if binding.get("status") == "active":
        if manifest.get("kernel", {}).get("revision") != plan["kernel_revision"]:
            errors.append("bounded recovery kernel revision changed")
        kernel_path = case_file(root, str(manifest.get("kernel", {}).get("path", "")))
        if (
            manifest.get("kernel", {}).get("sha256") != plan["kernel_sha256"]
            or not kernel_path.is_file()
            or sha256(kernel_path) != plan["kernel_sha256"]
        ):
            errors.append("bounded recovery kernel content changed")
        draft = case_file(root, manifest["artifacts"]["draft"])
        if not draft.is_file() or sha256(draft) != plan["draft_sha256"]:
            errors.append("bounded recovery draft content changed")
        baselines = binding.get("block_baselines")
        if not isinstance(baselines, dict):
            errors.append("bounded recovery block baselines are invalid")
        else:
            blocks = blocks_by_id(ledger)
            for block_id in plan["block_scopes"]:
                baseline = baselines.get(block_id)
                block = blocks.get(block_id)
                if not isinstance(baseline, dict) or block is None:
                    errors.append(f"bounded recovery baseline is missing for {block_id}")
                    continue
                artifact = case_file(root, block["artifact"])
                index = case_file(root, block["semantic_index"])
                if not artifact.is_file() or sha256(artifact) != baseline.get("artifact_sha256"):
                    errors.append(f"bounded recovery block content changed: {block_id}")
                if (
                    not index.is_file()
                    or semantic_index_recovery_sha256(index)
                    != baseline.get("semantic_index_sha256")
                ):
                    errors.append(f"bounded recovery semantic index changed: {block_id}")
        if final:
            errors.append("bounded recovery must be completed before final validation")
    return errors


def rebase_bounded_recovery_block(
    root: Path,
    manifest: dict[str, Any],
    ledger: dict[str, Any],
    *,
    block_id: str,
) -> None:
    """Carry a frozen stale block onto the pinned kernel before bounded re-review."""
    binding, plan = load_bounded_recovery(root, manifest, ledger, require_active=True)
    if block_id not in plan["block_scopes"]:
        raise CaseError(f"{block_id}: outside bounded recovery scope")
    block = blocks_by_id(ledger)[block_id]
    if block.get("status") != "stale":
        raise CaseError(f"{block_id}: recovery rebase requires stale status")
    baseline = binding["block_baselines"][block_id]
    artifact = case_file(root, block["artifact"])
    index_path = case_file(root, block["semantic_index"])
    if sha256(artifact) != baseline["artifact_sha256"]:
        raise CaseError(f"{block_id}: block content changed after recovery plan")
    if semantic_index_recovery_sha256(index_path) != baseline["semantic_index_sha256"]:
        raise CaseError(f"{block_id}: semantic index changed after recovery plan")
    index = read_json(index_path)
    index["kernel_revision"] = manifest["kernel"]["revision"]
    atomic_json(index_path, index)
    block["kernel_revision"] = manifest["kernel"]["revision"]
    block["kernel_sha256"] = manifest["kernel"]["sha256"]
    block["artifact_sha256"] = sha256(artifact)
    block["index_sha256"] = sha256(index_path)
    block["review_sha256"] = None
    block["status"] = "analyzed"
    block["note"] = "frozen content carried forward for bounded recovery review"
    block["updated_at"] = now_utc()
    manifest["events"].append(event("bounded_recovery_block_rebased", block_id=block_id))
    save_case(root, manifest, ledger)


def stop_bounded_recovery(
    root: Path,
    manifest: dict[str, Any],
    ledger: dict[str, Any],
    *,
    reason: str,
) -> None:
    """Stop a recovery when a new decision or semantic correction is required."""
    binding = active_bounded_recovery(manifest)
    if binding is None:
        raise CaseError("Bounded recovery is not active")
    if not reason.strip():
        raise CaseError("Stopping bounded recovery requires a reason")
    binding.update(status="cancelled", completed_at=now_utc(), note=reason.strip())
    manifest["events"].append(event("bounded_recovery_cancelled", reason=reason.strip()))
    save_case(root, manifest, ledger)


def complete_bounded_recovery(
    root: Path,
    manifest: dict[str, Any],
    ledger: dict[str, Any],
    *,
    note: str,
) -> None:
    """Close recovery only after every declared block and gate has current evidence."""
    binding, plan = load_bounded_recovery(root, manifest, ledger, require_active=True)
    drift = bounded_recovery_errors(root, manifest, ledger, final=False)
    if drift:
        raise CaseError("Bounded recovery drift: " + "; ".join(drift))
    blocks = blocks_by_id(ledger)
    incomplete = [
        block_id
        for block_id in plan["block_scopes"]
        if blocks[block_id].get("status") != "integrated"
    ]
    if incomplete:
        raise CaseError("Bounded recovery blocks are incomplete: " + ", ".join(incomplete))
    open_gates = [
        gate_name
        for gate_name in GATE_NAMES
        if manifest.get("gates", {}).get(gate_name, {}).get("status")
        not in {"pass", "not_required"}
    ]
    if open_gates:
        raise CaseError("Bounded recovery gates are incomplete: " + ", ".join(open_gates))
    previous_binding = dict(binding)
    active_role_manifest = copy.deepcopy(role_manifest(manifest))
    binding.update(status="complete", completed_at=now_utc(), note=note.strip() or None)
    final_errors = validate_case(
        root,
        manifest,
        ledger,
        final=True,
        accepted_role_manifests=[active_role_manifest],
    )
    if final_errors:
        binding.clear()
        binding.update(previous_binding)
        raise CaseError(
            "Bounded recovery is not local-green: " + "; ".join(final_errors)
        )
    manifest["events"].append(
        event("bounded_recovery_completed", plan_sha256=binding["sha256"], note=note.strip())
    )
    save_case(root, manifest, ledger)


def _external_binding_identity(
    payload: dict[str, Any],
) -> dict[str, tuple[str, str, str | None]]:
    """Return external object identity without volatile read-back fields."""
    return {
        binding["target_id"]: (
            binding["system"],
            binding["object_id"],
            binding.get("url"),
        )
        for binding in payload.get("external_bindings", [])
        if isinstance(binding, dict)
        and all(
            isinstance(binding.get(field), str) and binding[field].strip()
            for field in ("target_id", "system", "object_id")
        )
    }


def migrate_planning_handoff(
    root: Path,
    manifest: dict[str, Any],
    ledger: dict[str, Any],
    *,
    handoff_root: Path,
    reason: str,
) -> dict[str, Any]:
    """Replace a superseded planning handoff without rebuilding semantic work.

    The previous handoff, timing ledger, coordinator manifest, role projection,
    and semantic ledger are archived before the new planning revision is bound.
    Runtime checklist progress starts fresh and must be re-established through
    normal evidence/read-back commands; the archived ledger retains earlier
    wall-clock observations.
    """
    if active_bounded_recovery(manifest) is not None:
        raise CaseError("Planning migration is forbidden during bounded recovery")
    if not reason.strip():
        raise CaseError("Planning handoff migration requires a reason")
    in_progress = [
        str(block.get("id"))
        for block in ledger.get("blocks", [])
        if isinstance(block, dict) and block.get("status") == "in_progress"
    ]
    if in_progress:
        raise CaseError(
            "Planning handoff migration requires stable semantic blocks; in progress: "
            + ", ".join(in_progress)
        )

    old_binding = manifest.get("planning_handoff")
    if not isinstance(old_binding, dict):
        raise CaseError("Existing case has no planning handoff binding to migrate")
    old_metadata = case_file(root, PLANNING_HANDOFF_JSON)
    old_content = case_file(root, PLANNING_HANDOFF_MARKDOWN)
    old_payload = read_json(old_metadata)
    old_markdown = old_content.read_text(encoding="utf-8")
    if old_payload.get("fingerprint") != canonical_planning_fingerprint(old_payload):
        raise CaseError("Existing planning handoff fingerprint mismatch")
    if old_payload.get("content_sha256") != hashlib.sha256(
        old_markdown.encode("utf-8")
    ).hexdigest():
        raise CaseError("Existing planning handoff content hash mismatch")
    if old_binding.get("fingerprint") != old_payload.get("fingerprint"):
        raise CaseError("Coordinator manifest does not match existing planning handoff")

    source_root = handoff_root.expanduser().resolve()
    source_metadata = source_root / PLANNING_HANDOFF_JSON
    source_content = source_root / PLANNING_HANDOFF_MARKDOWN
    if not source_metadata.is_file() or not source_content.is_file():
        raise CaseError("Migration source requires planning-handoff.json and .md")
    new_payload = read_json(source_metadata)
    new_markdown = source_content.read_text(encoding="utf-8")
    try:
        validate_planning_handoff(
            new_payload,
            new_markdown,
            expected_profile_id=manifest.get("profile_id"),
            expected_project_root=manifest.get("project_root"),
            enforce_project_root=True,
        )
    except PlanningError as exc:
        raise CaseError(f"Invalid replacement planning handoff: {exc}") from exc

    old_case_id = old_payload.get("planning_case_id")
    old_revision = old_payload.get("planning_revision")
    new_revision = new_payload.get("planning_revision")
    if new_payload.get("planning_case_id") != old_case_id:
        raise CaseError("Replacement planning handoff belongs to another planning case")
    if not isinstance(old_revision, int) or not isinstance(new_revision, int):
        raise CaseError("Planning handoff revisions must be integers")
    if new_revision <= old_revision:
        raise CaseError("Replacement planning revision must be newer")
    old_passport = old_payload.get("passport")
    new_passport = new_payload.get("passport")
    if isinstance(old_passport, dict) and isinstance(new_passport, dict):
        if old_passport.get("id") != new_passport.get("id"):
            raise CaseError("Replacement planning handoff changes the passport")
    elif old_passport != new_passport:
        raise CaseError("Replacement planning handoff changes the passport")
    old_bindings = _external_binding_identity(old_payload)
    new_bindings = _external_binding_identity(new_payload)
    if not old_bindings.keys() <= new_bindings.keys():
        raise CaseError("Replacement planning handoff removes external bindings")
    projection_path = case_file(root, WORKING_PROJECTION_JSON)
    projection_state = (
        read_json(projection_path)
        if projection_path.is_file()
        else {
            "schema": WORKING_PROJECTION_SCHEMA,
            "policy": "optional",
            "targets": [],
            "updates": [],
        }
    )
    projection_errors = validate_working_projection_state(projection_state)
    if projection_errors:
        raise CaseError("Existing working projection is invalid: " + "; ".join(projection_errors))
    replacement_projection = new_payload.get(
        "working_projection", {"policy": "optional", "targets": []}
    )
    if not isinstance(replacement_projection, dict):
        raise CaseError("Replacement working projection is invalid")
    old_projection_targets = {
        item.get("target_id"): (
            item.get("system"),
            item.get("object_id"),
            item.get("url"),
            item.get("evidence_kind"),
        )
        for item in projection_state.get("targets", [])
        if isinstance(item, dict) and isinstance(item.get("target_id"), str)
    }
    new_projection_targets = {
        item.get("target_id"): (
            item.get("system"),
            item.get("object_id"),
            item.get("url"),
            item.get("evidence_kind"),
        )
        for item in replacement_projection.get("targets", [])
        if isinstance(item, dict) and isinstance(item.get("target_id"), str)
    }
    if not old_projection_targets.keys() <= new_projection_targets.keys():
        raise CaseError("Replacement planning handoff removes a working projection target")
    unchanged_projection_targets = {
        target_id
        for target_id, identity in old_projection_targets.items()
        if new_projection_targets.get(target_id) == identity
    }
    preserved_updates = [
        update
        for update in projection_state.get("updates", [])
        if isinstance(update, dict)
        and update.get("target_id") in unchanged_projection_targets
    ]
    replacement_projection_state = {
        "schema": WORKING_PROJECTION_SCHEMA,
        "policy": replacement_projection.get("policy", "optional"),
        "targets": replacement_projection.get("targets", []),
        "updates": preserved_updates,
    }
    projection_errors = validate_working_projection_state(replacement_projection_state)
    if projection_errors:
        raise CaseError(
            "Replacement working projection is invalid: " + "; ".join(projection_errors)
        )

    replacement_timing = initialize_automation_timing(
        case_id=manifest["case_id"],
        automation_plan=runtime_automation_plan(
            new_payload.get("automation_plan"),
            tracking_policy(manifest),
        ),
        planning_case_id=new_payload.get("planning_case_id"),
        planning_revision=new_revision,
        passport=new_payload.get("passport"),
    )
    archive_relative = (
        f"migrations/planning-r{old_revision:03d}-to-r{new_revision:03d}"
    )
    archive = case_file(root, archive_relative)
    if archive.exists():
        raise CaseError(f"Planning migration archive already exists: {archive_relative}")
    archive.mkdir(parents=True)
    archive_files = (
        "manifest.json",
        "ledger.json",
        PLANNING_HANDOFF_JSON,
        PLANNING_HANDOFF_MARKDOWN,
        AUTOMATION_TIMING_FILENAME,
        ROLE_MANIFEST_JSON,
        PLANNING_ROLE_CONTEXT_JSON,
        WORKING_PROJECTION_JSON,
    )
    archived: dict[str, str] = {}
    for relative in archive_files:
        source = root / relative
        if not source.is_file():
            continue
        destination = archive / source.name
        shutil.copy2(source, destination)
        archived[relative] = sha256(destination)

    atomic_json(root / PLANNING_HANDOFF_JSON, new_payload)
    atomic_text(root / PLANNING_HANDOFF_MARKDOWN, new_markdown)
    role_context_payload = planning_role_context(new_payload)
    atomic_json(root / PLANNING_ROLE_CONTEXT_JSON, role_context_payload)
    atomic_json(root / AUTOMATION_TIMING_FILENAME, replacement_timing)
    atomic_json(root / WORKING_PROJECTION_JSON, replacement_projection_state)
    manifest["planning_handoff"] = {
        "metadata_path": PLANNING_HANDOFF_JSON,
        "content_path": PLANNING_HANDOFF_MARKDOWN,
        "planning_case_id": new_payload["planning_case_id"],
        "planning_revision": new_revision,
        "project_root": new_payload["project_root"],
        "fingerprint": new_payload["fingerprint"],
        "content_sha256": new_payload["content_sha256"],
        "role_context_path": PLANNING_ROLE_CONTEXT_JSON,
        "role_context_fingerprint": role_context_payload["fingerprint"],
    }
    manifest.setdefault("artifacts", {}).update(
        {
            "automation_timing": AUTOMATION_TIMING_FILENAME,
            "role_manifest": ROLE_MANIFEST_JSON,
            "planning_role_context": PLANNING_ROLE_CONTEXT_JSON,
            "working_projection": WORKING_PROJECTION_JSON,
        }
    )
    migrated_at = now_utc()
    previous_automation_plan = old_payload.get("automation_plan")
    replacement_automation_plan = new_payload.get("automation_plan")
    manifest.setdefault("events", []).append(
        {
            "at": migrated_at,
            "kind": "planning_handoff_migrated",
            "from_revision": old_revision,
            "to_revision": new_revision,
            "archive": archive_relative,
            "reason": reason.strip(),
            "previous_automation_plan_fingerprint": (
                previous_automation_plan.get("fingerprint")
                if isinstance(previous_automation_plan, dict)
                else None
            ),
            "automation_plan_fingerprint": (
                replacement_automation_plan.get("fingerprint")
                if isinstance(replacement_automation_plan, dict)
                else None
            ),
        }
    )
    save_case(root, manifest, ledger)
    migration_record = {
        "schema": 1,
        "case_id": manifest["case_id"],
        "planning_case_id": new_payload["planning_case_id"],
        "from_revision": old_revision,
        "to_revision": new_revision,
        "migrated_at": migrated_at,
        "reason": reason.strip(),
        "archived_files": archived,
        "new_handoff_fingerprint": new_payload["fingerprint"],
        "new_automation_plan_fingerprint": (
            replacement_automation_plan.get("fingerprint")
            if isinstance(replacement_automation_plan, dict)
            else None
        ),
        "runtime_checklist_policy": "reverify_through_normal_check_commands",
    }
    atomic_json(archive / "migration.json", migration_record)
    return migration_record


def save_case(root: Path, manifest: dict[str, Any], ledger: dict[str, Any]) -> None:
    """Persist state and refresh the human-readable dashboard."""
    manifest["updated_at"] = now_utc()
    atomic_json(root / "manifest.json", manifest)
    atomic_json(root / ROLE_MANIFEST_JSON, role_manifest(manifest))
    atomic_json(root / "ledger.json", ledger)
    render_status(root, manifest, ledger)


def validate_agent_ledger(payload: Any, *, case_id: str) -> list[str]:
    """Validate telemetry shape without pretending missing provider counters exist."""
    if not isinstance(payload, dict):
        return ["agent-ledger.json must be an object"]
    if payload.get("schema") != AGENT_LEDGER_SCHEMA or payload.get("case_id") != case_id:
        return ["agent-ledger.json identity is invalid"]
    runs = payload.get("runs")
    if not isinstance(runs, list):
        return ["agent-ledger.json runs must be an array"]
    errors: list[str] = []
    seen_run_ids: set[str] = set()
    for index, run in enumerate(runs):
        label = f"agent-ledger run {index + 1}"
        if not isinstance(run, dict):
            errors.append(f"{label} must be an object")
            continue
        for field in ("at", "role", "role_mode", "model"):
            if not isinstance(run.get(field), str) or not run[field].strip():
                errors.append(f"{label} requires {field}")
        run_id = run.get("run_id")
        if run_id is not None:
            if not isinstance(run_id, str) or not AGENT_RUN_ID_RE.fullmatch(run_id):
                errors.append(f"{label} has invalid run_id")
            elif run_id in seen_run_ids:
                errors.append(f"{label} duplicates run_id {run_id}")
            else:
                seen_run_ids.add(run_id)
        if run.get("assurance_level") not in ASSURANCE_LEVELS:
            errors.append(f"{label} has invalid assurance_level")
        if not isinstance(run.get("subject_sha256"), str) or not SHA256_RE.fullmatch(
            run["subject_sha256"]
        ):
            errors.append(f"{label} has invalid subject_sha256")
        for field in (
            "input_bytes",
            "input_tokens",
            "output_tokens",
            "tool_calls",
            "poll_calls",
        ):
            value = run.get(field)
            if value is not None and (
                not isinstance(value, int) or isinstance(value, bool) or value < 0
            ):
                errors.append(f"{label} {field} must be non-negative or null")
        duration = run.get("duration_seconds")
        if (
            not isinstance(duration, (int, float))
            or isinstance(duration, bool)
            or duration < 0
        ):
            errors.append(f"{label} has invalid duration_seconds")
        wait_seconds = run.get("wait_seconds")
        if wait_seconds is not None and (
            not isinstance(wait_seconds, (int, float))
            or isinstance(wait_seconds, bool)
            or wait_seconds < 0
        ):
            errors.append(f"{label} wait_seconds must be non-negative or null")
        retries = run.get("retries")
        if not isinstance(retries, int) or isinstance(retries, bool) or retries < 0:
            errors.append(f"{label} has invalid retries")
        elif run.get("supervisor_contract") == AGENT_SUPERVISOR_CONTRACT and retries > 1:
            errors.append(f"{label} exceeds the one-retry policy")
        supervisor_contract = run.get("supervisor_contract")
        if supervisor_contract is not None and supervisor_contract != AGENT_SUPERVISOR_CONTRACT:
            errors.append(f"{label} has invalid supervisor_contract")
        findings = run.get("findings")
        if not isinstance(findings, dict):
            errors.append(f"{label} findings must be an object")
        else:
            for severity in ("blocker", "major", "minor"):
                value = findings.get(severity)
                if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                    errors.append(f"{label} findings.{severity} is invalid")
        if run.get("cache_status") not in {"hit", "miss", "unknown"}:
            errors.append(f"{label} has invalid cache_status")
        status = run.get("status", "completed")
        if status not in AGENT_RUN_STATUSES:
            errors.append(f"{label} has invalid status")
        degraded_reasons = run.get("degraded_reasons", [])
        if not isinstance(degraded_reasons, list) or any(
            not isinstance(item, str) or not item.strip() for item in degraded_reasons
        ):
            errors.append(f"{label} degraded_reasons must contain non-empty strings")
        if degraded_reasons and status == "completed":
            errors.append(f"{label} completed status cannot have degraded_reasons")
        lenses = run.get("lenses", [])
        if not isinstance(lenses, list) or any(
            not isinstance(item, str) or not REVIEW_LENS_RE.fullmatch(item)
            for item in lenses
        ):
            errors.append(f"{label} lenses must use stable id@version values")
        if isinstance(lenses, list) and len(lenses) != len(set(lenses)):
            errors.append(f"{label} lenses must be unique")
        artifacts = run.get("artifacts")
        if artifacts is not None:
            if not isinstance(artifacts, dict) or not artifacts:
                errors.append(f"{label} artifacts must be a non-empty object")
            else:
                for artifact_kind, binding in artifacts.items():
                    if artifact_kind not in {"prompt", "output"}:
                        errors.append(f"{label} has unknown artifact kind {artifact_kind}")
                        continue
                    if not isinstance(binding, dict):
                        errors.append(f"{label} {artifact_kind} artifact must be an object")
                        continue
                    if not isinstance(binding.get("ref"), str) or not binding["ref"].strip():
                        errors.append(f"{label} {artifact_kind} artifact requires ref")
                    if not isinstance(binding.get("sha256"), str) or not SHA256_RE.fullmatch(
                        binding["sha256"]
                    ):
                        errors.append(f"{label} {artifact_kind} artifact has invalid sha256")
        verification = run.get("verification")
        if verification is not None:
            if run_id is None:
                errors.append(f"{label} legacy run cannot have verification")
            elif not isinstance(verification, dict):
                errors.append(f"{label} verification must be an object")
            else:
                for field in ("at", "evidence_ref", "evidence_sha256"):
                    if not isinstance(verification.get(field), str) or not verification[field].strip():
                        errors.append(f"{label} verification requires {field}")
                if isinstance(verification.get("evidence_sha256"), str) and not SHA256_RE.fullmatch(
                    verification["evidence_sha256"]
                ):
                    errors.append(f"{label} verification has invalid evidence_sha256")
                dispositions = verification.get("dispositions")
                if not isinstance(dispositions, dict):
                    errors.append(f"{label} verification dispositions must be an object")
                else:
                    for disposition in ("accepted", "rejected", "duplicate", "verified"):
                        value = dispositions.get(disposition)
                        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                            errors.append(
                                f"{label} verification dispositions.{disposition} is invalid"
                            )
                    accepted = dispositions.get("accepted")
                    verified = dispositions.get("verified")
                    if isinstance(accepted, int) and isinstance(verified, int) and verified > accepted:
                        errors.append(f"{label} verification verified exceeds accepted")
    attempts_by_assignment: dict[tuple[str, str, str], int] = {}
    terminal_assignments: set[tuple[str, str, str]] = set()
    for index, run in enumerate(runs, start=1):
        if (
            not isinstance(run, dict)
            or not isinstance(run.get("run_id"), str)
            or not AGENT_RUN_ID_RE.fullmatch(run["run_id"])
            or run.get("supervisor_contract") != AGENT_SUPERVISOR_CONTRACT
            or not isinstance(run.get("retries"), int)
            or isinstance(run.get("retries"), bool)
        ):
            continue
        key = (
            str(run.get("role")),
            str(run.get("role_mode")),
            str(run.get("subject_sha256")),
        )
        if key in terminal_assignments:
            errors.append(
                f"agent-ledger run {index} repeats a terminal assignment"
            )
        attempts_by_assignment[key] = attempts_by_assignment.get(key, 0) + 1 + run["retries"]
        if attempts_by_assignment[key] > 2:
            errors.append(
                f"agent-ledger run {index} exceeds two attempts for one assignment"
            )
        if run.get("status", "completed") in {"completed", "degraded"}:
            terminal_assignments.add(key)
    return errors


def agent_artifact_binding(root: Path, relative: str) -> dict[str, str]:
    """Bind an existing case-owned prompt or output artifact by content hash."""
    path = case_file(root, relative)
    if not path.is_file():
        raise CaseError(f"Agent artifact is missing: {relative}")
    return {"ref": relative, "sha256": sha256(path)}


def agent_artifact_errors(root: Path, payload: dict[str, Any]) -> list[str]:
    """Detect changed or missing artifacts bound into observability records."""
    errors: list[str] = []
    for index, run in enumerate(payload.get("runs", []), start=1):
        if not isinstance(run, dict):
            continue
        bindings: list[tuple[str, Any]] = list((run.get("artifacts") or {}).items())
        verification = run.get("verification")
        if isinstance(verification, dict):
            bindings.append(
                (
                    "verification",
                    {
                        "ref": verification.get("evidence_ref"),
                        "sha256": verification.get("evidence_sha256"),
                    },
                )
            )
        for kind, binding in bindings:
            if not isinstance(binding, dict):
                continue
            relative = binding.get("ref")
            expected = binding.get("sha256")
            if not isinstance(relative, str) or not isinstance(expected, str):
                continue
            try:
                path = case_file(root, relative)
            except CaseError as exc:
                errors.append(f"agent-ledger run {index} {kind}: {exc}")
                continue
            if not path.is_file():
                errors.append(f"agent-ledger run {index} {kind} artifact is missing")
            elif sha256(path) != expected:
                errors.append(f"agent-ledger run {index} {kind} artifact changed after binding")
    return errors


def next_agent_run_id(runs: list[Any]) -> str:
    """Return a stable monotonic id without rewriting legacy run records."""
    maximum = 0
    for run in runs:
        if not isinstance(run, dict):
            continue
        run_id = run.get("run_id")
        if isinstance(run_id, str) and AGENT_RUN_ID_RE.fullmatch(run_id):
            maximum = max(maximum, int(run_id.removeprefix("AR-")))
    return f"AR-{maximum + 1:04d}"


def record_agent_run(
    root: Path,
    manifest: dict[str, Any],
    ledger: dict[str, Any],
    *,
    role: str,
    role_mode: str,
    model: str,
    subject_sha256: str,
    input_bytes: int | None,
    input_tokens: int | None,
    output_tokens: int | None,
    duration_seconds: float,
    retries: int,
    reported_blocker: int,
    reported_major: int,
    reported_minor: int,
    cache_status: str,
    status: str = "completed",
    degraded_reasons: list[str] | None = None,
    lenses: list[str] | None = None,
    prompt_artifact: str | None = None,
    output_artifact: str | None = None,
    tool_calls: int | None = None,
    poll_calls: int | None = None,
    wait_seconds: float | None = None,
) -> str:
    """Append cost and finding-yield telemetry without exposing it to roles."""
    relative = manifest.get("artifacts", {}).get("agent_ledger")
    if not isinstance(relative, str):
        raise CaseError("Case has no agent ledger; legacy cases keep legacy telemetry")
    if not role.strip() or not role_mode.strip() or not model.strip():
        raise CaseError("Agent role, role mode, and model are required")
    normalized_subject = subject_sha256.strip().lower()
    if not SHA256_RE.fullmatch(normalized_subject):
        raise CaseError("Agent subject hash must be a lowercase SHA-256 value")
    integer_fields = {
        "input_bytes": input_bytes,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "tool_calls": tool_calls,
        "poll_calls": poll_calls,
        "retries": retries,
        "reported_blocker": reported_blocker,
        "reported_major": reported_major,
        "reported_minor": reported_minor,
    }
    for label, value in integer_fields.items():
        if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 0):
            raise CaseError(f"Agent telemetry {label} must be a non-negative integer or null")
    if retries > 1:
        raise CaseError("Agent telemetry permits at most one retry")
    if duration_seconds < 0:
        raise CaseError("Agent telemetry duration must be non-negative")
    if wait_seconds is not None and (
        not isinstance(wait_seconds, (int, float))
        or isinstance(wait_seconds, bool)
        or wait_seconds < 0
    ):
        raise CaseError("Agent telemetry wait_seconds must be non-negative or null")
    if cache_status not in {"hit", "miss", "unknown"}:
        raise CaseError("Agent telemetry cache status must be hit, miss, or unknown")
    if status not in AGENT_RUN_STATUSES:
        raise CaseError("Agent telemetry status is invalid")
    normalized_reasons = [item.strip() for item in degraded_reasons or []]
    if any(not item for item in normalized_reasons):
        raise CaseError("Agent telemetry degraded reasons must be non-empty")
    if normalized_reasons and status == "completed":
        raise CaseError("Completed agent run cannot have degraded reasons")
    normalized_lenses = [item.strip() for item in lenses or []]
    if len(normalized_lenses) != len(set(normalized_lenses)) or any(
        not REVIEW_LENS_RE.fullmatch(item) for item in normalized_lenses
    ):
        raise CaseError("Agent lenses must be unique stable id@version values")
    path = case_file(root, relative)
    payload = read_json(path)
    ledger_errors = validate_agent_ledger(payload, case_id=str(manifest.get("case_id")))
    if ledger_errors:
        raise CaseError("agent-ledger.json is invalid: " + "; ".join(ledger_errors))
    assignment = (role.strip(), role_mode.strip(), normalized_subject)
    attempts = 0
    terminal = False
    for previous in payload["runs"]:
        if (
            not isinstance(previous, dict)
            or not isinstance(previous.get("run_id"), str)
            or previous.get("supervisor_contract") != AGENT_SUPERVISOR_CONTRACT
        ):
            continue
        previous_assignment = (
            str(previous.get("role")),
            str(previous.get("role_mode")),
            str(previous.get("subject_sha256")),
        )
        if previous_assignment != assignment:
            continue
        attempts += 1 + int(previous.get("retries", 0))
        terminal = terminal or previous.get("status", "completed") in {
            "completed",
            "degraded",
        }
    if terminal:
        raise CaseError("Agent assignment already has a terminal result")
    if attempts + 1 + retries > 2:
        raise CaseError("Agent assignment exceeded one retry")
    run = {
        "run_id": next_agent_run_id(payload["runs"]),
        "at": now_utc(),
        "role": role.strip(),
        "role_mode": role_mode.strip(),
        "assurance_level": assurance_level(manifest),
        "model": model.strip(),
        "subject_sha256": normalized_subject,
        "input_bytes": input_bytes,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "duration_seconds": duration_seconds,
        "retries": retries,
        "supervisor_contract": AGENT_SUPERVISOR_CONTRACT,
        "tool_calls": tool_calls,
        "poll_calls": poll_calls,
        "wait_seconds": wait_seconds,
        "findings": {
            "blocker": reported_blocker,
            "major": reported_major,
            "minor": reported_minor,
        },
        "cache_status": cache_status,
        "status": status,
        "degraded_reasons": normalized_reasons,
        "lenses": normalized_lenses,
    }
    artifacts: dict[str, dict[str, str]] = {}
    if prompt_artifact is not None:
        artifacts["prompt"] = agent_artifact_binding(root, prompt_artifact)
    if output_artifact is not None:
        artifacts["output"] = agent_artifact_binding(root, output_artifact)
    if artifacts:
        run["artifacts"] = artifacts
    payload["runs"].append(run)
    atomic_json(path, payload)
    manifest["events"].append(
        event(
            "agent_run_recorded",
            role=run["role"],
            role_mode=run["role_mode"],
            subject_sha256=normalized_subject,
            reported_blocker=reported_blocker,
            reported_major=reported_major,
            reported_minor=reported_minor,
        )
    )
    save_case(root, manifest, ledger)
    return str(run["run_id"])


def record_agent_verification(
    root: Path,
    manifest: dict[str, Any],
    ledger: dict[str, Any],
    *,
    run_id: str,
    accepted: int,
    rejected: int,
    duplicate: int,
    verified: int,
    evidence_ref: str,
) -> None:
    """Attach one final finding disposition receipt to an existing run."""
    if not AGENT_RUN_ID_RE.fullmatch(run_id):
        raise CaseError("Agent run id is invalid")
    counts = {
        "accepted": accepted,
        "rejected": rejected,
        "duplicate": duplicate,
        "verified": verified,
    }
    if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in counts.values()):
        raise CaseError("Agent verification counts must be non-negative integers")
    if verified > accepted:
        raise CaseError("Verified findings cannot exceed accepted findings")
    relative = manifest.get("artifacts", {}).get("agent_ledger")
    if not isinstance(relative, str):
        raise CaseError("Case has no agent ledger; legacy cases keep legacy telemetry")
    path = case_file(root, relative)
    payload = read_json(path)
    ledger_errors = validate_agent_ledger(payload, case_id=str(manifest.get("case_id")))
    if ledger_errors:
        raise CaseError("agent-ledger.json is invalid: " + "; ".join(ledger_errors))
    matches = [run for run in payload["runs"] if isinstance(run, dict) and run.get("run_id") == run_id]
    if len(matches) != 1:
        raise CaseError(f"Agent run not found: {run_id}")
    run = matches[0]
    if "verification" in run:
        raise CaseError(f"Agent run already has verification: {run_id}")
    reported = run.get("findings", {})
    reported_total = sum(
        value for value in reported.values() if isinstance(value, int) and not isinstance(value, bool)
    )
    if accepted + rejected + duplicate != reported_total:
        raise CaseError("Agent verification must classify every reported finding exactly once")
    evidence = agent_artifact_binding(root, evidence_ref)
    run["verification"] = {
        "at": now_utc(),
        "evidence_ref": evidence["ref"],
        "evidence_sha256": evidence["sha256"],
        "dispositions": counts,
    }
    atomic_json(path, payload)
    manifest["events"].append(
        event("agent_run_verified", run_id=run_id, **counts)
    )
    save_case(root, manifest, ledger)


def record_working_projection_update(
    root: Path,
    manifest: dict[str, Any],
    ledger: dict[str, Any],
    *,
    target_id: str,
    source: str,
    source_sha256: str,
    content_sha256: str,
    evidence_kind: str,
    evidence_ref: str,
    read_back_at: str,
) -> None:
    """Record one user-visible projection update only after a successful read-back."""
    relative = manifest.get("artifacts", {}).get("working_projection")
    if not isinstance(relative, str):
        raise CaseError("Case has no working projection artifact")
    path = case_file(root, relative)
    payload = read_json(path)
    errors = validate_working_projection_state(payload)
    if errors:
        raise CaseError("Invalid working projection state: " + "; ".join(errors))
    if not source.strip() or not evidence_ref.strip() or not read_back_at.strip():
        raise CaseError("Projection source, evidence ref, and read-back time are required")
    normalized_source_hash = source_sha256.strip().lower()
    if not SHA256_RE.fullmatch(normalized_source_hash):
        raise CaseError("Projection source hash must be a lowercase SHA-256 value")
    normalized_content_hash = content_sha256.strip().lower()
    if not SHA256_RE.fullmatch(normalized_content_hash):
        raise CaseError("Projection content hash must be a lowercase SHA-256 value")
    targets = working_projection_targets(payload)
    if target_id not in targets:
        raise CaseError(f"Unknown working projection target: {target_id}")
    normalized_source = source.strip()
    if BLOCK_ID_RE.fullmatch(normalized_source):
        block = blocks_by_id(ledger).get(normalized_source)
        if block is None:
            raise CaseError(f"Unknown projection source block: {normalized_source}")
        if block.get("status") not in {"reviewed", "integrated"}:
            raise CaseError(f"Projection source block is not reviewed: {normalized_source}")
        if block.get("artifact_sha256") != normalized_source_hash:
            raise CaseError(f"Projection source hash is stale for {normalized_source}")
    elif normalized_source in {"draft", "integration"}:
        draft = case_file(root, manifest["artifacts"]["draft"])
        if not artifact_ready(draft) or sha256(draft) != normalized_source_hash:
            raise CaseError(f"Projection source hash is stale for {normalized_source}")
    else:
        raise CaseError(f"Unknown projection source: {normalized_source}")
    normalized_evidence_kind = evidence_kind.strip().lower()
    evidence_hash = projection_evidence_sha256(
        root,
        manifest,
        targets[target_id],
        evidence_kind=normalized_evidence_kind,
        evidence_ref=evidence_ref.strip(),
        content_sha256=normalized_content_hash,
        read_back_at=read_back_at.strip(),
    )
    candidate = {
        "target_id": target_id,
        "source": normalized_source,
        "source_sha256": normalized_source_hash,
        "content_sha256": normalized_content_hash,
        "evidence_kind": normalized_evidence_kind,
        "evidence_ref": evidence_ref.strip(),
        "evidence_sha256": evidence_hash,
        "read_back_at": read_back_at.strip(),
    }
    target_updates = [
        item
        for item in payload["updates"]
        if isinstance(item, dict) and item.get("target_id") == target_id
    ]
    latest = target_updates[-1] if target_updates else None
    if (
        isinstance(latest, dict)
        and latest.get("source") == candidate["source"]
        and latest.get("source_sha256") == normalized_source_hash
        and latest.get("content_sha256") == normalized_content_hash
        and latest.get("evidence_kind") == normalized_evidence_kind
        and latest.get("evidence_sha256") == evidence_hash
    ):
        return
    if (
        projection_sync_policy(manifest) == "milestones"
        and isinstance(latest, dict)
        and latest.get("content_sha256") == normalized_content_hash
        and latest.get("evidence_kind") == normalized_evidence_kind
        and latest.get("evidence_sha256") == evidence_hash
    ):
        binding = {
            "source": normalized_source,
            "source_sha256": normalized_source_hash,
            "bound_at": read_back_at.strip(),
        }
        bindings = latest.setdefault("source_bindings", [])
        if not any(
            isinstance(item, dict)
            and item.get("source") == normalized_source
            and item.get("source_sha256") == normalized_source_hash
            for item in bindings
        ):
            bindings.append(binding)
            atomic_json(path, payload)
            manifest["events"].append(
                event(
                    "working_projection_source_bound",
                    target_id=target_id,
                    source=normalized_source,
                    source_sha256=normalized_source_hash,
                    content_sha256=normalized_content_hash,
                )
            )
            save_case(root, manifest, ledger)
        return
    payload["updates"].append(candidate)
    atomic_json(path, payload)
    manifest["events"].append(
        event(
            "working_projection_updated",
            target_id=target_id,
            source=candidate["source"],
            source_sha256=normalized_source_hash,
            content_sha256=normalized_content_hash,
            evidence_kind=normalized_evidence_kind,
            evidence_ref=candidate["evidence_ref"],
            evidence_sha256=evidence_hash,
        )
    )
    save_case(root, manifest, ledger)


def blocks_by_id(ledger: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Index blocks and reject duplicate ids."""
    result: dict[str, dict[str, Any]] = {}
    for block in ledger["blocks"]:
        block_id = block.get("id")
        if block_id in result:
            raise CaseError(f"Duplicate block id: {block_id}")
        result[block_id] = block
    return result


def ensure_acyclic(ledger: dict[str, Any]) -> None:
    """Reject missing dependencies and dependency cycles."""
    blocks = blocks_by_id(ledger)
    for block in blocks.values():
        for dependency in block.get("depends_on", []):
            if dependency not in blocks:
                raise CaseError(f"{block['id']}: unknown dependency {dependency}")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(block_id: str) -> None:
        if block_id in visiting:
            raise CaseError(f"Dependency cycle includes {block_id}")
        if block_id in visited:
            return
        visiting.add(block_id)
        for dependency in blocks[block_id].get("depends_on", []):
            visit(dependency)
        visiting.remove(block_id)
        visited.add(block_id)

    for block_id in blocks:
        visit(block_id)


def add_block(
    root: Path,
    manifest: dict[str, Any],
    ledger: dict[str, Any],
    *,
    block_id: str,
    title: str,
    kind: str,
    depends_on: list[str],
    risk_surfaces: list[str] | None = None,
) -> None:
    """Add one semantic block to the dependency ledger."""
    if active_bounded_recovery(manifest) is not None:
        raise CaseError("Adding blocks is forbidden during bounded recovery")
    if manifest.get("mode") != "block":
        raise CaseError("Blocks can only be added in block mode")
    if not BLOCK_ID_RE.fullmatch(block_id):
        raise CaseError(f"Invalid block id: {block_id}")
    if kind not in BLOCK_KINDS:
        raise CaseError(f"Invalid block kind: {kind}")
    if block_id in blocks_by_id(ledger):
        raise CaseError(f"Block already exists: {block_id}")
    unknown = sorted(set(depends_on) - set(blocks_by_id(ledger)))
    if unknown:
        raise CaseError(f"Unknown dependencies: {', '.join(unknown)}")
    raw_risk_surfaces = list(risk_surfaces or [])
    invalid_risk_surfaces = sorted(
        (
            item
            for item in raw_risk_surfaces
            if not isinstance(item, str) or not RISK_SURFACE_RE.fullmatch(item)
        ),
        key=repr,
    )
    if invalid_risk_surfaces:
        raise CaseError(
            "Risk surfaces must use stable lowercase kebab-case ids: "
            + ", ".join(repr(item) for item in invalid_risk_surfaces)
        )
    normalized_risk_surfaces = list(dict.fromkeys(raw_risk_surfaces))

    block = {
        "id": block_id,
        "title": title,
        "kind": kind,
        "depends_on": list(dict.fromkeys(depends_on)),
        "status": "planned",
        "artifact": f"blocks/{block_id}.md",
        "semantic_index": f"blocks/{block_id}.index.json",
        "review": f"reviews/{block_id}.md",
        "kernel_revision": None,
        "kernel_sha256": None,
        "artifact_sha256": None,
        "index_sha256": None,
        "review_sha256": None,
        "review_history": [],
        "risk_surfaces": normalized_risk_surfaces,
        "risk_preflight": None,
        "remediation_contract": REMEDIATION_CONTRACT_V2,
        "remediation_epoch": 1,
        "remediations": [],
        "active_remediation": None,
        "status_before_stale": None,
        "note": None,
        "updated_at": now_utc(),
    }
    ledger["blocks"].append(block)
    ledger["blocks"].sort(key=lambda item: item["id"])
    ensure_acyclic(ledger)

    write_template(
        case_file(root, block["artifact"]),
        f"# {block_id} — {title}\n\n"
        "## Block contract\n\nVIGERS_TODO\n\n"
        "## Analysis\n\nVIGERS_TODO\n\n"
        "## Assumptions and open questions\n\nVIGERS_TODO\n",
    )
    atomic_json(
        case_file(root, block["semantic_index"]),
        {
            "schema": SCHEMA_VERSION,
            "block_id": block_id,
            "kernel_revision": None,
            "definitions": [],
            "trace": [],
        },
    )
    write_template(
        case_file(root, block["review"]),
        f"# Review {block_id}\n\nVIGERS_TODO\n",
    )
    manifest["events"].append(
        event(
            "block_added",
            block_id=block_id,
            kind_name=kind,
            risk_surfaces=normalized_risk_surfaces,
        )
    )
    save_case(root, manifest, ledger)


def declare_block_risks(
    root: Path,
    manifest: dict[str, Any],
    ledger: dict[str, Any],
    *,
    block_id: str,
    risk_surfaces: list[str],
    reason: str,
) -> list[str]:
    """Add newly evidenced risk surfaces without hand-editing the semantic ledger."""
    if active_bounded_recovery(manifest) is not None:
        raise CaseError("Declaring new risks requires stopping bounded recovery")
    ensure_kernel_synced(root, manifest)
    blocks = blocks_by_id(ledger)
    if block_id not in blocks:
        raise CaseError(f"Unknown block: {block_id}")
    if not reason.strip():
        raise CaseError("Declaring block risk requires a reason")
    if not risk_surfaces:
        raise CaseError("Declare at least one --risk-surface")
    invalid = sorted(
        (
            surface
            for surface in risk_surfaces
            if not isinstance(surface, str) or not RISK_SURFACE_RE.fullmatch(surface)
        ),
        key=repr,
    )
    if invalid:
        raise CaseError(
            "Risk surfaces must use stable lowercase kebab-case ids: "
            + ", ".join(repr(item) for item in invalid)
        )
    block = blocks[block_id]
    if block.get("status") in {"analyzed", "reviewed", "integrated"}:
        raise CaseError(
            f"{block_id}: refresh the kernel with explicit semantic/architecture impact "
            "before adding risk to an already analyzed block"
        )
    current = list(block.get("risk_surfaces", []))
    added = [surface for surface in dict.fromkeys(risk_surfaces) if surface not in current]
    if not added:
        return current
    block["risk_surfaces"] = [*current, *added]
    preflight = block.get("risk_preflight")
    if isinstance(preflight, dict):
        preflight["status"] = "stale"
        preflight["stale_reason"] = "risk-scope-expanded"
    if block.get("status") == "in_progress":
        block["status"] = "blocked"
        block["note"] = "new risk surfaces require risk preflight before authoring resumes"
    block["updated_at"] = now_utc()
    manifest["events"].append(
        event(
            "block_risk_declared",
            block_id=block_id,
            added=added,
            risk_surfaces=block["risk_surfaces"],
            reason=reason.strip(),
        )
    )
    save_case(root, manifest, ledger)
    return list(block["risk_surfaces"])


def current_kernel(root: Path, manifest: dict[str, Any]) -> tuple[Path, str]:
    """Return the current kernel file and hash."""
    path = case_file(root, manifest["kernel"]["path"])
    if not path.is_file():
        raise CaseError(f"Missing kernel: {path}")
    return path, sha256(path)


def ensure_kernel_synced(root: Path, manifest: dict[str, Any]) -> None:
    """Require explicit refresh after a kernel edit."""
    _, current_hash = current_kernel(root, manifest)
    if current_hash != manifest["kernel"]["sha256"]:
        raise CaseError("kernel.md changed; run refresh-kernel before continuing")


def downstream_closure(ledger: dict[str, Any], seeds: set[str]) -> set[str]:
    """Return selected blocks and every dependent block."""
    affected = set(seeds)
    changed = True
    while changed:
        changed = False
        for block in ledger["blocks"]:
            if block["id"] not in affected and affected.intersection(block["depends_on"]):
                affected.add(block["id"])
                changed = True
    return affected


def archive_passed_gate(
    manifest: dict[str, Any],
    gate_name: str,
    *,
    reason: str,
) -> None:
    """Preserve one passed gate before invalidation so bounded re-review can reuse it."""
    gate = manifest.get("gates", {}).get(gate_name)
    if not isinstance(gate, dict) or gate.get("status") != "pass":
        return
    history_by_gate = manifest.setdefault("gate_history", {})
    if not isinstance(history_by_gate, dict):
        raise CaseError("manifest gate_history must be an object")
    history = history_by_gate.setdefault(gate_name, [])
    if not isinstance(history, list):
        raise CaseError(f"manifest gate_history.{gate_name} must be an array")
    snapshot = json.loads(json.dumps(gate, ensure_ascii=False))
    if history and isinstance(history[-1], dict):
        latest = history[-1]
        if (
            latest.get("subject_sha256") == snapshot.get("subject_sha256")
            and latest.get("evidence_sha256") == snapshot.get("evidence_sha256")
        ):
            return
    snapshot["archived_at"] = now_utc()
    snapshot["archive_reason"] = reason
    history.append(snapshot)


def gate_history_errors(root: Path, manifest: dict[str, Any]) -> list[str]:
    """Validate archived whole-case review states and their immutable evidence."""
    history_by_gate = manifest.get("gate_history", {})
    if not isinstance(history_by_gate, dict):
        return ["manifest gate_history must be an object"]
    errors: list[str] = []
    for gate_name, history in history_by_gate.items():
        if gate_name not in REVISIONED_REVIEW_GATES or not isinstance(history, list):
            errors.append(f"manifest gate_history.{gate_name} is invalid")
            continue
        for index, snapshot in enumerate(history, start=1):
            label = f"gate history {gate_name} r{index:03d}"
            if not isinstance(snapshot, dict) or snapshot.get("status") != "pass":
                errors.append(f"{label} is not a passed gate snapshot")
                continue
            evidence = snapshot.get("evidence")
            if not isinstance(evidence, str):
                errors.append(f"{label} has no evidence")
                continue
            path = case_file(root, evidence)
            if not artifact_ready(path):
                errors.append(f"{label} evidence is missing")
            elif sha256(path) != snapshot.get("evidence_sha256"):
                errors.append(f"{label} evidence changed after archive")
            if not SHA256_RE.fullmatch(str(snapshot.get("subject_sha256", ""))):
                errors.append(f"{label} has invalid subject hash")
            if snapshot.get("semantic_snapshot") is not None and not isinstance(
                snapshot.get("semantic_snapshot"), dict
            ):
                errors.append(f"{label} has invalid semantic snapshot")
    return errors


def refresh_kernel(
    root: Path,
    manifest: dict[str, Any],
    ledger: dict[str, Any],
    affected_ids: list[str],
    *,
    change_scope: str | None = None,
    invalidate_all: bool = False,
    reason: str | None = None,
) -> list[str]:
    """Advance kernel revision with explicit impact for new assurance-aware cases."""
    if active_bounded_recovery(manifest) is not None:
        raise CaseError("Kernel refresh is forbidden during bounded recovery")
    _, current_hash = current_kernel(root, manifest)
    if current_hash == manifest["kernel"]["sha256"]:
        return []

    blocks = blocks_by_id(ledger)
    legacy_refresh = change_scope is None
    if change_scope is not None and change_scope not in CHANGE_SCOPES:
        raise CaseError(f"Invalid kernel change scope: {change_scope!r}")
    if change_scope in {"editorial", "projection-only"}:
        if affected_ids or invalidate_all:
            raise CaseError(f"{change_scope} kernel refresh cannot invalidate semantic blocks")
        seeds: set[str] = set()
    elif change_scope == "semantic-local":
        if invalidate_all:
            raise CaseError("semantic-local refresh uses --affects, not --invalidate-all")
        if blocks and not affected_ids:
            raise CaseError("semantic-local refresh requires at least one --affects block")
        seeds = set(affected_ids)
    elif change_scope in {"semantic-crosscutting", "architecture"}:
        if not invalidate_all:
            raise CaseError(f"{change_scope} refresh requires explicit --invalidate-all")
        if affected_ids:
            raise CaseError(f"{change_scope} refresh cannot combine --affects and --invalidate-all")
        seeds = set(blocks)
    else:
        # Backward compatibility for existing callers and legacy runtime cases.
        seeds = set(affected_ids) if affected_ids else set(blocks)
    unknown = sorted(seeds - set(blocks))
    if unknown:
        raise CaseError(f"Unknown affected blocks: {', '.join(unknown)}")
    affected = downstream_closure(ledger, seeds)

    root_cause_resets: list[str] = []
    if change_scope in {"semantic-crosscutting", "architecture"}:
        for block_id in sorted(affected):
            block = blocks[block_id]
            if block.get("remediation_contract") != REMEDIATION_CONTRACT_V2:
                continue
            epoch = block.get("remediation_epoch", 1)
            used = sum(
                1
                for remediation in block.get("remediations", [])
                if isinstance(remediation, dict) and remediation.get("epoch", 1) == epoch
            )
            if used == 0:
                continue
            block["remediation_epoch"] = epoch + 1
            root_cause_resets.append(block_id)

    previous_assurance = assurance_level(manifest)
    escalated_assurance = previous_assurance
    if change_scope == "architecture" and previous_assurance != "high":
        escalated_assurance = "high"
    elif (
        change_scope in {"semantic-local", "semantic-crosscutting"}
        and previous_assurance == "lite"
    ):
        escalated_assurance = "standard"
    if escalated_assurance != previous_assurance:
        manifest["assurance_level"] = escalated_assurance
        for gate_name in ("global_review", "project_conformance"):
            gate = manifest["gates"][gate_name]
            if gate.get("status") == "not_required":
                gate.update(status="pending", note="assurance escalated after semantic delta")
        if escalated_assurance == "high" and manifest.get("mode") == "block":
            gate = manifest["gates"]["integration_review"]
            if gate.get("status") == "not_required":
                gate.update(status="pending", note="high assurance requires separate integration review")
        manifest["events"].append(
            event(
                "assurance_escalated",
                previous_assurance=previous_assurance,
                assurance_level=escalated_assurance,
                change_scope=change_scope,
                reason=reason.strip() if isinstance(reason, str) and reason.strip() else None,
            )
        )

    manifest["kernel"]["revision"] += 1
    manifest["kernel"]["sha256"] = current_hash
    stale: list[str] = []
    for block_id in sorted(affected):
        block = blocks[block_id]
        risk_preflight = block.get("risk_preflight")
        if isinstance(risk_preflight, dict) and risk_preflight.get("status") == "pass":
            risk_preflight["status"] = "stale"
            risk_preflight["stale_reason"] = change_scope or "legacy-full"
        if block["status"] in {"in_progress", "analyzed", "reviewed", "integrated"}:
            block["status_before_stale"] = block["status"]
            block["status"] = "stale"
            block["note"] = f"kernel revision changed to {manifest['kernel']['revision']}"
            block["updated_at"] = now_utc()
            stale.append(block_id)

    rebased: list[str] = []
    for block_id, block in sorted(blocks.items()):
        if block_id in affected:
            continue
        risk_preflight = block.get("risk_preflight")
        if isinstance(risk_preflight, dict) and risk_preflight.get("status") == "pass":
            risk_preflight["kernel_revision"] = manifest["kernel"]["revision"]
            risk_preflight["kernel_sha256"] = current_hash
        if block.get("status") in {"analyzed", "reviewed", "integrated"}:
            block["kernel_revision"] = manifest["kernel"]["revision"]
            block["kernel_sha256"] = current_hash
            rebased.append(block_id)

    if stale or change_scope in {"semantic-crosscutting", "architecture"}:
        invalidated_gates = [
            "author_passes",
            "semantic_integration",
            "consistency",
            "integration_review",
            "global_review",
            "project_conformance",
        ]
        if legacy_refresh or change_scope == "architecture":
            invalidated_gates.extend(("architecture_design", "architecture_conformance"))
        for gate_name in invalidated_gates:
            gate = manifest["gates"][gate_name]
            if gate["status"] != "not_required":
                if gate_name in REVISIONED_REVIEW_GATES:
                    archive_passed_gate(
                        manifest,
                        gate_name,
                        reason=f"kernel changed: {change_scope or 'legacy-full'}",
                    )
                gate.update(
                    status="pending",
                    evidence=None,
                    note=f"kernel changed: {change_scope or 'legacy-full'}",
                )
                gate["evidence_sha256"] = None
                gate["subject_sha256"] = None
    manifest["events"].append(
        event(
            "kernel_refreshed",
            revision=manifest["kernel"]["revision"],
            affected=sorted(affected),
            stale=stale,
            rebased=rebased,
            change_scope=change_scope or "legacy-full",
            invalidate_all=invalidate_all,
            reason=reason.strip() if isinstance(reason, str) and reason.strip() else None,
        )
    )
    for block_id in root_cause_resets:
        manifest["events"].append(
            event(
                "remediation_root_cause_reset",
                block_id=block_id,
                remediation_epoch=blocks[block_id]["remediation_epoch"],
                change_scope=change_scope,
                reason=reason.strip() if isinstance(reason, str) and reason.strip() else None,
            )
        )
    save_case(root, manifest, ledger)
    return stale


def validate_index(path: Path, expected_block: str) -> tuple[list[str], list[dict[str, Any]]]:
    """Validate one semantic sidecar and return ids and trace rows."""
    payload = read_json(path)
    errors: list[str] = []
    if payload.get("schema") != SCHEMA_VERSION:
        errors.append(f"{path.name}: unsupported schema")
    if payload.get("block_id") != expected_block:
        errors.append(f"{path.name}: block_id must be {expected_block}")
    definitions = payload.get("definitions")
    traces = payload.get("trace")
    if not isinstance(definitions, list):
        errors.append(f"{path.name}: definitions must be an array")
        definitions = []
    if not isinstance(traces, list):
        errors.append(f"{path.name}: trace must be an array")
        traces = []

    ids: list[str] = []
    for definition in definitions:
        if not isinstance(definition, dict):
            errors.append(f"{path.name}: each definition must be an object")
            continue
        semantic_id = definition.get("id")
        kind = definition.get("kind")
        summary = definition.get("summary")
        match = SEMANTIC_ID_RE.fullmatch(semantic_id or "")
        if not match or match.group(2) != expected_block:
            errors.append(f"{path.name}: invalid semantic id {semantic_id!r}")
        if kind not in SEMANTIC_KIND_PREFIX:
            errors.append(f"{path.name}: invalid semantic kind {kind!r}")
        elif match and match.group(1) != SEMANTIC_KIND_PREFIX[kind]:
            errors.append(f"{path.name}: id {semantic_id!r} does not match kind {kind!r}")
        if not isinstance(summary, str) or not summary.strip():
            errors.append(f"{path.name}: {semantic_id!r} needs a summary")
        source_refs = definition.get("source_refs", [])
        if not isinstance(source_refs, list) or not all(
            isinstance(item, str) and item.strip() for item in source_refs
        ):
            errors.append(f"{path.name}: {semantic_id!r} has invalid source_refs")
        if isinstance(semantic_id, str):
            ids.append(semantic_id)

    for trace in traces:
        if not isinstance(trace, dict):
            errors.append(f"{path.name}: each trace row must be an object")
            continue
        if not isinstance(trace.get("from"), str):
            errors.append(f"{path.name}: trace.from must be a string")
        targets = trace.get("to")
        if not isinstance(targets, list) or not targets or not all(
            isinstance(item, str) for item in targets
        ):
            errors.append(f"{path.name}: trace.to must be a non-empty string array")
    if errors:
        raise CaseError("\n".join(errors))
    return ids, traces


def immutable_copy(source: Path, target: Path) -> None:
    """Copy one case artifact without allowing an existing revision to change."""
    if target.exists():
        raise CaseError(f"Immutable history artifact already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    shutil.copy2(source, temporary)
    temporary.replace(target)


def required_risk_pairs(
    manifest: dict[str, Any],
    ledger: dict[str, Any],
) -> set[tuple[str, str]]:
    """Return risk pairs whose block has no current passed preflight binding."""
    required: set[tuple[str, str]] = set()
    current_kernel = manifest.get("kernel", {}).get("sha256")
    for block in ledger.get("blocks", []):
        if not isinstance(block, dict):
            continue
        surfaces = block.get("risk_surfaces", [])
        binding = block.get("risk_preflight")
        is_current = (
            isinstance(binding, dict)
            and binding.get("status") == "pass"
            and binding.get("kernel_sha256") == current_kernel
        )
        if is_current:
            continue
        required.update(
            (str(block.get("id")), surface)
            for surface in surfaces
            if isinstance(surface, str)
        )
    return required


def risk_preflight_subject_hash(
    manifest: dict[str, Any],
    ledger: dict[str, Any],
) -> str:
    """Hash only the risk assignment that still needs architecture coverage."""
    required_blocks = {block_id for block_id, _ in required_risk_pairs(manifest, ledger)}
    scope = [
        {
            "block_id": block.get("id"),
            "title": block.get("title"),
            "depends_on": block.get("depends_on", []),
            "risk_surfaces": sorted(block.get("risk_surfaces", [])),
        }
        for block in sorted(ledger.get("blocks", []), key=lambda item: item.get("id", ""))
        if isinstance(block, dict) and block.get("id") in required_blocks
    ]
    payload = {
        "contract": "risk-preflight-v1",
        "case_id": manifest.get("case_id"),
        "kernel_sha256": manifest.get("kernel", {}).get("sha256"),
        "scope": scope,
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def declared_risk_pairs(ledger: dict[str, Any]) -> set[tuple[str, str]]:
    """Return every block/surface pair declared by the semantic DAG."""
    return {
        (str(block.get("id")), surface)
        for block in ledger.get("blocks", [])
        if isinstance(block, dict)
        for surface in block.get("risk_surfaces", [])
        if isinstance(surface, str)
    }


def agent_run_by_id(
    root: Path,
    manifest: dict[str, Any],
    run_id: str,
) -> dict[str, Any]:
    """Resolve one validated observability run used by a machine gate."""
    relative = manifest.get("artifacts", {}).get("agent_ledger")
    if not isinstance(relative, str):
        raise CaseError("Case has no agent ledger for risk-gate provenance")
    payload = read_json(case_file(root, relative))
    errors = validate_agent_ledger(payload, case_id=str(manifest.get("case_id")))
    if errors:
        raise CaseError("agent-ledger.json is invalid: " + "; ".join(errors))
    matches = [
        run
        for run in payload.get("runs", [])
        if isinstance(run, dict) and run.get("run_id") == run_id
    ]
    if len(matches) != 1:
        raise CaseError(f"Agent run not found: {run_id}")
    return matches[0]


def validate_risk_preflight_payload(
    root: Path,
    manifest: dict[str, Any],
    ledger: dict[str, Any],
    payload: Any,
) -> list[dict[str, Any]]:
    """Validate one complete high-risk architecture matrix and its agent provenance."""
    if not isinstance(payload, dict):
        raise CaseError("Risk preflight must be a JSON object")
    if payload.get("schema") != RISK_PREFLIGHT_SCHEMA:
        raise CaseError("Risk preflight schema is invalid")
    if payload.get("case_id") != manifest.get("case_id"):
        raise CaseError("Risk preflight case_id mismatch")
    if payload.get("kernel_sha256") != manifest.get("kernel", {}).get("sha256"):
        raise CaseError("Risk preflight is stale against kernel")
    expected = required_risk_pairs(manifest, ledger)
    if not expected:
        raise CaseError("Risk preflight is not required: every declared surface is current")
    run_id = payload.get("agent_run_id")
    if not isinstance(run_id, str) or not AGENT_RUN_ID_RE.fullmatch(run_id):
        raise CaseError("Risk preflight requires a valid agent_run_id")
    run = agent_run_by_id(root, manifest, run_id)
    if (
        run.get("role") != "solution-architect"
        or run.get("role_mode") != "risk-preflight"
        or run.get("subject_sha256") != risk_preflight_subject_hash(manifest, ledger)
        or run.get("status") != "completed"
    ):
        raise CaseError(
            "Risk preflight agent run must be a completed solution-architect "
            "risk-preflight run for the current subject"
        )
    decisions = payload.get("decisions")
    if not isinstance(decisions, list) or not decisions or any(
        not isinstance(item, str) or not item.strip() for item in decisions
    ):
        raise CaseError("Risk preflight requires at least one concrete decision")
    if payload.get("unresolved") != []:
        raise CaseError("Risk preflight cannot pass with unresolved risk decisions")
    coverage = payload.get("coverage")
    if not isinstance(coverage, list):
        raise CaseError("Risk preflight coverage must be an array")
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for index, item in enumerate(coverage, start=1):
        if not isinstance(item, dict):
            raise CaseError(f"Risk preflight coverage row {index} must be an object")
        block_id = item.get("block_id")
        surface = item.get("surface")
        pair = (block_id, surface)
        if not isinstance(block_id, str) or not isinstance(surface, str) or pair not in expected:
            raise CaseError(f"Risk preflight coverage row {index} names an unknown surface")
        if pair in seen:
            raise CaseError(f"Risk preflight duplicates {block_id}/{surface}")
        seen.add(pair)
        status = item.get("status")
        if status not in {"covered", "not-applicable"}:
            raise CaseError(f"Risk preflight {block_id}/{surface} has invalid status")
        rationale = item.get("rationale")
        if not isinstance(rationale, str) or not rationale.strip():
            raise CaseError(f"Risk preflight {block_id}/{surface} requires rationale")
        evidence_refs = item.get("evidence_refs")
        if not isinstance(evidence_refs, list) or any(
            not isinstance(ref, str) or not ref.strip() for ref in evidence_refs
        ):
            raise CaseError(f"Risk preflight {block_id}/{surface} has invalid evidence_refs")
        if status == "covered" and not evidence_refs:
            raise CaseError(f"Risk preflight {block_id}/{surface} requires evidence_refs")
        normalized.append(
            {
                "block_id": block_id,
                "surface": surface,
                "status": status,
                "rationale": rationale.strip(),
                "evidence_refs": list(evidence_refs),
            }
        )
    missing = sorted(expected - seen)
    if missing:
        raise CaseError(
            "Risk preflight does not cover: "
            + ", ".join(f"{block_id}/{surface}" for block_id, surface in missing)
        )
    return sorted(normalized, key=lambda item: (item["block_id"], item["surface"]))


def record_risk_preflight(
    root: Path,
    manifest: dict[str, Any],
    ledger: dict[str, Any],
    *,
    evidence: str,
) -> dict[str, Any]:
    """Bind one complete risk-first architecture pass before high-risk authoring."""
    if active_bounded_recovery(manifest) is not None:
        raise CaseError("Risk preflight is forbidden during bounded recovery")
    ensure_kernel_synced(root, manifest)
    evidence_path = case_file(root, evidence)
    if not artifact_ready(evidence_path):
        raise CaseError(f"Risk preflight evidence is missing or incomplete: {evidence}")
    try:
        payload = read_json(evidence_path)
    except CaseError as exc:
        raise CaseError(f"Invalid risk preflight evidence: {exc}") from exc
    evidence_sha256 = sha256(evidence_path)
    history = ledger.setdefault("risk_preflight_history", [])
    if not isinstance(history, list):
        raise CaseError("ledger risk_preflight_history must be an array")
    required = required_risk_pairs(manifest, ledger)
    if not required:
        if history:
            latest = history[-1]
            if (
                isinstance(latest, dict)
                and latest.get("source_sha256") == evidence_sha256
            ):
                return latest
        raise CaseError("Risk preflight is not required: every declared surface is current")
    coverage = validate_risk_preflight_payload(root, manifest, ledger, payload)
    subject_sha256 = risk_preflight_subject_hash(manifest, ledger)
    if history:
        latest = history[-1]
        if (
            isinstance(latest, dict)
            and latest.get("subject_sha256") == subject_sha256
            and latest.get("source_sha256") == evidence_sha256
        ):
            return latest
    revision = len(history) + 1
    snapshot = f"reviews/history/risk-preflight-r{revision:03d}.json"
    immutable_copy(evidence_path, case_file(root, snapshot))
    record = {
        "revision": revision,
        "recorded_at": now_utc(),
        "agent_run_id": payload["agent_run_id"],
        "subject_sha256": subject_sha256,
        "kernel_revision": manifest["kernel"]["revision"],
        "kernel_sha256": manifest["kernel"]["sha256"],
        "source": evidence,
        "source_sha256": evidence_sha256,
        "evidence": snapshot,
        "evidence_sha256": sha256(case_file(root, snapshot)),
        "coverage": coverage,
    }
    history.append(record)
    covered_blocks = {str(item["block_id"]) for item in coverage}
    blocks = blocks_by_id(ledger)
    for block_id in sorted(covered_blocks):
        block = blocks[block_id]
        block["risk_preflight"] = {
            "status": "pass",
            "revision": revision,
            "evidence": snapshot,
            "evidence_sha256": record["evidence_sha256"],
            "subject_sha256": subject_sha256,
            "kernel_revision": manifest["kernel"]["revision"],
            "kernel_sha256": manifest["kernel"]["sha256"],
        }
    manifest["events"].append(
        event(
            "risk_preflight_recorded",
            revision=revision,
            subject_sha256=subject_sha256,
            blocks=sorted(covered_blocks),
            evidence=snapshot,
            agent_run_id=payload["agent_run_id"],
        )
    )
    save_case(root, manifest, ledger)
    return record


def risk_preflight_state_errors(
    root: Path,
    manifest: dict[str, Any],
    ledger: dict[str, Any],
) -> list[str]:
    """Validate immutable risk-preflight history and active block bindings."""
    errors: list[str] = []
    history = ledger.get("risk_preflight_history", [])
    if not isinstance(history, list):
        return ["ledger risk_preflight_history must be an array"]
    history_by_revision: dict[int, dict[str, Any]] = {}
    for index, record in enumerate(history, start=1):
        label = f"risk preflight r{index:03d}"
        if not isinstance(record, dict) or record.get("revision") != index:
            errors.append(f"{label} has invalid revision metadata")
            continue
        history_by_revision[index] = record
        relative = record.get("evidence")
        if not isinstance(relative, str) or not relative.startswith("reviews/history/"):
            errors.append(f"{label} has invalid evidence path")
            continue
        path = case_file(root, relative)
        if not path.is_file():
            errors.append(f"{label} evidence is missing")
        elif sha256(path) != record.get("evidence_sha256"):
            errors.append(f"{label} evidence changed after snapshot")
        if not SHA256_RE.fullmatch(str(record.get("subject_sha256", ""))):
            errors.append(f"{label} has invalid subject hash")
    for block in ledger.get("blocks", []):
        if not isinstance(block, dict):
            continue
        block_id = str(block.get("id", "<unknown>"))
        surfaces = block.get("risk_surfaces", [])
        if not isinstance(surfaces, list) or any(
            not isinstance(surface, str) or not RISK_SURFACE_RE.fullmatch(surface)
            for surface in surfaces
        ):
            errors.append(f"{block_id}: invalid risk_surfaces")
            continue
        if len(surfaces) != len(set(surfaces)):
            errors.append(f"{block_id}: duplicate risk_surfaces")
            continue
        binding = block.get("risk_preflight")
        if not surfaces:
            if binding is not None:
                errors.append(f"{block_id}: risk preflight exists without declared surfaces")
            continue
        if block.get("status") not in {"in_progress", "analyzed", "reviewed", "integrated"}:
            continue
        if not isinstance(binding, dict) or binding.get("status") != "pass":
            errors.append(f"{block_id}: required risk preflight is not passed")
            continue
        revision = binding.get("revision")
        record = history_by_revision.get(revision)
        if record is None or record.get("evidence") != binding.get("evidence"):
            errors.append(f"{block_id}: risk preflight revision does not resolve")
        if binding.get("kernel_sha256") != manifest.get("kernel", {}).get("sha256"):
            errors.append(f"{block_id}: risk preflight is stale against kernel")
        path = case_file(root, str(binding.get("evidence", "")))
        if not path.is_file() or sha256(path) != binding.get("evidence_sha256"):
            errors.append(f"{block_id}: risk preflight evidence is missing or changed")
    return errors


def risk_review_errors(
    root: Path,
    manifest: dict[str, Any],
    block: dict[str, Any],
    report_path: Path,
) -> list[str]:
    """Require one complete surface sweep and bound reviewer telemetry for risk blocks."""
    surfaces = block.get("risk_surfaces", [])
    if not surfaces:
        return []
    text = report_path.read_text(encoding="utf-8")
    errors: list[str] = []
    run_match = re.search(r"(?m)^\s*review_agent_run\s*:\s*(AR-[0-9]{4,})\s*$", text)
    if not run_match:
        errors.append("review_agent_run is required for a risk review")
    else:
        try:
            run = agent_run_by_id(root, manifest, run_match.group(1))
            if (
                run.get("role") != "spec-reviewer"
                or run.get("role_mode") != "block"
                or run.get("subject_sha256") != block_review_subject_hash(root, manifest, block)
                or run.get("status") != "completed"
            ):
                errors.append("review_agent_run does not match the current block review subject")
        except CaseError as exc:
            errors.append(str(exc))
    remediation = active_block_remediation(block)
    if remediation is not None and remediation.get("scope") == "targeted":
        return errors
    scope_match = re.search(r"(?m)^\s*review_scope\s*:\s*(\S+)\s*$", text)
    if not scope_match or scope_match.group(1) != "full-block":
        errors.append("risk review_scope must be full-block")
    batch_match = re.search(r"(?m)^\s*finding_batch_complete\s*:\s*(\S+)\s*$", text)
    if not batch_match or batch_match.group(1).lower() != "true":
        errors.append("finding_batch_complete must be true")
    rows = re.findall(
        r"(?m)^\s*risk_surface\s*:\s*([a-z][a-z0-9-]{1,63})\s*=\s*(\S+)\s*$",
        text,
    )
    found: dict[str, str] = {}
    for surface, outcome in rows:
        if surface in found:
            errors.append(f"risk_surface duplicates {surface}")
            continue
        found[surface] = outcome
        if outcome not in {"pass", "not-applicable"} and not FINDING_ID_RE.fullmatch(outcome):
            errors.append(f"risk_surface {surface} has invalid outcome")
    missing = sorted(set(surfaces) - set(found))
    unknown = sorted(set(found) - set(surfaces))
    if missing:
        errors.append("risk review does not cover: " + ", ".join(missing))
    if unknown:
        errors.append("risk review names undeclared surfaces: " + ", ".join(unknown))
    return errors


def risk_review_open_findings(
    block: dict[str, Any],
    report_path: Path,
) -> list[str]:
    """Return finding ids from a full risk sweep that still require disposition."""
    remediation = active_block_remediation(block)
    if remediation is not None and remediation.get("scope") == "targeted":
        return []
    outcomes = re.findall(
        r"(?m)^\s*risk_surface\s*:\s*[a-z][a-z0-9-]{1,63}\s*=\s*(\S+)\s*$",
        report_path.read_text(encoding="utf-8"),
    )
    return sorted(
        {
            outcome
            for outcome in outcomes
            if outcome not in {"pass", "not-applicable"}
            and FINDING_ID_RE.fullmatch(outcome)
        }
    )


def block_review_subject_hash(
    root: Path,
    manifest: dict[str, Any],
    block: dict[str, Any],
) -> str:
    """Hash the exact block subject attested by one local review revision."""
    digest = hashlib.sha256()
    digest.update(str(block.get("id", "")).encode("utf-8"))
    digest.update(str(manifest.get("kernel", {}).get("sha256", "")).encode("ascii"))
    for field in ("artifact", "semantic_index"):
        relative = block.get(field)
        if not isinstance(relative, str):
            digest.update(b"<missing-path>")
            continue
        path = case_file(root, relative)
        digest.update(relative.encode("utf-8"))
        digest.update(path.read_bytes() if path.is_file() else b"<missing>")
    return digest.hexdigest()


def record_block_review_revision(
    root: Path,
    manifest: dict[str, Any],
    block: dict[str, Any],
    *,
    outcome: str,
    remediation_id: str | None = None,
) -> dict[str, Any]:
    """Snapshot one local review so a later retry cannot erase prior coverage."""
    source = case_file(root, block["review"])
    if not artifact_ready(source):
        raise CaseError(f"{block['id']}: review artifact is missing or still a placeholder")
    history = block.setdefault("review_history", [])
    if not isinstance(history, list):
        raise CaseError(f"{block['id']}: review_history must be an array")
    subject_hash = block_review_subject_hash(root, manifest, block)
    evidence_hash = sha256(source)
    if history:
        latest = history[-1]
        if (
            isinstance(latest, dict)
            and latest.get("subject_sha256") == subject_hash
            and latest.get("evidence_sha256") == evidence_hash
            and latest.get("outcome") == outcome
            and latest.get("remediation_id") == remediation_id
        ):
            return latest
    revision = len(history) + 1
    suffix = source.suffix or ".md"
    relative = f"reviews/history/{block['id']}-r{revision:03d}{suffix}"
    target = case_file(root, relative)
    immutable_copy(source, target)
    record = {
        "revision": revision,
        "recorded_at": now_utc(),
        "outcome": outcome,
        "evidence": relative,
        "evidence_sha256": evidence_hash,
        "subject_sha256": subject_hash,
        "remediation_id": remediation_id,
    }
    history.append(record)
    return record


def parse_remediation_findings(values: list[str]) -> list[dict[str, str]]:
    """Parse repeated FINDING=severity CLI values into a stable record."""
    findings: list[dict[str, str]] = []
    seen: set[str] = set()
    for value in values:
        finding_id, separator, severity = value.rpartition("=")
        if not separator or not FINDING_ID_RE.fullmatch(finding_id):
            raise CaseError(
                "Each --finding must use FINDING_ID=blocker|major with a stable id"
            )
        if severity not in REMEDIATION_SEVERITIES:
            raise CaseError(f"Invalid remediation severity for {finding_id}: {severity}")
        if finding_id in seen:
            raise CaseError(f"Duplicate remediation finding: {finding_id}")
        seen.add(finding_id)
        findings.append({"id": finding_id, "severity": severity})
    return findings


def begin_block_remediation(
    root: Path,
    manifest: dict[str, Any],
    ledger: dict[str, Any],
    *,
    block_id: str,
    findings: list[dict[str, str]],
    semantic_ids: list[str],
    evidence: str,
    reason: str,
    full_block: bool = False,
    batch_complete: bool = False,
) -> dict[str, Any]:
    """Open a bounded correction while preserving prior review and subject snapshots."""
    if active_bounded_recovery(manifest) is not None:
        raise CaseError(
            "Semantic remediation requires stopping bounded recovery and recording a new decision"
        )
    ensure_kernel_synced(root, manifest)
    blocks = blocks_by_id(ledger)
    if block_id not in blocks:
        raise CaseError(f"Unknown block: {block_id}")
    block = blocks[block_id]
    if block.get("status") not in {"analyzed", "reviewed", "integrated"}:
        raise CaseError(
            f"{block_id}: remediation requires analyzed, reviewed, or integrated status"
        )
    if not reason.strip():
        raise CaseError("Remediation requires a reason")
    if not findings:
        raise CaseError("Remediation requires at least one blocker or major finding")
    normalized_findings: list[dict[str, str]] = []
    finding_ids: set[str] = set()
    for item in findings:
        if not isinstance(item, dict):
            raise CaseError("Remediation findings must be objects")
        finding_id = item.get("id")
        severity = item.get("severity")
        if not isinstance(finding_id, str) or not FINDING_ID_RE.fullmatch(finding_id):
            raise CaseError(f"Invalid remediation finding id: {finding_id!r}")
        if severity not in REMEDIATION_SEVERITIES:
            raise CaseError(f"Invalid remediation severity for {finding_id}: {severity!r}")
        if finding_id in finding_ids:
            raise CaseError(f"Duplicate remediation finding: {finding_id}")
        finding_ids.add(finding_id)
        normalized_findings.append({"id": finding_id, "severity": str(severity)})

    scope = "full-block" if full_block else "targeted"
    unique_semantic_ids = list(dict.fromkeys(semantic_ids))
    current_ids, _ = validate_index(case_file(root, block["semantic_index"]), block_id)
    unknown_semantic_ids = sorted(set(unique_semantic_ids) - set(current_ids))
    if unknown_semantic_ids:
        raise CaseError(
            f"{block_id}: remediation names unknown semantic ids: "
            + ", ".join(unknown_semantic_ids)
        )
    if scope == "targeted" and not unique_semantic_ids:
        raise CaseError("Targeted remediation requires at least one --semantic-id")

    evidence_path = case_file(root, evidence)
    if not artifact_ready(evidence_path):
        raise CaseError(f"Remediation evidence is missing or incomplete: {evidence}")
    remediation_contract = block.get("remediation_contract", REMEDIATION_CONTRACT_V1)
    if remediation_contract == REMEDIATION_CONTRACT_V2 and not batch_complete:
        raise CaseError(
            f"{block_id}: confirm one complete accepted finding batch before remediation"
        )
    if block.get("risk_surfaces") and not block.get("review_history"):
        if evidence != block.get("review"):
            raise CaseError(
                f"{block_id}: first risk remediation must use the complete local block review"
            )
        initial_review_errors = risk_review_errors(
            root,
            manifest,
            block,
            evidence_path,
        )
        if initial_review_errors:
            raise CaseError(
                f"{block_id}: initial risk review is incomplete: "
                + "; ".join(initial_review_errors)
            )
    projection_errors = working_projection_errors(
        root,
        manifest,
        ledger,
        require_any_update=False,
        exclude_sources={block_id},
    )
    if projection_errors:
        raise CaseError(
            "Working projection is behind reviewed content: "
            + "; ".join(projection_errors)
        )

    remediations = block.setdefault("remediations", [])
    if not isinstance(remediations, list):
        raise CaseError(f"{block_id}: remediations must be an array")
    active_id = block.get("active_remediation")
    for previous in remediations:
        if isinstance(previous, dict) and previous.get("id") == active_id:
            if previous.get("status") == "in_progress":
                previous["status"] = "retry_required"
                previous["completed_at"] = now_utc()
            break
    remediation_epoch = block.get("remediation_epoch", 1)
    if remediation_contract == REMEDIATION_CONTRACT_V2:
        batches_in_epoch = [
            previous
            for previous in remediations
            if isinstance(previous, dict)
            and previous.get("epoch", 1) == remediation_epoch
        ]
        if len(batches_in_epoch) >= MAX_REMEDIATION_BATCHES:
            raise CaseError(
                f"{block_id}: remediation budget exhausted after "
                f"{MAX_REMEDIATION_BATCHES} batches; aggregate the root cause and "
                "refresh the kernel with semantic-crosscutting or architecture impact "
                "instead of starting another finding-by-finding review"
            )
        batch_index = len(batches_in_epoch) + 1
    else:
        batch_index = None
    same_finding_cycles = sum(
        1
        for previous in remediations
        if isinstance(previous, dict)
        and set(previous.get("finding_ids", [])) == finding_ids
        and previous.get("epoch", 1) == remediation_epoch
    )
    cycle = same_finding_cycles + 1
    if remediation_contract != REMEDIATION_CONTRACT_V2 and cycle > 2:
        raise CaseError(
            "The same blocker/major already used two targeted correction cycles; "
            "record user-decision instead of starting a third"
        )

    revision = len(remediations) + 1
    remediation_id = f"R{revision:03d}"
    baseline_artifact = f"blocks/history/{block_id}-{remediation_id}.md"
    baseline_index = f"blocks/history/{block_id}-{remediation_id}.index.json"
    evidence_suffix = evidence_path.suffix or ".md"
    evidence_snapshot = (
        f"reviews/history/{block_id}-{remediation_id}-finding{evidence_suffix}"
    )
    immutable_copy(case_file(root, block["artifact"]), case_file(root, baseline_artifact))
    immutable_copy(case_file(root, block["semantic_index"]), case_file(root, baseline_index))
    immutable_copy(evidence_path, case_file(root, evidence_snapshot))
    prior_review = None
    review_history = block.get("review_history")
    if isinstance(review_history, list) and review_history:
        latest_review = review_history[-1]
        if isinstance(latest_review, dict) and isinstance(latest_review.get("evidence"), str):
            prior_review = latest_review["evidence"]
    if prior_review is None:
        prior_review = evidence_snapshot

    remediation = {
        "id": remediation_id,
        "scope": scope,
        "status": "in_progress",
        "cycle": cycle,
        "epoch": remediation_epoch,
        "batch_index": batch_index,
        "finding_ids": sorted(finding_ids),
        "findings": normalized_findings,
        "finding_batch_complete": (
            True if remediation_contract == REMEDIATION_CONTRACT_V2 else None
        ),
        "semantic_ids": unique_semantic_ids,
        "reason": reason.strip(),
        "opened_at": now_utc(),
        "status_before": block.get("status"),
        "baseline_artifact": baseline_artifact,
        "baseline_artifact_sha256": sha256(case_file(root, baseline_artifact)),
        "baseline_index": baseline_index,
        "baseline_index_sha256": sha256(case_file(root, baseline_index)),
        "finding_evidence": evidence_snapshot,
        "finding_evidence_sha256": sha256(case_file(root, evidence_snapshot)),
        "coverage_evidence": prior_review if scope == "targeted" else None,
    }
    remediations.append(remediation)
    block["active_remediation"] = remediation_id
    block["status"] = "in_progress"
    block["review_sha256"] = None
    block["note"] = f"{scope} remediation {remediation_id}: {reason.strip()}"
    block["updated_at"] = now_utc()
    manifest["events"].append(
        event(
            "block_remediation_started",
            block_id=block_id,
            remediation_id=remediation_id,
            scope=scope,
            cycle=cycle,
            epoch=remediation_epoch,
            batch_index=batch_index,
            finding_ids=sorted(finding_ids),
            semantic_ids=unique_semantic_ids,
            evidence=evidence_snapshot,
            reason=reason.strip(),
        )
    )
    save_case(root, manifest, ledger)
    return remediation


def active_block_remediation(block: dict[str, Any]) -> dict[str, Any] | None:
    """Return the currently open remediation record, if any."""
    active_id = block.get("active_remediation")
    if not isinstance(active_id, str):
        return None
    for item in block.get("remediations", []):
        if isinstance(item, dict) and item.get("id") == active_id:
            return item
    return None


def semantic_delta_ids(root: Path, remediation: dict[str, Any], block: dict[str, Any]) -> set[str]:
    """Return semantic ids whose definition or trace row changed since remediation start."""
    baseline = read_json(case_file(root, remediation["baseline_index"]))
    current = read_json(case_file(root, block["semantic_index"]))

    def definitions(payload: Any) -> dict[str, str]:
        if not isinstance(payload, dict) or not isinstance(payload.get("definitions"), list):
            raise CaseError("Remediation semantic snapshot has invalid definitions")
        result: dict[str, str] = {}
        for item in payload["definitions"]:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                raise CaseError("Remediation semantic snapshot has an invalid definition")
            result[item["id"]] = json.dumps(item, ensure_ascii=False, sort_keys=True)
        return result

    before_definitions = definitions(baseline)
    after_definitions = definitions(current)
    changed = {
        semantic_id
        for semantic_id in set(before_definitions) | set(after_definitions)
        if before_definitions.get(semantic_id) != after_definitions.get(semantic_id)
    }

    def trace_rows(payload: Any) -> dict[str, dict[str, Any]]:
        if not isinstance(payload, dict) or not isinstance(payload.get("trace"), list):
            raise CaseError("Remediation semantic snapshot has invalid trace")
        result: dict[str, dict[str, Any]] = {}
        for item in payload["trace"]:
            if not isinstance(item, dict) or not isinstance(item.get("from"), str):
                raise CaseError("Remediation semantic snapshot has an invalid trace row")
            canonical = json.dumps(item, ensure_ascii=False, sort_keys=True)
            result[canonical] = item
        return result

    before_trace = trace_rows(baseline)
    after_trace = trace_rows(current)
    for canonical in set(before_trace) ^ set(after_trace):
        row = before_trace.get(canonical) or after_trace.get(canonical)
        if not isinstance(row, dict):
            continue
        source = row.get("from")
        if isinstance(source, str):
            changed.add(source)
        changed.update(item for item in row.get("to", []) if isinstance(item, str))
    return changed


def parse_report_list(text: str, field: str) -> list[str] | None:
    """Read one simple YAML-like inline list from a review report."""
    match = re.search(rf"(?m)^\s*{re.escape(field)}\s*:\s*\[([^\]]*)\]\s*$", text)
    if not match:
        return None
    return [
        item.strip().strip("'\"")
        for item in match.group(1).split(",")
        if item.strip().strip("'\"")
    ]


def report_scalar(text: str, field: str) -> str | None:
    """Read one simple machine-contract field from a Markdown report."""
    match = re.search(rf"(?m)^\s*{re.escape(field)}\s*:\s*([^\n]+?)\s*$", text)
    return match.group(1).strip().strip("'\"") if match else None


def completed_agent_run_errors(
    root: Path,
    manifest: dict[str, Any],
    *,
    run_id: str | None,
    role: str,
    role_mode: str,
    subject_sha256: str,
) -> list[str]:
    """Require one completed agent run bound to the exact recovery assignment."""
    if run_id is None or not AGENT_RUN_ID_RE.fullmatch(run_id):
        return ["report requires a valid agent_run_id"]
    relative = manifest.get("artifacts", {}).get("agent_ledger")
    if not isinstance(relative, str):
        return ["case has no agent ledger"]
    payload = read_json(case_file(root, relative))
    for run in payload.get("runs", []):
        if not isinstance(run, dict) or run.get("run_id") != run_id:
            continue
        errors: list[str] = []
        if run.get("role") != role or run.get("role_mode") != role_mode:
            errors.append("agent run role does not match recovery assignment")
        if run.get("subject_sha256") != subject_sha256:
            errors.append("agent run subject does not match recovery assignment")
        if run.get("status") != "completed":
            errors.append("recovery evidence requires a completed agent run")
        return errors
    return [f"agent run {run_id} is not recorded"]


def recovery_block_subject_hash(
    manifest: dict[str, Any],
    block: dict[str, Any],
    plan_sha256: str,
) -> str:
    """Hash exactly one frozen block recovery assignment."""
    digest = hashlib.sha256()
    for value in (
        "bounded-recovery-block-v1",
        str(manifest.get("case_id")),
        plan_sha256,
        str(manifest.get("kernel", {}).get("sha256")),
        str(block.get("id")),
        str(block.get("artifact_sha256")),
        str(block.get("index_sha256")),
    ):
        digest.update(value.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def recovery_block_review_errors(
    root: Path,
    manifest: dict[str, Any],
    ledger: dict[str, Any],
    block: dict[str, Any],
    report_path: Path,
) -> list[str]:
    """Validate exact-surface read-only evidence for one recovery block."""
    binding, plan = load_bounded_recovery(root, manifest, ledger, require_active=True)
    block_id = str(block.get("id"))
    expected_surfaces = plan["block_scopes"].get(block_id)
    if expected_surfaces is None:
        return [f"{block_id} is outside bounded recovery scope"]
    text = report_path.read_text(encoding="utf-8")
    subject = recovery_block_subject_hash(manifest, block, binding["sha256"])
    errors: list[str] = []
    expected_scalars = {
        "review_scope": "bounded-recovery",
        "recovery_plan_sha256": binding["sha256"],
        "recovery_block": block_id,
        "recovery_subject_sha256": subject,
        "new_findings_policy": "user-decision",
        "decision": "pass",
    }
    for field, expected in expected_scalars.items():
        if report_scalar(text, field) != expected:
            errors.append(f"recovery report requires {field}: {expected}")
    if parse_report_list(text, "reviewed_surfaces") != expected_surfaces:
        errors.append("recovery report reviewed_surfaces do not match the plan")
    if parse_report_list(text, "deferred_findings") != []:
        errors.append("recovery pass requires deferred_findings: []")
    errors.extend(
        completed_agent_run_errors(
            root,
            manifest,
            run_id=report_scalar(text, "agent_run_id"),
            role="spec-reviewer",
            role_mode="block",
            subject_sha256=subject,
        )
    )
    return errors


def remediation_review_errors(
    root: Path,
    block: dict[str, Any],
    report_path: Path,
) -> list[str]:
    """Validate bounded re-review markers and prevent undeclared semantic expansion."""
    remediation = active_block_remediation(block)
    if remediation is None:
        return []
    errors: list[str] = []
    expected_scope = (
        "targeted-remediation"
        if remediation.get("scope") == "targeted"
        else "full-block"
    )
    text = report_path.read_text(encoding="utf-8")
    scope_match = re.search(r"(?m)^\s*review_scope\s*:\s*(\S+)\s*$", text)
    if not scope_match or scope_match.group(1) != expected_scope:
        errors.append(f"review_scope must be {expected_scope}")
    verified = parse_report_list(text, "verified_findings")
    expected_findings = sorted(remediation.get("finding_ids", []))
    if verified is None or sorted(verified) != expected_findings:
        errors.append(
            "verified_findings must exactly match " + ", ".join(expected_findings)
        )
    coverage_match = re.search(r"(?m)^\s*coverage_reused\s*:\s*(\S+)\s*$", text)
    expected_coverage = (
        remediation.get("coverage_evidence")
        if remediation.get("scope") == "targeted"
        else "none"
    )
    if not coverage_match or coverage_match.group(1) != expected_coverage:
        errors.append(f"coverage_reused must be {expected_coverage}")
    if remediation.get("scope") == "targeted":
        changed = semantic_delta_ids(root, remediation, block)
        declared = set(remediation.get("semantic_ids", []))
        undeclared = sorted(changed - declared)
        if undeclared:
            errors.append(
                "targeted remediation changed undeclared semantic ids: "
                + ", ".join(undeclared)
            )
    return errors


def block_review_state_errors(root: Path, block: dict[str, Any]) -> list[str]:
    """Validate immutable local review history and remediation bindings."""
    block_id = str(block.get("id", "<unknown>"))
    errors: list[str] = []
    remediation_contract = block.get("remediation_contract", REMEDIATION_CONTRACT_V1)
    if remediation_contract not in {REMEDIATION_CONTRACT_V1, REMEDIATION_CONTRACT_V2}:
        errors.append(f"{block_id}: invalid remediation_contract")
    if remediation_contract == REMEDIATION_CONTRACT_V2:
        epoch = block.get("remediation_epoch")
        if not isinstance(epoch, int) or isinstance(epoch, bool) or epoch < 1:
            errors.append(f"{block_id}: invalid remediation_epoch")
    history = block.get("review_history", [])
    if not isinstance(history, list):
        return [f"{block_id}: review_history must be an array"]
    for index, record in enumerate(history, start=1):
        label = f"{block_id}: review history r{index:03d}"
        if not isinstance(record, dict) or record.get("revision") != index:
            errors.append(f"{label} has invalid revision metadata")
            continue
        relative = record.get("evidence")
        if not isinstance(relative, str) or not relative.startswith("reviews/history/"):
            errors.append(f"{label} has invalid evidence path")
            continue
        path = case_file(root, relative)
        if not path.is_file():
            errors.append(f"{label} evidence is missing")
        elif sha256(path) != record.get("evidence_sha256"):
            errors.append(f"{label} evidence changed after snapshot")
        if not SHA256_RE.fullmatch(str(record.get("subject_sha256", ""))):
            errors.append(f"{label} has invalid subject hash")

    remediations = block.get("remediations", [])
    if not isinstance(remediations, list):
        return errors + [f"{block_id}: remediations must be an array"]
    remediation_ids: set[str] = set()
    for index, remediation in enumerate(remediations, start=1):
        label = f"{block_id}: remediation R{index:03d}"
        if not isinstance(remediation, dict) or remediation.get("id") != f"R{index:03d}":
            errors.append(f"{label} has invalid identity")
            continue
        remediation_ids.add(remediation["id"])
        if remediation.get("scope") not in REMEDIATION_SCOPES:
            errors.append(f"{label} has invalid scope")
        if block.get("remediation_contract") == REMEDIATION_CONTRACT_V2:
            epoch = remediation.get("epoch")
            batch_index = remediation.get("batch_index")
            if remediation.get("finding_batch_complete") is not True:
                errors.append(f"{label} does not attest a complete finding batch")
            if not isinstance(epoch, int) or isinstance(epoch, bool) or epoch < 1:
                errors.append(f"{label} has invalid epoch")
            if (
                not isinstance(batch_index, int)
                or isinstance(batch_index, bool)
                or batch_index not in range(1, MAX_REMEDIATION_BATCHES + 1)
            ):
                errors.append(f"{label} has invalid batch_index")
        if remediation.get("status") not in {
            "in_progress",
            "retry_required",
            "verified",
        }:
            errors.append(f"{label} has invalid status")
        for field, hash_field, prefix in (
            ("baseline_artifact", "baseline_artifact_sha256", "blocks/history/"),
            ("baseline_index", "baseline_index_sha256", "blocks/history/"),
            ("finding_evidence", "finding_evidence_sha256", "reviews/history/"),
        ):
            relative = remediation.get(field)
            if not isinstance(relative, str) or not relative.startswith(prefix):
                errors.append(f"{label} has invalid {field}")
                continue
            path = case_file(root, relative)
            if not path.is_file():
                errors.append(f"{label} {field} is missing")
            elif sha256(path) != remediation.get(hash_field):
                errors.append(f"{label} {field} changed after snapshot")
        finding_ids = remediation.get("finding_ids")
        if not isinstance(finding_ids, list) or not finding_ids:
            errors.append(f"{label} has no findings")
        semantic_ids = remediation.get("semantic_ids")
        if remediation.get("scope") == "targeted" and (
            not isinstance(semantic_ids, list) or not semantic_ids
        ):
            errors.append(f"{label} has no targeted semantic ids")
    active = block.get("active_remediation")
    if active is not None and active not in remediation_ids:
        errors.append(f"{block_id}: active remediation does not resolve")
    if isinstance(active, str):
        active_record = next(
            (
                item
                for item in remediations
                if isinstance(item, dict) and item.get("id") == active
            ),
            None,
        )
        if active_record is not None and active_record.get("status") != "in_progress":
            errors.append(f"{block_id}: active remediation is not in progress")
    return errors


def transition_block(
    root: Path,
    manifest: dict[str, Any],
    ledger: dict[str, Any],
    *,
    block_id: str,
    new_status: str,
    note: str | None,
) -> None:
    """Apply one guarded block-state transition."""
    ensure_kernel_synced(root, manifest)
    blocks = blocks_by_id(ledger)
    if block_id not in blocks:
        raise CaseError(f"Unknown block: {block_id}")
    if new_status not in BLOCK_STATUSES:
        raise CaseError(f"Invalid block status: {new_status}")
    block = blocks[block_id]
    old_status = block["status"]
    recovery = active_bounded_recovery(manifest)
    if recovery is not None:
        _, recovery_plan = load_bounded_recovery(
            root, manifest, ledger, require_active=True
        )
        if block_id not in recovery_plan["block_scopes"]:
            raise CaseError(f"{block_id}: outside bounded recovery scope")
        if old_status == "stale":
            raise CaseError(
                f"{block_id}: use rebase-recovery-block for frozen stale content"
            )
        if new_status in {"ready", "in_progress"}:
            raise CaseError(
                f"{block_id}: content authoring is forbidden during bounded recovery"
            )
    if new_status not in ALLOWED_TRANSITIONS[old_status]:
        raise CaseError(f"Invalid transition {old_status} -> {new_status} for {block_id}")
    if (
        new_status == "in_progress"
        and block.get("remediation_contract")
        in {REMEDIATION_CONTRACT_V1, REMEDIATION_CONTRACT_V2}
        and (
            old_status in {"reviewed", "integrated"}
            or (
                old_status == "analyzed"
                and artifact_ready(case_file(root, block["review"]))
            )
        )
    ):
        raise CaseError(
            f"{block_id}: use begin-remediation so prior review coverage and the "
            "accepted finding are preserved"
        )

    if new_status == "in_progress" and block.get("risk_surfaces"):
        risk_preflight = block.get("risk_preflight")
        if not isinstance(risk_preflight, dict) or risk_preflight.get("status") != "pass":
            raise CaseError(f"{block_id}: record a complete risk preflight before authoring")
        if risk_preflight.get("kernel_sha256") != manifest["kernel"]["sha256"]:
            raise CaseError(f"{block_id}: risk preflight is stale against kernel")
        risk_evidence = case_file(root, str(risk_preflight.get("evidence", "")))
        if (
            not risk_evidence.is_file()
            or sha256(risk_evidence) != risk_preflight.get("evidence_sha256")
        ):
            raise CaseError(f"{block_id}: risk preflight evidence is missing or changed")

    if new_status in {"in_progress", "reviewed", "integrated"}:
        rollback_source = (
            {block_id}
            if new_status == "in_progress" and old_status in {"reviewed", "integrated"}
            else set()
        )
        projection_errors = working_projection_errors(
            root,
            manifest,
            ledger,
            require_any_update=False,
            exclude_sources=rollback_source,
        )
        if projection_errors:
            raise CaseError(
                "Working projection is behind reviewed content: "
                + "; ".join(projection_errors)
            )

    if new_status == "ready":
        incomplete = [
            dependency
            for dependency in block["depends_on"]
            if blocks[dependency]["status"] not in {"reviewed", "integrated"}
        ]
        if incomplete:
            raise CaseError(f"{block_id}: dependencies are not reviewed: {', '.join(incomplete)}")
    if new_status == "analyzed":
        artifact = case_file(root, block["artifact"])
        if not artifact_ready(artifact):
            raise CaseError(f"{block_id}: analysis artifact is missing or still a placeholder")
        index_path = case_file(root, block["semantic_index"])
        ids, _ = validate_index(index_path, block_id)
        if not ids:
            raise CaseError(f"{block_id}: semantic index has no definitions")
        index_payload = read_json(index_path)
        index_payload["kernel_revision"] = manifest["kernel"]["revision"]
        atomic_json(index_path, index_payload)
        block["kernel_revision"] = manifest["kernel"]["revision"]
        block["kernel_sha256"] = manifest["kernel"]["sha256"]
        block["artifact_sha256"] = sha256(artifact)
        block["index_sha256"] = sha256(index_path)
        block["review_sha256"] = None
    if new_status == "reviewed":
        review_path = case_file(root, block["review"])
        if not artifact_ready(review_path):
            raise CaseError(f"{block_id}: review artifact is missing or still a placeholder")
        if block["kernel_sha256"] != manifest["kernel"]["sha256"]:
            raise CaseError(f"{block_id}: analysis is stale against the kernel")
        if sha256(case_file(root, block["artifact"])) != block["artifact_sha256"]:
            raise CaseError(f"{block_id}: analysis changed after analyzed state")
        if sha256(case_file(root, block["semantic_index"])) != block["index_sha256"]:
            raise CaseError(f"{block_id}: semantic index changed after analyzed state")
        remediation_errors = remediation_review_errors(root, block, review_path)
        remediation_errors.extend(risk_review_errors(root, manifest, block, review_path))
        if recovery is not None:
            remediation_errors.extend(
                recovery_block_review_errors(
                    root,
                    manifest,
                    ledger,
                    block,
                    review_path,
                )
            )
        open_risk_findings = risk_review_open_findings(block, review_path)
        if open_risk_findings:
            remediation_errors.append(
                "risk review has open findings requiring begin-remediation: "
                + ", ".join(open_risk_findings)
            )
        if remediation_errors:
            raise CaseError(
                f"{block_id}: remediation review is invalid: "
                + "; ".join(remediation_errors)
            )
        remediation = active_block_remediation(block)
        remediation_id = remediation.get("id") if remediation is not None else None
        review_revision = record_block_review_revision(
            root,
            manifest,
            block,
            outcome="pass",
            remediation_id=remediation_id,
        )
        block["review_sha256"] = sha256(review_path)
        if remediation is not None:
            remediation["status"] = "verified"
            remediation["completed_at"] = now_utc()
            remediation["review_revision"] = review_revision["revision"]
            block["active_remediation"] = None
            manifest["events"].append(
                event(
                    "block_remediation_verified",
                    block_id=block_id,
                    remediation_id=remediation_id,
                    review_revision=review_revision["revision"],
                )
            )
    if new_status == "integrated":
        if not artifact_ready(case_file(root, manifest["artifacts"]["draft"])):
            raise CaseError("Integrated draft is missing or still a placeholder")
        if block["kernel_sha256"] != manifest["kernel"]["sha256"]:
            raise CaseError(f"{block_id}: reviewed block is stale against the kernel")
    if new_status == "blocked" and not note:
        raise CaseError("A blocked transition requires --note")

    block["status"] = new_status
    block["note"] = note
    block["updated_at"] = now_utc()
    manifest["events"].append(
        event(
            "block_transition",
            block_id=block_id,
            previous=old_status,
            status=new_status,
            note=note,
        )
    )
    save_case(root, manifest, ledger)


def block_subject_hash(root: Path, ledger: dict[str, Any]) -> str:
    """Hash all block artifacts/indexes in stable order."""
    digest = hashlib.sha256()
    for block in sorted(ledger["blocks"], key=lambda item: item["id"]):
        for key in ("artifact", "semantic_index"):
            path = case_file(root, block[key])
            digest.update(block["id"].encode("utf-8"))
            digest.update(key.encode("utf-8"))
            digest.update(path.read_bytes() if path.is_file() else b"<missing>")
    return digest.hexdigest()


def gate_subject_hash(
    root: Path,
    manifest: dict[str, Any],
    ledger: dict[str, Any],
    name: str,
) -> str:
    """Hash the mutable subject that one gate attests to."""
    digest = hashlib.sha256()
    digest.update(name.encode("utf-8"))
    if name == "evidence":
        digest.update(case_file(root, manifest["artifacts"]["evidence"]).read_bytes())
    elif name == "architecture_design":
        digest.update(manifest["kernel"]["sha256"].encode("ascii"))
        decisions = case_file(root, manifest["artifacts"]["decisions"])
        digest.update(decisions.read_bytes() if decisions.is_file() else b"<missing>")
    elif name == "author_passes":
        draft = case_file(root, manifest["artifacts"]["draft"])
        digest.update(draft.read_bytes() if draft.is_file() else b"<missing>")
        digest.update(manifest["kernel"]["sha256"].encode("ascii"))
        boundary, boundary_errors = solution_boundary_errors(
            root,
            manifest,
            required=solution_boundary_probe_present(root, manifest),
        )
        if boundary is not None or boundary_errors:
            decisions = case_file(root, manifest["artifacts"]["decisions"])
            digest.update(decisions.read_bytes() if decisions.is_file() else b"<missing>")
            role_context = manifest.get("artifacts", {}).get("planning_role_context")
            if isinstance(role_context, str):
                path = case_file(root, role_context)
                digest.update(path.read_bytes() if path.is_file() else b"<missing>")
    elif name == "semantic_integration":
        draft = case_file(root, manifest["artifacts"]["draft"])
        digest.update(draft.read_bytes() if draft.is_file() else b"<missing>")
        digest.update(block_subject_hash(root, ledger).encode("ascii"))
    elif name == "consistency":
        report = case_file(root, manifest["artifacts"]["consistency_report"])
        digest.update(report.read_bytes() if report.is_file() else b"<missing>")
    elif name == "project_conformance":
        draft = case_file(root, manifest["artifacts"]["draft"])
        digest.update(draft.read_bytes() if draft.is_file() else b"<missing>")
        digest.update(manifest["kernel"]["sha256"].encode("ascii"))
        contract, contract_errors = load_project_conformance_contract(root, manifest)
        if contract is not None and not contract_errors:
            binding = manifest["project_conformance_contract"]
            digest.update(case_file(root, binding["path"]).read_bytes())
            documents, resolution_errors = project_conformance_documents(
                root, manifest, contract
            )
            for error in resolution_errors:
                digest.update(error.encode("utf-8"))
            for label, path in sorted(documents, key=lambda item: item[0]):
                digest.update(label.encode("utf-8"))
                digest.update(path.read_bytes() if path.is_file() else b"<missing>")
    else:
        draft = case_file(root, manifest["artifacts"]["draft"])
        digest.update(draft.read_bytes() if draft.is_file() else b"<missing>")
        digest.update(manifest["kernel"]["sha256"].encode("ascii"))
        if name in {"integration_review", "global_review"} and manifest.get("mode") == "block":
            digest.update(block_subject_hash(root, ledger).encode("ascii"))
        if name in {"global_review", "architecture_conformance"}:
            boundary, boundary_errors = solution_boundary_errors(
                root,
                manifest,
                required=solution_boundary_probe_present(root, manifest),
            )
            if boundary is not None or boundary_errors:
                decisions = case_file(root, manifest["artifacts"]["decisions"])
                digest.update(
                    decisions.read_bytes() if decisions.is_file() else b"<missing>"
                )
                role_context = manifest.get("artifacts", {}).get(
                    "planning_role_context"
                )
                if isinstance(role_context, str):
                    path = case_file(root, role_context)
                    digest.update(path.read_bytes() if path.is_file() else b"<missing>")
    return digest.hexdigest()


def snapshot_review_evidence(root: Path, gate_name: str, source: Path) -> str:
    """Persist one immutable review revision and return its case-relative path."""
    history = root / "reviews" / "history"
    history.mkdir(parents=True, exist_ok=True)
    suffix = source.suffix or ".txt"
    revision = 1
    while True:
        target = history / f"{gate_name}-r{revision:03d}{suffix}"
        if not target.exists():
            break
        revision += 1
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_bytes(source.read_bytes())
    temporary.replace(target)
    return target.relative_to(root).as_posix()


def recovery_final_subject_hash(
    manifest: dict[str, Any],
    ledger: dict[str, Any],
    binding: dict[str, Any],
) -> str:
    """Hash the exact frozen whole-case subject for the combined recovery review."""
    digest = hashlib.sha256()
    for value in (
        "bounded-recovery-final-v1",
        str(manifest.get("case_id")),
        str(binding.get("sha256")),
        str(manifest.get("kernel", {}).get("sha256")),
        str(binding.get("draft_sha256")),
    ):
        digest.update(value.encode("utf-8"))
        digest.update(b"\0")
    for block in sorted(ledger.get("blocks", []), key=lambda item: str(item.get("id"))):
        for field in ("id", "artifact_sha256", "index_sha256"):
            digest.update(str(block.get(field)).encode("utf-8"))
            digest.update(b"\0")
    return digest.hexdigest()


def recovery_final_report_errors(
    root: Path,
    manifest: dict[str, Any],
    ledger: dict[str, Any],
    report_path: Path,
) -> list[str]:
    """Validate one combined final report against the pinned recovery subject."""
    binding, plan = load_bounded_recovery(root, manifest, ledger, require_active=True)
    text = report_path.read_text(encoding="utf-8")
    subject = recovery_final_subject_hash(manifest, ledger, binding)
    errors: list[str] = []
    expected_scalars = {
        "review_scope": "bounded-recovery-final",
        "recovery_plan_sha256": binding["sha256"],
        "recovery_subject_sha256": subject,
        "new_findings_policy": "user-decision",
        "decision": "pass",
    }
    for field, expected in expected_scalars.items():
        if report_scalar(text, field) != expected:
            errors.append(f"recovery final report requires {field}: {expected}")
    if parse_report_list(text, "covered_gates") != list(RECOVERY_COMBINED_GATES):
        errors.append(
            "recovery final report covered_gates must be: "
            + ", ".join(RECOVERY_COMBINED_GATES)
        )
    if parse_report_list(text, "deferred_findings") != []:
        errors.append("recovery final pass requires deferred_findings: []")
    errors.extend(
        completed_agent_run_errors(
            root,
            manifest,
            run_id=report_scalar(text, "agent_run_id"),
            role="spec-reviewer",
            role_mode="final",
            subject_sha256=subject,
        )
    )
    if not plan.get("combine_final_review"):
        errors.append("recovery plan does not permit a combined final review")
    return errors


def rebase_nonsemantic_change(
    root: Path,
    manifest: dict[str, Any],
    ledger: dict[str, Any],
    *,
    change_scope: str,
    reason: str,
) -> list[str]:
    """Carry passed review evidence over an explicitly non-semantic delta."""
    if active_bounded_recovery(manifest) is not None:
        raise CaseError("Content rebasing is forbidden during bounded recovery")
    if change_scope not in {"editorial", "projection-only"}:
        raise CaseError("record-change supports only editorial or projection-only deltas")
    if not reason.strip():
        raise CaseError("record-change requires a reason")
    if manifest.get("gates", {}).get("consistency", {}).get("status") != "pass":
        raise CaseError("Run a successful consistency check before record-change")
    draft_path = case_file(root, manifest["artifacts"]["draft"])
    report_path = case_file(root, manifest["artifacts"]["consistency_report"])
    if not report_path.is_file() or report_path.stat().st_mtime_ns < draft_path.stat().st_mtime_ns:
        raise CaseError("Consistency report is older than the current draft")
    report = read_json(report_path)
    if (
        not isinstance(report, dict)
        or report.get("errors") != []
        or report.get("kernel_sha256") != manifest.get("kernel", {}).get("sha256")
        or report.get("draft_sha256") != sha256(draft_path)
    ):
        raise CaseError("Consistency report does not match the current kernel and draft")
    current_snapshot = report.get("semantic_snapshot")
    if not isinstance(current_snapshot, dict):
        raise CaseError("Consistency report has no semantic snapshot")
    projection_errors = working_projection_errors(
        root,
        manifest,
        ledger,
        require_any_update=True,
    )
    if projection_errors:
        raise CaseError("Working projection is not current: " + "; ".join(projection_errors))
    document_errors = project_conformance_errors(root, manifest)
    if document_errors:
        raise CaseError("Project document conformance failed: " + "; ".join(document_errors))
    rebased: list[str] = []
    for gate_name, gate in manifest.get("gates", {}).items():
        if gate.get("status") != "pass" or not gate.get("subject_sha256"):
            continue
        previous = gate["subject_sha256"]
        current = gate_subject_hash(root, manifest, ledger, gate_name)
        if previous == current:
            continue
        baseline = gate.get("semantic_snapshot")
        if not isinstance(baseline, dict) or set(baseline) != set(current_snapshot):
            raise CaseError(f"{gate_name} has no comparable semantic snapshot")
        changed_paths: list[str] = []
        for relative in sorted(current_snapshot):
            before = baseline.get(relative)
            after = current_snapshot.get(relative)
            if not isinstance(before, dict) or not isinstance(after, dict):
                changed_paths.append(relative)
                continue
            comparison = (
                "sha256" if change_scope == "projection-only" else "editorial_sha256"
            )
            if relative.startswith("blocks/"):
                comparison = "sha256"
            if before.get(comparison) != after.get(comparison):
                changed_paths.append(relative)
        if changed_paths:
            raise CaseError(
                f"{change_scope} delta changed semantic content since {gate_name}: "
                + ", ".join(changed_paths)
            )
        gate["subject_sha256"] = current
        gate["semantic_snapshot"] = current_snapshot
        rebased.append(gate_name)
        manifest["events"].append(
            event(
                "gate_rebased",
                gate=gate_name,
                change_scope=change_scope,
                previous_subject_sha256=previous,
                subject_sha256=current,
                reason=reason.strip(),
            )
        )
    manifest["events"].append(
        event(
            "nonsemantic_change_recorded",
            change_scope=change_scope,
            reason=reason.strip(),
            rebased_gates=rebased,
        )
    )
    save_case(root, manifest, ledger)
    return rebased


def prior_passed_gate_state(
    manifest: dict[str, Any],
    gate_name: str,
) -> dict[str, Any] | None:
    """Return the current or most recently archived passed state for one gate."""
    current = manifest.get("gates", {}).get(gate_name)
    if isinstance(current, dict) and current.get("status") == "pass":
        return current
    history = manifest.get("gate_history", {}).get(gate_name, [])
    if not isinstance(history, list):
        raise CaseError(f"manifest gate_history.{gate_name} must be an array")
    for item in reversed(history):
        if isinstance(item, dict) and item.get("status") == "pass":
            return item
    return None


def record_semantic_remediation(
    root: Path,
    manifest: dict[str, Any],
    ledger: dict[str, Any],
    *,
    block_id: str,
    remediation_id: str | None,
    reason: str,
) -> list[str]:
    """Reuse prior whole-case coverage after a machine-bounded targeted correction."""
    if active_bounded_recovery(manifest) is not None:
        raise CaseError("Semantic remediation recording is forbidden during bounded recovery")
    if not reason.strip():
        raise CaseError("record-remediation requires a reason")
    blocks = blocks_by_id(ledger)
    if block_id not in blocks:
        raise CaseError(f"Unknown block: {block_id}")
    block = blocks[block_id]
    remediations = block.get("remediations", [])
    if not isinstance(remediations, list):
        raise CaseError(f"{block_id}: remediations must be an array")
    selected = None
    for item in reversed(remediations):
        if not isinstance(item, dict):
            continue
        if remediation_id is None or item.get("id") == remediation_id:
            selected = item
            break
    if selected is None:
        raise CaseError(f"{block_id}: remediation does not exist")
    if selected.get("scope") != "targeted":
        raise CaseError("Full-block remediation requires fresh full-block and whole-case review")
    if selected.get("status") != "verified":
        raise CaseError("Targeted remediation must pass its bounded review first")
    if selected.get("coverage_rebased_at") is not None:
        return list(selected.get("rebased_gates", []))
    if block.get("active_remediation") is not None:
        raise CaseError("Cannot reuse coverage while another remediation is active")
    if block.get("status") not in {"reviewed", "integrated"}:
        raise CaseError(f"{block_id}: targeted remediation is not in a reviewed state")

    consistency = manifest.get("gates", {}).get("consistency", {})
    if consistency.get("status") != "pass":
        raise CaseError("Run a successful consistency check before record-remediation")
    draft_path = case_file(root, manifest["artifacts"]["draft"])
    report_path = case_file(root, manifest["artifacts"]["consistency_report"])
    if not report_path.is_file() or report_path.stat().st_mtime_ns < draft_path.stat().st_mtime_ns:
        raise CaseError("Consistency report is older than the current draft")
    report = read_json(report_path)
    if (
        not isinstance(report, dict)
        or report.get("errors") != []
        or report.get("kernel_sha256") != manifest.get("kernel", {}).get("sha256")
        or report.get("draft_sha256") != sha256(draft_path)
    ):
        raise CaseError("Consistency report does not match the current kernel and draft")
    current_snapshot = report.get("semantic_snapshot")
    if not isinstance(current_snapshot, dict):
        raise CaseError("Consistency report has no semantic snapshot")
    delta_errors = remediation_review_errors(
        root,
        {**block, "active_remediation": selected["id"]},
        case_file(root, block["review"]),
    )
    if delta_errors:
        raise CaseError("Targeted remediation is no longer bounded: " + "; ".join(delta_errors))
    projection_errors = working_projection_errors(
        root,
        manifest,
        ledger,
        require_any_update=True,
    )
    if projection_errors:
        raise CaseError("Working projection is not current: " + "; ".join(projection_errors))
    document_errors = project_conformance_errors(root, manifest)
    if document_errors:
        raise CaseError("Project document conformance failed: " + "; ".join(document_errors))

    for prerequisite in ("semantic_integration", "author_passes"):
        gate = manifest.get("gates", {}).get(prerequisite, {})
        if gate.get("status") == "not_required":
            continue
        if gate.get("status") != "pass" or gate.get("subject_sha256") != gate_subject_hash(
            root,
            manifest,
            ledger,
            prerequisite,
        ):
            raise CaseError(
                f"Gate {prerequisite} must be freshly passed for the corrected subject"
            )

    allowed_changed_paths = {
        str(manifest["kernel"]["path"]),
        str(manifest["artifacts"]["draft"]),
        str(block["artifact"]),
        str(block["semantic_index"]),
    }
    eligible_gates = (
        "architecture_design",
        "integration_review",
        "global_review",
        "project_conformance",
        "architecture_conformance",
    )
    rebased: list[str] = []
    review_revision = next(
        (
            item
            for item in reversed(block.get("review_history", []))
            if isinstance(item, dict)
            and item.get("remediation_id") == selected.get("id")
        ),
        None,
    )
    if not isinstance(review_revision, dict):
        raise CaseError("Targeted remediation has no immutable verification review")
    receipts_dir = root / "reviews" / "history"
    receipts_dir.mkdir(parents=True, exist_ok=True)
    for gate_name in eligible_gates:
        prior = prior_passed_gate_state(manifest, gate_name)
        if prior is None:
            continue
        current_subject = gate_subject_hash(root, manifest, ledger, gate_name)
        current_gate = manifest["gates"][gate_name]
        if (
            current_gate.get("status") == "pass"
            and current_gate.get("subject_sha256") == current_subject
        ):
            continue
        baseline = prior.get("semantic_snapshot")
        if not isinstance(baseline, dict) or set(baseline) != set(current_snapshot):
            raise CaseError(f"{gate_name} has no comparable prior semantic snapshot")
        changed_paths = sorted(
            relative
            for relative in current_snapshot
            if baseline.get(relative, {}).get("sha256")
            != current_snapshot.get(relative, {}).get("sha256")
        )
        outside = sorted(set(changed_paths) - allowed_changed_paths)
        if outside:
            raise CaseError(
                f"{gate_name} prior coverage cannot be reused; unrelated paths changed: "
                + ", ".join(outside)
            )
        prior_evidence = prior.get("evidence")
        if not isinstance(prior_evidence, str):
            raise CaseError(f"{gate_name} prior coverage has no evidence")
        prior_evidence_path = case_file(root, prior_evidence)
        if (
            not artifact_ready(prior_evidence_path)
            or sha256(prior_evidence_path) != prior.get("evidence_sha256")
        ):
            raise CaseError(f"{gate_name} prior evidence is missing or changed")
        receipt_relative = (
            f"reviews/history/{gate_name}-{block_id}-{selected['id']}-reuse.json"
        )
        receipt_path = case_file(root, receipt_relative)
        receipt = {
            "schema": 1,
            "case_id": manifest["case_id"],
            "gate": gate_name,
            "block_id": block_id,
            "remediation_id": selected["id"],
            "recorded_at": now_utc(),
            "reason": reason.strip(),
            "previous_evidence": prior_evidence,
            "previous_evidence_sha256": prior["evidence_sha256"],
            "previous_subject_sha256": prior["subject_sha256"],
            "verification_review": review_revision["evidence"],
            "verification_review_sha256": review_revision["evidence_sha256"],
            "finding_evidence": selected["finding_evidence"],
            "finding_evidence_sha256": selected["finding_evidence_sha256"],
            "consistency_report": manifest["artifacts"]["consistency_report"],
            "consistency_report_sha256": sha256(report_path),
            "changed_paths": changed_paths,
            "semantic_ids": selected["semantic_ids"],
            "subject_sha256": current_subject,
        }
        if receipt_path.exists():
            existing = read_json(receipt_path)
            comparable = dict(receipt)
            comparable["recorded_at"] = existing.get("recorded_at") if isinstance(existing, dict) else None
            if existing != comparable:
                raise CaseError(f"Remediation receipt already exists: {receipt_relative}")
        else:
            atomic_json(receipt_path, receipt)
        manifest["gates"][gate_name] = {
            "status": "pass",
            "evidence": receipt_relative,
            "evidence_sha256": sha256(receipt_path),
            "subject_sha256": current_subject,
            "semantic_snapshot": current_snapshot,
            "note": f"prior coverage reused after {block_id} {selected['id']}",
        }
        manifest["events"].append(
            event(
                "gate_rebased_after_targeted_remediation",
                gate=gate_name,
                block_id=block_id,
                remediation_id=selected["id"],
                previous_subject_sha256=prior["subject_sha256"],
                subject_sha256=current_subject,
                receipt=receipt_relative,
            )
        )
        rebased.append(gate_name)
    selected["coverage_rebased_at"] = now_utc()
    selected["rebased_gates"] = rebased
    selected["coverage_rebase_reason"] = reason.strip()
    manifest["events"].append(
        event(
            "targeted_remediation_recorded",
            block_id=block_id,
            remediation_id=selected["id"],
            rebased_gates=rebased,
            reason=reason.strip(),
        )
    )
    save_case(root, manifest, ledger)
    return rebased


def set_gate(
    root: Path,
    manifest: dict[str, Any],
    ledger: dict[str, Any],
    *,
    name: str,
    status: str,
    evidence: str | None,
    note: str | None,
) -> None:
    """Record a verified workflow gate."""
    if name not in GATE_NAMES:
        raise CaseError(f"Unknown gate: {name}")
    recovery_plan: dict[str, Any] | None = None
    if active_bounded_recovery(manifest) is not None:
        _, recovery_plan = load_bounded_recovery(
            root, manifest, ledger, require_active=True
        )
        if name not in recovery_plan["allowed_gates"]:
            raise CaseError(f"Gate {name} is outside bounded recovery scope")
    if status not in GATE_STATUSES:
        raise CaseError(f"Invalid gate status: {status}")
    if name == "consistency" and status == "pass":
        raise CaseError("Use the check command to pass the consistency gate")
    if status == "blocked" and not note:
        raise CaseError("A blocked gate requires --note")
    if status == "not_required" and not note:
        raise CaseError("A not_required gate requires --note")
    if status == "not_required":
        boundary_required = solution_boundary_probe_present(root, manifest)
        boundary, _ = solution_boundary_errors(root, manifest, required=False)
        if name in {"author_passes", "global_review"} and (
            boundary_required or boundary is not None
        ):
            raise CaseError(
                f"{name} must pass when a solution boundary is required or present"
            )
        if (
            name in {"architecture_design", "architecture_conformance"}
            and boundary is not None
            and boundary.get("solution_horizon")
            in {"tactical", "generalized-capability"}
        ):
            raise CaseError(
                f"{name} must pass for {boundary.get('solution_horizon')} horizon"
            )
        if name in required_gates(manifest):
            raise CaseError(f"Gate {name} is required by the execution policy")
    if status == "pass" and not evidence:
        raise CaseError("A passed gate requires --evidence")
    if status == "pass" and name == "author_passes":
        projection_errors = working_projection_errors(
            root,
            manifest,
            ledger,
            require_any_update=True,
        )
        if projection_errors:
            raise CaseError(
                "Working projection must be visible before author passes: "
                + "; ".join(projection_errors)
            )
        boundary_required = solution_boundary_probe_present(root, manifest)
        boundary, boundary_errors = solution_boundary_errors(
            root,
            manifest,
            required=boundary_required,
        )
        if boundary_errors:
            raise CaseError(
                "Author passes require a valid solution boundary: "
                + "; ".join(boundary_errors)
            )
        if boundary is not None and boundary.get("solution_horizon") in {
            "tactical",
            "generalized-capability",
        }:
            architecture_gate = manifest.get("gates", {}).get(
                "architecture_design", {}
            )
            if architecture_gate.get("status") != "pass":
                raise CaseError(
                    f"{boundary.get('solution_horizon')} horizon requires a passed "
                    "architecture_design gate before author passes"
                )
            if architecture_gate.get("subject_sha256") != gate_subject_hash(
                root, manifest, ledger, "architecture_design"
            ):
                raise CaseError(
                    "architecture_design decision is stale for the current "
                    "solution boundary"
                )
    if status == "pass" and name == "project_conformance":
        projection_errors = working_projection_errors(
            root,
            manifest,
            ledger,
            require_any_update=True,
        )
        if projection_errors:
            raise CaseError(
                "Project conformance requires a current visible read-back: "
                + "; ".join(projection_errors)
            )
        document_errors = project_conformance_errors(root, manifest)
        if document_errors:
            raise CaseError(
                "Project document conformance failed: " + "; ".join(document_errors)
            )
    evidence_hash = None
    subject_hash = None
    if status == "pass" and evidence:
        path = case_file(root, evidence)
        if not artifact_ready(path):
            raise CaseError(f"Gate evidence is missing or still a placeholder: {evidence}")
        if (
            recovery_plan is not None
            and recovery_plan.get("combine_final_review")
            and name in RECOVERY_COMBINED_GATES
        ):
            recovery_errors = recovery_final_report_errors(
                root,
                manifest,
                ledger,
                path,
            )
            if recovery_errors:
                raise CaseError(
                    "Bounded recovery final report is invalid: "
                    + "; ".join(recovery_errors)
                )
        if assurance_level(manifest) == "standard" and name in {
            "global_review",
            "project_conformance",
        }:
            report_text = path.read_text(encoding="utf-8")
            match = re.search(r"covered_gates\s*:\s*\[([^\]]+)\]", report_text)
            covered = {
                item.strip().strip("'\"")
                for item in match.group(1).split(",")
            } if match else set()
            expected_covered = {
                "integration_review",
                "global_review",
                "project_conformance",
            }
            if covered != expected_covered:
                raise CaseError(
                    "Standard final report must declare exact covered_gates: "
                    + ", ".join(sorted(expected_covered))
                )
        if name == "project_conformance":
            freshness_errors = project_conformance_review_freshness_errors(
                root,
                manifest,
                path,
            )
            if freshness_errors:
                raise CaseError(
                    "Project-conformance review is stale: "
                    + "; ".join(freshness_errors)
                )
        current_gate = manifest.get("gates", {}).get(name, {})
        current_subject = gate_subject_hash(root, manifest, ledger, name)
        if (
            current_gate.get("status") == "pass"
            and current_gate.get("evidence_sha256") == sha256(path)
            and current_gate.get("subject_sha256") == current_subject
        ):
            return
        if name in REVISIONED_REVIEW_GATES:
            evidence = snapshot_review_evidence(root, name, path)
            path = case_file(root, evidence)
        evidence_hash = sha256(path)
        subject_hash = current_subject

    manifest["gates"][name] = {
        "status": status,
        "evidence": evidence,
        "evidence_sha256": evidence_hash,
        "subject_sha256": subject_hash,
        "semantic_snapshot": (
            semantic_state_snapshot(root, manifest, ledger) if status == "pass" else None
        ),
        "note": note,
    }
    manifest["events"].append(
        event("gate_updated", gate=name, status=status, evidence=evidence, note=note)
    )
    save_case(root, manifest, ledger)


def validate_case(
    root: Path,
    manifest: dict[str, Any],
    ledger: dict[str, Any],
    *,
    final: bool,
    ignore_consistency_gate: bool = False,
    accepted_role_manifests: list[dict[str, Any]] | None = None,
) -> list[str]:
    """Return structural, freshness, traceability, and optional final errors."""
    errors: list[str] = []
    errors.extend(bounded_recovery_errors(root, manifest, ledger, final=final))
    boundary_required = solution_boundary_probe_present(root, manifest)
    boundary, boundary_errors = solution_boundary_errors(
        root,
        manifest,
        required=boundary_required and (
            final
            or manifest.get("gates", {}).get("author_passes", {}).get("status") == "pass"
        ),
    )
    errors.extend(f"Solution boundary: {item}" for item in boundary_errors)
    boundary_active = boundary_required or boundary is not None
    if final and boundary_active:
        for gate_name in ("author_passes", "global_review"):
            if manifest.get("gates", {}).get(gate_name, {}).get("status") != "pass":
                errors.append(f"Gate {gate_name} must pass for a solution boundary")
        if boundary is not None and boundary.get("solution_horizon") in {
            "tactical",
            "generalized-capability",
        }:
            for gate_name in ("architecture_design", "architecture_conformance"):
                if manifest.get("gates", {}).get(gate_name, {}).get("status") != "pass":
                    errors.append(
                        f"Gate {gate_name} must pass for "
                        f"{boundary.get('solution_horizon')} horizon"
                    )
    errors.extend(
        working_projection_errors(
            root,
            manifest,
            ledger,
            require_any_update=final,
        )
    )
    if final or manifest.get("gates", {}).get("project_conformance", {}).get(
        "status"
    ) == "pass":
        errors.extend(
            f"Project document conformance: {item}"
            for item in project_conformance_errors(root, manifest)
        )
    decision_binding = manifest.get("mode_decision")
    if decision_binding is not None:
        if not isinstance(decision_binding, dict):
            errors.append("manifest mode_decision binding must be an object or null")
        else:
            decision_relative = decision_binding.get("path")
            if decision_relative != MODE_DECISION_FILENAME:
                errors.append("manifest mode_decision path is invalid")
            else:
                try:
                    decision_payload = read_json(case_file(root, decision_relative))
                    validate_mode_decision(
                        decision_payload,
                        expected_mode=manifest.get("mode"),
                        expected_profile_id=manifest.get("profile_id"),
                    )
                    if decision_binding.get("fingerprint") != decision_payload["fingerprint"]:
                        errors.append("manifest mode_decision fingerprint mismatch")
                    if "selected_assurance" in decision_payload:
                        selected_assurance = decision_payload["selected_assurance"]
                        actual_assurance = assurance_level(manifest)
                        escalation_allowed = (
                            selected_assurance == "lite"
                            and actual_assurance in {"standard", "high"}
                        ) or (
                            selected_assurance == "standard"
                            and actual_assurance == "high"
                        )
                        if actual_assurance != selected_assurance and not escalation_allowed:
                            errors.append("manifest assurance conflicts with mode decision")
                        if tracking_policy(manifest) != decision_payload["selected_tracking"]:
                            errors.append("manifest tracking conflicts with mode decision")
                        if (
                            projection_sync_policy(manifest)
                            != decision_payload["selected_projection_sync"]
                        ):
                            errors.append("manifest projection sync conflicts with mode decision")
                except (CaseError, ModeDecisionError) as exc:
                    errors.append(f"Invalid mode decision: {exc}")
    method_binding = manifest.get("method_context")
    if method_binding is not None:
        if not isinstance(method_binding, dict):
            errors.append("manifest method_context binding must be an object or null")
        elif (
            method_binding.get("metadata_path") != METHOD_CONTEXT_JSON
            or method_binding.get("content_path") != METHOD_CONTEXT_MARKDOWN
        ):
            errors.append("manifest method_context paths are invalid")
        else:
            try:
                method_payload = read_json(case_file(root, METHOD_CONTEXT_JSON))
                method_markdown = case_file(root, METHOD_CONTEXT_MARKDOWN).read_text(
                    encoding="utf-8"
                )
                validate_method_context(
                    method_payload,
                    method_markdown,
                    expected_route_id=manifest.get("route_id"),
                    verify_sources=False,
                )
                if method_binding.get("fingerprint") != method_payload["fingerprint"]:
                    errors.append("manifest method_context fingerprint mismatch")
                if method_binding.get("content_sha256") != method_payload["content_sha256"]:
                    errors.append("manifest method_context content hash mismatch")
            except (OSError, CaseError, RouterError) as exc:
                errors.append(f"Invalid method context: {exc}")
    planning_payload: dict[str, Any] | None = None
    planning_binding = manifest.get("planning_handoff")
    if planning_binding is not None:
        if not isinstance(planning_binding, dict):
            errors.append("manifest planning_handoff binding must be an object or null")
        elif (
            planning_binding.get("metadata_path") != PLANNING_HANDOFF_JSON
            or planning_binding.get("content_path") != PLANNING_HANDOFF_MARKDOWN
        ):
            errors.append("manifest planning_handoff paths are invalid")
        else:
            try:
                planning_payload = read_json(case_file(root, PLANNING_HANDOFF_JSON))
                planning_markdown = case_file(root, PLANNING_HANDOFF_MARKDOWN).read_text(
                    encoding="utf-8"
                )
                validate_planning_handoff(
                    planning_payload,
                    planning_markdown,
                    expected_profile_id=manifest.get("profile_id"),
                    expected_project_root=manifest.get("project_root"),
                    enforce_project_root=True,
                )
                if planning_binding.get("fingerprint") != planning_payload["fingerprint"]:
                    errors.append("manifest planning_handoff fingerprint mismatch")
                if planning_binding.get("content_sha256") != planning_payload["content_sha256"]:
                    errors.append("manifest planning_handoff content hash mismatch")
                if manifest.get("execution_preferences") != planning_payload.get(
                    "execution_preferences"
                ):
                    errors.append("manifest execution preferences differ from planning handoff")
                role_context_path = planning_binding.get("role_context_path")
                if role_context_path != PLANNING_ROLE_CONTEXT_JSON:
                    errors.append("manifest planning role-context path is invalid")
                else:
                    stored_role_context = read_json(
                        case_file(root, PLANNING_ROLE_CONTEXT_JSON)
                    )
                    expected_role_context = planning_role_context(planning_payload)
                    accepted_role_contexts = [expected_role_context]
                    if "working_projection" not in planning_payload:
                        legacy_role_context = {
                            key: value
                            for key, value in expected_role_context.items()
                            if key not in {"working_projection", "fingerprint"}
                        }
                        legacy_role_context["fingerprint"] = role_context_fingerprint(
                            legacy_role_context
                        )
                        accepted_role_contexts.append(legacy_role_context)
                    if stored_role_context not in accepted_role_contexts:
                        errors.append("planning role-context differs from approved handoff")
                    stored_role_fingerprint = (
                        stored_role_context.get("fingerprint")
                        if isinstance(stored_role_context, dict)
                        else None
                    )
                    if (
                        not isinstance(stored_role_context, dict)
                        or stored_role_fingerprint
                        != role_context_fingerprint(stored_role_context)
                        or planning_binding.get("role_context_fingerprint")
                        != stored_role_fingerprint
                    ):
                        errors.append("manifest planning role-context fingerprint mismatch")
            except (OSError, CaseError, PlanningError) as exc:
                errors.append(f"Invalid planning handoff: {exc}")
    timing_relative = manifest.get("artifacts", {}).get("automation_timing")
    if timing_relative is not None:
        if not isinstance(timing_relative, str) or timing_relative != AUTOMATION_TIMING_FILENAME:
            errors.append("manifest automation_timing path is invalid")
        else:
            try:
                timing_payload = read_json(case_file(root, timing_relative))
                timing_errors = validate_automation_timing(
                    timing_payload,
                    final=final,
                    expected_case_id=manifest.get("case_id"),
                    expected_plan=runtime_automation_plan(
                        (planning_payload or {}).get("automation_plan"),
                        tracking_policy(manifest),
                    ),
                    expected_planning_case_id=(planning_payload or {}).get("planning_case_id"),
                    expected_planning_revision=(planning_payload or {}).get("planning_revision"),
                )
                errors.extend(timing_errors)
            except (CaseError, AutomationTimingError) as exc:
                errors.append(f"Invalid automation timing: {exc}")
    agent_ledger_relative = manifest.get("artifacts", {}).get("agent_ledger")
    if agent_ledger_relative is not None:
        if not isinstance(agent_ledger_relative, str) or agent_ledger_relative != AGENT_LEDGER_JSON:
            errors.append("manifest agent_ledger path is invalid")
        else:
            try:
                agent_ledger = read_json(case_file(root, agent_ledger_relative))
                errors.extend(
                    validate_agent_ledger(
                        agent_ledger,
                        case_id=str(manifest.get("case_id")),
                    )
                )
                errors.extend(agent_artifact_errors(root, agent_ledger))
            except CaseError as exc:
                errors.append(f"Invalid agent ledger: {exc}")
    role_manifest_relative = manifest.get("artifacts", {}).get("role_manifest")
    if role_manifest_relative != ROLE_MANIFEST_JSON:
        errors.append("manifest role_manifest path is invalid")
    else:
        try:
            stored_role_manifest = read_json(case_file(root, ROLE_MANIFEST_JSON))
            expected_role_manifest = role_manifest(manifest)
            accepted_role_manifests = accepted_role_manifests or []
            if (
                stored_role_manifest != expected_role_manifest
                and stored_role_manifest not in accepted_role_manifests
            ):
                errors.append("role-manifest.json differs from coordinator manifest projection")
        except CaseError as exc:
            errors.append(f"Invalid role manifest: {exc}")
    errors.extend(gate_history_errors(root, manifest))
    try:
        ensure_acyclic(ledger)
    except CaseError as exc:
        errors.append(str(exc))
    errors.extend(risk_preflight_state_errors(root, manifest, ledger))

    try:
        _, kernel_hash = current_kernel(root, manifest)
        if kernel_hash != manifest["kernel"]["sha256"]:
            errors.append("kernel.md changed without refresh-kernel")
    except CaseError as exc:
        errors.append(str(exc))
        kernel_hash = None

    all_ids: dict[str, str] = {}
    all_traces: list[tuple[str, dict[str, Any]]] = []
    for block in ledger["blocks"]:
        block_id = block.get("id")
        if not BLOCK_ID_RE.fullmatch(block_id or ""):
            errors.append(f"Invalid block id: {block_id!r}")
            continue
        if block.get("kind") not in BLOCK_KINDS:
            errors.append(f"{block_id}: invalid kind {block.get('kind')!r}")
        errors.extend(block_review_state_errors(root, block))
        if block.get("status") not in BLOCK_STATUSES:
            errors.append(f"{block_id}: invalid status {block.get('status')!r}")
            continue
        if block["status"] in {"analyzed", "reviewed", "integrated"}:
            if not artifact_ready(case_file(root, block["artifact"])):
                errors.append(f"{block_id}: analysis artifact is incomplete")
            try:
                ids, traces = validate_index(case_file(root, block["semantic_index"]), block_id)
                if not ids:
                    errors.append(f"{block_id}: semantic index has no definitions")
                for semantic_id in ids:
                    if semantic_id in all_ids:
                        errors.append(
                            f"Duplicate semantic id {semantic_id}: {all_ids[semantic_id]} and {block_id}"
                        )
                    all_ids[semantic_id] = block_id
                all_traces.extend((block_id, row) for row in traces)
            except CaseError as exc:
                errors.extend(str(exc).splitlines())
            if kernel_hash and block.get("kernel_sha256") != kernel_hash:
                errors.append(f"{block_id}: stale kernel snapshot")
            artifact = case_file(root, block["artifact"])
            index = case_file(root, block["semantic_index"])
            if artifact.is_file() and sha256(artifact) != block.get("artifact_sha256"):
                errors.append(f"{block_id}: analysis changed after analyzed state")
            if index.is_file() and sha256(index) != block.get("index_sha256"):
                errors.append(f"{block_id}: semantic index changed after analyzed state")
        if block["status"] in {"reviewed", "integrated"} and not artifact_ready(
            case_file(root, block["review"])
        ):
            errors.append(f"{block_id}: review artifact is incomplete")
        elif block["status"] in {"reviewed", "integrated"} and sha256(
            case_file(root, block["review"])
        ) != block.get("review_sha256"):
            errors.append(f"{block_id}: review changed after reviewed state")

    inbound: dict[str, set[str]] = {semantic_id: set() for semantic_id in all_ids}
    outbound: dict[str, set[str]] = {semantic_id: set() for semantic_id in all_ids}
    for block_id, row in all_traces:
        source = row.get("from")
        targets = row.get("to") if isinstance(row.get("to"), list) else []
        if source not in all_ids:
            errors.append(f"{block_id}: trace source does not resolve: {source!r}")
            continue
        for target in targets:
            if target not in all_ids:
                errors.append(f"{block_id}: trace target does not resolve: {target!r}")
                continue
            outbound[source].add(target)
            inbound[target].add(source)

    if final and manifest.get("mode") == "block":
        non_integrated = [
            block["id"] for block in ledger["blocks"] if block.get("status") != "integrated"
        ]
        if non_integrated:
            errors.append(f"Blocks are not integrated: {', '.join(non_integrated)}")
        for semantic_id in sorted(all_ids):
            prefix = semantic_id.split("-", 1)[0]
            if prefix == "AC" and not any(target.startswith("REQ-") for target in outbound[semantic_id]):
                errors.append(f"{semantic_id}: acceptance criterion must trace to REQ")
            if prefix == "REQ":
                if not outbound[semantic_id]:
                    errors.append(f"{semantic_id}: requirement has no upstream trace")
                if not any(source.startswith("AC-") for source in inbound[semantic_id]):
                    errors.append(f"{semantic_id}: requirement has no acceptance criterion")

    if final:
        for gate_name in FINAL_GATES:
            if ignore_consistency_gate and gate_name == "consistency":
                continue
            status = manifest.get("gates", {}).get(gate_name, {}).get("status")
            if status not in {"pass", "not_required"}:
                errors.append(f"Gate {gate_name} is {status or 'missing'}")
                continue
            if (
                status == "not_required"
                and gate_name
                in required_gates(manifest)
            ):
                errors.append(f"Gate {gate_name} is required by the execution policy")
                continue
            if status == "pass":
                gate = manifest["gates"][gate_name]
                evidence_path = gate.get("evidence")
                if not evidence_path:
                    errors.append(f"Gate {gate_name} has no evidence")
                    continue
                path = case_file(root, evidence_path)
                if not artifact_ready(path):
                    errors.append(f"Gate {gate_name} evidence is incomplete")
                    continue
                if sha256(path) != gate.get("evidence_sha256"):
                    errors.append(f"Gate {gate_name} evidence changed after pass")
                if gate_subject_hash(root, manifest, ledger, gate_name) != gate.get(
                    "subject_sha256"
                ):
                    errors.append(f"Gate {gate_name} subject changed after pass")
    return errors


def semantic_state_snapshot(
    root: Path,
    manifest: dict[str, Any],
    ledger: dict[str, Any],
) -> dict[str, dict[str, str]]:
    """Capture exact and whitespace-normalized hashes of semantic artifacts."""
    relatives = {
        str(manifest["kernel"]["path"]),
        str(manifest["artifacts"]["evidence"]),
        str(manifest["artifacts"]["decisions"]),
        str(manifest["artifacts"]["draft"]),
    }
    for block in ledger.get("blocks", []):
        if not isinstance(block, dict):
            continue
        for field in ("artifact", "semantic_index"):
            if isinstance(block.get(field), str):
                relatives.add(block[field])
    snapshot: dict[str, dict[str, str]] = {}
    for relative in sorted(relatives):
        path = case_file(root, relative)
        if not path.is_file():
            continue
        text = unicodedata.normalize(
            "NFKC",
            path.read_text(encoding="utf-8", errors="replace"),
        )
        editorial = " ".join(text.split())
        snapshot[relative] = {
            "sha256": sha256(path),
            "editorial_sha256": hashlib.sha256(editorial.encode("utf-8")).hexdigest(),
        }
    return snapshot


def run_check(
    root: Path,
    manifest: dict[str, Any],
    ledger: dict[str, Any],
    *,
    final_trace: bool,
) -> list[str]:
    """Run deterministic checks and record their gate result."""
    errors = validate_case(
        root,
        manifest,
        ledger,
        final=False,
    )
    if final_trace and not errors:
        trace_errors = validate_case(
            root,
            manifest,
            ledger,
            final=True,
            ignore_consistency_gate=True,
        )
        errors.extend(
            item
            for item in trace_errors
            if not item.startswith("Gate ")
            and item != "bounded recovery must be completed before final validation"
        )
    report = {
        "schema": SCHEMA_VERSION,
        "case_id": manifest["case_id"],
        "checked_at": now_utc(),
        "final_trace": final_trace,
        "kernel_revision": manifest["kernel"]["revision"],
        "kernel_sha256": manifest["kernel"]["sha256"],
        "block_subject_sha256": block_subject_hash(root, ledger),
        "draft_sha256": sha256(case_file(root, manifest["artifacts"]["draft"])),
        "semantic_snapshot": semantic_state_snapshot(root, manifest, ledger),
        "errors": errors,
    }
    report_path = case_file(root, manifest["artifacts"]["consistency_report"])
    atomic_json(report_path, report)
    manifest["gates"]["consistency"] = {
        "status": "pass" if not errors else "blocked",
        "evidence": manifest["artifacts"]["consistency_report"] if not errors else None,
        "evidence_sha256": sha256(report_path) if not errors else None,
        "subject_sha256": (
            gate_subject_hash(root, manifest, ledger, "consistency") if not errors else None
        ),
        "semantic_snapshot": report["semantic_snapshot"] if not errors else None,
        "note": None if not errors else "; ".join(errors[:5]),
    }
    manifest["events"].append(
        event("consistency_check", final_trace=final_trace, passed=not errors)
    )
    save_case(root, manifest, ledger)
    return errors


def context_bundle(
    manifest: dict[str, Any],
    ledger: dict[str, Any],
    *,
    block_id: str | None,
    role: str,
    role_mode: str | None = None,
    contract_surfaces: list[str] | None = None,
) -> dict[str, Any]:
    """Build a bounded, role-specific list of case inputs."""
    selected_surfaces = set(contract_surfaces or [])
    unknown_surfaces = sorted(selected_surfaces - CONTRACT_SURFACES)
    if unknown_surfaces:
        raise CaseError("Unknown contract surfaces: " + ", ".join(unknown_surfaces))
    assurance = assurance_level(manifest)
    if assurance == "high":
        selected_surfaces.update(
            {"solution-boundary", "diagram", "reader-projection", "project-rules"}
        )
    recovery = active_bounded_recovery(manifest)

    contract_inputs = [
        f"agents/contracts/{role}.md",
        "references/prompt-contract.md",
        "references/handoff-contract.md",
        "references/convergence-contract.md",
    ]
    if recovery is not None:
        contract_inputs.append("references/bounded-recovery.md")
    surface_paths = {
        "solution-boundary": "references/solution-boundary-contract.md",
        "diagram": "references/diagram-contract.md",
        "reader-projection": "references/reader-projection-contract.md",
    }
    contract_inputs.extend(
        surface_paths[surface]
        for surface in sorted(selected_surfaces)
        if surface in surface_paths
    )

    def covered_gates_for(effective_mode: str) -> list[str]:
        if role != "spec-reviewer":
            return []
        if effective_mode == "final":
            return ["integration_review", "global_review", "project_conformance"]
        return {
            "integration": ["integration_review"],
            "global": ["global_review"],
            "project-conformance": ["project_conformance"],
        }.get(effective_mode, [])

    common = [ROLE_MANIFEST_JSON, "kernel.md", "evidence.md", "decisions.md"]
    if recovery is not None:
        common.insert(1, RECOVERY_PLAN_JSON)
    if isinstance(manifest.get("artifacts", {}).get("working_projection"), str):
        common.insert(1, WORKING_PROJECTION_JSON)
    if manifest.get("planning_handoff") is not None:
        common.insert(1, PLANNING_ROLE_CONTEXT_JSON)
    if manifest.get("mode_decision") is not None:
        common.insert(1, MODE_DECISION_FILENAME)
    method_inputs: list[str] = []
    if manifest.get("method_context") is not None:
        method_inputs = [METHOD_CONTEXT_JSON, METHOD_CONTEXT_MARKDOWN]
    if block_id is None:
        if recovery is not None:
            if role in {"system-analyst", "spec-editor"}:
                raise CaseError("Content roles are forbidden during bounded recovery")
            if role == "spec-reviewer" and recovery.get("combine_final_review"):
                if role_mode != "final":
                    raise CaseError(
                        "Bounded recovery combines whole-case review in role mode final"
                    )
            if role == "solution-architect" and (
                role_mode != "conformance"
                or "architecture_conformance" not in recovery.get("allowed_gates", [])
            ):
                raise CaseError(
                    "Bounded recovery exposes only declared architecture conformance"
                )
        whole_case_block_role = manifest.get("mode") == "block" and (
            (
                role == "spec-reviewer"
                and role_mode in {"integration", "global", "final", "project-conformance"}
            )
            or (role == "spec-editor" and role_mode == "integrate")
            or (
                role == "solution-architect"
                and role_mode in {"risk-preflight", "design", "conformance"}
            )
        )
        if manifest.get("mode") != "compact" and not whole_case_block_role:
            raise CaseError("Block mode context requires --block except for whole-case reviewer modes")
        if role == "system-analyst":
            effective_role_mode = role_mode or "document"
            inputs = common + method_inputs
            excluded = ["draft.md", "reviews/global.md", "author reasoning"]
        elif role == "spec-editor":
            effective_role_mode = role_mode or (
                "integrate" if manifest.get("mode") == "block" else "document"
            )
            block_inputs = [
                str(value)
                for block in ledger.get("blocks", [])
                if isinstance(block, dict)
                for value in (block.get("artifact"), block.get("semantic_index"))
                if isinstance(value, str)
            ]
            inputs = common + ["draft.md", *block_inputs]
            excluded = [*method_inputs, "reviews/global.md", "author reasoning"]
        elif role == "spec-reviewer":
            effective_role_mode = role_mode or "global"
            if (
                effective_role_mode == "final"
                and assurance == "high"
                and not (recovery is not None and recovery.get("combine_final_review"))
            ):
                raise CaseError("High assurance uses separate integration/global/project reviews")
            indexes = [
                str(block.get("semantic_index"))
                for block in ledger.get("blocks", [])
                if isinstance(block, dict) and isinstance(block.get("semantic_index"), str)
            ]
            inputs = common + method_inputs + ["draft.md", *indexes]
            if "project-rules" in selected_surfaces:
                contract_relative = manifest.get("artifacts", {}).get(
                    "project_conformance_contract"
                )
                if isinstance(contract_relative, str):
                    inputs.append(contract_relative)
            excluded = [
                "reviews/*.md",
                "reviews/history/*",
                "author reasoning",
                "previous findings",
            ]
        elif role == "solution-architect":
            effective_role_mode = role_mode or "design"
            if effective_role_mode not in {"risk-preflight", "design", "conformance"}:
                raise CaseError(
                    "Architect role mode must be risk-preflight, design, or conformance"
                )
            semantic_inputs = [
                str(value)
                for block in ledger.get("blocks", [])
                if isinstance(block, dict)
                for value in (block.get("artifact"), block.get("semantic_index"))
                if isinstance(value, str)
            ]
            inputs = (
                common
                if effective_role_mode == "risk-preflight"
                else common + semantic_inputs
            )
            if effective_role_mode == "conformance":
                inputs.append("draft.md")
            excluded = [
                *method_inputs,
                "reviews/*.md",
                "reviews/history/*",
                "author reasoning",
                "previous findings",
            ]
        else:
            raise CaseError(f"Unsupported compact role: {role}")
        required_risk_blocks = {
            block_id for block_id, _ in required_risk_pairs(manifest, ledger)
        }
        risk_scope = (
            [
                {
                    "block_id": block.get("id"),
                    "title": block.get("title"),
                    "depends_on": block.get("depends_on", []),
                    "risk_surfaces": block.get("risk_surfaces", []),
                }
                for block in ledger.get("blocks", [])
                if isinstance(block, dict) and block.get("id") in required_risk_blocks
            ]
            if role == "solution-architect" and effective_role_mode == "risk-preflight"
            else []
        )
        if role == "solution-architect" and effective_role_mode == "risk-preflight" and not risk_scope:
            raise CaseError("Risk preflight context requires at least one declared risk surface")
        recovery_final = (
            recovery is not None
            and role == "spec-reviewer"
            and effective_role_mode == "final"
            and recovery.get("combine_final_review") is True
        )
        if recovery_final:
            recovery_project_contract = manifest.get("artifacts", {}).get(
                "project_conformance_contract"
            )
            inputs = [
                ROLE_MANIFEST_JSON,
                RECOVERY_PLAN_JSON,
                "kernel.md",
                "draft.md",
                *(
                    [str(recovery_project_contract)]
                    if isinstance(recovery_project_contract, str)
                    else []
                ),
                *[
                    str(block.get("semantic_index"))
                    for block in ledger.get("blocks", [])
                    if isinstance(block, dict)
                    and isinstance(block.get("semantic_index"), str)
                ],
            ]
            excluded = [
                "method-context.*",
                "evidence.md",
                "decisions.md",
                "reviews/*.md",
                "reviews/history/*",
                "author reasoning",
                "previous findings",
                "external research",
            ]
        return {
            "case_id": manifest["case_id"],
            "target": "whole-case",
            "role": role,
            "role_mode": effective_role_mode,
            "assurance_level": assurance,
            "review_strategy": (
                "bounded-recovery-final" if recovery_final else REVIEW_STRATEGIES[assurance]
            ),
            "subject_sha256": (
                risk_preflight_subject_hash(manifest, ledger)
                if risk_scope
                else (
                    recovery_final_subject_hash(manifest, ledger, recovery)
                    if recovery_final
                    else None
                )
            ),
            "risk_scope": risk_scope,
            "covered_gates": covered_gates_for(effective_role_mode),
            "contract_surfaces": sorted(selected_surfaces),
            "contract_inputs": list(dict.fromkeys(contract_inputs)),
            "case_inputs": list(dict.fromkeys(inputs)),
            "external_inputs": [
                "resolved project profile",
                "role contract",
                "Vigers prompt and handoff contracts",
                "explicitly named requirement/design artifact when required by the role",
            ],
            "exclude": excluded,
            **(
                {
                    "review_scope": "bounded-recovery-final",
                    "recovery_plan_sha256": recovery.get("sha256"),
                    "new_findings_policy": "user-decision",
                }
                if recovery_final
                else {}
            ),
        }
    blocks = blocks_by_id(ledger)
    if block_id not in blocks:
        raise CaseError(f"Unknown block: {block_id}")
    block = blocks[block_id]
    if recovery is not None:
        block_scopes = recovery.get("block_scopes", {})
        if block_id not in block_scopes:
            raise CaseError(f"{block_id}: outside bounded recovery scope")
        if role != "spec-reviewer":
            raise CaseError("Bounded block recovery exposes only the reviewer role")
    dependencies = [blocks[item] for item in block["depends_on"]]
    dependency_files = [
        value
        for dependency in dependencies
        for value in (dependency["artifact"], dependency["semantic_index"])
    ]
    if role == "system-analyst":
        effective_role_mode = role_mode or "block"
        inputs = common + method_inputs + dependency_files
        excluded = [block["review"], "draft.md", "reviews/global.md"]
    elif role == "spec-editor":
        effective_role_mode = role_mode or "block-render"
        inputs = common + dependency_files + [block["artifact"], block["semantic_index"]]
        excluded = [block["review"], "reviews/global.md"]
    elif role == "spec-reviewer":
        effective_role_mode = role_mode or "block"
        if effective_role_mode != "block":
            raise CaseError("A reviewer with --block must use role mode block")
        remediation = active_block_remediation(block)
        remediation_inputs: list[str] = []
        if remediation is not None:
            remediation_inputs = [
                str(remediation["baseline_artifact"]),
                str(remediation["baseline_index"]),
                str(remediation["finding_evidence"]),
            ]
            coverage_evidence = remediation.get("coverage_evidence")
            if isinstance(coverage_evidence, str):
                remediation_inputs.append(coverage_evidence)
        inputs = (
            common
            + method_inputs
            + dependency_files
            + [block["artifact"], block["semantic_index"]]
            + remediation_inputs
        )
        excluded = [block["review"], "reviews/global.md", "author reasoning"]
        if remediation is None:
            excluded.extend(["reviews/history/*", "previous findings"])
        else:
            excluded.append("unbound reviews/history/*")
    elif role == "solution-architect":
        effective_role_mode = role_mode or "design"
        if effective_role_mode != "design":
            raise CaseError("A block-scoped architect must use role mode design")
        inputs = common + dependency_files + [block["artifact"], block["semantic_index"]]
        excluded = [
            *method_inputs,
            block["review"],
            "reviews/*.md",
            "author reasoning",
            "previous findings",
        ]
    else:
        raise CaseError(f"Unsupported block role: {role}")
    remediation = (
        active_block_remediation(block)
        if role == "spec-reviewer"
        else None
    )
    recovery_subject = (
        recovery_block_subject_hash(manifest, block, str(recovery.get("sha256")))
        if recovery is not None
        else None
    )
    if recovery is not None:
        inputs = [
            ROLE_MANIFEST_JSON,
            RECOVERY_PLAN_JSON,
            "kernel.md",
            *dependency_files,
            block["artifact"],
            block["semantic_index"],
        ]
        excluded = [
            "method-context.*",
            "evidence.md",
            "decisions.md",
            block["review"],
            "reviews/history/*",
            "reviews/global.md",
            "unrelated blocks",
            "author reasoning",
            "previous findings",
            "external research",
        ]
    return {
        "case_id": manifest["case_id"],
        "block": block,
        "role": role,
        "role_mode": effective_role_mode,
        "assurance_level": assurance,
        "review_strategy": (
            "bounded-recovery" if recovery is not None else REVIEW_STRATEGIES[assurance]
        ),
        "review_scope": (
            "bounded-recovery"
            if recovery is not None
            else (
                "targeted-remediation"
                if remediation is not None and remediation.get("scope") == "targeted"
                else "full-block"
            )
        ),
        "subject_sha256": recovery_subject,
        "remediation": remediation,
        "covered_gates": covered_gates_for(effective_role_mode),
        "contract_surfaces": sorted(selected_surfaces),
        "contract_inputs": list(dict.fromkeys(contract_inputs)),
        "case_inputs": list(dict.fromkeys(inputs)),
        "external_inputs": [
            "resolved project profile",
            "role contract",
            "Vigers prompt and handoff contracts",
        ],
        "exclude": excluded,
        **(
            {
                "recovery_plan_sha256": recovery.get("sha256"),
                "reviewed_surfaces": recovery.get("block_scopes", {}).get(block_id),
                "new_findings_policy": "user-decision",
            }
            if recovery is not None
            else {}
        ),
    }


def render_status(root: Path, manifest: dict[str, Any], ledger: dict[str, Any]) -> None:
    """Render a compact human dashboard from machine state."""
    lines = [
        f"# Case {manifest['case_id']}",
        "",
        f"- mode: `{manifest['mode']}`",
        f"- assurance: `{assurance_level(manifest)}`",
        f"- tracking: `{tracking_policy(manifest)}`",
        f"- projection sync: `{projection_sync_policy(manifest)}`",
        f"- intent: `{manifest['intent']}`",
        f"- profile: `{manifest['profile_id']}`",
        f"- route: `{manifest['route_id']}`",
        f"- mode decision: `{'recorded' if manifest.get('mode_decision') else 'legacy-unrecorded'}`",
        f"- method context: `{'recorded' if manifest.get('method_context') else 'legacy-unrecorded'}`",
        f"- planning handoff: `{'recorded' if manifest.get('planning_handoff') else 'legacy-unplanned'}`",
        f"- kernel revision: `{manifest['kernel']['revision']}`",
        f"- updated: `{manifest['updated_at']}`",
    ]
    recovery = bounded_recovery_binding(manifest)
    if recovery is not None:
        lines.extend(
            [
                f"- bounded recovery: `{recovery.get('status', 'invalid')}`",
                f"- recovery blocks: `{', '.join(sorted(recovery.get('block_scopes', {})))}`",
                f"- recovery gates: `{', '.join(recovery.get('allowed_gates', []))}`",
            ]
        )
    projection_relative = manifest.get("artifacts", {}).get("working_projection")
    if isinstance(projection_relative, str):
        try:
            projection = read_json(case_file(root, projection_relative))
            if not isinstance(projection, dict):
                raise CaseError("working projection payload must be an object")
            lines.extend(
                [
                    f"- working projection: `{projection.get('policy', 'invalid')}`",
                    f"- projection targets: `{len(projection.get('targets', []))}`",
                    f"- projection updates: `{len(projection.get('updates', []))}`",
                ]
            )
        except CaseError:
            lines.append("- working projection: `invalid`")
    lines.extend(
        [
            "",
            "## Blocks",
            "",
            "| ID | Kind | Status | Risk preflight | Depends on | Title |",
            "|---|---|---|---|---|---|",
        ]
    )
    if ledger["blocks"]:
        for block in ledger["blocks"]:
            dependencies = ", ".join(block["depends_on"]) or "—"
            risk_surfaces = block.get("risk_surfaces", [])
            risk_status = (
                str((block.get("risk_preflight") or {}).get("status", "pending"))
                if risk_surfaces
                else "not-required"
            )
            lines.append(
                f"| {block['id']} | {block['kind']} | {block['status']} | "
                f"{risk_status} | {dependencies} | {block['title']} |"
            )
    else:
        lines.append("| — | — | — | — | — | compact mode or blocks not planned |")

    lines.extend(["", "## Gates", ""])
    for name in GATE_NAMES:
        gate = manifest["gates"][name]
        checked = "x" if gate["status"] in {"pass", "not_required"} else " "
        suffix = f" — {gate['note']}" if gate.get("note") else ""
        lines.append(f"- [{checked}] `{name}`: {gate['status']}{suffix}")
    timing_relative = manifest.get("artifacts", {}).get("automation_timing")
    if isinstance(timing_relative, str):
        lines.extend(["", "## Automation timing", ""])
        try:
            timing = read_json(case_file(root, timing_relative))
            timing_summary = summarize_automation_timing(timing)
            forecast = timing_summary["forecast"]
            actual = timing_summary["actual"]
            lines.extend(
                [
                    f"- policy: `{timing_summary['policy']}`",
                    "- critical-path forecast: "
                    f"`{forecast['optimistic_critical_path_seconds']} / "
                    f"{forecast['likely_critical_path_seconds']} / "
                    f"{forecast['pessimistic_critical_path_seconds']}` seconds",
                    f"- actual elapsed: `{actual['elapsed_seconds']}` seconds",
                    "- terminal stages: "
                    f"`{timing_summary['terminal_stage_count']}/{timing_summary['stage_count']}`",
                    "- checklist completed: "
                    f"`{timing_summary['completed_checklist_item_count']}/"
                    f"{timing_summary['checklist_item_count']}`",
                ]
            )
        except (CaseError, AutomationTimingError):
            lines.append("- timing ledger is invalid; run `automation_timing.py validate`")
    lines.extend(
        [
            "",
            "## Resume",
            "",
            "Machine truth: `manifest.json` + `ledger.json`. Regenerate this file with "
            "`case_pipeline.py status`.",
            "",
        ]
    )
    (root / "status.md").write_text("\n".join(lines), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line interface."""
    parser = argparse.ArgumentParser(description="Vigers resumable case-state pipeline")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Initialize a case package")
    init_parser.add_argument("--case-root", required=True)
    init_parser.add_argument("--case-id", required=True)
    init_parser.add_argument("--mode", choices=("compact", "block"), required=True)
    init_parser.add_argument(
        "--intent",
        choices=("create", "update", "review", "decompose", "architecture"),
        default="create",
    )
    init_parser.add_argument("--cwd", default=".")
    init_parser.add_argument("--profile-id", default="auto")
    init_parser.add_argument("--route-id", default="core")
    init_parser.add_argument("--project-root")
    init_parser.add_argument(
        "--allow-unrecorded-mode",
        action="store_true",
        help="Migration escape hatch for a case without mode-decision.json",
    )
    init_parser.add_argument(
        "--allow-unrecorded-method",
        action="store_true",
        help="Migration escape hatch for a case without pinned method context",
    )
    init_parser.add_argument(
        "--allow-unplanned",
        action="store_true",
        help="Migration escape hatch for a non-review case without an approved planning handoff",
    )

    migrate_parser = subparsers.add_parser(
        "migrate-planning",
        help="Bind a newer planning handoff while preserving semantic case work",
    )
    migrate_parser.add_argument("--case-root", required=True)
    migrate_parser.add_argument("--handoff-root", required=True)
    migrate_parser.add_argument("--reason", required=True)

    recovery_parser = subparsers.add_parser(
        "begin-recovery",
        help="Bind an explicit frozen-version bounded recovery plan",
    )
    recovery_parser.add_argument("--case-root", required=True)
    recovery_parser.add_argument("--plan", required=True)

    recovery_rebase_parser = subparsers.add_parser(
        "rebase-recovery-block",
        help="Carry one frozen stale block onto the pinned recovery kernel",
    )
    recovery_rebase_parser.add_argument("--case-root", required=True)
    recovery_rebase_parser.add_argument("--id", required=True)

    recovery_complete_parser = subparsers.add_parser(
        "complete-recovery",
        help="Close bounded recovery after all declared evidence passes",
    )
    recovery_complete_parser.add_argument("--case-root", required=True)
    recovery_complete_parser.add_argument("--note", default="")

    recovery_stop_parser = subparsers.add_parser(
        "stop-recovery",
        help="Stop bounded recovery before a new decision or semantic correction",
    )
    recovery_stop_parser.add_argument("--case-root", required=True)
    recovery_stop_parser.add_argument("--reason", required=True)

    add_parser = subparsers.add_parser("add-block", help="Add a semantic block")
    add_parser.add_argument("--case-root", required=True)
    add_parser.add_argument("--id", required=True)
    add_parser.add_argument("--title", required=True)
    add_parser.add_argument("--kind", choices=sorted(BLOCK_KINDS), required=True)
    add_parser.add_argument("--depends-on", action="append", default=[])
    add_parser.add_argument(
        "--risk-surface",
        action="append",
        default=[],
        help="Stable high-risk contract surface requiring an early architecture preflight",
    )

    risk_preflight_parser = subparsers.add_parser(
        "record-risk-preflight",
        help="Bind a complete risk-first architecture matrix before high-risk authoring",
    )
    risk_preflight_parser.add_argument("--case-root", required=True)
    risk_preflight_parser.add_argument("--evidence", required=True)

    declare_risk_parser = subparsers.add_parser(
        "declare-risk",
        help="Pause a block when early analysis discovers a new high-risk surface",
    )
    declare_risk_parser.add_argument("--case-root", required=True)
    declare_risk_parser.add_argument("--id", required=True)
    declare_risk_parser.add_argument(
        "--risk-surface",
        action="append",
        default=[],
        help="Stable newly evidenced high-risk contract surface",
    )
    declare_risk_parser.add_argument("--reason", required=True)

    transition_parser = subparsers.add_parser("transition", help="Move one block")
    transition_parser.add_argument("--case-root", required=True)
    transition_parser.add_argument("--id", required=True)
    transition_parser.add_argument("--status", choices=sorted(BLOCK_STATUSES), required=True)
    transition_parser.add_argument("--note")

    remediation_parser = subparsers.add_parser(
        "begin-remediation",
        help="Open a bounded blocker/major correction without discarding prior review",
    )
    remediation_parser.add_argument("--case-root", required=True)
    remediation_parser.add_argument("--id", required=True)
    remediation_parser.add_argument(
        "--finding",
        action="append",
        default=[],
        help="Stable finding and severity as FINDING_ID=blocker|major",
    )
    remediation_parser.add_argument("--semantic-id", action="append", default=[])
    remediation_parser.add_argument("--evidence", required=True)
    remediation_parser.add_argument("--reason", required=True)
    remediation_parser.add_argument("--full-block", action="store_true")
    remediation_parser.add_argument(
        "--batch-complete",
        action="store_true",
        help="Confirm that every accepted blocker/major from this gate is in the batch",
    )

    refresh_parser = subparsers.add_parser("refresh-kernel", help="Record a kernel edit")
    refresh_parser.add_argument("--case-root", required=True)
    refresh_parser.add_argument("--affects", action="append", default=[])
    refresh_parser.add_argument("--change-scope", choices=sorted(CHANGE_SCOPES))
    refresh_parser.add_argument("--invalidate-all", action="store_true")
    refresh_parser.add_argument("--reason")

    gate_parser = subparsers.add_parser("set-gate", help="Record a workflow gate")
    gate_parser.add_argument("--case-root", required=True)
    gate_parser.add_argument("--name", choices=GATE_NAMES, required=True)
    gate_parser.add_argument("--status", choices=sorted(GATE_STATUSES), required=True)
    gate_parser.add_argument("--evidence")
    gate_parser.add_argument("--note")

    change_parser = subparsers.add_parser(
        "record-change",
        help="Carry passed gates over an explicitly non-semantic delta",
    )
    change_parser.add_argument("--case-root", required=True)
    change_parser.add_argument(
        "--change-scope",
        choices=("editorial", "projection-only"),
        required=True,
    )
    change_parser.add_argument("--reason", required=True)

    remediation_record_parser = subparsers.add_parser(
        "record-remediation",
        help="Reuse prior whole-case review coverage after a bounded targeted correction",
    )
    remediation_record_parser.add_argument("--case-root", required=True)
    remediation_record_parser.add_argument("--id", required=True)
    remediation_record_parser.add_argument("--remediation-id")
    remediation_record_parser.add_argument("--reason", required=True)

    projection_parser = subparsers.add_parser(
        "projection-update",
        help="Record a visible working projection update after read-back",
    )
    projection_parser.add_argument("--case-root", required=True)
    projection_parser.add_argument("--target-id", required=True)
    projection_parser.add_argument("--source", required=True)
    projection_parser.add_argument("--source-sha256", required=True)
    projection_parser.add_argument("--content-sha256", required=True)
    projection_parser.add_argument(
        "--evidence-kind",
        choices=sorted(PROJECTION_EVIDENCE_KINDS),
        required=True,
    )
    projection_parser.add_argument("--evidence-ref", required=True)
    projection_parser.add_argument("--read-back-at", required=True)

    context_parser = subparsers.add_parser("context", help="Print a bounded role context")
    context_parser.add_argument("--case-root", required=True)
    context_parser.add_argument("--block", help="Required in block mode; omit in compact mode")
    context_parser.add_argument(
        "--role",
        choices=(
            "system-analyst",
            "solution-architect",
            "spec-editor",
            "spec-reviewer",
        ),
        required=True,
    )
    context_parser.add_argument("--role-mode")
    context_parser.add_argument(
        "--contract-surface",
        action="append",
        choices=sorted(CONTRACT_SURFACES),
        default=[],
    )

    agent_parser = subparsers.add_parser(
        "record-agent-run",
        help="Append model cost and finding-yield telemetry",
    )
    agent_parser.add_argument("--case-root", required=True)
    agent_parser.add_argument("--role", required=True)
    agent_parser.add_argument("--role-mode", required=True)
    agent_parser.add_argument("--model", required=True)
    agent_parser.add_argument("--subject-sha256", required=True)
    agent_parser.add_argument("--input-bytes", type=int)
    agent_parser.add_argument("--input-tokens", type=int)
    agent_parser.add_argument("--output-tokens", type=int)
    agent_parser.add_argument("--tool-calls", type=int)
    agent_parser.add_argument("--poll-calls", type=int)
    agent_parser.add_argument("--wait-seconds", type=float)
    agent_parser.add_argument("--duration-seconds", type=float, required=True)
    agent_parser.add_argument("--retries", type=int, default=0)
    agent_parser.add_argument("--reported-blocker", type=int, default=0)
    agent_parser.add_argument("--reported-major", type=int, default=0)
    agent_parser.add_argument("--reported-minor", type=int, default=0)
    agent_parser.add_argument(
        "--cache-status",
        choices=("hit", "miss", "unknown"),
        default="unknown",
    )
    agent_parser.add_argument(
        "--status",
        choices=sorted(AGENT_RUN_STATUSES),
        default="completed",
    )
    agent_parser.add_argument("--degraded-reason", action="append", default=[])
    agent_parser.add_argument(
        "--lens",
        action="append",
        default=[],
        help="Versioned review surface as stable-id@positive-version",
    )
    agent_parser.add_argument("--prompt-artifact")
    agent_parser.add_argument("--output-artifact")

    agent_verification_parser = subparsers.add_parser(
        "record-agent-verification",
        help="Record final accepted/rejected/duplicate/verified finding yield",
    )
    agent_verification_parser.add_argument("--case-root", required=True)
    agent_verification_parser.add_argument("--run-id", required=True)
    agent_verification_parser.add_argument("--accepted", type=int, required=True)
    agent_verification_parser.add_argument("--rejected", type=int, required=True)
    agent_verification_parser.add_argument("--duplicate", type=int, required=True)
    agent_verification_parser.add_argument("--verified", type=int, required=True)
    agent_verification_parser.add_argument("--evidence-ref", required=True)

    check_parser = subparsers.add_parser("check", help="Run checks and update consistency gate")
    check_parser.add_argument("--case-root", required=True)
    check_parser.add_argument("--final-trace", action="store_true")

    validate_parser = subparsers.add_parser("validate", help="Validate case state")
    validate_parser.add_argument("--case-root", required=True)
    validate_parser.add_argument("--final", action="store_true")

    status_parser = subparsers.add_parser("status", help="Refresh and print status")
    status_parser.add_argument("--case-root", required=True)
    status_parser.add_argument("--json", action="store_true")
    return parser


def main() -> int:
    """CLI entry point."""
    parser = build_parser()
    args = parser.parse_args()
    try:
        if args.command == "init":
            selection, selected_project_root = resolve_init_project_context(
                args.profile_id,
                Path(args.cwd),
                Path(args.project_root) if args.project_root else None,
            )
            init_case(
                Path(args.case_root),
                case_id=args.case_id,
                mode=args.mode,
                intent=args.intent,
                profile_id=selection.profile_id,
                route_id=args.route_id,
                project_root=selected_project_root,
                document_contract=selection.document_contract,
                allow_unrecorded_mode=args.allow_unrecorded_mode,
                allow_unrecorded_method=args.allow_unrecorded_method,
                allow_unplanned=args.allow_unplanned,
            )
            print(f"PASS case={args.case_id} mode={args.mode}")
            return 0

        root, manifest, ledger = load_case(Path(args.case_root))
        if args.command == "begin-recovery":
            result = begin_bounded_recovery(
                root,
                manifest,
                ledger,
                plan_path=Path(args.plan),
            )
            print(
                f"PASS bounded-recovery={result['status']} plan={result['sha256']}"
            )
            return 0
        if args.command == "rebase-recovery-block":
            rebase_bounded_recovery_block(
                root,
                manifest,
                ledger,
                block_id=args.id,
            )
            print(f"PASS bounded-recovery-block={args.id} status=analyzed")
            return 0
        if args.command == "complete-recovery":
            complete_bounded_recovery(
                root,
                manifest,
                ledger,
                note=args.note,
            )
            print("PASS bounded-recovery=complete")
            return 0
        if args.command == "stop-recovery":
            stop_bounded_recovery(
                root,
                manifest,
                ledger,
                reason=args.reason,
            )
            print("PASS bounded-recovery=cancelled")
            return 0
        if args.command == "migrate-planning":
            result = migrate_planning_handoff(
                root,
                manifest,
                ledger,
                handoff_root=Path(args.handoff_root),
                reason=args.reason,
            )
            print(
                "PASS planning-migration="
                f"r{result['from_revision']}->r{result['to_revision']} "
                f"archive={'recorded' if result['archived_files'] else 'none'}"
            )
            return 0
        if args.command == "add-block":
            add_block(
                root,
                manifest,
                ledger,
                block_id=args.id,
                title=args.title,
                kind=args.kind,
                depends_on=args.depends_on,
                risk_surfaces=args.risk_surface,
            )
            print(f"PASS block={args.id} status=planned")
            return 0
        if args.command == "record-risk-preflight":
            result = record_risk_preflight(
                root,
                manifest,
                ledger,
                evidence=args.evidence,
            )
            print(
                f"PASS risk-preflight=r{result['revision']} "
                f"surfaces={len(result['coverage'])}"
            )
            return 0
        if args.command == "declare-risk":
            surfaces = declare_block_risks(
                root,
                manifest,
                ledger,
                block_id=args.id,
                risk_surfaces=args.risk_surface,
                reason=args.reason,
            )
            print(
                f"PASS block={args.id} risks={','.join(surfaces)} "
                f"status={blocks_by_id(ledger)[args.id]['status']}"
            )
            return 0
        if args.command == "transition":
            transition_block(
                root,
                manifest,
                ledger,
                block_id=args.id,
                new_status=args.status,
                note=args.note,
            )
            print(f"PASS block={args.id} status={args.status}")
            return 0
        if args.command == "begin-remediation":
            remediation = begin_block_remediation(
                root,
                manifest,
                ledger,
                block_id=args.id,
                findings=parse_remediation_findings(args.finding),
                semantic_ids=args.semantic_id,
                evidence=args.evidence,
                reason=args.reason,
                full_block=args.full_block,
                batch_complete=args.batch_complete,
            )
            print(
                f"PASS block={args.id} remediation={remediation['id']} "
                f"scope={remediation['scope']} cycle={remediation['cycle']} "
                f"batch={remediation.get('batch_index') or '-'}"
            )
            return 0
        if args.command == "refresh-kernel":
            if "assurance_level" in manifest and args.change_scope is None:
                raise CaseError(
                    "Assurance-aware cases require --change-scope for refresh-kernel"
                )
            stale = refresh_kernel(
                root,
                manifest,
                ledger,
                args.affects,
                change_scope=args.change_scope,
                invalidate_all=args.invalidate_all,
                reason=args.reason,
            )
            print(
                f"PASS revision={manifest['kernel']['revision']} "
                f"stale={','.join(stale) if stale else '-'}"
            )
            return 0
        if args.command == "set-gate":
            set_gate(
                root,
                manifest,
                ledger,
                name=args.name,
                status=args.status,
                evidence=args.evidence,
                note=args.note,
            )
            print(f"PASS gate={args.name} status={args.status}")
            return 0
        if args.command == "record-change":
            rebased = rebase_nonsemantic_change(
                root,
                manifest,
                ledger,
                change_scope=args.change_scope,
                reason=args.reason,
            )
            print(
                "PASS nonsemantic-change="
                f"{args.change_scope} rebased={','.join(rebased) if rebased else '-'}"
            )
            return 0
        if args.command == "record-remediation":
            rebased = record_semantic_remediation(
                root,
                manifest,
                ledger,
                block_id=args.id,
                remediation_id=args.remediation_id,
                reason=args.reason,
            )
            print(
                f"PASS remediation={args.remediation_id or 'latest'} "
                f"rebased={','.join(rebased) if rebased else '-'}"
            )
            return 0
        if args.command == "projection-update":
            record_working_projection_update(
                root,
                manifest,
                ledger,
                target_id=args.target_id,
                source=args.source,
                source_sha256=args.source_sha256,
                content_sha256=args.content_sha256,
                evidence_kind=args.evidence_kind,
                evidence_ref=args.evidence_ref,
                read_back_at=args.read_back_at,
            )
            print(f"PASS projection={args.target_id} source={args.source}")
            return 0
        if args.command == "context":
            print(
                json.dumps(
                    context_bundle(
                        manifest,
                        ledger,
                        block_id=args.block,
                        role=args.role,
                        role_mode=args.role_mode,
                        contract_surfaces=args.contract_surface,
                    ),
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        if args.command == "record-agent-run":
            run_id = record_agent_run(
                root,
                manifest,
                ledger,
                role=args.role,
                role_mode=args.role_mode,
                model=args.model,
                subject_sha256=args.subject_sha256,
                input_bytes=args.input_bytes,
                input_tokens=args.input_tokens,
                output_tokens=args.output_tokens,
                duration_seconds=args.duration_seconds,
                retries=args.retries,
                reported_blocker=args.reported_blocker,
                reported_major=args.reported_major,
                reported_minor=args.reported_minor,
                cache_status=args.cache_status,
                status=args.status,
                degraded_reasons=args.degraded_reason,
                lenses=args.lens,
                prompt_artifact=args.prompt_artifact,
                output_artifact=args.output_artifact,
                tool_calls=args.tool_calls,
                poll_calls=args.poll_calls,
                wait_seconds=args.wait_seconds,
            )
            print(f"PASS agent-run={run_id} role={args.role}/{args.role_mode}")
            return 0
        if args.command == "record-agent-verification":
            record_agent_verification(
                root,
                manifest,
                ledger,
                run_id=args.run_id,
                accepted=args.accepted,
                rejected=args.rejected,
                duplicate=args.duplicate,
                verified=args.verified,
                evidence_ref=args.evidence_ref,
            )
            print(f"PASS agent-verification={args.run_id}")
            return 0
        if args.command == "check":
            errors = run_check(root, manifest, ledger, final_trace=args.final_trace)
            if errors:
                raise CaseError("\n".join(f"- {item}" for item in errors))
            print(f"PASS consistency=pass final_trace={str(args.final_trace).lower()}")
            return 0
        if args.command == "validate":
            errors = validate_case(root, manifest, ledger, final=args.final)
            if errors:
                raise CaseError("\n".join(f"- {item}" for item in errors))
            print(
                f"PASS case={manifest['case_id']} blocks={len(ledger['blocks'])} "
                f"final={str(args.final).lower()}"
            )
            return 0
        if args.command == "status":
            render_status(root, manifest, ledger)
            if args.json:
                print(
                    json.dumps(
                        {"manifest": manifest, "ledger": ledger},
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            else:
                print((root / "status.md").read_text(encoding="utf-8"))
            return 0
        raise AssertionError(args.command)
    except (OSError, CaseError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
