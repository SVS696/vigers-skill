#!/usr/bin/env python3
"""Deterministic context router for the Vigers skill."""

from __future__ import annotations

import argparse
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

    referenced_files: set[str] = set()
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
                    extract_heading(skill_path, heading)
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
    uncovered = all_reference_files - referenced_files
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
    if "/Users/" in skill_text or "/home/" in skill_text:
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

    distilled = route.get("distilled", [])
    if not distilled:
        print("\nNo additional context required. Use SKILL.md only.")
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
        return 0
    except (OSError, RouterError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
