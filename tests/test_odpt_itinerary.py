from __future__ import annotations

import sys
import unittest
import json
from dataclasses import replace
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from odpt_itinerary import (  # noqa: E402
    DEFAULT_DATA_DIR,
    DEFAULT_GTFS,
    FeedDateError,
    ItineraryGenerator,
    choose_primary,
    format_service_time,
    parse_gtfs_time,
    to_dict,
)


@unittest.skipUnless(DEFAULT_GTFS.exists(), "local Tokyo Metro GTFS ZIP is not present")
class LocalFeedItineraryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.generator = ItineraryGenerator(DEFAULT_GTFS, DEFAULT_DATA_DIR)

    def test_service_time_keeps_after_midnight_service_seconds(self):
        self.assertEqual(parse_gtfs_time("24:02:00"), 86520)
        self.assertEqual(format_service_time(86520), "24:02:00")
        self.assertEqual(parse_gtfs_time("06:42"), 24120)
        self.assertIsNone(parse_gtfs_time(""))

    def test_weekday_direct_transfer_and_connection_boundaries(self):
        results = self.generator.generate("2026-10-22")
        self.assertEqual(len(results), 439)
        self.assertEqual(sum(r.direct_alternative is not None for r in results), 287)
        self.assertEqual(sum(r.best_transfer_alternative is not None for r in results), 417)
        self.assertEqual(sum(r.transfer_candidates_count > 1 for r in results), 189)
        self.assertEqual(self.generator.last_wait_histogram.get(0), 23)
        self.assertEqual(self.generator.last_wait_histogram.get(60), 66)
        self.assertEqual(self.generator.last_wait_histogram.get(120), 60)
        accepted_waits = [r.best_transfer_alternative.transfer_wait_seconds for r in results
                          if r.best_transfer_alternative]
        self.assertTrue(all(60 <= wait <= 600 for wait in accepted_waits))
        self.assertEqual(sum(count for wait, count in self.generator.last_wait_histogram.items()
                             if 60 <= wait <= 600), 622)
        self.assertTrue(any(r.primary_itinerary and r.primary_itinerary.arrival_seconds >= 86400
                            for r in results))
        self.assertEqual(sum(r.primary_itinerary.kind == "direct" for r in results if r.primary_itinerary), 287)

    def test_saturday_and_holiday_exceptions(self):
        saturday = self.generator.generate("2026-10-24")
        holiday = self.generator.generate("2026-11-03")
        for results in (saturday, holiday):
            self.assertEqual(len(results), 405)
            self.assertEqual(sum(r.direct_alternative is not None for r in results), 240)
            self.assertEqual(sum(r.best_transfer_alternative is not None for r in results), 366)
            self.assertEqual(self.generator.last_wait_histogram.get(60), 80)
            self.assertEqual(self.generator.last_wait_histogram.get(120), 29)
            self.assertTrue(any(r.primary_itinerary and r.primary_itinerary.arrival_seconds >= 86400
                                for r in results))

    def test_unusable_hikawadai_times_are_not_fabricated(self):
        for day, expected in (("2026-10-22", 13), ("2026-10-24", 34)):
            results = self.generator.generate(day)
            missing = sum("destination_arrival_missing" in r.data_quality for r in results)
            prohibited = sum("destination_alighting_prohibited" in r.data_quality for r in results)
            self.assertEqual(missing, expected)
            self.assertEqual(prohibited, expected)
            for result in results:
                if result.status == "no_valid_arrival":
                    self.assertIsNone(result.primary_itinerary)

    def test_primary_is_single_and_ties_prefer_direct(self):
        results = self.generator.generate("2026-10-22")
        for result in results:
            if result.primary_itinerary and result.direct_alternative and result.best_transfer_alternative:
                direct = result.direct_alternative
                transfer = result.best_transfer_alternative
                if direct.arrival_seconds == transfer.arrival_seconds:
                    self.assertEqual(result.primary_itinerary.kind, "direct")
            if result.best_transfer_alternative:
                self.assertEqual(result.best_transfer_alternative.kind, "transfer")
                self.assertNotEqual(result.best_transfer_alternative.first_leg.trip.trip_id,
                                    result.best_transfer_alternative.second_leg.trip.trip_id)
        comparable = next(r for r in results if r.direct_alternative and r.best_transfer_alternative)
        tied_direct = replace(comparable.direct_alternative,
                              arrival_seconds=comparable.best_transfer_alternative.arrival_seconds)
        self.assertEqual(choose_primary(tied_direct, comparable.best_transfer_alternative).kind, "direct")

    def test_feed_outside_validity_raises(self):
        with self.assertRaises(FeedDateError):
            self.generator.generate(date(2026, 9, 18))

    def test_odpt_enrichment_is_only_exposed_when_unique(self):
        results = self.generator.generate("2026-10-22")
        enriched = [result for result in results if result.odpt.status == "unique_match"]
        self.assertTrue(enriched)
        self.assertTrue(all(result.odpt.train_type for result in enriched))
        self.assertTrue(all(result.odpt.destination for result in enriched))

    def test_compact_json_dto_contains_no_raw_odpt_or_full_stop_list(self):
        result = self.generator.generate("2026-10-22")[0]
        dto = to_dict(result)
        encoded = json.dumps(dto, ensure_ascii=False)
        self.assertIn("primary_itinerary", dto)
        self.assertNotIn("odpt:trainTimetableObject", encoded)
        self.assertNotIn("events", dto["primary_itinerary"]["first_leg"]["trip"])


if __name__ == "__main__":
    unittest.main()
