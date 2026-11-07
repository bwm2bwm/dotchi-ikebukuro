"""Synthetic-only publication approvals; never approve acquired ODPT data."""
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from test_odpt_public_v2 import _bundle
import build_odpt_public_release as builder
import odpt_release_contract as c
import release_contract as legacy
from validate_odpt_public_release import validate_artifact

NOW = datetime(2026, 10, 29, 12, tzinfo=timezone.utc)


def inventory(root):
    return {p.relative_to(root).as_posix(): (hashlib.sha256(p.read_bytes()).hexdigest(),
             p.stat().st_size, p.stat().st_ino, p.stat().st_mtime_ns, p.stat().st_ctime_ns)
            for p in root.rglob("*") if p.is_file()}


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="odpt-release-synthetic-", dir="/private/tmp")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "synthetic-source"
        self.source.mkdir()
        for name in c.qa.REQUIRED_JSON:
            (self.source / name).write_text("[]")
        with zipfile.ZipFile(self.source / c.qa.GTFS_NAME, "w") as archive:
            for member in c.qa.GTFS_MEMBERS:
                text = ("feed_version,feed_start_date,feed_end_date\nsynthetic,20260919,20270312\n"
                        if member == "feed_info.txt" else "synthetic\n")
                archive.writestr(member, text)
        self.candidate, self.manifest, self.dates = _bundle(self.root / "candidate")
        entries, _ = c.qa._inventory(self.source)
        self.fp = c.qa._fingerprint(entries)
        self.manifest.update(sourceFiles=entries, sourceFingerprint=self.fp, publicationApproved=False)
        resolution = c.qa._resolution_summary([])
        self.manifest["odpt0"] = {"status": "PASS", "unmatchedOdptJourneyCount": 0,
            "diagnosticSeverity": {"FAIL": {"failGateCount": 0}, "WARNING": {"codeOccurrences": 0}},
            "resolution": resolution,
            "stationDateResolution": [{"stationId": s, "serviceDate": d, "resolution": copy.deepcopy(resolution)}
                                      for s in c.STATION_FILES for d in self.dates]}
        self.manifest["quality"]["odptMatchStatusCounts"] = {"unique_match": 24}
        self.save_manifest()
        self.approval = self.root / "synthetic-approval.json"
        self.request = {"candidateDigest": c.candidate_digest(self.candidate), "sourceFingerprint": self.fp,
            "applicationPeriod": {"startsAt": "2026-10-29T00:00:00+09:00", "endsAt": "2026-10-30T00:00:00+09:00"},
            "approval": {"approved": True, "recordId": "synthetic-test-only", "approvedAt": "2026-10-29T12:00:00Z"},
            "retrievedAt": "2026-10-28T00:00:00Z", "evidenceKind": "synthetic",
            "codeCommit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=c.ROOT, text=True).strip(),
            "attribution": {"provider": "東京メトロ / 公共交通オープンデータセンター", "sourceUrl": "https://www.odpt.org/"}}
        self.save_request()
        self.output = self.root / "release"

    def save_manifest(self):
        (self.candidate / "private-generator-manifest.json").write_bytes(c.canonical(self.manifest))

    def save_request(self):
        self.approval.write_bytes(c.canonical(self.request))

    def build(self):
        return builder.build(candidate=self.candidate, source=self.source, approval=self.approval,
                             output=self.output, now=NOW)

    def validate(self, **kwargs):
        return validate_artifact(self.output, candidate=self.candidate, source=self.source,
             approval=self.approval, expected_candidate_digest=self.request["candidateDigest"],
             expected_source_fingerprint=self.fp, now=kwargs.get("now", NOW))

    def public(self):
        return c.load_json((self.output / "manifest.json").read_bytes())

    def write_public(self, value):
        (self.output / "manifest.json").write_bytes(c.canonical(value))

    def test_success_independent_validator_and_input_immutability(self):
        before = inventory(self.candidate), inventory(self.source)
        result = self.build()
        self.assertEqual(result["stationCount"], 8)
        self.assertFalse(result["deployable"])
        self.assertEqual(self.validate()["releaseId"], result["releaseId"])
        self.assertEqual(before, (inventory(self.candidate), inventory(self.source)))
        public = self.public()
        self.assertEqual(public["metadata"]["quality"]["resolution"], self.manifest["odpt0"]["resolution"])
        self.assertNotIn("private-generator-manifest", (self.output / "manifest.json").read_text())
        self.assertEqual(legacy.validate_versioned_manifest(public, now=NOW), public)
        with self.assertRaises(legacy.ReleaseContractError):
            legacy.validate_manifest(public)  # v1 entrypoint cannot deploy v2 data.
        for raw in (self.output / "releases").rglob("*.json"):
            self.assertIsNone(c.load_json(raw.read_bytes())["payload"]["applicationPeriod"])
        self.assertFalse(self.manifest["publicationApproved"])

    def test_missing_approval_is_rejected_without_output(self):
        self.approval.unlink()
        with self.assertRaises(c.ContractError):
            self.build()
        self.assertFalse(self.output.exists())

    def test_request_mismatches_and_no_approval(self):
        cases = [("candidateDigest", "0" * 64), ("sourceFingerprint", "0" * 64),
                 ("codeCommit", "0" * 40), ("approval", {"approved": False, "recordId": "test", "approvedAt": "2026-10-29T00:00:00Z"}),
                 ("applicationPeriod", None), ("retrievedAt", None), ("evidenceKind", "unknown")]
        base = copy.deepcopy(self.request)
        for key, value in cases:
            with self.subTest(key=key):
                self.request = {**base, key: value}
                self.save_request()
                with self.assertRaises((c.ContractError, c.v2.V2Error)):
                    self.build()
                self.assertFalse(self.output.exists())

    def test_missing_buffer_and_expired_or_future_period(self):
        periods = [("2026-10-28T00:00:00+09:00", "2026-10-30T00:00:00+09:00"),
                   ("2026-10-29T00:00:00+09:00", "2026-10-31T00:00:00+09:00"),
                   ("2026-10-29T00:00:00+09:00", "2026-10-29T12:00:00Z"),
                   ("2026-10-29T13:00:00Z", "2026-10-30T00:00:00+09:00")]
        for start, end in periods:
            self.request["applicationPeriod"] = {"startsAt": start, "endsAt": end}
            self.save_request()
            with self.assertRaises(c.ContractError):
                self.build()

    def test_independent_rejects_expiry_approval_and_hash_tampering(self):
        self.build()
        with self.assertRaises(c.ContractError):
            self.validate(now=datetime(2026, 10, 30, tzinfo=timezone.utc))
        original = self.public()
        for mutate in (lambda x: x["metadata"].update(retrievedAt="2026-10-27T00:00:00Z"),
                       lambda x: x["metadata"]["quality"]["resolution"]["classes"].update(A=1),
                       lambda x: x.update(schemaVersion=3),
                       lambda x: x["serviceDates"].pop(),
                       lambda x: x["stations"]["Hikawadai"].update(bytes=1)):
            public = copy.deepcopy(original)
            mutate(public)
            self.write_public(public)
            with self.assertRaises((c.ContractError, c.v2.V2Error)):
                self.validate()
        self.write_public(original)
        path = next((self.output / "releases").rglob("*.json"))
        path.write_bytes(path.read_bytes() + b" ")
        with self.assertRaises(c.ContractError):
            self.validate()

    def test_source_or_candidate_corruption(self):
        self.build()
        path = self.source / c.qa.REQUIRED_JSON[0]
        path.write_text("[{}]")
        with self.assertRaises(c.ContractError):
            self.validate()
        path.write_text("[]")
        path = next((self.candidate / "public-candidates").iterdir())
        path.write_bytes(path.read_bytes() + b" ")
        with self.assertRaises(c.ContractError):
            self.validate()

    def test_unknown_schema_and_missing_metadata_rejected(self):
        from test_release_contract import envelopes_and_manifest
        old = envelopes_and_manifest()[2]
        self.assertIs(legacy.validate_versioned_manifest(old), old)
        for value in ({"schemaVersion": 3}, {"schemaVersion": True}, {}):
            with self.assertRaises(legacy.ReleaseContractError):
                legacy.validate_versioned_manifest(value)
        self.build()
        for key in self.public()["metadata"]:
            public = self.public()
            del public["metadata"][key]
            with self.assertRaises(c.ContractError):
                c.validate_manifest(public, NOW)

    def test_warning_originals_and_resolutions_kept_and_unknown_blocked(self):
        odpt = self.manifest["odpt0"]
        odpt["status"] = "WARNING"
        for row in odpt["stationDateResolution"]:
            r = row["resolution"]
            r["classes"]["B"] = 1
            r["unmatched"].update(original=1, resolved=1)
        odpt["resolution"] = c.qa._merge_resolutions(row["resolution"] for row in odpt["stationDateResolution"])
        odpt["unmatchedOdptJourneyCount"] = 24
        self.manifest["quality"]["odptMatchStatusCounts"] = {"unmatched": 24}
        self.save_manifest()
        self.request["candidateDigest"] = c.candidate_digest(self.candidate)
        self.save_request()
        self.build()
        q = self.public()["metadata"]["quality"]
        self.assertEqual((q["status"], q["unmatchedOriginal"], q["resolution"]["unmatched"]["resolved"]), ("WARNING", 24, 24))
        self.assertEqual(q["resolution"]["unmatched"]["unresolved"], 0)
        for category in "CD":
            broken = copy.deepcopy(q)
            broken["resolution"]["classes"][category] = 1
            with self.assertRaises(c.v2.V2Error):
                c.validate_quality(broken, {}, self.dates)

    def test_quality_fail_coverage_missing_station_and_symlink(self):
        for state in ("FAIL", "UNKNOWN"):
            self.manifest["odpt0"]["status"] = state
            self.save_manifest()
            self.request["candidateDigest"] = c.candidate_digest(self.candidate)
            self.save_request()
            with self.assertRaises(c.ContractError):
                self.build()
        self.manifest["odpt0"]["status"] = "PASS"
        self.save_manifest()
        path = self.candidate / "public-candidates" / c.v2.ROUTE_FILENAMES["Hikawadai"]
        payload = c.load_json(path.read_bytes())
        payload["serviceDays"][0]["routeCoverage"]["9"]["dataState"] = "unknown"
        raw = c.canonical(payload)
        path.write_bytes(raw)
        self.manifest["candidateFiles"]["Hikawadai"].update(bytes=len(raw), sha256=c.digest(raw))
        self.save_manifest()
        self.request["candidateDigest"] = c.candidate_digest(self.candidate)
        self.save_request()
        with self.assertRaises(c.v2.V2Error):
            self.build()
        path.unlink()
        with self.assertRaises((c.ContractError, c.v2.V2Error)):
            self.build()
        path.symlink_to(self.source / c.qa.REQUIRED_JSON[0])
        with self.assertRaises((c.ContractError, c.v2.V2Error)):
            self.build()

    def test_original_warning_counts_retained(self):
        odpt = self.manifest["odpt0"]
        odpt["status"] = "WARNING"
        for row in odpt["stationDateResolution"]:
            r = row["resolution"]
            r["classes"]["A"] = 1
            r["unmatched"].update(original=1, resolved=1)
            r["warningCodes"].update(original=2, resolved=2)
        odpt["resolution"] = c.qa._merge_resolutions(row["resolution"] for row in odpt["stationDateResolution"])
        odpt["unmatchedOdptJourneyCount"] = 24
        odpt["diagnosticSeverity"]["WARNING"]["codeOccurrences"] = 48
        self.manifest["quality"]["odptMatchStatusCounts"] = {"unmatched": 24}
        self.save_manifest()
        self.request["candidateDigest"] = c.candidate_digest(self.candidate)
        self.save_request()
        self.build()
        self.assertEqual(self.public()["metadata"]["quality"]["warningOriginal"], 48)
        self.assertEqual(self.validate()["stationCount"], 8)

    def test_recomputed_metadata_hash_still_requires_original_approval(self):
        self.build()
        public = self.public()
        public["metadata"]["approval"]["recordId"] = "different-record"
        public["releaseDescriptor"]["metadataSha256"] = c.digest(c.canonical(public["metadata"]))
        public["releaseId"] = c.release_id(public["releaseDescriptor"])
        for s, name in c.STATION_FILES.items():
            public["stations"][s]["url"] = f"/releases/{public['releaseId']}/{name}"
        self.write_public(public)
        with self.assertRaisesRegex(c.ContractError, "approval_input_mismatch"):
            self.validate()

    def test_file_and_total_limits_extra_files_and_no_overwrite(self):
        with self.assertRaisesRegex(c.ContractError, "path_traversal_rejected"):
            builder.build(candidate=self.candidate, source=self.source, approval=self.approval,
                          output=self.root / "unused" / ".." / "release", now=NOW)
        self.build()
        before = inventory(self.output)
        with self.assertRaisesRegex(c.ContractError, "output_exists"):
            self.build()
        self.assertEqual(before, inventory(self.output))
        with patch.object(c, "MAX_TOTAL_BYTES", 1):
            with self.assertRaisesRegex(c.ContractError, "artifact_oversize"):
                self.validate()
        with patch.object(c, "MAX_FILE_BYTES", 1):
            with self.assertRaisesRegex(c.ContractError, "station_bytes_invalid"):
                self.validate()
        (self.output / "unexpected.json").write_text("{}")
        with self.assertRaisesRegex(c.ContractError, "unexpected_file"):
            self.validate()

    def test_clock_and_source_evidence_cannot_relabel_acquired_as_synthetic(self):
        self.request["evidenceKind"] = "odpt-acquired"
        self.save_request()
        with self.assertRaisesRegex(c.ContractError, "test_clock_requires_synthetic"):
            self.build()
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
