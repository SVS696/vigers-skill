#!/usr/bin/env python3
"""Regression tests for the deterministic Vigers context router."""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout

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


if __name__ == "__main__":
    unittest.main()
