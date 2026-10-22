#!/usr/bin/env python3
"""Download the Tokyo Metro static GTFS ZIP for local research only."""
from pathlib import Path
import os
import socket
import ssl
import sys
import tempfile
import zipfile
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

import certifi

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env.local"
OUT = ROOT / "local_data" / "odpt"
URL = "https://api.odpt.org/api/v4/files/TokyoMetro/data/TokyoMetro-Train-GTFS.zip"
OUTPUT_NAME = "TokyoMetro-Train-GTFS.zip"
TIMEOUT_SECONDS = 45
REQUIRED_GTFS_FILES = {"stops.txt", "routes.txt", "trips.txt", "stop_times.txt"}
ALLOWED_REDIRECT_HOST = "dataodpt.blob.core.windows.net"


class NoRedirectHandler(HTTPRedirectHandler):
    """Keep the fetch to one HTTP request, even if the endpoint redirects."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def read_key():
    try:
        lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return None
    for line in lines:
        entry = line.strip()
        if not entry or entry.startswith("#") or "=" not in entry:
            continue
        name, value = entry.split("=", 1)
        if name.strip() == "ODPT_API_KEY":
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            return value or None
    return None


def network_error(exc):
    if isinstance(exc, HTTPError):
        return "HTTP認証エラー" if exc.code in (401, 403) else "HTTPエラー"
    if isinstance(exc, ssl.SSLError):
        return "TLS証明書エラー"
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return "タイムアウト"
    if isinstance(exc, URLError):
        reason = exc.reason
        if isinstance(reason, socket.gaierror):
            return "DNSエラー"
        if isinstance(reason, ssl.SSLError):
            return "TLS証明書エラー"
        if isinstance(reason, (TimeoutError, socket.timeout)):
            return "タイムアウト"
        return "ネットワークエラー"
    return "通信エラー"


def safe_redirect_url(source_url, location, api_key):
    """Resolve and validate a redirect without exposing its URL or query values."""
    if not location:
        return None
    try:
        destination = urlsplit(urljoin(source_url, location))
        if destination.scheme.lower() != "https":
            return None
        if destination.hostname is None or destination.hostname.lower() != ALLOWED_REDIRECT_HOST:
            return None
        if destination.username is not None or destination.password is not None:
            return None
        if destination.port not in (None, 443):
            return None
        parameters = parse_qsl(destination.query, keep_blank_values=True)
        forbidden_names = {
            "acl:consumerkey", "consumerkey", "key", "api_key", "apikey", "odpt_api_key"
        }
        if any(name.lower() in forbidden_names for name, _ in parameters):
            return None
        if api_key and any(value == api_key for _, value in parameters):
            return None
        return destination.geturl()
    except (TypeError, ValueError):
        return None


def valid_gtfs_zip(path: Path):
    try:
        with zipfile.ZipFile(path) as archive:
            names = [Path(name).name.lower() for name in archive.namelist() if not name.endswith("/")]
            if not REQUIRED_GTFS_FILES.issubset(set(names)):
                return False
            return archive.testzip() is None
    except (OSError, zipfile.BadZipFile, RuntimeError, zipfile.LargeZipFile):
        return False


def main():
    key = read_key()
    if not key:
        print("ODPT_API_KEY が .env.local にありません。通信していません。")
        return 2

    target = OUT / OUTPUT_NAME
    if target.exists():
        print(f"保存先に既存ファイルがあります。上書きせず終了しました: {target.relative_to(ROOT)}")
        return 2

    OUT.mkdir(parents=True, exist_ok=True)
    temp_path = None
    target_created = False
    request = Request(
        URL + "?" + urlencode({"acl:consumerKey": key}),
        headers={"Accept": "application/zip, application/octet-stream"},
        method="GET",
    )
    context = ssl.create_default_context(cafile=certifi.where())
    opener = build_opener(HTTPSHandler(context=context), NoRedirectHandler())
    try:
        # The ODPT request is made first. Only an explicitly validated 302 may
        # cause one additional GET; both requests have automatic redirects off.
        try:
            response_context = opener.open(request, timeout=TIMEOUT_SECONDS)
        except HTTPError as redirect:
            if redirect.code != 302:
                raise
            destination = safe_redirect_url(URL, redirect.headers.get("Location"), key)
            if destination is None:
                print("GTFS取得: 転送先が許可条件を満たさないため停止しました。")
                return 1
            redirect.close()
            # Intentionally construct a fresh request: no API key, Authorization,
            # cookies, or other headers from the ODPT request are copied.
            blob_request = Request(
                destination,
                headers={"Accept": "application/zip, application/octet-stream"},
                method="GET",
            )
            response_context = opener.open(blob_request, timeout=TIMEOUT_SECONDS)

        with response_context as response:
            if response.status != 200:
                print(f"GTFS取得: HTTPエラー ({response.status})")
                return 1
            with tempfile.NamedTemporaryFile(mode="wb", prefix=".gtfs-", suffix=".part", dir=OUT, delete=False) as tmp:
                temp_path = Path(tmp.name)
                os.chmod(temp_path, 0o600)
                while True:
                    block = response.read(1024 * 1024)
                    if not block:
                        break
                    tmp.write(block)

        if not valid_gtfs_zip(temp_path):
            print("GTFS取得: ZIP形式または必須GTFSファイルを検証できません。保存しませんでした。")
            return 1

        # Exclusive creation prevents overwriting even if another file appeared meanwhile.
        try:
            with temp_path.open("rb") as source, target.open("xb") as destination:
                target_created = True
                while True:
                    block = source.read(1024 * 1024)
                    if not block:
                        break
                    destination.write(block)
            os.chmod(target, 0o600)
        except FileExistsError:
            print(f"保存先に既存ファイルがあります。上書きしません: {target.relative_to(ROOT)}")
            return 2
        except OSError:
            if target_created:
                try:
                    target.unlink(missing_ok=True)
                except OSError:
                    pass
            print("GTFS取得: 保存エラー")
            return 1

        print(f"保存しました: {target.relative_to(ROOT)}")
        print("GTFS ZIP検証: OK")
        return 0
    except HTTPError as exc:
        if exc.code in (301, 302, 303, 307, 308):
            print("GTFS取得: 許可されていないHTTPリダイレクトのため停止しました。")
            return 1
        print(f"GTFS取得: {network_error(exc)} ({exc.code})")
        return 1
    except (URLError, ssl.SSLError, TimeoutError, socket.timeout, OSError) as exc:
        print(f"GTFS取得: {network_error(exc)}")
        return 1
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass


if __name__ == "__main__":
    sys.exit(main())
