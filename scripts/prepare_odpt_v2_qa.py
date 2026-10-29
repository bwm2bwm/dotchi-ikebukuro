#!/usr/bin/env python3
"""Stage an existing private public-display-v2 bundle for loopback-only UI QA."""
from __future__ import annotations

import argparse
from datetime import date, timedelta
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import odpt_public_v2 as v2  # noqa: E402

QA_ROOT = (Path.home() / "Library" / "Application Support" /
           "dotchi-ikebukuro-preview" / "odpt-v2-qa")
STATIC_FILES = {
    "odpt_v2_qa.html": ROOT / "_local_preview" / "odpt_v2_qa.html",
    "styles.css": ROOT / "styles.css",
    "preview.css": ROOT / "_local_preview" / "preview.css",
    "odpt_v2_qa.css": ROOT / "_local_preview" / "odpt_v2_qa.css",
    "preview_odpt_v2_qa.mjs": ROOT / "_local_preview" / "preview_odpt_v2_qa.mjs",
    "odpt_v2_qa_adapter.mjs": ROOT / "_local_preview" / "odpt_v2_qa_adapter.mjs",
    "selection.mjs": ROOT / "_local_preview" / "selection.mjs",
}
STATE_FILENAME = "_odpt_v2_qa_state.json"


class PrepareError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _strict_date(value: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError):
        raise PrepareError("service_date_invalid") from None
    if parsed.isoformat() != value:
        raise PrepareError("service_date_invalid")
    return parsed


def _reject_symlink_components(path: Path) -> Path:
    absolute = path.expanduser().absolute()
    for component in (absolute, *absolute.parents):
        if os.path.lexists(component) and component.is_symlink():
            raise PrepareError("symlink_path_rejected")
    return absolute


def _outside_repository(path: Path) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError:
        return resolved
    raise PrepareError("repository_path_rejected")


def _write_private(path: Path, content: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(content)
    path.chmod(0o600)


def _date_range(target_text: str) -> list[str]:
    target = _strict_date(target_text)
    return [(target + timedelta(days=offset)).isoformat() for offset in (-1, 0, 1)]


def _qa_state(manifest: dict, station_ids: list[str], service_dates: list[str]) -> dict:
    audit = manifest.get("quality", {}).get("exclusionAudit")
    if not isinstance(audit, dict) or not isinstance(audit.get("byStationDate"), list):
        raise PrepareError("exclusion_audit_missing")
    rows = {(row.get("stationId"), row.get("serviceDate")): row
            for row in audit["byStationDate"] if isinstance(row, dict)}
    expected_pairs = {(station, day) for station in station_ids for day in service_dates}
    if set(rows) != expected_pairs:
        raise PrepareError("exclusion_audit_station_date_mismatch")
    stations = {}
    for station_id in station_ids:
        stations[station_id] = {}
        for service_date in service_dates:
            row = rows[(station_id, service_date)]
            reasons = row.get("reasonCounts")
            if not isinstance(reasons, dict):
                raise PrepareError("exclusion_audit_invalid")
            no_valid_arrival_count = reasons.get("no_valid_arrival", 0)
            other_unknown_count = sum(reasons.get(key, 0) for key in (
                "primary_arrival_missing", "unknown"))
            info_count = reasons.get("explicit_pass_info", 0)
            if any(type(value) is not int or value < 0 for value in
                   (no_valid_arrival_count, other_unknown_count, info_count)):
                raise PrepareError("exclusion_audit_invalid")
            stations[station_id][service_date] = {
                "infoCount": info_count, "noValidArrivalCount": no_valid_arrival_count,
                "otherUnknownCount": other_unknown_count,
            }
    candidate_files = manifest.get("candidateFiles")
    if not isinstance(candidate_files, dict) or set(candidate_files) != set(station_ids):
        raise PrepareError("candidate_manifest_entries_invalid")
    integrity = {}
    for station_id in station_ids:
        entry = candidate_files[station_id]
        if (not isinstance(entry, dict) or entry.get("path") != v2.ROUTE_FILENAMES[station_id]
                or type(entry.get("bytes")) is not int or entry["bytes"] < 1
                or not isinstance(entry.get("sha256"), str) or len(entry["sha256"]) != 64):
            raise PrepareError("candidate_manifest_entries_invalid")
        integrity[station_id] = {"sha256": entry["sha256"], "bytes": entry["bytes"]}
    return {"schemaVersion": 1, "dataScope": "private-local-odpt-v2-qa-state",
            "serviceDates": service_dates, "stations": stations, "candidateFiles": integrity}


def prepare(bundle_dir: Path, service_date: str, output_dir: Path | None = None) -> dict:
    service_dates = _date_range(service_date)
    bundle = _outside_repository(_reject_symlink_components(bundle_dir))
    if bundle.is_symlink() or not bundle.is_dir():
        raise PrepareError("bundle_missing_or_unsafe")
    output = output_dir or (QA_ROOT / service_date / "site")
    output = _outside_repository(_reject_symlink_components(output))
    try:
        output.relative_to(bundle)
    except ValueError:
        pass
    else:
        raise PrepareError("output_inside_bundle")
    if os.path.lexists(output):
        raise PrepareError("output_already_exists")
    if output == bundle or bundle in output.parents:
        raise PrepareError("output_inside_bundle")

    try:
        manifest_path = bundle / "private-generator-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        entries = manifest.get("candidateFiles", {})
        v2.validate_bundle(bundle, manifest, list(v2.DESTINATIONS), service_dates,
                           manifest.get("sourceFingerprint"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, v2.V2Error) as exc:
        code = exc.code if isinstance(exc, v2.V2Error) else "bundle_validation_failed"
        raise PrepareError(code) from None

    for name, source in STATIC_FILES.items():
        if source.is_symlink() or not source.is_file():
            raise PrepareError("qa_static_asset_missing_or_unsafe")
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if output.parent.is_symlink():
        raise PrepareError("output_parent_symlink")
    if output == (QA_ROOT / service_date / "site").absolute().resolve():
        QA_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
        QA_ROOT.chmod(0o700)
        output.parent.chmod(0o700)
    elif stat.S_IMODE(output.parent.stat().st_mode) & 0o077:
        raise PrepareError("output_parent_not_private")
    if os.path.lexists(output):
        raise PrepareError("output_already_exists")
    stage = Path(tempfile.mkdtemp(prefix=f".{output.name}.stage-", dir=output.parent))
    stage.chmod(0o700)
    try:
        copied = 0
        for name, source in STATIC_FILES.items():
            _write_private(stage / name, source.read_bytes())
            copied += 1
        qa_state = _qa_state(manifest, list(v2.DESTINATIONS), service_dates)
        _write_private(stage / STATE_FILENAME,
                       json.dumps(qa_state, ensure_ascii=False, sort_keys=True,
                                  separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n")
        copied += 1
        candidate_dir = bundle / "public-candidates"
        for station_id in v2.DESTINATIONS:
            filename = v2.ROUTE_FILENAMES[station_id]
            source = candidate_dir / filename
            if source.is_symlink() or not source.is_file():
                raise PrepareError("candidate_missing_or_unsafe")
            content = source.read_bytes()
            entry = entries.get(station_id)
            if (not isinstance(entry, dict) or entry.get("path") != filename
                    or entry.get("bytes") != len(content) or entry.get("sha256") != _sha256(content)):
                raise PrepareError("candidate_hash_or_bytes_mismatch")
            try:
                payload = json.loads(content)
                v2.validate_v2_payload(payload)
            except (UnicodeDecodeError, json.JSONDecodeError, v2.V2Error):
                raise PrepareError("candidate_validation_failed") from None
            _write_private(stage / filename, content)
            staged = (stage / filename).read_bytes()
            if len(staged) != len(content) or _sha256(staged) != _sha256(content):
                raise PrepareError("staged_candidate_mismatch")
            copied += 1
        if copied != len(STATIC_FILES) + len(v2.DESTINATIONS) + 1:
            raise PrepareError("staged_file_count_mismatch")
        expected_names = set(STATIC_FILES) | set(v2.ROUTE_FILENAMES.values()) | {STATE_FILENAME}
        if {path.name for path in stage.iterdir()} != expected_names:
            raise PrepareError("staged_file_set_mismatch")
        if os.path.lexists(output):
            raise PrepareError("output_appeared_during_prepare")
        os.replace(stage, output)
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return {"status": "PASS", "output": str(output), "stationCount": len(v2.DESTINATIONS),
            "serviceDates": service_dates, "candidateCount": manifest["quality"]["candidateDepartureCount"],
            "excludedCount": manifest["quality"]["exclusionAudit"]["excludedCount"],
            "fileCount": len(STATIC_FILES) + len(v2.DESTINATIONS) + 1,
            "manifestCopied": False, "permissions": "directories 0700; files 0600"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True,
                        help="ODPT-1B private completed bundle directory")
    parser.add_argument("--service-date", required=True, help="QA target date YYYY-MM-DD")
    parser.add_argument("--output", type=Path, help="new output directory outside repository and bundle")
    args = parser.parse_args(argv)
    try:
        result = prepare(args.bundle, args.service_date, args.output)
    except (PrepareError, OSError, ValueError) as exc:
        code = exc.code if isinstance(exc, PrepareError) else "prepare_failed"
        print(f"FAIL: {code}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    print(f"起動: python3 scripts/serve_odpt_v2_qa.py --directory {result['output']} --port 8765")
    print("画面: http://127.0.0.1:8765/odpt_v2_qa.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
