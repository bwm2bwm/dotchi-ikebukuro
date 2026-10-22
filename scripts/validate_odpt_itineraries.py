#!/usr/bin/env python3
"""Offline validation report for the local GTFS itinerary generator."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date
from pathlib import Path
import sys

from odpt_itinerary import (DEFAULT_GTFS, DEFAULT_DATA_DIR, FeedDateError,
                            ItineraryGenerator, format_service_time)


REPRESENTATIVE_DATES = ("2026-10-22", "2026-10-24", "2026-11-03")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dates", nargs="*", default=list(REPRESENTATIVE_DATES))
    parser.add_argument("--gtfs", type=Path, default=DEFAULT_GTFS)
    parser.add_argument("--odpt-dir", type=Path, default=DEFAULT_DATA_DIR)
    args = parser.parse_args()

    try:
        generator = ItineraryGenerator(args.gtfs, args.odpt_dir)
    except (OSError, ValueError) as exc:
        print(f"読込エラー: {exc}", file=sys.stderr)
        return 2

    print(f"feed_version={generator.feed_version}; 有効期間={generator.feed_start}..{generator.feed_end}; "
          f"乗換条件={generator.min_transfer_seconds}..{generator.max_transfer_seconds}秒")
    for raw_day in args.dates:
        try:
            day = date.fromisoformat(raw_day)
            results = generator.generate(day)
        except FeedDateError as exc:
            print(f"{raw_day}: 期間外（候補なし）: {exc}")
            continue
        except ValueError as exc:
            print(f"{raw_day}: 日付エラー: {exc}", file=sys.stderr)
            return 2

        service_ids = sorted(generator.active_service_ids(day))
        primary = Counter(result.primary_itinerary.kind if result.primary_itinerary else "none" for result in results)
        status = Counter(result.status for result in results)
        direct_count = sum(result.direct_alternative is not None for result in results)
        transfer_count = sum(result.best_transfer_alternative is not None for result in results)
        multiple = sum(result.transfer_candidates_count > 1 for result in results)
        arrival_missing = sum("destination_arrival_missing" in result.data_quality for result in results)
        alighting_prohibited = sum("destination_alighting_prohibited" in result.data_quality for result in results)
        midnight = sum(
            result.primary_itinerary is not None and result.primary_itinerary.arrival_seconds >= 86400
            for result in results
        )
        print(f"\n{day} service_id={','.join(service_ids) or '(なし)'} 池袋発={len(results)} "
              f"直通有効={direct_count} 乗換候補あり={transfer_count} 複数接続={multiple} "
              f"代表候補={dict(primary)} 状態={dict(status)} "
              f"氷川台時刻欠損={arrival_missing} 降車不可={alighting_prohibited} "
              f"代表旅程の24時超到着={midnight} "
              f"10分以内全組={generator.last_raw_transfer_pairs} "
              f"（60〜600秒={sum(count for wait, count in generator.last_wait_histogram.items() if 60 <= wait <= 600)}） "
              f"0/1/2分={generator.last_wait_histogram.get(0, 0)}/"
              f"{generator.last_wait_histogram.get(60, 0)}/"
              f"{generator.last_wait_histogram.get(120, 0)}")
        for result in results:
            itinerary = result.primary_itinerary
            if itinerary is None or itinerary.arrival_seconds < 86400:
                continue
            if itinerary.kind == "transfer" and itinerary.second_leg:
                print(f"  日付跨ぎ例: {result.departure_text} {result.origin_trip_id} → "
                      f"小竹向原{format_service_time(itinerary.first_leg.alight.arrival_seconds)}着／"
                      f"{format_service_time(itinerary.second_leg.board.departure_seconds)}発 → "
                      f"氷川台{itinerary.arrival_text}（service day基準）")
            else:
                print(f"  日付跨ぎ例: {result.departure_text} {result.origin_trip_id} → "
                      f"氷川台{itinerary.arrival_text}")
            break
        for result in results:
            if result.status == "transfer_only" and result.primary_itinerary:
                print(f"  乗換のみ例: 池袋{result.departure_text} → 小竹向原待ち"
                      f"{result.primary_itinerary.transfer_wait_seconds}秒 → "
                      f"氷川台{result.primary_itinerary.arrival_text}")
                break
        for result in results:
            if result.transfer_candidates_count > 1:
                print(f"  複数接続例: 池袋{result.departure_text} {result.origin_trip_id}; "
                      f"接続{result.transfer_candidates_count}候補を最早着1件に集約")
                break

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
