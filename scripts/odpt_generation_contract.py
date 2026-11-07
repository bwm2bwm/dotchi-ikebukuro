"""V2 published-generation contracts. Content validation is not deploy permission."""
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
import re

import odpt_release_contract as c
from assemble_public_release import MIN_RETENTION, VALIDITY_GRACE, DELETE_SAFETY_MARGIN, MAX_FILES_DEFAULT
from validate_odpt_public_site import SiteHtml, validate_site_assets

GEN_KEYS = ('releaseId', 'releaseDescriptor', 'metadata', 'serviceDates', 'stations')
GENERATION_CONTRACT = 'dotchi-odpt-generations-v1'


def text_time(value):
    return value.astimezone(timezone.utc).isoformat(timespec='microseconds' if value.microsecond else 'seconds').replace('+00:00', 'Z')


def release_id(value):
    c.require(isinstance(value, str) and re.fullmatch(r'r1-[0-9a-f]{64}', value), 'release_id_invalid')


def clean(generation):
    return dict(schemaVersion=2, artifactKind=c.SITE_KIND, runtimeContract=c.RUNTIME,
                payloadSchemaVersion=2, dataScope=c.SCOPE, retainedReleases=[],
                **{key: generation[key] for key in GEN_KEYS})


def deadline(metadata, retired):
    """Preserve existing 7d + validity/48h guarantees; derive a finite per-generation cap."""
    period = metadata['applicationPeriod']
    start, end = c.timestamp(period['startsAt']), c.timestamp(period['endsAt'])
    feed_end = c.timestamp(metadata['feed']['validThrough'] + 'T00:00:00+09:00') + timedelta(days=1)
    c.require(start < end and retired >= start, 'retirement_time_invalid')
    required = max(retired + MIN_RETENTION, min(end, feed_end) + VALIDITY_GRACE)
    cap = retired + max(MIN_RETENTION, end - start + VALIDITY_GRACE)
    c.require(required <= cap, 'retention_bound_exceeded')
    return required


def validate_history(m, now):
    c.require(m['artifactKind'] == c.SITE_KIND, 'publication_requires_full_site')
    pub = c.exact(m['publication'], {'contract', 'publishedAt', 'assembledAt', 'operation', 'previousReleaseId',
                                   'previousArtifactDigest', 'prunedReleaseIds'})
    c.require(pub['contract'] == GENERATION_CONTRACT, 'generation_contract_unknown')
    published, assembled = c.timestamp(pub['publishedAt']), c.timestamp(pub['assembledAt'])
    c.require(published <= assembled <= now, 'publication_time_invalid')
    c.validate_metadata(m['metadata'], m['serviceDates'], published)
    c.hash_value(pub['previousArtifactDigest'])
    c.require(pub['operation'] in {'initial', 'update', 'rollback'}, 'operation_invalid')
    if pub['operation'] == 'initial':
        c.require(pub['previousReleaseId'] is None and m['retainedReleases'] == []
                  and pub['prunedReleaseIds'] == [], 'initial_state_invalid')
    else:
        release_id(pub['previousReleaseId'])
        c.require(pub['previousReleaseId'] != m['releaseId'], 'same_generation_update')
    pruned = pub['prunedReleaseIds']
    c.require(isinstance(pruned, list) and all(isinstance(x, str) for x in pruned)
              and pruned == sorted(set(pruned)), 'prune_ids_invalid')
    for rid in pruned:
        release_id(rid)
        c.require(rid not in {m['releaseId'], pub['previousReleaseId']}, 'prune_ids_invalid')
    seen = {m['releaseId']}
    order = []
    for entry in m['retainedReleases']:
        c.exact(entry, {*GEN_KEYS, 'publishedAt', 'retiredAt', 'retainUntil'})
        release_id(entry['releaseId'])
        c.require(entry['releaseId'] not in seen, 'duplicate_generation')
        seen.add(entry['releaseId'])
        first, retired = c.timestamp(entry['publishedAt']), c.timestamp(entry['retiredAt'])
        c.require(first <= retired <= assembled, 'retained_time_invalid')
        c.validate_manifest(clean(entry), first)
        c.require(entry['metadata']['evidenceKind'] == m['metadata']['evidenceKind'], 'evidence_kind_mismatch')
        c.require(c.timestamp(entry['retainUntil']) == deadline(entry['metadata'], retired), 'retention_deadline_mismatch')
        order.append(entry['releaseId'])
    c.require(order == sorted(order), 'retained_order_invalid')
    if pub['operation'] != 'initial':
        c.require(pub['previousReleaseId'] in seen, 'previous_generation_missing')


def read_tree(root):
    """Portable SHA-256 of exact files AND directories; no symlink, special file or secret lookup."""
    root = c.safe_path(root)
    c.require(root.is_dir(), 'snapshot_directory_required')
    files, dirs, records, total = {}, set(), [], 0
    for p in sorted(root.rglob('*')):
        c.safe_path(p)
        name = p.relative_to(root).as_posix()
        if p.is_dir():
            dirs.add(name); records.append({'path': name, 'kind': 'directory'})
        else:
            raw = c.read_file(p); total += len(raw)
            c.require(total <= c.MAX_TOTAL_BYTES, 'artifact_oversize')
            files[name] = raw
            c.require(len(files) <= MAX_FILES_DEFAULT, 'artifact_file_limit')
            records.append({'path': name, 'kind': 'file', 'bytes': len(raw), 'sha256': c.digest(raw)})
    return dict(root=root, files=files, dirs=dirs, digest=c.digest(c.canonical(records)), bytes=total)


def plan_manifest(previous, incoming, *, operation, now, previous_digest, rollback_release_id=None, prune_release_ids=()):
    """Pure transition contract; no file reads, writes, approval creation or deployment."""
    import copy
    c.require(operation in {'initial', 'update', 'rollback'}, 'operation_invalid')
    entries = {} if previous is None else {e['releaseId']: copy.deepcopy(e) for e in previous['retainedReleases']}
    if operation == 'rollback':
        c.require(incoming is None and previous is not None and rollback_release_id in entries, 'rollback_target_unverified')
        chosen = entries.pop(rollback_release_id)
        c.require(now < c.timestamp(chosen['retainUntil']), 'rollback_retention_expired')
        current = clean(chosen)
        c.validate_manifest(current, now)  # An expired approved period is never revived.
        published_at = chosen['publishedAt']
    else:
        c.require(incoming is not None and rollback_release_id is None, 'incoming_release_required')
        current = clean(incoming)
        c.validate_manifest(current, now)
        c.require(current['releaseId'] not in entries, 'explicit_rollback_required')
        published_at = text_time(now)
    if previous is not None:
        c.require(operation != 'initial' and previous['releaseId'] != current['releaseId'], 'same_generation_or_initial_update')
        c.require(previous['metadata']['evidenceKind'] == current['metadata']['evidenceKind'], 'evidence_kind_mismatch')
        old = {k: copy.deepcopy(previous[k]) for k in GEN_KEYS}
        old.update(publishedAt=previous['publication']['publishedAt'], retiredAt=text_time(now),
                   retainUntil=text_time(deadline(old['metadata'], now)))
        entries[old['releaseId']] = old
    else:
        c.require(operation == 'initial', 'previous_required')
    prune = sorted(prune_release_ids)
    c.require(len(prune) == len(set(prune)), 'prune_ids_invalid')
    for rid in prune:
        c.require(rid in entries and previous is not None and rid != previous['releaseId'], 'prune_target_invalid')
        c.require(now >= c.timestamp(entries[rid]['retainUntil']) + DELETE_SAFETY_MARGIN, 'prune_before_deadline')
        del entries[rid]
    current['retainedReleases'] = [entries[rid] for rid in sorted(entries)]
    current['publication'] = dict(contract=GENERATION_CONTRACT, publishedAt=published_at, assembledAt=text_time(now),
        operation=operation, previousReleaseId=None if previous is None else previous['releaseId'],
        previousArtifactDigest=previous_digest, prunedReleaseIds=prune)
    c.validate_manifest(current, now)
    return current


def verify_tree(root, now, *, historical=False):
    tree = read_tree(root)
    c.require('manifest.json' in tree['files'], 'v2_manifest_required_no_legacy_fallback')
    m = c.load_json(tree['files']['manifest.json'])
    c.require(isinstance(m, dict), 'manifest_invalid')
    c.require(c.canonical(m) == tree['files']['manifest.json'], 'manifest_not_canonical')
    c.require(m.get('artifactKind') == c.SITE_KIND, 'v2_full_site_required')
    at = c.timestamp(m['publication']['assembledAt']) if historical and 'publication' in m else now
    c.require(at <= now, 'future_publication')
    c.validate_manifest(m, at)
    expected = {'manifest.json', *c.SITE_ASSETS}
    for current, g in [(True, m), *((False, e) for e in m['retainedReleases'])]:
        published = c.timestamp(g['publishedAt']) if not current else at
        cm = clean(g)
        c.validate_manifest(cm, published)
        payloads = {}
        for station, name in c.STATION_FILES.items():
            path = f"releases/{g['releaseId']}/{name}"
            expected.add(path)
            c.require(path in tree['files'], 'generation_file_missing')
            payloads[station] = c.validate_envelope(tree['files'][path], cm, station)
        c.require(len({p['generatedAt'] for p in payloads.values()}) == 1, 'generated_at_mismatch')
        generated = c.timestamp(next(iter(payloads.values()))['generatedAt'])
        c.require(c.timestamp(g['metadata']['retrievedAt']) <= generated
                  <= c.timestamp(g['metadata']['approval']['approvedAt']), 'generation_time_invalid')
        c.validate_quality(g['metadata']['quality'], payloads, g['serviceDates'])
        prefix = '' if current else f"releases/{g['releaseId']}/assets"
        module = c.read_file(tree['root'] / prefix / 'odpt_public_runtime.mjs')
        if 'publication' in m:
            c.require(("export const GENERATION_CONTRACT = '" + GENERATION_CONTRACT + "'").encode() in module,
                      'generation_runtime_incompatible')
        if not current:
            expected.update(prefix + '/' + name for name in c.SITE_ASSETS)
        parser = SiteHtml(); parser.feed(c.read_file(tree['root'] / prefix / 'index.html').decode('utf-8'))
        c.require(len(parser.contact) == 1, 'contact_missing')
        # Old toolchains are bound by their descriptor bytes and trusted previous
        # tree digest, not compared to today's source checkout.
        validate_site_assets(tree['root'], cm, parser.contact[0], trusted_toolchain=False, asset_prefix=prefix)
    expected_dirs = {str(parent) for name in expected for parent in PurePosixPath(name).parents if str(parent) != '.'}
    c.require(set(tree['files']) == expected and tree['dirs'] == expected_dirs, 'artifact_tree_invalid')
    tree['manifest'] = m
    return tree
