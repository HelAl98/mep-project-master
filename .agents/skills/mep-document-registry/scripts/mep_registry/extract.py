"""Bounded, local document metadata extraction. No equipment or approval inference.

Only labeled literals are content_extracted. Naming/rule candidates retain their
basis. Every result is unreviewed and conflicting observations are preserved.
"""
from copy import deepcopy
import codecs
import csv
import importlib.util
import io
from pathlib import Path
import re
import zipfile

FIELDS = ('document_number', 'title', 'revision', 'revision_date', 'issue_status',
          'discipline', 'document_type', 'system', 'building', 'floor', 'scale', 'sheet_number')
DEFAULT_LIMITS = {'max_file_bytes': 100 * 1024 * 1024, 'small_pdf_max_bytes': 2 * 1024 * 1024,
                  'small_pdf_max_pages': 20, 'max_pdf_pages': 2000,
                  'max_rows_per_sheet': 10000, 'max_columns': 200, 'max_sheets': 100,
                  'max_text_bytes': 8 * 1024 * 1024, 'max_lines': 100000,
                  'max_content_characters': 2 * 1024 * 1024,
                  'max_zip_uncompressed_bytes': 200 * 1024 * 1024}


def _key(value):
    return re.sub(r'[^a-z0-9]+', '', str(value).casefold())


_DISCIPLINES = {
    'HVAC': ('hvac', 'air conditioning', 'ventilation', 'heating ventilation and air conditioning'),
    'Plumbing': ('plumbing', 'public health', 'ph', 'plb'),
    'Fire Fighting': ('fire fighting', 'firefighting', 'ff', 'fire protection', 'sprinkler'),
    'Electrical Power': ('electrical power', 'power', 'ep', 'elec power'),
    'Lighting': ('lighting', 'ltg', 'light'),
    'Low Current': ('low current', 'lowcurrent', 'elv', 'ict', 'lc', 'extra low voltage'),
    'Fire Alarm': ('fire alarm', 'firealarm', 'fa'),
    'BMS': ('bms', 'building management system', 'building management systems', 'building automation'),
    'Other MEP': ('other mep', 'othermep'),
    'Mechanical': ('mechanical', 'mech'), 'Electrical': ('electrical', 'elec')}
_TYPES = {
    'Drawing': ('drawing', 'drawings', 'dwg', 'layout', 'layouts'),
    'Shop Drawing': ('shop drawing', 'shop drawings', 'shopdrawing'),
    'As Built Drawing': ('as built', 'as-built', 'as built drawing', 'asbuilt'),
    'Specification': ('specification', 'specifications', 'spec', 'specs'),
    'BOQ': ('boq', 'bill of quantities', 'billofquantities'),
    'Equipment Schedule': ('equipment schedule', 'equipment schedules', 'schedule'),
    'Calculation': ('calculation', 'calculations', 'calc', 'design calculation'),
    'Report': ('report', 'technical report', 'reports'),
    'Submittal': ('submittal', 'material submittal', 'technical submittal'),
    'Method Statement': ('method statement', 'methodstatement'),
    'RFI': ('rfi', 'request for information'),
    'Datasheet': ('datasheet', 'data sheet', 'technical data sheet'),
    'Manual': ('manual', 'operation and maintenance', 'o&m', 'om manual'),
    'Certificate': ('certificate', 'certificates'),
    'Other': ('other',)}
ALIASES = {'discipline': { _key(alias): canonical for canonical, aliases in _DISCIPLINES.items() for alias in aliases},
           'document_type': {_key(alias): canonical for canonical, aliases in _TYPES.items() for alias in aliases}}
_LABELS = {
    'document_number': ('document number', 'document no', 'doc no', 'drawing number', 'drawing no', 'dwg no', 'drawing #'),
    'sheet_number': ('sheet number', 'sheet no', 'sheet #'),
    'title': ('title', 'document title', 'drawing title', 'sheet title'),
    'revision': ('revision', 'rev', 'revision number', 'revision no'),
    'revision_date': ('revision date', 'rev date', 'issue date', 'date'),
    'issue_status': ('issue status', 'status', 'issued for'),
    'discipline': ('discipline', 'trade'), 'document_type': ('document type', 'drawing type', 'category'),
    'system': ('system', 'system name'), 'building': ('building', 'building name', 'block'),
    'floor': ('floor', 'level'), 'scale': ('scale',)}
LABEL_FIELDS = {_key(label): field for field, aliases in _LABELS.items() for label in aliases}
# Long alternatives precede short ones so REVISION DATE is never parsed as REVISION.
LABEL_PATTERN = re.compile(r'^\s*(?:#{1,6}\s+)?(?P<label>' + '|'.join(
    re.escape(label).replace(r'\ ', r'\s+') + r'\.?' for label in sorted(
        (label for aliases in _LABELS.values() for label in aliases), key=len, reverse=True))
    + r')\s*[:=]\s*(?P<value>.*?)\s*$', re.I)


def _issue(result, code, message, source=None, severity='review'):
    result['issues'].append({'code': code, 'message': message, 'source': source or {}, 'severity': severity})


def _observation(field, value, evidence, source, confidence=None):
    raw = value
    if value is not None:
        value = str(value).strip()
        value = ALIASES.get(field, {}).get(_key(value), value)
    return {'field': field, 'value': value, 'raw_value': raw, 'evidence_class': evidence,
            'confidence': confidence or ('high' if evidence == 'content_extracted' else 'low'),
            'source': deepcopy(source), 'review_status': 'unreviewed'}


def _literal(text, source, observations):
    match = LABEL_PATTERN.match(text)
    if match and match['value'].strip():
        observations.append(_observation(LABEL_FIELDS[_key(match['label'])], match['value'].strip(),
                           'content_extracted', {**source, 'text': text}))


def _pair(label, value, source, observations):
    field = LABEL_FIELDS.get(_key(str(label).strip().rstrip(':=')))
    if field and value is not None and str(value).strip():
        observations.append(_observation(field, str(value), 'content_extracted',
                           {**source, 'label': str(label), 'text': str(value)}))


def _load_helper(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _rules(result, config, filename, relative_path, content, page=None, sink=None):
    observations = sink if sink is not None else result['observations']
    for index, rule in enumerate(config.get('classification_rules', [])):
        try:
            target = rule.get('target', 'relative_path')
            if target not in ('relative_path', 'filename', 'content'):
                raise ValueError('target must be relative_path, filename or content')
            if content is None and target == 'content':
                continue
            if content is not None and target != 'content':
                continue
            text = {'relative_path': relative_path, 'filename': filename, 'content': content}[target]
            match = re.search(rule['pattern'], text, re.I)
            if not match:
                continue
            values = dict(rule.get('fields', {}))
            values.update({field: match.group(group) for field, group in rule.get('captures', {}).items()})
            for field, value in values.items():
                if field not in FIELDS:
                    raise ValueError('unknown metadata field: ' + str(field))
                if value is None:
                    continue
                source = {'method': 'classification-rule', 'rule_id': rule.get('id', str(index + 1)),
                          'target': target, 'pattern': rule['pattern'], 'matched_text': match.group(),
                          'basis': 'rule candidate, unverified', 'text': text if target != 'content' else match.group()}
                if page is not None:
                    source['pdf_page'] = page
                observations.append(_observation(field, value,
                     'inferred' if target == 'content' else 'filename_derived', source))
        except (KeyError, TypeError, ValueError, IndexError, re.error, AttributeError) as exc:
            source = {'rule_index': index, 'pdf_page': page}
            if not any(i['code'] == 'INVALID_CLASSIFICATION_RULE' and i['source'].get('rule_index') == index for i in result['issues']):
                _issue(result, 'INVALID_CLASSIFICATION_RULE', str(exc), source)


def _naming(result, filename, relative_path):
    stem = Path(filename).stem
    source = {'method': 'filename-heuristic', 'filename': filename,
              'relative_path': relative_path, 'basis': 'filename candidate, unverified'}
    if stem.strip():
        result['observations'].append(_observation('title', stem, 'filename_derived', source))
    rev = re.search(r'(?:^|[\s_.-])REV(?:ISION)?[\s_.-]*([A-Za-z0-9]+)(?=$|[\s_.-])', stem, re.I)
    if rev:
        result['observations'].append(_observation('revision', rev[1], 'filename_derived', {**source, 'matched_text': rev[0]}))
    date = re.search(r'(?<!\d)(?:19|20)\d{2}[-_.](?:0[1-9]|1[0-2])[-_.](?:0[1-9]|[12]\d|3[01])(?!\d)', stem)
    if date:
        result['observations'].append(_observation('revision_date', date[0], 'filename_derived', {**source, 'matched_text': date[0]}))
    # Match whole path components or token phrases, not engineering tags or equipment.
    normalized_path = re.sub(r'[_/\\.\-]+', ' ', relative_path)
    for field, catalog in (('discipline', _DISCIPLINES), ('document_type', _TYPES)):
        found = []
        for canonical, aliases in catalog.items():
            for alias in aliases:
                if re.search(r'(?<!\w)' + re.escape(alias).replace(r'\ ', r'\s+') + r'(?!\w)', normalized_path, re.I):
                    found.append((canonical, alias))
                    break
        # Prefer more specific names to their contained generic names.
        for canonical, alias in found:
            if any(alias.casefold() in other_alias.casefold() and canonical != other for other, other_alias in found):
                continue
            result['observations'].append(_observation(field, canonical, 'filename_derived',
                    {**source, 'matched_text': alias}))


def _complete(observations, result, source=None):
    for field in FIELDS:
        observed = [o for o in observations if o['field'] == field and o['value'] is not None]
        if not observed:
            observations.append(_observation(field, None, 'missing', source or {'method': 'metadata-not-observed'}, 'unknown'))
        # Weaker naming candidates do not make an explicit literal ambiguous.
        literals = [o for o in observed if o['evidence_class'] == 'content_extracted']
        candidates = literals or observed
        values = sorted({o['value'] for o in candidates})
        if len(values) > 1:
            _issue(result, 'CONFLICTING_METADATA', 'Conflicting ' + field + ' candidates retained; requires review.',
                   {**(source or {}), 'field': field, 'values': values})


def _check_zip(path, limits):
    with zipfile.ZipFile(path) as archive:
        if sum(info.file_size for info in archive.infolist()) > limits['max_zip_uncompressed_bytes']:
            raise ValueError('Archive uncompressed size exceeds max_zip_uncompressed_bytes')


def _capture_content(result, text, limits):
    """Accumulate only a bounded prefix for nonliteral classification rules."""
    remaining = limits['max_content_characters'] - result.get('_content_size', 0)
    if remaining <= 0:
        return
    fragment = str(text)[:remaining]
    result.setdefault('_content', []).append(fragment)
    result['_content_size'] = result.get('_content_size', 0) + len(fragment) + 1


def _pdf(path, result, config, limits, skills_root, filename, relative_path):
    import pdfplumber
    with pdfplumber.open(path) as pdf:
        count = len(pdf.pages)
    result['metadata']['page_count'] = count
    small = (skills_root is not None and path.stat().st_size <= limits['small_pdf_max_bytes'] and
             count <= min(limits['small_pdf_max_pages'], limits['max_pdf_pages']))
    package = None
    helper_path = Path(skills_root) / 'pdf-to-structured/scripts/extract_pdf.py' if skills_root else None
    if small and helper_path.is_file():
        package = _load_helper(helper_path, '_registry_pdf_evidence').extract_pdf(path)
        result['metadata']['parser'] = 'pdf-to-structured'
        for issue in package['issues']:
            _issue(result, issue['code'].upper(), issue['message'], {'pdf_page': issue.get('pdf_page')})
        # The analyzer receives ONLY line/page records. It cannot emit equipment.
        analyzer_path = Path(skills_root) / 'drawing-analyzer/scripts/analyze_drawing.py'
        if analyzer_path.is_file():
            subset = {**package, 'records': [r for r in package['records'] if r['kind'] in ('page', 'line')]}
            analyzed = _load_helper(analyzer_path, '_registry_drawing_metadata').analyze_drawing(subset)
            result['metadata']['drawing_metadata_adapter'] = 'drawing-analyzer; line/page subset only'
            analyzer_metadata = [r for r in analyzed['records'] if r['kind'] == 'drawing_metadata']
        else:
            analyzer_metadata = []
        pages = []
        for page in range(1, count + 1):
            records = [r for r in package['records'] if r['kind'] == 'line' and r['source']['pdf_page'] == page]
            pages.append((page, records, [r for r in analyzer_metadata if r['source']['pdf_page'] == page]))
        for page, records, metadata in pages:
            _pdf_page(page, records, metadata, result, config, filename, relative_path, limits)
    else:
        result['metadata']['parser'] = 'pdfplumber-stream'
        with pdfplumber.open(path) as pdf:
            for page_number, page in enumerate(pdf.pages, 1):
                if page_number > limits['max_pdf_pages']:
                    _issue(result, 'EXTRACTION_LIMIT', 'PDF page limit reached; later pages unprocessed.', {'pdf_page': page_number})
                    break
                records = []
                for index, line in enumerate(page.extract_text_lines(return_chars=False), 1):
                    records.append({'raw_text': line['text'], 'source': {'method': 'pdfplumber-labeled-line',
                         'pdf_page': page_number, 'line': index, 'bbox': [line[k] for k in ('x0', 'top', 'x1', 'bottom')]}})
                    if index >= limits['max_lines']:
                        _issue(result, 'EXTRACTION_LIMIT', 'PDF per-page line limit reached.', {'pdf_page': page_number})
                        break
                if not records:
                    _issue(result, 'OCR_NEEDED' if page.images else 'NO_EXTRACTABLE_TEXT',
                           'No extractable text; inspect page. OCR is not performed.', {'pdf_page': page_number})
                elif page.images:
                    _issue(result, 'RASTER_CONTENT_UNPROCESSED', 'Image contents are not extracted.', {'pdf_page': page_number})
                _pdf_page(page_number, records, [], result, config, filename, relative_path, limits)
                page.close()


def _pdf_page(page, records, analyzer_metadata, result, config, filename, relative_path, limits):
    observations = []
    for record in records[:limits['max_lines']]:
        _literal(record['raw_text'], record['source'], observations)
    for record in analyzer_metadata:
        for name, value in record['data'].items():
            field = {'drawing_number': 'document_number'}.get(name, name)
            # The existing analyzer aliases SHEET NUMBER to drawing_number;
            # registry identities must keep these different literal fields separate.
            if name == 'drawing_number' and re.match(r'^\s*SHEET\b', record['raw_text'], re.I):
                field = 'sheet_number'
            if field not in FIELDS or any(o['field'] == field and o['raw_value'] == value for o in observations):
                continue
            observations.append(_observation(field, value, 'content_extracted',
                {**record['source'], 'text': record['raw_text']}))
    content = '\n'.join(r['raw_text'] for r in records)[:limits['max_content_characters']]
    _rules(result, config, filename, relative_path, content, page, observations)
    result['observations'].extend(deepcopy(observations))
    type_facts = [o for o in observations if o['field'] == 'document_type' and o['value'] is not None]
    priority = {'content_extracted':3, 'filename_derived':2, 'inferred':1, 'missing':0}
    strongest = max((priority[o['evidence_class']] for o in type_facts), default=0)
    page_types = [o['value'] for o in type_facts if priority[o['evidence_class']] == strongest]
    file_types = [o['value'] for o in result['observations'] if o['field'] == 'document_type'
                  and o['evidence_class'] == 'filename_derived' and o['source'].get('pdf_page') is None]
    drawing = (any(o['field'] == 'sheet_number' for o in observations) or
               any(re.match(r'^\s*(?:DRAWING|DWG)\s*(?:NO\.?|NUMBER|#)\s*:', r['raw_text'], re.I) for r in records) or
               any(value in ('Drawing', 'Shop Drawing', 'As Built Drawing') for value in (page_types or file_types)))
    if drawing:
        source = {'method': 'pdf-page', 'pdf_page': page}
        _complete(observations, result, source)
        result['sheets'].append({'pdf_page': page, 'observations': observations, 'source': source, 'sheet_kind': 'drawing_sheet'})


def _rows(rows, result, limits, method, sheet=None):
    for row_number, row in enumerate(rows, 1):
        if row_number > limits['max_rows_per_sheet']:
            _issue(result, 'EXTRACTION_LIMIT', 'Row limit reached; later rows unprocessed.', {'sheet': sheet, 'row': row_number})
            break
        if len(row) > limits['max_columns']:
            _issue(result, 'EXTRACTION_LIMIT', 'Column limit reached.', {'sheet': sheet, 'row': row_number})
        row = row[:limits['max_columns']]
        values = [getattr(cell, 'value', cell) for cell in row]
        for column, value in enumerate(values, 1):
            if value is None:
                continue
            cell = row[column - 1]
            source = {'method': method, 'row': row_number, 'column': column}
            if sheet is not None:
                source['sheet'] = sheet
            if hasattr(cell, 'coordinate'):
                source['cell'] = cell.coordinate
            if getattr(cell, 'data_type', None) == 'f':
                _issue(result, 'FORMULA_NOT_EVALUATED', 'Formula retained in source; not used as a metadata value.', source)
                continue
            _capture_content(result, value, limits)
            _literal(str(value), source, result['observations'])
            if column >= 2 and values[column - 2] is not None:
                _pair(values[column - 2], value, source, result['observations'])


def extract_document(path, config=None, *, skills_root=None, original_name=None, relative_path=None):
    """Return unreviewed metadata candidates from an immutable local byte version.

    Config: classification_rules and extraction_limits (keys in DEFAULT_LIMITS).
    revision_order/exclude_globs are scanner/review concerns, never approvals here.
    """
    result = {'status': 'registered', 'observations': [], 'sheets': [], 'issues': [], 'metadata': {}}
    try:
        config = config or {}
        limits = dict(DEFAULT_LIMITS)
        for key, value in config.get('extraction_limits', {}).items():
            if key not in limits or type(value) is not int or value < 1:
                raise ValueError('Invalid extraction_limits entry: ' + str(key))
            limits[key] = value
        path = Path(path)
        filename = str(original_name or path.name).replace('\\', '/').rsplit('/', 1)[-1]
        relative_path = str(relative_path or filename)
        extension = Path(filename).suffix.lower()
        result['metadata'].update({'format': extension.lstrip('.'), 'parser': None,
                                   'extraction_limits': limits, 'ocr_performed': False})
        _naming(result, filename, relative_path)
        _rules(result, config, filename, relative_path, None)
        size = path.stat().st_size
        if size > limits['max_file_bytes']:
            result['status'] = 'registered_metadata_extraction_pending'
            _issue(result, 'EXTRACTION_LIMIT', 'Source exceeds max_file_bytes; byte version registered without parsing.')
        elif extension == '.dwg':
            result['status'] = 'registered_metadata_extraction_pending'
            _issue(result, 'DWG_EXTRACTION_PENDING', 'DWG bytes registered. No verified DWG metadata extractor or conversion is available.')
        elif extension == '.dxf':
            try:
                import ezdxf
            except ImportError:
                result['status'] = 'registered_metadata_extraction_pending'
                _issue(result, 'DXF_PARSER_UNAVAILABLE', 'Optional local ezdxf is unavailable; no DWG support is implied.')
            else:
                if size > limits['max_file_bytes']:
                    raise ValueError('DXF exceeds max_file_bytes')
                doc = ezdxf.readfile(path)
                result['metadata']['parser'] = 'ezdxf'
                for entity in doc.modelspace():
                    if entity.dxftype() in ('TEXT', 'MTEXT'):
                        text = entity.dxf.text if entity.dxftype() == 'TEXT' else entity.plain_text()
                        _literal(text, {'method': 'ezdxf-labeled-text', 'handle': entity.dxf.handle,
                           'layer': entity.dxf.layer, 'coordinates': list(entity.dxf.insert)}, result['observations'])
        elif extension == '.pdf':
            _pdf(path, result, config, limits, skills_root, filename, relative_path)
        elif extension in ('.docx', '.xlsx', '.xlsm'):
            if size > limits['max_file_bytes']:
                raise ValueError('Office source exceeds max_file_bytes')
            _check_zip(path, limits)
            payload = io.BytesIO(path.read_bytes())
            if extension == '.docx':
                from docx import Document
                document = Document(payload)
                result['metadata']['parser'] = 'python-docx'
                for index, paragraph in enumerate(document.paragraphs, 1):
                    if index > limits['max_lines']:
                        _issue(result, 'EXTRACTION_LIMIT', 'DOCX paragraph limit reached.')
                        break
                    _literal(paragraph.text, {'method': 'docx-labeled-paragraph', 'paragraph': index}, result['observations'])
                    _capture_content(result, paragraph.text, limits)
                for table_index, table in enumerate(document.tables, 1):
                    if table_index > limits['max_sheets']:
                        _issue(result, 'EXTRACTION_LIMIT', 'DOCX table limit reached.')
                        break
                    for row_index, row in enumerate(table.rows, 1):
                        if row_index > limits['max_rows_per_sheet']:
                            _issue(result, 'EXTRACTION_LIMIT', 'DOCX row limit reached.', {'table': table_index})
                            break
                        cells = row.cells[:limits['max_columns']]
                        for cell_index, cell in enumerate(cells, 1):
                            source = {'method': 'docx-table-labeled-cell', 'table': table_index, 'row': row_index, 'cell': cell_index}
                            _literal(cell.text, source, result['observations'])
                            _capture_content(result, cell.text, limits)
                            if cell_index >= 2:
                                _pair(cells[cell_index - 2].text, cell.text, source, result['observations'])
            else:
                from openpyxl import load_workbook
                book = load_workbook(payload, read_only=True, data_only=False, keep_links=False)
                result['metadata']['parser'] = 'openpyxl-read-only'
                try:
                    for index, sheet in enumerate(book.worksheets, 1):
                        if index > limits['max_sheets']:
                            _issue(result, 'EXTRACTION_LIMIT', 'Workbook sheet limit reached.')
                            break
                        _rows(sheet.iter_rows(max_col=limits['max_columns'], max_row=limits['max_rows_per_sheet'] + 1),
                              result, limits, 'xlsx-labeled-cell', sheet.title)
                        if sheet.max_column and sheet.max_column > limits['max_columns']:
                            _issue(result, 'EXTRACTION_LIMIT', 'Workbook column limit reached.', {'sheet': sheet.title})
                finally:
                    book.close()
            _rules(result, config, filename, relative_path, '\n'.join(result.get('_content', [])))
        elif extension in ('.txt', '.md', '.csv'):
            result['metadata']['parser'] = 'csv' if extension == '.csv' else 'utf-8-labeled-lines'
            with path.open('rb') as stream:
                payload = stream.read(limits['max_text_bytes'] + 1)
            truncated = len(payload) > limits['max_text_bytes']
            if truncated:
                _issue(result, 'EXTRACTION_LIMIT', 'Text byte limit reached; remaining source unprocessed.')
                payload = payload[:limits['max_text_bytes']]
            # A byte limit may split a final code point. Retain only complete
            # code points; invalid bytes elsewhere still yield a parser error.
            text = codecs.getincrementaldecoder('utf-8-sig')().decode(payload, final=not truncated)
            if extension == '.csv':
                _rows(csv.reader(io.StringIO(text)), result, limits, 'csv-labeled-cell')
            else:
                for index, line in enumerate(io.StringIO(text), 1):
                    if index > limits['max_lines']:
                        _issue(result, 'EXTRACTION_LIMIT', 'Text line limit reached.')
                        break
                    _literal(line.rstrip('\r\n'), {'method': 'text-labeled-line', 'line': index}, result['observations'])
            _rules(result, config, filename, relative_path, text[:limits['max_content_characters']])
        else:
            result['status'] = 'registered_metadata_extraction_pending'
            _issue(result, 'UNSUPPORTED_FORMAT', 'No local metadata parser for this file type.')
    except Exception as exc:
        result['status'] = 'error'
        # No partial parse masquerades as a successfully extracted source.
        result['observations'] = [o for o in result['observations'] if o['evidence_class'] == 'filename_derived']
        result['sheets'] = []
        _issue(result, 'PARSER_ERROR', type(exc).__name__ + ': ' + str(exc), severity='error')
    result.pop('_content', None)
    result.pop('_content_size', None)
    _complete(result['observations'], result)
    missing = [o['field'] for o in result['observations'] if o['evidence_class'] == 'missing']
    if missing:
        _issue(result, 'MISSING_METADATA', 'Metadata not observed: ' + ', '.join(missing), {'fields': missing})
    if result['status'] == 'registered' and result['issues']:
        result['status'] = 'registered_with_issues'
    return result
