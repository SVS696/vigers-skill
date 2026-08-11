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


def story_contract() -> dict[str, object]:
    metadata = {
        "document_checks": "draft, working_projection",
        "document_required_headings": (
            "Оглавление, История изменений, Описание, User Story, Полезные ссылки"
        ),
        "document_toc": "obsidian-h2-exact",
        "document_toc_heading": "Оглавление",
        "document_toc_separators": "required",
        "document_user_story_policy": "numbered-role-goal-value",
        "document_user_story_heading": "User Story",
        "document_user_story_id_prefix": "US",
        "document_user_story_title_separator": ".",
        "document_user_story_role_label": "Как",
        "document_user_story_goal_label": "я хочу",
        "document_user_story_value_label": "чтобы",
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


VALID_STORIES = VALID.replace(
    "## User Story\n\nТекст.",
    """## User Story

### US-1. Просмотр результата

**Как пользователь**, я хочу видеть результат, чтобы принять решение.

### US-2. Повторная проверка

**Как контролёр**, я хочу
перепроверить результат, чтобы исключить ошибку.""",
)


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

    def test_numbered_role_goal_value_stories_pass(self) -> None:
        self.assertEqual(
            document_conformance.validate_markdown(
                VALID_STORIES,
                story_contract(),
                label="draft",
            ),
            [],
        )

    def test_user_story_table_is_rejected(self) -> None:
        text = VALID.replace(
            "## User Story\n\nТекст.",
            """## User Story

| ID | Как | Хочу | Чтобы |
|---|---|---|---|
| ACT-1 | Пользователь | Видеть результат | Принять решение |""",
        )
        errors = document_conformance.validate_markdown(
            text,
            story_contract(),
            label="draft",
        )
        self.assertTrue(any("must contain at least one" in item for item in errors))

    def test_plain_story_bullets_are_rejected(self) -> None:
        text = VALID.replace(
            "## User Story\n\nТекст.",
            """## User Story

- Как пользователь, я хочу видеть результат, чтобы принять решение.""",
        )
        errors = document_conformance.validate_markdown(
            text,
            story_contract(),
            label="draft",
        )
        self.assertTrue(any("must contain at least one" in item for item in errors))

    def test_scenario_subsection_cannot_replace_user_story(self) -> None:
        text = VALID.replace(
            "## User Story\n\nТекст.",
            """## User Story

### Сценарии

- SCN-1 — Построить результат.""",
        )
        errors = document_conformance.validate_markdown(
            text,
            story_contract(),
            label="draft",
        )
        self.assertTrue(any("unexpected H3" in item for item in errors))
        self.assertTrue(any("must contain at least one" in item for item in errors))

    def test_story_statement_must_use_project_markers(self) -> None:
        text = VALID_STORIES.replace(
            "**Как пользователь**, я хочу видеть результат, чтобы принять решение.",
            "**Как** пользователь, **я хочу** видеть результат, **чтобы** принять решение.",
        )
        errors = document_conformance.validate_markdown(
            text,
            story_contract(),
            label="draft",
        )
        self.assertTrue(any("must contain exactly one" in item for item in errors))

    def test_story_ids_are_sequential(self) -> None:
        text = VALID_STORIES.replace("### US-2. Повторная проверка", "### US-3. Повторная проверка")
        errors = document_conformance.validate_markdown(
            text,
            story_contract(),
            label="draft",
        )
        self.assertTrue(any("IDs must be unique and sequential" in item for item in errors))


if __name__ == "__main__":
    unittest.main()
