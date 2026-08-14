#!/usr/bin/env python3
"""Regression tests for resumable Vigers case state."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

import automation_timing
import case_pipeline
import mode_decision
import planning_case
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
    def project_document_contract(self) -> dict[str, object]:
        return {
            "schema": 1,
            "profile_id": "generic",
            "profile_sha256": "a" * 64,
            "checks": ["draft", "working_projection"],
            "required_headings": [
                "Оглавление",
                "История изменений",
                "Описание",
                "User Story",
                "Полезные ссылки",
            ],
            "toc": {
                "policy": "obsidian-h2-exact",
                "heading": "Оглавление",
                "separators": "required",
            },
        }

    def test_role_context_is_invariant_to_human_timing_estimates(self) -> None:
        common: dict[str, object] = {
            "planning_case_id": "demo-plan",
            "planning_revision": 2,
            "profile_id": "generic",
            "project_root": None,
            "passport": None,
            "required_anchor_systems": [],
            "external_bindings": [],
            "preliminary_requirements": None,
            "approval": {"revision": 2, "kind": "user"},
        }
        short_estimate = {
            **common,
            "automation_plan": {"stages": [{"estimate": {"likely_seconds": 60}}]},
            "fingerprint": "fingerprint-derived-from-short-estimate",
        }
        long_estimate = {
            **common,
            "automation_plan": {"stages": [{"estimate": {"likely_seconds": 36000}}]},
            "fingerprint": "fingerprint-derived-from-long-estimate",
        }

        self.assertEqual(
            case_pipeline.planning_role_context(short_estimate),
            case_pipeline.planning_role_context(long_estimate),
        )
        self.assertNotIn(
            "source_handoff_fingerprint",
            case_pipeline.planning_role_context(short_estimate),
        )

        manifest_common: dict[str, object] = {
            "case_id": "demo",
            "mode": "compact",
            "intent": "create",
            "profile_id": "generic",
            "route_id": "core",
            "project_root": None,
            "mode_decision": None,
            "method_context": None,
            "kernel": {"path": "kernel.md", "revision": 1, "sha256": "kernel"},
            "artifacts": {
                "automation_timing": "automation-timing.json",
                "planning_role_context": "planning-role-context.json",
                "evidence": "evidence.md",
            },
            "gates": {},
        }
        manifest_short = {
            **manifest_common,
            "planning_handoff": {
                "fingerprint": "derived-from-short-estimate",
                "planning_case_id": "demo-plan",
                "planning_revision": 2,
                "project_root": None,
                "role_context_path": "planning-role-context.json",
                "role_context_fingerprint": "timing-invariant-role-context",
            },
        }
        manifest_long = {
            **manifest_common,
            "planning_handoff": {
                "fingerprint": "derived-from-long-estimate",
                "planning_case_id": "demo-plan",
                "planning_revision": 2,
                "project_root": None,
                "role_context_path": "planning-role-context.json",
                "role_context_fingerprint": "timing-invariant-role-context",
            },
        }
        self.assertEqual(
            case_pipeline.role_manifest(manifest_short),
            case_pipeline.role_manifest(manifest_long),
        )
        projected = case_pipeline.role_manifest(manifest_short)
        self.assertNotIn("automation_timing", projected["artifacts"])
        self.assertNotIn("fingerprint", projected["planning_context"])

    def write_mode_decision(
        self,
        root: Path,
        *,
        selected_mode: str = "block",
        profile_id: str = "generic",
        assurance: str = "high",
        tracking: str = "fine",
        projection_sync: str = "per-block",
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
            requested_assurance=assurance,
            requested_tracking=tracking,
            requested_projection_sync=projection_sync,
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

    def write_planning_handoff(
        self,
        root: Path,
        *,
        profile_id: str = "generic",
        project_root: str | None = None,
        working_projection: bool = False,
        revision: int = 1,
        projection_object_id: str = "specification.md",
        projection_url: str | None = None,
        projection_evidence_kind: str = "local_file",
        solution_boundary_probe: bool = False,
    ) -> dict[str, object]:
        markdown = "# Planning handoff\n\nVerified research and approved plan.\n"
        projection_binding = {
            "target_id": "EXT-001",
            "system": "visible-draft",
            "object_id": projection_object_id,
            "url": projection_url,
            "read_back_at": "2026-08-08T10:00:00+00:00",
        }
        payload: dict[str, object] = {
            "schema": planning_case.HANDOFF_SCHEMA_VERSION,
            "planning_case_id": "demo-plan",
            "planning_revision": revision,
            "profile_id": profile_id,
            "project_root": project_root,
            "required_anchor_systems": [],
            "passport": None,
            "external_bindings": [projection_binding] if working_projection else [],
            "working_projection": {
                "policy": "required" if working_projection else "optional",
                "targets": (
                    [
                        {
                            **projection_binding,
                            "action": "create",
                            "purpose": "Growing specification",
                            "evidence_kind": projection_evidence_kind,
                        }
                    ]
                    if working_projection
                    else []
                ),
            },
            "approval": {"revision": revision},
            "artifact_hashes": {},
            "content_sha256": hashlib.sha256(markdown.encode("utf-8")).hexdigest(),
        }
        if solution_boundary_probe:
            payload["solution_boundary_probe"] = {
                "status": "preliminary",
                "validation_gate": "full_analysis",
                "candidate_horizon": "bounded-systemic",
                "observed_case": "A current variant is requested",
                "candidate_root_capability": "Handle the capability consistently",
                "analogy_search": {
                    "searched_surfaces": ["backlog"],
                    "source_refs": ["SRC-001"],
                    "confirmed_variants": [
                        {"name": "Current variant", "source_refs": ["SRC-001"]}
                    ],
                    "hypothesized_variants": [],
                    "roadmap_refs": [],
                    "irreversibility_signals": [],
                    "negative_result_recorded": False,
                },
                "urgent_fix": {"confirmed": False, "source_refs": []},
            }
        payload["fingerprint"] = planning_case.canonical_fingerprint(payload)
        root.mkdir(parents=True, exist_ok=True)
        (root / planning_case.HANDOFF_JSON).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (root / planning_case.HANDOFF_MARKDOWN).write_text(markdown, encoding="utf-8")
        return payload

    def write_solution_boundary(self, root: Path, horizon: str) -> None:
        hotfix = (
            {
                "reason": "Urgent risk is confirmed",
                "source_refs": ["SRC-001"],
                "reversibility": "Remove the narrow rule",
                "return_trigger": "A second confirmed variant appears",
            }
            if horizon == "tactical"
            else None
        )
        confirmed = [
            {"name": "Current variant", "evidence_refs": ["SRC-001"]}
        ]
        roadmap_refs: list[str] = []
        if horizon == "generalized-capability":
            confirmed.append(
                {"name": "Second variant", "evidence_refs": ["SRC-002"]}
            )
        payload = {
            "schema": 1,
            "solution_horizon": horizon,
            "observed_case": "A current variant is requested",
            "root_capability": "Handle the capability consistently",
            "invariants": ["Existing behavior remains compatible"],
            "confirmed_variants": confirmed,
            "hypothesized_variants": [],
            "current_scope": ["Support confirmed behavior"],
            "extension_seams": ["Keep the variant boundary neutral"],
            "extension_seam_absence_reason": None,
            "deferred_variants": [],
            "expansion_triggers": ["A new variant is confirmed"],
            "horizon_evidence": {
                "analogy_search_refs": ["SRC-001"],
                "roadmap_refs": roadmap_refs,
                "irreversibility_signals": [],
            },
            "hotfix_exception": hotfix,
            "planning_probe_disposition": {
                "status": "confirmed",
                "rationale": "Full analysis confirmed the boundary",
            },
        }
        text = (
            "# Decision log\n\n"
            f"{case_pipeline.SOLUTION_BOUNDARY_START}\n"
            "```json\n"
            f"{json.dumps(payload, ensure_ascii=False, indent=2)}\n"
            "```\n"
            f"{case_pipeline.SOLUTION_BOUNDARY_END}\n"
        )
        (root / "decisions.md").write_text(text, encoding="utf-8")

    def write_external_receipt(
        self,
        root: Path,
        *,
        target_id: str = "EXT-001",
        system: str = "visible-draft",
        object_id: str = "specification.md",
        content_sha256: str,
        read_back_at: str,
        relative: str = "readbacks/ext-001.json",
    ) -> str:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema": case_pipeline.EXTERNAL_READBACK_RECEIPT_SCHEMA,
            "kind": "external_readback",
            "adapter": "test-project-adapter",
            "target_id": target_id,
            "system": system,
            "object_id": object_id,
            "read_back_at": read_back_at,
            "content_sha256": content_sha256,
            "response_fingerprint": "f" * 64,
        }
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return relative

    def write_timed_planning_handoff(
        self,
        root: Path,
        *,
        revision: int,
        project_root: str | None = None,
    ) -> dict[str, object]:
        markdown = f"# Planning handoff\n\nApproved revision {revision}.\n"
        plan = {
            "schema": 3,
            "revision": revision,
            "automation_estimation": {
                "policy": "required",
                "metric": "wall_clock",
                "unit": "seconds",
                "execution_use": "human_information_only",
            },
            "stages": [
                {
                    "id": "P01",
                    "title": "Verify source",
                    "depends_on": [],
                    "automation_estimate": {
                        "optimistic_seconds": 30,
                        "likely_seconds": 60,
                        "pessimistic_seconds": 120,
                        "basis": "heuristic",
                        "confidence": "low",
                        "sample_size": 0,
                    },
                    "external_target_id": None,
                    "checklist": [
                        {
                            "id": "P01-C01",
                            "text": "Verify the source",
                            "done_when": "Evidence is recorded",
                        }
                    ],
                }
            ],
        }
        automation_plan = automation_timing.build_automation_plan(plan)
        payload: dict[str, object] = {
            "schema": planning_case.HANDOFF_SCHEMA_VERSION,
            "planning_case_id": "demo-plan",
            "planning_revision": revision,
            "profile_id": "generic",
            "project_root": project_root,
            "required_anchor_systems": [],
            "passport": {"id": "PASS-1", "path": None},
            "automation_plan": automation_plan,
            "preliminary_requirements": None,
            "external_bindings": [],
            "approval": {"revision": revision, "kind": "coordinator_local_replan"},
            "artifact_hashes": {},
            "content_sha256": hashlib.sha256(markdown.encode("utf-8")).hexdigest(),
        }
        payload["fingerprint"] = planning_case.canonical_fingerprint(payload)
        root.mkdir(parents=True, exist_ok=True)
        (root / planning_case.HANDOFF_JSON).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (root / planning_case.HANDOFF_MARKDOWN).write_text(markdown, encoding="utf-8")
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
            allow_unplanned=True,
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

    def test_standard_assurance_is_independent_from_block_scale(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "case"
            self.write_method_context(root)
            self.write_mode_decision(
                root,
                selected_mode="block",
                assurance="standard",
                tracking="milestones",
                projection_sync="milestones",
            )
            case_pipeline.init_case(
                root,
                case_id="standard-block",
                mode="block",
                intent="create",
                profile_id="generic",
                route_id="core",
                project_root=None,
                allow_unplanned=True,
            )
            _, manifest, _ = case_pipeline.load_case(root)
            self.assertEqual(manifest["assurance_level"], "standard")
            self.assertEqual(manifest["tracking"], "milestones")
            self.assertEqual(manifest["projection_sync"], "milestones")
            self.assertEqual(manifest["gates"]["integration_review"]["status"], "not_required")
            self.assertEqual(manifest["gates"]["global_review"]["status"], "pending")
            self.assertTrue((root / case_pipeline.AGENT_LEDGER_JSON).is_file())

    def test_targeted_kernel_refresh_rebases_unaffected_completed_block(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self.init(Path(temp))
            self.add(root, "B01")
            self.add(root, "B02")
            self.analyze_and_review(root, "B01", "SCN-B01-001")
            self.analyze_and_review(root, "B02", "SCN-B02-001")
            (root / "kernel.md").write_text("# Kernel\n\nChanged local rule\n", encoding="utf-8")
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            stale = case_pipeline.refresh_kernel(
                loaded_root,
                manifest,
                ledger,
                ["B01"],
                change_scope="semantic-local",
                reason="Only B01 consumes the changed rule",
            )
            self.assertEqual(stale, ["B01"])
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            blocks = case_pipeline.blocks_by_id(ledger)
            self.assertEqual(blocks["B01"]["status"], "stale")
            self.assertEqual(blocks["B02"]["status"], "reviewed")
            self.assertEqual(blocks["B02"]["kernel_sha256"], manifest["kernel"]["sha256"])
            self.assertFalse(
                any("B02: stale kernel snapshot" in item for item in case_pipeline.validate_case(
                    loaded_root, manifest, ledger, final=False
                ))
            )

    def test_targeted_remediation_preserves_prior_review_and_binds_delta_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self.init(Path(temp))
            self.add(root, "B01")
            self.analyze_and_review(root, "B01", "SCN-B01-001")
            _, _, ledger = case_pipeline.load_case(root)
            block = case_pipeline.blocks_by_id(ledger)["B01"]
            self.assertEqual(len(block["review_history"]), 1)
            prior_review = block["review_history"][0]["evidence"]
            prior_review_bytes = (root / prior_review).read_bytes()

            replace_todo(
                root / "reviews" / "global.md",
                "# Global review\n\nF-B01-001 major: rule is ambiguous",
            )
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            remediation = case_pipeline.begin_block_remediation(
                loaded_root,
                manifest,
                ledger,
                block_id="B01",
                findings=[{"id": "F-B01-001", "severity": "major"}],
                semantic_ids=["SCN-B01-001"],
                evidence="reviews/global.md",
                reason="Resolve the accepted ambiguity only",
            )
            self.assertEqual(remediation["scope"], "targeted")

            replace_todo(root / "blocks" / "B01.md", "# B01\n\nCorrected rule")
            index_path = root / "blocks" / "B01.index.json"
            index = json.loads(index_path.read_text(encoding="utf-8"))
            index["definitions"][0]["summary"] = "Corrected requirement"
            index_path.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
            self.transition(root, "B01", "analyzed")

            _, manifest, ledger = case_pipeline.load_case(root)
            bundle = case_pipeline.context_bundle(
                manifest,
                ledger,
                block_id="B01",
                role="spec-reviewer",
                role_mode="block",
            )
            self.assertEqual(bundle["review_scope"], "targeted-remediation")
            self.assertEqual(bundle["remediation"]["finding_ids"], ["F-B01-001"])
            self.assertIn(remediation["baseline_artifact"], bundle["case_inputs"])
            self.assertIn(remediation["finding_evidence"], bundle["case_inputs"])
            self.assertIn(prior_review, bundle["case_inputs"])

            replace_todo(
                root / "reviews" / "B01.md",
                "# Targeted review\n\n"
                "review_scope: targeted-remediation\n"
                "verified_findings: [F-B01-001]\n"
                f"coverage_reused: {prior_review}\n\nPASS",
            )
            self.transition(root, "B01", "reviewed")
            _, _, ledger = case_pipeline.load_case(root)
            block = case_pipeline.blocks_by_id(ledger)["B01"]
            self.assertEqual(block["remediations"][0]["status"], "verified")
            self.assertEqual(len(block["review_history"]), 2)
            self.assertEqual((root / prior_review).read_bytes(), prior_review_bytes)

    def test_targeted_remediation_rejects_undeclared_semantic_rewrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self.init(Path(temp))
            self.add(root, "B01")
            self.transition(root, "B01", "ready")
            self.transition(root, "B01", "in_progress")
            replace_todo(root / "blocks" / "B01.md", "# B01\n\nTwo requirements")
            add_definition(root, "B01", "REQ-B01-001", "requirement")
            add_definition(root, "B01", "REQ-B01-002", "requirement")
            self.transition(root, "B01", "analyzed")
            replace_todo(root / "reviews" / "B01.md", "# Review B01\n\nPASS")
            self.transition(root, "B01", "reviewed")
            _, _, ledger = case_pipeline.load_case(root)
            prior_review = case_pipeline.blocks_by_id(ledger)["B01"]["review_history"][0]["evidence"]
            replace_todo(root / "reviews" / "global.md", "# Finding\n\nF-B01-001 major")
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            case_pipeline.begin_block_remediation(
                loaded_root,
                manifest,
                ledger,
                block_id="B01",
                findings=[{"id": "F-B01-001", "severity": "major"}],
                semantic_ids=["REQ-B01-001"],
                evidence="reviews/global.md",
                reason="Correct only REQ-B01-001",
            )
            index_path = root / "blocks" / "B01.index.json"
            index = json.loads(index_path.read_text(encoding="utf-8"))
            index["definitions"][1]["summary"] = "Unrelated rewrite"
            index_path.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
            replace_todo(root / "blocks" / "B01.md", "# B01\n\nUnexpected broad change")
            self.transition(root, "B01", "analyzed")
            replace_todo(
                root / "reviews" / "B01.md",
                "# Targeted review\n\n"
                "review_scope: targeted-remediation\n"
                "verified_findings: [F-B01-001]\n"
                f"coverage_reused: {prior_review}\n\nPASS",
            )
            with self.assertRaisesRegex(
                case_pipeline.CaseError,
                "undeclared semantic ids: REQ-B01-002",
            ):
                self.transition(root, "B01", "reviewed")

    def test_reviewed_block_cannot_restart_without_remediation_record(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self.init(Path(temp))
            self.add(root, "B01")
            self.analyze_and_review(root, "B01", "SCN-B01-001")
            with self.assertRaisesRegex(
                case_pipeline.CaseError,
                "use begin-remediation",
            ):
                self.transition(root, "B01", "in_progress")

    def test_full_block_remediation_does_not_reuse_previous_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self.init(Path(temp))
            self.add(root, "B01")
            self.analyze_and_review(root, "B01", "SCN-B01-001")
            replace_todo(root / "reviews" / "global.md", "# Finding\n\nF-B01-ALL major")
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            remediation = case_pipeline.begin_block_remediation(
                loaded_root,
                manifest,
                ledger,
                block_id="B01",
                findings=[{"id": "F-B01-ALL", "severity": "major"}],
                semantic_ids=[],
                evidence="reviews/global.md",
                reason="The block contract must be rewritten",
                full_block=True,
            )
            self.assertIsNone(remediation["coverage_evidence"])
            replace_todo(root / "blocks" / "B01.md", "# B01\n\nRewritten block contract")
            index_path = root / "blocks" / "B01.index.json"
            index = json.loads(index_path.read_text(encoding="utf-8"))
            index["definitions"][0]["summary"] = "Rewritten scenario"
            index_path.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
            self.transition(root, "B01", "analyzed")
            replace_todo(
                root / "reviews" / "B01.md",
                "# Full block review\n\n"
                "review_scope: full-block\n"
                "verified_findings: [F-B01-ALL]\n"
                "coverage_reused: none\n\nPASS",
            )
            self.transition(root, "B01", "reviewed")
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            with self.assertRaisesRegex(
                case_pipeline.CaseError,
                "Full-block remediation requires fresh",
            ):
                case_pipeline.record_semantic_remediation(
                    loaded_root,
                    manifest,
                    ledger,
                    block_id="B01",
                    remediation_id=remediation["id"],
                    reason="Attempted reuse",
                )

    def test_record_remediation_reuses_prior_global_coverage_after_fresh_checks(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self.init(Path(temp))
            self.add(root, "B01")
            self.analyze_and_review(root, "B01", "SCN-B01-001")
            replace_todo(root / "draft.md", "# Draft\n\nInitial requirement")
            self.transition(root, "B01", "integrated")
            replace_todo(root / "reviews" / "global.md", "# Global review\n\nPASS")
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            case_pipeline.set_gate(
                loaded_root, manifest, ledger,
                name="semantic_integration", status="pass", evidence="draft.md", note=None,
            )
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            case_pipeline.set_gate(
                loaded_root, manifest, ledger,
                name="author_passes", status="pass", evidence="draft.md", note=None,
            )
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            self.assertEqual(case_pipeline.run_check(loaded_root, manifest, ledger, final_trace=False), [])
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            case_pipeline.set_gate(
                loaded_root, manifest, ledger,
                name="global_review", status="pass", evidence="reviews/global.md", note=None,
            )
            _, manifest, ledger = case_pipeline.load_case(root)
            previous_global_subject = manifest["gates"]["global_review"]["subject_sha256"]
            previous_block_review = case_pipeline.blocks_by_id(ledger)["B01"]["review_history"][0]["evidence"]

            replace_todo(root / "reviews" / "global.md", "# Finding\n\nF-B01-001 major")
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            remediation = case_pipeline.begin_block_remediation(
                loaded_root,
                manifest,
                ledger,
                block_id="B01",
                findings=[{"id": "F-B01-001", "severity": "major"}],
                semantic_ids=["SCN-B01-001"],
                evidence="reviews/global.md",
                reason="Correct the one accepted requirement finding",
            )
            replace_todo(root / "blocks" / "B01.md", "# B01\n\nCorrected requirement")
            index_path = root / "blocks" / "B01.index.json"
            index = json.loads(index_path.read_text(encoding="utf-8"))
            index["definitions"][0]["summary"] = "Corrected requirement"
            index_path.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
            self.transition(root, "B01", "analyzed")
            replace_todo(
                root / "reviews" / "B01.md",
                "# Targeted review\n\n"
                "review_scope: targeted-remediation\n"
                "verified_findings: [F-B01-001]\n"
                f"coverage_reused: {previous_block_review}\n\nPASS",
            )
            self.transition(root, "B01", "reviewed")
            replace_todo(root / "draft.md", "# Draft\n\nCorrected requirement")
            self.transition(root, "B01", "integrated")
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            case_pipeline.set_gate(
                loaded_root, manifest, ledger,
                name="semantic_integration", status="pass", evidence="draft.md", note=None,
            )
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            case_pipeline.set_gate(
                loaded_root, manifest, ledger,
                name="author_passes", status="pass", evidence="draft.md", note=None,
            )
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            self.assertEqual(case_pipeline.run_check(loaded_root, manifest, ledger, final_trace=False), [])
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            rebased = case_pipeline.record_semantic_remediation(
                loaded_root,
                manifest,
                ledger,
                block_id="B01",
                remediation_id=remediation["id"],
                reason="Fresh checks prove the delta stayed inside REQ-B01-001",
            )
            self.assertIn("global_review", rebased)
            _, manifest, ledger = case_pipeline.load_case(root)
            self.assertNotEqual(
                manifest["gates"]["global_review"]["subject_sha256"],
                previous_global_subject,
            )
            self.assertTrue(
                manifest["gates"]["global_review"]["evidence"].endswith("-reuse.json")
            )
            self.assertEqual(
                case_pipeline.validate_case(root, manifest, ledger, final=False),
                [],
            )

    def test_lite_case_escalates_when_change_becomes_semantic(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "case"
            self.write_method_context(root)
            self.write_mode_decision(
                root,
                selected_mode="compact",
                assurance="lite",
                tracking="milestones",
                projection_sync="milestones",
            )
            case_pipeline.init_case(
                root,
                case_id="lite-semantic-escalation",
                mode="compact",
                intent="update",
                profile_id="generic",
                route_id="core",
                project_root=None,
                allow_unplanned=True,
            )
            self.assertEqual(
                case_pipeline.load_case(root)[1]["gates"]["global_review"]["status"],
                "not_required",
            )
            (root / "kernel.md").write_text(
                "# Kernel\n\nMeaning changed\n",
                encoding="utf-8",
            )
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            case_pipeline.refresh_kernel(
                loaded_root,
                manifest,
                ledger,
                [],
                change_scope="semantic-local",
                reason="Editorial assumption was wrong",
            )
            _, manifest, _ = case_pipeline.load_case(root)
            self.assertEqual(manifest["assurance_level"], "standard")
            self.assertEqual(manifest["gates"]["global_review"]["status"], "pending")
            self.assertEqual(
                manifest["gates"]["project_conformance"]["status"],
                "pending",
            )

    def test_manifest_cannot_silently_weaken_bound_execution_policy(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self.init(Path(temp))
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            manifest["assurance_level"] = "lite"
            manifest["tracking"] = "off"
            manifest["projection_sync"] = "milestones"
            case_pipeline.save_case(loaded_root, manifest, ledger)
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            errors = case_pipeline.validate_case(loaded_root, manifest, ledger, final=False)
            self.assertTrue(any("assurance conflicts" in item for item in errors), errors)
            self.assertTrue(any("tracking conflicts" in item for item in errors), errors)
            self.assertTrue(any("projection sync conflicts" in item for item in errors), errors)

    def test_standard_final_reviewer_gets_whole_block_subject_without_old_reviews(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "case"
            self.write_method_context(root)
            self.write_mode_decision(
                root,
                selected_mode="block",
                assurance="standard",
                tracking="milestones",
                projection_sync="milestones",
            )
            case_pipeline.init_case(
                root,
                case_id="standard-final-context",
                mode="block",
                intent="create",
                profile_id="generic",
                route_id="core",
                project_root=None,
                allow_unplanned=True,
            )
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            case_pipeline.add_block(
                loaded_root, manifest, ledger,
                block_id="B01", title="Block", kind="scenarios", depends_on=[]
            )
            _, manifest, ledger = case_pipeline.load_case(root)
            bundle = case_pipeline.context_bundle(
                manifest,
                ledger,
                block_id=None,
                role="spec-reviewer",
                role_mode="final",
                contract_surfaces=["reader-projection", "project-rules"],
            )
            self.assertEqual(bundle["review_strategy"], "combined-final")
            self.assertEqual(
                bundle["covered_gates"],
                ["integration_review", "global_review", "project_conformance"],
            )
            self.assertIn("blocks/B01.index.json", bundle["case_inputs"])
            self.assertNotIn("reviews/global.md", bundle["case_inputs"])
            self.assertIn("references/reader-projection-contract.md", bundle["contract_inputs"])
            self.assertNotIn("references/diagram-contract.md", bundle["contract_inputs"])

    def test_architect_context_is_materialized_from_declared_surfaces(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self.init(Path(temp), mode="compact")
            _, manifest, ledger = case_pipeline.load_case(root)
            bundle = case_pipeline.context_bundle(
                manifest,
                ledger,
                block_id=None,
                role="solution-architect",
                role_mode="conformance",
                contract_surfaces=[],
            )
            self.assertEqual(bundle["role_mode"], "conformance")
            self.assertIn("draft.md", bundle["case_inputs"])
            self.assertIn(
                "references/solution-boundary-contract.md",
                bundle["contract_inputs"],
            )
            self.assertIn("references/diagram-contract.md", bundle["contract_inputs"])
            self.assertNotIn("method-context.md", bundle["case_inputs"])

    def test_agent_ledger_records_cost_and_finding_yield(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self.init(Path(temp))
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            case_pipeline.record_agent_run(
                loaded_root,
                manifest,
                ledger,
                role="spec-reviewer",
                role_mode="global",
                model="test-model",
                subject_sha256="a" * 64,
                input_bytes=1200,
                input_tokens=300,
                output_tokens=40,
                duration_seconds=2.5,
                retries=0,
                reported_blocker=0,
                reported_major=1,
                reported_minor=2,
                cache_status="miss",
            )
            payload = json.loads((root / case_pipeline.AGENT_LEDGER_JSON).read_text())
            self.assertEqual(payload["runs"][0]["findings"]["major"], 1)
            self.assertEqual(payload["runs"][0]["input_tokens"], 300)

    def test_milestone_tracking_preserves_user_owned_gates(self) -> None:
        plan = {
            "policy": "required",
            "metric": "wall_clock",
            "unit": "seconds",
            "execution_use": "human_information_only",
            "stages": [
                {
                    "id": "P01",
                    "title": "Approve result",
                    "depends_on": [],
                    "estimate": {
                        "optimistic_seconds": 1,
                        "likely_seconds": 2,
                        "pessimistic_seconds": 3,
                        "basis": "heuristic",
                        "confidence": "low",
                        "sample_size": 0,
                    },
                    "external_target_id": None,
                    "checklist": [
                        {
                            "id": "P01-C01",
                            "text": "Prepare result",
                            "required": True,
                            "done_when": "Draft ready",
                            "completion_owner": "agent",
                        },
                        {
                            "id": "P01-C02",
                            "text": "Approve result",
                            "required": True,
                            "done_when": "User confirmed",
                            "completion_owner": "user",
                        },
                    ],
                }
            ],
        }
        plan["fingerprint"] = automation_timing.canonical_fingerprint(plan)
        projected = case_pipeline.runtime_automation_plan(plan, "milestones")
        self.assertIsNotNone(projected)
        assert projected is not None
        checklist = projected["stages"][0]["checklist"]
        self.assertEqual(
            [(item["id"], item["completion_owner"]) for item in checklist],
            [("P01-MILESTONE", "agent"), ("P01-C02", "user")],
        )
        self.assertEqual(
            automation_timing.validate_automation_plan(projected),
            [],
        )
        off = case_pipeline.runtime_automation_plan(plan, "off")
        self.assertIsNotNone(off)
        assert off is not None
        self.assertEqual(
            [(item["id"], item["completion_owner"]) for item in off["stages"][0]["checklist"]],
            [("P01-C02", "user")],
        )
        self.assertEqual(automation_timing.validate_automation_plan(off), [])

    def test_standard_review_report_is_combined_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "case"
            self.write_method_context(root)
            self.write_mode_decision(
                root,
                selected_mode="compact",
                assurance="standard",
                tracking="milestones",
                projection_sync="milestones",
            )
            case_pipeline.init_case(
                root,
                case_id="standard-combined-review",
                mode="compact",
                intent="create",
                profile_id="generic",
                route_id="core",
                project_root=None,
                allow_unplanned=True,
            )
            replace_todo(root / "draft.md", "# Draft\n\nCurrent subject")
            report = root / "reviews" / "global.md"
            replace_todo(
                report,
                "# Final review\n\ncovered_gates: [global_review, project_conformance]\n\nPASS",
            )
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            with self.assertRaisesRegex(case_pipeline.CaseError, "exact covered_gates"):
                case_pipeline.set_gate(
                    loaded_root,
                    manifest,
                    ledger,
                    name="global_review",
                    status="pass",
                    evidence="reviews/global.md",
                    note=None,
                )
            replace_todo(
                report,
                "# Final review\n\ncovered_gates: [integration_review, global_review, project_conformance]\n\nPASS",
            )
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
            manifest_before = (root / "manifest.json").read_bytes()
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
            self.assertEqual((root / "manifest.json").read_bytes(), manifest_before)
            self.assertEqual(
                len(list((root / "reviews" / "history").glob("global_review-r*.md"))),
                1,
            )

    def test_nonsemantic_change_rebases_only_after_current_machine_check(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self.init(Path(temp), mode="compact")
            replace_todo(root / "draft.md", "# Draft\n\nVersion one")
            replace_todo(root / "reviews" / "global.md", "# Global review\n\nPASS")
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            self.assertEqual(
                case_pipeline.run_check(loaded_root, manifest, ledger, final_trace=False),
                [],
            )
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
            _, manifest, _ = case_pipeline.load_case(root)
            old_subject = manifest["gates"]["global_review"]["subject_sha256"]

            replace_todo(root / "draft.md", "# Draft\n\nVersion   one")
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            with self.assertRaisesRegex(case_pipeline.CaseError, "Consistency report is older"):
                case_pipeline.rebase_nonsemantic_change(
                    loaded_root,
                    manifest,
                    ledger,
                    change_scope="editorial",
                    reason="Spacing only",
                )
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            self.assertEqual(
                case_pipeline.run_check(loaded_root, manifest, ledger, final_trace=False),
                [],
            )
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            rebased = case_pipeline.rebase_nonsemantic_change(
                loaded_root,
                manifest,
                ledger,
                change_scope="editorial",
                reason="Spacing only",
            )
            self.assertIn("global_review", rebased)
            _, manifest, _ = case_pipeline.load_case(root)
            self.assertNotEqual(
                manifest["gates"]["global_review"]["subject_sha256"],
                old_subject,
            )

    def test_editorial_change_preserves_operators(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self.init(Path(temp), mode="compact")
            replace_todo(root / "draft.md", "# Draft\n\nRule: x < 5")
            replace_todo(root / "reviews" / "global.md", "# Global review\n\nPASS")
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            self.assertEqual(case_pipeline.run_check(loaded_root, manifest, ledger, final_trace=False), [])
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
            replace_todo(root / "draft.md", "# Draft\n\nRule: x > 5")
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            self.assertEqual(case_pipeline.run_check(loaded_root, manifest, ledger, final_trace=False), [])
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            with self.assertRaisesRegex(case_pipeline.CaseError, "semantic content"):
                case_pipeline.rebase_nonsemantic_change(
                    loaded_root,
                    manifest,
                    ledger,
                    change_scope="editorial",
                    reason="Claimed punctuation cleanup",
                )

    def test_editorial_change_preserves_case_sensitive_values(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self.init(Path(temp), mode="compact")
            replace_todo(root / "draft.md", "# Draft\n\nStatus: OPEN")
            replace_todo(root / "reviews" / "global.md", "# Global review\n\nPASS")
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            self.assertEqual(case_pipeline.run_check(loaded_root, manifest, ledger, final_trace=False), [])
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
            replace_todo(root / "draft.md", "# Draft\n\nStatus: open")
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            self.assertEqual(case_pipeline.run_check(loaded_root, manifest, ledger, final_trace=False), [])
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            with self.assertRaisesRegex(case_pipeline.CaseError, "semantic content"):
                case_pipeline.rebase_nonsemantic_change(
                    loaded_root,
                    manifest,
                    ledger,
                    change_scope="editorial",
                    reason="Claimed capitalization cleanup",
                )

    def test_required_gate_cannot_be_waived(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self.init(Path(temp), mode="compact")
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            with self.assertRaisesRegex(case_pipeline.CaseError, "required by the execution policy"):
                case_pipeline.set_gate(
                    loaded_root,
                    manifest,
                    ledger,
                    name="global_review",
                    status="not_required",
                    evidence=None,
                    note="Claimed not applicable",
                )
            manifest["gates"]["global_review"].update(
                status="not_required",
                note="Manual bypass",
            )
            case_pipeline.save_case(loaded_root, manifest, ledger)
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            errors = case_pipeline.validate_case(loaded_root, manifest, ledger, final=True)
            self.assertTrue(any("required by the execution policy" in item for item in errors), errors)

    def test_editorial_kernel_refresh_requires_a_new_machine_check(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self.init(Path(temp), mode="compact")
            replace_todo(root / "draft.md", "# Draft\n\nStable")
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            self.assertEqual(
                case_pipeline.run_check(loaded_root, manifest, ledger, final_trace=False),
                [],
            )
            (root / "kernel.md").write_text(
                "# Kernel\n\nEditorially normalized vocabulary\n",
                encoding="utf-8",
            )
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            case_pipeline.refresh_kernel(
                loaded_root,
                manifest,
                ledger,
                [],
                change_scope="editorial",
                reason="Terminology normalization only",
            )
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            with self.assertRaisesRegex(case_pipeline.CaseError, "current kernel"):
                case_pipeline.rebase_nonsemantic_change(
                    loaded_root,
                    manifest,
                    ledger,
                    change_scope="editorial",
                    reason="Terminology normalization only",
                )

    def test_editorial_change_cannot_mask_a_semantic_rewrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self.init(Path(temp), mode="compact")
            replace_todo(root / "draft.md", "# Draft\n\nRefund is allowed")
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            self.assertEqual(
                case_pipeline.run_check(loaded_root, manifest, ledger, final_trace=False),
                [],
            )
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
            replace_todo(root / "draft.md", "# Draft\n\nRefund is forbidden")
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            self.assertEqual(
                case_pipeline.run_check(loaded_root, manifest, ledger, final_trace=False),
                [],
            )
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            with self.assertRaisesRegex(case_pipeline.CaseError, "semantic content"):
                case_pipeline.rebase_nonsemantic_change(
                    loaded_root,
                    manifest,
                    ledger,
                    change_scope="editorial",
                    reason="Claimed wording cleanup",
                )

    def test_planning_probe_requires_boundary_before_author_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "case"
            self.write_method_context(root)
            self.write_mode_decision(root, selected_mode="compact")
            self.write_planning_handoff(root, solution_boundary_probe=True)
            case_pipeline.init_case(
                root,
                case_id="boundary-required",
                mode="compact",
                intent="create",
                profile_id="generic",
                route_id="core",
                project_root=None,
            )
            replace_todo(root / "draft.md", "# Draft\n\nVerified scope")
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            with self.assertRaisesRegex(
                case_pipeline.CaseError,
                "no final solution-boundary block",
            ):
                case_pipeline.set_gate(
                    loaded_root,
                    manifest,
                    ledger,
                    name="author_passes",
                    status="pass",
                    evidence="draft.md",
                    note=None,
                )

            self.write_solution_boundary(root, "bounded-systemic")
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            case_pipeline.set_gate(
                loaded_root,
                manifest,
                ledger,
                name="author_passes",
                status="pass",
                evidence="draft.md",
                note=None,
            )
            _, manifest, _ = case_pipeline.load_case(root)
            self.assertEqual(manifest["gates"]["author_passes"]["status"], "pass")

    def test_tactical_boundary_requires_architecture_design(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "case"
            self.write_method_context(root)
            self.write_mode_decision(root, selected_mode="compact")
            self.write_planning_handoff(root, solution_boundary_probe=True)
            case_pipeline.init_case(
                root,
                case_id="tactical-boundary",
                mode="compact",
                intent="create",
                profile_id="generic",
                route_id="core",
                project_root=None,
            )
            replace_todo(root / "draft.md", "# Draft\n\nNarrow reversible fix")
            self.write_solution_boundary(root, "tactical")
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            with self.assertRaisesRegex(
                case_pipeline.CaseError,
                "requires a passed architecture_design gate",
            ):
                case_pipeline.set_gate(
                    loaded_root,
                    manifest,
                    ledger,
                    name="author_passes",
                    status="pass",
                    evidence="draft.md",
                    note=None,
                )
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            case_pipeline.set_gate(
                loaded_root,
                manifest,
                ledger,
                name="architecture_design",
                status="pass",
                evidence="decisions.md",
                note=None,
            )
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            case_pipeline.set_gate(
                loaded_root,
                manifest,
                ledger,
                name="author_passes",
                status="pass",
                evidence="draft.md",
                note=None,
            )
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            with self.assertRaisesRegex(
                case_pipeline.CaseError,
                "architecture_conformance must pass",
            ):
                case_pipeline.set_gate(
                    loaded_root,
                    manifest,
                    ledger,
                    name="architecture_conformance",
                    status="not_required",
                    evidence=None,
                    note="No additional review",
                )

    def test_boundary_required_gates_cannot_be_marked_not_required(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "case"
            self.write_method_context(root)
            self.write_mode_decision(root, selected_mode="compact")
            self.write_planning_handoff(root, solution_boundary_probe=True)
            case_pipeline.init_case(
                root,
                case_id="boundary-required-gates",
                mode="compact",
                intent="create",
                profile_id="generic",
                route_id="core",
                project_root=None,
            )
            self.write_solution_boundary(root, "bounded-systemic")
            for gate_name in ("author_passes", "global_review"):
                loaded_root, manifest, ledger = case_pipeline.load_case(root)
                with self.assertRaisesRegex(
                    case_pipeline.CaseError,
                    f"{gate_name} must pass",
                ):
                    case_pipeline.set_gate(
                        loaded_root,
                        manifest,
                        ledger,
                        name=gate_name,
                        status="not_required",
                        evidence=None,
                        note="Attempted bypass",
                    )

            manifest_path = root / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["gates"]["author_passes"]["status"] = "not_required"
            manifest["gates"]["global_review"]["status"] = "not_required"
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            errors = case_pipeline.validate_case(
                loaded_root, manifest, ledger, final=True
            )
            self.assertTrue(
                any("Gate author_passes must pass" in item for item in errors)
            )
            self.assertTrue(
                any("Gate global_review must pass" in item for item in errors)
            )

    def test_boundary_change_invalidates_author_pass_subject(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "case"
            self.write_method_context(root)
            self.write_mode_decision(root, selected_mode="compact")
            self.write_planning_handoff(root, solution_boundary_probe=True)
            case_pipeline.init_case(
                root,
                case_id="boundary-tamper",
                mode="compact",
                intent="create",
                profile_id="generic",
                route_id="core",
                project_root=None,
            )
            replace_todo(root / "draft.md", "# Draft\n\nVerified scope")
            self.write_solution_boundary(root, "bounded-systemic")
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            case_pipeline.set_gate(
                loaded_root,
                manifest,
                ledger,
                name="author_passes",
                status="pass",
                evidence="draft.md",
                note=None,
            )
            decisions = root / "decisions.md"
            decisions.write_text(
                decisions.read_text(encoding="utf-8").replace(
                    "Handle the capability consistently",
                    "Handle the capability with a changed boundary",
                ),
                encoding="utf-8",
            )
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            errors = case_pipeline.validate_case(
                loaded_root, manifest, ledger, final=True
            )
            self.assertTrue(
                any("Gate author_passes subject changed" in item for item in errors)
            )

    def test_boundary_change_invalidates_global_and_architecture_reviews(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "case"
            self.write_method_context(root)
            self.write_mode_decision(root, selected_mode="compact")
            self.write_planning_handoff(root, solution_boundary_probe=True)
            case_pipeline.init_case(
                root,
                case_id="boundary-review-tamper",
                mode="compact",
                intent="create",
                profile_id="generic",
                route_id="core",
                project_root=None,
            )
            replace_todo(root / "draft.md", "# Draft\n\nVerified scope")
            replace_todo(root / "reviews" / "global.md", "# Global\n\nPASS")
            replace_todo(
                root / "reviews" / "architecture.md",
                "# Architecture conformance\n\nPASS",
            )
            self.write_solution_boundary(root, "bounded-systemic")
            for name, evidence in (
                ("author_passes", "draft.md"),
                ("global_review", "reviews/global.md"),
                ("architecture_conformance", "reviews/architecture.md"),
            ):
                loaded_root, manifest, ledger = case_pipeline.load_case(root)
                case_pipeline.set_gate(
                    loaded_root,
                    manifest,
                    ledger,
                    name=name,
                    status="pass",
                    evidence=evidence,
                    note=None,
                )
            decisions = root / "decisions.md"
            decisions.write_text(
                decisions.read_text(encoding="utf-8").replace(
                    "Handle the capability consistently",
                    "Handle a newly changed capability boundary",
                ),
                encoding="utf-8",
            )
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            errors = case_pipeline.validate_case(
                loaded_root, manifest, ledger, final=True
            )
            self.assertTrue(
                any("Gate global_review subject changed" in item for item in errors)
            )
            self.assertTrue(
                any(
                    "Gate architecture_conformance subject changed" in item
                    for item in errors
                )
            )

    def test_status_handles_non_object_working_projection_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self.init(Path(temp))
            (root / case_pipeline.WORKING_PROJECTION_JSON).write_text(
                "[]\n", encoding="utf-8"
            )
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            case_pipeline.render_status(loaded_root, manifest, ledger)
            status = (root / "status.md").read_text(encoding="utf-8")
            self.assertIn("working projection: `invalid`", status)

    def test_projection_update_cli_requires_evidence_kind(self) -> None:
        parser = case_pipeline.build_parser()
        args = parser.parse_args(
            [
                "projection-update",
                "--case-root",
                "/tmp/case",
                "--target-id",
                "EXT-001",
                "--source",
                "draft",
                "--source-sha256",
                "a" * 64,
                "--content-sha256",
                "b" * 64,
                "--evidence-kind",
                "external_readback",
                "--evidence-ref",
                "readbacks/ext-001.json",
                "--read-back-at",
                "2026-08-08T10:30:00+00:00",
            ]
        )
        self.assertEqual(args.evidence_kind, "external_readback")

    def test_legacy_planning_role_context_without_projection_stays_valid(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "case"
            self.write_method_context(root)
            self.write_mode_decision(root)
            self.write_planning_handoff(root)
            handoff_path = root / planning_case.HANDOFF_JSON
            handoff = json.loads(handoff_path.read_text(encoding="utf-8"))
            handoff.pop("working_projection")
            handoff["fingerprint"] = planning_case.canonical_fingerprint(handoff)
            handoff_path.write_text(
                json.dumps(handoff, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            case_pipeline.init_case(
                root,
                case_id="legacy-role-context",
                mode="block",
                intent="create",
                profile_id="generic",
                route_id="core",
                project_root=None,
            )
            role_path = root / case_pipeline.PLANNING_ROLE_CONTEXT_JSON
            role_context = json.loads(role_path.read_text(encoding="utf-8"))
            role_context.pop("working_projection")
            role_context["fingerprint"] = case_pipeline.role_context_fingerprint(
                role_context
            )
            role_path.write_text(
                json.dumps(role_context, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            manifest_path = root / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["planning_handoff"]["role_context_fingerprint"] = role_context[
                "fingerprint"
            ]
            manifest["artifacts"].pop("working_projection")
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            (root / case_pipeline.WORKING_PROJECTION_JSON).unlink()
            (root / case_pipeline.ROLE_MANIFEST_JSON).write_text(
                json.dumps(
                    case_pipeline.role_manifest(manifest),
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            self.assertEqual(
                case_pipeline.validate_case(loaded_root, manifest, ledger, final=False),
                [],
            )

    def test_migrate_planning_preserves_semantic_work_and_archives_old_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            root = base / "case"
            self.write_method_context(root)
            self.write_mode_decision(root)
            self.write_timed_planning_handoff(root, revision=1)
            case_pipeline.init_case(
                root,
                case_id="migration-case",
                mode="block",
                intent="create",
                profile_id="generic",
                route_id="core",
                project_root=None,
            )
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            case_pipeline.add_block(
                loaded_root,
                manifest,
                ledger,
                block_id="B01",
                title="Preserved block",
                kind="scenarios",
                depends_on=[],
            )
            old_timing_hash = case_pipeline.sha256(root / "automation-timing.json")

            replacement = base / "replacement"
            new_payload = self.write_timed_planning_handoff(replacement, revision=2)
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            result = case_pipeline.migrate_planning_handoff(
                loaded_root,
                manifest,
                ledger,
                handoff_root=replacement,
                reason="runtime contract upgrade",
            )

            self.assertEqual(result["from_revision"], 1)
            self.assertEqual(result["to_revision"], 2)
            archive = root / "migrations" / "planning-r001-to-r002"
            self.assertTrue((archive / "migration.json").is_file())
            self.assertEqual(
                case_pipeline.sha256(archive / "automation-timing.json"),
                old_timing_hash,
            )
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            self.assertEqual(manifest["planning_handoff"]["planning_revision"], 2)
            self.assertEqual(manifest["artifacts"]["role_manifest"], "role-manifest.json")
            self.assertEqual(ledger["blocks"][0]["id"], "B01")
            timing = case_pipeline.read_json(root / "automation-timing.json")
            self.assertEqual(timing["planning"]["revision"], 2)
            self.assertEqual(timing["stages"][0]["status"], "pending")
            self.assertEqual(timing["stages"][0]["checklist"][0]["id"], "P01-C01")
            self.assertEqual(
                timing["plan_fingerprint"],
                new_payload["automation_plan"]["fingerprint"],
            )
            self.assertEqual(
                case_pipeline.validate_case(loaded_root, manifest, ledger, final=False),
                [],
            )

    def test_migrate_planning_rejects_in_progress_semantic_block(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            root = base / "case"
            self.write_method_context(root)
            self.write_mode_decision(root)
            self.write_timed_planning_handoff(root, revision=1)
            case_pipeline.init_case(
                root,
                case_id="migration-running",
                mode="block",
                intent="create",
                profile_id="generic",
                route_id="core",
                project_root=None,
            )
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            case_pipeline.add_block(
                loaded_root,
                manifest,
                ledger,
                block_id="B01",
                title="Running block",
                kind="scenarios",
                depends_on=[],
            )
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            case_pipeline.transition_block(
                loaded_root,
                manifest,
                ledger,
                block_id="B01",
                new_status="ready",
                note=None,
            )
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            case_pipeline.transition_block(
                loaded_root,
                manifest,
                ledger,
                block_id="B01",
                new_status="in_progress",
                note=None,
            )
            replacement = base / "replacement"
            self.write_timed_planning_handoff(replacement, revision=2)
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            with self.assertRaises(case_pipeline.CaseError):
                case_pipeline.migrate_planning_handoff(
                    loaded_root,
                    manifest,
                    ledger,
                    handoff_root=replacement,
                    reason="runtime contract upgrade",
                )

    def test_migrate_legacy_case_without_working_projection_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            root = base / "case"
            self.write_method_context(root)
            self.write_mode_decision(root)
            self.write_timed_planning_handoff(root, revision=1)
            case_pipeline.init_case(
                root,
                case_id="legacy-projection-migration",
                mode="block",
                intent="create",
                profile_id="generic",
                route_id="core",
                project_root=None,
            )
            (root / case_pipeline.WORKING_PROJECTION_JSON).unlink()
            replacement = base / "replacement"
            self.write_timed_planning_handoff(replacement, revision=2)

            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            case_pipeline.migrate_planning_handoff(
                loaded_root,
                manifest,
                ledger,
                handoff_root=replacement,
                reason="add working projection runtime contract",
            )

            projection = case_pipeline.read_json(
                root / case_pipeline.WORKING_PROJECTION_JSON
            )
            self.assertEqual(projection["policy"], "optional")
            self.assertEqual(projection["updates"], [])

    def test_migrate_drops_updates_when_projection_target_is_redirected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            root = base / "case"
            self.write_method_context(root)
            self.write_mode_decision(root)
            self.write_planning_handoff(
                root,
                working_projection=True,
                revision=1,
                project_root=str(base),
            )
            case_pipeline.init_case(
                root,
                case_id="redirected-projection",
                mode="block",
                intent="create",
                profile_id="generic",
                route_id="core",
                project_root=str(base),
            )
            replace_todo(root / "draft.md", "# Draft\n\nFirst version")
            visible = base / "specification.md"
            visible.write_text("# Visible\n\nFirst version\n", encoding="utf-8")
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            case_pipeline.record_working_projection_update(
                loaded_root,
                manifest,
                ledger,
                target_id="EXT-001",
                source="draft",
                source_sha256=case_pipeline.sha256(root / "draft.md"),
                content_sha256=case_pipeline.sha256(visible),
                evidence_kind="local_file",
                evidence_ref="specification.md",
                read_back_at="2026-08-08T10:30:00+00:00",
            )

            replacement = base / "replacement"
            self.write_planning_handoff(
                replacement,
                working_projection=True,
                revision=2,
                project_root=str(base),
                projection_object_id="specification-v2.md",
            )
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            case_pipeline.migrate_planning_handoff(
                loaded_root,
                manifest,
                ledger,
                handoff_root=replacement,
                reason="move the visible draft target",
            )

            projection = case_pipeline.read_json(
                root / case_pipeline.WORKING_PROJECTION_JSON
            )
            self.assertEqual(projection["targets"][0]["object_id"], "specification-v2.md")
            self.assertEqual(projection["updates"], [])

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
                allow_unplanned=True,
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
                allow_unplanned=True,
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
                    allow_unplanned=True,
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
                    allow_unplanned=True,
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
                    allow_unplanned=True,
                )

    def test_non_review_init_requires_planning_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "case"
            self.write_method_context(root)
            self.write_mode_decision(root, selected_mode="compact")
            with self.assertRaises(case_pipeline.CaseError):
                case_pipeline.init_case(
                    root,
                    case_id="planning-required",
                    mode="compact",
                    intent="create",
                    profile_id="generic",
                    route_id="core",
                    project_root=None,
                )

    def test_review_init_allows_missing_planning_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "case"
            self.write_method_context(root)
            self.write_mode_decision(root, selected_mode="compact")
            case_pipeline.init_case(
                root,
                case_id="review-without-planning",
                mode="compact",
                intent="review",
                profile_id="generic",
                route_id="core",
                project_root=None,
            )
            _, manifest, _ = case_pipeline.load_case(root)
            self.assertEqual(manifest["intent"], "review")
            self.assertIsNone(manifest["planning_handoff"])

    def test_handoff_project_root_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            root = base / "case"
            first_project = base / "first-project"
            second_project = base / "second-project"
            self.write_method_context(root)
            self.write_mode_decision(root, selected_mode="compact", profile_id="demo")
            self.write_planning_handoff(
                root,
                profile_id="demo",
                project_root=str(first_project.resolve()),
            )
            with self.assertRaises(case_pipeline.CaseError):
                case_pipeline.init_case(
                    root,
                    case_id="project-root-mismatch",
                    mode="compact",
                    intent="create",
                    profile_id="demo",
                    route_id="core",
                    project_root=str(second_project.resolve()),
                )

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
            with self.assertRaises(case_pipeline.CaseError):
                case_pipeline.resolve_init_profile("generic", project)

    def test_explicit_project_root_cannot_bypass_nearest_project_overlay(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            project = base / "project"
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
            unrelated = base / "unrelated"
            unrelated.mkdir()
            with self.assertRaises(case_pipeline.CaseError):
                case_pipeline.resolve_init_project_context(
                    "auto",
                    project,
                    unrelated,
                )

            selection, selected_root = case_pipeline.resolve_init_project_context(
                "auto",
                project,
                project,
            )
            self.assertEqual(selection.profile_id, "demo")
            self.assertEqual(selected_root, str(project.resolve()))

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
                    allow_unplanned=True,
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
                allow_unplanned=True,
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
                allow_unplanned=True,
            )
            path = root / mode_decision.MODE_DECISION_FILENAME
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["task"] = "Tampered"
            path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            errors = case_pipeline.validate_case(loaded_root, manifest, ledger, final=True)
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

    def test_reviewed_block_must_reach_visible_projection_before_next_work(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project_root = Path(temp)
            root = project_root / "case"
            self.write_method_context(root)
            self.write_mode_decision(root)
            self.write_planning_handoff(
                root,
                working_projection=True,
                project_root=str(project_root),
            )
            case_pipeline.init_case(
                root,
                case_id="visible-draft",
                mode="block",
                intent="create",
                profile_id="generic",
                route_id="core",
                project_root=str(project_root),
            )
            replace_todo(root / "kernel.md", "# Kernel\n\nStable kernel")
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            case_pipeline.refresh_kernel(loaded_root, manifest, ledger, [])
            self.add(root, "B01")
            self.add(root, "B02", ["B01"])
            self.analyze_and_review(root, "B01", "SCN-B01-001")
            self.transition(root, "B02", "ready")
            with self.assertRaises(case_pipeline.CaseError):
                self.transition(root, "B02", "in_progress")

            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            source_hash = case_pipeline.blocks_by_id(ledger)["B01"]["artifact_sha256"]
            visible = project_root / "specification.md"
            visible.write_text("# Visible draft\n\nB01 reviewed.\n", encoding="utf-8")
            case_pipeline.record_working_projection_update(
                loaded_root,
                manifest,
                ledger,
                target_id="EXT-001",
                source="B01",
                source_sha256=source_hash,
                content_sha256=case_pipeline.sha256(visible),
                evidence_kind="local_file",
                evidence_ref="specification.md",
                read_back_at="2026-08-08T10:30:00+00:00",
            )
            _, _, ledger = case_pipeline.load_case(root)
            prior_review = case_pipeline.blocks_by_id(ledger)["B01"]["review_history"][0]["evidence"]
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            case_pipeline.begin_block_remediation(
                loaded_root,
                manifest,
                ledger,
                block_id="B01",
                findings=[{"id": "F-B01-001", "severity": "major"}],
                semantic_ids=["SCN-B01-001"],
                evidence="reviews/B01.md",
                reason="Correct the reviewed block before continuing",
            )
            replace_todo(root / "blocks" / "B01.md", "# B01\n\nCorrected analysis")
            self.transition(root, "B01", "analyzed")
            replace_todo(
                root / "reviews" / "B01.md",
                "# Targeted review\n\n"
                "review_scope: targeted-remediation\n"
                "verified_findings: [F-B01-001]\n"
                f"coverage_reused: {prior_review}\n\nPASS",
            )
            self.transition(root, "B01", "reviewed")
            with self.assertRaises(case_pipeline.CaseError):
                self.transition(root, "B02", "in_progress")
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            corrected_hash = case_pipeline.blocks_by_id(ledger)["B01"]["artifact_sha256"]
            visible.write_text("# Visible draft\n\nB01 corrected.\n", encoding="utf-8")
            case_pipeline.record_working_projection_update(
                loaded_root,
                manifest,
                ledger,
                target_id="EXT-001",
                source="B01",
                source_sha256=corrected_hash,
                content_sha256=case_pipeline.sha256(visible),
                evidence_kind="local_file",
                evidence_ref="specification.md",
                read_back_at="2026-08-08T10:40:00+00:00",
            )
            self.transition(root, "B02", "in_progress")
            payload = json.loads(
                (root / case_pipeline.WORKING_PROJECTION_JSON).read_text(encoding="utf-8")
            )
            self.assertEqual(len(payload["updates"]), 2)
            self.assertEqual(payload["updates"][-1]["source_sha256"], corrected_hash)

    def test_reviewed_block_can_begin_remediation_before_projection(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project_root = Path(temp)
            root = project_root / "case"
            self.write_method_context(root)
            self.write_mode_decision(root)
            self.write_planning_handoff(
                root,
                working_projection=True,
                project_root=str(project_root),
            )
            case_pipeline.init_case(
                root,
                case_id="reviewed-rollback",
                mode="block",
                intent="create",
                profile_id="generic",
                route_id="core",
                project_root=str(project_root),
            )
            replace_todo(root / "kernel.md", "# Kernel\n\nStable kernel")
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            case_pipeline.refresh_kernel(loaded_root, manifest, ledger, [])
            self.add(root, "B01")
            self.analyze_and_review(root, "B01", "SCN-B01-001")

            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            case_pipeline.begin_block_remediation(
                loaded_root,
                manifest,
                ledger,
                block_id="B01",
                findings=[{"id": "F-B01-001", "severity": "major"}],
                semantic_ids=["SCN-B01-001"],
                evidence="reviews/B01.md",
                reason="Correct the reviewed block before projection",
            )

            _, _, ledger = case_pipeline.load_case(root)
            self.assertEqual(
                case_pipeline.blocks_by_id(ledger)["B01"]["status"],
                "in_progress",
            )

    def test_projection_update_rejects_unknown_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project_root = Path(temp)
            root = project_root / "case"
            self.write_method_context(root)
            self.write_mode_decision(root)
            self.write_planning_handoff(
                root,
                working_projection=True,
                project_root=str(project_root),
            )
            case_pipeline.init_case(
                root,
                case_id="projection-source",
                mode="block",
                intent="create",
                profile_id="generic",
                route_id="core",
                project_root=str(project_root),
            )
            visible = project_root / "specification.md"
            visible.write_text("visible\n", encoding="utf-8")
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            with self.assertRaises(case_pipeline.CaseError):
                case_pipeline.record_working_projection_update(
                    loaded_root,
                    manifest,
                    ledger,
                    target_id="EXT-001",
                    source="arbitrary",
                    source_sha256="a" * 64,
                    content_sha256=case_pipeline.sha256(visible),
                    evidence_kind="local_file",
                    evidence_ref="specification.md",
                    read_back_at="2026-08-08T10:30:00+00:00",
                )

    def test_local_projection_update_checks_read_back_content_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project_root = Path(temp)
            root = project_root / "case"
            self.write_method_context(root)
            self.write_mode_decision(root, selected_mode="compact")
            self.write_planning_handoff(
                root,
                working_projection=True,
                project_root=str(project_root),
            )
            case_pipeline.init_case(
                root,
                case_id="local-readback",
                mode="compact",
                intent="create",
                profile_id="generic",
                route_id="core",
                project_root=str(project_root),
            )
            replace_todo(root / "draft.md", "# Draft\n\nComplete")
            visible = project_root / "specification.md"
            visible.write_text("# Visible\n\nComplete\n", encoding="utf-8")
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            with self.assertRaises(case_pipeline.CaseError):
                case_pipeline.record_working_projection_update(
                    loaded_root,
                    manifest,
                    ledger,
                    target_id="EXT-001",
                    source="draft",
                    source_sha256=case_pipeline.sha256(root / "draft.md"),
                    content_sha256="a" * 64,
                    evidence_kind="local_file",
                    evidence_ref="specification.md",
                    read_back_at="2026-08-08T10:30:00+00:00",
                )

            update = {
                "target_id": "EXT-001",
                "source": "draft",
                "source_sha256": case_pipeline.sha256(root / "draft.md"),
                "content_sha256": case_pipeline.sha256(visible),
                "evidence_kind": "local_file",
                "evidence_ref": "specification.md",
                "read_back_at": "2026-08-08T10:30:00+00:00",
            }
            case_pipeline.record_working_projection_update(
                loaded_root,
                manifest,
                ledger,
                **update,
            )
            manifest_before = (root / "manifest.json").read_bytes()
            projection_before = (
                root / case_pipeline.WORKING_PROJECTION_JSON
            ).read_bytes()
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            case_pipeline.record_working_projection_update(
                loaded_root,
                manifest,
                ledger,
                **update,
            )
            self.assertEqual((root / "manifest.json").read_bytes(), manifest_before)
            self.assertEqual(
                (root / case_pipeline.WORKING_PROJECTION_JSON).read_bytes(),
                projection_before,
            )
            visible.write_text("# Visible\n\nComplete plus note\n", encoding="utf-8")
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            case_pipeline.record_working_projection_update(
                loaded_root,
                manifest,
                ledger,
                **{
                    **update,
                    "content_sha256": case_pipeline.sha256(visible),
                    "read_back_at": "2026-08-08T10:40:00+00:00",
                },
            )
            projection = case_pipeline.read_json(
                root / case_pipeline.WORKING_PROJECTION_JSON
            )
            self.assertEqual(len(projection["updates"]), 2)
            visible.write_text("# Visible\n\nComplete\n", encoding="utf-8")
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            case_pipeline.record_working_projection_update(
                loaded_root,
                manifest,
                ledger,
                **{
                    **update,
                    "content_sha256": case_pipeline.sha256(visible),
                    "read_back_at": "2026-08-08T10:50:00+00:00",
                },
            )
            projection = case_pipeline.read_json(
                root / case_pipeline.WORKING_PROJECTION_JSON
            )
            self.assertEqual(len(projection["updates"]), 3)
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            self.assertEqual(
                case_pipeline.working_projection_errors(
                    loaded_root,
                    manifest,
                    ledger,
                    require_any_update=True,
                ),
                [],
            )

    def test_milestone_projection_binds_multiple_sources_to_one_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project_root = Path(temp)
            root = project_root / "case"
            self.write_method_context(root)
            self.write_mode_decision(
                root,
                assurance="standard",
                tracking="milestones",
                projection_sync="milestones",
            )
            self.write_planning_handoff(
                root,
                working_projection=True,
                project_root=str(project_root),
            )
            case_pipeline.init_case(
                root,
                case_id="milestone-shared-snapshot",
                mode="block",
                intent="create",
                profile_id="generic",
                route_id="core",
                project_root=str(project_root),
            )
            self.add(root, "B01")
            self.add(root, "B02")
            self.analyze_and_review(root, "B01", "SCN-B01-001")
            self.analyze_and_review(root, "B02", "SCN-B02-001")
            visible = project_root / "specification.md"
            visible.write_text("# Visible\n\nBoth blocks\n", encoding="utf-8")
            for block_id in ("B01", "B02"):
                loaded_root, manifest, ledger = case_pipeline.load_case(root)
                block = case_pipeline.blocks_by_id(ledger)[block_id]
                case_pipeline.record_working_projection_update(
                    loaded_root,
                    manifest,
                    ledger,
                    target_id="EXT-001",
                    source=block_id,
                    source_sha256=block["artifact_sha256"],
                    content_sha256=case_pipeline.sha256(visible),
                    evidence_kind="local_file",
                    evidence_ref="specification.md",
                    read_back_at="2026-08-10T20:00:00+00:00",
                )
            payload = json.loads(
                (root / case_pipeline.WORKING_PROJECTION_JSON).read_text(encoding="utf-8")
            )
            self.assertEqual(len(payload["updates"]), 1)
            sources = case_pipeline.projection_update_sources(payload, "EXT-001")
            self.assertEqual(set(sources), {"B01", "B02"})
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            self.assertEqual(
                case_pipeline.working_projection_errors(
                    loaded_root,
                    manifest,
                    ledger,
                    require_any_update=False,
                ),
                [],
            )

    def test_hidden_case_file_cannot_satisfy_local_projection(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project_root = Path(temp)
            root = project_root / "case"
            self.write_method_context(root)
            self.write_mode_decision(root, selected_mode="compact")
            self.write_planning_handoff(
                root,
                working_projection=True,
                project_root=str(project_root),
                projection_object_id="case/draft.md",
            )
            case_pipeline.init_case(
                root,
                case_id="hidden-projection",
                mode="compact",
                intent="create",
                profile_id="generic",
                route_id="core",
                project_root=str(project_root),
            )
            replace_todo(root / "draft.md", "# Draft\n\nHidden runtime content")
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            with self.assertRaisesRegex(case_pipeline.CaseError, "Hidden runtime case"):
                case_pipeline.record_working_projection_update(
                    loaded_root,
                    manifest,
                    ledger,
                    target_id="EXT-001",
                    source="draft",
                    source_sha256=case_pipeline.sha256(root / "draft.md"),
                    content_sha256=case_pipeline.sha256(root / "draft.md"),
                    evidence_kind="local_file",
                    evidence_ref="case/draft.md",
                    read_back_at="2026-08-08T10:30:00+00:00",
                )

    def test_external_projection_rejects_parallel_local_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project_root = Path(temp)
            root = project_root / "case"
            self.write_method_context(root)
            self.write_mode_decision(root, selected_mode="compact")
            self.write_planning_handoff(
                root,
                working_projection=True,
                project_root=str(project_root),
                projection_object_id="TASK-42",
                projection_url="https://tracker.example.invalid/TASK-42",
                projection_evidence_kind="external_readback",
            )
            case_pipeline.init_case(
                root,
                case_id="external-no-local-duplicate",
                mode="compact",
                intent="create",
                profile_id="generic",
                route_id="core",
                project_root=str(project_root),
            )
            replace_todo(root / "draft.md", "# Draft\n\nComplete")
            local_duplicate = project_root / "TASK-42"
            local_duplicate.write_text("duplicate\n", encoding="utf-8")
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            with self.assertRaisesRegex(
                case_pipeline.CaseError,
                "does not match the declared target contract",
            ):
                case_pipeline.record_working_projection_update(
                    loaded_root,
                    manifest,
                    ledger,
                    target_id="EXT-001",
                    source="draft",
                    source_sha256=case_pipeline.sha256(root / "draft.md"),
                    content_sha256=case_pipeline.sha256(local_duplicate),
                    evidence_kind="local_file",
                    evidence_ref="TASK-42",
                    read_back_at="2026-08-08T10:30:00+00:00",
                )

    def test_external_projection_update_requires_stable_adapter_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "case"
            self.write_method_context(root)
            self.write_mode_decision(root, selected_mode="compact")
            self.write_planning_handoff(
                root,
                working_projection=True,
                projection_url="https://tracker.example.invalid/TASK-42",
                projection_evidence_kind="external_readback",
            )
            case_pipeline.init_case(
                root,
                case_id="external-readback",
                mode="compact",
                intent="create",
                profile_id="generic",
                route_id="core",
                project_root=None,
            )
            replace_todo(root / "draft.md", "# Draft\n\nComplete")
            read_back_at = "2026-08-08T10:30:00+00:00"
            content_hash = "b" * 64
            receipt = self.write_external_receipt(
                root,
                content_sha256=content_hash,
                read_back_at=read_back_at,
            )
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            case_pipeline.record_working_projection_update(
                loaded_root,
                manifest,
                ledger,
                target_id="EXT-001",
                source="draft",
                source_sha256=case_pipeline.sha256(root / "draft.md"),
                content_sha256=content_hash,
                evidence_kind="external_readback",
                evidence_ref=receipt,
                read_back_at=read_back_at,
            )
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            self.assertEqual(
                case_pipeline.validate_case(loaded_root, manifest, ledger, final=False),
                [],
            )

            receipt_path = root / receipt
            payload = json.loads(receipt_path.read_text(encoding="utf-8"))
            payload["content_sha256"] = "c" * 64
            receipt_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            errors = case_pipeline.validate_case(loaded_root, manifest, ledger, final=False)
            self.assertTrue(any("receipt" in error for error in errors))

    def test_compact_author_pass_requires_current_draft_projection(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project_root = Path(temp)
            root = project_root / "case"
            self.write_method_context(root)
            self.write_mode_decision(root, selected_mode="compact")
            self.write_planning_handoff(
                root,
                working_projection=True,
                project_root=str(project_root),
            )
            case_pipeline.init_case(
                root,
                case_id="compact-projection-freshness",
                mode="compact",
                intent="create",
                profile_id="generic",
                route_id="core",
                project_root=str(project_root),
            )
            draft = root / "draft.md"
            visible = project_root / "specification.md"
            replace_todo(draft, "# Draft\n\nVersion one")
            visible.write_text("# Visible\n\nVersion one\n", encoding="utf-8")
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            case_pipeline.record_working_projection_update(
                loaded_root,
                manifest,
                ledger,
                target_id="EXT-001",
                source="draft",
                source_sha256=case_pipeline.sha256(draft),
                content_sha256=case_pipeline.sha256(visible),
                evidence_kind="local_file",
                evidence_ref="specification.md",
                read_back_at="2026-08-08T10:30:00+00:00",
            )

            replace_todo(draft, "# Draft\n\nVersion two")
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            with self.assertRaises(case_pipeline.CaseError):
                case_pipeline.set_gate(
                    loaded_root,
                    manifest,
                    ledger,
                    name="author_passes",
                    status="pass",
                    evidence="draft.md",
                    note=None,
                )

            visible.write_text("# Visible\n\nVersion two\n", encoding="utf-8")
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            case_pipeline.record_working_projection_update(
                loaded_root,
                manifest,
                ledger,
                target_id="EXT-001",
                source="draft",
                source_sha256=case_pipeline.sha256(draft),
                content_sha256=case_pipeline.sha256(visible),
                evidence_kind="local_file",
                evidence_ref="specification.md",
                read_back_at="2026-08-08T10:40:00+00:00",
            )
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            case_pipeline.set_gate(
                loaded_root,
                manifest,
                ledger,
                name="author_passes",
                status="pass",
                evidence="draft.md",
                note=None,
            )

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

    def test_project_conformance_rejects_missing_profile_owned_toc(self) -> None:
        valid = """# Specification

---

## Оглавление

1. [[#История изменений]]
2. [[#Описание]]
3. [[#User Story]]
4. [[#Полезные ссылки]]

---

## История изменений

Text.

## Описание

Text.

## User Story

Text.

## Полезные ссылки

Text.
"""
        missing_toc = """# Specification

## История изменений

Text.

## Описание

Text.

## User Story

Text.

## Полезные ссылки

Text.
"""
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            root = project / ".vigers" / "cases" / "demo"
            self.write_method_context(root)
            self.write_mode_decision(root, selected_mode="compact")
            self.write_planning_handoff(
                root,
                project_root=str(project),
                working_projection=True,
            )
            project.mkdir(parents=True, exist_ok=True)
            visible = project / "specification.md"
            visible.write_text(missing_toc, encoding="utf-8")
            case_pipeline.init_case(
                root,
                case_id="demo-document-contract",
                mode="compact",
                intent="create",
                profile_id="generic",
                route_id="core",
                project_root=str(project),
                document_contract=self.project_document_contract(),
            )
            replace_todo(root / "draft.md", missing_toc)
            draft_hash = case_pipeline.sha256(root / "draft.md")
            visible_hash = case_pipeline.sha256(visible)
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            case_pipeline.record_working_projection_update(
                loaded_root,
                manifest,
                ledger,
                target_id="EXT-001",
                source="draft",
                source_sha256=draft_hash,
                content_sha256=visible_hash,
                evidence_kind="local_file",
                evidence_ref="specification.md",
                read_back_at="2026-08-10T20:00:00+00:00",
            )
            replace_todo(root / "reviews" / "project.md", "# Project review\n\nPASS")
            os.utime(root / "reviews" / "project.md", ns=(1, 1))

            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            with self.assertRaisesRegex(case_pipeline.CaseError, "missing required H2"):
                case_pipeline.set_gate(
                    loaded_root,
                    manifest,
                    ledger,
                    name="project_conformance",
                    status="pass",
                    evidence="reviews/project.md",
                    note=None,
                )

            replace_todo(root / "draft.md", valid)
            visible.write_text(valid, encoding="utf-8")
            draft_hash = case_pipeline.sha256(root / "draft.md")
            visible_hash = case_pipeline.sha256(visible)
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            case_pipeline.record_working_projection_update(
                loaded_root,
                manifest,
                ledger,
                target_id="EXT-001",
                source="draft",
                source_sha256=draft_hash,
                content_sha256=visible_hash,
                evidence_kind="local_file",
                evidence_ref="specification.md",
                read_back_at="2026-08-10T20:05:00+00:00",
            )
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            with self.assertRaisesRegex(case_pipeline.CaseError, "older than"):
                case_pipeline.set_gate(
                    loaded_root,
                    manifest,
                    ledger,
                    name="project_conformance",
                    status="pass",
                    evidence="reviews/project.md",
                    note=None,
                )

            replace_todo(
                root / "reviews" / "project.md",
                "# Project review\n\nFresh PASS after document correction",
            )
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            case_pipeline.set_gate(
                loaded_root,
                manifest,
                ledger,
                name="project_conformance",
                status="pass",
                evidence="reviews/project.md",
                note=None,
            )
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            self.assertEqual(manifest["gates"]["project_conformance"]["status"], "pass")
            self.assertTrue(
                manifest["gates"]["project_conformance"]["evidence"].startswith(
                    "reviews/history/project_conformance-r001"
                )
            )

            visible.write_text(missing_toc, encoding="utf-8")
            loaded_root, manifest, ledger = case_pipeline.load_case(root)
            errors = case_pipeline.validate_case(loaded_root, manifest, ledger, final=True)
            self.assertTrue(any("missing required H2" in item for item in errors))
            self.assertTrue(
                any("project_conformance subject changed" in item for item in errors),
                errors,
            )

    def test_review_gate_evidence_is_preserved_by_revision(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self.init(Path(temp), mode="compact")
            review = root / "reviews" / "global.md"
            replace_todo(review, "# Global review\n\nFirst pass")
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
            replace_todo(review, "# Global review\n\nSecond pass")
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
            first = root / "reviews" / "history" / "global_review-r001.md"
            second = root / "reviews" / "history" / "global_review-r002.md"
            self.assertIn("First pass", first.read_text(encoding="utf-8"))
            self.assertIn("Second pass", second.read_text(encoding="utf-8"))

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
