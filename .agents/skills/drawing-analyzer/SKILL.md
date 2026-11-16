---
name: drawing-analyzer
metadata:
  variant: project-mep-local
  source-repository: https://github.com/datadrivenconstruction/DDC_Skills_for_AI_Agents_in_Construction
  source-commit: 410ed1e71e4a5c6fd231afd0c8d1e586a9f546e8
description: Use when native PDF drawing evidence needs candidate MEP equipment tag occurrences or explicitly labeled drawing metadata for engineering review.
---

# Drawing text candidates

Run `python scripts/analyze_drawing.py --help`, then `python scripts/analyze_drawing.py evidence.json --output candidates.json`. The importable function is `analyze_drawing(package)` in [scripts/analyze_drawing.py](scripts/analyze_drawing.py). Python 3.10+ standard library suffices; PDF extraction is a separate upstream step using `pdf-to-structured` or equivalent `mep-evidence/1` records. No external services or installs are invoked.

Consume PDF `word` and `line` records with actual source boxes and one-based pages. Results retain the original document identity and SHA256. Each equipment candidate retains original word text, match span, input record index, page, and word bbox. A word bbox identifies extracted text, not an equipment symbol or physical position. A missing bbox remains null and is flagged.

The bundled pattern recognizes common MEP prefixes such as AHU, FCU, EF, P, DB, MDB and FACP followed by a hyphen/underscore and digits. Inspect the pattern in the script when project naming differs. Candidates are occurrences only: repeated mentions never establish physical quantity, and `quantity` stays null.

Explicit `DRAWING NO:`, `SHEET NUMBER:`, `REVISION:`, `DISCIPLINE:`, `ROOM:` and `FLOOR:` labels become separate metadata evidence. Page drawing numbers remain page-specific. Conflicting values leave document-level fields null. Room/floor association to equipment is accepted only from a single-tag line followed immediately by explicit inline labels; this association is recorded for review. Unrelated labels, filenames, and nearby annotations do not establish an equipment location.

Only `--output` creates a new file and overwrite is refused; otherwise JSON goes to stdout. Review candidates against the original PDF before passing reviewed facts downstream.

Limitations: text matching does not recognize graphical symbols, physical quantities, scales, dimensions, spatial rooms, DWG objects, or scanned image text. Unsupported or split tag formats may be missed. Unicode/Arabic and OCR warnings from PDF extraction remain in output; the script performs no OCR. Inline labels and title metadata can themselves be wrong in the source and remain unreviewed. This is an evidence adapter, not an engineering approval or takeoff tool.
