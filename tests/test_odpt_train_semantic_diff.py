"""All source bytes and stores in this suite are synthetic temporary fixtures."""
import copy
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import odpt_source_contract as contract
from scripts import odpt_source_inventory as inventory
from scripts import odpt_source_store as store
from scripts import odpt_train_semantic_diff as semantic
from tests.test_odpt_source_store import synthetic_gtfs

Y = "metro.train-timetable.yurakucho"
F = "metro.train-timetable.fukutoshin"


def record(number="1", line="Yurakucho"):
    return {"@context": semantic.CONTEXT, "@type": "odpt:TrainTimetable",
            "@id": f"urn:fixture:{line}:{number}", "owl:sameAs": f"urn:timetable:{line}:{number}",
            "dc:date": "2026-10-08T00:00:00+09:00", "dct:issued": "2026-10-07",
            "odpt:train": f"urn:train:{number}", "odpt:trainNumber": number,
            "odpt:railway": f"odpt.Railway:TokyoMetro.{line}",
            "odpt:railDirection": "urn:direction:north", "odpt:calendar": "urn:calendar:weekday",
            "odpt:operator": "urn:operator:fixture", "odpt:trainType": "urn:type:local",
            "odpt:originStation": ["urn:station:one"], "odpt:destinationStation": ["urn:station:three"],
            "odpt:trainTimetableObject": [
                {"odpt:departureStation": "urn:station:one", "odpt:departureTime": "06:00"},
                {"odpt:departureStation": "urn:station:two", "odpt:departureTime": "06:02"},
                {"odpt:arrivalStation": "urn:station:three", "odpt:arrivalTime": "06:04"}]}


class TrainSemanticDiffTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir="/private/tmp")
        self.root = Path(self.temp.name)
        self.serial = 0
        self.rows = [record("1"), record("2")]
        self.a = self.make_store(self.rows)

    def tearDown(self):
        self.temp.cleanup()

    def make_store(self, rows, *, raw=None, pretty=False, f_rows=None):
        self.serial += 1
        source_dir = self.root / f"raw-{self.serial}"
        destination = self.root / f"store-{self.serial}"
        source_dir.mkdir(mode=0o700)
        destination.mkdir(mode=0o700)
        (destination / "sources").mkdir(mode=0o700)
        records = []
        for sid, filename in contract.SOURCE_FILES.items():
            values = rows if sid == Y else f_rows if f_rows is not None and sid == F else [record("1", "Fukutoshin")] if sid == F else []
            data = raw if sid == Y and raw is not None else json.dumps(
                values, indent=2 if pretty else None, sort_keys=pretty).encode()
            if sid == "metro.gtfs":
                data = synthetic_gtfs()
                metadata = {"status": "parsed", "gtfs": {"feedVersion": "fixture", "validFrom": "2026-01-01", "validThrough": "2026-12-31"}, "odpt": None}
            else:
                metadata = {"status": "parsed", "gtfs": None, "odpt": {
                    "recordCount": len(values), "dcDates": [], "issuedDates": [],
                    "dcDateMissingCount": len(values), "issuedMissingCount": len(values)}}
            (source_dir / filename).write_bytes(data)
            row = inventory._record(sid, f"raw/{filename}", data, metadata, "2026-11-04T00:00:00Z")
            records.append(row)
            self.write_json(destination / "sources" / f"{sid}.json", row)
        self.write_json(destination / "snapshot.json", store.create_snapshot(records, "2026-11-04T00:00:00Z"))
        return destination, source_dir

    @staticmethod
    def write_json(path, value):
        path.write_text(json.dumps(value), encoding="utf-8")
        os.chmod(path, 0o600)

    def compare(self, b=None):
        b = b or self.make_store(self.rows)
        return semantic.compare_train_timetables(self.a[0], b[0], self.a[1], b[1])

    @staticmethod
    def target(result, sid=Y):
        return next(r for r in result["sourceResults"] if r["sourceId"] == sid)

    def changed(self, mutate):
        rows = copy.deepcopy(self.rows)
        mutate(rows)
        return self.target(self.compare(self.make_store(rows)))

    def test_same_content_distinct_snapshot_and_fixed_seven_partial_overall(self):
        result = self.compare()
        self.assertNotEqual(result["baselineSnapshotId"], result["candidateSnapshotId"])
        self.assertEqual(result["profile"], semantic.PROFILE)
        self.assertEqual(result["semanticStatus"], "indeterminate")
        self.assertEqual(result["comparisonStatus"], "partial")
        self.assertEqual(len(result["sourceResults"]), 7)
        for row in result["sourceResults"]:
            self.assertEqual(set(row["inputBytesStatus"].values()), {"verified"})
            self.assertEqual(row["coverage"], "complete" if row["sourceId"] in semantic.TARGETS else "not-evaluated")
        self.assertEqual(self.target(result)["semanticStatus"], "equivalent")
        self.assertEqual(self.target(result, F)["semanticStatus"], "equivalent")

    def test_format_object_keys_and_record_order(self):
        pretty = self.target(self.compare(self.make_store(self.rows, pretty=True)))
        self.assertEqual(pretty["categories"], ["json-format-only"])
        reversed_rows = self.target(self.compare(self.make_store(list(reversed(self.rows)))))
        self.assertEqual(reversed_rows["categories"], ["record-order-only"])
        self.assertEqual(reversed_rows["semanticStatus"], "equivalent")

    def test_add_remove_and_time_delta_paths(self):
        result = self.changed(lambda rows: rows.append(record("3")))
        self.assertEqual(result["counts"]["added"], 1)
        result = self.changed(lambda rows: rows.pop())
        self.assertEqual(result["counts"]["removed"], 1)
        result = self.changed(lambda rows: rows[0][semantic.EVENTS][0].update({"odpt:departureTime": "06:01"}))
        time_change = next(r for r in result["changes"] if r["kind"] == "time-changed")
        self.assertEqual(time_change["deltaSeconds"], 60)
        self.assertEqual(time_change["fieldPath"], "/odpt:trainTimetableObject/0/odpt:departureTime")
        self.assertEqual(result["counts"]["modified"], 1)

    def test_type_destination_station_and_event_order(self):
        cases = [
            (lambda rows: rows[0].update({"odpt:trainType": "urn:type:express"}), "train-type-changed"),
            (lambda rows: rows[0].update({"odpt:destinationStation": ["urn:station:four"]}), "destination-changed"),
            (lambda rows: rows[0][semantic.EVENTS][0].update({"odpt:departureStation": "urn:station:four"}), "stop-station-changed"),
            (lambda rows: rows[0][semantic.EVENTS].reverse(), "stop-order-changed")]
        for mutate, kind in cases:
            with self.subTest(kind=kind):
                result = self.changed(mutate)
                self.assertIn(kind, result["categories"])
                if kind == "stop-order-changed":
                    self.assertNotIn("time-changed", result["categories"])

    def test_metadata_at_id_and_auxiliary_fields(self):
        result = self.changed(lambda rows: rows[0].update({"dc:date": "2026-10-09"}))
        self.assertEqual(result["categories"], ["metadata-changed"])
        result = self.changed(lambda rows: rows[0].update({"@id": "urn:replacement"}))
        self.assertIn("identifier-changed", result["categories"])
        result = self.changed(lambda rows: rows[0].update({"odpt:operator": "urn:other"}))
        self.assertIn("reference-changed", result["categories"])

    def test_reordered_and_edited_events_do_not_invent_time_deltas_between_stations(self):
        def mutate(rows):
            events = rows[0][semantic.EVENTS]
            events[0], events[1] = events[1], events[0]
            events[0]["odpt:departureTime"] = "06:03"
        result = self.changed(mutate)
        self.assertIn("stop-order-changed", result["categories"])
        self.assertIn("event-position-changed", result["categories"])
        self.assertNotIn("time-changed", result["categories"])

    def test_strict_json_and_identifier_validation(self):
        invalid = [(b"{bad", "json_invalid"), (b"[NaN]", "json_constant_invalid"),
                   (b'[{"a":1,"a":2}]', "json_duplicate_key"), (b"{}", "json_structure_invalid")]
        for raw, code in invalid:
            with self.subTest(code=code):
                row = self.target(self.compare(self.make_store(self.rows, raw=raw)))
                self.assertIn(code, row["errorCodes"])
                self.assertEqual(row["comparisonStatus"], "failed")
        cases = [
            (lambda r: r[1].update({"owl:sameAs": r[0]["owl:sameAs"]}), "same_as_duplicate"),
            (lambda r: r[0].pop("owl:sameAs"), "record_identifier_or_reference_type_invalid"),
            (lambda r: r[1].update({"@id": r[0]["@id"]}), "at_id_duplicate"),
            (lambda r: r[0].update({"odpt:calendar": 0}), "record_identifier_or_reference_type_invalid"),
            (lambda r: r[0].update({semantic.EVENTS: {}}), "event_array_invalid"),
            (lambda r: r[0][semantic.EVENTS][0].update({"odpt:departureTime": False}), "event_time_invalid")]
        for mutate, code in cases:
            with self.subTest(code=code):
                self.assertIn(code, self.changed(mutate)["errorCodes"])

    def test_unknown_fields_are_preserved_type_sensitive_and_partial(self):
        for value in (None, "", False, 0, {"nested": [1, 2]}):
            with self.subTest(value=value):
                result = self.changed(lambda rows: rows[0].update({"extension": value}))
                self.assertEqual(result["coverage"], "partial")
                self.assertIn("unknown-field-changed", result["categories"])
                self.assertEqual(result["unknownFields"][0]["fieldPath"], "/extension")
        left = copy.deepcopy(self.rows)
        left[0]["extension"] = False
        self.a = self.make_store(left)
        left[0]["extension"] = 0
        result = self.target(self.compare(self.make_store(left)))
        self.assertIn("unknown-field-changed", result["categories"])
        left[0][semantic.EVENTS][0]["new-event-field"] = "value"
        result = self.target(self.compare(self.make_store(left)))
        self.assertTrue(any("new-event-field" in r["fieldPath"] for r in result["unknownFields"]))

    def test_missing_null_empty_metadata_and_time_are_not_merged(self):
        left = copy.deepcopy(self.rows)
        left[0].pop("dct:issued")
        self.a = self.make_store(left)
        for value in (None, ""):
            right = copy.deepcopy(left)
            right[0]["dct:issued"] = value
            result = self.target(self.compare(self.make_store(right)))
            self.assertIn("metadata-changed", result["categories"])
        left[0][semantic.EVENTS][0].pop("odpt:departureTime")
        self.a = self.make_store(left)
        left[0][semantic.EVENTS][0]["odpt:departureTime"] = None
        self.assertIn("time-changed", self.target(self.compare(self.make_store(left)))["categories"])

    def test_twenty_four_hour_time_is_not_reduced_modulo_day(self):
        result = self.changed(lambda rows: rows[0][semantic.EVENTS][0].update({"odpt:departureTime": "30:00"}))
        self.assertEqual(next(r["deltaSeconds"] for r in result["changes"] if r["kind"] == "time-changed"), 86400)
        result = self.changed(lambda rows: rows[0][semantic.EVENTS][0].update({"odpt:departureTime": "06:00:00"}))
        self.assertEqual(result["semanticStatus"], "equivalent")

    def test_identifier_candidates_never_merge_add_remove_and_detect_ambiguity(self):
        result = self.changed(lambda rows: rows[0].update({"owl:sameAs": "urn:new", "@id": "urn:new-id"}))
        self.assertEqual((result["counts"]["added"], result["counts"]["removed"]), (1, 1))
        self.assertIn("possible-identifier-change", result["categories"])
        self.assertEqual(result["semanticStatus"], "indeterminate")
        rows = [record("1")]
        self.a = self.make_store(rows)
        replacement = copy.deepcopy(rows[0])
        replacement.update({"owl:sameAs": "urn:new-a", "@id": "urn:id-a"})
        second = copy.deepcopy(replacement)
        second.update({"owl:sameAs": "urn:new-b", "@id": "urn:id-b"})
        result = self.target(self.compare(self.make_store([replacement, second])))
        self.assertIn("ambiguous-identifier-change", result["categories"])

    def test_same_identifier_with_calendar_change_warns_of_reuse(self):
        result = self.changed(lambda rows: rows[0].update({"odpt:calendar": "urn:calendar:holiday"}))
        self.assertIn("suspected-identifier-reuse", [r["code"] for r in result["warnings"]])
        self.assertEqual(result["semanticStatus"], "indeterminate")
        result = self.changed(lambda rows: rows[0].update({"owl:sameAs": "urn:new", "odpt:calendar": "urn:calendar:new"}))
        self.assertIn("suspected-identifier-reuse", [r["code"] for r in result["warnings"]])

    def test_missing_mismatched_and_symlink_sources(self):
        for mode in ("missing", "mismatch", "symlink"):
            b = self.make_store(self.rows)
            path = b[1] / contract.SOURCE_FILES[Y]
            if mode == "missing":
                path.unlink()
            elif mode == "mismatch":
                path.write_bytes(path.read_bytes() + b" ")
            else:
                path.unlink()
                path.symlink_to(self.a[1] / contract.SOURCE_FILES[Y])
            result = self.compare(b)
            self.assertEqual(result["comparisonStatus"], "failed")
            self.assertEqual(self.target(result)["semanticStatus"], "indeterminate")
            self.assertTrue(result["inputErrors"])
        # Non-target originals must also be checked, without semantic parsing.
        b = self.make_store(self.rows)
        (b[1] / contract.SOURCE_FILES["metro.station"]).unlink()
        self.assertEqual(self.compare(b)["comparisonStatus"], "failed")

    def test_source_changes_during_read_and_during_comparison(self):
        path = self.a[1] / contract.SOURCE_FILES[Y]
        real_fstat = semantic.os.fstat
        def mutate(fd):
            info = real_fstat(fd)
            path.write_bytes(path.read_bytes() + b" ")
            return info
        with patch.object(semantic.os, "fstat", side_effect=mutate):
            with self.assertRaises(semantic.SemanticDiffError) as raised:
                semantic._read_bytes(path)
        self.assertEqual(raised.exception.code, "source_changed_while_reading")
        self.a = self.make_store(self.rows)
        b = self.make_store(self.rows)
        original = semantic._compare_raw
        def during(*args):
            result = original(*args)
            p = self.a[1] / contract.SOURCE_FILES[Y]
            p.write_bytes(p.read_bytes() + b" ")
            return result
        with patch.object(semantic, "_compare_raw", side_effect=during):
            result = self.compare(b)
        self.assertEqual(self.target(result)["semanticStatus"], "indeterminate")
        self.assertIn("source_changed_during_comparison", [e["code"] for e in result["inputErrors"]])

    def test_invalid_store_fingerprint_and_store_mutation(self):
        b = self.make_store(self.rows)
        path = b[0] / "snapshot.json"
        snapshot = json.loads(path.read_text())
        snapshot["contentFingerprint"] = "0" * 64
        self.write_json(path, snapshot)
        with self.assertRaises(semantic.SemanticDiffError) as raised:
            self.compare(b)
        self.assertIn("fingerprint", raised.exception.code)
        with self.assertRaises(semantic.SemanticDiffError):
            semantic.compare_train_timetables(self.root / "absent", self.a[0], self.a[1], self.a[1])
        b = self.make_store(self.rows)
        original = semantic._compare_raw
        def mutate_store(*args):
            result = original(*args)
            record_path = b[0] / "sources" / f"{Y}.json"
            value = json.loads(record_path.read_text())
            value["unknownReasons"].append("synthetic-change")
            self.write_json(record_path, value)
            return result
        with patch.object(semantic, "_compare_raw", side_effect=mutate_store):
            with self.assertRaises(semantic.SemanticDiffError) as raised:
                self.compare(b)
        self.assertEqual(raised.exception.code, "store_changed_during_comparison")

    def test_detail_limit_is_bounded_counts_are_exact_and_results_deterministic(self):
        rows = copy.deepcopy(self.rows)
        for row in rows:
            for event in row[semantic.EVENTS]:
                event["odpt:arrivalTime" if "odpt:arrivalStation" in event else "odpt:departureTime"] = "07:00"
        b = self.make_store(rows)
        with patch.object(semantic, "MAX_DETAILS", 2):
            first = self.compare(b)
            second = self.compare(b)
        self.assertEqual(first, second)
        result = self.target(first)
        self.assertTrue(result["truncated"])
        self.assertEqual(len(result["changes"]), 2)
        self.assertEqual(result["counts"]["changes"], 6)
        self.assertIn("detail_limit_reached", result["errorCodes"])
        self.assertEqual(result["semanticStatus"], "indeterminate")

    def test_input_structural_limits(self):
        with patch.object(semantic, "MAX_RECORDS", 1):
            self.assertIn("record_limit_exceeded", self.target(self.compare())["errorCodes"])
        with patch.object(semantic, "MAX_EVENTS", 1):
            self.assertIn("event_limit_exceeded", self.target(self.compare())["errorCodes"])
        rows = copy.deepcopy(self.rows)
        rows[0]["unknown"] = [[[[[1]]]]]
        with patch.object(semantic, "MAX_DEPTH", 3):
            self.assertIn("json_depth_limit_exceeded", self.target(self.compare(self.make_store(rows)))["errorCodes"])

    def test_cli_exit_codes_summary_and_no_source_body(self):
        command = [sys.executable, "-B", "scripts/odpt_source_inventory.py", "compare-semantic",
                   "--baseline-store", str(self.a[0]), "--candidate-store", str(self.a[0]),
                   "--baseline-source-dir", str(self.a[1]), "--candidate-source-dir", str(self.a[1])]
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("coverage=not-evaluated", result.stdout)
        self.assertNotIn("urn:station", result.stdout)
        self.assertNotIn("Traceback", result.stderr)
        rows = copy.deepcopy(self.rows)
        rows[0]["odpt:trainType"] = "urn:type:express"
        b = self.make_store(rows)
        changed_command = command.copy()
        changed_command[changed_command.index("--candidate-store") + 1] = str(b[0])
        changed_command[changed_command.index("--candidate-source-dir") + 1] = str(b[1])
        changed = subprocess.run(changed_command, capture_output=True, text=True)
        self.assertEqual(changed.returncode, 0)
        self.assertIn("train-type-changed", changed.stdout)
        (self.a[1] / contract.SOURCE_FILES[Y]).unlink()
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("error=source_unavailable", result.stdout)

    def test_success_and_failure_do_not_write_originals_or_stores(self):
        b = self.make_store(self.rows)
        paths = [p for root in (*self.a, *b) for p in root.rglob("*") if p.is_file()]
        signature = lambda: {str(p): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns, p.stat().st_mode) for p in paths}
        before = signature()
        self.compare(b)
        self.assertEqual(before, signature())
        with patch.object(semantic, "MAX_RECORDS", 0):
            self.compare(b)
        self.assertEqual(before, signature())


if __name__ == "__main__":
    unittest.main()
