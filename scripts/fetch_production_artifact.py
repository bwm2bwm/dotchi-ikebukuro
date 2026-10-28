#!/usr/bin/env python3
"""Fetch and independently validate the current static artifact from a fixed alias."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import http.client
import ipaddress
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import socket
import ssl
import stat
import sys
import tempfile
import time
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from release_contract import (
    STATION_FILES,
    canonicalize_jcs,
    encode_manifest,
    sha256_hex,
    validate_manifest,
)
from validate_public_artifact import (
    ArtifactValidationError,
    EXPECTED_FILES,
    STATIC_FILES,
    validate_artifact,
    validate_release_managed_artifact,
)

MAX_FILES_DEFAULT = 20_000
MAX_FILE_BYTES_DEFAULT = 25 * 1024 * 1024
MAX_TOTAL_BYTES_DEFAULT = 256 * 1024 * 1024
MAX_MANIFEST_BYTES_DEFAULT = 2 * 1024 * 1024
LEGACY_ASSETS = tuple(sorted(EXPECTED_FILES))
TRANSIENT_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


class ArtifactFetchError(ValueError):
    """Safe public error. Never includes request headers, response body, or raw URLs."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ARG002
        return None


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ArtifactFetchError("manifest contains a duplicate JSON member")
        result[key] = value
    return result


def _loopback_host(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def normalize_base_url(value: str, *, allow_insecure_loopback: bool = False) -> tuple[str, str]:
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError:
        raise ArtifactFetchError("base URL is invalid") from None
    if parts.scheme not in {"https", "http"} or not parts.hostname or parts.username or parts.password \
       or parts.query or parts.fragment or parts.path not in {"", "/"}:
        raise ArtifactFetchError("base URL must be a root HTTPS origin without credentials, query, or fragment")
    if parts.scheme != "https" and not (allow_insecure_loopback and _loopback_host(parts.hostname)):
        raise ArtifactFetchError("HTTP is allowed only for explicit local loopback tests")
    if parts.scheme == "https" and allow_insecure_loopback and _loopback_host(parts.hostname):
        # HTTPS remains valid; this flag only relaxes HTTP for loopback tests.
        pass
    netloc = parts.hostname.lower()
    if ":" in netloc:
        netloc = f"[{netloc}]"
    if port is not None:
        netloc += f":{port}"
    origin = urlunsplit((parts.scheme, netloc, "", "", ""))
    return origin, parts.scheme


def _safe_relative_path(path: str) -> str:
    if not isinstance(path, str) or not path or path.startswith("/") or "\\" in path \
       or "%" in path or "?" in path or "#" in path:
        raise ArtifactFetchError("artifact path is invalid")
    parts = path.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ArtifactFetchError("artifact path is invalid")
    pure = PurePosixPath(path)
    if pure.is_absolute() or pure.as_posix() != path:
        raise ArtifactFetchError("artifact path is invalid")
    return path


def access_headers(client_id: str | None = None, client_secret: str | None = None) -> dict[str, str]:
    if (client_id is None) != (client_secret is None):
        raise ArtifactFetchError("both Access Service Token environment values are required")
    headers = {"Accept": "*/*", "Accept-Encoding": "identity"}
    if client_id is not None:
        if not client_id.strip() or not client_secret or not client_secret.strip():
            raise ArtifactFetchError("Access Service Token environment values must be nonempty")
        headers["CF-Access-Client-Id"] = client_id
        headers["CF-Access-Client-Secret"] = client_secret
    return headers


class AliasHttpClient:
    def __init__(self, base_url: str, *, headers: dict[str, str] | None = None,
                 timeout: float = 10.0, retries: int = 2, max_file_bytes: int = MAX_FILE_BYTES_DEFAULT,
                 max_manifest_bytes: int = MAX_MANIFEST_BYTES_DEFAULT,
                 allow_insecure_loopback: bool = False, sleep: Callable[[float], None] = time.sleep):
        if timeout <= 0 or retries < 0 or max_file_bytes < 1 or max_manifest_bytes < 1:
            raise ArtifactFetchError("timeout, retry, and byte limits are invalid")
        self.origin, self.scheme = normalize_base_url(base_url, allow_insecure_loopback=allow_insecure_loopback)
        self.headers = dict(headers or {"Accept": "*/*", "Accept-Encoding": "identity"})
        self.timeout = timeout
        self.retries = retries
        self.max_file_bytes = max_file_bytes
        self.max_manifest_bytes = max_manifest_bytes
        self.sleep = sleep
        self.opener = build_opener(_NoRedirect())

    def _get(self, path: str, *, kind: str, allow_404: bool = False,
             allow_manifest_html: bool = False) -> tuple[int, bytes | None, str | None]:
        relative = _safe_relative_path(path)
        limit = self.max_manifest_bytes if kind == "manifest" else self.max_file_bytes
        allowed_types = {
            "manifest": {"application/json"},
            "json": {"application/json"},
            "html": {"text/html"},
            "css": {"text/css"},
            "javascript": {"text/javascript", "application/javascript", "application/x-javascript"},
        }[kind]
        request = Request(f"{self.origin}/{relative}", headers=self.headers, method="GET")
        attempts = self.retries + 1
        for attempt in range(attempts):
            retryable = False
            try:
                with self.opener.open(request, timeout=self.timeout) as response:
                    status = response.status
                    if status != 200:
                        raise ArtifactFetchError(f"HTTP status {status} for {relative}")
                    media_type = response.headers.get_content_type().lower()
                    html_manifest = kind == "manifest" and allow_manifest_html and media_type == "text/html"
                    if media_type not in allowed_types and not html_manifest:
                        raise ArtifactFetchError(f"unexpected Content-Type for {relative}")
                    raw_length = response.headers.get("Content-Length")
                    declared = None
                    if raw_length is not None:
                        if not raw_length.isdigit():
                            raise ArtifactFetchError(f"invalid Content-Length for {relative}")
                        declared = int(raw_length)
                        if declared > limit:
                            raise ArtifactFetchError(f"download byte limit exceeded for {relative}")
                    body = bytearray()
                    while True:
                        chunk = response.read(min(64 * 1024, limit + 1 - len(body)))
                        if not chunk:
                            break
                        body.extend(chunk)
                        if len(body) > limit:
                            raise ArtifactFetchError(f"download byte limit exceeded for {relative}")
                    if declared is not None and len(body) != declared:
                        raise _RetryableTransferError(f"incomplete response body for {relative}")
                    return status, bytes(body), media_type
            except HTTPError as error:
                error.close()
                if allow_404 and error.code == 404:
                    return 404, None, None
                retryable = error.code in TRANSIENT_STATUS
                if not retryable or attempt + 1 >= attempts:
                    raise ArtifactFetchError(f"HTTP status {error.code} for {relative}") from None
            except _RetryableTransferError:
                if attempt + 1 >= attempts:
                    raise ArtifactFetchError(f"incomplete response body for {relative}") from None
                retryable = True
            except ArtifactFetchError:
                raise
            except (TimeoutError, socket.timeout, http.client.IncompleteRead, ConnectionResetError,
                    ConnectionAbortedError, BrokenPipeError, URLError) as error:
                if isinstance(error, URLError) and isinstance(error.reason, ssl.SSLError):
                    raise ArtifactFetchError(f"TLS request failed for {relative}") from None
                retryable = True
                if attempt + 1 >= attempts:
                    raise ArtifactFetchError(f"request failed or timed out for {relative}") from None
            if retryable:
                self.sleep(min(0.25 * (2 ** attempt), 2.0))
        raise ArtifactFetchError(f"request failed for {relative}")

    def manifest_probe(self, *, allow_404: bool = False,
                       allow_spa_html: bool = False) -> tuple[int, bytes | None, str | None]:
        return self._get("manifest.json", kind="manifest", allow_404=allow_404,
                         allow_manifest_html=allow_spa_html)

    def manifest(self, *, allow_404: bool = False) -> bytes | None:
        _, body, _ = self.manifest_probe(allow_404=allow_404)
        return body

    def file(self, path: str, *, kind: str) -> bytes:
        _, body, _ = self._get(path, kind=kind)
        assert body is not None
        return body


class _RetryableTransferError(ArtifactFetchError):
    pass


def _parse_manifest(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_object)
        if not isinstance(value, dict):
            raise ArtifactFetchError("manifest root must be an object")
        validate_manifest(value)
        return value
    except (UnicodeError, json.JSONDecodeError, ValueError) as error:
        if isinstance(error, ArtifactFetchError):
            raise
        raise ArtifactFetchError(f"manifest validation failed: {error}") from None


def _validate_release_manifest(raw: bytes) -> dict[str, Any]:
    manifest = _parse_manifest(raw)
    if manifest["releaseDescriptor"] is None:
        raise ArtifactFetchError("release manifest has no current release descriptor")
    if {item["path"] for item in manifest["releaseDescriptor"]["assets"]} != set(STATIC_FILES):
        raise ArtifactFetchError("release manifest static asset set differs from the runtime allowlist")
    return manifest


def _manifest_download_plan(manifest: dict[str, Any], now: datetime) -> tuple[set[str], dict[str, Any], str | None]:
    if manifest["releaseDescriptor"] is None:
        raise ArtifactFetchError("release manifest has no current release descriptor")
    asset_paths = {item["path"] for item in manifest["releaseDescriptor"]["assets"]}
    if asset_paths != set(STATIC_FILES):
        raise ArtifactFetchError("release manifest static asset set differs from the runtime allowlist")
    paths = set(STATIC_FILES)
    retained = []
    for item in manifest["retainedReleases"]:
        until = _parse_timestamp(item["retainUntil"])
        if now < until + timedelta(hours=24):
            if item.get("releaseDescriptor") is None:
                raise ArtifactFetchError("active retained release has no verifiable descriptor")
            retained.append(item)
            paths.update(record["url"].lstrip("/") for record in item["stations"].values())
    normalized = dict(manifest)
    normalized["retainedReleases"] = retained
    legacy = manifest["legacyCompatibilityV1"]
    if legacy is not None and now >= _parse_timestamp(legacy["expiresAt"]) + timedelta(hours=24):
        normalized["legacyCompatibilityV1"] = None
        legacy = None
    if legacy is not None:
        paths.update(record["url"].lstrip("/") for record in legacy["stations"].values())
    paths.update(record["url"].lstrip("/") for record in manifest["stations"].values())
    safe = {_safe_relative_path(path) for path in paths}
    return safe, normalized, (legacy["sourceLegacyDigest"] if legacy is not None else None)


def _parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        raise ArtifactFetchError("manifest has an invalid timestamp") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ArtifactFetchError("manifest timestamp has no timezone")
    return parsed.astimezone(timezone.utc)


def _mime_kind(relative: str) -> str:
    if relative.endswith(".json"):
        return "json"
    if relative.endswith(".html"):
        return "html"
    if relative.endswith(".css"):
        return "css"
    if relative.endswith((".js", ".mjs")):
        return "javascript"
    raise ArtifactFetchError("manifest references an unsupported file type")


def _write_file(root: Path, relative: str, raw: bytes) -> None:
    safe = _safe_relative_path(relative)
    path = root.joinpath(*PurePosixPath(safe).parts)
    if path.exists() or path.is_symlink():
        raise ArtifactFetchError("artifact path collision")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)


def _file_fingerprint(records: dict[str, bytes]) -> str:
    framed = {name: {"sha256": sha256_hex(raw), "bytes": len(raw)}
              for name, raw in sorted(records.items())}
    return sha256_hex(canonicalize_jcs(framed))


def _measure(root: Path, *, max_files: int, max_total_bytes: int, max_file_bytes: int) -> dict[str, int]:
    paths = list(root.rglob("*"))
    for path in paths:
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode):
            raise ArtifactFetchError("downloaded artifact contains a symbolic link")
        if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
            raise ArtifactFetchError("downloaded artifact contains a non-regular path")
    files = [path for path in paths if path.is_file()]
    if len(files) > max_files:
        raise ArtifactFetchError("downloaded artifact file count exceeds limit")
    sizes = [path.stat().st_size for path in files]
    total = sum(sizes)
    largest = max(sizes, default=0)
    if largest > max_file_bytes:
        raise ArtifactFetchError("downloaded artifact file exceeds byte limit")
    if total > max_total_bytes:
        raise ArtifactFetchError("downloaded artifact total exceeds byte limit")
    return {"files": len(files), "total_bytes": total, "largest_file_bytes": largest}


def _validate_snapshot(root: Path, mode: str) -> dict[str, Any]:
    try:
        return validate_release_managed_artifact(root) if mode == "release-managed" else validate_artifact(root)
    except ArtifactValidationError as error:
        raise ArtifactFetchError(f"downloaded {mode} artifact failed independent validation: {error}") from None


def _check_new_destination(output: Path) -> tuple[Path, Path]:
    output = output.expanduser().absolute()
    if os.path.lexists(output):
        raise ArtifactFetchError("output must not already exist")
    if not output.parent.is_dir() or any(parent.is_symlink() for parent in (output.parent, *output.parent.parents)):
        raise ArtifactFetchError("output parent must exist and contain no symlink components")
    return output, output.parent


def _fetch_legacy_snapshot(client: AliasHttpClient, root: Path, *, max_total_bytes: int,
                           max_files: int,
                           prefetched: dict[str, bytes] | None = None) -> tuple[dict[str, bytes], str]:
    if len(LEGACY_ASSETS) > max_files:
        raise ArtifactFetchError("legacy snapshot file count exceeds limit")
    records: dict[str, bytes] = dict(prefetched or {})
    total = sum(len(raw) for raw in records.values())
    if set(records) - set(LEGACY_ASSETS) or total > max_total_bytes:
        raise ArtifactFetchError("legacy snapshot prefetched files exceed the allowed set or byte limit")
    for relative, raw in records.items():
        _write_file(root, relative, raw)
    for relative in LEGACY_ASSETS:
        if relative in records:
            continue
        raw = client.file(relative, kind=_mime_kind(relative))
        total += len(raw)
        if total > max_total_bytes:
            raise ArtifactFetchError("legacy snapshot total exceeds byte limit")
        records[relative] = raw
        _write_file(root, relative, raw)
    _validate_snapshot(root, "legacy")
    return records, _file_fingerprint(records)


def _probe_legacy_absence(client: AliasHttpClient, *, allow_initial_legacy: bool
                          ) -> tuple[str, dict[str, bytes], bytes | None]:
    """Classify a missing manifest without treating arbitrary HTML as legacy."""
    status, body, media_type = client.manifest_probe(
        allow_404=True, allow_spa_html=allow_initial_legacy)
    if status == 404:
        return "http-404", {}, None
    if status == 200 and media_type == "text/html" and body is not None:
        # Pages serves /index.html for an unknown path when SPA fallback is active.
        # Only accept that exact response, and only after the caller's explicit migration opt-in.
        root_html = client.file("index.html", kind="html")
        if body != root_html:
            raise ArtifactFetchError("manifest HTML response does not match the root index.html")
        return "spa-html", {"index.html": root_html}, body
    return "manifest-present", {}, body


def _confirm_legacy_absence(client: AliasHttpClient, *, expected_kind: str,
                            expected_html: bytes | None = None) -> None:
    status, body, media_type = client.manifest_probe(
        allow_404=True, allow_spa_html=(expected_kind == "spa-html"))
    if expected_kind == "http-404":
        if status != 404:
            raise ArtifactFetchError("Production alias changed from legacy during fetch")
        return
    if expected_kind != "spa-html" or status != 200 or media_type != "text/html" \
       or body is None or body != expected_html:
        raise ArtifactFetchError("Production alias changed from SPA fallback during fetch")
    current_root = client.file("index.html", kind="html")
    if current_root != expected_html:
        raise ArtifactFetchError("root index.html changed during legacy fetch")


def _fetch_release_snapshot(client: AliasHttpClient, root: Path, raw_manifest: bytes, manifest: dict[str, Any],
                            *, now: datetime, max_total_bytes: int,
                            max_files: int) -> tuple[dict[str, bytes], dict[str, Any]]:
    plan, normalized, _ = _manifest_download_plan(manifest, now)
    if len(plan) + 1 > max_files:
        raise ArtifactFetchError("release snapshot file count exceeds limit")
    records: dict[str, bytes] = {}
    total = len(raw_manifest)
    for relative in sorted(plan):
        raw = client.file(relative, kind=_mime_kind(relative))
        total += len(raw)
        if total > max_total_bytes:
            raise ArtifactFetchError("release snapshot total exceeds byte limit")
        records[relative] = raw
        _write_file(root, relative, raw)
    manifest_bytes = raw_manifest if normalized == manifest else encode_manifest(normalized)
    if total - len(raw_manifest) + len(manifest_bytes) > max_total_bytes:
        raise ArtifactFetchError("release snapshot total exceeds byte limit")
    _write_file(root, "manifest.json", manifest_bytes)
    return records, normalized


def fetch_production_artifact(*, base_url: str, output: Path,
                              client_id: str | None = None, client_secret: str | None = None,
                              allow_initial_legacy: bool = False, as_of: datetime | None = None,
                              timeout: float = 10.0, retries: int = 2,
                              max_file_bytes: int = MAX_FILE_BYTES_DEFAULT,
                              max_manifest_bytes: int = MAX_MANIFEST_BYTES_DEFAULT,
                              max_total_bytes: int = MAX_TOTAL_BYTES_DEFAULT,
                              max_files: int = MAX_FILES_DEFAULT,
                              allow_insecure_loopback: bool = False,
                              sleep: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    """Fetch an immutable-by-fingerprint alias snapshot into a new validated directory."""
    output_path, parent = _check_new_destination(output)
    if max_files < 1 or max_total_bytes < 1:
        raise ArtifactFetchError("file count and total byte limits must be positive")
    if as_of is not None and (as_of.tzinfo is None or as_of.utcoffset() is None):
        raise ArtifactFetchError("as-of timestamp requires an explicit timezone")
    now = (as_of or datetime.now(timezone.utc)).astimezone(timezone.utc)
    client = AliasHttpClient(base_url, headers=access_headers(client_id, client_secret), timeout=timeout,
        retries=retries, max_file_bytes=max_file_bytes, max_manifest_bytes=max_manifest_bytes,
        allow_insecure_loopback=allow_insecure_loopback, sleep=sleep)
    temporary = Path(tempfile.mkdtemp(prefix="dotchi-alias-fetch-", dir=parent))
    stage = temporary / "artifact"
    try:
        stage.mkdir()
        initial_kind, prefetched, initial_manifest = _probe_legacy_absence(
            client, allow_initial_legacy=allow_initial_legacy)
        if initial_kind != "manifest-present":
            if not allow_initial_legacy:
                raise ArtifactFetchError("manifest is absent; legacy mode requires explicit initial-migration opt-in")
            records, initial_fingerprint = _fetch_legacy_snapshot(client, stage,
                max_total_bytes=max_total_bytes, max_files=max_files, prefetched=prefetched)
            _confirm_legacy_absence(client, expected_kind=initial_kind,
                                    expected_html=initial_manifest if initial_kind == "spa-html" else None)
            second_records: dict[str, bytes] = {}
            total = 0
            for relative in LEGACY_ASSETS:
                raw = client.file(relative, kind=_mime_kind(relative))
                total += len(raw)
                if total > max_total_bytes:
                    raise ArtifactFetchError("legacy fingerprint pass exceeds byte limit")
                second_records[relative] = raw
            final_fingerprint = _file_fingerprint(second_records)
            if final_fingerprint != initial_fingerprint:
                raise ArtifactFetchError("legacy Production alias changed during fetch")
            _confirm_legacy_absence(client, expected_kind=initial_kind,
                                    expected_html=initial_manifest if initial_kind == "spa-html" else None)
            validation = _validate_snapshot(stage, "legacy")
            stats = _measure(stage, max_files=max_files, max_total_bytes=max_total_bytes,
                             max_file_bytes=max_file_bytes)
            if os.path.lexists(output_path):
                raise ArtifactFetchError("output appeared during fetch; refusing to replace it")
            os.replace(stage, output_path)
            return {**stats, "mode": "legacy", "fingerprint": initial_fingerprint,
                    "files_validated": validation["files"], "release_id": None}

        assert initial_manifest is not None
        manifest = _validate_release_manifest(initial_manifest)
        initial_fingerprint = sha256_hex(initial_manifest)
        records, normalized = _fetch_release_snapshot(client, stage, initial_manifest, manifest,
            now=now, max_total_bytes=max_total_bytes, max_files=max_files)
        final_manifest = client.manifest()
        if final_manifest is None or sha256_hex(final_manifest) != initial_fingerprint:
            raise ArtifactFetchError("release-managed Production alias manifest changed during fetch")
        # Every fetched release JSON is bound to the initial raw manifest; the independent validator checks all bytes.
        validation = _validate_snapshot(stage, "release-managed")
        stats = _measure(stage, max_files=max_files, max_total_bytes=max_total_bytes,
                         max_file_bytes=max_file_bytes)
        if os.path.lexists(output_path):
            raise ArtifactFetchError("output appeared during fetch; refusing to replace it")
        os.replace(stage, output_path)
        return {**stats, "mode": "release-managed", "fingerprint": initial_fingerprint,
                "release_id": manifest["releaseId"], "retained_releases": len(normalized["retainedReleases"]),
                "legacy_compatibility": normalized["legacyCompatibilityV1"] is not None,
                "files_validated": validation["files"]}
    except (OSError, ArtifactValidationError, ValueError) as error:
        if isinstance(error, ArtifactFetchError):
            raise
        raise ArtifactFetchError(f"Production artifact fetch failed: {error}") from None
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def production_fingerprint(*, base_url: str, mode: str, allow_initial_legacy: bool = False,
                           client_id: str | None = None, client_secret: str | None = None,
                           timeout: float = 10.0, retries: int = 2,
                           max_file_bytes: int = MAX_FILE_BYTES_DEFAULT,
                           max_manifest_bytes: int = MAX_MANIFEST_BYTES_DEFAULT,
                           max_total_bytes: int = MAX_TOTAL_BYTES_DEFAULT,
                           max_files: int = MAX_FILES_DEFAULT,
                           allow_insecure_loopback: bool = False,
                           sleep: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    """Capture a deploy-preflight fingerprint for the caller's expected alias mode."""
    if mode not in {"release-managed", "legacy"}:
        raise ArtifactFetchError("fingerprint mode must be release-managed or legacy")
    if max_files < 1 or max_total_bytes < 1:
        raise ArtifactFetchError("file count and total byte limits must be positive")
    client = AliasHttpClient(base_url, headers=access_headers(client_id, client_secret), timeout=timeout,
        retries=retries, max_file_bytes=max_file_bytes, max_manifest_bytes=max_manifest_bytes,
        allow_insecure_loopback=allow_insecure_loopback, sleep=sleep)
    if mode == "release-managed":
        raw = client.manifest()
        if raw is None:
            raise ArtifactFetchError("expected release-managed manifest is absent")
        manifest = _validate_release_manifest(raw)
        fingerprint = sha256_hex(raw)
        return {"mode": mode, "fingerprint": fingerprint, "release_id": manifest["releaseId"]}
    if not allow_initial_legacy:
        # Keep the non-migration fingerprint path strict: only JSON manifest responses are accepted.
        raw = client.manifest(allow_404=True)
        if raw is not None:
            raise ArtifactFetchError("expected legacy alias but manifest exists; no fallback is permitted")
        raise ArtifactFetchError("legacy fingerprint requires explicit initial-migration opt-in")
    absence_kind, _, raw = _probe_legacy_absence(client, allow_initial_legacy=True)
    if absence_kind == "manifest-present":
        raise ArtifactFetchError("expected legacy alias but manifest exists; no fallback is permitted")
    initial_html = raw if absence_kind == "spa-html" else None
    with tempfile.TemporaryDirectory(prefix=".dotchi-legacy-fingerprint-", dir=Path.cwd()) as temp_name:
        if len(LEGACY_ASSETS) > max_files:
            raise ArtifactFetchError("legacy fingerprint file count exceeds limit")
        root = Path(temp_name)
        records: dict[str, bytes] = {}
        total = 0
        for relative in LEGACY_ASSETS:
            body = client.file(relative, kind=_mime_kind(relative))
            total += len(body)
            if total > max_total_bytes:
                raise ArtifactFetchError("legacy fingerprint total exceeds byte limit")
            records[relative] = body
            _write_file(root, relative, body)
        _validate_snapshot(root, "legacy")
        fingerprint = _file_fingerprint(records)
        # A second read closes the race during the legacy fingerprint capture.
        second: dict[str, bytes] = {}
        second_total = 0
        for relative in LEGACY_ASSETS:
            body = client.file(relative, kind=_mime_kind(relative))
            second_total += len(body)
            if second_total > max_total_bytes:
                raise ArtifactFetchError("legacy fingerprint recheck exceeds byte limit")
            second[relative] = body
        if _file_fingerprint(second) != fingerprint:
            raise ArtifactFetchError("legacy Production alias changed during fingerprint capture")
        _confirm_legacy_absence(client, expected_kind=absence_kind, expected_html=initial_html)
        return {"mode": mode, "fingerprint": fingerprint, "release_id": None}


def verify_expected_fingerprint(*, base_url: str, expected: str, mode: str,
                                allow_initial_legacy: bool = False, **options: Any) -> dict[str, Any]:
    result = production_fingerprint(base_url=base_url, mode=mode,
        allow_initial_legacy=allow_initial_legacy, **options)
    result["expected"] = expected
    result["matches"] = result["fingerprint"] == expected
    if not result["matches"]:
        raise ArtifactFetchError("Production alias fingerprint changed since the captured snapshot")
    return result


def _env_headers() -> tuple[str | None, str | None]:
    return os.environ.get("CF_ACCESS_CLIENT_ID"), os.environ.get("CF_ACCESS_CLIENT_SECRET")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    fetch = sub.add_parser("fetch", help="fetch and validate an artifact snapshot")
    fetch.add_argument("--base-url", required=True)
    fetch.add_argument("--output", type=Path, required=True)
    fetch.add_argument("--allow-initial-legacy-migration", action="store_true")
    fetch.add_argument("--as-of", help="timezone-aware ISO timestamp; default is current UTC time")
    fingerprint = sub.add_parser("fingerprint", help="capture or compare a deploy-preflight alias fingerprint")
    fingerprint.add_argument("--base-url", required=True)
    fingerprint.add_argument("--mode", choices=("release-managed", "legacy"), required=True)
    fingerprint.add_argument("--expected-sha256")
    fingerprint.add_argument("--allow-initial-legacy-migration", action="store_true")
    for child in (fetch, fingerprint):
        child.add_argument("--timeout", type=float, default=10.0)
        child.add_argument("--retries", type=int, default=2)
        child.add_argument("--max-file-bytes", type=int, default=MAX_FILE_BYTES_DEFAULT)
        child.add_argument("--max-manifest-bytes", type=int, default=MAX_MANIFEST_BYTES_DEFAULT)
        child.add_argument("--max-total-bytes", type=int, default=MAX_TOTAL_BYTES_DEFAULT)
        child.add_argument("--max-files", type=int, default=MAX_FILES_DEFAULT)
        child.add_argument("--allow-insecure-localhost", action="store_true")
    args = parser.parse_args()
    client_id, client_secret = _env_headers()
    options = {"client_id": client_id, "client_secret": client_secret,
        "timeout": args.timeout, "retries": args.retries,
        "max_file_bytes": args.max_file_bytes, "max_manifest_bytes": args.max_manifest_bytes,
        "max_total_bytes": args.max_total_bytes, "max_files": args.max_files,
        "allow_insecure_loopback": args.allow_insecure_localhost}
    try:
        if args.command == "fetch":
            instant = datetime.fromisoformat(args.as_of.replace("Z", "+00:00")) if args.as_of else None
            if instant is not None and (instant.tzinfo is None or instant.utcoffset() is None):
                raise ArtifactFetchError("--as-of requires an explicit timezone offset")
            result = fetch_production_artifact(base_url=args.base_url, output=args.output,
                allow_initial_legacy=args.allow_initial_legacy_migration, as_of=instant, **options)
        elif args.expected_sha256:
            result = verify_expected_fingerprint(base_url=args.base_url, expected=args.expected_sha256,
                mode=args.mode, allow_initial_legacy=args.allow_initial_legacy_migration, **options)
        else:
            result = production_fingerprint(base_url=args.base_url, mode=args.mode,
                allow_initial_legacy=args.allow_initial_legacy_migration, **options)
    except (ArtifactFetchError, OSError, ValueError) as error:
        print(f"production artifact fetch failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
