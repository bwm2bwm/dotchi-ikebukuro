#!/usr/bin/env python3
"""Offline quality audit for the saved ODPT/GTFS snapshot.

This tool is local-only. It reads the seven existing source files, reuses the
offline ItineraryGenerator, and emits aggregate reports without journey rows.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import stat
import sys
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from odpt_itinerary import DESTINATIONS, FeedDateError, ItineraryGenerator, to_dict

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SNAPSHOT = ROOT / "local_data" / "odpt"
DEFAULT_OUTPUT = Path.home() / "Library" / "Application Support" / "dotchi-ikebukuro-odpt-qa"
REQUIRED_JSON = (
    "Railway_all.json", "Station_all.json",
    "TrainTimetable_Yurakucho.json", "TrainTimetable_Fukutoshin.json",
    "StationTimetable_Yurakucho.json", "StationTimetable_Fukutoshin.json",
)
GTFS_NAME = "TokyoMetro-Train-GTFS.zip"
GTFS_MEMBERS = ("feed_info.txt", "calendar.txt", "calendar_dates.txt", "stops.txt",
                "routes.txt", "trips.txt", "stop_times.txt")


class QAError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _sha256_file(path: Path) -> tuple[str, int, int]:
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or path.is_symlink():
        raise QAError("source_not_regular_file")
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
            size += len(block)
    after = path.lstat()
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino) or size != after.st_size:
        raise QAError("source_changed_while_reading")
    return digest.hexdigest(), size, after.st_mtime_ns


def _fingerprint(entries: list[dict[str, Any]]) -> str:
    content = json.dumps(entries, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(content).hexdigest()


def _inventory(snapshot: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    expected = (*REQUIRED_JSON, GTFS_NAME)
    entries: list[dict[str, Any]] = []
    metadata: dict[str, Any] = {"json": {}, "gtfs": {}}
    for name in expected:
        path = snapshot / name
        if not path.exists():
            raise QAError("required_file_missing")
        digest, size, mtime_ns = _sha256_file(path)
        entries.append({"path": name, "sizeBytes": size, "sha256": digest})
        metadata["files"] = metadata.get("files", 0) + 1
        metadata.setdefault("observedFilesystemMtimeUtc", {})[name] = datetime.fromtimestamp(
            mtime_ns / 1_000_000_000, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    for name in REQUIRED_JSON:
        path = snapshot / name
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, OSError):
            raise QAError("json_invalid") from None
        if not isinstance(data, list) or any(not isinstance(record, dict) for record in data):
            raise QAError("json_structure_invalid")
        issued = sorted({str(row.get("dct:issued")) for row in data if row.get("dct:issued") is not None})
        source_dates = sorted({str(row.get("dc:date")) for row in data if row.get("dc:date") is not None})
        metadata["json"][name] = {"recordCount": len(data), "sourceIssuedDates": issued,
                                   "sourceDates": source_dates}
    gtfs_path = snapshot / GTFS_NAME
    try:
        with zipfile.ZipFile(gtfs_path) as archive:
            members = set(archive.namelist())
            bad_member = archive.testzip()
            if bad_member or not set(GTFS_MEMBERS).issubset(members):
                raise QAError("gtfs_structure_invalid")
            info_rows = list(__import__("csv").DictReader(archive.read("feed_info.txt").decode("utf-8-sig").splitlines()))
            if len(info_rows) != 1:
                raise QAError("gtfs_feed_info_invalid")
            info = info_rows[0]
            version = info.get("feed_version")
            start = info.get("feed_start_date")
            end = info.get("feed_end_date")
            if not version or not start or not end:
                raise QAError("gtfs_feed_info_invalid")
            start_date = date.fromisoformat(f"{start[:4]}-{start[4:6]}-{start[6:8]}")
            end_date = date.fromisoformat(f"{end[:4]}-{end[4:6]}-{end[6:8]}")
            if end_date < start_date:
                raise QAError("gtfs_feed_info_invalid")
            metadata["gtfs"] = {"feedVersion": version, "validFrom": start_date.isoformat(),
                                 "validThrough": end_date.isoformat(), "requiredMemberCount": len(GTFS_MEMBERS)}
    except QAError:
        raise
    except (OSError, zipfile.BadZipFile, KeyError, UnicodeDecodeError, ValueError):
        raise QAError("gtfs_zip_invalid") from None
    return entries, metadata


def _generator_fingerprint() -> str:
    files = [Path(__file__), Path(__import__("odpt_itinerary").__file__),
             Path(__import__("odpt_stop_patterns").__file__)]
    digests = [{"name": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for path in files]
    return _fingerprint(digests)


def _journey_metrics(results: list[Any]) -> dict[str, Any]:
    direct = transfer = 0
    routes: collections.Counter[str] = collections.Counter()
    odpt: collections.Counter[str] = collections.Counter()
    quality: collections.Counter[str] = collections.Counter()
    over_24h = 0
    for result in results:
        itinerary = result.primary_itinerary
        if itinerary is not None:
            if itinerary.kind == "direct":
                direct += 1
            elif itinerary.kind == "transfer":
                transfer += 1
        routes[str(result.route_id)] += 1
        odpt[result.odpt.status] += 1
        quality.update(result.data_quality)
        if result.departure_seconds >= 24 * 60 * 60:
            over_24h += 1
    return {"journeyCount": len(results), "primaryDirectCount": direct,
            "primaryTransferCount": transfer, "routeCounts": dict(sorted(routes.items())),
            "odptMatchStatusCounts": dict(sorted(odpt.items())),
            "dataQualityCodeCounts": dict(sorted(quality.items())),
            "departuresAtOrAfter24Hours": over_24h}


def _classify_diagnostics(result: Any) -> dict[str, set[str]]:
    """Classify codes by observed context, without changing itinerary generation."""
    codes = set(result.data_quality)
    info: set[str] = set()
    warning: set[str] = set()
    explicit_pass = "destination_explicit_pass" in codes
    confirmed_non_alighting = explicit_pass and "destination_alighting_prohibited" in codes
    transfer = result.best_transfer_alternative
    valid_transfer = (transfer is not None and transfer.kind == "transfer"
                      and transfer.departure_seconds is not None
                      and transfer.arrival_seconds is not None
                      and transfer.arrival_seconds >= transfer.departure_seconds)
    for code in codes:
        if code == "destination_explicit_pass":
            info.add(code)
        elif code == "destination_alighting_prohibited" and explicit_pass:
            info.add(code)
        elif code == "destination_arrival_missing" and confirmed_non_alighting:
            info.add(code)
        elif code == "direct_arrival_unavailable" and valid_transfer:
            info.add(code)
        else:
            warning.add(code)
    return {"INFO": info, "WARNING": warning}


def _diagnostic_summary(results: list[Any]) -> dict[str, Any]:
    code_occurrences = {"INFO": collections.Counter(), "WARNING": collections.Counter()}
    code_itineraries = {"INFO": collections.defaultdict(set),
                        "WARNING": collections.defaultdict(set)}
    affected_itineraries = {"INFO": set(), "WARNING": set()}
    for result in results:
        itinerary_key = result.origin_trip_id
        for severity, codes in _classify_diagnostics(result).items():
            if codes:
                affected_itineraries[severity].add(itinerary_key)
            for code in codes:
                code_occurrences[severity][code] += 1
                code_itineraries[severity][code].add(itinerary_key)
    return {
        severity: {
            "codeOccurrences": sum(code_occurrences[severity].values()),
            "affectedItineraryInstances": len(affected_itineraries[severity]),
            "codes": {
                code: {"occurrences": code_occurrences[severity][code],
                       "affectedItineraryInstances": len(code_itineraries[severity][code]),
                       "reason": _diagnostic_reason(code, severity)}
                for code in sorted(code_occurrences[severity])
            },
        }
        for severity in ("INFO", "WARNING")
    }


def _diagnostic_reason(code: str, severity: str) -> str:
    if severity == "INFO":
        return {
            "destination_explicit_pass": "GTFS explicitly marks this stop as no-alighting; the direct destination is intentionally skipped.",
            "destination_alighting_prohibited": "No-alighting is corroborated by destination_explicit_pass.",
            "destination_arrival_missing": "Arrival time is absent at a stop corroborated as an explicit no-alighting pass-through.",
            "direct_arrival_unavailable": "No direct arrival is available, but a time-valid transfer itinerary remains.",
        }.get(code, "Contextual informational condition.")
    if code == "destination_arrival_missing":
        return "Arrival time is missing without confirmed explicit pass-through and no-alighting evidence."
    if code == "direct_arrival_unavailable":
        return "Direct arrival is unavailable and no valid transfer candidate remains."
    return "Diagnostic is not covered by a confirmed informational exception; review the data or itinerary condition."


def _safe_output_path(output_dir: Path, snapshot: Path) -> Path:
    output_dir = output_dir.expanduser().resolve()
    snapshot = snapshot.resolve()
    try:
        output_dir.relative_to(ROOT)
        raise QAError("output_inside_repository")
    except ValueError:
        pass
    try:
        output_dir.relative_to(snapshot)
        raise QAError("output_inside_snapshot")
    except ValueError:
        pass
    return output_dir


def run_qa(snapshot_dir: Path, service_date: str, output_dir: Path,
           mutation_hook: Callable[[], None] | None = None) -> dict[str, Any]:
    try:
        anchor = date.fromisoformat(service_date)
    except ValueError:
        raise QAError("service_date_invalid") from None
    if anchor.isoformat() != service_date:
        raise QAError("service_date_invalid")
    snapshot = snapshot_dir.expanduser().resolve()
    output_dir = _safe_output_path(output_dir, snapshot)
    initial_entries, source_metadata = _inventory(snapshot)
    source_fingerprint = _fingerprint(initial_entries)
    if mutation_hook:
        mutation_hook()
    requested_dates = [anchor + timedelta(days=offset) for offset in (-1, 0, 1)]
    day_rows: list[dict[str, Any]] = []
    result_digests: list[dict[str, str]] = []
    for destination_id, destination in DESTINATIONS.items():
        try:
            generator = ItineraryGenerator(gtfs_zip=snapshot / GTFS_NAME, odpt_dir=snapshot,
                                           destination_station_id=destination_id)
        except Exception:
            raise QAError("itinerary_generator_input_invalid") from None
        for day in requested_dates:
            if day < generator.feed_start or day > generator.feed_end:
                day_rows.append({"stationId": destination_id, "station": destination["name"],
                                 "serviceDate": day.isoformat(), "status": "outside_feed_range",
                                 "journeyCount": 0})
                continue
            try:
                results = generator.generate(day)
            except FeedDateError:
                day_rows.append({"stationId": destination_id, "station": destination["name"],
                                 "serviceDate": day.isoformat(), "status": "requested_date_unavailable",
                                 "journeyCount": 0})
                continue
            except Exception:
                raise QAError("itinerary_generation_failed") from None
            metrics = _journey_metrics(results)
            metrics["diagnosticSeverity"] = _diagnostic_summary(results)
            destination_status = getattr(generator, "last_destination_status", {}) or {}
            status = "ok" if results else "no_candidates"
            if not results and not generator.active_service_ids(day):
                status = "no_active_service"
            day_rows.append({"stationId": destination_id, "station": destination["name"],
                             "serviceDate": day.isoformat(), "status": status,
                             "activeServiceCount": len(generator.active_service_ids(day)),
                             "destinationDataStatus": destination_status.get("status", "unknown"), **metrics})
            # The digest deliberately includes the generator's deterministic complete DTO internally;
            # no journey row or trip identifier is written to the report.
            result_payload = [to_dict(row) for row in results]
            digest = hashlib.sha256(json.dumps(result_payload, ensure_ascii=False, sort_keys=True,
                                               separators=(",", ":")).encode()).hexdigest()
            result_digests.append({"stationId": destination_id, "serviceDate": day.isoformat(),
                                   "sha256": digest})
    final_entries, _ = _inventory(snapshot)
    if initial_entries != final_entries:
        raise QAError("source_changed_during_run")
    expected_pairs = len(DESTINATIONS) * len(requested_dates)
    counts = collections.Counter(row["status"] for row in day_rows)
    failures = counts["outside_feed_range"] + counts["requested_date_unavailable"]
    missing_station_dates = max(0, expected_pairs - len(day_rows))
    warnings = sum(row.get("journeyCount", 0) == 0 for row in day_rows
                   if row["status"] in {"no_candidates", "no_active_service"})
    matched_statuses = {"matched", "unique_match"}
    unmatched = sum(sum(v for key, v in row.get("odptMatchStatusCounts", {}).items()
                        if key not in matched_statuses) for row in day_rows)
    severity_summary = {
        severity: {"codeOccurrences": 0, "affectedItineraryInstances": 0, "codes": {}}
        for severity in ("INFO", "WARNING")
    }
    for row in day_rows:
        for severity in severity_summary:
            metrics = row.get("diagnosticSeverity", {}).get(severity, {})
            target = severity_summary[severity]
            target["codeOccurrences"] += metrics.get("codeOccurrences", 0)
            target["affectedItineraryInstances"] += metrics.get("affectedItineraryInstances", 0)
            for code, counts_for_code in metrics.get("codes", {}).items():
                entry = target["codes"].setdefault(code, {"occurrences": 0, "affectedItineraryInstances": 0})
                entry["occurrences"] += counts_for_code["occurrences"]
                entry["affectedItineraryInstances"] += counts_for_code["affectedItineraryInstances"]
    fail_gate_count = failures + missing_station_dates + int(len(day_rows) > expected_pairs)
    status = ("FAIL" if fail_gate_count else
              "WARNING" if warnings or unmatched or severity_summary["WARNING"]["codeOccurrences"] else "PASS")
    severity_summary["FAIL"] = {
        "failGateCount": fail_gate_count,
        "affectedStationDates": failures + missing_station_dates,
        "reasons": {
            "outsideFeedRangeOrRequestedDateUnavailable": failures,
            "missingStationDateResults": missing_station_dates,
            "unexpectedExtraStationDateResults": int(len(day_rows) > expected_pairs),
        },
    }
    severity_reasons = {
        "INFO": "Confirmed pass-through/no-alighting exclusions; missing arrival is INFO only with both explicit-pass and no-alighting evidence; direct-unavailable is INFO only when a valid transfer remains.",
        "WARNING": "Unconfirmed/malformed destination data, invalid time/order, unresolved transfer, unmatched ODPT, or station-date with no candidates/service.",
        "FAIL": "Requested date outside feed validity, missing requested station-date result, or unexpected result cardinality. Invalid source structure or source mutation aborts before a report is emitted.",
    }
    body = {"schemaVersion": 1, "status": status, "serviceDate": anchor.isoformat(),
            "requestedServiceDates": [d.isoformat() for d in requested_dates],
            "stationCount": len(DESTINATIONS), "dayResultCount": len(day_rows),
            "sourceFingerprint": source_fingerprint, "generatorFingerprint": _generator_fingerprint(),
            "generationDigest": _fingerprint(result_digests), "source": source_metadata,
            "sourceFiles": initial_entries, "dayResults": day_rows,
            "reproducibility": {"digestAlgorithm": "sha256", "digestExcludesRunMetadata": True,
                                 "perStationDateResultDigests": result_digests},
            "summary": {"outsideFeedRangeOrMissingDates": failures, "noCandidateOrNoActiveServiceStationDates": warnings,
                        "unmatchedOdptJourneyCount": unmatched,
                        "diagnosticSeverity": severity_summary,
                        "severityDecisionReasons": severity_reasons,
                        "note": "Counts are descriptive; no minimum journey or ODPT-match threshold is imposed."},
            "rules": ["All 8 verified destinations and anchor date ±1 calendar day are evaluated.",
                      "A requested date outside GTFS feed validity is FAIL; no journey candidates are reported, not threshold-failed.",
                      "Diagnostic severity is context-based; informational pass-through codes do not raise overall status.",
                      "ODPT matching and existing itinerary rules are unchanged; unmatched statuses and unresolved diagnostics are reported as WARNING.",
                      "GTFS feed validity and ODPT source dc:date/dct:issued are independent metadata; filesystem mtime is not acquisition time.",
                      "Source SHA-256/size inventory must remain identical before and after generation."]}
    return body


def _write_report(report: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(output_dir, 0o700)
    json_path = output_dir / "odpt-snapshot-qa.json"
    text_path = output_dir / "odpt-snapshot-qa.txt"
    encoded = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    lines = ["ODPT保存済みsnapshot 非公開品質検証", f"判定: {report['status']}",
             f"基準service date: {report['serviceDate']}",
             f"検証日: {', '.join(report['requestedServiceDates'])}",
             f"駅数 / station-date結果: {report['stationCount']} / {report['dayResultCount']}",
             f"source fingerprint: {report['sourceFingerprint']}",
             f"生成結果digest: {report['generationDigest']}",
             f"GTFS: {report['source']['gtfs']['feedVersion']} ({report['source']['gtfs']['validFrom']}..{report['source']['gtfs']['validThrough']})",
             f"日付欠落/期間外: {report['summary']['outsideFeedRangeOrMissingDates']}",
             f"候補なし/active serviceなし station-date: {report['summary']['noCandidateOrNoActiveServiceStationDates']}",
             f"ODPT未照合 journey: {report['summary']['unmatchedOdptJourneyCount']}",
             *[f"{severity}: code occurrences={report['summary']['diagnosticSeverity'][severity]['codeOccurrences']}, "
               f"affected itinerary instances={report['summary']['diagnosticSeverity'][severity]['affectedItineraryInstances']}; "
               f"reason={report['summary']['severityDecisionReasons'][severity]}"
               for severity in ("INFO", "WARNING")],
             f"FAIL: gates={report['summary']['diagnosticSeverity']['FAIL']['failGateCount']}, "
             f"affected station-dates={report['summary']['diagnosticSeverity']['FAIL']['affectedStationDates']}; "
             f"reason={report['summary']['severityDecisionReasons']['FAIL']}",
             f"診断コード別件数はJSON reportを参照。1旅程の複数codeはoccurrencesとaffected itinerary instancesを分離。",
             f"過去report比較: {report['reproducibility'].get('comparison', {}).get('status', '未指定')}",
             "実行日時や旅程本文・列車IDはレポートに含めません。"]
    for path, content in ((json_path, encoded), (text_path, "\n".join(lines) + "\n")):
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise QAError("report_target_not_regular_file")
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(path, flags, 0o600)
        except OSError:
            raise QAError("report_target_not_writable") from None
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
    return json_path, text_path


def _compare_previous(report: dict[str, Any], previous_path: Path) -> dict[str, str]:
    try:
        previous = json.loads(previous_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {"status": "INVALID_PREVIOUS_REPORT"}
    keys = ("serviceDate", "sourceFingerprint", "generatorFingerprint")
    if not isinstance(previous, dict) or any(previous.get(key) != report.get(key) for key in keys):
        return {"status": "INCOMPARABLE"}
    if previous.get("generationDigest") == report.get("generationDigest"):
        return {"status": "MATCH", "previousGenerationDigest": previous["generationDigest"]}
    return {"status": "MISMATCH", "previousGenerationDigest": str(previous.get("generationDigest", ""))}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument("--service-date", default="2026-10-29", help="YYYY-MM-DD (default: 2026-10-29)")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--compare-with", type=Path,
                        help="compare against a previous QA JSON report; same inputs with a different digest fail")
    args = parser.parse_args(argv)
    try:
        report = run_qa(args.snapshot, args.service_date, args.output_dir)
        if args.compare_with:
            report["reproducibility"]["comparison"] = _compare_previous(report, args.compare_with.expanduser())
            comparison_status = report["reproducibility"]["comparison"]["status"]
            if comparison_status == "MISMATCH":
                report["status"] = "FAIL"
            elif comparison_status in {"INCOMPARABLE", "INVALID_PREVIOUS_REPORT"} and report["status"] != "FAIL":
                report["status"] = "WARNING"
        json_path, text_path = _write_report(report, args.output_dir.expanduser().resolve())
    except QAError as exc:
        print(f"FAIL: {exc.code}", file=sys.stderr)
        return 1
    print(f"{report['status']}: offline ODPT snapshot QA")
    print(f"sourceFingerprint={report['sourceFingerprint']}")
    print(f"generationDigest={report['generationDigest']}")
    print(f"report={json_path.name}, summary={text_path.name}")
    return 1 if report["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
