#!/usr/bin/env python3
"""Strict offline validator for ODPT source-history contract v1.

This module validates in-memory records only. It performs no file I/O or
network access and is intentionally independent of existing QA/public paths.
"""
from __future__ import annotations

import json
import hashlib
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable


SOURCE_FILES = {
    "metro.railway": "Railway_all.json",
    "metro.station": "Station_all.json",
    "metro.train-timetable.yurakucho": "TrainTimetable_Yurakucho.json",
    "metro.train-timetable.fukutoshin": "TrainTimetable_Fukutoshin.json",
    "metro.station-timetable.yurakucho": "StationTimetable_Yurakucho.json",
    "metro.station-timetable.fukutoshin": "StationTimetable_Fukutoshin.json",
    "metro.gtfs": "TokyoMetro-Train-GTFS.zip",
}
ORIGIN_IDS = {
    "metro.railway": "odpt.Railway", "metro.station": "odpt.Station",
    "metro.train-timetable.yurakucho": "odpt.TrainTimetable.Yurakucho",
    "metro.train-timetable.fukutoshin": "odpt.TrainTimetable.Fukutoshin",
    "metro.station-timetable.yurakucho": "odpt.StationTimetable.Yurakucho",
    "metro.station-timetable.fukutoshin": "odpt.StationTimetable.Fukutoshin",
    "metro.gtfs": "metro.gtfs-file.v1",
}
SOURCE_IDS = frozenset(SOURCE_FILES)
SOURCE_FIELDS = frozenset({
    "contract", "schemaVersion", "recordId", "sourceId", "sourceType", "originId",
    "mode", "batchId", "attemptId", "retryOfAttemptId", "observedAt", "startedAt",
    "finishedAt", "retrievedAt", "outcome", "http", "errorCode", "artifact",
    "metadata", "unknownReasons",
})
SNAPSHOT_FIELDS = frozenset({
    "contract", "schemaVersion", "snapshotId", "createdAt", "mode", "batchId",
    "selectedRecords", "contentFingerprint", "completeness", "acquisitionStatus",
    "crossSourceConsistency",
})
HEX_256 = re.compile(r"[0-9a-f]{64}\Z")
RFC3339_UTC = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)\Z"
)


class ContractError(ValueError):
    """Stable, non-sensitive contract error."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _fail(code: str) -> None:
    raise ContractError(code)


def _exact_keys(value: Any, expected: frozenset[str], code: str) -> None:
    if not isinstance(value, dict):
        _fail(code)
    if set(value) != expected:
        _fail(code)


def _uuid(value: Any, *, nullable: bool = False) -> bool:
    if value is None:
        return nullable
    if not isinstance(value, str):
        return False
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError):
        return False
    return str(parsed) == value


def _timestamp(value: Any, *, nullable: bool = False) -> bool:
    if value is None:
        return nullable
    if not isinstance(value, str) or not RFC3339_UTC.fullmatch(value):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() == timezone.utc.utcoffset(parsed)


def _ordered(*values: str | None) -> bool:
    parsed = [datetime.fromisoformat(v.replace("Z", "+00:00")) for v in values if v is not None]
    return all(left <= right for left, right in zip(parsed, parsed[1:]))


def _valid_http(value: Any, *, nullable: bool) -> bool:
    if value is None:
        return nullable
    if not isinstance(value, dict) or set(value) != {"responses"}:
        return False
    rows = value["responses"]
    if not isinstance(rows, list) or not rows:
        return False
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"endpointId", "status", "contentType"}:
            return False
        if not isinstance(row["endpointId"], str) or not row["endpointId"]:
            return False
        if row["status"] is not None and (type(row["status"]) is not int or not 100 <= row["status"] <= 599):
            return False
        if row["contentType"] is not None and not isinstance(row["contentType"], str):
            return False
    return True


def _valid_artifact(value: Any, *, nullable: bool) -> bool:
    if value is None:
        return nullable
    if not isinstance(value, dict) or set(value) != {"path", "representation", "sha256", "sizeBytes"}:
        return False
    return (isinstance(value["path"], str) and value["path"].startswith("raw/")
            and value["path"] == value["path"].replace("\\", "/")
            and all(part not in {"", ".", ".."} for part in value["path"].split("/"))
            and isinstance(value["representation"], str) and value["representation"] in {"stored-file", "response-body"}
            and isinstance(value["sha256"], str) and HEX_256.fullmatch(value["sha256"]) is not None
            and type(value["sizeBytes"]) is int and value["sizeBytes"] >= 0)


def _valid_metadata(value: Any, source_id: str) -> bool:
    if not isinstance(value, dict) or set(value) != {"status", "gtfs", "odpt"}:
        return False
    if not isinstance(value["status"], str) or value["status"] not in {"parsed", "unavailable"}:
        return False
    if value["status"] == "unavailable":
        return value["gtfs"] is None and value["odpt"] is None
    if source_id == "metro.gtfs":
        if value["odpt"] is not None or not isinstance(value["gtfs"], dict):
            return False
        gtfs = value["gtfs"]
        return (set(gtfs) == {"feedVersion", "validFrom", "validThrough"}
                and isinstance(gtfs["feedVersion"], str) and bool(gtfs["feedVersion"])
                and isinstance(gtfs["validFrom"], str) and isinstance(gtfs["validThrough"], str)
                and bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", gtfs["validFrom"]))
                and bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", gtfs["validThrough"]))
                and gtfs["validFrom"] <= gtfs["validThrough"])
    if value["gtfs"] is not None or not isinstance(value["odpt"], dict):
        return False
    odpt = value["odpt"]
    return (set(odpt) == {"recordCount", "dcDates", "issuedDates", "dcDateMissingCount", "issuedMissingCount"}
            and type(odpt["recordCount"]) is int and odpt["recordCount"] >= 0
            and all(isinstance(odpt[key], list) and all(isinstance(item, str) for item in odpt[key])
                    for key in ("dcDates", "issuedDates"))
            and type(odpt["dcDateMissingCount"]) is int and odpt["dcDateMissingCount"] >= 0
            and type(odpt["issuedMissingCount"]) is int and odpt["issuedMissingCount"] >= 0
            and odpt["dcDateMissingCount"] <= odpt["recordCount"]
            and odpt["issuedMissingCount"] <= odpt["recordCount"])


def validate_source_record(record: Any) -> dict[str, Any]:
    """Validate one source record and return the original mapping."""
    _exact_keys(record, SOURCE_FIELDS, "source_record_fields_invalid")
    if record["contract"] != "odpt-source-record":
        _fail("source_contract_invalid")
    if type(record["schemaVersion"]) is not int or record["schemaVersion"] != 1:
        _fail("source_schema_version_unsupported")
    if not _uuid(record["recordId"]):
        _fail("record_id_invalid")
    source_id = record["sourceId"]
    if not isinstance(source_id, str) or source_id not in SOURCE_IDS:
        _fail("source_id_invalid")
    expected_type = "gtfs-zip" if source_id == "metro.gtfs" else "odpt-json"
    if record["sourceType"] != expected_type:
        _fail("source_type_invalid")
    if not isinstance(record["originId"], str) or record["originId"] != ORIGIN_IDS[source_id]:
        _fail("origin_id_invalid")
    if not isinstance(record["mode"], str) or record["mode"] not in {"legacy-observation", "fetch"}:
        _fail("source_mode_invalid")
    if not isinstance(record["unknownReasons"], list) or any(not isinstance(v, str) or not v for v in record["unknownReasons"]):
        _fail("unknown_reasons_invalid")
    if not _valid_metadata(record["metadata"], source_id):
        _fail("source_metadata_invalid")

    artifact = record["artifact"]
    if artifact is not None and not _valid_artifact(artifact, nullable=False):
        _fail("artifact_invalid")
    if artifact is not None and artifact["path"] != f"raw/{SOURCE_FILES[source_id]}":
        _fail("artifact_path_invalid")

    if record["mode"] == "legacy-observation":
        if (not _timestamp(record["observedAt"]) or any(record[k] is not None for k in
            ("batchId", "attemptId", "retryOfAttemptId", "startedAt", "finishedAt", "retrievedAt", "http", "errorCode"))
                or record["outcome"] != "observed" or artifact is None
                or "historical_acquisition_not_recorded" not in record["unknownReasons"]):
            _fail("legacy_observation_state_invalid")
        return record

    if not _uuid(record["batchId"]) or not _uuid(record["attemptId"]):
        _fail("attempt_id_invalid")
    if record["retryOfAttemptId"] is not None and not _uuid(record["retryOfAttemptId"]):
        _fail("retry_reference_invalid")
    if record["observedAt"] is not None or not _timestamp(record["startedAt"]) or not _timestamp(record["finishedAt"], nullable=True):
        _fail("attempt_timestamp_invalid")
    if not _timestamp(record["retrievedAt"], nullable=True) or not _valid_http(record["http"], nullable=True):
        _fail("attempt_result_invalid")
    if record["outcome"] == "succeeded":
        if (record["finishedAt"] is None or record["retrievedAt"] is None or artifact is None
                or record["errorCode"] is not None or record["http"] is None
                or record["http"]["responses"][-1]["status"] is None
                or not 200 <= record["http"]["responses"][-1]["status"] < 300):
            _fail("fetch_success_state_invalid")
    elif record["outcome"] == "failed":
        if (record["finishedAt"] is None or record["retrievedAt"] is not None or artifact is not None
                or not isinstance(record["errorCode"], str) or not record["errorCode"]):
            _fail("fetch_failure_state_invalid")
    elif record["outcome"] == "interrupted":
        if (record["finishedAt"] is not None or record["retrievedAt"] is not None or artifact is not None
                or not isinstance(record["errorCode"], str) or not record["errorCode"]):
            _fail("fetch_interruption_state_invalid")
    else:
        _fail("source_outcome_invalid")
    if not _ordered(record["startedAt"], record["finishedAt"], record["retrievedAt"]):
        _fail("attempt_timestamp_order_invalid")
    return record


def loads_record(text: str) -> dict[str, Any]:
    """Parse one JSON source record, rejecting duplicate keys and constants."""
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                _fail("json_duplicate_key")
            result[key] = value
        return result
    try:
        value = json.loads(text, object_pairs_hook=pairs,
                           parse_constant=lambda _value: _fail("json_constant_invalid"))
    except ContractError:
        raise
    except (json.JSONDecodeError, TypeError):
        _fail("json_invalid")
    return validate_source_record(value)


def content_fingerprint(records: Iterable[Any]) -> str:
    """Return the Phase 1A canonical fingerprint for selected source records."""
    rows = [{"sourceId": row["sourceId"], "sha256": row["artifact"]["sha256"],
             "sizeBytes": row["artifact"]["sizeBytes"]}
            for row in sorted(records, key=lambda value: value["sourceId"])]
    encoded = json.dumps(rows, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_snapshot(snapshot: Any, records: Iterable[Any]) -> dict[str, Any]:
    """Validate a snapshot and all referenced records, including retries."""
    _exact_keys(snapshot, SNAPSHOT_FIELDS, "snapshot_fields_invalid")
    if snapshot["contract"] != "odpt-source-snapshot":
        _fail("snapshot_contract_invalid")
    if type(snapshot["schemaVersion"]) is not int or snapshot["schemaVersion"] != 1:
        _fail("snapshot_schema_version_unsupported")
    if not _uuid(snapshot["snapshotId"]) or not _timestamp(snapshot["createdAt"]):
        _fail("snapshot_identity_invalid")
    if not isinstance(snapshot["contentFingerprint"], str) or not HEX_256.fullmatch(snapshot["contentFingerprint"]):
        _fail("snapshot_fingerprint_invalid")
    if not isinstance(snapshot["completeness"], str) or snapshot["completeness"] != "complete":
        _fail("snapshot_completeness_invalid")
    if (not isinstance(snapshot["acquisitionStatus"], str)
            or snapshot["acquisitionStatus"] not in {"historical-unknown", "fetch-success"}):
        _fail("snapshot_acquisition_status_invalid")
    if (not isinstance(snapshot["crossSourceConsistency"], str)
            or snapshot["crossSourceConsistency"] not in {"not-evaluated", "consistent", "inconsistent"}):
        _fail("snapshot_cross_source_consistency_invalid")
    if not isinstance(snapshot["selectedRecords"], dict) or set(snapshot["selectedRecords"]) != SOURCE_IDS:
        _fail("snapshot_source_set_invalid")
    if not isinstance(snapshot["mode"], str) or snapshot["mode"] not in {"legacy-observation", "fetch"}:
        _fail("snapshot_mode_invalid")
    if ((snapshot["mode"] == "legacy-observation" and snapshot["acquisitionStatus"] != "historical-unknown")
            or (snapshot["mode"] == "fetch" and snapshot["acquisitionStatus"] != "fetch-success")):
        _fail("snapshot_acquisition_status_invalid")
    if snapshot["mode"] == "legacy-observation" and snapshot["crossSourceConsistency"] != "not-evaluated":
        _fail("snapshot_cross_source_consistency_invalid")
    if snapshot["mode"] == "legacy-observation":
        if snapshot["batchId"] is not None:
            _fail("snapshot_batch_invalid")
    elif not _uuid(snapshot["batchId"]):
        _fail("snapshot_batch_invalid")

    by_record: dict[str, dict[str, Any]] = {}
    by_attempt: dict[str, dict[str, Any]] = {}
    for raw in records:
        record = validate_source_record(raw)
        if record["recordId"] in by_record:
            _fail("record_id_duplicate")
        by_record[record["recordId"]] = record
        if record["attemptId"] is not None:
            if record["attemptId"] in by_attempt:
                _fail("attempt_id_duplicate")
            by_attempt[record["attemptId"]] = record

    for record in by_record.values():
        parent_id = record["retryOfAttemptId"]
        if parent_id is None:
            continue
        parent = by_attempt.get(parent_id)
        if (parent is None or parent["outcome"] not in {"failed", "interrupted"}
                or parent["sourceId"] != record["sourceId"] or parent["batchId"] != record["batchId"]
                or parent["attemptId"] == record["attemptId"]
                or (parent["finishedAt"] is not None and record["startedAt"] < parent["finishedAt"])):
            _fail("retry_relation_invalid")
    for record in by_record.values():
        seen: set[str] = set()
        cursor = record
        while cursor["retryOfAttemptId"] is not None:
            attempt = cursor["attemptId"]
            if attempt in seen:
                _fail("retry_cycle_invalid")
            seen.add(attempt)
            cursor = by_attempt[cursor["retryOfAttemptId"]]

    selected: list[dict[str, Any]] = []
    for source_id, record_id in snapshot["selectedRecords"].items():
        if not _uuid(record_id) or record_id not in by_record:
            _fail("snapshot_record_reference_missing")
        record = by_record[record_id]
        if record["sourceId"] != source_id or record["outcome"] not in {"observed", "succeeded"}:
            _fail("snapshot_record_reference_mismatch")
        if snapshot["mode"] == "legacy-observation":
            if record["mode"] != "legacy-observation":
                _fail("snapshot_mode_mismatch")
        elif record["mode"] != "fetch" or record["batchId"] != snapshot["batchId"]:
            _fail("snapshot_batch_mismatch")
        selected.append(record)
    if content_fingerprint(selected) != snapshot["contentFingerprint"]:
        _fail("snapshot_fingerprint_mismatch")
    selected_times = [r["observedAt"] if snapshot["mode"] == "legacy-observation" else r["retrievedAt"] for r in selected]
    if any(value is None for value in selected_times):
        _fail("snapshot_acquisition_time_unknown")
    created = datetime.fromisoformat(snapshot["createdAt"].replace("Z", "+00:00"))
    if any(datetime.fromisoformat(value.replace("Z", "+00:00")) > created for value in selected_times):
        _fail("snapshot_created_before_record")
    return snapshot
