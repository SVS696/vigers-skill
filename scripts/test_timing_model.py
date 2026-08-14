#!/usr/bin/env python3
"""Regression tests for project-local human timing forecasts."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import automation_timing
import mode_decision
import timing_model


def decision(
    profile_id: str = "project-alpha",
    *,
    surfaces: list[str] | None = None,
    components: list[str] | None = None,
    change_scope: str = "semantic-local",
) -> dict[str, object]:
    return mode_decision.build_mode_decision(
        task="Describe one behavior change",
        profile_id=profile_id,
        profile_file=".vigers/profile.md",
        profile_source="project",
        project_root="/tmp/project-alpha",
        estimated_blocks=2,
        surfaces=surfaces or ["scenarios", "rules"],
        components=components or ["service-a"],
        owners=["team-a"],
        dependent_parts=True,
        unsafe_single_pass=False,
        project_triggers=[],
        requested_mode=None,
        change_scope=change_scope,
    )


def plan_graph() -> dict[str, object]:
    return {
        "schema": 4,
        "stages": [
            {
                "id": "P01",
                "title": "Research",
                "depends_on": [],
                "checklist": [{"id": "P01-C01", "text": "Collect evidence"}],
            },
            {
                "id": "P02",
                "title": "Synthesis",
                "depends_on": ["P01"],
                "checklist": [{"id": "P02-C01", "text": "Write result"}],
            },
        ],
    }


def measured_automation_plan() -> dict[str, object]:
    payload: dict[str, object] = {
        "policy": "measured",
        "metric": "wall_clock",
        "unit": "seconds",
        "execution_use": "human_information_only",
        "stages": [
            {
                "id": "P01",
                "title": "Research",
                "depends_on": [],
                "estimate": None,
                "external_target_id": None,
                "checklist": [
                    {
                        "id": "P01-C01",
                        "text": "Collect evidence",
                        "required": True,
                        "done_when": None,
                    }
                ],
            },
            {
                "id": "P02",
                "title": "Synthesis",
                "depends_on": ["P01"],
                "estimate": None,
                "external_target_id": None,
                "checklist": [
                    {
                        "id": "P02-C01",
                        "text": "Write result",
                        "required": True,
                        "done_when": None,
                    }
                ],
            },
        ],
    }
    payload["fingerprint"] = automation_timing.canonical_fingerprint(payload)
    return payload


def complete_ledger(case_id: str) -> dict[str, object]:
    ledger = automation_timing.initialize_ledger(
        case_id=case_id,
        automation_plan=measured_automation_plan(),
        planning_case_id=f"plan-{case_id}",
        planning_revision=1,
        passport=None,
        created_at="2026-08-07T10:00:00+00:00",
    )
    automation_timing.start_stage(ledger, "P01", at="2026-08-07T10:00:00+00:00")
    automation_timing.begin_checklist_item(
        ledger, "P01", "P01-C01", at="2026-08-07T10:00:10+00:00"
    )
    automation_timing.complete_checklist_item(
        ledger,
        "P01",
        "P01-C01",
        evidence_refs=["evidence.md"],
        at="2026-08-07T10:01:00+00:00",
    )
    automation_timing.stop_stage(
        ledger,
        "P01",
        status="completed",
        reason=None,
        at="2026-08-07T10:02:00+00:00",
    )
    automation_timing.start_stage(ledger, "P02", at="2026-08-07T10:02:00+00:00")
    automation_timing.pause_stage(
        ledger,
        "P02",
        reason="user_pause",
        at="2026-08-07T10:03:00+00:00",
    )
    automation_timing.resume_stage(ledger, "P02", at="2026-08-07T10:08:00+00:00")
    automation_timing.begin_checklist_item(
        ledger, "P02", "P02-C01", at="2026-08-07T10:08:10+00:00"
    )
    automation_timing.complete_checklist_item(
        ledger,
        "P02",
        "P02-C01",
        evidence_refs=["draft.md"],
        at="2026-08-07T10:09:00+00:00",
    )
    automation_timing.stop_stage(
        ledger,
        "P02",
        status="completed",
        reason=None,
        at="2026-08-07T10:10:00+00:00",
    )
    automation_timing.record_milestone(
        ledger,
        kind="publication",
        evidence_ref="redmine:read-back:1",
        at="2026-08-07T10:10:00+00:00",
    )
    automation_timing.reopen_stage(
        ledger,
        "P02",
        evidence_ref="user:post-publication-edits",
        at="2026-08-07T10:12:00+00:00",
    )
    automation_timing.stop_stage(
        ledger,
        "P02",
        status="completed",
        reason=None,
        at="2026-08-07T10:14:00+00:00",
    )
    automation_timing.record_milestone(
        ledger,
        kind="publication",
        evidence_ref="redmine:read-back:2",
        at="2026-08-07T10:14:00+00:00",
    )
    automation_timing.record_milestone(
        ledger,
        kind="development_handoff",
        evidence_ref="user:handoff-confirmed",
        at="2026-08-07T10:16:00+00:00",
    )
    return ledger


def activity_reconciliation(
    *,
    case_id: str,
    project_key: str,
    active_seconds: int = 300,
    elapsed_seconds: int = 960,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema": 1,
        "work_item": {"id": case_id, "project_key": project_key, "kind": "specification"},
        "window": {
            "started_at": "2026-08-07T10:00:00+00:00",
            "ended_at": "2026-08-07T10:16:00+00:00",
            "terminal": True,
        },
        "quality": "reconciled_measured",
        "coverage": {"status": "complete"},
        "training_eligible": True,
        "warnings": [],
        "metric_results": [
            {
                "provider": "activity-time",
                "schema": 1,
                "values": {
                    "active_observed_seconds": 240,
                    "active_seconds": active_seconds,
                    "elapsed_seconds": elapsed_seconds,
                },
            }
        ],
    }
    payload["fingerprint"] = timing_model.canonical_fingerprint(payload)
    return payload


class TimingModelTests(unittest.TestCase):
    def test_prediction_requires_preliminary_plan(self) -> None:
        with self.assertRaisesRegex(timing_model.TimingModelError, "preliminary plan"):
            timing_model.build_features(decision(), {"stages": []})

    def test_typed_surfaces_and_change_scope_change_similarity_fingerprint(self) -> None:
        base = timing_model.build_features(
            decision(surfaces=["data", "interfaces", "qualities", "states"]),
            plan_graph(),
        )
        different_surface = timing_model.build_features(
            decision(surfaces=["data", "interfaces", "qualities", "scenarios"]),
            plan_graph(),
        )
        different_scope = timing_model.build_features(
            decision(
                surfaces=["data", "interfaces", "qualities", "states"],
                change_scope="semantic-crosscutting",
            ),
            plan_graph(),
        )
        self.assertEqual(base["surface_count"], different_surface["surface_count"])
        self.assertNotEqual(
            timing_model.canonical_fingerprint(base),
            timing_model.canonical_fingerprint(different_surface),
        )
        self.assertGreater(timing_model.feature_distance(base, different_surface), 0)
        self.assertNotEqual(
            timing_model.canonical_fingerprint(base),
            timing_model.canonical_fingerprint(different_scope),
        )
        self.assertGreater(timing_model.feature_distance(base, different_scope), 0)

    def test_typed_neighbor_ranks_before_same_count_different_type(self) -> None:
        query = timing_model.build_features(
            decision(surfaces=["data", "interfaces", "states"]), plan_graph()
        )
        exact = dict(query)
        different = timing_model.build_features(
            decision(surfaces=["data", "interfaces", "errors"]), plan_graph()
        )
        model = timing_model.empty_model("project-alpha", "/tmp/project-alpha")
        for case_id, features, seconds in (
            ("exact", exact, 100),
            ("different", different, 900),
        ):
            calibration = {"schema": 1, "case_id": case_id}
            calibration["fingerprint"] = timing_model.canonical_fingerprint(calibration)
            model["samples"].append(
                {
                    "case_id": case_id,
                    "features": features,
                    "active_seconds": seconds,
                    "elapsed_seconds": seconds,
                    "quality": "measured",
                    "calibration": calibration,
                }
            )
        model["sample_count"] = 2
        result = timing_model.predict(model, query)
        self.assertEqual(result["matching_case_ids"][0], "exact")
        self.assertEqual(result["matching_neighbors"][0]["distance"], 0)

    def test_history_is_bound_to_exact_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root_a = str(Path(temp) / "project-a")
            root_b = str(Path(temp) / "project-b")
            model = timing_model.empty_model("project-alpha", root_a)
            with self.assertRaisesRegex(timing_model.TimingModelError, "another project root"):
                timing_model.validate_model(
                    model,
                    profile_id="project-alpha",
                    project_root=root_b,
                )

    def test_schema_one_model_loads_without_rewriting_old_samples(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project_root = str(Path(temp) / "project-alpha")
            path = Path(temp) / "timing-model.json"
            model = timing_model.empty_model("project-alpha", project_root)
            model["feature_schema"] = 1
            path.write_text(json.dumps(model), encoding="utf-8")
            loaded = timing_model.load_model(
                path,
                profile_id="project-alpha",
                project_root=project_root,
            )
            self.assertEqual(loaded["feature_schema"], 2)
            self.assertEqual(loaded["samples"], [])

    def test_completed_measurement_updates_idempotently_and_predicts(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project_root = str(Path(temp) / "project-alpha")
            ledger_path = Path(temp) / "automation-timing.json"
            automation_timing.atomic_json(ledger_path, complete_ledger("case-1"))
            features = timing_model.build_features(decision(), plan_graph())
            model = timing_model.empty_model("project-alpha", project_root)
            initial_forecast = timing_model.predict(model, features)
            sample = timing_model.measured_sample(
                ledger_path=ledger_path,
                features=features,
                forecast=initial_forecast,
            )
            self.assertTrue(timing_model.update_model(model, sample))
            self.assertFalse(timing_model.update_model(model, sample))
            result = timing_model.predict(model, features)
            self.assertEqual(result["status"], "forecast")
            self.assertEqual(result["sample_size"], 1)
            self.assertEqual(result["confidence"], "low")
            self.assertEqual(result["active"]["likely_seconds"], 420)
            self.assertEqual(result["elapsed"]["likely_seconds"], 960)
            self.assertEqual(result["purpose"], "human_information_only")
            self.assertIn("после предварительного анализа", result["human_note"])
            self.assertEqual(
                result["measurement_scope"]["ends_at"],
                "first_development_handoff",
            )
            self.assertEqual(sample["calibration"]["forecast_status"], "insufficient_data")
            self.assertEqual(sample["calibration"]["publication_count"], 2)
            self.assertEqual(sample["calibration"]["elapsed"]["actual_seconds"], 960)

    def test_run_log_recovery_is_partial_and_not_training_eligible(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "agent-ledger.json"
            path.write_text(
                json.dumps(
                    {
                        "schema": 1,
                        "case_id": "legacy-case",
                        "runs": [
                            {
                                "at": "2026-08-07T10:10:00+00:00",
                                "duration_seconds": 120,
                            },
                            {
                                "at": "2026-08-07T10:20:00+00:00",
                                "duration_seconds": 180,
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            candidate = timing_model.recover_candidate(path)
            self.assertEqual(candidate["active_lower_bound_seconds"], 300)
            self.assertFalse(candidate["training_eligible"])
            self.assertEqual(candidate["coverage"], "partial")

    def test_complete_activity_reconciliation_overrides_explicit_active_time(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project_root = str(Path(temp) / "project-alpha")
            ledger_path = Path(temp) / "automation-timing.json"
            automation_timing.atomic_json(ledger_path, complete_ledger("case-1"))
            features = timing_model.build_features(decision(), plan_graph())
            forecast = timing_model.predict(
                timing_model.empty_model("project-alpha", project_root), features
            )
            reconciliation = activity_reconciliation(
                case_id="case-1",
                project_key=forecast["project_key"],
            )
            sample = timing_model.measured_sample(
                ledger_path=ledger_path,
                features=features,
                forecast=forecast,
                activity_reconciliation=reconciliation,
            )
            self.assertEqual(sample["active_seconds"], 300)
            self.assertEqual(sample["elapsed_seconds"], 960)
            self.assertEqual(
                sample["calibration"]["measurement"]["source"],
                "work_metrics_activity_reconciliation",
            )
            self.assertEqual(
                sample["calibration"]["measurement"][
                    "activity_reconciliation_fingerprint"
                ],
                reconciliation["fingerprint"],
            )

    def test_activity_reconciliation_is_bound_to_case_project_and_complete_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project_root = str(Path(temp) / "project-alpha")
            ledger_path = Path(temp) / "automation-timing.json"
            automation_timing.atomic_json(ledger_path, complete_ledger("case-1"))
            features = timing_model.build_features(decision(), plan_graph())
            forecast = timing_model.predict(
                timing_model.empty_model("project-alpha", project_root), features
            )
            candidates = [
                activity_reconciliation(
                    case_id="another-case", project_key=forecast["project_key"]
                ),
                activity_reconciliation(case_id="case-1", project_key="another-project"),
                activity_reconciliation(
                    case_id="case-1", project_key=forecast["project_key"]
                ),
            ]
            candidates[2]["coverage"] = {"status": "partial"}
            candidates[2]["fingerprint"] = timing_model.canonical_fingerprint(candidates[2])
            patterns = ("another case", "another project", "not complete")
            for candidate, pattern in zip(candidates, patterns, strict=True):
                with self.subTest(pattern=pattern), self.assertRaisesRegex(
                    timing_model.TimingModelError, pattern
                ):
                    timing_model.measured_sample(
                        ledger_path=ledger_path,
                        features=features,
                        forecast=forecast,
                        activity_reconciliation=candidate,
                    )

    def test_legacy_forecast_still_resolves_its_schema_one_features(self) -> None:
        legacy_features = timing_model.build_features(
            decision(), plan_graph(), schema_version=1
        )
        legacy_forecast = {
            "feature_fingerprint": timing_model.canonical_fingerprint(legacy_features)
        }
        resolved = timing_model.resolve_forecast_features(
            decision(), plan_graph(), legacy_forecast
        )
        self.assertEqual(resolved["schema"], 1)

    def test_post_handoff_followup_cannot_train_initial_model(self) -> None:
        reconciliation = activity_reconciliation(
            case_id="case-1",
            project_key="project-key",
        )
        reconciliation["work_item"]["cycle_kind"] = "post-handoff-followup"
        reconciliation["work_item"]["parent_id"] = "original-case"
        reconciliation["fingerprint"] = timing_model.canonical_fingerprint(reconciliation)
        with self.assertRaisesRegex(timing_model.TimingModelError, "follow-up"):
            timing_model.validate_activity_reconciliation(
                reconciliation,
                case_id="case-1",
                project_key="project-key",
                development_handoff_at="2026-08-07T10:16:00+00:00",
            )

    def test_activity_reconciliation_must_end_at_handoff(self) -> None:
        reconciliation = activity_reconciliation(
            case_id="case-1",
            project_key="project-key",
        )
        reconciliation["window"]["ended_at"] = "2026-08-07T10:17:00+00:00"
        reconciliation["fingerprint"] = timing_model.canonical_fingerprint(reconciliation)
        with self.assertRaisesRegex(timing_model.TimingModelError, "first development handoff"):
            timing_model.validate_activity_reconciliation(
                reconciliation,
                case_id="case-1",
                project_key="project-key",
                development_handoff_at="2026-08-07T10:16:00+00:00",
            )


if __name__ == "__main__":
    unittest.main()
