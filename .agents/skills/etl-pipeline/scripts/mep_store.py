"""Local, append-only MEP evidence store. No network services or embeddings."""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3

SCHEMA = 'mep-evidence/1'


def canonical(value):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False,
                          separators=(',', ':'))
    except (TypeError, ValueError) as exc:
        raise ValueError('Evidence must contain finite JSON values') from exc


def digest(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode('utf-8')).hexdigest()


def document_info(path, metadata=None):
    path = Path(path).resolve(strict=True)
    metadata = dict(metadata or {})
    return {'path': str(path), 'filename': path.name, 'sha256': digest(path.read_bytes()),
            'document_id': metadata.get('document_id'), 'revision': metadata.get('revision'),
            'drawing_number': metadata.get('drawing_number'), 'discipline': metadata.get('discipline'),
            'media_type': path.suffix.lower().lstrip('.'), 'metadata': metadata}


def validate_package(package):
    canonical(package)
    if not isinstance(package, dict) or package.get('schema_version') != SCHEMA:
        raise ValueError('Expected mep-evidence/1 package')
    doc = package.get('document')
    if not isinstance(doc, dict):
        raise ValueError('Missing document object')
    for field in ('path', 'filename', 'sha256', 'media_type'):
        if not isinstance(doc.get(field), str) or not doc[field].strip():
            raise ValueError('Missing document.' + field)
    if not re.fullmatch(r'[a-f0-9]{64}', doc['sha256']):
        raise ValueError('Invalid source hash')
    if not re.fullmatch(r'[a-z0-9][a-z0-9.+-]*', doc['media_type']):
        raise ValueError('media_type must be a lowercase file format, e.g. pdf or xlsx')
    for field in ('document_id', 'revision', 'drawing_number', 'discipline'):
        if doc.get(field) is not None and (not isinstance(doc[field], str) or not doc[field].strip()):
            raise ValueError('Document ' + field + ' must be null or a nonempty string')
    if not isinstance(package.get('records'), list) or not isinstance(package.get('issues'), list):
        raise ValueError('Expected records and issues arrays')
    for i, record in enumerate(package['records']):
        if not isinstance(record, dict) or not isinstance(record.get('kind'), str) or not record['kind']:
            raise ValueError(f'Record {i}: missing kind')
        if not isinstance(record.get('raw_text'), str):
            raise ValueError(f'Record {i}: raw_text must be a string')
        source = record.get('source')
        if not isinstance(source, dict) or not isinstance(source.get('method'), str) or not source['method']:
            raise ValueError(f'Record {i}: missing source.method')
        page = source.get('pdf_page')
        if doc['media_type'] == 'pdf' and page is None:
            raise ValueError(f'Record {i}: PDF evidence needs a page')
        for field in ('pdf_page', 'row'):
            value = source.get(field)
            if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 1):
                raise ValueError(f'Record {i}: {field} must be a one-based integer')
        bbox = source.get('bbox')
        if bbox is not None:
            if (not isinstance(bbox, list) or len(bbox) != 4 or
                    any(isinstance(v, bool) or not isinstance(v, (int, float)) or
                        not math.isfinite(v) for v in bbox) or bbox[2] < bbox[0] or bbox[3] < bbox[1]):
                raise ValueError(f'Record {i}: invalid bbox')
        if not isinstance(record.get('data'), dict) or not isinstance(record.get('review'), dict):
            raise ValueError(f'Record {i}: data and review must be objects')
        if record['review'].get('status') not in ('unreviewed', 'needs_review'):
            raise ValueError('Extraction cannot assert engineering approval')
        if not isinstance(record['review'].get('issues'), list):
            raise ValueError(f'Record {i}: review.issues must be an array')
    return package


SQL = '''
CREATE TABLE IF NOT EXISTS versions (
 id TEXT PRIMARY KEY, logical_key TEXT NOT NULL, document_id TEXT, revision TEXT,
 source_path TEXT NOT NULL, filename TEXT NOT NULL, sha256 TEXT NOT NULL,
 archive_path TEXT NOT NULL, metadata_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS records (
 id TEXT PRIMARY KEY, version_id TEXT NOT NULL REFERENCES versions(id),
 kind TEXT NOT NULL, raw_text TEXT NOT NULL, payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
 id TEXT PRIMARY KEY, version_id TEXT NOT NULL REFERENCES versions(id),
 package_hash TEXT NOT NULL, issues_json TEXT NOT NULL, document_json TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS run_records (
 run_id TEXT NOT NULL REFERENCES runs(id), record_id TEXT NOT NULL REFERENCES records(id),
 PRIMARY KEY(run_id, record_id)
);
CREATE TABLE IF NOT EXISTS reviews (
 id INTEGER PRIMARY KEY AUTOINCREMENT, record_id TEXT NOT NULL REFERENCES records(id),
 reviewer TEXT NOT NULL, decision TEXT NOT NULL CHECK(decision IN ('approved','rejected','needs_review')),
 reason TEXT NOT NULL, field TEXT, value_json TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS activations (
 id INTEGER PRIMARY KEY AUTOINCREMENT, logical_key TEXT NOT NULL,
 version_id TEXT NOT NULL REFERENCES versions(id), reviewer TEXT NOT NULL,
 reason TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS evidence_fts USING fts5(record_id UNINDEXED, text);
CREATE INDEX IF NOT EXISTS versions_logical ON versions(logical_key);
CREATE INDEX IF NOT EXISTS records_version ON records(version_id);
'''


class Store:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute('PRAGMA foreign_keys=ON')
        existing = {row[0] for row in self.conn.execute("select name from sqlite_master where type='table'")}
        version = self.conn.execute('PRAGMA user_version').fetchone()[0]
        if version not in (0, 2) or (existing and 'versions' not in existing):
            self.conn.close()
            raise ValueError('Not a supported MEP evidence database; refusing migration')
        self.conn.executescript(SQL)
        for table in ('versions', 'records', 'runs', 'run_records', 'reviews', 'activations'):
            for operation in ('UPDATE', 'DELETE'):
                self.conn.execute(f'''CREATE TRIGGER IF NOT EXISTS immutable_{table}_{operation}
                    BEFORE {operation} ON {table} BEGIN
                    SELECT RAISE(ABORT, 'Immutable evidence and event history'); END''')
            # REPLACE otherwise bypasses ordinary UPDATE/DELETE guards in SQLite.
            key_check = ('run_id=NEW.run_id AND record_id=NEW.record_id' if table == 'run_records'
                         else 'id=NEW.id')
            self.conn.execute(f'''CREATE TRIGGER IF NOT EXISTS immutable_{table}_INSERT
                BEFORE INSERT ON {table} WHEN EXISTS(SELECT 1 FROM {table} WHERE {key_check})
                BEGIN SELECT RAISE(ABORT, 'Immutable keys cannot be replaced'); END''')
        self.conn.execute('PRAGMA user_version=2')
        self.conn.commit()

    def close(self):
        self.conn.close()

    @staticmethod
    def now():
        return datetime.now(timezone.utc).isoformat()

    def _archive(self, data, expected_hash):
        path = self.path.parent / (self.path.stem + '.evidence') / expected_hash[:2] / expected_hash
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open('xb') as stream:
                stream.write(data)
        except FileExistsError:
            if digest(path.read_bytes()) != expected_hash:
                raise ValueError('Existing evidence archive failed hash verification')
        return path

    def ingest(self, package):
        validate_package(package)
        doc = package['document']
        source_path = Path(doc['path']).resolve(strict=True)
        if source_path.name != doc['filename']:
            raise ValueError('Document filename does not match source path')
        if source_path.suffix.lower().lstrip('.') != doc['media_type']:
            raise ValueError('media_type does not match the actual source filename')
        source_bytes = source_path.read_bytes()
        if digest(source_bytes) != doc['sha256']:
            raise ValueError('Source hash changed since extraction')
        if source_bytes.lstrip().startswith(b'%PDF-') and doc['media_type'] != 'pdf':
            raise ValueError('Actual PDF bytes require pdf media_type and page validation')
        if doc['media_type'] == 'pdf':
            import io
            from pypdf import PdfReader
            page_count = len(PdfReader(io.BytesIO(source_bytes)).pages)
            if any(r['source']['pdf_page'] > page_count for r in package['records']):
                raise ValueError('PDF page reference exceeds actual source page count')
        logical_key = doc.get('document_id') or str(source_path).casefold()
        version_id = digest(canonical([logical_key, doc.get('revision'), doc['sha256']]))
        run_id = digest(canonical([version_id, package]))
        archive = self._archive(source_bytes, doc['sha256'])
        issues = []
        record_ids = []
        inserted = 0
        activated = False
        with self.conn:
            previous = self.conn.execute('select id,revision,sha256 from versions where logical_key=?',
                                         (logical_key,)).fetchall()
            if any(r['revision'] == doc.get('revision') and r['sha256'] != doc['sha256'] for r in previous):
                issues.append('REVISION_HASH_CONFLICT')
            if doc.get('document_id') is None:
                issues.append('DOCUMENT_ID_NOT_SUPPLIED_PATH_IDENTITY_ONLY')
            if doc.get('revision') is None:
                issues.append('REVISION_NOT_SUPPLIED')
            if not self.conn.execute('select 1 from versions where id=?', (version_id,)).fetchone():
                self.conn.execute('insert into versions values(?,?,?,?,?,?,?,?,?,?)',
                              (version_id, logical_key, doc.get('document_id'), doc.get('revision'),
                               str(source_path), doc['filename'], doc['sha256'], str(archive),
                               canonical(doc), self.now()))
            if not self.conn.execute('select 1 from runs where id=?', (run_id,)).fetchone():
                self.conn.execute('insert into runs values(?,?,?,?,?,?)',
                              (run_id, version_id, digest(canonical(package)),
                               canonical({'extraction_issues': package['issues'], 'ingestion_issues': issues}),
                               canonical(doc), self.now()))
            for record in package['records']:
                payload = canonical(record)
                record_id = digest(canonical([version_id, record]))
                changed = not self.conn.execute('select 1 from records where id=?', (record_id,)).fetchone()
                if changed:
                    self.conn.execute('insert into records values(?,?,?,?,?)',
                                      (record_id, version_id, record['kind'], record['raw_text'], payload))
                    inserted += 1
                    self.conn.execute('insert into evidence_fts(record_id,text) values(?,?)',
                                      (record_id, record['raw_text'] + '\n' + canonical(record['data'])))
                if not self.conn.execute('select 1 from run_records where run_id=? and record_id=?',
                                         (run_id, record_id)).fetchone():
                    self.conn.execute('insert into run_records values(?,?)', (run_id, record_id))
                record_ids.append(record_id)
            if not previous:
                self.conn.execute('insert into activations(logical_key,version_id,reviewer,reason,created_at) values(?,?,?,?,?)',
                                  (logical_key, version_id, 'system', 'First observed version; NOT engineering approval', self.now()))
                activated = True
        return {'version_id': version_id, 'run_id': run_id, 'record_ids': record_ids,
                'new_records': inserted, 'archive_path': str(archive), 'activated': activated, 'issues': issues}

    def activate(self, version_id, reviewer, reason):
        if not isinstance(reviewer, str) or not reviewer.strip() or not isinstance(reason, str) or not reason.strip():
            raise ValueError('Activation needs reviewer and reason')
        row = self.conn.execute('select logical_key from versions where id=?', (version_id,)).fetchone()
        if row is None:
            raise ValueError('Unknown version')
        with self.conn:
            cursor = self.conn.execute('insert into activations(logical_key,version_id,reviewer,reason,created_at) values(?,?,?,?,?)',
                                       (row['logical_key'], version_id, reviewer, reason, self.now()))
        return {'activation_id': cursor.lastrowid, 'version_id': version_id}

    def review(self, record_id, reviewer, decision, reason, field=None, value=None):
        if not isinstance(reviewer, str) or not reviewer.strip() or not isinstance(reason, str) or not reason.strip():
            raise ValueError('Review needs reviewer and reason')
        if decision not in ('approved', 'rejected', 'needs_review'):
            raise ValueError('Unknown review decision')
        if not self.conn.execute('select 1 from records where id=?', (record_id,)).fetchone():
            raise ValueError('Unknown evidence record')
        if field is not None and (not isinstance(field, str) or not field.strip()):
            raise ValueError('Correction field must be nonempty')
        if field is None and value is not None:
            raise ValueError('Correction value needs a field')
        with self.conn:
            cur = self.conn.execute('insert into reviews(record_id,reviewer,decision,reason,field,value_json,created_at) values(?,?,?,?,?,?,?)',
                                    (record_id, reviewer, decision, reason, field,
                                     canonical(value) if field is not None else None, self.now()))
        return {'review_id': cur.lastrowid, 'record_id': record_id, 'decision': decision}

    def inspect(self, record_id):
        row = self.conn.execute('select r.payload_json,v.* from records r join versions v on r.version_id=v.id where r.id=?',
                                (record_id,)).fetchone()
        if row is None:
            raise ValueError('Unknown evidence record')
        reviews = []
        for review in self.conn.execute('select * from reviews where record_id=? order by id', (record_id,)):
            data = dict(review)
            data['value'] = json.loads(data.pop('value_json')) if data['value_json'] is not None else None
            reviews.append(data)
        archive = Path(row['archive_path'])
        verified = archive.is_file() and digest(archive.read_bytes()) == row['sha256']
        runs = []
        for run in self.conn.execute('select u.* from runs u join run_records rr on rr.run_id=u.id where rr.record_id=? order by u.created_at,u.id', (record_id,)):
            data = dict(run)
            data['document'] = json.loads(data.pop('document_json'))
            runs.append(data)
        return {'record_id': record_id, 'record': json.loads(row['payload_json']),
                'document': json.loads(row['metadata_json']), 'version_id': row['id'],
                'archive_path': str(archive), 'evidence_verified': verified, 'reviews': reviews, 'runs': runs}

    def search(self, query, active_only=False, limit=50):
        if not isinstance(query, str) or len(query) > 1000:
            raise ValueError('Query must be a string of at most 1000 characters')
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ValueError('Limit must be 1 to 1000')
        if not query.strip():
            return {'results': [], 'active_only': active_only}
        literal = '"' + query.replace('"', '""') + '"'
        sql = '''select r.id as record_id,r.version_id,r.payload_json,v.metadata_json
                 from evidence_fts f join records r on r.id=f.record_id
                 join versions v on v.id=r.version_id where evidence_fts match ?'''
        if active_only:
            sql += ''' and v.id=(select a.version_id from activations a
                       where a.logical_key=v.logical_key order by a.id desc limit 1)'''
        sql += ' order by r.id limit ?'
        result = []
        for row in self.conn.execute(sql, (literal, limit)):
            result.append({'record_id': row['record_id'], 'version_id': row['version_id'],
                           'record': json.loads(row['payload_json']), 'document': json.loads(row['metadata_json'])})
        return {'results': result, 'active_only': active_only}


def _number(value):
    if value is None or value == '':
        return None
    if isinstance(value, bool):
        return None
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return (int(n) if n.is_integer() else n) if math.isfinite(n) else None


def tabular_package(path, mapping, metadata=None):
    path = Path(path).resolve(strict=True)
    initial_hash = digest(path.read_bytes())
    columns = mapping.get('columns', {})
    if not isinstance(columns, dict) or 'tag' not in columns:
        raise ValueError('Explicit columns mapping including tag is required')
    header_row = mapping.get('header_row', 1)
    if isinstance(header_row, bool) or not isinstance(header_row, int) or header_row < 1:
        raise ValueError('header_row must be a one-based integer')
    if path.suffix.lower() == '.xlsx':
        from openpyxl import load_workbook
        wb = load_workbook(path, read_only=True, data_only=False, keep_links=False)
        try:
            sheet = mapping.get('sheet')
            if sheet not in wb.sheetnames:
                raise ValueError('An explicit existing sheet is required')
            rows = list(wb[sheet].iter_rows(values_only=True))
        finally:
            wb.close()
    elif path.suffix.lower() == '.csv':
        sheet = 'CSV'
        with path.open(encoding='utf-8-sig', newline='') as stream:
            rows = list(csv.reader(stream))
    else:
        raise ValueError('Only .xlsx and UTF-8 .csv are supported; convert legacy XLS separately')
    if len(rows) < header_row:
        raise ValueError('Header row not present')
    headers = [str(v).strip() if v is not None else '' for v in rows[header_row - 1]]
    nonempty = [h for h in headers if h]
    if len(set(nonempty)) != len(nonempty):
        raise ValueError('Duplicate headers make mapping ambiguous')
    needed = list(columns.values())
    for p in mapping.get('parameters', []):
        needed += [p.get('value_column')]
        if p.get('unit_column'):
            needed.append(p['unit_column'])
    if any(h not in nonempty for h in needed):
        raise ValueError('Mapped column missing from header')
    records = []
    for row_number, cells in enumerate(rows[header_row:], header_row + 1):
        if all(v is None or v == '' for v in cells):
            continue
        raw = {h: cells[i] if i < len(cells) else None for i, h in enumerate(headers) if h}
        # Keep dates and other Excel native values textual, with raw formulas preserved.
        raw = {k: v if isinstance(v, (str, int, float, bool, type(None))) else str(v) for k, v in raw.items()}
        data = {key: raw.get(header) for key, header in columns.items()}
        issues = []
        if isinstance(data.get('quantity'), str) and data['quantity'].startswith('='):
            issues.append('FORMULA_NOT_EVALUATED')
        quantity = _number(data.get('quantity'))
        if data.get('quantity') not in (None, '') and quantity is None:
            issues.append('QUANTITY_NOT_VERIFIED_NUMERIC')
        data['quantity'] = quantity
        for key in ('discipline', 'role', 'scope'):
            if key in mapping and mapping[key] is not None:
                if data.get(key) not in (None, '', mapping[key]):
                    issues.append('MAPPED_VALUE_CONSTANT_CONFLICT:' + key)
                data[key] = mapping[key]
        data['parameters'] = []
        for parameter in mapping.get('parameters', []):
            value = raw.get(parameter['value_column'])
            if isinstance(value, str) and value.startswith('='):
                issues.append('FORMULA_NOT_EVALUATED')
                value = None
            if parameter.get('value_type', 'number') == 'number':
                numeric = _number(value)
                if value not in (None, '') and numeric is None:
                    issues.append('PARAMETER_NOT_VERIFIED_NUMERIC:' + parameter['name'])
                value = numeric
            elif parameter.get('value_type') != 'text':
                raise ValueError('Parameter value_type must be number or text')
            data['parameters'].append({'name': parameter['name'], 'value': value,
                                       'unit': raw.get(parameter.get('unit_column')) if parameter.get('unit_column') else parameter.get('fixed_unit'),
                                       'scope': mapping.get('scope')})
        source = {'sheet': sheet, 'row': row_number, 'method': 'openpyxl/csv-explicit-mapping-v1',
                  'columns': dict(columns), 'parameter_columns': json.loads(canonical(mapping.get('parameters', []))),
                  'pdf_page': None, 'drawing_number': data.get('drawing_number')}
        records.append({'kind': 'equipment', 'raw_text': canonical(raw), 'source': source,
                        'data': data, 'review': {'status': 'unreviewed', 'issues': sorted(set(issues))}})
    document = document_info(path, metadata)
    if document['sha256'] != initial_hash:
        raise ValueError('Source changed during tabular extraction; discard and retry')
    return validate_package({'schema_version': SCHEMA, 'document': document,
                             'records': records, 'issues': []})


def write_json(value, path=None):
    text = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)
    if path:
        with Path(path).open('x', encoding='utf-8') as stream:
            stream.write(text + '\n')
    else:
        print(text)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    ingest = sub.add_parser('ingest', help='Validate, archive and append an evidence package')
    ingest.add_argument('--db', required=True)
    ingest.add_argument('--package', required=True)
    table = sub.add_parser('tabular', help='Extract XLSX/CSV using an explicit header mapping')
    table.add_argument('--input', required=True)
    table.add_argument('--mapping', required=True)
    table.add_argument('--metadata')
    table.add_argument('--output')
    search = sub.add_parser('search', help='Literal FTS5 phrase search, no embeddings')
    search.add_argument('--db', required=True)
    search.add_argument('--query', required=True)
    search.add_argument('--active-only', action='store_true')
    search.add_argument('--limit', type=int, default=50)
    activate = sub.add_parser('activate', help='Explicitly select a revision after review')
    for key in ('db', 'version', 'reviewer', 'reason'):
        activate.add_argument('--' + key, required=True)
    args = parser.parse_args(argv)
    if args.command == 'tabular':
        metadata = json.loads(Path(args.metadata).read_text(encoding='utf-8')) if args.metadata else None
        result = tabular_package(args.input, json.loads(Path(args.mapping).read_text(encoding='utf-8')), metadata)
        write_json(result, args.output)
        return
    store = Store(args.db)
    try:
        if args.command == 'ingest':
            result = store.ingest(json.loads(Path(args.package).read_text(encoding='utf-8')))
        elif args.command == 'activate':
            result = store.activate(args.version, args.reviewer, args.reason)
        else:
            result = store.search(args.query, args.active_only, args.limit)
        write_json(result)
    finally:
        store.close()


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, sqlite3.Error) as error:
        raise SystemExit(str(error))
