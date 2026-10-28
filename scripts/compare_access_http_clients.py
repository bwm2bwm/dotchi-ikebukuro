#!/usr/bin/env python3
"""Compare curl and urllib against the staging Access endpoint.

Network access is disabled unless --run-live is supplied. Tests may inject a
loopback URL through the Python API; the CLI always uses the fixed Pages URL.
"""
from __future__ import annotations

from dataclasses import dataclass
import getpass
import os
import re
import shutil
import socket
import ssl
import subprocess
import sys
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


URL = "https://dotchi-ikebukuro-staging.pages.dev/timetable-Wakoshi.json"
USER_AGENT = "dotchi-ikebukuro-access-client-compare/1.0"
TIMEOUT_SECONDS = 20
_RAY = re.compile(r"^[A-Za-z0-9-]{1,64}$")
_MIME = re.compile(r"^[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+$")
_PROXY_VARIABLE_GROUPS = {
    "http_proxy": ("HTTP_PROXY", "http_proxy"),
    "https_proxy": ("HTTPS_PROXY", "https_proxy"),
    "all_proxy": ("ALL_PROXY", "all_proxy"),
    "no_proxy": ("NO_PROXY", "no_proxy"),
}
_CA_VARIABLES = ("SSL_CERT_FILE", "SSL_CERT_DIR", "CURL_CA_BUNDLE")


class DiagnosticError(ValueError):
    """Safe, redacted diagnostic setup error."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ARG002
        return None


@dataclass(frozen=True)
class Result:
    status: int | None = None
    content_type: str = "unavailable"
    cf_ray: str = "unavailable"
    error_type: str = "none"


def _validate_credentials(client_id: str, client_secret: str) -> None:
    # HTTP header values must not permit injection. Never include a value in an error.
    for value in (client_id, client_secret):
        if not value or not value.strip() or any(ord(ch) < 32 or ord(ch) > 126 for ch in value):
            raise DiagnosticError("credentials are empty or not valid HTTP header values")


def _validate_url(url: str, *, allow_loopback_http: bool) -> None:
    parts = urlsplit(url)
    if parts.username or parts.password or parts.query or parts.fragment or not parts.hostname:
        raise DiagnosticError("diagnostic URL is invalid")
    if url == URL:
        return
    if allow_loopback_http and parts.scheme == "http" and parts.hostname in {"127.0.0.1", "::1", "localhost"}:
        return
    raise DiagnosticError("diagnostic URL is not allowed")


def _response_result(status: int, headers) -> Result:
    raw_type = headers.get("Content-Type", "")
    media_type = raw_type.split(";", 1)[0].strip().lower()
    content_type = media_type if _MIME.fullmatch(media_type) else "unavailable"
    ray = (headers.get("CF-Ray") or "").strip()
    if not _RAY.fullmatch(ray):
        ray = "unavailable"
    return Result(status=status, content_type=content_type, cf_ray=ray)


def _classify_exception(error: BaseException) -> str:
    if isinstance(error, ssl.SSLCertVerificationError):
        return "tls_certificate_error"
    if isinstance(error, ssl.SSLError):
        return "tls_error"
    if isinstance(error, (TimeoutError, socket.timeout, subprocess.TimeoutExpired)):
        return "timeout"
    if isinstance(error, URLError):
        reason = error.reason
        if isinstance(reason, ssl.SSLCertVerificationError):
            return "tls_certificate_error"
        if isinstance(reason, ssl.SSLError):
            return "tls_error"
        if isinstance(reason, (TimeoutError, socket.timeout)):
            return "timeout"
    return "network_error"


def request_urllib(url: str, *, client_id: str, client_secret: str,
                   timeout: float = TIMEOUT_SECONDS,
                   opener_factory: Callable[[], object] | None = None) -> Result:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        "Accept-Encoding": "identity",
        "CF-Access-Client-Id": client_id,
        "CF-Access-Client-Secret": client_secret,
    }
    request = Request(url, headers=headers, method="GET")
    opener = (opener_factory or (lambda: build_opener(_NoRedirect())))()
    response = None
    try:
        response = opener.open(request, timeout=timeout)
        return _response_result(response.status, response.headers)
    except HTTPError as error:
        result = _response_result(error.code, error.headers)
        error.close()
        return result
    except BaseException as error:  # redact urllib/OpenSSL details which can include request context
        return Result(error_type=_classify_exception(error))
    finally:
        if response is not None:
            response.close()


def _curl_config(url: str, client_id: str, client_secret: str, timeout: float) -> bytes:
    # Values go to curl over stdin, never argv or logs. Reject controls before quoting.
    def quote(value: str) -> str:
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'

    lines = [
        f"url = {quote(url)}",
        "request = \"GET\"",
        f"user-agent = {quote(USER_AGENT)}",
        f"header = {quote('Accept: application/json')}",
        f"header = {quote('Accept-Encoding: identity')}",
        f"header = {quote('CF-Access-Client-Id: ' + client_id)}",
        f"header = {quote('CF-Access-Client-Secret: ' + client_secret)}",
        "http1.1",
        f"max-time = {timeout}",
        "max-redirs = 0",
    ]
    return ("\n".join(lines) + "\n").encode("ascii")


def _parse_curl_headers(raw: bytes) -> Result | None:
    # curl --dump-header can contain multiple response blocks. Use the final non-1xx block.
    blocks: list[list[bytes]] = []
    current: list[bytes] = []
    for line in raw.splitlines():
        if line.startswith(b"HTTP/"):
            if current:
                blocks.append(current)
            current = [line]
        elif current:
            current.append(line)
    if current:
        blocks.append(current)
    selected: list[bytes] | None = None
    for block in blocks:
        try:
            status = int(block[0].split()[1])
        except (IndexError, ValueError):
            continue
        if status >= 200:
            selected = block
    if selected is None:
        return None
    parsed: dict[str, str] = {}
    for line in selected[1:]:
        key, sep, value = line.partition(b":")
        if sep:
            try:
                parsed[key.decode("ascii").strip().lower()] = value.decode("latin-1").strip()
            except UnicodeDecodeError:
                continue
    class _Headers(dict):
        def get(self, key, default=None):
            return super().get(key.lower(), default)
    return _response_result(int(selected[0].split()[1]), _Headers(parsed))


def request_curl(*, client_id: str, client_secret: str,
                 url: str = URL,
                 curl_path: str | None = None,
                 run: Callable = subprocess.run,
                 timeout: float = TIMEOUT_SECONDS) -> Result:
    executable = curl_path or shutil.which("curl")
    if not executable:
        return Result(error_type="curl_unavailable")
    command = [executable, "--disable", "--silent", "--output", os.devnull,
               "--dump-header", "-", "--http1.1", "--config", "-"]
    try:
        completed = run(command, input=_curl_config(url, client_id, client_secret, timeout),
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                         timeout=timeout, check=False)
    except BaseException as error:  # never print exception text
        return Result(error_type=_classify_exception(error))
    result = _parse_curl_headers(completed.stdout or b"")
    if result is not None:
        return result
    if completed.returncode == 60 or completed.returncode == 77:
        return Result(error_type="tls_certificate_error")
    if completed.returncode == 28:
        return Result(error_type="timeout")
    return Result(error_type="network_error")


def _comparison(curl_result: Result, python_result: Result) -> str:
    c, p = curl_result.status, python_result.status
    if curl_result.error_type == "tls_certificate_error" or python_result.error_type == "tls_certificate_error":
        return "tls_certificate_error"
    if curl_result.error_type != "none" or python_result.error_type != "none":
        if curl_result.error_type == python_result.error_type:
            return curl_result.error_type
        return "different_communication_errors"
    if c == 200 and p == 200:
        return "curl_200_python_200"
    if c == 200 and p == 403:
        return "curl_200_python_403"
    if c == 403 and p == 403:
        return "curl_403_python_403"
    return "different_http_statuses"


def compare(*, client_id: str, client_secret: str, url: str = URL,
            allow_loopback_http: bool = False,
            curl_path: str | None = None, curl_run: Callable = subprocess.run,
            urllib_opener_factory: Callable[[], object] | None = None,
            timeout: float = TIMEOUT_SECONDS) -> tuple[Result, Result, str]:
    _validate_credentials(client_id, client_secret)
    _validate_url(url, allow_loopback_http=allow_loopback_http)
    # Tests can direct both clients to loopback. The public CLI always uses URL above.
    curl_result = request_curl(client_id=client_id, client_secret=client_secret,
                               url=url, curl_path=curl_path, run=curl_run, timeout=timeout)
    # urllib uses the same target through its URL argument; no cookie handler is installed.
    python_result = request_urllib(url, client_id=client_id, client_secret=client_secret,
                                   timeout=timeout, opener_factory=urllib_opener_factory)
    return curl_result, python_result, _comparison(curl_result, python_result)


def _print_result(name: str, result: Result) -> None:
    print(f"{name}.http_status={result.status if result.status is not None else 'unavailable'}")
    print(f"{name}.content_type={result.content_type}")
    print(f"{name}.cf_ray={result.cf_ray}")
    print(f"{name}.error_type={result.error_type}")


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args != ["--run-live"]:
        print("No network request was made. Run with --run-live to contact the fixed staging URL.")
        return 2
    client_id = os.environ.get("CF_ACCESS_CLIENT_ID")
    client_secret = os.environ.get("CF_ACCESS_CLIENT_SECRET")
    try:
        if (not client_id or not client_secret) and not sys.stdin.isatty():
            raise DiagnosticError("required Environment secrets are missing or empty")
        if not client_id:
            client_id = getpass.getpass("Cloudflare Access Client ID (hidden): ")
        if not client_secret:
            client_secret = getpass.getpass("Cloudflare Access Client Secret (hidden): ")
        _validate_credentials(client_id, client_secret)
        curl_result, python_result, outcome = compare(client_id=client_id, client_secret=client_secret)
    except DiagnosticError as error:
        print(f"diagnostic_failed={error}", file=sys.stderr)
        return 2
    finally:
        # Best-effort reference release; Python strings cannot be reliably zeroized.
        client_id = None
        client_secret = None
    _print_result("curl", curl_result)
    _print_result("python_urllib", python_result)
    print(f"comparison={outcome}")
    for normalized, names in _PROXY_VARIABLE_GROUPS.items():
        present = any(os.environ.get(name) for name in names)
        print(f"transport_context.{normalized}={'present' if present else 'absent'}")
    for name in _CA_VARIABLES:
        print(f"transport_context.{name.lower()}={'present' if os.environ.get(name) else 'absent'}")
    print("transport_context.curlrc=disabled")
    print("transport_context.redirects=disabled")
    return 0 if outcome == "curl_200_python_200" else 1


if __name__ == "__main__":
    raise SystemExit(main())
