import copy
import csv
import hashlib
import json
import os
from contextlib import redirect_stdout
import io
import stat
import struct
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path
from unittest.mock import patch

from scripts import odpt_gtfs_loader as loader
from scripts import odpt_source_inventory as inventory


def fixture():
    return {
        'agency': [{'agency_id': 'a', 'agency_name': 'Synthetic', 'agency_url': 'https://example.invalid', 'agency_timezone': 'Asia/Tokyo'}],
        'feed_info': [{'feed_publisher_name': 'Fixture', 'feed_publisher_url': 'https://example.invalid', 'feed_lang': 'ja'}],
        'routes': [{'route_id': 'r', 'route_type': '1', 'route_short_name': 'R'}],
        'stops': [{'stop_id': 's', 'stop_name': 'Station', 'zone_id': 'z'}],
        'trips': [{'trip_id': 't', 'route_id': 'r', 'service_id': 'c'}],
        'stop_times': [{'trip_id': 't', 'stop_id': 's', 'stop_sequence': '10', 'arrival_time': '24:10:00', 'departure_time': ''},
                       {'trip_id': 't', 'stop_id': 's', 'stop_sequence': '2', 'arrival_time': '00:10:00', 'departure_time': ''}],
        'calendar': [{'service_id': 'c', **{day: '1' for day in 'monday tuesday wednesday thursday friday saturday sunday'.split()}, 'start_date': '20260101', 'end_date': '20261231'}],
        'calendar_dates': [{'service_id': 'c', 'date': '20260103', 'exception_type': '2'}],
        'fare_attributes': [{'fare_id': 'f', 'price': '100', 'currency_type': 'JPY', 'payment_method': '0', 'transfers': ''}],
        'fare_rules': [{'fare_id': 'f', 'route_id': 'r', 'origin_id': 'z'}],
        'translations': [{'table_name': 'stops', 'field_name': 'stop_name', 'language': 'en', 'translation': 'Station, "A"\nNorth', 'field_value': 'Station'}],
    }


def archive(tables=None, *, bom=False, reverse=False, newline='\n', compression=zipfile.ZIP_DEFLATED, replacements=None, extras=()):
    tables = fixture() if tables is None else tables
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', compression=compression) as z:
        for name in sorted(tables, reverse=reverse):
            rows = tables[name]
            header = list(rows[0]) if rows else loader.SCHEMAS[name][0].split()
            if reverse: header.reverse(); rows = list(reversed(rows))
            text = io.StringIO(newline=''); writer = csv.DictWriter(text, header, lineterminator=newline)
            writer.writeheader(); writer.writerows(rows)
            raw = text.getvalue().encode('utf-8-sig' if bom else 'utf-8')
            z.writestr(name + '.txt', (replacements or {}).get(name, raw))
        for info, raw in extras: z.writestr(info, raw)
    return stream.getvalue()


class GTFSLoaderTests(unittest.TestCase):
    def error(self, code, raw):
        with self.assertRaises(loader.GTFSError) as caught: loader.parse_gtfs(raw)
        self.assertEqual(caught.exception.code, code)

    def test_eleven_tables_normalization_and_cell_states(self):
        r = loader.parse_gtfs(archive()); self.assertEqual(len(r['tables']), 11)
        self.assertEqual(r['coverage'], 'complete')
        rows = r['tables']['stop_times']['rows']
        self.assertEqual([row['values']['stop_sequence'] for row in rows], [2, 10])
        self.assertEqual([row['values']['arrival_time'] for row in rows], [600, 87000])
        self.assertEqual(loader.cell_state('stop_times', rows[0], 'departure_time'), 'empty')
        self.assertEqual(loader.cell_state('stop_times', rows[0], 'stop_headsign'), 'missing-column')
        fare = r['tables']['fare_attributes']['rows'][0]
        self.assertEqual(loader.cell_state('fare_attributes', fare, 'transfers'), 'null-equivalent')
        self.assertEqual(r['tables']['calendar_dates']['rows'][0]['values']['date'], '2026-01-03')

    def test_representation_invariance(self):
        base = loader.parse_gtfs(archive())
        for options in ({'bom': True}, {'newline': '\r\n'}, {'newline': '\r'}, {'reverse': True}, {'compression': zipfile.ZIP_STORED}):
            with self.subTest(options=options): self.assertEqual(base['tables'], loader.parse_gtfs(archive(**options))['tables'])

    def test_optional_calendar_agency_and_fields(self):
        t = fixture(); del t['calendar']; t['calendar_dates'][0]['exception_type'] = '1'
        del t['agency'][0]['agency_id']; del t['feed_info']; del t['translations']
        r = loader.parse_gtfs(archive(t)); self.assertIn('implicit_agency_key', r['errorCodes'])

    def test_unknowns_retained_and_no_literal_null_conversion(self):
        t = fixture(); t['stops'][0]['new_column'] = 'null'
        r = loader.parse_gtfs(archive(t, extras=[('future.txt', b'opaque\ncontent\n')]))
        self.assertEqual(r['coverage'], 'partial'); self.assertEqual(r['unsupportedTables']['future.txt'], b'opaque\ncontent\n')
        self.assertEqual(r['tables']['stops']['rows'][0]['cells']['new_column'], 'null')

    def test_ambiguous_fare_rule_retained(self):
        t = fixture(); t['fare_rules'] *= 2
        r = loader.parse_gtfs(archive(t)); self.assertEqual(r['tables']['fare_rules']['recordCount'], 2)
        self.assertEqual(r['coverage'], 'partial')

    def test_csv_failures(self):
        for raw, code in [(b'', 'csv_header_missing'), (b'route_id,route_id\nr,r\n','csv_header_duplicate'),
            (b'route_id,route_type\nr,1,extra\n','csv_column_count_invalid'),
            (b'route_id,route_type\nr\n','csv_column_count_invalid'),
            (b'route_id,route_type\n"r,1\n','csv_quote_invalid'),
            (b'route_id,route_type\nr"x,1\n','csv_quote_invalid'),
            (b'route_id,route_type\n"r"x,1\n','csv_quote_invalid'),
            (b'route_id,route_type\n\xff,1\n','csv_utf8_invalid'),
            (b'route_id\nr\n','csv_required_column_missing'),
            (b'route_id,route_type\n,1\n','gtfs_required_value_empty')]:
            with self.subTest(code=code): self.error(code, archive(replacements={'routes': raw}))

    def test_invalid_types_dates_times_and_duplicate_keys(self):
        for table, field, value, code in [('calendar_dates','date','20260230','gtfs_date_invalid'),
            ('stop_times','arrival_time','24:60:00','gtfs_time_invalid'),
            ('stop_times','arrival_time','12:00','gtfs_time_invalid'),
            ('stop_times','stop_sequence','-1','gtfs_integer_invalid'),
            ('stops','stop_lat','nan','gtfs_number_invalid')]:
            t = fixture(); t[table][0][field] = value
            with self.subTest(field=field): self.error(code, archive(t))
        t = fixture(); t['trips'] *= 2; self.error('gtfs_key_duplicate', archive(t))
        t = fixture(); t['stop_times'][0]['stop_sequence'] = '02'; self.error('gtfs_key_duplicate', archive(t))

    def test_unknown_enum_is_partial(self):
        t = fixture(); t['trips'][0]['direction_id'] = '9'
        self.assertIn('enum_unsupported', loader.parse_gtfs(archive(t))['errorCodes'])

    def test_references(self):
        for table, field in [('trips','route_id'), ('trips','service_id'), ('stop_times','trip_id'),
                             ('stop_times','stop_id'), ('stops','parent_station'), ('routes','agency_id'),
                             ('fare_rules','fare_id'), ('fare_rules','route_id'), ('fare_rules','origin_id')]:
            t = fixture(); t[table][0][field] = 'missing'
            with self.subTest(table=table,field=field): self.error('gtfs_reference_unresolved', archive(t))
        t = fixture(); t['translations'][0]['field_value'] = 'missing'; self.error('gtfs_reference_unresolved',archive(t))
        t = fixture(); t['translations'][0].update(field_value='', record_id='s')
        self.assertEqual(loader.parse_gtfs(archive(t))['coverage'], 'complete')
        t['translations'][0].update(record_id='t', table_name='stop_times', field_name='stop_headsign', record_sub_id='2')
        for r in t['stop_times']: r['stop_headsign']='H'
        self.assertEqual(loader.parse_gtfs(archive(t))['coverage'], 'complete')

    def test_zip_safety(self):
        self.error('gtfs_zip_invalid', b'broken')
        for name in ('../evil.txt', '/evil.txt', 'nested/file.txt', 'directory/'):
            with self.subTest(name=name): self.error('zip_entry_path_unsafe', archive(extras=[(name,b'x')]))
        link=zipfile.ZipInfo('link.txt'); link.create_system=3; link.external_attr=(stat.S_IFLNK|0o777)<<16
        self.error('zip_entry_type_unsafe',archive(extras=[(link,b'target')]))
        with warnings.catch_warnings():
            warnings.simplefilter('ignore'); raw=archive(extras=[('routes.txt',b'x')])
        self.error('zip_duplicate_entry',raw)
        self.error('zip_compression_ratio_exceeded',archive(extras=[('bomb.txt', b'0' * 2_000_000)]))
        self.error('zip_entry_count_limit_exceeded',archive(extras=[(f'entry{i}.txt',b'x') for i in range(129)]))
        damaged=bytearray(archive(compression=zipfile.ZIP_STORED))
        with zipfile.ZipFile(io.BytesIO(damaged)) as z: info=z.getinfo('routes.txt')
        n,e=struct.unpack_from('<HH',damaged,info.header_offset+26); damaged[info.header_offset+30+n+e]^=1
        self.error('gtfs_zip_invalid',bytes(damaged))
        encrypted=bytearray(archive()); offset=encrypted.find(b'PK\x01\x02'); flags=struct.unpack_from('<H',encrypted,offset+8)[0]
        struct.pack_into('<H',encrypted,offset+8,flags|1); self.error('zip_entry_type_unsafe',bytes(encrypted))
        with patch.object(inventory,'MAX_ZIP_MEMBER_BYTES',1): self.error('zip_member_size_limit_exceeded',archive())
        with patch.object(inventory,'MAX_ZIP_TOTAL_BYTES',1): self.error('zip_total_size_limit_exceeded',archive())

    def test_source_identity_paths_changes_and_unchanged_bytes(self):
        with tempfile.TemporaryDirectory(dir='/private/tmp') as d:
            path=Path(d)/'feed.zip'; raw=archive(); path.write_bytes(raw)
            metadata={'status':'parsed','gtfs':{'feedVersion':'fixture','validFrom':'2026-01-01','validThrough':'2026-12-31'},'odpt':None}
            record=inventory._record('metro.gtfs','raw/TokyoMetro-Train-GTFS.zip',raw,metadata,'2026-11-04T00:00:00Z')
            self.assertEqual(loader.load_gtfs(path,record)['input']['sourceIdentity'],'verified')
            for field,value in [('sha256','0'*64),('sizeBytes',1)]:
                bad=copy.deepcopy(record); bad['artifact'][field]=value
                with self.assertRaises(loader.GTFSError) as c: loader.load_gtfs(path,bad)
                self.assertEqual(c.exception.code,'source_bytes_mismatch')
            link=Path(d)/'link.zip';link.symlink_to(path)
            for target in (link,Path('relative.zip'),Path(d)/'..'/'feed.zip',Path(d)/'missing.zip'):
                with self.assertRaises(loader.GTFSError): loader.load_gtfs(target)
            original=loader._read
            def changed(p):
                data, identity=original(p); return data, (*identity[:-1],identity[-1]+changed.calls)
            changed.calls=0
            def read(p):
                changed.calls+=1; return changed(p)
            with patch.object(loader,'_read',side_effect=read):
                with self.assertRaises(loader.GTFSError) as c: loader.load_gtfs(path)
                self.assertEqual(c.exception.code,'source_changed_during_validation')
            original_fstat = os.fstat
            def mutate(fd):
                path.write_bytes(raw + b'changed')
                return original_fstat(fd)
            with patch.object(os, 'fstat', side_effect=mutate):
                with self.assertRaises(loader.GTFSError) as c: loader.load_gtfs(path)
                self.assertEqual(c.exception.code, 'source_changed_while_reading')
            path.write_bytes(raw)
            record_path = Path(d) / 'source.json'; record_path.write_text(json.dumps(record))
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(loader.main(['--zip', str(path), '--source-record', str(record_path)]), 0)
            self.assertIn('source_identity=verified', out.getvalue())
            self.assertNotIn('Station,', out.getvalue())
            self.assertEqual(path.read_bytes(),raw)


if __name__ == '__main__': unittest.main()
