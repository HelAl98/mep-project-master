# Configuration, applicability and source interpretation

Use JSON following `assets/project.example.json`. It is an adaptation example, not a naming standard or project authority. Lists replace defaults; dictionaries merge. Use the same configuration for indexing, mapping, comparison, decisions and export. Unknown top-level keys are refused.

## Multi-section applicability

`applicability_rules` has id, level, equipment selector, requirement selector and basis. Levels: project, discipline, system, equipment_category, equipment_type, equipment_instance. All produce candidates; even a project-wide rule does not automatically approve a clause. `basis` identifies the actual source/project scope authority, not invented contractual priority.

Equipment selectors support ids, categories, types (explicit names or existing confirmed type IDs), tags, disciplines, systems, buildings, floors, scopes, kinds, or deliberate `project: true`. Requirement selectors support sections (regex), topics, technical_categories, file_ids, disciplines, systems, scopes and text_terms. Fields are combined with AND; values within a field identify alternatives. A rule may have `exclude: true` or an `exclude_pattern`; it proposes exclusion requiring an actual not-applicable decision, without deleting the clause. Conflicting candidate inclusion/exclusion remains visible.

Literal-tag retrieval is only one path. Add the actual AHU/pump/electrical/BMS sections and topic rules for fans, filters, coils, construction, insulation, motors, VFDs, electrical installations, monitoring, testing, commissioning and documentation. FTS5 retrieves relevant text/context candidates; section selectors can retrieve indexed section metadata. Per-equipment limits are explicit and leave coverage incomplete when reached.

`section_mappings` provides section_pattern, basis, optional fields (discipline/system/scope/categories/equipment_types/equipment_tags), topics and technical_category. These populate visibly candidate context where no literal context exists; original text/locators remain unchanged. `equipment_aliases`, `discipline_aliases` and `system_aliases` normalize configured terms while retaining originals. They are not engineering approvals.

Generic classification topics cover Performance, Construction, Electrical, Controls and BMS, Testing, Installation and Documentation. Extra categories can be added in `topics`. Unclassified paragraphs stay indexed. Keyword lists are not a complete multilingual interpretation engine.

## Numeric and qualitative requirements

`parameter_patterns` optionally extracts explicit numeric candidates from literal source text. Each has id, parameter, operator and regex with named value/unit groups; ranges can include value_end. Patterns retain match text/span and remain unreviewed. Without a safe rule, the complete qualitative paragraph remains an unresolved requirement; nothing is summarized away.

`data.interpretations` in structured evidence can provide candidates directly. Existing SQL specification fragments are reused before parsing a source again. Manual/Codex interpretations are separately appended and explicitly approved/rejected; they never replace original text. No automatic AI call is made.

Use `parameter_aliases` for genuine equivalences, with canonical lower-case/underscore keys. Do not equate generic capacity with motor power, airflow with electrical demand or a pump-set quantity with individual units. `parameter_kinds` protects semantic quantities independently of physical dimension: cooling/heating/active power remain distinct even when all use W.

`units` entries require dimension, positive factor, canonical unit, allowed kinds and conversion basis; optional context must be explicitly supplied through source interpretation or `unit_contexts`. Built-in conversions cover m³/h/L/s/CFM, W/kW, refrigeration TR, VA/kVA, Pa/kPa/bar, qualified in.w.g., mm/m, V/A/Hz. TR uses the stated IT refrigeration definition and only cooling capacity. In.w.g. conversion remains unresolved without the configured conventional-4°C context. No power-factor, fluid-density or pump-head/pressure assumption is introduced. Unknown numeric units remain unresolved; text stays qualitative only for nonnumeric parameter meanings.

`tolerances` is empty by default: differences are flagged, not silently accepted. Each supplied parameter tolerance needs nonnegative absolute/relative values and an actual documented basis. The computation is `absolute + max(abs(a),abs(b)) * relative` in normalized units. Decimal conversion factors/precision are retained in comparison evidence; a near-equality can still be flagged without an authorized tolerance. Overlapping constraints mean only that no disjoint constraint was detected, not that equipment complies.

Different natural-language strings do not prove contradiction. Configure `text_aliases` for reviewed equivalences and `text_conflict_rules` with parameter/left_pattern/right_pattern/basis for explicit contradictions. Otherwise interpretation remains unresolved. No independent design calculations or regulatory compliance checking occurs.

## Quantities, precedence and coverage

Quantity comparisons are disabled unless a `quantity_rules` entry supplies actual scope, count_basis (`individual_equipment|pump_set|package`), duty_arrangement, authority basis, equivalent_units, optional roles and equipment selector. The scope/arrangement must match source evidence. Independent declared totals remain per source file; repeated drawing tags or views never become counts. Do not declare pump-set and individual-pump units equivalent without actual documented grouping.

`precedence_rules` identifies selected higher_file_id, lower_file_id and actual authority basis. It annotates evidence, never silently accepts a value or resolves a conflict. Approved revisions remain the registry's responsibility; no universal BOQ/drawing/specification hierarchy exists.

Eight coverage categories are mandatory. `coverage_rules` can map actual document metadata to them; unclassified documents remain an explicit completeness limitation. Availability is candidate availability and may include sources whose engineering relevance remains unresolved. A processed source is not automatically a complete specification. Actual engineer coverage approval needs a complete-document-scope declaration, reviewed scope and supporting references to every candidate source in the category. Unprocessed/unmatched/truncated evidence blocks it. A not-applicable disposition is separate and source-supported.

`status_labels` changes display labels only; it cannot redefine guarded machine approval semantics. `report.title` sets the workbook title. Input/ZIP/record/candidate/comparison/text-search limits are external settings. Exceeding a discovery/comparison limit is visible; original requirement text is not truncated. `equipment_config` can explicitly select the existing matcher's configuration; otherwise one consistent current import configuration is reused. Mixed upstream configurations remain an integration limitation requiring upstream reconciliation.
