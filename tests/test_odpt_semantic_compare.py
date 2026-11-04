import copy
import io
import json
import hashlib
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from scripts import odpt_gtfs_semantic_diff as diff
from scripts import odpt_semantic_compare as integrated
from scripts import odpt_source_contract as contract
from scripts import odpt_source_store as store
from tests import test_odpt_gtfs_semantic_diff as fixtures
from tests.test_odpt_gtfs_semantic_diff import dated
from tests.test_odpt_gtfs_loader import archive


class IntegratedSemanticTests(unittest.TestCase):
    def setUp(self): self.helper=fixtures.GTFSSemanticTests();self.helper.setUp()
    def tearDown(self): self.helper.tearDown()
    def compact(self, tables=None, **kwargs):
        self.helper.serial += 1
        path=self.helper.root/f'{self.helper.serial}.zip'
        path.write_bytes(archive(dated() if tables is None else tables, **kwargs))
        from scripts.odpt_source_inventory import _record
        raw=path.read_bytes(); metadata={'status':'parsed','gtfs':{'feedVersion':'fixture','validFrom':'2026-01-01','validThrough':'2026-12-31'},'odpt':None}
        record=_record('metro.gtfs','raw/TokyoMetro-Train-GTFS.zip',raw,metadata,'2026-11-04T00:00:00Z')
        return diff._compact(path,record,all_tables=True)
    def compare(self, mutate=None, **kwargs):
        tables=dated()
        if mutate: mutate(tables)
        return diff.compare_loaded(self.compact(dated()),self.compact(tables,**kwargs),all_tables=True)
    def replace(self, pair, sid, raw):
        s,d=pair; (d/contract.SOURCE_FILES[sid]).write_bytes(raw)
        p=s/'sources'/f'{sid}.json'; r=json.loads(p.read_text()); r['artifact']['sha256']=hashlib.sha256(raw).hexdigest();r['artifact']['sizeBytes']=len(raw);p.write_text(json.dumps(r))
        records=[json.loads(p.read_text()) for p in sorted((s/'sources').iterdir())]
        (s/'snapshot.json').write_text(json.dumps(store.create_snapshot(records,'2026-11-04T00:00:00Z')))
    def run_pair(self, a,b): return integrated.compare_sources(a[0],b[0],a[1],b[1])

    def test_complete_known_scope(self):
        r=self.compare();self.assertEqual(r['coverage'],'complete');self.assertEqual(r['semanticStatus'],'equivalent')
        self.assertEqual(len(r['tableResults']),11);self.assertFalse(r['notEvaluated'])
        self.assertTrue(all('checks' in t and 'findings' in t and 'categories' in t for t in r['tableResults']))

    def test_auxiliary_attributes(self):
        for name,field,value in [('agency','agency_name','New'),('feed_info','feed_version','v2'),('feed_info','feed_end_date','20260108'),('fare_attributes','price','101'),('translations','translation','New')]:
            with self.subTest(name=name,field=field):
                r=self.compare(lambda t:t[name][0].update({field:value}))
                tab=next(t for t in r['tableResults'] if t['table']==name)
                self.assertEqual(tab['counts']['modified'],1);self.assertGreater(r['counts']['changes'],0)

    def test_selector_missing_empty_unknown_and_multiset(self):
        r=self.compare(lambda t:t['fare_rules'][0].update(contains_id=''))
        tab=next(t for t in r['tableResults'] if t['table']=='fare_rules')
        self.assertEqual((tab['counts']['added'],tab['counts']['removed']),(1,1))
        r=self.compare(lambda t:t['fare_rules'].append(copy.deepcopy(t['fare_rules'][0])))
        self.assertEqual(r['coverage'],'partial'); self.assertGreater(r['counts']['ambiguous'],0)
        t=dated();t['fare_rules']*=2
        a=self.compact(t); b=self.compact(t,reverse=True)
        r=diff.compare_loaded(a,b,all_tables=True);self.assertEqual(r['counts']['changes'],0);self.assertEqual(r['semanticStatus'],'indeterminate')
        r=self.compare(lambda t:t['fare_rules'][0].update(extra='value'))
        self.assertIn('unsupported-field-change',r['categories']);self.assertTrue(r['unsupportedFields'])

    def test_translation_ambiguity_and_priority(self):
        # Build directly through the explicit audit loader: legacy default still rejects duplicates.
        t=dated();t['translations'].append({**t['translations'][0],'translation':'Other'})
        raw=archive(t)
        with self.assertRaises(diff.loader.GTFSError): diff.loader.parse_gtfs(raw)
        parsed=diff.loader.parse_gtfs(raw,preserve_selector_duplicates=True)
        self.assertEqual(parsed['tables']['translations']['recordCount'],2)
        # Avoid legacy compact writer validation when testing ambiguous groups.
        a=self.compact(t)
        r=diff.compare_loaded(a,a,all_tables=True)
        self.assertEqual(r['coverage'],'partial');self.assertEqual(r['counts']['changes'],0)
        self.assertTrue(r['ambiguities'])
        t=dated();other=copy.deepcopy(t['translations'][0]);other.update(record_id='',field_value='Station');t['translations'].append(other)
        r=diff.compare_loaded(self.compact(t),self.compact(t),all_tables=True)
        self.assertIn('translation_precedence_not_evaluated',r['errorCodes'])

    def test_add_delete_reverse_determinism_and_limit(self):
        for name in ('fare_rules','translations'):
            r=self.compare(lambda t:t[name].clear());tab=next(t for t in r['tableResults'] if t['table']==name)
            self.assertEqual(tab['counts']['removed'],1)
        a=self.compact(dated());t=dated();t['translations'][0]['translation']='New';b=self.compact(t)
        r=diff.compare_loaded(a,b,all_tables=True);rr=diff.compare_loaded(b,a,all_tables=True)
        self.assertEqual(r['counts']['modified'],rr['counts']['modified'])
        first=diff.compare_loaded(a,b,all_tables=True);second=diff.compare_loaded(a,b,all_tables=True)
        first.pop('timings');second.pop('timings');self.assertEqual(first,second)
        with patch.object(diff,'MAX_DETAILS',0):
            r=diff.compare_loaded(a,b,all_tables=True);self.assertTrue(r['truncated']);self.assertEqual(r['semanticStatus'],'indeterminate')

    def test_seven_sources_changes_failures_and_cli(self):
        a=self.helper.make_store();b=self.helper.make_store()
        r=self.run_pair(a,b);self.assertEqual(len(r['sourceResults']),7);self.assertEqual(r['semanticStatus'],'equivalent')
        out=io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(integrated.main(['--baseline-store',str(a[0]),'--candidate-store',str(b[0]),'--baseline-source-dir',str(a[1]),'--candidate-source-dir',str(b[1])]),0)
        self.assertEqual(sum(line.startswith('table=') for line in out.getvalue().splitlines()),11)
        self.assertIn('checks=',out.getvalue())
        railway={'@context':'http://vocab.odpt.org/context_odpt_Railway.jsonld','@type':'odpt:Railway','owl:sameAs':'urn:rail:fixture','@id':'urn:id:fixture','dc:title':'Synthetic','odpt:stationOrder':[]}
        self.replace(b,'metro.railway',json.dumps([railway]).encode());r=self.run_pair(a,b)
        self.assertEqual(r['semanticStatus'],'changed');self.assertEqual(r['confirmedChanges']['metro.railway']['added'],1)
        t=dated();t['feed_info'][0]['feed_version']='new';self.replace(b,'metro.gtfs',archive(t))
        r=self.run_pair(a,b);self.assertGreater(r['confirmedChanges']['metro.gtfs']['changes'],0)
        self.replace(b,'metro.gtfs',b'broken');r=self.run_pair(a,b)
        self.assertEqual(r['comparisonStatus'],'failed');self.assertEqual(r['confirmedChanges']['metro.railway']['added'],1)
        self.replace(b,'metro.gtfs',archive(t));self.replace(b,'metro.station',b'[')
        r=self.run_pair(a,b);self.assertEqual(r['comparisonStatus'],'failed');self.assertGreater(r['confirmedChanges']['metro.gtfs']['changes'],0)
        out=io.StringIO()
        with redirect_stdout(out): code=integrated.main(['--baseline-store',str(a[0]),'--candidate-store',str(b[0]),'--baseline-source-dir',str(a[1]),'--candidate-source-dir',str(b[1])])
        self.assertEqual(code,2);self.assertNotIn('Synthetic',out.getvalue())

    def test_partial_propagation_and_bytes_mismatch(self):
        a=self.helper.make_store();b=self.helper.make_store();t=dated();t['trips'][0]['block_id']='group';self.replace(b,'metro.gtfs',archive(t))
        r=self.run_pair(a,b);self.assertEqual(r['semanticStatus'],'indeterminate');self.assertEqual(r['comparisonStatus'],'partial')
        (b[1]/contract.SOURCE_FILES['metro.gtfs']).write_bytes(b'bad')
        with self.assertRaises(diff.loader.GTFSError): self.run_pair(a,b)
