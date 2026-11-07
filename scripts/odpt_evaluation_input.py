"""Read-only evaluation adapter. Strict stores and sealed fetch batches stay distinct."""
from __future__ import annotations
import hashlib
from pathlib import Path

if __package__:
    from . import odpt_manual_fetch as fetch
    from .odpt_source_contract import SOURCE_FILES, SOURCE_IDS, validate_snapshot
    from .odpt_source_store import StoreError, _read_store_file, load_store_contract as load_strict_store
else:
    import odpt_manual_fetch as fetch
    from odpt_source_contract import SOURCE_FILES, SOURCE_IDS, validate_snapshot
    from odpt_source_store import StoreError, _read_store_file, load_store_contract as load_strict_store


def metadata_files(path):
    """Return validated relative metadata paths for physical immutability checks."""
    loaded = load_input(path)
    if 'inputFiles' in loaded:
        return sorted(loaded['inputFiles'])
    return ['snapshot.json'] + ['sources/' + sid + '.json' for sid in sorted(SOURCE_IDS)]


def _files(root):
    names = ['batch.json', 'snapshot.json']
    attempts = fetch._safe_existing_store_path(root / 'attempts')
    for directory in sorted(attempts.iterdir()):
        fetch._safe_existing_store_path(directory)
        actual = {p.name for p in directory.iterdir()}
        if not {'started.json'} <= actual or not actual <= {'started.json', 'result.json', 'evidence.json'}:
            raise StoreError('fetch_attempt_files_invalid')
        names.extend('attempts/' + directory.name + '/' + name for name in sorted(actual))
    return {name: hashlib.sha256(_read_store_file(root / name)).hexdigest()
            for name in names}


def load_fetch_batch(path):
    """Validate full retry history before exposing the selected seven records."""
    try:
        with fetch._locked(Path(path)) as root:
            if {p.name for p in root.iterdir()} != {'batch.json', 'snapshot.json', 'raw', 'attempts'}:
                raise StoreError('fetch_batch_files_invalid')
            snapshot = fetch._read_json(root / 'snapshot.json')
            before = _files(root)
            batch, attempts = fetch.history(root)
            if (set(batch) != {'contract', 'schemaVersion', 'batchId', 'provenance', 'applicationPeriod', 'publicationApproved'}
                    or type(batch['schemaVersion']) is not int or batch['schemaVersion'] != 1
                    or batch['provenance'] != {'transport': 'offline-injected', 'retrievedAt': None}
                    or batch['publicationApproved'] is not False
                    or batch['applicationPeriod'] is not None or snapshot['mode'] != 'fetch'
                    or snapshot['batchId'] != batch['batchId']
                    or snapshot['crossSourceConsistency'] != 'not-evaluated'):
                raise StoreError('fetch_batch_state_invalid')
            validate_snapshot(snapshot, attempts)
            selected = []
            for sid in sorted(SOURCE_IDS):
                chain = [r for r in attempts if r['sourceId'] == sid]
                children = [r['retryOfAttemptId'] for r in chain if r['retryOfAttemptId'] is not None]
                roots = [r for r in chain if r['retryOfAttemptId'] is None]
                leaves = [r for r in chain if r['attemptId'] not in children]
                successes = [r for r in chain if r['outcome'] == 'succeeded']
                if (len(roots) != 1 or len(children) != len(set(children)) or len(leaves) != 1
                        or len(successes) != 1 or leaves[0] != successes[0]
                        or snapshot['selectedRecords'][sid] != successes[0]['recordId']):
                    raise StoreError('fetch_selection_invalid')
                selected.append(successes[0])
            raw_root = fetch._safe_existing_store_path(root / 'raw')
            if {p.name for p in raw_root.iterdir()} != set(SOURCE_FILES.values()):
                raise StoreError('fetch_raw_set_invalid')
            for _ in range(2):
                for rec in selected:
                    raw, metadata = fetch._stable_read(raw_root / SOURCE_FILES[rec['sourceId']], rec['sourceId'])
                    if (hashlib.sha256(raw).hexdigest() != rec['artifact']['sha256']
                            or len(raw) != rec['artifact']['sizeBytes'] or metadata != rec['metadata']):
                        raise StoreError('fetch_raw_mismatch')
            if before != _files(root):
                raise StoreError('fetch_metadata_changed')
            return {'snapshot': snapshot, 'records': selected, 'attemptRecords': attempts, 'inputFiles': before}
    except StoreError:
        raise
    except Exception:
        raise StoreError('fetch_input_invalid') from None


def load_input(path):
    """No fallback from a malformed batch to legacy. No schema is relaxed."""
    path = Path(path)
    marker = path / 'batch.json'
    if marker.exists() or marker.is_symlink():
        return load_fetch_batch(path)
    return load_strict_store(path)
