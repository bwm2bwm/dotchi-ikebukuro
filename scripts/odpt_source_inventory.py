#!/usr/bin/env python3
"""Inspect, persist, or verify private metadata records for saved ODPT sources.

The default inspect operation is read-only. Persistence requires an explicit
new store path and writes metadata only; this CLI never copies raw sources or
accesses a network.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import stat
import sys
import uuid
import zipfile
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from odpt_snapshot_qa import DEFAULT_SNAPSHOT
from odpt_source_contract import ORIGIN_IDS, SOURCE_FILES, SOURCE_IDS, ContractError, validate_source_record


MAX_SOURCE_BYTES = 128 * 1024 * 1024
MAX_ZIP_MEMBER_BYTES = 64 * 1024 * 1024
MAX_ZIP_TOTAL_BYTES = 256 * 1024 * 1024
MAX_ZIP_RATIO = 1000
GTFS_MEMBERS = frozenset({"feed_info.txt", "calendar.txt", "calendar_dates.txt", "stops.txt",
                          "routes.txt", "trips.txt", "stop_times.txt"})
SAFE_GTFS_FILENAME = re.compile(r"[A-Za-z0-9_-]+\.txt\Z")


class InventoryError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _fail(code: str) -> None:
    raise InventoryError(code)


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail("json_duplicate_key")
        result[key] = value
    return result


def _parse_json(raw: bytes) -> list[dict[str, Any]]:
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicates,
                           parse_constant=lambda _value: _fail("json_constant_invalid"))
    except InventoryError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        _fail("json_invalid")
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        _fail("json_structure_invalid")
    return value


def _date_text(value: Any) -> str:
    if not isinstance(value, str) or len(value) != 8 or not value.isascii() or not value.isdigit():
        _fail("gtfs_date_invalid")
    try:
        return datetime.strptime(value, "%Y%m%d").date().isoformat()
    except ValueError:
        _fail("gtfs_date_invalid")


def _read_gtfs_metadata(raw: bytes) -> dict[str, str]:
    if len(raw) > MAX_SOURCE_BYTES:
        _fail("source_size_limit_exceeded")
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if len(names) != len(set(names)):
                _fail("zip_duplicate_entry")
            if any(not SAFE_GTFS_FILENAME.fullmatch(name) for name in names):
                _fail("zip_entry_path_unsafe")
            if not GTFS_MEMBERS.issubset(set(names)):
                _fail("gtfs_required_member_missing")
            total = 0
            for info in infos:
                if info.is_dir() or info.flag_bits & 0x1:
                    _fail("zip_entry_type_unsafe")
                mode = (info.external_attr >> 16) & 0xFFFF
                if stat.S_ISLNK(mode):
                    _fail("zip_entry_type_unsafe")
                if info.file_size < 0 or info.file_size > MAX_ZIP_MEMBER_BYTES:
                    _fail("zip_member_size_limit_exceeded")
                total += info.file_size
                if total > MAX_ZIP_TOTAL_BYTES:
                    _fail("zip_total_size_limit_exceeded")
                if info.file_size and info.compress_size == 0:
                    _fail("zip_compression_ratio_exceeded")
                if info.compress_size and info.file_size / info.compress_size > MAX_ZIP_RATIO:
                    _fail("zip_compression_ratio_exceeded")
            if archive.testzip() is not None:
                _fail("gtfs_zip_invalid")
            feed_raw = archive.read("feed_info.txt")
            if len(feed_raw) > MAX_ZIP_MEMBER_BYTES:
                _fail("gtfs_feed_info_size_limit_exceeded")
            rows = list(csv.DictReader(io.StringIO(feed_raw.decode("utf-8-sig"))))
    except InventoryError:
        raise
    except (zipfile.BadZipFile, RuntimeError, OSError, UnicodeDecodeError, csv.Error,
            zlib.error, EOFError, NotImplementedError):
        _fail("gtfs_zip_invalid")
    if len(rows) != 1:
        _fail("gtfs_feed_info_invalid")
    row = rows[0]
    version = row.get("feed_version")
    if not isinstance(version, str) or not version.strip():
        _fail("gtfs_feed_version_missing")
    start = _date_text(row.get("feed_start_date"))
    end = _date_text(row.get("feed_end_date"))
    if start > end:
        _fail("gtfs_feed_period_invalid")
    return {"feedVersion": version, "validFrom": start, "validThrough": end}


def _stable_read(path: Path, source_id: str) -> tuple[bytes, dict[str, Any]]:
    try:
        before = path.lstat()
    except OSError:
        _fail("source_read_failed")
    if not stat.S_ISREG(before.st_mode) or path.is_symlink():
        _fail("source_not_regular_file")
    if before.st_size > MAX_SOURCE_BYTES:
        _fail("source_size_limit_exceeded")
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as stream:
            raw = stream.read(MAX_SOURCE_BYTES + 1)
            after_fd = os.fstat(stream.fileno())
        after_path = path.lstat()
    except OSError:
        _fail("source_read_failed")
    if len(raw) > MAX_SOURCE_BYTES:
        _fail("source_size_limit_exceeded")
    identity_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    identity_fd = (after_fd.st_dev, after_fd.st_ino, after_fd.st_size, after_fd.st_mtime_ns)
    identity_path = (after_path.st_dev, after_path.st_ino, after_path.st_size, after_path.st_mtime_ns)
    if identity_before != identity_fd or identity_before != identity_path or len(raw) != before.st_size:
        _fail("source_changed_while_reading")

    if source_id == "metro.gtfs":
        metadata = {"status": "parsed", "gtfs": _read_gtfs_metadata(raw), "odpt": None}
    else:
        records = _parse_json(raw)
        for row in records:
            for key in ("dc:date", "dct:issued"):
                if key in row and row[key] is not None and not isinstance(row[key], str):
                    _fail("odpt_metadata_invalid")
        dc_dates = sorted({row["dc:date"] for row in records if isinstance(row.get("dc:date"), str)})
        issued_dates = sorted({row["dct:issued"] for row in records if isinstance(row.get("dct:issued"), str)})
        metadata = {"status": "parsed", "gtfs": None, "odpt": {
            "recordCount": len(records), "dcDates": dc_dates, "issuedDates": issued_dates,
            "dcDateMissingCount": sum("dc:date" not in row or row["dc:date"] is None for row in records),
            "issuedMissingCount": sum("dct:issued" not in row or row["dct:issued"] is None for row in records),
        }}
    if not validate_metadata_contract(metadata, source_id):
        _fail("source_metadata_invalid")
    return raw, metadata


def validate_metadata_contract(metadata: dict[str, Any], source_id: str) -> bool:
    """Apply the same metadata shape checked by Phase 1A without a fake record."""
    if metadata["status"] != "parsed":
        return False
    if source_id == "metro.gtfs":
        return metadata["gtfs"] is not None and metadata["odpt"] is None
    odpt = metadata["odpt"]
    return (metadata["gtfs"] is None and isinstance(odpt, dict)
            and set(odpt) == {"recordCount", "dcDates", "issuedDates", "dcDateMissingCount", "issuedMissingCount"}
            and type(odpt["recordCount"]) is int and type(odpt["dcDateMissingCount"]) is int
            and type(odpt["issuedMissingCount"]) is int)


def _record(source_id: str, relative_ref: str, raw: bytes, metadata: dict[str, Any], observed_at: str) -> dict[str, Any]:
    return {
        "contract": "odpt-source-record", "schemaVersion": 1, "recordId": str(uuid.uuid4()),
        "sourceId": source_id, "sourceType": "gtfs-zip" if source_id == "metro.gtfs" else "odpt-json",
        "originId": ORIGIN_IDS[source_id], "mode": "legacy-observation",
        "batchId": None, "attemptId": None, "retryOfAttemptId": None,
        "observedAt": observed_at, "startedAt": None, "finishedAt": None, "retrievedAt": None,
        "outcome": "observed", "http": None, "errorCode": None,
        "artifact": {"path": relative_ref, "representation": "stored-file",
                     "sha256": hashlib.sha256(raw).hexdigest(), "sizeBytes": len(raw)},
        "metadata": metadata, "unknownReasons": ["historical_acquisition_not_recorded"],
    }


def generate_inventory(source_dir: Path, observed_at: str | None = None,
                       read_hook: Callable[[Path, str], tuple[bytes, dict[str, Any]]] | None = None) -> dict[str, Any]:
    """Generate and validate seven in-memory legacy records; persist nothing."""
    when = observed_at or datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    if not isinstance(when, str):
        _fail("observed_at_invalid")
    reader = read_hook or _stable_read
    try:
        root = source_dir.resolve(strict=True)
        if not root.is_dir():
            _fail("source_directory_invalid")
    except InventoryError:
        raise
    except (OSError, RuntimeError):
        _fail("source_directory_invalid")
    records = []
    before = {}
    source_paths: dict[str, Path] = {}
    for source_id in sorted(SOURCE_IDS):
        filename = SOURCE_FILES[source_id]
        path = root / filename
        try:
            source_stat = path.lstat()
        except OSError:
            _fail("source_missing_or_outside_root")
        if not stat.S_ISREG(source_stat.st_mode) or stat.S_ISLNK(source_stat.st_mode):
            _fail("source_not_regular_file")
        raw, metadata = reader(path, source_id)
        record = _record(source_id, f"raw/{filename}", raw, metadata, when)
        try:
            validate_source_record(record)
        except ContractError as exc:
            _fail("source_contract_invalid")
        records.append(record)
        before[source_id] = (record["artifact"]["sha256"], record["artifact"]["sizeBytes"])
        source_paths[source_id] = path
    for source_id, expected in before.items():
        raw, _metadata = reader(source_paths[source_id], source_id)
        actual = (hashlib.sha256(raw).hexdigest(), len(raw))
        if actual != expected:
            _fail("source_changed_during_inventory")
    return {"status": "PASS", "sourceCount": len(records), "records": records}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs="?", choices=("inspect", "persist", "verify", "compare-legacy"), default="inspect")
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument("--store", type=Path)
    args = parser.parse_args(argv)
    if args.command != "inspect" and args.store is None:
        parser.error(f"--store is required for {args.command}")
    if args.command == "inspect" and args.store is not None:
        parser.error("--store is only valid for persist, verify, or compare-legacy")

    if args.command == "inspect":
        try:
            result = generate_inventory(args.source_dir)
        except InventoryError as exc:
            print(f"inventory=FAIL error={exc.code}")
            return 1
        print(f"inventory={result['status']} source_count={result['sourceCount']}")
        for row in result["records"]:
            print(f"source_id={row['sourceId']} bytes={row['artifact']['sizeBytes']} sha256={row['artifact']['sha256']}")
        return 0

    try:
        from odpt_source_store import StoreError
        from odpt_source_compat import CompatibilityError
        if args.command == "persist":
            from odpt_source_store import persist_snapshot
            result = persist_snapshot(args.store, args.source_dir)
            verified = result["verification"]
            print(f"persist=PASS source_count={result['sourceCount']} snapshot_id={verified['snapshotId']} "
                  f"record_validation={verified['recordStatus']} source_bytes={verified['sourceBytesStatus']} "
                  f"content_fingerprint={verified['contentFingerprint']}")
            return 0
        if args.command == "verify":
            from odpt_source_store import verify_store
            result = verify_store(args.store, args.source_dir)
            print(f"verify_records={result['recordStatus']} snapshot_id={result['snapshotId']} "
                  f"source_bytes={result['sourceBytesStatus']} matched={result['sourceBytes']['matched']} "
                  f"missing={result['sourceBytes']['missing']} mismatched={result['sourceBytes']['mismatched']} "
                  f"content_fingerprint={result['contentFingerprint']}")
            return 0 if result["sourceBytesStatus"] == "match" else 2
        from odpt_source_compat import compare_legacy
        result = compare_legacy(args.store, args.source_dir)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        return 0 if result["status"] == "PASS" else 2
    except (InventoryError, StoreError, CompatibilityError) as exc:
        operation = "persist" if args.command == "persist" else "verify"
        print(f"{operation}=FAIL error={exc.code}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
