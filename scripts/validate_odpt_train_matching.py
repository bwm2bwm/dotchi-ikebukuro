#!/usr/bin/env python3
"""Validate normalized GTFS→ODPT matching against saved local data only."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import date
import json
from pathlib import Path

from odpt_itinerary import DEFAULT_DATA_DIR, DEFAULT_GTFS, ItineraryGenerator
from odpt_phase3_train_type_match import exact_id_record, gtfs_trip_candidates, load_odpt
from odpt_stop_patterns import CRITICAL_STOPS, classify, event_state, resolve_type
from odpt_train_matcher import (OdptTrainMatcher, odpt_destinations, station_lookup_from_odpt,
                                type_scope)

DATES = ("2026-10-22", "2026-10-24", "2026-11-03")


def run(dates: list[str], gtfs: Path, odpt_dir: Path) -> dict:
    generator = ItineraryGenerator(gtfs, odpt_dir)
    odpt = load_odpt(odpt_dir)
    station_rows = json.loads((odpt_dir / "Station_all.json").read_text(encoding="utf-8"))
    station_lookup = station_lookup_from_odpt(station_rows)
    controls, residuals, other_unmatched, destination_heads = [], [], [], defaultdict(set)
    day_context = {}
    for raw_day in dates:
        day = date.fromisoformat(raw_day)
        active_services = generator.active_service_ids(day)
        calendar = generator._day_calendar(active_services)
        generated = {r.origin_trip_id: r for r in generator.generate(day)}
        active_by_route = {
            route_id: [trip_id for trip_id, row in generator.trips.items()
                       if row.get("route_id") == route_id and row.get("service_id") in active_services]
            for route_id in ("6", "9")
        }
        day_context[raw_day] = (day, active_services, calendar, generated, active_by_route)
        for trip, trip_calendar in gtfs_trip_candidates(generator, day, active_services):
            result = generated.get(trip.trip_id)
            if result is None or result.primary_itinerary is None:
                continue
            record, legacy_status = exact_id_record(odpt, trip, trip_calendar)
            if legacy_status == "unique_id_and_time" and record:
                controls.append((raw_day, trip, trip_calendar, record))
                for station_id in odpt_destinations(record):
                    if trip.headsign:
                        destination_heads[station_id].add(trip.headsign)
            else:
                if legacy_status == "time_mismatch":
                    legacy_type_status = "unmatched"
                else:
                    legacy_type_status = legacy_status
                states = {name: event_state(trip.events, stop_id, trip.origin_event.sequence)
                          for name, stop_id in CRITICAL_STOPS[trip.route_id].items()}
                pattern = classify(trip.route_id, states)
                old_resolution = resolve_type(
                    trip.route_id, legacy_type_status, None, None, pattern, states,
                )
                row = (raw_day, trip, trip_calendar, result)
                if old_resolution.source == "unknown":
                    residuals.append(row)
                else:
                    other_unmatched.append(row)

    matcher = OdptTrainMatcher(
        odpt, station_lookup, destination_heads,
        {stop_id: row.get("stop_name", "") for stop_id, row in generator.stops.items()},
    )
    results = []
    for label, rows in (("known_control", controls), ("residual_unknown", residuals),
                        ("pattern_classified_unmatched", other_unmatched)):
        for raw_day, trip, calendar, legacy in rows:
            _, _, _, _, active_by_route = day_context[raw_day]
            matched = matcher.match(trip, calendar, active_by_route[trip.route_id])
            legacy_record = legacy if label == "known_control" else None
            result = {
                "group": label,
                "service_date": raw_day,
                "calendar": calendar,
                "trip_id": trip.trip_id,
                "route_id": trip.route_id,
                "departure": trip.departure_text,
                "headsign": trip.headsign,
                "legacy_odpt_train_number": legacy_record.get("odpt:trainNumber") if legacy_record else None,
                "match_status": matched.status,
                "reason": matched.reason,
                "candidate_train_numbers": list(matched.candidates),
                "matched_train_number": (matched.odpt_record or {}).get("odpt:trainNumber"),
                "matched_raw_train_type": matched.raw_train_type,
                "matched_type_code": (matched.raw_train_type or "").rsplit(":", 1)[-1].rsplit(".", 1)[-1] or None,
            }
            if matched.status == "confirmed":
                result["type_scope"] = type_scope(result["matched_raw_train_type"], trip.route_id)
            results.append(result)

    counts = Counter((row["group"], row["match_status"]) for row in results)
    residual_reasons = Counter(row["reason"] for row in results if row["group"] == "residual_unknown")
    residual_by_day = {
        raw_day: dict(Counter(row["match_status"] for row in results
                              if row["group"] == "residual_unknown" and row["service_date"] == raw_day))
        for raw_day in dates
    }
    raw_type_counts = Counter(
        (row["route_id"], row.get("matched_type_code") or "missing")
        for row in results if row["group"] == "residual_unknown" and row["match_status"] == "confirmed"
    )
    scope_counts = Counter(
        (row["route_id"], (row.get("type_scope") or {}).get("type_scope"))
        for row in results if row["group"] == "residual_unknown" and row["match_status"] == "confirmed"
    )
    return {
        "feed_version": generator.feed_version,
        "validity": [generator.feed_start.isoformat(), generator.feed_end.isoformat()],
        "counts": {f"{group}:{status}": count for (group, status), count in sorted(counts.items())},
        "legacy_known_controls": len(controls),
        "residual_unknown_total": len(residuals),
        "other_unmatched_total": len(other_unmatched),
        "primary_journey_total": len(controls) + len(residuals) + len(other_unmatched),
        "residual_by_day": residual_by_day,
        "residual_reasons": dict(residual_reasons),
        "residual_raw_types": {f"route{route}:{kind}": count for (route, kind), count in sorted(raw_type_counts.items())},
        "residual_type_scopes": {f"route{route}:{scope}": count for (route, scope), count in sorted(scope_counts.items())},
        "unconfirmed": [row for row in results if row["match_status"] != "confirmed"],
        "rows": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dates", nargs="*", default=list(DATES))
    parser.add_argument("--gtfs", type=Path, default=DEFAULT_GTFS)
    parser.add_argument("--odpt-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--output", type=Path, help="write derived report outside the repository")
    args = parser.parse_args()
    report = run(args.dates, args.gtfs, args.odpt_dir)
    serialized = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(serialized, encoding="utf-8")
        print(f"report_written={args.output}")
    print(f"controls={report['legacy_known_controls']}; residual={report['residual_unknown_total']}")
    print("counts=" + json.dumps(report["counts"], ensure_ascii=False, sort_keys=True))
    print("residual_by_day=" + json.dumps(report["residual_by_day"], ensure_ascii=False, sort_keys=True))
    print("residual_reasons=" + json.dumps(report["residual_reasons"], ensure_ascii=False, sort_keys=True))
    print("residual_raw_types=" + json.dumps(report["residual_raw_types"], ensure_ascii=False, sort_keys=True))
    print("residual_type_scopes=" + json.dumps(report["residual_type_scopes"], ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
