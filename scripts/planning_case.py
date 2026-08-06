#!/usr/bin/env python3
"""Deterministic research-and-planning state for Vigers preflight cases."""

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

from spec_pipeline import PipelineError, detect_profile, select_profile


SCHEMA_VERSION = 1
HANDOFF_SCHEMA_VERSION = 1
TODO_MARKER = "VIGERS_TODO"
MANIFEST_FILENAME = "planning-manifest.json"
HANDOFF_JSON = "planning-handoff.json"
HANDOFF_MARKDOWN = "planning-handoff.md"

CASE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
SOURCE_ID_RE = re.compile(r"^SRC-[0-9]{3,4}$")
TARGET_ID_RE = re.compile(r"^EXT-[0-9]{3,4}$")
STAGE_ID_RE = re.compile(r"^P[0-9]{2,3}$")
CHECK_ID_RE = re.compile(r"^P[0-9]{2,3}-C[0-9]{2,3}$")
PUBLISH_GATES = {"before_research", "before_review", "after_approval", "none"}

STATES = {
    "intake",
    "researching",
    "researched",
    "artifacts_planned",
    "published_for_review",
    "changes_requested",
    "approved",
    "handed_to_vigers",
    "blocked",
}
ALLOWED_TRANSITIONS = {
    "intake": {"researching", "blocked"},
    "researching": {"researched", "blocked"},
    "researched": {"researching", "artifacts_planned", "blocked"},
    "artifacts_planned": {"researching", "published_for_review", "blocked"},
    "published_for_review": {"changes_requested", "approved", "blocked"},
    "changes_requested": {"researching", "blocked"},
    "approved": {"handed_to_vigers", "blocked"},
    "handed_to_vigers": set(),
    "blocked": {"researching"},
}

MARKDOWN_ARTIFACTS = (
    "intake",
    "research",
    "plan_markdown",
    "handoff",
)
JSON_ARTIFACTS = (
    "source_map",
    "artifact_plan",
    "plan_graph",
    "bindings",
)
SNAPSHOT_ARTIFACTS = (*MARKDOWN_ARTIFACTS, *JSON_ARTIFACTS)


class PlanningError(RuntimeError):
    """Invalid planning state, artifact, or transition."""


def now_utc() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_fingerprint(payload: dict[str, Any]) -> str:
    material = dict(payload)
    material.pop("fingerprint", None)
    encoded = json.dumps(
        material,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def canonical_project_root(value: Any) -> str | None:
    """Normalize an optional project root for cross-package comparisons."""
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise PlanningError("project_root must be a non-empty path or null")
    return str(Path(value).expanduser().resolve())


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PlanningError(f"Cannot read JSON {path}: {exc}") from exc


def case_file(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise PlanningError(f"Planning path escapes root: {relative}") from exc
    return candidate


def write_template(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(text, encoding="utf-8")


def artifact_ready(path: Path) -> bool:
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8")
    return bool(text.strip()) and TODO_MARKER not in text


def event(kind: str, **details: Any) -> dict[str, Any]:
    return {"at": now_utc(), "kind": kind, **details}


def init_case(
    root: Path,
    *,
    case_id: str,
    profile_id: str,
    project_root: str | None,
    passport_id: str | None,
    passport_path: str | None,
    required_anchor_systems: list[str] | None = None,
) -> None:
    if not CASE_ID_RE.fullmatch(case_id):
        raise PlanningError(f"Invalid planning case id: {case_id!r}")
    root = root.expanduser().resolve()
    manifest_path = root / MANIFEST_FILENAME
    if manifest_path.exists():
        raise PlanningError(f"Planning case already exists: {manifest_path}")
    if root.exists() and any(root.iterdir()):
        raise PlanningError(f"Refusing to initialize a non-empty directory: {root}")

    (root / "reviews").mkdir(parents=True, exist_ok=True)
    (root / "revisions").mkdir(parents=True, exist_ok=True)
    write_template(root / "intake.md", "# Intake\n\nVIGERS_TODO\n")
    write_template(
        root / "research.md",
        "# Research report\n\n"
        "## Goal and search scope\n\nVIGERS_TODO\n\n"
        "## Confirmed facts\n\nVIGERS_TODO\n\n"
        "## Contradictions and gaps\n\nVIGERS_TODO\n\n"
        "## Planning implications\n\nVIGERS_TODO\n",
    )
    write_template(root / "plan.md", "# Approved-work plan\n\nVIGERS_TODO\n")
    write_template(
        root / "handoff.md",
        "# Planning handoff\n\n"
        "## Goal, scope, and non-goals\n\nVIGERS_TODO\n\n"
        "## Research basis and gaps\n\nVIGERS_TODO\n\n"
        "## Approved stages and dependencies\n\nVIGERS_TODO\n\n"
        "## Passport and external bindings\n\nVIGERS_TODO\n\n"
        "## Open risks and decisions\n\nVIGERS_TODO\n",
    )

    atomic_json(
        root / "source-map.json",
        {
            "schema": SCHEMA_VERSION,
            "coverage_verdict": "VIGERS_TODO",
            "queries": [],
            "sources": [],
            "gaps": [],
        },
    )
    anchor_systems = required_anchor_systems or []
    normalized_anchor_systems: list[str] = []
    for system in anchor_systems:
        normalized = system.strip()
        if not normalized:
            raise PlanningError("Accounting anchor system must be non-empty")
        if normalized.casefold() in {item.casefold() for item in normalized_anchor_systems}:
            raise PlanningError(f"Duplicate accounting anchor system: {normalized}")
        normalized_anchor_systems.append(normalized)
    anchor_targets = [
        {
            "id": f"EXT-{index:03d}",
            "system": system,
            "action": "create",
            "purpose": "Project-required accounting anchor",
            "authority": "profile",
            "publish_gate": "before_research",
            "read_back_required": True,
        }
        for index, system in enumerate(normalized_anchor_systems, start=1)
    ]
    atomic_json(
        root / "artifact-plan.json",
        {"schema": SCHEMA_VERSION, "targets": anchor_targets},
    )
    atomic_json(
        root / "plan.json",
        {"schema": SCHEMA_VERSION, "revision": 1, "stages": []},
    )
    atomic_json(
        root / "bindings.json",
        {
            "schema": SCHEMA_VERSION,
            "passport": {
                "id": passport_id or f"TEMP-{case_id}",
                "path": passport_path,
                "provenance_status": "partial",
            },
            "external": [],
        },
    )
    write_template(
        root / "reviews" / "revision-001.md",
        "# Planning review: revision 1\n\nVIGERS_TODO\n",
    )

    manifest = {
        "schema": SCHEMA_VERSION,
        "case_id": case_id,
        "profile_id": profile_id,
        "project_root": project_root,
        "required_anchor_systems": normalized_anchor_systems,
        "state": "intake",
        "revision": 1,
        "created_at": now_utc(),
        "updated_at": now_utc(),
        "artifacts": {
            "intake": "intake.md",
            "research": "research.md",
            "source_map": "source-map.json",
            "artifact_plan": "artifact-plan.json",
            "plan_graph": "plan.json",
            "plan_markdown": "plan.md",
            "bindings": "bindings.json",
            "handoff": "handoff.md",
        },
        "snapshots": {},
        "approval": None,
        "handoff": None,
        "events": [event("planning_case_initialized", revision=1)],
    }
    atomic_json(manifest_path, manifest)
    render_status(root, manifest)


def load_case(root: Path) -> tuple[Path, dict[str, Any]]:
    root = root.expanduser().resolve()
    manifest = read_json(root / MANIFEST_FILENAME)
    if manifest.get("schema") != SCHEMA_VERSION:
        raise PlanningError(f"Unsupported planning schema in {root}")
    if manifest.get("state") not in STATES:
        raise PlanningError(f"Unknown planning state: {manifest.get('state')!r}")
    return root, manifest


def save_case(root: Path, manifest: dict[str, Any]) -> None:
    manifest["updated_at"] = now_utc()
    atomic_json(root / MANIFEST_FILENAME, manifest)
    render_status(root, manifest)


def artifact_paths(root: Path, manifest: dict[str, Any]) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict):
        raise PlanningError("planning manifest artifacts must be an object")
    for name in SNAPSHOT_ARTIFACTS:
        relative = artifacts.get(name)
        if not isinstance(relative, str):
            raise PlanningError(f"Missing artifact path: {name}")
        paths[name] = case_file(root, relative)
    return paths


def validate_source_map(payload: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA_VERSION:
        return ["source-map.json has unsupported schema"]
    verdict = payload.get("coverage_verdict")
    if verdict not in {"sufficient", "partial", "blocked"}:
        errors.append("source-map coverage_verdict must be sufficient, partial, or blocked")
    sources = payload.get("sources")
    if not isinstance(sources, list) or not sources:
        errors.append("source-map must contain at least one source")
        sources = []
    seen: set[str] = set()
    for source in sources:
        if not isinstance(source, dict):
            errors.append("source-map entries must be objects")
            continue
        source_id = source.get("id")
        if not isinstance(source_id, str) or not SOURCE_ID_RE.fullmatch(source_id):
            errors.append(f"invalid source id: {source_id!r}")
        elif source_id in seen:
            errors.append(f"duplicate source id: {source_id}")
        else:
            seen.add(source_id)
        if source.get("status") not in {"confirmed", "partial", "unavailable"}:
            errors.append(f"{source_id}: invalid status")
        if source.get("authority") not in {"canonical", "evidence", "historical", "request"}:
            errors.append(f"{source_id}: invalid authority")
        for field in ("system", "ref", "checked_at"):
            if not isinstance(source.get(field), str) or not source[field].strip():
                errors.append(f"{source_id}: missing {field}")
    gaps = payload.get("gaps")
    if not isinstance(gaps, list):
        errors.append("source-map gaps must be an array")
    elif verdict in {"partial", "blocked"} and not gaps:
        errors.append(f"source-map verdict {verdict} requires explicit gaps")
    queries = payload.get("queries")
    if not isinstance(queries, list):
        errors.append("source-map queries must be an array")
    return errors


def validate_artifact_plan(payload: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA_VERSION:
        return ["artifact-plan.json has unsupported schema"]
    targets = payload.get("targets")
    if not isinstance(targets, list):
        return ["artifact-plan targets must be an array"]
    seen: set[str] = set()
    early_systems: dict[str, str] = {}
    for target in targets:
        if not isinstance(target, dict):
            errors.append("artifact-plan targets must be objects")
            continue
        target_id = target.get("id")
        if not isinstance(target_id, str) or not TARGET_ID_RE.fullmatch(target_id):
            errors.append(f"invalid external target id: {target_id!r}")
        elif target_id in seen:
            errors.append(f"duplicate external target id: {target_id}")
        else:
            seen.add(target_id)
        if target.get("action") not in {"create", "update", "link", "none"}:
            errors.append(f"{target_id}: invalid action")
        if target.get("authority") not in {"explicit", "profile", "none"}:
            errors.append(f"{target_id}: invalid authority")
        if target.get("action") != "none" and target.get("authority") == "none":
            errors.append(f"{target_id}: mutation requires explicit or profile authority")
        publish_gate = target.get("publish_gate")
        if publish_gate not in PUBLISH_GATES:
            errors.append(
                f"{target_id}: publish_gate must be before_research, before_review, "
                "after_approval, or none"
            )
        if target.get("action") == "none":
            if target.get("authority") != "none":
                errors.append(f"{target_id}: action none requires authority none")
            if publish_gate != "none":
                errors.append(f"{target_id}: action none requires publish_gate none")
        elif publish_gate == "none":
            errors.append(f"{target_id}: actionable target requires a publish gate")
        if publish_gate == "before_research":
            if target.get("authority") != "profile":
                errors.append(f"{target_id}: early anchor requires profile authority")
            if target.get("action") not in {"create", "link"}:
                errors.append(f"{target_id}: early anchor action must be create or link")
            if target.get("read_back_required") is not True:
                errors.append(f"{target_id}: early anchor requires read-back")
            system = target.get("system")
            if isinstance(system, str) and system.strip():
                normalized_system = system.strip().casefold()
                previous = early_systems.get(normalized_system)
                if previous is not None:
                    errors.append(
                        f"{target_id}: duplicate early anchor system already used by {previous}"
                    )
                else:
                    early_systems[normalized_system] = target_id
        for field in ("system", "purpose"):
            if not isinstance(target.get(field), str) or not target[field].strip():
                errors.append(f"{target_id}: missing {field}")
        if not isinstance(target.get("read_back_required"), bool):
            errors.append(f"{target_id}: read_back_required must be boolean")
    return errors


def ensure_acyclic(stages: list[dict[str, Any]]) -> None:
    by_id = {stage["id"]: stage for stage in stages}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(stage_id: str) -> None:
        if stage_id in visited:
            return
        if stage_id in visiting:
            raise PlanningError(f"Plan dependency cycle at {stage_id}")
        visiting.add(stage_id)
        for dependency in by_id[stage_id].get("depends_on", []):
            visit(dependency)
        visiting.remove(stage_id)
        visited.add(stage_id)

    for identifier in by_id:
        visit(identifier)


def validate_plan(payload: Any, revision: int, source_ids: set[str]) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA_VERSION:
        return ["plan.json has unsupported schema"]
    if payload.get("revision") != revision:
        errors.append(f"plan revision must equal planning revision {revision}")
    stages = payload.get("stages")
    if not isinstance(stages, list) or not stages:
        return [*errors, "plan must contain at least one stage"]
    stage_ids: set[str] = set()
    checklist_ids: set[str] = set()
    for stage in stages:
        if not isinstance(stage, dict):
            errors.append("plan stages must be objects")
            continue
        stage_id = stage.get("id")
        if not isinstance(stage_id, str) or not STAGE_ID_RE.fullmatch(stage_id):
            errors.append(f"invalid stage id: {stage_id!r}")
            continue
        if stage_id in stage_ids:
            errors.append(f"duplicate stage id: {stage_id}")
        stage_ids.add(stage_id)
        for field in ("title", "outcome"):
            if not isinstance(stage.get(field), str) or not stage[field].strip():
                errors.append(f"{stage_id}: missing {field}")
        if not isinstance(stage.get("exit_criteria"), list) or not stage["exit_criteria"]:
            errors.append(f"{stage_id}: exit_criteria must be non-empty")
        depends_on = stage.get("depends_on")
        if not isinstance(depends_on, list):
            errors.append(f"{stage_id}: depends_on must be an array")
        source_refs = stage.get("source_refs", [])
        if not isinstance(source_refs, list):
            errors.append(f"{stage_id}: source_refs must be an array")
        else:
            unknown_sources = sorted(set(source_refs) - source_ids)
            if unknown_sources:
                errors.append(f"{stage_id}: unknown source refs: {', '.join(unknown_sources)}")
        checklist = stage.get("checklist")
        if not isinstance(checklist, list) or not checklist:
            errors.append(f"{stage_id}: checklist must be non-empty")
            continue
        for item in checklist:
            if not isinstance(item, dict):
                errors.append(f"{stage_id}: checklist items must be objects")
                continue
            item_id = item.get("id")
            if not isinstance(item_id, str) or not CHECK_ID_RE.fullmatch(item_id):
                errors.append(f"{stage_id}: invalid checklist id {item_id!r}")
            elif not item_id.startswith(f"{stage_id}-"):
                errors.append(f"{item_id}: checklist id does not belong to {stage_id}")
            elif item_id in checklist_ids:
                errors.append(f"duplicate checklist id: {item_id}")
            else:
                checklist_ids.add(item_id)
            if not isinstance(item.get("text"), str) or not item["text"].strip():
                errors.append(f"{item_id}: missing text")
            for optional_text in ("details", "done_when"):
                value = item.get(optional_text)
                if value is not None and (not isinstance(value, str) or not value.strip()):
                    errors.append(f"{item_id}: {optional_text} must be non-empty text")
            links = item.get("links", [])
            if not isinstance(links, list) or any(
                not isinstance(link, str) or not link.strip() for link in links
            ):
                errors.append(f"{item_id}: links must be an array of non-empty strings")
            item_sources = item.get("source_refs", [])
            if not isinstance(item_sources, list):
                errors.append(f"{item_id}: source_refs must be an array")
            else:
                unknown_item_sources = sorted(set(item_sources) - source_ids)
                if unknown_item_sources:
                    errors.append(
                        f"{item_id}: unknown source refs: {', '.join(unknown_item_sources)}"
                    )
    if not errors:
        by_id = {stage["id"]: stage for stage in stages}
        for stage in stages:
            for dependency in stage.get("depends_on", []):
                if dependency not in by_id:
                    errors.append(f"{stage['id']}: unknown dependency {dependency}")
        if not errors:
            try:
                ensure_acyclic(stages)
            except PlanningError as exc:
                errors.append(str(exc))
    return errors


def validate_bindings(
    payload: Any,
    artifact_plan: dict[str, Any],
    *,
    required_publish_gates: set[str],
) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA_VERSION:
        return ["bindings.json has unsupported schema"]
    passport = payload.get("passport")
    if not isinstance(passport, dict) or not isinstance(passport.get("id"), str):
        errors.append("bindings passport requires a stable or temporary id")
    elif passport.get("provenance_status") not in {"partial", "confirmed"}:
        errors.append("bindings passport provenance_status must be partial or confirmed")
    external = payload.get("external")
    if not isinstance(external, list):
        return [*errors, "bindings external must be an array"]
    by_target: dict[str, dict[str, Any]] = {}
    for binding in external:
        if not isinstance(binding, dict):
            errors.append("external bindings must be objects")
            continue
        target_id = binding.get("target_id")
        if target_id in by_target:
            errors.append(f"duplicate binding for {target_id}")
        elif isinstance(target_id, str):
            by_target[target_id] = binding
        for field in ("target_id", "system", "object_id", "read_back_at"):
            if not isinstance(binding.get(field), str) or not binding[field].strip():
                errors.append(f"binding {target_id}: missing {field}")
    targets = {
        target["id"]: target
        for target in artifact_plan.get("targets", [])
        if isinstance(target, dict) and isinstance(target.get("id"), str)
    }
    unknown = sorted(set(by_target) - set(targets))
    if unknown:
        errors.append(f"bindings reference unknown targets: {', '.join(unknown)}")
    for target_id, binding in by_target.items():
        target = targets.get(target_id)
        if target is not None and target.get("action") == "none":
            errors.append(f"{target_id}: non-actionable target cannot have a binding")
    for target_id, target in targets.items():
        if target.get("action") == "none":
            continue
        if target.get("publish_gate") not in required_publish_gates:
            continue
        binding = by_target.get(target_id)
        if binding is None:
            errors.append(f"{target_id}: required external artifact has no read-back binding")
        elif target.get("read_back_required") and not binding.get("read_back_at"):
            errors.append(f"{target_id}: required read-back is missing")
    return errors


def validate_approved_artifacts(
    root: Path,
    manifest: dict[str, Any],
    *,
    require_after_approval: bool,
) -> list[str]:
    """Allow only declared post-approval bindings to differ from the reviewed snapshot."""
    snapshot = manifest.get("snapshots", {}).get(str(manifest["revision"]))
    if not isinstance(snapshot, dict):
        return ["approved planning case has no immutable snapshot"]

    paths = artifact_paths(root, manifest)
    immutable_names = set(paths) - {"bindings"}
    if any(snapshot.get(name) != sha256(paths[name]) for name in immutable_names):
        return ["approved artifacts changed after snapshot"]

    snapshot_bindings_path = (
        root
        / "revisions"
        / f"revision-{manifest['revision']:03d}"
        / paths["bindings"].name
    )
    snapshot_bindings = read_json(snapshot_bindings_path)
    current_bindings = read_json(paths["bindings"])
    artifact_plan = read_json(paths["artifact_plan"])
    required_gates = {"before_research", "before_review"}
    if require_after_approval:
        required_gates.add("after_approval")
    errors = validate_bindings(
        current_bindings,
        artifact_plan,
        required_publish_gates=required_gates,
    )

    target_gates = {
        target.get("id"): target.get("publish_gate")
        for target in artifact_plan.get("targets", [])
        if isinstance(target, dict)
    }

    def reviewed_part(payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema": payload.get("schema"),
            "passport": payload.get("passport"),
            "external": [
                binding
                for binding in payload.get("external", [])
                if target_gates.get(binding.get("target_id")) != "after_approval"
            ],
        }

    if reviewed_part(current_bindings) != reviewed_part(snapshot_bindings):
        errors.append("approved pre-review bindings changed after snapshot")
    return errors


def validate_required_anchors(
    manifest: dict[str, Any],
    artifact_plan: dict[str, Any],
) -> list[str]:
    """Keep profile-required early anchors immutable in machine state."""
    errors: list[str] = []
    required = manifest.get("required_anchor_systems")
    if not isinstance(required, list) or any(
        not isinstance(system, str) or not system.strip() for system in required
    ):
        return ["planning manifest required_anchor_systems must be an array of names"]
    required_by_name: dict[str, str] = {}
    for system in required:
        normalized = system.strip().casefold()
        if normalized in required_by_name:
            errors.append(f"duplicate required anchor system: {system}")
        else:
            required_by_name[normalized] = system.strip()

    early_targets: dict[str, list[dict[str, Any]]] = {}
    for target in artifact_plan.get("targets", []):
        if not isinstance(target, dict) or target.get("publish_gate") != "before_research":
            continue
        system = target.get("system")
        if not isinstance(system, str) or not system.strip():
            continue
        early_targets.setdefault(system.strip().casefold(), []).append(target)

    for normalized, display_name in required_by_name.items():
        matches = early_targets.get(normalized, [])
        if len(matches) != 1:
            errors.append(
                f"required anchor {display_name} must have exactly one before_research target"
            )
    for normalized, targets in early_targets.items():
        if normalized not in required_by_name:
            errors.append(
                f"undeclared before_research anchor system: {targets[0].get('system')}"
            )
    return errors


def validate_artifacts(root: Path, manifest: dict[str, Any], *, for_review: bool) -> list[str]:
    errors: list[str] = []
    paths = artifact_paths(root, manifest)
    for name in MARKDOWN_ARTIFACTS:
        if name == "handoff" and not for_review:
            continue
        if not artifact_ready(paths[name]):
            errors.append(f"{paths[name].name} is missing or still a placeholder")
    source_map = read_json(paths["source_map"])
    artifact_plan = read_json(paths["artifact_plan"])
    plan_graph = read_json(paths["plan_graph"])
    bindings = read_json(paths["bindings"])
    errors.extend(validate_source_map(source_map))
    errors.extend(validate_artifact_plan(artifact_plan))
    errors.extend(validate_required_anchors(manifest, artifact_plan))
    source_ids = {
        source.get("id")
        for source in source_map.get("sources", [])
        if isinstance(source, dict) and isinstance(source.get("id"), str)
    }
    errors.extend(validate_plan(plan_graph, manifest["revision"], source_ids))
    errors.extend(
        validate_bindings(
            bindings,
            artifact_plan,
            required_publish_gates=(
                {"before_research", "before_review"}
                if for_review
                else {"before_research"}
            ),
        )
    )
    return errors


def snapshot_revision(root: Path, manifest: dict[str, Any]) -> dict[str, str]:
    revision = manifest["revision"]
    revision_key = str(revision)
    existing = manifest.get("snapshots", {}).get(revision_key)
    if isinstance(existing, dict):
        return existing
    destination = root / "revisions" / f"revision-{revision:03d}"
    destination.mkdir(parents=True, exist_ok=False)
    snapshot: dict[str, str] = {}
    for name, source in artifact_paths(root, manifest).items():
        target = destination / source.name
        shutil.copy2(source, target)
        snapshot[name] = sha256(target)
    manifest.setdefault("snapshots", {})[revision_key] = snapshot
    manifest["events"].append(event("revision_snapshotted", revision=revision))
    return snapshot


def transition(
    root: Path,
    manifest: dict[str, Any],
    *,
    new_state: str,
    note: str | None,
    via_review: bool = False,
    via_export: bool = False,
) -> None:
    old_state = manifest["state"]
    if new_state not in ALLOWED_TRANSITIONS[old_state]:
        raise PlanningError(f"Invalid planning transition {old_state} -> {new_state}")
    if new_state in {"changes_requested", "approved"} and not via_review:
        raise PlanningError(f"State {new_state} can be entered only through review")
    if new_state == "approved" and not isinstance(manifest.get("approval"), dict):
        raise PlanningError("Approved state requires an approval record")
    if new_state == "handed_to_vigers" and not via_export:
        raise PlanningError("State handed_to_vigers can be entered only through export")
    if new_state == "handed_to_vigers" and not isinstance(manifest.get("handoff"), dict):
        raise PlanningError("State handed_to_vigers requires an exported handoff record")
    paths = artifact_paths(root, manifest)
    if new_state == "researching" and not artifact_ready(paths["intake"]):
        raise PlanningError("intake.md must be complete before research starts")
    if new_state == "researching":
        artifact_plan = read_json(paths["artifact_plan"])
        bindings = read_json(paths["bindings"])
        errors = validate_artifact_plan(artifact_plan)
        errors.extend(validate_required_anchors(manifest, artifact_plan))
        errors.extend(
            validate_bindings(
                bindings,
                artifact_plan,
                required_publish_gates={"before_research"},
            )
        )
        if errors:
            raise PlanningError("Project-required anchors are incomplete: " + "; ".join(errors))
    if new_state == "researched":
        if not artifact_ready(paths["research"]):
            raise PlanningError("research.md must be complete")
        errors = validate_source_map(read_json(paths["source_map"]))
        if errors:
            raise PlanningError("Invalid research basis: " + "; ".join(errors))
        if read_json(paths["source_map"])["coverage_verdict"] == "blocked":
            raise PlanningError("Blocked source coverage cannot transition to researched")
    if new_state == "artifacts_planned":
        errors = validate_artifacts(root, manifest, for_review=False)
        if errors:
            raise PlanningError("Invalid planning artifacts: " + "; ".join(errors))
    if new_state == "published_for_review":
        errors = validate_artifacts(root, manifest, for_review=True)
        if errors:
            raise PlanningError("Planning case is not publishable: " + "; ".join(errors))
        snapshot_revision(root, manifest)
    if new_state in {"blocked", "changes_requested"} and not note:
        raise PlanningError(f"{new_state} requires a note")
    if new_state == "researching" and str(manifest["revision"]) in manifest.get(
        "snapshots", {}
    ):
        manifest["revision"] += 1
        manifest["approval"] = None
        manifest["handoff"] = None
        write_template(
            root / "reviews" / f"revision-{manifest['revision']:03d}.md",
            f"# Planning review: revision {manifest['revision']}\n\n{TODO_MARKER}\n",
        )
    manifest["state"] = new_state
    manifest["events"].append(
        event(
            "planning_transition",
            old_state=old_state,
            new_state=new_state,
            revision=manifest["revision"],
            note=note,
        )
    )
    save_case(root, manifest)


def record_binding(
    root: Path,
    manifest: dict[str, Any],
    *,
    target_id: str,
    system: str,
    object_id: str,
    url: str | None,
    read_back_at: str,
    action: str | None = None,
    replace: bool = False,
) -> None:
    paths = artifact_paths(root, manifest)
    artifact_plan = read_json(paths["artifact_plan"])
    targets = {
        target.get("id"): target
        for target in artifact_plan.get("targets", [])
        if isinstance(target, dict)
    }
    target = targets.get(target_id)
    if target is None:
        raise PlanningError(f"Unknown external target: {target_id}")
    publish_gate = target.get("publish_gate")
    bindings = read_json(paths["bindings"])
    existing_binding = next(
        (
            item
            for item in bindings.get("external", [])
            if item.get("target_id") == target_id
        ),
        None,
    )
    allowed_states = (
        ({"intake", "blocked", "researching"} if replace else {"intake", "blocked"})
        if publish_gate == "before_research"
        else {"researched", "artifacts_planned"}
        if publish_gate == "before_review"
        else {"approved"}
        if publish_gate == "after_approval"
        else set()
    )
    if manifest["state"] not in allowed_states:
        raise PlanningError(
            f"Binding {target_id} with gate {publish_gate!r} cannot be recorded "
            f"in state {manifest['state']}"
        )
    if target.get("system") != system:
        raise PlanningError(f"Target {target_id} belongs to {target.get('system')}, not {system}")
    if replace and existing_binding is None:
        raise PlanningError(f"Binding does not exist for replacement: {target_id}")
    if not replace and existing_binding is not None:
        raise PlanningError(f"Binding already exists for {target_id}")
    if replace and action is None:
        raise PlanningError("Replacing a binding requires an explicit --action")
    if action is not None:
        allowed_actions = (
            {"create", "link"}
            if publish_gate == "before_research"
            else {"create", "update", "link"}
        )
        if action not in allowed_actions:
            raise PlanningError(
                f"Action {action!r} is invalid for target {target_id} with gate {publish_gate}"
            )
        if manifest["state"] == "approved" and action != target.get("action"):
            raise PlanningError("Approved external target action cannot be changed")
        if action != target.get("action"):
            target["action"] = action
            errors = validate_artifact_plan(artifact_plan)
            errors.extend(validate_required_anchors(manifest, artifact_plan))
            if errors:
                raise PlanningError("Invalid external target action: " + "; ".join(errors))
            atomic_json(paths["artifact_plan"], artifact_plan)
            manifest["events"].append(
                event("external_target_action_resolved", target_id=target_id, action=action)
            )
    binding = {
        "target_id": target_id,
        "system": system,
        "object_id": object_id,
        "url": url,
        "read_back_at": read_back_at,
    }
    if replace:
        bindings["external"] = [
            binding if item.get("target_id") == target_id else item
            for item in bindings["external"]
        ]
    else:
        bindings["external"].append(binding)
    atomic_json(paths["bindings"], bindings)
    manifest["events"].append(
        event(
            "external_binding_replaced" if replace else "external_binding_recorded",
            target_id=target_id,
            system=system,
        )
    )
    save_case(root, manifest)


def record_review(
    root: Path,
    manifest: dict[str, Any],
    *,
    verdict: str,
    actor: str,
    note: str,
) -> None:
    if manifest["state"] != "published_for_review":
        raise PlanningError("Review can be recorded only from published_for_review")
    if verdict not in {"changes_requested", "approved"}:
        raise PlanningError(f"Invalid review verdict: {verdict}")
    if not actor.strip() or not note.strip():
        raise PlanningError("Review actor and note are required")
    review_path = root / "reviews" / f"revision-{manifest['revision']:03d}.md"
    existing = review_path.read_text(encoding="utf-8") if review_path.exists() else ""
    if TODO_MARKER not in existing and existing.strip():
        raise PlanningError(f"Review artifact already recorded: {review_path}")
    recorded_at = now_utc()
    approval: dict[str, Any] | None = None
    if verdict == "approved":
        errors = validate_artifacts(root, manifest, for_review=True)
        if errors:
            raise PlanningError("Planning case cannot be approved: " + "; ".join(errors))
        snapshot = manifest.get("snapshots", {}).get(str(manifest["revision"]))
        if not isinstance(snapshot, dict):
            raise PlanningError("Published revision has no immutable snapshot")
        current_hashes = {
            name: sha256(path)
            for name, path in artifact_paths(root, manifest).items()
        }
        if current_hashes != snapshot:
            raise PlanningError("Published planning artifacts changed after snapshot")
        subject = hashlib.sha256(
            json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        approval = {
            "revision": manifest["revision"],
            "actor": actor,
            "at": recorded_at,
            "note": note.strip(),
            "subject_sha256": subject,
        }
    review_text = (
        f"# Planning review: revision {manifest['revision']}\n\n"
        f"- verdict: `{verdict}`\n"
        f"- actor: `{actor}`\n"
        f"- recorded_at: `{recorded_at}`\n\n"
        f"## Comment\n\n{note.strip()}\n"
    )
    atomic_text(review_path, review_text)
    if approval is not None:
        manifest["approval"] = approval
    transition(root, manifest, new_state=verdict, note=note.strip(), via_review=True)


def build_handoff(root: Path, manifest: dict[str, Any]) -> tuple[dict[str, Any], str]:
    if manifest["state"] != "approved":
        raise PlanningError("Only an approved planning case can be handed to Vigers")
    errors = validate_artifacts(root, manifest, for_review=True)
    if errors:
        raise PlanningError("Approved planning artifacts are invalid: " + "; ".join(errors))
    errors = validate_approved_artifacts(
        root,
        manifest,
        require_after_approval=True,
    )
    if errors:
        raise PlanningError("Approved planning artifacts are invalid: " + "; ".join(errors))
    paths = artifact_paths(root, manifest)
    snapshot = manifest.get("snapshots", {}).get(str(manifest["revision"]))
    if not isinstance(snapshot, dict):
        raise PlanningError("Approved revision has no immutable snapshot")
    markdown = paths["handoff"].read_text(encoding="utf-8")
    bindings = read_json(paths["bindings"])
    payload: dict[str, Any] = {
        "schema": HANDOFF_SCHEMA_VERSION,
        "planning_case_id": manifest["case_id"],
        "planning_revision": manifest["revision"],
        "profile_id": manifest["profile_id"],
        "project_root": canonical_project_root(manifest.get("project_root")),
        "required_anchor_systems": manifest.get("required_anchor_systems", []),
        "passport": bindings["passport"],
        "external_bindings": bindings["external"],
        "approval": manifest["approval"],
        "artifact_hashes": snapshot,
        "content_sha256": hashlib.sha256(markdown.encode("utf-8")).hexdigest(),
    }
    payload["fingerprint"] = canonical_fingerprint(payload)
    return payload, markdown


def validate_handoff(
    payload: Any,
    markdown: str,
    *,
    expected_profile_id: str | None = None,
    expected_project_root: str | None = None,
    enforce_project_root: bool = False,
) -> None:
    if not isinstance(payload, dict) or payload.get("schema") != HANDOFF_SCHEMA_VERSION:
        raise PlanningError("planning handoff has unsupported schema")
    if expected_profile_id is not None and payload.get("profile_id") != expected_profile_id:
        raise PlanningError(
            f"planning handoff profile mismatch: {payload.get('profile_id')} != {expected_profile_id}"
        )
    if "project_root" not in payload:
        raise PlanningError("planning handoff project root is missing")
    project_root = canonical_project_root(payload.get("project_root"))
    if enforce_project_root and project_root != canonical_project_root(expected_project_root):
        raise PlanningError(
            "planning handoff project root mismatch: "
            f"{project_root} != {canonical_project_root(expected_project_root)}"
        )
    if payload.get("fingerprint") != canonical_fingerprint(payload):
        raise PlanningError("planning handoff fingerprint mismatch")
    if payload.get("content_sha256") != hashlib.sha256(markdown.encode("utf-8")).hexdigest():
        raise PlanningError("planning handoff content hash mismatch")
    approval = payload.get("approval")
    if not isinstance(approval, dict) or approval.get("revision") != payload.get("planning_revision"):
        raise PlanningError("planning handoff approval is missing or stale")
    required_anchors = payload.get("required_anchor_systems")
    if not isinstance(required_anchors, list) or any(
        not isinstance(system, str) or not system.strip() for system in required_anchors
    ):
        raise PlanningError("planning handoff required anchors are invalid")
    external_bindings = payload.get("external_bindings")
    if not isinstance(external_bindings, list):
        raise PlanningError("planning handoff external bindings are invalid")
    bound_systems = {
        binding.get("system").casefold()
        for binding in external_bindings
        if isinstance(binding, dict)
        and isinstance(binding.get("system"), str)
        and binding.get("system").strip()
        and isinstance(binding.get("read_back_at"), str)
        and binding.get("read_back_at").strip()
    }
    missing_anchors = [
        system for system in required_anchors if system.casefold() not in bound_systems
    ]
    if missing_anchors:
        raise PlanningError(
            "planning handoff required anchors have no read-back binding: "
            + ", ".join(missing_anchors)
        )
    if not artifact_ready_text(markdown):
        raise PlanningError("planning handoff markdown is empty or incomplete")


def artifact_ready_text(text: str) -> bool:
    return bool(text.strip()) and TODO_MARKER not in text


def export_handoff(root: Path, manifest: dict[str, Any], output_root: Path) -> None:
    payload, markdown = build_handoff(root, manifest)
    output_root = output_root.expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    json_path = output_root / HANDOFF_JSON
    markdown_path = output_root / HANDOFF_MARKDOWN
    if json_path.exists() or markdown_path.exists():
        raise PlanningError(f"Refusing to overwrite an existing planning handoff in {output_root}")
    validate_handoff(payload, markdown)
    atomic_text(markdown_path, markdown)
    atomic_json(json_path, payload)
    validate_handoff(read_json(json_path), markdown_path.read_text(encoding="utf-8"))
    manifest["handoff"] = {
        "fingerprint": payload["fingerprint"],
        "exported_at": now_utc(),
        "bindings_sha256": sha256(artifact_paths(root, manifest)["bindings"]),
    }
    transition(
        root,
        manifest,
        new_state="handed_to_vigers",
        note="approved snapshot exported",
        via_export=True,
    )


def validate_case(root: Path, manifest: dict[str, Any], *, final: bool) -> list[str]:
    errors: list[str] = []
    try:
        paths = artifact_paths(root, manifest)
    except PlanningError as exc:
        return [str(exc)]
    for path in paths.values():
        if not path.is_file():
            errors.append(f"missing artifact: {path.name}")
    if errors:
        return errors
    state = manifest["state"]
    if state not in {"artifacts_planned", "published_for_review", "approved", "handed_to_vigers"}:
        artifact_plan = read_json(paths["artifact_plan"])
        errors.extend(validate_artifact_plan(artifact_plan))
        errors.extend(validate_required_anchors(manifest, artifact_plan))
    if state in {"researched", "artifacts_planned", "published_for_review", "approved", "handed_to_vigers"}:
        errors.extend(validate_source_map(read_json(paths["source_map"])))
    if state in {"artifacts_planned", "published_for_review", "approved", "handed_to_vigers"}:
        errors.extend(validate_artifacts(root, manifest, for_review=state != "artifacts_planned"))
    if state in {"published_for_review", "changes_requested", "approved", "handed_to_vigers"}:
        snapshot = manifest.get("snapshots", {}).get(str(manifest["revision"]))
        if not isinstance(snapshot, dict):
            errors.append("current reviewed revision has no snapshot")
        elif state in {"approved", "handed_to_vigers"}:
            errors.extend(
                validate_approved_artifacts(
                    root,
                    manifest,
                    require_after_approval=state == "handed_to_vigers",
                )
            )
    if state in {"approved", "handed_to_vigers"} and not isinstance(manifest.get("approval"), dict):
        errors.append("approved planning case has no approval record")
    if state == "handed_to_vigers":
        handoff = manifest.get("handoff")
        if not isinstance(handoff, dict):
            errors.append("handed planning case has no exported handoff record")
        elif any(
            not isinstance(handoff.get(field), str) or not handoff[field].strip()
            for field in ("fingerprint", "exported_at", "bindings_sha256")
        ):
            errors.append("exported handoff record is incomplete")
        elif handoff["bindings_sha256"] != sha256(paths["bindings"]):
            errors.append("external bindings changed after handoff export")
    if final and state != "handed_to_vigers":
        errors.append(f"final planning state must be handed_to_vigers, got {state}")
    return errors


def context_bundle(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "planning_case_id": manifest["case_id"],
        "revision": manifest["revision"],
        "state": manifest["state"],
        "required_anchor_systems": manifest.get("required_anchor_systems", []),
        "role": "planner",
        "include": [
            MANIFEST_FILENAME,
            manifest["artifacts"]["intake"],
            manifest["artifacts"]["source_map"],
            manifest["artifacts"]["research"],
            manifest["artifacts"]["artifact_plan"],
            manifest["artifacts"]["plan_graph"],
            manifest["artifacts"]["plan_markdown"],
            manifest["artifacts"]["bindings"],
            "resolved project profile",
        ],
        "exclude": [
            "parent-chat history",
            "tracker credentials",
            "unbounded source dumps",
            "future Vigers case artifacts",
        ],
    }


def render_status(root: Path, manifest: dict[str, Any]) -> None:
    revision = manifest["revision"]
    lines = [
        f"# Planning case {manifest['case_id']}",
        "",
        f"- state: `{manifest['state']}`",
        f"- revision: `{revision}`",
        f"- profile: `{manifest['profile_id']}`",
        f"- approval: `{'recorded' if manifest.get('approval') else 'pending'}`",
        f"- updated: `{manifest['updated_at']}`",
        "",
        "## DoD",
        "",
        f"- [{'x' if manifest['state'] in {'researched', 'artifacts_planned', 'published_for_review', 'changes_requested', 'approved', 'handed_to_vigers'} else ' '}] source research completed",
        f"- [{'x' if manifest['state'] in {'artifacts_planned', 'published_for_review', 'approved', 'handed_to_vigers'} else ' '}] dependent stages and checklists planned",
        f"- [{'x' if manifest['state'] in {'published_for_review', 'approved', 'handed_to_vigers'} else ' '}] required external drafts created and read back",
        f"- [{'x' if manifest.get('approval') else ' '}] user review recorded",
        f"- [{'x' if manifest['state'] == 'handed_to_vigers' else ' '}] approved snapshot handed to Vigers",
        "",
        "Machine truth: `planning-manifest.json`; do not edit it manually.",
    ]
    (root / "status.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def resolve_init_profile(requested_id: str, cwd: Path):
    """Resolve the nearest profile without allowing an explicit generic bypass."""
    detected = detect_profile(cwd)
    if requested_id == "generic" and detected.profile_id != "generic":
        raise PlanningError("Explicit generic profile cannot override the nearest project profile")
    return detected if requested_id == "auto" else select_profile(requested_id, cwd)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Create a planning case")
    init_parser.add_argument("--case-root", required=True)
    init_parser.add_argument("--case-id", required=True)
    init_parser.add_argument("--cwd", default=".")
    init_parser.add_argument("--profile-id", default="auto")
    init_parser.add_argument("--project-root")
    init_parser.add_argument("--passport-id")
    init_parser.add_argument("--passport-path")

    transition_parser = subparsers.add_parser("transition", help="Move planning state")
    transition_parser.add_argument("--case-root", required=True)
    transition_parser.add_argument(
        "--state",
        choices=(
            "researching",
            "researched",
            "artifacts_planned",
            "published_for_review",
            "blocked",
        ),
        required=True,
    )
    transition_parser.add_argument("--note")

    bind_parser = subparsers.add_parser("bind", help="Record an external artifact read-back")
    bind_parser.add_argument("--case-root", required=True)
    bind_parser.add_argument("--target-id", required=True)
    bind_parser.add_argument("--system", required=True)
    bind_parser.add_argument("--object-id", required=True)
    bind_parser.add_argument("--url")
    bind_parser.add_argument("--read-back-at", required=True)
    bind_parser.add_argument("--action", choices=("create", "update", "link"))
    bind_parser.add_argument("--replace", action="store_true")

    review_parser = subparsers.add_parser("review", help="Record user review")
    review_parser.add_argument("--case-root", required=True)
    review_parser.add_argument("--verdict", choices=("changes_requested", "approved"), required=True)
    review_parser.add_argument("--actor", required=True)
    review_parser.add_argument("--note", required=True)

    export_parser = subparsers.add_parser("export", help="Export approved Vigers handoff")
    export_parser.add_argument("--case-root", required=True)
    export_parser.add_argument("--write", required=True)

    validate_parser = subparsers.add_parser("validate", help="Validate planning case")
    validate_parser.add_argument("--case-root", required=True)
    validate_parser.add_argument("--final", action="store_true")

    context_parser = subparsers.add_parser("context", help="Print bounded planner context")
    context_parser.add_argument("--case-root", required=True)

    status_parser = subparsers.add_parser("status", help="Regenerate status.md")
    status_parser.add_argument("--case-root", required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "init":
            cwd = Path(args.cwd)
            selection = resolve_init_profile(args.profile_id, cwd)
            selected_project_root = (
                str(selection.project_root) if selection.project_root is not None else None
            )
            if args.project_root and selected_project_root:
                if Path(args.project_root).expanduser().resolve() != Path(
                    selected_project_root
                ).resolve():
                    raise PlanningError("Explicit project root conflicts with detected profile")
            init_case(
                Path(args.case_root),
                case_id=args.case_id,
                profile_id=selection.profile_id,
                project_root=selected_project_root or args.project_root,
                passport_id=args.passport_id,
                passport_path=args.passport_path,
                required_anchor_systems=list(selection.planning_anchors),
            )
            print(f"PASS planning-case={args.case_id} state=intake")
            return 0
        root, manifest = load_case(Path(args.case_root))
        if args.command == "transition":
            transition(root, manifest, new_state=args.state, note=args.note)
            print(f"PASS state={manifest['state']} revision={manifest['revision']}")
            return 0
        if args.command == "bind":
            record_binding(
                root,
                manifest,
                target_id=args.target_id,
                system=args.system,
                object_id=args.object_id,
                url=args.url,
                read_back_at=args.read_back_at,
                action=args.action,
                replace=args.replace,
            )
            print(f"PASS binding={args.target_id}")
            return 0
        if args.command == "review":
            record_review(
                root,
                manifest,
                verdict=args.verdict,
                actor=args.actor,
                note=args.note,
            )
            print(f"PASS verdict={args.verdict} revision={manifest['revision']}")
            return 0
        if args.command == "export":
            export_handoff(root, manifest, Path(args.write))
            print(f"PASS handoff={args.write}")
            return 0
        if args.command == "validate":
            errors = validate_case(root, manifest, final=args.final)
            if errors:
                for error in errors:
                    print(f"ERROR: {error}", file=sys.stderr)
                return 1
            print(f"PASS planning-case={manifest['case_id']} state={manifest['state']}")
            return 0
        if args.command == "context":
            print(json.dumps(context_bundle(manifest), ensure_ascii=False, indent=2))
            return 0
        if args.command == "status":
            render_status(root, manifest)
            print(root / "status.md")
            return 0
        raise PlanningError(f"Unknown command: {args.command}")
    except (OSError, PipelineError, PlanningError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
