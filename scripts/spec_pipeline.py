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


ROOT = Path(__file__).resolve().parent.parent
GENERIC_PROFILE_PATH = ROOT / "profiles" / "generic.md"
PROFILE_TEMPLATE_PATH = ROOT / "profiles" / "project-profile-template.md"
PROJECT_PROFILE_RELATIVE = Path(".vigers") / "profile.md"
PROFILE_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
REQUIRED_PROFILE_HEADINGS = (
    "## Область",
    "## Канонические источники",
    "## Системный анализ",
    "## Архитектурный гейт",
    "## Артефакт и author gates",
    "## Жизненный цикл и публикация",
)
REQUIRED_CONTRACTS = (
    "system-analyst",
    "solution-architect",
    "spec-editor",
    "spec-reviewer",
)
REQUIRED_WORKFLOWS = ("specification-pipeline.md",)
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


def validate_profile_text(
    text: str,
    source: Path,
    *,
    allow_generic: bool,
) -> str:
    """Validate one built-in or project-owned profile and return its id."""
    metadata = parse_frontmatter(text, source)
    if metadata.get("vigers_profile") != "1":
        raise PipelineError(f"{source}: vigers_profile must be 1")
    profile_id = metadata.get("profile_id", "")
    if not PROFILE_ID_RE.fullmatch(profile_id):
        raise PipelineError(f"{source}: invalid profile_id: {profile_id!r}")
    if profile_id == "generic" and not allow_generic:
        raise PipelineError(f"{source}: project profile cannot shadow generic")
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
    return ProfileSelection(profile_id, resolved, root.resolve(), "project")


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
    return ProfileSelection(profile_id, GENERIC_PROFILE_PATH, None, "generic")


def select_profile(requested_id: str, cwd: Path) -> ProfileSelection:
    """Resolve auto/generic or assert that a discovered project id matches."""
    if requested_id == "generic":
        text = GENERIC_PROFILE_PATH.read_text(encoding="utf-8")
        profile_id = validate_profile_text(text, GENERIC_PROFILE_PATH, allow_generic=True)
        return ProfileSelection(profile_id, GENERIC_PROFILE_PATH, None, "generic")

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
        except PipelineError as exc:
            errors.append(str(exc))

    for workflow in REQUIRED_WORKFLOWS:
        try:
            text = safe_file(f"workflows/{workflow}").read_text(encoding="utf-8")
            for phase in range(1, 11):
                if f"## Фаза {phase}." not in text:
                    errors.append(f"{workflow}: missing phase {phase}")
        except PipelineError as exc:
            errors.append(str(exc))

    required_files = (
        "SKILL.md",
        "references/handoff-contract.md",
        "references/requirements-method.md",
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
            "{baseDir}/references/handoff-contract.md",
            "{baseDir}/scripts/spec_pipeline.py",
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

        raise AssertionError(args.command)
    except (OSError, PipelineError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
