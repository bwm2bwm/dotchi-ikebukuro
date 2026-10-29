from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
import zipfile
from types import SimpleNamespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import odpt_snapshot_qa as qa


def make_snapshot(root: Path, *, start="20261028", end="20261030", bad_zip=False, active=True) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for name in qa.REQUIRED_JSON:
        (root / name).write_text("[]\n", encoding="utf-8")
    path = root / qa.GTFS_NAME
    if bad_zip:
        path.write_bytes(b"not a zip")
        return root
    destinations = list(__import__("odpt_itinerary").DESTINATIONS.values())
    stops = [{"stop_id": "228", "stop_name": "池袋"}]
    for dest in destinations:
        for stop_id in dest["routeStopIds"].values():
            stops.append({"stop_id": stop_id, "stop_name": dest["name"]})
    rows = {
        "feed_info.txt": [{"feed_version": "test-v1", "feed_start_date": start, "feed_end_date": end}],
        "calendar.txt": [{"service_id": "0", "monday": "1" if active else "0", "tuesday": "1" if active else "0", "wednesday": "1" if active else "0",
                           "thursday": "1" if active else "0", "friday": "1" if active else "0", "saturday": "1" if active else "0", "sunday": "1" if active else "0",
                           "start_date": start, "end_date": end}],
        "calendar_dates.txt": [],
        "stops.txt": stops,
        "routes.txt": [{"route_id": "6", "route_long_name": "有楽町線"},
                       {"route_id": "9", "route_long_name": "副都心線"}],
        "trips.txt": [], "stop_times.txt": [],
    }
    for route_id in ("6", "9"):
        for index, dest in enumerate(destinations):
            trip_id = f"trip-{route_id}-{index}"
            rows["trips.txt"].append({"route_id": route_id, "service_id": "0", "trip_id": trip_id,
                                      "trip_headsign": dest["name"]})
            target = dest["routeStopIds"][route_id]
            first = 23 * 3600 + index * 60
            last = first + 60
            if dest["stationKey"] == "heiwadai":
                first, last = 25 * 3600 + 5 * 60, 25 * 3600 + 7 * 60
            rows["stop_times.txt"].extend([
                {"trip_id": trip_id, "arrival_time": "", "departure_time": f"{first // 3600:02}:{first % 3600 // 60:02}:00",
                 "stop_id": "228", "stop_sequence": "1", "pickup_type": "0", "drop_off_type": "1"},
                {"trip_id": trip_id, "arrival_time": f"{last // 3600:02}:{last % 3600 // 60:02}:00", "departure_time": "",
                 "stop_id": target, "stop_sequence": "2", "pickup_type": "1", "drop_off_type": "0"},
            ])
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for filename, records in rows.items():
            fields = list(records[0]) if records else {
                "calendar_dates.txt": ["service_id", "date", "exception_type"],
            }.get(filename, ["unused"])
            from io import StringIO
            output = StringIO()
            writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            writer.writerows(records)
            archive.writestr(filename, output.getvalue())
    return root


class SnapshotQATests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "snapshot"
        self.out = Path(self.temp.name) / "private-report"
        make_snapshot(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_normal_snapshot_and_eight_stations_three_dates(self):
        report = qa.run_qa(self.root, "2026-10-29", self.out)
        self.assertEqual(report["source"]["gtfs"]["feedVersion"], "test-v1")
        self.assertEqual(report["stationCount"], 8)
        self.assertEqual(report["dayResultCount"], 24)
        self.assertEqual(report["requestedServiceDates"], ["2026-10-28", "2026-10-29", "2026-10-30"])
        self.assertEqual(report["status"], "WARNING")
        self.assertTrue(all("sourceDates" in item for item in report["source"]["json"].values()))
        self.assertEqual(report["source"]["json"]["TrainTimetable_Yurakucho.json"]["sourceIssuedDates"], [])

    def test_missing_required_file(self):
        (self.root / qa.REQUIRED_JSON[0]).unlink()
        with self.assertRaisesRegex(qa.QAError, "required_file_missing"):
            qa.run_qa(self.root, "2026-10-29", self.out)

    def test_invalid_json(self):
        (self.root / qa.REQUIRED_JSON[0]).write_text("{bad", encoding="utf-8")
        with self.assertRaisesRegex(qa.QAError, "json_invalid"):
            qa.run_qa(self.root, "2026-10-29", self.out)

    def test_invalid_gtfs_zip(self):
        make_snapshot(self.root, bad_zip=True)
        with self.assertRaisesRegex(qa.QAError, "gtfs_zip_invalid"):
            qa.run_qa(self.root, "2026-10-29", self.out)

    def test_outside_feed_range_is_fail(self):
        make_snapshot(self.root, start="20261029", end="20261030")
        report = qa.run_qa(self.root, "2026-10-29", self.out)
        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(report["summary"]["outsideFeedRangeOrMissingDates"], 8)

    def test_missing_requested_service_date_is_visible(self):
        make_snapshot(self.root, active=False)
        report = qa.run_qa(self.root, "2026-10-29", self.out)
        self.assertEqual(report["summary"]["noCandidateOrNoActiveServiceStationDates"], 24)
        self.assertEqual(report["status"], "WARNING")
        self.assertEqual(report["dayResults"][0]["activeServiceCount"], 0)

    def test_source_modification_during_run_fails(self):
        target = self.root / qa.REQUIRED_JSON[0]
        def mutate():
            target.write_text("[{\"changed\":true}]\n", encoding="utf-8")
        with self.assertRaisesRegex(qa.QAError, "source_changed_during_run"):
            qa.run_qa(self.root, "2026-10-29", self.out, mutation_hook=mutate)

    def test_same_snapshot_is_reproducible_and_has_no_rows_in_report(self):
        first = qa.run_qa(self.root, "2026-10-29", self.out)
        second = qa.run_qa(self.root, "2026-10-29", self.out)
        self.assertEqual(first["sourceFingerprint"], second["sourceFingerprint"])
        self.assertEqual(first["generationDigest"], second["generationDigest"])
        self.assertNotIn("trip_id", json.dumps(first))
        self.assertNotIn("origin_trip_id", json.dumps(first))

    def test_source_files_are_not_modified(self):
        before = {p.name: p.read_bytes() for p in self.root.iterdir()}
        qa.run_qa(self.root, "2026-10-29", self.out)
        after = {p.name: p.read_bytes() for p in self.root.iterdir()}
        self.assertEqual(before, after)

    def test_machine_and_human_reports_are_private_and_aggregate_only(self):
        report = qa.run_qa(self.root, "2026-10-29", self.out)
        json_path, text_path = qa._write_report(report, self.out)
        self.assertEqual(json_path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(text_path.stat().st_mode & 0o777, 0o600)
        content = json_path.read_text(encoding="utf-8")
        self.assertNotIn("trip_id", content)
        self.assertNotIn("origin_trip_id", content)
        self.assertIn("判定:", text_path.read_text(encoding="utf-8"))

    def test_report_symlink_cannot_overwrite_snapshot_source(self):
        report = qa.run_qa(self.root, "2026-10-29", self.out)
        self.out.mkdir(parents=True, exist_ok=True)
        target = self.root / qa.REQUIRED_JSON[0]
        before = target.read_bytes()
        (self.out / "odpt-snapshot-qa.json").symlink_to(target)
        with self.assertRaisesRegex(qa.QAError, "report_target_not_regular_file"):
            qa._write_report(report, self.out)
        self.assertEqual(target.read_bytes(), before)

    def test_comparison_detects_divergent_digest_under_same_conditions(self):
        report = qa.run_qa(self.root, "2026-10-29", self.out)
        previous = self.out / "previous.json"
        previous.parent.mkdir(parents=True, exist_ok=True)
        previous.write_text(json.dumps(report), encoding="utf-8")
        self.assertEqual(qa._compare_previous(report, previous)["status"], "MATCH")
        altered = dict(report)
        altered["generationDigest"] = "0" * 64
        self.assertEqual(qa._compare_previous(altered, previous)["status"], "MISMATCH")
        altered["serviceDate"] = "2026-10-30"
        self.assertEqual(qa._compare_previous(altered, previous)["status"], "INCOMPARABLE")

    def test_confirmed_pass_through_with_valid_transfer_is_info_once_per_itinerary(self):
        transfer = SimpleNamespace(kind="transfer", departure_seconds=100, arrival_seconds=300)
        result = SimpleNamespace(
            origin_trip_id="synthetic-route9-pass",
            best_transfer_alternative=transfer,
            data_quality=["destination_explicit_pass", "destination_alighting_prohibited",
                          "destination_arrival_missing", "direct_arrival_unavailable"],
        )
        summary = qa._diagnostic_summary([result])
        self.assertEqual(summary["INFO"]["codeOccurrences"], 4)
        self.assertEqual(summary["INFO"]["affectedItineraryInstances"], 1)
        self.assertEqual(summary["WARNING"]["codeOccurrences"], 0)
        self.assertEqual(summary["INFO"]["codes"]["destination_arrival_missing"]["affectedItineraryInstances"], 1)

    def test_unconfirmed_missing_arrival_and_failed_transfer_remain_warning(self):
        no_transfer = SimpleNamespace(kind="transfer", departure_seconds=None, arrival_seconds=None)
        missing_only = SimpleNamespace(
            origin_trip_id="synthetic-missing-arrival", best_transfer_alternative=None,
            data_quality=["destination_arrival_missing", "direct_arrival_unavailable"],
        )
        pass_without_transfer = SimpleNamespace(
            origin_trip_id="synthetic-pass-no-transfer", best_transfer_alternative=no_transfer,
            data_quality=["destination_explicit_pass", "destination_alighting_prohibited",
                          "destination_arrival_missing", "direct_arrival_unavailable"],
        )
        invalid_time = SimpleNamespace(
            origin_trip_id="synthetic-invalid-time", best_transfer_alternative=None,
            data_quality=["destination_time_order_conflict"],
        )
        summary = qa._diagnostic_summary([missing_only, pass_without_transfer, invalid_time])
        self.assertEqual(summary["INFO"]["codeOccurrences"], 3)
        self.assertEqual(summary["INFO"]["affectedItineraryInstances"], 1)
        self.assertEqual(summary["WARNING"]["codeOccurrences"], 4)
        self.assertEqual(summary["WARNING"]["affectedItineraryInstances"], 3)
        self.assertEqual(summary["WARNING"]["codes"]["destination_arrival_missing"]["occurrences"], 1)
        self.assertEqual(summary["INFO"]["codes"]["destination_arrival_missing"]["occurrences"], 1)

    def test_twenty_four_plus_hour_schedule_is_preserved_by_generator(self):
        from odpt_itinerary import parse_gtfs_time
        self.assertEqual(parse_gtfs_time("25:05:00"), 25 * 3600 + 5 * 60)


if __name__ == "__main__":
    unittest.main()
