# P1-02 — Unified read-only EvidenceReader

Development addition; not globally synchronized. Read existing evidence only. No extractors, matcher runs, migrations, reviews, workflow events or approval inference. The existing 11-stage workflow is unchanged.

## Python API

Resolve Python with the workspace dependency loader. Add this master's `scripts` folder to `sys.path` (absolute path on Windows):

```python
from master_project.source_currency import load_config
from master_project.evidence_reader import EvidenceReader

config = load_config("/absolute/project/rules/master.json")
with EvidenceReader(config, currency_snapshot="/absolute/explicit-assessment.json") as reader:
    profile = reader.get_equipment_profile("AHU-01-01", limit=25)
    parameters = reader.get_parameters("AHU-01-01", limit=50, offset=0)
    clauses = reader.get_specifications("AHU-01-01", section="23000", limit=10)
    reader.write_json("/absolute/new-output.json", profile)  # only explicit export writes
```

Omit `currency_snapshot` to perform no source-currency enrichment. It never triggers the Phase 01 hash assessment. One reader reuses the supplied snapshot/index and one read transaction across calls; close it, preferably with `with`, to obtain a newer database snapshot. Use the existing project's own configuration, not another project's DB.

Methods:

| Method | Return / scope |
|---|---|
| `get_equipment_profile(reference, include_history=False, limit=25, offset=0)` | Versioned envelope with separately paged sections |
| `list_equipment(family=None, include_history=False, limit=25, offset=0)` | Envelope; current UC profiles, or native source references when UC unsupported |
| `get_observations(reference, ...)` | Page of original source observations |
| `get_parameters(reference, ...)` | Page combining native `eq_parameters` and additional saved `uc_fields`; original printed values/units retained |
| `get_schedule_fields(reference, ...)` | Only additional saved UC schedule fields |
| `get_specifications(reference, section=None, applicability=None, ...)` | Page of existing family/system specification links, exact text and original/derived identity |
| `get_drawing_references(reference, ...)` | Page of native drawing/schedule/electrical/BMS occurrences; additional linked context via `get_context` |
| `get_context(reference, role=None, ...)` | Page of UC context, role filter `boq/electrical/bms/drawing/schedule` |
| `get_findings(reference, ...)` | Page of saved UC consistency/missing-information findings and original citation sides |
| `get_relationships(reference, ...)` | Page of existing matching candidates; active endpoints by default, never a count |
| `get_provenance(evidence_id, table=None)` | Envelope; supported evidence tables enumerated below |
| `list_source_limitations(limit=25, offset=0)` | Envelope; recorded accepted limitation audits and UC limitations |
| `write_json(path, response)` | Explicit exclusive-create export, outside source/state/archive/master |

All collection methods accept `limit=1..200` and nonnegative `offset`. Methods with `...` accept `include_history=False, limit=25, offset=0`. Domain methods return a page, while profile/list/provenance/limitations return an envelope. The CLI wraps domain pages in the same envelope. No method silently follows all specification candidates or matching pairs.

References may be exact stored tags (case insensitive), native occurrence IDs, current UC profile IDs or equipment entity IDs linked through saved memberships. No fuzzy identity or tag alias is invented. A profile may contain more than one identity candidate; inspect all identity pages. Family search is exact case-insensitive stored UC family/category matching, not inferred synonyms.

## CLI

```text
python -X utf8 -B /absolute/master/scripts/master.py --config /absolute/master.json evidence profile --reference AHU-01-01
python -X utf8 -B /absolute/master/scripts/master.py --config /absolute/master.json evidence list --family AHU --limit 25
python -X utf8 -B /absolute/master/scripts/master.py --config /absolute/master.json evidence parameters --reference AHU-01-01 --history
python -X utf8 -B /absolute/master/scripts/master.py --config /absolute/master.json evidence specifications --reference AHU-01-01 --section 23000 --limit 10 --offset 10
python -X utf8 -B /absolute/master/scripts/master.py --config /absolute/master.json evidence context --reference AHU-01-01 --role bms
python -X utf8 -B /absolute/master/scripts/master.py --config /absolute/master.json evidence provenance --reference RECORD_ID --table records
python -X utf8 -B /absolute/master/scripts/master.py --config /absolute/master.json evidence limitations
```

`evidence` actions: `profile/list/observations/parameters/schedule-fields/specifications/drawings/context/findings/relationships/provenance/limitations`. `--reference` is required except list/limitations. `--currency-snapshot /absolute/phase01.json` explicitly enriches from saved assessment. `--output /absolute/new.json` explicitly exports; otherwise JSON is stdout only. Existing outputs are never overwritten. Parent folders are created only for explicitly requested output. Use absolute Windows paths and the bundled interpreter; examples are argument shapes, not new hardcoded project locations.

## Versioned response contract

Schema identifier: **`mep-evidence-reader/1`**. Machine-readable envelope/page schema: [evidence-reader-response.schema.json](evidence-reader-response.schema.json).

Every envelope contains project ID, operation, read time, database path, read-only protection description, currency snapshot metadata and `engineering_approval_created:false`. Profile envelopes contain `sections`, each with independent pagination. Domain envelopes use `result`. Provenance envelopes use `items` and explicit status.

Pages contain `status`, `items`, `total`, `limit`, `offset`, `next_offset`. `UNSUPPORTED` has `total:null` and a reason. `NO_RECORDED_EVIDENCE` has `total:0`, distinguishing absence in a supported scope from an unsupported relationship. `AVAILABLE` is retrieval availability, never engineering approval. Offset beyond the last row yields empty items with the true total. Fetch the same section using its `next_offset`, not a global profile cursor; the database snapshot remains stable during a reader context.

Fact projections preserve `evidence_id`, original values/units, recorded status and a `provenance` object:

- `database_record`: table, exact ID, cited version ID.
- `original_source`: registered original file/version ID, path, original SHA256 and archive path when established. Historical citations use the cited hash/version, not today's source head.
- `derived_document`: a separate conversion version, filename/path/SHA256, when saved metadata establishes a derived DOC→PDF chain. A PDF hash never replaces a DOC hash.
- `extracted_evidence_id`: core evidence ID, or null if absent.
- `source_locator`: saved page/clause/paragraph/worksheet/cell/CAD locator values, unknown fields null. `recorded_source`, source cells/fragments and derived artifact descriptors retain extra original details.
- `equipment_relationship`: existing profile relationship/status or null. Relationship fields on context/specification rows remain explicit candidates where recorded.
- `lineage_status`: recorded source chain or UNKNOWN. A consolidated profile/finding may have multiple source roots and no single original; inspect memberships or the finding's citation sides instead of inferring a source.
- `currency`: separate `source_currency` and `dependency_impact`, never an approval. Unavailable enrichment is UNKNOWN.

Matching relationships carry exact endpoint IDs, run ID, candidate evidence and recorded latest review event. Retrieve either endpoint's provenance explicitly. Identity descriptions/UC profiles retain their own row locator and UNKNOWN single-source lineage; they are projections over memberships, not primary observations. Limitations retain their audit/UC table and record ID.

`verified_printed_page` is populated only if the source explicitly records `printed_page_verified:true`. `printed_page_as_recorded` remains separate. Drawing installation location and area served are separate explicit fields. CAD coordinates are not physical installation positions. Controller/annotation/BOQ printed quantities are not promoted to physical equipment quantities.

## Active/history and review rules

Default native observations use the last import by SQLite row order for each `(file_id,slot)` whose analysis/version matches the current present registry head, following the existing matcher contract without invoking its writable Registry constructor. Historical imports and their parameters require `include_history=True` / `--history`; each native fact exposes `is_active`. This is registered-import currency, not approval of engineering revisions or verification of original bytes.

Current UC evidence requires the existing project-scoped `uc_equipment` view and `uc_runs`. A stale empty UC view does not fall back to historical UC tables. Native references can still be retrieved. Explicit history reads UC profiles from saved runs. No current-run definition or record count is hardcoded in the reader.

Source values remain original. Correction and approval events are exposed as saved events with actor/rationale/basis, not applied over original data. Full upstream review-basis revalidation is intentionally not invoked because its current storage path may write. Therefore a saved instance assertion is not promoted to a currently approved `Confirmed Instance`; it remains a reference with recorded identity kind and review information. Existing confirmed-entity basis revalidation is a known unsupported effective-status projection, not a missing human decision the reader can invent.

Matching rows are latest saved run candidates with active endpoints by default; `run_currency:UNKNOWN_NOT_REVALIDATED` makes clear that latest is not certified current. Candidate specification rules remain Pending/recorded status, never automatically applicable or approved. Declared family/system scope and conditions are returned. Core `tr_*` applicability schemas without UC links are explicitly unsupported in this first reader adapter, not substituted with keyword matches.

## Currency snapshot contract and limits

Supply an explicit Phase 01 `mep-source-currency/1` snapshot for the same project, maximum 64 MiB. Its path, SHA256, assessment time, original database path, scan limits and limitations are exposed. It can accompany a consistent DB copy because original IDs/hashes, rather than the copied filename, establish source identity. The cited original hash and current registered head hash must match the snapshot source basis before returning its saved source state. A changed registry basis returns UNKNOWN.

The snapshot is **not a fresh source-hash check**. Its age is visible and the user decides when to obtain a newer read-only Phase 01 assessment. No TTL or assertion of live currency is invented. Missing dependency nodes/lineage remain UNKNOWN; unrelated evidence is not invalidated. Snapshots may include POTENTIALLY_OUTDATED, UNKNOWN and UNAFFECTED_BY_DETECTED_SOURCE_CHANGES independently of source states CURRENT/MODIFIED/MISSING/UNVERIFIED.

Only known schema contracts are queried after column inspection; absent optional domains return explicit UNSUPPORTED. Core schema 2, a registered project ID and matching source root remain required by the existing read-only connection. Missing databases are not created. SQLite protections are mode=ro, query_only, a read transaction and an authorizer denying writes/DDL/PRAGMA mutation. No external dependencies, network calls or models are used.

Per-page limits bound linked row expansion, not the byte length of an individual stored paragraph/fact or the number of rows counted by SQL. Retained raw values may overlap native/UC context; no quantity sum or deduplication by apparent similarity is performed. No full coverage certification is implied. Additional linked drawing context is queried through `context --role drawing/electrical/bms`; it is not silently treated as a native occurrence. Project-wide limitation rows are not assumed to apply to every selected equipment.

## Synchronization

This reader is included in the release. On later installation updates, compare fresh source/destination hashes, back up destinations and preserve installation-specific routing/path changes. Preserve native agent/model definitions, all source/SQLite state and checkpoint history. Review existing code-signature/prerequisite compatibility through the established upgrade mechanism; no resets or retrospective approvals.
