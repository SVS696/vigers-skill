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


def trace_contract() -> dict[str, object]:
    metadata = {
        "document_checks": "draft, working_projection",
        "document_required_headings": (
            "Оглавление, User Story, Требования, Acceptance Criteria, "
            "Definition of Done, Трассировка, Полезные ссылки"
        ),
        "document_toc": "obsidian-h2-exact",
        "document_toc_heading": "Оглавление",
        "document_toc_separators": "required",
        "document_traceability_policy": "semantic-id-links",
        "document_traceability_heading": "Трассировка",
        "document_traceability_link_style": "obsidian-heading-exact",
        "document_traceability_id_prefixes": "US, REQ, AC, DOD",
    }
    result = document_conformance.build_profile_contract(
        metadata,
        profile_id="project-alpha",
        profile_text=PROFILE,
        source=Path("profile.md"),
    )
    assert result is not None
    return result


def projection_contract() -> dict[str, object]:
    metadata = {
        "document_checks": "draft, working_projection",
        "document_required_headings": (
            "Оглавление, User Story, Требования, Acceptance Criteria, "
            "Definition of Done, Трассировка, Полезные ссылки"
        ),
        "document_toc": "obsidian-h2-exact",
        "document_toc_heading": "Оглавление",
        "document_toc_separators": "required",
        "document_traceability_policy": "semantic-id-links",
        "document_traceability_heading": "Трассировка",
        "document_traceability_link_style": "obsidian-heading-exact",
        "document_traceability_id_prefixes": "US, REQ, AC, DOD",
        "document_reader_projection": "required",
        "document_public_id_prefixes": "GOAL, US, SCN, RULE, DATA, STATE, IF, REQ, AC, DOD",
        "document_internal_id_prefixes": "ACT, CON, DEC, ARCH, ASM, Q, PUS, PDOD",
        "document_semantic_references": "exact-heading-links",
        "document_traceability_density": "direct-edges",
        "document_acceptance_focus": "observable-behavior",
        "document_dod_focus": "acceptance-readiness",
        "document_developer_checks": "omit-unless-normative",
        "document_prose_language": "ru",
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


VALID_TRACE = r"""# Постановка

---

## Оглавление

1. [[#User Story]]
2. [[#Требования]]
3. [[#Acceptance Criteria]]
4. [[#Definition of Done]]
5. [[#Трассировка]]
6. [[#Полезные ссылки]]

---

## User Story

### US-1. Просмотр результата

Текст.

## Требования

### REQ-B01-001 — Показать результат

Текст.

## Acceptance Criteria

### AC-B01-001 — Результат показан

Текст.

## Definition of Done

### DOD-B01-001 — Проверка добавлена

Текст.

## Трассировка

| Откуда | Куда |
|---|---|
| [[#US-1. Просмотр результата\|US-1]] | [[#REQ-B01-001 — Показать результат\|REQ-B01-001]] |
| [[#AC-B01-001 — Результат показан\|AC-B01-001]] | [[#REQ-B01-001 — Показать результат\|REQ-B01-001]] |
| [[#DOD-B01-001 — Проверка добавлена\|DOD-B01-001]] | [[#AC-B01-001 — Результат показан\|AC-B01-001]] |

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

    def test_individual_semantic_heading_links_pass(self) -> None:
        self.assertEqual(
            document_conformance.validate_markdown(
                VALID_TRACE,
                trace_contract(),
                label="draft",
            ),
            [],
        )

    def test_plain_trace_ids_are_rejected(self) -> None:
        text = VALID_TRACE.replace(
            "[[#REQ-B01-001 — Показать результат\\|REQ-B01-001]]",
            "REQ-B01-001",
        )
        errors = document_conformance.validate_markdown(text, trace_contract(), label="draft")
        self.assertTrue(any("must be an individual internal link" in item for item in errors))

    def test_compressed_trace_ranges_are_rejected(self) -> None:
        text = VALID_TRACE.replace(
            "[[#REQ-B01-001 — Показать результат\\|REQ-B01-001]]",
            "REQ-B01-001/004–007",
        )
        errors = document_conformance.validate_markdown(text, trace_contract(), label="draft")
        self.assertTrue(any("must not compress semantic ID ranges" in item for item in errors))

    def test_trace_link_must_resolve_exact_heading(self) -> None:
        text = VALID_TRACE.replace(
            "#REQ-B01-001 — Показать результат\\|REQ-B01-001",
            "#REQ-B01-001 — Несуществующий заголовок\\|REQ-B01-001",
            1,
        )
        errors = document_conformance.validate_markdown(text, trace_contract(), label="draft")
        self.assertTrue(any("missing exact heading target" in item for item in errors))

    def test_trace_alias_must_equal_target_semantic_id(self) -> None:
        text = VALID_TRACE.replace(
            "#REQ-B01-001 — Показать результат\\|REQ-B01-001",
            "#REQ-B01-001 — Показать результат\\|AC-B01-001",
            1,
        )
        errors = document_conformance.validate_markdown(text, trace_contract(), label="draft")
        self.assertTrue(any("different semantic ID" in item for item in errors))

    def test_trace_table_alias_separator_must_be_escaped(self) -> None:
        text = VALID_TRACE.replace(
            "#US-1. Просмотр результата\\|US-1",
            "#US-1. Просмотр результата|US-1",
        )
        errors = document_conformance.validate_markdown(text, trace_contract(), label="draft")
        self.assertTrue(any("must escape its alias separator" in item for item in errors))

    def test_partial_traceability_contract_is_rejected(self) -> None:
        metadata = {
            "document_checks": "draft",
            "document_required_headings": "Оглавление, Трассировка",
            "document_toc": "obsidian-h2-exact",
            "document_toc_heading": "Оглавление",
            "document_toc_separators": "optional",
            "document_traceability_policy": "semantic-id-links",
        }
        with self.assertRaises(document_conformance.DocumentContractError):
            document_conformance.build_profile_contract(
                metadata,
                profile_id="project-alpha",
                profile_text=PROFILE,
                source=Path("profile.md"),
            )

    def test_reader_projection_accepts_defined_and_linked_public_ids(self) -> None:
        self.assertEqual(
            document_conformance.validate_markdown(
                VALID_TRACE,
                projection_contract(),
                label="draft",
            ),
            [],
        )

    def test_reader_projection_rejects_analysis_only_ids_anywhere(self) -> None:
        text = VALID_TRACE.replace(
            "Текст.\n\n## Требования",
            "Решение принято по ARCH-013.\n\n## Требования",
        )
        errors = document_conformance.validate_markdown(
            text,
            projection_contract(),
            label="draft",
        )
        self.assertTrue(any("analysis-only semantic IDs: ARCH-013" in item for item in errors))

    def test_reader_projection_keeps_goal_as_public_navigable_layer(self) -> None:
        text = VALID_TRACE.replace(
            "## User Story\n\n### US-1. Просмотр результата\n\nТекст.",
            """## User Story

### GOAL-B01-001 — Дать пользователю результат

Общая бизнес-цель.

### US-1. Просмотр результата

Реализует [[#GOAL-B01-001 — Дать пользователю результат|GOAL-B01-001]].""",
        )
        self.assertEqual(
            document_conformance.validate_markdown(
                text,
                projection_contract(),
                label="draft",
            ),
            [],
        )

    def test_reader_projection_rejects_plain_public_reference_outside_traceability(self) -> None:
        text = VALID_TRACE.replace(
            "Текст.\n\n## Требования",
            "Поведение описано в REQ-B01-001.\n\n## Требования",
        )
        errors = document_conformance.validate_markdown(
            text,
            projection_contract(),
            label="draft",
        )
        self.assertTrue(any("outside its definition heading" in item for item in errors))

    def test_reader_projection_rejects_compressed_reference_outside_traceability(self) -> None:
        text = VALID_TRACE.replace(
            "Текст.\n\n## Требования",
            "Проверить AC-B01-001/003–005.\n\n## Требования",
        )
        errors = document_conformance.validate_markdown(
            text,
            projection_contract(),
            label="draft",
        )
        self.assertTrue(any("must not use compressed ranges" in item for item in errors))

    def test_reader_projection_rejects_dangling_link_outside_traceability(self) -> None:
        text = VALID_TRACE.replace(
            "Текст.\n\n## Требования",
            "См. [[#REQ-B01-999 — Нет определения|REQ-B01-999]].\n\n## Требования",
        )
        errors = document_conformance.validate_markdown(
            text,
            projection_contract(),
            label="draft",
        )
        self.assertTrue(any("missing exact heading target" in item for item in errors))

    def test_reader_projection_prefix_sets_must_not_overlap(self) -> None:
        metadata = {
            "document_checks": "draft",
            "document_required_headings": "Оглавление",
            "document_toc": "obsidian-h2-exact",
            "document_toc_heading": "Оглавление",
            "document_toc_separators": "optional",
            "document_reader_projection": "required",
            "document_public_id_prefixes": "US, REQ",
            "document_internal_id_prefixes": "REQ, ARCH",
            "document_semantic_references": "exact-heading-links",
            "document_traceability_density": "direct-edges",
            "document_acceptance_focus": "observable-behavior",
            "document_dod_focus": "acceptance-readiness",
            "document_developer_checks": "omit-unless-normative",
            "document_prose_language": "ru",
        }
        with self.assertRaises(document_conformance.DocumentContractError):
            document_conformance.build_profile_contract(
                metadata,
                profile_id="project-alpha",
                profile_text=PROFILE,
                source=Path("profile.md"),
            )


if __name__ == "__main__":
    unittest.main()
