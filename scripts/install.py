#!/usr/bin/env python3
"""Activate a Vigers clone for Codex and Claude Code without overwriting files."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path


DEFAULT_SKILL_ROOT = Path(__file__).resolve().parent.parent
AGENT_NAMES = (
    "vigers-system-analyst",
    "vigers-solution-architect",
    "vigers-spec-editor",
    "vigers-spec-reviewer",
)


class InstallerError(RuntimeError):
    """Unsafe or incomplete installation state."""


@dataclass(frozen=True)
class LinkSpec:
    source: Path
    target: Path


@dataclass(frozen=True)
class LinkState:
    spec: LinkSpec
    status: str
    detail: str


def link_specs(skill_root: Path, user_home: Path) -> list[LinkSpec]:
    """Return every discovery link required by both runtimes."""
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
            )
        )
        specs.append(
            LinkSpec(
                root / "agents" / "claude" / f"{name}.md",
                home / ".claude" / "agents" / f"{name}.md",
            )
        )
    return specs


def inspect_links(skill_root: Path, user_home: Path) -> list[LinkState]:
    """Classify sources and targets without changing the filesystem."""
    states: list[LinkState] = []
    for spec in link_specs(skill_root, user_home):
        source = spec.source.resolve()
        if not source.exists():
            states.append(LinkState(spec, "source-missing", str(source)))
            continue

        target = spec.target
        if target.is_symlink():
            if target.resolve(strict=False) == source:
                states.append(LinkState(spec, "installed", str(source)))
            else:
                states.append(
                    LinkState(spec, "conflict", f"symlink points to {target.resolve(strict=False)}")
                )
        elif target.exists():
            states.append(LinkState(spec, "conflict", "target exists and is not a symlink"))
        else:
            states.append(LinkState(spec, "missing", str(source)))
    return states


def install(skill_root: Path, user_home: Path, *, dry_run: bool = False) -> list[LinkState]:
    """Create only missing links after a mutation-free full preflight."""
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
        if state.status != "missing":
            continue
        state.spec.target.parent.mkdir(parents=True, exist_ok=True)
        state.spec.target.symlink_to(
            state.spec.source.resolve(),
            target_is_directory=state.spec.source.is_dir(),
        )

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
            if any(state.status == "missing" for state in states):
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
