import io
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from scripts import odpt_source_contract as contract
from scripts import odpt_source_diff as source_diff
from scripts import odpt_source_inventory as inventory
from scripts import odpt_source_store as store


def _gtfs(version="fixture", start="20260101", end="20261231"):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for member in sorted(inventory.GTFS_MEMBERS):
            data = (f"feed_version,feed_start_date,feed_end_date\n{version},{start},{end}\n"
                    if member == "feed_info.txt" else "fixture\n")
            archive.writestr(member, data)
    return output.getvalue()


class SourceDiffTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir="/private/tmp")
        self.root = Path(self.temp.name)
        self.parent = self.root / "stores"
        self.parent.mkdir(mode=0o700)
        os.chmod(self.parent, 0o700)
        self.a_sources = self._sources("a")
        self.b_sources = self._sources("a")
        store.persist_snapshot(self.parent / "baseline", self.a_sources)
        store.persist_snapshot(self.parent / "candidate", self.b_sources)
        self.a, self.b = self.parent / "baseline", self.parent / "candidate"

    def tearDown(self):
        self.temp.cleanup()

    def _sources(self, text):
        root = self.root / f"raw-{len(list(self.root.glob('raw-*')))}"
        root.mkdir(mode=0o700)
        for source_id, filename in contract.SOURCE_FILES.items():
            raw = (_gtfs() if source_id == "metro.gtfs" else
                   json.dumps([{"@id": f"urn:{source_id}", "dc:date": f"{text}-date",
                                "dct:issued": "2026-10-07"}], separators=(",", ":")).encode())
            (root / filename).write_bytes(raw)
        return root

    def _rewrite_json(self, path, mutate):
        data = json.loads(path.read_text(encoding="utf-8"))
        mutate(data)
        path.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
        os.chmod(path, 0o600)

    def _set_record_metadata(self, store_path, source_id, mutate):
        record_path = store_path / "sources" / f"{source_id}.json"
        self._rewrite_json(record_path, mutate)

    def compare(self, a=None, b=None):
        return source_diff.compare_stores(a or self.a, b or self.b)

    def test_all_seven_identical_even_when_snapshot_ids_and_history_differ(self):
        result = self.compare()
        self.assertEqual(result["overallBasicStatus"], "identical")
        self.assertEqual(len(result["sourceDiffs"]), 7)
        self.assertNotEqual(result["baselineSnapshotId"], result["candidateSnapshotId"])
        self.assertEqual(result["baselineContentFingerprint"], result["candidateContentFingerprint"])
        self.assertEqual({row["status"] for row in result["sourceDiffs"]}, {"identical"})
        self.assertEqual(result["checks"]["originalSourceBytes"], "not-required; not-read")

    def test_hash_diff_with_same_byte_count_is_different(self):
        sid = "metro.station"
        left = self.a_sources / contract.SOURCE_FILES[sid]
        right = self.b_sources / contract.SOURCE_FILES[sid]
        original = right.read_bytes()
        right.write_bytes(original.replace(b"a-date", b"b-date"))
        self.assertEqual(len(original), right.stat().st_size)
        store.persist_snapshot(self.parent / "different-same-size", self.b_sources)
        self.b = self.parent / "different-same-size"
        row = next(item for item in self.compare(b=self.b)["sourceDiffs"] if item["sourceId"] == sid)
        self.assertEqual(row["status"], "different")
        self.assertFalse(row["hashMatch"])
        self.assertTrue(row["byteCountMatch"])

    def test_hash_and_byte_count_diff_and_multiple_sources(self):
        for sid in ("metro.station", "metro.railway"):
            path = self.b_sources / contract.SOURCE_FILES[sid]
            path.write_bytes(path.read_bytes() + b" ")
        store.persist_snapshot(self.parent / "different-multiple", self.b_sources)
        self.b = self.parent / "different-multiple"
        result = self.compare(b=self.b)
        self.assertEqual(result["overallBasicStatus"], "changed")
        changed = [row for row in result["sourceDiffs"] if row["status"] == "different"]
        self.assertEqual(len(changed), 2)
        self.assertTrue(all(not row["hashMatch"] and not row["byteCountMatch"] for row in changed))

    def test_metadata_only_gtfs_version_and_period_differences(self):
        def update(record):
            record["metadata"]["gtfs"].update({"feedVersion": "fixture-next",
                                                "validFrom": "2026-01-02", "validThrough": "2026-12-30"})
        self._set_record_metadata(self.b, "metro.gtfs", update)
        result = self.compare()
        self.assertEqual(result["overallBasicStatus"], "changed")
        self.assertTrue(all(row["status"] == "identical" for row in result["sourceDiffs"]))
        gtfs = [row for row in result["metadataDiffs"] if row["sourceId"] == "metro.gtfs"]
        self.assertEqual({row["field"] for row in gtfs if row["status"] == "different"},
                         {"feedVersion", "validFrom", "validThrough"})

    def test_metadata_only_odpt_dates_counts_and_missing_counts(self):
        sid = "metro.station"
        def update(record):
            odpt = record["metadata"]["odpt"]
            odpt.update({"recordCount": 2, "dcDates": ["2026-10-09", "2026-10-08"],
                         "issuedDates": ["2026-10-07"], "dcDateMissingCount": 1,
                         "issuedMissingCount": 1})
        self._set_record_metadata(self.b, sid, update)
        result = self.compare()
        self.assertEqual(result["overallBasicStatus"], "changed")
        changed_fields = {row["field"] for row in result["metadataDiffs"]
                          if row["sourceId"] == sid and row["status"] == "different"}
        self.assertEqual(changed_fields, {"recordCount", "dcDates", "dcDateMissingCount", "issuedMissingCount"})
        self.assertTrue(all(row["status"] == "identical" for row in result["sourceDiffs"]))

    def test_array_order_is_preserved(self):
        sid = "metro.station"
        def update(record):
            record["metadata"]["odpt"]["dcDates"] = ["first", "second"]
        self._set_record_metadata(self.a, sid, update)
        def reverse(record):
            record["metadata"]["odpt"]["dcDates"] = ["second", "first"]
        self._set_record_metadata(self.b, sid, reverse)
        result = self.compare()
        row = next(row for row in result["metadataDiffs"]
                   if row["sourceId"] == sid and row["field"] == "dcDates")
        self.assertEqual(row["status"], "different")

    def test_both_unknown_and_one_unknown_metadata_are_distinguished(self):
        for current in (self.a, self.b):
            sid = "metro.station"
            def unavailable(record):
                record["metadata"] = {"status": "unavailable", "gtfs": None, "odpt": None}
            self._set_record_metadata(current, sid, unavailable)
        result = self.compare()
        self.assertEqual({row["status"] for row in result["metadataDiffs"]
                          if row["sourceId"] == "metro.station"}, {"both-unknown"})
        self.assertEqual(result["overallBasicStatus"], "unavailable")
        self._set_record_metadata(self.a, "metro.station", lambda record: record["metadata"].update(
            {"status": "parsed", "gtfs": None, "odpt": {"recordCount": 1, "dcDates": ["a-date"],
             "issuedDates": ["2026-10-07"], "dcDateMissingCount": 0, "issuedMissingCount": 0}}))
        result = self.compare()
        self.assertEqual({row["status"] for row in result["metadataDiffs"]
                          if row["sourceId"] == "metro.station"}, {"one-unknown"})

    def test_original_source_reference_is_not_required(self):
        self.a_sources.rename(self.root / "raw-a-removed")
        self.b_sources.rename(self.root / "raw-b-removed")
        result = self.compare()
        self.assertEqual(result["overallBasicStatus"], "identical")

    def test_missing_baseline_candidate_and_corrupt_stores_fail_closed(self):
        with self.assertRaises(source_diff.SourceDiffError) as raised:
            self.compare(a=self.parent / "missing")
        self.assertTrue(raised.exception.code.startswith("baseline_"))
        with self.assertRaises(source_diff.SourceDiffError) as raised:
            self.compare(b=self.parent / "missing")
        self.assertTrue(raised.exception.code.startswith("candidate_"))
        broken_baseline = self.parent / "broken-baseline"
        store.persist_snapshot(broken_baseline, self.a_sources)
        (broken_baseline / "snapshot.json").write_text("{bad", encoding="utf-8")
        with self.assertRaises(source_diff.SourceDiffError) as raised:
            self.compare(a=broken_baseline)
        self.assertTrue(raised.exception.code.startswith("baseline_"))
        (self.b / "snapshot.json").write_text("{bad", encoding="utf-8")
        with self.assertRaises(source_diff.SourceDiffError) as raised:
            self.compare()
        self.assertTrue(raised.exception.code.startswith("candidate_"))

    def test_selected_records_missing_extra_reference_and_fingerprint_corruption(self):
        snapshot = self.a / "snapshot.json"
        original = json.loads(snapshot.read_text())
        for selected in ({key: value for key, value in original["selectedRecords"].items()
                          if key != "metro.station"},
                         {**original["selectedRecords"], "metro.unknown": "record"},
                         {**original["selectedRecords"], "metro.station": "00000000-0000-0000-0000-000000000000"}):
            self._rewrite_json(snapshot, lambda data, selected=selected: data.update({"selectedRecords": selected}))
            with self.assertRaises(source_diff.SourceDiffError):
                self.compare()
        self._rewrite_json(snapshot, lambda data: data.update({"selectedRecords": original["selectedRecords"],
                                                                "contentFingerprint": "0" * 64}))
        with self.assertRaises(source_diff.SourceDiffError) as raised:
            self.compare()
        self.assertIn("fingerprint", raised.exception.code)

    def test_source_record_reference_metadata_schema_and_unknown_schema_rejected(self):
        record_path = self.b / "sources" / "metro.station.json"
        self._rewrite_json(record_path, lambda data: data.update({"sourceId": "metro.railway"}))
        with self.assertRaises(source_diff.SourceDiffError):
            self.compare()
        # Restore from a freshly generated candidate before the other corruptions.
        self.b_sources = self._sources("a")
        store.persist_snapshot(self.parent / "candidate-restored", self.b_sources)
        self.b = self.parent / "candidate-restored"
        self._set_record_metadata(self.b, "metro.station", lambda data: data["metadata"].update(
            {"status": "parsed", "gtfs": None, "odpt": {"unexpected": 1}}))
        with self.assertRaises(source_diff.SourceDiffError) as raised:
            self.compare()
        self.assertIn("metadata", raised.exception.code)
        self.b_sources = self._sources("a")
        store.persist_snapshot(self.parent / "candidate-valid-again", self.b_sources)
        self.b = self.parent / "candidate-valid-again"
        snapshot_path = self.b / "snapshot.json"
        self._rewrite_json(snapshot_path, lambda data: data.update({"schemaVersion": 2}))
        with self.assertRaises(source_diff.SourceDiffError) as raised:
            self.compare()
        self.assertIn("schema_version", raised.exception.code)

    def test_symlink_and_non_absolute_paths_rejected(self):
        linked = self.parent / "linked"
        linked.symlink_to(self.a, target_is_directory=True)
        with self.assertRaises(source_diff.SourceDiffError) as raised:
            self.compare(a=linked)
        self.assertIn("symlink", raised.exception.code)
        with self.assertRaises(source_diff.SourceDiffError) as raised:
            self.compare(a=Path("relative"))
        self.assertIn("absolute", raised.exception.code)

    def test_cli_summarizes_changes_without_source_payload(self):
        from scripts import odpt_source_inventory as cli
        output = io.StringIO()
        with patch("sys.stdout", output):
            code = cli.main(["compare", "--baseline-store", str(self.a),
                             "--candidate-store", str(self.b)])
        self.assertEqual(code, 0)
        self.assertIn("overall_basic_status=identical", output.getvalue())
        self.assertIn("source_id=metro.gtfs", output.getvalue())
        self.assertNotIn("dc:date", output.getvalue())


if __name__ == "__main__":
    unittest.main()
