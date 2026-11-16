"""Extract local PDF evidence, without OCR or engineering interpretation."""
import argparse
import copy
import hashlib
import io
import json
from pathlib import Path
import sys

VERSION = '1.0'


def _source(page, label, method, bbox=None, **extra):
    source = dict(pdf_page=page, printed_page=None, pdf_page_label=label,
                  bbox=list(bbox) if bbox is not None else None, table_id=None,
                  sheet=None, row=None, drawing_number=None, spec_section=None,
                  clause=None, method=method, layer=None, handle=None,
                  coordinates=None, coordinate_system='PDF points; x right, y down from page top')
    source.update(extra)
    return source


def _record(kind, raw_text, source, data):
    return dict(kind=kind, raw_text=raw_text, source=source, data=data,
                review=dict(status='unreviewed', issues=[]))


def _json_safe(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return str(value)


def _table_location(bbox, tables):
    """Assign only a word/line completely contained by an observed row box."""
    x0, top, x1, bottom = bbox
    for table_id, rows in tables:
        for row_number, row in enumerate(rows, 1):
            rx0, rtop, rx1, rbottom = row.bbox
            if rx0 <= x0 <= x1 <= rx1 and rtop <= top <= bottom <= rbottom:
                return dict(table_id=table_id, row=row_number)
    return {}


def extract_pdf(path, metadata=None):
    """Return mep-evidence/1 records for pages, words, lines, tables and rows.

    metadata optionally supplies document_id/revision/discipline/drawing_number;
    these caller assertions are retained separately and never inferred from a name.
    The hash and parsed PDF are derived from the same immutable in-memory bytes.
    """
    try:
        import pdfplumber
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError('PDF extraction requires local pdfplumber and pypdf; see SKILL.md.') from exc
    path = Path(path).expanduser().resolve(strict=True)
    if not path.is_file():
        raise ValueError('PDF input must be an existing local file')
    if metadata is not None and not isinstance(metadata, dict):
        raise ValueError('metadata must be a JSON object')
    metadata = copy.deepcopy(metadata or {})
    payload = path.read_bytes()
    reader = PdfReader(io.BytesIO(payload))
    if reader.is_encrypted:
        raise ValueError('Encrypted PDF unsupported; provide an authorized decrypted copy')
    printed_pages = metadata.get('printed_pages', {})
    if not isinstance(printed_pages, dict):
        raise ValueError('printed_pages must map one-based PDF page numbers to user-supplied labels')
    for key, value in printed_pages.items():
        if (not str(key).isdigit() or str(int(key)) != str(key) or not 1 <= int(key) <= len(reader.pages)
                or type(value) not in (str, int) or value == ''):
            raise ValueError('Invalid user-supplied printed_pages label or PDF page')
    printed_pages = {int(key): value for key, value in printed_pages.items()}
    # pypdf supplies numeric defaults even without /PageLabels; those are not evidence.
    labels = reader.page_labels if '/PageLabels' in reader.trailer['/Root'] else None
    method = f'pdf-to-structured/{VERSION}; pdfplumber/{pdfplumber.__version__}'
    document = dict(path=str(path), filename=path.name,
                    sha256=hashlib.sha256(payload).hexdigest(),
                    document_id=metadata.get('document_id'), revision=metadata.get('revision'),
                    discipline=metadata.get('discipline'), drawing_number=metadata.get('drawing_number'),
                    media_type='pdf', metadata=dict(pdf_metadata=_json_safe(reader.metadata or {}),
                        supplied_metadata=metadata, extractor=method,
                        page_count=len(reader.pages), ocr_performed=False))
    package = dict(schema_version='mep-evidence/1', document=document, records=[], issues=[])
    records = package['records']
    with pdfplumber.open(io.BytesIO(payload)) as pdf:
        for page_number, page in enumerate(pdf.pages, 1):
            label = labels[page_number - 1] if labels else None
            text = page.extract_text() or ''
            records.append(_record('page', text,
                _source(page_number, label, method, page.bbox),
                dict(width=page.width, height=page.height, rotation=page.rotation,
                     image_count=len(page.images), ocr_performed=False)))
            if not text.strip():
                code = 'ocr_needed' if page.images else 'no_extractable_text'
                message = ('Raster content has no extractable text; local OCR and visual review are required.'
                           if page.images else 'No extractable text; page may be blank, outlined, or require OCR. Inspect visually.')
                package['issues'].append(dict(code=code, pdf_page=page_number, message=message))
            elif page.images:
                package['issues'].append(dict(code='raster_content_unprocessed', pdf_page=page_number,
                    message='Images are present; text extraction does not read their contents. Inspect for missing scanned content.'))
            if any(ord(char) > 127 for char in text):
                package['issues'].append(dict(code='unicode_text_review', pdf_page=page_number,
                    message='Non-ASCII text preserved as extracted; verify font decoding, Arabic/RTL order and tag spelling visually. No OCR performed.'))
            if '\ufffd' in text or '(cid:' in text:
                package['issues'].append(dict(code='font_decoding_review', pdf_page=page_number,
                    message='Replacement glyphs/CID placeholders detected; text may be incomplete. Inspect original and obtain verified OCR if needed.'))
            found_tables = page.find_tables()
            table_rows = []
            for table_number, table in enumerate(found_tables, 1):
                table_id = f'p{page_number}-t{table_number}'
                cells = table.extract()
                table_rows.append((table_id, table.rows))
                records.append(_record('table', json.dumps(cells, ensure_ascii=False),
                    _source(page_number, label, method, table.bbox, table_id=table_id),
                    dict(cells=cells, table_id_is_internal=True)))
                for row_number, (row, values) in enumerate(zip(table.rows, cells), 1):
                    records.append(_record('table_row', json.dumps(values, ensure_ascii=False),
                        _source(page_number, label, method, row.bbox, table_id=table_id, row=row_number),
                        dict(cells=values, cell_bboxes=[list(cell) if cell else None for cell in row.cells])))
            for line_number, line in enumerate(page.extract_text_lines(return_chars=False), 1):
                bbox = [line[key] for key in ('x0', 'top', 'x1', 'bottom')]
                records.append(_record('line', line['text'],
                    _source(page_number, label, method, bbox, line_index=line_number,
                            **_table_location(bbox, table_rows)), {}))
            for word_number, word in enumerate(page.extract_words(), 1):
                bbox = [word[key] for key in ('x0', 'top', 'x1', 'bottom')]
                records.append(_record('word', word['text'],
                    _source(page_number, label, method, bbox, word_index=word_number,
                            **_table_location(bbox, table_rows)),
                    dict(direction=word.get('direction'), upright=word.get('upright'))))
            page.close()
    for record in records:
        page_number = record['source']['pdf_page']
        if page_number in printed_pages:
            record['source']['printed_page'] = printed_pages[page_number]
            record['source']['printed_page_method'] = 'user_supplied'
    return package


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path, help='Existing local native PDF; scanned pages are flagged, never OCRed')
    parser.add_argument('--metadata', type=Path, help='Optional JSON object of explicitly supplied document metadata')
    parser.add_argument('--output', type=Path, help='New JSON file (exclusive create); default: JSON on stdout')
    args = parser.parse_args(argv)
    try:
        if args.output and args.output.exists():
            raise FileExistsError(f'Refusing overwrite: {args.output}')
        metadata = json.loads(args.metadata.read_text(encoding='utf-8-sig')) if args.metadata else None
        result = extract_pdf(args.input, metadata)
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
