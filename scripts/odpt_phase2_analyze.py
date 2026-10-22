#!/usr/bin/env python3
"""Inspect locally acquired ODPT JSON and any GTFS ZIP; never invent missing data."""

from collections import Counter
from pathlib import Path
import csv
import json
import sys
import zipfile

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "local_data" / "odpt"
STATION_NAMES = ("池袋", "小竹向原", "氷川台", "要町", "千川", "平和台",
                 "地下鉄赤塚", "地下鉄成増", "和光市", "新桜台", "練馬")


def keys_in(value, counts):
    if isinstance(value, dict):
        counts.update(value.keys())
        for child in value.values(): keys_in(child, counts)
    elif isinstance(value, list):
        for child in value: keys_in(child, counts)


def json_report():
    files = sorted(DATA.glob("*.json"))
    if not files:
        print("ODPT JSON: local_data/odpt/*.json がありません。取得後に再実行してください。")
        return False
    stations = []
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            print(f"{path.name}: 読み込みエラー")
            continue
        if not isinstance(data, list):
            print(f"{path.name}: JSON配列ではありません")
            continue
        fields = Counter()
        for row in data: keys_in(row, fields)
        print(f"\n[{path.name}] records={len(data)}")
        print("主要フィールド:", ", ".join(f"{k}({n})" for k, n in fields.most_common(24)) or "なし")
        if path.name.startswith("Station_"):
            stations.extend(x for x in data if isinstance(x, dict))
        if data and path.name.startswith(("TrainTimetable", "StationTimetable")):
            sample = data[0]
            print("サンプルID:", sample.get("@id", "未確認"))
            print("運行日/曜日関連キー:", ", ".join(k for k in sample if any(t in k.lower() for t in ("calendar", "weekday", "holiday", "valid", "date"))) or "未確認")
    print("\n対象駅の駅情報レコード:")
    found = set()
    for row in stations:
        names = row.get("dc:title", {})
        name = names.get("ja") if isinstance(names, dict) else names
        if name in STATION_NAMES:
            found.add(name)
            print(f"- {name}: {row.get('@id', 'ID未確認')} / 路線参照={row.get('odpt:railway', '未確認')}")
    if not found: print("- 該当レコードなし（駅情報が含まれるJSONを確認してください）")
    print("対象駅名確認:", "、".join(x for x in STATION_NAMES if x in found) or "該当なし")
    print("旅程判定: 実フィールド構造を確認する段階です。未知のフィールド意味を推測して便・接続を生成しません。")
    return True


def gtfs_report():
    archives = sorted(DATA.glob("*.zip"))
    if not archives:
        print("\nGTFS: ZIP未配置のため未解析です。実際のCKAN配布URL・認証条件は別途確認が必要です。")
        return
    for archive in archives:
        print(f"\n[GTFS {archive.name}]")
        try:
            with zipfile.ZipFile(archive) as zf:
                names = zf.namelist()
                print("ZIP内ファイル:", ", ".join(names))
                tables = {}
                for member in names:
                    if Path(member).name.lower().endswith(".txt"):
                        with zf.open(member) as f:
                            reader = csv.DictReader((line.decode("utf-8-sig") for line in f))
                            rows = list(reader)
                        tables[Path(member).name.lower()] = rows
                        print(f"{member}: rows={len(rows)}, fields={','.join(reader.fieldnames or [])}")
                stops = tables.get("stops.txt", [])
                targets = {r.get("stop_id"): r.get("stop_name", "") for r in stops
                           if any(n in r.get("stop_name", "") for n in STATION_NAMES)}
                print("対象駅候補:", ", ".join(f"{n} ({sid})" for sid, n in targets.items()) or "該当なし")
                for cal in ("calendar.txt", "calendar_dates.txt"):
                    rows = tables.get(cal)
                    if rows:
                        dates = [r.get(k, "") for r in rows for k in ("start_date", "end_date", "date") if r.get(k)]
                        print(f"{cal} 有効日範囲:", f"{min(dates)}–{max(dates)}" if dates else "日付フィールドなし")
                info = tables.get("feed_info.txt", [])
                if info: print("feed_info:", json.dumps(info[:2], ensure_ascii=False))
                if not targets: print("対象駅・対象路線の収録は確認できませんでした。")
                gtfs_journeys(tables, targets)
        except (OSError, zipfile.BadZipFile, UnicodeError, csv.Error):
            print("ZIP読み込みエラー")


def gtfs_journeys(tables, targets):
    """Build timetable-only journey candidates only if the archive has needed columns."""
    times = tables.get("stop_times.txt")
    trips = tables.get("trips.txt")
    if times is None or trips is None:
        print("旅程候補: trips.txt / stop_times.txt が揃わないため未生成")
        return
    if not times or not trips:
        print("旅程候補: trips.txt / stop_times.txt にレコードがありません")
        return
    required = {"trip_id", "stop_id", "stop_sequence", "arrival_time", "departure_time"}
    if not required.issubset(times[0]) or not {"trip_id", "service_id"}.issubset(trips[0]):
        print("旅程候補: 必要列が実ファイルに揃わないため未生成")
        return
    name_to_ids = {}
    for sid, name in targets.items(): name_to_ids.setdefault(name, set()).add(sid)
    def ids(name): return name_to_ids.get(name, set())
    if not ids("池袋") or not ids("氷川台") or not ids("小竹向原"):
        print("池袋→氷川台: 対象駅ID不足のため旅程候補は未生成")
        return
    by_trip = {}
    for row in times:
        by_trip.setdefault(row["trip_id"], []).append(row)
    trip_meta = {r["trip_id"]: r for r in trips}
    for rows in by_trip.values(): rows.sort(key=lambda r: int(r["stop_sequence"]))
    def route(tid, start_name, end_name):
        rows = by_trip.get(tid, [])
        start_ix = next((i for i, r in enumerate(rows) if r["stop_id"] in ids(start_name)), None)
        if start_ix is None: return None
        end_ix = next((i for i in range(start_ix + 1, len(rows)) if rows[i]["stop_id"] in ids(end_name)), None)
        if end_ix is None: return None
        a, b = rows[start_ix], rows[end_ix]
        return (a.get("departure_time", ""), b.get("arrival_time", ""), trip_meta.get(tid, {}).get("service_id", ""), tid)
    found = {"direct": [], "transfer": []}
    for tid in by_trip:
        candidate = route(tid, "池袋", "氷川台")
        if candidate: found["direct"].append(candidate)
    # Candidate transfer requires two distinct trips. Service IDs must match;
    # transfer time is reported only as a clock comparison, never feasibility.
    legs_to = [route(tid, "池袋", "小竹向原") for tid in by_trip]
    legs_from = [route(tid, "小竹向原", "氷川台") for tid in by_trip]
    legs_to = [x for x in legs_to if x]
    legs_from = [x for x in legs_from if x]
    transfer = []
    def seconds(t):
        try:
            h, m, s = map(int, t.split(":")); return h * 3600 + m * 60 + s
        except (ValueError, AttributeError): return None
    for a in legs_to:
        for b in legs_from:
            gap_a, gap_b = seconds(a[1]), seconds(b[0])
            if a[3] != b[3] and a[2] == b[2] and gap_a is not None and gap_b is not None and gap_b >= gap_a:
                transfer.append((a, b, gap_b - gap_a))
    print("\n池袋→氷川台のGTFS時刻表候補:")
    print(f"- 同一便直通候補: {len(found['direct'])}")
    for dep, arr, service, tid in found["direct"][:12]:
        print(f"  {dep} → {arr}; service_id={service}; trip_id={tid}")
    print(f"- 小竹向原の別便乗換時刻候補: {len(transfer)}")
    for a, b, gap in transfer[:12]:
        print(f"  {a[0]} / 小竹向原 {a[1]} → {b[0]} / 氷川台 {b[1]}; 待ち={gap // 60}分{gap % 60}秒; service_id={a[2]}")
    print("注: 同一service_idと時刻順による候補のみ。日付適用、ホーム、必要乗換時間を確認できないため乗換可能とは判定しません。")


def main():
    json_report()
    gtfs_report()
    return 0


if __name__ == "__main__":
    sys.exit(main())
