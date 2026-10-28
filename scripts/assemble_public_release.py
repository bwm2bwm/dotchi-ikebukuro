#!/usr/bin/env python3
"""Assemble a validated release artifact with deterministic generation retention."""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile
from typing import Any
from zoneinfo import ZoneInfo

from release_contract import (
    STATION_FILES,
    canonicalize_jcs,
    create_manifest,
    sha256_hex,
    verify_envelope_bytes,
    validate_manifest,
    encode_manifest,
)
from public_payload_profile import validate_public_payload
from validate_public_artifact import (
    ArtifactValidationError,
    validate_artifact,
    validate_release_managed_artifact,
)

JST = ZoneInfo("Asia/Tokyo")
MIN_RETENTION = timedelta(days=7)
MAX_RETENTION = timedelta(days=14)
VALIDITY_GRACE = timedelta(hours=48)
DELETE_SAFETY_MARGIN = timedelta(hours=24)
LEGACY_RETENTION = timedelta(days=14)
MAX_FILES_DEFAULT = 20_000
MAX_ASSET_BYTES_DEFAULT = 25 * 1024 * 1024
MAX_TOTAL_BYTES_DEFAULT = 256 * 1024 * 1024


class AssemblyError(ValueError):
    """Raised when a source cannot be safely assembled into a deployable tree."""


def _read_manifest(root: Path) -> dict[str, Any]:
    try:
        value = json.loads((root / "manifest.json").read_text(encoding="utf-8"),
                           object_pairs_hook=_unique_object)
        return validate_manifest(value)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise AssemblyError(f"invalid source manifest: {error}") from None


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise AssemblyError("duplicate JSON member in source manifest")
        value[key] = item
    return value


def _timestamp(value: str) -> datetime:
    if not isinstance(value, str):
        raise AssemblyError("timestamp must be an ISO-8601 string with timezone")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise AssemblyError("timestamp must be an ISO-8601 string with timezone") from None
    if result.tzinfo is None or result.utcoffset() is None:
        raise AssemblyError("timestamp must include a timezone offset")
    return result.astimezone(timezone.utc)


def _format_timestamp(value: datetime) -> str:
    instant = value.astimezone(timezone.utc)
    precision = "microseconds" if instant.microsecond else "seconds"
    return instant.isoformat(timespec=precision).replace("+00:00", "Z")


def _as_of(value: str | datetime) -> datetime:
    instant = _timestamp(value) if isinstance(value, str) else value
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise AssemblyError("evaluation time must be timezone-aware")
    return instant.astimezone(timezone.utc)


def _effective_validity_end(payload: dict[str, Any]) -> datetime:
    period_end = _timestamp(payload["applicationPeriod"]["endsAt"])
    feed_end_date = date.fromisoformat(payload["feed"]["validThrough"]) + timedelta(days=1)
    feed_end = datetime.combine(feed_end_date, datetime.min.time(), tzinfo=JST).astimezone(timezone.utc)
    return min(period_end, feed_end)


def retention_deadline(retired_at: datetime, effective_validity_end: datetime) -> datetime:
    """Return max(retirement + 7d, valid end + 48h), capped at 14d; reject unsafe cap."""
    retired = _as_of(retired_at)
    valid_end = _as_of(effective_validity_end)
    lower_bound = retired + MIN_RETENTION
    data_bound = valid_end + VALIDITY_GRACE
    upper_bound = retired + MAX_RETENTION
    required = max(lower_bound, data_bound)
    if required > upper_bound:
        raise AssemblyError("retention policy would remove still-required data beyond the 14-day cap")
    return required


def _read_payload_generation(root: Path, manifest: dict[str, Any], release_id: str,
                             station_records: dict[str, Any]) -> tuple[dict[str, bytes], dict[str, dict[str, Any]]]:
    files: dict[str, bytes] = {}
    payloads: dict[str, dict[str, Any]] = {}
    dates: list[str] | None = None
    common: dict[str, Any] | None = None
    for station_id, filename in STATION_FILES.items():
        relative = f"releases/{release_id}/{filename}"
        path = root / relative
        try:
            mode = path.lstat().st_mode
            if not stat.S_ISREG(mode):
                raise AssemblyError(f"generation file is not a regular file: {relative}")
            raw = path.read_bytes()
            envelope = verify_envelope_bytes(raw, expected_release_id=release_id,
                expected_station_id=station_id, expected_sha256=station_records[station_id]["sha256"],
                expected_bytes=station_records[station_id]["bytes"])
            payload = envelope["payload"]
            validate_public_payload(payload)
        except (OSError, ValueError) as error:
            raise AssemblyError(f"generation failed complete station verification: {relative}: {error}") from None
        station_dates = [day["serviceDate"] for day in payload["serviceDays"]]
        if not station_dates or any(value < manifest["serviceDateRange"]["from"]
                                    or value > manifest["serviceDateRange"]["through"] for value in station_dates):
            raise AssemblyError(f"station service dates do not match generation manifest: {station_id}")
        if min(station_dates) != manifest["serviceDateRange"]["from"] \
           or max(station_dates) != manifest["serviceDateRange"]["through"]:
            raise AssemblyError(f"station service date range differs from generation manifest: {station_id}")
        metadata = {key: payload[key] for key in ("generatedAt", "feed", "applicationPeriod", "timezone", "schemaVersion", "dataScope")}
        if dates is not None and station_dates != dates:
            raise AssemblyError("generation serviceDate lists differ across stations")
        if common is not None and metadata != common:
            raise AssemblyError("generation common metadata differs across stations")
        dates, common = station_dates, metadata
        files[relative] = raw
        payloads[station_id] = payload
    return files, payloads


def _verify_descriptor_payloads(descriptor: dict[str, Any], release_id: str,
                                payloads: dict[str, dict[str, Any]]) -> None:
    from release_contract import calculate_release_id
    try:
        if calculate_release_id(descriptor) != release_id:
            raise AssemblyError(f"release descriptor does not reproduce {release_id}")
        hashes = {item["stationId"]: item["payloadSha256"] for item in descriptor["stations"]}
    except (KeyError, TypeError, ValueError):
        raise AssemblyError(f"release descriptor is invalid for {release_id}") from None
    if set(hashes) != set(STATION_FILES):
        raise AssemblyError(f"release descriptor has incomplete stations: {release_id}")
    for station_id, payload in payloads.items():
        if sha256_hex(canonicalize_jcs(payload)) != hashes[station_id]:
            raise AssemblyError(f"release descriptor payload hash mismatch: {release_id}/{station_id}")


def _station_records(files: dict[str, bytes], release_id: str) -> dict[str, Any]:
    return {
        station_id: {
            "url": f"/releases/{release_id}/{filename}",
            "sha256": sha256_hex(files[f"releases/{release_id}/{filename}"]),
            "bytes": len(files[f"releases/{release_id}/{filename}"]),
        }
        for station_id, filename in STATION_FILES.items()
    }


def _retained_entry(manifest: dict[str, Any], files: dict[str, bytes], payloads: dict[str, dict[str, Any]],
                    *, published_at: str, retired_at: datetime) -> dict[str, Any]:
    descriptor = manifest.get("releaseDescriptor")
    if descriptor is None:
        raise AssemblyError(f"cannot retain {manifest['releaseId']} without its release descriptor")
    _verify_descriptor_payloads(descriptor, manifest["releaseId"], payloads)
    if _timestamp(published_at) > _as_of(retired_at):
        raise AssemblyError("release publish time cannot be after its retirement time")
    validity_end = _effective_validity_end(payloads[next(iter(STATION_FILES))])
    retain_until = retention_deadline(retired_at, validity_end)
    return {
        "releaseId": manifest["releaseId"],
        "releaseDescriptor": deepcopy(descriptor),
        "publishedAt": published_at,
        "retiredAt": _format_timestamp(retired_at),
        "retainUntil": _format_timestamp(retain_until),
        "serviceDateRange": deepcopy(manifest["serviceDateRange"]),
        "stations": _station_records(files, manifest["releaseId"]),
    }


def _record_is_retained(entry: dict[str, Any], now: datetime) -> bool:
    deadline = _timestamp(entry["retainUntil"])
    return now < deadline + DELETE_SAFETY_MARGIN


def _legacy_records(root: Path) -> tuple[dict[str, bytes], dict[str, Any]]:
    files: dict[str, bytes] = {}
    stations: dict[str, Any] = {}
    digest_input: dict[str, Any] = {}
    for station_id, filename in STATION_FILES.items():
        path = root / filename
        try:
            mode = path.lstat().st_mode
            if not stat.S_ISREG(mode):
                raise AssemblyError(f"legacy station is not a regular file: {filename}")
            raw = path.read_bytes()
            payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
            validate_public_payload(payload)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
            raise AssemblyError(f"legacy station failed validation: {filename}: {error}") from None
        if any(day["destinationStationId"] != station_id for day in payload["serviceDays"]):
            raise AssemblyError(f"legacy payload is for a different station: {station_id}")
        files[filename] = raw
        stations[station_id] = {"url": f"/{filename}", "sha256": sha256_hex(raw), "bytes": len(raw)}
        digest_input[station_id] = {"sha256": sha256_hex(raw), "bytes": len(raw)}
    return files, {"expiresAt": None, "sourceLegacyDigest": sha256_hex(canonicalize_jcs(digest_input)),
                   "stations": stations}


def _copy_bytes(target: Path, files: dict[str, bytes]) -> None:
    for relative, raw in files.items():
        path = target / relative
        if path.exists() or path.is_symlink():
            raise AssemblyError(f"artifact path collision: {relative}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)


def _measure(root: Path, *, max_files: int, max_total_bytes: int, max_asset_bytes: int) -> dict[str, int]:
    paths = sorted(path for path in root.rglob("*") if path.is_file())
    if len(paths) > max_files:
        raise AssemblyError(f"artifact file count {len(paths)} exceeds limit {max_files}")
    sizes = [path.stat().st_size for path in paths]
    largest = max(sizes, default=0)
    total = sum(sizes)
    if largest > max_asset_bytes:
        raise AssemblyError(f"single artifact file size {largest} exceeds limit {max_asset_bytes}")
    if total > max_total_bytes:
        raise AssemblyError(f"artifact total bytes {total} exceeds limit {max_total_bytes}")
    return {"files": len(paths), "total_bytes": total, "largest_file_bytes": largest}


def _copy_validated_release(root: Path, manifest: dict[str, Any], release_id: str) -> dict[str, bytes]:
    records = manifest["stations"] if release_id == manifest["releaseId"] else next(
        item["stations"] for item in manifest["retainedReleases"] if item["releaseId"] == release_id)
    files, payloads = _read_payload_generation(root, manifest if release_id == manifest["releaseId"] else {
        **manifest, "serviceDateRange": next(item["serviceDateRange"] for item in manifest["retainedReleases"]
                                               if item["releaseId"] == release_id)}, release_id, records)
    descriptor = manifest.get("releaseDescriptor") if release_id == manifest["releaseId"] else next(
        item.get("releaseDescriptor") for item in manifest["retainedReleases"] if item["releaseId"] == release_id)
    if descriptor is None:
        raise AssemblyError(f"retained release has no descriptor: {release_id}")
    _verify_descriptor_payloads(descriptor, release_id, payloads)
    retained_entry = next((item for item in manifest["retainedReleases"] if item["releaseId"] == release_id), None)
    if retained_entry is not None:
        if _timestamp(retained_entry["publishedAt"]) > _timestamp(retained_entry["retiredAt"]):
            raise AssemblyError(f"retained release timestamps are reversed: {release_id}")
        expected_deadline = retention_deadline(_timestamp(retained_entry["retiredAt"]),
            _effective_validity_end(payloads[next(iter(STATION_FILES))]))
        if _timestamp(retained_entry["retainUntil"]) != expected_deadline:
            raise AssemblyError(f"retained release deadline does not match policy: {release_id}")
    return files


def assemble_public_artifact(*, previous: Path, new_release: Path, output: Path,
                             evaluated_at: str | datetime,
                             max_files: int = MAX_FILES_DEFAULT,
                             max_total_bytes: int = MAX_TOTAL_BYTES_DEFAULT,
                             max_asset_bytes: int = MAX_ASSET_BYTES_DEFAULT) -> dict[str, Any]:
    """Create an atomic full artifact from a previous production tree and new release."""
    now = _as_of(evaluated_at)
    previous = previous.expanduser().absolute()
    new_release = new_release.expanduser().absolute()
    output = output.expanduser().absolute()
    if max_files < 1 or max_total_bytes < 1 or max_asset_bytes < 1:
        raise AssemblyError("artifact limits must be positive integers")
    if os.path.lexists(output):
        raise AssemblyError("output must not already exist")
    if not output.parent.is_dir() or output.parent.is_symlink():
        raise AssemblyError("output parent must be an existing regular directory without symlinks")
    if any(part.is_symlink() for part in (output.parent, *output.parent.parents)):
        raise AssemblyError("output path contains a symlink")

    try:
        validate_release_managed_artifact(new_release)
        new_manifest = _read_manifest(new_release)
    except (ArtifactValidationError, OSError, AssemblyError) as error:
        raise AssemblyError(f"new release artifact failed validation: {error}") from None
    if new_manifest["retainedReleases"] or new_manifest["legacyCompatibilityV1"] is not None:
        raise AssemblyError("new release input must be a clean generation-only artifact")

    previous_manifest: dict[str, Any] | None = None
    legacy_files: dict[str, bytes] = {}
    legacy_info: dict[str, Any] | None = None
    manifest_path = previous / "manifest.json"
    try:
        mode = manifest_path.lstat().st_mode
        has_manifest = stat.S_ISREG(mode)
    except FileNotFoundError:
        has_manifest = False
    if has_manifest:
        try:
            validate_release_managed_artifact(previous)
            previous_manifest = _read_manifest(previous)
        except (ArtifactValidationError, OSError, AssemblyError) as error:
            raise AssemblyError(f"previous release artifact failed validation: {error}") from None
    else:
        try:
            validate_artifact(previous)
            legacy_files, legacy_info = _legacy_records(previous)
        except (ArtifactValidationError, OSError, AssemblyError) as error:
            raise AssemblyError(f"previous legacy artifact failed validation: {error}") from None

    new_id = new_manifest["releaseId"]
    as_of_text = _format_timestamp(now)
    new_generation = _copy_validated_release(new_release, new_manifest, new_id)
    retained_files: dict[str, bytes] = {}
    retained_entries: list[dict[str, Any]] = []
    prior_published_at: str | None = None

    if previous_manifest is not None:
        old_ids = {item["releaseId"] for item in previous_manifest["retainedReleases"]}
        if new_id == previous_manifest["releaseId"]:
            if new_manifest["releaseDescriptor"] != previous_manifest["releaseDescriptor"]:
                raise AssemblyError("same releaseId has a different descriptor in old and new artifact")
            existing_files = _copy_validated_release(previous, previous_manifest, new_id)
            if existing_files != new_generation:
                raise AssemblyError("same releaseId resolves to different envelope bytes")
            prior_published_at = previous_manifest["publishedAt"] or as_of_text
        else:
            rollback_entry = next((item for item in previous_manifest["retainedReleases"]
                                   if item["releaseId"] == new_id), None)
            prior_published_at = (rollback_entry["publishedAt"] if rollback_entry else None)
            old_files = _copy_validated_release(previous, previous_manifest, previous_manifest["releaseId"])
            old_entry = _retained_entry(previous_manifest, old_files,
                _read_payload_generation(previous, previous_manifest, previous_manifest["releaseId"],
                                         previous_manifest["stations"])[1],
                published_at=previous_manifest["publishedAt"] or as_of_text, retired_at=now)
            if _record_is_retained(old_entry, now):
                retained_entries.append(old_entry)
                retained_files.update(old_files)

        for old in previous_manifest["retainedReleases"]:
            if old["releaseId"] == new_id:
                continue
            if old.get("releaseDescriptor") is None:
                raise AssemblyError(f"previous retained release lacks descriptor: {old['releaseId']}")
            if not _record_is_retained(old, now):
                continue
            if old["releaseId"] in old_ids and any(item["releaseId"] == old["releaseId"] for item in retained_entries):
                raise AssemblyError(f"duplicate retained generation: {old['releaseId']}")
            files = _copy_validated_release(previous, previous_manifest, old["releaseId"])
            retained_files.update(files)
            retained_entries.append(deepcopy(old))

        if prior_published_at and new_id in old_ids:
            rollback_entry = next(item for item in previous_manifest["retainedReleases"] if item["releaseId"] == new_id)
            if rollback_entry["releaseDescriptor"] != new_manifest["releaseDescriptor"]:
                raise AssemblyError("rollback release descriptor differs from selected current release")
            rollback_files = _copy_validated_release(previous, previous_manifest, new_id)
            if rollback_files != new_generation:
                raise AssemblyError("rollback release resolves to different envelope bytes")

        if previous_manifest["legacyCompatibilityV1"] is not None:
            old_legacy = previous_manifest["legacyCompatibilityV1"]
            if now < _timestamp(old_legacy["expiresAt"]) + DELETE_SAFETY_MARGIN:
                legacy_info = deepcopy(old_legacy)
                for station_id, filename in STATION_FILES.items():
                    raw = (previous / filename).read_bytes()
                    record = old_legacy["stations"][station_id]
                    if len(raw) != record["bytes"] or sha256_hex(raw) != record["sha256"]:
                        raise AssemblyError(f"legacy alias changed after validation: {filename}")
                    legacy_files[filename] = raw
            else:
                legacy_info = None

    if prior_published_at is None:
        prior_published_at = as_of_text
    if previous_manifest is None:
        assert legacy_info is not None
        legacy_info["expiresAt"] = _format_timestamp(now + LEGACY_RETENTION)

    # Ensure current wins over all histories and retention ordering is stable.
    unique_entries: dict[str, dict[str, Any]] = {}
    for item in retained_entries:
        if item["releaseId"] == new_id:
            continue
        if item["releaseId"] in unique_entries:
            if unique_entries[item["releaseId"]] != item:
                raise AssemblyError(f"conflicting duplicate retained release: {item['releaseId']}")
            continue
        unique_entries[item["releaseId"]] = item
    retained_entries = sorted(unique_entries.values(), key=lambda item: (item["retiredAt"], item["releaseId"]))

    manifest = create_manifest(
        release_id=new_id,
        release_descriptor=new_manifest["releaseDescriptor"],
        published_at=prior_published_at,
        generated_at=new_manifest["generatedAt"],
        service_date_range=new_manifest["serviceDateRange"],
        feed=new_manifest["feed"],
        application_period=new_manifest["applicationPeriod"],
        station_json_bytes={station_id: new_generation[f"releases/{new_id}/{filename}"]
                            for station_id, filename in STATION_FILES.items()},
        retained_releases=retained_entries,
        legacy_compatibility_v1=legacy_info,
    )

    temp_parent = Path(tempfile.mkdtemp(prefix="dotchi-release-assembly-", dir=output.parent))
    stage = temp_parent / "artifact"
    try:
        stage.mkdir()
        for path in sorted(new_release.iterdir(), key=lambda item: item.name):
            if path.name in {"manifest.json", "releases"}:
                continue
            if path.is_symlink() or not path.is_file():
                raise AssemblyError(f"new artifact contains an unexpected path: {path.name}")
            (stage / path.name).write_bytes(path.read_bytes())
        _copy_bytes(stage, new_generation)
        _copy_bytes(stage, retained_files)
        _copy_bytes(stage, legacy_files)
        manifest_path = stage / "manifest.json"
        if manifest_path.exists():
            raise AssemblyError("manifest path collision")
        manifest_path.write_bytes(encode_manifest(manifest))
        validation = validate_release_managed_artifact(stage)
        stats = _measure(stage, max_files=max_files, max_total_bytes=max_total_bytes,
                         max_asset_bytes=max_asset_bytes)
        if stats["files"] != 18 + 8 * len(retained_entries) + (8 if legacy_info is not None else 0):
            raise AssemblyError("assembled file count differs from manifest generation set")
        if validation["release_id"] != new_id:
            raise AssemblyError("final validator returned a different current releaseId")
        if os.path.lexists(output):
            raise AssemblyError("output appeared during assembly; refusing to replace it")
        os.replace(stage, output)
        return {**stats, "release_id": new_id,
                "retained_release_ids": [item["releaseId"] for item in retained_entries],
                "legacy_compatibility": legacy_info is not None,
                "legacy_expires_at": legacy_info["expiresAt"] if legacy_info else None}
    except (OSError, ArtifactValidationError, ValueError) as error:
        raise AssemblyError(f"final artifact assembly failed: {error}") from None
    finally:
        shutil.rmtree(temp_parent, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous", type=Path, required=True,
                        help="validated previous release-managed or exact 17-file legacy artifact")
    parser.add_argument("--new-release", type=Path, required=True,
                        help="validated clean release-managed generation artifact")
    parser.add_argument("--as-of", required=True, help="evaluation instant with explicit timezone, e.g. 2026-10-28T10:00:00+09:00")
    parser.add_argument("--output", type=Path, required=True, help="new output directory; existing paths are refused")
    parser.add_argument("--max-files", type=int, default=MAX_FILES_DEFAULT)
    parser.add_argument("--max-total-bytes", type=int, default=MAX_TOTAL_BYTES_DEFAULT)
    parser.add_argument("--max-asset-bytes", type=int, default=MAX_ASSET_BYTES_DEFAULT)
    args = parser.parse_args()
    try:
        result = assemble_public_artifact(previous=args.previous, new_release=args.new_release,
            output=args.output, evaluated_at=args.as_of, max_files=args.max_files,
            max_total_bytes=args.max_total_bytes, max_asset_bytes=args.max_asset_bytes)
    except (AssemblyError, OSError, ValueError) as error:
        print(f"release assembly failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
