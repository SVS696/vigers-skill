#!/usr/bin/env python3
"""Regression tests for the deterministic Vigers context router."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import vigers_context


class RouterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = vigers_context.load_map()

    def first_match(self, text: str) -> str:
        output = io.StringIO()
        with redirect_stdout(output):
            vigers_context.match_routes(self.data, text)
        return output.getvalue().split("\t", 1)[0]

    def test_validation(self) -> None:
        counts = vigers_context.validate()
        self.assertEqual(counts["routes"], 23)
        self.assertEqual(counts["blocks"], 21)
        self.assertEqual(counts["native_ids"], 70)
        self.assertEqual(counts["operational_reference_files"], 3)

    def test_representative_routing(self) -> None:
        cases = {
            "Связать сценарии с требованиями и тестами": "traceability",
            "Описать API и обмен через очередь": "integration",
            "Сделать удобную выгрузку отчётов": "reports-dashboards",
            "Описать состояния заказа и переходы": "lifecycle",
            "Подготовить критерии приемки и DoD": "review-acceptance",
            "Исправить небольшую локальную постановку": "core",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(self.first_match(text), expected)

    def test_every_route_matches_its_own_when(self) -> None:
        for route in self.data["routes"]:
            if route["id"] == "core":
                continue
            with self.subTest(route=route["id"]):
                self.assertEqual(self.first_match(route["when"]), route["id"])

    def test_provenance_does_not_match_performance(self) -> None:
        self.assertEqual(
            self.first_match("Проверить происхождение артефакта D14"),
            "source-audit",
        )

    def test_every_route_renders_distilled_context(self) -> None:
        for route in self.data["routes"]:
            with self.subTest(route=route["id"]):
                output = io.StringIO()
                with redirect_stdout(output):
                    vigers_context.show_route(
                        self.data, route["id"], include_fallback=False
                    )
                self.assertIn(f"# Route: {route['id']}", output.getvalue())

    def test_fallback_does_not_leak_contents_page(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            vigers_context.show_route(
                self.data, "traceability", include_fallback=True
            )
        rendered = output.getvalue()
        self.assertIn("book-traceability", rendered)
        self.assertIn("Матрица отслеживаемости требований", rendered)
        self.assertNotIn("ОГЛАВЛЕНИЕ", rendered)

    def test_exact_native_id(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            vigers_context.show_native_id("C09")
        rendered = output.getvalue()
        self.assertIn("C09. Информационная безопасность", rendered)
        self.assertNotIn("C10. Измерение удобства", rendered)

    def test_materialized_context_is_deterministic_and_valid(self) -> None:
        first_payload, first_markdown = vigers_context.build_method_context(
            self.data,
            "traceability",
        )
        second_payload, second_markdown = vigers_context.build_method_context(
            self.data,
            "traceability",
        )
        self.assertEqual(first_payload, second_payload)
        self.assertEqual(first_markdown, second_markdown)
        vigers_context.validate_method_context(
            first_payload,
            first_markdown,
            expected_route_id="traceability",
            verify_sources=True,
        )
        self.assertNotIn("book-traceability", first_markdown)

    def test_materialized_context_includes_only_requested_fallback(self) -> None:
        payload, markdown = vigers_context.build_method_context(
            self.data,
            "traceability",
            include_fallback=True,
        )
        self.assertTrue(payload["include_fallback"])
        self.assertIn("book-traceability", markdown)
        self.assertNotIn("ОГЛАВЛЕНИЕ", markdown)

    def test_materialized_context_accepts_one_route_owned_exact_id(self) -> None:
        payload, markdown = vigers_context.build_method_context(
            self.data,
            "quality",
            exact_ids=["C09"],
        )
        self.assertEqual(payload["exact_ids"], ["C09"])
        self.assertIn("C09. Информационная безопасность", markdown)
        with self.assertRaises(vigers_context.RouterError):
            vigers_context.build_method_context(
                self.data,
                "traceability",
                exact_ids=["C09"],
            )

    def test_method_context_detects_tampered_markdown(self) -> None:
        payload, markdown = vigers_context.build_method_context(self.data, "core")
        with self.assertRaises(vigers_context.RouterError):
            vigers_context.validate_method_context(payload, markdown + "tampered")

    def test_method_context_writer_refuses_overwrite(self) -> None:
        payload, markdown = vigers_context.build_method_context(self.data, "core")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "case"
            vigers_context.write_method_context(root, payload, markdown)
            saved = json.loads(
                (root / vigers_context.METHOD_CONTEXT_JSON).read_text(encoding="utf-8")
            )
            self.assertEqual(saved["fingerprint"], payload["fingerprint"])
            with self.assertRaises(vigers_context.RouterError):
                vigers_context.write_method_context(root, payload, markdown)


if __name__ == "__main__":
    unittest.main()
