---
name: mep-cross-document-reviewer
description: Map MEP equipment to multi-section technical specifications, compare registered drawing/schedule/BOQ/electrical/BMS evidence, and maintain source-traceable engineering conflicts, coverage and approvals in the existing project SQLite database.
---

# MEP Cross-Document Reviewer

Use for document-based technical requirements mapping, cross-discipline comparisons, engineering conflict review and approved-requirements retrieval. Preserve original clauses and equipment observations separately from normalized or AI-assisted interpretations. This skill does not calculate designs, certify code compliance or generate RFQ packages.

## Prerequisites

Require the existing registered project/database with core schema 2, registry migration 1 and equipment migration 1. Do not discover/rebuild documents, recreate equipment, install dependencies or create another database. Resolve `scripts/reviewer.py` relative to this skill and use its absolute path with Codex Python from the workspace dependency loader (`-X utf8 -B` on Windows). Sibling registry, matcher, ETL, PDF and specification helpers remain unchanged dependencies. The matcher's interfaces are provisional and were inspected, not execution-validated.

Read [usage and decisions](references/usage.md) before operating. Read [configuration and evidence](references/configuration.md) when preparing project rules/interpretations and [storage semantics](references/schema.md) before treating approvals or coverage as current. Adapt `assets/project.example.json` to actual authority and source scope; its examples are not project facts.

## Workflow

1. Obtain current equipment IDs/tags and selected source revisions from upstream skills. Use registered sources and actually processed equipment evidence. Unknown identity or revision applicability remains a review issue.
2. `index` reuses selected structured/SQL extraction first, otherwise native PDF/DOCX/TXT/Markdown. Preserve full original paragraphs, exact fragments/page spans, printed labels, section/part/article/clause and actual locators. Missing references remain unknown or `source_reference_incomplete`; never invent pages or clause IDs. No OCR/native DWG parsing is added.
3. `map` uses literal tags and configurable section/topic/category/type/system/project rules to retrieve multiple potentially applicable clauses through FTS5 and indexed metadata. Include mechanical, electrical, BMS, installation/testing/documentation topics. Generic clauses and exclusions remain candidates until an actual engineer confirms/rejects applicability.
4. `compare` stores exact compared observations and logic. Compare only equivalent canonical parameters and semantic quantity kinds; preserve original units and explicit conversion/tolerance basis. Compare quantities only through explicit scope/count-basis/duty rules; never use drawing tag occurrences as quantities. Unknown units, conflicting text meaning or incomplete identity/applicability stay unresolved. No universal document hierarchy or newest-revision approval is assumed.
5. Inspect `record`, `category`, `conflicts`, `coverage`, `source` and `search`. Use `interpret` only for deliberately supplied manual/Codex reasoning, retaining original text. It invokes no model API and does not approve its own interpretation.
6. Record actual authorized `review` / `accept-value` decisions with reviewer, rationale and real supporting project references. Requirement text, applicability, interpretation, equipment identity, values and coverage are independent decisions. Reuse the shared audit log; corrections/approved interpretations never overwrite raw evidence. Reindex/remap/recompare after underlying evidence changes and review current targets.
7. Export stored Excel/JSON matrices and coverage. `export-approved` includes only eligible current approved requirements/values, lists withheld items and states whether equipment review is complete. It generates no equipment folders or RFQ documents. No detected conflict in reviewed evidence is not complete verification of all requirements.

Eight mandatory coverage categories distinguish available, processed, matched, reviewed, approved, unavailable and not applicable. Do not claim full review while relevant source scope, candidate mapping, qualitative clauses, revisions or comparisons remain unresolved. Unclassified documents and budgets remain visible limits.

## Implementation status

The user explicitly deferred tests and execution. No tests, demonstrations, database migrations or actual project processing were run while creating this skill. Do not claim it is tested. Use [deferred validation](references/first-project-validation.md) when practical validation is later authorized.
