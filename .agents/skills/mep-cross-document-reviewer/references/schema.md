# Storage, review authority and currentness

## Existing infrastructure

The existing database must have core schema 2, registry migration 1 and equipment migration 1 plus the selected project. The compatibility layer calls inspected Registry/Matcher APIs for current files, source hashes, equipment observations/parameters/types, matching statuses and revision dispositions. Upstream snapshots can append their existing registry revision derivations at runtime. This integration is provisional and was not execution-tested.

No project/document/equipment tables are duplicated. Review decisions reuse **eq_reviews**, with technical_requirement, technical_interpretation, technical_applicability, technical_case, technical_coverage and technical_value target kinds. Existing matcher identity decisions retain its `match` target semantics. `tr_decision_evidence` attaches supporting sources and previous status to the shared event; it is not another decision log. Generic technical targets receive explicit project/currentness validation in this skill because eq_reviews spans several target kinds.

## Additive technical migration 1

The migration is stored in `scripts/migrations/001_technical_review.sql`. It will apply transactionally only at later actual runtime use. Core/registry/equipment version ledgers remain unchanged; unsupported technical versions fail safely. No migration was run while creating the skill.

| Table | Purpose |
|---|---|
| tr_migrations | Independent technical schema ledger |
| tr_imports | Registered file/version/analysis, stable view slot, extraction fingerprint and partial/unprocessed coverage |
| tr_requirements | Exact original clause/paragraph fragments, source/context/classification and reference status |
| tr_interpretations | Separate normalized/qualitative candidates; automatic candidates have no fictional reviewer |
| tr_links | Entity-to-requirement applicability, scope level, rule/evidence and source foundation |
| tr_mapping_runs | Completed mapping counts, candidate limits and current foundation |
| tr_runs, tr_results | Comparison configuration/foundation, terminal summary and coverage snapshot |
| tr_comparisons | Exact left/right observations, conversions, constraints, precedence and comparison logic |
| tr_cases | Evidence-linked cases, guarded confirmation eligibility and stable conceptual case keys |
| tr_coverage_scopes | Equipment/category/source scope being reviewed; status is an event projection |
| tr_approved_values | Explicit accepted interpretations tied to entity, parameter/requirement, actual review and supporting evidence |
| tr_decision_evidence | Supporting references and prior status for shared review events |
| tr_fts | Rebuildable lexical clause/context index |

Foreign keys connect the existing project/entity/parameter/core-record tables and the new technical entities. Composite project keys prevent cross-project links. Indexes cover imports, entities, requirement links, comparisons and approvals. Evidence/event tables reject UPDATE/DELETE and primary-key replacement; transactions roll back incomplete imports/runs/decisions. Logical append-only guards do not authenticate reviewers or prevent administrator-level database replacement. Back up database and its adjacent evidence archive together.

## Evidence and interpretations

Requirements retain full original text, exact original fragment texts, registered file ID/version/hash/path/revision, physical PDF pages, separate printed page labels, actual text boxes or DOCX/table/line locators, section/title/part/article/clause when observed and extraction method. PDF continuation groups retain their actual page list and remain candidate continuations. Internal hashes/group IDs are not official clause IDs. Missing provenance is explicitly source_reference_incomplete. DOCX/TXT/Markdown receive no invented PDF pages.

Classification, mapped section context and normalized interpretations are distinct from original clauses. Structured supplied/regex/Codex candidates start unreviewed. An actual engineer can reject an interpretation and append its correction without modifying either original text or earlier interpretations. Source technical observations remain in the matcher; comparisons reference them rather than replacing them. Accepted values have their own evidence-backed projection and are not silently treated as conflict resolution.

## Currentness and approvals

The current requirement view uses latest imports per current file/analysis/slot. New bytes or relevant extraction/configuration/helper changes preserve older records but create new identities. Applicability foundation includes upstream source/identity/revision state and indexed requirement/interpretation identities. Comparison basis additionally includes applicability/interpretation/coverage review state. Source changes conservatively invalidate prior mappings, comparisons and accepted-value projections rather than inheriting approvals.

Review events retain actor/reason/timestamp/previous state/supporting refs. Exact current review targets are required. Conflict confirmation is blocked unless identity, revisions, requirement applicability and interpretations are established; potential findings never become confirmed automatically. Request-clarification, resolution, reopening and not-applicable remain explicit dispositions. A later case under the same conceptual case key shows prior case IDs while historical approvals remain invalidated.

No universal precedence exists. Configured authority is comparison evidence, not an approval. Equipment identity, source revision applicability, original-clause review, normalized interpretation, applicability, accepted value and coverage are separate decisions. Multiple incompatible current accepted interpretations remain visible and prevent a complete-review claim.

## Coverage and approved downstream data

Coverage distinguishes eight source categories and independent availability/processing/matching/review/approval/not-applicable flags. Candidate availability does not prove applicability or section completeness. Limits, unclassified documents, unprocessed/unmatched sources, unresolved clauses/identities and stale comparisons prevent full-review claims. The engine records no conflict-free-design or code-compliance verdict.

Approved-requirements export requires a current comparison, confirmed identity/applicability, approved original clause, selected applicable revision, available source references and reviewed interpretations. Withheld items retain reasons. It carries actual decisions and completeness indicators for later package generation; default partial export does not mean all equipment requirements are verified. `--require-complete` additionally rejects incomplete equipment coverage. No fourth skill, RFQ documents or equipment package folders are generated.
