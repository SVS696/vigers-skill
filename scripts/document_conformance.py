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
    return errors


def validate_markdown_file(path: Path, contract: dict[str, Any], *, label: str) -> list[str]:
    """Read and validate one UTF-8 Markdown file."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"{label}: cannot read document: {exc}"]
    return validate_markdown(text, contract, label=label)
