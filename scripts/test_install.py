#!/usr/bin/env python3
"""Regression tests for the fail-closed Vigers installer."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import install as installer


class InstallerTests(unittest.TestCase):
    def test_install_is_complete_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            user_home = Path(temp)
            first = installer.install(installer.DEFAULT_SKILL_ROOT, user_home)
            second = installer.install(installer.DEFAULT_SKILL_ROOT, user_home)
            self.assertTrue(first)
            self.assertTrue(all(state.status == "installed" for state in first))
            self.assertTrue(all(state.status == "installed" for state in second))
            codex_agent = user_home / ".codex" / "agents" / "vigers-planner.toml"
            claude_agent = user_home / ".claude" / "agents" / "vigers-planner.md"
            self.assertTrue(codex_agent.is_file())
            self.assertFalse(codex_agent.is_symlink())
            self.assertEqual(
                codex_agent.read_bytes(),
                (installer.DEFAULT_SKILL_ROOT / "agents" / "codex" / codex_agent.name).read_bytes(),
            )
            self.assertTrue(claude_agent.is_symlink())
            self.assertTrue(installer.manifest_path(user_home).is_file())

    def test_dry_run_does_not_create_links(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            user_home = Path(temp)
            states = installer.install(
                installer.DEFAULT_SKILL_ROOT,
                user_home,
                dry_run=True,
            )
            self.assertTrue(any(state.status == "missing" for state in states))
            self.assertFalse((user_home / ".agents").exists())

    def test_matching_codex_symlink_is_migrated_to_regular_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            user_home = Path(temp)
            source = (
                installer.DEFAULT_SKILL_ROOT
                / "agents"
                / "codex"
                / "vigers-planner.toml"
            )
            target = user_home.resolve() / ".codex" / "agents" / source.name
            target.parent.mkdir(parents=True)
            target.symlink_to(source)

            before = installer.inspect_links(installer.DEFAULT_SKILL_ROOT, user_home)
            planner = next(state for state in before if state.spec.target == target)
            self.assertEqual(planner.status, "migration-required")

            installer.install(installer.DEFAULT_SKILL_ROOT, user_home)
            self.assertTrue(target.is_file())
            self.assertFalse(target.is_symlink())
            self.assertEqual(target.read_bytes(), source.read_bytes())

    def test_managed_codex_copy_refreshes_but_manual_edit_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            sandbox = Path(temp)
            skill_root = sandbox / "skill"
            user_home = sandbox / "home"
            for name in installer.AGENT_NAMES:
                codex = skill_root / "agents" / "codex" / f"{name}.toml"
                claude = skill_root / "agents" / "claude" / f"{name}.md"
                codex.parent.mkdir(parents=True, exist_ok=True)
                claude.parent.mkdir(parents=True, exist_ok=True)
                codex.write_text(f'name = "{name}"\n', encoding="utf-8")
                claude.write_text(f"# {name}\n", encoding="utf-8")

            installer.install(skill_root, user_home)
            source = skill_root / "agents" / "codex" / "vigers-planner.toml"
            target = user_home.resolve() / ".codex" / "agents" / source.name
            source.write_text('name = "vigers-planner"\ndescription = "updated"\n', encoding="utf-8")

            refresh = next(
                state
                for state in installer.inspect_links(skill_root, user_home)
                if state.spec.target == target
            )
            self.assertEqual(refresh.status, "refresh-required")
            installer.install(skill_root, user_home)
            self.assertEqual(target.read_bytes(), source.read_bytes())

            target.write_text("manual edit\n", encoding="utf-8")
            with self.assertRaises(installer.InstallerError):
                installer.install(skill_root, user_home)

    def test_conflict_aborts_before_any_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            user_home = Path(temp)
            conflict = user_home / ".codex" / "agents" / "vigers-spec-editor.toml"
            conflict.parent.mkdir(parents=True)
            conflict.write_text("owned by user", encoding="utf-8")

            with self.assertRaises(installer.InstallerError):
                installer.install(installer.DEFAULT_SKILL_ROOT, user_home)

            self.assertFalse((user_home / ".agents" / "skills" / "vigers").exists())
            self.assertEqual(conflict.read_text(encoding="utf-8"), "owned by user")


if __name__ == "__main__":
    unittest.main()
