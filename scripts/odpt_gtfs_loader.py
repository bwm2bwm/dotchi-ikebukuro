#!/usr/bin/env python3
"""Offline GTFS input foundation. No comparison, extraction or persistence."""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import zipfile
import zlib
from collections import Counter
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

if __package__:
    from .odpt_source_inventory import InventoryError, validate_gtfs_archive, MAX_SOURCE_BYTES
    from .odpt_source_contract import ContractError, loads_record, validate_source_record
    from .odpt_train_semantic_diff import PROFILE, SemanticDiffError, _root, _read_bytes
else:
    from odpt_source_inventory import InventoryError, validate_gtfs_archive, MAX_SOURCE_BYTES
    from odpt_source_contract import ContractError, loads_record, validate_source_record
    from odpt_train_semantic_diff import PROFILE, SemanticDiffError, _root, _read_bytes

# (required columns/cells, supported optional columns, identity columns).
SCHEMAS = {
 'agency': ('agency_name agency_url agency_timezone', 'agency_id agency_lang agency_phone agency_fare_url agency_email', 'agency_id'),
 'feed_info': ('feed_publisher_name feed_publisher_url feed_lang', 'default_lang feed_start_date feed_end_date feed_version feed_contact_email feed_contact_url', ''),
 'routes': ('route_id route_type', 'agency_id route_short_name route_long_name route_desc route_url route_color route_text_color route_sort_order continuous_pickup continuous_drop_off network_id', 'route_id'),
 'stops': ('stop_id', 'stop_code stop_name tts_stop_name stop_desc stop_lat stop_lon zone_id stop_url location_type parent_station stop_timezone wheelchair_boarding level_id platform_code', 'stop_id'),
 'trips': ('route_id service_id trip_id', 'trip_headsign trip_short_name direction_id block_id shape_id wheelchair_accessible bikes_allowed', 'trip_id'),
 'stop_times': ('trip_id stop_sequence', 'arrival_time departure_time stop_id stop_headsign pickup_type drop_off_type continuous_pickup continuous_drop_off shape_dist_traveled timepoint location_group_id location_id start_pickup_drop_off_window end_pickup_drop_off_window pickup_booking_rule_id drop_off_booking_rule_id', 'trip_id stop_sequence'),
 'calendar': ('service_id monday tuesday wednesday thursday friday saturday sunday start_date end_date', '', 'service_id'),
 'calendar_dates': ('service_id date exception_type', '', 'service_id date'),
 'fare_attributes': ('fare_id price currency_type payment_method transfers', 'agency_id transfer_duration', 'fare_id'),
 'fare_rules': ('fare_id', 'route_id origin_id destination_id contains_id', 'fare_id route_id origin_id destination_id contains_id'),
 'translations': ('table_name field_name language translation', 'record_id record_sub_id field_value', 'table_name field_name language record_id record_sub_id field_value'),
}
DATES = {'start_date', 'end_date', 'date', 'feed_start_date', 'feed_end_date'}
TIMES = {'arrival_time', 'departure_time', 'start_pickup_drop_off_window', 'end_pickup_drop_off_window'}
INTS = {'stop_sequence', 'transfer_duration', 'route_sort_order'}
DECIMALS = {'stop_lat', 'stop_lon', 'price', 'shape_dist_traveled'}
ENUMS = {**{d: {0, 1} for d in 'monday tuesday wednesday thursday friday saturday sunday direction_id payment_method timepoint'.split()},
 'exception_type': {1, 2}, 'location_type': set(range(5)), 'wheelchair_boarding': {0, 1, 2},
 'wheelchair_accessible': {0, 1, 2}, 'bikes_allowed': {0, 1, 2}, 'transfers': {0, 1, 2},
 'pickup_type': {0, 1, 2, 3}, 'drop_off_type': {0, 1, 2, 3},
 'continuous_pickup': {0, 1, 2, 3}, 'continuous_drop_off': {0, 1, 2, 3}}
MAX_ROWS = 1_000_000  # additional implementation ceiling, never relaxed ZIP limits


class GTFSError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def fail(code):
    raise GTFSError(code)


def _quotes(text):
    """Reject bare quotes and text after a closing quote (csv.strict misses bare quotes)."""
    state = 'start'
    for ch in text:
        if ch == '\x00':
            fail('csv_nul_invalid')
        if state == 'quoted':
            if ch == '"': state = 'closed'
        elif state == 'closed':
            if ch == '"': state = 'quoted'
            elif ch == ',': state = 'start'
            elif ch in '\r\n': state = 'start'
            else: fail('csv_quote_invalid')
        elif ch == '"':
            if state != 'start': fail('csv_quote_invalid')
            state = 'quoted'
        elif ch == ',' or ch in '\r\n': state = 'start'
        else: state = 'plain'
    if state == 'quoted': fail('csv_quote_invalid')


def _number(value):
    if not re.fullmatch(r'[0-9]+', value, flags=re.ASCII): fail('gtfs_integer_invalid')
    # Bound conversion work, without narrowing a normal GTFS integer.
    if len(value) > 18: fail('gtfs_numeric_limit_exceeded')
    return int(value)


def _normalize(field, value, issues):
    if value == '': return None  # original empty string remains in cells
    if field in DATES:
        if not re.fullmatch(r'[0-9]{8}', value): fail('gtfs_date_invalid')
        try: return date(int(value[:4]), int(value[4:6]), int(value[6:])).isoformat()
        except ValueError: fail('gtfs_date_invalid')
    if field in TIMES:
        match = re.fullmatch(r'([0-9]{1,6}):([0-9]{2}):([0-9]{2})', value)
        if not match or int(match[2]) > 59 or int(match[3]) > 59: fail('gtfs_time_invalid')
        return int(match[1])*3600 + int(match[2])*60 + int(match[3])
    if field in INTS or field in ENUMS or field == 'route_type':
        number = _number(value)
        if field in ENUMS and number not in ENUMS[field]: issues.add('enum_unsupported')
        if field == 'route_type' and number not in {*range(8), 11, 12}: issues.add('route_type_extension')
        return number
    if field in DECIMALS:
        if not re.fullmatch(r'-?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)', value): fail('gtfs_number_invalid')
        try: number = Decimal(value)
        except InvalidOperation: fail('gtfs_number_invalid')
        if not number.is_finite(): fail('gtfs_number_invalid')
        if field == 'stop_lat' and not -90 <= number <= 90: fail('gtfs_coordinate_invalid')
        if field == 'stop_lon' and not -180 <= number <= 180: fail('gtfs_coordinate_invalid')
        if field in {'price', 'shape_dist_traveled'} and number < 0: fail('gtfs_number_invalid')
        return number
    return value


def cell_state(table, row, field):
    """Distinguish omitted column, empty cell, GTFS-defined null and literal text."""
    if field not in row['cells']: return 'missing-column'
    if row['cells'][field] != '': return 'value'
    if table == 'fare_attributes' and field == 'transfers': return 'null-equivalent'
    return 'empty'


def _key(name, row):
    # Presence bit preserves absent optional columns vs present empty cells.
    if name == 'stop_times': return (row['cells']['trip_id'], row['values']['stop_sequence'])
    return tuple((field in row['cells'], row['cells'].get(field, '')) for field in SCHEMAS[name][2].split())


def _table(name, raw, *, preserve_selector_duplicates=False):
    try: text = raw.decode('utf-8-sig')
    except UnicodeDecodeError: fail('csv_utf8_invalid')
    _quotes(text)
    issues = set()
    try:
        reader = csv.reader(io.StringIO(text, newline=''), strict=True)
        header = next(reader, None)
        if not header or any(not field for field in header): fail('csv_header_missing')
        if len(header) != len(set(header)): fail('csv_header_duplicate')
        required, optional, keys = (set(s.split()) for s in SCHEMAS[name])
        if not required <= set(header): fail('csv_required_column_missing')
        unknown = sorted(set(header) - required - optional)
        if unknown: issues.add('unknown_columns')
        rows = []
        seen = set()
        duplicate = 0
        for cells in reader:
            if len(cells) != len(header): fail('csv_column_count_invalid')
            values = dict(zip(header, cells))
            # transfers is required as a column, but blank has a defined GTFS meaning.
            if any(values[field] == '' for field in required - {'transfers'}): fail('gtfs_required_value_empty')
            row = {'cells': values, 'values': {field: _normalize(field, value, issues)
                   if field in required | optional else value for field, value in values.items()}}
            key = _key(name, row)
            if key in seen:
                duplicate += 1
                if name != 'fare_rules' and not (name == 'translations' and preserve_selector_duplicates): fail('gtfs_key_duplicate')
                issues.add('fare_rule_key_ambiguous' if name == 'fare_rules' else 'translation_key_ambiguous')
            seen.add(key)
            rows.append(row)
            if len(rows) > MAX_ROWS: fail('gtfs_row_limit_exceeded')
        if name == 'feed_info' and len(rows) != 1: fail('gtfs_feed_info_count_invalid')
        if name == 'agency':
            if len(rows) != 1 and any(not row['cells'].get('agency_id') for row in rows): fail('gtfs_agency_id_required')
            if any(not row['cells'].get('agency_id') for row in rows): issues.add('implicit_agency_key')
        rows.sort(key=lambda row: (_key(name, row), tuple(sorted(row['cells'].items()))))
        return {'headers': sorted(header), 'rows': rows, 'recordCount': len(rows),
                'keyFields': SCHEMAS[name][2].split(), 'duplicateKeyCount': duplicate,
                'keyUnique': duplicate == 0, 'unknownColumns': unknown, 'issues': sorted(issues)}
    except csv.Error: fail('csv_invalid')


def _references(tables, issues, members):
    def rows(table): return tables.get(table, {}).get('rows', [])
    indexes = {name: {r['cells'].get(fields[2].split()[0], '') for r in rows(name)}
               for name, fields in SCHEMAS.items() if fields[2]}
    services = indexes.get('calendar', set()) | indexes.get('calendar_dates', set())
    counts = Counter()
    def check(value, targets, optional=False):
        if value in (None, '') and optional:
            counts['optional-absent'] += 1
        elif value not in targets: fail('gtfs_reference_unresolved')
        else: counts['resolved'] += 1
    for r in rows('trips'):
        c = r['cells']; check(c['route_id'], indexes.get('routes', set())); check(c['service_id'], services)
        for field in ('shape_id', 'block_id'):
            if c.get(field): issues.add('trip_auxiliary_reference_not_evaluated')
    for r in rows('stop_times'):
        c = r['cells']; check(c['trip_id'], indexes.get('trips', set()))
        if c.get('stop_id'): check(c['stop_id'], indexes.get('stops', set()))
        elif c.get('location_id') or c.get('location_group_id'): issues.add('flex_reference_not_evaluated')
        else: fail('gtfs_stop_reference_missing')
    for r in rows('stops'):
        c = r['cells']; check(c.get('parent_station'), indexes.get('stops', set()), True)
        if c.get('parent_station') == c['stop_id']: fail('gtfs_parent_self_reference')
        if c.get('level_id'): issues.add('level_reference_not_evaluated')
    for r in rows('routes') + rows('fare_attributes'):
        c = r['cells']; agency = c.get('agency_id')
        if agency: check(agency, indexes.get('agency', set()))
        elif len(rows('agency')) == 1: counts['implicit-agency'] += 1
        else: fail('gtfs_agency_reference_required')
    zones = {r['cells']['zone_id'] for r in rows('stops') if r['cells'].get('zone_id')}
    for r in rows('fare_rules'):
        c = r['cells']; check(c['fare_id'], indexes.get('fare_attributes', set()))
        check(c.get('route_id'), indexes.get('routes', set()), True)
        for field in ('origin_id', 'destination_id', 'contains_id'): check(c.get(field), zones, True)
    # Translation references: selectors are exact text, never fuzzy labels.
    selectors = {}
    for r in rows('translations'):
        c = r['cells']; target, field = c['table_name'], c['field_name']
        if target not in tables:
            if target in SCHEMAS or target + '.txt' not in members:
                fail('gtfs_translation_target_missing')
            issues.add('translation_target_not_evaluated'); counts['not-evaluated'] += 1; continue
        if field not in tables[target]['headers']: fail('gtfs_translation_field_missing')
        record, sub, value = c.get('record_id', ''), c.get('record_sub_id', ''), c.get('field_value', '')
        if target == 'feed_info':
            if record or sub or value: fail('gtfs_translation_selector_invalid')
            counts['resolved'] += 1; continue
        if bool(record) == bool(value): fail('gtfs_translation_selector_invalid')
        if value:
            if sub: fail('gtfs_translation_selector_invalid')
            key = (target, field)
            if key not in selectors: selectors[key] = {row['cells'].get(field) for row in rows(target)}
            check(value, selectors[key])
        else:
            if target == 'stop_times':
                if not sub: fail('gtfs_translation_selector_invalid')
                key = (target, 'record')
                if key not in selectors: selectors[key] = {(row['cells']['trip_id'], row['values']['stop_sequence']) for row in rows(target)}
                check((record, _number(sub)), selectors[key])
            elif target in {'agency', 'stops', 'routes', 'trips'}:
                if sub: fail('gtfs_translation_selector_invalid')
                check(record, indexes[target])
            else: issues.add('translation_selector_not_evaluated'); counts['not-evaluated'] += 1
    return dict(sorted(counts.items()))


def parse_gtfs(raw, *, preserve_selector_duplicates=False):
    """Return normalized in-memory tables. Bytes API has no source identity claim."""
    if len(raw) > MAX_SOURCE_BYTES: fail('source_size_limit_exceeded')
    issues = set()
    tables = {}
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            infos = validate_gtfs_archive(archive)
            members = sorted(i.filename for i in infos)
            for member in members:
                name = member[:-4]
                if name not in SCHEMAS:
                    issues.add('unsupported_table'); continue
                tables[name] = _table(name, archive.read(member), preserve_selector_duplicates=preserve_selector_duplicates)
            if not {'agency', 'routes', 'trips', 'stop_times'} <= tables.keys(): fail('gtfs_required_table_missing')
            if not {'calendar', 'calendar_dates'} & tables.keys(): fail('gtfs_service_table_missing')
            if 'translations' in tables and 'feed_info' not in tables: fail('gtfs_feed_info_required')
            unsupported = {m: archive.read(m) for m in members if m[:-4] not in SCHEMAS}
    except InventoryError as exc: fail(exc.code)
    except (zipfile.BadZipFile, OSError, RuntimeError, EOFError, zlib.error, NotImplementedError): fail('gtfs_zip_invalid')
    for table in tables.values(): issues.update(table['issues'])
    for name in ('calendar', 'feed_info'):
        for row in tables.get(name, {}).get('rows', []):
            a, b = ('start_date', 'end_date') if name == 'calendar' else ('feed_start_date', 'feed_end_date')
            if row['values'].get(a) and row['values'].get(b) and row['values'][a] > row['values'][b]: fail('gtfs_date_range_invalid')
    refs = _references(tables, issues, members)
    return {'contract': 'odpt-gtfs-input', 'schemaVersion': 1, 'profile': dict(PROFILE),
            'input': {'sha256': hashlib.sha256(raw).hexdigest(), 'sizeBytes': len(raw), 'sourceIdentity': 'not-checked'},
            'members': members, 'tables': dict(sorted(tables.items())), 'unsupportedTables': unsupported,
            'referenceChecks': refs, 'coverage': 'partial' if issues else 'complete', 'errorCodes': sorted(issues)}


def _read(path):
    try:
        _root(path.parent)
        return _read_bytes(path)
    except SemanticDiffError as exc: fail(exc.code)


def load_gtfs(path: Path, source_record=None, *, preserve_selector_duplicates=False):
    """Read one explicit absolute ZIP path; optionally bind to a validated Source record."""
    if not isinstance(path, Path) or not path.is_absolute() or '..' in path.parts: fail('source_path_invalid')
    raw, identity = _read(path)
    if source_record is not None:
        try: validate_source_record(source_record)
        except ContractError: fail('source_record_invalid')
        if source_record['sourceId'] != 'metro.gtfs': fail('source_record_id_mismatch')
        artifact = source_record['artifact']
        if not artifact or (hashlib.sha256(raw).hexdigest(), len(raw)) != (artifact['sha256'], artifact['sizeBytes']): fail('source_bytes_mismatch')
    result = parse_gtfs(raw, preserve_selector_duplicates=preserve_selector_duplicates)
    again, after = _read(path)
    if identity != after or raw != again: fail('source_changed_during_validation')
    if source_record is not None: result['input']['sourceIdentity'] = 'verified'
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--zip', type=Path, required=True)
    parser.add_argument('--source-record', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        record_raw, identity = _read(args.source_record)
        try: record = loads_record(record_raw.decode('utf-8'))
        except (ContractError, UnicodeDecodeError): fail('source_record_invalid')
        result = load_gtfs(args.zip, record)
        after_raw, after = _read(args.source_record)
        if identity != after or record_raw != after_raw: fail('source_record_changed')
        print('source_identity=verified structure=validated coverage=' + result['coverage'])
        for name, table in result['tables'].items():
            print(f"table={name} records={table['recordCount']} key_unique={table['keyUnique']} unknown_columns={len(table['unknownColumns'])}")
        print('references=' + json.dumps(result['referenceChecks'], sort_keys=True))
        print('codes=' + (','.join(result['errorCodes']) or 'none'))
        return 0
    except GTFSError as exc:
        print('gtfs_validation=FAIL error=' + exc.code)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
