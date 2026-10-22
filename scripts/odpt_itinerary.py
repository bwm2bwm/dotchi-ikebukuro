#!/usr/bin/env python3
"""Build local, date-specific Ikebukuro–Hikawadai itineraries from Tokyo Metro GTFS.

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


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = ROOT / "local_data" / "odpt"
DEFAULT_GTFS = DEFAULT_DATA_DIR / "TokyoMetro-Train-GTFS.zip"

ROUTES = {"6": "有楽町線", "9": "副都心線"}
OPPOSITE_ROUTE = {"6": "9", "9": "6"}
STATION_STOP_IDS = {
    "ikebukuro": {"228", "609", "909"},
    "kotake_mukaihara": {"606", "906"},
    "hikawadai": {"605", "905"},
}
ROUTE_STOP_IDS = {
    "6": {"ikebukuro": {"228", "609"}, "kotake_mukaihara": {"606"}, "hikawadai": {"605"}},
    "9": {"ikebukuro": {"228", "909"}, "kotake_mukaihara": {"906"}, "hikawadai": {"905"}},
}
LINE_ODPT = {"6": "Yurakucho", "9": "Fukutoshin"}
ODPT_CALENDAR = {"0": "Weekday", "1": "SaturdayHoliday"}


class FeedError(ValueError):
    """Invalid or unsupported GTFS feed."""


class FeedDateError(ValueError):
    """Requested service date is outside the feed validity period."""


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


@dataclass(frozen=True)
class OdptEnrichment:
    status: str  # unique_match | unmatched | ambiguous | unavailable
    train_type: str | None = None
    destination: tuple[str, ...] = ()


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
    primary_itinerary: Itinerary | None
    direct_alternative: Itinerary | None
    best_transfer_alternative: Itinerary | None
    transfer_candidates_count: int
    status: str
    data_quality: list[str] = field(default_factory=list)


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


class ItineraryGenerator:
    """Reusable in-memory GTFS timetable and itinerary generator."""

    def __init__(self, gtfs_zip: str | Path = DEFAULT_GTFS, odpt_dir: str | Path | None = DEFAULT_DATA_DIR,
                 min_transfer_seconds: int = 60, max_transfer_seconds: int = 600):
        if min_transfer_seconds < 0 or max_transfer_seconds < min_transfer_seconds:
            raise ValueError("Transfer limits must satisfy 0 <= minimum <= maximum")
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
        self.last_wait_histogram: dict[int, int] = {}
        self.last_raw_transfer_pairs = 0
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
            objects = record.get("odpt:trainTimetableObject", [])
            names = [
                (item.get("odpt:departureStation") or item.get("odpt:arrivalStation", "")).rsplit(".", 1)[-1]
                for item in objects
            ]
            if "Ikebukuro" not in names or "Hikawadai" not in names or names.index("Ikebukuro") >= names.index("Hikawadai"):
                continue
            index[number].append(record)
        normalized = dict(index)
        self._odpt_cache[cache_key] = normalized
        return normalized

    @staticmethod
    def _odpt_number(trip_id: str) -> str | None:
        # Empirical Phase 3 rule: two-character GTFS prefix and suffix surround
        # the train number. It is applied only to this observed 10-char shape.
        return trip_id[2:-2] if len(trip_id) == 10 else None

    def _enrich(self, trip: TripInstance, calendar: str | None) -> OdptEnrichment:
        number = self._odpt_number(trip.trip_id)
        if number is None or calendar is None or self.odpt_dir is None:
            return OdptEnrichment("unavailable")
        matches = self._odpt_index(trip.route_id, calendar).get(number, [])
        if not matches:
            return OdptEnrichment("unmatched")
        if len(matches) != 1:
            return OdptEnrichment("ambiguous")
        record = matches[0]
        objects = record.get("odpt:trainTimetableObject", [])
        ike_obj = next((obj for obj in objects if
                        (obj.get("odpt:departureStation") or "").rsplit(".", 1)[-1] == "Ikebukuro"), None)
        gtfs_time = trip.departure_seconds % 86400
        odpt_time = parse_gtfs_time((ike_obj or {}).get("odpt:departureTime"))
        if odpt_time is None or odpt_time % 86400 != gtfs_time:
            # Keep the evidence-based unique ID match visible, but do not enrich
            # when its independent Ikebukuro time check disagrees.
            return OdptEnrichment("unmatched")
        train_type = record.get("odpt:trainType", "").rsplit(".", 1)[-1] or None
        destination = record.get("odpt:destinationStation", [])
        if isinstance(destination, str):
            destination = [destination]
        destinations = tuple(str(value).rsplit(".", 1)[-1] for value in destination if value)
        return OdptEnrichment("unique_match", train_type, destinations)

    def _make_trip(self, trip_id: str, row: dict[str, str], day: date, events: tuple[StopEvent, ...]) -> TripInstance | None:
        route_id = row.get("route_id", "")
        if route_id not in ROUTES:
            return None
        route_stops = ROUTE_STOP_IDS[route_id]
        origin = next((event for event in events if event.stop_id in route_stops["ikebukuro"]), None)
        if origin is None or not _time_event_usable(origin, "board"):
            return None
        kotake = next((event for event in events if event.stop_id in route_stops["kotake_mukaihara"]), None)
        if kotake is None or origin.sequence >= kotake.sequence:
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
        active = self.active_service_ids(day)
        calendar = self._day_calendar(active)
        trips: dict[str, TripInstance] = {}
        for trip_id, row in self.trips.items():
            if row.get("service_id") not in active:
                continue
            instance = self._make_trip(trip_id, row, day, self.events.get(trip_id, ()))
            if instance:
                trips[trip_id] = instance
        trips = {trip_id: replace(trip, odpt=self._enrich(trip, calendar))
                 for trip_id, trip in trips.items()}

        direct_by_origin: dict[str, Itinerary] = {}
        transfer_by_origin: dict[str, list[Itinerary]] = defaultdict(list)
        diagnostics: dict[str, set[str]] = defaultdict(set)
        arrivals: dict[str, StopEvent] = {}
        departures: dict[str, StopEvent] = {}

        for trip_id, trip in trips.items():
            route_stops = ROUTE_STOP_IDS[trip.route_id]
            h_event = self._event_after(trip.events, route_stops["hikawadai"], trip.origin_event.sequence)
            if h_event:
                if h_event.arrival_seconds is None:
                    diagnostics[trip_id].add("destination_arrival_missing")
                if not h_event.can_alight:
                    diagnostics[trip_id].add("destination_alighting_prohibited")
                if h_event.arrival_seconds is not None and h_event.can_alight:
                    first = Leg(trip, trip.origin_event, h_event, trip.departure_seconds, h_event.arrival_seconds)
                    direct_by_origin[trip_id] = Itinerary(
                        "direct", trip.departure_seconds, h_event.arrival_seconds, trip.departure_text,
                        format_service_time(h_event.arrival_seconds) or "", first, None, None, None,
                    )

            k_event = next((event for event in trip.events
                            if event.stop_id in route_stops["kotake_mukaihara"]
                            and event.sequence > trip.origin_event.sequence), None)
            if k_event is None:
                continue
            if k_event.arrival_seconds is not None and k_event.can_alight:
                arrivals[trip_id] = k_event
            elif k_event.arrival_seconds is None:
                diagnostics[trip_id].add("kotake_arrival_missing")
            elif not k_event.can_alight:
                diagnostics[trip_id].add("kotake_alighting_prohibited")

            if k_event.departure_seconds is not None and k_event.can_board:
                h_after_k = self._event_after(trip.events, route_stops["hikawadai"], k_event.sequence)
                if h_after_k and h_after_k.arrival_seconds is not None and h_after_k.can_alight:
                    departures[trip_id] = k_event

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
                if wait < 0 or wait > self.max_transfer_seconds:
                    continue
                wait_histogram[wait] += 1
                raw_pairs += 1
                if wait < self.min_transfer_seconds:
                    continue
                h_event = self._event_after(out_trip.events, ROUTE_STOP_IDS[out_trip.route_id]["hikawadai"], out_event.sequence)
                if h_event is None or h_event.arrival_seconds is None or not h_event.can_alight:
                    continue
                first = Leg(in_trip, in_trip.origin_event, in_event, in_trip.departure_seconds, in_event.arrival_seconds)
                second = Leg(out_trip, out_event, h_event, out_event.departure_seconds, h_event.arrival_seconds)
                transfer_by_origin[in_id].append(Itinerary(
                    "transfer", in_trip.departure_seconds, h_event.arrival_seconds, in_trip.departure_text,
                    format_service_time(h_event.arrival_seconds) or "", first, second, "小竹向原", wait,
                ))
        self.last_wait_histogram = dict(wait_histogram)
        self.last_raw_transfer_pairs = raw_pairs

        results: list[DepartureResult] = []
        for trip_id, trip in trips.items():
            direct = direct_by_origin.get(trip_id)
            transfers = sorted(transfer_by_origin.get(trip_id, []), key=lambda item: (
                item.arrival_seconds, item.transfer_wait_seconds or 0,
                item.second_leg.trip.trip_id if item.second_leg else "",
            ))
            best_transfer = transfers[0] if transfers else None
            primary = choose_primary(direct, best_transfer)
            if primary:
                status = "ok" if direct else "transfer_only"
            else:
                status = "no_valid_arrival"
            enrichment = trip.odpt or OdptEnrichment("unavailable")
            data_quality = sorted(diagnostics.get(trip_id, set()))
            if not direct and "destination_arrival_missing" in data_quality:
                data_quality.append("direct_arrival_unavailable")
            results.append(DepartureResult(
                service_date=day.isoformat(), origin_trip_id=trip_id, route_id=trip.route_id,
                route_name=trip.route_name, departure_seconds=trip.departure_seconds,
                departure_text=trip.departure_text, headsign=trip.headsign, odpt=enrichment,
                primary_itinerary=primary, direct_alternative=direct, best_transfer_alternative=best_transfer,
                transfer_candidates_count=len(transfers), status=status, data_quality=data_quality,
            ))
        return sorted(results, key=lambda result: (result.departure_seconds, result.route_id, result.origin_trip_id))


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
            },
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
        },
        "primary_itinerary": itinerary_dict(result.primary_itinerary),
        "direct_alternative": itinerary_dict(result.direct_alternative),
        "best_transfer_alternative": itinerary_dict(result.best_transfer_alternative),
        "transfer_candidates_count": result.transfer_candidates_count,
        "status": result.status,
        "data_quality": list(result.data_quality),
    }
