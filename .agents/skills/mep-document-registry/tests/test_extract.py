"""Synthetic metadata evidence fixtures; no real project sources are used."""
import io
from pathlib import Path
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'scripts'))
try:
    from mep_registry.extract import extract_document
except ImportError:
    extract_document = None

SKILLS = HERE.parents[3] / '.agents' / 'skills'


class ExtractionTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(extract_document, 'Metadata extraction API must exist')
        self.tmp = tempfile.TemporaryDirectory(dir=HERE, prefix='synthetic-extract-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def run_extract(self, payload, name, config=None, **kwargs):
        path = self.root / 'immutable-archive-byte-version'
        path.write_bytes(payload)
        result = extract_document(path, config, skills_root=SKILLS, original_name=name, **kwargs)
        self.assertEqual(path.read_bytes(), payload)
        self.assertTrue(all(o['review_status'] == 'unreviewed' for o in result['observations']))
        return result

    def values(self, result, field, evidence=None):
        return [o['value'] for o in result['observations'] if o['field'] == field and
                (evidence is None or o['evidence_class'] == evidence)]

    def pdf(self, pages):
        from reportlab.pdfgen.canvas import Canvas
        buf = io.BytesIO()
        canvas = Canvas(buf)
        for lines in pages:
            for i, line in enumerate(lines):
                canvas.drawString(45, 760 - i * 22, line)
            canvas.showPage()
        canvas.save()
        return buf.getvalue()

    def test_literal_text_conflicts_are_retained_and_missing_is_null(self):
        result = self.run_extract(b'TITLE: Plant room\nREVISION: A\nREVISION: B\nDISCIPLINE: BMS\n', 'facts.txt')
        self.assertEqual(self.values(result, 'revision', 'content_extracted'), ['A', 'B'])
        self.assertEqual(self.values(result, 'title', 'content_extracted'), ['Plant room'])
        self.assertEqual(self.values(result, 'floor', 'missing'), [None])
        self.assertIn('CONFLICTING_METADATA', [i['code'] for i in result['issues']])
        title = next(o for o in result['observations'] if o['field'] == 'title' and o['evidence_class'] == 'content_extracted')
        self.assertEqual(title['source']['line'], 1)

    def test_archive_filename_uses_original_extension_and_path_rules_are_unverified(self):
        config = {'classification_rules': [{'id': 'power', 'pattern': r'Electrical[/\\]Power',
                  'target': 'relative_path', 'fields': {'discipline': 'Electrical Power'}}]}
        result = self.run_extract(b'TITLE: One\n', 'EL-01_Rev-C.txt', config,
                                  relative_path='Electrical\\Power\\EL-01_Rev-C.txt')
        self.assertEqual(set(self.values(result, 'discipline', 'filename_derived')), {'Electrical Power'})
        self.assertIn('C', self.values(result, 'revision', 'filename_derived'))
        self.assertFalse(self.values(result, 'discipline', 'content_extracted'))

    def test_content_rule_is_inferred_even_if_pattern_matches(self):
        cfg = {'classification_rules': [{'id': 'spec', 'target': 'content', 'pattern': 'technical requirements',
                 'fields': {'document_type': 'Specification'}}]}
        result = self.run_extract(b'Technical requirements for power\n', 'notes.md', cfg)
        self.assertEqual(self.values(result, 'document_type', 'inferred'), ['Specification'])
        self.assertFalse(self.values(result, 'document_type', 'content_extracted'))

    def test_named_group_rule_and_filename_date_keep_basis(self):
        cfg = {'classification_rules': [{'id': 'number', 'target': 'filename',
              'pattern': r'(?P<number>M-\d+)', 'captures': {'document_number': 'number'}}]}
        result = self.run_extract(b'', 'M-012_2026-10-07.txt', cfg)
        self.assertEqual(self.values(result, 'document_number', 'filename_derived'), ['M-012'])
        self.assertEqual(self.values(result, 'revision_date', 'filename_derived'), ['2026-10-07'])
        obs = next(o for o in result['observations'] if o['field'] == 'document_number' and o['value'])
        self.assertEqual(obs['source']['rule_id'], 'number')

    def test_pdf_multi_sheet_revisions_and_boxes_are_individual(self):
        payload = self.pdf([['DRAWING NO: M-01', 'DRAWING TITLE: Ventilation', 'REVISION: A', 'DISCIPLINE: HVAC'],
                            ['SHEET NUMBER: E-02', 'TITLE: Power', 'REVISION: C', 'DISCIPLINE: Electrical Power']])
        result = self.run_extract(payload, 'package.pdf')
        self.assertEqual(result['metadata']['page_count'], 2)
        self.assertEqual([s['pdf_page'] for s in result['sheets']], [1, 2])
        revisions = [[o['value'] for o in s['observations'] if o['field'] == 'revision' and o['value']] for s in result['sheets']]
        self.assertEqual(revisions, [['A'], ['C']])
        for sheet in result['sheets']:
            obs = next(o for o in sheet['observations'] if o['field'] == 'revision')
            self.assertEqual(obs['source']['pdf_page'], sheet['pdf_page'])
            self.assertEqual(len(obs['source']['bbox']), 4)
        self.assertFalse(any(o.get('field') == 'equipment' for o in result['observations']))

    def test_spec_pdf_not_automatically_drawing_and_streaming_limit(self):
        result = self.run_extract(self.pdf([['DOCUMENT TYPE: Specification', 'TITLE: HVAC requirements'], ['General requirements']]),
                                  'spec.pdf', {'extraction_limits': {'small_pdf_max_bytes': 1, 'max_pdf_pages': 1}})
        self.assertEqual(result['sheets'], [])
        self.assertEqual(result['metadata']['parser'], 'pdfplumber-stream')
        self.assertEqual(result['metadata']['page_count'], 2)
        self.assertIn('EXTRACTION_LIMIT', [i['code'] for i in result['issues']])

    def test_blank_pdf_requires_review_without_invented_content(self):
        result = self.run_extract(self.pdf([[]]), 'scan.pdf')
        self.assertTrue(any(i['code'] in ('NO_EXTRACTABLE_TEXT', 'OCR_NEEDED') for i in result['issues']))
        self.assertFalse(any(o['evidence_class'] == 'content_extracted' for o in result['observations']))

    def test_docx_paragraph_and_table_cell_sources(self):
        from docx import Document
        buf = io.BytesIO()
        document = Document()
        document.add_paragraph('TITLE: Pump specification')
        table = document.add_table(rows=1, cols=2)
        table.cell(0, 0).text = 'DISCIPLINE'
        table.cell(0, 1).text = 'Plumbing'
        document.save(buf)
        result = self.run_extract(buf.getvalue(), 'document.docx')
        title = next(o for o in result['observations'] if o['field'] == 'title' and o['value'] == 'Pump specification')
        discipline = next(o for o in result['observations'] if o['field'] == 'discipline' and o['value'])
        self.assertEqual(title['source']['paragraph'], 1)
        self.assertEqual(discipline['source']['table'], 1)
        self.assertEqual(discipline['source']['row'], 1)
        self.assertEqual(discipline['source']['cell'], 2)

    def test_xlsx_separate_label_cells_and_formulas_not_executed(self):
        from openpyxl import Workbook
        book = Workbook()
        sheet = book.active
        sheet.title = 'Cover'
        sheet.append(['Drawing No', 'M-12'])
        sheet.append(['Revision', 'B'])
        sheet.append(['Title', '=1+1'])
        buf = io.BytesIO()
        book.save(buf)
        result = self.run_extract(buf.getvalue(), 'schedule.xlsx')
        self.assertEqual(self.values(result, 'document_number', 'content_extracted'), ['M-12'])
        number = next(o for o in result['observations'] if o['field'] == 'document_number' and o['value'])
        self.assertEqual(number['source']['sheet'], 'Cover')
        self.assertEqual(number['source']['cell'], 'B1')
        self.assertNotIn(2, self.values(result, 'title'))
        self.assertIn('FORMULA_NOT_EVALUATED', [i['code'] for i in result['issues']])

    def test_xlsx_and_text_limits_report_incomplete_evidence(self):
        from openpyxl import Workbook
        book = Workbook()
        book.active.append(['TITLE', 'First'])
        book.active.append(['REVISION', 'Unseen'])
        buf = io.BytesIO()
        book.save(buf)
        result = self.run_extract(buf.getvalue(), 'facts.xlsx', {'extraction_limits': {'max_rows_per_sheet': 1}})
        self.assertFalse(self.values(result, 'revision', 'content_extracted'))
        self.assertIn('EXTRACTION_LIMIT', [i['code'] for i in result['issues']])

    def test_csv_literal_pairs_have_row_column_source(self):
        result = self.run_extract(b'TITLE,Lighting layouts\nDISCIPLINE,Lighting\nREVISION,A\n', 'facts.csv')
        obs = next(o for o in result['observations'] if o['field'] == 'title' and o['value'] == 'Lighting layouts')
        self.assertEqual(obs['source']['row'], 1)
        self.assertEqual(obs['source']['column'], 2)

    def test_canonical_aliases_preserve_raw_literals(self):
        for literal, expected in [('HVAC', 'HVAC'), ('Public Health', 'Plumbing'), ('Firefighting', 'Fire Fighting'),
                                  ('Electrical Power', 'Electrical Power'), ('Lighting', 'Lighting'),
                                  ('FireAlarm', 'Fire Alarm'), ('Building Management System', 'BMS'),
                                  ('ELV', 'Low Current')]:
            with self.subTest(literal=literal):
                result = self.run_extract(('DISCIPLINE: ' + literal).encode(), 'facts.txt')
                obs = next(o for o in result['observations'] if o['field'] == 'discipline' and o['value'])
                self.assertEqual(obs['value'], expected)
                self.assertEqual(obs['raw_value'], literal)

    def test_dwg_is_pending_never_claimed_converted(self):
        result = self.run_extract(b'AC1032real-content-not-converted', 'M-01.dwg')
        self.assertEqual(result['status'], 'registered_metadata_extraction_pending')
        self.assertIn('DWG_EXTRACTION_PENDING', [i['code'] for i in result['issues']])
        self.assertFalse(any(o['evidence_class'] == 'content_extracted' for o in result['observations']))

    def test_optional_dxf_is_explicitly_pending_when_dependency_missing(self):
        result = self.run_extract(b'0\nSECTION\n2\nHEADER\n0\nENDSEC\n0\nEOF\n', 'floor.dxf')
        self.assertEqual(result['status'], 'registered_metadata_extraction_pending')
        self.assertIn('DXF_PARSER_UNAVAILABLE', [i['code'] for i in result['issues']])

    def test_corrupt_supported_format_is_error_and_no_fake_metadata(self):
        for name in ('bad.pdf', 'bad.docx', 'bad.xlsx'):
            with self.subTest(name=name):
                result = self.run_extract(b'not a valid source', name)
                self.assertEqual(result['status'], 'error')
                self.assertIn('PARSER_ERROR', [i['code'] for i in result['issues']])
                self.assertFalse(any(o['evidence_class'] == 'content_extracted' for o in result['observations']))

    def test_invalid_rule_fails_clearly(self):
        result = self.run_extract(b'TITLE: Useful\n', 'facts.txt', {'classification_rules': [{'pattern': '[', 'target': 'filename', 'fields': {'discipline': 'BMS'}}]})
        self.assertIn('INVALID_CLASSIFICATION_RULE', [i['code'] for i in result['issues']])
        self.assertEqual(self.values(result, 'title', 'content_extracted'), ['Useful'])

    def test_office_unlabeled_content_rule_retains_inferred_basis(self):
        from docx import Document
        from openpyxl import Workbook
        document = Document()
        document.add_paragraph('Technical requirements')
        word_buffer = io.BytesIO()
        document.save(word_buffer)
        book = Workbook()
        book.active['A1'] = 'Technical requirements'
        excel_buffer = io.BytesIO()
        book.save(excel_buffer)
        cfg = {'classification_rules': [{'id': 'technical', 'target': 'content',
               'pattern': 'Technical requirements', 'fields': {'document_type': 'Specification'}}]}
        for name, payload in [('facts.docx', word_buffer.getvalue()), ('facts.xlsx', excel_buffer.getvalue())]:
            with self.subTest(name=name):
                result = self.run_extract(payload, name, cfg)
                self.assertEqual(self.values(result, 'document_type', 'inferred'), ['Specification'])
                self.assertFalse(self.values(result, 'document_type', 'content_extracted'))

    def test_text_unicode_limit_keeps_complete_decoded_prefix(self):
        result = self.run_extract('TITLE: A\n\u00e9'.encode('utf-8'), 'facts.txt',
                                  {'extraction_limits': {'max_text_bytes': 10}})
        self.assertNotEqual(result['status'], 'error')
        self.assertEqual(self.values(result, 'title', 'content_extracted'), ['A'])
        self.assertIn('EXTRACTION_LIMIT', [i['code'] for i in result['issues']])

    def test_global_file_size_limit_yields_explicit_pending(self):
        result = self.run_extract(b'TITLE: Too long', 'facts.txt',
                                  {'extraction_limits': {'max_file_bytes': 1}})
        self.assertEqual(result['status'], 'registered_metadata_extraction_pending')
        self.assertIn('EXTRACTION_LIMIT', [i['code'] for i in result['issues']])
        self.assertFalse(self.values(result, 'title', 'content_extracted'))

    def test_other_mep_is_only_explicit_and_configured_drawings_create_sheets(self):
        result = self.run_extract(b'DISCIPLINE: OtherMEP', 'facts.txt')
        self.assertEqual(self.values(result, 'discipline', 'content_extracted'), ['Other MEP'])
        cfg = {'classification_rules': [{'id': 'drawings', 'target': 'relative_path',
               'pattern': 'IFC', 'fields': {'document_type': 'Drawing'}}]}
        result = self.run_extract(self.pdf([['TITLE: Plan']]), 'plan.pdf', cfg, relative_path='IFC/plan.pdf')
        self.assertEqual(len(result['sheets']), 1)
        self.assertFalse(self.values(result, 'discipline', 'content_extracted'))


if __name__ == '__main__':
    unittest.main()
