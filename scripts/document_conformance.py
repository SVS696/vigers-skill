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
H2_RE = re.compile(r"^##(?!#)\s+(.+?)\s*$")
OBSIDIAN_TOC_LINK_RE = re.compile(r"\[\[#([^\]|]+)(?:\|[^\]]+)?\]\]")


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
    return errors


def validate_markdown_file(path: Path, contract: dict[str, Any], *, label: str) -> list[str]:
    """Read and validate one UTF-8 Markdown file."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"{label}: cannot read document: {exc}"]
    return validate_markdown(text, contract, label=label)
