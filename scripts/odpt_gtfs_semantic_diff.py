#!/usr/bin/env python3
"""Private read-only comparison of six GTFS operational tables."""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import resource
import time
import zipfile
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

if __package__:
    from . import odpt_gtfs_loader as loader
    from .odpt_source_contract import SOURCE_FILES
    from .odpt_source_store import load_store_contract, StoreError
    from .odpt_train_semantic_diff import compare_train_timetables, SemanticDiffError, _root, _read_bytes
else:
    import odpt_gtfs_loader as loader
    from odpt_source_contract import SOURCE_FILES
    from odpt_source_store import load_store_contract, StoreError
    from odpt_train_semantic_diff import compare_train_timetables, SemanticDiffError, _root, _read_bytes

TABLES = ('routes', 'stops', 'trips', 'stop_times', 'calendar', 'calendar_dates')
NOT_EVALUATED = ('agency', 'feed_info', 'fare_attributes', 'fare_rules', 'translations')
MAX_DETAILS = 1000  # shared by findings and ambiguities for the GTFS source
MAX_CALENDAR_DAYS = 3660
MAX_SERVICE_DATES = 1_000_000
MISSING = object()


def _digest(value):
    return hashlib.sha256(repr(value).encode()).hexdigest()


def _signature(row, excluded=()):
    # Type names prevent bool/numeric equality from masking unsupported structure.
    return tuple((k, type(v).__name__, v) for k, v in sorted(row.items()) if k not in excluded)


def _record_key(table, row):
    fields = loader.SCHEMAS[table][2].split()
    return tuple(row[field] for field in fields)


def _csv_evidence(raw):
    text = raw.decode('utf-8-sig')
    reader = csv.reader(io.StringIO(text, newline=''), strict=True)
    header = next(reader)
    ordered = hashlib.sha256()
    for row in reader:
        ordered.update(_digest(tuple(sorted(zip(header, row)))).encode())
    # Exact lexical records prove a pure row permutation, including quote/newline style.
    records = Counter(); quoted = False; start = 0; first = None; i = 0
    while i < len(text):
        ch = text[i]
        if ch == '"': quoted = not quoted
        if ch in '\r\n' and not quoted:
            end = i + 1
            if ch == '\r' and end < len(text) and text[end] == '\n': end += 1
            part = text[start:end]
            if first is None: first = part
            else: records[_digest(part)] += 1
            start = end; i = end; continue
        i += 1
    if start < len(text):
        part = text[start:]
        if first is None: first = part
        else: records[_digest(part)] += 1
    return {'orderedCells': ordered.hexdigest(), 'lexicalHeader': _digest((raw.startswith(b'\xef\xbb\xbf'), first)),
            'lexicalRows': _digest(tuple(sorted(records.items())))}


def _compact(path, record):
    started = time.perf_counter()
    parsed = loader.load_gtfs(path, record)
    result = {'tables': {}, 'input': parsed['input'], 'issues': parsed['errorCodes'], 'period': None}
    feed = parsed['tables'].get('feed_info', {}).get('rows', [])
    if feed:
        a, b = (feed[0]['values'].get(f) for f in ('feed_start_date', 'feed_end_date'))
        if a and b: result['period'] = (a, b)
    for table in TABLES:
        tab = parsed['tables'].pop(table, None)
        if tab is None:
            result['tables'][table] = {'present': False, 'headers': [], 'rows': {}, 'issues': [], 'cellsDigest': None}
            continue
        cells = hashlib.sha256(); indexed = {}
        for entry in tab['rows']:
            cells.update(_digest(tuple(sorted(entry.pop('cells').items()))).encode())
            row = entry.pop('values'); key = _record_key(table, row)
            if key in indexed: loader.fail('gtfs_key_duplicate')
            indexed[key] = row
        result['tables'][table] = {'present': True, 'headers': tab['headers'], 'rows': indexed,
                                  'issues': tab['issues'], 'cellsDigest': cells.hexdigest()}
    # All remaining table semantics are deliberately discarded, never compared.
    del parsed
    raw, _ = loader._read(path)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        result['memberHashes'] = {name: hashlib.sha256(archive.read(name)).hexdigest() for name in sorted(archive.namelist())}
        for table in TABLES:
            if result['tables'][table]['present']:
                result['tables'][table]['csvEvidence'] = _csv_evidence(archive.read(table + '.txt'))
    result['parseSeconds'] = time.perf_counter() - started
    return result


class Evidence:
    def __init__(self):
        self.findings = []; self.ambiguities = []; self.categories = Counter(); self.total = 0
        self.counts = Counter(); self.truncated = 0

    def add(self, kind, table, key=(), field=None, *, ambiguity=False, **extra):
        self.categories[kind] += 1; self.total += 1
        finding = {'kind': kind, 'table': table, 'recordKey': list(key), **extra}
        if field is not None: finding['fieldPath'] = '/' + field.replace('~', '~0').replace('/', '~1')
        if len(self.findings) + len(self.ambiguities) < MAX_DETAILS:
            (self.ambiguities if ambiguity else self.findings).append(finding)
        else: self.truncated += 1


def _kind(table, field, unknown):
    if unknown: return 'unsupported-field-change'
    if table in {'calendar', 'calendar_dates'}: return 'calendar-record-changed'
    if table == 'stop_times':
        if field in {'arrival_time', 'departure_time'}: return 'time-changed'
        if field == 'stop_id': return 'stop-pattern-changed'
    if field in {'parent_station', 'route_id', 'service_id', 'shape_id', 'block_id'}: return 'reference-changed'
    return 'operational-attribute-changed'


def _compare_table(table, left, right, evidence):
    a, b = left['rows'], right['rows']; counts = Counter(added=0, removed=0, modified=0, fieldChanges=0, schemaChanges=0)
    known = set((loader.SCHEMAS[table][0] + ' ' + loader.SCHEMAS[table][1]).split())
    for field in sorted(set(left['headers']) ^ set(right['headers'])):
        evidence.add('column-added' if field in right['headers'] else 'column-removed', table, field=field)
        counts['schemaChanges'] += 1
        if field not in known: evidence.add('unsupported-field-change', table, field=field)
    if left['present'] != right['present']:
        evidence.add('table-added' if right['present'] else 'table-removed', table); counts['schemaChanges'] += 1
    removed, added = sorted(a.keys() - b.keys()), sorted(b.keys() - a.keys())
    for kind, keys in (('record-removed', removed), ('record-added', added)):
        for key in keys: evidence.add(kind, table, key)
    counts.update(added=len(added), removed=len(removed))
    for key in sorted(a.keys() & b.keys()):
        modified = False
        for field in sorted(a[key].keys() | b[key].keys()):
            old, new = a[key].get(field, MISSING), b[key].get(field, MISSING)
            if type(old) is type(new) and old == new: continue
            modified = True; counts['fieldChanges'] += 1
            extra = {'baselineState': 'missing' if old is MISSING else 'empty' if old is None else 'value',
                     'candidateState': 'missing' if new is MISSING else 'empty' if new is None else 'value'}
            if field in {'arrival_time', 'departure_time'} and type(old) is int and type(new) is int:
                extra['deltaSeconds'] = new - old
            unsupported = field not in known
            if field in loader.ENUMS:
                unsupported |= any(v is not MISSING and v is not None and v not in loader.ENUMS[field] for v in (old, new))
            if field == 'route_type':
                unsupported |= any(v is not MISSING and v is not None and v not in {*range(8), 11, 12} for v in (old, new))
            evidence.add(_kind(table, field, unsupported), table, key, field, **extra)
        if modified:
            counts['modified'] += 1
            identity = {'routes': {'route_type'}, 'stops': {'parent_station', 'stop_lat', 'stop_lon'},
                        'trips': {'route_id', 'service_id', 'direction_id'}, 'stop_times': {'stop_id'}}.get(table, set())
            if any(a[key].get(f, MISSING) != b[key].get(f, MISSING) for f in identity):
                evidence.add('suspected-identifier-reuse', table, key, ambiguity=True)
    # Conservative ID candidates: only full equality of all other compared attributes.
    if table in {'routes', 'stops', 'trips'} and not (left['issues'] or right['issues']):
        groups = defaultdict(lambda: [[], []]); key_fields = loader.SCHEMAS[table][2].split()
        for side, keys, rows in ((0, removed, a), (1, added, b)):
            for key in keys: groups[_signature(rows[key], key_fields)][side].append(key)
        paired = set()
        for signature in sorted(groups, key=repr):
            old, new = groups[signature]
            if old and new:
                unique = len(old) == len(new) == 1
                for side, keys in (('baseline', old), ('candidate', new)):
                    for key in keys:
                        evidence.add('possible-identifier-change' if unique else 'ambiguous-change', table, key,
                                     ambiguity=True, side=side, baselineCandidateCount=len(old), candidateCandidateCount=len(new))
                        paired.add((side, key))
        if removed and added and (len(paired) < len(removed) + len(added)):
            evidence.add('ambiguous-change', table, ambiguity=True, reason='unmatched-identifiers-or-reference-chain',
                         baselineCandidateCount=len(removed), candidateCandidateCount=len(added))
    if table == 'stop_times':
        def patterns(rows):
            groups = defaultdict(list)
            for key, row in sorted(rows.items()): groups[row['trip_id']].append((row['stop_sequence'], row.get('stop_id')))
            return groups
        old, new = patterns(a), patterns(b)
        for trip in sorted(old.keys() & new.keys()):
            if ([v[0] for v in old[trip]] != [v[0] for v in new[trip]] or
                    ([v[1] for v in old[trip]] != [v[1] for v in new[trip]] and Counter(v[1] for v in old[trip]) == Counter(v[1] for v in new[trip]))):
                evidence.add('stop-order-changed', table, (trip,))
    partial = bool(left['issues'] or right['issues'])
    return {'table': table, 'coverage': 'partial' if partial else 'complete',
            'semanticStatus': 'indeterminate' if partial else 'changed' if any(counts.values()) else 'equivalent',
            'counts': dict(sorted(counts.items())), 'baselineRecords': len(a), 'candidateRecords': len(b)}


def _calendar(left, right, evidence):
    periods = {'baseline': left['period'], 'candidate': right['period']}
    result = {'feedPeriods': periods, 'unionRanges': sorted(set(p for p in periods.values() if p)),
              'status': 'complete', 'evaluatedServiceDates': 0, 'changedServiceDates': 0,
              'outsideCommonPeriod': 'not-evaluated'}
    if not all(periods.values()):
        result.update(status='partial', errorCode='feed_period_unavailable'); return result
    start = max(p[0] for p in periods.values()); end = min(p[1] for p in periods.values())
    result['commonPeriod'] = [start, end] if start <= end else None
    if start > end: result['status'] = 'no-common-period'; return result
    def indexes(side):
        calendars = {row['service_id']: row for row in side['tables']['calendar']['rows'].values()}
        exceptions = {(row['service_id'], row['date']): row['exception_type'] for row in side['tables']['calendar_dates']['rows'].values()}
        services = set(calendars) | {key[0] for key in exceptions}
        services.update(r['service_id'] for r in side['tables']['trips']['rows'].values())
        return calendars, exceptions, services
    a, b = indexes(left), indexes(right); services = sorted(a[2] | b[2])
    start_day, end_day = date.fromisoformat(start), date.fromisoformat(end)
    days = (end_day - start_day).days + 1
    if days > MAX_CALENDAR_DAYS or days * len(services) > MAX_SERVICE_DATES:
        result.update(status='partial', errorCode='calendar_evaluation_limit', requestedDays=days,
                      requestedServiceDates=days*len(services)); return result
    weekdays = 'monday tuesday wednesday thursday friday saturday sunday'.split()
    def active(index, service, day):
        cal, exceptions, _ = index; text = day.isoformat()
        if (service, text) in exceptions:
            value = exceptions[service, text]; return value == 1 if value in {1, 2} else None
        row = cal.get(service)
        if row is None or not row['start_date'] <= text <= row['end_date']: return False
        flag = row[weekdays[day.weekday()]]; return flag == 1 if flag in {0, 1} else None
    unknown = 0
    for service in services:
        for offset in range(days):
            day = start_day + timedelta(days=offset); old, new = active(a, service, day), active(b, service, day)
            if old is None or new is None: unknown += 1; continue
            result['evaluatedServiceDates'] += 1
            if old != new:
                result['changedServiceDates'] += 1
                evidence.add('service-date-added' if new else 'service-date-removed', 'calendar-effective', (service, day.isoformat()))
    if unknown: result.update(status='partial', errorCode='calendar_value_unsupported', unknownServiceDates=unknown)
    return result


def _service_candidates(left, right, evidence):
    def signatures(side):
        groups = defaultdict(list)
        for table in ('calendar', 'calendar_dates'):
            if side['tables'][table]['issues']: return None
            for row in side['tables'][table]['rows'].values():
                groups[row['service_id']].append((table, _signature(row, ('service_id',))))
        return {service: tuple(sorted(pattern, key=repr)) for service, pattern in groups.items()}
    a, b = signatures(left), signatures(right)
    if a is None or b is None: return
    groups = defaultdict(lambda: [[], []])
    for side, patterns, other in ((0, a, b), (1, b, a)):
        for service in sorted(patterns.keys() - other.keys()): groups[patterns[service]][side].append(service)
    for signature in sorted(groups, key=repr):
        old, new = groups[signature]
        if old and new:
            for side, keys in (('baseline', old), ('candidate', new)):
                for service in keys:
                    evidence.add('possible-identifier-change' if len(old) == len(new) == 1 else 'ambiguous-change',
                                 'service-identity', (service,), ambiguity=True, side=side,
                                 baselineCandidateCount=len(old), candidateCandidateCount=len(new))


def compare_loaded(left, right):
    """Compare compact, validated inputs. Never declares whole GTFS equivalence."""
    started = time.perf_counter(); evidence = Evidence()
    tables = [_compare_table(name, left['tables'][name], right['tables'][name], evidence) for name in TABLES]
    _service_candidates(left, right, evidence)
    calendar = _calendar(left, right, evidence)
    representations = []
    if left['input']['sha256'] != right['input']['sha256'] and left['memberHashes'] == right['memberHashes']:
        representations.append({'kind': 'zip-container-only', 'scope': 'member-bytes'})
    for table in TABLES:
        a, b = left['tables'][table], right['tables'][table]
        if not a['present'] or not b['present']: continue
        if left['memberHashes'][table+'.txt'] == right['memberHashes'][table+'.txt']: continue
        if a['headers'] == b['headers'] and a['cellsDigest'] == b['cellsDigest']:
            x, y = a['csvEvidence'], b['csvEvidence']
            if x['lexicalHeader'] == y['lexicalHeader'] and x['lexicalRows'] == y['lexicalRows']:
                kind = 'csv-record-order-only'
            elif x['orderedCells'] == y['orderedCells']: kind = 'csv-format-only'
            else: kind = 'csv-format-and-record-order'
            representations.append({'table': table, 'kind': kind})
        elif a['rows'] == b['rows']:
            representations.append({'table': table, 'kind': 'normalized-value-representation'})
    for representation in representations: evidence.categories[representation['kind']] += 1
    counts = Counter()
    for table in tables: counts.update(table['counts'])
    counts['effectiveDateChanges'] = calendar['changedServiceDates']
    for table in tables:
        table['detailComplete'] = evidence.truncated == 0
        if evidence.truncated:
            table.update(coverage='partial', semanticStatus='indeterminate')
    return {'sourceId': 'metro.gtfs', 'coverage': 'partial', 'comparisonStatus': 'partial', 'semanticStatus': 'indeterminate',
            'categories': sorted(evidence.categories), 'categoryCounts': dict(sorted(evidence.categories.items())),
            'counts': dict(sorted(counts.items())), 'findings': evidence.findings, 'ambiguities': evidence.ambiguities,
            'tableResults': tables + [{'table': name, 'coverage': 'not-evaluated'} for name in NOT_EVALUATED],
            'calendarEvaluation': calendar, 'representations': representations, 'loaderIssues': {'baseline': left['issues'], 'candidate': right['issues']},
            'notEvaluated': list(NOT_EVALUATED), 'truncated': evidence.truncated > 0, 'omittedDetails': evidence.truncated,
            'totalDetails': evidence.total, 'detailLimit': MAX_DETAILS,
            'errorCodes': (['detail_limit_reached'] if evidence.truncated else []) + ([calendar['errorCode']] if 'errorCode' in calendar else []),
            'timings': {'baselineParseSeconds': left['parseSeconds'], 'candidateParseSeconds': right['parseSeconds'],
                        'compareSeconds': time.perf_counter() - started}}


def compare_gtfs(baseline_store, candidate_store, baseline_source_dir, candidate_source_dir):
    started = time.perf_counter()
    try:
        stores = [load_store_contract(p) for p in (baseline_store, candidate_store)]
        # Reuse all seven byte bindings and existing six-source ODPT comparison.
        result = compare_train_timetables(baseline_store, candidate_store, baseline_source_dir, candidate_source_dir)
        for role, store in zip(('baseline', 'candidate'), stores):
            for field in ('snapshotId', 'contentFingerprint'):
                if result[role + field[0].upper() + field[1:]] != store['snapshot'][field]: loader.fail('store_changed_during_comparison')
        if result['comparisonStatus'] == 'failed': loader.fail('source_input_validation_failed')
        signatures = {}
        for side, (directory, store) in enumerate(zip((baseline_source_dir, candidate_source_dir), stores)):
            _root(directory)
            for record in store['records']:
                raw, identity = _read_bytes(directory / SOURCE_FILES[record['sourceId']])
                signature = (hashlib.sha256(raw).hexdigest(), len(raw))
                if signature != (record['artifact']['sha256'], record['artifact']['sizeBytes']): loader.fail('source_bytes_mismatch')
                signatures[side, record['sourceId']] = (signature, identity)
        parsed = []
        for directory, store in zip((baseline_source_dir, candidate_source_dir), stores):
            record = next(r for r in store['records'] if r['sourceId'] == 'metro.gtfs')
            parsed.append(_compact(directory / SOURCE_FILES['metro.gtfs'], record))
        gtfs = compare_loaded(*parsed); del parsed
        gtfs['inputBytesStatus'] = {'baseline': 'verified', 'candidate': 'verified'}
        for side, (directory, store_path) in enumerate(zip((baseline_source_dir, candidate_source_dir), (baseline_store, candidate_store))):
            _root(directory)
            for sid in sorted(SOURCE_FILES):
                raw, identity = _read_bytes(directory / SOURCE_FILES[sid])
                if ((hashlib.sha256(raw).hexdigest(), len(raw)), identity) != signatures[side, sid]: loader.fail('source_changed_during_comparison')
            if stores[side] != load_store_contract(store_path): loader.fail('store_changed_during_comparison')
        result['sourceResults'] = [gtfs if r['sourceId'] == 'metro.gtfs' else r for r in result['sourceResults']]
        result['notEvaluated'] = [x for x in result['notEvaluated'] if x != 'metro.gtfs'] + ['metro.gtfs/' + t for t in NOT_EVALUATED]
        result['categories'] = sorted({c for r in result['sourceResults'] for c in r['categories']})
        result['counts'] = {'gtfs': gtfs['counts'], 'odpt': {r['sourceId']: r['counts'] for r in result['sourceResults'] if r['sourceId'] != 'metro.gtfs'}}; result['coverage'] = 'partial'
        result['findings'] = gtfs['findings']; result['ambiguities'] = gtfs['ambiguities']
        result['timings'] = {**gtfs['timings'], 'totalSeconds': time.perf_counter() - started,
                             'peakRSSPlatformUnits': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
        return result
    except (StoreError, SemanticDiffError) as exc: loader.fail(exc.code)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('baseline-store', 'candidate-store', 'baseline-source-dir', 'candidate-source-dir'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = compare_gtfs(args.baseline_store, args.candidate_store, args.baseline_source_dir, args.candidate_source_dir)
        gtfs = next(r for r in result['sourceResults'] if r['sourceId'] == 'metro.gtfs')
        incomplete = gtfs['truncated'] or gtfs['calendarEvaluation']['status'] == 'partial'
        print('compare_gtfs=' + ('partial' if incomplete else 'PASS') + ' coverage=partial semantic_status=indeterminate')
        for table in gtfs['tableResults']:
            print('table=' + table['table'] + ' coverage=' + table['coverage'] + ' counts=' + json.dumps(table.get('counts', {}), sort_keys=True))
        print('categories=' + ','.join(gtfs['categories']))
        print('calendar_status=' + gtfs['calendarEvaluation']['status'])
        print(f"details={len(gtfs['findings']) + len(gtfs['ambiguities'])} omitted={gtfs['omittedDetails']}")
        print('errors=' + (','.join(gtfs['errorCodes']) or 'none'))
        print('timings=' + json.dumps(result['timings'], sort_keys=True))
        return 2 if incomplete else 0
    except loader.GTFSError as exc:
        print('compare_gtfs=FAIL error=' + exc.code); return 2


if __name__ == '__main__': raise SystemExit(main())
