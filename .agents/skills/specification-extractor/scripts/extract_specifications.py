"""Preserve local PDF specification paragraphs and candidate clause context."""
import argparse
import copy
import json
import math
from pathlib import Path
import re
import sys

VERSION = '1.0'
SECTION = re.compile(r'^(?:SECTION\s+)?(\d{2}\s+\d{2}\s+\d{2}(?:\.\d+)?)\s*[-\u2013:]?\s*(.*)$', re.I)
ARTICLE = re.compile(r'^(\d+\.\d+)\s+(.+)$')
PART = re.compile(r'^PART\s+(\d+)\b', re.I)
ITEM = re.compile(r'^([A-Z])\.\s+')
DISCIPLINES = [('HVAC', r'\bHVAC\b'), ('electrical', r'\belectrical\b'),
               ('fire alarm', r'\bfire\s+alarm\b'), ('plumbing', r'\bplumbing\b'),
               ('fire protection', r'\bfire\s+protection\b'), ('BMS', r'\bBMS\b'),
               ('low current', r'\blow\s+current\b'), ('fire fighting', r'\bfire\s*fighting\b')]


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
    pages = {r['source']['pdf_page'] for r in package['records'] if r.get('kind') == 'page'}
    for record in package['records']:
        page = record['source']['pdf_page']
        if (type(page_count) is int and page > page_count) or (pages and page not in pages):
            raise ValueError('Record page is outside observed PDF pages')


def _fragment(lines, section, clause, part, kind, continuation=False):
    source = copy.deepcopy(lines[0][1]['source'])
    source['upstream_method'] = source['method']
    source['method'] = f'specification-extractor/{VERSION}; local line grouping'
    source['spec_section'] = section
    source['clause'] = clause
    source['input_record_indexes'] = [index for index, _ in lines]
    boxes = [record['source'].get('bbox') for _, record in lines]
    source['bbox'] = ([min(b[0] for b in boxes), min(b[1] for b in boxes),
                       max(b[2] for b in boxes), max(b[3] for b in boxes)]
                      if all(b is not None for b in boxes) else None)
    raw = '\n'.join(record['raw_text'] for _, record in lines)
    issues = [] if source['bbox'] is not None else [dict(code='missing_bbox', message='At least one input line lacks a bbox; no complete paragraph bbox inferred.')]
    if continuation:
        issues.append(dict(code='continuation_candidate', message='Page-edge continuation is a layout heuristic; verify linked fragments.'))
    return dict(kind='specification', raw_text=raw, source=source,
                data=dict(type=kind, part=part, continuation_candidate=continuation,
                          discipline_mentions=[name for name, pattern in DISCIPLINES if re.search(pattern, raw, re.I)],
                          line_fragments=[dict(raw_text=r['raw_text'], source=copy.deepcopy(r['source']), input_record_index=i) for i, r in lines]),
                review=dict(status='unreviewed', issues=issues))


def extract_specifications(package):
    """Consume PDF line evidence without mutating input or inventing project facts.

    Paragraphs remain page fragments. Clauses spanning page edges share a generated
    internal group only when the previous fragment is at the page bottom and the
    next unnumbered text is at the following page top; this remains a candidate.
    """
    _validate(package)
    result = dict(schema_version='mep-evidence/1', document=copy.deepcopy(package['document']),
                  records=[], issues=copy.deepcopy(package['issues']))
    result['issues'].append(dict(code='specification_layout_review', message='Line grouping, section/clause context and page continuations are candidates for review. Headers, footers and columns are not semantically resolved.'))
    lines = [(i, r) for i, r in enumerate(package['records']) if r.get('kind') == 'line']
    # Page order is physical PDF order; within a page preserve extractor order.
    lines.sort(key=lambda item: item[1]['source']['pdf_page'])
    heights = {r['source']['pdf_page']: r['data'].get('height') for r in package['records'] if r.get('kind') == 'page'}
    section = article = clause = part = None
    pending = []
    pending_parent = None
    records = result['records']

    def flush():
        nonlocal pending_parent
        if pending:
            fragment = _fragment(pending, section, clause, part, 'paragraph', continuation=pending_parent is not None)
            if pending_parent is not None:
                fragment['data']['continuation_of'] = pending_parent
            records.append(fragment)
            pending.clear()
        pending_parent = None

    for index, record in lines:
        text = record['raw_text']
        stripped = text.strip()
        if not stripped:
            flush()
            continue
        section_match = SECTION.match(stripped)
        article_match = ARTICLE.match(stripped)
        part_match = PART.match(stripped)
        item_match = ITEM.match(stripped)
        if section_match or article_match or part_match or item_match:
            flush()
            if section_match:
                section = section_match.group(1)
                article = clause = part = None
                kind = 'section'
            elif part_match:
                part = part_match.group(1)
                article = clause = None
                kind = 'part'
            elif article_match:
                article = clause = article_match.group(1)
                kind = 'clause'
            else:
                clause = (article + '.' if article else '') + item_match.group(1)
                pending.append((index, record))
                continue
            records.append(_fragment([(index, record)], section, clause, part, kind))
            continue
        if pending:
            previous = pending[-1][1]
            previous_page = previous['source']['pdf_page']
            page = record['source']['pdf_page']
            previous_box = previous['source'].get('bbox')
            box = record['source'].get('bbox')
            if page != previous_page:
                height = heights.get(previous_page)
                join = (page == previous_page + 1 and previous_box is not None and box is not None
                        and type(height) in (int, float) and previous_box[3] >= height * .85 and box[1] <= height * .15)
                flush()
                pending_parent = len(records) - 1 if join else None
                pending.append((index, record))
                continue
            if previous_box is None or box is None or box[1] - previous_box[3] > max(8, (previous_box[3] - previous_box[1]) * .8):
                flush()
        pending.append((index, record))
    flush()
    groups = {}
    for index, record in enumerate(records):
        parent = record['data'].pop('continuation_of', None)
        group = records[parent]['data']['clause_group'] if parent is not None else f'fragment-group-{index + 1}'
        record['data']['clause_group'] = group
        groups.setdefault(group, []).append(record)
    for fragments in groups.values():
        locators = [dict(raw_text=r['raw_text'], **copy.deepcopy(r['source'])) for r in fragments]
        for record in fragments:
            record['data']['fragments'] = copy.deepcopy(locators)
    if not lines:
        result['issues'].append(dict(code='no_line_evidence', message='No line records supplied; extract PDF text first and inspect OCR warnings.'))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path, help='mep-evidence/1 JSON containing PDF line records')
    parser.add_argument('--output', type=Path, help='New JSON file; exclusive create. Default: stdout')
    args = parser.parse_args(argv)
    try:
        if args.output and args.output.exists():
            raise FileExistsError(f'Refusing overwrite: {args.output}')
        result = extract_specifications(json.loads(args.input.read_text(encoding='utf-8-sig')))
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
