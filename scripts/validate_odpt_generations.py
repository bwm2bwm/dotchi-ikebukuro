#!/usr/bin/env python3
"""Independent offline transition validator. Requires a trusted previous tree digest.

The digest must come from a prior validated/published record. Computing it from
an untrusted download does not authenticate that download. No remote CAS/deploy.
"""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys
import subprocess

sys.dont_write_bytecode = True
import odpt_release_contract as c
import odpt_generation_contract as g
from validate_odpt_public_site import validate_artifact as validate_new_site


def verify_inputs(*, previous, expected_previous_digest, operation, expected_previous_release_id=None,
                  new_release=None, validation_inputs=None, rollback_release_id=None, now=None, **_):
    c.hash_value(expected_previous_digest)
    clock = now or datetime.now(timezone.utc)
    c.require(clock.tzinfo is not None, 'clock_invalid')
    old = g.read_tree(previous)
    c.require(old['digest'] == expected_previous_digest, 'previous_artifact_changed')
    c.require(operation in {'initial', 'update', 'rollback'}, 'operation_invalid')
    if operation == 'initial':
        c.require(not old['files'] and not old['dirs'] and expected_previous_release_id is None,
                  'initial_requires_explicit_empty_snapshot')
        old['manifest'] = None
    else:
        g.release_id(expected_previous_release_id)
        old = g.verify_tree(previous, clock, historical=True)
        c.require(old['digest'] == expected_previous_digest and 'publication' in old['manifest'], 'published_previous_required')
        c.require(old['manifest']['releaseId'] == expected_previous_release_id, 'previous_release_id_mismatch')
    if now is not None and old['manifest'] is not None:
        c.require(old['manifest']['metadata']['evidenceKind'] == 'synthetic', 'test_clock_requires_synthetic')
    new = None
    if operation in {'initial', 'update'}:
        c.require(new_release is not None and isinstance(validation_inputs, dict), 'new_validation_inputs_required')
        c.exact(validation_inputs, {'candidate', 'source', 'approval', 'contact_url',
                                   'expected_candidate_digest', 'expected_source_fingerprint'})
        validate_new_site(new_release, now=now, **validation_inputs)
        new = g.verify_tree(new_release, clock)
        c.require('publication' not in new['manifest'] and new['manifest']['retainedReleases'] == [], 'clean_new_release_required')
    else:
        c.require(new_release is None and validation_inputs is None, 'rollback_uses_archive_only')
        g.release_id(rollback_release_id)
    return old, new, clock


def expected_files(manifest, old, new):
    """Every output byte must originate from the validated new or anchored old tree."""
    rid = manifest['releaseId']
    if new is not None:
        current_files = new['files']
        assets = {name: current_files[name] for name in c.SITE_ASSETS}
    else:
        current_files = old['files']
        assets = {name: current_files[f'releases/{rid}/assets/{name}'] for name in c.SITE_ASSETS}
    files = {**assets, 'manifest.json': c.canonical(manifest)}
    for name in c.STATION_FILES.values():
        path = f'releases/{rid}/{name}'; files[path] = current_files[path]
    for entry in manifest['retainedReleases']:
        rid = entry['releaseId']
        for name in c.STATION_FILES.values():
            path = f'releases/{rid}/{name}'; files[path] = old['files'][path]
        is_old_current = rid == old['manifest']['releaseId']
        for name in c.SITE_ASSETS:
            path = f'releases/{rid}/assets/{name}'
            files[path] = old['files'][name if is_old_current else path]
    return files


def validate_transition(artifact, *, prune_release_ids=(), **inputs):
    old, new, clock = verify_inputs(**inputs)
    actual = g.verify_tree(artifact, clock)
    assembled = c.timestamp(actual['manifest']['publication']['assembledAt'])
    c.require(clock - assembled <= g.DELETE_SAFETY_MARGIN, 'assembly_stale_rebuild_required')
    if old['manifest'] is not None:
        c.require(assembled >= c.timestamp(old['manifest']['publication']['assembledAt']), 'transition_time_reversed')
    planned = g.plan_manifest(old['manifest'], None if new is None else new['manifest'],
        operation=inputs['operation'], now=assembled, previous_digest=inputs['expected_previous_digest'],
        rollback_release_id=inputs.get('rollback_release_id'), prune_release_ids=prune_release_ids)
    c.require(actual['manifest'] == planned, 'transition_manifest_mismatch')
    c.require(actual['files'] == expected_files(planned, old, new), 'transition_bytes_mismatch')
    c.require(g.read_tree(inputs['previous'])['digest'] == old['digest'], 'previous_artifact_changed')
    if new is not None:
        c.require(g.read_tree(inputs['new_release'])['digest'] == new['digest'], 'new_release_changed')
    return dict(releaseId=planned['releaseId'], artifactDigest=actual['digest'],
        previousArtifactDigest=old['digest'], retainedReleaseIds=[e['releaseId'] for e in planned['retainedReleases']],
        prunedReleaseIds=planned['publication']['prunedReleaseIds'], operation=inputs['operation'],
        bytes=actual['bytes'], files=len(actual['files']), assembledAt=planned['publication']['assembledAt'],
        deploymentPreflightRequired=True, deploymentPerformed=False)


def cli_parser(description):
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument('--operation', choices=['initial', 'update', 'rollback'], required=True)
    parser.add_argument('--previous', type=Path, required=True, help='read-only local snapshot; initial requires an existing empty directory')
    parser.add_argument('--expected-previous-digest', required=True)
    parser.add_argument('--expected-previous-release-id')
    parser.add_argument('--new-release', type=Path)
    parser.add_argument('--validation-inputs', type=Path, help='private JSON with Phase 3A original-input paths and expected digests')
    parser.add_argument('--rollback-release-id')
    parser.add_argument('--prune-release-id', action='append', default=[], dest='prune_release_ids')
    parser.add_argument('--evaluated-at', help='explicit synthetic test clock only; normal use reads UTC now')
    return parser


def cli_inputs(args):
    values = vars(args).copy()
    evaluated = values.pop('evaluated_at')
    values['now'] = c.timestamp(evaluated) if evaluated else None
    if values['validation_inputs'] is not None:
        context = c.load_json(c.read_file(values['validation_inputs']))
        for key in ('candidate', 'source', 'approval'):
            context[key] = Path(context[key])
        values['validation_inputs'] = context
    return values


def main():
    parser = cli_parser(__doc__); parser.add_argument('--artifact', type=Path, required=True)
    try:
        values = cli_inputs(parser.parse_args()); artifact = values.pop('artifact')
        print(c.canonical(validate_transition(artifact, **values)).decode()); return 0
    except (ValueError, OSError, KeyError, TypeError, c.v2.V2Error, c.qa.QAError, subprocess.SubprocessError):
        print('v2 generation validation failed', file=sys.stderr); return 1


if __name__ == '__main__':
    raise SystemExit(main())
