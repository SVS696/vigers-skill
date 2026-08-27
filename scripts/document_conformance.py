#!/usr/bin/env python3
"""Machine-readable project document contracts for Vigers outputs."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any


CONTRACT_SCHEMA = 1
CHECK_TARGETS = {"draft", "working_projection"}
TOC_POLICIES = {"obsidian-h2-exact"}
SEPARATOR_POLICIES = {"optional", "required"}
USER_STORY_POLICIES = {"numbered-role-goal-value"}
USER_STORY_TITLE_SEPARATORS = {".", ":"}
TRACEABILITY_POLICIES = {"semantic-id-links"}
TRACEABILITY_LINK_STYLES = {"obsidian-heading-exact"}
READER_PROJECTION_POLICIES = {"required"}
READER_NAVIGATION_POLICIES = {"required"}
READER_SUMMARY_POLICIES = {"problem-goal-solution"}
COMPONENT_OWNERSHIP_POLICIES = {"separated-summary"}
COMPONENT_DETAIL_LINK_POLICIES = {"described-owner-specific"}
READER_MAP_LAYOUT_POLICIES = {"structured-lists"}
PUBLIC_HISTORY_POLICIES = {"semantic-releases-only"}
PROSE_LAYOUT_POLICIES = {"semantic-paragraph-one-line", "unconstrained"}
SEMANTIC_REFERENCE_POLICIES = {"exact-heading-links"}
TRACEABILITY_DENSITIES = {"direct-edges"}
ACCEPTANCE_FOCI = {"observable-behavior"}
DOD_FOCI = {"acceptance-readiness"}
DEVELOPER_CHECK_POLICIES = {"omit-unless-normative"}
USER_JOURNEY_CONTEXT_POLICIES = {"screen-on-entry-and-evidenced-navigation"}
UI_FIELD_NAMING_POLICIES = {"visible-label-then-technical-id"}
DIAGRAM_WORKING_SOURCES = {"inline-mermaid", "inline-plantuml", "external-source"}
DIAGRAM_QA_RENDERS = {
    "target-native",
    "ephemeral-render",
    "target-native-with-ephemeral-fallback",
}
DIAGRAM_QA_ARTIFACT_POLICIES = {"none", "ephemeral"}
DIAGRAM_PUBLICATION_GATES = {"none", "explicit-publication"}
DIAGRAM_PUBLICATION_RENDERS = {"none", "target-native", "png", "svg"}
DIAGRAM_PUBLICATION_SOURCES = {"none", "inline", "attachment"}
H2_RE = re.compile(r"^##(?!#)\s+(.+?)\s*$")
H3_RE = re.compile(r"^###(?!#)\s+(.+?)\s*$")
ATX_HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*$")
OBSIDIAN_TOC_LINK_RE = re.compile(r"\[\[#([^\]|]+)(?:\|[^\]]+)?\]\]")
OBSIDIAN_HEADING_LINK_RE = re.compile(
    r"\[\[#(?P<target>[^\]\n|]+?)(?:(?P<separator>\\?\|)(?P<alias>[^\]\n]+?))?\]\]"
)


class DocumentContractError(RuntimeError):
    """Invalid project-owned document contract."""


def _csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _pipe_list(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split("|") if item.strip())


def build_profile_contract(
    metadata: dict[str, str],
    *,
    profile_id: str,
    profile_text: str,
    source: Path,
) -> dict[str, Any] | None:
    """Build a validated contract from scalar project-profile frontmatter."""
    field_names = {
        "document_checks",
        "document_required_headings",
        "document_toc",
        "document_toc_heading",
        "document_toc_separators",
        "document_user_story_policy",
        "document_user_story_heading",
        "document_user_story_id_prefix",
        "document_user_story_title_separator",
        "document_user_story_role_label",
        "document_user_story_goal_label",
        "document_user_story_value_label",
        "document_traceability_policy",
        "document_traceability_heading",
        "document_traceability_link_style",
        "document_traceability_id_prefixes",
        "document_reader_projection",
        "document_public_id_prefixes",
        "document_internal_id_prefixes",
        "document_semantic_references",
        "document_traceability_density",
        "document_acceptance_focus",
        "document_dod_focus",
        "document_developer_checks",
        "document_prose_language",
        "document_prose_layout",
        "document_reader_navigation",
        "document_reader_summary_policy",
        "document_reader_summary_heading",
        "document_reader_summary_parts",
        "document_component_ownership_policy",
        "document_component_ownership_heading",
        "document_component_owners",
        "document_component_detail_links",
        "document_reader_map_layout",
        "document_public_history_policy",
        "document_public_history_heading",
        "document_forbidden_reader_headings",
        "document_forbidden_reader_phrases",
        "document_user_journey_context",
        "document_ui_field_naming",
        "document_diagram_working_source",
        "document_diagram_qa_render",
        "document_diagram_qa_artifacts",
        "document_diagram_publication_gate",
        "document_diagram_publication_render",
        "document_diagram_publication_source",
    }
    if not any(metadata.get(field, "").strip() for field in field_names):
        return None

    checks = _csv(metadata.get("document_checks", ""))
    required_headings = _csv(metadata.get("document_required_headings", ""))
    toc_policy = metadata.get("document_toc", "").strip().casefold()
    toc_heading = metadata.get("document_toc_heading", "Оглавление").strip()
    separators = metadata.get("document_toc_separators", "optional").strip().casefold()
    contract: dict[str, Any] = {
        "schema": CONTRACT_SCHEMA,
        "profile_id": profile_id,
        "profile_sha256": hashlib.sha256(profile_text.encode("utf-8")).hexdigest(),
        "checks": list(checks),
        "required_headings": list(required_headings),
        "toc": {
            "policy": toc_policy,
            "heading": toc_heading,
            "separators": separators,
        },
    }
    user_story_fields = {
        "policy": metadata.get("document_user_story_policy", "").strip().casefold(),
        "heading": metadata.get("document_user_story_heading", "").strip(),
        "id_prefix": metadata.get("document_user_story_id_prefix", "").strip(),
        "title_separator": metadata.get("document_user_story_title_separator", "").strip(),
        "role_label": metadata.get("document_user_story_role_label", "").strip(),
        "goal_label": metadata.get("document_user_story_goal_label", "").strip(),
        "value_label": metadata.get("document_user_story_value_label", "").strip(),
    }
    if any(user_story_fields.values()):
        contract["user_story"] = user_story_fields
    traceability_fields: dict[str, Any] = {
        "policy": metadata.get("document_traceability_policy", "").strip().casefold(),
        "heading": metadata.get("document_traceability_heading", "").strip(),
        "link_style": metadata.get("document_traceability_link_style", "").strip().casefold(),
        "id_prefixes": list(_csv(metadata.get("document_traceability_id_prefixes", ""))),
    }
    if any(traceability_fields.values()):
        contract["traceability"] = traceability_fields
    reader_projection_policy = metadata.get("document_reader_projection", "").strip().casefold()
    prose_layout = metadata.get("document_prose_layout", "").strip().casefold()
    if not prose_layout and reader_projection_policy == "required":
        prose_layout = "semantic-paragraph-one-line"
    reader_projection_fields: dict[str, Any] = {
        "policy": reader_projection_policy,
        "public_id_prefixes": list(_csv(metadata.get("document_public_id_prefixes", ""))),
        "internal_id_prefixes": list(_csv(metadata.get("document_internal_id_prefixes", ""))),
        "semantic_references": metadata.get("document_semantic_references", "").strip().casefold(),
        "traceability_density": metadata.get("document_traceability_density", "").strip().casefold(),
        "acceptance_focus": metadata.get("document_acceptance_focus", "").strip().casefold(),
        "dod_focus": metadata.get("document_dod_focus", "").strip().casefold(),
        "developer_checks": metadata.get("document_developer_checks", "").strip().casefold(),
        "prose_language": metadata.get("document_prose_language", "").strip(),
        "prose_layout": prose_layout,
    }
    if any(reader_projection_fields.values()):
        contract["reader_projection"] = reader_projection_fields
    reader_navigation_fields: dict[str, Any] = {
        "policy": metadata.get("document_reader_navigation", "").strip().casefold(),
        "summary_policy": metadata.get("document_reader_summary_policy", "")
        .strip()
        .casefold(),
        "summary_heading": metadata.get("document_reader_summary_heading", "").strip(),
        "summary_parts": list(_csv(metadata.get("document_reader_summary_parts", ""))),
        "ownership_policy": metadata.get("document_component_ownership_policy", "")
        .strip()
        .casefold(),
        "ownership_heading": metadata.get(
            "document_component_ownership_heading", ""
        ).strip(),
        "owners": list(_csv(metadata.get("document_component_owners", ""))),
        "ownership_detail_links": metadata.get(
            "document_component_detail_links", ""
        )
        .strip()
        .casefold(),
        "map_layout": metadata.get("document_reader_map_layout", "")
        .strip()
        .casefold(),
        "history_policy": metadata.get("document_public_history_policy", "")
        .strip()
        .casefold(),
        "history_heading": metadata.get("document_public_history_heading", "").strip(),
        "forbidden_headings": list(
            _csv(metadata.get("document_forbidden_reader_headings", ""))
        ),
        "forbidden_phrases": list(
            _pipe_list(metadata.get("document_forbidden_reader_phrases", ""))
        ),
    }
    if any(reader_navigation_fields.values()):
        contract["reader_navigation"] = reader_navigation_fields
    user_journey_fields = {
        "context": metadata.get("document_user_journey_context", "")
        .strip()
        .casefold(),
        "ui_field_naming": metadata.get("document_ui_field_naming", "")
        .strip()
        .casefold(),
    }
    if any(user_journey_fields.values()):
        contract["user_journey"] = user_journey_fields
    diagram_delivery_fields = {
        "working_source": metadata.get("document_diagram_working_source", "")
        .strip()
        .casefold(),
        "qa_render": metadata.get("document_diagram_qa_render", "").strip().casefold(),
        "qa_artifacts": metadata.get("document_diagram_qa_artifacts", "")
        .strip()
        .casefold(),
        "publication_gate": metadata.get("document_diagram_publication_gate", "")
        .strip()
        .casefold(),
        "publication_render": metadata.get("document_diagram_publication_render", "")
        .strip()
        .casefold(),
        "publication_source": metadata.get("document_diagram_publication_source", "")
        .strip()
        .casefold(),
    }
    if any(diagram_delivery_fields.values()):
        contract["diagram_delivery"] = diagram_delivery_fields
    errors = validate_contract(contract)
    if errors:
        raise DocumentContractError(f"{source}: " + "; ".join(errors))
    return contract


def validate_contract(payload: Any) -> list[str]:
    """Validate the pinned JSON-compatible document contract."""
    errors: list[str] = []
    if not isinstance(payload, dict) or payload.get("schema") != CONTRACT_SCHEMA:
        return ["document contract has unsupported schema"]
    if not isinstance(payload.get("profile_id"), str) or not payload["profile_id"].strip():
        errors.append("document contract has no profile_id")
    profile_hash = payload.get("profile_sha256")
    if not isinstance(profile_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", profile_hash):
        errors.append("document contract has invalid profile_sha256")

    checks = payload.get("checks")
    if not isinstance(checks, list) or not checks:
        errors.append("document contract checks must be a non-empty array")
    elif not all(isinstance(item, str) and item in CHECK_TARGETS for item in checks):
        errors.append("document contract has an unsupported check target")
    elif len(checks) != len(set(checks)):
        errors.append("document contract has duplicate check targets")

    headings = payload.get("required_headings")
    if not isinstance(headings, list) or not headings:
        errors.append("document contract required_headings must be a non-empty array")
    elif not all(isinstance(item, str) and item.strip() for item in headings):
        errors.append("document contract has an invalid required heading")
    elif len(headings) != len(set(headings)):
        errors.append("document contract has duplicate required headings")

    toc = payload.get("toc")
    if not isinstance(toc, dict):
        errors.append("document contract toc must be an object")
    else:
        if toc.get("policy") not in TOC_POLICIES:
            errors.append("document contract has an unsupported toc policy")
        if not isinstance(toc.get("heading"), str) or not toc["heading"].strip():
            errors.append("document contract has no toc heading")
        if toc.get("separators") not in SEPARATOR_POLICIES:
            errors.append("document contract has an unsupported toc separator policy")
        if isinstance(headings, list) and toc.get("heading") not in headings:
            errors.append("toc heading must be included in required_headings")

    user_story = payload.get("user_story")
    if user_story is not None:
        if not isinstance(user_story, dict):
            errors.append("document contract user_story must be an object")
        else:
            if user_story.get("policy") not in USER_STORY_POLICIES:
                errors.append("document contract has an unsupported user story policy")
            heading = user_story.get("heading")
            if not isinstance(heading, str) or not heading.strip():
                errors.append("document contract has no user story heading")
            elif isinstance(headings, list) and heading not in headings:
                errors.append("user story heading must be included in required_headings")
            prefix = user_story.get("id_prefix")
            if not isinstance(prefix, str) or not re.fullmatch(r"[A-Z][A-Z0-9]*", prefix):
                errors.append("document contract has an invalid user story id_prefix")
            if user_story.get("title_separator") not in USER_STORY_TITLE_SEPARATORS:
                errors.append("document contract has an unsupported user story title separator")
            for field in ("role_label", "goal_label", "value_label"):
                value = user_story.get(field)
                if not isinstance(value, str) or not value.strip():
                    errors.append(f"document contract has no user story {field}")

    traceability = payload.get("traceability")
    if traceability is not None:
        if not isinstance(traceability, dict):
            errors.append("document contract traceability must be an object")
        else:
            if traceability.get("policy") not in TRACEABILITY_POLICIES:
                errors.append("document contract has an unsupported traceability policy")
            heading = traceability.get("heading")
            if not isinstance(heading, str) or not heading.strip():
                errors.append("document contract has no traceability heading")
            elif isinstance(headings, list) and heading not in headings:
                errors.append("traceability heading must be included in required_headings")
            if traceability.get("link_style") not in TRACEABILITY_LINK_STYLES:
                errors.append("document contract has an unsupported traceability link style")
            prefixes = traceability.get("id_prefixes")
            if not isinstance(prefixes, list) or not prefixes:
                errors.append("document contract traceability id_prefixes must be non-empty")
            elif not all(
                isinstance(item, str) and re.fullmatch(r"[A-Z][A-Z0-9]*", item)
                for item in prefixes
            ):
                errors.append("document contract has an invalid traceability id_prefix")
            elif len(prefixes) != len(set(prefixes)):
                errors.append("document contract has duplicate traceability id_prefixes")

    reader_projection = payload.get("reader_projection")
    if reader_projection is not None:
        if not isinstance(reader_projection, dict):
            errors.append("document contract reader_projection must be an object")
        else:
            if reader_projection.get("policy") not in READER_PROJECTION_POLICIES:
                errors.append("document contract has an unsupported reader projection policy")
            public_prefixes = reader_projection.get("public_id_prefixes")
            internal_prefixes = reader_projection.get("internal_id_prefixes")
            for name, prefixes in (
                ("public", public_prefixes),
                ("internal", internal_prefixes),
            ):
                if not isinstance(prefixes, list) or not prefixes:
                    errors.append(
                        f"document contract reader_projection {name}_id_prefixes must be non-empty"
                    )
                elif not all(
                    isinstance(item, str) and re.fullmatch(r"[A-Z][A-Z0-9]*", item)
                    for item in prefixes
                ):
                    errors.append(
                        f"document contract has an invalid reader_projection {name}_id_prefix"
                    )
                elif len(prefixes) != len(set(prefixes)):
                    errors.append(
                        f"document contract has duplicate reader_projection {name}_id_prefixes"
                    )
            if isinstance(public_prefixes, list) and isinstance(internal_prefixes, list):
                overlap = sorted(set(public_prefixes) & set(internal_prefixes))
                if overlap:
                    errors.append(
                        "document contract public/internal id prefixes overlap: "
                        + ", ".join(overlap)
                    )
            if reader_projection.get("semantic_references") not in SEMANTIC_REFERENCE_POLICIES:
                errors.append("document contract has an unsupported semantic reference policy")
            if reader_projection.get("traceability_density") not in TRACEABILITY_DENSITIES:
                errors.append("document contract has an unsupported traceability density")
            if reader_projection.get("acceptance_focus") not in ACCEPTANCE_FOCI:
                errors.append("document contract has an unsupported acceptance focus")
            if reader_projection.get("dod_focus") not in DOD_FOCI:
                errors.append("document contract has an unsupported DoD focus")
            if reader_projection.get("developer_checks") not in DEVELOPER_CHECK_POLICIES:
                errors.append("document contract has an unsupported developer checks policy")
            prose_language = reader_projection.get("prose_language")
            if not isinstance(prose_language, str) or not re.fullmatch(
                r"[a-z]{2}(?:-[A-Z]{2})?", prose_language
            ):
                errors.append("document contract has an invalid prose language")
            prose_layout = reader_projection.get("prose_layout")
            if prose_layout is not None and prose_layout not in PROSE_LAYOUT_POLICIES:
                errors.append("document contract has an unsupported prose layout policy")
            traceability = payload.get("traceability")
            if isinstance(traceability, dict) and isinstance(public_prefixes, list):
                unknown = sorted(set(traceability.get("id_prefixes", [])) - set(public_prefixes))
                if unknown:
                    errors.append(
                        "traceability prefixes are not public reader IDs: " + ", ".join(unknown)
                    )

    reader_navigation = payload.get("reader_navigation")
    if reader_navigation is not None:
        if not isinstance(reader_navigation, dict):
            errors.append("document contract reader_navigation must be an object")
        else:
            if reader_navigation.get("policy") not in READER_NAVIGATION_POLICIES:
                errors.append("document contract has an unsupported reader navigation policy")
            if reader_navigation.get("summary_policy") not in READER_SUMMARY_POLICIES:
                errors.append("document contract has an unsupported reader summary policy")
            if reader_navigation.get("ownership_policy") not in COMPONENT_OWNERSHIP_POLICIES:
                errors.append("document contract has an unsupported component ownership policy")
            ownership_detail_links = reader_navigation.get("ownership_detail_links")
            if (
                ownership_detail_links is not None
                and ownership_detail_links not in COMPONENT_DETAIL_LINK_POLICIES
            ):
                errors.append(
                    "document contract has an unsupported component detail link policy"
                )
            map_layout = reader_navigation.get("map_layout")
            if map_layout and map_layout not in READER_MAP_LAYOUT_POLICIES:
                errors.append("document contract has an unsupported reader map layout")
            if reader_navigation.get("history_policy") not in PUBLIC_HISTORY_POLICIES:
                errors.append("document contract has an unsupported public history policy")
            for name in ("summary_heading", "ownership_heading", "history_heading"):
                value = reader_navigation.get(name)
                if not isinstance(value, str) or not value.strip():
                    errors.append(f"document contract reader_navigation has no {name}")
                elif isinstance(headings, list) and value not in headings:
                    errors.append(
                        f"reader navigation {name} must be included in required_headings"
                    )
            summary_parts = reader_navigation.get("summary_parts")
            if not isinstance(summary_parts, list) or len(summary_parts) != 3:
                errors.append(
                    "document contract reader summary must define exactly three parts"
                )
            elif not all(isinstance(item, str) and item.strip() for item in summary_parts):
                errors.append("document contract reader summary has an invalid part")
            elif len(summary_parts) != len(set(summary_parts)):
                errors.append("document contract reader summary has duplicate parts")
            owners = reader_navigation.get("owners")
            if not isinstance(owners, list) or len(owners) < 2:
                errors.append(
                    "document contract component ownership must define at least two owners"
                )
            elif not all(isinstance(item, str) and item.strip() for item in owners):
                errors.append("document contract component ownership has an invalid owner")
            elif len(owners) != len(set(owners)):
                errors.append("document contract component ownership has duplicate owners")
            for name in ("forbidden_headings", "forbidden_phrases"):
                values = reader_navigation.get(name)
                if not isinstance(values, list) or not all(
                    isinstance(item, str) and item.strip() for item in values
                ):
                    errors.append(f"document contract reader_navigation has invalid {name}")

    user_journey = payload.get("user_journey")
    if user_journey is not None:
        if not isinstance(user_journey, dict):
            errors.append("document contract user_journey must be an object")
        else:
            if user_journey.get("context") not in USER_JOURNEY_CONTEXT_POLICIES:
                errors.append("document contract has an unsupported user journey context")
            if user_journey.get("ui_field_naming") not in UI_FIELD_NAMING_POLICIES:
                errors.append("document contract has an unsupported UI field naming policy")

    diagram_delivery = payload.get("diagram_delivery")
    if diagram_delivery is not None:
        if not isinstance(diagram_delivery, dict):
            errors.append("document contract diagram_delivery must be an object")
        else:
            required_fields = {
                "working_source",
                "qa_render",
                "qa_artifacts",
                "publication_gate",
                "publication_render",
                "publication_source",
            }
            missing = sorted(
                field for field in required_fields if not diagram_delivery.get(field)
            )
            if missing:
                errors.append(
                    "document contract diagram_delivery is incomplete: " + ", ".join(missing)
                )
            if diagram_delivery.get("working_source") not in DIAGRAM_WORKING_SOURCES:
                errors.append("document contract has an unsupported diagram working source")
            qa_render = diagram_delivery.get("qa_render")
            qa_artifacts = diagram_delivery.get("qa_artifacts")
            if qa_render not in DIAGRAM_QA_RENDERS:
                errors.append("document contract has an unsupported diagram QA render")
            if qa_artifacts not in DIAGRAM_QA_ARTIFACT_POLICIES:
                errors.append("document contract has an unsupported diagram QA artifact policy")
            if qa_render == "target-native" and qa_artifacts != "none":
                errors.append("target-native diagram QA must not persist QA artifacts")
            if qa_render in {
                "ephemeral-render",
                "target-native-with-ephemeral-fallback",
            } and qa_artifacts != "ephemeral":
                errors.append("diagram QA fallback requires ephemeral artifacts")
            publication_gate = diagram_delivery.get("publication_gate")
            publication_render = diagram_delivery.get("publication_render")
            publication_source = diagram_delivery.get("publication_source")
            if publication_gate not in DIAGRAM_PUBLICATION_GATES:
                errors.append("document contract has an unsupported diagram publication gate")
            if publication_render not in DIAGRAM_PUBLICATION_RENDERS:
                errors.append("document contract has an unsupported diagram publication render")
            if publication_source not in DIAGRAM_PUBLICATION_SOURCES:
                errors.append("document contract has an unsupported diagram publication source")
            if publication_gate == "none" and (
                publication_render != "none" or publication_source != "none"
            ):
                errors.append("diagram publication disabled but publication artifacts are enabled")
            if publication_gate == "explicit-publication" and (
                publication_render == "none" or publication_source == "none"
            ):
                errors.append("explicit diagram publication requires render and source policies")
    return errors


def _heading_text(raw: str) -> str:
    return re.sub(r"\s+#+\s*$", "", raw).strip()


def markdown_h2(lines: list[str]) -> list[tuple[str, int]]:
    """Return H2 headings outside fenced code blocks as (text, zero-based line)."""
    headings: list[tuple[str, int]] = []
    fence: str | None = None
    for index, line in enumerate(lines):
        stripped = line.lstrip()
        marker = stripped[:3]
        if marker in {"```", "~~~"}:
            if fence is None:
                fence = marker
            elif fence == marker:
                fence = None
            continue
        if fence is not None:
            continue
        match = H2_RE.match(line)
        if match:
            headings.append((_heading_text(match.group(1)), index))
    return headings


def _previous_nonblank(lines: list[str], before: int) -> str | None:
    for index in range(before - 1, -1, -1):
        if lines[index].strip():
            return lines[index].strip()
    return None


def _outside_fences(lines: list[str]) -> list[bool]:
    outside: list[bool] = []
    fence: str | None = None
    for line in lines:
        stripped = line.lstrip()
        marker = stripped[:3]
        if marker in {"```", "~~~"}:
            outside.append(False)
            if fence is None:
                fence = marker
            elif fence == marker:
                fence = None
            continue
        outside.append(fence is None)
    return outside


def _paragraphs(lines: list[str], outside: list[bool]) -> list[str]:
    paragraphs: list[str] = []
    current: list[str] = []
    for line, is_outside in zip(lines, outside, strict=True):
        stripped = line.strip()
        if not is_outside or not stripped:
            if current:
                paragraphs.append(" ".join(current))
                current = []
            continue
        current.append(stripped)
    if current:
        paragraphs.append(" ".join(current))
    return paragraphs


def _validate_user_story_section(
    lines: list[str],
    headings: list[tuple[str, int]],
    contract: dict[str, Any],
    *,
    label: str,
) -> list[str]:
    policy = contract["user_story"]
    heading = policy["heading"]
    section_matches = [(name, index) for name, index in headings if name == heading]
    if len(section_matches) != 1:
        return []

    section_start = section_matches[0][1] + 1
    section_end = next(
        (index for _name, index in headings if index >= section_start),
        len(lines),
    )
    section_lines = lines[section_start:section_end]
    outside = _outside_fences(section_lines)
    h3: list[tuple[str, int]] = []
    for index, (line, is_outside) in enumerate(zip(section_lines, outside, strict=True)):
        if not is_outside:
            continue
        match = H3_RE.match(line)
        if match:
            h3.append((_heading_text(match.group(1)), index))

    prefix = policy["id_prefix"]
    separator = policy["title_separator"]
    story_heading_re = re.compile(
        rf"^{re.escape(prefix)}-([1-9][0-9]*){re.escape(separator)}\s+(.+)$"
    )
    stories: list[tuple[int, int]] = []
    errors: list[str] = []
    for raw, index in h3:
        match = story_heading_re.fullmatch(raw)
        if not match:
            errors.append(
                f"{label}: unexpected H3 in {heading!r}: {raw!r}; "
                f"expected '{prefix}-N{separator} <title>'"
            )
            continue
        stories.append((int(match.group(1)), index))

    if not stories:
        errors.append(
            f"{label}: {heading!r} must contain at least one "
            f"'### {prefix}-N{separator} <title>' entry"
        )
        return errors

    numbers = [number for number, _index in stories]
    expected_numbers = list(range(1, len(numbers) + 1))
    if numbers != expected_numbers:
        errors.append(
            f"{label}: {heading!r} IDs must be unique and sequential from "
            f"{prefix}-1 (found: {', '.join(f'{prefix}-{number}' for number in numbers)})"
        )

    role_label = re.escape(policy["role_label"])
    goal_label = re.escape(policy["goal_label"])
    value_label = re.escape(policy["value_label"])
    statement_re = re.compile(
        rf"^\*\*{role_label}\s+.+?\*\*,\s+{goal_label}\s+.+?,\s+{value_label}\s+.+\.$"
    )
    h3_indexes = [index for _raw, index in h3]
    for number, start in stories:
        end = next((index for index in h3_indexes if index > start), len(section_lines))
        body_lines = section_lines[start + 1 : end]
        body_outside = outside[start + 1 : end]
        statements = [
            paragraph
            for paragraph in _paragraphs(body_lines, body_outside)
            if statement_re.fullmatch(paragraph)
        ]
        if len(statements) != 1:
            errors.append(
                f"{label}: {prefix}-{number} must contain exactly one "
                f"'**{policy['role_label']} <role>**, {policy['goal_label']} <goal>, "
                f"{policy['value_label']} <value>.' paragraph"
            )
    return errors


def _semantic_id_body(prefixes: list[str]) -> str:
    prefix_group = "|".join(re.escape(prefix) for prefix in sorted(prefixes, key=len, reverse=True))
    return rf"(?:{prefix_group})(?:-[A-Z][A-Z0-9]*)*-\d+"


def _semantic_id_re(prefixes: list[str], *, full: bool = False) -> re.Pattern[str]:
    body = _semantic_id_body(prefixes)
    return re.compile(rf"^{body}$" if full else rf"(?<![A-Z0-9-]){body}(?![A-Z0-9-])")


def _all_atx_headings(lines: list[str]) -> dict[str, list[int]]:
    headings: dict[str, list[int]] = {}
    outside = _outside_fences(lines)
    for index, (line, is_outside) in enumerate(zip(lines, outside, strict=True)):
        if not is_outside:
            continue
        match = ATX_HEADING_RE.match(line)
        if match:
            headings.setdefault(_heading_text(match.group(1)), []).append(index)
    return headings


def _validate_traceability_section(
    lines: list[str],
    headings: list[tuple[str, int]],
    contract: dict[str, Any],
    *,
    label: str,
) -> list[str]:
    policy = contract["traceability"]
    heading = policy["heading"]
    section_matches = [(name, index) for name, index in headings if name == heading]
    if len(section_matches) != 1:
        return []

    section_start = section_matches[0][1] + 1
    section_end = next(
        (index for _name, index in headings if index >= section_start),
        len(lines),
    )
    section_lines = lines[section_start:section_end]
    outside = _outside_fences(section_lines)
    semantic_re = _semantic_id_re(policy["id_prefixes"])
    semantic_full_re = _semantic_id_re(policy["id_prefixes"], full=True)
    semantic_body = _semantic_id_body(policy["id_prefixes"])
    compression_re = re.compile(
        rf"(?<![A-Z0-9-]){semantic_body}(?:\s*(?:/|–|—|-)\s*\d+)+"
    )
    document_headings = _all_atx_headings(lines)
    errors: list[str] = []
    linked_ids: list[str] = []
    plain_ids: list[str] = []
    compressed_refs: list[str] = []

    for line, is_outside in zip(section_lines, outside, strict=True):
        if not is_outside:
            continue
        masked = list(line)
        for match in OBSIDIAN_HEADING_LINK_RE.finditer(line):
            target = match.group("target").strip()
            alias = (match.group("alias") or "").strip()
            target_id_match = semantic_re.match(target)
            target_id = target_id_match.group(0) if target_id_match and target_id_match.start() == 0 else None
            alias_is_id = bool(semantic_full_re.fullmatch(alias))
            if target_id or alias_is_id:
                semantic_id = alias if alias_is_id else target_id
                assert semantic_id is not None
                linked_ids.append(semantic_id)
                if alias != semantic_id:
                    errors.append(
                        f"{label}: trace link to {target!r} must use exact semantic ID "
                        f"{semantic_id!r} as alias"
                    )
                if target_id != semantic_id:
                    errors.append(
                        f"{label}: trace link alias {semantic_id!r} points to a heading "
                        "with a different semantic ID"
                    )
                target_lines = document_headings.get(target, [])
                if len(target_lines) != 1:
                    state = "missing" if not target_lines else "ambiguous"
                    errors.append(
                        f"{label}: trace link {semantic_id!r} has {state} exact heading target "
                        f"{target!r}"
                    )
                if line.lstrip().startswith("|") and match.group("separator") == "|":
                    errors.append(
                        f"{label}: trace table link {semantic_id!r} must escape its alias "
                        "separator as '\\|'"
                    )
            for index in range(match.start(), match.end()):
                masked[index] = " "

        remaining = "".join(masked)
        compressed_refs.extend(match.group(0) for match in compression_re.finditer(remaining))
        plain_ids.extend(match.group(0) for match in semantic_re.finditer(remaining))

    if compressed_refs:
        errors.append(
            f"{label}: traceability must not compress semantic ID ranges: "
            + ", ".join(dict.fromkeys(compressed_refs))
        )
    if plain_ids:
        errors.append(
            f"{label}: every semantic ID in {heading!r} must be an individual internal link: "
            + ", ".join(dict.fromkeys(plain_ids))
        )
    if not linked_ids:
        errors.append(
            f"{label}: {heading!r} must contain at least one linked semantic ID"
        )
    return errors


def _validate_reader_projection(
    lines: list[str],
    contract: dict[str, Any],
    *,
    label: str,
) -> list[str]:
    """Keep analysis-only IDs out and require navigable public references globally."""
    policy = contract["reader_projection"]
    public_prefixes = policy["public_id_prefixes"]
    internal_prefixes = policy["internal_id_prefixes"]
    public_re = _semantic_id_re(public_prefixes)
    public_full_re = _semantic_id_re(public_prefixes, full=True)
    internal_re = _semantic_id_re(internal_prefixes)
    public_body = _semantic_id_body(public_prefixes)
    compression_re = re.compile(
        rf"(?<![A-Z0-9-]){public_body}(?:\s*(?:/|–|—|-)\s*\d+)+"
    )
    document_headings = _all_atx_headings(lines)
    outside = _outside_fences(lines)
    errors: list[str] = []
    internal_ids: list[str] = []
    compressed_refs: list[str] = []
    plain_refs: list[str] = []

    for line, is_outside in zip(lines, outside, strict=True):
        if not is_outside:
            continue
        internal_ids.extend(match.group(0) for match in internal_re.finditer(line))
        masked = list(line)
        for match in OBSIDIAN_HEADING_LINK_RE.finditer(line):
            target = match.group("target").strip()
            alias = (match.group("alias") or "").strip()
            target_id_match = public_re.match(target)
            target_id = (
                target_id_match.group(0)
                if target_id_match and target_id_match.start() == 0
                else None
            )
            alias_is_id = bool(public_full_re.fullmatch(alias))
            if target_id or alias_is_id:
                semantic_id = alias if alias_is_id else target_id
                assert semantic_id is not None
                if alias != semantic_id:
                    errors.append(
                        f"{label}: semantic link to {target!r} must use exact ID "
                        f"{semantic_id!r} as alias"
                    )
                if target_id != semantic_id:
                    errors.append(
                        f"{label}: semantic link alias {semantic_id!r} points to a heading "
                        "with a different semantic ID"
                    )
                target_lines = document_headings.get(target, [])
                if len(target_lines) != 1:
                    state = "missing" if not target_lines else "ambiguous"
                    errors.append(
                        f"{label}: semantic link {semantic_id!r} has {state} exact heading "
                        f"target {target!r}"
                    )
                if line.lstrip().startswith("|") and match.group("separator") == "|":
                    errors.append(
                        f"{label}: semantic table link {semantic_id!r} must escape its alias "
                        "separator as '\\|'"
                    )
            for index in range(match.start(), match.end()):
                masked[index] = " "

        heading_match = ATX_HEADING_RE.match(line)
        if heading_match:
            heading_text = _heading_text(heading_match.group(1))
            definition = public_re.match(heading_text)
            if definition and definition.start() == 0:
                absolute_start = line.find(definition.group(0))
                for index in range(absolute_start, absolute_start + len(definition.group(0))):
                    masked[index] = " "

        remaining = "".join(masked)
        compressed_refs.extend(match.group(0) for match in compression_re.finditer(remaining))
        plain_refs.extend(match.group(0) for match in public_re.finditer(remaining))

    if internal_ids:
        errors.append(
            f"{label}: reader projection contains analysis-only semantic IDs: "
            + ", ".join(dict.fromkeys(internal_ids))
        )
    if compressed_refs:
        errors.append(
            f"{label}: semantic references must not use compressed ranges: "
            + ", ".join(dict.fromkeys(compressed_refs))
        )
    if plain_refs:
        errors.append(
            f"{label}: every public semantic reference outside its definition heading "
            "must be an exact internal link: "
            + ", ".join(dict.fromkeys(plain_refs))
        )
    if policy.get("prose_layout") == "semantic-paragraph-one-line":
        errors.extend(_validate_reader_prose_layout(lines, label=label))
    return errors


def _section_h3(
    lines: list[str],
    headings: list[tuple[str, int]],
    *,
    heading: str,
) -> list[str]:
    section_matches = [(name, index) for name, index in headings if name == heading]
    if len(section_matches) != 1:
        return []
    section_start = section_matches[0][1]
    section_end = next(
        (index for _name, index in headings if index > section_start),
        len(lines),
    )
    outside = _outside_fences(lines)
    result: list[str] = []
    for index in range(section_start + 1, section_end):
        if not outside[index]:
            continue
        match = H3_RE.match(lines[index])
        if match:
            result.append(_heading_text(match.group(1)))
    return result


def _section_h3_blocks(
    lines: list[str],
    headings: list[tuple[str, int]],
    *,
    heading: str,
) -> dict[str, list[str]]:
    """Return H3 bodies for one H2 section, excluding fenced content."""
    section_matches = [(name, index) for name, index in headings if name == heading]
    if len(section_matches) != 1:
        return {}
    section_start = section_matches[0][1]
    section_end = next(
        (index for _name, index in headings if index > section_start),
        len(lines),
    )
    outside = _outside_fences(lines)
    entries: list[tuple[str, int]] = []
    for index in range(section_start + 1, section_end):
        if not outside[index]:
            continue
        match = H3_RE.match(lines[index])
        if match:
            entries.append((_heading_text(match.group(1)), index))
    result: dict[str, list[str]] = {}
    for position, (name, start) in enumerate(entries):
        end = entries[position + 1][1] if position + 1 < len(entries) else section_end
        result[name] = [
            lines[index]
            for index in range(start + 1, end)
            if outside[index] and lines[index].strip()
        ]
    return result


def _frontmatter_lines(lines: list[str]) -> set[int]:
    result: set[int] = set()
    if not lines or lines[0].strip() != "---":
        return result
    result.add(0)
    for index in range(1, len(lines)):
        result.add(index)
        if lines[index].strip() == "---":
            break
    return result


def _validate_reader_navigation(
    lines: list[str],
    headings: list[tuple[str, int]],
    contract: dict[str, Any],
    *,
    label: str,
) -> list[str]:
    """Require a reader summary/ownership map and reject project-declared process leaks."""
    policy = contract["reader_navigation"]
    errors: list[str] = []
    for section_name, required in (
        (policy["summary_heading"], policy["summary_parts"]),
        (policy["ownership_heading"], policy["owners"]),
    ):
        actual = _section_h3(lines, headings, heading=section_name)
        missing = [item for item in required if actual.count(item) != 1]
        if missing:
            errors.append(
                f"{label}: {section_name!r} must contain exactly one H3 for: "
                + ", ".join(missing)
            )

    summary_blocks = _section_h3_blocks(
        lines, headings, heading=policy["summary_heading"]
    )
    for part in policy["summary_parts"]:
        if part in summary_blocks and not summary_blocks[part]:
            errors.append(
                f"{label}: reader summary part {part!r} must contain a concise explanation"
            )
        if policy.get("map_layout") == "structured-lists" and part in summary_blocks:
            non_list_lines = [
                line
                for line in summary_blocks[part]
                if not re.fullmatch(r"\s*(?:---+|\*\*\*+|___+)\s*", line)
                and not re.match(r"^\s*(?:[-+*]|\d+[.)])\s+", line)
            ]
            if non_list_lines:
                errors.append(
                    f"{label}: reader summary part {part!r} must use Markdown list "
                    "items instead of dense prose"
                )

    document_headings = _all_atx_headings(lines)
    ownership_blocks = _section_h3_blocks(
        lines, headings, heading=policy["ownership_heading"]
    )
    for owner in policy["owners"]:
        body = ownership_blocks.get(owner)
        if body is None:
            continue
        if not body:
            errors.append(
                f"{label}: component owner {owner!r} must describe work or state that changes are absent"
            )
            continue
        content_body = [
            line
            for line in body
            if not re.fullmatch(r"\s*(?:---+|\*\*\*+|___+)\s*", line)
        ]
        body_text = "\n".join(content_body)
        if "изменений нет" in body_text.casefold():
            if body_text.strip().casefold().rstrip(".") != "изменений нет":
                errors.append(
                    f"{label}: unchanged component owner {owner!r} must contain only "
                    "'Изменений нет.'"
                )
            continue
        if policy.get("map_layout") == "structured-lists":
            non_list_lines = [
                line
                for line in content_body
                if not re.match(r"^\s*(?:[-+*]|\d+[.)])\s+", line)
            ]
            if non_list_lines:
                errors.append(
                    f"{label}: component owner {owner!r} must use Markdown list "
                    "items instead of dense prose"
                )
        links = [
            match.group("target").strip()
            for match in OBSIDIAN_HEADING_LINK_RE.finditer(body_text)
        ]
        if not links:
            errors.append(
                f"{label}: component owner {owner!r} must link to detailed sections "
                "or state 'Изменений нет'"
            )
            continue
        dangling = [
            target for target in links if len(document_headings.get(target, [])) != 1
        ]
        if dangling:
            errors.append(
                f"{label}: component owner {owner!r} has unresolved detail links: "
                + ", ".join(dict.fromkeys(dangling))
            )
        if policy.get("ownership_detail_links") == "described-owner-specific":
            if "подробнее:" in body_text.casefold():
                errors.append(
                    f"{label}: component owner {owner!r} must describe what each detail "
                    "link contains instead of using a generic 'Подробнее:' link list"
                )
            specific_targets = [
                target
                for target in links
                if any(
                    len(lines[index]) - len(lines[index].lstrip("#")) >= 3
                    for index in document_headings.get(target, [])
                )
            ]
            if not specific_targets:
                errors.append(
                    f"{label}: component owner {owner!r} must link to at least one exact "
                    "owner-specific detail heading, not only broad H2 sections"
                )

    outside = _outside_fences(lines)
    role_labels = [*policy["owners"], "Совместно: BE + FE"]
    bold_role_re = re.compile(
        r"^\s*\*\*(?:"
        + "|".join(re.escape(role) for role in role_labels)
        + r")(?:[.:])?\*\*"
    )
    bold_role_lines = [
        index + 1
        for index, (line, is_outside) in enumerate(zip(lines, outside, strict=True))
        if is_outside and bold_role_re.match(line)
    ]
    if bold_role_lines:
        errors.append(
            f"{label}: detailed component boundaries must use ATX headings, not bold "
            "paragraph labels; lines: "
            + ", ".join(str(index) for index in bold_role_lines)
        )

    history_matches = [
        index for name, index in headings if name == policy["history_heading"]
    ]
    if len(history_matches) == 1:
        history_start = history_matches[0]
        history_end = next(
            (index for _name, index in headings if index > history_start),
            len(lines),
        )
        outside = _outside_fences(lines)
        version_row_re = re.compile(r"^\|\s*[1-9][0-9]*(?:\.[0-9]+)+\s*\|")
        if not any(
            outside[index] and version_row_re.match(lines[index].strip())
            for index in range(history_start + 1, history_end)
        ):
            errors.append(
                f"{label}: {policy['history_heading']!r} must contain a semantic version row"
            )

    all_headings = _all_atx_headings(lines)
    forbidden_heading_map = {
        item.casefold(): item for item in policy.get("forbidden_headings", [])
    }
    leaked_headings = [
        forbidden_heading_map[name.casefold()]
        for name in all_headings
        if name.casefold() in forbidden_heading_map
    ]
    if leaked_headings:
        errors.append(
            f"{label}: reader projection contains forbidden lifecycle headings: "
            + ", ".join(dict.fromkeys(leaked_headings))
        )

    forbidden_phrases = policy.get("forbidden_phrases", [])
    if forbidden_phrases:
        outside = _outside_fences(lines)
        frontmatter = _frontmatter_lines(lines)
        leaked_phrases: list[str] = []
        for index, line in enumerate(lines):
            if not outside[index] or index in frontmatter:
                continue
            folded = line.casefold()
            leaked_phrases.extend(
                phrase for phrase in forbidden_phrases if phrase.casefold() in folded
            )
        if leaked_phrases:
            errors.append(
                f"{label}: reader projection contains forbidden lifecycle phrases: "
                + ", ".join(dict.fromkeys(leaked_phrases))
            )
    return errors


def _validate_reader_prose_layout(lines: list[str], *, label: str) -> list[str]:
    """Reject editor-width hard wraps in ordinary reader-facing prose paragraphs."""
    outside = _outside_fences(lines)
    errors: list[str] = []
    current: list[tuple[int, str]] = []
    list_item_re = re.compile(r"^(?P<indent>\s*)(?:[-+*]|\d+[.)])\s+")
    structural_continuation_re = re.compile(
        r"^(?:#{1,6}\s+|>|\||```|~~~|\$\$|:::|!!!|</?[A-Za-z!]|!\[\[)"
    )
    frontmatter_lines: set[int] = set()
    if lines and lines[0].strip() == "---":
        frontmatter_lines.add(0)
        for index in range(1, len(lines)):
            frontmatter_lines.add(index)
            if lines[index].strip() == "---":
                break

    for index, line in enumerate(lines):
        if not outside[index] or index in frontmatter_lines:
            continue
        item = list_item_re.match(line)
        if item is None:
            continue
        continuation_end = index
        for cursor in range(index + 1, len(lines)):
            candidate = lines[cursor]
            if (
                not outside[cursor]
                or cursor in frontmatter_lines
                or not candidate.strip()
                or candidate.startswith(("    ", "\t"))
                or lines[cursor - 1].endswith(("  ", "\\"))
            ):
                break
            if list_item_re.match(candidate) or structural_continuation_re.match(
                candidate.lstrip()
            ):
                break
            continuation_end = cursor
        if continuation_end > index:
            errors.append(
                f"{label}: reader list item is hard-wrapped across physical lines "
                f"{index + 1}-{continuation_end + 1}; keep one prose item on one line"
            )

    def flush() -> None:
        if len(current) < 2:
            current.clear()
            return
        stripped_lines = [line.strip() for _, line in current]
        structural_patterns = (
            r"#{1,6}\s+",  # ATX heading
            r"(?:[-+*]|\d+[.)])\s+",  # list item
            r">",  # blockquote or Obsidian callout
            r"\|",  # table with a leading pipe
            r"(?:---+|\*\*\*+|___+)\s*$",  # thematic break or frontmatter fence
            r"(?:```|~~~|\$\$|:::|!!!)",  # fenced/directive blocks
            r"</?[A-Za-z!]",  # HTML block or comment
            r"\[[^]]+\]:\s+",  # link reference definition
            r"\[\^[^]]+\]:\s+",  # footnote definition
            r"!\[\[",  # Obsidian embed
        )
        is_structural = any(
            line.startswith(("    ", "\t"))
            or any(re.match(pattern, stripped) for pattern in structural_patterns)
            for (_, line), stripped in zip(current, stripped_lines, strict=True)
        )
        has_explicit_break = any(
            line.endswith("  ") or line.endswith("\\") for _, line in current[:-1]
        )
        has_setext_or_table_separator = any(
            re.fullmatch(r"\s*(?:=+|-+|:?-{3,}:?(?:\s*\|\s*:?-{3,}:?)+)\s*", line)
            for line in stripped_lines
        )
        if not is_structural and not has_explicit_break and not has_setext_or_table_separator:
            start = current[0][0] + 1
            end = current[-1][0] + 1
            errors.append(
                f"{label}: reader prose paragraph is hard-wrapped across physical lines "
                f"{start}-{end}; keep one semantic paragraph on one line"
            )
        current.clear()

    for index, (line, is_outside) in enumerate(zip(lines, outside, strict=True)):
        if not is_outside or not line.strip():
            flush()
            continue
        current.append((index, line))
    flush()
    return errors


def validate_markdown(text: str, contract: dict[str, Any], *, label: str) -> list[str]:
    """Validate one Markdown document against a pinned project contract."""
    contract_errors = validate_contract(contract)
    if contract_errors:
        return [f"{label}: {error}" for error in contract_errors]

    errors: list[str] = []
    lines = text.splitlines()
    headings = markdown_h2(lines)
    heading_names = [name for name, _ in headings]
    duplicates = sorted({name for name in heading_names if heading_names.count(name) > 1})
    if duplicates:
        errors.append(f"{label}: duplicate H2 headings: {', '.join(duplicates)}")
    missing = [name for name in contract["required_headings"] if name not in heading_names]
    if missing:
        errors.append(f"{label}: missing required H2 headings: {', '.join(missing)}")

    toc = contract["toc"]
    toc_heading = toc["heading"]
    toc_matches = [(name, index) for name, index in headings if name == toc_heading]
    if len(toc_matches) != 1:
        if not toc_matches and toc_heading not in missing:
            errors.append(f"{label}: missing TOC heading {toc_heading!r}")
        return errors

    toc_line = toc_matches[0][1]
    later_headings = [(name, index) for name, index in headings if index > toc_line]
    toc_end = later_headings[0][1] if later_headings else len(lines)
    toc_text = "\n".join(lines[toc_line + 1 : toc_end])
    links = [match.group(1).strip() for match in OBSIDIAN_TOC_LINK_RE.finditer(toc_text)]
    expected = [name for name, _ in later_headings]
    if links != expected:
        missing_links = [name for name in expected if name not in links]
        extra_links = [name for name in links if name not in expected]
        details: list[str] = []
        if missing_links:
            details.append("missing=" + ", ".join(missing_links))
        if extra_links:
            details.append("extra=" + ", ".join(extra_links))
        if not missing_links and not extra_links:
            details.append("order differs from H2 order")
        errors.append(f"{label}: TOC must exactly cover following H2 headings ({'; '.join(details)})")

    if toc["separators"] == "required":
        if _previous_nonblank(lines, toc_line) != "---":
            errors.append(f"{label}: TOC must have a '---' separator before it")
        if later_headings and _previous_nonblank(lines, toc_end) != "---":
            errors.append(f"{label}: TOC must have a '---' separator after it")
    if contract.get("user_story") is not None:
        errors.extend(_validate_user_story_section(lines, headings, contract, label=label))
    if contract.get("traceability") is not None:
        errors.extend(_validate_traceability_section(lines, headings, contract, label=label))
    if contract.get("reader_projection") is not None:
        errors.extend(_validate_reader_projection(lines, contract, label=label))
    if contract.get("reader_navigation") is not None:
        errors.extend(
            _validate_reader_navigation(lines, headings, contract, label=label)
        )
    return errors


def validate_markdown_file(path: Path, contract: dict[str, Any], *, label: str) -> list[str]:
    """Read and validate one UTF-8 Markdown file."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"{label}: cannot read document: {exc}"]
    return validate_markdown(text, contract, label=label)
