#!/usr/bin/env python3
"""Prepare revmux review inputs, validate rounds, and emit adoption evidence.

The script is deliberately not a review loop. It turns one finished revmux
round into immutable evidence and combines exactly one initial/final pair into
bounded adoption metrics. Source changes remain the coordinator's responsibility.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


GATING_SEVERITIES = {"critical", "major"}
ACTIONABLE_VERDICTS = {"confirmed", "refined"}
VALID_VERDICTS = ACTIONABLE_VERDICTS | {"unverified"}
PHASES = {"initial", "final"}
REVIEW_MODES = {"block", "integration", "global", "final", "project-conformance"}
SHA256_RE_LENGTH = 64
REVMUX_COMPAT_REVISION = "33ede7aaf632cebbde08f2dd53ffa06c4722d81b"


class EvidenceError(RuntimeError):
    """The supplied revmux evidence is incomplete or inconsistent."""


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise EvidenceError(f"JSON root must be an object: {path}")
    return value


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def string_list(value: object, field: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise EvidenceError(f"{field} must be a string array")
    return value


def findings(report: dict[str, Any]) -> list[dict[str, Any]]:
    value = report.get("findings")
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise EvidenceError("findings must be an object array")
    return value


def finding_area(item: dict[str, Any]) -> str:
    file_name = str(item.get("file") or "<document>")
    lenses = item.get("lenses")
    if not isinstance(lenses, list) or not lenses:
        return f"unclassified::{file_name}"
    return ",".join(sorted(str(lens) for lens in lenses)) + f"::{file_name}"


def resolve_bounded_file(root: Path, relative: str, field: str) -> Path:
    path = (root / relative).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise EvidenceError(f"{field} escapes its root: {relative}") from exc
    if not path.is_file():
        raise EvidenceError(f"{field} is not a readable file: {path}")
    return path


def detect_revmux(binary: str) -> dict[str, str]:
    resolved = shutil.which(binary)
    if resolved is None:
        raise EvidenceError(f"required revmux binary is not on PATH: {binary}")
    try:
        result = subprocess.run(
            [resolved, "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError as exc:
        raise EvidenceError(f"cannot execute revmux binary {resolved}: {exc}") from exc
    version = result.stdout.decode("utf-8", errors="replace").strip()
    if result.returncode != 0 or not version:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise EvidenceError(f"revmux --version failed: {detail or result.returncode}")
    if REVMUX_COMPAT_REVISION[:7] not in version:
        raise EvidenceError(
            "unsupported revmux build; expected compatible revision "
            f"{REVMUX_COMPAT_REVISION}, got {version!r}"
        )
    return {
        "binary": str(Path(resolved).resolve()),
        "version": version,
        "compatible_revision": REVMUX_COMPAT_REVISION,
    }


def expected_covered_gates(assignment: dict[str, Any]) -> list[str]:
    role_mode = assignment.get("role_mode")
    if role_mode == "block":
        block = assignment.get("block")
        block_id = block.get("id") if isinstance(block, dict) else None
        if not isinstance(block_id, str) or not block_id:
            raise EvidenceError("block revmux assignment requires block.id")
        return [f"block_review:{block_id}"]
    return {
        "integration": ["integration_review"],
        "global": ["global_review"],
        "final": ["integration_review", "global_review", "project_conformance"],
        "project-conformance": ["project_conformance"],
    }.get(str(role_mode), [])


def comparison_question(role_mode: str, target: list[str]) -> str:
    target_label = ", ".join(target)
    return {
        "block": f"Does {target_label} conform to its kernel, dependencies, decisions and semantic index?",
        "integration": "Does the integrated draft preserve every block and remain coherent across their boundaries?",
        "global": "Does the draft satisfy the frozen goal, scope, requirements, acceptance and traceability model?",
        "final": "Does the draft pass the exact combined integration, global and project gates in this assignment?",
        "project-conformance": "Does the draft conform to only the named project rules and document contract?",
    }[role_mode]


def prepare_round(args: argparse.Namespace) -> int:
    assignment = read_json(args.assignment)
    if assignment.get("role") != "spec-reviewer":
        raise EvidenceError("revmux round preparation requires role=spec-reviewer")
    if assignment.get("review_backend") != "revmux":
        raise EvidenceError("assignment must select review_backend=revmux")
    role_mode = assignment.get("role_mode")
    if role_mode not in REVIEW_MODES:
        raise EvidenceError(f"unsupported revmux reviewer mode: {role_mode!r}")
    phase = assignment.get("review_phase")
    if phase not in PHASES:
        raise EvidenceError("assignment requires review_phase=initial|final")
    expected_profile = "vigers-review" if phase == "initial" else "vigers-final"
    if assignment.get("revmux_profile") != expected_profile:
        raise EvidenceError(f"assignment profile must be {expected_profile}")
    covered = string_list(assignment.get("covered_gates"), "covered_gates")
    expected_gates = expected_covered_gates(assignment)
    if covered != expected_gates:
        raise EvidenceError(
            f"covered_gates must be exact for {role_mode}: {expected_gates}"
        )
    revmux_dependency = detect_revmux(args.revmux_bin)

    case_root = args.case_root.resolve()
    skill_root = args.skill_root.resolve()
    if not case_root.is_dir() or not skill_root.is_dir():
        raise EvidenceError("case root and skill root must be existing directories")
    case_inputs = string_list(assignment.get("case_inputs"), "case_inputs")
    contract_inputs = string_list(assignment.get("contract_inputs"), "contract_inputs")
    case_files = [
        resolve_bounded_file(case_root, relative, "case input") for relative in case_inputs
    ]
    contract_files = [
        resolve_bounded_file(skill_root, relative, "contract input")
        for relative in contract_inputs
    ]
    profile_source = args.profile_source.resolve()
    if not profile_source.is_file():
        raise EvidenceError(f"project profile is not a readable file: {profile_source}")

    block = assignment.get("block")
    block_targets = []
    if isinstance(block, dict):
        block_targets = [
            str(block[field])
            for field in ("artifact", "semantic_index")
            if isinstance(block.get(field), str)
        ]
    target_relatives = block_targets if role_mode == "block" else ["draft.md"]
    missing_targets = [item for item in target_relatives if item not in case_inputs]
    if missing_targets:
        raise EvidenceError("assignment omits review target(s): " + ", ".join(missing_targets))

    materials = [
        {
            "kind": "target" if relative in target_relatives else "case-baseline",
            "path": str(path),
            "relative": relative,
            "sha256": sha256(path),
        }
        for relative, path in zip(case_inputs, case_files, strict=True)
    ] + [
        {
            "kind": "review-contract",
            "path": str(path),
            "relative": relative,
            "sha256": sha256(path),
        }
        for relative, path in zip(contract_inputs, contract_files, strict=True)
    ]
    materials.append(
        {
            "kind": "project-profile",
            "path": str(profile_source),
            "relative": profile_source.name,
            "sha256": sha256(profile_source),
        }
    )
    fingerprint_payload = {
        "role_mode": role_mode,
        "review_scope": assignment.get("review_scope"),
        "covered_gates": covered,
        "materials": materials,
    }
    material_fingerprint = hashlib.sha256(
        json.dumps(
            fingerprint_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    assigned_subject = assignment.get("subject_sha256")
    subject_sha256 = (
        assigned_subject
        if isinstance(assigned_subject, str) and len(assigned_subject) == SHA256_RE_LENGTH
        else material_fingerprint
    )
    context_payload = {
        "schema": 1,
        "case_id": assignment.get("case_id"),
        "role": "spec-reviewer",
        "role_mode": role_mode,
        "review_scope": assignment.get("review_scope"),
        "review_backend": "revmux",
        "review_phase": phase,
        "revmux_profile": expected_profile,
        "covered_gates": covered,
        "subject_sha256": subject_sha256,
        "material_fingerprint": material_fingerprint,
        "question": comparison_question(role_mode, target_relatives),
        "targets": [item for item in materials if item["kind"] == "target"],
        "baselines": [item for item in materials if item["kind"] != "target"],
        "excluded": assignment.get("exclude", []),
        "revmux_dependency": revmux_dependency,
    }

    outputs = [args.scope_output, args.goal_output, args.profile_output]
    if any(path.exists() for path in outputs):
        raise EvidenceError("revmux new output files must not already exist")
    if args.context_dir.exists():
        if not args.context_dir.is_dir() or any(args.context_dir.iterdir()):
            raise EvidenceError("revmux context directory must be absent or empty")
    args.context_dir.mkdir(parents=True, exist_ok=True)
    context_path = args.context_dir / "vigers-assignment.json"
    context_path.write_text(
        json.dumps(context_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    target_lines = ", ".join(f"`{item}`" for item in target_relatives)
    excluded = assignment.get("exclude")
    excluded_text = ", ".join(str(item) for item in excluded) if isinstance(excluded, list) else "none"
    scope_text = (
        "# Scope\n\n"
        f"- Vigers case: `{assignment.get('case_id')}`\n"
        f"- Reviewer mode: `{role_mode}`; phase: `{phase}`; profile: `{expected_profile}`\n"
        f"- Covered gates: [{', '.join(covered)}]\n"
        f"- Exact target: {target_lines}\n"
        "- Compare it only against the hashed target/baseline map in "
        f"`{context_path}` and the frozen round profile.\n"
        f"- Subject SHA-256: `{subject_sha256}`\n"
        f"- Exclude: {excluded_text}\n"
        "- Do not inspect unlisted case artifacts, previous findings or author reasoning.\n"
    )
    goal_text = (
        "# Goal\n\n"
        f"{context_payload['question']}\n\n"
        "This review is correct only if it stays inside the assigned role mode and covered gates, "
        "uses the frozen profile as the project rule source, and reports only evidenced defects.\n\n"
        "Confirmed critical/major findings gate the assignment. Minor findings never request a "
        "correction round; in final phase they are not reported. Returning no findings is valid.\n"
    )
    args.scope_output.write_text(scope_text, encoding="utf-8")
    args.goal_output.write_text(goal_text, encoding="utf-8")
    args.profile_output.write_bytes(profile_source.read_bytes())
    result = {
        "schema": 1,
        "scope": str(args.scope_output.resolve()),
        "goal": str(args.goal_output.resolve()),
        "profile": str(args.profile_output.resolve()),
        "context": str(context_path.resolve()),
        "role_mode": role_mode,
        "covered_gates": covered,
        "subject_sha256": subject_sha256,
        "material_fingerprint": material_fingerprint,
        "revmux_dependency": revmux_dependency,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def gating_findings(report: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        item
        for item in findings(report)
        if item.get("severity") in GATING_SEVERITIES
        and item.get("verdict") in ACTIONABLE_VERDICTS
    ]


def validate_round(
    report_path: Path,
    manifest_path: Path,
    expected_profile: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    report = read_json(report_path)
    manifest = read_json(manifest_path)
    scope = report.get("scope")
    sources = report.get("sources")
    stats = report.get("stats")
    if not isinstance(scope, dict) or not isinstance(sources, dict) or not isinstance(stats, dict):
        raise EvidenceError("report requires scope, sources and stats objects")
    for field in ("task", "run", "scope_path"):
        if not isinstance(scope.get(field), str) or not scope[field]:
            raise EvidenceError(f"scope.{field} must be a non-empty string")
    for field in ("task", "run", "scope_path"):
        if manifest.get(field) != scope.get(field):
            raise EvidenceError(f"manifest {field} does not match report scope")
    if manifest.get("profile") != expected_profile:
        raise EvidenceError(
            f"expected revmux profile {expected_profile!r}, got {manifest.get('profile')!r}"
        )
    expected = sources.get("expected")
    reported = sources.get("reported")
    degraded = string_list(sources.get("degraded"), "sources.degraded")
    agents = sources.get("agents")
    if not isinstance(expected, int) or expected < 1:
        raise EvidenceError("sources.expected must be a positive integer")
    if not isinstance(reported, int) or reported != expected:
        raise EvidenceError(f"incomplete revmux sources: {reported}/{expected}")
    if degraded:
        raise EvidenceError("degraded revmux sources: " + ", ".join(degraded))
    if not isinstance(agents, list) or len(agents) != expected:
        raise EvidenceError("sources.agents must contain every expected source")
    degraded_agents = [
        str(agent.get("name", "<unnamed>"))
        for agent in agents
        if isinstance(agent, dict) and agent.get("degraded") is True
    ]
    if degraded_agents:
        raise EvidenceError("degraded revmux agents: " + ", ".join(degraded_agents))
    for item in findings(report):
        severity = item.get("severity")
        verdict = item.get("verdict")
        if severity not in {"critical", "major", "minor"}:
            raise EvidenceError(f"finding has invalid severity: {severity!r}")
        if verdict not in VALID_VERDICTS:
            raise EvidenceError(f"finding has invalid actionable verdict: {verdict!r}")
        if severity in GATING_SEVERITIES and verdict == "unverified":
            raise EvidenceError("critical/major finding is unverified")
    duration_ms = stats.get("duration_ms")
    tokens = stats.get("tokens")
    if not isinstance(duration_ms, int) or duration_ms < 0:
        raise EvidenceError("stats.duration_ms must be a non-negative integer")
    if not isinstance(tokens, int) or tokens < 0:
        raise EvidenceError("stats.tokens must be a non-negative integer")
    if manifest.get("duration_ms") != duration_ms or manifest.get("tokens") != tokens:
        raise EvidenceError("manifest timing/token totals do not match report")

    stages = stats.get("stages")
    if not isinstance(stages, list) or not all(isinstance(item, dict) for item in stages):
        raise EvidenceError("stats.stages must be an object array")
    stage_names = {str(item.get("name")) for item in stages}
    if not {"synthesis", "verify"}.issubset(stage_names):
        raise EvidenceError("review evidence requires both synthesis and verify stages")

    round_dir = manifest_path.resolve().parent
    stage_prompts = list((round_dir / "prompts" / "stages").glob("*.md"))
    if len(stage_prompts) < 2:
        raise EvidenceError("round archive is missing synthesis/verify prompt evidence")
    retry_calls = list((round_dir / "agents").glob("*.retry.*"))
    revmux_model_calls = len(agents) + len(stage_prompts) + len(retry_calls)
    model_calls = revmux_model_calls + 1  # the fresh reviewer-driver assignment
    gating = gating_findings(report)
    metrics = {
        "schema": 1,
        "task": scope["task"],
        "run": scope["run"],
        "profile": expected_profile,
        "report": str(report_path.resolve()),
        "report_sha256": sha256(report_path),
        "manifest": str(manifest_path.resolve()),
        "manifest_sha256": sha256(manifest_path),
        "revmux_duration_ms": duration_ms,
        "model_calls": model_calls,
        "revmux_model_calls": revmux_model_calls,
        "driver_model_calls": 1,
        "revmux_tokens": tokens,
        "confirmed_critical": sum(item.get("severity") == "critical" for item in gating),
        "confirmed_major": sum(item.get("severity") == "major" for item in gating),
        "confirmed_gating_total": len(gating),
        "minor": sum(item.get("severity") == "minor" for item in findings(report)),
        "gating_areas": sorted({finding_area(item) for item in gating}),
        "source_count": expected,
        "degraded": False,
    }
    return report, manifest, metrics


def write_round(args: argparse.Namespace) -> int:
    report, _, metrics = validate_round(args.report, args.manifest, args.expected_profile)
    if args.phase not in PHASES:
        raise EvidenceError(f"invalid phase: {args.phase}")
    if len(args.subject_sha256) != SHA256_RE_LENGTH:
        raise EvidenceError("subject SHA-256 must contain 64 characters")
    gating = gating_findings(report)
    decision = "pass" if not gating else "revise"
    if args.phase == "final" and gating:
        decision = "fail"
    covered = list(dict.fromkeys(args.covered_gate))
    if not covered:
        raise EvidenceError("round evidence requires at least one covered gate")
    gate_recommendation = (
        "pass"
        if not gating
        else ("user-decision" if args.phase == "final" else "revise")
    )
    evidence_lines = [
        "# revmux review evidence",
        "",
        f"- backend: `revmux`",
        f"- phase: `{args.phase}`",
        f"- profile: `{metrics['profile']}`",
        f"- task: `{metrics['task']}`",
        f"- run: `{metrics['run']}`",
        f"- subject_sha256: `{args.subject_sha256}`",
        f"- report_sha256: `{metrics['report_sha256']}`",
        f"- manifest_sha256: `{metrics['manifest_sha256']}`",
        f"- covered_gates: [{', '.join(covered)}]",
        f"- confirmed_critical: `{metrics['confirmed_critical']}`",
        f"- confirmed_major: `{metrics['confirmed_major']}`",
        f"- minor: `{metrics['minor']}`",
        f"- reported_blocker: `{metrics['confirmed_critical']}`",
        f"- reported_major: `{metrics['confirmed_major']}`",
        f"- reported_minor: `{metrics['minor']}`",
        f"- gate_recommendation: `{gate_recommendation}`",
        f"- revmux_duration_ms: `{metrics['revmux_duration_ms']}`",
        f"- model_calls: `{metrics['model_calls']}`",
        f"- revmux_tokens: `{metrics['revmux_tokens']}`",
        f"- decision: `{decision}`",
        "",
        "The reviewer used revmux as the sole semantic review engine for this gate and did not add an independent model pass.",
    ]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(evidence_lines) + "\n", encoding="utf-8")
    metrics.update(
        phase=args.phase,
        subject_sha256=args.subject_sha256,
        covered_gates=covered,
        decision=decision,
        gate_recommendation=gate_recommendation,
        evidence=str(args.output.resolve()),
        evidence_sha256=sha256(args.output),
    )
    args.metrics_output.parent.mkdir(parents=True, exist_ok=True)
    args.metrics_output.write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    return 1 if args.phase == "final" and gating else 0


def metric_paths(value: object, field: str) -> list[Path]:
    if isinstance(value, Path):
        return [value]
    if isinstance(value, list) and value and all(isinstance(item, Path) for item in value):
        return value
    raise EvidenceError(f"{field} requires one or more paths")


def receipt_fingerprint(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(sha256(path).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def subject_fingerprint(rows: list[dict[str, Any]], field: str) -> str:
    values = [str(item.get(field) or "") for item in rows]
    if any(len(value) != SHA256_RE_LENGTH for value in values):
        raise EvidenceError(f"{field} must contain SHA-256 values")
    if len(values) == 1:
        return values[0]
    payload = json.dumps(values, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def write_case(args: argparse.Namespace) -> int:
    initial_paths = metric_paths(args.initial_metrics, "initial metrics")
    final_paths = metric_paths(args.final_metrics, "final metrics")
    if len(initial_paths) != len(final_paths):
        raise EvidenceError("case metrics require matching initial/final gate pairs")
    initials = [read_json(path) for path in initial_paths]
    finals = [read_json(path) for path in final_paths]
    seen_gates: set[str] = set()
    gate_pairs: list[dict[str, Any]] = []
    for initial, final in zip(initials, finals, strict=True):
        if initial.get("phase") != "initial" or final.get("phase") != "final":
            raise EvidenceError("case metrics require initial/final gate pairs")
        if initial.get("task") != final.get("task"):
            raise EvidenceError("initial/final task mismatch")
        initial_gates = set(string_list(initial.get("covered_gates"), "initial.covered_gates"))
        final_gates = set(string_list(final.get("covered_gates"), "final.covered_gates"))
        if not initial_gates or initial_gates != final_gates:
            raise EvidenceError("initial/final covered gates must be the same and non-empty")
        if seen_gates & initial_gates:
            raise EvidenceError("case metrics contain duplicate reviewer gate coverage")
        seen_gates.update(initial_gates)
        gate_pairs.append(
            {
                "covered_gates": sorted(initial_gates),
                "initial_subject_sha256": initial.get("subject_sha256"),
                "final_subject_sha256": final.get("subject_sha256"),
                "initial_decision": initial.get("decision"),
                "final_decision": final.get("decision"),
            }
        )
    tasks = {str(item.get("task")) for item in [*initials, *finals]}
    if len(tasks) != 1:
        raise EvidenceError("all gate pairs in one adoption case must use one revmux task")
    if args.active_time_seconds < 0:
        raise EvidenceError("active time must be non-negative")
    if args.driver_tokens < 0:
        raise EvidenceError("driver tokens must be non-negative")
    initial_gating_pairs = sum(
        int(item.get("confirmed_critical", 0)) + int(item.get("confirmed_major", 0)) > 0
        for item in initials
    )
    final_gating = sum(
        int(item.get("confirmed_critical", 0)) + int(item.get("confirmed_major", 0))
        for item in finals
    )
    if (
        args.correction_rounds < int(initial_gating_pairs > 0)
        or args.correction_rounds > initial_gating_pairs
    ):
        raise EvidenceError(
            "correction rounds must be zero without gating findings and at most one per gating gate pair"
        )
    if all(item.get("decision") == "pass" for item in finals) and final_gating:
        raise EvidenceError("final pass cannot contain confirmed critical/major findings")
    initial_areas = {
        area
        for item in initials
        for area in string_list(item.get("gating_areas"), "initial.gating_areas")
    }
    final_areas = {
        area
        for item in finals
        for area in string_list(item.get("gating_areas"), "final.gating_areas")
    }
    final_decision = "pass" if all(item.get("decision") == "pass" for item in finals) else "fail"
    receipt = {
        "schema": 1,
        "case_kind": args.case_kind,
        "task": next(iter(tasks)),
        "review_gate_pairs": gate_pairs,
        "initial_subject_sha256": subject_fingerprint(initials, "subject_sha256"),
        "final_subject_sha256": subject_fingerprint(finals, "subject_sha256"),
        "active_time_seconds": args.active_time_seconds,
        "revmux_duration_ms": sum(
            int(item["revmux_duration_ms"]) for item in [*initials, *finals]
        ),
        "model_calls": sum(int(item["model_calls"]) for item in [*initials, *finals]),
        "revmux_tokens": sum(
            int(item["revmux_tokens"]) for item in [*initials, *finals]
        ),
        "driver_tokens": args.driver_tokens,
        "tokens": sum(int(item["revmux_tokens"]) for item in [*initials, *finals])
        + args.driver_tokens,
        "confirmed_critical": sum(int(item["confirmed_critical"]) for item in initials),
        "confirmed_major": sum(int(item["confirmed_major"]) for item in initials),
        "correction_rounds": args.correction_rounds,
        "reopened_reviewed_areas": sorted(final_areas - initial_areas),
        "repeated_gating_areas": sorted(final_areas & initial_areas),
        "final_decision": final_decision,
        "initial_metrics_sha256": receipt_fingerprint(initial_paths),
        "final_metrics_sha256": receipt_fingerprint(final_paths),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0 if receipt["final_decision"] == "pass" else 1


def aggregate(args: argparse.Namespace) -> int:
    receipts = [read_json(path) for path in args.receipt]
    count = len(receipts)
    if count > 5:
        raise EvidenceError("adoption decision must be taken no later than five cases")
    identities = [
        (str(item.get("task")), str(item.get("initial_subject_sha256")))
        for item in receipts
    ]
    if len(set(identities)) != count:
        raise EvidenceError("adoption aggregate requires distinct case subjects")
    case_kinds = {str(item.get("case_kind")) for item in receipts}
    coverage_ready = {"vigers", "delivery"}.issubset(case_kinds)
    decision_ready = 3 <= count <= 5 and coverage_ready
    result = {
        "schema": 1,
        "case_count": count,
        "case_kinds": sorted(case_kinds),
        "decision_ready": decision_ready,
        "permanent_enablement": (
            "human-decision-required"
            if decision_ready
            else ("missing-vigers-or-delivery-coverage" if count >= 3 else "not-enough-cases")
        ),
        "totals": {
            field: sum(int(item.get(field, 0)) for item in receipts)
            for field in (
                "active_time_seconds",
                "revmux_duration_ms",
                "model_calls",
                "revmux_tokens",
                "driver_tokens",
                "tokens",
                "confirmed_critical",
                "confirmed_major",
                "correction_rounds",
            )
        },
        "reopened_reviewed_areas": sum(
            len(item.get("reopened_reviewed_areas", [])) for item in receipts
        ),
        "repeated_gating_areas": sum(
            len(item.get("repeated_gating_areas", [])) for item in receipts
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    prepare_cmd = commands.add_parser("prepare")
    prepare_cmd.add_argument("--assignment", type=Path, required=True)
    prepare_cmd.add_argument("--case-root", type=Path, required=True)
    prepare_cmd.add_argument(
        "--skill-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    prepare_cmd.add_argument("--profile-source", type=Path, required=True)
    prepare_cmd.add_argument("--revmux-bin", default="revmux")
    prepare_cmd.add_argument("--scope-output", type=Path, required=True)
    prepare_cmd.add_argument("--goal-output", type=Path, required=True)
    prepare_cmd.add_argument("--profile-output", type=Path, required=True)
    prepare_cmd.add_argument("--context-dir", type=Path, required=True)
    round_cmd = commands.add_parser("round")
    round_cmd.add_argument("--report", type=Path, required=True)
    round_cmd.add_argument("--manifest", type=Path, required=True)
    round_cmd.add_argument("--phase", choices=sorted(PHASES), required=True)
    round_cmd.add_argument("--expected-profile", required=True)
    round_cmd.add_argument("--subject-sha256", required=True)
    round_cmd.add_argument("--covered-gate", action="append", default=[])
    round_cmd.add_argument("--output", type=Path, required=True)
    round_cmd.add_argument("--metrics-output", type=Path, required=True)
    case_cmd = commands.add_parser("case")
    case_cmd.add_argument("--initial-metrics", type=Path, action="append", required=True)
    case_cmd.add_argument("--final-metrics", type=Path, action="append", required=True)
    case_cmd.add_argument("--case-kind", choices=("vigers", "delivery"), required=True)
    case_cmd.add_argument("--active-time-seconds", type=int, required=True)
    case_cmd.add_argument("--driver-tokens", type=int, required=True)
    case_cmd.add_argument("--correction-rounds", type=int, required=True)
    case_cmd.add_argument("--output", type=Path, required=True)
    aggregate_cmd = commands.add_parser("aggregate")
    aggregate_cmd.add_argument("--receipt", type=Path, action="append", required=True)
    aggregate_cmd.add_argument("--output", type=Path, required=True)
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "prepare":
            return prepare_round(args)
        if args.command == "round":
            return write_round(args)
        if args.command == "case":
            return write_case(args)
        return aggregate(args)
    except EvidenceError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
