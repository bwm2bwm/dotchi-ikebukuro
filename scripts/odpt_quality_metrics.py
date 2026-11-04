#!/usr/bin/env python3
"""Private, read-only single-Snapshot generator/v2 basic metrics (in memory only)."""
from __future__ import annotations

import argparse
import collections
import copy
import hashlib
import json
import resource
import sys
import time
from datetime import date
from pathlib import Path

# The existing generator and projector use script-local imports.
if __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from . import odpt_quality_input as quality
else:
    import odpt_quality_input as quality
import odpt_public_v2 as v2
from odpt_itinerary import FeedDateError, ItineraryGenerator

METRIC_UNITS = {
    'G': 'generated-rows', 'C': 'candidate-rows', 'E': 'excluded-rows',
    'primaryDirectCount': 'candidate-rows', 'primaryTransferCount': 'candidate-rows',
    'exclusionReasonCounts': 'excluded-rows-by-reason',
    'alternativeDirectRowCount': 'generated-rows', 'bestTransferRowCount': 'generated-rows',
    'validTransferPairCount': 'transfer-pairs',
}
NOT_EVALUATED = [
    'matcher-details', 'unknown-warning-details', 'route-coverage-details',
    'display-model', 'browser-runtime', 'quality-diff', 'freshness',
    'application-period', 'publication-eligibility', 'cross-source-consistency',
    'phase2b-opaque-and-auxiliary-semantics',
]


def _metric(metric_id, dimensions, value=None, availability='known', reasons=(), evidence=()):
    return {'metricId': metric_id, 'dimensions': dict(dimensions), 'availability': availability,
            'value': value if availability == 'known' else None, 'unit': METRIC_UNITS[metric_id],
            'reasonCodes': sorted(set(reasons)), 'evidenceRefs': list(evidence)}


def _empty_cell(dimensions, availability, reason):
    return [_metric(m, dimensions, availability=availability, reasons=[reason])
            for m in sorted(METRIC_UNITS)]


def _consistency(metrics):
    """Check observed values; never repair counts or derive exclusion measurements."""
    by_id = {m['metricId']: m for m in metrics}
    checks = []
    for code, names, equal in (
        ('G_equals_C_plus_E', ('G', 'C', 'E'), lambda v: v[0] == v[1] + v[2]),
        ('C_equals_primary_direct_plus_transfer', ('C', 'primaryDirectCount', 'primaryTransferCount'),
         lambda v: v[0] == v[1] + v[2]),
        ('E_equals_observed_reason_counts', ('E', 'exclusionReasonCounts'),
         lambda v: v[0] == sum(v[1].values())),
    ):
        available = all(by_id[m]['availability'] == 'known' for m in names)
        checks.append({'checkId': code, 'dimensions': dict(metrics[0]['dimensions']),
                       'status': ('PASS' if equal([by_id[m]['value'] for m in names]) else 'FAIL')
                       if available else 'not-evaluated'})
    return checks


def measure_cell(rows, dimensions):
    """Use actual generator DTO fields and the existing v2 row projection/classifier.

    Alternatives/pairs cover G, including excluded rows. Primary counts cover C.
    No matcher diagnostics, route coverage, payloads or public gate are evaluated.
    """
    metrics = [_metric('G', dimensions, len(rows), evidence=['generator.generate'])]
    for name, field in (('alternativeDirectRowCount', 'direct_alternative'),
                        ('bestTransferRowCount', 'best_transfer_alternative'),
                        ('validTransferPairCount', 'transfer_candidates_count')):
        if any(not hasattr(row, field) for row in rows):
            metrics.append(_metric(name, dimensions, availability='unavailable',
                                   reasons=['generator_field_unavailable'], evidence=['generator.' + field]))
        elif name == 'validTransferPairCount' and any(
                not v2._safe_nonnegative_int(getattr(row, field)) for row in rows):
            metrics.append(_metric(name, dimensions, availability='unavailable',
                                   reasons=['generator_pair_count_invalid'], evidence=['generator.' + field]))
        else:
            value = (sum(getattr(row, field) for row in rows) if name == 'validTransferPairCount'
                     else sum(getattr(row, field) is not None for row in rows))
            metrics.append(_metric(name, dimensions, value, evidence=['generator.' + field]))

    projected_ids = ('C', 'E', 'primaryDirectCount', 'primaryTransferCount', 'exclusionReasonCounts')
    try:
        candidates = excluded = direct = transfer = 0
        reasons = {key: 0 for key in v2.EXCLUSION_REASONS}
        signatures, ids = set(), set()
        for result in rows:
            row = v2._public_departure(result)
            if row is None:
                reason, _ = v2._exclusion_detail(result)
                reasons[reason] += 1
                excluded += 1
            else:
                # Same duplicate/collision checks as the existing station projector.
                signature = v2._journey_signature(row)
                row_id = v2.public_id(dimensions['stationId'], dimensions['serviceDate'], row)
                if signature in signatures:
                    raise v2.V2Error('duplicate_public_journey')
                if row_id in ids:
                    raise v2.V2Error('public_id_collision')
                signatures.add(signature)
                ids.add(row_id)
                candidates += 1
                direct += row['primary']['kind'] == 'direct'
                transfer += row['primary']['kind'] == 'transfer'
        values = (candidates, excluded, direct, transfer, reasons)
        metrics.extend(_metric(name, dimensions, value, evidence=['v2._public_departure', 'v2._exclusion_detail'])
                       for name, value in zip(projected_ids, values))
    except Exception as exc:
        # No partial projection counts masquerade as a complete cell. Never emit raw exceptions.
        reason = exc.code if isinstance(exc, v2.V2Error) else 'v2_projection_failed'
        metrics.extend(_metric(name, dimensions, availability='failed', reasons=[reason])
                       for name in projected_ids)
    return sorted(metrics, key=lambda m: m['metricId'])


def _inventory(store, source_dir):
    """Bind byte hashes and stable file identities, including store serialization."""
    quality.load_store_contract(store)
    files = [('source', name, source_dir / name) for name in sorted(quality.SOURCE_FILES.values())]
    files += [('store', 'snapshot.json', store / 'snapshot.json')]
    files += [('store', 'sources/' + sid + '.json', store / 'sources' / (sid + '.json'))
              for sid in sorted(quality.SOURCE_FILES)]
    entries, identities = [], []
    for role, name, path in files:
        raw, identity = quality._read(path)
        entries.append({'role': role, 'path': name, 'sha256': hashlib.sha256(raw).hexdigest(),
                        'sizeBytes': len(raw)})
        identities.append(identity)
    return entries, identities


def collect_metrics(store, source_dir, *, context=None, engine=None, root=quality.ROOT):
    """Return descriptive partial-scope collection; never write the report or inputs.

    Frozen engine/context can be supplied by an in-process caller. The CLI builds
    current evidence and the initial 48-cell context. Global binding failures
    invalidate values; local cell failures preserve other confirmed metrics.
    """
    report = {'contract': 'odpt-itinerary-quality-collection', 'schemaVersion': 1,
              'profile': dict(quality.PROFILE), 'snapshotId': None, 'contentFingerprint': None,
              'evaluationContext': None, 'contextFingerprint': None, 'engineFingerprint': None,
              'metrics': [], 'checks': {'consistency': []}, 'findings': [],
              'notEvaluated': list(NOT_EVALUATED), 'collectionStatus': 'failed',
              'basicMetricsStatus': 'failed', 'reasonCodes': []}
    before = None
    try:
        engine = copy.deepcopy(engine) if engine is not None else quality.build_engine(root)
        quality._validate_engine(engine)
        context = copy.deepcopy(context) if context is not None else quality.initial_context(engine['engineFingerprint'])
        # Freeze all 15 physical inputs before validation as well as generation.
        before = _inventory(store, source_dir)
        def validate():
            return quality.validate_inputs(store, store, source_dir, source_dir,
                                           context, context, engine, engine, root=root)
        start = validate()
        report['checks']['inputStart'] = start
        report.update(snapshotId=start['baselineSnapshotId'], contentFingerprint=start['baselineContentFingerprint'])
        if start['comparisonReadiness'] != 'ready':
            report['reasonCodes'] = start['reasonCodes']
        else:
            context = quality.normalize_context(context)
            report.update(evaluationContext=context, contextFingerprint=context['contextFingerprint'],
                          engineFingerprint=engine['engineFingerprint'])
            for station in context['stationIds']:
                generator = None
                try:
                    generator = ItineraryGenerator(
                        gtfs_zip=source_dir / 'TokyoMetro-Train-GTFS.zip', odpt_dir=source_dir,
                        destination_station_id=station,
                        min_transfer_seconds=context['minimumWaitSeconds'],
                        max_transfer_seconds=context['maximumWaitSeconds'])
                except Exception:
                    pass
                for day in context['serviceDates']:
                    availability, reason, rows = 'known', None, None
                    if generator is None:
                        availability, reason = 'failed', 'generator_input_invalid'
                    else:
                        try:
                            rows = generator.generate(date.fromisoformat(day))
                            if any(str(r.route_id) not in context['routeIds'] for r in rows):
                                raise ValueError('unexpected route')
                        except FeedDateError:
                            availability, reason = 'out-of-range', 'service_date_outside_feed'
                        except Exception:
                            availability, reason = 'failed', 'generator_execution_failed'
                    for route in context['routeIds']:
                        dims = {'snapshotId': report['snapshotId'], 'serviceDate': day,
                                'stationId': station, 'routeId': route}
                        cell = (measure_cell([r for r in rows if str(r.route_id) == route], dims)
                                if availability == 'known' else _empty_cell(dims, availability, reason))
                        report['metrics'].extend(cell)
                        report['checks']['consistency'].extend(_consistency(cell))
                # Release a station's parsed feed before constructing the next one.
                del generator
            end = validate()
            report['checks']['inputEnd'] = end
            report['reasonCodes'].extend(end['reasonCodes'])
            if end['comparisonReadiness'] == 'ready':
                report['collectionStatus'] = 'partial'
        after = _inventory(store, source_dir)
        same = before == after
        report['checks']['inputImmutability'] = {
            'status': 'PASS' if same else 'FAIL', 'sourceFileCount': 7, 'storeFileCount': 8,
            'before': before[0], 'after': after[0]}
        if not same:
            report['reasonCodes'].append('inputs_changed_during_collection')
    except (quality.QualityInputError, quality.StoreError) as exc:
        report['reasonCodes'].append(exc.code)
        report['checks']['inputImmutability'] = {'status': 'not-confirmed'}
        report['failureCategory'] = getattr(exc, 'category',
            'unavailable' if exc.code == 'store_not_found' else 'invalid')

    if report['reasonCodes']:
        report['collectionStatus'] = 'failed'
        # Values from a changed input/engine cannot be confirmed as Snapshot metrics.
        for metric in report['metrics']:
            metric.update(availability='failed', value=None,
                          reasonCodes=sorted(set(metric['reasonCodes'] + report['reasonCodes'])))
        for check in report['checks']['consistency']:
            check['status'] = 'not-evaluated'
    report['metrics'].sort(key=lambda m: tuple(m['dimensions'][k] for k in ('serviceDate', 'stationId', 'routeId')) + (m['metricId'],))
    report['checks']['consistency'].sort(key=lambda c: tuple(c['dimensions'][k] for k in ('serviceDate', 'stationId', 'routeId')) + (c['checkId'],))
    report['findings'] = [copy.deepcopy(c) for c in report['checks']['consistency'] if c['status'] == 'FAIL']
    report['findings'].extend({'code': code} for code in sorted(set(report['reasonCodes'])))
    if report['collectionStatus'] != 'failed':
        report['basicMetricsStatus'] = ('collected' if not report['findings'] and
            all(m['availability'] == 'known' for m in report['metrics']) else 'partial')
    report['reasonCodes'] = sorted(set(report['reasonCodes']))
    return report


def summarize(report):
    totals, known_cells = {}, {}
    for name in sorted(METRIC_UNITS):
        values = [m['value'] for m in report['metrics'] if m['metricId'] == name and m['availability'] == 'known']
        known_cells[name] = len(values)
        totals[name] = ({key: sum(v[key] for v in values) for key in sorted(v2.EXCLUSION_REASONS)}
                        if name == 'exclusionReasonCounts' else sum(values)) if values else None
    cells = collections.defaultdict(list)
    for metric in report['metrics']:
        dims = metric['dimensions']
        cells[tuple(dims[k] for k in ('serviceDate', 'stationId', 'routeId'))].append(metric)
    return {'rowInstanceTotals': totals, 'knownCellCounts': known_cells, 'cellCount': len(cells),
            'unevaluableCellCount': sum(any(m['availability'] != 'known' for m in cell) for cell in cells.values()),
            'consistency': dict(sorted(collections.Counter(c['status'] for c in report['checks']['consistency']).items()))}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--store', type=Path, required=True)
    parser.add_argument('--source-dir', type=Path, required=True)
    args = parser.parse_args(argv)
    started = time.perf_counter()
    report = collect_metrics(args.store, args.source_dir)
    context = report['evaluationContext']
    print('profile=' + quality.PROFILE['id'] + ' version=' + quality.PROFILE['version'])
    if context:
        print('service_dates=' + ','.join(context['serviceDates']))
        print('origin=Ikebukuro stations=' + ','.join(context['stationIds']) + ' routes=' + ','.join(context['routeIds']))
    print('summary=' + json.dumps(summarize(report), sort_keys=True))
    print('not_evaluated=' + ','.join(report['notEvaluated']))
    print('collection_status=' + report['collectionStatus'] + ' basic_metrics_status=' + report['basicMetricsStatus'])
    print('input_immutability=' + report['checks'].get('inputImmutability', {}).get('status', 'not-confirmed'))
    print('reasons=' + (','.join(report['reasonCodes']) or 'none'))
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    print(f'elapsed_seconds={time.perf_counter() - started:.3f} peak_rss_bytes={rss if sys.platform == "darwin" else rss * 1024}')
    if report['collectionStatus'] != 'failed':
        return 0 if report['basicMetricsStatus'] == 'collected' else 2
    statuses = [report['checks'][k]['comparisonReadiness'] for k in ('inputStart', 'inputEnd') if k in report['checks']]
    statuses.append(report.get('failureCategory'))
    if 'invalid' in statuses: return 3
    if 'unavailable' in statuses: return 4
    return 2 if 'incomparable' in statuses else 3


if __name__ == '__main__':
    raise SystemExit(main())
