import io
import json
import os
import stat
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from scripts import odpt_source_contract as contract
from scripts import odpt_source_inventory as inventory
from scripts import odpt_source_store as store


def synthetic_gtfs():
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for member in sorted(inventory.GTFS_MEMBERS):
            content = ("feed_version,feed_start_date,feed_end_date\nfixture,20260101,20261231\n"
                       if member == "feed_info.txt" else "fixture\n")
            archive.writestr(member, content)
    return output.getvalue()


class SourceStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir="/private/tmp")
        self.root = Path(self.temp.name)
        self.sources = self.root / "raw-sources"
        self.sources.mkdir(mode=0o700)
        self.store_parent = self.root / "private"
        self.store_parent.mkdir(mode=0o700)
        for source_id, filename in contract.SOURCE_FILES.items():
            raw = synthetic_gtfs() if source_id == "metro.gtfs" else json.dumps(
                [{"@id": f"urn:{source_id}", "dc:date": "2026-10-08"}], separators=(",", ":")).encode()
            (self.sources / filename).write_bytes(raw)
        os.chmod(self.store_parent, 0o700)

    def tearDown(self):
        self.temp.cleanup()

    def destination(self, name="snapshot-one"):
        return self.store_parent / name

    def persisted(self, name="snapshot-one"):
        target = self.destination(name)
        result = store.persist_snapshot(target, self.sources)
        return target, result

    def test_snapshot_generation_contract_and_phase1a_canonical_fingerprint(self):
        inventory_result = inventory.generate_inventory(self.sources, "2026-11-03T00:00:00Z")
        records = inventory_result["records"]
        snapshot = store.create_snapshot(records, "2026-11-03T00:00:00Z")
        self.assertEqual(snapshot["schemaVersion"], 1)
        self.assertEqual(snapshot["mode"], "legacy-observation")
        self.assertEqual(snapshot["completeness"], "complete")
        self.assertEqual(snapshot["acquisitionStatus"], "historical-unknown")
        self.assertEqual(snapshot["crossSourceConsistency"], "not-evaluated")
        self.assertEqual(set(snapshot["selectedRecords"]), contract.SOURCE_IDS)
        self.assertEqual(snapshot["contentFingerprint"], contract.content_fingerprint(records))
        self.assertIs(contract.validate_snapshot(snapshot, records), snapshot)

    def test_persist_reload_verify_and_private_modes(self):
        target, result = self.persisted()
        self.assertEqual(result["verification"]["recordStatus"], "PASS")
        self.assertEqual(result["verification"]["sourceBytesStatus"], "match")
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((target / "sources").stat().st_mode), 0o700)
        files = [target / "snapshot.json", *(target / "sources").glob("*.json")]
        self.assertEqual(len(files), 8)
        for path in files:
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        check = store.verify_store(target, self.sources)
        self.assertEqual(check["recordStatus"], "PASS")
        self.assertEqual(check["sourceBytesStatus"], "match")

    def test_same_source_content_can_create_distinct_snapshots(self):
        first, a = self.persisted("first")
        second, b = self.persisted("second")
        self.assertNotEqual(a["snapshot"]["snapshotId"], b["snapshot"]["snapshotId"])
        self.assertEqual(a["snapshot"]["contentFingerprint"], b["snapshot"]["contentFingerprint"])
        self.assertTrue(first.is_dir() and second.is_dir())

    def test_source_reference_mismatch_missing_and_unavailable_are_distinct(self):
        target, _ = self.persisted()
        changed = self.sources / contract.SOURCE_FILES["metro.station"]
        original = changed.read_bytes()
        changed.write_bytes(original + b" ")
        result = store.verify_store(target, self.sources)
        self.assertEqual(result["recordStatus"], "PASS")
        self.assertEqual(result["sourceBytesStatus"], "mismatch")
        changed.write_bytes(original)
        changed.unlink()
        result = store.verify_store(target, self.sources)
        self.assertEqual(result["sourceBytesStatus"], "missing")
        result = store.verify_store(target, self.root / "absent-source-dir")
        self.assertEqual(result["sourceBytesStatus"], "unavailable")

    def test_snapshot_reference_and_fingerprint_tampering_are_rejected(self):
        target, _ = self.persisted()
        snapshot_path = target / "snapshot.json"
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        snapshot["selectedRecords"]["metro.station"] = "00000000-0000-0000-0000-000000000000"
        snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
        with self.assertRaises(store.StoreError) as raised:
            store.verify_store(target, self.sources)
        self.assertIn("snapshot_record_reference_missing", raised.exception.code)
        snapshot["selectedRecords"]["metro.station"] = next(
            json.loads((target / "sources" / f"{sid}.json").read_text())["recordId"]
            for sid in contract.SOURCE_IDS if sid == "metro.station")
        snapshot["contentFingerprint"] = "0" * 64
        snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
        with self.assertRaises(store.StoreError) as raised:
            store.verify_store(target, self.sources)
        self.assertIn("snapshot_fingerprint_mismatch", raised.exception.code)

    def test_record_json_corruption_duplicate_unknown_and_snapshot_duplicate(self):
        target, _ = self.persisted()
        source_file = target / "sources" / "metro.station.json"
        original = source_file.read_text(encoding="utf-8")
        source_file.write_text(original[:-2] + ',"schemaVersion":1}\n', encoding="utf-8")
        with self.assertRaises(store.StoreError) as raised:
            store.verify_store(target, self.sources)
        self.assertIn("json_duplicate_key", raised.exception.code)
        record = json.loads(original)
        record["unexpected"] = True
        source_file.write_text(json.dumps(record), encoding="utf-8")
        with self.assertRaises(store.StoreError) as raised:
            store.verify_store(target, self.sources)
        self.assertIn("source_record_fields_invalid", raised.exception.code)
        source_file.write_text(original, encoding="utf-8")
        snapshot_file = target / "snapshot.json"
        snapshot_text = snapshot_file.read_text(encoding="utf-8").rstrip()
        snapshot_file.write_text(snapshot_text[:-1] + ',"schemaVersion":1}', encoding="utf-8")
        with self.assertRaises(store.StoreError) as raised:
            store.verify_store(target, self.sources)
        self.assertEqual(raised.exception.code, "store_json_duplicate_key")

    def test_partial_store_is_never_adopted(self):
        target = self.destination()
        target.mkdir(mode=0o700)
        (target / "sources").mkdir(mode=0o700)
        with self.assertRaises(store.StoreError) as raised:
            store.verify_store(target, self.sources)
        self.assertEqual(raised.exception.code, "store_incomplete_snapshot")

    def test_failure_injection_cleans_new_store_and_leaves_no_temporary_files(self):
        target = self.destination()

        def fail(stage):
            if stage == "source-written-3":
                raise OSError("synthetic interruption")

        with self.assertRaises(store.StoreError) as raised:
            store.persist_snapshot(target, self.sources, fault_hook=fail)
        self.assertEqual(raised.exception.code, "store_write_failed")
        self.assertFalse(target.exists())
        self.assertEqual(list(self.store_parent.iterdir()), [])

    def test_write_error_cleanup_and_snapshot_commit_is_last(self):
        target = self.destination()
        original_write = store.os.write

        def fail_write(*_args):
            raise OSError("injected write failure")

        with patch.object(store.os, "write", fail_write):
            with self.assertRaises(store.StoreError) as raised:
                store.persist_snapshot(target, self.sources)
        self.assertEqual(raised.exception.code, "store_write_failed")
        self.assertFalse(target.exists())
        stages = []

        def inspect_stage(stage):
            stages.append(stage)
            if stage.startswith("source-written-"):
                self.assertFalse((target / "snapshot.json").exists())

        store.persist_snapshot(target, self.sources, fault_hook=inspect_stage)
        self.assertEqual(stages[-1], "after-snapshot-commit")

    def test_existing_destination_symlink_traversal_and_repository_paths_are_rejected(self):
        existing = self.destination("existing")
        existing.mkdir(mode=0o700)
        with self.assertRaises(store.StoreError) as raised:
            store.persist_snapshot(existing, self.sources)
        self.assertEqual(raised.exception.code, "store_destination_exists")
        link = self.store_parent / "linked"
        link.symlink_to(self.sources, target_is_directory=True)
        with self.assertRaises(store.StoreError) as raised:
            store.persist_snapshot(link, self.sources)
        self.assertEqual(raised.exception.code, "store_path_symlink")
        with self.assertRaises(store.StoreError) as raised:
            store.persist_snapshot(self.store_parent / ".." / "escape", self.sources)
        self.assertEqual(raised.exception.code, "store_path_traversal")
        with self.assertRaises(store.StoreError) as raised:
            store.persist_snapshot(store.PROJECT_ROOT / "private-store", self.sources)
        self.assertEqual(raised.exception.code, "store_path_inside_repository")

    def test_store_creation_permission_failure_does_not_leave_destination(self):
        target = self.destination()
        original_mkdir = store.os.mkdir

        def fail_target(path, mode=0o777, *args, **kwargs):
            if Path(path) == target:
                raise PermissionError("injected permission failure")
            return original_mkdir(path, mode, *args, **kwargs)

        with patch.object(store.os, "mkdir", fail_target):
            with self.assertRaises(store.StoreError) as raised:
                store.persist_snapshot(target, self.sources)
        self.assertEqual(raised.exception.code, "store_create_failed")
        self.assertFalse(target.exists())

    def test_directory_permission_and_content_shape_are_checked(self):
        target, _ = self.persisted()
        os.chmod(target, 0o755)
        with self.assertRaises(store.StoreError) as raised:
            store.verify_store(target, self.sources)
        self.assertEqual(raised.exception.code, "store_directory_permissions_unsafe")

    def test_snapshot_file_permission_is_checked(self):
        target, _ = self.persisted()
        os.chmod(target / "snapshot.json", 0o644)
        with self.assertRaises(store.StoreError) as raised:
            store.verify_store(target, self.sources)
        self.assertEqual(raised.exception.code, "store_file_permissions_unsafe")


if __name__ == "__main__":
    unittest.main()
