# BOQ-first geometry checks and scoped procurement issue

This is an extension of the existing Master procurement command, not another
orchestrator or an engineering approval. Main prepares the options and source
selections internally after reading the actual evidence. Users give the project
request and field choices; they do not prepare mappings or run workflow stages.

## One request

1. Call `master.py procurement run --root SOURCE --state STATE` to initialize or
   reuse the Registry-owned SQLite database, extract available sources and emit
   draft schedules/specifications. An existing `--config CONFIG` precedes
   `procurement run` on resume. All paths resolve against that existing project.
2. Inspect the stored source/item/field/section evidence. Main prepares only the
   necessary mappings, section/system/topic candidate rules and geometry checks.
   Pass an options JSON with `procurement configure --request OPTIONS`, then
   resume. If these options are already known, `procurement run --request OPTIONS`
   saves and uses them on the first run. No human stage-selection prompt is needed.
3. Continue independent sources and groups even while another source is unreadable
   or a field choice is pending. Present real decisions as item + field + competing
   values + units + filename/page/sheet/row/clause/handle + why it matters. Main maps
   the user's sentence to exact current item/field/link IDs; only ambiguous identity
   or meaning requires clarification. Never infer a blanket source priority.
4. `procurement decide` records the actual statement and attribution, one field at
   a time. Omit `--source-link` only for an explicit unresolved disposition. These
   decisions are not upstream Reviewer or engineering certifications. Resume
   applies selections and reuses current extraction and render receipts.
5. `procurement status --item ID` returns the reviewed scope fingerprint. Only after
   actual user confirmation call `procurement issue --item ID --fingerprint HASH
   --statement ACTUAL_WORDS --actor ACTUAL_ATTRIBUTION`. Unresolved/missing fields,
   stale decisions, unreviewed clause applicability and selection omissions block
   the included items. `--exclude-item ID` explicitly removes that item from the
   reviewed issue scope and records the exclusion in the existing audit. Use the
   fingerprint of the full reviewed selection including excluded items. All excluded
   items/evidence/decisions remain in drafts/history. Independent ready items proceed.

The four original DDC skills remain guidance; Registry, ETL, PDF/spec extraction,
Matcher parameter normalization and native Reviewer classification/selection retain
their responsibilities. The existing six native specialist roles/settings remain
unchanged. Python never calls a model. Use the existing delegation policy only for
bounded interpretation when authorized; the Main Agent alone persists state.

## Specification candidates

`specification_rules` reuse the existing technical Reviewer's `classify` and
`requirement_selected` functions. Item selectors accept `categories`, `systems`
(the item's documented service) and `tags`. Requirement selectors accept the
native `sections` regex, `topics` literal topics, `technical_categories`,
`text_terms`, `file_ids`, `disciplines`, `systems` and `scopes`. Selectors are ANDed;
values within each selector are alternatives. Source system/scope selectors require
documented metadata; do not infer them from a nearby equipment tag.

Example Main-prepared candidate rule:

```json
{
  "specification_rules": [{
    "id": "common-installation",
    "basis": "Reviewed general installation section potentially applies to CHW",
    "items": {"systems": ["CHW"]},
    "requirements": {"sections": ["^23 05 00$"], "technical_categories": ["Installation"]}
  }],
  "specification_limit": 300
}
```

All rule hits remain candidate/conditional. Main uses `link --relation direct` only
after checking actual applicability evidence. No rule grants approval. The saved
selection includes examined/matched counts, exact omitted record IDs per item and
unlinked clause IDs. A limit never silently discards the unreviewed scope. Omitted
matches block issue for the affected item. Unlinked does not mean irrelevant.

## Supported geometry route

Direct native DWG conversion/measurement is **not verified or implemented here**.
The executable export route reads actual **UTF-8 ASCII DXF**, preserving original
entity group pairs and handles in the existing core `records` table through ETL.
It measures only model-space horizontal or vertical **LINE centerlines**. Binary
DXF, curves/polylines, nested blocks/Xrefs, sloped 3D lines and valve/fitting symbol
counts are unsupported. Unsupported selected entities make coverage partial or
unable to verify; merely extracting an entity is not measurement success.

Every configured check starts from one current BOQ quantity row. Its `scope` must
match the row's explicit `Scope` column or mapping `quantity_basis`. Identity must
include exact recorded service and size, with an evidence rationale. The selected
drawing hash, revision/title handle, scope, identity and layer must match. A
separate calibration LINE is checked against an exact cited length label; it never
contributes to measured quantity. Header `$INSUNITS`, declared units and calibration
must agree at **1:1 model scale**. The code never rescales geometry to fit the BOQ.

Example shape (replace all identifiers and bases with actual reviewed evidence):

```json
{
  "quantity_tolerances": {"pipe": {"relative": 0.10, "absolute": 0}},
  "quantity_checks": [{
    "id": "boq-line-2", "item_type": "pipe",
    "boq": {"file": "BOQ.xlsx", "sheet": "BOQ", "row": 2},
    "scope": "Level 1", "identity": {"service": "CHW", "size": "DN25"},
    "identity_basis": "Exact BOQ attributes and checked source-layer assignment",
    "coverage": {"complete": true, "missing": [], "basis": "Checked scope and all applicable drops/views"},
    "drawings": [{
      "file": "mechanical_R1.dxf", "sha256": "ACTUAL_64_CHARACTER_SHA256",
      "revision": "R1", "revision_handle": "A2", "revision_basis": "Checked applicable title revision",
      "scope": "Level 1", "identity": {"service": "CHW", "size": "DN25"},
      "identity_basis": "Checked geometry on the identified item layer",
      "layer": "CHW_DN25", "handles": ["B1"], "units": "mm", "scale": 1,
      "calibration": {"handle": "A0", "length": 1000, "unit": "mm",
                      "label_handle": "A1", "label": "CALIBRATION 1000 mm"},
      "risers_verified": false
    }]
  }]
}
```

The selected revision title must contain `REVISION: <revision>`. The calibration
label must preserve the exact recorded length and unit. These are documented checks
of the supplied export, not authentication of the designer or contractual approval.
Do not invent missing labels, calibration, scope or complete coverage.

Positive collinear overlap/reversed duplicates are excluded and downgrade coverage;
potential duplicate views are never summed into a full-scope conclusion. Separate
horizontal and explicitly verified vertical lengths are retained. Incomplete drops,
unreadable drawings, unknown units, stale hashes, mismatched identities/scopes and
unsupported selections remain explicit limitations.

The result stores original BOQ quantity, measured portion, unit, horizontal/riser
components, full-scope difference (null if partial), source handles/hashes/revision,
calibration, coverage and status separately. The BOQ is never overwritten. Statuses:
`close_within_review_tolerance`, `material_discrepancy`, `partial_check`,
`unable_to_verify`. Allowance is `max(absolute, abs(BOQ) * relative)`; absolute is in
the BOQ unit. Default relative tolerance is 10%, configurable by item type or the
project's `default` entry. This is a screening threshold, not engineering acceptance.

Results are appended to the existing `master_operator_events`; geometry remains in
core evidence, not a second database. Exact plan/source/code/tolerance fingerprints
reuse measurements. A changed quantity-check basis invalidates its field choice.

## Executed generic verification

The focused executable check is `scripts/tests/test_procurement_flow.py`. Use the
bundled Python with `-X utf8 -B`, `--fixture NEW_EXTERNAL_FOLDER` and
`--outputs EXTERNAL_SAMPLE_FOLDER`. Test data must stay outside the skill. It uses
the actual Master CLI, Registry, ETL, source records, Reviewer rule functions and
the real Excel/Word writer. The fixture is explicitly synthetic and creates no real
engineering approvals. `--resume-fixture` is only for continuing that same isolated
test after a code correction, not for a real project.

Executed coverage: 37/40 close, 370/40 discrepancy, 36 horizontal/40 with unmeasured
drops partial; wrong units/scope, duplicate views, unsupported ARC, separate verified
riser; header unit retention; queryable SQLite geometry/specification evidence;
body-material source choice in Excel and Word after resume; unresolved pressure
blocking issue; explicit valve exclusion permitting the confirmed pump scope;
unchanged extraction/measurement/render reuse; corrupt XLSX isolation; candidate
selection omissions and conditional facts; source-basis invalidation calculation.

The test does not qualify native DWG, arbitrary drawing geometry, OCR, complete
engineering design review or every legacy workflow route. Real project source
coverage, applicability and user confirmation remain necessary.
