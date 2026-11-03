#!/usr/bin/env python3
"""Private, atomic persistence and verification for ODPT source snapshots.

Only Source/Snapshot metadata is stored. This module never copies raw sources
or accesses a network.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

if __package__:
    from .odpt_source_contract import (SOURCE_FILES, SOURCE_IDS, ContractError, content_fingerprint,
                                       loads_record, validate_snapshot, validate_source_record)
    from .odpt_source_inventory import InventoryError, _stable_read, generate_inventory
else:
    from odpt_source_contract import (SOURCE_FILES, SOURCE_IDS, ContractError, content_fingerprint,
                                      loads_record, validate_snapshot, validate_source_record)
    from odpt_source_inventory import InventoryError, _stable_read, generate_inventory


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PRIVATE_MODE = 0o700
FILE_MODE = 0o600
MAX_RECORD_FILE_BYTES = 16 * 1024 * 1024
RESERVED_PUBLIC_COMPONENTS = frozenset({"public", "_site", "dist", "build", "pages"})


class StoreError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _fail(code: str) -> None:
    raise StoreError(code)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                       allow_nan=False) + "\n").encode("utf-8")


def _is_within(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False


def _assert_external_store_location(destination: Path) -> None:
    if _is_within(destination, PROJECT_ROOT):
        _fail("store_path_inside_repository")
    if any(part.lower() in RESERVED_PUBLIC_COMPONENTS for part in destination.parts):
        _fail("store_path_public_like")
    home = Path.home().resolve()
    protected_roots = (
        home / "Library" / "Application Support" / "dotchi-ikebukuro-odpt-qa",
        home / "Library" / "Application Support" / "dotchi-ikebukuro-preview",
    )
    for protected in protected_roots:
        if _is_within(destination, protected):
            _fail("store_path_reserved_output")


def _check_path_components(path: Path) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue
        except OSError:
            _fail("store_path_unreadable")
        if stat.S_ISLNK(info.st_mode):
            _fail("store_path_symlink")


def _safe_new_store_path(value: Path) -> Path:
    if not isinstance(value, Path) or not value.is_absolute():
        _fail("store_path_must_be_absolute")
    if ".." in value.parts or value.name in {"", ".", ".."}:
        _fail("store_path_traversal")
    _check_path_components(value)
    try:
        parent = value.parent.resolve(strict=True)
        if not parent.is_dir():
            _fail("store_parent_invalid")
    except StoreError:
        raise
    except (OSError, RuntimeError):
        _fail("store_parent_invalid")
    destination = parent / value.name
    _assert_external_store_location(destination)
    if destination.exists():
        _fail("store_destination_exists")
    return destination


def _safe_existing_store_path(value: Path) -> Path:
    if not isinstance(value, Path) or not value.is_absolute():
        _fail("store_path_must_be_absolute")
    if ".." in value.parts:
        _fail("store_path_traversal")
    _check_path_components(value)
    try:
        resolved = value.resolve(strict=True)
        info = resolved.lstat()
    except (OSError, RuntimeError):
        _fail("store_not_found")
    if not stat.S_ISDIR(info.st_mode):
        _fail("store_directory_invalid")
    _assert_external_store_location(resolved)
    if stat.S_IMODE(info.st_mode) & 0o077:
        _fail("store_directory_permissions_unsafe")
    return resolved


def create_snapshot(records: list[dict[str, Any]], created_at: str | None = None) -> dict[str, Any]:
    """Build a complete legacy-observation snapshot using Phase 1A fingerprinting."""
    by_source = {record["sourceId"]: record for record in records}
    if set(by_source) != SOURCE_IDS or len(by_source) != 7:
        _fail("snapshot_source_set_invalid")
    selected = {source_id: by_source[source_id]["recordId"] for source_id in sorted(SOURCE_IDS)}
    snapshot = {
        "contract": "odpt-source-snapshot", "schemaVersion": 1,
        "snapshotId": str(uuid.uuid4()), "createdAt": created_at or _utc_now(),
        "mode": "legacy-observation", "batchId": None, "selectedRecords": selected,
        "contentFingerprint": content_fingerprint(list(by_source.values())),
        "completeness": "complete", "acquisitionStatus": "historical-unknown",
        "crossSourceConsistency": "not-evaluated",
    }
    try:
        validate_snapshot(snapshot, records)
    except ContractError as exc:
        _fail(f"snapshot_contract_{exc.code}")
    return snapshot


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_atomic(directory: Path, filename: str, content: bytes) -> None:
    if Path(filename).name != filename or filename in {".", ".."}:
        _fail("store_filename_invalid")
    temporary = directory / f".{filename}.{uuid.uuid4().hex}.tmp"
    final = directory / filename
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = -1
    try:
        descriptor = os.open(temporary, flags, FILE_MODE)
        os.fchmod(descriptor, FILE_MODE)
        view = memoryview(content)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                _fail("store_write_failed")
            view = view[written:]
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        if final.exists() or final.is_symlink():
            _fail("store_file_collision")
        os.rename(temporary, final)
        _fsync_directory(directory)
    except StoreError:
        raise
    except OSError:
        _fail("store_write_failed")
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _cleanup_created_store(path: Path, identity: tuple[int, int]) -> None:
    try:
        info = path.lstat()
        if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
                or (info.st_dev, info.st_ino) != identity):
            return
        shutil.rmtree(path)
        _fsync_directory(path.parent)
    except OSError:
        # A leftover directory without snapshot.json is deliberately unverifiable.
        return


def persist_snapshot(store_path: Path, source_dir: Path,
                     fault_hook: Callable[[str], None] | None = None) -> dict[str, Any]:
    """Create a new private store. snapshot.json is the final commit marker."""
    destination = _safe_new_store_path(store_path)
    observed_at = _utc_now()
    try:
        inventory = generate_inventory(source_dir, observed_at=observed_at)
        records = inventory["records"]
        snapshot = create_snapshot(records, created_at=observed_at)
    except InventoryError:
        raise

    try:
        os.mkdir(destination, PRIVATE_MODE)
    except FileExistsError:
        _fail("store_destination_exists")
    except OSError:
        _fail("store_create_failed")
    info = destination.lstat()
    identity = (info.st_dev, info.st_ino)
    hook = fault_hook or (lambda _stage: None)
    try:
        os.chmod(destination, PRIVATE_MODE)
        _fsync_directory(destination.parent)
        sources_dir = destination / "sources"
        os.mkdir(sources_dir, PRIVATE_MODE)
        os.chmod(sources_dir, PRIVATE_MODE)
        _fsync_directory(destination)
        for index, record in enumerate(records, start=1):
            validate_source_record(record)
            _write_atomic(sources_dir, f"{record['sourceId']}.json", _json_bytes(record))
            hook(f"source-written-{index}")
        hook("before-snapshot-commit")
        # snapshot.json appears only after all seven Source records are durable.
        _write_atomic(destination, "snapshot.json", _json_bytes(snapshot))
        hook("after-snapshot-commit")
        verified = verify_store(destination, source_dir)
        if verified["sourceBytesStatus"] != "match":
            _fail("source_reference_verification_failed")
        return {"snapshot": snapshot, "sourceCount": len(records), "verification": verified}
    except (StoreError, ContractError):
        _cleanup_created_store(destination, identity)
        raise
    except OSError:
        _cleanup_created_store(destination, identity)
        _fail("store_write_failed")
    except Exception:
        _cleanup_created_store(destination, identity)
        _fail("store_write_failed")


def _read_store_file(path: Path) -> bytes:
    try:
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or stat.S_ISLNK(before.st_mode):
            _fail("store_record_file_invalid")
        if before.st_size > MAX_RECORD_FILE_BYTES:
            _fail("store_record_size_limit_exceeded")
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(descriptor, "rb") as stream:
            raw = stream.read(MAX_RECORD_FILE_BYTES + 1)
            after_fd = os.fstat(stream.fileno())
        after_path = path.lstat()
    except StoreError:
        raise
    except OSError:
        _fail("store_record_read_failed")
    if len(raw) > MAX_RECORD_FILE_BYTES:
        _fail("store_record_size_limit_exceeded")
    identity_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    identity_fd = (after_fd.st_dev, after_fd.st_ino, after_fd.st_size, after_fd.st_mtime_ns)
    identity_path = (after_path.st_dev, after_path.st_ino, after_path.st_size, after_path.st_mtime_ns)
    if identity_before != identity_fd or identity_before != identity_path or len(raw) != before.st_size:
        _fail("store_record_changed_while_reading")
    return raw


def _load_json_object(path: Path) -> Any:
    try:
        text = _read_store_file(path).decode("utf-8")
    except UnicodeDecodeError:
        _fail("store_json_invalid")
    try:
        def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, value in items:
                if key in result:
                    _fail("store_json_duplicate_key")
                result[key] = value
            return result
        value = json.loads(text, object_pairs_hook=pairs,
                           parse_constant=lambda _value: _fail("store_json_constant_invalid"))
    except StoreError:
        raise
    except (json.JSONDecodeError, ValueError):
        _fail("store_json_invalid")
    if not isinstance(value, dict):
        _fail("store_json_structure_invalid")
    return value


def _verify_source_bytes(records: list[dict[str, Any]], source_dir: Path | None) -> dict[str, Any]:
    if source_dir is None:
        return {"status": "unavailable", "matched": 0, "missing": 0, "mismatched": 0}
    try:
        root = source_dir.resolve(strict=True)
        if not root.is_dir():
            return {"status": "unavailable", "matched": 0, "missing": 0, "mismatched": 0}
    except (OSError, RuntimeError):
        return {"status": "unavailable", "matched": 0, "missing": 0, "mismatched": 0}
    matched = missing = mismatched = 0
    for record in records:
        source_id = record["sourceId"]
        path = root / SOURCE_FILES[source_id]
        try:
            path.lstat()
        except FileNotFoundError:
            missing += 1
            continue
        except OSError:
            mismatched += 1
            continue
        try:
            raw, _metadata = _stable_read(path, source_id)
        except InventoryError:
            mismatched += 1
            continue
        digest, size = hashlib.sha256(raw).hexdigest(), len(raw)
        artifact = record["artifact"]
        if digest == artifact["sha256"] and size == artifact["sizeBytes"]:
            matched += 1
        else:
            mismatched += 1
    if mismatched:
        status = "mismatch"
    elif missing:
        status = "missing"
    elif matched == 7:
        status = "match"
    else:
        status = "unavailable"
    return {"status": status, "matched": matched, "missing": missing, "mismatched": mismatched}


def load_store_contract(store_path: Path) -> dict[str, Any]:
    """Read and validate a completed store without checking external raw sources."""
    root = _safe_existing_store_path(store_path)
    try:
        root_entries = {entry.name for entry in root.iterdir()}
    except OSError:
        _fail("store_read_failed")
    if "snapshot.json" not in root_entries:
        _fail("store_incomplete_snapshot")
    if root_entries != {"sources", "snapshot.json"}:
        _fail("store_contents_invalid")
    sources_dir = root / "sources"
    try:
        info = sources_dir.lstat()
    except OSError:
        _fail("store_sources_directory_missing")
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077:
        _fail("store_sources_directory_invalid")
    expected_names = {f"{source_id}.json" for source_id in SOURCE_IDS}
    try:
        if {entry.name for entry in sources_dir.iterdir()} != expected_names:
            _fail("store_source_set_invalid")
    except OSError:
        _fail("store_read_failed")
    records = []
    for source_id in sorted(SOURCE_IDS):
        path = sources_dir / f"{source_id}.json"
        try:
            file_info = path.lstat()
        except OSError:
            _fail("store_record_read_failed")
        if not stat.S_ISREG(file_info.st_mode) or stat.S_ISLNK(file_info.st_mode):
            _fail("store_record_file_invalid")
        if stat.S_IMODE(file_info.st_mode) & 0o077:
            _fail("store_file_permissions_unsafe")
        try:
            record = loads_record(_read_store_file(path).decode("utf-8"))
        except UnicodeDecodeError:
            _fail("store_json_invalid")
        except ContractError as exc:
            _fail(f"store_source_record_{exc.code}")
        if record["sourceId"] != source_id:
            _fail("store_record_source_mismatch")
        records.append(record)

    snapshot_path = root / "snapshot.json"
    try:
        snapshot_info = snapshot_path.lstat()
    except OSError:
        _fail("store_record_read_failed")
    if not stat.S_ISREG(snapshot_info.st_mode) or stat.S_ISLNK(snapshot_info.st_mode):
        _fail("store_record_file_invalid")
    if stat.S_IMODE(snapshot_info.st_mode) & 0o077:
        _fail("store_file_permissions_unsafe")
    snapshot = _load_json_object(snapshot_path)
    try:
        validate_snapshot(snapshot, records)
    except ContractError as exc:
        _fail(f"store_snapshot_{exc.code}")
    return {"snapshot": snapshot, "records": records}


def verify_store(store_path: Path, source_dir: Path | None = None) -> dict[str, Any]:
    """Validate a persisted snapshot and optionally compare all referenced bytes."""
    loaded = load_store_contract(store_path)
    snapshot = loaded["snapshot"]
    records = loaded["records"]
    source_result = _verify_source_bytes(records, source_dir)
    return {"recordStatus": "PASS", "snapshotId": snapshot["snapshotId"],
            "contentFingerprint": snapshot["contentFingerprint"],
            "sourceBytesStatus": source_result["status"], "sourceBytes": source_result}
