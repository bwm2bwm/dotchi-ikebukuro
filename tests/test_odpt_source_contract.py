import copy
import hashlib
import json
import unittest
import uuid

from scripts import odpt_source_contract as contract


def uid():
    return str(uuid.uuid4())


def artifact(source_id, fill="a"):
    return {"path": "raw/" + contract.SOURCE_FILES[source_id],
            "representation": "stored-file", "sha256": fill * 64, "sizeBytes": 17}


def source(source_id, *, mode="fetch", record_id=None, batch_id=None,
           attempt_id=None, retry=None, outcome=None, start=None, finish=None,
           retrieved=None, http=None, error=None):
    is_gtfs = source_id == "metro.gtfs"
    legacy = mode == "legacy-observation"
    outcome = outcome or "succeeded"
    if outcome in {"failed", "interrupted"}:
        retrieved = None
        if outcome == "interrupted":
            finish = None
    return {
        "contract": "odpt-source-record", "schemaVersion": 1,
        "recordId": record_id or uid(), "sourceId": source_id,
        "sourceType": "gtfs-zip" if is_gtfs else "odpt-json",
        "originId": contract.ORIGIN_IDS[source_id], "mode": mode,
        "batchId": None if legacy else (batch_id or uid()),
        "attemptId": None if legacy else (attempt_id or uid()),
        "retryOfAttemptId": None if legacy else retry,
        "observedAt": "2026-11-03T00:00:00Z" if legacy else None,
        "startedAt": None if legacy else (start or "2026-11-03T00:00:00Z"),
        "finishedAt": None if legacy else finish if finish is not None else "2026-11-03T00:00:01Z",
        "retrievedAt": None if legacy or outcome in {"failed", "interrupted"} else retrieved if retrieved is not None else "2026-11-03T00:00:01Z",
        "outcome": "legacy-observed" if legacy else outcome,
        "http": None if legacy else http or {"responses": [{"endpointId": contract.ORIGIN_IDS[source_id],
             "status": 200 if outcome == "succeeded" else 503,
             "contentType": "application/json" if not is_gtfs else "application/zip"}]},
        "errorCode": None if legacy else error,
        "artifact": artifact(source_id) if legacy or outcome == "succeeded" else None,
        "metadata": {"status": "parsed", "gtfs": {"feedVersion": "v", "validFrom": "2026-01-01",
             "validThrough": "2027-01-01"}, "odpt": None} if is_gtfs else
             {"status": "parsed", "gtfs": None, "odpt": {"recordCount": 1, "dcDates": [], "issuedDates": []}},
        "unknownReasons": ["historical_acquisition_not_recorded"] if legacy else [],
    }


def fingerprint(records):
    rows = [{"sourceId": r["sourceId"], "sha256": r["artifact"]["sha256"],
             "sizeBytes": r["artifact"]["sizeBytes"]} for r in sorted(records, key=lambda x: x["sourceId"])]
    body = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(body).hexdigest()


def snapshot(records, mode="legacy-observation", batch=None):
    return {"contract": "odpt-source-snapshot", "schemaVersion": 1, "snapshotId": uid(),
        "createdAt": "2026-11-03T00:00:02Z", "mode": mode, "batchId": batch,
        "selectedRecords": {r["sourceId"]: r["recordId"] for r in records},
        "contentFingerprint": fingerprint(records)}


class SourceRecordTests(unittest.TestCase):
    def test_legacy_valid_and_retrieved_time_stays_unknown(self):
        row = source("metro.gtfs", mode="legacy-observation")
        self.assertIs(contract.validate_source_record(row), row)
        row["retrievedAt"] = row["observedAt"]
        self.assertCode("legacy_observation_state_invalid", lambda: contract.validate_source_record(row))

    def test_fetch_success_failure_interrupted(self):
        self.assertEqual(contract.validate_source_record(source("metro.station"))["outcome"], "succeeded")
        fail = source("metro.station", outcome="failed", retrieved=None, error="http_error")
        fail["finishedAt"] = "2026-11-03T00:00:02Z"
        self.assertEqual(contract.validate_source_record(fail)["outcome"], "failed")
        stopped = source("metro.station", outcome="interrupted", finish=None, retrieved=None, error="timeout")
        stopped["finishedAt"] = None
        self.assertEqual(contract.validate_source_record(stopped)["outcome"], "interrupted")

    def test_invalid_time_uuid_hash_bytes_types_and_version(self):
        cases = [
            ("attempt_id_invalid", lambda x: x.update(attemptId="bad")),
            ("attempt_timestamp_invalid", lambda x: x.update(startedAt="2026-11-03T09:00:00+09:00")),
            ("artifact_invalid", lambda x: x["artifact"].update(sha256="z" * 64)),
            ("artifact_invalid", lambda x: x["artifact"].update(sizeBytes=True)),
            ("source_schema_version_unsupported", lambda x: x.update(schemaVersion=2)),
            ("source_id_invalid", lambda x: x.update(sourceId="metro.other")),
        ]
        for code, mutate in cases:
            row = source("metro.station")
            mutate(row)
            self.assertCode(code, lambda row=row: contract.validate_source_record(row))
        row = source("metro.station")
        row["retrievedAt"] = "not-a-timestamp"
        self.assertCode("attempt_result_invalid", lambda: contract.validate_source_record(row))

    def test_unknown_keys_duplicate_keys_and_bool_integer(self):
        row = source("metro.station")
        row["extra"] = 1
        self.assertCode("source_record_fields_invalid", lambda: contract.validate_source_record(row))
        raw = json.dumps(source("metro.station"))[:-1] + ',"schemaVersion":1}'
        self.assertCode("json_duplicate_key", lambda: contract.loads_record(raw))
        row = source("metro.station")
        row["metadata"]["odpt"]["recordCount"] = True
        self.assertCode("source_metadata_invalid", lambda: contract.validate_source_record(row))

    def assertCode(self, expected, call):
        with self.assertRaises(contract.ContractError) as caught:
            call()
        self.assertEqual(caught.exception.code, expected)


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.rows = [source(source_id, mode="legacy-observation") for source_id in sorted(contract.SOURCE_IDS)]
        self.snapshot = snapshot(self.rows)

    def test_valid_legacy_snapshot(self):
        self.assertIs(contract.validate_snapshot(self.snapshot, self.rows), self.snapshot)
        unsupported = copy.deepcopy(self.snapshot)
        unsupported["schemaVersion"] = 99
        self.assertCode("snapshot_schema_version_unsupported",
                        lambda: contract.validate_snapshot(unsupported, self.rows))

    def test_source_set_missing_extra_duplicate_and_bad_reference(self):
        snap = copy.deepcopy(self.snapshot)
        del snap["selectedRecords"]["metro.station"]
        self.assertCode("snapshot_source_set_invalid", lambda: contract.validate_snapshot(snap, self.rows))
        snap = copy.deepcopy(self.snapshot)
        snap["selectedRecords"]["metro.extra"] = uid()
        self.assertCode("snapshot_source_set_invalid", lambda: contract.validate_snapshot(snap, self.rows))
        snap = copy.deepcopy(self.snapshot)
        snap["selectedRecords"]["metro.station"] = uid()
        self.assertCode("snapshot_record_reference_missing", lambda: contract.validate_snapshot(snap, self.rows))

    def test_record_reference_wrong_source(self):
        snap = copy.deepcopy(self.snapshot)
        snap["selectedRecords"]["metro.station"] = snap["selectedRecords"]["metro.railway"]
        self.assertCode("snapshot_record_reference_mismatch", lambda: contract.validate_snapshot(snap, self.rows))

    def test_fetch_batch_consistency_and_retry_relation(self):
        batch = uid()
        rows = [source(sid, mode="fetch", batch_id=batch) for sid in sorted(contract.SOURCE_IDS)]
        snap = snapshot(rows, mode="fetch", batch=batch)
        self.assertIs(contract.validate_snapshot(snap, rows), snap)
        mixed = copy.deepcopy(rows)
        mixed[0]["batchId"] = uid()
        self.assertCode("snapshot_batch_mismatch", lambda: contract.validate_snapshot(snap, mixed))
        parent = source("metro.station", mode="fetch", batch_id=batch, outcome="failed", error="http_error", retrieved=None)
        child = source("metro.station", mode="fetch", batch_id=batch, retry=parent["attemptId"],
                       start="2026-11-03T00:00:02Z", finish="2026-11-03T00:00:03Z",
                       retrieved="2026-11-03T00:00:03Z")
        all_records = rows + [parent, child]
        self.assertIs(contract.validate_snapshot(snap, all_records), snap)
        orphan = copy.deepcopy(child)
        orphan["retryOfAttemptId"] = uid()
        self.assertCode("retry_relation_invalid", lambda: contract.validate_snapshot(snap, rows + [orphan]))
        wrong_batch = copy.deepcopy(child)
        wrong_batch["batchId"] = uid()
        self.assertCode("retry_relation_invalid", lambda: contract.validate_snapshot(snap, rows + [parent, wrong_batch]))

    def test_failed_or_legacy_record_cannot_be_selected_as_fetch(self):
        batch = uid()
        rows = [source(sid, mode="fetch", batch_id=batch) for sid in sorted(contract.SOURCE_IDS)]
        failed = source("metro.station", mode="fetch", batch_id=batch, outcome="failed", error="http_error", retrieved=None)
        snap = snapshot(rows, mode="fetch", batch=batch)
        snap["selectedRecords"]["metro.station"] = failed["recordId"]
        self.assertCode("snapshot_record_reference_mismatch", lambda: contract.validate_snapshot(snap, rows + [failed]))

    def assertCode(self, expected, call):
        with self.assertRaises(contract.ContractError) as caught:
            call()
        self.assertEqual(caught.exception.code, expected)


if __name__ == "__main__":
    unittest.main()
