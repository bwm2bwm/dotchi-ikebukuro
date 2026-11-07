import copy
from datetime import date
from types import SimpleNamespace as NS
import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import odpt_snapshot_qa as qa
import odpt_public_v2 as v

class QualityGateTests(unittest.TestCase):
    def rows(self):
        a=NS(odpt=NS(status='unmatched',match_reason='no_route_calendar_number_and_exact_departure_candidate'),
             primary_itinerary=None,direct_alternative=None,best_transfer_alternative=None,
             origin_boarding_prohibited_rule='s_train_saturday_holiday_seibu_bound_ikebukuro_alight_only',
             data_quality=['kotake_alighting_prohibited','origin_boarding_prohibited_official_rule'])
        b=NS(odpt=NS(status='unmatched',match_reason='destination_has_no_independent_gtfs_crosswalk',passenger_match_verified=True),
             primary_itinerary=object(),best_transfer_alternative=None,data_quality=[])
        return a,b
    def report(self):
        resolution=qa._resolution_summary(self.rows())
        days=[dict(stationId=s,serviceDate=d,status='ok',resolution=copy.deepcopy(resolution),
                   odptMatchStatusCounts={'unmatched':2},diagnosticSeverity={'WARNING':{'codeOccurrences':2}},
                   routeCoverage={r:{'dataState':'complete'} for r in v.ROUTES})
              for s in v.DESTINATIONS for d in ['2026-11-06','2026-11-07','2026-11-08']]
        return dict(status='WARNING',sourceFingerprint='a'*64,serviceDate='2026-11-07',
                    requestedServiceDates=['2026-11-06','2026-11-07','2026-11-08'],stationCount=8,dayResultCount=24,
                    dayResults=days,summary=dict(resolution=qa._merge_resolutions(d['resolution'] for d in days),
                    unmatchedOdptJourneyCount=48,diagnosticSeverity={'WARNING':{'codeOccurrences':48},'FAIL':{'failGateCount':0}}))
    def check(self,r):
        v._validate_odpt0_report(r,date(2026,11,7),['2026-11-06','2026-11-07','2026-11-08'],'a'*64)
    def test_warning_status_and_original_counts_survive(self):
        r=self.report();before=copy.deepcopy(r);self.check(r);self.assertEqual(r,before)
        self.assertEqual(r['summary']['resolution']['classes'],dict(A=24,B=24,C=0,D=0))
    def test_missing_evidence_extra_warning_and_conflict_block(self):
        a,b=self.rows();a.origin_boarding_prohibited_rule=None
        self.assertEqual(qa._resolution_class(a),'C')
        a,b=self.rows();a.data_quality.append('unexpected_warning')
        self.assertEqual(qa._resolution_class(a),'C')
        a,b=self.rows();b.odpt.passenger_match_verified=False
        self.assertEqual(qa._resolution_class(b),'C')
        b.odpt.match_reason='ordered_stop_sequence_conflict'
        self.assertEqual(qa._resolution_class(b),'D')
        a,b=self.rows();a.primary_itinerary=object()
        self.assertEqual(qa._resolution_class(a),'C')
    def test_explicit_type_stop_pattern_conflict_is_blocking(self):
        a,b=self.rows();b.type_resolution=NS(validation="conflict")
        self.assertEqual(qa._resolution_class(b),"D")

    def test_tampered_or_incomplete_reports_fail_closed(self):
        changes=[lambda r:r['dayResults'].pop(),
                 lambda r:r.update(sourceFingerprint='wrong'),
                 lambda r:r['dayResults'][0]['resolution']['classes'].update(C=1),
                 lambda r:r['dayResults'][0]['routeCoverage']['9'].update(dataState='insufficient'),
                 lambda r:r['summary']['resolution']['warningCodes'].update(original=0),
                 lambda r:r['dayResults'][0]['diagnosticSeverity']['WARNING'].update(codeOccurrences=3),
                 lambda r:r['summary'].pop('resolution')]
        for change in changes:
            r=self.report();change(r)
            with self.assertRaises(v.V2Error):self.check(r)
