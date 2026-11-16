---
name: dwg-to-excel
description: Use when inspecting DwgExporter availability or extracting MEP blocks, tags, attributes, layers and drawing coordinates from an explicitly mapped AutoCAD DWG XLSX export.
metadata:
  variant: project-mep-local
  source-repository: https://github.com/datadrivenconstruction/DDC_Skills_for_AI_Agents_in_Construction
  source-commit: 410ed1e71e4a5c6fd231afd0c8d1e586a9f546e8
---
# MEP DWG export adapter

Use `scripts/extract_dwg.py` with the Codex Python runtime and openpyxl. Resolve script paths relative to this SKILL.md. This local adapter reads an existing real XLSX export, not DWG binary geometry. No API keys are required. Consult `--help` and [mapping examples](references/mapping.md).

## Check converter status

`probe [--exporter <explicit-path>]` locates the executable and reports its hash without running it. `verify --exporter <path> --sha256 <expected-hash>` checks identity only. Neither proves conversion functionality. Direct conversion stays blocked until an inspected exporter and a real DWG fixture/output have passed a functional verification. No converter is bundled, downloaded or installed. Never report a DWG conversion as successful from a file-presence check, a workbook fixture, or an exit code alone.

## Ingest a supplied export

`ingest <actual-export.xlsx> --mapping <mapping.json> [--metadata <metadata.json>] [--output <new.json>]` returns a `mep-evidence/1` package. Mapping names the actual sheet, header row, and exact headers for tag/entity type/block/layer/handle/attributes/coordinates/units/drawing identifiers. Raw cells, source sheet/row and export SHA256 are retained. Formula values remain unresolved. There is no default tag, coordinate zero, physical quantity or drawing number.

Only INSERT records become equipment candidates; other entity rows remain CAD evidence. Attributes are taken from explicit same-row columns or an object on that row. Do not associate adjacent ATTRIB rows with INSERT entities by order or presumed handle proximity. Drawing coordinates require their real coordinate system/units, and do not establish physical floor or room locations.

Optional `original_dwg` metadata requires an existing original file and its supplied matching SHA256. This verifies its bytes independently; it does not prove the workbook was generated from that DWG. Without verified linkage, cite the parsed XLSX as the actual source. Preserve original DWG and export separately.

Use sibling `etl-pipeline` to validate/archive the package and `data-quality-check` for review findings. This is a tested export adapter; CAD symbol recognition, direct conversion, XREF/attribute relationship resolution, and verified spatial equipment counts remain additional work. Output files refuse overwrite.
