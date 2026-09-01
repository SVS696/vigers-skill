#!/usr/bin/env python3
"""Activate a Vigers clone for Codex and Claude Code without overwriting files."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import sys
from dataclasses import dataclass
from pathlib import Path


DEFAULT_SKILL_ROOT = Path(__file__).resolve().parent.parent
AGENT_NAMES = (
    "vigers-planner",
    "vigers-system-analyst",
    "vigers-solution-architect",
    "vigers-spec-editor",
    "vigers-spec-reviewer",
)
MANIFEST_NAME = ".vigers-agent-copies.json"
LINK = "link"
COPY = "copy"


class InstallerError(RuntimeError):
    """Unsafe or incomplete installation state."""


@dataclass(frozen=True)
class LinkSpec:
    source: Path
    target: Path
    mode: str = LINK


@dataclass(frozen=True)
class LinkState:
    spec: LinkSpec
    status: str
    detail: str


def link_specs(skill_root: Path, user_home: Path) -> list[LinkSpec]:
    """Return every discovery target required by both runtimes."""
    root = skill_root.expanduser().resolve()
    home = user_home.expanduser().resolve()
    specs = [
        LinkSpec(root, home / ".agents" / "skills" / "vigers"),
        LinkSpec(root, home / ".claude" / "skills" / "vigers"),
    ]
    for name in AGENT_NAMES:
        specs.append(
            LinkSpec(
                root / "agents" / "codex" / f"{name}.toml",
                home / ".codex" / "agents" / f"{name}.toml",
                COPY,
            )
        )
        specs.append(
            LinkSpec(
                root / "agents" / "claude" / f"{name}.md",
                home / ".claude" / "agents" / f"{name}.md",
            )
        )
    return specs


def manifest_path(user_home: Path) -> Path:
    """Return the ownership manifest for managed Codex agent copies."""
    return user_home.expanduser().resolve() / ".codex" / "agents" / MANIFEST_NAME


def digest(path: Path) -> str:
    """Return a stable content digest for a regular file."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_manifest(user_home: Path) -> dict[str, str]:
    """Load managed-copy hashes and reject ambiguous manifest state."""
    path = manifest_path(user_home)
    if not path.exists() and not path.is_symlink():
        return {}
    if path.is_symlink() or not path.is_file():
        raise InstallerError(f"Managed-copy manifest is not a regular file: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InstallerError(f"Cannot read managed-copy manifest {path}: {exc}") from exc
    if payload.get("schema") != 1 or not isinstance(payload.get("files"), dict):
        raise InstallerError(f"Unsupported managed-copy manifest: {path}")
    files = payload["files"]
    if not all(isinstance(name, str) and isinstance(value, str) for name, value in files.items()):
        raise InstallerError(f"Invalid managed-copy manifest entries: {path}")
    return files


def atomic_copy(source: Path, target: Path) -> None:
    """Replace a target with a regular-file copy without exposing partial content."""
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=target.parent,
            prefix=f".{target.name}.",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(source.read_bytes())
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(source.stat().st_mode & 0o777)
        os.replace(temporary, target)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def write_manifest(user_home: Path, files: dict[str, str]) -> None:
    """Atomically record the exact Codex agent copies managed by this installer."""
    path = manifest_path(user_home)
    payload = json.dumps({"schema": 1, "files": files}, indent=2, sort_keys=True) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def inspect_links(skill_root: Path, user_home: Path) -> list[LinkState]:
    """Classify sources and targets without changing the filesystem."""
    managed = load_manifest(user_home)
    states: list[LinkState] = []
    for spec in link_specs(skill_root, user_home):
        source = spec.source.resolve()
        if not source.exists():
            states.append(LinkState(spec, "source-missing", str(source)))
            continue

        target = spec.target
        if target.is_symlink():
            if target.resolve(strict=False) == source:
                status = "installed" if spec.mode == LINK else "migration-required"
                states.append(LinkState(spec, status, str(source)))
            else:
                states.append(
                    LinkState(spec, "conflict", f"symlink points to {target.resolve(strict=False)}")
                )
        elif target.exists() and spec.mode == COPY:
            if not target.is_file():
                states.append(LinkState(spec, "conflict", "copy target is not a regular file"))
                continue
            source_digest = digest(source)
            target_digest = digest(target)
            managed_digest = managed.get(target.name)
            if target_digest == source_digest and managed_digest == target_digest:
                states.append(LinkState(spec, "installed", source_digest))
            elif target_digest == source_digest:
                states.append(LinkState(spec, "adoption-required", source_digest))
            elif managed_digest == target_digest:
                states.append(
                    LinkState(
                        spec,
                        "refresh-required",
                        f"{target_digest} -> {source_digest}",
                    )
                )
            else:
                states.append(
                    LinkState(
                        spec,
                        "conflict",
                        "regular file differs from source and is not an unchanged managed copy",
                    )
                )
        elif target.exists():
            states.append(LinkState(spec, "conflict", "target exists and is not a symlink"))
        else:
            states.append(LinkState(spec, "missing", str(source)))
    return states


def install(skill_root: Path, user_home: Path, *, dry_run: bool = False) -> list[LinkState]:
    """Install links and managed copies after a mutation-free full preflight."""
    states = inspect_links(skill_root, user_home)
    blockers = [state for state in states if state.status in {"source-missing", "conflict"}]
    if blockers:
        details = "\n".join(
            f"- {state.status}: {state.spec.target} ({state.detail})" for state in blockers
        )
        raise InstallerError(f"Preflight failed; no links were changed:\n{details}")
    if dry_run:
        return states

    for state in states:
        if state.status == "installed":
            continue
        if state.spec.mode == COPY:
            atomic_copy(state.spec.source.resolve(), state.spec.target)
        elif state.status == "missing":
            state.spec.target.parent.mkdir(parents=True, exist_ok=True)
            state.spec.target.symlink_to(
                state.spec.source.resolve(),
                target_is_directory=state.spec.source.is_dir(),
            )

    copies = {
        spec.target.name: digest(spec.target)
        for spec in link_specs(skill_root, user_home)
        if spec.mode == COPY
    }
    write_manifest(user_home, copies)

    verified = inspect_links(skill_root, user_home)
    incomplete = [state for state in verified if state.status != "installed"]
    if incomplete:
        details = "\n".join(
            f"- {state.status}: {state.spec.target} ({state.detail})" for state in incomplete
        )
        raise InstallerError(f"Post-install verification failed:\n{details}")
    return verified


def print_states(states: list[LinkState]) -> None:
    for state in states:
        print(f"{state.status}\t{state.spec.target}\t{state.detail}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skill-root", type=Path, default=DEFAULT_SKILL_ROOT)
    parser.add_argument("--home", type=Path, default=Path.home())
    parser.add_argument("--check", action="store_true", help="Inspect without installing")
    parser.add_argument("--dry-run", action="store_true", help="Preflight and show planned state")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.check:
            states = inspect_links(args.skill_root, args.home)
            print_states(states)
            if any(state.status in {"source-missing", "conflict"} for state in states):
                return 2
            if any(state.status != "installed" for state in states):
                return 1
            return 0

        states = install(args.skill_root, args.home, dry_run=args.dry_run)
        print_states(states)
        return 0
    except (OSError, InstallerError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
