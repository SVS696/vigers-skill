#!/usr/bin/env python3
"""Deterministic, resumable case-state orchestration for Vigers."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
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
from mode_decision import (
    MODE_DECISION_FILENAME,
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
EXTERNAL_READBACK_RECEIPT_SCHEMA = 1
CASE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
BLOCK_ID_RE = re.compile(r"^B[0-9]{2,3}$")
SEMANTIC_ID_RE = re.compile(
    r"^(GOAL|ACT|SCN|RULE|DATA|STATE|IF|QUAL|REQ|AC|DOD|ASM|Q|DEC|CON)-"
    r"(B[0-9]{2,3})-[0-9]{3}$"
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

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
        "timing_visibility": "human_information_only",
        "excluded_fields": ["automation_plan", "automation_estimation", "estimates"],
    }
    result["fingerprint"] = role_context_fingerprint(result)
    return result


def role_context_fingerprint(payload: dict[str, Any]) -> str:
    """Hash a bounded role context without trusting its stored fingerprint."""
    encoded = json.dumps(
        {key: value for key, value in payload.items() if key != "fingerprint"},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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
    seen_updates: set[tuple[str, str, str, str]] = set()
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
        if key in seen_updates:
            errors.append(f"duplicate working projection update: {target_id}/{update.get('source')}")
        seen_updates.add(key)
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
    return {
        item["source"]: item["source_sha256"]
        for item in payload.get("updates", [])
        if isinstance(item, dict)
        and item.get("target_id") == target_id
        and isinstance(item.get("source"), str)
        and isinstance(item.get("source_sha256"), str)
    }


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


def initial_gates(mode: str) -> dict[str, dict[str, Any]]:
    """Create gate state, skipping block-only gates in compact mode."""
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
    return gates


def init_case(
    root: Path,
    *,
    case_id: str,
    mode: str,
    intent: str,
    profile_id: str,
    route_id: str,
    project_root: str | None,
    allow_unrecorded_mode: bool = False,
    allow_unrecorded_method: bool = False,
    allow_unplanned: bool = False,
) -> None:
    """Create a new case package."""
    if not CASE_ID_RE.fullmatch(case_id):
        raise CaseError(f"Invalid case id: {case_id!r}")
    if mode not in {"compact", "block"}:
        raise CaseError(f"Invalid mode: {mode}")

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
        "intent": intent,
        "profile_id": profile_id,
        "route_id": route_id,
        "project_root": project_root,
        "mode_decision": decision_binding,
        "method_context": method_binding,
        "planning_handoff": planning_binding,
        "created_at": now_utc(),
        "updated_at": now_utc(),
        "kernel": {
            "path": "kernel.md",
            "revision": 1,
            "sha256": sha256(root / "kernel.md"),
        },
        "artifacts": {
            "automation_timing": AUTOMATION_TIMING_FILENAME,
            "role_manifest": ROLE_MANIFEST_JSON,
            "planning_role_context": (
                PLANNING_ROLE_CONTEXT_JSON if planning_binding is not None else None
            ),
            "working_projection": WORKING_PROJECTION_JSON,
            "evidence": "evidence.md",
            "decisions": "decisions.md",
            "draft": "draft.md",
            "integration_review": "reviews/integration.md",
            "global_review": "reviews/global.md",
            "project_conformance": "reviews/project.md",
            "architecture_conformance": "reviews/architecture.md",
            "consistency_report": "consistency.json",
        },
        "gates": initial_gates(mode),
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
        automation_plan=(planning_payload or {}).get("automation_plan"),
        planning_case_id=(planning_payload or {}).get("planning_case_id"),
        planning_revision=(planning_payload or {}).get("planning_revision"),
        passport=(planning_payload or {}).get("passport"),
    )
    atomic_json(manifest_path, manifest)
    atomic_json(root / ROLE_MANIFEST_JSON, role_manifest(manifest))
    atomic_json(root / "ledger.json", ledger)
    atomic_json(root / AUTOMATION_TIMING_FILENAME, automation_ledger)
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
        automation_plan=new_payload.get("automation_plan"),
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
    duplicate = next(
        (
            item
            for item in payload["updates"]
            if isinstance(item, dict)
            and item.get("target_id") == target_id
            and item.get("source") == candidate["source"]
            and item.get("source_sha256") == normalized_source_hash
            and item.get("content_sha256") == normalized_content_hash
        ),
        None,
    )
    if duplicate is not None:
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
) -> None:
    """Add one semantic block to the dependency ledger."""
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
    manifest["events"].append(event("block_added", block_id=block_id, kind_name=kind))
    save_case(root, manifest, ledger)


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


def refresh_kernel(
    root: Path,
    manifest: dict[str, Any],
    ledger: dict[str, Any],
    affected_ids: list[str],
) -> list[str]:
    """Advance the kernel revision and invalidate affected completed work."""
    _, current_hash = current_kernel(root, manifest)
    if current_hash == manifest["kernel"]["sha256"]:
        return []

    blocks = blocks_by_id(ledger)
    seeds = set(affected_ids) if affected_ids else set(blocks)
    unknown = sorted(seeds - set(blocks))
    if unknown:
        raise CaseError(f"Unknown affected blocks: {', '.join(unknown)}")
    affected = downstream_closure(ledger, seeds)

    manifest["kernel"]["revision"] += 1
    manifest["kernel"]["sha256"] = current_hash
    stale: list[str] = []
    for block_id in sorted(affected):
        block = blocks[block_id]
        if block["status"] in {"in_progress", "analyzed", "reviewed", "integrated"}:
            block["status_before_stale"] = block["status"]
            block["status"] = "stale"
            block["note"] = f"kernel revision changed to {manifest['kernel']['revision']}"
            block["updated_at"] = now_utc()
            stale.append(block_id)

    if stale:
        for gate_name in (
            "author_passes",
            "semantic_integration",
            "consistency",
            "integration_review",
            "global_review",
            "project_conformance",
            "architecture_conformance",
        ):
            gate = manifest["gates"][gate_name]
            if gate["status"] != "not_required":
                gate.update(status="pending", evidence=None, note="kernel changed")
                gate["evidence_sha256"] = None
                gate["subject_sha256"] = None
    manifest["events"].append(
        event(
            "kernel_refreshed",
            revision=manifest["kernel"]["revision"],
            affected=sorted(affected),
            stale=stale,
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
    if new_status not in ALLOWED_TRANSITIONS[old_status]:
        raise CaseError(f"Invalid transition {old_status} -> {new_status} for {block_id}")

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
        if not artifact_ready(case_file(root, block["review"])):
            raise CaseError(f"{block_id}: review artifact is missing or still a placeholder")
        if block["kernel_sha256"] != manifest["kernel"]["sha256"]:
            raise CaseError(f"{block_id}: analysis is stale against the kernel")
        if sha256(case_file(root, block["artifact"])) != block["artifact_sha256"]:
            raise CaseError(f"{block_id}: analysis changed after analyzed state")
        if sha256(case_file(root, block["semantic_index"])) != block["index_sha256"]:
            raise CaseError(f"{block_id}: semantic index changed after analyzed state")
        block["review_sha256"] = sha256(case_file(root, block["review"]))
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
    elif name == "semantic_integration":
        draft = case_file(root, manifest["artifacts"]["draft"])
        digest.update(draft.read_bytes() if draft.is_file() else b"<missing>")
        digest.update(block_subject_hash(root, ledger).encode("ascii"))
    elif name == "consistency":
        report = case_file(root, manifest["artifacts"]["consistency_report"])
        digest.update(report.read_bytes() if report.is_file() else b"<missing>")
    else:
        draft = case_file(root, manifest["artifacts"]["draft"])
        digest.update(draft.read_bytes() if draft.is_file() else b"<missing>")
        digest.update(manifest["kernel"]["sha256"].encode("ascii"))
    return digest.hexdigest()


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
    if status not in GATE_STATUSES:
        raise CaseError(f"Invalid gate status: {status}")
    if name == "consistency" and status == "pass":
        raise CaseError("Use the check command to pass the consistency gate")
    if status == "blocked" and not note:
        raise CaseError("A blocked gate requires --note")
    if status == "not_required" and not note:
        raise CaseError("A not_required gate requires --note")
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
    evidence_hash = None
    subject_hash = None
    if status == "pass" and evidence:
        path = case_file(root, evidence)
        if not artifact_ready(path):
            raise CaseError(f"Gate evidence is missing or still a placeholder: {evidence}")
        evidence_hash = sha256(path)
        subject_hash = gate_subject_hash(root, manifest, ledger, name)

    manifest["gates"][name] = {
        "status": status,
        "evidence": evidence,
        "evidence_sha256": evidence_hash,
        "subject_sha256": subject_hash,
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
) -> list[str]:
    """Return structural, freshness, traceability, and optional final errors."""
    errors: list[str] = []
    errors.extend(
        working_projection_errors(
            root,
            manifest,
            ledger,
            require_any_update=final,
        )
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
                    expected_plan=(planning_payload or {}).get("automation_plan"),
                    expected_planning_case_id=(planning_payload or {}).get("planning_case_id"),
                    expected_planning_revision=(planning_payload or {}).get("planning_revision"),
                )
                errors.extend(timing_errors)
            except (CaseError, AutomationTimingError) as exc:
                errors.append(f"Invalid automation timing: {exc}")
    role_manifest_relative = manifest.get("artifacts", {}).get("role_manifest")
    if role_manifest_relative != ROLE_MANIFEST_JSON:
        errors.append("manifest role_manifest path is invalid")
    else:
        try:
            stored_role_manifest = read_json(case_file(root, ROLE_MANIFEST_JSON))
            expected_role_manifest = role_manifest(manifest)
            if stored_role_manifest != expected_role_manifest:
                errors.append("role-manifest.json differs from coordinator manifest projection")
        except CaseError as exc:
            errors.append(f"Invalid role manifest: {exc}")
    try:
        ensure_acyclic(ledger)
    except CaseError as exc:
        errors.append(str(exc))

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
        errors.extend(item for item in trace_errors if not item.startswith("Gate "))
    report = {
        "schema": SCHEMA_VERSION,
        "case_id": manifest["case_id"],
        "checked_at": now_utc(),
        "final_trace": final_trace,
        "kernel_revision": manifest["kernel"]["revision"],
        "kernel_sha256": manifest["kernel"]["sha256"],
        "block_subject_sha256": block_subject_hash(root, ledger),
        "draft_sha256": sha256(case_file(root, manifest["artifacts"]["draft"])),
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
) -> dict[str, Any]:
    """Build a bounded, role-specific list of case inputs."""
    common = [ROLE_MANIFEST_JSON, "kernel.md", "evidence.md", "decisions.md"]
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
        if manifest.get("mode") != "compact":
            raise CaseError("Block mode context requires --block")
        if role == "system-analyst":
            inputs = common + method_inputs
            excluded = ["draft.md", "reviews/global.md", "author reasoning"]
        elif role == "spec-editor":
            inputs = common + ["draft.md"]
            excluded = [*method_inputs, "reviews/global.md", "author reasoning"]
        elif role == "spec-reviewer":
            inputs = common + method_inputs + ["draft.md"]
            excluded = ["reviews/global.md", "author reasoning", "previous findings"]
        else:
            raise CaseError(f"Unsupported compact role: {role}")
        return {
            "case_id": manifest["case_id"],
            "target": "whole-case",
            "role": role,
            "case_inputs": list(dict.fromkeys(inputs)),
            "external_inputs": [
                "resolved project profile",
                "role contract",
                "Vigers prompt and handoff contracts",
                "explicitly named requirement/design artifact when required by the role",
            ],
            "exclude": excluded,
        }
    blocks = blocks_by_id(ledger)
    if block_id not in blocks:
        raise CaseError(f"Unknown block: {block_id}")
    block = blocks[block_id]
    dependencies = [blocks[item] for item in block["depends_on"]]
    dependency_files = [
        value
        for dependency in dependencies
        for value in (dependency["artifact"], dependency["semantic_index"])
    ]
    if role == "system-analyst":
        inputs = common + method_inputs + dependency_files
        excluded = [block["review"], "draft.md", "reviews/global.md"]
    elif role == "spec-editor":
        inputs = common + dependency_files + [block["artifact"], block["semantic_index"]]
        excluded = [block["review"], "reviews/global.md"]
    elif role == "spec-reviewer":
        inputs = (
            common
            + method_inputs
            + dependency_files
            + [block["artifact"], block["semantic_index"]]
        )
        excluded = [block["review"], "reviews/global.md", "author reasoning"]
    else:
        raise CaseError(f"Unsupported block role: {role}")
    return {
        "case_id": manifest["case_id"],
        "block": block,
        "role": role,
        "case_inputs": list(dict.fromkeys(inputs)),
        "external_inputs": [
            "resolved project profile",
            "role contract",
            "Vigers prompt and handoff contracts",
        ],
        "exclude": excluded,
    }


def render_status(root: Path, manifest: dict[str, Any], ledger: dict[str, Any]) -> None:
    """Render a compact human dashboard from machine state."""
    lines = [
        f"# Case {manifest['case_id']}",
        "",
        f"- mode: `{manifest['mode']}`",
        f"- intent: `{manifest['intent']}`",
        f"- profile: `{manifest['profile_id']}`",
        f"- route: `{manifest['route_id']}`",
        f"- mode decision: `{'recorded' if manifest.get('mode_decision') else 'legacy-unrecorded'}`",
        f"- method context: `{'recorded' if manifest.get('method_context') else 'legacy-unrecorded'}`",
        f"- planning handoff: `{'recorded' if manifest.get('planning_handoff') else 'legacy-unplanned'}`",
        f"- kernel revision: `{manifest['kernel']['revision']}`",
        f"- updated: `{manifest['updated_at']}`",
    ]
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
            "| ID | Kind | Status | Depends on | Title |",
            "|---|---|---|---|---|",
        ]
    )
    if ledger["blocks"]:
        for block in ledger["blocks"]:
            dependencies = ", ".join(block["depends_on"]) or "—"
            lines.append(
                f"| {block['id']} | {block['kind']} | {block['status']} | "
                f"{dependencies} | {block['title']} |"
            )
    else:
        lines.append("| — | — | — | — | compact mode or blocks not planned |")

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

    add_parser = subparsers.add_parser("add-block", help="Add a semantic block")
    add_parser.add_argument("--case-root", required=True)
    add_parser.add_argument("--id", required=True)
    add_parser.add_argument("--title", required=True)
    add_parser.add_argument("--kind", choices=sorted(BLOCK_KINDS), required=True)
    add_parser.add_argument("--depends-on", action="append", default=[])

    transition_parser = subparsers.add_parser("transition", help="Move one block")
    transition_parser.add_argument("--case-root", required=True)
    transition_parser.add_argument("--id", required=True)
    transition_parser.add_argument("--status", choices=sorted(BLOCK_STATUSES), required=True)
    transition_parser.add_argument("--note")

    refresh_parser = subparsers.add_parser("refresh-kernel", help="Record a kernel edit")
    refresh_parser.add_argument("--case-root", required=True)
    refresh_parser.add_argument("--affects", action="append", default=[])

    gate_parser = subparsers.add_parser("set-gate", help="Record a workflow gate")
    gate_parser.add_argument("--case-root", required=True)
    gate_parser.add_argument("--name", choices=GATE_NAMES, required=True)
    gate_parser.add_argument("--status", choices=sorted(GATE_STATUSES), required=True)
    gate_parser.add_argument("--evidence")
    gate_parser.add_argument("--note")

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
        choices=("system-analyst", "spec-editor", "spec-reviewer"),
        required=True,
    )

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
                allow_unrecorded_mode=args.allow_unrecorded_mode,
                allow_unrecorded_method=args.allow_unrecorded_method,
                allow_unplanned=args.allow_unplanned,
            )
            print(f"PASS case={args.case_id} mode={args.mode}")
            return 0

        root, manifest, ledger = load_case(Path(args.case_root))
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
            )
            print(f"PASS block={args.id} status=planned")
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
        if args.command == "refresh-kernel":
            stale = refresh_kernel(root, manifest, ledger, args.affects)
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
                    ),
                    ensure_ascii=False,
                    indent=2,
                )
            )
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
