#!/usr/bin/env python3
"""Serve only a prepared ODPT v2 QA site over IPv4 loopback."""
from __future__ import annotations

import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
import stat
import sys
from datetime import date, timedelta
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import odpt_public_v2 as v2  # noqa: E402
from prepare_odpt_v2_qa import STATIC_FILES, STATE_FILENAME  # noqa: E402

HOST = "127.0.0.1"
STATIC_NAMES = set(STATIC_FILES) | set(v2.ROUTE_FILENAMES.values()) | {STATE_FILENAME}
HTML_NAME = "odpt_v2_qa.html"


class ServeError(Exception):
    pass


def validate_site(directory: Path) -> tuple[Path, dict[str, bytes]]:
    raw = directory.expanduser().absolute()
    for component in (raw, *raw.parents):
        if os.path.lexists(component) and component.is_symlink():
            raise ServeError("site_symlink_rejected")
    site = raw.resolve()
    try:
        site.relative_to(ROOT.resolve())
    except ValueError:
        pass
    else:
        raise ServeError("site_inside_repository")
    if not site.is_dir() or stat.S_IMODE(site.stat().st_mode) != 0o700:
        raise ServeError("site_directory_permissions_invalid")
    entries = list(site.iterdir())
    if {entry.name for entry in entries} != STATIC_NAMES or len(entries) != len(STATIC_NAMES):
        raise ServeError("site_file_set_invalid")
    contents = {}
    for entry in entries:
        if entry.is_symlink() or not entry.is_file() or stat.S_IMODE(entry.stat().st_mode) != 0o600:
            raise ServeError("site_file_permissions_or_type_invalid")
        contents[entry.name] = entry.read_bytes()
    try:
        state = json.loads(contents[STATE_FILENAME])
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ServeError("qa_state_invalid") from None
    if (not isinstance(state, dict) or state.get("schemaVersion") != 1
            or state.get("dataScope") != "private-local-odpt-v2-qa-state"
            or not isinstance(state.get("serviceDates"), list)
            or len(state["serviceDates"]) != 3 or not isinstance(state.get("stations"), dict)
            or set(state["stations"]) != set(v2.DESTINATIONS)
            or not isinstance(state.get("candidateFiles"), dict)
            or set(state["candidateFiles"]) != set(v2.DESTINATIONS)):
        raise ServeError("qa_state_invalid")
    try:
        dates = [date.fromisoformat(value) for value in state["serviceDates"]]
    except (TypeError, ValueError):
        raise ServeError("qa_state_invalid") from None
    if ([value.isoformat() for value in dates] != state["serviceDates"]
            or dates[1] != dates[0] + timedelta(days=1)
            or dates[2] != dates[1] + timedelta(days=1)):
        raise ServeError("qa_state_invalid")
    for station_id in v2.DESTINATIONS:
        station_dates = state["stations"][station_id]
        if not isinstance(station_dates, dict) or set(station_dates) != set(state["serviceDates"]):
            raise ServeError("qa_state_invalid")
        for counts in station_dates.values():
            if (not isinstance(counts, dict) or set(counts) != {
                    "infoCount", "noValidArrivalCount", "otherUnknownCount"}
                    or any(type(value) is not int or value < 0 for value in counts.values())):
                raise ServeError("qa_state_invalid")
    common_generated_at = None
    for station_id in v2.DESTINATIONS:
        integrity = state["candidateFiles"][station_id]
        if (not isinstance(integrity, dict) or set(integrity) != {"sha256", "bytes"}
                or not isinstance(integrity.get("sha256"), str)
                or len(integrity["sha256"]) != 64
                or type(integrity.get("bytes")) is not int or integrity["bytes"] < 1):
            raise ServeError("qa_state_candidate_integrity_invalid")
        candidate_bytes = contents[v2.ROUTE_FILENAMES[station_id]]
        if (len(candidate_bytes) != integrity["bytes"]
                or hashlib.sha256(candidate_bytes).hexdigest() != integrity["sha256"]):
            raise ServeError("candidate_hash_or_bytes_mismatch")
        try:
            payload = json.loads(candidate_bytes)
            v2.validate_v2_payload(payload)
        except (UnicodeDecodeError, json.JSONDecodeError, v2.V2Error, KeyError):
            raise ServeError("candidate_invalid") from None
        if ([day.get("serviceDate") for day in payload.get("serviceDays", [])]
                != state["serviceDates"]):
            raise ServeError("candidate_service_dates_invalid")
        if common_generated_at is None:
            common_generated_at = payload["generatedAt"]
        elif common_generated_at != payload["generatedAt"]:
            raise ServeError("candidate_generation_metadata_mismatch")
    return site, contents


def make_handler(files: dict[str, bytes], port: int):
    allowed_host = f"{HOST}:{port}"

    class Handler(BaseHTTPRequestHandler):
        server_version = "ODPTv2LocalQA"
        sys_version = ""

        def log_message(self, _format, *_args):
            return

        def _respond(self, send_body: bool):
            if self.headers.get("Host", "") != allowed_host:
                self.send_error(400)
                return
            path = urlsplit(self.path).path
            if path == "/":
                path = f"/{HTML_NAME}"
            if path.count("/") != 1 or path[1:] not in files:
                self.send_error(404)
                return
            body = files[path[1:]]
            self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(path)[0] or "application/octet-stream")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cross-Origin-Resource-Policy", "same-origin")
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; script-src 'self'; style-src 'self'; "
                             "connect-src 'self'; img-src 'self' data:; object-src 'none'; "
                             "base-uri 'none'; frame-ancestors 'none'")
            self.end_headers()
            if send_body:
                self.wfile.write(body)

        def do_GET(self):
            self._respond(True)

        def do_HEAD(self):
            self._respond(False)

        def do_POST(self):
            self.send_error(405)

    return Handler


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    if not 1024 <= args.port <= 65535:
        print("FAIL: port_invalid", file=sys.stderr)
        return 1
    try:
        site, files = validate_site(args.directory)
        server = ThreadingHTTPServer((HOST, args.port), make_handler(files, args.port))
    except (ServeError, OSError) as exc:
        code = str(exc) if isinstance(exc, ServeError) else "server_start_failed"
        print(f"FAIL: {code}", file=sys.stderr)
        return 1
    server.daemon_threads = True
    server.timeout = 0.5
    print(f"ODPT v2 QA: http://{HOST}:{args.port}/{HTML_NAME}")
    print(f"source files: {len(files)} local-only files from {site}")
    print("bind: 127.0.0.1 only; no CORS; credentials omitted by browser runtime")
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
