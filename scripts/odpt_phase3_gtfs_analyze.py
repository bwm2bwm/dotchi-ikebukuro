#!/usr/bin/env python3
"""Analyze locally placed Tokyo Metro GTFS ZIPs and compare with ODPT JSON.

No network access. Reads only local_data/odpt/*.zip and the existing ODPT JSON files.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
import re
import sys
import zipfile
from collections import Counter, defaultdict
from datetime import date, timedelta

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "local_data" / "odpt"
TARGETS = ("池袋", "小竹向原", "氷川台")
LINES = {"Yurakucho": "有楽町線", "Fukutoshin": "副都心線"}
ODPT_FILES = {
    "Yurakucho": DATA / "TrainTimetable_Yurakucho.json",
    "Fukutoshin": DATA / "TrainTimetable_Fukutoshin.json",
}


def read_csv(zf: zipfile.ZipFile, filename: str):
    members = [n for n in zf.namelist() if Path(n).name.lower() == filename.lower()]
    if not members:
        return None, []
    # GTFS filenames should be unique. Use the first, and report all locations.
    member = members[0]
    with zf.open(member) as stream:
        rows = list(csv.DictReader((line.decode("utf-8-sig") for line in stream)))
    return members, rows


def parse_date(s: str):
    try:
        return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    except (ValueError, TypeError):
        return None


def active_dates(cal_rows, exception_rows):
    active = set()
    for row in cal_rows:
        start, end = parse_date(row.get("start_date", "")), parse_date(row.get("end_date", ""))
        if not start or not end:
            continue
        d = start
        fields = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
        while d <= end:
            if row.get(fields[d.weekday()], "0") == "1":
                active.add((row.get("service_id", ""), d))
            d += timedelta(days=1)
    for row in exception_rows:
        d = parse_date(row.get("date", ""))
        if not d:
            continue
        key = (row.get("service_id", ""), d)
        typ = row.get("exception_type", "")
        if typ == "1":
            active.add(key)
        elif typ == "2":
            active.discard(key)
    return active


def active_dates_by_service(cal_rows, exception_rows):
    result = defaultdict(set)
    for sid, day in active_dates(cal_rows, exception_rows):
        result[sid].add(day)
    return result


def time_minutes(value):
    m = re.fullmatch(r"(\d{1,3}):(\d{2}):(\d{2})", value or "")
    # ODPT timetable objects use HH:MM; GTFS may use service times such as 24:11.
    if m:
        return (int(m[1]) * 60 + int(m[2])) % (24 * 60)
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", value or "")
    return (int(m[1]) * 60 + int(m[2])) % (24 * 60) if m else None


def odpt_train_number_from_gtfs_trip_id(trip_id):
    """Observed Tokyo Metro format: two-character prefix + number + two-char suffix."""
    if len(trip_id) != 10 or not re.fullmatch(r"\d{2}.*\d{2}", trip_id):
        return None
    return trip_id[2:-2]


def timepoint_class(row):
    if "timepoint" not in row:
        return "exact (timepoint column omitted)"
    if row.get("timepoint") == "1":
        return "exact"
    if row.get("timepoint") == "0":
        return "approx"
    return "unknown (blank/invalid timepoint)"


def line_guess(route):
    text = " ".join(route.get(k, "") for k in ("route_id", "route_short_name", "route_long_name", "route_desc"))
    low = text.lower()
    if "yurakucho" in low or "有楽町" in text:
        return "Yurakucho"
    if "fukutoshin" in low or "副都心" in text:
        return "Fukutoshin"
    return None


def read_odpt(line):
    path = ODPT_FILES[line]
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []


def odpt_candidates(line, calendar):
    rows = read_odpt(line)
    result = []
    for trip in rows:
        if trip.get("odpt:calendar", "").endswith(calendar) is False:
            continue
        objs = trip.get("odpt:trainTimetableObject", [])
        stations = [o.get("odpt:departureStation") or o.get("odpt:arrivalStation", "") for o in objs]
        names = [s.rsplit(".", 1)[-1] for s in stations]
        try:
            ix_ike = names.index("Ikebukuro")
        except ValueError:
            continue
        entry = objs[ix_ike]
        result.append({
            "number": trip.get("odpt:trainNumber", ""),
            "train": trip.get("odpt:train", ""),
            "calendar": calendar,
            "ike_departure": entry.get("odpt:departureTime", ""),
            "path": names,
            "destination": trip.get("odpt:destinationStation", []),
        })
    return result


def report_archive(path: Path):
    print(f"\n=== {path.name} ===")
    try:
        zf = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile):
        print("ZIPを開けません。解析をスキップします。")
        return
    with zf:
        tables = {}
        for name in ("agency.txt", "stops.txt", "routes.txt", "trips.txt", "stop_times.txt",
                     "calendar.txt", "calendar_dates.txt", "feed_info.txt"):
            members, rows = read_csv(zf, name)
            if members is not None:
                tables[name] = rows
                print(f"{name}: {len(rows)}行; files={members}; columns=" + ",".join(rows[0].keys() if rows else []))
            else:
                print(f"{name}: なし")

        feed = (tables.get("feed_info.txt") or [{}])[0]
        if feed:
            print("feed_info:", json.dumps({k: feed.get(k, "") for k in
                  ("feed_publisher_name", "feed_publisher_url", "feed_lang", "feed_start_date", "feed_end_date", "feed_version")}, ensure_ascii=False))
        stops = tables.get("stops.txt") or []
        routes = tables.get("routes.txt") or []
        trips = tables.get("trips.txt") or []
        stop_times = tables.get("stop_times.txt") or []
        calendars = tables.get("calendar.txt") or []
        exceptions = tables.get("calendar_dates.txt") or []
        active = active_dates(calendars, exceptions)
        active_by_service = active_dates_by_service(calendars, exceptions)
        if active:
            ds = [d for _, d in active]
            print(f"運行日適用範囲(calendar + exceptions): {min(ds)} .. {max(ds)} ({len(active)} service-date pairs)")
        else:
            print("運行日範囲: calendar/calendar_dates から復元できません。")
        print(f"calendar_dates例外件数={len(exceptions)} / 追加={sum(r.get('exception_type')=='1' for r in exceptions)} / 削除={sum(r.get('exception_type')=='2' for r in exceptions)}")

        station_ids = defaultdict(set)
        stop_by_id = {s.get("stop_id", ""): s for s in stops}
        for s in stops:
            name = s.get("stop_name", "")
            normalized = name.replace("駅", "").strip()
            if normalized in TARGETS:
                station_ids[normalized].add(s.get("stop_id", ""))
        # stop_times can reference platform children whose name is not the station name.
        for s in stops:
            parent = s.get("parent_station", "")
            ancestor = stop_by_id.get(parent, {})
            parent_name = ancestor.get("stop_name", "").replace("駅", "").strip()
            if parent_name in TARGETS:
                station_ids[parent_name].add(s.get("stop_id", ""))
        for name in TARGETS:
            print(f"駅 {name}: " + (", ".join(sorted(x for x in station_ids[name] if x)) or "該当なし"))

        route_by_id = {r.get("route_id", ""): r for r in routes}
        trip_by_id = {t.get("trip_id", ""): t for t in trips}
        times_by_trip = defaultdict(list)
        for row in stop_times:
            times_by_trip[row.get("trip_id", "")].append(row)
        for rows in times_by_trip.values():
            rows.sort(key=lambda r: int(r.get("stop_sequence") or 0))

        # Route discovery is explicit, then only trips assigned to those route_ids are inspected.
        target_routes = {rid: line_guess(r) for rid, r in route_by_id.items() if line_guess(r)}
        if not target_routes:
            print("有楽町線/副都心線 route_idを名称から判別できません。路線名とroute_id:")
            for r in routes:
                print("  " + json.dumps(r, ensure_ascii=False))
            return
        print("対象routes:")
        for rid, line in target_routes.items():
            r = route_by_id[rid]
            print(f"  {LINES[line]} route_id={rid} short={r.get('route_short_name','')} long={r.get('route_long_name','')}")

        indexes = defaultdict(list)
        for trip in trips:
            line = target_routes.get(trip.get("route_id", ""))
            if line:
                indexes[line].append(trip)
        for line, ja in LINES.items():
            print(f"\n[{ja}] trips={len(indexes[line])}")
            local_stops = station_ids
            candidates = []
            for trip in indexes[line]:
                tid = trip.get("trip_id", "")
                seq = times_by_trip.get(tid, [])
                by_name = {}
                for row in seq:
                    matched = [n for n, ids in local_stops.items() if row.get("stop_id") in ids]
                    if matched:
                        by_name[matched[0]] = row
                if "池袋" not in by_name:
                    continue
                candidates.append((trip, by_name, seq))
            print(f"池袋停車便={len(candidates)}")
            direct = []
            to_kotake = []
            for trip, by_name, seq in candidates:
                if "氷川台" in by_name and seq.index(by_name["池袋"]) < seq.index(by_name["氷川台"]):
                    direct.append((trip, by_name))
                if "小竹向原" in by_name and seq.index(by_name["池袋"]) < seq.index(by_name["小竹向原"]):
                    to_kotake.append((trip, by_name))
            print(f"池袋→氷川台停車便={len(direct)} / 池袋→小竹向原停車便={len(to_kotake)}")
            direct_arrivals = sum(bool(by_name['氷川台'].get('arrival_time')) for _, by_name in direct)
            kotake_arrivals = sum(bool(by_name['小竹向原'].get('arrival_time')) for _, by_name in to_kotake)
            print(f"記録された到着時刻: 氷川台 {direct_arrivals}/{len(direct)}, 小竹向原 {kotake_arrivals}/{len(to_kotake)}")
            for station, group in (("氷川台", direct), ("小竹向原", to_kotake)):
                precision = Counter()
                for _, by_name in group:
                    row = by_name[station]
                    if not row.get("arrival_time"):
                        precision["arrival_timeなし"] += 1
                    elif timepoint_class(row).startswith("approx"):
                        precision["概算/補間"] += 1
                    elif timepoint_class(row).startswith("exact"):
                        precision["正確"] += 1
                    else:
                        precision["timepoint未確定"] += 1
                print(f"{station} arrival_time精度内訳: {dict(precision)}")
            if line == "Fukutoshin":
                missing_hikawadai = [
                    (trip, by_name["氷川台"]) for trip, by_name in direct
                    if not by_name["氷川台"].get("arrival_time")
                ]
                print(f"氷川台到着時刻なし詳細={len(missing_hikawadai)}件:")
                for trip, row in missing_hikawadai:
                    print("  " + json.dumps({
                        "trip_id": trip.get("trip_id"), "service_id": trip.get("service_id"),
                        "stop_id": row.get("stop_id"), "stop_sequence": row.get("stop_sequence"),
                        "arrival_time": row.get("arrival_time"), "departure_time": row.get("departure_time"),
                        "pickup_type": row.get("pickup_type"), "drop_off_type": row.get("drop_off_type"),
                        "timepoint": row.get("timepoint"),
                    }, ensure_ascii=False))
            for label, found, destination in (("直通", direct, "氷川台"), ("小竹向原到着確認", to_kotake, "小竹向原")):
                print(f"{label}サンプル:")
                for trip, by_name in found[:4]:
                    start, end = by_name["池袋"], by_name[destination]
                    def exactness(row, field):
                        if not row.get(field):
                            return "not recorded"
                        return timepoint_class(row)
                    number = trip.get("trip_short_name") or trip.get("trip_id", "")
                    print("  " + json.dumps({
                        "trip": number, "trip_id": trip.get("trip_id"), "service_id": trip.get("service_id"),
                        "池袋": {"arrival": start.get("arrival_time"), "departure": start.get("departure_time"), "timepoint": start.get("timepoint", "(省略=1)"), "classification": exactness(start, "departure_time")},
                        destination: {"arrival": end.get("arrival_time"), "departure": end.get("departure_time"), "timepoint": end.get("timepoint", "(省略=1)"), "classification": exactness(end, "arrival_time")},
                    }, ensure_ascii=False))

            # Validate the observed GTFS trip_id extraction against same-direction ODPT trips.
            for cal, label, service_id in (("Weekday", "平日", "0"), ("SaturdayHoliday", "土休日", "1")):
                odpt = [o for o in odpt_candidates(line, cal)
                        if "Hikawadai" in o["path"] and o["path"].index("Ikebukuro") < o["path"].index("Hikawadai")]
                odpt_index = defaultdict(list)
                for o in odpt:
                    odpt_index[o["number"]].append(o)
                counts = Counter()
                time_equal = 0
                for trip, by_name in direct:
                    if trip.get("service_id") != service_id:
                        continue
                    number = odpt_train_number_from_gtfs_trip_id(trip.get("trip_id", ""))
                    matches = odpt_index.get(number, []) if number else []
                    counts[len(matches)] += 1
                    if len(matches) == 1:
                        gtfs_departure = time_minutes(by_name["池袋"].get("departure_time", ""))
                        odpt_departure = time_minutes(matches[0].get("ike_departure", ""))
                        if gtfs_departure is not None and gtfs_departure == odpt_departure:
                            time_equal += 1
                print(f"ODPT照合({label}): GTFS直通便={sum(counts.values())}, "
                      f"列車番号中央部+路線+運行日区分の一意候補={counts[1]}, "
                      f"複数候補={sum(v for n, v in counts.items() if n > 1)}, "
                      f"候補なし={counts[0]}, 一意候補中の池袋発時刻一致={time_equal}")

        # Detailed calendar exception effect, which supplements weekday-only ODPT calendar labels.
        if exceptions:
            by_type = Counter(r.get("exception_type", "") for r in exceptions)
            print("calendar_dates exception_type counts:", dict(by_type))
            for row in exceptions[:8]:
                print("  exception sample:", json.dumps(row, ensure_ascii=False))
        print("注意: GTFS arrival/departure values and timepoint are reported as encoded; no missing time is estimated by this script.")


def main():
    archives = sorted(DATA.glob("*.zip"))
    if not archives:
        print("GTFS ZIPが local_data/odpt/ にありません。実データ解析は未実施です。")
        print("取得したZIPを配置後、このスクリプトを再実行してください。")
        return 0
    for path in archives:
        report_archive(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
