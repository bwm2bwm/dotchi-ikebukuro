#!/usr/bin/env python3
"""Generate date-specific Ikebukuro–Hikawadai itinerary candidates from local GTFS."""
from __future__ import annotations

import argparse
import csv
from datetime import date, timedelta
from pathlib import Path
import zipfile
from collections import Counter, defaultdict

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "local_data" / "odpt"
ARCHIVE = DATA / "TokyoMetro-Train-GTFS.zip"
LINE_NAMES = {"6": "有楽町線", "9": "副都心線"}
IKEBUKURO = {"228", "609", "909"}
KOTAKE = {"6": "606", "9": "906"}
HIKAWADAI = {"6": "605", "9": "905"}


def read_table(zf, name):
    with zf.open(name) as stream:
        return list(csv.DictReader((line.decode("utf-8-sig") for line in stream)))


def parse_date(value):
    try:
        return date(int(value[:4]), int(value[4:6]), int(value[6:8]))
    except (ValueError, TypeError):
        return None


def active_services(calendars, exceptions, service_day, feed_start, feed_end):
    if not (feed_start <= service_day <= feed_end):
        return set()
    weekday_fields = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
    active = {
        row["service_id"] for row in calendars
        if parse_date(row.get("start_date", "")) <= service_day <= parse_date(row.get("end_date", ""))
        and row.get(weekday_fields[service_day.weekday()]) == "1"
    }
    for row in exceptions:
        if parse_date(row.get("date", "")) != service_day:
            continue
        if row.get("exception_type") == "1":
            active.add(row.get("service_id", ""))
        elif row.get("exception_type") == "2":
            active.discard(row.get("service_id", ""))
    return active


def seconds(value):
    try:
        hour, minute, second = map(int, value.split(":"))
        return hour * 3600 + minute * 60 + second
    except (ValueError, AttributeError):
        return None


def passenger_stop(row, field):
    return row.get(field, "0") == "0"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dates", nargs="*", default=["2026-10-22", "2026-10-24", "2026-11-03"])
    args = parser.parse_args()
    if not ARCHIVE.exists():
        print(f"GTFS ZIPがありません: {ARCHIVE}")
        return 0

    with zipfile.ZipFile(ARCHIVE) as zf:
        feed = read_table(zf, "feed_info.txt")[0]
        feed_start = parse_date(feed.get("feed_start_date", ""))
        feed_end = parse_date(feed.get("feed_end_date", ""))
        calendars = read_table(zf, "calendar.txt")
        exceptions = read_table(zf, "calendar_dates.txt")
        trips = {row["trip_id"]: row for row in read_table(zf, "trips.txt")}
        stop_times = defaultdict(list)
        for row in read_table(zf, "stop_times.txt"):
            stop_times[row["trip_id"]].append(row)
        for rows in stop_times.values():
            rows.sort(key=lambda row: int(row.get("stop_sequence") or 0))

    for raw_day in args.dates:
        try:
            service_day = date.fromisoformat(raw_day)
        except ValueError:
            print(f"日付形式エラー: {raw_day} (YYYY-MM-DD)")
            continue
        active = active_services(calendars, exceptions, service_day, feed_start, feed_end)
        print(f"\n=== {service_day} active_service_ids={','.join(sorted(active)) or '(なし)'} ===")
        if not active:
            print(f"対象日運行なし（feed有効期間 {feed_start}..{feed_end}）")
            continue

        direct = Counter()
        direct_examples = defaultdict(list)
        incoming = []
        outgoing = []
        through_count = Counter()

        for trip_id, trip in trips.items():
            route = trip.get("route_id", "")
            if route not in LINE_NAMES or trip.get("service_id") not in active:
                continue
            rows = stop_times.get(trip_id, [])
            ike = next((r for r in rows if r.get("stop_id") in IKEBUKURO), None)
            kotake = next((r for r in rows if r.get("stop_id") == KOTAKE[route]), None)
            hikawadai = next((r for r in rows if r.get("stop_id") == HIKAWADAI[route]), None)
            if not kotake:
                continue

            if ike and int(ike["stop_sequence"]) < int(kotake["stop_sequence"]):
                arrival = seconds(kotake.get("arrival_time", ""))
                if (arrival is not None and passenger_stop(ike, "pickup_type")
                        and passenger_stop(kotake, "drop_off_type")):
                    incoming.append((trip_id, route, trip, ike, kotake))
                    if hikawadai and int(kotake["stop_sequence"]) < int(hikawadai["stop_sequence"]):
                        through_count[route] += 1

            if (hikawadai and int(kotake["stop_sequence"]) < int(hikawadai["stop_sequence"])
                    and seconds(kotake.get("departure_time", "")) is not None
                    and seconds(hikawadai.get("arrival_time", "")) is not None
                    and passenger_stop(kotake, "pickup_type")
                    and passenger_stop(hikawadai, "drop_off_type")):
                outgoing.append((trip_id, route, trip, kotake, hikawadai))

            if (ike and hikawadai and int(ike["stop_sequence"]) < int(hikawadai["stop_sequence"])):
                direct[route] += 1
                if hikawadai.get("arrival_time") and passenger_stop(hikawadai, "drop_off_type"):
                    direct_examples[route].append((trip_id, ike, hikawadai))

        print("直通便（池袋→氷川台、stop_sequence順）:")
        for route in LINE_NAMES:
            print(f"  {LINE_NAMES[route]}: {direct[route]}便; 到着時刻あり/降車可={len(direct_examples[route])}")
            for trip_id, ike, hikawadai in direct_examples[route][:2]:
                print(f"    例 {trip_id} ({trips[trip_id].get('trip_headsign')}): "
                      f"池袋発{ike.get('departure_time')} → 氷川台着{hikawadai.get('arrival_time')}")
            print(f"    小竹向原を越えて同一trip_idで氷川台へ続く便={through_count[route]}")

        connections = []
        for in_id, in_route, in_trip, ike, in_kotake in incoming:
            in_arrival = seconds(in_kotake.get("arrival_time", ""))
            for out_id, out_route, out_trip, out_kotake, hikawadai in outgoing:
                if in_route == out_route or in_id == out_id:
                    continue
                out_departure = seconds(out_kotake.get("departure_time", ""))
                wait = out_departure - in_arrival
                if wait < 0:
                    continue
                connections.append({
                    "in_id": in_id, "in_route": in_route, "in_ike": ike,
                    "in_kotake": in_kotake, "out_id": out_id, "out_route": out_route,
                    "out_trip": out_trip, "out_kotake": out_kotake, "hikawadai": hikawadai,
                    "wait_seconds": wait,
                })

        buckets = Counter()
        bucket_examples = {}
        midnight_crossings = 0
        near_midnight = 0
        midnight_example = None
        by_inbound = defaultdict(list)
        for connection in connections:
            wait = connection["wait_seconds"]
            bucket = "0分" if wait == 0 else "1分未満" if wait < 60 else "1分" if wait < 120 else "2分" if wait < 180 else "3分以上"
            buckets[bucket] += 1
            bucket_examples.setdefault(bucket, connection)
            in_arrival = seconds(connection["in_kotake"].get("arrival_time", ""))
            out_departure = seconds(connection["out_kotake"].get("departure_time", ""))
            if 23 * 3600 <= in_arrival < 24 * 3600 <= out_departure:
                midnight_crossings += 1
                if 60 <= wait <= 10 * 60:
                    near_midnight += 1
                if midnight_example is None and 60 <= wait <= 10 * 60:
                    midnight_example = connection
            by_inbound[connection["in_id"]].append(connection)
        adopted = [c for c in connections if c["wait_seconds"] >= 60]
        multiple = sum(len([c for c in candidates if c["wait_seconds"] >= 60]) > 1 for candidates in by_inbound.values())
        print(f"別列車・反対路線の全時刻組={len(connections)}組（全て同一service_day上で比較）; "
              f"待ち時間内訳={dict(buckets)}; 23時台着→24時以降発={midnight_crossings}組; "
              f"そのうち待ち1〜10分={near_midnight}組")
        for bucket in ("0分", "1分未満", "1分", "2分", "3分以上"):
            if bucket not in bucket_examples:
                continue
            c = bucket_examples[bucket]
            wait_minute = c["wait_seconds"] // 60
            print(f"  {bucket}例: {c['in_id']} 小竹向原着{c['in_kotake']['arrival_time']} → "
                  f"{c['out_id']} 小竹向原発{c['out_kotake']['departure_time']} → "
                  f"氷川台着{c['hikawadai']['arrival_time']} (待ち{wait_minute}分)")
        if midnight_example:
            c = midnight_example
            print(f"  日付跨ぎ例 (1〜10分の候補を例示): {c['in_id']} 小竹向原着{c['in_kotake']['arrival_time']} → "
                  f"{c['out_id']} 小竹向原発{c['out_kotake']['departure_time']} → "
                  f"氷川台着{c['hikawadai']['arrival_time']}")
        print(f"暫定基準1分以上={len(adopted)}組; 接続候補を1件以上持つ到着便={len({c['in_id'] for c in adopted})}; "
              f"1便に複数接続候補={multiple}到着便")
        print("1分以上の候補例 (到着trip_id / 小竹向原着 → 出発trip_id / 小竹向原発 → 氷川台着):")
        shown = set()
        for connection in sorted(adopted, key=lambda c: (c["wait_seconds"], c["in_kotake"]["arrival_time"], c["out_kotake"]["departure_time"])):
            pair = (connection["in_id"], connection["out_id"])
            if pair in shown:
                continue
            shown.add(pair)
            print(f"  {connection['in_id']} {connection['in_kotake']['arrival_time']} → "
                  f"{connection['out_id']} {connection['out_kotake']['departure_time']} → "
                  f"{connection['hikawadai']['arrival_time']} "
                  f"(待ち{connection['wait_seconds'] // 60}分, "
                  f"{connection['in_route']}→{connection['out_route']}, "
                  f"方面{connection['out_trip'].get('trip_headsign')})")
            if len(shown) == 5:
                break
        if not adopted:
            print("  該当なし")


if __name__ == "__main__":
    main()
