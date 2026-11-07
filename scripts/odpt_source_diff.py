#!/usr/bin/env python3
"""Read-only Phase 2A comparison of two private Source/Snapshot stores."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

if __package__:
    from .odpt_source_contract import SOURCE_IDS
    from .odpt_source_store import StoreError
    from .odpt_evaluation_input import load_input as load_store_contract
else:
    from odpt_source_contract import SOURCE_IDS
    from odpt_source_store import StoreError
    from odpt_evaluation_input import load_input as load_store_contract


class SourceDiffError(ValueError):
    """Stable, non-sensitive comparison error."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _metadata_fields(source_id: str) -> tuple[tuple[str, str], ...]:
    if source_id == "metro.gtfs":
        return (("feedVersion", "gtfs"), ("validFrom", "gtfs"), ("validThrough", "gtfs"))
    return (("recordCount", "odpt"), ("dcDates", "odpt"), ("issuedDates", "odpt"),
            ("dcDateMissingCount", "odpt"), ("issuedMissingCount", "odpt"))


def _metadata_value(record: dict[str, Any], family: str, field: str) -> tuple[str, Any]:
    metadata = record.get("metadata")
    if not isinstance(metadata, dict) or set(metadata) != {"status", "gtfs", "odpt"}:
        return "invalid", None
    status = metadata.get("status")
    if status not in {"parsed", "unavailable"}:
        return "invalid", None
    if status == "unavailable":
        if metadata.get("gtfs") is not None or metadata.get("odpt") is not None:
            return "invalid", None
        return "unknown", None
    values = metadata.get(family)
    other = "odpt" if family == "gtfs" else "gtfs"
    if not isinstance(values, dict) or metadata.get(other) is not None:
        return "invalid", None
    expected = {name for name, item_family in _metadata_fields(record["sourceId"]) if item_family == family}
    if set(values) != expected:
        return "invalid", None
    return "known", values.get(field)


def _compare_metadata(baseline: dict[str, Any], candidate: dict[str, Any]) -> list[dict[str, Any]]:
    diffs = []
    for source_id in sorted(SOURCE_IDS):
        left = baseline[source_id]
        right = candidate[source_id]
        for field, family in _metadata_fields(source_id):
            left_state, left_value = _metadata_value(left, family, field)
            right_state, right_value = _metadata_value(right, family, field)
            if "invalid" in {left_state, right_state}:
                raise SourceDiffError("metadata_schema_invalid")
            if left_state == right_state == "unknown":
                status = "both-unknown"
            elif left_state != right_state:
                status = "one-unknown"
            elif left_value == right_value:
                status = "same"
            else:
                status = "different"
            diffs.append({"sourceId": source_id, "field": field, "status": status,
                          "baselineValue": left_value if left_state == "known" else None,
                          "candidateValue": right_value if right_state == "known" else None})
    return diffs


def _validated_store(path: Path, role: str) -> dict[str, Any]:
    try:
        return load_store_contract(path)
    except StoreError as exc:
        raise SourceDiffError(f"{role}_{exc.code}") from None


def compare_stores(baseline_path: Path, candidate_path: Path) -> dict[str, Any]:
    """Compare persisted records. Original source files are not needed or read."""
    baseline = _validated_store(baseline_path, "baseline")
    candidate = _validated_store(candidate_path, "candidate")
    left_records = {row["sourceId"]: row for row in baseline["records"]}
    right_records = {row["sourceId"]: row for row in candidate["records"]}
    # The store loader already enforces the fixed seven-source set, record refs,
    # schema version, and canonical fingerprint. Keep this invariant explicit.
    if set(left_records) != SOURCE_IDS or set(right_records) != SOURCE_IDS:
        raise SourceDiffError("source_set_invalid")

    source_diffs = []
    any_changed = False
    any_unavailable = False
    for source_id in sorted(SOURCE_IDS):
        left_artifact = left_records[source_id].get("artifact")
        right_artifact = right_records[source_id].get("artifact")
        if not isinstance(left_artifact, dict) or not isinstance(right_artifact, dict):
            source_status = "unavailable"
            left_hash = right_hash = left_size = right_size = None
            hash_match = size_match = None
            any_unavailable = True
        else:
            left_hash, right_hash = left_artifact["sha256"], right_artifact["sha256"]
            left_size, right_size = left_artifact["sizeBytes"], right_artifact["sizeBytes"]
            hash_match = left_hash == right_hash
            size_match = left_size == right_size
            source_status = "identical" if hash_match and size_match else "different"
            any_changed |= source_status == "different"
        source_diffs.append({"sourceId": source_id, "baselineHash": left_hash,
                             "candidateHash": right_hash, "baselineBytes": left_size,
                             "candidateBytes": right_size, "hashMatch": hash_match,
                             "byteCountMatch": size_match, "status": source_status})

    metadata_diffs = _compare_metadata(left_records, right_records)
    metadata_changed = any(row["status"] == "different" for row in metadata_diffs)
    metadata_unknown = any(row["status"] in {"both-unknown", "one-unknown"} for row in metadata_diffs)
    any_changed |= metadata_changed
    checks = {
        "baselineStoreContract": "PASS",
        "candidateStoreContract": "PASS",
        "fixedSevenSources": "PASS",
        "recordReferences": "PASS",
        "contentFingerprints": "PASS",
        "schemaVersions": "PASS",
        "sourceIdMapping": "PASS",
        "originalSourceBytes": "not-required; not-read",
    }
    if any_changed:
        overall = "changed"
    elif any_unavailable or metadata_unknown:
        overall = "unavailable"
    else:
        overall = "identical"
    return {
        "baselineSnapshotId": baseline["snapshot"]["snapshotId"],
        "candidateSnapshotId": candidate["snapshot"]["snapshotId"],
        "baselineContentFingerprint": baseline["snapshot"]["contentFingerprint"],
        "candidateContentFingerprint": candidate["snapshot"]["contentFingerprint"],
        "sourceDiffs": source_diffs,
        "metadataDiffs": metadata_diffs,
        "checks": checks,
        "overallBasicStatus": overall,
        "notImplemented": ["ODPT JSON semantic comparison", "GTFS timetable semantic comparison",
                           "itinerary quality comparison", "publication eligibility assessment"],
        "classificationScope": "Phase 2A basic status; separate from Phase 0 classification",
        "publicationApproval": "not-assessed",
    }
