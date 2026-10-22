#!/usr/bin/env python3
"""Compare GTFS stop patterns with confirmed ODPT train types (offline only)."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

from odpt_itinerary import DEFAULT_DATA_DIR, DEFAULT_GTFS, ItineraryGenerator
from odpt_stop_patterns import (
    CRITICAL_STOPS,
    FUKUTOSHIN_TYPE_PATTERN,
    classify,
    event_state,
)


REPRESENTATIVE_DATES = ("2026-10-22", "2026-10-24", "2026-11-03")


def run(dates: list[str], gtfs: Path, odpt_dir: Path) -> int:
    generator = ItineraryGenerator(gtfs, odpt_dir)
    labels = {
        "local": "各駅停車",
        "commuter_express": "通勤急行",
        "express_pattern": "急行停車パターン（Fライナーと区別不可）",
        "all_stops_metro_section": "メトロ線内全駅停車パターン（種別名ではない）",
        "non_all_stop_pattern_unclassified": "メトロ線内通過あり（種別名不明）",
        "unclassifiable": "判定不能",
    }
    examples = defaultdict(list)
    aggregate = defaultdict(Counter)
    for raw_day in dates:
        day = date.fromisoformat(raw_day)
        results = generator.generate(day)
        for result in results:
            if result.primary_itinerary is None:
                continue
            events = generator.events[result.origin_trip_id]
            origin = next((item for item in events
                           if item.stop_id in CRITICAL_STOPS[result.route_id].values()
                           and generator.stops[item.stop_id].get("stop_name") == "池袋"), None)
            # Route-specific Ikebukuro aliases are distinct from the four
            # pattern stations; use the actual origin event from its trip.
            if origin is None:
                origin = next((item for item in events
                               if generator.stops.get(item.stop_id, {}).get("stop_name") == "池袋"), None)
            if origin is None:
                continue
            states = {name: event_state(events, stop_id, origin.sequence)
                      for name, stop_id in CRITICAL_STOPS[result.route_id].items()}
            pattern = classify(result.route_id, states)
            exact_type = result.odpt.train_type if result.odpt.status == "unique_match" else None
            route_name = result.route_name
            key = (raw_day, route_name)
            count = aggregate[key]
            count["primary"] += 1
            count[f"pattern:{pattern}"] += 1
            if exact_type:
                count["odpt_confirmed"] += 1
                count[f"odpt_type:{exact_type}"] += 1
                count[f"odpt_type_pattern:{exact_type}|{pattern}"] += 1
                if result.route_id == "9" and exact_type in FUKUTOSHIN_TYPE_PATTERN:
                    expected = FUKUTOSHIN_TYPE_PATTERN[exact_type]
                    observed = pattern
                    if observed == expected:
                        count["comparable_agree"] += 1
                    elif pattern == "unclassifiable":
                        count["comparable_unclassifiable"] += 1
                    else:
                        count["comparable_conflict"] += 1
                        if len(examples[(key, "conflict")]) < 5:
                            examples[(key, "conflict")].append((result.origin_trip_id, exact_type, states, pattern))
                elif result.route_id == "6":
                    # ODPT types on the through-service can name behavior
                    # beyond the Metro segment; do not treat them as Metro classes.
                    count["odpt_type_not_comparable_to_metro_table"] += 1
            else:
                count["odpt_unknown"] += 1
                if pattern in ("local", "commuter_express", "express_pattern"):
                    count[f"unknown_classifiable:{pattern}"] += 1
                    if len(examples[(key, pattern)]) < 5:
                        examples[(key, pattern)].append((result.origin_trip_id, None, states, pattern))
                elif pattern == "all_stops_metro_section":
                    count["unknown_all_stops_metro_pattern_only"] += 1
                    if len(examples[(key, pattern)]) < 5:
                        examples[(key, pattern)].append((result.origin_trip_id, None, states, pattern))
                elif len(examples[(key, "unclassifiable")]) < 5:
                    examples[(key, "unclassifiable")].append((result.origin_trip_id, None, states, pattern))

    for (raw_day, route_name), counter in sorted(aggregate.items()):
        print(f"\n{raw_day} {route_name}: {dict(counter)}")
        for pattern in ("local", "commuter_express", "express_pattern", "unclassifiable",
                        "all_stops_metro_section", "non_all_stop_pattern_unclassified"):
            sample = examples.get(((raw_day, route_name), pattern), [])
            if sample:
                print(f"  {labels[pattern]} examples: " + "; ".join(
                    f"{trip_id} ODPT={odpt_type or 'unknown'} category={pattern} pattern={states}"
                    for trip_id, odpt_type, states, _ in sample))
        conflicts = examples.get(((raw_day, route_name), "conflict"), [])
        if conflicts:
            print("  conflicts: " + "; ".join(
                f"{trip_id} ODPT={odpt_type} pattern={pattern} states={states}"
                for trip_id, odpt_type, states, pattern in conflicts))
    print("\nPattern semantics: stop=time present and boarding or alighting allowed; "
          "pass=explicit row with no times and pickup/drop_off both 1; missing/other=unknown.")
    print("Only primary journeys are counted; no train-type values are written to payloads.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dates", nargs="*", default=REPRESENTATIVE_DATES)
    parser.add_argument("--gtfs", type=Path, default=DEFAULT_GTFS)
    parser.add_argument("--odpt-dir", type=Path, default=DEFAULT_DATA_DIR)
    args = parser.parse_args()
    return run(args.dates, args.gtfs, args.odpt_dir)


if __name__ == "__main__":
    raise SystemExit(main())
