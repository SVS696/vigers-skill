#!/usr/bin/env python3
"""Regression tests for the Vigers research-and-planning preflight."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import planning_case
import case_pipeline
import mode_decision
import vigers_context


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class PlanningCaseTests(unittest.TestCase):
    def init(self, base: Path, *, required_anchors: list[str] | None = None) -> Path:
        root = base / "planning"
        planning_case.init_case(
            root,
            case_id="demo-plan",
            profile_id="generic",
            project_root=None,
            passport_id=None,
            passport_path=None,
            required_anchor_systems=required_anchors,
        )
        return root

    def complete_research(self, root: Path) -> None:
        (root / "intake.md").write_text("# Intake\n\nPrepare a verified change.\n", encoding="utf-8")
        _, manifest = planning_case.load_case(root)
        planning_case.transition(root, manifest, new_state="researching", note=None)
        (root / "research.md").write_text(
            "# Research\n\nConfirmed current tracker and project documentation.\n",
            encoding="utf-8",
        )
        write_json(
            root / "source-map.json",
            {
                "schema": 1,
                "coverage_verdict": "sufficient",
                "queries": [
                    {
                        "system": "tracker",
                        "query": "demo-plan",
                        "status": "completed",
                        "checked_at": "2026-08-06T10:00:00+00:00",
                    }
                ],
                "sources": [
                    {
                        "id": "SRC-001",
                        "system": "user-request",
                        "ref": "task intake",
                        "status": "confirmed",
                        "authority": "request",
                        "checked_at": "2026-08-06T10:00:00+00:00",
                    }
                ],
                "gaps": [],
            },
        )
        _, manifest = planning_case.load_case(root)
        planning_case.transition(root, manifest, new_state="researched", note=None)

    def complete_plan(self, root: Path, *, external: bool = True) -> None:
        write_json(
            root / "artifact-plan.json",
            {
                "schema": 1,
                "targets": (
                    [
                        {
                            "id": "EXT-001",
                            "system": "personal-tasks",
                            "action": "create",
                            "purpose": "personal WIP and review checklist",
                            "authority": "explicit",
                            "publish_gate": "before_review",
                            "read_back_required": True,
                        }
                    ]
                    if external
                    else []
                ),
            },
        )
        write_json(
            root / "plan.json",
            {
                "schema": 1,
                "revision": 1,
                "stages": [
                    {
                        "id": "P01",
                        "title": "Research basis",
                        "outcome": "Sources are sufficient for specification work",
                        "depends_on": [],
                        "source_refs": ["SRC-001"],
                        "exit_criteria": ["Coverage verdict is sufficient"],
                        "checklist": [
                            {"id": "P01-C01", "text": "Verify canonical sources"}
                        ],
                    },
                    {
                        "id": "P02",
                        "title": "Vigers specification",
                        "outcome": "Approved planning handoff enters Vigers",
                        "depends_on": ["P01"],
                        "source_refs": ["SRC-001"],
                        "exit_criteria": ["Planning review is approved"],
                        "checklist": [
                            {"id": "P02-C01", "text": "Run Vigers pipeline"}
                        ],
                    },
                ],
            },
        )
        (root / "plan.md").write_text("# Plan\n\nP01 research, then P02 specification.\n", encoding="utf-8")
        (root / "handoff.md").write_text(
            "# Planning handoff\n\nApproved research basis and dependent stages.\n",
            encoding="utf-8",
        )
        _, manifest = planning_case.load_case(root)
        planning_case.transition(root, manifest, new_state="artifacts_planned", note=None)

    def bind(self, root: Path) -> None:
        _, manifest = planning_case.load_case(root)
        planning_case.record_binding(
            root,
            manifest,
            target_id="EXT-001",
            system="personal-tasks",
            object_id="T-demo",
            url="https://tasks.example.invalid/T-demo",
            read_back_at="2026-08-06T10:30:00+00:00",
        )

    def publish(self, root: Path) -> None:
        _, manifest = planning_case.load_case(root)
        planning_case.transition(root, manifest, new_state="published_for_review", note=None)

    def test_full_flow_exports_approved_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            root = self.init(base)
            self.complete_research(root)
            self.complete_plan(root)
            self.bind(root)
            self.publish(root)
            _, manifest = planning_case.load_case(root)
            planning_case.record_review(
                root,
                manifest,
                verdict="approved",
                actor="owner",
                note="Approved for Vigers",
            )
            output = base / "spec"
            _, manifest = planning_case.load_case(root)
            planning_case.export_handoff(root, manifest, output)
            payload = json.loads((output / planning_case.HANDOFF_JSON).read_text(encoding="utf-8"))
            markdown = (output / planning_case.HANDOFF_MARKDOWN).read_text(encoding="utf-8")
            planning_case.validate_handoff(payload, markdown, expected_profile_id="generic")
            decision = mode_decision.build_mode_decision(
                task="Approved planning handoff",
                profile_id="generic",
                profile_file="profiles/generic.md",
                profile_source="generic",
                project_root=None,
                estimated_blocks=1,
                surfaces=["scenarios"],
                components=[],
                owners=[],
                dependent_parts=False,
                unsafe_single_pass=False,
                project_triggers=[],
                requested_mode=None,
            )
            write_json(output / mode_decision.MODE_DECISION_FILENAME, decision)
            method, method_markdown = vigers_context.build_method_context(
                vigers_context.load_map(), "core", include_fallback=False, exact_ids=[]
            )
            vigers_context.write_method_context(output, method, method_markdown)
            case_pipeline.init_case(
                output,
                case_id="demo-spec",
                mode="compact",
                intent="create",
                profile_id="generic",
                route_id="core",
                project_root=None,
                allow_unplanned=False,
            )
            _, spec_manifest, spec_ledger = case_pipeline.load_case(output)
            self.assertEqual(spec_manifest["planning_handoff"]["planning_case_id"], "demo-plan")
            self.assertEqual(
                case_pipeline.validate_case(output, spec_manifest, spec_ledger, final=False),
                [],
            )
            _, final_manifest = planning_case.load_case(root)
            self.assertEqual(final_manifest["state"], "handed_to_vigers")
            self.assertEqual(planning_case.validate_case(root, final_manifest, final=True), [])

    def test_research_is_a_required_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self.init(Path(temp))
            (root / "intake.md").write_text("# Intake\n\nDemo\n", encoding="utf-8")
            _, manifest = planning_case.load_case(root)
            planning_case.transition(root, manifest, new_state="researching", note=None)
            (root / "research.md").write_text("# Research\n\nNo sources.\n", encoding="utf-8")
            with self.assertRaises(planning_case.PlanningError):
                _, manifest = planning_case.load_case(root)
                planning_case.transition(root, manifest, new_state="researched", note=None)

    def test_profile_required_anchors_precede_read_only_research(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self.init(
                Path(temp),
                required_anchors=["Tracker", "PersonalTasks"],
            )
            (root / "intake.md").write_text("# Intake\n\nDemo\n", encoding="utf-8")
            _, manifest = planning_case.load_case(root)
            with self.assertRaises(planning_case.PlanningError):
                planning_case.transition(root, manifest, new_state="researching", note=None)

            for target_id, system, object_id in (
                ("EXT-001", "Tracker", "12345"),
                ("EXT-002", "PersonalTasks", "T-demo"),
            ):
                _, manifest = planning_case.load_case(root)
                planning_case.record_binding(
                    root,
                    manifest,
                    target_id=target_id,
                    system=system,
                    object_id=object_id,
                    url=f"https://example.invalid/{object_id}",
                    read_back_at="2026-08-06T10:10:00+00:00",
                )

            _, manifest = planning_case.load_case(root)
            planning_case.transition(root, manifest, new_state="researching", note=None)
            _, manifest = planning_case.load_case(root)
            with self.assertRaises(planning_case.PlanningError):
                planning_case.record_binding(
                    root,
                    manifest,
                    target_id="EXT-001",
                    system="Tracker",
                    object_id="12345",
                    url=None,
                    read_back_at="2026-08-06T10:11:00+00:00",
                )

    def test_existing_anchor_can_be_linked_before_research(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self.init(Path(temp), required_anchors=["PersonalTasks"])
            (root / "intake.md").write_text("# Intake\n\nDemo\n", encoding="utf-8")

            _, manifest = planning_case.load_case(root)
            planning_case.record_binding(
                root,
                manifest,
                target_id="EXT-001",
                system="PersonalTasks",
                object_id="T-existing",
                url="https://tasks.example.invalid/T-existing",
                read_back_at="2026-08-06T10:10:00+00:00",
                action="link",
            )
            _, manifest = planning_case.load_case(root)
            planning_case.transition(root, manifest, new_state="researching", note=None)

            _, manifest = planning_case.load_case(root)
            self.assertEqual(manifest["state"], "researching")
            bindings = json.loads((root / "bindings.json").read_text(encoding="utf-8"))
            self.assertEqual(len(bindings["external"]), 1)
            self.assertEqual(bindings["external"][0]["object_id"], "T-existing")
            artifact_plan = json.loads(
                (root / "artifact-plan.json").read_text(encoding="utf-8")
            )
            self.assertEqual(artifact_plan["targets"][0]["action"], "link")

    def test_required_anchor_cannot_be_removed_from_artifact_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self.init(Path(temp), required_anchors=["PersonalTasks"])
            (root / "intake.md").write_text("# Intake\n\nDemo\n", encoding="utf-8")
            write_json(root / "artifact-plan.json", {"schema": 1, "targets": []})
            _, manifest = planning_case.load_case(root)
            with self.assertRaises(planning_case.PlanningError):
                planning_case.transition(root, manifest, new_state="researching", note=None)

    def test_blocked_intake_cannot_resume_without_required_anchor(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self.init(Path(temp), required_anchors=["PersonalTasks"])
            (root / "intake.md").write_text("# Intake\n\nDemo\n", encoding="utf-8")
            _, manifest = planning_case.load_case(root)
            planning_case.transition(root, manifest, new_state="blocked", note="anchor unavailable")
            _, manifest = planning_case.load_case(root)
            with self.assertRaises(planning_case.PlanningError):
                planning_case.transition(
                    root,
                    manifest,
                    new_state="researching",
                    note="retry",
                )

            _, manifest = planning_case.load_case(root)
            planning_case.record_binding(
                root,
                manifest,
                target_id="EXT-001",
                system="PersonalTasks",
                object_id="T-restored",
                url="https://tasks.example.invalid/T-restored",
                read_back_at="2026-08-06T10:15:00+00:00",
            )
            _, manifest = planning_case.load_case(root)
            planning_case.transition(
                root,
                manifest,
                new_state="researching",
                note="anchor restored",
            )
            self.assertEqual(manifest["state"], "researching")

    def test_early_anchor_binding_can_be_corrected_during_research(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self.init(Path(temp), required_anchors=["PersonalTasks"])
            (root / "intake.md").write_text("# Intake\n\nDemo\n", encoding="utf-8")
            _, manifest = planning_case.load_case(root)
            planning_case.record_binding(
                root,
                manifest,
                target_id="EXT-001",
                system="PersonalTasks",
                object_id="T-initial",
                url=None,
                read_back_at="2026-08-06T10:10:00+00:00",
            )
            _, manifest = planning_case.load_case(root)
            planning_case.transition(root, manifest, new_state="researching", note=None)
            _, manifest = planning_case.load_case(root)
            planning_case.record_binding(
                root,
                manifest,
                target_id="EXT-001",
                system="PersonalTasks",
                object_id="T-epic",
                url=None,
                read_back_at="2026-08-06T10:20:00+00:00",
                action="link",
                replace=True,
            )
            bindings = json.loads((root / "bindings.json").read_text(encoding="utf-8"))
            self.assertEqual(bindings["external"][0]["object_id"], "T-epic")

    def test_replacing_binding_requires_explicit_action(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self.init(Path(temp), required_anchors=["PersonalTasks"])
            (root / "intake.md").write_text("# Intake\n\nDemo\n", encoding="utf-8")
            _, manifest = planning_case.load_case(root)
            planning_case.record_binding(
                root,
                manifest,
                target_id="EXT-001",
                system="PersonalTasks",
                object_id="T-initial",
                url=None,
                read_back_at="2026-08-06T10:10:00+00:00",
            )
            _, manifest = planning_case.load_case(root)
            planning_case.transition(root, manifest, new_state="researching", note=None)
            _, manifest = planning_case.load_case(root)
            with self.assertRaises(planning_case.PlanningError):
                planning_case.record_binding(
                    root,
                    manifest,
                    target_id="EXT-001",
                    system="PersonalTasks",
                    object_id="T-other",
                    url=None,
                    read_back_at="2026-08-06T10:20:00+00:00",
                    replace=True,
                )

    def test_publish_requires_external_read_back_binding(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self.init(Path(temp))
            self.complete_research(root)
            self.complete_plan(root)
            with self.assertRaises(planning_case.PlanningError):
                self.publish(root)

    def test_changes_requested_starts_new_revision(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self.init(Path(temp))
            self.complete_research(root)
            self.complete_plan(root, external=False)
            self.publish(root)
            _, manifest = planning_case.load_case(root)
            planning_case.record_review(
                root,
                manifest,
                verdict="changes_requested",
                actor="owner",
                note="Research one more source",
            )
            _, manifest = planning_case.load_case(root)
            planning_case.transition(root, manifest, new_state="researching", note="research delta")
            self.assertEqual(manifest["revision"], 2)
            self.assertTrue((root / "revisions" / "revision-001" / "plan.json").is_file())

    def test_blocked_review_snapshot_starts_new_revision_on_resume(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self.init(Path(temp))
            self.complete_research(root)
            self.complete_plan(root, external=False)
            self.publish(root)
            _, manifest = planning_case.load_case(root)
            planning_case.transition(root, manifest, new_state="blocked", note="source unavailable")
            _, manifest = planning_case.load_case(root)
            planning_case.transition(root, manifest, new_state="researching", note="source restored")
            self.assertEqual(manifest["revision"], 2)
            self.assertTrue((root / "reviews" / "revision-002.md").is_file())

    def test_protected_states_require_review_and_export_commands(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self.init(Path(temp))
            self.complete_research(root)
            self.complete_plan(root, external=False)
            self.publish(root)
            _, manifest = planning_case.load_case(root)
            with self.assertRaises(planning_case.PlanningError):
                planning_case.transition(root, manifest, new_state="approved", note="bypass")

            planning_case.record_review(
                root,
                manifest,
                verdict="approved",
                actor="owner",
                note="Approved",
            )
            _, manifest = planning_case.load_case(root)
            with self.assertRaises(planning_case.PlanningError):
                planning_case.transition(
                    root,
                    manifest,
                    new_state="handed_to_vigers",
                    note="bypass",
                )

    def test_approved_case_can_start_a_new_revision_through_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self.init(Path(temp))
            self.complete_research(root)
            self.complete_plan(root, external=False)
            self.publish(root)
            _, manifest = planning_case.load_case(root)
            planning_case.record_review(
                root,
                manifest,
                verdict="approved",
                actor="owner",
                note="Approved",
            )
            _, manifest = planning_case.load_case(root)
            planning_case.transition(root, manifest, new_state="blocked", note="new fact")
            _, manifest = planning_case.load_case(root)
            planning_case.transition(root, manifest, new_state="researching", note="revise")
            self.assertEqual(manifest["revision"], 2)
            self.assertIsNone(manifest["approval"])

    def test_after_approval_target_requires_binding_before_export(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            root = self.init(base)
            self.complete_research(root)
            self.complete_plan(root, external=False)
            artifact_plan = {
                "schema": 1,
                "targets": [
                    {
                        "id": "EXT-001",
                        "system": "tracker",
                        "action": "create",
                        "purpose": "Approved tracker issue",
                        "authority": "profile",
                        "publish_gate": "after_approval",
                        "read_back_required": True,
                    }
                ],
            }
            (root / "artifact-plan.json").write_text(
                json.dumps(artifact_plan, ensure_ascii=False, indent=4),
                encoding="utf-8",
            )
            self.publish(root)
            _, manifest = planning_case.load_case(root)
            planning_case.record_review(
                root,
                manifest,
                verdict="approved",
                actor="owner",
                note="Approved",
            )
            _, manifest = planning_case.load_case(root)
            with self.assertRaises(planning_case.PlanningError):
                planning_case.export_handoff(root, manifest, base / "missing-binding")

            approved_plan_bytes = (root / "artifact-plan.json").read_bytes()
            planning_case.record_binding(
                root,
                manifest,
                target_id="EXT-001",
                system="tracker",
                object_id="DEMO-1",
                url="https://tracker.example.invalid/DEMO-1",
                read_back_at="2026-08-06T11:00:00+00:00",
                action="create",
            )
            self.assertEqual((root / "artifact-plan.json").read_bytes(), approved_plan_bytes)
            _, manifest = planning_case.load_case(root)
            output = base / "with-binding"
            planning_case.export_handoff(root, manifest, output)
            _, manifest = planning_case.load_case(root)
            self.assertEqual(manifest["state"], "handed_to_vigers")
            self.assertEqual(planning_case.validate_case(root, manifest, final=True), [])

            bindings_path = root / "bindings.json"
            bindings = json.loads(bindings_path.read_text(encoding="utf-8"))
            bindings["external"][0]["object_id"] = "DEMO-999"
            write_json(bindings_path, bindings)
            _, manifest = planning_case.load_case(root)
            self.assertIn(
                "external bindings changed after handoff export",
                planning_case.validate_case(root, manifest, final=True),
            )

    def test_handoff_rejects_required_anchor_without_read_back_binding(self) -> None:
        markdown = "# Planning handoff\n\nVerified plan.\n"
        payload = {
            "schema": planning_case.HANDOFF_SCHEMA_VERSION,
            "planning_case_id": "demo-plan",
            "planning_revision": 1,
            "profile_id": "demo",
            "project_root": "/tmp/demo",
            "required_anchor_systems": ["PersonalTasks"],
            "passport": None,
            "external_bindings": [],
            "approval": {"revision": 1},
            "artifact_hashes": {},
            "content_sha256": hashlib.sha256(markdown.encode("utf-8")).hexdigest(),
        }
        payload["fingerprint"] = planning_case.canonical_fingerprint(payload)
        with self.assertRaises(planning_case.PlanningError):
            planning_case.validate_handoff(payload, markdown)

    def test_generic_profile_cannot_override_nearest_project_overlay(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            profile_dir = project / ".vigers"
            profile_dir.mkdir(parents=True)
            template = (
                Path(__file__).resolve().parents[1]
                / "profiles"
                / "project-profile-template.md"
            ).read_text(encoding="utf-8")
            (profile_dir / "profile.md").write_text(
                template.replace("profile_id: example", "profile_id: demo"),
                encoding="utf-8",
            )
            with self.assertRaises(planning_case.PlanningError):
                planning_case.resolve_init_profile("generic", project)

    def test_final_validation_requires_exported_handoff_record(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self.init(Path(temp))
            _, manifest = planning_case.load_case(root)
            manifest["state"] = "handed_to_vigers"
            manifest["approval"] = {"revision": 1}
            planning_case.save_case(root, manifest)
            errors = planning_case.validate_case(root, manifest, final=True)
            self.assertIn("handed planning case has no exported handoff record", errors)

    def test_approved_artifacts_are_immutable(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self.init(Path(temp))
            self.complete_research(root)
            self.complete_plan(root, external=False)
            self.publish(root)
            _, manifest = planning_case.load_case(root)
            planning_case.record_review(
                root,
                manifest,
                verdict="approved",
                actor="owner",
                note="Approved",
            )
            (root / "plan.md").write_text("tampered\n", encoding="utf-8")
            _, manifest = planning_case.load_case(root)
            errors = planning_case.validate_case(root, manifest, final=False)
            self.assertIn("approved artifacts changed after snapshot", errors)

    def test_failed_approval_does_not_write_partial_verdict(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self.init(Path(temp))
            self.complete_research(root)
            self.complete_plan(root, external=False)
            self.publish(root)
            review_path = root / "reviews" / "revision-001.md"
            original_review = review_path.read_text(encoding="utf-8")
            (root / "plan.md").write_text("# Plan\n\nChanged after publication.\n", encoding="utf-8")

            _, manifest = planning_case.load_case(root)
            with self.assertRaises(planning_case.PlanningError):
                planning_case.record_review(
                    root,
                    manifest,
                    verdict="approved",
                    actor="owner",
                    note="Approve stale snapshot",
                )

            _, manifest = planning_case.load_case(root)
            self.assertEqual(manifest["state"], "published_for_review")
            self.assertIsNone(manifest["approval"])
            self.assertEqual(review_path.read_text(encoding="utf-8"), original_review)

    def test_plan_dependency_cycle_is_rejected(self) -> None:
        payload = {
            "schema": 1,
            "revision": 1,
            "stages": [
                {
                    "id": "P01",
                    "title": "One",
                    "outcome": "One",
                    "depends_on": ["P02"],
                    "source_refs": ["SRC-001"],
                    "exit_criteria": ["done"],
                    "checklist": [{"id": "P01-C01", "text": "one"}],
                },
                {
                    "id": "P02",
                    "title": "Two",
                    "outcome": "Two",
                    "depends_on": ["P01"],
                    "source_refs": ["SRC-001"],
                    "exit_criteria": ["done"],
                    "checklist": [{"id": "P02-C01", "text": "two"}],
                },
            ],
        }
        errors = planning_case.validate_plan(payload, 1, {"SRC-001"})
        self.assertTrue(any("cycle" in error.lower() for error in errors))


if __name__ == "__main__":
    unittest.main()
