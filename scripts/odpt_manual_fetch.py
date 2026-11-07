#!/usr/bin/env python3
"""Offline-safe manual ODPT batch capture primitives and disabled-by-default CLI.

Native HTTPS requires a reviewed plan and explicit CLI confirmation.
"""
from __future__ import annotations
import argparse, hashlib, json, os, sys, uuid
import fcntl, http.client, socket, ssl
from contextlib import contextmanager
from contextvars import ContextVar
from urllib.parse import parse_qsl, urljoin, unquote
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlencode

if __package__:
    from .odpt_source_contract import SOURCE_IDS, SOURCE_FILES, validate_source_record, validate_snapshot, content_fingerprint
    from .odpt_source_inventory import _stable_read, _record, _read_gtfs_metadata, _parse_json, MAX_SOURCE_BYTES
    from .odpt_source_store import _safe_new_store_path, PRIVATE_MODE, FILE_MODE, _safe_existing_store_path, _load_json_object, _json_bytes
else:
    from odpt_source_contract import SOURCE_IDS, SOURCE_FILES, validate_source_record, validate_snapshot, content_fingerprint
    from odpt_source_inventory import _stable_read, _record, _read_gtfs_metadata, _parse_json, MAX_SOURCE_BYTES
    from odpt_source_store import _safe_new_store_path, PRIVATE_MODE, FILE_MODE, _safe_existing_store_path, _load_json_object, _json_bytes

_LIVE_PLAN = ContextVar('odpt_live_plan', default=None)
TRANSPORT_MODES = frozenset({'offline-injected', 'live-https'})
ENDPOINT_IDS = {s: "odpt-" + s.replace(".", "-") for s in SOURCE_IDS}
MAX_RESPONSE_BYTES = MAX_SOURCE_BYTES

def now(): return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00","Z")

def make_fetch_record(source_id, batch_id, attempt_id, started, finished, status, content_type, raw=None, error=None, retry_of=None):
    if source_id not in SOURCE_IDS: raise ValueError("source_id_invalid")
    metadata = {"status":"unavailable","gtfs":None,"odpt":None}
    artifact = None; retrieved = None; outcome = "failed" if error else "succeeded"
    if raw is not None:
        if len(raw) > MAX_RESPONSE_BYTES: raise ValueError("source_size_limit_exceeded")
        if source_id == "metro.gtfs": metadata={"status":"parsed","gtfs":_read_gtfs_metadata(raw),"odpt":None}
        else:
            rows=_parse_json(raw)
            validate_response_scope(source_id, rows)
            dc=sorted({r["dc:date"] for r in rows if isinstance(r.get("dc:date"),str)})
            issued=sorted({r["dct:issued"] for r in rows if isinstance(r.get("dct:issued"),str)})
            for row in rows:
                if any(k in row and row[k] is not None and not isinstance(row[k],str) for k in ("dc:date","dct:issued")): raise ValueError("odpt_metadata_invalid")
            metadata={"status":"parsed","gtfs":None,"odpt":{"recordCount":len(rows),"dcDates":dc,"issuedDates":issued,"dcDateMissingCount":sum("dc:date" not in r or r["dc:date"] is None for r in rows),"issuedMissingCount":sum("dct:issued" not in r or r["dct:issued"] is None for r in rows)}}
        retrieved=finished
        artifact={"path":"raw/"+SOURCE_FILES[source_id],"representation":"response-body","sha256":hashlib.sha256(raw).hexdigest(),"sizeBytes":len(raw)}
    rec=_record(source_id,"raw/"+SOURCE_FILES[source_id],raw or b"",metadata,finished)
    rec.update(mode="fetch",batchId=batch_id,attemptId=attempt_id,retryOfAttemptId=retry_of,observedAt=None,startedAt=started,finishedAt=finished,retrievedAt=retrieved,outcome=outcome,http={"responses":[{"endpointId":ENDPOINT_IDS[source_id],"status":status,"contentType":content_type}]} if status is not None else None,errorCode=error,artifact=artifact,unknownReasons=[])
    validate_source_record(rec)
    return rec

def create_fetch_snapshot(records, created_at=None):
    records=list(records); selected={r["sourceId"]:r for r in records if r.get("outcome")=="succeeded"}
    if len(selected)!=7 or sum(r.get("outcome")=="succeeded" for r in records)!=7 or set(selected)!=SOURCE_IDS or len({r.get("batchId") for r in records})!=1: raise ValueError("batch_incomplete")
    snapshot={"contract":"odpt-source-snapshot","schemaVersion":1,"snapshotId":str(uuid.uuid4()),"createdAt":created_at or now(),"mode":"fetch","batchId":records[0]["batchId"],"selectedRecords":{s:selected[s]["recordId"] for s in sorted(SOURCE_IDS)},"contentFingerprint":content_fingerprint(selected.values()),"completeness":"complete","acquisitionStatus":"fetch-success","crossSourceConsistency":"not-evaluated"}
    validate_snapshot(snapshot,records)
    return snapshot

CONNECT_TIMEOUT = 15
READ_TIMEOUT = 30
BASE = "https://api.odpt.org/api/v4/"


class FetchError(ValueError):
    """Only fixed codes may cross the transport boundary."""


def _require_live_policy():
    """A constant/environment change cannot authorize a native request."""
    if _LIVE_PLAN.get() is None:
        raise FetchError('live_transport_disabled')


def _transport_mode(exchange):
    if exchange is None:
        _require_live_policy()
        return 'live-https'
    if _LIVE_PLAN.get() is not None:
        raise FetchError('transport_provenance_mismatch')
    if not callable(exchange):
        raise FetchError('exchange_invalid')
    return 'offline-injected'


def endpoint(source_id):
    if source_id not in SOURCE_IDS:
        raise FetchError("source_id_invalid")
    if source_id == "metro.gtfs":
        return BASE + "files/TokyoMetro/data/TokyoMetro-Train-GTFS.zip", {}
    resource = {"railway": "Railway", "station": "Station",
                "train-timetable": "TrainTimetable", "station-timetable": "StationTimetable"}[source_id.split(".")[1]]
    filters = {"odpt:operator": "odpt.Operator:TokyoMetro"}
    if len(source_id.split(".")) == 3:
        filters["odpt:railway"] = "odpt.Railway:TokyoMetro." + source_id.split(".")[2].capitalize()
    return BASE + "odpt:" + resource, filters


def _https_exchange(url):
    """Native adapter requires the invocation permit and verifies TLS/host/timeouts."""
    _require_live_policy()
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or parsed.port not in (None, 443)
            or parsed.username or parsed.password or parsed.fragment
            or not ((parsed.hostname == 'api.odpt.org' and parsed.path in
                     {urlsplit(endpoint(s)[0]).path for s in SOURCE_IDS})
                    or parsed.hostname == 'dataodpt.blob.core.windows.net')):
        raise FetchError('redirect_rejected')
    conn = http.client.HTTPSConnection(parsed.hostname, port=443,
                                       timeout=CONNECT_TIMEOUT, context=ssl.create_default_context())
    try:
        conn.connect()
        conn.sock.settimeout(READ_TIMEOUT)
        conn.request("GET", parsed.path + ("?" + parsed.query if parsed.query else ""),
                     headers={"Accept-Encoding": "identity"})
        response = conn.getresponse()
        # Response close also owns the connection (no connection reuse).
        original_close = response.close
        def close():
            original_close()
            conn.close()
        response.close = close
        return response
    except BaseException:
        conn.close()
        raise


def env_credential():
    """Called only explicitly; never read .env.local or accept a CLI key."""
    return os.environ.get("ODPT_API_KEY")


def checked_credential(value):
    if not isinstance(value, str) or not value or any(ord(c) < 33 or ord(c) > 126 for c in value):
        raise FetchError('credential_invalid')
    return value


def validate_response_scope(source_id, rows):
    """Minimal request-scope check, not a completeness or timetable-version claim."""
    if not rows:
        raise FetchError('response_empty')
    base, filters = endpoint(source_id)
    kind = urlsplit(base).path.rsplit('/', 1)[-1]
    for row in rows:
        if row.get('@type') != kind:
            raise FetchError('response_type_mismatch')
        if any(not isinstance(row.get(k), str) or not row[k] for k in ('@id', 'owl:sameAs')):
            raise FetchError('response_identifier_invalid')
        if any(row.get(k) != v for k, v in filters.items()):
            raise FetchError('response_filter_mismatch')


def transport(source_id, credential_provider, exchange=None):
    """Injected exchange must return status/getheader/read/close; no auto retry."""
    if source_id not in SOURCE_IDS:
        raise FetchError('source_id_invalid')
    _transport_mode(exchange)  # Deny before reading a credential.
    responses = []
    try:
        secret = checked_credential(credential_provider())
        base, filters = endpoint(source_id)
        url = base + "?" + urlencode({**filters, "acl:consumerKey": secret})
        send = exchange or _https_exchange
        for hop in range(2):
            response = send(url)
            try:
                status = response.status
                ctype = (response.getheader("Content-Type") or "").split(";", 1)[0].strip().lower()
                allowed = {"application/zip", "application/octet-stream"} if source_id == "metro.gtfs" else {"application/json", "application/ld+json"}
                # Never retain raw Content-Type, Location, headers or URL.
                safe_type = ctype if ctype in allowed else None
                responses.append({"endpointId": ENDPOINT_IDS[source_id] if hop == 0 else "odpt-gtfs-blob",
                                  "status": status if type(status) is int else None, "contentType": safe_type})
                if status == 302 and source_id == "metro.gtfs" and hop == 0:
                    location = response.getheader("Location") or ""
                    target = urlsplit(urljoin(base, location))
                    forbidden = {"acl:consumerkey", "consumerkey", "key", "api_key", "apikey", "odpt_api_key"}
                    if (target.scheme != "https" or target.hostname != "dataodpt.blob.core.windows.net"
                            or target.port not in (None, 443) or target.username or target.password or target.fragment
                            or not target.path.startswith("/") or "\\" in location
                            or secret in unquote(location) or any(ord(c) < 32 for c in location)
                            or any(k.lower() in forbidden for k, _ in parse_qsl(target.query))):
                        raise FetchError("redirect_rejected")
                    url = target.geturl()  # May be signed: memory only, fresh request, no key/header forwarding.
                    continue
                if status != 200:
                    raise FetchError("http_status_failed")
                if ctype not in allowed:
                    raise FetchError("content_type_invalid")
                if response.getheader("Content-Encoding") not in (None, "", "identity"):
                    raise FetchError("content_encoding_invalid")
                length = response.getheader("Content-Length")
                if length is not None and (not length.isascii() or not length.isdigit() or int(length) > MAX_RESPONSE_BYTES):
                    raise FetchError("response_size_invalid")
                body = bytearray()
                while True:
                    block = response.read(min(65536, MAX_RESPONSE_BYTES + 1 - len(body)))
                    if not block:
                        break
                    body.extend(block)
                    if len(body) > MAX_RESPONSE_BYTES:
                        raise FetchError("response_too_large")
                if length is not None and len(body) != int(length):
                    raise FetchError("response_incomplete")
                if secret.encode() in body or urlencode({"x": secret})[2:].encode() in body:
                    raise FetchError("credential_echo_rejected")
                return bytes(body), responses
            finally:
                response.close()
        raise FetchError("redirect_rejected")
    except KeyboardInterrupt as exc:
        exc.responses = responses
        raise
    except Exception as exc:
        if isinstance(exc, FetchError) and str(exc) in {
            "credential_invalid", "redirect_rejected", "http_status_failed", "content_type_invalid",
            "content_encoding_invalid", "response_size_invalid", "response_too_large",
            "response_incomplete", "credential_echo_rejected", "live_transport_disabled"}: code = str(exc)
        elif isinstance(exc, ssl.SSLError): code = "tls_failed"
        elif isinstance(exc, (TimeoutError, socket.timeout)): code = "timeout"
        else: code = "transport_failed"
        error = FetchError(code)
        error.responses = responses
        raise error from None


def _save(directory, filename, value):
    """Exclusive atomic publication; an existing name is never replaced."""
    _safe_existing_store_path(directory)
    tmp = directory / (".pending-" + str(uuid.uuid4()))
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, FILE_MODE)
        with os.fdopen(fd, "wb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(tmp, directory / filename, follow_symlinks=False)
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try: os.fsync(fd)
        finally: os.close(fd)
    except OSError:
        raise FetchError("persistence_failed") from None
    finally:
        tmp.unlink(missing_ok=True)


def _read_json(path):
    return _load_json_object(path)


def validate_batch(batch):
    """Auxiliary envelope v1 stays offline-only; v2 also describes future live data."""
    if (not isinstance(batch, dict) or set(batch) != {'contract', 'schemaVersion', 'batchId',
            'provenance', 'applicationPeriod', 'publicationApproved'}
            or batch['contract'] != 'odpt-manual-fetch-batch'
            or type(batch['schemaVersion']) is not int or batch['schemaVersion'] not in (1, 2)
            or batch['publicationApproved'] is not False or batch['applicationPeriod'] is not None):
        raise FetchError('batch_invalid')
    try:
        if str(uuid.UUID(batch['batchId'])) != batch['batchId']:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise FetchError('batch_id_invalid') from None
    provenance = batch['provenance']
    if (not isinstance(provenance, dict) or set(provenance) != {'transport', 'retrievedAt'}
            or not isinstance(provenance['transport'], str) or provenance['transport'] not in TRANSPORT_MODES
            or provenance['retrievedAt'] is not None
            or (batch['schemaVersion'] == 1 and provenance['transport'] != 'offline-injected')):
        raise FetchError('provenance_invalid')
    return provenance['transport']


def new_batch(path, *, transport_mode='offline-injected'):
    batch = {'batchId': str(uuid.uuid4()), 'contract': 'odpt-manual-fetch-batch', 'schemaVersion': 2,
             'provenance': {'transport': transport_mode, 'retrievedAt': None},
             'applicationPeriod': None, 'publicationApproved': False}
    validate_batch(batch)
    root = _safe_new_store_path(path)
    root.mkdir(mode=PRIVATE_MODE)
    os.chmod(root, PRIVATE_MODE)
    for name in ("raw", "attempts"):
        (root / name).mkdir(mode=PRIVATE_MODE)
    _save(root, "batch.json", _json_bytes(batch))
    return root


@contextmanager
def _locked(path):
    root = _safe_existing_store_path(path)
    # Lock the directory inode, without adding or replacing a lock file.
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield root
    finally:
        os.close(fd)


def history(root):
    batch = _read_json(root / "batch.json")
    validate_batch(batch)
    attempts = _safe_existing_store_path(root / "attempts")
    records = []
    for directory in sorted(attempts.iterdir()):
        _safe_existing_store_path(directory)
        start = _read_json(directory / "started.json")
        rec = _read_json(directory / "result.json") if (directory / "result.json").exists() else start
        validate_source_record(start)
        validate_source_record(rec)
        if (start["outcome"] != "interrupted" or rec["batchId"] != batch["batchId"]
                or any(rec[k] != start[k] for k in ("recordId", "attemptId", "sourceId", "batchId", "retryOfAttemptId", "startedAt"))
                or directory.name != rec["attemptId"]):
            raise FetchError("history_invalid")
        if (directory / "result.json").exists():
            evidence = _read_json(directory / "evidence.json")
            if evidence != evidence_for(rec, batch): raise FetchError("evidence_invalid")
        records.append(rec)
    by_attempt = {r["attemptId"]: r for r in records}
    if len(by_attempt) != len(records) or len({r["recordId"] for r in records}) != len(records):
        raise FetchError("history_duplicate")
    for rec in records:
        seen = {rec["attemptId"]}
        cursor = rec
        while cursor["retryOfAttemptId"] is not None:
            parent = by_attempt.get(cursor["retryOfAttemptId"])
            if (parent is None or parent["attemptId"] in seen or parent["outcome"] == "succeeded"
                    or parent["sourceId"] != cursor["sourceId"] or parent["batchId"] != cursor["batchId"]):
                raise FetchError("retry_chain_invalid")
            if parent["finishedAt"] and datetime.fromisoformat(parent["finishedAt"]) > datetime.fromisoformat(cursor["startedAt"]):
                raise FetchError("retry_chain_invalid")
            seen.add(parent["attemptId"])
            cursor = parent
    return batch, records


def evidence_for(rec, batch=None):
    # The default is only for reading the original v1 offline evidence format.
    mode = validate_batch(batch) if batch is not None else 'offline-injected'
    base, filters = endpoint(rec["sourceId"])
    return {"contract": "odpt-fetch-evidence", "schemaVersion": batch['schemaVersion'] if batch else 1,
            "batchId": rec["batchId"], "attemptId": rec["attemptId"], "sourceId": rec["sourceId"],
            "endpointId": ENDPOINT_IDS[rec["sourceId"]], "host": "api.odpt.org",
            "path": urlsplit(base).path, "filters": filters, "selector": None,
            "selectorStatus": "not-used-unconfirmed", "transport": mode,
            "outcome": rec["outcome"], "errorCode": rec["errorCode"]}


def acquire(path, source_id, credential_provider, *, exchange=None):
    """One manual attempt. Retry follows only the latest failed/interrupted attempt."""
    if source_id not in SOURCE_IDS: raise FetchError("source_id_invalid")
    mode = _transport_mode(exchange)
    _check_live_batch(path)
    with _locked(path) as root:
        if (root / "snapshot.json").exists() or (root / "snapshot.json").is_symlink(): raise FetchError("batch_sealed")
        batch, records = history(root)
        if mode != batch['provenance']['transport']:
            raise FetchError('transport_provenance_mismatch')
        prior = [r for r in records if r["sourceId"] == source_id]
        # A retry chain, not wall clock order, determines the latest record.
        parents = {r["retryOfAttemptId"] for r in prior}
        leaves = [r for r in prior if r["attemptId"] not in parents]
        if len(leaves) > 1: raise FetchError("retry_chain_invalid")
        parent = leaves[0] if leaves else None
        if parent and parent["outcome"] == "succeeded": raise FetchError("source_already_succeeded")
        raw_root = _safe_existing_store_path(root / "raw")
        target = raw_root / SOURCE_FILES[source_id]
        if target.exists() or target.is_symlink(): raise FetchError("raw_already_present")
        attempt = str(uuid.uuid4())
        directory = root / "attempts" / attempt
        directory.mkdir(mode=PRIVATE_MODE)
        start = make_fetch_record(source_id, batch["batchId"], attempt, now(), now(), None, None,
                                  error="interrupted", retry_of=parent["attemptId"] if parent else None)
        start.update(finishedAt=None, outcome="interrupted")
        validate_source_record(start)
        _save(directory, "started.json", _json_bytes(start))
        rec = dict(start)
        responses = []
        try:
            raw, responses = transport(source_id, credential_provider, exchange)
            rec = make_fetch_record(source_id, batch["batchId"], attempt, start["startedAt"], now(),
                                    200, responses[-1]["contentType"], raw, retry_of=start["retryOfAttemptId"])
            rec["recordId"] = start["recordId"]
            rec["http"] = {"responses": responses}
        except KeyboardInterrupt as exc:
            if getattr(exc, "responses", None): start["http"] = {"responses": exc.responses}
            validate_source_record(start)
            _save(directory, "evidence.json", _json_bytes(evidence_for(start, batch)))
            _save(directory, "result.json", _json_bytes(start))
            return start
        except Exception as exc:
            code = str(exc) if isinstance(exc, FetchError) else "body_validation_failed"
            rec = dict(start, outcome="failed", finishedAt=now(), errorCode=code)
            observed = getattr(exc, "responses", None) or responses
            if observed: rec["http"] = {"responses": observed}
        validate_source_record(rec)
        _save(directory, "evidence.json", _json_bytes(evidence_for(rec, batch)))
        if rec["outcome"] == "succeeded":
            # History result is durable only after raw is durable. Orphan raw blocks retries.
            _save(root / "raw", SOURCE_FILES[source_id], raw)
        _save(directory, "result.json", _json_bytes(rec))
        return rec


def _verify_raw(root, records, batch):
    # No raw copies. Stable read applies JSON/GTFS validation and inode checks.
    _safe_existing_store_path(root / "raw")
    for rec in records:
        if rec["outcome"] != "succeeded": continue
        raw, metadata = _stable_read(root / "raw" / SOURCE_FILES[rec["sourceId"]], rec["sourceId"])
        if rec['sourceId'] != 'metro.gtfs':
            validate_response_scope(rec['sourceId'], _parse_json(raw))
        artifact = rec["artifact"]
        if (hashlib.sha256(raw).hexdigest() != artifact["sha256"] or len(raw) != artifact["sizeBytes"]
                or metadata != rec["metadata"] or rec["batchId"] != batch["batchId"]):
            raise FetchError("raw_mismatch")
    # A second pass catches changes to early files during later parsing.
    for rec in records:
        if rec["outcome"] != "succeeded": continue
        raw, _ = _stable_read(root / "raw" / SOURCE_FILES[rec["sourceId"]], rec["sourceId"])
        if (hashlib.sha256(raw).hexdigest(), len(raw)) != (rec["artifact"]["sha256"], rec["artifact"]["sizeBytes"]):
            raise FetchError("raw_changed_during_finalization")


def finalize(path):
    with _locked(path) as root:
        batch, records = history(root)
        snapshot = create_fetch_snapshot(records)
        _verify_raw(root, records, batch)
        _save(root, "snapshot.json", _json_bytes(snapshot))
        return snapshot


def run_fetch(path, credential_provider, *, exchange=None, retry_source=None):
    """Fixed seven-source driver. Only explicit retry may reopen an unfinished batch.

    Dependency injection is a Python test seam, never a CLI transport/URL option.
    """
    mode = _transport_mode(exchange)  # Never read secrets/create a batch while live is prohibited.
    _check_live_batch(path)
    if not callable(credential_provider):
        raise FetchError('credential_provider_required')
    order = list(SOURCE_FILES)
    if retry_source is None:
        root = new_batch(path, transport_mode=mode)
        pending = order
    else:
        if retry_source not in SOURCE_IDS:
            raise FetchError('source_id_invalid')
        with _locked(path) as root:
            if (root / 'snapshot.json').exists() or (root / 'snapshot.json').is_symlink():
                raise FetchError('batch_sealed')
            batch, records = history(root)
            if validate_batch(batch) != mode:
                raise FetchError('transport_provenance_mismatch')
            latest = {}
            for sid in order:
                chain = [r for r in records if r['sourceId'] == sid]
                if not chain:
                    continue
                children = [r['retryOfAttemptId'] for r in chain if r['retryOfAttemptId'] is not None]
                roots = [r for r in chain if r['retryOfAttemptId'] is None]
                leaves = [r for r in chain if r['attemptId'] not in children]
                if len(roots) != 1 or len(children) != len(set(children)) or len(leaves) != 1:
                    raise FetchError('retry_chain_invalid')
                latest[sid] = leaves[0]
            unattempted = [sid for sid in order if sid not in latest]
            target = latest.get(retry_source)
            # A process may stop between attempts, leaving no failed record for the next source.
            # Explicit continuation starts that source's first attempt; never invent a retry parent.
            if ((target is not None and target['outcome'] not in ('failed', 'interrupted'))
                    or (target is None and (not unattempted or retry_source != unattempted[0]))
                    or any(r['outcome'] != 'succeeded' for sid, r in latest.items() if sid != retry_source)):
                raise FetchError('explicit_retry_target_invalid')
            _verify_raw(root, records, batch)  # Do not continue a batch whose earlier successes changed.
            pending = [retry_source] + [sid for sid in unattempted if sid != retry_source]
    attempted = []
    for sid in pending:
        rec = acquire(root, sid, credential_provider, exchange=exchange)
        attempted.append(sid)
        if rec['outcome'] != 'succeeded':
            return {'driverStatus': 'stopped', 'stoppedSourceId': sid, 'outcome': rec['outcome'],
                    'attemptedSourceIds': attempted, 'snapshotCreated': False,
                    'publicationApproved': False, 'applicationPeriod': None}
    finalize(root)  # Seven unique successes, full history and unchanged raw are mandatory.
    return {'driverStatus': 'complete', 'attemptedSourceIds': attempted, 'snapshotCreated': True,
            'publicationApproved': False, 'applicationPeriod': None}


def capture_mock_batch(batch_path, responses):
    """Compatibility test seam, using the same transport and journal as acquire."""
    root = new_batch(batch_path)
    class Response:
        def __init__(self, value):
            self.status, self.ctype, self.body = value
            import io
            self.stream = io.BytesIO(self.body)
        def getheader(self, key): return self.ctype if key == "Content-Type" else None
        def read(self, count): return self.stream.read(count)
        def close(self): self.stream.close()
    count = 0
    for sid in sorted(SOURCE_IDS):
        def exchange(_url):
            if sid not in responses: raise OSError("mock missing")
            return Response(responses[sid])
        rec = acquire(root, sid, lambda: "mock-credential", exchange=exchange)
        count += rec["outcome"] == "succeeded"
    if count == 7: finalize(root)
    return {"batchId": _read_json(root / "batch.json")["batchId"], "successCount": count, "snapshotCreated": count == 7}


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse normally echoes unknown arguments (which might contain a key).
        self.exit(2, "cli_arguments_invalid\n")


def acquisition_plan(path, retry_source=None):
    """Read-only, secret-free preview. The digest binds destination, scope and retry history."""
    if retry_source is None:
        root = _safe_new_store_path(path)
        history_hash = None
    else:
        if retry_source not in SOURCE_IDS:
            raise FetchError('source_id_invalid')
        with _locked(path) as root:
            if (root / 'snapshot.json').exists():
                raise FetchError('batch_sealed')
            batch, records = history(root)
            if validate_batch(batch) != 'live-https':
                raise FetchError('transport_provenance_mismatch')
            history_hash = hashlib.sha256(_json_bytes([batch, sorted(records, key=lambda r: r['attemptId'])])).hexdigest()
    plan = {'operation': 'retry' if retry_source else 'fetch', 'batch': str(root),
            'retrySource': retry_source, 'historyFingerprint': history_hash,
            'sources': [{'sourceId': s, 'filename': SOURCE_FILES[s],
                         'endpoint': endpoint(s)[0], 'filters': endpoint(s)[1]} for s in SOURCE_FILES],
            'gtfsRedirect': 'https://dataodpt.blob.core.windows.net:443; maximum one 302',
            'selector': None, 'publicationApproved': False, 'applicationPeriod': None}
    plan['confirmation'] = hashlib.sha256(_json_bytes(plan)).hexdigest()
    return plan


def validate_live_confirmation(plan, enabled, confirmation):
    if enabled is not True or confirmation != plan['confirmation']:
        raise FetchError('live_transport_disabled')


@contextmanager
def _live_session(plan):
    token = _LIVE_PLAN.set(plan)
    try:
        yield
    finally:
        _LIVE_PLAN.reset(token)


def _check_live_batch(path):
    plan = _LIVE_PLAN.get()
    if plan is not None and str(path) != plan['batch']:
        raise FetchError('live_batch_mismatch')


def main(argv=None, *, exchange=None, credential_provider=None):
    parser = SafeArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    live = commands.add_parser("fetch", help="explicitly confirmed fixed-source capture")
    live.add_argument("--batch", type=Path, required=True)
    live.add_argument("--enable-live-transport", action="store_true")
    live.add_argument("--confirm-plan")
    retry = commands.add_parser("retry", help="explicit retry of one failed/interrupted source, then remaining unattempted sources")
    retry.add_argument("--batch", type=Path, required=True)
    retry.add_argument("--source", choices=sorted(SOURCE_IDS), required=True)
    retry.add_argument("--enable-live-transport", action="store_true")
    retry.add_argument("--confirm-plan")
    plan_command = commands.add_parser('plan', help='preview only; no secrets, writes or communication')
    plan_command.add_argument('--batch', type=Path, required=True)
    plan_command.add_argument('--source', choices=sorted(SOURCE_IDS), help='preview retry of this source')
    commands.add_parser("help-offline", help="show offline transport status")
    for name in ("init", "inspect", "finalize"):
        command = commands.add_parser(name, help="local batch operation only")
        command.add_argument("--batch", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command in ('fetch', 'retry'):
            source = args.source if args.command == 'retry' else None
            if exchange is not None:
                if args.enable_live_transport or args.confirm_plan is not None:
                    raise FetchError('transport_provenance_mismatch')
                result = run_fetch(args.batch, credential_provider, exchange=exchange, retry_source=source)
            else:
                if not args.enable_live_transport or args.confirm_plan is None:
                    raise FetchError('live_transport_disabled')
                plan = acquisition_plan(args.batch, source)
                validate_live_confirmation(plan, args.enable_live_transport, args.confirm_plan)
                secret = checked_credential((credential_provider or env_credential)())
                with _live_session(plan):
                    result = run_fetch(args.batch, lambda: secret, retry_source=source)
            print(json.dumps(result, sort_keys=True))
            return 0 if result['driverStatus'] == 'complete' else 2
        if args.command == 'plan':
            print(json.dumps(acquisition_plan(args.batch, args.source), sort_keys=True))
        elif args.command == "help-offline":
            print("live_transport=default-deny; explicit plan confirmation required")
        elif args.command == "init":
            new_batch(args.batch)
            print("batch_created; publicationApproved=false; applicationPeriod=null")
        elif args.command == "finalize":
            finalize(args.batch)
            print("snapshot_created; publicationApproved=false; applicationPeriod=null")
        else:
            with _locked(args.batch) as root:
                _, records = history(root)
                print("attempts=" + str(len(records)) + "; succeeded=" + str(sum(r["outcome"] == "succeeded" for r in records)))
        return 0
    except KeyboardInterrupt:
        print("local_batch_operation_interrupted", file=sys.stderr)
        return 2
    except Exception:
        # Do not expose paths, exceptions, malformed metadata or credentials.
        print("local_batch_operation_failed", file=sys.stderr)
        return 2


if __name__ == "__main__": raise SystemExit(main())
