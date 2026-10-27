#!/usr/bin/env python3
"""Build a local-only, frozen-clock UI harness from synthetic public artifacts."""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import date
import ipaddress
import json
from pathlib import Path
import shutil
import sys
import tempfile
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from build_public_site import PublicSiteBuildError, build_public_site
from synthetic_public_fixture_factory import (
    STATION_FILES,
    SYNTHETIC_MARKER,
    SYNTHETIC_MARKER_CONTENT,
    SyntheticFixtureError,
    generate_fixture_directory,
    make_public_fixture,
)
from validate_public_artifact import ArtifactValidationError, validate_artifact

ROOT = Path(__file__).resolve().parents[1]
SAFE_TEMP_ROOT = Path('/private/tmp')
DEFAULT_ANCHOR_DATE = date(2026, 10, 27)
EVENING_DATE = '2026-10-26'
STATION_IDS = tuple(STATION_FILES)
EVENING_DIRECT_ROWS = (
    ('9', 22 * 3600 + 15 * 60, 22 * 3600 + 34 * 60, 'f-2215'),
    ('6', 22 * 3600 + 30 * 60, 22 * 3600 + 58 * 60, 'y-2230'),
    ('9', 22 * 3600 + 35 * 60, 22 * 3600 + 42 * 60, 'f-2235'),
    ('6', 22 * 3600 + 40 * 60, 22 * 3600 + 55 * 60, 'y-2240'),
    ('9', 22 * 3600 + 45 * 60, 23 * 3600 + 2 * 60, 'f-2245'),
    ('6', 22 * 3600 + 50 * 60, 23 * 3600 + 5 * 60, 'y-2250'),
    ('6', 23 * 3600, 23 * 3600 + 20 * 60, 'y-2300'),
)


class QaHarnessError(ValueError):
    """Raised when the isolated synthetic QA harness cannot be built safely."""


def _time_text(seconds: int) -> str:
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f'{hours:02d}:{minutes:02d}:{seconds:02d}'


def _retime_departure(departure: dict[str, Any], departure_seconds: int, arrival_seconds: int) -> None:
    departure['departureServiceSeconds'] = departure_seconds
    departure['departureText'] = _time_text(departure_seconds)
    for key in ('primary', 'directAlternative', 'bestTransferAlternative'):
        journey = departure.get(key)
        if journey is None:
            continue
        journey['departureServiceSeconds'] = departure_seconds
        journey['arrivalServiceSeconds'] = arrival_seconds
        journey['departureText'] = _time_text(departure_seconds)
        journey['arrivalText'] = _time_text(arrival_seconds)


def _copy_direct(template: dict[str, Any], departure_seconds: int, arrival_seconds: int,
                 trip_id: str) -> dict[str, Any]:
    row = deepcopy(template)
    if row.get('directAlternative') is None:
        raise QaHarnessError('synthetic source template has no direct alternative')
    row['id'] = f'synthetic-qa:{trip_id}'
    row['originTripId'] = f'synthetic-qa-trip:{trip_id}'
    row['primary'] = deepcopy(row['directAlternative'])
    _retime_departure(row, departure_seconds, arrival_seconds)
    return row


def _copy_transfer_only(template: dict[str, Any], departure_seconds: int, arrival_seconds: int,
                        trip_id: str) -> dict[str, Any]:
    row = deepcopy(template)
    transfer = row.get('bestTransferAlternative')
    if transfer is None:
        raise QaHarnessError('synthetic source template has no transfer alternative')
    row['id'] = f'synthetic-qa:{trip_id}'
    row['originTripId'] = f'synthetic-qa-trip:{trip_id}'
    row['directAlternative'] = None
    row['primary'] = deepcopy(transfer)
    row['transferCandidateCount'] = 1
    _retime_departure(row, departure_seconds, arrival_seconds)
    return row


def _recount_public_destination_status(day: dict[str, Any]) -> None:
    status = day['destinationStatus']
    metrics: dict[str, dict[str, int]] = {}
    for route_id in ('6', '9'):
        rows = [row for row in day['departures'] if row['routeId'] == route_id]
        metrics[route_id] = {
            'originTripCount': len(rows),
            'candidateCount': sum(row['primary'] is not None for row in rows),
            'directCandidateCount': sum(row['directAlternative'] is not None for row in rows),
            'transferCandidateCount': sum(row['bestTransferAlternative'] is not None for row in rows),
            'transferPairCount': sum(row['transferCandidateCount'] for row in rows),
            'transferOnlyCount': sum(row['directAlternative'] is None
                                      and row['bestTransferAlternative'] is not None for row in rows),
        }
        route = status['routes'][route_id]
        for key, value in metrics[route_id].items():
            if key in route:
                route[key] = value
        if 'scheduledTripCount' in route:
            route['scheduledTripCount'] = len(rows)
    status.update({
        'status': 'normal',
        'candidateCount': sum(value['candidateCount'] for value in metrics.values()),
        'directCandidateCount': sum(value['directCandidateCount'] for value in metrics.values()),
        'transferCandidateCount': sum(value['transferCandidateCount'] for value in metrics.values()),
        'transferPairCount': sum(value['transferPairCount'] for value in metrics.values()),
        'transferOnlyCount': sum(value['transferOnlyCount'] for value in metrics.values()),
    })


def make_evening_qa_payload(destination_id: str) -> dict[str, Any]:
    """Create a fixed, synthetic evening UI scenario from the tracked fixture templates."""
    service_dates = ['2026-10-25', EVENING_DATE, '2026-10-27', '2026-10-28']
    payload = make_public_fixture(destination_id, service_dates)
    day = next(item for item in payload['serviceDays'] if item['serviceDate'] == EVENING_DATE)
    templates = {row['routeId']: row for row in day['departures']}
    if set(templates) != {'6', '9'}:
        raise QaHarnessError('tracked synthetic templates must include both routes')

    rows = []
    for route_id, depart, arrive, suffix in EVENING_DIRECT_ROWS:
        rows.append(_copy_direct(templates[route_id], depart, arrive, suffix))
    rows.append(_copy_transfer_only(templates['6'], 22 * 3600 + 32 * 60,
                                    22 * 3600 + 40 * 60, 'y-transfer-2232'))
    rows.append(_copy_transfer_only(templates['6'], 23 * 3600 + 5 * 60,
                                    23 * 3600 + 25 * 60, 'y-transfer-2305'))
    day['departures'] = rows
    _recount_public_destination_status(day)
    return payload


def _build_validated_artifact(fixtures: Path, output: Path) -> None:
    try:
        build_public_site(fixtures=fixtures, output=output)
        validate_artifact(output)
    except (PublicSiteBuildError, ArtifactValidationError, OSError) as error:
        raise QaHarnessError('public artifact build or validation failed') from error


def _write_evening_fixtures(directory: Path) -> None:
    directory.mkdir()
    for destination_id, filename in STATION_FILES.items():
        payload = make_evening_qa_payload(destination_id)
        (directory / filename).write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + '\n', encoding='utf-8')
    (directory / SYNTHETIC_MARKER).write_text(SYNTHETIC_MARKER_CONTENT, encoding='utf-8')


def _write_harness_shell(output: Path) -> None:
    baseline_html = (output / 'artifacts' / 'baseline' / 'index.html').read_text(encoding='utf-8')
    replacements = {
        'href="styles.css"': 'href="./artifacts/baseline/styles.css"',
        'href="preview.css"': 'href="./artifacts/baseline/preview.css"',
        'src="preview_public.js"': 'src="./qa_entry.mjs"',
    }
    for old, new in replacements.items():
        if baseline_html.count(old) != 1:
            raise QaHarnessError('validated public shell did not match the expected entrypoint')
        baseline_html = baseline_html.replace(old, new)
    qa_panel = '''\n  <details class="synthetic-qa-panel">
    <summary>固定時刻 synthetic QA</summary>
    <label for="qa-scenario">表示シナリオ</label>
    <select id="qa-scenario">
      <option value="morning-before">始発ゲート前 05:09:59 JST</option>
      <option value="morning-gate">始発ゲート 05:10:00 JST</option>
      <option value="previous-tail">前運行日25:50 01:40 JST</option>
      <option value="evening-before">夜間の始発ゲート前 21:14:59 JST</option>
      <option value="evening-gate">夜間の始発ゲート 21:15:00 JST</option>
      <option value="cards">カード・並び順 22:05:00 JST</option>
      <option value="direct-terminal">直通終電 22:59:59 JST</option>
      <option value="all-terminal">終電 23:04:59 JST</option>
      <option value="ended">全路線終了 23:05:01 JST</option>
    </select>
    <p id="qa-scenario-note">synthetic（架空）fixtureのみ。ローカルQA専用です。</p>
  </details>
  <style>
    .synthetic-qa-panel { position: fixed; z-index: 10000; inset: 8px auto auto 8px;
      padding: 7px 10px; max-width: min(90vw, 340px); border: 1px solid #827b6c;
      border-radius: 8px; background: #fffdf7; color: #292720; font: 12px/1.4 sans-serif;
      box-shadow: 0 2px 10px #0003; }
    .synthetic-qa-panel summary { cursor: pointer; font-weight: 700; }
    .synthetic-qa-panel label, .synthetic-qa-panel select { display: block; margin-top: 6px; }
    .synthetic-qa-panel select { max-width: 82vw; font: inherit; }
    .synthetic-qa-panel p { margin: 5px 0 0; }
  </style>
'''
    if baseline_html.count('<body>') != 1:
        raise QaHarnessError('validated public shell body marker is missing')
    output.joinpath('index.html').write_text(baseline_html.replace('<body>', '<body>' + qa_panel, 1), encoding='utf-8')
    output.joinpath('qa_entry.mjs').write_text(QA_ENTRYPOINT, encoding='utf-8')


QA_ENTRYPOINT = '''import { createPreviewRuntime } from './artifacts/baseline/preview_core.mjs';
import { PUBLIC_DATA_SCOPE } from './artifacts/baseline/timetable_adapter.mjs';
import { DESTINATION_PAYLOADS, DESTINATION_STORAGE_KEY, DISPLAY_MODE_STORAGE_KEY } from './artifacts/baseline/local_preview_payload_loader.mjs';

const scenarios = Object.freeze({
  'morning-before': { artifact: 'baseline', now: '2026-10-27T05:09:59+09:00' },
  'morning-gate': { artifact: 'baseline', now: '2026-10-27T05:10:00+09:00' },
  'previous-tail': { artifact: 'baseline', now: '2026-10-27T01:40:00+09:00' },
  'evening-before': { artifact: 'evening', now: '2026-10-26T21:14:59+09:00' },
  'evening-gate': { artifact: 'evening', now: '2026-10-26T21:15:00+09:00' },
  cards: { artifact: 'evening', now: '2026-10-26T22:05:00+09:00' },
  'direct-terminal': { artifact: 'evening', now: '2026-10-26T22:59:59+09:00' },
  'all-terminal': { artifact: 'evening', now: '2026-10-26T23:04:59+09:00' },
  ended: { artifact: 'evening', now: '2026-10-26T23:05:01+09:00' },
});

const params = new URLSearchParams(location.search);
const selectedId = scenarios[params.get('scenario')] ? params.get('scenario') : 'cards';
const select = document.getElementById('qa-scenario');
const note = document.getElementById('qa-scenario-note');
select.value = selectedId;
let selected = scenarios[selectedId];
let fixedNow = Date.parse(selected.now);
note.textContent = `synthetic QA · 固定時刻 ${selected.now} · ${selected.artifact} artifact`;
try {
  localStorage.removeItem(DESTINATION_STORAGE_KEY);
  localStorage.removeItem(DISPLAY_MODE_STORAGE_KEY);
} catch {}

const originalFetch = window.fetch.bind(window);
window.fetch = (input, options) => {
  const filename = new URL(input, location.href).pathname.split('/').pop();
  if (!Object.values(DESTINATION_PAYLOADS).some(path => path.endsWith(filename))) {
    return Promise.reject(new TypeError('QA loader requested an unexpected synthetic payload path'));
  }
  return originalFetch(`./artifacts/${selected.artifact}/${filename}`, options);
};

const runtime = createPreviewRuntime({ expectedProfile: PUBLIC_DATA_SCOPE, cacheMode: 'default',
  nowProvider: () => fixedNow, documentRef: document, windowRef: window });
select.addEventListener('change', () => {
  if (!scenarios[select.value]) return;
  const next = new URL(location.href);
  next.searchParams.set('scenario', select.value);
  location.assign(next.href);
});
window.syntheticQaRuntime = runtime;
'''


def prepare_harness(output: Path, anchor_date: date = DEFAULT_ANCHOR_DATE) -> dict[str, Any]:
    """Create two independently validated 17-file artifacts and a separate QA shell."""
    raw_output = output.expanduser().absolute()
    if raw_output.is_symlink() or raw_output.exists():
        raise QaHarnessError('output must be a new, non-symlink directory')
    if raw_output == ROOT or ROOT in raw_output.parents:
        raise QaHarnessError('QA output must be outside the repository')
    raw_output.parent.mkdir(parents=True, exist_ok=True)
    raw_output.mkdir()
    artifacts = raw_output / 'artifacts'
    artifacts.mkdir()
    try:
        with tempfile.TemporaryDirectory(prefix='synthetic-public-qa-', dir=SAFE_TEMP_ROOT) as temp_name:
            work = Path(temp_name)
            baseline_fixtures = work / 'baseline-fixtures'
            generate_fixture_directory(baseline_fixtures, anchor_date)
            baseline_site = work / 'baseline-site'
            _build_validated_artifact(baseline_fixtures, baseline_site)
            shutil.copytree(baseline_site, artifacts / 'baseline')

            evening_fixtures = work / 'evening-fixtures'
            _write_evening_fixtures(evening_fixtures)
            evening_site = work / 'evening-site'
            _build_validated_artifact(evening_fixtures, evening_site)
            shutil.copytree(evening_site, artifacts / 'evening')

        _write_harness_shell(raw_output)
        return {
            'output': raw_output,
            'artifacts': 2,
            'files_per_artifact': 17,
            'stations': len(STATION_IDS),
            'service_dates': [
                (anchor_date.fromordinal(anchor_date.toordinal() + offset)).isoformat()
                for offset in (-1, 0, 1)
            ],
        }
    except Exception:
        shutil.rmtree(raw_output, ignore_errors=True)
        raise


class NoDirectoryListingHandler(SimpleHTTPRequestHandler):
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map, '.mjs': 'text/javascript'}

    def list_directory(self, path):  # noqa: ARG002
        self.send_error(403, 'Directory listing disabled for local synthetic QA')
        return None


def _private_lan_ipv4(value: str) -> str:
    try:
        address = ipaddress.ip_address(value)
    except ValueError as error:
        raise QaHarnessError('--bind must be an explicit private LAN IPv4 address') from error
    lan_networks = (ipaddress.ip_network('10.0.0.0/8'), ipaddress.ip_network('172.16.0.0/12'),
                    ipaddress.ip_network('192.168.0.0/16'))
    if not isinstance(address, ipaddress.IPv4Address) or not any(address in network for network in lan_networks):
        raise QaHarnessError('--bind must be an explicit private LAN IPv4 address, not a wildcard or loopback')
    return str(address)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bind', help='explicit Mac private LAN IPv4 address; server never binds wildcard')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--prepare-only', action='store_true', help='build to --output without starting a server')
    parser.add_argument('--output', type=Path, help='new QA root; required with --prepare-only')
    args = parser.parse_args()
    try:
        if args.port < 1024 or args.port > 65535:
            raise QaHarnessError('--port must be between 1024 and 65535')
        if args.prepare_only:
            if args.output is None or args.bind is not None:
                raise QaHarnessError('--prepare-only requires --output and does not accept --bind')
            result = prepare_harness(args.output)
            print(f"Synthetic QA harness prepared: {result['output']}")
            print(f"Validated artifacts: {result['artifacts']} x {result['files_per_artifact']} files; "
                  f"stations: {result['stations']}; baseline dates: {', '.join(result['service_dates'])}")
            print('QA shell/scenario controls are outside both validated artifacts.')
            return 0

        if args.output is not None:
            raise QaHarnessError('--output is only valid with --prepare-only')
        if not args.bind:
            raise QaHarnessError('--bind is required; bind to the Mac private LAN IPv4 address')
        bind = _private_lan_ipv4(args.bind)
        with tempfile.TemporaryDirectory(prefix='dotchi-synthetic-qa-', dir=SAFE_TEMP_ROOT) as temp_name:
            qa_root = Path(temp_name) / 'site'
            result = prepare_harness(qa_root)
            handler = lambda *handler_args, **handler_kwargs: NoDirectoryListingHandler(  # noqa: E731
                *handler_args, directory=str(result['output']), **handler_kwargs)
            server = ThreadingHTTPServer((bind, args.port), handler)
            print(f"Mac:    http://{bind}:{args.port}/?scenario=cards")
            print(f"iPhone: http://{bind}:{args.port}/?scenario=cards")
            print('Synthetic-only local QA. Press Ctrl+C to stop the server and remove temporary files.')
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                print('\nStopping synthetic QA server.')
            finally:
                server.server_close()
        return 0
    except (QaHarnessError, SyntheticFixtureError, OSError, ValueError) as error:
        print(f'synthetic public QA failed: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
