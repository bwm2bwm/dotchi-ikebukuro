#!/usr/bin/env python3
"""Offline validation of ODPT train-type matching for generated itineraries."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import date
import json
from pathlib import Path
import sys

from odpt_itinerary import DEFAULT_DATA_DIR, DEFAULT_GTFS, ItineraryGenerator, parse_gtfs_time


REPRESENTATIVE_DATES = ("2026-10-22", "2026-10-24", "2026-11-03")
LINE_NAME = {"6": "Yurakucho", "9": "Fukutoshin"}
SERVICE_CALENDAR = {"0": "Weekday", "1": "SaturdayHoliday"}


def destinations(record: dict) -> list[str]:
    raw = record.get("odpt:destinationStation", [])
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    return [str(item).rsplit(".", 1)[-1] for item in raw if item]


def ikebukuro_departure(record: dict) -> int | None:
    for item in record.get("odpt:trainTimetableObject", []):
        station = (item.get("odpt:departureStation") or "").rsplit(".", 1)[-1]
        if station == "Ikebukuro":
            return parse_gtfs_time(item.get("odpt:departureTime"))
    return None


def load_odpt(data_dir: Path) -> dict[str, list[dict]]:
    loaded = {}
    for line in LINE_NAME.values():
        path = data_dir / f"TrainTimetable_{line}.json"
        loaded[line] = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(loaded[line], list):
            raise ValueError(f"ODPT timetable must be a JSON array: {path.name}")
    return loaded


def indexed_records(odpt: dict[str, list[dict]], line: str, calendar: str) -> list[dict]:
    return [record for record in odpt[line]
            if record.get("odpt:calendar", "").rsplit(":", 1)[-1] == calendar]


def gtfs_trip_candidates(generator: ItineraryGenerator, day: date, active: set[str]):
    calendar = generator._day_calendar(active)
    for trip_id, row in generator.trips.items():
        if row.get("service_id") not in active or row.get("route_id") not in LINE_NAME:
            continue
        trip = generator._make_trip(trip_id, row, day, generator.events.get(trip_id, ()))
        if trip is not None:
            yield trip, calendar


def exact_id_record(odpt, trip, calendar):
    if not calendar:
        return None, "unavailable"
    line = LINE_NAME[trip.route_id]
    number = ItineraryGenerator._odpt_number(trip.trip_id)
    candidates = [record for record in indexed_records(odpt, line, calendar)
                  if record.get("odpt:trainNumber") == number]
    if not candidates:
        return None, "unmatched"
    if len(candidates) != 1:
        return None, "ambiguous"
    record = candidates[0]
    odpt_time = ikebukuro_departure(record)
    if odpt_time is None or odpt_time % 86400 != trip.departure_seconds % 86400:
        return None, "time_mismatch"
    return record, "unique_id_and_time"


def holdout_destination_map(generator, odpt, dates, held_out):
    """Learn ODPT destination IDs from exact ID+time pairs on other dates."""
    observed: dict[str, set[str]] = defaultdict(set)
    for raw_day in dates:
        if raw_day == held_out:
            continue
        day = date.fromisoformat(raw_day)
        active = generator.active_service_ids(day)
        for trip, calendar in gtfs_trip_candidates(generator, day, active):
            record, status = exact_id_record(odpt, trip, calendar)
            if status != "unique_id_and_time" or not trip.headsign:
                continue
            for station_id in destinations(record):
                observed[station_id].add(trip.headsign)
    return {station_id: next(iter(headsigns)) for station_id, headsigns in observed.items()
            if len(headsigns) == 1}


def fallback_candidates(odpt, trip, calendar, station_to_headsign):
    """Unique candidate by route, operation calendar, minute, and learned destination."""
    if not calendar or not trip.headsign:
        return []
    line = LINE_NAME[trip.route_id]
    gtfs_minute = (trip.departure_seconds % 86400) // 60
    result = []
    for record in indexed_records(odpt, line, calendar):
        departure = ikebukuro_departure(record)
        if departure is None or (departure % 86400) // 60 != gtfs_minute:
            continue
        mapped = {station_to_headsign.get(station_id) for station_id in destinations(record)}
        if trip.headsign in mapped:
            result.append(record)
    return result


def run(dates: list[str], gtfs: Path, data_dir: Path) -> int:
    generator = ItineraryGenerator(gtfs, data_dir)
    odpt = load_odpt(data_dir)
    print(f"feed_version={generator.feed_version}; valid={generator.feed_start}..{generator.feed_end}")
    all_dates = [date.fromisoformat(value).isoformat() for value in dates]
    results_by_date = {}
    for raw_day in all_dates:
        day = date.fromisoformat(raw_day)
        try:
            results_by_date[raw_day] = generator.generate(day)
        except ValueError as exc:
            print(f"{raw_day}: skipped ({exc})")

    for raw_day, results in results_by_date.items():
        day = date.fromisoformat(raw_day)
        active = generator.active_service_ids(day)
        station_map = holdout_destination_map(generator, odpt, all_dates, raw_day)
        counts: dict[tuple[str, str], Counter] = defaultdict(Counter)
        eligible_trips = {}
        for trip, calendar in gtfs_trip_candidates(generator, day, active):
            eligible_trips[trip.trip_id] = (trip, calendar)

        for result in results:
            if not result.primary_itinerary:
                continue
            trip, calendar = eligible_trips[result.origin_trip_id]
            key = (trip.route_id, result.primary_itinerary.kind)
            count = counts[key]
            count["itinerary_candidates"] += 1
            count[f"current_direct_path_status:{result.odpt.status}"] += 1

            id_record, id_status = exact_id_record(odpt, trip, calendar)
            if id_status == "unique_id_and_time":
                count["unique_id_route_calendar_and_departure"] += 1
                type_name = id_record.get("odpt:trainType", "").rsplit(":", 1)[-1].rsplit(".", 1)[-1]
                count[f"verified_type:{type_name or 'missing'}"] += 1
            else:
                count[f"id_route_calendar_status:{id_status}"] += 1

            fallback = fallback_candidates(odpt, trip, calendar, station_map)
            if len(fallback) == 1:
                count["destination_time_fallback_unique"] += 1
                count[f"fallback_type:{fallback[0].get('odpt:trainType', '').rsplit(':', 1)[-1].rsplit('.', 1)[-1] or 'missing'}"] += 1
                if id_status == "unique_id_and_time":
                    count["holdout_control_unique"] += 1
                    count["holdout_control_same_train"] += (
                        fallback[0].get("odpt:train") == id_record.get("odpt:train"))
                else:
                    count["fallback_unique_without_ID_confirmation"] += 1
            elif not fallback:
                count["destination_time_fallback_none"] += 1
            else:
                count["destination_time_fallback_multiple"] += 1
                if id_status == "unique_id_and_time":
                    count["holdout_control_multiple"] += 1

        print(f"\n=== {raw_day} service_id={','.join(sorted(active)) or '(none)'} "
              f"destination_crosswalk={len(station_map)} ===")
        for (route, kind), counter in sorted(counts.items()):
            print(f"{generator.routes[route].get('route_long_name', route)} {kind}: {dict(counter)}")
        verified = sum(c["unique_id_route_calendar_and_departure"] for c in counts.values())
        fallback_unique = sum(c["destination_time_fallback_unique"] for c in counts.values())
        primary_total = sum(c["itinerary_candidates"] for c in counts.values())
        control_total = sum(c["unique_id_route_calendar_and_departure"] for c in counts.values())
        control_unique = sum(c["holdout_control_unique"] for c in counts.values())
        control_same = sum(c["holdout_control_same_train"] for c in counts.values())
        additional = sum(c["fallback_unique_without_ID_confirmation"] for c in counts.values())
        print(f"summary: primary={primary_total}, independently verified ID+time={verified}, "
              f"fallback unique candidates={fallback_unique}, additional unmatched-ID candidates={additional}, "
              f"holdout controls unique/same_identity={control_unique}/{control_same}/{control_total}")

    for line, records in odpt.items():
        types = Counter(record.get("odpt:trainType", "").rsplit(":", 1)[-1].rsplit(".", 1)[-1]
                        or "missing" for record in records)
        print(f"ODPT {line} record trainType values: {dict(types)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dates", nargs="*", default=list(REPRESENTATIVE_DATES))
    parser.add_argument("--gtfs", type=Path, default=DEFAULT_GTFS)
    parser.add_argument("--odpt-dir", type=Path, default=DEFAULT_DATA_DIR)
    args = parser.parse_args()
    try:
        return run(args.dates, args.gtfs, args.odpt_dir)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"分析エラー: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
