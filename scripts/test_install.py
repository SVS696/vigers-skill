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
