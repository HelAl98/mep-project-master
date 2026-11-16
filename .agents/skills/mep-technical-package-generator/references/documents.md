# Document content and configuration

Use `assets/project.example.json` after adapting actual category codes/column names. No example is applied automatically to project data. List settings replace defaults and dictionary settings merge. No configuration supplies artificial equipment values or turns a pending source into approved evidence.

## Package configuration

- output_root: dedicated generated-output directory. It is never the original project root/ancestor or database directory itself.
- category_aliases/category_titles/discipline_aliases: output grouping/display conventions; actual original categories/IDs remain in data receipts. There is no hardcoded finite equipment catalogue. Existing categories and type entities support future kinds without material takeoff.
- group_by: category and verified type are mandatory; discipline/system/building/floor/scope can further partition. type_requirements and mandatory_parameters name additional existing reviewed fields needed by category. They never create equivalence from raw capacities.
- category_columns: category-specific technical fields. Omitted configuration uses actual observed parameters ordered by parameter_order; unrelated equipment fields are not filled with invented values. Configured but unavailable fields remain empty evidence lists.
- count_units: discrete-unit spellings for explicit count contexts. Sets/packages are not implicitly individual items. Final scope/count-basis approval still applies.
- specification_sections/section_routes: document organization labels. Original paragraphs are unchanged. Global/discipline-wide confirmed scope routes to General Requirements; electrical/BMS/documentation and mechanical topics route separately. Other documented clauses are retained, not dropped.
- file_names: safe unique basenames with required XLSX/DOCX extensions. No path templates or executable expressions are accepted. Deterministic category/version path naming prevents overwrite and Windows collisions.
- language/font/font_size/accent_color/page_size/rtl: English labels initially; source text retains its original language. A formatting/direction boundary supports future translated/RTL labels, but Arabic report generation/visual fidelity is not certified. page_size accepts A4/Letter.
- rfq_template: optional JSON template following `assets/templates/rfq.json`. It cannot remove the draft notice or any required commercial response field. The template supplies labels, never prices or supplier facts.
- source_links: safe relative hyperlinks to actual registered PDF/CAD/Office/text paths when drives permit. References retain path/hash even where a relative link is impractical. No original document is copied or embedded wholesale.
- readiness_requirements and mandatory_coverage: mandatory safeguards cannot be disabled. require_formal_release_decision can add an existing explicit authority requirement; the generator never writes an approval itself.

## Excel

Reusable openpyxl utilities follow the existing construction-document conventions: project/package/version/status metadata, consistent colored headers, original units, wrapped cells, filters, frozen panes, repeated print headers, landscape fit-to-width and page-number footers. Long workbooks are split across sheets. Literal strings preserve formula-like source values without evaluation. Long/control-character values have a display representation and full JSON companion; they are not silently discarded.

Equipment_Register contains physical IDs/tags/type/system/location, approved and original parameter observations with source/review IDs, verified-instance quantity, independent schedule/BOQ totals, selected final quantity and reconciliation status. Rows are type/scope review groups, not repeated drawing mentions.

Requirements_Matrix retains full original requirement text and source document/revision/pages/section/part/article/clause, applicable equipment/type scope, classifications, applicability/review status and exclusions. Review_Status keeps independent group readiness, current/historical engineering cases and coverage. Source_References retains actual source locators and links.

## Word

Technical_Specifications includes actual equipment scope and complete original applicable paragraphs, not AI-written summaries or common-practice defaults. Each exported clause retains its requirement ID, applicability scope/review and original source references, including multi-page fragments. Numbering is an export navigation aid, not a fabricated original clause number. Repeated requirements are referenced once per shared scope/status with explicit equipment applicability. Exclusions appear separately as outside supply scope.

RFQ_Draft includes actual project/category/package/version, explicitly blank RFQ reference/issue date placeholders, reviewed equipment scope/quantities/parameters and documented technical/submittal requirements. No accessories, installation, testing, certificates or warranties are invented because they are customary. Mandatory clauses remain exact in the supplier compliance matrix, including equipment-specific scope. Compliance/offered specification/deviation/datasheet cells and commercial unit price/total/currency/delivery/validity/warranty/payment/tax/exclusion response fields remain blank.

All RFQs are drafts and always display `INTERNAL DRAFT — NOT APPROVED FOR ISSUE`. Draft specifications also display that label. Headers, source references, repeated table headings, proportional widths, page-number fields and a landscape compliance section support engineering readability. No Word render was performed; actual layout must be inspected later. XML-forbidden source characters cause a visible Word-generation error instead of silent alteration of binding wording; original JSON remains retained.

No generic pricing/cost/proposal examples from the original DDC references are executed. No source formulas/macros are run. No original PDF split/bookmark helper is used.
