from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import odpt_public_v2 as v2
import odpt_snapshot_qa


def _journey(kind="direct", departure=24 * 3600 + 60, arrival=24 * 3600 + 600,
             transfer=None):
    return {"kind": kind, "departureServiceSeconds": departure,
            "arrivalServiceSeconds": arrival, "transfer": transfer}


def _payload(station_id: str, generated_at="2026-10-29T12:00:00Z", dates=None):
    dates = dates or ["2026-10-28", "2026-10-29", "2026-10-30"]
    days = []
    for service_date in dates:
        row = {"routeId": "6", "destination": "行先",
               "displayType": "各駅停車",
               "departureServiceSeconds": 24 * 3600 + 60,
               "primary": _journey(),
               "directAlternative": _journey(),
               "bestTransferAlternative": None}
        row["id"] = v2.public_id(station_id, service_date, row)
        days.append({"serviceDate": service_date,
                     "routeCoverage": {
                         "6": {"scheduledTripCount": 20, "dataState": "complete"},
                         # A scheduled count is not mechanically equal to rows
                         # emitted for this destination.
                         "9": {"scheduledTripCount": 7, "dataState": "complete"}},
                     "departures": [row]})
    return {"schemaVersion": 2, "dataScope": "public-display-v2",
            "generatedAt": generated_at, "timezone": "Asia/Tokyo",
            "applicationPeriod": None, "stationId": station_id,
            "originStationId": "Ikebukuro", "serviceDays": days}


def _bundle(root: Path, *, dates=None, state="complete"):
    dates = dates or ["2026-10-28", "2026-10-29", "2026-10-30"]
    candidate_dir = root / "public-candidates"
    candidate_dir.mkdir(parents=True)
    entries = {}
    station_date_rows = []
    for station_id, filename in v2.ROUTE_FILENAMES.items():
        payload = _payload(station_id, dates=dates)
        if state != "complete":
            payload["serviceDays"][0]["routeCoverage"]["9"]["dataState"] = state
        data = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":")).encode() + b"\n"
        (candidate_dir / filename).write_bytes(data)
        entries[station_id] = {"path": filename, "bytes": len(data),
                               "sha256": hashlib.sha256(data).hexdigest()}
        station_date_rows.extend({"stationId": station_id, "serviceDate": day,
                                  "generatedCount": 1, "candidateCount": 1, "excludedCount": 0,
                                  "classificationCounts": {key: 0 for key in v2.EXCLUSION_CLASSIFICATIONS},
                                  "reasonCounts": {key: 0 for key in v2.EXCLUSION_REASONS}}
                                 for day in dates)
    audit = v2._build_exclusion_audit(station_date_rows)
    manifest = {"dataScope": v2.MANIFEST_SCOPE,
                "sourceFingerprint": "a" * 64,
                "evaluationServiceDates": dates,
                "applicationPeriod": None,
                "candidateFiles": entries,
                "quality": {"itineraryResultCount": audit["totalGeneratedCount"],
                            "candidateDepartureCount": audit["candidateCount"],
                            "exclusionAudit": audit}}
    (root / "private-generator-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return root, manifest, dates


class FakeGenerator:
    def __init__(self, gtfs_zip, odpt_dir, destination_station_id):
        self.destination_station_id = destination_station_id
        self.feed_start = date(2026, 9, 19)
        self.feed_end = date(2027, 3, 12)
        self.last_destination_status = {}

    def generate(self, service_date):
        routes = {}
        rows = []
        for route_id in v2.ROUTES:
            routes[route_id] = {"scheduledTripCount": 9, "originTripCount": 1,
                                "dataInsufficientCount": 0,
                                "transferDataInsufficientCount": 0}
            itin = SimpleNamespace(kind="direct", departure_seconds=24 * 3600 + 60,
                                   arrival_seconds=24 * 3600 + 600,
                                   transfer_wait_seconds=None, second_leg=None)
            rows.append(SimpleNamespace(
                route_id=route_id, headsign="行先", departure_seconds=itin.departure_seconds,
                primary_itinerary=itin, direct_alternative=itin, best_transfer_alternative=None,
                type_resolution=SimpleNamespace(label="各駅停車"),
                odpt=SimpleNamespace(status="unique_match"),
                data_quality=[], origin_trip_id=f"raw-secret-trip-{route_id}"))
        self.last_destination_status = {"routes": routes}
        return rows


class PublicV2Tests(unittest.TestCase):
    def test_valid_payload_preserves_24_plus_seconds(self):
        payload = _payload("Hikawadai")
        self.assertIs(v2.validate_v2_payload(payload), payload)
        self.assertEqual(payload["serviceDays"][0]["departures"][0]["departureServiceSeconds"], 86460)

    def test_unknown_field_and_internal_id_are_rejected(self):
        payload = _payload("Hikawadai")
        payload["serviceDays"][0]["departures"][0]["originTripId"] = "internal"
        with self.assertRaisesRegex(v2.V2Error, "fields_invalid"):
            v2.validate_v2_payload(payload)

    def test_duplicate_public_id_and_duplicate_journey_are_rejected(self):
        payload = _payload("Hikawadai")
        payload["serviceDays"][0]["departures"].append(
            copy.deepcopy(payload["serviceDays"][0]["departures"][0]))
        with self.assertRaisesRegex(v2.V2Error, "public_id_duplicate"):
            v2.validate_v2_payload(payload)

    def test_validator_recomputes_id_and_rejects_content_or_id_tampering(self):
        payload = _payload("Hikawadai")
        row = payload["serviceDays"][0]["departures"][0]
        original_id = row["id"]
        row["id"] = "p2-" + "0" * 32
        with self.assertRaisesRegex(v2.V2Error, "public_id_mismatch"):
            v2.validate_v2_payload(payload)
        row["id"] = original_id
        row["displayType"] = "急行"
        with self.assertRaisesRegex(v2.V2Error, "public_id_mismatch"):
            v2.validate_v2_payload(payload)

    def test_same_time_route_with_distinct_public_journey_gets_distinct_id(self):
        payload = _payload("Hikawadai")
        day = payload["serviceDays"][0]
        first = day["departures"][0]
        second = copy.deepcopy(first)
        second["bestTransferAlternative"] = {
            "kind": "transfer", "departureServiceSeconds": first["departureServiceSeconds"],
            "arrivalServiceSeconds": first["primary"]["arrivalServiceSeconds"] + 300,
            "transfer": {"stationId": "KotakeMukaihara", "waitSeconds": 120,
                         "outgoingRouteId": "9"}}
        second["id"] = v2.public_id(payload["stationId"], day["serviceDate"], second)
        day["departures"].append(second)
        v2.validate_v2_payload(payload)
        self.assertNotEqual(first["id"], second["id"])

    def test_generator_rejects_public_id_hash_collision(self):
        generator = FakeGenerator(None, None, "Hikawadai")
        original_generate = generator.generate
        def generate_with_second_departure(service_date):
            rows = original_generate(service_date)
            base = rows[0]
            itin = SimpleNamespace(kind="direct", departure_seconds=25 * 3600,
                                   arrival_seconds=25 * 3600 + 500,
                                   transfer_wait_seconds=None, second_leg=None)
            rows.append(SimpleNamespace(**{**base.__dict__,
                                           "departure_seconds": itin.departure_seconds,
                                           "primary_itinerary": itin,
                                           "direct_alternative": itin,
                                           "route_id": "6"}))
            generator.last_destination_status["routes"]["6"]["originTripCount"] += 1
            return rows
        generator.generate = generate_with_second_departure
        with patch.object(v2, "_sha256", return_value="f" * 64):
            with self.assertRaisesRegex(v2.V2Error, "public_id_collision"):
                v2._build_station_payload(generator, "Hikawadai", ["2026-10-29"],
                                          "2026-10-29T12:00:00Z")

    def test_transfer_time_route_and_alternative_consistency(self):
        payload = _payload("Wakoshi")
        row = payload["serviceDays"][0]["departures"][0]
        transfer = {"kind": "transfer", "departureServiceSeconds": 86460,
                    "arrivalServiceSeconds": 87000,
                    "transfer": {"stationId": "KotakeMukaihara", "waitSeconds": 30,
                                 "outgoingRouteId": "9"}}
        row["primary"] = transfer
        row["bestTransferAlternative"] = transfer
        with self.assertRaisesRegex(v2.V2Error, "transfer_wait_invalid"):
            v2.validate_v2_payload(payload)
        transfer["transfer"]["waitSeconds"] = 120
        transfer["transfer"]["outgoingRouteId"] = "6"
        with self.assertRaisesRegex(v2.V2Error, "transfer_route_same"):
            v2.validate_v2_payload(payload)

    def test_route_coverage_enum_and_empty_schedule_cannot_be_complete(self):
        payload = _payload("Heiwadai")
        payload["serviceDays"][0]["routeCoverage"]["6"]["dataState"] = "bad"
        with self.assertRaisesRegex(v2.V2Error, "data_state_invalid"):
            v2.validate_v2_payload(payload)
        payload = _payload("Heiwadai")
        payload["serviceDays"][0]["routeCoverage"]["6"]["scheduledTripCount"] = 0
        with self.assertRaisesRegex(v2.V2Error, "empty_schedule_cannot_be_complete"):
            v2.validate_v2_payload(payload)

    def test_incomplete_application_period_is_not_publishable(self):
        payload = _payload("Senkawa")
        payload["applicationPeriod"] = {"startsAt": "2026-10-28T00:00:00+09:00",
                                        "endsAt": "2026-10-31T00:00:00+09:00"}
        with self.assertRaisesRegex(v2.V2Error, "publication_metadata_invalid"):
            v2.validate_v2_payload(payload)

    def test_bundle_completeness_hash_and_fingerprint(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle_dir, manifest, dates = _bundle(Path(directory))
            result = v2.validate_bundle(bundle_dir, manifest, list(v2.DESTINATIONS), dates,
                                        "a" * 64)
            self.assertEqual(result["stationDateCount"], 24)
            self.assertEqual(result["routeStateCount"], 48)
            with self.assertRaisesRegex(v2.V2Error, "source_fingerprint_mismatch"):
                v2.validate_bundle(bundle_dir, manifest, list(v2.DESTINATIONS), dates, "b" * 64)
            manifest["candidateFiles"]["Hikawadai"]["bytes"] += 1
            (bundle_dir / "private-generator-manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, sort_keys=True), encoding="utf-8")
            with self.assertRaisesRegex(v2.V2Error, "candidate_hash_or_bytes_mismatch"):
                v2.validate_bundle(bundle_dir, manifest, list(v2.DESTINATIONS), dates, "a" * 64)

    def test_bundle_rejects_missing_dates_and_incomplete_coverage(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle_dir, manifest, dates = _bundle(Path(directory), dates=["2026-10-28"])
            with self.assertRaisesRegex(v2.V2Error, "manifest_date_set_mismatch"):
                v2.validate_bundle(bundle_dir, manifest, list(v2.DESTINATIONS),
                                    ["2026-10-28", "2026-10-29"], "a" * 64)
        with tempfile.TemporaryDirectory() as directory:
            bundle_dir, manifest, dates = _bundle(Path(directory), state="unknown")
            with self.assertRaisesRegex(v2.V2Error, "route_coverage_not_complete"):
                v2.validate_bundle(bundle_dir, manifest, list(v2.DESTINATIONS), dates, "a" * 64)

    def test_bundle_rejects_duplicate_dates_missing_station_and_extra_station_set(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle_dir, manifest, dates = _bundle(Path(directory))
            with self.assertRaisesRegex(v2.V2Error, "expected_dates_invalid"):
                v2.validate_bundle(bundle_dir, manifest, list(v2.DESTINATIONS),
                                    [dates[0], dates[0]], "a" * 64)
            with self.assertRaisesRegex(v2.V2Error, "expected_station_set_invalid"):
                v2.validate_bundle(bundle_dir, manifest, list(v2.DESTINATIONS)[:-1],
                                    dates, "a" * 64)
            (bundle_dir / "public-candidates" / v2.ROUTE_FILENAMES["Hikawadai"]).unlink()
            with self.assertRaisesRegex(v2.V2Error, "candidate_file_set_invalid"):
                v2.validate_bundle(bundle_dir, manifest, list(v2.DESTINATIONS),
                                    dates, "a" * 64)

    def test_bundle_rejects_extra_file_and_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle_dir, manifest, dates = _bundle(Path(directory))
            (bundle_dir / "public-candidates" / "temporary.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(v2.V2Error, "candidate_file_set_invalid"):
                v2.validate_bundle(bundle_dir, manifest, list(v2.DESTINATIONS), dates, "a" * 64)
        with tempfile.TemporaryDirectory() as directory:
            bundle_dir, manifest, dates = _bundle(Path(directory))
            extra = bundle_dir / "extra.tmp"
            extra.write_text("x", encoding="utf-8")
            with self.assertRaisesRegex(v2.V2Error, "bundle_file_set_invalid"):
                v2.validate_bundle(bundle_dir, manifest, list(v2.DESTINATIONS), dates, "a" * 64)
        with tempfile.TemporaryDirectory() as directory:
            bundle_dir, manifest, dates = _bundle(Path(directory))
            target = bundle_dir / "public-candidates" / v2.ROUTE_FILENAMES["Hikawadai"]
            target.unlink()
            target.symlink_to(Path(__file__))
            with self.assertRaisesRegex(v2.V2Error, "candidate_file_missing_or_unsafe"):
                v2.validate_bundle(bundle_dir, manifest, list(v2.DESTINATIONS), dates, "a" * 64)
        with tempfile.TemporaryDirectory() as directory:
            bundle_dir, manifest, dates = _bundle(Path(directory))
            candidate_dir = bundle_dir / "public-candidates"
            source = candidate_dir / v2.ROUTE_FILENAMES["Hikawadai"]
            target = candidate_dir / v2.ROUTE_FILENAMES["Senkawa"]
            target.unlink()
            os.link(source, target)
            with self.assertRaisesRegex(v2.V2Error, "bundle_duplicate_file"):
                v2.validate_bundle(bundle_dir, manifest, list(v2.DESTINATIONS), dates, "a" * 64)

    def test_exclusion_audit_preserves_no_valid_arrival_as_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle_dir, manifest, dates = _bundle(Path(directory))
            rows = copy.deepcopy(manifest["quality"]["exclusionAudit"]["byStationDate"])
            first = rows[0]
            first["generatedCount"] = 2
            first["excludedCount"] = 1
            first["reasonCounts"]["no_valid_arrival"] = 1
            first["classificationCounts"]["UNKNOWN"] = 1
            audit = v2._build_exclusion_audit(rows)
            manifest["quality"]["itineraryResultCount"] = 25
            manifest["quality"]["exclusionAudit"] = audit
            (bundle_dir / "private-generator-manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, sort_keys=True), encoding="utf-8")
            result = v2.validate_bundle(bundle_dir, manifest, list(v2.DESTINATIONS), dates, "a" * 64)
            self.assertEqual(result["excludedCount"], 1)
            self.assertEqual(audit["reasonCounts"]["no_valid_arrival"], 1)
            self.assertEqual(audit["classificationCounts"]["UNKNOWN"], 1)

    def test_exclusion_audit_count_or_reason_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle_dir, manifest, dates = _bundle(Path(directory))
            audit = manifest["quality"]["exclusionAudit"]
            audit["byStationDate"][0]["reasonCounts"]["no_valid_arrival"] = 1
            (bundle_dir / "private-generator-manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, sort_keys=True), encoding="utf-8")
            with self.assertRaisesRegex(v2.V2Error, "exclusion_reason_count_mismatch"):
                v2.validate_bundle(bundle_dir, manifest, list(v2.DESTINATIONS), dates, "a" * 64)

    def test_exclusion_total_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle_dir, manifest, dates = _bundle(Path(directory))
            manifest["quality"]["exclusionAudit"]["excludedCount"] = 1
            (bundle_dir / "private-generator-manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, sort_keys=True), encoding="utf-8")
            with self.assertRaisesRegex(v2.V2Error, "exclusion_aggregate_mismatch"):
                v2.validate_bundle(bundle_dir, manifest, list(v2.DESTINATIONS), dates, "a" * 64)

    def test_no_diagnostic_no_valid_arrival_is_unknown_not_normal_or_warning(self):
        result = SimpleNamespace(data_quality=[], status="no_valid_arrival",
                                 primary_itinerary=None, best_transfer_alternative=None)
        self.assertEqual(v2._exclusion_detail(result), ("no_valid_arrival", "UNKNOWN"))
        unclassified = SimpleNamespace(data_quality=[], status="unexpected_status",
                                       primary_itinerary=None, best_transfer_alternative=None)
        self.assertEqual(v2._exclusion_detail(unclassified), ("unknown", "UNKNOWN"))
        passed = SimpleNamespace(data_quality=["destination_explicit_pass"],
                                 status="no_valid_arrival", primary_itinerary=None,
                                 best_transfer_alternative=None)
        self.assertEqual(v2._exclusion_detail(passed), ("explicit_pass_info", "INFO"))

    def test_digest_excludes_generated_at_but_not_payload_content(self):
        first = {"Hikawadai": _payload("Hikawadai", "2026-10-29T12:00:00Z")}
        second = {"Hikawadai": _payload("Hikawadai", "2026-10-30T12:00:00Z")}
        self.assertEqual(v2._manifest_digest_payloads(first), v2._manifest_digest_payloads(second))
        second["Hikawadai"]["serviceDays"][0]["departures"][0]["displayType"] = "急行"
        self.assertNotEqual(v2._manifest_digest_payloads(first), v2._manifest_digest_payloads(second))

    def test_pipeline_atomic_output_reproducibility_and_source_id_removal(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as directory:
            root = Path(directory)
            snapshot = root / "snapshot"
            snapshot.mkdir()
            fingerprint = "a" * 64
            inventory = ([{"path": "snapshot.json", "sizeBytes": 1, "sha256": "b" * 64}],
                         fingerprint, {"gtfs": {"feedVersion": "fixture"}, "json": {}})
            def qa_report(*args, **kwargs):
                dates = ["2026-10-28", "2026-10-29", "2026-10-30"]
                days = [{"stationId": station, "serviceDate": day, "journeyCount": 2,
                         "primaryDirectCount": 2, "primaryTransferCount": 0,
                         "odptMatchStatusCounts": {"unique_match": 2}}
                        for station in v2.DESTINATIONS for day in dates]
                return {"status": "PASS", "sourceFingerprint": fingerprint,
                        "serviceDate": "2026-10-29",
                        "requestedServiceDates": ["2026-10-28", "2026-10-29", "2026-10-30"],
                        "stationCount": 8, "dayResultCount": 24, "dayResults": days,
                        "summary": {"unmatchedOdptJourneyCount": 0,
                                    "diagnosticSeverity": {"WARNING": {"codeOccurrences": 0},
                                                           "FAIL": {"failGateCount": 0}}},
                        "generationDigest": "c" * 64, "generatorFingerprint": "d" * 64}
            with patch.object(v2, "_inventory", return_value=inventory), \
                    patch.object(v2.snapshot_qa, "run_qa", side_effect=qa_report), \
                    patch.object(v2, "ItineraryGenerator", FakeGenerator):
                first = v2.run_pipeline(snapshot, "2026-10-29", root / "out-a")
                second = v2.run_pipeline(snapshot, "2026-10-29", root / "out-b")
                self.assertEqual(first["generationDigest"], second["generationDigest"])
                payload_file = root / "out-a" / "public-candidates" / v2.ROUTE_FILENAMES["Hikawadai"]
                text = payload_file.read_text(encoding="utf-8")
                self.assertNotIn("raw-secret-trip", text)
                self.assertNotIn("originTripId", text)
                self.assertEqual((root / "out-a" / "private-generator-manifest.json").stat().st_mode & 0o777,
                                 0o600)

    def test_pipeline_discards_partial_stage_on_validator_failure(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as directory:
            root = Path(directory)
            snapshot = root / "snapshot"
            snapshot.mkdir()
            fingerprint = "a" * 64
            inventory = ([{"path": "snapshot.json", "sizeBytes": 1, "sha256": "b" * 64}],
                         fingerprint, {"gtfs": {"feedVersion": "fixture"}, "json": {}})
            def qa_report(*args, **kwargs):
                dates = ["2026-10-28", "2026-10-29", "2026-10-30"]
                days = [{"stationId": station, "serviceDate": day, "journeyCount": 2,
                         "primaryDirectCount": 2, "primaryTransferCount": 0,
                         "odptMatchStatusCounts": {"unique_match": 2}}
                        for station in v2.DESTINATIONS for day in dates]
                return {"status": "PASS", "sourceFingerprint": fingerprint,
                        "serviceDate": "2026-10-29",
                        "requestedServiceDates": ["2026-10-28", "2026-10-29", "2026-10-30"],
                        "stationCount": 8, "dayResultCount": 24, "dayResults": days,
                        "summary": {"unmatchedOdptJourneyCount": 0,
                                    "diagnosticSeverity": {"WARNING": {"codeOccurrences": 0},
                                                           "FAIL": {"failGateCount": 0}}},
                        "generationDigest": "c" * 64, "generatorFingerprint": "d" * 64}
            output = root / "out"
            with patch.object(v2, "_inventory", return_value=inventory), \
                    patch.object(v2.snapshot_qa, "run_qa", side_effect=qa_report), \
                    patch.object(v2, "ItineraryGenerator", FakeGenerator), \
                    patch.object(v2, "validate_bundle", side_effect=v2.V2Error("injected_failure")):
                with self.assertRaisesRegex(v2.V2Error, "injected_failure"):
                    v2.run_pipeline(snapshot, "2026-10-29", output)
            self.assertFalse(output.exists())
            self.assertEqual(list(root.glob(".out.stage-*")), [])

    def test_output_symlink_and_repository_paths_are_rejected(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as directory:
            root = Path(directory)
            snapshot = root / "snapshot"
            snapshot.mkdir()
            target = root / "real"
            target.mkdir()
            link = root / "link"
            link.symlink_to(target, target_is_directory=True)
            with self.assertRaisesRegex(v2.V2Error, "output_path_symlink"):
                v2._safe_output(link / "candidate", snapshot)
            with self.assertRaisesRegex(v2.V2Error, "output_inside_repository"):
                v2._safe_output(v2.ROOT / "private-candidate", snapshot)


if __name__ == "__main__":
    unittest.main()
