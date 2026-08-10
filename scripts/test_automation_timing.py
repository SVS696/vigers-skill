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
        automation_timing.begin_checklist_item(
            ledger,
            "P01",
            "P01-C01",
            at="2026-08-07T10:00:30+00:00",
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
        automation_timing.begin_checklist_item(
            ledger,
            "P02",
            "P02-C01",
            at="2026-08-07T10:02:30+00:00",
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

    def test_user_owned_checklist_requires_explicit_confirmation(self) -> None:
        plan = demo_plan()
        plan["stages"][0]["checklist"][0]["completion_owner"] = "user"
        plan["fingerprint"] = automation_timing.canonical_fingerprint(plan)
        ledger = automation_timing.initialize_ledger(
            case_id="manual-handoff",
            automation_plan=plan,
            planning_case_id="manual-plan",
            planning_revision=1,
            passport=None,
            created_at="2026-08-10T20:00:00+00:00",
        )
        automation_timing.start_stage(
            ledger,
            "P01",
            at="2026-08-10T20:00:00+00:00",
        )
        with self.assertRaisesRegex(
            automation_timing.AutomationTimingError,
            "user-owned",
        ):
            automation_timing.begin_checklist_item(ledger, "P01", "P01-C01")
        with self.assertRaisesRegex(
            automation_timing.AutomationTimingError,
            "--user-confirmed",
        ):
            automation_timing.complete_checklist_item(
                ledger,
                "P01",
                "P01-C01",
                evidence_refs=["user said handed to BE"],
            )
        automation_timing.complete_checklist_item(
            ledger,
            "P01",
            "P01-C01",
            evidence_refs=["user said handed to BE"],
            user_confirmed=True,
            at="2026-08-10T20:05:00+00:00",
        )
        item = automation_timing.find_checklist_item(
            automation_timing.find_stage(ledger, "P01"),
            "P01-C01",
        )
        self.assertEqual(item["completion_confirmation"], "user")
        self.assertEqual(automation_timing.validate_ledger(ledger), [])

    def test_checklist_completion_is_idempotent_with_same_evidence(self) -> None:
        ledger = self.ledger()
        automation_timing.start_stage(
            ledger,
            "P01",
            at="2026-08-07T10:00:00+00:00",
        )
        automation_timing.begin_checklist_item(
            ledger,
            "P01",
            "P01-C01",
            at="2026-08-07T10:00:30+00:00",
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
        automation_timing.begin_checklist_item(
            ledger,
            "P01",
            "P01-C01",
            at="2026-08-07T10:00:30+00:00",
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
        automation_timing.begin_checklist_item(
            ledger,
            "P01",
            "P01-C01",
            at="2026-08-07T10:00:30+00:00",
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
        automation_timing.begin_checklist_item(
            ledger,
            "P01",
            "P01-C01",
            at="2026-08-07T10:00:30+00:00",
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

    def test_check_requires_an_explicit_begin(self) -> None:
        ledger = self.ledger()
        automation_timing.start_stage(
            ledger,
            "P01",
            at="2026-08-07T10:00:00+00:00",
        )
        with self.assertRaisesRegex(
            automation_timing.AutomationTimingError,
            "begin it before work",
        ):
            automation_timing.complete_checklist_item(
                ledger,
                "P01",
                "P01-C01",
                evidence_refs=["evidence.md#research"],
                at="2026-08-07T10:01:00+00:00",
            )

    def test_any_pending_item_can_begin_out_of_list_order(self) -> None:
        plan = demo_plan()
        plan["stages"][0]["checklist"].append(
            {
                "id": "P01-C02",
                "text": "Review evidence",
                "required": True,
                "done_when": "Review exists",
            }
        )
        plan["fingerprint"] = automation_timing.canonical_fingerprint(plan)
        ledger = automation_timing.initialize_ledger(
            case_id="out-of-order",
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
        self.assertTrue(
            automation_timing.begin_checklist_item(
                ledger,
                "P01",
                "P01-C02",
                at="2026-08-07T10:00:30+00:00",
            )
        )
        self.assertEqual(ledger["stages"][0]["checklist"][0]["status"], "pending")
        self.assertEqual(ledger["stages"][0]["checklist"][1]["status"], "in_progress")

    def test_second_active_item_requires_explicit_parallel_reason(self) -> None:
        plan = demo_plan()
        plan["stages"][0]["checklist"].append(
            {
                "id": "P01-C02",
                "text": "Review evidence",
                "required": True,
                "done_when": "Review exists",
            }
        )
        plan["fingerprint"] = automation_timing.canonical_fingerprint(plan)
        ledger = automation_timing.initialize_ledger(
            case_id="parallel-items",
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
        with self.assertRaisesRegex(
            automation_timing.AutomationTimingError,
            "requires another checklist item already in progress",
        ):
            automation_timing.begin_checklist_item(
                ledger,
                "P01",
                "P01-C01",
                parallel_reason="Nothing else is actually running",
                at="2026-08-07T10:00:20+00:00",
            )
        automation_timing.begin_checklist_item(
            ledger,
            "P01",
            "P01-C01",
            at="2026-08-07T10:00:30+00:00",
        )
        with self.assertRaisesRegex(
            automation_timing.AutomationTimingError,
            "already has in-progress checklist items",
        ):
            automation_timing.begin_checklist_item(
                ledger,
                "P01",
                "P01-C02",
                at="2026-08-07T10:00:40+00:00",
            )
        self.assertTrue(
            automation_timing.begin_checklist_item(
                ledger,
                "P01",
                "P01-C02",
                parallel_reason="Independent reviewer is already running",
                at="2026-08-07T10:00:40+00:00",
            )
        )

    def test_completed_stage_rejects_an_optional_item_still_in_progress(self) -> None:
        plan = demo_plan()
        plan["stages"][0]["checklist"].append(
            {
                "id": "P01-C02",
                "text": "Optional comparison",
                "required": False,
                "done_when": "Comparison exists",
            }
        )
        plan["fingerprint"] = automation_timing.canonical_fingerprint(plan)
        ledger = automation_timing.initialize_ledger(
            case_id="optional-active",
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
        automation_timing.begin_checklist_item(
            ledger,
            "P01",
            "P01-C01",
            at="2026-08-07T10:00:10+00:00",
        )
        automation_timing.complete_checklist_item(
            ledger,
            "P01",
            "P01-C01",
            evidence_refs=["evidence.md#research"],
            at="2026-08-07T10:00:20+00:00",
        )
        automation_timing.begin_checklist_item(
            ledger,
            "P01",
            "P01-C02",
            at="2026-08-07T10:00:30+00:00",
        )
        with self.assertRaisesRegex(
            automation_timing.AutomationTimingError,
            "unfinished checklist items: P01-C02",
        ):
            automation_timing.stop_stage(
                ledger,
                "P01",
                status="completed",
                reason=None,
                at="2026-08-07T10:01:00+00:00",
            )

    def test_legacy_completed_item_without_begin_fields_remains_valid(self) -> None:
        ledger = self.ledger()
        automation_timing.start_stage(
            ledger,
            "P01",
            at="2026-08-07T10:00:00+00:00",
        )
        automation_timing.begin_checklist_item(
            ledger,
            "P01",
            "P01-C01",
            at="2026-08-07T10:00:30+00:00",
        )
        automation_timing.complete_checklist_item(
            ledger,
            "P01",
            "P01-C01",
            evidence_refs=["evidence.md#research"],
            at="2026-08-07T10:01:00+00:00",
        )
        item = ledger["stages"][0]["checklist"][0]
        item.pop("started_at")
        item.pop("parallel_reason")
        self.assertEqual(automation_timing.validate_ledger(ledger), [])


if __name__ == "__main__":
    unittest.main()
