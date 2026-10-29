#!/usr/bin/env python3
"""Render a metadata-only Actions summary from a fetched release snapshot."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any

from release_contract import HASH_RE, RELEASE_ID_RE, STATION_FILES
from validate_public_artifact import ArtifactValidationError, validate_release_managed_artifact


TIMESTAMP_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)


class SnapshotSummaryError(ValueError):
    """Safe failure for an untrusted or inconsistent diagnostic snapshot."""


def _timestamp(value: Any) -> str:
    if not isinstance(value, str) or not TIMESTAMP_RE.fullmatch(value):
        raise SnapshotSummaryError("snapshot timestamp is invalid")
    return value


def _validate_fetch_result(result: Any, snapshot: Path, validation: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(result, dict):
        raise SnapshotSummaryError("fetch result is invalid")
    if (result.get("mode") != "release-managed"
            or result.get("manifest_classification") != "release-managed"
            or result.get("fingerprint_verified") is not True):
        raise SnapshotSummaryError("release-managed fetch and fingerprint verification are required")
    release_id = result.get("release_id")
    if not isinstance(release_id, str) or not RELEASE_ID_RE.fullmatch(release_id):
        raise SnapshotSummaryError("fetch result releaseId is invalid")
    fingerprint = result.get("fingerprint")
    if not isinstance(fingerprint, str) or not HASH_RE.fullmatch(fingerprint):
        raise SnapshotSummaryError("fetch result fingerprint is invalid")
    for key in ("files", "files_validated", "retained_releases", "total_bytes", "largest_file_bytes"):
        if type(result.get(key)) is not int or result[key] < 0:
            raise SnapshotSummaryError("fetch result counts are invalid")
    if type(result.get("legacy_compatibility")) is not bool:
        raise SnapshotSummaryError("fetch result compatibility state is invalid")
    if (validation.get("release_id") != release_id
            or validation.get("files") != result["files"]
            or validation.get("files") != result["files_validated"]):
        raise SnapshotSummaryError("fetch result differs from the independently validated snapshot")

    manifest_path = snapshot / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise SnapshotSummaryError("snapshot manifest cannot be read") from None
    if (not isinstance(manifest, dict) or manifest.get("releaseId") != release_id
            or manifest.get("schemaVersion") != 1):
        raise SnapshotSummaryError("snapshot manifest does not match the fetched release")
    retained = manifest.get("retainedReleases")
    legacy = manifest.get("legacyCompatibilityV1")
    if (not isinstance(retained, list) or len(retained) != result["retained_releases"]
            or (legacy is not None) != result["legacy_compatibility"]):
        raise SnapshotSummaryError("snapshot retention metadata differs from fetch result")
    return {"result": result, "manifest": manifest, "retained": retained, "legacy": legacy}


def render_summary(snapshot_dir: Path, fetch_result: Any) -> str:
    """Independently validate the snapshot, then render allowlisted metadata only."""
    try:
        validation = validate_release_managed_artifact(snapshot_dir)
    except (ArtifactValidationError, OSError, ValueError):
        raise SnapshotSummaryError("independent release-managed validation failed") from None

    checked = _validate_fetch_result(fetch_result, snapshot_dir, validation)
    result = checked["result"]
    manifest = checked["manifest"]
    retained = checked["retained"]
    legacy = checked["legacy"]
    release_id = manifest["releaseId"]

    station_rows: list[tuple[str, str, int, str]] = []
    stations = manifest.get("stations")
    if not isinstance(stations, dict) or set(stations) != set(STATION_FILES):
        raise SnapshotSummaryError("snapshot station set is invalid")
    for station_id, filename in STATION_FILES.items():
        record = stations.get(station_id)
        expected_url = f"/releases/{release_id}/{filename}"
        if not isinstance(record, dict) or record.get("url") != expected_url:
            raise SnapshotSummaryError("snapshot station path is invalid")
        size = record.get("bytes")
        digest = record.get("sha256")
        if type(size) is not int or size < 1 or not isinstance(digest, str) or not HASH_RE.fullmatch(digest):
            raise SnapshotSummaryError("snapshot station byte metadata is invalid")
        try:
            raw = (snapshot_dir / "releases" / release_id / filename).read_bytes()
        except OSError:
            raise SnapshotSummaryError("current station file is missing") from None
        if len(raw) != size or hashlib.sha256(raw).hexdigest() != digest:
            raise SnapshotSummaryError("current station file integrity check failed")
        station_rows.append((station_id, filename, size, digest))

    retained_rows: list[tuple[str, str, str]] = []
    for entry in retained:
        if not isinstance(entry, dict):
            raise SnapshotSummaryError("retained release metadata is invalid")
        retained_id = entry.get("releaseId")
        if not isinstance(retained_id, str) or not RELEASE_ID_RE.fullmatch(retained_id):
            raise SnapshotSummaryError("retained release ID is invalid")
        retained_rows.append((retained_id, _timestamp(entry.get("retiredAt")),
                              _timestamp(entry.get("retainUntil"))))

    lines = [
        "## Cloudflare Production artifact fetch diagnostic",
        "",
        "- diagnostic_result: **PASS**",
        "- manifest_classification: `release-managed`",
        f"- current releaseId: `{release_id}`",
        f"- files_fetched: `{result['files']}`",
        "- fingerprint_match: **confirmed**",
        f"- independent_validator: **PASS** (`{validation['files']}` files, `{validation['stations']}` stations)",
        "",
        "### Retained releases",
        "",
        "| releaseId | retiredAt | retainUntil |",
        "|---|---|---|",
    ]
    if retained_rows:
        lines.extend(f"| `{rid}` | `{retired}` | `{until}` |" for rid, retired, until in retained_rows)
    else:
        lines.append("| none | — | — |")

    lines.extend(["", "### Legacy compatibility", ""])
    if legacy is None:
        lines.append("- legacyCompatibilityV1: **absent**")
    else:
        lines.append(f"- legacyCompatibilityV1: **present**; expiresAt `{_timestamp(legacy.get('expiresAt'))}`")

    lines.extend([
        "",
        "### Current release station files",
        "",
        "| stationId | file | bytes | SHA-256 |",
        "|---|---|---:|---|",
    ])
    lines.extend(f"| `{station}` | `{filename}` | `{size}` | `{digest}` |"
                 for station, filename, size, digest in station_rows)
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True, type=Path)
    args = parser.parse_args()
    try:
        fetch_result = json.load(sys.stdin)
        summary = render_summary(args.snapshot, fetch_result)
    except (json.JSONDecodeError, OSError, SnapshotSummaryError):
        print("snapshot_summary_failed=invalid_release_managed_snapshot", file=sys.stderr)
        return 1
    sys.stdout.write(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
