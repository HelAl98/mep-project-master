# Additive storage and matching semantics

## Shared database

The matcher requires an existing schema-v2 engineering database containing registry migration 1 and the named project. It opens the sibling Registry and reuses its project, physical-file, archived byte-version, analysis, drawing-sheet and revision structures. No second database or duplicate project/document/version tables are created. Registry snapshots may append their existing revision derivations; the matcher does not rewrite source metadata. Core `PRAGMA user_version` remains 2; registry migration remains 1.

`scripts/migrations/001_equipment.sql` is applied transactionally at first runtime use. `eq_migrations` independently records equipment migration 1. Unknown versions fail rather than silently replacing schemas. The migration has not been executed during skill creation.

| Table | Responsibility |
|---|---|
| eq_migrations | Equipment-only migration ledger |
| eq_categories | Project-scoped canonical category keys; exact applied definitions also live in import manifests |
| eq_imports | File/version/analysis links, role, stable adapter slot, configuration/helper fingerprint, errors/warnings |
| eq_occurrences | Immutable raw equipment/specification appearances with original/normalized tags and source locators |
| eq_parameters | Original and normalized technical values, linked to their exact occurrence |
| eq_entities | Separate kinds: instance candidate, technical type, group/package |
| eq_entity_sources | Many-to-many entity-to-occurrence evidence |
| eq_runs, eq_results | Dataset fingerprint, matching configuration, transactional terminal counters |
| eq_matches | Instance/type/BOQ/reference proposals, supporting fields and conflicts |
| eq_relationships | Cross-discipline, panel/controller, electrical-supply and candidate specification associations |
| eq_issues | Evidence-linked potential discrepancies, missing evidence, unprocessed sources |
| eq_reviews | Append-only decisions, actor/reason, exact target and reviewed basis fingerprint |
| eq_fts | Rebuildable lexical search index, including reviewed aliases |

Foreign keys scope file/category/import/occurrence/entity/run relationships to the project. Generic review targets are validated for project/currentness in the application, since target IDs span several table types. Indexes cover tag, import, source slot, parameter and review lookups. Deterministic identities make repeated identical imports idempotent; source observations are not deduplicated by tag alone. Review IDs identify actual separate events.

Evidence/event tables reject UPDATE, DELETE and duplicate-primary-key replacement. FTS is a derived index. These are logical append-only protections, not administrator-proof WORM storage or authenticated engineering approval. Back up database and original evidence archive together.

## Current versus historical evidence

The latest import per file/slot is current only while its registry analysis is current/present. New source bytes, new registry analysis or replaced mapping preserve old occurrences but exclude them from current matching. An unchanged source/config/adapter signature reuses its import. All raw records, unit strings and original columns remain; a reviewed correction creates a projection, never a replacement.

`show --history` includes historical observations and invalidated matching results. Superseded document revisions are excluded from matching/count candidates. Unreviewed revisions are visibly unreviewed; document applicability is never approved by equipment matching. Instance approval alone does not certify a contractual quantity.

Match run identity includes current imports, configuration/implementation, registry metadata/revision dispositions and equipment corrections. A dataset change invalidates the prior run conservatively, including decisions on its exact candidates. Regenerate and review current IDs rather than inheriting historical approval. Entity confirmations are scoped to current observation fingerprints. Type/group proposals also record their source fingerprints and become invalidated when those source interpretations change.

## Deterministic proposal policy

Candidate discovery groups exact normalized tags and category/explicit scope, with separate bounded association passes. There is no global fuzzy all-pairs comparison and no capacity-based automatic instance merge. Exceeding a pair budget produces an explicit incomplete-discovery issue; it does not discard source observations.

- Probable: exact normalized tag, at least one consistent context/category field and no identified identity/parameter conflict.
- Possible: incomplete or conflicting evidence; conflicts are explicit and block identity confirmation until corrected.
- Confirmed/rejected: actual engineering decision against the current candidate.
- Unmatched: no current non-rejected match proposal; not proof of equipment absence.

Evidence strength is categorical, not an arbitrary probability. Numeric comparisons use documented unit dimensions and relative tolerance. Unsupported/incomparable units remain explicit. Cross-discipline appearances can refer to one item, without inferring loads, wiring or controls. A specification association is applicability for review, not technical compliance.

## Instances, types and counts

Each eligible source occurrence can have its own **candidate** entity. Identity matching does not turn repeated mentions into independently counted physical units. Confirmed same-instance/reference links create derived clusters. Only clusters containing an explicitly confirmed instance entity count as verified physical items; duplicates in a confirmed cluster count once. Cluster IDs derive from their current member IDs and can change when membership changes; immutable instance entities and observation IDs remain the stable audit targets.

Type proposals compare all supplied parameter signatures and configured mandatory material fields, including motor/duty differences. Missing material values, ambiguous parameters or missing units on dimensional numeric values block type confirmation. Configurations must identify all material distinctions relevant to the actual category. An identical subset of available columns cannot establish unobserved engineering equivalence. Group confirmation does not merge member instances.

Quantities preserve separate contexts:

- Verified identity clusters, with contributing source IDs.
- Drawing distinct-tag hypotheses, explicitly not physical counts.
- Each schedule/BOQ/source file's declared quantity and discrete unit.

No quantity is inferred from blank cells, number of views, CAD symbols or a generic BOQ package. Counts are not summed across different source documents. Comparison requires an explicit common scope and remains a potential discrepancy because scope completeness and source applicability need engineering review. `confirm_discrepancy` makes an actual reviewed issue confirmed; no conflict is automatically resolved. Category/location groups are non-additive perspectives and must not be summed together as a project total.

## Outputs

The authoritative store is SQLite. Exports use stored snapshots; Excel is a view, not the database. The master records retain candidate/verified status, independent quantity contexts and every parameter observation rather than selecting an unapproved canonical value. Approved parameter projections point to their original occurrence and review event. Source mapping retains drawing, schedule, BOQ, electrical and BMS references plus matching status. Complete JSON preserves long values and review history. Export markers exclude generated files from registry rescans.
