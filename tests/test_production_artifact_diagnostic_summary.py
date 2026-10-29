from __future__ import annotations

from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_public_site import build_public_site  # noqa: E402
from assemble_public_release import assemble_public_artifact  # noqa: E402
from release_contract import STATION_FILES  # noqa: E402
from summarize_production_artifact_snapshot import (  # noqa: E402
    SnapshotSummaryError,
    render_summary,
)
from synthetic_public_fixture_factory import generate_fixture_directory  # noqa: E402
from validate_public_artifact import validate_release_managed_artifact  # noqa: E402


class ProductionArtifactDiagnosticSummaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="production-summary-fixtures-", dir="/private/tmp")
        cls.base = Path(cls.temp.name)
        old_fixtures = cls.base / "fixtures-old"
        generate_fixture_directory(old_fixtures, date(2026, 10, 27))
        legacy = cls.base / "legacy"
        build_public_site(fixtures=old_fixtures, output=legacy)
        release_a = cls.base / "release-a"
        build_public_site(fixtures=old_fixtures, output=release_a, release_managed=True)
        initial_migration = cls.base / "initial-migration"
        assemble_public_artifact(previous=legacy, new_release=release_a,
            output=initial_migration, evaluated_at="2026-10-27T12:00:00+09:00")

        new_fixtures = cls.base / "fixtures-new"
        generate_fixture_directory(new_fixtures, date(2026, 10, 28))
        release_b = cls.base / "release-b"
        build_public_site(fixtures=new_fixtures, output=release_b, release_managed=True)
        cls.snapshot = cls.base / "snapshot"
        assemble_public_artifact(previous=initial_migration, new_release=release_b,
            output=cls.snapshot, evaluated_at="2026-10-28T12:00:00+09:00")
        validation = validate_release_managed_artifact(cls.snapshot)
        manifest = json.loads((cls.snapshot / "manifest.json").read_text(encoding="utf-8"))
        all_files = [path for path in cls.snapshot.rglob("*") if path.is_file()]
        cls.fetch_result = {
            "files": len(all_files),
            "total_bytes": sum(path.stat().st_size for path in all_files),
            "largest_file_bytes": max(path.stat().st_size for path in all_files),
            "mode": "release-managed",
            "fingerprint": "a" * 64,
            "release_id": manifest["releaseId"],
            "retained_releases": len(manifest["retainedReleases"]),
            "legacy_compatibility": manifest["legacyCompatibilityV1"] is not None,
            "files_validated": validation["files"],
            "manifest_classification": "release-managed",
            "fingerprint_verified": True,
        }

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def isolated_snapshot(self, name: str) -> Path:
        destination = self.base / name
        shutil.copytree(self.snapshot, destination)
        return destination

    def test_success_summary_reports_retention_legacy_and_all_current_station_hashes(self):
        summary = render_summary(self.snapshot, self.fetch_result)
        manifest = json.loads((self.snapshot / "manifest.json").read_text(encoding="utf-8"))
        self.assertIn("diagnostic_result: **PASS**", summary)
        self.assertIn("manifest_classification: `release-managed`", summary)
        self.assertIn(f"current releaseId: `{manifest['releaseId']}`", summary)
        self.assertIn("independent_validator: **PASS**", summary)
        self.assertIn("legacyCompatibilityV1: **present**", summary)
        self.assertIn(manifest["legacyCompatibilityV1"]["expiresAt"], summary)
        for retained in manifest["retainedReleases"]:
            self.assertIn(retained["releaseId"], summary)
            self.assertIn(retained["retainUntil"], summary)
        for station_id, filename in STATION_FILES.items():
            station = manifest["stations"][station_id]
            self.assertIn(filename, summary)
            self.assertIn(str(station["bytes"]), summary)
            self.assertIn(station["sha256"], summary)

    def test_legacy_fetch_result_is_rejected(self):
        legacy_result = deepcopy(self.fetch_result)
        legacy_result.update(mode="legacy", manifest_classification="http_404", release_id=None)
        with self.assertRaises(SnapshotSummaryError):
            render_summary(self.snapshot, legacy_result)

    def test_invalid_manifest_is_rejected_without_summary(self):
        snapshot = self.isolated_snapshot("invalid-manifest")
        manifest_path = snapshot / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["releaseId"] = "r1-" + "b" * 64 + "\n| injected |"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaises(SnapshotSummaryError):
            render_summary(snapshot, self.fetch_result)

    def test_missing_current_station_file_is_rejected(self):
        snapshot = self.isolated_snapshot("missing-station")
        manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
        filename = manifest["stations"]["Wakoshi"]["url"].rsplit("/", 1)[-1]
        (snapshot / "releases" / manifest["releaseId"] / filename).unlink()
        with self.assertRaises(SnapshotSummaryError):
            render_summary(snapshot, self.fetch_result)

    def test_summary_contains_no_secret_or_payload_body_and_rejects_markdown_injection(self):
        summary = render_summary(self.snapshot, self.fetch_result)
        current_json = self.snapshot / "releases" / self.fetch_result["release_id"] / STATION_FILES["Wakoshi"]
        payload_text = current_json.read_text(encoding="utf-8")
        self.assertNotIn('"payload"', summary)
        self.assertNotIn("synthetic-trip:", summary)
        self.assertNotIn("CF_ACCESS_CLIENT_SECRET_TEST_SENTINEL", summary)
        self.assertNotIn(payload_text, summary)

        injected_result = deepcopy(self.fetch_result)
        injected_result["release_id"] = "r1-" + "c" * 64 + "\n- injected metadata"
        with self.assertRaises(SnapshotSummaryError):
            render_summary(self.snapshot, injected_result)


if __name__ == "__main__":
    unittest.main()
