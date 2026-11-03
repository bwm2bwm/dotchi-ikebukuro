import hashlib
import io
import json
import struct
import tempfile
import unittest
import uuid
import warnings
import zipfile
from pathlib import Path
from unittest.mock import patch

from scripts import odpt_source_contract as contract
from scripts import odpt_source_inventory as inventory


def gtfs_zip(*, extra=(), duplicate=False, corrupt=False):
    if corrupt:
        return b"not a zip"
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for member in sorted(inventory.GTFS_MEMBERS):
            content = ("feed_version,feed_start_date,feed_end_date\n"
                       "fixture-2026-10-08,20261008,20271007\n" if member == "feed_info.txt" else "fixture\n")
            archive.writestr(member, content)
        for member, content in extra:
            archive.writestr(member, content)
        if duplicate:
            archive.writestr("feed_info.txt", "feed_version,feed_start_date,feed_end_date\nother,20260101,20271231\n")
    return stream.getvalue()


class SourceInventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for source_id, filename in contract.SOURCE_FILES.items():
            if source_id == "metro.gtfs":
                raw = gtfs_zip()
            else:
                raw = json.dumps([{"@id": f"urn:{source_id}", "dc:date": "2026-10-08",
                                   "dct:issued": "2026-10-07"}], separators=(",", ":")).encode()
            (self.root / filename).write_bytes(raw)

    def tearDown(self):
        self.temp.cleanup()

    def test_seven_sources_hash_metadata_and_phase1a_contract(self):
        result = inventory.generate_inventory(self.root, "2026-11-03T01:02:03Z")
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["sourceCount"], 7)
        self.assertEqual({row["sourceId"] for row in result["records"]}, contract.SOURCE_IDS)
        for row in result["records"]:
            raw = (self.root / contract.SOURCE_FILES[row["sourceId"]]).read_bytes()
            self.assertEqual(row["artifact"]["sha256"], hashlib.sha256(raw).hexdigest())
            self.assertEqual(row["artifact"]["sizeBytes"], len(raw))
            self.assertEqual(row["artifact"]["path"], f"raw/{contract.SOURCE_FILES[row['sourceId']]}")
            self.assertEqual(row["mode"], "legacy-observation")
            self.assertEqual(row["outcome"], "observed")
            self.assertEqual(row["observedAt"], "2026-11-03T01:02:03Z")
            self.assertIsNone(row["retrievedAt"])
            self.assertIsNone(row["startedAt"])
            self.assertIsNone(row["finishedAt"])
            self.assertIn("historical_acquisition_not_recorded", row["unknownReasons"])
            self.assertIs(contract.validate_source_record(row), row)
        odpt_row = next(row for row in result["records"] if row["sourceType"] == "odpt-json")
        odpt = odpt_row["metadata"]["odpt"]
        self.assertEqual(odpt["recordCount"], 1)
        self.assertEqual(odpt["dcDates"], ["2026-10-08"])
        self.assertEqual(odpt["issuedDates"], ["2026-10-07"])
        self.assertEqual(odpt["dcDateMissingCount"], 0)
        self.assertEqual(odpt["issuedMissingCount"], 0)
        gtfs = next(row for row in result["records"] if row["sourceId"] == "metro.gtfs")
        self.assertEqual(gtfs["metadata"]["gtfs"], {
            "feedVersion": "fixture-2026-10-08", "validFrom": "2026-10-08", "validThrough": "2027-10-07"})

    def test_missing_source_and_file_read_error(self):
        (self.root / contract.SOURCE_FILES["metro.station"]).unlink()
        self.assertInventoryError("source_missing_or_outside_root", lambda: inventory.generate_inventory(self.root))
        path = self.root / contract.SOURCE_FILES["metro.station"]
        path.write_text("[]", encoding="utf-8")
        import os
        original_open = os.open

        def fail_selected(target, flags, *args, **kwargs):
            if Path(target).name == path.name:
                raise OSError("synthetic read failure")
            return original_open(target, flags, *args, **kwargs)

        with patch.object(os, "open", fail_selected):
            self.assertInventoryError("source_read_failed", lambda: inventory.generate_inventory(self.root))

    def test_malformed_json_and_missing_metadata(self):
        path = self.root / contract.SOURCE_FILES["metro.station"]
        path.write_text("{broken", encoding="utf-8")
        self.assertInventoryError("json_invalid", lambda: inventory.generate_inventory(self.root))
        path.write_text('[{"@id":"urn:station"}]', encoding="utf-8")
        result = inventory.generate_inventory(self.root)
        row = next(item for item in result["records"] if item["sourceId"] == "metro.station")
        self.assertEqual(row["metadata"]["odpt"]["dcDateMissingCount"], 1)
        self.assertEqual(row["metadata"]["odpt"]["issuedMissingCount"], 1)

    def test_malformed_zip_unsafe_entry_and_duplicate_entry(self):
        path = self.root / contract.SOURCE_FILES["metro.gtfs"]
        path.write_bytes(gtfs_zip(corrupt=True))
        self.assertInventoryError("gtfs_zip_invalid", lambda: inventory.generate_inventory(self.root))
        damaged = bytearray(gtfs_zip())
        with zipfile.ZipFile(io.BytesIO(damaged)) as archive:
            info = archive.getinfo("feed_info.txt")
            name_len, extra_len = struct.unpack_from("<HH", damaged, info.header_offset + 26)
            content_offset = info.header_offset + 30 + name_len + extra_len
        damaged[content_offset] ^= 0xFF
        path.write_bytes(damaged)
        self.assertInventoryError("gtfs_zip_invalid", lambda: inventory.generate_inventory(self.root))
        path.write_bytes(gtfs_zip(extra=[("../outside.txt", "x")]))
        self.assertInventoryError("zip_entry_path_unsafe", lambda: inventory.generate_inventory(self.root))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            path.write_bytes(gtfs_zip(duplicate=True))
        self.assertInventoryError("zip_duplicate_entry", lambda: inventory.generate_inventory(self.root))

    def test_symlink_is_rejected(self):
        path = self.root / contract.SOURCE_FILES["metro.station"]
        replacement = self.root / "elsewhere.json"
        replacement.write_text("[]", encoding="utf-8")
        path.unlink()
        path.symlink_to(replacement)
        self.assertInventoryError("source_not_regular_file", lambda: inventory.generate_inventory(self.root))

    def test_change_during_inventory_is_rejected(self):
        calls = 0

        def mutate_on_reread(path, source_id):
            nonlocal calls
            calls += 1
            raw, metadata = inventory._stable_read(path, source_id)
            if calls == 8:
                raw += b" "
            return raw, metadata

        self.assertInventoryError("source_changed_during_inventory",
                                  lambda: inventory.generate_inventory(self.root, read_hook=mutate_on_reread))

    def test_root_and_metadata_type_errors(self):
        self.assertInventoryError("source_directory_invalid",
                                  lambda: inventory.generate_inventory(self.root / "missing"))
        path = self.root / contract.SOURCE_FILES["metro.station"]
        path.write_text('[{"dc:date":17}]', encoding="utf-8")
        self.assertInventoryError("odpt_metadata_invalid", lambda: inventory.generate_inventory(self.root))

    def assertInventoryError(self, code, callback):
        with self.assertRaises(inventory.InventoryError) as raised:
            callback()
        self.assertEqual(raised.exception.code, code)


if __name__ == "__main__":
    unittest.main()
