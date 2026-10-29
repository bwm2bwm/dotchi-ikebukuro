from __future__ import annotations

import hashlib
from http.server import ThreadingHTTPServer
import os
from pathlib import Path
import socket
import stat
import sys
import tempfile
from threading import Thread
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
import odpt_public_v2 as v2  # noqa: E402
import build_public_site  # noqa: E402
import prepare_odpt_v2_qa as prepare  # noqa: E402
import serve_odpt_v2_qa as serve  # noqa: E402
from test_odpt_public_v2 import _bundle  # noqa: E402


class PrepareOdptV2QaTests(unittest.TestCase):
    def test_prepares_private_site_without_manifest_and_preserves_source(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as directory:
            root = Path(directory)
            bundle, manifest, dates = _bundle(root / "bundle")
            before = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                      for path in bundle.rglob("*") if path.is_file()}
            output = root / "private-qa" / "site"
            result = prepare.prepare(bundle, "2026-10-29", output)
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["serviceDates"], dates)
            self.assertEqual(result["candidateCount"], 24)
            self.assertEqual(result["manifestCopied"], False)
            self.assertEqual(len(list(output.iterdir())), result["fileCount"])
            self.assertFalse((output / "private-generator-manifest.json").exists())
            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o700)
            self.assertTrue(all(stat.S_IMODE(path.stat().st_mode) == 0o600
                                for path in output.iterdir()))
            self.assertEqual({path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                              for path in bundle.rglob("*") if path.is_file()}, before)
            qa_state = __import__("json").loads((output / prepare.STATE_FILENAME).read_text())
            self.assertEqual(qa_state["stations"]["Hikawadai"]["2026-10-28"]["noValidArrivalCount"], 0)
            site, files = serve.validate_site(output)
            self.assertEqual(site, output.resolve())
            self.assertNotIn("private-generator-manifest.json", files)
            self.assertEqual(set(files), serve.STATIC_NAMES)

    def test_rejects_existing_output_repository_output_and_bad_service_date(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as directory:
            root = Path(directory)
            bundle, _, _ = _bundle(root / "bundle")
            output = root / "qa"
            prepare.prepare(bundle, "2026-10-29", output)
            with self.assertRaisesRegex(prepare.PrepareError, "output_already_exists"):
                prepare.prepare(bundle, "2026-10-29", output)
            with self.assertRaisesRegex(prepare.PrepareError, "repository_path_rejected"):
                prepare.prepare(bundle, "2026-10-29", ROOT / "qa-output")
            with self.assertRaisesRegex(prepare.PrepareError, "service_date_invalid"):
                prepare.prepare(bundle, "2026-02-30", root / "other")

    def test_rejects_symlinked_source_and_output_paths(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as directory:
            root = Path(directory)
            bundle, _, _ = _bundle(root / "bundle")
            alias = root / "bundle-alias"
            alias.symlink_to(bundle, target_is_directory=True)
            with self.assertRaisesRegex(prepare.PrepareError, "symlink_path_rejected"):
                prepare.prepare(alias, "2026-10-29", root / "qa")
            target = root / "somewhere"
            target.mkdir()
            output_alias = root / "qa-link"
            output_alias.symlink_to(target, target_is_directory=True)
            with self.assertRaisesRegex(prepare.PrepareError, "symlink_path_rejected"):
                prepare.prepare(bundle, "2026-10-29", output_alias / "site")

    def test_rejects_candidate_tampering_before_staging(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as directory:
            root = Path(directory)
            bundle, _, _ = _bundle(root / "bundle")
            candidate = bundle / "public-candidates" / v2.ROUTE_FILENAMES["Hikawadai"]
            candidate.write_text("{}", encoding="utf-8")
            with self.assertRaises(prepare.PrepareError):
                prepare.prepare(bundle, "2026-10-29", root / "qa")
            self.assertFalse((root / "qa").exists())

    def test_local_server_serves_only_allowlisted_files_and_rejects_other_host_header(self):
        self.assertEqual(serve.HOST, "127.0.0.1")
        with tempfile.TemporaryDirectory(dir="/private/tmp") as directory:
            root = Path(directory)
            bundle, _, _ = _bundle(root / "bundle")
            output = root / "private-qa" / "site"
            prepare.prepare(bundle, "2026-10-29", output)
            _, files = serve.validate_site(output)
            with socket.socket() as probe:
                probe.bind((serve.HOST, 0))
                port = probe.getsockname()[1]
            server = ThreadingHTTPServer((serve.HOST, port), serve.make_handler(files, port))
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://{serve.HOST}:{server.server_port}"
            try:
                with urlopen(base + "/odpt_v2_qa.html") as response:
                    self.assertEqual(response.status, 200)
                    self.assertIn("実ODPT候補".encode(), response.read())
                    self.assertEqual(response.headers.get("Cache-Control"), "no-store")
                    self.assertIsNone(response.headers.get("Access-Control-Allow-Origin"))
                with self.assertRaises(HTTPError) as error:
                    urlopen(Request(base + "/private-generator-manifest.json",
                                    headers={"Host": f"example.invalid:{server.server_port}"}))
                self.assertEqual(error.exception.code, 400)
                error.exception.close()
                with self.assertRaises(HTTPError) as missing:
                    urlopen(base + "/unexpected.json")
                self.assertEqual(missing.exception.code, 404)
                missing.exception.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_qa_files_are_not_referenced_by_public_entry_or_builder_allowlist(self):
        qa_only = {"odpt_v2_qa.html", "odpt_v2_qa.css", "preview_odpt_v2_qa.mjs",
                   "odpt_v2_qa_adapter.mjs", "_odpt_v2_qa_state.json"}
        self.assertTrue(qa_only.isdisjoint(build_public_site.SOURCE_FILES))
        public_html = (ROOT / "_local_preview" / "public_index.html").read_text(encoding="utf-8")
        public_bootstrap = (ROOT / "_local_preview" / "preview_public.js").read_text(encoding="utf-8")
        for marker in qa_only - {"_odpt_v2_qa_state.json"}:
            self.assertNotIn(marker, public_html)
            self.assertNotIn(marker, public_bootstrap)

    def test_destination_switch_clears_old_cards_before_request_and_on_failure(self):
        entry = (ROOT / "_local_preview" / "preview_odpt_v2_qa.mjs").read_text(encoding="utf-8")
        start = entry.index("async function loadSelectedStation()")
        end = entry.index("\nfunction updateClockInput()", start)
        body = entry[start:end]
        self.assertLess(body.index("selectedPayload = null"), body.index("await loadStation("))
        self.assertLess(body.index("elements.board.replaceChildren()"), body.index("await loadStation("))
        error_path = body[body.index("} catch (error) {"):]
        self.assertIn("selectedPayload = null", error_path)
        self.assertIn("elements.board.replaceChildren", error_path)
        self.assertIn("HOST = \"127.0.0.1\"", (ROOT / "scripts" / "serve_odpt_v2_qa.py").read_text())


if __name__ == "__main__":
    unittest.main()
