from __future__ import annotations

from contextlib import redirect_stdout, redirect_stderr
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
from threading import Thread
import unittest

from scripts.diagnose_cloudflare_access import DiagnosticError, run_diagnostic


CLIENT_ID = "diagnostic-test-client-id"
CLIENT_SECRET = "diagnostic-test-client-secret"
BODY_SENTINEL = "diagnostic-response-body-must-not-appear"


class _MockServer(ThreadingHTTPServer):
    daemon_threads = True
    request_statuses: dict[str, int]
    requests: list[tuple[str, str | None, str | None]]


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):  # noqa: A002, ARG002
        return

    def do_GET(self):
        self.server.requests.append((self.path,
                                     self.headers.get("CF-Access-Client-Id"),
                                     self.headers.get("CF-Access-Client-Secret")))
        status = self.server.request_statuses.get(self.path, 404)
        self.send_response(status)
        self.send_header("Content-Type", "application/json" if self.path.endswith(".json") else "text/html")
        self.send_header("CF-Ray", "ab12cd34ef56aa78-SJC")
        if status == 302:
            self.send_header("Location", "https://login.example.invalid/")
        self.send_header("CF-Mitigated", "challenge")
        body = BODY_SENTINEL.encode()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class CloudflareAccessDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.server = _MockServer(("127.0.0.1", 0), _Handler)
        self.server.request_statuses = {
            "/timetable-Wakoshi.json": 200,
            "/manifest.json": 404,
        }
        self.server.requests = []
        self.server_shutdown = False
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.origin = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        if not self.server_shutdown:
            self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def call_diagnostic(self, *, client_id=CLIENT_ID, client_secret=CLIENT_SECRET):
        output = io.StringIO()
        errors = io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            try:
                code = run_diagnostic(client_id=client_id, client_secret=client_secret,
                    station_url=f"{self.origin}/timetable-Wakoshi.json",
                    manifest_url=f"{self.origin}/manifest.json",
                    allow_loopback_http_for_test=True)
            except DiagnosticError as error:
                print(f"diagnostic_failed={error}", file=errors)
                code = 1
        return code, output.getvalue(), errors.getvalue()

    def test_nonempty_secrets_station_200_and_legacy_manifest_404(self):
        code, output, errors = self.call_diagnostic()
        self.assertEqual(code, 0)
        self.assertEqual(errors, "")
        self.assertIn("station_json_http_status=200", output)
        self.assertIn("manifest_http_status=404", output)
        self.assertIn("manifest_404_consistent_with_legacy_only", output)
        self.assertIn("migration_readiness=not_evaluated", output)
        self.assertIn("station_json_cf_ray=ab12cd34ef56aa78-SJC", output)
        self.assertIn("station_json_cf_mitigated_present=yes", output)
        self.assertEqual(self.server.requests, [
            ("/timetable-Wakoshi.json", CLIENT_ID, CLIENT_SECRET),
            ("/manifest.json", CLIENT_ID, CLIENT_SECRET),
        ])
        self.assertNotIn(CLIENT_ID, output + errors)
        self.assertNotIn(CLIENT_SECRET, output + errors)
        self.assertNotIn(BODY_SENTINEL, output + errors)

    def test_missing_secret_stops_before_http_request(self):
        code, output, errors = self.call_diagnostic(client_secret="")
        self.assertEqual(code, 1)
        self.assertIn("credentials_present=no", output)
        self.assertIn("required Environment secrets are missing or empty", errors)
        self.assertEqual(self.server.requests, [])

    def test_station_statuses_are_distinguished_and_manifest_is_not_requested(self):
        for status, expected in ((401, "unauthorized_401"), (403, "forbidden_403"),
                                 (404, "not_found_404"), (302, "redirect_302")):
            with self.subTest(status=status):
                self.server.requests.clear()
                self.server.request_statuses["/timetable-Wakoshi.json"] = status
                code, output, errors = self.call_diagnostic()
                self.assertEqual(code, 1)
                self.assertIn(f"station_json_http_status={status}", output)
                self.assertIn(f"result={expected}", output)
                self.assertNotIn("manifest_http_status=", output)
                self.assertEqual(len(self.server.requests), 1)
                self.assertNotIn(CLIENT_SECRET, output + errors)
                self.assertNotIn(BODY_SENTINEL, output + errors)
        self.server.request_statuses["/timetable-Wakoshi.json"] = 200

    def test_manifest_403_is_not_mistaken_for_expected_legacy_404(self):
        self.server.request_statuses["/manifest.json"] = 403
        code, output, errors = self.call_diagnostic()
        self.assertEqual(code, 1)
        self.assertIn("manifest_http_status=403", output)
        self.assertIn("result=manifest_forbidden_403", output)
        self.assertNotIn(CLIENT_SECRET, output + errors)

    def test_manifest_200_reports_state_mismatch_without_readiness_claim(self):
        self.server.request_statuses["/manifest.json"] = 200
        code, output, _ = self.call_diagnostic()
        self.assertEqual(code, 0)
        self.assertIn("manifest_http_status=200", output)
        self.assertIn("manifest_present_state_differs_from_legacy_report", output)
        self.assertIn("migration_readiness=not_evaluated", output)

    def test_network_error_is_redacted(self):
        self.server.shutdown()
        self.server_shutdown = True
        self.server.server_close()
        code, output, errors = self.call_diagnostic()
        self.assertEqual(code, 1)
        self.assertIn("diagnostic_failed=network_error", errors)
        self.assertNotIn(CLIENT_SECRET, output + errors)
        self.assertNotIn(BODY_SENTINEL, output + errors)


if __name__ == "__main__":
    unittest.main()
