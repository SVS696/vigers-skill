#!/usr/bin/env python3
"""Regression tests for profile-owned Markdown document contracts."""

from __future__ import annotations

import unittest
from pathlib import Path

import document_conformance


PROFILE = """---
vigers_profile: 2
profile_id: project-alpha
document_checks: draft, working_projection
document_required_headings: Оглавление, История изменений, Описание, User Story, Полезные ссылки
document_toc: obsidian-h2-exact
document_toc_heading: Оглавление
document_toc_separators: required
---
"""


def contract() -> dict[str, object]:
    metadata = {
        "document_checks": "draft, working_projection",
        "document_required_headings": (
            "Оглавление, История изменений, Описание, User Story, Полезные ссылки"
        ),
        "document_toc": "obsidian-h2-exact",
        "document_toc_heading": "Оглавление",
        "document_toc_separators": "required",
    }
    result = document_conformance.build_profile_contract(
        metadata,
        profile_id="project-alpha",
        profile_text=PROFILE,
        source=Path("profile.md"),
    )
    assert result is not None
    return result


VALID = """# Постановка

---

## Оглавление

1. [[#История изменений]]
2. [[#Описание]]
3. [[#User Story]]
4. [[#Полезные ссылки]]

---

## История изменений

Текст.

## Описание

Текст.

## User Story

Текст.

## Полезные ссылки

Текст.
"""


class DocumentConformanceTests(unittest.TestCase):
    def test_valid_obsidian_toc_passes(self) -> None:
        self.assertEqual(
            document_conformance.validate_markdown(VALID, contract(), label="draft"),
            [],
        )

    def test_missing_toc_is_rejected(self) -> None:
        text = VALID.replace(
            "---\n\n## Оглавление\n\n1. [[#История изменений]]\n"
            "2. [[#Описание]]\n3. [[#User Story]]\n4. [[#Полезные ссылки]]\n\n---\n\n",
            "",
        )
        errors = document_conformance.validate_markdown(text, contract(), label="visible")
        self.assertTrue(any("missing required H2 headings: Оглавление" in item for item in errors))

    def test_toc_must_cover_h2_in_exact_order(self) -> None:
        text = VALID.replace(
            "2. [[#Описание]]\n3. [[#User Story]]",
            "2. [[#User Story]]\n3. [[#Описание]]",
        )
        errors = document_conformance.validate_markdown(text, contract(), label="draft")
        self.assertTrue(any("order differs from H2 order" in item for item in errors))

    def test_toc_separators_are_required(self) -> None:
        text = VALID.replace("# Постановка\n\n---\n\n## Оглавление", "# Постановка\n\n## Оглавление")
        errors = document_conformance.validate_markdown(text, contract(), label="draft")
        self.assertTrue(any("separator before" in item for item in errors))


if __name__ == "__main__":
    unittest.main()
