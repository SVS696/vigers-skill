#!/usr/bin/env python3
"""Deterministic mode selection shared by Vigers pipeline commands."""

from __future__ import annotations

import hashlib
import json
from typing import Any


MODE_DECISION_SCHEMA = 1
MODE_DECISION_FILENAME = "mode-decision.json"
MODES = {"compact", "block"}
ASSURANCE_LEVELS = {"lite", "standard", "high"}
CHANGE_SCOPES = {
    "editorial",
    "projection-only",
    "semantic-local",
    "semantic-crosscutting",
    "architecture",
}
TRACKING_POLICIES = {"off", "milestones", "fine"}
PROJECTION_SYNC_POLICIES = {"milestones", "per-block"}
SURFACES = {
    "scenarios",
    "rules",
    "data",
    "interfaces",
    "permissions",
    "states",
    "errors",
    "qualities",
}


class ModeDecisionError(RuntimeError):
    """Invalid facts, decision payload, or decision binding."""


def normalized_values(values: list[str], *, label: str) -> list[str]:
    """Return stable, unique non-empty values for deterministic evaluation."""
    normalized: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise ModeDecisionError(f"{label} must contain non-empty strings")
        normalized.add(value.strip())
    return sorted(normalized)


def fingerprint(payload: dict[str, Any]) -> str:
    """Hash a decision without trusting its stored fingerprint."""
    canonical = {key: value for key, value in payload.items() if key != "fingerprint"}
    encoded = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_mode_decision(
    *,
    task: str,
    profile_id: str,
    profile_file: str,
    profile_source: str,
    project_root: str | None,
    estimated_blocks: int,
    surfaces: list[str],
    components: list[str],
    owners: list[str],
    dependent_parts: bool,
    unsafe_single_pass: bool,
    project_triggers: list[str],
    requested_mode: str | None,
    change_scope: str = "semantic-local",
    public_contract: bool = False,
    data_migration: bool = False,
    security_or_permissions: bool = False,
    cross_service: bool = False,
    irreversible: bool = False,
    compliance: bool = False,
    requested_assurance: str | None = None,
    requested_tracking: str | None = None,
    requested_projection_sync: str | None = None,
) -> dict[str, Any]:
    """Select context scale and assurance independently from observable facts."""
    task = task.strip()
    if not task:
        raise ModeDecisionError("task must be non-empty")
    if estimated_blocks < 1:
        raise ModeDecisionError("estimated_blocks must be at least 1")
    if requested_mode is not None and requested_mode not in MODES:
        raise ModeDecisionError(f"invalid requested mode: {requested_mode!r}")
    if change_scope not in CHANGE_SCOPES:
        raise ModeDecisionError(f"invalid change scope: {change_scope!r}")
    if requested_assurance is not None and requested_assurance not in ASSURANCE_LEVELS:
        raise ModeDecisionError(f"invalid requested assurance: {requested_assurance!r}")
    if requested_tracking is not None and requested_tracking not in TRACKING_POLICIES:
        raise ModeDecisionError(f"invalid requested tracking: {requested_tracking!r}")
    if (
        requested_projection_sync is not None
        and requested_projection_sync not in PROJECTION_SYNC_POLICIES
    ):
        raise ModeDecisionError(
            f"invalid requested projection sync: {requested_projection_sync!r}"
        )

    stable_surfaces = normalized_values(surfaces, label="surfaces")
    unknown_surfaces = sorted(set(stable_surfaces) - SURFACES)
    if unknown_surfaces:
        raise ModeDecisionError(f"unknown surfaces: {', '.join(unknown_surfaces)}")
    stable_components = normalized_values(components, label="components")
    stable_owners = normalized_values(owners, label="owners")
    stable_project_triggers = normalized_values(
        project_triggers,
        label="project_triggers",
    )

    triggered_rules: list[dict[str, str]] = []
    if estimated_blocks >= 3:
        triggered_rules.append(
            {
                "id": "MODE-BLOCK-COUNT",
                "reason": f"estimated independently verifiable blocks: {estimated_blocks}",
            }
        )
    if len(stable_surfaces) >= 2:
        triggered_rules.append(
            {
                "id": "MODE-MULTI-SURFACE",
                "reason": "multiple semantic surfaces: " + ", ".join(stable_surfaces),
            }
        )
    if len(stable_components) >= 2:
        triggered_rules.append(
            {
                "id": "MODE-MULTI-COMPONENT",
                "reason": "multiple affected components: " + ", ".join(stable_components),
            }
        )
    if len(stable_owners) >= 2:
        triggered_rules.append(
            {
                "id": "MODE-MULTI-OWNER",
                "reason": "multiple data or decision owners: " + ", ".join(stable_owners),
            }
        )
    if dependent_parts:
        triggered_rules.append(
            {
                "id": "MODE-DEPENDENT-PARTS",
                "reason": "task parts require an explicit dependency order",
            }
        )
    if unsafe_single_pass:
        triggered_rules.append(
            {
                "id": "MODE-UNSAFE-SINGLE-PASS",
                "reason": "source corpus or target document is unsafe for one role pass",
            }
        )
    if stable_project_triggers:
        triggered_rules.append(
            {
                "id": "MODE-PROJECT-TRIGGER",
                "reason": "project profile triggers: " + ", ".join(stable_project_triggers),
            }
        )

    recommended_mode = "block" if triggered_rules else "compact"
    selected_mode = requested_mode or recommended_mode
    warnings: list[str] = []
    if requested_mode is not None and requested_mode != recommended_mode:
        warnings.append(
            f"explicit mode {requested_mode!r} overrides rule recommendation "
            f"{recommended_mode!r}"
        )

    risk_facts = {
        "change_scope": change_scope,
        "public_contract": public_contract,
        "data_migration": data_migration,
        "security_or_permissions": security_or_permissions,
        "cross_service": cross_service,
        "irreversible": irreversible,
        "compliance": compliance,
    }
    assurance_rules: list[dict[str, str]] = []
    for rule_id, active, reason in (
        ("ASSURANCE-ARCHITECTURE", change_scope == "architecture", "architecture decision"),
        ("ASSURANCE-PUBLIC-CONTRACT", public_contract, "public contract change"),
        ("ASSURANCE-DATA-MIGRATION", data_migration, "data migration or schema change"),
        ("ASSURANCE-SECURITY", security_or_permissions, "security or permission boundary"),
        ("ASSURANCE-CROSS-SERVICE", cross_service, "cross-service ownership or flow"),
        ("ASSURANCE-IRREVERSIBLE", irreversible, "irreversible or high-blast-radius change"),
        ("ASSURANCE-COMPLIANCE", compliance, "compliance or regulatory constraint"),
    ):
        if active:
            assurance_rules.append({"id": rule_id, "reason": reason})
    if assurance_rules:
        recommended_assurance = "high"
    elif change_scope in {"editorial", "projection-only"}:
        recommended_assurance = "lite"
    else:
        recommended_assurance = "standard"
    selected_assurance = requested_assurance or recommended_assurance
    if requested_assurance is not None and requested_assurance != recommended_assurance:
        warnings.append(
            f"explicit assurance {requested_assurance!r} overrides risk recommendation "
            f"{recommended_assurance!r}"
        )

    # Progress granularity is a user/project preference, not an assurance cost.
    # Detailed Pxx-Cxx items remain the portable default even when reviews are
    # combined under standard assurance.
    recommended_tracking = "fine"
    selected_tracking = requested_tracking or recommended_tracking
    recommended_projection_sync = (
        "per-block"
        if selected_assurance == "high" and selected_mode == "block"
        else "milestones"
    )
    selected_projection_sync = requested_projection_sync or recommended_projection_sync

    payload: dict[str, Any] = {
        "schema": MODE_DECISION_SCHEMA,
        "task": task,
        "profile": {
            "id": profile_id,
            "file": profile_file,
            "source": profile_source,
            "project_root": project_root,
        },
        "facts": {
            "estimated_blocks": estimated_blocks,
            "surfaces": stable_surfaces,
            "components": stable_components,
            "owners": stable_owners,
            "dependent_parts": dependent_parts,
            "unsafe_single_pass": unsafe_single_pass,
            "project_triggers": stable_project_triggers,
        },
        "triggered_rules": triggered_rules,
        "recommended_mode": recommended_mode,
        "requested_mode": requested_mode,
        "selected_mode": selected_mode,
        "selection_source": "explicit" if requested_mode is not None else "rules",
        "warnings": warnings,
        "risk_facts": risk_facts,
        "triggered_assurance_rules": assurance_rules,
        "recommended_assurance": recommended_assurance,
        "requested_assurance": requested_assurance,
        "selected_assurance": selected_assurance,
        "assurance_selection_source": (
            "explicit" if requested_assurance is not None else "risk-rules"
        ),
        "recommended_tracking": recommended_tracking,
        "requested_tracking": requested_tracking,
        "selected_tracking": selected_tracking,
        "recommended_projection_sync": recommended_projection_sync,
        "requested_projection_sync": requested_projection_sync,
        "selected_projection_sync": selected_projection_sync,
    }
    payload["fingerprint"] = fingerprint(payload)
    return payload


def validate_mode_decision(
    payload: Any,
    *,
    expected_mode: str | None = None,
    expected_profile_id: str | None = None,
) -> None:
    """Validate schema, fingerprint, and optional case bindings."""
    if not isinstance(payload, dict):
        raise ModeDecisionError("mode decision must be a JSON object")
    if payload.get("schema") != MODE_DECISION_SCHEMA:
        raise ModeDecisionError("unsupported mode decision schema")
    if payload.get("recommended_mode") not in MODES:
        raise ModeDecisionError("invalid recommended_mode")
    if payload.get("requested_mode") is not None and payload.get("requested_mode") not in MODES:
        raise ModeDecisionError("invalid requested_mode")
    if payload.get("selected_mode") not in MODES:
        raise ModeDecisionError("invalid selected_mode")
    if payload.get("selection_source") not in {"rules", "explicit"}:
        raise ModeDecisionError("invalid selection_source")
    if not isinstance(payload.get("task"), str) or not payload["task"].strip():
        raise ModeDecisionError("mode decision has no task")
    profile = payload.get("profile")
    if (
        not isinstance(profile, dict)
        or not isinstance(profile.get("id"), str)
        or not profile["id"].strip()
    ):
        raise ModeDecisionError("mode decision has no profile id")
    for field in ("file", "source"):
        if not isinstance(profile.get(field), str) or not profile[field].strip():
            raise ModeDecisionError(f"mode decision profile has no {field}")
    if profile.get("project_root") is not None and not isinstance(
        profile.get("project_root"),
        str,
    ):
        raise ModeDecisionError("mode decision profile project_root must be a string or null")
    facts = payload.get("facts")
    if not isinstance(facts, dict):
        raise ModeDecisionError("mode decision has no facts object")
    rules = payload.get("triggered_rules")
    if not isinstance(rules, list):
        raise ModeDecisionError("mode decision has no triggered_rules array")
    warnings = payload.get("warnings")
    if not isinstance(warnings, list):
        raise ModeDecisionError("mode decision has no warnings array")
    stored_fingerprint = payload.get("fingerprint")
    if not isinstance(stored_fingerprint, str) or stored_fingerprint != fingerprint(payload):
        raise ModeDecisionError("mode decision fingerprint mismatch")
    if expected_mode is not None and payload["selected_mode"] != expected_mode:
        raise ModeDecisionError(
            f"mode decision selects {payload['selected_mode']!r}, case uses {expected_mode!r}"
        )
    if expected_profile_id is not None and profile["id"] != expected_profile_id:
        raise ModeDecisionError(
            f"mode decision profile {profile['id']!r}, case uses {expected_profile_id!r}"
        )

    legacy_decision = "selected_assurance" not in payload
    risk_facts: dict[str, Any] | None = None
    if not legacy_decision:
        if payload.get("selected_assurance") not in ASSURANCE_LEVELS:
            raise ModeDecisionError("invalid selected_assurance")
        if payload.get("recommended_assurance") not in ASSURANCE_LEVELS:
            raise ModeDecisionError("invalid recommended_assurance")
        if payload.get("selected_tracking") not in TRACKING_POLICIES:
            raise ModeDecisionError("invalid selected_tracking")
        if payload.get("selected_projection_sync") not in PROJECTION_SYNC_POLICIES:
            raise ModeDecisionError("invalid selected_projection_sync")
        candidate_risk_facts = payload.get("risk_facts")
        if (
            not isinstance(candidate_risk_facts, dict)
            or candidate_risk_facts.get("change_scope") not in CHANGE_SCOPES
        ):
            raise ModeDecisionError("invalid risk_facts")
        risk_facts = candidate_risk_facts
        for field in (
            "public_contract",
            "data_migration",
            "security_or_permissions",
            "cross_service",
            "irreversible",
            "compliance",
        ):
            if not isinstance(risk_facts.get(field), bool):
                raise ModeDecisionError(f"risk_facts.{field} must be boolean")

    required_fact_types = {
        "estimated_blocks": int,
        "surfaces": list,
        "components": list,
        "owners": list,
        "dependent_parts": bool,
        "unsafe_single_pass": bool,
        "project_triggers": list,
    }
    for field, expected_type in required_fact_types.items():
        value = facts.get(field)
        if not isinstance(value, expected_type) or (
            expected_type is int and isinstance(value, bool)
        ):
            raise ModeDecisionError(f"mode decision fact {field!r} has invalid type")

    if legacy_decision:
        rebuilt_legacy = build_mode_decision(
            task=payload.get("task", ""),
            profile_id=profile["id"],
            profile_file=profile["file"],
            profile_source=profile["source"],
            project_root=profile.get("project_root"),
            estimated_blocks=facts["estimated_blocks"],
            surfaces=facts["surfaces"],
            components=facts["components"],
            owners=facts["owners"],
            dependent_parts=facts["dependent_parts"],
            unsafe_single_pass=facts["unsafe_single_pass"],
            project_triggers=facts["project_triggers"],
            requested_mode=payload["requested_mode"],
        )
        for field in (
            "risk_facts",
            "triggered_assurance_rules",
            "recommended_assurance",
            "requested_assurance",
            "selected_assurance",
            "assurance_selection_source",
            "recommended_tracking",
            "requested_tracking",
            "selected_tracking",
            "recommended_projection_sync",
            "requested_projection_sync",
            "selected_projection_sync",
        ):
            rebuilt_legacy.pop(field)
        rebuilt_legacy["fingerprint"] = fingerprint(rebuilt_legacy)
        if payload != rebuilt_legacy:
            raise ModeDecisionError("legacy mode decision does not match deterministic rules")
        return

    assert risk_facts is not None

    rebuilt = build_mode_decision(
        task=payload.get("task", ""),
        profile_id=profile["id"],
        profile_file=profile["file"],
        profile_source=profile["source"],
        project_root=profile.get("project_root"),
        estimated_blocks=facts["estimated_blocks"],
        surfaces=facts["surfaces"],
        components=facts["components"],
        owners=facts["owners"],
        dependent_parts=facts["dependent_parts"],
        unsafe_single_pass=facts["unsafe_single_pass"],
        project_triggers=facts["project_triggers"],
        requested_mode=payload["requested_mode"],
        change_scope=risk_facts["change_scope"],
        public_contract=risk_facts.get("public_contract", False),
        data_migration=risk_facts.get("data_migration", False),
        security_or_permissions=risk_facts.get("security_or_permissions", False),
        cross_service=risk_facts.get("cross_service", False),
        irreversible=risk_facts.get("irreversible", False),
        compliance=risk_facts.get("compliance", False),
        requested_assurance=payload.get("requested_assurance"),
        requested_tracking=payload.get("requested_tracking"),
        requested_projection_sync=payload.get("requested_projection_sync"),
    )
    if payload != rebuilt:
        raise ModeDecisionError("mode decision does not match deterministic rules")
