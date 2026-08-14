#!/usr/bin/env python3
"""Regression tests for project-local timing calendar projections."""

from __future__ import annotations

import unittest
from datetime import datetime

import timing_calendar


def calendar() -> dict[str, object]:
    return {
        "schema": 1,
        "calendar_id": "rtl",
        "timezone": "Europe/Moscow",
        "working_windows": [
            {"weekdays": [1, 2, 3, 4, 5], "start": "09:00", "end": "18:00"}
        ],
        "handoff_windows": [
            {"weekdays": [1, 2, 3, 4, 5], "start": "09:00", "end": "18:00"}
        ],
        "holidays": [],
    }


class TimingCalendarTests(unittest.TestCase):
    def test_friday_evening_projection_moves_handoff_to_monday(self) -> None:
        projected = timing_calendar.project_business_seconds(
            calendar(),
            started_at=datetime.fromisoformat("2026-08-14T17:00:00+03:00"),
            business_seconds=2 * 3600,
        )
        self.assertEqual(projected.isoformat(), "2026-08-17T07:00:00+00:00")

    def test_completion_after_handoff_window_snaps_to_next_window(self) -> None:
        value = calendar()
        value["working_windows"] = [
            {"weekdays": [1, 2, 3, 4, 5], "start": "09:00", "end": "21:00"}
        ]
        projected = timing_calendar.project_business_seconds(
            value,
            started_at=datetime.fromisoformat("2026-08-14T17:00:00+03:00"),
            business_seconds=2 * 3600,
        )
        self.assertEqual(projected.isoformat(), "2026-08-17T06:00:00+00:00")

    def test_holiday_is_skipped(self) -> None:
        value = calendar()
        value["holidays"] = ["2026-08-17"]
        projected = timing_calendar.project_business_seconds(
            value,
            started_at=datetime.fromisoformat("2026-08-14T17:00:00+03:00"),
            business_seconds=2 * 3600,
        )
        self.assertEqual(projected.isoformat(), "2026-08-18T07:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
