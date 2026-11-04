#!/usr/bin/env python3
"""Read-only quality evaluation context, engine identity and input readiness.

Never generates journeys, metrics, candidates or display models.
"""
from __future__ import annotations
import argparse
import ast
import copy
import hashlib
import json
import platform
import re
import shutil
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import TZPATH

if __package__:
    from .odpt_source_contract import SOURCE_FILES
    from .odpt_source_store import StoreError, load_store_contract
    from .odpt_train_semantic_diff import SemanticDiffError, _read_bytes, _root
else:
    from odpt_source_contract import SOURCE_FILES
    from odpt_source_store import StoreError, load_store_contract
    from odpt_train_semantic_diff import SemanticDiffError, _read_bytes, _root

ROOT = Path(__file__).resolve().parents[1]
PROFILE = {'id': 'dotchi.odpt.itinerary-quality', 'version': '0.1.0-draft'}
STATIONS = ('Kanamecho','Senkawa','KotakeMukaihara','Hikawadai','Heiwadai','ChikatetsuAkatsuka','ChikatetsuNarimasu','Wakoshi')
SEEDS = ('scripts/odpt_itinerary.py','scripts/odpt_train_matcher.py','scripts/odpt_stop_patterns.py',
         'scripts/odpt_public_v2.py','scripts/odpt_snapshot_qa.py','scripts/export_local_timetable_payload.py',
         'scripts/prepare_odpt_v2_qa.py','_local_preview/odpt_v2_qa_adapter.mjs','scripts/odpt_quality_input.py')
FIELDS = set('contract schemaVersion profile serviceDates auxiliaryServiceDates stationIds routeIds originStationId direction minimumWaitSeconds maximumWaitSeconds crossServiceDateSearch transferStationId journeyPolicy primaryRule observationInstants displayScenarios displayEvaluation engineFingerprint contextFingerprint'.split())
NOT_EVALUATED = ['feed-service-availability','journey-generation','quality-metrics','quality-diff','display-model','browser-runtime',
                 'freshness','application-period','publication-eligibility','cross-source-consistency',
                 'phase2b-opaque-and-auxiliary-semantics']


class QualityInputError(ValueError):
    def __init__(self, code, category='invalid'):
        self.code, self.category = code, category
        super().__init__(code)


def fail(code, category='invalid'): raise QualityInputError(code, category)


def canonical(value):
    try: return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')
    except (ValueError, TypeError, UnicodeError): fail('canonical_value_invalid')


def digest(value): return hashlib.sha256(canonical(value)).hexdigest()


def _read(path):
    try:
        _root(path.parent)
        return _read_bytes(path)
    except SemanticDiffError as exc:
        fail(exc.code, 'unavailable' if exc.code in {'source_unavailable','source_directory_unavailable','source_read_failed'} else 'invalid')


def loads(text):
    def pairs(items):
        obj = {}
        for k,v in items:
            if k in obj: fail('json_duplicate_key')
            obj[k]=v
        return obj
    try: return json.loads(text, object_pairs_hook=pairs, parse_constant=lambda _: fail('json_constant_invalid'))
    except (ValueError, UnicodeError, RecursionError) as exc:
        if isinstance(exc, QualityInputError): raise
        fail('json_invalid')


def _date(value):
    if not isinstance(value,str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}',value): fail('context_date_invalid')
    try: return date.fromisoformat(value).isoformat()
    except ValueError: fail('context_date_invalid')


def _set_list(value, code):
    if not isinstance(value,list) or any(not isinstance(v,str) for v in value) or len(set(value))!=len(value): fail(code)
    return sorted(value)


def _hex(value): return isinstance(value,str) and re.fullmatch(r'[0-9a-f]{64}',value) is not None


def normalize_context(context, *, seal=False):
    if not isinstance(context,dict): fail('context_incomplete','incomparable')
    missing=FIELDS-context.keys()
    if seal: missing -= {'contextFingerprint'}
    if context.keys()-FIELDS: fail('context_unknown_field')
    if missing: fail('context_incomplete','incomparable')
    c=copy.deepcopy(context)
    if c['contract']!='odpt-quality-evaluation-context' or type(c['schemaVersion']) is not int or c['schemaVersion']!=1 or c['profile']!=PROFILE: fail('context_contract_invalid')
    for field in ('serviceDates','auxiliaryServiceDates','stationIds','routeIds','observationInstants'):
        c[field]=_set_list(c[field],'context_list_invalid')
    if not c['serviceDates']: fail('context_dates_empty')
    for day in c['serviceDates']+c['auxiliaryServiceDates']: _date(day)
    if set(c['serviceDates']) & set(c['auxiliaryServiceDates']): fail('context_date_overlap')
    if set(c['stationIds'])!=set(STATIONS): fail('context_station_set_invalid')
    if c['routeIds']!=['6','9'] or c['originStationId']!='Ikebukuro' or c['transferStationId']!='KotakeMukaihara': fail('context_route_or_origin_invalid')
    expected_direction={'rule':'ikebukuro-outbound-order-v1','originStopIdsByRoute':{'6':['228','609'],'9':['228','909']}}
    direction=c['direction']
    if not isinstance(direction,dict) or set(direction)!={'rule','originStopIdsByRoute'}: fail('context_direction_invalid')
    ids=direction['originStopIdsByRoute']
    if not isinstance(ids,dict) or set(ids)!={'6','9'}: fail('context_direction_invalid')
    for route in ids: ids[route]=_set_list(ids[route],'context_direction_invalid')
    if direction!=expected_direction: fail('context_direction_invalid')
    lo,hi=c['minimumWaitSeconds'],c['maximumWaitSeconds']
    if type(lo) is not int or type(hi) is not int or lo!=60 or not lo<=hi<=3600: fail('context_wait_invalid')
    if type(c['crossServiceDateSearch']) is not bool or c['crossServiceDateSearch']: fail('context_cross_date_unsupported')
    expected_policy={s: 'direct-only' if s in STATIONS[:3] else 'direct-and-opposite-route-transfer' for s in STATIONS}
    if c['journeyPolicy']!=expected_policy: fail('context_journey_policy_invalid')
    if c['primaryRule']!='arrival-direct-wait-second-trip-id-v1': fail('context_primary_rule_unsupported')
    if c['displayEvaluation']!='not-evaluated': fail('context_display_stage_unsupported')
    for instant in c['observationInstants']:
        if not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z',instant): fail('context_instant_invalid')
        try: datetime.strptime(instant,'%Y-%m-%dT%H:%M:%SZ')
        except ValueError: fail('context_instant_invalid')
    if not isinstance(c['displayScenarios'],list): fail('context_display_scenario_invalid')
    seen=set()
    for scenario in c['displayScenarios']:
        if not isinstance(scenario,dict) or set(scenario)!={'id','mode','directOnly','horizonSeconds','lineLimit','departureLimit'}: fail('context_display_scenario_invalid')
        if not isinstance(scenario['id'],str) or not re.fullmatch(r'[a-z0-9-]{1,64}',scenario['id']) or scenario['id'] in seen: fail('context_display_scenario_invalid')
        seen.add(scenario['id'])
        if not isinstance(scenario['mode'],str) or scenario['mode'] not in {'line','departure'} or type(scenario['directOnly']) is not bool: fail('context_display_scenario_invalid')
        for field,expected in (('horizonSeconds',86400),('lineLimit',3),('departureLimit',6)):
            if type(scenario[field]) is not int or scenario[field]!=expected: fail('context_display_scenario_invalid')
    c['displayScenarios'].sort(key=lambda s:s['id'])
    if not _hex(c['engineFingerprint']): fail('context_engine_reference_invalid')
    body={k:v for k,v in c.items() if k!='contextFingerprint'}
    fp=digest(body)
    if not seal and c['contextFingerprint']!=fp: fail('context_fingerprint_mismatch')
    c['contextFingerprint']=fp
    return c


def initial_context(engine_fingerprint):
    return normalize_context({'contract':'odpt-quality-evaluation-context','schemaVersion':1,'profile':dict(PROFILE),
        'serviceDates':['2026-10-28','2026-10-29','2026-10-30'],'auxiliaryServiceDates':[],
        'stationIds':list(STATIONS),'routeIds':['6','9'],'originStationId':'Ikebukuro',
        'direction':{'rule':'ikebukuro-outbound-order-v1','originStopIdsByRoute':{'6':['228','609'],'9':['228','909']}},
        'minimumWaitSeconds':60,'maximumWaitSeconds':3600,'crossServiceDateSearch':False,'transferStationId':'KotakeMukaihara',
        'journeyPolicy':{s:'direct-only' if s in STATIONS[:3] else 'direct-and-opposite-route-transfer' for s in STATIONS},
        'primaryRule':'arrival-direct-wait-second-trip-id-v1','observationInstants':[],'displayScenarios':[],
        'displayEvaluation':'not-evaluated','engineFingerprint':engine_fingerprint},seal=True)


def compare_contexts(baseline,candidate):
    values=[];errors=[]
    for side,c in (('baseline',baseline),('candidate',candidate)):
        try: values.append(normalize_context(c))
        except QualityInputError as exc: errors.append({'side':side,'code':exc.code,'category':exc.category})
    if errors: return {'status':'invalid' if any(e['category']=='invalid' for e in errors) else 'insufficient','errors':errors,'contexts':None}
    changed=sorted(k for k in FIELDS-{'contextFingerprint'} if values[0][k]!=values[1][k])
    return {'status':'different' if changed else 'identical','changedFields':changed,'contexts':values,'errors':[]}


def _local_imports(path, raw, root):
    try: tree=ast.parse(raw.decode('utf-8'))
    except (ValueError,SyntaxError,UnicodeError): fail('engine_dependency_syntax_invalid')
    names=set()
    for node in ast.walk(tree):
        if isinstance(node,ast.Import): names.update(a.name for a in node.names)
        if isinstance(node,ast.ImportFrom) and node.module: names.add(node.module)
        if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id=='__import__':
            if not node.args or not isinstance(node.args[0],ast.Constant) or not isinstance(node.args[0].value,str): fail('engine_dynamic_import_unresolved')
            names.add(node.args[0].value)
    dependencies=set()
    for name in names:
        leaf=name.split('.')[-1]; relative='scripts/'+leaf+'.py'
        if leaf.startswith('odpt_') or leaf in {'export_local_timetable_payload','prepare_odpt_v2_qa'}:
            if not (root/relative).is_file(): fail('engine_dependency_missing','unavailable')
            dependencies.add(relative)
        elif (root/relative).is_file(): dependencies.add(relative)
    return dependencies


def _mapping(raw):
    tree=ast.parse(raw.decode('utf-8')); values={}
    for node in tree.body:
        if isinstance(node,ast.Assign):
            for target in node.targets:
                if isinstance(target,ast.Name) and target.id in {'DESTINATIONS','STATION_STOP_IDS','ROUTES','OPPOSITE_ROUTE','LINE_ODPT','ODPT_CALENDAR'}:
                    try: values[target.id]=ast.literal_eval(node.value)
                    except ValueError: fail('engine_station_mapping_unresolved')
    if set(values)!={'DESTINATIONS','STATION_STOP_IDS','ROUTES','OPPOSITE_ROUTE','LINE_ODPT','ODPT_CALENDAR'}: fail('engine_station_mapping_missing')
    if set(values['DESTINATIONS'])!=set(STATIONS) or set(values['ROUTES'])!={'6','9'}: fail('engine_station_mapping_unsupported')
    for node in tree.body:
        if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='ROUTE_STOP_IDS' for t in node.targets):
            try:
                origins={}
                for route,definition in zip(node.value.keys,node.value.values):
                    for key,value in zip(definition.keys,definition.values):
                        if isinstance(key,ast.Constant) and key.value=='ikebukuro': origins[ast.literal_eval(route)]=sorted(ast.literal_eval(value))
                values['ORIGIN_ROUTE_STOP_IDS']=origins
            except (ValueError,AttributeError,TypeError): fail('engine_station_mapping_unresolved')
    if set(values.get('ORIGIN_ROUTE_STOP_IDS',{}))!={'6','9'}: fail('engine_station_mapping_unresolved')
    # Sets are explicitly sorted for the mapping digest; no source arrays are transformed.
    return {k:({name:sorted(v) for name,v in val.items()} if k=='STATION_STOP_IDS' else val) for k,val in values.items()}


def collect_environment():
    node=shutil.which('node')
    if not node: fail('node_runtime_unavailable','unavailable')
    js="console.log(JSON.stringify({versions:process.versions,platform:process.platform,arch:process.arch,intl:{time:new Intl.DateTimeFormat('en-GB',{timeZone:'Asia/Tokyo'}).resolvedOptions(),serviceDate:new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Tokyo'}).resolvedOptions()}}))"
    try:
        run=subprocess.run([node,'-e',js],capture_output=True,text=True,timeout=10,check=True)
        node_env=loads(run.stdout)
        node_hash=hashlib.sha256(Path(node).resolve().read_bytes()).hexdigest()
        python_hash=hashlib.sha256(Path(sys.executable).resolve().read_bytes()).hexdigest()
    except (OSError,subprocess.SubprocessError): fail('runtime_probe_failed','unavailable')
    zones=[]
    for name in ('tzdata.zi','Asia/Tokyo'):
        for base in TZPATH:
            p=Path(base)/name
            if p.is_file():
                try: zones.append({'name':name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
                except OSError: fail('timezone_data_unavailable','unavailable')
                break
    if not any(z['name']=='Asia/Tokyo' for z in zones): fail('timezone_data_unavailable','unavailable')
    return {'python':{'implementation':platform.python_implementation(),'version':sys.version,'cacheTag':sys.implementation.cache_tag,
                      'binarySha256':python_hash},'node':node_env,'nodeBinarySha256':node_hash,'timezoneData':zones,
            'platform':{'system':platform.system(),'release':platform.release(),'machine':platform.machine(),'libc':list(platform.libc_ver()),'byteorder':sys.byteorder}}


def build_engine(root=ROOT, environment=None):
    root=Path(root); pending=set(SEEDS); entries={}; identities={}; mapping=None
    while pending:
        name=min(pending);pending.remove(name)
        if name in entries: continue
        path=root/name
        try: raw,identity=_read(path)
        except QualityInputError as exc: fail('engine_dependency_'+exc.code,exc.category)
        entries[name]={'path':name,'sha256':hashlib.sha256(raw).hexdigest(),'sizeBytes':len(raw)};identities[name]=identity
        if path.suffix=='.py': pending.update(_local_imports(path,raw,root)-entries.keys())
        if name=='scripts/odpt_itinerary.py':
            try: mapping=_mapping(raw)
            except (TypeError,AttributeError,ValueError) as exc:
                if isinstance(exc,QualityInputError): raise
                fail('engine_station_mapping_invalid')
        if path.suffix=='.mjs':
            for spec in re.findall(r"(?:from\s*|import\s*\(?\s*)['\"]([^'\"]+)['\"]",raw.decode('utf-8')):
                if not spec.startswith('./'): fail('engine_js_import_unresolved')
                dep=path.parent/spec
                if '..' in dep.parts: fail('engine_js_import_unresolved')
                pending.add(dep.relative_to(root).as_posix())
    for name in sorted(entries):
        raw,identity=_read(root/name)
        if identity!=identities[name] or hashlib.sha256(raw).hexdigest()!=entries[name]['sha256']: fail('engine_changed_during_scan','incomparable')
    body={'contract':'odpt-quality-engine','schemaVersion':1,'files':[entries[k] for k in sorted(entries)],
          'stationMappingFingerprint':digest(mapping),'stationMapping':mapping,'environment':copy.deepcopy(environment if environment is not None else collect_environment())}
    return {**body,'engineFingerprint':digest(body)}


def _validate_engine(engine):
    if engine is None: fail('engine_evidence_missing','unavailable')
    fields={'contract','schemaVersion','files','stationMappingFingerprint','stationMapping','environment','engineFingerprint'}
    if not isinstance(engine,dict) or set(engine)!=fields or engine['contract']!='odpt-quality-engine' or type(engine['schemaVersion']) is not int or engine['schemaVersion']!=1: fail('engine_contract_invalid')
    if not isinstance(engine['files'],list): fail('engine_contract_invalid')
    names=[]
    for f in engine['files']:
        if not isinstance(f,dict) or set(f)!={'path','sha256','sizeBytes'} or not isinstance(f['path'],str) or not _hex(f['sha256']) or type(f['sizeBytes']) is not int or f['sizeBytes']<0: fail('engine_contract_invalid')
        names.append(f['path'])
    if names!=sorted(set(names)) or not set(SEEDS)<=set(names) or not _hex(engine['stationMappingFingerprint']) or not isinstance(engine['environment'],dict): fail('engine_contract_invalid')
    if digest(engine['stationMapping'])!=engine['stationMappingFingerprint']: fail('engine_mapping_fingerprint_mismatch')
    if digest({k:v for k,v in engine.items() if k!='engineFingerprint'})!=engine['engineFingerprint']: fail('engine_fingerprint_mismatch')


def validate_inputs(baseline_store,candidate_store,baseline_source_dir,candidate_source_dir,
                    baseline_context,candidate_context,baseline_engine,candidate_engine, *, root=ROOT):
    result={'contract':'odpt-quality-input-validation','schemaVersion':1,'profile':dict(PROFILE),
            'evaluationContext':None,'contextFingerprint':None,'engineFingerprint':None,'environment':None,
            'baselineSnapshotId':None,'candidateSnapshotId':None,'baselineContentFingerprint':None,'candidateContentFingerprint':None,
            'inputChecks':{},'comparisonReadiness':'ready','reasonCodes':[],'notEvaluated':list(NOT_EVALUATED)}
    problems=[]
    def problem(code,category): problems.append((code,category))
    compared=compare_contexts(baseline_context,candidate_context);result['inputChecks']['context']=compared['status']
    for e in compared['errors']: problem(e['code'],e['category'])
    if compared['status']=='different': problem('context_conditions_mismatch','incomparable')
    if compared['contexts']:
        result['evaluationContext']={'baseline':compared['contexts'][0],'candidate':compared['contexts'][1]}
        result['contextFingerprint']={'baseline':compared['contexts'][0]['contextFingerprint'],'candidate':compared['contexts'][1]['contextFingerprint']}
    current=None
    engine_problem_start=len(problems)
    try:
        for engine in (baseline_engine,candidate_engine): _validate_engine(engine)
        current=build_engine(root)
        result['engineFingerprint']={'baseline':baseline_engine['engineFingerprint'],'candidate':candidate_engine['engineFingerprint'],'current':current['engineFingerprint']}
        result['environment']=current['environment']
        for engine in (baseline_engine,candidate_engine):
            if engine['engineFingerprint']!=current['engineFingerprint']: problem('engine_current_fingerprint_mismatch','incomparable')
            if canonical(engine['environment'])!=canonical(current['environment']): problem('engine_environment_mismatch','incomparable')
            if engine['files']!=current['files'] or engine['stationMappingFingerprint']!=current['stationMappingFingerprint']: problem('engine_dependencies_mismatch','incomparable')
        if baseline_engine['engineFingerprint']!=candidate_engine['engineFingerprint']: problem('engine_fingerprints_differ','incomparable')
        if compared['contexts']:
            for c,e in zip(compared['contexts'],(baseline_engine,candidate_engine)):
                if c['engineFingerprint']!=e['engineFingerprint']: problem('context_engine_reference_mismatch','incomparable')
        if compared['contexts']:
            for c in compared['contexts']:
                actual={s: 'direct-only' if current['stationMapping']['DESTINATIONS'][s]['routePolicy']=='direct_only' else 'direct-and-opposite-route-transfer' for s in STATIONS}
                if c['direction']['originStopIdsByRoute']!=current['stationMapping']['ORIGIN_ROUTE_STOP_IDS'] or c['journeyPolicy']!=actual:
                    problem('context_station_mapping_mismatch','incomparable')
        result['inputChecks']['engine']='PASS' if len(problems)==engine_problem_start else 'not-ready'
    except QualityInputError as exc: problem(exc.code,exc.category);result['inputChecks']['engine']='FAIL'
    loaded={}; signatures={}
    for role,store,directory in (('baseline',baseline_store,baseline_source_dir),('candidate',candidate_store,candidate_source_dir)):
        check={'storeContract':'not-checked','contentFingerprint':'not-checked','originalBytes':'not-checked','postValidation':'not-checked','sourceCount':0}
        result['inputChecks'][role]=check
        try:
            value=load_store_contract(store);loaded[role]=value
            result[role+'SnapshotId']=value['snapshot']['snapshotId'];result[role+'ContentFingerprint']=value['snapshot']['contentFingerprint']
            check['storeContract']='PASS';check['contentFingerprint']='PASS';_root(directory)
            for record in value['records']:
                sid=record['sourceId'];raw,identity=_read(directory/SOURCE_FILES[sid]); artifact=record['artifact']
                if not artifact: fail('source_artifact_missing')
                sig=(hashlib.sha256(raw).hexdigest(),len(raw))
                if sig!=(artifact['sha256'],artifact['sizeBytes']): fail('source_bytes_mismatch')
                signatures[role,sid]=(sig,identity);check['sourceCount']+=1
            check['originalBytes']='PASS'
        except (StoreError,SemanticDiffError,QualityInputError) as exc:
            category=getattr(exc,'category','unavailable' if exc.code in {'store_not_found','source_unavailable','source_directory_unavailable'} else 'invalid')
            problem(exc.code,category);check['originalBytes']='FAIL'
            if check['storeContract']=='not-checked': check['storeContract']='FAIL'
    for role,store,directory in (('baseline',baseline_store,baseline_source_dir),('candidate',candidate_store,candidate_source_dir)):
        try:
            if role in loaded and loaded[role]!=load_store_contract(store): fail('store_changed_during_validation')
            for sid in sorted(SOURCE_FILES):
                if (role,sid) not in signatures: continue
                raw,identity=_read(directory/SOURCE_FILES[sid])
                if ((hashlib.sha256(raw).hexdigest(),len(raw)),identity)!=signatures[role,sid]: fail('source_changed_during_validation')
            result['inputChecks'][role]['postValidation']='PASS' if result['inputChecks'][role]['sourceCount']==7 else 'incomplete'
        except (StoreError,QualityInputError) as exc:
            problem(exc.code,getattr(exc,'category','invalid'));result['inputChecks'][role]['postValidation']='FAIL'
    if current is not None:
        try:
            if current!=build_engine(root): problem('engine_changed_during_validation','incomparable')
        except QualityInputError as exc: problem(exc.code,exc.category)
    result['reasonCodes']=sorted({code for code,_ in problems})
    for category in ('invalid','unavailable','incomparable'):
        if any(c==category for _,c in problems): result['comparisonReadiness']=category;break
    return result


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('baseline-store','candidate-store','baseline-source-dir','candidate-source-dir'):
        p.add_argument('--'+name,type=Path,required=True)
    for name in ('baseline-context','candidate-context','baseline-engine','candidate-engine'): p.add_argument('--'+name,type=Path)
    args=p.parse_args(argv)
    try:
        engine=build_engine(); context=initial_context(engine['engineFingerprint'])
        def pair(kind,default):
            paths=[getattr(args,role+'_'+kind) for role in ('baseline','candidate')]
            if not any(paths): return [copy.deepcopy(default),copy.deepcopy(default)]
            return [loads(_read(path)[0].decode('utf-8')) if path else None for path in paths]
        contexts=pair('context',context);engines=pair('engine',engine)
        r=validate_inputs(args.baseline_store,args.candidate_store,args.baseline_source_dir,args.candidate_source_dir,*contexts,*engines)
        print('comparison_readiness='+r['comparisonReadiness']+' metrics=not-evaluated')
        print('profile='+PROFILE['id']+' version='+PROFILE['version'])
        print('context_fingerprints='+json.dumps(r['contextFingerprint'],sort_keys=True))
        print('engine_fingerprints='+json.dumps(r['engineFingerprint'],sort_keys=True))
        if r['evaluationContext']:
            c=r['evaluationContext']['baseline'];print('service_dates='+','.join(c['serviceDates'])+' wait_seconds='+str(c['minimumWaitSeconds'])+'..'+str(c['maximumWaitSeconds']))
        print('snapshots='+json.dumps({k:r[k] for k in ('baselineSnapshotId','candidateSnapshotId','baselineContentFingerprint','candidateContentFingerprint')},sort_keys=True))
        print('origin=Ikebukuro routes=6,9 stations=8 cross_service_date_search=false display=not-evaluated')
        print('input_checks='+json.dumps(r['inputChecks'],sort_keys=True))
        print('reasons='+(','.join(r['reasonCodes']) or 'none'))
        return {'ready':0,'incomparable':2,'invalid':3,'unavailable':4}[r['comparisonReadiness']]
    except (QualityInputError,UnicodeError) as exc:
        code=getattr(exc,'code','json_invalid');category=getattr(exc,'category','invalid')
        print('comparison_readiness='+category+' error='+code+' metrics=not-evaluated')
        return {'incomparable':2,'invalid':3,'unavailable':4}[category]


if __name__=='__main__': raise SystemExit(main())
