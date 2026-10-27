"""Create deterministic public-profile fixtures from one tracked synthetic test input."""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, time, timedelta
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any
from zoneinfo import ZoneInfo

from public_payload_profile import project_public_payload

ROOT = Path(__file__).resolve().parents[1]
SOURCE_FIXTURE = ROOT / "tests" / "fixtures" / "public_payload_profile_input.json"
JST = ZoneInfo("Asia/Tokyo")
SYNTHETIC_MARKER = ".synthetic-public-display-v1"
SYNTHETIC_MARKER_CONTENT = "dotchi-ikebukuro synthetic public payload fixtures v1\n"
STATION_FILES = {
    "Kanamecho": "timetable-Kanamecho.json",
    "Senkawa": "timetable-Senkawa.json",
    "KotakeMukaihara": "timetable-KotakeMukaihara.json",
    "Hikawadai": "timetable.json",
    "Heiwadai": "timetable-Heiwadai.json",
    "ChikatetsuAkatsuka": "timetable-ChikatetsuAkatsuka.json",
    "ChikatetsuNarimasu": "timetable-ChikatetsuNarimasu.json",
    "Wakoshi": "timetable-Wakoshi.json",
}


class SyntheticFixtureError(ValueError):
    """Raised when a deterministic synthetic fixture cannot be generated safely."""


def jst_today(now: datetime | None = None) -> date:
    """Return today's calendar date in JST; an injected instant aids boundary tests."""
    instant = now if now is not None else datetime.now(JST)
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise SyntheticFixtureError("current time must include a timezone")
    return instant.astimezone(JST).date()


def parse_service_date(value: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError) as error:
        raise SyntheticFixtureError("service date must use YYYY-MM-DD") from error
    if parsed.isoformat() != value:
        raise SyntheticFixtureError("service date must use YYYY-MM-DD")
    return parsed


def _read_source() -> dict[str, Any]:
    """Read only the tracked, local synthetic input used by the profile tests."""
    try:
        source = json.loads(SOURCE_FIXTURE.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SyntheticFixtureError("tracked synthetic test fixture could not be read") from error
    if not isinstance(source, dict) or source.get("dataScope") != "local-preview-only":
        raise SyntheticFixtureError("tracked synthetic test fixture has an unexpected profile")
    try:
        project_public_payload(source)
    except (TypeError, ValueError) as error:
        raise SyntheticFixtureError("tracked synthetic test fixture does not match its local schema") from error
    days = source.get("serviceDays")
    if not isinstance(days, list) or len(days) < 2 or any(not isinstance(day, dict) for day in days[:2]):
        raise SyntheticFixtureError("tracked synthetic test fixture must contain two service-day templates")
    return source


def _set_destination(day: dict[str, Any], destination_id: str) -> None:
    day["originStationId"] = "Ikebukuro"
    day["destinationStationId"] = destination_id
    for departure in day["departures"]:
        # Every generated trip has an unmistakably synthetic, date-specific identity.
        departure["id"] = f"synthetic:{destination_id}:{day['serviceDate']}:{departure['routeId']}"
        departure["originTripId"] = f"synthetic-trip:{day['serviceDate']}:{departure['routeId']}"
        for key in ("primary", "directAlternative", "bestTransferAlternative"):
            journey = departure[key]
            if journey is not None:
                journey["arrivalStationId"] = destination_id


def _recount_destination_status(day: dict[str, Any]) -> None:
    status = day["destinationStatus"]
    by_route = {
        route_id: {"origin": 0, "candidate": 0, "direct": 0, "transfer": 0,
                   "pairs": 0, "transfer_only": 0}
        for route_id in ("6", "9")
    }
    for departure in day["departures"]:
        metrics = by_route[departure["routeId"]]
        metrics["origin"] += 1
        metrics["candidate"] += departure["primary"] is not None
        metrics["direct"] += departure["directAlternative"] is not None
        metrics["transfer"] += departure["bestTransferAlternative"] is not None
        metrics["pairs"] += departure["transferCandidateCount"]
        metrics["transfer_only"] += (
            departure["directAlternative"] is None
            and departure["bestTransferAlternative"] is not None
        )

    for route_id, route in status["routes"].items():
        metrics = by_route[route_id]
        route.update({
            "scheduledTripCount": metrics["origin"],
            "originTripCount": metrics["origin"],
            "candidateCount": metrics["candidate"],
            "directCandidateCount": metrics["direct"],
            "passThroughCount": 0,
            "dataInsufficientCount": 0,
            "transferCandidateCount": metrics["transfer"],
            "transferPairCount": metrics["pairs"],
            "transferOnlyCount": metrics["transfer_only"],
            "transferDataInsufficientCount": 0,
        })

    status.update({
        "status": "normal",
        "candidateCount": sum(item["candidate"] for item in by_route.values()),
        "passThroughCount": 0,
        "dataInsufficientCount": 0,
        "directCandidateCount": sum(item["direct"] for item in by_route.values()),
        "transferCandidateCount": sum(item["transfer"] for item in by_route.values()),
        "transferPairCount": sum(item["pairs"] for item in by_route.values()),
        "transferOnlyCount": sum(item["transfer_only"] for item in by_route.values()),
        "transferPassThroughCount": 0,
        "transferDataInsufficientCount": 0,
    })


def make_public_fixture(destination_id: str, service_dates: list[str]) -> dict[str, Any]:
    """Build one public-display-v1 payload from synthetic direct/transfer templates."""
    if destination_id not in STATION_FILES:
        raise SyntheticFixtureError("unsupported synthetic destination")
    if not service_dates or any(parse_service_date(item).isoformat() != item for item in service_dates):
        raise SyntheticFixtureError("one or more valid service dates are required")
    if len(set(service_dates)) != len(service_dates) or service_dates != sorted(service_dates):
        raise SyntheticFixtureError("service dates must be unique and ascending")

    source = _read_source()
    templates = source["serviceDays"][:2]
    generated_days: list[dict[str, Any]] = []
    for service_date in service_dates:
        day = deepcopy(templates[0])
        day["serviceDate"] = service_date
        day["departures"] = deepcopy(templates[0]["departures"] + templates[1]["departures"])
        _set_destination(day, destination_id)
        _recount_destination_status(day)
        generated_days.append(day)

    first_date = parse_service_date(service_dates[0])
    last_date = parse_service_date(service_dates[-1])
    generated_at = datetime.combine(first_date, time(0), JST).isoformat(timespec="seconds")
    source["generatedAt"] = generated_at
    source["feed"]["validFrom"] = first_date.isoformat()
    source["feed"]["validThrough"] = last_date.isoformat()
    source["applicationPeriod"]["startsAt"] = datetime.combine(
        first_date, time(0), JST).isoformat(timespec="seconds")
    source["applicationPeriod"]["endsAt"] = datetime.combine(
        last_date + timedelta(days=1), time(0), JST).isoformat(timespec="seconds")
    source["serviceDays"] = generated_days

    try:
        return project_public_payload(source)
    except (TypeError, ValueError) as error:
        raise SyntheticFixtureError("synthetic input did not satisfy the public payload profile") from error


def generate_fixture_directory(output: Path, anchor_date: date) -> dict[str, Any]:
    """Atomically create a new fixture directory; existing paths are never overwritten."""
    output = output.expanduser().absolute()
    if output.exists() or output.is_symlink():
        raise SyntheticFixtureError("output already exists; choose a new output path")
    if output.name in {"", ".", ".."}:
        raise SyntheticFixtureError("output must name a new directory")
    output.parent.mkdir(parents=True, exist_ok=True)

    lock = output.parent / ("." + output.name + ".synthetic-fixture.lock")
    try:
        lock.mkdir()
    except FileExistsError as error:
        raise SyntheticFixtureError("another fixture generation is using this output path") from error

    stage: Path | None = None
    try:
        if output.exists() or output.is_symlink():
            raise SyntheticFixtureError("output already exists; choose a new output path")
        stage = Path(tempfile.mkdtemp(prefix=".synthetic-fixtures-", dir=output.parent))
        service_dates = [(anchor_date + timedelta(days=offset)).isoformat() for offset in (-1, 0, 1)]
        for destination_id, filename in STATION_FILES.items():
            payload = make_public_fixture(destination_id, service_dates)
            (stage / filename).write_text(
                json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                encoding="utf-8",
            )
        (stage / SYNTHETIC_MARKER).write_text(SYNTHETIC_MARKER_CONTENT, encoding="utf-8")

        # The completed directory (including its marker) becomes visible in one rename.
        os.rename(stage, output)
        stage = None
        return {"output": output, "stations": len(STATION_FILES), "service_dates": service_dates}
    except OSError as error:
        raise SyntheticFixtureError("synthetic fixture directory could not be published") from error
    finally:
        if stage is not None:
            shutil.rmtree(stage, ignore_errors=True)
        shutil.rmtree(lock, ignore_errors=True)
