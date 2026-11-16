---
name: pdf-to-structured
metadata:
  variant: project-mep-local
  source-repository: https://github.com/datadrivenconstruction/DDC_Skills_for_AI_Agents_in_Construction
  source-commit: 410ed1e71e4a5c6fd231afd0c8d1e586a9f546e8
description: Use when local construction PDFs need auditable text, table, word, and page evidence for later MEP review or parsing.
---

# PDF evidence extraction

Run `python scripts/extract_pdf.py --help`, then `python scripts/extract_pdf.py source.pdf --output evidence.json`. The importable entry point is `extract_pdf(path, metadata=None)` in [scripts/extract_pdf.py](scripts/extract_pdf.py).

Use a local Python environment with `pdfplumber>=0.11` and `pypdf>=6` available. If unavailable, report the missing dependency and obtain authorization before installing. This script makes no network calls.

Output is `mep-evidence/1`: `schema_version`, `document`, `records`, `issues`. The actual parsed bytes determine SHA256; PDF metadata and caller-supplied metadata remain separate. Only explicitly supplied document identifiers are accepted. `--metadata` reads an optional JSON object with `document_id`, `revision`, `discipline`, or `drawing_number`. User-observed printed labels can be supplied as `"printed_pages": {"1": "M-01", "2": "M-02"}`; keys are actual one-based PDF pages, and each applied label is marked `printed_page_method: user_supplied`. Such assertions are retained as supplied, not independently verified. Missing printed labels remain null; embedded PDF page labels never establish a printed page label.

Records use kinds `page`, `word`, `line`, `table`, `table_row`. Exact extracted strings remain `raw_text`; table rows serialize original cell arrays without converting units or quantities. `source.pdf_page` is one-based. `source.bbox` uses PDF points, x right and y down from the page top; table/cell boxes follow the same system. Table IDs are internal page-local references, and row numbers include the original first row. PDF page labels remain separate; unknown printed page numbers remain null.

Only explicit `--output` writes a file; existing files are refused. Otherwise JSON goes to stdout. Keep source files immutable and inspect evidence against original pages before relying on it.

Limitations: no OCR, symbol recognition, engineering quantities, or interpretation. Raster pages raise OCR-needed warnings; mixed image/text pages and Unicode/Arabic text require visual review. PDF text spacing and reading order reflect pdfplumber, not guaranteed visual paragraph order. Line-based table detection can miss borderless tables or merge cells. Encrypted files require an authorized decrypted copy. These warnings do not certify extraction completeness.
