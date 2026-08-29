#!/usr/bin/env python3
"""Regression tests for project-local shadow policy learning."""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import case_pipeline
import mode_decision
import policy_learning


class PolicyLearningTests(unittest.TestCase):
    def decision(self, project_root: str, *, assurance: str = "standard") -> dict[str, object]:
        return mode_decision.build_mode_decision(
            task="Prepare one bounded specification",
            profile_id="project-alpha",
            profile_file=".vigers/profile.md",
            profile_source="project",
            project_root=project_root,
            estimated_blocks=1,
            surfaces=["scenarios"],
            components=["service-a"],
            owners=["team-a"],
            dependent_parts=False,
            unsafe_single_pass=False,
            project_triggers=[],
            requested_mode=None,
            requested_assurance=assurance,
        )

    def feedback(self, case_id: str, project_root: str) -> dict[str, object]:
        evidence_path = (
            Path(project_root) / ".vigers" / "telemetry" / "test-receipts" / f"{case_id}.json"
        )
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_text('{"status":"closed"}\n', encoding="utf-8")
        return policy_learning.build_feedback(
            case_id=case_id,
            coverage="complete",
            window_closed=True,
            human_rework_count=0,
            developer_clarification_count=0,
            blocker_defects=0,
            major_defects=0,
            minor_defects=0,
            evidence_refs=[policy_learning.bind_evidence_file(evidence_path)],
        )

    def process_audit_files(self, case_id: str, project_root: str) -> tuple[Path, Path]:
        root = Path(project_root) / ".vigers" / "telemetry" / "test-process-audits"
        root.mkdir(parents=True, exist_ok=True)
        episode_path = root / f"{case_id}-episode.json"
        verdict_path = root / f"{case_id}-verdict.json"
        evidence_path = root / f"{case_id}-evidence.json"
        evidence_path.write_text('{"status":"verified"}\n', encoding="utf-8")
        episode = {
            "schema": 1,
            "episode_id": f"audit-{case_id}",
            "work_item_id": case_id,
            "parent_episode_id": None,
            "outcome": "completed",
            "origin": "prospective-clean",
            "project_root": str(Path(project_root).resolve()),
            "project_key": policy_learning.process_audit_root_key(project_root),
            "workflow": "vigers-policy-learning",
            "author_run_id": f"author-{case_id}",
            "skill_chain": [{"name": "vigers", "version": "test-revision"}],
            "signals": [],
            "required_depth": "routine",
            "window": {"started_at": None, "ended_at": None},
            "manual_stop": None,
            "evidence_refs": [policy_learning.bind_evidence_file(evidence_path)],
            "recorded_at": "2026-08-29T10:00:00+00:00",
        }
        episode["fingerprint"] = policy_learning.canonical_fingerprint(episode)
        verdict = {
            "schema": 2,
            "episode_id": episode["episode_id"],
            "episode_fingerprint": episode["fingerprint"],
            "evaluator": {
                "run_id": f"review-{case_id}",
                "model": "independent-test-model",
                "independent": True,
                "context_policy": "evidence-only",
                "review_depth": "routine",
            },
            "classification": "KEEP",
            "severity": "none",
            "summary": "The completed process is proportionate to the evidence.",
            "process_pattern_id": None,
            "findings": [],
            "actions": [
                {
                    "kind": "no_change",
                    "target_skill": None,
                    "description": "Retain the current process.",
                }
            ],
            "manual_stop_assessment": "not_applicable",
            "no_auto_resume": True,
            "auto_apply": False,
            "recorded_at": "2026-08-29T10:01:00+00:00",
        }
        verdict["fingerprint"] = policy_learning.canonical_fingerprint(verdict)
        episode_path.write_text(json.dumps(episode), encoding="utf-8")
        verdict_path.write_text(json.dumps(verdict), encoding="utf-8")
        return episode_path, verdict_path

    def process_audit_summary(self, case_id: str, project_root: str) -> dict[str, object]:
        episode_path, verdict_path = self.process_audit_files(case_id, project_root)
        return policy_learning.process_audit_summary(
            case_id=case_id,
            project_root=project_root,
            origin="prospective-clean",
            episode_path=episode_path,
            verdict_path=verdict_path,
        )

    def episode(
        self,
        case_id: str,
        project_root: str,
        *,
        assurance: str = "standard",
    ) -> dict[str, object]:
        features = policy_learning.build_features(
            self.decision(project_root, assurance=assurance),
            route_id="core",
            intent="create",
        )
        feedback = policy_learning.feedback_summary(self.feedback(case_id, project_root))
        process_audit = self.process_audit_summary(case_id, project_root)
        identity = {
            "role": "spec-reviewer",
            "role_mode": "global",
            "lenses": ["global-logic@1"],
        }
        bundle = {
            **identity,
            "bundle_fingerprint": policy_learning.canonical_fingerprint(identity),
            "model": "test-model",
            "duration_seconds": 30,
            "input_tokens": 100,
            "output_tokens": 20,
            "reported": {"blocker": 0, "major": 0, "minor": 0},
            "reported_total": 0,
            "verification_complete": True,
            "dispositions": None,
            "status": "completed",
        }
        payload: dict[str, object] = {
            "case_id": case_id,
            "origin": "prospective-clean",
            "case_subject_fingerprint": policy_learning.canonical_fingerprint(
                {"case_id": case_id}
            ),
            "features": features,
            "strategy": {
                "review_strategy": case_pipeline.REVIEW_STRATEGIES[assurance],
                "run_bundles": [bundle],
                "remediations": {"targeted": 0, "full-block": 0},
            },
            "efficiency": {
                "agent_run_count": 1,
                "review_run_count": 1,
                "duration_seconds": 30,
                "retries": 0,
                "input_tokens": 100,
                "output_tokens": 20,
                "tool_calls": 0,
                "poll_calls": 0,
            },
            "quality": {
                "final_validation": "pass",
                "terminal_runs_clean": True,
                "verification_complete": True,
                "reported_findings": {"blocker": 0, "major": 0, "minor": 0},
                "dispositions": {
                    "accepted": 0,
                    "rejected": 0,
                    "duplicate": 0,
                    "verified": 0,
                },
                "external_feedback": feedback,
                "process_audit": process_audit,
            },
            "training_eligible": True,
            "promotion_evidence_eligible": True,
            "recorded_at": "2026-08-29T10:00:00+00:00",
        }
        payload["fingerprint"] = policy_learning.canonical_fingerprint(
            payload,
            ignored={"recorded_at"},
        )
        return payload

    def test_complete_feedback_requires_evidence(self) -> None:
        with self.assertRaisesRegex(policy_learning.PolicyLearningError, "evidence_refs"):
            policy_learning.build_feedback(
                case_id="case-1",
                coverage="complete",
                window_closed=True,
                human_rework_count=0,
                developer_clarification_count=0,
                blocker_defects=0,
                major_defects=0,
                minor_defects=0,
                evidence_refs=[],
            )

    def test_policy_model_is_project_local_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project_root = str(Path(temp) / "project-a")
            other_root = str(Path(temp) / "project-b")
            model = policy_learning.empty_model("project-alpha", project_root)
            sample = self.episode("case-1", project_root)
            self.assertTrue(policy_learning.update_model(model, sample))
            self.assertFalse(policy_learning.update_model(model, sample))
            self.assertEqual(
                policy_learning.validate_model(
                    model,
                    profile_id="project-alpha",
                    project_root=project_root,
                ),
                [],
            )
            self.assertIn(
                "another project root",
                " ".join(
                    policy_learning.validate_model(
                        model,
                        profile_id="project-alpha",
                        project_root=other_root,
                    )
                ),
            )
            with self.assertRaisesRegex(
                policy_learning.PolicyLearningError,
                "another policy project root",
            ):
                policy_learning.build_shadow_candidate(
                    model,
                    self.decision(other_root),
                    route_id="core",
                    intent="create",
                )

    def test_build_episode_requires_final_green_and_binds_feedback(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project_root = str(Path(temp) / "project")
            case_root = Path(temp) / "case"
            case_root.mkdir()
            decision = self.decision(project_root)
            (case_root / "mode-decision.json").write_text(
                json.dumps(decision, ensure_ascii=False),
                encoding="utf-8",
            )
            manifest = {
                "schema": case_pipeline.SCHEMA_VERSION,
                "case_id": "case-1",
                "mode": "compact",
                "assurance_level": "standard",
                "profile_id": "project-alpha",
                "project_root": project_root,
                "route_id": "core",
                "intent": "create",
                "mode_decision": {
                    "path": "mode-decision.json",
                    "fingerprint": decision["fingerprint"],
                },
                "kernel": {"sha256": "a" * 64},
                "gates": {},
                "artifacts": {"agent_ledger": "agent-ledger.json"},
            }
            (case_root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            (case_root / "ledger.json").write_text(
                json.dumps({"schema": case_pipeline.SCHEMA_VERSION, "blocks": []}),
                encoding="utf-8",
            )
            agent_ledger = {
                "schema": case_pipeline.AGENT_LEDGER_SCHEMA,
                "case_id": "case-1",
                "runs": [
                    {
                        "run_id": "AR-0001",
                        "at": "2026-08-29T10:00:00+00:00",
                        "role": "spec-reviewer",
                        "role_mode": "final",
                        "assurance_level": "standard",
                        "model": "test-model",
                        "subject_sha256": "b" * 64,
                        "input_bytes": 100,
                        "input_tokens": 20,
                        "output_tokens": 5,
                        "duration_seconds": 10,
                        "retries": 0,
                        "supervisor_contract": case_pipeline.AGENT_SUPERVISOR_CONTRACT,
                        "tool_calls": 0,
                        "poll_calls": 0,
                        "wait_seconds": 0,
                        "findings": {"blocker": 0, "major": 0, "minor": 0},
                        "cache_status": "miss",
                        "status": "completed",
                        "degraded_reasons": [],
                        "lenses": ["global-logic@1"],
                    }
                ],
            }
            (case_root / "agent-ledger.json").write_text(
                json.dumps(agent_ledger),
                encoding="utf-8",
            )
            feedback_path = Path(temp) / "feedback.json"
            feedback_path.write_text(
                json.dumps(self.feedback("case-1", project_root)),
                encoding="utf-8",
            )
            process_episode_path, process_verdict_path = self.process_audit_files(
                "case-1",
                project_root,
            )
            with mock.patch.object(case_pipeline, "validate_case", return_value=[]):
                with self.assertRaisesRegex(
                    policy_learning.PolicyLearningError,
                    "require an independent process audit",
                ):
                    policy_learning.build_episode(
                        case_root,
                        profile_id="project-alpha",
                        project_root=project_root,
                        origin="prospective-clean",
                        feedback_path=feedback_path,
                    )
                episode = policy_learning.build_episode(
                    case_root,
                    profile_id="project-alpha",
                    project_root=project_root,
                    origin="prospective-clean",
                    feedback_path=feedback_path,
                    process_episode_path=process_episode_path,
                    process_verdict_path=process_verdict_path,
                )
            self.assertTrue(episode["training_eligible"])
            self.assertTrue(episode["promotion_evidence_eligible"])

            with mock.patch.object(
                case_pipeline,
                "validate_case",
                return_value=["Gate global_review must pass"],
            ):
                with self.assertRaisesRegex(policy_learning.PolicyLearningError, "final-green"):
                    policy_learning.build_episode(
                        case_root,
                        profile_id="project-alpha",
                        project_root=project_root,
                        origin="historical-biased",
                    )

    def test_historical_biased_sample_cannot_train_policy(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project_root = str(Path(temp) / "project")
            sample = self.episode("historical-1", project_root)
            sample["origin"] = "historical-biased"
            sample["training_eligible"] = True
            sample["fingerprint"] = policy_learning.canonical_fingerprint(
                sample,
                ignored={"recorded_at"},
            )
            model = policy_learning.empty_model("project-alpha", project_root)
            policy_learning.update_model(model, sample)
            errors = policy_learning.validate_model(
                model,
                profile_id="project-alpha",
                project_root=project_root,
            )
            self.assertIn("historical-biased sample cannot train policy", " ".join(errors))

    def test_process_audit_rejects_incomplete_public_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project_root = str(Path(temp) / "project")
            episode_path, verdict_path = self.process_audit_files(
                "case-public-contract", project_root
            )
            original_episode = policy_learning.read_json(episode_path)
            original_verdict = policy_learning.read_json(verdict_path)
            for field in ("project_key", "workflow", "window"):
                with self.subTest(artifact="episode", field=field):
                    episode = copy.deepcopy(original_episode)
                    episode.pop(field)
                    episode["fingerprint"] = policy_learning.canonical_fingerprint(episode)
                    verdict = copy.deepcopy(original_verdict)
                    verdict["episode_fingerprint"] = episode["fingerprint"]
                    verdict["fingerprint"] = policy_learning.canonical_fingerprint(verdict)
                    episode_path.write_text(json.dumps(episode), encoding="utf-8")
                    verdict_path.write_text(json.dumps(verdict), encoding="utf-8")
                    with self.assertRaisesRegex(
                        policy_learning.PolicyLearningError,
                        field,
                    ):
                        policy_learning.process_audit_summary(
                            case_id="case-public-contract",
                            project_root=project_root,
                            origin="prospective-clean",
                            episode_path=episode_path,
                            verdict_path=verdict_path,
                        )
            episode_path.write_text(json.dumps(original_episode), encoding="utf-8")
            for field in (
                "severity",
                "summary",
                "process_pattern_id",
                "findings",
                "actions",
                "manual_stop_assessment",
            ):
                with self.subTest(artifact="verdict", field=field):
                    verdict = copy.deepcopy(original_verdict)
                    verdict.pop(field)
                    verdict["fingerprint"] = policy_learning.canonical_fingerprint(verdict)
                    verdict_path.write_text(json.dumps(verdict), encoding="utf-8")
                    with self.assertRaisesRegex(
                        policy_learning.PolicyLearningError,
                        field,
                    ):
                        policy_learning.process_audit_summary(
                            case_id="case-public-contract",
                            project_root=project_root,
                            origin="prospective-clean",
                            episode_path=episode_path,
                            verdict_path=verdict_path,
                        )

    def test_process_audit_origin_must_match_policy_sample(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project_root = str(Path(temp) / "project")
            episode_path, verdict_path = self.process_audit_files("case-origin", project_root)
            episode = policy_learning.read_json(episode_path)
            episode["origin"] = "historical-biased"
            episode["fingerprint"] = policy_learning.canonical_fingerprint(episode)
            episode_path.write_text(json.dumps(episode), encoding="utf-8")
            verdict = policy_learning.read_json(verdict_path)
            verdict["episode_fingerprint"] = episode["fingerprint"]
            verdict["fingerprint"] = policy_learning.canonical_fingerprint(verdict)
            verdict_path.write_text(json.dumps(verdict), encoding="utf-8")
            with self.assertRaisesRegex(
                policy_learning.PolicyLearningError,
                "origin does not match",
            ):
                policy_learning.process_audit_summary(
                    case_id="case-origin",
                    project_root=project_root,
                    origin="prospective-clean",
                    episode_path=episode_path,
                    verdict_path=verdict_path,
                )

    def test_process_audit_requires_current_evidence_and_schema_two(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project_root = str(Path(temp) / "project")
            episode_path, verdict_path = self.process_audit_files(
                "case-current-audit", project_root
            )
            episode = policy_learning.read_json(episode_path)
            evidence_path = Path(episode["evidence_refs"][0]["ref"])
            evidence_path.write_text('{"status":"changed"}\n', encoding="utf-8")
            with self.assertRaisesRegex(
                policy_learning.PolicyLearningError,
                "evidence changed",
            ):
                policy_learning.process_audit_summary(
                    case_id="case-current-audit",
                    project_root=project_root,
                    origin="prospective-clean",
                    episode_path=episode_path,
                    verdict_path=verdict_path,
                )
            evidence_path.write_text('{"status":"verified"}\n', encoding="utf-8")
            verdict = policy_learning.read_json(verdict_path)
            verdict["schema"] = 1
            verdict["fingerprint"] = policy_learning.canonical_fingerprint(verdict)
            verdict_path.write_text(json.dumps(verdict), encoding="utf-8")
            with self.assertRaisesRegex(
                policy_learning.PolicyLearningError,
                "unsupported schema",
            ):
                policy_learning.process_audit_summary(
                    case_id="case-current-audit",
                    project_root=project_root,
                    origin="prospective-clean",
                    episode_path=episode_path,
                    verdict_path=verdict_path,
                )
            verdict["schema"] = 2
            verdict["evaluator"]["review_depth"] = "deep"
            verdict["fingerprint"] = policy_learning.canonical_fingerprint(verdict)
            verdict_path.write_text(json.dumps(verdict), encoding="utf-8")
            with self.assertRaisesRegex(
                policy_learning.PolicyLearningError,
                "review_depth does not match",
            ):
                policy_learning.process_audit_summary(
                    case_id="case-current-audit",
                    project_root=project_root,
                    origin="prospective-clean",
                    episode_path=episode_path,
                    verdict_path=verdict_path,
                )

            episode = policy_learning.read_json(episode_path)
            episode["signals"] = ["quality_regression"]
            episode["required_depth"] = "routine"
            episode["fingerprint"] = policy_learning.canonical_fingerprint(episode)
            episode_path.write_text(json.dumps(episode), encoding="utf-8")
            verdict["evaluator"]["review_depth"] = "routine"
            verdict["episode_fingerprint"] = episode["fingerprint"]
            verdict["fingerprint"] = policy_learning.canonical_fingerprint(verdict)
            verdict_path.write_text(json.dumps(verdict), encoding="utf-8")
            with self.assertRaisesRegex(
                policy_learning.PolicyLearningError,
                "required_depth is weaker",
            ):
                policy_learning.process_audit_summary(
                    case_id="case-current-audit",
                    project_root=project_root,
                    origin="prospective-clean",
                    episode_path=episode_path,
                    verdict_path=verdict_path,
                )

    def test_stopped_process_audit_cannot_promote_policy(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project_root = str(Path(temp) / "project")
            episode_path, verdict_path = self.process_audit_files(
                "case-stopped-audit", project_root
            )
            episode = policy_learning.read_json(episode_path)
            episode["outcome"] = "user_stopped"
            episode["signals"] = ["manual_stop"]
            episode["required_depth"] = "deep"
            episode["manual_stop"] = {
                "authority": "user",
                "at": "2026-08-29T10:00:30+00:00",
                "reason": "runaway review loop",
                "reason_status": "provided",
                "resume_authority": "user_only",
            }
            episode["fingerprint"] = policy_learning.canonical_fingerprint(episode)
            episode_path.write_text(json.dumps(episode), encoding="utf-8")
            verdict = policy_learning.read_json(verdict_path)
            verdict["evaluator"]["review_depth"] = "deep"
            verdict["classification"] = "MANUAL_STOP_VALIDATED"
            verdict["severity"] = "minor"
            verdict["summary"] = "The user correctly stopped a runaway review loop."
            verdict["findings"] = [
                {
                    "description": "The evidence confirms a runaway review loop.",
                    "target_skill": "vigers",
                    "evidence_sha256": [episode["evidence_refs"][0]["sha256"]],
                }
            ]
            verdict["actions"] = [
                {
                    "kind": "investigate",
                    "target_skill": "vigers",
                    "description": "Investigate the stopped review loop.",
                }
            ]
            verdict["manual_stop_assessment"] = "validated"
            verdict["episode_fingerprint"] = episode["fingerprint"]
            verdict["fingerprint"] = policy_learning.canonical_fingerprint(verdict)
            verdict_path.write_text(json.dumps(verdict), encoding="utf-8")
            summary = policy_learning.process_audit_summary(
                case_id="case-stopped-audit",
                project_root=project_root,
                origin="prospective-clean",
                episode_path=episode_path,
                verdict_path=verdict_path,
            )
            self.assertEqual("user_stopped", summary["outcome"])
            self.assertFalse(summary["promotion_evidence_eligible"])
            verdict["actions"] = [
                {
                    "kind": "propose_policy_change",
                    "target_skill": "vigers",
                    "description": "Propose a bounded review-loop policy change.",
                }
            ]
            verdict["process_pattern_id"] = None
            verdict["fingerprint"] = policy_learning.canonical_fingerprint(verdict)
            verdict_path.write_text(json.dumps(verdict), encoding="utf-8")
            with self.assertRaisesRegex(
                policy_learning.PolicyLearningError,
                "requires process_pattern_id",
            ):
                policy_learning.process_audit_summary(
                    case_id="case-stopped-audit",
                    project_root=project_root,
                    origin="prospective-clean",
                    episode_path=episode_path,
                    verdict_path=verdict_path,
                )

    def test_targeted_process_recheck_is_valid_but_cannot_promote_policy(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project_root = str(Path(temp) / "project")
            source_episode_path, source_verdict_path = self.process_audit_files(
                "case-targeted-audit", project_root
            )
            source_episode = policy_learning.read_json(source_episode_path)
            source_verdict = policy_learning.read_json(source_verdict_path)
            source_finding = {
                "description": "A bounded execution defect requires remediation.",
                "target_skill": "vigers",
                "evidence_sha256": [source_episode["evidence_refs"][0]["sha256"]],
            }
            source_verdict["classification"] = "EXECUTION_DEFECT"
            source_verdict["severity"] = "major"
            source_verdict["findings"] = [source_finding]
            source_verdict["actions"] = [
                {
                    "kind": "repair_result",
                    "target_skill": "vigers",
                    "description": "Repair only the selected execution defect.",
                }
            ]
            source_verdict["fingerprint"] = policy_learning.canonical_fingerprint(
                source_verdict
            )
            source_verdict_path.write_text(json.dumps(source_verdict), encoding="utf-8")

            current_evidence = source_episode_path.parent / "targeted-current.json"
            current_evidence.write_text('{"status":"closed"}\n', encoding="utf-8")
            target_episode_path = source_episode_path.parent / "targeted-episode.json"
            target_verdict_path = source_episode_path.parent / "targeted-verdict.json"
            target_episode = copy.deepcopy(source_episode)
            target_episode.update(
                {
                    "episode_id": "audit-case-targeted-audit-remediation",
                    "parent_episode_id": source_episode["episode_id"],
                    "author_run_id": "targeted-remediation-author",
                    "skill_chain": [
                        {"name": "vigers", "version": "targeted-remediation"}
                    ],
                    "evidence_refs": [
                        policy_learning.bind_evidence_file(source_episode_path),
                        policy_learning.bind_evidence_file(source_verdict_path),
                        policy_learning.bind_evidence_file(current_evidence),
                    ],
                    "recorded_at": "2026-08-29T10:02:00+00:00",
                }
            )
            selected_fingerprint = policy_learning.canonical_fingerprint(source_finding)
            target_episode["review_scope"] = {
                "mode": "targeted_remediation",
                "source_episode_ref": str(source_episode_path.resolve()),
                "source_episode_sha256": policy_learning.sha256_file(source_episode_path),
                "source_episode_id": source_episode["episode_id"],
                "source_verdict_ref": str(source_verdict_path.resolve()),
                "source_verdict_sha256": policy_learning.sha256_file(source_verdict_path),
                "source_verdict_fingerprint": source_verdict["fingerprint"],
                "selected_findings": [
                    {
                        "index": 1,
                        "fingerprint": selected_fingerprint,
                        "target_skill": "vigers",
                    }
                ],
                "new_findings_policy": "backlog_only",
                "max_rechecks": 1,
                "automatic_followup": False,
            }
            target_episode["fingerprint"] = policy_learning.canonical_fingerprint(
                target_episode
            )
            target_episode_path.write_text(json.dumps(target_episode), encoding="utf-8")
            target_verdict = copy.deepcopy(source_verdict)
            target_verdict.update(
                {
                    "episode_id": target_episode["episode_id"],
                    "episode_fingerprint": target_episode["fingerprint"],
                    "evaluator": {
                        "run_id": "targeted-independent-reviewer",
                        "model": "independent-test-model",
                        "independent": True,
                        "context_policy": "evidence-only",
                        "review_depth": "routine",
                    },
                    "classification": "KEEP",
                    "severity": "none",
                    "summary": "The selected remediation finding is closed.",
                    "findings": [],
                    "actions": [
                        {
                            "kind": "no_change",
                            "target_skill": None,
                            "description": "Stop after the bounded recheck.",
                        }
                    ],
                    "remediation_results": [
                        {
                            "finding_fingerprint": selected_fingerprint,
                            "status": "closed",
                            "summary": "Current evidence closes the selected finding.",
                            "evidence_sha256": [
                                policy_learning.sha256_file(current_evidence)
                            ],
                        }
                    ],
                    "scope_expansion": False,
                    "automatic_followup": False,
                    "recorded_at": "2026-08-29T10:03:00+00:00",
                }
            )
            target_verdict["fingerprint"] = policy_learning.canonical_fingerprint(
                target_verdict
            )
            target_verdict_path.write_text(json.dumps(target_verdict), encoding="utf-8")
            summary = policy_learning.process_audit_summary(
                case_id="case-targeted-audit",
                project_root=project_root,
                origin="prospective-clean",
                episode_path=target_episode_path,
                verdict_path=target_verdict_path,
            )
            self.assertEqual("KEEP", summary["classification"])
            self.assertFalse(summary["promotion_evidence_eligible"])

            target_verdict["findings"] = [source_finding]
            target_verdict["fingerprint"] = policy_learning.canonical_fingerprint(
                target_verdict
            )
            target_verdict_path.write_text(json.dumps(target_verdict), encoding="utf-8")
            with self.assertRaisesRegex(
                policy_learning.PolicyLearningError, "cannot expand findings"
            ):
                policy_learning.process_audit_summary(
                    case_id="case-targeted-audit",
                    project_root=project_root,
                    origin="prospective-clean",
                    episode_path=target_episode_path,
                    verdict_path=target_verdict_path,
                )

    def test_shadow_candidate_requires_three_clean_external_outcomes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project_root = str(Path(temp) / "project")
            model = policy_learning.empty_model("project-alpha", project_root)
            policy_learning.update_model(model, self.episode("case-1", project_root))
            result = policy_learning.build_shadow_candidate(
                model,
                self.decision(project_root),
                route_id="core",
                intent="create",
            )
            self.assertEqual(result["status"], "insufficient_data")
            self.assertFalse(result["enforcement"]["auto_apply"])

            policy_learning.update_model(model, self.episode("case-2", project_root))
            policy_learning.update_model(model, self.episode("case-3", project_root))
            result = policy_learning.build_shadow_candidate(
                model,
                self.decision(project_root),
                route_id="core",
                intent="create",
            )
            self.assertEqual(result["status"], "shadow_candidates")
            self.assertEqual(
                result["candidates"][0]["kind"],
                "extra-review-bundle-ablation-replay",
            )
            self.assertFalse(result["candidates"][0]["promotion_allowed"])

            evidence_path = Path(
                model["samples"][0]["quality"]["external_feedback"]["evidence_refs"][0][
                    "ref"
                ]
            )
            evidence_path.write_text('{"status":"changed"}\n', encoding="utf-8")
            result = policy_learning.build_shadow_candidate(
                model,
                self.decision(project_root),
                route_id="core",
                intent="create",
            )
            self.assertEqual(result["status"], "quality_floor_not_met")
            evidence_path.write_text('{"status":"closed"}\n', encoding="utf-8")

            damaged = copy.deepcopy(self.episode("case-4", project_root))
            damaged["quality"]["external_feedback"]["specification_defects"]["major"] = 1
            damaged["fingerprint"] = policy_learning.canonical_fingerprint(
                damaged,
                ignored={"recorded_at"},
            )
            policy_learning.update_model(model, damaged)
            result = policy_learning.build_shadow_candidate(
                model,
                self.decision(project_root),
                route_id="core",
                intent="create",
            )
            self.assertEqual(result["status"], "quality_floor_not_met")

    def test_high_assurance_keeps_protected_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project_root = str(Path(temp) / "project")
            model = policy_learning.empty_model("project-alpha", project_root)
            for number in range(1, 4):
                policy_learning.update_model(
                    model,
                    self.episode(f"case-{number}", project_root, assurance="high"),
                )
            result = policy_learning.build_shadow_candidate(
                model,
                self.decision(project_root, assurance="high"),
                route_id="core",
                intent="create",
            )
            self.assertEqual(result["status"], "protected_baseline")
            self.assertEqual(result["candidates"], [])

    def test_standard_final_reviewer_is_not_an_ablation_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project_root = str(Path(temp) / "project")
            model = policy_learning.empty_model("project-alpha", project_root)
            for number in range(1, 4):
                episode = self.episode(f"case-{number}", project_root)
                bundle = episode["strategy"]["run_bundles"][0]
                bundle["role_mode"] = "final"
                identity = {
                    "role": bundle["role"],
                    "role_mode": bundle["role_mode"],
                    "lenses": bundle["lenses"],
                }
                bundle["bundle_fingerprint"] = policy_learning.canonical_fingerprint(identity)
                episode["fingerprint"] = policy_learning.canonical_fingerprint(
                    episode,
                    ignored={"recorded_at"},
                )
                policy_learning.update_model(model, episode)
            result = policy_learning.build_shadow_candidate(
                model,
                self.decision(project_root),
                route_id="core",
                intent="create",
            )
            self.assertEqual(result["status"], "baseline_retained")
            self.assertEqual(result["candidates"], [])


if __name__ == "__main__":
    unittest.main()
