"""Phase 4-8A content-addressed release, manifest and envelope contracts.

This module is deliberately not wired into the current public builder or
artifact validator. It operates on JSON-domain values and raw byte strings.
"""
from __future__ import annotations

from datetime import date, datetime
import hashlib
import json
import math
import re
from typing import Any

from public_payload_profile import PUBLIC_DATA_SCOPE, validate_public_payload

STATION_FILES = {
    "Kanamecho": "timetable-Kanamecho.json",
    "Senkawa": "timetable-Senkawa.json",
    "KotakeMukaihara": "timetable-KotakeMukaihara.json",
    "Hikawadai": "timetable.json",
    "Heiwadai": "timetable-Heiwadai.json",
    "ChikatetsuAkatsuka": "timetable-ChikatetsuAkatsuka.json",
    "ChikatetsuNarimasu": "timetable-ChikatetsuNarimasu.json",
    "Wakoshi": "timetable-Wakoshi.json",
}
RUNTIME_CONTRACT = "dotchi-public-runtime-v2"
MANIFEST_SCHEMA_VERSION = 1
ENVELOPE_SCHEMA_VERSION = 1
PAYLOAD_SCHEMA_VERSION = 1
RELEASE_ID_RE = re.compile(r"^r1-[0-9a-f]{64}$")
HASH_RE = re.compile(r"^[0-9a-f]{64}$")


class ReleaseContractError(ValueError):
    """Validation error with a stable machine-readable ``code``."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _fail(code: str, message: str) -> None:
    raise ReleaseContractError(code, message)


def _quote(value: str) -> str:
    if any(0xD800 <= ord(char) <= 0xDFFF for char in value):
        _fail("invalid_unicode", "unpaired UTF-16 surrogate is not valid JCS input")
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _float_jcs(value: float) -> str:
    if not math.isfinite(value):
        _fail("invalid_number", "JCS does not allow non-finite numbers")
    if value == 0:
        return "0"
    negative = value < 0
    raw = repr(abs(value)).lower()
    if "e" in raw:
        mantissa, exponent_text = raw.split("e", 1)
        exponent = int(exponent_text)
    else:
        mantissa, exponent = raw, 0
    if "." in mantissa:
        whole, fraction = mantissa.split(".", 1)
    else:
        whole, fraction = mantissa, ""
    digits = (whole + fraction).lstrip("0") or "0"
    decimal_position = len(whole) + exponent
    leading_zero_count = len(whole + fraction) - len((whole + fraction).lstrip("0"))
    decimal_position -= leading_zero_count
    digits = digits.rstrip("0") or "0"
    k = decimal_position
    if 0 < k <= 21:
        if len(digits) <= k:
            body = digits + "0" * (k - len(digits))
        else:
            body = digits[:k] + "." + digits[k:]
    elif -6 < k <= 0:
        body = "0." + "0" * (-k) + digits
    else:
        exponent_out = k - 1
        body = digits[0] + ("." + digits[1:] if len(digits) > 1 else "")
        body += "e" + ("+" if exponent_out >= 0 else "") + str(exponent_out)
    return ("-" if negative else "") + body


def _canonical(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        return _quote(value)
    if isinstance(value, int):
        if abs(value) > 9007199254740991:
            _fail("invalid_number", "integer is outside the interoperable IEEE-754 safe range")
        return str(value)
    if isinstance(value, float):
        return _float_jcs(value)
    if isinstance(value, list):
        return "[" + ",".join(_canonical(item) for item in value) + "]"
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            _fail("invalid_object_key", "JSON object keys must be strings")
        # RFC 8785 orders property names by UTF-16 code units, not Unicode scalar values.
        keys = sorted(value, key=lambda key: key.encode("utf-16-be", errors="strict"))
        return "{" + ",".join(_quote(key) + ":" + _canonical(value[key]) for key in keys) + "}"
    _fail("invalid_json_value", "value is outside the JSON data model")


def canonicalize_jcs(value: Any) -> bytes:
    """Return UTF-8 RFC 8785 canonical JSON bytes for a JSON-domain value."""
    try:
        return _canonical(value).encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        _fail("invalid_unicode", "unpaired UTF-16 surrogate is not valid JCS input")


def encode_manifest(value: dict[str, Any]) -> bytes:
    """Validate and serialize a manifest as RFC 8785 canonical UTF-8 bytes."""
    validate_manifest(value)
    return canonicalize_jcs(value)


def sha256_hex(raw: bytes) -> str:
    if not isinstance(raw, bytes):
        _fail("invalid_bytes", "raw bytes required")
    return hashlib.sha256(raw).hexdigest()


def _valid_hash(value: Any, code: str = "invalid_hash") -> bool:
    return isinstance(value, str) and HASH_RE.fullmatch(value) is not None


def _valid_release_id(value: Any) -> bool:
    return isinstance(value, str) and RELEASE_ID_RE.fullmatch(value) is not None


def build_release_descriptor(*, runtime_contract: str, builder_contract_version: str,
                             payloads: dict[str, dict[str, Any]],
                             assets: dict[str, bytes]) -> dict[str, Any]:
    """Bind schema/contracts, all 8 inner payloads, and HTML/CSS/JS asset bytes.

    Asset paths and station IDs are sorted by their JCS UTF-16 ordering when
    canonicalized. Payload hashes are over canonical inner payload bytes.
    """
    if set(payloads) != set(STATION_FILES):
        _fail("station_set", "descriptor requires exactly the eight supported stations")
    if not isinstance(runtime_contract, str) or not runtime_contract:
        _fail("invalid_contract", "runtime contract must be a nonempty string")
    if not isinstance(builder_contract_version, str) or not builder_contract_version:
        _fail("invalid_contract", "builder contract version must be a nonempty string")
    if not assets or any(not isinstance(path, str) or not path for path in assets):
        _fail("invalid_asset", "at least one asset with a nonempty path is required")
    descriptor_assets = []
    asset_extensions: set[str] = set()
    for path, raw in assets.items():
        if path.startswith("/") or "\\" in path or any(part in {"", ".", ".."} for part in path.split("/")):
            _fail("invalid_asset", "asset path must be a normalized relative path")
        if not isinstance(raw, bytes):
            _fail("invalid_asset", "asset contents must be raw bytes")
        asset_extensions.add(path.rsplit(".", 1)[-1].lower() if "." in path else "")
        descriptor_assets.append({"path": path, "sha256": sha256_hex(raw)})
    if "html" not in asset_extensions or "css" not in asset_extensions or not ({"js", "mjs"} & asset_extensions):
        _fail("invalid_asset", "descriptor must bind HTML, CSS, and JavaScript asset bytes")
    stations = []
    for station_id in sorted(payloads):
        try:
            validate_public_payload(payloads[station_id])
        except ValueError as error:
            _fail("invalid_payload", f"{station_id}: {error}")
        days = payloads[station_id]["serviceDays"]
        if any(day["destinationStationId"] != station_id for day in days):
            _fail("station_mismatch", f"payload does not belong to {station_id}")
        stations.append({"stationId": station_id,
                         "payloadSha256": sha256_hex(canonicalize_jcs(payloads[station_id]))})
    return {
        "manifestSchemaVersion": MANIFEST_SCHEMA_VERSION,
        "jsonEnvelopeSchemaVersion": ENVELOPE_SCHEMA_VERSION,
        "payloadSchemaVersion": PAYLOAD_SCHEMA_VERSION,
        "runtimeContract": runtime_contract,
        "publicDataScope": PUBLIC_DATA_SCOPE,
        "builderContractVersion": builder_contract_version,
        "assets": sorted(descriptor_assets, key=lambda item: item["path"].encode("utf-16-be")),
        "stations": stations,
    }


def calculate_release_id(descriptor: dict[str, Any]) -> str:
    """Calculate ``r1-<sha256>`` from the complete canonical descriptor."""
    required = {"manifestSchemaVersion", "jsonEnvelopeSchemaVersion", "payloadSchemaVersion",
                "runtimeContract", "publicDataScope", "builderContractVersion", "assets", "stations"}
    if not isinstance(descriptor, dict) or set(descriptor) != required:
        _fail("invalid_descriptor", "release descriptor has missing or unknown fields")
    if descriptor["manifestSchemaVersion"] != MANIFEST_SCHEMA_VERSION or \
       descriptor["jsonEnvelopeSchemaVersion"] != ENVELOPE_SCHEMA_VERSION or \
       descriptor["payloadSchemaVersion"] != PAYLOAD_SCHEMA_VERSION or \
       descriptor["publicDataScope"] != PUBLIC_DATA_SCOPE:
        _fail("invalid_descriptor", "release descriptor contract versions are unsupported")
    return "r1-" + sha256_hex(canonicalize_jcs(descriptor))


def _date(value: Any, code: str) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def _timestamp(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.tzinfo is not None and parsed.utcoffset() is not None
    except ValueError:
        return False


def _station_records(records: Any, release_id: str, *, retained: bool = False) -> None:
    if not isinstance(records, dict) or set(records) != set(STATION_FILES):
        _fail("station_set", "manifest must contain exactly the eight supported stations")
    urls: set[str] = set()
    for station_id, filename in STATION_FILES.items():
        record = records[station_id]
        if not isinstance(record, dict) or set(record) != {"url", "sha256", "bytes"}:
            _fail("invalid_station_record", f"{station_id} record has missing or unknown fields")
        url = record["url"]
        expected = f"/releases/{release_id}/{filename}"
        if not isinstance(url, str) or url != expected or ".." in url or "\\" in url or \
           "?" in url or "#" in url or "%" in url or url.startswith("//"):
            _fail("invalid_url", f"{station_id} URL must be its exact same-origin release path")
        if url in urls:
            _fail("duplicate_url", "manifest station URLs must be unique")
        urls.add(url)
        if not _valid_hash(record["sha256"]):
            _fail("invalid_hash", f"{station_id} sha256 must be 64 lowercase hex characters")
        if type(record["bytes"]) is not int or record["bytes"] <= 0:
            _fail("invalid_byte_count", f"{station_id} bytes must be a positive integer")


def validate_manifest(value: Any) -> dict[str, Any]:
    """Validate the strict Phase 4-7 manifest schema; unknown fields fail closed."""
    fields = {"schemaVersion", "releaseId", "runtimeContract", "jsonEnvelopeSchemaVersion",
              "payloadSchemaVersion", "dataScope", "publishedAt", "generatedAt",
              "serviceDateRange", "feed", "applicationPeriod", "stations",
              "retainedReleases", "legacyCompatibilityV1"}
    if not isinstance(value, dict) or set(value) != fields:
        _fail("manifest_fields", "manifest has missing or unknown fields")
    if type(value["schemaVersion"]) is not int or value["schemaVersion"] != MANIFEST_SCHEMA_VERSION:
        _fail("manifest_schema", "unsupported manifest schemaVersion")
    release_id = value["releaseId"]
    if not _valid_release_id(release_id):
        _fail("invalid_release_id", "releaseId must use r1- followed by 64 lowercase hex characters")
    if value["runtimeContract"] != RUNTIME_CONTRACT:
        _fail("compatibility_mismatch", "runtimeContract does not match this contract")
    if type(value["jsonEnvelopeSchemaVersion"]) is not int or value["jsonEnvelopeSchemaVersion"] != ENVELOPE_SCHEMA_VERSION or \
       type(value["payloadSchemaVersion"]) is not int or value["payloadSchemaVersion"] != PAYLOAD_SCHEMA_VERSION or \
       value["dataScope"] != PUBLIC_DATA_SCOPE:
        _fail("compatibility_mismatch", "manifest schema/data compatibility values do not match")
    if not _timestamp(value["publishedAt"]) or not _timestamp(value["generatedAt"]):
        _fail("invalid_timestamp", "publishedAt and generatedAt must include timezone offsets")
    date_range = value["serviceDateRange"]
    if not isinstance(date_range, dict) or set(date_range) != {"from", "through"} or \
       not _date(date_range.get("from"), "date") or not _date(date_range.get("through"), "date") or \
       date_range["from"] > date_range["through"]:
        _fail("invalid_date_range", "serviceDateRange must be an ordered YYYY-MM-DD range")
    feed = value["feed"]
    if not isinstance(feed, dict) or set(feed) != {"version", "validFrom", "validThrough", "sourceUpdatedAt"} or \
       not isinstance(feed["version"], str) or not feed["version"] or \
       not _date(feed["validFrom"], "date") or not _date(feed["validThrough"], "date") or \
       feed["validFrom"] > feed["validThrough"] or \
       (feed["sourceUpdatedAt"] is not None and not _timestamp(feed["sourceUpdatedAt"])):
        _fail("invalid_feed", "feed metadata is malformed")
    period = value["applicationPeriod"]
    if not isinstance(period, dict) or set(period) != {"startsAt", "endsAt"} or \
       not _timestamp(period["startsAt"]) or not _timestamp(period["endsAt"]):
        _fail("invalid_application_period", "applicationPeriod must contain zoned startsAt and endsAt")
    if datetime.fromisoformat(period["endsAt"].replace("Z", "+00:00")) <= \
       datetime.fromisoformat(period["startsAt"].replace("Z", "+00:00")):
        _fail("invalid_application_period", "applicationPeriod endsAt must follow startsAt")
    _station_records(value["stations"], release_id)
    retained = value["retainedReleases"]
    if not isinstance(retained, list):
        _fail("invalid_retained_releases", "retainedReleases must be an array")
    seen = {release_id}
    for item in retained:
        retained_fields = {"releaseId", "publishedAt", "retiredAt", "retainUntil", "serviceDateRange", "stations"}
        if not isinstance(item, dict) or set(item) != retained_fields or not _valid_release_id(item.get("releaseId")):
            _fail("invalid_retained_releases", "retained release entry is malformed")
        if item["releaseId"] in seen:
            _fail("duplicate_release", "current and retained release IDs must be unique")
        seen.add(item["releaseId"])
        if not all(_timestamp(item[key]) for key in ("publishedAt", "retiredAt", "retainUntil")):
            _fail("invalid_retained_releases", "retained timestamps must include timezone offsets")
        rr = item["serviceDateRange"]
        if not isinstance(rr, dict) or set(rr) != {"from", "through"} or \
           not _date(rr.get("from"), "date") or not _date(rr.get("through"), "date") or rr["from"] > rr["through"]:
            _fail("invalid_retained_releases", "retained serviceDateRange is malformed")
        _station_records(item["stations"], item["releaseId"], retained=True)
    legacy = value["legacyCompatibilityV1"]
    if legacy is not None:
        legacy_fields = {"expiresAt", "sourceLegacyDigest", "stations"}
        if not isinstance(legacy, dict) or set(legacy) != legacy_fields or not _timestamp(legacy.get("expiresAt")) or \
           not _valid_hash(legacy.get("sourceLegacyDigest")):
            _fail("invalid_legacy_compatibility", "legacyCompatibilityV1 metadata is malformed")
        if not isinstance(legacy["stations"], dict) or set(legacy["stations"]) != set(STATION_FILES):
            _fail("invalid_legacy_compatibility", "legacyCompatibilityV1 requires all eight station files")
        legacy_urls: set[str] = set()
        for station_id, filename in STATION_FILES.items():
            record = legacy["stations"][station_id]
            if not isinstance(record, dict) or set(record) != {"url", "sha256", "bytes"} or \
               record["url"] != f"/{filename}" or not _valid_hash(record["sha256"]) or \
               type(record["bytes"]) is not int or record["bytes"] <= 0:
                _fail("invalid_legacy_compatibility", f"legacy file record for {station_id} is malformed")
            if record["url"] in legacy_urls:
                _fail("invalid_legacy_compatibility", "legacy compatibility URLs must be unique")
            legacy_urls.add(record["url"])
    return value


def create_manifest(*, release_id: str, published_at: str, generated_at: str,
                    service_date_range: dict[str, str], feed: dict[str, Any],
                    application_period: dict[str, str], station_json_bytes: dict[str, bytes],
                    retained_releases: list[dict[str, Any]] | None = None,
                    legacy_compatibility_v1: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a current-release manifest from final envelope bytes.

    ``station_json_bytes`` must contain the complete encoded envelope for each
    station; hashes and byte counts are calculated from these exact bytes.
    """
    if not _valid_release_id(release_id):
        _fail("invalid_release_id", "invalid releaseId")
    if set(station_json_bytes) != set(STATION_FILES):
        _fail("station_set", "manifest generation requires exactly eight station JSON byte strings")
    stations = {}
    for station_id, filename in STATION_FILES.items():
        raw = station_json_bytes[station_id]
        if not isinstance(raw, bytes) or not raw:
            _fail("invalid_bytes", f"{station_id} must be nonempty raw JSON bytes")
        verify_envelope_bytes(raw, expected_release_id=release_id, expected_station_id=station_id,
                             expected_sha256=sha256_hex(raw), expected_bytes=len(raw))
        stations[station_id] = {"url": f"/releases/{release_id}/{filename}",
                                "sha256": sha256_hex(raw), "bytes": len(raw)}
    manifest = {
        "schemaVersion": MANIFEST_SCHEMA_VERSION,
        "releaseId": release_id,
        "runtimeContract": RUNTIME_CONTRACT,
        "jsonEnvelopeSchemaVersion": ENVELOPE_SCHEMA_VERSION,
        "payloadSchemaVersion": PAYLOAD_SCHEMA_VERSION,
        "dataScope": PUBLIC_DATA_SCOPE,
        "publishedAt": published_at,
        "generatedAt": generated_at,
        "serviceDateRange": service_date_range,
        "feed": feed,
        "applicationPeriod": application_period,
        "stations": stations,
        "retainedReleases": retained_releases if retained_releases is not None else [],
        "legacyCompatibilityV1": legacy_compatibility_v1,
    }
    validate_manifest(manifest)
    for station_id, raw in station_json_bytes.items():
        verify_station_bytes(raw, manifest, station_id)
    return manifest


def encode_envelope(*, release_id: str, station_id: str, payload: dict[str, Any]) -> bytes:
    """Create a validated envelope and return its canonical UTF-8 JSON bytes."""
    return canonicalize_jcs(create_envelope(release_id=release_id, station_id=station_id, payload=payload))


def verify_station_bytes(raw: bytes, manifest: dict[str, Any], station_id: str) -> dict[str, Any]:
    """Verify a station file against a previously validated current manifest."""
    validate_manifest(manifest)
    if station_id not in STATION_FILES:
        _fail("invalid_station", "unsupported stationId")
    record = manifest["stations"][station_id]
    envelope = verify_envelope_bytes(raw, expected_release_id=manifest["releaseId"],
                                     expected_station_id=station_id,
                                     expected_sha256=record["sha256"], expected_bytes=record["bytes"])
    payload = envelope["payload"]
    dates = [day["serviceDate"] for day in payload["serviceDays"]]
    if payload["generatedAt"] != manifest["generatedAt"] or payload["feed"] != manifest["feed"] or \
       payload["applicationPeriod"] != manifest["applicationPeriod"] or \
       min(dates) != manifest["serviceDateRange"]["from"] or max(dates) != manifest["serviceDateRange"]["through"]:
        _fail("manifest_payload_mismatch", "station payload common metadata differs from manifest")
    return envelope


def create_envelope(*, release_id: str, station_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    if not _valid_release_id(release_id):
        _fail("invalid_release_id", "invalid releaseId")
    if station_id not in STATION_FILES:
        _fail("invalid_station", "unsupported stationId")
    try:
        validate_public_payload(payload)
    except ValueError as error:
        _fail("invalid_payload", str(error))
    if any(day["destinationStationId"] != station_id for day in payload["serviceDays"]):
        _fail("station_mismatch", "inner payload destination does not match stationId")
    return {"schemaVersion": ENVELOPE_SCHEMA_VERSION, "releaseId": release_id,
            "stationId": station_id, "payloadSchemaVersion": PAYLOAD_SCHEMA_VERSION,
            "dataScope": PUBLIC_DATA_SCOPE, "payload": payload}


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail("invalid_json", "duplicate JSON property")
        result[key] = value
    return result


def verify_envelope_bytes(raw: bytes, *, expected_release_id: str, expected_station_id: str,
                          expected_sha256: str, expected_bytes: int) -> dict[str, Any]:
    """Check raw bytes/hash/length first, then JSON and envelope/payload schema."""
    if not isinstance(raw, bytes):
        _fail("invalid_bytes", "raw response bytes required")
    if type(expected_bytes) is not int or expected_bytes <= 0:
        _fail("invalid_byte_count", "expected byte count must be a positive integer")
    if len(raw) != expected_bytes:
        _fail("byte_count_mismatch", "response byte count differs from manifest")
    if not _valid_hash(expected_sha256):
        _fail("invalid_hash", "expected SHA-256 is malformed")
    if sha256_hex(raw) != expected_sha256:
        _fail("hash_mismatch", "response SHA-256 differs from manifest")
    try:
        value = json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=_reject_duplicate_pairs,
                           parse_constant=lambda _: _fail("invalid_json", "non-finite JSON number"))
    except ReleaseContractError:
        raise
    except (UnicodeError, json.JSONDecodeError, ValueError):
        _fail("invalid_json", "response bytes are not valid UTF-8 JSON")
    fields = {"schemaVersion", "releaseId", "stationId", "payloadSchemaVersion", "dataScope", "payload"}
    if not isinstance(value, dict) or set(value) != fields:
        _fail("envelope_fields", "envelope has missing or unknown fields")
    if type(value["schemaVersion"]) is not int or value["schemaVersion"] != ENVELOPE_SCHEMA_VERSION or \
       type(value["payloadSchemaVersion"]) is not int or value["payloadSchemaVersion"] != PAYLOAD_SCHEMA_VERSION or \
       value["dataScope"] != PUBLIC_DATA_SCOPE:
        _fail("compatibility_mismatch", "envelope compatibility values do not match")
    if value["releaseId"] != expected_release_id:
        _fail("release_id_mismatch", "envelope releaseId differs from pinned manifest")
    if value["stationId"] != expected_station_id or expected_station_id not in STATION_FILES:
        _fail("station_mismatch", "envelope stationId differs from requested station")
    try:
        validate_public_payload(value["payload"])
    except ValueError as error:
        _fail("invalid_payload", str(error))
    if any(day["destinationStationId"] != expected_station_id for day in value["payload"]["serviceDays"]):
        _fail("station_mismatch", "inner payload destination does not match requested station")
    return value
