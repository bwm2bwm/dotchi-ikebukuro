"""Evidence-gated matching of Tokyo Metro GTFS trips to saved ODPT timetables.

Offline only. The normalizer is deliberately limited to the trip_id forms
observed in the supplied GTFS feed; a unique spelling/time candidate is not
itself treated as a confirmed match.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Iterable

from odpt_itinerary import LINE_ODPT, ROUTES, StopEvent, TripInstance, parse_gtfs_time

_TRIP_ID = re.compile(r"^(?P<prefix>\d{2})(?P<letter>[A-Z])(?P<digits>\d{4})(?P<suffix_letter>[A-Z])(?P<tail>\d{2})$")
_DAY_MARKER = {"0": "Weekday", "1": "Weekday", "2": "SaturdayHoliday", "3": "SaturdayHoliday"}
_ROUTE_MARKER = {"6": "6", "9": "9"}


@dataclass(frozen=True)
class ParsedTripNumber:
    raw_trip_id: str
    route_id: str
    calendar: str
    number_core: str
    tail: str
    candidates: tuple[str, ...]


@dataclass(frozen=True)
class MatchResult:
    status: str  # confirmed | ambiguous | candidate_unconfirmed | unmatched | unavailable
    reason: str
    candidates: tuple[str, ...] = ()  # ODPT train numbers, for diagnostics only
    odpt_record: dict[str, Any] | None = None
    method: str | None = None

    @property
    def raw_train_type(self) -> str | None:
        """Original ODPT trainType URI, without shortening or relabeling."""
        return (self.odpt_record or {}).get("odpt:trainType")


def parse_trip_number(trip_id: str, route_id: str) -> ParsedTripNumber | None:
    """Parse only feed-observed ID structure and return evidence-based spellings."""
    match = _TRIP_ID.fullmatch(trip_id or "")
    if not match or route_id not in _ROUTE_MARKER:
        return None
    prefix = match.group("prefix")
    if prefix[0] != route_id or prefix[1] not in _DAY_MARKER:
        return None
    tail = match.group("tail")
    # In this feed 00 is padding; the single 20 ID encodes the additional
    # terminal 2 in ODPT's number. No other suffix forms are generalized.
    if tail == "00":
        number_core = f"{match.group('letter')}{match.group('digits')}{match.group('suffix_letter')}"
    elif tail == "20":
        number_core = f"{match.group('letter')}{match.group('digits')}{match.group('suffix_letter')}2"
    else:
        return None
    numeric = re.search(r"\d+", number_core)
    if not numeric:
        return None
    no_leading_zero = (number_core[:numeric.start()] +
                       numeric.group().lstrip("0") +
                       number_core[numeric.end():])
    if not no_leading_zero:
        no_leading_zero = number_core
    candidates = tuple(dict.fromkeys((number_core, no_leading_zero)))
    return ParsedTripNumber(trip_id, route_id, _DAY_MARKER[prefix[1]],
                            number_core, tail, candidates)


def odpt_ikebukuro_departure(record: dict[str, Any]) -> int | None:
    for item in record.get("odpt:trainTimetableObject", ()):
        station = (item.get("odpt:departureStation") or "").rsplit(".", 1)[-1]
        if station == "Ikebukuro":
            return parse_gtfs_time(item.get("odpt:departureTime"))
    return None


def odpt_destinations(record: dict[str, Any]) -> tuple[str, ...]:
    raw = record.get("odpt:destinationStation", ())
    if isinstance(raw, str):
        raw = (raw,)
    if not isinstance(raw, (list, tuple)):
        return ()
    return tuple(str(value) for value in raw if value)


def odpt_route_station_sequence(record: dict[str, Any], route_id: str) -> tuple[str, ...]:
    """Return station IDs for the Metro route segment, preserving stop order."""
    station_prefix = f"odpt.Station:TokyoMetro.{LINE_ODPT[route_id]}."
    result: list[str] = []
    for item in record.get("odpt:trainTimetableObject", ()):
        for key in ("odpt:departureStation", "odpt:arrivalStation"):
            station = item.get(key)
            if station and station.startswith(station_prefix):
                if not result or result[-1] != station:
                    result.append(station)
    return tuple(result)


def gtfs_route_station_sequence(events: Iterable[StopEvent], station_lookup: dict[tuple[str, str], str],
                                route_id: str, stop_names: dict[str, str] | None = None) -> tuple[str, ...] | None:
    """Map GTFS stop names to route-specific ODPT IDs; None means unverified."""
    result = []
    for event in events:
        # ODPT train timetables list scheduled stops, while GTFS includes
        # pass-through stop_times rows with blank times and pickup/drop-off=1.
        if (event.arrival_seconds is None and event.departure_seconds is None) or (
                not event.can_board and not event.can_alight):
            continue
        name = (stop_names or {}).get(event.stop_id) or event.station
        if name is None:
            continue
        station_id = station_lookup.get((route_id, name))
        if station_id is None:
            return None
        if not result or result[-1] != station_id:
            result.append(station_id)
    return tuple(result)


class OdptTrainMatcher:
    """Batch matcher using route, calendar, number, exact departure, destination and stop order."""

    def __init__(self, odpt_records: dict[str, list[dict[str, Any]]],
                 station_lookup: dict[tuple[str, str], str],
                 destination_headsigns: dict[str, set[str]] | None = None,
                 stop_names: dict[str, str] | None = None):
        self.odpt_records = odpt_records
        self.station_lookup = station_lookup
        self.destination_headsigns = destination_headsigns or {}
        self.stop_names = stop_names or {}

    def match(self, trip: TripInstance, calendar: str | None,
              active_gtfs_ids: Iterable[str] = ()) -> MatchResult:
        parsed = parse_trip_number(trip.trip_id, trip.route_id)
        if not parsed or not calendar:
            return MatchResult("unavailable", "trip_id_structure_or_service_calendar_unavailable")
        if parsed.calendar != calendar:
            return MatchResult("unmatched", "trip_id_calendar_marker_conflicts_with_active_service")
        line = LINE_ODPT[trip.route_id]
        records = [r for r in self.odpt_records.get(line, ())
                   if (r.get("odpt:calendar") or "").rsplit(":", 1)[-1] == calendar
                   and (r.get("odpt:railway") or "").rsplit(".", 1)[-1] == line]
        number_hits = [r for r in records if r.get("odpt:trainNumber") in parsed.candidates]
        time_hits = [r for r in number_hits
                     if odpt_ikebukuro_departure(r) is not None
                     and odpt_ikebukuro_departure(r) == trip.departure_seconds % 86400]
        numbers = tuple(sorted({str(r.get("odpt:trainNumber")) for r in time_hits}))
        if not time_hits:
            return MatchResult("unmatched", "no_route_calendar_number_and_exact_departure_candidate", numbers)
        if len(time_hits) != 1:
            return MatchResult("ambiguous", "multiple_route_calendar_number_and_exact_departure_candidates", numbers)
        candidate = time_hits[0]

        # Detect alias collisions among active GTFS trips that could map to the
        # same ODPT number on this route/calendar/time, including exact spellings.
        competing = []
        active_ids = set(active_gtfs_ids)
        for other_id in active_ids:
            if other_id == trip.trip_id:
                continue
            other = parse_trip_number(other_id, trip.route_id)
            if other and candidate.get("odpt:trainNumber") in other.candidates:
                competing.append(other_id)
        if competing:
            return MatchResult("ambiguous", "normalized_number_collides_with_other_active_gtfs_trip", numbers)

        mapped_heads = {head for dest in odpt_destinations(candidate)
                        for head in self.destination_headsigns.get(dest, set())}
        if not mapped_heads:
            return MatchResult("candidate_unconfirmed", "destination_has_no_independent_gtfs_crosswalk", numbers)
        if trip.headsign not in mapped_heads:
            return MatchResult("candidate_unconfirmed", "destination_headsign_conflict", numbers)

        gtfs_stops = gtfs_route_station_sequence(trip.events, self.station_lookup, trip.route_id,
                                                self.stop_names)
        odpt_stops = odpt_route_station_sequence(candidate, trip.route_id)
        if gtfs_stops is None or not gtfs_stops:
            return MatchResult("candidate_unconfirmed", "gtfs_stop_order_not_fully_mappable", numbers)
        if gtfs_stops != odpt_stops:
            return MatchResult("candidate_unconfirmed", "ordered_stop_sequence_conflict", numbers)
        return MatchResult("confirmed", "route_calendar_number_exact_time_destination_and_stop_order_match",
                           numbers, candidate, "normalized_number+exact_time+destination+stop_order")


def station_lookup_from_odpt(station_records: list[dict[str, Any]]) -> dict[tuple[str, str], str]:
    """Build route-scoped Japanese stop-name mapping from saved Station_all.json."""
    result = {}
    for record in station_records:
        railway = (record.get("odpt:railway") or "").rsplit(".", 1)[-1]
        route_id = next((key for key, value in LINE_ODPT.items() if value == railway), None)
        title = (record.get("odpt:stationTitle") or {}).get("ja")
        same_as = record.get("owl:sameAs")
        if route_id and title and same_as:
            key = (route_id, title)
            if key in result and result[key] != same_as:
                # Do not silently resolve duplicate same-name route stations.
                result.pop(key, None)
            elif key not in result:
                result[key] = same_as
    return result


def type_scope(raw_type: str | None, route_id: str, metro_pattern: str | None = None) -> dict[str, str | None]:
    """Keep ODPT source code, Metro-local class and service brand separate."""
    type_code = (raw_type or "").rsplit(":", 1)[-1].rsplit(".", 1)[-1] or None
    brand = "F-Liner" if type_code == "F-Liner" else None
    metro = None
    scope = "scope_unresolved"
    if route_id == "9" and type_code in {"Local", "CommuterExpress", "Express"}:
        metro, scope = type_code, "Fukutoshin_line_type"
    elif route_id == "9" and type_code == "F-Liner":
        scope = "Fukutoshin_service_brand; Metro_class_requires_stop_pattern"
    elif route_id == "6" and type_code == "Local" and metro_pattern in {
            "all_stops_metro_section", "all_stops_to_kotake_segment"}:
        metro, scope = "Local", "Yurakucho_all_stops_pattern_confirmed"
    elif route_id == "9" and type_code is not None:
        scope = "not_validated_as_Fukutoshin_line_type"
    return {"odpt_raw_type": raw_type, "type_code": type_code,
            "metro_line_type": metro, "other_operator_type": None,
            "unscoped_through_service_type": type_code,
            "service_brand": brand, "type_scope": scope}
