#!/usr/bin/env python3
"""Private offline entry point for 2A/2B/2C. Never persists QA output or raw copies."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path

if __package__:
    from . import odpt_evaluation_input as inputs
    from . import odpt_source_diff as basic
    from . import odpt_semantic_compare as semantic
    from . import odpt_quality_metrics as metrics
    from . import odpt_quality_diff as quality_diff
    from . import odpt_display_diff as display_diff
    from . import odpt_dom_metrics as dom
else:
    import odpt_evaluation_input as inputs
    import odpt_source_diff as basic
    import odpt_semantic_compare as semantic
    import odpt_quality_metrics as metrics
    import odpt_quality_diff as quality_diff
    import odpt_display_diff as display_diff
    import odpt_dom_metrics as dom


def _bind(store, raw_dir):
    loaded = inputs.load_input(store)
    metrics.quality._root(raw_dir)
    for rec in loaded['records']:
        raw, _ = inputs.fetch._stable_read(raw_dir / inputs.SOURCE_FILES[rec['sourceId']], rec['sourceId'])
        if (hashlib.sha256(raw).hexdigest(), len(raw)) != (rec['artifact']['sha256'], rec['artifact']['sizeBytes']):
            raise inputs.StoreError('evaluation_raw_mismatch')
    return loaded, metrics._inventory(store, raw_dir)


def evaluate(baseline_store, baseline_raw, candidate_batch, *, stage,
             service_dates=None, observation_instant=None, dom_station_ids=None):
    """Reuse existing engines; both sides are pinned and revalidated after evaluation."""
    if stage not in ('2a', '2b', '2c'):
        raise ValueError('evaluation_stage_invalid')
    paths = [(Path(baseline_store), Path(baseline_raw)),
             (Path(candidate_batch), Path(candidate_batch) / 'raw')]
    # Require a sealed fetch candidate, not an arbitrary strict store.
    candidate = inputs.load_fetch_batch(paths[1][0])
    before = [_bind(*pair) for pair in paths]
    if candidate != before[1][0]:
        raise inputs.StoreError('candidate_changed_before_evaluation')
    result = {'contract': 'dotchi.odpt.fetch-evaluation', 'schemaVersion': 1,
              'stage': stage, 'publicationApproved': False, 'applicationPeriod': None,
              'crossSourceConsistency': 'not-evaluated', 'publicationEligibility': 'not-assessed',
              'baselineSnapshotId': before[0][0]['snapshot']['snapshotId'],
              'candidateSnapshotId': candidate['snapshot']['snapshotId'], 'reports': {}}
    if stage == '2a':
        result['reports']['basic'] = basic.compare_stores(paths[0][0], paths[1][0])
    elif stage == '2b':
        result['reports']['semantic'] = semantic.compare_sources(paths[0][0], paths[1][0], paths[0][1], paths[1][1])
        if result['reports']['semantic']['comparisonStatus'] == 'failed':
            raise inputs.StoreError('semantic_evaluation_failed')
    else:
        if not service_dates or not observation_instant or not dom_station_ids:
            raise ValueError('explicit_evaluation_scope_required')
        if (not isinstance(dom_station_ids, (list, tuple))
                or len(set(dom_station_ids)) != len(dom_station_ids)
                or not set(dom_station_ids) <= set(metrics.quality.STATIONS)):
            raise ValueError('dom_stations_invalid')
        dom_station_ids = [s for s in metrics.quality.STATIONS if s in dom_station_ids]
        engine = metrics.quality.build_engine()
        q = metrics.quality.initial_context(engine['engineFingerprint'])
        q['serviceDates'] = list(service_dates)
        q = metrics.quality.normalize_context(q, seal=True)
        d = dom.display.create_context(q, [observation_instant])
        result['scope'] = {'qualityContext': q, 'displayContext': d,
                           'domStationIds': list(dom_station_ids), 'engine': engine}
        reports = result['reports']
        reports['quality'] = quality_diff.compare_quality(paths[0][0], paths[1][0], paths[0][1], paths[1][1], context=q, engine=engine)
        if reports['quality']['comparisonStatus'] == 'failed' or reports['quality']['inputReadiness'] != 'ready':
            raise inputs.StoreError('quality_evaluation_failed')
        reports['display'] = display_diff.compare_display_models(paths[0][0], paths[1][0], paths[0][1], paths[1][1], quality_context=q, display_context=d, engine=engine)
        if reports['display']['comparisonStatus'] == 'failed' or reports['display']['inputReadiness'] != 'ready':
            raise inputs.StoreError('display_evaluation_failed')
        for role, (store, raw) in zip(('baselineDom', 'candidateDom'), paths):
            reports[role] = dom.collect_dom_qa(store, raw, quality_context=q, display_context=d,
                                             engine=engine, station_ids=list(dom_station_ids))
            if reports[role]['domQaStatus'] in ('failed', 'incomparable') or reports[role]['inputReadiness'] != 'ready':
                raise inputs.StoreError('dom_evaluation_failed')
        if engine != metrics.quality.build_engine():
            raise inputs.StoreError('evaluation_engine_changed')
    if before != [_bind(*pair) for pair in paths]:
        raise inputs.StoreError('evaluation_input_changed')
    result['inputImmutability'] = 'PASS'
    return result


def main(argv=None):
    parser = inputs.fetch.SafeArgumentParser(description=__doc__)
    for name in ('baseline-store', 'baseline-raw', 'candidate-batch'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--stage', choices=('2a', '2b', '2c'), required=True)
    parser.add_argument('--service-date', action='append')
    parser.add_argument('--observation-instant', help='fixed UTC YYYY-MM-DDTHH:MM:SSZ')
    parser.add_argument('--dom-station', action='append', choices=metrics.quality.STATIONS)
    args = parser.parse_args(argv)
    try:
        result = evaluate(args.baseline_store, args.baseline_raw, args.candidate_batch, stage=args.stage,
                          service_dates=args.service_date, observation_instant=args.observation_instant,
                          dom_station_ids=args.dom_station)
        # Summary only: never print source fields, journeys, local paths or private report bodies.
        summary = {'stage': result['stage'], 'inputImmutability': result['inputImmutability'],
                   'publicationApproved': False, 'applicationPeriod': None,
                   'crossSourceConsistency': 'not-evaluated', 'publicationEligibility': 'not-assessed'}
        for name, report in result['reports'].items():
            summary[name] = {key: report[key] for key in ('overallBasicStatus', 'comparisonStatus',
                            'semanticStatus', 'coverage', 'qualityDiffStatus', 'displayDiffStatus', 'domQaStatus') if key in report}
        if 'scope' in result:
            summary['scope'] = {key: result['scope'][key] for key in ('qualityContext', 'displayContext', 'domStationIds')}
        print(json.dumps(summary, sort_keys=True))
        # Partial/indeterminate retains its existing meaning; never collapse it to PASS.
        return 2 if any(r.get('comparisonStatus') == 'partial' or r.get('domQaStatus') == 'partial'
                        or r.get('overallBasicStatus') == 'unavailable'
                        for r in result['reports'].values()) else 0
    except Exception:
        print('fetch_evaluation=stopped; publication_eligibility=not-assessed')
        return 2


if __name__ == '__main__': raise SystemExit(main())
