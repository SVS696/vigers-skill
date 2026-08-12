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
working_projection: {working_projection}
{extra_frontmatter}
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
    working_projection: str = "optional",
    extra_frontmatter: str = "",
) -> Path:
    profile = root / ".vigers" / "profile.md"
    profile.parent.mkdir(parents=True)
    profile.write_text(
        PROFILE_BODY.format(
            profile_id=profile_id,
            planning_anchors=planning_anchors,
            working_projection=working_projection,
            extra_frontmatter=extra_frontmatter,
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
        self.assertEqual(counts["prompt_evals"], 14)

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

    def test_diagram_eval_requires_decomposition_and_visual_readback(self) -> None:
        eval_path = (
            spec_pipeline.ROOT
            / "evals"
            / "prompt-cookbook"
            / "diagram-complexity-barrier.json"
        )
        payload = json.loads(eval_path.read_text(encoding="utf-8"))
        expected = payload["expected"]
        self.assertIn(
            "собрать все поверхности в одну гигантскую диаграмму",
            expected["forbidden_actions"],
        )
        self.assertIn(
            "visual read-back фактического render",
            expected["required_output_signals"],
        )

    def test_diagram_lifecycle_eval_blocks_early_publication_artifacts(self) -> None:
        eval_path = (
            spec_pipeline.ROOT
            / "evals"
            / "prompt-cookbook"
            / "diagram-render-lifecycle-barrier.json"
        )
        payload = json.loads(eval_path.read_text(encoding="utf-8"))
        expected = payload["expected"]
        self.assertIn(
            "сохранить PNG рядом с постановкой на author-pass",
            expected["forbidden_actions"],
        )
        self.assertIn(
            "publication gate: not reached",
            expected["required_output_signals"],
        )

    def test_early_projection_eval_rejects_hidden_case_as_user_artifact(self) -> None:
        eval_path = (
            spec_pipeline.ROOT
            / "evals"
            / "prompt-cookbook"
            / "early-working-projection.json"
        )
        payload = json.loads(eval_path.read_text(encoding="utf-8"))
        expected = payload["expected"]
        self.assertIn(
            "считать .vigers case достаточной видимостью для пользователя",
            expected["forbidden_actions"],
        )
        self.assertIn(
            "read-back before continuation",
            expected["required_output_signals"],
        )

    def test_projection_target_eval_defers_to_project_profile(self) -> None:
        eval_path = (
            spec_pipeline.ROOT
            / "evals"
            / "prompt-cookbook"
            / "profile-owned-working-projection.json"
        )
        payload = json.loads(eval_path.read_text(encoding="utf-8"))
        expected = payload["expected"]
        self.assertIn(
            "создавать локальный файл постановки вопреки project profile",
            expected["forbidden_actions"],
        )
        self.assertIn(
            "external adapter read-back receipt",
            expected["required_output_signals"],
        )

    def test_live_checklist_eval_preserves_order_freedom_and_completion_barrier(self) -> None:
        eval_path = (
            spec_pipeline.ROOT
            / "evals"
            / "prompt-cookbook"
            / "live-checklist-completion-barrier.json"
        )
        payload = json.loads(eval_path.read_text(encoding="utf-8"))
        expected = payload["expected"]
        self.assertIn(
            "объявлять порядок checklist обязательной dependency",
            expected["forbidden_actions"],
        )
        self.assertIn(
            "completion_barrier: required",
            expected["required_output_signals"],
        )

    def test_traceability_eval_rejects_plain_and_compressed_ids(self) -> None:
        eval_path = (
            spec_pipeline.ROOT
            / "evals"
            / "prompt-cookbook"
            / "traceability-link-barrier.json"
        )
        payload = json.loads(eval_path.read_text(encoding="utf-8"))
        expected = payload["expected"]
        self.assertIn(
            "оставлять semantic IDs обычным текстом или сокращённым диапазоном",
            expected["forbidden_actions"],
        )
        self.assertIn(
            "every semantic ID is an individually resolved link",
            expected["required_output_signals"],
        )

    def test_reader_projection_eval_separates_acceptance_from_developer_checks(self) -> None:
        eval_path = (
            spec_pipeline.ROOT
            / "evals"
            / "prompt-cookbook"
            / "reader-projection-barrier.json"
        )
        payload = json.loads(eval_path.read_text(encoding="utf-8"))
        expected = payload["expected"]
        self.assertIn(
            "считать автоматические тесты основным содержанием AC или DoD",
            expected["forbidden_actions"],
        )
        self.assertIn(
            "machine check before scoped re-review",
            expected["required_output_signals"],
        )
        self.assertIn(
            "public GOAL preserved",
            expected["required_output_signals"],
        )

    def test_user_journey_eval_requires_screen_context_without_ui_invention(self) -> None:
        eval_path = (
            spec_pipeline.ROOT
            / "evals"
            / "prompt-cookbook"
            / "user-journey-screen-context-barrier.json"
        )
        payload = json.loads(eval_path.read_text(encoding="utf-8"))
        prompt = payload["prompt"]
        expected = payload["expected"]
        for case_id in ("UI-NAV", "UI-OPEN", "UI-UNKNOWN", "SYSTEM"):
            self.assertIn(f"id: {case_id}", prompt)
        self.assertNotIn("Настройка отчётных периодов", prompt)
        self.assertNotIn("Бизнес-администрирование", prompt)
        self.assertIn(
            "придумывать экран, маршрут, видимую подпись или technical ID",
            expected["forbidden_actions"],
        )
        self.assertIn(
            "screen on entry and evidenced navigation",
            expected["required_output_signals"],
        )
        self.assertIn(
            "no route repetition on same screen",
            expected["required_output_signals"],
        )
        self.assertIn(
            "already-open screen has no reconstructed route",
            expected["required_output_signals"],
        )
        self.assertIn(
            "system-only has no screen",
            expected["required_output_signals"],
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

    def test_project_overlay_exposes_working_projection_policy(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "project"
            root.mkdir()
            write_profile(root, working_projection="required")
            selection = spec_pipeline.detect_profile(root)
            self.assertEqual(selection.working_projection, "required")

    def test_empty_working_projection_policy_defaults_to_optional(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "project"
            root.mkdir()
            write_profile(root, working_projection="")
            selection = spec_pipeline.detect_profile(root)
            self.assertEqual(selection.working_projection, "optional")

    def test_invalid_working_projection_policy_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "project"
            root.mkdir()
            write_profile(root, working_projection="sometimes")
            with self.assertRaises(spec_pipeline.PipelineError):
                spec_pipeline.detect_profile(root)

    def test_project_overlay_exposes_pinned_document_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "project"
            root.mkdir()
            write_profile(
                root,
                extra_frontmatter=(
                    "document_checks: draft, working_projection\n"
                    "document_required_headings: Оглавление, Описание, User Story, Трассировка\n"
                    "document_toc: obsidian-h2-exact\n"
                    "document_toc_heading: Оглавление\n"
                    "document_toc_separators: required\n"
                    "document_user_story_policy: numbered-role-goal-value\n"
                    "document_user_story_heading: User Story\n"
                    "document_user_story_id_prefix: US\n"
                    "document_user_story_title_separator: .\n"
                    "document_user_story_role_label: As\n"
                    "document_user_story_goal_label: I want\n"
                    "document_user_story_value_label: so that\n"
                    "document_traceability_policy: semantic-id-links\n"
                    "document_traceability_heading: Трассировка\n"
                    "document_traceability_link_style: obsidian-heading-exact\n"
                    "document_traceability_id_prefixes: US, REQ, AC, DOD"
                ),
            )
            selection = spec_pipeline.detect_profile(root)
            self.assertIsNotNone(selection.document_contract)
            assert selection.document_contract is not None
            self.assertEqual(
                selection.document_contract["checks"],
                ["draft", "working_projection"],
            )
            self.assertEqual(
                selection.document_contract["user_story"],
                {
                    "policy": "numbered-role-goal-value",
                    "heading": "User Story",
                    "id_prefix": "US",
                    "title_separator": ".",
                    "role_label": "As",
                    "goal_label": "I want",
                    "value_label": "so that",
                },
            )
            self.assertEqual(
                selection.document_contract["traceability"],
                {
                    "policy": "semantic-id-links",
                    "heading": "Трассировка",
                    "link_style": "obsidian-heading-exact",
                    "id_prefixes": ["US", "REQ", "AC", "DOD"],
                },
            )

    def test_partial_document_contract_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "project"
            root.mkdir()
            write_profile(root, extra_frontmatter="document_toc: obsidian-h2-exact")
            with self.assertRaises(spec_pipeline.PipelineError):
                spec_pipeline.detect_profile(root)

    def test_partial_user_story_contract_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "project"
            root.mkdir()
            write_profile(
                root,
                extra_frontmatter=(
                    "document_checks: draft\n"
                    "document_required_headings: Оглавление, User Story\n"
                    "document_toc: obsidian-h2-exact\n"
                    "document_toc_heading: Оглавление\n"
                    "document_toc_separators: optional\n"
                    "document_user_story_policy: numbered-role-goal-value"
                ),
            )
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
                PROFILE_BODY.format(
                    profile_id="external",
                    planning_anchors="",
                    working_projection="optional",
                    extra_frontmatter="",
                ),
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
