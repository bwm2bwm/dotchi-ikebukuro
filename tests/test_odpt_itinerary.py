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
    DESTINATIONS,
    FeedDateError,
    ItineraryGenerator,
    ROUTE_STOP_IDS,
    VERIFIED_DESTINATION_IDS,
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

    def test_phase1_destination_catalog_has_route_scoped_ids_and_outbound_order(self):
        expected = {
            "Kanamecho": ("608", "908"), "Senkawa": ("607", "907"),
            "KotakeMukaihara": ("606", "906"), "Hikawadai": ("605", "905"),
            "Heiwadai": ("604", "904"), "ChikatetsuAkatsuka": ("603", "903"),
            "ChikatetsuNarimasu": ("602", "902"), "Wakoshi": ("601", "901"),
        }
        self.assertEqual(set(DESTINATIONS), set(expected))
        for station_id, (y_stop, f_stop) in expected.items():
            with self.subTest(station_id=station_id):
                destination = DESTINATIONS[station_id]
                self.assertEqual(destination["routeStopIds"], {"6": y_stop, "9": f_stop})
                self.assertIn(y_stop, self.generator.stops)
                self.assertIn(f_stop, self.generator.stops)
                self.assertEqual(self.generator.stops[y_stop]["stop_name"], destination["name"])
                self.assertEqual(self.generator.stops[f_stop]["stop_name"], destination["name"])
        self.assertEqual([DESTINATIONS[key]["outboundOrder"] for key in expected],
                         list(range(1, 9)))
        for route_id in ("6", "9"):
            for trip_id, trip in self.generator.trips.items():
                if trip.get("route_id") != route_id:
                    continue
                events = self.generator.events[trip_id]
                ikebukuro = next((event for event in events
                                  if event.stop_id in ROUTE_STOP_IDS[route_id]["ikebukuro"]), None)
                if ikebukuro is None:
                    continue
                order_by_stop = {value["routeStopIds"][route_id]: value["outboundOrder"]
                                 for value in DESTINATIONS.values()}
                observed = [order_by_stop[event.stop_id] for event in events
                            if event.sequence > ikebukuro.sequence and event.stop_id in order_by_stop]
                self.assertEqual(observed, sorted(observed))

    def test_phase3_destinations_are_verified_and_unknown_id_is_rejected(self):
        for destination_id in ("Heiwadai", "ChikatetsuAkatsuka", "ChikatetsuNarimasu", "Wakoshi"):
            with self.subTest(destination_id=destination_id):
                self.assertIn(destination_id, VERIFIED_DESTINATION_IDS)
                ItineraryGenerator(DEFAULT_GTFS, DEFAULT_DATA_DIR,
                                   destination_station_id=destination_id)
        with self.assertRaisesRegex(ValueError, "Unknown destination"):
            ItineraryGenerator(DEFAULT_GTFS, DEFAULT_DATA_DIR, destination_station_id="ShinjukuSanchome")

    def test_phase3_targets_generate_only_valid_same_trip_direct_journeys(self):
        expected = {
            "Heiwadai": {"2026-10-22": (150, 137, 13, 7),
                         "2026-10-24": (129, 111, 34, 8),
                         "2026-11-03": (129, 111, 34, 8)},
            "ChikatetsuAkatsuka": {"2026-10-22": (150, 137, 13, 7),
                                   "2026-10-24": (129, 111, 34, 8),
                                   "2026-11-03": (129, 111, 34, 8)},
            "ChikatetsuNarimasu": {"2026-10-22": (150, 137, 13, 8),
                                   "2026-10-24": (129, 111, 34, 9),
                                   "2026-11-03": (129, 111, 34, 9)},
            "Wakoshi": {"2026-10-22": (150, 150, 0, 8),
                        "2026-10-24": (129, 145, 0, 9),
                        "2026-11-03": (129, 145, 0, 9)},
        }
        for destination_id, by_day in expected.items():
            generator = ItineraryGenerator(DEFAULT_GTFS, DEFAULT_DATA_DIR,
                                           destination_station_id=destination_id)
            target = DESTINATIONS[destination_id]
            for service_date, (y_count, f_count, pass_count, after_midnight) in by_day.items():
                with self.subTest(destination=destination_id, service_date=service_date):
                    rows = generator.generate(service_date)
                    coverage = generator.last_destination_status
                    self.assertEqual(coverage["status"], "normal")
                    self.assertEqual(coverage["candidateCount"], y_count + f_count)
                    self.assertEqual(coverage["passThroughCount"], pass_count)
                    self.assertEqual(coverage["dataInsufficientCount"], 0)
                    self.assertEqual(coverage["routes"]["6"]["candidateCount"], y_count)
                    self.assertEqual(coverage["routes"]["9"]["candidateCount"], f_count)
                    self.assertEqual(coverage["routes"]["6"]["passThroughCount"] +
                                     coverage["routes"]["9"]["passThroughCount"], pass_count)
                    candidates = [row for row in rows if row.primary_itinerary]
                    self.assertEqual(len(candidates), y_count + f_count)
                    self.assertEqual(sum(row.primary_itinerary.arrival_seconds >= 86400
                                         for row in candidates), after_midnight)
                    for row in candidates:
                        itinerary = row.primary_itinerary
                        self.assertEqual(itinerary.kind, "direct")
                        self.assertIsNone(itinerary.second_leg)
                        self.assertEqual(itinerary.first_leg.trip.trip_id, row.origin_trip_id)
                        self.assertEqual(itinerary.arrival_station_id, destination_id)
                        self.assertEqual(itinerary.first_leg.alight.stop_id,
                                         target["routeStopIds"][row.route_id])
                        self.assertTrue(itinerary.first_leg.alight.can_alight)
                        self.assertIsNotNone(itinerary.first_leg.alight.arrival_seconds)
                        route_order = {value["routeStopIds"][row.route_id]: value["outboundOrder"]
                                       for value in DESTINATIONS.values()}
                        path_events = [event for event in itinerary.first_leg.trip.events
                                       if itinerary.first_leg.board.sequence <= event.sequence
                                       <= itinerary.first_leg.alight.sequence
                                       and event.stop_id in route_order]
                        self.assertEqual([route_order[event.stop_id] for event in path_events],
                                         sorted(route_order[event.stop_id] for event in path_events))
                        path_times = [seconds for event in path_events
                                      for seconds in (event.arrival_seconds, event.departure_seconds)
                                      if seconds is not None]
                        self.assertTrue(all(later >= earlier for earlier, later in
                                            zip(path_times, path_times[1:])))
                    passed = [row for row in rows
                              if "destination_explicit_pass" in row.data_quality]
                    self.assertEqual(len(passed), pass_count)
                    self.assertTrue(all(row.primary_itinerary is None for row in passed))

    def test_phase2_targets_generate_same_trip_direct_only_and_classify_data(self):
        expected = {
            "Kanamecho": {"2026-10-22": (219, 152, 68), "2026-10-24": (190, 154, 61),
                          "2026-11-03": (190, 154, 61)},
            "Senkawa": {"2026-10-22": (219, 152, 68), "2026-10-24": (190, 154, 61),
                        "2026-11-03": (190, 154, 61)},
            "KotakeMukaihara": {"2026-10-22": (219, 220, 0), "2026-10-24": (190, 212, 3),
                                "2026-11-03": (190, 212, 3)},
        }
        baseline = ItineraryGenerator(DEFAULT_GTFS, DEFAULT_DATA_DIR)
        for destination_id, by_day in expected.items():
            generator = ItineraryGenerator(DEFAULT_GTFS, DEFAULT_DATA_DIR,
                                           destination_station_id=destination_id)
            target = DESTINATIONS[destination_id]
            for service_date, (y_count, f_count, pass_count) in by_day.items():
                with self.subTest(destination=destination_id, service_date=service_date):
                    old_rows = {row.origin_trip_id: row for row in baseline.generate(service_date)}
                    rows = generator.generate(service_date)
                    coverage = generator.last_destination_status
                    self.assertEqual(coverage["status"], "normal")
                    self.assertEqual(coverage["candidateCount"], y_count + f_count)
                    self.assertEqual(coverage["passThroughCount"], pass_count)
                    self.assertEqual(coverage["dataInsufficientCount"], 0)
                    self.assertEqual(coverage["routes"]["6"]["candidateCount"], y_count)
                    self.assertEqual(coverage["routes"]["9"]["candidateCount"], f_count)
                    self.assertTrue(all(row.primary_itinerary is None or
                                        row.primary_itinerary.kind == "direct" for row in rows))
                    self.assertTrue(all(row.best_transfer_alternative is None for row in rows))
                    candidates = [row for row in rows if row.primary_itinerary]
                    self.assertEqual(len(candidates), y_count + f_count)
                    for row in rows:
                        old = old_rows[row.origin_trip_id]
                        self.assertEqual(row.odpt, old.odpt)
                        self.assertEqual(row.type_resolution.reported_train_type,
                                         old.type_resolution.reported_train_type)
                        if row.primary_itinerary:
                            itinerary = row.primary_itinerary
                            self.assertEqual(itinerary.first_leg.trip.trip_id, row.origin_trip_id)
                            self.assertIsNone(itinerary.second_leg)
                            self.assertEqual(itinerary.arrival_station_id, destination_id)
                            stop_id = target["routeStopIds"][row.route_id]
                            self.assertEqual(itinerary.first_leg.alight.stop_id, stop_id)
                            self.assertTrue(itinerary.first_leg.alight.can_alight)
                            self.assertIsNotNone(itinerary.first_leg.alight.arrival_seconds)
                            self.assertGreaterEqual(itinerary.arrival_seconds, row.departure_seconds)
                            path_events = [event for event in itinerary.first_leg.trip.events
                                           if itinerary.first_leg.board.sequence <= event.sequence
                                           <= itinerary.first_leg.alight.sequence]
                            path_times = [seconds for event in path_events
                                          for seconds in (event.arrival_seconds, event.departure_seconds)
                                          if seconds is not None]
                            self.assertTrue(all(later >= earlier for earlier, later in
                                                zip(path_times, path_times[1:])))
                    passed = [row for row in rows if "destination_explicit_pass" in row.data_quality]
                    self.assertEqual(len(passed), pass_count)
                    self.assertTrue(all(row.primary_itinerary is None for row in passed))

    def test_missing_destination_stop_record_is_data_insufficient_not_a_pass(self):
        generator = ItineraryGenerator(DEFAULT_GTFS, DEFAULT_DATA_DIR,
                                       destination_station_id="Kanamecho")
        target_ids = set(DESTINATIONS["Kanamecho"]["routeStopIds"].values())
        for trip_id, events in list(generator.events.items()):
            if generator.trips[trip_id].get("route_id") not in ("6", "9"):
                continue
            generator.events[trip_id] = tuple(event for event in events if event.stop_id not in target_ids)
        rows = generator.generate("2026-10-22")
        self.assertEqual(sum(row.primary_itinerary is not None for row in rows), 0)
        self.assertEqual(generator.last_destination_status["status"], "data_insufficient")
        self.assertGreater(generator.last_destination_status["dataInsufficientCount"], 0)
        self.assertTrue(all("destination_explicit_pass" not in row.data_quality for row in rows))

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
