# Operations and explicit engineering decisions

Status: implementation authored and installed; **execution testing is deferred**. No command below was executed during creation. No project database was opened/migrated and no source was processed.

## Runtime and sequence

Use Python 3.10+, existing FTS5 SQLite, pypdf/pdfplumber for native PDF and python-docx for DOCX, plus openpyxl for Excel export. No dependencies were reinstalled. The existing registry and matcher skills must be siblings. Native DWG/OCR remain unavailable. No web server, cloud/paid service or automatic LLM API is used.

Set actual paths from the project directory. Global flags precede the command:

```powershell
$reviewerPython = 'python'
$reviewerScript = '.agents/skills/mep-cross-document-reviewer/scripts/reviewer.py'
$reviewerDb = 'D:/MEP Project/State/engineering.sqlite'
$reviewerProject = 'actual-registered-project-id'
$reviewerConfig = 'D:/MEP Project/Rules/technical-review.json'
& $reviewerPython -X utf8 -B $reviewerScript --db $reviewerDb --project-id $reviewerProject --config $reviewerConfig index --file-id '<registered-specification-id>'
& $reviewerPython -X utf8 -B $reviewerScript --db $reviewerDb --project-id $reviewerProject --config $reviewerConfig map
& $reviewerPython -X utf8 -B $reviewerScript --db $reviewerDb --project-id $reviewerProject --config $reviewerConfig compare
```

In Codex substitute Python's actual dependency-loader path. The first later command installs technical migration 1 additively; even a query may initialize these tables. Core 2, registry 1 and equipment 1 must already exist; unknown/missing projects or incompatible schemas are refused. Back up the database and adjacent evidence archive together before first real execution.

Register/rescan source versions and resolve document applicability with the registry. Import/match/confirm physical equipment with the matcher. This skill does not rebuild either workflow.

`index` without a file ID selects registered documents classified as specifications. `--mode auto` prefers a single existing SQL extraction run; ambiguous runs require `--run-id`. `--mode sql`, `--mode native` and `--mode json --input <evidence.json>` explicitly select intake. A supplied JSON/run needs the original registered file ID. A stable `--slot` identifies one extraction view; latest imports replace current projections while retaining old evidence.

Structured evidence must describe the original source's exact SHA-256, not the transport JSON hash. Supported envelopes are `mep-evidence/1` and `mep-requirements/1` with records/issues arrays. Records retain `kind`, `raw_text`, `source`, `data`; requirement/specification/paragraph records are accepted, or PDF line evidence is passed to the existing specification extractor. Exact references and fragment arrays are preserved. `data.interpretations` can supply explicit parameter/operator/value/unit candidates; supplied approval labels are ignored.

Unchanged source/config/helper signatures reuse the import. Failed/empty extraction is stored as unprocessed evidence, never as a clean specification. After source/config/interpretation changes reindex as appropriate, rerun mapping/comparison and review current IDs. No regex or alias convention is assumed universal.

## Find equipment and original clauses

```powershell
& $reviewerPython -X utf8 -B $reviewerScript --db $reviewerDb --project-id $reviewerProject --config $reviewerConfig record --tag 'CHWP-003'
& $reviewerPython -X utf8 -B $reviewerScript --db $reviewerDb --project-id $reviewerProject --config $reviewerConfig category --category 'AHU'
& $reviewerPython -X utf8 -B $reviewerScript --db $reviewerDb --project-id $reviewerProject --config $reviewerConfig search --query 'mechanical seal'
& $reviewerPython -X utf8 -B $reviewerScript --db $reviewerDb --project-id $reviewerProject --config $reviewerConfig source --requirement-id '<requirement-id>'
& $reviewerPython -X utf8 -B $reviewerScript --db $reviewerDb --project-id $reviewerProject --config $reviewerConfig conflicts --entity-id '<equipment-id>'
& $reviewerPython -X utf8 -B $reviewerScript --db $reviewerDb --project-id $reviewerProject --config $reviewerConfig coverage --tag 'CHWP-003'
```

Tag queries return all current matching equipment scopes; reused tags in different locations are not merged. `--entity-id` disambiguates. Records include original clauses/observations, candidate/confirmed applicability, exact comparison evidence, conflicts, coverage and approved interpretations. `--history` includes prior invalidated comparison records for current selected equipment; it is not a selector for deleted/historical equipment entities. `source`/search default to current indexed requirements, including not-yet-mapped clauses. FTS5 is literal lexical retrieval, not semantic completeness certification.

## Review

Use actual target IDs from current records and actual authorized reviewer/rationale. Supporting references must be current registered project sources. `--refs-json` is a nonempty list of `{requirement_id}`, `{occurrence_id}` or `{file_id, analysis_id?, pdf_page?, clause?, note?}` objects. Register an RFI/clarification before citing it as approval authority; free fictional document IDs are refused. Unknown PDF page values are never invented.

```powershell
& $reviewerPython -X utf8 -B $reviewerScript --db $reviewerDb --project-id $reviewerProject --config $reviewerConfig review --target-kind applicability --target-id '<link-id>' --decision confirm_applicability --actor '<actual engineer>' --reason '<actual applicability basis>' --refs-json '[{"requirement_id":"<actual-requirement-id>"}]'
& $reviewerPython -X utf8 -B $reviewerScript --db $reviewerDb --project-id $reviewerProject --config $reviewerConfig review --target-kind requirement --target-id '<requirement-id>' --decision approve_requirement --actor '<actual engineer>' --reason '<verified original clause and scope>' --refs-json '[{"requirement_id":"<actual-requirement-id>"}]'
```

| Target | Decisions |
|---|---|
| requirement | approve_requirement, reject_requirement, request_clarification |
| interpretation | approve_interpretation, reject_interpretation, request_clarification |
| applicability | confirm_applicability, reject_applicability, request_clarification |
| case | confirm_conflict, resolve, reopen, not_applicable, request_clarification |
| coverage | reviewed, approve_coverage, not_applicable, reopen |
| value | withdraw_value |
| equipment_match | confirm, reject using existing matcher semantics |

Each event preserves supporting refs and previous status in the shared `eq_reviews` audit history plus a linked source-evidence record. Actor names are supplied audit labels, not authentication. Incomplete identity/applicability/interpretation blocks conflict confirmation. An actual resolution requires a rationale and registered supporting evidence; no precedence rule or newer filename silently closes a case.

Coverage approval also requires `--value-json` with `complete_document_scope: true` and nonempty `reviewed_scope`, plus refs covering all candidate files in that category. Unprocessed, unmatched or truncated sources block approval. Manual scope attestation is not generated by the parser. Not-applicable is a separate actual decision.

## Interpretations and accepted technical values

`interpret --requirement-id <id> --payload-json <JSON> --actor ... --reason ... --refs-json ...` appends a candidate, never edits original text. Payload fields: parameter, operator (`eq|min|max|range|contains`), value, unit when dimensional, optional value_end/unit_context and either a matching original literal/span or explicit evidence basis. `--method codex_assisted` records deliberately supplied Codex reasoning; it makes no API call and does not self-approve. Reject an earlier wrong interpretation and propose its correction, retaining both.

`accept-value --entity-id <id> --payload-json <JSON> ...` stores an engineer-approved interpretation linked to a current source `parameter_id` or confirmed applicable `requirement_id` plus approved `interpretation_id`. Supply parameter/value/unit explicitly. Identity and source applicability must be confirmed. Original source values survive. Multiple conflicting accepted values remain visible and block a complete-review claim; withdraw an obsolete interpretation explicitly.

## Exports

```powershell
& $reviewerPython -X utf8 -B $reviewerScript --db $reviewerDb --project-id $reviewerProject --config $reviewerConfig export --tag 'CHWP-003' --output 'D:/MEP Project/Reports/technical-review-01'
& $reviewerPython -X utf8 -B $reviewerScript --db $reviewerDb --project-id $reviewerProject --config $reviewerConfig export-approved --entity-id '<equipment-id>' --output 'D:/MEP Project/Reports/approved-requirements-01'
```

Full export contains `technical_review_matrices.xlsx`, `technical_records.json`, `engineering_conflict_register.json` and `technical_review_coverage.json`. Workbook sheets: RequirementsMatrix, Comparisons, ConflictRegister, ReviewCoverage, ApprovedValues, ReviewHistory, DecisionSources. Every original text/reference remains in JSON even beyond Excel's cell display limit. Strings are literal, never formulas.

Approved export produces `approved_requirements.json`: eligible current clauses/values, actual decisions/supporting references, withheld reasons and completeness indicators. `--require-complete` refuses a partial equipment review. Default partial approved export does not claim all specifications are covered. No RFQ documents or per-equipment folders are created.

Exports read SQLite projections, refuse existing directories and write a registry-compatible exclusion marker before other outputs. Missing/stale comparison results are labeled. Exit codes: 0 command completed, 1 indexing had per-file errors, 2 validation/runtime error, 130 interruption. Completed imports remain; incomplete transactions roll back. No output claims engineering code compliance or a conflict-free design.
