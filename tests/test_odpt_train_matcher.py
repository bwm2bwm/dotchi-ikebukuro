from __future__ import annotations

import json
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from odpt_itinerary import DEFAULT_DATA_DIR, DEFAULT_GTFS, StopEvent, TripInstance  # noqa: E402
from odpt_train_matcher import (  # noqa: E402
    OdptTrainMatcher,
    parse_trip_number,
    station_lookup_from_odpt,
    type_scope,
)


FUKU = "odpt.Railway:TokyoMetro.Fukutoshin"
STATION = "odpt.Station:TokyoMetro.Fukutoshin."
DEST = "odpt.Station:Seibu.Ikebukuro.ShakujiiKoen"


def sample_trip(trip_id="91B0565S00", route="9", calendar_day="Weekday",
                departure=21600, headsign="小手指", reverse=False):
    stations = ["渋谷", "池袋", "小竹向原"]
    if reverse:
        stations = list(reversed(stations))
    events = tuple(StopEvent(
        stop_id=str(index), station=name, sequence=index,
        arrival_seconds=departure + index * 60, departure_seconds=departure + index * 60,
        pickup_type="0", drop_off_type="0", timepoint="1",
    ) for index, name in enumerate(stations))
    return TripInstance("2026-10-22", trip_id, "service", route, "副都心線", headsign,
                        departure, "06:00:00", events[1], events)


def sample_record(number="B565S", calendar="Weekday", departure="06:00", destination=DEST,
                  reverse=False):
    stations = ["Shibuya", "Ikebukuro", "KotakeMukaihara"]
    if reverse:
        stations = list(reversed(stations))
    timetable = [{"odpt:departureTime": departure if station == "Ikebukuro" else "05:59",
                  "odpt:departureStation": STATION + station}
                 for station in stations[:-1]]
    timetable.append({"odpt:arrivalTime": "06:02", "odpt:arrivalStation": STATION + stations[-1]})
    return {
        "odpt:railway": FUKU,
        "odpt:calendar": f"odpt.Calendar:{calendar}",
        "odpt:trainNumber": number,
        "odpt:train": f"odpt.Train:TokyoMetro.Fukutoshin.{number}",
        "odpt:trainType": "odpt.TrainType:TokyoMetro.Local",
        "odpt:destinationStation": [destination],
        "odpt:trainTimetableObject": timetable,
    }


class TripNumberTests(unittest.TestCase):
    def test_observed_padding_zero_and_leading_zero_rules(self):
        parsed = parse_trip_number("61B0565S00", "6")
        self.assertEqual(parsed.calendar, "Weekday")
        self.assertEqual(parsed.candidates, ("B0565S", "B565S"))

    def test_observed_20_suffix_is_preserved_as_terminal_two(self):
        parsed = parse_trip_number("91B0526K20", "9")
        self.assertEqual(parsed.candidates, ("B0526K2", "B526K2"))
        self.assertEqual(parse_trip_number("91B0526K30", "9"), None)

    def test_route_and_prefix_calendar_are_validated(self):
        self.assertIsNone(parse_trip_number("91B0565S00", "6"))
        self.assertEqual(parse_trip_number("93B0565S00", "9").calendar, "SaturdayHoliday")


class SyntheticMatcherTests(unittest.TestCase):
    def setUp(self):
        self.lookup = {
            ("9", "渋谷"): STATION + "Shibuya",
            ("9", "池袋"): STATION + "Ikebukuro",
            ("9", "小竹向原"): STATION + "KotakeMukaihara",
        }
        self.matcher = OdptTrainMatcher(
            {"Fukutoshin": [sample_record()]}, self.lookup,
            {DEST: {"小手指"}},
        )

    def test_unique_number_time_destination_and_stop_order_confirms(self):
        result = self.matcher.match(sample_trip(), "Weekday", ["91B0565S00"])
        self.assertEqual(result.status, "confirmed")
        self.assertEqual(result.odpt_record["odpt:trainNumber"], "B565S")

    def test_normalized_number_collision_is_ambiguous(self):
        result = self.matcher.match(sample_trip(), "Weekday",
                                    ["91B0565S00", "90B0565S00"])
        self.assertEqual(result.status, "ambiguous")
        self.assertEqual(result.reason, "normalized_number_collides_with_other_active_gtfs_trip")

    def test_same_time_multiple_odpt_candidates_are_ambiguous(self):
        records = [sample_record(), sample_record(number="B565S")]
        matcher = OdptTrainMatcher({"Fukutoshin": records}, self.lookup, {DEST: {"小手指"}})
        self.assertEqual(matcher.match(sample_trip(), "Weekday").status, "ambiguous")

    def test_service_calendar_and_route_mismatch_do_not_confirm(self):
        wrong_day = self.matcher.match(sample_trip(), "SaturdayHoliday")
        self.assertEqual(wrong_day.status, "unmatched")
        wrong_route = self.matcher.match(sample_trip(trip_id="61B0565S00", route="6"), "Weekday")
        self.assertEqual(wrong_route.status, "unmatched")

    def test_destination_and_stop_order_conflicts_remain_unconfirmed(self):
        bad_destination = OdptTrainMatcher(
            {"Fukutoshin": [sample_record(destination="odpt.Station:Seibu.Ikebukuro.Hoya")]},
            self.lookup, {"odpt.Station:Seibu.Ikebukuro.Hoya": {"保谷"}},
        )
        self.assertEqual(bad_destination.match(sample_trip(), "Weekday").reason,
                         "destination_headsign_conflict")
        bad_order = OdptTrainMatcher(
            {"Fukutoshin": [sample_record(reverse=True)]}, self.lookup, {DEST: {"小手指"}},
        )
        self.assertEqual(bad_order.match(sample_trip(), "Weekday").reason,
                         "ordered_stop_sequence_conflict")

    def test_unknown_destination_crosswalk_is_not_assumed(self):
        matcher = OdptTrainMatcher({"Fukutoshin": [sample_record()]}, self.lookup)
        result = matcher.match(sample_trip(), "Weekday")
        self.assertEqual(result.status, "candidate_unconfirmed")
        self.assertEqual(result.reason, "destination_has_no_independent_gtfs_crosswalk")


class TypeScopeTests(unittest.TestCase):
    def test_raw_type_metro_type_and_brand_are_separate(self):
        self.assertEqual(type_scope("F-Liner", "9")["metro_line_type"], None)
        self.assertEqual(type_scope("F-Liner", "9")["service_brand"], "F-Liner")
        self.assertEqual(type_scope("odpt.TrainType:TokyoMetro.F-Liner", "9")["odpt_raw_type"],
                         "odpt.TrainType:TokyoMetro.F-Liner")
        self.assertEqual(type_scope("Local", "9")["metro_line_type"], "Local")
        self.assertEqual(type_scope("SemiExpress", "6")["other_operator_type"], None)
        self.assertEqual(type_scope("SemiExpress", "6")["unscoped_through_service_type"], "SemiExpress")


@unittest.skipUnless(DEFAULT_GTFS.exists() and (DEFAULT_DATA_DIR / "Station_all.json").exists(),
                     "saved GTFS/ODPT data not present")
class RealDataRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from validate_odpt_train_matching import run
        cls.report = run(["2026-10-22", "2026-10-24", "2026-11-03"], DEFAULT_GTFS, DEFAULT_DATA_DIR)

    def test_all_879_known_controls_confirm(self):
        self.assertEqual(self.report["legacy_known_controls"], 879)
        self.assertEqual(self.report["counts"].get("known_control:confirmed"), 879)

    def test_all_100_residual_unknowns_confirm_across_representative_dates(self):
        self.assertEqual(self.report["residual_unknown_total"], 100)
        self.assertEqual(self.report["counts"].get("residual_unknown:confirmed"), 100)
        self.assertEqual(self.report["residual_by_day"]["2026-10-22"], {"confirmed": 38})
        self.assertEqual(self.report["residual_by_day"]["2026-10-24"], {"confirmed": 31})
        self.assertEqual(self.report["residual_by_day"]["2026-11-03"], {"confirmed": 31})
        self.assertEqual([row for row in self.report["unconfirmed"]
                          if row["group"] == "residual_unknown"], [])

    def test_full_primary_population_keeps_six_unsupported_destinations_unconfirmed(self):
        self.assertEqual(self.report["primary_journey_total"], 1227)
        self.assertEqual(self.report["other_unmatched_total"], 248)
        self.assertEqual(self.report["counts"].get("pattern_classified_unmatched:confirmed"), 242)
        self.assertEqual(self.report["counts"].get("pattern_classified_unmatched:candidate_unconfirmed"), 6)
        self.assertTrue(all(row["reason"] == "destination_has_no_independent_gtfs_crosswalk"
                            for row in self.report["unconfirmed"]))


if __name__ == "__main__":
    unittest.main()
