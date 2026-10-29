#!/usr/bin/env python3
"""Create a private, local-only public-display-v2 candidate from a saved snapshot.

This tool never accesses a network. Candidate JSON and its private provenance
manifest are written atomically outside the repository and source snapshot.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import odpt_snapshot_qa as snapshot_qa
from odpt_itinerary import DESTINATIONS, FeedDateError, ItineraryGenerator

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = 2
DATA_SCOPE = "public-display-v2"
MANIFEST_SCOPE = "private-odpt-public-display-v2-candidate-manifest"
ROUTES = ("6", "9")
ROUTE_FILENAMES = {key: f"timetable-{key}.json" for key in DESTINATIONS}
PUBLIC_ID_PATTERN = re.compile(r"p2-[0-9a-f]{32}\Z")
EXCLUSION_REASONS = ("explicit_pass_info", "no_valid_arrival", "primary_arrival_missing",
                     "quality_warning", "unknown")
EXCLUSION_CLASSIFICATIONS = ("INFO", "WARNING", "UNKNOWN")


class V2Error(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def public_id(station_id: str, service_date: str, public_journey: dict[str, Any]) -> str:
    """Create the deterministic, source-ID-free v2 ID from public content."""
    if "id" in public_journey:
        public_journey = {key: value for key, value in public_journey.items() if key != "id"}
    preimage = {"stationId": station_id, "serviceDate": service_date,
                "publicJourney": public_journey}
    return "p2-" + _sha256(_canonical(preimage))[:32]


def _strict_date(value: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError):
        raise V2Error("service_date_invalid") from None
    if parsed.isoformat() != value:
        raise V2Error("service_date_invalid")
    return parsed


def _inventory(snapshot: Path) -> tuple[list[dict[str, Any]], str, dict[str, Any]]:
    try:
        entries, source_meta = snapshot_qa._inventory(snapshot)
    except snapshot_qa.QAError as exc:
        raise V2Error(f"snapshot_{exc.code}") from None
    return entries, snapshot_qa._fingerprint(entries), source_meta


def _source_generator_fingerprint() -> str:
    paths = [Path(__file__), Path(__import__("odpt_itinerary").__file__),
             Path(__import__("odpt_stop_patterns").__file__),
             Path(__import__("export_local_timetable_payload").__file__),
             Path(__import__("odpt_snapshot_qa").__file__)]
    entries = [{"name": path.name, "sha256": _sha256(path.read_bytes())} for path in paths]
    return _sha256(_canonical(entries))


def _journey(itinerary: Any) -> dict[str, Any] | None:
    if itinerary is None:
        return None
    if itinerary.kind == "direct":
        transfer = None
    elif itinerary.kind == "transfer":
        second = itinerary.second_leg.trip if itinerary.second_leg else None
        if second is None:
            raise V2Error("transfer_leg_missing")
        transfer = {"stationId": "KotakeMukaihara",
                    "waitSeconds": itinerary.transfer_wait_seconds,
                    "outgoingRouteId": str(second.route_id)}
    else:
        raise V2Error("journey_kind_invalid")
    return {"kind": itinerary.kind,
            "departureServiceSeconds": itinerary.departure_seconds,
            "arrivalServiceSeconds": itinerary.arrival_seconds,
            "transfer": transfer}


def _safe_nonnegative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _route_state(route_id: str, route_metrics: Any, results: list[Any]) -> dict[str, Any]:
    if not isinstance(route_metrics, dict):
        return {"scheduledTripCount": 0, "dataState": "unknown"}
    scheduled = route_metrics.get("scheduledTripCount")
    origin_count = route_metrics.get("originTripCount")
    data_issues = route_metrics.get("dataInsufficientCount")
    transfer_issues = route_metrics.get("transferDataInsufficientCount")
    required = (scheduled, origin_count, data_issues, transfer_issues)
    if not all(_safe_nonnegative_int(value) for value in required):
        return {"scheduledTripCount": scheduled if _safe_nonnegative_int(scheduled) else 0,
                "dataState": "unknown"}
    route_results = [row for row in results if str(row.route_id) == route_id]
    # scheduledTripCount covers active GTFS trips on the route, not departures
    # emitted by this destination-specific generator.
    if scheduled == 0:
        state = "unknown"
    elif data_issues or transfer_issues or origin_count != len(route_results):
        state = "insufficient"
    else:
        from odpt_snapshot_qa import _classify_diagnostics
        warnings = any(_classify_diagnostics(row)["WARNING"] for row in route_results)
        unresolved_match = any(row.odpt.status not in {"matched", "unique_match"}
                              for row in route_results)
        state = "insufficient" if warnings or unresolved_match else "complete"
    return {"scheduledTripCount": scheduled, "dataState": state}


def _public_departure(result: Any) -> dict[str, Any] | None:
    primary = _journey(result.primary_itinerary)
    if primary is None or primary["arrivalServiceSeconds"] is None:
        return None
    direct = _journey(result.direct_alternative)
    transfer = _journey(result.best_transfer_alternative)
    if direct is not None and direct["kind"] != "direct":
        raise V2Error("direct_alternative_invalid")
    if transfer is not None and transfer["kind"] != "transfer":
        raise V2Error("transfer_alternative_invalid")
    if primary != (direct if primary["kind"] == "direct" else transfer):
        raise V2Error("primary_alternative_mismatch")
    return {"routeId": str(result.route_id),
            "destination": result.headsign,
            "displayType": result.type_resolution.label,
            "departureServiceSeconds": result.departure_seconds,
            "primary": primary,
            "directAlternative": direct,
            "bestTransferAlternative": transfer}


def _journey_signature(row: dict[str, Any]) -> bytes:
    return _canonical(row)


def _empty_exclusion_counts() -> tuple[dict[str, int], dict[str, int]]:
    return ({reason: 0 for reason in EXCLUSION_REASONS},
            {classification: 0 for classification in EXCLUSION_CLASSIFICATIONS})


def _exclusion_detail(result: Any) -> tuple[str, str]:
    """Classify omissions conservatively without retaining trip identifiers."""
    codes = set(result.data_quality)
    from odpt_snapshot_qa import _classify_diagnostics
    warning_codes = _classify_diagnostics(result)["WARNING"]
    if "destination_explicit_pass" in codes and not warning_codes:
        return "explicit_pass_info", "INFO"
    if warning_codes:
        return "quality_warning", "WARNING"
    if result.primary_itinerary is not None:
        return "primary_arrival_missing", "UNKNOWN"
    if result.status == "no_valid_arrival" and not codes:
        return "no_valid_arrival", "UNKNOWN"
    return "unknown", "UNKNOWN"


def _build_station_payload(generator: ItineraryGenerator, station_id: str,
                           service_dates: list[str], generated_at: str) -> tuple[dict[str, Any], dict[str, Any]]:
    days: list[dict[str, Any]] = []
    metrics: dict[str, Any] = {"itineraryResultCount": 0,
                               "odptMatchStatusCounts": collections.Counter(),
                               "primaryDirectCount": 0, "primaryTransferCount": 0,
                               "exclusionAudit": []}
    for service_date in service_dates:
        day = _strict_date(service_date)
        try:
            results = generator.generate(day)
        except FeedDateError:
            raise V2Error("requested_service_date_outside_feed") from None
        metrics["itineraryResultCount"] += len(results)
        metrics["odptMatchStatusCounts"].update(row.odpt.status for row in results)
        metrics["primaryDirectCount"] += sum(row.primary_itinerary is not None
                                              and row.primary_itinerary.kind == "direct" for row in results)
        metrics["primaryTransferCount"] += sum(row.primary_itinerary is not None
                                                and row.primary_itinerary.kind == "transfer" for row in results)
        status = generator.last_destination_status
        routes = status.get("routes") if isinstance(status, dict) else None
        if not isinstance(routes, dict):
            routes = {}
        route_coverage = {route: _route_state(route, routes.get(route), results) for route in ROUTES}
        public_rows = []
        reason_counts, classification_counts = _empty_exclusion_counts()
        for result in results:
            public_row = _public_departure(result)
            if public_row is not None:
                public_rows.append(public_row)
            else:
                reason, classification = _exclusion_detail(result)
                reason_counts[reason] += 1
                classification_counts[classification] += 1
        public_rows.sort(key=lambda row: (row["departureServiceSeconds"], row["routeId"],
                                          _journey_signature(row)))
        seen_signatures: set[bytes] = set()
        seen_ids: set[str] = set()
        for row in public_rows:
            signature = _journey_signature(row)
            if signature in seen_signatures:
                raise V2Error("duplicate_public_journey")
            seen_signatures.add(signature)
            row_id = public_id(station_id, service_date, row)
            if row_id in seen_ids:
                raise V2Error("public_id_collision")
            seen_ids.add(row_id)
            row["id"] = row_id
        # Keep public rows sorted after adding their IDs; no source trip IDs are
        # used for ordering, identity, or tie-breaking.
        public_rows.sort(key=lambda row: (row["departureServiceSeconds"], row["routeId"], row["id"]))
        days.append({"serviceDate": service_date, "routeCoverage": route_coverage,
                     "departures": public_rows})
        metrics["exclusionAudit"].append({
            "stationId": station_id, "serviceDate": service_date,
            "generatedCount": len(results), "candidateCount": len(public_rows),
            "excludedCount": len(results) - len(public_rows),
            "classificationCounts": classification_counts,
            "reasonCounts": reason_counts,
        })
    return ({"schemaVersion": SCHEMA_VERSION, "dataScope": DATA_SCOPE,
            "generatedAt": generated_at, "timezone": "Asia/Tokyo",
            # Public applicability has not been approved. Null is intentional;
            # the separate QA evaluation window is kept only in the manifest.
            "applicationPeriod": None, "stationId": station_id,
            "originStationId": "Ikebukuro", "serviceDays": days}, metrics)


def _exact_fields(value: Any, required: set[str], path: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != required:
        raise V2Error(f"{path}_fields_invalid")
    return value


def _validate_journey(value: Any, path: str, expected_kind: str | None = None) -> None:
    if value is None:
        if expected_kind:
            return
        raise V2Error(f"{path}_missing")
    journey = _exact_fields(value, {"kind", "departureServiceSeconds", "arrivalServiceSeconds", "transfer"}, path)
    kind = journey["kind"]
    if kind not in {"direct", "transfer"} or (expected_kind and kind != expected_kind):
        raise V2Error(f"{path}_kind_invalid")
    depart, arrive = journey["departureServiceSeconds"], journey["arrivalServiceSeconds"]
    if not _safe_nonnegative_int(depart) or not _safe_nonnegative_int(arrive) or arrive < depart:
        raise V2Error(f"{path}_time_invalid")
    transfer = journey["transfer"]
    if kind == "direct":
        if transfer is not None:
            raise V2Error(f"{path}_transfer_must_be_null")
    else:
        transfer = _exact_fields(transfer, {"stationId", "waitSeconds", "outgoingRouteId"},
                                 f"{path}_transfer")
        if transfer["stationId"] != "KotakeMukaihara":
            raise V2Error(f"{path}_transfer_station_invalid")
        if not _safe_nonnegative_int(transfer["waitSeconds"]) or not 60 <= transfer["waitSeconds"] <= 600:
            raise V2Error(f"{path}_transfer_wait_invalid")
        if transfer["outgoingRouteId"] not in ROUTES:
            raise V2Error(f"{path}_transfer_route_invalid")


def _validate_bundle_tree(bundle_dir: Path, manifest: dict[str, Any]) -> Path:
    if bundle_dir.is_symlink() or not bundle_dir.is_dir():
        raise V2Error("bundle_root_missing_or_unsafe")
    expected_root = {"private-generator-manifest.json", "public-candidates"}
    try:
        root_entries = list(bundle_dir.iterdir())
    except OSError:
        raise V2Error("bundle_root_unreadable") from None
    if {item.name for item in root_entries} != expected_root or len(root_entries) != len(expected_root):
        raise V2Error("bundle_file_set_invalid")
    manifest_path = bundle_dir / "private-generator-manifest.json"
    candidate_dir = bundle_dir / "public-candidates"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise V2Error("private_manifest_missing_or_unsafe")
    if candidate_dir.is_symlink() or not candidate_dir.is_dir():
        raise V2Error("candidate_directory_missing_or_unsafe")
    try:
        on_disk_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise V2Error("private_manifest_invalid") from None
    if on_disk_manifest != manifest:
        raise V2Error("private_manifest_mismatch")
    try:
        candidate_entries = list(candidate_dir.iterdir())
    except OSError:
        raise V2Error("candidate_directory_unreadable") from None
    expected_candidates = set(ROUTE_FILENAMES.values())
    if ({item.name for item in candidate_entries} != expected_candidates
            or len(candidate_entries) != len(expected_candidates)):
        raise V2Error("candidate_file_set_invalid")
    if any(item.is_symlink() or not item.is_file() for item in candidate_entries):
        raise V2Error("candidate_file_missing_or_unsafe")
    file_identities = set()
    for path in (manifest_path, *candidate_entries):
        stat = path.stat(follow_symlinks=False)
        identity = (stat.st_dev, stat.st_ino)
        if identity in file_identities:
            raise V2Error("bundle_duplicate_file")
        file_identities.add(identity)
    return candidate_dir


def _expected_classification_counts(reason_counts: dict[str, int]) -> dict[str, int]:
    counts = {classification: 0 for classification in EXCLUSION_CLASSIFICATIONS}
    reason_classification = {
        "explicit_pass_info": "INFO",
        "quality_warning": "WARNING",
        "no_valid_arrival": "UNKNOWN",
        "primary_arrival_missing": "UNKNOWN",
        "unknown": "UNKNOWN",
    }
    for reason, count in reason_counts.items():
        if reason not in reason_classification:
            raise V2Error("exclusion_reason_invalid")
        if not _safe_nonnegative_int(count):
            raise V2Error("exclusion_count_invalid")
        counts[reason_classification[reason]] += count
    return counts


def _build_exclusion_audit(station_date_rows: list[dict[str, Any]]) -> dict[str, Any]:
    reasons, classifications = _empty_exclusion_counts()
    for row in station_date_rows:
        for key in EXCLUSION_REASONS:
            reasons[key] += row["reasonCounts"][key]
        for key in EXCLUSION_CLASSIFICATIONS:
            classifications[key] += row["classificationCounts"][key]
    generated = sum(row["generatedCount"] for row in station_date_rows)
    candidates = sum(row["candidateCount"] for row in station_date_rows)
    excluded = sum(row["excludedCount"] for row in station_date_rows)
    if generated != candidates + excluded or excluded != sum(reasons.values()):
        raise V2Error("exclusion_count_inconsistent")
    if classifications != _expected_classification_counts(reasons):
        raise V2Error("exclusion_classification_inconsistent")
    return {"totalGeneratedCount": generated, "candidateCount": candidates,
            "excludedCount": excluded, "classificationCounts": classifications,
            "reasonCounts": reasons, "byStationDate": station_date_rows}


def _validate_exclusion_audit(audit: Any, expected_station_ids: list[str],
                              expected_dates: list[str], actual_candidates: dict[tuple[str, str], int],
                              expected_generated_count: int) -> dict[str, Any]:
    if not isinstance(audit, dict) or set(audit) != {
            "totalGeneratedCount", "candidateCount", "excludedCount",
            "classificationCounts", "reasonCounts", "byStationDate"}:
        raise V2Error("exclusion_audit_invalid")
    rows = audit["byStationDate"]
    if not isinstance(rows, list):
        raise V2Error("exclusion_station_dates_invalid")
    expected_pairs = {(station, day) for station in expected_station_ids for day in expected_dates}
    observed: set[tuple[str, str]] = set()
    for row in rows:
        required = {"stationId", "serviceDate", "generatedCount", "candidateCount", "excludedCount",
                    "classificationCounts", "reasonCounts"}
        if not isinstance(row, dict) or set(row) != required:
            raise V2Error("exclusion_station_date_invalid")
        pair = (row["stationId"], row["serviceDate"])
        if pair not in expected_pairs or pair in observed:
            raise V2Error("exclusion_station_date_duplicate_or_unexpected")
        observed.add(pair)
        for key in ("generatedCount", "candidateCount", "excludedCount"):
            if not _safe_nonnegative_int(row[key]):
                raise V2Error("exclusion_count_invalid")
        if row["candidateCount"] != actual_candidates.get(pair, 0):
            raise V2Error("exclusion_candidate_count_mismatch")
        if row["generatedCount"] != row["candidateCount"] + row["excludedCount"]:
            raise V2Error("exclusion_count_inconsistent")
        reasons = row["reasonCounts"]
        classifications = row["classificationCounts"]
        if not isinstance(reasons, dict) or set(reasons) != set(EXCLUSION_REASONS):
            raise V2Error("exclusion_reason_counts_invalid")
        if not isinstance(classifications, dict) or set(classifications) != set(EXCLUSION_CLASSIFICATIONS):
            raise V2Error("exclusion_classification_counts_invalid")
        if any(not _safe_nonnegative_int(value) for value in reasons.values()):
            raise V2Error("exclusion_count_invalid")
        if any(not _safe_nonnegative_int(value) for value in classifications.values()):
            raise V2Error("exclusion_count_invalid")
        if sum(reasons.values()) != row["excludedCount"]:
            raise V2Error("exclusion_reason_count_mismatch")
        if classifications != _expected_classification_counts(reasons):
            raise V2Error("exclusion_classification_inconsistent")
    if observed != expected_pairs:
        raise V2Error("exclusion_station_date_set_mismatch")
    expected = _build_exclusion_audit(rows)
    if audit != expected:
        raise V2Error("exclusion_aggregate_mismatch")
    if (audit["totalGeneratedCount"] != expected_generated_count
            or audit["candidateCount"] != sum(actual_candidates.values())):
        raise V2Error("exclusion_generation_candidate_mismatch")
    return audit


def validate_v2_payload(payload: Any) -> dict[str, Any]:
    top = _exact_fields(payload, {"schemaVersion", "dataScope", "generatedAt", "timezone",
                                 "applicationPeriod", "stationId", "originStationId", "serviceDays"},
                        "payload")
    if top["schemaVersion"] != SCHEMA_VERSION or top["dataScope"] != DATA_SCOPE:
        raise V2Error("profile_invalid")
    if top["timezone"] != "Asia/Tokyo" or top["applicationPeriod"] is not None:
        raise V2Error("publication_metadata_invalid")
    if not isinstance(top["generatedAt"], str):
        raise V2Error("generated_at_invalid")
    try:
        parsed = datetime.fromisoformat(top["generatedAt"].replace("Z", "+00:00"))
    except ValueError:
        raise V2Error("generated_at_invalid") from None
    if parsed.tzinfo is None:
        raise V2Error("generated_at_invalid")
    if top["stationId"] not in DESTINATIONS or top["originStationId"] != "Ikebukuro":
        raise V2Error("station_invalid")
    days = top["serviceDays"]
    if not isinstance(days, list) or not days:
        raise V2Error("service_days_invalid")
    seen_dates: set[str] = set()
    for index, day in enumerate(days):
        path = f"service_day_{index}"
        _exact_fields(day, {"serviceDate", "routeCoverage", "departures"}, path)
        service_date = day["serviceDate"]
        if not isinstance(service_date, str):
            raise V2Error("service_date_invalid")
        _strict_date(service_date)
        if service_date in seen_dates:
            raise V2Error("service_date_duplicate")
        seen_dates.add(service_date)
        coverage = day["routeCoverage"]
        if not isinstance(coverage, dict) or set(coverage) != set(ROUTES):
            raise V2Error("route_coverage_invalid")
        departures = day["departures"]
        if not isinstance(departures, list):
            raise V2Error("departures_invalid")
        ids: set[str] = set()
        signatures: set[bytes] = set()
        for row_index, row in enumerate(departures):
            row_path = f"{path}_departure_{row_index}"
            _exact_fields(row, {"id", "routeId", "destination", "displayType",
                                "departureServiceSeconds", "primary", "directAlternative",
                                "bestTransferAlternative"}, row_path)
            if not isinstance(row["id"], str) or not PUBLIC_ID_PATTERN.fullmatch(row["id"]):
                raise V2Error("public_id_invalid")
            if row["id"] in ids:
                raise V2Error("public_id_duplicate")
            ids.add(row["id"])
            if row["routeId"] not in ROUTES:
                raise V2Error("route_id_invalid")
            if not isinstance(row["destination"], str) or not row["destination"].strip():
                raise V2Error("destination_invalid")
            if not isinstance(row["displayType"], str) or not row["displayType"].strip():
                raise V2Error("display_type_invalid")
            departure = row["departureServiceSeconds"]
            if not _safe_nonnegative_int(departure):
                raise V2Error("departure_time_invalid")
            _validate_journey(row["primary"], f"{row_path}_primary")
            _validate_journey(row["directAlternative"], f"{row_path}_direct", "direct")
            _validate_journey(row["bestTransferAlternative"], f"{row_path}_transfer", "transfer")
            primary = row["primary"]
            if primary["departureServiceSeconds"] != departure:
                raise V2Error("primary_departure_mismatch")
            if primary["kind"] == "direct" and row["directAlternative"] != primary:
                raise V2Error("primary_direct_mismatch")
            if primary["kind"] == "transfer" and row["bestTransferAlternative"] != primary:
                raise V2Error("primary_transfer_mismatch")
            for alt in (row["directAlternative"], row["bestTransferAlternative"]):
                if alt is not None and alt["departureServiceSeconds"] != departure:
                    raise V2Error("alternative_departure_mismatch")
                if alt is not None and alt["kind"] == "transfer":
                    if alt["transfer"]["outgoingRouteId"] == row["routeId"]:
                        raise V2Error("transfer_route_same")
            signature = _canonical({key: value for key, value in row.items() if key != "id"})
            if row["id"] != public_id(top["stationId"], service_date, row):
                raise V2Error("public_id_mismatch")
            if signature in signatures:
                raise V2Error("duplicate_public_journey")
            signatures.add(signature)
        for route in ROUTES:
            item = coverage[route]
            _exact_fields(item, {"scheduledTripCount", "dataState"}, f"{path}_coverage_{route}")
            if not _safe_nonnegative_int(item["scheduledTripCount"]):
                raise V2Error("scheduled_trip_count_invalid")
            if item["dataState"] not in {"complete", "insufficient", "unknown"}:
                raise V2Error("data_state_invalid")
            if item["scheduledTripCount"] == 0 and item["dataState"] == "complete":
                raise V2Error("empty_schedule_cannot_be_complete")
    return payload


def validate_bundle(bundle_dir: Path, manifest: dict[str, Any],
                    expected_station_ids: list[str], expected_dates: list[str],
                    expected_fingerprint: str | None = None) -> dict[str, Any]:
    if set(expected_station_ids) != set(DESTINATIONS) or len(expected_station_ids) != len(DESTINATIONS):
        raise V2Error("expected_station_set_invalid")
    dates = [_strict_date(value).isoformat() for value in expected_dates]
    if not dates or len(set(dates)) != len(dates):
        raise V2Error("expected_dates_invalid")
    if manifest.get("dataScope") != MANIFEST_SCOPE:
        raise V2Error("private_manifest_scope_invalid")
    if manifest.get("sourceFingerprint") != expected_fingerprint or not expected_fingerprint:
        raise V2Error("source_fingerprint_mismatch")
    if manifest.get("evaluationServiceDates") != dates:
        raise V2Error("manifest_date_set_mismatch")
    candidate_dir = _validate_bundle_tree(bundle_dir, manifest)
    entries = manifest.get("candidateFiles")
    if not isinstance(entries, dict) or set(entries) != set(DESTINATIONS):
        raise V2Error("candidate_file_set_invalid")
    common_generated: set[str] = set()
    all_states: list[str] = []
    actual_candidates: dict[tuple[str, str], int] = {}
    for station_id in expected_station_ids:
        name = ROUTE_FILENAMES[station_id]
        path = candidate_dir / name
        if path.is_symlink() or not path.is_file():
            raise V2Error("candidate_file_missing_or_unsafe")
        data = path.read_bytes()
        entry = entries.get(station_id)
        if not isinstance(entry, dict) or entry.get("path") != name:
            raise V2Error("manifest_candidate_path_mismatch")
        if entry.get("bytes") != len(data) or entry.get("sha256") != _sha256(data):
            raise V2Error("candidate_hash_or_bytes_mismatch")
        try:
            payload = json.loads(data)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise V2Error("candidate_json_invalid") from None
        validate_v2_payload(payload)
        if payload["stationId"] != station_id:
            raise V2Error("candidate_station_mismatch")
        if [item["serviceDate"] for item in payload["serviceDays"]] != dates:
            raise V2Error("candidate_service_dates_mismatch")
        for day in payload["serviceDays"]:
            actual_candidates[(station_id, day["serviceDate"])] = len(day["departures"])
        common_generated.add(payload["generatedAt"])
        all_states.extend(coverage["dataState"] for day in payload["serviceDays"]
                          for coverage in day["routeCoverage"].values())
    if len(common_generated) != 1:
        raise V2Error("candidate_common_metadata_mismatch")
    if any(state != "complete" for state in all_states):
        raise V2Error("route_coverage_not_complete")
    if manifest.get("applicationPeriod") is not None:
        raise V2Error("public_application_period_must_remain_unapproved")
    quality = manifest.get("quality")
    if not isinstance(quality, dict):
        raise V2Error("private_quality_manifest_invalid")
    expected_generated = quality.get("itineraryResultCount")
    expected_candidates = quality.get("candidateDepartureCount")
    if (not _safe_nonnegative_int(expected_generated)
            or not _safe_nonnegative_int(expected_candidates)
            or expected_candidates != sum(actual_candidates.values())):
        raise V2Error("private_quality_count_mismatch")
    audit = _validate_exclusion_audit(quality.get("exclusionAudit"), expected_station_ids,
                                      dates, actual_candidates, expected_generated)
    return {"stationCount": len(expected_station_ids), "serviceDateCount": len(dates),
            "stationDateCount": len(expected_station_ids) * len(dates),
            "candidateDepartureCount": sum(actual_candidates.values()),
            "excludedCount": audit["excludedCount"],
            "routeStateCount": len(all_states), "dataStateCounts": {
                state: all_states.count(state) for state in ("complete", "insufficient", "unknown")}}


def _safe_output(output: Path, snapshot: Path) -> Path:
    raw = output.expanduser().absolute()
    for component in (raw, *raw.parents):
        if component.exists() and component.is_symlink():
            raise V2Error("output_path_symlink")
    resolved = raw.resolve()
    for root, code in ((ROOT.resolve(), "output_inside_repository"),
                       (snapshot.resolve(), "output_inside_snapshot")):
        try:
            resolved.relative_to(root)
        except ValueError:
            continue
        raise V2Error(code)
    if os.path.lexists(resolved):
        raise V2Error("output_already_exists")
    return resolved


def _manifest_digest_payloads(payloads: dict[str, dict[str, Any]]) -> str:
    stable = {}
    for station_id, payload in sorted(payloads.items()):
        stable_payload = dict(payload)
        stable_payload.pop("generatedAt", None)
        stable[station_id] = stable_payload
    return _sha256(_canonical(stable))


def _validate_odpt0_report(report: dict[str, Any], anchor: date,
                          requested_dates: list[str], source_fp: str) -> None:
    if (report.get("status") != "PASS" or report.get("sourceFingerprint") != source_fp
            or report.get("serviceDate") != anchor.isoformat()
            or report.get("requestedServiceDates") != requested_dates
            or report.get("stationCount") != len(DESTINATIONS)
            or report.get("dayResultCount") != len(DESTINATIONS) * len(requested_dates)):
        raise V2Error("odpt0_quality_gate_failed")
    summary = report.get("summary")
    if not isinstance(summary, dict) or summary.get("unmatchedOdptJourneyCount") != 0:
        raise V2Error("odpt0_quality_gate_failed")
    severity = summary.get("diagnosticSeverity")
    if not isinstance(severity, dict):
        raise V2Error("odpt0_quality_gate_failed")
    warning = severity.get("WARNING", {})
    failure = severity.get("FAIL", {})
    if (not isinstance(warning, dict) or warning.get("codeOccurrences") != 0
            or not isinstance(failure, dict) or failure.get("failGateCount") != 0):
        raise V2Error("odpt0_quality_gate_failed")


def _assert_odpt0_generation_matches(report: dict[str, Any], metrics: dict[str, Any]) -> None:
    day_rows = report.get("dayResults")
    if not isinstance(day_rows, list):
        raise V2Error("odpt0_generation_consistency_mismatch")
    expected_count = sum(day.get("journeyCount", 0) for day in day_rows)
    expected_direct = sum(day.get("primaryDirectCount", 0) for day in day_rows)
    expected_transfer = sum(day.get("primaryTransferCount", 0) for day in day_rows)
    match_counts: collections.Counter[str] = collections.Counter()
    for day in day_rows:
        match_counts.update(day.get("odptMatchStatusCounts", {}))
    if (expected_count != metrics["itineraryResultCount"]
            or expected_direct != metrics["primaryDirectCount"]
            or expected_transfer != metrics["primaryTransferCount"]
            or dict(sorted(match_counts.items()))
            != dict(sorted(metrics["odptMatchStatusCounts"].items()))):
        raise V2Error("odpt0_generation_consistency_mismatch")


def _assert_station_date_generation_matches(report: dict[str, Any],
                                           station_date_rows: list[dict[str, Any]]) -> None:
    day_rows = report.get("dayResults")
    if not isinstance(day_rows, list):
        raise V2Error("odpt0_generation_consistency_mismatch")
    expected: dict[tuple[str, str], int] = {}
    for row in day_rows:
        pair = (row.get("stationId"), row.get("serviceDate"))
        if pair in expected or not _safe_nonnegative_int(row.get("journeyCount")):
            raise V2Error("odpt0_station_date_report_invalid")
        expected[pair] = row["journeyCount"]
    observed = {(row["stationId"], row["serviceDate"]): row["generatedCount"]
                for row in station_date_rows}
    if expected != observed:
        raise V2Error("odpt0_station_date_generation_mismatch")


def run_pipeline(snapshot_dir: Path, service_date: str, output_dir: Path) -> dict[str, Any]:
    anchor = _strict_date(service_date)
    requested_dates = [(anchor + timedelta(days=offset)).isoformat() for offset in (-1, 0, 1)]
    snapshot = snapshot_dir.expanduser().resolve()
    output = _safe_output(output_dir, snapshot)
    source_files, source_fp, source_metadata = _inventory(snapshot)
    qa_report = snapshot_qa.run_qa(snapshot, anchor.isoformat(), output)
    _validate_odpt0_report(qa_report, anchor, requested_dates, source_fp)
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    payloads: dict[str, dict[str, Any]] = {}
    output_stats: dict[str, Any] = {}
    aggregate_metrics: dict[str, Any] = {"itineraryResultCount": 0,
                                         "odptMatchStatusCounts": collections.Counter(),
                                         "primaryDirectCount": 0, "primaryTransferCount": 0,
                                         "exclusionStationDates": []}
    for station_id in DESTINATIONS:
        generator = ItineraryGenerator(gtfs_zip=snapshot / snapshot_qa.GTFS_NAME,
                                       odpt_dir=snapshot, destination_station_id=station_id)
        if any(_strict_date(item) < generator.feed_start or _strict_date(item) > generator.feed_end
               for item in requested_dates):
            raise V2Error("requested_service_date_outside_feed")
        payload, station_metrics = _build_station_payload(generator, station_id, requested_dates, generated_at)
        validate_v2_payload(payload)
        payloads[station_id] = payload
        aggregate_metrics["itineraryResultCount"] += station_metrics["itineraryResultCount"]
        aggregate_metrics["odptMatchStatusCounts"].update(station_metrics["odptMatchStatusCounts"])
        aggregate_metrics["primaryDirectCount"] += station_metrics["primaryDirectCount"]
        aggregate_metrics["primaryTransferCount"] += station_metrics["primaryTransferCount"]
        aggregate_metrics["exclusionStationDates"].extend(station_metrics["exclusionAudit"])

    _assert_odpt0_generation_matches(qa_report, aggregate_metrics)
    _assert_station_date_generation_matches(qa_report, aggregate_metrics["exclusionStationDates"])
    for station_id, payload in payloads.items():
        output_stats[station_id] = sum(len(day["departures"]) for day in payload["serviceDays"])
    candidate_count = sum(output_stats.values())
    exclusion_audit = _build_exclusion_audit(aggregate_metrics["exclusionStationDates"])
    if (exclusion_audit["totalGeneratedCount"] != aggregate_metrics["itineraryResultCount"]
            or exclusion_audit["candidateCount"] != candidate_count
            or exclusion_audit["totalGeneratedCount"] != candidate_count + exclusion_audit["excludedCount"]):
        raise V2Error("exclusion_count_inconsistent")

    final_files, final_fp, _ = _inventory(snapshot)
    if final_fp != source_fp or final_files != source_files:
        raise V2Error("source_changed_during_generation")

    stage_parent = output.parent
    stage_parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if stage_parent.is_symlink():
        raise V2Error("output_parent_symlink")
    stage = Path(tempfile.mkdtemp(prefix=f".{output.name}.stage-", dir=stage_parent))
    os.chmod(stage, 0o700)
    try:
        candidate_dir = stage / "public-candidates"
        candidate_dir.mkdir(mode=0o700)
        candidate_entries: dict[str, Any] = {}
        for station_id, payload in payloads.items():
            name = ROUTE_FILENAMES[station_id]
            content = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                 separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n"
            target = candidate_dir / name
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                         getattr(os, "O_NOFOLLOW", 0), 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(content)
            candidate_entries[station_id] = {"path": name, "sha256": _sha256(content),
                                             "bytes": len(content)}
        generation_digest = _manifest_digest_payloads(payloads)
        route_state_counts = collections.Counter(
            coverage["dataState"]
            for payload in payloads.values()
            for day in payload["serviceDays"]
            for coverage in day["routeCoverage"].values())
        manifest = {
            "schemaVersion": 1, "dataScope": MANIFEST_SCOPE,
            "createdAt": generated_at,
            "sourceFingerprint": source_fp,
            "sourceFiles": source_files,
            "odpt0": {"status": qa_report["status"],
                      "generationDigest": qa_report["generationDigest"],
                      "generatorFingerprint": qa_report["generatorFingerprint"]},
            "generatorFingerprint": _source_generator_fingerprint(),
            "evaluationAnchorServiceDate": anchor.isoformat(),
            "evaluationServiceDates": requested_dates,
            "quality": {"odpt0Status": qa_report["status"],
                        "itineraryResultCount": aggregate_metrics["itineraryResultCount"],
                        "odptMatchStatusCounts": dict(sorted(aggregate_metrics["odptMatchStatusCounts"].items())),
                        "primaryDirectCount": aggregate_metrics["primaryDirectCount"],
                        "primaryTransferCount": aggregate_metrics["primaryTransferCount"],
                        "candidateDepartureCount": sum(output_stats.values()),
                        "exclusionAudit": exclusion_audit,
                        "routeCoverageStateCounts": dict(sorted(route_state_counts.items())),
                        "routeCoveragePolicy": "complete only when scheduled route counts and origin result counts are present and consistent, route data issue counts are zero, ODPT match states are matched/unique_match, and contextual diagnostics contain no WARNING; INFO is non-blocking. Generated rows without a primary journey are omitted as candidates and do not alone imply missing source data.",
                        "journeyGenerationDigest": generation_digest},
            "provenance": {"input": "saved local ODPT JSON and GTFS snapshot",
                           "networkAccess": False, "sourceRecordBodiesIncluded": False,
                           "retrievedAt": None,
                           "retrievedAtNote": "保存済みsnapshotの取得成功日時は確認できない。filesystem mtimeは取得日時として扱わない。",
                           "sourceMetadata": source_metadata,
                           "gtfsValidityIsNotPublicationFreshness": True},
            "applicationPeriod": None,
            "publicationApproved": False,
            "candidateFiles": candidate_entries,
        }
        manifest_path = stage / "private-generator-manifest.json"
        manifest_bytes = json.dumps(manifest, ensure_ascii=False, sort_keys=True,
                                    indent=2, allow_nan=False).encode("utf-8") + b"\n"
        fd = os.open(manifest_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                     getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(manifest_bytes)
        validation = validate_bundle(stage, manifest, list(DESTINATIONS),
                                     requested_dates, source_fp)
        final_files, final_fp, _ = _inventory(snapshot)
        if final_fp != source_fp or final_files != source_files:
            raise V2Error("source_changed_before_commit")
        if os.path.lexists(output):
            raise V2Error("output_appeared_during_generation")
        os.replace(stage, output)
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return {"status": "PASS", "output": str(output), "serviceDate": anchor.isoformat(),
            "serviceDates": requested_dates, "stationCount": len(DESTINATIONS),
            "stationDateCount": validation["stationDateCount"],
            "departureCountsByStation": output_stats,
            "candidateDepartureCount": sum(output_stats.values()),
            "excludedPrimaryCount": exclusion_audit["excludedCount"],
            "exclusionAudit": exclusion_audit,
            "itineraryResultCount": aggregate_metrics["itineraryResultCount"],
            "odptMatchStatusCounts": dict(sorted(aggregate_metrics["odptMatchStatusCounts"].items())),
            "primaryDirectCount": aggregate_metrics["primaryDirectCount"],
            "primaryTransferCount": aggregate_metrics["primaryTransferCount"],
            "sourceFingerprint": source_fp,
            "odpt0GenerationDigest": qa_report["generationDigest"],
            "generationDigest": generation_digest,
            "dataStateCounts": validation["dataStateCounts"],
            "applicationPeriod": None, "publicationApproved": False}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, default=snapshot_qa.DEFAULT_SNAPSHOT)
    parser.add_argument("--service-date", default="2026-10-29", help="YYYY-MM-DD")
    parser.add_argument("--output", type=Path, required=True,
                        help="new, non-existing output directory outside the repository and snapshot")
    args = parser.parse_args(argv)
    try:
        result = run_pipeline(args.snapshot, args.service_date, args.output)
    except (V2Error, snapshot_qa.QAError, OSError, ValueError) as exc:
        code = exc.code if isinstance(exc, V2Error) else str(exc)
        print(f"FAIL: {code}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
