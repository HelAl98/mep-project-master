# Native equipment evidence contract — B-01

`mep-equipment-profile/1` is the native identity projection plus the paginated evidence sections in the existing `mep-evidence-reader/1` equipment profile envelope. The outer native envelope declares `equipment_profile_contract`; identity rows declare `schema_version`. See `native-equipment-contract.schema.json`. This is a query-only adapter, not a database, extractor, matching engine or approval route.

## Route selection and identity

When the supported UC profile/view contract exists, existing Reader methods and P3 compilations keep their previous behavior and output shape. A stale/empty supported UC view is NOT replaced silently by native or historical records. When UC is absent, native `eq_occurrences`/`eq_imports` and registered source heads produce source-reference profiles.

One profile is one native occurrence ID, never an inferred physical instance or a merge of repeated tags. The profile ID is the real `eq_occurrences.id`, so existing Reader queries, P4 exact evidence inspection and parameter relationships use actual database identities. Original and native normalized tags remain distinct. Type and Group stay separate from Reference. Native instance claims remain Reference here: this projection does not implement physical-instance approval revalidation. Physical quantity is always null. Unknown family/tag is retained and blocks a consumer requiring a usable grouping; it is not invented.

| Profile/evidence field | Native basis |
|---|---|
| id / native_target | eq_occurrences.id / table eq_occurrences |
| native_observation_ids | Exact source occurrence ID; no synthetic grouping ID |
| original_tag / normalized_tag | Original columns from the native importer |
| family | Project eq_categories.name, otherwise recorded data_json.category |
| identity_kind | Native type→Type, group→Group, others→Reference; no approval inference |
| is_active | Existing Reader latest-import file/slot and registry analysis/version projection |
| provenance | Original registered file/version/hash, source_json locators, native record identity |
| parameters section | eq_parameters joined to the selected native occurrence; original value/unit/source_cells retained |
| drawings section | Existing Reader selected source observations and CAD/PDF/schedule locators |
| context section | Same source observation or endpoints of an explicitly stored eq_relationships row |
| specifications section | Explicitly selected core specification IDs or recorded tr_links through eq_entity_sources |
| review/currency | Existing source/review projections and optional P4 history; no original value overwritten |
| quantity/coverage | null physical count, source-reference semantics and explicit coverage limitations |

Current and historical native imports remain separate via the existing Reader `include_history` option. Pagination retains totals/next_offset. Native enumeration has a visible 10000-observation bound, not silent truncation. Family/role are the importer's recorded classifications, not new semantic matching.

## Specifications

Python: `reader.get_specifications(reference, evidence_ids=[core_record_id], section=...)`, or `reader.get_equipment_profile(reference, specification_evidence_ids=[core_record_id])` for an enriched profile. Explicit selections are bounded to 300 unique exact IDs, require an available native equipment reference and native `records.kind == specification`, and preserve core source locators. They must resolve to this project's registered original source and current original head unless history is explicitly requested. Saved core activation is checked when present. Missing/foreign IDs fail visibly. Section filters do not invent section values.

For P3, existing `specification_rules[].evidence_ids` now feed this native selection, with the already required section, discipline and selection basis. `title_evidence_id` may be included explicitly. UC keeps its old candidate-query and filtering behavior unchanged.

For operation D, the optional top-level `specification_evidence_ids` declares exact clauses. Operation E uses the existing P3 options. Supporting-source closure participates in the existing operation authorization: an explicitly selected clause cannot widen an `explicit` closed source scope. User-selected clauses are `explicit_user_selected_clause / Pending`, not approved applicability. If no IDs and no native recorded requirement links exist, zero clauses are selected and the gap is reported. No global keyword or family search assigns unlinked fragments.

Native `tr_links` are traversed only through stored `eq_entity_sources` membership and a `tr_requirements.core_record_id`. Without a traceable core clause locator they are not projected. They are labeled `native_recorded_equipment_requirement_link`, retain link IDs/entity/basis, and expose `native_link_currency: UNKNOWN_NOT_REVALIDATED`. They remain Pending even if a historical native review exists; the adapter does not execute the technical review engine's approval/readiness validation. P4 assertions remain separately inspectable. This conservative path was inspected statically; the positive acceptance uses explicit native core IDs, not a fabricated tr schema/link.

Direct native core extraction resolves original identity from supplied file_id metadata or an unambiguous exact registered source path AND SHA256. Derived documents continue to require their explicit original-source lineage; filename similarity does not establish it.

## BOQ and interdisciplinary context

Only exact selected observations and explicitly recorded native relationship endpoints supply context. Candidate matching pairs do not become approved identity or context links. Equal tags alone do not join two observations. Original quantity fields remain declarations, never physical counts. Absent BOQ/BMS/electrical links return no selected records with a coverage limitation, not invented counterparts. Physical source coordinates do not infer installation location. General family candidates supported by UC remain UC behavior; this adapter does not create new family-wide applicability.

## APIs and consumers

- Existing `list_equipment`, `get_equipment_profile`, `get_observations`, `get_parameters`, `get_context`, `get_specifications` remain the entry points; no second generator or SQLite store.
- Native list identities now satisfy id/family/normalized_tag/identity_kind/provenance expected by C and P3. `get_equipment_profile` sections expose the full values/units/source/limitations under the existing Reader envelope.
- C reuses source-reference profiles. D adds optional selected clauses and original recorded context. E compiles/renders through the existing SupplierDraftGenerator and its XLSX/PDF defaults.
- P5 native adapter implementation bytes are included in operation fingerprints. Existing I-01 native cache replay and I-02 extraction-warning policies are unchanged.
- The existing CLI `evidence list/profile` now exposes native profiles without a new command. Explicit native clause selection is supported by the Python API, D request and P3 options; no new CLI evidence-id flag was introduced.

## Verified scope

B01_Contract_Remediation contains a genuine no-UC acceptance: registered CSV + PDF, native matcher import-schedule, PDF/specification extraction and ETL ingestion, Reader → C → D → P3 → E → actual XLSX/PDF. No mocks or UC rows. Source value `1,250` and unit `L/s` remain original, repeated tag/type remain separate, physical quantity stays unknown, selected clause Pending, unlinked clause excluded. Native tables and formal stage history stay unchanged during C/D/E; only operation audit is appended. Registry/ETL/schema initialization is explicit native setup, not automatic five-operation orchestration.

Prior scoped compilation checks do not establish complete workflow compatibility. Installation updates and broader execution validation remain separate tasks.
