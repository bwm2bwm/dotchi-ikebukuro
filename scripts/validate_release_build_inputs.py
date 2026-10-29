#!/usr/bin/env python3
"""Validate fixed-date release build inputs and an optional A/B comparison."""
from __future__ import annotations

import argparse
from datetime import date, datetime
import json
import re
import sys
from typing import Any
from zoneinfo import ZoneInfo


RELEASE_ID_RE = re.compile(r"^r1-[0-9a-f]{64}$")
SERVICE_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
JST = ZoneInfo("Asia/Tokyo")


class BuildInputError(ValueError):
    """Safe input validation error; never includes caller supplied values."""


def _service_date(value: str | None, *, now: datetime | None = None) -> str:
    if value is None or value == "":
        instant = now if now is not None else datetime.now(JST)
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise BuildInputError("current time must include a timezone")
        return instant.astimezone(JST).date().isoformat()
    if not isinstance(value, str) or not SERVICE_DATE_RE.fullmatch(value):
        raise BuildInputError("service-date must use YYYY-MM-DD")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise BuildInputError("service-date is not a calendar date") from None
    if parsed.isoformat() != value:
        raise BuildInputError("service-date must use canonical YYYY-MM-DD")
    return value


def resolve_build_inputs(*, service_date: str | None, expected_previous_release_id: str | None,
                         publish_staging: bool, allow_initial_legacy_migration: bool,
                         now: datetime | None = None) -> dict[str, Any]:
    """Validate dispatch inputs and resolve the date while preserving omitted-date behavior."""
    resolved_date = _service_date(service_date, now=now)
    expected = expected_previous_release_id or None
    if expected is not None and not RELEASE_ID_RE.fullmatch(expected):
        raise BuildInputError("expected previous releaseId is malformed")
    if expected is not None and allow_initial_legacy_migration:
        raise BuildInputError("legacy migration cannot be enabled when expected previous releaseId is supplied")
    if publish_staging:
        if not allow_initial_legacy_migration and expected is None:
            raise BuildInputError("expected previous releaseId is required for release-managed publishing")
    return {"service_date_anchor": resolved_date,
            "expected_previous_release_id": expected}


def compare_release_ids(*, built_release_id: str, expected_previous_release_id: str | None) -> str:
    """Return a safe comparison status or fail closed when B equals expected A."""
    if not isinstance(built_release_id, str) or not RELEASE_ID_RE.fullmatch(built_release_id):
        raise BuildInputError("built releaseId is malformed")
    if expected_previous_release_id is None:
        return "not-requested"
    if not RELEASE_ID_RE.fullmatch(expected_previous_release_id):
        raise BuildInputError("expected previous releaseId is malformed")
    if built_release_id == expected_previous_release_id:
        raise BuildInputError("new releaseId equals expected previous releaseId")
    return "different"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service-date", default="")
    parser.add_argument("--expected-previous-release-id", default="")
    parser.add_argument("--publish-staging", action="store_true")
    parser.add_argument("--allow-initial-legacy-migration", action="store_true")
    parser.add_argument("--built-release-id")
    args = parser.parse_args()
    try:
        result = resolve_build_inputs(
            service_date=args.service_date,
            expected_previous_release_id=args.expected_previous_release_id,
            publish_staging=args.publish_staging,
            allow_initial_legacy_migration=args.allow_initial_legacy_migration,
        )
        if args.built_release_id is not None:
            result["ab_comparison"] = compare_release_ids(
                built_release_id=args.built_release_id,
                expected_previous_release_id=result["expected_previous_release_id"],
            )
    except BuildInputError as error:
        print(f"release build input validation failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
