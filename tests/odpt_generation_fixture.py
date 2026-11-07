"""Explicit synthetic fixtures; no acquired data or real approval is ever used."""
from contextlib import contextmanager, ExitStack
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import copy
import json
import sys

import test_odpt_public_release as data_tests
from test_odpt_public_v2 import _bundle
import odpt_release_contract as c
import odpt_generation_contract as g
from build_odpt_public_release import build
from assemble_odpt_public_site import assemble as site_assemble
from assemble_odpt_generations import assemble

DAY1 = datetime(2026, 11, 9, tzinfo=timezone.utc)
DAY2 = DAY1 + timedelta(days=1)
DAY3 = DAY1 + timedelta(days=2)


@contextmanager
def toolchain(fixture):
    if not fixture.old_toolchain:
        yield
        return
    original = c.site_asset_bytes
    def older_assets(url, kind):
        out = original(url, kind)
        out['odpt_public_runtime.mjs'] = b'// synthetic previously approved toolchain\n' + out['odpt_public_runtime.mjs']
        return out
    with patch('subprocess.run', return_value=SimpleNamespace(stdout='a'*40)), patch.object(c, 'site_asset_bytes', older_assets):
        yield


def make_site(label, *, start='2026-11-09', end='2026-12-09', now=DAY1, old_toolchain=False):
    f = data_tests.ReleaseTests(); f.setUp(); f.old_toolchain = old_toolchain
    first = date.fromisoformat(start) - timedelta(days=1)
    last = date.fromisoformat(end)
    dates = [(first + timedelta(days=i)).isoformat() for i in range((last-first).days+1)]
    original = f.manifest
    f.candidate, f.manifest, f.dates = _bundle(f.root/('candidate-'+label), dates=dates)
    m = f.manifest
    m.update(sourceFiles=original['sourceFiles'], sourceFingerprint=f.fp, publicationApproved=False)
    zero = c.qa._resolution_summary([])
    m['odpt0'] = dict(status='PASS', unmatchedOdptJourneyCount=0,
        diagnosticSeverity={'FAIL': {'failGateCount':0}, 'WARNING': {'codeOccurrences':0}}, resolution=zero,
        stationDateResolution=[dict(stationId=s, serviceDate=d, resolution=copy.deepcopy(zero)) for s in c.STATION_FILES for d in dates])
    m['quality']['odptMatchStatusCounts'] = {'unique_match':len(dates)*8}
    f.save_manifest()
    f.request.update(candidateDigest=c.candidate_digest(f.candidate),
        applicationPeriod={'startsAt':start+'T00:00:00+09:00','endsAt':end+'T00:00:00+09:00'})
    f.request['approval']['recordId'] = 'synthetic-'+label
    if old_toolchain: f.request['codeCommit'] = 'a'*40
    f.save_request()
    f.context = dict(candidate=f.candidate, source=f.source, approval=f.approval,
        expected_candidate_digest=f.request['candidateDigest'], expected_source_fingerprint=f.fp,
        contact_url='https://example.invalid/contact')
    f.site = f.root/'site'
    with toolchain(f):
        build(candidate=f.candidate, source=f.source, approval=f.approval, output=f.output, now=now)
        site_assemble(data_release=f.output, output=f.site, now=now, **f.context)
    return f


def initial(f, empty, output, now=DAY1):
    args = dict(previous=empty, expected_previous_digest=g.read_tree(empty)['digest'], operation='initial',
        new_release=f.site, validation_inputs=f.context, now=now)
    with toolchain(f): result=assemble(output=output, **args)
    return result, args


def change(previous, output, *, fixture=None, now=DAY2, target=None, prune=()):
    snapshot=g.read_tree(previous); m=c.load_json(snapshot['files']['manifest.json'])
    args=dict(previous=previous, expected_previous_digest=snapshot['digest'], expected_previous_release_id=m['releaseId'],
        operation='rollback' if target else 'update', rollback_release_id=target,
        new_release=None if fixture is None else fixture.site,
        validation_inputs=None if fixture is None else fixture.context, now=now, prune_release_ids=prune)
    return assemble(output=output, **args), args


def stage(root):
    root.mkdir()
    with ExitStack() as stack:
        a=make_site('A',old_toolchain=True); stack.callback(a.doCleanups)
        b=make_site('B',now=DAY2); stack.callback(b.doCleanups)
        empty=root/'empty'; empty.mkdir()
        ra,_=initial(a,empty,root/'initial')
        rb,_=change(root/'initial',root/'updated',fixture=b)
        rr,_=change(root/'updated',root/'rollback',target=ra['releaseId'],now=DAY3)
        result={'initial':ra,'updated':rb,'rollback':rr}
        (root/'results.json').write_bytes(c.canonical(result))
        return result


if __name__ == '__main__':
    print(json.dumps(stage(Path(sys.argv[1]))))
