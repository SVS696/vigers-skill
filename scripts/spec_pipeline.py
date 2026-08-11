#!/usr/bin/env python3
"""Project-profile discovery and structural validation for Vigers."""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

from document_conformance import DocumentContractError, build_profile_contract
from mode_decision import (
    MODE_DECISION_FILENAME,
    SURFACES,
    ModeDecisionError,
    build_mode_decision,
)


ROOT = Path(__file__).resolve().parent.parent
GENERIC_PROFILE_PATH = ROOT / "profiles" / "generic.md"
PROFILE_TEMPLATE_PATH = ROOT / "profiles" / "project-profile-template.md"
PROJECT_PROFILE_RELATIVE = Path(".vigers") / "profile.md"
PROFILE_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
WORKING_PROJECTION_POLICIES = {"required", "optional", "disabled"}
PROJECTION_EVIDENCE_KINDS = {"local_file", "external_readback"}
REQUIRED_PROFILE_HEADINGS = (
    "## Область",
    "## Канонические источники",
    "## Планирование и внешние артефакты",
    "## Системный анализ",
    "## Архитектурный гейт",
    "## Режимы и разбиение",
    "## Артефакт и author gates",
    "## Жизненный цикл и публикация",
)
REQUIRED_CONTRACTS = (
    "planner",
    "system-analyst",
    "solution-architect",
    "spec-editor",
    "spec-reviewer",
)
REQUIRED_AGENT_REFERENCES = (
    "references/prompt-contract.md",
    "references/handoff-contract.md",
    "references/convergence-contract.md",
    "references/solution-boundary-contract.md",
)
REQUIRED_WORKFLOWS = {
    "planning-pipeline.md": 8,
    "specification-pipeline.md": 10,
    "block-pipeline.md": 13,
}
REQUIRED_PROMPT_EVALS = (
    "evals/prompt-cookbook/convergence-closed-coverage.json",
    "evals/prompt-cookbook/delivery-completion-handoff-barrier.json",
    "evals/prompt-cookbook/early-working-projection.json",
    "evals/prompt-cookbook/live-checklist-completion-barrier.json",
    "evals/prompt-cookbook/project-conformance-document-barrier.json",
    "evals/prompt-cookbook/profile-owned-working-projection.json",
    "evals/prompt-cookbook/bounded-systemic-scope.json",
    "evals/prompt-cookbook/solution-boundary-smells.json",
    "evals/prompt-cookbook/user-story-format-barrier.json",
    "evals/prompt-cookbook/traceability-link-barrier.json",
)
PUBLIC_FORBIDDEN_MARKERS = tuple(
    "".join(parts) for parts in (("R", "TL"), ("H", "ÆZE"), ("HA", "EZE"))
)
HOME_PATH_MARKERS = tuple("".join(parts) for parts in (("/", "Users/"), ("/", "home/")))


class PipelineError(RuntimeError):
    """Profile discovery or structural validation failure."""


@dataclass(frozen=True)
class ProfileSelection:
    profile_id: str
    profile_path: Path
    project_root: Path | None
    source: str
    planning_anchors: tuple[str, ...]
    working_projection: str
    document_contract: dict[str, object] | None


def safe_file(relative: str) -> Path:
    """Resolve one package-owned file without allowing root escape."""
    if not isinstance(relative, str) or not relative:
        raise PipelineError("File path must be a non-empty relative string")
    candidate = (ROOT / relative).resolve()
    try:
        candidate.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise PipelineError(f"Path escapes skill root: {relative}") from exc
    if not candidate.is_file():
        raise PipelineError(f"File does not exist: {relative}")
    return candidate


def ancestors(cwd: Path) -> list[Path]:
    """Return cwd and its ancestors, normalizing a file cwd to its parent."""
    current = cwd.expanduser().resolve()
    if current.is_file():
        current = current.parent
    return [current, *current.parents]


def parse_frontmatter(text: str, source: Path) -> dict[str, str]:
    """Parse the deliberately small scalar frontmatter used by profiles."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise PipelineError(f"{source}: missing YAML frontmatter")
    try:
        end = next(index for index, line in enumerate(lines[1:], 1) if line.strip() == "---")
    except StopIteration as exc:
        raise PipelineError(f"{source}: unclosed YAML frontmatter") from exc

    metadata: dict[str, str] = {}
    for line in lines[1:end]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in stripped:
            raise PipelineError(f"{source}: invalid frontmatter line: {stripped}")
        key, value = stripped.split(":", 1)
        metadata[key.strip()] = value.strip().strip('"\'')
    return metadata


def parse_planning_anchors(metadata: dict[str, str], source: Path) -> tuple[str, ...]:
    """Parse the optional comma-separated profile anchor contract."""
    anchors: list[str] = []
    seen: set[str] = set()
    for raw in metadata.get("planning_anchors", "").split(","):
        anchor = raw.strip()
        if not anchor:
            continue
        normalized = anchor.casefold()
        if normalized in seen:
            raise PipelineError(f"{source}: duplicate planning anchor {anchor!r}")
        seen.add(normalized)
        anchors.append(anchor)
    return tuple(anchors)


def parse_working_projection(metadata: dict[str, str], source: Path) -> str:
    """Return the machine-readable visibility policy declared by a profile."""
    policy = metadata.get("working_projection", "optional").strip().casefold() or "optional"
    if policy not in WORKING_PROJECTION_POLICIES:
        allowed = ", ".join(sorted(WORKING_PROJECTION_POLICIES))
        raise PipelineError(
            f"{source}: working_projection must be one of {allowed}, got {policy!r}"
        )
    return policy


def validate_profile_text(
    text: str,
    source: Path,
    *,
    allow_generic: bool,
) -> str:
    """Validate one built-in or project-owned profile and return its id."""
    metadata = parse_frontmatter(text, source)
    if metadata.get("vigers_profile") != "2":
        raise PipelineError(f"{source}: vigers_profile must be 2")
    profile_id = metadata.get("profile_id", "")
    if not PROFILE_ID_RE.fullmatch(profile_id):
        raise PipelineError(f"{source}: invalid profile_id: {profile_id!r}")
    if profile_id == "generic" and not allow_generic:
        raise PipelineError(f"{source}: project profile cannot shadow generic")
    parse_planning_anchors(metadata, source)
    parse_working_projection(metadata, source)
    try:
        build_profile_contract(
            metadata,
            profile_id=profile_id,
            profile_text=text,
            source=source,
        )
    except DocumentContractError as exc:
        raise PipelineError(str(exc)) from exc
    missing = [heading for heading in REQUIRED_PROFILE_HEADINGS if heading not in text]
    if missing:
        raise PipelineError(f"{source}: missing headings: {', '.join(missing)}")
    return profile_id


def read_project_profile(root: Path) -> ProfileSelection | None:
    """Read a profile owned by exactly this project root, if present."""
    candidate = root / PROJECT_PROFILE_RELATIVE
    if not candidate.exists() and not candidate.is_symlink():
        return None
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise PipelineError(f"{candidate}: profile symlink escapes project root") from exc
    if not resolved.is_file():
        raise PipelineError(f"{candidate}: project profile is not a readable file")
    text = resolved.read_text(encoding="utf-8")
    profile_id = validate_profile_text(text, candidate, allow_generic=False)
    metadata = parse_frontmatter(text, candidate)
    return ProfileSelection(
        profile_id,
        resolved,
        root.resolve(),
        "project",
        parse_planning_anchors(metadata, candidate),
        parse_working_projection(metadata, candidate),
        build_profile_contract(
            metadata,
            profile_id=profile_id,
            profile_text=text,
            source=candidate,
        ),
    )


def detect_profile(cwd: Path) -> ProfileSelection:
    """Select the nearest project overlay or the package-owned generic profile."""
    for root in ancestors(cwd):
        selection = read_project_profile(root)
        if selection is not None:
            return selection

    generic_text = GENERIC_PROFILE_PATH.read_text(encoding="utf-8")
    profile_id = validate_profile_text(
        generic_text,
        GENERIC_PROFILE_PATH,
        allow_generic=True,
    )
    metadata = parse_frontmatter(generic_text, GENERIC_PROFILE_PATH)
    return ProfileSelection(
        profile_id,
        GENERIC_PROFILE_PATH,
        None,
        "generic",
        parse_planning_anchors(metadata, GENERIC_PROFILE_PATH),
        parse_working_projection(metadata, GENERIC_PROFILE_PATH),
        build_profile_contract(
            metadata,
            profile_id=profile_id,
            profile_text=generic_text,
            source=GENERIC_PROFILE_PATH,
        ),
    )


def select_profile(requested_id: str, cwd: Path) -> ProfileSelection:
    """Resolve auto/generic or assert that a discovered project id matches."""
    if requested_id == "generic":
        text = GENERIC_PROFILE_PATH.read_text(encoding="utf-8")
        profile_id = validate_profile_text(text, GENERIC_PROFILE_PATH, allow_generic=True)
        metadata = parse_frontmatter(text, GENERIC_PROFILE_PATH)
        return ProfileSelection(
            profile_id,
            GENERIC_PROFILE_PATH,
            None,
            "generic",
            parse_planning_anchors(metadata, GENERIC_PROFILE_PATH),
            parse_working_projection(metadata, GENERIC_PROFILE_PATH),
            build_profile_contract(
                metadata,
                profile_id=profile_id,
                profile_text=text,
                source=GENERIC_PROFILE_PATH,
            ),
        )

    detected = detect_profile(cwd)
    if requested_id == "auto":
        return detected
    if detected.profile_id != requested_id:
        raise PipelineError(
            f"Requested profile {requested_id!r}, but cwd resolves to {detected.profile_id!r}"
        )
    return detected


def display_profile_file(selection: ProfileSelection) -> str:
    if selection.source == "generic":
        return str(selection.profile_path.relative_to(ROOT))
    return PROJECT_PROFILE_RELATIVE.as_posix()


def write_mode_decision(path: Path, payload: dict[str, object]) -> Path:
    """Create one case-owned decision artifact without overwriting prior state."""
    target = path.expanduser().resolve()
    if target.name != MODE_DECISION_FILENAME:
        raise PipelineError(f"Mode decision file must be named {MODE_DECISION_FILENAME}")
    if target.exists() or target.is_symlink():
        raise PipelineError(f"Refusing to overwrite mode decision: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def validate(project_roots: list[Path] | None = None) -> dict[str, int]:
    """Validate the public package and any explicitly supplied private overlays."""
    errors: list[str] = []

    for profile_path, allow_generic in (
        (GENERIC_PROFILE_PATH, True),
        (PROFILE_TEMPLATE_PATH, False),
    ):
        try:
            text = profile_path.read_text(encoding="utf-8")
            validate_profile_text(text, profile_path, allow_generic=allow_generic)
        except (OSError, PipelineError) as exc:
            errors.append(str(exc))

    validated_projects = 0
    for supplied_root in project_roots or []:
        project_root = supplied_root.expanduser().resolve()
        try:
            selection = read_project_profile(project_root)
            if selection is None:
                raise PipelineError(
                    f"{project_root}: missing {PROJECT_PROFILE_RELATIVE.as_posix()}"
                )
            validated_projects += 1
        except (OSError, PipelineError) as exc:
            errors.append(str(exc))

    for contract in REQUIRED_CONTRACTS:
        relative = f"agents/contracts/{contract}.md"
        try:
            text = safe_file(relative).read_text(encoding="utf-8")
            for heading in ("## Назначение", "## Выход"):
                if heading not in text:
                    errors.append(f"{relative}: missing heading {heading}")
        except PipelineError as exc:
            errors.append(str(exc))

        codex_relative = f"agents/codex/vigers-{contract}.toml"
        try:
            codex_text = safe_file(codex_relative).read_text(encoding="utf-8")
            parsed = tomllib.loads(codex_text)
            for field in ("name", "description", "developer_instructions"):
                if not isinstance(parsed.get(field), str) or not parsed[field].strip():
                    errors.append(f"{codex_relative}: missing string field {field}")
            instructions = parsed.get("developer_instructions", "")
            for reference in REQUIRED_AGENT_REFERENCES:
                if reference not in instructions:
                    errors.append(f"{codex_relative}: missing agent reference {reference}")
        except (PipelineError, tomllib.TOMLDecodeError) as exc:
            errors.append(f"{codex_relative}: {exc}")

        claude_relative = f"agents/claude/vigers-{contract}.md"
        try:
            claude_text = safe_file(claude_relative).read_text(encoding="utf-8")
            if not claude_text.startswith("---\n"):
                errors.append(f"{claude_relative}: missing YAML frontmatter")
            for field in ("name:", "description:", "tools:"):
                if field not in claude_text:
                    errors.append(f"{claude_relative}: missing frontmatter field {field}")
            for reference in REQUIRED_AGENT_REFERENCES:
                if reference not in claude_text:
                    errors.append(f"{claude_relative}: missing agent reference {reference}")
        except PipelineError as exc:
            errors.append(str(exc))

    for workflow, phase_count in REQUIRED_WORKFLOWS.items():
        try:
            text = safe_file(f"workflows/{workflow}").read_text(encoding="utf-8")
            for phase in range(1, phase_count + 1):
                if f"## Фаза {phase}." not in text:
                    errors.append(f"{workflow}: missing phase {phase}")
        except PipelineError as exc:
            errors.append(str(exc))

    prompt_eval_count = 0
    for relative in REQUIRED_PROMPT_EVALS:
        try:
            payload = json.loads(safe_file(relative).read_text(encoding="utf-8"))
            if payload.get("schema") != 1:
                errors.append(f"{relative}: schema must be 1")
            if not isinstance(payload.get("id"), str) or not payload["id"].strip():
                errors.append(f"{relative}: missing id")
            prompt = payload.get("prompt")
            if not isinstance(prompt, str):
                errors.append(f"{relative}: prompt must be a string")
            else:
                for marker in ("<assignment>", "<source_documents>", "<final_instruction>"):
                    if marker not in prompt:
                        errors.append(f"{relative}: prompt missing {marker}")
            expected = payload.get("expected")
            if not isinstance(expected, dict):
                errors.append(f"{relative}: expected must be an object")
            else:
                for field in (
                    "required_actions",
                    "forbidden_actions",
                    "required_output_signals",
                    "allowed_research_exception",
                ):
                    if not expected.get(field):
                        errors.append(f"{relative}: expected.{field} is required")
            prompt_eval_count += 1
        except (json.JSONDecodeError, PipelineError) as exc:
            errors.append(f"{relative}: {exc}")

    required_files = (
        "SKILL.md",
        "references/handoff-contract.md",
        "references/prompt-contract.md",
        "references/case-state.md",
        "references/block-contract.md",
        "references/requirements-method.md",
        "references/planning-contract.md",
        "references/convergence-contract.md",
        "scripts/mode_decision.py",
        "scripts/planning_case.py",
        "scripts/case_pipeline.py",
        "scripts/install.py",
    )
    for relative in required_files:
        try:
            safe_file(relative)
        except PipelineError as exc:
            errors.append(str(exc))

    try:
        skill_text = safe_file("SKILL.md").read_text(encoding="utf-8")
        if len(skill_text.splitlines()) > 500:
            errors.append("SKILL.md exceeds 500 lines")
        for link in (
            "{baseDir}/workflows/specification-pipeline.md",
            "{baseDir}/workflows/block-pipeline.md",
            "{baseDir}/references/handoff-contract.md",
            "{baseDir}/references/prompt-contract.md",
            "{baseDir}/references/case-state.md",
            "{baseDir}/references/block-contract.md",
            "{baseDir}/references/convergence-contract.md",
            "{baseDir}/evals/prompt-cookbook/convergence-closed-coverage.json",
            "{baseDir}/evals/prompt-cookbook/early-working-projection.json",
            "{baseDir}/evals/prompt-cookbook/live-checklist-completion-barrier.json",
            "{baseDir}/evals/prompt-cookbook/profile-owned-working-projection.json",
            "{baseDir}/evals/prompt-cookbook/user-story-format-barrier.json",
            "{baseDir}/evals/prompt-cookbook/traceability-link-barrier.json",
            "{baseDir}/scripts/spec_pipeline.py",
            "{baseDir}/scripts/case_pipeline.py",
        ):
            if link not in skill_text:
                errors.append(f"SKILL.md missing link: {link}")
    except PipelineError as exc:
        errors.append(str(exc))

    public_suffixes = {".md", ".json", ".py", ".toml", ".yaml", ".yml"}
    for package_file in ROOT.rglob("*"):
        if not package_file.is_file() or package_file.suffix not in public_suffixes:
            continue
        if ".omc" in package_file.parts or "__pycache__" in package_file.parts:
            continue
        text = package_file.read_text(encoding="utf-8")
        relative = package_file.relative_to(ROOT)
        if any(marker in text for marker in HOME_PATH_MARKERS):
            errors.append(f"{relative} contains a hardcoded home path")
        for marker in PUBLIC_FORBIDDEN_MARKERS:
            if marker in text:
                errors.append(f"{relative} contains private project marker {marker!r}")

    if errors:
        raise PipelineError("\n".join(f"- {error}" for error in errors))

    return {
        "builtin_profiles": 1,
        "project_profiles": validated_projects,
        "contracts": len(REQUIRED_CONTRACTS),
        "runtime_adapters": len(REQUIRED_CONTRACTS) * 2,
        "workflows": len(REQUIRED_WORKFLOWS),
        "prompt_evals": prompt_eval_count,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Vigers specification pipeline tools")
    subparsers = parser.add_subparsers(dest="command", required=True)

    detect_parser = subparsers.add_parser("detect", help="Detect project profile")
    detect_parser.add_argument("--cwd", default=".")
    detect_parser.add_argument("--json", action="store_true")

    show_parser = subparsers.add_parser("show-profile", help="Print one profile")
    show_parser.add_argument("profile_id", help="auto, generic, or the detected project id")
    show_parser.add_argument("--cwd", default=".")

    validate_parser = subparsers.add_parser("validate", help="Validate package and overlays")
    validate_parser.add_argument("--project-root", action="append", default=[])

    suggest_parser = subparsers.add_parser(
        "suggest-mode",
        help="Select compact or block from explicit observable facts",
    )
    suggest_parser.add_argument("--cwd", default=".")
    suggest_parser.add_argument("--profile-id", default="auto")
    suggest_parser.add_argument("--task", required=True)
    suggest_parser.add_argument("--blocks", type=int, default=1)
    suggest_parser.add_argument("--surface", action="append", choices=sorted(SURFACES), default=[])
    suggest_parser.add_argument("--component", action="append", default=[])
    suggest_parser.add_argument("--owner", action="append", default=[])
    suggest_parser.add_argument("--dependent-parts", action="store_true")
    suggest_parser.add_argument("--unsafe-single-pass", action="store_true")
    suggest_parser.add_argument("--project-trigger", action="append", default=[])
    suggest_parser.add_argument("--requested-mode", choices=("compact", "block"))
    suggest_parser.add_argument(
        "--write",
        help=f"Create <case-root>/{MODE_DECISION_FILENAME} without overwriting it",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        if args.command == "validate":
            counts = validate([Path(item) for item in args.project_root])
            print("PASS " + " ".join(f"{key}={value}" for key, value in counts.items()))
            return 0

        if args.command == "detect":
            selection = detect_profile(Path(args.cwd))
            payload = {
                "profile_id": selection.profile_id,
                "profile_file": display_profile_file(selection),
                "profile_source": selection.source,
                "project_root": (
                    str(selection.project_root) if selection.project_root is not None else None
                ),
                "planning_anchors": list(selection.planning_anchors),
                "working_projection": selection.working_projection,
                "document_contract": selection.document_contract,
            }
            if args.json:
                print(json.dumps(payload, ensure_ascii=False))
            else:
                for key, value in payload.items():
                    print(f"{key}={value if value is not None else ''}")
            return 0

        if args.command == "show-profile":
            selection = select_profile(args.profile_id, Path(args.cwd))
            print(selection.profile_path.read_text(encoding="utf-8"))
            return 0

        if args.command == "suggest-mode":
            selection = select_profile(args.profile_id, Path(args.cwd))
            payload = build_mode_decision(
                task=args.task,
                profile_id=selection.profile_id,
                profile_file=display_profile_file(selection),
                profile_source=selection.source,
                project_root=(
                    str(selection.project_root) if selection.project_root is not None else None
                ),
                estimated_blocks=args.blocks,
                surfaces=args.surface,
                components=args.component,
                owners=args.owner,
                dependent_parts=args.dependent_parts,
                unsafe_single_pass=args.unsafe_single_pass,
                project_triggers=args.project_trigger,
                requested_mode=args.requested_mode,
            )
            if args.write:
                write_mode_decision(Path(args.write), payload)
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0

        raise AssertionError(args.command)
    except (OSError, PipelineError, ModeDecisionError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
