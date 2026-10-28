from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import os
import shutil
import ssl
import subprocess
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener

from scripts import compare_access_http_clients as diagnostic


CLIENT_ID = "mock-client-id-never-print"
CLIENT_SECRET = "mock-client-secret-never-print"
SENTINEL_BODY = "response-body-must-not-be-read-or-printed"


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    status = 200
    slow = False
    requests: list[dict[str, str]]

    def handle_error(self, request, client_address):  # noqa: ARG002
        # A timeout test intentionally closes a delayed mock connection.
        return


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):  # noqa: A002, ARG002
        return

    def do_GET(self):
        self.server.requests.append({key.lower(): value for key, value in self.headers.items()})
        if self.server.slow:
            time.sleep(0.4)
        self.send_response(self.server.status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("CF-Ray", "aabbccddeeff0011-SJC")
        self.send_header("Content-Length", str(len(SENTINEL_BODY)))
        if self.server.status == 302:
            self.send_header("Location", "https://login.example.invalid/")
        self.end_headers()
        try:
            self.wfile.write(SENTINEL_BODY.encode())
        except (BrokenPipeError, ConnectionResetError):
            pass


class CompareAccessHttpClientsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("curl"):
            raise unittest.SkipTest("curl executable is not installed")

    def setUp(self):
        self.server = _Server(("127.0.0.1", 0), _Handler)
        self.server.status = 200
        self.server.slow = False
        self.server.requests = []
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}/timetable-Wakoshi.json"
        self.opener_factory = lambda: build_opener(diagnostic._NoRedirect(), ProxyHandler({}))

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def run_pair(self, *, timeout=2):
        return diagnostic.compare(
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
            url=self.url,
            allow_loopback_http=True,
            urllib_opener_factory=self.opener_factory,
            timeout=timeout,
        )

    def test_same_http_conditions_and_both_200(self):
        curl_result, python_result, comparison = self.run_pair()
        self.assertEqual(comparison, "curl_200_python_200")
        self.assertEqual((curl_result.status, python_result.status), (200, 200))
        self.assertEqual(curl_result.content_type, "application/json")
        self.assertEqual(python_result.content_type, "application/json")
        self.assertEqual(curl_result.cf_ray, "aabbccddeeff0011-SJC")
        self.assertEqual(python_result.cf_ray, "aabbccddeeff0011-SJC")
        self.assertEqual(len(self.server.requests), 2)
        for request in self.server.requests:
            self.assertEqual(request["user-agent"], diagnostic.USER_AGENT)
            self.assertEqual(request["accept"], "application/json")
            self.assertEqual(request["accept-encoding"], "identity")
            self.assertEqual(request["cf-access-client-id"], CLIENT_ID)
            self.assertEqual(request["cf-access-client-secret"], CLIENT_SECRET)
            self.assertNotIn("cookie", request)
        self.assertNotIn(CLIENT_ID, repr((curl_result, python_result, comparison)))
        self.assertNotIn(CLIENT_SECRET, repr((curl_result, python_result, comparison)))

    def test_both_403_and_redirect_not_followed(self):
        self.server.status = 403
        curl_result, python_result, comparison = self.run_pair()
        self.assertEqual(comparison, "curl_403_python_403")
        self.assertEqual((curl_result.status, python_result.status), (403, 403))
        self.server.status = 302
        self.server.requests.clear()
        curl_result, python_result, comparison = self.run_pair()
        self.assertEqual(comparison, "different_http_statuses")
        self.assertEqual(curl_result.status, 302)
        # urllib treats an un-followed redirect as HTTPError; the diagnostic adapter returns its status.
        self.assertEqual(python_result.status, 302)
        self.assertEqual(len(self.server.requests), 2)

    def test_curl_and_urllib_status_disagreement(self):
        # A controlled curl subprocess mock proves 200/403 classification without external traffic.
        with patch.object(diagnostic, "request_curl", return_value=diagnostic.Result(status=200, content_type="application/json")):
            self.server.status = 403
            _, python_result, comparison = self.run_pair()
        self.assertEqual(python_result.status, 403)
        self.assertEqual(comparison, "curl_200_python_403")

    def test_curl_config_keeps_secrets_out_of_argv_and_aligns_protocol(self):
        seen = {}

        def fake_run(command, **kwargs):
            seen["command"] = command
            seen["input"] = kwargs["input"]
            seen["stderr"] = kwargs["stderr"]
            return subprocess.CompletedProcess(command, 0,
                b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n", b"")

        result = diagnostic.request_curl(client_id=CLIENT_ID, client_secret=CLIENT_SECRET,
                                         url=self.url, curl_path="curl", run=fake_run, timeout=3)
        self.assertEqual(result.status, 200)
        self.assertNotIn(CLIENT_ID, " ".join(seen["command"]))
        self.assertNotIn(CLIENT_SECRET, " ".join(seen["command"]))
        config = seen["input"].decode()
        self.assertIn("http1.1", config)
        self.assertIn("Accept: application/json", config)
        self.assertIn("Accept-Encoding: identity", config)
        self.assertIn(diagnostic.USER_AGENT, config)
        self.assertIn(CLIENT_ID, config)
        self.assertIn(CLIENT_SECRET, config)
        self.assertIn("--disable", seen["command"])
        self.assertIn("--dump-header", seen["command"])
        self.assertIs(seen["stderr"], subprocess.DEVNULL)

    def test_tls_certificate_error_classification(self):
        def failing_curl(*args, **kwargs):  # noqa: ARG001
            return subprocess.CompletedProcess(["curl"], 60, b"", b"suppressed")

        curl_result = diagnostic.request_curl(client_id=CLIENT_ID, client_secret=CLIENT_SECRET,
                                              curl_path="curl", run=failing_curl)

        class _FailingOpener:
            def open(self, request, timeout):  # noqa: ARG002
                raise URLError(ssl.SSLCertVerificationError("mock certificate failure"))

        python_result = diagnostic.request_urllib(self.url, client_id=CLIENT_ID,
                                                   client_secret=CLIENT_SECRET,
                                                   opener_factory=_FailingOpener)
        self.assertEqual(curl_result.error_type, "tls_certificate_error")
        self.assertEqual(python_result.error_type, "tls_certificate_error")
        self.assertEqual(diagnostic._comparison(curl_result, python_result), "tls_certificate_error")

    def test_timeout_classification(self):
        self.server.slow = True
        curl_result, python_result, comparison = self.run_pair(timeout=0.08)
        self.assertEqual(curl_result.error_type, "timeout")
        self.assertEqual(python_result.error_type, "timeout")
        self.assertEqual(comparison, "timeout")

    def test_output_never_includes_credentials_or_response_body(self):
        out = io.StringIO()
        err = io.StringIO()
        with patch.dict(os.environ, {"CF_ACCESS_CLIENT_ID": CLIENT_ID,
                                     "CF_ACCESS_CLIENT_SECRET": CLIENT_SECRET}), \
             patch.object(diagnostic, "compare", return_value=(
                 diagnostic.Result(status=200, content_type="application/json"),
                 diagnostic.Result(status=403, content_type="application/json"),
                 "curl_200_python_403")), \
             redirect_stdout(out), redirect_stderr(err):
            code = diagnostic.main(["--run-live"])
        self.assertEqual(code, 1)
        combined = out.getvalue() + err.getvalue()
        self.assertNotIn(CLIENT_ID, combined)
        self.assertNotIn(CLIENT_SECRET, combined)
        self.assertNotIn(SENTINEL_BODY, combined)
        self.assertIn("curl.http_status=200", combined)
        self.assertIn("python_urllib.http_status=403", combined)

    def test_missing_environment_secret_stops_noninteractive_run_before_network(self):
        output = io.StringIO()
        errors = io.StringIO()
        with patch.dict(os.environ, {"CF_ACCESS_CLIENT_ID": "", "CF_ACCESS_CLIENT_SECRET": ""}), \
             patch.object(diagnostic.sys.stdin, "isatty", return_value=False), \
             patch.object(diagnostic, "compare", side_effect=AssertionError("network must not start")), \
             redirect_stdout(output), redirect_stderr(errors):
            code = diagnostic.main(["--run-live"])
        self.assertEqual(code, 2)
        self.assertIn("required Environment secrets are missing or empty", errors.getvalue())
        self.assertNotIn(CLIENT_ID, output.getvalue() + errors.getvalue())
        self.assertNotIn(CLIENT_SECRET, output.getvalue() + errors.getvalue())

    def test_live_flag_required_before_credentials_or_network(self):
        output = io.StringIO()
        with redirect_stdout(output):
            code = diagnostic.main([])
        self.assertEqual(code, 2)
        self.assertIn("No network request was made", output.getvalue())
        self.assertEqual(self.server.requests, [])


if __name__ == "__main__":
    unittest.main()
