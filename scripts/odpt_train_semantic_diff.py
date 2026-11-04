#!/usr/bin/env python3
"""Private, offline TrainTimetable comparison under semantic profile 1.0.0."""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any

if __package__:
    from .odpt_source_contract import SOURCE_FILES, SOURCE_IDS
    from .odpt_source_diff import SourceDiffError, compare_stores
    from .odpt_source_store import StoreError, load_store_contract
else:
    from odpt_source_contract import SOURCE_FILES, SOURCE_IDS
    from odpt_source_diff import SourceDiffError, compare_stores
    from odpt_source_store import StoreError, load_store_contract

PROFILE = {"id": "dotchi.odpt-gtfs.semantic", "version": "1.0.0"}
TARGETS = frozenset({"metro.train-timetable.yurakucho", "metro.train-timetable.fukutoshin"})
NEW_TARGETS = frozenset({"metro.railway", "metro.station", "metro.station-timetable.yurakucho",
                         "metro.station-timetable.fukutoshin"})
SEMANTIC_TARGETS = TARGETS | NEW_TARGETS
MAX_SOURCE_BYTES = 128 * 1024 * 1024
MAX_RECORDS = 20_000
MAX_EVENTS = 500_000
MAX_DETAILS = 1_000  # shared by changes, unknown fields, ambiguities and warnings, per source
MAX_DEPTH = 32
EVENTS = "odpt:trainTimetableObject"
TIMES = frozenset({"odpt:arrivalTime", "odpt:departureTime"})
STATIONS = frozenset({"odpt:arrivalStation", "odpt:departureStation"})
METADATA = frozenset({"dc:date", "dct:issued"})
IDS = frozenset({"owl:sameAs", "@id", "odpt:train", "odpt:trainNumber"})
REFERENCES = frozenset({"odpt:railway", "odpt:railDirection", "odpt:calendar", "odpt:operator"})
ARRAYS = frozenset({"odpt:originStation", "odpt:destinationStation"})
STRINGS = IDS | REFERENCES | frozenset({"@context", "@type", "odpt:trainType"})
KNOWN = STRINGS | ARRAYS | METADATA | {EVENTS}
CONTEXT = "http://vocab.odpt.org/context_odpt_TrainTimetable.jsonld"
MISSING = object()
TIME_RE = re.compile(r"[0-9]{2,3}:[0-9]{2}(?::[0-9]{2})?\Z")
CATALOG_COMMON = frozenset({"owl:sameAs", "@id", "@context", "@type", "dc:date", "dc:title", "odpt:operator"})
CATALOG_COMMON |= {"dct:issued"}
RAILWAY_FIELDS = CATALOG_COMMON | {"odpt:lineCode", "odpt:railwayTitle", "odpt:color",
    "odpt:ascendingRailDirection", "odpt:descendingRailDirection", "odpt:stationOrder"}
STATION_FIELDS = CATALOG_COMMON | {"odpt:railway", "odpt:stationCode", "odpt:stationTitle", "geo:lat", "geo:long",
    "odpt:connectingRailway", "odpt:connectingStation", "odpt:stationTimetable", "odpt:passengerSurvey"}
STATION_TIMETABLE_FIELDS = CATALOG_COMMON | {"odpt:station", "odpt:railway", "odpt:railDirection", "odpt:calendar",
    "odpt:stationTimetableObject"}
STATION_EVENT_FIELDS = frozenset({"odpt:train", "odpt:trainNumber", "odpt:departureTime", "odpt:trainType",
    "odpt:destinationStation", "odpt:isOrigin", "odpt:isLast"})
JSONLD_CONTEXTS = {"metro.railway": "http://vocab.odpt.org/context_odpt_Railway.jsonld",
    "metro.station": "http://vocab.odpt.org/context_odpt_Station.jsonld",
    "metro.station-timetable.yurakucho": "http://vocab.odpt.org/context_odpt_StationTimetable.jsonld",
    "metro.station-timetable.fukutoshin": "http://vocab.odpt.org/context_odpt_StationTimetable.jsonld"}


class SemanticDiffError(ValueError):
    """Only fixed, non-sensitive codes may leave this module as errors."""
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _fail(code: str) -> None:
    raise SemanticDiffError(code)


def _root(value: Path) -> Path:
    if not isinstance(value, Path) or not value.is_absolute():
        _fail("source_directory_must_be_absolute")
    if ".." in value.parts:
        _fail("source_path_traversal")
    current = Path(value.anchor)
    try:
        for part in value.parts[1:]:
            current /= part
            if stat.S_ISLNK(current.lstat().st_mode):
                _fail("source_path_symlink")
        if not value.is_dir():
            _fail("source_directory_invalid")
    except OSError:
        _fail("source_directory_unavailable")
    return value


def _identity(info: os.stat_result) -> tuple[int, int, int, int, int]:
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _read_bytes(path: Path) -> tuple[bytes, tuple[int, int, int, int, int]]:
    try:
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode):
            _fail("source_not_regular_file")
        if before.st_size > MAX_SOURCE_BYTES:
            _fail("source_size_limit_exceeded")
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as stream:
            raw = stream.read(MAX_SOURCE_BYTES + 1)
            after_fd = os.fstat(stream.fileno())
        after = path.lstat()
    except FileNotFoundError:
        _fail("source_unavailable")
    except OSError:
        _fail("source_read_failed")
    if len(raw) > MAX_SOURCE_BYTES:
        _fail("source_size_limit_exceeded")
    if (_identity(before) != _identity(after_fd) or _identity(before) != _identity(after)
            or len(raw) != before.st_size):
        _fail("source_changed_while_reading")
    return raw, _identity(after)


def _signature(raw: bytes) -> tuple[str, int]:
    return hashlib.sha256(raw).hexdigest(), len(raw)


def _seconds(value: Any) -> int | None:
    if not isinstance(value, str) or not TIME_RE.fullmatch(value):
        return None
    parts = [int(part) for part in value.split(":")]
    h, m = parts[:2]
    s = parts[2] if len(parts) == 3 else 0
    return h * 3600 + m * 60 + s if m < 60 and s < 60 else None


def _token(value: Any, depth: int = 0) -> Any:
    """Type-preserving equality; in particular False != 0 and missing != null."""
    if depth > MAX_DEPTH:
        _fail("json_depth_limit_exceeded")
    if value is MISSING:
        return ("missing",)
    if isinstance(value, dict):
        return ("object", tuple((k, _token(v, depth + 1)) for k, v in sorted(value.items())))
    if isinstance(value, list):
        return ("array", tuple(_token(v, depth + 1) for v in value))
    return (type(value).__name__, str(value))


def _pointer(parts: tuple[Any, ...]) -> str:
    return "/" + "/".join(str(p).replace("~", "~0").replace("/", "~1") for p in parts)


def _parse(raw: bytes, source_id: str) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result = {}
        for key, value in items:
            if key in result:
                _fail("json_duplicate_key")
            result[key] = value
        return result
    try:
        rows = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_float=Decimal,
                          parse_constant=lambda _value: _fail("json_constant_invalid"))
        _token(rows)  # bounds nesting, including unknown extensions
    except SemanticDiffError:
        raise
    except (UnicodeDecodeError, ValueError, ArithmeticError, RecursionError):
        _fail("json_invalid")
    if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
        _fail("json_structure_invalid")
    if source_id in NEW_TARGETS:
        return _parse_catalog_rows(rows, source_id)
    if len(rows) > MAX_RECORDS:
        _fail("record_limit_exceeded")
    indexed = {}
    ids = set()
    event_count = 0
    line = "Yurakucho" if source_id.endswith("yurakucho") else "Fukutoshin"
    for row in rows:
        for field in STRINGS:
            if not isinstance(row.get(field), str) or not row[field]:
                _fail("record_identifier_or_reference_type_invalid")
        if row["owl:sameAs"] in indexed:
            _fail("same_as_duplicate")
        if row["@id"] in ids:
            _fail("at_id_duplicate")
        if row["@type"] != "odpt:TrainTimetable":
            _fail("record_type_unsupported")
        if row["odpt:railway"] != f"odpt.Railway:TokyoMetro.{line}":
            _fail("source_railway_mismatch")
        for field in ARRAYS:
            values = row.get(field)
            if not isinstance(values, list) or not values or any(not isinstance(v, str) or not v for v in values):
                _fail("station_reference_array_invalid")
        for field in METADATA:
            if field in row and row[field] is not None and not isinstance(row[field], str):
                _fail("metadata_type_invalid")
        events = row.get(EVENTS)
        if not isinstance(events, list) or not events:
            _fail("event_array_invalid")
        event_count += len(events)
        if event_count > MAX_EVENTS:
            _fail("event_limit_exceeded")
        for event in events:
            if not isinstance(event, dict) or not (STATIONS & event.keys()):
                _fail("event_structure_invalid")
            for field in STATIONS & event.keys():
                if not isinstance(event[field], str) or not event[field]:
                    _fail("event_station_type_invalid")
            for field in TIMES & event.keys():
                value = event[field]
                if value is not None and value != "" and _seconds(value) is None:
                    _fail("event_time_invalid")
                station = field.replace("Time", "Station")
                if station not in event:
                    _fail("event_time_station_reference_missing")
        indexed[row["owl:sameAs"]] = row
        ids.add(row["@id"])
    return rows, indexed


def _is_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value)


def _parse_catalog_rows(rows: list[dict[str, Any]], source_id: str):
    if len(rows) > MAX_RECORDS:
        _fail("record_limit_exceeded")
    indexed, ids = {}, set()
    if source_id == "metro.railway":
        known = RAILWAY_FIELDS
        id_lists = {"odpt:stationTimetable", "odpt:passengerSurvey"}
        nested_list = "odpt:stationOrder"
        event_known = frozenset()
    elif source_id == "metro.station":
        known = STATION_FIELDS
        id_lists = {"odpt:connectingRailway", "odpt:connectingStation", "odpt:stationTimetable", "odpt:passengerSurvey"}
        nested_list = None
        event_known = frozenset()
    else:
        known = STATION_TIMETABLE_FIELDS
        id_lists = set()
        nested_list = "odpt:stationTimetableObject"
        event_known = STATION_EVENT_FIELDS
    for row in rows:
        for field in ("owl:sameAs", "@id"):
            if not _is_text(row.get(field)):
                _fail("record_identifier_or_reference_type_invalid")
        if row["owl:sameAs"] in indexed:
            _fail("same_as_duplicate")
        if row["@id"] in ids:
            _fail("at_id_duplicate")
        if not _is_text(row.get("@context")) or not _is_text(row.get("@type")):
            _fail("schema_context_type_invalid")
        expected_type = ("odpt:Railway" if source_id == "metro.railway" else
                         "odpt:Station" if source_id == "metro.station" else "odpt:StationTimetable")
        if row["@type"] != expected_type:
            _fail("record_type_unsupported")
        required_references = ("odpt:railway",) if source_id == "metro.station" else (
            ("odpt:station", "odpt:railway", "odpt:railDirection", "odpt:calendar")
            if source_id.startswith("metro.station-timetable") else ())
        if any(not _is_text(row.get(field)) for field in required_references):
            _fail("record_reference_required")
        for field in known - {"owl:sameAs", "@id", "dc:date", "dc:title", "odpt:railwayTitle", "odpt:stationTitle",
                              "geo:lat", "geo:long", "odpt:color", "odpt:stationOrder", "odpt:stationTimetableObject",
                              "odpt:connectingRailway", "odpt:connectingStation", "odpt:stationTimetable", "odpt:passengerSurvey"}:
            if field in row and not _is_text(row[field]):
                _fail("reference_field_type_invalid")
        for field in known & {"dc:date", "dc:title", "odpt:lineCode", "odpt:stationCode", "odpt:color"}:
            if field in row and row[field] is not None and not isinstance(row[field], str):
                _fail("metadata_type_invalid")
        for field in ("odpt:railwayTitle", "odpt:stationTitle"):
            if field in row and (not isinstance(row[field], dict) or
                                 any(not isinstance(k, str) or not isinstance(v, str) for k, v in row[field].items())):
                _fail("localized_title_invalid")
        for field in ("geo:lat", "geo:long"):
            if field in row and (isinstance(row[field], bool) or not isinstance(row[field], (int, Decimal))):
                _fail("coordinate_type_invalid")
        for field in id_lists:
            if field in row and (not isinstance(row[field], list) or any(not _is_text(v) for v in row[field])):
                _fail("reference_array_invalid")
        if nested_list and nested_list in row:
            values = row[nested_list]
            if not isinstance(values, list):
                _fail("event_array_invalid")
            if nested_list == "odpt:stationOrder":
                for event in values:
                    if not isinstance(event, dict) or type(event.get("odpt:index")) is not int or not _is_text(event.get("odpt:station")) or not isinstance(event.get("odpt:stationTitle"), dict):
                        _fail("station_order_event_invalid")
                    if any(not isinstance(v, str) for v in event["odpt:stationTitle"].values()):
                        _fail("station_order_title_invalid")
            else:
                for event in values:
                    if not isinstance(event, dict):
                        _fail("event_structure_invalid")
                    for field in event_known & {"odpt:train", "odpt:trainNumber", "odpt:departureTime", "odpt:trainType"}:
                        if field in event and not _is_text(event[field]):
                            _fail("station_event_field_invalid")
                    if "odpt:destinationStation" in event and (not isinstance(event["odpt:destinationStation"], list) or any(not _is_text(v) for v in event["odpt:destinationStation"])):
                        _fail("station_event_field_invalid")
                    for field in ("odpt:isOrigin", "odpt:isLast"):
                        if field in event and type(event[field]) is not bool:
                            _fail("station_event_field_invalid")
        indexed[row["owl:sameAs"]] = row
        ids.add(row["@id"])
    if source_id.startswith("metro.station-timetable"):
        keys = [(row.get("odpt:station"), row.get("odpt:railway"), row.get("odpt:railDirection"), row.get("odpt:calendar")) for row in rows]
        if len(keys) != len(set(keys)):
            _fail("station_timetable_auxiliary_key_duplicate")
    return rows, indexed


def _empty(source_id: str) -> dict[str, Any]:
    return {"sourceId": source_id, "inputBytesStatus": {}, "coverage": "not-evaluated",
            "comparisonStatus": "not-evaluated", "semanticStatus": "indeterminate",
            "categories": [], "categoryCounts": {},
            "counts": {"added": 0, "removed": 0, "modified": 0, "changes": 0},
            "changes": [], "unknownFields": [], "ambiguities": [], "warnings": [],
            "errorCodes": [], "truncated": False, "detailLimit": MAX_DETAILS}


class _Evidence:
    def __init__(self, result: dict[str, Any]):
        self.result = result
        self.count = 0
        self.categories: Counter[str] = Counter()

    def add(self, bucket: str, value: dict[str, Any]) -> None:
        if self.count < MAX_DETAILS:
            self.result[bucket].append(value)
            self.count += 1
        else:
            self.result["truncated"] = True

    def change(self, key: str, parts: tuple[Any, ...], kind: str, left: Any, right: Any) -> None:
        detail = {"recordKey": key, "fieldPath": _pointer(parts), "kind": kind,
                  "baselineState": "missing" if left is MISSING else type(left).__name__,
                  "candidateState": "missing" if right is MISSING else type(right).__name__}
        if kind == "time-changed" and _seconds(left) is not None and _seconds(right) is not None:
            detail["deltaSeconds"] = _seconds(right) - _seconds(left)
        self.add("changes", detail)
        self.categories[kind] += 1
        self.result["counts"]["changes"] += 1


def _known_for(source_id: str) -> frozenset[str]:
    if source_id == "metro.railway": return RAILWAY_FIELDS
    if source_id == "metro.station": return STATION_FIELDS
    if source_id in NEW_TARGETS: return STATION_TIMETABLE_FIELDS
    return KNOWN


def _dynamic_key(parent: dict[str, Any], key: str) -> bool:
    return key == parent.get("owl:sameAs", "").split(":", 1)[-1]


def _unknown(row: dict[str, Any], source_id: str) -> list[tuple[Any, ...]]:
    known = _known_for(source_id)
    paths = [(key,) for key in sorted(row.keys() - known)]
    event_field = EVENTS if source_id in TARGETS else "odpt:stationTimetableObject"
    for i, event in enumerate(row.get(event_field, [])):
        allowed = STATIONS | TIMES if source_id in TARGETS else STATION_EVENT_FIELDS
        paths.extend((event_field, i, key) for key in sorted(event.keys() - allowed)
                     if not (source_id in NEW_TARGETS and _dynamic_key(row, key)))
    if source_id == "metro.railway":
        for i, event in enumerate(row.get("odpt:stationOrder", [])):
            paths.extend(("odpt:stationOrder", i, key) for key in sorted(
                event.keys() - {"odpt:index", "odpt:station", "odpt:stationTitle"}))
            title = event.get("odpt:stationTitle")
            if isinstance(title, dict):
                paths.extend(("odpt:stationOrder", i, "odpt:stationTitle", key)
                             for key in sorted(title) if not isinstance(title[key], str))
    return paths


def _opaque_count(row: dict[str, Any], source_id: str) -> int:
    if source_id not in NEW_TARGETS or source_id.startswith("metro.station-timetable") is False:
        return 0
    return sum(_dynamic_key(row, key) for event in row.get("odpt:stationTimetableObject", []) for key in event)


def _kind(parts: tuple[Any, ...], source_id: str, left: Any = None, right: Any = None) -> str:
    field = parts[0]
    if source_id == "metro.station" and field not in {"owl:sameAs", "@id", "@context", "@type", "dc:date", "dct:issued", "dc:title"}:
        return "reference-data-changed"
    if field not in _known_for(source_id):
        return "unknown-field-changed"
    if field == "odpt:stationOrder":
        if len(parts) == 2 and (left is MISSING or right is MISSING):
            return "station-added" if left is MISSING else "station-removed"
        return "station-order-changed"
    if field == "odpt:stationTimetableObject" and len(parts) > 2 and parts[2] not in STATION_EVENT_FIELDS:
        return "opaque-extension-changed" if source_id.startswith("metro.station-timetable") else "unsupported-field-change"
    if field == "odpt:stationTimetableObject":
        if len(parts) == 2 and (left is MISSING or right is MISSING):
            return "event-added" if left is MISSING else "event-removed"
        changed = parts[2] if len(parts) > 2 else parts[-1]
        if changed == "odpt:departureTime": return "time-changed"
        if changed == "odpt:trainType": return "train-type-changed"
        if changed == "odpt:destinationStation": return "destination-changed"
        return "reference-data-changed"
    if source_id == "metro.station" and field in {"odpt:connectingRailway", "odpt:connectingStation", "odpt:stationTimetable", "odpt:passengerSurvey"}:
        return "reference-data-changed"
    if source_id == "metro.railway" and field == "odpt:stationOrder": return "station-order-changed"
    if field in METADATA:
        return "metadata-changed"
    if field in IDS:
        return "identifier-changed"
    if field == "odpt:trainType":
        return "train-type-changed"
    if field == "odpt:destinationStation":
        return "destination-changed"
    if field == "odpt:originStation":
        return "origin-changed"
    if field == EVENTS:
        if parts[-1] in TIMES:
            return "time-changed"
        if parts[-1] in STATIONS:
            return "stop-station-changed"
        return "event-structure-changed"
    if field in {"@context", "@type"}:
        return "schema-context-changed"
    return "reference-changed"


def _walk(key: str, parts: tuple[Any, ...], left: Any, right: Any, evidence: _Evidence,
          source_id: str, aligned: bool = True) -> None:
    if _token(left) == _token(right):
        return
    if parts and parts[0] == EVENTS and parts[-1] in TIMES:
        if _seconds(left) is not None and _seconds(left) == _seconds(right):
            return  # HH:MM and HH:MM:00; never reduce modulo 24 hours
    if isinstance(left, dict) and isinstance(right, dict):
        if parts and parts[0] == EVENTS and len(parts) == 2:
            aligned = _token({k: left[k] for k in STATIONS if k in left}) == _token(
                {k: right[k] for k in STATIONS if k in right})
        for field in sorted(left.keys() | right.keys()):
            _walk(key, (*parts, field), left.get(field, MISSING), right.get(field, MISSING), evidence, source_id, aligned)
    elif isinstance(left, list) and isinstance(right, list):
        array_name = EVENTS if source_id in TARGETS else "odpt:stationTimetableObject"
        if parts == (array_name,) and Counter(_token(v) for v in left) == Counter(_token(v) for v in right):
            kind = "stop-order-changed" if source_id in TARGETS else "event-order-changed"
            evidence.change(key, parts, kind, left, right)
            return
        if parts == ("odpt:stationOrder",):
            evidence.change(key, parts, "station-order-changed", left, right)
        if parts == (array_name,) and source_id in TARGETS:
            station = lambda e: _token({k: e[k] for k in STATIONS if k in e})
            if ([station(e) for e in left] != [station(e) for e in right]
                    and Counter(station(e) for e in left) == Counter(station(e) for e in right)):
                evidence.change(key, parts, "stop-order-changed", left, right)
        for i in range(max(len(left), len(right))):
            _walk(key, (*parts, i), left[i] if i < len(left) else MISSING,
                  right[i] if i < len(right) else MISSING, evidence, source_id)
    else:
        kind = _kind(parts, source_id, left, right)
        if kind == "time-changed" and not aligned:
            kind = "event-position-changed"
        evidence.change(key, parts, kind, left, right)


def _compare_raw(source_id: str, left_raw: bytes, right_raw: bytes) -> dict[str, Any]:
    left_rows, left = _parse(left_raw, source_id)
    right_rows, right = _parse(right_raw, source_id)
    result = _empty(source_id)
    evidence = _Evidence(result)
    opaque = 0
    for role, rows in (("baseline", left), ("candidate", right)):
        for key, row in sorted(rows.items()):
            for path in _unknown(row, source_id):
                evidence.add("unknownFields", {"side": role, "recordKey": key, "fieldPath": _pointer(path)})
            opaque += _opaque_count(row, source_id)
            if row["@context"] != JSONLD_CONTEXTS.get(source_id, CONTEXT):
                evidence.add("warnings", {"side": role, "recordKey": key, "code": "context-unrecognized"})
    unknown = any(_unknown(row, source_id) for row in [*left.values(), *right.values()])
    removed, added = sorted(left.keys() - right.keys()), sorted(right.keys() - left.keys())
    result["counts"].update(added=len(added), removed=len(removed))
    for key in removed:
        evidence.change(key, (), "record-removed", left[key], MISSING)
    for key in added:
        evidence.change(key, (), "record-added", MISSING, right[key])
    for key in sorted(left.keys() & right.keys()):
        before = result["counts"]["changes"]
        _walk(key, (), left[key], right[key], evidence, source_id)
        if before != result["counts"]["changes"]:
            result["counts"]["modified"] += 1
        identity_fields = (("odpt:train", "odpt:trainNumber", "odpt:railway", "odpt:railDirection", "odpt:calendar")
                           if source_id in TARGETS else ("odpt:station", "odpt:railway", "odpt:railDirection", "odpt:calendar"))
        if any(left[key].get(f, MISSING) != right[key].get(f, MISSING) for f in identity_fields):
            evidence.add("warnings", {"recordKey": key, "code": "suspected-identifier-reuse"})
        if left[key]["@context"] != right[key]["@context"]:
            evidence.add("warnings", {"recordKey": key, "code": "context-change-unresolved"})
    old_at_ids = {row["@id"]: row for row in left.values()}
    for key, row in sorted(right.items()):
        old = old_at_ids.get(row["@id"])
        if old is not None and old["owl:sameAs"] != key and _token(
                {k: v for k, v in old.items() if k not in IDS}) != _token(
                {k: v for k, v in row.items() if k not in IDS}):
            evidence.add("warnings", {"recordKey": key, "code": "suspected-identifier-reuse",
                                      "fieldPath": "/@id"})
    # Indexed, bidirectional candidate groups avoid quadratic fuzzy matching.
    groups: dict[Any, dict[str, list[str]]] = defaultdict(lambda: {"baseline": [], "candidate": []})
    for role, keys, rows in (("baseline", removed, left), ("candidate", added, right)):
        for key in keys:
            if not _unknown(rows[key], source_id):
                signature = _token({k: v for k, v in rows[key].items() if k not in IDS})
                groups[signature][role].append(key)
    for group in groups.values():
        if group["baseline"] and group["candidate"]:
            unique = len(group["baseline"]) == len(group["candidate"]) == 1
            # One entry per candidate, never an unbounded cross-product/list.
            for role in ("baseline", "candidate"):
                for key in group[role]:
                    evidence.add("ambiguities", {"side": role, "recordKey": key,
                        "code": "possible-identifier-change" if unique else "multiple-identifier-candidates",
                        "baselineCandidateCount": len(group["baseline"]),
                        "candidateCandidateCount": len(group["candidate"])})
            evidence.categories["possible-identifier-change" if unique else "ambiguous-identifier-change"] += 1
    changed = result["counts"]["changes"] > 0
    if not changed and left_raw != right_raw:
        same_order = [r["owl:sameAs"] for r in left_rows] == [r["owl:sameAs"] for r in right_rows]
        evidence.categories["json-format-only" if same_order else "record-order-only"] += 1
    elif set(left) == set(right) and [r["owl:sameAs"] for r in left_rows] != [r["owl:sameAs"] for r in right_rows]:
        evidence.categories["record-order-changed"] += 1
    dynamic_extension = source_id in NEW_TARGETS and "station-timetable" in source_id
    if dynamic_extension and opaque:
        evidence.categories["opaque-extension-present"] += opaque
        result["errorCodes"].append("opaque_extension_uninterpreted")
    partial = unknown or result["truncated"] or bool(result["warnings"] or result["ambiguities"]) or dynamic_extension and opaque > 0
    result.update(coverage="partial" if partial else "complete",
                  comparisonStatus="partial" if partial else "complete",
                  semanticStatus="indeterminate" if partial else "changed" if changed else "equivalent",
                  categories=sorted(evidence.categories), categoryCounts=dict(sorted(evidence.categories.items())))
    if result["truncated"]:
        result["errorCodes"].append("detail_limit_reached")
    if unknown:
        result["errorCodes"].append("unknown_fields_present")
    return result


def compare_train_timetables(baseline_store: Path, candidate_store: Path,
                             baseline_source_dir: Path, candidate_source_dir: Path) -> dict[str, Any]:
    """Verify all seven originals on both sides; compare only the two train sources."""
    try:
        basic = compare_stores(baseline_store, candidate_store)
        loaded = {"baseline": load_store_contract(baseline_store), "candidate": load_store_contract(candidate_store)}
    except (SourceDiffError, StoreError) as exc:
        _fail(exc.code)
    for role in ("baseline", "candidate"):
        for field in ("snapshotId", "contentFingerprint"):
            basic_key = role + field[0].upper() + field[1:]
            if loaded[role]["snapshot"][field] != basic[basic_key]:
                _fail("store_changed_during_comparison")
    results = {sid: _empty(sid) for sid in sorted(SOURCE_IDS)}
    roots = {}
    verified = {}
    raw_targets = {}
    parsed_sources = {"baseline": {}, "candidate": {}}
    input_errors = []
    parse_errors = {}
    for role, directory in (("baseline", baseline_source_dir), ("candidate", candidate_source_dir)):
        try:
            roots[role] = _root(directory)
        except SemanticDiffError as exc:
            for sid in sorted(SOURCE_IDS):
                results[sid]["inputBytesStatus"][role] = "unavailable"
                input_errors.append({"side": role, "sourceId": sid, "code": exc.code})
            continue
        for record in loaded[role]["records"]:
            sid = record["sourceId"]
            try:
                raw, identity = _read_bytes(roots[role] / SOURCE_FILES[sid])
                signature = _signature(raw)
                if signature != (record["artifact"]["sha256"], record["artifact"]["sizeBytes"]):
                    _fail("source_bytes_mismatch")
                verified[role, sid] = (signature, identity)
                results[sid]["inputBytesStatus"][role] = "verified"
                if sid in SEMANTIC_TARGETS:
                    raw_targets[role, sid] = raw
                if sid in SEMANTIC_TARGETS:
                    parsed_sources[role][sid] = _parse(raw, sid)[1]
            except SemanticDiffError as exc:
                if (role, sid) in verified:
                    parse_errors[role, sid] = exc.code
                else:
                    results[sid]["inputBytesStatus"][role] = "mismatch" if exc.code == "source_bytes_mismatch" else "unavailable"
                input_errors.append({"side": role, "sourceId": sid, "code": exc.code})
    for sid in sorted(SEMANTIC_TARGETS):
        statuses = results[sid]["inputBytesStatus"]
        parse_codes = sorted({parse_errors[role, sid] for role in ("baseline", "candidate") if (role, sid) in parse_errors})
        if parse_codes:
            results[sid]["errorCodes"].extend(parse_codes)
            results[sid].update(coverage="partial", comparisonStatus="failed")
        elif all(statuses.get(role) == "verified" for role in ("baseline", "candidate")):
            try:
                results[sid] = _compare_raw(sid, raw_targets["baseline", sid], raw_targets["candidate", sid])
            except SemanticDiffError as exc:
                results[sid]["errorCodes"].append(exc.code)
                results[sid].update(coverage="partial", comparisonStatus="failed")
        else:
            results[sid].update(coverage="partial", comparisonStatus="failed")
        results[sid]["inputBytesStatus"] = statuses
    reference_checks = []
    for role in ("baseline", "candidate"):
        catalog = parsed_sources[role]
        railway_ids = set(catalog.get("metro.railway", {}))
        station_ids = set(catalog.get("metro.station", {}))
        train_ids = Counter()
        for sid in TARGETS & catalog.keys():
            for item in catalog[sid].values():
                train_ids[item["odpt:train"], item["odpt:calendar"]] += 1
        def reference(source_id, target_id, field, value):
            if value in catalog.get(target_id, {}):
                return "resolved"
            # Cross-operator IDs are explicitly external; unresolved Metro IDs
            # in the supplied catalog are an internal reference failure.
            if value.startswith("odpt.") and ":TokyoMetro." in value:
                return "unresolved-internal"
            return "external"
        checks = Counter()
        for row in catalog.get("metro.railway", {}).values():
            for event in row.get("odpt:stationOrder", []):
                checks[reference("metro.railway", "metro.station", "odpt:station", event["odpt:station"])] += 1
        for row in catalog.get("metro.station", {}).values():
            checks[reference("metro.station", "metro.railway", "odpt:railway", row["odpt:railway"])] += 1
            for field, target in (("odpt:connectingStation", "metro.station"), ("odpt:connectingRailway", "metro.railway")):
                for value in row.get(field, []):
                    checks[reference("metro.station", target, field, value)] += 1
        for sid in ("metro.station-timetable.yurakucho", "metro.station-timetable.fukutoshin"):
            for row in catalog.get(sid, {}).values():
                checks[reference(sid, "metro.station", "odpt:station", row["odpt:station"])] += 1
                checks[reference(sid, "metro.railway", "odpt:railway", row["odpt:railway"])] += 1
                for event in row.get("odpt:stationTimetableObject", []):
                    if "odpt:train" in event:
                        train_ref = event["odpt:train"]
                        count = train_ids[train_ref, row["odpt:calendar"]]
                        if count == 1:
                            checks["resolved"] += 1
                        elif count > 1:
                            checks["ambiguous-internal"] += 1
                        elif train_ref.startswith("odpt.") and ":TokyoMetro." in train_ref:
                            checks["unresolved-internal"] += 1
                        else:
                            checks["external"] += 1
        for status, count in sorted(checks.items()):
            reference_checks.append({"side": role, "status": status, "count": count})
        if checks["unresolved-internal"]:
            for sid in sorted(SEMANTIC_TARGETS):
                if sid in catalog:
                    results[sid]["errorCodes"].append("internal_reference_unresolved")
                    results[sid]["comparisonStatus"] = "failed"
    # Re-read all original bytes and complete records after comparison. No parsed
    # result survives as equivalent if its evidence changed during the run.
    for (role, sid), expected in sorted(verified.items()):
        try:
            _root(roots[role])
            raw, identity = _read_bytes(roots[role] / SOURCE_FILES[sid])
            if (_signature(raw), identity) != expected:
                _fail("source_changed_during_comparison")
        except SemanticDiffError as exc:
            input_errors.append({"side": role, "sourceId": sid, "code": exc.code})
            results[sid]["inputBytesStatus"][role] = "unavailable"
            if sid in TARGETS:
                results[sid].update(coverage="partial", comparisonStatus="failed", semanticStatus="indeterminate")
    try:
        if (loaded["baseline"] != load_store_contract(baseline_store)
                or loaded["candidate"] != load_store_contract(candidate_store)):
            _fail("store_changed_during_comparison")
    except StoreError:
        _fail("store_changed_during_comparison")
    failed = bool(input_errors) or any(results[sid]["comparisonStatus"] == "failed" for sid in SEMANTIC_TARGETS)
    return {"contract": "odpt-semantic-diff", "schemaVersion": 1, "profile": dict(PROFILE),
            **{key: basic[key] for key in ("baselineSnapshotId", "candidateSnapshotId",
                "baselineContentFingerprint", "candidateContentFingerprint")},
            "basicDiff": basic, "comparisonStatus": "failed" if failed else "partial",
            "semanticStatus": "indeterminate",  # GTFS is deliberately not evaluated
            "sourceResults": [results[sid] for sid in sorted(SOURCE_IDS)],
            "inputErrors": input_errors, "referenceChecks": reference_checks,
            "notEvaluated": ["metro.gtfs", "itinerary-quality", "freshness",
                             "publication-eligibility", "cross-source-semantic-consistency"]}
