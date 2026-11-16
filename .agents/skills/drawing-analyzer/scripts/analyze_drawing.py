"""Find text-only MEP tag candidates in a local mep-evidence/1 PDF package."""
import argparse
import copy
import json
import math
from pathlib import Path
import re
import sys

VERSION = '1.0'
TAG = re.compile(r'(?<!\w)(?:AHU|FCU|FAHU|MAU|RTU|VAV|VFD|EF|SF|RF|CHWP|CWP|CHW|CH|PUMP|P|FAN|DB|MDB|SMDB|ATS|UPS|FACP|FD|SD|WH|EWH|HRU|CU|AC|ACCU|DDC|BMS|PLC|CCTV|ACP|FA)[-_](?=[A-Z0-9/_-]*\d)[A-Z0-9]+(?:[-_/][A-Z0-9]+)*(?!\w)', re.IGNORECASE)
FIELDS = {
    'drawing_number': r'^(?:DRAWING|SHEET)\s*(?:NO\.?|NUMBER|#)\s*:\s*(\S+)\s*$',
    'revision': r'^REV(?:ISION)?\.?\s*:\s*(\S+)\s*$',
    'discipline': r'^DISCIPLINE\s*:\s*(.+?)\s*$',
    'floor': r'^(?:FLOOR|LEVEL)\s*:\s*(.+?)\s*$',
    'room': r'^ROOM\s*:\s*(.+?)\s*$',
}


def _validate(package):
    if not isinstance(package, dict) or package.get('schema_version') != 'mep-evidence/1':
        raise ValueError('Expected mep-evidence/1 package')
    doc = package.get('document')
    if not isinstance(doc, dict) or doc.get('media_type') != 'pdf' or not re.fullmatch(r'[0-9a-f]{64}', doc.get('sha256', '')):
        raise ValueError('Expected PDF document with SHA256')
    if not isinstance(package.get('records'), list) or not isinstance(package.get('issues'), list):
        raise ValueError('Expected records and issues arrays')
    for record in package['records']:
        if not isinstance(record, dict) or not isinstance(record.get('raw_text'), str) or not isinstance(record.get('data'), dict):
            raise ValueError('Invalid evidence record')
        source = record.get('source')
        if not isinstance(source, dict) or type(source.get('pdf_page')) is not int or source['pdf_page'] < 1 or not source.get('method'):
            raise ValueError('Each PDF record needs a one-based page and extraction method')
        bbox = source.get('bbox')
        if bbox is not None and (not isinstance(bbox, (list, tuple)) or len(bbox) != 4 or
                not all(type(v) in (int, float) and math.isfinite(v) for v in bbox) or bbox[2] < bbox[0] or bbox[3] < bbox[1]):
            raise ValueError('Invalid PDF evidence bbox')
    page_count = doc.get('metadata', {}).get('page_count')
    observed_pages = {r['source']['pdf_page'] for r in package['records'] if r.get('kind') == 'page'}
    for record in package['records']:
        page = record['source']['pdf_page']
        if ((type(page_count) is int and page > page_count) or
                (observed_pages and page not in observed_pages)):
            raise ValueError('Record page is outside observed PDF pages')


def _source(record, index):
    source = copy.deepcopy(record['source'])
    source['upstream_method'] = source['method']
    source['method'] = f'drawing-analyzer/{VERSION}; local text candidate matching'
    source['input_record_index'] = index
    return source


def _single(values):
    unique = set(values)
    return next(iter(unique)) if len(unique) == 1 else None


def _inline_location(word_record, lines, tag):
    """Accept contiguous, single-tag inline labeled fields, never nearby room labels."""
    page = word_record['source']['pdf_page']
    word_box = word_record['source'].get('bbox')
    if word_box is None:
        return {}, None
    for index, line in lines:
        if line['source']['pdf_page'] != page:
            continue
        box = line['source'].get('bbox')
        if box is None or not (box[0] <= word_box[0] and box[1] <= word_box[1] and word_box[2] <= box[2] and word_box[3] <= box[3]):
            continue
        text = line['raw_text']
        if len(list(TAG.finditer(text))) != 1:
            continue
        # A single tag followed immediately by explicit inline fields supports association.
        prefix = re.match(r'^' + re.escape(tag) + r'\s+(?=(?:ROOM|FLOOR|LEVEL)\s*:)', text, re.IGNORECASE)
        if not prefix:
            continue
        suffix = text[prefix.end():]
        matches = list(re.finditer(r'(ROOM|FLOOR|LEVEL)\s*:\s*([^;]+?)(?=\s+(?:ROOM|FLOOR|LEVEL)\s*:|;|$)', suffix, re.IGNORECASE))
        fields = {}
        for match in matches:
            key = 'room' if match.group(1).upper() == 'ROOM' else 'floor'
            fields.setdefault(key, []).append(match.group(2).strip())
        fields = {key: _single(values) for key, values in fields.items()}
        return fields, dict(raw_text=text, source=copy.deepcopy(line['source']), input_record_index=index,
                            association='single-tag inline labeled fields; candidate for review')
    return {}, None


def analyze_drawing(package):
    """Return candidate text occurrences and explicitly labeled metadata, with evidence.

    No graphics/symbols, dimensions, scale, quantity or spatial room inference.
    Input is not mutated. Generated indexes are internal locators, not project IDs.
    """
    _validate(package)
    result = dict(schema_version='mep-evidence/1', document=copy.deepcopy(package['document']),
                  records=[], issues=copy.deepcopy(package['issues']))
    result['issues'].append(dict(code='text_candidates_only', message='Tag matches are text occurrences, not physical equipment or quantities. Symbols, unsupported tag formats and image text are not analyzed.'))
    lines = [(i, r) for i, r in enumerate(package['records']) if r.get('kind') == 'line']
    page_fields = {}
    metadata_records = []
    for index, record in lines:
        for field, pattern in FIELDS.items():
            match = re.match(pattern, record['raw_text'], re.IGNORECASE)
            if not match:
                continue
            value = match.group(1)
            page = record['source']['pdf_page']
            page_fields.setdefault(page, {}).setdefault(field, []).append(value)
            source = _source(record, index)
            if field == 'drawing_number':
                source['drawing_number'] = value
            metadata_records.append(dict(kind='drawing_metadata', raw_text=record['raw_text'], source=source,
                data={field: value, 'explicit_label': True}, review=dict(status='unreviewed', issues=[])))
    result['records'].extend(metadata_records)
    for field in ('drawing_number', 'revision', 'discipline'):
        values = [value for fields in page_fields.values() for value in fields.get(field, [])]
        supplied = result['document'].get(field)
        if supplied is not None:
            values.append(supplied)
        if values:
            result['document'][field] = _single(values)
        if len(set(values)) > 1:
            result['issues'].append(dict(code='multiple_document_values', field=field,
                values=sorted(set(values)), message='Conflicting or page-specific values retained in evidence; document-level field is null.'))
    for index, record in enumerate(package['records']):
        if record.get('kind') != 'word':
            continue
        for match in TAG.finditer(record['raw_text']):
            source = _source(record, index)
            page = source['pdf_page']
            source['drawing_number'] = _single(page_fields.get(page, {}).get('drawing_number', []))
            source['bbox_scope'] = 'original extracted word, not a recognized symbol or physical position'
            location, evidence = _inline_location(record, lines, match.group(0))
            issues = []
            if source.get('bbox') is None:
                issues.append(dict(code='missing_bbox', message='Input word has no observed bbox; no coordinates were fabricated.'))
            result['records'].append(dict(kind='equipment', raw_text=record['raw_text'], source=source,
                data=dict(tag=match.group(0), match_span=[match.start(), match.end()], quantity=None,
                          discipline=None, role='drawing', candidate=True, occurrence_only=True,
                          floor=location.get('floor'), room=location.get('room'), location_evidence=evidence),
                review=dict(status='unreviewed', issues=issues)))
    if not lines:
        result['issues'].append(dict(code='no_line_evidence', message='No line records supplied; explicit title metadata and inline room/floor associations unavailable.'))
    if not any(r.get('kind') == 'word' for r in package['records']):
        result['issues'].append(dict(code='no_word_evidence', message='No word records supplied; no tag recognition attempted. Create PDF evidence first; inspect scan warnings.'))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path, help='mep-evidence/1 JSON containing PDF word/line records')
    parser.add_argument('--output', type=Path, help='New JSON file; exclusive create. Default: stdout')
    args = parser.parse_args(argv)
    try:
        if args.output and args.output.exists():
            raise FileExistsError(f'Refusing overwrite: {args.output}')
        package = json.loads(args.input.read_text(encoding='utf-8-sig'))
        result = analyze_drawing(package)
        serialized = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
        if args.output:
            with args.output.open('x', encoding='utf-8') as output:
                output.write(serialized)
        else:
            if hasattr(sys.stdout, 'reconfigure'):
                sys.stdout.reconfigure(encoding='utf-8')
            sys.stdout.write(serialized)
    except Exception as exc:
        parser.exit(2, f'{type(exc).__name__}: {exc}\n')
    return 0


if __name__ == '__main__':
    main()
