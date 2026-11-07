"""Passenger access evidence must not erase matcher or diagnostic evidence."""
import copy
from dataclasses import replace
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from odpt_itinerary import ItineraryGenerator, StopEvent
from odpt_public_v2 import _route_state
from odpt_snapshot_qa import _classify_diagnostics


class PassengerCoverageTests(unittest.TestCase):
    def setUp(self):
        self.g = object.__new__(ItineraryGenerator)
        self.record = {
            "odpt:trainType": "odpt.TrainType:TokyoMetro.S-TRAIN",
            "odpt:railDirection": "odpt.RailDirection:TokyoMetro.Wakoshi",
            "odpt:destinationStation": ["odpt.Station:Seibu.Ikebukuro.Hanno"],
            "odpt:trainTimetableObject": [{
                "odpt:arrivalStation": "odpt.Station:TokyoMetro.Fukutoshin.Ikebukuro",
                "odpt:arrivalTime": "08:39"}],
        }
        self.g._odpt_index = lambda route, cal: {"B771M": [self.record]}
        self.trip = NS(route_id="9", trip_id="93B0771M00", departure_seconds=31140,
                       origin_event=NS(sequence=8),
                       events=(StopEvent("906", None, 11, 31380, 31380, "1", "1", None),))
        self.metrics = dict(scheduledTripCount=10, originTripCount=1,
                            dataInsufficientCount=0, transferDataInsufficientCount=0)

    def row(self, **kwargs):
        values = dict(route_id="9", primary_itinerary=object(), direct_alternative=None,
                      best_transfer_alternative=None, data_quality=[],
                      odpt=NS(status="unmatched", match_reason="destination_has_no_independent_gtfs_crosswalk"))
        values.update(kwargs)
        return NS(**values)

    def state(self, row):
        return _route_state("9", self.metrics, [row])["dataState"]

    def test_official_rule_is_narrow_and_does_not_mutate_raw(self):
        before = copy.deepcopy(self.record)
        self.assertTrue(self.g._origin_boarding_prohibited(self.trip, "SaturdayHoliday"))
        self.assertEqual(before, self.record)
        self.assertFalse(self.g._origin_boarding_prohibited(self.trip, "Weekday"))
        self.trip.route_id = "6"
        self.assertFalse(self.g._origin_boarding_prohibited(self.trip, "SaturdayHoliday"))

    def test_missing_or_conflicting_rule_evidence_is_not_an_exclusion(self):
        cases = [("odpt:trainType", "odpt.TrainType:TokyoMetro.CommuterExpress"),
                 ("odpt:railDirection", "odpt.RailDirection:TokyoMetro.Shibuya"),
                 ("odpt:destinationStation", []),
                 ("odpt:destinationStation", ["odpt.Station:Tobu.Tojo.Wakoshi"]),
                 ("odpt:trainTimetableObject", []),
                 ("odpt:trainTimetableObject", [{"odpt:arrivalStation": "other",
                                                "odpt:arrivalTime": "08:39"}])]
        for key, value in cases:
            old = self.record[key]
            self.record[key] = value
            with self.subTest(key=key, value=value):
                self.assertFalse(self.g._origin_boarding_prohibited(self.trip, "SaturdayHoliday"))
            self.record[key] = old
        event = self.record["odpt:trainTimetableObject"][0]
        event["odpt:departureTime"] = "08:39"
        self.assertFalse(self.g._origin_boarding_prohibited(self.trip, "SaturdayHoliday"))
        del event["odpt:departureTime"]
        event["odpt:arrivalTime"] = "08:40"
        self.assertFalse(self.g._origin_boarding_prohibited(self.trip, "SaturdayHoliday"))

    def test_kotake_pickup_or_ambiguous_identity_prevents_rule_exclusion(self):
        self.trip.events = (replace(self.trip.events[0], pickup_type="0"),)
        self.assertFalse(self.g._origin_boarding_prohibited(self.trip, "SaturdayHoliday"))
        self.trip.events = (replace(self.trip.events[0], pickup_type="1"),)
        self.g._odpt_index = lambda route, cal: {"B771M": [self.record, self.record]}
        self.assertFalse(self.g._origin_boarding_prohibited(self.trip, "SaturdayHoliday"))

    def test_crosswalk_gap_does_not_bypass_unchecked_stop_order(self):
        self.trip.events = (replace(self.trip.events[0], pickup_type="0", drop_off_type="0"),)
        match = NS(reason="destination_has_no_independent_gtfs_crosswalk", candidates=("B771M",))
        matcher = NS(match=lambda *args: match,
                     station_lookup={("9", "小竹向原"): "odpt.Station:TokyoMetro.Fukutoshin.KotakeMukaihara"},
                     stop_names={"906": "小竹向原"})
        result = self.g._enrich(self.trip, "SaturdayHoliday", matcher)
        self.assertEqual(result.status, "unmatched")
        self.assertEqual(result.match_reason, "ordered_stop_sequence_conflict")

    def test_enrichment_only_gap_does_not_hide_valid_journey_or_explicit_pass(self):
        r = self.row()
        self.assertEqual(self.state(r), "complete")
        self.assertEqual(r.odpt.status, "unmatched")
        self.assertEqual(self.state(self.row(primary_itinerary=None,
                                            data_quality=["destination_explicit_pass"])), "complete")

    def test_unknowns_and_independent_warnings_still_block(self):
        self.assertEqual(self.state(self.row(primary_itinerary=None)), "insufficient")
        for reason in (None, "ordered_stop_sequence_conflict", "destination_headsign_conflict",
                       "no_route_calendar_number_and_exact_departure_candidate"):
            self.assertEqual(self.state(self.row(odpt=NS(status="unmatched", match_reason=reason))), "insufficient")
        self.assertEqual(self.state(self.row(data_quality=["destination_arrival_missing"])), "insufficient")

    def test_known_boarding_ban_preserves_warning_but_contradictory_journey_blocks(self):
        r = self.row(primary_itinerary=None, origin_boarding_prohibited_rule=
                     "s_train_saturday_holiday_seibu_bound_ikebukuro_alight_only",
                     data_quality=["kotake_alighting_prohibited", "origin_boarding_prohibited_official_rule"])
        self.assertTrue(_classify_diagnostics(r)["WARNING"])
        self.assertEqual(self.state(r), "complete")
        r.data_quality.append("destination_stop_record_ambiguous")
        self.assertEqual(self.state(r), "insufficient")
        r.data_quality.pop()
        r.primary_itinerary = object()
        self.assertEqual(self.state(r), "insufficient")
        r.primary_itinerary = None
        self.metrics["dataInsufficientCount"] = 1
        self.assertEqual(self.state(r), "insufficient")


if __name__ == "__main__":
    unittest.main()
