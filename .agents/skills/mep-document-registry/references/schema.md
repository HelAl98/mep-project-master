# Storage and evidence semantics

## Existing infrastructure

The registry imports the sibling engineering `etl-pipeline` Store at runtime, reuses the same SQLite file and the existing `versions` table/content-addressed `<database-stem>.evidence/` archive layout. `PRAGMA user_version` stays 2. Existing engineering records, extraction runs, review events, activations and FTS content are neither rewritten nor populated with synthetic registry engineering data.

A registry file version is a hash of exact archived bytes, scoped by stable project/file identity. Its core `versions.document_id` and `versions.revision` remain null: an official document number is an observation, and a PDF container can contain multiple sheet revisions. Registration therefore never mistakes an internal byte-version ID for an engineering revision.

## Additive migration

Registry migration version 1 is recorded independently in `registry_migrations`; it does not change core migration numbering. Unknown registry/core schema versions fail safely. New registry tables are:

| Table | Purpose |
|---|---|
| registry_projects | Explicit project identity and canonical source root |
| registry_entities | Project-scoped file/sheet/discipline/scope endpoints |
| registry_files | Stable relative path identity; no source reorganization |
| registry_scans, registry_scan_results | Config and terminal scan counters/status, including interruptions |
| registry_scan_files | Append-only observations of each path's current byte version or absence |
| registry_analyses | Extraction/config/capability fingerprints, status and parser metadata |
| registry_document_sheets | Actual one-based PDF pages as distinct drawing sheets |
| registry_observations | Literal/derived/inferred/missing values and source evidence |
| registry_issues | Missing/conflicting/unsupported/error and relationship review issues |
| registry_revisions | Independent file/sheet revision candidates derived from observations |
| registry_relationships | Proposed representation/revision/discipline/scope/duplicate relationships |
| registry_reviews | Append-only actor/decision/reason/target/correction history |
| registry_fts | Rebuildable SQLite FTS5 index of metadata and reviewed corrections |

Foreign keys constrain project and target relationships. Indexes support current-file lookup, analysis/field lookup, drawing numbers and reviews. Writes use bounded per-file transactions and a SQLite busy timeout. Failed parses do not discard the registered bytes or prevent other readable files from registering. Interrupted traversals retain completed transactions and never establish missing paths from an incomplete directory walk.

Repeated scans add scan audit events, not duplicate files/sheets/observations/revisions. File changes get new version/analysis IDs; prior evidence remains. Config or parser/helper-version changes can trigger a new analysis even for identical bytes. Revisions are not inferred from filesystem modification times. Current snapshots exclude old/excluded/missing file metadata; `show --history` keeps original observations and decisions available.

Evidence and event tables reject UPDATE, DELETE and duplicate-key replacement. This is logical immutability/tamper detection, not operating-system WORM storage or protection against an administrator altering the database. Archived bytes are hash checked on registration/reuse. Back up the database and adjacent evidence directory together. No automatic archive garbage collection is performed.

## Metadata and confidence

Observations carry field/value, evidence class, confidence, source and an immutable identity. Source includes the actual relative path/file version through linked records, and, when observed, PDF page/bbox, sheet number, Office sheet/row/column or DOCX paragraph/table/cell. No page/position is invented for filename metadata. PDF positions use page points measured from the top-left. Unknown printed/sheet metadata does not inherit a page index.

- `content_extracted`: a literal labeled value observed in file contents. It is evidence of that text, not proof the source or engineering meaning is correct.
- `filename_derived`: project naming/path rules or conservative filename candidates.
- `inferred`: classification rules applied to content without an explicit literal label.
- `missing`: no observed value, retained as null.

Confidence high/medium/low/unknown is categorical extraction evidence quality, not a measured probability. Every extraction begins unreviewed. Highest-evidence-class conflicting values remain null with candidate observations intact. Human corrections are separately attributable projections; original observations/source bytes never change.

Relationships retain type, endpoint identities, exact supporting evidence, confidence and verification status. File hashes, extraction-analysis IDs and identity/review fingerprints make old confirmations invalid after relevant source/identity changes. Filename similarity only proposes a match; it never merges files, proves a CAD export relationship or confirms applicability. Raw DWG registration continues when no parser exists.

Review decisions and document issue purpose/date are independent. File identity confirmation does not approve technical content. Revision applicability approval covers its named source/sheet candidate only. Supersession is an explicit decision with a reason, not a consequence of alphabetical sorting or filesystem recency. Correcting a value changes its current projection, preserves its raw observation, and can invalidate affected relationships. Full review history remains available, including decisions on historical evidence.

## Supported subset and limits

Native text PDFs, labeled Office/text metadata and explicitly configured naming conventions are supported. The small-PDF path reuses existing PDF and drawing metadata helpers on line/page records only; no equipment word matching runs. A registry adapter keeps sheet numbers distinct from the older helper's ambiguous drawing-number alias. Larger PDFs use page-wise local parsing. PDF/Office content and relationship budgets are explicit and visible when reached.

No OCR, arbitrary title-block visual understanding, native DWG conversion, equipment extraction, technical matching, takeoff, design verification or procurement is implemented. Optional DXF support requires an actual ezdxf installation; it does not imply DWG reading. Corresponding XLSX/DXF files are independently registered; their metadata is not silently promoted to original-DWG evidence. Real project formats and classification accuracy require representative file testing.
