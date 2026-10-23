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
from odpt_stop_patterns import classify, resolve_type  # noqa: E402


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
        self.assertTrue(all(result.odpt.destination for result in enriched))
        primary = [result for result in results if result.primary_itinerary]
        self.assertEqual(sum(result.odpt.status == "unique_match" for result in primary), 435)
        f_liners = [result for result in primary if result.odpt.service_brand == "F-Liner"]
        self.assertEqual(len(f_liners), 23)
        self.assertTrue(all(result.odpt.train_type is None for result in f_liners))
        self.assertTrue(all(result.odpt.reported_train_type == "F-Liner" for result in f_liners))
        self.assertTrue(all(result.type_resolution.label == "Fライナー" for result in f_liners))
        self.assertTrue(any(result.route_id == "9" and result.primary_itinerary.kind == "transfer"
                            for result in f_liners))

    def test_stop_pattern_and_official_route_rule_counts_and_sources(self):
        for day, expected in (("2026-10-22", (426, 9, 0)),
                              ("2026-10-24", (387, 6, 3)),
                              ("2026-11-03", (387, 6, 3))):
            all_departures = self.generator.generate(day)
            primary = [r for r in all_departures if r.primary_itinerary]
            odpt_count = sum(r.type_resolution.source == "odpt_confirmed" for r in primary)
            unknown_count = sum(r.type_resolution.label == "種別不明" for r in primary)
            route_rule = [r for r in primary if r.type_resolution.source == "official_route_rule"]
            pattern_count = sum(r.type_resolution.source == "gtfs_stop_pattern" for r in primary)
            brand_count = sum(r.odpt.service_brand == "F-Liner" and r.type_resolution.label == "Fライナー"
                              for r in primary)
            unresolved_count = sum(r.odpt.status != "unique_match" for r in primary)
            self.assertEqual(odpt_count, expected[0])
            self.assertEqual(unknown_count, 0)
            self.assertFalse(any(r.type_resolution.source == "official_route_rule"
                                 for r in all_departures if not r.primary_itinerary))
            self.assertEqual(len(route_rule), 9 if day == "2026-10-22" else 6)
            self.assertEqual(pattern_count, expected[2])
            self.assertEqual(unresolved_count, expected[2])
            self.assertEqual(brand_count, 23 if day == "2026-10-22" else 24)
            self.assertTrue(all(r.odpt.train_type is None for r in primary
                                if r.odpt.reported_train_type in {"SemiExpress", "Rapid", "RapidExpress"}))
            self.assertTrue(all(r.type_resolution.label == "各駅停車"
                                and r.type_resolution.train_type == "Local"
                                and r.odpt.status == "unique_match"
                                and r.odpt.reported_train_type == r.odpt.unscoped_through_service_type
                                and r.type_resolution.diagnostic == "yurakucho_all_stops_official_route_rule"
                                for r in route_rule))

    def test_yurakucho_official_rule_requires_confirmed_scoped_eligible_trip(self):
        result = next(r for r in self.generator.generate("2026-10-22")
                      if r.type_resolution.source == "official_route_rule")
        trip = result.primary_itinerary.first_leg.trip
        self.assertTrue(self.generator._yurakucho_rule_eligible(trip))

        self.assertFalse(self.generator._yurakucho_rule_eligible(
            replace(trip, odpt=replace(trip.odpt, status="unmatched"))))
        self.assertFalse(self.generator._yurakucho_rule_eligible(replace(trip, route_id="9")))
        self.assertFalse(self.generator._yurakucho_rule_eligible(
            replace(trip, odpt=replace(trip.odpt, reported_train_type=None,
                                       unscoped_through_service_type=None))))
        self.assertFalse(self.generator._yurakucho_rule_eligible(
            replace(trip, odpt=replace(trip.odpt, raw_train_type_uri=None))))
        self.assertFalse(self.generator._yurakucho_rule_eligible(
            replace(trip, odpt=replace(trip.odpt, reported_train_type="S-TRAIN",
                                       unscoped_through_service_type="S-TRAIN"))))

        missing_stop = replace(trip, events=tuple(event for event in trip.events if event.stop_id != "607"))
        self.assertFalse(self.generator._yurakucho_rule_eligible(missing_stop))
        unusable_stop = replace(trip, events=tuple(
            replace(event, arrival_seconds=None, departure_seconds=None,
                    pickup_type="1", drop_off_type="1") if event.stop_id == "607" else event
            for event in trip.events))
        self.assertFalse(self.generator._yurakucho_rule_eligible(unusable_stop))

    def test_official_route_rule_source_is_gated_and_preserves_raw_type(self):
        states = {"kotake": "stop", "hikawadai": "missing", "senkawa": "stop", "kanamecho": "stop"}
        resolution = resolve_type("6", "unique_match", None, None,
                                  "all_stops_to_kotake_segment", states, "SemiExpress",
                                  official_route_rule_eligible=True)
        self.assertEqual(resolution.label, "各駅停車")
        self.assertEqual(resolution.source, "official_route_rule")
        self.assertEqual(resolution.train_type, "Local")
        self.assertEqual(resolution.reported_train_type, "SemiExpress")
        self.assertEqual(resolution.diagnostic, "yurakucho_all_stops_official_route_rule")

        for route_id, status, raw_type in (("9", "unique_match", "SemiExpress"),
                                           ("6", "unmatched", "SemiExpress"),
                                           ("6", "unique_match", "S-TRAIN")):
            with self.subTest(route_id=route_id, status=status, raw_type=raw_type):
                withheld = resolve_type(route_id, status, None, None,
                                        "all_stops_to_kotake_segment", states, raw_type,
                                        official_route_rule_eligible=True)
                self.assertNotEqual(withheld.source, "official_route_rule")

    def test_odpt_pattern_conflict_is_held_for_diagnosis(self):
        states = {"kotake": "stop", "hikawadai": "stop", "senkawa": "stop", "kanamecho": "stop"}
        resolution = resolve_type("9", "unique_match", "F-Liner", None, "local", states)
        self.assertEqual(resolution.source, "unknown")
        self.assertEqual(resolution.label, "種別不明")
        self.assertEqual(resolution.validation, "conflict")
        self.assertEqual(resolution.reported_train_type, "F-Liner")
        self.assertEqual(resolution.diagnostic, "odpt_stop_pattern_conflict")

    def test_stop_pattern_fallback_requires_an_unmatched_odpt_record(self):
        states = {"kotake": "stop", "hikawadai": "stop", "senkawa": "pass", "kanamecho": "pass"}
        for status in ("ambiguous", "unavailable"):
            with self.subTest(status=status):
                resolution = resolve_type("9", status, None, None, "commuter_express", states)
                self.assertEqual(resolution.source, "unknown")
                self.assertEqual(resolution.label, "種別不明")

    def test_missing_required_stop_row_is_not_filled_by_pattern_fallback(self):
        states = {"kotake": "stop", "hikawadai": "missing", "senkawa": "stop", "kanamecho": "stop"}
        self.assertEqual(classify("9", states), "unclassifiable")
        resolution = resolve_type("9", "unmatched", None, None, "unclassifiable", states)
        self.assertEqual(resolution.label, "種別不明")
        self.assertEqual(resolution.source, "unknown")

    def test_compact_json_dto_contains_no_raw_odpt_or_full_stop_list(self):
        result = self.generator.generate("2026-10-22")[0]
        dto = to_dict(result)
        encoded = json.dumps(dto, ensure_ascii=False)
        self.assertIn("primary_itinerary", dto)
        self.assertNotIn("odpt:trainTimetableObject", encoded)
        self.assertNotIn("events", dto["primary_itinerary"]["first_leg"]["trip"])


if __name__ == "__main__":
    unittest.main()
