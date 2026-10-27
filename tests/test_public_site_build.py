from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_public_site  # noqa: E402
from synthetic_public_fixture_factory import make_public_fixture as _make_public_fixture  # noqa: E402


def make_public_fixture(destination_id: str) -> dict:
    return _make_public_fixture(destination_id, ["2026-10-26", "2026-10-27"])


class PublicSiteBuildTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="synthetic-public-site-")
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.fixtures = base / "fixtures"
        self.fixtures.mkdir()
        (self.fixtures / build_public_site.SYNTHETIC_MARKER).write_text(
            build_public_site.SYNTHETIC_MARKER_CONTENT, encoding="utf-8")
        self.output = base / "output" / "site"
        self.output.parent.mkdir()
        self._write_fixtures()

    def _write_fixtures(self):
        for destination_id, filename in build_public_site.PAYLOAD_FILENAMES.items():
            payload = make_public_fixture(destination_id)
            (self.fixtures / filename).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def test_build_creates_complete_allowlisted_site_from_synthetic_payloads(self):
        root_index_before = (ROOT / "index.html").read_bytes()
        root_css_before = (ROOT / "styles.css").read_bytes()
        local_html_before = (ROOT / "_local_preview" / "index.html").read_bytes()

        result = build_public_site.build_public_site(fixtures=self.fixtures, output=self.output)

        self.assertEqual(result["payload_count"], 8)
        self.assertEqual(result["service_dates"], ["2026-10-26", "2026-10-27"])
        self.assertEqual({path.name for path in self.output.iterdir()}, build_public_site.ARTIFACT_FILENAMES)
        html = (self.output / "index.html").read_text(encoding="utf-8")
        self.assertIn('src="preview_public.js"', html)
        self.assertNotIn("preview_diagnostics.css", html)
        self.assertNotIn("debugNow", html)
        self.assertNotIn("performance-", html)
        self.assertIn("AD 320×50", html)
        public_entry = (self.output / "preview_public.js").read_text(encoding="utf-8")
        self.assertIn("expectedProfile: PUBLIC_DATA_SCOPE", public_entry)
        self.assertIn("PUBLIC_DATA_SCOPE = 'public-display-v1'", (self.output / "timetable_adapter.mjs").read_text(encoding="utf-8"))
        self.assertIn("cacheMode: 'default'", public_entry)
        self.assertEqual((ROOT / "index.html").read_bytes(), root_index_before)
        self.assertEqual((ROOT / "styles.css").read_bytes(), root_css_before)
        self.assertEqual((ROOT / "_local_preview" / "index.html").read_bytes(), local_html_before)
        self.assertFalse({"preview.js", "virtual_now.mjs", "performance_metrics.mjs", "preview_diagnostics.css",
                          "validate_payload.mjs"} & {path.name for path in self.output.iterdir()})

    def test_import_graph_rejects_diagnostic_or_unallowlisted_dependency(self):
        build_public_site.build_public_site(fixtures=self.fixtures, output=self.output)
        (self.output / "preview_core.mjs").write_text("import './virtual_now.mjs';\n", encoding="utf-8")
        with self.assertRaisesRegex(build_public_site.PublicSiteBuildError, "import escapes public allowlist"):
            build_public_site._validate_import_graph(self.output)

    def test_payload_errors_and_incomplete_fixture_set_fail_before_output_swap(self):
        self.output.mkdir()
        (self.output / "old.marker").write_text("keep", encoding="utf-8")
        cases = [
            ("scope", lambda p: p.update(dataScope="local-preview-only"), "public-display-v1"),
            ("unknown field", lambda p: p.update(apiKey="synthetic-secret-sentinel"), "unknown field"),
            ("destination mismatch", lambda p: p["serviceDays"][0].update(destinationStationId="Wakoshi"),
             "must match destinationStationId"),
            ("date mismatch", lambda p: p["serviceDays"][0].update(serviceDate="2026-10-25"),
             "serviceDate list differs"),
        ]
        filename = build_public_site.PAYLOAD_FILENAMES["Hikawadai"]
        original = (self.fixtures / filename).read_text(encoding="utf-8")
        for _, mutate, expected in cases:
            payload = json.loads(original)
            mutate(payload)
            (self.fixtures / filename).write_text(json.dumps(payload), encoding="utf-8")
            with self.subTest(expected=expected), self.assertRaisesRegex(build_public_site.PublicSiteBuildError, expected):
                build_public_site.build_public_site(fixtures=self.fixtures, output=self.output)
            self.assertEqual((self.output / "old.marker").read_text(encoding="utf-8"), "keep")
            (self.fixtures / filename).write_text(original, encoding="utf-8")

        (self.fixtures / build_public_site.PAYLOAD_FILENAMES["Wakoshi"]).unlink()
        with self.assertRaisesRegex(build_public_site.PublicSiteBuildError, "exactly eight"):
            build_public_site.build_public_site(fixtures=self.fixtures, output=self.output)
        self.assertEqual((self.output / "old.marker").read_text(encoding="utf-8"), "keep")

    def test_broken_json_and_duplicate_keys_are_rejected(self):
        path = self.fixtures / build_public_site.PAYLOAD_FILENAMES["Wakoshi"]
        path.write_text("{\"schemaVersion\":1,\"schemaVersion\":1}", encoding="utf-8")
        with self.assertRaisesRegex(build_public_site.PublicSiteBuildError, "duplicate JSON key"):
            build_public_site.build_public_site(fixtures=self.fixtures, output=self.output)

        path.write_text("{broken", encoding="utf-8")
        with self.assertRaisesRegex(build_public_site.PublicSiteBuildError, "invalid JSON"):
            build_public_site.build_public_site(fixtures=self.fixtures, output=self.output)

    def test_staged_artifact_validation_failure_keeps_previous_output(self):
        self.output.mkdir()
        (self.output / "old.marker").write_text("keep", encoding="utf-8")
        with patch.object(build_public_site, "_validate_artifacts",
                          side_effect=build_public_site.PublicSiteBuildError("synthetic staged rejection")):
            with self.assertRaisesRegex(build_public_site.PublicSiteBuildError, "staged rejection"):
                build_public_site.build_public_site(fixtures=self.fixtures, output=self.output)
        self.assertEqual((self.output / "old.marker").read_text(encoding="utf-8"), "keep")
        self.assertEqual({path.name for path in self.output.iterdir()}, {"old.marker"})

    def test_output_cannot_target_repository_root_or_private_fixture_tree(self):
        with self.assertRaisesRegex(build_public_site.PublicSiteBuildError, "outside the repository"):
            build_public_site.build_public_site(fixtures=self.fixtures, output=ROOT / "index.html")
        with self.assertRaisesRegex(build_public_site.PublicSiteBuildError, "must not overlap"):
            build_public_site.build_public_site(fixtures=self.fixtures, output=self.fixtures / "site")


if __name__ == "__main__":
    unittest.main()
