from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from public_payload_profile import project_public_payload  # noqa: E402
import validate_public_artifact  # noqa: E402


LOCAL_FIXTURE = ROOT / "tests" / "fixtures" / "public_payload_profile_input.json"
VALIDATOR = ROOT / "scripts" / "validate_public_artifact.py"
EXPECTED_FILES = {
    "index.html", "styles.css", "preview.css", "preview_public.js", "preview_core.mjs",
    "timetable_adapter.mjs", "local_preview_payload_loader.mjs", "selection.mjs", "terminal_ui.mjs",
    "timetable.json", "timetable-Kanamecho.json", "timetable-Senkawa.json",
    "timetable-KotakeMukaihara.json", "timetable-Heiwadai.json", "timetable-ChikatetsuAkatsuka.json",
    "timetable-ChikatetsuNarimasu.json", "timetable-Wakoshi.json",
}
SOURCES = {
    "index.html": ROOT / "_local_preview" / "public_index.html",
    "styles.css": ROOT / "styles.css",
    "preview.css": ROOT / "_local_preview" / "preview.css",
    "preview_public.js": ROOT / "_local_preview" / "preview_public.js",
    "preview_core.mjs": ROOT / "_local_preview" / "preview_core.mjs",
    "timetable_adapter.mjs": ROOT / "scripts" / "timetable_adapter.mjs",
    "local_preview_payload_loader.mjs": ROOT / "scripts" / "local_preview_payload_loader.mjs",
    "selection.mjs": ROOT / "_local_preview" / "selection.mjs",
    "terminal_ui.mjs": ROOT / "_local_preview" / "terminal_ui.mjs",
}


def make_payload(destination_id: str) -> dict:
    payload = json.loads(LOCAL_FIXTURE.read_text(encoding="utf-8"))
    for day in payload["serviceDays"]:
        day["destinationStationId"] = destination_id
        state = day["destinationStatus"]
        route_counts = {route_id: {"direct": 0, "transfer": 0, "pairs": 0, "transfer_only": 0}
                        for route_id in ("6", "9")}
        for departure in day["departures"]:
            counts = route_counts[departure["routeId"]]
            counts["direct"] += departure["directAlternative"] is not None
            counts["transfer"] += departure["bestTransferAlternative"] is not None
            counts["pairs"] += departure["transferCandidateCount"]
            counts["transfer_only"] += (departure["directAlternative"] is None
                                         and departure["bestTransferAlternative"] is not None)
            for key in ("primary", "directAlternative", "bestTransferAlternative"):
                journey = departure[key]
                if journey is not None:
                    journey["arrivalStationId"] = destination_id
        state.update({
            "directCandidateCount": sum(value["direct"] for value in route_counts.values()),
            "transferCandidateCount": sum(value["transfer"] for value in route_counts.values()),
            "transferPairCount": sum(value["pairs"] for value in route_counts.values()),
            "transferOnlyCount": sum(value["transfer_only"] for value in route_counts.values()),
            "transferPassThroughCount": 0,
            "transferDataInsufficientCount": 0,
        })
        for route_id, counts in state["routes"].items():
            metrics = route_counts[route_id]
            counts.update({
                "directCandidateCount": metrics["direct"],
                "transferCandidateCount": metrics["transfer"],
                "transferPairCount": metrics["pairs"],
                "transferOnlyCount": metrics["transfer_only"],
            })

    today = next(day for day in payload["serviceDays"] if day["serviceDate"] == "2026-10-26")
    previous = deepcopy(today)
    previous["serviceDate"] = "2026-10-25"
    for departure in today["departures"]:
        departure["departureServiceSeconds"] = 79_200
        departure["departureText"] = "22:00:00"
        for key in ("primary", "directAlternative", "bestTransferAlternative"):
            journey = departure[key]
            if journey is None:
                continue
            journey["departureServiceSeconds"] = 79_200
            if journey["arrivalServiceSeconds"] is not None:
                offset = 1_200 if journey["kind"] == "transfer" else 600
                journey["arrivalServiceSeconds"] = 79_200 + offset
                journey["arrivalText"] = "22:20:00" if offset == 1_200 else "22:10:00"
    payload["serviceDays"] = [previous, *payload["serviceDays"]]
    return project_public_payload(payload)


class PublicArtifactValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp(prefix="public-artifact-validation-")).resolve()
        self.addCleanup(shutil.rmtree, self.temp, True)
        self.site = self.temp / "site"
        self.site.mkdir()
        self._write_valid_site(self.site)

    def _write_valid_site(self, directory: Path):
        for filename, source in SOURCES.items():
            shutil.copyfile(source, directory / filename)
        for destination_id, filename in validate_public_artifact.STATION_FILES.items():
            (directory / filename).write_text(json.dumps(make_payload(destination_id), ensure_ascii=False), encoding="utf-8")

    def _copy_site(self, name: str = "mutated") -> Path:
        target = self.temp / name
        shutil.copytree(self.site, target)
        return target

    def _run_validator(self, target: Path):
        return subprocess.run([sys.executable, "-B", str(VALIDATOR), str(target)],
                              capture_output=True, text=True, timeout=30)

    def _assert_rejected(self, target: Path, expected: str):
        result = self._run_validator(target)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(expected, result.stderr)

    def test_valid_artifact_passes_read_only_and_is_independent_of_builder(self):
        before = {path.name: path.read_bytes() for path in self.site.iterdir()}
        result = self._run_validator(self.site)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("17 files, 8 stations", result.stdout)
        self.assertIn("2026-10-25, 2026-10-26, 2026-10-27", result.stdout)
        self.assertEqual({path.name: path.read_bytes() for path in self.site.iterdir()}, before)
        source = VALIDATOR.read_text(encoding="utf-8")
        self.assertNotIn("build_public_site", source)

    def test_missing_and_unexpected_files_are_rejected(self):
        target = self._copy_site("missing")
        (target / "preview.css").unlink()
        self._assert_rejected(target, "required artifact files are missing")

        target = self._copy_site("extra")
        (target / "unlisted.txt").write_text("unexpected", encoding="utf-8")
        self._assert_rejected(target, "unexpected artifact file")

    def test_broken_json_scope_service_date_and_station_mismatch_are_rejected(self):
        target = self._copy_site("broken-json")
        (target / "timetable.json").write_text("{broken", encoding="utf-8")
        self._assert_rejected(target, "invalid JSON")

        target = self._copy_site("bad-profile")
        path = target / "timetable.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["dataScope"] = "local-preview-only"
        path.write_text(json.dumps(payload), encoding="utf-8")
        self._assert_rejected(target, "not public-display-v1")

        target = self._copy_site("bad-date")
        path = target / "timetable-Wakoshi.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["serviceDays"][0]["serviceDate"] = "2026-10-24"
        path.write_text(json.dumps(payload), encoding="utf-8")
        self._assert_rejected(target, "serviceDate lists do not match")

        target = self._copy_site("bad-station")
        path = target / "timetable.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        for day in payload["serviceDays"]:
            day["destinationStationId"] = "Wakoshi"
            for departure in day["departures"]:
                for key in ("primary", "directAlternative", "bestTransferAlternative"):
                    if departure[key] is not None:
                        departure[key]["arrivalStationId"] = "Wakoshi"
        path.write_text(json.dumps(payload), encoding="utf-8")
        self._assert_rejected(target, "origin/destination does not match")

    def test_missing_import_diagnostic_module_and_secret_sentinel_are_rejected(self):
        target = self._copy_site("missing-import")
        path = target / "preview_core.mjs"
        path.write_text(path.read_text(encoding="utf-8").replace("./terminal_ui.mjs", "./missing.mjs"), encoding="utf-8")
        self._assert_rejected(target, "escapes the public module allowlist")

        target = self._copy_site("wrong-payload-ref")
        path = target / "local_preview_payload_loader.mjs"
        path.write_text(path.read_text(encoding="utf-8").replace(
            "./timetable-Kanamecho.json", "./timetable-Missing.json"), encoding="utf-8")
        self._assert_rejected(target, "payload references do not match")

        target = self._copy_site("diagnostic")
        path = target / "preview_core.mjs"
        path.write_text(path.read_text(encoding="utf-8") + "\nimport './virtual_now.mjs';\n", encoding="utf-8")
        self._assert_rejected(target, "local diagnostic code")

        target = self._copy_site("perf-parameter")
        path = target / "preview_public.js"
        path.write_text(path.read_text(encoding="utf-8") + "\n// perf=1\n", encoding="utf-8")
        self._assert_rejected(target, "local diagnostic code")

        target = self._copy_site("qa-metadata")
        path = target / "timetable.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["qaTargetDate"] = "2026-10-27"
        path.write_text(json.dumps(payload), encoding="utf-8")
        self._assert_rejected(target, "schema and allowlist checks")

        target = self._copy_site("secret")
        path = target / "preview.css"
        path.write_text(path.read_text(encoding="utf-8") + "\n/* SYNTHETIC_API_KEY_SENTINEL=never-log-this-value */\n", encoding="utf-8")
        result = self._run_validator(target)
        self.assertEqual(result.returncode, 1)
        self.assertIn("secret sentinel", result.stderr)
        self.assertNotIn("never-log-this-value", result.stderr)

        target = self._copy_site("api-key-like")
        path = target / "preview.css"
        path.write_text(path.read_text(encoding="utf-8") + "\n/* apiKey=synthetic-fake-value-123 */\n", encoding="utf-8")
        self._assert_rejected(target, "credential-like content")

    def test_symlink_and_mock_root_shell_are_rejected(self):
        target = self._copy_site("symlink")
        outside = self.temp / "outside.txt"
        outside.write_text("safe synthetic content", encoding="utf-8")
        (target / "styles.css").unlink()
        (target / "styles.css").symlink_to(outside)
        self._assert_rejected(target, "contains a symlink")

        target = self._copy_site("root-mock")
        shutil.copyfile(ROOT / "index.html", target / "index.html")
        self._assert_rejected(target, "HTML must load only preview_public.js")

    def test_missing_public_dom_and_changed_public_scope_definition_are_rejected(self):
        target = self._copy_site("missing-dom")
        path = target / "index.html"
        path.write_text(path.read_text(encoding="utf-8").replace('id="board"', 'class="board"'), encoding="utf-8")
        self._assert_rejected(target, "missing required runtime DOM")

        target = self._copy_site("wrong-scope-constant")
        path = target / "timetable_adapter.mjs"
        path.write_text(path.read_text(encoding="utf-8").replace(
            "PUBLIC_DATA_SCOPE = 'public-display-v1'", "PUBLIC_DATA_SCOPE = 'local-preview-only'"), encoding="utf-8")
        self._assert_rejected(target, "does not define the public payload profile")

    def test_diagnostic_dom_css_and_absolute_path_are_rejected(self):
        target = self._copy_site("diagnostic-dom")
        path = target / "index.html"
        path.write_text(path.read_text(encoding="utf-8").replace("</main>",
            '<section id="performance-panel"></section></main>'), encoding="utf-8")
        self._assert_rejected(target, "local diagnostic")

        target = self._copy_site("absolute-path")
        path = target / "preview.css"
        path.write_text(path.read_text(encoding="utf-8") + "\n/* /Users/synthetic/private */\n", encoding="utf-8")
        self._assert_rejected(target, "absolute path")

    def test_symlinked_artifact_root_is_rejected(self):
        link = self.temp / "site-link"
        link.symlink_to(self.site, target_is_directory=True)
        result = self._run_validator(link)
        self.assertEqual(result.returncode, 1)
        self.assertIn("symlink", result.stderr)


if __name__ == "__main__":
    unittest.main()
