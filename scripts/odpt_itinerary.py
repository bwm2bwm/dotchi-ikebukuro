#!/usr/bin/env python3
"""Build local, date-specific Ikebukuro itineraries from Tokyo Metro GTFS.

This module is deliberately offline: it reads the supplied GTFS zip and optional
saved ODPT timetable JSON files. It never performs network requests or prints raw
ODPT records.
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path
from typing import Any
import zipfile
from odpt_stop_patterns import CRITICAL_STOPS, TypeResolution, classify, event_state, resolve_type


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = ROOT / "local_data" / "odpt"
DEFAULT_GTFS = DEFAULT_DATA_DIR / "TokyoMetro-Train-GTFS.zip"

ROUTES = {"6": "有楽町線", "9": "副都心線"}
OPPOSITE_ROUTE = {"6": "9", "9": "6"}
# Phase 1 station catalog. Stop IDs are route-scoped; a station is never
# inferred from its display name or from the other route's stop ID.
DESTINATIONS = {
    "Kanamecho": {"name": "要町", "stationKey": "kanamecho", "routeStopIds": {"6": "608", "9": "908"}, "outboundOrder": 1, "routePolicy": "direct_only"},
    "Senkawa": {"name": "千川", "stationKey": "senkawa", "routeStopIds": {"6": "607", "9": "907"}, "outboundOrder": 2, "routePolicy": "direct_only"},
    "KotakeMukaihara": {"name": "小竹向原", "stationKey": "kotake_mukaihara", "routeStopIds": {"6": "606", "9": "906"}, "outboundOrder": 3, "routePolicy": "direct_only"},
    "Hikawadai": {"name": "氷川台", "stationKey": "hikawadai", "routeStopIds": {"6": "605", "9": "905"}, "outboundOrder": 4, "routePolicy": "direct_and_kotake_transfer"},
    "Heiwadai": {"name": "平和台", "stationKey": "heiwadai", "routeStopIds": {"6": "604", "9": "904"}, "outboundOrder": 5, "routePolicy": "direct_and_kotake_transfer"},
    "ChikatetsuAkatsuka": {"name": "地下鉄赤塚", "stationKey": "chikatetsu_akatsuka", "routeStopIds": {"6": "603", "9": "903"}, "outboundOrder": 6, "routePolicy": "direct_and_kotake_transfer"},
    "ChikatetsuNarimasu": {"name": "地下鉄成増", "stationKey": "chikatetsu_narimasu", "routeStopIds": {"6": "602", "9": "902"}, "outboundOrder": 7, "routePolicy": "direct_and_kotake_transfer"},
    "Wakoshi": {"name": "和光市", "stationKey": "wakoshi", "routeStopIds": {"6": "601", "9": "901"}, "outboundOrder": 8, "routePolicy": "direct_and_kotake_transfer"},
}
DEFAULT_DESTINATION_ID = "Hikawadai"
# Phases 2–3 validate same-trip direct journeys for the parallel corridor.
VERIFIED_DESTINATION_IDS = frozenset({
    "Kanamecho", "Senkawa", "KotakeMukaihara", DEFAULT_DESTINATION_ID,
    "Heiwadai", "ChikatetsuAkatsuka", "ChikatetsuNarimasu", "Wakoshi",
})
STATION_STOP_IDS = {
    "ikebukuro": {"228", "609", "909"},
    "kanamecho": {"608", "908"},
    "senkawa": {"607", "907"},
    "kotake_mukaihara": {"606", "906"},
    "hikawadai": {"605", "905"},
    "heiwadai": {"604", "904"},
    "chikatetsu_akatsuka": {"603", "903"},
    "chikatetsu_narimasu": {"602", "902"},
    "wakoshi": {"601", "901"},
}
ROUTE_STOP_IDS = {
    "6": {"ikebukuro": {"228", "609"}, **{
        target["stationKey"]: {target["routeStopIds"]["6"]}
        for target in DESTINATIONS.values()}},
    "9": {"ikebukuro": {"228", "909"}, **{
        target["stationKey"]: {target["routeStopIds"]["9"]}
        for target in DESTINATIONS.values()}},
}
LINE_ODPT = {"6": "Yurakucho", "9": "Fukutoshin"}
ODPT_CALENDAR = {"0": "Weekday", "1": "SaturdayHoliday"}

DESTINATION_DATA_ISSUE_CODES = frozenset({
    "destination_stop_record_missing", "destination_stop_record_ambiguous",
    "destination_arrival_missing", "destination_alighting_restricted",
    "destination_alighting_unknown", "destination_time_order_conflict",
    "destination_stop_order_conflict",
})


def _legacy_destination_event_diagnostics(event: StopEvent) -> set[str]:
    """Keep legacy Hikawadai diagnostics while identifying explicit pass-throughs."""
    diagnostics: set[str] = set()
    if event.arrival_seconds is None:
        diagnostics.add("destination_arrival_missing")
    if event.drop_off_type == "1":
        diagnostics.add("destination_explicit_pass")
        diagnostics.add("destination_alighting_prohibited")
    elif event.drop_off_type in ("2", "3"):
        diagnostics.add("destination_alighting_restricted")
        diagnostics.add("destination_alighting_prohibited")
    elif event.drop_off_type not in ("", "0"):
        diagnostics.add("destination_alighting_unknown")
        diagnostics.add("destination_alighting_prohibited")
    elif not event.can_alight:
        # Defensive fallback if can_alight semantics are extended later.
        diagnostics.add("destination_alighting_unknown")
        diagnostics.add("destination_alighting_prohibited")
    return diagnostics


def _destination_data_issues(diagnostics: set[str]) -> set[str]:
    """Return unresolved destination issues; a missing time at an explicit pass is informational."""
    issues = set(diagnostics) & DESTINATION_DATA_ISSUE_CODES
    if "destination_explicit_pass" in diagnostics:
        issues.discard("destination_arrival_missing")
    return issues


class FeedError(ValueError):
    """Invalid or unsupported GTFS feed."""


class FeedDateError(ValueError):
    """Requested service date is outside the feed validity period."""


class DestinationNotReadyError(ValueError):
    """Destination exists in the catalog but is not journey-validated yet."""


@dataclass(frozen=True)
class StopEvent:
    stop_id: str
    station: str | None
    sequence: int
    arrival_seconds: int | None
    departure_seconds: int | None
    pickup_type: str
    drop_off_type: str
    timepoint: str | None

    @property
    def can_board(self) -> bool:
        return self.pickup_type in ("", "0")

    @property
    def can_alight(self) -> bool:
        return self.drop_off_type in ("", "0")


@dataclass(frozen=True)
class TripInstance:
    service_date: str
    trip_id: str
    service_id: str
    route_id: str
    route_name: str
    headsign: str | None
    departure_seconds: int
    departure_text: str
    origin_event: StopEvent
    events: tuple[StopEvent, ...]
    odpt: OdptEnrichment | None = None
    type_resolution: TypeResolution | None = None


@dataclass(frozen=True)
class OdptEnrichment:
    status: str  # unique_match | unmatched | ambiguous | unavailable
    # train_type is a validated Metro-local type; preserve raw and unscoped
    # through-service codes independently for diagnostics and future UI use.
    train_type: str | None = None
    destination: tuple[str, ...] = ()
    service_brand: str | None = None
    raw_train_type_uri: str | None = None
    reported_train_type: str | None = None
    other_operator_type: str | None = None
    unscoped_through_service_type: str | None = None
    match_method: str | None = None
    match_reason: str | None = None


@dataclass(frozen=True)
class Leg:
    trip: TripInstance
    board: StopEvent
    alight: StopEvent
    board_seconds: int
    alight_seconds: int


@dataclass(frozen=True)
class Itinerary:
    kind: str  # direct | transfer
    departure_seconds: int
    arrival_seconds: int
    departure_text: str
    arrival_text: str
    first_leg: Leg
    second_leg: Leg | None
    transfer_station: str | None
    transfer_wait_seconds: int | None
    platform_status: str = "unknown"
    connection_guaranteed: bool = False
    arrival_station_id: str = DEFAULT_DESTINATION_ID


@dataclass
class DepartureResult:
    service_date: str
    origin_trip_id: str
    route_id: str
    route_name: str
    departure_seconds: int
    departure_text: str
    headsign: str | None
    odpt: OdptEnrichment
    type_resolution: TypeResolution
    primary_itinerary: Itinerary | None
    direct_alternative: Itinerary | None
    best_transfer_alternative: Itinerary | None
    transfer_candidates_count: int
    status: str
    data_quality: list[str] = field(default_factory=list)
    # A valid destination transfer existed but was outside the configured
    # search policy. Kept private and separate from source-data diagnostics.
    transfer_wait_policy_excluded: bool = False


def choose_primary(direct: Itinerary | None, best_transfer: Itinerary | None) -> Itinerary | None:
    """Choose earliest arrival, preferring direct for equal arrivals."""
    choices = [item for item in (direct, best_transfer) if item is not None]
    if not choices:
        return None
    return min(choices, key=lambda item: (
        item.arrival_seconds, 0 if item.kind == "direct" else 1,
        item.transfer_wait_seconds or 0,
        item.second_leg.trip.trip_id if item.second_leg else "",
    ))


def _transfer_wait_in_bounds(wait_seconds: int, minimum: int, maximum: int) -> bool:
    return minimum <= wait_seconds <= maximum


def parse_service_date(value: str | date) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid service date: {value!r}; expected YYYY-MM-DD") from exc


def parse_gtfs_time(value: str | None) -> int | None:
    """Return service-day seconds; GTFS values such as 24:12:00 stay > 86400."""
    if not value:
        return None
    try:
        parts = [int(part) for part in value.split(":")]
        if len(parts) == 2:  # ODPT station-level time fields may omit seconds.
            hour, minute = parts
            second = 0
        elif len(parts) == 3:
            hour, minute, second = parts
        else:
            return None
    except (ValueError, AttributeError):
        return None
    if hour < 0 or not 0 <= minute < 60 or not 0 <= second < 60:
        return None
    return hour * 3600 + minute * 60 + second


def format_service_time(value: int | None) -> str | None:
    if value is None:
        return None
    hour, remainder = divmod(value, 3600)
    minute, second = divmod(remainder, 60)
    return f"{hour:02d}:{minute:02d}:{second:02d}"


def _read_table(archive: zipfile.ZipFile, filename: str, *, required: bool = True) -> list[dict[str, str]]:
    try:
        member = next(name for name in archive.namelist() if name.endswith("/" + filename) or name == filename)
    except StopIteration:
        if required:
            raise FeedError(f"GTFS member missing: {filename}")
        return []
    with archive.open(member) as stream:
        return list(csv.DictReader((line.decode("utf-8-sig") for line in stream)))


def _date_field(value: str, field_name: str) -> date:
    try:
        return date(int(value[:4]), int(value[4:6]), int(value[6:8]))
    except (ValueError, TypeError) as exc:
        raise FeedError(f"Invalid {field_name}: {value!r}") from exc


def _active_services(calendars: list[dict[str, str]], exceptions: list[dict[str, str]], day: date,
                     feed_start: date, feed_end: date) -> set[str]:
    if not feed_start <= day <= feed_end:
        raise FeedDateError(f"{day} is outside feed validity {feed_start}..{feed_end}")
    weekday = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")[day.weekday()]
    active = set()
    for row in calendars:
        if _date_field(row["start_date"], "calendar.start_date") <= day <= _date_field(row["end_date"], "calendar.end_date") and row.get(weekday) == "1":
            active.add(row["service_id"])
    for row in exceptions:
        if _date_field(row["date"], "calendar_dates.date") != day:
            continue
        if row.get("exception_type") == "1":
            active.add(row["service_id"])
        elif row.get("exception_type") == "2":
            active.discard(row["service_id"])
        else:
            raise FeedError(f"Invalid calendar_dates.exception_type: {row.get('exception_type')!r}")
    return active


def _event(row: dict[str, str]) -> StopEvent:
    sequence = row.get("stop_sequence", "")
    try:
        sequence_number = int(sequence)
    except ValueError as exc:
        raise FeedError(f"Invalid stop_sequence: {sequence!r}") from exc
    return StopEvent(
        stop_id=row.get("stop_id", ""),
        station=next((station for station, ids in STATION_STOP_IDS.items() if row.get("stop_id") in ids), None),
        sequence=sequence_number,
        arrival_seconds=parse_gtfs_time(row.get("arrival_time")),
        departure_seconds=parse_gtfs_time(row.get("departure_time")),
        pickup_type=row.get("pickup_type", "0"),
        drop_off_type=row.get("drop_off_type", "0"),
        timepoint=row.get("timepoint") or None,
    )


def _time_event_usable(event: StopEvent, side: str) -> bool:
    if side == "board":
        return event.departure_seconds is not None and event.can_board
    if side == "alight":
        return event.arrival_seconds is not None and event.can_alight
    raise ValueError(side)


def _event_times_monotonic(events: tuple[StopEvent, ...], start_sequence: int, end_sequence: int) -> bool:
    values = [seconds for event in events if start_sequence <= event.sequence <= end_sequence
              for seconds in (event.arrival_seconds, event.departure_seconds) if seconds is not None]
    return all(later >= earlier for earlier, later in zip(values, values[1:]))


class ItineraryGenerator:
    """Reusable in-memory GTFS timetable and itinerary generator."""

    def __init__(self, gtfs_zip: str | Path = DEFAULT_GTFS, odpt_dir: str | Path | None = DEFAULT_DATA_DIR,
                 min_transfer_seconds: int = 60, max_transfer_seconds: int = 600,
                 destination_station_id: str = DEFAULT_DESTINATION_ID):
        if min_transfer_seconds < 0 or max_transfer_seconds < min_transfer_seconds:
            raise ValueError("Transfer limits must satisfy 0 <= minimum <= maximum")
        if destination_station_id not in DESTINATIONS:
            raise ValueError(f"Unknown destination station ID: {destination_station_id}")
        if destination_station_id not in VERIFIED_DESTINATION_IDS:
            raise DestinationNotReadyError(
                f"{DESTINATIONS[destination_station_id]['name']} is cataloged but not journey-validated yet"
            )
        self.destination_station_id = destination_station_id
        self.gtfs_zip = Path(gtfs_zip)
        self.odpt_dir = Path(odpt_dir) if odpt_dir is not None else None
        self.min_transfer_seconds = min_transfer_seconds
        self.max_transfer_seconds = max_transfer_seconds
        self.feed_version = ""
        self.feed_start: date
        self.feed_end: date
        self.stops: dict[str, dict[str, str]] = {}
        self.routes: dict[str, dict[str, str]] = {}
        self.trips: dict[str, dict[str, str]] = {}
        self.events: dict[str, tuple[StopEvent, ...]] = {}
        self.calendars: list[dict[str, str]] = []
        self.exceptions: list[dict[str, str]] = []
        self._odpt_cache: dict[tuple[str, str], dict[str, list[dict[str, Any]]]] = {}
        self._station_lookup_cache: dict[tuple[str, str], str] | None = None
        self.last_wait_histogram: dict[int, int] = {}
        self.last_raw_transfer_pairs = 0
        self.last_destination_status: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        if not self.gtfs_zip.is_file():
            raise FeedError(f"GTFS ZIP not found: {self.gtfs_zip}")
        try:
            with zipfile.ZipFile(self.gtfs_zip) as archive:
                feed_rows = _read_table(archive, "feed_info.txt")
                if not feed_rows:
                    raise FeedError("feed_info.txt has no rows")
                feed = feed_rows[0]
                self.feed_version = feed.get("feed_version", "")
                self.feed_start = _date_field(feed.get("feed_start_date", ""), "feed_start_date")
                self.feed_end = _date_field(feed.get("feed_end_date", ""), "feed_end_date")
                self.calendars = _read_table(archive, "calendar.txt", required=False)
                self.exceptions = _read_table(archive, "calendar_dates.txt", required=False)
                self.stops = {row["stop_id"]: row for row in _read_table(archive, "stops.txt")}
                self.routes = {row["route_id"]: row for row in _read_table(archive, "routes.txt")}
                self.trips = {row["trip_id"]: row for row in _read_table(archive, "trips.txt")}
                by_trip: dict[str, list[StopEvent]] = defaultdict(list)
                for row in _read_table(archive, "stop_times.txt"):
                    by_trip[row["trip_id"]].append(_event(row))
                self.events = {trip_id: tuple(sorted(rows, key=lambda event: event.sequence))
                               for trip_id, rows in by_trip.items()}
        except zipfile.BadZipFile as exc:
            raise FeedError(f"Invalid GTFS ZIP: {self.gtfs_zip}") from exc
        if self.feed_end < self.feed_start:
            raise FeedError("feed_end_date precedes feed_start_date")

    def active_service_ids(self, service_date: str | date) -> set[str]:
        day = parse_service_date(service_date)
        return _active_services(self.calendars, self.exceptions, day, self.feed_start, self.feed_end)

    def _day_calendar(self, active: set[str]) -> str | None:
        categories = {ODPT_CALENDAR[service_id] for service_id in active if service_id in ODPT_CALENDAR}
        return next(iter(categories)) if len(categories) == 1 else None

    def _odpt_index(self, route_id: str, calendar: str | None) -> dict[str, list[dict[str, Any]]]:
        if self.odpt_dir is None or calendar is None:
            return {}
        cache_key = (route_id, calendar)
        if cache_key in self._odpt_cache:
            return self._odpt_cache[cache_key]
        filename = self.odpt_dir / f"TrainTimetable_{LINE_ODPT[route_id]}.json"
        index: dict[str, list[dict[str, Any]]] = defaultdict(list)
        try:
            records = json.loads(filename.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self._odpt_cache[cache_key] = {}
            return {}
        if not isinstance(records, list):
            self._odpt_cache[cache_key] = {}
            return {}
        for record in records:
            if not isinstance(record, dict) or record.get("odpt:calendar", "").rsplit(":", 1)[-1] != calendar:
                continue
            number = record.get("odpt:trainNumber", "")
            if not number:
                continue
            # The first train of a transfer itinerary need not continue to
            # Hikawadai. Match all ODPT train timetables on identity/calendar;
            # the exact Ikebukuro departure is checked below before enrichment.
            index[number].append(record)
        normalized = dict(index)
        self._odpt_cache[cache_key] = normalized
        return normalized

    @staticmethod
    def _odpt_number(trip_id: str) -> str | None:
        # Empirical Phase 3 rule: two-character GTFS prefix and suffix surround
        # the train number. It is applied only to this observed 10-char shape.
        return trip_id[2:-2] if len(trip_id) == 10 else None

    def _build_odpt_matcher(self, trips: dict[str, TripInstance], calendar: str | None):
        if calendar is None or self.odpt_dir is None:
            return None, {}
        from collections import defaultdict as _defaultdict
        from odpt_train_matcher import (  # local import avoids the module cycle
            OdptTrainMatcher,
            odpt_destinations,
            odpt_ikebukuro_departure,
            station_lookup_from_odpt,
        )

        records_by_line = {}
        for route_id in ROUTES:
            records_by_line[LINE_ODPT[route_id]] = [
                record for values in self._odpt_index(route_id, calendar).values()
                for record in values
            ]

        # Build the destination/headsign crosswalk only from the legacy exact
        # ID+departure matches. The candidate trip cannot teach its own mapping.
        destination_heads: dict[str, set[str]] = _defaultdict(set)
        for trip in trips.values():
            number = self._odpt_number(trip.trip_id)
            if number is None or not trip.headsign:
                continue
            matches = [record for record in self._odpt_index(trip.route_id, calendar).get(number, ())
                       if odpt_ikebukuro_departure(record) is not None
                       and odpt_ikebukuro_departure(record) % 86400 == trip.departure_seconds % 86400]
            if len(matches) == 1:
                for station_id in odpt_destinations(matches[0]):
                    destination_heads[station_id].add(trip.headsign)

        if self._station_lookup_cache is None:
            station_path = self.odpt_dir / "Station_all.json"
            try:
                station_rows = json.loads(station_path.read_text(encoding="utf-8"))
                self._station_lookup_cache = station_lookup_from_odpt(station_rows)
            except (OSError, json.JSONDecodeError, TypeError):
                self._station_lookup_cache = {}
        matcher = OdptTrainMatcher(
            records_by_line,
            self._station_lookup_cache,
            destination_heads,
            {stop_id: row.get("stop_name", "") for stop_id, row in self.stops.items()},
        )
        active_ids = {route_id: [trip_id for trip_id, trip in trips.items()
                                 if trip.route_id == route_id]
                      for route_id in ROUTES}
        return matcher, active_ids

    def _enrich(self, trip: TripInstance, calendar: str | None,
                matcher=None, active_trip_ids=()) -> OdptEnrichment:
        if matcher is None:
            return OdptEnrichment("unavailable")
        from odpt_train_matcher import odpt_destinations, type_scope

        match = matcher.match(trip, calendar, active_trip_ids)
        if match.status != "confirmed" or match.odpt_record is None:
            status = "ambiguous" if match.status == "ambiguous" else (
                "unavailable" if match.status == "unavailable" else "unmatched")
            return OdptEnrichment(status, match_method=match.method, match_reason=match.reason)

        record = match.odpt_record
        raw_type = record.get("odpt:trainType")
        type_code = (raw_type or "").rsplit(":", 1)[-1].rsplit(".", 1)[-1] or None
        states = {name: event_state(trip.events, stop_id, trip.origin_event.sequence)
                  for name, stop_id in CRITICAL_STOPS[trip.route_id].items()}
        pattern = classify(trip.route_id, states)
        scope_pattern = pattern
        if trip.route_id == "6" and self._all_stops_to_kotake(trip):
            scope_pattern = "all_stops_to_kotake_segment"
        scope = type_scope(raw_type, trip.route_id, scope_pattern)
        return OdptEnrichment(
            status="unique_match",
            train_type=scope["metro_line_type"],
            destination=tuple(value.rsplit(".", 1)[-1] for value in odpt_destinations(record)),
            service_brand=scope["service_brand"],
            raw_train_type_uri=raw_type,
            reported_train_type=type_code,
            other_operator_type=scope["other_operator_type"],
            unscoped_through_service_type=scope["unscoped_through_service_type"],
            match_method=match.method,
            match_reason=match.reason,
        )

    @staticmethod
    def _all_stops_to_kotake(trip: TripInstance) -> bool:
        if trip.route_id != "6":
            return False
        kotake = next((event for event in trip.events
                       if event.stop_id in ROUTE_STOP_IDS["6"]["kotake_mukaihara"]
                       and event.sequence > trip.origin_event.sequence), None)
        if kotake is None:
            return False
        segment = [event for event in trip.events
                   if trip.origin_event.sequence <= event.sequence <= kotake.sequence]
        return bool(segment) and all(
            (event.arrival_seconds is not None or event.departure_seconds is not None)
            and (event.can_board or event.can_alight)
            for event in segment
        )

    def _yurakucho_rule_eligible(self, trip: TripInstance) -> bool:
        """Check the exact, boardable Ikebukuro-to-Kotake segment before using the line rule."""
        odpt = trip.odpt or OdptEnrichment("unavailable")
        if (trip.route_id != "6" or odpt.status != "unique_match" or odpt.train_type is not None
                or not odpt.raw_train_type_uri or not odpt.reported_train_type or odpt.service_brand
                or odpt.unscoped_through_service_type != odpt.reported_train_type
                or odpt.reported_train_type == "S-TRAIN"):
            return False
        if trip.origin_event.stop_id not in ROUTE_STOP_IDS["6"]["ikebukuro"]:
            return False
        if not _time_event_usable(trip.origin_event, "board"):
            return False

        trip_row = self.trips.get(trip.trip_id, {})
        if any("S-TRAIN" in (trip_row.get(field) or "").upper()
               for field in ("trip_short_name", "trip_headsign", "block_id")):
            return False

        kotake_events = [event for event in trip.events
                         if event.stop_id in ROUTE_STOP_IDS["6"]["kotake_mukaihara"]
                         and event.sequence > trip.origin_event.sequence]
        if len(kotake_events) != 1:
            return False
        kotake = kotake_events[0]
        segment = [event for event in trip.events
                   if trip.origin_event.sequence <= event.sequence <= kotake.sequence]
        if not segment or segment[0] != trip.origin_event or len({event.sequence for event in segment}) != len(segment):
            return False

        required_stops = ("608", "607", "606")  # 要町・千川・小竹向原
        prior_sequence = trip.origin_event.sequence
        for stop_id in required_stops:
            matches = [event for event in segment if event.stop_id == stop_id]
            if len(matches) != 1 or matches[0].sequence <= prior_sequence:
                return False
            event = matches[0]
            if (event.arrival_seconds is None and event.departure_seconds is None) or not (event.can_board or event.can_alight):
                return False
            prior_sequence = event.sequence

        event_times = [seconds for event in segment
                       for seconds in (event.arrival_seconds, event.departure_seconds) if seconds is not None]
        if any(later < earlier for earlier, later in zip(event_times, event_times[1:])):
            return False
        if any((event.arrival_seconds is None and event.departure_seconds is None)
               or not (event.can_board or event.can_alight) for event in segment):
            return False
        return True

    def _resolve_train_type(self, trip: TripInstance) -> TypeResolution:
        origin_sequence = trip.origin_event.sequence
        states = {name: event_state(trip.events, stop_id, origin_sequence)
                  for name, stop_id in CRITICAL_STOPS[trip.route_id].items()}
        pattern = classify(trip.route_id, states)
        odpt = trip.odpt or OdptEnrichment("unavailable")
        route_rule_eligible = self._yurakucho_rule_eligible(trip)
        if trip.route_id == "6" and odpt.train_type == "Local" and self._all_stops_to_kotake(trip):
            pattern = "all_stops_to_kotake_segment"
        elif route_rule_eligible:
            pattern = "all_stops_to_kotake_segment"
        return resolve_type(trip.route_id, odpt.status, odpt.train_type,
                            odpt.service_brand, pattern, states,
                            odpt.reported_train_type,
                            official_route_rule_eligible=route_rule_eligible)

    def _make_trip(self, trip_id: str, row: dict[str, str], day: date, events: tuple[StopEvent, ...]) -> TripInstance | None:
        route_id = row.get("route_id", "")
        if route_id not in ROUTES:
            return None
        route_stops = ROUTE_STOP_IDS[route_id]
        origin = next((event for event in events if event.stop_id in route_stops["ikebukuro"]), None)
        if origin is None or not _time_event_usable(origin, "board"):
            return None
        route_policy = DESTINATIONS[self.destination_station_id]["routePolicy"]
        if route_policy == "direct_and_kotake_transfer":
            # Transfer-capable destinations need every Ikebukuro-to-Kotake trip
            # as a possible incoming or outgoing leg, even when this trip does
            # not itself reach the selected destination.
            kotake = next((event for event in events if event.stop_id in route_stops["kotake_mukaihara"]), None)
            if kotake is None or origin.sequence >= kotake.sequence:
                return None
        else:
            target_order = DESTINATIONS[self.destination_station_id]["outboundOrder"]
            onward_ids = {
                target["routeStopIds"][route_id]
                for target in DESTINATIONS.values()
                if target["outboundOrder"] >= target_order
            }
            if not any(event.stop_id in onward_ids and event.sequence > origin.sequence for event in events):
                return None
        return TripInstance(
            service_date=day.isoformat(), trip_id=trip_id, service_id=row["service_id"], route_id=route_id,
            route_name=self.routes.get(route_id, {}).get("route_long_name") or ROUTES[route_id],
            headsign=row.get("trip_headsign") or None, departure_seconds=origin.departure_seconds or 0,
            departure_text=format_service_time(origin.departure_seconds) or "",
            origin_event=origin, events=events,
        )

    @staticmethod
    def _event_after(events: tuple[StopEvent, ...], station_ids: set[str], sequence: int) -> StopEvent | None:
        return next((event for event in events if event.stop_id in station_ids and event.sequence > sequence), None)

    def generate(self, service_date: str | date) -> list[DepartureResult]:
        day = parse_service_date(service_date)
        destination = DESTINATIONS[self.destination_station_id]
        transfer_enabled = destination["routePolicy"] == "direct_and_kotake_transfer"
        active = self.active_service_ids(day)
        calendar = self._day_calendar(active)
        trips: dict[str, TripInstance] = {}
        scheduled_trip_counts = {route_id: 0 for route_id in ROUTES}
        for trip_id, row in self.trips.items():
            if row.get("service_id") not in active:
                continue
            route_id = row.get("route_id", "")
            if route_id in ROUTES:
                scheduled_trip_counts[route_id] += 1
            instance = self._make_trip(trip_id, row, day, self.events.get(trip_id, ()))
            if instance:
                trips[trip_id] = instance
        matcher, active_trip_ids = self._build_odpt_matcher(trips, calendar)
        enriched = {}
        for trip_id, trip in trips.items():
            trip = replace(trip, odpt=self._enrich(
                trip, calendar, matcher, active_trip_ids.get(trip.route_id, ())))
            enriched[trip_id] = replace(trip, type_resolution=self._resolve_train_type(trip))
        trips = enriched

        direct_by_origin: dict[str, Itinerary] = {}
        best_transfer_by_origin: dict[str, Itinerary] = {}
        transfer_candidate_counts: dict[str, int] = defaultdict(int)
        transfer_wait_policy_excluded: set[str] = set()
        diagnostics: dict[str, set[str]] = defaultdict(set)
        arrivals: dict[str, StopEvent] = {}
        departures: dict[str, StopEvent] = {}
        departure_destinations: dict[str, StopEvent] = {}
        transfer_data_insufficient_trip_ids: set[str] = set()
        transfer_pass_through_count = 0
        route_destination_counts = {
            route_id: {"scheduledTripCount": scheduled_trip_counts[route_id],
                       "originTripCount": 0, "candidateCount": 0, "passThroughCount": 0,
                       "dataInsufficientCount": 0, "transferDataInsufficientCount": 0}
            for route_id in ROUTES
        }
        direct_data_issue_trip_ids: set[str] = set()
        if transfer_enabled:
            for counts in route_destination_counts.values():
                counts.update({"directCandidateCount": 0, "transferCandidateCount": 0,
                               "transferPairCount": 0, "transferOnlyCount": 0})

        for trip_id, trip in trips.items():
            route_stops = ROUTE_STOP_IDS[trip.route_id]
            destination_stop_id = DESTINATIONS[self.destination_station_id]["routeStopIds"][trip.route_id]
            route_destination_counts[trip.route_id]["originTripCount"] += 1
            if self.destination_station_id == DEFAULT_DESTINATION_ID:
                target_order = destination["outboundOrder"]
                station_order = {
                    item["routeStopIds"][trip.route_id]: item["outboundOrder"]
                    for item in DESTINATIONS.values()
                }
                forward_events = [event for event in trip.events
                                  if event.sequence > trip.origin_event.sequence
                                  and event.stop_id in station_order]
                ordered_values = [station_order[event.stop_id] for event in forward_events]
                destination_events = [event for event in forward_events
                                      if event.stop_id == destination_stop_id]
                if ordered_values != sorted(ordered_values):
                    diagnostics[trip_id].add("destination_stop_order_conflict")
                    h_event = None
                elif len(destination_events) > 1:
                    diagnostics[trip_id].add("destination_stop_record_ambiguous")
                    h_event = None
                elif destination_events:
                    h_event = destination_events[0]
                else:
                    # A later listed station proves the trip continues past the
                    # target; do not mistake a missing target row for pass-through.
                    if any(order > target_order for order in ordered_values):
                        diagnostics[trip_id].add("destination_stop_record_missing")
                    h_event = None
            else:
                target_order = DESTINATIONS[self.destination_station_id]["outboundOrder"]
                station_order = {
                    item["routeStopIds"][trip.route_id]: item["outboundOrder"]
                    for item in DESTINATIONS.values()
                }
                forward_events = [event for event in trip.events
                                  if event.sequence > trip.origin_event.sequence
                                  and event.stop_id in station_order]
                ordered_values = [station_order[event.stop_id] for event in forward_events]
                destination_events = [event for event in forward_events
                                      if event.stop_id == destination_stop_id]
                if ordered_values != sorted(ordered_values):
                    diagnostics[trip_id].add("destination_stop_order_conflict")
                    h_event = None
                elif len(destination_events) > 1:
                    diagnostics[trip_id].add("destination_stop_record_ambiguous")
                    h_event = None
                elif destination_events:
                    h_event = destination_events[0]
                else:
                    # A later scheduled station proves the trip continues beyond
                    # the target, but an absent target row is not treated as a pass.
                    if any(order > target_order for order in ordered_values):
                        diagnostics[trip_id].add("destination_stop_record_missing")
                    h_event = None
            if h_event:
                is_phase2_destination = self.destination_station_id != DEFAULT_DESTINATION_ID
                if not is_phase2_destination:
                    # Keep legacy row diagnostics, but count an absent time at an
                    # explicitly non-alightable stop as a known pass, not a gap.
                    diagnostics[trip_id].update(_legacy_destination_event_diagnostics(h_event))
                    if h_event.drop_off_type == "1":
                        route_destination_counts[trip.route_id]["passThroughCount"] += 1
                elif h_event.drop_off_type == "1":
                    diagnostics[trip_id].add("destination_explicit_pass")
                    route_destination_counts[trip.route_id]["passThroughCount"] += 1
                elif h_event.drop_off_type not in ("", "0"):
                    code = ("destination_alighting_restricted" if h_event.drop_off_type in ("2", "3")
                            else "destination_alighting_unknown")
                    diagnostics[trip_id].add(code)
                elif h_event.arrival_seconds is None:
                    diagnostics[trip_id].add("destination_arrival_missing")
                elif is_phase2_destination and h_event.arrival_seconds < trip.departure_seconds:
                    diagnostics[trip_id].add("destination_time_order_conflict")
                elif is_phase2_destination and not _event_times_monotonic(
                        trip.events, trip.origin_event.sequence, h_event.sequence):
                    diagnostics[trip_id].add("destination_time_order_conflict")
                if (not is_phase2_destination and h_event.arrival_seconds is not None and h_event.can_alight) or (
                    is_phase2_destination and h_event.drop_off_type in ("", "0")
                    and h_event.arrival_seconds is not None and "destination_time_order_conflict" not in diagnostics[trip_id]
                ):
                    first = Leg(trip, trip.origin_event, h_event, trip.departure_seconds, h_event.arrival_seconds)
                    direct_by_origin[trip_id] = Itinerary(
                        "direct", trip.departure_seconds, h_event.arrival_seconds, trip.departure_text,
                        format_service_time(h_event.arrival_seconds) or "", first, None, None, None,
                        arrival_station_id=self.destination_station_id,
                    )

            if _destination_data_issues(diagnostics[trip_id]):
                route_destination_counts[trip.route_id]["dataInsufficientCount"] += 1
                direct_data_issue_trip_ids.add(trip_id)
            if not transfer_enabled:
                if trip_id in direct_by_origin:
                    route_destination_counts[trip.route_id]["candidateCount"] += 1
                # Phase 2 is strictly same-trip direct only, including Kotake.
                continue

            k_event = next((event for event in trip.events
                            if event.stop_id in route_stops["kotake_mukaihara"]
                            and event.sequence > trip.origin_event.sequence), None)
            if k_event is None:
                continue
            if self.destination_station_id == DEFAULT_DESTINATION_ID:
                # Preserve the existing default-destination candidate checks.
                if k_event.arrival_seconds is not None and k_event.can_alight:
                    arrivals[trip_id] = k_event
                elif k_event.arrival_seconds is None:
                    diagnostics[trip_id].add("kotake_arrival_missing")
                elif not k_event.can_alight:
                    diagnostics[trip_id].add("kotake_alighting_prohibited")
                if k_event.departure_seconds is None or not k_event.can_board:
                    continue
                h_after_k = self._event_after(
                    trip.events, {destination["routeStopIds"][trip.route_id]}, k_event.sequence)
                if h_after_k and h_after_k.arrival_seconds is not None and h_after_k.can_alight:
                    departures[trip_id] = k_event
                    departure_destinations[trip_id] = h_after_k
            else:
                station_order = {
                    item["routeStopIds"][trip.route_id]: item["outboundOrder"]
                    for item in DESTINATIONS.values()
                }
                before_k = [event for event in trip.events
                            if trip.origin_event.sequence <= event.sequence <= k_event.sequence
                            and event.stop_id in station_order]
                observed_before_order = [station_order[event.stop_id] for event in before_k]
                first_leg_valid = (
                    observed_before_order == sorted(observed_before_order)
                    and len(observed_before_order) == len(set(event.stop_id for event in before_k))
                    and _event_times_monotonic(trip.events, trip.origin_event.sequence, k_event.sequence)
                )
                if k_event.arrival_seconds is not None and k_event.can_alight and first_leg_valid:
                    arrivals[trip_id] = k_event
                elif k_event.arrival_seconds is None:
                    diagnostics[trip_id].add("kotake_arrival_missing")
                    transfer_data_insufficient_trip_ids.add(trip_id)
                elif not k_event.can_alight:
                    diagnostics[trip_id].add("kotake_alighting_prohibited")
                    transfer_data_insufficient_trip_ids.add(trip_id)
                else:
                    diagnostics[trip_id].add("kotake_path_order_conflict")
                    transfer_data_insufficient_trip_ids.add(trip_id)

                if k_event.departure_seconds is None or not k_event.can_board:
                    diagnostics[trip_id].add("kotake_boarding_unavailable")
                    transfer_data_insufficient_trip_ids.add(trip_id)
                    continue

                destination_stop_id = destination["routeStopIds"][trip.route_id]
                target_order = destination["outboundOrder"]
                target_events = [event for event in trip.events
                                 if event.stop_id == destination_stop_id
                                 and event.sequence > k_event.sequence]
                h_after_k = target_events[0] if len(target_events) == 1 else None
                onward_events = [event for event in trip.events
                                 if event.sequence > k_event.sequence
                                 and event.stop_id in station_order]
                onward_order = [station_order[event.stop_id] for event in onward_events]
                invalid_path = (onward_order != sorted(onward_order)
                                or len(onward_order) != len(set(event.stop_id for event in onward_events)))
                if invalid_path:
                    diagnostics[trip_id].add("destination_stop_order_conflict")
                    transfer_data_insufficient_trip_ids.add(trip_id)
                elif len(target_events) > 1:
                    diagnostics[trip_id].add("destination_stop_record_ambiguous")
                    transfer_data_insufficient_trip_ids.add(trip_id)
                elif h_after_k is None:
                    if any(order > target_order for order in onward_order):
                        diagnostics[trip_id].add("destination_stop_record_missing")
                        transfer_data_insufficient_trip_ids.add(trip_id)
                elif h_after_k.drop_off_type == "1":
                    diagnostics[trip_id].add("destination_explicit_pass")
                    transfer_pass_through_count += 1
                elif h_after_k.drop_off_type not in ("", "0"):
                    diagnostics[trip_id].add("destination_alighting_restricted")
                    transfer_data_insufficient_trip_ids.add(trip_id)
                elif h_after_k.arrival_seconds is None:
                    diagnostics[trip_id].add("destination_arrival_missing")
                    transfer_data_insufficient_trip_ids.add(trip_id)
                elif not _event_times_monotonic(trip.events, k_event.sequence, h_after_k.sequence):
                    diagnostics[trip_id].add("destination_time_order_conflict")
                    transfer_data_insufficient_trip_ids.add(trip_id)
                else:
                    departures[trip_id] = k_event
                    departure_destinations[trip_id] = h_after_k

        wait_histogram: dict[int, int] = defaultdict(int)
        raw_pairs = 0
        for in_id, in_event in arrivals.items():
            in_trip = trips[in_id]
            for out_id, out_event in departures.items():
                out_trip = trips[out_id]
                if in_id == out_id:
                    # Same trip is continuation and never a transfer leg.
                    continue
                if out_trip.route_id != OPPOSITE_ROUTE[in_trip.route_id]:
                    continue
                wait = out_event.departure_seconds - in_event.arrival_seconds
                if wait < 0:
                    continue
                if wait > self.max_transfer_seconds:
                    h_event = departure_destinations.get(out_id)
                    if h_event is not None and h_event.arrival_seconds is not None and h_event.can_alight:
                        transfer_wait_policy_excluded.add(in_id)
                    continue
                wait_histogram[wait] += 1
                raw_pairs += 1
                if not _transfer_wait_in_bounds(wait, self.min_transfer_seconds,
                                                self.max_transfer_seconds):
                    continue
                h_event = departure_destinations.get(out_id)
                if h_event is None or h_event.arrival_seconds is None or not h_event.can_alight:
                    continue
                first = Leg(in_trip, in_trip.origin_event, in_event, in_trip.departure_seconds, in_event.arrival_seconds)
                second = Leg(out_trip, out_event, h_event, out_event.departure_seconds, h_event.arrival_seconds)
                candidate = Itinerary(
                    "transfer", in_trip.departure_seconds, h_event.arrival_seconds, in_trip.departure_text,
                    format_service_time(h_event.arrival_seconds) or "", first, second, "小竹向原", wait,
                    arrival_station_id=self.destination_station_id,
                )
                transfer_candidate_counts[in_id] += 1
                current = best_transfer_by_origin.get(in_id)
                candidate_key = (candidate.arrival_seconds, candidate.transfer_wait_seconds or 0,
                                 candidate.second_leg.trip.trip_id if candidate.second_leg else "")
                current_key = ((current.arrival_seconds, current.transfer_wait_seconds or 0,
                                current.second_leg.trip.trip_id if current.second_leg else "")
                               if current else None)
                if current_key is None or candidate_key < current_key:
                    best_transfer_by_origin[in_id] = candidate
        self.last_wait_histogram = dict(wait_histogram)
        self.last_raw_transfer_pairs = raw_pairs

        results: list[DepartureResult] = []
        for trip_id, trip in trips.items():
            direct = direct_by_origin.get(trip_id)
            best_transfer = best_transfer_by_origin.get(trip_id)
            primary = choose_primary(direct, best_transfer)
            if primary:
                status = "ok" if direct else "transfer_only"
            else:
                status = "no_valid_arrival"
            enrichment = trip.odpt or OdptEnrichment("unavailable")
            data_quality = sorted(diagnostics.get(trip_id, set()))
            if not direct and "destination_arrival_missing" in data_quality:
                data_quality.append("direct_arrival_unavailable")
            type_resolution = trip.type_resolution or self._resolve_train_type(trip)
            if not primary and type_resolution.source == "official_route_rule":
                # Do not label a non-displayable trip from a partial route record.
                # The route fallback is reserved for departures with a validated
                # Ikebukuro-to-Hikawadai itinerary in this preview.
                type_resolution = replace(
                    type_resolution,
                    train_type=None,
                    label="種別不明",
                    source="unknown",
                    validation="unverifiable",
                    diagnostic="official_route_rule_requires_valid_hikawadai_itinerary",
                )
            results.append(DepartureResult(
                service_date=day.isoformat(), origin_trip_id=trip_id, route_id=trip.route_id,
                route_name=trip.route_name, departure_seconds=trip.departure_seconds,
                departure_text=trip.departure_text, headsign=trip.headsign, odpt=enrichment,
                type_resolution=type_resolution,
                primary_itinerary=primary, direct_alternative=direct, best_transfer_alternative=best_transfer,
                transfer_candidates_count=transfer_candidate_counts.get(trip_id, 0),
                status=status, data_quality=data_quality,
                transfer_wait_policy_excluded=(trip_id in transfer_wait_policy_excluded and primary is None),
            ))
        if transfer_enabled:
            transfer_data_insufficient_count = len(
                transfer_data_insufficient_trip_ids - direct_data_issue_trip_ids)
            direct_candidate_count = sum(row.direct_alternative is not None for row in results)
            transfer_candidate_count = sum(row.best_transfer_alternative is not None for row in results)
            transfer_pair_count = sum(row.transfer_candidates_count for row in results)
            transfer_only_count = sum(
                row.direct_alternative is None and row.best_transfer_alternative is not None
                for row in results
            )
            candidate_count = sum(row.primary_itinerary is not None for row in results)
            direct_insufficient_count = sum(
                counts["dataInsufficientCount"] for counts in route_destination_counts.values())
            insufficient_count = direct_insufficient_count + transfer_data_insufficient_count
            for result in results:
                counts = route_destination_counts[result.route_id]
                counts["candidateCount"] += result.primary_itinerary is not None
                counts["directCandidateCount"] += result.direct_alternative is not None
                counts["transferCandidateCount"] += result.best_transfer_alternative is not None
                counts["transferPairCount"] += result.transfer_candidates_count
                counts["transferOnlyCount"] += (
                    result.direct_alternative is None and result.best_transfer_alternative is not None)
            transfer_issues_by_route = {route_id: 0 for route_id in ROUTES}
            for trip_id in transfer_data_insufficient_trip_ids - direct_data_issue_trip_ids:
                issue_trip = trips.get(trip_id)
                if issue_trip is not None:
                    transfer_issues_by_route[issue_trip.route_id] += 1
            for route_id, count in transfer_issues_by_route.items():
                route_destination_counts[route_id]["transferDataInsufficientCount"] = count
            status = ("normal" if candidate_count else
                      "data_insufficient" if insufficient_count else "no_candidates")
            self.last_destination_status = {
                "status": status,
                "candidateCount": candidate_count,
                "directCandidateCount": direct_candidate_count,
                "transferCandidateCount": transfer_candidate_count,
                "transferPairCount": transfer_pair_count,
                "transferOnlyCount": transfer_only_count,
                "passThroughCount": sum(row["passThroughCount"] for row in route_destination_counts.values()),
                "transferPassThroughCount": transfer_pass_through_count,
                "dataInsufficientCount": insufficient_count,
                "transferDataInsufficientCount": transfer_data_insufficient_count,
                "routes": route_destination_counts,
            }
        else:
            candidate_count = sum(row["candidateCount"] for row in route_destination_counts.values())
            pass_count = sum(row["passThroughCount"] for row in route_destination_counts.values())
            insufficient_count = sum(row["dataInsufficientCount"] for row in route_destination_counts.values())
            status = ("normal" if candidate_count else
                      "data_insufficient" if insufficient_count else "no_candidates")
            self.last_destination_status = {
                "status": status,
                "candidateCount": candidate_count,
                "passThroughCount": pass_count,
                "dataInsufficientCount": insufficient_count,
                "routes": route_destination_counts,
            }
        return sorted(results, key=lambda result: (result.departure_seconds, result.route_id, result.origin_trip_id))


def _type_resolution_dict(resolution: TypeResolution | None) -> dict[str, Any] | None:
    if resolution is None:
        return None
    return {
        "train_type": resolution.train_type,
        "reported_train_type": resolution.reported_train_type,
        "service_brand": resolution.service_brand,
        "label": resolution.label,
        "source": resolution.source,
        "stop_pattern": resolution.stop_pattern,
        "pattern_states": dict(resolution.pattern_states),
        "validation": resolution.validation,
        "diagnostic": resolution.diagnostic,
    }


def to_dict(result: DepartureResult) -> dict[str, Any]:
    """Compact JSON-friendly DTO; excludes unrelated stops and raw source JSON."""
    def event_dict(event: StopEvent) -> dict[str, Any]:
        return {
            "stop_id": event.stop_id,
            "station": event.station,
            "sequence": event.sequence,
            "arrival_seconds": event.arrival_seconds,
            "departure_seconds": event.departure_seconds,
            "pickup_type": event.pickup_type,
            "drop_off_type": event.drop_off_type,
            "timepoint": event.timepoint,
        }

    def trip_dict(trip: TripInstance) -> dict[str, Any]:
        odpt = trip.odpt or OdptEnrichment("unavailable")
        return {
            "service_date": trip.service_date,
            "trip_id": trip.trip_id,
            "service_id": trip.service_id,
            "route_id": trip.route_id,
            "route_name": trip.route_name,
            "headsign": trip.headsign,
            "departure_seconds": trip.departure_seconds,
            "departure_text": trip.departure_text,
            "odpt": {
                "status": odpt.status,
                "train_type": odpt.train_type,
                "destination": list(odpt.destination),
                "service_brand": odpt.service_brand,
                "raw_train_type_uri": odpt.raw_train_type_uri,
                "reported_train_type": odpt.reported_train_type,
                "other_operator_type": odpt.other_operator_type,
                "unscoped_through_service_type": odpt.unscoped_through_service_type,
                "match_method": odpt.match_method,
                "match_reason": odpt.match_reason,
            },
            "type_resolution": _type_resolution_dict(trip.type_resolution),
        }

    def leg_dict(leg: Leg | None) -> dict[str, Any] | None:
        if leg is None:
            return None
        return {
            "trip": trip_dict(leg.trip),
            "board": event_dict(leg.board),
            "alight": event_dict(leg.alight),
            "board_seconds": leg.board_seconds,
            "alight_seconds": leg.alight_seconds,
        }

    def itinerary_dict(itinerary: Itinerary | None) -> dict[str, Any] | None:
        if itinerary is None:
            return None
        return {
            "kind": itinerary.kind,
            "departure_seconds": itinerary.departure_seconds,
            "arrival_seconds": itinerary.arrival_seconds,
            "departure_text": itinerary.departure_text,
            "arrival_text": itinerary.arrival_text,
            "first_leg": leg_dict(itinerary.first_leg),
            "second_leg": leg_dict(itinerary.second_leg),
            "transfer_station": itinerary.transfer_station,
            "transfer_wait_seconds": itinerary.transfer_wait_seconds,
            "platform_status": itinerary.platform_status,
            "connection_guaranteed": itinerary.connection_guaranteed,
        }

    return {
        "service_date": result.service_date,
        "origin_trip_id": result.origin_trip_id,
        "route_id": result.route_id,
        "route_name": result.route_name,
        "departure_seconds": result.departure_seconds,
        "departure_text": result.departure_text,
        "headsign": result.headsign,
        "odpt": {
            "status": result.odpt.status,
            "train_type": result.odpt.train_type,
            "destination": list(result.odpt.destination),
            "service_brand": result.odpt.service_brand,
            "raw_train_type_uri": result.odpt.raw_train_type_uri,
            "reported_train_type": result.odpt.reported_train_type,
            "other_operator_type": result.odpt.other_operator_type,
            "unscoped_through_service_type": result.odpt.unscoped_through_service_type,
            "match_method": result.odpt.match_method,
            "match_reason": result.odpt.match_reason,
        },
        "type_resolution": _type_resolution_dict(result.type_resolution),
        "primary_itinerary": itinerary_dict(result.primary_itinerary),
        "direct_alternative": itinerary_dict(result.direct_alternative),
        "best_transfer_alternative": itinerary_dict(result.best_transfer_alternative),
        "transfer_candidates_count": result.transfer_candidates_count,
        "status": result.status,
        "data_quality": list(result.data_quality),
    }
