#!/usr/bin/env python3
"""Diagnose every primary itinerary still shown as unknown (offline only).

The output contains derived trip diagnostics, not raw GTFS rows or ODPT JSON.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

from odpt_itinerary import DEFAULT_DATA_DIR, DEFAULT_GTFS, ItineraryGenerator, parse_gtfs_time
from odpt_phase3_train_type_match import (
    destinations as odpt_destinations,
    exact_id_record,
    fallback_candidates,
    gtfs_trip_candidates,
    holdout_destination_map,
    load_odpt,
)
from odpt_stop_patterns import CRITICAL_STOPS, classify, event_state


DATES = ("2026-10-22", "2026-10-24", "2026-11-03")


def _odpt_ikebukuro_time(record: dict) -> int | None:
    objects = record.get("odpt:trainTimetableObject", [])
    obj = next((item for item in objects if
                (item.get("odpt:departureStation") or "").rsplit(".", 1)[-1] == "Ikebukuro"), None)
    value = parse_gtfs_time((obj or {}).get("odpt:departureTime"))
    return value % 86400 if value is not None else None


def _station_name(generator: ItineraryGenerator, stop_id: str) -> str:
    return generator.stops.get(stop_id, {}).get("stop_name", "") or f"stop:{stop_id}"


def _event_dto(generator: ItineraryGenerator, event, origin_sequence: int) -> dict:
    times = [value for value in (event.arrival_seconds, event.departure_seconds) if value is not None]
    if times and (event.can_board or event.can_alight):
        state = "time_and_access"
    elif not times and event.pickup_type == "1" and event.drop_off_type == "1":
        state = "no_time_no_board_or_alight"
    elif times:
        state = "time_but_boarding_or_alighting_prohibited"
    else:
        state = "no_time_access_unspecified_or_partial"
    return {
        "station": _station_name(generator, event.stop_id),
        "stop_id": event.stop_id,
        "position": "before_or_at_ikebukuro" if event.sequence <= origin_sequence else "after_ikebukuro",
        "arrival": event.arrival_seconds,
        "departure": event.departure_seconds,
        "pickup_type": event.pickup_type,
        "drop_off_type": event.drop_off_type,
        "can_board": event.can_board,
        "can_alight": event.can_alight,
        "state": state,
    }


def _cause(result, pattern: str, states: dict[str, str], events, origin_sequence: int,
           same_number_records: list[dict], time_candidates: list[dict]) -> tuple[str, str]:
    odpt = result.odpt
    if odpt.status == "ambiguous":
        return "odpt_ambiguous_same_number_and_time", "複数のODPT便が同じ番号・池袋発時刻に一致"
    if odpt.status == "unavailable":
        return "odpt_identity_unavailable", "GTFS便番号・運行日区分をODPT照合条件へ変換できない"
    if odpt.status == "unique_match" and not odpt.train_type:
        return "odpt_type_missing", "ODPT便は一意照合したが odpt:trainType がない"
    # A uniquely confirmed type would ordinarily not have an unknown source;
    # conflicts are nevertheless kept explicit for diagnostic completeness.
    if result.type_resolution.validation == "conflict":
        return "confirmed_type_pattern_conflict", "確定ODPT種別と比較可能なGTFS停車パターンが矛盾"
    if result.type_resolution.diagnostic == "odpt_train_type_missing":
        return "odpt_type_missing", "ODPT便は一意照合したが種別値が欠損"

    route_id = result.route_id
    critical_ids = CRITICAL_STOPS[route_id]
    observed = {name: next((e for e in events if e.stop_id == stop_id and e.sequence > origin_sequence), None)
                for name, stop_id in critical_ids.items()}
    # Missing event rows are differentiated by their place relative to the
    # trip's observed segment; absence inside the segment remains a data gap.
    relevant = []
    for name, event in observed.items():
        if event is not None:
            continue
        stop_id = critical_ids[name]
        station_event = next((e for e in events if e.stop_id == stop_id), None)
        after = [e for e in events if e.sequence > origin_sequence]
        if station_event is not None and station_event.sequence <= origin_sequence:
            relevant.append((name, "before_origin"))
        elif after and events and max(e.sequence for e in after) < max(e.sequence for e in events):
            relevant.append((name, "after_trip_end"))
        else:
            relevant.append((name, "no_trip_row"))
    if any(where != "no_trip_row" for _, where in relevant):
        desc = ",".join(f"{name}:{where}" for name, where in relevant if where != "no_trip_row")
        return "pattern_station_outside_observed_segment", f"必要駅の一部が池袋発後の観測運行区間外 ({desc})"

    last_after_origin = max((event for event in events if event.sequence > origin_sequence),
                            key=lambda event: event.sequence, default=None)
    if (states.get("hikawadai") == "missing" and states.get("kotake") == "stop"
            and last_after_origin is not None and last_after_origin.stop_id == critical_ids["kotake"]):
        return "trip_segment_ends_at_kotake", "当該GTFS tripの池袋発後の最終記録駅が小竹向原。氷川台はこのtripの運行区間外"

    relevant_events = [event for event in observed.values() if event is not None]
    if any(event.arrival_seconds is None and event.departure_seconds is None for event in relevant_events):
        return "pattern_station_time_missing", "必要駅レコードはあるが到着・出発時刻がない"
    if any(not event.can_board and not event.can_alight for event in relevant_events):
        return "pattern_station_access_prohibited", "必要駅で乗降不可が指定され、停車／通過の検証条件を満たさない"
    if any(states[name] in ("missing", "unknown") for name in states):
        return "pattern_station_record_missing_or_incomplete", "必要駅レコードがないか、時刻・乗降属性が部分的で通過を確認できない"
    if pattern == "express_pattern":
        return "multiple_types_share_pattern", "急行とFライナーが同一停車パターンでGTFSから区別できない"
    if pattern == "non_all_stop_pattern_unclassified":
        return "route_pattern_not_in_official_type_table", "有楽町線の一部通過は記録されるが公式種別表と対応づけられない"
    if odpt.status == "unmatched":
        if same_number_records and not time_candidates:
            return "same_number_departure_time_mismatch", "同じ列車番号候補はあるが池袋発時刻が一致しない"
        if time_candidates:
            return "only_time_based_odpt_candidates", "番号照合なし。池袋発時刻だけ一致するODPT候補があり、同一便とは断定不可"
        return "no_odpt_number_or_time_candidate", "同じ列車番号も池袋発時刻候補も見つからない"
    return "other_pattern_or_odpt_issue", "記録はあるが現行の検証済み分類条件に該当しない"


def _number_variants(trip_id: str) -> set[str]:
    """Test ID spellings for diagnosis; these variants do not establish identity."""
    values = set()
    for suffix_length in (1, 2, 3):
        candidate = trip_id[2:-suffix_length]
        if candidate:
            values.add(candidate)
            values.add(candidate[0] + candidate[1:].lstrip("0"))
    return values


def analyze(dates: list[str], gtfs: Path, odpt_dir: Path) -> dict:
    generator = ItineraryGenerator(gtfs, odpt_dir)
    odpt_data = load_odpt(odpt_dir)
    reports = []
    confirmed_short_segment_pairs = Counter()
    variant_control = Counter()
    for raw_day in dates:
        day = date.fromisoformat(raw_day)
        active = generator.active_service_ids(day)
        calendar = generator._day_calendar(active)
        station_map = holdout_destination_map(generator, odpt_data, dates, raw_day)
        results = generator.generate(day)
        results_by_id = {result.origin_trip_id: result for result in results if result.primary_itinerary}
        for trip, trip_calendar in gtfs_trip_candidates(generator, day, active):
            result = results_by_id.get(trip.trip_id)
            if not result:
                continue
            station_states = {name: event_state(trip.events, stop_id, trip.origin_event.sequence)
                              for name, stop_id in CRITICAL_STOPS[trip.route_id].items()}
            last_event = max((event for event in trip.events if event.sequence > trip.origin_event.sequence),
                             key=lambda event: event.sequence, default=None)
            if (trip.route_id == "9" and station_states.get("hikawadai") == "missing"
                    and station_states.get("kotake") == "stop" and last_event
                    and last_event.stop_id == CRITICAL_STOPS["9"]["kotake"]
                    and result.odpt.status == "unique_match" and result.odpt.train_type):
                pair = (station_states.get("kanamecho"), station_states.get("senkawa"))
                confirmed_short_segment_pairs[
                    f"{raw_day}|{pair[0]}|{pair[1]}|{result.odpt.train_type}"] += 1
            if result.odpt.status == "unique_match" and result.odpt.train_type:
                exact, exact_status = exact_id_record(odpt_data, trip, trip_calendar)
                candidates = [record for values in generator._odpt_index(trip.route_id, trip_calendar).values()
                              for record in values if _odpt_ikebukuro_time(record) == trip.departure_seconds % 86400
                              and record.get("odpt:trainNumber") in _number_variants(trip.trip_id)]
                variant_control["confirmed_id_time"] += exact_status == "unique_id_and_time"
                variant_control["exact_record_number_in_variants"] += bool(
                    exact and exact.get("odpt:trainNumber") in _number_variants(trip.trip_id))
                variant_control["unique_variant_candidate"] += len(candidates) == 1
                variant_control["unique_variant_same_train"] += (
                    len(candidates) == 1 and exact is not None
                    and candidates[0].get("odpt:train") == exact.get("odpt:train"))
        for result in results:
            if result.primary_itinerary is None or result.type_resolution.source != "unknown":
                continue
            trip_id = result.origin_trip_id
            trip_row = generator.trips[trip_id]
            events = generator.events.get(trip_id, ())
            origin = next(event for event in events
                          if event.stop_id in ("228", "609", "909") and event.sequence > -1
                          and event.departure_seconds == result.departure_seconds)
            states = {name: event_state(events, stop_id, origin.sequence)
                      for name, stop_id in CRITICAL_STOPS[result.route_id].items()}
            pattern = classify(result.route_id, states)
            number = generator._odpt_number(trip_id)
            indexed = generator._odpt_index(result.route_id, calendar)
            same_number = indexed.get(number, []) if number else []
            departure_tod = result.departure_seconds % 86400
            time_candidates = [record for values in indexed.values() for record in values
                               if _odpt_ikebukuro_time(record) == departure_tod]
            by_number_time = [record for record in same_number
                              if _odpt_ikebukuro_time(record) == departure_tod]
            variants = _number_variants(trip_id)
            variant_time_matches = [record for record in time_candidates
                                    if record.get("odpt:trainNumber") in variants]
            trip_instance = generator._make_trip(trip_id, trip_row, day, events)
            destination_matches = fallback_candidates(odpt_data, trip_instance, calendar, station_map)
            cross_calendar_index = {cal: generator._odpt_index(result.route_id, cal)
                                    for cal in ("Weekday", "SaturdayHoliday")}
            cross_calendar_same_number = [record for cal, index in cross_calendar_index.items()
                                          if cal != calendar
                                          for record in index.get(number, [])] if number else []
            cross_calendar_variant = [record for cal, index in cross_calendar_index.items()
                                      if cal != calendar
                                      for values in index.values() for record in values
                                      if record.get("odpt:trainNumber") in variants]
            pair_suggestion = "none"
            if states.get("hikawadai") == "missing" and states.get("kotake") == "stop":
                if result.route_id == "9" and states.get("kanamecho") == states.get("senkawa") == "stop":
                    pair_suggestion = "local_candidate_from_kanamecho_and_senkawa_only"
                elif result.route_id == "9" and states.get("kanamecho") == states.get("senkawa") == "pass":
                    pair_suggestion = "commuter_express_or_express_indistinguishable_without_hikawadai"
                elif result.route_id == "6":
                    pair_suggestion = "all_recorded_critical_stops_stop_but_not_full_route_pattern"
            candidate_rows = []
            for record in time_candidates:
                candidate_rows.append({
                    "train_number": record.get("odpt:trainNumber"),
                    "train_type": (record.get("odpt:trainType") or "").rsplit(".", 1)[-1] or None,
                    "destination_ids": [str(x).rsplit(".", 1)[-1] for x in
                                        (record.get("odpt:destinationStation", []) if isinstance(record.get("odpt:destinationStation", []), list)
                                         else [record.get("odpt:destinationStation")]) if x],
                    "same_number_candidate": record in same_number,
                })
            cause, reason = _cause(result, pattern, states, events, origin.sequence,
                                   same_number, time_candidates)
            event_rows = [_event_dto(generator, event, origin.sequence) for event in events]
            reports.append({
                "service_date": raw_day,
                "calendar": calendar,
                "trip_id": trip_id,
                "route": result.route_name,
                "route_id": result.route_id,
                "departure": result.departure_text,
                "headsign": result.headsign,
                "gtfs_trip_short_name": trip_row.get("trip_short_name") or None,
                "odpt_status": result.odpt.status,
                "derived_odpt_number": number,
                "same_number_candidate_count": len(same_number),
                "same_number_time_match_count": len(by_number_time),
                "time_only_candidate_count": len([x for x in candidate_rows if not x["same_number_candidate"]]),
                "time_candidates": candidate_rows,
                "number_variants_tested": sorted(variants),
                "variant_time_match_numbers": [record.get("odpt:trainNumber") for record in variant_time_matches],
                "destination_and_minute_candidates": [{
                    "train_number": record.get("odpt:trainNumber"),
                    "train_type": (record.get("odpt:trainType") or "").rsplit(".", 1)[-1] or None,
                    "destination_ids": odpt_destinations(record),
                    "mapped_headsign_match": result.headsign in {station_map.get(x) for x in odpt_destinations(record)},
                } for record in destination_matches],
                "same_number_on_other_calendar": [record.get("odpt:trainNumber") for record in cross_calendar_same_number],
                "variant_number_on_other_calendar": [record.get("odpt:trainNumber") for record in cross_calendar_variant],
                "pairwise_pattern_suggestion": pair_suggestion,
                "primary_itinerary_kind": result.primary_itinerary.kind,
                "pattern": pattern,
                "critical_station_states": states,
                "cause": cause,
                "cause_detail": reason,
                "events": event_rows,
            })
    counts = Counter(item["cause"] for item in reports)
    return {
        "feed_version": generator.feed_version,
        "feed_validity": [generator.feed_start.isoformat(), generator.feed_end.isoformat()],
        "totals_by_date": {day: sum(item["service_date"] == day for item in reports) for day in dates},
        "causes_by_date": {day: dict(Counter(item["cause"] for item in reports if item["service_date"] == day))
                           for day in dates},
        "cause_totals": dict(counts),
        "pairwise_pattern_suggestion_totals": dict(Counter(item["pairwise_pattern_suggestion"] for item in reports)),
        "odpt_candidate_totals": {
            "no_same_number_in_calendar": sum(not item["same_number_candidate_count"] for item in reports),
            "same_number_and_time": sum(bool(item["same_number_time_match_count"]) for item in reports),
            "time_only_candidates": sum(bool(item["time_only_candidate_count"]) for item in reports),
            "number_variant_time_matches": sum(bool(item["variant_time_match_numbers"]) for item in reports),
            "destination_minute_candidates": sum(bool(item["destination_and_minute_candidates"]) for item in reports),
            "same_number_on_other_calendar": sum(bool(item["same_number_on_other_calendar"]) for item in reports),
            "variant_number_on_other_calendar": sum(bool(item["variant_number_on_other_calendar"]) for item in reports),
        },
        "odpt_candidate_train_type_totals": dict(Counter(
            candidate["train_type"] or "missing"
            for item in reports for candidate in item["destination_and_minute_candidates"])),
        "confirmed_short_segment_pair_controls": dict(confirmed_short_segment_pairs),
        "confirmed_number_variant_controls": dict(variant_control),
        "reports": reports,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dates", nargs="*", default=DATES)
    parser.add_argument("--gtfs", type=Path, default=DEFAULT_GTFS)
    parser.add_argument("--odpt-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--output", type=Path, help="write derived diagnostic JSON (prefer a path outside the repository)")
    args = parser.parse_args()
    report = analyze(args.dates, args.gtfs, args.odpt_dir)
    output = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(output, encoding="utf-8")
        print(f"診断JSONを出力: {args.output}")
    else:
        print(output, end="")
    print("\n対象件数:", report["totals_by_date"])
    print("原因別:", report["cause_totals"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
