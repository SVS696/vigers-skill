#!/usr/bin/env python3
"""Regression tests for resumable Vigers case state."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import case_pipeline
import mode_decision
import vigers_context


def replace_todo(path: Path, text: str) -> None:
    path.write_text(text + "\n", encoding="utf-8")


def add_definition(root: Path, block_id: str, semantic_id: str, kind: str) -> None:
    path = root / "blocks" / f"{block_id}.index.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["definitions"].append(
        {
            "id": semantic_id,
            "kind": kind,
            "summary": f"Definition {semantic_id}",
            "source_refs": ["SRC-1"],
        }
    )
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class CasePipelineTests(unittest.TestCase):
    def write_mode_decision(
        self,
        root: Path,
        *,
        selected_mode: str = "block",
        profile_id: str = "generic",
    ) -> dict[str, object]:
        is_block = selected_mode == "block"
        payload = mode_decision.build_mode_decision(
            task="Prepare a specification",
            profile_id=profile_id,
            profile_file="profiles/generic.md",
            profile_source="generic",
            project_root=None,
            estimated_blocks=3 if is_block else 1,
            surfaces=["scenarios", "interfaces"] if is_block else ["scenarios"],
            components=[],
            owners=[],
            dependent_parts=False,
            unsafe_single_pass=False,
            project_triggers=[],
            requested_mode=None,
        )
        root.mkdir(parents=True, exist_ok=True)
        (root / mode_decision.MODE_DECISION_FILENAME).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return payload

    def write_method_context(
        self,
        root: Path,
        *,
        route_id: str = "core",
    ) -> dict[str, object]:
        payload, markdown = vigers_context.build_method_context(
            vigers_context.load_map(),
            route_id,
        )
        vigers_context.write_method_context(root, payload, markdown)
        return payload

    def init(self, base: Path, mode: str = "block") -> Path:
        root = base / "case"
        self.write_method_context(root)
        self.write_mode_decision(root, selected_mode=mode)
        case_pipeline.init_case(
            root,
            case_id="demo-1",
            mode=mode,
            intent="create",
            profile_id="generic",
            route_id="core",
            project_root=None,
        )
        replace_todo(root / "kernel.md", "# Kernel\n\nStable kernel")
        loaded_root, manifest, ledger = case_pipeline.load_case(root)
        case_pipeline.refresh_kernel(loaded_root, manifest, ledger, [])
        return root

    def add(self, root: Path, block_id: str, depends_on: list[str] | None = None) -> None:
        loaded_root, manifest, ledger = case_pipeline.load_case(root)
        case_pipeline.add_block(
            loaded_root,
            manifest,
            ledger,
            block_id=block_id,
            title=f"Block {block_id}",
            kind="scenarios",
            depends_on=depends_on or [],
        )

    def transition(self, root: Path, block_id: str, status: str, note: str | None = None) -> None:
        loaded_root, manifest, ledger = case_pipeline.load_case(root)
        case_pipeline.transition_block(
            loaded_root,
            manifest,
            ledger,
            block_id=block_id,
            new_status=status,
            note=note,
        )

    def analyze_and_review(self, root: Path, block_id: str, semantic_id: str) -> None:
        self.transition(root, block_id, "ready")
        self.transition(root, block_id, "in_progress")
        replace_todo(root / "blocks" / f"{block_id}.md", f"# {block_id}\n\nAnalysis")
        add_definition(root, block_id, semantic_id, "scenario")
        self.transition(root, block_id, "analyzed")
        replace_todo(root / "reviews" / f"{block_id}.md", f"# Review {block_id}\n\nPASS")
        self.transition(root, block_id, "reviewed")

    def test_init_creates_resumable_package(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self.init(Path(temp))
            self.assertTrue((root / "manifest.json").is_file())
            self.assertTrue((root / "ledger.json").is_file())
            self.assertTrue((root / "status.md").is_file())
            _, manifest, ledger = case_pipeline.load_case(root)
            self.assertEqual(manifest["schema"], 2)
            self.assertEqual(ledger["blocks"], [])

    def test_init_binds_precomputed_mode_decision(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "case"
            self.write_method_context(root)
            decision = self.write_mode_decision(root)
            case_pipeline.init_case(
                root,
                case_id="mode-bound",
                mode="block",
                intent="create",
                profile_id="generic",
                route_id="core",
                project_root=None,
            )
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            self.assertEqual(
                manifest["mode_decision"]["fingerprint"],
                decision["fingerprint"],
            )
            self.assertEqual(case_pipeline.validate_case(loaded_root, manifest, ledger, final=False), [])

    def test_init_binds_pinned_method_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "case"
            method = self.write_method_context(root, route_id="traceability")
            self.write_mode_decision(root)
            case_pipeline.init_case(
                root,
                case_id="method-bound",
                mode="block",
                intent="create",
                profile_id="generic",
                route_id="traceability",
                project_root=None,
            )
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            self.assertEqual(
                manifest["method_context"]["fingerprint"],
                method["fingerprint"],
            )
            self.assertEqual(
                case_pipeline.validate_case(loaded_root, manifest, ledger, final=False),
                [],
            )

    def test_init_rejects_mode_decision_binding_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "case"
            self.write_method_context(root)
            self.write_mode_decision(root, selected_mode="block")
            with self.assertRaises(case_pipeline.CaseError):
                case_pipeline.init_case(
                    root,
                    case_id="mode-mismatch",
                    mode="compact",
                    intent="create",
                    profile_id="generic",
                    route_id="core",
                    project_root=None,
                )

    def test_init_requires_mode_decision_without_migration_escape_hatch(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "case"
            with self.assertRaises(case_pipeline.CaseError):
                case_pipeline.init_case(
                    root,
                    case_id="mode-required",
                    mode="compact",
                    intent="create",
                    profile_id="generic",
                    route_id="core",
                    project_root=None,
                )

    def test_init_requires_method_context_without_migration_escape_hatch(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "case"
            self.write_mode_decision(root, selected_mode="compact")
            with self.assertRaises(case_pipeline.CaseError):
                case_pipeline.init_case(
                    root,
                    case_id="method-required",
                    mode="compact",
                    intent="create",
                    profile_id="generic",
                    route_id="core",
                    project_root=None,
                )

    def test_init_rejects_method_route_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "case"
            self.write_method_context(root, route_id="traceability")
            self.write_mode_decision(root)
            with self.assertRaises(case_pipeline.CaseError):
                case_pipeline.init_case(
                    root,
                    case_id="method-mismatch",
                    mode="block",
                    intent="create",
                    profile_id="generic",
                    route_id="core",
                    project_root=None,
                )

    def test_init_allows_explicit_unrecorded_migration_case(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "case"
            case_pipeline.init_case(
                root,
                case_id="legacy-mode",
                mode="compact",
                intent="create",
                profile_id="generic",
                route_id="core",
                project_root=None,
                allow_unrecorded_mode=True,
                allow_unrecorded_method=True,
            )
            _, manifest, _ = case_pipeline.load_case(root)
            self.assertIsNone(manifest["mode_decision"])

    def test_validation_detects_tampered_mode_decision(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "case"
            self.write_method_context(root)
            self.write_mode_decision(root)
            case_pipeline.init_case(
                root,
                case_id="mode-tamper",
                mode="block",
                intent="create",
                profile_id="generic",
                route_id="core",
                project_root=None,
            )
            path = root / mode_decision.MODE_DECISION_FILENAME
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["task"] = "Tampered"
            path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            errors = case_pipeline.validate_case(loaded_root, manifest, ledger, final=False)
            self.assertTrue(any("fingerprint mismatch" in error for error in errors))

    def test_validation_detects_tampered_method_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self.init(Path(temp))
            path = root / vigers_context.METHOD_CONTEXT_MARKDOWN
            path.write_text(path.read_text(encoding="utf-8") + "tampered\n", encoding="utf-8")
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            errors = case_pipeline.validate_case(loaded_root, manifest, ledger, final=False)
            self.assertTrue(any("Markdown hash mismatch" in error for error in errors))

    def test_dependency_must_be_reviewed_before_ready(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self.init(Path(temp))
            self.add(root, "B01")
            self.add(root, "B02", ["B01"])
            with self.assertRaises(case_pipeline.CaseError):
                self.transition(root, "B02", "ready")
            self.analyze_and_review(root, "B01", "SCN-B01-001")
            self.transition(root, "B02", "ready")

    def test_kernel_change_marks_completed_block_and_dependents_stale(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self.init(Path(temp))
            self.add(root, "B01")
            self.add(root, "B02", ["B01"])
            self.analyze_and_review(root, "B01", "SCN-B01-001")
            replace_todo(root / "kernel.md", "# Kernel\n\nChanged")
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            stale = case_pipeline.refresh_kernel(loaded_root, manifest, ledger, ["B01"])
            self.assertEqual(stale, ["B01"])
            _, _, ledger = case_pipeline.load_case(root)
            self.assertEqual(case_pipeline.blocks_by_id(ledger)["B01"]["status"], "stale")

    def test_duplicate_semantic_ids_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self.init(Path(temp))
            self.add(root, "B01")
            self.add(root, "B02")
            self.analyze_and_review(root, "B01", "SCN-B01-001")
            self.transition(root, "B02", "ready")
            self.transition(root, "B02", "in_progress")
            replace_todo(root / "blocks" / "B02.md", "# B02\n\nAnalysis")
            index_path = root / "blocks" / "B02.index.json"
            payload = json.loads(index_path.read_text(encoding="utf-8"))
            payload["definitions"].append(
                {
                    "id": "SCN-B02-001",
                    "kind": "scenario",
                    "summary": "Duplicate after tampering",
                    "source_refs": [],
                }
            )
            index_path.write_text(json.dumps(payload), encoding="utf-8")
            self.transition(root, "B02", "analyzed")
            payload = json.loads(index_path.read_text(encoding="utf-8"))
            payload["definitions"][0]["id"] = "SCN-B01-001"
            index_path.write_text(json.dumps(payload), encoding="utf-8")
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            errors = case_pipeline.validate_case(loaded_root, manifest, ledger, final=False)
            self.assertTrue(any("invalid semantic id" in item for item in errors))

    def test_unresolved_trace_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self.init(Path(temp))
            self.add(root, "B01")
            self.transition(root, "B01", "ready")
            self.transition(root, "B01", "in_progress")
            replace_todo(root / "blocks" / "B01.md", "# B01\n\nAnalysis")
            add_definition(root, "B01", "REQ-B01-001", "requirement")
            index_path = root / "blocks" / "B01.index.json"
            payload = json.loads(index_path.read_text(encoding="utf-8"))
            payload["trace"] = [{"from": "REQ-B01-001", "to": ["SCN-B01-999"]}]
            index_path.write_text(json.dumps(payload), encoding="utf-8")
            self.transition(root, "B01", "analyzed")
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            errors = case_pipeline.validate_case(loaded_root, manifest, ledger, final=False)
            self.assertTrue(any("does not resolve" in item for item in errors))

    def test_final_trace_requires_ac_for_each_requirement(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self.init(Path(temp))
            self.add(root, "B01")
            self.transition(root, "B01", "ready")
            self.transition(root, "B01", "in_progress")
            replace_todo(root / "blocks" / "B01.md", "# B01\n\nAnalysis")
            path = root / "blocks" / "B01.index.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["definitions"] = [
                {"id": "SCN-B01-001", "kind": "scenario", "summary": "Scenario", "source_refs": []},
                {"id": "REQ-B01-001", "kind": "requirement", "summary": "Requirement", "source_refs": []},
            ]
            payload["trace"] = [{"from": "REQ-B01-001", "to": ["SCN-B01-001"]}]
            path.write_text(json.dumps(payload), encoding="utf-8")
            self.transition(root, "B01", "analyzed")
            replace_todo(root / "reviews" / "B01.md", "# Review\n\nPASS")
            self.transition(root, "B01", "reviewed")
            replace_todo(root / "draft.md", "# Draft\n\nIntegrated")
            self.transition(root, "B01", "integrated")
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            errors = case_pipeline.validate_case(
                loaded_root,
                manifest,
                ledger,
                final=True,
                ignore_consistency_gate=True,
            )
            self.assertTrue(any("no acceptance criterion" in item for item in errors))

    def test_context_bundle_is_role_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self.init(Path(temp))
            self.add(root, "B01")
            _, manifest, ledger = case_pipeline.load_case(root)
            bundle = case_pipeline.context_bundle(
                manifest,
                ledger,
                block_id="B01",
                role="spec-reviewer",
            )
            self.assertIn("blocks/B01.md", bundle["case_inputs"])
            self.assertIn(vigers_context.METHOD_CONTEXT_MARKDOWN, bundle["case_inputs"])
            self.assertIn("reviews/B01.md", bundle["exclude"])
            editor_bundle = case_pipeline.context_bundle(
                manifest,
                ledger,
                block_id="B01",
                role="spec-editor",
            )
            self.assertNotIn(
                vigers_context.METHOD_CONTEXT_MARKDOWN,
                editor_bundle["case_inputs"],
            )

    def test_compact_mode_marks_block_only_gates_not_required(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self.init(Path(temp), mode="compact")
            _, manifest, _ = case_pipeline.load_case(root)
            self.assertEqual(manifest["gates"]["semantic_integration"]["status"], "not_required")
            self.assertEqual(manifest["gates"]["integration_review"]["status"], "not_required")

    def test_compact_context_routes_method_only_to_semantic_roles(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self.init(Path(temp), mode="compact")
            _, manifest, ledger = case_pipeline.load_case(root)
            analyst = case_pipeline.context_bundle(
                manifest, ledger, block_id=None, role="system-analyst"
            )
            editor = case_pipeline.context_bundle(
                manifest, ledger, block_id=None, role="spec-editor"
            )
            reviewer = case_pipeline.context_bundle(
                manifest, ledger, block_id=None, role="spec-reviewer"
            )
            self.assertIn(vigers_context.METHOD_CONTEXT_MARKDOWN, analyst["case_inputs"])
            self.assertIn(vigers_context.METHOD_CONTEXT_MARKDOWN, reviewer["case_inputs"])
            self.assertNotIn(vigers_context.METHOD_CONTEXT_MARKDOWN, editor["case_inputs"])
            self.assertEqual(analyst["target"], "whole-case")

    def test_passed_gate_requires_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self.init(Path(temp), mode="compact")
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            with self.assertRaises(case_pipeline.CaseError):
                case_pipeline.set_gate(
                    loaded_root,
                    manifest,
                    ledger,
                    name="evidence",
                    status="pass",
                    evidence=None,
                    note=None,
                )

    def test_gate_detects_changed_subject(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self.init(Path(temp), mode="compact")
            replace_todo(root / "draft.md", "# Draft\n\nVersion one")
            replace_todo(root / "reviews" / "global.md", "# Global review\n\nPASS")
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            case_pipeline.set_gate(
                loaded_root,
                manifest,
                ledger,
                name="global_review",
                status="pass",
                evidence="reviews/global.md",
                note=None,
            )
            replace_todo(root / "draft.md", "# Draft\n\nVersion two")
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            errors = case_pipeline.validate_case(loaded_root, manifest, ledger, final=True)
            self.assertTrue(any("global_review subject changed" in item for item in errors))

    def test_complete_block_case_passes_final_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self.init(Path(temp))
            self.add(root, "B01")
            self.transition(root, "B01", "ready")
            self.transition(root, "B01", "in_progress")
            replace_todo(root / "blocks" / "B01.md", "# B01\n\nComplete analysis")
            index_path = root / "blocks" / "B01.index.json"
            payload = json.loads(index_path.read_text(encoding="utf-8"))
            payload["definitions"] = [
                {"id": "SCN-B01-001", "kind": "scenario", "summary": "Scenario", "source_refs": []},
                {"id": "REQ-B01-001", "kind": "requirement", "summary": "Requirement", "source_refs": []},
                {"id": "AC-B01-001", "kind": "acceptance", "summary": "Acceptance", "source_refs": []},
            ]
            payload["trace"] = [
                {"from": "REQ-B01-001", "to": ["SCN-B01-001"]},
                {"from": "AC-B01-001", "to": ["REQ-B01-001"]},
            ]
            index_path.write_text(json.dumps(payload), encoding="utf-8")
            self.transition(root, "B01", "analyzed")
            replace_todo(root / "reviews" / "B01.md", "# Review B01\n\nPASS")
            self.transition(root, "B01", "reviewed")
            replace_todo(root / "draft.md", "# Draft\n\nComplete")
            self.transition(root, "B01", "integrated")
            replace_todo(root / "evidence.md", "# Evidence\n\nSRC-1")
            replace_todo(root / "reviews" / "integration.md", "# Integration\n\nPASS")
            replace_todo(root / "reviews" / "global.md", "# Global\n\nPASS")
            replace_todo(root / "reviews" / "project.md", "# Project\n\nPASS")

            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            self.assertEqual(case_pipeline.run_check(loaded_root, manifest, ledger, final_trace=True), [])
            gate_updates = [
                ("evidence", "pass", "evidence.md", None),
                ("architecture_design", "not_required", None, "No architecture impact"),
                ("author_passes", "pass", "draft.md", None),
                ("semantic_integration", "pass", "draft.md", None),
                ("integration_review", "pass", "reviews/integration.md", None),
                ("global_review", "pass", "reviews/global.md", None),
                ("project_conformance", "pass", "reviews/project.md", None),
                ("architecture_conformance", "not_required", None, "No architecture impact"),
            ]
            for name, status, evidence, note in gate_updates:
                loaded_root, manifest, ledger = case_pipeline.load_case(root)
                case_pipeline.set_gate(
                    loaded_root,
                    manifest,
                    ledger,
                    name=name,
                    status=status,
                    evidence=evidence,
                    note=note,
                )
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            self.assertEqual(case_pipeline.validate_case(loaded_root, manifest, ledger, final=True), [])


if __name__ == "__main__":
    unittest.main()
