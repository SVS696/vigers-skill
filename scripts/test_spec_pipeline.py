#!/usr/bin/env python3
"""Regression tests for Vigers package profiles and project overlays."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import mode_decision
import spec_pipeline


PROFILE_BODY = """---
vigers_profile: 2
profile_id: {profile_id}
planning_anchors: {planning_anchors}
---

# Project profile

## Область
Scope.

## Канонические источники
Sources.

## Планирование и внешние артефакты
Planning.

## Системный анализ
Analysis.

## Архитектурный гейт
Gate.

## Режимы и разбиение
Modes.

## Артефакт и author gates
Artifact.

## Жизненный цикл и публикация
Lifecycle.
"""


def write_profile(
    root: Path,
    profile_id: str = "project-alpha",
    planning_anchors: str = "",
) -> Path:
    profile = root / ".vigers" / "profile.md"
    profile.parent.mkdir(parents=True)
    profile.write_text(
        PROFILE_BODY.format(
            profile_id=profile_id,
            planning_anchors=planning_anchors,
        ),
        encoding="utf-8",
    )
    return profile


class PipelineTests(unittest.TestCase):
    def decision(self, **overrides: object) -> dict[str, object]:
        values: dict[str, object] = {
            "task": "Describe one behavior change",
            "profile_id": "generic",
            "profile_file": "profiles/generic.md",
            "profile_source": "generic",
            "project_root": None,
            "estimated_blocks": 1,
            "surfaces": ["scenarios"],
            "components": ["service-a"],
            "owners": ["team-a"],
            "dependent_parts": False,
            "unsafe_single_pass": False,
            "project_triggers": [],
            "requested_mode": None,
        }
        values.update(overrides)
        return mode_decision.build_mode_decision(**values)  # type: ignore[arg-type]

    def test_package_validation(self) -> None:
        counts = spec_pipeline.validate()
        self.assertEqual(counts["builtin_profiles"], 1)
        self.assertEqual(counts["project_profiles"], 0)
        self.assertEqual(counts["contracts"], 5)
        self.assertEqual(counts["runtime_adapters"], 10)
        self.assertEqual(counts["workflows"], 3)
        self.assertEqual(counts["prompt_evals"], 1)

    def test_closed_coverage_prompt_eval_rejects_archaeological_restart(self) -> None:
        eval_path = (
            spec_pipeline.ROOT
            / "evals"
            / "prompt-cookbook"
            / "convergence-closed-coverage.json"
        )
        payload = json.loads(eval_path.read_text(encoding="utf-8"))
        expected = payload["expected"]
        self.assertIn(
            "открыть новый общий research cluster",
            expected["forbidden_actions"],
        )
        self.assertIn("research_reopen: no", expected["required_output_signals"])
        self.assertEqual(
            expected["allowed_research_exception"]["required_fields"],
            [
                "research_question",
                "missing_evidence",
                "target_sources",
                "stop_condition",
            ],
        )

    def test_generic_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            selection = spec_pipeline.detect_profile(Path(temp))
            self.assertEqual(selection.profile_id, "generic")
            self.assertEqual(selection.source, "generic")
            self.assertIsNone(selection.project_root)

    def test_project_overlay_detection_from_nested_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "project"
            nested = root / "docs" / "drafts"
            nested.mkdir(parents=True)
            profile = write_profile(root)
            selection = spec_pipeline.detect_profile(nested)
            self.assertEqual(selection.profile_id, "project-alpha")
            self.assertEqual(selection.project_root, root.resolve())
            self.assertEqual(selection.profile_path, profile.resolve())
            self.assertEqual(selection.source, "project")

    def test_project_overlay_exposes_machine_readable_planning_anchors(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "project"
            root.mkdir()
            write_profile(root, planning_anchors="Tracker, Personal tasks")
            selection = spec_pipeline.detect_profile(root)
            self.assertEqual(selection.planning_anchors, ("Tracker", "Personal tasks"))

    def test_duplicate_planning_anchor_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "project"
            root.mkdir()
            write_profile(root, planning_anchors="Tracker, tracker")
            with self.assertRaises(spec_pipeline.PipelineError):
                spec_pipeline.detect_profile(root)

    def test_nearest_project_overlay_wins(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            outer = Path(temp) / "outer"
            inner = outer / "inner"
            nested = inner / "docs"
            nested.mkdir(parents=True)
            write_profile(outer, "outer-project")
            write_profile(inner, "inner-project")
            selection = spec_pipeline.detect_profile(nested)
            self.assertEqual(selection.profile_id, "inner-project")
            self.assertEqual(selection.project_root, inner.resolve())

    def test_named_profile_must_match_detected_overlay(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "project"
            root.mkdir()
            write_profile(root, "project-alpha")
            with self.assertRaises(spec_pipeline.PipelineError):
                spec_pipeline.select_profile("project-beta", root)

    def test_project_profile_cannot_shadow_generic(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "project"
            root.mkdir()
            write_profile(root, "generic")
            with self.assertRaises(spec_pipeline.PipelineError):
                spec_pipeline.detect_profile(root)

    def test_invalid_profile_id_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "project"
            root.mkdir()
            write_profile(root, "Not Valid")
            with self.assertRaises(spec_pipeline.PipelineError):
                spec_pipeline.detect_profile(root)

    def test_explicit_project_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "project"
            root.mkdir()
            write_profile(root)
            counts = spec_pipeline.validate([root])
            self.assertEqual(counts["project_profiles"], 1)

    def test_profile_symlink_cannot_escape_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            root = base / "project"
            root.mkdir()
            external = base / "external.md"
            external.write_text(
                PROFILE_BODY.format(profile_id="external", planning_anchors=""),
                encoding="utf-8",
            )
            profile = root / ".vigers" / "profile.md"
            profile.parent.mkdir()
            profile.symlink_to(external)
            with self.assertRaises(spec_pipeline.PipelineError):
                spec_pipeline.detect_profile(root)

    def test_mode_without_block_triggers_is_compact(self) -> None:
        decision = self.decision()
        self.assertEqual(decision["recommended_mode"], "compact")
        self.assertEqual(decision["selected_mode"], "compact")
        self.assertEqual(decision["triggered_rules"], [])

    def test_each_structural_trigger_can_select_block(self) -> None:
        variants = (
            {"estimated_blocks": 3},
            {"surfaces": ["data", "interfaces"]},
            {"components": ["api", "worker"]},
            {"owners": ["team-a", "team-b"]},
            {"dependent_parts": True},
            {"unsafe_single_pass": True},
            {"project_triggers": ["cross-cutting-change"]},
        )
        for variant in variants:
            with self.subTest(variant=variant):
                self.assertEqual(self.decision(**variant)["selected_mode"], "block")

    def test_explicit_mode_wins_and_keeps_rule_warning(self) -> None:
        decision = self.decision(estimated_blocks=4, requested_mode="compact")
        self.assertEqual(decision["recommended_mode"], "block")
        self.assertEqual(decision["selected_mode"], "compact")
        self.assertEqual(decision["selection_source"], "explicit")
        self.assertTrue(decision["warnings"])

    def test_mode_decision_is_deterministic_across_fact_order(self) -> None:
        first = self.decision(
            surfaces=["interfaces", "data"],
            components=["worker", "api"],
        )
        second = self.decision(
            surfaces=["data", "interfaces"],
            components=["api", "worker"],
        )
        self.assertEqual(first, second)

    def test_validation_recomputes_rules_instead_of_trusting_fingerprint(self) -> None:
        decision = self.decision()
        decision["selected_mode"] = "block"
        decision["fingerprint"] = mode_decision.fingerprint(decision)
        with self.assertRaises(mode_decision.ModeDecisionError):
            mode_decision.validate_mode_decision(decision)

    def test_mode_decision_writer_refuses_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / mode_decision.MODE_DECISION_FILENAME
            spec_pipeline.write_mode_decision(target, self.decision())
            with self.assertRaises(spec_pipeline.PipelineError):
                spec_pipeline.write_mode_decision(target, self.decision())


if __name__ == "__main__":
    unittest.main()
