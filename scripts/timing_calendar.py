#!/usr/bin/env python3
"""Project-local working calendar and deterministic handoff projection."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

SCHEMA_VERSION = 1
MAX_PROJECTION_DAYS = 3660


class TimingCalendarError(RuntimeError):
    """Invalid calendar or a completion projection that cannot be resolved."""


def parse_clock(value: Any, *, field: str) -> time:
    if not isinstance(value, str) or not value.strip():
        raise TimingCalendarError(f"{field} must be HH:MM")
    try:
        parsed = time.fromisoformat(value.strip())
    except ValueError as exc:
        raise TimingCalendarError(f"{field} must be HH:MM") from exc
    if parsed.tzinfo is not None or parsed.second or parsed.microsecond:
        raise TimingCalendarError(f"{field} must be local HH:MM without seconds")
    return parsed


def validate_rules(value: Any, *, field: str) -> None:
    if not isinstance(value, list) or not value:
        raise TimingCalendarError(f"{field} must be a non-empty array")
    for index, rule in enumerate(value, start=1):
        label = f"{field}[{index}]"
        if not isinstance(rule, dict):
            raise TimingCalendarError(f"{label} must be an object")
        weekdays = rule.get("weekdays")
        if (
            not isinstance(weekdays, list)
            or not weekdays
            or any(
                not isinstance(item, int)
                or isinstance(item, bool)
                or item < 1
                or item > 7
                for item in weekdays
            )
        ):
            raise TimingCalendarError(f"{label}.weekdays must contain ISO weekdays 1..7")
        if len(set(weekdays)) != len(weekdays):
            raise TimingCalendarError(f"{label}.weekdays must not contain duplicates")
        start = parse_clock(rule.get("start"), field=f"{label}.start")
        end = parse_clock(rule.get("end"), field=f"{label}.end")
        if end <= start:
            raise TimingCalendarError(f"{label} must finish after it starts")


def validate_calendar(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA_VERSION:
        raise TimingCalendarError("timing calendar has unsupported schema")
    if not isinstance(payload.get("calendar_id"), str) or not payload["calendar_id"].strip():
        raise TimingCalendarError("timing calendar calendar_id is required")
    timezone_name = payload.get("timezone")
    if not isinstance(timezone_name, str) or not timezone_name.strip():
        raise TimingCalendarError("timing calendar timezone is required")
    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise TimingCalendarError("timing calendar timezone is unknown") from exc
    validate_rules(payload.get("working_windows"), field="working_windows")
    if payload.get("handoff_windows") is not None:
        validate_rules(payload["handoff_windows"], field="handoff_windows")
    holidays = payload.get("holidays", [])
    if not isinstance(holidays, list):
        raise TimingCalendarError("timing calendar holidays must be an array")
    parsed_holidays: set[date] = set()
    for index, value in enumerate(holidays, start=1):
        try:
            parsed = date.fromisoformat(value)
        except (TypeError, ValueError) as exc:
            raise TimingCalendarError(
                f"timing calendar holidays[{index}] must be YYYY-MM-DD"
            ) from exc
        if parsed in parsed_holidays:
            raise TimingCalendarError("timing calendar holidays contain duplicates")
        parsed_holidays.add(parsed)
    return payload


def local_windows(
    payload: dict[str, Any],
    local_day: date,
    *,
    field: str,
) -> list[tuple[datetime, datetime]]:
    timezone = ZoneInfo(payload["timezone"])
    holidays = {date.fromisoformat(value) for value in payload.get("holidays", [])}
    if local_day in holidays:
        return []
    rules = payload.get(field) or payload["working_windows"]
    intervals: list[tuple[datetime, datetime]] = []
    for rule in rules:
        if local_day.isoweekday() not in rule["weekdays"]:
            continue
        start = datetime.combine(
            local_day,
            parse_clock(rule["start"], field=f"{field}.start"),
            tzinfo=timezone,
        ).astimezone(UTC)
        end = datetime.combine(
            local_day,
            parse_clock(rule["end"], field=f"{field}.end"),
            tzinfo=timezone,
        ).astimezone(UTC)
        intervals.append((start, end))
    return sorted(intervals)


def next_handoff_at(payload: dict[str, Any], candidate: datetime) -> datetime:
    """Return candidate inside an allowed handoff window or the next window start."""
    validate_calendar(payload)
    if candidate.tzinfo is None:
        raise TimingCalendarError("handoff candidate requires timezone")
    candidate = candidate.astimezone(UTC)
    timezone = ZoneInfo(payload["timezone"])
    local_day = candidate.astimezone(timezone).date()
    for offset in range(MAX_PROJECTION_DAYS):
        day = local_day + timedelta(days=offset)
        for start, end in local_windows(payload, day, field="handoff_windows"):
            if start <= candidate <= end:
                return candidate
            if start >= candidate:
                return start
    raise TimingCalendarError("cannot resolve a handoff window within ten years")


def project_business_seconds(
    payload: dict[str, Any],
    *,
    started_at: datetime,
    business_seconds: int,
) -> datetime:
    """Lay business duration over working windows, then snap to a handoff window."""
    validate_calendar(payload)
    if started_at.tzinfo is None:
        raise TimingCalendarError("projection start requires timezone")
    if not isinstance(business_seconds, int) or isinstance(business_seconds, bool):
        raise TimingCalendarError("business_seconds must be an integer")
    if business_seconds < 0:
        raise TimingCalendarError("business_seconds must be non-negative")
    cursor = started_at.astimezone(UTC)
    remaining = business_seconds
    timezone = ZoneInfo(payload["timezone"])
    local_day = cursor.astimezone(timezone).date()
    for offset in range(MAX_PROJECTION_DAYS):
        day = local_day + timedelta(days=offset)
        for start, end in local_windows(payload, day, field="working_windows"):
            effective_start = max(start, cursor)
            if effective_start >= end:
                continue
            available = int((end - effective_start).total_seconds())
            if remaining <= available:
                return next_handoff_at(
                    payload, effective_start + timedelta(seconds=remaining)
                )
            remaining -= available
            cursor = end
    raise TimingCalendarError("cannot project business duration within ten years")
