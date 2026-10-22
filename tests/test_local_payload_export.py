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
        self.assertNotIn("stop_times", serialized)
        self.assertNotIn("odpt:trainTimetableObject", serialized)
        self.assertNotIn("apikey", serialized.lower())
        departure = payload["serviceDays"][0]["departures"][0]
        self.assertIn("primary", departure)
        self.assertIn("directAlternative", departure)
        self.assertIn("bestTransferAlternative", departure)

    def test_outside_feed_service_dates_are_listed_and_skipped(self):
        generator = ItineraryGenerator(DEFAULT_GTFS, DEFAULT_DATA_DIR)
        payload = build_payload(generator, ["2026-09-18", "2026-10-22"])
        self.assertEqual(payload["excludedServiceDates"], ["2026-09-18"])
        self.assertEqual([row["serviceDate"] for row in payload["serviceDays"]], ["2026-10-22"])


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
