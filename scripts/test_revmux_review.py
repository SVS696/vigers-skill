#!/usr/bin/env python3
"""Tests for revmux context preparation, evidence, and adoption metrics."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import revmux_review as review


class RevmuxReviewTest(unittest.TestCase):
    def test_dependency_rejects_incompatible_revmux_build(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            binary = Path(raw) / "revmux"
            binary.write_text(
                "#!/bin/sh\necho 'revmux master-deadbee-test'\n", encoding="utf-8"
            )
            binary.chmod(0o755)
            with self.assertRaisesRegex(review.EvidenceError, "unsupported revmux build"):
                review.detect_revmux(str(binary))

    def make_round(self, root: Path, *, profile: str, findings: list[dict] | None = None) -> tuple[Path, Path]:
        (root / "prompts" / "stages").mkdir(parents=True)
        (root / "agents").mkdir()
        (root / "prompts" / "stages" / "synthesis.md").write_text("x", encoding="utf-8")
        (root / "prompts" / "stages" / "verify-one.md").write_text("x", encoding="utf-8")
        scope = {"task": "review-1", "run": root.name, "scope_path": str(root / "input/scope.md")}
        agents = [
            {
                "name": "one",
                "lenses": ["a"],
                "executor": "claude",
                "requested_model": "opus",
                "actual_model": "opus",
                "effort": "high",
                "tokens": 50,
                "raised": len(findings or []),
                "degraded": False,
            }
        ]
        report = {
            "scope": scope,
            "sources": {"expected": 1, "reported": 1, "degraded": [], "agents": agents},
            "findings": findings or [],
            "open_questions": [],
            "pre_existing": [],
            "immaterial": [],
            "stats": {
                "duration_ms": 100,
                "tokens": 50,
                "stages": [{"name": "synthesis"}, {"name": "verify"}],
            },
        }
        manifest = {
            **scope,
            "profile": profile,
            "duration_ms": 100,
            "tokens": 50,
            "agents": agents,
            "degraded": [],
            "prompts": [],
            "stages": [],
        }
        report_path = root / "findings.json"
        manifest_path = root / "manifest.json"
        report_path.write_text(json.dumps(report), encoding="utf-8")
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        return report_path, manifest_path

    def test_prepare_materializes_exact_block_target_and_baselines(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            case_root = root / "case"
            skill_root = root / "skill"
            input_root = root / "round" / "input"
            for path in (
                case_root / "blocks",
                skill_root / "agents" / "contracts",
                skill_root / "references",
                input_root,
            ):
                path.mkdir(parents=True, exist_ok=True)
            case_files = {
                "role-manifest.json": "{}\n",
                "kernel.md": "# Kernel\n\nInvariant\n",
                "blocks/B01.md": "# B01\n\nFlow\n",
                "blocks/B01.index.json": "{}\n",
            }
            for relative, content in case_files.items():
                (case_root / relative).write_text(content, encoding="utf-8")
            contract_files = {
                "agents/contracts/spec-reviewer.md": "# Reviewer\n",
                "references/revmux-review-backend.md": "# Backend\n",
            }
            for relative, content in contract_files.items():
                (skill_root / relative).write_text(content, encoding="utf-8")
            profile = root / "project-profile.md"
            profile.write_text("# Project rules\n\nUse the frozen contract.\n", encoding="utf-8")
            revmux_bin = root / "revmux"
            revmux_bin.write_text(
                "#!/bin/sh\necho 'revmux master-33ede7a-test'\n", encoding="utf-8"
            )
            revmux_bin.chmod(0o755)
            assignment_path = root / "assignment.json"
            assignment_path.write_text(
                json.dumps(
                    {
                        "case_id": "case-1",
                        "role": "spec-reviewer",
                        "role_mode": "block",
                        "review_scope": "full-block",
                        "review_backend": "revmux",
                        "review_phase": "initial",
                        "revmux_profile": "vigers-review",
                        "covered_gates": ["block_review:B01"],
                        "subject_sha256": None,
                        "block": {
                            "id": "B01",
                            "artifact": "blocks/B01.md",
                            "semantic_index": "blocks/B01.index.json",
                        },
                        "case_inputs": list(case_files),
                        "contract_inputs": list(contract_files),
                        "exclude": ["previous findings", "author reasoning"],
                    }
                ),
                encoding="utf-8",
            )
            args = argparse.Namespace(
                assignment=assignment_path,
                case_root=case_root,
                skill_root=skill_root,
                profile_source=profile,
                revmux_bin=str(revmux_bin),
                scope_output=input_root / "scope.md",
                goal_output=input_root / "goal.md",
                profile_output=input_root / "profile.md",
                context_dir=input_root / "context",
            )
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                self.assertEqual(review.prepare_round(args), 0)
            result = json.loads(stdout.getvalue())
            context = json.loads(
                (input_root / "context" / "vigers-assignment.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(context["role_mode"], "block")
            self.assertEqual(context["covered_gates"], ["block_review:B01"])
            self.assertEqual(
                {item["relative"] for item in context["targets"]},
                {"blocks/B01.md", "blocks/B01.index.json"},
            )
            self.assertIn("kernel.md", {item["relative"] for item in context["baselines"]})
            self.assertEqual(context["subject_sha256"], result["subject_sha256"])
            self.assertEqual(
                context["revmux_dependency"]["compatible_revision"],
                review.REVMUX_COMPAT_REVISION,
            )
            scope = (input_root / "scope.md").read_text(encoding="utf-8")
            self.assertIn("Compare it only against the hashed target/baseline map", scope)
            self.assertIn("block_review:B01", scope)
            self.assertEqual(
                (input_root / "profile.md").read_bytes(),
                profile.read_bytes(),
            )

    def test_prepare_rejects_wrong_gate_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            assignment = root / "assignment.json"
            assignment.write_text(
                json.dumps(
                    {
                        "role": "spec-reviewer",
                        "role_mode": "global",
                        "review_backend": "revmux",
                        "review_phase": "initial",
                        "revmux_profile": "vigers-review",
                        "covered_gates": ["project_conformance"],
                    }
                ),
                encoding="utf-8",
            )
            args = argparse.Namespace(
                assignment=assignment,
                case_root=root,
                skill_root=root,
                profile_source=root / "profile.md",
                revmux_bin="revmux",
                scope_output=root / "scope.md",
                goal_output=root / "goal.md",
                profile_output=root / "round-profile.md",
                context_dir=root / "context",
            )
            with self.assertRaisesRegex(review.EvidenceError, "covered_gates must be exact"):
                review.prepare_round(args)

    def test_round_evidence_and_final_gate(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "01-initial"
            report, manifest = self.make_round(root, profile="vigers-review")
            output = root / "evidence.md"
            metrics = root / "metrics.json"
            args = argparse.Namespace(
                report=report,
                manifest=manifest,
                phase="initial",
                expected_profile="vigers-review",
                subject_sha256="a" * 64,
                covered_gate=["global_review"],
                output=output,
                metrics_output=metrics,
            )
            with contextlib.redirect_stdout(io.StringIO()):
                result = review.write_round(args)
            self.assertEqual(result, 0)
            payload = json.loads(metrics.read_text(encoding="utf-8"))
            self.assertEqual(payload["revmux_model_calls"], 3)
            self.assertEqual(payload["model_calls"], 4)
            self.assertEqual(payload["decision"], "pass")
            self.assertIn("covered_gates: [global_review]", output.read_text(encoding="utf-8"))

    def test_final_gating_finding_fails_without_loop(self) -> None:
        finding = {
            "id": "f1",
            "file": "draft.md",
            "line": 4,
            "severity": "major",
            "confidence": 90,
            "title": "gap",
            "body": "effect",
            "fix": "clarify",
            "sources": ["one"],
            "lenses": ["a"],
            "verdict": "confirmed",
        }
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "02-final"
            report, manifest = self.make_round(root, profile="vigers-final", findings=[finding])
            args = argparse.Namespace(
                report=report,
                manifest=manifest,
                phase="final",
                expected_profile="vigers-final",
                subject_sha256="b" * 64,
                covered_gate=["global_review"],
                output=root / "evidence.md",
                metrics_output=root / "metrics.json",
            )
            with contextlib.redirect_stdout(io.StringIO()):
                result = review.write_round(args)
            self.assertEqual(result, 1)
            payload = json.loads(args.metrics_output.read_text(encoding="utf-8"))
            self.assertEqual(payload["decision"], "fail")
            self.assertEqual(payload["confirmed_major"], 1)

    def test_degraded_round_is_not_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "01-initial"
            report, manifest = self.make_round(root, profile="vigers-review")
            payload = json.loads(report.read_text(encoding="utf-8"))
            payload["sources"]["degraded"] = ["one"]
            report.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(review.EvidenceError):
                review.validate_round(report, manifest, "vigers-review")

    def test_case_and_three_case_aggregate(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            common = {
                "schema": 1,
                "task": "review-1",
                "revmux_duration_ms": 100,
                "model_calls": 3,
                "revmux_tokens": 50,
                "confirmed_critical": 0,
                "confirmed_major": 1,
            }
            initial = root / "initial.json"
            final = root / "final.json"
            initial.write_text(
                json.dumps(
                    {
                        **common,
                        "phase": "initial",
                        "subject_sha256": "a" * 64,
                        "covered_gates": ["global_review"],
                        "gating_areas": ["scope::draft.md"],
                    }
                ),
                encoding="utf-8",
            )
            final.write_text(
                json.dumps(
                    {
                        **common,
                        "phase": "final",
                        "subject_sha256": "b" * 64,
                        "covered_gates": ["global_review"],
                        "confirmed_major": 1,
                        "gating_areas": ["trace::draft.md"],
                        "decision": "fail",
                    }
                ),
                encoding="utf-8",
            )
            receipt = root / "receipt.json"
            args = argparse.Namespace(
                initial_metrics=initial,
                final_metrics=final,
                case_kind="vigers",
                active_time_seconds=120,
                driver_tokens=20,
                correction_rounds=1,
                output=receipt,
            )
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(review.write_case(args), 1)
            payload = json.loads(receipt.read_text(encoding="utf-8"))
            self.assertEqual(payload["initial_subject_sha256"], "a" * 64)
            self.assertEqual(payload["final_subject_sha256"], "b" * 64)
            self.assertEqual(payload["reopened_reviewed_areas"], ["trace::draft.md"])

            aggregate_path = root / "aggregate.json"
            second = root / "receipt-2.json"
            third = root / "receipt-3.json"
            second_payload = {**payload, "task": "review-2", "case_kind": "delivery"}
            third_payload = {**payload, "task": "review-3"}
            second.write_text(json.dumps(second_payload), encoding="utf-8")
            third.write_text(json.dumps(third_payload), encoding="utf-8")
            aggregate_args = argparse.Namespace(
                receipt=[receipt, second, third], output=aggregate_path
            )
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(review.aggregate(aggregate_args), 0)
            aggregate_payload = json.loads(aggregate_path.read_text(encoding="utf-8"))
            self.assertTrue(aggregate_payload["decision_ready"])
            self.assertEqual(aggregate_payload["case_count"], 3)

    def test_case_combines_multiple_distinct_reviewer_gate_pairs(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initial_paths = []
            final_paths = []
            for index, gate in enumerate(("block_review:B01", "global_review"), start=1):
                common = {
                    "schema": 1,
                    "task": "review-block-case",
                    "revmux_duration_ms": 100,
                    "model_calls": 3,
                    "revmux_tokens": 50,
                    "confirmed_critical": 0,
                    "confirmed_major": int(index == 1),
                    "covered_gates": [gate],
                }
                initial = root / f"initial-{index}.json"
                final = root / f"final-{index}.json"
                initial.write_text(
                    json.dumps(
                        {
                            **common,
                            "phase": "initial",
                            "subject_sha256": chr(96 + index) * 64,
                            "gating_areas": [f"scope::{gate}"],
                            "decision": "revise" if index == 1 else "pass",
                        }
                    ),
                    encoding="utf-8",
                )
                final.write_text(
                    json.dumps(
                        {
                            **common,
                            "phase": "final",
                            "subject_sha256": chr(98 + index) * 64,
                            "confirmed_major": 0,
                            "gating_areas": [],
                            "decision": "pass",
                        }
                    ),
                    encoding="utf-8",
                )
                initial_paths.append(initial)
                final_paths.append(final)

            output = root / "receipt.json"
            args = argparse.Namespace(
                initial_metrics=initial_paths,
                final_metrics=final_paths,
                case_kind="vigers",
                active_time_seconds=200,
                driver_tokens=30,
                correction_rounds=1,
                output=output,
            )
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(review.write_case(args), 0)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(len(payload["review_gate_pairs"]), 2)
            self.assertEqual(payload["model_calls"], 12)
            self.assertEqual(payload["tokens"], 230)
            self.assertEqual(payload["confirmed_major"], 1)
            self.assertEqual(payload["final_decision"], "pass")


if __name__ == "__main__":
    unittest.main()
