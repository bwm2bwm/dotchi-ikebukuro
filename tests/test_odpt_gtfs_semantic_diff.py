import copy
import hashlib
import io
import json
import os
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from scripts import odpt_gtfs_semantic_diff as diff
from scripts import odpt_source_contract as contract
from scripts import odpt_source_inventory as inventory
from scripts import odpt_source_store as store
from tests.test_odpt_gtfs_loader import fixture, archive


def dated():
    t = fixture(); t['translations'][0].update(field_value='', record_id='s'); t['feed_info'][0].update(feed_start_date='20260101', feed_end_date='20260107')
    return t


class GTFSSemanticTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir='/private/tmp'); self.root = Path(self.temp.name); self.serial = 0
    def tearDown(self): self.temp.cleanup()

    def compact(self, tables=None, **kwargs):
        self.serial += 1; raw = archive(dated() if tables is None else tables, **kwargs)
        path = self.root / f'{self.serial}.zip'; path.write_bytes(raw)
        metadata = {'status':'parsed','gtfs':{'feedVersion':'fixture','validFrom':'2026-01-01','validThrough':'2026-12-31'},'odpt':None}
        record = inventory._record('metro.gtfs','raw/TokyoMetro-Train-GTFS.zip', raw, metadata,'2026-11-04T00:00:00Z')
        return diff._compact(path, record)

    def compare(self, mutate=None, **kwargs):
        tables = dated()
        if mutate: mutate(tables)
        return diff.compare_loaded(self.compact(), self.compact(tables, **kwargs))

    def test_identical_and_scope(self):
        r = self.compare(); self.assertEqual(r['semanticStatus'],'indeterminate'); self.assertEqual(r['coverage'],'partial')
        self.assertTrue(all(t['semanticStatus']=='equivalent' for t in r['tableResults'][:6]))
        self.assertEqual(len(r['notEvaluated']),5); self.assertEqual(r['findings'],[])

    def test_container_csv_and_row_representation(self):
        r = self.compare(compression=zipfile.ZIP_STORED)
        self.assertIn('zip-container-only',[v['kind'] for v in r['representations']])
        for kwargs, expected in [({'bom':True}, 'csv-format-only'), ({'newline':'\r\n'},'csv-format-only'), ({'reverse':True},'csv-format-and-record-order')]:
            r=self.compare(**kwargs); self.assertEqual(r['counts']['fieldChanges'] if 'fieldChanges' in r['counts'] else 0,0)
            self.assertTrue(r['representations'])
        tables=dated(); text='trip_id,stop_id,stop_sequence,arrival_time,departure_time\nt,s,2,00:10:00,\nt,s,10,24:10:00,\n'
        r=diff.compare_loaded(self.compact(),self.compact(tables,replacements={'stop_times':text.encode()}))
        self.assertIn('csv-record-order-only',[v['kind'] for v in r['representations']])

    def test_each_table_properties_and_calendar(self):
        cases=[('routes','route_short_name','Changed','operational-attribute-changed'),
               ('stops','stop_name','Changed','operational-attribute-changed'),
               ('trips','trip_headsign','New','operational-attribute-changed'),
               ('stop_times','arrival_time','24:11:00','time-changed'),
               ('calendar','monday','0','calendar-record-changed'),
               ('calendar_dates','exception_type','1','calendar-record-changed')]
        for table,field,value,kind in cases:
            with self.subTest(table=table):
                r=self.compare(lambda t:t[table][0].update({field:value}))
                self.assertIn(kind,r['categories'])
                if kind=='time-changed': self.assertEqual(next(f['deltaSeconds'] for f in r['findings'] if f['kind']==kind),60)
        r=self.compare(lambda t:t['stop_times'][0].update(arrival_time='00:10:00'))
        self.assertEqual(next(f['deltaSeconds'] for f in r['findings'] if f['kind']=='time-changed'),-86400)
        r=self.compare(lambda t:t['stop_times'][0].update(departure_time='24:10:00'))
        f=next(f for f in r['findings'] if f.get('fieldPath')=='/departure_time'); self.assertEqual(f['baselineState'],'empty')

    def test_add_remove_reverse_and_stop_order(self):
        for name in diff.TABLES:
            # Test comparison layer directly after validated inputs; removal can violate cross refs.
            a=self.compact(); b=copy.deepcopy(a)
            key=next(iter(b['tables'][name]['rows'])); del b['tables'][name]['rows'][key]
            forward=diff.compare_loaded(a,b); reverse=diff.compare_loaded(b,a)
            self.assertEqual(forward['tableResults'][diff.TABLES.index(name)]['counts']['removed'],1)
            self.assertEqual(reverse['tableResults'][diff.TABLES.index(name)]['counts']['added'],1)
        r=self.compare(lambda t:t['stop_times'][0].update(stop_sequence='20'))
        self.assertIn('stop-order-changed',r['categories'])
        r=self.compare(lambda t:t['calendar_dates'].append({'service_id':'c','date':'20260104','exception_type':'2'}))
        self.assertEqual(r['calendarEvaluation']['changedServiceDates'],1)

    def test_feed_common_range_and_limits(self):
        r=self.compare(lambda t:t['feed_info'][0].update(feed_start_date='20260104',feed_end_date='20260110'))
        self.assertEqual(r['calendarEvaluation']['commonPeriod'],['2026-01-04','2026-01-07'])
        self.assertEqual(r['calendarEvaluation']['changedServiceDates'],0)
        self.assertEqual(r['calendarEvaluation']['evaluatedServiceDates'],4)
        r=self.compare(lambda t:t['feed_info'][0].update(feed_start_date='20260201',feed_end_date='20260202'))
        self.assertEqual(r['calendarEvaluation']['status'],'no-common-period')
        with patch.object(diff,'MAX_CALENDAR_DAYS',1):
            r=self.compare(); self.assertIn('calendar_evaluation_limit',r['errorCodes'])
        with patch.object(diff,'MAX_SERVICE_DATES',1):
            self.assertEqual(self.compare()['calendarEvaluation']['status'],'partial')
        with patch.object(diff,'MAX_DETAILS',1):
            r=self.compare(lambda t:t['calendar'][0].update(monday='0',tuesday='0',wednesday='0'))
            self.assertTrue(r['truncated']); self.assertGreater(r['omittedDetails'],0)
        r=diff.compare_loaded(self.compact(fixture()),self.compact(fixture()))
        self.assertIn('feed_period_unavailable',r['errorCodes'])

    def test_ids_unknown_fields_and_determinism(self):
        a=self.compact(); b=copy.deepcopy(a)
        row=b['tables']['trips']['rows'].pop(('t',)); row['trip_id']='new'; b['tables']['trips']['rows'][('new',)]=row
        r=diff.compare_loaded(a,b); self.assertIn('possible-identifier-change',r['categories'])
        self.assertIn('record-added',r['categories']); self.assertIn('record-removed',r['categories'])
        row=copy.deepcopy(row); row['trip_id']='other'; b['tables']['trips']['rows'][('other',)]=row
        self.assertIn('ambiguous-change',diff.compare_loaded(a,b)['categories'])
        r=self.compare(lambda t:t['trips'][0].update(unknown='raw'))
        self.assertIn('unsupported-field-change',r['categories'])
        self.assertEqual(r['tableResults'][2]['coverage'],'partial')
        first=diff.compare_loaded(a,b); second=diff.compare_loaded(a,b)
        first.pop('timings'); second.pop('timings'); self.assertEqual(first,second)

    def test_service_and_reference_chain_identifier_changes(self):
        def rename(t):
            t['calendar'][0]['service_id']='new-service'
            t['calendar_dates'][0]['service_id']='new-service'
            t['trips'][0]['service_id']='new-service'
        r=self.compare(rename)
        self.assertTrue(any(f['kind']=='possible-identifier-change' and f['table']=='service-identity' for f in r['ambiguities']))
        self.assertGreater(r['calendarEvaluation']['changedServiceDates'],0)
        def chain(t):
            rename(t); t['trips'][0]['trip_id']='new-trip'
            for row in t['stop_times']: row['trip_id']='new-trip'
        r=self.compare(chain)
        self.assertTrue(any(f['kind']=='ambiguous-change' and f['table']=='trips' for f in r['ambiguities']))
        self.assertFalse(any(f['kind']=='possible-identifier-change' and f['table']=='trips' for f in r['ambiguities']))

    def test_validated_additions_stop_references_and_unknown_values(self):
        for name in ('routes','stops','trips'):
            def add(t):
                row=copy.deepcopy(t[name][0]); row[diff.loader.SCHEMAS[name][2]]='extra'; t[name].append(row)
            r=self.compare(add)
            self.assertEqual(next(v for v in r['tableResults'] if v['table']==name)['counts']['added'],1)
        def parent(t):
            t['stops'].append({'stop_id':'parent','stop_name':'Parent','zone_id':''})
            for row in t['stops']: row['parent_station']='parent' if row['stop_id']=='s' else ''
        r=self.compare(parent); self.assertIn('reference-changed',r['categories'])
        r=self.compare(lambda t:t['trips'][0].update(direction_id='9'))
        self.assertIn('unsupported-field-change',r['categories'])
        r=self.compare(lambda t:t['calendar_dates'].clear())
        self.assertEqual(r['calendarEvaluation']['changedServiceDates'],1)

    def make_store(self):
        self.serial+=1; directory=self.root/f'raw-{self.serial}'; destination=self.root/f'store-{self.serial}'
        directory.mkdir(mode=0o700); destination.mkdir(mode=0o700); (destination/'sources').mkdir(mode=0o700); records=[]
        for sid,filename in contract.SOURCE_FILES.items():
            raw=archive(dated()) if sid=='metro.gtfs' else b'[]'; (directory/filename).write_bytes(raw)
            metadata={'status':'parsed','gtfs':{'feedVersion':'fixture','validFrom':'2026-01-01','validThrough':'2026-01-07'},'odpt':None} if sid=='metro.gtfs' else {'status':'parsed','gtfs':None,'odpt':{'recordCount':0,'dcDates':[],'issuedDates':[],'dcDateMissingCount':0,'issuedMissingCount':0}}
            record=inventory._record(sid,f'raw/{filename}',raw,metadata,'2026-11-04T00:00:00Z'); records.append(record)
            path=destination/'sources'/f'{sid}.json'; path.write_text(json.dumps(record)); path.chmod(0o600)
        path=destination/'snapshot.json';path.write_text(json.dumps(store.create_snapshot(records,'2026-11-04T00:00:00Z')));path.chmod(0o600)
        return destination,directory

    def test_integrated_inputs_cli_and_immutability(self):
        s,a=self.make_store(); t,b=self.make_store()
        def signature(): return {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in self.root.rglob('*') if p.is_file()}
        before=signature(); r=diff.compare_gtfs(s,t,a,b)
        self.assertEqual(len(r['sourceResults']),7);self.assertEqual(r['semanticStatus'],'indeterminate')
        self.assertEqual(signature(),before)
        out=io.StringIO()
        with redirect_stdout(out): self.assertEqual(diff.main(['--baseline-store',str(s),'--candidate-store',str(t),'--baseline-source-dir',str(a),'--candidate-source-dir',str(b)]),0)
        self.assertNotIn('Station,',out.getvalue()); self.assertIn('coverage=not-evaluated',out.getvalue())
        (b/contract.SOURCE_FILES['metro.gtfs']).write_bytes(b'bad')
        with self.assertRaises(diff.loader.GTFSError): diff.compare_gtfs(s,t,a,b)
        (a/contract.SOURCE_FILES['metro.station']).unlink()
        with self.assertRaises(diff.loader.GTFSError): diff.compare_gtfs(s,t,a,b)
