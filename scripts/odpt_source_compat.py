#!/usr/bin/env python3
"""Read-only compatibility check between a private Source/Snapshot store and ODPT-0."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

if __package__:
    from . import odpt_snapshot_qa as odpt0
    from .odpt_source_contract import SOURCE_FILES, SOURCE_IDS, content_fingerprint
    from .odpt_source_store import StoreError, load_store_contract, verify_store
else:
    import odpt_snapshot_qa as odpt0
    from odpt_source_contract import SOURCE_FILES, SOURCE_IDS, content_fingerprint
    from odpt_source_store import StoreError, load_store_contract, verify_store


class CompatibilityError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _fail(code: str) -> None:
    raise CompatibilityError(code)


def compare_inventories(records: list[dict[str, Any]], legacy_entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Match new Source records to ODPT-0 path/hash/size entries by fixed filename."""
    source_rows: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict):
            _fail("source_inventory_record_invalid")
        source_id = record.get("sourceId")
        if not isinstance(source_id, str) or source_id not in SOURCE_IDS:
            _fail("source_inventory_source_id_invalid")
        if source_id in source_rows:
            _fail("source_inventory_duplicate_source_id")
        source_rows[source_id] = record
    if set(source_rows) != SOURCE_IDS or len(records) != 7:
        _fail("source_inventory_source_set_mismatch")

    entry_rows: dict[str, dict[str, Any]] = {}
    expected_names = set(SOURCE_FILES.values())
    for entry in legacy_entries:
        if not isinstance(entry, dict) or set(entry) != {"path", "sizeBytes", "sha256"}:
            _fail("legacy_inventory_entry_invalid")
        path = entry["path"]
        if not isinstance(path, str) or path not in expected_names:
            _fail("legacy_inventory_path_invalid")
        if path in entry_rows:
            _fail("legacy_inventory_duplicate_path")
        entry_rows[path] = entry
    if set(entry_rows) != expected_names or len(legacy_entries) != 7:
        _fail("legacy_inventory_source_set_mismatch")

    results = []
    for source_id in sorted(SOURCE_IDS):
        record = source_rows[source_id]
        filename = SOURCE_FILES[source_id]
        artifact = record.get("artifact")
        if not isinstance(artifact, dict) or artifact.get("path") != f"raw/{filename}":
            _fail("source_id_filename_mapping_mismatch")
        entry = entry_rows[filename]
        digest_match = artifact.get("sha256") == entry.get("sha256")
        size_match = artifact.get("sizeBytes") == entry.get("sizeBytes")
        if not digest_match:
            _fail("source_hash_mismatch")
        if not size_match:
            _fail("source_byte_count_mismatch")
        results.append({"sourceId": source_id, "filename": filename,
                        "sha256Match": True, "byteCountMatch": True})
    return {"status": "PASS", "sourceCount": 7, "sources": results}


def _compare_metadata(records: list[dict[str, Any]], legacy_metadata: dict[str, Any]) -> dict[str, Any]:
    legacy_json = legacy_metadata.get("json")
    legacy_gtfs = legacy_metadata.get("gtfs")
    if not isinstance(legacy_json, dict) or not isinstance(legacy_gtfs, dict):
        _fail("legacy_metadata_structure_invalid")
    comparisons = []
    schema_differences = []
    mismatches = []
    for record in sorted(records, key=lambda row: row["sourceId"]):
        source_id = record["sourceId"]
        filename = SOURCE_FILES[source_id]
        source_metadata = record["metadata"]
        if source_id == "metro.gtfs":
            current = source_metadata["gtfs"]
            legacy = legacy_gtfs
            if not isinstance(current, dict):
                _fail("source_metadata_structure_invalid")
            fields = (("feedVersion", "feedVersion"), ("validFrom", "validFrom"),
                      ("validThrough", "validThrough"))
            for current_key, legacy_key in fields:
                if current.get(current_key) != legacy.get(legacy_key):
                    mismatches.append({"sourceId": source_id, "field": current_key,
                                   "classification": "shared_field_extraction_mismatch"})
            schema_differences.append({"sourceId": source_id, "field": "requiredMemberCount",
                                       "classification": "legacy_only_derived_field"})
            comparisons.append({"sourceId": source_id, "recordCount": "not-applicable",
                                "sharedFields": [field[0] for field in fields]})
            continue

        legacy = legacy_json.get(filename)
        current = source_metadata["odpt"]
        if not isinstance(legacy, dict) or not isinstance(current, dict):
            _fail("legacy_metadata_source_missing")
        if current.get("recordCount") != legacy.get("recordCount"):
            mismatches.append({"sourceId": source_id, "field": "recordCount",
                               "classification": "shared_field_extraction_mismatch"})
        for current_key, legacy_key in (("dcDates", "sourceDates"), ("issuedDates", "sourceIssuedDates")):
            values = current.get(current_key)
            legacy_values = legacy.get(legacy_key)
            if not isinstance(values, list) or not isinstance(legacy_values, list):
                _fail("metadata_date_values_invalid")
            if set(values) != set(legacy_values):
                mismatches.append({"sourceId": source_id, "field": current_key,
                                   "classification": "shared_field_extraction_mismatch"})
        schema_differences.append({"sourceId": source_id, "field": "dcDateMissingCount/issuedMissingCount",
                                   "classification": "new_only_missing_count_metrics"})
        comparisons.append({"sourceId": source_id, "recordCount": "compared",
                            "sharedFields": ["recordCount", "dc:date values", "dct:issued values"]})
    status = "mismatch" if mismatches else "compatible-with-extraction-differences" if schema_differences else "match"
    return {"status": status, "comparisons": comparisons,
            "schemaDifferences": schema_differences, "mismatches": mismatches,
            "rules": ["ODPT-0 casts non-null dc:date/dct:issued values to strings; new Source metadata accepts strings only.",
                      "ODPT-0 does not report missing-value counts for dc:date/dct:issued.",
                      "ODPT-0 reports required GTFS member count; the new Source metadata does not."]}


def compare_legacy(store_path: Path, source_dir: Path) -> dict[str, Any]:
    """Recompute both fingerprint formats and compare their source inventories read-only."""
    loaded = load_store_contract(store_path)
    snapshot = loaded["snapshot"]
    records = loaded["records"]
    new_fingerprint = content_fingerprint(records)
    if new_fingerprint != snapshot["contentFingerprint"]:
        _fail("source_snapshot_fingerprint_mismatch")

    current_check = verify_store(store_path, source_dir)
    if current_check["sourceBytesStatus"] != "match":
        _fail(f"source_reference_{current_check['sourceBytesStatus']}")
    try:
        legacy_entries, legacy_metadata = odpt0._inventory(source_dir)
    except odpt0.QAError as exc:
        _fail(f"odpt0_{exc.code}")
    inventory = compare_inventories(records, legacy_entries)
    legacy_fingerprint = odpt0._fingerprint(legacy_entries)
    if len(legacy_fingerprint) != 64:
        _fail("odpt0_fingerprint_invalid")
    metadata = _compare_metadata(records, legacy_metadata)

    # Repeat the old inventory read to guard against changes during comparison.
    try:
        final_entries, _ = odpt0._inventory(source_dir)
    except odpt0.QAError as exc:
        _fail(f"odpt0_{exc.code}")
    if final_entries != legacy_entries:
        _fail("source_changed_during_compare")
    final_store_check = verify_store(store_path, source_dir)
    if final_store_check["sourceBytesStatus"] != "match":
        _fail(f"source_reference_{final_store_check['sourceBytesStatus']}")

    return {
        "status": "PASS" if metadata["status"] != "mismatch" else "FAIL",
        "errorCode": None if metadata["status"] != "mismatch" else "metadata_shared_field_extraction_mismatch",
        "sourceInventory": inventory,
        "newSnapshotFingerprint": {"status": "PASS", "value": new_fingerprint},
        "odpt0Fingerprint": {"status": "PASS", "value": legacy_fingerprint,
                             "baselineComparison": "no-persisted-report-available"},
        "fingerprintsEqual": new_fingerprint == legacy_fingerprint,
        "currentSourceBytes": current_check["sourceBytes"],
        "metadataComparison": metadata,
        "acquisitionStatus": snapshot["acquisitionStatus"],
        "crossSourceConsistency": snapshot["crossSourceConsistency"],
        "publicationStatus": "not-assessed; compatibility check grants no approval",
    }
