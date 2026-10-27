from __future__ import annotations

from datetime import datetime
from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import synthetic_public_fixture_factory as factory  # noqa: E402
import generate_synthetic_public_fixtures as fixture_cli  # noqa: E402


class SyntheticPublicFixtureTests(unittest.TestCase):
    def test_jst_date_selection_handles_utc_midnight_boundary(self):
        before = datetime.fromisoformat("2026-10-26T14:59:00+00:00")
        after = datetime.fromisoformat("2026-10-26T15:00:00+00:00")
        self.assertEqual(factory.jst_today(before).isoformat(), "2026-10-26")
        self.assertEqual(factory.jst_today(after).isoformat(), "2026-10-27")
        with self.assertRaisesRegex(factory.SyntheticFixtureError, "timezone"):
            factory.jst_today(datetime(2026, 10, 26, 15, 0))

    def test_date_parser_rejects_invalid_and_noncanonical_dates(self):
        for value in ("2026-02-30", "2026-1-02", "not-a-date"):
            with self.subTest(value=value), self.assertRaises(factory.SyntheticFixtureError):
                factory.parse_service_date(value)

    def test_payload_has_three_dates_and_basic_synthetic_display_cases(self):
        payload = factory.make_public_fixture("Hikawadai", ["2026-10-26", "2026-10-27", "2026-10-28"])
        self.assertEqual(payload["dataScope"], "public-display-v1")
        self.assertEqual([day["serviceDate"] for day in payload["serviceDays"]],
                         ["2026-10-26", "2026-10-27", "2026-10-28"])
        for day in payload["serviceDays"]:
            self.assertEqual(day["originStationId"], "Ikebukuro")
            self.assertEqual(day["destinationStationId"], "Hikawadai")
            self.assertEqual(len(day["departures"]), 2)
            direct, overnight = day["departures"]
            self.assertIsNotNone(direct["directAlternative"])
            self.assertIsNotNone(direct["bestTransferAlternative"])
            self.assertEqual(direct["bestTransferAlternative"]["kind"], "transfer")
            self.assertEqual(direct["departureText"], "06:10:00")
            self.assertEqual(overnight["departureText"], "25:50:00")
            self.assertEqual(day["destinationStatus"]["candidateCount"], 2)
            self.assertEqual(day["destinationStatus"]["routes"]["6"]["originTripCount"], 1)
            self.assertEqual(day["destinationStatus"]["routes"]["9"]["originTripCount"], 1)
        self.assertEqual(payload["feed"]["validFrom"], "2026-10-26")
        self.assertEqual(payload["feed"]["validThrough"], "2026-10-28")
        self.assertEqual(payload["applicationPeriod"]["endsAt"], "2026-10-29T00:00:00+09:00")

    def test_factory_reads_only_the_tracked_synthetic_test_fixture(self):
        self.assertEqual(factory.SOURCE_FIXTURE,
                         ROOT / "tests" / "fixtures" / "public_payload_profile_input.json")
        payload = factory.make_public_fixture("Wakoshi", ["2026-10-26", "2026-10-27", "2026-10-28"])
        encoded = json.dumps(payload, ensure_ascii=False)
        for private_or_diagnostic in (
            "synthetic-secret-must-drop", "drop-this-raw-uri", "/synthetic/private", "futureUnknownField",
        ):
            self.assertNotIn(private_or_diagnostic, encoded)
        self.assertIn("synthetic-trip:", encoded)
        self.assertIn("synthetic-feed-v1", encoded)

    def test_all_eight_payloads_share_profile_dates_and_station_mapping(self):
        dates = ["2026-10-26", "2026-10-27", "2026-10-28"]
        self.assertEqual(len(factory.STATION_FILES), 8)
        for destination_id in factory.STATION_FILES:
            with self.subTest(destination_id=destination_id):
                payload = factory.make_public_fixture(destination_id, dates)
                self.assertEqual(payload["dataScope"], "public-display-v1")
                self.assertEqual([day["serviceDate"] for day in payload["serviceDays"]], dates)
                self.assertTrue(all(day["originStationId"] == "Ikebukuro"
                                    and day["destinationStationId"] == destination_id
                                    for day in payload["serviceDays"]))

    def test_directory_regeneration_is_byte_deterministic_and_marked(self):
        with tempfile.TemporaryDirectory(prefix="synthetic-fixtures-test-") as temp:
            root = Path(temp)
            first = factory.generate_fixture_directory(root / "first", datetime(2026, 10, 27).date())
            second = factory.generate_fixture_directory(root / "second", datetime(2026, 10, 27).date())
            first_files = {path.name: path.read_bytes() for path in first["output"].iterdir()}
            second_files = {path.name: path.read_bytes() for path in second["output"].iterdir()}
            self.assertEqual(first_files, second_files)
            self.assertEqual(set(first_files), {*factory.STATION_FILES.values(), factory.SYNTHETIC_MARKER})
            self.assertEqual(first_files[factory.SYNTHETIC_MARKER],
                             factory.SYNTHETIC_MARKER_CONTENT.encode("utf-8"))
            self.assertEqual(first["service_dates"], ["2026-10-26", "2026-10-27", "2026-10-28"])

    def test_cli_defaults_to_jst_today_when_service_date_is_omitted(self):
        with tempfile.TemporaryDirectory(prefix="synthetic-fixtures-default-date-") as temp:
            output = Path(temp) / "fixtures"
            anchor = datetime(2026, 10, 27).date()
            with patch.object(fixture_cli, "jst_today", return_value=anchor), \
                    patch("sys.argv", ["generate_synthetic_public_fixtures.py", "--output", str(output)]):
                self.assertEqual(fixture_cli.main(), 0)
            payload = json.loads((output / factory.STATION_FILES["Hikawadai"]).read_text(encoding="utf-8"))
            self.assertEqual([day["serviceDate"] for day in payload["serviceDays"]],
                             ["2026-10-26", "2026-10-27", "2026-10-28"])

    def test_existing_output_is_preserved_and_missing_source_leaves_no_output(self):
        with tempfile.TemporaryDirectory(prefix="synthetic-fixtures-safety-") as temp:
            root = Path(temp)
            existing = root / "existing"
            existing.mkdir()
            sentinel = existing / "keep.txt"
            sentinel.write_text("keep", encoding="utf-8")
            with self.assertRaisesRegex(factory.SyntheticFixtureError, "already exists"):
                factory.generate_fixture_directory(existing, datetime(2026, 10, 27).date())
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")

            missing_source = root / "missing-source" / "fixtures"
            output = root / "must-not-remain"
            with patch.object(factory, "SOURCE_FIXTURE", missing_source):
                with self.assertRaises(factory.SyntheticFixtureError):
                    factory.generate_fixture_directory(output, datetime(2026, 10, 27).date())
            self.assertFalse(output.exists())
            self.assertEqual(list(root.glob(".synthetic-fixtures-*")), [])
            self.assertFalse((root / ".must-not-remain.synthetic-fixture.lock").exists())

    def test_unsupported_destination_and_malformed_dates_fail(self):
        with self.assertRaisesRegex(factory.SyntheticFixtureError, "unsupported"):
            factory.make_public_fixture("Unknown", ["2026-10-26"])
        with self.assertRaises(factory.SyntheticFixtureError):
            factory.make_public_fixture("Hikawadai", ["2026-10-26", "2026-10-27", "2026-02-30"])


if __name__ == "__main__":
    unittest.main()
