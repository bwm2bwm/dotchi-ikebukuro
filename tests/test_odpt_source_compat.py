import copy
import hashlib
import io
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from scripts import odpt_source_compat as compat
from scripts import odpt_source_contract as contract
from scripts import odpt_source_inventory as inventory
from scripts import odpt_source_store as store
import scripts.odpt_snapshot_qa as odpt0


def synthetic_gtfs():
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for member in sorted(inventory.GTFS_MEMBERS):
            content = ("feed_version,feed_start_date,feed_end_date\nfixture,20260101,20261231\n"
                       if member == "feed_info.txt" else "fixture\n")
            archive.writestr(member, content)
    return output.getvalue()


class SourceCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir="/private/tmp")
        self.root = Path(self.temp.name)
        self.source_dir = self.root / "saved-source"
        self.source_dir.mkdir(mode=0o700)
        self.store_parent = self.root / "private-store"
        self.store_parent.mkdir(mode=0o700)
        os.chmod(self.store_parent, 0o700)
        for source_id, filename in contract.SOURCE_FILES.items():
            raw = synthetic_gtfs() if source_id == "metro.gtfs" else json.dumps(
                [{"@id": f"urn:{source_id}", "dc:date": "2026-10-08", "dct:issued": "2026-10-07"}],
                separators=(",", ":")).encode()
            (self.source_dir / filename).write_bytes(raw)
        self.store_path = self.store_parent / "snapshot"
        store.persist_snapshot(self.store_path, self.source_dir)

    def tearDown(self):
        self.temp.cleanup()

    def test_compatibility_inventory_fingerprints_metadata_and_statuses(self):
        result = compat.compare_legacy(self.store_path, self.source_dir)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["sourceInventory"]["status"], "PASS")
        self.assertEqual(result["sourceInventory"]["sourceCount"], 7)
        self.assertTrue(all(row["sha256Match"] and row["byteCountMatch"]
                            for row in result["sourceInventory"]["sources"]))
        self.assertEqual(result["currentSourceBytes"]["status"], "match")
        self.assertEqual(result["currentSourceBytes"]["matched"], 7)
        self.assertEqual(result["newSnapshotFingerprint"]["status"], "PASS")
        self.assertEqual(result["odpt0Fingerprint"]["status"], "PASS")
        self.assertEqual(result["odpt0Fingerprint"]["baselineComparison"], "no-persisted-report-available")
        self.assertNotEqual(result["newSnapshotFingerprint"]["value"],
                            result["odpt0Fingerprint"]["value"])
        self.assertEqual(result["metadataComparison"]["status"], "compatible-with-extraction-differences")
        self.assertEqual(len(result["metadataComparison"]["schemaDifferences"]), 7)
        self.assertEqual(result["acquisitionStatus"], "historical-unknown")
        self.assertEqual(result["crossSourceConsistency"], "not-evaluated")
        self.assertIn("no approval", result["publicationStatus"])

        entries, _ = odpt0._inventory(self.source_dir)
        expected = hashlib.sha256(json.dumps(entries, ensure_ascii=False, sort_keys=True,
                                             separators=(",", ":")).encode("utf-8")).hexdigest()
        self.assertEqual(result["odpt0Fingerprint"]["value"], expected)

    def test_inventory_rejects_missing_extra_duplicate_and_bad_mapping(self):
        records = inventory.generate_inventory(self.source_dir)["records"]
        entries, _ = odpt0._inventory(self.source_dir)
        cases = [
            ("source_inventory_source_set_mismatch", records[:-1], entries),
            ("source_inventory_duplicate_source_id", records + [records[0]], entries),
            ("legacy_inventory_source_set_mismatch", records, entries[:-1]),
            ("legacy_inventory_duplicate_path", records, entries + [entries[0]]),
            ("legacy_inventory_path_invalid", records, entries[:-1] + [{**entries[-1], "path": "../other"}]),
        ]
        for code, source_records, old_entries in cases:
            with self.subTest(code=code), self.assertRaises(compat.CompatibilityError) as raised:
                compat.compare_inventories(source_records, old_entries)
            self.assertEqual(raised.exception.code, code)
        wrong_name = copy.deepcopy(records)
        wrong_name[0]["artifact"]["path"] = "raw/not-the-file.json"
        with self.assertRaises(compat.CompatibilityError) as raised:
            compat.compare_inventories(wrong_name, entries)
        self.assertEqual(raised.exception.code, "source_id_filename_mapping_mismatch")
        wrong_hash = copy.deepcopy(entries)
        wrong_hash[0]["sha256"] = "0" * 64
        with self.assertRaises(compat.CompatibilityError) as raised:
            compat.compare_inventories(records, wrong_hash)
        self.assertEqual(raised.exception.code, "source_hash_mismatch")
        wrong_size = copy.deepcopy(entries)
        wrong_size[0]["sizeBytes"] += 1
        with self.assertRaises(compat.CompatibilityError) as raised:
            compat.compare_inventories(records, wrong_size)
        self.assertEqual(raised.exception.code, "source_byte_count_mismatch")

    def test_snapshot_fingerprint_corruption_is_rejected(self):
        path = self.store_path / "snapshot.json"
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        snapshot["contentFingerprint"] = "0" * 64
        path.write_text(json.dumps(snapshot), encoding="utf-8")
        with self.assertRaises(store.StoreError) as raised:
            compat.compare_legacy(self.store_path, self.source_dir)
        self.assertEqual(raised.exception.code, "store_snapshot_snapshot_fingerprint_mismatch")

    def test_source_reference_change_and_missing_are_distinguished(self):
        path = self.source_dir / contract.SOURCE_FILES["metro.station"]
        original = path.read_bytes()
        path.write_bytes(original + b" ")
        with self.assertRaises(compat.CompatibilityError) as raised:
            compat.compare_legacy(self.store_path, self.source_dir)
        self.assertEqual(raised.exception.code, "source_reference_mismatch")
        path.write_bytes(original)
        path.unlink()
        with self.assertRaises(compat.CompatibilityError) as raised:
            compat.compare_legacy(self.store_path, self.source_dir)
        self.assertEqual(raised.exception.code, "source_reference_missing")

    def test_metadata_projection_difference_and_true_mismatch_are_distinguished(self):
        compatible = compat.compare_legacy(self.store_path, self.source_dir)
        self.assertEqual(compatible["metadataComparison"]["status"], "compatible-with-extraction-differences")
        source_path = self.store_path / "sources" / "metro.station.json"
        record = json.loads(source_path.read_text(encoding="utf-8"))
        record["metadata"]["odpt"]["dcDates"] = ["2099-01-01"]
        source_path.write_text(json.dumps(record), encoding="utf-8")
        result = compat.compare_legacy(self.store_path, self.source_dir)
        self.assertEqual(result["sourceInventory"]["status"], "PASS")
        self.assertEqual(result["currentSourceBytes"]["status"], "match")
        self.assertEqual(result["metadataComparison"]["status"], "mismatch")
        self.assertEqual(result["metadataComparison"]["mismatches"][0]["classification"],
                         "shared_field_extraction_mismatch")
        self.assertEqual(result["errorCode"], "metadata_shared_field_extraction_mismatch")

    def test_invalid_metadata_schema_is_rejected(self):
        source_path = self.store_path / "sources" / "metro.station.json"
        record = json.loads(source_path.read_text(encoding="utf-8"))
        record["metadata"]["odpt"]["recordCount"] = "1"
        source_path.write_text(json.dumps(record), encoding="utf-8")
        with self.assertRaises(store.StoreError) as raised:
            compat.compare_legacy(self.store_path, self.source_dir)
        self.assertEqual(raised.exception.code, "store_source_record_source_metadata_invalid")

    def test_odpt0_fingerprint_invalid_result_is_rejected(self):
        with patch.object(compat.odpt0, "_fingerprint", return_value="bad"):
            with self.assertRaises(compat.CompatibilityError) as raised:
                compat.compare_legacy(self.store_path, self.source_dir)
        self.assertEqual(raised.exception.code, "odpt0_fingerprint_invalid")

    def test_incomplete_store_symlink_and_traversal_are_rejected(self):
        incomplete = self.store_parent / "incomplete"
        incomplete.mkdir(mode=0o700)
        (incomplete / "sources").mkdir(mode=0o700)
        with self.assertRaises(store.StoreError) as raised:
            compat.compare_legacy(incomplete, self.source_dir)
        self.assertEqual(raised.exception.code, "store_incomplete_snapshot")
        link = self.store_parent / "linked"
        link.symlink_to(self.store_path, target_is_directory=True)
        with self.assertRaises(store.StoreError) as raised:
            compat.compare_legacy(link, self.source_dir)
        self.assertEqual(raised.exception.code, "store_path_symlink")
        with self.assertRaises(store.StoreError) as raised:
            compat.compare_legacy(self.store_parent / ".." / "outside", self.source_dir)
        self.assertEqual(raised.exception.code, "store_path_traversal")


if __name__ == "__main__":
    unittest.main()
