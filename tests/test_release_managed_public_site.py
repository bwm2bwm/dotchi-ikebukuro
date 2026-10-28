from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_public_site  # noqa: E402
import release_contract  # noqa: E402
import validate_public_artifact  # noqa: E402
from synthetic_public_fixture_factory import make_public_fixture, STATION_FILES  # noqa: E402


DAYS = ["2026-10-26", "2026-10-27", "2026-10-28"]


def tree_bytes(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob("*") if path.is_file()}


class ReleaseManagedPublicSiteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="release-managed-public-site-")
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.fixtures = base / "fixtures"
        self.fixtures.mkdir()
        (self.fixtures / build_public_site.SYNTHETIC_MARKER).write_text(
            build_public_site.SYNTHETIC_MARKER_CONTENT, encoding="utf-8")
        self.output = base / "out" / "site"
        self.output.parent.mkdir()
        self._write_fixtures()

    def _write_fixtures(self):
        for station_id, filename in STATION_FILES.items():
            payload = make_public_fixture(station_id, DAYS)
            (self.fixtures / filename).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def _build(self, **kwargs):
        return build_public_site.build_public_site(fixtures=self.fixtures, output=self.output,
                                                   release_managed=True, **kwargs)

    def _validate(self):
        return validate_public_artifact.validate_release_managed_artifact(self.output.resolve())

    def test_opt_in_build_has_manifest_envelopes_and_independent_validation(self):
        result = self._build()
        manifest = json.loads((self.output / "manifest.json").read_text(encoding="utf-8"))
        self.assertTrue(result["release_managed"])
        self.assertEqual(result["files"], sorted(result["files"]))
        self.assertEqual(len(result["files"]), 18)
        self.assertEqual(len(manifest["stations"]), 8)
        self.assertIsNone(manifest["publishedAt"], "local artifact is not a published deployment")
        self.assertEqual(manifest["releaseId"], release_contract.calculate_release_id(manifest["releaseDescriptor"]))
        for station_id, filename in STATION_FILES.items():
            record = manifest["stations"][station_id]
            envelope_path = self.output / record["url"].lstrip("/")
            envelope = json.loads(envelope_path.read_text(encoding="utf-8"))
            self.assertEqual(envelope["releaseId"], manifest["releaseId"])
            self.assertEqual(envelope["stationId"], station_id)
            self.assertEqual(envelope["payload"]["dataScope"], "public-display-v1")
            self.assertEqual(record["bytes"], envelope_path.stat().st_size)
            self.assertEqual(record["sha256"], release_contract.sha256_hex(envelope_path.read_bytes()))
        result = self._validate()
        self.assertEqual(result["release_id"], manifest["releaseId"])
        self.assertEqual(result["files"], 18)

    def test_same_input_produces_identical_release_manifest_station_bytes_and_tree(self):
        self._build()
        first = tree_bytes(self.output)
        first_manifest = first["manifest.json"]
        first_release = json.loads(first_manifest)["releaseId"]
        self._build()
        second = tree_bytes(self.output)
        self.assertEqual(first, second)
        self.assertEqual(json.loads(first_manifest)["releaseId"], json.loads(second["manifest.json"])["releaseId"])
        self.assertEqual(sum(name.startswith(f"releases/{first_release}/") for name in first), 8)

    def test_single_station_payload_change_changes_release_id(self):
        self._build()
        initial_id = json.loads((self.output / "manifest.json").read_text())["releaseId"]
        payload_file = self.fixtures / STATION_FILES["Hikawadai"]
        payload = json.loads(payload_file.read_text(encoding="utf-8"))
        payload["webApp"]["builtAt"] = "2026-10-28T09:00:00+09:00"
        payload_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        self._build()
        changed_id = json.loads((self.output / "manifest.json").read_text())["releaseId"]
        self.assertNotEqual(initial_id, changed_id)

    def test_asset_and_builder_contract_changes_change_release_id(self):
        self._build()
        first_id = json.loads((self.output / "manifest.json").read_text())["releaseId"]
        custom_css = Path(self.temp.name) / "custom.css"
        custom_css.write_bytes((ROOT / "styles.css").read_bytes() + b"\n/* synthetic asset variant */\n")
        with patch.dict(build_public_site.SOURCE_FILES, {"styles.css": custom_css}):
            self._build()
        asset_id = json.loads((self.output / "manifest.json").read_text())["releaseId"]
        self.assertNotEqual(first_id, asset_id)
        with patch.object(build_public_site, "BUILDER_CONTRACT_VERSION", "dotchi-public-builder-test-v2"):
            self._build()
        contract_id = json.loads((self.output / "manifest.json").read_text())["releaseId"]
        self.assertNotEqual(asset_id, contract_id)

    def test_validator_rejects_manifest_json_and_hash_byte_tampering(self):
        self._build()
        manifest_path = self.output / "manifest.json"
        original_manifest = manifest_path.read_bytes()
        manifest = json.loads(original_manifest)
        manifest["runtimeContract"] = "unknown-runtime"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaises(validate_public_artifact.ArtifactValidationError):
            self._validate()
        manifest_path.write_bytes(original_manifest)

        current = json.loads(original_manifest)
        json_path = self.output / current["stations"]["Hikawadai"]["url"].lstrip("/")
        original_json = json_path.read_bytes()
        json_path.write_bytes(original_json[:-1])
        with self.assertRaisesRegex(validate_public_artifact.ArtifactValidationError, "hash"):
            self._validate()
        json_path.write_bytes(original_json)

        current["stations"]["Hikawadai"]["bytes"] += 1
        manifest_path.write_bytes(release_contract.encode_manifest(current))
        with self.assertRaises(validate_public_artifact.ArtifactValidationError):
            self._validate()

    def test_validator_recomputes_release_id_and_rejects_asset_or_extra_file(self):
        self._build()
        manifest_path = self.output / "manifest.json"
        original = manifest_path.read_bytes()
        altered = json.loads(original)
        altered["releaseId"] = "r1-" + "b" * 64
        manifest_path.write_text(json.dumps(altered), encoding="utf-8")
        with self.assertRaises(validate_public_artifact.ArtifactValidationError):
            self._validate()
        manifest_path.write_bytes(original)

        css = self.output / "styles.css"
        old_css = css.read_bytes()
        css.write_bytes(old_css + b"\n/* altered */\n")
        with self.assertRaisesRegex(validate_public_artifact.ArtifactValidationError, "asset hash"):
            self._validate()
        css.write_bytes(old_css)

        (self.output / "unexpected.txt").write_text("unexpected", encoding="utf-8")
        with self.assertRaisesRegex(validate_public_artifact.ArtifactValidationError, "file set"):
            self._validate()

    def test_validator_rejects_bad_path_missing_station_and_wrong_station_id(self):
        self._build()
        manifest_path = self.output / "manifest.json"
        original = json.loads(manifest_path.read_bytes())
        changed = deepcopy(original)
        changed["stations"]["Wakoshi"]["url"] = "https://example.invalid/data.json"
        manifest_path.write_text(json.dumps(changed), encoding="utf-8")
        with self.assertRaises(validate_public_artifact.ArtifactValidationError):
            self._validate()
        manifest_path.write_bytes(release_contract.encode_manifest(original))

        station_path = self.output / original["stations"]["Wakoshi"]["url"].lstrip("/")
        station_path.unlink()
        with self.assertRaises(validate_public_artifact.ArtifactValidationError):
            self._validate()
        self._build()

        original = json.loads(manifest_path.read_bytes())
        station_path = self.output / original["stations"]["Hikawadai"]["url"].lstrip("/")
        envelope = json.loads(station_path.read_bytes())
        envelope["stationId"] = "Senkawa"
        raw = release_contract.canonicalize_jcs(envelope)
        station_path.write_bytes(raw)
        original["stations"]["Hikawadai"]["sha256"] = release_contract.sha256_hex(raw)
        original["stations"]["Hikawadai"]["bytes"] = len(raw)
        manifest_path.write_bytes(release_contract.encode_manifest(original))
        with self.assertRaises(validate_public_artifact.ArtifactValidationError):
            self._validate()

    def test_validator_rejects_invalid_inner_payload_and_station_metadata_mixing(self):
        self._build()
        manifest_path = self.output / "manifest.json"
        manifest = json.loads(manifest_path.read_bytes())
        station_path = self.output / manifest["stations"]["Hikawadai"]["url"].lstrip("/")
        envelope = json.loads(station_path.read_bytes())
        envelope["payload"]["schemaVersion"] = 2
        raw = release_contract.canonicalize_jcs(envelope)
        station_path.write_bytes(raw)
        manifest["stations"]["Hikawadai"].update(sha256=release_contract.sha256_hex(raw), bytes=len(raw))
        manifest_path.write_bytes(release_contract.encode_manifest(manifest))
        with self.assertRaises(validate_public_artifact.ArtifactValidationError):
            self._validate()

        self._build()
        manifest = json.loads(manifest_path.read_bytes())
        station_path = self.output / manifest["stations"]["Hikawadai"]["url"].lstrip("/")
        envelope = json.loads(station_path.read_bytes())
        envelope["payload"]["feed"]["version"] = "mixed-generation"
        raw = release_contract.canonicalize_jcs(envelope)
        station_path.write_bytes(raw)
        manifest["stations"]["Hikawadai"].update(sha256=release_contract.sha256_hex(raw), bytes=len(raw))
        manifest_path.write_bytes(release_contract.encode_manifest(manifest))
        with self.assertRaisesRegex(validate_public_artifact.ArtifactValidationError, "metadata"):
            self._validate()

    def test_default_builder_and_legacy_validator_still_use_exact_17_file_form(self):
        legacy = Path(self.temp.name) / "legacy"
        result = build_public_site.build_public_site(fixtures=self.fixtures, output=legacy)
        self.assertFalse(result["release_managed"])
        self.assertEqual(len(list(legacy.iterdir())), 17)
        self.assertEqual(validate_public_artifact.validate_artifact(legacy.resolve())["files"], 17)


if __name__ == "__main__":
    unittest.main()
