#!/usr/bin/env python3
"""Deterministic context router for the Vigers skill."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
MAP_PATH = ROOT / "references" / "knowledge-map.md"
BOOK_PATH = ROOT / "references" / "book-extract.md"
METHOD_PATH = ROOT / "references" / "requirements-method.md"
NATIVE_FILES = (
    ROOT / "references" / "native-checklists.md",
    ROOT / "references" / "native-diagrams.md",
    ROOT / "references" / "native-tables.md",
)
MAP_MARKER = "<!-- vigers:routes -->"
BLOCK_RE = re.compile(
    r"<!--\s*vigers:block\s+([a-z0-9-]+):(start|end)\s*-->"
)
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
NATIVE_ID_RE = re.compile(r"^([CDT]\d{2})\.\s")
WORD_RE = re.compile(r"[0-9a-zа-яё]+", re.IGNORECASE)
MAX_TARGET_CHARS = 50_000
MAX_DISTILLED_TARGETS = 5
MAX_METHOD_CONTEXT_CHARS = 120_000
METHOD_CONTEXT_SCHEMA = 1
METHOD_CONTEXT_JSON = "method-context.json"
METHOD_CONTEXT_MARKDOWN = "method-context.md"
OPERATIONAL_REFERENCE_FILES = {
    "references/automation-timing.md",
    "references/bounded-recovery.md",
    "references/convergence-contract.md",
    "references/diagram-contract.md",
    "references/execution-policy.md",
    "references/reader-projection-contract.md",
    "references/runtime-preferences.md",
    "references/solution-boundary-contract.md",
}
SHORT_TERMS = {
    "api",
    "crud",
    "dod",
    "erd",
    "fr",
    "srs",
    "uc",
    "ui",
    "uml",
    "ux",
}


class RouterError(RuntimeError):
    """A deterministic routing or validation failure."""


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold().replace("ё", "е")
    return " ".join(value.split())


def match_terms(value: str) -> set[str]:
    terms: set[str] = set()
    for token in WORD_RE.findall(normalize(value)):
        if token in SHORT_TERMS:
            terms.add(token)
        elif re.fullmatch(r"[а-яё]+", token) and len(token) >= 4:
            # Five letters preserve useful Russian inflection matching while
            # avoiding collisions such as происхождение/производительность.
            terms.add(token[:5] if len(token) >= 5 else token)
        elif re.fullmatch(r"[a-z0-9]+", token) and len(token) >= 4:
            terms.add(token)
    return terms


def terms_contain(signal_terms: set[str], text_terms: set[str]) -> bool:
    """Return whether every normalized signal term occurs in task terms."""
    if not signal_terms:
        return False
    for signal_term in signal_terms:
        if signal_term in text_terms:
            continue
        # Four-letter domain terms such as «тест» should match inflected
        # forms («тестами»), without reducing every Russian word to four
        # letters and recreating broad prefix collisions.
        if len(signal_term) == 4 and any(
            text_term.startswith(signal_term) for text_term in text_terms
        ):
            continue
        return False
    return True


def safe_file(relative: str) -> Path:
    if not isinstance(relative, str) or not relative:
        raise RouterError("Target file must be a non-empty relative path")
    candidate = (ROOT / relative).resolve()
    try:
        candidate.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise RouterError(f"Target escapes skill root: {relative}") from exc
    if not candidate.is_file():
        raise RouterError(f"Target file does not exist: {relative}")
    return candidate


def load_map() -> dict[str, Any]:
    text = MAP_PATH.read_text(encoding="utf-8")
    marker_at = text.find(MAP_MARKER)
    if marker_at < 0:
        raise RouterError(f"Missing route marker in {MAP_PATH}")
    fenced = re.search(r"```json\s*(\{.*\})\s*```", text[marker_at:], re.DOTALL)
    if not fenced:
        raise RouterError(f"Missing fenced JSON route map in {MAP_PATH}")
    try:
        data = json.loads(fenced.group(1))
    except json.JSONDecodeError as exc:
        raise RouterError(f"Invalid route JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise RouterError("Route map root must be an object")
    return data


def markdown_headings(text: str) -> list[dict[str, Any]]:
    lines = text.splitlines()
    headings: list[dict[str, Any]] = []
    fence: str | None = None

    for index, line in enumerate(lines):
        stripped = line.lstrip()
        fence_match = re.match(r"(```+|~~~+)", stripped)
        if fence_match:
            token = fence_match.group(1)
            if fence is None:
                fence = token[0]
            elif token[0] == fence:
                fence = None
            continue
        if fence is not None:
            continue

        match = HEADING_RE.match(line)
        if not match:
            continue
        title = re.sub(r"\s+#+\s*$", "", match.group(2)).strip()
        headings.append(
            {
                "title": title,
                "normalized": normalize(title),
                "level": len(match.group(1)),
                "start": index,
            }
        )

    for position, heading in enumerate(headings):
        end = len(lines)
        for next_heading in headings[position + 1 :]:
            if next_heading["level"] <= heading["level"]:
                end = next_heading["start"]
                break
        heading["end"] = end
    return headings


def extract_heading(path: Path, title: str) -> str:
    text = path.read_text(encoding="utf-8")
    matches = [
        heading
        for heading in markdown_headings(text)
        if heading["normalized"] == normalize(title)
    ]
    if len(matches) != 1:
        raise RouterError(
            f"{path.relative_to(ROOT)} heading {title!r} resolved "
            f"{len(matches)} times; expected exactly once"
        )
    lines = text.splitlines()
    match = matches[0]
    result = "\n".join(lines[match["start"] : match["end"]]).strip()
    if not result:
        raise RouterError(
            f"{path.relative_to(ROOT)} heading {title!r} is empty"
        )
    return result


def block_markers(text: str) -> dict[str, dict[str, list[int]]]:
    markers: dict[str, dict[str, list[int]]] = {}
    for line_number, line in enumerate(text.splitlines()):
        match = BLOCK_RE.search(line)
        if not match:
            continue
        block_id, boundary = match.groups()
        markers.setdefault(block_id, {"start": [], "end": []})[boundary].append(
            line_number
        )
    return markers


def extract_block(path: Path, block_id: str) -> str:
    text = path.read_text(encoding="utf-8")
    markers = block_markers(text)
    marker = markers.get(block_id)
    if marker is None:
        raise RouterError(f"{path.relative_to(ROOT)} has no block {block_id!r}")
    if len(marker["start"]) != 1 or len(marker["end"]) != 1:
        raise RouterError(
            f"{path.relative_to(ROOT)} block {block_id!r} must have one "
            "start and one end marker"
        )
    start = marker["start"][0]
    end = marker["end"][0]
    if start >= end:
        raise RouterError(
            f"{path.relative_to(ROOT)} block {block_id!r} markers are reversed"
        )
    result = "\n".join(text.splitlines()[start + 1 : end]).strip()
    if not result:
        raise RouterError(
            f"{path.relative_to(ROOT)} block {block_id!r} is empty"
        )
    return result


def extract_target(target: dict[str, Any]) -> tuple[str, str]:
    if not isinstance(target, dict):
        raise RouterError("Every target must be an object")
    path = safe_file(target.get("file", ""))
    has_heading = isinstance(target.get("heading"), str)
    has_block = isinstance(target.get("block"), str)
    if has_heading == has_block:
        raise RouterError(
            f"Target {target!r} must contain exactly one of heading or block"
        )
    if has_heading:
        label = f"{path.relative_to(ROOT)} :: {target['heading']}"
        content = extract_heading(path, target["heading"])
    else:
        label = f"{path.relative_to(ROOT)} :: {target['block']}"
        content = extract_block(path, target["block"])
    if len(content) > MAX_TARGET_CHARS:
        raise RouterError(
            f"Target {label} is {len(content)} characters; split the block"
        )
    return label, content


def text_sha256(content: str) -> str:
    """Hash UTF-8 text deterministically."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def payload_fingerprint(payload: dict[str, Any]) -> str:
    """Hash canonical JSON without trusting its stored fingerprint."""
    canonical = {key: value for key, value in payload.items() if key != "fingerprint"}
    encoded = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def method_section(
    *,
    kind: str,
    source: str,
    selector_type: str,
    selector: str,
    label: str,
    content: str,
) -> tuple[dict[str, Any], str]:
    """Build one provenance row and its Markdown section."""
    metadata = {
        "kind": kind,
        "source": source,
        "selector": {"type": selector_type, "value": selector},
        "label": label,
        "content_sha256": text_sha256(content),
        "characters": len(content),
    }
    heading = f"## {kind.upper()}: {label}"
    return metadata, f"{heading}\n\n{content}"


def build_method_context(
    data: dict[str, Any],
    route_id: str,
    *,
    include_fallback: bool = False,
    exact_ids: list[str] | None = None,
) -> tuple[dict[str, Any], str]:
    """Materialize one bounded method route as Markdown plus a JSON sidecar."""
    routes = route_index(data)
    route = routes.get(route_id)
    if route is None:
        raise RouterError(f"Unknown route {route_id!r}. Run the list command first.")

    normalized_ids = [native_id.upper() for native_id in (exact_ids or [])]
    if len(normalized_ids) > 1:
        raise RouterError("Method context accepts at most one exact C/D/T section")
    if len(set(normalized_ids)) != len(normalized_ids):
        raise RouterError("Method context exact IDs must be unique")
    allowed_ids = set(route.get("optional_ids", []))
    disallowed_ids = sorted(set(normalized_ids) - allowed_ids)
    if disallowed_ids:
        raise RouterError(
            f"Route {route_id!r} does not allow exact IDs: {', '.join(disallowed_ids)}"
        )

    section_rows: list[dict[str, Any]] = []
    rendered_sections: list[str] = []
    for heading in route["core"]:
        content = extract_heading(METHOD_PATH, heading)
        row, rendered = method_section(
            kind="core",
            source=str(METHOD_PATH.relative_to(ROOT)),
            selector_type="heading",
            selector=heading,
            label=f"references/requirements-method.md :: {heading}",
            content=content,
        )
        section_rows.append(row)
        rendered_sections.append(rendered)

    for target in route.get("distilled", []):
        label, content = extract_target(target)
        selector_type = "heading" if "heading" in target else "block"
        row, rendered = method_section(
            kind="distilled",
            source=target["file"],
            selector_type=selector_type,
            selector=target[selector_type],
            label=label,
            content=content,
        )
        section_rows.append(row)
        rendered_sections.append(rendered)

    if include_fallback:
        for target in route.get("fallback", []):
            label, content = extract_target(target)
            selector_type = "heading" if "heading" in target else "block"
            row, rendered = method_section(
                kind="fallback",
                source=target["file"],
                selector_type=selector_type,
                selector=target[selector_type],
                label=label,
                content=content,
            )
            section_rows.append(row)
            rendered_sections.append(rendered)

    native = native_sections()
    for native_id in normalized_ids:
        path, heading = native[native_id]
        content = extract_heading(path, heading)
        row, rendered = method_section(
            kind="exact",
            source=str(path.relative_to(ROOT)),
            selector_type="native_id",
            selector=native_id,
            label=f"{path.relative_to(ROOT)} :: {heading}",
            content=content,
        )
        section_rows.append(row)
        rendered_sections.append(rendered)

    header = (
        f"# Vigers method context: {route_id}\n\n"
        f"- route_id: `{route_id}`\n"
        f"- when: {route['when']}\n"
        f"- expected result: {route['result']}\n"
        f"- fallback included: `{'yes' if include_fallback else 'no'}`\n"
        f"- exact IDs: `{', '.join(normalized_ids) if normalized_ids else 'none'}`"
    )
    markdown = header + "\n\n" + "\n\n".join(rendered_sections) + "\n"
    if len(markdown) > MAX_METHOD_CONTEXT_CHARS:
        raise RouterError(
            f"Method context is {len(markdown)} characters; reduce the route inputs"
        )

    payload: dict[str, Any] = {
        "schema": METHOD_CONTEXT_SCHEMA,
        "route_id": route_id,
        "include_fallback": include_fallback,
        "exact_ids": normalized_ids,
        "when": route["when"],
        "expected_result": route["result"],
        "content_path": METHOD_CONTEXT_MARKDOWN,
        "content_sha256": text_sha256(markdown),
        "sections": section_rows,
    }
    payload["fingerprint"] = payload_fingerprint(payload)
    return payload, markdown


def validate_method_context(
    payload: Any,
    markdown: str,
    *,
    expected_route_id: str | None = None,
    verify_sources: bool = False,
) -> None:
    """Validate method snapshot integrity, route binding, and optionally live sources."""
    if not isinstance(payload, dict) or payload.get("schema") != METHOD_CONTEXT_SCHEMA:
        raise RouterError("Unsupported method context schema")
    if not isinstance(payload.get("route_id"), str) or not payload["route_id"]:
        raise RouterError("Method context has no route_id")
    if payload.get("content_path") != METHOD_CONTEXT_MARKDOWN:
        raise RouterError("Method context content_path is invalid")
    if payload.get("content_sha256") != text_sha256(markdown):
        raise RouterError("Method context Markdown hash mismatch")
    if payload.get("fingerprint") != payload_fingerprint(payload):
        raise RouterError("Method context fingerprint mismatch")
    if not isinstance(payload.get("include_fallback"), bool):
        raise RouterError("Method context include_fallback must be Boolean")
    if not isinstance(payload.get("exact_ids"), list):
        raise RouterError("Method context exact_ids must be an array")
    if not isinstance(payload.get("sections"), list) or not payload["sections"]:
        raise RouterError("Method context sections must be a non-empty array")
    for section in payload["sections"]:
        if not isinstance(section, dict):
            raise RouterError("Method context section must be an object")
        for field in ("kind", "source", "label", "content_sha256"):
            if not isinstance(section.get(field), str) or not section[field]:
                raise RouterError(f"Method context section has no {field}")
        selector = section.get("selector")
        if not isinstance(selector, dict) or not isinstance(selector.get("value"), str):
            raise RouterError("Method context section has no selector")
    if expected_route_id is not None and payload["route_id"] != expected_route_id:
        raise RouterError(
            f"Method context route {payload['route_id']!r}, case uses {expected_route_id!r}"
        )

    if verify_sources:
        rebuilt_payload, rebuilt_markdown = build_method_context(
            load_map(),
            payload["route_id"],
            include_fallback=payload["include_fallback"],
            exact_ids=payload["exact_ids"],
        )
        if payload != rebuilt_payload or markdown != rebuilt_markdown:
            raise RouterError("Method context does not match current routed sources")


def write_method_context(root: Path, payload: dict[str, Any], markdown: str) -> None:
    """Create both method artifacts without overwriting prior case state."""
    target_root = root.expanduser().resolve()
    metadata_path = target_root / METHOD_CONTEXT_JSON
    content_path = target_root / METHOD_CONTEXT_MARKDOWN
    for target in (metadata_path, content_path):
        if target.exists() or target.is_symlink():
            raise RouterError(f"Refusing to overwrite method context: {target}")
    target_root.mkdir(parents=True, exist_ok=True)
    content_path.write_text(markdown, encoding="utf-8")
    metadata_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def route_index(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    routes = data.get("routes")
    if not isinstance(routes, list):
        raise RouterError("routes must be an array")
    index: dict[str, dict[str, Any]] = {}
    for route in routes:
        if not isinstance(route, dict) or not isinstance(route.get("id"), str):
            raise RouterError("Every route must be an object with a string id")
        route_id = route["id"]
        if route_id in index:
            raise RouterError(f"Duplicate route id: {route_id}")
        index[route_id] = route
    return index


def native_sections() -> dict[str, tuple[Path, str]]:
    result: dict[str, tuple[Path, str]] = {}
    for path in NATIVE_FILES:
        for heading in markdown_headings(path.read_text(encoding="utf-8")):
            match = NATIVE_ID_RE.match(heading["title"])
            if not match:
                continue
            native_id = match.group(1)
            if native_id in result:
                raise RouterError(f"Duplicate native id: {native_id}")
            result[native_id] = (path, heading["title"])
    return result


def expected_native_ids() -> set[str]:
    return {
        *(f"C{number:02d}" for number in range(1, 27)),
        *(f"D{number:02d}" for number in range(1, 19)),
        *(f"T{number:02d}" for number in range(1, 27)),
    }


def validate() -> dict[str, int]:
    data = load_map()
    errors: list[str] = []

    if data.get("version") != 1:
        errors.append("Route map version must be 1")

    try:
        routes = route_index(data)
    except RouterError as exc:
        errors.append(str(exc))
        routes = {}

    default_route = data.get("default_route")
    if default_route not in routes:
        errors.append("default_route must reference an existing route")

    referenced_files: set[str] = {
        "references/requirements-method.md",
        "references/handoff-contract.md",
        "references/prompt-contract.md",
        "references/planning-contract.md",
        "references/case-state.md",
        "references/block-contract.md",
    }
    referenced_blocks: set[str] = set()
    skill_path = ROOT / "SKILL.md"

    for route_id, route in routes.items():
        for field in ("when", "signals", "core", "distilled", "fallback", "result"):
            if field not in route:
                errors.append(f"{route_id}: missing field {field}")
        if not isinstance(route.get("when"), str) or not route.get("when", "").strip():
            errors.append(f"{route_id}: when must be a non-empty string")
        if not isinstance(route.get("result"), str) or not route.get(
            "result", ""
        ).strip():
            errors.append(f"{route_id}: result must be a non-empty string")
        if not isinstance(route.get("signals"), list):
            errors.append(f"{route_id}: signals must be an array")
        if not isinstance(route.get("core"), list) or not route.get("core"):
            errors.append(f"{route_id}: core must contain at least one heading")
        else:
            for heading in route["core"]:
                try:
                    extract_heading(METHOD_PATH, heading)
                except RouterError as exc:
                    errors.append(f"{route_id}: {exc}")

        distilled = route.get("distilled")
        fallback = route.get("fallback")
        if not isinstance(distilled, list):
            errors.append(f"{route_id}: distilled must be an array")
            distilled = []
        if not isinstance(fallback, list):
            errors.append(f"{route_id}: fallback must be an array")
            fallback = []
        if len(distilled) > MAX_DISTILLED_TARGETS:
            errors.append(
                f"{route_id}: distilled has {len(distilled)} targets; "
                f"maximum is {MAX_DISTILLED_TARGETS}"
            )
        if len(fallback) > 1:
            errors.append(f"{route_id}: fallback must contain at most one block")

        for target in distilled:
            if isinstance(target, dict):
                relative = target.get("file", "")
                referenced_files.add(relative)
                if relative == "references/book-extract.md":
                    errors.append(f"{route_id}: book target placed in distilled")
            try:
                extract_target(target)
            except RouterError as exc:
                errors.append(f"{route_id}: {exc}")

        for target in fallback:
            if isinstance(target, dict):
                relative = target.get("file", "")
                referenced_files.add(relative)
                if relative != "references/book-extract.md":
                    errors.append(f"{route_id}: fallback must use book-extract.md")
                if isinstance(target.get("block"), str):
                    referenced_blocks.add(target["block"])
            try:
                extract_target(target)
            except RouterError as exc:
                errors.append(f"{route_id}: {exc}")

    book_text = BOOK_PATH.read_text(encoding="utf-8")
    markers = block_markers(book_text)
    for block_id, boundaries in markers.items():
        if len(boundaries["start"]) != 1 or len(boundaries["end"]) != 1:
            errors.append(f"{block_id}: block markers are not unique")
        elif boundaries["start"][0] >= boundaries["end"][0]:
            errors.append(f"{block_id}: block markers are reversed")
    orphan_blocks = set(markers) - referenced_blocks
    if orphan_blocks:
        errors.append(f"Unrouted book blocks: {', '.join(sorted(orphan_blocks))}")
    missing_blocks = referenced_blocks - set(markers)
    if missing_blocks:
        errors.append(f"Missing book blocks: {', '.join(sorted(missing_blocks))}")

    try:
        native = native_sections()
        expected = expected_native_ids()
        if set(native) != expected:
            errors.append(
                "Native IDs differ from expected set: "
                f"missing={sorted(expected - set(native))}, "
                f"extra={sorted(set(native) - expected)}"
            )
        for route_id, route in routes.items():
            optional = route.get("optional_ids", [])
            if not isinstance(optional, list):
                errors.append(f"{route_id}: optional_ids must be an array")
                continue
            unknown = set(optional) - set(native)
            if unknown:
                errors.append(
                    f"{route_id}: unknown optional_ids {sorted(unknown)}"
                )
    except RouterError as exc:
        errors.append(str(exc))
        native = {}

    image_map = (ROOT / "references" / "native-image-map.md").read_text(
        encoding="utf-8"
    )
    mapped_ids = re.findall(r"\b[CDT]\d{2}\b", image_map)
    counts = Counter(mapped_ids)
    if set(counts) != expected_native_ids() or any(count != 1 for count in counts.values()):
        errors.append("native-image-map.md must map every C/D/T id exactly once")

    all_reference_files = {
        str(path.relative_to(ROOT))
        for path in (ROOT / "references").glob("*.md")
        if path.name != "knowledge-map.md"
    }
    missing_operational = OPERATIONAL_REFERENCE_FILES - all_reference_files
    if missing_operational:
        errors.append(
            "Declared operational reference files are missing: "
            + ", ".join(sorted(missing_operational))
        )
    routed_operational = OPERATIONAL_REFERENCE_FILES & referenced_files
    if routed_operational:
        errors.append(
            "Operational reference files must not be injected through method routes: "
            + ", ".join(sorted(routed_operational))
        )
    uncovered = (
        all_reference_files - referenced_files - OPERATIONAL_REFERENCE_FILES
    )
    if uncovered:
        errors.append(
            "Reference files absent from routes: " + ", ".join(sorted(uncovered))
        )

    skill_text = skill_path.read_text(encoding="utf-8")
    if len(skill_text.splitlines()) > 500:
        errors.append("SKILL.md exceeds 500 lines")
    required_links = (
        "{baseDir}/references/knowledge-map.md",
        "{baseDir}/scripts/vigers_context.py",
    )
    for link in required_links:
        if link not in skill_text:
            errors.append(f"SKILL.md missing router link: {link}")
    home_path_markers = tuple(
        "".join(parts) for parts in (("/", "Users/"), ("/", "home/"))
    )
    if any(marker in skill_text for marker in home_path_markers):
        errors.append("SKILL.md contains a hardcoded home path")
    if "![" in book_text or re.search(r"<img\b", book_text, re.IGNORECASE):
        errors.append("book-extract.md still contains image embeds")

    if errors:
        raise RouterError("\n".join(f"- {error}" for error in errors))

    return {
        "routes": len(routes),
        "blocks": len(markers),
        "native_ids": len(native),
        "reference_files": len(all_reference_files),
        "operational_reference_files": len(OPERATIONAL_REFERENCE_FILES),
    }


def print_routes(data: dict[str, Any]) -> None:
    default_route = data["default_route"]
    for route in data["routes"]:
        suffix = " [default]" if route["id"] == default_route else ""
        print(f"{route['id']}{suffix}\t{route['when']}")


def match_routes(data: dict[str, Any], text: str) -> None:
    normalized_text = normalize(text)
    if not normalized_text:
        raise RouterError("Provide task text as arguments or standard input")
    text_terms = match_terms(text)
    matches: list[tuple[int, str, list[str]]] = []
    for route in data["routes"]:
        hits: list[str] = []
        score = 0
        for signal in route.get("signals", []):
            normalized_signal = normalize(signal)
            signal_terms = match_terms(signal)
            exact = normalized_signal in normalized_text
            term_match = terms_contain(signal_terms, text_terms)
            if not exact and not term_match:
                continue
            hits.append(signal)
            score += max(1, len(signal_terms))
            if exact:
                score += 2
        if hits:
            matches.append((score, route["id"], hits))
    if not matches:
        print(f"{data['default_route']}\tno distinctive route signal")
        return
    for score, route_id, hits in sorted(matches, reverse=True)[:3]:
        print(f"{route_id}\tscore={score}\thits={', '.join(hits)}")


def show_route(data: dict[str, Any], route_id: str, include_fallback: bool) -> None:
    routes = route_index(data)
    route = routes.get(route_id)
    if route is None:
        raise RouterError(
            f"Unknown route {route_id!r}. Run the list command first."
        )

    print(f"# Route: {route['id']}")
    print(f"When: {route['when']}")
    print(f"Expected result: {route['result']}")
    print("Core sections: " + "; ".join(route["core"]))
    if route.get("optional_ids"):
        print(
            "Optional exact sections: "
            + ", ".join(route["optional_ids"])
            + " (load one with the id command)"
        )

    for heading in route["core"]:
        content = extract_heading(METHOD_PATH, heading)
        print(f"\n--- CORE: references/requirements-method.md :: {heading} ---\n")
        print(content)

    distilled = route.get("distilled", [])
    if not distilled:
        print("\nNo additional distilled context required.")
    for target in distilled:
        label, content = extract_target(target)
        print(f"\n--- DISTILLED: {label} ---\n")
        print(content)

    fallback = route.get("fallback", [])
    if include_fallback:
        if not fallback:
            print("\nNo book fallback is defined for this route.")
        for target in fallback:
            label, content = extract_target(target)
            print(f"\n--- FALLBACK: {label} ---\n")
            print(content)
    elif fallback:
        print(
            "\nFallback omitted. Re-run this route with --fallback only if a "
            "named detail remains unresolved."
        )


def show_native_id(native_id: str) -> None:
    native_id = native_id.upper()
    if not re.fullmatch(r"[CDT]\d{2}", native_id):
        raise RouterError("Native id must look like C09, D13, or T22")
    native = native_sections()
    target = native.get(native_id)
    if target is None:
        raise RouterError(f"Unknown native id: {native_id}")
    path, heading = target
    print(extract_heading(path, heading))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Load one deterministic Vigers knowledge route"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("list", help="List route ids and their use cases")

    match_parser = subparsers.add_parser(
        "match", help="Suggest routes from distinctive phrases"
    )
    match_parser.add_argument(
        "text",
        nargs="*",
        help="Task text; when omitted, read it from standard input",
    )

    show_parser = subparsers.add_parser(
        "show", help="Print distilled context for exactly one route"
    )
    show_parser.add_argument("route_id")
    show_parser.add_argument(
        "--fallback",
        action="store_true",
        help="Also print the route's bounded book-extract block",
    )

    id_parser = subparsers.add_parser(
        "id", help="Print exactly one native C/D/T section"
    )
    id_parser.add_argument("native_id")

    materialize_parser = subparsers.add_parser(
        "materialize",
        help="Create a pinned method-context Markdown and JSON pair",
    )
    materialize_parser.add_argument("route_id")
    materialize_parser.add_argument("--fallback", action="store_true")
    materialize_parser.add_argument("--id", action="append", default=[])
    materialize_parser.add_argument("--write", required=True, help="Target case-root")

    subparsers.add_parser(
        "validate", help="Validate routes, blocks, IDs, paths, and coverage"
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        if args.command == "validate":
            counts = validate()
            print(
                "PASS "
                + " ".join(f"{key}={value}" for key, value in counts.items())
            )
            return 0

        data = load_map()
        route_index(data)
        if args.command == "list":
            print_routes(data)
        elif args.command == "match":
            text = " ".join(args.text) if args.text else sys.stdin.read()
            match_routes(data, text)
        elif args.command == "show":
            show_route(data, args.route_id, args.fallback)
        elif args.command == "id":
            show_native_id(args.native_id)
        elif args.command == "materialize":
            payload, markdown = build_method_context(
                data,
                args.route_id,
                include_fallback=args.fallback,
                exact_ids=args.id,
            )
            validate_method_context(
                payload,
                markdown,
                expected_route_id=args.route_id,
                verify_sources=True,
            )
            write_method_context(Path(args.write), payload, markdown)
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    except (OSError, RouterError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
