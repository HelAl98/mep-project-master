---
name: specification-extractor
metadata:
  variant: project-mep-local
  source-repository: https://github.com/datadrivenconstruction/DDC_Skills_for_AI_Agents_in_Construction
  source-commit: 410ed1e71e4a5c6fd231afd0c8d1e586a9f546e8
description: Use when local PDF specification evidence needs exact paragraph fragments with section, clause, page and cross-discipline context for review.
---

# Specification paragraph evidence

Run `python scripts/extract_specifications.py --help`, then `python scripts/extract_specifications.py evidence.json --output specifications.json`. The importable entry point is `extract_specifications(package)` in [scripts/extract_specifications.py](scripts/extract_specifications.py). Python 3.10+ standard library suffices; obtain PDF evidence separately through `pdf-to-structured`. No network, external inference, or automatic dependency installation is used.

Input must be `mep-evidence/1` for an actual PDF with `line` records. Output has the same four top-level fields and retains a detached copy of the document identity, SHA256 and upstream issues. All output records have kind `specification`, remain unreviewed, and retain source extraction method, input line indexes, one-based `pdf_page`, observed bbox and separate PDF/printed page labels. No filename-derived project identifiers are accepted.

Common explicitly numbered section headings (`SECTION 23 09 23`), part headings, decimal articles (`1.02`) and uppercase letter items (`A.`) provide candidate context. A paragraph's `raw_text` joins the exact extracted lines with newline characters. `data.line_fragments` preserves every original line and locator. Unknown section/clause context stays null. No submittal copies, timing, manufacturer, product, quantity or engineering requirement is invented.

Paragraphs break at explicit headings/items, blank lines and large vertical gaps. A paragraph at the bottom 15% of one PDF page followed by unnumbered text in the top 15% of the next page can share an internal `clause_group`; this is marked `continuation_candidate`. Each output record remains a single actual page fragment and `data.fragments` links the exact text and locators of related fragments. Generated group IDs are internal evidence links, never official clause or document numbers. Verify every proposed continuation against the original PDF.

Literal mentions of HVAC, electrical, fire alarm, plumbing, fire protection, fire fighting, BMS and low current appear in `discipline_mentions` without restricting source scope or inferring a single discipline. The source paragraph remains authoritative; this short English keyword list is not a multilingual classification engine.

Only explicit `--output` creates a JSON file; an existing output is refused. Otherwise JSON goes to stdout. Keep original sources immutable and review paragraphs against actual pages before using them in engineering decisions.

Limitations: native text only, no OCR or graphics analysis. Section/item formats outside the documented subset remain raw text. Headers, footers, columns, tables, nested numeric/lowercase items and repeated page titles are not semantically resolved. Paragraph grouping and page continuations are layout heuristics and can be wrong. Arabic/RTL and font-decoding warnings are preserved from upstream. This adapter preserves inspectable evidence; it does not certify specification completeness or compliance.
