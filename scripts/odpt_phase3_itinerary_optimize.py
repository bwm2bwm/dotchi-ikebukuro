#!/usr/bin/env python3
"""Optimize date-specific local GTFS itineraries and inspect display fields."""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
import zipfile

from odpt_phase3_itinerary_analyze import (
    ARCHIVE, DATA, HIKAWADAI, IKEBUKURO, KOTAKE, LINE_NAMES,
    active_services, parse_date, passenger_stop, seconds,
)

DEFAULT_DATES = ("2026-10-22", "2026-10-24", "2026-11-03")
WAIT_LIMITS = (300, 600, 900, None)  # 5, 10, 15 minutes, unlimited
SAVING_THRESHOLDS = (60, 120, 180, 300)  # 1, 2, 3, 5 minutes


def read_table(zf, name):
    with zf.open(name) as stream:
        return list(csv.DictReader((line.decode("utf-8-sig") for line in stream)))


def odpt_rows(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []


def station_path(rows, stop_by_id):
    result = []
    for row in rows:
        stop = stop_by_id.get(row.get("stop_id", ""), {})
        name = stop.get("stop_name", "")
        result.append((row, name))
    return result


def odpt_direct_index(line, calendar):
    filename = DATA / f"TrainTimetable_{line}.json"
    index = defaultdict(list)
    for trip in odpt_rows(filename):
        if trip.get("odpt:calendar", "").rsplit(":", 1)[-1] != calendar:
            continue
        objects = trip.get("odpt:trainTimetableObject", [])
        names = [
            (obj.get("odpt:departureStation") or obj.get("odpt:arrivalStation", "")).rsplit(".", 1)[-1]
            for obj in objects
        ]
        if "Ikebukuro" not in names or "Hikawadai" not in names or names.index("Ikebukuro") >= names.index("Hikawadai"):
            continue
        ike_obj = next((obj for obj in objects if (obj.get("odpt:departureStation") or "").rsplit(".", 1)[-1] == "Ikebukuro"), {})
        index[trip.get("odpt:trainNumber", "")].append({
            "train_type": trip.get("odpt:trainType", ""),
            "destination": trip.get("odpt:destinationStation", []),
            "ike_departure": ike_obj.get("odpt:departureTime", ""),
        })
    return index


def train_number(trip_id):
    if len(trip_id) == 10:
        return trip_id[2:-2]
    return ""


def compare_direct_to_odpt(trip, calendar, indexes, departure):
    line = "Yurakucho" if trip.get("route_id") == "6" else "Fukutoshin"
    matches = indexes[line].get(train_number(trip.get("trip_id", "")), [])
    if len(matches) != 1:
        return {"match_count": len(matches), "type": None, "time_equal": False}
    odpt = matches[0]
    gtfs_minute = None if departure is None else departure // 60
    odpt_sec = seconds(odpt.get("ike_departure", "") + (":00" if odpt.get("ike_departure", "").count(":") == 1 else ""))
    odpt_minute = None if odpt_sec is None else (odpt_sec // 60) % (24 * 60)
    return {
        "match_count": 1,
        "type": odpt.get("train_type", "").rsplit(".", 1)[-1] or None,
        "destination_available": bool(odpt.get("destination")),
        "time_equal": gtfs_minute is not None and gtfs_minute % (24 * 60) == odpt_minute,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dates", nargs="*", default=list(DEFAULT_DATES))
    args = parser.parse_args()
    if not ARCHIVE.exists():
        print(f"GTFS ZIPがありません: {ARCHIVE}")
        return 0

    with zipfile.ZipFile(ARCHIVE) as zf:
        feed = read_table(zf, "feed_info.txt")[0]
        feed_start, feed_end = parse_date(feed["feed_start_date"]), parse_date(feed["feed_end_date"])
        calendars, exceptions = read_table(zf, "calendar.txt"), read_table(zf, "calendar_dates.txt")
        routes = {r["route_id"]: r for r in read_table(zf, "routes.txt")}
        stops = {s["stop_id"]: s for s in read_table(zf, "stops.txt")}
        trips = {t["trip_id"]: t for t in read_table(zf, "trips.txt")}
        by_trip = defaultdict(list)
        for row in read_table(zf, "stop_times.txt"):
            by_trip[row["trip_id"]].append(row)
        for rows in by_trip.values():
            rows.sort(key=lambda r: int(r.get("stop_sequence") or 0))

    print(f"feed_version={feed.get('feed_version')} 有効期間={feed_start}..{feed_end}")
    print("GTFS表示項目の収録状況:")
    for route in LINE_NAMES:
        rows = [t for t in trips.values() if t.get("route_id") == route]
        type_column = f"route_type={routes[route].get('route_type')} (鉄道区分); GTFSに急行/各停等のtrip種別列なし"
        print(f"  {LINE_NAMES[route]} route_long_name={routes[route].get('route_long_name')!r}; "
              f"trip_headsignあり={sum(bool(t.get('trip_headsign')) for t in rows)}/{len(rows)}; "
              f"trip_short_nameあり={sum(bool(t.get('trip_short_name')) for t in rows)}/{len(rows)}; {type_column}")

    odpt_indexes = {
        ("Yurakucho", "Weekday"): odpt_direct_index("Yurakucho", "Weekday"),
        ("Yurakucho", "SaturdayHoliday"): odpt_direct_index("Yurakucho", "SaturdayHoliday"),
        ("Fukutoshin", "Weekday"): odpt_direct_index("Fukutoshin", "Weekday"),
        ("Fukutoshin", "SaturdayHoliday"): odpt_direct_index("Fukutoshin", "SaturdayHoliday"),
    }

    for raw_day in args.dates:
        try:
            service_day = date.fromisoformat(raw_day)
        except ValueError:
            print(f"日付形式エラー: {raw_day}")
            continue
        active = active_services(calendars, exceptions, service_day, feed_start, feed_end)
        print(f"\n=== {service_day} active_service_ids={','.join(sorted(active)) or '(なし)'} ===")
        if not active:
            print("期間外または運行serviceなし")
            continue
        calendar = "Weekday" if "0" in active else "SaturdayHoliday" if "1" in active else "unknown"
        indexes = {
            "Yurakucho": odpt_indexes[("Yurakucho", calendar)],
            "Fukutoshin": odpt_indexes[("Fukutoshin", calendar)],
        } if calendar != "unknown" else {"Yurakucho": {}, "Fukutoshin": {}}

        origins = {}
        direct = {}
        direct_path = set()
        direct_unusable = set()
        incoming = []
        outgoing = []
        type_stats = defaultdict(Counter)
        path_examples = {}
        path_patterns = defaultdict(Counter)
        for trip_id, trip in trips.items():
            route = trip.get("route_id", "")
            if route not in LINE_NAMES or trip.get("service_id") not in active:
                continue
            rows = by_trip.get(trip_id, [])
            ike = next((r for r in rows if r.get("stop_id") in IKEBUKURO), None)
            kotake = next((r for r in rows if r.get("stop_id") == KOTAKE[route]), None)
            hikawadai = next((r for r in rows if r.get("stop_id") == HIKAWADAI[route]), None)
            if (not ike or not kotake or int(ike["stop_sequence"]) >= int(kotake["stop_sequence"])
                    or seconds(ike.get("departure_time", "")) is None or not passenger_stop(ike, "pickup_type")):
                continue
            origins[trip_id] = {"trip": trip, "route": route, "ike": ike, "rows": rows}
            if kotake and int(ike["stop_sequence"]) < int(kotake["stop_sequence"]):
                arr_k = seconds(kotake.get("arrival_time", ""))
                if arr_k is not None and passenger_stop(kotake, "drop_off_type"):
                    incoming.append((trip_id, route, trip, ike, kotake))
            if kotake and hikawadai and int(kotake["stop_sequence"]) < int(hikawadai["stop_sequence"]):
                dep_k, arr_h = seconds(kotake.get("departure_time", "")), seconds(hikawadai.get("arrival_time", ""))
                if (dep_k is not None and arr_h is not None and passenger_stop(kotake, "pickup_type")
                        and passenger_stop(hikawadai, "drop_off_type")):
                    outgoing.append((trip_id, route, trip, kotake, hikawadai))
            if hikawadai and int(ike["stop_sequence"]) < int(hikawadai["stop_sequence"]):
                direct_path.add(trip_id)
                arr_h = seconds(hikawadai.get("arrival_time", ""))
                if arr_h is not None and passenger_stop(hikawadai, "drop_off_type"):
                    direct[trip_id] = {"arrival": arr_h, "row": hikawadai}
                    line = "Yurakucho" if route == "6" else "Fukutoshin"
                    id_match = compare_direct_to_odpt(trip, calendar, indexes, seconds(ike["departure_time"]))
                    type_stats[line]["unique_match" if id_match["match_count"] == 1 else "unmatched_or_ambiguous"] += 1
                    type_stats[line]["type_available"] += id_match["type"] is not None
                    type_stats[line]["departure_time_equal"] += id_match["time_equal"]
                    type_stats[line][f"ODPT種別:{id_match['type'] or '未照合'}"] += 1
                    type_stats[line]["ODPT行先あり"] += id_match.get("destination_available", False)
                    for stop_row, stop_name in station_path(rows, stops):
                        if int(stop_row["stop_sequence"]) <= int(ike["stop_sequence"]) or int(stop_row["stop_sequence"]) > int(hikawadai["stop_sequence"]):
                            continue
                        if stop_name in ("池袋", "小竹向原", "氷川台"):
                            continue
                        path_examples.setdefault(trip_id, []).append(stop_name)
                    path_patterns[line][tuple(path_examples[trip_id])] += 1
                else:
                    direct_unusable.add(trip_id)

        print(f"池袋発便={len(origins)}; 氷川台までの停車順レコード={len(direct_path)}; "
              f"直通到着時刻あり・降車可={len(direct)}; 行はあるが時刻欠損/降車不可={len(direct_unusable)}")
        for route in LINE_NAMES:
            line = "Yurakucho" if route == "6" else "Fukutoshin"
            print(f"  {LINE_NAMES[route]} direct ODPT種別照合={dict(type_stats[line])}")
            print(f"  {LINE_NAMES[route]} 中間停車パターン={len(path_patterns[line])}; "
                  f"頻出5件={path_patterns[line].most_common(5)}")
        sample_ids = list(path_examples)[:3]
        for trip_id in sample_ids:
            print(f"  途中停車例 {trip_id}: {', '.join(path_examples[trip_id]) or '(なし)'}")

        all_connections = defaultdict(list)
        for in_id, in_route, in_trip, ike, in_kotake in incoming:
            arrival = seconds(in_kotake["arrival_time"])
            for out_id, out_route, out_trip, out_kotake, hikawadai in outgoing:
                if in_id == out_id or in_route == out_route:
                    continue
                wait = seconds(out_kotake["departure_time"]) - arrival
                if wait < 60:
                    continue
                all_connections[in_id].append({
                    "out_id": out_id, "out_trip": out_trip, "out_route": out_route,
                    "wait": wait, "arrival": seconds(hikawadai["arrival_time"]),
                    "arrival_text": hikawadai["arrival_time"], "departure_text": out_kotake["departure_time"],
                    "kotake_arrival_text": in_kotake["arrival_time"],
                })

        for limit in WAIT_LIMITS:
            label = "上限なし" if limit is None else f"上限{limit // 60}分"
            grouped = {}
            raw_count = 0
            for origin_id, candidates in all_connections.items():
                eligible = [c for c in candidates if limit is None or c["wait"] <= limit]
                if eligible:
                    raw_count += len(eligible)
                    grouped[origin_id] = min(eligible, key=lambda c: (c["arrival"], c["wait"], c["out_id"]))

            direct_win = transfer_win = ties = direct_only = transfer_only = 0
            savings = Counter()
            signed = Counter()
            unusable_direct = missing_direct_path = 0
            for origin_id, best in grouped.items():
                if origin_id in direct:
                    delta = direct[origin_id]["arrival"] - best["arrival"]
                    if delta > 0:
                        transfer_win += 1
                        savings[delta // 60] += 1
                        signed[f"乗換が{delta // 60}分早い"] += 1
                    elif delta == 0:
                        ties += 1
                        direct_win += 1  # provisional tie-break: direct preferred
                    else:
                        direct_win += 1
                        signed[f"直通が{(-delta) // 60}分早い"] += 1
                else:
                    transfer_only += 1
                    if origin_id in direct_unusable:
                        unusable_direct += 1
                    else:
                        missing_direct_path += 1
            direct_with_no_transfer = len(set(direct) - set(grouped))
            direct_only += direct_with_no_transfer
            recommend_counts = {
                f"短縮{threshold // 60}分以上": sum(count for saved, count in savings.items() if saved >= threshold // 60)
                for threshold in SAVING_THRESHOLDS
            }
            saving_hist = dict(sorted(savings.items()))
            print(f"{label}: 元接続組={raw_count}; 池袋発便に集約={len(grouped)}; "
                  f"直通最早(同着含む)={direct_win}; 乗換が早い={transfer_win}; 同着={ties}; "
                  f"直通のみ={direct_only}; 直通到着時刻なしで乗換のみ={transfer_only}; "
                  f"（内訳: 直通行はあるが到着不可={unusable_direct}, 同一tripの氷川台行なし={missing_direct_path}）; "
                  f"短縮分布={saving_hist}; 直通が早い分布="
                  f"{dict((k, v) for k, v in signed.items() if k.startswith('直通が'))}; "
                  f"推奨閾値別={recommend_counts}")

            examples = 0
            transfer_only_examples = 0
            for origin_id, best in grouped.items():
                if origin_id not in direct:
                    if transfer_only_examples < 2:
                        origin = origins[origin_id]
                        print(f"  乗換のみ例（直通到着なし）: 池袋{origin['ike']['departure_time']} {origin_id}; "
                              f"小竹向原{best['kotake_arrival_text']}着→{best['departure_text']}発; "
                              f"氷川台{best['arrival_text']}着; 後続便={best['out_id']}")
                        transfer_only_examples += 1
                    continue
                delta = direct[origin_id]["arrival"] - best["arrival"]
                if delta >= 0:
                    continue
                origin = origins[origin_id]
                origin_line = LINE_NAMES[origin["route"]]
                transfer_line = LINE_NAMES[best["out_route"]]
                print(f"  直通が早い比較例: 池袋{origin['ike']['departure_time']} {origin_id}; "
                      f"直通着{direct[origin_id]['row']['arrival_time']}; "
                      f"乗換 {origin_line}→{transfer_line} "
                      f"{best['kotake_arrival_text']}着→{best['departure_text']}発→{best['arrival_text']}着; "
                      f"直通が{(-delta) // 60}分早い")
                examples += 1
                if examples == 2:
                    break


if __name__ == "__main__":
    main()
