/** Private display protocol utilities. No DOM, source IO, or wall-clock defaults. */
import { createHash } from 'node:crypto';
import { ODPT_V2_QA_STATIONS } from '../_local_preview/odpt_v2_qa_adapter.mjs';
export function fail(code) { const e = new Error(code); e.code = code; throw e; }
export function exact(v, fields, code) {
  if (!v || typeof v !== 'object' || Array.isArray(v)
    || Object.keys(v).sort().join('\0') !== [...fields].sort().join('\0')) fail(code);
}
export function canonical(v) {
  if (v === null || ['string','boolean'].includes(typeof v)) return JSON.stringify(v);
  if (typeof v === 'number') { if (!Number.isSafeInteger(v)) fail('canonical_number_invalid'); return JSON.stringify(v); }
  if (Array.isArray(v)) return '['+v.map(canonical).join(',')+']';
  if (v && typeof v === 'object') return '{'+Object.keys(v).sort().map(k=>JSON.stringify(k)+':'+canonical(v[k])).join(',')+'}';
  fail('canonical_value_invalid');
}
export const digest = v => createHash('sha256').update(canonical(v)).digest('hex');
export const scenarios = ['departure','line'].flatMap(mode=>[['all',false],['direct',true]].map(([s,directOnly])=>
  ({id:mode+'-'+s,mode,directOnly,horizonSeconds:86400,lineLimit:3,departureLimit:6})));
export function requiredDates(instant) {
  if (typeof instant !== 'string' || !/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$/.test(instant)) fail('display_instant_invalid');
  const ms = Date.parse(instant);
  if (!Number.isFinite(ms) || new Date(ms).toISOString() !== instant.replace('Z','.000Z')) fail('display_instant_invalid');
  const day = new Date(ms+9*3600000).toISOString().slice(0,10);
  const base = Date.parse(day+'T00:00:00Z');
  return [-1,0,1].map(n=>new Date(base+n*86400000).toISOString().slice(0,10));
}
export function nodeRuntime() {
  return {versions:process.versions,platform:process.platform,arch:process.arch,intl:{
    time:new Intl.DateTimeFormat('en-GB',{timeZone:'Asia/Tokyo'}).resolvedOptions(),
    serviceDate:new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Tokyo'}).resolvedOptions()}};
}
function list(v) { return Array.isArray(v) && v.every(x=>typeof x==='string') && new Set(v).size===v.length; }
export function validateContexts(c,q) {
  exact(q, 'contract schemaVersion profile serviceDates auxiliaryServiceDates stationIds routeIds originStationId direction minimumWaitSeconds maximumWaitSeconds crossServiceDateSearch transferStationId journeyPolicy primaryRule observationInstants displayScenarios displayEvaluation engineFingerprint contextFingerprint'.split(' '),'quality_context_fields_invalid');
  const normalized=structuredClone(q);
  for (const k of ['serviceDates','auxiliaryServiceDates','stationIds','routeIds','observationInstants']) {
    if (!list(q[k])) fail('quality_context_list_invalid'); normalized[k].sort();
  }
  if (!q.direction?.originStopIdsByRoute) fail('quality_direction_invalid');
  for (const k of ['6','9']) {
    if (!list(q.direction.originStopIdsByRoute[k])) fail('quality_direction_invalid');
    normalized.direction.originStopIdsByRoute[k].sort();
  }
  if (!Array.isArray(q.displayScenarios)) fail('quality_scenarios_invalid');
  normalized.displayScenarios.sort((a,b)=>a.id.localeCompare(b.id));
  const {contextFingerprint:qfp,...qb}=normalized;
  if (digest(qb)!==qfp || !/^[a-f0-9]{64}$/.test(q.engineFingerprint)) fail('quality_context_fingerprint_mismatch');
  if (q.contract!=='odpt-quality-evaluation-context'||q.schemaVersion!==1 || canonical(q.profile)!==canonical({id:'dotchi.odpt.itinerary-quality',version:'0.1.0-draft'})
    || q.displayEvaluation!=='not-evaluated'||!q.serviceDates.length || q.originStationId!=='Ikebukuro'
    || q.transferStationId!=='KotakeMukaihara'||q.crossServiceDateSearch!==false||q.minimumWaitSeconds!==60
    || !Number.isInteger(q.maximumWaitSeconds)||q.maximumWaitSeconds<60||q.maximumWaitSeconds>3600
    || q.primaryRule!=='arrival-direct-wait-second-trip-id-v1'
    || canonical(normalized.stationIds)!==canonical(Object.keys(ODPT_V2_QA_STATIONS).sort())
    || canonical(normalized.routeIds)!==canonical(['6','9'])
    || canonical(normalized.direction)!==canonical({rule:'ikebukuro-outbound-order-v1',originStopIdsByRoute:{'6':['228','609'],'9':['228','909']}})
    || canonical(q.journeyPolicy)!==canonical(Object.fromEntries(Object.keys(ODPT_V2_QA_STATIONS).map(s=>[s,['Kanamecho','Senkawa','KotakeMukaihara'].includes(s)?'direct-only':'direct-and-opposite-route-transfer'])))) fail('quality_context_invalid');
  for(const d of [...q.serviceDates,...q.auxiliaryServiceDates]) {
    if (!/^\d{4}-\d\d-\d\d$/.test(d) || new Date(Date.parse(d+'T00:00:00Z')).toISOString().slice(0,10)!==d) fail('quality_date_invalid');
  }
  if(q.serviceDates.some(d=>q.auxiliaryServiceDates.includes(d))) fail('quality_date_overlap');
  q.observationInstants.forEach(requiredDates);
  for (const s of q.displayScenarios) {
    exact(s,['id','mode','directOnly','horizonSeconds','lineLimit','departureLimit'],'quality_scenario_invalid');
    if(!/^[a-z0-9-]{1,64}$/.test(s.id)||!['line','departure'].includes(s.mode)||typeof s.directOnly!=='boolean'||s.horizonSeconds!==86400||s.lineLimit!==3||s.departureLimit!==6) fail('quality_scenario_invalid');
  }
  if(new Set(q.displayScenarios.map(s=>s.id)).size!==q.displayScenarios.length) fail('quality_scenario_invalid');
  exact(c,['contract','schemaVersion','qualityContextFingerprint','observationInstants','displayScenarios','timezone','requiredServiceDates','contextFingerprint'],'display_context_fields_invalid');
  if(c.contract!=='odpt-display-evaluation-context'||c.schemaVersion!==1||c.timezone!=='Asia/Tokyo') fail('display_context_invalid');
  if(c.qualityContextFingerprint!==qfp) fail('display_quality_context_mismatch');
  if(!list(c.observationInstants)||!c.observationInstants.length||c.observationInstants.length>1000) fail('display_instants_invalid');
  if(!Array.isArray(c.displayScenarios)) fail('display_scenarios_invalid');
  const n={...c,observationInstants:[...c.observationInstants].sort(),displayScenarios:[...c.displayScenarios].sort((a,b)=>a.id.localeCompare(b.id))};
  if(canonical(n.displayScenarios)!==canonical(scenarios)) fail('display_scenarios_invalid');
  const dates=Object.fromEntries(n.observationInstants.map(i=>[i,requiredDates(i)]));
  if(canonical(dates)!==canonical(c.requiredServiceDates)) fail('display_required_dates_mismatch');
  const available=[...q.serviceDates,...q.auxiliaryServiceDates];
  if(Object.values(dates).some(ds=>ds.some(d=>!available.includes(d)))) fail('display_quality_dates_missing');
  const {contextFingerprint,...body}=n;
  if(digest(body)!==contextFingerprint) fail('display_context_fingerprint_mismatch');
  return n;
}

/** Reject duplicate JSON keys and deep nesting before schema validation. */
export function parseRequestJson(text) {
  let pos=0;
  const ws=()=>{while(/[ \t\r\n]/.test(text[pos]??'')&&pos<text.length)pos++;};
  function string() {
    const start=pos++;
    while(pos<text.length) {
      const ch=text[pos++];
      if(ch==='\\')pos++;
      else if(ch==='"')return JSON.parse(text.slice(start,pos));
    }
    fail('request_json_invalid');
  }
  function value(depth=0) {
    if(depth>64)fail('request_depth_limit');ws();
    const ch=text[pos];
    if(ch==='"')return string();
    if(ch==='{'||ch==='[') {
      pos++;const object=ch==='{',result=object?Object.create(null):[],keys=new Set(),end=object?'}':']';
      ws();if(text[pos]===end){pos++;return result;}
      while(pos<text.length) {
        ws();let key;
        if(object) {
          if(text[pos]!=='"')fail('request_json_invalid');key=string();
          if(keys.has(key))fail('request_json_duplicate_key');keys.add(key);ws();
          if(text[pos++]!==':')fail('request_json_invalid');
        }
        const v=value(depth+1);if(object)result[key]=v;else result.push(v);
        ws();const next=text[pos++];if(next===end)return result;
        if(next!==',')fail('request_json_invalid');
      }
      fail('request_json_invalid');
    }
    const m=/^(?:true|false|null|-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)/.exec(text.slice(pos));
    if(!m)fail('request_json_invalid');pos+=m[0].length;return JSON.parse(m[0]);
  }
  const result=value();ws();if(pos!==text.length)fail('request_json_invalid');return result;
}
