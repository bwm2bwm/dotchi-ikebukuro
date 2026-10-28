from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_public_site import build_public_site
from release_contract import STATION_FILES
from release_contract import calculate_release_id
from assemble_public_release import (
    AssemblyError,
    assemble_public_artifact,
    retention_deadline,
)
from synthetic_public_fixture_factory import generate_fixture_directory
from validate_public_artifact import ArtifactValidationError, validate_release_managed_artifact


JST = timezone(timedelta(hours=9))


def read_manifest(path: Path) -> dict:
    return json.loads((path / "manifest.json").read_text(encoding="utf-8"))


class ReleaseAssemblyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="release-assembly-tests-", dir="/private/tmp")
        cls.base = Path(cls.temp.name)
        cls.releases = {}
        for label, anchor in (("A", "2026-10-27"), ("B", "2026-10-28"), ("C", "2026-10-29")):
            fixtures = cls.base / f"fixtures-{label}"
            site = cls.base / f"release-{label}"
            generate_fixture_directory(fixtures, date.fromisoformat(anchor))
            build_public_site(fixtures=fixtures, output=site, release_managed=True)
            cls.releases[label] = site
        fixtures = cls.base / "fixtures-legacy"
        cls.legacy = cls.base / "legacy"
        generate_fixture_directory(fixtures, date(2026, 10, 27))
        build_public_site(fixtures=fixtures, output=cls.legacy)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="release-assembly-case-", dir="/private/tmp")
        self.base = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def assemble(self, previous: Path, new: Path, name: str, when: str, **limits):
        return assemble_public_artifact(previous=previous, new_release=new,
            output=self.base / name, evaluated_at=when, **limits)

    def test_old_a_plus_new_b_creates_complete_artifact_and_rechecks_descriptor(self):
        old_id = read_manifest(self.releases["A"])["releaseId"]
        new_id = read_manifest(self.releases["B"])["releaseId"]
        result = self.assemble(self.releases["A"], self.releases["B"], "AB",
                               "2026-10-28T12:00:00+09:00")
        output = self.base / "AB"
        manifest = read_manifest(output)
        self.assertEqual(manifest["releaseId"], new_id)
        self.assertEqual([item["releaseId"] for item in manifest["retainedReleases"]], [old_id])
        old = manifest["retainedReleases"][0]
        self.assertEqual(calculate_release_id(old["releaseDescriptor"]), old_id)
        self.assertEqual(result["files"], 26)
        self.assertEqual(result["retained_release_ids"], [old_id])
        self.assertEqual(validate_release_managed_artifact(output)["retained_releases"], 1)
        for station_id, filename in STATION_FILES.items():
            self.assertEqual((output / f"releases/{old_id}/{filename}").read_bytes(),
                             (self.releases["A"] / f"releases/{old_id}/{filename}").read_bytes())

    def test_a_b_then_c_carries_multiple_generations(self):
        ab = self.base / "AB"
        self.assemble(self.releases["A"], self.releases["B"], "AB", "2026-10-28T12:00:00+09:00")
        result = self.assemble(ab, self.releases["C"], "ABC", "2026-10-29T12:00:00+09:00")
        manifest = read_manifest(self.base / "ABC")
        ids = {entry["releaseId"] for entry in manifest["retainedReleases"]}
        self.assertEqual(ids, {read_manifest(self.releases["A"])["releaseId"],
                               read_manifest(self.releases["B"])["releaseId"]})
        self.assertEqual(result["files"], 34)
        self.assertEqual(validate_release_managed_artifact(self.base / "ABC")["retained_releases"], 2)

    def test_same_release_reinput_does_not_duplicate_or_restart_retention(self):
        self.assemble(self.releases["A"], self.releases["B"], "AB", "2026-10-28T12:00:00+09:00")
        before = read_manifest(self.base / "AB")
        result = self.assemble(self.base / "AB", self.releases["B"], "ABB", "2026-10-30T12:00:00+09:00")
        after = read_manifest(self.base / "ABB")
        self.assertEqual(after["publishedAt"], before["publishedAt"])
        self.assertEqual([x["releaseId"] for x in after["retainedReleases"]],
                         [x["releaseId"] for x in before["retainedReleases"]])
        self.assertEqual(result["files"], 26)

    def test_retention_7_day_14_day_48_hour_boundaries_and_overflow(self):
        retired = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)
        end = datetime(2026, 10, 29, 12, tzinfo=timezone.utc)
        self.assertEqual(retention_deadline(retired, end), end + timedelta(hours=48))
        self.assertEqual(retention_deadline(retired, retired), retired + timedelta(days=7))
        fourteen_day_retirement = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)
        end_at_twelve_days = fourteen_day_retirement + timedelta(days=12)
        self.assertEqual(retention_deadline(fourteen_day_retirement, end_at_twelve_days),
                         fourteen_day_retirement + timedelta(days=14))
        with self.assertRaisesRegex(AssemblyError, "14-day cap"):
            retention_deadline(datetime(2026, 10, 17, 12, tzinfo=timezone.utc), end_at_twelve_days)

    def test_retained_files_are_removed_only_after_deadline_and_safety_margin(self):
        self.assemble(self.releases["A"], self.releases["B"], "AB", "2026-10-28T12:00:00+09:00")
        ab_manifest = read_manifest(self.base / "AB")
        old = ab_manifest["retainedReleases"][0]
        deadline = datetime.fromisoformat(old["retainUntil"].replace("Z", "+00:00"))
        keep_at = deadline + timedelta(hours=23, minutes=59, seconds=59)
        self.assemble(self.base / "AB", self.releases["C"], "KEEP", keep_at.isoformat())
        self.assertIn(old["releaseId"], {item["releaseId"] for item in read_manifest(self.base / "KEEP")["retainedReleases"]})
        delete_at = deadline + timedelta(hours=24)
        self.assemble(self.base / "AB", self.releases["C"], "DROP", delete_at.isoformat())
        dropped = read_manifest(self.base / "DROP")
        self.assertNotIn(old["releaseId"], {item["releaseId"] for item in dropped["retainedReleases"]})
        self.assertFalse((self.base / "DROP" / f"releases/{old['releaseId']}").exists())

    def test_jst_and_utc_evaluation_instants_are_the_same_boundary(self):
        jst = datetime(2026, 10, 28, 12, 0, tzinfo=JST)
        utc = jst.astimezone(timezone.utc)
        first = self.assemble(self.releases["A"], self.releases["B"], "JST", jst.isoformat())
        second = self.assemble(self.releases["A"], self.releases["B"], "UTC", utc.isoformat())
        self.assertEqual(first["retained_release_ids"], second["retained_release_ids"])
        self.assertEqual(read_manifest(self.base / "JST"), read_manifest(self.base / "UTC"))

    def test_currently_valid_generation_is_retained_but_policy_conflict_fails_closed(self):
        self.assemble(self.releases["A"], self.releases["B"], "AB", "2026-10-18T12:00:00+09:00")
        # A fixture whose effective validity plus 48 hours exceeds the 14-day ceiling cannot be retired safely.
        with self.assertRaisesRegex(AssemblyError, "14-day cap"):
            self.assemble(self.releases["A"], self.releases["B"], "TOO_EARLY", "2026-10-16T12:00:00+09:00")

    def test_legacy_first_migration_keeps_exact_flat_json_for_14_days(self):
        result = self.assemble(self.legacy, self.releases["B"], "MIGRATED", "2026-10-28T12:00:00+09:00")
        output = self.base / "MIGRATED"
        manifest = read_manifest(output)
        legacy = manifest["legacyCompatibilityV1"]
        self.assertIsNotNone(legacy)
        self.assertEqual(legacy["expiresAt"], "2026-11-11T03:00:00Z")
        self.assertTrue(result["legacy_compatibility"])
        self.assertEqual(result["files"], 26)
        for filename in ("timetable.json", *(f"timetable-{station}.json" for station in STATION_FILES if station != "Hikawadai")):
            self.assertEqual((output / filename).read_bytes(), (self.legacy / filename).read_bytes())
        validate_release_managed_artifact(output)
        expire_at = datetime.fromisoformat(legacy["expiresAt"].replace("Z", "+00:00")) + timedelta(hours=24)
        self.assemble(output, self.releases["C"], "MIGRATED-EXPIRED", expire_at.isoformat())
        expired = read_manifest(self.base / "MIGRATED-EXPIRED")
        self.assertIsNone(expired["legacyCompatibilityV1"])
        self.assertFalse((self.base / "MIGRATED-EXPIRED" / "timetable.json").exists())

    def test_malformed_previous_manifest_missing_json_hash_and_descriptor_are_rejected(self):
        for case in ("manifest", "missing", "hash", "descriptor", "path"):
            with self.subTest(case=case):
                source = self.base / f"bad-{case}"
                shutil.copytree(self.releases["A"], source)
                current = read_manifest(source)
                if case == "manifest":
                    (source / "manifest.json").write_text("{", encoding="utf-8")
                elif case == "missing":
                    old_id = current["releaseId"]
                    (source / f"releases/{old_id}/timetable.json").unlink()
                elif case == "hash":
                    old_id = current["releaseId"]
                    path = source / f"releases/{old_id}/timetable.json"
                    path.write_bytes(path.read_bytes() + b" ")
                elif case == "path":
                    current["stations"]["Hikawadai"]["url"] = "/releases/../timetable.json"
                    (source / "manifest.json").write_text(json.dumps(current), encoding="utf-8")
                else:
                    current["releaseDescriptor"]["builderContractVersion"] = "tampered"
                    (source / "manifest.json").write_text(json.dumps(current), encoding="utf-8")
                with self.assertRaises(AssemblyError):
                    self.assemble(source, self.releases["B"], f"OUT-{case}", "2026-10-28T12:00:00+09:00")

    def test_retained_descriptor_is_recomputed_and_payload_bound(self):
        self.assemble(self.releases["A"], self.releases["B"], "AB", "2026-10-28T12:00:00+09:00")
        output = self.base / "AB"
        manifest = read_manifest(output)
        descriptor = manifest["retainedReleases"][0]["releaseDescriptor"]
        self.assertEqual(calculate_release_id(descriptor), manifest["retainedReleases"][0]["releaseId"])
        station_hash = next(item["payloadSha256"] for item in descriptor["stations"] if item["stationId"] == "Hikawadai")
        self.assertRegex(station_hash, r"^[0-9a-f]{64}$")
        descriptor["stations"][0]["payloadSha256"] = "0" * 64
        manifest["retainedReleases"][0]["releaseDescriptor"] = descriptor
        (output / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaises(ArtifactValidationError):
            validate_release_managed_artifact(output)

    def test_symlink_input_is_rejected(self):
        source = self.base / "symlink-source"
        shutil.copytree(self.releases["A"], source)
        release_id = read_manifest(source)["releaseId"]
        victim = source / f"releases/{release_id}/timetable.json"
        original = victim.read_bytes()
        victim.unlink()
        outside = self.base / "outside.json"
        outside.write_bytes(original)
        victim.symlink_to(outside)
        with self.assertRaises(AssemblyError):
            self.assemble(source, self.releases["B"], "OUT", "2026-10-28T12:00:00+09:00")

    def test_output_conflict_size_limits_and_failure_cleanup(self):
        existing = self.base / "existing"
        existing.mkdir()
        with self.assertRaisesRegex(AssemblyError, "must not already exist"):
            assemble_public_artifact(previous=self.releases["A"], new_release=self.releases["B"],
                output=existing, evaluated_at="2026-10-28T12:00:00+09:00")
        with self.assertRaisesRegex(AssemblyError, "file count"):
            self.assemble(self.releases["A"], self.releases["B"], "TOO_MANY", "2026-10-28T12:00:00+09:00", max_files=1)
        self.assertFalse((self.base / "TOO_MANY").exists())
        self.assertFalse(any(path.name.startswith("dotchi-release-assembly-") for path in self.base.iterdir()))
        with self.assertRaisesRegex(AssemblyError, "single artifact file size"):
            self.assemble(self.releases["A"], self.releases["B"], "TOO_LARGE", "2026-10-28T12:00:00+09:00", max_asset_bytes=1)
        with self.assertRaisesRegex(AssemblyError, "total bytes"):
            self.assemble(self.releases["A"], self.releases["B"], "TOO_BIG_TOTAL", "2026-10-28T12:00:00+09:00", max_total_bytes=1)

    def test_descriptorless_legacy_retention_cannot_be_carried_forward(self):
        self.assemble(self.releases["A"], self.releases["B"], "AB", "2026-10-28T12:00:00+09:00")
        ab = self.base / "AB"
        manifest = read_manifest(ab)
        manifest["retainedReleases"][0].pop("releaseDescriptor")
        (ab / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaises(AssemblyError):
            self.assemble(ab, self.releases["C"], "ABC", "2026-10-29T12:00:00+09:00")


if __name__ == "__main__":
    unittest.main()
