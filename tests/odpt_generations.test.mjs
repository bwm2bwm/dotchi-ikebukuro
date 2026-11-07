import test from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtemp, readdir, readFile, rm } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';
import { webcrypto } from 'node:crypto';

const root=await mkdtemp('/private/tmp/odpt-generations-browser-');
test.after(()=>rm(root,{recursive:true,force:true}));
const scenario=root+'/scenario';
const results=JSON.parse(execFileSync('python3',['-B','tests/odpt_generation_fixture.py',scenario],{encoding:'utf8'}));
async function tree(dir,prefix='') {
  const files=new Map();
  for(const e of await readdir(dir,{withFileTypes:true})) {
    const path=prefix+'/'+e.name;
    if(e.isDirectory()) for(const [k,v] of await tree(dir+'/'+e.name,path))files.set(k,v);
    else files.set(path,await readFile(dir+'/'+e.name));
  }
  return files;
}
const versions=Object.fromEntries(await Promise.all(['initial','updated','rollback'].map(async k=>[k,await tree(scenario+'/'+k)])));
const manifests=Object.fromEntries(Object.entries(versions).map(([k,v])=>[k,JSON.parse(v.get('/manifest.json'))]));
const oldRuntime=await import(pathToFileURL(scenario+'/initial/odpt_public_runtime.mjs'));
const newRuntime=await import(pathToFileURL(scenario+'/updated/odpt_public_runtime.mjs'));
const restoredRuntime=await import(pathToFileURL(scenario+'/rollback/odpt_public_runtime.mjs'));
let active=versions.initial;
const calls=[];
const fetchImpl=async(url,options)=>{
  calls.push({url,options});const raw=active.get(url);assert.ok(raw,`missing published URL ${url}`);return new Response(raw);
};

test('old tab keeps A paths through update; new tab pins B; rollback restores original toolchain and ID',async()=>{
  active=versions.initial;
  const old=await oldRuntime.createV2ReleaseSession({fetchImpl,cryptoImpl:webcrypto});
  const before=await old.loadStation('Hikawadai');
  active=versions.updated;
  const fresh=await newRuntime.createV2ReleaseSession({fetchImpl,cryptoImpl:webcrypto});
  assert.equal(old.releaseId,results.initial.releaseId);assert.equal(fresh.releaseId,results.updated.releaseId);
  for(const s of Object.keys(manifests.initial.stations)) {
    assert.equal((await old.loadStation(s)).manifest.releaseId,old.releaseId);
    assert.equal((await fresh.loadStation(s)).manifest.releaseId,fresh.releaseId);
  }
  const nowMs=Date.parse('2026-11-10T23:30:00+09:00');
  assert.ok(oldRuntime.buildV2PublicBoard(before,{nowMs}).items.length>0);
  assert.equal(oldRuntime.buildV2PublicBoard(before,{nowMs:Date.parse('2026-12-09T00:00:00+09:00')}).validity,'expired');
  active=versions.rollback;
  const restored=await restoredRuntime.createV2ReleaseSession({fetchImpl,cryptoImpl:webcrypto});
  assert.equal(restored.releaseId,old.releaseId);
  assert.deepEqual(versions.rollback.get('/odpt_public_runtime.mjs'),versions.initial.get('/odpt_public_runtime.mjs'));
  assert.notDeepEqual(versions.updated.get('/odpt_public_runtime.mjs'),versions.initial.get('/odpt_public_runtime.mjs'));
  assert.equal((await fresh.loadStation('Wakoshi')).manifest.releaseId,fresh.releaseId); // B remains retained.
  assert.equal((await restored.loadStation('Wakoshi')).manifest.metadata.codeCommit,'a'.repeat(40));
  assert.ok(calls.filter(c=>c.url==='/manifest.json').every(c=>c.options.cache==='no-cache'));
});

test('history metadata, retention, duplicate IDs and unknown contract remain fail-closed',async()=>{
  for(const mutate of [
    m=>{m.publication.contract='unknown';},
    m=>{m.retainedReleases[0].retainUntil='2027-01-01T00:00:00Z';},
    m=>{m.retainedReleases[0].metadata.sourceFingerprint='0'.repeat(64);},
    m=>{m.retainedReleases.push(structuredClone(m.retainedReleases[0]));},
    m=>{m.retainedReleases[0].metadata.quality.resolution.classes.C=1;},
    m=>{m.retainedReleases=[];},
  ]) {
    const m=structuredClone(manifests.updated);mutate(m);
    await assert.rejects(newRuntime.validateV2ReleaseManifest(m,webcrypto));
  }
  await newRuntime.validateV2ReleaseManifest(manifests.updated,webcrypto);
  await restoredRuntime.validateV2ReleaseManifest(manifests.rollback,webcrypto);
});
