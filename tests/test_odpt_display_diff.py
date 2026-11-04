"""Synthetic models/source fixtures only. No private saved inputs or network."""
import copy
from datetime import date
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout
from scripts import odpt_display_diff as diff
from tests.test_odpt_snapshot_qa import make_snapshot
from tests.test_odpt_public_v2 import FakeGenerator

m,q=diff.collector,diff.quality
K=('2026-10-29T03:00:00Z','Hikawadai','departure-all')


def item(n=0, destination='合成', arrival=None, route='6'):
    return dict(departureAtMs=1793243100000+n*60000,arrivalAtMs=1793243700000+n*60000 if arrival is None else arrival,
        routeId=route,serviceDate='2026-10-29',journeyKind='direct',kind='各駅停車',destination=destination,transfer=None)


def evidence(items=None,mode='departure',best=0):
    items=copy.deepcopy([item()] if items is None else items)
    groups=([{'groupId':'departure','items':items[:6]}] if items else []) if mode=='departure' else [
        {'groupId':r,'items':[i for i in items if i['routeId']==r][:3]} for r in ('6','9') if any(i['routeId']==r for i in items)]
    selected=items[best] if items else None
    # Local ordinal chooses a specific occurrence; semantic duplicates remain ambiguous.
    selected_index=best if items else None
    markers=[]
    for g in groups:
        indices=list(range(min(6,len(items)))) if mode=='departure' else [idx for idx,i in enumerate(items) if i['routeId']==g['groupId']][:3]
        for pos,actual in enumerate(indices):
            if selected_index==actual:markers.append({'groupId':g['groupId'],'position':pos,'content':items[actual],'label':'● 最早着'})
    visible=bool(markers)
    return dict(availability='known',reasonCodes=[],items=items,groups=groups,markers=markers,
        values=dict(itemsCount=len(items),groupsCardCount=sum(len(g['items']) for g in groups),
            directCount=sum(i['journeyKind']=='direct' for i in items),transferCount=sum(i['journeyKind']=='transfer' for i in items),
            visibleBestMarkerCount=len(markers),routeCardCounts={r:sum(i['routeId']==r for g in groups for i in g['items']) for r in ('6','9')},
            serviceDateItemsCounts={'2026-10-29':len(items)},best=selected,bestInGroups=visible))


class BasicDisplayDiffTests(unittest.TestCase):
    def compare(self,a=None,b=None,**kwargs):return diff.compare_cells({K:a if a is not None else evidence()},{K:b if b is not None else evidence()},[K],**kwargs)

    def test_self_comparison_and_zero(self):
        for e in (evidence(),evidence([])):
            r=self.compare(e,e)
            self.assertEqual(r['summary']['unchangedCellCount'],1);self.assertFalse(r['cellDiffs']);self.assertFalse(r['findings'])
            self.assertEqual(r['summary']['unchangedDetailsAggregatedCount'],1)
            self.assertTrue(all(t['delta']==0 for t in r['summary']['metricDiffTotals'].values()))

    def test_count_content_and_order_are_distinct(self):
        a=evidence([item(0),item(1)])
        for b,required,absent in [(evidence([item(0),item(1),item(2)]),'items-increased','item-order-changed'),
                                  (evidence([item(0)]),'items-decreased','item-order-changed'),
                                  (evidence([item(0,destination='別行先'),item(1)]),'item-content-changed','item-order-changed'),
                                  (evidence([item(1),item(0)],best=1),'item-order-changed','item-content-changed')]:
            r=self.compare(a,b);c=r['cellDiffs'][0]
            self.assertIn(required,c['classifications']);self.assertNotIn(absent,c['classifications']);self.assertTrue(c['changed'])
        self.assertIn('card-order-changed',self.compare(a,evidence([item(1),item(0)],best=1))['cellDiffs'][0]['classifications'])

    def test_duplicate_multiset_and_best_ambiguity(self):
        a=evidence([item(),item()]);b=evidence([item(),item(),item()])
        r=self.compare(a,b);c=r['cellDiffs'][0]
        self.assertEqual(c['items']['addedCount'],1);self.assertEqual(c['items']['baselineCount'],2)
        self.assertIn('ambiguous',c['classifications']);self.assertEqual(c['best']['identityAvailability'],'ambiguous')
        self.assertFalse(c['items']['positionChanges'])
        same=self.compare(a,a);self.assertEqual(same['summary']['confirmedFindingCount'],0)
        self.assertEqual(same['summary']['ambiguousCellCount'],1)

    def test_partial_missing_known_zero_and_confirmed_other_cell(self):
        a={K:evidence([])};b={K:{'availability':'unavailable','values':None,'reasonCodes':['unavailable']}}
        other=(K[0],'Wakoshi',K[2]);a[other]=evidence();b[other]=evidence([item(1)])
        missing=(K[0],'Senkawa',K[2])
        r=diff.compare_cells(a,b,[K,other,missing]);self.assertEqual(r['summary']['notEvaluableCellCount'],2)
        self.assertEqual(r['summary']['changedCellCount'],1)
        c=next(c for c in r['cellDiffs'] if c['dimensions']['stationId']=='Hikawadai')
        first=c['metricDiffs'][0];self.assertEqual(first['baselineValue'],0);self.assertIsNone(first['candidateValue']);self.assertIsNone(first['delta'])

    def test_line_groups_and_cards_independent_of_item_multiset(self):
        a=evidence([item(0),item(1),item(2),item(3)],mode='line')
        b=evidence([item(3),item(0),item(1),item(2)],mode='line',best=1)
        c=self.compare(a,b)['cellDiffs'][0]
        self.assertFalse(c['items']['contentChanged']);self.assertTrue(c['groups']['contentChanged'])
        self.assertIn('card-content-changed',c['classifications'])
        b=evidence([item(route='9')],mode='line')
        self.assertNotEqual(self.compare(a,b)['cellDiffs'][0]['groupPresence']['baselineValue'],self.compare(a,b)['cellDiffs'][0]['groupPresence']['candidateValue'])

    def test_best_content_visibility_marker_label_and_no_best(self):
        a=evidence([item(n) for n in range(8)])
        b=evidence([item(n) for n in range(8)],best=7)
        c=self.compare(a,b)['cellDiffs'][0]
        self.assertIn('best-changed',c['classifications']);self.assertIn('best-not-visible',c['classifications'])
        self.assertIn('best-marker-changed',c['classifications']);self.assertFalse(c['metricDiffs'][-1]['candidateValue'])
        hidden=self.compare(b,b);self.assertEqual(hidden['summary']['candidateBestNotVisibleCellCount'],1);self.assertFalse(hidden['findings'])
        b=copy.deepcopy(a);b['markers'][0]['label']='● 表示候補内の最早着'
        self.assertIn('best-marker-changed',self.compare(a,b)['cellDiffs'][0]['classifications'])
        self.assertIn('best-changed',self.compare(a,evidence([]))['cellDiffs'][0]['classifications'])

    def test_limits_unchanged_and_digest_order(self):
        keys=[('2026-10-29T03:00:00Z',f's{i:04}',K[2]) for i in range(1024)]
        a={k:evidence() for k in keys};b={k:evidence([item(1)]) for k in reversed(keys)}
        r=diff.compare_cells(a,b,reversed(keys));self.assertEqual(r['summary']['changedCellCount'],1024)
        self.assertEqual(len(r['cellDiffs']),1000);self.assertEqual(r['omittedDetails']['cellDiffs'],24)
        self.assertEqual(r,diff.compare_cells(a,b,keys))
        same=diff.compare_cells(a,a,keys);self.assertEqual(same['summary']['unchangedDetailsAggregatedCount'],1024)
        self.assertFalse(same['cellDiffs']);self.assertFalse(same['omittedDetails'])
        self.assertEqual(diff.exit_code({'inputReadiness':'ready',**same}),0)
        result={'summary':same['summary'],'timings':{'total':1},'resources':{'rss':1}}
        digest=diff.comparison_digest(result);result['timings']['total']=99;result['resources']['rss']=99
        self.assertEqual(digest,diff.comparison_digest(result))


    def test_changed_is_not_an_exit_error_and_caps_are(self):
        changed=self.compare(b=evidence([item(1)]))
        result={'inputReadiness':'ready',**changed}
        self.assertEqual(diff.exit_code(result),0)
        limited=self.compare(b=evidence([item(1)]),detail_limit=0)
        self.assertEqual(limited['summary']['changedCellCount'],1)
        self.assertEqual(diff.exit_code({'inputReadiness':'ready',**limited}),2)
        ambiguous=self.compare(evidence([item(),item()]),evidence([item(),item()]))
        self.assertEqual(diff.exit_code({'inputReadiness':'ready',**ambiguous}),2)


def recompute_cell(cell):
    board=cell['model'];items=board['items']
    if cell['dimensions']['scenarioId'].startswith('line-'):
        board['groups']=[{'routeId':r,'line':next(i['line'] for i in items if i['routeId']==r),'items':[i for i in items if i['routeId']==r][:3]} for r in ('6','9') if any(i['routeId']==r for i in items)]
    else:board['groups']=[{'line':None,'items':items[:6]}] if items else []
    visible=[i for g in board['groups'] for i in g['items']]
    response=dict(itemContentKeys=[m._js_digest({k:v for k,v in i.items() if k not in ('id','sourceId')}) for i in items],
        bestInGroups=any(i['id']==board['bestId'] for i in visible),displayedBestMarkCount=sum(i['isBest'] for i in visible),
        terminalKnownByRouteDate={k:v['terminalKnown'] for k,v in board['routeStates'].items()},
        unknownRouteStateCount=sum(s['state'] in {'unknown','data_insufficient','start_unconfirmed','terminal_unconfirmed'} for s in board['routeStates'].values()))
    cell['metrics']=m._cell_metrics(board,response);cell['boardDigest']=m._js_digest(board)


def reseal_report(report):
    cells=report['cells'];known=[c for c in cells if c['availability']=='known'];a=report['aggregateMetrics']
    a['evaluatedCellCount']=len(known)
    a['availabilityCounts']=dict(m.Counter(c['availability'] for c in cells))
    for field in ('itemsCount','groupsCardCount','directCount','transferCount','displayedBestMarkCount'):
        a[field]=sum(c['metrics'][field] for c in known) if known else None
    for total,field in [('bestExistsCount','bestExists'),('bestInGroupsCount','bestInGroups'),('zeroCandidateCellCount','zeroCandidates')]:
        a[total]=sum(c['metrics'][field] for c in known) if known else None
    a['bestOutsideGroupsCount']=sum(c['metrics']['bestExists'] and not c['metrics']['bestInGroups'] for c in known) if known else None
    a['bestConsistencyPassCount']=len(known) if known else None
    report['collectionDigest']=q.digest({k:v for k,v in report.items() if k!='collectionDigest'})


class DisplayDiffIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.root=Path(cls.temp.name).resolve()
        cls.source=make_snapshot(cls.root/'template-source');cls.store=cls.root/'template-store'
        from scripts import odpt_source_store
        cls.store_api=odpt_source_store;odpt_source_store.persist_snapshot(cls.store,cls.source)
        cls.engine=q.build_engine();cls.context=q.initial_context(cls.engine['engineFingerprint'])
        cls.display=diff.display.create_context(cls.context,['2026-10-28T15:00:00Z'])
        with patch.object(m,'ItineraryGenerator',FakeGenerator):
            cls.template=m.collect_display_models(cls.store,cls.source,engine=cls.engine,quality_context=cls.context,display_context=cls.display)
        assert cls.template['aggregateMetrics']['evaluatedCellCount']==32,cls.template['reasonCodes']

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.work=Path(self.tmp.name).resolve()
        self.a_source=make_snapshot(self.work/'a-source');self.b_source=make_snapshot(self.work/'b-source')
        self.a=self.work/'a';self.b=self.work/'b'
        self.store_api.persist_snapshot(self.a,self.a_source);self.store_api.persist_snapshot(self.b,self.b_source)

    def bound_report(self,store):
        r=copy.deepcopy(self.template);snap=q.load_store_contract(store)['snapshot']
        r['snapshotId']=snap['snapshotId'];r['contentFingerprint']=snap['contentFingerprint']
        for c in r['cells']:c['dimensions']['snapshotId']=snap['snapshotId']
        for field in ('inputStart','inputEnd'):
            for side in diff.SIDES:
                r['checks'][field][side+'SnapshotId']=snap['snapshotId'];r['checks'][field][side+'ContentFingerprint']=snap['contentFingerprint']
        reseal_report(r);return r

    def compare(self,mutate=None,**kwargs):
        calls=[]
        def collect(store,source,**options):
            calls.append((store,options));r=self.bound_report(store)
            if mutate:mutate(r,len(calls))
            return r
        with patch.object(m,'collect_display_models',side_effect=collect):
            result=diff.compare_display_models(self.a,self.b,self.a_source,self.b_source,
                quality_context=self.context,display_context=self.display,engine=self.engine,**kwargs)
        return result,calls

    def test_sequential_self_comparison_and_independent_summaries(self):
        before=[m.itinerary_metrics._inventory(*p) for p in ((self.a,self.a_source),(self.b,self.b_source))]
        r,calls=self.compare();self.assertEqual([p[0] for p in calls],[self.a,self.b])
        self.assertTrue(all(p[1]['detail_limit']==m.MAX_DETAIL_LIMIT for p in calls))
        self.assertEqual(r['summary']['unchangedCellCount'],32);self.assertEqual(r['summary']['confirmedFindingCount'],0)
        self.assertEqual(r['comparisonStatus'],'partial');self.assertEqual(r['displayDiffStatus'],'indeterminate')
        self.assertEqual(r['basicDisplayDiffStatus'],'unchanged');self.assertEqual(diff.exit_code(r),0)
        self.assertFalse(r['cellDiffs']);self.assertFalse(r['findings'])
        self.assertEqual(before,[m.itinerary_metrics._inventory(*p) for p in ((self.a,self.a_source),(self.b,self.b_source))])
        again,_=self.compare();self.assertEqual(r['comparisonDigest'],again['comparisonDigest'])

    def test_ids_only_and_deferred_terminal_state_fields_do_not_change_basic_diff(self):
        def mutate(r,n):
            if n==2:
                for c in r['cells']:
                    board=c['model'];mapping={i['id']:'local-'+str(j) for j,i in enumerate(board['items'])}
                    for i in board['items']:i['id']=i['sourceId']=mapping[i['id']]
                    # Groups reference the same objects in the copied collector report.
                    board['bestId']=mapping.get(board['bestId']);board['serviceState']='unknown'
                    for i in board['items']:i['isLastDeparture']=False
                    recompute_cell(c)
                reseal_report(r)
        r,_=self.compare(mutate);self.assertEqual(r['summary']['changedCellCount'],0)
        self.assertEqual(diff.exit_code(r),0)

    def test_known_difference_survives_a_local_unavailable_cell(self):
        def mutate(r,n):
            if n==2:
                c=r['cells'][0];c['model']['items'][0]['destination']='合成差分';recompute_cell(c)
                c=r['cells'][1];c.update(availability='unavailable',reasonCodes=['node_timeout'],metrics=None);c.pop('model')
                reseal_report(r)
        r,_=self.compare(mutate)
        self.assertEqual(r['displayDiffStatus'],'changed');self.assertEqual(r['summary']['changedCellCount'],1)
        self.assertEqual(r['summary']['notEvaluableCellCount'],1);self.assertEqual(diff.exit_code(r),2)

    def test_context_runtime_engine_and_snapshot_rejection(self):
        d=diff.display.create_context(self.context,['2026-10-29T03:00:00Z'])
        r,calls=self.compare(candidate_display_context=d);self.assertEqual(r['comparisonStatus'],'incomparable');self.assertFalse(calls)
        bad=copy.deepcopy(self.engine);bad['environment']['node']['versions']['icu']='other'
        bad['engineFingerprint']=q.digest({k:v for k,v in bad.items() if k!='engineFingerprint'})
        r,calls=self.compare(candidate_engine=bad);self.assertEqual(r['comparisonStatus'],'incomparable');self.assertFalse(calls)
        p=self.b_source/'Station_all.json';p.write_bytes(p.read_bytes()+b' ')
        r,calls=self.compare();self.assertEqual(r['inputReadiness'],'invalid');self.assertFalse(calls);self.assertEqual(diff.exit_code(r),3)

    def test_report_payload_schema_and_mid_comparison_source_change(self):
        def corrupt(r,n):
            if n==2:r['cells'][0]['model']['items'][0]['arrivalAtMs']='invalid';reseal_report(r)
        r,_=self.compare(corrupt);self.assertEqual(r['inputReadiness'],'invalid');self.assertIsNone(r['summary'])
        def mutate(r,n):
            if n==1:
                p=self.a_source/'Station_all.json';p.write_bytes(p.read_bytes()+b' ')
        r,_=self.compare(mutate);self.assertEqual(r['inputReadiness'],'invalid');self.assertIsNone(r['summary'])
        self.assertEqual(r['checks']['baselineInputImmutability']['status'],'FAIL')

    def test_cli_and_fixed_exit_codes_no_body(self):
        r,_=self.compare();out=io.StringIO()
        with patch.object(diff,'compare_display_models',return_value=r),redirect_stdout(out):
            code=diff.main(['--baseline-store',str(self.a),'--candidate-store',str(self.b),
                           '--baseline-source-dir',str(self.a_source),'--candidate-source-dir',str(self.b_source)])
        self.assertEqual(code,0);self.assertNotIn('行先',out.getvalue());self.assertNotIn('p2-',out.getvalue())
        for ready,code in [('invalid',3),('unavailable',4),('incomparable',2)]:
            x=copy.deepcopy(r);x['inputReadiness']=ready;self.assertEqual(diff.exit_code(x),code)

    def test_missing_collector_cell_is_not_zero_and_runtime_response_is_global(self):
        def missing(r,n):
            if n==2:
                r['cells'].pop();r['omittedDetails']['cells']=1
                r['collectionDigest']=q.digest({k:v for k,v in r.items() if k!='collectionDigest'})
        r,_=self.compare(missing)
        self.assertEqual(r['summary']['notEvaluableCellCount'],1);self.assertEqual(r['summary']['comparedCellCount'],31)
        self.assertEqual(diff.exit_code(r),2)
        for code,readiness in [('node_runner_node_runtime_mismatch','incomparable'),('node_response_json_invalid','invalid')]:
            def failure(r,n):
                if n==2:
                    r['cells'][0].update(availability='unavailable',metrics=None,reasonCodes=[code]);reseal_report(r)
            r,_=self.compare(failure);self.assertEqual(r['inputReadiness'],readiness);self.assertIsNone(r['summary'])

    def test_engine_change_during_comparison_invalidates_results(self):
        changed=False;original=q.build_engine
        def current(*a,**kw):
            e=original(*a,**kw)
            if changed:
                e['files'][-1]['sha256']='1'*64;e['engineFingerprint']=q.digest({k:v for k,v in e.items() if k!='engineFingerprint'})
            return e
        def mutate(r,n):
            nonlocal changed
            changed=True
        with patch.object(q,'build_engine',side_effect=current):r,_=self.compare(mutate)
        self.assertEqual(r['comparisonStatus'],'incomparable');self.assertIsNone(r['summary']);self.assertFalse(r['cellDiffs'])

    def test_synthetic_different_snapshot_through_existing_builder_and_node(self):
        import csv
        import zipfile
        # Modify only a generated synthetic fixture, then bind its new Snapshot.
        path=self.b_source/'TokyoMetro-Train-GTFS.zip'
        with zipfile.ZipFile(path) as z:tables={name:z.read(name) for name in z.namelist()}
        rows=list(csv.DictReader(io.StringIO(tables['stop_times.txt'].decode('utf-8-sig'))))
        first=rows[0];first['departure_time']='23:01:00'
        text=io.StringIO();writer=csv.DictWriter(text,fieldnames=rows[0].keys());writer.writeheader();writer.writerows(rows)
        tables['stop_times.txt']=text.getvalue().encode()
        with zipfile.ZipFile(path,'w') as z:
            for name,raw in tables.items():z.writestr(name,raw)
        other_store=self.work/'b-updated';self.store_api.persist_snapshot(other_store,self.b_source)
        class SourceGenerator(FakeGenerator):
            def __init__(self,*a,**kw):
                super().__init__(*a,**kw)
                source=kw['gtfs_zip']
                with zipfile.ZipFile(source) as z:r=next(csv.DictReader(io.StringIO(z.read('stop_times.txt').decode('utf-8-sig'))))
                h,mi,se=map(int,r['departure_time'].split(':'));self.shift=h*3600+mi*60+se-23*3600
            def generate(self,day):
                result=super().generate(day)
                for row in result:
                    row.departure_seconds+=self.shift
                    row.primary_itinerary.departure_seconds+=self.shift;row.primary_itinerary.arrival_seconds+=self.shift
                return result
        with patch.object(m,'ItineraryGenerator',SourceGenerator),patch.object(m.v2,'run_pipeline',side_effect=AssertionError('gate must not run')):
            r=diff.compare_display_models(self.a,other_store,self.a_source,self.b_source,engine=self.engine,
                quality_context=self.context,display_context=self.display)
        self.assertEqual(r['inputReadiness'],'ready');self.assertEqual(r['displayDiffStatus'],'changed')
        self.assertEqual(r['summary']['changedCellCount'],32);self.assertEqual(diff.exit_code(r),0)
        self.assertNotEqual(r['contentFingerprints']['baseline'],r['contentFingerprints']['candidate'])

    def test_direct_filter_scenarios_remain_separate(self):
        def mutate(r,n):
            if n==2:
                for c in r['cells']:
                    if c['dimensions']['scenarioId'].endswith('-direct'):
                        c['model']['items'][0]['destination']='直通条件の合成変更';recompute_cell(c)
                reseal_report(r)
        r,_=self.compare(mutate)
        self.assertEqual(r['summary']['changedCellCount'],16);self.assertEqual(r['summary']['unchangedCellCount'],16)
        self.assertTrue(all(c['dimensions']['scenarioId'].endswith('-direct') for c in r['cellDiffs']))
        self.assertEqual(diff.exit_code(r),0)

    def test_invalid_display_snapshot_missing_source_and_dependency_mismatch(self):
        bad=copy.deepcopy(self.display);bad['contextFingerprint']='1'*64
        r,calls=self.compare(candidate_display_context=bad)
        self.assertEqual(r['inputReadiness'],'invalid');self.assertFalse(calls)
        e=copy.deepcopy(self.engine);e['files'][-1]['sha256']='1'*64;e['engineFingerprint']=q.digest({k:v for k,v in e.items() if k!='engineFingerprint'})
        r,calls=self.compare(candidate_engine=e)
        self.assertEqual(r['comparisonStatus'],'incomparable');self.assertFalse(calls)
        (self.b_source/'Station_all.json').unlink()
        r,calls=self.compare();self.assertEqual(r['inputReadiness'],'unavailable');self.assertFalse(calls)
        make_snapshot(self.b_source)
        (self.b/'snapshot.json').write_text('{"schemaVersion":999}')
        r,calls=self.compare();self.assertEqual(r['inputReadiness'],'invalid');self.assertFalse(calls)
