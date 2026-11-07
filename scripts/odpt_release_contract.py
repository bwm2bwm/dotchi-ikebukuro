"""Offline v2 release DATA contract. No runtime, deployment, or approval creation.

The candidate stays unapproved; applicability belongs to separately approved
publication metadata. Hashes bind content, not the identity of an approver.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import re

import odpt_public_v2 as v2
import odpt_snapshot_qa as qa
from release_contract import canonicalize_jcs as canonical, sha256_hex as digest, STATION_FILES

SCOPE = "public-display-v2"
RUNTIME = "dotchi-odpt-public-v2"
KIND = "release-data-only"
MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_TOTAL_BYTES = 256 * 1024 * 1024
ROOT = Path(__file__).resolve().parents[1]
SOURCES = (*qa.REQUIRED_JSON, qa.GTFS_NAME)


class ContractError(ValueError):
    pass


def require(condition, code):
    if not condition:
        raise ContractError(code)


def exact(value, keys):
    require(isinstance(value, dict) and set(value) == set(keys), "fields_invalid")
    return value


def hash_value(value):
    require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value), "hash_invalid")


def timestamp(value):
    require(isinstance(value, str) and re.fullmatch(
        r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)", value), "timestamp_invalid")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        raise ContractError("timestamp_invalid") from None


def safe_text(value):
    require(isinstance(value, str) and 0 < len(value) <= 200
            and re.fullmatch(r"[\w .:/#()、。・〜（）−-]+", value)
            and not any(x in value.lower() for x in ("/users/", "/private/", "consumerkey", "api_key", "?", "@")),
            "public_text_invalid")


def load_json(raw):
    def pairs(items):
        out = {}
        for key, value in items:
            require(key not in out, "duplicate_json_key")
            out[key] = value
        return out
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                          parse_constant=lambda _: require(False, "nonfinite_json"))
    except (UnicodeError, ValueError) as error:
        if isinstance(error, ContractError):
            raise
        raise ContractError("json_invalid") from None


def safe_path(path):
    path = Path(path).absolute()
    require(".." not in path.parts, "path_traversal_rejected")
    require(not any(p.is_symlink() for p in (path, *path.parents)), "symlink_rejected")
    return path.resolve()


def read_file(path, limit=MAX_FILE_BYTES):
    path = safe_path(path)
    require(path.is_file() and 0 < path.stat().st_size <= limit, "file_invalid_or_oversize")
    before = path.stat()
    raw = path.read_bytes()
    after = path.stat()
    require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
            (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns), "file_changed")
    require(0 < len(raw) <= limit, "file_invalid_or_oversize")
    return raw


def candidate_digest(bundle):
    """SHA-256 of JCS records of exact manifest + eight raw candidate files."""
    bundle = safe_path(bundle)
    paths = ["private-generator-manifest.json", *(
        "public-candidates/" + name for name in v2.ROUTE_FILENAMES.values())]
    records = [{"path": name, "bytes": len(raw), "sha256": digest(raw)}
               for name in sorted(paths) for raw in [read_file(bundle / name)]]
    return digest(canonical(records))


def validate_sources(entries, expected):
    require(isinstance(entries, list) and len(entries) == len(SOURCES), "source_set_invalid")
    require([x.get("path") for x in entries if isinstance(x, dict)] == list(SOURCES), "source_order_invalid")
    for item in entries:
        exact(item, {"path", "sizeBytes", "sha256"})
        require(type(item["sizeBytes"]) is int and item["sizeBytes"] > 0, "source_bytes_invalid")
        hash_value(item["sha256"])
    hash_value(expected)
    require(qa._fingerprint(entries) == expected, "source_fingerprint_mismatch")


def validate_metadata(meta, dates, now):
    exact(meta, {"candidateDigest", "sourceFingerprint", "sourceFiles", "applicationPeriod",
                 "approval", "codeCommit", "retrievedAt", "feed", "attribution", "evidenceKind",
                 "quality", "transferSearchPolicy"})
    hash_value(meta["candidateDigest"])
    validate_sources(meta["sourceFiles"], meta["sourceFingerprint"])
    require(meta["evidenceKind"] in {"synthetic", "odpt-acquired"}, "evidence_kind_invalid")
    require(isinstance(meta["codeCommit"], str) and re.fullmatch(r"[0-9a-f]{40}", meta["codeCommit"]), "commit_invalid")
    approval = exact(meta["approval"], {"approved", "recordId", "approvedAt"})
    require(approval["approved"] is True, "approval_required")
    safe_text(approval["recordId"])
    require(timestamp(meta["retrievedAt"]) <= timestamp(approval["approvedAt"]) <= now,
            "approval_time_invalid")
    period = exact(meta["applicationPeriod"], {"startsAt", "endsAt"})
    start, end = timestamp(period["startsAt"]), timestamp(period["endsAt"])
    require(start < end and start <= now < end, "application_period_outside_or_invalid")
    require(isinstance(dates, list) and 3 <= len(dates) <= 366, "service_dates_invalid")
    try:
        parsed = [date.fromisoformat(d) for d in dates]
    except (TypeError, ValueError):
        raise ContractError("service_dates_invalid") from None
    require(all(d.isoformat() == s for d, s in zip(parsed, dates)) and
            all(b - a == timedelta(days=1) for a, b in zip(parsed, parsed[1:])), "service_dates_invalid")
    jst = timezone(timedelta(hours=9))
    first = start.astimezone(jst).date() - timedelta(days=1)
    last = (end - timedelta(microseconds=1)).astimezone(jst).date() + timedelta(days=1)
    require(parsed[0] <= first and last <= parsed[-1], "publication_buffer_dates_missing")
    feed = exact(meta["feed"], {"version", "validFrom", "validThrough"})
    require(isinstance(feed["version"], str) and re.fullmatch(r"[\w.-]{1,80}", feed["version"]), "feed_invalid")
    require((meta["evidenceKind"] == "synthetic") == feed["version"].startswith("synthetic"), "evidence_source_mismatch")
    try:
        lo, hi = date.fromisoformat(feed["validFrom"]), date.fromisoformat(feed["validThrough"])
    except (TypeError, ValueError):
        raise ContractError("feed_invalid") from None
    require(lo.isoformat() == feed["validFrom"] and hi.isoformat() == feed["validThrough"]
            and lo <= parsed[0] <= parsed[-1] <= hi, "feed_period_mismatch")
    attribution = exact(meta["attribution"], {"provider", "sourceUrl"})
    require(attribution == {"provider": "東京メトロ / 公共交通オープンデータセンター",
                            "sourceUrl": "https://www.odpt.org/"}, "attribution_invalid")
    require(meta["transferSearchPolicy"] == {"minimumWaitSeconds": 60,
            "maximumWaitSeconds": 3600, "crossServiceDateSearch": False}, "transfer_policy_invalid")


def validate_quality(quality, payloads, dates):
    exact(quality, {"status", "failGateCount", "unmatchedOriginal", "warningOriginal", "resolution",
                    "stationDateResolution", "exclusionAudit", "odptMatchStatusCounts"})
    require(quality["status"] in {"PASS", "WARNING"} and type(quality["failGateCount"]) is int
            and quality["failGateCount"] == 0, "quality_failed")
    v2._validate_resolution(quality["resolution"], quality["unmatchedOriginal"], quality["warningOriginal"])
    require(quality["status"] != "PASS" or quality["warningOriginal"] == quality["unmatchedOriginal"] == 0,
            "quality_status_mismatch")
    rows = quality["stationDateResolution"]
    expected = {(s, d) for s in STATION_FILES for d in dates}
    require(isinstance(rows, list) and len(rows) == len(expected), "quality_scope_invalid")
    seen = set()
    for row in rows:
        exact(row, {"stationId", "serviceDate", "resolution"})
        pair = (row["stationId"], row["serviceDate"])
        require(pair in expected and pair not in seen, "quality_scope_invalid")
        seen.add(pair)
        r = row["resolution"]
        require(isinstance(r, dict) and isinstance(r.get("unmatched"), dict)
                and isinstance(r.get("warningCodes"), dict), "quality_resolution_invalid")
        v2._validate_resolution(r, r["unmatched"].get("original"), r["warningCodes"].get("original"))
    require(qa._merge_resolutions(row["resolution"] for row in rows) == quality["resolution"], "quality_totals_mismatch")
    counts = quality["odptMatchStatusCounts"]
    require(isinstance(counts, dict) and set(counts) <= {"matched", "unique_match", "unmatched", "ambiguous"}
            and all(type(x) is int and x >= 0 for x in counts.values()), "match_counts_invalid")
    require(sum(v for k, v in counts.items() if k not in {"matched", "unique_match"}) == quality["unmatchedOriginal"], "match_counts_mismatch")
    actual = {(s, day["serviceDate"]): len(day["departures"])
              for s, payload in payloads.items() for day in payload["serviceDays"]}
    audit = quality["exclusionAudit"]
    require(isinstance(audit, dict), "audit_missing")
    v2._validate_exclusion_audit(audit, list(STATION_FILES), dates, actual, audit.get("totalGeneratedCount"))
    require(sum(counts.values()) == audit["totalGeneratedCount"], "match_total_mismatch")


def release_id(descriptor):
    exact(descriptor, {"manifestSchemaVersion", "jsonEnvelopeSchemaVersion", "payloadSchemaVersion",
                       "publicDataScope", "runtimeContract", "builderContractVersion", "metadataSha256", "stations"})
    require(type(descriptor["manifestSchemaVersion"]) is int and descriptor["manifestSchemaVersion"] == 2
            and type(descriptor["payloadSchemaVersion"]) is int and descriptor["payloadSchemaVersion"] == 2
            and type(descriptor["jsonEnvelopeSchemaVersion"]) is int and descriptor["jsonEnvelopeSchemaVersion"] == 1
            and descriptor["publicDataScope"] == SCOPE and descriptor["runtimeContract"] == RUNTIME
            and descriptor["builderContractVersion"] == "dotchi-odpt-release-builder-v1", "descriptor_profile_invalid")
    hash_value(descriptor["metadataSha256"])
    require(isinstance(descriptor["stations"], list) and len(descriptor["stations"]) == 8, "descriptor_stations_invalid")
    for row, station in zip(descriptor["stations"], sorted(STATION_FILES)):
        exact(row, {"stationId", "payloadSha256"})
        require(row["stationId"] == station, "descriptor_stations_invalid")
        hash_value(row["payloadSha256"])
    return "r1-" + digest(canonical(descriptor))


def validate_manifest(manifest, now=None):
    exact(manifest, {"schemaVersion", "artifactKind", "releaseId", "releaseDescriptor", "runtimeContract",
                     "payloadSchemaVersion", "dataScope", "serviceDates", "metadata", "stations", "retainedReleases"})
    require(type(manifest["schemaVersion"]) is int and manifest["schemaVersion"] == 2
            and type(manifest["payloadSchemaVersion"]) is int and manifest["payloadSchemaVersion"] == 2
            and manifest["dataScope"] == SCOPE and manifest["runtimeContract"] == RUNTIME
            and manifest["artifactKind"] == KIND and manifest["retainedReleases"] == [], "manifest_profile_invalid")
    now = now or datetime.now(timezone.utc)
    require(now.tzinfo is not None, "validation_time_invalid")
    validate_metadata(manifest["metadata"], manifest["serviceDates"], now)
    descriptor = manifest["releaseDescriptor"]
    require(release_id(descriptor) == manifest["releaseId"], "release_id_mismatch")
    require(descriptor["metadataSha256"] == digest(canonical(manifest["metadata"])), "metadata_hash_mismatch")
    exact(manifest["stations"], STATION_FILES)
    for station, filename in STATION_FILES.items():
        row = exact(manifest["stations"][station], {"url", "sha256", "bytes"})
        require(row["url"] == f"/releases/{manifest['releaseId']}/{filename}", "station_url_invalid")
        hash_value(row["sha256"])
        require(type(row["bytes"]) is int and 0 < row["bytes"] <= MAX_FILE_BYTES, "station_bytes_invalid")
    return manifest


def validate_envelope(raw, manifest, station):
    record = manifest["stations"][station]
    require(len(raw) == record["bytes"] and digest(raw) == record["sha256"], "envelope_integrity_mismatch")
    envelope = exact(load_json(raw), {"schemaVersion", "releaseId", "stationId", "payloadSchemaVersion", "dataScope", "payload"})
    require(canonical(envelope) == raw, "envelope_not_canonical")
    require(type(envelope["schemaVersion"]) is int and envelope["schemaVersion"] == 1
            and type(envelope["payloadSchemaVersion"]) is int and envelope["payloadSchemaVersion"] == 2
            and envelope["dataScope"] == SCOPE and envelope["releaseId"] == manifest["releaseId"]
            and envelope["stationId"] == station, "envelope_profile_mismatch")
    payload = v2.validate_v2_payload(envelope["payload"])
    require(payload["stationId"] == station and [d["serviceDate"] for d in payload["serviceDays"]] == manifest["serviceDates"], "payload_scope_mismatch")
    require(all(c["dataState"] == "complete" for d in payload["serviceDays"] for c in d["routeCoverage"].values()), "coverage_incomplete")
    expected = next(r["payloadSha256"] for r in manifest["releaseDescriptor"]["stations"] if r["stationId"] == station)
    require(digest(canonical(payload)) == expected, "payload_descriptor_mismatch")
    return payload
