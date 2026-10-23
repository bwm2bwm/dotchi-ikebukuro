#!/usr/bin/env python3
"""Export minimal UI-facing timetable data outside the repository for local review."""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import json
from pathlib import Path
import tempfile
import sys

from odpt_itinerary import DEFAULT_DATA_DIR, DEFAULT_GTFS, FeedDateError, ItineraryGenerator


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = Path(tempfile.gettempdir()) / "dotchi-ikebukuro-local" / "timetable.json"


def _journey(itinerary):
    if itinerary is None:
        return None
    second_trip = itinerary.second_leg.trip if itinerary.second_leg else None
    resolution = second_trip.type_resolution if second_trip else None
    return {
        "kind": itinerary.kind,
        "departureServiceSeconds": itinerary.departure_seconds,
        "arrivalServiceSeconds": itinerary.arrival_seconds,
        "departureText": itinerary.departure_text,
        "arrivalText": itinerary.arrival_text,
        "arrivalStationId": "Hikawadai",
        "transfer": None if second_trip is None else {
            "stationId": "KotakeMukaihara",
            "stationName": itinerary.transfer_station,
            "waitSeconds": itinerary.transfer_wait_seconds,
            "outgoingRouteId": second_trip.route_id,
            "outgoingRouteName": second_trip.route_name,
            "outgoingHeadsign": second_trip.headsign,
            "outgoingTrainType": resolution.train_type if resolution else None,
            "outgoingReportedTrainType": resolution.reported_train_type if resolution else None,
            "outgoingServiceBrand": resolution.service_brand if resolution else None,
            "outgoingOdptTrainTypeUri": second_trip.odpt.raw_train_type_uri if second_trip.odpt else None,
            "outgoingOtherOperatorType": second_trip.odpt.other_operator_type if second_trip.odpt else None,
            "outgoingUnscopedTrainType": second_trip.odpt.unscoped_through_service_type if second_trip.odpt else None,
            "outgoingTypeLabel": resolution.label if resolution else "種別不明",
            "outgoingTypeSource": resolution.source if resolution else "unknown",
            "outgoingStopPattern": resolution.stop_pattern if resolution else "unclassifiable",
            "outgoingTypeValidation": resolution.validation if resolution else "unverifiable",
            "outgoingDestinationIds": list(second_trip.odpt.destination) if second_trip.odpt else [],
            "outgoingMatchMethod": second_trip.odpt.match_method if second_trip.odpt else None,
            "outgoingMatchReason": second_trip.odpt.match_reason if second_trip.odpt else None,
        },
        "platformStatus": itinerary.platform_status,
        "connectionGuaranteed": itinerary.connection_guaranteed,
    }


def build_payload(generator: ItineraryGenerator, service_dates: list[str]) -> dict:
    day_payloads = []
    excluded_dates = []
    for raw_day in service_dates:
        day = date.fromisoformat(raw_day)
        try:
            results = generator.generate(day)
        except FeedDateError:
            excluded_dates.append(day.isoformat())
            continue
        day_payloads.append({
            "serviceDate": day.isoformat(),
            "originStationId": "Ikebukuro",
            "destinationStationId": "Hikawadai",
            "departures": [{
                "id": f"{result.service_date}:{result.origin_trip_id}",
                "originTripId": result.origin_trip_id,
                "routeId": result.route_id,
                "routeName": result.route_name,
                "headsign": result.headsign,
                "trainType": result.type_resolution.train_type,
                "reportedTrainType": result.type_resolution.reported_train_type,
                "serviceBrand": result.type_resolution.service_brand,
                "odptTrainTypeUri": result.odpt.raw_train_type_uri,
                "otherOperatorTrainType": result.odpt.other_operator_type,
                "unscopedTrainType": result.odpt.unscoped_through_service_type,
                "odptMatchMethod": result.odpt.match_method,
                "odptMatchReason": result.odpt.match_reason,
                "typeLabel": result.type_resolution.label,
                "typeSource": result.type_resolution.source,
                "stopPattern": result.type_resolution.stop_pattern,
                "stopPatternStates": dict(result.type_resolution.pattern_states),
                "typeValidation": result.type_resolution.validation,
                "typeDiagnostic": result.type_resolution.diagnostic,
                "destination": result.headsign,
                "destinationSource": "gtfs_headsign",
                "odptDestinationIds": list(result.odpt.destination),
                "odptMatchStatus": result.odpt.status,
                "departureServiceSeconds": result.departure_seconds,
                "departureText": result.departure_text,
                "primary": _journey(result.primary_itinerary),
                "directAlternative": _journey(result.direct_alternative),
                "bestTransferAlternative": _journey(result.best_transfer_alternative),
                "transferCandidateCount": result.transfer_candidates_count,
                "status": result.status,
                "dataQuality": list(result.data_quality),
            } for result in results],
        })
    return {
        "schemaVersion": 1,
        "dataScope": "local-preview-only",
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "timezone": "Asia/Tokyo",
        "feed": {
            "version": generator.feed_version,
            "validFrom": generator.feed_start.isoformat(),
            "validThrough": generator.feed_end.isoformat(),
            # Source publication timestamps are not present in the local feed files.
            "sourceUpdatedAt": None,
        },
        "odpt": {"sourceUpdatedAt": None},
        "applicationPeriod": {
            "startsAt": f"{generator.feed_start.isoformat()}T00:00:00+09:00",
            # GTFS end_date is inclusive; represent its exclusive instant explicitly.
            "endsAt": f"{date.fromordinal(generator.feed_end.toordinal() + 1).isoformat()}T00:00:00+09:00",
        },
        "webApp": {"builtAt": None},
        "connectionPolicy": {
            "minimumWaitSeconds": generator.min_transfer_seconds,
            "maximumWaitSeconds": generator.max_transfer_seconds,
            "platformStatus": "unknown",
            "connectionGuaranteed": False,
        },
        "serviceDays": day_payloads,
        "excludedServiceDates": excluded_dates,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service-date", action="append", required=True,
                        help="GTFS運行日 YYYY-MM-DD（複数回指定可）")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT,
                        help=f"リポジトリ外の出力先（既定: {DEFAULT_OUTPUT}）")
    parser.add_argument("--gtfs", type=Path, default=DEFAULT_GTFS)
    parser.add_argument("--odpt-dir", type=Path, default=DEFAULT_DATA_DIR)
    args = parser.parse_args()

    output = args.output.expanduser().resolve()
    if output == ROOT or ROOT in output.parents:
        print("出力先はリポジトリ外を指定してください。", file=sys.stderr)
        return 2
    try:
        generator = ItineraryGenerator(args.gtfs, args.odpt_dir)
        payload = build_payload(generator, args.service_date)
    except (OSError, ValueError) as exc:
        print(f"生成エラー: {exc}", file=sys.stderr)
        return 2

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    departures = sum(len(day["departures"]) for day in payload["serviceDays"])
    print(f"ローカル表示用データを出力: {output} (運行日{len(payload['serviceDays'])}日、池袋発{departures}便)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
