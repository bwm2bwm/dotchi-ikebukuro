from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from export_local_timetable_payload import build_payload  # noqa: E402
from odpt_itinerary import DEFAULT_DATA_DIR, DEFAULT_GTFS, ItineraryGenerator  # noqa: E402


@unittest.skipUnless(DEFAULT_GTFS.exists(), "local Tokyo Metro GTFS ZIP is not present")
class LocalPayloadExportTests(unittest.TestCase):
    def test_payload_contains_minimal_display_data_and_internal_metadata(self):
        generator = ItineraryGenerator(DEFAULT_GTFS, DEFAULT_DATA_DIR)
        payload = build_payload(generator, ["2026-10-22"])
        serialized = json.dumps(payload, ensure_ascii=False)
        self.assertEqual(payload["schemaVersion"], 1)
        self.assertEqual(payload["dataScope"], "local-preview-only")
        self.assertEqual(payload["feed"]["version"], "20261008")
        self.assertEqual(payload["timezone"], "Asia/Tokyo")
        self.assertEqual(payload["applicationPeriod"]["startsAt"], "2026-09-19T00:00:00+09:00")
        self.assertEqual(payload["applicationPeriod"]["endsAt"], "2027-03-13T00:00:00+09:00")
        self.assertEqual(payload["serviceDays"][0]["originStationId"], "Ikebukuro")
        self.assertEqual(payload["serviceDays"][0]["destinationStationId"], "Hikawadai")
        self.assertIsNone(payload["feed"]["sourceUpdatedAt"])
        self.assertIsNone(payload["odpt"]["sourceUpdatedAt"])
        self.assertIsNone(payload["webApp"]["builtAt"])
        self.assertNotIn("stop_times", serialized)
        self.assertNotIn("odpt:trainTimetableObject", serialized)
        self.assertNotIn("apikey", serialized.lower())
        departure = payload["serviceDays"][0]["departures"][0]
        self.assertIn("primary", departure)
        self.assertIn("directAlternative", departure)
        self.assertIn("bestTransferAlternative", departure)
        self.assertEqual(departure["primary"]["arrivalStationId"], "Hikawadai")
        self.assertIn("reportedTrainType", departure)
        self.assertIn("serviceBrand", departure)
        self.assertIn(departure["typeSource"],
                      {"odpt_confirmed", "official_route_rule", "gtfs_stop_pattern", "unknown"})
        self.assertIn("stopPatternStates", departure)
        self.assertIn(departure["typeValidation"],
                      {"consistent", "unverifiable", "conflict", "not_applicable", "unmatched"})
        self.assertEqual(departure["serviceBrand"], None)
        f_liner = next(item for item in payload["serviceDays"][0]["departures"]
                       if item["reportedTrainType"] == "F-Liner")
        self.assertEqual(f_liner["serviceBrand"], "F-Liner")
        self.assertIsNone(f_liner["trainType"])
        self.assertEqual(f_liner["typeSource"], "odpt_confirmed")
        self.assertEqual(f_liner["typeLabel"], "Fライナー")

    def test_yurakucho_scope_labels_only_eligible_unknown_types(self):
        generator = ItineraryGenerator(DEFAULT_GTFS, DEFAULT_DATA_DIR)
        for service_date, expected_count in (("2026-10-22", 9), ("2026-10-24", 6), ("2026-11-03", 6)):
            payload = build_payload(generator, [service_date])
            rows = [item for item in payload["serviceDays"][0]["departures"]
                    if item["typeSource"] == "official_route_rule"]
            self.assertEqual(len(rows), expected_count)
            self.assertTrue(all(item["routeId"] == "6"
                                and item["odptMatchStatus"] == "unique_match"
                                and item["trainType"] == "Local"
                                and item["typeLabel"] == "各駅停車"
                                and item["reportedTrainType"] in {"SemiExpress", "Rapid", "RapidExpress"}
                                and item["unscopedTrainType"] == item["reportedTrainType"]
                                and item["typeDiagnostic"] == "yurakucho_all_stops_official_route_rule"
                                for item in rows))
            non_displayable = [item for item in payload["serviceDays"][0]["departures"]
                               if item["status"] == "no_valid_arrival"]
            self.assertTrue(all(item["typeSource"] != "official_route_rule"
                                for item in non_displayable))
            self.assertTrue(all(item["typeLabel"] == "種別不明"
                                and item["typeDiagnostic"] ==
                                "official_route_rule_requires_valid_hikawadai_itinerary"
                                for item in non_displayable
                                if item["typeDiagnostic"] ==
                                "official_route_rule_requires_valid_hikawadai_itinerary"))

    def test_outside_feed_service_dates_are_listed_and_skipped(self):
        generator = ItineraryGenerator(DEFAULT_GTFS, DEFAULT_DATA_DIR)
        payload = build_payload(generator, ["2026-09-18", "2026-10-22"])
        self.assertEqual(payload["excludedServiceDates"], ["2026-09-18"])
        self.assertEqual([row["serviceDate"] for row in payload["serviceDays"]], ["2026-10-22"])

    def test_phase2_payload_keeps_selected_destination_separate_and_adds_daily_status(self):
        generator = ItineraryGenerator(DEFAULT_GTFS, DEFAULT_DATA_DIR,
                                       destination_station_id="KotakeMukaihara")
        payload = build_payload(generator, ["2026-10-22"])
        day = payload["serviceDays"][0]
        self.assertEqual(day["destinationStationId"], "KotakeMukaihara")
        self.assertEqual(day["destinationStatus"]["status"], "normal")
        self.assertEqual(day["destinationStatus"]["candidateCount"], 439)
        self.assertEqual(day["destinationStatus"]["routes"]["6"]["candidateCount"], 219)
        self.assertEqual(day["destinationStatus"]["routes"]["9"]["candidateCount"], 220)
        for item in day["departures"]:
            if item["primary"] is not None:
                self.assertEqual(item["primary"]["kind"], "direct")
                self.assertEqual(item["primary"]["transfer"], None)
                self.assertEqual(item["primary"]["arrivalStationId"], "KotakeMukaihara")
                self.assertEqual(item["destination"], item["headsign"])


class ExportPathGuardTests(unittest.TestCase):
    def test_repository_output_path_is_rejected_before_generation(self):
        root = Path(__file__).resolve().parents[1]
        output = root / "should-not-write-real-timetable.json"
        process = subprocess.run(
            [sys.executable, "-B", str(root / "scripts" / "export_local_timetable_payload.py"),
             "--service-date", "2026-10-22", "--output", str(output)],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(process.returncode, 2)
        self.assertIn("リポジトリ外", process.stderr)
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
