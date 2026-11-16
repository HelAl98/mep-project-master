# P1-04 — Granular human decisions

Read original evidence, prepare explicit human-inspectable proposals, and append narrowly scoped human assertions to **existing `master_operator_events`**. No new table/schema/migration, workflow transitions, quantity inference, supplier issuance, native approval activation or P1-05 eligibility rules.

Read the original [state/review contract](state-and-review.md). Existing `reviews`, `registry_reviews` and `eq_reviews` retain their original authority and are never overwritten. This extension does not claim that its Accepted assertions are native project/package approvals.

## Storage choice

Core `reviews` records record-level quality/corrections. Registry reviews represent document/revision/relationship dispositions. Equipment reviews represent matcher-specific entities/parameters/proposals and enforce their own basis. None safely represents all four granular decisions, particularly a reviewed quantity with an explicit equipment scope or one clause linked to a family/type/item, using the currently available public write interfaces without storage-constructor side effects.

Reuse the master audit rather than creating a competing approval database: action `granular_human_decision_v1`, payload `mep-human-decision/1`. Only one INSERT into that existing table is permitted per recording. Existing no-update/no-delete audit triggers are required. Missing audit infrastructure blocks recording; the code never initializes/migrates it. A query-only reader needs no constructor migration.

The writer uses the existing validated connection helper, a short `BEGIN IMMEDIATE`, and a SQLite authorizer permitting INSERT into this audit table only. It does not use the writable Memory/Registry/Matcher constructors. It rereads the evidence and latest predecessor under the writer reservation, closes that read snapshot before inserting/committing, and refuses stale/concurrent proposals. Original evidence and legacy reviews remain intact.

## Decisions and supported targets

| Type | Exact target | Acceptance constraints |
|---|---|---|
| `identity` | `uc_profiles`, `eq_entities`, `eq_matches`, `eq_occurrences` | Explicit Reference/Type/Group/Physical Instance and registered supporting evidence. Physical Instance requires associated schedule evidence; repeated controller/drawing labels alone are insufficient. |
| `quantity` | `uc_profiles`, `eq_entities`, `eq_occurrences` | Explicit quantity, original printed unit, physical_count/scheduled_quantity. An associated source-linked schedule quantity field must equal the supplied value; no counts of annotations/pairs/controllers/panels or inferred sums. |
| `specification_applicability` | One `records` row with saved kind `specification` | Exact clause ID and explicit family/type/item scope; `assertion.applies:true`. One accepted assertion never changes all family candidates to approved. |
| `document_revision` | One `registry_revisions` or registered `versions` row | Established saved revision label matching `assertion.revision`. Derived conversion/hash equality is not approval of a contractual revision. |

Results: `Accepted`, `Rejected`, `Unresolved`. Rejected/Unresolved assertions do not need an invented accepted value. A quantity needs exact saved semantics: native schedule occurrence quantity+unit or a native quantity parameter. UC additional fields require explicit saved `quantity_basis:explicit_equipment_schedule`; vague/controller/BOQ semantics are not reinterpreted. Unsupported site-count/BOQ quantity contracts remain a reported gap; retain an unresolved decision or supply properly registered supported evidence, rather than inventing a physical count.

Quantity and identity are independent. A reviewed physical-count assertion does not confirm instance identity, a revision decision does not activate a version, and clause applicability does not approve wording or final procurement. The reader's original technical values never change.

## Preparing a request

```json
{
  "project_id": "ACTUAL_REGISTERED_PROJECT_ID",
  "decision_type": "quantity",
  "target": {"table": "uc_profiles", "id": "EXACT_SAVED_PROFILE_ID"},
  "result": "Accepted",
  "assertion": {"quantity": "4", "unit": "No.", "quantity_kind": "physical_count"},
  "reviewer": "Label supplied by the actual reviewer",
  "rationale": "Actual reviewer rationale for this exact evidence and value",
  "supporting_references": [{"table": "eq_parameters", "id": "EXACT_RELATED_QUANTITY_PARAMETER_ID"}]
}
```

This is an argument-shape example, not a real approval. The value must actually exist in related schedule evidence; a reviewer name or rationale does not make unsupported evidence sufficient.

Identity assertion: `{"identity_kind":"Type"}` (or Reference, Group, Physical Instance). Clause applicability: target one `records` ID plus `assertion:{"applies":true}` and a scope:

```json
{"kind":"family","family":"Exact stored family"}
```

or `{"kind":"type","table":"uc_profiles","id":"SAVED_TYPE_ID"}` / `{"kind":"item","table":"uc_profiles","id":"SAVED_ITEM_REFERENCE_ID"}`. Type scope must point to a saved type. Item scope does not silently confirm a physical instance. A family scope captures its saved members. Revision assertion: `{"revision":"EXACT_ESTABLISHED_LABEL"}`. Never infer a revision from a filename/hash.

`prepare_decision` returns `mep-human-decision-proposal/1` with the request, target label/key, exact original rows/parsed values, original and derived provenance, source heads, legacy review information, predecessor ID, prepared time and canonical SHA256. It records **nothing**. Up to 50 explicit supporting refs and a 16 MiB proposal bound prevent accidental massive review packets. Missing/foreign IDs and stale previous-decision IDs are errors.

## Human control and identity assurance

`record` requires an explicit intent flag **and** a direct interactive terminal confirmation of the exact proposal digest. The human must inspect the full prepared proposal and enter `RECORD <full SHA256>`. Agents must never supply this response, manufacture a reviewer label/rationale, or call recording automatically. Noninteractive flags, names, booleans and JSON pretending to be authorization are refused. Authorization objects are in-process, bound to the exact proposal, and single-use; changed proposals, stale evidence and concurrent predecessors are refused.

**This is a procedural human-action gate, not independent identity authentication.** A terminal/PTY can be automated by code with local privileges. The implementation does not pretend to distinguish malicious console automation or authenticate an external human account. Every real event explicitly records `independently_authenticated:false` and `RECORDED HUMAN ASSERTION — NOT INDEPENDENTLY AUTHENTICATED`. An organization needing verified identities must provide an authenticated authorization mechanism in later, separately authorized work. This phase adds no authentication service or GUI.

The private test seam produces `TEST ONLY — SIMULATED, NOT A HUMAN DECISION`, requires an explicitly labelled `FIXTURE_ONLY_` registered project and `decision_test_fixture:true`, and is not exposed through CLI. It cannot authorize an ordinary production project ID or an unchanged-ID copy. Synthetic test assertions are never represented as actual human decisions.

## Validity and history

Separate the saved result from the read-only projection:

- Unreviewed: no granular decision, or an explicit Unresolved result.
- Accepted / Rejected: latest recorded result with its required basis verified **as of** the explicitly identified source assessment/database read.
- Superseded: a later event explicitly references this one; original event remains immutable.
- Requires Revalidation: changed original/derived evidence, scope, legacy relevant review, registered source version/hash or changed/missing source / potentially outdated supporting dependency.
- Unknown Validity: missing lineage, unverified/unknown source/dependency information or absent/old source assessment.

A source assessment predating the decision cannot establish later validity. Obtain a separately requested Phase 01 assessment after the decision when a verified-as-of source status is needed; the reader never rehashes the project on every query. A newer assessment can be reused if the original evidence/version basis remains identical. The projection explicitly exposes its assessment time/identity/limits and is never a live-source or engineering approval certification. Changed basis requires a newly inspected human successor, not an automated reopen/approval event.

Supersession/rejection is a **new proposal then a new human-authorized event**. Previous accepted/rejected/unresolved records and supporting values remain present. Decision type, exact target and applicability scope define independence. Revision choices for the same original file share a history even when version targets differ. Latest-predecessor checks prevent parallel contradictory successors under the same key. No broad workflow status is created.

## Python API

```python
from master_project.source_currency import load_config
from master_project.evidence_reader import EvidenceReader
from master_project.human_decisions import (
    prepare_decision, prepare_successor,
    authorize_in_terminal, record_decision,
)

cfg = load_config("/absolute/project/rules/master.json")
with EvidenceReader(cfg, currency_snapshot="/absolute/phase01.json") as reader:
    pending = reader.list_pending_reviews(family="Exact stored family")
    fact = reader.inspect_evidence("EXACT_ID", table="eq_parameters")
    proposal = prepare_decision(reader, request)
    reader.write_json("/absolute/new-proposal.json", proposal)
    history = reader.get_decision_history("EXACT_PROFILE_ID", decision_type="quantity")
    checked = reader.check_decision_validity("EXACT_DECISION_ID")
    profile = reader.get_equipment_profile("EXACT_TAG", include_decisions=True)

# HUMAN RUNS/INTERACTS DIRECTLY, after inspecting that proposal:
authorization = authorize_in_terminal(proposal)
receipt = record_decision(cfg, proposal, authorization, currency_snapshot="/absolute/phase01.json")
```

Default `get_equipment_profile` is unchanged: `include_decisions=False`. Opt-in adds `human_decisions` without replacing sections or technical values. New reader methods remain query-only. `inspect_evidence` exposes exact original rows and parsed JSON, cited provenance and legacy reviews (not revalidated). It supports the tables above plus eq_parameters/uc_fields/uc_context/uc_findings. The original `mep-evidence-reader/1` envelope remains compatible; decision payloads have their own version.

Pending queue is a bounded **granular identity/quantity** equipment queue, not a completeness-certified project review register. A rejected granular decision resolves that queued assertion, without removing source evidence. Inspect exact clauses/revisions and prepare them explicitly; the queue does not expand thousands of clause candidates or presume their applicability. History pagination uses limit 1..200, offset, total and next_offset. Related histories match exact stored IDs/labels/family scopes, not fuzzy tags.

## CLI

Use the master development entry point with existing config, absolute paths and bundled Python `-X utf8 -B`:

```text
python /absolute/master.py --config /absolute/master.json human-review pending --family "Exact stored family"
python /absolute/master.py --config /absolute/master.json human-review inspect --table eq_parameters --reference EXACT_ID
python /absolute/master.py --config /absolute/master.json human-review history --reference EXACT_PROFILE_ID --decision-type quantity
python /absolute/master.py --config /absolute/master.json human-review prepare --request /absolute/request.json --output /absolute/new-proposal.json
python /absolute/master.py --config /absolute/master.json human-review validity --reference DECISION_ID --currency-snapshot /absolute/new-phase01.json
```

The actual human, in a direct terminal, records only after inspection:

```text
python /absolute/master.py --config /absolute/master.json human-review record --proposal /absolute/new-proposal.json --human-authorized
```

Use the same explicit snapshot when recording a proposal prepared with one, or reprepare against the intended snapshot. Changing source snapshot between inspection and recording requires a new proposal. `--human-authorized` is only an intent assertion; terminal confirmation remains required and is not authenticated identity.

For a successor, `human-review supersede --reference DECISION_ID --request reviewer-update.json --output new-successor.json` prepares a proposal using reviewer/rationale/result and optional replacement assertion. `human-review reject` prepares a Rejected successor using reviewer/rationale. Neither command writes a decision. Inspect and use `record` separately. Read/export/prepare do not initialize storage. `--output` creates a new JSON through the reader safety contract outside source/state/archive/master, never overwrites a report.

Existing evidence profile CLI also supports `evidence profile --reference EXACT_TAG --include-decisions`. No Approved RFQ mode, new final-package eligibility or automatic engineering approvals are introduced.

## Contract, validation and future synchronization

Machine-readable event shape: [human-decision.schema.json](human-decision.schema.json). Required data: decision type/result, target and scope, reviewer-provided identity, rationale, recorded timestamp, explicit support refs, original evidence/source-version basis, previous event ID, proposal digest and unauthenticated/test-labelled authorization. Existing audit ID/project/scope/actor/reason/time mirror the payload. The writer enforces the contract and constraints; a schema file alone is not full JSON Schema certification.

Recording returns a separate `mep-human-decision-receipt/1` response with the stored ID and `decision_validity:Unknown Validity`, `validity_checked:false`. Query the reader for actual validity. Receipts are not event records and are not validated against the event-only JSON Schema.

Bounded validation writes synthetic fixtures only. Production queries and compilation inspection remain read-only. Supplier Draft remains DRAFT-only and original quantities stay UNKNOWN; this phase deliberately does not feed granular Accepted assertions into procurement approval or overwrite its default compilation. Existing default Phase 02 profiles and Phase 03 compilations are compared directly for compatibility. Native full-workflow and authenticated-user interaction testing are not implied.

For any later installation update, compare current source/destination hashes, back up changed files, preserve installation-specific paths/routes, and retain native agents/models, SQLite/source state and checkpoints. Do not reset history or execute migrations. Code-fingerprint compatibility and final eligibility remain under the existing mechanism and future P1-05 scope.
