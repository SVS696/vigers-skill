#!/usr/bin/env python3
"""Project-profile discovery and structural validation for Vigers."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

from document_conformance import DocumentContractError, build_profile_contract
from mode_decision import (
    ASSURANCE_LEVELS,
    CHANGE_SCOPES,
    MODE_DECISION_FILENAME,
    PROJECTION_SYNC_POLICIES,
    SURFACES,
    TRACKING_POLICIES,
    ModeDecisionError,
    build_mode_decision,
)


ROOT = Path(__file__).resolve().parent.parent
GENERIC_PROFILE_PATH = ROOT / "profiles" / "generic.md"
PROFILE_TEMPLATE_PATH = ROOT / "profiles" / "project-profile-template.md"
DOCUMENT_TEMPLATES_DIR = ROOT / "templates"
DEFAULT_DOCUMENT_TEMPLATE_ID = "reader-specification-ru"
PROJECT_PROFILE_RELATIVE = Path(".vigers") / "profile.md"
PROFILE_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
DOCUMENT_TEMPLATE_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
WORKING_PROJECTION_POLICIES = {"required", "optional", "disabled"}
PROJECTION_EVIDENCE_KINDS = {"local_file", "external_readback"}
PREFERENCES_SCHEMA = 1
AUTOMATION_TIMING_POLICIES = {"enabled", "disabled"}
TIMING_PROJECTION_POLICIES = {"none", "task-note"}
PROGRESS_PROJECTION_POLICIES = {"none", "checklist"}
TIMING_HISTORY_POLICIES = {"none", "passport"}
STATE_PROJECTION_POLICIES = {"none", "project"}
PROFILE_INHERIT = "inherit"
TASK_MANAGER_RE = re.compile(r"^(?:none|[a-z][a-z0-9_-]{0,63})$")
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
ROLE_SPECIFIC_AGENT_REFERENCES = {
    "system-analyst": (
        "references/diagram-contract.md",
        "references/reader-projection-contract.md",
    ),
    "solution-architect": (
        "references/diagram-contract.md",
        "references/reader-projection-contract.md",
    ),
    "spec-editor": (
        "references/diagram-contract.md",
        "references/reader-projection-contract.md",
    ),
    "spec-reviewer": (
        "references/diagram-contract.md",
        "references/reader-projection-contract.md",
    ),
}
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
    "evals/prompt-cookbook/diagram-complexity-barrier.json",
    "evals/prompt-cookbook/diagram-render-lifecycle-barrier.json",
    "evals/prompt-cookbook/reader-projection-barrier.json",
    "evals/prompt-cookbook/user-journey-screen-context-barrier.json",
    "evals/prompt-cookbook/acceptance-verification-context-barrier.json",
    "evals/prompt-cookbook/standard-combined-final-review.json",
    "evals/prompt-cookbook/high-layered-review.json",
    "evals/prompt-cookbook/nonsemantic-change-no-rereview.json",
    "evals/prompt-cookbook/targeted-remediation-preserves-coverage.json",
    "evals/prompt-cookbook/risk-first-batched-convergence.json",
    "evals/prompt-cookbook/execution-economy-terminal-green.json",
    "evals/prompt-cookbook/legacy-transition-authority.json",
    "evals/prompt-cookbook/human-only-timing-boundary.json",
    "evals/prompt-cookbook/native-simplicity-with-control.json",
    "evals/prompt-cookbook/process-yagni-no-new-gate.json",
    "evals/prompt-cookbook/bounded-recovery-frozen-case.json",
)
PUBLIC_FORBIDDEN_MARKERS = tuple(
    "".join(parts) for parts in (("R", "TL"), ("H", "ÆZE"), ("HA", "EZE"))
)
HOME_PATH_MARKERS = tuple("".join(parts) for parts in (("/", "Users/"), ("/", "home/")))


class PipelineError(RuntimeError):
    """Profile discovery or structural validation failure."""


@dataclass(frozen=True)
class RecommendedDocumentTemplate:
    """One optional, overridable document-template recommendation."""

    template_id: str
    template_path: Path
    source: str


@dataclass(frozen=True)
class ExecutionPreferences:
    """Effective optional telemetry and personal task-manager capabilities."""

    automation_timing: str
    timing_model: str
    progress_tracking: str
    task_manager: str
    timing_projection: str
    timing_history: str
    timing_calendar: str
    deferred_state: str
    state_projection: str
    progress_projection: str
    source: str

    def as_dict(self) -> dict[str, str | int]:
        return {
            "schema": PREFERENCES_SCHEMA,
            "automation_timing": self.automation_timing,
            "timing_model": self.timing_model,
            "progress_tracking": self.progress_tracking,
            "task_manager": self.task_manager,
            "timing_projection": self.timing_projection,
            "timing_history": self.timing_history,
            "timing_calendar": self.timing_calendar,
            "deferred_state": self.deferred_state,
            "state_projection": self.state_projection,
            "progress_projection": self.progress_projection,
            "history_scope": "project-profile",
            "source": self.source,
        }


@dataclass(frozen=True)
class ProfileSelection:
    profile_id: str
    profile_path: Path
    project_root: Path | None
    source: str
    planning_anchors: tuple[str, ...]
    working_projection: str
    execution_preferences: ExecutionPreferences
    document_contract: dict[str, object] | None
    recommended_document_template: RecommendedDocumentTemplate | None


DEFAULT_EXECUTION_PREFERENCES = ExecutionPreferences(
    automation_timing="disabled",
    timing_model="disabled",
    progress_tracking="fine",
    task_manager="none",
    timing_projection="none",
    timing_history="none",
    timing_calendar="disabled",
    deferred_state="disabled",
    state_projection="none",
    progress_projection="none",
    source="package-default",
)


def common_preferences_path() -> Path:
    """Return the optional user-owned common Vigers preferences path."""
    override = os.environ.get("VIGERS_PREFERENCES")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".config" / "vigers" / "preferences.json"


def validate_common_preferences(payload: object, source: Path) -> ExecutionPreferences:
    """Validate one provider-neutral common preferences file."""
    if not isinstance(payload, dict) or payload.get("schema") != PREFERENCES_SCHEMA:
        raise PipelineError(f"{source}: preferences schema must be {PREFERENCES_SCHEMA}")
    automation_timing = payload.get("automation_timing")
    timing_model = payload.get("timing_model", "disabled")
    progress_tracking = payload.get("progress_tracking")
    task_manager = payload.get("task_manager")
    timing_projection = payload.get("timing_projection")
    timing_history = payload.get("timing_history", "none")
    timing_calendar = payload.get("timing_calendar", "disabled")
    deferred_state = payload.get("deferred_state", "disabled")
    state_projection = payload.get("state_projection", "none")
    progress_projection = payload.get("progress_projection")
    if automation_timing not in AUTOMATION_TIMING_POLICIES:
        raise PipelineError(f"{source}: invalid automation_timing")
    if timing_model not in AUTOMATION_TIMING_POLICIES:
        raise PipelineError(f"{source}: invalid timing_model")
    if progress_tracking not in TRACKING_POLICIES:
        raise PipelineError(f"{source}: invalid progress_tracking")
    if not isinstance(task_manager, str) or not TASK_MANAGER_RE.fullmatch(task_manager):
        raise PipelineError(f"{source}: invalid task_manager")
    if timing_projection not in TIMING_PROJECTION_POLICIES:
        raise PipelineError(f"{source}: invalid timing_projection")
    if timing_history not in TIMING_HISTORY_POLICIES:
        raise PipelineError(f"{source}: invalid timing_history")
    if timing_calendar not in AUTOMATION_TIMING_POLICIES:
        raise PipelineError(f"{source}: invalid timing_calendar")
    if deferred_state not in AUTOMATION_TIMING_POLICIES:
        raise PipelineError(f"{source}: invalid deferred_state")
    if state_projection not in STATE_PROJECTION_POLICIES:
        raise PipelineError(f"{source}: invalid state_projection")
    if progress_projection not in PROGRESS_PROJECTION_POLICIES:
        raise PipelineError(f"{source}: invalid progress_projection")
    if automation_timing == "disabled" and timing_projection != "none":
        raise PipelineError(
            f"{source}: disabled automation timing cannot have a timing projection"
        )
    if automation_timing == "disabled" and timing_model != "disabled":
        raise PipelineError(
            f"{source}: timing model requires automation timing"
        )
    if automation_timing == "disabled" and timing_history != "none":
        raise PipelineError(f"{source}: timing history requires automation timing")
    if automation_timing == "disabled" and timing_calendar != "disabled":
        raise PipelineError(f"{source}: timing calendar requires automation timing")
    if timing_calendar == "enabled" and timing_model != "enabled":
        raise PipelineError(f"{source}: timing calendar requires timing model")
    if deferred_state == "disabled" and state_projection != "none":
        raise PipelineError(f"{source}: state projection requires deferred state")
    if task_manager == "none" and (
        timing_projection != "none" or progress_projection != "none"
    ):
        raise PipelineError(
            f"{source}: task-manager projections require a configured provider"
        )
    return ExecutionPreferences(
        automation_timing=automation_timing,
        timing_model=timing_model,
        progress_tracking=progress_tracking,
        task_manager=task_manager,
        timing_projection=timing_projection,
        timing_history=timing_history,
        timing_calendar=timing_calendar,
        deferred_state=deferred_state,
        state_projection=state_projection,
        progress_projection=progress_projection,
        source=str(source),
    )


def load_common_preferences(path: Path | None = None) -> ExecutionPreferences:
    """Load optional user common preferences without making them package policy."""
    source = path or common_preferences_path()
    if not source.exists():
        return DEFAULT_EXECUTION_PREFERENCES
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PipelineError(f"{source}: invalid preferences JSON") from exc
    return validate_common_preferences(payload, source)


def resolve_execution_preferences(
    metadata: dict[str, str],
    source: Path,
    common: ExecutionPreferences,
) -> ExecutionPreferences:
    """Apply scalar project overrides to user common preferences."""
    values = common.as_dict()
    allowed = {
        "automation_timing": AUTOMATION_TIMING_POLICIES,
        "timing_model": AUTOMATION_TIMING_POLICIES,
        "progress_tracking": TRACKING_POLICIES,
        "timing_projection": TIMING_PROJECTION_POLICIES,
        "timing_history": TIMING_HISTORY_POLICIES,
        "timing_calendar": AUTOMATION_TIMING_POLICIES,
        "deferred_state": AUTOMATION_TIMING_POLICIES,
        "state_projection": STATE_PROJECTION_POLICIES,
        "progress_projection": PROGRESS_PROJECTION_POLICIES,
    }
    for field, choices in allowed.items():
        raw = metadata.get(field, PROFILE_INHERIT).strip().casefold() or PROFILE_INHERIT
        if raw != PROFILE_INHERIT and raw not in choices:
            raise PipelineError(
                f"{source}: {field} must be inherit or one of {', '.join(sorted(choices))}"
            )
        if raw != PROFILE_INHERIT:
            values[field] = raw
    task_manager = metadata.get("task_manager", PROFILE_INHERIT).strip().casefold()
    task_manager = task_manager or PROFILE_INHERIT
    if task_manager != PROFILE_INHERIT:
        if not TASK_MANAGER_RE.fullmatch(task_manager):
            raise PipelineError(f"{source}: invalid task_manager")
        values["task_manager"] = task_manager

    explicit_timing_projection = metadata.get("timing_projection", PROFILE_INHERIT)
    explicit_timing_history = metadata.get("timing_history", PROFILE_INHERIT)
    explicit_timing_calendar = metadata.get("timing_calendar", PROFILE_INHERIT)
    explicit_state_projection = metadata.get("state_projection", PROFILE_INHERIT)
    explicit_progress_projection = metadata.get("progress_projection", PROFILE_INHERIT)
    if values["automation_timing"] == "disabled":
        explicit_timing_model = metadata.get("timing_model", PROFILE_INHERIT)
        if explicit_timing_model.strip().casefold() not in {
            "",
            PROFILE_INHERIT,
            "disabled",
        }:
            raise PipelineError(
                f"{source}: timing model requires automation timing"
            )
        values["timing_model"] = "disabled"
        if explicit_timing_projection.strip().casefold() not in {"", PROFILE_INHERIT, "none"}:
            raise PipelineError(
                f"{source}: disabled automation timing cannot project timing"
            )
        values["timing_projection"] = "none"
        if explicit_timing_history.strip().casefold() not in {"", PROFILE_INHERIT, "none"}:
            raise PipelineError(f"{source}: timing history requires automation timing")
        values["timing_history"] = "none"
        if explicit_timing_calendar.strip().casefold() not in {
            "",
            PROFILE_INHERIT,
            "disabled",
        }:
            raise PipelineError(f"{source}: timing calendar requires automation timing")
        values["timing_calendar"] = "disabled"
    if values["timing_calendar"] == "enabled" and values["timing_model"] != "enabled":
        raise PipelineError(f"{source}: timing calendar requires timing model")
    if values["deferred_state"] == "disabled":
        if explicit_state_projection.strip().casefold() not in {
            "",
            PROFILE_INHERIT,
            "none",
        }:
            raise PipelineError(f"{source}: state projection requires deferred state")
        values["state_projection"] = "none"
    if values["task_manager"] == "none":
        if explicit_timing_projection.strip().casefold() not in {"", PROFILE_INHERIT, "none"}:
            raise PipelineError(f"{source}: timing projection requires a task manager")
        if explicit_progress_projection.strip().casefold() not in {
            "",
            PROFILE_INHERIT,
            "none",
        }:
            raise PipelineError(f"{source}: progress projection requires a task manager")
        values["timing_projection"] = "none"
        values["progress_projection"] = "none"
    return ExecutionPreferences(
        automation_timing=str(values["automation_timing"]),
        timing_model=str(values["timing_model"]),
        progress_tracking=str(values["progress_tracking"]),
        task_manager=str(values["task_manager"]),
        timing_projection=str(values["timing_projection"]),
        timing_history=str(values["timing_history"]),
        timing_calendar=str(values["timing_calendar"]),
        deferred_state=str(values["deferred_state"]),
        state_projection=str(values["state_projection"]),
        progress_projection=str(values["progress_projection"]),
        source=(
            f"{common.source}+{source}"
            if any(metadata.get(field, PROFILE_INHERIT).strip() not in {"", PROFILE_INHERIT}
                   for field in (
                       "automation_timing",
                       "timing_model",
                       "progress_tracking",
                       "task_manager",
                       "timing_projection",
                       "timing_history",
                       "timing_calendar",
                       "deferred_state",
                       "state_projection",
                       "progress_projection",
                   ))
            else common.source
        ),
    )


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


def package_document_template(template_id: str, *, source: str) -> RecommendedDocumentTemplate:
    """Resolve a package-owned template by stable public identifier."""
    if not DOCUMENT_TEMPLATE_ID_RE.fullmatch(template_id):
        raise PipelineError(f"invalid document template id: {template_id!r}")
    template_path = DOCUMENT_TEMPLATES_DIR / f"{template_id}.md"
    if not template_path.is_file():
        raise PipelineError(f"document template does not exist: {template_id!r}")
    return RecommendedDocumentTemplate(template_id, template_path.resolve(), source)


def resolve_recommended_document_template(
    metadata: dict[str, str],
    source: Path,
    project_root: Path | None,
) -> RecommendedDocumentTemplate | None:
    """Resolve a recommendation without turning it into a mandatory contract."""
    raw = metadata.get("recommended_document_template", "inherit").strip()
    value = raw or "inherit"
    normalized = value.casefold()
    if normalized == "none":
        return None
    if normalized == "inherit":
        return package_document_template(
            DEFAULT_DOCUMENT_TEMPLATE_ID,
            source="package-default",
        )
    if normalized.startswith("project:"):
        if project_root is None:
            raise PipelineError(
                f"{source}: project document template requires a project profile"
            )
        relative_text = value.split(":", 1)[1].strip()
        relative = Path(relative_text)
        if (
            not relative_text
            or relative.is_absolute()
            or ".." in relative.parts
            or relative.suffix.casefold() != ".md"
        ):
            raise PipelineError(f"{source}: invalid project document template path")
        template_path = (project_root / relative).resolve()
        try:
            template_path.relative_to(project_root.resolve())
        except ValueError as exc:
            raise PipelineError(
                f"{source}: project document template escapes project root"
            ) from exc
        if not template_path.is_file():
            raise PipelineError(
                f"{source}: project document template does not exist: {relative_text}"
            )
        return RecommendedDocumentTemplate(
            f"project:{relative.as_posix()}",
            template_path,
            "project",
        )
    return package_document_template(value, source="profile-package")


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
    # Profile syntax is validated against portable package defaults.  Live
    # user preferences are deliberately not consulted by package validation.
    resolve_execution_preferences(metadata, source, DEFAULT_EXECUTION_PREFERENCES)
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
        resolve_execution_preferences(metadata, candidate, load_common_preferences()),
        build_profile_contract(
            metadata,
            profile_id=profile_id,
            profile_text=text,
            source=candidate,
        ),
        resolve_recommended_document_template(metadata, candidate, root.resolve()),
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
        resolve_execution_preferences(
            metadata,
            GENERIC_PROFILE_PATH,
            load_common_preferences(),
        ),
        build_profile_contract(
            metadata,
            profile_id=profile_id,
            profile_text=generic_text,
            source=GENERIC_PROFILE_PATH,
        ),
        resolve_recommended_document_template(metadata, GENERIC_PROFILE_PATH, None),
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
            resolve_execution_preferences(
                metadata,
                GENERIC_PROFILE_PATH,
                load_common_preferences(),
            ),
            build_profile_contract(
                metadata,
                profile_id=profile_id,
                profile_text=text,
                source=GENERIC_PROFILE_PATH,
            ),
            resolve_recommended_document_template(metadata, GENERIC_PROFILE_PATH, None),
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


def display_document_template_file(
    selection: ProfileSelection,
    template: RecommendedDocumentTemplate,
) -> str:
    """Render a portable package path or a project-relative template path."""
    try:
        return str(template.template_path.relative_to(ROOT.resolve()))
    except ValueError:
        if selection.project_root is None:
            raise PipelineError("document template is outside the package and project")
        try:
            return str(template.template_path.relative_to(selection.project_root.resolve()))
        except ValueError as exc:
            raise PipelineError("document template escapes selected project") from exc


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
            expected_references = (
                (*REQUIRED_AGENT_REFERENCES, *ROLE_SPECIFIC_AGENT_REFERENCES.get(contract, ()))
                if contract == "planner"
                else (f"agents/contracts/{contract}.md", "contract_inputs")
            )
            for reference in expected_references:
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
            expected_references = (
                (*REQUIRED_AGENT_REFERENCES, *ROLE_SPECIFIC_AGENT_REFERENCES.get(contract, ()))
                if contract == "planner"
                else (f"agents/contracts/{contract}.md", "contract_inputs")
            )
            for reference in expected_references:
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
        "references/runtime-preferences.md",
        "references/automation-timing.md",
        "references/convergence-contract.md",
        "references/bounded-recovery.md",
        "references/reader-projection-contract.md",
        "templates/reader-specification-ru.md",
        "scripts/mode_decision.py",
        "scripts/planning_case.py",
        "scripts/case_pipeline.py",
        "scripts/timing_model.py",
        "scripts/timing_calendar.py",
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
            "{baseDir}/references/bounded-recovery.md",
            "{baseDir}/references/reader-projection-contract.md",
            "{baseDir}/references/runtime-preferences.md",
            "{baseDir}/references/automation-timing.md",
            "{baseDir}/evals/prompt-cookbook/convergence-closed-coverage.json",
            "{baseDir}/evals/prompt-cookbook/early-working-projection.json",
            "{baseDir}/evals/prompt-cookbook/live-checklist-completion-barrier.json",
            "{baseDir}/evals/prompt-cookbook/profile-owned-working-projection.json",
            "{baseDir}/evals/prompt-cookbook/user-story-format-barrier.json",
            "{baseDir}/evals/prompt-cookbook/traceability-link-barrier.json",
            "{baseDir}/evals/prompt-cookbook/reader-projection-barrier.json",
            "{baseDir}/evals/prompt-cookbook/user-journey-screen-context-barrier.json",
            "{baseDir}/evals/prompt-cookbook/acceptance-verification-context-barrier.json",
            "{baseDir}/evals/prompt-cookbook/human-only-timing-boundary.json",
            "{baseDir}/evals/prompt-cookbook/targeted-remediation-preserves-coverage.json",
            "{baseDir}/evals/prompt-cookbook/risk-first-batched-convergence.json",
            "{baseDir}/evals/prompt-cookbook/execution-economy-terminal-green.json",
            "{baseDir}/evals/prompt-cookbook/bounded-recovery-frozen-case.json",
            "{baseDir}/scripts/spec_pipeline.py",
            "{baseDir}/scripts/case_pipeline.py",
            "{baseDir}/scripts/timing_model.py",
            "{baseDir}/scripts/timing_calendar.py",
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
        "--change-scope",
        choices=sorted(CHANGE_SCOPES),
        default="semantic-local",
    )
    suggest_parser.add_argument("--public-contract", action="store_true")
    suggest_parser.add_argument("--data-migration", action="store_true")
    suggest_parser.add_argument("--security-or-permissions", action="store_true")
    suggest_parser.add_argument("--cross-service", action="store_true")
    suggest_parser.add_argument("--irreversible", action="store_true")
    suggest_parser.add_argument("--compliance", action="store_true")
    suggest_parser.add_argument(
        "--requested-assurance",
        choices=sorted(ASSURANCE_LEVELS),
    )
    suggest_parser.add_argument(
        "--requested-tracking",
        choices=sorted(TRACKING_POLICIES),
    )
    suggest_parser.add_argument(
        "--requested-projection-sync",
        choices=sorted(PROJECTION_SYNC_POLICIES),
    )
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
            template = selection.recommended_document_template
            payload = {
                "profile_id": selection.profile_id,
                "profile_file": display_profile_file(selection),
                "profile_source": selection.source,
                "project_root": (
                    str(selection.project_root) if selection.project_root is not None else None
                ),
                "planning_anchors": list(selection.planning_anchors),
                "working_projection": selection.working_projection,
                "execution_preferences": selection.execution_preferences.as_dict(),
                "document_contract": selection.document_contract,
                "recommended_document_template": (
                    {
                        "id": template.template_id,
                        "file": display_document_template_file(selection, template),
                        "source": template.source,
                    }
                    if template is not None
                    else None
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
                change_scope=args.change_scope,
                public_contract=args.public_contract,
                data_migration=args.data_migration,
                security_or_permissions=args.security_or_permissions,
                cross_service=args.cross_service,
                irreversible=args.irreversible,
                compliance=args.compliance,
                requested_assurance=args.requested_assurance,
                requested_tracking=(
                    args.requested_tracking
                    if args.requested_tracking is not None
                    else selection.execution_preferences.progress_tracking
                ),
                requested_projection_sync=args.requested_projection_sync,
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
