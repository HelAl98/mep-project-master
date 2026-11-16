# Read-only data integration and immutable generation records

The essential upstream interfaces were found in actual installed folders. SQLite requires core version 2 and registry/equipment/technical migration 1. The generator has **no migration** and no second database. It never calls index, map, compare, extraction, ingestion or approval actions.

## Compatibility facade

The connection uses URI `mode=ro`, `PRAGMA query_only=ON` and a read transaction for a consistent snapshot. Existing constructors are intentionally bypassed because they initialize schemas. Local subclasses reuse the inspected Registry, Matcher and Reviewer projection methods.

The Registry snapshot's `_revision_rows` boundary is replaced by a pure calculation of the exact candidate IDs using its existing key/provenance convention. No revision record is inserted; an absent stored candidate remains unapproved. Matcher `documents` does not commit the read transaction. Insert/transaction methods in the facades refuse writes, with SQLite read-only mode as a second boundary. No other private helper is repaired or changed. An upstream interface/schema change can fail this adapter and must be reviewed rather than guessed around.

The Reviewer snapshot recomputes view fingerprints/current statuses from stored records; it does **not** run comparisons or technical interpretation again. Existing stale-review detection, confirmed identity clusters, approved values and exact requirement/source matrices are reused. The correct existing reviewer config is necessary; defaulting to different rules makes the review stale, not approved.

## Grouping and counts

Existing physical-instance targets are already collapsed only by confirmed identity relationships. A single confirmed type membership and matching reviewed requirement/value signatures permit grouping. Incomplete or competing type membership leaves separate targets. Location/system/category and optional floor/scope further partition groups. Flow/head equality alone is never used to define a type.

BOQ rows are not manufactured into physical equipment. Their quantities can be associated through confirmed stored BOQ links, while unresolved category associations block final readiness. Source rows are identified by actual worksheet/page/table/row, not tag text; conflicting duplicate rows remain visible. Each source file retains its own totals, original units, scope and package/count basis. No automatic apportionment or duty/standby arithmetic is added.

Normalized values are taken only from existing approved parameter/interpretation projections. The generator performs no new engineering unit conversion. Original values/units and approval/source IDs remain alongside them. Mandatory parameter lists and type constraints add project requirements; they cannot weaken core readiness checks.

## Snapshot and output records

Each Package_Manifest records project/package/version IDs, actual entities/types/requirements, source references/revisions/hashes, engineering/registry review IDs, generation timestamp, readiness and independent generation status, component selection, source-state receipt, configuration/code/template hashes and every output checksum. The manifest is not recursively self-hashed.

Generation metadata is stored in filesystem JSON under a dedicated marked output root, outside immutable engineering evidence. No writable SQL metadata is needed. Package IDs identify a logical scope; version IDs also include source state, configuration, selected components, mode and implementation/template. Project-level receipts intentionally invalidate conservatively. Unchanged rescans with unchanged byte/analysis identity do not create a distinct receipt solely because a scan ID/time changed.

Earlier versions are immutable. Identical complete versions are reused only after validating path confinement and output hashes. Partial retries get new attempt paths; old partial files remain. Inspection identifies potential obsolescence and damage without changing historical readiness or claiming formal supersession/issue authority that was not recorded upstream.

Successful generation, reviewed technical information, formally approved source interpretations, RFQ-ready technical scope and a formally issued RFQ are distinct. All RFQ documents remain drafts; no external communication or issue workflow exists. A dedicated formal package release is not inferred from a source clause approval.
