import copy
import unittest
from datetime import date
from scripts import odpt_display_context as display
from scripts import odpt_quality_input as quality
from scripts.odpt_itinerary import _active_services


class DisplayContextTests(unittest.TestCase):
    def setUp(self):
        self.q = quality.initial_context('0'*64)
        self.instants = ['2026-10-29T03:00:00Z', '2026-10-28T15:00:00Z']
        self.c = display.create_context(self.q, self.instants)

    def test_canonical_order_and_references(self):
        c=copy.deepcopy(self.c);c['observationInstants'].reverse();c['displayScenarios'].reverse()
        self.assertEqual(display.normalize_context(c,self.q),self.c)
        self.assertEqual(self.c['requiredServiceDates'][self.instants[0]],['2026-10-28','2026-10-29','2026-10-30'])
        self.assertEqual(self.q['displayEvaluation'],'not-evaluated')

    def test_rejects_tampering_duplicates_and_scope(self):
        for field,value in [('contextFingerprint','a'*64),('qualityContextFingerprint','a'*64),
                            ('timezone','UTC'),('observationInstants',[self.instants[0]]*2),
                            ('displayScenarios',[]),('requiredServiceDates',{})]:
            c=copy.deepcopy(self.c);c[field]=value
            with self.subTest(field=field),self.assertRaises(quality.QualityInputError):display.normalize_context(c,self.q)
        with self.assertRaises(quality.QualityInputError):display.create_context(self.q,['2026-10-30T15:00:00Z'])
        q=copy.deepcopy(self.q);q['serviceDates'].pop()
        with self.assertRaises(quality.QualityInputError):display.normalize_context(self.c,q)

    def test_midnight_and_utc_seconds(self):
        self.assertEqual(display.required_dates('2026-10-29T14:59:59Z'),['2026-10-28','2026-10-29','2026-10-30'])
        self.assertEqual(display.required_dates('2026-10-29T15:00:00Z'),['2026-10-29','2026-10-30','2026-10-31'])
        for invalid in ['2026-02-30T00:00:00Z','2026-10-29T03:00:00.000Z','2026-10-29T12:00:00+09:00',None]:
            with self.subTest(invalid=invalid),self.assertRaises(quality.QualityInputError):display.required_dates(invalid)

    def test_synthetic_weekday_exception_and_substitute_like_day(self):
        days='monday tuesday wednesday thursday friday saturday sunday'.split()
        cal=[dict(service_id=s,start_date='20260101',end_date='20261231',**{d:str(int((i<5)==(s=='0'))) for i,d in enumerate(days)}) for s in ('0','1')]
        exceptions=[dict(service_id=s,date=d,exception_type=t) for d in ('20260106','20260506') for s,t in (('0','2'),('1','1'))]
        for d,expected in [('2026-01-05',{'0'}),('2026-01-06',{'1'}),('2026-05-06',{'1'}),('2026-01-11',{'1'})]:
            self.assertEqual(_active_services(cal,exceptions,date.fromisoformat(d),date(2026,1,1),date(2026,12,31)),expected)

    def test_display_engine_dependency_closure(self):
        engine=quality.build_engine(environment={'synthetic':True})
        names={f['path'] for f in engine['files']}
        self.assertTrue({'scripts/odpt_display_context.py','scripts/odpt_display_contract.mjs',
                         'scripts/odpt_display_runner.mjs','_local_preview/selection.mjs',
                         '_local_preview/preview_odpt_v2_qa.mjs','_local_preview/odpt_v2_qa.html'} <= names)
        self.assertEqual(engine['schemaVersion'],1)
