# Mechanical procurement inside the existing Master

## User entry and ownership

User prompt: **$mep-project-master Review this project and prepare mechanical procurement.**

Use a supplied folder or the actual project workspace; preserve a narrower system/category scope. Main runs all commands below and prepares mappings itself. Continue until an actual engineering/procurement choice or all available independent work is done. Return a concise English summary with files, not routine CLI details.

Internally: **master.py procurement run --root SOURCE**. Resume with the existing **--config CONFIG before procurement run**. A new default project has a sibling folder named <source-name>-mep, containing rules/master.json, state/engineering.sqlite, its archive and outputs/. Reuse an existing compatible config/DB; ambiguous DB ownership must be resolved rather than creating a competing database. Existing unrelated projects are never reopened as examples.

There is no second DAG/stage scheduler or raw evidence store. The façade uses Registry, native PDF/drawing/spec adapters, existing matcher normalization and ETL Store.ingest. Raw facts remain queryable in core records/runs/versions. Append-only master_procurement_sources/items/links hold source checkpoints and item/reference indexes. Existing master_operator_events stores decisions, mappings and issue confirmations. Legacy stages/UC/eq/tr history is not rewritten or declared complete.

## Available evidence, reuse and mapping

Native PDF text/tables use pdf-to-structured, tags use drawing-analyzer, and specification fragments use specification-extractor. Original warnings remain; procurement storage never asserts strict legacy stage completion. CSV/XLSX literal headers, including common Arabic names and units, are recognized deterministically. Materials do not require a Tag column. Original cells/values/units and unresolved formulas are preserved. Formulas never establish quantities.

Native DOCX paragraphs/tables and UTF-8 TXT/MD are stored with real paragraph/table locators. They show **Page unavailable** until a real traceable pagination/conversion exists. Binary DWG, legacy DOC/XLS, scans and bad mappings remain explicit gaps. Main may use an actual supported native export/conversion when supplied, preserving original/derived identities; never simulate successful conversion.

Reuse requires actual SQLite IDs and archive integrity. Source/mapping/helper changes reprocess that source, and affected decisions require revalidation. Keep historic facts and choices. The three gap labels are:

- Not provided in the available files.
- File present but unreadable or unsupported.
- Field not found in the sources reviewed.

Explain affected information and continue independent work. No findings or an absent counterpart never means conflict-free design.

Main stores mappings with **procurement configure --request MAIN_OPTIONS.json**. Options include scope, mappings, specification_rules, specification_limit, quantity_checks and quantity_tolerances. See [BOQ-first checks and issue](boq-drawing-checks.md) for the executable contracts. `procurement run --request OPTIONS` accepts these on first use. A mapping is mappings[registered relative path][worksheet], with header_row, columns (original header to canonical field), units, optional context/constants and quantity_basis. Inspect stored headers/source meaning before writing it. Users do not need to build these files.

## Items and review

Tagged references use native tag normalization and explicit compatible service context. References, types, groups and physical units remain distinct. Materials use actual defining attributes; absent/differing attributes stay separate. Decimal/fraction punctuation and subtype/extra characteristics prevent accidental merging. Similar incomplete material references are candidates, never automatic merges.

Written quantities retain source/unit/count basis. Do not sum/apportion them implicitly. Calculated graphical takeoff stays UNKNOWN unless a reliable source/method supplies a traceable basis. The bounded calibrated ASCII DXF LINE route now measures horizontal and explicitly verified riser portions against an existing BOQ row; see [the measurement contract](boq-drawing-checks.md). Native DWG, symbol counting, curved/nested geometry, support-spacing and insulation calculations remain unsupported.

**procurement status** reads the stored view. Main associates an exact record with **procurement link --item ID --record RECORD --field FIELD --relation candidate|supported|direct|conditional --basis BASIS**. Omit field for a clause/context link. Literal category/tag retrieval creates candidates only; review actual applicability/conditions and do not dump whole specifications.

For a paragraph fact Main can call **procurement interpret --request MAIN_REQUEST.json** with item_id, record_id, exact excerpt, basis and fields mapping each name to value/unit/context. Values/units must literally occur in the excerpt. The unreviewed interpretation is ingested through existing ETL and points to its original record. It cannot approve itself or invent a semantic deduction.

MCC/electrical/BMS rows describe mechanical items, not new electrical procurement scopes. Exact tag/service can support structured links; missing context stays candidate. Reuse existing matcher parameter/unit normalization. Compare only the same item, field and operating basis; quantity disagreements additionally need an explicit compatible count basis. Show A/B values, units, exact citations and the concrete question. Missing fields and uncertain associations are distinct from comparable disagreements.

## Plain-language decisions and issue

Main translates the user's actual sentence into exact item/field/evidence IDs. “Use the BOQ quantity for this valve, but use the specification for its body material” becomes two independent calls, both retaining the actual original statement:

    master.py --config CONFIG procurement decide --item ITEM --field quantity --source-link BOQ_LINK --statement ACTUAL_WORDS --actor "user (chat)"
    master.py --config CONFIG procurement decide --item ITEM --field body_material --source-link SPEC_LINK --statement ACTUAL_WORDS --actor "user (chat)"

Omit source-link only for the user's explicit unresolved choice. It displays PENDING, survives resume and blocks issue for that item. Header units such as Quantity (m) are retained when no separate unit cell is supplied. Ask only when item/basis ambiguity changes an engineering choice. Preserve alternatives/history; changed supporting evidence makes a choice Requires Revalidation. Attributions are not authenticated identity. These events are not upstream approvals and do not bypass or forge the legacy P1-04 terminal contract.

Render once through the existing supplier boundary's render_procurement_items extension. Do not force material items into the original equipment package contract. Each category receives Technical Schedule.xlsx (Items, optional BOQ drawing checks, Properties, Outstanding) and Technical Specifications.docx. Preserve all available properties/units, selected values and important pending fields. Word retains exact original clause wording and filename/page basis/section/clause/heading where known, and explicitly marks missing citation details. Separate directly selected clauses from conditional/uncertain ones; render shared clauses once per category. Detailed evidence/decisions/receipts remain under internal/.

After actual user confirmation of exact current item IDs and their reviewed fingerprint:

    master.py --config CONFIG procurement issue --item ITEM_A --item ITEM_B --fingerprint EXACT_REVIEWED_FINGERPRINT --statement ACTUAL_CONFIRMATION --actor "user (chat)"

Validate originals/archives and the included scope's blockers before recording release and rendering. Unresolved fields, stale decisions, uncertain applicability and omitted matches prevent FOR ISSUE. The actual user may explicitly exclude affected item IDs with --exclude-item; retain their drafts/history and issue only the remaining confirmed scope. No email/upload/Drive/n8n/supplier action is available or authorized. Main must render/visually inspect actual project documents before claiming supplier-ready layout; deterministic receipts do not claim visual QA.

## All 16 existing responsibilities

| Skill | Actual responsibility; select only when useful |
|---|---|
| mep-project-master | Existing CLI, lock, sequence, item/source links, decisions and English delivery |
| mep-document-registry | Native discovery/scan/rescan, file/revision metadata and DB ownership |
| data-profiler | Main's source/header/type/null/unit profiling and mapping guidance; no importable Markdown class |
| pdf-to-structured | Native PDF words/lines/tables/pages and locators |
| dwg-to-excel | Real mapped CAD XLSX intake/lineage when supplied; no binary DWG conversion claim |
| drawing-analyzer | Literal drawing-tag candidates, never physical counts |
| specification-extractor | Exact PDF specification fragments with original warnings and locators |
| etl-pipeline | Validation/archive/Store.ingest and queryable raw or bounded interpretation evidence |
| data-lineage-tracker | Core trace/archive/review semantics; Main uses native inspect when needed |
| mep-equipment-matcher | Existing tag/unit/parameter normalization; native equipment intake/matching where compatible |
| mep-cross-document-reviewer | Equivalent-basis/applicability/coverage rules and compatible native reviewer; item links extend materials |
| data-quality-check | Native comparable-package QC when relevant; item projection adds field-level gaps/comparisons |
| mep-technical-package-generator | Existing reviewed equipment dossiers/readiness only where requested/compatible; never duplicate item output |
| xlsx-construction | Schedule/quantity/source presentation guidance; examples are not takeoff engines |
| docx-construction | Word organization and exact technical wording/citation/layout guidance |
| pdf-construction | Optional safe PDF handling/QA; no defective split/bookmark examples |

## Specialists and validation

Main may delegate only bounded ambiguity after deterministic work, with the minimum stored evidence. Keep all six preferred configurations, read-only children, at most two at once, no nested delegation, and Main as sole writer. Record actual model/role evidence or Main fallback in the audit. Main Sol/medium is a preference, not an asserted host override. critical_reviewer needs the user's explicit request. Do not launch validation agents merely to install this change.

Main persists that receipt with procurement reasoning --request RECEIPT. Include role, task_id, basis, exact evidence_ids, the actual returned runtime_evidence and actual_model only where verified. Otherwise record fallback_reason and leave actual_model unknown. Critical review additionally requires explicit_user_request. This command records a host action; Python never invokes a model. Computed review findings are also saved as source-linked procurement_findings_v1 audit events, not only transient console text.

The new scripts/tests/test_procurement_items.py uses only generic isolated CSV/DOCX/PDF and an explicitly unreadable DWG placeholder. It checks native Registry/ETL, real SQLite records, identity separation, reuse, field decisions/revalidation, source links, scoped issue and actual XLSX/DOCX content. It is not a real-project run, old test suite, global deployment, graphical takeoff qualification or native Office visual review.


The new focused `scripts/tests/test_procurement_flow.py` exercises the actual CLI and sample outputs. Earlier tests that permitted unresolved items in issue now expect the issue gate to reject them. Scope-specific issue confirmation is still separate from upstream engineering certification.
