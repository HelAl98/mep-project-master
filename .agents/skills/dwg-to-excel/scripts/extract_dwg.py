"""Mapped DwgExporter XLSX evidence ingestion. Does not execute DWG converters."""
import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import shutil
import sys

from openpyxl import load_workbook

METHOD = 'mapped-dwgexporter-xlsx/1'
BLOCK_REASON = ('Direct DWG conversion is deferred: no inspected real exporter and real DWG/XLSX '
                'fixture have been functionally verified. File/hash inspection is not a functionality test.')


def _hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def probe_exporter(explicit_path=None):
    """Inspect presence and hash only; PATH discovery never executes the discovered file."""
    found = explicit_path if explicit_path is not None else shutil.which('DwgExporter.exe')
    path = Path(found).expanduser().resolve() if found else None
    result = {'status': 'unavailable', 'path': str(path) if path else None, 'sha256': None,
              'functionality_verified': False, 'direct_conversion': 'blocked', 'reason': BLOCK_REASON}
    if path and path.is_file():
        result.update(status='present_unverified', sha256=_hash(path), size_bytes=path.stat().st_size)
    return result


def verify_exporter(explicit_path, expected_sha256):
    """Verify an explicitly selected file's identity, without executing it or approving conversion."""
    if not isinstance(expected_sha256, str) or len(expected_sha256) != 64:
        raise ValueError('Expected SHA-256 must be supplied explicitly as 64 hex characters')
    result = probe_exporter(explicit_path)
    if result['status'] == 'unavailable':
        raise FileNotFoundError(explicit_path)
    if result['sha256'] != expected_sha256.lower():
        raise ValueError('Exporter SHA-256 mismatch')
    result['identity_verified'] = True
    result['status'] = 'identity_verified_only'
    return result


def _json_cell(value):
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    return str(value)


def ingest_export(path, mapping, metadata=None):
    """Read exact mapped Elements cells. No schema guessing or cross-row attribute association."""
    path = Path(path).expanduser().resolve(strict=True)
    if path.suffix.lower() != '.xlsx':
        raise ValueError('Supply the actual XLSX export; direct DWG parsing/conversion is blocked')
    if not isinstance(mapping, dict) or not mapping.get('sheet') or not isinstance(mapping.get('columns'), dict) or not mapping['columns']:
        raise ValueError('Explicit mapping requires sheet and nonempty columns')
    header_row = mapping.get('header_row', 1)
    if isinstance(header_row, bool) or not isinstance(header_row, int) or header_row < 1:
        raise ValueError('header_row must be a positive integer')
    metadata = copy.deepcopy(metadata or {})
    original = metadata.get('original_dwg')
    if original is not None:
        if not isinstance(original, dict) or not original.get('path') or not original.get('sha256'):
            raise ValueError('original_dwg requires path and explicitly supplied sha256')
        dwg = Path(original['path']).expanduser().resolve(strict=True)
        if dwg.suffix.lower() != '.dwg' or _hash(dwg) != original['sha256']:
            raise ValueError('Original DWG identity/hash mismatch')
        metadata['original_dwg'] = {**original, 'path': str(dwg), 'identity_verified': True,
                                    'relationship_verified': False}
    digest = _hash(path)
    document = {'path': str(path), 'filename': path.name, 'sha256': digest,
                'document_id': metadata.get('document_id'), 'revision': metadata.get('revision'),
                'discipline': mapping.get('discipline', metadata.get('discipline')),
                'drawing_number': metadata.get('drawing_number'), 'media_type': 'xlsx', 'metadata': metadata}
    package = {'schema_version': 'mep-evidence/1', 'document': document, 'records': [], 'issues': []}
    workbook = load_workbook(path, read_only=True, data_only=False, keep_links=False)
    try:
        if mapping['sheet'] not in workbook.sheetnames:
            raise ValueError(f'Mapped sheet absent: {mapping["sheet"]}')
        sheet = workbook[mapping['sheet']]
        rows = sheet.iter_rows(min_row=header_row)
        first = next(rows, ())
        headers = [_json_cell(c.value) for c in first]
        used = list(mapping['columns'].values())
        used += list(mapping.get('attribute_columns', {}).values())
        parameters = mapping.get('parameters', [])
        if not isinstance(parameters, list):
            raise ValueError('parameters mapping must be a list')
        for parameter in parameters:
            if not isinstance(parameter, dict) or not parameter.get('name') or not parameter.get('value_column'):
                raise ValueError('Each parameter mapping requires name and value_column')
            used.append(parameter['value_column'])
            if parameter.get('unit_column'):
                used.append(parameter['unit_column'])
        for column in used:
            if not isinstance(column, str) or headers.count(column) != 1:
                raise ValueError(f'Mapped column must exist exactly once: {column!r}')
        indexes = {column: headers.index(column) for column in used}
        if len([x for x in headers if x is not None]) != len(set(x for x in headers if x is not None)):
            raise ValueError('Duplicate XLSX headers are ambiguous')
        for row_number, cells in enumerate(rows, header_row + 1):
            values = [_json_cell(c.value) for c in cells]
            if not any(v is not None for v in values):
                continue
            issues = []
            raw = {str(h) if h is not None else f'__column_{i + 1}': v for i, (h, v) in enumerate(zip(headers, values))}
            def cell(column):
                idx = indexes[column]
                if idx >= len(cells):
                    return None
                if cells[idx].data_type == 'f':
                    issue = f'formula_not_evaluated:{column}'
                    if issue not in issues:
                        issues.append(issue)
                    return None
                return values[idx]
            def field(name):
                column = mapping['columns'].get(name)
                return cell(column) if column is not None else None
            attributes = field('attributes')
            if isinstance(attributes, str):
                try:
                    parsed = json.loads(attributes)
                    if not isinstance(parsed, dict):
                        raise ValueError('Attributes must be an object')
                    attributes = parsed
                except (ValueError, TypeError):
                    issues.append('attributes_not_json_object:raw_value_retained')
            if attributes is None:
                attributes = {}
            if mapping.get('attribute_columns'):
                if not isinstance(attributes, dict):
                    issues.append('attribute_columns_not_merged_with_invalid_attributes')
                else:
                    for name, column in mapping['attribute_columns'].items():
                        attributes[name] = cell(column)
            tag = field('tag')
            if tag is None and mapping.get('tag_from_attribute') and isinstance(attributes, dict):
                tag = attributes.get(mapping['tag_from_attribute'])
            coordinates = {}
            for axis in ('x', 'y', 'z'):
                value = field(axis)
                if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)):
                    issues.append(f'invalid_coordinate:{axis}')
                    value = None
                coordinates[axis] = value
            if all(value is None for value in coordinates.values()):
                coordinates = None
            else:
                coordinates.update(units=field('units'), system=mapping.get('coordinate_system'))
                if coordinates['system'] is None:
                    issues.append('coordinate_system_unknown')
            entity_type = field('entity_type')
            data = {'tag': tag, 'block': field('block'), 'entity_type': entity_type,
                    'attributes': attributes, 'units': field('units'), 'quantity': field('quantity'),
                    'drawing_id': field('drawing_id'), 'discipline': document['discipline'],
                    'role': mapping.get('role'), 'scope': copy.deepcopy(mapping.get('scope')),
                    'parameters': []}
            for parameter in parameters:
                value = cell(parameter['value_column'])
                if value is not None:
                    data['parameters'].append({'name': parameter['name'], 'value': value,
                        'unit': cell(parameter['unit_column']) if parameter.get('unit_column') else parameter.get('fixed_unit')})
            source = {key: None for key in ('pdf_page', 'printed_page', 'pdf_page_label', 'bbox', 'table_id',
                                            'drawing_number', 'spec_section', 'clause')}
            source.update(sheet=mapping['sheet'], row=row_number, method=METHOD, layer=field('layer'),
                          handle=field('handle'), coordinates=coordinates, drawing_number=field('drawing_id'))
            package['records'].append({'kind': 'equipment' if entity_type == 'INSERT' else 'cad_entity',
                'raw_text': json.dumps(raw, ensure_ascii=False, allow_nan=False), 'source': source, 'data': data,
                'review': {'status': 'unreviewed', 'issues': issues}})
    finally:
        workbook.close()
    if _hash(path) != digest:
        raise ValueError('Source export changed during extraction; discard evidence and retry')
    return package


def _emit(value, output):
    encoded = json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False)
    if output:
        with Path(output).open('x', encoding='utf-8') as target:
            target.write(encoded + '\n')
    else:
        print(encoded)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    ingest = sub.add_parser('ingest')
    ingest.add_argument('path')
    ingest.add_argument('--mapping', required=True)
    ingest.add_argument('--metadata')
    probe = sub.add_parser('probe')
    probe.add_argument('--exporter')
    verify = sub.add_parser('verify')
    verify.add_argument('--exporter', required=True)
    verify.add_argument('--sha256', required=True)
    for command in (ingest, probe, verify):
        command.add_argument('--output')
    args = parser.parse_args(argv)
    try:
        if args.command == 'ingest':
            mapping = json.loads(Path(args.mapping).read_text(encoding='utf-8-sig'))
            metadata = json.loads(Path(args.metadata).read_text(encoding='utf-8-sig')) if args.metadata else None
            result = ingest_export(args.path, mapping, metadata)
        elif args.command == 'verify':
            result = verify_exporter(args.exporter, args.sha256)
        else:
            result = probe_exporter(args.exporter)
        _emit(result, args.output)
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(f'error: {error}', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
