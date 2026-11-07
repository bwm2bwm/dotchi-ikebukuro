"""Stage SYNTHETIC v2 data + runtime for private tests.

The source/candidate/approval inputs exist only in a synthetic temporary area.
Default: Phase 2 QA copy. full_site=True: delegate to the Phase 3A assembler
and independent validator, rather than manufacturing a full-site manifest here.
"""
import copy
import json
from pathlib import Path
import shutil
import sys

from test_odpt_public_release import ReleaseTests, NOW
import odpt_release_contract as c
import build_public_site
from test_odpt_public_v2 import _payload


def stage(output, unknown=0, full_site=False):
    fixture = ReleaseTests()
    fixture.setUp()
    try:
        dates = ['2026-10-28', '2026-10-29', '2026-10-30', '2026-10-31', '2026-11-01', '2026-11-02']
        m = fixture.manifest
        m.update(evaluationServiceDates=dates,
                 serviceDateRange={'from': dates[0], 'through': dates[-1]},
                 evaluationServiceDateRange={'from': dates[1], 'through': dates[-2]})
        audits = []
        for station in c.STATION_FILES:
            p = _payload(station, generated_at='2026-10-28T00:00:00Z', dates=dates)
            for day in p['serviceDays']:
                day['departures'] = []
                for route in ('6', '9'):
                    for n, seconds in enumerate((5*3600, 12*3600+60, 12*3600+120, 12*3600+180, 23*3600+59*60, 24*3600+600)):
                        direct = {'kind': 'direct', 'departureServiceSeconds': seconds,
                                  'arrivalServiceSeconds': seconds+900, 'transfer': None}
                        transfer = {'kind': 'transfer', 'departureServiceSeconds': seconds,
                                    'arrivalServiceSeconds': seconds+600,
                                    'transfer': {'stationId': 'KotakeMukaihara', 'waitSeconds': 90,
                                                'outgoingRouteId': '9' if route == '6' else '6'}}
                        can_transfer = station in ('Heiwadai', 'ChikatetsuAkatsuka', 'ChikatetsuNarimasu', 'Wakoshi')
                        primary = transfer if can_transfer else direct
                        display_type = '各駅停車' if route == '6' else '通勤急行'
                        if route == '9' and station in ('KotakeMukaihara', 'Wakoshi') and n in (2, 3):
                            display_type = '急行' if n == 2 else 'Fライナー'
                        row = {'routeId': route, 'destination': '合成終点', 'displayType': display_type,
                               'departureServiceSeconds': seconds, 'primary': primary,
                               'directAlternative': direct, 'bestTransferAlternative': transfer if can_transfer else None}
                        row['id'] = c.v2.public_id(station, day['serviceDate'], row)
                        day['departures'].append(row)
                day['departures'].sort(key=lambda r: (r['departureServiceSeconds'], r['routeId'], r['id']))
                reasons = dict.fromkeys(c.v2.EXCLUSION_REASONS, 0)
                # One known excluded S-TRAIN (A), one crosswalk-only row (B).
                # This models retained audit counts, not a runtime train-name exception.
                reasons['quality_warning'] = 1
                reasons['no_valid_arrival'] = unknown
                classifications = c.v2._expected_classification_counts(reasons)
                audits.append({'stationId': station, 'serviceDate': day['serviceDate'],
                    'generatedCount': len(day['departures'])+1+unknown, 'candidateCount': len(day['departures']),
                    'excludedCount': 1+unknown, 'reasonCounts': reasons, 'classificationCounts': classifications})
            raw = c.canonical(p)
            (fixture.candidate / 'public-candidates' / c.v2.ROUTE_FILENAMES[station]).write_bytes(raw)
            m['candidateFiles'][station].update(bytes=len(raw), sha256=c.digest(raw))
        audit = c.v2._build_exclusion_audit(audits)
        r = c.qa._resolution_summary([])
        r['classes'].update(A=1, B=1)
        r['unmatched'].update(original=2, resolved=2)
        r['warningCodes'].update(original=2, resolved=2)
        details = [{'stationId': s, 'serviceDate': d, 'resolution': copy.deepcopy(r)} for s in c.STATION_FILES for d in dates]
        total = c.qa._merge_resolutions(row['resolution'] for row in details)
        m['odpt0'].update(status='WARNING', resolution=total, stationDateResolution=details,
                         unmatchedOdptJourneyCount=total['unmatched']['original'])
        m['odpt0']['diagnosticSeverity']['WARNING']['codeOccurrences'] = total['warningCodes']['original']
        m['quality'].update(exclusionAudit=audit, itineraryResultCount=audit['totalGeneratedCount'],
            candidateDepartureCount=audit['candidateCount'],
            odptMatchStatusCounts={'unmatched': total['unmatched']['original'],
                'unique_match': audit['totalGeneratedCount']-total['unmatched']['original']})
        fixture.save_manifest()
        fixture.request.update(candidateDigest=c.candidate_digest(fixture.candidate), retrievedAt='2026-10-27T00:00:00Z',
            applicationPeriod={'startsAt': '2026-10-29T00:00:00+09:00', 'endsAt': '2026-11-02T00:00:00+09:00'})
        fixture.request['approval']['approvedAt'] = '2026-10-28T01:00:00Z'
        fixture.save_request()
        result = fixture.build()
        if full_site:
            from assemble_odpt_public_site import assemble
            return assemble(data_release=fixture.output, candidate=fixture.candidate, source=fixture.source,
                approval=fixture.approval, output=output, contact_url='https://example.invalid/contact',
                expected_candidate_digest=fixture.request['candidateDigest'], expected_source_fingerprint=fixture.fp, now=NOW)
        shutil.copytree(fixture.output, output)
        for name, source in build_public_site.SOURCE_FILES.items():
            shutil.copyfile(source, output / name)
        for name in ('preview_public_v2.js', 'odpt_public_runtime.mjs', 'odpt_v2_qa_adapter.mjs', 'odpt_public.css'):
            shutil.copyfile(c.ROOT / '_local_preview' / name, output / name)
        shutil.copyfile(c.ROOT / '_local_preview' / 'public_odpt_index.html', output / 'index.html')
        return result
    finally:
        fixture.doCleanups()


if __name__ == '__main__':
    print(json.dumps(stage(Path(sys.argv[1]), int(sys.argv[2]) if len(sys.argv)>2 else 0,
                           len(sys.argv)>3 and sys.argv[3]=='full-site')))
