#!/usr/bin/env python3
"""Read-only independent validation of a completed public static artifact."""
from __future__ import annotations

from datetime import date
from html.parser import HTMLParser
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
from typing import Any

# Keep this validator read-only, including Python's import cache.
sys.dont_write_bytecode = True
from public_payload_profile import PUBLIC_DATA_SCOPE, validate_public_payload  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
STATION_FILES = {
    "Kanamecho": "timetable-Kanamecho.json",
    "Senkawa": "timetable-Senkawa.json",
    "KotakeMukaihara": "timetable-KotakeMukaihara.json",
    "Hikawadai": "timetable.json",
    "Heiwadai": "timetable-Heiwadai.json",
    "ChikatetsuAkatsuka": "timetable-ChikatetsuAkatsuka.json",
    "ChikatetsuNarimasu": "timetable-ChikatetsuNarimasu.json",
    "Wakoshi": "timetable-Wakoshi.json",
}
JS_MODULES = frozenset({
    "preview_public.js", "preview_core.mjs", "timetable_adapter.mjs",
    "local_preview_payload_loader.mjs", "selection.mjs", "terminal_ui.mjs",
})
EXPECTED_FILES = frozenset({
    "index.html", "styles.css", "preview.css", *JS_MODULES, *STATION_FILES.values(),
})
DIAGNOSTIC_MARKERS = (
    "debugnow", "perf=1", "preview_diagnostics.css", "performance_metrics.mjs", "virtual_now.mjs",
)
DIAGNOSTIC_DOM_MARKERS = (
    "debug-now-banner", "payload-metadata", "performance-panel", "performance-history", "performance-copy",
)
SYNTHETIC_SECRET_SENTINELS = (
    "synthetic-secret-sentinel", "synthetic_api_key_sentinel", "synthetic-odpt-secret-sentinel",
)
API_KEY_PATTERN = re.compile(
    r"(?i)\b(?:api[_-]?key|client[_-]?secret|access[_-]?token|authorization)\b"
)
BEARER_PATTERN = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{12,}")
KEY_VALUE_PATTERN = re.compile(
    r"(?i)\b(?:api[_-]?key|client[_-]?secret|access[_-]?token)\b\s*[:=]\s*[\"']?[^\s\"'<>]{8,}"
)
TOKEN_PATTERN = re.compile(r"\b(?:sk|pk)-[A-Za-z0-9_-]{16,}\b")
ABSOLUTE_PATH_PATTERN = re.compile(
    r"(?:/(?:Users|home|tmp|Volumes)/[^\s\"']+|/private/(?:tmp|var)/[^\s\"']+|"
    r"[A-Za-z]:\\Users\\[^\s\"']+)"
)
CSS_URL_PATTERN = re.compile(r"url\(\s*[\"']?([^\"')]+)[\"']?\s*\)", re.IGNORECASE)
STATIC_IMPORT_PATTERN = re.compile(
    r"^\s*import\s+(?:[^'\"]*?\s+from\s+)?['\"]([^'\"]+)['\"]\s*;?"
    r"|^\s*export\s+[^'\"]*?\s+from\s+['\"]([^'\"]+)['\"]\s*;?",
    re.MULTILINE,
)


class ArtifactValidationError(ValueError):
    """An artifact failed a safe-public-output check."""


class _HtmlReferences(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.scripts: list[tuple[str | None, str | None]] = []
        self.stylesheets: list[str] = []
        self.inline_script = False
        self.inline_handler = False
        self.embedded_document = False
        self.ids: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if values.get("id"):
            self.ids.add(values["id"] or "")
        if any(name.lower().startswith("on") for name, _ in attrs):
            self.inline_handler = True
        if tag.lower() == "script":
            src = values.get("src")
            self.scripts.append((src, values.get("type")))
            if not src:
                self.inline_script = True
        elif tag.lower() == "link" and "stylesheet" in (values.get("rel") or "").lower().split():
            self.stylesheets.append(values.get("href") or "")
        elif tag.lower() in {"iframe", "object", "embed"}:
            self.embedded_document = True


def _path_has_symlink_component(path: Path) -> bool:
    absolute = Path(os.path.abspath(path.expanduser()))
    cursor = Path(absolute.anchor)
    for component in absolute.parts[1:]:
        cursor = cursor / component
        try:
            mode = cursor.lstat().st_mode
        except FileNotFoundError:
            return True
        if stat.S_ISLNK(mode):
            return True
    return False


def _artifact_root(argument: Path) -> Path:
    if _path_has_symlink_component(argument):
        raise ArtifactValidationError("artifact path contains a symlink or missing path component")
    root = argument.expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ArtifactValidationError("artifact path must be a directory")
    return root


def _check_file_set(root: Path) -> None:
    entries = list(root.iterdir())
    if any(entry.is_symlink() for entry in entries):
        raise ArtifactValidationError("artifact directory contains a symlink")
    if any(not entry.is_file() for entry in entries):
        raise ArtifactValidationError("artifact directory contains a nested or non-regular entry")
    actual = {entry.name for entry in entries}
    if actual != EXPECTED_FILES:
        missing = EXPECTED_FILES - actual
        extra = actual - EXPECTED_FILES
        if missing:
            raise ArtifactValidationError("one or more required artifact files are missing")
        if extra:
            raise ArtifactValidationError("unexpected artifact file is present")
        raise ArtifactValidationError("artifact file set does not match the public allowlist")
    for entry in entries:
        if not stat.S_ISREG(entry.lstat().st_mode):
            raise ArtifactValidationError("artifact entry is not a regular file")


def _read_text(root: Path, filename: str) -> str:
    try:
        raw = (root / filename).read_bytes()
        return raw.decode("utf-8")
    except (OSError, UnicodeError):
        raise ArtifactValidationError("an artifact file is unreadable or not UTF-8") from None


def _check_html(contents: dict[str, str]) -> None:
    parser = _HtmlReferences()
    try:
        parser.feed(contents["index.html"])
        parser.close()
    except Exception:
        raise ArtifactValidationError("index.html is malformed") from None
    if parser.scripts != [("preview_public.js", "module")]:
        raise ArtifactValidationError("HTML must load only preview_public.js as a module")
    if parser.stylesheets != ["styles.css", "preview.css"]:
        raise ArtifactValidationError("HTML stylesheet references or order are invalid")
    if parser.inline_script or parser.inline_handler or parser.embedded_document:
        raise ArtifactValidationError("inline code or embedded documents are not allowed")
    required_dom_ids = {
        "clock", "timetable-status", "board", "destination-trigger", "route-display",
        "destination-dialog", "destination-close", "destination-list", "direct-only", "mode-line", "mode-departure",
    }
    if not required_dom_ids.issubset(parser.ids):
        raise ArtifactValidationError("public HTML is missing required runtime DOM elements")
    if re.search(r"(?i)\b(?:src|href)\s*=\s*[\"'](?:https?:|//|\.\.?/\.\.)", contents["index.html"]):
        raise ArtifactValidationError("HTML references an external or out-of-directory resource")
    lowered = contents["index.html"].lower()
    if any(marker in lowered for marker in (*DIAGNOSTIC_MARKERS, *DIAGNOSTIC_DOM_MARKERS)):
        raise ArtifactValidationError("local diagnostic HTML is present")
    if re.search(r"(?i)\bid\s*=\s*[\"'](?:debug|performance|payload-metadata|meta-)", lowered):
        raise ArtifactValidationError("local diagnostic DOM is present")
    # The public shell has a fixed public entrypoint and no root-mock application scripts.
    if re.search(r"(?i)(?:app|data)\.js", lowered):
        raise ArtifactValidationError("root mock script reference is present")


def _check_import_graph(contents: dict[str, str]) -> None:
    reached: set[str] = set()
    pending = ["preview_public.js"]
    while pending:
        source_name = pending.pop()
        if source_name in reached:
            continue
        if source_name not in JS_MODULES:
            raise ArtifactValidationError("JavaScript imports a module outside the public allowlist")
        source = contents[source_name]
        if re.search(r"\bimport\s*\(", source):
            raise ArtifactValidationError("dynamic JavaScript imports are not allowed")
        reached.add(source_name)
        for match in STATIC_IMPORT_PATTERN.finditer(source):
            specifier = match.group(1) or match.group(2)
            if not specifier.startswith("./") or "\\" in specifier or "?" in specifier or "#" in specifier:
                raise ArtifactValidationError("JavaScript import must be a local relative module reference")
            resolved = str(PurePosixPath(source_name).parent.joinpath(specifier))
            if resolved.startswith("../") or resolved not in JS_MODULES:
                raise ArtifactValidationError("JavaScript import escapes the public module allowlist")
            if resolved not in contents:
                raise ArtifactValidationError("JavaScript import target is missing")
            pending.append(resolved)
    if reached != JS_MODULES:
        raise ArtifactValidationError("public JavaScript module dependency graph is incomplete")


def _check_payload_references(contents: dict[str, str]) -> None:
    source = contents["local_preview_payload_loader.mjs"]
    match = re.search(r"DESTINATION_PAYLOADS\s*=\s*Object\.freeze\(\{([\s\S]*?)\}\)", source)
    if not match:
        raise ArtifactValidationError("station payload mapping is missing from the public loader")
    actual = dict(re.findall(r"([A-Za-z]+)\s*:\s*['\"]([^'\"]+)['\"]", match.group(1)))
    expected = {station: "./" + filename for station, filename in STATION_FILES.items()}
    if actual != expected:
        raise ArtifactValidationError("public loader payload references do not match the eight station files")
    adapter = contents["timetable_adapter.mjs"]
    if not re.search(r"PUBLIC_DATA_SCOPE\s*=\s*['\"]public-display-v1['\"]", adapter):
        raise ArtifactValidationError("shared adapter does not define the public payload profile")


def _check_js_syntax(root: Path) -> None:
    node = shutil.which("node")
    if not node:
        raise ArtifactValidationError("Node.js is required for JavaScript syntax verification")
    for filename in sorted(JS_MODULES):
        try:
            result = subprocess.run([node, "--check", str(root / filename)],
                                    capture_output=True, text=True, timeout=20)
        except (OSError, subprocess.SubprocessError):
            raise ArtifactValidationError("JavaScript syntax verification could not run") from None
        if result.returncode:
            raise ArtifactValidationError("a public JavaScript module has invalid syntax")


def _check_payloads(contents: dict[str, str]) -> list[str]:
    common_dates: list[str] | None = None
    for destination_id, filename in STATION_FILES.items():
        try:
            payload = json.loads(contents[filename], object_pairs_hook=_unique_object)
        except (json.JSONDecodeError, _DuplicateJsonMember):
            raise ArtifactValidationError("a station payload is invalid JSON") from None
        if not isinstance(payload, dict):
            raise ArtifactValidationError("station payload root must be a JSON object")
        if type(payload.get("schemaVersion")) is not int or payload["schemaVersion"] != 1:
            raise ArtifactValidationError("station payload schema version is not supported")
        if payload.get("dataScope") != PUBLIC_DATA_SCOPE:
            raise ArtifactValidationError("station payload profile is not public-display-v1")
        raw_days = payload.get("serviceDays")
        if not isinstance(raw_days, list):
            raise ArtifactValidationError("station payload has no service days")
        for raw_day in raw_days:
            if isinstance(raw_day, dict) and (
                raw_day.get("originStationId") != "Ikebukuro"
                or raw_day.get("destinationStationId") != destination_id
            ):
                raise ArtifactValidationError("station payload origin/destination does not match its filename")
        try:
            validate_public_payload(payload)
        except (TypeError, ValueError):
            raise ArtifactValidationError("station payload failed the public schema and allowlist checks") from None
        days = payload.get("serviceDays")
        if not isinstance(days, list) or not days:
            raise ArtifactValidationError("station payload has no service days")
        dates: list[str] = []
        for day in days:
            if not isinstance(day, dict):
                raise ArtifactValidationError("station payload has an invalid service day")
            service_date = day.get("serviceDate")
            try:
                parsed = date.fromisoformat(service_date) if isinstance(service_date, str) else None
            except ValueError:
                parsed = None
            if parsed is None or parsed.isoformat() != service_date:
                raise ArtifactValidationError("station payload contains an invalid serviceDate")
            dates.append(service_date)
            if day.get("originStationId") != "Ikebukuro" or day.get("destinationStationId") != destination_id:
                raise ArtifactValidationError("station payload origin/destination does not match its filename")
            if not isinstance(day.get("departures"), list) or not day["departures"]:
                raise ArtifactValidationError("station payload service day has no candidate input")
        if common_dates is None:
            common_dates = dates
        elif dates != common_dates:
            raise ArtifactValidationError("station payload serviceDate lists do not match")
    if not common_dates:
        raise ArtifactValidationError("station payload serviceDate list is empty")
    return common_dates


class _DuplicateJsonMember(ValueError):
    pass


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonMember
        result[key] = value
    return result


def _check_content_safety(contents: dict[str, str]) -> None:
    all_text = "\n".join(contents.values())
    lowered = all_text.lower()
    if any(marker in lowered for marker in DIAGNOSTIC_MARKERS):
        raise ArtifactValidationError("local diagnostic code or markup is present")
    html_and_css = "\n".join(contents[name] for name in ("index.html", "styles.css", "preview.css")).lower()
    if any(marker in html_and_css for marker in DIAGNOSTIC_DOM_MARKERS):
        raise ArtifactValidationError("local diagnostic DOM or CSS is present")
    if any(sentinel in lowered for sentinel in SYNTHETIC_SECRET_SENTINELS):
        raise ArtifactValidationError("a secret sentinel is present in the artifact")
    if API_KEY_PATTERN.search(all_text) or BEARER_PATTERN.search(all_text) \
            or KEY_VALUE_PATTERN.search(all_text) or TOKEN_PATTERN.search(all_text):
        raise ArtifactValidationError("credential-like content is present in the artifact")
    if ABSOLUTE_PATH_PATTERN.search(all_text):
        raise ArtifactValidationError("a local absolute path is present in the artifact")
    if re.search(r"(?i)https?://|@import\b", all_text):
        raise ArtifactValidationError("external URLs or CSS imports are not allowed")
    for css_name in ("styles.css", "preview.css"):
        for target in CSS_URL_PATTERN.findall(contents[css_name]):
            if not target.startswith("data:"):
                raise ArtifactValidationError("CSS references an external or unlisted asset")
    # A public bootstrap must pin the profile and browser cache, and must not expose QA hooks.
    entry = contents["preview_public.js"]
    if "expectedProfile: PUBLIC_DATA_SCOPE" not in entry or "cacheMode: 'default'" not in entry \
            or "nowProvider: () => Date.now()" not in entry:
        raise ArtifactValidationError("public entrypoint profile, cache, or clock contract is invalid")
    if re.search(r"(?i)debugnow|perf(?:ormance)?mode|performance_metrics|virtual_now|hooks\s*:", entry):
        raise ArtifactValidationError("public entrypoint contains local QA or performance hooks")
    if "preview.js" in lowered or "prepare_preview" in lowered or "prepare_qa_preview" in lowered:
        raise ArtifactValidationError("local preview or QA implementation is present")


def validate_artifact(directory: Path) -> dict[str, Any]:
    """Inspect an existing artifact without modifying it or invoking the builder."""
    root = _artifact_root(directory)
    _check_file_set(root)
    contents = {name: _read_text(root, name) for name in EXPECTED_FILES}
    _check_content_safety(contents)
    _check_html(contents)
    _check_import_graph(contents)
    _check_payload_references(contents)
    _check_js_syntax(root)
    service_dates = _check_payloads(contents)
    return {"files": len(EXPECTED_FILES), "stations": len(STATION_FILES), "service_dates": service_dates}


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python3 scripts/validate_public_artifact.py ARTIFACT_DIR", file=sys.stderr)
        return 2
    try:
        result = validate_artifact(Path(sys.argv[1]))
    except ArtifactValidationError as error:
        print(f"public artifact validation failed: {error}", file=sys.stderr)
        return 1
    except OSError:
        print("public artifact validation failed: artifact could not be read", file=sys.stderr)
        return 1
    print(f"public artifact valid: {result['files']} files, {result['stations']} stations, "
          + ", ".join(result["service_dates"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
