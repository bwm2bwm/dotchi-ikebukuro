from __future__ import annotations

from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import tempfile
from threading import Thread
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_public_site import build_public_site  # noqa: E402
from assemble_public_release import assemble_public_artifact  # noqa: E402
import compare_access_http_clients as access_diagnostic  # noqa: E402
from fetch_production_artifact import (  # noqa: E402
    ArtifactFetchError,
    fetch_production_artifact,
    production_fingerprint,
    verify_expected_fingerprint,
)
from synthetic_public_fixture_factory import generate_fixture_directory  # noqa: E402
from validate_public_artifact import validate_artifact, validate_release_managed_artifact  # noqa: E402


def files_under(root: Path) -> dict[str, bytes]:
    return {item.relative_to(root).as_posix(): item.read_bytes()
            for item in root.rglob("*") if item.is_file()}


class LocalAlias:
    def __init__(self, files: dict[str, bytes], *, auth: bool = False):
        self.files = dict(files)
        self.counts: dict[str, int] = {}
        self.request_headers: dict[str, list[dict[str, str]]] = {}
        self.overrides: dict[str, object] = {}
        self.auth = auth
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.server.state = self  # type: ignore[attr-defined]
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def _handler(self):
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, format, *args):  # noqa: A002, ARG002
                return

            def do_GET(self):
                path = self.path.split("?", 1)[0].lstrip("/")
                owner.counts[path] = owner.counts.get(path, 0) + 1
                owner.request_headers.setdefault(path, []).append(
                    {key.lower(): value for key, value in self.headers.items()})
                if owner.auth and (self.headers.get("CF-Access-Client-Id") != "test-id"
                                   or self.headers.get("CF-Access-Client-Secret") != "test-secret"):
                    self.send_response(401 if not self.headers.get("CF-Access-Client-Id") else 403)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                spec = owner.overrides.get(path)
                if callable(spec):
                    spec = spec(owner, path, owner.counts[path])
                if spec is None:
                    if path not in owner.files:
                        self.send_response(404)
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        return
                    body = owner.files[path]
                    status = 200
                    ctype = "application/json" if path.endswith(".json") else (
                        "text/html" if path.endswith(".html") else "text/css" if path.endswith(".css")
                        else "text/javascript")
                    headers = {}
                else:
                    status, ctype, body, headers = spec
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                for name, value in headers.items():
                    self.send_header(name, value)
                if "Content-Length" not in headers:
                    self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    pass
                if headers.get("X-Test-Close") == "1":
                    self.close_connection = True

        return Handler

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


class FetchProductionArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="fetch-alias-fixtures-", dir="/private/tmp")
        cls.base = Path(cls.temp.name)
        cls.fixtures = cls.base / "fixtures"
        generate_fixture_directory(cls.fixtures, date(2026, 10, 27))
        cls.release = cls.base / "release"
        build_public_site(fixtures=cls.fixtures, output=cls.release, release_managed=True)
        cls.legacy = cls.base / "legacy"
        build_public_site(fixtures=cls.fixtures, output=cls.legacy)
        next_fixtures = cls.base / "fixtures-next"
        generate_fixture_directory(next_fixtures, date(2026, 10, 28))
        cls.next_release = cls.base / "release-next"
        build_public_site(fixtures=next_fixtures, output=cls.next_release, release_managed=True)
        cls.with_retained = cls.base / "release-with-retained"
        assemble_public_artifact(previous=cls.release, new_release=cls.next_release,
            output=cls.with_retained, evaluated_at="2026-10-28T12:00:00+09:00")
        cls.with_legacy_alias = cls.base / "release-with-legacy-alias"
        assemble_public_artifact(previous=cls.legacy, new_release=cls.next_release,
            output=cls.with_legacy_alias, evaluated_at="2026-10-28T12:00:00+09:00")
        cls.release_files = files_under(cls.release)
        cls.legacy_files = files_under(cls.legacy)
        cls.retained_files = files_under(cls.with_retained)
        cls.migration_files = files_under(cls.with_legacy_alias)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="fetch-alias-case-", dir="/private/tmp")
        self.base = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        self.aliases: list[LocalAlias] = []

    def alias(self, files=None, **kwargs):
        server = LocalAlias(files or self.release_files, **kwargs)
        self.aliases.append(server)
        self.addCleanup(server.close)
        return server

    def fetch(self, alias, name="out", **kwargs):
        return fetch_production_artifact(base_url=alias.url, output=self.base / name,
            allow_insecure_loopback=True, sleep=lambda _: None, **kwargs)

    def test_release_managed_download_is_independently_validated_and_fingerprint_pinned(self):
        alias = self.alias()
        result = self.fetch(alias, "release")
        self.assertEqual(result["mode"], "release-managed")
        self.assertEqual(result["files"], 18)
        self.assertEqual(validate_release_managed_artifact(self.base / "release")["release_id"], result["release_id"])
        self.assertEqual((self.base / "release" / "manifest.json").read_bytes(), self.release_files["manifest.json"])
        assemble_public_artifact(previous=self.base / "release", new_release=self.next_release,
            output=self.base / "assembled-release", evaluated_at="2026-10-28T12:00:00+09:00")
        self.assertEqual(validate_release_managed_artifact(self.base / "assembled-release")["files"], 26)
        fingerprint = production_fingerprint(base_url=alias.url, mode="release-managed",
            allow_insecure_loopback=True, sleep=lambda _: None)
        self.assertEqual(fingerprint["fingerprint"], result["fingerprint"])
        self.assertEqual(verify_expected_fingerprint(base_url=alias.url, mode="release-managed",
            expected=result["fingerprint"], allow_insecure_loopback=True, sleep=lambda _: None)["matches"], True)
        with self.assertRaisesRegex(ArtifactFetchError, "changed since"):
            verify_expected_fingerprint(base_url=alias.url, mode="release-managed", expected="0" * 64,
                allow_insecure_loopback=True, sleep=lambda _: None)

        retained_alias = self.alias(self.retained_files)
        retained_result = self.fetch(retained_alias, "retained",
            as_of=datetime.fromisoformat("2026-10-28T12:00:00+09:00"))
        self.assertEqual(retained_result["files"], 26)
        self.assertEqual(validate_release_managed_artifact(self.base / "retained")["retained_releases"], 1)

        migration_alias = self.alias(self.migration_files)
        migration_result = self.fetch(migration_alias, "migration",
            as_of=datetime.fromisoformat("2026-10-28T12:00:00+09:00"))
        self.assertTrue(migration_result["legacy_compatibility"])
        self.assertEqual(migration_result["files"], 26)
        self.assertTrue((self.base / "migration" / "timetable.json").is_file())
        validate_release_managed_artifact(self.base / "migration")

    def test_legacy_requires_explicit_initial_migration_and_passes_strict_validator(self):
        alias = self.alias(self.legacy_files)
        with self.assertRaisesRegex(ArtifactFetchError, "explicit initial-migration"):
            self.fetch(alias, "denied")
        self.assertFalse((self.base / "denied").exists())
        result = self.fetch(alias, "legacy", allow_initial_legacy=True)
        self.assertEqual(result["mode"], "legacy")
        self.assertEqual(result["files"], 17)
        self.assertEqual(validate_artifact(self.base / "legacy")["files"], 17)
        assemble_public_artifact(previous=self.base / "legacy", new_release=self.next_release,
            output=self.base / "assembled-legacy-migration", evaluated_at="2026-10-28T12:00:00+09:00")
        self.assertEqual(validate_release_managed_artifact(
            self.base / "assembled-legacy-migration")["files"], 26)

    def test_manifest_missing_and_malformed_never_silently_fallback(self):
        legacy = self.alias(self.legacy_files)
        with self.assertRaisesRegex(ArtifactFetchError, "explicit initial-migration"):
            self.fetch(legacy)
        malformed_files = dict(self.release_files)
        malformed_files["manifest.json"] = b"<html>login</html>"
        malformed = self.alias(malformed_files)
        with self.assertRaises(ArtifactFetchError):
            self.fetch(malformed, "bad-manifest", allow_initial_legacy=True)
        self.assertFalse((self.base / "bad-manifest").exists())

    def test_initial_legacy_migration_accepts_only_exact_pages_spa_fallback(self):
        spa = self.alias(self.legacy_files, auth=True)
        spa.overrides["manifest.json"] = (
            200, "text/html; charset=utf-8", self.legacy_files["index.html"], {})
        with self.assertRaisesRegex(ArtifactFetchError, "Content-Type"):
            self.fetch(spa, "spa-no-opt-in", client_id="test-id", client_secret="test-secret")
        self.assertFalse((self.base / "spa-no-opt-in").exists())

        result = self.fetch(spa, "spa-migration", allow_initial_legacy=True,
                            client_id="test-id", client_secret="test-secret")
        self.assertEqual(result["mode"], "legacy")
        self.assertEqual(result["files"], 17)
        self.assertEqual(files_under(self.base / "spa-migration"), self.legacy_files)
        self.assertGreaterEqual(spa.counts.get("index.html", 0), 3)
        self.assertEqual(validate_artifact(self.base / "spa-migration")["files"], 17)
        first_manifest_request = spa.request_headers["manifest.json"][0]
        self.assertEqual(first_manifest_request["user-agent"], access_diagnostic.USER_AGENT)
        self.assertEqual(first_manifest_request["accept"], "application/json")
        self.assertEqual(first_manifest_request["accept-encoding"], "identity")
        self.assertEqual(first_manifest_request["cf-access-client-id"], "test-id")
        self.assertEqual(first_manifest_request["cf-access-client-secret"], "test-secret")
        self.assertNotIn("cookie", first_manifest_request)

        mismatch = self.alias(self.legacy_files)
        mismatch.overrides["manifest.json"] = (
            200, "text/html", b"<html>not-the-root-page</html>", {})
        with self.assertRaisesRegex(ArtifactFetchError, "does not match") as caught:
            self.fetch(mismatch, "spa-mismatch", allow_initial_legacy=True)
        self.assertNotIn("not-the-root-page", str(caught.exception))
        self.assertFalse((self.base / "spa-mismatch").exists())

    def test_spa_migration_fails_closed_for_root_and_manifest_errors(self):
        for status in (403, 404, 302):
            alias = self.alias(self.legacy_files)
            alias.overrides["index.html"] = (status, "text/html", b"root-error", {})
            alias.overrides["manifest.json"] = (
                200, "text/html", self.legacy_files["index.html"], {})
            with self.subTest(root_status=status), self.assertRaises(ArtifactFetchError):
                self.fetch(alias, f"root-error-{status}", allow_initial_legacy=True)
            self.assertFalse((self.base / f"root-error-{status}").exists())

        denied = self.alias(self.legacy_files)
        denied.overrides["manifest.json"] = (403, "application/json", b"private-response", {})
        with self.assertRaisesRegex(ArtifactFetchError, "HTTP status 403") as caught:
            self.fetch(denied, "manifest-403", allow_initial_legacy=True)
        self.assertNotIn("private-response", str(caught.exception))
        self.assertFalse((self.base / "manifest-403").exists())

    def test_spa_fingerprint_and_manifest_transition_are_checked(self):
        stable = self.alias(self.legacy_files)
        stable.overrides["manifest.json"] = (
            200, "text/html", self.legacy_files["index.html"], {})
        result = production_fingerprint(base_url=stable.url, mode="legacy",
            allow_initial_legacy=True, allow_insecure_loopback=True, sleep=lambda _: None)
        self.assertEqual(result["mode"], "legacy")
        self.assertRegex(result["fingerprint"], r"^[0-9a-f]{64}$")

        changing = self.alias(self.legacy_files)
        changing.overrides["manifest.json"] = (
            200, "text/html", self.legacy_files["index.html"], {})
        changed_path = "timetable-Wakoshi.json"
        original = self.legacy_files[changed_path]
        changing.overrides[changed_path] = lambda _owner, _path, count: (
            200, "application/json", original if count == 1 else original + b" ", {})
        with self.assertRaisesRegex(ArtifactFetchError, "legacy Production alias changed"):
            self.fetch(changing, "spa-fingerprint-race", allow_initial_legacy=True)
        self.assertFalse((self.base / "spa-fingerprint-race").exists())

        switching = self.alias(self.legacy_files)
        switching.overrides["manifest.json"] = lambda owner, _path, count: (
            (200, "text/html", owner.files["index.html"], {}) if count == 1 else
            (200, "application/json", self.release_files["manifest.json"], {}))
        with self.assertRaisesRegex(ArtifactFetchError, "changed from SPA fallback"):
            self.fetch(switching, "html-json-race", allow_initial_legacy=True)
        self.assertFalse((self.base / "html-json-race").exists())

    def test_spa_migration_still_requires_legacy_strict_validation(self):
        files = dict(self.legacy_files)
        files["timetable.json"] = b"{\"invalid\":true}"
        alias = self.alias(files)
        alias.overrides["manifest.json"] = (200, "text/html", files["index.html"], {})
        with self.assertRaisesRegex(ArtifactFetchError, "failed independent validation"):
            self.fetch(alias, "invalid-legacy", allow_initial_legacy=True)
        self.assertFalse((self.base / "invalid-legacy").exists())

    def test_service_auth_headers_and_auth_failures_do_not_echo_credentials(self):
        alias = self.alias(auth=True)
        with self.assertRaisesRegex(ArtifactFetchError, "HTTP status 401"):
            self.fetch(alias, "no-auth")
        with self.assertRaisesRegex(ArtifactFetchError, "HTTP status 403") as caught:
            self.fetch(alias, "bad-auth", client_id="test-id", client_secret="wrong-secret")
        self.assertNotIn("wrong-secret", str(caught.exception))
        result = self.fetch(alias, "with-auth", client_id="test-id", client_secret="test-secret")
        self.assertEqual(result["mode"], "release-managed")
        self.assertNotIn("test-secret", repr(result))

    def test_html_login_response_wrong_content_type_redirect_and_traversal_are_rejected(self):
        html_files = dict(self.release_files)
        html_files["manifest.json"] = b"{}"
        html_alias = self.alias(html_files)
        html_alias.overrides["manifest.json"] = (200, "text/html", b"<html>login</html>", {})
        with self.assertRaisesRegex(ArtifactFetchError, "Content-Type"):
            self.fetch(html_alias, "html")

        redirect_target = self.alias()
        redirect = self.alias()
        redirect.overrides["manifest.json"] = (302, "text/plain", b"",
            {"Location": f"{redirect_target.url}/manifest.json"})
        with self.assertRaisesRegex(ArtifactFetchError, "HTTP status 302"):
            self.fetch(redirect, "redirect")
        self.assertEqual(redirect_target.counts, {})

        path_files = dict(self.release_files)
        manifest = json.loads(path_files["manifest.json"])
        manifest["stations"]["Hikawadai"]["url"] = "/releases/../escape.json"
        path_files["manifest.json"] = json.dumps(manifest).encode("utf-8")
        path_alias = self.alias(path_files)
        with self.assertRaises(ArtifactFetchError):
            self.fetch(path_alias, "path")
        self.assertEqual(path_alias.counts.get("escape.json", 0), 0)

    def test_missing_or_tampered_generation_json_fails_closed(self):
        manifest = json.loads(self.release_files["manifest.json"])
        station_url = manifest["stations"]["Hikawadai"]["url"].lstrip("/")
        missing_files = dict(self.release_files)
        del missing_files[station_url]
        missing = self.alias(missing_files)
        with self.assertRaisesRegex(ArtifactFetchError, "HTTP status 404"):
            self.fetch(missing, "missing-json")

        changed_files = dict(self.release_files)
        changed_files[station_url] += b" "
        changed = self.alias(changed_files)
        with self.assertRaises(ArtifactFetchError):
            self.fetch(changed, "tampered-json")
        self.assertFalse((self.base / "tampered-json").exists())

    def test_generation_change_during_download_is_detected_and_stage_cleaned(self):
        alias = self.alias()
        initial = self.release_files["manifest.json"]
        changed = bytearray(initial)
        changed[-2] = ord(" ") if changed[-2] != ord(" ") else ord("\n")
        changed = bytes(changed)
        alias.overrides["manifest.json"] = lambda owner, _path, count: (
            200, "application/json", initial if count == 1 else changed, {})
        with self.assertRaisesRegex(ArtifactFetchError, "manifest changed during fetch"):
            self.fetch(alias, "race")
        self.assertFalse((self.base / "race").exists())
        self.assertFalse(any(p.name.startswith("dotchi-alias-fetch-") for p in self.base.iterdir()))

    def test_retry_is_finite_for_timeout_and_interrupted_response(self):
        alias = self.alias()
        path = "manifest.json"
        alias.overrides[path] = lambda owner, _path, count: (
            200, "application/json", owner.files[path],
            {"Content-Length": str(len(owner.files[path]) + 20), "X-Test-Close": "1"}) if count <= 2 else None
        with self.assertRaises(ArtifactFetchError):
            self.fetch(alias, "interrupted", retries=1, timeout=1)
        self.assertEqual(alias.counts[path], 2)

        slow = self.alias()
        def delayed(owner, rel, count):
            time.sleep(0.12)
            return None
        slow.overrides[path] = delayed
        with self.assertRaises(ArtifactFetchError):
            self.fetch(slow, "timeout", retries=1, timeout=0.03)
        self.assertEqual(slow.counts[path], 2)

    def test_file_and_total_byte_limits_and_existing_output_are_refused(self):
        alias = self.alias()
        with self.assertRaisesRegex(ArtifactFetchError, "byte limit"):
            self.fetch(alias, "small-file-limit", max_file_bytes=32)
        with self.assertRaisesRegex(ArtifactFetchError, "total exceeds"):
            self.fetch(alias, "small-total-limit", max_total_bytes=100)
        with self.assertRaisesRegex(ArtifactFetchError, "file count exceeds"):
            self.fetch(alias, "small-file-count", max_files=1)
        existing = self.base / "existing"
        existing.mkdir()
        with self.assertRaisesRegex(ArtifactFetchError, "must not already exist"):
            self.fetch(alias, "existing")
        self.assertEqual(list(self.base.glob("dotchi-alias-fetch-*")), [])

    def test_static_and_station_paths_only_are_downloaded_unknown_remote_files_are_ignored(self):
        files = dict(self.release_files)
        files["not-referenced.txt"] = b"not requested"
        alias = self.alias(files)
        self.fetch(alias, "filtered")
        self.assertEqual(alias.counts.get("not-referenced.txt", 0), 0)

    def test_legacy_fingerprint_is_stable_and_rejects_incomplete_files(self):
        alias = self.alias(self.legacy_files)
        result = production_fingerprint(base_url=alias.url, mode="legacy", allow_initial_legacy=True,
            allow_insecure_loopback=True, sleep=lambda _: None)
        self.assertRegex(result["fingerprint"], r"^[0-9a-f]{64}$")
        changing = self.alias(self.legacy_files)
        first_path = sorted(self.legacy_files)[0]
        original = self.legacy_files[first_path]
        changing.overrides[first_path] = lambda _owner, _path, count: (
            200, "text/html", original if count == 1 else original + b" ", {})
        with self.assertRaisesRegex(ArtifactFetchError, "legacy Production alias changed"):
            self.fetch(changing, "legacy-race", allow_initial_legacy=True)
        self.assertFalse((self.base / "legacy-race").exists())
        files = dict(self.legacy_files)
        files.pop("timetable.json")
        missing = self.alias(files)
        with self.assertRaises(ArtifactFetchError):
            production_fingerprint(base_url=missing.url, mode="legacy", allow_initial_legacy=True,
                allow_insecure_loopback=True, sleep=lambda _: None)

    def test_output_symlink_and_non_loopback_http_are_refused(self):
        alias = self.alias()
        link = self.base / "link"
        link.symlink_to(self.base / "absent")
        with self.assertRaisesRegex(ArtifactFetchError, "output must not already exist"):
            self.fetch(alias, "link")
        with self.assertRaisesRegex(ArtifactFetchError, "loopback"):
            fetch_production_artifact(base_url="http://192.0.2.1", output=self.base / "remote-http")


if __name__ == "__main__":
    unittest.main()
