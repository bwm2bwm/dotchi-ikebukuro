#!/usr/bin/env python3
"""Read-only, redacted diagnostic for the staging Pages Access Service Token."""
from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import os
import re
import sys
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


ORIGIN = "https://dotchi-ikebukuro-staging.pages.dev"
STATION_URL = f"{ORIGIN}/timetable-Wakoshi.json"
MANIFEST_URL = f"{ORIGIN}/manifest.json"
TIMEOUT_SECONDS = 15
_RAY_ID = re.compile(r"^[A-Za-z0-9-]{1,64}$")
_MIME = re.compile(r"^[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+$")
_AUTH_DIAGNOSTIC_HEADERS = (
    "location",
    "cf-mitigated",
    "www-authenticate",
    "set-cookie",
)


class DiagnosticError(ValueError):
    """Safe diagnostic failure that never includes credentials or response bodies."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ARG002
        return None


@dataclass(frozen=True)
class ResponseSummary:
    status: int
    content_type: str
    cf_ray: str | None
    present_headers: tuple[str, ...]


def _validate_target(url: str, *, allow_loopback_http_for_test: bool) -> None:
    parts = urlsplit(url)
    if parts.username or parts.password or parts.query or parts.fragment:
        raise DiagnosticError("diagnostic target is invalid")
    if parts.scheme == "https" and parts.netloc == "dotchi-ikebukuro-staging.pages.dev":
        return
    if allow_loopback_http_for_test and parts.scheme == "http" and parts.hostname:
        try:
            is_loopback = ipaddress.ip_address(parts.hostname).is_loopback
        except ValueError:
            is_loopback = parts.hostname.lower() == "localhost"
        if is_loopback and parts.port:
            return
    raise DiagnosticError("diagnostic target is not allowed")


def _summary(status: int, headers) -> ResponseSummary:
    raw_content_type = headers.get("Content-Type", "")
    media_type = raw_content_type.split(";", 1)[0].strip().lower()
    content_type = media_type if _MIME.fullmatch(media_type) else "unavailable"
    ray = headers.get("CF-Ray")
    if ray is not None:
        ray = ray.strip()
        if not _RAY_ID.fullmatch(ray):
            ray = None
    present = tuple(name for name in _AUTH_DIAGNOSTIC_HEADERS if headers.get(name) is not None)
    return ResponseSummary(status, content_type, ray, present)


def _request_summary(url: str, *, client_id: str, client_secret: str,
                     opener, timeout: int) -> ResponseSummary:
    response = None
    try:
        request = Request(url, headers={
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "CF-Access-Client-Id": client_id,
            "CF-Access-Client-Secret": client_secret,
        }, method="GET")
        response = opener.open(request, timeout=timeout)
        return _summary(response.status, response.headers)
    except HTTPError as error:
        # Do not read or render the response body, URL, or headers beyond the safe allowlist.
        summary = _summary(error.code, error.headers)
        error.close()
        return summary
    except Exception as error:  # noqa: BLE001 - suppress library errors that might include request details.
        if isinstance(error, TimeoutError):
            raise DiagnosticError("network_timeout") from None
        if isinstance(error, URLError) and isinstance(error.reason, TimeoutError):
            raise DiagnosticError("network_timeout") from None
        raise DiagnosticError("network_error") from None
    finally:
        if response is not None:
            response.close()


def _emit(label: str, summary: ResponseSummary) -> None:
    print(f"{label}_http_status={summary.status}")
    print(f"{label}_content_type={summary.content_type}")
    print(f"{label}_cf_ray={summary.cf_ray or 'unavailable'}")
    for name in _AUTH_DIAGNOSTIC_HEADERS:
        print(f"{label}_{name.replace('-', '_')}_present={'yes' if name in summary.present_headers else 'no'}")


def _status_class(status: int) -> str:
    if status == 401:
        return "unauthorized_401"
    if status == 403:
        return "forbidden_403"
    if status == 404:
        return "not_found_404"
    if 300 <= status < 400:
        return f"redirect_{status}"
    return f"http_error_{status}"


def run_diagnostic(*, client_id: str | None, client_secret: str | None,
                   station_url: str = STATION_URL, manifest_url: str = MANIFEST_URL,
                   timeout: int = TIMEOUT_SECONDS,
                   allow_loopback_http_for_test: bool = False,
                   opener_factory: Callable[[], object] | None = None) -> int:
    """Run two fixed-purpose GETs; URL injection is limited to loopback tests."""
    if not client_id or not client_secret:
        print("credentials_present=no")
        raise DiagnosticError("required Environment secrets are missing or empty")
    if timeout <= 0:
        raise DiagnosticError("timeout must be positive")
    _validate_target(station_url, allow_loopback_http_for_test=allow_loopback_http_for_test)
    _validate_target(manifest_url, allow_loopback_http_for_test=allow_loopback_http_for_test)

    opener = (opener_factory or (lambda: build_opener(_NoRedirect())))()
    station = _request_summary(station_url, client_id=client_id, client_secret=client_secret,
                               opener=opener, timeout=timeout)
    _emit("station_json", station)
    if station.status != 200:
        print(f"result={_status_class(station.status)}")
        return 1
    if station.content_type != "application/json":
        print("result=station_response_not_json")
        return 1

    manifest = _request_summary(manifest_url, client_id=client_id, client_secret=client_secret,
                                opener=opener, timeout=timeout)
    _emit("manifest", manifest)
    if manifest.status == 404:
        print("result=service_token_verified; manifest_404_consistent_with_legacy_only")
        print("migration_readiness=not_evaluated")
        return 0
    if manifest.status == 200:
        print("result=service_token_verified; manifest_present_state_differs_from_legacy_report")
        print("migration_readiness=not_evaluated")
        return 0
    print(f"result=manifest_{_status_class(manifest.status)}")
    print("migration_readiness=not_evaluated")
    return 1


def main() -> int:
    client_id = os.environ.get("CF_ACCESS_CLIENT_ID")
    client_secret = os.environ.get("CF_ACCESS_CLIENT_SECRET")
    try:
        return run_diagnostic(client_id=client_id, client_secret=client_secret)
    except DiagnosticError as error:
        print(f"diagnostic_failed={error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
