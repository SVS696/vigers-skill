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
        self.assertEqual(counts["prompt_evals"], 26)

    def test_scale_and_assurance_are_selected_independently(self) -> None:
        large_local = self.decision(
            estimated_blocks=5,
            surfaces=["scenarios", "rules"],
        )
        self.assertEqual(large_local["selected_mode"], "block")
        self.assertEqual(large_local["selected_assurance"], "standard")
        self.assertEqual(large_local["selected_tracking"], "fine")
        self.assertEqual(large_local["selected_projection_sync"], "milestones")

        small_risky = self.decision(
            estimated_blocks=1,
            surfaces=["interfaces"],
            public_contract=True,
        )
        self.assertEqual(small_risky["selected_mode"], "compact")
        self.assertEqual(small_risky["selected_assurance"], "high")

        editorial = self.decision(change_scope="editorial")
        self.assertEqual(editorial["selected_assurance"], "lite")

        projection_only = self.decision(change_scope="projection-only")
        self.assertEqual(projection_only["selected_assurance"], "lite")

    def test_execution_preferences_are_common_then_project_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            preferences_path = Path(temp) / "preferences.json"
            preferences_path.write_text(
                json.dumps(
                    {
                        "schema": 1,
                        "automation_timing": "enabled",
                        "timing_model": "enabled",
                        "progress_tracking": "fine",
                        "task_manager": "singularity",
                        "timing_projection": "task-note",
                        "timing_calendar": "enabled",
                        "deferred_state": "enabled",
                        "state_projection": "project",
                        "progress_projection": "checklist",
                    }
                ),
                encoding="utf-8",
            )
            common = spec_pipeline.load_common_preferences(preferences_path)
            effective = spec_pipeline.resolve_execution_preferences(
                {
                    "automation_timing": "disabled",
                    "timing_model": "inherit",
                    "task_manager": "inherit",
                },
                Path("project-profile.md"),
                common,
            )
            self.assertEqual(effective.automation_timing, "disabled")
            self.assertEqual(effective.timing_model, "disabled")
            self.assertEqual(effective.timing_projection, "none")
            self.assertEqual(effective.timing_calendar, "disabled")
            self.assertEqual(effective.deferred_state, "enabled")
            self.assertEqual(effective.state_projection, "project")
            self.assertEqual(effective.progress_tracking, "fine")
            self.assertEqual(effective.progress_projection, "checklist")

    def test_project_cannot_enable_projection_when_timer_is_disabled(self) -> None:
        with self.assertRaisesRegex(spec_pipeline.PipelineError, "cannot project timing"):
            spec_pipeline.resolve_execution_preferences(
                {
                    "automation_timing": "disabled",
                    "timing_projection": "task-note",
                },
                Path("project-profile.md"),
                spec_pipeline.DEFAULT_EXECUTION_PREFERENCES,
            )

    def test_project_can_disable_deferred_state_and_its_projection(self) -> None:
        common = spec_pipeline.ExecutionPreferences(
            automation_timing="enabled",
            timing_model="enabled",
            progress_tracking="fine",
            task_manager="singularity",
            timing_projection="task-note",
            timing_history="passport",
            timing_calendar="enabled",
            deferred_state="enabled",
            state_projection="project",
            progress_projection="checklist",
            source="test",
        )
        effective = spec_pipeline.resolve_execution_preferences(
            {"deferred_state": "disabled", "state_projection": "inherit"},
            Path("project-profile.md"),
            common,
        )
        self.assertEqual(effective.deferred_state, "disabled")
        self.assertEqual(effective.state_projection, "none")

    def test_state_projection_requires_deferred_state(self) -> None:
        with self.assertRaisesRegex(
            spec_pipeline.PipelineError, "state projection requires deferred state"
        ):
            spec_pipeline.resolve_execution_preferences(
                {"deferred_state": "disabled", "state_projection": "project"},
                Path("project-profile.md"),
                spec_pipeline.DEFAULT_EXECUTION_PREFERENCES,
            )

    def test_legacy_mode_decision_remains_valid(self) -> None:
        payload = self.decision()
        for field in (
            "risk_facts",
            "triggered_assurance_rules",
            "recommended_assurance",
            "requested_assurance",
            "selected_assurance",
            "assurance_selection_source",
            "recommended_tracking",
            "requested_tracking",
            "selected_tracking",
            "recommended_projection_sync",
            "requested_projection_sync",
            "selected_projection_sync",
        ):
            payload.pop(field)
        payload["fingerprint"] = mode_decision.fingerprint(payload)
        mode_decision.validate_mode_decision(
            payload,
            expected_mode="compact",
            expected_profile_id="generic",
        )

    def test_legacy_mode_decision_still_obeys_original_scale_rules(self) -> None:
        payload = self.decision(estimated_blocks=5)
        for field in (
            "risk_facts",
            "triggered_assurance_rules",
            "recommended_assurance",
            "requested_assurance",
            "selected_assurance",
            "assurance_selection_source",
            "recommended_tracking",
            "requested_tracking",
            "selected_tracking",
            "recommended_projection_sync",
            "requested_projection_sync",
            "selected_projection_sync",
        ):
            payload.pop(field)
        payload["selected_mode"] = "compact"
        payload["fingerprint"] = mode_decision.fingerprint(payload)
        with self.assertRaisesRegex(mode_decision.ModeDecisionError, "deterministic rules"):
            mode_decision.validate_mode_decision(
                payload,
                expected_mode="compact",
                expected_profile_id="generic",
            )

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

    def test_simplicity_is_native_and_has_one_bounded_control(self) -> None:
        eval_path = (
            spec_pipeline.ROOT
            / "evals"
            / "prompt-cookbook"
            / "native-simplicity-with-control.json"
        )
        payload = json.loads(eval_path.read_text(encoding="utf-8"))
        expected = payload["expected"]
        self.assertIn(
            "запускать второй полный simplicity-pass после собственной bounded коррекции",
            expected["forbidden_actions"],
        )
        self.assertIn(
            "native simplicity_authoring",
            expected["required_output_signals"],
        )
        self.assertIn(
            "one control before independent review",
            expected["required_output_signals"],
        )
        self.assertIn("protected_floor: pass", expected["required_output_signals"])
        self.assertIn("root_owner and chosen_rung", expected["required_output_signals"])

    def test_process_yagni_reuses_existing_coverage(self) -> None:
        eval_path = (
            spec_pipeline.ROOT
            / "evals"
            / "prompt-cookbook"
            / "process-yagni-no-new-gate.json"
        )
        payload = json.loads(eval_path.read_text(encoding="utf-8"))
        expected = payload["expected"]
        self.assertIn(
            "создавать отдельного simplicity reviewer",
            expected["forbidden_actions"],
        )
        self.assertIn(
            "no new role gate or artifact",
            expected["required_output_signals"],
        )

    def test_execution_economy_preserves_evidence_and_terminal_green(self) -> None:
        eval_path = (
            spec_pipeline.ROOT
            / "evals"
            / "prompt-cookbook"
            / "execution-economy-terminal-green.json"
        )
        payload = json.loads(eval_path.read_text(encoding="utf-8"))
        expected = payload["expected"]
        self.assertIn(
            "ingest all six pages after the source is selected",
            expected["required_actions"],
        )
        self.assertIn(
            "claim final or handoff green from named check exit zero alone",
            expected["forbidden_actions"],
        )
        self.assertIn(
            "projection read-back",
            expected["required_output_signals"],
        )
        self.assertIn(
            "poll_calls and wait_seconds remain human-only telemetry",
            expected["required_output_signals"],
        )

    def test_bounded_recovery_keeps_frozen_case_out_of_reanalysis(self) -> None:
        eval_path = (
            spec_pipeline.ROOT
            / "evals"
            / "prompt-cookbook"
            / "bounded-recovery-frozen-case.json"
        )
        payload = json.loads(eval_path.read_text(encoding="utf-8"))
        expected = payload["expected"]
        self.assertIn(
            "carry stale blocks forward only through rebase-recovery-block after baseline hash checks",
            expected["required_actions"],
        )
        self.assertIn(
            "rerun preliminary or full analysis",
            expected["forbidden_actions"],
        )
        self.assertIn(
            "run a third attempt for the same role, mode, and subject",
            expected["forbidden_actions"],
        )
        self.assertIn(
            "bounded recovery stops before semantic correction",
            expected["required_output_signals"],
        )
        self.assertIn(
            "include stale-pass gates whose evidence or subject already drifted",
            expected["required_actions"],
        )
        self.assertIn(
            "complete-recovery refuses to persist complete before final validation passes",
            expected["required_output_signals"],
        )
        self.assertIn(
            "method-context.* is excluded and its absence is not input-error",
            expected["required_output_signals"],
        )
        for relative in (
            "agents/codex/vigers-spec-reviewer.toml",
            "agents/claude/vigers-spec-reviewer.md",
        ):
            agent_text = (spec_pipeline.ROOT / relative).read_text(encoding="utf-8")
            self.assertIn(
                "review_scope=bounded-recovery|bounded-recovery-final",
                agent_text,
            )
            self.assertIn("отсутствие method context", agent_text)

    def test_legacy_transition_has_one_authority_and_retirement(self) -> None:
        eval_path = (
            spec_pipeline.ROOT
            / "evals"
            / "prompt-cookbook"
            / "legacy-transition-authority.json"
        )
        payload = json.loads(eval_path.read_text(encoding="utf-8"))
        expected = payload["expected"]
        self.assertIn(
            "name one authoritative owner for every migration stage",
            expected["required_actions"],
        )
        self.assertIn(
            "add new business rules to the legacy bridge",
            expected["forbidden_actions"],
        )
        self.assertIn(
            "retirement_trigger",
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
        for case_id in ("UI-NAV", "UI-OPEN", "UI-UNKNOWN", "SYSTEM", "MIXED"):
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
        self.assertIn(
            "mixed branches split or classified",
            expected["required_output_signals"],
        )
        self.assertIn(
            "causal system response remains in UI scenario",
            expected["required_output_signals"],
        )
        self.assertIn(
            "объявлять весь MIXED сценарий system-only, скрывая отсутствующий экран пользовательской ветви",
            expected["forbidden_actions"],
        )
        self.assertIn(
            "приписывать системной ветви экран соседнего пользовательского шага",
            expected["forbidden_actions"],
        )

    def test_acceptance_eval_requires_direct_verification_context(self) -> None:
        eval_path = (
            spec_pipeline.ROOT
            / "evals"
            / "prompt-cookbook"
            / "acceptance-verification-context-barrier.json"
        )
        payload = json.loads(eval_path.read_text(encoding="utf-8"))
        prompt = payload["prompt"]
        expected = payload["expected"]
        for case_id in ("AC-UI-LINK", "AC-UI-GENERIC", "AC-UI-GAP", "AC-API"):
            self.assertIn(f"id: {case_id}", prompt)
        self.assertIn(
            "оставлять UI AC только со ссылкой на REQ, US или общий раздел сценариев",
            expected["forbidden_actions"],
        )
        self.assertIn(
            "AC has direct verification context",
            expected["required_output_signals"],
        )
        self.assertIn(
            "missing tester route is major testability finding",
            expected["required_output_signals"],
        )
        self.assertIn(
            "targeted remediation preserves prior coverage",
            expected["required_output_signals"],
        )

    def test_generic_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            selection = spec_pipeline.detect_profile(Path(temp))
            self.assertEqual(selection.profile_id, "generic")
            self.assertEqual(selection.source, "generic")
            self.assertIsNone(selection.project_root)
            template = selection.recommended_document_template
            self.assertIsNotNone(template)
            assert template is not None
            self.assertEqual(template.template_id, "reader-specification-ru")
            self.assertEqual(template.source, "profile-package")
            self.assertEqual(
                spec_pipeline.display_document_template_file(selection, template),
                "templates/reader-specification-ru.md",
            )

    def test_recommended_template_keeps_reader_specification_structure(self) -> None:
        template = spec_pipeline.package_document_template(
            "reader-specification-ru",
            source="test",
        )
        text = template.template_path.read_text(encoding="utf-8")
        for heading in (
            "## Описание",
            "## User Story",
            "## Сценарии",
            "## Acceptance Criteria",
            "## Definition of Done",
            "## Трассировка",
            "## Границы решения",
        ):
            self.assertIn(heading, text)
        self.assertIn("### GOAL-1.", text)
        self.assertIn("### US-1.", text)
        self.assertIn("### AC-1.", text)
        self.assertIn("### DOD-1.", text)

    def test_project_profile_inherits_package_template_recommendation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "project"
            root.mkdir()
            write_profile(root)
            selection = spec_pipeline.detect_profile(root)
            template = selection.recommended_document_template
            self.assertIsNotNone(template)
            assert template is not None
            self.assertEqual(template.template_id, "reader-specification-ru")
            self.assertEqual(template.source, "package-default")

    def test_project_profile_can_disable_template_recommendation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "project"
            root.mkdir()
            write_profile(root, extra_frontmatter="recommended_document_template: none")
            selection = spec_pipeline.detect_profile(root)
            self.assertIsNone(selection.recommended_document_template)

    def test_project_profile_can_select_project_template(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "project"
            root.mkdir()
            project_template = root / "docs" / "specification.md"
            project_template.parent.mkdir()
            project_template.write_text("# Project template\n", encoding="utf-8")
            write_profile(
                root,
                extra_frontmatter=(
                    "recommended_document_template: project:docs/specification.md"
                ),
            )
            selection = spec_pipeline.detect_profile(root)
            template = selection.recommended_document_template
            self.assertIsNotNone(template)
            assert template is not None
            self.assertEqual(template.source, "project")
            self.assertEqual(template.template_path, project_template.resolve())
            self.assertEqual(
                spec_pipeline.display_document_template_file(selection, template),
                "docs/specification.md",
            )

    def test_project_template_must_exist_inside_project(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "project"
            root.mkdir()
            write_profile(
                root,
                extra_frontmatter="recommended_document_template: project:../outside.md",
            )
            with self.assertRaises(spec_pipeline.PipelineError):
                spec_pipeline.detect_profile(root)

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
