#!/usr/bin/env python3
"""Build an allowlisted static public site from explicit synthetic payloads only."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from typing import Any

from public_payload_profile import PUBLIC_DATA_SCOPE, validate_public_payload
from release_contract import (
    RUNTIME_CONTRACT,
    build_release_descriptor,
    calculate_release_id,
    create_manifest,
    encode_envelope,
    encode_manifest,
)

ROOT = Path(__file__).resolve().parents[1]
SYNTHETIC_MARKER = ".synthetic-public-display-v1"
SYNTHETIC_MARKER_CONTENT = "dotchi-ikebukuro synthetic public payload fixtures v1\n"
PAYLOAD_FILENAMES = {
    "Kanamecho": "timetable-Kanamecho.json",
    "Senkawa": "timetable-Senkawa.json",
    "KotakeMukaihara": "timetable-KotakeMukaihara.json",
    "Hikawadai": "timetable.json",
    "Heiwadai": "timetable-Heiwadai.json",
    "ChikatetsuAkatsuka": "timetable-ChikatetsuAkatsuka.json",
    "ChikatetsuNarimasu": "timetable-ChikatetsuNarimasu.json",
    "Wakoshi": "timetable-Wakoshi.json",
}
SOURCE_FILES = {
    "index.html": ROOT / "_local_preview" / "public_index.html",
    "styles.css": ROOT / "styles.css",
    "preview.css": ROOT / "_local_preview" / "preview.css",
    "preview_public.js": ROOT / "_local_preview" / "preview_public.js",
    "preview_core.mjs": ROOT / "_local_preview" / "preview_core.mjs",
    "timetable_adapter.mjs": ROOT / "scripts" / "timetable_adapter.mjs",
    "local_preview_payload_loader.mjs": ROOT / "scripts" / "local_preview_payload_loader.mjs",
    "selection.mjs": ROOT / "_local_preview" / "selection.mjs",
    "terminal_ui.mjs": ROOT / "_local_preview" / "terminal_ui.mjs",
}
JS_ARTIFACTS = frozenset({
    "preview_public.js", "preview_core.mjs", "timetable_adapter.mjs",
    "local_preview_payload_loader.mjs", "selection.mjs", "terminal_ui.mjs",
})
ARTIFACT_FILENAMES = frozenset((*SOURCE_FILES, *PAYLOAD_FILENAMES.values()))
BUILDER_CONTRACT_VERSION = "dotchi-public-builder-v1"
FORBIDDEN_ARTIFACT_MARKERS = (
    "preview.js", "virtual_now.mjs", "performance_metrics.mjs", "preview_diagnostics.css",
    "debugnow", "perf=1", ".env", "apikey", "api_key", "synthetic-secret",
)
ABSOLUTE_PATH = re.compile(r"(?:/Users/[^/\s]+|/private/(?:tmp|var)/[^\s\"']+|[A-Za-z]:\\Users\\[^\s\"']+)")
IMPORT_RE = re.compile(
    r"^\s*import\s+(?:[^'\"]*?\s+from\s+)?['\"]([^'\"]+)['\"]\s*;?"
    r"|^\s*export\s+[^'\"]*?\s+from\s+['\"]([^'\"]+)['\"]\s*;?",
    re.MULTILINE,
)


class PublicSiteBuildError(ValueError):
    """Raised when the synthetic input or staged public artifact is unsafe."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PublicSiteBuildError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _read_payload(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_keys)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise PublicSiteBuildError(f"invalid JSON fixture {path.name}: {error}") from error
    if not isinstance(value, dict):
        raise PublicSiteBuildError(f"{path.name}: JSON object required")
    try:
        validate_public_payload(value)
    except ValueError as error:
        raise PublicSiteBuildError(f"{path.name}: {error}") from error
    return value


def _validate_fixture_directory(fixture_dir: Path) -> tuple[dict[str, dict[str, Any]], list[str]]:
    if not fixture_dir.is_dir() or fixture_dir.is_symlink():
        raise PublicSiteBuildError("fixture directory must be an explicit, regular directory")
    expected_names = {*PAYLOAD_FILENAMES.values(), SYNTHETIC_MARKER}
    entries = list(fixture_dir.iterdir())
    invalid = [entry.name for entry in entries if entry.is_symlink() or not entry.is_file()]
    if invalid:
        raise PublicSiteBuildError("fixture directory contains non-regular entries: " + ", ".join(sorted(invalid)))
    actual_names = {entry.name for entry in entries}
    missing = expected_names - actual_names
    extra = actual_names - expected_names
    if missing or extra:
        detail = []
        if missing:
            detail.append("missing: " + ", ".join(sorted(missing)))
        if extra:
            detail.append("unexpected: " + ", ".join(sorted(extra)))
        raise PublicSiteBuildError("fixture set must contain the synthetic marker and exactly eight named station payloads ("
                                   + "; ".join(detail) + ")")
    try:
        marker_content = (fixture_dir / SYNTHETIC_MARKER).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise PublicSiteBuildError(f"synthetic fixture marker cannot be read: {error}") from error
    if marker_content != SYNTHETIC_MARKER_CONTENT:
        raise PublicSiteBuildError("synthetic fixture marker is missing or invalid")

    payloads: dict[str, dict[str, Any]] = {}
    expected_dates: list[str] | None = None
    for destination_id, filename in PAYLOAD_FILENAMES.items():
        payload = _read_payload(fixture_dir / filename)
        if payload.get("schemaVersion") != 1 or payload.get("dataScope") != PUBLIC_DATA_SCOPE:
            raise PublicSiteBuildError(f"{filename}: schema v1 public-display-v1 required")
        dates = [day["serviceDate"] for day in payload["serviceDays"]]
        if expected_dates is None:
            expected_dates = dates
        elif dates != expected_dates:
            raise PublicSiteBuildError(f"{filename}: serviceDate list differs from other station payloads")
        for day in payload["serviceDays"]:
            if day["originStationId"] != "Ikebukuro":
                raise PublicSiteBuildError(f"{filename}: originStationId must be Ikebukuro")
            if day["destinationStationId"] != destination_id:
                raise PublicSiteBuildError(f"{filename}: destinationStationId must match {destination_id}")
        payloads[destination_id] = payload
    if not expected_dates:
        raise PublicSiteBuildError("serviceDate list must not be empty")
    return payloads, expected_dates


def _ensure_safe_paths(fixture_dir: Path, output_dir: Path) -> tuple[Path, Path]:
    raw_fixture = fixture_dir.expanduser()
    if raw_fixture.is_symlink():
        raise PublicSiteBuildError("fixture directory must not be a symlink")
    fixture_dir = raw_fixture.resolve()
    raw_output = output_dir.expanduser()
    if raw_output.is_symlink():
        raise PublicSiteBuildError("output path must not be a symlink")
    output_dir = raw_output.resolve()
    if output_dir == ROOT or ROOT in output_dir.parents:
        raise PublicSiteBuildError("output must be outside the repository; root mock and tracked files are protected")
    if output_dir == fixture_dir or fixture_dir in output_dir.parents or output_dir in fixture_dir.parents:
        raise PublicSiteBuildError("output and fixture paths must not overlap")
    if output_dir == Path(output_dir.anchor):
        raise PublicSiteBuildError("filesystem root cannot be an output directory")
    if output_dir.exists() and (not output_dir.is_dir() or output_dir.is_symlink()):
        raise PublicSiteBuildError("existing output must be a regular directory")
    return fixture_dir, output_dir


def _copy_allowlisted_assets(stage: Path) -> None:
    for output_name, source in SOURCE_FILES.items():
        if source.is_symlink() or not source.is_file():
            raise PublicSiteBuildError(f"allowlisted source is missing or not a regular file: {source.name}")
        shutil.copyfile(source, stage / output_name)


def _validate_import_graph(stage: Path) -> None:
    reached: set[str] = set()
    pending = ["preview_public.js"]
    while pending:
        current = pending.pop()
        if current in reached:
            continue
        if current not in JS_ARTIFACTS or not (stage / current).is_file():
            raise PublicSiteBuildError(f"import dependency is outside the public JavaScript allowlist: {current}")
        reached.add(current)
        source = (stage / current).read_text(encoding="utf-8")
        if re.search(r"\bimport\s*\(", source):
            raise PublicSiteBuildError(f"dynamic import is not permitted in public artifact: {current}")
        for match in IMPORT_RE.finditer(source):
            specifier = match.group(1) or match.group(2)
            if not specifier.startswith("./"):
                raise PublicSiteBuildError(f"non-relative import is not permitted: {current} -> {specifier}")
            resolved = PurePosixPath(current).parent.joinpath(specifier)
            normalized = str(resolved)
            if normalized.startswith("../") or normalized not in JS_ARTIFACTS:
                raise PublicSiteBuildError(f"import escapes public allowlist: {current} -> {specifier}")
            if not (stage / normalized).is_file():
                raise PublicSiteBuildError(f"unresolved public import: {current} -> {specifier}")
            pending.append(normalized)
    if reached != JS_ARTIFACTS:
        raise PublicSiteBuildError("public JavaScript dependency graph differs from expected allowlist: "
                                   + ", ".join(sorted(JS_ARTIFACTS - reached)))


def _validate_artifacts(stage: Path) -> None:
    names = {path.name for path in stage.iterdir()}
    if names != ARTIFACT_FILENAMES:
        raise PublicSiteBuildError("artifact file set differs from allowlist: "
                                   + ", ".join(sorted(names ^ ARTIFACT_FILENAMES)))
    _validate_import_graph(stage)
    node = shutil.which("node")
    if not node:
        raise PublicSiteBuildError("Node.js is required for public adapter and syntax validation")
    for name in sorted(JS_ARTIFACTS):
        result = subprocess.run([node, "--check", str(stage / name)], capture_output=True, text=True)
        if result.returncode:
            raise PublicSiteBuildError(f"JavaScript syntax validation failed for {name}: {result.stderr.strip()}")

    for path in stage.iterdir():
        if path.suffix.lower() not in {".html", ".css", ".js", ".mjs", ".json"}:
            raise PublicSiteBuildError(f"unexpected artifact extension: {path.name}")
        content = path.read_text(encoding="utf-8")
        lowered = content.lower()
        marker = next((item for item in FORBIDDEN_ARTIFACT_MARKERS if item in lowered), None)
        if marker:
            raise PublicSiteBuildError(f"forbidden public artifact marker {marker!r} in {path.name}")
        if ABSOLUTE_PATH.search(content):
            raise PublicSiteBuildError(f"local absolute path found in public artifact: {path.name}")


def _validate_with_adapter(stage: Path) -> None:
    node = shutil.which("node")
    if not node:
        raise PublicSiteBuildError("Node.js is required for public adapter validation")
    validator = ROOT / "scripts" / "validate_public_payload.mjs"
    for destination_id, filename in PAYLOAD_FILENAMES.items():
        result = subprocess.run([node, str(validator), str(stage / filename), destination_id],
                                cwd=ROOT, capture_output=True, text=True)
        if result.returncode:
            raise PublicSiteBuildError(f"adapter rejected {filename}: {result.stderr.strip()}")


def _build_release_managed(stage: Path, payloads: dict[str, dict[str, Any]],
                           service_dates: list[str]) -> list[str]:
    index_path = stage / "index.html"
    index_html = index_path.read_text(encoding="utf-8")
    marker = '<meta name="dotchi-data-mode" content="legacy">'
    if index_html.count(marker) != 1:
        raise PublicSiteBuildError("public HTML is missing its explicit legacy data-mode marker")
    index_path.write_text(index_html.replace(marker,
        '<meta name="dotchi-data-mode" content="release-managed">'), encoding="utf-8")
    asset_bytes = {name: (stage / name).read_bytes() for name in SOURCE_FILES}
    descriptor = build_release_descriptor(
        runtime_contract=RUNTIME_CONTRACT,
        builder_contract_version=BUILDER_CONTRACT_VERSION,
        payloads=payloads,
        assets=asset_bytes,
    )
    release_id = calculate_release_id(descriptor)
    release_dir = stage / "releases" / release_id
    release_dir.mkdir(parents=True)
    envelope_bytes: dict[str, bytes] = {}
    for station_id, filename in PAYLOAD_FILENAMES.items():
        envelope_bytes[station_id] = encode_envelope(
            release_id=release_id, station_id=station_id, payload=payloads[station_id])
        (release_dir / filename).write_bytes(envelope_bytes[station_id])
    first_payload = payloads[next(iter(PAYLOAD_FILENAMES))]
    manifest = create_manifest(
        release_id=release_id,
        release_descriptor=descriptor,
        published_at=None,
        generated_at=first_payload["generatedAt"],
        service_date_range={"from": service_dates[0], "through": service_dates[-1]},
        feed=first_payload["feed"],
        application_period=first_payload["applicationPeriod"],
        station_json_bytes=envelope_bytes,
    )
    (stage / "manifest.json").write_bytes(encode_manifest(manifest))
    validator = ROOT / "scripts" / "validate_public_artifact.py"
    result = subprocess.run([sys.executable, str(validator), "--release-managed", str(stage)],
                            cwd=ROOT, capture_output=True, text=True)
    if result.returncode:
        detail = result.stderr.strip() or "independent release validator rejected the artifact"
        raise PublicSiteBuildError(f"release-managed artifact validation failed: {detail}")
    return sorted(path.relative_to(stage).as_posix() for path in stage.rglob("*") if path.is_file())


def build_public_site(*, fixtures: Path, output: Path, release_managed: bool = False) -> dict[str, Any]:
    """Atomically build either the legacy 17-file site or opt-in release-managed artifact."""
    fixture_dir, output_dir = _ensure_safe_paths(fixtures, output)
    payloads, service_dates = _validate_fixture_directory(fixture_dir)
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    stage_root = Path(tempfile.mkdtemp(prefix=".public-site-stage-", dir=output_dir.parent))
    stage = stage_root / "site"
    stage.mkdir(mode=0o700)
    backup = output_dir.parent / (".public-site-backup-" + uuid.uuid4().hex)
    old_moved = False
    try:
        _copy_allowlisted_assets(stage)
        if release_managed:
            files = _build_release_managed(stage, payloads, service_dates)
        else:
            for destination_id, filename in PAYLOAD_FILENAMES.items():
                shutil.copyfile(fixture_dir / filename, stage / filename)
            _validate_with_adapter(stage)
            _validate_artifacts(stage)
            files = sorted(ARTIFACT_FILENAMES)
        for path in stage.rglob("*"):
            path.chmod(0o755 if path.is_dir() else 0o644)
        stage.chmod(0o755)
        if output_dir.exists():
            os.replace(output_dir, backup)
            old_moved = True
        try:
            os.replace(stage, output_dir)
        except Exception:
            if old_moved:
                os.replace(backup, output_dir)
                old_moved = False
            raise
        if old_moved:
            shutil.rmtree(backup)
            old_moved = False
        return {"output": output_dir, "payload_count": len(payloads), "service_dates": service_dates,
                "files": files, "release_managed": release_managed}
    finally:
        if old_moved and backup.exists() and not output_dir.exists():
            os.replace(backup, output_dir)
        shutil.rmtree(stage_root, ignore_errors=True)
        if backup.exists():
            shutil.rmtree(backup, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", required=True, type=Path,
                        help="directory containing exactly eight synthetic public-display-v1 payload fixtures")
    parser.add_argument("--output", required=True, type=Path,
                        help="explicit output directory outside the repository (never the public root mock)")
    parser.add_argument("--release-managed", action="store_true",
                        help="opt in to manifest.json plus immutable releases/<releaseId>/ station envelopes")
    args = parser.parse_args()
    try:
        result = build_public_site(fixtures=args.fixtures, output=args.output,
                                   release_managed=args.release_managed)
    except (PublicSiteBuildError, OSError, subprocess.SubprocessError) as error:
        print(f"public site build failed: {error}", file=sys.stderr)
        return 1
    print(f"Synthetic public site built at {result['output']}")
    print(f"Payloads: {result['payload_count']}; serviceDate: {', '.join(result['service_dates'])}")
    if result["release_managed"]:
        print(f"Release-managed files: {len(result['files'])}")
        print("Runtime compatibility: contract artifact only; not deployable until Phase 4-8C")
    else:
        print(f"Allowlisted files: {len(result['files'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
