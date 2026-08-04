#!/usr/bin/env python3
"""Deterministic, resumable case-state orchestration for Vigers."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mode_decision import (
    MODE_DECISION_FILENAME,
    ModeDecisionError,
    validate_mode_decision,
)


SCHEMA_VERSION = 2
TODO_MARKER = "VIGERS_TODO"
CASE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
BLOCK_ID_RE = re.compile(r"^B[0-9]{2,3}$")
SEMANTIC_ID_RE = re.compile(
    r"^(GOAL|ACT|SCN|RULE|DATA|STATE|IF|QUAL|REQ|AC|DOD|ASM|Q|DEC|CON)-"
    r"(B[0-9]{2,3})-[0-9]{3}$"
)

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
    unexpected_entries = [
        entry for entry in existing_entries if entry.name != MODE_DECISION_FILENAME
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

    manifest = {
        "schema": SCHEMA_VERSION,
        "case_id": case_id,
        "mode": mode,
        "intent": intent,
        "profile_id": profile_id,
        "route_id": route_id,
        "project_root": project_root,
        "mode_decision": decision_binding,
        "created_at": now_utc(),
        "updated_at": now_utc(),
        "kernel": {
            "path": "kernel.md",
            "revision": 1,
            "sha256": sha256(root / "kernel.md"),
        },
        "artifacts": {
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
            )
        ],
    }
    ledger = {"schema": SCHEMA_VERSION, "blocks": []}
    atomic_json(manifest_path, manifest)
    atomic_json(root / "ledger.json", ledger)
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


def save_case(root: Path, manifest: dict[str, Any], ledger: dict[str, Any]) -> None:
    """Persist state and refresh the human-readable dashboard."""
    manifest["updated_at"] = now_utc()
    atomic_json(root / "manifest.json", manifest)
    atomic_json(root / "ledger.json", ledger)
    render_status(root, manifest, ledger)


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
    block_id: str,
    role: str,
) -> dict[str, Any]:
    """Build a bounded, role-specific list of case inputs."""
    blocks = blocks_by_id(ledger)
    if block_id not in blocks:
        raise CaseError(f"Unknown block: {block_id}")
    block = blocks[block_id]
    dependencies = [blocks[item] for item in block["depends_on"]]
    common = ["manifest.json", "kernel.md", "evidence.md", "decisions.md"]
    if manifest.get("mode_decision") is not None:
        common.insert(1, MODE_DECISION_FILENAME)
    dependency_files = [
        value
        for dependency in dependencies
        for value in (dependency["artifact"], dependency["semantic_index"])
    ]
    if role == "system-analyst":
        inputs = common + dependency_files
        excluded = [block["review"], "draft.md", "reviews/global.md"]
    elif role == "spec-editor":
        inputs = common + dependency_files + [block["artifact"], block["semantic_index"]]
        excluded = [block["review"], "reviews/global.md"]
    elif role == "spec-reviewer":
        inputs = common + dependency_files + [block["artifact"], block["semantic_index"]]
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
            "selected Vigers method route",
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
        f"- kernel revision: `{manifest['kernel']['revision']}`",
        f"- updated: `{manifest['updated_at']}`",
        "",
        "## Blocks",
        "",
        "| ID | Kind | Status | Depends on | Title |",
        "|---|---|---|---|---|",
    ]
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
    init_parser.add_argument("--profile-id", default="generic")
    init_parser.add_argument("--route-id", default="core")
    init_parser.add_argument("--project-root")
    init_parser.add_argument(
        "--allow-unrecorded-mode",
        action="store_true",
        help="Migration escape hatch for a case without mode-decision.json",
    )

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

    context_parser = subparsers.add_parser("context", help="Print a bounded block context")
    context_parser.add_argument("--case-root", required=True)
    context_parser.add_argument("--block", required=True)
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
            init_case(
                Path(args.case_root),
                case_id=args.case_id,
                mode=args.mode,
                intent=args.intent,
                profile_id=args.profile_id,
                route_id=args.route_id,
                project_root=args.project_root,
                allow_unrecorded_mode=args.allow_unrecorded_mode,
            )
            print(f"PASS case={args.case_id} mode={args.mode}")
            return 0

        root, manifest, ledger = load_case(Path(args.case_root))
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
