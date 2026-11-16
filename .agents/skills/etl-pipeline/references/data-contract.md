# Evidence contract and database semantics

Packages are UTF-8 JSON with `schema_version: mep-evidence/1`, `document`, `records`, and `issues`. Document identity is actual source path, filename, SHA256, nullable document ID/revision/drawing number/discipline, media type and metadata. Generated version/record IDs are internal keys, not official project identifiers.

Records have `kind`, `raw_text`, `source`, `data`, and `review`. Extra source/data fields are retained. Source includes extraction method and applicable exact PDF page, separately evidenced printed page, bounding box, table/row, workbook/sheet/row/columns, drawing number, specification section/clause, or CAD handle/layer/coordinates. PDF pages and spreadsheet rows are one-based. Unknowns are null. CAD coordinates are not physical room names. Extracted text/cells remain unchanged. Extraction status is unreviewed or needs_review.

Example mapped worksheet configuration (replace all values with actual project conventions):

```json
{
  "sheet": "Equipment",
  "header_row": 1,
  "columns": {"tag": "Tag", "quantity": "Quantity", "floor": "Floor", "room": "Room"},
  "discipline": "HVAC",
  "role": "schedule",
  "scope": "Building A Level 01",
  "parameters": [
    {"name": "electrical_power", "value_column": "Power", "unit_column": "Power Unit"}
  ]
}
```

Map actual headers. Parameter `value_type` defaults to `number`; use `text` for a textual parameter. Raw cells and parameter-to-column mappings are retained. `fixed_unit` can replace `unit_column` only when a header or supplied convention justifies it; record that basis in metadata. Scope must be the actual comparison boundary. Role differentiates schedule, BOQ, drawing and specification evidence. Do not compare whole-building BOQ totals to one-floor drawing mentions. Optional document metadata is supplied separately, e.g. `{"document_id":"SCH-M-001","revision":"C","discipline":"HVAC"}`; populate it from evidence only.

## Storage

- `versions`: logical identity, content hash, revision, source path, archive pointer and original metadata.
- `records`: deterministic per-version observation ID and immutable complete payload.
- `runs` and `run_records`: extraction package hash, issues, full per-run document metadata and observation membership.
- `reviews`: actor, time, decision, reason and optional field/value interpretation; never overwrites evidence.
- `activations`: selected working revision, separate from technical acceptance.
- `evidence_fts`: rebuildable lexical index, not embeddings.

SQL evidence/event tables reject UPDATE, DELETE and duplicate-key replacement. An administrator can still replace the database or archived files. `inspect` checks archived SHA256 and reports failure; it cannot restore deleted evidence. Back up the SQLite file and adjacent `<database-stem>.evidence/` directory together. The local schema is version 2; migration of other schemas is intentionally refused rather than replacing tables.

Exact repeats reuse version/run/record IDs. Changed extraction output may append distinct observations to the same source version; older observations are retained. New revisions remain inactive until reviewed; no ordering is assumed. Same revision plus changed bytes produces `REVISION_HASH_CONFLICT`. Without a document ID, a source rename is not automatically linked to the previous document.

FTS accepts literal phrases. There is no semantic retrieval, Arabic linguistic normalization, automatic equipment entity resolution, or verified search ranking. A review log records supplied identities without authenticating them. Review decisions are not engineering approvals unless an actual authorized reviewer supplied them.
