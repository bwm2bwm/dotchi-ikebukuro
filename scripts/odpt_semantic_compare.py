#!/usr/bin/env python3
"""Private seven-source semantic comparison; no persistence or publication gate."""
import argparse
import json
from pathlib import Path

if __package__:
    from .odpt_gtfs_semantic_diff import compare_gtfs, loader
else:
    from odpt_gtfs_semantic_diff import compare_gtfs, loader


def compare_sources(baseline_store, candidate_store, baseline_source_dir, candidate_source_dir):
    return compare_gtfs(baseline_store, candidate_store, baseline_source_dir, candidate_source_dir, all_tables=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('baseline-store', 'candidate-store', 'baseline-source-dir', 'candidate-source-dir'):
        parser.add_argument('--' + flag, type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = compare_sources(args.baseline_store, args.candidate_store, args.baseline_source_dir, args.candidate_source_dir)
        print(f"compare_sources={result['comparisonStatus']} coverage={result['coverage']} semantic_status={result['semanticStatus']}")
        for source in result['sourceResults']:
            print(f"source={source['sourceId']} coverage={source['coverage']} semantic_status={source['semanticStatus']} "
                  f"counts={json.dumps(source['counts'], sort_keys=True)} categories={','.join(source['categories']) or 'none'} "
                  f"unsupported_fields={len(source['unsupportedFields'])} ambiguities_held={len(source['ambiguities'])} counts_known={source['countsKnown']}")
            print('source=' + source['sourceId'] + ' checks=' + json.dumps(source['checks'], sort_keys=True))
            reasons = sorted(set(source['errorCodes']) | set(source['checks'].get('warnings', [])))
            print('source=' + source['sourceId'] + ' reasons=' + (','.join(reasons) or 'none'))
            if source['sourceId'] == 'metro.gtfs':
                for table in source['tableResults']:
                    print(f"table={table['table']} coverage={table['coverage']} counts={json.dumps(table['counts'], sort_keys=True)} "
                          f"categories={','.join(table['categories']) or 'none'} checks={json.dumps(table['checks'], sort_keys=True)}")
                print(f"gtfs_details_omitted={source['omittedDetails']} calendar_status={source['calendarEvaluation']['status']}")
        print('not_evaluated=' + ','.join(result['notEvaluated']))
        print('cross_source_consistency=not-evaluated')
        print('timings=' + json.dumps(result['timings'], sort_keys=True))
        limits = {'detail_limit_reached', 'calendar_evaluation_limit', 'feed_period_unavailable', 'calendar_value_unsupported'}
        return 2 if result['comparisonStatus'] == 'failed' or limits.intersection(result['errorCodes']) else 0
    except loader.GTFSError as exc:
        print('compare_sources=failed error=' + exc.code)
        return 2


if __name__ == '__main__': raise SystemExit(main())
