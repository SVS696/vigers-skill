#!/usr/bin/env python3
"""Regression tests for Vigers automated wall-clock telemetry."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import automation_timing


def demo_plan() -> dict[str, object]:
    """Return a valid two-stage automation plan."""
    plan: dict[str, object] = {
        "policy": "required",
        "metric": "wall_clock",
        "unit": "seconds",
        "execution_use": "human_information_only",
        "stages": [
            {
                "id": "P01",
                "title": "Research",
                "depends_on": [],
                "estimate": {
                    "optimistic_seconds": 60,
                    "likely_seconds": 120,
                    "pessimistic_seconds": 180,
                    "basis": "heuristic",
                    "confidence": "low",
                    "sample_size": 0,
                },
                "external_target_id": None,
                "checklist": [
                    {
                        "id": "P01-C01",
                        "text": "Collect evidence",
                        "required": True,
                        "done_when": "Evidence exists",
                    }
                ],
            },
            {
                "id": "P02",
                "title": "Synthesis",
                "depends_on": ["P01"],
                "estimate": {
                    "optimistic_seconds": 120,
                    "likely_seconds": 240,
                    "pessimistic_seconds": 360,
                    "basis": "heuristic",
                    "confidence": "low",
                    "sample_size": 0,
                },
                "external_target_id": None,
                "checklist": [
                    {
                        "id": "P02-C01",
                        "text": "Synthesize result",
                        "required": True,
                        "done_when": None,
                    }
                ],
            },
        ],
    }
    plan["fingerprint"] = automation_timing.canonical_fingerprint(plan)
    return plan


class AutomationTimingTests(unittest.TestCase):
    def ledger(self) -> dict[str, object]:
        return automation_timing.initialize_ledger(
            case_id="demo-case",
            automation_plan=demo_plan(),
            planning_case_id="demo-plan",
            planning_revision=3,
            passport={"id": "PASS-1", "path": "passport.md"},
            created_at="2026-08-07T10:00:00+00:00",
        )

    def test_start_stop_and_dependency_order(self) -> None:
        ledger = self.ledger()
        with self.assertRaises(automation_timing.AutomationTimingError):
            automation_timing.start_stage(
                ledger,
                "P02",
                at="2026-08-07T10:00:10+00:00",
            )

        automation_timing.start_stage(
            ledger,
            "P01",
            at="2026-08-07T10:00:00+00:00",
        )
        automation_timing.complete_checklist_item(
            ledger,
            "P01",
            "P01-C01",
            evidence_refs=["evidence.md#research"],
            at="2026-08-07T10:01:00+00:00",
        )
        automation_timing.stop_stage(
            ledger,
            "P01",
            status="completed",
            reason=None,
            at="2026-08-07T10:02:00+00:00",
        )
        automation_timing.start_stage(
            ledger,
            "P02",
            at="2026-08-07T10:02:00+00:00",
        )
        automation_timing.complete_checklist_item(
            ledger,
            "P02",
            "P02-C01",
            evidence_refs=["draft.md"],
            at="2026-08-07T10:05:00+00:00",
        )
        automation_timing.stop_stage(
            ledger,
            "P02",
            status="completed",
            reason=None,
            at="2026-08-07T10:06:00+00:00",
        )

        self.assertEqual(automation_timing.validate_ledger(ledger, final=True), [])
        summary = automation_timing.summarize(ledger)
        self.assertEqual(summary["forecast"]["likely_critical_path_seconds"], 360)
        self.assertEqual(summary["actual"]["elapsed_seconds"], 360)
        self.assertEqual(summary["actual"]["likely_estimate_ratio"], 1.0)
        self.assertEqual(summary["completed_checklist_item_count"], 2)

    def test_completed_stage_requires_all_required_checklist_items(self) -> None:
        ledger = self.ledger()
        automation_timing.start_stage(
            ledger,
            "P01",
            at="2026-08-07T10:00:00+00:00",
        )
        with self.assertRaises(automation_timing.AutomationTimingError):
            automation_timing.stop_stage(
                ledger,
                "P01",
                status="completed",
                reason=None,
                at="2026-08-07T10:02:00+00:00",
            )

    def test_checklist_completion_is_idempotent_with_same_evidence(self) -> None:
        ledger = self.ledger()
        automation_timing.start_stage(
            ledger,
            "P01",
            at="2026-08-07T10:00:00+00:00",
        )
        self.assertTrue(
            automation_timing.complete_checklist_item(
                ledger,
                "P01",
                "P01-C01",
                evidence_refs=["evidence.md#research"],
                at="2026-08-07T10:01:00+00:00",
            )
        )
        self.assertFalse(
            automation_timing.complete_checklist_item(
                ledger,
                "P01",
                "P01-C01",
                evidence_refs=["evidence.md#research"],
            )
        )

    def test_external_checklist_requires_checked_read_back(self) -> None:
        plan = demo_plan()
        plan["stages"][0]["external_target_id"] = "EXT-001"
        plan["fingerprint"] = automation_timing.canonical_fingerprint(plan)
        ledger = automation_timing.initialize_ledger(
            case_id="external-case",
            automation_plan=plan,
            planning_case_id="demo-plan",
            planning_revision=3,
            passport=None,
            created_at="2026-08-07T10:00:00+00:00",
        )
        automation_timing.start_stage(
            ledger,
            "P01",
            at="2026-08-07T10:00:00+00:00",
        )
        with self.assertRaises(automation_timing.AutomationTimingError):
            automation_timing.complete_checklist_item(
                ledger,
                "P01",
                "P01-C01",
                evidence_refs=["evidence.md#research"],
                at="2026-08-07T10:01:00+00:00",
            )
        automation_timing.complete_checklist_item(
            ledger,
            "P01",
            "P01-C01",
            evidence_refs=["evidence.md#research"],
            external_system="personal-tasks",
            external_item_id="item-42",
            read_back_at="2026-08-07T10:01:05+00:00",
            at="2026-08-07T10:01:00+00:00",
        )
        self.assertEqual(automation_timing.validate_ledger(ledger), [])

    def test_non_completed_terminal_stage_requires_reason(self) -> None:
        ledger = self.ledger()
        automation_timing.start_stage(
            ledger,
            "P01",
            at="2026-08-07T10:00:00+00:00",
        )
        with self.assertRaises(automation_timing.AutomationTimingError):
            automation_timing.stop_stage(
                ledger,
                "P01",
                status="blocked",
                reason=None,
                at="2026-08-07T10:01:00+00:00",
            )

    def test_estimate_overrun_does_not_affect_execution(self) -> None:
        ledger = self.ledger()
        automation_timing.start_stage(
            ledger,
            "P01",
            at="2026-08-07T10:00:00+00:00",
        )
        automation_timing.complete_checklist_item(
            ledger,
            "P01",
            "P01-C01",
            evidence_refs=["evidence.md#research"],
            at="2026-08-07T10:10:00+00:00",
        )
        automation_timing.stop_stage(
            ledger,
            "P01",
            status="completed",
            reason=None,
            at="2026-08-07T11:00:00+00:00",
        )
        self.assertEqual(ledger["stages"][0]["actual_seconds"], 3600)
        self.assertEqual(ledger["stages"][0]["status"], "completed")
        self.assertEqual(automation_timing.validate_ledger(ledger), [])

    def test_tampered_immutable_plan_is_rejected(self) -> None:
        ledger = self.ledger()
        ledger["stages"][0]["estimate"]["likely_seconds"] = 999
        errors = automation_timing.validate_ledger(ledger)
        self.assertIn("automation timing plan fingerprint mismatch", errors)

    def test_final_validation_rejects_running_timer(self) -> None:
        ledger = self.ledger()
        automation_timing.start_stage(
            ledger,
            "P01",
            at="2026-08-07T10:00:00+00:00",
        )
        errors = automation_timing.validate_ledger(ledger, final=True)
        self.assertTrue(any("unfinished stages" in error for error in errors))

    def test_aggregate_links_case_and_passport(self) -> None:
        ledger = self.ledger()
        automation_timing.start_stage(
            ledger,
            "P01",
            at="2026-08-07T10:00:00+00:00",
        )
        automation_timing.complete_checklist_item(
            ledger,
            "P01",
            "P01-C01",
            evidence_refs=["evidence.md#research"],
            at="2026-08-07T10:01:00+00:00",
        )
        automation_timing.stop_stage(
            ledger,
            "P01",
            status="completed",
            reason=None,
            at="2026-08-07T10:02:00+00:00",
        )
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "case"
            automation_timing.atomic_json(root / automation_timing.FILENAME, ledger)
            result = automation_timing.aggregate([Path(temp)])
        self.assertEqual(result["case_count"], 1)
        self.assertEqual(result["cases"][0]["passport"]["id"], "PASS-1")
        self.assertEqual(result["by_stage_title"]["Research"]["sample_size"], 1)


if __name__ == "__main__":
    unittest.main()
