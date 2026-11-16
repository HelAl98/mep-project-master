# Deferred first-project validation

This guide is for a later authorized session. **None of these actions was executed during creation.** No test suite, synthetic demo, actual intake, migration, performance benchmark, CLI smoke run or workbook render was performed. Frontmatter/source inspection and packaging inventory are not behavioral tests.

## Recommended first use

1. Back up the existing registered engineering database and adjacent evidence archive. Use a small representative, non-sensitive subset whose document revisions and expected tags have been manually checked.
2. Confirm the intended existing database/project/file IDs and Python dependency versions. Apply the additive migration in the backed-up working copy first. Inspect SQLite integrity/foreign keys and confirm core version 2 / registry migration 1 remain unchanged.
3. Adapt tag/category aliases, actual worksheet headers, comparison scope, quantity units and mandatory material type fields. Check one HVAC schedule, electrical/BMS reference, BOQ package and a known drawing using original evidence. Do not use example constants as facts.
4. Inspect imported observations against exact PDF pages/boxes, XLSX cells, CAD handles/attributes and archived source hashes. Check that unavailable DWG/OCR/DXF paths are visibly pending rather than invented.
5. Repeat an unchanged import and confirm no duplicate occurrences. Change one working source through the registry workflow and confirm history retention/currentness invalidation. Include multi-view repeated tags and tags reused in different buildings/floors.
6. Examine known same-instance, different-instance, type and package cases; conflicting parameters; unknown units; explicit electrical/control references; and one specification candidate. Confirm that no proposal is auto-approved and no generic paragraph becomes an approved requirement.
7. Record actual review decisions, then check corrections, rejection, type-material completeness, value approval and decision history. Change evidence and check invalidation. Reviewer identity is an audit label, not authentication.
8. Compare verified unique-instance counts, distinct tag hypotheses and each source's declared quantities independently. Validate scope completeness/revision applicability before interpreting a quantity discrepancy.
9. Open Excel and inspect formatting, formula-like source text and long-value JSON companions. Re-export to a new directory. Confirm generated outputs are excluded by subsequent registry scans.
10. Only after correctness is established, increase document volume and measure runtime/memory on the real workload. Keep extraction limits explicit; no large-project performance figures are established yet.

## Untested assumptions and limits

- Existing sibling helper interfaces/schema still match the inspected versions. Their earlier tests do not validate this new integration.
- Windows path, optional DXF, corruption/interrupt recovery, migration atomicity, caching, matching invalidation, FTS, review projections and Excel output have not been exercised here.
- The runtime previously supplied pypdf/pdfplumber/openpyxl and FTS5. No dependencies were installed or freshly imported to test the matcher. ezdxf, native DWG extraction and OCR remain unavailable.
- Native PDF line/table reading order and English label/category patterns need review, especially for scans, merged/borderless tables, Arabic/Unicode and unusual title blocks. No graphic/room recognition exists.
- External structured evidence can preserve a hash and syntactically valid locators without proving its interpretation. Verify extraction meaning against original sources.
- Scope/role/type material rules are project assertions. Completeness, actual physical uniqueness and contractual applicability require qualified review.
- Pair budgets, input/row bounds and local transactions are implemented safeguards, not demonstrated capacity or performance guarantees. No automated test suite was authored or run for this delivery.
- No specification compliance checking, engineering design verification, material takeoff, RFQ package folders, pricing analysis, supplier contact or procurement execution is included.
